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

// MARK: - Stream State

/// The state of a streaming inference session.
public enum StreamState: Sendable, Equatable {
    /// The stream has not started yet.
    case idle
    /// The stream is actively producing tokens.
    case streaming
    /// The stream has been paused (backpressure applied).
    case paused
    /// The stream completed successfully.
    case completed(StreamResult)
    /// The stream encountered an error.
    case failed(AinosError)
    /// The stream was cancelled by the client.
    case cancelled

    /// Returns `true` if the stream is still active.
    public var isActive: Bool {
        switch self {
        case .idle, .streaming, .paused: return true
        case .completed, .failed, .cancelled: return false
        }
    }

    /// Returns `true` if the stream has terminated.
    public var isTerminal: Bool {
        !isActive
    }
}

/// The final result of a completed stream.
public struct StreamResult: Sendable, Equatable {
    /// The full generated text.
    public let fullText: String

    /// The total number of tokens generated.
    public let tokenCount: Int

    /// Token usage statistics.
    public let usage: TokenUsage?

    /// The reason why generation stopped.
    public let stopReason: StopReason?

    /// Timing information.
    public let timings: InferenceTimings?

    /// Creates a stream result.
    public init(
        fullText: String,
        tokenCount: Int,
        usage: TokenUsage? = nil,
        stopReason: StopReason? = nil,
        timings: InferenceTimings? = nil
    ) {
        self.fullText = fullText
        self.tokenCount = tokenCount
        self.usage = usage
        self.stopReason = stopReason
        self.timings = timings
    }
}

// MARK: - AsyncSequence for Streaming

/// An `AsyncSequence` that yields streaming inference events.
///
/// `InferenceStream` conforms to `AsyncSequence` and `AsyncIteratorProtocol`,
/// allowing you to use `for await` loops to consume streaming results:
///
/// ```swift
/// let stream = try await client.inferStream(prompt: "Hello")
/// for try await event in stream {
///     switch event.type {
///     case .token:
///         print(event.delta ?? "", terminator: "")
///     case .done:
///         print("\n[Generation complete]")
///     case .error:
///         print("\n[Error: \(event.error ?? "unknown")]")
///     default:
///         break
///     }
/// }
/// ```
///
/// ## Cancellation
///
/// The stream respects task cancellation. When the enclosing task is
/// cancelled, the stream stops producing events and the state transitions
/// to `.cancelled`.
///
/// ## Backpressure
///
/// The stream applies backpressure by only reading the next event when
/// the consumer requests it. This prevents unbounded buffering.
public final class InferenceStream: AsyncSequence, AsyncIteratorProtocol {

    // MARK: - Types

    public typealias Element = StreamEvent

    /// The stream element type.
    public typealias AsyncIterator = InferenceStream

    // MARK: - Public Properties

    /// The current state of the stream.
    public private(set) var state: StreamState = .idle

    /// A stream of state changes for observation.
    public let stateChanges: AsyncStream<StreamState>

    /// The accumulated text so far.
    public private(set) var accumulatedText: String = ""

    /// The total number of tokens received so far.
    public private(set) var tokenCount: Int = 0

    // MARK: - Private Properties

    private let transport: TransportProtocol
    private let requestId: String
    private var stateContinuation: AsyncStream<StreamState>.Continuation?
    private var hasMoreEvents: Bool = true
    private var nextEvent: StreamEvent?
    private let lock = NSLock()
    private var isCancelled: Bool = false

    // MARK: - Initialization

    /// Creates an inference stream backed by a transport connection.
    /// - Parameters:
    ///   - transport: The transport to read events from.
    ///   - requestId: The request identifier for correlation.
    public init(transport: TransportProtocol, requestId: String) {
        self.transport = transport
        self.requestId = requestId

        var continuation: AsyncStream<StreamState>.Continuation?
        self.stateChanges = AsyncStream { continuation = $0 }
        self.stateContinuation = continuation
    }

    deinit {
        stateContinuation?.finish()
    }

    // MARK: - AsyncIteratorProtocol

    public func next() async throws -> StreamEvent? {
        // Check for cancellation
        if Task.isCancelled || isCancelled {
            transition(to: .cancelled)
            return nil
        }

        // If we have a buffered event, return it
        if let event = nextEvent {
            nextEvent = nil
            return processEvent(event)
        }

        // If no more events, return nil
        guard hasMoreEvents else {
            return nil
        }

        // Read the next event from the transport
        return try await readNextEvent()
    }

    // MARK: - AsyncSequence

    public func makeAsyncIterator() -> InferenceStream {
        self
    }

    // MARK: - Public Methods

    /// Cancels the stream and releases resources.
    public func cancel() {
        lock.lock()
        defer { lock.unlock() }

        isCancelled = true
        hasMoreEvents = false
        transition(to: .cancelled)
    }

    /// Returns the accumulated text.
    /// - Returns: The complete text generated so far.
    public func getAccumulatedText() -> String {
        lock.lock()
        defer { lock.unlock() }
        return accumulatedText
    }

    // MARK: - Private Methods

    /// Reads the next event from the transport.
    private func readNextEvent() async throws -> StreamEvent? {
        transition(to: .streaming)

        guard let line = try await transport.readLine() else {
            // Connection closed
            hasMoreEvents = false
            transition(to: .completed(StreamResult(
                fullText: accumulatedText,
                tokenCount: tokenCount
            )))
            return nil
        }

        guard let data = line.data(using: .utf8) else {
            throw AinosError.invalidResponse(details: "Non-UTF8 data in stream")
        }

        let event: StreamEvent
        do {
            event = try JSONDecoder.ainos.decode(StreamEvent.self, from: data)
        } catch {
            throw AinosError.invalidResponse(
                details: "Failed to decode stream event",
                underlying: error
            )
        }

        // Check for terminal events
        switch event.type {
        case .done:
            hasMoreEvents = false
            let result = StreamResult(
                fullText: accumulatedText,
                tokenCount: tokenCount,
                usage: event.usage,
                stopReason: event.stopReason,
                timings: event.timings
            )
            transition(to: .completed(result))

        case .error:
            hasMoreEvents = false
            let error = AinosError.inferenceFailed(
                reason: event.delta ?? "Unknown stream error"
            )
            transition(to: .failed(error))

        default:
            break
        }

        return processEvent(event)
    }

    /// Processes an event and updates internal state.
    private func processEvent(_ event: StreamEvent) -> StreamEvent {
        if let delta = event.delta {
            lock.lock()
            accumulatedText += delta
            if event.index != nil {
                tokenCount += 1
            }
            lock.unlock()
        }
        return event
    }

    /// Transitions to a new state and notifies observers.
    private func transition(to newState: StreamState) {
        lock.lock()
        state = newState
        lock.unlock()
        stateContinuation?.yield(newState)
    }
}

// MARK: - Stream Collector

/// A utility that collects all events from a stream into a single result.
///
/// `StreamCollector` provides a convenient way to consume a streaming
/// inference and get the complete result, while still being able to
/// observe individual events through a callback.
///
/// ## Usage
///
/// ```swift
/// let collector = StreamCollector()
/// let stream = try await client.inferStream(prompt: "Hello")
/// let result = try await collector.collect(stream)
/// print(result.fullText)
/// ```
public final class StreamCollector {

    /// A callback invoked for each stream event.
    public typealias EventCallback = @Sendable (StreamEvent) -> Void

    private let onEvent: EventCallback?

    /// Creates a stream collector.
    /// - Parameter onEvent: An optional callback for each event.
    public init(onEvent: EventCallback? = nil) {
        self.onEvent = onEvent
    }

    /// Collects all events from a stream into a `StreamResult`.
    /// - Parameter stream: The inference stream to consume.
    /// - Returns: The complete stream result.
    /// - Throws: An error if the stream encounters an error.
    public func collect(_ stream: InferenceStream) async throws -> StreamResult {
        var fullText = ""
        var tokenCount = 0
        var finalUsage: TokenUsage?
        var finalStopReason: StopReason?
        var finalTimings: InferenceTimings?

        for try await event in stream {
            onEvent?(event)

            switch event.type {
            case .token:
                if let delta = event.delta {
                    fullText += delta
                }
                if event.index != nil {
                    tokenCount += 1
                }

            case .done:
                finalUsage = event.usage
                finalStopReason = event.stopReason
                finalTimings = event.timings

            case .error:
                throw AinosError.inferenceFailed(
                    reason: event.delta ?? "Stream error"
                )

            case .processing:
                // Processing event, no action needed
                break
            }
        }

        return StreamResult(
            fullText: fullText,
            tokenCount: tokenCount,
            usage: finalUsage,
            stopReason: finalStopReason,
            timings: finalTimings
        )
    }

    /// Collects all events from a stream and returns just the text.
    /// - Parameter stream: The inference stream to consume.
    /// - Returns: The complete generated text.
    /// - Throws: An error if the stream encounters an error.
    public func collectText(_ stream: InferenceStream) async throws -> String {
        let result = try await collect(stream)
        return result.fullText
    }
}

// MARK: - Stream Event Serialization

extension StreamEvent {

    /// Serializes this event to a JSON string suitable for NDJSON.
    /// - Returns: A JSON string representation.
    /// - Throws: An error if serialization fails.
    public func serialize() throws -> String {
        let encoder = JSONEncoder.ainos
        let data = try encoder.encode(self)
        guard let jsonString = String(data: data, encoding: .utf8) else {
            throw AinosError.internalError("Failed to serialize StreamEvent to string")
        }
        return jsonString
    }

    /// Deserializes a stream event from a JSON string.
    /// - Parameter json: The JSON string to parse.
    /// - Returns: The decoded stream event.
    /// - Throws: An error if deserialization fails.
    public static func deserialize(from json: String) throws -> StreamEvent {
        guard let data = json.data(using: .utf8) else {
            throw AinosError.invalidResponse(details: "Non-UTF8 JSON string")
        }
        return try JSONDecoder.ainos.decode(StreamEvent.self, from: data)
    }
}

// MARK: - Stream Metrics

/// Metrics collected during a streaming inference session.
public struct StreamMetrics: Sendable, Equatable {
    /// The total number of events received.
    public let totalEvents: Int

    /// The number of token events.
    public let tokenEvents: Int

    /// The total time from first to last event (in seconds).
    public let duration: TimeInterval

    /// The average time between token events (in seconds).
    public let averageTokenInterval: TimeInterval?

    /// The tokens per second rate.
    public let tokensPerSecond: Double?

    /// The time to first token (in seconds).
    public let timeToFirstToken: TimeInterval?

    /// Creates stream metrics.
    public init(
        totalEvents: Int,
        tokenEvents: Int,
        duration: TimeInterval,
        averageTokenInterval: TimeInterval? = nil,
        tokensPerSecond: Double? = nil,
        timeToFirstToken: TimeInterval? = nil
    ) {
        self.totalEvents = totalEvents
        self.tokenEvents = tokenEvents
        self.duration = duration
        self.averageTokenInterval = averageTokenInterval
        self.tokensPerSecond = tokensPerSecond
        self.timeToFirstToken = timeToFirstToken
    }
}

// MARK: - Stream Monitor

/// An utility that monitors a stream and collects metrics.
///
/// `StreamMonitor` wraps an `InferenceStream` and records timing
/// information for each event. It is useful for performance analysis
/// and debugging.
///
/// ## Usage
///
/// ```swift
/// let monitor = StreamMonitor()
/// let monitoredStream = monitor.attach(to: originalStream)
/// let result = try await StreamCollector().collect(monitoredStream)
/// print(monitor.metrics) // StreamMetrics
/// ```
public final class StreamMonitor: Sendable {

    // MARK: - Public Properties

    /// The collected metrics.
    public private(set) var metrics: StreamMetrics?

    // MARK: - Private Properties

    private let lock = NSLock()
    private var eventTimestamps: [Date] = []
    private var startTime: Date?
    private var firstTokenTime: Date?
    private var lastEventTime: Date?
    private var tokenCount: Int = 0
    private var totalEvents: Int = 0

    /// Creates a stream monitor.
    public init() {}

    /// Attaches this monitor to a stream, returning a wrapped stream.
    /// - Parameter stream: The original inference stream.
    /// - Returns: A monitored inference stream.
    public func attach(to stream: InferenceStream) -> MonitoredStream {
        MonitoredStream(stream: stream, monitor: self)
    }

    /// Records an event for metric collection.
    /// - Parameter event: The event that occurred.
    internal func recordEvent(_ event: StreamEvent) {
        lock.lock()
        defer { lock.unlock() }

        let now = Date()
        totalEvents += 1
        eventTimestamps.append(now)

        if startTime == nil {
            startTime = now
        }

        if event.type == .token {
            if firstTokenTime == nil {
                firstTokenTime = now
            }
            tokenCount += 1
        }

        lastEventTime = now
    }

    /// Finalizes and computes metrics.
    internal func finalize() {
        lock.lock()
        defer { lock.unlock() }

        guard let start = startTime, let end = lastEventTime else {
            metrics = nil
            return
        }

        let duration = end.timeIntervalSince(start)

        let timeToFirstToken: TimeInterval?
        if let firstToken = firstTokenTime {
            timeToFirstToken = firstToken.timeIntervalSince(start)
        } else {
            timeToFirstToken = nil
        }

        let tokensPerSecond: Double?
        let averageTokenInterval: TimeInterval?
        if duration > 0 && tokenCount > 0 {
            tokensPerSecond = Double(tokenCount) / duration
            averageTokenInterval = duration / Double(tokenCount)
        } else {
            tokensPerSecond = nil
            averageTokenInterval = nil
        }

        metrics = StreamMetrics(
            totalEvents: totalEvents,
            tokenEvents: tokenCount,
            duration: duration,
            averageTokenInterval: averageTokenInterval,
            tokensPerSecond: tokensPerSecond,
            timeToFirstToken: timeToFirstToken
        )
    }
}

/// A stream wrapper that records events for a `StreamMonitor`.
public final class MonitoredStream: AsyncSequence, AsyncIteratorProtocol {

    public typealias Element = StreamEvent
    public typealias AsyncIterator = MonitoredStream

    private var iterator: InferenceStream.AsyncIterator
    private let monitor: StreamMonitor

    /// Creates a monitored stream.
    /// - Parameters:
    ///   - stream: The stream to wrap.
    ///   - monitor: The monitor to record events.
    internal init(stream: InferenceStream, monitor: StreamMonitor) {
        self.iterator = stream.makeAsyncIterator()
        self.monitor = monitor
    }

    public func next() async throws -> StreamEvent? {
        let event = try await iterator.next()
        if let event = event {
            monitor.recordEvent(event)
        } else {
            monitor.finalize()
        }
        return event
    }

    public func makeAsyncIterator() -> MonitoredStream {
        self
    }
}

// MARK: - Stream Merge

/// Merges multiple inference streams into a single stream.
///
/// Events from all input streams are interleaved in the order they
/// are received. This is useful for parallel generation scenarios.
///
/// ## Note
///
/// The merged stream ends when all input streams have completed.
public final class MergedStream: AsyncSequence, AsyncIteratorProtocol {

    public typealias Element = (streamIndex: Int, event: StreamEvent)
    public typealias AsyncIterator = MergedStream

    private let streams: [InferenceStream]
    private var activeStreams: Set<Int>
    private let lock = NSLock()
    private var currentIndex: Int = 0

    /// Creates a merged stream from multiple inference streams.
    /// - Parameter streams: The streams to merge.
    public init(streams: [InferenceStream]) {
        self.streams = streams
        self.activeStreams = Set(streams.indices)
    }

    public func next() async throws -> (streamIndex: Int, event: StreamEvent)? {
        // This is a simplified implementation — in practice, you'd use
        // a more sophisticated approach with async task groups.
        // For now, we round-robin through the streams.
        lock.lock()
        let startIndex = currentIndex
        lock.unlock()

        for offset in 0..<streams.count {
            let idx = (startIndex + offset) % streams.count

            guard activeStreams.contains(idx) else { continue }

            var iterator = streams[idx].makeAsyncIterator()
            if let event = try await iterator.next() {
                lock.lock()
                currentIndex = (idx + 1) % streams.count
                lock.unlock()
                return (idx, event)
            } else {
                lock.lock()
                activeStreams.remove(idx)
                lock.unlock()
            }
        }

        return nil
    }

    public func makeAsyncIterator() -> MergedStream {
        self
    }
}