# Ainos Python SDK

A fully typed, async Python SDK for interacting with the **Ainos inference daemon** over the NDJSON TCP protocol.

## Features

- **Async API** — Built on `asyncio` for high-performance concurrent operations
- **Streaming inference** — Token-by-token streaming with async iterators
- **Model management** — Load, unload, and query models on the daemon
- **Connection pooling** — Multiplex requests across multiple TCP connections
- **Automatic reconnection** — Exponential backoff with configurable retry
- **Authentication** — Bearer token support with multiple token sources
- **Comprehensive error handling** — Typed exception hierarchy for every error case
- **Fully type-annotated** — Complete type hints for IDE support and static analysis
- **Zero external dependencies** — Uses only Python standard library
- **Thoroughly tested** — Complete test suite with mock daemon

## Installation

```bash
pip install ainos
```

Or install from source:

```bash
git clone https://github.com/ainos/ainos-python.git
cd ainos-python
pip install -e .
```

## Quick Start

```python
import asyncio
from ainos import AinosClient


async def main() -> None:
    # Create the client (auto-connects)
    async with AinosClient(
        host="127.0.0.1",
        port=9500,
        auth_token="your-auth-token",
    ) as client:
        # Check daemon health
        health = await client.health()
        print(f"Daemon healthy: {health.healthy}")

        # List available models
        models = await client.model_list()
        for m in models:
            print(f"  - {m.name} ({m.status})")

        # Non-streaming inference
        response = await client.infer(
            model="my-model",
            prompt="What is the capital of France?",
            max_tokens=100,
        )
        print(f"Response: {response.text}")

        # Streaming inference
        async for chunk in client.infer_stream(
            model="my-model",
            prompt="Write a short poem about AI.",
            max_tokens=200,
        ):
            print(chunk.token, end="", flush=True)


asyncio.run(main())
```

## Documentation

### Connection

The client connects to the Ainos daemon over TCP. By default it connects to
`127.0.0.1:9500`.

```python
# Explicit connection
client = AinosClient(host="127.0.0.1", port=9500, auth_token="...")
await client.connect()

# Context manager (auto-connect and auto-disconnect)
async with AinosClient(host="127.0.0.1", port=9500, auth_token="...") as client:
    ...
```

### Authentication

Tokens can be provided in several ways:

```python
# Direct token
client = AinosClient(auth_token="my-token")

# Token from file
client = AinosClient(auth_token_file="/path/to/token")

# Token from environment variable
client = AinosClient(auth_token_env_var="AINOS_AUTH_TOKEN")

# Auto-discover from AINOS_AUTH_TOKEN env var
client = AinosClient()
```

### Inference

#### Non-streaming

```python
response = await client.infer(
    model="llama-3-8b",
    prompt="Explain quantum computing in simple terms.",
    system_prompt="You are a helpful teacher.",
    temperature=0.7,
    max_tokens=500,
    stop=["\n\n", "###"],
)
print(response.text)
print(f"Tokens: {response.usage.total_tokens}")
```

#### Streaming

```python
accumulator = StreamAccumulator()
async for chunk in client.infer_stream(
    model="llama-3-8b",
    prompt="Write a story about a robot.",
    max_tokens=1000,
):
    print(chunk.token, end="", flush=True)
    accumulator.add(chunk)

print(f"\n\nTotal tokens: {accumulator.token_count}")
print(f"Finish reason: {accumulator.finish_reason}")
```

### Model Management

```python
# List models
models = await client.model_list()

# Load a model
info = await client.model_load(
    name="my-llama",
    path="/models/llama-3-8b.gguf",
    backend="llama.cpp",
    gpu_layers=32,
    context_length=8192,
)
print(f"Loaded: {info.id} on {info.device}")

# Check if a model is loaded
if await client.model_manager.is_loaded("my-llama"):
    print("Model is ready")

# Unload a model
await client.model_unload("my-llama")
```

### Context Store

```python
# Store a value
await client.context_store("my_key", {"nested": "data"}, ttl=3600)

# Retrieve a value
value = await client.context_retrieve("my_key")
print(value)  # {"nested": "data"}
```

### System Status

```python
# Health check
health = await client.health()
print(f"Healthy: {health.healthy}, version: {health.version}")

# Detailed status
status = await client.status()
print(f"Uptime: {status.uptime_seconds}s")
print(f"Memory: {status.memory_used_mb}MB / {status.memory_total_mb}MB")
print(f"Active models: {status.active_models}")
print(f"GPU usage: {status.gpu_usage_percent}%")
```

## Error Handling

All SDK errors inherit from `AinosError`. Catch specific errors for granular
control:

```python
from ainos.errors import (
    ConnectionError,
    ModelNotLoadedError,
    InferenceTimeoutError,
    AuthenticationError,
)

try:
    response = await client.infer("unknown-model", "Hello")
except ModelNotLoadedError:
    print("Model not loaded!")
except ConnectionError:
    print("Daemon is not running!")
except AuthenticationError:
    print("Invalid token!")
except InferenceTimeoutError:
    print("Inference timed out!")
```

## Configuration

Key configuration options:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `host` | `"127.0.0.1"` | Daemon hostname |
| `port` | `9500` | Daemon TCP port |
| `connect_timeout` | `10.0` | Connection timeout (seconds) |
| `request_timeout` | `60.0` | Request timeout (seconds) |
| `reconnect_attempts` | `3` | Max reconnection attempts |
| `pool_size` | `4` | Connection pool size |
| `max_message_size` | `16 MiB` | Maximum message size |
| `ssl` | `False` | Enable SSL/TLS |

## Development

### Setup

```bash
# Clone the repository
git clone https://github.com/ainos/ainos-python.git
cd ainos-python

# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=ainos

# Type checking
mypy ainos

# Linting
ruff check ainos
```

### Project Structure

```
ainos/
├── __init__.py       # Package entry point
├── client.py         # AinosClient main class
├── types.py          # Data classes (InferenceRequest, ModelInfo, etc.)
├── transport.py      # TCP transport layer + connection pool
├── auth.py           # Token authentication
├── stream.py         # Streaming inference iterator
├── errors.py         # Exception hierarchy
├── utils.py          # Utility functions
└── models.py         # Model management
examples/
├── basic_usage.py
├── streaming.py
├── model_management.py
└── async_usage.py
tests/
├── conftest.py
├── test_client.py
├── test_transport.py
└── test_stream.py
```

## License

MIT License. See [LICENSE](LICENSE) for details.