/**
 * Ainos SDK — Authentication module.
 *
 * Handles token management, session lifecycle, and secure token storage
 * for the Ainos daemon IPC protocol.
 */
import { AuthResponse } from './types';
/**
 * Manages authentication tokens for the Ainos daemon.
 *
 * Supports:
 * - In-memory token storage
 * - File-based token persistence (similar to `.ainos_token`)
 * - Token generation for development/testing
 * - Session token lifecycle
 */
export declare class TokenManager {
    private token;
    private sessionToken;
    private sessionExpiry;
    private permissions;
    private sessionTtl;
    private tokenPath;
    constructor(tokenPath?: string);
    /** Whether a bearer token has been configured. */
    get hasToken(): boolean;
    /** Whether an active session exists. */
    get hasSession(): boolean;
    /** The current bearer token (raw). */
    get bearerToken(): string | null;
    /** The current session token. */
    get currentSessionToken(): string | null;
    /** Permissions granted to the current session. */
    get currentPermissions(): string[];
    /** Session TTL in seconds. */
    get sessionTtlSeconds(): number;
    /**
     * Set the bearer token for authentication.
     *
     * @param token - The bearer token.
     * @throws {AuthError} If the token is too short.
     */
    setToken(token: string): void;
    /**
     * Clear the bearer token and invalidate any session.
     */
    clearToken(): void;
    /**
     * Load the bearer token from the configured file path.
     *
     * @returns `true` if a token was loaded, `false` otherwise.
     */
    loadTokenFromFile(): boolean;
    /**
     * Save the bearer token to the configured file path.
     */
    saveTokenToFile(): void;
    /**
     * Update session state from an authentication response.
     *
     * @param response - The auth response from the daemon.
     */
    updateSession(response: AuthResponse): void;
    /**
     * Invalidate the current session.
     */
    clearSession(): void;
    /**
     * Check whether the session has expired.
     */
    isSessionExpired(): boolean;
    /**
     * Get the number of seconds until the session expires.
     * Returns 0 if no active session.
     */
    sessionTimeRemaining(): number;
    /**
     * Generate a cryptographically-random bearer token for development/testing.
     *
     * @param length - Token length in characters (default: 32).
     * @returns A hex-encoded random token.
     */
    static generateToken(length?: number): string;
    /**
     * Generate a UUID-style session token.
     *
     * @returns A UUID v4 string.
     */
    static generateSessionToken(): string;
    /**
     * Serialize the current token state to a JSON object.
     */
    toJSON(): Record<string, unknown>;
}
/**
 * High-level authentication helper that integrates with the transport layer.
 *
 * Handles the full authentication flow:
 * 1. Send Auth request with bearer token
 * 2. Parse AuthResponse
 * 3. Manage session token lifecycle
 */
export declare class Authenticator {
    private tokenManager;
    private _authenticated;
    constructor(tokenManager: TokenManager);
    /** Whether the authenticator has a valid session. */
    get authenticated(): boolean;
    /** The current session token. */
    get sessionToken(): string | null;
    /** The bearer token. */
    get bearerToken(): string | null;
    /**
     * Perform the authentication handshake.
     *
     * @param sendFn - Function that sends a payload and returns the parsed response.
     * @returns The parsed auth response.
     * @throws {AuthError} If authentication fails.
     */
    authenticate(sendFn: (payload: unknown) => Promise<Record<string, unknown>>): Promise<AuthResponse>;
    /**
     * Invalidate the current session.
     */
    deauthenticate(): void;
}
/**
 * Read a token from a file, with basic validation.
 *
 * @param filePath - Path to the token file.
 * @returns The token string, or `null` if not found.
 */
export declare function readTokenFromFile(filePath: string): string | null;
/**
 * Write a token to a file with restricted permissions.
 *
 * @param filePath - Path to the token file.
 * @param token - The token to write.
 */
export declare function writeTokenToFile(filePath: string, token: string): void;
/**
 * Check if a token file exists and is readable.
 */
export declare function tokenFileExists(filePath: string): boolean;
//# sourceMappingURL=auth.d.ts.map