"""Ainos AI Daemon — Python SDK Client.

Provides the :class:`AinosClient` class for communicating with the Ainos AI
Daemon over TCP using newline-delimited JSON (NDJSON) — the same protocol
used by the Rust ``ai-daemon`` IPC server.

Usage::

    from ainos import AinosClient

    # With authentication
    client = AinosClient(auth_token="your-token-here")
    client.connect()
    client.authenticate()

    # Sync inference
    resp = client.infer("Hello, Ainos!")
    print(resp.output)

    # Context manager
    with AinosClient(auth_token="token") as c:
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


class AinosAuthError(AinosError):
    """Raised when authentication with the daemon fails."""


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
        auth_token: Bearer token for authentication. If provided, the client
            will automatically authenticate on connect (default ``None``).
        auto_authenticate: Whether to automatically authenticate after
            connecting when ``auth_token`` is provided (default ``True``).
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9500,
        connect_timeout: float = 5.0,
        read_timeout: float = 120.0,
        auto_reconnect: bool = True,
        reconnect_delay: float = 1.0,
        auth_token: Optional[str] = None,
        auto_authenticate: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._auto_reconnect = auto_reconnect
        self._reconnect_delay = reconnect_delay
        self._auth_token = auth_token
        self._auto_authenticate = auto_authenticate

        self._socket: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._session_token: Optional[str] = None
        self._authenticated = False
        self._permissions: list[str] = []
        self._session_ttl: int = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        """``True`` if the socket is currently open."""
        return self._socket is not None

    @property
    def authenticated(self) -> bool:
        """``True`` if the client has been authenticated with the daemon."""
        return self._authenticated

    @property
    def session_token(self) -> Optional[str]:
        """The current session token, if authenticated."""
        return self._session_token

    @property
    def permissions(self) -> list[str]:
        """The permissions granted to the current session."""
        return list(self._permissions)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open a TCP connection to the daemon.

        If ``auth_token`` and ``auto_authenticate`` are set, this will
        also attempt authentication after connecting.

        Raises:
            AinosConnectionError: If the connection cannot be established.
            AinosAuthError: If auto-authentication fails.
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

        # Auto-authenticate if token is provided
        if self._auth_token and self._auto_authenticate:
            self.authenticate(self._auth_token)

    def disconnect(self) -> None:
        """Close the TCP connection if open."""
        with self._lock:
            if self._socket is not None:
                try:
                    self._socket.close()
                except OSError:
                    pass
                self._socket = None
                self._session_token = None
                self._authenticated = False
                self._permissions = []
                logger.info("Disconnected from Ainos daemon")

    def authenticate(self, token: Optional[str] = None) -> dict[str, Any]:
        """Authenticate with the daemon using a bearer token.

        Args:
            token: The bearer token. If not provided, uses the token
                from the constructor.

        Returns:
            The authentication response dict with keys:
            - ``success``: bool
            - ``session_token``: str (if successful)
            - ``message``: str
            - ``permissions``: list[str]
            - ``session_ttl_seconds``: int

        Raises:
            AinosAuthError: If authentication fails.
            AinosConnectionError: If the connection is lost.
        """
        token = token or self._auth_token
        if not token:
            raise AinosAuthError("No authentication token provided")

        payload = _build_request("Auth", token=token)
        data = self._send_recv(payload)

        if data.get("type") != "AuthResponse":
            raise AinosAuthError(
                f"Unexpected response type: {data.get('type')}"
            )

        if not data.get("success", False):
            raise AinosAuthError(
                data.get("message", "Authentication failed")
            )

        self._session_token = data.get("session_token")
        self._authenticated = True
        self._permissions = data.get("permissions", [])
        self._session_ttl = data.get("session_ttl_seconds", 0)

        logger.info(
            "Authenticated successfully, session token: %s...",
            self._session_token[:8] if self._session_token else "None",
        )

        return data

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

    def model_load(self, path: str) -> dict[str, Any]:
        """Load a model into memory by its file path.

        Args:
            path: Absolute path to the model file on disk.

        Returns:
            A dict with keys: ``model_id``, ``status``, ``message``,
            and optionally ``model_info``.

        Raises:
            AinosError: If the daemon returns an error.
        """
        payload = _build_request("ModelLoad", path=path)
        data = self._send_recv(payload)

        if data.get("type") == "Error":
            raise AinosError(data.get("message", "Model load failed"))

        return {
            "model_id": data.get("model_id", ""),
            "status": data.get("status", "error"),
            "message": data.get("message", ""),
            "model_info": data.get("model_info"),
        }

    def model_unload(self, model_id: str) -> dict[str, Any]:
        """Unload a model from memory.

        Args:
            model_id: The model identifier (e.g. ``"phi_3_mini_4k..."``).

        Returns:
            A dict with keys: ``model_id``, ``status``, ``message``.

        Raises:
            AinosError: If the daemon returns an error.
        """
        payload = _build_request("ModelUnload", model_id=model_id)
        data = self._send_recv(payload)

        if data.get("type") == "Error":
            raise AinosError(data.get("message", "Model unload failed"))

        return {
            "model_id": data.get("model_id", ""),
            "status": data.get("status", "error"),
            "message": data.get("message", ""),
        }

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
            return None
        return data.get("output", "")

    def rate_limit_status(self) -> dict[str, Any]:
        """Query the current rate limit status for this session.

        Returns:
            A dict with rate limit information for each category.

        Raises:
            AinosError: If the query fails.
        """
        payload = _build_request("RateLimitStatus")
        data = self._send_recv(payload)

        if data.get("type") == "Error":
            raise AinosError(data.get("message", "Rate limit query failed"))
        return data

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
                self._session_token = None
                self._authenticated = False