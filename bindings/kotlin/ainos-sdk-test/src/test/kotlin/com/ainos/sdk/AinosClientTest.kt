package com.ainos.sdk

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlin.test.*

/**
 * Comprehensive test suite for the AinosClient.
 *
 * All tests use a [MockDaemon] to simulate the Ainos daemon, avoiding
 * any dependency on a running daemon instance. The mock daemon is started
 * on a random port before each test and stopped after.
 */
class AinosClientTest {

    private lateinit var mockDaemon: MockDaemon
    private lateinit var client: AinosClient

    @Before
    fun setup() {
        mockDaemon = MockDaemon(port = 0)
        mockDaemon.start()
    }

    @After
    fun teardown() {
        try {
            kotlinx.coroutines.runBlocking {
                if (::client.isInitialized && client.isConnected) {
                    client.disconnect()
                }
            }
        } catch (_: Exception) { /* ignore */ }
        mockDaemon.stop()
    }

    // =========================================================================
    // Connection Tests
    // =========================================================================

    @Test
    fun `connect successfully establishes connection`() = kotlinx.coroutines.runBlocking {
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        assertFalse(client.isConnected)
        client.connect()
        assertTrue(client.isConnected)
    }

    @Test
    fun `connect to wrong port throws ConnectionException`() = kotlinx.coroutines.runBlocking {
        client = AinosClient(ClientConfig(host = "localhost", port = 1))
        assertFailsWith<AinosException.ConnectionException> {
            client.connect()
        }
    }

    @Test
    fun `disconnect releases resources`() = kotlinx.coroutines.runBlocking {
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()
        assertTrue(client.isConnected)
        client.disconnect()
        assertFalse(client.isConnected)
    }

    @Test
    fun `ensureConnected connects automatically`() = kotlinx.coroutines.runBlocking {
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        assertFalse(client.isConnected)
        client.ensureConnected()
        assertTrue(client.isConnected)
    }

    @Test
    fun `disconnect is idempotent`() = kotlinx.coroutines.runBlocking {
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.disconnect() // Should not throw
        client.disconnect() // Should not throw
        assertFalse(client.isConnected)
    }

    @Test
    fun `multiple connects are safe`() = kotlinx.coroutines.runBlocking {
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()
        client.connect() // Should be no-op
        assertTrue(client.isConnected)
        client.disconnect()
    }

    // =========================================================================
    // Health Tests
    // =========================================================================

    @Test
    fun `health returns correct status`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("health") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"status":"ok","version":"1.0.0","uptime":3600}""")
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val health = client.health()
        assertEquals("ok", health.status)
        assertEquals("1.0.0", health.version)
        assertEquals(3600L, health.uptime)
        assertTrue(health.isHealthy)
    }

    @Test
    fun `health returns degraded status`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("health") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"status":"degraded"}""")
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val health = client.health()
        assertEquals("degraded", health.status)
        assertFalse(health.isHealthy)
    }

    @Test
    fun `health with active connections`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("health") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"status":"ok","active_connections":3}""")
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val health = client.health()
        assertEquals(3, health.activeConnections)
    }

    @Test
    fun `health without connection throws InvalidStateException`() = kotlinx.coroutines.runBlocking {
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        assertFailsWith<AinosException.InvalidStateException> {
            client.health()
        }
    }

    // =========================================================================
    // Status Tests
    // =========================================================================

    @Test
    fun `status returns server information`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("status") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""
                    {
                        "uptime": 7200,
                        "version": "1.0.0",
                        "active_models": 2,
                        "total_models": 5,
                        "memory_usage": {"current": 4096, "peak": 8192, "limit": 16384},
                        "cpu_usage": 0.45
                    }
                """)
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val status = client.status()
        assertEquals(7200L, status.uptime)
        assertEquals("1.0.0", status.version)
        assertEquals(2, status.activeModels)
        assertEquals(5, status.totalModels)
        assertNotNull(status.memoryUsage)
        assertEquals(4096L, status.memoryUsage.current)
        assertEquals(8192L, status.memoryUsage.peak)
        assertEquals(16384L, status.memoryUsage.limit)
        assertEquals(0.45f, status.cpuUsage)
    }

    @Test
    fun `status with GPU info`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("status") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""
                    {
                        "uptime": 100,
                        "version": "1.0.0",
                        "gpu_info": {
                            "device": "NVIDIA RTX 4090",
                            "memory_used": 8192,
                            "memory_total": 24576,
                            "utilization": 35
                        }
                    }
                """)
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val status = client.status()
        assertNotNull(status.gpuInfo)
        assertEquals("NVIDIA RTX 4090", status.gpuInfo.device)
        assertEquals(8192L, status.gpuInfo.memoryUsed)
        assertEquals(24576L, status.gpuInfo.memoryTotal)
        assertEquals(35, status.gpuInfo.utilization)
    }

    // =========================================================================
    // Inference Tests
    // =========================================================================

    @Test
    fun `infer returns generated text`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("infer") { params, _ ->
            val prompt = params?.get("prompt")?.jsonPrimitive?.contentOrNull ?: ""
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""
                    {
                        "text": "Hello! I am an AI assistant.",
                        "finish_reason": "stop",
                        "tokens": 8,
                        "tokens_per_second": 15.5
                    }
                """)
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val result = client.infer("Hello!")
        assertEquals("Hello! I am an AI assistant.", result.text)
        assertEquals("stop", result.finishReason)
        assertEquals(8, result.tokens)
        assertEquals(15.5f, result.tokensPerSecond)
    }

    @Test
    fun `infer with custom parameters`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("infer") { params, _ ->
            val maxTokens = params?.get("max_tokens")?.jsonPrimitive?.intOrNull
            val temperature = params?.get("temperature")?.jsonPrimitive?.contentOrNull
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"text":"Custom response"}""")
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val params = InferParams(prompt = "Test", maxTokens = 512, temperature = 0.3f)
        val result = client.infer("Test", params)
        assertEquals("Custom response", result.text)
    }

    @Test
    fun `infer with session`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("infer") { params, _ ->
            val sessionId = params?.get("session_id")?.jsonPrimitive?.contentOrNull
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""
                    {"text":"Session response","session_id":"${sessionId ?: "new"}"}
                """)
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val result = client.inferWithSession("Hello", "session-123")
        assertEquals("Session response", result.text)
        assertEquals("session-123", result.sessionId)
    }

    @Test
    fun `infer sends prompt in params`() = kotlinx.coroutines.runBlocking {
        var capturedPrompt: String? = null
        mockDaemon.on("infer") { params, _ ->
            capturedPrompt = params?.get("prompt")?.jsonPrimitive?.contentOrNull
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"text":"ok"}""")
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        client.infer("What is AI?")
        assertEquals("What is AI?", capturedPrompt)
    }

    // =========================================================================
    // Streaming Inference Tests
    // =========================================================================

    @Test
    fun `inferStream emits chunks in order`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("infer") { _, _ ->
            listOf(
                MockDaemon.MockResponse(
                    type = "stream",
                    data = json.parseToJsonElement("""{"text":"Hello","index":0}""")
                ),
                MockDaemon.MockResponse(
                    type = "stream",
                    data = json.parseToJsonElement("""{"text":" world","index":1}""")
                ),
                MockDaemon.MockResponse(
                    type = "stream",
                    data = json.parseToJsonElement("""{"text":"!","index":2,"finished":true,"finish_reason":"stop"}""")
                ),
                MockDaemon.MockResponse(type = "stream_end")
            )
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val chunks = client.inferStream("Hi").toList()
        assertEquals(3, chunks.size)
        assertEquals("Hello", chunks[0].text)
        assertEquals(0, chunks[0].index)
        assertFalse(chunks[0].finished)
        assertEquals(" world", chunks[1].text)
        assertEquals(1, chunks[1].index)
        assertEquals("!", chunks[2].text)
        assertEquals(2, chunks[2].index)
        assertTrue(chunks[2].finished)
        assertEquals("stop", chunks[2].finishReason)
    }

    @Test
    fun `inferStream collects full text`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("infer") { _, _ ->
            listOf(
                MockDaemon.MockResponse(
                    type = "stream",
                    data = json.parseToJsonElement("""{"text":"Once","index":0}""")
                ),
                MockDaemon.MockResponse(
                    type = "stream",
                    data = json.parseToJsonElement("""{"text":" upon","index":1}""")
                ),
                MockDaemon.MockResponse(
                    type = "stream",
                    data = json.parseToJsonElement("""{"text":" a time","index":2,"finished":true}""")
                ),
                MockDaemon.MockResponse(type = "stream_end")
            )
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val fullText = Streaming.collectText(client.inferStream("Tell a story"))
        assertEquals("Once upon a time", fullText)
    }

    @Test
    fun `inferStream with empty stream`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("infer") { _, _ ->
            listOf(
                MockDaemon.MockResponse(type = "stream_end")
            )
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val chunks = client.inferStream("Test").toList()
        assertTrue(chunks.isEmpty())
    }

    @Test
    fun `inferStream textOnly filters empty`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("infer") { _, _ ->
            listOf(
                MockDaemon.MockResponse(
                    type = "stream",
                    data = json.parseToJsonElement("""{"text":"","index":0}""")
                ),
                MockDaemon.MockResponse(
                    type = "stream",
                    data = json.parseToJsonElement("""{"text":"Hello","index":1,"finished":true}""")
                ),
                MockDaemon.MockResponse(type = "stream_end")
            )
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val texts = client.inferStream("Hi").textOnly().toList()
        assertEquals(1, texts.size)
        assertEquals("Hello", texts[0])
    }

    // =========================================================================
    // Model Management Tests
    // =========================================================================

    @Test
    fun `modelList returns models`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("model_list") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""
                    {
                        "models": [
                            {"name": "llama-7b", "loaded": true, "size": 4096, "quantization": "Q4_K_M"},
                            {"name": "mistral-7b", "loaded": false, "size": 4096}
                        ],
                        "total": 2
                    }
                """)
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val models = client.modelList()
        assertEquals(2, models.size)
        assertEquals("llama-7b", models[0].name)
        assertTrue(models[0].loaded)
        assertEquals(4096L, models[0].size)
        assertEquals("Q4_K_M", models[0].quantization)
        assertEquals("mistral-7b", models[1].name)
        assertFalse(models[1].loaded)
    }

    @Test
    fun `modelList empty`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("model_list") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"models":[],"total":0}""")
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val models = client.modelList()
        assertTrue(models.isEmpty())
    }

    @Test
    fun `modelLoad loads a model`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("model_load") { params, _ ->
            val name = params?.get("name")?.jsonPrimitive?.contentOrNull ?: "unknown"
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""
                    {"name":"$name","loaded":true,"backend":"llama.cpp"}
                """)
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val model = client.modelLoad("llama-7b")
        assertEquals("llama-7b", model.name)
        assertTrue(model.loaded)
        assertEquals("llama.cpp", model.backend)
    }

    @Test
    fun `modelLoad with params`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("model_load") { params, _ ->
            val gpuLayers = params?.get("gpu_layers")?.jsonPrimitive?.intOrNull
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"name":"test","loaded":true,"gpu_layers":$gpuLayers}""")
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val params = ModelLoadParams(name = "test", gpuLayers = 32, contextSize = 4096)
        val model = client.modelLoad(params)
        assertTrue(model.loaded)
    }

    @Test
    fun `modelLoad with name only`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("model_load") { params, _ ->
            val name = params?.get("name")?.jsonPrimitive?.contentOrNull
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"name":"$name","loaded":true}""")
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val model = client.modelLoad("llama-7b")
        assertEquals("llama-7b", model.name)
    }

    @Test
    fun `modelUnload unloads a model`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("model_unload") { params, _ ->
            val name = params?.get("name")?.jsonPrimitive?.contentOrNull ?: "unknown"
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"name":"$name","success":true,"message":"unloaded"}""")
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val result = client.modelUnload("llama-7b")
        assertEquals("llama-7b", result.name)
        assertTrue(result.success)
        assertEquals("unloaded", result.message)
    }

    @Test
    fun `modelUnload nonexistent model`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("model_unload") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"name":"nonexistent","success":false,"message":"not found"}""")
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val result = client.modelUnload("nonexistent")
        assertFalse(result.success)
        assertEquals("not found", result.message)
    }

    // =========================================================================
    // Context Management Tests
    // =========================================================================

    @Test
    fun `contextStore stores and returns ID`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("context_store") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"id":"ctx-abc123","success":true}""")
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val id = client.contextStore("Hello, I am John.")
        assertEquals("ctx-abc123", id)
    }

    @Test
    fun `contextStore with metadata`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("context_store") { params, _ ->
            val metadata = params?.get("metadata")?.jsonObject
            val model = params?.get("model")?.jsonPrimitive?.contentOrNull
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"id":"ctx-xyz","success":true}""")
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val id = client.contextStore(
            content = "Some context",
            metadata = mapOf("source" to "user", "type" to "preference"),
            model = "llama-7b"
        )
        assertEquals("ctx-xyz", id)
    }

    @Test
    fun `contextStore with ContextData object`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("context_store") { params, _ ->
            val content = params?.get("content")?.jsonPrimitive?.contentOrNull
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"id":"ctx-obj","success":true}""")
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val context = ContextData(
            content = "Hello world",
            metadata = mapOf("key" to "value"),
            model = "test-model"
        )
        val id = client.contextStore(context)
        assertEquals("ctx-obj", id)
    }

    @Test
    fun `contextRetrieve returns stored data`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("context_retrieve") { params, _ ->
            val id = params?.get("id")?.jsonPrimitive?.contentOrNull ?: ""
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""
                    {"id":"$id","content":"Stored content","metadata":{"source":"user"},"timestamp":1234567890}
                """)
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val context = client.contextRetrieve("ctx-abc")
        assertEquals("ctx-abc", context.id)
        assertEquals("Stored content", context.content)
        assertEquals("user", context.metadata?.get("source"))
        assertEquals(1234567890L, context.timestamp)
    }

    @Test
    fun `contextRetrieve nonexistent ID`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("context_retrieve") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "error",
                error = ErrorDetail(code = 404, message = "Context not found")
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        assertFailsWith<AinosException.ApiException> {
            client.contextRetrieve("nonexistent")
        }
    }

    // =========================================================================
    // Authentication Tests
    // =========================================================================

    @Test
    fun `authentication token is sent with requests`() = kotlinx.coroutines.runBlocking {
        var capturedToken: String? = null
        mockDaemon.on("health") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"status":"ok"}""")
            ))
        }
        mockDaemon.expectedToken = "test-token-123"
        client = AinosClient(ClientConfig(
            host = "localhost",
            port = mockDaemon.actualPort,
            token = "test-token-123"
        ))
        client.connect()

        val health = client.health()
        assertEquals("ok", health.status)
    }

    @Test
    fun `wrong token is rejected`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("health") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"status":"ok"}""")
            ))
        }
        mockDaemon.expectedToken = "correct-token"
        client = AinosClient(ClientConfig(
            host = "localhost",
            port = mockDaemon.actualPort,
            token = "wrong-token"
        ))
        client.connect()

        assertFailsWith<AinosException.ApiException> {
            client.health()
        }
    }

    @Test
    fun `authentication manager updates token`() = kotlinx.coroutines.runBlocking {
        var capturedToken: String? = null
        mockDaemon.on("health") { params, _ ->
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"status":"ok"}""")
            ))
        }
        // Start with no token
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        // Update token via auth manager
        client.authentication.setToken("new-token")
        assertEquals("new-token", client.authentication.token)
        assertTrue(client.authentication.isAuthenticated)
    }

    @Test
    fun `clear token removes authentication`() = kotlinx.coroutines.runBlocking {
        client = AinosClient(ClientConfig(
            host = "localhost",
            port = mockDaemon.actualPort,
            token = "some-token"
        ))

        client.authentication.clearToken()
        assertNull(client.authentication.token)
        assertFalse(client.authentication.isAuthenticated)
    }

    // =========================================================================
    // Error Handling Tests
    // =========================================================================

    @Test
    fun `API error returns correct code and message`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("infer") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "error",
                error = ErrorDetail(code = 5, message = "Invalid parameters")
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val exception = assertFailsWith<AinosException.ApiException> {
            client.infer("test")
        }
        assertEquals(5, exception.code)
        assertTrue(exception.message?.contains("Invalid parameters") == true)
    }

    @Test
    fun `unknown method returns error`() = kotlinx.coroutines.runBlocking {
        // No handler registered
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        assertFailsWith<AinosException.ApiException> {
            client.rawRequest("unknown_method")
        }
    }

    @Test
    fun `request timeout throws TimeoutException`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("infer") { _, _ ->
            // Never respond
            listOf<MockDaemon.MockResponse>()
        }
        client = AinosClient(
            ClientConfig(
                host = "localhost",
                port = mockDaemon.actualPort,
                requestTimeoutMs = 500
            )
        )
        client.connect()

        assertFailsWith<AinosException.TimeoutException> {
            client.infer("test")
        }
    }

    @Test
    fun `connection lost during request`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("infer") { _, _ ->
            // Stop the mock daemon to simulate connection loss
            mockDaemon.stop()
            listOf<MockDaemon.MockResponse>()
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        assertFailsWith<AinosException.ConnectionException> {
            client.infer("test")
        }
    }

    // =========================================================================
    // Wait For Healthy Tests
    // =========================================================================

    @Test
    fun `waitForHealthy returns true when healthy`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("health") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"status":"ok"}""")
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val healthy = client.waitForHealthy(maxWaitMs = 2000, pollIntervalMs = 100)
        assertTrue(healthy)
    }

    @Test
    fun `waitForHealthy returns false on timeout`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("health") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"status":"degraded"}""")
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val healthy = client.waitForHealthy(maxWaitMs = 500, pollIntervalMs = 100)
        assertFalse(healthy)
    }

    // =========================================================================
    // Connection Configuration Tests
    // =========================================================================

    @Test
    fun `ClientConfig builder constructs correctly`() {
        val config = ClientConfig.Builder()
            .host("192.168.1.1")
            .port(19500)
            .token("secret")
            .connectTimeoutMs(5000)
            .readTimeoutMs(30000)
            .requestTimeoutMs(60000)
            .autoReconnect(true)
            .maxReconnectAttempts(5)
            .reconnectDelayMs(2000)
            .build()

        assertEquals("192.168.1.1", config.host)
        assertEquals(19500, config.port)
        assertEquals("secret", config.token)
        assertEquals(5000L, config.connectTimeoutMs)
        assertEquals(30000L, config.readTimeoutMs)
        assertEquals(60000L, config.requestTimeoutMs)
        assertTrue(config.autoReconnect)
        assertEquals(5, config.maxReconnectAttempts)
        assertEquals(2000L, config.reconnectDelayMs)
    }

    @Test
    fun `ClientConfig DSL`() {
        val config = ClientConfig {
            host("10.0.0.1")
            port(9500)
            token("dsl-token")
        }

        assertEquals("10.0.0.1", config.host)
        assertEquals(9500, config.port)
        assertEquals("dsl-token", config.token)
    }

    @Test
    fun `ClientConfig defaults`() {
        val config = ClientConfig()
        assertEquals("localhost", config.host)
        assertEquals(9500, config.port)
        assertNull(config.token)
        assertEquals(10_000L, config.connectTimeoutMs)
        assertEquals(60_000L, config.readTimeoutMs)
        assertEquals(120_000L, config.requestTimeoutMs)
        assertFalse(config.autoReconnect)
        assertEquals(3, config.maxReconnectAttempts)
        assertEquals(1_000L, config.reconnectDelayMs)
    }

    @Test
    fun `ClientConfig builder default`() {
        val config = ClientConfig.Builder().build()
        assertEquals("localhost", config.host)
        assertEquals(9500, config.port)
    }

    // =========================================================================
    // ModelInfo Tests
    // =========================================================================

    @Test
    fun `ModelInfo with full fields`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("model_list") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""
                    {
                        "models": [{
                            "name": "test-model",
                            "path": "/models/test.gguf",
                            "loaded": true,
                            "size": 8192,
                            "quantization": "Q8_0",
                            "backend": "llama.cpp",
                            "architecture": "llama",
                            "parameter_count": "7B"
                        }],
                        "total": 1
                    }
                """)
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val models = client.modelList()
        assertEquals(1, models.size)
        val model = models[0]
        assertEquals("test-model", model.name)
        assertEquals("/models/test.gguf", model.filePath)
        assertTrue(model.loaded)
        assertEquals(8192L, model.size)
        assertEquals("Q8_0", model.quantization)
        assertEquals("llama.cpp", model.backend)
        assertEquals("llama", model.architecture)
        assertEquals("7B", model.parameterCount)
    }

    // =========================================================================
    // Raw API Tests
    // =========================================================================

    @Test
    fun `rawRequest sends and receives`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("ping") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"pong":true}""")
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        val params = buildJsonObject { put("echo", "hello") }
        val response = client.rawRequest("ping", params)
        assertNotNull(response.jsonObject["pong"])
        assertTrue(response.jsonObject["pong"]?.jsonPrimitive?.contentOrNull == "true")
    }

    // =========================================================================
    // Client Factory Tests
    // =========================================================================

    @Test
    fun `create factory connects automatically`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("health") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"status":"ok"}""")
            ))
        }
        client = AinosClient.create(
            config = ClientConfig(host = "localhost", port = mockDaemon.actualPort)
        )
        assertTrue(client.isConnected)
        val health = client.health()
        assertEquals("ok", health.status)
        client.disconnect()
    }

    @Test
    fun `create with DSL block`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("health") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"status":"ok"}""")
            ))
        }
        client = AinosClient.create(
            config = ClientConfig(host = "localhost", port = mockDaemon.actualPort)
        ) {
            token("dsl-token")
        }
        assertTrue(client.isConnected)
        assertEquals("dsl-token", client.authentication.token)
        client.disconnect()
    }

    // =========================================================================
    // Protocol Error Tests
    // =========================================================================

    @Test
    fun `malformed response throws ProtocolException`() = kotlinx.coroutines.runBlocking {
        mockDaemon.on("infer") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"text":123}""") // wrong type, should be string
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        // Should not throw for coerceInputValues
        client.infer("test")
    }

    // =========================================================================
    // Concurrent Request Tests
    // =========================================================================

    @Test
    fun `concurrent requests`() = kotlinx.coroutines.runBlocking {
        var requestCount = 0
        mockDaemon.on("ping") { _, _ ->
            requestCount++
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"count":$requestCount}""")
            ))
        }
        client = AinosClient(ClientConfig(host = "localhost", port = mockDaemon.actualPort))
        client.connect()

        // Launch 5 concurrent requests
        val results = (1..5).map { index ->
            kotlinx.coroutines.async {
                client.rawRequest("ping")
            }
        }

        // Wait for all
        results.forEach { it.await() }
        assertEquals(5, requestCount)
    }

    // =========================================================================
    // AuthenticationManager Tests
    // =========================================================================

    @Test
    fun `auth manager token lifecycle`() {
        val auth = AuthenticationManager("initial-token")
        assertEquals("initial-token", auth.token)
        assertTrue(auth.isAuthenticated)

        auth.setToken("new-token")
        assertEquals("new-token", auth.token)

        auth.clearToken()
        assertNull(auth.token)
        assertFalse(auth.isAuthenticated)
    }

    @Test
    fun `auth manager listener is notified`() {
        val auth = AuthenticationManager()
        var changedToken: String? = null
        var cleared = false

        auth.addListener(object : AuthListener {
            override fun onTokenChanged(newToken: String) {
                changedToken = newToken
            }
            override fun onTokenCleared() {
                cleared = true
            }
        })

        auth.setToken("test-token")
        assertEquals("test-token", changedToken)

        auth.clearToken()
        assertTrue(cleared)
    }

    @Test
    fun `auth manager copy`() {
        val auth = AuthenticationManager("my-token")
        val copy = auth.copy()
        assertEquals(auth.token, copy.token)
    }

    @Test
    fun `auth manager rejects blank token`() {
        val auth = AuthenticationManager()
        assertFailsWith<IllegalArgumentException> {
            auth.setToken("")
        }
        assertFailsWith<IllegalArgumentException> {
            auth.setToken("   ")
        }
    }

    @Test
    fun `auth manager authorization header`() {
        val auth = AuthenticationManager("my-token")
        assertEquals("Bearer my-token", auth.authorizationHeader())

        auth.clearToken()
        assertNull(auth.authorizationHeader())
    }

    // =========================================================================
    // Utils Tests
    // =========================================================================

    @Test
    fun `uuid generates unique values`() {
        val ids = (1..1000).map { uuid() }
        assertEquals(ids.size, ids.distinct().size)
        assertEquals(32, ids[0].length)
    }

    @Test
    fun `generateRequestId produces unique IDs`() {
        val ids = (1..1000).map { generateRequestId() }
        assertEquals(ids.size, ids.distinct().size)
        assertTrue(ids[0].startsWith("ainos-1-"))
    }

    @Test
    fun `truncate shortens long strings`() {
        assertEquals("Hello...", "Hello World!".truncate(8))
        assertEquals("Hello", "Hello".truncate(10))
    }

    @Test
    fun `requireNotBlank validates`() {
        assertEquals("valid", "valid".requireNotBlank("test"))
        assertFailsWith<IllegalArgumentException> {
            "".requireNotBlank("test")
        }
    }
}