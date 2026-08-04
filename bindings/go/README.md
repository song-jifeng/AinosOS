# Ainos Go SDK

A zero-dependency Go SDK for the [Ainos AI Daemon](https://ainos.io) -- connect,
infer, and manage AI models over TCP/IP using the newline-delimited JSON (NDJSON)
protocol.

## Features

- **Zero external dependencies** -- stdlib only
- **Thread-safe** -- all public methods are safe for concurrent use
- **Streaming inference** -- receive token chunks as they are generated
- **Authentication** -- bearer token auth with session management
- **Model management** -- list, load, and unload models
- **Context storage** -- persist and retrieve key-value pairs
- **Rate limiting** -- query and handle rate limits
- **Auto-reconnect** -- exponential backoff reconnection
- **Connection pooling** -- for concurrent batch operations
- **TLS support** -- optional TLS encryption
- **Context support** -- standard Go context for cancellation and timeouts

## Installation

### As a Go module dependency

```bash
# In your go.mod
require github.com/ainos/ainos-go/ainos v0.1.0
```

Or use the local copy:

```bash
go get ainos/ainos
```

### From source

```bash
cd D:/Ainos/bindings/go/ainos
go build ./...
```

## Quick Start

```go
package main

import (
    "context"
    "fmt"
    "log"
    "ainos/ainos"
)

func main() {
    // Create a client (defaults to 127.0.0.1:9500)
    client := ainos.NewClient()
    if err := client.Connect(); err != nil {
        log.Fatal(err)
    }
    defer client.Disconnect()

    // Send an inference request
    ctx := context.Background()
    resp, err := client.Infer(ctx, &ainos.InferenceRequest{
        Prompt: "Hello, Ainos!",
        Model:  "default",
    })
    if err != nil {
        log.Fatal(err)
    }

    fmt.Println(resp.Text)
}
```

## API Reference

### Client Creation

```go
// Default client (127.0.0.1:9500)
client := ainos.NewClient()

// Custom client with options
client := ainos.NewClient(
    ainos.WithHost("192.168.1.100"),
    ainos.WithPort(9500),
    ainos.WithConnectTimeout(3 * time.Second),
    ainos.WithReadTimeout(120 * time.Second),
    ainos.WithAuthToken("your-token"),
    ainos.WithAutoReconnect(true),
    ainos.WithTLS(true),
)
```

### Client Options

| Option | Description | Default |
|--------|-------------|---------|
| `WithHost(host)` | Daemon hostname | `127.0.0.1` |
| `WithPort(port)` | Daemon TCP port | `9500` |
| `WithConnectTimeout(d)` | Connection timeout | `5s` |
| `WithReadTimeout(d)` | Read timeout | `120s` |
| `WithWriteTimeout(d)` | Write timeout | `10s` |
| `WithTimeout(d)` | Set both connect and read timeout | -- |
| `WithAutoReconnect(enabled)` | Auto-reconnect on failure | `true` |
| `WithReconnectDelay(d)` | Initial reconnect delay | `1s` |
| `WithMaxReconnectAttempts(n)` | Max reconnect attempts | `5` |
| `WithAuthToken(token)` | Bearer token | `""` |
| `WithAutoAuthenticate(enabled)` | Auto-auth on connect | `true` |
| `WithTLS(enabled)` | Enable TLS | `false` |
| `WithTLSInsecureSkipVerify(skip)` | Skip TLS verification | `false` |
| `WithRetryConfig(rc)` | Retry configuration | 3 retries, 100ms base |

### Request Options

```go
// Using the builder pattern
req := ainos.NewRequest("Your prompt",
    ainos.WithTemperature(0.7),
    ainos.WithTopP(0.9),
    ainos.WithTopK(50),
    ainos.WithMaxTokens(1024),
    ainos.WithStop([]string{"\n"}),
    ainos.WithModel("default"),
    ainos.WithSessionID("session-123"),
)
```

### Client Methods

#### Connection

```go
err := client.Connect()
err := client.Disconnect()
err := client.Reconnect()
ok := client.IsConnected()
```

#### Authentication

```go
resp, err := client.Authenticate(token)
session := client.Session()
ok := client.IsAuthenticated()
ok := client.HasPermission("infer")
```

#### Inference

```go
// Synchronous inference
resp, err := client.Infer(ctx, &ainos.InferenceRequest{
    Prompt: "Hello",
    Model:  "default",
})

// Streaming inference
chunks, err := client.InferStream(ctx, req)
for chunk := range chunks {
    fmt.Print(chunk.Text)
}
```

#### Model Management

```go
models, err := client.ModelList()
info, err := client.ModelLoad(path, opts)
err := client.ModelUnload(id)
```

#### Context Storage

```go
err := client.ContextStore(sessionID, key, value, ttl)
value, err := client.ContextRetrieve(sessionID, key)
```

#### System

```go
status, err := client.Status()
health, err := client.Health()
rateLimit, err := client.RateLimitStatus()
```

#### Batch Operations

```go
responses, err := client.BatchInfer(ctx, []*ainos.InferenceRequest{req1, req2, req3})
```

### Error Handling

```go
_, err := client.Infer(ctx, req)
if err != nil {
    if ainos.IsConnectionError(err) {
        // Handle connection error
    } else if ainos.IsAuthError(err) {
        // Handle authentication error
    } else if ainos.IsTimeout(err) {
        // Handle timeout
    } else if ainos.IsRateLimited(err) {
        // Handle rate limit
    } else if code, ok := ainos.DaemonCode(err); ok {
        fmt.Printf("Daemon error code: %d\n", code)
    }
}
```

### Error Types

| Type | Description |
|------|-------------|
| `*ConnectionError` | Connection refused or lost |
| `*AuthError` | Authentication failed |
| `*PermissionError` | Permission denied |
| `*RateLimitError` | Rate limit exceeded |
| `*InferenceError` | Inference request failed |
| `*TimeoutError` | Operation timed out |
| `*ProtocolError` | Unexpected response from daemon |
| `*Error` | Generic daemon error with code |

## Protocol

The SDK communicates with the Ainos daemon over TCP using newline-delimited JSON
(NDJSON). Each message is a single JSON object terminated by a newline character.

The message format uses a `type` field for discrimination (serde tag), matching
the Rust daemon's `IpcMessage` enum. Supported message types include:

- `Auth` / `AuthResponse`
- `Inference` / `InferenceResponse`
- `InferenceStream` / `InferenceChunk`
- `ModelList` / `ModelListResponse`
- `ModelLoad` / `ModelLoadResponse`
- `ModelUnload` / `ModelUnloadResponse`
- `ContextStore` / `ContextRetrieve`
- `Status` / `StatusResponse`
- `RateLimitStatus`
- `Error`

## Testing

```bash
cd D:/Ainos/bindings/go/ainos
go test -v ./...
```

The tests include a mock TCP server that simulates the daemon's protocol, so
no actual daemon is required.

## Running Examples

```bash
cd D:/Ainos/bindings/go/ainos
go run examples/basic_usage.go
```

Note: The examples require a running Ainos daemon on `127.0.0.1:9500` for most
operations to succeed.

## Project Structure

```
bindings/go/
├── go.mod                  # Root module
├── README.md               # This file
└── ainos/
    ├── go.mod              # Package module
    ├── client.go           # Main client implementation
    ├── types.go            # Type definitions
    ├── errors.go           # Error types and classification
    ├── transport.go        # NDJSON transport layer
    ├── auth.go             # Authentication and session management
    ├── options.go          # Builder pattern for request/client options
    ├── stream.go           # Streaming inference support
    ├── ainos_test.go       # Comprehensive test suite
    └── examples/
        └── basic_usage.go  # Usage examples
```

## License

MIT License -- see the [LICENSE](../../LICENSE) file for details.