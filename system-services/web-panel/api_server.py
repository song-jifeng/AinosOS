#!/usr/bin/env python3
"""
AinosOS Web Dashboard API Server
=================================
HTTP API server for the AinosOS inference platform web dashboard.

Features:
- System status monitoring (CPU, memory, temperature, uptime)
- Model management (list, load, unload)
- Inference with streaming support (SSE + WebSocket)
- Context management (CRUD)
- Log viewer with filtering
- Plugin management (enable/disable)
- Server-Sent Events for real-time updates
- WebSocket for streaming inference
- Token-based authentication
- CORS support
- Static file serving for dashboard assets

Requirements: Python 3.12+, aiohttp, psutil
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import secrets
import signal
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Try optional dependencies
# ---------------------------------------------------------------------------
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    import aiohttp
    from aiohttp import web
    from aiohttp.web import (
        Application, Response, Request, StreamResponse,
        WebSocketResponse, FileResponse, json_response,
    )
    from aiohttp.web_exceptions import (
        HTTPBadRequest, HTTPUnauthorized, HTTPNotFound,
        HTTPInternalServerError, HTTPMethodNotAllowed,
    )
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ServerConfig:
    """Server configuration."""
    host: str = "0.0.0.0"
    port: int = 8080
    api_token: str = ""
    cors_origins: str = "*"
    log_level: str = "INFO"
    static_dir: str = ""
    max_log_entries: int = 1000
    sse_heartbeat: int = 30  # seconds
    ws_max_size: int = 1024 * 1024  # 1MB
    enable_auth: bool = False

    @classmethod
    def from_env(cls) -> "ServerConfig":
        return cls(
            host=os.environ.get("AINOS_HOST", "0.0.0.0"),
            port=int(os.environ.get("AINOS_PORT", "8080")),
            api_token=os.environ.get("AINOS_API_TOKEN", ""),
            cors_origins=os.environ.get("AINOS_CORS_ORIGINS", "*"),
            log_level=os.environ.get("AINOS_LOG_LEVEL", "INFO"),
            static_dir=os.environ.get("AINOS_STATIC_DIR", ""),
            max_log_entries=int(os.environ.get("AINOS_MAX_LOG_ENTRIES", "1000")),
            enable_auth=bool(os.environ.get("AINOS_ENABLE_AUTH", "")),
        )


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


@dataclass
class LogEntry:
    """A single log entry."""
    timestamp: float
    level: str
    message: str
    source: str = "system"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "message": self.message,
            "source": self.source,
        }


@dataclass
class ModelInfo:
    """Information about a loaded model."""
    id: str
    name: str = ""
    provider: str = "unknown"
    status: str = "unloaded"
    vram: int = 0
    context_length: int = 0
    requests: int = 0
    uptime: float = 0.0
    loaded_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name or self.id,
            "provider": self.provider,
            "status": self.status,
            "vram": self.vram,
            "context_length": self.context_length,
            "requests": self.requests,
            "uptime": self.uptime,
            "loaded_at": self.loaded_at,
            "metadata": self.metadata,
        }


@dataclass
class ContextEntry:
    """A context entry from conversation history."""
    id: str
    content: str
    tokens: int = 0
    created_at: float = 0.0
    expires_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "preview": self.content[:200] if self.content else "",
            "content": self.content,
            "tokens": self.tokens,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "metadata": self.metadata,
        }


@dataclass
class PluginInfo:
    """Information about a plugin."""
    id: str
    name: str = ""
    version: str = "0.0.0"
    description: str = ""
    author: str = ""
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name or self.id,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "enabled": self.enabled,
            "metadata": self.metadata,
        }


@dataclass
class SystemStatus:
    """System status snapshot."""
    status: str = "online"
    cpu: float = 0.0
    memory: float = 0.0
    memory_used: int = 0
    memory_total: int = 0
    temperature: float = 0.0
    uptime: float = 0.0
    active_models: List[Dict[str, Any]] = field(default_factory=list)
    system: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "cpu": round(self.cpu, 1),
            "memory": round(self.memory, 1),
            "memory_used": self.memory_used,
            "memory_total": self.memory_total,
            "temperature": round(self.temperature, 1),
            "uptime": self.uptime,
            "active_models": self.active_models,
            "system": self.system,
            "timestamp": self.timestamp or time.time(),
        }


# ---------------------------------------------------------------------------
# Inference Engine (Simulated / Placeholder)
# ---------------------------------------------------------------------------

class InferenceEngine:
    """
    Inference engine for AinosOS.
    In production, this would interface with actual model backends
    (e.g., llama.cpp, vLLM, TensorRT-LLM, OpenAI API, etc.).
    """

    def __init__(self, config: ServerConfig):
        self.config = config
        self.models: Dict[str, ModelInfo] = {}
        self._load_dummy_models()

    def _load_dummy_models(self):
        """Load default model entries for demonstration."""
        default_models = [
            ModelInfo(
                id="ainos-llama-3.1-8b",
                name="Ainos Llama 3.1 8B",
                provider="llama.cpp",
                status="loaded",
                vram=8 * 1024 * 1024 * 1024,  # 8GB
                context_length=8192,
                loaded_at=time.time(),
            ),
            ModelInfo(
                id="ainos-qwen-2.5-7b",
                name="Ainos Qwen 2.5 7B",
                provider="vLLM",
                status="loaded",
                vram=7 * 1024 * 1024 * 1024,
                context_length=32768,
                loaded_at=time.time(),
            ),
            ModelInfo(
                id="ainos-mistral-7b",
                name="Ainos Mistral 7B",
                provider="llama.cpp",
                status="unloaded",
                vram=0,
                context_length=8192,
            ),
            ModelInfo(
                id="ainos-gpt-4o-mini",
                name="Ainos GPT-4o Mini (Proxy)",
                provider="openai",
                status="loaded",
                vram=0,
                context_length=128000,
                loaded_at=time.time(),
            ),
        ]
        for model in default_models:
            self.models[model.id] = model

    def list_models(self) -> List[ModelInfo]:
        return list(self.models.values())

    def get_model(self, model_id: str) -> Optional[ModelInfo]:
        return self.models.get(model_id)

    def load_model(self, model_id: str) -> ModelInfo:
        if model_id not in self.models:
            self.models[model_id] = ModelInfo(
                id=model_id,
                name=model_id,
                status="loaded",
                loaded_at=time.time(),
            )
        model = self.models[model_id]
        model.status = "loaded"
        model.loaded_at = time.time()
        return model

    def unload_model(self, model_id: str) -> bool:
        model = self.models.get(model_id)
        if model:
            model.status = "unloaded"
            model.loaded_at = None
            return True
        return False

    async def infer(
        self,
        model_id: str,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        stream: bool = False,
    ) -> Any:
        """
        Run inference on a model.
        Returns full response or async generator for streaming.
        """
        model = self.models.get(model_id)
        if not model:
            raise ValueError(f"Model '{model_id}' not found")
        if model.status != "loaded":
            raise ValueError(f"Model '{model_id}' is not loaded")

        model.requests += 1

        if stream:
            return self._stream_inference(prompt, max_tokens, temperature)
        else:
            return await self._direct_inference(prompt, max_tokens, temperature)

    async def _direct_inference(
        self, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        """Simulate a complete inference response."""
        await asyncio.sleep(0.5)  # Simulate processing time
        return self._generate_response(prompt, max_tokens)

    async def _stream_inference(
        self, prompt: str, max_tokens: int, temperature: float
    ) -> AsyncGenerator:
        """Simulate streaming inference tokens."""
        response = self._generate_response(prompt, max_tokens)
        words = response.split(" ")
        for i, word in enumerate(words):
            token = word + (" " if i < len(words) - 1 else "")
            yield {"token": token, "index": i}
            await asyncio.sleep(0.02 + (temperature * 0.01))  # Simulate generation speed
        yield {"done": True}

    def _generate_response(self, prompt: str, max_tokens: int) -> str:
        """Generate a simulated response."""
        # In production, this would call the actual model.
        # For now, return a template response.
        prompt_len = len(prompt.split())
        response_len = min(max_tokens, max(50, prompt_len * 2))

        responses = {
            "hello": "Hello! I'm AinosOS, your AI inference platform. I can help you with a wide range of tasks including text generation, analysis, coding, and more. How can I assist you today?",
            "help": "I'm here to help! I can assist with:\n\n1. **Text Generation** - Generate articles, stories, emails\n2. **Code** - Write, review, and debug code\n3. **Analysis** - Analyze data and documents\n4. **Q&A** - Answer questions on various topics\n5. **Translation** - Translate between languages\n\nJust tell me what you need!",
        }

        for key, resp in responses.items():
            if key in prompt.lower():
                return resp

        # Generic response
        return (
            f"Thank you for your prompt. I have processed your request and generated a response "
            f"based on the input: '{prompt[:100]}{'...' if len(prompt) > 100 else ''}'. "
            f"This is a simulated response from the AinosOS inference engine. "
            f"In production, this would be the output from the actual AI model. "
            f"The response demonstrates the inference pipeline working correctly. "
            f"Max tokens configured: {max_tokens}. "
            f"Temperature setting: {temperature}. "
            f"Response generated at: {datetime.now(timezone.utc).isoformat()}."
        )


# ---------------------------------------------------------------------------
# System Monitor
# ---------------------------------------------------------------------------

class SystemMonitor:
    """Collects system metrics."""

    def __init__(self):
        self.start_time = time.time()
        self._prev_cpu = 0.0

    def get_status(self, engine: InferenceEngine) -> SystemStatus:
        """Gather current system status."""
        status = SystemStatus()
        status.timestamp = time.time()

        # CPU
        if HAS_PSUTIL:
            status.cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            status.memory = mem.percent
            status.memory_used = mem.used
            status.memory_total = mem.total

            # Temperature (platform-specific)
            try:
                if hasattr(psutil, "sensors_temperatures"):
                    temps = psutil.sensors_temperatures()
                    for name, entries in temps.items():
                        if entries:
                            status.temperature = entries[0].current
                            break
            except Exception:
                pass

            # System info
            boot_time = psutil.boot_time()
            status.uptime = time.time() - boot_time

            status.system = {
                "hostname": platform.node(),
                "os": f"{platform.system()} {platform.release()}",
                "kernel": platform.version(),
                "cpu_cores": psutil.cpu_count(logical=True),
                "total_memory": mem.total,
                "disk_usage": self._get_disk_usage(),
                "python_version": sys.version.split()[0],
                "ainos_version": "1.0.0",
            }
        else:
            # Fallback without psutil
            status.cpu = 25.0
            status.memory = 30.0
            status.memory_used = 4 * 1024 * 1024 * 1024
            status.memory_total = 16 * 1024 * 1024 * 1024
            status.temperature = 45.0
            status.uptime = time.time() - self.start_time
            status.system = {
                "hostname": platform.node(),
                "os": f"{platform.system()} {platform.release()}",
                "kernel": platform.version(),
                "cpu_cores": os.cpu_count() or 4,
                "total_memory": 16 * 1024 * 1024 * 1024,
                "disk_usage": 45,
                "python_version": sys.version.split()[0],
                "ainos_version": "1.0.0",
            }

        # Active models
        status.active_models = []
        for model in engine.list_models():
            if model.status == "loaded":
                model_dict = model.to_dict()
                if model.loaded_at:
                    model_dict["uptime"] = time.time() - model.loaded_at
                status.active_models.append(model_dict)

        # Determine overall status
        if status.cpu > 90 or status.memory > 90 or status.temperature > 80:
            status.status = "degraded"
        if status.cpu > 98 or status.memory > 98:
            status.status = "error"

        return status

    def _get_disk_usage(self) -> float:
        """Get disk usage percentage."""
        if HAS_PSUTIL:
            try:
                return psutil.disk_usage("/").percent
            except Exception:
                pass
        return 45.0


# ---------------------------------------------------------------------------
# Log Manager
# ---------------------------------------------------------------------------

class LogManager:
    """Manages log entries with circular buffer."""

    def __init__(self, max_entries: int = 1000):
        self.max_entries = max_entries
        self.entries: deque = deque(maxlen=max_entries)

    def add(self, level: str, message: str, source: str = "system"):
        entry = LogEntry(
            timestamp=time.time(),
            level=level,
            message=message,
            source=source,
        )
        self.entries.append(entry)

    def debug(self, message: str, source: str = "system"):
        self.add("debug", message, source)

    def info(self, message: str, source: str = "system"):
        self.add("info", message, source)

    def warn(self, message: str, source: str = "system"):
        self.add("warn", message, source)

    def error(self, message: str, source: str = "system"):
        self.add("error", message, source)

    def get_logs(
        self,
        level: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get filtered logs."""
        filtered = list(self.entries)

        if level and level != "all":
            filtered = [e for e in filtered if e.level == level]

        if search:
            search_lower = search.lower()
            filtered = [
                e for e in filtered
                if search_lower in e.message.lower()
            ]

        total = len(filtered)
        filtered = filtered[offset:offset + limit]

        return [e.to_dict() for e in filtered], total


# ---------------------------------------------------------------------------
# Context Manager
# ---------------------------------------------------------------------------

class ContextManager:
    """Manages conversation context entries."""

    def __init__(self):
        self.entries: Dict[str, ContextEntry] = {}
        self._ttl = 3600  # 1 hour default TTL

    def add(self, content: str, tokens: int = 0, ttl: Optional[float] = None) -> ContextEntry:
        entry = ContextEntry(
            id=uuid.uuid4().hex[:12],
            content=content,
            tokens=tokens or len(content.split()),
            created_at=time.time(),
            expires_at=(time.time() + (ttl or self._ttl)) if ttl or self._ttl else None,
        )
        self.entries[entry.id] = entry
        self._cleanup()
        return entry

    def get(self, entry_id: str) -> Optional[ContextEntry]:
        entry = self.entries.get(entry_id)
        if entry:
            self._check_expiry(entry)
        return entry if entry and not self._is_expired(entry) else None

    def delete(self, entry_id: str) -> bool:
        return self.entries.pop(entry_id, None) is not None

    def clear(self):
        self.entries.clear()

    def list(self) -> List[Dict[str, Any]]:
        self._cleanup()
        return [e.to_dict() for e in self.entries.values()]

    def count(self) -> int:
        self._cleanup()
        return len(self.entries)

    def _cleanup(self):
        now = time.time()
        expired = [eid for eid, e in self.entries.items() if self._is_expired(e)]
        for eid in expired:
            del self.entries[eid]

    def _is_expired(self, entry: ContextEntry) -> bool:
        if entry.expires_at is None:
            return False
        return time.time() > entry.expires_at

    def _check_expiry(self, entry: ContextEntry):
        if self._is_expired(entry):
            self.entries.pop(entry.id, None)


# ---------------------------------------------------------------------------
# Plugin Manager
# ---------------------------------------------------------------------------

class PluginManager:
    """Manages system plugins."""

    def __init__(self):
        self.plugins: Dict[str, PluginInfo] = {}
        self._load_default_plugins()

    def _load_default_plugins(self):
        defaults = [
            PluginInfo(
                id="auth-basic",
                name="Basic Authentication",
                version="1.0.0",
                description="Provides token-based authentication for API access",
                author="AinosOS Team",
                enabled=True,
            ),
            PluginInfo(
                id="telemetry",
                name="Telemetry Collector",
                version="1.0.0",
                description="Collects anonymous usage statistics to improve the platform",
                author="AinosOS Team",
                enabled=True,
            ),
            PluginInfo(
                id="model-cache",
                name="Model Cache",
                version="1.0.0",
                description="Caches model responses for faster repeated inference",
                author="AinosOS Team",
                enabled=True,
            ),
            PluginInfo(
                id="rate-limiter",
                name="Rate Limiter",
                version="1.0.0",
                description="Rate limits API requests to prevent abuse",
                author="AinosOS Team",
                enabled=False,
            ),
            PluginInfo(
                id="audit-log",
                name="Audit Logger",
                version="1.0.0",
                description="Logs all API requests for security auditing",
                author="AinosOS Team",
                enabled=False,
            ),
            PluginInfo(
                id="webhook",
                name="Webhook Notifier",
                version="1.0.0",
                description="Sends webhook notifications on system events",
                author="AinosOS Team",
                enabled=False,
            ),
        ]
        for plugin in defaults:
            self.plugins[plugin.id] = plugin

    def list_plugins(self) -> List[PluginInfo]:
        return list(self.plugins.values())

    def get_plugin(self, plugin_id: str) -> Optional[PluginInfo]:
        return self.plugins.get(plugin_id)

    def toggle(self, plugin_id: str, enabled: bool) -> Optional[PluginInfo]:
        plugin = self.plugins.get(plugin_id)
        if plugin:
            plugin.enabled = enabled
        return plugin


# ---------------------------------------------------------------------------
# SSE Manager
# ---------------------------------------------------------------------------

class SSEManager:
    """Manages Server-Sent Events connections."""

    def __init__(self):
        self.clients: Set[web.StreamResponse] = set()
        self._lock = asyncio.Lock()

    async def add(self, response: web.StreamResponse):
        async with self._lock:
            self.clients.add(response)

    async def remove(self, response: web.StreamResponse):
        async with self._lock:
            self.clients.discard(response)

    async def broadcast(self, event: str, data: Any):
        async with self._lock:
            if not self.clients:
                return
            message = f"event: {event}\ndata: {json.dumps(data)}\n\n"
            dead = set()
            for client in self.clients:
                try:
                    await client.write(message.encode("utf-8"))
                except (ConnectionResetError, ConnectionAbortedError, Exception):
                    dead.add(client)
            self.clients -= dead

    @property
    def client_count(self) -> int:
        return len(self.clients)


# ---------------------------------------------------------------------------
# WebSocket Manager
# ---------------------------------------------------------------------------

class WSManager:
    """Manages WebSocket connections for streaming inference."""

    def __init__(self):
        self.connections: Set[WebSocketResponse] = set()

    async def add(self, ws: WebSocketResponse):
        self.connections.add(ws)

    async def remove(self, ws: WebSocketResponse):
        self.connections.discard(ws)

    async def broadcast(self, data: Any):
        message = json.dumps(data)
        dead = set()
        for ws in self.connections:
            try:
                await ws.send_str(message)
            except Exception:
                dead.add(ws)
        self.connections -= dead


# ---------------------------------------------------------------------------
# API Server
# ---------------------------------------------------------------------------

class AinosAPIServer:
    """
    Main API server for AinosOS web dashboard.
    Handles all HTTP, SSE, and WebSocket endpoints.
    """

    def __init__(self, config: ServerConfig):
        self.config = config
        self.engine = InferenceEngine(config)
        self.monitor = SystemMonitor()
        self.logger = LogManager(max_entries=config.max_log_entries)
        self.context = ContextManager()
        self.plugins = PluginManager()
        self.sse = SSEManager()
        self.ws = WSManager()
        self._app: Optional[Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

        # Setup logging
        self._setup_logging()

    def _setup_logging(self):
        """Configure Python logging."""
        logging.basicConfig(
            level=getattr(logging, self.config.log_level.upper(), logging.INFO),
            format="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self._log = logging.getLogger("ainos-api")

    def _check_auth(self, request: Request) -> bool:
        """Check authentication token."""
        if not self.config.enable_auth or not self.config.api_token:
            return True
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:] == self.config.api_token
        return False

    def _auth_middleware(self, request: Request) -> Optional[Response]:
        """Authentication middleware handler."""
        if not self._check_auth(request):
            return json_response(
                {"error": "Unauthorized", "detail": "Invalid or missing API token"},
                status=401,
            )
        return None

    # ------------------------------------------------------------------
    # Route Handlers
    # ------------------------------------------------------------------

    async def handle_status(self, request: Request) -> Response:
        """GET /api/status - System status."""
        auth = self._auth_middleware(request)
        if auth:
            return auth

        status = self.monitor.get_status(self.engine)
        return json_response(status.to_dict())

    async def handle_models(self, request: Request) -> Response:
        """GET /api/models - List models."""
        auth = self._auth_middleware(request)
        if auth:
            return auth

        models = [m.to_dict() for m in self.engine.list_models()]
        return json_response({"models": models})

    async def handle_model_load(self, request: Request) -> Response:
        """POST /api/models/load - Load a model."""
        auth = self._auth_middleware(request)
        if auth:
            return auth

        try:
            body = await request.json()
        except json.JSONDecodeError:
            raise HTTPBadRequest(text="Invalid JSON body")

        model_id = body.get("model_id", "").strip()
        if not model_id:
            raise HTTPBadRequest(text="model_id is required")

        try:
            model = self.engine.load_model(model_id)
            self.logger.info(f"Model loaded: {model_id}", "api")
            # Broadcast model event
            asyncio.ensure_future(
                self.sse.broadcast("model", {"event": "loaded", "model_id": model_id})
            )
            return json_response(model.to_dict(), status=201)
        except ValueError as e:
            raise HTTPBadRequest(text=str(e))
        except Exception as e:
            self.logger.error(f"Failed to load model {model_id}: {e}", "api")
            raise HTTPInternalServerError(text=str(e))

    async def handle_model_unload(self, request: Request) -> Response:
        """POST /api/models/unload - Unload a model."""
        auth = self._auth_middleware(request)
        if auth:
            return auth

        try:
            body = await request.json()
        except json.JSONDecodeError:
            raise HTTPBadRequest(text="Invalid JSON body")

        model_id = body.get("model_id", "").strip()
        if not model_id:
            raise HTTPBadRequest(text="model_id is required")

        if self.engine.unload_model(model_id):
            self.logger.info(f"Model unloaded: {model_id}", "api")
            asyncio.ensure_future(
                self.sse.broadcast("model", {"event": "unloaded", "model_id": model_id})
            )
            return json_response({"status": "ok", "model_id": model_id})
        else:
            raise HTTPNotFound(text=f"Model '{model_id}' not found")

    async def handle_inference(self, request: Request) -> Response:
        """POST /api/inference - Run inference."""
        auth = self._auth_middleware(request)
        if auth:
            return auth

        try:
            body = await request.json()
        except json.JSONDecodeError:
            raise HTTPBadRequest(text="Invalid JSON body")

        model_id = body.get("model", "").strip()
        prompt = body.get("prompt", "").strip()
        max_tokens = int(body.get("max_tokens", 1024))
        temperature = float(body.get("temperature", 0.7))
        stream = bool(body.get("stream", False))

        if not model_id:
            raise HTTPBadRequest(text="model is required")
        if not prompt:
            raise HTTPBadRequest(text="prompt is required")

        if stream:
            # Streaming response via SSE
            return await self._handle_streaming_inference(
                request, model_id, prompt, max_tokens, temperature
            )

        # Direct response
        try:
            response = await self.engine.infer(
                model_id, prompt, max_tokens, temperature, stream=False
            )
            # Store context
            self.context.add(prompt, tokens=len(prompt.split()), ttl=3600)
            self.context.add(response, tokens=len(response.split()), ttl=3600)
            self.logger.info(
                f"Inference completed: model={model_id}, tokens={len(response.split())}", "api"
            )
            return json_response({
                "model": model_id,
                "text": response,
                "tokens": len(response.split()),
                "finish_reason": "stop",
            })
        except ValueError as e:
            raise HTTPBadRequest(text=str(e))
        except Exception as e:
            self.logger.error(f"Inference error: {e}", "api")
            raise HTTPInternalServerError(text=str(e))

    async def _handle_streaming_inference(
        self,
        request: Request,
        model_id: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> StreamResponse:
        """Handle streaming inference via SSE."""
        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(request)

        try:
            async for token_data in self.engine.infer(
                model_id, prompt, max_tokens, temperature, stream=True
            ):
                if token_data.get("done"):
                    await response.write(b"data: [DONE]\n\n")
                    break
                message = f"data: {json.dumps(token_data)}\n\n"
                await response.write(message.encode("utf-8"))
                await response.drain()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            error_msg = f"data: {json.dumps({'error': str(e)})}\n\n"
            await response.write(error_msg.encode("utf-8"))
        finally:
            await response.write_eof()

        return response

    async def handle_ws_inference(self, request: Request) -> WebSocketResponse:
        """WebSocket /ws/inference - Streaming inference via WebSocket."""
        ws = WebSocketResponse(max_msg_size=self.config.ws_max_size)
        await ws.prepare(request)
        await self.ws.add(ws)

        self.logger.info("WebSocket client connected", "ws")

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        await ws.send_json({"error": "Invalid JSON"})
                        continue

                    model_id = data.get("model", "").strip()
                    prompt = data.get("prompt", "").strip()
                    max_tokens = int(data.get("max_tokens", 1024))
                    temperature = float(data.get("temperature", 0.7))

                    if not model_id or not prompt:
                        await ws.send_json({"error": "model and prompt are required"})
                        continue

                    try:
                        async for token_data in self.engine.infer(
                            model_id, prompt, max_tokens, temperature, stream=True
                        ):
                            await ws.send_json(token_data)
                            if token_data.get("done"):
                                break
                    except ValueError as e:
                        await ws.send_json({"error": str(e)})
                    except Exception as e:
                        self.logger.error(f"WS inference error: {e}", "ws")
                        await ws.send_json({"error": "Internal server error"})

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    self.logger.error(f"WS error: {ws.exception()}", "ws")

        except asyncio.CancelledError:
            pass
        finally:
            await self.ws.remove(ws)
            self.logger.info("WebSocket client disconnected", "ws")

        return ws

    async def handle_context_list(self, request: Request) -> Response:
        """GET /api/context - List context entries."""
        auth = self._auth_middleware(request)
        if auth:
            return auth

        return json_response({"contexts": self.context.list()})

    async def handle_context_create(self, request: Request) -> Response:
        """POST /api/context - Store context entry."""
        auth = self._auth_middleware(request)
        if auth:
            return auth

        try:
            body = await request.json()
        except json.JSONDecodeError:
            raise HTTPBadRequest(text="Invalid JSON body")

        content = body.get("content", "").strip()
        if not content:
            raise HTTPBadRequest(text="content is required")

        tokens = int(body.get("tokens", 0))
        ttl = body.get("ttl")

        entry = self.context.add(content, tokens=tokens, ttl=ttl)
        self.logger.debug(f"Context created: {entry.id}", "api")
        return json_response(entry.to_dict(), status=201)

    async def handle_context_delete(self, request: Request) -> Response:
        """DELETE /api/context - Clear all context."""
        auth = self._auth_middleware(request)
        if auth:
            return auth

        self.context.clear()
        self.logger.info("All context cleared", "api")
        return json_response({"status": "ok", "message": "All context cleared"})

    async def handle_context_delete_one(self, request: Request) -> Response:
        """DELETE /api/context/{id} - Delete a specific context entry."""
        auth = self._auth_middleware(request)
        if auth:
            return auth

        context_id = request.match_info.get("id", "")
        if self.context.delete(context_id):
            self.logger.debug(f"Context deleted: {context_id}", "api")
            return json_response({"status": "ok", "deleted": context_id})
        else:
            raise HTTPNotFound(text=f"Context '{context_id}' not found")

    async def handle_logs(self, request: Request) -> Response:
        """GET /api/logs - Get logs with filtering."""
        auth = self._auth_middleware(request)
        if auth:
            return auth

        level = request.query.get("level", "all")
        search = request.query.get("search", "")
        limit = min(int(request.query.get("limit", "100")), 1000)
        offset = int(request.query.get("offset", "0"))

        logs, total = self.logger.get_logs(
            level=level if level != "all" else None,
            search=search if search else None,
            limit=limit,
            offset=offset,
        )

        return json_response({
            "logs": logs,
            "total": total,
            "limit": limit,
            "offset": offset,
        })

    async def handle_plugins(self, request: Request) -> Response:
        """GET /api/plugins - List plugins."""
        auth = self._auth_middleware(request)
        if auth:
            return auth

        return json_response({
            "plugins": [p.to_dict() for p in self.plugins.list_plugins()]
        })

    async def handle_plugin_toggle(self, request: Request) -> Response:
        """POST /api/plugins/{id}/toggle - Enable/disable plugin."""
        auth = self._auth_middleware(request)
        if auth:
            return auth

        plugin_id = request.match_info.get("id", "")

        try:
            body = await request.json()
        except json.JSONDecodeError:
            raise HTTPBadRequest(text="Invalid JSON body")

        enabled = bool(body.get("enabled", True))

        plugin = self.plugins.toggle(plugin_id, enabled)
        if not plugin:
            raise HTTPNotFound(text=f"Plugin '{plugin_id}' not found")

        status = "enabled" if enabled else "disabled"
        self.logger.info(f"Plugin {status}: {plugin_id}", "api")
        return json_response(plugin.to_dict())

    async def handle_events(self, request: Request) -> StreamResponse:
        """GET /api/events - SSE endpoint for real-time updates."""
        auth = self._auth_middleware(request)
        if auth:
            return auth

        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(request)
        await self.sse.add(response)

        self.logger.info("SSE client connected", "sse")

        try:
            # Send initial status
            status = self.monitor.get_status(self.engine)
            initial = f"event: status\ndata: {json.dumps(status.to_dict())}\n\n"
            await response.write(initial.encode("utf-8"))

            # Keep connection alive
            while True:
                await asyncio.sleep(self.config.sse_heartbeat)
                try:
                    # Send heartbeat
                    status = self.monitor.get_status(self.engine)
                    heartbeat = f"event: status\ndata: {json.dumps(status.to_dict())}\n\n"
                    await response.write(heartbeat.encode("utf-8"))
                except (ConnectionResetError, ConnectionAbortedError):
                    break
        except asyncio.CancelledError:
            pass
        finally:
            await self.sse.remove(response)
            self.logger.info("SSE client disconnected", "sse")

        return response

    async def handle_static(self, request: Request) -> FileResponse:
        """Serve static files for the dashboard."""
        static_dir = self.config.static_dir
        if not static_dir:
            static_dir = os.path.dirname(os.path.abspath(__file__))

        filename = request.match_info.get("filename", "dashboard.html")
        filepath = os.path.join(static_dir, filename)

        # Security: prevent directory traversal
        real_path = os.path.realpath(filepath)
        real_static = os.path.realpath(static_dir)
        if not real_path.startswith(real_static):
            raise HTTPNotFound(text="File not found")

        if not os.path.isfile(filepath):
            # Fallback to dashboard.html for SPA-like navigation
            filepath = os.path.join(static_dir, "dashboard.html")
            if not os.path.isfile(filepath):
                raise HTTPNotFound(text="File not found")

        return FileResponse(filepath)

    async def handle_root(self, request: Request) -> FileResponse:
        """GET / - Serve dashboard.html."""
        static_dir = self.config.static_dir
        if not static_dir:
            static_dir = os.path.dirname(os.path.abspath(__file__))

        filepath = os.path.join(static_dir, "dashboard.html")
        if os.path.isfile(filepath):
            return FileResponse(filepath)
        else:
            return json_response({
                "service": "AinosOS API Server",
                "version": "1.0.0",
                "endpoints": {
                    "status": "GET /api/status",
                    "models": "GET /api/models",
                    "inference": "POST /api/inference",
                    "context": "GET/POST /api/context",
                    "logs": "GET /api/logs",
                    "plugins": "GET /api/plugins",
                    "events": "GET /api/events (SSE)",
                    "ws_inference": "WS /ws/inference",
                },
            })

    # ------------------------------------------------------------------
    # CORS Middleware
    # ------------------------------------------------------------------

    @web.middleware
    async def cors_middleware(self, request: Request, handler: Callable) -> Response:
        """Add CORS headers to all responses."""
        if request.method == "OPTIONS":
            # Preflight request
            response = Response(status=204)
        else:
            try:
                response = await handler(request)
            except HTTPBadRequest as e:
                response = json_response({"error": "Bad Request", "detail": e.text}, status=400)
            except HTTPUnauthorized as e:
                response = json_response({"error": "Unauthorized", "detail": e.text}, status=401)
            except HTTPNotFound as e:
                response = json_response({"error": "Not Found", "detail": e.text}, status=404)
            except HTTPInternalServerError as e:
                response = json_response({"error": "Internal Server Error", "detail": e.text}, status=500)
            except Exception as e:
                self.logger.error(f"Unhandled error: {e}", "api")
                response = json_response({"error": "Internal Server Error"}, status=500)

        origin = request.headers.get("Origin", "*")
        if self.config.cors_origins == "*":
            response.headers["Access-Control-Allow-Origin"] = "*"
        else:
            allowed = [o.strip() for o in self.config.cors_origins.split(",")]
            if origin in allowed:
                response.headers["Access-Control-Allow-Origin"] = origin

        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Max-Age"] = "3600"

        return response

    # ------------------------------------------------------------------
    # Logging Middleware
    # ------------------------------------------------------------------

    @web.middleware
    async def logging_middleware(self, request: Request, handler: Callable) -> Response:
        """Log all API requests."""
        start = time.time()
        try:
            response = await handler(request)
            duration = (time.time() - start) * 1000
            self.logger.debug(
                f"{request.method} {request.path} -> {response.status} ({duration:.0f}ms)", "api"
            )
            return response
        except Exception as e:
            duration = (time.time() - start) * 1000
            self.logger.error(
                f"{request.method} {request.path} -> ERROR ({duration:.0f}ms): {e}", "api"
            )
            raise

    # ------------------------------------------------------------------
    # Application Setup
    # ------------------------------------------------------------------

    def build_app(self) -> Application:
        """Build the aiohttp application."""
        app = Application(middlewares=[self.cors_middleware, self.logging_middleware])

        # API routes
        app.router.add_get("/", self.handle_root)
        app.router.add_get("/api/status", self.handle_status)
        app.router.add_get("/api/models", self.handle_models)
        app.router.add_post("/api/models/load", self.handle_model_load)
        app.router.add_post("/api/models/unload", self.handle_model_unload)
        app.router.add_post("/api/inference", self.handle_inference)
        app.router.add_get("/api/context", self.handle_context_list)
        app.router.add_post("/api/context", self.handle_context_create)
        app.router.add_delete("/api/context", self.handle_context_delete)
        app.router.add_delete("/api/context/{id}", self.handle_context_delete_one)
        app.router.add_get("/api/logs", self.handle_logs)
        app.router.add_get("/api/plugins", self.handle_plugins)
        app.router.add_post("/api/plugins/{id}/toggle", self.handle_plugin_toggle)
        app.router.add_get("/api/events", self.handle_events)
        app.router.add_get("/ws/inference", self.handle_ws_inference)

        # Static files
        static_dir = self.config.static_dir
        if not static_dir:
            static_dir = os.path.dirname(os.path.abspath(__file__))
        app.router.add_get("/{filename:.*}", self.handle_static)

        self._app = app
        return app

    async def start(self):
        """Start the server."""
        app = self.build_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()

        site = web.TCPSite(self._runner, self.config.host, self.config.port)
        await site.start()

        self._log.info(
            f"AinosOS API Server started on http://{self.config.host}:{self.config.port}"
        )
        self._log.info(f"Dashboard: http://localhost:{self.config.port}/dashboard.html")
        self._log.info(f"API docs: http://localhost:{self.config.port}/")
        self._log.info(f"Auth enabled: {self.config.enable_auth}")
        self._log.info(f"CORS origins: {self.config.cors_origins}")

        # Log startup
        self.logger.info("Server started", "system")

        # Keep running until signal
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self):
        """Stop the server gracefully."""
        self._log.info("Shutting down server...")
        self.logger.info("Server shutting down", "system")

        if self._runner:
            await self._runner.cleanup()

        self._log.info("Server stopped")


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def print_banner():
    """Print startup banner."""
    banner = r"""
    ╔══════════════════════════════════════════╗
    ║           AinosOS API Server             ║
    ║      Inference Platform v1.0.0           ║
    ╚══════════════════════════════════════════╝
    """
    print(banner)


def main():
    """Main entry point."""
    print_banner()

    config = ServerConfig.from_env()
    server = AinosAPIServer(config)

    if not HAS_AIOHTTP:
        print("ERROR: aiohttp is required. Install with: pip install aiohttp")
        print("Optional: pip install psutil (for system monitoring)")
        sys.exit(1)

    if not HAS_PSUTIL:
        print("WARNING: psutil not installed. System monitoring will use simulated data.")
        print("  Install: pip install psutil")

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("\nShutdown requested...")
    finally:
        print("Server stopped.")


if __name__ == "__main__":
    main()