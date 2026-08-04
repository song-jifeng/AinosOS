using System.Text.Json.Serialization;

namespace AinosSdk.Models;

/// <summary>
/// Health check response from the daemon.
/// </summary>
public class HealthStatus
{
    /// <summary>
    /// Whether the daemon is healthy and accepting requests.
    /// </summary>
    [JsonPropertyName("healthy")]
    public bool Healthy { get; init; }

    /// <summary>
    /// Human-readable status message.
    /// </summary>
    [JsonPropertyName("message")]
    public string Message { get; init; } = string.Empty;

    /// <summary>
    /// Daemon uptime in seconds.
    /// </summary>
    [JsonPropertyName("uptime")]
    public long Uptime { get; init; }

    /// <summary>
    /// Number of models loaded.
    /// </summary>
    [JsonPropertyName("models_loaded")]
    public int ModelsLoaded { get; init; }

    /// <summary>
    /// Returns a human-readable summary.
    /// </summary>
    public override string ToString()
        => $"HealthStatus {{ Healthy={Healthy}, Uptime={Uptime}s, ModelsLoaded={ModelsLoaded} }}";
}