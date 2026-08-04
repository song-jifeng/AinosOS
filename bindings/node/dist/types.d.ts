/**
 * Ainos SDK — TypeScript type definitions for the Ainos IPC protocol.
 *
 * These types map directly to the JSON payloads exchanged with the Ainos AI
 * Daemon over the NDJSON TCP protocol.  All field names use camelCase to match
 * the daemon's serde serialization.
 */
/** Configuration options for the {@link AinosClient}. */
export interface ClientOptions {
    /** Daemon hostname or IP address (default: "127.0.0.1"). */
    host?: string;
    /** Daemon TCP port (default: 9500). */
    port?: number;
    /** Connection timeout in milliseconds (default: 5000). */
    connectTimeout?: number;
    /** Read timeout in milliseconds (default: 120000). */
    readTimeout?: number;
    /** Whether to attempt automatic reconnection on failure (default: true). */
    autoReconnect?: boolean;
    /** Delay in milliseconds before reconnecting (default: 1000). */
    reconnectDelay?: number;
    /** Maximum number of reconnection attempts (default: 5, 0 = infinite). */
    maxReconnectAttempts?: number;
    /** Bearer token for authentication. */
    authToken?: string;
    /** Whether to authenticate automatically after connecting (default: true). */
    autoAuthenticate?: boolean;
}
/** Request payload for an LLM inference call. */
export interface InferenceRequest {
    /** Input text for the model. */
    prompt: string;
    /** Model identifier (default: "default"). */
    model?: string;
    /** Sampling temperature (0.0 – 2.0). */
    temperature?: number;
    /** Maximum number of tokens to generate. */
    maxTokens?: number;
    /** Optional session identifier for context tracking. */
    sessionId?: string;
}
/** Response from a completed LLM inference. */
export interface InferenceResponse {
    /** Generated text output. */
    output: string;
    /** Number of tokens produced. */
    tokensGenerated: number;
    /** Wall-clock inference time in milliseconds. */
    inferenceMs: number;
    /** Either "local" or "cloud". */
    source: string;
}
/** A single chunk from a streaming inference response. */
export interface InferenceChunk {
    /** Text fragment produced by the model. */
    chunk: string;
    /** Whether this is the final chunk. */
    done: boolean;
}
/** Metadata describing a single registered model. */
export interface ModelInfo {
    /** Unique model identifier (e.g. "phi_3_mini_4k_instruct_q4_gguf"). */
    id: string;
    /** Human-readable model name (e.g. "phi-3-mini-4k-instruct-q4.gguf"). */
    name: string;
    /** Absolute file path on disk. */
    path: string;
    /** Model file size in megabytes. */
    sizeMb: number;
    /** Whether the model is currently loaded in memory. */
    loaded: boolean;
    /** Model architecture string (e.g. "auto", "phi3", "llama"). */
    architecture: string;
}
/** Options for loading a model. */
export interface ModelLoadOptions {
    /** Optional model identifier override. If not provided, derived from path. */
    modelId?: string;
    /** Optional architecture hint (e.g. "auto", "phi3", "llama"). */
    architecture?: string;
}
/** Response from a model load request. */
export interface ModelLoadResponse {
    /** The model identifier. */
    modelId: string;
    /** Status: "loaded", "already_loaded", or "error". */
    status: string;
    /** Human-readable status message. */
    message: string;
    /** Full model info, if available. */
    modelInfo?: ModelInfo;
}
/** Response from a model unload request. */
export interface ModelUnloadResponse {
    /** The model identifier. */
    modelId: string;
    /** Status: "unloaded", "not_found", or "error". */
    status: string;
    /** Human-readable status message. */
    message: string;
}
/** Daemon health and statistics. */
export interface SystemStatus {
    /** Seconds since the daemon started. */
    uptime: number;
    /** Number of models currently loaded in memory. */
    modelsLoaded: number;
    /** Total inference requests handled. */
    totalRequests: number;
    /** Whether the internet is reachable. */
    networkAvailable: boolean;
    /** Number of active sessions. */
    activeSessions?: number;
    /** Per-category rate limit information, if available. */
    rateLimits?: RateLimitInfo[];
}
/** Health check response. */
export interface HealthStatus {
    /** Whether the daemon is running and accepting connections. */
    ok: boolean;
    /** Daemon version string. */
    version?: string;
    /** Human-readable status message. */
    message?: string;
    /** Uptime in seconds. */
    uptime?: number;
}
/** Per-category rate limit information. */
export interface RateLimitInfo {
    /** Rate limit category (e.g. "inference", "model_ops", "status", "admin"). */
    category: string;
    /** Maximum requests allowed in the window. */
    limit: number;
    /** Requests remaining in the current window. */
    remaining: number;
    /** Seconds until the rate limit window resets. */
    resetSeconds: number;
}
/** Rate limit status response. */
export interface RateLimitStatus {
    /** List of per-category rate limits. */
    limits: RateLimitInfo[];
}
/** Authentication request payload. */
export interface AuthRequest {
    /** Bearer token for authentication. */
    token: string;
}
/** Authentication response from the daemon. */
export interface AuthResponse {
    /** Whether authentication was successful. */
    success: boolean;
    /** Session token for subsequent requests. */
    sessionToken?: string;
    /** Human-readable status message. */
    message: string;
    /** Permissions granted to the session. */
    permissions: string[];
    /** Session TTL in seconds. */
    sessionTtlSeconds: number;
}
/** A single key-value entry in the daemon's context store. */
export interface ContextEntry {
    /** The lookup key. */
    key: string;
    /** The stored value. */
    value: string;
    /** Session identifier (default: "default"). */
    sessionId?: string;
}
/**
 * Raw IPC message types as defined by the daemon's serde enum.
 * These are used internally by the transport layer.
 */
export declare const IPC_MESSAGE_TYPES: {
    readonly AUTH: "Auth";
    readonly AUTH_RESPONSE: "AuthResponse";
    readonly INFERENCE: "Inference";
    readonly INFERENCE_RESPONSE: "InferenceResponse";
    readonly INFERENCE_STREAM: "InferenceStream";
    readonly INFERENCE_CHUNK: "InferenceChunk";
    readonly MODEL_LIST: "ModelList";
    readonly MODEL_LIST_RESPONSE: "ModelListResponse";
    readonly MODEL_LOAD: "ModelLoad";
    readonly MODEL_LOAD_RESPONSE: "ModelLoadResponse";
    readonly MODEL_UNLOAD: "ModelUnload";
    readonly MODEL_UNLOAD_RESPONSE: "ModelUnloadResponse";
    readonly STATUS: "Status";
    readonly STATUS_RESPONSE: "StatusResponse";
    readonly RATE_LIMIT_STATUS: "RateLimitStatus";
    readonly RATE_LIMIT_STATUS_RESPONSE: "RateLimitStatusResponse";
    readonly CONTEXT_STORE: "ContextStore";
    readonly CONTEXT_RETRIEVE: "ContextRetrieve";
    readonly ERROR: "Error";
};
export type IpcMessageType = typeof IPC_MESSAGE_TYPES[keyof typeof IPC_MESSAGE_TYPES];
/** Raw IPC message envelope (the JSON object on the wire). */
export interface IpcMessage {
    type: IpcMessageType;
    [key: string]: unknown;
}
/** Events emitted by the AinosClient. */
export interface AinosClientEvents {
    /** Emitted when the TCP connection is established. */
    connect: [];
    /** Emitted when the TCP connection is closed. */
    disconnect: [];
    /** Emitted when reconnection is attempted. */
    reconnect: [attempt: number, maxAttempts: number];
    /** Emitted when authentication succeeds. */
    authenticated: [sessionToken: string];
    /** Emitted when authentication fails. */
    authError: [message: string];
    /** Emitted when an error occurs at the connection level. */
    error: [error: Error];
    /** Emitted when the daemon sends a rate-limit warning. */
    rateLimited: [retryAfter: number];
}
/** Events emitted by a streaming inference operation. */
export interface InferenceStreamEvents {
    /** Emitted for each text chunk received. */
    data: [chunk: string];
    /** Emitted when the stream completes. */
    end: [];
    /** Emitted when an error occurs. */
    error: [error: Error];
    /** Emitted with progress metadata. */
    progress: [tokensGenerated: number, elapsedMs: number];
}
//# sourceMappingURL=types.d.ts.map