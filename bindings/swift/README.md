# Ainos SDK for Swift

A Swift SDK for communicating with the Ainos AI daemon over TCP using NDJSON (Newline-Delimited JSON).

## Requirements

- Swift 5.9+
- macOS 13.0+ / iOS 16.0+ / tvOS 16.0+ / watchOS 9.0+ / visionOS 1.0+
- Ainos daemon running on a reachable host (default: `127.0.0.1:9500`)

## Installation

### Swift Package Manager

Add the following to your `Package.swift`:

```swift
dependencies: [
    .package(url: "https://github.com/ainos/bindings-swift.git", from: "1.0.0")
]
```

Then add `AinosSDK` as a dependency to your target:

```swift
.target(
    name: "YourTarget",
    dependencies: ["AinosSDK"]
)
```

### Xcode

1. File > Add Package Dependencies...
2. Enter: `https://github.com/ainos/bindings-swift.git`
3. Select version rule: Up to Next Major (1.0.0)

## Quick Start

```swift
import AinosSDK

// Create a client
let client = AinosClient(config: AinosClientConfig(
    host: "127.0.0.1",
    port: 9500,
    token: "your-token"
))

// Connect to the daemon
try await client.connect()

// Basic inference
let response = try await client.infer(
    model: "your-model",
    prompt: "Hello, world!"
)
print(response.text)

// Streaming inference
let stream = try await client.inferStream(
    model: "your-model",
    prompt: "Write a story"
)
for try await event in stream {
    print(event.delta ?? "", terminator: "")
}

// Disconnect when done
await client.disconnect()
```

## API Reference

### Client

| Method | Description |
|--------|-------------|
| `connect()` | Connect to the Ainos daemon |
| `disconnect()` | Disconnect from the daemon |
| `infer(model:prompt:messages:config:sessionId:)` | Non-streaming inference |
| `inferStream(model:prompt:messages:config:sessionId:)` | Streaming inference |
| `modelList()` | List available models |
| `modelLoad(model:config:)` | Load a model into memory |
| `modelUnload(model:)` | Unload a model from memory |
| `health()` | Check daemon health |
| `status()` | Get daemon status |
| `contextStore(key:value:ttlSeconds:overwrite:)` | Store context data |
| `contextRetrieve(key:)` | Retrieve stored context |

### Convenience Methods

| Method | Description |
|--------|-------------|
| `chat(model:messages:config:)` | Chat-style inference |
| `chatStream(model:messages:config:)` | Streaming chat-style inference |
| `generate(model:prompt:config:)` | Inference returning only the text |
| `isHealthy()` | Quick health check returning Bool |

### Configuration

```swift
let config = AinosClientConfig(
    host: "127.0.0.1",      // Daemon host
    port: 9500,               // Daemon port
    token: "your-token",      // Authentication token
    connectionTimeout: 10,    // Connection timeout (seconds)
    readTimeout: 60,          // Read timeout (seconds)
    maxReconnectAttempts: 3,  // Max reconnection attempts
    reconnectDelay: 1.0,      // Delay between reconnects
    verbose: false            // Enable verbose logging
)
```

## Protocol

The SDK communicates with the daemon over TCP using NDJSON:

```
Request:  {"type":"infer","request_id":"...","timestamp":"...","payload":{...}}\n
Response: {"type":"response","request_id":"...","timestamp":"...","payload":{...}}\n
```

### Authentication

Authentication uses Bearer tokens sent in the `Authorization` header:

```swift
let auth = BearerTokenAuthenticator(token: "your-token")
```

For anonymous access (no authentication required):

```swift
let auth = AnonymousAuthenticator()
```

## Streaming

Streaming inference returns an `InferenceStream` that conforms to `AsyncSequence`:

```swift
let stream = try await client.inferStream(model: "model", prompt: "Hello")

// Iterate over events
for try await event in stream {
    switch event.type {
    case .token:
        print(event.delta ?? "", terminator: "")
    case .done:
        print("\n[Done]")
    case .error:
        print("\n[Error]")
    default:
        break
    }
}

// Or use convenience operators
let text = try await stream.textDeltas().collectText()
```

## Error Handling

All errors are thrown as `AinosError` with machine-readable codes:

```swift
do {
    let response = try await client.infer(model: "model", prompt: "Hi")
} catch let error as AinosError {
    switch error.code {
    case .connectionRefused:
        // Daemon not running
    case .authenticationFailed:
        // Invalid token
    case .modelNotFound:
        // Model not available
    default:
        // General error
    }
}
```

## Logging

The SDK includes a built-in logger:

```swift
Logger.currentLevel = .debug  // Enable debug logging
Logger.includeTimestamps = true
Logger.debug("Custom debug message")
Logger.info("Informational message")
Logger.warning("Warning message")
Logger.error("Error message", error: someError)
```

## Running Tests

```bash
cd path/to/AinosSDK
swift test
```

## Running the Example

```bash
cd path/to/AinosSDK
swift run AinosSDKExample --token "your-token"
```

## License

Apache License 2.0