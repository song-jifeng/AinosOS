"""Data models for the Ainos AI Daemon IPC protocol.

All models are plain dataclasses compatible with the JSON-line protocol
used by the Rust ai-daemon.  No external dependencies required.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Wire-format helpers
# ---------------------------------------------------------------------------

def _from_dict(cls: type, data: dict[str, Any]) -> Any:
    """Deserialize *data* into *cls*, coercing snake_case keys."""
    field_map = {f.name: f for f in dataclasses.fields(cls)}
    kwargs: dict[str, Any] = {}
    for key, value in data.items():
        # serde uses camelCase in JSON; we use snake_case in Python
        py_key = key.replace("-", "_")
        # Handle type-tagged enums: skip the "type" key when it's not a field
        if py_key == "type":
            continue
        if py_key in field_map:
            kwargs[py_key] = value
    return cls(**kwargs)


def _to_dict(instance: Any) -> dict[str, Any]:
    """Serialize *instance* to a JSON-compatible dict."""
    result: dict[str, Any] = {}
    for f in dataclasses.fields(instance):
        value = getattr(instance, f.name)
        if value is not None or f.default is not dataclasses.MISSING:
            result[f.name] = value
    return result


# ---------------------------------------------------------------------------
# Public data models
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class InferenceResponse:
    """Response from an LLM inference request.

    Attributes:
        output: Generated text.
        tokens_generated: Number of tokens produced.
        inference_ms: Wall-clock inference time in milliseconds.
        source: Either ``"local"`` or ``"cloud"``.
    """
    output: str
    tokens_generated: int = 0
    inference_ms: int = 0
    source: str = "local"


@dataclasses.dataclass
class ModelInfo:
    """Metadata describing a single registered model.

    Attributes:
        id: Unique model identifier (e.g. ``"phi_3_mini_4k_instruct_q4_gguf"``).
        name: Human-readable file name.
        path: Absolute file path on disk.
        size_mb: Model file size in megabytes.
        loaded: Whether the model is currently loaded in memory.
        architecture: Model architecture string (e.g. ``"auto"``, ``"phi3"``).
    """
    id: str
    name: str
    path: str
    size_mb: int = 0
    loaded: bool = False
    architecture: str = "auto"


@dataclasses.dataclass
class SystemStatus:
    """Daemon health and statistics.

    Attributes:
        uptime: Seconds since the daemon started.
        models_loaded: Number of models currently loaded in memory.
        total_requests: Total inference requests handled.
        network_available: Whether the internet is reachable.
    """
    uptime: int = 0
    models_loaded: int = 0
    total_requests: int = 0
    network_available: bool = False


@dataclasses.dataclass
class ContextEntry:
    """A single key-value entry in the daemon's context store.

    Attributes:
        key: The lookup key.
        value: The stored value.
        session_id: Session identifier (default ``"default"``).
    """
    key: str
    value: str
    session_id: str = "default"


# ---------------------------------------------------------------------------
# Internal IPC message builders / parsers
# ---------------------------------------------------------------------------

def _build_request(msg_type: str, **kwargs: Any) -> str:
    """Build a JSON-line request string for the daemon."""
    payload: dict[str, Any] = {"type": msg_type}
    payload.update(kwargs)
    return json.dumps(payload, separators=(",", ":"))


def _parse_response(line: str) -> dict[str, Any]:
    """Parse a single JSON-line response from the daemon."""
    return json.loads(line)


def _parse_inference_response(data: dict[str, Any]) -> InferenceResponse:
    return InferenceResponse(
        output=data.get("output", ""),
        tokens_generated=data.get("tokens_generated", 0),
        inference_ms=data.get("inference_ms", 0),
        source=data.get("source", "local"),
    )


def _parse_model_list_response(data: dict[str, Any]) -> list[ModelInfo]:
    models_raw = data.get("models", [])
    return [
        ModelInfo(
            id=m.get("id", ""),
            name=m.get("name", ""),
            path=m.get("path", ""),
            size_mb=m.get("size_mb", 0),
            loaded=m.get("loaded", False),
            architecture=m.get("architecture", "auto"),
        )
        for m in models_raw
    ]


def _parse_status_response(data: dict[str, Any]) -> SystemStatus:
    return SystemStatus(
        uptime=data.get("uptime", 0),
        models_loaded=data.get("models_loaded", 0),
        total_requests=data.get("total_requests", 0),
        network_available=data.get("network_available", False),
    )