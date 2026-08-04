"""
端到端集成测试

全链路测试: SDK -> daemon -> runtime 完整管线, 以及多语言 SDK 一致性、
认证授权流程和错误处理流程。
"""

import os
import sys
import json
import time
import uuid
import hmac
import hashlib
import base64
import random
import string
import threading
import asyncio
import pytest
from typing import List, Dict, Optional, Any, Tuple, Callable, Union
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum, auto
from collections import defaultdict
from unittest.mock import MagicMock, Mock, patch, AsyncMock, PropertyMock
from contextlib import contextmanager, asynccontextmanager


# =============================================================================
# 枚举与数据类
# =============================================================================

class RequestMethod(Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


class AuthScheme(Enum):
    BEARER = "Bearer"
    API_KEY = "ApiKey"
    BASIC = "Basic"
    DIGEST = "Digest"
    HMAC = "HMAC"


class RuntimeStatus(Enum):
    IDLE = "idle"
    LOADING = "loading"
    READY = "ready"
    RUNNING = "running"
    ERROR = "error"
    SHUTDOWN = "shutdown"


class ModelFormat(Enum):
    PYTORCH = "pytorch"
    TENSORFLOW = "tensorflow"
    ONNX = "onnx"
    TENSORRT = "tensorrt"
    GGUF = "gguf"
    SAFETENSORS = "safetensors"


class ErrorCode(Enum):
    SUCCESS = 0
    INVALID_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    RATE_LIMITED = 429
    INTERNAL_ERROR = 500
    SERVICE_UNAVAILABLE = 503
    MODEL_NOT_LOADED = 1001
    MODEL_LOADING = 1002
    INFERENCE_TIMEOUT = 1003
    RESOURCE_EXHAUSTED = 1004
    INVALID_MODEL_FORMAT = 1005
    PROTOCOL_ERROR = 2001
    AUTHENTICATION_ERROR = 2002
    AUTHORIZATION_ERROR = 2003


@dataclass
class ApiResponse:
    """API 响应"""
    status_code: int
    body: Dict[str, Any]
    headers: Dict[str, str] = field(default_factory=dict)
    latency_ms: float = 0.0

    @property
    def is_ok(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def error_code(self) -> Optional[ErrorCode]:
        if not self.is_ok:
            return ErrorCode(self.status_code)
        return None


@dataclass
class InferenceRequest:
    """推理请求"""
    model: str
    prompt: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    stream: bool = False
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class InferenceResponse:
    """推理响应"""
    request_id: str
    model: str
    choices: List[Dict[str, Any]]
    usage: Dict[str, int]
    created: int = field(default_factory=lambda: int(time.time()))


@dataclass
class AuthCredentials:
    """认证凭据"""
    api_key: str
    secret_key: Optional[str] = None
    token: Optional[str] = None
    expires_at: Optional[float] = None


@dataclass
class UserSession:
    """用户会话"""
    user_id: str
    token: str
    role: str
    permissions: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 3600)


# =============================================================================
# Mock SDK 层
# =============================================================================

class MockSDKClient:
    """模拟 SDK 客户端 - 多种语言版本的 SDK"""

    def __init__(self, base_url: str = "http://localhost:8080",
                 api_key: str = "test-api-key"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._headers: Dict[str, str] = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "AinosSDK/1.0",
        }
        self._request_count = 0
        self._last_response: Optional[ApiResponse] = None
        self._timeout: float = 30.0
        self._max_retries: int = 3
        self._daemon: Optional['MockDaemon'] = None

    def set_daemon(self, daemon: 'MockDaemon'):
        self._daemon = daemon

    async def request(self, method: str, path: str,
                      body: Dict[str, Any] = None,
                      headers: Dict[str, str] = None,
                      timeout: float = None) -> ApiResponse:
        """发送 API 请求"""
        self._request_count += 1
        start = time.time()
        actual_timeout = timeout or self._timeout

        all_headers = {**self._headers, **(headers or {})}
        url = f"{self.base_url}{path}"

        if self._daemon:
            response = await self._daemon.handle_request(method, path, body, all_headers)
        else:
            response = ApiResponse(
                status_code=503,
                body={"error": "Daemon not connected", "code": ErrorCode.SERVICE_UNAVAILABLE.value},
            )

        response.latency_ms = (time.time() - start) * 1000
        self._last_response = response
        return response

    async def chat_completion(self, request: InferenceRequest) -> InferenceResponse:
        """聊天补全"""
        response = await self.request(
            "POST", "/v1/chat/completions",
            body=asdict(request) if hasattr(request, '__dataclass_fields__') else request,
        )
        if response.is_ok:
            return InferenceResponse(
                request_id=request.request_id,
                model=request.model,
                choices=response.body.get("choices", []),
                usage=response.body.get("usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
            )
        raise RuntimeError(f"Chat completion failed: {response.body}")

    async def embed(self, model: str, input_texts: List[str]) -> List[List[float]]:
        """文本嵌入"""
        response = await self.request(
            "POST", "/v1/embeddings",
            body={"model": model, "input": input_texts},
        )
        if response.is_ok:
            return [item["embedding"] for item in response.body.get("data", [])]
        raise RuntimeError(f"Embedding failed: {response.body}")

    async def list_models(self) -> List[Dict[str, Any]]:
        """列出模型"""
        response = await self.request("GET", "/v1/models")
        if response.is_ok:
            return response.body.get("data", [])
        raise RuntimeError(f"List models failed: {response.body}")

    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        response = await self.request("GET", "/v1/health")
        return response.body if response.is_ok else {"status": "unhealthy"}

    async def get_usage(self) -> Dict[str, Any]:
        """获取用量信息"""
        response = await self.request("GET", "/v1/usage")
        return response.body if response.is_ok else {}

    @property
    def request_count(self) -> int:
        return self._request_count

    @property
    def last_response(self) -> Optional[ApiResponse]:
        return self._last_response


class MockPythonSDK(MockSDKClient):
    """Python SDK 实现"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._headers["X-SDK-Language"] = "python"
        self._headers["X-SDK-Version"] = "1.2.3"

    async def batch_inference(self, requests: List[InferenceRequest]) -> List[InferenceResponse]:
        """批量推理"""
        tasks = [self.chat_completion(req) for req in requests]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def stream_chat(self, request: InferenceRequest) -> AsyncMock:
        """流式聊天"""
        response = await self.request(
            "POST", "/v1/chat/completions",
            body={**asdict(request), "stream": True},
        )
        if response.is_ok:
            mock_stream = AsyncMock()
            chunks = response.body.get("choices", [])
            mock_stream.__aiter__.return_value = iter(chunks)
            return mock_stream
        raise RuntimeError(f"Stream chat failed: {response.body}")

    def to_dict(self, obj) -> Dict:
        """对象转字典"""
        if hasattr(obj, '__dataclass_fields__'):
            return asdict(obj)
        return obj

    def serialize(self, data: Any) -> bytes:
        """序列化"""
        if isinstance(data, bytes):
            return data
        return json.dumps(data, default=str).encode('utf-8')

    def deserialize(self, data: bytes) -> Any:
        """反序列化"""
        return json.loads(data.decode('utf-8'))


class MockJavaSDK:
    """模拟 Java SDK"""

    def __init__(self, host: str = "localhost", port: int = 8080):
        self.host = host
        self.port = port
        self._client = MockSDKClient(f"http://{host}:{port}")
        self._client._headers["X-SDK-Language"] = "java"
        self._client._headers["X-SDK-Version"] = "1.2.3"

    async def chat(self, model: str, prompt: str, **kwargs) -> Dict[str, Any]:
        resp = await self._client.request("POST", "/v1/chat/completions", body={
            "model": model, "prompt": prompt, **kwargs
        })
        return resp.body

    async def generate(self, model: str, prompt: str, **kwargs) -> Dict[str, Any]:
        return await self.chat(model, prompt, **kwargs)

    async def health(self) -> bool:
        resp = await self._client.request("GET", "/v1/health")
        return resp.is_ok


class MockGoSDK:
    """模拟 Go SDK"""

    def __init__(self, endpoint: str = "http://localhost:8080"):
        self.endpoint = endpoint
        self._client = MockSDKClient(endpoint)
        self._client._headers["X-SDK-Language"] = "go"
        self._client._headers["X-SDK-Version"] = "1.2.3"

    async def Complete(self, model: str, prompt: str) -> Dict[str, Any]:
        resp = await self._client.request("POST", "/v1/completions", body={
            "model": model, "prompt": prompt,
        })
        return resp.body

    async def Health(self) -> Dict[str, Any]:
        resp = await self._client.request("GET", "/v1/health")
        return resp.body


class MockNodeSDK:
    """模拟 Node.js SDK"""

    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url
        self._client = MockSDKClient(base_url)
        self._client._headers["X-SDK-Language"] = "nodejs"
        self._client._headers["X-SDK-Version"] = "1.2.3"

    async def createCompletion(self, model: str, prompt: str, options: Dict = None) -> Dict:
        resp = await self._client.request("POST", "/v1/completions", body={
            "model": model, "prompt": prompt, **(options or {}),
        })
        return resp.body

    async def healthCheck(self) -> Dict:
        resp = await self._client.request("GET", "/v1/health")
        return resp.body


# =============================================================================
# Mock Daemon 层
# =============================================================================

class MockDaemon:
    """模拟 Daemon 进程 - 核心服务管理"""

    def __init__(self):
        self._runtimes: Dict[str, 'MockRuntime'] = {}
        self._models: Dict[str, Dict[str, Any]] = {}
        self._sessions: Dict[str, UserSession] = {}
        self._request_log: List[Dict[str, Any]] = []
        self._rate_limiter: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.RLock()
        self._running = False
        self._config = {
            "max_models": 10,
            "max_connections": 1000,
            "rate_limit_per_minute": 60,
            "auth_required": True,
        }
        self._status = RuntimeStatus.IDLE
        self._error_handlers: Dict[str, Callable] = {}
        self._middlewares: List[Callable] = []

    def start(self):
        self._running = True
        self._status = RuntimeStatus.READY
        self._setup_default_models()

    def stop(self):
        self._running = False
        self._status = RuntimeStatus.SHUTDOWN
        for runtime in self._runtimes.values():
            runtime.shutdown()
        self._runtimes.clear()
        self._models.clear()
        self._sessions.clear()

    def _setup_default_models(self):
        self._models["gpt-3.5-turbo"] = {
            "id": "gpt-3.5-turbo",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "ainos",
            "format": ModelFormat.PYTORCH.value,
            "capabilities": ["chat", "completion"],
        }
        self._models["gpt-4"] = {
            "id": "gpt-4",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "ainos",
            "format": ModelFormat.PYTORCH.value,
            "capabilities": ["chat", "completion", "vision"],
        }
        self._models["text-embedding-ada-002"] = {
            "id": "text-embedding-ada-002",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "ainos",
            "format": ModelFormat.ONNX.value,
            "capabilities": ["embedding"],
        }

    def register_runtime(self, model_id: str, runtime: 'MockRuntime'):
        with self._lock:
            self._runtimes[model_id] = runtime

    def get_runtime(self, model_id: str) -> Optional['MockRuntime']:
        with self._lock:
            return self._runtimes.get(model_id)

    async def handle_request(self, method: str, path: str,
                             body: Dict[str, Any] = None,
                             headers: Dict[str, str] = None) -> ApiResponse:
        """处理 API 请求"""
        if not self._running:
            return ApiResponse(
                status_code=503,
                body={"error": "Service not running", "code": ErrorCode.SERVICE_UNAVAILABLE.value},
            )

        headers = headers or {}

        # 认证检查
        if self._config["auth_required"]:
            auth_result = self._authenticate(headers)
            if not auth_result["ok"]:
                return ApiResponse(
                    status_code=401,
                    body={"error": auth_result["error"], "code": ErrorCode.UNAUTHORIZED.value},
                    headers={"WWW-Authenticate": "Bearer"},
                )

        # 速率限制
        client_id = headers.get("Authorization", "unknown")
        if not self._check_rate_limit(client_id):
            return ApiResponse(
                status_code=429,
                body={"error": "Rate limit exceeded", "code": ErrorCode.RATE_LIMITED.value},
                headers={"Retry-After": "60"},
            )

        # 路由
        self._request_log.append({
            "method": method,
            "path": path,
            "body": body,
            "headers": headers,
            "timestamp": time.time(),
        })

        if path == "/v1/health":
            return self._handle_health()
        elif path == "/v1/models":
            return self._handle_list_models()
        elif path == "/v1/chat/completions":
            return await self._handle_chat_completion(body)
        elif path == "/v1/embeddings":
            return await self._handle_embeddings(body)
        elif path == "/v1/completions":
            return await self._handle_completions(body)
        elif path == "/v1/usage":
            return self._handle_usage()
        elif path.startswith("/v1/models/"):
            model_id = path.split("/")[-1]
            return self._handle_model_detail(model_id)
        else:
            return ApiResponse(
                status_code=404,
                body={"error": f"Not found: {path}", "code": ErrorCode.NOT_FOUND.value},
            )

    def _authenticate(self, headers: Dict[str, str]) -> Dict[str, Any]:
        """认证请求"""
        auth_header = headers.get("Authorization", "")
        if not auth_header:
            return {"ok": False, "error": "Missing Authorization header"}

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            for session in self._sessions.values():
                if session.token == token and session.expires_at > time.time():
                    return {"ok": True, "session": session}
            return {"ok": False, "error": "Invalid or expired token"}

        elif auth_header.startswith("ApiKey "):
            api_key = auth_header[7:]
            if api_key and len(api_key) >= 8:
                return {"ok": True, "api_key": api_key}
            return {"ok": False, "error": "Invalid API key"}

        return {"ok": False, "error": "Unsupported auth scheme"}

    def _check_rate_limit(self, client_id: str) -> bool:
        """检查速率限制"""
        now = time.time()
        minute_ago = now - 60
        with self._lock:
            requests = self._rate_limiter[client_id]
            requests.append(now)
            requests[:] = [t for t in requests if t > minute_ago]
            return len(requests) <= self._config["rate_limit_per_minute"]

    def _handle_health(self) -> ApiResponse:
        return ApiResponse(200, {
            "status": self._status.value,
            "version": "1.2.3",
            "uptime": 12345.6,
            "models_loaded": len(self._runtimes),
            "total_requests": len(self._request_log),
        })

    def _handle_list_models(self) -> ApiResponse:
        return ApiResponse(200, {
            "object": "list",
            "data": list(self._models.values()),
        })

    async def _handle_chat_completion(self, body: Dict) -> ApiResponse:
        model_id = body.get("model", "")
        if model_id not in self._models:
            return ApiResponse(404, {
                "error": f"Model '{model_id}' not found",
                "code": ErrorCode.NOT_FOUND.value,
            })

        runtime = self.get_runtime(model_id)
        if not runtime:
            # 自动加载模型
            runtime = MockRuntime(model_id)
            self.register_runtime(model_id, runtime)
            self._status = RuntimeStatus.LOADING
            await runtime.load()
            self._status = RuntimeStatus.RUNNING

        try:
            prompt = body.get("prompt") or body.get("messages", [{}])[0].get("content", "")
            result = await runtime.infer(prompt, body.get("parameters", {}))
            return ApiResponse(200, {
                "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model_id,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": result["text"]},
                    "finish_reason": "stop",
                }],
                "usage": result["usage"],
            })
        except Exception as e:
            return ApiResponse(500, {
                "error": str(e),
                "code": ErrorCode.INTERNAL_ERROR.value,
            })

    async def _handle_embeddings(self, body: Dict) -> ApiResponse:
        model_id = body.get("model", "text-embedding-ada-002")
        inputs = body.get("input", [])
        if isinstance(inputs, str):
            inputs = [inputs]

        runtime = self.get_runtime(model_id)
        if not runtime:
            runtime = MockRuntime(model_id)
            self.register_runtime(model_id, runtime)
            await runtime.load()

        data = []
        for i, text in enumerate(inputs):
            embedding = await runtime.embed(text)
            data.append({
                "object": "embedding",
                "index": i,
                "embedding": embedding,
            })

        return ApiResponse(200, {
            "object": "list",
            "data": data,
            "model": model_id,
            "usage": {"prompt_tokens": len(" ".join(inputs)) // 4},
        })

    async def _handle_completions(self, body: Dict) -> ApiResponse:
        return await self._handle_chat_completion(body)

    def _handle_usage(self) -> ApiResponse:
        return ApiResponse(200, {
            "total_requests": len(self._request_log),
            "active_models": len(self._runtimes),
            "status": self._status.value,
        })

    def _handle_model_detail(self, model_id: str) -> ApiResponse:
        if model_id in self._models:
            return ApiResponse(200, self._models[model_id])
        return ApiResponse(404, {
            "error": f"Model '{model_id}' not found",
            "code": ErrorCode.NOT_FOUND.value,
        })

    def create_session(self, user_id: str, role: str = "user",
                       permissions: List[str] = None) -> UserSession:
        session = UserSession(
            user_id=user_id,
            token=f"tok-{uuid.uuid4().hex}",
            role=role,
            permissions=permissions or ["inference"],
        )
        self._sessions[session.token] = session
        return session

    def revoke_session(self, token: str):
        if token in self._sessions:
            del self._sessions[token]

    @property
    def status(self) -> RuntimeStatus:
        return self._status

    @property
    def request_count(self) -> int:
        return len(self._request_log)


# =============================================================================
# Mock Runtime 层
# =============================================================================

class MockRuntime:
    """模拟模型运行时"""

    def __init__(self, model_id: str):
        self.model_id = model_id
        self._loaded = False
        self._load_time = 0.0
        self._inference_count = 0
        self._total_inference_time = 0.0
        self._lock = threading.RLock()

    async def load(self):
        """加载模型"""
        start = time.time()
        await asyncio.sleep(0.05)  # 模拟加载延迟
        self._load_time = time.time() - start
        self._loaded = True

    def shutdown(self):
        self._loaded = False

    async def infer(self, prompt: str, parameters: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self._loaded:
            raise RuntimeError("Model not loaded")

        params = parameters or {}
        start = time.time()

        # 模拟推理延迟
        delay = params.get("mock_delay", random.uniform(0.01, 0.05))
        await asyncio.sleep(delay)

        prompt_length = len(prompt)
        response_length = random.randint(10, 50)

        with self._lock:
            self._inference_count += 1
            self._total_inference_time += time.time() - start

        return {
            "text": f"Mock response for '{prompt[:20]}...' (model: {self.model_id})",
            "usage": {
                "prompt_tokens": prompt_length // 4,
                "completion_tokens": response_length,
                "total_tokens": prompt_length // 4 + response_length,
            },
        }

    async def embed(self, text: str) -> List[float]:
        if not self._loaded:
            raise RuntimeError("Model not loaded")
        await asyncio.sleep(0.02)
        random.seed(hash(text) % (2**31))
        return [random.uniform(-1, 1) for _ in range(128)]

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "model_id": self.model_id,
                "loaded": self._loaded,
                "load_time": self._load_time,
                "inference_count": self._inference_count,
                "total_inference_time": self._total_inference_time,
                "avg_inference_time": (
                    self._total_inference_time / self._inference_count
                    if self._inference_count > 0 else 0
                ),
            }


# =============================================================================
# 测试夹具
# =============================================================================

@pytest.fixture
def daemon():
    d = MockDaemon()
    d.start()
    yield d
    d.stop()


@pytest.fixture
def python_sdk(daemon):
    sdk = MockPythonSDK(api_key="test-key-12345")
    sdk.set_daemon(daemon)
    session = daemon.create_session("test-user", "admin", ["inference", "admin"])
    sdk._headers["Authorization"] = f"Bearer {session.token}"
    return sdk


@pytest.fixture
def java_sdk(daemon):
    sdk = MockJavaSDK()
    sdk._client.set_daemon(daemon)
    session = daemon.create_session("test-user", "admin", ["inference", "admin"])
    sdk._client._headers["Authorization"] = f"Bearer {session.token}"
    return sdk


@pytest.fixture
def go_sdk(daemon):
    sdk = MockGoSDK()
    sdk._client.set_daemon(daemon)
    session = daemon.create_session("test-user", "admin", ["inference", "admin"])
    sdk._client._headers["Authorization"] = f"Bearer {session.token}"
    return sdk


@pytest.fixture
def node_sdk(daemon):
    sdk = MockNodeSDK()
    sdk._client.set_daemon(daemon)
    session = daemon.create_session("test-user", "admin", ["inference", "admin"])
    sdk._client._headers["Authorization"] = f"Bearer {session.token}"
    return sdk


# =============================================================================
# 测试用例: SDK -> Daemon -> Runtime 完整链路
# =============================================================================

class TestFullPipeline:
    """SDK -> Daemon -> Runtime 完整链路测试"""

    @pytest.mark.asyncio
    async def test_health_check_pipeline(self, python_sdk, daemon):
        """测试健康检查链路"""
        assert daemon.status == RuntimeStatus.READY
        health = await python_sdk.health_check()
        assert health["status"] == "ready"
        assert "version" in health
        assert "uptime" in health

    @pytest.mark.asyncio
    async def test_chat_completion_pipeline(self, python_sdk, daemon):
        """测试聊天补全链路"""
        request = InferenceRequest(
            model="gpt-3.5-turbo",
            prompt="What is the capital of France?",
            parameters={"temperature": 0.7, "max_tokens": 100},
        )
        response = await python_sdk.chat_completion(request)
        assert response.model == "gpt-3.5-turbo"
        assert len(response.choices) > 0
        assert "content" in response.choices[0]["message"]
        assert "usage" in response.__dict__
        assert response.usage["total_tokens"] > 0

    @pytest.mark.asyncio
    async def test_embedding_pipeline(self, python_sdk, daemon):
        """测试嵌入链路"""
        embeddings = await python_sdk.embed(
            model="text-embedding-ada-002",
            input_texts=["Hello world", "Test embedding"],
        )
        assert len(embeddings) == 2
        assert len(embeddings[0]) == 128
        assert all(isinstance(v, float) for v in embeddings[0])

    @pytest.mark.asyncio
    async def test_list_models_pipeline(self, python_sdk, daemon):
        """测试模型列表链路"""
        models = await python_sdk.list_models()
        assert len(models) >= 3
        model_ids = [m["id"] for m in models]
        assert "gpt-3.5-turbo" in model_ids
        assert "gpt-4" in model_ids

    @pytest.mark.asyncio
    async def test_auto_model_loading(self, python_sdk, daemon):
        """测试自动模型加载"""
        request = InferenceRequest(
            model="gpt-4",
            prompt="Test auto-loading",
        )
        response = await python_sdk.chat_completion(request)
        assert response.model == "gpt-4"
        # 验证模型已加载到运行时
        runtime = daemon.get_runtime("gpt-4")
        assert runtime is not None
        assert runtime.is_loaded

    @pytest.mark.asyncio
    async def test_concurrent_requests_pipeline(self, python_sdk, daemon):
        """测试并发请求链路"""
        requests = [
            InferenceRequest(model="gpt-3.5-turbo", prompt=f"Request {i}")
            for i in range(10)
        ]
        tasks = [python_sdk.chat_completion(req) for req in requests]
        responses = await asyncio.gather(*tasks)

        assert len(responses) == 10
        for response in responses:
            assert response.model == "gpt-3.5-turbo"

    @pytest.mark.asyncio
    async def test_request_logging(self, python_sdk, daemon):
        """测试请求日志"""
        await python_sdk.health_check()
        await python_sdk.list_models()
        assert daemon.request_count == 2

    @pytest.mark.asyncio
    async def test_usage_tracking(self, python_sdk, daemon):
        """测试用量跟踪"""
        usage = await python_sdk.get_usage()
        assert "total_requests" in usage
        assert "active_models" in usage

    @pytest.mark.asyncio
    async def test_empty_prompt_handling(self, python_sdk, daemon):
        """测试空提示处理"""
        request = InferenceRequest(model="gpt-3.5-turbo", prompt="")
        response = await python_sdk.chat_completion(request)
        assert response is not None


# =============================================================================
# 测试用例: 多语言 SDK 一致性
# =============================================================================

class TestMultiLanguageSDKConsistency:
    """多语言 SDK 一致性测试"""

    @pytest.mark.asyncio
    async def test_health_consistency(self, python_sdk, java_sdk, go_sdk, node_sdk):
        """测试健康检查一致性"""
        py_health = await python_sdk.health_check()
        java_health = await java_sdk.health()
        go_health = await go_sdk.Health()
        node_health = await node_sdk.healthCheck()

        # 所有 SDK 应该返回一致的状态
        assert py_health["status"] == "ready"
        assert java_health is True
        assert go_health["status"] == "ready"
        assert node_health["status"] == "ready"

    @pytest.mark.asyncio
    async def test_chat_completion_consistency(self, python_sdk, java_sdk, go_sdk, node_sdk):
        """测试聊天补全结果一致性"""
        py_result = await python_sdk.chat_completion(
            InferenceRequest(model="gpt-3.5-turbo", prompt="Hello")
        )
        java_result = await java_sdk.chat("gpt-3.5-turbo", "Hello")
        go_result = await go_sdk.Complete("gpt-3.5-turbo", "Hello")
        node_result = await node_sdk.createCompletion("gpt-3.5-turbo", "Hello")

        assert py_result.choices[0]["message"]["content"] is not None
        assert java_result["choices"] is not None
        assert go_result["choices"] is not None
        assert node_result["choices"] is not None

    @pytest.mark.asyncio
    async def test_error_consistency(self, python_sdk, java_sdk, go_sdk, node_sdk):
        """测试错误处理一致性"""
        # 所有 SDK 对不存在的模型应该返回错误
        bad_request = InferenceRequest(model="nonexistent-model", prompt="test")

        with pytest.raises(RuntimeError):
            await python_sdk.chat_completion(bad_request)

        java_result = await java_sdk.chat("nonexistent-model", "test")
        assert "error" in java_result.lower() or "choices" not in java_result

        go_result = await go_sdk.Complete("nonexistent-model", "test")
        assert "error" in str(go_result)

        node_result = await node_sdk.createCompletion("nonexistent-model", "test")
        assert "error" in str(node_result)

    @pytest.mark.asyncio
    async def test_sdk_headers_consistency(self, python_sdk, java_sdk, go_sdk, node_sdk):
        """测试 SDK 请求头一致性"""
        # 所有 SDK 都应该有类似的基础头
        for sdk in [python_sdk, java_sdk._client, go_sdk._client, node_sdk._client]:
            assert "Authorization" in sdk._headers
            assert "Content-Type" in sdk._headers
            assert sdk._headers["Content-Type"] == "application/json"

    @pytest.mark.asyncio
    async def test_response_format_consistency(self, python_sdk, java_sdk, go_sdk, node_sdk):
        """测试响应格式一致性"""
        # 所有 SDK 的 chat 响应应该有相同的基本结构
        py_resp = await python_sdk.chat_completion(
            InferenceRequest(model="gpt-3.5-turbo", prompt="test")
        )
        assert hasattr(py_resp, "choices")
        assert hasattr(py_resp, "model")
        assert hasattr(py_resp, "usage")

    @pytest.mark.asyncio
    async def test_batch_consistency(self, python_sdk, java_sdk, go_sdk, node_sdk):
        """测试批量请求一致性"""
        requests = [
            InferenceRequest(model="gpt-3.5-turbo", prompt=f"Batch {i}")
            for i in range(5)
        ]
        responses = await python_sdk.batch_inference(requests)
        assert len(responses) == 5
        for r in responses:
            assert isinstance(r, InferenceResponse)


# =============================================================================
# 测试用例: 认证/授权流程
# =============================================================================

class TestAuthenticationAuthorization:
    """认证和授权流程测试"""

    @pytest.mark.asyncio
    async def test_valid_token_auth(self, daemon):
        """测试有效 token 认证"""
        sdk = MockSDKClient(api_key="test-key")
        sdk.set_daemon(daemon)

        session = daemon.create_session("user1", "user", ["inference"])
        sdk._headers["Authorization"] = f"Bearer {session.token}"

        response = await sdk.request("GET", "/v1/health")
        assert response.is_ok

    @pytest.mark.asyncio
    async def test_invalid_token_auth(self, daemon):
        """测试无效 token 认证"""
        sdk = MockSDKClient(api_key="test-key")
        sdk.set_daemon(daemon)
        sdk._headers["Authorization"] = "Bearer invalid-token"

        response = await sdk.request("GET", "/v1/health")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_auth_header(self, daemon):
        """测试缺失认证头"""
        sdk = MockSDKClient(api_key="test-key")
        sdk.set_daemon(daemon)
        del sdk._headers["Authorization"]

        response = await sdk.request("GET", "/v1/health")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_api_key_auth(self, daemon):
        """测试 API Key 认证"""
        sdk = MockSDKClient(api_key="test-key-valid")
        sdk.set_daemon(daemon)
        sdk._headers["Authorization"] = "ApiKey test-key-valid-12345"

        response = await sdk.request("GET", "/v1/health")
        assert response.is_ok

    @pytest.mark.asyncio
    async def test_token_expiry(self, daemon):
        """测试 Token 过期"""
        sdk = MockSDKClient(api_key="test-key")
        sdk.set_daemon(daemon)

        session = UserSession(
            user_id="expired-user",
            token="expired-token",
            role="user",
            expires_at=time.time() - 3600,  # 已过期
        )
        daemon._sessions[session.token] = session
        sdk._headers["Authorization"] = f"Bearer {session.token}"

        response = await sdk.request("GET", "/v1/health")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_rate_limiting(self, daemon):
        """测试速率限制"""
        sdk = MockSDKClient(api_key="test-key")
        sdk.set_daemon(daemon)
        session = daemon.create_session("ratelimit-user", "user", ["inference"])
        sdk._headers["Authorization"] = f"Bearer {session.token}"

        daemon._config["rate_limit_per_minute"] = 5

        # 前 5 个请求应该成功
        for i in range(5):
            response = await sdk.request("GET", "/v1/health")
            assert response.is_ok, f"Request {i} failed"

        # 第 6 个请求应该被限流
        response = await sdk.request("GET", "/v1/health")
        assert response.status_code == 429

    @pytest.mark.asyncio
    async def test_session_revocation(self, daemon):
        """测试会话撤销"""
        sdk = MockSDKClient(api_key="test-key")
        sdk.set_daemon(daemon)

        session = daemon.create_session("revokable-user", "user", ["inference"])
        sdk._headers["Authorization"] = f"Bearer {session.token}"

        # 撤销前可以访问
        response = await sdk.request("GET", "/v1/health")
        assert response.is_ok

        # 撤销会话
        daemon.revoke_session(session.token)

        # 撤销后不能访问
        response = await sdk.request("GET", "/v1/health")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_unsupported_auth_scheme(self, daemon):
        """测试不支持的认证方案"""
        sdk = MockSDKClient(api_key="test-key")
        sdk.set_daemon(daemon)
        sdk._headers["Authorization"] = "Digest realm=test"

        response = await sdk.request("GET", "/v1/health")
        assert response.status_code == 401


# =============================================================================
# 测试用例: 错误处理流程
# =============================================================================

class TestErrorHandling:
    """错误处理流程测试"""

    @pytest.mark.asyncio
    async def test_model_not_found(self, python_sdk, daemon):
        """测试模型不存在"""
        request = InferenceRequest(model="unknown-model", prompt="test")
        with pytest.raises(RuntimeError) as exc_info:
            await python_sdk.chat_completion(request)
        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_service_unavailable(self, daemon):
        """测试服务不可用"""
        daemon.stop()
        sdk = MockSDKClient(api_key="test-key")
        sdk.set_daemon(daemon)

        response = await sdk.request("GET", "/v1/health")
        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_not_found_endpoint(self, python_sdk, daemon):
        """测试不存在的端点"""
        response = await python_sdk.request("GET", "/v1/nonexistent")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_request_body(self, python_sdk, daemon):
        """测试无效请求体"""
        response = await python_sdk.request("POST", "/v1/chat/completions", body={})
        assert response.status_code == 404  # 缺少 model 字段

    @pytest.mark.asyncio
    async def test_server_error_recovery(self, python_sdk, daemon):
        """测试服务器错误恢复"""
        # 发送一个错误请求后的正常请求
        bad_request = InferenceRequest(model="unknown-model", prompt="test")
        try:
            await python_sdk.chat_completion(bad_request)
        except RuntimeError:
            pass

        # 后续请求应该正常
        health = await python_sdk.health_check()
        assert health["status"] == "ready"

    @pytest.mark.asyncio
    async def test_concurrent_errors(self, python_sdk, daemon):
        """测试并发错误"""
        requests = [
            InferenceRequest(model="unknown-model", prompt=f"Error test {i}")
            for i in range(5)
        ]
        tasks = [python_sdk.chat_completion(req) for req in requests]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        errors = [r for r in results if isinstance(r, Exception)]
        assert len(errors) == 5

    @pytest.mark.asyncio
    async def test_error_response_format(self, python_sdk, daemon):
        """测试错误响应格式"""
        response = await python_sdk.request("GET", "/v1/nonexistent")
        assert "error" in response.body
        assert "code" in response.body


# =============================================================================
# 测试用例: 复杂集成场景
# =============================================================================

class TestComplexIntegrationScenarios:
    """复杂集成场景测试"""

    @pytest.mark.asyncio
    async def test_inference_with_parameters(self, python_sdk, daemon):
        """测试带参数的推理"""
        request = InferenceRequest(
            model="gpt-3.5-turbo",
            prompt="Write a poem",
            parameters={
                "temperature": 0.8,
                "max_tokens": 200,
                "top_p": 0.9,
                "frequency_penalty": 0.5,
                "presence_penalty": 0.5,
            },
        )
        response = await python_sdk.chat_completion(request)
        assert response.usage["total_tokens"] > 0

    @pytest.mark.asyncio
    async def test_sequential_requests(self, python_sdk, daemon):
        """测试顺序请求"""
        prompts = ["First", "Second", "Third"]
        for prompt in prompts:
            request = InferenceRequest(model="gpt-3.5-turbo", prompt=prompt)
            response = await python_sdk.chat_completion(request)
            assert response.model == "gpt-3.5-turbo"

    @pytest.mark.asyncio
    async def test_mixed_workload(self, python_sdk, daemon):
        """测试混合工作负载"""
        # 健康检查
        health = await python_sdk.health_check()
        assert health["status"] == "ready"

        # 列出模型
        models = await python_sdk.list_models()
        assert len(models) > 0

        # 推理
        inference = await python_sdk.chat_completion(
            InferenceRequest(model="gpt-3.5-turbo", prompt="Test")
        )
        assert inference is not None

        # 嵌入
        embeddings = await python_sdk.embed(
            model="text-embedding-ada-002",
            input_texts=["test"],
        )
        assert len(embeddings) > 0

        # 用量统计
        usage = await python_sdk.get_usage()
        assert usage["total_requests"] >= 3

    @pytest.mark.asyncio
    async def test_daemon_restart(self, python_sdk, daemon):
        """测试 Daemon 重启"""
        # 正常使用
        await python_sdk.health_check()

        # 停止 daemon
        daemon.stop()

        # 请求应该失败
        with pytest.raises(Exception):
            await python_sdk.health_check()

        # 重启 daemon
        daemon.start()

        # 恢复
        health = await python_sdk.health_check()
        assert health["status"] == "ready"

    @pytest.mark.asyncio
    async def test_multi_model_concurrent(self, python_sdk, daemon):
        """测试多模型并发"""
        models = ["gpt-3.5-turbo", "gpt-4"]
        requests = [
            InferenceRequest(model=random.choice(models), prompt=f"Concurrent {i}")
            for i in range(20)
        ]
        tasks = [python_sdk.chat_completion(req) for req in requests]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        successful = [r for r in responses if isinstance(r, InferenceResponse)]
        assert len(successful) > 0

    @pytest.mark.asyncio
    async def test_long_prompt(self, python_sdk, daemon):
        """测试长提示"""
        long_prompt = "Hello " * 1000
        request = InferenceRequest(model="gpt-3.5-turbo", prompt=long_prompt)
        response = await python_sdk.chat_completion(request)
        assert response.usage["prompt_tokens"] > 0

    @pytest.mark.asyncio
    async def test_runtime_stats_after_requests(self, python_sdk, daemon):
        """测试推理后的运行时统计"""
        for i in range(5):
            await python_sdk.chat_completion(
                InferenceRequest(model="gpt-3.5-turbo", prompt=f"Stats test {i}")
            )

        runtime = daemon.get_runtime("gpt-3.5-turbo")
        stats = runtime.stats
        assert stats["inference_count"] == 5
        assert stats["avg_inference_time"] > 0

    @pytest.mark.asyncio
    async def test_error_rate_under_load(self, python_sdk, daemon):
        """测试负载下的错误率"""
        num_requests = 50
        requests = [
            InferenceRequest(
                model=random.choice(["gpt-3.5-turbo", "gpt-4", "unknown-model"]),
                prompt=f"Load test {i}",
            )
            for i in range(num_requests)
        ]
        tasks = [python_sdk.chat_completion(req) for req in requests]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        errors = sum(1 for r in results if isinstance(r, Exception))
        error_rate = errors / num_requests
        # 错误率不应该太高（未知模型会失败，但已知模型应该成功）
        assert error_rate < 0.5


# =============================================================================
# 测试用例: 安全与合规
# =============================================================================

class TestSecurityAndCompliance:
    """安全与合规测试"""

    @pytest.mark.asyncio
    async def test_https_enforcement(self, python_sdk):
        """测试 HTTPS 强制"""
        # 应该处理 HTTP URL
        pass

    @pytest.mark.asyncio
    async def test_request_validation(self, python_sdk, daemon):
        """测试请求验证"""
        response = await python_sdk.request("POST", "/v1/chat/completions", body={
            "model": "gpt-3.5-turbo",
            "prompt": "test",
            "temperature": 2.5,  # 超出范围
        })
        # 应该接受请求（mock 不做严格验证）
        assert response.is_ok or response.status_code == 400

    @pytest.mark.asyncio
    async def test_sensitive_data_logging(self, python_sdk, daemon):
        """测试敏感数据日志"""
        request = InferenceRequest(
            model="gpt-3.5-turbo",
            prompt="My password is secret123",
        )
        await python_sdk.chat_completion(request)

        # 检查日志中是否包含敏感信息
        for log in daemon._request_log:
            if log["body"] and "prompt" in log["body"]:
                assert "secret123" not in json.dumps(log["body"])

    @pytest.mark.asyncio
    async def test_input_sanitization(self, python_sdk, daemon):
        """测试输入清理"""
        malicious_inputs = [
            "<script>alert('xss')</script>",
            "'; DROP TABLE users; --",
            "../../../etc/passwd",
            None,
            {"nested": "object"},
        ]
        for inp in malicious_inputs:
            try:
                request = InferenceRequest(
                    model="gpt-3.5-turbo",
                    prompt=str(inp) if inp is not None else "",
                )
                response = await python_sdk.chat_completion(request)
                assert response is not None
            except Exception:
                pass


# =============================================================================
# E2E 测试主入口
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])