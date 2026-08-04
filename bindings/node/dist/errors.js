"use strict";
/**
 * Ainos SDK — Error class hierarchy.
 *
 * Every error thrown by the SDK is an instance of a subclass of {@link AinosError}.
 * Consumers can catch a specific error type or the base type for broad handling.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.DaemonError = exports.TimeoutError = exports.InferenceError = exports.RateLimitError = exports.AuthError = exports.ConnectionError = exports.AinosError = void 0;
/**
 * Base error for all Ainos SDK errors.
 */
class AinosError extends Error {
    /** Numeric error code from the daemon (if available). */
    code;
    constructor(message, code = -1) {
        super(message);
        this.name = 'AinosError';
        this.code = code;
        // Fix prototype chain for instanceof checks
        Object.setPrototypeOf(this, new.target.prototype);
    }
}
exports.AinosError = AinosError;
/**
 * Raised when the SDK cannot establish or maintain a TCP connection to the
 * Ainos daemon.
 */
class ConnectionError extends AinosError {
    constructor(message, code = -1) {
        super(message, code);
        this.name = 'ConnectionError';
        Object.setPrototypeOf(this, new.target.prototype);
    }
}
exports.ConnectionError = ConnectionError;
/**
 * Raised when authentication with the daemon fails (invalid token, expired
 * session, etc.).
 */
class AuthError extends AinosError {
    constructor(message, code = 401) {
        super(message, code);
        this.name = 'AuthError';
        Object.setPrototypeOf(this, new.target.prototype);
    }
}
exports.AuthError = AuthError;
/**
 * Raised when the daemon returns a rate-limit error (HTTP 429 equivalent).
 */
class RateLimitError extends AinosError {
    /** Number of seconds the caller should wait before retrying. */
    retryAfter;
    constructor(message, retryAfter = 1, code = 429) {
        super(message, code);
        this.name = 'RateLimitError';
        this.retryAfter = retryAfter;
        Object.setPrototypeOf(this, new.target.prototype);
    }
}
exports.RateLimitError = RateLimitError;
/**
 * Raised when an inference request fails (daemon returns an Error message).
 */
class InferenceError extends AinosError {
    constructor(message, code = -1) {
        super(message, code);
        this.name = 'InferenceError';
        Object.setPrototypeOf(this, new.target.prototype);
    }
}
exports.InferenceError = InferenceError;
/**
 * Raised when an operation exceeds the configured timeout.
 */
class TimeoutError extends AinosError {
    /** The operation that timed out. */
    operation;
    constructor(operation, timeoutMs) {
        super(`Operation "${operation}" timed out after ${timeoutMs}ms`, -1);
        this.name = 'TimeoutError';
        this.operation = operation;
        Object.setPrototypeOf(this, new.target.prototype);
    }
}
exports.TimeoutError = TimeoutError;
/**
 * Raised when the daemon returns an Error message type that does not fit
 * a more specific exception class.
 */
class DaemonError extends AinosError {
    constructor(message, code = -1) {
        super(message, code);
        this.name = 'DaemonError';
        Object.setPrototypeOf(this, new.target.prototype);
    }
}
exports.DaemonError = DaemonError;
//# sourceMappingURL=errors.js.map