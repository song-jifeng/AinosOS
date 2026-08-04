using System.Text.Json.Serialization;

namespace AinosSdk.Models;

/// <summary>
/// Metadata describing a single registered model.
/// </summary>
public class ModelInfo
{
    /// <summary>
    /// Unique model identifier (e.g. "phi_3_mini_4k_instruct_q4_gguf").
    /// </summary>
    [JsonPropertyName("id")]
    public string Id { get; init; } = string.Empty;

    /// <summary>
    /// Human-readable model name (e.g. "phi-3-mini-4k-instruct-q4.gguf").
    /// </summary>
    [JsonPropertyName("name")]
    public string Name { get; init; } = string.Empty;

    /// <summary>
    /// Absolute file path on disk.
    /// </summary>
    [JsonPropertyName("path")]
    public string Path { get; init; } = string.Empty;

    /// <summary>
    /// Model file size in megabytes.
    /// </summary>
    [JsonPropertyName("size_mb")]
    public long SizeMb { get; init; }

    /// <summary>
    /// Whether the model is currently loaded in memory.
    /// </summary>
    [JsonPropertyName("loaded")]
    public bool Loaded { get; init; }

    /// <summary>
    /// Model architecture string (e.g. "auto", "phi3", "llama").
    /// </summary>
    [JsonPropertyName("architecture")]
    public string Architecture { get; init; } = "auto";

    /// <summary>
    /// Returns a human-readable summary of the model info.
    /// </summary>
    public override string ToString()
        => $"ModelInfo {{ Id={Id}, Name={Name}, Loaded={Loaded}, Size={SizeMb}MB, Arch={Architecture} }}";
}