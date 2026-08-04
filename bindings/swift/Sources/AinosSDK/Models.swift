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

// MARK: - Connect Request / Response

/// Request payload sent to establish a connection with the daemon.
public struct ConnectRequest: Codable, Sendable, Equatable {
    /// The protocol version the client supports.
    public let version: String

    /// Optional client metadata.
    public let clientInfo: ClientInfo?

    /// Creates a connect request.
    /// - Parameters:
    ///   - version: Protocol version (e.g. "1.0").
    ///   - clientInfo: Optional client metadata.
    public init(version: String = "1.0", clientInfo: ClientInfo? = nil) {
        self.version = version
        self.clientInfo = clientInfo
    }

    enum CodingKeys: String, CodingKey {
        case version
        case clientInfo = "client_info"
    }
}

/// Metadata about the client application.
public struct ClientInfo: Codable, Sendable, Equatable {
    /// The client application name.
    public let name: String

    /// The client application version.
    public let version: String

    /// The platform identifier (e.g. "macOS", "iOS").
    public let platform: String?

    /// The Swift version used to build the client.
    public let swiftVersion: String?

    /// Creates client info.
    public init(
        name: String,
        version: String,
        platform: String? = nil,
        swiftVersion: String? = nil
    ) {
        self.name = name
        self.version = version
        self.platform = platform
        self.swiftVersion = swiftVersion
    }
}

/// Response from the daemon after a successful connection.
public struct ConnectResponse: Codable, Sendable, Equatable {
    /// The daemon version string.
    public let version: String

    /// The daemon's session identifier.
    public let sessionId: String

    /// Server capabilities and features.
    public let capabilities: ServerCapabilities?

    /// A welcome message from the daemon, if any.
    public let welcome: String?

    enum CodingKeys: String, CodingKey {
        case version
        case sessionId = "session_id"
        case capabilities
        case welcome
    }
}

/// Describes the capabilities and features supported by the daemon.
public struct ServerCapabilities: Codable, Sendable, Equatable {
    /// The maximum number of concurrent inference requests.
    public let maxConcurrentInferences: Int?

    /// The maximum context length supported.
    public let maxContextLength: Int?

    /// List of supported inference backends.
    public let supportedBackends: [String]?

    /// Whether the server supports streaming inference.
    public let streamingSupported: Bool?

    /// Whether the server supports context storage.
    public let contextStoreSupported: Bool?

    /// The daemon's maximum batch size.
    public let maxBatchSize: Int?

    /// List of supported model formats.
    public let supportedFormats: [String]?

    enum CodingKeys: String, CodingKey {
        case maxConcurrentInferences = "max_concurrent_inferences"
        case maxContextLength = "max_context_length"
        case supportedBackends = "supported_backends"
        case streamingSupported = "streaming_supported"
        case contextStoreSupported = "context_store_supported"
        case maxBatchSize = "max_batch_size"
        case supportedFormats = "supported_formats"
    }
}

// MARK: - Inference Request / Response

/// Configuration for model inference.
public struct InferenceConfig: Codable, Sendable, Equatable {
    /// The sampling temperature (0.0 to 2.0).
    public var temperature: Double?

    /// Top-k sampling: only the k most likely tokens are considered.
    public var topK: Int?

    /// Top-p (nucleus) sampling threshold.
    public var topP: Double?

    /// The maximum number of tokens to generate.
    public var maxTokens: Int?

    /// Repetition penalty.
    public var repeatPenalty: Double?

    /// Presence penalty.
    public var presencePenalty: Double?

    /// Frequency penalty.
    public var frequencyPenalty: Double?

    /// Stop sequences that halt generation.
    public var stop: [String]?

    /// The random seed for deterministic generation.
    public var seed: UInt64?

    /// Creates an inference configuration with default values.
    public init(
        temperature: Double? = nil,
        topK: Int? = nil,
        topP: Double? = nil,
        maxTokens: Int? = nil,
        repeatPenalty: Double? = nil,
        presencePenalty: Double? = nil,
        frequencyPenalty: Double? = nil,
        stop: [String]? = nil,
        seed: UInt64? = nil
    ) {
        self.temperature = temperature
        self.topK = topK
        self.topP = topP
        self.maxTokens = maxTokens
        self.repeatPenalty = repeatPenalty
        self.presencePenalty = presencePenalty
        self.frequencyPenalty = frequencyPenalty
        self.stop = stop
        self.seed = seed
    }

    enum CodingKeys: String, CodingKey {
        case temperature
        case topK = "top_k"
        case topP = "top_p"
        case maxTokens = "max_tokens"
        case repeatPenalty = "repeat_penalty"
        case presencePenalty = "presence_penalty"
        case frequencyPenalty = "frequency_penalty"
        case stop
        case seed
    }
}

/// A message in a conversation, used for chat-style inference.
public struct Message: Codable, Sendable, Equatable {
    /// The role of the message author.
    public let role: MessageRole

    /// The content of the message.
    public let content: String

    /// Optional metadata attached to the message.
    public let metadata: [String: String]?

    /// Creates a message.
    /// - Parameters:
    ///   - role: The role (system, user, assistant, tool).
    ///   - content: The message content.
    ///   - metadata: Optional metadata.
    public init(
        role: MessageRole,
        content: String,
        metadata: [String: String]? = nil
    ) {
        self.role = role
        self.content = content
        self.metadata = metadata
    }
}

/// The role of a message author.
public enum MessageRole: String, Codable, Sendable, CaseIterable {
    /// System-level instruction message.
    case system
    /// User message (prompt / question).
    case user
    /// Assistant response message.
    case assistant
    /// Tool call result message.
    case tool
}

/// A request for model inference (non-streaming).
public struct InferRequest: Codable, Sendable, Equatable {
    /// The model identifier to use for inference.
    public let model: String

    /// The input prompt text.
    public let prompt: String?

    /// Chat messages for chat-style inference.
    public let messages: [Message]?

    /// Inference configuration overrides.
    public let config: InferenceConfig?

    /// Optional session identifier for context reuse.
    public let sessionId: String?

    /// Creates an inference request.
    /// - Parameters:
    ///   - model: The model identifier.
    ///   - prompt: The input prompt (mutually exclusive with messages).
    ///   - messages: Chat messages (mutually exclusive with prompt).
    ///   - config: Optional inference configuration.
    ///   - sessionId: Optional session identifier.
    public init(
        model: String,
        prompt: String? = nil,
        messages: [Message]? = nil,
        config: InferenceConfig? = nil,
        sessionId: String? = nil
    ) {
        self.model = model
        self.prompt = prompt
        self.messages = messages
        self.config = config
        self.sessionId = sessionId
    }

    enum CodingKeys: String, CodingKey {
        case model
        case prompt
        case messages
        case config
        case sessionId = "session_id"
    }
}

/// The response from a non-streaming inference request.
public struct InferResponse: Codable, Sendable, Equatable {
    /// The generated text.
    public let text: String

    /// The model that generated the response.
    public let model: String

    /// Token usage statistics.
    public let usage: TokenUsage?

    /// The reason why generation stopped.
    public let stopReason: StopReason?

    /// The session identifier for context continuation.
    public let sessionId: String?

    /// Timing information for the inference.
    public let timings: InferenceTimings?

    /// The finish reason as a raw string (e.g. "stop", "length").
    public let finishReason: String?

    enum CodingKeys: String, CodingKey {
        case text, model, usage
        case stopReason = "stop_reason"
        case sessionId = "session_id"
        case timings
        case finishReason = "finish_reason"
    }
}

/// Token usage statistics for an inference request.
public struct TokenUsage: Codable, Sendable, Equatable {
    /// Number of tokens in the prompt.
    public let promptTokens: Int

    /// Number of tokens generated in the response.
    public let completionTokens: Int

    /// Total tokens used (prompt + completion).
    public let totalTokens: Int

    /// Number of tokens cached from a previous request.
    public let cachedTokens: Int?

    enum CodingKeys: String, CodingKey {
        case promptTokens = "prompt_tokens"
        case completionTokens = "completion_tokens"
        case totalTokens = "total_tokens"
        case cachedTokens = "cached_tokens"
    }
}

/// The reason why inference stopped.
public enum StopReason: String, Codable, Sendable {
    /// Generation stopped naturally (e.g. hit a stop token or EOS).
    case stop
    /// Generation stopped because the maximum token limit was reached.
    case length
    /// Generation was cancelled by the client or server.
    case cancelled
    /// Generation stopped due to a content filter.
    case contentFilter = "content_filter"
    /// The model requested a tool call.
    case toolCall = "tool_call"
    /// Generation stopped for an unknown reason.
    case unknown
}

/// Timing information for an inference request.
public struct InferenceTimings: Codable, Sendable, Equatable {
    /// Time spent processing the prompt (in seconds).
    public let promptProcessingMs: Double?

    /// Time spent generating tokens (in seconds).
    public let tokenGenerationMs: Double?

    /// Total inference time (in seconds).
    public let totalMs: Double?

    /// Tokens generated per second.
    public let tokensPerSecond: Double?

    enum CodingKeys: String, CodingKey {
        case promptProcessingMs = "prompt_processing_ms"
        case tokenGenerationMs = "token_generation_ms"
        case totalMs = "total_ms"
        case tokensPerSecond = "tokens_per_second"
    }
}

// MARK: - Streaming Inference

/// A single event in a streaming inference response.
public struct StreamEvent: Codable, Sendable, Equatable {
    /// The type of stream event.
    public let type: StreamEventType

    /// The delta text for this chunk, if applicable.
    public let delta: String?

    /// The index of this token in the generation.
    public let index: Int?

    /// The reason why generation stopped (only on final event).
    public let stopReason: StopReason?

    /// Token usage for the complete generation (only on final event).
    public let usage: TokenUsage?

    /// Timing information (only on final event).
    public let timings: InferenceTimings?

    enum CodingKeys: String, CodingKey {
        case type, delta, index
        case stopReason = "stop_reason"
        case usage, timings
    }
}

/// The type of a streaming inference event.
public enum StreamEventType: String, Codable, Sendable {
    /// A new token has been generated.
    case token
    /// Inference is complete.
    case done
    /// An error occurred during streaming.
    case error
    /// The model is processing the prompt.
    case processing
}

// MARK: - Model Management

/// Represents a model managed by the daemon.
public struct ModelInfo: Codable, Sendable, Equatable, Identifiable {
    /// The unique model identifier.
    public let id: String

    /// The human-readable name of the model.
    public let name: String?

    /// The model version or revision.
    public let version: String?

    /// The model format (e.g. "gguf", "safetensors").
    public let format: String?

    /// The backend used to run the model.
    public let backend: String?

    /// The model family or architecture.
    public let family: String?

    /// The model size in bytes.
    public let sizeBytes: Int64?

    /// Whether the model is currently loaded in memory.
    public let isLoaded: Bool

    /// The number of parameters (e.g. "7B", "13B").
    public let parameterCount: String?

    /// The context length the model supports.
    public let contextLength: Int?

    /// A description of the model.
    public let description: String?

    /// The model's license.
    public let license: String?

    /// Additional metadata.
    public let metadata: [String: String]?

    enum CodingKeys: String, CodingKey {
        case id, name, version, format, backend, family
        case sizeBytes = "size_bytes"
        case isLoaded = "is_loaded"
        case parameterCount = "parameter_count"
        case contextLength = "context_length"
        case description, license, metadata
    }
}

/// Request to load a model.
public struct ModelLoadRequest: Codable, Sendable, Equatable {
    /// The model identifier to load.
    public let model: String

    /// Optional configuration overrides for loading.
    public let config: ModelLoadConfig?

    /// Creates a model load request.
    public init(model: String, config: ModelLoadConfig? = nil) {
        self.model = model
        self.config = config
    }
}

/// Configuration for loading a model.
public struct ModelLoadConfig: Codable, Sendable, Equatable {
    /// The number of GPU layers to offload (if applicable).
    public let gpuLayers: Int?

    /// The context size to use.
    public let contextSize: Int?

    /// The number of threads to use for inference.
    public let threads: Int?

    /// Whether to use memory locking (mlock).
    public let useMlock: Bool?

    /// Whether to use memory mapping (mmap).
    public let useMmap: Bool?

    /// Batch size for prompt processing.
    public let batchSize: Int?

    /// The number of CPU threads to use.
    public let cpuThreads: Int?

    /// The NUMA policy to use.
    public let numaPolicy: String?

    /// Additional backend-specific options.
    public let extra: [String: String]?

    enum CodingKeys: String, CodingKey {
        case gpuLayers = "gpu_layers"
        case contextSize = "context_size"
        case threads
        case useMlock = "use_mlock"
        case useMmap = "use_mmap"
        case batchSize = "batch_size"
        case cpuThreads = "cpu_threads"
        case numaPolicy = "numa_policy"
        case extra
    }

    /// Creates a model load configuration.
    public init(
        gpuLayers: Int? = nil,
        contextSize: Int? = nil,
        threads: Int? = nil,
        useMlock: Bool? = nil,
        useMmap: Bool? = nil,
        batchSize: Int? = nil,
        cpuThreads: Int? = nil,
        numaPolicy: String? = nil,
        extra: [String: String]? = nil
    ) {
        self.gpuLayers = gpuLayers
        self.contextSize = contextSize
        self.threads = threads
        self.useMlock = useMlock
        self.useMmap = useMmap
        self.batchSize = batchSize
        self.cpuThreads = cpuThreads
        self.numaPolicy = numaPolicy
        self.extra = extra
    }
}

/// Response from a model load or unload operation.
public struct ModelOperationResponse: Codable, Sendable, Equatable {
    /// Whether the operation was successful.
    public let success: Bool

    /// The model identifier the operation was performed on.
    public let model: String

    /// A human-readable message about the operation.
    public let message: String?

    /// The time taken for the operation in milliseconds.
    public let durationMs: Double?

    enum CodingKeys: String, CodingKey {
        case success, model, message
        case durationMs = "duration_ms"
    }
}

/// Response from listing models.
public struct ModelListResponse: Codable, Sendable, Equatable {
    /// The list of available models.
    public let models: [ModelInfo]

    /// The total number of models available.
    public let total: Int

    /// Creates a model list response.
    public init(models: [ModelInfo], total: Int) {
        self.models = models
        self.total = total
    }
}

// MARK: - Health & Status

/// Response from the health check endpoint.
public struct HealthResponse: Codable, Sendable, Equatable {
    /// Whether the daemon is healthy.
    public let healthy: Bool

    /// The daemon uptime in seconds.
    public let uptimeSeconds: Double?

    /// The daemon version.
    public let version: String?

    /// The number of active connections.
    public let activeConnections: Int?

    /// The memory usage of the daemon in bytes.
    public let memoryUsageBytes: Int64?

    enum CodingKeys: String, CodingKey {
        case healthy
        case uptimeSeconds = "uptime_seconds"
        case version
        case activeConnections = "active_connections"
        case memoryUsageBytes = "memory_usage_bytes"
    }
}

/// Detailed daemon status information.
public struct DaemonStatus: Codable, Sendable, Equatable {
    /// The daemon version.
    public let version: String

    /// The daemon's current state.
    public let state: DaemonState

    /// List of loaded models.
    public let loadedModels: [ModelInfo]

    /// The total number of inferences served.
    public let totalInferences: Int64?

    /// The number of active inference requests.
    public let activeInferences: Int?

    /// The total memory used by loaded models.
    public let modelMemoryBytes: Int64?

    /// The system memory status.
    public let systemMemory: SystemMemory?

    /// The daemon's configuration.
    public let config: [String: String]?

    enum CodingKeys: String, CodingKey {
        case version, state
        case loadedModels = "loaded_models"
        case totalInferences = "total_inferences"
        case activeInferences = "active_inferences"
        case modelMemoryBytes = "model_memory_bytes"
        case systemMemory = "system_memory"
        case config
    }
}

/// The current state of the daemon.
public enum DaemonState: String, Codable, Sendable {
    /// The daemon is starting up.
    case starting
    /// The daemon is ready to accept requests.
    case ready
    /// The daemon is busy processing requests.
    case busy
    /// The daemon is shutting down.
    case shuttingDown
    /// The daemon encountered an error.
    case error
    /// The daemon state is unknown.
    case unknown
}

/// System memory information.
public struct SystemMemory: Codable, Sendable, Equatable {
    /// Total physical memory in bytes.
    public let totalBytes: Int64

    /// Available (free) memory in bytes.
    public let availableBytes: Int64

    /// Used memory in bytes.
    public let usedBytes: Int64

    /// Memory usage as a percentage (0.0 - 1.0).
    public let usagePercent: Double

    enum CodingKeys: String, CodingKey {
        case totalBytes = "total_bytes"
        case availableBytes = "available_bytes"
        case usedBytes = "used_bytes"
        case usagePercent = "usage_percent"
    }
}

// MARK: - Context Store / Retrieve

/// A request to store context data on the daemon.
public struct ContextStoreRequest: Codable, Sendable, Equatable {
    /// The key to store the context under.
    public let key: String

    /// The context data (must be valid JSON).
    public let value: [String: AnyCodable]

    /// Optional time-to-live in seconds.
    public let ttlSeconds: Int?

    /// Whether to overwrite an existing value.
    public let overwrite: Bool?

    enum CodingKeys: String, CodingKey {
        case key, value
        case ttlSeconds = "ttl_seconds"
        case overwrite
    }

    /// Creates a context store request.
    /// - Parameters:
    ///   - key: The storage key.
    ///   - value: The context data.
    ///   - ttlSeconds: Optional TTL in seconds.
    ///   - overwrite: Whether to overwrite existing data.
    public init(
        key: String,
        value: [String: AnyCodable],
        ttlSeconds: Int? = nil,
        overwrite: Bool? = nil
    ) {
        self.key = key
        self.value = value
        self.ttlSeconds = ttlSeconds
        self.overwrite = overwrite
    }
}

/// Response from a context store operation.
public struct ContextStoreResponse: Codable, Sendable, Equatable {
    /// Whether the operation was successful.
    public let success: Bool

    /// The key that was stored.
    public let key: String

    /// A human-readable message.
    public let message: String?
}

/// A request to retrieve context data from the daemon.
public struct ContextRetrieveRequest: Codable, Sendable, Equatable {
    /// The key to retrieve.
    public let key: String

    /// Creates a context retrieve request.
    public init(key: String) {
        self.key = key
    }
}

/// Response from a context retrieve operation.
public struct ContextRetrieveResponse: Codable, Sendable, Equatable {
    /// Whether the retrieval was successful.
    public let success: Bool

    /// The key that was retrieved.
    public let key: String

    /// The stored context data.
    public let value: [String: AnyCodable]?

    /// The time-to-live remaining in seconds.
    public let ttlRemaining: Int?

    /// The timestamp when the context was created.
    public let createdAt: Date?

    /// The timestamp when the context was last accessed.
    public let accessedAt: Date?

    enum CodingKeys: String, CodingKey {
        case success, key, value
        case ttlRemaining = "ttl_remaining"
        case createdAt = "created_at"
        case accessedAt = "accessed_at"
    }
}

// MARK: - Generic NDJSON Frame

/// A generic NDJSON frame that wraps all request/response types.
///
/// Every message sent over the TCP transport is a JSON object
/// wrapped in an `NdjsonFrame` that identifies the message type
/// so the receiver can dispatch it correctly.
public struct NdjsonFrame: Codable, Sendable {
    /// The message type identifier.
    public let type: String

    /// The request identifier for correlating responses.
    public let requestId: String?

    /// The timestamp of the message.
    public let timestamp: Date?

    /// The error information, if this is an error response.
    public let error: FrameError?

    /// The payload data (decoded from the raw JSON).
    public let payload: [String: AnyCodable]

    /// Creates an NDJSON frame.
    public init(
        type: String,
        requestId: String? = nil,
        timestamp: Date? = nil,
        error: FrameError? = nil,
        payload: [String: AnyCodable] = [:]
    ) {
        self.type = type
        self.requestId = requestId
        self.timestamp = timestamp
        self.error = error
        self.payload = payload
    }

    enum CodingKeys: String, CodingKey {
        case type
        case requestId = "request_id"
        case timestamp, error
        case payload
    }
}

/// Error information within an NDJSON frame.
public struct FrameError: Codable, Sendable, Equatable {
    /// The error code.
    public let code: String

    /// A human-readable error message.
    public let message: String

    /// Additional error details.
    public let details: String?

    /// Creates frame error info.
    public init(code: String, message: String, details: String? = nil) {
        self.code = code
        self.message = message
        self.details = details
    }
}

// MARK: - AnyCodable

/// A type-erased Codable wrapper for handling heterogeneous JSON values.
///
/// `AnyCodable` can represent any JSON-compatible value: string, number,
/// boolean, null, array, or dictionary. It is used in contexts where the
/// exact schema of a value is not known at compile time.
public struct AnyCodable: Codable, Sendable, Equatable {
    /// The underlying value.
    public let value: Any

    /// Creates an AnyCodable wrapping the given value.
    public init(_ value: Any) {
        self.value = value
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            value = AnyCodableNull.null
        } else if let bool = try? container.decode(Bool.self) {
            value = bool
        } else if let int = try? container.decode(Int.self) {
            value = int
        } else if let double = try? container.decode(Double.self) {
            value = double
        } else if let string = try? container.decode(String.self) {
            value = string
        } else if let array = try? container.decode([AnyCodable].self) {
            value = array.map { $0.value }
        } else if let dict = try? container.decode([String: AnyCodable].self) {
            value = dict.mapValues { $0.value }
        } else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "AnyCodable value cannot be decoded"
            )
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch value {
        case is AnyCodableNull:
            try container.encodeNil()
        case let bool as Bool:
            try container.encode(bool)
        case let int as Int:
            try container.encode(int)
        case let int8 as Int8:
            try container.encode(Int(int8))
        case let int16 as Int16:
            try container.encode(Int(int16))
        case let int32 as Int32:
            try container.encode(Int(int32))
        case let int64 as Int64:
            try container.encode(Int(int64))
        case let uint as UInt:
            try container.encode(Int(uint))
        case let uint8 as UInt8:
            try container.encode(Int(uint8))
        case let uint16 as UInt16:
            try container.encode(Int(uint16))
        case let uint32 as UInt32:
            try container.encode(Int(uint32))
        case let uint64 as UInt64:
            try container.encode(Int(uint64))
        case let float as Float:
            try container.encode(Double(float))
        case let double as Double:
            try container.encode(double)
        case let string as String:
            try container.encode(string)
        case let array as [Any]:
            let codableArray = array.map { AnyCodable($0) }
            try container.encode(codableArray)
        case let dict as [String: Any]:
            let codableDict = dict.mapValues { AnyCodable($0) }
            try container.encode(codableDict)
        default:
            let context = EncodingError.Context(
                codingPath: container.codingPath,
                debugDescription: "AnyCodable value cannot be encoded: \(type(of: value))"
            )
            throw EncodingError.invalidValue(value, context)
        }
    }

    public static func == (lhs: AnyCodable, rhs: AnyCodable) -> Bool {
        switch (lhs.value, rhs.value) {
        case is (AnyCodableNull, AnyCodableNull):
            return true
        case let (l as Bool, r as Bool):
            return l == r
        case let (l as Int, r as Int):
            return l == r
        case let (l as Double, r as Double):
            return l == r
        case let (l as String, r as String):
            return l == r
        case let (l as [Any], r as [Any]):
            return AnyCodable.anyArraysEqual(l, r)
        case let (l as [String: Any], r as [String: Any]):
            return AnyCodable.anyDictionariesEqual(l, r)
        default:
            return false
        }
    }

    private static func anyArraysEqual(_ lhs: [Any], _ rhs: [Any]) -> Bool {
        guard lhs.count == rhs.count else { return false }
        return zip(lhs, rhs).allSatisfy {
            AnyCodable($0.0) == AnyCodable($0.1)
        }
    }

    private static func anyDictionariesEqual(
        _ lhs: [String: Any], _ rhs: [String: Any]
    ) -> Bool {
        guard lhs.keys == rhs.keys else { return false }
        return lhs.allSatisfy { key, value in
            AnyCodable(value) == AnyCodable(rhs[key] as Any)
        }
    }
}

/// Sentinel type representing a JSON null value in AnyCodable.
public struct AnyCodableNull: Sendable, Equatable {
    /// The shared null instance.
    public static let `null` = AnyCodableNull()
}

// MARK: - Request ID Generation

/// A type that generates unique request identifiers.
public protocol RequestIDGenerator: Sendable {
    /// Generates a new unique request identifier.
    func generate() -> String
}

/// The default request ID generator using UUIDs.
public struct DefaultRequestIDGenerator: RequestIDGenerator {
    /// Creates a new generator.
    public init() {}

    /// Generates a UUID-based request identifier.
    public func generate() -> String {
        UUID().uuidString.lowercased()
    }
}

// MARK: - Request Method

/// The set of supported request methods for the NDJSON protocol.
public enum RequestMethod: String, Codable, Sendable {
    case connect
    case infer
    case inferStream = "infer_stream"
    case modelList = "model_list"
    case modelLoad = "model_load"
    case modelUnload = "model_unload"
    case health
    case status
    case contextStore = "context_store"
    case contextRetrieve = "context_retrieve"
    case disconnect

    /// The method name as sent over the wire.
    public var wireValue: String { rawValue }
}

// MARK: - Event Loop Metrics

/// Performance metrics collected by the SDK.
public struct SDKMetrics: Codable, Sendable, Equatable {
    /// The number of bytes sent over the wire.
    public let bytesSent: Int64

    /// The number of bytes received.
    public let bytesReceived: Int64

    /// The number of requests sent.
    public let requestsSent: Int64

    /// The number of responses received.
    public let responsesReceived: Int64

    /// The number of errors encountered.
    public let errors: Int64

    /// The number of reconnections performed.
    public let reconnections: Int

    /// The average round-trip time in milliseconds.
    public let averageRttMs: Double?

    enum CodingKeys: String, CodingKey {
        case bytesSent = "bytes_sent"
        case bytesReceived = "bytes_received"
        case requestsSent = "requests_sent"
        case responsesReceived = "responses_received"
        case errors
        case reconnections
        case averageRttMs = "average_rtt_ms"
    }
}

// MARK: - Configuration

/// Global configuration for the Ainos SDK client.
public struct AinosClientConfig: Sendable, Equatable {
    /// The host address of the daemon.
    public var host: String

    /// The port of the daemon.
    public var port: Int

    /// The authentication token.
    public var token: String?

    /// The connection timeout in seconds.
    public var connectionTimeout: TimeInterval

    /// The read timeout in seconds.
    public var readTimeout: TimeInterval

    /// The maximum number of reconnection attempts.
    public var maxReconnectAttempts: Int

    /// The delay between reconnection attempts in seconds.
    public var reconnectDelay: TimeInterval

    /// Whether to enable verbose logging.
    public var verbose: Bool

    /// The request ID generator.
    public var requestIDGenerator: RequestIDGenerator

    /// Creates a client configuration.
    /// - Parameters:
    ///   - host: The daemon host (default: "127.0.0.1").
    ///   - port: The daemon port (default: 9500).
    ///   - token: The authentication token.
    ///   - connectionTimeout: Connection timeout in seconds (default: 10).
    ///   - readTimeout: Read timeout in seconds (default: 60).
    ///   - maxReconnectAttempts: Max reconnection attempts (default: 3).
    ///   - reconnectDelay: Delay between reconnects in seconds (default: 1.0).
    ///   - verbose: Enable verbose logging (default: false).
    ///   - requestIDGenerator: Custom request ID generator.
    public init(
        host: String = "127.0.0.1",
        port: Int = 9500,
        token: String? = nil,
        connectionTimeout: TimeInterval = 10,
        readTimeout: TimeInterval = 60,
        maxReconnectAttempts: Int = 3,
        reconnectDelay: TimeInterval = 1.0,
        verbose: Bool = false,
        requestIDGenerator: RequestIDGenerator = DefaultRequestIDGenerator()
    ) {
        self.host = host
        self.port = port
        self.token = token
        self.connectionTimeout = connectionTimeout
        self.readTimeout = readTimeout
        self.maxReconnectAttempts = maxReconnectAttempts
        self.reconnectDelay = reconnectDelay
        self.verbose = verbose
        self.requestIDGenerator = requestIDGenerator
    }

    public static func == (lhs: AinosClientConfig, rhs: AinosClientConfig) -> Bool {
        lhs.host == rhs.host &&
        lhs.port == rhs.port &&
        lhs.token == rhs.token &&
        lhs.connectionTimeout == rhs.connectionTimeout &&
        lhs.readTimeout == rhs.readTimeout &&
        lhs.maxReconnectAttempts == rhs.maxReconnectAttempts &&
        lhs.reconnectDelay == rhs.reconnectDelay &&
        lhs.verbose == rhs.verbose
    }
}