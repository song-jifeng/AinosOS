# Ainos Kotlin SDK

A type-safe, coroutine-based Kotlin SDK for the **Ainos inference daemon**. Provides a complete client library for interacting with Ainos over TCP using the NDJSON protocol.

## Features

- **Coroutine-native** - All API methods are suspend functions or return `Flow` for streaming
- **Type-safe** - Full `kotlinx.serialization` integration with well-typed request/response models
- **Streaming inference** - Real-time token-by-token generation via Kotlin `Flow`
- **Model management** - List, load, and unload models on the daemon
- **Health monitoring** - Check daemon health, get detailed server status, wait for readiness
- **Context management** - Store and retrieve long-term memory/context data
- **Authentication** - Bearer token authentication with runtime token updates
- **Comprehensive error handling** - Typed exception hierarchy for all failure modes
- **Thread-safe** - Designed for concurrent use from multiple coroutines

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  AinosClient (high-level API)                               │
│  ┌───────────┬──────────────┬───────────┬────────────────┐  │
│  │ Inference │ Model Mgmt   │ Health    │ Context Mgmt   │  │
│  │ infer()   │ modelList()  │ health()  │ contextStore() │  │
│  │ inferStream() │ modelLoad() │ status() │ contextRetrieve()│
│  └───────────┴──────────────┴───────────┴────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  Transport (NDJSON TCP)                                     │
│  - Request/response matching by ID                          │
│  - Streaming via ReceiveChannel                             │
│  - Thread-safe send/receive loop                            │
├─────────────────────────────────────────────────────────────┤
│  AuthenticationManager                                      │
│  - Bearer token management                                 │
│  - Listener notifications                                   │
└─────────────────────────────────────────────────────────────┘
```

## Protocol

The SDK communicates with the Ainos daemon over **TCP** using **NDJSON** (Newline-Delimited JSON):

```
Request:  {"id":"req-1","method":"infer","params":{...},"token":"..."}
Response: {"id":"req-1","type":"result","data":{...}}
Stream:   {"id":"req-1","type":"stream","data":{...}}
StreamEnd:{"id":"req-1","type":"stream_end","data":{...}}
Error:    {"id":"req-1","type":"error","error":{"code":-1,"message":"..."}}
```

Default port: **9500**

## Quick Start

### Installation

Add to your `build.gradle.kts`:

```kotlin
repositories {
    mavenCentral()
}

dependencies {
    implementation("com.ainos:ainos-sdk:1.0.0")
}
```

### Basic Usage

```kotlin
import com.ainos.sdk.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*

suspend fun main() {
    val client = AinosClient(
        ClientConfig {
            host("localhost")
            port(9500)
            token("your-bearer-token")
        }
    )

    client.connect()

    // Non-streaming inference
    val result = client.infer("What is machine learning?")
    println(result.text)

    // Streaming inference
    client.inferStream("Tell me a story about AI").collect { chunk ->
        print(chunk.text)
    }

    client.disconnect()
}
```

## API Reference

### Connection Management

| Method | Description |
|--------|-------------|
| `connect()` | Establishes TCP connection to the daemon |
| `disconnect()` | Gracefully closes the connection |
| `ensureConnected()` | Connects if not already connected |
| `isConnected` | Returns whether the client is connected |

### Inference

| Method | Returns | Description |
|--------|---------|-------------|
| `infer(prompt, params)` | `InferResult` | Non-streaming inference |
| `inferStream(prompt, params)` | `Flow<StreamChunk>` | Streaming inference |
| `inferWithSession(prompt, sessionId, params)` | `InferResult` | Inference with conversation session |

### Model Management

| Method | Returns | Description |
|--------|---------|-------------|
| `modelList()` | `List<ModelInfo>` | List all available models |
| `modelLoad(params)` | `ModelInfo` | Load a model into memory |
| `modelLoad(name)` | `ModelInfo` | Load model by name |
| `modelUnload(name)` | `ModelUnloadResult` | Unload a model from memory |

### Health & Status

| Method | Returns | Description |
|--------|---------|-------------|
| `health()` | `HealthInfo` | Check daemon health |
| `status()` | `ServerStatus` | Get detailed server status |
| `waitForHealthy(maxWaitMs, pollIntervalMs)` | `Boolean` | Wait for daemon to be healthy |

### Context Management

| Method | Returns | Description |
|--------|---------|-------------|
| `contextStore(content, metadata, model)` | `String` | Store context data |
| `contextStore(context)` | `String` | Store ContextData object |
| `contextRetrieve(id)` | `ContextData` | Retrieve context by ID |

### Low-Level API

| Method | Returns | Description |
|--------|---------|-------------|
| `rawRequest(method, params)` | `JsonElement` | Send raw RPC request |
| `rawRequestStream(method, params)` | `ReceiveChannel<JsonElement>` | Send raw streaming request |

## Configuration

### ClientConfig

| Property | Default | Description |
|----------|---------|-------------|
| `host` | `"localhost"` | Daemon hostname |
| `port` | `9500` | Daemon TCP port |
| `token` | `null` | Bearer authentication token |
| `connectTimeoutMs` | `10000` | Connection timeout (ms) |
| `readTimeoutMs` | `60000` | Read timeout (ms) |
| `requestTimeoutMs` | `120000` | Request timeout (ms) |
| `autoReconnect` | `false` | Auto-reconnect on disconnect |
| `maxReconnectAttempts` | `3` | Max reconnection attempts |
| `reconnectDelayMs` | `1000` | Base reconnect delay (ms) |

### Builder Pattern

```kotlin
val config = ClientConfig.Builder()
    .host("192.168.1.100")
    .port(9500)
    .token("my-secret-token")
    .connectTimeoutMs(5000)
    .build()
```

### DSL

```kotlin
val config = ClientConfig {
    host("192.168.1.100")
    port(9500)
    token("my-secret-token")
}
```

## Streaming

Streaming inference uses Kotlin `Flow` for reactive, backpressure-aware consumption:

```kotlin
// Real-time printing
client.inferStream("Write a poem")
    .collect { chunk -> print(chunk.text) }

// Collect to string
val fullText = Streaming.collectText(client.inferStream("Hello"))

// With callback
val text = Streaming.collectWithCallback(
    client.inferStream("Tell me a story")
) { chunk -> updateUI(chunk.text) }

// Text-only chunks (empty filtered)
client.inferStream("Hi").textOnly().collect { text -> println(text) }

// Final chunk only
client.inferStream("Hello").finalChunk().collect { chunk ->
    println("Finished: ${chunk.finishReason}")
}
```

## Error Handling

The SDK provides a typed exception hierarchy:

```kotlin
try {
    client.connect()
    val result = client.infer("Hello")
} catch (e: AinosException.ConnectionException) {
    // Daemon unreachable
} catch (e: AinosException.AuthenticationException) {
    // Invalid token
} catch (e: AinosException.TimeoutException) {
    // Request timed out
} catch (e: AinosException.ApiException) {
    // Daemon returned error (e.code, e.message)
} catch (e: AinosException.ModelException) {
    // Model operation failed
} catch (e: AinosException.StreamException) {
    // Streaming error
} catch (e: AinosException.ProtocolException) {
    // Protocol violation
} catch (e: AinosException.InvalidStateException) {
    // Not connected
}
```

## Thread Safety

The `AinosClient` and `Transport` are designed for concurrent use. Multiple coroutines can call API methods simultaneously. The internal receive loop runs on a dedicated thread, and response matching uses concurrent data structures.

## Testing

The SDK includes a `MockDaemon` for integration testing without a running daemon:

```kotlin
class MyTest {
    private lateinit var mockDaemon: MockDaemon
    private lateinit var client: AinosClient

    @Before
    fun setup() {
        mockDaemon = MockDaemon()
        mockDaemon.start()
        mockDaemon.on("health") { _, _ ->
            listOf(MockDaemon.MockResponse(
                type = "result",
                data = json.parseToJsonElement("""{"status":"ok"}""")
            ))
        }
        client = AinosClient(ClientConfig(port = mockDaemon.actualPort))
    }

    @Test
    fun testHealth() = runBlocking {
        client.connect()
        assertEquals("ok", client.health().status)
    }

    @After
    fun teardown() {
        client.disconnect()
        mockDaemon.stop()
    }
}
```

## Examples

### AutoCloseable Usage

```kotlin
AinosClient(config).use { client ->
    client.connect()
    val result = client.infer("Hello")
    println(result.text)
}
```

### Session-Based Conversation

```kotlin
var sessionId: String? = null

val response1 = client.infer("My name is Alice")
sessionId = response1.sessionId

val response2 = client.inferWithSession(
    "What's my name?",
    sessionId = sessionId!!
)
println(response2.text) // "Your name is Alice."
```

### Wait for Daemon

```kotlin
if (client.waitForHealthy(maxWaitMs = 10_000)) {
    val result = client.infer("Ready!")
} else {
    println("Daemon not ready after 10 seconds")
}
```

## Project Structure

```
ainos-sdk/                    # Main SDK module
├── build.gradle.kts
└── src/main/kotlin/com/ainos/sdk/
    ├── AinosClient.kt        # Main client
    ├── Models.kt             # Data classes
    ├── Transport.kt          # TCP transport layer
    ├── Authentication.kt     # Authentication manager
    ├── Streaming.kt          # Flow utilities
    ├── Errors.kt             # Exception hierarchy
    └── Utils.kt              # Internal utilities

ainos-sdk-test/               # Test module
├── build.gradle.kts
└── src/test/kotlin/com/ainos/sdk/
    ├── AinosClientTest.kt    # Comprehensive tests
    └── MockDaemon.kt         # Mock daemon for testing

examples/
└── Main.kt                   # Example application

settings.gradle.kts
gradle.properties
README.md
```

## Building

```bash
# Build the SDK
./gradlew :ainos-sdk:build

# Run tests
./gradlew :ainos-sdk-test:test

# Generate documentation
./gradlew :ainos-sdk:dokkaHtml

# Run example
./gradlew :examples:run --args="localhost 9500 your-token"
```

## Requirements

- Kotlin 1.9+
- JVM 17+
- Ainos daemon running on port 9500 (default)

## License

Copyright (c) 2026 Ainos. All rights reserved.