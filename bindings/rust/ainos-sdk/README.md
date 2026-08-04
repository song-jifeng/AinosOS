# Ainos SDK — Rust

A complete async Rust SDK for the [Ainos AI Daemon](https://github.com/ainos-os/ainos).
Communicates over TCP/IP port 9500 using the newline-delimited JSON (NDJSON)
protocol — the same protocol used by the daemon's built-in IPC server.

## Features

- **Async/await** — Built on tokio for high-performance async I/O
- **Inference** — Sync and streaming inference with builder-pattern requests
- **Model Management** — List, load, and unload models
- **Context Store** — Key-value persistence with session scoping
- **Authentication** — Token-based auth with session management
- **Auto-reconnect** — Exponential backoff with configurable retry
- **Streaming** — Token-by-token streaming with backpressure and cancellation
- **Thread-safe** — `Send + Sync`, shareable via `Arc`
- **Comprehensive Errors** — Typed error enum with retry classification
- **Zeroize** — Sensitive tokens are zeroed on drop
- **Mock Transport** — Built-in mock for testing without a daemon

## Quick Start

Add to your `Cargo.toml`:

```toml
[dependencies]
ainos-sdk = "0.1"
tokio = { version = "1", features = ["full"] }
```

### Basic Inference

```rust
use ainos_sdk::{AinosClient, InferenceRequest};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let client = AinosClient::builder()
        .host("127.0.0.1")
        .port(9500)
        .auth_token("your-token")
        .build();

    client.connect().await?;

    let resp = client.infer(
        &InferenceRequest::builder()
            .prompt("Hello, Ainos!")
            .temperature(0.7)
            .max_tokens(512)
            .build()
    ).await?;

    println!("{}", resp.output);
    client.disconnect().await?;
    Ok(())
}
```

### Streaming Inference

```rust
use ainos_sdk::prelude::*;

async fn stream_example(client: &AinosClient) -> Result<()> {
    let req = InferenceRequest::builder()
        .prompt("Tell me a story")
        .max_tokens(1000)
        .build();

    let mut stream = client.infer_stream(&req).await?;

    while let Some(chunk) = stream.next().await {
        match chunk {
            Ok(c) => {
                print!("{}", c.chunk);
                if c.done { break; }
            }
            Err(e) => eprintln!("Error: {}", e),
        }
    }
    Ok(())
}
```

## API Reference

### Client

| Method | Description |
|--------|-------------|
| `AinosClient::builder()` | Create a builder for custom configuration |
| `client.connect()` | Connect to the daemon |
| `client.disconnect()` | Disconnect from the daemon |
| `client.reconnect()` | Reconnect with exponential backoff |
| `client.is_connected()` | Check if connected |
| `client.is_authenticated()` | Check if authenticated |
| `client.authenticate(token)` | Authenticate with a bearer token |
| `client.infer(req)` | Send an inference request |
| `client.infer_stream(req)` | Stream inference tokens |
| `client.batch_infer(reqs)` | Send multiple inference requests |
| `client.model_list()` | List all registered models |
| `client.model_load(path, opts)` | Load a model from disk |
| `client.model_unload(id)` | Unload a model from memory |
| `client.status()` | Query daemon system status |
| `client.health()` | Quick health check |
| `client.rate_limit_status()` | Query rate limit status |
| `client.context_store(session, key, value, ttl)` | Store context |
| `client.context_retrieve(session, key)` | Retrieve context |

### Types

| Type | Description |
|------|-------------|
| `InferenceRequest` | Inference request parameters (builder pattern) |
| `InferenceResponse` | Inference response with output and stats |
| `InferenceChunk` | Single streaming chunk |
| `InferenceStream` | Async stream of `InferenceChunk` |
| `ModelInfo` | Model metadata |
| `ModelLoadOptions` | Model load options (builder pattern) |
| `SystemStatus` | Daemon system status |
| `HealthStatus` | Daemon health check |
| `RateLimitStatus` | Rate limit information |
| `Session` | Authentication session |
| `ClientConfig` | Client configuration |

### Error Handling

All fallible methods return `Result<T, AinosError>` where `AinosError` is a
comprehensive enum covering all failure modes:

```rust
use ainos_sdk::AinosError;

match error {
    AinosError::ConnectionRefused(msg) => { /* retry */ }
    AinosError::ConnectionLost(msg) => { /* reconnect */ }
    AinosError::Timeout(dur) => { /* increase timeout */ }
    AinosError::AuthFailed(msg) => { /* check token */ }
    AinosError::DaemonError { code, message } => { /* handle daemon error */ }
    AinosError::RateLimited(msg) => { /* back off */ }
    _ => { /* fatal */ }
}
```

Errors can be classified for retry:

```rust
use ainos_sdk::error::Retryable;

if error.retry_kind().is_transient() {
    // Retry the operation
}
```

## Feature Flags

| Feature | Description |
|---------|-------------|
| `full` | All features enabled (default) |
| `streaming` | Streaming inference support |
| `tls` | TLS encrypted transport |
| `mock` | Mock transport for testing |

## Examples

Run the comprehensive example:

```bash
# Set environment variables (optional)
export AINOS_HOST=127.0.0.1
export AINOS_PORT=9500
export AINOS_TOKEN=your-token

cargo run --example basic
```

The example demonstrates:
- Basic inference
- Streaming inference
- Model management
- Context operations
- Status and health queries
- Rate limit status
- Batch inference
- Error handling
- Connection management

## Testing

```bash
# Run all tests (uses mock transport, no daemon needed)
cargo test

# Run with specific features
cargo test --features mock

# Run integration tests only
cargo test --test integration_test
```

## Protocol

The SDK communicates with the Ainos daemon over TCP port 9500 using
newline-delimited JSON (NDJSON). Each request is a single JSON line ending
with `\n`, and the response is also a single JSON line.

The JSON uses a `type` tag field for message discrimination, matching the
daemon's `#[serde(tag = "type")]` serialization.

### Request Format

```json
{"type":"Inference","model":"default","prompt":"Hello","temperature":0.7,"max_tokens":512}
```

### Response Format

```json
{"type":"InferenceResponse","output":"Hello!","tokens_generated":1,"inference_ms":50,"source":"local"}
```

## License

MIT