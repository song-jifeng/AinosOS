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
#if canImport(Network)
import Network
#endif

// MARK: - Transport Protocol

/// A protocol abstracting the underlying transport mechanism.
///
/// The transport layer is responsible for establishing a TCP connection
/// to the Ainos daemon, sending NDJSON-encoded data, and receiving
/// NDJSON-delimited responses. The default implementation uses
/// `NWConnection` from the Network framework, which supports both
/// IPv4 and IPv6, TLS, and works across Apple platforms.
///
/// ## Concurrency
///
/// All transport methods are `async` and can be cancelled via
/// `Task.cancel()`. The transport respects structured concurrency
/// and will clean up resources when the enclosing task is cancelled.
public protocol TransportProtocol: AnyObject, Sendable {

    /// The current state of the transport connection.
    var state: TransportState { get }

    /// A stream of state changes for observation.
    var stateStream: AsyncStream<TransportState> { get }

    /// Connects to the specified host and port.
    /// - Parameters:
    ///   - host: The hostname or IP address.
    ///   - port: The TCP port.
    ///   - timeout: The connection timeout in seconds.
    /// - Throws: `AinosError` if the connection fails.
    func connect(host: String, port: Int, timeout: TimeInterval) async throws

    /// Disconnects from the daemon.
    func disconnect() async

    /// Sends data over the connection.
    /// - Parameter data: The data to send.
    /// - Throws: `AinosError` if the send fails.
    func send(data: Data) async throws

    /// Receives data from the connection.
    /// - Returns: The received data, or `nil` if the connection closed.
    /// - Throws: `AinosError` if the receive fails.
    func receive() async throws -> Data?

    /// Sends a string over the connection (appends a newline for NDJSON).
    /// - Parameter string: The string to send.
    /// - Throws: `AinosError` if the send fails.
    func sendLine(_ string: String) async throws

    /// Reads a single line (terminated by `\n`) from the connection.
    /// - Returns: The line as a string, or `nil` if the connection closed.
    /// - Throws: `AinosError` if the read fails.
    func readLine() async throws -> String?
}

/// The state of the transport connection.
public enum TransportState: Sendable, Equatable, CustomStringConvertible {
    /// The transport is not connected.
    case disconnected
    /// The transport is in the process of connecting.
    case connecting
    /// The transport is connected and ready.
    case connected
    /// The transport encountered an error.
    case failed(AinosError)

    public var description: String {
        switch self {
        case .disconnected: return "disconnected"
        case .connecting: return "connecting"
        case .connected: return "connected"
        case .failed(let error): return "failed: \(error.description)"
        }
    }

    /// Returns `true` if the transport is in a usable state.
    public var isUsable: Bool {
        if case .connected = self { return true }
        return false
    }
}

// MARK: - Default Transport Implementation

/// The default TCP transport implementation using Network.framework.
///
/// `TCPTransport` manages a single `NWConnection` to the Ainos daemon.
/// It handles:
/// - Connection establishment with timeout
/// - Graceful disconnection
/// - NDJSON line-delimited sending and receiving
/// - Partial read buffering
/// - Connection state observation via `AsyncStream`
/// - Cancellation via task cancellation
///
/// ## Usage
///
/// ```swift
/// let transport = TCPTransport()
/// try await transport.connect(host: "127.0.0.1", port: 9500, timeout: 10)
/// try await transport.sendLine("{\"type\":\"health\"}")
/// let response = try await transport.readLine()
/// ```
public final class TCPTransport: TransportProtocol {

    // MARK: - Public Properties

    public private(set) var state: TransportState = .disconnected {
        didSet {
            continuation?.yield(state)
        }
    }

    public var stateStream: AsyncStream<TransportState> {
        AsyncStream { continuation in
            self.continuation = continuation
            continuation.yield(state)
        }
    }

    // MARK: - Private Properties

    private var connection: NWConnection?
    private var continuation: AsyncStream<TransportState>.Continuation?
    private let queue: DispatchQueue
    private var readBuffer: Data
    private let receiveQueue: DispatchQueue
    private var isCancelled: Bool = false

    // MARK: - Initialization

    /// Creates a new TCP transport.
    /// - Parameter queue: The dispatch queue for network operations.
    public init(
        queue: DispatchQueue = DispatchQueue(
            label: "com.ainos.sdk.transport",
            qos: .userInitiated
        )
    ) {
        self.queue = queue
        self.receiveQueue = DispatchQueue(
            label: "com.ainos.sdk.transport.receive",
            qos: .userInitiated
        )
        self.readBuffer = Data()
    }

    deinit {
        continuation?.finish()
        connection?.cancel()
    }

    // MARK: - Connect

    public func connect(
        host: String,
        port: Int,
        timeout: TimeInterval
    ) async throws {
        guard state != .connected else {
            throw AinosError(
                code: .connectionFailed,
                description: "Already connected to \(host):\(port)"
            )
        }

        state = .connecting

        let parameters = NWParameters.tcp
        parameters.allowFastOpen = true
        parameters.expiredDNSBehavior = .allow

        let endpoint = NWEndpoint.hostPort(
            host: NWEndpoint.Host(host),
            port: NWEndpoint.Port(rawValue: UInt16(port))!
        )

        let connection = NWConnection(to: endpoint, using: parameters)
        self.connection = connection
        self.isCancelled = false

        // Set up the state update handler
        connection.stateUpdateHandler = { [weak self] newState in
            guard let self = self else { return }
            self.queue.async {
                switch newState {
                case .ready:
                    self.state = .connected
                case .failed(let error):
                    self.state = .failed(error.asAinosError)
                case .cancelled:
                    self.state = .disconnected
                case .waiting(let error):
                    // Still connecting, but may be waiting for network
                    Logger.debug("Transport waiting: \(error.localizedDescription)")
                default:
                    break
                }
            }
        }

        // Start the connection
        connection.start(queue: queue)

        // Wait for connection or timeout
        try await withThrowingTaskGroup(of: Void.self) { group in
            group.addTask {
                try await self.waitForConnection()
            }
            group.addTask {
                try await Task.sleep(nanoseconds: UInt64(timeout * 1_000_000_000))
                throw AinosError(
                    code: .connectionTimedOut,
                    description: "Connection to \(host):\(port) timed out after \(timeout)s"
                )
            }
            try await group.next()
            group.cancelAll()
        }

        // Start receiving
        receiveLoop()
    }

    // MARK: - Disconnect

    public func disconnect() async {
        isCancelled = true
        connection?.cancel()
        connection = nil
        state = .disconnected
        continuation?.finish()
        continuation = nil
    }

    // MARK: - Send

    public func send(data: Data) async throws {
        guard let connection = connection else {
            throw AinosError(
                code: .connectionClosed,
                description: "Cannot send: not connected"
            )
        }

        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            connection.send(
                content: data,
                completion: .contentProcessed { error in
                    if let error = error {
                        continuation.resume(throwing: error.asAinosError)
                    } else {
                        continuation.resume()
                    }
                }
            )
        }
    }

    public func sendLine(_ string: String) async throws {
        var data = Data(string.utf8)
        data.append(contentsOf: [0x0A]) // newline
        try await send(data: data)
    }

    // MARK: - Receive

    public func receive() async throws -> Data? {
        guard let connection = connection else {
            throw AinosError(
                code: .connectionClosed,
                description: "Cannot receive: not connected"
            )
        }

        return try await withCheckedThrowingContinuation { continuation in
            connection.receive(
                minimumIncompleteLength: 1,
                maximumLength: 65536
            ) { data, _, isComplete, error in
                if let error = error {
                    continuation.resume(throwing: error.asAinosError)
                } else if isComplete || data == nil {
                    continuation.resume(returning: nil)
                } else {
                    continuation.resume(returning: data)
                }
            }
        }
    }

    public func readLine() async throws -> String? {
        // Check if we already have a complete line in the buffer
        if let line = extractLineFromBuffer() {
            return line
        }

        // Keep reading until we get a line or the connection closes
        while !isCancelled {
            guard let data = try await receive() else {
                // Connection closed
                return nil
            }

            readBuffer.append(data)

            if let line = extractLineFromBuffer() {
                return line
            }
        }

        return nil
    }

    // MARK: - Private Helpers

    /// Extracts a single line from the read buffer.
    /// - Returns: The line as a string, or nil if no complete line is available.
    private func extractLineFromBuffer() -> String? {
        guard let newlineIndex = readBuffer.firstIndex(of: 0x0A) else {
            return nil
        }

        let lineData = readBuffer[..<newlineIndex]
        readBuffer = readBuffer[readBuffer.index(after: newlineIndex)...]

        guard let line = String(data: lineData, encoding: .utf8) else {
            throw AinosError(
                code: .invalidResponse,
                description: "Failed to decode received data as UTF-8"
            )
        }

        return line
    }

    /// Waits for the connection to become ready.
    private func waitForConnection() async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            var token: NSObjectProtocol?
            token = NotificationCenter.default.addObserver(
                forName: .transportStateChanged,
                object: nil,
                queue: nil
            ) { [weak self] notification in
                guard let self = self else { return }
                if let state = notification.userInfo?["state"] as? TransportState {
                    switch state {
                    case .connected:
                        if let token = token {
                            NotificationCenter.default.removeObserver(token)
                        }
                        continuation.resume()
                    case .failed(let error):
                        if let token = token {
                            NotificationCenter.default.removeObserver(token)
                        }
                        continuation.resume(throwing: error)
                    default:
                        break
                    }
                }
            }
        }
    }

    /// Starts the background receive loop that updates state.
    private func receiveLoop() {
        // No-op for now; reading is done on-demand via readLine().
        // This method exists as a hook for future push-based reception.
    }
}

// MARK: - Notification

extension Notification.Name {
    /// Posted when the transport state changes.
    public static let transportStateChanged = Notification.Name(
        "com.ainos.sdk.transportStateChanged"
    )
}

// MARK: - Reconnecting Transport

/// A transport wrapper that automatically reconnects on failure.
///
/// `ReconnectingTransport` wraps any `TransportProtocol` and adds
/// automatic reconnection with exponential backoff. It is useful
/// for long-lived client applications that need to survive
/// temporary network interruptions or daemon restarts.
///
/// ## Usage
///
/// ```swift
/// let inner = TCPTransport()
/// let transport = ReconnectingTransport(
///     wrapping: inner,
///     host: "127.0.0.1",
///     port: 9500,
///     config: AinosClientConfig()
/// )
/// ```
public final class ReconnectingTransport: TransportProtocol {

    // MARK: - Public Properties

    public var state: TransportState {
        inner.state
    }

    public var stateStream: AsyncStream<TransportState> {
        inner.stateStream
    }

    // MARK: - Private Properties

    private let inner: TransportProtocol
    private let host: String
    private let port: Int
    private let config: AinosClientConfig
    private let lock: os_unfair_lock_t
    private var isConnected: Bool

    // MARK: - Initialization

    /// Creates a reconnecting transport.
    /// - Parameters:
    ///   - inner: The underlying transport to wrap.
    ///   - host: The daemon host.
    ///   - port: The daemon port.
    ///   - config: Client configuration for reconnection parameters.
    public init(
        wrapping inner: TransportProtocol,
        host: String,
        port: Int,
        config: AinosClientConfig
    ) {
        self.inner = inner
        self.host = host
        self.port = port
        self.config = config
        self.lock = os_unfair_lock_t.allocate(capacity: 1)
        self.lock.initialize(to: os_unfair_lock())
        self.isConnected = false
    }

    deinit {
        lock.deinitialize(count: 1)
        lock.deallocate()
    }

    // MARK: - Connect

    public func connect(
        host: String,
        port: Int,
        timeout: TimeInterval
    ) async throws {
        try await inner.connect(host: host, port: port, timeout: timeout)
        os_unfair_lock_lock(lock)
        isConnected = true
        os_unfair_lock_unlock(lock)
    }

    // MARK: - Disconnect

    public func disconnect() async {
        os_unfair_lock_lock(lock)
        isConnected = false
        os_unfair_lock_unlock(lock)
        await inner.disconnect()
    }

    // MARK: - Send

    public func send(data: Data) async throws {
        try await performWithReconnect {
            try await self.inner.send(data: data)
        }
    }

    public func sendLine(_ string: String) async throws {
        try await performWithReconnect {
            try await self.inner.sendLine(string)
        }
    }

    // MARK: - Receive

    public func receive() async throws -> Data? {
        try await performWithReconnect {
            try await self.inner.receive()
        }
    }

    public func readLine() async throws -> String? {
        try await performWithReconnect {
            try await self.inner.readLine()
        }
    }

    // MARK: - Reconnection Logic

    /// Performs an operation, automatically reconnecting on failure.
    private func performWithReconnect<T>(
        operation: () async throws -> T
    ) async throws -> T {
        var lastError: Error?

        for attempt in 0...config.maxReconnectAttempts {
            do {
                return try await operation()
            } catch {
                lastError = error

                guard let ainosError = error as? AinosError,
                      ainosError.isRetryable else {
                    throw error
                }

                // Check if we should still try to reconnect
                var shouldReconnect = false
                os_unfair_lock_lock(lock)
                shouldReconnect = isConnected
                os_unfair_lock_unlock(lock)

                guard shouldReconnect else {
                    throw error
                }

                // Exponential backoff
                if attempt < config.maxReconnectAttempts {
                    let delay = config.reconnectDelay * pow(2.0, Double(attempt))
                    Logger.debug(
                        "Reconnecting in \(delay)s (attempt \(attempt + 1)/\(config.maxReconnectAttempts))"
                    )

                    try await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))

                    do {
                        try await inner.connect(
                            host: host,
                            port: port,
                            timeout: config.connectionTimeout
                        )
                    } catch {
                        lastError = error
                        // Continue to next attempt
                    }
                }
            }
        }

        throw lastError ?? AinosError(
            code: .connectionFailed,
            description: "All reconnection attempts failed"
        )
    }
}

// MARK: - Mock Transport (for testing)

/// A mock transport that simulates a daemon connection for testing.
///
/// This transport is backed by a pair of in-memory streams, allowing
/// tests to verify the client's behavior without connecting to a real
/// daemon.
public final class MockTransport: TransportProtocol {

    // MARK: - Public Properties

    public private(set) var state: TransportState = .disconnected
    public var stateStream: AsyncStream<TransportState> {
        AsyncStream { continuation in
            stateContinuation = continuation
            continuation.yield(state)
        }
    }

    /// The data that has been sent by the client.
    public private(set) var sentData: [Data] = []

    /// The data that will be returned by `readLine()`.
    public var mockResponseLines: [String] = []

    /// Whether to simulate a connection failure on the next `connect()`.
    public var simulateConnectionFailure: Bool = false

    /// The error to throw when simulating a connection failure.
    public var connectionFailureError: AinosError = .connectionRefused(
        host: "127.0.0.1", port: 9500
    )

    /// Whether to simulate a send failure.
    public var simulateSendFailure: Bool = false

    /// The error to throw when simulating a send failure.
    public var sendFailureError: AinosError = .connectionClosed

    /// Whether to simulate a receive failure.
    public var simulateReceiveFailure: Bool = false

    /// The error to throw when simulating a receive failure.
    public var receiveFailureError: AinosError = .connectionClosed

    // MARK: - Private Properties

    private var stateContinuation: AsyncStream<TransportState>.Continuation?
    private var responseIndex: Int = 0
    private let lock = NSLock()

    // MARK: - Initialization

    public init() {}

    deinit {
        stateContinuation?.finish()
    }

    // MARK: - Connect

    public func connect(
        host: String,
        port: Int,
        timeout: TimeInterval
    ) async throws {
        if simulateConnectionFailure {
            state = .failed(connectionFailureError)
            throw connectionFailureError
        }
        state = .connected
    }

    // MARK: - Disconnect

    public func disconnect() async {
        state = .disconnected
        stateContinuation?.finish()
        stateContinuation = nil
    }

    // MARK: - Send

    public func send(data: Data) async throws {
        if simulateSendFailure {
            throw sendFailureError
        }
        lock.lock()
        sentData.append(data)
        lock.unlock()
    }

    public func sendLine(_ string: String) async throws {
        var data = Data(string.utf8)
        data.append(contentsOf: [0x0A])
        try await send(data: data)
    }

    // MARK: - Receive

    public func receive() async throws -> Data? {
        if simulateReceiveFailure {
            throw receiveFailureError
        }
        return try await readLine().map { Data($0.utf8) }
    }

    public func readLine() async throws -> String? {
        if simulateReceiveFailure {
            throw receiveFailureError
        }

        lock.lock()
        defer { lock.unlock() }

        guard responseIndex < mockResponseLines.count else {
            // Simulate a hanging connection — return nil only if we're disconnected
            if state == .disconnected {
                return nil
            }
            // Otherwise, suspend until a response is added
            return nil
        }

        let line = mockResponseLines[responseIndex]
        responseIndex += 1
        return line
    }

    // MARK: - Test Helpers

    /// Resets the mock transport to its initial state.
    public func reset() {
        lock.lock()
        sentData.removeAll()
        mockResponseLines.removeAll()
        responseIndex = 0
        simulateConnectionFailure = false
        simulateSendFailure = false
        simulateReceiveFailure = false
        state = .disconnected
        lock.unlock()
    }

    /// Adds a mock response line that will be returned by `readLine()`.
    /// - Parameter line: The response line to add.
    public func enqueueResponse(_ line: String) {
        lock.lock()
        mockResponseLines.append(line)
        lock.unlock()
    }

    /// Returns the last sent data decoded as a UTF-8 string, if possible.
    public var lastSentString: String? {
        lock.lock()
        defer { lock.unlock() }
        guard let last = sentData.last else { return nil }
        return String(data: last, encoding: .utf8)
    }

    /// Returns all sent data decoded as UTF-8 strings.
    public var allSentStrings: [String] {
        lock.lock()
        defer { lock.unlock() }
        return sentData.compactMap { String(data: $0, encoding: .utf8) }
    }
}