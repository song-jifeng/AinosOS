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

// ============================================================================
// Main Client
// ============================================================================

export { AinosClient, createClient } from './client';

// ============================================================================
// Types
// ============================================================================

export type {
  ClientOptions,
  InferenceRequest,
  InferenceResponse,
  InferenceChunk,
  ModelInfo,
  ModelLoadOptions,
  ModelLoadResponse,
  ModelUnloadResponse,
  SystemStatus,
  HealthStatus,
  RateLimitStatus,
  RateLimitInfo,
  AuthRequest,
  AuthResponse,
  ContextEntry,
  IpcMessage,
  IpcMessageType,
  AinosClientEvents,
  InferenceStreamEvents,
} from './types';

export { IPC_MESSAGE_TYPES } from './types';

// ============================================================================
// Errors
// ============================================================================

export {
  AinosError,
  ConnectionError,
  AuthError,
  RateLimitError,
  InferenceError,
  TimeoutError,
  DaemonError,
} from './errors';

// ============================================================================
// Transport
// ============================================================================

export {
  TcpTransport,
  TransportPool,
  DEFAULT_PORT,
  DEFAULT_HOST,
} from './transport';

export type { TransportOptions, TransportEvents } from './transport';

// ============================================================================
// Streaming
// ============================================================================

export {
  InferenceStream,
  ReadableStreamAdapter,
  accumulateStream,
} from './stream';

// ============================================================================
// Authentication
// ============================================================================

export {
  TokenManager,
  Authenticator,
  readTokenFromFile,
  writeTokenToFile,
  tokenFileExists,
} from './auth';

// ============================================================================
// Utilities
// ============================================================================

export {
  encodeJson,
  decodeJson,
  safeDecodeJson,
  withTimeout,
  defer,
  calculateBackoff,
  generateId,
  generateSessionId,
  bufferToBase64,
  base64ToBuffer,
  encodeContextValue,
  decodeContextValue,
  sleep,
} from './utils';

// ============================================================================
// Package metadata
// ============================================================================

// eslint-disable-next-line @typescript-eslint/no-var-requires
const pkg = require('../package.json');

/** The SDK version string (from package.json). */
export const VERSION: string = pkg.version;

/** The SDK name. */
export const NAME: string = pkg.name;

/** Human-readable description of the SDK. */
export const DESCRIPTION: string = pkg.description;