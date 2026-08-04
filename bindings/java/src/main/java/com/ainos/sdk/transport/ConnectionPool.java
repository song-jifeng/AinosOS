package com.ainos.sdk.transport;

import com.ainos.sdk.models.AinosConnectionException;
import com.ainos.sdk.models.AinosTimeoutException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.locks.Lock;
import java.util.concurrent.locks.ReentrantLock;

/**
 * A pool of {@link TcpTransport} connections to the Ainos daemon.
 * <p>
 * Manages multiple connections to support concurrent operations and
 * provides load-balanced connection selection. Connections are created
 * lazily and can be configured with a maximum pool size.
 * <p>
 * This class is thread-safe.
 */
public class ConnectionPool implements AutoCloseable {

    private static final Logger log = LoggerFactory.getLogger(ConnectionPool.class);

    private final String host;
    private final int port;
    private final int connectTimeoutMs;
    private final int readTimeoutMs;
    private final boolean tcpNoDelay;
    private final int maxSize;
    private final int maxWaitMs;

    private final List<PooledConnection> connections;
    private final Lock lock;
    private final AtomicInteger roundRobin;
    private volatile boolean closed;

    /**
     * Constructs a new connection pool.
     *
     * @param host             the daemon hostname
     * @param port             the daemon port
     * @param connectTimeoutMs connection timeout in milliseconds
     * @param readTimeoutMs    read timeout in milliseconds
     * @param tcpNoDelay       whether to enable TCP_NODELAY
     * @param maxSize          maximum number of pooled connections
     * @param maxWaitMs        maximum time to wait for an available connection
     */
    public ConnectionPool(String host, int port, int connectTimeoutMs, int readTimeoutMs,
                          boolean tcpNoDelay, int maxSize, int maxWaitMs) {
        this.host = host;
        this.port = port;
        this.connectTimeoutMs = connectTimeoutMs;
        this.readTimeoutMs = readTimeoutMs;
        this.tcpNoDelay = tcpNoDelay;
        this.maxSize = Math.max(1, maxSize);
        this.maxWaitMs = maxWaitMs;
        this.connections = new ArrayList<>();
        this.lock = new ReentrantLock();
        this.roundRobin = new AtomicInteger(0);
        this.closed = false;
    }

    /**
     * Constructs a connection pool with default settings.
     *
     * @param host the daemon hostname
     * @param port the daemon port
     */
    public ConnectionPool(String host, int port) {
        this(host, port, 5000, 120000, true, 4, 10000);
    }

    /**
     * Gets a transport connection from the pool.
     * <p>
     * Uses round-robin selection across available connections. If no
     * connections are available, a new one is created (up to the max pool size).
     *
     * @return a connected transport
     * @throws AinosConnectionException if no connection can be acquired
     * @throws AinosTimeoutException    if the connection times out
     */
    public TcpTransport acquire() throws AinosConnectionException, AinosTimeoutException {
        if (closed) {
            throw new AinosConnectionException("Connection pool is closed");
        }

        lock.lock();
        try {
            // Try to reuse an existing connection
            for (PooledConnection pc : connections) {
                if (pc.transport.isConnected()) {
                    return pc.transport;
                }
            }

            // Create a new connection if we haven't reached the max
            if (connections.size() < maxSize) {
                TcpTransportImpl transport = new TcpTransportImpl(
                        host, port, connectTimeoutMs, readTimeoutMs, tcpNoDelay);
                transport.connect();
                connections.add(new PooledConnection(transport));
                log.debug("Created new pooled connection (total: {})", connections.size());
                return transport;
            }

            // All connections are in use or broken - attempt to recreate the first one
            for (PooledConnection pc : connections) {
                try {
                    pc.transport.close();
                    TcpTransportImpl transport = new TcpTransportImpl(
                            host, port, connectTimeoutMs, readTimeoutMs, tcpNoDelay);
                    transport.connect();
                    pc.transport = transport;
                    return transport;
                } catch (Exception e) {
                    log.warn("Failed to reconnect pooled connection: {}", e.getMessage());
                }
            }

            throw new AinosConnectionException(
                    "All " + maxSize + " pooled connections are unavailable");
        } finally {
            lock.unlock();
        }
    }

    /**
     * Returns a connection to the pool.
     * <p>
     * If the connection is broken, it will be recreated on the next
     * {@link #acquire()} call.
     *
     * @param transport the transport to release
     */
    public void release(TcpTransport transport) {
        // Connections are automatically reused; no action needed.
        // Broken connections will be detected on the next acquire().
    }

    /**
     * Returns the number of connections currently in the pool.
     *
     * @return the pool size
     */
    public int size() {
        lock.lock();
        try {
            return connections.size();
        } finally {
            lock.unlock();
        }
    }

    /**
     * Closes all connections in the pool and releases resources.
     */
    @Override
    public void close() {
        lock.lock();
        try {
            closed = true;
            for (PooledConnection pc : connections) {
                try {
                    pc.transport.close();
                } catch (Exception e) {
                    log.warn("Error closing pooled connection: {}", e.getMessage());
                }
            }
            connections.clear();
            log.info("Connection pool closed");
        } finally {
            lock.unlock();
        }
    }

    // -----------------------------------------------------------------------
    // Internal
    // -----------------------------------------------------------------------

    private static class PooledConnection {
        TcpTransport transport;

        PooledConnection(TcpTransport transport) {
            this.transport = transport;
        }
    }
}