/**
 * Ainos SDK — Internal utilities.
 *
 * JSON helpers, promise-with-timeout, exponential backoff, and ID generation.
 */

import { TimeoutError } from './errors';

// ============================================================================
// JSON Encoding / Decoding
// ============================================================================

/** Encode a value as a compact JSON string (no extra whitespace). */
export function encodeJson(value: unknown): string {
  return JSON.stringify(value);
}

/** Decode a JSON string, returning `undefined` on failure. */
export function decodeJson<T = Record<string, unknown>>(text: string): T | undefined {
  try {
    return JSON.parse(text) as T;
  } catch {
    return undefined;
  }
}

/** Safely decode a JSON string, returning a default on failure. */
export function safeDecodeJson<T = Record<string, unknown>>(
  text: string,
  fallback: T,
): T {
  try {
    return JSON.parse(text) as T;
  } catch {
    return fallback;
  }
}

// ============================================================================
// Promise with Timeout
// ============================================================================

/**
 * Wrap a promise so it rejects with a {@link TimeoutError} if it does not
 * settle within `ms` milliseconds.
 *
 * The underlying promise is NOT cancelled — it continues to run but its
 * result is ignored.
 */
export function withTimeout<T>(
  operation: string,
  promise: Promise<T>,
  ms: number,
): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;

  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      reject(new TimeoutError(operation, ms));
    }, ms);
  });

  return Promise.race([promise, timeout]).finally(() => {
    if (timer !== undefined) clearTimeout(timer);
  });
}

/**
 * Create a deferred promise that can be resolved or rejected externally.
 */
export function defer<T = void>(): {
  promise: Promise<T>;
  resolve: (value: T | PromiseLike<T>) => void;
  reject: (reason: unknown) => void;
} {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

// ============================================================================
// Backoff Calculator
// ============================================================================

/**
 * Calculate an exponential backoff delay with jitter.
 *
 * @param attempt - Zero-based attempt number.
 * @param baseMs  - Base delay in milliseconds (default: 1000).
 * @param maxMs   - Maximum delay in milliseconds (default: 30000).
 * @returns Delay in milliseconds.
 */
export function calculateBackoff(
  attempt: number,
  baseMs: number = 1000,
  maxMs: number = 30000,
): number {
  const exponential = Math.min(baseMs * Math.pow(2, attempt), maxMs);
  // Add up to 25% jitter, but never exceed maxMs
  const jitter = exponential * 0.25 * Math.random();
  return Math.min(Math.floor(exponential + jitter), maxMs);
}

// ============================================================================
// ID Generator
// ============================================================================

let idCounter = 0;

/**
 * Generate a unique request identifier.
 *
 * Format: `rq_<timestamp>_<counter>`
 */
export function generateId(): string {
  idCounter += 1;
  return `rq_${Date.now()}_${idCounter}`;
}

/**
 * Generate a unique session identifier.
 *
 * Format: `sess_<timestamp>_<counter>`
 */
export function generateSessionId(): string {
  idCounter += 1;
  return `sess_${Date.now()}_${idCounter}`;
}

// ============================================================================
// Byte helpers
// ============================================================================

/**
 * Convert a Node.js Buffer to a base64-encoded string.
 */
export function bufferToBase64(buf: Buffer): string {
  return buf.toString('base64');
}

/**
 * Convert a base64-encoded string back to a Buffer.
 */
export function base64ToBuffer(encoded: string): Buffer {
  return Buffer.from(encoded, 'base64');
}

// ============================================================================
// Type guards
// ============================================================================

/** Check if a value is a non-null object. */
export function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Check if a value is a plain string. */
export function isString(value: unknown): value is string {
  return typeof value === 'string';
}

// ============================================================================
// Serialization helpers
// ============================================================================

/**
 * Normalise a key-value pair for the context store.
 * If `value` is a Buffer, it is base64-encoded and prefixed with `base64:`.
 */
export function encodeContextValue(value: string | Buffer): string {
  if (Buffer.isBuffer(value)) {
    return `base64:${bufferToBase64(value)}`;
  }
  return value;
}

/**
 * Decode a context value that may have been base64-encoded.
 */
export function decodeContextValue(value: string): string | Buffer {
  if (value.startsWith('base64:')) {
    return base64ToBuffer(value.slice(7));
  }
  return value;
}

/**
 * Sleep for the given number of milliseconds.
 */
export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}