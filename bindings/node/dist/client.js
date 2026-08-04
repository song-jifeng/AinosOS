"use strict";
/**
 * Ainos SDK — Main client class.
 *
 * `AinosClient` is the primary entry point for communicating with the Ainos AI
 * Daemon over TCP.  It wraps the NDJSON transport layer and provides a
 * high-level, promise-based API for all daemon operations.
 *
 * @example
 * ```ts
 * import { AinosClient } from 'ainos-sdk';
 *
 * const client = new AinosClient({ authToken: 'your-token' });
 * await client.connect();
 *
 * const resp = await client.infer({ prompt: 'Hello, Ainos!' });
 * console.log(resp.output);
 *
 * await client.disconnect();
 * ```
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.AinosClient = void 0;
exports.createClient = createClient;
const events_1 = require("events");
const transport_1 = require("./transport");
const stream_1 = require("./stream");
const auth_1 = require("./auth");
const errors_1 = require("./errors");
const utils_1 = require("./utils");
// ============================================================================
// AinosClient
// ============================================================================
/**
 * High-level TCP client for the Ainos AI Daemon.
 *
 * Features:
 * - Connection management with auto-reconnect and exponential backoff
 * - Bearer token authentication
 * - Synchronous and streaming inference
 * - Model lifecycle management (list, load, unload)
 * - Context store (key-value persistence)
 * - System status and health checks
 * - Rate limit inspection
 * - EventEmitter-based architecture
 * - Timeout support for all operations
 *
 * @emits {@link AinosClientEvents.connect} When the TCP connection is established.
 * @emits {@link AinosClientEvents.disconnect} When the TCP connection is closed.
 * @emits {@link AinosClientEvents.reconnect} When reconnection is attempted.
 * @emits {@link AinosClientEvents.authenticated} When authentication succeeds.
 * @emits {@link AinosClientEvents.authError} When authentication fails.
 * @emits {@link AinosClientEvents.error} When a connection-level error occurs.
 * @emits {@link AinosClientEvents.rateLimited} When a rate-limit response is received.
 */
class AinosClient extends events_1.EventEmitter {
    transport;
    tokenManager;
    authenticator;
    opts;
    _connected = false;
    _authenticated = false;
    _sessionToken = null;
    _permissions = [];
    _sessionTtl = 0;
    requestTimeout;
    // Cache for model list
    modelCache = null;
    modelCacheTime = 0;
    MODEL_CACHE_TTL = 5000; // 5 seconds
    constructor(options = {}) {
        super();
        this.setMaxListeners(100);
        this.opts = {
            host: options.host ?? '127.0.0.1',
            port: options.port ?? 9500,
            connectTimeout: options.connectTimeout ?? 5000,
            readTimeout: options.readTimeout ?? 120000,
            autoReconnect: options.autoReconnect ?? true,
            reconnectDelay: options.reconnectDelay ?? 1000,
            maxReconnectAttempts: options.maxReconnectAttempts ?? 5,
            authToken: options.authToken ?? '',
            autoAuthenticate: options.autoAuthenticate ?? true,
        };
        this.requestTimeout = this.opts.readTimeout;
        // Transport layer
        this.transport = new transport_1.TcpTransport(this.opts);
        this.transport.on('connect', this.handleTransportConnect.bind(this));
        this.transport.on('disconnect', this.handleTransportDisconnect.bind(this));
        this.transport.on('reconnect', (attempt, max) => {
            this.emit('reconnect', attempt, max);
        });
        this.transport.on('error', (err) => {
            this.emit('error', err);
        });
        // Authentication
        this.tokenManager = new auth_1.TokenManager();
        if (this.opts.authToken) {
            this.tokenManager.setToken(this.opts.authToken);
        }
        this.authenticator = new auth_1.Authenticator(this.tokenManager);
    }
    // --------------------------------------------------------------------------
    // Properties
    // --------------------------------------------------------------------------
    /** Whether the TCP connection is currently open. */
    get connected() {
        return this._connected && this.transport.connected;
    }
    /** Whether the client has been authenticated with the daemon. */
    get authenticated() {
        return this._authenticated;
    }
    /** The current session token, if authenticated. */
    get sessionToken() {
        return this._sessionToken;
    }
    /** The permissions granted to the current session. */
    get permissions() {
        return [...this._permissions];
    }
    /** Session TTL in seconds. */
    get sessionTtl() {
        return this._sessionTtl;
    }
    /** The host address. */
    get host() {
        return this.opts.host;
    }
    /** The port number. */
    get port() {
        return this.opts.port;
    }
    // --------------------------------------------------------------------------
    // Lifecycle
    // --------------------------------------------------------------------------
    /**
     * Open a TCP connection to the daemon.
     *
     * If `authToken` and `autoAuthenticate` are set, this will also attempt
     * authentication after connecting.
     *
     * @throws {ConnectionError} If the connection cannot be established.
     * @throws {AuthError} If auto-authentication fails.
     */
    async connect() {
        if (this._connected) {
            return;
        }
        await this.transport.connect();
        this._connected = true;
        // Auto-authenticate if configured
        if (this.opts.authToken && this.opts.autoAuthenticate) {
            try {
                await this.authenticate(this.opts.authToken);
            }
            catch (err) {
                // Don't fail the connection if auth fails — the user may want to
                // handle it later
                if (err instanceof errors_1.AuthError) {
                    this.emit('authError', err.message);
                }
                throw err;
            }
        }
    }
    /**
     * Close the TCP connection.
     */
    disconnect() {
        this._connected = false;
        this._authenticated = false;
        this._sessionToken = null;
        this._permissions = [];
        this._sessionTtl = 0;
        this.transport.disconnect();
        this.emit('disconnect');
    }
    /**
     * Authenticate with the daemon using a bearer token.
     *
     * @param token - The bearer token. If not provided, uses the configured token.
     * @returns The authentication response.
     * @throws {AuthError} If authentication fails.
     * @throws {ConnectionError} If the connection is lost.
     */
    async authenticate(token) {
        const useToken = token ?? this.opts.authToken;
        if (!useToken) {
            throw new errors_1.AuthError('No authentication token provided');
        }
        // Ensure we have a token set in the manager
        try {
            this.tokenManager.setToken(useToken);
        }
        catch (err) {
            if (err instanceof errors_1.AuthError)
                throw err;
        }
        const authResponse = await this.authenticator.authenticate(async (payload) => {
            const line = await this.sendAndReceive(payload);
            return (0, utils_1.safeDecodeJson)(line, { type: 'Error' });
        });
        this._authenticated = true;
        this._sessionToken = authResponse.sessionToken ?? null;
        this._permissions = authResponse.permissions;
        this._sessionTtl = authResponse.sessionTtlSeconds;
        this.emit('authenticated', this._sessionToken ?? '');
        return authResponse;
    }
    // --------------------------------------------------------------------------
    // Inference
    // --------------------------------------------------------------------------
    /**
     * Send an inference request and wait for the complete response.
     *
     * @param req - The inference request parameters.
     * @returns The inference response with generated text.
     * @throws {InferenceError} If the daemon returns an error.
     * @throws {ConnectionError} If the connection is lost.
     * @throws {TimeoutError} If the request times out.
     */
    async infer(req) {
        const payload = this.buildInferencePayload(req);
        const line = await this.sendAndReceive(payload);
        const data = this.parseResponse(line);
        if (data.type === 'Error') {
            throw new errors_1.InferenceError(String(data.message ?? 'Unknown inference error'), Number(data.code ?? -1));
        }
        if (data.type !== 'InferenceResponse') {
            throw new errors_1.InferenceError(`Unexpected response type: ${String(data.type)}`);
        }
        return {
            output: String(data.output ?? ''),
            tokensGenerated: Number(data.tokens_generated ?? 0),
            inferenceMs: Number(data.inference_ms ?? 0),
            source: String(data.source ?? 'local'),
        };
    }
    /**
     * Send an inference request and return a streaming interface.
     *
     * The returned {@link InferenceStream} emits `data` events for each text
     * chunk and `end` when the stream completes.
     *
     * @param req - The inference request parameters.
     * @returns An InferenceStream that emits chunks as they arrive.
     */
    inferStream(req) {
        const payload = this.buildInferencePayload(req);
        const stream = new stream_1.InferenceStream(this.transport, payload);
        // Start reading in next tick to allow the caller to attach listeners
        process.nextTick(() => {
            stream.start();
        });
        return stream;
    }
    /**
     * Send an inference request and return the full response as a string.
     *
     * Internally uses streaming but accumulates the result.  This is useful
     * when you want streaming semantics but a single-string result.
     *
     * @param req - The inference request parameters.
     * @returns The full generated text.
     */
    async inferText(req) {
        const stream = this.inferStream(req);
        return (0, stream_1.accumulateStream)(stream);
    }
    /**
     * Send multiple inference requests and collect all responses.
     *
     * Requests are sent sequentially to avoid overwhelming the daemon.
     * For parallel execution, use multiple `infer()` calls with
     * `Promise.all()`.
     *
     * @param reqs - Array of inference requests.
     * @returns Array of inference responses, in the same order.
     */
    async batchInfer(reqs) {
        const results = [];
        for (const req of reqs) {
            const result = await this.infer(req);
            results.push(result);
        }
        return results;
    }
    // --------------------------------------------------------------------------
    // Model Management
    // --------------------------------------------------------------------------
    /**
     * List all registered models.
     *
     * Results are cached for 5 seconds to avoid redundant queries.
     *
     * @returns A list of ModelInfo objects.
     * @throws {DaemonError} If the daemon returns an error.
     */
    async modelList() {
        // Return cached result if fresh
        if (this.modelCache && Date.now() - this.modelCacheTime < this.MODEL_CACHE_TTL) {
            return this.modelCache;
        }
        const line = await this.sendAndReceive({ type: 'ModelList' });
        const data = this.parseResponse(line);
        if (data.type === 'Error') {
            throw new errors_1.DaemonError(String(data.message ?? 'Model list failed'), Number(data.code ?? -1));
        }
        if (data.type !== 'ModelListResponse') {
            throw new errors_1.DaemonError(`Unexpected response type: ${String(data.type)}`);
        }
        const models = this.parseModelList(data.models);
        this.modelCache = models;
        this.modelCacheTime = Date.now();
        return models;
    }
    /**
     * Load a model into memory from disk.
     *
     * @param path - Absolute path to the model file on disk.
     * @param opts - Optional load options (modelId, architecture).
     * @returns The model load response.
     * @throws {DaemonError} If loading fails.
     */
    async modelLoad(path, opts) {
        const payload = { type: 'ModelLoad', path };
        if (opts?.modelId)
            payload.model_id = opts.modelId;
        if (opts?.architecture)
            payload.architecture = opts.architecture;
        const line = await this.sendAndReceive(payload);
        const data = this.parseResponse(line);
        if (data.type === 'Error') {
            throw new errors_1.DaemonError(String(data.message ?? 'Model load failed'), Number(data.code ?? -1));
        }
        if (data.type !== 'ModelLoadResponse') {
            throw new errors_1.DaemonError(`Unexpected response type: ${String(data.type)}`);
        }
        // Invalidate model cache
        this.modelCache = null;
        return {
            modelId: String(data.model_id ?? ''),
            status: String(data.status ?? 'error'),
            message: String(data.message ?? ''),
            modelInfo: data.model_info
                ? this.parseModelInfo(data.model_info)
                : undefined,
        };
    }
    /**
     * Unload a model from memory.
     *
     * @param id - The model identifier.
     * @throws {DaemonError} If unloading fails.
     */
    async modelUnload(id) {
        const line = await this.sendAndReceive({ type: 'ModelUnload', model_id: id });
        const data = this.parseResponse(line);
        if (data.type === 'Error') {
            throw new errors_1.DaemonError(String(data.message ?? 'Model unload failed'), Number(data.code ?? -1));
        }
        if (data.type !== 'ModelUnloadResponse') {
            throw new errors_1.DaemonError(`Unexpected response type: ${String(data.type)}`);
        }
        if (data.status === 'error') {
            throw new errors_1.DaemonError(String(data.message ?? 'Model unload failed'));
        }
        // Invalidate model cache
        this.modelCache = null;
    }
    // --------------------------------------------------------------------------
    // Context Management
    // --------------------------------------------------------------------------
    /**
     * Store a key-value pair in the daemon's context store.
     *
     * @param sessionId - Session identifier for the context.
     * @param key - The lookup key.
     * @param value - The value to store (string or Buffer).
     * @param ttl - Optional TTL in seconds.
     * @throws {DaemonError} If the store operation fails.
     */
    async contextStore(sessionId, key, value, ttl) {
        const encodedValue = (0, utils_1.encodeContextValue)(value);
        const payload = {
            type: 'ContextStore',
            key: `${sessionId}:${key}`,
            value: encodedValue,
        };
        if (ttl !== undefined) {
            payload.ttl = ttl;
        }
        const line = await this.sendAndReceive(payload);
        const data = this.parseResponse(line);
        if (data.type === 'Error') {
            throw new errors_1.DaemonError(String(data.message ?? 'Context store failed'), Number(data.code ?? -1));
        }
    }
    /**
     * Retrieve a value by key from the daemon's context store.
     *
     * @param sessionId - Session identifier for the context.
     * @param key - The lookup key.
     * @returns The stored value as a Buffer, or `null` if not found.
     * @throws {DaemonError} If the retrieve operation fails.
     */
    async contextRetrieve(sessionId, key) {
        const payload = {
            type: 'ContextRetrieve',
            key: `${sessionId}:${key}`,
        };
        const line = await this.sendAndReceive(payload);
        const data = this.parseResponse(line);
        if (data.type === 'Error') {
            return null;
        }
        const output = data.output;
        if (output === undefined) {
            return null;
        }
        const decoded = (0, utils_1.decodeContextValue)(output);
        if (Buffer.isBuffer(decoded)) {
            return decoded;
        }
        return Buffer.from(decoded, 'utf-8');
    }
    // --------------------------------------------------------------------------
    // Status & Health
    // --------------------------------------------------------------------------
    /**
     * Query the daemon's health and statistics.
     *
     * @returns System status information.
     * @throws {DaemonError} If the query fails.
     */
    async status() {
        const line = await this.sendAndReceive({ type: 'Status' });
        const data = this.parseResponse(line);
        if (data.type === 'Error') {
            throw new errors_1.DaemonError(String(data.message ?? 'Status query failed'), Number(data.code ?? -1));
        }
        if (data.type !== 'StatusResponse') {
            throw new errors_1.DaemonError(`Unexpected response type: ${String(data.type)}`);
        }
        return {
            uptime: Number(data.uptime ?? 0),
            modelsLoaded: Number(data.models_loaded ?? 0),
            totalRequests: Number(data.total_requests ?? 0),
            networkAvailable: Boolean(data.network_available ?? false),
            activeSessions: data.active_sessions !== undefined
                ? Number(data.active_sessions)
                : undefined,
            rateLimits: data.rate_limits
                ? this.parseRateLimitInfos(data.rate_limits)
                : undefined,
        };
    }
    /**
     * Quick health check.
     *
     * @returns A simple health status object.
     */
    async health() {
        try {
            const status = await this.status();
            return {
                ok: true,
                uptime: status.uptime,
                message: 'Daemon is running',
            };
        }
        catch (err) {
            return {
                ok: false,
                message: err instanceof Error ? err.message : 'Unknown error',
            };
        }
    }
    /**
     * Query the current rate limit status for this session.
     *
     * @returns Rate limit information for each category.
     * @throws {DaemonError} If the query fails.
     */
    async rateLimitStatus() {
        const line = await this.sendAndReceive({ type: 'RateLimitStatus' });
        const data = this.parseResponse(line);
        if (data.type === 'Error') {
            throw new errors_1.DaemonError(String(data.message ?? 'Rate limit query failed'), Number(data.code ?? -1));
        }
        // RateLimitStatusResponse may come through as a raw JSON object
        const limits = Array.isArray(data.limits) ? data.limits : [];
        return {
            limits: this.parseRateLimitInfos(limits),
        };
    }
    // --------------------------------------------------------------------------
    // Internal: Transport helpers
    // --------------------------------------------------------------------------
    /**
     * Send a JSON-serialisable payload and receive the response line.
     */
    async sendAndReceive(payload, timeoutMs) {
        return this.transport.sendAndReceive(payload, timeoutMs ?? this.requestTimeout);
    }
    /**
     * Parse a JSON response line, handling errors.
     */
    parseResponse(line) {
        const data = (0, utils_1.decodeJson)(line);
        if (!data) {
            throw new errors_1.DaemonError('Failed to parse daemon response: invalid JSON');
        }
        const type = data.type;
        if (type === 'Error') {
            const code = Number(data.code ?? -1);
            const message = String(data.message ?? 'Daemon error');
            // Map to specific error types based on code
            if (code === 401) {
                throw new errors_1.AuthError(message);
            }
            if (code === 429) {
                const retryAfter = Number(data.retry_after ?? 1);
                throw new errors_1.RateLimitError(message, retryAfter);
            }
        }
        return data;
    }
    /**
     * Build the payload for an inference request.
     */
    buildInferencePayload(req) {
        const payload = {
            type: 'Inference',
            model: req.model ?? 'default',
            prompt: req.prompt,
        };
        if (req.temperature !== undefined) {
            payload.temperature = req.temperature;
        }
        if (req.maxTokens !== undefined) {
            payload.max_tokens = req.maxTokens;
        }
        if (req.sessionId !== undefined) {
            payload.session_id = req.sessionId;
        }
        return payload;
    }
    // --------------------------------------------------------------------------
    // Internal: Model parsing
    // --------------------------------------------------------------------------
    /**
     * Parse a model info object from the daemon's JSON representation.
     * The daemon uses snake_case field names.
     */
    parseModelInfo(raw) {
        return {
            id: String(raw.id ?? ''),
            name: String(raw.name ?? ''),
            path: String(raw.path ?? ''),
            sizeMb: Number(raw.size_mb ?? 0),
            loaded: Boolean(raw.loaded ?? false),
            architecture: String(raw.architecture ?? 'auto'),
        };
    }
    /**
     * Parse a list of models from the daemon's JSON representation.
     */
    parseModelList(raw) {
        if (!Array.isArray(raw))
            return [];
        return raw.map((item) => {
            if ((0, utils_1.isObject)(item)) {
                return this.parseModelInfo(item);
            }
            return {
                id: String(item),
                name: String(item),
                path: '',
                sizeMb: 0,
                loaded: false,
                architecture: 'auto',
            };
        });
    }
    /**
     * Parse rate limit info objects from the daemon's JSON representation.
     */
    parseRateLimitInfos(raw) {
        if (!Array.isArray(raw))
            return [];
        return raw.map((item) => {
            if ((0, utils_1.isObject)(item)) {
                const obj = item;
                return {
                    category: String(obj.category ?? ''),
                    limit: Number(obj.limit ?? 0),
                    remaining: Number(obj.remaining ?? 0),
                    resetSeconds: Number(obj.reset_seconds ?? 0),
                };
            }
            return { category: '', limit: 0, remaining: 0, resetSeconds: 0 };
        });
    }
    // --------------------------------------------------------------------------
    // Internal: Transport event handlers
    // --------------------------------------------------------------------------
    handleTransportConnect() {
        this._connected = true;
        this.emit('connect');
    }
    handleTransportDisconnect() {
        this._connected = false;
        this._authenticated = false;
        this._sessionToken = null;
        this._permissions = [];
        this.emit('disconnect');
    }
    // --------------------------------------------------------------------------
    // Utility Methods
    // --------------------------------------------------------------------------
    /**
     * Get the daemon's version information.
     * This queries the status endpoint and returns available metadata.
     */
    async getVersion() {
        try {
            const status = await this.status();
            return `Ainos Daemon | uptime: ${status.uptime}s | models: ${status.modelsLoaded}`;
        }
        catch {
            return 'unknown';
        }
    }
    /**
     * Check if the daemon is reachable and responsive.
     * Unlike `health()`, this does not catch errors — it throws on failure.
     */
    async ping() {
        await this.sendAndReceive({ type: 'Status' });
        return true;
    }
    /**
     * Return a JSON-serialisable summary of the client state.
     */
    toJSON() {
        return {
            connected: this._connected,
            authenticated: this._authenticated,
            host: this.opts.host,
            port: this.opts.port,
            hasSessionToken: this._sessionToken !== null,
            permissions: this._permissions,
            sessionTtl: this._sessionTtl,
        };
    }
}
exports.AinosClient = AinosClient;
// ============================================================================
// Factory function
// ============================================================================
/**
 * Create and connect an AinosClient in one call.
 *
 * @param options - Client configuration options.
 * @returns A connected (and optionally authenticated) AinosClient.
 */
async function createClient(options = {}) {
    const client = new AinosClient(options);
    await client.connect();
    return client;
}
//# sourceMappingURL=client.js.map