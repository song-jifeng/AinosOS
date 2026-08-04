"use strict";
/**
 * Ainos SDK — Authentication module.
 *
 * Handles token management, session lifecycle, and secure token storage
 * for the Ainos daemon IPC protocol.
 */
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.Authenticator = exports.TokenManager = void 0;
exports.readTokenFromFile = readTokenFromFile;
exports.writeTokenToFile = writeTokenToFile;
exports.tokenFileExists = tokenFileExists;
const crypto = __importStar(require("crypto"));
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
const errors_1 = require("./errors");
// ============================================================================
// Constants
// ============================================================================
/** Default session TTL in seconds (1 hour). */
const DEFAULT_SESSION_TTL = 3600;
/** Minimum token length required by the daemon. */
const MIN_TOKEN_LENGTH = 32;
// ============================================================================
// Token Manager
// ============================================================================
/**
 * Manages authentication tokens for the Ainos daemon.
 *
 * Supports:
 * - In-memory token storage
 * - File-based token persistence (similar to `.ainos_token`)
 * - Token generation for development/testing
 * - Session token lifecycle
 */
class TokenManager {
    token = null;
    sessionToken = null;
    sessionExpiry = 0;
    permissions = [];
    sessionTtl = DEFAULT_SESSION_TTL;
    tokenPath = null;
    constructor(tokenPath) {
        if (tokenPath) {
            this.tokenPath = tokenPath;
        }
        else {
            // Default: look for .ainos_token in the home directory
            const home = process.env.HOME || process.env.USERPROFILE || '';
            if (home) {
                this.tokenPath = path.join(home, '.ainos_token');
            }
        }
    }
    // --------------------------------------------------------------------------
    // Properties
    // --------------------------------------------------------------------------
    /** Whether a bearer token has been configured. */
    get hasToken() {
        return this.token !== null;
    }
    /** Whether an active session exists. */
    get hasSession() {
        return this.sessionToken !== null && !this.isSessionExpired();
    }
    /** The current bearer token (raw). */
    get bearerToken() {
        return this.token;
    }
    /** The current session token. */
    get currentSessionToken() {
        if (this.isSessionExpired()) {
            return null;
        }
        return this.sessionToken;
    }
    /** Permissions granted to the current session. */
    get currentPermissions() {
        return [...this.permissions];
    }
    /** Session TTL in seconds. */
    get sessionTtlSeconds() {
        return this.sessionTtl;
    }
    // --------------------------------------------------------------------------
    // Token Management
    // --------------------------------------------------------------------------
    /**
     * Set the bearer token for authentication.
     *
     * @param token - The bearer token.
     * @throws {AuthError} If the token is too short.
     */
    setToken(token) {
        if (token.length < MIN_TOKEN_LENGTH) {
            throw new errors_1.AuthError(`Token must be at least ${MIN_TOKEN_LENGTH} characters long ` +
                `(got ${token.length})`);
        }
        this.token = token;
    }
    /**
     * Clear the bearer token and invalidate any session.
     */
    clearToken() {
        this.token = null;
        this.clearSession();
    }
    /**
     * Load the bearer token from the configured file path.
     *
     * @returns `true` if a token was loaded, `false` otherwise.
     */
    loadTokenFromFile() {
        if (!this.tokenPath)
            return false;
        try {
            if (fs.existsSync(this.tokenPath)) {
                const content = fs.readFileSync(this.tokenPath, 'utf-8').trim();
                if (content.length > 0) {
                    this.token = content;
                    return true;
                }
            }
        }
        catch {
            // File not readable — ignore
        }
        return false;
    }
    /**
     * Save the bearer token to the configured file path.
     */
    saveTokenToFile() {
        if (!this.tokenPath || !this.token)
            return;
        try {
            const dir = path.dirname(this.tokenPath);
            if (!fs.existsSync(dir)) {
                fs.mkdirSync(dir, { recursive: true });
            }
            fs.writeFileSync(this.tokenPath, this.token, {
                encoding: 'utf-8',
                mode: 0o600, // Owner read/write only
            });
        }
        catch {
            // Best-effort
        }
    }
    // --------------------------------------------------------------------------
    // Session Management
    // --------------------------------------------------------------------------
    /**
     * Update session state from an authentication response.
     *
     * @param response - The auth response from the daemon.
     */
    updateSession(response) {
        if (response.success && response.sessionToken) {
            this.sessionToken = response.sessionToken;
            this.permissions = response.permissions || [];
            this.sessionTtl = response.sessionTtlSeconds || DEFAULT_SESSION_TTL;
            this.sessionExpiry = Date.now() + this.sessionTtl * 1000;
        }
        else {
            this.clearSession();
        }
    }
    /**
     * Invalidate the current session.
     */
    clearSession() {
        this.sessionToken = null;
        this.sessionExpiry = 0;
        this.permissions = [];
    }
    /**
     * Check whether the session has expired.
     */
    isSessionExpired() {
        if (this.sessionToken === null)
            return true;
        if (this.sessionExpiry === 0)
            return false; // No expiry set
        return Date.now() >= this.sessionExpiry;
    }
    /**
     * Get the number of seconds until the session expires.
     * Returns 0 if no active session.
     */
    sessionTimeRemaining() {
        if (this.sessionToken === null || this.sessionExpiry === 0)
            return 0;
        const remaining = Math.max(0, Math.floor((this.sessionExpiry - Date.now()) / 1000));
        return remaining;
    }
    // --------------------------------------------------------------------------
    // Token Generation (dev/test)
    // --------------------------------------------------------------------------
    /**
     * Generate a cryptographically-random bearer token for development/testing.
     *
     * @param length - Token length in characters (default: 32).
     * @returns A hex-encoded random token.
     */
    static generateToken(length = 32) {
        return crypto.randomBytes(Math.ceil(length / 2))
            .toString('hex')
            .slice(0, length);
    }
    /**
     * Generate a UUID-style session token.
     *
     * @returns A UUID v4 string.
     */
    static generateSessionToken() {
        return crypto.randomUUID();
    }
    // --------------------------------------------------------------------------
    // Serialization
    // --------------------------------------------------------------------------
    /**
     * Serialize the current token state to a JSON object.
     */
    toJSON() {
        return {
            hasToken: this.hasToken,
            hasSession: this.hasSession,
            sessionTtl: this.sessionTtl,
            permissions: this.permissions,
            sessionTimeRemaining: this.sessionTimeRemaining(),
        };
    }
}
exports.TokenManager = TokenManager;
// ============================================================================
// Authenticator
// ============================================================================
/**
 * High-level authentication helper that integrates with the transport layer.
 *
 * Handles the full authentication flow:
 * 1. Send Auth request with bearer token
 * 2. Parse AuthResponse
 * 3. Manage session token lifecycle
 */
class Authenticator {
    tokenManager;
    _authenticated = false;
    constructor(tokenManager) {
        this.tokenManager = tokenManager;
    }
    /** Whether the authenticator has a valid session. */
    get authenticated() {
        return this._authenticated && this.tokenManager.hasSession;
    }
    /** The current session token. */
    get sessionToken() {
        return this.tokenManager.currentSessionToken;
    }
    /** The bearer token. */
    get bearerToken() {
        return this.tokenManager.bearerToken;
    }
    /**
     * Perform the authentication handshake.
     *
     * @param sendFn - Function that sends a payload and returns the parsed response.
     * @returns The parsed auth response.
     * @throws {AuthError} If authentication fails.
     */
    async authenticate(sendFn) {
        const token = this.tokenManager.bearerToken;
        if (!token) {
            throw new errors_1.AuthError('No authentication token provided');
        }
        const response = await sendFn({ type: 'Auth', token });
        // Validate the response
        if (response.type !== 'AuthResponse') {
            throw new errors_1.AuthError(`Unexpected response type: ${String(response.type)}`);
        }
        const authResponse = {
            success: Boolean(response.success),
            sessionToken: response.session_token,
            message: String(response.message || ''),
            permissions: Array.isArray(response.permissions)
                ? response.permissions
                : [],
            sessionTtlSeconds: Number(response.session_ttl_seconds || 0),
        };
        if (!authResponse.success) {
            throw new errors_1.AuthError(authResponse.message || 'Authentication failed');
        }
        // Update session state
        this.tokenManager.updateSession(authResponse);
        this._authenticated = true;
        return authResponse;
    }
    /**
     * Invalidate the current session.
     */
    deauthenticate() {
        this._authenticated = false;
        this.tokenManager.clearSession();
    }
}
exports.Authenticator = Authenticator;
// ============================================================================
// Secure Token Storage Helpers
// ============================================================================
/**
 * Read a token from a file, with basic validation.
 *
 * @param filePath - Path to the token file.
 * @returns The token string, or `null` if not found.
 */
function readTokenFromFile(filePath) {
    try {
        if (fs.existsSync(filePath)) {
            const content = fs.readFileSync(filePath, 'utf-8').trim();
            return content.length > 0 ? content : null;
        }
    }
    catch {
        // Ignore
    }
    return null;
}
/**
 * Write a token to a file with restricted permissions.
 *
 * @param filePath - Path to the token file.
 * @param token - The token to write.
 */
function writeTokenToFile(filePath, token) {
    const dir = path.dirname(filePath);
    if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
    }
    fs.writeFileSync(filePath, token, {
        encoding: 'utf-8',
        mode: 0o600,
    });
}
/**
 * Check if a token file exists and is readable.
 */
function tokenFileExists(filePath) {
    try {
        return fs.existsSync(filePath) && fs.statSync(filePath).size > 0;
    }
    catch {
        return false;
    }
}
//# sourceMappingURL=auth.js.map