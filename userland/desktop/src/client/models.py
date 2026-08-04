#!/usr/bin/env python3
"""Ainos Desktop - Data Models.

This module provides data models and serialization for all entities
exchanged with the Ainos backend service.
"""

import uuid
import json
import time
from enum import Enum, auto
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any


class ModelStatus(Enum):
    """Status of a model on the backend."""

    UNLOADED = "unloaded"
    LOADING = "loading"
    LOADED = "loaded"
    UNLOADING = "unloading"
    ERROR = "error"
    NOT_FOUND = "not_found"
    QUEUED = "queued"

    @classmethod
    def from_string(cls, status: str) -> "ModelStatus":
        """Create ModelStatus from a string value.

        Args:
            status: String representation of the status.

        Returns:
            Corresponding ModelStatus enum value.
        """
        status_map = {
            "unloaded": cls.UNLOADED,
            "loading": cls.LOADING,
            "loaded": cls.LOADED,
            "unloading": cls.UNLOADING,
            "error": cls.ERROR,
            "not_found": cls.NOT_FOUND,
            "queued": cls.QUEUED,
        }
        return status_map.get(status.lower(), cls.UNKNOWN if hasattr(cls, "UNKNOWN") else cls.UNLOADED)


class InferenceTaskStatus(Enum):
    """Status of an inference task."""

    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()
    STREAMING = auto()


@dataclass
class ModelInfo:
    """Information about an AI model available on the backend."""

    id: str = ""
    name: str = ""
    version: str = ""
    model_type: str = "llm"
    description: str = ""
    status: ModelStatus = ModelStatus.UNLOADED
    path: str = ""
    size_bytes: int = 0
    parameter_count: int = 0
    quantization: str = ""
    context_length: int = 4096
    gpu_memory_required: int = 0
    supported_features: list[str] = field(default_factory=list)
    loaded_at: str = ""
    error_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = asdict(self)
        result["status"] = self.status.value
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelInfo":
        """Create ModelInfo from a dictionary.

        Args:
            data: Dictionary representation.

        Returns:
            A ModelInfo instance.
        """
        data = data.copy()
        if "status" in data and isinstance(data["status"], str):
            data["status"] = ModelStatus.from_string(data["status"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def formatted_size(self) -> str:
        """Get human-readable model size.

        Returns:
            Formatted size string (e.g., "7.2 GB").
        """
        if self.size_bytes <= 0:
            return "Unknown"
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if self.size_bytes < 1024.0:
                return f"{self.size_bytes:.1f} {unit}"
            self.size_bytes /= 1024.0
        return f"{self.size_bytes:.1f} PB"

    def formatted_parameters(self) -> str:
        """Get human-readable parameter count.

        Returns:
            Formatted parameter count (e.g., "7B").
        """
        if self.parameter_count <= 0:
            return "Unknown"
        if self.parameter_count >= 1_000_000_000:
            return f"{self.parameter_count / 1_000_000_000:.0f}B"
        if self.parameter_count >= 1_000_000:
            return f"{self.parameter_count / 1_000_000:.0f}M"
        return str(self.parameter_count)


@dataclass
class GenerationConfig:
    """Configuration for text generation/inference."""

    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 40
    max_tokens: int = 2048
    stop_sequences: list[str] = field(default_factory=list)
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    repetition_penalty: float = 1.0
    seed: int | None = None
    stream: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API calls."""
        result = asdict(self)
        # Remove None values
        return {k: v for k, v in result.items() if v is not None}


@dataclass
class InferenceRequest:
    """A request for model inference."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    model_id: str = ""
    prompt: str = ""
    system_prompt: str = ""
    context_id: str = ""
    config: GenerationConfig = field(default_factory=GenerationConfig)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API calls."""
        result = {
            "id": self.id,
            "model_id": self.model_id,
            "prompt": self.prompt,
            "system_prompt": self.system_prompt,
            "context_id": self.context_id,
            "config": self.config.to_dict(),
            "created_at": self.created_at,
        }
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InferenceRequest":
        """Create InferenceRequest from a dictionary.

        Args:
            data: Dictionary representation.

        Returns:
            An InferenceRequest instance.
        """
        data = data.copy()
        if "config" in data and isinstance(data["config"], dict):
            data["config"] = GenerationConfig(**data["config"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class TokenUsage:
    """Token usage statistics for an inference request."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_tokens_per_second: float = 0.0
    completion_tokens_per_second: float = 0.0
    total_duration_ms: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TokenUsage":
        """Create TokenUsage from a dictionary.

        Args:
            data: Dictionary representation.

        Returns:
            A TokenUsage instance.
        """
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class InferenceResponse:
    """Response from a model inference request."""

    id: str = ""
    request_id: str = ""
    model_id: str = ""
    text: str = ""
    is_partial: bool = False
    is_final: bool = False
    is_error: bool = False
    error_message: str = ""
    token_usage: TokenUsage | None = None
    finish_reason: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = asdict(self)
        if self.token_usage:
            result["token_usage"] = asdict(self.token_usage)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InferenceResponse":
        """Create InferenceResponse from a dictionary.

        Args:
            data: Dictionary representation.

        Returns:
            An InferenceResponse instance.
        """
        data = data.copy()
        if "token_usage" in data and isinstance(data["token_usage"], dict):
            data["token_usage"] = TokenUsage.from_dict(data["token_usage"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ContextEntry:
    """A single entry in the inference context/history."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    context_id: str = ""
    role: str = "user"  # user, assistant, system
    content: str = ""
    model_id: str = ""
    token_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContextEntry":
        """Create ContextEntry from a dictionary.

        Args:
            data: Dictionary representation.

        Returns:
            A ContextEntry instance.
        """
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class SystemMetrics:
    """System performance metrics from the backend."""

    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_used_gb: float = 0.0
    memory_total_gb: float = 0.0
    gpu_percent: float = 0.0
    gpu_memory_percent: float = 0.0
    gpu_memory_used_gb: float = 0.0
    gpu_memory_total_gb: float = 0.0
    gpu_temperature: float = 0.0
    cpu_temperature: float = 0.0
    disk_percent: float = 0.0
    network_bytes_sent: int = 0
    network_bytes_received: int = 0
    process_count: int = 0
    uptime_seconds: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SystemMetrics":
        """Create SystemMetrics from a dictionary.

        Args:
            data: Dictionary representation.

        Returns:
            A SystemMetrics instance.
        """
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ConnectionConfig:
    """Configuration for connecting to the Ainos backend."""

    host: str = "127.0.0.1"
    port: int = 8765
    use_ssl: bool = False
    api_key: str = ""
    timeout_ms: int = 30000
    reconnect_interval_ms: int = 5000
    max_reconnect_attempts: int = 10
    heartbeat_interval_ms: int = 15000

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = asdict(self)
        # Mask API key for display
        if result["api_key"]:
            result["api_key_masked"] = self.masked_api_key()
        return result

    def masked_api_key(self) -> str:
        """Get a masked version of the API key for display.

        Returns:
            Masked API key string.
        """
        if not self.api_key:
            return ""
        if len(self.api_key) <= 8:
            return "*" * len(self.api_key)
        return self.api_key[:4] + "*" * (len(self.api_key) - 8) + self.api_key[-4:]

    @property
    def url(self) -> str:
        """Get the full connection URL.

        Returns:
            Connection URL string.
        """
        protocol = "wss" if self.use_ssl else "ws"
        return f"{protocol}://{self.host}:{self.port}"


@dataclass
class BackendInfo:
    """Information about the Ainos backend service."""

    version: str = ""
    name: str = "Ainos Backend"
    uptime_seconds: float = 0.0
    active_models: int = 0
    total_models: int = 0
    active_connections: int = 0
    total_inferences: int = 0
    status: str = "unknown"
    gpu_available: bool = False
    gpu_count: int = 0
    gpu_names: list[str] = field(default_factory=list)
    cuda_version: str = ""
    python_version: str = ""
    os_info: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BackendInfo":
        """Create BackendInfo from a dictionary.

        Args:
            data: Dictionary representation.

        Returns:
            A BackendInfo instance.
        """
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})