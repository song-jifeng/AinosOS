package com.ainos.sdk

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.channels.ReceiveChannel
import kotlinx.coroutines.channels.SendChannel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.encodeToJsonElement
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.coroutines.future.await
import kotlinx.serialization.json.put
import java.io.BufferedReader
import java.io.BufferedWriter
import java.io.IOException
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.CancellationException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicReference
import kotlin.concurrent.thread

/**
 * Low-level TCP transport layer for communicating with the Ainos daemon.
 *
 * Implements the NDJSON (Newline-Delimited JSON) protocol over TCP.
 * Each line on the wire is a complete JSON object. The transport manages
 * the socket lifecycle, encodes/decodes messages, and routes responses
 * to the correct pending request by matching response IDs.
 *
 * ## Protocol
 * - **Request**: `{"id":"req-1","method":"infer","params":{...},"token":"..."}`
 * - **Response**: `{"id":"req-1","type":"result","data":{...}}`
 * - **Stream**: `{"id":"req-1","type":"stream","data":{...}}` followed by
 *   `{"id":"req-1","type":"stream_end","data":{...}}`
 * - **Error**: `{"id":"req-1","type":"error","error":{"code":1,"message":"..."}}`
 *
 * ## Thread Safety
 * This class is thread-safe. Sending and receiving happen on different
 * threads: the caller's coroutine sends, and a dedicated receive loop
 * thread processes incoming data.
 *
 * @param host Daemon hostname or IP address
 * @param port Daemon TCP port
 * @param config Transport configuration
 */
public class Transport(
    public val host: String = "localhost",
    public val port: Int = 9500,
    private val config: TransportConfig = TransportConfig()
) {
    private val socketRef = AtomicReference<Socket?>(null)
    private val writerRef = AtomicReference<BufferedWriter?>(null)
    private val readerRef = AtomicReference<BufferedReader?>(null)

    // Maps request ID -> deferred result for request/response matching
    private val pendingRequests = ConcurrentHashMap<String, CompletableDeferred<JsonElement>>()

    // Maps request ID -> send channel for streaming responses
    private val pendingStreams = ConcurrentHashMap<String, SendChannel<JsonElement>>()

    // Coroutine scope for the receive loop and stream dispatch
    private var scopeRef = AtomicReference<CoroutineScope?>(null)
    private var receiveJobRef = AtomicReference<Job?>(null)

    @Volatile
    private var receiveThread: Thread? = null

    @Volatile
    public var isConnected: Boolean = false
        private set

    @Volatile
    public var lastError: Throwable? = null
        private set

    /**
     * Connects to the Ainos daemon.
     *
     * Creates a TCP socket to [host]:[port], sets up the input/output streams,
     * and starts the background receive loop. This method is a suspend function
     * and blocks the calling coroutine, not the thread.
     *
     * @throws AinosException.ConnectionException if the connection cannot be established
     */
    public suspend fun connect(): Unit = withContext(Dispatchers.IO) {
        if (isConnected) return@withContext

        try {
            val sock = Socket()
            sock.connect(InetSocketAddress(host, port), config.connectTimeoutMs)
            sock.soTimeout = config.readTimeoutMs
            sock.tcpNoDelay = true
            sock.keepAlive = true

            val sockWriter = sock.getOutputStream().bufferedWriter()
            val sockReader = sock.getInputStream().bufferedReader()

            socketRef.set(sock)
            writerRef.set(sockWriter)
            readerRef.set(sockReader)

            // Create coroutine scope for the receive loop
            val sockScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
            scopeRef.set(sockScope)

            // Start the receive loop on a dedicated thread for immediate read responsiveness
            val rcvThread = thread(name = "ainos-transport-recv-$host:$port") {
                try {
                    receiveLoop(sockReader)
                } catch (e: InterruptedException) {
                    Thread.currentThread().interrupt()
                } catch (e: CancellationException) {
                    // Normal cancellation
                } catch (e: Exception) {
                    if (isConnected) {
                        lastError = e
                        // Fail all pending requests
                        failAllPending(AinosException.ConnectionException(
                            "Connection error: ${e.message}", e
                        ))
                    }
                }
            }
            receiveThread = rcvThread

            isConnected = true
            lastError = null
        } catch (e: IOException) {
            isConnected = false
            cleanup()
            throw AinosException.ConnectionException(
                "Cannot connect to Ainos daemon at $host:$port: ${e.message}", e
            )
        }
    }

    /**
     * Disconnects from the Ainos daemon gracefully.
     *
     * Stops the receive loop, fails all pending requests with
     * [AinosException.ConnectionException], and closes the TCP socket.
     * This method is idempotent: calling it multiple times has no additional effect.
     */
    public suspend fun disconnect() {
        isConnected = false

        // Stop receive thread
        receiveThread?.interrupt()
        receiveThread = null

        // Cancel coroutine scope
        scopeRef.getAndSet(null)?.cancel()

        // Fail all pending requests
        val connEx = AinosException.ConnectionException("Client disconnected")
        failAllPending(connEx)

        // Close socket and streams
        cleanup()
    }

    /**
     * Sends an RPC request and waits for a single response.
     *
     * The request is sent as a JSON line, and the method suspends until
     * a matching response (by ID) is received or the timeout expires.
     *
     * @param method The RPC method name (e.g., "infer", "health", "model_list")
     * @param params Optional JSON object parameters
     * @param token Optional bearer token for authentication
     * @return The response data as a [JsonElement]
     * @throws AinosException.InvalidStateException if not connected
     * @throws AinosException.TimeoutException if the request times out
     * @throws AinosException.ApiException if the daemon returns an error
     * @throws AinosException.ConnectionException if the connection is lost
     */
    public suspend fun request(
        method: String,
        params: JsonObject? = null,
        token: String? = null
    ): JsonElement {
        ensureConnected()

        val id = generateRequestId()
        val envelope = buildJsonObject {
            put("id", id)
            put("method", method)
            if (params != null) put("params", params)
            if (token != null) put("token", token)
        }

        val deferred = CompletableDeferred<JsonElement>()
        pendingRequests[id] = deferred

        try {
            sendLine(envelope)

            val response = withTimeout(config.requestTimeoutMs.toLong()) {
                deferred.await()
            }

            return response
        } catch (e: TimeoutCancellationException) {
            pendingRequests.remove(id)
            throw AinosException.TimeoutException(
                "Request '$method' (id=$id) timed out after ${config.requestTimeoutMs}ms"
            )
        } catch (e: CancellationException) {
            pendingRequests.remove(id)
            throw e
        } finally {
            // Ensure cleanup if not already removed
            pendingRequests.remove(id)
        }
    }

    /**
     * Sends an RPC request and returns a [ReceiveChannel] for streaming responses.
     *
     * The channel emits JSON elements for each "stream" chunk and closes
     * automatically when "stream_end" is received. If the daemon returns
     * an error, the channel closes with the error.
     *
     * @param method The RPC method name
     * @param params Optional JSON object parameters
     * @param token Optional bearer token
     * @return A [ReceiveChannel] that emits stream chunks as [JsonElement]
     * @throws AinosException.InvalidStateException if not connected
     */
    public fun requestStream(
        method: String,
        params: JsonObject? = null,
        token: String? = null
    ): ReceiveChannel<JsonElement> {
        ensureConnected()

        val currentScope = scopeRef.get()
            ?: throw AinosException.InvalidStateException("Transport scope not initialized")

        val id = generateRequestId()
        val channel = Channel<JsonElement>(Channel.BUFFERED)
        pendingStreams[id] = channel

        val envelope = buildJsonObject {
            put("id", id)
            put("method", method)
            if (params != null) put("params", params)
            if (token != null) put("token", token)
        }

        currentScope.launch {
            try {
                sendLine(envelope)
            } catch (e: Exception) {
                channel.close(e)
                pendingStreams.remove(id)
            }
        }

        return channel
    }

    /**
     * Sends a JSON object as a single NDJSON line to the daemon.
     */
    private suspend fun sendLine(element: JsonObject): Unit = withContext(Dispatchers.IO) {
        val writer = writerRef.get()
            ?: throw AinosException.InvalidStateException("Not connected, no writer available")

        try {
            val line = json.encodeToJsonElement(element).toString()
            synchronized(writer) {
                writer.write(line)
                writer.newLine()
                writer.flush()
            }
        } catch (e: IOException) {
            isConnected = false
            throw AinosException.ConnectionException(
                "Failed to send data to $host:$port: ${e.message}", e
            )
        }
    }

    /**
     * Continuous loop that reads lines from the socket and routes them
     * to the appropriate pending request or stream.
     *
     * Runs on a dedicated thread. This is a blocking loop that only exits
     * when the socket is closed or an I/O error occurs.
     */
    private fun receiveLoop(reader: BufferedReader) {
        try {
            while (!Thread.currentThread().isInterrupted) {
                val line = reader.readLine() ?: break // EOF: remote closed connection
                if (line.isBlank()) continue

                try {
                    val element = json.parseToJsonElement(line)
                    val obj = element.jsonObject

                    val id = obj["id"]?.jsonPrimitive?.contentOrNull
                        ?: run {
                            // Malformed: missing ID, skip
                            continue
                        }

                    val type = obj["type"]?.jsonPrimitive?.contentOrNull ?: "result"

                    when (type) {
                        "result" -> {
                            // Complete a pending request with the data field
                            val deferred = pendingRequests.remove(id)
                            deferred?.complete(obj["data"] ?: JsonNull)
                        }

                        "error" -> {
                            val errorObj = obj["error"]?.jsonObject
                            val errorCode = errorObj?.get("code")?.jsonPrimitive?.intOrNull ?: -1
                            val errorMsg = errorObj?.get("message")?.jsonPrimitive?.contentOrNull
                                ?: "Unknown daemon error"

                            val apiEx = AinosException.ApiException(errorCode, errorMsg)

                            // Route to pending request
                            val deferred = pendingRequests.remove(id)
                            if (deferred != null) {
                                deferred.completeExceptionally(apiEx)
                            }

                            // Route to pending stream
                            val streamChannel = pendingStreams.remove(id)
                            if (streamChannel != null) {
                                streamChannel.close(apiEx)
                            }
                        }

                        "stream" -> {
                            // Send data to the stream channel
                            val channel = pendingStreams[id]
                            if (channel != null) {
                                val data = obj["data"] ?: JsonNull
                                channel.trySend(data)
                            } else {
                                // Stream channel not found, might have been cancelled
                                // This is benign — the client may have cancelled the flow
                            }
                        }

                        "stream_end" -> {
                            // Close the stream channel
                            val channel = pendingStreams.remove(id)
                            if (channel != null) {
                                channel.close()
                            }
                        }

                        else -> {
                            // Unknown response type, treat as result for backward compatibility
                            val deferred = pendingRequests.remove(id)
                            deferred?.complete(obj["data"] ?: obj)
                        }
                    }
                } catch (e: AinosException) {
                    // Propagate SDK exceptions
                    throw e
                } catch (e: Exception) {
                    // Skip malformed JSON lines gracefully
                    lastError = e
                }
            }
        } catch (e: IOException) {
            // Socket closed or read error
            if (isConnected) {
                isConnected = false
                lastError = e
                val connEx = AinosException.ConnectionException(
                    "Connection to $host:$port lost: ${e.message}", e
                )
                failAllPending(connEx)
            }
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
        } finally {
            isConnected = false
        }
    }

    /**
     * Fails all pending requests and streams with the given exception.
     */
    private fun failAllPending(exception: AinosException) {
        pendingRequests.forEach { (_, deferred) ->
            deferred.completeExceptionally(exception)
        }
        pendingRequests.clear()

        pendingStreams.forEach { (_, channel) ->
            channel.close(exception)
        }
        pendingStreams.clear()
    }

    /**
     * Cleans up socket and stream resources.
     */
    private fun cleanup() {
        try {
            writerRef.getAndSet(null)?.close()
        } catch (_: Exception) { /* ignore */ }
        try {
            readerRef.getAndSet(null)?.close()
        } catch (_: Exception) { /* ignore */ }
        try {
            socketRef.getAndSet(null)?.close()
        } catch (_: Exception) { /* ignore */ }
    }

    /**
     * Throws [AinosException.InvalidStateException] if not connected.
     */
    private fun ensureConnected() {
        if (!isConnected) {
            throw AinosException.InvalidStateException(
                "Not connected to Ainos daemon at $host:$port. Call connect() first."
            )
        }
    }
}

/**
 * Configuration for the [Transport] layer.
 *
 * @property connectTimeoutMs TCP socket connection timeout in milliseconds
 * @property readTimeoutMs Socket read timeout in milliseconds (SO_TIMEOUT)
 * @property requestTimeoutMs Maximum time to wait for a response in milliseconds
 */
public data class TransportConfig(
    /** TCP connection timeout in milliseconds. Default: 10 seconds. */
    val connectTimeoutMs: Int = 10_000,

    /** Socket read timeout in milliseconds. Default: 60 seconds. */
    val readTimeoutMs: Int = 60_000,

    /** Per-request timeout in milliseconds. Default: 120 seconds. */
    val requestTimeoutMs: Long = 120_000
) {
    init {
        require(connectTimeoutMs > 0) { "connectTimeoutMs must be positive" }
        require(readTimeoutMs > 0) { "readTimeoutMs must be positive" }
        require(requestTimeoutMs > 0) { "requestTimeoutMs must be positive" }
    }
}

/**
 * A simple [CompletableDeferred] implementation using a [CompletableFuture].
 * Provides a suspend-friendly await that completes when the future completes.
 */
private class CompletableDeferred<T> {
    private val future = java.util.concurrent.CompletableFuture<T>()

    /**
     * Completes this deferred with the given value.
     * @return true if this was completed by this call, false otherwise
     */
    fun complete(value: T): Boolean = future.complete(value)

    /**
     * Completes this deferred exceptionally with the given cause.
     * @return true if this was completed by this call, false otherwise
     */
    fun completeExceptionally(exception: Throwable): Boolean =
        future.completeExceptionally(exception)

    /**
     * Awaits the completion of this deferred as a suspend function.
     */
    suspend fun await(): T = future.await()

    /**
     * Returns true if this deferred is already completed (normally or exceptionally).
     */
    fun isCompleted(): Boolean = future.isDone

    /**
     * Returns true if this deferred completed exceptionally.
     */
    fun isCompletedExceptionally(): Boolean = future.isCompletedExceptionally()
}
}