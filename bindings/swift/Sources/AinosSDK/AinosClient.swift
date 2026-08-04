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

// MARK: - AinosClient

/// The main client for communicating with the Ainos daemon.
///
/// `AinosClient` provides a Swift-concurrency-native interface for all
/// Ainos daemon operations, including model inference (both streaming
/// and non-streaming), model management, health checks, and context
/// storage.
///
/// ## Overview
///
/// The client communicates with the daemon over TCP using NDJSON
/// (Newline-Delimited JSON). Each request is sent as a single JSON
/// line, and the response is received as one or more JSON lines.
///
/// ## Usage
///
/// ```swift
/// let client = AinosClient(config: AinosClientConfig(
///     host: "127.0.0.1",
///     port: 9500,
///     token: "your-token"
/// ))
///
/// try await client.connect()
///
/// // Non-streaming inference
/// let response = try await client.infer(
///     model: "gpt-3.5-turbo",
///     prompt: "Hello, world!"
/// )
/// print(response.text)
///
/// // Streaming inference
/// let stream = try await client.inferStream(
///     model: "gpt-3.5-turbo",
///     prompt: "Write a story"
/// )
/// for try await event in stream {
///     print(event.delta ?? "", terminator: "")
/// }
///
/// // Model management
/// let models = try await client.modelList()
/// for model in models.models {
///     print("\(model.id) — \(model.isLoaded ? "loaded" : "unloaded")")
/// }
///
/// // Clean up
/// try await client.disconnect()
/// ```
///
/// ## Thread Safety
///
/// `AinosClient` is safe to use from multiple concurrent tasks. Internal
/// state is protected by a combination of locks and Swift structured
/// concurrency.
///
/// ## Error Handling
///
/// All methods throw `AinosError` on failure. See `AinosError.Code` for
/// the full list of possible error codes.
public final class AinosClient: Sendable {

    // MARK: - Public Properties

    /// The client configuration.
    public let config: AinosClientConfig

    /// The current connection state.
    public private(set) var connectionState: ConnectionState = .disconnected

    /// A stream of connection state changes.
    public let stateStream: AsyncStream<ConnectionState>

    /// The daemon's capabilities, populated after a successful connection.
    public private(set) var capabilities: ServerCapabilities?

    /// The daemon version, populated after a successful connection.
    public private(set) var daemonVersion: String?

    /// The session identifier, populated after a successful connection.
    public private(set) var sessionId: String?

    /// The SDK version.
    public static let sdkVersion = "1.0.0"

    // MARK: - Private Properties

    private let transport: TransportProtocol
    private let authentication: AuthenticationProtocol
    private let requestIDGenerator: RequestIDGenerator
    private let lock = NSLock()
    private var stateContinuation: AsyncStream<ConnectionState>.Continuation?
    private var activeRequestId: String?
    private var metrics: SDKMetrics

    // MARK: - Initialization

    /// Creates a new Ainos client with the default configuration.
    /// - Parameters:
    ///   - config: The client configuration.
    ///   - transport: An optional custom transport. Defaults to `TCPTransport`.
    ///   - authentication: An optional custom authenticator. Defaults to
    ///     `BearerTokenAuthenticator` if a token is configured, or
    ///     `AnonymousAuthenticator` otherwise.
    public init(
        config: AinosClientConfig = AinosClientConfig(),
        transport: TransportProtocol? = nil,
        authentication: AuthenticationProtocol? = nil
    ) {
        self.config = config

        // Create the transport
        if let transport = transport {
            self.transport = transport
        } else {
            self.transport = TCPTransport()
        }

        // Create the authenticator
        if let authentication = authentication {
            self.authentication = authentication
        } else if let token = config.token {
            self.authentication = BearerTokenAuthenticator(token: token)
        } else {
            self.authentication = AnonymousAuthenticator()
        }

        self.requestIDGenerator = config.requestIDGenerator
        self.metrics = SDKMetrics(
            bytesSent: 0, bytesReceived: 0,
            requestsSent: 0, responsesReceived: 0,
            errors: 0, reconnections: 0,
            averageRttMs: nil
        )

        var continuation: AsyncStream<ConnectionState>.Continuation?
        self.stateStream = AsyncStream { continuation = $0 }
        self.stateContinuation = continuation
    }

    deinit {
        stateContinuation?.finish()
    }

    // MARK: - Connection Management

    /// Connects to the Ainos daemon.
    ///
    /// This method:
    /// 1. Establishes a TCP connection to the daemon
    /// 2. Performs authentication (if configured)
    /// 3. Sends a connect request to establish a session
    /// 4. Reads the daemon's capabilities
    ///
    /// - Throws: `AinosError` if connection or authentication fails.
    public func connect() async throws {
        Logger.info("Connecting to Ainos daemon at \(config.host):\(config.port)")

        updateState(.connecting)

        do {
            // Step 1: Establish TCP connection
            try await transport.connect(
                host: config.host,
                port: config.port,
                timeout: config.connectionTimeout
            )

            // Step 2: Authenticate
            try await authentication.authenticate(transport: transport)

            // Step 3: Send connect request
            let connectRequest = ConnectRequest(
                version: "1.0",
                clientInfo: ClientInfo(
                    name: "AinosSDK",
                    version: Self.sdkVersion,
                    platform: await Self.detectPlatform(),
                    swiftVersion: await Self.detectSwiftVersion()
                )
            )

            let response = try await sendRequest(
                method: .connect,
                payload: connectRequest,
                responseType: ConnectResponse.self
            )

            self.daemonVersion = response.version
            self.sessionId = response.sessionId
            self.capabilities = response.capabilities

            Logger.info("Connected to Ainos daemon v\(response.version) (session: \(response.sessionId))")

            if let welcome = response.welcome {
                Logger.info("Daemon says: \(welcome)")
            }

            updateState(.connected)

        } catch {
            updateState(.failed(error.asAinosError))
            // Clean up the transport on failure
            await transport.disconnect()
            throw error
        }
    }

    /// Disconnects from the Ainos daemon gracefully.
    ///
    /// Sends a disconnect request to the daemon before closing the TCP
    /// connection. This allows the daemon to clean up any resources
    /// associated with the session.
    public func disconnect() async {
        Logger.info("Disconnecting from Ainos daemon")

        updateState(.disconnecting)

        do {
            // Send a disconnect request (best-effort)
            try await sendDisconnectRequest()
        } catch {
            Logger.debug("Disconnect request failed (ignored): \(error.localizedDescription)")
        }

        await transport.disconnect()
        updateState(.disconnected)
        stateContinuation?.finish()
        stateContinuation = nil
    }

    // MARK: - Inference

    /// Performs a non-streaming inference request.
    ///
    /// The response is returned as a single `InferResponse` once the
    /// entire generation is complete.
    ///
    /// - Parameters:
    ///   - model: The model identifier to use.
    ///   - prompt: The input prompt text.
    ///   - messages: Chat messages (alternative to prompt).
    ///   - config: Optional inference configuration overrides.
    ///   - sessionId: Optional session identifier for context reuse.
    /// - Returns: The complete inference response.
    /// - Throws: `AinosError` if the request fails.
    public func infer(
        model: String,
        prompt: String? = nil,
        messages: [Message]? = nil,
        config: InferenceConfig? = nil,
        sessionId: String? = nil
    ) async throws -> InferResponse {
        try await ensureConnected()

        let request = InferRequest(
            model: model,
            prompt: prompt,
            messages: messages,
            config: config,
            sessionId: sessionId
        )

        return try await sendRequest(
            method: .infer,
            payload: request,
            responseType: InferResponse.self
        )
    }

    /// Performs a streaming inference request.
    ///
    /// Returns an `InferenceStream` that conforms to `AsyncSequence`,
    /// allowing you to iterate over events as they arrive:
    ///
    /// ```swift
    /// let stream = try await client.inferStream(
    ///     model: "gpt-3.5-turbo",
    ///     prompt: "Tell me a story"
    /// )
    ///
    /// for try await event in stream {
    ///     switch event.type {
    ///     case .token:
    ///         print(event.delta ?? "", terminator: "")
    ///     case .done:
    ///         print("\n[Done]")
    ///     case .error:
    ///         print("\n[Error: \(event.delta ?? "unknown")]")
    ///     default:
    ///         break
    ///     }
    /// }
    /// ```
    ///
    /// - Parameters:
    ///   - model: The model identifier to use.
    ///   - prompt: The input prompt text.
    ///   - messages: Chat messages (alternative to prompt).
    ///   - config: Optional inference configuration overrides.
    ///   - sessionId: Optional session identifier for context reuse.
    /// - Returns: A stream of inference events.
    /// - Throws: `AinosError` if the request fails to start.
    public func inferStream(
        model: String,
        prompt: String? = nil,
        messages: [Message]? = nil,
        config: InferenceConfig? = nil,
        sessionId: String? = nil
    ) async throws -> InferenceStream {
        try await ensureConnected()

        let requestId = requestIDGenerator.generate()
        let request = InferRequest(
            model: model,
            prompt: prompt,
            messages: messages,
            config: config,
            sessionId: sessionId
        )

        // Send the stream request
        let payload = try createFrame(
            method: .inferStream,
            requestId: requestId,
            payload: request
        )
        let jsonString = try JSON.stringify(payload)
        try await transport.sendLine(jsonString)

        Logger.debug("Sent streaming inference request [\(requestId)]")

        // Track metrics
        lock.lock()
        metrics.requestsSent += 1
        metrics.bytesSent += Int64(jsonString.utf8.count + 1) // +1 for newline
        lock.unlock()

        // Create and return the stream
        return InferenceStream(transport: transport, requestId: requestId)
    }

    // MARK: - Model Management

    /// Lists all available models on the daemon.
    ///
    /// - Returns: A response containing the list of models.
    /// - Throws: `AinosError` if the request fails.
    public func modelList() async throws -> ModelListResponse {
        try await ensureConnected()

        return try await sendRequest(
            method: .modelList,
            payload: EmptyPayload(),
            responseType: ModelListResponse.self
        )
    }

    /// Loads a model into memory.
    ///
    /// - Parameters:
    ///   - model: The model identifier to load.
    ///   - config: Optional loading configuration.
    /// - Returns: The operation response.
    /// - Throws: `AinosError` if the load fails.
    public func modelLoad(
        model: String,
        config: ModelLoadConfig? = nil
    ) async throws -> ModelOperationResponse {
        try await ensureConnected()

        let request = ModelLoadRequest(model: model, config: config)
        return try await sendRequest(
            method: .modelLoad,
            payload: request,
            responseType: ModelOperationResponse.self
        )
    }

    /// Unloads a model from memory.
    ///
    /// - Parameter model: The model identifier to unload.
    /// - Returns: The operation response.
    /// - Throws: `AinosError` if the unload fails.
    public func modelUnload(model: String) async throws -> ModelOperationResponse {
        try await ensureConnected()

        let request = ModelLoadRequest(model: model)
        return try await sendRequest(
            method: .modelUnload,
            payload: request,
            responseType: ModelOperationResponse.self
        )
    }

    // MARK: - Health & Status

    /// Checks the health of the daemon.
    ///
    /// - Returns: The health response.
    /// - Throws: `AinosError` if the health check fails.
    public func health() async throws -> HealthResponse {
        // Health check can work even without a full connection
        do {
            return try await sendRequest(
                method: .health,
                payload: EmptyPayload(),
                responseType: HealthResponse.self
            )
        } catch {
            // If we get a connection error, return unhealthy
            if let ainosError = error as? AinosError, ainosError.isConnectionError {
                return HealthResponse(
                    healthy: false,
                    uptimeSeconds: nil,
                    version: nil,
                    activeConnections: nil,
                    memoryUsageBytes: nil
                )
            }
            throw error
        }
    }

    /// Gets the detailed daemon status.
    ///
    /// - Returns: The daemon status.
    /// - Throws: `AinosError` if the status request fails.
    public func status() async throws -> DaemonStatus {
        try await ensureConnected()

        return try await sendRequest(
            method: .status,
            payload: EmptyPayload(),
            responseType: DaemonStatus.self
        )
    }

    // MARK: - Context Store / Retrieve

    /// Stores context data on the daemon for later retrieval.
    ///
    /// Context data is key-value storage that persists for the duration
    /// of the session (or a configurable TTL). It can be used to share
    /// state between different inference requests.
    ///
    /// - Parameters:
    ///   - key: The key to store the context under.
    ///   - value: The context data.
    ///   - ttlSeconds: Optional time-to-live in seconds.
    ///   - overwrite: Whether to overwrite an existing value.
    /// - Returns: The store response.
    /// - Throws: `AinosError` if the store operation fails.
    public func contextStore(
        key: String,
        value: [String: AnyCodable],
        ttlSeconds: Int? = nil,
        overwrite: Bool? = nil
    ) async throws -> ContextStoreResponse {
        try await ensureConnected()

        let request = ContextStoreRequest(
            key: key,
            value: value,
            ttlSeconds: ttlSeconds,
            overwrite: overwrite
        )

        return try await sendRequest(
            method: .contextStore,
            payload: request,
            responseType: ContextStoreResponse.self
        )
    }

    /// Retrieves stored context data from the daemon.
    ///
    /// - Parameter key: The key to retrieve.
    /// - Returns: The retrieve response containing the stored context.
    /// - Throws: `AinosError` if the retrieval fails.
    public func contextRetrieve(key: String) async throws -> ContextRetrieveResponse {
        try await ensureConnected()

        let request = ContextRetrieveRequest(key: key)
        return try await sendRequest(
            method: .contextRetrieve,
            payload: request,
            responseType: ContextRetrieveResponse.self
        )
    }

    // MARK: - Metrics

    /// Returns the current SDK metrics.
    /// - Returns: A copy of the metrics.
    public func getMetrics() -> SDKMetrics {
        lock.lock()
        defer { lock.unlock() }
        return metrics
    }

    // MARK: - Private Methods

    /// Ensures the client is connected before performing operations.
    private func ensureConnected() async throws {
        guard case .connected = connectionState else {
            throw AinosError(
                code: .connectionClosed,
                description: "Not connected to the daemon. Call connect() first."
            )
        }
    }

    /// Sends a request and receives a typed response.
    private func sendRequest<Request: Encodable, Response: Decodable>(
        method: RequestMethod,
        payload: Request,
        responseType: Response.Type
    ) async throws -> Response {
        let requestId = requestIDGenerator.generate()
        let frame = try createFrame(method: method, requestId: requestId, payload: payload)
        let jsonString = try JSON.stringify(frame)

        Logger.debug("Sending \(method.wireValue) request [\(requestId)]")

        // Send the request
        try await transport.sendLine(jsonString)

        // Track metrics
        lock.lock()
        metrics.requestsSent += 1
        metrics.bytesSent += Int64(jsonString.utf8.count + 1)
        lock.unlock()

        // Read the response
        guard let responseLine = try await transport.readLine() else {
            throw AinosError(
                code: .connectionClosed,
                description: "Connection closed before receiving response"
            )
        }

        // Track metrics
        lock.lock()
        metrics.responsesReceived += 1
        metrics.bytesReceived += Int64(responseLine.utf8.count + 1)
        lock.unlock()

        // Parse the response frame
        let responseFrame: NdjsonFrame
        do {
            responseFrame = try JSON.parse(responseLine, as: NdjsonFrame.self)
        } catch {
            lock.lock()
            metrics.errors += 1
            lock.unlock()
            throw AinosError.invalidResponse(
                details: "Failed to parse response frame: \(error.localizedDescription)",
                underlying: error
            )
        }

        // Check for daemon-level error
        if let frameError = responseFrame.error {
            lock.lock()
            metrics.errors += 1
            lock.unlock()

            throw AinosError(
                code: AinosError.Code(rawValue: frameError.code),
                description: frameError.message,
                underlyingError: nil
            )
        }

        // Decode the payload
        do {
            let payloadData = try JSONEncoder.ainos.encode(responseFrame.payload)
            let response = try JSONDecoder.ainos.decode(Response.self, from: payloadData)
            return response
        } catch {
            lock.lock()
            metrics.errors += 1
            lock.unlock()
            throw AinosError.invalidResponse(
                details: "Failed to decode response payload: \(error.localizedDescription)",
                underlying: error
            )
        }
    }

    /// Creates an NDJSON frame for a request.
    private func createFrame<Payload: Encodable>(
        method: RequestMethod,
        requestId: String,
        payload: Payload
    ) throws -> NdjsonFrame {
        let payloadData = try JSONEncoder.ainos.encode(payload)
        let payloadDict = try JSONDecoder.ainos.decode(
            [String: AnyCodable].self, from: payloadData
        )

        return NdjsonFrame(
            type: method.wireValue,
            requestId: requestId,
            timestamp: Date(),
            payload: payloadDict
        )
    }

    /// Sends a disconnect request (best-effort, ignores errors).
    private func sendDisconnectRequest() async throws {
        guard case .connected = connectionState else { return }

        let requestId = requestIDGenerator.generate()
        let frame = NdjsonFrame(
            type: RequestMethod.disconnect.wireValue,
            requestId: requestId,
            timestamp: Date()
        )
        let jsonString = try JSON.stringify(frame)
        try await transport.sendLine(jsonString)
    }

    /// Updates the connection state and notifies observers.
    private func updateState(_ newState: ConnectionState) {
        lock.lock()
        connectionState = newState
        lock.unlock()
        stateContinuation?.yield(newState)
    }

    /// Detects the current platform name.
    private static func detectPlatform() async -> String {
        #if os(macOS)
        return "macOS"
        #elseif os(iOS)
        return "iOS"
        #elseif os(tvOS)
        return "tvOS"
        #elseif os(watchOS)
        return "watchOS"
        #elseif os(visionOS)
        return "visionOS"
        #elseif os(Linux)
        return "Linux"
        #elseif os(Windows)
        return "Windows"
        #else
        return "Unknown"
        #endif
    }

    /// Detects the Swift version used to build the SDK.
    private static func detectSwiftVersion() async -> String {
        #if swift(>=6.0)
        return "6.0"
        #elseif swift(>=5.10)
        return "5.10"
        #elseif swift(>=5.9)
        return "5.9"
        #elseif swift(>=5.8)
        return "5.8"
        #else
        return "Unknown"
        #endif
    }
}

// MARK: - Connection State

/// The state of the client's connection to the daemon.
public enum ConnectionState: Sendable, Equatable, CustomStringConvertible {
    /// The client is not connected.
    case disconnected
    /// The client is in the process of connecting.
    case connecting
    /// The client is connected and ready.
    case connected
    /// The client is disconnecting.
    case disconnecting
    /// The connection failed with an error.
    case failed(AinosError)

    public var description: String {
        switch self {
        case .disconnected: return "disconnected"
        case .connecting: return "connecting"
        case .connected: return "connected"
        case .disconnecting: return "disconnecting"
        case .failed(let error): return "failed: \(error.description)"
        }
    }

    /// Returns `true` if the client is in a connected state.
    public var isConnected: Bool {
        self == .connected
    }
}

// MARK: - Empty Payload

/// A type used for requests that have no payload body.
internal struct EmptyPayload: Codable, Sendable {}

// MARK: - Convenience Extensions

extension AinosClient {

    /// Convenience method for chat-style inference with messages.
    /// - Parameters:
    ///   - model: The model identifier.
    ///   - messages: The chat messages.
    ///   - config: Optional inference configuration.
    /// - Returns: The inference response.
    public func chat(
        model: String,
        messages: [Message],
        config: InferenceConfig? = nil
    ) async throws -> InferResponse {
        try await infer(
            model: model,
            messages: messages,
            config: config
        )
    }

    /// Convenience method for streaming chat-style inference.
    /// - Parameters:
    ///   - model: The model identifier.
    ///   - messages: The chat messages.
    ///   - config: Optional inference configuration.
    /// - Returns: A stream of inference events.
    public func chatStream(
        model: String,
        messages: [Message],
        config: InferenceConfig? = nil
    ) async throws -> InferenceStream {
        try await inferStream(
            model: model,
            messages: messages,
            config: config
        )
    }

    /// Convenience method to perform inference and collect the full text.
    /// - Parameters:
    ///   - model: The model identifier.
    ///   - prompt: The input prompt.
    ///   - config: Optional inference configuration.
    /// - Returns: The generated text.
    public func generate(
        model: String,
        prompt: String,
        config: InferenceConfig? = nil
    ) async throws -> String {
        let response = try await infer(model: model, prompt: prompt, config: config)
        return response.text
    }

    /// Convenience method to check if the daemon is reachable.
    /// - Returns: `true` if the daemon is healthy.
    public func isHealthy() async -> Bool {
        do {
            let response = try await health()
            return response.healthy
        } catch {
            return false
        }
    }
}

// MARK: - AsyncSequence Support for InferenceStream

// InferenceStream already conforms to AsyncSequence — this extension
// adds convenience operators like `map`, `filter`, `compactMap`, etc.

extension InferenceStream {

    /// Transforms each event using the provided closure.
    /// - Parameter transform: The transformation closure.
    /// - Returns: An async throwing stream of transformed values.
    public func map<T>(
        _ transform: @escaping (StreamEvent) async throws -> T
    ) -> AsyncThrowingStream<T, Error> {
        AsyncThrowingStream { continuation in
            Task {
                do {
                    for try await event in self {
                        let transformed = try await transform(event)
                        continuation.yield(transformed)
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
        }
    }

    /// Filters events based on the provided predicate.
    /// - Parameter isIncluded: The predicate to filter events.
    /// - Returns: An async throwing stream of filtered events.
    public func filter(
        _ isIncluded: @escaping (StreamEvent) async throws -> Bool
    ) -> AsyncThrowingStream<StreamEvent, Error> {
        AsyncThrowingStream { continuation in
            Task {
                do {
                    for try await event in self {
                        if try await isIncluded(event) {
                            continuation.yield(event)
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
        }
    }

    /// Extracts only the text delta from each token event.
    /// - Returns: An async throwing stream of text deltas.
    public func textDeltas() -> AsyncThrowingStream<String, Error> {
        filter { $0.type == .token }.compactMap { $0.delta }
    }
}

extension AsyncThrowingStream where Element == String, Failure == Error {

    /// Collects all text deltas into a single string.
    /// - Returns: The concatenated text.
    public func collectText() async throws -> String {
        try await reduce(into: "") { $0 += $1 }
    }
}