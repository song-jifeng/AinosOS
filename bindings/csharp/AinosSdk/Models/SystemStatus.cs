using System.Text.Json.Serialization;

namespace AinosSdk.Models;

/// <summary>
/// Daemon health and statistics.
/// </summary>
public class SystemStatus
{
    /// <summary>
    /// Seconds since the daemon started.
    /// </summary>
    [JsonPropertyName("uptime")]
    public long Uptime { get; init; }

    /// <summary>
    /// Number of models currently loaded in memory.
    /// </summary>
    [JsonPropertyName("models_loaded")]
    public int ModelsLoaded { get; init; }

    /// <summary>
    /// Total inference requests handled since daemon start.
    /// </summary>
    [JsonPropertyName("total_requests")]
    public long TotalRequests { get; init; }

    /// <summary>
    /// Whether the internet is reachable by the daemon.
    /// </summary>
    [JsonPropertyName("network_available")]
    public bool NetworkAvailable { get; init; }

    /// <summary>
    /// Number of active client sessions.
    /// </summary>
    [JsonPropertyName("active_sessions")]
    public int ActiveSessions { get; init; }

    /// <summary>
    /// Optional rate limit information per category.
    /// </summary>
    [JsonPropertyName("rate_limits")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public List<RateLimitInfo>? RateLimits { get; init; }

    /// <summary>
    /// Returns a human-readable summary of the daemon status.
    /// </summary>
    public override string ToString()
        => $"SystemStatus {{ Uptime={Uptime}s, ModelsLoaded={ModelsLoaded}, TotalRequests={TotalRequests}, Network={NetworkAvailable} }}";
}

/// <summary>
/// Rate limit information for a specific category.
/// </summary>
public class RateLimitInfo
{
    /// <summary>
    /// The rate limit category (e.g. "inference", "model_ops", "status", "admin").
    /// </summary>
    [JsonPropertyName("category")]
    public string Category { get; init; } = string.Empty;

    /// <summary>
    /// Maximum requests allowed in the current window.
    /// </summary>
    [JsonPropertyName("limit")]
    public long Limit { get; init; }

    /// <summary>
    /// Requests remaining in the current window.
    /// </summary>
    [JsonPropertyName("remaining")]
    public long Remaining { get; init; }

    /// <summary>
    /// Seconds until the rate limit window resets.
    /// </summary>
    [JsonPropertyName("reset_seconds")]
    public long ResetSeconds { get; init; }
}