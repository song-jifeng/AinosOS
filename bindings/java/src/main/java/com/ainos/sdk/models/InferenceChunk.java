package com.ainos.sdk.models;

import java.util.Objects;

/**
 * A single chunk from a streaming inference response.
 * <p>
 * During streaming inference, the daemon sends multiple {@code InferenceChunk}
 * messages, each containing a fragment of the generated text. The final chunk
 * has {@code done} set to {@code true}.
 * <p>
 * This class is immutable and thread-safe.
 */
public final class InferenceChunk {

    private final String chunk;
    private final boolean done;

    /**
     * Constructs a new inference chunk.
     *
     * @param chunk the text fragment for this chunk
     * @param done  whether this is the final chunk
     */
    public InferenceChunk(String chunk, boolean done) {
        this.chunk = Objects.requireNonNull(chunk, "chunk must not be null");
        this.done = done;
    }

    /**
     * Creates a final chunk (done=true) with the given text.
     *
     * @param chunk the final text fragment
     * @return a new InferenceChunk marked as done
     */
    public static InferenceChunk finalChunk(String chunk) {
        return new InferenceChunk(chunk, true);
    }

    /**
     * Creates an intermediate chunk (done=false) with the given text.
     *
     * @param chunk the text fragment
     * @return a new InferenceChunk
     */
    public static InferenceChunk of(String chunk) {
        return new InferenceChunk(chunk, false);
    }

    /** Returns the text fragment for this chunk. */
    public String getChunk() {
        return chunk;
    }

    /**
     * Returns whether this is the final chunk in the stream.
     *
     * @return {@code true} if this is the last chunk
     */
    public boolean isDone() {
        return done;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof InferenceChunk)) return false;
        InferenceChunk that = (InferenceChunk) o;
        return done == that.done && chunk.equals(that.chunk);
    }

    @Override
    public int hashCode() {
        return Objects.hash(chunk, done);
    }

    @Override
    public String toString() {
        return "InferenceChunk{"
                + "chunk='" + chunk + '\''
                + ", done=" + done
                + '}';
    }
}