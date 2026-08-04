/**
 * Ainos SDK — Internal utilities.
 *
 * JSON helpers, promise-with-timeout, exponential backoff, and ID generation.
 */
/** Encode a value as a compact JSON string (no extra whitespace). */
export declare function encodeJson(value: unknown): string;
/** Decode a JSON string, returning `undefined` on failure. */
export declare function decodeJson<T = Record<string, unknown>>(text: string): T | undefined;
/** Safely decode a JSON string, returning a default on failure. */
export declare function safeDecodeJson<T = Record<string, unknown>>(text: string, fallback: T): T;
/**
 * Wrap a promise so it rejects with a {@link TimeoutError} if it does not
 * settle within `ms` milliseconds.
 *
 * The underlying promise is NOT cancelled — it continues to run but its
 * result is ignored.
 */
export declare function withTimeout<T>(operation: string, promise: Promise<T>, ms: number): Promise<T>;
/**
 * Create a deferred promise that can be resolved or rejected externally.
 */
export declare function defer<T = void>(): {
    promise: Promise<T>;
    resolve: (value: T | PromiseLike<T>) => void;
    reject: (reason: unknown) => void;
};
/**
 * Calculate an exponential backoff delay with jitter.
 *
 * @param attempt - Zero-based attempt number.
 * @param baseMs  - Base delay in milliseconds (default: 1000).
 * @param maxMs   - Maximum delay in milliseconds (default: 30000).
 * @returns Delay in milliseconds.
 */
export declare function calculateBackoff(attempt: number, baseMs?: number, maxMs?: number): number;
/**
 * Generate a unique request identifier.
 *
 * Format: `rq_<timestamp>_<counter>`
 */
export declare function generateId(): string;
/**
 * Generate a unique session identifier.
 *
 * Format: `sess_<timestamp>_<counter>`
 */
export declare function generateSessionId(): string;
/**
 * Convert a Node.js Buffer to a base64-encoded string.
 */
export declare function bufferToBase64(buf: Buffer): string;
/**
 * Convert a base64-encoded string back to a Buffer.
 */
export declare function base64ToBuffer(encoded: string): Buffer;
/** Check if a value is a non-null object. */
export declare function isObject(value: unknown): value is Record<string, unknown>;
/** Check if a value is a plain string. */
export declare function isString(value: unknown): value is string;
/**
 * Normalise a key-value pair for the context store.
 * If `value` is a Buffer, it is base64-encoded and prefixed with `base64:`.
 */
export declare function encodeContextValue(value: string | Buffer): string;
/**
 * Decode a context value that may have been base64-encoded.
 */
export declare function decodeContextValue(value: string): string | Buffer;
/**
 * Sleep for the given number of milliseconds.
 */
export declare function sleep(ms: number): Promise<void>;
//# sourceMappingURL=utils.d.ts.map