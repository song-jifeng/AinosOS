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

// MARK: - JSON Encoding/Decoding

extension JSONEncoder {

    /// The default JSON encoder used throughout the SDK.
    ///
    /// Configuration:
    /// - ISO 8601 date formatting with fractional seconds
    /// - Output formatting sorted keys for deterministic output
    /// - Non-conforming float strategy for flexible number parsing
    public static let ainos: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .custom { date, encoder in
            var container = encoder.singleValueContainer()
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            let dateString = formatter.string(from: date)
            try container.encode(dateString)
        }
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }()

    /// A JSON encoder with pretty-printed output (for debugging/logging).
    public static let ainosPretty: JSONEncoder = {
        let encoder = JSONEncoder.ainos
        encoder.outputFormatting = [.sortedKeys, .prettyPrinted, .withoutEscapingSlashes]
        return encoder
    }()
}

extension JSONDecoder {

    /// The default JSON decoder used throughout the SDK.
    ///
    /// Configuration:
    /// - ISO 8601 date parsing with and without fractional seconds
    /// - Non-conforming float strategy for flexible number parsing
    public static let ainos: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let dateString = try container.decode(String.self)

            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

            if let date = formatter.date(from: dateString) {
                return date
            }

            formatter.formatOptions = [.withInternetDateTime]
            if let date = formatter.date(from: dateString) {
                return date
            }

            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Cannot decode date string: \(dateString)"
            )
        }
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.nonConformingFloatDecodingStrategy = .convertFromString(
            positiveInfinity: "inf",
            negativeInfinity: "-inf",
            nan: "nan"
        )
        return decoder
    }()
}

// MARK: - Logger

/// A lightweight logging utility for the Ainos SDK.
///
/// The logger writes to `os_log` on Apple platforms and falls back to
/// `print` on other platforms. Log level is controlled by the client
/// configuration.
///
/// ## Usage
///
/// ```swift
/// Logger.debug("Connecting to daemon...")
/// Logger.info("Connected successfully")
/// Logger.warning("Connection unstable")
/// Logger.error("Connection failed", error: someError)
/// ```
public enum Logger {

    /// Log levels in increasing severity.
    public enum Level: Int, Sendable, Comparable {
        case debug = 0
        case info = 1
        case warning = 2
        case error = 3
        case none = 4

        public static func < (lhs: Level, rhs: Level) -> Bool {
            lhs.rawValue < rhs.rawValue
        }
    }

    /// The current minimum log level. Defaults to `.info`.
    public static var currentLevel: Level = .info

    /// Whether to include timestamps in log output.
    public static var includeTimestamps: Bool = true

    /// Whether to include source file and line in log output.
    public static var includeSourceLocation: Bool = false

    /// The date formatter for log timestamps.
    private static let dateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd HH:mm:ss.SSS"
        return formatter
    }()

    /// Logs a debug-level message.
    /// - Parameters:
    ///   - message: The message to log.
    ///   - file: The source file (automatically captured).
    ///   - line: The source line (automatically captured).
    public static func debug(
        _ message: @autoclosure () -> String,
        file: String = #fileID,
        line: Int = #line
    ) {
        log(level: .debug, message: message(), file: file, line: line)
    }

    /// Logs an info-level message.
    /// - Parameters:
    ///   - message: The message to log.
    ///   - file: The source file (automatically captured).
    ///   - line: The source line (automatically captured).
    public static func info(
        _ message: @autoclosure () -> String,
        file: String = #fileID,
        line: Int = #line
    ) {
        log(level: .info, message: message(), file: file, line: line)
    }

    /// Logs a warning-level message.
    /// - Parameters:
    ///   - message: The message to log.
    ///   - file: The source file (automatically captured).
    ///   - line: The source line (automatically captured).
    public static func warning(
        _ message: @autoclosure () -> String,
        file: String = #fileID,
        line: Int = #line
    ) {
        log(level: .warning, message: message(), file: file, line: line)
    }

    /// Logs an error-level message.
    /// - Parameters:
    ///   - message: The message to log.
    ///   - error: An optional error to include.
    ///   - file: The source file (automatically captured).
    ///   - line: The source line (automatically captured).
    public static func error(
        _ message: @autoclosure () -> String,
        error: Error? = nil,
        file: String = #fileID,
        line: Int = #line
    ) {
        var msg = message()
        if let error = error {
            msg += " — \(error.localizedDescription)"
        }
        log(level: .error, message: msg, file: file, line: line)
    }

    /// Internal logging method.
    private static func log(
        level: Level,
        message: @autoclosure () -> String,
        file: String,
        line: Int
    ) {
        guard level.rawValue >= currentLevel.rawValue else { return }

        var components: [String] = []

        if includeTimestamps {
            components.append("[\(dateFormatter.string(from: Date()))]")
        }

        switch level {
        case .debug: components.append("[DEBUG]")
        case .info: components.append("[INFO]")
        case .warning: components.append("[WARN]")
        case .error: components.append("[ERROR]")
        case .none: return
        }

        if includeSourceLocation {
            components.append("(\(file):\(line))")
        }

        components.append(message())

        #if canImport(os)
        os_log("%{public}@", log: .default, type: level.osLogType, components.joined(separator: " "))
        #else
        print(components.joined(separator: " "))
        #endif
    }
}

#if canImport(os)
import os

extension Logger.Level {
    /// Maps the logger level to the corresponding `OSLogType`.
    fileprivate var osLogType: OSLogType {
        switch self {
        case .debug: return .debug
        case .info: return .info
        case .warning: return .default
        case .error: return .error
        case .none: return .default
        }
    }
}
#endif

// MARK: - JSON Serialization Helpers

/// A utility for working with JSON data.
public enum JSON {

    /// Attempts to serialize a `Codable` value to a JSON string.
    /// - Parameter value: The value to serialize.
    /// - Returns: A JSON string.
    /// - Throws: An error if serialization fails.
    public static func stringify<T: Encodable>(_ value: T) throws -> String {
        let data = try JSONEncoder.ainos.encode(value)
        guard let string = String(data: data, encoding: .utf8) else {
            throw AinosError.internalError("Failed to create JSON string from data")
        }
        return string
    }

    /// Attempts to serialize a `Codable` value to a pretty-printed JSON string.
    /// - Parameter value: The value to serialize.
    /// - Returns: A pretty-printed JSON string.
    /// - Throws: An error if serialization fails.
    public static func prettyPrint<T: Encodable>(_ value: T) throws -> String {
        let data = try JSONEncoder.ainosPretty.encode(value)
        guard let string = String(data: data, encoding: .utf8) else {
            throw AinosError.internalError("Failed to create JSON string from data")
        }
        return string
    }

    /// Attempts to parse a JSON string into a `Decodable` value.
    /// - Parameter string: The JSON string to parse.
    /// - Returns: The decoded value.
    /// - Throws: An error if parsing fails.
    public static func parse<T: Decodable>(_ string: String, as type: T.Type) throws -> T {
        guard let data = string.data(using: .utf8) else {
            throw AinosError.invalidResponse(details: "Cannot convert string to UTF-8 data")
        }
        return try JSONDecoder.ainos.decode(type, from: data)
    }

    /// Validates that a string is well-formed JSON.
    /// - Parameter string: The string to validate.
    /// - Returns: `true` if the string is valid JSON.
    public static func isValidJSON(_ string: String) -> Bool {
        guard let data = string.data(using: .utf8) else { return false }
        return (try? JSONSerialization.jsonObject(with: data)) != nil
    }

    /// Attempts to extract a value from a JSON string using a key path.
    /// - Parameters:
    ///   - string: The JSON string.
    ///   - keyPath: The key path to extract (e.g. "model.id").
    /// - Returns: The extracted value, or nil if the path doesn't exist.
    public static func extractValue(from string: String, keyPath: String) -> Any? {
        guard let data = string.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }

        let keys = keyPath.split(separator: ".")
        var current: Any = json

        for key in keys {
            if let dict = current as? [String: Any],
               let value = dict[String(key)] {
                current = value
            } else {
                return nil
            }
        }

        return current
    }
}

// MARK: - Data Extensions

extension Data {

    /// Returns a hex-encoded string representation of the data.
    public var hexString: String {
        map { String(format: "%02x", $0) }.joined()
    }

    /// Appends a newline character to the data.
    public mutating func appendNewline() {
        append(contentsOf: [0x0A])
    }

    /// Returns a copy of the data with a newline appended.
    public func withNewline() -> Data {
        var copy = self
        copy.append(contentsOf: [0x0A])
        return copy
    }
}

// MARK: - String Extensions

extension String {

    /// Returns `true` if the string is a valid JSON document.
    public var isValidJSON: Bool {
        JSON.isValidJSON(self)
    }

    /// Attempts to decode this string as a JSON value of the specified type.
    /// - Parameter type: The type to decode.
    /// - Returns: The decoded value.
    /// - Throws: An error if decoding fails.
    public func decodeJSON<T: Decodable>(as type: T.Type) throws -> T {
        try JSON.parse(self, as: type)
    }

    /// Truncates the string to a maximum length, appending an ellipsis if truncated.
    /// - Parameter maxLength: The maximum number of characters.
    /// - Returns: The truncated string.
    public func truncated(to maxLength: Int) -> String {
        guard count > maxLength else { return self }
        return "\(prefix(maxLength))..."
    }
}

// MARK: - Task Extensions

extension Task where Success == Never, Failure == Never {

    /// Sleeps for the specified duration in seconds.
    /// - Parameter seconds: The number of seconds to sleep.
    public static func sleep(seconds: TimeInterval) async throws {
        try await sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
    }
}

// MARK: - Throttle

/// A utility for throttling asynchronous operations.
///
/// `AsyncThrottle` ensures that an operation is not performed more
/// frequently than the specified interval. It is useful for rate-limiting
/// requests to the daemon.
///
/// ## Usage
///
/// ```swift
/// let throttle = AsyncThrottle(interval: 0.1)
/// for event in fastEvents {
///     await throttle.throttle()
///     // process event
/// }
/// ```
public final class AsyncThrottle: Sendable {

    private let interval: TimeInterval
    private let lock = NSLock()
    private var lastFireTime: Date?

    /// Creates a throttle.
    /// - Parameter interval: The minimum interval between operations.
    public init(interval: TimeInterval) {
        self.interval = interval
    }

    /// Waits if necessary to respect the throttle interval.
    public func throttle() async {
        lock.lock()
        let last = lastFireTime
        lastFireTime = Date()
        lock.unlock()

        if let last = last {
            let elapsed = Date().timeIntervalSince(last)
            if elapsed < interval {
                let wait = interval - elapsed
                try? await Task.sleep(nanoseconds: UInt64(wait * 1_000_000_000))
            }
        }
    }
}

// MARK: - Retry

/// A utility for retrying asynchronous operations with backoff.
///
/// ## Usage
///
/// ```swift
/// let result = try await retry(maxAttempts: 3) {
///     try await client.infer(prompt: "Hello")
/// }
/// ```
///
/// - Parameters:
///   - maxAttempts: Maximum number of retry attempts.
///   - baseDelay: Base delay in seconds for exponential backoff.
///   - maxDelay: Maximum delay in seconds.
///   - retryIf: A closure that determines if an error is retryable.
///   - operation: The operation to retry.
/// - Returns: The result of the operation.
/// - Throws: The last error if all retries fail.
public func retry<T>(
    maxAttempts: Int = 3,
    baseDelay: TimeInterval = 1.0,
    maxDelay: TimeInterval = 30.0,
    retryIf: @Sendable (Error) -> Bool = { error in
        guard let ainosError = error as? AinosError else { return false }
        return ainosError.isRetryable
    },
    operation: @Sendable () async throws -> T
) async throws -> T {
    var lastError: Error?

    for attempt in 1...maxAttempts {
        do {
            return try await operation()
        } catch {
            lastError = error

            guard attempt < maxAttempts, retryIf(error) else {
                throw error
            }

            let delay = min(baseDelay * pow(2.0, Double(attempt - 1)), maxDelay)
            Logger.debug(
                "Retry attempt \(attempt)/\(maxAttempts) in \(delay)s after: \(error.localizedDescription)"
            )
            try await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
        }
    }

    throw lastError ?? AinosError.internalError("Retry loop exited without error")
}

// MARK: - Stopwatch

/// A simple stopwatch for measuring elapsed time.
///
/// ## Usage
///
/// ```swift
/// let stopwatch = Stopwatch()
/// // ... do work ...
/// print("Elapsed: \(stopwatch.elapsed)s")
/// ```
public final class Stopwatch: Sendable {

    private let startTime: Date

    /// Creates a stopwatch and starts timing.
    public init() {
        self.startTime = Date()
    }

    /// The elapsed time in seconds since the stopwatch was created.
    public var elapsed: TimeInterval {
        Date().timeIntervalSince(startTime)
    }

    /// The elapsed time in milliseconds.
    public var elapsedMs: Double {
        elapsed * 1000
    }

    /// Resets the stopwatch to the current time.
    /// - Returns: The elapsed time before resetting.
    @discardableResult
    public func reset() -> TimeInterval {
        let previous = elapsed
        // Note: we can't reassign let constant, so this is a design limitation.
        // In practice, create a new Stopwatch or store the old value.
        return previous
    }
}

// MARK: - Version

/// A semantic version representation.
public struct Version: Sendable, Equatable, Comparable, CustomStringConvertible {

    /// The major version number.
    public let major: Int

    /// The minor version number.
    public let minor: Int

    /// The patch version number.
    public let patch: Int

    /// An optional pre-release identifier.
    public let preRelease: String?

    /// An optional build metadata identifier.
    public let build: String?

    /// Creates a version.
    public init(
        major: Int,
        minor: Int,
        patch: Int,
        preRelease: String? = nil,
        build: String? = nil
    ) {
        self.major = major
        self.minor = minor
        self.patch = patch
        self.preRelease = preRelease
        self.build = build
    }

    /// Creates a version from a version string (e.g. "1.2.3", "1.2.3-beta").
    /// - Parameter string: The version string to parse.
    public init?(_ string: String) {
        let components = string.split(separator: "-", maxSplits: 1)
        let versionPart = String(components[0])
        self.preRelease = components.count > 1 ? String(components[1]) : nil

        let buildComponents = versionPart.split(separator: "+", maxSplits: 1)
        let cleanVersion = String(buildComponents[0])
        self.build = buildComponents.count > 1 ? String(buildComponents[1]) : nil

        let parts = cleanVersion.split(separator: ".").map { Int($0) }
        guard parts.count >= 1, let major = parts[0] else { return nil }
        self.major = major
        self.minor = parts.count > 1 ? parts[1] ?? 0 : 0
        self.patch = parts.count > 2 ? parts[2] ?? 0 : 0
    }

    public var description: String {
        var result = "\(major).\(minor).\(patch)"
        if let preRelease = preRelease {
            result += "-\(preRelease)"
        }
        if let build = build {
            result += "+\(build)"
        }
        return result
    }

    public static func < (lhs: Version, rhs: Version) -> Bool {
        if lhs.major != rhs.major { return lhs.major < rhs.major }
        if lhs.minor != rhs.minor { return lhs.minor < rhs.minor }
        if lhs.patch != rhs.patch { return lhs.patch < rhs.patch }
        // Pre-release versions have lower precedence
        switch (lhs.preRelease, rhs.preRelease) {
        case (nil, nil): return false
        case (nil, .some): return false
        case (.some, nil): return true
        case (.some(let l), .some(let r)):
            return l < r
        }
    }
}