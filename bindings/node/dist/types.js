"use strict";
/**
 * Ainos SDK — TypeScript type definitions for the Ainos IPC protocol.
 *
 * These types map directly to the JSON payloads exchanged with the Ainos AI
 * Daemon over the NDJSON TCP protocol.  All field names use camelCase to match
 * the daemon's serde serialization.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.IPC_MESSAGE_TYPES = void 0;
// ============================================================================
// IPC Wire Protocol
// ============================================================================
/**
 * Raw IPC message types as defined by the daemon's serde enum.
 * These are used internally by the transport layer.
 */
exports.IPC_MESSAGE_TYPES = {
    AUTH: 'Auth',
    AUTH_RESPONSE: 'AuthResponse',
    INFERENCE: 'Inference',
    INFERENCE_RESPONSE: 'InferenceResponse',
    INFERENCE_STREAM: 'InferenceStream',
    INFERENCE_CHUNK: 'InferenceChunk',
    MODEL_LIST: 'ModelList',
    MODEL_LIST_RESPONSE: 'ModelListResponse',
    MODEL_LOAD: 'ModelLoad',
    MODEL_LOAD_RESPONSE: 'ModelLoadResponse',
    MODEL_UNLOAD: 'ModelUnload',
    MODEL_UNLOAD_RESPONSE: 'ModelUnloadResponse',
    STATUS: 'Status',
    STATUS_RESPONSE: 'StatusResponse',
    RATE_LIMIT_STATUS: 'RateLimitStatus',
    RATE_LIMIT_STATUS_RESPONSE: 'RateLimitStatusResponse',
    CONTEXT_STORE: 'ContextStore',
    CONTEXT_RETRIEVE: 'ContextRetrieve',
    ERROR: 'Error',
};
//# sourceMappingURL=types.js.map