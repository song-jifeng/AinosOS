/**
 * Ainos SDK — Error class hierarchy.
 *
 * Every error thrown by the SDK is an instance of a subclass of {@link AinosError}.
 * Consumers can catch a specific error type or the base type for broad handling.
 */
/**
 * Base error for all Ainos SDK errors.
 */
export declare class AinosError extends Error {
    /** Numeric error code from the daemon (if available). */
    readonly code: number;
    constructor(message: string, code?: number);
}
/**
 * Raised when the SDK cannot establish or maintain a TCP connection to the
 * Ainos daemon.
 */
export declare class ConnectionError extends AinosError {
    constructor(message: string, code?: number);
}
/**
 * Raised when authentication with the daemon fails (invalid token, expired
 * session, etc.).
 */
export declare class AuthError extends AinosError {
    constructor(message: string, code?: number);
}
/**
 * Raised when the daemon returns a rate-limit error (HTTP 429 equivalent).
 */
export declare class RateLimitError extends AinosError {
    /** Number of seconds the caller should wait before retrying. */
    readonly retryAfter: number;
    constructor(message: string, retryAfter?: number, code?: number);
}
/**
 * Raised when an inference request fails (daemon returns an Error message).
 */
export declare class InferenceError extends AinosError {
    constructor(message: string, code?: number);
}
/**
 * Raised when an operation exceeds the configured timeout.
 */
export declare class TimeoutError extends AinosError {
    /** The operation that timed out. */
    readonly operation: string;
    constructor(operation: string, timeoutMs: number);
}
/**
 * Raised when the daemon returns an Error message type that does not fit
 * a more specific exception class.
 */
export declare class DaemonError extends AinosError {
    constructor(message: string, code?: number);
}
//# sourceMappingURL=errors.d.ts.map