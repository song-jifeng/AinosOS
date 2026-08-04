using Microsoft.Extensions.Logging;

namespace AinosSdk.Configuration;

/// <summary>
/// Fluent builder for constructing <see cref="AinosClientOptions"/> and <see cref="AinosClient"/> instances.
/// </summary>
public class AinosClientBuilder
{
    private readonly AinosClientOptions _options;
    private ILoggerFactory? _loggerFactory;
    private ILogger<AinosClient>? _logger;

    /// <summary>
    /// Creates a new builder with default options.
    /// </summary>
    public AinosClientBuilder()
    {
        _options = new AinosClientOptions();
    }

    /// <summary>
    /// Creates a new builder with the given options.
    /// </summary>
    public AinosClientBuilder(AinosClientOptions options)
    {
        _options = options?.Clone() ?? throw new ArgumentNullException(nameof(options));
    }

    /// <summary>
    /// Sets the daemon host address.
    /// </summary>
    public AinosClientBuilder WithHost(string host)
    {
        _options.Host = host ?? throw new ArgumentNullException(nameof(host));
        return this;
    }

    /// <summary>
    /// Sets the daemon TCP port.
    /// </summary>
    public AinosClientBuilder WithPort(int port)
    {
        if (port < 1 || port > 65535)
            throw new ArgumentOutOfRangeException(nameof(port), "Port must be between 1 and 65535");
        _options.Port = port;
        return this;
    }

    /// <summary>
    /// Sets the connection timeout.
    /// </summary>
    public AinosClientBuilder WithConnectTimeout(TimeSpan timeout)
    {
        _options.ConnectTimeout = timeout > TimeSpan.Zero
            ? timeout
            : throw new ArgumentOutOfRangeException(nameof(timeout), "Timeout must be positive");
        return this;
    }

    /// <summary>
    /// Sets the read timeout for receiving responses.
    /// </summary>
    public AinosClientBuilder WithReadTimeout(TimeSpan timeout)
    {
        _options.ReadTimeout = timeout > TimeSpan.Zero
            ? timeout
            : throw new ArgumentOutOfRangeException(nameof(timeout), "Timeout must be positive");
        return this;
    }

    /// <summary>
    /// Sets the send timeout for sending requests.
    /// </summary>
    public AinosClientBuilder WithSendTimeout(TimeSpan timeout)
    {
        _options.SendTimeout = timeout > TimeSpan.Zero
            ? timeout
            : throw new ArgumentOutOfRangeException(nameof(timeout), "Timeout must be positive");
        return this;
    }

    /// <summary>
    /// Enables or disables auto-reconnect on connection loss.
    /// </summary>
    public AinosClientBuilder WithAutoReconnect(bool autoReconnect = true)
    {
        _options.AutoReconnect = autoReconnect;
        return this;
    }

    /// <summary>
    /// Sets the delay before reconnect attempts.
    /// </summary>
    public AinosClientBuilder WithReconnectDelay(TimeSpan delay)
    {
        _options.ReconnectDelay = delay >= TimeSpan.Zero
            ? delay
            : throw new ArgumentOutOfRangeException(nameof(delay), "Delay must be non-negative");
        return this;
    }

    /// <summary>
    /// Sets the maximum number of retry attempts.
    /// </summary>
    public AinosClientBuilder WithMaxRetries(int maxRetries)
    {
        _options.MaxRetries = maxRetries > 0
            ? maxRetries
            : throw new ArgumentOutOfRangeException(nameof(maxRetries), "Max retries must be positive");
        return this;
    }

    /// <summary>
    /// Sets the authentication token.
    /// </summary>
    public AinosClientBuilder WithAuthToken(string token)
    {
        _options.AuthToken = token ?? throw new ArgumentNullException(nameof(token));
        return this;
    }

    /// <summary>
    /// Enables or disables automatic authentication after connecting.
    /// </summary>
    public AinosClientBuilder WithAutoAuthenticate(bool autoAuthenticate = true)
    {
        _options.AutoAuthenticate = autoAuthenticate;
        return this;
    }

    /// <summary>
    /// Enables the connection pool for batch operations.
    /// </summary>
    public AinosClientBuilder WithConnectionPool(int maxPoolSize = 8)
    {
        _options.UseConnectionPool = true;
        _options.MaxPoolSize = maxPoolSize > 0 ? maxPoolSize : 8;
        return this;
    }

    /// <summary>
    /// Sets the default model for inference requests.
    /// </summary>
    public AinosClientBuilder WithDefaultModel(string model)
    {
        _options.DefaultModel = model ?? throw new ArgumentNullException(nameof(model));
        return this;
    }

    /// <summary>
    /// Sets the default temperature for inference.
    /// </summary>
    public AinosClientBuilder WithDefaultTemperature(float temperature)
    {
        _options.DefaultTemperature = temperature;
        return this;
    }

    /// <summary>
    /// Sets the default max tokens for inference.
    /// </summary>
    public AinosClientBuilder WithDefaultMaxTokens(int maxTokens)
    {
        _options.DefaultMaxTokens = maxTokens;
        return this;
    }

    /// <summary>
    /// Sets the client name identifier.
    /// </summary>
    public AinosClientBuilder WithClientName(string clientName)
    {
        _options.ClientName = clientName ?? throw new ArgumentNullException(nameof(clientName));
        return this;
    }

    /// <summary>
    /// Sets the logger factory for the client.
    /// </summary>
    public AinosClientBuilder WithLoggerFactory(ILoggerFactory loggerFactory)
    {
        _loggerFactory = loggerFactory ?? throw new ArgumentNullException(nameof(loggerFactory));
        return this;
    }

    /// <summary>
    /// Sets a specific logger instance for the client.
    /// </summary>
    public AinosClientBuilder WithLogger(ILogger<AinosClient> logger)
    {
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        return this;
    }

    /// <summary>
    /// Builds the <see cref="AinosClientOptions"/>.
    /// </summary>
    public AinosClientOptions BuildOptions() => _options.Clone();

    /// <summary>
    /// Builds the <see cref="AinosClient"/>.
    /// </summary>
    public AinosClient Build()
    {
        ILogger<AinosClient>? logger = _logger;

        if (logger is null && _loggerFactory is not null)
        {
            logger = _loggerFactory.CreateLogger<AinosClient>();
        }

        return new AinosClient(_options, logger);
    }

    /// <summary>
    /// Builds the <see cref="AinosClient"/> and connects it.
    /// </summary>
    public async Task<AinosClient> BuildAndConnectAsync(CancellationToken cancellationToken = default)
    {
        var client = Build();
        await client.ConnectAsync(cancellationToken).ConfigureAwait(false);
        return client;
    }

    /// <summary>
    /// Creates a builder pre-configured for connecting to localhost:9500.
    /// </summary>
    public static AinosClientBuilder CreateDefault() => new();

    /// <summary>
    /// Creates a builder pre-configured with the given host and port.
    /// </summary>
    public static AinosClientBuilder Create(string host, int port)
        => new AinosClientBuilder().WithHost(host).WithPort(port);

    /// <summary>
    /// Creates a builder with authentication.
    /// </summary>
    public static AinosClientBuilder CreateAuthenticated(string token)
        => new AinosClientBuilder().WithAuthToken(token);
}