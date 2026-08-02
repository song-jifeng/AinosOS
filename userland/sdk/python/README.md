# Ainos AI Daemon — Python SDK

A lightweight, zero-dependency Python SDK for communicating with the Ainos AI
Daemon over TCP.  Uses the same newline-delimited JSON (NDJSON) protocol as the
Rust `ai-daemon` IPC server.

## Features

- Simple synchronous TCP client with automatic reconnect
- Full daemon API coverage: inference, model management, context store, status
- Zero external dependencies (stdlib only: `socket`, `json`, `typing`)
- Python 3.9+ compatible
- Context manager support (`with AinosClient() as client:`)
- Custom exceptions for clear error handling

## Installation

```bash
# From the SDK directory
pip install .

# Or in editable mode for development
pip install -e .
```

## Quick Start

```python
from ainos import AinosClient

# The daemon listens on 127.0.0.1:9500 by default
with AinosClient() as client:
    # --- Inference ---
    resp = client.infer("What is Ainos OS?")
    print(f"AI: {resp.output}")
    print(f"Tokens: {resp.tokens_generated}, Time: {resp.inference_ms}ms")

    # --- System status ---
    status = client.status()
    print(f"Daemon uptime: {status.uptime}s")
    print(f"Models loaded: {status.models_loaded}")
    print(f"Total requests: {status.total_requests}")

    # --- List models ---
    models = client.model_list()
    for m in models:
        loaded = "loaded" if m.loaded else "unloaded"
        print(f"  [{loaded}] {m.name} ({m.size_mb} MB)")

    # --- Context store ---
    client.context_store("my_key", "my_value")
    val = client.context_retrieve("my_key")
    print(f"Stored value: {val}")
```

## API Reference

### AinosClient

```python
client = AinosClient(
    host="127.0.0.1",      # Daemon host
    port=9500,              # Daemon TCP port
    connect_timeout=5.0,    # Connection timeout (seconds)
    read_timeout=120.0,     # Read timeout (seconds)
    auto_reconnect=True,    # Attempt reconnect on connection loss
    reconnect_delay=1.0,    # Delay before reconnect attempt
)
```

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `connect()` | `None` | Open connection to the daemon |
| `disconnect()` | `None` | Close the connection |
| `infer(prompt, model, temperature, max_tokens, session_id)` | `InferenceResponse` | Send an inference request |
| `status()` | `SystemStatus` | Query daemon health and stats |
| `model_list()` | `list[ModelInfo]` | List all registered models |
| `model_load(path)` | `None` | Load a model by file path |
| `model_unload(model_id)` | `None` | Unload a model by ID |
| `context_store(key, value)` | `str` | Persist a key-value pair |
| `context_retrieve(key)` | `Optional[str]` | Retrieve a value by key |

### Data Models

- `InferenceResponse(output, tokens_generated, inference_ms, source)`
- `SystemStatus(uptime, models_loaded, total_requests, network_available)`
- `ModelInfo(id, name, path, size_mb, loaded, architecture)`
- `ContextEntry(key, value, session_id)`

### Exceptions

- `AinosError` — Base exception for all SDK errors
- `AinosConnectionError` — Connection failures
- `AinosInferenceError` — Inference request failures
- `AinosTimeoutError` — Operation timeout

## Requirements

- Python 3.9+
- No external dependencies

## License

Same as Ainos OS.