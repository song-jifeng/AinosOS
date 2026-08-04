"use strict";
/**
 * Ainos SDK — Entry point.
 *
 * Re-exports all public types and classes for the `ainos-sdk` package.
 *
 * @example
 * ```ts
 * import { AinosClient, createClient } from 'ainos-sdk';
 *
 * const client = createClient({ authToken: 'my-token' });
 * const resp = await client.infer({ prompt: 'Hello' });
 * ```
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.DESCRIPTION = exports.NAME = exports.VERSION = exports.sleep = exports.decodeContextValue = exports.encodeContextValue = exports.base64ToBuffer = exports.bufferToBase64 = exports.generateSessionId = exports.generateId = exports.calculateBackoff = exports.defer = exports.withTimeout = exports.safeDecodeJson = exports.decodeJson = exports.encodeJson = exports.tokenFileExists = exports.writeTokenToFile = exports.readTokenFromFile = exports.Authenticator = exports.TokenManager = exports.accumulateStream = exports.ReadableStreamAdapter = exports.InferenceStream = exports.DEFAULT_HOST = exports.DEFAULT_PORT = exports.TransportPool = exports.TcpTransport = exports.DaemonError = exports.TimeoutError = exports.InferenceError = exports.RateLimitError = exports.AuthError = exports.ConnectionError = exports.AinosError = exports.IPC_MESSAGE_TYPES = exports.createClient = exports.AinosClient = void 0;
// ============================================================================
// Main Client
// ============================================================================
var client_1 = require("./client");
Object.defineProperty(exports, "AinosClient", { enumerable: true, get: function () { return client_1.AinosClient; } });
Object.defineProperty(exports, "createClient", { enumerable: true, get: function () { return client_1.createClient; } });
var types_1 = require("./types");
Object.defineProperty(exports, "IPC_MESSAGE_TYPES", { enumerable: true, get: function () { return types_1.IPC_MESSAGE_TYPES; } });
// ============================================================================
// Errors
// ============================================================================
var errors_1 = require("./errors");
Object.defineProperty(exports, "AinosError", { enumerable: true, get: function () { return errors_1.AinosError; } });
Object.defineProperty(exports, "ConnectionError", { enumerable: true, get: function () { return errors_1.ConnectionError; } });
Object.defineProperty(exports, "AuthError", { enumerable: true, get: function () { return errors_1.AuthError; } });
Object.defineProperty(exports, "RateLimitError", { enumerable: true, get: function () { return errors_1.RateLimitError; } });
Object.defineProperty(exports, "InferenceError", { enumerable: true, get: function () { return errors_1.InferenceError; } });
Object.defineProperty(exports, "TimeoutError", { enumerable: true, get: function () { return errors_1.TimeoutError; } });
Object.defineProperty(exports, "DaemonError", { enumerable: true, get: function () { return errors_1.DaemonError; } });
// ============================================================================
// Transport
// ============================================================================
var transport_1 = require("./transport");
Object.defineProperty(exports, "TcpTransport", { enumerable: true, get: function () { return transport_1.TcpTransport; } });
Object.defineProperty(exports, "TransportPool", { enumerable: true, get: function () { return transport_1.TransportPool; } });
Object.defineProperty(exports, "DEFAULT_PORT", { enumerable: true, get: function () { return transport_1.DEFAULT_PORT; } });
Object.defineProperty(exports, "DEFAULT_HOST", { enumerable: true, get: function () { return transport_1.DEFAULT_HOST; } });
// ============================================================================
// Streaming
// ============================================================================
var stream_1 = require("./stream");
Object.defineProperty(exports, "InferenceStream", { enumerable: true, get: function () { return stream_1.InferenceStream; } });
Object.defineProperty(exports, "ReadableStreamAdapter", { enumerable: true, get: function () { return stream_1.ReadableStreamAdapter; } });
Object.defineProperty(exports, "accumulateStream", { enumerable: true, get: function () { return stream_1.accumulateStream; } });
// ============================================================================
// Authentication
// ============================================================================
var auth_1 = require("./auth");
Object.defineProperty(exports, "TokenManager", { enumerable: true, get: function () { return auth_1.TokenManager; } });
Object.defineProperty(exports, "Authenticator", { enumerable: true, get: function () { return auth_1.Authenticator; } });
Object.defineProperty(exports, "readTokenFromFile", { enumerable: true, get: function () { return auth_1.readTokenFromFile; } });
Object.defineProperty(exports, "writeTokenToFile", { enumerable: true, get: function () { return auth_1.writeTokenToFile; } });
Object.defineProperty(exports, "tokenFileExists", { enumerable: true, get: function () { return auth_1.tokenFileExists; } });
// ============================================================================
// Utilities
// ============================================================================
var utils_1 = require("./utils");
Object.defineProperty(exports, "encodeJson", { enumerable: true, get: function () { return utils_1.encodeJson; } });
Object.defineProperty(exports, "decodeJson", { enumerable: true, get: function () { return utils_1.decodeJson; } });
Object.defineProperty(exports, "safeDecodeJson", { enumerable: true, get: function () { return utils_1.safeDecodeJson; } });
Object.defineProperty(exports, "withTimeout", { enumerable: true, get: function () { return utils_1.withTimeout; } });
Object.defineProperty(exports, "defer", { enumerable: true, get: function () { return utils_1.defer; } });
Object.defineProperty(exports, "calculateBackoff", { enumerable: true, get: function () { return utils_1.calculateBackoff; } });
Object.defineProperty(exports, "generateId", { enumerable: true, get: function () { return utils_1.generateId; } });
Object.defineProperty(exports, "generateSessionId", { enumerable: true, get: function () { return utils_1.generateSessionId; } });
Object.defineProperty(exports, "bufferToBase64", { enumerable: true, get: function () { return utils_1.bufferToBase64; } });
Object.defineProperty(exports, "base64ToBuffer", { enumerable: true, get: function () { return utils_1.base64ToBuffer; } });
Object.defineProperty(exports, "encodeContextValue", { enumerable: true, get: function () { return utils_1.encodeContextValue; } });
Object.defineProperty(exports, "decodeContextValue", { enumerable: true, get: function () { return utils_1.decodeContextValue; } });
Object.defineProperty(exports, "sleep", { enumerable: true, get: function () { return utils_1.sleep; } });
// ============================================================================
// Package metadata
// ============================================================================
// eslint-disable-next-line @typescript-eslint/no-var-requires
const pkg = require('../package.json');
/** The SDK version string (from package.json). */
exports.VERSION = pkg.version;
/** The SDK name. */
exports.NAME = pkg.name;
/** Human-readable description of the SDK. */
exports.DESCRIPTION = pkg.description;
//# sourceMappingURL=index.js.map