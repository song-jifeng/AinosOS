"""
Ainos SDK - Test Fixtures and Configuration
============================================

Provides pytest fixtures for testing the Ainos SDK, including a mock daemon
that simulates the NDJSON TCP protocol.

The mock daemon listens on a random port and responds to requests according
to a configurable handler map.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import sys
import typing as t
from typing import Any, AsyncGenerator

import pytest

# Disable SDK logging during tests
logging.disable(logging.CRITICAL)

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Mock daemon
# ---------------------------------------------------------------------------


class MockDaemonProtocol(asyncio.Protocol):
    """ASyncio protocol that implements a mock Ainos daemon.

    Reads NDJSON messages, dispatches them to registered handlers, and
    sends NDJSON responses back.
    """

    def __init__(self, handlers: t.Dict[str, t.Callable[[dict[str, t.Any]], dict[str, t.Any]]]) -> None:
        """Initialise the protocol.

        Args:
            handlers: A dictionary mapping method names to handler functions.
                Each handler receives the request params and returns a
                response result dict.
        """
        super().__init__()
        self.handlers: dict[str, t.Callable[[dict[str, t.Any]], dict[str, t.Any]]] = handlers
        self._buffer: bytearray = bytearray()
        self._transport: t.Optional[asyncio.Transport] = None

    def connection_made(self, transport: asyncio.Transport) -> None:
        """Handle a new connection."""
        self._transport = transport

    def data_received(self, data: bytes) -> None:
        """Handle incoming data."""
        self._buffer.extend(data)
        self._process_buffer()

    def _process_buffer(self) -> None:
        """Process the buffer, extracting complete NDJSON messages."""
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue

            try:
                message: dict[str, t.Any] = json.loads(line.decode("utf-8"))
                self._handle_message(message)
            except json.JSONDecodeError:
                self._send_error("", -32700, "Parse error")

    def _handle_message(self, message: dict[str, t.Any]) -> None:
        """Route a parsed message to the appropriate handler.

        Args:
            message: The parsed request message.
        """
        msg_type: str = message.get("type", "")
        msg_id: str = message.get("id", "")
        method: str = message.get("method", "")
        params: dict[str, t.Any] = message.get("params", {})
        auth: t.Optional[str] = message.get("auth")

        if msg_type != "request":
            self._send_error(msg_id, -32600, "Invalid request type")

        # Check authentication
        if auth is not None and not self._verify_auth(auth):
            self._send_error(msg_id, -32020, "Authentication failed")
            return

        # Find and call the handler
        handler: t.Optional[t.Callable[[dict[str, t.Any]], dict[str, t.Any]]] = self.handlers.get(method)
        if handler is None:
            self._send_error(msg_id, -32601, f"Method not found: {method}")
            return

        try:
            result: dict[str, t.Any] = handler(params)
            self._send_response(msg_id, result)
        except MockDaemonError as exc:
            self._send_error(msg_id, exc.code, exc.message)
        except Exception as exc:
            self._send_error(msg_id, -32603, f"Internal error: {exc}")

    def _verify_auth(self, auth_header: str) -> bool:
        """Verify an authentication header.

        Args:
            auth_header: The Authorization header value.

        Returns:
            True if the token is valid.
        """
        # Accept "Bearer valid-token" or any token if no auth configured
        if auth_header == "Bearer valid-token":
            return True
        if auth_header == "Bearer invalid-token":
            return False
        # Default: accept any non-empty token
        return bool(auth_header) and auth_header.startswith("Bearer ")

    def _send_response(self, msg_id: str, result: dict[str, t.Any]) -> None:
        """Send a response message.

        Args:
            msg_id: The request ID.
            result: The result data.
        """
        response: dict[str, t.Any] = {
            "type": "response",
            "id": msg_id,
            "result": result,
        }
        self._send_json(response)

    def _send_error(self, msg_id: str, code: int, message: str) -> None:
        """Send an error response.

        Args:
            msg_id: The request ID.
            code: The error code.
            message: The error message.
        """
        response: dict[str, t.Any] = {
            "type": "response",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }
        self._send_json(response)

    def _send_stream_chunk(self, msg_id: str, token: str, final: bool = False) -> None:
        """Send a streaming chunk.

        Args:
            msg_id: The request ID.
            token: The token text.
            final: Whether this is the final chunk.
        """
        chunk: dict[str, t.Any] = {
            "type": "stream",
            "id": msg_id,
            "data": {
                "token": token,
                "final": final,
            },
        }
        if final:
            chunk["data"]["finish_reason"] = "stop"
            chunk["data"]["usage"] = {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            }
        self._send_json(chunk)

    def _send_json(self, data: dict[str, t.Any]) -> None:
        """Send a JSON message over the wire.

        Args:
            data: The data to send.
        """
        if self._transport is None:
            return
        raw: bytes = (json.dumps(data, separators=(",", ":")) + "\n").encode("utf-8")
        self._transport.write(raw)

    def connection_lost(self, exc: t.Optional[Exception]) -> None:
        """Handle connection loss."""
        self._transport = None


class MockDaemonError(Exception):
    """An error that can be raised by a mock handler to return a specific error code."""

    def __init__(self, code: int, message: str) -> None:
        """Initialise the error.

        Args:
            code: The error code.
            message: The error message.
        """
        super().__init__(message)
        self.code: int = code
        self.message: str = message


# ---------------------------------------------------------------------------
# Default mock handlers
# ---------------------------------------------------------------------------


def _health_handler(params: dict[str, t.Any]) -> dict[str, t.Any]:
    """Handle the health method."""
    return {
        "healthy": True,
        "status": "running",
        "version": "0.1.0",
        "uptime_seconds": 3600.0,
        "active_models": 1,
    }


def _status_handler(params: dict[str, t.Any]) -> dict[str, t.Any]:
    """Handle the status method."""
    return {
        "version": "0.1.0",
        "uptime_seconds": 3600.0,
        "active_models": 1,
        "total_models": 2,
        "memory_used_mb": 1024.0,
        "memory_total_mb": 16384.0,
        "gpu_usage_percent": 45.0,
        "gpu_memory_used_mb": 2048.0,
        "gpu_memory_total_mb": 8192.0,
        "cpu_usage_percent": 12.5,
        "active_requests": 2,
        "queued_requests": 0,
        "status": "running",
    }


def _model_list_handler(params: dict[str, t.Any]) -> dict[str, t.Any]:
    """Handle the model_list method."""
    return [
        {
            "id": "model-1",
            "name": "test-model",
            "path": "/models/test.gguf",
            "status": "loaded",
            "backend": "llama.cpp",
            "size_bytes": 4_000_000_000,
            "loaded_at": 1000.0,
            "context_length": 4096,
            "device": "cuda:0",
        },
        {
            "id": "model-2",
            "name": "other-model",
            "path": "/models/other.gguf",
            "status": "unloaded",
            "backend": "transformers",
            "size_bytes": 2_000_000_000,
            "loaded_at": None,
            "context_length": 2048,
            "device": "cpu",
        },
    ]


def _infer_handler(params: dict[str, t.Any]) -> dict[str, t.Any]:
    """Handle the infer method (non-streaming)."""
    return {
        "model": params.get("model", ""),
        "text": "This is a mock inference response from the Ainos daemon.",
        "finish_reason": "stop",
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 8,
            "total_tokens": 18,
        },
        "id": "resp-001",
        "created": 1000.0,
    }


def _infer_stream_handler(params: dict[str, t.Any]) -> dict[str, t.Any]:
    """Handle the infer method (streaming).

    This returns a single chunk for the mock. The test protocol handles
    actual streaming by sending multiple messages.
    """
    return {
        "token": "Hello",
        "final": True,
        "finish_reason": "stop",
    }


def _model_load_handler(params: dict[str, t.Any]) -> dict[str, t.Any]:
    """Handle the model_load method."""
    name: str = params.get("name", "unknown")
    return {
        "id": f"{name}-id",
        "name": name,
        "path": params.get("path", ""),
        "status": "loaded",
        "backend": params.get("backend", "llama.cpp"),
        "size_bytes": 4_000_000_000,
        "loaded_at": 1000.0,
        "context_length": params.get("context_length", 4096),
        "device": params.get("device", "cuda:0"),
    }


def _model_unload_handler(params: dict[str, t.Any]) -> dict[str, t.Any]:
    """Handle the model_unload method."""
    return {"success": True}


def _model_get_handler(params: dict[str, t.Any]) -> dict[str, t.Any]:
    """Handle the model_get method."""
    model_id: str = params.get("model_id", "")
    # Return the first model from the list if found, or error
    models = _model_list_handler({})
    for m in models:
        if m["id"] == model_id:
            return m
    raise MockDaemonError(-32000, f"Model not found: {model_id}")


def _context_store_handler(params: dict[str, t.Any]) -> dict[str, t.Any]:
    """Handle the context_store method."""
    return {"success": True}


def _context_retrieve_handler(params: dict[str, t.Any]) -> dict[str, t.Any]:
    """Handle the context_retrieve method."""
    return {"value": {"stored": "data"}}


# Default handlers for the mock daemon
DEFAULT_HANDLERS: dict[str, t.Callable[[dict[str, t.Any]], dict[str, t.Any]]] = {
    "health": _health_handler,
    "status": _status_handler,
    "model_list": _model_list_handler,
    "model_get": _model_get_handler,
    "infer": _infer_handler,
    "infer_stream": _infer_stream_handler,
    "model_load": _model_load_handler,
    "model_unload": _model_unload_handler,
    "context_store": _context_store_handler,
    "context_retrieve": _context_retrieve_handler,
}


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_handlers() -> dict[str, t.Callable[[dict[str, t.Any]], dict[str, t.Any]]]:
    """Fixture providing default mock handlers.

    Override this fixture to customise handler behaviour for specific tests.

    Returns:
        A dictionary of method name to handler function.
    """
    return dict(DEFAULT_HANDLERS)


@pytest.fixture
async def mock_daemon(
    mock_handlers: dict[str, t.Callable[[dict[str, t.Any]], dict[str, t.Any]]],
) -> AsyncGenerator[tuple[str, int], None]:
    """Fixture that starts a mock daemon server.

    Yields:
        A tuple of (host, port) for the mock daemon.
    """
    loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()

    # Find a free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        host, port = s.getsockname()

    # Create the server
    factory = lambda: MockDaemonProtocol(mock_handlers)  # noqa: E731
    server: asyncio.AbstractServer = await loop.create_server(
        factory,
        host="127.0.0.1",
        port=port,
    )

    async with server:
        yield ("127.0.0.1", port)


@pytest.fixture
async def client(mock_daemon: tuple[str, int]) -> AsyncGenerator[Any, None]:
    """Fixture providing a connected AinosClient.

    Args:
        mock_daemon: The mock daemon fixture.

    Yields:
        A connected AinosClient instance.
    """
    from ainos import AinosClient

    host, port = mock_daemon
    c: AinosClient = AinosClient(
        host=host,
        port=port,
        auth_token="valid-token",
        auto_connect=False,
        connect_timeout=5.0,
        request_timeout=10.0,
        pool_size=2,
    )
    await c.connect()
    yield c
    await c.disconnect()


@pytest.fixture
def event_loop() -> t.Generator[asyncio.AbstractEventLoop, None, None]:
    """Fixture providing the event loop for async tests."""
    loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()