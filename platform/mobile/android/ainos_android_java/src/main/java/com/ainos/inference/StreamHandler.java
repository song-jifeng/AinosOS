package com.ainos.inference;

import android.util.Log;

import com.ainos.models.InferenceResult;
import com.ainos.models.ModelInfo;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

/**
 * StreamHandler - Manages streaming inference sessions for token-by-token
 * generation. Supports multiple concurrent streams with thermal-aware pacing.
 */
public class StreamHandler {

    private static final String TAG = "StreamHandler";
    private static final long STREAM_TIMEOUT_MS = 60000;
    private static final int MAX_CONCURRENT_STREAMS = 4;

    // Stream event types matching C API
    public static final int EVENT_START = 0;
    public static final int EVENT_TOKEN = 1;
    public static final int EVENT_COMPLETE = 2;
    public static final int EVENT_ERROR = 3;
    public static final int EVENT_CANCELLED = 4;
    public static final int EVENT_PROGRESS = 5;
    public static final int EVENT_THERMAL_WARN = 6;

    private final InferenceEngine mInferenceEngine;
    private final Map<Long, StreamSession> mActiveStreams;
    private final AtomicLong mNextStreamId;
    private final AtomicBoolean mShutdown;

    /**
     * Stream event data.
     */
    public static class StreamEvent {
        public final int event;
        public final long sequence;
        public final String tokenData;
        public final float progress;
        public final int errorCode;
        public final String errorMessage;
        public final int thermalStatus;
        public final int batteryLevel;
        public final float inferenceTimeMs;
        public final long tokensSoFar;
        public final boolean isFinal;

        public StreamEvent(int event, long sequence, String tokenData,
                            float progress, int errorCode, String errorMessage,
                            int thermalStatus, int batteryLevel,
                            float inferenceTimeMs, long tokensSoFar,
                            boolean isFinal) {
            this.event = event;
            this.sequence = sequence;
            this.tokenData = tokenData;
            this.progress = progress;
            this.errorCode = errorCode;
            this.errorMessage = errorMessage;
            this.thermalStatus = thermalStatus;
            this.batteryLevel = batteryLevel;
            this.inferenceTimeMs = inferenceTimeMs;
            this.tokensSoFar = tokensSoFar;
            this.isFinal = isFinal;
        }
    }

    /**
     * Interface for stream event callbacks.
     */
    public interface StreamEventCallback {
        void onStreamEvent(long streamId, StreamEvent event);
    }

    /**
     * Internal stream session state.
     */
    private static class StreamSession {
        final long streamId;
        final String modelId;
        final ModelInfo modelInfo;
        final StreamEventCallback callback;
        final AtomicBoolean active;
        final AtomicBoolean cancelled;
        long startTime;
        long tokenCount;
        long lastTokenTime;
        Thread workerThread;

        StreamSession(long streamId, String modelId, ModelInfo modelInfo,
                       StreamEventCallback callback) {
            this.streamId = streamId;
            this.modelId = modelId;
            this.modelInfo = modelInfo;
            this.callback = callback;
            this.active = new AtomicBoolean(true);
            this.cancelled = new AtomicBoolean(false);
            this.startTime = System.currentTimeMillis();
            this.tokenCount = 0;
            this.lastTokenTime = startTime;
        }
    }

    /**
     * Create the stream handler.
     */
    public StreamHandler(InferenceEngine inferenceEngine) {
        mInferenceEngine = inferenceEngine;
        mActiveStreams = new ConcurrentHashMap<>();
        mNextStreamId = new AtomicLong(1);
        mShutdown = new AtomicBoolean(false);

        Log.i(TAG, "Stream handler initialized");
    }

    /**
     * Open a new streaming session.
     *
     * @param modelId  Model identifier
     * @param callback Callback for stream events
     * @return Stream ID, or -1 if failed
     */
    public long openStream(String modelId, ModelInfo modelInfo,
                            StreamEventCallback callback) {
        if (mShutdown.get()) return -1;

        if (mActiveStreams.size() >= MAX_CONCURRENT_STREAMS) {
            Log.w(TAG, "Max concurrent streams reached");
            return -1;
        }

        long streamId = mNextStreamId.getAndIncrement();
        if (streamId <= 0) {
            streamId = mNextStreamId.getAndIncrement();
        }

        StreamSession session = new StreamSession(streamId, modelId, modelInfo, callback);
        mActiveStreams.put(streamId, session);

        // Send start event
        if (callback != null) {
            callback.onStreamEvent(streamId, new StreamEvent(
                EVENT_START, 0, null, 0.0f,
                0, "", 0, 50, 0.0f, 0, false));
        }

        Log.i(TAG, "Stream opened: " + streamId + " for model " + modelId);
        return streamId;
    }

    /**
     * Send data to an active stream for processing.
     *
     * @param streamId Stream ID
     * @param data     Input data (e.g., prompt text)
     */
    public void sendData(long streamId, byte[] data) {
        StreamSession session = mActiveStreams.get(streamId);
        if (session == null || !session.active.get()) {
            Log.w(TAG, "Cannot send to inactive stream: " + streamId);
            return;
        }

        if (session.cancelled.get()) {
            Log.w(TAG, "Stream cancelled: " + streamId);
            return;
        }

        // Start processing in background
        session.workerThread = new Thread(() -> {
            processStream(session, data);
        }, "Stream-" + streamId);
        session.workerThread.setDaemon(true);
        session.workerThread.start();
    }

    /**
     * Close a stream session.
     *
     * @param streamId Stream ID to close
     */
    public void closeStream(long streamId) {
        StreamSession session = mActiveStreams.remove(streamId);
        if (session != null) {
            session.active.set(false);
            session.cancelled.set(true);
            if (session.workerThread != null && session.workerThread.isAlive()) {
                session.workerThread.interrupt();
            }
            Log.i(TAG, "Stream closed: " + streamId);
        }
    }

    /**
     * Check if a stream is active.
     */
    public boolean isStreamActive(long streamId) {
        StreamSession session = mActiveStreams.get(streamId);
        return session != null && session.active.get() && !session.cancelled.get();
    }

    /**
     * Cancel a stream.
     */
    public void cancelStream(long streamId) {
        StreamSession session = mActiveStreams.get(streamId);
        if (session != null) {
            session.cancelled.set(true);

            if (session.callback != null) {
                session.callback.onStreamEvent(streamId, new StreamEvent(
                    EVENT_CANCELLED, 0, null, 0.0f,
                    0, "", 0, 0, 0.0f, session.tokenCount, true));
            }
        }
    }

    /**
     * Get the number of active streams.
     */
    public int getActiveStreamCount() {
        return mActiveStreams.size();
    }

    /**
     * Shutdown the stream handler, closing all streams.
     */
    public void shutdown() {
        mShutdown.set(true);
        for (Long streamId : mActiveStreams.keySet()) {
            closeStream(streamId);
        }
        mActiveStreams.clear();
        Log.i(TAG, "Stream handler shut down");
    }

    /*========================================================================
     * Stream Processing
     *======================================================================*/

    private void processStream(StreamSession session, byte[] data) {
        try {
            String modelId = session.modelId;

            // Check timeout
            long elapsed = System.currentTimeMillis() - session.startTime;
            if (elapsed > STREAM_TIMEOUT_MS) {
                sendError(session, -6, "Stream timeout");
                return;
            }

            // Generate streaming tokens
            // In production, this would call the native streaming API
            String[] tokens = generateTokens(data);

            for (int i = 0; i < tokens.length; i++) {
                // Check for cancellation
                if (session.cancelled.get() || Thread.currentThread().isInterrupted()) {
                    sendError(session, -21, "Cancelled");
                    return;
                }

                // Check timeout
                elapsed = System.currentTimeMillis() - session.startTime;
                if (elapsed > STREAM_TIMEOUT_MS) {
                    sendError(session, -6, "Stream timeout after " + elapsed + "ms");
                    return;
                }

                // Send token event
                String token = tokens[i];
                float progress = (float)(i + 1) / tokens.length;
                session.tokenCount++;
                session.lastTokenTime = System.currentTimeMillis();

                if (session.callback != null) {
                    session.callback.onStreamEvent(session.streamId, new StreamEvent(
                        EVENT_TOKEN, i + 1, token, progress,
                        0, "", 0, 50,
                        System.currentTimeMillis() - session.startTime,
                        session.tokenCount, i == tokens.length - 1));
                }

                // Simulate generation delay
                Thread.sleep(30);
            }

            // Send complete event
            float totalTimeMs = System.currentTimeMillis() - session.startTime;
            if (session.callback != null) {
                session.callback.onStreamEvent(session.streamId, new StreamEvent(
                    EVENT_COMPLETE, tokens.length, null, 1.0f,
                    0, "", 0, 50,
                    totalTimeMs, session.tokenCount, true));
            }

        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            sendError(session, -21, "Interrupted");
        } catch (Exception e) {
            Log.e(TAG, "Stream processing error", e);
            sendError(session, -1, e.getMessage());
        } finally {
            // Clean up session
            session.active.set(false);
        }
    }

    private String[] generateTokens(byte[] data) {
        // In production, this would use the actual model
        // For now, return sample tokens
        return new String[]{
            "Hello", " I", " am", " Ainos", ",", " your",
            " AI", " assistant", ".", " How", " can", " I",
            " help", " you", " today", "?"
        };
    }

    private void sendError(StreamSession session, int errorCode, String message) {
        if (session.callback != null && session.active.get()) {
            session.callback.onStreamEvent(session.streamId, new StreamEvent(
                EVENT_ERROR, 0, null, 0.0f,
                errorCode, message, 0, 0,
                System.currentTimeMillis() - session.startTime,
                session.tokenCount, true));
        }
        session.active.set(false);
    }
}