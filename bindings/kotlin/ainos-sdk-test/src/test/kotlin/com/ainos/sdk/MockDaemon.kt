package com.ainos.sdk

import kotlinx.serialization.encodeToJsonElement
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.io.BufferedReader
import java.io.BufferedWriter
import java.io.Closeable
import java.io.IOException
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * A mock TCP server that simulates the Ainos daemon for testing purposes.
 *
 * Listens on a local port, accepts connections, and responds to NDJSON
 * requests based on registered [RequestHandler] instances. Supports both
 * single-response and streaming-response scenarios.
 *
 * ## Usage
 * ```kotlin
 * val mock = MockDaemon()
 * mock.start()
 *
 * // Register a handler for the "health" method
 * mock.on("health") { params, requestId ->
 *     listOf(MockDaemon.MockResponse(
 *         type = "result",
 *         data = json.parseToJsonElement("""{"status":"ok","version":"1.0.0"}""")
 *     ))
 * }
 *
 * // Register a streaming handler
 * mock.on("infer") { params, requestId ->
 *     listOf(
 *         MockDaemon.MockResponse(type = "stream", data = json.parseToJsonElement("""{"text":"Hello","index":0}""")),
 *         MockDaemon.MockResponse(type = "stream", data = json.parseToJsonElement("""{"text":" world","index":1,"finished":true,"finish_reason":"stop"}""")),
 *         MockDaemon.MockResponse(type = "stream_end")
 *     )
 * }
 *
 * // Use with client
 * val client = AinosClient(ClientConfig(port = mock.actualPort))
 * client.connect()
 * val health = client.health()
 * assertEquals("ok", health.status)
 *
 * mock.stop()
 * ```
 *
 * @property port Port to listen on (0 = any available port)
 */
public class MockDaemon(
    public val port: Int = 0
) : Closeable {

    private val serverSocket: ServerSocket = ServerSocket(port)
    private val running = AtomicBoolean(true)
    private val requestHandlers = ConcurrentHashMap<String, RequestHandler>()
    private var serverThread: Thread? = null
    private val connections = CopyOnWriteArrayList<MockConnection>()
    private val receivedRequests = CopyOnWriteArrayList<JsonObject>()

    /**
     * The actual port the server is listening on.
     * Useful when [port] was 0 (auto-assign).
     */
    public val actualPort: Int
        get() = serverSocket.localPort

    /**
     * Returns an immutable copy of all requests received by this mock daemon.
     * Useful for verifying that the client sent the correct requests.
     */
    public val requests: List<JsonObject>
        get() = receivedRequests.toList()

    /**
     * Handler for a specific RPC method.
     * Receives the request parameters and request ID, and returns a list
     * of [MockResponse] objects to send back.
     */
    public fun interface RequestHandler {
        /**
         * Handles a request and returns responses.
         *
         * @param params The JSON parameters from the request (may be null)
         * @param requestId The request ID for response matching
         * @return List of responses to send (multiple for streaming)
         */
        fun handle(params: JsonObject?, requestId: String): List<MockResponse>
    }

    /**
     * A mock response to be sent back to the client.
     *
         * @property type Response type: "result", "error", "stream", or "stream_end"
     * @property data Optional response data
     * @property error Optional error detail
     */
    public data class MockResponse(
        val type: String,
        val data: JsonElement? = null,
        val error: ErrorDetail? = null
    )

    /**
     * Starts the mock daemon server thread.
     * The server begins accepting connections immediately.
     */
    public fun start() {
        serverThread = thread(name = "mock-daemon-${actualPort}") {
            try {
                while (running.get()) {
                    try {
                        val socket = serverSocket.accept()
                        val conn = MockConnection(socket)
                        connections.add(conn)
                        conn.start()
                    } catch (e: SocketException) {
                        // Server socket closed, exit loop
                        break
                    } catch (e: IOException) {
                        if (running.get()) {
                            e.printStackTrace()
                        }
                        break
                    }
                }
            } catch (e: Exception) {
                if (running.get()) {
                    e.printStackTrace()
                }
            }
        }
    }

    /**
     * Registers a handler for a specific RPC method.
     *
     * @param method The method name to handle
     * @param handler The handler function
     */
    public fun on(method: String, handler: RequestHandler) {
        requestHandlers[method] = handler
    }

    /**
     * Registers a handler for a method that returns a single response.
     *
     * @param method The method name to handle
     * @param response The single response to send
     */
    public fun on(method: String, response: MockResponse) {
        requestHandlers[method] = RequestHandler { _, _ -> listOf(response) }
    }

    /**
     * Registers a handler for a method that returns a single result with data.
     *
     * @param method The method name to handle
     * @param responseData The response data as a JSON element
     */
    public fun onResult(method: String, responseData: JsonElement) {
        on(method, MockResponse(type = "result", data = responseData))
    }

    /**
     * Clears all registered handlers.
     */
    public fun clearHandlers() {
        requestHandlers.clear()
    }

    /**
     * Stops the mock daemon, closes all connections, and releases the port.
     */
    public fun stop() {
        running.set(false)

        // Close all connections
        connections.forEach { it.stop() }
        connections.clear()

        // Close server socket
        try {
            serverSocket.close()
        } catch (_: Exception) { /* ignore */ }

        serverThread?.join(1000)
        serverThread = null
    }

    /**
     * Resets the mock daemon: clears handlers and received requests.
     */
    public fun reset() {
        requestHandlers.clear()
        receivedRequests.clear()
    }

    override fun close() {
        stop()
    }

    /**
     * Represents a single client connection handled by a dedicated thread.
     */
    private inner class MockConnection(
        private val socket: Socket
    ) {
        private var running = true
        private var thread: Thread? = null

        fun start() {
            thread = thread(name = "mock-conn-${socket.port}") {
                try {
                    val reader: BufferedReader = socket.getInputStream().bufferedReader()
                    val writer: BufferedWriter = socket.getOutputStream().bufferedWriter()

                    while (running) {
                        val line: String = try {
                            reader.readLine() ?: break
                        } catch (e: IOException) {
                            break
                        }

                        if (line.isBlank()) continue

                        try {
                            val request = json.parseToJsonElement(line).jsonObject
                            receivedRequests.add(request)

                            val method = request["method"]?.jsonPrimitive?.contentOrNull
                                ?: continue

                            val requestId = request["id"]?.jsonPrimitive?.contentOrNull
                                ?: "unknown"

                            val params = request["params"]?.jsonObject
                            val token = request["token"]?.jsonPrimitive?.contentOrNull

                            // Verify token if configured
                            if (token != null && expectedToken != null && token != expectedToken) {
                                sendError(writer, requestId, 7, "Authentication failed: invalid token")
                                continue
                            }

                            val handler = requestHandlers[method]
                            if (handler != null) {
                                val responses = handler.handle(params, requestId)
                                for (response in responses) {
                                    sendResponse(writer, requestId, response)
                                    if (response.type == "stream_end" || response.type == "error") {
                                        break
                                    }
                                }
                            } else {
                                sendError(
                                    writer, requestId, -1,
                                    "Unknown method: $method"
                                )
                            }
                        } catch (e: Exception) {
                            // Skip malformed requests
                            e.printStackTrace()
                        }
                    }
                } catch (e: IOException) {
                    // Connection closed
                } finally {
                    try {
                        socket.close()
                    } catch (_: Exception) { /* ignore */ }
                }
            }
        }

        fun stop() {
            running = false
            thread?.interrupt()
            try {
                socket.close()
            } catch (_: Exception) { /* ignore */ }
        }

        private fun sendResponse(writer: BufferedWriter, requestId: String, response: MockResponse) {
            val envelope = buildJsonObject {
                put("id", requestId)
                put("type", response.type)
                if (response.data != null) {
                    put("data", response.data)
                }
                if (response.error != null) {
                    put("error", buildJsonObject {
                        put("code", response.error.code)
                        put("message", response.error.message)
                    })
                }
            }
            val responseLine = json.encodeToJsonElement(envelope).toString()
            synchronized(writer) {
                writer.write(responseLine)
                writer.newLine()
                writer.flush()
            }
        }

        private fun sendError(writer: BufferedWriter, requestId: String, code: Int, message: String) {
            val envelope = buildJsonObject {
                put("id", requestId)
                put("type", "error")
                put("error", buildJsonObject {
                    put("code", code)
                    put("message", message)
                })
            }
            val responseLine = json.encodeToJsonElement(envelope).toString()
            synchronized(writer) {
                writer.write(responseLine)
                writer.newLine()
                writer.flush()
            }
        }
    }

    /**
     * Optional expected token for authentication testing.
     * If set, requests with a different token will be rejected.
     */
    public var expectedToken: String? = null

    /**
     * Returns a [ClientConfig] pre-configured to connect to this mock daemon.
     */
    public fun clientConfig(
        token: String? = null,
        block: (ClientConfig.Builder.() -> Unit)? = null
    ): ClientConfig {
        val builder = ClientConfig.Builder()
            .host("localhost")
            .port(actualPort)

        if (token != null) {
            builder.token(token)
            expectedToken = token
        }

        if (block != null) {
            builder.apply(block)
        }

        return builder.build()
    }
}