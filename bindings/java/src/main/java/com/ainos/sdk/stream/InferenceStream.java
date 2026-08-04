package com.ainos.sdk.stream;

import com.ainos.sdk.models.AinosConnectionException;
import com.ainos.sdk.models.AinosInferenceException;
import com.ainos.sdk.models.AinosTimeoutException;
import com.ainos.sdk.models.InferenceChunk;
import com.ainos.sdk.transport.JsonCodec;
import com.ainos.sdk.transport.TcpTransport;

import java.util.Iterator;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Objects;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/**
 * A streaming inference session that reads chunks from the daemon as they arrive.
 * <p>
 * This class implements {@link Iterable} so it can be used in enhanced for-loops,
 * and it also provides a reactive {@link Subscriber} API for push-based consumption.
 * <p>
 * The stream is consumed once. After all chunks have been read, the underlying
 * transport resources are released.
 * <p>
 * Usage:
 * <pre>{@code
 * try (InferenceStream stream = client.inferStream(request)) {
 *     for (InferenceChunk chunk : stream) {
 *         System.out.print(chunk.getChunk());
 *         if (chunk.isDone()) break;
 *     }
 * }
 * }</pre>
 */
public class InferenceStream implements Iterable<InferenceChunk>, AutoCloseable {

    private final StreamReader reader;
    private final AtomicBoolean started;
    private final AtomicBoolean closed;

    /**
     * Constructs a new InferenceStream.
     *
     * @param reader the underlying stream reader
     */
    public InferenceStream(StreamReader reader) {
        this.reader = Objects.requireNonNull(reader, "reader must not be null");
        this.started = new AtomicBoolean(false);
        this.closed = new AtomicBoolean(false);
    }

    /**
     * Reads the next chunk from the stream, blocking if necessary.
     *
     * @return the next chunk, or {@code null} if the stream is exhausted
     * @throws AinosConnectionException if the connection is lost
     * @throws AinosTimeoutException    if the read times out
     * @throws AinosInferenceException  if the daemon returns an error
     */
    public InferenceChunk next()
            throws AinosConnectionException, AinosTimeoutException, AinosInferenceException {
        if (closed.get()) {
            return null;
        }
        started.set(true);
        return reader.readChunk();
    }

    /**
     * Reads the next chunk with a timeout.
     *
     * @param timeout the maximum time to wait
     * @param unit    the time unit of the timeout argument
     * @return the next chunk, or {@code null} if the stream is exhausted or timed out
     * @throws AinosConnectionException if the connection is lost
     * @throws AinosTimeoutException    if the timeout expires
     * @throws AinosInferenceException  if the daemon returns an error
     */
    public InferenceChunk next(long timeout, TimeUnit unit)
            throws AinosConnectionException, AinosTimeoutException, AinosInferenceException {
        if (closed.get()) {
            return null;
        }
        started.set(true);
        return reader.readChunk(timeout, unit);
    }

    /**
     * Returns an iterator over the chunks in this stream.
     * <p>
     * The iterator reads chunks lazily as they arrive from the daemon.
     * The stream can only be iterated once.
     *
     * @return a lazy chunk iterator
     */
    @Override
    public Iterator<InferenceChunk> iterator() {
        if (started.getAndSet(true)) {
            throw new IllegalStateException("Stream has already been consumed");
        }
        return new ChunkIterator();
    }

    /**
     * Subscribes a consumer to receive chunks as they arrive.
     * <p>
     * The subscription runs on the calling thread and blocks until the stream
     * is exhausted. For background consumption, wrap the call in a thread.
     *
     * @param subscriber the subscriber to receive chunks
     */
    public void subscribe(StreamSubscriber subscriber) {
        Objects.requireNonNull(subscriber, "subscriber must not be null");
        started.set(true);
        try {
            subscriber.onStart();
            while (!closed.get()) {
                try {
                    InferenceChunk chunk = reader.readChunk();
                    if (chunk == null) {
                        break;
                    }
                    subscriber.onChunk(chunk);
                    if (chunk.isDone()) {
                        break;
                    }
                } catch (AinosConnectionException | AinosTimeoutException e) {
                    subscriber.onError(e);
                    return;
                } catch (AinosInferenceException e) {
                    subscriber.onError(e);
                    return;
                }
            }
            subscriber.onComplete();
        } catch (Exception e) {
            subscriber.onError(e);
        }
    }

    /**
     * Closes the stream and releases underlying resources.
     */
    @Override
    public void close() {
        if (closed.compareAndSet(false, true)) {
            reader.close();
        }
    }

    /**
     * Returns whether this stream has been closed.
     *
     * @return {@code true} if closed
     */
    public boolean isClosed() {
        return closed.get();
    }

    // -----------------------------------------------------------------------
    // Chunk iterator
    // -----------------------------------------------------------------------

    private class ChunkIterator implements Iterator<InferenceChunk> {

        private InferenceChunk nextChunk;
        private boolean fetched;
        private boolean exhausted;
        private boolean doneReceived;

        @Override
        public boolean hasNext() {
            if (exhausted) return false;
            if (!fetched) {
                fetchNext();
            }
            return !exhausted;
        }

        @Override
        public InferenceChunk next() {
            if (exhausted) {
                throw new NoSuchElementException("No more chunks in stream");
            }
            if (!fetched) {
                fetchNext();
            }
            if (exhausted) {
                throw new NoSuchElementException("No more chunks in stream");
            }
            fetched = false;
            // Mark as exhausted after the final chunk is consumed
            if (nextChunk.isDone()) {
                exhausted = true;
            }
            return nextChunk;
        }

        private void fetchNext() {
            try {
                InferenceChunk chunk = reader.readChunk();
                if (chunk == null) {
                    exhausted = true;
                } else {
                    nextChunk = chunk;
                    fetched = true;
                }
            } catch (AinosConnectionException | AinosTimeoutException | AinosInferenceException e) {
                throw new RuntimeException("Stream error: " + e.getMessage(), e);
            }
        }
    }

    // -----------------------------------------------------------------------
    // Subscriber interface
    // -----------------------------------------------------------------------

    /**
     * Reactive subscriber for receiving streaming inference chunks.
     * <p>
     * Implement this interface to receive push-based notifications as
     * chunks arrive from the daemon.
     */
    public interface StreamSubscriber {

        /**
         * Called when the stream starts.
         */
        default void onStart() {
        }

        /**
         * Called for each chunk received.
         *
         * @param chunk the received chunk
         */
        void onChunk(InferenceChunk chunk);

        /**
         * Called when the stream completes successfully.
         */
        default void onComplete() {
        }

        /**
         * Called when an error occurs during streaming.
         *
         * @param error the error that occurred
         */
        default void onError(Throwable error) {
        }
    }
}