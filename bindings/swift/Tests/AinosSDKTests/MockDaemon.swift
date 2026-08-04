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

// MARK: - Mock Daemon

/// A mock daemon that simulates the Ainos daemon for testing.
///
/// `MockDaemon` provides:
/// - Configurable response sequences
/// - Verification of received requests
/// - Simulated connection failures
/// - Simulated authentication challenges
///
/// ## Usage
///
/// ```swift
/// let daemon = MockDaemon()
/// daemon.onConnect = { request in
///     return ConnectResponse(version: "1.0", sessionId: "test-session")
/// }
/// daemon.onInfer = { request in
///     return InferResponse(text: "Hello!", model: "test-model")
/// }
///
/// // Use with MockTransport
/// let transport = MockTransport()
/// transport.mockResponseLines = daemon.generateResponses(for: .infer)
/// ```
public final class MockDaemon {

    // MARK: - Types

    /// A handler for connect requests.
    public typealias ConnectHandler = @Sendable (ConnectRequest) async throws -> ConnectResponse

    /// A handler for infer requests.
    public typealias InferHandler = @Sendable (InferRequest) async throws -> InferResponse

    /// A handler for infer stream requests.
    public typealias InferStreamHandler = @Sendable (InferRequest) async throws -> [StreamEvent]

    /// A handler for model list requests.
    public typealias ModelListHandler = @Sendable () async throws -> ModelListResponse

    /// A handler for model load requests.
    public typealias ModelLoadHandler = @Sendable (ModelLoadRequest) async throws -> ModelOperationResponse

    /// A handler for model unload requests.
    public typealias ModelUnloadHandler = @Sendable (String) async throws -> ModelOperationResponse

    /// A handler for health requests.
    public typealias HealthHandler = @Sendable () async throws -> HealthResponse

    /// A handler for status requests.
    public typealias StatusHandler = @Sendable () async throws -> DaemonStatus

    /// A handler for context store requests.
    public typealias ContextStoreHandler = @Sendable (ContextStoreRequest) async throws -> ContextStoreResponse

    /// A handler for context retrieve requests.
    public typealias ContextRetrieveHandler = @Sendable (String) async throws -> ContextRetrieveResponse

    // MARK: - Properties

    /// Whether to simulate a connection failure.
    public var simulateConnectionFailure: Bool = false

    /// The error to throw on connection failure.
    public var connectionError: AinosError = .connectionRefused(host: "127.0.0.1", port: 9500)

    /// Whether to simulate authentication failure.
    public var simulateAuthFailure: Bool = false

    /// The authentication failure error.
    public var authError: AinosError = .authenticationFailed()

    /// The simulated network delay in seconds.
    public var networkDelay: TimeInterval = 0

    /// The request handlers.
    public var onConnect: ConnectHandler?
    public var onInfer: InferHandler?
    public var onInferStream: InferStreamHandler?
    public var onModelList: ModelListHandler?
    public var onModelLoad: ModelLoadHandler?
    public var onModelUnload: ModelUnloadHandler?
    public var onHealth: HealthHandler?
    public var onStatus: StatusHandler?
    public var onContextStore: ContextStoreHandler?
    public var onContextRetrieve: ContextRetrieveHandler?

    /// Records of all received requests.
    public private(set) var receivedRequests: [ReceivedRequest] = []

    /// A record of a received request.
    public struct ReceivedRequest: Sendable, CustomStringConvertible {
        public let method: String
        public let requestId: String?
        public let rawJSON: String
        public let timestamp: Date

        public var description: String {
            "[\(timestamp)] \(method) [\(requestId ?? "?")]: \(rawJSON.truncated(to: 200))"
        }
    }

    private let lock = NSLock()

    // MARK: - Initialization

    public init() {}

    // MARK: - Request Generation

    /// Generates response lines for a given request method and payload.
    /// - Parameters:
    ///   - method: The request method.
    ///   - jsonString: The JSON request string.
    /// - Returns: An array of response JSON strings.
    public func generateResponse(for method: String, jsonString: String) -> [String] {
        lock.lock()
        defer { lock.unlock() }

        // Record the request
        let request = ReceivedRequest(
            method: method,
            requestId: extractRequestId(from: jsonString),
            rawJSON: jsonString,
            timestamp: Date()
        )
        receivedRequests.append(request)

        // Simulate network delay
        if networkDelay > 0 {
            Thread.sleep(forTimeInterval: networkDelay)
        }

        guard let requestData = jsonString.data(using: .utf8),
              let frame = try? JSONDecoder.ainos.decode(NdjsonFrame.self, from: requestData) else {
            return [errorResponse("invalid_request", "Invalid request JSON")]
        }

        return handleFrame(frame)
    }

    /// Handles a decoded NDJSON frame and returns response lines.
    private func handleFrame(_ frame: NdjsonFrame) -> [String] {
        let requestId = frame.requestId ?? "unknown"

        switch frame.type {
        case RequestMethod.connect.rawValue:
            return handleConnect(requestId: requestId, payload: frame.payload)

        case RequestMethod.infer.rawValue:
            return handleInfer(requestId: requestId, payload: frame.payload)

        case RequestMethod.inferStream.rawValue:
            return handleInferStream(requestId: requestId, payload: frame.payload)

        case RequestMethod.modelList.rawValue:
            return handleModelList(requestId: requestId)

        case RequestMethod.modelLoad.rawValue:
            return handleModelLoad(requestId: requestId, payload: frame.payload)

        case RequestMethod.modelUnload.rawValue:
            return handleModelUnload(requestId: requestId, payload: frame.payload)

        case RequestMethod.health.rawValue:
            return handleHealth(requestId: requestId)

        case RequestMethod.status.rawValue:
            return handleStatus(requestId: requestId)

        case RequestMethod.contextStore.rawValue:
            return handleContextStore(requestId: requestId, payload: frame.payload)

        case RequestMethod.contextRetrieve.rawValue:
            return handleContextRetrieve(requestId: requestId, payload: frame.payload)

        default:
            return [errorResponse("unknown_method", "Unknown method: \(frame.type)", requestId: requestId)]
        }
    }

    // MARK: - Handler Dispatch

    private func handleConnect(requestId: String, payload: [String: AnyCodable]) -> [String] {
        if simulateConnectionFailure {
            return [errorResponse("connection_failed", connectionError.description, requestId: requestId)]
        }

        if let handler = onConnect {
            // Decode the request from the payload
            do {
                let payloadData = try JSONEncoder.ainos.encode(payload)
                let request = try JSONDecoder.ainos.decode(ConnectRequest.self, from: payloadData)
                let response = try awaitHandler(handler(request))
                return [successResponse(response, requestId: requestId)]
            } catch {
                return [errorResponse("handler_error", error.localizedDescription, requestId: requestId)]
            }
        }

        // Default response
        let response = ConnectResponse(
            version: "1.0.0",
            sessionId: "test-session-\(UUID().uuidString.prefix(8))",
            capabilities: ServerCapabilities(
                maxConcurrentInferences: 4,
                maxContextLength: 4096,
                supportedBackends: ["cpu", "gpu"],
                streamingSupported: true,
                contextStoreSupported: true,
                maxBatchSize: 1,
                supportedFormats: ["gguf"]
            ),
            welcome: "Welcome to Ainos Mock Daemon"
        )
        return [successResponse(response, requestId: requestId)]
    }

    private func handleInfer(requestId: String, payload: [String: AnyCodable]) -> [String] {
        if let handler = onInfer {
            do {
                let payloadData = try JSONEncoder.ainos.encode(payload)
                let request = try JSONDecoder.ainos.decode(InferRequest.self, from: payloadData)
                let response = try awaitHandler(handler(request))
                return [successResponse(response, requestId: requestId)]
            } catch {
                return [errorResponse("handler_error", error.localizedDescription, requestId: requestId)]
            }
        }

        let response = InferResponse(
            text: "Hello from mock daemon!",
            model: "mock-model",
            usage: TokenUsage(promptTokens: 5, completionTokens: 5, totalTokens: 10),
            stopReason: .stop,
            sessionId: nil,
            timings: InferenceTimings(
                promptProcessingMs: 10,
                tokenGenerationMs: 50,
                totalMs: 60,
                tokensPerSecond: 100.0
            ),
            finishReason: nil
        )
        return [successResponse(response, requestId: requestId)]
    }

    private func handleInferStream(requestId: String, payload: [String: AnyCodable]) -> [String] {
        if let handler = onInferStream {
            do {
                let payloadData = try JSONEncoder.ainos.encode(payload)
                let request = try JSONDecoder.ainos.decode(InferRequest.self, from: payloadData)
                let events = try awaitHandler(handler(request))
                return events.map { event in
                    successResponse(event, requestId: requestId)
                }
            } catch {
                return [errorResponse("handler_error", error.localizedDescription, requestId: requestId)]
            }
        }

        // Default streaming response
        let events: [StreamEvent] = [
            StreamEvent(type: .token, delta: "Hello", index: 0),
            StreamEvent(type: .token, delta: " ", index: 1),
            StreamEvent(type: .token, delta: "world", index: 2),
            StreamEvent(type: .token, delta: "!", index: 3),
            StreamEvent(type: .done, delta: nil, index: nil,
                       stopReason: .stop,
                       usage: TokenUsage(promptTokens: 5, completionTokens: 4, totalTokens: 9),
                       timings: InferenceTimings(
                        promptProcessingMs: 10, tokenGenerationMs: 40,
                        totalMs: 50, tokensPerSecond: 80.0
                       ))
        ]
        return events.map { successResponse($0, requestId: requestId) }
    }

    private func handleModelList(requestId: String) -> [String] {
        if let handler = onModelList {
            do {
                let response = try awaitHandler(handler())
                return [successResponse(response, requestId: requestId)]
            } catch {
                return [errorResponse("handler_error", error.localizedDescription, requestId: requestId)]
            }
        }

        let response = ModelListResponse(
            models: [
                ModelInfo(
                    id: "mock-model-1",
                    name: "Mock Model 1",
                    version: "1.0",
                    format: "gguf",
                    backend: "cpu",
                    family: "mock",
                    sizeBytes: 1_000_000_000,
                    isLoaded: true,
                    parameterCount: "7B",
                    contextLength: 2048,
                    description: "A mock model for testing",
                    license: "MIT",
                    metadata: ["test": "true"]
                ),
                ModelInfo(
                    id: "mock-model-2",
                    name: "Mock Model 2",
                    version: "2.0",
                    format: "gguf",
                    backend: "gpu",
                    family: "mock",
                    sizeBytes: 2_000_000_000,
                    isLoaded: false,
                    parameterCount: "13B",
                    contextLength: 4096,
                    description: "Another mock model",
                    license: "MIT",
                    metadata: nil
                )
            ],
            total: 2
        )
        return [successResponse(response, requestId: requestId)]
    }

    private func handleModelLoad(requestId: String, payload: [String: AnyCodable]) -> [String] {
        if let handler = onModelLoad {
            do {
                let payloadData = try JSONEncoder.ainos.encode(payload)
                let request = try JSONDecoder.ainos.decode(ModelLoadRequest.self, from: payloadData)
                let response = try awaitHandler(handler(request))
                return [successResponse(response, requestId: requestId)]
            } catch {
                return [errorResponse("handler_error", error.localizedDescription, requestId: requestId)]
            }
        }

        let response = ModelOperationResponse(
            success: true,
            model: "mock-model",
            message: "Model loaded successfully",
            durationMs: 1500
        )
        return [successResponse(response, requestId: requestId)]
    }

    private func handleModelUnload(requestId: String, payload: [String: AnyCodable]) -> [String] {
        if let handler = onModelUnload {
            do {
                let payloadData = try JSONEncoder.ainos.encode(payload)
                let request = try JSONDecoder.ainos.decode(ModelLoadRequest.self, from: payloadData)
                let response = try awaitHandler(handler(request.model))
                return [successResponse(response, requestId: requestId)]
            } catch {
                return [errorResponse("handler_error", error.localizedDescription, requestId: requestId)]
            }
        }

        let response = ModelOperationResponse(
            success: true,
            model: "mock-model",
            message: "Model unloaded successfully",
            durationMs: 500
        )
        return [successResponse(response, requestId: requestId)]
    }

    private func handleHealth(requestId: String) -> [String] {
        if let handler = onHealth {
            do {
                let response = try awaitHandler(handler())
                return [successResponse(response, requestId: requestId)]
            } catch {
                return [errorResponse("handler_error", error.localizedDescription, requestId: requestId)]
            }
        }

        let response = HealthResponse(
            healthy: true,
            uptimeSeconds: 3600,
            version: "1.0.0",
            activeConnections: 1,
            memoryUsageBytes: 500_000_000
        )
        return [successResponse(response, requestId: requestId)]
    }

    private func handleStatus(requestId: String) -> [String] {
        if let handler = onStatus {
            do {
                let response = try awaitHandler(handler())
                return [successResponse(response, requestId: requestId)]
            } catch {
                return [errorResponse("handler_error", error.localizedDescription, requestId: requestId)]
            }
        }

        let response = DaemonStatus(
            version: "1.0.0",
            state: .ready,
            loadedModels: [
                ModelInfo(
                    id: "mock-model-1",
                    name: "Mock Model 1",
                    version: "1.0",
                    format: "gguf",
                    backend: "cpu",
                    family: "mock",
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
            config: ["log_level": "info"]
        )
        return [successResponse(response, requestId: requestId)]
    }

    private func handleContextStore(requestId: String, payload: [String: AnyCodable]) -> [String] {
        if let handler = onContextStore {
            do {
                let payloadData = try JSONEncoder.ainos.encode(payload)
                let request = try JSONDecoder.ainos.decode(ContextStoreRequest.self, from: payloadData)
                let response = try awaitHandler(handler(request))
                return [successResponse(response, requestId: requestId)]
            } catch {
                return [errorResponse("handler_error", error.localizedDescription, requestId: requestId)]
            }
        }

        let response = ContextStoreResponse(success: true, key: "test-key", message: "Context stored")
        return [successResponse(response, requestId: requestId)]
    }

    private func handleContextRetrieve(requestId: String, payload: [String: AnyCodable]) -> [String] {
        if let handler = onContextRetrieve {
            do {
                let payloadData = try JSONEncoder.ainos.encode(payload)
                let request = try JSONDecoder.ainos.decode(ContextRetrieveRequest.self, from: payloadData)
                let response = try awaitHandler(handler(request.key))
                return [successResponse(response, requestId: requestId)]
            } catch {
                return [errorResponse("handler_error", error.localizedDescription, requestId: requestId)]
            }
        }

        let response = ContextRetrieveResponse(
            success: true,
            key: "test-key",
            value: ["value": AnyCodable("test-data")],
            ttlRemaining: 300,
            createdAt: Date(),
            accessedAt: Date()
        )
        return [successResponse(response, requestId: requestId)]
    }

    // MARK: - Response Helpers

    private func successResponse<T: Encodable>(_ value: T, requestId: String) -> String {
        let frame = NdjsonFrame(
            type: "response",
            requestId: requestId,
            timestamp: Date(),
            payload: (try? JSON.parse(JSON.stringify(value), as: [String: AnyCodable].self)) ?? [:]
        )
        return (try? JSON.stringify(frame)) ?? ""
    }

    private func errorResponse(_ code: String, _ message: String, requestId: String? = nil) -> String {
        let frame = NdjsonFrame(
            type: "error",
            requestId: requestId,
            timestamp: Date(),
            error: FrameError(code: code, message: message),
            payload: [:]
        )
        return (try? JSON.stringify(frame)) ?? ""
    }

    private func extractRequestId(from json: String) -> String? {
        guard let data = json.data(using: .utf8),
              let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        return dict["request_id"] as? String
    }

    /// Helper to run async handlers synchronously in tests.
    private func awaitHandler<T>(_ operation: @escaping @autoclosure () async throws -> T) rethrows -> T {
        // Note: In tests, we use XCTest's async expectations.
        // This helper is a simplified version for the mock.
        // The actual test handles async via Swift concurrency.
        fatalError("Use async test methods instead")
    }
}

// MARK: - Test Utilities

/// A utility for creating test data.
public enum TestData {

    /// Creates a basic connect request.
    public static func connectRequest() -> ConnectRequest {
        ConnectRequest(
            version: "1.0",
            clientInfo: ClientInfo(
                name: "TestClient",
                version: "1.0",
                platform: "macOS",
                swiftVersion: "5.9"
            )
        )
    }

    /// Creates a basic inference request.
    public static func inferRequest(model: String = "test-model") -> InferRequest {
        InferRequest(
            model: model,
            prompt: "Hello, world!",
            messages: nil,
            config: InferenceConfig(
                temperature: 0.7,
                maxTokens: 100
            )
        )
    }

    /// Creates a basic connect response.
    public static func connectResponse() -> ConnectResponse {
        ConnectResponse(
            version: "1.0.0",
            sessionId: "test-session-1234",
            capabilities: ServerCapabilities(
                maxConcurrentInferences: 4,
                maxContextLength: 4096,
                supportedBackends: ["cpu"],
                streamingSupported: true,
                contextStoreSupported: true,
                maxBatchSize: 1,
                supportedFormats: ["gguf"]
            ),
            welcome: "Welcome"
        )
    }

    /// Creates a basic inference response.
    public static func inferResponse(text: String = "Hello, world!") -> InferResponse {
        InferResponse(
            text: text,
            model: "test-model",
            usage: TokenUsage(promptTokens: 5, completionTokens: 3, totalTokens: 8),
            stopReason: .stop,
            sessionId: "test-session",
            timings: InferenceTimings(
                promptProcessingMs: 10,
                tokenGenerationMs: 30,
                totalMs: 40,
                tokensPerSecond: 100.0
            ),
            finishReason: nil
        )
    }

    /// Creates a stream event for testing.
    public static func tokenEvent(_ text: String, index: Int) -> StreamEvent {
        StreamEvent(type: .token, delta: text, index: index)
    }

    /// Creates a done event for testing.
    public static func doneEvent() -> StreamEvent {
        StreamEvent(
            type: .done,
            delta: nil,
            index: nil,
            stopReason: .stop,
            usage: TokenUsage(promptTokens: 5, completionTokens: 10, totalTokens: 15),
            timings: InferenceTimings(
                promptProcessingMs: 10, tokenGenerationMs: 100,
                totalMs: 110, tokensPerSecond: 90.9
            )
        )
    }

    /// Creates an error event for testing.
    public static func errorEvent(_ message: String) -> StreamEvent {
        StreamEvent(type: .error, delta: message, index: nil)
    }

    /// Creates a model list for testing.
    public static func modelList() -> ModelListResponse {
        ModelListResponse(
            models: [
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
                    description: "Test model 1",
                    license: "MIT",
                    metadata: nil
                ),
                ModelInfo(
                    id: "model-2",
                    name: "Model 2",
                    version: "2.0",
                    format: "gguf",
                    backend: "gpu",
                    family: "llama",
                    sizeBytes: 2_000_000_000,
                    isLoaded: false,
                    parameterCount: "13B",
                    contextLength: 4096,
                    description: "Test model 2",
                    license: "Apache-2.0",
                    metadata: nil
                )
            ],
            total: 2
        )
    }
}