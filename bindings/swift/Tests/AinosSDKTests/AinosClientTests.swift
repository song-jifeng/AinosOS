//===----------------------------------------------------------------------===//
//
// This source file is part of the Ainos SDK for Swift open source project
//
// Copyright (c) 2024 Ainos AI and the Ainos SDK project authors
// Licensed under Apache License v2.0
//
// See LICENSE.txt for license information
//
// SPDX-License-Identifier: Apache-2.0
//
//===----------------------------------------------------------------------===//

import Foundation
@testable import AinosSDK
import XCTest

// MARK: - AinosClientTests

/// Tests for the AinosClient class.
///
/// These tests use a `MockTransport` to simulate the daemon without
/// requiring a real TCP connection. The mock transport records sent
/// data and returns pre-configured responses.
final class AinosClientTests: XCTestCase {

    // MARK: - Properties

    var mockTransport: MockTransport!
    var client: AinosClient!

    // MARK: - Setup & Teardown

    override func setUp() async throws {
        try await super.setUp()
        mockTransport = MockTransport()
        client = AinosClient(
            config: AinosClientConfig(
                host: "127.0.0.1",
                port: 9500,
                token: "test-token",
                verbose: false
            ),
            transport: mockTransport
        )
    }

    override func tearDown() async throws {
        mockTransport.reset()
        mockTransport = nil
        client = nil
        try await super.tearDown()
    }

    // MARK: - Connection Tests

    /// Tests that connect() sends the correct connect request.
    func testConnectSendsConnectRequest() async throws {
        // Configure mock to respond with a valid connect response
        mockTransport.enqueueResponse(connectResponseJSON())

        try await client.connect()

        // Verify the connection state
        XCTAssertEqual(client.connectionState, .connected)

        // Verify the session info was populated
        XCTAssertNotNil(client.daemonVersion)
        XCTAssertNotNil(client.sessionId)
        XCTAssertNotNil(client.capabilities)

        // Verify the last sent message contains the connect type
        let lastSent = mockTransport.lastSentString ?? ""
        XCTAssertTrue(lastSent.contains("connect"), "Expected connect request, got: \(lastSent)")
    }

    /// Tests that connect() throws when the daemon rejects.
    func testConnectThrowsOnRejection() async throws {
        mockTransport.enqueueResponse(errorResponseJSON(code: "auth_failed", message: "Invalid token"))

        do {
            try await client.connect()
            XCTFail("Expected connection to throw")
        } catch let error as AinosError {
            XCTAssertEqual(error.code, .invalidResponse)
        }
    }

    /// Tests that connect() throws when the mock simulates connection failure.
    func testConnectThrowsOnTransportFailure() async throws {
        mockTransport.simulateConnectionFailure = true

        do {
            try await client.connect()
            XCTFail("Expected connection to throw")
        } catch let error as AinosError {
            XCTAssertTrue(error.isConnectionError)
        }
    }

    /// Tests that disconnect() cleans up state.
    func testDisconnectCleansUp() async throws {
        mockTransport.enqueueResponse(connectResponseJSON())
        try await client.connect()
        XCTAssertEqual(client.connectionState, .connected)

        // Disconnect
        await client.disconnect()
        XCTAssertEqual(client.connectionState, .disconnected)
    }

    // MARK: - Inference Tests

    /// Tests that infer() returns the correct response.
    func testInferReturnsResponse() async throws {
        // Setup connection
        mockTransport.enqueueResponse(connectResponseJSON())
        try await client.connect()

        // Enqueue infer response
        let inferResponse = TestData.inferResponse(text: "Hello, world!")
        mockTransport.enqueueResponse(inferResponseJSON(from: inferResponse))

        let response = try await client.infer(model: "test-model", prompt: "Hello")

        XCTAssertEqual(response.text, "Hello, world!")
        XCTAssertEqual(response.model, "test-model")
        XCTAssertNotNil(response.usage)
        XCTAssertEqual(response.usage?.totalTokens, 8)
    }

    /// Tests that infer() throws when not connected.
    func testInferThrowsWhenNotConnected() async throws {
        do {
            _ = try await client.infer(model: "test", prompt: "Hello")
            XCTFail("Expected error when not connected")
        } catch let error as AinosError {
            XCTAssertEqual(error.code, .connectionClosed)
        }
    }

    /// Tests that infer() with messages works.
    func testInferWithMessages() async throws {
        mockTransport.enqueueResponse(connectResponseJSON())
        try await client.connect()

        mockTransport.enqueueResponse(inferResponseJSON(from: TestData.inferResponse(text: "Hi")))

        let messages = [
            Message(role: .system, content: "You are a helpful assistant."),
            Message(role: .user, content: "Hello!")
        ]

        let response = try await client.chat(model: "test-model", messages: messages)
        XCTAssertEqual(response.text, "Hi")
    }

    // MARK: - Streaming Tests

    /// Tests that inferStream() returns a stream of events.
    func testInferStreamReturnsEvents() async throws {
        mockTransport.enqueueResponse(connectResponseJSON())
        try await client.connect()

        // Enqueue stream events
        mockTransport.enqueueResponse(streamEventJSON(text: "Hello", index: 0))
        mockTransport.enqueueResponse(streamEventJSON(text: " ", index: 1))
        mockTransport.enqueueResponse(streamEventJSON(text: "world", index: 2))
        mockTransport.enqueueResponse(streamDoneJSON())

        let stream = try await client.inferStream(model: "test-model", prompt: "Hi")

        var events: [StreamEvent] = []
        for try await event in stream {
            events.append(event)
        }

        XCTAssertEqual(events.count, 4, "Expected 4 stream events")
        XCTAssertEqual(events[0].type, .token)
        XCTAssertEqual(events[0].delta, "Hello")
        XCTAssertEqual(events[1].delta, " ")
        XCTAssertEqual(events[2].delta, "world")
        XCTAssertEqual(events[3].type, .done)
    }

    /// Tests that stream textDeltas() helper works.
    func testStreamTextDeltas() async throws {
        mockTransport.enqueueResponse(connectResponseJSON())
        try await client.connect()

        mockTransport.enqueueResponse(streamEventJSON(text: "Hello", index: 0))
        mockTransport.enqueueResponse(streamEventJSON(text: " ", index: 1))
        mockTransport.enqueueResponse(streamEventJSON(text: "world", index: 2))
        mockTransport.enqueueResponse(streamDoneJSON())

        let stream = try await client.inferStream(model: "test-model", prompt: "Hi")
        let text = try await stream.textDeltas().collectText()

        XCTAssertEqual(text, "Hello world")
    }

    /// Tests that inferStream() throws when not connected.
    func testInferStreamThrowsWhenNotConnected() async throws {
        do {
            _ = try await client.inferStream(model: "test", prompt: "Hello")
            XCTFail("Expected error")
        } catch let error as AinosError {
            XCTAssertEqual(error.code, .connectionClosed)
        }
    }

    // MARK: - Model Management Tests

    /// Tests that modelList() returns the list of models.
    func testModelList() async throws {
        mockTransport.enqueueResponse(connectResponseJSON())
        try await client.connect()

        mockTransport.enqueueResponse(modelListResponseJSON())

        let response = try await client.modelList()

        XCTAssertEqual(response.total, 2)
        XCTAssertEqual(response.models.count, 2)
        XCTAssertEqual(response.models[0].id, "model-1")
        XCTAssertTrue(response.models[0].isLoaded)
        XCTAssertFalse(response.models[1].isLoaded)
    }

    /// Tests that modelLoad() succeeds.
    func testModelLoad() async throws {
        mockTransport.enqueueResponse(connectResponseJSON())
        try await client.connect()

        let loadResponse = ModelOperationResponse(
            success: true,
            model: "test-model",
            message: "Loaded",
            durationMs: 1000
        )
        mockTransport.enqueueResponse(operationResponseJSON(from: loadResponse))

        let response = try await client.modelLoad(model: "test-model")

        XCTAssertTrue(response.success)
        XCTAssertEqual(response.model, "test-model")
        XCTAssertEqual(response.durationMs, 1000)
    }

    /// Tests that modelUnload() succeeds.
    func testModelUnload() async throws {
        mockTransport.enqueueResponse(connectResponseJSON())
        try await client.connect()

        let unloadResponse = ModelOperationResponse(
            success: true,
            model: "test-model",
            message: "Unloaded",
            durationMs: 500
        )
        mockTransport.enqueueResponse(operationResponseJSON(from: unloadResponse))

        let response = try await client.modelUnload(model: "test-model")

        XCTAssertTrue(response.success)
        XCTAssertEqual(response.model, "test-model")
    }

    /// Tests that modelLoad() with config works.
    func testModelLoadWithConfig() async throws {
        mockTransport.enqueueResponse(connectResponseJSON())
        try await client.connect()

        let loadResponse = ModelOperationResponse(
            success: true,
            model: "test-model",
            message: "Loaded with GPU",
            durationMs: 2000
        )
        mockTransport.enqueueResponse(operationResponseJSON(from: loadResponse))

        let config = ModelLoadConfig(
            gpuLayers: 32,
            contextSize: 4096,
            threads: 8
        )

        let response = try await client.modelLoad(model: "test-model", config: config)
        XCTAssertTrue(response.success)
    }

    // MARK: - Health & Status Tests

    /// Tests that health() returns the correct response.
    func testHealth() async throws {
        mockTransport.enqueueResponse(connectResponseJSON())
        try await client.connect()

        mockTransport.enqueueResponse(healthResponseJSON())

        let response = try await client.health()

        XCTAssertTrue(response.healthy)
        XCTAssertEqual(response.version, "1.0.0")
        XCTAssertNotNil(response.uptimeSeconds)
    }

    /// Tests that health() returns unhealthy when not connected.
    func testHealthWhenNotConnected() async throws {
        // Health should work even without a full connection
        // but if the transport fails, it should return unhealthy
        mockTransport.simulateConnectionFailure = true

        let response = try await client.health()
        XCTAssertFalse(response.healthy)
    }

    /// Tests that status() returns daemon status.
    func testStatus() async throws {
        mockTransport.enqueueResponse(connectResponseJSON())
        try await client.connect()

        mockTransport.enqueueResponse(statusResponseJSON())

        let response = try await client.status()

        XCTAssertEqual(response.version, "1.0.0")
        XCTAssertEqual(response.state, .ready)
        XCTAssertEqual(response.loadedModels.count, 1)
        XCTAssertNotNil(response.systemMemory)
    }

    // MARK: - Context Store Tests

    /// Tests that contextStore() and contextRetrieve() work.
    func testContextStoreAndRetrieve() async throws {
        mockTransport.enqueueResponse(connectResponseJSON())
        try await client.connect()

        // Store
        mockTransport.enqueueResponse(storeResponseJSON())
        let storeResponse = try await client.contextStore(
            key: "test-key",
            value: ["data": AnyCodable("test-value")]
        )
        XCTAssertTrue(storeResponse.success)
        XCTAssertEqual(storeResponse.key, "test-key")

        // Retrieve
        mockTransport.enqueueResponse(retrieveResponseJSON())
        let retrieveResponse = try await client.contextRetrieve(key: "test-key")
        XCTAssertTrue(retrieveResponse.success)
        XCTAssertEqual(retrieveResponse.key, "test-key")
    }

    /// Tests that contextRetrieve() throws when key is not found.
    func testContextRetrieveNotFound() async throws {
        mockTransport.enqueueResponse(connectResponseJSON())
        try await client.connect()

        mockTransport.enqueueResponse(errorResponseJSON(code: "not_found", message: "Key not found"))

        do {
            _ = try await client.contextRetrieve(key: "nonexistent")
            XCTFail("Expected error")
        } catch let error as AinosError {
            // The error should be in the frame error
            XCTAssertTrue(error.code == .invalidResponse || error.code.rawValue == "not_found")
        }
    }

    // MARK: - Convenience Methods Tests

    /// Tests the generate() convenience method.
    func testGenerate() async throws {
        mockTransport.enqueueResponse(connectResponseJSON())
        try await client.connect()

        mockTransport.enqueueResponse(inferResponseJSON(from: TestData.inferResponse(text: "Generated text")))

        let text = try await client.generate(model: "test-model", prompt: "Write something")
        XCTAssertEqual(text, "Generated text")
    }

    /// Tests the isHealthy() convenience method.
    func testIsHealthy() async throws {
        mockTransport.enqueueResponse(connectResponseJSON())
        try await client.connect()

        mockTransport.enqueueResponse(healthResponseJSON())

        let healthy = await client.isHealthy()
        XCTAssertTrue(healthy)
    }

    /// Tests the isHealthy() method when daemon is down.
    func testIsHealthyWhenDown() async {
        let localClient = AinosClient(
            config: AinosClientConfig(host: "127.0.0.1", port: 1),
            transport: MockTransport()
        )

        let healthy = await localClient.isHealthy()
        XCTAssertFalse(healthy)
    }

    // MARK: - Error Handling Tests

    /// Tests that errors are properly propagated.
    func testErrorPropagation() async throws {
        mockTransport.enqueueResponse(connectResponseJSON())
        try await client.connect()

        mockTransport.enqueueResponse(errorResponseJSON(code: "model_not_found", message: "Model not found"))

        do {
            _ = try await client.infer(model: "nonexistent", prompt: "Hi")
            XCTFail("Expected error")
        } catch let error as AinosError {
            XCTAssertTrue(error.code == .invalidResponse || error.code.rawValue == "model_not_found")
        }
    }

    /// Tests that connection errors are thrown correctly.
    func testConnectionStateChanges() async throws {
        XCTAssertEqual(client.connectionState, .disconnected)

        mockTransport.enqueueResponse(connectResponseJSON())
        try await client.connect()
        XCTAssertEqual(client.connectionState, .connected)

        await client.disconnect()
        XCTAssertEqual(client.connectionState, .disconnected)
    }

    /// Tests that attempting operations after disconnect throws.
    func testOperationsAfterDisconnect() async throws {
        mockTransport.enqueueResponse(connectResponseJSON())
        try await client.connect()
        await client.disconnect()

        do {
            _ = try await client.infer(model: "test", prompt: "Hello")
            XCTFail("Expected error")
        } catch let error as AinosError {
            XCTAssertEqual(error.code, .connectionClosed)
        }
    }

    // MARK: - Metrics Tests

    /// Tests that metrics are collected correctly.
    func testMetricsCollection() async throws {
        mockTransport.enqueueResponse(connectResponseJSON())
        try await client.connect()

        mockTransport.enqueueResponse(inferResponseJSON(from: TestData.inferResponse()))
        _ = try await client.infer(model: "test", prompt: "Hi")

        let metrics = client.getMetrics()
        XCTAssertGreaterThan(metrics.requestsSent, 0)
        XCTAssertGreaterThan(metrics.responsesReceived, 0)
        XCTAssertGreaterThan(metrics.bytesSent, 0)
        XCTAssertGreaterThan(metrics.bytesReceived, 0)
    }

    // MARK: - Configuration Tests

    /// Tests that the client respects configuration.
    func testClientConfiguration() {
        let config = AinosClientConfig(
            host: "10.0.0.1",
            port: 9000,
            token: "custom-token",
            connectionTimeout: 30,
            readTimeout: 120,
            verbose: true
        )

        let customClient = AinosClient(config: config)
        XCTAssertEqual(customClient.config.host, "10.0.0.1")
        XCTAssertEqual(customClient.config.port, 9000)
        XCTAssertEqual(customClient.config.token, "custom-token")
        XCTAssertEqual(customClient.config.connectionTimeout, 30, accuracy: 0.1)
        XCTAssertEqual(customClient.config.readTimeout, 120, accuracy: 0.1)
        XCTAssertTrue(customClient.config.verbose)
    }

    // MARK: - JSON Response Helpers

    private func connectResponseJSON() -> String {
        let response = TestData.connectResponse()
        return wrapResponse(response, requestId: "test-conn-1")
    }

    private func inferResponseJSON(from response: InferResponse) -> String {
        wrapResponse(response, requestId: "test-inf-1")
    }

    private func streamEventJSON(text: String, index: Int) -> String {
        let event = TestData.tokenEvent(text, index: index)
        return wrapResponse(event, requestId: "test-str-1")
    }

    private func streamDoneJSON() -> String {
        let event = TestData.doneEvent()
        return wrapResponse(event, requestId: "test-str-1")
    }

    private func modelListResponseJSON() -> String {
        let response = TestData.modelList()
        return wrapResponse(response, requestId: "test-ml-1")
    }

    private func operationResponseJSON(from response: ModelOperationResponse) -> String {
        wrapResponse(response, requestId: "test-op-1")
    }

    private func healthResponseJSON() -> String {
        let response = HealthResponse(
            healthy: true,
            uptimeSeconds: 3600,
            version: "1.0.0",
            activeConnections: 1,
            memoryUsageBytes: 500_000_000
        )
        return wrapResponse(response, requestId: "test-hlth-1")
    }

    private func statusResponseJSON() -> String {
        let response = DaemonStatus(
            version: "1.0.0",
            state: .ready,
            loadedModels: [
                ModelInfo(
                    id: "model-1",
                    name: "Model 1",
                    version: "1.0",
                    format: "gguf",
                    backend: "cpu",
                    family: "llama",
                    sizeBytes: 1_000_000_000,
                    isLoaded: true,
                    parameterCount: "7B",
                    contextLength: 2048,
                    description: nil,
                    license: nil,
                    metadata: nil
                )
            ],
            totalInferences: 42,
            activeInferences: 0,
            modelMemoryBytes: 1_000_000_000,
            systemMemory: SystemMemory(
                totalBytes: 16_000_000_000,
                availableBytes: 8_000_000_000,
                usedBytes: 8_000_000_000,
                usagePercent: 0.5
            ),
            config: nil
        )
        return wrapResponse(response, requestId: "test-stat-1")
    }

    private func storeResponseJSON() -> String {
        let response = ContextStoreResponse(
            success: true,
            key: "test-key",
            message: "Stored"
        )
        return wrapResponse(response, requestId: "test-cs-1")
    }

    private func retrieveResponseJSON() -> String {
        let response = ContextRetrieveResponse(
            success: true,
            key: "test-key",
            value: ["data": AnyCodable("test-value")],
            ttlRemaining: 300,
            createdAt: Date(),
            accessedAt: Date()
        )
        return wrapResponse(response, requestId: "test-cr-1")
    }

    private func errorResponseJSON(code: String, message: String) -> String {
        let frame = NdjsonFrame(
            type: "error",
            requestId: "test-err-1",
            timestamp: Date(),
            error: FrameError(code: code, message: message),
            payload: [:]
        )
        return (try! JSON.stringify(frame))
    }

    private func wrapResponse<T: Encodable>(_ value: T, requestId: String) -> String {
        let payloadData = try! JSONEncoder.ainos.encode(value)
        let payload = try! JSONDecoder.ainos.decode([String: AnyCodable].self, from: payloadData)
        let frame = NdjsonFrame(
            type: "response",
            requestId: requestId,
            timestamp: Date(),
            payload: payload
        )
        return (try! JSON.stringify(frame))
    }
}

// MARK: - Model Tests

/// Tests for the data models.
final class ModelTests: XCTestCase {

    func testMessageCodable() throws {
        let message = Message(role: .user, content: "Hello", metadata: ["key": "value"])
        let data = try JSONEncoder.ainos.encode(message)
        let decoded = try JSONDecoder.ainos.decode(Message.self, from: data)

        XCTAssertEqual(decoded.role, .user)
        XCTAssertEqual(decoded.content, "Hello")
        XCTAssertEqual(decoded.metadata?["key"], "value")
    }

    func testMessageRoleCases() {
        XCTAssertEqual(MessageRole.allCases.count, 4)
        XCTAssertEqual(MessageRole.system.rawValue, "system")
        XCTAssertEqual(MessageRole.user.rawValue, "user")
        XCTAssertEqual(MessageRole.assistant.rawValue, "assistant")
        XCTAssertEqual(MessageRole.tool.rawValue, "tool")
    }

    func testTokenUsage() throws {
        let usage = TokenUsage(promptTokens: 10, completionTokens: 20, totalTokens: 30, cachedTokens: 5)
        let data = try JSONEncoder.ainos.encode(usage)
        let decoded = try JSONDecoder.ainos.decode(TokenUsage.self, from: data)

        XCTAssertEqual(decoded.promptTokens, 10)
        XCTAssertEqual(decoded.completionTokens, 20)
        XCTAssertEqual(decoded.totalTokens, 30)
        XCTAssertEqual(decoded.cachedTokens, 5)
    }

    func testInferenceConfigDefaults() {
        let config = InferenceConfig()
        XCTAssertNil(config.temperature)
        XCTAssertNil(config.maxTokens)
        XCTAssertNil(config.stop)
    }

    func testInferenceConfigCustom() {
        let config = InferenceConfig(
            temperature: 0.8,
            topK: 40,
            topP: 0.95,
            maxTokens: 200,
            repeatPenalty: 1.1,
            stop: ["\n", "END"]
        )

        XCTAssertEqual(config.temperature, 0.8)
        XCTAssertEqual(config.topK, 40)
        XCTAssertEqual(config.topP, 0.95)
        XCTAssertEqual(config.maxTokens, 200)
        XCTAssertEqual(config.repeatPenalty, 1.1)
        XCTAssertEqual(config.stop, ["\n", "END"])
    }

    func testModelInfo() throws {
        let info = ModelInfo(
            id: "test-model",
            name: "Test Model",
            version: "1.0",
            format: "gguf",
            backend: "cpu",
            family: "test",
            sizeBytes: 1_000_000_000,
            isLoaded: true,
            parameterCount: "7B",
            contextLength: 2048,
            description: "A test model",
            license: "MIT",
            metadata: ["key": "value"]
        )

        let data = try JSONEncoder.ainos.encode(info)
        let decoded = try JSONDecoder.ainos.decode(ModelInfo.self, from: data)

        XCTAssertEqual(decoded.id, "test-model")
        XCTAssertEqual(decoded.format, "gguf")
        XCTAssertTrue(decoded.isLoaded)
        XCTAssertEqual(decoded.parameterCount, "7B")
        XCTAssertEqual(decoded.metadata?["key"], "value")
    }

    func testStopReasonValues() {
        XCTAssertEqual(StopReason.stop.rawValue, "stop")
        XCTAssertEqual(StopReason.length.rawValue, "length")
        XCTAssertEqual(StopReason.cancelled.rawValue, "cancelled")
        XCTAssertEqual(StopReason.contentFilter.rawValue, "content_filter")
        XCTAssertEqual(StopReason.toolCall.rawValue, "tool_call")
    }

    func testDaemonStateValues() {
        XCTAssertEqual(DaemonState.starting.rawValue, "starting")
        XCTAssertEqual(DaemonState.ready.rawValue, "ready")
        XCTAssertEqual(DaemonState.busy.rawValue, "busy")
        XCTAssertEqual(DaemonState.shuttingDown.rawValue, "shutting_down")
        XCTAssertEqual(DaemonState.error.rawValue, "error")
    }

    func testAnyCodableBool() throws {
        let value = AnyCodable(true)
        let data = try JSONEncoder.ainos.encode(value)
        let decoded = try JSONDecoder.ainos.decode(AnyCodable.self, from: data)
        XCTAssertEqual(decoded.value as? Bool, true)
    }

    func testAnyCodableString() throws {
        let value = AnyCodable("hello")
        let data = try JSONEncoder.ainos.encode(value)
        let decoded = try JSONDecoder.ainos.decode(AnyCodable.self, from: data)
        XCTAssertEqual(decoded.value as? String, "hello")
    }

    func testAnyCodableInt() throws {
        let value = AnyCodable(42)
        let data = try JSONEncoder.ainos.encode(value)
        let decoded = try JSONDecoder.ainos.decode(AnyCodable.self, from: data)
        XCTAssertEqual(decoded.value as? Int, 42)
    }

    func testAnyCodableDouble() throws {
        let value = AnyCodable(3.14)
        let data = try JSONEncoder.ainos.encode(value)
        let decoded = try JSONDecoder.ainos.decode(AnyCodable.self, from: data)
        XCTAssertEqual(decoded.value as? Double, 3.14)
    }

    func testAnyCodableNull() throws {
        let value = AnyCodable(AnyCodableNull.null)
        let data = try JSONEncoder.ainos.encode(value)
        let decoded = try JSONDecoder.ainos.decode(AnyCodable.self, from: data)
        XCTAssertTrue(decoded.value is AnyCodableNull)
    }

    func testAnyCodableArray() throws {
        let value = AnyCodable([1, "two", true] as [Any])
        let data = try JSONEncoder.ainos.encode(value)
        let decoded = try JSONDecoder.ainos.decode(AnyCodable.self, from: data)
        if let array = decoded.value as? [Any] {
            XCTAssertEqual(array.count, 3)
        } else {
            XCTFail("Expected array")
        }
    }

    func testAnyCodableDictionary() throws {
        let value = AnyCodable(["a": 1, "b": "two"] as [String: Any])
        let data = try JSONEncoder.ainos.encode(value)
        let decoded = try JSONDecoder.ainos.decode(AnyCodable.self, from: data)
        if let dict = decoded.value as? [String: Any] {
            XCTAssertEqual(dict.count, 2)
        } else {
            XCTFail("Expected dictionary")
        }
    }

    func testServerCapabilities() throws {
        let caps = ServerCapabilities(
            maxConcurrentInferences: 8,
            maxContextLength: 8192,
            supportedBackends: ["cpu", "gpu", "vulkan"],
            streamingSupported: true,
            contextStoreSupported: true,
            maxBatchSize: 4,
            supportedFormats: ["gguf", "safetensors"]
        )

        let data = try JSONEncoder.ainos.encode(caps)
        let decoded = try JSONDecoder.ainos.decode(ServerCapabilities.self, from: data)

        XCTAssertEqual(decoded.maxConcurrentInferences, 8)
        XCTAssertEqual(decoded.supportedBackends?.count, 3)
        XCTAssertTrue(decoded.streamingSupported ?? false)
    }

    func testRequestMethodWireValues() {
        XCTAssertEqual(RequestMethod.connect.wireValue, "connect")
        XCTAssertEqual(RequestMethod.infer.wireValue, "infer")
        XCTAssertEqual(RequestMethod.inferStream.wireValue, "infer_stream")
        XCTAssertEqual(RequestMethod.modelList.wireValue, "model_list")
        XCTAssertEqual(RequestMethod.modelLoad.wireValue, "model_load")
        XCTAssertEqual(RequestMethod.modelUnload.wireValue, "model_unload")
        XCTAssertEqual(RequestMethod.contextStore.wireValue, "context_store")
        XCTAssertEqual(RequestMethod.contextRetrieve.wireValue, "context_retrieve")
    }

    func testConnectRequestEncoding() throws {
        let request = ConnectRequest(
            version: "1.0",
            clientInfo: ClientInfo(
                name: "Test",
                version: "1.0",
                platform: "macOS",
                swiftVersion: "5.9"
            )
        )
        let data = try JSONEncoder.ainos.encode(request)
        let json = String(data: data, encoding: .utf8)!
        XCTAssertTrue(json.contains("1.0"))
        XCTAssertTrue(json.contains("Test"))
    }

    func testSystemMemoryEquality() {
        let mem1 = SystemMemory(totalBytes: 100, availableBytes: 50, usedBytes: 50, usagePercent: 0.5)
        let mem2 = SystemMemory(totalBytes: 100, availableBytes: 50, usedBytes: 50, usagePercent: 0.5)
        let mem3 = SystemMemory(totalBytes: 200, availableBytes: 100, usedBytes: 100, usagePercent: 0.5)

        XCTAssertEqual(mem1, mem2)
        XCTAssertNotEqual(mem1, mem3)
    }
}

// MARK: - Error Tests

/// Tests for AinosError and related types.
final class ErrorTests: XCTestCase {

    func testAinosErrorCodeEquality() {
        let code1 = AinosError.Code.connectionFailed
        let code2 = AinosError.Code(rawValue: "connection_failed")
        XCTAssertEqual(code1, code2)
    }

    func testAinosErrorCodeStringLiteral() {
        let code: AinosError.Code = "custom_error"
        XCTAssertEqual(code.rawValue, "custom_error")
    }

    func testAinosErrorEquality() {
        let error1 = AinosError(code: .connectionFailed, description: "Failed")
        let error2 = AinosError(code: .connectionFailed, description: "Failed")
        XCTAssertEqual(error1, error2)
    }

    func testAinosErrorInequality() {
        let error1 = AinosError(code: .connectionFailed, description: "Failed")
        let error2 = AinosError(code: .authenticationFailed, description: "Auth failed")
        XCTAssertNotEqual(error1, error2)
    }

    func testIsConnectionError() {
        let connectionErrors: [AinosError.Code] = [
            .connectionFailed, .connectionRefused, .connectionTimedOut,
            .connectionClosed, .connectionReset, .ioError
        ]

        for code in connectionErrors {
            let error = AinosError(code: code, description: "test")
            XCTAssertTrue(error.isConnectionError, "\(code) should be a connection error")
        }

        let authError = AinosError(code: .authenticationFailed, description: "test")
        XCTAssertFalse(authError.isConnectionError)
    }

    func testIsAuthenticationError() {
        let authErrors: [AinosError.Code] = [
            .authenticationFailed, .authenticationMissing, .tokenExpired, .tokenRefreshFailed
        ]

        for code in authErrors {
            let error = AinosError(code: code, description: "test")
            XCTAssertTrue(error.isAuthenticationError, "\(code) should be an auth error")
        }

        let connError = AinosError(code: .connectionFailed, description: "test")
        XCTAssertFalse(connError.isAuthenticationError)
    }

    func testIsRetryable() {
        let retryable: [AinosError.Code] = [
            .connectionFailed, .connectionRefused, .connectionTimedOut,
            .connectionClosed, .connectionReset, .rateLimited, .inferenceTimedOut
        ]

        for code in retryable {
            let error = AinosError(code: code, description: "test")
            XCTAssertTrue(error.isRetryable, "\(code) should be retryable")
        }

        let nonRetryable = AinosError(code: .authenticationFailed, description: "test")
        XCTAssertFalse(nonRetryable.isRetryable)
    }

    func testErrorWrapping() {
        let nsError = NSError(domain: NSURLErrorDomain, code: NSURLErrorTimedOut)
        let wrapped = nsError.asAinosError
        XCTAssertEqual(wrapped.code, .connectionTimedOut)
    }

    func testErrorWrappingPOSIX() {
        let posixError = POSIXError(.ECONNREFUSED)
        let wrapped = posixError.asAinosError
        XCTAssertTrue(wrapped.isConnectionError)
    }

    func testLocalizedErrorDescription() {
        let error = AinosError(code: .connectionRefused, description: "Connection refused by daemon")
        XCTAssertEqual(error.errorDescription, "Connection refused by daemon")
    }

    func testLocalizedErrorFailureReason() {
        let error = AinosError(code: .connectionRefused, description: "test")
        XCTAssertNotNil(error.failureReason)
    }

    func testLocalizedErrorRecoverySuggestion() {
        let error = AinosError(code: .connectionRefused, description: "test")
        XCTAssertNotNil(error.recoverySuggestion)
    }

    func testConvenienceFactoryMethods() {
        let connFailed = AinosError.connectionFailed(host: "localhost", port: 9500)
        XCTAssertEqual(connFailed.code, .connectionFailed)

        let authFailed = AinosError.authenticationFailed(reason: "Bad token")
        XCTAssertEqual(authFailed.code, .authenticationFailed)

        let invalidResp = AinosError.invalidResponse(details: "Bad JSON")
        XCTAssertEqual(invalidResp.code, .invalidResponse)

        let infFailed = AinosError.inferenceFailed(reason: "OOM")
        XCTAssertEqual(infFailed.code, .inferenceFailed)

        let modelNotFound = AinosError.modelNotFound("test-model")
        XCTAssertEqual(modelNotFound.code, .modelNotFound)
    }

    func testAinosErrorHashable() {
        let error1 = AinosError(code: .connectionFailed, description: "test")
        let error2 = AinosError(code: .connectionFailed, description: "test")
        let set: Set<AinosError> = [error1, error2]
        XCTAssertEqual(set.count, 1)
    }
}

// MARK: - Transport Tests

/// Tests for the transport layer.
final class TransportTests: XCTestCase {

    func testMockTransportConnect() async throws {
        let transport = MockTransport()
        try await transport.connect(host: "127.0.0.1", port: 9500, timeout: 10)
        XCTAssertEqual(transport.state, .connected)
    }

    func testMockTransportSendAndReceive() async throws {
        let transport = MockTransport()
        try await transport.connect(host: "127.0.0.1", port: 9500, timeout: 10)

        transport.enqueueResponse("{\"type\":\"response\"}")

        try await transport.sendLine("{\"type\":\"request\"}")
        let response = try await transport.readLine()

        XCTAssertEqual(response, "{\"type\":\"response\"}")
        XCTAssertEqual(transport.sentData.count, 1)
    }

    func testMockTransportConnectionFailure() async {
        let transport = MockTransport()
        transport.simulateConnectionFailure = true

        do {
            try await transport.connect(host: "127.0.0.1", port: 9500, timeout: 10)
            XCTFail("Expected connection failure")
        } catch {
            XCTAssertTrue(error is AinosError)
        }
    }

    func testMockTransportDisconnect() async throws {
        let transport = MockTransport()
        try await transport.connect(host: "127.0.0.1", port: 9500, timeout: 10)
        XCTAssertEqual(transport.state, .connected)

        await transport.disconnect()
        XCTAssertEqual(transport.state, .disconnected)
    }

    func testMockTransportMultipleSends() async throws {
        let transport = MockTransport()
        try await transport.connect(host: "127.0.0.1", port: 9500, timeout: 10)

        try await transport.sendLine("line1")
        try await transport.sendLine("line2")
        try await transport.sendLine("line3")

        XCTAssertEqual(transport.sentData.count, 3)
        XCTAssertEqual(transport.allSentStrings.count, 3)
    }

    func testMockTransportSendFailure() async {
        let transport = MockTransport()
        try await transport.connect(host: "127.0.0.1", port: 9500, timeout: 10)

        transport.simulateSendFailure = true

        do {
            try await transport.sendLine("test")
            XCTFail("Expected send failure")
        } catch {
            XCTAssertTrue(error is AinosError)
        }
    }

    func testMockTransportReceiveFailure() async {
        let transport = MockTransport()
        try await transport.connect(host: "127.0.0.1", port: 9500, timeout: 10)

        transport.simulateReceiveFailure = true

        do {
            _ = try await transport.readLine()
            XCTFail("Expected receive failure")
        } catch {
            XCTAssertTrue(error is AinosError)
        }
    }

    func testMockTransportReset() async throws {
        let transport = MockTransport()
        try await transport.connect(host: "127.0.0.1", port: 9500, timeout: 10)
        try await transport.sendLine("test")
        XCTAssertEqual(transport.sentData.count, 1)

        transport.reset()
        XCTAssertEqual(transport.state, .disconnected)
        XCTAssertEqual(transport.sentData.count, 0)
    }

    func testTransportStateDescription() {
        XCTAssertEqual(TransportState.disconnected.description, "disconnected")
        XCTAssertEqual(TransportState.connecting.description, "connecting")
        XCTAssertEqual(TransportState.connected.description, "connected")

        let error = AinosError(code: .connectionFailed, description: "fail")
        let state = TransportState.failed(error)
        XCTAssertTrue(state.description.contains("fail"))
    }

    func testTransportStateIsUsable() {
        XCTAssertTrue(TransportState.connected.isUsable)
        XCTAssertFalse(TransportState.disconnected.isUsable)
        XCTAssertFalse(TransportState.connecting.isUsable)
        XCTAssertFalse(TransportState.failed(.connectionFailed(host: "", port: 0)).isUsable)
    }
}

// MARK: - Authentication Tests

/// Tests for the authentication layer.
final class AuthenticationTests: XCTestCase {

    func testBearerTokenAuthenticator() async throws {
        let transport = MockTransport()
        try await transport.connect(host: "127.0.0.1", port: 9500, timeout: 10)

        // The authenticator will send a token and expect a response
        transport.enqueueResponse("{\"success\":true,\"session_id\":\"test-session\"}")

        let auth = BearerTokenAuthenticator(token: "test-token")
        try await auth.authenticate(transport: transport)

        XCTAssertTrue(auth.state.isAuthenticated)
    }

    func testBearerTokenAuthenticatorFailure() async {
        let transport = MockTransport()
        try await transport.connect(host: "127.0.0.1", port: 9500, timeout: 10)

        transport.enqueueResponse("{\"success\":false,\"message\":\"Invalid token\"}")

        let auth = BearerTokenAuthenticator(token: "bad-token")

        do {
            try await auth.authenticate(transport: transport)
            XCTFail("Expected authentication failure")
        } catch let error as AinosError {
            XCTAssertTrue(error.isAuthenticationError)
        }
    }

    func testBearerTokenAuthenticatorNoToken() async {
        let auth = BearerTokenAuthenticator(tokenProvider: { nil })

        do {
            try await auth.authenticate(transport: MockTransport())
            XCTFail("Expected authentication failure")
        } catch let error as AinosError {
            XCTAssertEqual(error.code, .authenticationMissing)
        }
    }

    func testTokenFormatValidation() {
        XCTAssertTrue(BearerTokenAuthenticator.validateTokenFormat("valid-token-123"))
        XCTAssertTrue(BearerTokenAuthenticator.validateTokenFormat("abc"))
        XCTAssertFalse(BearerTokenAuthenticator.validateTokenFormat(""))
        XCTAssertFalse(BearerTokenAuthenticator.validateTokenFormat("token with spaces"))
    }

    func testAnonymousAuthenticator() async throws {
        let auth = AnonymousAuthenticator()
        try await auth.authenticate(transport: MockTransport())

        XCTAssertTrue(auth.state.isAuthenticated)
        let headers = try await auth.authHeaders()
        XCTAssertTrue(headers.isEmpty)
    }

    func testAuthenticationStateDescription() {
        XCTAssertEqual(AuthenticationState.unauthenticated.description, "unauthenticated")
        XCTAssertEqual(AuthenticationState.authenticating.description, "authenticating")
        XCTAssertEqual(AuthenticationState.authenticated.description, "authenticated")

        let error = AinosError.authenticationFailed()
        let state = AuthenticationState.failed(error)
        XCTAssertTrue(state.description.contains("failed"))
    }

    func testAuthenticationStateIsAuthenticated() {
        XCTAssertTrue(AuthenticationState.authenticated.isAuthenticated)
        XCTAssertFalse(AuthenticationState.unauthenticated.isAuthenticated)
        XCTAssertFalse(AuthenticationState.authenticating.isAuthenticated)
        XCTAssertFalse(AuthenticationState.failed(.authenticationFailed()).isAuthenticated)
    }

    func testInMemoryTokenStore() throws {
        let store = InMemoryTokenStore()
        try store.store(token: "my-token", for: "api-key")
        XCTAssertTrue(store.hasToken(for: "api-key"))

        let retrieved = try store.retrieveToken(for: "api-key")
        XCTAssertEqual(retrieved, "my-token")

        try store.deleteToken(for: "api-key")
        XCTAssertFalse(store.hasToken(for: "api-key"))
    }

    func testAuthenticationChain() async throws {
        let transport = MockTransport()
        try await transport.connect(host: "127.0.0.1", port: 9500, timeout: 10)

        transport.enqueueResponse("{\"success\":true,\"session_id\":\"test\"}")

        let chain = AuthenticationChain(providers: [
            BearerTokenAuthenticator(token: "token1"),
            BearerTokenAuthenticator(token: "token2")
        ])

        try await chain.authenticate(transport: transport)
        XCTAssertTrue(chain.state.isAuthenticated)
    }

    func testAuthenticationChainAllFail() async {
        let transport = MockTransport()
        try await transport.connect(host: "127.0.0.1", port: 9500, timeout: 10)

        transport.enqueueResponse("{\"success\":false}")
        transport.enqueueResponse("{\"success\":false}")

        let chain = AuthenticationChain(providers: [
            BearerTokenAuthenticator(token: "bad1"),
            BearerTokenAuthenticator(token: "bad2")
        ])

        do {
            try await chain.authenticate(transport: transport)
            XCTFail("Expected all providers to fail")
        } catch {
            XCTAssertTrue(error is AinosError)
        }
    }
}

// MARK: - Streaming Tests

/// Tests for the streaming layer.
final class StreamingTests: XCTestCase {

    func testStreamStateTransitions() {
        let stream = InferenceStream(
            transport: MockTransport(),
            requestId: "test"
        )

        XCTAssertEqual(stream.state, .idle)
        XCTAssertTrue(stream.state.isActive)
        XCTAssertFalse(stream.state.isTerminal)
    }

    func testStreamStateCompleted() {
        let result = StreamResult(fullText: "Hello", tokenCount: 5)
        let state = StreamState.completed(result)

        XCTAssertFalse(state.isActive)
        XCTAssertTrue(state.isTerminal)
    }

    func testStreamStateFailed() {
        let state = StreamState.failed(.inferenceFailed(reason: "test"))
        XCTAssertFalse(state.isActive)
        XCTAssertTrue(state.isTerminal)
    }

    func testStreamStateCancelled() {
        let state = StreamState.cancelled
        XCTAssertFalse(state.isActive)
        XCTAssertTrue(state.isTerminal)
    }

    func testStreamResult() {
        let usage = TokenUsage(promptTokens: 5, completionTokens: 10, totalTokens: 15)
        let result = StreamResult(
            fullText: "Hello world",
            tokenCount: 3,
            usage: usage,
            stopReason: .stop,
            timings: InferenceTimings(
                promptProcessingMs: 10, tokenGenerationMs: 30,
                totalMs: 40, tokensPerSecond: 75.0
            )
        )

        XCTAssertEqual(result.fullText, "Hello world")
        XCTAssertEqual(result.tokenCount, 3)
        XCTAssertEqual(result.usage?.totalTokens, 15)
        XCTAssertEqual(result.stopReason, .stop)
    }

    func testStreamCollector() async throws {
        let transport = MockTransport()
        try await transport.connect(host: "127.0.0.1", port: 9500, timeout: 10)

        // Enqueue events
        transport.enqueueResponse(streamEventJSON(text: "Hello", index: 0))
        transport.enqueueResponse(streamEventJSON(text: " ", index: 1))
        transport.enqueueResponse(streamEventJSON(text: "world", index: 2))
        transport.enqueueResponse(streamDoneJSON())

        let stream = InferenceStream(transport: transport, requestId: "test")
        let collector = StreamCollector()
        let result = try await collector.collect(stream)

        XCTAssertEqual(result.fullText, "Hello world")
        XCTAssertEqual(result.tokenCount, 3)
        XCTAssertNotNil(result.usage)
        XCTAssertEqual(result.stopReason, .stop)
    }

    func testStreamCollectorText() async throws {
        let transport = MockTransport()
        try await transport.connect(host: "127.0.0.1", port: 9500, timeout: 10)

        transport.enqueueResponse(streamEventJSON(text: "Hi", index: 0))
        transport.enqueueResponse(streamDoneJSON())

        let stream = InferenceStream(transport: transport, requestId: "test")
        let collector = StreamCollector()
        let text = try await collector.collectText(stream)

        XCTAssertEqual(text, "Hi")
    }

    func testStreamEventSerialization() throws {
        let event = StreamEvent(type: .token, delta: "Hello", index: 0)

        let json = try event.serialize()
        let decoded = try StreamEvent.deserialize(from: json)

        XCTAssertEqual(decoded.type, .token)
        XCTAssertEqual(decoded.delta, "Hello")
        XCTAssertEqual(decoded.index, 0)
    }

    func testStreamEventDeserializeError() {
        XCTAssertThrowsError(try StreamEvent.deserialize(from: "invalid json"))
    }

    func testStreamMonitor() async throws {
        let transport = MockTransport()
        try await transport.connect(host: "127.0.0.1", port: 9500, timeout: 10)

        transport.enqueueResponse(streamEventJSON(text: "Hello", index: 0))
        transport.enqueueResponse(streamEventJSON(text: " ", index: 1))
        transport.enqueueResponse(streamEventJSON(text: "world", index: 2))
        transport.enqueueResponse(streamDoneJSON())

        let stream = InferenceStream(transport: transport, requestId: "test")
        let monitor = StreamMonitor()
        let monitored = monitor.attach(to: stream)

        let _ = try await StreamCollector().collect(monitored)

        // Allow a brief moment for metrics finalization
        let metrics = monitor.metrics
        XCTAssertNotNil(metrics)
        XCTAssertEqual(metrics?.totalEvents, 4)
        XCTAssertEqual(metrics?.tokenEvents, 3)
    }

    // MARK: - Helpers

    private func streamEventJSON(text: String, index: Int) -> String {
        let event = StreamEvent(type: .token, delta: text, index: index)
        let data = try! JSONEncoder.ainos.encode(event)
        return String(data: data, encoding: .utf8)!
    }

    private func streamDoneJSON() -> String {
        let event = StreamEvent(
            type: .done,
            delta: nil,
            index: nil,
            stopReason: .stop,
            usage: TokenUsage(promptTokens: 5, completionTokens: 3, totalTokens: 8),
            timings: nil
        )
        let data = try! JSONEncoder.ainos.encode(event)
        return String(data: data, encoding: .utf8)!
    }
}

// MARK: - Utilities Tests

/// Tests for the utility functions.
final class UtilitiesTests: XCTestCase {

    func testJSONStringify() throws {
        let message = Message(role: .user, content: "Hello")
        let string = try JSON.stringify(message)
        XCTAssertTrue(string.contains("user"))
        XCTAssertTrue(string.contains("Hello"))
    }

    func testJSONPrettyPrint() throws {
        let message = Message(role: .user, content: "Hello")
        let string = try JSON.prettyPrint(message)
        XCTAssertTrue(string.contains("\n"))
    }

    func testJSONParse() throws {
        let json = "{\"role\":\"user\",\"content\":\"Hello\"}"
        let message: Message = try JSON.parse(json, as: Message.self)
        XCTAssertEqual(message.role, .user)
        XCTAssertEqual(message.content, "Hello")
    }

    func testJSONIsValid() {
        XCTAssertTrue(JSON.isValidJSON("{\"key\":\"value\"}"))
        XCTAssertTrue(JSON.isValidJSON("[]"))
        XCTAssertTrue(JSON.isValidJSON("123"))
        XCTAssertFalse(JSON.isValidJSON("{invalid}"))
        XCTAssertFalse(JSON.isValidJSON(""))
    }

    func testJSONExtractValue() {
        let json = "{\"model\":{\"id\":\"test\",\"name\":\"Test Model\"}}"
        let id = JSON.extractValue(from: json, keyPath: "model.id") as? String
        XCTAssertEqual(id, "test")
    }

    func testDataHexString() {
        let data = Data([0x48, 0x65, 0x6C, 0x6C, 0x6F])
        XCTAssertEqual(data.hexString, "48656c6c6f")
    }

    func testDataWithNewline() {
        let data = Data("Hello".utf8).withNewline()
        XCTAssertEqual(data.count, 6)
        XCTAssertEqual(data.last, 0x0A)
    }

    func testStringIsValidJSON() {
        XCTAssertTrue("{\"key\":1}".isValidJSON)
        XCTAssertFalse("not json".isValidJSON)
    }

    func testStringDecodeJSON() throws {
        let json = "{\"role\":\"user\",\"content\":\"Hello\"}"
        let message = try json.decodeJSON(as: Message.self)
        XCTAssertEqual(message.content, "Hello")
    }

    func testStringTruncated() {
        XCTAssertEqual("Hello".truncated(to: 10), "Hello")
        XCTAssertEqual("Hello World".truncated(to: 5), "Hello...")
    }

    func testVersionParsing() {
        let v1 = Version("1.2.3")
        XCTAssertNotNil(v1)
        XCTAssertEqual(v1?.major, 1)
        XCTAssertEqual(v1?.minor, 2)
        XCTAssertEqual(v1?.patch, 3)

        let v2 = Version("2.0.0-beta")
        XCTAssertNotNil(v2)
        XCTAssertEqual(v2?.major, 2)
        XCTAssertEqual(v2?.preRelease, "beta")
    }

    func testVersionComparison() {
        let v1 = Version("1.0.0")!
        let v2 = Version("2.0.0")!
        let v3 = Version("1.5.0")!

        XCTAssertLessThan(v1, v2)
        XCTAssertLessThan(v1, v3)
        XCTAssertGreaterThan(v2, v3)
    }

    func testVersionPreRelease() {
        let release = Version("1.0.0")!
        let beta = Version("1.0.0-beta")!
        let alpha = Version("1.0.0-alpha")!

        XCTAssertLessThan(beta, release)
        XCTAssertLessThan(alpha, release)
        XCTAssertGreaterThan(release, beta)
    }

    func testStopwatch() {
        let watch = Stopwatch()
        let elapsed = watch.elapsed
        XCTAssertGreaterThanOrEqual(elapsed, 0)
    }

    func testAinosClientConfigEquality() {
        let config1 = AinosClientConfig(host: "localhost", port: 9500, token: "abc")
        let config2 = AinosClientConfig(host: "localhost", port: 9500, token: "abc")
        let config3 = AinosClientConfig(host: "other", port: 9500, token: "abc")

        XCTAssertEqual(config1, config2)
        XCTAssertNotEqual(config1, config3)
    }

    func testConnectionStateEquality() {
        XCTAssertEqual(ConnectionState.disconnected, ConnectionState.disconnected)
        XCTAssertEqual(ConnectionState.connected, ConnectionState.connected)
        XCTAssertNotEqual(ConnectionState.disconnected, ConnectionState.connected)
    }

    func testConnectionStateIsConnected() {
        XCTAssertTrue(ConnectionState.connected.isConnected)
        XCTAssertFalse(ConnectionState.disconnected.isConnected)
        XCTAssertFalse(ConnectionState.connecting.isConnected)
    }

    func testAsyncThrottle() async throws {
        let throttle = AsyncThrottle(interval: 0.05)
        let start = Date()

        await throttle.throttle() // First call should not wait
        await throttle.throttle() // Second call should wait

        let elapsed = Date().timeIntervalSince(start)
        XCTAssertGreaterThanOrEqual(elapsed, 0.04)
    }
}

// MARK: - Performance Tests

/// Performance tests for the SDK.
final class PerformanceTests: XCTestCase {

    func testJSONSerializationPerformance() {
        let models = TestData.modelList()

        measure {
            for _ in 0..<100 {
                _ = try! JSON.stringify(models)
            }
        }
    }

    func testAnyCodablePerformance() {
        let dict: [String: Any] = [
            "string": "hello",
            "int": 42,
            "double": 3.14,
            "bool": true,
            "array": [1, 2, 3],
            "nested": ["key": "value"]
        ]

        measure {
            for _ in 0..<100 {
                let anyCodable = AnyCodable(dict)
                _ = try! JSON.stringify(anyCodable)
            }
        }
    }
}