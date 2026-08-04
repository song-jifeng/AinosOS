"""
Ainos SDK - Utility Functions
==============================

Provides utility functions for JSON encoding/decoding, timing, retry logic,
and other common operations used throughout the SDK.

Functions:
    - json_encode: Serialise an object to JSON bytes.
    - json_decode: Deserialise JSON bytes to a Python object.
    - generate_request_id: Generate a unique request ID (UUID4).
    - timestamp: Get the current Unix timestamp.
    - retry: Decorator for retrying async functions with exponential backoff.
    - validate_host: Validate a hostname or IP address.
    - truncate: Truncate a string to a maximum length with ellipsis.
    - merge_dicts: Deep-merge two dictionaries.
    - format_bytes: Format a byte count as a human-readable string.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import random
import socket
import time
import typing as t
import uuid

from ainos.errors import ReconnectionFailedError

# Module-level logger
log: logging.Logger = logging.getLogger("ainos.utils")

# Type alias for a JSON-encodable value
Encodable = t.Union[t.Dict[str, t.Any], t.List[t.Any], str, int, float, bool, None]


# ---------------------------------------------------------------------------
# JSON utilities
# ---------------------------------------------------------------------------


def json_encode(obj: t.Any, *, compact: bool = True) -> bytes:
    """Serialise an object to JSON bytes (UTF-8 encoded).

    Args:
        obj: The object to serialise. Must be JSON-encodable.
        compact: If True, produce compact output with no extra whitespace.
            If False, produce pretty-printed output (useful for debugging).

    Returns:
        UTF-8 encoded JSON bytes, with a trailing newline.

    Raises:
        TypeError: If the object is not JSON-encodable.
        ValueError: If the object contains circular references.
    """
    if compact:
        raw: str = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    else:
        raw = json.dumps(obj, indent=2, ensure_ascii=False)
    return raw.encode("utf-8") + b"\n"


def json_decode(data: t.Union[bytes, bytearray, str]) -> t.Any:
    """Deserialise JSON bytes or string to a Python object.

    Args:
        data: The JSON data to parse. Accepts bytes, bytearray, or str.

    Returns:
        The deserialised Python object.

    Raises:
        ValueError: If the input is not valid JSON.
        TypeError: If the input type is not supported.
    """
    if isinstance(data, (bytes, bytearray)):
        return json.loads(data.decode("utf-8"))
    if isinstance(data, str):
        return json.loads(data)
    raise TypeError(f"Expected bytes, bytearray, or str, got {type(data).__name__}")


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------


def generate_request_id() -> str:
    """Generate a unique request identifier.

    Uses UUID4 to create a statistically unique identifier suitable for
    correlating requests and responses.

    Returns:
        A UUID4 string (e.g. ``"f47ac10b-58cc-4372-a567-0e02b2c3d479"``).
    """
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Time utilities
# ---------------------------------------------------------------------------


def timestamp() -> float:
    """Get the current Unix timestamp with sub-second precision.

    Returns:
        Current time in seconds since the Unix epoch, as a float.
    """
    return time.time()


def monotonic_ns() -> int:
    """Get a monotonic clock value in nanoseconds.

    This clock is guaranteed to never go backwards, making it suitable for
    measuring elapsed time.

    Returns:
        Monotonic clock value in nanoseconds.
    """
    return time.monotonic_ns()


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    exceptions: t.Tuple[t.Type[BaseException], ...] = (ConnectionError, OSError),
) -> t.Callable[..., t.Any]:
    """Decorator factory for retrying async functions with exponential backoff.

    The decorated function will be retried up to ``max_attempts`` times when
    it raises one of the specified exceptions. Between retries, it waits for
    an exponentially increasing delay with optional jitter.

    Args:
        max_attempts: Maximum number of attempts (including the first).
        base_delay: Initial delay in seconds before the first retry.
        max_delay: Maximum delay in seconds between retries.
        backoff_factor: Multiplier for the delay after each retry.
        jitter: If True, adds random jitter to the delay to avoid thundering
            herd problems.
        exceptions: Tuple of exception classes that trigger a retry.

    Returns:
        A decorator that wraps an async function with retry logic.

    Example:
        @retry(max_attempts=5, base_delay=0.5)
        async def connect_with_retry():
            return await transport.connect()
    """

    def decorator(func: t.Callable[..., t.Any]) -> t.Callable[..., t.Any]:
        @functools.wraps(func)
        async def wrapper(*args: t.Any, **kwargs: t.Any) -> t.Any:
            last_exc: t.Optional[BaseException] = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        raise ReconnectionFailedError(
                            attempts=max_attempts,
                            last_error=exc,
                            cause=exc,
                        ) from exc

                    delay: float = min(
                        base_delay * (backoff_factor ** (attempt - 1)),
                        max_delay,
                    )
                    if jitter:
                        delay *= 0.5 + random.random() * 0.5

                    log.warning(
                        "Attempt %d/%d failed: %s. Retrying in %.2fs...",
                        attempt,
                        max_attempts,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)

            # Should not be reached, but satisfy the type checker
            raise ReconnectionFailedError(
                attempts=max_attempts,
                last_error=last_exc,
            )

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Synchronous retry (for use in non-async contexts)
# ---------------------------------------------------------------------------


def retry_sync(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    exceptions: t.Tuple[t.Type[BaseException], ...] = (ConnectionError, OSError),
) -> t.Callable[..., t.Any]:
    """Decorator factory for retrying synchronous functions.

    This is the synchronous counterpart of :func:`retry`. It uses
    ``time.sleep()`` instead of ``asyncio.sleep()``.

    Args:
        max_attempts: Maximum number of attempts (including the first).
        base_delay: Initial delay in seconds before the first retry.
        max_delay: Maximum delay in seconds between retries.
        backoff_factor: Multiplier for the delay after each retry.
        jitter: If True, adds random jitter to the delay.
        exceptions: Tuple of exception classes that trigger a retry.

    Returns:
        A decorator that wraps a synchronous function with retry logic.
    """

    def decorator(func: t.Callable[..., t.Any]) -> t.Callable[..., t.Any]:
        @functools.wraps(func)
        def wrapper(*args: t.Any, **kwargs: t.Any) -> t.Any:
            last_exc: t.Optional[BaseException] = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        raise ReconnectionFailedError(
                            attempts=max_attempts,
                            last_error=exc,
                            cause=exc,
                        ) from exc

                    delay: float = min(
                        base_delay * (backoff_factor ** (attempt - 1)),
                        max_delay,
                    )
                    if jitter:
                        delay *= 0.5 + random.random() * 0.5

                    log.warning(
                        "Attempt %d/%d failed: %s. Retrying in %.2fs...",
                        attempt,
                        max_attempts,
                        exc,
                        delay,
                    )
                    time.sleep(delay)

            raise ReconnectionFailedError(
                attempts=max_attempts,
                last_error=last_exc,
            )

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_host(host: str) -> bool:
    """Validate that a string is a valid hostname or IP address.

    This performs a basic sanity check; it does not attempt to resolve the
    hostname via DNS.

    Args:
        host: The hostname or IP address to validate.

    Returns:
        True if the host appears valid, False otherwise.
    """
    if not host or not isinstance(host, str):
        return False
    if len(host) > 255:
        return False
    # Check for valid IPv4 address
    parts: list[str] = host.split(".")
    if len(parts) == 4:
        try:
            return all(0 <= int(p) <= 255 for p in parts)
        except ValueError:
            pass
    # Check for valid IPv6 (simplified)
    if host.startswith("[") and host.endswith("]"):
        inner: str = host[1:-1]
        if ":" in inner:
            return True
    # Check for valid hostname
    if host.replace(".", "").replace("-", "").isalnum():
        return True
    return False


def validate_port(port: int) -> bool:
    """Validate that a port number is in the valid range.

    Args:
        port: The port number to validate.

    Returns:
        True if the port is between 1 and 65535, False otherwise.
    """
    return isinstance(port, int) and 1 <= port <= 65535


# ---------------------------------------------------------------------------
# String utilities
# ---------------------------------------------------------------------------


def truncate(text: str, max_length: int = 100, ellipsis: str = "...") -> str:
    """Truncate a string to a maximum length, adding an ellipsis if truncated.

    Args:
        text: The string to truncate.
        max_length: Maximum character length (including the ellipsis).
        ellipsis: The string to append when truncated.

    Returns:
        The truncated string. If ``text`` is shorter than ``max_length``,
        it is returned unchanged.
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - len(ellipsis)] + ellipsis


# ---------------------------------------------------------------------------
# Dictionary utilities
# ---------------------------------------------------------------------------


def merge_dicts(
    base: t.Dict[str, t.Any],
    override: t.Dict[str, t.Any],
    *,
    deep: bool = True,
) -> t.Dict[str, t.Any]:
    """Merge two dictionaries, with ``override`` taking precedence.

    Performs a deep merge when both values are dictionaries; otherwise the
    override value replaces the base value.

    Args:
        base: The base dictionary (lower priority).
        override: The override dictionary (higher priority).
        deep: If True, recursively merge nested dictionaries.

    Returns:
        A new dictionary with the merged contents. Neither input dict is
        modified.
    """
    result: t.Dict[str, t.Any] = dict(base)

    for key, value in override.items():
        if deep and key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dicts(result[key], value, deep=True)
        else:
            result[key] = value

    return result


# ---------------------------------------------------------------------------
# Byte formatting
# ---------------------------------------------------------------------------


def format_bytes(size: int) -> str:
    """Format a byte count as a human-readable string.

    Uses binary prefixes (KiB, MiB, GiB, TiB).

    Args:
        size: The size in bytes.

    Returns:
        A formatted string like ``"4.2 MiB"`` or ``"1.5 GiB"``.
    """
    if size < 0:
        return f"{size} B"
    units: list[str] = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    unit_index: int = 0
    value: float = float(size)
    while value >= 1024.0 and unit_index < len(units) - 1:
        value /= 1024.0
        unit_index += 1
    if unit_index == 0:
        return f"{int(value)} {units[unit_index]}"
    return f"{value:.2f} {units[unit_index]}"


# ---------------------------------------------------------------------------
# Network utilities
# ---------------------------------------------------------------------------


def resolve_host(
    host: str,
    port: int,
    *,
    family: int = socket.AF_UNSPEC,
) -> t.List[t.Tuple[socket.AddressFamily, socket.SocketKind, int, str, t.Tuple[str, int]]]:
    """Resolve a hostname to socket address information.

    Wraps ``socket.getaddrinfo()`` with consistent error handling.

    Args:
        host: The hostname to resolve.
        port: The port number.
        family: Socket family (``AF_INET``, ``AF_INET6``, or ``AF_UNSPEC``).

    Returns:
        A list of address info tuples as returned by ``getaddrinfo()``.

    Raises:
        socket.gaierror: If the hostname cannot be resolved.
    """
    return socket.getaddrinfo(host, port, family=family, type=socket.SOCK_STREAM)


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging(
    level: int = logging.INFO,
    fmt: t.Optional[str] = None,
) -> None:
    """Configure the SDK's logging.

    Call this once at application startup to enable SDK logging output.

    Args:
        level: The logging level (e.g. ``logging.DEBUG``, ``logging.INFO``).
        fmt: Optional log format string. If None, defaults to
            ``"%(asctime)s [%(name)s] %(levelname)s: %(message)s"``.
    """
    if fmt is None:
        fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

    handler: logging.StreamHandler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(fmt))

    logger: logging.Logger = logging.getLogger("ainos")
    logger.setLevel(level)
    # Avoid adding duplicate handlers
    if not logger.handlers:
        logger.addHandler(handler)


# ---------------------------------------------------------------------------
# Context manager for timing
# ---------------------------------------------------------------------------


class Timer:
    """A context manager that measures elapsed time.

    Usage::

        with Timer() as timer:
            await client.infer(...)
        print(f"Took {timer.elapsed:.2f}s")
    """

    def __init__(self) -> None:
        """Initialise the timer."""
        self._start: float = 0.0
        self._end: float = 0.0

    def __enter__(self) -> "Timer":
        """Start the timer when entering the context."""
        self._start = time.monotonic()
        return self

    def __exit__(
        self,
        exc_type: t.Optional[t.Type[BaseException]],
        exc_val: t.Optional[BaseException],
        exc_tb: t.Optional[object],
    ) -> t.Optional[bool]:
        """Stop the timer when exiting the context."""
        self._end = time.monotonic()
        return None

    @property
    def elapsed(self) -> float:
        """Elapsed time in seconds (read-only)."""
        if self._end > 0:
            return self._end - self._start
        return time.monotonic() - self._start

    @property
    def elapsed_ms(self) -> float:
        """Elapsed time in milliseconds (read-only)."""
        return self.elapsed * 1000.0

    def __repr__(self) -> str:
        """Return a string representation of the timer state."""
        return f"Timer(elapsed={self.elapsed:.3f}s)"


__all__: list[str] = [
    "json_encode",
    "json_decode",
    "generate_request_id",
    "timestamp",
    "monotonic_ns",
    "retry",
    "retry_sync",
    "validate_host",
    "validate_port",
    "truncate",
    "merge_dicts",
    "format_bytes",
    "resolve_host",
    "setup_logging",
    "Timer",
]