package com.ainos.sdk;

import com.ainos.sdk.models.*;
import com.ainos.sdk.stream.InferenceStream;
import com.ainos.sdk.stream.StreamReader;
import com.ainos.sdk.transport.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.Closeable;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.locks.Lock;
import java.util.concurrent.locks.ReentrantLock;
import java.util.stream.Stream;

/**
 * Main client for communicating with the Ainos AI Daemon over TCP.
 * <p>
 * This client provides synchronous access to all daemon features including
 * inference, model management, context storage, and system monitoring.
 * It uses the NDJSON (newline-delimited JSON) protocol over TCP.
 * <p>
 * The client is thread-safe. All public methods can be called concurrently
 * from multiple threads.
 * <p>
 * Usage:
 * <pre>{@code
 * // Create and configure
 * AinosClient client = AinosClient.builder()
 *     .host("127.0.0.1")
 *     .port(9500)
 *     .authToken("your-token")
 *     .build();
 *
 * // Connect and authenticate
 * client.connect();
 * client.authenticate();
 *
 * // Run inference
 * InferenceResponse resp = client.infer(InferenceRequest.of("Hello, Ainos!"));
 * System.out.println(resp.getOutput());
 *
 * // Check status
 * SystemStatus status = client.status();
 * System.out.println("Uptime: " + status.getUptime() + "s");
 *
 * // Clean up
 * client.close();
 * }</pre>
 */
public class AinosClient implements Closeable {

    private static final Logger log = LoggerFactory.getLogger(AinosClient.class);

    // -----------------------------------------------------------------------
    // Configuration
    // -----------------------------------------------------------------------

    private final String host;
    private final int port;
    private final int connectTimeoutMs;
    private final int readTimeoutMs;
    private final boolean autoReconnect;
    private final int reconnectDelayMs;
    private final int maxReconnectAttempts;
    private final String authToken;
    private final boolean autoAuthenticate;
    private final boolean useConnectionPool;
    private final int poolSize;

    // -----------------------------------------------------------------------
    // State
    // -----------------------------------------------------------------------

    private final Lock lock;
    private final JsonCodec codec;
    private final AtomicReference<ConnectionState> connectionState;
    private final AtomicBoolean closed;

    // Transport — either a single transport or a pool
    private TcpTransport transport;
    private ConnectionPool pool;

    // Authentication state
    private String sessionToken;
    private boolean authenticated;
    private List<String> permissions;
    private long sessionTtl;

    // -----------------------------------------------------------------------
    // Connection state enum
    // -----------------------------------------------------------------------

    private enum ConnectionState {
        DISCONNECTED,
        CONNECTING,
        CONNECTED,
        CLOSED
    }

    // -----------------------------------------------------------------------
    // Construction
    // -----------------------------------------------------------------------

    /**
     * Constructs an AinosClient with the specified configuration.
     * <p>
     * Use {@link #builder()} for convenient construction.
     *
     * @param host                the daemon hostname
     * @param port                the daemon TCP port
     * @param connectTimeoutMs    connection timeout in milliseconds
     * @param readTimeoutMs       read timeout in milliseconds
     * @param autoReconnect       whether to attempt reconnection on failure
     * @param reconnectDelayMs    base delay between reconnection attempts
     * @param maxReconnectAttempts maximum number of reconnect attempts
     * @param authToken           bearer token for authentication
     * @param autoAuthenticate    whether to authenticate automatically after connect
     * @param useConnectionPool   whether to use a connection pool
     * @param poolSize            maximum pool size (if pool is enabled)
     */
    AinosClient(String host, int port, int connectTimeoutMs, int readTimeoutMs,
                boolean autoReconnect, int reconnectDelayMs, int maxReconnectAttempts,
                String authToken, boolean autoAuthenticate,
                boolean useConnectionPool, int poolSize) {
        this.host = host;
        this.port = port;
        this.connectTimeoutMs = connectTimeoutMs;
        this.readTimeoutMs = readTimeoutMs;
        this.autoReconnect = autoReconnect;
        this.reconnectDelayMs = reconnectDelayMs;
        this.maxReconnectAttempts = maxReconnectAttempts;
        this.authToken = authToken;
        this.autoAuthenticate = autoAuthenticate;
        this.useConnectionPool = useConnectionPool;
        this.poolSize = poolSize;

        this.lock = new ReentrantLock();
        this.codec = new JsonCodec();
        this.connectionState = new AtomicReference<>(ConnectionState.DISCONNECTED);
        this.closed = new AtomicBoolean(false);
        this.sessionToken = null;
        this.authenticated = false;
        this.permissions = new ArrayList<>();
        this.sessionTtl = 0;
    }

    /**
     * Creates a new {@link AinosClientBuilder} for configuring the client.
     *
     * @return a new builder
     */
    public static AinosClientBuilder builder() {
        return new AinosClientBuilder();
    }

    // -----------------------------------------------------------------------
    // Connection lifecycle
    // -----------------------------------------------------------------------

    /**
     * Opens a TCP connection to the daemon.
     * <p>
     * If {@code authToken} is set and {@code autoAuthenticate} is enabled,
     * authentication will be attempted automatically after connecting.
     *
     * @throws AinosConnectionException if the connection cannot be established
     * @throws AinosTimeoutException    if the connection times out
     * @throws AinosAuthException       if auto-authentication fails
     */
    public void connect() throws AinosConnectionException, AinosTimeoutException, AinosAuthException {
        if (closed.get()) {
            throw new AinosConnectionException("Client is closed");
        }

        lock.lock();
        try {
            if (connectionState.get() == ConnectionState.CONNECTED) {
                log.debug("Already connected to {}:{}", host, port);
                return;
            }

            connectionState.set(ConnectionState.CONNECTING);

            if (useConnectionPool) {
                pool = new ConnectionPool(host, port, connectTimeoutMs, readTimeoutMs,
                        true, poolSize, connectTimeoutMs);
                transport = pool.acquire();
            } else {
                transport = TransportFactory.create(host, port, connectTimeoutMs, readTimeoutMs, true);
                transport.connect();
            }

            connectionState.set(ConnectionState.CONNECTED);
            log.info("Connected to Ainos daemon at {}:{}", host, port);

            // Auto-authenticate if token is provided
            if (authToken != null && autoAuthenticate) {
                authenticate(authToken);
            }
        } catch (AinosAuthException e) {
            connectionState.set(ConnectionState.DISCONNECTED);
            throw e;
        } catch (AinosConnectionException | AinosTimeoutException e) {
            connectionState.set(ConnectionState.DISCONNECTED);
            throw e;
        } finally {
            lock.unlock();
        }
    }

    /**
     * Closes the connection to the daemon and releases all resources.
     * <p>
     * Once closed, the client cannot be reused. Create a new client instance
     * to connect again.
     */
    @Override
    public void close() {
        if (closed.getAndSet(true)) {
            return;
        }

        lock.lock();
        try {
            connectionState.set(ConnectionState.CLOSED);
            authenticated = false;
            sessionToken = null;
            permissions = new ArrayList<>();
            sessionTtl = 0;

            if (pool != null) {
                pool.close();
                pool = null;
            }
            if (transport != null) {
                transport.close();
                transport = null;
            }
            log.info("Ainos client closed");
        } finally {
            lock.unlock();
        }
    }

    /**
     * Disconnects without closing the client.
     * <p>
     * The client can be reconnected by calling {@link #connect()} again.
     */
    public void disconnect() {
        lock.lock();
        try {
            connectionState.set(ConnectionState.DISCONNECTED);
            authenticated = false;
            sessionToken = null;
            permissions = new ArrayList<>();
            sessionTtl = 0;

            if (transport != null) {
                transport.close();
                transport = null;
            }
            if (pool != null) {
                pool.close();
                pool = null;
            }
            log.info("Disconnected from Ainos daemon");
        } finally {
            lock.unlock();
        }
    }

    // -----------------------------------------------------------------------
    // Authentication
    // -----------------------------------------------------------------------

    /**
     * Authenticates with the daemon using a bearer token.
     *
     * @param token the bearer token
     * @return a map containing the authentication response details
     * @throws AinosAuthException       if authentication fails
     * @throws AinosConnectionException if the connection is lost
     * @throws AinosTimeoutException    if the operation times out
     */
    public Map<String, Object> authenticate(String token)
            throws AinosAuthException, AinosConnectionException, AinosTimeoutException {
        if (token == null || token.isEmpty()) {
            throw new AinosAuthException("No authentication token provided");
        }

        Map<String, Object> request = codec.buildRequest("Auth",
                Collections.singletonMap("token", token));
        Map<String, Object> response = sendRequest(request);

        String type = JsonCodec.getType(response);
        if (!"AuthResponse".equals(type)) {
            throw new AinosAuthException("Unexpected response type: " + type);
        }

        boolean success = JsonCodec.getBoolean(response, "success", false);
        if (!success) {
            throw new AinosAuthException(JsonCodec.getString(response, "message", "Authentication failed"));
        }

        lock.lock();
        try {
            this.sessionToken = JsonCodec.getString(response, "session_token");
            this.authenticated = true;
            this.permissions = JsonCodec.getList(response, "permissions");
            this.sessionTtl = JsonCodec.getLong(response, "session_ttl_seconds", 0);
        } finally {
            lock.unlock();
        }

        log.info("Authentication successful");
        return response;
    }

    // -----------------------------------------------------------------------
    // Properties
    // -----------------------------------------------------------------------

    /**
     * Returns whether the client is currently connected to the daemon.
     *
     * @return {@code true} if connected
     */
    public boolean isConnected() {
        return connectionState.get() == ConnectionState.CONNECTED
                && transport != null && transport.isConnected();
    }

    /**
     * Returns whether the client has been authenticated.
     *
     * @return {@code true} if authenticated
     */
    public boolean isAuthenticated() {
        return authenticated;
    }

    /**
     * Returns the current session token, if authenticated.
     *
     * @return the session token, or {@code null}
     */
    public String getSessionToken() {
        return sessionToken;
    }

    /**
     * Returns the permissions granted to the current session.
     *
     * @return unmodifiable list of permission strings
     */
    public List<String> getPermissions() {
        lock.lock();
        try {
            return Collections.unmodifiableList(new ArrayList<>(permissions));
        } finally {
            lock.unlock();
        }
    }

    // -----------------------------------------------------------------------
    // Inference API
    // -----------------------------------------------------------------------

    /**
     * Sends an inference request and returns the complete response.
     * <p>
     * This is a blocking synchronous call that waits for the daemon
     * to generate the full response.
     *
     * @param request the inference request parameters
     * @return the inference response
     * @throws AinosConnectionException if the connection is lost
     * @throws AinosTimeoutException    if the operation times out
     * @throws AinosInferenceException  if the daemon returns an error
     */
    public InferenceResponse infer(InferenceRequest request)
            throws AinosConnectionException, AinosTimeoutException, AinosInferenceException {
        Objects.requireNonNull(request, "request must not be null");

        Map<String, Object> params = new LinkedHashMap<>();
        params.put("model", request.getModel());
        params.put("prompt", request.getPrompt());
        request.getTemperature().ifPresent(t -> params.put("temperature", t));
        request.getMaxTokens().ifPresent(m -> params.put("max_tokens", m));
        request.getSessionId().ifPresent(s -> params.put("session_id", s));

        Map<String, Object> payload = codec.buildRequest("Inference", params);
        Map<String, Object> response = sendRequest(payload);

        return parseInferenceResponse(response);
    }

    /**
     * Sends a streaming inference request.
     * <p>
     * Returns an {@link InferenceStream} that yields chunks as they arrive
     * from the daemon. The stream must be consumed or closed.
     *
     * @param request the inference request parameters
     * @return a streaming inference session
     * @throws AinosConnectionException if the connection is lost
     * @throws AinosTimeoutException    if the initial request times out
     */
    public InferenceStream inferStream(InferenceRequest request)
            throws AinosConnectionException, AinosTimeoutException {
        Objects.requireNonNull(request, "request must not be null");

        Map<String, Object> params = new LinkedHashMap<>();
        params.put("model", request.getModel());
        params.put("prompt", request.getPrompt());
        request.getTemperature().ifPresent(t -> params.put("temperature", t));
        request.getMaxTokens().ifPresent(m -> params.put("max_tokens", m));
        request.getSessionId().ifPresent(s -> params.put("session_id", s));

        Map<String, Object> payload = codec.buildRequest("InferenceStream", params);

        TcpTransport.ResponseReader reader = sendStreamRequest(payload);
        StreamReader streamReader = new StreamReader(reader, codec);
        return new InferenceStream(streamReader);
    }

    /**
     * Performs batch inference, sending multiple requests and collecting responses.
     * <p>
     * Requests are sent sequentially on the current connection.
     *
     * @param requests the list of inference requests
     * @return a list of inference responses in the same order as the requests
     * @throws AinosConnectionException if the connection is lost
     * @throws AinosTimeoutException    if the operation times out
     * @throws AinosInferenceException  if any request fails
     */
    public List<InferenceResponse> batchInfer(List<InferenceRequest> requests)
            throws AinosConnectionException, AinosTimeoutException, AinosInferenceException {
        Objects.requireNonNull(requests, "requests must not be null");

        List<InferenceResponse> results = new ArrayList<>(requests.size());
        for (InferenceRequest req : requests) {
            results.add(infer(req));
        }
        return results;
    }

    // -----------------------------------------------------------------------
    // System Status
    // -----------------------------------------------------------------------

    /**
     * Queries the daemon's health and statistics.
     *
     * @return a SystemStatus instance with daemon state
     * @throws AinosConnectionException if the connection is lost
     * @throws AinosTimeoutException    if the operation times out
     */
    public SystemStatus status()
            throws AinosConnectionException, AinosTimeoutException {
        Map<String, Object> payload = codec.buildRequest("Status");
        Map<String, Object> response = sendRequest(payload);

        if (JsonCodec.isError(response)) {
            throw new AinosConnectionException(
                    "Status query failed: " + JsonCodec.getErrorMessage(response));
        }

        return parseStatusResponse(response);
    }

    /**
     * Performs a health check against the daemon.
     * <p>
     * Unlike {@link #status()}, this method handles connection errors gracefully
     * and returns an unhealthy status instead of throwing.
     *
     * @return a HealthStatus indicating whether the daemon is healthy
     */
    public HealthStatus health() {
        try {
            // Ensure we have a connection
            if (!isConnected()) {
                connect();
            }

            Map<String, Object> payload = codec.buildRequest("Status");
            Map<String, Object> response = sendRequest(payload);

            if (JsonCodec.isError(response)) {
                return HealthStatus.unhealthy(JsonCodec.getErrorMessage(response));
            }

            long uptime = JsonCodec.getLong(response, "uptime", 0);
            int modelsLoaded = JsonCodec.getInt(response, "models_loaded", 0);
            boolean networkAvailable = JsonCodec.getBoolean(response, "network_available", false);

            return new HealthStatus(true, "OK", uptime, modelsLoaded, networkAvailable);
        } catch (AinosConnectionException | AinosTimeoutException | AinosAuthException e) {
            return HealthStatus.unhealthy(e.getMessage());
        }
    }

    /**
     * Queries the current rate limit status for this session.
     *
     * @return a RateLimitStatus with per-category rate limit information
     * @throws AinosConnectionException if the connection is lost
     * @throws AinosTimeoutException    if the operation times out
     */
    public RateLimitStatus rateLimitStatus()
            throws AinosConnectionException, AinosTimeoutException {
        Map<String, Object> payload = codec.buildRequest("RateLimitStatus");
        Map<String, Object> response = sendRequest(payload);

        if (JsonCodec.isError(response)) {
            throw new AinosConnectionException(
                    "Rate limit query failed: " + JsonCodec.getErrorMessage(response));
        }

        return parseRateLimitStatus(response);
    }

    // -----------------------------------------------------------------------
    // Model Management
    // -----------------------------------------------------------------------

    /**
     * Lists all registered models managed by the daemon.
     *
     * @return a list of ModelInfo objects
     * @throws AinosConnectionException if the connection is lost
     * @throws AinosTimeoutException    if the operation times out
     */
    public List<ModelInfo> modelList()
            throws AinosConnectionException, AinosTimeoutException {
        Map<String, Object> payload = codec.buildRequest("ModelList");
        Map<String, Object> response = sendRequest(payload);

        if (JsonCodec.isError(response)) {
            throw new AinosConnectionException(
                    "Model list failed: " + JsonCodec.getErrorMessage(response));
        }

        if (!"ModelListResponse".equals(JsonCodec.getType(response))) {
            throw new AinosConnectionException(
                    "Unexpected response type: " + JsonCodec.getType(response));
        }

        return parseModelListResponse(response);
    }

    /**
     * Loads a model into memory by its file path.
     *
     * @param path the absolute path to the model file on disk
     * @param opts optional model loading options (may be null)
     * @return a ModelInfo describing the loaded model
     * @throws AinosConnectionException if the connection is lost
     * @throws AinosTimeoutException    if the operation times out
     */
    public ModelInfo modelLoad(String path, ModelLoadOptions opts)
            throws AinosConnectionException, AinosTimeoutException {
        Objects.requireNonNull(path, "path must not be null");

        Map<String, Object> params = new LinkedHashMap<>();
        params.put("path", path);

        if (opts != null) {
            opts.getArchitecture().ifPresent(a -> params.put("architecture", a));
            opts.getGpuLayerCount().ifPresent(g -> params.put("gpu_layers", g));
            opts.getContextSize().ifPresent(c -> params.put("context_size", c));
            opts.getUseMmap().ifPresent(m -> params.put("use_mmap", m));
            opts.getThreads().ifPresent(t -> params.put("threads", t));
            opts.getEngineType().ifPresent(e -> params.put("engine_type", e));
        }

        Map<String, Object> payload = codec.buildRequest("ModelLoad", params);
        Map<String, Object> response = sendRequest(payload);

        if (JsonCodec.isError(response)) {
            throw new AinosConnectionException(
                    "Model load failed: " + JsonCodec.getErrorMessage(response));
        }

        return parseModelLoadResponse(response);
    }

    /**
     * Loads a model with default options.
     *
     * @param path the absolute path to the model file
     * @return a ModelInfo describing the loaded model
     * @throws AinosConnectionException if the connection is lost
     * @throws AinosTimeoutException    if the operation times out
     */
    public ModelInfo modelLoad(String path)
            throws AinosConnectionException, AinosTimeoutException {
        return modelLoad(path, null);
    }

    /**
     * Unloads a model from memory.
     *
     * @param modelId the model identifier
     * @throws AinosConnectionException if the connection is lost
     * @throws AinosTimeoutException    if the operation times out
     */
    public void modelUnload(String modelId)
            throws AinosConnectionException, AinosTimeoutException {
        Objects.requireNonNull(modelId, "modelId must not be null");

        Map<String, Object> params = Collections.singletonMap("model_id", modelId);
        Map<String, Object> payload = codec.buildRequest("ModelUnload", params);
        Map<String, Object> response = sendRequest(payload);

        if (JsonCodec.isError(response)) {
            throw new AinosConnectionException(
                    "Model unload failed: " + JsonCodec.getErrorMessage(response));
        }
    }

    // -----------------------------------------------------------------------
    // Context Management
    // -----------------------------------------------------------------------

    /**
     * Stores a key-value pair in the daemon's context store.
     *
     * @param sessionId the session identifier
     * @param key       the lookup key
     * @param value     the value to store (binary-safe, base64-encoded)
     * @param ttl       time-to-live in seconds (0 for no expiry)
     * @throws AinosConnectionException if the connection is lost
     * @throws AinosTimeoutException    if the operation times out
     */
    public void contextStore(String sessionId, String key, byte[] value, long ttl)
            throws AinosConnectionException, AinosTimeoutException {
        Objects.requireNonNull(sessionId, "sessionId must not be null");
        Objects.requireNonNull(key, "key must not be null");
        Objects.requireNonNull(value, "value must not be null");

        String valueStr = Base64.getEncoder().encodeToString(value);

        Map<String, Object> params = new LinkedHashMap<>();
        params.put("session_id", sessionId);
        params.put("key", key);
        params.put("value", valueStr);
        if (ttl > 0) {
            params.put("ttl", ttl);
        }

        Map<String, Object> payload = codec.buildRequest("ContextStore", params);
        Map<String, Object> response = sendRequest(payload);

        if (JsonCodec.isError(response)) {
            throw new AinosConnectionException(
                    "Context store failed: " + JsonCodec.getErrorMessage(response));
        }
    }

    /**
     * Retrieves a value by key from the daemon's context store.
     *
     * @param sessionId the session identifier
     * @param key       the lookup key
     * @return the stored value as bytes, or {@code null} if the key was not found
     * @throws AinosConnectionException if the connection is lost
     * @throws AinosTimeoutException    if the operation times out
     */
    public byte[] contextRetrieve(String sessionId, String key)
            throws AinosConnectionException, AinosTimeoutException {
        Objects.requireNonNull(sessionId, "sessionId must not be null");
        Objects.requireNonNull(key, "key must not be null");

        Map<String, Object> params = new LinkedHashMap<>();
        params.put("session_id", sessionId);
        params.put("key", key);

        Map<String, Object> payload = codec.buildRequest("ContextRetrieve", params);
        Map<String, Object> response = sendRequest(payload);

        if (JsonCodec.isError(response)) {
            return null;
        }

        String valueStr = JsonCodec.getString(response, "output");
        if (valueStr == null) {
            return null;
        }

        try {
            return Base64.getDecoder().decode(valueStr);
        } catch (IllegalArgumentException e) {
            // If it's not base64, return the raw string bytes
            return valueStr.getBytes(java.nio.charset.StandardCharsets.UTF_8);
        }
    }

    // -----------------------------------------------------------------------
    // Internal: request sending
    // -----------------------------------------------------------------------

    /**
     * Sends a request and returns the parsed response.
     * Handles auto-reconnect on connection failure.
     */
    private Map<String, Object> sendRequest(Map<String, Object> request)
            throws AinosConnectionException, AinosTimeoutException {
        int attempt = 0;
        AinosConnectionException lastException = null;

        while (attempt <= maxReconnectAttempts) {
            try {
                TcpTransport t = getTransport();
                return t.sendAndReceive(request);
            } catch (AinosConnectionException e) {
                lastException = e;
                if (autoReconnect && attempt < maxReconnectAttempts) {
                    attempt++;
                    log.warn("Connection lost (attempt {}/{}), reconnecting in {}ms...",
                            attempt, maxReconnectAttempts, reconnectDelayMs);
                    sleep(reconnectDelayMs * (1L << (attempt - 1))); // exponential backoff
                    reconnect();
                } else {
                    throw e;
                }
            }
        }

        throw lastException;
    }

    /**
     * Sends a request and returns a ResponseReader for streaming.
     */
    private TcpTransport.ResponseReader sendStreamRequest(Map<String, Object> request)
            throws AinosConnectionException, AinosTimeoutException {
        TcpTransport t = getTransport();
        return t.sendAndReadLines(request);
    }

    /**
     * Gets the current transport, reconnecting if necessary.
     */
    private TcpTransport getTransport() throws AinosConnectionException {
        lock.lock();
        try {
            if (transport != null && transport.isConnected()) {
                return transport;
            }
            if (connectionState.get() == ConnectionState.CLOSED) {
                throw new AinosConnectionException("Client is closed");
            }
            if (autoReconnect) {
                reconnect();
                return transport;
            }
            throw new AinosConnectionException("Not connected to daemon");
        } finally {
            lock.unlock();
        }
    }

    /**
     * Reconnects the transport.
     */
    private void reconnect() throws AinosConnectionException {
        lock.lock();
        try {
            // Close existing transport
            if (transport != null) {
                try {
                    transport.close();
                } catch (Exception ignored) {
                }
            }

            // Create new transport
            transport = TransportFactory.create(host, port, connectTimeoutMs, readTimeoutMs, true);
            transport.connect();
            connectionState.set(ConnectionState.CONNECTED);
            log.info("Reconnected to Ainos daemon at {}:{}", host, port);

            // Re-authenticate if we were previously authenticated
            if (authenticated && authToken != null) {
                try {
                    authenticate(authToken);
                } catch (AinosAuthException e) {
                    log.warn("Re-authentication failed after reconnect: {}", e.getMessage());
                }
            }
        } catch (AinosTimeoutException e) {
            connectionState.set(ConnectionState.DISCONNECTED);
            throw new AinosConnectionException("Reconnect timed out: " + e.getMessage(), e);
        } finally {
            lock.unlock();
        }
    }

    // -----------------------------------------------------------------------
    // Internal: response parsing
    // -----------------------------------------------------------------------

    private InferenceResponse parseInferenceResponse(Map<String, Object> response)
            throws AinosInferenceException {
        String type = JsonCodec.getType(response);

        if ("Error".equals(type)) {
            int code = JsonCodec.getErrorCode(response);
            String message = JsonCodec.getErrorMessage(response);
            throw new AinosInferenceException(code, message);
        }

        if (!"InferenceResponse".equals(type)) {
            throw new AinosInferenceException("Unexpected response type: " + type);
        }

        String output = JsonCodec.getString(response, "output", "");
        int tokensGenerated = JsonCodec.getInt(response, "tokens_generated", 0);
        long inferenceMs = JsonCodec.getLong(response, "inference_ms", 0L);
        String source = JsonCodec.getString(response, "source", "local");

        return new InferenceResponse(output, tokensGenerated, inferenceMs, source);
    }

    private SystemStatus parseStatusResponse(Map<String, Object> response) {
        long uptime = JsonCodec.getLong(response, "uptime", 0L);
        int modelsLoaded = JsonCodec.getInt(response, "models_loaded", 0);
        long totalRequests = JsonCodec.getLong(response, "total_requests", 0L);
        boolean networkAvailable = JsonCodec.getBoolean(response, "network_available", false);
        int activeSessions = JsonCodec.getInt(response, "active_sessions", 0);

        List<SystemStatus.RateLimitInfo> rateLimits = new ArrayList<>();
        List<Map<String, Object>> rawLimits = JsonCodec.getList(response, "rate_limits");
        if (rawLimits != null) {
            for (Map<String, Object> raw : rawLimits) {
                rateLimits.add(new SystemStatus.RateLimitInfo(
                        JsonCodec.getString(raw, "category", ""),
                        JsonCodec.getLong(raw, "limit", 0),
                        JsonCodec.getLong(raw, "remaining", 0),
                        JsonCodec.getLong(raw, "reset_seconds", 0)
                ));
            }
        }

        return new SystemStatus(uptime, modelsLoaded, totalRequests,
                networkAvailable, activeSessions, rateLimits);
    }

    private List<ModelInfo> parseModelListResponse(Map<String, Object> response) {
        List<ModelInfo> models = new ArrayList<>();
        List<Map<String, Object>> rawModels = JsonCodec.getList(response, "models");
        for (Map<String, Object> raw : rawModels) {
            models.add(new ModelInfo(
                    JsonCodec.getString(raw, "id", ""),
                    JsonCodec.getString(raw, "name", ""),
                    JsonCodec.getString(raw, "path", ""),
                    JsonCodec.getLong(raw, "size_mb", 0),
                    JsonCodec.getBoolean(raw, "loaded", false),
                    JsonCodec.getString(raw, "architecture", "auto")
            ));
        }
        return models;
    }

    private ModelInfo parseModelLoadResponse(Map<String, Object> response) {
        // If there's a model_info embedded, use it
        Map<String, Object> modelInfo = JsonCodec.getMap(response, "model_info");
        if (!modelInfo.isEmpty()) {
            return new ModelInfo(
                    JsonCodec.getString(modelInfo, "id", ""),
                    JsonCodec.getString(modelInfo, "name", ""),
                    JsonCodec.getString(modelInfo, "path", ""),
                    JsonCodec.getLong(modelInfo, "size_mb", 0),
                    JsonCodec.getBoolean(modelInfo, "loaded", false),
                    JsonCodec.getString(modelInfo, "architecture", "auto")
            );
        }

        // Otherwise, build from the top-level response fields
        return new ModelInfo(
                JsonCodec.getString(response, "model_id", ""),
                JsonCodec.getString(response, "model_id", ""),
                "",
                0,
                "loaded".equals(JsonCodec.getString(response, "status", "")),
                "auto"
        );
    }

    private RateLimitStatus parseRateLimitStatus(Map<String, Object> response) {
        List<RateLimitStatus.RateLimitEntry> entries = new ArrayList<>();
        List<Map<String, Object>> rawLimits = JsonCodec.getList(response, "limits");
        for (Map<String, Object> raw : rawLimits) {
            entries.add(new RateLimitStatus.RateLimitEntry(
                    JsonCodec.getString(raw, "category", ""),
                    JsonCodec.getLong(raw, "limit", 0),
                    JsonCodec.getLong(raw, "remaining", 0),
                    JsonCodec.getLong(raw, "reset_seconds", 0)
            ));
        }
        return new RateLimitStatus(entries);
    }

    // -----------------------------------------------------------------------
    // Utility
    // -----------------------------------------------------------------------

    private static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    @Override
    public String toString() {
        return "AinosClient{"
                + "host='" + host + '\''
                + ", port=" + port
                + ", connected=" + isConnected()
                + ", authenticated=" + authenticated
                + '}';
    }
}