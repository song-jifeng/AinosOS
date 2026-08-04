namespace AinosSdk.Models;

/// <summary>
/// Raised when the daemon returns a rate limit error (HTTP 429).
/// </summary>
public class AinosRateLimitException : AinosException
{
    /// <summary>
    /// Number of seconds to wait before retrying.
    /// </summary>
    public int RetryAfterSeconds { get; }

    /// <summary>
    /// The rate limit category that was exceeded.
    /// </summary>
    public string? Category { get; }

    /// <summary>
    /// The current limit value for this category.
    /// </summary>
    public long? Limit { get; }

    /// <summary>
    /// The number of requests remaining in the current window.
    /// </summary>
    public long? Remaining { get; }

    public AinosRateLimitException()
    {
    }

    public AinosRateLimitException(string message, int retryAfterSeconds)
        : base(message)
    {
        RetryAfterSeconds = retryAfterSeconds;
    }

    public AinosRateLimitException(string message, int retryAfterSeconds, string category, long limit, long remaining)
        : base($"Rate limit exceeded for '{category}': {message}. Retry after {retryAfterSeconds}s. ({remaining}/{limit} remaining)")
    {
        RetryAfterSeconds = retryAfterSeconds;
        Category = category;
        Limit = limit;
        Remaining = remaining;
    }
}