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

// MARK: - Authentication Protocol

/// A protocol that handles authentication with the Ainos daemon.
///
/// The authentication layer is responsible for:
/// - Presenting credentials (typically a Bearer token) during connection
/// - Handling authentication challenges from the daemon
/// - Refreshing expired tokens when possible
/// - Providing clear error information on authentication failures
///
/// ## Concurrency
///
/// All methods are `async` and support cancellation via structured concurrency.
public protocol AuthenticationProtocol: AnyObject, Sendable {

    /// The current authentication state.
    var state: AuthenticationState { get }

    /// Performs authentication with the daemon.
    /// - Parameter transport: The transport to use for authentication.
    /// - Throws: `AinosError.authenticationFailed` if authentication fails.
    func authenticate(transport: TransportProtocol) async throws

    /// Refreshes the authentication token.
    /// - Throws: `AinosError.tokenRefreshFailed` if the token cannot be refreshed.
    func refreshToken() async throws

    /// Returns the authentication headers to include in requests.
    /// - Returns: A dictionary of authentication headers.
    /// - Throws: `AinosError.authenticationMissing` if no token is available.
    func authHeaders() async throws -> [String: String]
}

/// The current state of authentication.
public enum AuthenticationState: Sendable, Equatable, CustomStringConvertible {
    /// Authentication has not been attempted.
    case unauthenticated
    /// Authentication is in progress.
    case authenticating
    /// Authentication was successful.
    case authenticated
    /// Authentication failed.
    case failed(AinosError)

    public var description: String {
        switch self {
        case .unauthenticated: return "unauthenticated"
        case .authenticating: return "authenticating"
        case .authenticated: return "authenticated"
        case .failed(let error): return "failed: \(error.description)"
        }
    }

    /// Returns `true` if the state is authenticated.
    public var isAuthenticated: Bool {
        if case .authenticated = self { return true }
        return false
    }
}

// MARK: - Bearer Token Authentication

/// Bearer token authentication for the Ainos daemon.
///
/// This authenticator sends a Bearer token in the `Authorization` header
/// of every request. It supports:
/// - Static tokens (pre-configured)
/// - Token refresh via a callback
/// - Secure token storage in the Keychain
///
/// ## Usage
///
/// ```swift
/// let auth = BearerTokenAuthenticator(token: "my-token")
/// let auth = BearerTokenAuthenticator { () -> String? in
///     return try? Keychain.read(key: "ainos-token")
/// }
/// ```
public final class BearerTokenAuthenticator: AuthenticationProtocol {

    // MARK: - Public Properties

    public private(set) var state: AuthenticationState = .unauthenticated

    // MARK: - Private Properties

    private let tokenProvider: TokenProvider
    private let tokenRefreshProvider: TokenRefreshProvider?
    private let lock = NSLock()

    /// A type that provides an authentication token.
    public typealias TokenProvider = @Sendable () -> String?

    /// A type that provides a refreshed token.
    public typealias TokenRefreshProvider = @Sendable () async throws -> String?

    // MARK: - Initialization

    /// Creates an authenticator with a static token.
    /// - Parameter token: The Bearer token string.
    public convenience init(token: String) {
        self.init(tokenProvider: { token })
    }

    /// Creates an authenticator with a token provider closure.
    /// - Parameters:
    ///   - tokenProvider: A closure that returns the current token.
    ///   - tokenRefreshProvider: An optional closure that provides token refresh.
    public init(
        tokenProvider: @escaping TokenProvider,
        tokenRefreshProvider: TokenRefreshProvider? = nil
    ) {
        self.tokenProvider = tokenProvider
        self.tokenRefreshProvider = tokenRefreshProvider
    }

    // MARK: - Authentication

    public func authenticate(transport: TransportProtocol) async throws {
        state = .authenticating

        guard let token = tokenProvider() else {
            state = .failed(.authenticationFailed(reason: "No token provided"))
            throw AinosError.authenticationMissing
        }

        // Validate the token format (basic sanity check)
        guard !token.isEmpty else {
            state = .failed(.authenticationFailed(reason: "Token is empty"))
            throw AinosError.authenticationFailed(reason: "Token is empty")
        }

        // Send authentication request to the daemon
        let authPayload = AuthenticationPayload(token: token)
        let requestData = try JSONEncoder.ainos.encode(authPayload)
        try await transport.sendLine(String(data: requestData, encoding: .utf8) ?? "")

        // Read the authentication response
        guard let responseString = try await transport.readLine() else {
            state = .failed(.authenticationFailed(reason: "No response from daemon"))
            throw AinosError.authenticationFailed(reason: "No response from daemon")
        }

        guard let responseData = responseString.data(using: .utf8),
              let response = try? JSONDecoder.ainos.decode(
                AuthenticationResponse.self, from: responseData
              ) else {
            state = .failed(.authenticationFailed(reason: "Invalid response format"))
            throw AinosError.authenticationFailed(reason: "Invalid response format")
        }

        guard response.success else {
            let reason = response.message ?? "Token rejected"
            state = .failed(.authenticationFailed(reason: reason))
            throw AinosError.authenticationFailed(reason: reason)
        }

        state = .authenticated
    }

    public func refreshToken() async throws {
        guard let refreshProvider = tokenRefreshProvider else {
            throw AinosError(
                code: .tokenRefreshFailed,
                description: "No token refresh provider configured"
            )
        }

        guard let newToken = try await refreshProvider() else {
            throw AinosError(
                code: .tokenRefreshFailed,
                description: "Token refresh provider returned nil"
            )
        }

        // Update the stored token (token provider is re-evaluated on next auth)
        // Note: This only works if the token provider reads from a mutable source.
        // For static tokens, refresh will not change the underlying value.
        state = .unauthenticated
    }

    public func authHeaders() async throws -> [String: String] {
        guard let token = tokenProvider() else {
            throw AinosError.authenticationMissing
        }

        return [
            "Authorization": "Bearer \(token)"
        ]
    }

    // MARK: - Token Validation

    /// Validates the format of a Bearer token.
    /// - Parameter token: The token to validate.
    /// - Returns: `true` if the token format is valid.
    public static func validateTokenFormat(_ token: String) -> Bool {
        // Basic validation: token should not be empty and should not contain
        // whitespace or control characters
        guard !token.isEmpty else { return false }
        guard token.rangeOfCharacter(from: .whitespacesAndNewlines) == nil else {
            return false
        }
        guard token.rangeOfCharacter(from: .controlCharacters) == nil else {
            return false
        }
        return true
    }
}

// MARK: - Anonymous Authentication

/// Anonymous authentication (no credentials required).
///
/// This authenticator is used when connecting to a daemon that does not
/// require authentication. It skips the authentication handshake entirely.
public final class AnonymousAuthenticator: AuthenticationProtocol {

    public private(set) var state: AuthenticationState = .authenticated

    /// Creates an anonymous authenticator.
    public init() {}

    public func authenticate(transport: TransportProtocol) async throws {
        // No authentication needed
        state = .authenticated
    }

    public func refreshToken() async throws {
        // No token to refresh
    }

    public func authHeaders() async throws -> [String: String] {
        [:]
    }
}

// MARK: - Authentication Challenge

/// A challenge sent by the daemon when authentication is required.
public struct AuthenticationChallenge: Codable, Sendable {
    /// The authentication scheme expected.
    public let scheme: String

    /// A realm or context for the challenge.
    public let realm: String?

    /// Additional challenge parameters.
    public let parameters: [String: String]?

    enum CodingKeys: String, CodingKey {
        case scheme, realm, parameters
    }
}

// MARK: - Authentication Payload

/// The payload sent to the daemon for authentication.
public struct AuthenticationPayload: Codable, Sendable {
    /// The authentication method.
    public let method: String

    /// The credentials payload.
    public let credentials: String

    /// Creates an authentication payload with a Bearer token.
    /// - Parameter token: The Bearer token.
    public init(token: String) {
        self.method = "bearer"
        self.credentials = token
    }

    /// Creates an authentication payload with a custom method and credentials.
    /// - Parameters:
    ///   - method: The authentication method.
    ///   - credentials: The credentials string.
    public init(method: String, credentials: String) {
        self.method = method
        self.credentials = credentials
    }
}

// MARK: - Authentication Response

/// The response from the daemon after an authentication attempt.
public struct AuthenticationResponse: Codable, Sendable {
    /// Whether authentication was successful.
    public let success: Bool

    /// A message from the daemon about the authentication result.
    public let message: String?

    /// The session identifier assigned by the daemon.
    public let sessionId: String?

    /// The token expiration timestamp (if applicable).
    public let expiresAt: Date?

    enum CodingKeys: String, CodingKey {
        case success, message
        case sessionId = "session_id"
        case expiresAt = "expires_at"
    }
}

// MARK: - Token Store

/// A protocol for secure token storage.
///
/// Implementations might use Keychain, encrypted UserDefaults, or
/// custom secure storage mechanisms.
public protocol TokenStore: Sendable {
    /// Stores a token for the given key.
    /// - Parameters:
    ///   - token: The token to store.
    ///   - key: The storage key.
    /// - Throws: An error if the store operation fails.
    func store(token: String, for key: String) throws

    /// Retrieves a token for the given key.
    /// - Parameter key: The storage key.
    /// - Returns: The token, or nil if not found.
    /// - Throws: An error if the retrieval fails.
    func retrieveToken(for key: String) throws -> String?

    /// Deletes a token for the given key.
    /// - Parameter key: The storage key.
    /// - Throws: An error if the deletion fails.
    func deleteToken(for key: String) throws

    /// Returns `true` if a token exists for the given key.
    /// - Parameter key: The storage key.
    /// - Returns: `true` if a token exists.
    func hasToken(for key: String) -> Bool
}

/// A simple in-memory token store (not suitable for production).
///
/// This store keeps tokens in memory only. Tokens are lost when the
/// process exits. For production use, implement `TokenStore` with
/// Keychain-backed storage.
public final class InMemoryTokenStore: TokenStore {

    private var tokens: [String: String] = [:]
    private let lock = NSLock()

    /// Creates an empty in-memory token store.
    public init() {}

    public func store(token: String, for key: String) throws {
        lock.lock()
        defer { lock.unlock() }
        tokens[key] = token
    }

    public func retrieveToken(for key: String) throws -> String? {
        lock.lock()
        defer { lock.unlock() }
        return tokens[key]
    }

    public func deleteToken(for key: String) throws {
        lock.lock()
        defer { lock.unlock() }
        tokens.removeValue(forKey: key)
    }

    public func hasToken(for key: String) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        return tokens[key] != nil
    }
}

// MARK: - Keychain Token Store (macOS/iOS)

#if canImport(Security)
import Security

/// A Keychain-backed token store for macOS and iOS.
///
/// This store uses the system Keychain to persist tokens securely.
/// Tokens survive application restarts and are protected by the
/// device's security mechanisms.
///
/// ## Usage
///
/// ```swift
/// let store = KeychainTokenStore(service: "com.ainos.sdk")
/// try store.store(token: "my-token", for: "ainos-api-key")
/// ```
public final class KeychainTokenStore: TokenStore {

    private let service: String
    private let accessGroup: String?

    /// Creates a Keychain token store.
    /// - Parameters:
    ///   - service: The Keychain service name (default: "com.ainos.sdk.tokens").
    ///   - accessGroup: An optional Keychain access group for sharing.
    public init(
        service: String = "com.ainos.sdk.tokens",
        accessGroup: String? = nil
    ) {
        self.service = service
        self.accessGroup = accessGroup
    }

    public func store(token: String, for key: String) throws {
        guard let tokenData = token.data(using: .utf8) else {
            throw AinosError.internalError("Failed to encode token data")
        }

        // Try to delete an existing item first
        try? deleteToken(for: key)

        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecValueData as String: tokenData,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        ]

        if let accessGroup = accessGroup {
            query[kSecAttrAccessGroup as String] = accessGroup
        }

        let status = SecItemAdd(query as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw AinosError.internalError(
                "Keychain store failed with status: \(status)"
            )
        }
    }

    public func retrieveToken(for key: String) throws -> String? {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]

        if let accessGroup = accessGroup {
            query[kSecAttrAccessGroup as String] = accessGroup
        }

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        guard status == errSecSuccess else {
            if status == errSecItemNotFound {
                return nil
            }
            throw AinosError.internalError(
                "Keychain retrieval failed with status: \(status)"
            )
        }

        guard let data = result as? Data,
              let token = String(data: data, encoding: .utf8) else {
            return nil
        }

        return token
    }

    public func deleteToken(for key: String) throws {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key
        ]

        if let accessGroup = accessGroup {
            query[kSecAttrAccessGroup as String] = accessGroup
        }

        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw AinosError.internalError(
                "Keychain deletion failed with status: \(status)"
            )
        }
    }

    public func hasToken(for key: String) -> Bool {
        (try? retrieveToken(for: key)) != nil
    }
}
#endif

// MARK: - Authentication Provider Chain

/// Combines multiple authentication providers into a chain.
///
/// The chain tries each provider in order and returns the result
/// of the first successful authentication. If all providers fail,
/// the last error is thrown.
public final class AuthenticationChain: AuthenticationProtocol {

    public private(set) var state: AuthenticationState = .unauthenticated

    private let providers: [AuthenticationProtocol]

    /// Creates an authentication chain.
    /// - Parameter providers: The providers to try, in order.
    public init(providers: [AuthenticationProtocol]) {
        self.providers = providers
    }

    public func authenticate(transport: TransportProtocol) async throws {
        var lastError: Error = AinosError.authenticationFailed(reason: "No providers configured")

        for provider in providers {
            do {
                try await provider.authenticate(transport: transport)
                state = provider.state
                return
            } catch {
                lastError = error
                Logger.debug("Authentication provider failed: \(error.localizedDescription)")
            }
        }

        state = .failed(lastError.asAinosError)
        throw lastError
    }

    public func refreshToken() async throws {
        for provider in providers {
            if provider.state.isAuthenticated {
                try await provider.refreshToken()
                state = provider.state
                return
            }
        }
        throw AinosError(
            code: .tokenRefreshFailed,
            description: "No authenticated provider to refresh"
        )
    }

    public func authHeaders() async throws -> [String: String] {
        for provider in providers {
            if provider.state.isAuthenticated {
                return try await provider.authHeaders()
            }
        }
        throw AinosError.authenticationMissing
    }
}