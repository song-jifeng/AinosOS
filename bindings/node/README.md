# Ainos SDK for Node.js / TypeScript

[![npm version](https://img.shields.io/npm/v/ainos-sdk)](https://www.npmjs.com/package/ainos-sdk)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> A lightweight, zero-dependency TypeScript SDK for communicating with the
> **Ainos AI Daemon** over TCP/IP using the newline-delimited JSON (NDJSON)
> protocol.

---

## Features

- **TCP/IP transport** — connects to the Ainos daemon on port 9500 via
  Node.js built-in `net` module (no external dependencies)
- **NDJSON protocol** — newline-delimited JSON framing, matching the daemon's
  native IPC format
- **Authentication** — bearer token auth with session management
- **Synchronous inference** — `infer()` returns a complete response
- **Streaming inference** — `inferStream()` emits `data` events for each
  generated chunk
- **Model management** — `list()`, `load()`, `unload()` APIs
- **Context store** — key-value persistence with optional TTL
- **System status** — health checks, rate limit inspection, statistics
- **Auto-reconnect** — exponential backoff with configurable retry limits
- **Timeout support** — per-operation and connection-level timeouts
- **Error hierarchy** — typed error classes for all failure modes
- **EventEmitter-based** — clean event-driven architecture
- **Fully tested** — comprehensive Jest test suite with mock daemon server

---

## Installation

```bash
npm install ainos-sdk
```

## Quick Start

```typescript
import { AinosClient } from 'ainos-sdk';

const client = new AinosClient({
  host: '127.0.0.1',
  port: 9500,
  authToken: 'your-bearer-token',
});

await client.connect();

const response = await client.infer({ prompt: 'Hello, Ainos!' });
console.log(response.output);

await client.disconnect();
```

---

## API Reference

### Client Options

```typescript
interface ClientOptions {
  host?: string;                    // Default: "127.0.0.1"
  port?: number;                    // Default: 9500
  connectTimeout?: number;          // ms, default: 5000
  readTimeout?: number;             // ms, default: 120000
  autoReconnect?: boolean;          // Default: true
  reconnectDelay?: number;          // ms, default: 1000
  maxReconnectAttempts?: number;    // 0 = infinite, default: 5
  authToken?: string;               // Bearer token
  autoAuthenticate?: boolean;       // Default: true
}
```

### Connection

| Method | Description |
|--------|-------------|
| `connect()` | Open TCP connection (auto-auth if configured) |
| `disconnect()` | Close the connection |
| `authenticate(token?)` | Authenticate with a bearer token |

### Inference

| Method | Returns | Description |
|--------|---------|-------------|
| `infer(req)` | `Promise<InferenceResponse>` | Complete inference |
| `inferStream(req)` | `InferenceStream` | Streaming inference |
| `inferText(req)` | `Promise<string>` | Stream accumulated to string |
| `batchInfer(reqs)` | `Promise<InferenceResponse[]>` | Sequential batch |

### Model Management

| Method | Returns | Description |
|--------|---------|-------------|
| `modelList()` | `Promise<ModelInfo[]>` | List registered models |
| `modelLoad(path, opts?)` | `Promise<ModelLoadResponse>` | Load a model |
| `modelUnload(id)` | `Promise<void>` | Unload a model |

### Context Store

| Method | Returns | Description |
|--------|---------|-------------|
| `contextStore(sessionId, key, value, ttl?)` | `Promise<void>` | Store a value |
| `contextRetrieve(sessionId, key)` | `Promise<Buffer \| null>` | Retrieve a value |

### Status & Health

| Method | Returns | Description |
|--------|---------|-------------|
| `status()` | `Promise<SystemStatus>` | Full daemon status |
| `health()` | `Promise<HealthStatus>` | Quick health check |
| `rateLimitStatus()` | `Promise<RateLimitStatus>` | Rate limit info |
| `ping()` | `Promise<boolean>` | Reachability check |

---

## Streaming

The `inferStream()` method returns an `InferenceStream` (EventEmitter):

```typescript
const stream = client.inferStream({
  prompt: 'Write a story',
  temperature: 0.8,
});

stream.on('data', (chunk: string) => process.stdout.write(chunk));
stream.on('progress', (tokens: number, elapsed: number) => {
  console.log(`\n[Generated ${tokens} tokens in ${elapsed}ms]`);
});
stream.on('end', () => console.log('\n[Done]'));
stream.on('error', (err: Error) => console.error(err));

// Or accumulate to a string
const fullText = await accumulateStream(stream);
```

---

## Error Handling

All errors extend `AinosError`:

```typescript
import {
  AinosError,
  ConnectionError,
  AuthError,
  RateLimitError,
  InferenceError,
  TimeoutError,
  DaemonError,
} from 'ainos-sdk';

try {
  await client.infer({ prompt: 'Hello' });
} catch (err) {
  if (err instanceof AuthError) {
    // Handle auth failure (401)
  } else if (err instanceof RateLimitError) {
    // Handle rate limit (429)
    console.log(`Retry after ${err.retryAfter}s`);
  } else if (err instanceof ConnectionError) {
    // Handle connection failure
  } else if (err instanceof TimeoutError) {
    // Handle timeout
  } else if (err instanceof InferenceError) {
    // Handle inference failure
  }
}
```

---

## Examples

See [`examples/basic.ts`](./examples/basic.ts) for complete examples:

```bash
# Run all examples
npx ts-node examples/basic.ts

# Run a specific example
npx ts-node examples/basic.ts 1   # Basic inference
npx ts-node examples/basic.ts 2   # Streaming inference
npx ts-node examples/basic.ts 4   # Model management
npx ts-node examples/basic.ts 5   # System status
```

---

## Protocol

The SDK communicates with the Ainos daemon over TCP using NDJSON
(newline-delimited JSON). Each message is a JSON object on a single line,
terminated by `\n`.

### Message Types

| Direction | Type | Description |
|-----------|------|-------------|
| Client → Server | `Auth` | Bearer token authentication |
| Server → Client | `AuthResponse` | Authentication result |
| Client → Server | `Inference` | Inference request |
| Server → Client | `InferenceResponse` | Complete inference result |
| Client → Server | `InferenceStream` | Streaming inference request |
| Server → Client | `InferenceChunk` | Streaming chunk |
| Client → Server | `ModelList` | List models |
| Server → Client | `ModelListResponse` | Model list |
| Client → Server | `ModelLoad` | Load model |
| Server → Client | `ModelLoadResponse` | Load result |
| Client → Server | `ModelUnload` | Unload model |
| Server → Client | `ModelUnloadResponse` | Unload result |
| Client → Server | `Status` | System status |
| Server → Client | `StatusResponse` | Status info |
| Client → Server | `ContextStore` | Store context |
| Client → Server | `ContextRetrieve` | Retrieve context |
| Server → Client | `Error` | Error response |

---

## Development

```bash
# Install dependencies
npm install

# Build
npm run build

# Run tests
npm test

# Run tests with coverage
npm run test:coverage
```

## Project Structure

```
bindings/node/
├── package.json
├── tsconfig.json
├── README.md
├── src/
│   ├── index.ts         # Entry point / re-exports
│   ├── client.ts        # Main AinosClient class
│   ├── types.ts         # TypeScript interfaces
│   ├── transport.ts     # TCP transport / NDJSON framing
│   ├── stream.ts        # Streaming inference
│   ├── auth.ts          # Token management / authentication
│   ├── errors.ts        # Error class hierarchy
│   └── utils.ts         # Utilities
├── __tests__/
│   └── client.test.ts   # Jest test suite
└── examples/
    └── basic.ts         # Usage examples
```

---

## License

MIT

## See Also

- [Ainos OS](https://github.com/ainos-os/ainos) — The Ainos operating system
- [Python SDK](https://github.com/ainos-os/ainos/tree/main/userland/sdk/python)
  — Python client for the same daemon protocol