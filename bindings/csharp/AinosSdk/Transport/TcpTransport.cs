using System.Net.Sockets;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using AinosSdk.Models;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;

namespace AinosSdk.Transport;

/// <summary>
/// Low-level TCP NDJSON transport for communicating with the Ainos daemon.
/// Handles connection establishment, line-based read/write, and auto-reconnect.
/// </summary>
public class TcpTransport : IAsyncDisposable
{
    private readonly string _host;
    private readonly int _port;
    private readonly TimeSpan _connectTimeout;
    private readonly TimeSpan _readTimeout;
    private readonly TimeSpan _sendTimeout;
    private readonly bool _autoReconnect;
    private readonly TimeSpan _reconnectDelay;
    private readonly int _maxRetries;
    private readonly ILogger _logger;

    private TcpClient? _tcpClient;
    private NetworkStream? _stream;
    private readonly SemaphoreSlim _lock = new(1, 1);
    private bool _disposed;
    private int _connectionAttempts;

    /// <summary>
    /// Whether the transport is currently connected.
    /// </summary>
    public bool IsConnected => _tcpClient?.Connected == true && _stream is not null;

    /// <summary>
    /// The host address.
    /// </summary>
    public string Host => _host;

    /// <summary>
    /// The port number.
    /// </summary>
    public int Port => _port;

    /// <summary>
    /// Creates a new TCP transport instance.
    /// </summary>
    public TcpTransport(
        string host,
        int port,
        TimeSpan? connectTimeout = null,
        TimeSpan? readTimeout = null,
        TimeSpan? sendTimeout = null,
        bool autoReconnect = true,
        TimeSpan? reconnectDelay = null,
        int maxRetries = 3,
        ILogger? logger = null)
    {
        _host = host ?? throw new ArgumentNullException(nameof(host));
        _port = port;
        _connectTimeout = connectTimeout ?? TimeSpan.FromSeconds(5);
        _readTimeout = readTimeout ?? TimeSpan.FromSeconds(120);
        _sendTimeout = sendTimeout ?? TimeSpan.FromSeconds(30);
        _autoReconnect = autoReconnect;
        _reconnectDelay = reconnectDelay ?? TimeSpan.FromSeconds(1);
        _maxRetries = Math.Max(1, maxRetries);
        _logger = logger ?? NullLogger.Instance;
    }

    /// <summary>
    /// Opens a TCP connection to the daemon.
    /// </summary>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <exception cref="AinosConnectionException">If the connection cannot be established.</exception>
    public async Task ConnectAsync(CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        await _lock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (IsConnected)
                return;

            _connectionAttempts = 0;
            await ConnectInternalAsync(cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            _lock.Release();
        }
    }

    /// <summary>
    /// Closes the TCP connection.
    /// </summary>
    public async Task DisconnectAsync()
    {
        await _lock.WaitAsync().ConfigureAwait(false);
        try
        {
            CloseInternal();
        }
        finally
        {
            _lock.Release();
        }
    }

    /// <summary>
    /// Sends a JSON request and reads a single JSON response line.
    /// </summary>
    /// <param name="requestJson">The JSON request string (without newline).</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The JSON response string.</returns>
    /// <exception cref="AinosConnectionException">If the connection is lost.</exception>
    /// <exception cref="AinosException">If the daemon returns an error.</exception>
    /// <exception cref="OperationCanceledException">If cancelled.</exception>
    public async Task<string> SendRequestAsync(string requestJson, CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        var lastException = default(Exception);

        for (int attempt = 0; attempt <= _maxRetries; attempt++)
        {
            cancellationToken.ThrowIfCancellationRequested();

            try
            {
                var (client, stream) = await GetConnectedClientAsync(cancellationToken).ConfigureAwait(false);

                using var writeCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
                writeCts.CancelAfter(_sendTimeout);

                // Write the JSON line
                var data = Encoding.UTF8.GetBytes(requestJson + "\n");
                await stream.WriteAsync(data, writeCts.Token).ConfigureAwait(false);
                await stream.FlushAsync(writeCts.Token).ConfigureAwait(false);

                // Read the response line
                using var readCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
                readCts.CancelAfter(_readTimeout);

                var response = await ReadLineAsync(stream, readCts.Token).ConfigureAwait(false);
                return response;
            }
            catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
            {
                // Timeout, not user cancellation
                lastException = new AinosConnectionException(
                    $"Read timed out after {_readTimeout.TotalSeconds}s");
                HandleConnectionFailure();
            }
            catch (IOException ex) when (ex is SocketException || ex.InnerException is SocketException)
            {
                lastException = new AinosConnectionException($"Connection lost: {ex.Message}", ex);
                HandleConnectionFailure();
            }
            catch (IOException ex)
            {
                lastException = new AinosConnectionException($"I/O error: {ex.Message}", ex);
                HandleConnectionFailure();
            }
            catch (AinosConnectionException)
            {
                throw;
            }
            catch (Exception ex)
            {
                lastException = ex;
                HandleConnectionFailure();
            }

            // Attempt reconnect if configured
            if (!_autoReconnect || attempt >= _maxRetries - 1)
                break;

            _logger.LogInformation("Attempting reconnect (attempt {Attempt}/{MaxRetries})...",
                attempt + 1, _maxRetries);

            await Task.Delay(_reconnectDelay, cancellationToken).ConfigureAwait(false);
        }

        throw new AinosConnectionException(
            $"Failed to send request after {_maxRetries} retries: {lastException?.Message}",
            lastException ?? new Exception("Unknown error"));
    }

    /// <summary>
    /// Sends a JSON request and returns an async enumerable of response lines (streaming).
    /// </summary>
    /// <param name="requestJson">The JSON request string (without newline).</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>An async enumerable of JSON response strings.</returns>
    public async IAsyncEnumerable<string> SendStreamRequestAsync(
        string requestJson,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        TcpClient? streamClient = null;
        NetworkStream? stream = null;

        try
        {
            (streamClient, stream) = await GetConnectedClientAsync(cancellationToken).ConfigureAwait(false);

            var data = Encoding.UTF8.GetBytes(requestJson + "\n");
            await stream.WriteAsync(data, cancellationToken).ConfigureAwait(false);
            await stream.FlushAsync(cancellationToken).ConfigureAwait(false);

            // Read streaming responses line by line
            while (!cancellationToken.IsCancellationRequested)
            {
                using var readCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
                readCts.CancelAfter(_readTimeout);

                var line = await ReadLineAsync(stream, readCts.Token).ConfigureAwait(false);

                if (line.Length == 0)
                    yield break;

                // Check if the response is a final error or done marker
                using var doc = JsonDocument.Parse(line);
                var root = doc.RootElement;

                if (root.TryGetProperty("type", out var typeProp))
                {
                    var type = typeProp.GetString();

                    if (type == "Error")
                    {
                        var code = root.TryGetProperty("code", out var c) ? c.GetInt32() : -1;
                        var message = root.TryGetProperty("message", out var m) ? m.GetString() : "Unknown error";
                        throw new AinosException(message, code, type);
                    }

                    if (type == "InferenceChunk")
                    {
                        yield return line;

                        // Check if this is the final chunk
                        if (root.TryGetProperty("done", out var doneProp) && doneProp.GetBoolean())
                            yield break;
                    }
                }
            }
        }
        finally
        {
            // For streaming, we don't close the connection here — the caller owns it
            // But if we're the ones who opened it, we should clean up
            stream?.Dispose();
            streamClient?.Dispose();
        }
    }

    /// <summary>
    /// Ensures the transport is connected, attempting reconnect if needed.
    /// </summary>
    private async Task<(TcpClient, NetworkStream)> GetConnectedClientAsync(CancellationToken cancellationToken)
    {
        if (IsConnected && _tcpClient is not null && _stream is not null)
            return (_tcpClient, _stream);

        if (!_autoReconnect)
            throw new AinosConnectionException("Not connected to daemon");

        await _lock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (IsConnected && _tcpClient is not null && _stream is not null)
                return (_tcpClient, _stream);

            _logger.LogInformation("Attempting auto-reconnect...");
            await Task.Delay(_reconnectDelay, cancellationToken).ConfigureAwait(false);
            await ConnectInternalAsync(cancellationToken).ConfigureAwait(false);

            return (_tcpClient!, _stream!);
        }
        finally
        {
            _lock.Release();
        }
    }

    /// <summary>
    /// Internal connection logic (must be called inside _lock).
    /// </summary>
    private async Task ConnectInternalAsync(CancellationToken cancellationToken)
    {
        CloseInternal();

        _connectionAttempts++;
        _logger.LogDebug("Connecting to {Host}:{Port} (attempt #{Attempt})...",
            _host, _port, _connectionAttempts);

        var tcpClient = new TcpClient();
        try
        {
            using var connectCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            connectCts.CancelAfter(_connectTimeout);

#if NET6_0_OR_GREATER
            await tcpClient.ConnectAsync(_host, _port, connectCts.Token).ConfigureAwait(false);
#else
            await tcpClient.ConnectAsync(_host, _port).ConfigureAwait(false);
#endif

            _tcpClient = tcpClient;
            _stream = tcpClient.GetStream();

            // Configure socket options
            tcpClient.NoDelay = true;
            tcpClient.ReceiveBufferSize = 65536;
            tcpClient.SendBufferSize = 65536;

            _logger.LogInformation("Connected to Ainos daemon at {Host}:{Port}", _host, _port);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            tcpClient.Dispose();
            throw new AinosConnectionException(
                $"Cannot connect to {_host}:{_port} — {ex.Message}", ex);
        }
    }

    /// <summary>
    /// Closes the current connection (must be called inside _lock).
    /// </summary>
    private void CloseInternal()
    {
        try
        {
            _stream?.Dispose();
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Error disposing stream");
        }

        try
        {
            _tcpClient?.Dispose();
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Error disposing TCP client");
        }

        _stream = null;
        _tcpClient = null;
    }

    /// <summary>
    /// Handles a connection failure by closing the socket.
    /// </summary>
    private void HandleConnectionFailure()
    {
        _lock.Wait();
        try
        {
            CloseInternal();
        }
        finally
        {
            _lock.Release();
        }
    }

    /// <summary>
    /// Reads a single newline-terminated line from the network stream.
    /// </summary>
    private static async Task<string> ReadLineAsync(NetworkStream stream, CancellationToken cancellationToken)
    {
        // Use a small buffer for efficient single-byte reading
        var sb = new StringBuilder(256);
        var singleByteBuffer = new byte[1];

        while (!cancellationToken.IsCancellationRequested)
        {
            var bytesRead = await stream.ReadAsync(singleByteBuffer, cancellationToken).ConfigureAwait(false);

            if (bytesRead == 0)
                throw new AinosConnectionException("Connection closed by peer");

            var ch = (char)singleByteBuffer[0];
            if (ch == '\n')
                break;

            sb.Append(ch);
        }

        return sb.ToString();
    }

    /// <summary>
    /// Disposes the transport and releases all resources.
    /// </summary>
    public async ValueTask DisposeAsync()
    {
        if (_disposed)
            return;

        _disposed = true;
        await DisconnectAsync().ConfigureAwait(false);
        _lock.Dispose();
        GC.SuppressFinalize(this);
    }
}