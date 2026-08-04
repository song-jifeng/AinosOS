# Ainos Desktop - Client Package
"""Client module for communicating with the Ainos backend."""

from .ainos_client import AinosClient
from .transport import TCPTransport, TransportError, ConnectionError, TimeoutError
from .models import (
    ModelInfo,
    ModelStatus,
    InferenceRequest,
    InferenceResponse,
    ContextEntry,
    SystemMetrics,
    ConnectionConfig,
    BackendInfo,
    GenerationConfig,
    TokenUsage,
)

__all__ = [
    "AinosClient",
    "TCPTransport",
    "TransportError",
    "ConnectionError",
    "TimeoutError",
    "ModelInfo",
    "ModelStatus",
    "InferenceRequest",
    "InferenceResponse",
    "ContextEntry",
    "SystemMetrics",
    "ConnectionConfig",
    "BackendInfo",
    "GenerationConfig",
    "TokenUsage",
]