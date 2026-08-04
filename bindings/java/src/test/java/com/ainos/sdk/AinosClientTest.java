package com.ainos.sdk;

import com.ainos.sdk.models.*;
import com.ainos.sdk.transport.JsonCodec;
import com.ainos.sdk.transport.TcpTransport;
import com.ainos.sdk.transport.TransportFactory;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.DisabledIfEnvironmentVariable;

import java.io.*;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for {@link AinosClient} using a mock TCP server.
 * <p>
 * These tests start a lightweight mock server that simulates the Ainos
 * daemon's NDJSON protocol, allowing tests without a running daemon.
 */
@Tag("integration")
public class AinosClientTest {

    private static MockDaemonServer mockServer;
    private static int mockPort;
    private static AinosClient client;

    @BeforeAll
    static void startMockServer() throws Exception {
        mockServer = new MockDaemonServer();
        mockServer.start();
        mockPort = mockServer.getPort();
    }

    @AfterAll
    static void stopMockServer() throws Exception {
        if (mockServer != null) {
            mockServer.stop();
        }
    }

    @BeforeEach
    void createClient() {
        client = AinosClient.builder()
                .host("127.0.0.1")
                .port(mockPort)
                .connectTimeoutMs(2000)
                .readTimeoutMs(5000)
                .autoReconnect(false)
                .build();
    }

    @AfterEach
    void destroyClient() throws Exception {
        if (client != null) {
            try {
                client.close();
            } catch (Exception ignored) {
            }
        }
        // Give the mock server time to clean up the old connection
        Thread.sleep(50);
    }

    // -----------------------------------------------------------------------
    // Connection tests
    // -----------------------------------------------------------------------

    @Test
    void testConnect() throws Exception {
        assertDoesNotThrow(() -> client.connect());
        assertTrue(client.isConnected());
    }

    @Test
    void testConnectTwice() throws Exception {
        client.connect();
        // Should not throw
        assertDoesNotThrow(() -> client.connect());
        assertTrue(client.isConnected());
    }

    @Test
    void testDisconnect() throws Exception {
        client.connect();
        assertTrue(client.isConnected());
        client.disconnect();
        assertFalse(client.isConnected());
    }

    @Test
    void testClose() throws Exception {
        client.connect();
        client.close();
        assertFalse(client.isConnected());
    }

    @Test
    void testConnectToInvalidPort() {
        AinosClient badClient = AinosClient.builder()
                .host("127.0.0.1")
                .port(19999)
                .connectTimeoutMs(1000)
                .readTimeoutMs(1000)
                .build();
        assertThrows(AinosConnectionException.class, badClient::connect);
    }

    // -----------------------------------------------------------------------
    // Authentication tests
    // -----------------------------------------------------------------------

    @Test
    void testAuthenticateSuccess() throws Exception {
        mockServer.setBehavior("Auth", (request, response) -> {
            response.put("type", "AuthResponse");
            response.put("success", true);
            response.put("session_token", "test-session-token-12345");
            response.put("message", "Authentication successful");
            response.put("permissions", Arrays.asList("infer", "status", "models"));
            response.put("session_ttl_seconds", 3600L);
        });

        client.connect();
        Map<String, Object> result = client.authenticate("test-token");
        assertNotNull(result);
        assertTrue((Boolean) result.get("success"));
        assertTrue(client.isAuthenticated());
        assertEquals("test-session-token-12345", client.getSessionToken());
        assertTrue(client.getPermissions().contains("infer"));
    }

    @Test
    void testAuthenticateFailure() throws Exception {
        mockServer.setBehavior("Auth", (request, response) -> {
            response.put("type", "AuthResponse");
            response.put("success", false);
            response.put("message", "Invalid token");
            response.put("permissions", new ArrayList<>());
            response.put("session_ttl_seconds", 0);
        });

        client.connect();
        assertThrows(AinosAuthException.class, () -> client.authenticate("bad-token"));
        assertFalse(client.isAuthenticated());
    }

    @Test
    void testAuthenticateNullToken() {
        assertThrows(AinosAuthException.class, () -> client.authenticate(null));
    }

    @Test
    void testAuthenticateEmptyToken() {
        assertThrows(AinosAuthException.class, () -> client.authenticate(""));
    }

    @Test
    void testAutoAuthenticate() throws Exception {
        mockServer.setBehavior("Auth", (request, response) -> {
            response.put("type", "AuthResponse");
            response.put("success", true);
            response.put("session_token", "auto-session-token");
            response.put("message", "Authentication successful");
            response.put("permissions", Collections.singletonList("infer"));
            response.put("session_ttl_seconds", 3600L);
        });

        AinosClient autoClient = AinosClient.builder()
                .host("127.0.0.1")
                .port(mockPort)
                .connectTimeoutMs(2000)
                .readTimeoutMs(5000)
                .authToken("auto-token")
                .autoAuthenticate(true)
                .build();

        try {
            autoClient.connect();
            assertTrue(autoClient.isAuthenticated());
        } finally {
            autoClient.close();
        }
    }

    // -----------------------------------------------------------------------
    // Inference tests
    // -----------------------------------------------------------------------

    @Test
    void testInfer() throws Exception {
        mockServer.setBehavior("Inference", (request, response) -> {
            response.put("type", "InferenceResponse");
            response.put("output", "Hello! I am an AI assistant.");
            response.put("tokens_generated", 8);
            response.put("inference_ms", 150);
            response.put("source", "local");
        });

        client.connect();
        InferenceRequest req = InferenceRequest.builder()
                .prompt("Hello")
                .model("default")
                .temperature(0.7)
                .maxTokens(100)
                .build();

        InferenceResponse resp = client.infer(req);
        assertNotNull(resp);
        assertEquals("Hello! I am an AI assistant.", resp.getOutput());
        assertEquals(8, resp.getTokensGenerated());
        assertEquals(150, resp.getInferenceMs());
        assertEquals("local", resp.getSource());
    }

    @Test
    void testInferError() throws Exception {
        mockServer.setBehavior("Inference", (request, response) -> {
            response.put("type", "Error");
            response.put("code", -1);
            response.put("message", "Model not loaded");
        });

        client.connect();
        InferenceRequest req = InferenceRequest.of("test");
        assertThrows(AinosInferenceException.class, () -> client.infer(req));
    }

    @Test
    void testBatchInfer() throws Exception {
        mockServer.setBehavior("Inference", (request, response) -> {
            response.put("type", "InferenceResponse");
            response.put("output", "Batch response");
            response.put("tokens_generated", 2);
            response.put("inference_ms", 10);
            response.put("source", "local");
        });

        client.connect();
        List<InferenceRequest> requests = Arrays.asList(
                InferenceRequest.of("req1"),
                InferenceRequest.of("req2"),
                InferenceRequest.of("req3")
        );

        List<InferenceResponse> results = client.batchInfer(requests);
        assertEquals(3, results.size());
        for (InferenceResponse r : results) {
            assertEquals("Batch response", r.getOutput());
        }
    }

    // -----------------------------------------------------------------------
    // Status tests
    // -----------------------------------------------------------------------

    @Test
    void testStatus() throws Exception {
        mockServer.setBehavior("Status", (request, response) -> {
            response.put("type", "StatusResponse");
            response.put("uptime", 3600L);
            response.put("models_loaded", 2);
            response.put("total_requests", 42L);
            response.put("network_available", true);
            response.put("active_sessions", 3);
        });

        client.connect();
        SystemStatus status = client.status();
        assertEquals(3600, status.getUptime());
        assertEquals(2, status.getModelsLoaded());
        assertEquals(42, status.getTotalRequests());
        assertTrue(status.isNetworkAvailable());
        assertEquals(3, status.getActiveSessions());
    }

    @Test
    void testHealth() throws Exception {
        mockServer.setBehavior("Status", (request, response) -> {
            response.put("type", "StatusResponse");
            response.put("uptime", 100L);
            response.put("models_loaded", 1);
            response.put("total_requests", 10L);
            response.put("network_available", true);
            response.put("active_sessions", 1);
        });

        client.connect();
        HealthStatus health = client.health();
        assertTrue(health.isHealthy());
        assertEquals("OK", health.getMessage());
        assertEquals(100, health.getUptime());
    }

    @Test
    void testHealthWithoutConnection() {
        // Should not throw -- health() handles connection errors gracefully
        HealthStatus health = client.health();
        assertFalse(health.isHealthy());
    }

    // -----------------------------------------------------------------------
    // Model management tests
    // -----------------------------------------------------------------------

    @Test
    void testModelList() throws Exception {
        List<Map<String, Object>> models = new ArrayList<>();
        Map<String, Object> model1 = new LinkedHashMap<>();
        model1.put("id", "phi_3_mini");
        model1.put("name", "phi-3-mini-4k-instruct-q4.gguf");
        model1.put("path", "/models/phi-3-mini.gguf");
        model1.put("size_mb", 2048L);
        model1.put("loaded", true);
        model1.put("architecture", "phi3");
        models.add(model1);

        Map<String, Object> model2 = new LinkedHashMap<>();
        model2.put("id", "llama_3_2");
        model2.put("name", "llama-3.2-3b.gguf");
        model2.put("path", "/models/llama-3.2.gguf");
        model2.put("size_mb", 3072L);
        model2.put("loaded", false);
        model2.put("architecture", "llama");
        models.add(model2);

        Map<String, Object> responseMap = new LinkedHashMap<>();
        responseMap.put("type", "ModelListResponse");
        responseMap.put("models", models);

        mockServer.setBehavior("ModelList", (request, response) -> response.putAll(responseMap));

        client.connect();
        List<ModelInfo> result = client.modelList();
        assertEquals(2, result.size());

        ModelInfo first = result.get(0);
        assertEquals("phi_3_mini", first.getId());
        assertEquals("phi-3-mini-4k-instruct-q4.gguf", first.getName());
        assertEquals("/models/phi-3-mini.gguf", first.getPath());
        assertEquals(2048, first.getSizeMb());
        assertTrue(first.isLoaded());
        assertEquals("phi3", first.getArchitecture());
    }

    @Test
    void testModelLoad() throws Exception {
        mockServer.setBehavior("ModelLoad", (request, response) -> {
            response.put("type", "ModelLoadResponse");
            response.put("model_id", "phi_3_mini");
            response.put("status", "loaded");
            response.put("message", "Model loaded successfully");

            Map<String, Object> modelInfo = new LinkedHashMap<>();
            modelInfo.put("id", "phi_3_mini");
            modelInfo.put("name", "phi-3-mini.gguf");
            modelInfo.put("path", "/models/phi-3-mini.gguf");
            modelInfo.put("size_mb", 2048L);
            modelInfo.put("loaded", true);
            modelInfo.put("architecture", "auto");
            response.put("model_info", modelInfo);
        });

        client.connect();
        ModelLoadOptions opts = ModelLoadOptions.builder()
                .architecture("phi3")
                .gpuLayerCount(32)
                .build();

        ModelInfo info = client.modelLoad("/models/phi-3-mini.gguf", opts);
        assertEquals("phi_3_mini", info.getId());
        assertTrue(info.isLoaded());
    }

    @Test
    void testModelUnload() throws Exception {
        mockServer.setBehavior("ModelUnload", (request, response) -> {
            response.put("type", "ModelUnloadResponse");
            response.put("model_id", "phi_3_mini");
            response.put("status", "unloaded");
            response.put("message", "Model unloaded successfully");
        });

        client.connect();
        assertDoesNotThrow(() -> client.modelUnload("phi_3_mini"));
    }

    // -----------------------------------------------------------------------
    // Context store tests
    // -----------------------------------------------------------------------

    @Test
    void testContextStore() throws Exception {
        mockServer.setBehavior("ContextStore", (request, response) -> {
            response.put("type", "InferenceResponse");
            response.put("output", "Context stored: my-key");
            response.put("tokens_generated", 0);
            response.put("inference_ms", 0);
            response.put("source", "local");
        });

        client.connect();
        assertDoesNotThrow(() ->
                client.contextStore("session-1", "my-key", "hello-world".getBytes(StandardCharsets.UTF_8), 3600));
    }

    @Test
    void testContextRetrieve() throws Exception {
        mockServer.setBehavior("ContextRetrieve", (request, response) -> {
            response.put("type", "InferenceResponse");
            response.put("output", Base64.getEncoder().encodeToString("stored-value".getBytes(StandardCharsets.UTF_8)));
            response.put("tokens_generated", 0);
            response.put("inference_ms", 0);
            response.put("source", "local");
        });

        client.connect();
        byte[] value = client.contextRetrieve("session-1", "my-key");
        assertNotNull(value);
        assertEquals("stored-value", new String(value, StandardCharsets.UTF_8));
    }

    @Test
    void testContextRetrieveMissing() throws Exception {
        mockServer.setBehavior("ContextRetrieve", (request, response) -> {
            response.put("type", "Error");
            response.put("code", -1);
            response.put("message", "Key not found: missing-key");
        });

        client.connect();
        byte[] value = client.contextRetrieve("session-1", "missing-key");
        assertNull(value);
    }

    // -----------------------------------------------------------------------
    // Rate limit tests
    // -----------------------------------------------------------------------

    @Test
    void testRateLimitStatus() throws Exception {
        List<Map<String, Object>> limits = new ArrayList<>();
        Map<String, Object> inferenceLimit = new LinkedHashMap<>();
        inferenceLimit.put("category", "inference");
        inferenceLimit.put("limit", 100L);
        inferenceLimit.put("remaining", 95L);
        inferenceLimit.put("reset_seconds", 30L);
        limits.add(inferenceLimit);

        Map<String, Object> responseMap = new LinkedHashMap<>();
        responseMap.put("type", "RateLimitStatusResponse");
        responseMap.put("limits", limits);

        mockServer.setBehavior("RateLimitStatus", (request, response) -> response.putAll(responseMap));

        client.connect();
        RateLimitStatus rls = client.rateLimitStatus();
        assertNotNull(rls);
        assertEquals(1, rls.getLimits().size());
        assertEquals("inference", rls.getLimits().get(0).getCategory());
        assertEquals(100, rls.getLimits().get(0).getLimit());
        assertEquals(95, rls.getLimits().get(0).getRemaining());
    }

    // -----------------------------------------------------------------------
    // Error handling tests
    // -----------------------------------------------------------------------

    @Test
    void testNotConnected() {
        assertThrows(AinosConnectionException.class,
                () -> client.infer(InferenceRequest.of("test")));
    }

    @Test
    void testErrorResponse() throws Exception {
        mockServer.setBehavior("Inference", (request, response) -> {
            response.put("type", "Error");
            response.put("code", 401);
            response.put("message", "Authentication required");
        });

        client.connect();
        assertThrows(AinosInferenceException.class,
                () -> client.infer(InferenceRequest.of("test")));
    }

    @Test
    void testRateLimitError() throws Exception {
        mockServer.setBehavior("Inference", (request, response) -> {
            response.put("type", "Error");
            response.put("code", 429);
            response.put("message", "Rate limit exceeded for Inference. Retry after 30 seconds.");
        });

        client.connect();
        try {
            client.infer(InferenceRequest.of("test"));
            fail("Expected AinosInferenceException");
        } catch (AinosInferenceException e) {
            assertTrue(e.getMessage().contains("Rate limit"));
        }
    }

    // -----------------------------------------------------------------------
    // Builder tests
    // -----------------------------------------------------------------------

    @Test
    void testBuilderDefaults() {
        AinosClientBuilder builder = AinosClient.builder();
        assertEquals("127.0.0.1", builder.getHost());
        assertEquals(9500, builder.getPort());
        assertEquals(5000, builder.getConnectTimeoutMs());
        assertEquals(120000, builder.getReadTimeoutMs());
        assertTrue(builder.isAutoReconnect());
        assertEquals(1000, builder.getReconnectDelayMs());
        assertEquals(3, builder.getMaxReconnectAttempts());
        assertTrue(builder.isAutoAuthenticate());
        assertNull(builder.getAuthToken());
        assertFalse(builder.isUseConnectionPool());
        assertEquals(4, builder.getPoolSize());
    }

    @Test
    void testBuilderCustomization() {
        AinosClient client = AinosClient.builder()
                .host("10.0.0.1")
                .port(19500)
                .connectTimeoutMs(10000)
                .readTimeoutMs(30000)
                .autoReconnect(false)
                .reconnectDelayMs(2000)
                .maxReconnectAttempts(5)
                .authToken("my-token")
                .autoAuthenticate(false)
                .useConnectionPool(true)
                .poolSize(8)
                .build();

        assertNotNull(client);
    }

    @Test
    void testBuilderCopy() {
        AinosClientBuilder original = AinosClient.builder()
                .host("10.0.0.1")
                .port(19500)
                .authToken("secret");
        AinosClientBuilder copy = original.copy();
        assertEquals(original.getHost(), copy.getHost());
        assertEquals(original.getPort(), copy.getPort());
        assertEquals(original.getAuthToken(), copy.getAuthToken());
    }

    // -----------------------------------------------------------------------
    // Thread safety tests
    // -----------------------------------------------------------------------

    @Test
    void testConcurrentRequests() throws Exception {
        mockServer.setBehavior("Inference", (request, response) -> {
            response.put("type", "InferenceResponse");
            response.put("output", "concurrent-result");
            response.put("tokens_generated", 1);
            response.put("inference_ms", 5);
            response.put("source", "local");
        });

        client.connect();

        int threadCount = 10;
        ExecutorService executor = Executors.newFixedThreadPool(threadCount);
        List<Future<InferenceResponse>> futures = new ArrayList<>();

        for (int i = 0; i < threadCount; i++) {
            futures.add(executor.submit(() ->
                    client.infer(InferenceRequest.of("concurrent-test"))));
        }

        for (Future<InferenceResponse> future : futures) {
            InferenceResponse resp = future.get(5, TimeUnit.SECONDS);
            assertNotNull(resp);
            assertEquals("concurrent-result", resp.getOutput());
        }

        executor.shutdown();
    }

    // -----------------------------------------------------------------------
    // Mock daemon server
    // -----------------------------------------------------------------------

    /**
     * A lightweight mock TCP server that simulates the Ainos daemon's NDJSON protocol.
     * <p>
     * Accepts multiple connections and processes JSON-line requests, returning
     * configurable responses based on the request type.
     */
    static class MockDaemonServer {

        private final com.google.gson.Gson gson = new com.google.gson.Gson();
        private final Map<String, Behavior> behaviors = new ConcurrentHashMap<>();
        private final AtomicBoolean running = new AtomicBoolean(false);
        private final Object acceptLock = new Object();

        private ServerSocket serverSocket;
        private Thread serverThread;
        private int port;
        private Socket clientSocket;
        private BufferedReader reader;
        private BufferedWriter writer;

        @FunctionalInterface
        interface Behavior {
            void apply(Map<String, Object> request, Map<String, Object> response);
        }

        void setBehavior(String type, Behavior behavior) {
            behaviors.put(type, behavior);
        }

        void start() throws Exception {
            serverSocket = new ServerSocket(0);
            port = serverSocket.getLocalPort();
            running.set(true);

            // Set default behaviors
            setDefaultBehaviors();

            serverThread = new Thread(() -> {
                while (running.get()) {
                    try {
                        Socket socket = serverSocket.accept();
                        // Handle each client in a separate thread to avoid blocking the accept loop
                        new Thread(() -> handleClient(socket), "mock-client-handler").start();
                    } catch (Exception e) {
                        if (running.get()) {
                            // Log but continue accepting
                        }
                    }
                }
            }, "mock-daemon");
            serverThread.setDaemon(true);
            serverThread.start();
        }

        private void handleClient(Socket socket) {
            try (socket) {
                this.clientSocket = socket;
                BufferedReader reader = new BufferedReader(
                        new InputStreamReader(socket.getInputStream(), StandardCharsets.UTF_8));
                BufferedWriter writer = new BufferedWriter(
                        new OutputStreamWriter(socket.getOutputStream(), StandardCharsets.UTF_8));

                String line;
                while (running.get() && (line = reader.readLine()) != null) {
                    if (line.isEmpty()) continue;
                    try {
                        @SuppressWarnings("unchecked")
                        Map<String, Object> request = gson.fromJson(line, Map.class);
                        String type = (String) request.get("type");

                        Map<String, Object> response = new LinkedHashMap<>();
                        Behavior behavior = behaviors.get(type);
                        if (behavior != null) {
                            behavior.apply(request, response);
                        } else {
                            response.put("type", "Error");
                            response.put("code", -1);
                            response.put("message", "No handler for: " + type);
                        }

                        String json = gson.toJson(response);
                        writer.write(json);
                        writer.write('\n');
                        writer.flush();
                    } catch (Exception e) {
                        Map<String, Object> error = new LinkedHashMap<>();
                        error.put("type", "Error");
                        error.put("code", -1);
                        error.put("message", "Server error: " + e.getMessage());
                        String json = gson.toJson(error);
                        writer.write(json);
                        writer.write('\n');
                        writer.flush();
                    }
                }
            } catch (Exception e) {
                if (running.get()) {
                    // Client disconnected, ready for next connection
                }
            }
        }

        void stop() {
            running.set(false);
            try {
                if (clientSocket != null) clientSocket.close();
            } catch (Exception ignored) {}
            try {
                if (serverSocket != null) serverSocket.close();
            } catch (Exception ignored) {}
        }

        int getPort() {
            return port;
        }

        private void setDefaultBehaviors() {
            // Default: all request types return an error
            behaviors.put("Auth", (request, response) -> {
                response.put("type", "AuthResponse");
                response.put("success", true);
                response.put("session_token", "default-session-token");
                response.put("message", "Authentication successful");
                response.put("permissions", Collections.singletonList("infer"));
                response.put("session_ttl_seconds", 3600L);
            });
        }
    }
}