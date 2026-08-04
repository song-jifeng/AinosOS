package com.ainos.sdk.models;

import java.util.Objects;

/**
 * Response from an LLM inference request.
 * <p>
 * Contains the generated text output along with usage statistics.
 * This class is immutable and thread-safe.
 */
public final class InferenceResponse {

    private final String output;
    private final int tokensGenerated;
    private final long inferenceMs;
    private final String source;

    /**
     * Constructs a new inference response.
     *
     * @param output          the generated text
     * @param tokensGenerated number of tokens produced
     * @param inferenceMs     wall-clock inference time in milliseconds
     * @param source          the inference source ({@code "local"} or {@code "cloud"})
     */
    public InferenceResponse(String output, int tokensGenerated, long inferenceMs, String source) {
        this.output = Objects.requireNonNull(output, "output must not be null");
        this.tokensGenerated = tokensGenerated;
        this.inferenceMs = inferenceMs;
        this.source = Objects.requireNonNull(source, "source must not be null");
    }

    /**
     * Creates a minimal inference response with just the output text.
     *
     * @param output the generated text
     * @return a new InferenceResponse
     */
    public static InferenceResponse of(String output) {
        return new InferenceResponse(output, 0, 0, "local");
    }

    /** Returns the generated text output. */
    public String getOutput() {
        return output;
    }

    /** Returns the number of tokens produced. */
    public int getTokensGenerated() {
        return tokensGenerated;
    }

    /** Returns the wall-clock inference time in milliseconds. */
    public long getInferenceMs() {
        return inferenceMs;
    }

    /**
     * Returns the inference source.
     *
     * @return {@code "local"} for local inference, {@code "cloud"} for cloud API
     */
    public String getSource() {
        return source;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof InferenceResponse)) return false;
        InferenceResponse that = (InferenceResponse) o;
        return tokensGenerated == that.tokensGenerated
                && inferenceMs == that.inferenceMs
                && output.equals(that.output)
                && source.equals(that.source);
    }

    @Override
    public int hashCode() {
        return Objects.hash(output, tokensGenerated, inferenceMs, source);
    }

    @Override
    public String toString() {
        return "InferenceResponse{"
                + "output='" + output + '\''
                + ", tokensGenerated=" + tokensGenerated
                + ", inferenceMs=" + inferenceMs
                + ", source='" + source + '\''
                + '}';
    }
}