"""
Ainos SDK - Streaming Inference Example
========================================

Demonstrates streaming inference with the Ainos daemon, including:
- Basic streaming with async for loop
- Collecting all tokens into a string
- Using StreamAccumulator for progress tracking
- Handling stream cancellation
- Measuring streaming performance

Prerequisites:
    - The Ainos daemon must be running on localhost:9500
    - At least one model must be loaded

Usage:
    python examples/streaming.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ainos import AinosClient, StreamAccumulator, setup_logging
from ainos.errors import AinosError
from ainos.types import InferenceChunk, ModelInfo


async def main() -> None:
    """Run the streaming example."""
    setup_logging(level=logging.WARNING)

    auth_token: str | None = os.environ.get("AINOS_AUTH_TOKEN")

    print("=" * 60)
    print("Ainos SDK - Streaming Inference Example")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Connect and find a model
    # ------------------------------------------------------------------
    print("\n[1] Connecting to daemon and finding a loaded model...")

    client: AinosClient = AinosClient(
        host="127.0.0.1",
        port=9500,
        auth_token=auth_token,
    )
    await client.connect()

    models: list[ModelInfo] = await client.model_list()
    loaded: list[ModelInfo] = [m for m in models if m.status == "loaded"]

    if not loaded:
        print("    No loaded models found. Please load a model first.")
        print("    Example: python examples/model_management.py")
        await client.disconnect()
        return

    model_name: str = loaded[0].id
    print(f"    Using model: {model_name}")

    # ------------------------------------------------------------------
    # 2. Basic streaming (async for loop)
    # ------------------------------------------------------------------
    print("\n[2] Basic streaming inference...")
    print("    Generating text, streaming token by token:\n")

    prompt: str = "Write a short paragraph about the future of artificial intelligence."

    stream = client.infer_stream(
        model=model_name,
        prompt=prompt,
        max_tokens=200,
        temperature=0.7,
    )

    start_time: float = time.monotonic()
    token_count: int = 0
    full_text: str = ""

    async for chunk in stream:
        print(chunk.token, end="", flush=True)
        full_text += chunk.token
        token_count += 1

        if chunk.final:
            print()
            print(f"\n    [Stream finished: {chunk.finish_reason}]")

    elapsed: float = time.monotonic() - start_time
    print(f"\n    Tokens: {token_count} in {elapsed:.2f}s "
          f"({token_count / elapsed:.1f} tokens/s)")

    # ------------------------------------------------------------------
    # 3. Using StreamAccumulator
    # ------------------------------------------------------------------
    print("\n[3] Streaming with StreamAccumulator (collect + stats)...")

    accumulator: StreamAccumulator = StreamAccumulator()

    async for chunk in client.infer_stream(
        model=model_name,
        prompt="List 3 interesting facts about the Python programming language.",
        max_tokens=150,
        temperature=0.8,
    ):
        accumulator.add(chunk)
        # Still print tokens as they arrive
        print(chunk.token, end="", flush=True)

    print("\n")
    print(f"    Accumulated text length: {len(accumulator.text)} chars")
    print(f"    Token count: {accumulator.token_count}")
    print(f"    Finish reason: {accumulator.finish_reason}")
    print(f"    Elapsed: {accumulator.elapsed:.2f}s")
    if accumulator.usage:
        print(f"    Usage: {accumulator.usage.total_tokens} total tokens")

    # ------------------------------------------------------------------
    # 4. Streaming with different parameters
    # ------------------------------------------------------------------
    print("\n[4] Streaming with different parameters (higher temperature)...")

    prompt = "Write a creative tagline for a robot barista."

    async for chunk in client.infer_stream(
        model=model_name,
        prompt=prompt,
        max_tokens=30,
        temperature=1.5,  # More creative / random
        top_p=0.9,
    ):
        print(chunk.token, end="", flush=True)

    print("\n")

    # ------------------------------------------------------------------
    # 5. Collect all tokens at once
    # ------------------------------------------------------------------
    print("\n[5] Collecting all tokens with collect()...")

    stream = client.infer_stream(
        model=model_name,
        prompt="What is 2 + 2? Answer briefly.",
        max_tokens=20,
    )
    collected: str = await stream.collect()
    print(f"    Collected text: {collected.strip()}")

    # ------------------------------------------------------------------
    # 6. Streaming with stop sequences
    # ------------------------------------------------------------------
    print("\n[6] Streaming with stop sequences...")

    async for chunk in client.infer_stream(
        model=model_name,
        prompt="Count from 1 to 5:",
        max_tokens=50,
        stop=["3"],  # Will stop at "3"
    ):
        print(chunk.token, end="", flush=True)

    print("\n    (Stopped at '3' due to stop sequence)")

    # ------------------------------------------------------------------
    # 7. Clean up
    # ------------------------------------------------------------------
    print("\n[7] Disconnecting...")
    await client.disconnect()
    print("    Done.")

    print("\n" + "=" * 60)
    print("Streaming example completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())