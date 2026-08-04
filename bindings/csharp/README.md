# Ainos .NET SDK

A complete C# .NET SDK for communicating with the **Ainos AI Daemon** over TCP/IP using the NDJSON (newline-delimited JSON) protocol.

## Overview

The Ainos daemon listens on TCP port **9500** and uses a simple JSON-line protocol. Each message is a single JSON object terminated by a newline. The daemon supports:

- **Inference** — synchronous and streaming
- **Model Management** — load, unload, and list models
- **Context Store** — key-value persistence with TTL support
- **System Status** — health, uptime, statistics
- **Rate Limiting** — per-category rate limit tracking
- **Authentication** — bearer token-based session management

## Installation

### NuGet

```xml
<PackageReference Include="AinosSdk" Version="1.0.0" />
```

### From source

```bash
git clone https://github.com/ainos/ainos.git
cd ainos/bindings/csharp
dotnet build
```

## Quick Start

### Simple inference

```csharp
using AinosSdk;
using AinosSdk.Configuration;

// Create and connect
var client = new AinosClient(new AinosClientOptions
{
    Host = "127.0.0.1",
    Port = 9500,
});
await client.ConnectAsync();

// Simple inference
var result = await client.InferSimpleAsync("What is the capital of France?");
Console.WriteLine(result);

// Clean up
await client.DisposeAsync();
```

### With authentication

```csharp
var client = new AinosClient(new AinosClientOptions
{
    Host = "127.0.0.1",
    Port = 9500,
    AuthToken = "your-bearer-token",
    AutoAuthenticate = true,
});
await client.ConnectAsync();

// Now authenticated for all requests
var status = await client.GetStatusAsync();
```

### Using the builder

```csharp
var client = AinosClientBuilder.Create("192.168.1.100", 9500)
    .WithAuthToken("my-token")
    .WithReadTimeout(TimeSpan.FromSeconds(60))
    .WithConnectionPool(maxPoolSize: 4)
    .BuildAndConnectAsync();
```

## API Reference

### AinosClient

The main class for all daemon interactions.

#### Connection

```csharp
// Connect (auto-authenticates if token is configured)
Task ConnectAsync(CancellationToken ct = default);

// Disconnect
Task DisconnectAsync();

// Authenticate with a bearer token
Task AuthenticateAsync(string token, CancellationToken ct = default);
```

#### Inference

```csharp
// Synchronous inference
Task<InferenceResponse> InferAsync(InferenceRequest request, CancellationToken ct = default);

// Streaming inference (returns IAsyncEnumerable<InferenceChunk>)
IAsyncEnumerable<InferenceChunk> InferStreamAsync(InferenceRequest request, CancellationToken ct = default);

// Convenience: simple text-in/text-out
Task<string> InferSimpleAsync(string prompt, string? model = null, CancellationToken ct = default);

// Convenience: streaming text-in/text-out
Task<string> InferStreamSimpleAsync(string prompt, string? model = null, CancellationToken ct = default);
```

#### Model Management

```csharp
// List all loaded models
Task<List<ModelInfo>> GetModelListAsync(CancellationToken ct = default);

// Load a model from disk
Task<ModelInfo> LoadModelAsync(string path, ModelLoadOptions? options = null, CancellationToken ct = default);

// Unload a model
Task UnloadModelAsync(string id, CancellationToken ct = default);
```

#### Context Store

```csharp
// Store a binary value
Task ContextStoreAsync(string sessionId, string key, byte[] value, long ttl = 0, CancellationToken ct = default);

// Store a string value
Task ContextStoreStringAsync(string sessionId, string key, string value, long ttl = 0, CancellationToken ct = default);

// Retrieve a binary value
Task<byte[]?> ContextRetrieveAsync(string sessionId, string key, CancellationToken ct = default);

// Retrieve a string value
Task<string?> ContextRetrieveStringAsync(string sessionId, string key, CancellationToken ct = default);
```

#### System

```csharp
// Get daemon status
Task<SystemStatus> GetStatusAsync(CancellationToken ct = default);

// Health check (never throws)
Task<HealthStatus> GetHealthAsync(CancellationToken ct = default);

// Rate limit status
Task<RateLimitStatus> GetRateLimitStatusAsync(CancellationToken ct = default);

// Batch inference
Task<List<InferenceResponse>> BatchInferAsync(List<InferenceRequest> requests, CancellationToken ct = default);
```

### InferenceRequest Builder

```csharp
var request = InferenceRequest.CreateBuilder("What is AI?")
    .WithModel("phi-3-mini")
    .WithTemperature(0.7f)
    .WithMaxTokens(500)
    .WithSessionId("my-session")
    .Build();
```

### ModelLoadOptions Builder

```csharp
var options = ModelLoadOptions.CreateBuilder()
    .WithSkipIfLoaded(true)
    .WithArchitecture("phi3")
    .WithGpuLayers(32)
    .WithContextSize(4096)
    .Build();
```

## Data Models

### InferenceResponse

| Field | Type | Description |
|-------|------|-------------|
| `Output` | `string` | Generated text |
| `TokensGenerated` | `int` | Number of tokens produced |
| `InferenceMs` | `long` | Wall-clock inference time in ms |
| `Source` | `string` | `"local"` or `"cloud"` |
| `Model` | `string?` | Model that produced the response |
| `SessionId` | `string?` | Associated session ID |

### InferenceChunk

| Field | Type | Description |
|-------|------|-------------|
| `Chunk` | `string` | Text chunk |
| `Done` | `bool` | Whether this is the final chunk |
| `Index` | `int` | Chunk index (0-based) |
| `Model` | `string?` | Model that produced the chunk |

### ModelInfo

| Field | Type | Description |
|-------|------|-------------|
| `Id` | `string` | Unique model identifier |
| `Name` | `string` | Human-readable file name |
| `Path` | `string` | Absolute file path on disk |
| `SizeMb` | `long` | Model file size in MB |
| `Loaded` | `bool` | Whether loaded in memory |
| `Architecture` | `string` | Architecture string |

### SystemStatus

| Field | Type | Description |
|-------|------|-------------|
| `Uptime` | `long` | Seconds since daemon started |
| `ModelsLoaded` | `int` | Models currently loaded |
| `TotalRequests` | `long` | Total inference requests |
| `NetworkAvailable` | `bool` | Internet reachable |
| `ActiveSessions` | `int` | Active client sessions |
| `RateLimits` | `List<RateLimitInfo>?` | Per-category rate limits |

## Configuration

### AinosClientOptions

| Property | Default | Description |
|----------|---------|-------------|
| `Host` | `"127.0.0.1"` | Daemon hostname |
| `Port` | `9500` | Daemon TCP port |
| `ConnectTimeout` | `5s` | Connection timeout |
| `ReadTimeout` | `120s` | Read response timeout |
| `SendTimeout` | `30s` | Send request timeout |
| `AutoReconnect` | `true` | Auto-reconnect on failure |
| `ReconnectDelay` | `1s` | Delay before reconnect |
| `MaxRetries` | `3` | Max retry attempts |
| `AuthToken` | `null` | Bearer token |
| `AutoAuthenticate` | `true` | Auto-auth on connect |
| `UseConnectionPool` | `false` | Enable connection pooling |
| `MaxPoolSize` | `8` | Max pool connections |
| `DefaultModel` | `"default"` | Default inference model |
| `DefaultTemperature` | `null` | Default temperature |
| `DefaultMaxTokens` | `null` | Default max tokens |

## Exceptions

| Exception | Description |
|-----------|-------------|
| `AinosException` | Base exception for all SDK errors |
| `AinosConnectionException` | Connection cannot be established or maintained |
| `AinosAuthException` | Authentication with the daemon fails |
| `AinosRateLimitException` | Rate limit exceeded (HTTP 429) |

## Protocol Details

The SDK uses the same NDJSON protocol as the Rust `ai-daemon` IPC server:

- **TCP transport** on port 9500
- **JSON-line messages**: each message is a single JSON object followed by `\n`
- **Type-tagged**: messages have a `"type"` field for discrimination
- **Compact encoding**: `JsonSerializerOptions` with `PropertyNamingPolicy = CamelCase`

### Request types

| Type | Description |
|------|-------------|
| `Auth` | Authentication with bearer token |
| `Inference` | Synchronous inference |
| `InferenceStream` | Streaming inference |
| `ModelLoad` | Load a model from disk |
| `ModelUnload` | Unload a model from memory |
| `ModelList` | List all registered models |
| `ContextStore` | Store a key-value pair |
| `ContextRetrieve` | Retrieve a value by key |
| `Status` | Query daemon status |
| `RateLimitStatus` | Query rate limit status |

### Response types

| Type | Description |
|------|-------------|
| `AuthResponse` | Authentication result |
| `InferenceResponse` | Inference result |
| `InferenceChunk` | Streaming inference chunk |
| `ModelLoadResponse` | Model load result |
| `ModelUnloadResponse` | Model unload result |
| `ModelListResponse` | Model list |
| `StatusResponse` | Daemon status |
| `RateLimitStatusResponse` | Rate limit info |
| `Error` | Error response with code and message |

## Thread Safety

All public methods on `AinosClient` are thread-safe. The underlying transport uses a semaphore to serialize access to the TCP socket. For high-concurrency scenarios, use the connection pool (`UseConnectionPool = true`) with `BatchInferAsync`.

## Logging

The SDK uses `Microsoft.Extensions.Logging.Abstractions`. Provide an `ILogger<AinosClient>` or `ILoggerFactory` to enable logging:

```csharp
using Microsoft.Extensions.Logging;

var loggerFactory = LoggerFactory.Create(builder =>
{
    builder.AddConsole().SetMinimumLevel(LogLevel.Debug);
});

var client = new AinosClient(options, loggerFactory.CreateLogger<AinosClient>());
```

## Building

```bash
# Build the SDK
cd D:/Ainos/bindings/csharp
dotnet build

# Run tests
dotnet test

# Build in release
dotnet build -c Release
```

## Project Structure

```
bindings/csharp/
├── AinosSdk.sln
├── README.md
├── AinosSdk/
│   ├── AinosSdk.csproj
│   ├── AinosClient.cs              # Main client class
│   ├── Models/
│   │   ├── InferenceRequest.cs      # Request with builder
│   │   ├── InferenceResponse.cs
│   │   ├── InferenceChunk.cs
│   │   ├── ModelInfo.cs
│   │   ├── SystemStatus.cs
│   │   ├── HealthStatus.cs
│   │   ├── RateLimitStatus.cs
│   │   ├── ModelLoadOptions.cs
│   │   ├── AinosException.cs
│   │   ├── AinosConnectionException.cs
│   │   ├── AinosAuthException.cs
│   │   └── AinosRateLimitException.cs
│   ├── Transport/
│   │   ├── TcpTransport.cs          # TCP NDJSON transport
│   │   ├── JsonCodec.cs             # JSON serialization
│   │   └── ConnectionPool.cs        # Connection pooling
│   ├── Streaming/
│   │   ├── InferenceStream.cs       # IAsyncEnumerable stream
│   │   └── StreamReader.cs          # NDJSON line reader
│   └── Configuration/
│       ├── AinosClientOptions.cs    # Configuration
│       └── AinosClientBuilder.cs    # Fluent builder
└── AinosSdk.Tests/
    ├── AinosSdk.Tests.csproj
    ├── AinosClientTests.cs
    ├── JsonCodecTests.cs
    └── StreamingTests.cs
```

## Requirements

- .NET 8.0 or later
- Dependencies: `System.Text.Json` 8.0+, `Microsoft.Extensions.Logging` 8.0+

## License

Copyright (c) Ainos Project. All rights reserved.