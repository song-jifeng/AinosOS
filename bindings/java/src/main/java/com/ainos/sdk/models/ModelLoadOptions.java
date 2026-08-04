package com.ainos.sdk.models;

import java.util.Objects;

/**
 * Options for loading a model into the Ainos daemon.
 * <p>
 * This class is immutable and should be constructed using the {@link Builder}.
 *
 * <pre>{@code
 * ModelLoadOptions opts = ModelLoadOptions.builder()
 *     .architecture("phi3")
 *     .gpuLayerCount(32)
 *     .contextSize(4096)
 *     .build();
 * }</pre>
 */
public final class ModelLoadOptions {

    private final String architecture;
    private final Integer gpuLayerCount;
    private final Integer contextSize;
    private final Boolean useMmap;
    private final Integer threads;
    private final String engineType;

    private ModelLoadOptions(Builder builder) {
        this.architecture = builder.architecture;
        this.gpuLayerCount = builder.gpuLayerCount;
        this.contextSize = builder.contextSize;
        this.useMmap = builder.useMmap;
        this.threads = builder.threads;
        this.engineType = builder.engineType;
    }

    /**
     * Creates a new {@link Builder} for constructing {@code ModelLoadOptions}.
     *
     * @return a new builder instance
     */
    public static Builder builder() {
        return new Builder();
    }

    /** Returns the model architecture hint, if set. */
    public java.util.Optional<String> getArchitecture() {
        return java.util.Optional.ofNullable(architecture);
    }

    /** Returns the number of GPU layers to offload, if set. */
    public java.util.Optional<Integer> getGpuLayerCount() {
        return java.util.Optional.ofNullable(gpuLayerCount);
    }

    /** Returns the context size in tokens, if set. */
    public java.util.Optional<Integer> getContextSize() {
        return java.util.Optional.ofNullable(contextSize);
    }

    /** Returns whether memory-mapped I/O should be used, if set. */
    public java.util.Optional<Boolean> getUseMmap() {
        return java.util.Optional.ofNullable(useMmap);
    }

    /** Returns the number of CPU threads for inference, if set. */
    public java.util.Optional<Integer> getThreads() {
        return java.util.Optional.ofNullable(threads);
    }

    /** Returns the engine type override, if set (e.g. {@code "ggml"}, {@code "onnx"}). */
    public java.util.Optional<String> getEngineType() {
        return java.util.Optional.ofNullable(engineType);
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof ModelLoadOptions)) return false;
        ModelLoadOptions that = (ModelLoadOptions) o;
        return Objects.equals(architecture, that.architecture)
                && Objects.equals(gpuLayerCount, that.gpuLayerCount)
                && Objects.equals(contextSize, that.contextSize)
                && Objects.equals(useMmap, that.useMmap)
                && Objects.equals(threads, that.threads)
                && Objects.equals(engineType, that.engineType);
    }

    @Override
    public int hashCode() {
        return Objects.hash(architecture, gpuLayerCount, contextSize, useMmap, threads, engineType);
    }

    @Override
    public String toString() {
        return "ModelLoadOptions{"
                + "architecture='" + architecture + '\''
                + ", gpuLayerCount=" + gpuLayerCount
                + ", contextSize=" + contextSize
                + ", useMmap=" + useMmap
                + ", threads=" + threads
                + ", engineType='" + engineType + '\''
                + '}';
    }

    // -----------------------------------------------------------------------
    // Builder
    // -----------------------------------------------------------------------

    /**
     * Builder for {@link ModelLoadOptions}.
     */
    public static final class Builder {
        private String architecture;
        private Integer gpuLayerCount;
        private Integer contextSize;
        private Boolean useMmap;
        private Integer threads;
        private String engineType;

        private Builder() {
        }

        /** Sets the model architecture hint (e.g. {@code "auto"}, {@code "phi3"}, {@code "llama"}). */
        public Builder architecture(String architecture) {
            this.architecture = architecture;
            return this;
        }

        /** Sets the number of GPU layers to offload. */
        public Builder gpuLayerCount(int gpuLayerCount) {
            this.gpuLayerCount = gpuLayerCount;
            return this;
        }

        /** Sets the context size in tokens. */
        public Builder contextSize(int contextSize) {
            this.contextSize = contextSize;
            return this;
        }

        /** Sets whether to use memory-mapped I/O for model loading. */
        public Builder useMmap(boolean useMmap) {
            this.useMmap = useMmap;
            return this;
        }

        /** Sets the number of CPU threads for inference. */
        public Builder threads(int threads) {
            this.threads = threads;
            return this;
        }

        /** Sets the engine type override (e.g. {@code "ggml"}, {@code "onnx"}). */
        public Builder engineType(String engineType) {
            this.engineType = engineType;
            return this;
        }

        /** Builds the {@link ModelLoadOptions}. */
        public ModelLoadOptions build() {
            return new ModelLoadOptions(this);
        }
    }
}