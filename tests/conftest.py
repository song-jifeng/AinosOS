"""AinosOS Test Suite — Shared Fixtures, Mock Daemon, and Test Utilities.

This module provides the shared pytest infrastructure for all AinosOS test
suites. It includes:

- A full mock daemon server (TCP + NDJSON protocol) that mimics the real
  Ainos AI Daemon's IPC behaviour.
- Temporary directory management with synthetic model files.
- Kernel syscall stubs for user-space testing.
- Test configuration via environment variables.
- Assertion helpers and logging capture.
- Time-budget enforcement.

Usage:
    # In any test file under tests/:
    def test_foo(mock_daemon, temp_model_dir, test_vectors):
        client = mock_daemon
        resp = client.infer("Hello")
        assert resp.output
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import queue
import random
import select
import socket
import struct
import sys
import tempfile
import threading
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple, Union

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AI_ERR_SUCCESS = 0
AI_ERR_GENERAL = -1
AI_ERR_INVALID_PARAM = -2
AI_ERR_MODEL_NOT_FOUND = -3
AI_ERR_MODEL_LOAD_FAIL = -4
AI_ERR_OUT_OF_MEMORY = -5
AI_ERR_TASK_QUEUE_FULL = -6
AI_ERR_NOT_SUPPORTED = -7
AI_ERR_PERMISSION = -8
AI_ERR_TIMEOUT = -9
AI_ERR_THERMAL_THROTTLE = -10

VALID_EMBEDDING_DIMS = {128, 256, 512, 768, 1024, 2048, 4096}

DEFAULT_DAEMON_HOST = "127.0.0.1"
DEFAULT_DAEMON_PORT_RANGE = (19000, 20000)
DEFAULT_TEST_TIMEOUT = 30.0
DEFAULT_STRESS_DURATION = 60
DEFAULT_STRESS_CONCURRENCY = 10
DEFAULT_BENCHMARK_ITERATIONS = 50
DEFAULT_BENCHMARK_WARMUP = 5

# IPC message types (mirrors the Rust IpcMessage enum)
IPC_MESSAGE_TYPES = frozenset({
    "Auth", "AuthResponse",
    "Inference", "InferenceResponse", "InferenceStream", "InferenceChunk",
    "ModelLoad", "ModelLoadResponse",
    "ModelUnload", "ModelUnloadResponse",
    "ModelList", "ModelListResponse",
    "ContextStore", "ContextRetrieve",
    "Status", "StatusResponse",
    "RateLimitStatus", "RateLimitStatusResponse",
    "Error",
})

# ---------------------------------------------------------------------------
# Test Configuration
# ---------------------------------------------------------------------------


def get_config() -> dict[str, Any]:
    """Read test configuration from environment variables."""
    return {
        "mode": os.environ.get("AINOS_TEST_MODE", "mock"),
        "daemon_host": os.environ.get("AINOS_DAEMON_HOST", DEFAULT_DAEMON_HOST),
        "daemon_port": int(os.environ.get("AINOS_DAEMON_PORT", "0")),
        "model_dir": os.environ.get("AINOS_MODEL_DIR", ""),
        "stress_duration": int(os.environ.get("AINOS_STRESS_DURATION", str(DEFAULT_STRESS_DURATION))),
        "stress_concurrency": int(os.environ.get("AINOS_STRESS_CONCURRENCY", str(DEFAULT_STRESS_CONCURRENCY))),
        "benchmark_iterations": int(os.environ.get("AINOS_BENCHMARK_ITERATIONS", str(DEFAULT_BENCHMARK_ITERATIONS))),
        "benchmark_warmup": int(os.environ.get("AINOS_BENCHMARK_WARMUP", str(DEFAULT_BENCHMARK_WARMUP))),
        "coverage_threshold": int(os.environ.get("AINOS_COVERAGE_THRESHOLD", "80")),
        "log_level": os.environ.get("AINOS_LOG_LEVEL", "INFO"),
        "timeout": float(os.environ.get("AINOS_TIMEOUT", str(DEFAULT_TEST_TIMEOUT))),
        "seed": os.environ.get("AINOS_SEED", str(int(time.time()))),
    }


# ---------------------------------------------------------------------------
# Mock Daemon Server
# ---------------------------------------------------------------------------


class MockDaemonError(Exception):
    """Base exception for mock daemon errors."""


class MockDaemonAuthError(MockDaemonError):
    """Authentication error from the mock daemon."""


class MockDaemonProtocolError(MockDaemonError):
    """Protocol error from the mock daemon."""


@dataclass
class MockModelInfo:
    """Metadata for a mock model registered with the daemon."""
    id: str
    name: str
    path: str
    size_mb: int = 0
    loaded: bool = False
    architecture: str = "auto"


@dataclass
class MockSession:
    """An authenticated client session."""
    session_token: str
    client_id: str
    created_at: float
    permissions: list[str] = field(default_factory=lambda: ["infer", "status", "model", "context"])
    ttl_seconds: int = 3600

    @property
    def expired(self) -> bool:
        return (time.monotonic() - self.created_at) > self.ttl_seconds


class MockDaemonServer:
    """A lightweight mock Ainos AI Daemon for testing IPC-dependent components.

    The server binds to a random available TCP port, listens for newline-delimited
    JSON (NDJSON) messages, and responds with appropriate JSON responses matching
    the real daemon's IPC protocol.

    Architecture::

        Test Fixture
            |
            +--> MockDaemonServer instance
            |        |
            |        +--> Binds to random available port
            |        +--> Starts background thread
            |        +--> Accepts NDJSON messages over TCP
            |        +--> Routes to handler methods
            |        +--> Returns JSON responses
            |
            +--> MockDaemonClient (returned to tests)
                     |
                     +--> infer(), status(), model_list(), etc.

    Usage::

        server = MockDaemonServer()
        server.start()
        client = server.make_client()
        resp = client.infer("Hello")
        assert "output" in resp
        server.stop()
    """

    def __init__(
        self,
        host: str = DEFAULT_DAEMON_HOST,
        port: int = 0,
        auth_token: Optional[str] = None,
        auth_enabled: bool = False,
        rate_limit_enabled: bool = False,
        response_delay_ms: float = 0.0,
        fail_on_type: Optional[set[str]] = None,
    ) -> None:
        self.host = host
        self.port = port or self._find_free_port()
        self.auth_token = auth_token or "test-token-32-chars-minimum-here!"
        self.auth_enabled = auth_enabled
        self.rate_limit_enabled = rate_limit_enabled
        self.response_delay_ms = response_delay_ms
        self.fail_on_type = fail_on_type or set()

        self._server_socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._lock = threading.Lock()

        # In-memory state
        self.models: dict[str, MockModelInfo] = {}
        self.sessions: dict[str, MockSession] = {}
        self.context_store: dict[str, str] = {}
        self.next_model_id = 1
        self.rate_limit_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.rate_limit_window_start: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.rate_limit_max: dict[str, int] = {
            "inference": 60,
            "model": 30,
            "status": 120,
            "context": 100,
            "admin": 20,
        }
        self.stats: dict[str, Any] = {
            "total_requests": 0,
            "total_inferences": 0,
            "total_errors": 0,
            "start_time": 0.0,
        }
        self._client_count = 0

    def _find_free_port(self) -> int:
        """Find a random available TCP port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the mock daemon in a background thread."""
        if self._running.is_set():
            return

        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.host, self.port))
        self._server_socket.listen(128)
        self._server_socket.settimeout(1.0)

        self.stats["start_time"] = time.monotonic()
        self._running.set()

        self._thread = threading.Thread(target=self._serve_loop, daemon=True, name="MockDaemon")
        self._thread.start()

        # Wait for the server to be ready
        self._wait_ready()

    def stop(self) -> None:
        """Stop the mock daemon and clean up."""
        self._running.clear()
        if self._server_socket:
            try:
                self._server_socket.close()
            except OSError:
                pass
            self._server_socket = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        with self._lock:
            self.models.clear()
            self.sessions.clear()
            self.context_store.clear()
            self.rate_limit_counts.clear()

    def _wait_ready(self, timeout: float = 5.0) -> None:
        """Wait until the server socket is accepting connections."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with socket.create_connection((self.host, self.port), timeout=1.0):
                    return
            except (ConnectionRefusedError, OSError):
                time.sleep(0.05)
        raise RuntimeError(f"Mock daemon did not start on {self.host}:{self.port} within {timeout}s")

    # ------------------------------------------------------------------
    # Server Loop
    # ------------------------------------------------------------------

    def _serve_loop(self) -> None:
        """Accept connections and dispatch to handlers."""
        while self._running.is_set():
            try:
                client_sock, addr = self._server_socket.accept()  # type: ignore[union-attr]
                client_sock.settimeout(30.0)
                client_id = f"{addr[0]}:{addr[1]}"
                t = threading.Thread(
                    target=self._handle_client,
                    args=(client_sock, client_id),
                    daemon=True,
                    name=f"MockDaemon-Client-{client_id}",
                )
                t.start()
            except socket.timeout:
                continue
            except OSError:
                if self._running.is_set():
                    continue
                break

    def _handle_client(self, sock: socket.socket, client_id: str) -> None:
        """Handle a single client connection: read NDJSON, respond."""
        client_state = {
            "authenticated": False,
            "session_token": None,
            "client_id": client_id,
            "permissions": [],
        }
        buf = b""
        try:
            while self._running.is_set():
                try:
                    data = sock.recv(8192)
                except socket.timeout:
                    continue
                except OSError:
                    break

                if not data:
                    break

                buf += data
                # Process complete lines
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    response = self._process_line(line, client_state)
                    if response is not None:
                        try:
                            sock.sendall(response.encode("utf-8") + b"\n")
                        except OSError:
                            return
        finally:
            try:
                sock.close()
            except OSError:
                pass

    def _process_line(self, line: bytes, state: dict) -> Optional[str]:
        """Process a single NDJSON line and return a response string."""
        try:
            msg = json.loads(line.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return json.dumps({"type": "Error", "code": -1, "message": f"Invalid JSON: {e}"})

        msg_type = msg.get("type", "")
        if msg_type not in IPC_MESSAGE_TYPES:
            return json.dumps({"type": "Error", "code": -1, "message": f"Unknown message type: {msg_type}"})

        # Check if this type should fail
        if msg_type in self.fail_on_type:
            return json.dumps({"type": "Error", "code": -1, "message": f"Injected failure for {msg_type}"})

        # Simulate response delay
        if self.response_delay_ms > 0:
            time.sleep(self.response_delay_ms / 1000.0)

        # Authentication gate
        if self.auth_enabled and msg_type not in ("Auth", "Error"):
            if not state["authenticated"]:
                return json.dumps({
                    "type": "Error",
                    "code": 401,
                    "message": "Authentication required. Send an Auth message first.",
                })

        # Rate limit check
        if self.rate_limit_enabled and msg_type not in ("Auth", "Error", "RateLimitStatus"):
            category = self._msg_type_to_category(msg_type)
            if self._check_rate_limit(state["client_id"], category):
                return json.dumps({
                    "type": "Error",
                    "code": 429,
                    "message": f"Rate limit exceeded for {category}",
                })

        # Route to handler
        self.stats["total_requests"] += 1
        handler = self._get_handler(msg_type)
        if handler:
            try:
                return handler(msg, state)
            except Exception as e:
                self.stats["total_errors"] += 1
                return json.dumps({"type": "Error", "code": -1, "message": str(e)})
        else:
            return json.dumps({"type": "Error", "code": -1, "message": f"No handler for {msg_type}"})

    def _msg_type_to_category(self, msg_type: str) -> str:
        if msg_type in ("Inference", "InferenceStream"):
            return "inference"
        elif msg_type in ("ModelLoad", "ModelUnload", "ModelList"):
            return "model"
        elif msg_type in ("Status", "RateLimitStatus"):
            return "status"
        elif msg_type in ("ContextStore", "ContextRetrieve"):
            return "context"
        return "admin"

    def _check_rate_limit(self, client_id: str, category: str) -> bool:
        now = time.monotonic()
        window_start = self.rate_limit_window_start[client_id][category]
        if now - window_start > 1.0:
            self.rate_limit_window_start[client_id][category] = now
            self.rate_limit_counts[client_id][category] = 0

        self.rate_limit_counts[client_id][category] += 1
        max_val = self.rate_limit_max.get(category, 100)
        return self.rate_limit_counts[client_id][category] > max_val

    def _get_handler(self, msg_type: str) -> Optional[Callable]:
        handlers = {
            "Auth": self._handle_auth,
            "Inference": self._handle_inference,
            "InferenceStream": self._handle_inference_stream,
            "ModelLoad": self._handle_model_load,
            "ModelUnload": self._handle_model_unload,
            "ModelList": self._handle_model_list,
            "ContextStore": self._handle_context_store,
            "ContextRetrieve": self._handle_context_retrieve,
            "Status": self._handle_status,
            "RateLimitStatus": self._handle_rate_limit_status,
        }
        return handlers.get(msg_type)

    # ------------------------------------------------------------------
    # Message Handlers
    # ------------------------------------------------------------------

    def _handle_auth(self, msg: dict, state: dict) -> str:
        token = msg.get("token", "")
        if not token:
            return json.dumps({
                "type": "AuthResponse",
                "success": False,
                "message": "No token provided",
                "permissions": [],
                "session_ttl_seconds": 0,
            })

        if self.auth_enabled and token != self.auth_token:
            return json.dumps({
                "type": "AuthResponse",
                "success": False,
                "message": "Authentication failed: invalid token",
                "permissions": [],
                "session_ttl_seconds": 0,
            })

        session_token = f"sess_{uuid.uuid4().hex[:16]}"
        session = MockSession(
            session_token=session_token,
            client_id=state["client_id"],
            created_at=time.monotonic(),
        )
        with self._lock:
            self.sessions[session_token] = session

        state["authenticated"] = True
        state["session_token"] = session_token
        state["permissions"] = session.permissions

        return json.dumps({
            "type": "AuthResponse",
            "success": True,
            "session_token": session_token,
            "message": "Authentication successful",
            "permissions": session.permissions,
            "session_ttl_seconds": session.ttl_seconds,
        })

    def _handle_inference(self, msg: dict, state: dict) -> str:
        self.stats["total_inferences"] += 1
        prompt = msg.get("prompt", "")
        model = msg.get("model", "default")
        temperature = msg.get("temperature")
        max_tokens = msg.get("max_tokens", 64)

        # Simulate inference latency proportional to tokens
        sim_tokens = min(max_tokens, 256)
        time.sleep(sim_tokens * 0.001)

        output = (
            f"[MockDaemon] Processed prompt '{prompt[:50]}{'...' if len(prompt) > 50 else ''}' "
            f"with model '{model}' (temp={temperature or 0.7}, max_tokens={max_tokens})"
        )

        return json.dumps({
            "type": "InferenceResponse",
            "output": output,
            "tokens_generated": sim_tokens,
            "inference_ms": sim_tokens,
            "source": "local",
        })

    def _handle_inference_stream(self, msg: dict, state: dict) -> str:
        # For simplicity, return a single chunk (real streaming would send multiple lines)
        self.stats["total_inferences"] += 1
        prompt = msg.get("prompt", "")
        model = msg.get("model", "default")
        max_tokens = msg.get("max_tokens", 64)

        sim_tokens = min(max_tokens, 32)
        output = (
            f"[MockDaemon-Stream] Processed '{prompt[:30]}' "
            f"with model '{model}' ({sim_tokens} tokens)"
        )

        return json.dumps({
            "type": "InferenceChunk",
            "chunk": output,
            "done": True,
        })

    def _handle_model_load(self, msg: dict, state: dict) -> str:
        path = msg.get("path", "")
        if not path:
            return json.dumps({
                "type": "ModelLoadResponse",
                "model_id": "",
                "status": "error",
                "message": "Model path is empty",
            })

        path_obj = Path(path)
        if not path_obj.exists():
            return json.dumps({
                "type": "ModelLoadResponse",
                "model_id": path,
                "status": "error",
                "message": f"Model file not found: {path}",
            })

        supported_exts = {".gguf", ".ggml", ".onnx", ".bin"}
        if path_obj.suffix.lower() not in supported_exts:
            return json.dumps({
                "type": "ModelLoadResponse",
                "model_id": path,
                "status": "error",
                "message": f"Unsupported model format: {path_obj.suffix}",
            })

        model_id = path_obj.stem.replace(".", "_")
        file_size = path_obj.stat().st_size
        size_mb = file_size // (1024 * 1024)
        arch = "auto"
        if "llama" in path.lower():
            arch = "llama"
        elif "phi" in path.lower():
            arch = "phi3"
        elif "mistral" in path.lower():
            arch = "mistral"

        info = MockModelInfo(
            id=model_id,
            name=path_obj.name,
            path=path,
            size_mb=size_mb,
            loaded=True,
            architecture=arch,
        )
        with self._lock:
            self.models[model_id] = info

        return json.dumps({
            "type": "ModelLoadResponse",
            "model_id": model_id,
            "status": "loaded",
            "message": f"Model '{model_id}' loaded successfully",
            "model_info": {
                "id": model_id,
                "name": path_obj.name,
                "path": path,
                "size_mb": size_mb,
                "loaded": True,
                "architecture": arch,
            },
        })

    def _handle_model_unload(self, msg: dict, state: dict) -> str:
        model_id = msg.get("model_id", "")
        with self._lock:
            if model_id not in self.models:
                return json.dumps({
                    "type": "ModelUnloadResponse",
                    "model_id": model_id,
                    "status": "not_found",
                    "message": f"Model '{model_id}' is not loaded",
                })
            del self.models[model_id]

        return json.dumps({
            "type": "ModelUnloadResponse",
            "model_id": model_id,
            "status": "unloaded",
            "message": f"Model '{model_id}' unloaded successfully",
        })

    def _handle_model_list(self, msg: dict, state: dict) -> str:
        models_list = []
        with self._lock:
            for info in self.models.values():
                models_list.append({
                    "id": info.id,
                    "name": info.name,
                    "path": info.path,
                    "size_mb": info.size_mb,
                    "loaded": info.loaded,
                    "architecture": info.architecture,
                })
        return json.dumps({"type": "ModelListResponse", "models": models_list})

    def _handle_context_store(self, msg: dict, state: dict) -> str:
        key = msg.get("key", "")
        value = msg.get("value", "")
        if not key:
            return json.dumps({"type": "Error", "code": -1, "message": "Key is empty"})
        with self._lock:
            self.context_store[key] = value
        return json.dumps({
            "type": "InferenceResponse",
            "output": f"Context stored: {key}",
            "tokens_generated": 0,
            "inference_ms": 0,
            "source": "local",
        })

    def _handle_context_retrieve(self, msg: dict, state: dict) -> str:
        key = msg.get("key", "")
        with self._lock:
            value = self.context_store.get(key)
        if value is None:
            return json.dumps({"type": "Error", "code": -1, "message": f"Key not found: {key}"})
        return json.dumps({
            "type": "InferenceResponse",
            "output": value,
            "tokens_generated": 0,
            "inference_ms": 0,
            "source": "local",
        })

    def _handle_status(self, msg: dict, state: dict) -> str:
        uptime = time.monotonic() - self.stats["start_time"]
        with self._lock:
            models_loaded = len(self.models)
        return json.dumps({
            "type": "StatusResponse",
            "uptime": int(uptime),
            "models_loaded": models_loaded,
            "total_requests": self.stats["total_requests"],
            "network_available": True,
            "active_sessions": len(self.sessions),
            "rate_limits": [
                {"category": "inference", "limit": 60, "remaining": 50, "reset_seconds": 1},
                {"category": "status", "limit": 120, "remaining": 100, "reset_seconds": 1},
            ],
        })

    def _handle_rate_limit_status(self, msg: dict, state: dict) -> str:
        return json.dumps({
            "type": "RateLimitStatusResponse",
            "limits": [
                {"category": "inference", "limit": 60, "remaining": 50, "reset_seconds": 1},
                {"category": "status", "limit": 120, "remaining": 100, "reset_seconds": 1},
                {"category": "model", "limit": 30, "remaining": 25, "reset_seconds": 1},
                {"category": "context", "limit": 100, "remaining": 90, "reset_seconds": 1},
            ],
        })

    # ------------------------------------------------------------------
    # Client Factory
    # ------------------------------------------------------------------

    def make_client(self) -> MockDaemonClient:
        """Create a MockDaemonClient connected to this server."""
        client = MockDaemonClient(self.host, self.port)
        client.connect()
        return client

    def make_authenticated_client(self, token: Optional[str] = None) -> MockDaemonClient:
        """Create a connected and authenticated client."""
        client = self.make_client()
        client.authenticate(token or self.auth_token)
        return client


# ---------------------------------------------------------------------------
# Mock Daemon Client
# ---------------------------------------------------------------------------


class MockDaemonClient:
    """A lightweight TCP client for the mock daemon.

    Mirrors the public API of the real ``AinosClient`` from the Python SDK.
    """

    def __init__(
        self,
        host: str = DEFAULT_DAEMON_HOST,
        port: int = 9500,
        connect_timeout: float = 5.0,
        read_timeout: float = 30.0,
    ) -> None:
        self._host = host
        self._port = port
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._socket: Optional[socket.socket] = None
        self._authenticated = False
        self._session_token: Optional[str] = None
        self._permissions: list[str] = []

    @property
    def connected(self) -> bool:
        return self._socket is not None

    @property
    def authenticated(self) -> bool:
        return self._authenticated

    def connect(self) -> None:
        if self._socket is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self._connect_timeout)
        sock.connect((self._host, self._port))
        sock.settimeout(self._read_timeout)
        self._socket = sock

    def disconnect(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
            self._authenticated = False
            self._session_token = None
            self._permissions = []

    def authenticate(self, token: str) -> dict[str, Any]:
        payload = json.dumps({"type": "Auth", "token": token}, separators=(",", ":"))
        data = self._send_recv(payload)
        if data.get("type") != "AuthResponse":
            raise MockDaemonProtocolError(f"Unexpected response: {data.get('type')}")
        if not data.get("success", False):
            raise MockDaemonAuthError(data.get("message", "Auth failed"))
        self._authenticated = True
        self._session_token = data.get("session_token")
        self._permissions = data.get("permissions", [])
        return data

    def infer(
        self,
        prompt: str,
        model: str = "default",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> dict[str, Any]:
        payload = {
            "type": "Inference",
            "model": model,
            "prompt": prompt,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if session_id is not None:
            payload["session_id"] = session_id
        data = self._send_recv(json.dumps(payload, separators=(",", ":")))
        if data.get("type") == "Error":
            raise MockDaemonError(data.get("message", "Inference failed"))
        return data

    def infer_stream(self, prompt: str, model: str = "default", **kwargs) -> dict[str, Any]:
        payload = {"type": "InferenceStream", "model": model, "prompt": prompt, **kwargs}
        data = self._send_recv(json.dumps(payload, separators=(",", ":")))
        if data.get("type") == "Error":
            raise MockDaemonError(data.get("message", "Stream failed"))
        return data

    def model_load(self, path: str) -> dict[str, Any]:
        payload = json.dumps({"type": "ModelLoad", "path": path}, separators=(",", ":"))
        return self._send_recv(payload)

    def model_unload(self, model_id: str) -> dict[str, Any]:
        payload = json.dumps({"type": "ModelUnload", "model_id": model_id}, separators=(",", ":"))
        return self._send_recv(payload)

    def model_list(self) -> list[dict[str, Any]]:
        payload = json.dumps({"type": "ModelList"}, separators=(",", ":"))
        data = self._send_recv(payload)
        return data.get("models", [])

    def status(self) -> dict[str, Any]:
        payload = json.dumps({"type": "Status"}, separators=(",", ":"))
        return self._send_recv(payload)

    def context_store(self, key: str, value: str) -> dict[str, Any]:
        payload = json.dumps({"type": "ContextStore", "key": key, "value": value}, separators=(",", ":"))
        return self._send_recv(payload)

    def context_retrieve(self, key: str) -> dict[str, Any]:
        payload = json.dumps({"type": "ContextRetrieve", "key": key}, separators=(",", ":"))
        return self._send_recv(payload)

    def rate_limit_status(self) -> dict[str, Any]:
        payload = json.dumps({"type": "RateLimitStatus"}, separators=(",", ":"))
        return self._send_recv(payload)

    def close(self) -> None:
        self.disconnect()

    def __enter__(self) -> MockDaemonClient:
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        self.disconnect()

    def _send_recv(self, payload: str) -> dict[str, Any]:
        if self._socket is None:
            raise MockDaemonError("Not connected")
        try:
            self._socket.sendall(payload.encode("utf-8") + b"\n")
            return self._read_response()
        except (socket.timeout, OSError) as e:
            self.disconnect()
            raise MockDaemonError(f"Connection error: {e}") from e

    def _read_response(self) -> dict[str, Any]:
        chunks: list[bytes] = []
        while True:
            try:
                char = self._socket.recv(1)  # type: ignore[union-attr]
            except OSError as e:
                raise MockDaemonError(f"Read error: {e}") from e
            if not char:
                raise MockDaemonError("Connection closed by peer")
            if char == b"\n":
                break
            chunks.append(char)
        line = b"".join(chunks).decode("utf-8")
        try:
            return json.loads(line)
        except json.JSONDecodeError as e:
            raise MockDaemonProtocolError(f"Invalid JSON response: {e}") from e


# ---------------------------------------------------------------------------
# Kernel Stubs
# ---------------------------------------------------------------------------


class KernelStub:
    """User-space stub for Ainos kernel AI syscalls (451-457).

    Provides deterministic behaviour suitable for testing runtime and SDK
    components without requiring the actual kernel module. All operations
    are in-memory with configurable error injection.

    Usage::

        stub = KernelStub()
        embedding, err = stub.ai_embedding(np.array([1.0, 2.0]), 128)
        assert err == AI_ERR_SUCCESS
    """

    def __init__(self, seed: int = 42, inject_errors: Optional[dict[str, int]] = None) -> None:
        self.models: dict[int, dict[str, Any]] = {}
        self.contexts: dict[tuple[int, str], dict[str, Any]] = {}
        self.next_model_id = 1
        self.next_entry_id = 1
        self.total_inferences = 0
        self.total_tokens = 0
        self.uptime_ms = 0
        self._rng = random.Random(seed)
        self._inject_errors = inject_errors or {}

    def _should_fail(self, op: str) -> bool:
        """Check if the given operation should be injected with an error."""
        if op in self._inject_errors:
            error_code = self._inject_errors[op]
            if error_code != AI_ERR_SUCCESS:
                return True
        return False

    def _get_error(self, op: str, default: int = AI_ERR_GENERAL) -> int:
        return self._inject_errors.get(op, default)

    # ------------------------------------------------------------------
    # Syscall 451: ai_embedding
    # ------------------------------------------------------------------

    def ai_embedding(
        self, input_data: Any, input_len: int, embedding_dim: int
    ) -> tuple[Optional[list[float]], int]:
        """Compute a deterministic embedding vector.

        Args:
            input_data: Input data (list of floats or array-like).
            input_len: Number of input elements.
            embedding_dim: Output dimension (must be 128, 256, 512, 768,
                           1024, 2048, or 4096).

        Returns:
            Tuple of (embedding_vector, error_code).
        """
        if self._should_fail("embedding"):
            return None, self._get_error("embedding")

        if input_data is None or input_len == 0:
            return None, AI_ERR_INVALID_PARAM
        if embedding_dim not in VALID_EMBEDDING_DIMS:
            return None, AI_ERR_INVALID_PARAM

        # Deterministic embedding based on input hash
        self._rng.seed(hash(str(input_data)) & 0xFFFFFFFF)
        embedding = [self._rng.random() for _ in range(embedding_dim)]
        # Normalize
        magnitude = sum(x * x for x in embedding) ** 0.5
        if magnitude > 0:
            embedding = [x / magnitude for x in embedding]

        self.total_inferences += 1
        self.total_tokens += input_len
        return embedding, AI_ERR_SUCCESS

    # ------------------------------------------------------------------
    # Syscall 452: ai_semantic_search
    # ------------------------------------------------------------------

    def ai_semantic_search(
        self,
        query: list[float],
        database: list[list[float]],
        top_k: int,
    ) -> tuple[Optional[list[tuple[int, float]]], int]:
        """Simulate cosine similarity search.

        Args:
            query: Query vector.
            database: List of database vectors.
            top_k: Number of top results to return.

        Returns:
            Tuple of (list of (index, score) tuples, error_code).
        """
        if self._should_fail("semantic_search"):
            return None, self._get_error("semantic_search")

        if not query or not database or top_k < 1:
            return None, AI_ERR_INVALID_PARAM

        if len(query) != len(database[0]):
            return None, AI_ERR_INVALID_PARAM

        # Compute cosine similarities
        def cosine_sim(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = sum(x * x for x in a) ** 0.5
            norm_b = sum(x * x for x in b) ** 0.5
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot / (norm_a * norm_b)

        scores = [(i, cosine_sim(query, db)) for i, db in enumerate(database)]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k], AI_ERR_SUCCESS

    # ------------------------------------------------------------------
    # Syscall 453: ai_model_load
    # ------------------------------------------------------------------

    def ai_model_load(
        self, name: str, path: str
    ) -> tuple[Optional[int], int]:
        """Register a model as loaded.

        Args:
            name: Model name.
            path: Path to model file.

        Returns:
            Tuple of (model_id, error_code).
        """
        if self._should_fail("model_load"):
            return None, self._get_error("model_load")

        if not name or not path:
            return None, AI_ERR_INVALID_PARAM

        model_id = self.next_model_id
        self.models[model_id] = {
            "name": name,
            "path": path,
            "loaded_at": time.monotonic(),
        }
        self.next_model_id += 1
        return model_id, AI_ERR_SUCCESS

    # ------------------------------------------------------------------
    # Syscall 454: ai_model_unload
    # ------------------------------------------------------------------

    def ai_model_unload(self, model_id: int) -> int:
        """Unload a previously loaded model.

        Args:
            model_id: The model identifier returned by ai_model_load.

        Returns:
            Error code.
        """
        if self._should_fail("model_unload"):
            return self._get_error("model_unload")

        if model_id not in self.models:
            return AI_ERR_MODEL_NOT_FOUND
        del self.models[model_id]
        return AI_ERR_SUCCESS

    # ------------------------------------------------------------------
    # Syscall 455: ai_context_store
    # ------------------------------------------------------------------

    def ai_context_store(
        self, session_id: int, key: str, value: str, ttl_ms: int
    ) -> tuple[Optional[int], int]:
        """Store a value in the context store.

        Args:
            session_id: Session identifier.
            key: Lookup key.
            value: Value to store.
            ttl_ms: Time-to-live in milliseconds.

        Returns:
            Tuple of (entry_id, error_code).
        """
        if self._should_fail("context_store"):
            return None, self._get_error("context_store")

        if not key:
            return None, AI_ERR_INVALID_PARAM

        entry_id = self.next_entry_id
        self.contexts[(session_id, key)] = {
            "value": value,
            "ttl_ms": ttl_ms,
            "entry_id": entry_id,
            "stored_at": time.monotonic(),
        }
        self.next_entry_id += 1
        return entry_id, AI_ERR_SUCCESS

    # ------------------------------------------------------------------
    # Syscall 456: ai_context_retrieve
    # ------------------------------------------------------------------

    def ai_context_retrieve(
        self, session_id: int, key: str, entry_id: int
    ) -> tuple[Optional[str], int]:
        """Retrieve a value from the context store.

        Args:
            session_id: Session identifier.
            key: Lookup key (can be empty if entry_id is provided).
            entry_id: Entry identifier (can be 0 if key is provided).

        Returns:
            Tuple of (value, error_code).
        """
        if self._should_fail("context_retrieve"):
            return None, self._get_error("context_retrieve")

        if not key and entry_id == 0:
            return None, AI_ERR_INVALID_PARAM

        if key:
            entry = self.contexts.get((session_id, key))
        else:
            for (sid, k), e in self.contexts.items():
                if e["entry_id"] == entry_id:
                    entry = e
                    break
            else:
                entry = None

        if entry is None:
            return None, AI_ERR_INVALID_PARAM

        # Check TTL
        if entry["ttl_ms"] > 0:
            elapsed = (time.monotonic() - entry["stored_at"]) * 1000
            if elapsed > entry["ttl_ms"]:
                return None, AI_ERR_INVALID_PARAM

        return entry["value"], AI_ERR_SUCCESS

    # ------------------------------------------------------------------
    # Syscall 457: ai_status
    # ------------------------------------------------------------------

    def ai_status(self) -> tuple[dict[str, Any], int]:
        """Return system status information.

        Returns:
            Tuple of (status_dict, error_code).
        """
        if self._should_fail("status"):
            return {}, self._get_error("status")

        self.uptime_ms += 1000  # Simulate time passing
        return {
            "models_loaded": len(self.models),
            "tasks_pending": 0,
            "tasks_running": 0,
            "total_inferences": self.total_inferences,
            "total_tokens": self.total_tokens,
            "uptime_ms": self.uptime_ms,
            "network_available": 1,
            "accelerator_type": 2,
            "version": "1.0.0-mock",
        }, AI_ERR_SUCCESS

    # ------------------------------------------------------------------
    # Error injection helpers
    # ------------------------------------------------------------------

    def set_error_injection(self, op: str, error_code: int) -> None:
        """Configure a specific operation to return an error."""
        self._inject_errors[op] = error_code

    def clear_error_injection(self, op: Optional[str] = None) -> None:
        """Clear error injection for an operation (or all if None)."""
        if op:
            self._inject_errors.pop(op, None)
        else:
            self._inject_errors.clear()

    def reset(self) -> None:
        """Reset all state to initial values."""
        self.models.clear()
        self.contexts.clear()
        self.next_model_id = 1
        self.next_entry_id = 1
        self.total_inferences = 0
        self.total_tokens = 0
        self.uptime_ms = 0
        self._inject_errors.clear()


# ---------------------------------------------------------------------------
# Test Utilities
# ---------------------------------------------------------------------------


def assert_successful_response(data: dict[str, Any]) -> None:
    """Assert that an IPC response indicates success (not an Error type)."""
    assert data is not None, "Response is None"
    assert data.get("type") != "Error", f"Got error response: {data.get('message', 'unknown')}"


def assert_error_response(data: dict[str, Any], expected_code: Optional[int] = None) -> None:
    """Assert that an IPC response is an error, optionally with a specific code."""
    assert data is not None, "Response is None"
    assert data.get("type") == "Error", f"Expected error, got {data.get('type')}"
    if expected_code is not None:
        assert data.get("code") == expected_code, (
            f"Expected error code {expected_code}, got {data.get('code')}"
        )


def assert_inference_response(data: dict[str, Any]) -> None:
    """Assert that a response is a valid InferenceResponse."""
    assert data.get("type") == "InferenceResponse", f"Expected InferenceResponse, got {data.get('type')}"
    assert "output" in data, "Missing 'output' field"
    assert isinstance(data["output"], str), "'output' must be a string"
    assert "tokens_generated" in data, "Missing 'tokens_generated'"
    assert "inference_ms" in data, "Missing 'inference_ms'"
    assert "source" in data, "Missing 'source'"
    assert data["source"] in ("local", "cloud"), f"Invalid source: {data['source']}"


def assert_model_load_response(data: dict[str, Any], expected_status: str = "loaded") -> None:
    """Assert that a response is a ModelLoadResponse with the expected status."""
    assert data.get("type") == "ModelLoadResponse", f"Expected ModelLoadResponse, got {data.get('type')}"
    assert data.get("status") == expected_status, (
        f"Expected status '{expected_status}', got '{data.get('status')}'"
    )
    assert "model_id" in data, "Missing 'model_id'"
    assert "message" in data, "Missing 'message'"


def assert_model_unload_response(data: dict[str, Any], expected_status: str = "unloaded") -> None:
    """Assert that a response is a ModelUnloadResponse with the expected status."""
    assert data.get("type") == "ModelUnloadResponse", f"Expected ModelUnloadResponse, got {data.get('type')}"
    assert data.get("status") == expected_status, (
        f"Expected status '{expected_status}', got '{data.get('status')}'"
    )
    assert "model_id" in data, "Missing 'model_id'"


def assert_status_response(data: dict[str, Any]) -> None:
    """Assert that a response is a valid StatusResponse."""
    assert data.get("type") == "StatusResponse", f"Expected StatusResponse, got {data.get('type')}"
    assert "uptime" in data, "Missing 'uptime'"
    assert "models_loaded" in data, "Missing 'models_loaded'"
    assert "total_requests" in data, "Missing 'total_requests'"
    assert "network_available" in data, "Missing 'network_available'"


def assert_auth_response(data: dict[str, Any], expected_success: bool = True) -> None:
    """Assert that a response is a valid AuthResponse."""
    assert data.get("type") == "AuthResponse", f"Expected AuthResponse, got {data.get('type')}"
    assert data.get("success") == expected_success, (
        f"Expected success={expected_success}, got {data.get('success')}"
    )
    if expected_success:
        assert "session_token" in data, "Missing 'session_token'"
        assert "permissions" in data, "Missing 'permissions'"
        assert "session_ttl_seconds" in data, "Missing 'session_ttl_seconds'"
    else:
        assert "message" in data, "Missing 'message'"


def assert_valid_message_type(msg_type: str) -> None:
    """Assert that the string is a valid IPC message type."""
    assert msg_type in IPC_MESSAGE_TYPES, f"Unknown message type: {msg_type}"


def assert_valid_embedding(embedding: list[float], expected_dim: int) -> None:
    """Assert that an embedding vector is valid."""
    assert embedding is not None, "Embedding is None"
    assert len(embedding) == expected_dim, (
        f"Expected {expected_dim} dimensions, got {len(embedding)}"
    )
    assert all(isinstance(x, float) for x in embedding), "All elements must be floats"
    # Check for NaN/Inf
    assert all(not (x != x) for x in embedding), "Embedding contains NaN"  # NaN check
    assert all(abs(x) < 1e6 for x in embedding), "Embedding contains Inf or very large values"


def assert_valid_model_id(model_id: Any) -> None:
    """Assert that a model identifier is valid (positive int or non-empty string)."""
    if isinstance(model_id, int):
        assert model_id > 0, f"Model ID must be positive, got {model_id}"
    elif isinstance(model_id, str):
        assert len(model_id) > 0, "Model ID string must not be empty"
    else:
        pytest.fail(f"Model ID must be int or str, got {type(model_id)}")


def random_string(length: int = 16) -> str:
    """Generate a random ASCII string of the given length."""
    return "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(length))


def random_embedding(dim: int = 128, seed: Optional[int] = None) -> list[float]:
    """Generate a random embedding vector, optionally with a fixed seed."""
    rng = random.Random(seed)
    vec = [rng.random() for _ in range(dim)]
    mag = sum(x * x for x in vec) ** 0.5
    return [x / mag for x in vec] if mag > 0 else vec


def create_minimal_gguf(path: str) -> None:
    """Create a minimal valid GGUF file at the given path.

    The file is a stub with a valid GGUF header. It is not a real model,
    but it has the correct magic bytes and structure for the mock daemon
    to accept it.
    """
    # GGUF magic: "GGUF" (0x46554747 little-endian)
    # Version 3, tensor_count=0, metadata_kv_count=0
    with open(path, "wb") as f:
        f.write(struct.pack("<I", 0x46554747))  # magic: "GGUF"
        f.write(struct.pack("<I", 3))            # version
        f.write(struct.pack("<Q", 0))            # tensor_count
        f.write(struct.pack("<Q", 0))            # metadata_kv_count


def create_minimal_onnx(path: str) -> None:
    """Create a minimal valid ONNX protobuf file.

    The file is a stub with a valid protobuf header. It is not a real model,
    but it has the correct structure for the mock daemon to accept it.
    """
    # ONNX protobuf: model with ir_version=8, opset_import=[onnx=18]
    import struct
    # Simplified ONNX protobuf header
    with open(path, "wb") as f:
        # protobuf field 1 (ir_version, varint) = 8
        f.write(b"\x08\x08")
        # protobuf field 2 (opset_import, message)
        # We just write a minimal valid protobuf
        f.write(b"\x12\x00")  # opset_import empty list


def create_corrupted_model(path: str) -> None:
    """Create a corrupted model file for error-path testing."""
    with open(path, "wb") as f:
        f.write(b"\x00\x00\x00\x00corrupted data that is not a valid model file")


# ---------------------------------------------------------------------------
# Pytest Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def mock_daemon_server() -> Generator[MockDaemonServer, None, None]:
    """Session-scoped fixture: start a single mock daemon for the whole session.

    Yields the MockDaemonServer instance. Tests should use ``mock_daemon_client``
    to get a connected client, or call ``server.make_client()``.
    """
    config = get_config()
    server = MockDaemonServer(
        port=config["daemon_port"],
        auth_enabled=True,
    )
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="function")
def mock_daemon(mock_daemon_server: MockDaemonServer) -> Generator[MockDaemonClient, None, None]:
    """Function-scoped fixture: a connected and authenticated client to the mock daemon.

    Each test function gets a fresh client. The client is automatically disconnected
    after the test.
    """
    client = mock_daemon_server.make_authenticated_client()
    yield client
    client.disconnect()


@pytest.fixture(scope="session")
def mock_daemon_unauthenticated(mock_daemon_server: MockDaemonServer) -> MockDaemonClient:
    """Session-scoped fixture: a connected but unauthenticated client."""
    return mock_daemon_server.make_client()


@pytest.fixture(scope="function")
def temp_model_dir() -> Generator[str, None, None]:
    """Create a temporary directory with test model files.

    The directory contains:
    - test_model.gguf (minimal valid GGUF header)
    - test_model.onnx (minimal valid ONNX model)
    - phi-3-mini.gguf (named for architecture detection tests)
    - llama-2-7b.gguf (named for architecture detection tests)
    - corrupted_model.gguf (invalid header for error-path tests)
    - empty_model.gguf (zero-byte file for edge-case tests)
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Valid models
        create_minimal_gguf(os.path.join(tmpdir, "test_model.gguf"))
        create_minimal_onnx(os.path.join(tmpdir, "test_model.onnx"))
        create_minimal_gguf(os.path.join(tmpdir, "phi-3-mini.gguf"))
        create_minimal_gguf(os.path.join(tmpdir, "llama-2-7b.gguf"))
        create_minimal_gguf(os.path.join(tmpdir, "mistral-7b.gguf"))
        # Edge cases
        create_corrupted_model(os.path.join(tmpdir, "corrupted_model.gguf"))
        Path(os.path.join(tmpdir, "empty_model.gguf")).touch()
        yield tmpdir


@pytest.fixture(scope="session")
def test_vectors() -> dict[str, Any]:
    """Fixed deterministic vectors for reproducible tests.

    Returns a dict with:
    - ``query``: (64,) float32 array
    - ``database``: (20, 64) float32 array
    - ``embedding_128``: (128,) float32 reference embedding
    - ``embedding_256``: (256,) float32 reference embedding
    - ``embedding_512``: (512,) float32 reference embedding
    - ``long_prompt``: A long string for context-window tests
    - ``special_chars_prompt``: Prompt with special/unicode characters
    """
    np = pytest.importorskip("numpy")
    rng = np.random.RandomState(42)
    return {
        "query": rng.rand(64).astype(np.float32),
        "database": rng.rand(20, 64).astype(np.float32),
        "embedding_128": rng.rand(128).astype(np.float32),
        "embedding_256": rng.rand(256).astype(np.float32),
        "embedding_512": rng.rand(512).astype(np.float32),
        "long_prompt": "The quick brown fox " * 1000,
        "special_chars_prompt": "Hello! @#$%^&*() 你好 ñoño émoji: 🚀🔥💯",
    }


@pytest.fixture(scope="function")
def mock_kernel() -> Generator[KernelStub, None, None]:
    """Function-scoped fixture: a fresh KernelStub for each test."""
    yield KernelStub()


@pytest.fixture(scope="function")
def capture_logs() -> Generator[StringIO, None, None]:
    """Capture log output for the duration of a test.

    Usage::

        def test_logging(capture_logs):
            logging.getLogger("ainos").info("test message")
            assert "test message" in capture_logs.getvalue()
    """
    logger = logging.getLogger("ainos")
    logger.setLevel(logging.DEBUG)
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(levelname)s:%(name)s:%(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    yield stream

    logger.removeHandler(handler)


@pytest.fixture(scope="function")
def time_budget() -> Generator[float, None, None]:
    """Enforce a per-test time budget. Raises AssertionError if exceeded.

    Default budget: 30 seconds (configurable via ``AINOS_TIMEOUT`` env var).
    """
    budget = float(os.environ.get("AINOS_TIMEOUT", str(DEFAULT_TEST_TIMEOUT)))
    start = time.monotonic()
    yield budget
    elapsed = time.monotonic() - start
    assert elapsed < budget, (
        f"Test exceeded time budget of {budget}s (took {elapsed:.2f}s)"
    )


@pytest.fixture(scope="function")
def deterministic_seed() -> Generator[int, None, None]:
    """Set a deterministic random seed for the test.

    Uses the ``AINOS_SEED`` environment variable, or a fixed seed (42).
    """
    seed = int(os.environ.get("AINOS_SEED", "42"))
    random.seed(seed)
    yield seed


@pytest.fixture(scope="function")
def no_auth_daemon() -> Generator[MockDaemonServer, None, None]:
    """A mock daemon with authentication disabled."""
    server = MockDaemonServer(auth_enabled=False)
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="function")
def rate_limited_daemon() -> Generator[MockDaemonServer, None, None]:
    """A mock daemon with rate limiting enabled."""
    server = MockDaemonServer(auth_enabled=True, rate_limit_enabled=True)
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="function")
def error_prone_daemon() -> Generator[MockDaemonServer, None, None]:
    """A mock daemon that fails on specific message types."""
    server = MockDaemonServer(
        auth_enabled=True,
        fail_on_type={"Inference", "ModelLoad"},
    )
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="function")
def slow_daemon() -> Generator[MockDaemonServer, None, None]:
    """A mock daemon with a simulated response delay."""
    server = MockDaemonServer(auth_enabled=True, response_delay_ms=50.0)
    server.start()
    yield server
    server.stop()


# ---------------------------------------------------------------------------
# Context managers
# ---------------------------------------------------------------------------


@contextmanager
def mock_daemon_context(
    auth_enabled: bool = True,
    rate_limit_enabled: bool = False,
    **kwargs: Any,
) -> Generator[MockDaemonClient, None, None]:
    """Context manager for a temporary mock daemon client.

    Usage::

        with mock_daemon_context() as client:
            resp = client.infer("Hello")
    """
    server = MockDaemonServer(
        auth_enabled=auth_enabled,
        rate_limit_enabled=rate_limit_enabled,
        **kwargs,
    )
    server.start()
    client = server.make_authenticated_client()
    try:
        yield client
    finally:
        client.disconnect()
        server.stop()


@contextmanager
def temp_environment(**env_vars: str) -> Generator[None, None, None]:
    """Temporarily set environment variables within a context.

    Usage::

        with temp_environment(AINOS_LOG_LEVEL="DEBUG"):
            ...
    """
    old_values = {}
    for key, value in env_vars.items():
        old_values[key] = os.environ.get(key)
        os.environ[key] = value
    try:
        yield
    finally:
        for key, old_value in old_values.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


# ---------------------------------------------------------------------------
# pytest configuration hooks
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers and configure the test suite."""
    config.addinivalue_line("markers", "kernel: Kernel module tests (C code)")
    config.addinivalue_line("markers", "runtime: Runtime component tests")
    config.addinivalue_line("markers", "sdk: SDK consistency tests")
    config.addinivalue_line("markers", "integration: End-to-end integration tests")
    config.addinivalue_line("markers", "stress: Stress and load tests")
    config.addinivalue_line("markers", "benchmark: Performance benchmarks")
    config.addinivalue_line("markers", "slow: Tests that take longer than 30 seconds")
    config.addinivalue_line("markers", "smoke: Quick smoke tests for CI pre-commit")
    config.addinivalue_line("markers", "flaky: Tests known to be flaky")


def pytest_report_header(config: pytest.Config) -> list[str]:
    """Add a custom header to the pytest output."""
    cfg = get_config()
    return [
        f"AinosOS Test Suite",
        f"  Mode: {cfg['mode']}",
        f"  Random seed: {cfg['seed']}",
        f"  Timeout: {cfg['timeout']}s",
    ]