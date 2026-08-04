"""
Ainos Python SDK
================

A Python SDK for interacting with the Ainos daemon over the NDJSON TCP
protocol. Provides a fully typed, async API for inference, model management,
and system monitoring.

Typical usage::

    import asyncio
    from ainos import AinosClient

    async def main():
        async with AinosClient(
            host="127.0.0.1",
            port=9500,
            auth_token="my-token",
        ) as client:
            # Health check
            health = await client.health()
            print(f"Daemon healthy: {health.healthy}")

            # Streaming inference
            async for chunk in client.infer_stream(
                "my-model",
                "Hello, world!",
            ):
                print(chunk.token, end="", flush=True)

    asyncio.run(main())
"""

from __future__ import annotations

from ainos.client import AinosClient
from ainos.errors import (
    AinosError,
    AuthenticationError,
    ConfigurationError,
    ConnectionError,
    ConnectionTimeoutError,
    ContextLengthExceededError,
    InferenceError,
    InferenceTimeoutError,
    InvalidMessageError,
    InvalidPromptError,
    InvalidRequestError,
    MessageTooLargeError,
    ModelBusyError,
    ModelError,
    ModelLoadError,
    ModelNotFoundError,
    ModelNotLoadedError,
    ModelUnloadError,
    ProtocolError,
    ReconnectionFailedError,
    RequestCancelledError,
    RequestError,
    RequestTimeoutError,
    StreamError,
    StreamInterruptedError,
    StreamNotStartedError,
    TransportBufferFullError,
    TransportClosedError,
    TransportError,
    error_from_code,
)
from ainos.models import ModelManager, ModelRegistry, ModelStatus
from ainos.stream import StreamAccumulator, StreamIterator, StreamManager
from ainos.types import (
    ConnectionConfig,
    HealthStatus,
    InferenceChunk,
    InferenceRequest,
    InferenceResponse,
    ModelConfig,
    ModelInfo,
    SystemStatus,
    TokenUsage,
)
from ainos.utils import setup_logging

# ---------------------------------------------------------------------------
# Package metadata
# ---------------------------------------------------------------------------

__version__: str = "0.1.0"
__author__: str = "Ainos Team"
__all__: list[str] = [
    # Main client
    "AinosClient",
    # Data types
    "InferenceRequest",
    "InferenceResponse",
    "InferenceChunk",
    "TokenUsage",
    "ModelInfo",
    "ModelConfig",
    "SystemStatus",
    "HealthStatus",
    "ConnectionConfig",
    # Model management
    "ModelManager",
    "ModelRegistry",
    "ModelStatus",
    # Streaming
    "StreamIterator",
    "StreamManager",
    "StreamAccumulator",
    # Errors
    "AinosError",
    "ConnectionError",
    "ConnectionTimeoutError",
    "AuthenticationError",
    "ReconnectionFailedError",
    "ProtocolError",
    "InvalidMessageError",
    "MessageTooLargeError",
    "RequestError",
    "InvalidRequestError",
    "RequestTimeoutError",
    "RequestCancelledError",
    "InferenceError",
    "ModelNotLoadedError",
    "InvalidPromptError",
    "ContextLengthExceededError",
    "InferenceTimeoutError",
    "ModelError",
    "ModelNotFoundError",
    "ModelLoadError",
    "ModelUnloadError",
    "ModelBusyError",
    "StreamError",
    "StreamInterruptedError",
    "StreamNotStartedError",
    "ConfigurationError",
    "TransportError",
    "TransportClosedError",
    "TransportBufferFullError",
    "error_from_code",
    # Utilities
    "setup_logging",
    # Package metadata
    "__version__",
    "__author__",
]