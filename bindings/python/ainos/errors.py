"""
Ainos SDK - Exception Hierarchy
================================

Defines a rich exception hierarchy for the Ainos SDK. Every error that can
arise from the SDK is represented as a typed exception, allowing callers to
catch precisely the errors they care about.

Exception Tree::

    AinosError (BaseException)
    +-- ConnectionError
    |   +-- ConnectionTimeoutError
    |   +-- AuthenticationError
    |   +-- ReconnectionFailedError
    +-- ProtocolError
    |   +-- InvalidMessageError
    |   +-- MessageTooLargeError
    +-- RequestError
    |   +-- InvalidRequestError
    |   +-- RequestTimeoutError
    |   +-- RequestCancelledError
    +-- InferenceError
    |   +-- ModelNotLoadedError
    |   +-- InvalidPromptError
    |   +-- ContextLengthExceededError
    |   +-- InferenceTimeoutError
    +-- ModelError
    |   +-- ModelNotFoundError
    |   +-- ModelLoadError
    |   +-- ModelUnloadError
    |   +-- ModelBusyError
    +-- StreamError
    |   +-- StreamInterruptedError
    |   +-- StreamNotStartedError
    +-- ConfigurationError
    +-- TransportError
    |   +-- TransportClosedError
    |   +-- TransportBufferFullError

Usage::

    from ainos.errors import ConnectionTimeoutError, InferenceError

    try:
        result = await client.infer("my-model", "Hello")
    except ConnectionTimeoutError:
        print("Daemon not reachable")
    except InferenceError as e:
        print(f"Inference failed: {e}")
"""

from __future__ import annotations

import typing as t


class AinosError(Exception):
    """Base exception for all Ainos SDK errors.

    Every exception raised by the SDK inherits from this class, making it
    possible to catch all SDK-originated errors with a single ``except
    AinosError`` clause.

    Attributes:
        message: Human-readable error description.
        code: Optional numeric error code from the daemon.
        cause: Optional originating exception (useful for exception chaining).
    """

    def __init__(
        self,
        message: str = "",
        *,
        code: t.Optional[int] = None,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise the exception.

        Args:
            message: Human-readable error description.
            code: Optional numeric error code from the daemon.
            cause: Optional originating exception.
        """
        self.message: str = message
        self.code: t.Optional[int] = code
        self.cause: t.Optional[BaseException] = cause
        if cause is not None:
            super().__init__(message, cause)
        else:
            super().__init__(message)

    def __str__(self) -> str:
        """Return a formatted error string including code and cause."""
        parts: list[str] = [self.message]
        if self.code is not None:
            parts.append(f"[code={self.code}]")
        if self.cause is not None:
            parts.append(f"(caused by: {self.cause})")
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Connection errors
# ---------------------------------------------------------------------------


class ConnectionError(AinosError):
    """Raised when the SDK cannot establish or maintain a connection.

    This is the base class for all connection-related errors. It is raised
    when the initial TCP handshake fails, the remote end closes the
    connection unexpectedly, or the connection pool is exhausted.
    """


class ConnectionTimeoutError(ConnectionError):
    """Raised when a connection attempt exceeds the configured timeout.

    This typically occurs when the daemon is not running, the host is
    unreachable, or a firewall is blocking the port.
    """

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float,
        *,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise with connection target details.

        Args:
            host: The remote host that was being connected to.
            port: The remote port.
            timeout: The timeout value in seconds.
            cause: Optional originating exception.
        """
        self.host: str = host
        self.port: int = port
        self.timeout: float = timeout
        super().__init__(
            f"Connection to {host}:{port} timed out after {timeout}s",
            cause=cause,
        )


class AuthenticationError(ConnectionError):
    """Raised when authentication with the daemon fails.

    This can happen if the token is invalid, expired, or the daemon rejects
    the credentials for any reason.
    """

    def __init__(
        self,
        message: str = "Authentication failed",
        *,
        token_hint: t.Optional[str] = None,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise with optional token hint.

        Args:
            message: Human-readable error description.
            token_hint: A prefix of the token that failed (for debugging).
            cause: Optional originating exception.
        """
        self.token_hint: t.Optional[str] = token_hint
        if token_hint:
            msg = f"{message} (token: {token_hint}...)"
        else:
            msg = message
        super().__init__(msg, cause=cause)


class ReconnectionFailedError(ConnectionError):
    """Raised after all reconnection attempts have been exhausted.

    The transport layer will attempt to reconnect according to the configured
    backoff strategy. If all attempts fail, this exception is raised.
    """

    def __init__(
        self,
        attempts: int,
        last_error: t.Optional[BaseException] = None,
        *,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise with attempt count.

        Args:
            attempts: Number of reconnection attempts made.
            last_error: The error from the last failed attempt.
            cause: Optional originating exception.
        """
        self.attempts: int = attempts
        self.last_error: t.Optional[BaseException] = last_error
        msg = f"All {attempts} reconnection attempts failed"
        if last_error:
            msg += f" (last: {last_error})"
        super().__init__(msg, cause=cause or last_error)


# ---------------------------------------------------------------------------
# Protocol errors
# ---------------------------------------------------------------------------


class ProtocolError(AinosError):
    """Raised when a malformed or unexpected message is received.

    This covers JSON parse failures, missing required fields, and messages
    that do not conform to the NDJSON protocol specification.
    """


class InvalidMessageError(ProtocolError):
    """Raised when a received message cannot be parsed or lacks required fields.

    This can happen if the daemon sends a message with an unknown ``type``
    field, missing ``id``, or invalid JSON structure.
    """

    def __init__(
        self,
        raw: t.Union[str, bytes],
        detail: str = "",
        *,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise with the raw message that failed.

        Args:
            raw: The raw message payload that could not be parsed.
            detail: Human-readable description of what was wrong.
            cause: Optional originating exception.
        """
        self.raw: t.Union[str, bytes] = raw
        preview = raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace")
        if len(preview) > 200:
            preview = preview[:200] + "..."
        msg = f"Invalid message: {detail} (raw: {preview})"
        super().__init__(msg, cause=cause)


class MessageTooLargeError(ProtocolError):
    """Raised when a message exceeds the maximum allowed size.

    Both sent and received messages are checked against the configured limit
    (default 16 MiB).
    """

    def __init__(
        self,
        size: int,
        limit: int,
        direction: str = "send",
        *,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise with size details.

        Args:
            size: The actual size of the message in bytes.
            limit: The maximum allowed size in bytes.
            direction: ``"send"`` or ``"recv"``.
            cause: Optional originating exception.
        """
        self.size: int = size
        self.limit: int = limit
        self.direction: str = direction
        super().__init__(
            f"Message too large for {direction}: {size} bytes (limit: {limit})",
            cause=cause,
        )


# ---------------------------------------------------------------------------
# Request errors
# ---------------------------------------------------------------------------


class RequestError(AinosError):
    """Raised when a request fails before or during processing.

    This is the base class for request-level errors that are not related to
    the transport or protocol layer.
    """


class InvalidRequestError(RequestError):
    """Raised when a request is malformed or contains invalid parameters.

    This is typically returned by the daemon when it cannot process the
    request due to missing or invalid fields.
    """

    def __init__(
        self,
        method: str,
        params: t.Optional[t.Dict[str, t.Any]] = None,
        detail: str = "",
        *,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise with request details.

        Args:
            method: The RPC method that was called.
            params: The parameters that were sent.
            detail: Server-provided error detail.
            cause: Optional originating exception.
        """
        self.method: str = method
        self.params: t.Optional[t.Dict[str, t.Any]] = params
        msg = f"Invalid request for '{method}': {detail}"
        super().__init__(msg, cause=cause)


class RequestTimeoutError(RequestError):
    """Raised when a request exceeds the configured timeout.

    The request was sent but no response was received within the timeout
    window.
    """

    def __init__(
        self,
        request_id: str,
        method: str,
        timeout: float,
        *,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise with request details.

        Args:
            request_id: The UUID of the timed-out request.
            method: The RPC method that was called.
            timeout: The timeout value in seconds.
            cause: Optional originating exception.
        """
        self.request_id: str = request_id
        self.method: str = method
        self.timeout: float = timeout
        super().__init__(
            f"Request '{request_id}' ({method}) timed out after {timeout}s",
            cause=cause,
        )


class RequestCancelledError(RequestError):
    """Raised when a request is cancelled before completion.

    This can happen when the client explicitly cancels a request, or when
    the connection is closed while the request is in-flight.
    """

    def __init__(
        self,
        request_id: str,
        reason: str = "cancelled",
        *,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise with request details.

        Args:
            request_id: The UUID of the cancelled request.
            reason: The reason for cancellation.
            cause: Optional originating exception.
        """
        self.request_id: str = request_id
        self.reason: str = reason
        super().__init__(
            f"Request '{request_id}' cancelled: {reason}",
            cause=cause,
        )


# ---------------------------------------------------------------------------
# Inference errors
# ---------------------------------------------------------------------------


class InferenceError(AinosError):
    """Raised when an inference operation fails.

    This is the base class for all inference-related errors, covering model
    issues, prompt problems, and execution failures.
    """


class ModelNotLoadedError(InferenceError):
    """Raised when the targeted model is not currently loaded in memory.

    The caller should call ``model_load()`` first or use a different model
    identifier.
    """

    def __init__(
        self,
        model: str,
        *,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise with model identifier.

        Args:
            model: The model identifier that was not loaded.
            cause: Optional originating exception.
        """
        self.model: str = model
        super().__init__(
            f"Model '{model}' is not loaded. Call model_load() first.",
            cause=cause,
        )


class InvalidPromptError(InferenceError):
    """Raised when the prompt is empty, malformed, or exceeds constraints.

    This covers prompts that are too long, contain invalid characters, or
    do not match the expected format for the model.
    """

    def __init__(
        self,
        detail: str = "Invalid prompt",
        *,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise with error detail.

        Args:
            detail: Description of what is wrong with the prompt.
            cause: Optional originating exception.
        """
        super().__init__(detail, cause=cause)


class ContextLengthExceededError(InferenceError):
    """Raised when the prompt exceeds the model's context window.

    The model has a maximum context length (e.g. 4096 tokens) and the
    combined prompt + previous context exceeds this limit.
    """

    def __init__(
        self,
        model: str,
        prompt_tokens: int,
        max_tokens: int,
        *,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise with token count details.

        Args:
            model: The model identifier.
            prompt_tokens: The number of tokens in the prompt.
            max_tokens: The maximum allowed context length.
            cause: Optional originating exception.
        """
        self.model: str = model
        self.prompt_tokens: int = prompt_tokens
        self.max_tokens: int = max_tokens
        super().__init__(
            f"Prompt exceeds context window for '{model}': "
            f"{prompt_tokens} tokens (max: {max_tokens})",
            cause=cause,
        )


class InferenceTimeoutError(InferenceError):
    """Raised when an inference request exceeds the maximum allowed time.

    The inference was started but the daemon did not complete it within the
    configured timeout.
    """

    def __init__(
        self,
        model: str,
        timeout: float,
        *,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise with inference details.

        Args:
            model: The model identifier.
            timeout: The timeout value in seconds.
            cause: Optional originating exception.
        """
        self.model: str = model
        self.timeout: float = timeout
        super().__init__(
            f"Inference on '{model}' timed out after {timeout}s",
            cause=cause,
        )


# ---------------------------------------------------------------------------
# Model errors
# ---------------------------------------------------------------------------


class ModelError(AinosError):
    """Raised for model management operations that fail.

    This is the base class for errors related to loading, unloading, and
    querying models.
    """


class ModelNotFoundError(ModelError):
    """Raised when a model identifier does not match any known model.

    This can happen when listing models, loading, or unloading.
    """

    def __init__(
        self,
        model_id: str,
        *,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise with model identifier.

        Args:
            model_id: The model identifier that was not found.
            cause: Optional originating exception.
        """
        self.model_id: str = model_id
        super().__init__(f"Model '{model_id}' not found", cause=cause)


class ModelLoadError(ModelError):
    """Raised when a model fails to load into memory.

    This can be due to file not found, out of memory, unsupported format, or
    other hardware/software constraints.
    """

    def __init__(
        self,
        name: str,
        path: str,
        detail: str = "",
        *,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise with load attempt details.

        Args:
            name: The model name.
            path: The file path that was attempted.
            detail: Server-provided error detail.
            cause: Optional originating exception.
        """
        self.name: str = name
        self.path: str = path
        super().__init__(
            f"Failed to load model '{name}' from {path}: {detail}",
            cause=cause,
        )


class ModelUnloadError(ModelError):
    """Raised when a model fails to unload.

    This can happen if the model is in use, or the daemon encounters an
    error during cleanup.
    """

    def __init__(
        self,
        model_id: str,
        detail: str = "",
        *,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise with unload attempt details.

        Args:
            model_id: The model identifier.
            detail: Server-provided error detail.
            cause: Optional originating exception.
        """
        self.model_id: str = model_id
        super().__init__(
            f"Failed to unload model '{model_id}': {detail}",
            cause=cause,
        )


class ModelBusyError(ModelError):
    """Raised when a model is busy processing another request.

    The model is single-threaded or has a limited concurrency and the
    current request cannot be queued.
    """

    def __init__(
        self,
        model_id: str,
        *,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise with model identifier.

        Args:
            model_id: The model identifier.
            cause: Optional originating exception.
        """
        self.model_id: str = model_id
        super().__init__(
            f"Model '{model_id}' is busy processing another request",
            cause=cause,
        )


# ---------------------------------------------------------------------------
# Stream errors
# ---------------------------------------------------------------------------


class StreamError(AinosError):
    """Raised when a streaming operation encounters an error.

    This is the base class for all stream-related errors.
    """


class StreamInterruptedError(StreamError):
    """Raised when an active stream is interrupted mid-way.

    This can happen if the connection drops, the daemon restarts, or the
    stream is explicitly cancelled.
    """

    def __init__(
        self,
        request_id: str,
        received_tokens: int,
        *,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise with stream details.

        Args:
            request_id: The UUID of the interrupted stream.
            received_tokens: Number of tokens received before interruption.
            cause: Optional originating exception.
        """
        self.request_id: str = request_id
        self.received_tokens: int = received_tokens
        super().__init__(
            f"Stream '{request_id}' interrupted after {received_tokens} tokens",
            cause=cause,
        )


class StreamNotStartedError(StreamError):
    """Raised when attempting to read from a stream that has not started.

    The caller must first call ``infer_stream()`` or ``start_stream()``
    before iterating over the stream.
    """

    def __init__(
        self,
        *,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise."""
        super().__init__(
            "Stream has not been started. Call infer_stream() first.",
            cause=cause,
        )


# ---------------------------------------------------------------------------
# Configuration / Transport errors
# ---------------------------------------------------------------------------


class ConfigurationError(AinosError):
    """Raised when the SDK is misconfigured.

    This covers missing required configuration values, invalid setting
    combinations, and environment issues.
    """

    def __init__(
        self,
        message: str,
        *,
        setting: t.Optional[str] = None,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise with configuration details.

        Args:
            message: Human-readable error description.
            setting: The name of the misconfigured setting (if applicable).
            cause: Optional originating exception.
        """
        self.setting: t.Optional[str] = setting
        if setting:
            msg = f"Configuration error for '{setting}': {message}"
        else:
            msg = f"Configuration error: {message}"
        super().__init__(msg, cause=cause)


class TransportError(AinosError):
    """Raised for low-level transport failures.

    This is the base class for errors originating from the transport layer.
    """


class TransportClosedError(TransportError):
    """Raised when attempting to use a transport that has been closed.

    The transport must be re-initialised before it can be used again.
    """

    def __init__(
        self,
        *,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise."""
        super().__init__("Transport is closed", cause=cause)


class TransportBufferFullError(TransportError):
    """Raised when the send buffer exceeds its capacity.

    The transport has a maximum buffer size for outgoing messages. If the
    client sends data faster than the daemon can consume it, this error is
    raised.
    """

    def __init__(
        self,
        buffer_size: int,
        max_size: int,
        *,
        cause: t.Optional[BaseException] = None,
    ) -> None:
        """Initialise with buffer details.

        Args:
            buffer_size: Current buffer size in bytes.
            max_size: Maximum allowed buffer size in bytes.
            cause: Optional originating exception.
        """
        self.buffer_size: int = buffer_size
        self.max_size: int = max_size
        super().__init__(
            f"Transport buffer full: {buffer_size}/{max_size} bytes",
            cause=cause,
        )


# ---------------------------------------------------------------------------
# Error code mapping
# ---------------------------------------------------------------------------

#: Mapping from daemon error codes to exception classes.
#: Used by the client to convert daemon responses into typed exceptions.
ERROR_CODE_MAP: t.Dict[int, t.Type[AinosError]] = {
    -32700: InvalidMessageError,     # Parse error
    -32600: InvalidRequestError,     # Invalid request
    -32601: RequestError,            # Method not found
    -32602: InvalidRequestError,     # Invalid params
    -32603: InferenceError,          # Internal error
    -32000: ModelNotFoundError,      # Model not found
    -32001: ModelLoadError,          # Model load failed
    -32002: ModelUnloadError,        # Model unload failed
    -32003: ModelBusyError,          # Model busy
    -32004: ModelNotLoadedError,     # Model not loaded
    -32010: ContextLengthExceededError,  # Context length exceeded
    -32011: InvalidPromptError,      # Invalid prompt
    -32012: InferenceTimeoutError,   # Inference timeout
    -32020: AuthenticationError,     # Auth failed
    -32030: RequestTimeoutError,     # Request timeout
}


def error_from_code(
    code: int,
    message: str,
    *,
    cause: t.Optional[BaseException] = None,
) -> AinosError:
    """Create an appropriate exception instance from a daemon error code.

    Args:
        code: Numeric error code returned by the daemon.
        message: Human-readable error message from the daemon.
        cause: Optional originating exception for chaining.

    Returns:
        An instance of the most specific exception class for the given code,
        or a generic ``AinosError`` if the code is unknown.
    """
    exc_cls: t.Type[AinosError] = ERROR_CODE_MAP.get(code, AinosError)
    exc: AinosError = exc_cls(message, cause=cause)
    exc.code = code
    return exc