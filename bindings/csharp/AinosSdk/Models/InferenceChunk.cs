using System.Text.Json.Serialization;

namespace AinosSdk.Models;

/// <summary>
/// A single chunk from a streaming inference response.
/// </summary>
public class InferenceChunk
{
    /// <summary>
    /// The text chunk generated so far.
    /// </summary>
    [JsonPropertyName("chunk")]
    public string Chunk { get; init; } = string.Empty;

    /// <summary>
    /// Whether this is the final chunk in the stream.
    /// </summary>
    [JsonPropertyName("done")]
    public bool Done { get; init; }

    /// <summary>
    /// The index of this chunk in the stream (0-based).
    /// </summary>
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingDefault)]
    public int Index { get; init; }

    /// <summary>
    /// The model that produced this chunk.
    /// </summary>
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Model { get; init; }

    /// <summary>
    /// Returns a human-readable summary of the chunk.
    /// </summary>
    public override string ToString()
        => $"InferenceChunk {{ Chunk=\"{Chunk[..Math.Min(Chunk.Length, 40)]}..., Done={Done}, Index={Index} }}";
}