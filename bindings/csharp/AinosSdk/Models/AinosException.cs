namespace AinosSdk.Models;

/// <summary>
/// Base exception for all Ainos SDK errors.
/// </summary>
public class AinosException : Exception
{
    /// <summary>
    /// Optional error code returned by the daemon.
    /// </summary>
    public int? ErrorCode { get; }

    /// <summary>
    /// The raw response type from the daemon, if applicable.
    /// </summary>
    public string? ResponseType { get; }

    public AinosException()
    {
    }

    public AinosException(string message) : base(message)
    {
    }

    public AinosException(string message, Exception innerException) : base(message, innerException)
    {
    }

    public AinosException(string message, int errorCode) : base(message)
    {
        ErrorCode = errorCode;
    }

    public AinosException(string message, int errorCode, string responseType) : base(message)
    {
        ErrorCode = errorCode;
        ResponseType = responseType;
    }
}