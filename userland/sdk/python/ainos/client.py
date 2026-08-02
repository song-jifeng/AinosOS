"""Ainos AI Daemon — Python SDK Client.

Provides the :class:`AinosClient` class for communicating with the Ainos AI
Daemon over TCP using newline-delimited JSON (NDJSON) — the same protocol
used by the Rust ``ai-daemon`` IPC server.

Usage::

    from ainos import AinosClient

    client = AinosClient()
    client.connect()

    # Sync inference
    resp = client.infer("Hello, Ainos!")
    print(resp.output)

    # Context manager
    with AinosClient() as c:
        status = c.status()
        print(status)

    client.disconnect()
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from typing import Any, Optional

from .models import (
    InferenceResponse,
    ModelInfo,
    SystemStatus,
    _build_request,
    _parse_inference_response,
    _parse_model_list_response,
    _parse_response,
    _parse_status_response,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class AinosError(Exception):
    """Base exception for all Ainos SDK errors."""


class AinosConnectionError(AinosError):
    """Raised when the SDK cannot establish or maintain a connection."""


class AinosInferenceError(AinosError):
    """Raised when an inference request fails."""


class AinosTimeoutError(AinosError):
    """Raised when an operation exceeds the configured timeout."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class AinosClient:
    """Synchronous TCP client for the Ainos AI Daemon.

    Parameters:
        host: Daemon hostname or IP address (default ``"127.0.0.1"``).
        port: Daemon TCP port (default ``9500``).
        connect_timeout: Connection timeout in seconds (default ``5``).
        read_timeout: Read (socket) timeout in seconds (default ``120``).
        auto_reconnect: Whether to attempt a single reconnect on failure
            (default ``True``).
        reconnect_delay: Seconds to wait before reconnecting (default ``1``).
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9500,
        connect_timeout: float = 5.0,
        read_timeout: float = 120.0,
        auto_reconnect: bool = True,
        reconnect_delay: float = 1.0,
    ) -> None:
        self._host = host
        self._port = port
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._auto_reconnect = auto_reconnect
        self._reconnect_delay = reconnect_delay

        self._socket: Optional[socket.socket] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open a TCP connection to the daemon.

        Raises:
            AinosConnectionError: If the connection cannot be established.
        """
        with self._lock:
            if self._socket is not None:
                return  # already connected

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self._connect_timeout)
            try:
                sock.connect((self._host, self._port))
            except (socket.timeout, ConnectionRefusedError, OSError) as exc:
                sock.close()
                raise AinosConnectionError(
                    f"Cannot connect to {self._host}:{self._port} — {exc}"
                ) from exc

            sock.settimeout(self._read_timeout)
            self._socket = sock
            logger.info(
                "Connected to Ainos daemon at %s:%s", self._host, self._port
            )

    def disconnect(self) -> None:
        """Close the TCP connection if open."""
        with self._lock:
            if self._socket is not None:
                try:
                    self._socket.close()
                except OSError:
                    pass
                self._socket = None
                logger.info("Disconnected from Ainos daemon")

    @property
    def connected(self) -> bool:
        """``True`` if the socket is currently open."""
        return self._socket is not None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> AinosClient:
        self.connect()
        return self

    def __exit__(self, *exc_args: Any) -> None:
        self.disconnect()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def infer(
        self,
        prompt: str,
        model: str = "default",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> InferenceResponse:
        """Send an inference request to the daemon.

        Args:
            prompt: Input text for the model.
            model: Model identifier (default ``"default"``).
            temperature: Sampling temperature (0.0–2.0).
            max_tokens: Maximum number of tokens to generate.
            session_id: Optional session identifier for context tracking.

        Returns:
            An :class:`InferenceResponse` with the generated output.

        Raises:
            AinosConnectionError: If the connection is lost.
            AinosInferenceError: If the daemon returns an error.
            AinosTimeoutError: If the operation times out.
        """
        payload = _build_request(
            "Inference",
            model=model,
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            session_id=session_id,
        )
        data = self._send_recv(payload)

        if data.get("type") == "Error":
            raise AinosInferenceError(
                data.get("message", "Unknown inference error")
            )
        if data.get("type") != "InferenceResponse":
            raise AinosInferenceError(
                f"Unexpected response type: {data.get('type')}"
            )

        return _parse_inference_response(data)

    def status(self) -> SystemStatus:
        """Query the daemon's health and statistics.

        Returns:
            A :class:`SystemStatus` instance.
        """
        payload = _build_request("Status")
        data = self._send_recv(payload)

        if data.get("type") == "Error":
            raise AinosError(data.get("message", "Status query failed"))
        return _parse_status_response(data)

    def model_list(self) -> list[ModelInfo]:
        """List all registered models.

        Returns:
            A list of :class:`ModelInfo` objects.
        """
        payload = _build_request("ModelList")
        data = self._send_recv(payload)

        if data.get("type") == "Error":
            raise AinosError(data.get("message", "Model list failed"))
        if data.get("type") != "ModelListResponse":
            raise AinosError(
                f"Unexpected response type: {data.get('type')}"
            )
        return _parse_model_list_response(data)

    def model_load(self, path: str) -> None:
        """Load a model into memory by its file path.

        Args:
            path: Absolute path to the model file on disk.

        Raises:
            AinosError: If the daemon returns an error.
        """
        payload = _build_request("ModelLoad", path=path)
        data = self._send_recv(payload)

        if data.get("type") == "Error":
            raise AinosError(data.get("message", "Model load failed"))

    def model_unload(self, model_id: str) -> None:
        """Unload a model from memory.

        Args:
            model_id: The model identifier (e.g. ``"phi_3_mini_4k..."``).

        Raises:
            AinosError: If the daemon returns an error.
        """
        payload = _build_request("ModelUnload", model_id=model_id)
        data = self._send_recv(payload)

        if data.get("type") == "Error":
            raise AinosError(data.get("message", "Model unload failed"))

    def context_store(self, key: str, value: str) -> str:
        """Persist a key-value pair in the daemon's context store.

        Args:
            key: The lookup key.
            value: The value to store.

        Returns:
            A confirmation message from the daemon.
        """
        payload = _build_request("ContextStore", key=key, value=value)
        data = self._send_recv(payload)

        if data.get("type") == "Error":
            raise AinosError(data.get("message", "Context store failed"))
        return data.get("output", "")

    def context_retrieve(self, key: str) -> Optional[str]:
        """Retrieve a value by key from the daemon's context store.

        Args:
            key: The lookup key.

        Returns:
            The stored value, or ``None`` if the key was not found.
        """
        payload = _build_request("ContextRetrieve", key=key)
        data = self._send_recv(payload)

        if data.get("type") == "Error":
            # Key-not-found is a normal case — return None
            return None
        return data.get("output", "")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> socket.socket:
        """Return the current socket, attempting a single reconnect if needed.

        Raises:
            AinosConnectionError: If no connection is available.
        """
        if self._socket is not None:
            return self._socket

        if self._auto_reconnect:
            logger.info("Attempting reconnect...")
            time.sleep(self._reconnect_delay)
            self.connect()
            assert self._socket is not None  # connect() raises on failure
            return self._socket

        raise AinosConnectionError("Not connected to daemon")

    def _send_recv(self, payload: str) -> dict[str, Any]:
        """Send a JSON-line request and read the JSON-line response.

        Raises:
            AinosConnectionError: On socket-level errors.
            AinosTimeoutError: If the socket read times out.
        """
        sock = self._ensure_connected()

        try:
            with self._lock:
                sock.sendall(payload.encode("utf-8") + b"\n")
                response = self._read_line(sock)
        except (socket.timeout, TimeoutError) as exc:
            self._handle_socket_error()
            raise AinosTimeoutError(
                f"Read timed out after {self._read_timeout}s"
            ) from exc
        except (BrokenPipeError, ConnectionResetError, OSError) as exc:
            self._handle_socket_error()
            raise AinosConnectionError(
                f"Connection lost: {exc}"
            ) from exc

        return _parse_response(response)

    def _read_line(self, sock: socket.socket) -> str:
        """Read one newline-terminated line from the socket."""
        chunks: list[bytes] = []
        while True:
            char = sock.recv(1)
            if not char:
                raise ConnectionResetError("Connection closed by peer")
            if char == b"\n":
                break
            chunks.append(char)
        return b"".join(chunks).decode("utf-8")

    def _handle_socket_error(self) -> None:
        """Mark the socket as closed so reconnect logic kicks in."""
        with self._lock:
            if self._socket is not None:
                try:
                    self._socket.close()
                except OSError:
                    pass
                self._socket = None