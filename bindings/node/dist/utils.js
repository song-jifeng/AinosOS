"use strict";
/**
 * Ainos SDK — Internal utilities.
 *
 * JSON helpers, promise-with-timeout, exponential backoff, and ID generation.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.encodeJson = encodeJson;
exports.decodeJson = decodeJson;
exports.safeDecodeJson = safeDecodeJson;
exports.withTimeout = withTimeout;
exports.defer = defer;
exports.calculateBackoff = calculateBackoff;
exports.generateId = generateId;
exports.generateSessionId = generateSessionId;
exports.bufferToBase64 = bufferToBase64;
exports.base64ToBuffer = base64ToBuffer;
exports.isObject = isObject;
exports.isString = isString;
exports.encodeContextValue = encodeContextValue;
exports.decodeContextValue = decodeContextValue;
exports.sleep = sleep;
const errors_1 = require("./errors");
// ============================================================================
// JSON Encoding / Decoding
// ============================================================================
/** Encode a value as a compact JSON string (no extra whitespace). */
function encodeJson(value) {
    return JSON.stringify(value);
}
/** Decode a JSON string, returning `undefined` on failure. */
function decodeJson(text) {
    try {
        return JSON.parse(text);
    }
    catch {
        return undefined;
    }
}
/** Safely decode a JSON string, returning a default on failure. */
function safeDecodeJson(text, fallback) {
    try {
        return JSON.parse(text);
    }
    catch {
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
function withTimeout(operation, promise, ms) {
    let timer;
    const timeout = new Promise((_, reject) => {
        timer = setTimeout(() => {
            reject(new errors_1.TimeoutError(operation, ms));
        }, ms);
    });
    return Promise.race([promise, timeout]).finally(() => {
        if (timer !== undefined)
            clearTimeout(timer);
    });
}
/**
 * Create a deferred promise that can be resolved or rejected externally.
 */
function defer() {
    let resolve;
    let reject;
    const promise = new Promise((res, rej) => {
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
function calculateBackoff(attempt, baseMs = 1000, maxMs = 30000) {
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
function generateId() {
    idCounter += 1;
    return `rq_${Date.now()}_${idCounter}`;
}
/**
 * Generate a unique session identifier.
 *
 * Format: `sess_<timestamp>_<counter>`
 */
function generateSessionId() {
    idCounter += 1;
    return `sess_${Date.now()}_${idCounter}`;
}
// ============================================================================
// Byte helpers
// ============================================================================
/**
 * Convert a Node.js Buffer to a base64-encoded string.
 */
function bufferToBase64(buf) {
    return buf.toString('base64');
}
/**
 * Convert a base64-encoded string back to a Buffer.
 */
function base64ToBuffer(encoded) {
    return Buffer.from(encoded, 'base64');
}
// ============================================================================
// Type guards
// ============================================================================
/** Check if a value is a non-null object. */
function isObject(value) {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}
/** Check if a value is a plain string. */
function isString(value) {
    return typeof value === 'string';
}
// ============================================================================
// Serialization helpers
// ============================================================================
/**
 * Normalise a key-value pair for the context store.
 * If `value` is a Buffer, it is base64-encoded and prefixed with `base64:`.
 */
function encodeContextValue(value) {
    if (Buffer.isBuffer(value)) {
        return `base64:${bufferToBase64(value)}`;
    }
    return value;
}
/**
 * Decode a context value that may have been base64-encoded.
 */
function decodeContextValue(value) {
    if (value.startsWith('base64:')) {
        return base64ToBuffer(value.slice(7));
    }
    return value;
}
/**
 * Sleep for the given number of milliseconds.
 */
function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}
//# sourceMappingURL=utils.js.map