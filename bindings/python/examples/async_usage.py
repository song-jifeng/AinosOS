"""
Ainos SDK - Async Usage Example
================================

Demonstrates advanced async usage patterns with the Ainos SDK:
- Running multiple concurrent inference requests
- Using asyncio.gather for parallel execution
- Combining streaming with concurrent tasks
- Connection pooling in action
- Graceful shutdown with signal handling

Prerequisites:
    - The Ainos daemon must be running on localhost:9500
    - At least one model must be loaded

Usage:
    python examples/async_usage.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ainos import AinosClient, StreamAccumulator, setup_logging
from ainos.errors import AinosError
from ainos.types import InferenceChunk, InferenceResponse, ModelInfo

# Flag to signal graceful shutdown
_shutdown_requested: bool = False


def handle_signal(sig: int, frame: object) -> None:
    """Handle shutdown signals gracefully."""
    global _shutdown_requested
    _shutdown_requested = True
    print(f"\n    Received signal {sig}, shutting down gracefully...")


async def single_inference(
    client: AinosClient,
    model: str,
    prompt: str,
    index: int,
) -> dict[str, Any]:
    """Run a single non-streaming inference and return results.

    Args:
        client: The AinosClient instance.
        model: The model identifier.
        prompt: The input prompt.
        index: A sequential index for logging.

    Returns:
        A dictionary with inference results.
    """
    start: float = time.monotonic()
    try:
        response: InferenceResponse = await client.infer(
            model=model,
            prompt=prompt,
            max_tokens=30,
            temperature=0.7,
        )
        elapsed: float = time.monotonic() - start
        return {
            "index": index,
            "success": True,
            "text": response.text,
            "elapsed": elapsed,
            "tokens": response.usage.total_tokens if response.usage else 0,
        }
    except AinosError as exc:
        elapsed = time.monotonic() - start
        return {
            "index": index,
            "success": False,
            "error": str(exc),
            "elapsed": elapsed,
        }


async def concurrent_inference_example(
    client: AinosClient,
    model: str,
) -> None:
    """Demonstrate running multiple inferences concurrently.

    Args:
        client: The AinosClient instance.
        model: The model identifier.
    """
    print("\n--- Concurrent Inference ---")
    print("Sending 5 concurrent inference requests...\n")

    prompts: list[str] = [
        "What is the capital of France?",
        "What is the capital of Japan?",
        "What is the capital of Brazil?",
        "What is the capital of Australia?",
        "What is the capital of Egypt?",
    ]

    # Create tasks for all prompts
    tasks: list[asyncio.Task[dict[str, Any]]] = [
        asyncio.create_task(
            single_inference(client, model, prompt, i)
        )
        for i, prompt in enumerate(prompts)
    ]

    # Run all tasks concurrently and wait for all to complete
    results: list[dict[str, Any]] = await asyncio.gather(*tasks)

    # Process results
    success_count: int = sum(1 for r in results if r["success"])
    total_time: float = max(r["elapsed"] for r in results)

    for r in results:
        if r["success"]:
            print(f"  [{r['index']}] ({r['elapsed']:.2f}s) {r['text'][:80]}...")
        else:
            print(f"  [{r['index']}] FAILED: {r['error']}")

    print(f"\n  Completed: {success_count}/{len(results)} in {total_time:.2f}s")
    print(f"  (With pool_size=4, requests are multiplexed across connections)")


async def streaming_with_concurrent_tasks(
    client: AinosClient,
    model: str,
) -> None:
    """Demonstrate streaming with concurrent processing.

    Args:
        client: The AinosClient instance.
        model: The model identifier.
    """
    print("\n--- Streaming with Concurrent Processing ---")
    print("Streaming a response while doing other work...\n")

    # Start a streaming inference
    stream = client.infer_stream(
        model=model,
        prompt="Write a list of 5 best practices for Python async programming.",
        max_tokens=200,
        temperature=0.7,
    )

    accumulator: StreamAccumulator = StreamAccumulator()
    chunk_count: int = 0

    # Process tokens as they arrive
    async for chunk in stream:
        accumulator.add(chunk)
        chunk_count += 1
        # Print the token
        print(chunk.token, end="", flush=True)

        # Every 10 tokens, do some other work (simulated)
        if chunk_count % 10 == 0:
            # In a real application, you might update a UI, log progress, etc.
            pass

    print(f"\n\n  Stream complete: {accumulator.token_count} tokens, "
          f"{accumulator.finish_reason}")


async def producer_consumer_example(
    client: AinosClient,
    model: str,
) -> None:
    """Demonstrate a producer/consumer pattern with streaming.

    One task produces streaming results, another consumes them
    for processing.

    Args:
        client: The AinosClient instance.
        model: The model identifier.
    """
    print("\n--- Producer/Consumer Pattern ---")

    # Queue for passing chunks between tasks
    queue: asyncio.Queue[InferenceChunk] = asyncio.Queue()
    done_event: asyncio.Event = asyncio.Event()

    async def producer() -> None:
        """Produce tokens by streaming inference."""
        try:
            async for chunk in client.infer_stream(
                model=model,
                prompt="Explain the concept of an async event loop in 3 sentences.",
                max_tokens=100,
            ):
                await queue.put(chunk)
            done_event.set()
        except Exception as exc:
            print(f"    Producer error: {exc}")
            done_event.set()

    async def consumer() -> None:
        """Consume tokens and process them."""
        word_count: int = 0
        char_count: int = 0

        while True:
            try:
                # Wait for a chunk with a timeout
                chunk: InferenceChunk = await asyncio.wait_for(
                    queue.get(),
                    timeout=1.0,
                )
                if chunk.token:
                    char_count += len(chunk.token)
                    word_count += len(chunk.token.split())

                if chunk.final:
                    break
            except asyncio.TimeoutError:
                if done_event.is_set():
                    break
                continue

        print(f"    Consumer processed: {word_count} words, {char_count} chars")

    # Run producer and consumer concurrently
    await asyncio.gather(producer(), consumer())


async def timeout_handling_example(
    client: AinosClient,
    model: str,
) -> None:
    """Demonstrate timeout handling for inference requests.

    Args:
        client: The AinosClient instance.
        model: The model identifier.
    """
    print("\n--- Timeout Handling ---")

    # Request with a very short timeout (will likely time out)
    try:
        response = await asyncio.wait_for(
            client.infer(
                model=model,
                prompt="Write a very long essay about AI.",
                max_tokens=10000,
                timeout=0.1,  # Very short timeout
            ),
            timeout=0.5,
        )
        print(f"    Response: {response.text[:50]}...")
    except (asyncio.TimeoutError, AinosError) as exc:
        print(f"    Timeout handled gracefully: {type(exc).__name__}: {exc}")

    # Request with adequate timeout
    try:
        response = await client.infer(
            model=model,
            prompt="What is 2 + 2?",
            max_tokens=10,
            timeout=10.0,
        )
        print(f"    Successful response: {response.text.strip()}")
    except AinosError as exc:
        print(f"    Error: {exc}")


async def main() -> None:
    """Run the async usage example."""
    setup_logging(level=logging.WARNING)

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    auth_token: str | None = os.environ.get("AINOS_AUTH_TOKEN")

    print("=" * 60)
    print("Ainos SDK - Async Usage Example")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Connect
    # ------------------------------------------------------------------
    print("\n[1] Connecting to daemon...")

    client: AinosClient = AinosClient(
        host="127.0.0.1",
        port=9500,
        auth_token=auth_token,
        pool_size=4,  # Use 4 connections for concurrent requests
    )
    await client.connect()

    # Find a loaded model
    models: list[ModelInfo] = await client.model_list()
    loaded: list[ModelInfo] = [m for m in models if m.status == "loaded"]

    if not loaded:
        print("    No loaded models found. Load one first.")
        await client.disconnect()
        return

    model_name: str = loaded[0].id
    print(f"    Connected. Using model: {model_name}")
    print(f"    Connection pool size: {client.config.pool_size}")

    # ------------------------------------------------------------------
    # 2. Run concurrent inference
    # ------------------------------------------------------------------
    await concurrent_inference_example(client, model_name)

    if _shutdown_requested:
        await client.disconnect()
        return

    # ------------------------------------------------------------------
    # 3. Streaming with concurrent tasks
    # ------------------------------------------------------------------
    await streaming_with_concurrent_tasks(client, model_name)

    if _shutdown_requested:
        await client.disconnect()
        return

    # ------------------------------------------------------------------
    # 4. Producer/consumer pattern
    # ------------------------------------------------------------------
    await producer_consumer_example(client, model_name)

    if _shutdown_requested:
        await client.disconnect()
        return

    # ------------------------------------------------------------------
    # 5. Timeout handling
    # ------------------------------------------------------------------
    await timeout_handling_example(client, model_name)

    # ------------------------------------------------------------------
    # 6. Clean up
    # ------------------------------------------------------------------
    print("\n[6] Disconnecting...")
    await client.disconnect()
    print("    Done.")

    print("\n" + "=" * 60)
    print("Async usage example completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())