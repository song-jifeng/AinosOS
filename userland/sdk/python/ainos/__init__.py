"""Ainos AI Daemon — Python SDK.

A lightweight, zero-dependency SDK for communicating with the Ainos AI
Daemon over TCP using the newline-delimited JSON (NDJSON) protocol.

Usage::

    from ainos import AinosClient

    with AinosClient() as client:
        resp = client.infer("Hello, Ainos!")
        print(resp.output)

        status = client.status()
        print(f"Uptime: {status.uptime}s, Models loaded: {status.models_loaded}")
"""

from .client import (
    AinosClient,
    AinosConnectionError,
    AinosError,
    AinosInferenceError,
    AinosTimeoutError,
)
from .models import (
    ContextEntry,
    InferenceResponse,
    ModelInfo,
    SystemStatus,
)

__all__ = [
    "AinosClient",
    "AinosConnectionError",
    "AinosError",
    "AinosInferenceError",
    "AinosTimeoutError",
    "ContextEntry",
    "InferenceResponse",
    "ModelInfo",
    "SystemStatus",
]

__version__ = "0.1.0"