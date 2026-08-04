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
import { EventEmitter } from 'events';
import { InferenceStream } from './stream';
import { ClientOptions, InferenceRequest, InferenceResponse, ModelInfo, ModelLoadOptions, ModelLoadResponse, SystemStatus, HealthStatus, RateLimitStatus, AuthResponse } from './types';
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
export declare class AinosClient extends EventEmitter {
    private transport;
    private tokenManager;
    private authenticator;
    private opts;
    private _connected;
    private _authenticated;
    private _sessionToken;
    private _permissions;
    private _sessionTtl;
    private requestTimeout;
    private modelCache;
    private modelCacheTime;
    private readonly MODEL_CACHE_TTL;
    constructor(options?: ClientOptions);
    /** Whether the TCP connection is currently open. */
    get connected(): boolean;
    /** Whether the client has been authenticated with the daemon. */
    get authenticated(): boolean;
    /** The current session token, if authenticated. */
    get sessionToken(): string | null;
    /** The permissions granted to the current session. */
    get permissions(): string[];
    /** Session TTL in seconds. */
    get sessionTtl(): number;
    /** The host address. */
    get host(): string;
    /** The port number. */
    get port(): number;
    /**
     * Open a TCP connection to the daemon.
     *
     * If `authToken` and `autoAuthenticate` are set, this will also attempt
     * authentication after connecting.
     *
     * @throws {ConnectionError} If the connection cannot be established.
     * @throws {AuthError} If auto-authentication fails.
     */
    connect(): Promise<void>;
    /**
     * Close the TCP connection.
     */
    disconnect(): void;
    /**
     * Authenticate with the daemon using a bearer token.
     *
     * @param token - The bearer token. If not provided, uses the configured token.
     * @returns The authentication response.
     * @throws {AuthError} If authentication fails.
     * @throws {ConnectionError} If the connection is lost.
     */
    authenticate(token?: string): Promise<AuthResponse>;
    /**
     * Send an inference request and wait for the complete response.
     *
     * @param req - The inference request parameters.
     * @returns The inference response with generated text.
     * @throws {InferenceError} If the daemon returns an error.
     * @throws {ConnectionError} If the connection is lost.
     * @throws {TimeoutError} If the request times out.
     */
    infer(req: InferenceRequest): Promise<InferenceResponse>;
    /**
     * Send an inference request and return a streaming interface.
     *
     * The returned {@link InferenceStream} emits `data` events for each text
     * chunk and `end` when the stream completes.
     *
     * @param req - The inference request parameters.
     * @returns An InferenceStream that emits chunks as they arrive.
     */
    inferStream(req: InferenceRequest): InferenceStream;
    /**
     * Send an inference request and return the full response as a string.
     *
     * Internally uses streaming but accumulates the result.  This is useful
     * when you want streaming semantics but a single-string result.
     *
     * @param req - The inference request parameters.
     * @returns The full generated text.
     */
    inferText(req: InferenceRequest): Promise<string>;
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
    batchInfer(reqs: InferenceRequest[]): Promise<InferenceResponse[]>;
    /**
     * List all registered models.
     *
     * Results are cached for 5 seconds to avoid redundant queries.
     *
     * @returns A list of ModelInfo objects.
     * @throws {DaemonError} If the daemon returns an error.
     */
    modelList(): Promise<ModelInfo[]>;
    /**
     * Load a model into memory from disk.
     *
     * @param path - Absolute path to the model file on disk.
     * @param opts - Optional load options (modelId, architecture).
     * @returns The model load response.
     * @throws {DaemonError} If loading fails.
     */
    modelLoad(path: string, opts?: ModelLoadOptions): Promise<ModelLoadResponse>;
    /**
     * Unload a model from memory.
     *
     * @param id - The model identifier.
     * @throws {DaemonError} If unloading fails.
     */
    modelUnload(id: string): Promise<void>;
    /**
     * Store a key-value pair in the daemon's context store.
     *
     * @param sessionId - Session identifier for the context.
     * @param key - The lookup key.
     * @param value - The value to store (string or Buffer).
     * @param ttl - Optional TTL in seconds.
     * @throws {DaemonError} If the store operation fails.
     */
    contextStore(sessionId: string, key: string, value: string | Buffer, ttl?: number): Promise<void>;
    /**
     * Retrieve a value by key from the daemon's context store.
     *
     * @param sessionId - Session identifier for the context.
     * @param key - The lookup key.
     * @returns The stored value as a Buffer, or `null` if not found.
     * @throws {DaemonError} If the retrieve operation fails.
     */
    contextRetrieve(sessionId: string, key: string): Promise<Buffer | null>;
    /**
     * Query the daemon's health and statistics.
     *
     * @returns System status information.
     * @throws {DaemonError} If the query fails.
     */
    status(): Promise<SystemStatus>;
    /**
     * Quick health check.
     *
     * @returns A simple health status object.
     */
    health(): Promise<HealthStatus>;
    /**
     * Query the current rate limit status for this session.
     *
     * @returns Rate limit information for each category.
     * @throws {DaemonError} If the query fails.
     */
    rateLimitStatus(): Promise<RateLimitStatus>;
    /**
     * Send a JSON-serialisable payload and receive the response line.
     */
    private sendAndReceive;
    /**
     * Parse a JSON response line, handling errors.
     */
    private parseResponse;
    /**
     * Build the payload for an inference request.
     */
    private buildInferencePayload;
    /**
     * Parse a model info object from the daemon's JSON representation.
     * The daemon uses snake_case field names.
     */
    private parseModelInfo;
    /**
     * Parse a list of models from the daemon's JSON representation.
     */
    private parseModelList;
    /**
     * Parse rate limit info objects from the daemon's JSON representation.
     */
    private parseRateLimitInfos;
    private handleTransportConnect;
    private handleTransportDisconnect;
    /**
     * Get the daemon's version information.
     * This queries the status endpoint and returns available metadata.
     */
    getVersion(): Promise<string>;
    /**
     * Check if the daemon is reachable and responsive.
     * Unlike `health()`, this does not catch errors — it throws on failure.
     */
    ping(): Promise<boolean>;
    /**
     * Return a JSON-serialisable summary of the client state.
     */
    toJSON(): Record<string, unknown>;
}
/**
 * Create and connect an AinosClient in one call.
 *
 * @param options - Client configuration options.
 * @returns A connected (and optionally authenticated) AinosClient.
 */
export declare function createClient(options?: ClientOptions): Promise<AinosClient>;
//# sourceMappingURL=client.d.ts.map