package com.ainos.inference;

import android.content.Context;
import android.util.Log;

import com.ainos.AinosNative;
import com.ainos.models.InferenceResult;
import com.ainos.models.ModelInfo;
import com.ainos.utils.ThermalManager;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.FloatBuffer;
import java.nio.IntBuffer;
import java.nio.ShortBuffer;
import java.util.Arrays;
import java.util.Map;
import java.util.concurrent.CancellationException;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * InferenceEngine - Core AI inference engine for the Ainos platform.
 * Manages model execution, delegates to hardware acceleration, and handles
 * thermal-aware scheduling.
 */
public class InferenceEngine {

    private static final String TAG = "InferenceEngine";
    private static final int DEFAULT_TIMEOUT_MS = 30000;
    private static final int MAX_BATCH_SIZE = 8;
    private static final int TOKEN_WARMUP_COUNT = 3;

    private final Context mContext;
    private final NNDelegate mNNDelegate;
    private final ThermalManager mThermalManager;

    private final ExecutorService mInferenceExecutor;
    private final Map<String, Future<?>> mRunningTasks;
    private final Map<String, ModelSession> mActiveSessions;
    private final AtomicInteger mTaskCounter;
    private final AtomicBoolean mShutdown;

    private InferenceConfig mConfig;
    private InferenceCallback mGlobalCallback;

    /**
     * Interface for inference completion callbacks.
     */
    public interface InferenceCallback {
        void onInferenceComplete(String modelId, InferenceResult result);
        void onInferenceError(String modelId, int status, String message);
    }

    /**
     * Interface for streaming inference callbacks.
     */
    public interface StreamCallback {
        void onToken(String modelId, String token, int sequence);
        void onStreamComplete(String modelId, InferenceResult result);
        void onStreamError(String modelId, int status, String message);
        void onStreamThermalWarning(String modelId, int thermalStatus);
    }

    /**
     * Inference engine configuration.
     */
    public static class InferenceConfig {
        public int backend = 0; // AUTO
        public int numThreads = 4;
        public boolean useGpu = true;
        public boolean useNpu = false;
        public boolean allowFp16 = true;
        public boolean enableQuantization = true;
        public int thermalThreshold = 2; // HOT
        public int batteryThreshold = 15;
        public int maxBatchSize = 1;
        public int timeoutMs = 30000;
        public String delegateOptions = "";

        public InferenceConfig() {}

        public InferenceConfig(int backend, int numThreads, boolean useGpu,
                                boolean useNpu, boolean allowFp16) {
            this.backend = backend;
            this.numThreads = numThreads;
            this.useGpu = useGpu;
            this.useNpu = useNpu;
            this.allowFp16 = allowFp16;
        }
    }

    /**
     * Internal model session tracking.
     */
    private static class ModelSession {
        final String modelId;
        final ModelInfo modelInfo;
        final AtomicBoolean loaded;
        final AtomicBoolean running;
        long lastAccessTime;
        int loadCount;

        ModelSession(String modelId, ModelInfo modelInfo) {
            this.modelId = modelId;
            this.modelInfo = modelInfo;
            this.loaded = new AtomicBoolean(false);
            this.running = new AtomicBoolean(false);
            this.lastAccessTime = System.currentTimeMillis();
            this.loadCount = 0;
        }
    }

    /**
     * Create the inference engine.
     */
    public InferenceEngine(Context context, NNDelegate nnDelegate, ThermalManager thermalManager) {
        mContext = context;
        mNNDelegate = nnDelegate;
        mThermalManager = thermalManager;

        mInferenceExecutor = Executors.newFixedThreadPool(
            Runtime.getRuntime().availableProcessors(),
            r -> {
                Thread t = new Thread(r, "AinosInference-" + mTaskCounter.incrementAndGet());
                t.setPriority(Thread.MAX_PRIORITY);
                return t;
            });

        mRunningTasks = new ConcurrentHashMap<>();
        mActiveSessions = new ConcurrentHashMap<>();
        mTaskCounter = new AtomicInteger(0);
        mShutdown = new AtomicBoolean(false);

        mConfig = new InferenceConfig();

        Log.i(TAG, "Inference engine initialized with " +
              Runtime.getRuntime().availableProcessors() + " threads");
    }

    /**
     * Update the inference configuration.
     */
    public void setConfig(InferenceConfig config) {
        mConfig = config;
        Log.i(TAG, "Config updated: backend=" + config.backend +
              " threads=" + config.numThreads +
              " gpu=" + config.useGpu);
    }

    /**
     * Set the global inference callback.
     */
    public void setGlobalCallback(InferenceCallback callback) {
        mGlobalCallback = callback;
    }

    /**
     * Load a model into memory.
     *
     * @param modelInfo Model to load
     * @return true if loaded successfully
     */
    public boolean loadModel(ModelInfo modelInfo) {
        if (mShutdown.get()) return false;

        String modelId = modelInfo.modelId;

        // Check if already loaded
        ModelSession session = mActiveSessions.get(modelId);
        if (session != null && session.loaded.get()) {
            session.lastAccessTime = System.currentTimeMillis();
            return true;
        }

        Log.i(TAG, "Loading model: " + modelId);

        try {
            // Initialize NN delegate for this model
            if (!mNNDelegate.initializeForModel(modelInfo)) {
                Log.e(TAG, "Failed to initialize NN delegate for " + modelId);
                return false;
            }

            // Create session
            session = new ModelSession(modelId, modelInfo);
            mActiveSessions.put(modelId, session);

            // Load native model
            int result = AinosNative.nativeModelLoad(modelId);
            if (result != 0) {
                Log.e(TAG, "Native model load failed: " + result);
                mActiveSessions.remove(modelId);
                return false;
            }

            session.loaded.set(true);
            session.loadCount++;
            session.lastAccessTime = System.currentTimeMillis();

            modelInfo.state = ModelInfo.STATE_LOADED;
            Log.i(TAG, "Model loaded: " + modelId);
            return true;

        } catch (Exception e) {
            Log.e(TAG, "Failed to load model: " + modelId, e);
            mActiveSessions.remove(modelId);
            return false;
        }
    }

    /**
     * Unload a model from memory.
     *
     * @param modelId Model to unload
     */
    public void unloadModel(String modelId) {
        ModelSession session = mActiveSessions.remove(modelId);
        if (session != null) {
            // Cancel any running tasks
            Future<?> task = mRunningTasks.remove(modelId);
            if (task != null && !task.isDone()) {
                task.cancel(true);
            }

            session.loaded.set(false);
            AinosNative.nativeModelUnload(modelId);
            Log.i(TAG, "Model unloaded: " + modelId);
        }
    }

    /**
     * Check if a model is loaded.
     */
    public boolean isModelLoaded(String modelId) {
        ModelSession session = mActiveSessions.get(modelId);
        return session != null && session.loaded.get();
    }

    /**
     * Run synchronous inference on a model.
     *
     * @param modelInfo Model to run
     * @param inputData Input tensor data
     * @return Inference result
     */
    public InferenceResult runInference(ModelInfo modelInfo, byte[] inputData) {
        return runInference(modelInfo, inputData, DEFAULT_TIMEOUT_MS);
    }

    /**
     * Run synchronous inference with timeout.
     *
     * @param modelInfo Model to run
     * @param inputData Input tensor data
     * @param timeoutMs Timeout in milliseconds
     * @return Inference result
     */
    public InferenceResult runInference(ModelInfo modelInfo, byte[] inputData, int timeoutMs) {
        if (mShutdown.get()) {
            return InferenceResult.createError(-1, "Engine shut down");
        }

        String modelId = modelInfo.modelId;

        // Check thermal conditions
        int thermalStatus = mThermalManager.getCurrentStatus();
        if (thermalStatus >= mConfig.thermalThreshold) {
            Log.w(TAG, "Inference throttled: thermal=" + thermalStatus);
            return InferenceResult.createError(-9, "Thermal throttled");
        }

        // Check battery
        if (AinosNative.nativeGetBatteryLevel() < mConfig.batteryThreshold &&
            !AinosNative.nativeIsCharging()) {
            Log.w(TAG, "Inference blocked: battery low");
            return InferenceResult.createError(-10, "Battery low");
        }

        // Ensure model is loaded
        if (!isModelLoaded(modelId)) {
            if (!loadModel(modelInfo)) {
                return InferenceResult.createError(-12, "Model load failed");
            }
        }

        long startTime = System.nanoTime();
        long preprocessStart = System.nanoTime();

        // Preprocess input data
        byte[] processedInput = preprocessInput(inputData, modelInfo);

        float preprocessTimeMs = (System.nanoTime() - preprocessStart) / 1_000_000.0f;

        // Allocate output buffer
        byte[] outputBuffer = new byte[1024 * 1024]; // 1MB output buffer

        long inferenceStart = System.nanoTime();

        // Run native inference
        int result = AinosNative.nativeRunInference(modelId, processedInput, outputBuffer);

        float inferenceTimeMs = (System.nanoTime() - inferenceStart) / 1_000_000.0f;

        long postprocessStart = System.nanoTime();

        // Postprocess
        byte[] outputData = postprocessOutput(outputBuffer, modelInfo);

        float postprocessTimeMs = (System.nanoTime() - postprocessStart) / 1_000_000.0f;
        float totalTimeMs = (System.nanoTime() - startTime) / 1_000_000.0f;

        // Calculate tokens (simplified - assume 1 token per 50ms of inference)
        long tokensGenerated = Math.max(1, (long)(inferenceTimeMs / 50.0f));
        float tokensPerSecond = tokensGenerated / (inferenceTimeMs / 1000.0f);

        // Update session
        ModelSession session = mActiveSessions.get(modelId);
        if (session != null) {
            session.lastAccessTime = System.currentTimeMillis();
        }

        // Update model info
        modelInfo.lastUsedTimestamp = System.currentTimeMillis();

        if (result != 0) {
            InferenceResult errorResult = InferenceResult.createError(result,
                "Inference failed: " + AinosNative.Error.toString(result));
            if (mGlobalCallback != null) {
                mGlobalCallback.onInferenceError(modelId, result, errorResult.errorMessage);
            }
            return errorResult;
        }

        InferenceResult inferenceResult = new InferenceResult(
            outputData, outputData.length,
            inferenceTimeMs, preprocessTimeMs, postprocessTimeMs, totalTimeMs,
            tokensGenerated, tokensPerSecond,
            thermalStatus, AinosNative.nativeGetBatteryLevel(),
            false, "");

        if (mGlobalCallback != null) {
            mGlobalCallback.onInferenceComplete(modelId, inferenceResult);
        }

        return inferenceResult;
    }

    /**
     * Run inference asynchronously.
     *
     * @param modelInfo  Model to run
     * @param inputData  Input tensor data
     * @param callback   Callback for completion
     */
    public void runInferenceAsync(ModelInfo modelInfo, byte[] inputData,
                                   InferenceCallback callback) {
        if (mShutdown.get()) {
            if (callback != null) {
                callback.onInferenceError(modelInfo.modelId, -1, "Engine shut down");
            }
            return;
        }

        String modelId = modelInfo.modelId;

        Future<?> existing = mRunningTasks.get(modelId);
        if (existing != null && !existing.isDone()) {
            if (callback != null) {
                callback.onInferenceError(modelId, -20, "Inference already running");
            }
            return;
        }

        Future<?> task = mInferenceExecutor.submit(() -> {
            try {
                InferenceResult result = runInference(modelInfo, inputData);
                if (callback != null) {
                    if (result.isSuccess()) {
                        callback.onInferenceComplete(modelId, result);
                    } else {
                        callback.onInferenceError(modelId, result.status, result.errorMessage);
                    }
                }
            } catch (Exception e) {
                Log.e(TAG, "Async inference failed", e);
                if (callback != null) {
                    callback.onInferenceError(modelId, -1, e.getMessage());
                }
            } finally {
                mRunningTasks.remove(modelId);
            }
        });

        mRunningTasks.put(modelId, task);
    }

    /**
     * Run streaming inference (token-by-token generation).
     *
     * @param modelInfo       Model to run
     * @param inputData       Input prompt data
     * @param streamCallback  Callback for streaming tokens
     */
    public void runStreamInference(ModelInfo modelInfo, byte[] inputData,
                                    StreamCallback streamCallback) {
        if (mShutdown.get()) {
            if (streamCallback != null) {
                streamCallback.onStreamError(modelInfo.modelId, -1, "Engine shut down");
            }
            return;
        }

        String modelId = modelInfo.modelId;

        mInferenceExecutor.submit(() -> {
            try {
                // Check thermal conditions
                int thermalStatus = mThermalManager.getCurrentStatus();
                if (thermalStatus >= 3) { // Critical
                    if (streamCallback != null) {
                        streamCallback.onStreamThermalWarning(modelId, thermalStatus);
                    }
                }

                // Ensure model is loaded
                if (!isModelLoaded(modelId)) {
                    if (!loadModel(modelInfo)) {
                        if (streamCallback != null) {
                            streamCallback.onStreamError(modelId, -12, "Model load failed");
                        }
                        return;
                    }
                }

                long startTime = System.nanoTime();
                long totalTokens = 0;

                // Simulate streaming tokens
                String[] sampleTokens = {
                    "Hello", " I", " am", " Ainos", ",", " your", " AI",
                    " assistant", ".", " How", " can", " I", " help",
                    " you", " today", "?"
                };

                for (int i = 0; i < sampleTokens.length; i++) {
                    if (Thread.currentThread().isInterrupted()) {
                        if (streamCallback != null) {
                            streamCallback.onStreamError(modelId, -21, "Cancelled");
                        }
                        return;
                    }

                    // Check thermal during streaming
                    if (i % 5 == 0) {
                        int currentThermal = mThermalManager.getCurrentStatus();
                        if (currentThermal >= 3 && streamCallback != null) {
                            streamCallback.onStreamThermalWarning(modelId, currentThermal);
                        }
                    }

                    // Simulate generation time
                    Thread.sleep(50);

                    if (streamCallback != null) {
                        streamCallback.onToken(modelId, sampleTokens[i], i);
                    }
                    totalTokens++;
                }

                float totalTimeMs = (System.nanoTime() - startTime) / 1_000_000.0f;
                float tokensPerSecond = totalTokens / (totalTimeMs / 1000.0f);

                InferenceResult result = new InferenceResult(
                    null, 0, totalTimeMs, totalTimeMs,
                    totalTokens, tokensPerSecond);

                if (streamCallback != null) {
                    streamCallback.onStreamComplete(modelId, result);
                }

            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                if (streamCallback != null) {
                    streamCallback.onStreamError(modelId, -21, "Interrupted");
                }
            } catch (Exception e) {
                Log.e(TAG, "Stream inference failed", e);
                if (streamCallback != null) {
                    streamCallback.onStreamError(modelId, -1, e.getMessage());
                }
            }
        });
    }

    /**
     * Cancel a running inference.
     *
     * @param modelId Model to cancel inference for
     */
    public void cancelInference(String modelId) {
        Future<?> task = mRunningTasks.remove(modelId);
        if (task != null && !task.isDone()) {
            task.cancel(true);
            AinosNative.nativeRunInference(modelId, null, null); // Signal cancel
            Log.i(TAG, "Inference cancelled: " + modelId);
        }
    }

    /**
     * Cancel all running inferences.
     */
    public void cancelAll() {
        for (Map.Entry<String, Future<?>> entry : mRunningTasks.entrySet()) {
            if (!entry.getValue().isDone()) {
                entry.getValue().cancel(true);
            }
        }
        mRunningTasks.clear();
        Log.i(TAG, "All inferences cancelled");
    }

    /**
     * Unload all models.
     */
    public void unloadAllModels() {
        for (String modelId : mActiveSessions.keySet()) {
            unloadModel(modelId);
        }
        mActiveSessions.clear();
        Log.i(TAG, "All models unloaded");
    }

    /**
     * Shutdown the inference engine.
     */
    public void shutdown() {
        mShutdown.set(true);
        cancelAll();
        unloadAllModels();
        mInferenceExecutor.shutdownNow();
        try {
            mInferenceExecutor.awaitTermination(5, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        Log.i(TAG, "Inference engine shut down");
    }

    /**
     * Get the number of active model sessions.
     */
    public int getActiveSessionCount() {
        return mActiveSessions.size();
    }

    /**
     * Get the number of running tasks.
     */
    public int getRunningTaskCount() {
        return mRunningTasks.size();
    }

    /*========================================================================
     * Input/Output Processing
     *======================================================================*/

    private byte[] preprocessInput(byte[] inputData, ModelInfo modelInfo) {
        // In production, this would handle:
        // - Tokenization for LLM models
        // - Image preprocessing for vision models
        // - Audio preprocessing for audio models
        // - Normalization, resizing, format conversion

        switch (modelInfo.type) {
            case ModelInfo.TYPE_LLM:
                return preprocessTextInput(inputData);

            case ModelInfo.TYPE_VISION:
                return preprocessImageInput(inputData);

            case ModelInfo.TYPE_AUDIO:
                return preprocessAudioInput(inputData);

            case ModelInfo.TYPE_EMBEDDING:
                return preprocessEmbeddingInput(inputData);

            default:
                return inputData;
        }
    }

    private byte[] preprocessTextInput(byte[] inputData) {
        // Tokenization placeholder
        // In production, use SentencePiece or tokenizer
        if (inputData == null) return new byte[0];
        return inputData;
    }

    private byte[] preprocessImageInput(byte[] inputData) {
        // Image preprocessing placeholder
        if (inputData == null) return new byte[0];
        return inputData;
    }

    private byte[] preprocessAudioInput(byte[] inputData) {
        // Audio preprocessing placeholder
        if (inputData == null) return new byte[0];
        return inputData;
    }

    private byte[] preprocessEmbeddingInput(byte[] inputData) {
        if (inputData == null) return new byte[0];
        return inputData;
    }

    private byte[] postprocessOutput(byte[] outputData, ModelInfo modelInfo) {
        // In production, this would handle:
        // - Detokenization for LLM models
        // - Image decoding for vision models
        // - Audio decoding for audio models

        switch (modelInfo.type) {
            case ModelInfo.TYPE_LLM:
                return postprocessTextOutput(outputData);

            case ModelInfo.TYPE_VISION:
                return postprocessVisionOutput(outputData);

            case ModelInfo.TYPE_AUDIO:
                return postprocessAudioOutput(outputData);

            default:
                return outputData;
        }
    }

    private byte[] postprocessTextOutput(byte[] outputData) {
        if (outputData == null) return new byte[0];
        return outputData;
    }

    private byte[] postprocessVisionOutput(byte[] outputData) {
        if (outputData == null) return new byte[0];
        return outputData;
    }

    private byte[] postprocessAudioOutput(byte[] outputData) {
        if (outputData == null) return new byte[0];
        return outputData;
    }
}