using System.Text.Json.Serialization;

namespace AinosSdk.Models;

/// <summary>
/// Response from a model inference request.
/// </summary>
public class InferenceResponse
{
    /// <summary>
    /// The generated output text.
    /// </summary>
    [JsonPropertyName("output")]
    public string Output { get; init; } = string.Empty;

    /// <summary>
    /// Number of tokens generated.
    /// </summary>
    [JsonPropertyName("tokens_generated")]
    public int TokensGenerated { get; init; }

    /// <summary>
    /// Wall-clock inference time in milliseconds.
    /// </summary>
    [JsonPropertyName("inference_ms")]
    public long InferenceMs { get; init; }

    /// <summary>
    /// Source of the inference: "local" or "cloud".
    /// </summary>
    [JsonPropertyName("source")]
    public string Source { get; init; } = "local";

    /// <summary>
    /// The model that produced this response.
    /// </summary>
    [JsonPropertyName("model")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Model { get; init; }

    /// <summary>
    /// The session ID associated with this inference, if any.
    /// </summary>
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? SessionId { get; init; }

    /// <summary>
    /// Returns a human-readable summary of the response.
    /// </summary>
    public override string ToString()
        => $"InferenceResponse {{ Output={Output[..Math.Min(Output.Length, 80)]}..., Tokens={TokensGenerated}, Time={InferenceMs}ms, Source={Source} }}";
}