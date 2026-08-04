# Ainos Java SDK

Java SDK for the Ainos AI Daemon TCP/IP protocol. Provides a thread-safe,
feature-complete client for communicating with the Ainos daemon over
newline-delimited JSON (NDJSON) via TCP.

## Prerequisites

- Java 11 or later
- A running Ainos AI Daemon (default: `127.0.0.1:9500`)

## Maven Dependency

Add the following to your `pom.xml`:

```xml
<dependency>
    <groupId>com.ainos</groupId>
    <artifactId>ainos-sdk</artifactId>
    <version>1.0.0</version>
</dependency>
```

## Quick Start

### Basic Usage

```java
import com.ainos.sdk.AinosClient;
import com.ainos.sdk.models.*;

// Create a client and connect
AinosClient client = AinosClient.builder()
    .host("127.0.0.1")
    .port(9500)
    .build();

client.connect();

// Run inference
InferenceRequest req = InferenceRequest.builder()
    .prompt("Hello, Ainos!")
    .model("default")
    .temperature(0.7)
    .maxTokens(512)
    .build();

InferenceResponse resp = client.infer(req);
System.out.println(resp.getOutput());

// Check daemon status
SystemStatus status = client.status();
System.out.println("Uptime: " + status.getUptime() + "s");

// Clean up
client.close();
```

### With Authentication

```java
AinosClient client = AinosClient.builder()
    .host("127.0.0.1")
    .port(9500)
    .authToken("your-bearer-token")
    .build();

// Connects and authenticates automatically
client.connect();
```

### Streaming Inference

```java
InferenceRequest req = InferenceRequest.of("Tell me a story");

try (InferenceStream stream = client.inferStream(req)) {
    for (InferenceChunk chunk : stream) {
        System.out.print(chunk.getChunk());
        if (chunk.isDone()) break;
    }
}
```

### Reactive Subscriber

```java
StreamSubscriber subscriber = new StreamSubscriber();

// In background thread:
new Thread(() -> stream.subscribe(subscriber)).start();

// In main thread:
InferenceChunk chunk;
while ((chunk = subscriber.poll(1, TimeUnit.SECONDS)) != null) {
    System.out.print(chunk.getChunk());
}
```

## API Reference

### Client Configuration

| Method | Default | Description |
|--------|---------|-------------|
| `host(String)` | `127.0.0.1` | Daemon hostname or IP |
| `port(int)` | `9500` | Daemon TCP port |
| `connectTimeoutMs(int)` | `5000` | Connection timeout (ms) |
| `readTimeoutMs(int)` | `120000` | Read/socket timeout (ms) |
| `autoReconnect(boolean)` | `true` | Auto-reconnect on failure |
| `reconnectDelayMs(int)` | `1000` | Base reconnect delay (ms) |
| `maxReconnectAttempts(int)` | `3` | Max reconnect attempts |
| `authToken(String)` | `null` | Bearer token for auth |
| `autoAuthenticate(boolean)` | `true` | Auto-auth after connect |
| `useConnectionPool(boolean)` | `false` | Enable connection pooling |
| `poolSize(int)` | `4` | Max pool connections |

### Client Methods

| Method | Description |
|--------|-------------|
| `connect()` | Establish TCP connection |
| `disconnect()` | Close connection |
| `close()` | Close and release resources |
| `authenticate(token)` | Authenticate with bearer token |
| `infer(request)` | Synchronous inference |
| `inferStream(request)` | Streaming inference |
| `batchInfer(requests)` | Batch inference |
| `status()` | Daemon health and statistics |
| `health()` | Health check (exception-safe) |
| `modelList()` | List registered models |
| `modelLoad(path, opts)` | Load a model |
| `modelUnload(id)` | Unload a model |
| `contextStore(session, key, value, ttl)` | Store context data |
| `contextRetrieve(session, key)` | Retrieve context data |
| `rateLimitStatus()` | Query rate limit status |

### Model Classes

All model classes are in `com.ainos.sdk.models`:

- **InferenceRequest** — Request parameters with Builder pattern
- **InferenceResponse** — Response with output and usage stats
- **InferenceChunk** — Streaming chunk
- **ModelInfo** — Model metadata
- **SystemStatus** — Daemon health and statistics
- **HealthStatus** — Health check result
- **RateLimitStatus** — Per-category rate limit info
- **ModelLoadOptions** — Model loading options with Builder
- **AinosException** — Base exception
- **AinosConnectionException** — Connection errors
- **AinosAuthException** — Authentication errors
- **AinosInferenceException** — Inference errors
- **AinosTimeoutException** — Timeout errors
- **AinosRateLimitException** — Rate limit errors

## Protocol

The SDK communicates with the Ainos daemon over TCP using
newline-delimited JSON (NDJSON). Each message is a JSON object with
a `type` field for discrimination, terminated by a newline character.

### Request Types

| Type | Fields | Description |
|------|--------|-------------|
| `Auth` | `token` | Authenticate session |
| `Inference` | `model`, `prompt`, `temperature`, `max_tokens`, `session_id` | Inference request |
| `InferenceStream` | `model`, `prompt`, `temperature`, `max_tokens`, `session_id` | Streaming inference |
| `ModelList` | (none) | List models |
| `ModelLoad` | `path`, `...opts` | Load model |
| `ModelUnload` | `model_id` | Unload model |
| `Status` | (none) | Query daemon status |
| `RateLimitStatus` | (none) | Query rate limits |
| `ContextStore` | `session_id`, `key`, `value`, `ttl` | Store context |
| `ContextRetrieve` | `session_id`, `key` | Retrieve context |

### Response Types

| Type | Fields | Description |
|------|--------|-------------|
| `AuthResponse` | `success`, `session_token`, `message`, `permissions`, `session_ttl_seconds` | Auth result |
| `InferenceResponse` | `output`, `tokens_generated`, `inference_ms`, `source` | Inference result |
| `InferenceChunk` | `chunk`, `done` | Stream chunk |
| `ModelListResponse` | `models` | Model list |
| `ModelLoadResponse` | `model_id`, `status`, `message`, `model_info` | Load result |
| `ModelUnloadResponse` | `model_id`, `status`, `message` | Unload result |
| `StatusResponse` | `uptime`, `models_loaded`, `total_requests`, `network_available`, `active_sessions`, `rate_limits` | Daemon status |
| `RateLimitStatusResponse` | `limits` | Rate limit info |
| `Error` | `code`, `message` | Error response |

## Thread Safety

All public methods of `AinosClient` are thread-safe and can be called
concurrently from multiple threads. The client uses internal locking
to serialize access to the underlying TCP connection.

## Connection Pooling

For high-throughput applications, enable connection pooling:

```java
AinosClient client = AinosClient.builder()
    .useConnectionPool(true)
    .poolSize(8)
    .build();
```

This maintains multiple TCP connections to the daemon, allowing
concurrent operations without head-of-line blocking.

## Error Handling

All SDK methods throw typed exceptions:

- `AinosConnectionException` — Network-level errors
- `AinosTimeoutException` — Operation timeout
- `AinosAuthException` — Authentication failures
- `AinosInferenceException` — Inference errors
- `AinosRateLimitException` — Rate limit exceeded

All exceptions extend `AinosException`, which can be caught for
general error handling.

## Building

```bash
# Build the JAR
mvn clean package

# Run tests
mvn test

# Install to local Maven repository
mvn clean install

# Generate Javadoc
mvn javadoc:javadoc
```

## Project Structure

```
bindings/java/
├── pom.xml
├── README.md
└── src/
    ├── main/java/com/ainos/sdk/
    │   ├── AinosClient.java              # Main client class
    │   ├── AinosClientBuilder.java        # Client builder
    │   ├── models/
    │   │   ├── AinosException.java        # Base exception
    │   │   ├── AinosConnectionException.java
    │   │   ├── AinosAuthException.java
    │   │   ├── AinosRateLimitException.java
    │   │   ├── AinosInferenceException.java
    │   │   ├── AinosTimeoutException.java
    │   │   ├── InferenceRequest.java      # Request with builder
    │   │   ├── InferenceResponse.java     # Response with stats
    │   │   ├── InferenceChunk.java        # Streaming chunk
    │   │   ├── ModelInfo.java             # Model metadata
    │   │   ├── SystemStatus.java          # Daemon status
    │   │   ├── HealthStatus.java          # Health check
    │   │   ├── RateLimitStatus.java       # Rate limit info
    │   │   └── ModelLoadOptions.java      # Load options
    │   ├── transport/
    │   │   ├── TcpTransport.java          # Transport interface
    │   │   ├── TcpTransportImpl.java      # TCP implementation
    │   │   ├── TransportFactory.java      # Transport factory
    │   │   ├── JsonCodec.java             # JSON codec
    │   │   └── ConnectionPool.java        # Connection pool
    │   └── stream/
    │       ├── InferenceStream.java       # Stream with Iterable
    │       ├── StreamReader.java          # Chunk reader
    │       └── StreamSubscriber.java      # Reactive subscriber
    └── test/java/com/ainos/sdk/
        ├── AinosClientTest.java           # Mock server tests
        ├── InferenceRequestTest.java      # Builder tests
        ├── JsonCodecTest.java             # Serialization tests
        └── StreamTest.java                # Streaming tests
```

## License

Same license as the Ainos project.