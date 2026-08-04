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

// MARK: - AinosError

/// The root error type for all Ainos SDK operations.
///
/// Every error thrown by the SDK is an `AinosError`, which provides
/// a structured description, an optional underlying error cause, and
/// a machine-readable code for programmatic handling.
///
/// ## Error Handling
///
/// ```swift
/// do {
///     let result = try await client.infer(prompt: "Hello")
/// } catch let error as AinosError {
///     switch error.code {
///     case .connectionRefused:
///         // Retry or show a "Daemon not running" message
///     case .authenticationFailed:
///         // Prompt for a new token
///     default:
///         // General fallback
///     }
/// } catch {
///     // Non-Ainos error (e.g. cancelled)
/// }
/// ```
public struct AinosError: Error, Sendable, CustomStringConvertible {

    /// Machine-readable error codes for programmatic handling.
    public struct Code: Sendable, Hashable, RawRepresentable, ExpressibleByStringLiteral {

        public typealias RawValue = String

        public let rawValue: String

        public init(rawValue: String) {
            self.rawValue = rawValue
        }

        public init(stringLiteral value: StringLiteralType) {
            self.rawValue = value
        }

        // MARK: - Connection Errors

        /// Failed to connect to the daemon at the specified host and port.
        public static let connectionFailed: Code = "connection_failed"

        /// The connection was refused by the remote host (daemon not running).
        public static let connectionRefused: Code = "connection_refused"

        /// The connection timed out during initial TCP handshake.
        public static let connectionTimedOut: Code = "connection_timed_out"

        /// The connection was unexpectedly closed by the remote peer.
        public static let connectionClosed: Code = "connection_closed"

        /// The connection was reset by the remote peer.
        public static let connectionReset: Code = "connection_reset"

        // MARK: - Authentication Errors

        /// Authentication failed (invalid or expired token).
        public static let authenticationFailed: Code = "authentication_failed"

        /// No authentication token was provided.
        public static let authenticationMissing: Code = "authentication_missing"

        /// The token has expired and could not be refreshed.
        public static let tokenExpired: Code = "token_expired"

        /// Token refresh failed.
        public static let tokenRefreshFailed: Code = "token_refresh_failed"

        // MARK: - Request Errors

        /// The request was malformed and could not be serialized.
        public static let invalidRequest: Code = "invalid_request"

        /// The request parameters failed validation.
        public static let validationError: Code = "validation_error"

        /// The request was cancelled before completion.
        public static let requestCancelled: Code = "request_cancelled"

        // MARK: - Response Errors

        /// The response from the daemon could not be parsed.
        public static let invalidResponse: Code = "invalid_response"

        /// The response contained an unexpected type or format.
        public static let unexpectedResponse: Code = "unexpected_response"

        /// The response was truncated or incomplete.
        public static let truncatedResponse: Code = "truncated_response"

        // MARK: - Model Errors

        /// The requested model was not found.
        public static let modelNotFound: Code = "model_not_found"

        /// The model failed to load.
        public static let modelLoadFailed: Code = "model_load_failed"

        /// The model failed to unload.
        public static let modelUnloadFailed: Code = "model_unload_failed"

        /// The model is not loaded and cannot be used for inference.
        public static let modelNotLoaded: Code = "model_not_loaded"

        /// The model is already loaded with the same configuration.
        public static let modelAlreadyLoaded: Code = "model_already_loaded"

        // MARK: - Inference Errors

        /// Inference failed with an internal error.
        public static let inferenceFailed: Code = "inference_failed"

        /// Inference timed out.
        public static let inferenceTimedOut: Code = "inference_timed_out"

        /// The inference context length was exceeded.
        public static let contextOverflow: Code = "context_overflow"

        /// The inference was cancelled by the server.
        public static let inferenceCancelled: Code = "inference_cancelled"

        // MARK: - Context Errors

        /// Context store operation failed.
        public static let contextStoreFailed: Code = "context_store_failed"

        /// Context retrieve operation failed.
        public static let contextRetrieveFailed: Code = "context_retrieve_failed"

        /// The requested context key was not found.
        public static let contextNotFound: Code = "context_not_found"

        // MARK: - Internal Errors

        /// An internal SDK error occurred.
        public static let internalError: Code = "internal_error"

        /// An I/O error occurred on the transport layer.
        public static let ioError: Code = "io_error"

        /// The operation is not supported by the connected daemon version.
        public static let notSupported: Code = "not_supported"

        /// The resource limit was exceeded.
        public static let rateLimited: Code = "rate_limited"
    }

    // MARK: Properties

    /// The machine-readable error code.
    public let code: Code

    /// A human-readable description of the error.
    public let description: String

    /// The underlying error that caused this error, if any.
    public let underlyingError: Error?

    /// The file where the error originated.
    public let file: String

    /// The line where the error originated.
    public let line: Int

    // MARK: Initializers

    /// Creates a new Ainos error.
    /// - Parameters:
    ///   - code: The machine-readable error code.
    ///   - description: A human-readable description.
    ///   - underlyingError: An optional underlying error.
    ///   - file: The source file (automatically captured).
    ///   - line: The source line (automatically captured).
    public init(
        code: Code,
        description: String,
        underlyingError: Error? = nil,
        file: String = #fileID,
        line: Int = #line
    ) {
        self.code = code
        self.description = description
        self.underlyingError = underlyingError
        self.file = file
        self.line = line
    }

    // MARK: Helpers

    /// Returns `true` if the error is related to connectivity issues.
    public var isConnectionError: Bool {
        switch code {
        case .connectionFailed, .connectionRefused, .connectionTimedOut,
             .connectionClosed, .connectionReset, .ioError:
            return true
        default:
            return false
        }
    }

    /// Returns `true` if the error is related to authentication.
    public var isAuthenticationError: Bool {
        switch code {
        case .authenticationFailed, .authenticationMissing,
             .tokenExpired, .tokenRefreshFailed:
            return true
        default:
            return false
        }
    }

    /// Returns `true` if the operation can be safely retried.
    public var isRetryable: Bool {
        switch code {
        case .connectionFailed, .connectionRefused, .connectionTimedOut,
             .connectionClosed, .connectionReset, .rateLimited,
             .inferenceTimedOut:
            return true
        default:
            return false
        }
    }
}

// MARK: - Equatable & Hashable

extension AinosError: Equatable {
    public static func == (lhs: AinosError, rhs: AinosError) -> Bool {
        lhs.code == rhs.code &&
        lhs.description == rhs.description
    }
}

extension AinosError: Hashable {
    public func hash(into hasher: inout Hasher) {
        hasher.combine(code)
        hasher.combine(description)
    }
}

// MARK: - LocalizedError

extension AinosError: LocalizedError {
    public var errorDescription: String? { description }
    public var failureReason: String? {
        switch code {
        case .connectionRefused:
            return "The Ainos daemon is not running or is not accepting connections."
        case .authenticationFailed:
            return "The provided authentication token was rejected."
        case .modelNotFound:
            return "The specified model identifier does not match any available model."
        default:
            return nil
        }
    }
    public var recoverySuggestion: String? {
        switch code {
        case .connectionRefused:
            return "Ensure the Ainos daemon is running on the target host and port."
        case .authenticationFailed:
            return "Verify your API token and ensure it has not expired."
        case .modelNotFound:
            return "Use `modelList()` to see the available models."
        default:
            return nil
        }
    }
}

// MARK: - Convenience Factory Methods

extension AinosError {

    /// Creates a connection-failed error.
    public static func connectionFailed(
        host: String, port: Int, underlying: Error? = nil
    ) -> AinosError {
        AinosError(
            code: .connectionFailed,
            description: "Failed to connect to \(host):\(port)",
            underlyingError: underlying
        )
    }

    /// Creates a connection-refused error.
    public static func connectionRefused(
        host: String, port: Int
    ) -> AinosError {
        AinosError(
            code: .connectionRefused,
            description: "Connection refused by \(host):\(port)"
        )
    }

    /// Creates an authentication-failed error.
    public static func authenticationFailed(
        reason: String = "Invalid or expired token"
    ) -> AinosError {
        AinosError(
            code: .authenticationFailed,
            description: "Authentication failed: \(reason)"
        )
    }

    /// Creates an invalid-response error.
    public static func invalidResponse(
        details: String = "",
        underlying: Error? = nil
    ) -> AinosError {
        AinosError(
            code: .invalidResponse,
            description: "Invalid response from daemon\(details.isEmpty ? "" : ": \(details)")",
            underlyingError: underlying
        )
    }

    /// Creates an inference-failed error.
    public static func inferenceFailed(
        reason: String = "Unknown inference error"
    ) -> AinosError {
        AinosError(
            code: .inferenceFailed,
            description: "Inference failed: \(reason)"
        )
    }

    /// Creates a model-not-found error.
    public static func modelNotFound(
        _ modelId: String
    ) -> AinosError {
        AinosError(
            code: .modelNotFound,
            description: "Model '\(modelId)' not found"
        )
    }

    /// Creates an internal error.
    public static func internalError(
        _ message: String,
        underlying: Error? = nil,
        file: String = #fileID,
        line: Int = #line
    ) -> AinosError {
        AinosError(
            code: .internalError,
            description: message,
            underlyingError: underlying,
            file: file,
            line: line
        )
    }

    /// Creates a not-supported error.
    public static func notSupported(
        _ feature: String
    ) -> AinosError {
        AinosError(
            code: .notSupported,
            description: "\(feature) is not supported by the connected daemon"
        )
    }
}

// MARK: - Error Wrapping

extension Error {

    /// Wraps this error as an `AinosError` if it is not already one.
    public var asAinosError: AinosError {
        if let ainos = self as? AinosError {
            return ainos
        }
        let nsError = self as NSError
        switch nsError.domain {
        case NSPOSIXErrorDomain:
            return AinosError(
                code: .ioError,
                description: nsError.localizedDescription,
                underlyingError: self
            )
        case NSURLErrorDomain:
            switch nsError.code {
            case NSURLErrorTimedOut:
                return AinosError(
                    code: .connectionTimedOut,
                    description: "Connection timed out",
                    underlyingError: self
                )
            case NSURLErrorCannotConnectToHost:
                return AinosError(
                    code: .connectionRefused,
                    description: "Cannot connect to host",
                    underlyingError: self
                )
            case NSURLErrorNetworkConnectionLost:
                return AinosError(
                    code: .connectionClosed,
                    description: "Network connection was lost",
                    underlyingError: self
                )
            default:
                return AinosError(
                    code: .ioError,
                    description: nsError.localizedDescription,
                    underlyingError: self
                )
            }
        default:
            return AinosError(
                code: .internalError,
                description: nsError.localizedDescription,
                underlyingError: self
            )
        }
    }
}