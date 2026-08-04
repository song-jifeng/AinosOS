namespace AinosSdk.Models;

/// <summary>
/// Raised when authentication with the daemon fails.
/// </summary>
public class AinosAuthException : AinosException
{
    /// <summary>
    /// The reason for the authentication failure.
    /// </summary>
    public string? Reason { get; }

    /// <summary>
    /// Whether the session has expired and needs re-authentication.
    /// </summary>
    public bool IsSessionExpired { get; }

    public AinosAuthException()
    {
    }

    public AinosAuthException(string message) : base(message)
    {
    }

    public AinosAuthException(string message, Exception innerException) : base(message, innerException)
    {
    }

    public AinosAuthException(string message, string reason) : base(message)
    {
        Reason = reason;
    }

    public AinosAuthException(string message, bool isSessionExpired) : base(message)
    {
        IsSessionExpired = isSessionExpired;
    }

    public AinosAuthException(string message, string reason, bool isSessionExpired) : base(message)
    {
        Reason = reason;
        IsSessionExpired = isSessionExpired;
    }
}