using System.Text.Json.Serialization;

namespace AinosSdk.Models;

/// <summary>
/// Current rate limit status for the client session.
/// </summary>
public class RateLimitStatus
{
    /// <summary>
    /// The rate limits for each category.
    /// </summary>
    [JsonPropertyName("limits")]
    public List<RateLimitInfo> Limits { get; init; } = new();

    /// <summary>
    /// Whether any rate limit is currently exceeded.
    /// </summary>
    [JsonIgnore]
    public bool IsExceeded => Limits.Exists(l => l.Remaining <= 0);

    /// <summary>
    /// Gets the rate limit info for a specific category.
    /// </summary>
    /// <param name="category">The category name (e.g. "inference").</param>
    /// <returns>The rate limit info, or null if not found.</returns>
    public RateLimitInfo? GetLimit(string category)
        => Limits.Find(l =>
            string.Equals(l.Category, category, StringComparison.OrdinalIgnoreCase));

    /// <summary>
    /// Returns a human-readable summary.
    /// </summary>
    public override string ToString()
        => $"RateLimitStatus {{ Limits={Limits.Count}, Exceeded={IsExceeded} }}";
}