using System.Text.Json.Serialization;

namespace AinosSdk.Models;

/// <summary>
/// Optional parameters for loading a model.
/// </summary>
public class ModelLoadOptions
{
    /// <summary>
    /// Whether to skip loading if the model is already loaded.
    /// </summary>
    [JsonPropertyName("skip_if_loaded")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingDefault)]
    public bool SkipIfLoaded { get; init; }

    /// <summary>
    /// Override the model architecture (e.g. "auto", "phi3", "llama").
    /// </summary>
    [JsonPropertyName("architecture")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Architecture { get; init; }

    /// <summary>
    /// Number of GPU layers to offload (0 = CPU only).
    /// </summary>
    [JsonPropertyName("gpu_layers")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? GpuLayers { get; init; }

    /// <summary>
    /// Context size in tokens.
    /// </summary>
    [JsonPropertyName("context_size")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? ContextSize { get; init; }

    /// <summary>
    /// Creates a default <see cref="ModelLoadOptions"/>.
    /// </summary>
    public static ModelLoadOptions Default => new();

    /// <summary>
    /// Creates a new <see cref="Builder"/> for constructing <see cref="ModelLoadOptions"/>.
    /// </summary>
    public static Builder CreateBuilder() => new();

    /// <summary>
    /// Fluent builder for <see cref="ModelLoadOptions"/>.
    /// </summary>
    public class Builder
    {
        private bool _skipIfLoaded;
        private string? _architecture;
        private int? _gpuLayers;
        private int? _contextSize;

        internal Builder() { }

        /// <summary>Sets whether to skip loading if already loaded.</summary>
        public Builder WithSkipIfLoaded(bool skip = true) { _skipIfLoaded = skip; return this; }

        /// <summary>Sets the model architecture override.</summary>
        public Builder WithArchitecture(string architecture) { _architecture = architecture; return this; }

        /// <summary>Sets the number of GPU layers.</summary>
        public Builder WithGpuLayers(int gpuLayers) { _gpuLayers = gpuLayers; return this; }

        /// <summary>Sets the context size in tokens.</summary>
        public Builder WithContextSize(int contextSize) { _contextSize = contextSize; return this; }

        /// <summary>Builds the <see cref="ModelLoadOptions"/>.</summary>
        public ModelLoadOptions Build() => new()
        {
            SkipIfLoaded = _skipIfLoaded,
            Architecture = _architecture,
            GpuLayers = _gpuLayers,
            ContextSize = _contextSize,
        };
    }
}