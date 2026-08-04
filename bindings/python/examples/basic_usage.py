"""
Ainos SDK - Basic Usage Example
================================

Demonstrates the core functionality of the Ainos SDK:
- Creating a client
- Checking daemon health
- Running non-streaming inference
- Listing models
- Using the context store
- Error handling

Prerequisites:
    - The Ainos daemon must be running on localhost:9500
    - An auth token may be required (set AINOS_AUTH_TOKEN env var)

Usage:
    python examples/basic_usage.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

# Add the parent directory to the path so we can import ainos
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ainos import AinosClient, setup_logging
from ainos.errors import (
    AinosError,
    ConnectionError,
    ModelNotLoadedError,
)
from ainos.types import (
    HealthStatus,
    InferenceResponse,
    ModelInfo,
    SystemStatus,
)


async def main() -> None:
    """Run the basic usage example."""
    # Set up logging so we can see what's happening
    setup_logging(level=logging.INFO)

    # Get auth token from environment (or use a default for local dev)
    auth_token: str | None = os.environ.get("AINOS_AUTH_TOKEN")

    print("=" * 60)
    print("Ainos SDK - Basic Usage Example")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Create and connect the client
    # ------------------------------------------------------------------
    print("\n[1] Connecting to Ainos daemon...")

    try:
        client: AinosClient = AinosClient(
            host="127.0.0.1",
            port=9500,
            auth_token=auth_token,
            connect_timeout=5.0,
            request_timeout=30.0,
        )
        await client.connect()
        print(f"    Connected: {client.connected}")
    except ConnectionError as exc:
        print(f"    FAILED: {exc}")
        print("    Is the Ainos daemon running on localhost:9500?")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 2. Health check
    # ------------------------------------------------------------------
    print("\n[2] Checking daemon health...")

    health: HealthStatus = await client.health()
    print(f"    Healthy: {health.healthy}")
    print(f"    Version: {health.version or 'unknown'}")
    print(f"    Status:  {health.status}")
    print(f"    Uptime:  {health.uptime_seconds:.1f}s")
    print(f"    Active models: {health.active_models}")

    # ------------------------------------------------------------------
    # 3. System status
    # ------------------------------------------------------------------
    print("\n[3] Fetching system status...")

    try:
        status: SystemStatus = await client.status()
        print(f"    Daemon version: {status.version}")
        print(f"    Uptime: {status.uptime_seconds:.1f}s")
        print(f"    Memory: {status.memory_used_mb:.0f}MB / {status.memory_total_mb:.0f}MB")
        print(f"    CPU: {status.cpu_usage_percent:.1f}%")
        if status.gpu_usage_percent is not None:
            print(f"    GPU: {status.gpu_usage_percent:.1f}%")
        print(f"    Active requests: {status.active_requests}")
        print(f"    Queued requests: {status.queued_requests}")
        if status.errors:
            print(f"    Errors: {status.errors}")
    except Exception as exc:
        print(f"    Failed to fetch status: {exc}")

    # ------------------------------------------------------------------
    # 4. List models
    # ------------------------------------------------------------------
    print("\n[4] Listing models...")

    try:
        models: list[ModelInfo] = await client.model_list()
        if models:
            print(f"    Found {len(models)} model(s):")
            for i, model in enumerate(models):
                print(f"      [{i + 1}] {model.name} (id={model.id})")
                print(f"           Status: {model.status}")
                print(f"           Backend: {model.backend}")
                print(f"           Device: {model.device}")
                print(f"           Context: {model.context_length} tokens")
        else:
            print("    No models found. Load one with model_load().")
    except Exception as exc:
        print(f"    Failed to list models: {exc}")

    # ------------------------------------------------------------------
    # 5. Non-streaming inference
    # ------------------------------------------------------------------
    print("\n[5] Running non-streaming inference...")

    # Find the first loaded model
    loaded_models: list[ModelInfo] = [m for m in models if m.status == "loaded"] if models else []

    if loaded_models:
        model_name: str = loaded_models[0].id
        print(f"    Using model: {model_name}")

        try:
            response: InferenceResponse = await client.infer(
                model=model_name,
                prompt="What is the meaning of life? Answer in one sentence.",
                max_tokens=50,
                temperature=0.8,
            )
            print(f"    Response: {response.text}")
            print(f"    Finish reason: {response.finish_reason}")
            if response.usage:
                print(f"    Tokens: {response.usage.prompt_tokens} prompt + "
                      f"{response.usage.completion_tokens} completion = "
                      f"{response.usage.total_tokens} total")
        except ModelNotLoadedError as exc:
            print(f"    Model not loaded: {exc}")
        except AinosError as exc:
            print(f"    Inference failed: {exc}")
    else:
        print("    No loaded models available for inference.")
        print("    Use model_management.py example to load a model first.")

    # ------------------------------------------------------------------
    # 6. Context store
    # ------------------------------------------------------------------
    print("\n[6] Using the context store...")

    try:
        # Store a value
        stored: bool = await client.context_store("example_key", {"hello": "world"}, ttl=60)
        print(f"    Stored value: {stored}")

        # Retrieve the value
        value: Any = await client.context_retrieve("example_key")
        print(f"    Retrieved value: {value}")

        # Retrieve a non-existent key
        missing: Any = await client.context_retrieve("non_existent_key")
        print(f"    Non-existent key: {missing}")
    except Exception as exc:
        print(f"    Context store operation failed: {exc}")

    # ------------------------------------------------------------------
    # 7. Disconnect
    # ------------------------------------------------------------------
    print("\n[7] Disconnecting...")

    await client.disconnect()
    print(f"    Connected: {client.connected}")
    print()

    print("=" * 60)
    print("Example completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())