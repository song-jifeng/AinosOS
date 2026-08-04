"""
Ainos SDK - Data Types
======================

Defines the data classes and type aliases used throughout the Ainos SDK.
All data classes are fully typed with Python type annotations and support
JSON serialisation/deserialisation.

Classes:
    - InferenceRequest: Parameters for a model inference request.
    - InferenceResponse: The result of a non-streaming inference.
    - InferenceChunk: A single token chunk from a streaming inference.
    - ModelInfo: Metadata about a loaded or available model.
    - ModelConfig: Configuration for loading a model.
    - SystemStatus: Daemon health and resource usage.
    - HealthStatus: High-level health check result.
    - ConnectionConfig: Connection parameters for the transport layer.
    - RequestMessage: An NDJSON request message sent to the daemon.
    - ResponseMessage: An NDJSON response message received from the daemon.
    - StreamMessage: A streaming chunk from the daemon.
    - ErrorMessage: An error response from the daemon.
"""

from __future__ import annotations

import dataclasses
import typing as t
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

#: JSON-compatible value types.
JSONValue: t.TypeAlias = t.Union[
    str,
    int,
    float,
    bool,
    None,
    t.Dict[str, "JSONValue"],
    t.List["JSONValue"],
]

#: A JSON object (dictionary).
JSONObject: t.TypeAlias = t.Dict[str, JSONValue]

#: A unique identifier for a request, typically a UUID string.
RequestId: t.TypeAlias = str

#: Timestamp in seconds since epoch (float).
Timestamp: t.TypeAlias = float


# ---------------------------------------------------------------------------
# Inference types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InferenceRequest:
    """Parameters for a model inference request.

    This dataclass encapsulates all parameters that can be sent to the
    daemon's ``infer`` method. It is serialised to JSON before transmission.

    Attributes:
        model: The model identifier to use for inference.
        prompt: The input text prompt.
        system_prompt: Optional system prompt to guide model behaviour.
        temperature: Sampling temperature (0.0 to 2.0). Higher values produce
            more random outputs.
        top_p: Nucleus sampling threshold (0.0 to 1.0).
        top_k: Top-k sampling (number of highest probability tokens to
            consider).
        max_tokens: Maximum number of tokens to generate.
        stop: List of stop sequences that terminate generation.
        presence_penalty: Penalty for token presence (-2.0 to 2.0).
        frequency_penalty: Penalty for token frequency (-2.0 to 2.0).
        stream: Whether to use streaming response.
        extra_params: Additional model-specific parameters.
    """

    model: str
    prompt: str
    system_prompt: t.Optional[str] = None
    temperature: t.Optional[float] = None
    top_p: t.Optional[float] = None
    top_k: t.Optional[int] = None
    max_tokens: t.Optional[int] = None
    stop: t.Optional[t.List[str]] = None
    presence_penalty: t.Optional[float] = None
    frequency_penalty: t.Optional[float] = None
    stream: bool = False
    extra_params: t.Optional[t.Dict[str, JSONValue]] = None

    def to_dict(self) -> JSONObject:
        """Convert this request to a JSON-compatible dictionary.

        Returns:
            A dictionary with all non-None fields, with ``extra_params``
            merged at the top level.
        """
        base: JSONObject = {}
        for field_ in dataclasses.fields(self):
            key: str = field_.name
            value: t.Any = getattr(self, key)
            if value is not None:
                base[key] = value
        # Merge extra_params into the top-level dict
        extra: t.Optional[t.Dict[str, JSONValue]] = self.extra_params
        if extra:
            base.update(extra)
            base.pop("extra_params", None)
        return base

    @classmethod
    def from_dict(cls, data: JSONObject) -> "InferenceRequest":
        """Create an InferenceRequest from a JSON dictionary.

        Args:
            data: Dictionary of request parameters.

        Returns:
            A new InferenceRequest instance.
        """
        valid_keys: set[str] = {f.name for f in dataclasses.fields(cls)}
        kwargs: dict[str, t.Any] = {}
        extra: dict[str, JSONValue] = {}
        for key, value in data.items():
            if key in valid_keys:
                kwargs[key] = value
            else:
                extra[key] = value
        if extra:
            kwargs["extra_params"] = extra
        return cls(**kwargs)


@dataclass(frozen=True)
class InferenceResponse:
    """The result of a non-streaming inference call.

    Attributes:
        model: The model that produced this response.
        text: The generated text output.
        finish_reason: Reason why generation stopped (e.g. "stop", "length",
            "model_error").
        usage: Token usage statistics.
        id: Optional unique identifier for this response.
        created: Unix timestamp when the response was generated.
    """

    model: str
    text: str
    finish_reason: str = "stop"
    usage: t.Optional["TokenUsage"] = None
    id: t.Optional[str] = None
    created: t.Optional[Timestamp] = None

    @classmethod
    def from_dict(cls, data: JSONObject) -> "InferenceResponse":
        """Create an InferenceResponse from a JSON dictionary.

        Args:
            data: Dictionary of response fields.

        Returns:
            A new InferenceResponse instance.
        """
        usage_data: t.Optional[JSONObject] = data.get("usage")
        usage: t.Optional[TokenUsage] = None
        if usage_data:
            usage = TokenUsage.from_dict(usage_data)
        return cls(
            model=data.get("model", ""),
            text=data.get("text", ""),
            finish_reason=data.get("finish_reason", "stop"),
            usage=usage,
            id=data.get("id"),
            created=data.get("created"),
        )


@dataclass(frozen=True)
class TokenUsage:
    """Token usage statistics for an inference request.

    Attributes:
        prompt_tokens: Number of tokens in the prompt.
        completion_tokens: Number of tokens generated.
        total_tokens: Total tokens used (prompt + completion).
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_dict(cls, data: JSONObject) -> "TokenUsage":
        """Create a TokenUsage from a JSON dictionary.

        Args:
            data: Dictionary with token counts.

        Returns:
            A new TokenUsage instance.
        """
        return cls(
            prompt_tokens=data.get("prompt_tokens", 0),
            completion_tokens=data.get("completion_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
        )


@dataclass(frozen=True)
class InferenceChunk:
    """A single token chunk from a streaming inference response.

    These are yielded one at a time by the streaming iterator. The final
    chunk will have ``final=True`` and may contain full response metadata.

    Attributes:
        token: The text token generated by the model.
        model: The model producing this chunk.
        final: Whether this is the last chunk in the stream.
        finish_reason: Reason for finishing (only set when ``final=True``).
        usage: Token usage (only set when ``final=True``).
        index: The index of this token in the generation sequence.
        request_id: The UUID of the originating request.
    """

    token: str
    model: str = ""
    final: bool = False
    finish_reason: t.Optional[str] = None
    usage: t.Optional[TokenUsage] = None
    index: int = 0
    request_id: t.Optional[str] = None

    @classmethod
    def from_dict(cls, data: JSONObject) -> "InferenceChunk":
        """Create an InferenceChunk from a JSON dictionary.

        Args:
            data: Dictionary of chunk fields.

        Returns:
            A new InferenceChunk instance.
        """
        usage_data: t.Optional[JSONObject] = data.get("usage")
        usage: t.Optional[TokenUsage] = None
        if usage_data:
            usage = TokenUsage.from_dict(usage_data)
        return cls(
            token=data.get("token", ""),
            model=data.get("model", ""),
            final=bool(data.get("final", False)),
            finish_reason=data.get("finish_reason"),
            usage=usage,
            index=int(data.get("index", 0)),
            request_id=data.get("request_id"),
        )


# ---------------------------------------------------------------------------
# Model types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelInfo:
    """Metadata about a model loaded in the daemon.

    Attributes:
        id: Unique model identifier.
        name: Human-readable model name.
        path: File path to the model on disk.
        status: Current status (e.g. "loaded", "loading", "unloaded").
        backend: The inference backend (e.g. "llama.cpp", "transformers").
        size_bytes: Size of the model file in bytes.
        loaded_at: Unix timestamp when the model was loaded.
        context_length: Maximum context length in tokens.
        device: The device the model is loaded on (e.g. "cuda:0", "cpu").
        metadata: Additional model-specific metadata.
    """

    id: str
    name: str = ""
    path: str = ""
    status: str = "unknown"
    backend: str = "unknown"
    size_bytes: int = 0
    loaded_at: t.Optional[Timestamp] = None
    context_length: int = 4096
    device: str = "cpu"
    metadata: t.Optional[t.Dict[str, JSONValue]] = None

    @classmethod
    def from_dict(cls, data: JSONObject) -> "ModelInfo":
        """Create a ModelInfo from a JSON dictionary.

        Args:
            data: Dictionary of model metadata fields.

        Returns:
            A new ModelInfo instance.
        """
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            path=data.get("path", ""),
            status=data.get("status", "unknown"),
            backend=data.get("backend", "unknown"),
            size_bytes=int(data.get("size_bytes", 0)),
            loaded_at=data.get("loaded_at"),
            context_length=int(data.get("context_length", 4096)),
            device=data.get("device", "cpu"),
            metadata=data.get("metadata"),
        )


@dataclass(frozen=True)
class ModelConfig:
    """Configuration for loading a model into the daemon.

    Attributes:
        name: Human-readable name for the model.
        path: File path to the model weights.
        backend: Inference backend to use (auto-detected if not specified).
        context_length: Maximum context length override.
        gpu_layers: Number of layers to offload to GPU (for llama.cpp).
        quantisation: Quantisation type (e.g. "q4_0", "q8_0").
        device: Device to load the model on.
        extra_options: Additional backend-specific options.
    """

    name: str
    path: str
    backend: t.Optional[str] = None
    context_length: t.Optional[int] = None
    gpu_layers: t.Optional[int] = None
    quantisation: t.Optional[str] = None
    device: t.Optional[str] = None
    extra_options: t.Optional[t.Dict[str, JSONValue]] = None

    def to_dict(self) -> JSONObject:
        """Convert this config to a JSON-compatible dictionary.

        Returns:
            A dictionary with all non-None fields.
        """
        result: JSONObject = {}
        for field_ in dataclasses.fields(self):
            value: t.Any = getattr(self, field_.name)
            if value is not None:
                result[field_.name] = value
        return result


# ---------------------------------------------------------------------------
# System / Health types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SystemStatus:
    """Overall system status of the daemon.

    Attributes:
        version: Daemon version string.
        uptime_seconds: Seconds since daemon started.
        active_models: Number of models currently loaded.
        total_models: Total number of models registered.
        memory_used_mb: Memory used by the daemon in MB.
        memory_total_mb: Total available memory in MB.
        gpu_usage_percent: GPU utilisation percentage (if applicable).
        gpu_memory_used_mb: GPU memory used in MB.
        gpu_memory_total_mb: Total GPU memory in MB.
        cpu_usage_percent: CPU utilisation percentage.
        active_requests: Number of requests currently being processed.
        queued_requests: Number of requests waiting in the queue.
        status: Daemon status string (e.g. "running", "degraded").
        errors: List of recent error messages.
    """

    version: str = ""
    uptime_seconds: float = 0.0
    active_models: int = 0
    total_models: int = 0
    memory_used_mb: float = 0.0
    memory_total_mb: float = 0.0
    gpu_usage_percent: t.Optional[float] = None
    gpu_memory_used_mb: t.Optional[float] = None
    gpu_memory_total_mb: t.Optional[float] = None
    cpu_usage_percent: float = 0.0
    active_requests: int = 0
    queued_requests: int = 0
    status: str = "unknown"
    errors: t.Optional[t.List[str]] = None

    @classmethod
    def from_dict(cls, data: JSONObject) -> "SystemStatus":
        """Create a SystemStatus from a JSON dictionary.

        Args:
            data: Dictionary of system status fields.

        Returns:
            A new SystemStatus instance.
        """
        return cls(
            version=data.get("version", ""),
            uptime_seconds=float(data.get("uptime_seconds", 0.0)),
            active_models=int(data.get("active_models", 0)),
            total_models=int(data.get("total_models", 0)),
            memory_used_mb=float(data.get("memory_used_mb", 0.0)),
            memory_total_mb=float(data.get("memory_total_mb", 0.0)),
            gpu_usage_percent=_to_optional_float(data.get("gpu_usage_percent")),
            gpu_memory_used_mb=_to_optional_float(data.get("gpu_memory_used_mb")),
            gpu_memory_total_mb=_to_optional_float(data.get("gpu_memory_total_mb")),
            cpu_usage_percent=float(data.get("cpu_usage_percent", 0.0)),
            active_requests=int(data.get("active_requests", 0)),
            queued_requests=int(data.get("queued_requests", 0)),
            status=data.get("status", "unknown"),
            errors=data.get("errors"),
        )


@dataclass(frozen=True)
class HealthStatus:
    """High-level health check result from the daemon.

    Attributes:
        healthy: Whether the daemon is healthy and ready to serve requests.
        status: Human-readable status string.
        version: Daemon version.
        uptime_seconds: Seconds since the daemon started.
        active_models: Number of loaded models.
        message: Optional additional status message.
    """

    healthy: bool = False
    status: str = "unknown"
    version: str = ""
    uptime_seconds: float = 0.0
    active_models: int = 0
    message: t.Optional[str] = None

    @classmethod
    def from_dict(cls, data: JSONObject) -> "HealthStatus":
        """Create a HealthStatus from a JSON dictionary.

        Args:
            data: Dictionary of health status fields.

        Returns:
            A new HealthStatus instance.
        """
        return cls(
            healthy=bool(data.get("healthy", False)),
            status=data.get("status", "unknown"),
            version=data.get("version", ""),
            uptime_seconds=float(data.get("uptime_seconds", 0.0)),
            active_models=int(data.get("active_models", 0)),
            message=data.get("message"),
        )


# ---------------------------------------------------------------------------
# Connection types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConnectionConfig:
    """Connection parameters for the transport layer.

    Attributes:
        host: Daemon hostname or IP address.
        port: Daemon TCP port.
        auth_token: Optional Bearer token for authentication.
        connect_timeout: Timeout for the initial TCP connection in seconds.
        request_timeout: Default timeout for requests in seconds.
        reconnect_attempts: Maximum number of reconnection attempts.
        reconnect_delay: Initial delay between reconnection attempts
            (uses exponential backoff).
        max_buffer_size: Maximum send buffer size in bytes.
        max_message_size: Maximum message size in bytes (send and receive).
        pool_size: Maximum number of connections in the pool.
        ssl: Whether to use SSL/TLS encryption.
        ssl_ca_cert: Path to CA certificate for SSL verification.
    """

    host: str = "127.0.0.1"
    port: int = 9500
    auth_token: t.Optional[str] = None
    connect_timeout: float = 10.0
    request_timeout: float = 60.0
    reconnect_attempts: int = 3
    reconnect_delay: float = 1.0
    max_buffer_size: int = 16 * 1024 * 1024  # 16 MiB
    max_message_size: int = 16 * 1024 * 1024  # 16 MiB
    pool_size: int = 4
    ssl: bool = False
    ssl_ca_cert: t.Optional[str] = None


# ---------------------------------------------------------------------------
# Protocol message types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RequestMessage:
    """An NDJSON request message sent to the daemon.

    Attributes:
        type: Message type, always ``"request"``.
        id: Unique request identifier (UUID).
        method: The RPC method to call.
        params: Method parameters as a JSON object.
        auth: Optional authentication header.
    """

    type: str = "request"
    id: str = ""
    method: str = ""
    params: JSONObject = field(default_factory=dict)
    auth: t.Optional[str] = None

    def to_dict(self) -> JSONObject:
        """Convert to a JSON-compatible dictionary.

        Returns:
            A dictionary ready for JSON serialisation, with None values
            omitted.
        """
        result: JSONObject = {
            "type": self.type,
            "id": self.id,
            "method": self.method,
            "params": self.params,
        }
        if self.auth is not None:
            result["auth"] = self.auth
        return result

    @classmethod
    def from_dict(cls, data: JSONObject) -> "RequestMessage":
        """Create a RequestMessage from a JSON dictionary.

        Args:
            data: Dictionary of message fields.

        Returns:
            A new RequestMessage instance.
        """
        return cls(
            type=data.get("type", "request"),
            id=data.get("id", ""),
            method=data.get("method", ""),
            params=data.get("params", {}),
            auth=data.get("auth"),
        )


@dataclass(frozen=True)
class ResponseMessage:
    """An NDJSON response message received from the daemon.

    Attributes:
        type: Message type, always ``"response"``.
        id: The UUID of the request this response corresponds to.
        result: The result payload (present on success).
        error: The error payload (present on failure).
    """

    type: str = "response"
    id: str = ""
    result: t.Optional[JSONValue] = None
    error: t.Optional["ErrorMessage"] = None

    @property
    def is_error(self) -> bool:
        """Whether this response represents an error."""
        return self.error is not None

    @classmethod
    def from_dict(cls, data: JSONObject) -> "ResponseMessage":
        """Create a ResponseMessage from a JSON dictionary.

        Args:
            data: Dictionary of message fields.

        Returns:
            A new ResponseMessage instance.
        """
        error_data: t.Optional[JSONObject] = data.get("error")
        error_msg: t.Optional[ErrorMessage] = None
        if error_data:
            error_msg = ErrorMessage.from_dict(error_data)
        return cls(
            type=data.get("type", "response"),
            id=data.get("id", ""),
            result=data.get("result"),
            error=error_msg,
        )


@dataclass(frozen=True)
class StreamMessage:
    """A streaming chunk message received from the daemon.

    Attributes:
        type: Message type, always ``"stream"``.
        id: The UUID of the originating request.
        data: The stream chunk payload.
    """

    type: str = "stream"
    id: str = ""
    data: JSONObject = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: JSONObject) -> "StreamMessage":
        """Create a StreamMessage from a JSON dictionary.

        Args:
            data: Dictionary of message fields.

        Returns:
            A new StreamMessage instance.
        """
        return cls(
            type=data.get("type", "stream"),
            id=data.get("id", ""),
            data=data.get("data", {}),
        )


@dataclass(frozen=True)
class ErrorMessage:
    """An error payload within a response message.

    Attributes:
        code: Numeric error code.
        message: Human-readable error description.
        data: Optional additional error data.
    """

    code: int = -1
    message: str = ""
    data: t.Optional[JSONValue] = None

    @classmethod
    def from_dict(cls, data: JSONObject) -> "ErrorMessage":
        """Create an ErrorMessage from a JSON dictionary.

        Args:
            data: Dictionary of error fields.

        Returns:
            A new ErrorMessage instance.
        """
        return cls(
            code=int(data.get("code", -1)),
            message=data.get("message", ""),
            data=data.get("data"),
        )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _to_optional_float(value: t.Any) -> t.Optional[float]:
    """Convert a value to an optional float.

    Args:
        value: The value to convert.

    Returns:
        A float, or None if the value is None.
    """
    if value is None:
        return None
    return float(value)


__all__: list[str] = [
    "InferenceRequest",
    "InferenceResponse",
    "InferenceChunk",
    "TokenUsage",
    "ModelInfo",
    "ModelConfig",
    "SystemStatus",
    "HealthStatus",
    "ConnectionConfig",
    "RequestMessage",
    "ResponseMessage",
    "StreamMessage",
    "ErrorMessage",
    "JSONValue",
    "JSONObject",
    "RequestId",
    "Timestamp",
]