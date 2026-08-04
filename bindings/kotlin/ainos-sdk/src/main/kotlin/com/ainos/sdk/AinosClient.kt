package com.ainos.sdk

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.ReceiveChannel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.serialization.decodeFromJsonElement
import kotlinx.serialization.encodeToJsonElement
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Main client for the Ainos inference daemon.
 *
 * Provides a type-safe, coroutine-based API for interacting with the Ainos
 * daemon over TCP using the NDJSON protocol. Supports both synchronous
 * (suspend) and streaming (Flow-based) inference, model management,
 * health checks, and context storage.
 *
 * ## Basic Usage
 *
 * ```kotlin
 * val client = AinosClient(
 *     ClientConfig {
 *         host("localhost")
 *         port(9500)
 *         token("your-bearer-token")
 *     }
 * )
 *
 * client.connect()
 *
 * // Non-streaming inference
 * val result = client.infer("Hello! How are you?")
 * println(result.text)
 *
 * // Streaming inference
 * client.inferStream("Tell me a story").collect { chunk ->
 *     print(chunk.text)
 * }
 *
 * client.disconnect()
 * ```
 *
 * ## Error Handling
 *
 * ```kotlin
 * try {
 *     client.connect()
 *     val result = client.infer("Hello")
 * } catch (e: AinosException.ConnectionException) {
 *     println("Cannot connect to daemon: ${e.message}")
 * } catch (e: AinosException.ApiException) {
 *     println("API error [${e.code}]: ${e.message}")
 * } catch (e: AinosException.TimeoutException) {
 *     println("Request timed out")
 * }
 * ```
 *
 * @property config Client configuration
 * @property transport The underlying NDJSON TCP transport layer
 * @property auth The authentication manager
 */
public class AinosClient(
    public val config: ClientConfig = ClientConfig()
) : AutoCloseable {

    private val transport: Transport = Transport(
        host = config.host,
        port = config.port,
        config = TransportConfig(
            connectTimeoutMs = config.connectTimeoutMs.toInt(),
            readTimeoutMs = config.readTimeoutMs.toInt(),
            requestTimeoutMs = config.requestTimeoutMs
        )
    )

    private val auth: AuthenticationManager = AuthenticationManager(config.token)

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    @Volatile
    private var _connected: Boolean = false

    /**
     * Whether the client is currently connected to the Ainos daemon.
     */
    public val isConnected: Boolean
        get() = _connected && transport.isConnected

    /**
     * The authentication manager. Can be used to update the bearer token
     * at runtime without creating a new client instance.
     *
     * ```kotlin
     * client.authentication.setToken("new-token")
     * ```
     */
    public val authentication: AuthenticationManager
        get() = auth

    // =========================================================================
    // Connection Management
    // =========================================================================

    /**
     * Connects to the Ainos daemon.
     *
     * Establishes a TCP connection to the configured host and port, and starts
     * the background receive loop for processing responses. This method is a
     * suspend function and will block the calling coroutine until the connection
     * is established or fails.
     *
     * @throws AinosException.ConnectionException if the connection fails
     */
    public suspend fun connect() {
        transport.connect()
        _connected = true
    }

    /**
     * Disconnects from the Ainos daemon gracefully.
     *
     * Closes the TCP connection, cancels all pending requests, and releases
     * resources. After disconnecting, call [connect] again to resume operations.
     * This method is idempotent.
     */
    public suspend fun disconnect() {
        try {
            transport.disconnect()
        } finally {
            _connected = false
        }
    }

    /**
     * Ensures the client is connected, connecting if necessary.
     *
     * If the client is already connected, this method returns immediately.
     * If not, it establishes a new connection. This is useful for lazy
     * connection patterns.
     *
     * @throws AinosException.ConnectionException if the connection fails
     */
    public suspend fun ensureConnected() {
        if (!isConnected) {
            connect()
        }
    }

    // =========================================================================
    // Inference
    // =========================================================================

    /**
     * Performs a non-streaming (blocking) inference request.
     *
     * Sends the prompt to the daemon and waits for the complete response.
     * Use [inferStream] for real-time token-by-token generation.
     *
     * @param prompt The input text prompt
     * @param params Optional inference parameters (defaults are used if omitted)
     * @return The complete inference result
     * @throws AinosException.ConnectionException if not connected
     * @throws AinosException.TimeoutException if the request times out
     * @throws AinosException.ApiException if the daemon returns an error
     * @throws AinosException.ModelException if the model fails to generate
     */
    public suspend fun infer(
        prompt: String,
        params: InferParams = InferParams(prompt = prompt)
    ): InferResult {
        // Ensure the prompt in params matches the explicit prompt argument
        val effectiveParams = if (params.prompt == prompt) params
            else params.copy(prompt = prompt)

        val paramsObj = effectiveParams.toJsonObject()
        val response = transport.request("infer", paramsObj, auth.token)

        return try {
            json.decodeFromJsonElement(response)
        } catch (e: Exception) {
            throw AinosException.ProtocolException(
                "Failed to parse inference response: ${e.message}", e
            )
        }
    }

    /**
     * Performs a streaming inference request and returns a [Flow] of [StreamChunk].
     *
     * The flow emits chunks as they arrive from the daemon and completes
     * when the stream ends. The underlying TCP stream is cancelled if the
     * coroutine collecting the flow is cancelled.
     *
     * ## Usage
     * ```kotlin
     * client.inferStream("Write a haiku about AI")
     *     .collect { chunk ->
     *         print(chunk.text)
     *     }
     * ```
     *
     * @param prompt The input text prompt
     * @param params Optional inference parameters (stream is forced to true)
     * @return A flow that emits [StreamChunk] objects
     * @throws AinosException.ConnectionException if not connected
     */
    public fun inferStream(
        prompt: String,
        params: InferParams = InferParams(prompt = prompt)
    ): Flow<StreamChunk> {
        val effectiveParams = if (params.prompt == prompt) params
            else params.copy(prompt = prompt)

        val streamParams = effectiveParams.asStream()
        val paramsObj = streamParams.toJsonObject()
        val channel: ReceiveChannel<JsonElement> = transport.requestStream(
            "infer", paramsObj, auth.token
        )

        return Streaming.fromChannel(channel)
    }

    /**
     * Performs inference with a session ID for conversational continuity.
     *
     * Sessions allow multi-turn conversations where the model is aware of
     * previous exchanges. The [sessionId] is returned from [infer] and
     * [inferStream] responses.
     *
     * @param prompt The input prompt
     * @param sessionId Session ID from a previous interaction
     * @param params Additional inference parameters
     * @return The inference result
     */
    public suspend fun inferWithSession(
        prompt: String,
        sessionId: String,
        params: InferParams = InferParams(prompt = prompt)
    ): InferResult {
        val sessionParams = params.copy(prompt = prompt, sessionId = sessionId)
        return infer(prompt, sessionParams)
    }

    // =========================================================================
    // Model Management
    // =========================================================================

    /**
     * Lists all available models registered with the daemon.
     *
     * @return List of [ModelInfo] with metadata about each model
     * @throws AinosException if the request fails
     */
    public suspend fun modelList(): List<ModelInfo> {
        val response = transport.request("model_list", token = auth.token)
        return try {
            val result: ModelListResult = json.decodeFromJsonElement(response)
            result.models
        } catch (e: Exception) {
            throw AinosException.ProtocolException(
                "Failed to parse model list response: ${e.message}", e
            )
        }
    }

    /**
     * Loads a model into memory on the daemon.
     *
     * Loading a model makes it available for inference. The daemon may
     * unload other models to free memory if needed.
     *
     * @param params Parameters specifying which model to load and how
     * @return [ModelInfo] for the loaded model
     * @throws AinosException.ModelException if loading fails
     */
    public suspend fun modelLoad(params: ModelLoadParams): ModelInfo {
        val paramsObj = params.toJsonObject()
        val response = transport.request("model_load", paramsObj, auth.token)
        return try {
            json.decodeFromJsonElement(response)
        } catch (e: AinosException) {
            throw e
        } catch (e: Exception) {
            throw AinosException.ModelException(
                "Failed to load model '${params.name}': ${e.message}", e
            )
        }
    }

    /**
     * Loads a model by name with default parameters.
     *
     * Convenience method that creates a [ModelLoadParams] from the model name
     * and calls [modelLoad] with it.
     *
     * @param name Model name or identifier
     * @return [ModelInfo] for the loaded model
     */
    public suspend fun modelLoad(name: String): ModelInfo {
        return modelLoad(ModelLoadParams(name = name))
    }

    /**
     * Unloads a model from memory on the daemon.
     *
     * Frees the memory used by the model. The model remains registered
     * and can be loaded again later.
     *
     * @param name Name of the model to unload
     * @return [ModelUnloadResult] indicating success or failure
     * @throws AinosException.ModelException if unloading fails
     */
    public suspend fun modelUnload(name: String): ModelUnloadResult {
        val params = buildJsonObject {
            put("name", name)
        }
        val response = transport.request("model_unload", params, auth.token)
        return try {
            json.decodeFromJsonElement(response)
        } catch (e: AinosException) {
            throw e
        } catch (e: Exception) {
            throw AinosException.ModelException(
                "Failed to unload model '$name': ${e.message}", e
            )
        }
    }

    // =========================================================================
    // Health & Status
    // =========================================================================

    /**
     * Checks the health status of the Ainos daemon.
     *
     * @return [HealthInfo] with status, version, and uptime
     * @throws AinosException if the request fails
     */
    public suspend fun health(): HealthInfo {
        val response = transport.request("health", token = auth.token)
        return try {
            json.decodeFromJsonElement(response)
        } catch (e: Exception) {
            throw AinosException.ProtocolException(
                "Failed to parse health response: ${e.message}", e
            )
        }
    }

    /**
     * Gets detailed server status information.
     *
     * @return [ServerStatus] with detailed metrics
     * @throws AinosException if the request fails
     */
    public suspend fun status(): ServerStatus {
        val response = transport.request("status", token = auth.token)
        return try {
            json.decodeFromJsonElement(response)
        } catch (e: Exception) {
            throw AinosException.ProtocolException(
                "Failed to parse status response: ${e.message}", e
            )
        }
    }

    /**
     * Polls the daemon health endpoint until it returns "ok" or a timeout
     * is reached.
     *
     * This is useful for startup scripts that need to wait for the daemon
     * to be ready before sending requests.
     *
     * @param maxWaitMs Maximum time to wait in milliseconds (default: 30s)
     * @param pollIntervalMs Polling interval in milliseconds (default: 500ms)
     * @return `true` if the daemon is healthy, `false` if the timeout was reached
     */
    public suspend fun waitForHealthy(
        maxWaitMs: Long = 30_000,
        pollIntervalMs: Long = 500
    ): Boolean {
        val deadline = System.currentTimeMillis() + maxWaitMs
        var lastError: String? = null

        while (System.currentTimeMillis() < deadline) {
            try {
                val info = health()
                if (info.isHealthy) return true
                lastError = "status=${info.status}"
            } catch (e: AinosException) {
                lastError = e.message
            } catch (e: Exception) {
                lastError = e.message
            }
            delay(pollIntervalMs)
        }

        // Timeout reached
        return false
    }

    // =========================================================================
    // Context Management
    // =========================================================================

    /**
     * Stores context data on the daemon for long-term memory/persistence.
     *
     * Context data persists across sessions and can be retrieved by the
     * returned ID to provide the model with memory of past interactions.
     *
     * @param content The context content to store (e.g., conversation history)
     * @param metadata Optional metadata key-value pairs for filtering
     * @param model Optional model this context is associated with
     * @return The assigned context ID for later retrieval
     * @throws AinosException if the request fails
     */
    public suspend fun contextStore(
        content: String,
        metadata: Map<String, String>? = null,
        model: String? = null
    ): String {
        val params = buildJsonObject {
            put("content", content)
            if (metadata != null) {
                put("metadata", json.encodeToJsonElement(metadata))
            }
            if (model != null) put("model", model)
        }
        val response = transport.request("context_store", params, auth.token)
        return try {
            val result: ContextStoreResult = json.decodeFromJsonElement(response)
            result.id
        } catch (e: Exception) {
            throw AinosException.ProtocolException(
                "Failed to parse context store response: ${e.message}", e
            )
        }
    }

    /**
     * Stores a pre-constructed [ContextData] object.
     *
     * @param context The context data to store
     * @return The assigned context ID
     */
    public suspend fun contextStore(context: ContextData): String {
        val params = buildJsonObject {
            put("content", context.content)
            if (context.id.isNotBlank()) put("id", context.id)
            if (context.metadata != null) {
                put("metadata", json.encodeToJsonElement(context.metadata))
            }
            if (context.model != null) put("model", context.model)
            if (context.timestamp != null) put("timestamp", context.timestamp)
        }
        val response = transport.request("context_store", params, auth.token)
        return try {
            val result: ContextStoreResult = json.decodeFromJsonElement(response)
            result.id
        } catch (e: Exception) {
            throw AinosException.ProtocolException(
                "Failed to parse context store response: ${e.message}", e
            )
        }
    }

    /**
     * Retrieves previously stored context data by its ID.
     *
     * @param id The context ID returned by [contextStore]
     * @return The stored [ContextData] including content and metadata
     * @throws AinosException if the request fails or the ID is not found
     */
    public suspend fun contextRetrieve(id: String): ContextData {
        val params = buildJsonObject {
            put("id", id)
        }
        val response = transport.request("context_retrieve", params, auth.token)
        return try {
            json.decodeFromJsonElement(response)
        } catch (e: Exception) {
            throw AinosException.ProtocolException(
                "Failed to parse context retrieve response: ${e.message}", e
            )
        }
    }

    // =========================================================================
    // Low-Level API
    // =========================================================================

    /**
     * Sends a raw RPC request to the daemon with the given method and parameters.
     *
     * This method bypasses the typed API and gives direct access to the
     * underlying transport. Use this for custom methods or daemon extensions
     * that are not yet covered by the typed API.
     *
     * @param method The RPC method name
     * @param params Raw JSON parameters (optional)
     * @return Raw JSON response from the daemon
     */
    public suspend fun rawRequest(method: String, params: JsonObject? = null): JsonElement {
        return transport.request(method, params, auth.token)
    }

    /**
     * Sends a raw streaming RPC request and returns the raw channel.
     *
     * @param method The RPC method name
     * @param params Raw JSON parameters (optional)
     * @return A [ReceiveChannel] that emits raw JSON elements
     */
    public fun rawRequestStream(
        method: String,
        params: JsonObject? = null
    ): ReceiveChannel<JsonElement> {
        return transport.requestStream(method, params, auth.token)
    }

    // =========================================================================
    // Lifecycle
    // =========================================================================

    /**
     * Closes the client and releases all resources.
     *
     * This is a convenience method that implements [AutoCloseable], allowing
     * use in Kotlin's `use {}` blocks:
     *
     * ```kotlin
     * AinosClient(config).use { client ->
     *     client.connect()
     *     val result = client.infer("Hello")
     *     println(result.text)
     * }
     * ```
     */
    override fun close() {
        kotlinx.coroutines.runBlocking {
            disconnect()
            scope.cancel()
        }
    }

    /**
     * Returns a string representation of the client state.
     */
    override fun toString(): String {
        return "AinosClient(host=${config.host}:${config.port}, connected=$isConnected)"
    }

    // =========================================================================
    // Companion
    // =========================================================================

    public companion object {
        /**
         * Creates a new [AinosClient] configured with the given block and
         * automatically connects it to the daemon.
         *
         * ## Usage
         * ```kotlin
         * val client = AinosClient.create {
         *     host("192.168.1.100")
         *     port(9500)
         *     token("my-token")
         * }
         * ```
         *
         * @param config Optional base configuration
         * @param block Configuration DSL block
         * @return A connected [AinosClient]
         * @throws AinosException.ConnectionException if the connection fails
         */
        public suspend fun create(
            config: ClientConfig = ClientConfig(),
            block: (ClientConfig.Builder.() -> Unit)? = null
        ): AinosClient {
            val resolvedConfig = if (block != null) {
                ClientConfig.Builder(config).apply(block).build()
            } else {
                config
            }
            val client = AinosClient(resolvedConfig)
            client.connect()
            return client
        }
    }
}