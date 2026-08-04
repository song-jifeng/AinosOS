using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using AinosSdk.Configuration;
using AinosSdk.Models;
using AinosSdk.Transport;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;

namespace AinosSdk;

/// <summary>
/// Main client for communicating with the Ainos AI Daemon over TCP/IP NDJSON protocol.
/// Provides methods for inference, model management, context store, and system queries.
/// Thread-safe, supports CancellationToken, and auto-reconnect.
/// </summary>
public class AinosClient : IAsyncDisposable
{
    private readonly AinosClientOptions _options;
    private readonly ILogger<AinosClient> _logger;
    private readonly TcpTransport _transport;
    private readonly JsonCodec _codec;
    private readonly SemaphoreSlim _authLock = new(1, 1);
    private ConnectionPool? _connectionPool;

    private string? _sessionToken;
    private bool _authenticated;
    private List<string> _permissions = new();
    private long _sessionTtlSeconds;
    private bool _disposed;

    /// <summary>
    /// Whether the client is currently connected to the daemon.
    /// </summary>
    public bool Connected => _transport.IsConnected;

    /// <summary>
    /// Whether the client has been authenticated with the daemon.
    /// </summary>
    public bool Authenticated => _authenticated;

    /// <summary>
    /// The current session token, if authenticated.
    /// </summary>
    public string? SessionToken => _sessionToken;

    /// <summary>
    /// The permissions granted to the current session.
    /// </summary>
    public IReadOnlyList<string> Permissions => _permissions.AsReadOnly();

    /// <summary>
    /// The current client options.
    /// </summary>
    public AinosClientOptions Options => _options;

    /// <summary>
    /// Creates a new AinosClient with the specified options.
    /// </summary>
    /// <param name="options">Configuration options.</param>
    /// <param name="logger">Optional logger instance.</param>
    public AinosClient(AinosClientOptions options, ILogger<AinosClient>? logger = null)
    {
        _options = options?.Clone() ?? throw new ArgumentNullException(nameof(options));
        _logger = logger ?? NullLogger<AinosClient>.Instance;

        _transport = new TcpTransport(
            _options.Host,
            _options.Port,
            connectTimeout: _options.ConnectTimeout,
            readTimeout: _options.ReadTimeout,
            sendTimeout: _options.SendTimeout,
            autoReconnect: _options.AutoReconnect,
            reconnectDelay: _options.ReconnectDelay,
            maxRetries: _options.MaxRetries,
            logger: _logger);

        if (_options.UseConnectionPool)
        {
            _connectionPool = new ConnectionPool(
                _options.Host,
                _options.Port,
                maxPoolSize: _options.MaxPoolSize,
                connectionTimeout: _options.ConnectTimeout,
                logger: _logger);
        }
    }

    // =========================================================================
    // Connection Lifecycle
    // =========================================================================

    /// <summary>
    /// Opens a TCP connection to the daemon.
    /// If <see cref="AinosClientOptions.AuthToken"/> and <see cref="AinosClientOptions.AutoAuthenticate"/>
    /// are set, this will also attempt authentication after connecting.
    /// </summary>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <exception cref="AinosConnectionException">If the connection cannot be established.</exception>
    /// <exception cref="AinosAuthException">If auto-authentication fails.</exception>
    public async Task ConnectAsync(CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        await _transport.ConnectAsync(cancellationToken).ConfigureAwait(false);
        _logger.LogInformation("Connected to Ainos daemon at {Host}:{Port}", _options.Host, _options.Port);

        // Auto-authenticate if token is provided
        if (!string.IsNullOrEmpty(_options.AuthToken) && _options.AutoAuthenticate)
        {
            await AuthenticateAsync(_options.AuthToken, cancellationToken).ConfigureAwait(false);
        }
    }

    /// <summary>
    /// Closes the TCP connection if open.
    /// </summary>
    public async Task DisconnectAsync()
    {
        await _transport.DisconnectAsync().ConfigureAwait(false);
        _sessionToken = null;
        _authenticated = false;
        _permissions = new List<string>();
        _logger.LogInformation("Disconnected from Ainos daemon");
    }

    /// <summary>
    /// Ensures the client is connected, attempting reconnect if needed.
    /// </summary>
    private async Task EnsureConnectedAsync(CancellationToken cancellationToken)
    {
        if (_transport.IsConnected)
            return;

        if (!_options.AutoReconnect)
            throw new AinosConnectionException("Not connected to daemon. Call ConnectAsync first.");

        _logger.LogInformation("Attempting reconnect...");
        await Task.Delay(_options.ReconnectDelay, cancellationToken).ConfigureAwait(false);
        await ConnectAsync(cancellationToken).ConfigureAwait(false);
    }

    // =========================================================================
    // Authentication
    // =========================================================================

    /// <summary>
    /// Authenticate with the daemon using a bearer token.
    /// </summary>
    /// <param name="token">The bearer token to authenticate with.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>A tuple of (success, sessionToken, permissions, sessionTtlSeconds).</returns>
    /// <exception cref="AinosAuthException">If authentication fails.</exception>
    /// <exception cref="AinosConnectionException">If the connection is lost.</exception>
    public async Task<(bool Success, string? SessionToken, List<string> Permissions, long SessionTtlSeconds)>
        AuthenticateAsync(string token, CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        if (string.IsNullOrEmpty(token))
            throw new AinosAuthException("No authentication token provided");

        await _authLock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            var requestJson = JsonCodec.SerializeRequest("Auth", new Dictionary<string, object?>
            {
                ["token"] = token
            });

            var responseJson = await _transport.SendRequestAsync(requestJson, cancellationToken)
                .ConfigureAwait(false);

            var authData = JsonCodec.ParseAuthResponse(responseJson);

            if (!authData.Success)
            {
                throw new AinosAuthException(
                    authData.Message ?? "Authentication failed",
                    authData.Message ?? "Unknown reason");
            }

            _sessionToken = authData.SessionToken;
            _authenticated = true;
            _permissions = authData.Permissions;
            _sessionTtlSeconds = authData.SessionTtlSeconds;

            _logger.LogInformation(
                "Authenticated successfully, session token: {TokenPrefix}...",
                _sessionToken?[..Math.Min(_sessionToken.Length, 8)] ?? "None");

            return (authData.Success, authData.SessionToken, authData.Permissions, authData.SessionTtlSeconds);
        }
        catch (AinosAuthException)
        {
            throw;
        }
        catch (AinosConnectionException)
        {
            throw;
        }
        catch (Exception ex)
        {
            throw new AinosAuthException($"Authentication failed: {ex.Message}", ex);
        }
        finally
        {
            _authLock.Release();
        }
    }

    // =========================================================================
    // Inference
    // =========================================================================

    /// <summary>
    /// Sends an inference request and returns the complete response.
    /// </summary>
    /// <param name="request">The inference request parameters.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The inference response with generated text.</returns>
    /// <exception cref="AinosConnectionException">If the connection is lost.</exception>
    /// <exception cref="AinosException">If the daemon returns an error.</exception>
    /// <exception cref="OperationCanceledException">If cancelled.</exception>
    public async Task<InferenceResponse> InferAsync(
        InferenceRequest request,
        CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        ArgumentNullException.ThrowIfNull(request);

        await EnsureConnectedAsync(cancellationToken).ConfigureAwait(false);

        var requestJson = JsonCodec.Serialize(request.ToWireFormat());
        var responseJson = await _transport.SendRequestAsync(requestJson, cancellationToken)
            .ConfigureAwait(false);

        // Check for error response
        if (JsonCodec.TryParseError(responseJson, out var errorCode, out var errorMessage))
        {
            if (errorCode == 429)
                throw new AinosRateLimitException(errorMessage ?? "Rate limit exceeded", 1);
            throw new AinosException(errorMessage ?? "Inference failed", errorCode, "Error");
        }

        return JsonCodec.ParseInferenceResponse(responseJson);
    }

    /// <summary>
    /// Sends a streaming inference request and returns an async enumerable of chunks.
    /// </summary>
    /// <param name="request">The inference request parameters.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>An async enumerable of inference chunks.</returns>
    /// <exception cref="AinosConnectionException">If the connection is lost.</exception>
    /// <exception cref="AinosException">If the daemon returns an error.</exception>
    public async IAsyncEnumerable<InferenceChunk> InferStreamAsync(
        InferenceRequest request,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        ArgumentNullException.ThrowIfNull(request);

        await EnsureConnectedAsync(cancellationToken).ConfigureAwait(false);

        var requestJson = JsonCodec.Serialize(request.ToStreamWireFormat());

        // Use the stream from the transport
        var streamEnumerable = _transport.SendStreamRequestAsync(requestJson, cancellationToken);

        await foreach (var line in streamEnumerable.WithCancellation(cancellationToken).ConfigureAwait(false))
        {
            if (string.IsNullOrWhiteSpace(line))
                continue;

            using var doc = JsonDocument.Parse(line);
            var root = doc.RootElement;

            var chunk = new InferenceChunk
            {
                Model = request.Model,
            };

            if (root.TryGetProperty("chunk", out var chunkProp))
                chunk = chunk with { Chunk = chunkProp.GetString() ?? string.Empty };

            if (root.TryGetProperty("done", out var doneProp))
                chunk = chunk with { Done = doneProp.GetBoolean() };

            yield return chunk;

            if (chunk.Done)
                yield break;
        }
    }

    // =========================================================================
    // System Status
    // =========================================================================

    /// <summary>
    /// Queries the daemon's health and statistics.
    /// </summary>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>A <see cref="SystemStatus"/> instance.</returns>
    public async Task<SystemStatus> GetStatusAsync(CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        await EnsureConnectedAsync(cancellationToken).ConfigureAwait(false);

        var requestJson = JsonCodec.SerializeRequest("Status");
        var responseJson = await _transport.SendRequestAsync(requestJson, cancellationToken)
            .ConfigureAwait(false);

        if (JsonCodec.TryParseError(responseJson, out _, out var errorMessage))
        {
            throw new AinosException(errorMessage ?? "Status query failed");
        }

        return JsonCodec.ParseStatusResponse(responseJson);
    }

    // =========================================================================
    // Model Management
    // =========================================================================

    /// <summary>
    /// Lists all registered models.
    /// </summary>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>A list of <see cref="ModelInfo"/> objects.</returns>
    public async Task<List<ModelInfo>> GetModelListAsync(CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        await EnsureConnectedAsync(cancellationToken).ConfigureAwait(false);

        var requestJson = JsonCodec.SerializeRequest("ModelList");
        var responseJson = await _transport.SendRequestAsync(requestJson, cancellationToken)
            .ConfigureAwait(false);

        if (JsonCodec.TryParseError(responseJson, out _, out var errorMessage))
        {
            throw new AinosException(errorMessage ?? "Model list query failed");
        }

        return JsonCodec.ParseModelListResponse(responseJson);
    }

    /// <summary>
    /// Loads a model into memory from a file path.
    /// </summary>
    /// <param name="path">Absolute path to the model file on disk.</param>
    /// <param name="options">Optional model load parameters.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>A <see cref="ModelInfo"/> for the loaded model.</returns>
    /// <exception cref="AinosException">If the load fails.</exception>
    public async Task<ModelInfo> LoadModelAsync(
        string path,
        ModelLoadOptions? options = null,
        CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        if (string.IsNullOrEmpty(path))
            throw new ArgumentException("Model path is required", nameof(path));

        await EnsureConnectedAsync(cancellationToken).ConfigureAwait(false);

        var body = new Dictionary<string, object?>
        {
            ["path"] = path
        };

        if (options is not null)
        {
            if (options.SkipIfLoaded)
                body["skip_if_loaded"] = true;
            if (options.Architecture is not null)
                body["architecture"] = options.Architecture;
            if (options.GpuLayers.HasValue)
                body["gpu_layers"] = options.GpuLayers.Value;
            if (options.ContextSize.HasValue)
                body["context_size"] = options.ContextSize.Value;
        }

        var requestJson = JsonCodec.SerializeRequest("ModelLoad", body);
        var responseJson = await _transport.SendRequestAsync(requestJson, cancellationToken)
            .ConfigureAwait(false);

        if (JsonCodec.TryParseError(responseJson, out _, out var errorMessage))
        {
            throw new AinosException(errorMessage ?? "Model load failed");
        }

        var loadData = JsonCodec.ParseModelLoadResponse(responseJson);

        if (loadData.Status == "error")
        {
            throw new AinosException(loadData.Message);
        }

        return loadData.ModelInfo ?? new ModelInfo
        {
            Id = loadData.ModelId,
            Path = path,
            Loaded = loadData.Status == "loaded" || loadData.Status == "already_loaded",
        };
    }

    /// <summary>
    /// Unloads a model from memory.
    /// </summary>
    /// <param name="id">The model identifier.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <exception cref="AinosException">If the unload fails.</exception>
    public async Task UnloadModelAsync(string id, CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        if (string.IsNullOrEmpty(id))
            throw new ArgumentException("Model ID is required", nameof(id));

        await EnsureConnectedAsync(cancellationToken).ConfigureAwait(false);

        var requestJson = JsonCodec.SerializeRequest("ModelUnload", new Dictionary<string, object?>
        {
            ["model_id"] = id
        });

        var responseJson = await _transport.SendRequestAsync(requestJson, cancellationToken)
            .ConfigureAwait(false);

        if (JsonCodec.TryParseError(responseJson, out _, out var errorMessage))
        {
            throw new AinosException(errorMessage ?? "Model unload failed");
        }

        var unloadData = JsonCodec.ParseModelUnloadResponse(responseJson);

        if (unloadData.Status == "error")
        {
            throw new AinosException(unloadData.Message);
        }

        _logger.LogInformation("Model {ModelId} unloaded: {Status}", id, unloadData.Status);
    }

    // =========================================================================
    // Context Management
    // =========================================================================

    /// <summary>
    /// Stores a key-value pair in the daemon's context store.
    /// </summary>
    /// <param name="sessionId">The session identifier for the context.</param>
    /// <param name="key">The lookup key.</param>
    /// <param name="value">The value to store (as bytes, will be base64-encoded).</param>
    /// <param name="ttl">Time-to-live in seconds (0 = no expiration).</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <exception cref="AinosException">If the store fails.</exception>
    public async Task ContextStoreAsync(
        string sessionId,
        string key,
        byte[] value,
        long ttl = 0,
        CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        if (string.IsNullOrEmpty(key))
            throw new ArgumentException("Key is required", nameof(key));
        ArgumentNullException.ThrowIfNull(value);

        await EnsureConnectedAsync(cancellationToken).ConfigureAwait(false);

        var valueStr = Convert.ToBase64String(value);

        var body = new Dictionary<string, object?>
        {
            ["key"] = key,
            ["value"] = valueStr,
            ["session_id"] = sessionId ?? "default",
        };

        if (ttl > 0)
            body["ttl"] = ttl;

        var requestJson = JsonCodec.SerializeRequest("ContextStore", body);
        var responseJson = await _transport.SendRequestAsync(requestJson, cancellationToken)
            .ConfigureAwait(false);

        if (JsonCodec.TryParseError(responseJson, out _, out var errorMessage))
        {
            throw new AinosException(errorMessage ?? "Context store failed");
        }

        _logger.LogDebug("Context stored: key={Key}, session={SessionId}, ttl={Ttl}", key, sessionId, ttl);
    }

    /// <summary>
    /// Stores a string value in the daemon's context store.
    /// </summary>
    /// <param name="sessionId">The session identifier.</param>
    /// <param name="key">The lookup key.</param>
    /// <param name="value">The string value to store.</param>
    /// <param name="ttl">Time-to-live in seconds.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    public async Task ContextStoreStringAsync(
        string sessionId,
        string key,
        string value,
        long ttl = 0,
        CancellationToken cancellationToken = default)
    {
        await ContextStoreAsync(sessionId, key, Encoding.UTF8.GetBytes(value), ttl, cancellationToken)
            .ConfigureAwait(false);
    }

    /// <summary>
    /// Retrieves a value by key from the daemon's context store.
    /// </summary>
    /// <param name="sessionId">The session identifier.</param>
    /// <param name="key">The lookup key.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The stored value as bytes, or null if the key was not found.</returns>
    /// <exception cref="AinosException">If the retrieval fails.</exception>
    public async Task<byte[]?> ContextRetrieveAsync(
        string sessionId,
        string key,
        CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        if (string.IsNullOrEmpty(key))
            throw new ArgumentException("Key is required", nameof(key));

        await EnsureConnectedAsync(cancellationToken).ConfigureAwait(false);

        var body = new Dictionary<string, object?>
        {
            ["key"] = key,
            ["session_id"] = sessionId ?? "default",
        };

        var requestJson = JsonCodec.SerializeRequest("ContextRetrieve", body);
        var responseJson = await _transport.SendRequestAsync(requestJson, cancellationToken)
            .ConfigureAwait(false);

        // Check for error - key not found returns an error
        if (JsonCodec.TryParseError(responseJson, out _, out var errorMessage))
        {
            _logger.LogDebug("Context key not found: {Key}", key);
            return null;
        }

        var output = JsonCodec.ParseContextResponse(responseJson);
        if (string.IsNullOrEmpty(output))
            return null;

        // Try to decode as base64; if fails, return raw UTF-8 bytes
        try
        {
            return Convert.FromBase64String(output);
        }
        catch (FormatException)
        {
            return Encoding.UTF8.GetBytes(output);
        }
    }

    /// <summary>
    /// Retrieves a string value by key from the daemon's context store.
    /// </summary>
    /// <param name="sessionId">The session identifier.</param>
    /// <param name="key">The lookup key.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The stored string value, or null if not found.</returns>
    public async Task<string?> ContextRetrieveStringAsync(
        string sessionId,
        string key,
        CancellationToken cancellationToken = default)
    {
        var bytes = await ContextRetrieveAsync(sessionId, key, cancellationToken).ConfigureAwait(false);
        if (bytes is null)
            return null;

        return Encoding.UTF8.GetString(bytes);
    }

    // =========================================================================
    // Batch Inference
    // =========================================================================

    /// <summary>
    /// Sends multiple inference requests sequentially and returns all responses.
    /// Uses the connection pool if configured.
    /// </summary>
    /// <param name="requests">The list of inference requests.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>A list of inference responses in the same order as the requests.</returns>
    public async Task<List<InferenceResponse>> BatchInferAsync(
        List<InferenceRequest> requests,
        CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        ArgumentNullException.ThrowIfNull(requests);

        if (requests.Count == 0)
            return new List<InferenceResponse>();

        var results = new List<InferenceResponse>(requests.Count);

        if (_options.UseConnectionPool && _connectionPool is not null)
        {
            // Use connection pool for parallel execution
            var tasks = requests.Select(req => Task.Run(async () =>
            {
                var conn = await _connectionPool.AcquireAsync(cancellationToken).ConfigureAwait(false);
                try
                {
                    var requestJson = JsonCodec.Serialize(req.ToWireFormat());
                    var responseJson = await conn.SendRequestAsync(requestJson, cancellationToken)
                        .ConfigureAwait(false);

                    if (JsonCodec.TryParseError(responseJson, out _, out var errorMessage))
                    {
                        throw new AinosException(errorMessage ?? "Batch inference failed");
                    }

                    return JsonCodec.ParseInferenceResponse(responseJson);
                }
                finally
                {
                    conn.ReturnToPool();
                }
            }, cancellationToken));

            var completed = await Task.WhenAll(tasks).ConfigureAwait(false);
            results.AddRange(completed);
        }
        else
        {
            // Sequential execution
            foreach (var req in requests)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var result = await InferAsync(req, cancellationToken).ConfigureAwait(false);
                results.Add(result);
            }
        }

        return results;
    }

    // =========================================================================
    // Health & Rate Limit
    // =========================================================================

    /// <summary>
    /// Gets the daemon health status.
    /// </summary>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>A <see cref="HealthStatus"/> instance.</returns>
    public async Task<HealthStatus> GetHealthAsync(CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        try
        {
            var status = await GetStatusAsync(cancellationToken).ConfigureAwait(false);
            return new HealthStatus
            {
                Healthy = true,
                Message = "Daemon is responding",
                Uptime = status.Uptime,
                ModelsLoaded = status.ModelsLoaded,
            };
        }
        catch (AinosConnectionException ex)
        {
            return new HealthStatus
            {
                Healthy = false,
                Message = $"Cannot reach daemon: {ex.Message}",
            };
        }
        catch (Exception ex)
        {
            return new HealthStatus
            {
                Healthy = false,
                Message = $"Health check failed: {ex.Message}",
            };
        }
    }

    /// <summary>
    /// Queries the current rate limit status for this session.
    /// </summary>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>A <see cref="RateLimitStatus"/> instance.</returns>
    public async Task<RateLimitStatus> GetRateLimitStatusAsync(CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        await EnsureConnectedAsync(cancellationToken).ConfigureAwait(false);

        var requestJson = JsonCodec.SerializeRequest("RateLimitStatus");
        var responseJson = await _transport.SendRequestAsync(requestJson, cancellationToken)
            .ConfigureAwait(false);

        if (JsonCodec.TryParseError(responseJson, out _, out var errorMessage))
        {
            throw new AinosException(errorMessage ?? "Rate limit status query failed");
        }

        return JsonCodec.ParseRateLimitResponse(responseJson);
    }

    // =========================================================================
    // Convenience methods
    // =========================================================================

    /// <summary>
    /// Sends a simple inference request with just a prompt and returns the output text.
    /// </summary>
    /// <param name="prompt">The input prompt.</param>
    /// <param name="model">Optional model identifier.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The generated output text.</returns>
    public async Task<string> InferSimpleAsync(
        string prompt,
        string? model = null,
        CancellationToken cancellationToken = default)
    {
        var request = InferenceRequest.CreateBuilder(prompt)
            .WithModel(model ?? _options.DefaultModel);

        if (_options.DefaultTemperature.HasValue)
            request.WithTemperature(_options.DefaultTemperature.Value);
        if (_options.DefaultMaxTokens.HasValue)
            request.WithMaxTokens(_options.DefaultMaxTokens.Value);

        var response = await InferAsync(request.Build(), cancellationToken).ConfigureAwait(false);
        return response.Output;
    }

    /// <summary>
    /// Sends a streaming inference request and collects all chunks into a single string.
    /// </summary>
    /// <param name="prompt">The input prompt.</param>
    /// <param name="model">Optional model identifier.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The complete generated text.</returns>
    public async Task<string> InferStreamSimpleAsync(
        string prompt,
        string? model = null,
        CancellationToken cancellationToken = default)
    {
        var request = InferenceRequest.CreateBuilder(prompt)
            .WithModel(model ?? _options.DefaultModel)
            .Build();

        var sb = new StringBuilder();
        await foreach (var chunk in InferStreamAsync(request, cancellationToken).ConfigureAwait(false))
        {
            sb.Append(chunk.Chunk);
            if (chunk.Done)
                break;
        }
        return sb.ToString();
    }

    // =========================================================================
    // Dispose
    // =========================================================================

    /// <summary>
    /// Disposes the client and releases all resources.
    /// </summary>
    public async ValueTask DisposeAsync()
    {
        if (_disposed)
            return;

        _disposed = true;

        try
        {
            await _transport.DisposeAsync().ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Error disposing transport");
        }

        if (_connectionPool is not null)
        {
            try
            {
                await _connectionPool.DisposeAsync().ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Error disposing connection pool");
            }
        }

        _authLock.Dispose();
        _sessionToken = null;
        _authenticated = false;
        _permissions = new List<string>();

        GC.SuppressFinalize(this);
    }
}