package com.ainos.sdk

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

// ===========================================================================
// Internal Protocol Types
// ===========================================================================

/**
 * Request envelope sent to the Ainos daemon over NDJSON TCP.
 *
 * Every request must include a unique [id] for response matching, the
 * RPC [method] name, optional [params], and an optional [token] for
 * authentication.
 */
@Serializable
internal data class RequestEnvelope(
    val id: String,
    val method: String,
    val params: JsonObject? = null,
    val token: String? = null
)

/**
 * Response envelope received from the Ainos daemon.
 *
 * The [type] field discriminates the response kind:
 * - `"result"`: A complete response with [data] containing the result.
 * - `"error"`: An error response with [error] containing the error details.
 * - `"stream"`: A streaming chunk with [data] containing partial output.
 * - `"stream_end"`: Signals the end of a stream with optional final [data].
 */
@Serializable
internal data class ResponseEnvelope(
    val id: String,
    val type: String,
    val data: JsonElement? = null,
    val error: ErrorDetail? = null
)

/**
 * Error detail within an error response envelope.
 */
@Serializable
public data class ErrorDetail(
    val code: Int,
    val message: String
)

// ===========================================================================
// Public API Models
// ===========================================================================

/**
 * Information about a model managed by the Ainos daemon.
 *
 * @property name Unique model name or identifier used in API calls
 * @property filePath Absolute or relative path to the model file on disk
 * @property loaded Whether the model is currently loaded into memory
 * @property size Model file size in bytes
 * @property quantization Quantization method applied (e.g., "Q4_K_M", "Q8_0", "f16")
 * @property backend Inference backend (e.g., "llama.cpp", "transformers", "onnx")
 * @property architecture Model architecture (e.g., "llama", "mistral", "gpt2")
 * @property parameterCount Human-readable parameter count (e.g., "7B", "13B", "70B")
 */
@Serializable
public data class ModelInfo(
    val name: String,
    @SerialName("path")
    val filePath: String? = null,
    val loaded: Boolean = false,
    val size: Long? = null,
    val quantization: String? = null,
    val backend: String? = null,
    val architecture: String? = null,
    @SerialName("parameter_count")
    val parameterCount: String? = null
)

/**
 * Result of a health check against the Ainos daemon.
 *
 * @property status Overall health status: "ok", "degraded", or "error"
 * @property version Daemon version string in semantic versioning format
 * @property uptime Number of seconds the daemon has been running
 * @property activeConnections Current number of active TCP connections
 */
@Serializable
public data class HealthInfo(
    val status: String,
    val version: String? = null,
    val uptime: Long? = null,
    @SerialName("active_connections")
    val activeConnections: Int? = null
) {
    /**
     * Whether the daemon is fully healthy and ready to serve requests.
     */
    public val isHealthy: Boolean get() = status == "ok"
}

/**
 * Detailed server status information.
 *
 * @property uptime Server uptime in seconds
 * @property version Daemon version string
 * @property activeModels Number of models currently loaded in memory
 * @property totalModels Total number of registered/unloaded models
 * @property memoryUsage Current memory usage statistics
 * @property cpuUsage CPU usage as a fraction between 0.0 and 1.0
 * @property gpuInfo GPU hardware and utilization information
 */
@Serializable
public data class ServerStatus(
    val uptime: Long,
    val version: String,
    @SerialName("active_models")
    val activeModels: Int = 0,
    @SerialName("total_models")
    val totalModels: Int = 0,
    @SerialName("memory_usage")
    val memoryUsage: MemoryUsage? = null,
    @SerialName("cpu_usage")
    val cpuUsage: Float? = null,
    @SerialName("gpu_info")
    val gpuInfo: GpuInfo? = null
)

/**
 * Memory usage statistics for the daemon process.
 *
 * @property current Current memory usage in bytes (RSS)
 * @property peak Peak memory usage since daemon start in bytes
 * @property limit Memory limit in bytes (0 if no limit is configured)
 */
@Serializable
public data class MemoryUsage(
    val current: Long,
    val peak: Long,
    val limit: Long = 0
)

/**
 * GPU hardware and utilization information.
 *
 * @property device GPU device name (e.g., "NVIDIA GeForce RTX 4090")
 * @property memoryUsed GPU memory currently in use in bytes
 * @property memoryTotal Total GPU memory available in bytes
 * @property utilization GPU compute utilization percentage (0-100)
 */
@Serializable
public data class GpuInfo(
    val device: String? = null,
    @SerialName("memory_used")
    val memoryUsed: Long? = null,
    @SerialName("memory_total")
    val memoryTotal: Long? = null,
    val utilization: Int? = null
)

/**
 * Parameters for inference requests to the Ainos daemon.
 *
 * @property prompt The input text prompt to generate from
 * @property maxTokens Maximum number of tokens to generate (1-8192)
 * @property temperature Sampling temperature. Higher values (e.g., 1.5) make
 *   output more random; lower values (e.g., 0.2) make it more deterministic
 * @property topP Nucleus sampling threshold: cumulative probability cutoff
 * @property topK Top-k sampling: only consider the k most likely next tokens
 * @property repeatPenalty Penalty for repeating tokens (1.0 = no penalty)
 * @property presencePenalty Positive penalty for new tokens based on presence
 * @property frequencyPenalty Positive penalty for new tokens based on frequency
 * @property stop Sequences of tokens at which generation stops
 * @property stream Whether to stream the response token-by-token
 * @property sessionId Session ID for continuing a multi-turn conversation
 * @property contextId Context ID for long-term memory integration
 * @property keepPrompt Number of prompt tokens to keep in context (0 = keep all)
 */
@Serializable
public data class InferParams(
    val prompt: String,
    @SerialName("max_tokens")
    val maxTokens: Int = 2048,
    val temperature: Float = 0.7f,
    @SerialName("top_p")
    val topP: Float = 0.9f,
    @SerialName("top_k")
    val topK: Int = 40,
    @SerialName("repeat_penalty")
    val repeatPenalty: Float = 1.1f,
    @SerialName("presence_penalty")
    val presencePenalty: Float = 0.0f,
    @SerialName("frequency_penalty")
    val frequencyPenalty: Float = 0.0f,
    val stop: List<String>? = null,
    val stream: Boolean = false,
    @SerialName("session_id")
    val sessionId: String? = null,
    @SerialName("context_id")
    val contextId: String? = null,
    @SerialName("keep_prompt")
    val keepPrompt: Int = 0
) {
    /**
     * Creates a copy of these params with [stream] forced to true.
     * Used internally by the streaming API.
     */
    internal fun asStream(): InferParams = copy(stream = true)
}

/**
 * Result of a non-streaming (blocking) inference request.
 *
 * @property text The generated text completion
 * @property finishReason Reason generation finished: "stop" (hit stop token),
 *   "length" (hit max_tokens), or "timeout"
 * @property tokens Total number of tokens generated
 * @property tokensPerSecond Generation speed in tokens per second
 * @property sessionId Session ID for continuing the conversation
 * @property promptTokens Number of tokens in the input prompt
 */
@Serializable
public data class InferResult(
    val text: String,
    @SerialName("finish_reason")
    val finishReason: String? = null,
    val tokens: Int? = null,
    @SerialName("tokens_per_second")
    val tokensPerSecond: Float? = null,
    @SerialName("session_id")
    val sessionId: String? = null,
    @SerialName("prompt_tokens")
    val promptTokens: Int? = null
)

/**
 * A single chunk emitted during streaming inference.
 *
 * @property text The text generated in this chunk (may be empty)
 * @property index Zero-based index of this chunk in the stream
 * @property finished Whether generation is complete
 * @property finishReason Reason for finishing (only set when [finished] is true)
 * @property tokens Total tokens generated so far
 * @property tokensPerSecond Generation speed so far
 */
@Serializable
public data class StreamChunk(
    val text: String,
    val index: Int = 0,
    val finished: Boolean = false,
    @SerialName("finish_reason")
    val finishReason: String? = null,
    val tokens: Int? = null,
    @SerialName("tokens_per_second")
    val tokensPerSecond: Float? = null
)

/**
 * Parameters for loading a model into memory on the daemon.
 *
 * @property name Model name or identifier
 * @property path Path to the model file on disk (optional if already registered)
 * @property quantization Quantization to apply when loading (e.g., "Q4_K_M")
 * @property backend Inference backend to use
 * @property gpuLayers Number of layers to offload to GPU (0 = CPU only)
 * @property contextSize Context window size in tokens
 * @property batchSize Batch size for prompt processing
 * @property threads Number of CPU threads to use for inference
 */
@Serializable
public data class ModelLoadParams(
    val name: String,
    val path: String? = null,
    val quantization: String? = null,
    val backend: String? = null,
    @SerialName("gpu_layers")
    val gpuLayers: Int? = null,
    @SerialName("context_size")
    val contextSize: Int? = null,
    @SerialName("batch_size")
    val batchSize: Int? = null,
    val threads: Int? = null
)

/**
 * Data for long-term context/memory storage.
 *
 * Context data persists across sessions and can be retrieved by ID
 * to provide the model with long-term memory of past interactions.
 *
 * @property id Unique context identifier (assigned by server for store,
 *   specified for retrieve)
 * @property content The context content (e.g., conversation history, facts)
 * @property metadata Optional key-value metadata for filtering and search
 * @property timestamp Creation/update timestamp in epoch milliseconds
 * @property model Model this context is associated with
 */
@Serializable
public data class ContextData(
    val id: String = "",
    val content: String,
    val metadata: Map<String, String>? = null,
    val timestamp: Long? = null,
    val model: String? = null
)

/**
 * Result of listing available models on the daemon.
 *
 * @property models List of available models with their metadata
 * @property total Total number of models (may be > models.size if paginated)
 */
@Serializable
public data class ModelListResult(
    val models: List<ModelInfo> = emptyList(),
    val total: Int = 0
)

/**
 * Result of unloading a model from memory.
 *
 * @property name Name of the unloaded model
 * @property success Whether the unload operation was successful
 * @property message Optional human-readable message (e.g., "unloaded", "not found")
 */
@Serializable
public data class ModelUnloadResult(
    val name: String,
    val success: Boolean = true,
    val message: String? = null
)

/**
 * Result of storing context data on the daemon.
 *
 * @property id The assigned context ID for later retrieval
 * @property success Whether the store operation was successful
 */
@Serializable
public data class ContextStoreResult(
    val id: String,
    val success: Boolean = true
)

// ===========================================================================
// Client Configuration
// ===========================================================================

/**
 * Configuration for the [AinosClient].
 *
 * @property host Daemon hostname or IP address (default: "localhost")
 * @property port Daemon TCP port (default: 9500)
 * @property token Bearer token for authentication (null = no auth)
 * @property connectTimeoutMs TCP connection timeout in milliseconds (default: 10s)
 * @property readTimeoutMs Socket read timeout in milliseconds (default: 60s)
 * @property requestTimeoutMs Per-request timeout in milliseconds (default: 120s)
 * @property autoReconnect Whether to automatically reconnect on disconnect
 * @property maxReconnectAttempts Maximum reconnection attempts (0 = unlimited)
 * @property reconnectDelayMs Base delay between reconnection attempts in ms
 */
public data class ClientConfig(
    val host: String = "localhost",
    val port: Int = 9500,
    val token: String? = null,
    val connectTimeoutMs: Long = 10_000,
    val readTimeoutMs: Long = 60_000,
    val requestTimeoutMs: Long = 120_000,
    val autoReconnect: Boolean = false,
    val maxReconnectAttempts: Int = 3,
    val reconnectDelayMs: Long = 1_000
) {
    /**
     * Builder for constructing [ClientConfig] with a fluent API.
     *
     * Usage:
     * ```kotlin
     * val config = ClientConfig.Builder()
     *     .host("192.168.1.100")
     *     .port(9500)
     *     .token("my-secret-token")
     *     .build()
     * ```
     */
    public class Builder {
        private var host: String = "localhost"
        private var port: Int = 9500
        private var token: String? = null
        private var connectTimeoutMs: Long = 10_000
        private var readTimeoutMs: Long = 60_000
        private var requestTimeoutMs: Long = 120_000
        private var autoReconnect: Boolean = false
        private var maxReconnectAttempts: Int = 3
        private var reconnectDelayMs: Long = 1_000

        /**
         * Creates a builder with default values.
         */
        public constructor()

        /**
         * Creates a builder pre-populated from an existing [ClientConfig].
         * Useful for overriding specific properties.
         */
        internal constructor(config: ClientConfig) {
            this.host = config.host
            this.port = config.port
            this.token = config.token
            this.connectTimeoutMs = config.connectTimeoutMs
            this.readTimeoutMs = config.readTimeoutMs
            this.requestTimeoutMs = config.requestTimeoutMs
            this.autoReconnect = config.autoReconnect
            this.maxReconnectAttempts = config.maxReconnectAttempts
            this.reconnectDelayMs = config.reconnectDelayMs
        }

        /** Sets the daemon hostname. */
        public fun host(host: String): Builder = apply { this.host = host }

        /** Sets the daemon TCP port. */
        public fun port(port: Int): Builder = apply { this.port = port }

        /** Sets the bearer token for authentication. */
        public fun token(token: String): Builder = apply { this.token = token }

        /** Sets the connection timeout in milliseconds. */
        public fun connectTimeoutMs(timeout: Long): Builder = apply { this.connectTimeoutMs = timeout }

        /** Sets the socket read timeout in milliseconds. */
        public fun readTimeoutMs(timeout: Long): Builder = apply { this.readTimeoutMs = timeout }

        /** Sets the per-request timeout in milliseconds. */
        public fun requestTimeoutMs(timeout: Long): Builder = apply { this.requestTimeoutMs = timeout }

        /** Enables or disables auto-reconnection. */
        public fun autoReconnect(auto: Boolean): Builder = apply { this.autoReconnect = auto }

        /** Sets the maximum reconnection attempts. */
        public fun maxReconnectAttempts(max: Int): Builder = apply { this.maxReconnectAttempts = max }

        /** Sets the base delay between reconnection attempts in milliseconds. */
        public fun reconnectDelayMs(delay: Long): Builder = apply { this.reconnectDelayMs = delay }

        /** Builds the [ClientConfig] instance. */
        public fun build(): ClientConfig = ClientConfig(
            host = host,
            port = port,
            token = token,
            connectTimeoutMs = connectTimeoutMs,
            readTimeoutMs = readTimeoutMs,
            requestTimeoutMs = requestTimeoutMs,
            autoReconnect = autoReconnect,
            maxReconnectAttempts = maxReconnectAttempts,
            reconnectDelayMs = reconnectDelayMs
        )
    }

    /**
     * Companion object providing factory methods.
     */
    public companion object {
        /**
         * Creates a [ClientConfig] using the DSL builder pattern.
         *
         * Usage:
         * ```kotlin
         * val config = ClientConfig {
         *     host("192.168.1.100")
         *     port(9500)
         *     token("my-token")
         * }
         * ```
         */
        public operator fun invoke(block: Builder.() -> Unit): ClientConfig {
            return Builder().apply(block).build()
        }

        /**
         * Returns a new [Builder] instance.
         */
        public fun builder(): Builder = Builder()
    }
}