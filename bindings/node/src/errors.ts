/**
 * Ainos SDK — Error class hierarchy.
 *
 * Every error thrown by the SDK is an instance of a subclass of {@link AinosError}.
 * Consumers can catch a specific error type or the base type for broad handling.
 */

/**
 * Base error for all Ainos SDK errors.
 */
export class AinosError extends Error {
  /** Numeric error code from the daemon (if available). */
  public readonly code: number;

  constructor(message: string, code: number = -1) {
    super(message);
    this.name = 'AinosError';
    this.code = code;
    // Fix prototype chain for instanceof checks
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Raised when the SDK cannot establish or maintain a TCP connection to the
 * Ainos daemon.
 */
export class ConnectionError extends AinosError {
  constructor(message: string, code: number = -1) {
    super(message, code);
    this.name = 'ConnectionError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Raised when authentication with the daemon fails (invalid token, expired
 * session, etc.).
 */
export class AuthError extends AinosError {
  constructor(message: string, code: number = 401) {
    super(message, code);
    this.name = 'AuthError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Raised when the daemon returns a rate-limit error (HTTP 429 equivalent).
 */
export class RateLimitError extends AinosError {
  /** Number of seconds the caller should wait before retrying. */
  public readonly retryAfter: number;

  constructor(message: string, retryAfter: number = 1, code: number = 429) {
    super(message, code);
    this.name = 'RateLimitError';
    this.retryAfter = retryAfter;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Raised when an inference request fails (daemon returns an Error message).
 */
export class InferenceError extends AinosError {
  constructor(message: string, code: number = -1) {
    super(message, code);
    this.name = 'InferenceError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Raised when an operation exceeds the configured timeout.
 */
export class TimeoutError extends AinosError {
  /** The operation that timed out. */
  public readonly operation: string;

  constructor(operation: string, timeoutMs: number) {
    super(`Operation "${operation}" timed out after ${timeoutMs}ms`, -1);
    this.name = 'TimeoutError';
    this.operation = operation;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Raised when the daemon returns an Error message type that does not fit
 * a more specific exception class.
 */
export class DaemonError extends AinosError {
  constructor(message: string, code: number = -1) {
    super(message, code);
    this.name = 'DaemonError';
    Object.setPrototypeOf(this, new.target.prototype);
  }
}