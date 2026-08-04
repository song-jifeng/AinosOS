package com.ainos.sdk.models;

import java.util.Objects;
import java.util.Optional;

/**
 * Request parameters for an LLM inference operation.
 * <p>
 * This class is immutable and should be constructed using the {@link Builder}.
 *
 * <pre>{@code
 * InferenceRequest req = InferenceRequest.builder()
 *     .prompt("Hello, Ainos!")
 *     .model("phi-3-mini")
 *     .temperature(0.7)
 *     .maxTokens(512)
 *     .sessionId("sess-001")
 *     .build();
 * }</pre>
 */
public final class InferenceRequest {

    private final String prompt;
    private final String model;
    private final Double temperature;
    private final Integer maxTokens;
    private final String sessionId;

    private InferenceRequest(Builder builder) {
        this.prompt = Objects.requireNonNull(builder.prompt, "prompt must not be null");
        this.model = builder.model != null ? builder.model : "default";
        this.temperature = builder.temperature;
        this.maxTokens = builder.maxTokens;
        this.sessionId = builder.sessionId;
    }

    /**
     * Creates a new {@link Builder} for constructing an {@code InferenceRequest}.
     *
     * @return a new builder instance
     */
    public static Builder builder() {
        return new Builder();
    }

    /**
     * Creates a simple inference request with just a prompt, using the default model.
     *
     * @param prompt the input prompt text
     * @return a new InferenceRequest
     * @throws NullPointerException if prompt is null
     */
    public static InferenceRequest of(String prompt) {
        return builder().prompt(prompt).build();
    }

    /**
     * Creates an inference request with a prompt and specific model.
     *
     * @param prompt the input prompt text
     * @param model  the model identifier
     * @return a new InferenceRequest
     */
    public static InferenceRequest of(String prompt, String model) {
        return builder().prompt(prompt).model(model).build();
    }

    /** Returns the input prompt text. */
    public String getPrompt() {
        return prompt;
    }

    /** Returns the model identifier (defaults to {@code "default"}). */
    public String getModel() {
        return model;
    }

    /** Returns the sampling temperature, if set. */
    public Optional<Double> getTemperature() {
        return Optional.ofNullable(temperature);
    }

    /** Returns the maximum number of tokens to generate, if set. */
    public Optional<Integer> getMaxTokens() {
        return Optional.ofNullable(maxTokens);
    }

    /** Returns the session identifier for context tracking, if set. */
    public Optional<String> getSessionId() {
        return Optional.ofNullable(sessionId);
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof InferenceRequest)) return false;
        InferenceRequest that = (InferenceRequest) o;
        return prompt.equals(that.prompt)
                && model.equals(that.model)
                && Objects.equals(temperature, that.temperature)
                && Objects.equals(maxTokens, that.maxTokens)
                && Objects.equals(sessionId, that.sessionId);
    }

    @Override
    public int hashCode() {
        return Objects.hash(prompt, model, temperature, maxTokens, sessionId);
    }

    @Override
    public String toString() {
        return "InferenceRequest{"
                + "prompt='" + prompt + '\''
                + ", model='" + model + '\''
                + ", temperature=" + temperature
                + ", maxTokens=" + maxTokens
                + ", sessionId='" + sessionId + '\''
                + '}';
    }

    // -----------------------------------------------------------------------
    // Builder
    // -----------------------------------------------------------------------

    /**
     * Builder for {@link InferenceRequest}.
     * <p>
     * All fields are optional except {@code prompt}, which is required.
     */
    public static final class Builder {

        private String prompt;
        private String model;
        private Double temperature;
        private Integer maxTokens;
        private String sessionId;

        private Builder() {
        }

        /**
         * Sets the input prompt text (required).
         *
         * @param prompt the prompt text
         * @return this builder
         */
        public Builder prompt(String prompt) {
            this.prompt = prompt;
            return this;
        }

        /**
         * Sets the model identifier.
         *
         * @param model the model identifier (e.g. {@code "phi-3-mini"})
         * @return this builder
         */
        public Builder model(String model) {
            this.model = model;
            return this;
        }

        /**
         * Sets the sampling temperature (0.0 to 2.0).
         *
         * @param temperature the temperature value
         * @return this builder
         */
        public Builder temperature(double temperature) {
            this.temperature = temperature;
            return this;
        }

        /**
         * Sets the maximum number of tokens to generate.
         *
         * @param maxTokens the maximum tokens
         * @return this builder
         */
        public Builder maxTokens(int maxTokens) {
            this.maxTokens = maxTokens;
            return this;
        }

        /**
         * Sets the session identifier for context tracking.
         *
         * @param sessionId the session identifier
         * @return this builder
         */
        public Builder sessionId(String sessionId) {
            this.sessionId = sessionId;
            return this;
        }

        /**
         * Builds the {@link InferenceRequest}.
         *
         * @return a new inference request
         * @throws NullPointerException if prompt is null
         */
        public InferenceRequest build() {
            return new InferenceRequest(this);
        }
    }
}