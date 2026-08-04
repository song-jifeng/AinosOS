package com.ainos.sdk.stream;

import com.ainos.sdk.models.InferenceChunk;

import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/**
 * A reactive subscriber for streaming inference chunks.
 * <p>
 * Chunks are buffered in a blocking queue, allowing the subscriber
 * to process them asynchronously. This is useful for bridging the
 * streaming API with reactive frameworks or for manual polling.
 * <p>
 * Usage:
 * <pre>{@code
 * BufferedStreamSubscriber subscriber = new BufferedStreamSubscriber();
 * stream.subscribe(subscriber);
 *
 * // In another thread:
 * InferenceChunk chunk;
 * while ((chunk = subscriber.poll(1, TimeUnit.SECONDS)) != null) {
 *     System.out.print(chunk.getChunk());
 * }
 * }</pre>
 */
public class StreamSubscriber implements InferenceStream.StreamSubscriber {

    private final BlockingQueue<InferenceChunk> queue;
    private final AtomicBoolean completed;
    private final AtomicReference<Throwable> error;
    private final int capacity;

    /**
     * Constructs a StreamSubscriber with the specified buffer capacity.
     *
     * @param capacity the maximum number of chunks to buffer
     */
    public StreamSubscriber(int capacity) {
        this.capacity = capacity;
        this.queue = new LinkedBlockingQueue<>(capacity);
        this.completed = new AtomicBoolean(false);
        this.error = new AtomicReference<>(null);
    }

    /**
     * Constructs a StreamSubscriber with unlimited buffer capacity.
     */
    public StreamSubscriber() {
        this(Integer.MAX_VALUE);
    }

    @Override
    public void onStart() {
        // no-op
    }

    @Override
    public void onChunk(InferenceChunk chunk) {
        try {
            queue.put(chunk);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    @Override
    public void onComplete() {
        completed.set(true);
    }

    @Override
    public void onError(Throwable t) {
        error.set(t);
        completed.set(true);
    }

    /**
     * Polls for the next chunk, blocking if necessary.
     *
     * @return the next chunk, or {@code null} if the stream is complete
     * @throws RuntimeException if the stream encountered an error
     */
    public InferenceChunk take() {
        Throwable err = error.get();
        if (err != null) {
            throw new RuntimeException("Stream error", err);
        }
        if (completed.get() && queue.isEmpty()) {
            return null;
        }
        try {
            InferenceChunk chunk = queue.take();
            // Check for poison pill (null chunk means end of stream)
            if (chunk == null) {
                return null;
            }
            return chunk;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return null;
        }
    }

    /**
     * Polls for the next chunk with a timeout.
     *
     * @param timeout the maximum time to wait
     * @param unit    the time unit
     * @return the next chunk, or {@code null} if none available or stream complete
     * @throws RuntimeException if the stream encountered an error
     */
    public InferenceChunk poll(long timeout, TimeUnit unit) {
        Throwable err = error.get();
        if (err != null) {
            throw new RuntimeException("Stream error", err);
        }
        if (completed.get() && queue.isEmpty()) {
            return null;
        }
        try {
            return queue.poll(timeout, unit);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return null;
        }
    }

    /**
     * Returns whether the stream has completed (either successfully or with error).
     *
     * @return {@code true} if the stream is done
     */
    public boolean isCompleted() {
        return completed.get();
    }

    /**
     * Returns the error, if any, that occurred during streaming.
     *
     * @return the error, or {@code null} if no error
     */
    public Throwable getError() {
        return error.get();
    }

    /**
     * Returns the number of chunks currently buffered and available for polling.
     *
     * @return the queue size
     */
    public int bufferedCount() {
        return queue.size();
    }

    /**
     * Drains all remaining chunks from the buffer.
     *
     * @return an array of remaining chunks
     */
    public InferenceChunk[] drain() {
        return queue.toArray(new InferenceChunk[0]);
    }
}