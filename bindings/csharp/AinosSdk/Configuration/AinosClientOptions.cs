using Microsoft.Extensions.Logging;

namespace AinosSdk.Configuration;

/// <summary>
/// Configuration options for the <see cref="AinosClient"/>.
/// </summary>
public class AinosClientOptions
{
    /// <summary>
    /// Default daemon host address.
    /// </summary>
    public const string DefaultHost = "127.0.0.1";

    /// <summary>
    /// Default daemon TCP port.
    /// </summary>
    public const int DefaultPort = 9500;

    /// <summary>
    /// Default connection timeout in seconds.
    /// </summary>
    public const double DefaultConnectTimeoutSeconds = 5.0;

    /// <summary>
    /// Default read timeout in seconds.
    /// </summary>
    public const double DefaultReadTimeoutSeconds = 120.0;

    /// <summary>
    /// Default send timeout in seconds.
    /// </summary>
    public const double DefaultSendTimeoutSeconds = 30.0;

    /// <summary>
    /// Default reconnect delay in seconds.
    /// </summary>
    public const double DefaultReconnectDelaySeconds = 1.0;

    /// <summary>
    /// Default maximum retry attempts.
    /// </summary>
    public const int DefaultMaxRetries = 3;

    /// <summary>
    /// Default maximum pool size.
    /// </summary>
    public const int DefaultMaxPoolSize = 8;

    /// <summary>
    /// The daemon hostname or IP address.
    /// </summary>
    public string Host { get; set; } = DefaultHost;

    /// <summary>
    /// The daemon TCP port.
    /// </summary>
    public int Port { get; set; } = DefaultPort;

    /// <summary>
    /// Connection timeout duration.
    /// </summary>
    public TimeSpan ConnectTimeout { get; set; } = TimeSpan.FromSeconds(DefaultConnectTimeoutSeconds);

    /// <summary>
    /// Read timeout for receiving responses.
    /// </summary>
    public TimeSpan ReadTimeout { get; set; } = TimeSpan.FromSeconds(DefaultReadTimeoutSeconds);

    /// <summary>
    /// Send timeout for sending requests.
    /// </summary>
    public TimeSpan SendTimeout { get; set; } = TimeSpan.FromSeconds(DefaultSendTimeoutSeconds);

    /// <summary>
    /// Whether to automatically attempt reconnection on connection loss.
    /// </summary>
    public bool AutoReconnect { get; set; } = true;

    /// <summary>
    /// Delay before reconnect attempts.
    /// </summary>
    public TimeSpan ReconnectDelay { get; set; } = TimeSpan.FromSeconds(DefaultReconnectDelaySeconds);

    /// <summary>
    /// Maximum number of retry attempts for failed requests.
    /// </summary>
    public int MaxRetries { get; set; } = DefaultMaxRetries;

    /// <summary>
    /// Bearer token for authentication. If set, the client will automatically authenticate on connect.
    /// </summary>
    public string? AuthToken { get; set; }

    /// <summary>
    /// Whether to automatically authenticate after connecting when <see cref="AuthToken"/> is set.
    /// </summary>
    public bool AutoAuthenticate { get; set; } = true;

    /// <summary>
    /// Whether to use the connection pool for batch operations.
    /// </summary>
    public bool UseConnectionPool { get; set; }

    /// <summary>
    /// Maximum number of connections in the pool.
    /// </summary>
    public int MaxPoolSize { get; set; } = DefaultMaxPoolSize;

    /// <summary>
    /// The default model to use for inference requests.
    /// </summary>
    public string DefaultModel { get; set; } = "default";

    /// <summary>
    /// Default temperature for inference (null = use daemon default).
    /// </summary>
    public float? DefaultTemperature { get; set; }

    /// <summary>
    /// Default max tokens for inference (null = use daemon default).
    /// </summary>
    public int? DefaultMaxTokens { get; set; }

    /// <summary>
    /// Application name sent as a client identifier.
    /// </summary>
    public string? ClientName { get; set; }

    /// <summary>
    /// Creates a shallow clone of the options.
    /// </summary>
    public AinosClientOptions Clone()
    {
        return new AinosClientOptions
        {
            Host = Host,
            Port = Port,
            ConnectTimeout = ConnectTimeout,
            ReadTimeout = ReadTimeout,
            SendTimeout = SendTimeout,
            AutoReconnect = AutoReconnect,
            ReconnectDelay = ReconnectDelay,
            MaxRetries = MaxRetries,
            AuthToken = AuthToken,
            AutoAuthenticate = AutoAuthenticate,
            UseConnectionPool = UseConnectionPool,
            MaxPoolSize = MaxPoolSize,
            DefaultModel = DefaultModel,
            DefaultTemperature = DefaultTemperature,
            DefaultMaxTokens = DefaultMaxTokens,
            ClientName = ClientName,
        };
    }

    /// <summary>
    /// Returns a string representation of the options (excluding auth token).
    /// </summary>
    public override string ToString()
        => $"AinosClientOptions {{ Host={Host}:{Port}, Timeout={ConnectTimeout.TotalSeconds}s, "
           + $"AutoReconnect={AutoReconnect}, AuthConfigured={AuthToken is not null} }}";
}