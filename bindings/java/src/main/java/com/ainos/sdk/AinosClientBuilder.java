package com.ainos.sdk;

import com.ainos.sdk.models.AinosAuthException;
import com.ainos.sdk.models.AinosConnectionException;
import com.ainos.sdk.models.AinosTimeoutException;

/**
 * Builder for configuring and creating {@link AinosClient} instances.
 * <p>
 * Provides a fluent API for setting all client configuration options.
 * <p>
 * Usage:
 * <pre>{@code
 * AinosClient client = AinosClient.builder()
 *     .host("192.168.1.100")
 *     .port(9500)
 *     .connectTimeout(10, TimeUnit.SECONDS)
 *     .readTimeout(5, TimeUnit.MINUTES)
 *     .authToken("my-secret-token")
 *     .autoReconnect(true)
 *     .maxReconnectAttempts(5)
 *     .build();
 * }</pre>
 */
public class AinosClientBuilder {

    // -----------------------------------------------------------------------
    // Defaults
    // -----------------------------------------------------------------------

    /** Default daemon host. */
    public static final String DEFAULT_HOST = "127.0.0.1";

    /** Default daemon TCP port. */
    public static final int DEFAULT_PORT = 9500;

    /** Default connection timeout in milliseconds. */
    public static final int DEFAULT_CONNECT_TIMEOUT_MS = 5000;

    /** Default read timeout in milliseconds. */
    public static final int DEFAULT_READ_TIMEOUT_MS = 120000;

    /** Default auto-reconnect behavior. */
    public static final boolean DEFAULT_AUTO_RECONNECT = true;

    /** Default reconnect delay in milliseconds. */
    public static final int DEFAULT_RECONNECT_DELAY_MS = 1000;

    /** Default maximum reconnect attempts. */
    public static final int DEFAULT_MAX_RECONNECT_ATTEMPTS = 3;

    /** Default auto-authenticate behavior. */
    public static final boolean DEFAULT_AUTO_AUTHENTICATE = true;

    /** Default connection pool usage. */
    public static final boolean DEFAULT_USE_CONNECTION_POOL = false;

    /** Default pool size. */
    public static final int DEFAULT_POOL_SIZE = 4;

    // -----------------------------------------------------------------------
    // Fields
    // -----------------------------------------------------------------------

    private String host = DEFAULT_HOST;
    private int port = DEFAULT_PORT;
    private int connectTimeoutMs = DEFAULT_CONNECT_TIMEOUT_MS;
    private int readTimeoutMs = DEFAULT_READ_TIMEOUT_MS;
    private boolean autoReconnect = DEFAULT_AUTO_RECONNECT;
    private int reconnectDelayMs = DEFAULT_RECONNECT_DELAY_MS;
    private int maxReconnectAttempts = DEFAULT_MAX_RECONNECT_ATTEMPTS;
    private String authToken;
    private boolean autoAuthenticate = DEFAULT_AUTO_AUTHENTICATE;
    private boolean useConnectionPool = DEFAULT_USE_CONNECTION_POOL;
    private int poolSize = DEFAULT_POOL_SIZE;

    // Package-private constructor; instances created via AinosClient.builder()
    AinosClientBuilder() {
    }

    // -----------------------------------------------------------------------
    // Host and port
    // -----------------------------------------------------------------------

    /**
     * Sets the daemon hostname or IP address.
     * <p>
     * Default: {@code "127.0.0.1"}
     *
     * @param host the daemon host
     * @return this builder
     */
    public AinosClientBuilder host(String host) {
        if (host == null || host.isEmpty()) {
            throw new IllegalArgumentException("host must not be null or empty");
        }
        this.host = host;
        return this;
    }

    /**
     * Sets the daemon TCP port.
     * <p>
     * Default: {@code 9500}
     *
     * @param port the TCP port (1-65535)
     * @return this builder
     */
    public AinosClientBuilder port(int port) {
        if (port < 1 || port > 65535) {
            throw new IllegalArgumentException("port must be between 1 and 65535");
        }
        this.port = port;
        return this;
    }

    /**
     * Sets the host and port together.
     * <p>
     * Convenience method equivalent to calling {@link #host(String)} and
     * {@link #port(int)}.
     *
     * @param host the daemon hostname
     * @param port the daemon TCP port
     * @return this builder
     */
    public AinosClientBuilder address(String host, int port) {
        return host(host).port(port);
    }

    // -----------------------------------------------------------------------
    // Timeouts
    // -----------------------------------------------------------------------

    /**
     * Sets the connection timeout in milliseconds.
     * <p>
     * Default: {@code 5000} (5 seconds)
     *
     * @param connectTimeoutMs the connection timeout in milliseconds
     * @return this builder
     */
    public AinosClientBuilder connectTimeoutMs(int connectTimeoutMs) {
        if (connectTimeoutMs < 1) {
            throw new IllegalArgumentException("connectTimeoutMs must be positive");
        }
        this.connectTimeoutMs = connectTimeoutMs;
        return this;
    }

    /**
     * Sets the connection timeout with a custom time unit.
     *
     * @param timeout the timeout duration
     * @param unit    the time unit
     * @return this builder
     */
    public AinosClientBuilder connectTimeout(long timeout, java.util.concurrent.TimeUnit unit) {
        return connectTimeoutMs((int) unit.toMillis(timeout));
    }

    /**
     * Sets the read (socket) timeout in milliseconds.
     * <p>
     * Default: {@code 120000} (2 minutes)
     *
     * @param readTimeoutMs the read timeout in milliseconds
     * @return this builder
     */
    public AinosClientBuilder readTimeoutMs(int readTimeoutMs) {
        if (readTimeoutMs < 1) {
            throw new IllegalArgumentException("readTimeoutMs must be positive");
        }
        this.readTimeoutMs = readTimeoutMs;
        return this;
    }

    /**
     * Sets the read timeout with a custom time unit.
     *
     * @param timeout the timeout duration
     * @param unit    the time unit
     * @return this builder
     */
    public AinosClientBuilder readTimeout(long timeout, java.util.concurrent.TimeUnit unit) {
        return readTimeoutMs((int) unit.toMillis(timeout));
    }

    // -----------------------------------------------------------------------
    // Reconnection
    // -----------------------------------------------------------------------

    /**
     * Sets whether to attempt automatic reconnection on connection failure.
     * <p>
     * Default: {@code true}
     *
     * @param autoReconnect {@code true} to enable auto-reconnect
     * @return this builder
     */
    public AinosClientBuilder autoReconnect(boolean autoReconnect) {
        this.autoReconnect = autoReconnect;
        return this;
    }

    /**
     * Sets the base delay between reconnection attempts in milliseconds.
     * <p>
     * The actual delay uses exponential backoff: {@code delay * 2^(attempt-1)}.
     * Default: {@code 1000} (1 second)
     *
     * @param reconnectDelayMs the base delay in milliseconds
     * @return this builder
     */
    public AinosClientBuilder reconnectDelayMs(int reconnectDelayMs) {
        if (reconnectDelayMs < 1) {
            throw new IllegalArgumentException("reconnectDelayMs must be positive");
        }
        this.reconnectDelayMs = reconnectDelayMs;
        return this;
    }

    /**
     * Sets the maximum number of reconnection attempts.
     * <p>
     * Default: {@code 3}
     *
     * @param maxReconnectAttempts the maximum number of attempts
     * @return this builder
     */
    public AinosClientBuilder maxReconnectAttempts(int maxReconnectAttempts) {
        if (maxReconnectAttempts < 0) {
            throw new IllegalArgumentException("maxReconnectAttempts must be non-negative");
        }
        this.maxReconnectAttempts = maxReconnectAttempts;
        return this;
    }

    // -----------------------------------------------------------------------
    // Authentication
    // -----------------------------------------------------------------------

    /**
     * Sets the bearer token for authentication.
     * <p>
     * If set, the client will automatically authenticate after connecting
     * (unless {@link #autoAuthenticate(boolean)} is set to {@code false}).
     *
     * @param authToken the bearer token
     * @return this builder
     */
    public AinosClientBuilder authToken(String authToken) {
        this.authToken = authToken;
        return this;
    }

    /**
     * Sets whether to automatically authenticate after connecting.
     * <p>
     * Only has effect when {@link #authToken(String)} is also set.
     * Default: {@code true}
     *
     * @param autoAuthenticate {@code true} to auto-authenticate
     * @return this builder
     */
    public AinosClientBuilder autoAuthenticate(boolean autoAuthenticate) {
        this.autoAuthenticate = autoAuthenticate;
        return this;
    }

    // -----------------------------------------------------------------------
    // Connection pool
    // -----------------------------------------------------------------------

    /**
     * Sets whether to use a connection pool for concurrent requests.
     * <p>
     * Default: {@code false}
     *
     * @param useConnectionPool {@code true} to enable connection pooling
     * @return this builder
     */
    public AinosClientBuilder useConnectionPool(boolean useConnectionPool) {
        this.useConnectionPool = useConnectionPool;
        return this;
    }

    /**
     * Sets the maximum number of connections in the pool.
     * <p>
     * Only has effect when {@link #useConnectionPool(boolean)} is {@code true}.
     * Default: {@code 4}
     *
     * @param poolSize the maximum pool size (minimum 1)
     * @return this builder
     */
    public AinosClientBuilder poolSize(int poolSize) {
        if (poolSize < 1) {
            throw new IllegalArgumentException("poolSize must be at least 1");
        }
        this.poolSize = poolSize;
        return this;
    }

    // -----------------------------------------------------------------------
    // Build
    // -----------------------------------------------------------------------

    /**
     * Builds a new {@link AinosClient} with the configured settings.
     * <p>
     * The client is returned in a disconnected state. Call {@link AinosClient#connect()}
     * to establish the connection.
     *
     * @return a new AinosClient instance
     */
    public AinosClient build() {
        return new AinosClient(
                host, port, connectTimeoutMs, readTimeoutMs,
                autoReconnect, reconnectDelayMs, maxReconnectAttempts,
                authToken, autoAuthenticate,
                useConnectionPool, poolSize
        );
    }

    /**
     * Builds a new {@link AinosClient} and immediately connects.
     * <p>
     * Equivalent to {@code builder.build().connect()}.
     *
     * @return a connected AinosClient instance
     * @throws AinosConnectionException if the connection cannot be established
     * @throws AinosTimeoutException    if the connection times out
     * @throws AinosAuthException       if auto-authentication fails
     */
    public AinosClient connect()
            throws AinosConnectionException, AinosTimeoutException, AinosAuthException {
        AinosClient client = build();
        client.connect();
        return client;
    }

    // -----------------------------------------------------------------------
    // Copy
    // -----------------------------------------------------------------------

    /**
     * Creates a copy of this builder with the same configuration.
     *
     * @return a new builder with identical settings
     */
    public AinosClientBuilder copy() {
        AinosClientBuilder copy = new AinosClientBuilder();
        copy.host = this.host;
        copy.port = this.port;
        copy.connectTimeoutMs = this.connectTimeoutMs;
        copy.readTimeoutMs = this.readTimeoutMs;
        copy.autoReconnect = this.autoReconnect;
        copy.reconnectDelayMs = this.reconnectDelayMs;
        copy.maxReconnectAttempts = this.maxReconnectAttempts;
        copy.authToken = this.authToken;
        copy.autoAuthenticate = this.autoAuthenticate;
        copy.useConnectionPool = this.useConnectionPool;
        copy.poolSize = this.poolSize;
        return copy;
    }

    // -----------------------------------------------------------------------
    // Getters (for inspection of current settings)
    // -----------------------------------------------------------------------

    /** Returns the configured host. */
    public String getHost() { return host; }

    /** Returns the configured port. */
    public int getPort() { return port; }

    /** Returns the connection timeout in milliseconds. */
    public int getConnectTimeoutMs() { return connectTimeoutMs; }

    /** Returns the read timeout in milliseconds. */
    public int getReadTimeoutMs() { return readTimeoutMs; }

    /** Returns whether auto-reconnect is enabled. */
    public boolean isAutoReconnect() { return autoReconnect; }

    /** Returns the reconnect delay in milliseconds. */
    public int getReconnectDelayMs() { return reconnectDelayMs; }

    /** Returns the maximum number of reconnect attempts. */
    public int getMaxReconnectAttempts() { return maxReconnectAttempts; }

    /** Returns the configured auth token, or {@code null}. */
    public String getAuthToken() { return authToken; }

    /** Returns whether auto-authenticate is enabled. */
    public boolean isAutoAuthenticate() { return autoAuthenticate; }

    /** Returns whether connection pooling is enabled. */
    public boolean isUseConnectionPool() { return useConnectionPool; }

    /** Returns the configured pool size. */
    public int getPoolSize() { return poolSize; }

    @Override
    public String toString() {
        return "AinosClientBuilder{"
                + "host='" + host + '\''
                + ", port=" + port
                + ", connectTimeoutMs=" + connectTimeoutMs
                + ", readTimeoutMs=" + readTimeoutMs
                + ", autoReconnect=" + autoReconnect
                + ", authToken=" + (authToken != null ? "***" : "null")
                + '}';
    }
}