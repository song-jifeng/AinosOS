namespace AinosSdk.Models;

/// <summary>
/// Raised when the SDK cannot establish or maintain a connection to the daemon.
/// </summary>
public class AinosConnectionException : AinosException
{
    /// <summary>
    /// The host that was being connected to.
    /// </summary>
    public string? Host { get; }

    /// <summary>
    /// The port that was being connected to.
    /// </summary>
    public int? Port { get; }

    /// <summary>
    /// Whether the connection was lost after being established.
    /// </summary>
    public bool WasConnected { get; }

    public AinosConnectionException()
    {
    }

    public AinosConnectionException(string message) : base(message)
    {
    }

    public AinosConnectionException(string message, Exception innerException) : base(message, innerException)
    {
    }

    public AinosConnectionException(string message, string host, int port)
        : base($"Cannot connect to {host}:{port} — {message}")
    {
        Host = host;
        Port = port;
    }

    public AinosConnectionException(string message, string host, int port, bool wasConnected)
        : base(message)
    {
        Host = host;
        Port = port;
        WasConnected = wasConnected;
    }
}