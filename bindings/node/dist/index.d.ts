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
export { AinosClient, createClient } from './client';
export type { ClientOptions, InferenceRequest, InferenceResponse, InferenceChunk, ModelInfo, ModelLoadOptions, ModelLoadResponse, ModelUnloadResponse, SystemStatus, HealthStatus, RateLimitStatus, RateLimitInfo, AuthRequest, AuthResponse, ContextEntry, IpcMessage, IpcMessageType, AinosClientEvents, InferenceStreamEvents, } from './types';
export { IPC_MESSAGE_TYPES } from './types';
export { AinosError, ConnectionError, AuthError, RateLimitError, InferenceError, TimeoutError, DaemonError, } from './errors';
export { TcpTransport, TransportPool, DEFAULT_PORT, DEFAULT_HOST, } from './transport';
export type { TransportOptions, TransportEvents } from './transport';
export { InferenceStream, ReadableStreamAdapter, accumulateStream, } from './stream';
export { TokenManager, Authenticator, readTokenFromFile, writeTokenToFile, tokenFileExists, } from './auth';
export { encodeJson, decodeJson, safeDecodeJson, withTimeout, defer, calculateBackoff, generateId, generateSessionId, bufferToBase64, base64ToBuffer, encodeContextValue, decodeContextValue, sleep, } from './utils';
/** The SDK version string (from package.json). */
export declare const VERSION: string;
/** The SDK name. */
export declare const NAME: string;
/** Human-readable description of the SDK. */
export declare const DESCRIPTION: string;
//# sourceMappingURL=index.d.ts.map