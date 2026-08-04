using System.Collections.Concurrent;
using Microsoft.Extensions.Logging;

namespace AinosSdk.Transport;

/// <summary>
/// Manages a pool of TCP transport connections for batch and concurrent operations.
/// Provides connection reuse, lifecycle management, and health checking.
/// </summary>
public class ConnectionPool : IAsyncDisposable
{
    private readonly string _host;
    private readonly int _port;
    private readonly int _maxPoolSize;
    private readonly TimeSpan _connectionTimeout;
    private readonly TimeSpan _idleTimeout;
    private readonly ILogger _logger;
    private readonly ConcurrentBag<PooledConnection> _available = new();
    private readonly ConcurrentBag<PooledConnection> _inUse = new();
    private readonly SemaphoreSlim _poolSemaphore;
    private readonly CancellationTokenSource _cleanupCts = new();
    private int _totalCreated;
    private bool _disposed;

    /// <summary>
    /// Number of connections currently in the pool (available + in use).
    /// </summary>
    public int TotalCount => _available.Count + _inUse.Count;

    /// <summary>
    /// Number of available (idle) connections.
    /// </summary>
    public int AvailableCount => _available.Count;

    /// <summary>
    /// Number of connections currently in use.
    /// </summary>
    public int InUseCount => _inUse.Count;

    /// <summary>
    /// Creates a new connection pool.
    /// </summary>
    /// <param name="host">The daemon host.</param>
    /// <param name="port">The daemon port.</param>
    /// <param name="maxPoolSize">Maximum number of connections in the pool.</param>
    /// <param name="connectionTimeout">Timeout for establishing connections.</param>
    /// <param name="idleTimeout">Time after which idle connections are closed.</param>
    /// <param name="logger">Optional logger.</param>
    public ConnectionPool(
        string host,
        int port,
        int maxPoolSize = 8,
        TimeSpan? connectionTimeout = null,
        TimeSpan? idleTimeout = null,
        ILogger? logger = null)
    {
        _host = host ?? throw new ArgumentNullException(nameof(host));
        _port = port;
        _maxPoolSize = maxPoolSize > 0 ? maxPoolSize : 8;
        _connectionTimeout = connectionTimeout ?? TimeSpan.FromSeconds(5);
        _idleTimeout = idleTimeout ?? TimeSpan.FromSeconds(60);
        _logger = logger ?? Microsoft.Extensions.Logging.Abstractions.NullLogger.Instance;
        _poolSemaphore = new SemaphoreSlim(_maxPoolSize, _maxPoolSize);

        // Start background idle connection cleanup
        _ = CleanupIdleConnectionsAsync(_cleanupCts.Token);
    }

    /// <summary>
    /// Acquires a connection from the pool, creating a new one if needed.
    /// </summary>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>A pooled connection that should be returned via <see cref="ReturnAsync"/>.</returns>
    public async Task<PooledConnection> AcquireAsync(CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        await _poolSemaphore.WaitAsync(cancellationToken).ConfigureAwait(false);

        try
        {
            // Try to get an available connection
            if (_available.TryTake(out var connection))
            {
                if (connection.IsHealthy)
                {
                    _inUse.Add(connection);
                    _logger.LogTrace("Reused pooled connection {Id}", connection.Id);
                    return connection;
                }

                // Connection is stale, dispose it
                await connection.DisposeAsync().ConfigureAwait(false);
                _logger.LogTrace("Disposed stale connection {Id}", connection.Id);
            }

            // Create a new connection
            var transport = new TcpTransport(
                _host, _port,
                connectTimeout: _connectionTimeout,
                autoReconnect: false,
                logger: _logger);

            await transport.ConnectAsync(cancellationToken).ConfigureAwait(false);

            var newConn = new PooledConnection(transport, this);
            Interlocked.Increment(ref _totalCreated);
            _inUse.Add(newConn);
            _logger.LogTrace("Created new connection {Id} (total: {Total})",
                newConn.Id, Volatile.Read(ref _totalCreated));

            return newConn;
        }
        catch
        {
            _poolSemaphore.Release();
            throw;
        }
    }

    /// <summary>
    /// Returns a connection to the pool for reuse.
    /// </summary>
    /// <param name="connection">The connection to return.</param>
    public void Return(PooledConnection connection)
    {
        if (_disposed)
        {
            _ = connection.DisposeAsync().AsTask();
            return;
        }

        // Remove from in-use
        var tempBag = new ConcurrentBag<PooledConnection>();
        while (_inUse.TryTake(out var item))
        {
            if (item != connection)
                tempBag.Add(item);
        }
        foreach (var item in tempBag)
            _inUse.Add(item);

        // Return to available pool or dispose
        if (connection.IsHealthy && _available.Count < _maxPoolSize)
        {
            connection.MarkReturned();
            _available.Add(connection);
            _logger.LogTrace("Returned connection {Id} to pool", connection.Id);
        }
        else
        {
            _ = connection.DisposeAsync().AsTask();
            _logger.LogTrace("Disposed returned connection {Id}", connection.Id);
        }

        _poolSemaphore.Release();
    }

    /// <summary>
    /// Evicts all connections from the pool.
    /// </summary>
    public async Task EvictAllAsync()
    {
        var toDispose = new List<PooledConnection>();

        while (_available.TryTake(out var conn))
            toDispose.Add(conn);

        foreach (var conn in toDispose)
            await conn.DisposeAsync().ConfigureAwait(false);

        _logger.LogInformation("Evicted {Count} idle connections from pool", toDispose.Count);
    }

    /// <summary>
    /// Background task that cleans up idle connections that have exceeded the idle timeout.
    /// </summary>
    private async Task CleanupIdleConnectionsAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            try
            {
                await Task.Delay(TimeSpan.FromSeconds(15), cancellationToken).ConfigureAwait(false);

                var now = DateTimeOffset.UtcNow;
                var toDispose = new List<PooledConnection>();

                while (_available.TryTake(out var conn))
                {
                    if (now - conn.ReturnedAt > _idleTimeout || !conn.IsHealthy)
                    {
                        toDispose.Add(conn);
                    }
                    else
                    {
                        // Put it back
                        _available.Add(conn);
                    }
                }

                foreach (var conn in toDispose)
                {
                    await conn.DisposeAsync().ConfigureAwait(false);
                    _logger.LogTrace("Cleaned up idle connection {Id}", conn.Id);
                }

                if (toDispose.Count > 0)
                {
                    _logger.LogDebug("Cleaned up {Count} idle connections", toDispose.Count);
                }
            }
            catch (OperationCanceledException)
            {
                break;
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Error cleaning up idle connections");
            }
        }
    }

    /// <summary>
    /// Disposes the connection pool and all connections.
    /// </summary>
    public async ValueTask DisposeAsync()
    {
        if (_disposed)
            return;

        _disposed = true;
        await _cleanupCts.CancelAsync().ConfigureAwait(false);
        _cleanupCts.Dispose();

        // Dispose all available connections
        while (_available.TryTake(out var conn))
            await conn.DisposeAsync().ConfigureAwait(false);

        // Dispose all in-use connections
        while (_inUse.TryTake(out var conn))
            await conn.DisposeAsync().ConfigureAwait(false);

        _poolSemaphore.Dispose();
        GC.SuppressFinalize(this);
    }
}

/// <summary>
/// A pooled TCP transport connection.
/// </summary>
public class PooledConnection : IAsyncDisposable
{
    private static long _nextId;

    /// <summary>
    /// Unique identifier for this connection.
    /// </summary>
    public long Id { get; }

    /// <summary>
    /// The underlying TCP transport.
    /// </summary>
    public TcpTransport Transport { get; }

    /// <summary>
    /// When this connection was returned to the pool.
    /// </summary>
    public DateTimeOffset ReturnedAt { get; private set; }

    /// <summary>
    /// Whether the connection is healthy.
    /// </summary>
    public bool IsHealthy => Transport.IsConnected && !_disposed;

    /// <summary>
    /// The parent pool that owns this connection.
    /// </summary>
    private readonly ConnectionPool _owner;
    private bool _returned;
    private bool _disposed;

    internal PooledConnection(TcpTransport transport, ConnectionPool owner)
    {
        Id = Interlocked.Increment(ref _nextId);
        Transport = transport ?? throw new ArgumentNullException(nameof(transport));
        _owner = owner ?? throw new ArgumentNullException(nameof(owner));
        ReturnedAt = DateTimeOffset.UtcNow;
    }

    /// <summary>
    /// Marks this connection as returned to the pool.
    /// </summary>
    internal void MarkReturned()
    {
        ReturnedAt = DateTimeOffset.UtcNow;
        _returned = true;
    }

    /// <summary>
    /// Sends a request and returns the response.
    /// </summary>
    public Task<string> SendRequestAsync(string requestJson, CancellationToken cancellationToken = default)
    {
        return Transport.SendRequestAsync(requestJson, cancellationToken);
    }

    /// <summary>
    /// Returns this connection to the pool.
    /// </summary>
    public void ReturnToPool()
    {
        if (!_returned)
        {
            _returned = true;
            _owner.Return(this);
        }
    }

    /// <summary>
    /// Disposes the connection.
    /// </summary>
    public async ValueTask DisposeAsync()
    {
        if (_disposed)
            return;

        _disposed = true;
        await Transport.DisposeAsync().ConfigureAwait(false);
        GC.SuppressFinalize(this);
    }
}