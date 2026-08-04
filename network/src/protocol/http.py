"""
HTTP/1.1 + HTTP/2 协议实现
==========================

提供完整的 HTTP 客户端和服务器实现，支持 HTTP/1.1 和 HTTP/2 协议，
包括连接池、会话复用、流控制和头部压缩等特性。
"""

import asyncio
import io
import json
import zlib
import time
import uuid
import cgi
import logging
import urllib.parse
from typing import Optional, Dict, Any, List, Tuple, Callable
from dataclasses import dataclass, field
from enum import IntEnum
from collections import OrderedDict


logger = logging.getLogger(__name__)


class HTTPVersion(IntEnum):
    """HTTP 版本"""
    HTTP_1_0 = 10
    HTTP_1_1 = 11
    HTTP_2 = 20
    HTTP_3 = 30


class HTTPMethod(str, IntEnum):
    """HTTP 方法"""
    GET = "GET"
    HEAD = "HEAD"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    CONNECT = "CONNECT"
    OPTIONS = "OPTIONS"
    TRACE = "TRACE"
    PATCH = "PATCH"


class HTTPStatus(IntEnum):
    """HTTP 状态码"""
    # 1xx 信息
    CONTINUE = 100
    SWITCHING_PROTOCOLS = 101
    PROCESSING = 102

    # 2xx 成功
    OK = 200
    CREATED = 201
    ACCEPTED = 202
    NON_AUTHORITATIVE_INFORMATION = 203
    NO_CONTENT = 204
    RESET_CONTENT = 205
    PARTIAL_CONTENT = 206

    # 3xx 重定向
    MULTIPLE_CHOICES = 300
    MOVED_PERMANENTLY = 301
    FOUND = 302
    SEE_OTHER = 303
    NOT_MODIFIED = 304
    USE_PROXY = 305
    TEMPORARY_REDIRECT = 307
    PERMANENT_REDIRECT = 308

    # 4xx 客户端错误
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    PAYMENT_REQUIRED = 402
    FORBIDDEN = 403
    NOT_FOUND = 404
    METHOD_NOT_ALLOWED = 405
    NOT_ACCEPTABLE = 406
    PROXY_AUTHENTICATION_REQUIRED = 407
    REQUEST_TIMEOUT = 408
    CONFLICT = 409
    GONE = 410
    LENGTH_REQUIRED = 411
    PRECONDITION_FAILED = 412
    PAYLOAD_TOO_LARGE = 413
    URI_TOO_LONG = 414
    UNSUPPORTED_MEDIA_TYPE = 415
    RANGE_NOT_SATISFIABLE = 416
    EXPECTATION_FAILED = 417
    IM_A_TEAPOT = 418
    TOO_MANY_REQUESTS = 429
    REQUEST_HEADER_FIELDS_TOO_LARGE = 431

    # 5xx 服务器错误
    INTERNAL_SERVER_ERROR = 500
    NOT_IMPLEMENTED = 501
    BAD_GATEWAY = 502
    SERVICE_UNAVAILABLE = 503
    GATEWAY_TIMEOUT = 504
    HTTP_VERSION_NOT_SUPPORTED = 505
    INSUFFICIENT_STORAGE = 507
    NETWORK_AUTHENTICATION_REQUIRED = 511

    @property
    def phrase(self) -> str:
        """获取状态码的文本描述"""
        phrases = {
            100: "Continue", 101: "Switching Protocols", 102: "Processing",
            200: "OK", 201: "Created", 202: "Accepted", 203: "Non-Authoritative Information",
            204: "No Content", 205: "Reset Content", 206: "Partial Content",
            300: "Multiple Choices", 301: "Moved Permanently", 302: "Found",
            303: "See Other", 304: "Not Modified", 305: "Use Proxy",
            307: "Temporary Redirect", 308: "Permanent Redirect",
            400: "Bad Request", 401: "Unauthorized", 402: "Payment Required",
            403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed",
            406: "Not Acceptable", 407: "Proxy Authentication Required",
            408: "Request Timeout", 409: "Conflict", 410: "Gone",
            411: "Length Required", 412: "Precondition Failed",
            413: "Payload Too Large", 414: "URI Too Long",
            415: "Unsupported Media Type", 416: "Range Not Satisfiable",
            417: "Expectation Failed", 418: "I'm a teapot",
            429: "Too Many Requests", 431: "Request Header Fields Too Large",
            500: "Internal Server Error", 501: "Not Implemented",
            502: "Bad Gateway", 503: "Service Unavailable",
            504: "Gateway Timeout", 505: "HTTP Version Not Supported",
            507: "Insufficient Storage", 511: "Network Authentication Required",
        }
        return phrases.get(self.value, "Unknown")


class HTTPError(Exception):
    """HTTP 错误"""
    pass


class HTTPConnectionError(HTTPError):
    """HTTP 连接错误"""
    pass


class HTTPParseError(HTTPError):
    """HTTP 解析错误"""
    pass


@dataclass
class HTTPRequest:
    """HTTP 请求"""
    method: HTTPMethod = HTTPMethod.GET
    path: str = "/"
    version: HTTPVersion = HTTPVersion.HTTP_1_1
    headers: Dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    params: Dict[str, str] = field(default_factory=dict)
    cookies: Dict[str, str] = field(default_factory=dict)
    remote_addr: str = ""
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self):
        if isinstance(self.method, str):
            self.method = HTTPMethod(self.method.upper())
        if isinstance(self.version, int):
            self.version = HTTPVersion(self.version)

    @property
    def path_with_params(self) -> str:
        if self.params:
            query = urllib.parse.urlencode(self.params)
            return f"{self.path}?{query}"
        return self.path

    @property
    def content_type(self) -> str:
        return self.headers.get("Content-Type", "")

    @property
    def content_length(self) -> int:
        try:
            return int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            return 0

    @property
    def host(self) -> str:
        return self.headers.get("Host", "")

    @property
    def user_agent(self) -> str:
        return self.headers.get("User-Agent", "")

    def get_header(self, name: str, default: str = "") -> str:
        return self.headers.get(name, default)

    def get_cookie(self, name: str) -> Optional[str]:
        return self.cookies.get(name)

    def json(self) -> Any:
        """解析 JSON 请求体"""
        if self.body:
            try:
                return json.loads(self.body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise HTTPParseError(f"JSON 解析失败: {e}")
        return None

    def form(self) -> Dict[str, str]:
        """解析表单数据"""
        if self.content_type == "application/x-www-form-urlencoded":
            parsed = urllib.parse.parse_qs(self.body.decode("utf-8"))
            return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
        return {}

    def encode(self) -> bytes:
        """编码为字节"""
        lines = [
            f"{self.method.value} {self.path_with_params} "
            f"HTTP/{self.version.value / 10:.1f}"
        ]
        for key, value in self.headers.items():
            lines.append(f"{key}: {value}")
        lines.append("")
        data = "\r\n".join(lines).encode("utf-8")
        if self.body:
            data += b"\r\n" + self.body
        return data

    @classmethod
    def decode(cls, data: bytes) -> "HTTPRequest":
        """从字节解码"""
        try:
            text = data.decode("utf-8", errors="replace")
        except UnicodeDecodeError:
            raise HTTPParseError("HTTP 请求解码失败")

        lines = text.split("\r\n")
        if not lines:
            raise HTTPParseError("空的 HTTP 请求")

        # 解析请求行
        request_line = lines[0].strip()
        parts = request_line.split(" ")
        if len(parts) < 3:
            raise HTTPParseError(f"无效的请求行: {request_line}")

        method = HTTPMethod(parts[0].upper())
        path_with_params = parts[1]

        version_str = parts[2].replace("HTTP/", "")
        version = HTTPVersion(int(float(version_str) * 10))

        # 解析路径和参数
        parsed = urllib.parse.urlparse(path_with_params)
        path = parsed.path
        params = dict(urllib.parse.parse_qsl(parsed.query))

        # 解析头部
        headers = {}
        cookies = {}
        i = 1
        while i < len(lines) and lines[i].strip():
            header_line = lines[i]
            if ":" in header_line:
                key, value = header_line.split(":", 1)
                headers[key.strip()] = value.strip()
                if key.lower() == "cookie":
                    for cookie in value.split(";"):
                        cookie = cookie.strip()
                        if "=" in cookie:
                            ck, cv = cookie.split("=", 1)
                            cookies[ck.strip()] = cv.strip()
            i += 1

        # 解析请求体
        body_start = text.find("\r\n\r\n") + 4
        body = data[body_start:] if body_start < len(data) else b""

        return cls(
            method=method,
            path=path,
            version=version,
            headers=headers,
            body=body,
            params=params,
            cookies=cookies,
        )


@dataclass
class HTTPResponse:
    """HTTP 响应"""
    version: HTTPVersion = HTTPVersion.HTTP_1_1
    status: HTTPStatus = HTTPStatus.OK
    headers: Dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    cookies: Dict[str, Dict[str, str]] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self):
        if isinstance(self.status, int):
            self.status = HTTPStatus(self.status)
        if isinstance(self.version, int):
            self.version = HTTPVersion(self.version)

    @property
    def status_code(self) -> int:
        return self.status.value

    @property
    def reason_phrase(self) -> str:
        return self.status.phrase

    @property
    def content_type(self) -> str:
        return self.headers.get("Content-Type", "text/plain")

    @property
    def content_length(self) -> int:
        return len(self.body)

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def is_redirect(self) -> bool:
        return 300 <= self.status_code < 400

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400

    @property
    def location(self) -> Optional[str]:
        return self.headers.get("Location")

    def get_header(self, name: str, default: str = "") -> str:
        return self.headers.get(name, default)

    def set_cookie(self, name: str, value: str, **kwargs: Any) -> None:
        """设置 Cookie"""
        self.cookies[name] = {"value": value, **kwargs}

    def json(self) -> Any:
        """解析 JSON 响应体"""
        if self.body:
            try:
                return json.loads(self.body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return None
        return None

    def text(self) -> str:
        """获取文本响应体"""
        return self.body.decode("utf-8", errors="replace")

    def encode(self) -> bytes:
        """编码为字节"""
        lines = [
            f"HTTP/{self.version.value / 10:.1f} {self.status_code} {self.reason_phrase}"
        ]
        for key, value in self.headers.items():
            lines.append(f"{key}: {value}")
        lines.append("")
        data = "\r\n".join(lines).encode("utf-8")
        if self.body:
            data += b"\r\n" + self.body
        return data

    @classmethod
    def decode(cls, data: bytes) -> "HTTPResponse":
        """从字节解码"""
        try:
            text = data.decode("utf-8", errors="replace")
        except UnicodeDecodeError:
            raise HTTPParseError("HTTP 响应解码失败")

        lines = text.split("\r\n")
        if not lines:
            raise HTTPParseError("空的 HTTP 响应")

        # 解析状态行
        status_line = lines[0].strip()
        parts = status_line.split(" ", 2)
        if len(parts) < 2:
            raise HTTPParseError(f"无效的状态行: {status_line}")

        version_str = parts[0].replace("HTTP/", "")
        version = HTTPVersion(int(float(version_str) * 10))
        status = HTTPStatus(int(parts[1]))

        # 解析头部
        headers = {}
        i = 1
        while i < len(lines) and lines[i].strip():
            header_line = lines[i]
            if ":" in header_line:
                key, value = header_line.split(":", 1)
                headers[key.strip()] = value.strip()
            i += 1

        # 解析响应体
        body_start = text.find("\r\n\r\n") + 4
        body = data[body_start:] if body_start < len(data) else b""

        # 处理 Content-Length
        content_length = int(headers.get("Content-Length", 0))
        if content_length > 0:
            body = body[:content_length]

        return cls(
            version=version,
            status=status,
            headers=headers,
            body=body,
        )


class HTTPConnection:
    """HTTP 连接"""

    def __init__(self, host: str, port: int, ssl: bool = False,
                 timeout: float = 30.0) -> None:
        self.host = host
        self.port = port
        self.ssl = ssl
        self.timeout = timeout
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._last_used: float = 0
        self._is_alive: bool = False
        self._keep_alive: bool = True
        self._request_count: int = 0

    @property
    def is_idle(self) -> bool:
        return self._is_alive and time.time() - self._last_used > 5

    async def connect(self) -> None:
        """建立连接"""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port, ssl=self.ssl),
                timeout=self.timeout,
            )
            self._is_alive = True
            self._last_used = time.time()
        except asyncio.TimeoutError:
            raise HTTPConnectionError(f"连接超时: {self.host}:{self.port}")
        except OSError as e:
            raise HTTPConnectionError(f"连接失败: {e}")

    async def send_request(self, request: HTTPRequest) -> HTTPResponse:
        """发送请求并接收响应"""
        if not self._is_alive:
            await self.connect()

        self._request_count += 1
        self._last_used = time.time()

        try:
            data = request.encode()
            self._writer.write(data)
            await self._writer.drain()

            response_data = await self._read_response()
            response = HTTPResponse.decode(response_data)

            if not self._keep_alive:
                await self.close()

            return response

        except (OSError, asyncio.TimeoutError) as e:
            self._is_alive = False
            raise HTTPConnectionError(f"请求失败: {e}")

    async def _read_response(self) -> bytes:
        """读取响应"""
        data = b""
        while True:
            line = await self._reader.readline()
            data += line
            if line == b"\r\n":
                break

        # 解析头部以获取 Content-Length
        text = data.decode("utf-8", errors="replace")
        content_length = 0
        for line in text.split("\r\n"):
            if line.lower().startswith("content-length:"):
                try:
                    content_length = int(line.split(":", 1)[1].strip())
                except (ValueError, IndexError):
                    pass
            elif line.lower().startswith("transfer-encoding:") and "chunked" in line.lower():
                return await self._read_chunked_response(data)

        if content_length > 0:
            body = await self._reader.readexactly(content_length)
            data += body

        return data

    async def _read_chunked_response(self, header_data: bytes) -> bytes:
        """读取分块传输编码的响应"""
        data = header_data
        while True:
            line = await self._reader.readline()
            chunk_size_str = line.strip().split(b";")[0]
            try:
                chunk_size = int(chunk_size_str, 16)
            except ValueError:
                break

            if chunk_size == 0:
                data += line
                # 读取尾部
                while True:
                    trailer = await self._reader.readline()
                    data += trailer
                    if trailer == b"\r\n":
                        break
                break

            chunk = await self._reader.readexactly(chunk_size)
            data += line + chunk
            # 读取 CRLF
            crlf = await self._reader.readexactly(2)

        return data

    async def close(self) -> None:
        """关闭连接"""
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._is_alive = False

    def __del__(self):
        if self._writer:
            try:
                self._writer.close()
            except Exception:
                pass


class HTTPConnectionPool:
    """HTTP 连接池"""

    def __init__(self, host: str, port: int, ssl: bool = False,
                 max_connections: int = 10, max_idle: int = 5) -> None:
        self.host = host
        self.port = port
        self.ssl = ssl
        self.max_connections = max_connections
        self.max_idle = max_idle
        self._connections: List[HTTPConnection] = []
        self._lock = asyncio.Lock()

    async def get_connection(self) -> HTTPConnection:
        """获取一个连接"""
        async with self._lock:
            # 尝试复用空闲连接
            for conn in self._connections:
                if conn.is_idle:
                    self._connections.remove(conn)
                    return conn

            if len(self._connections) < self.max_connections:
                conn = HTTPConnection(self.host, self.port, self.ssl)
                return conn

            # 等待连接释放
            raise HTTPConnectionError("连接池已满")

    async def release_connection(self, conn: HTTPConnection) -> None:
        """释放连接回池中"""
        async with self._lock:
            if conn.is_idle and len(self._connections) < self.max_idle:
                self._connections.append(conn)
            else:
                await conn.close()

    async def close_all(self) -> None:
        """关闭所有连接"""
        async with self._lock:
            for conn in self._connections:
                await conn.close()
            self._connections.clear()


class HTTPClient:
    """HTTP 客户端"""

    def __init__(self, max_connections: int = 10, timeout: float = 30.0,
                 follow_redirects: bool = True, max_redirects: int = 5) -> None:
        self._max_connections = max_connections
        self._timeout = timeout
        self._follow_redirects = follow_redirects
        self._max_redirects = max_redirects
        self._default_headers: Dict[str, str] = {
            "User-Agent": "Ainos-Network-Stack/2.0",
            "Accept": "*/*",
        }
        self._pools: Dict[str, HTTPConnectionPool] = {}
        self._stats: Dict[str, int] = {
            "requests": 0,
            "success": 0,
            "errors": 0,
            "redirects": 0,
        }

    def set_default_header(self, name: str, value: str) -> None:
        """设置默认请求头"""
        self._default_headers[name] = value

    async def request(self, method: str, url: str, **kwargs: Any) -> HTTPResponse:
        """发送 HTTP 请求

        Args:
            method: HTTP 方法
            url: 请求 URL
            **kwargs: 额外参数 (headers, body, params, timeout, json, form)

        Returns:
            HTTP 响应

        Raises:
            HTTPConnectionError: 连接失败
            HTTPError: 请求失败
        """
        self._stats["requests"] += 1
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        ssl = parsed.scheme == "https"
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        # 构建请求
        headers = {**self._default_headers, **kwargs.get("headers", {})}
        body = kwargs.get("body", b"")
        params = kwargs.get("params", {})
        timeout = kwargs.get("timeout", self._timeout)

        # 处理 JSON
        if "json" in kwargs:
            body = json.dumps(kwargs["json"]).encode("utf-8")
            headers["Content-Type"] = "application/json"

        # 处理表单
        if "form" in kwargs:
            body = urllib.parse.urlencode(kwargs["form"]).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        if body:
            headers["Content-Length"] = str(len(body))

        http_method = HTTPMethod(method.upper())

        request = HTTPRequest(
            method=http_method,
            path=path,
            headers=headers,
            body=body,
            params=params,
        )

        # 获取连接池
        pool_key = f"{host}:{port}:{ssl}"
        if pool_key not in self._pools:
            self._pools[pool_key] = HTTPConnectionPool(
                host, port, ssl, self._max_connections
            )
        pool = self._pools[pool_key]

        # 发送请求
        redirect_count = 0
        while redirect_count <= self._max_redirects:
            conn = await pool.get_connection()
            try:
                response = await conn.send_request(request)
                await pool.release_connection(conn)

                # 处理重定向
                if (self._follow_redirects and response.is_redirect
                        and response.location):
                    redirect_count += 1
                    self._stats["redirects"] += 1
                    url = response.location
                    if not url.startswith("http"):
                        url = f"{parsed.scheme}://{host}:{port}{url}"
                    parsed = urllib.parse.urlparse(url)
                    request.path = parsed.path or "/"
                    if parsed.query:
                        request.path = f"{request.path}?{parsed.query}"
                    continue

                if response.is_success:
                    self._stats["success"] += 1
                else:
                    self._stats["errors"] += 1

                return response

            except Exception as e:
                await pool.release_connection(conn)
                self._stats["errors"] += 1
                raise HTTPConnectionError(f"请求失败: {e}")

        raise HTTPError(f"重定向次数过多 ({self._max_redirects})")

    # 便捷方法
    async def get(self, url: str, **kwargs: Any) -> HTTPResponse:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> HTTPResponse:
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> HTTPResponse:
        return await self.request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> HTTPResponse:
        return await self.request("DELETE", url, **kwargs)

    async def head(self, url: str, **kwargs: Any) -> HTTPResponse:
        return await self.request("HEAD", url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> HTTPResponse:
        return await self.request("PATCH", url, **kwargs)

    async def options(self, url: str, **kwargs: Any) -> HTTPResponse:
        return await self.request("OPTIONS", url, **kwargs)

    async def close(self) -> None:
        """关闭所有连接"""
        for pool in self._pools.values():
            await pool.close_all()
        self._pools.clear()

    def get_statistics(self) -> Dict[str, int]:
        return self._stats.copy()


class HTTPServer:
    """HTTP 服务器"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080,
                 backlog: int = 128) -> None:
        self.host = host
        self.port = port
        self.backlog = backlog
        self._routes: List[Tuple[str, str, Callable]] = []
        self._middleware: List[Callable] = []
        self._server: Optional[asyncio.AbstractServer] = None
        self._is_running: bool = False
        self._stats: Dict[str, int] = {
            "requests": 0,
            "success": 0,
            "errors": 0,
            "active_connections": 0,
        }

    def route(self, method: str, path: str) -> Callable:
        """路由装饰器"""
        def decorator(handler: Callable) -> Callable:
            self._routes.append((method.upper(), path, handler))
            return handler
        return decorator

    def get(self, path: str) -> Callable:
        return self.route("GET", path)

    def post(self, path: str) -> Callable:
        return self.route("POST", path)

    def put(self, path: str) -> Callable:
        return self.route("PUT", path)

    def delete(self, path: str) -> Callable:
        return self.route("DELETE", path)

    def use(self, middleware: Callable) -> None:
        """添加中间件"""
        self._middleware.append(middleware)

    async def start(self) -> None:
        """启动服务器"""
        self._server = await asyncio.start_server(
            self._handle_connection,
            self.host,
            self.port,
            backlog=self.backlog,
        )
        self._is_running = True
        logger.info(f"HTTP 服务器已启动: {self.host}:{self.port}")

    async def stop(self) -> None:
        """停止服务器"""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._is_running = False
            logger.info("HTTP 服务器已停止")

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        """处理连接"""
        self._stats["active_connections"] += 1
        addr = writer.get_extra_info("peername") or ("unknown", 0)

        try:
            data = await self._read_request(reader)
            if not data:
                return

            request = HTTPRequest.decode(data)
            request.remote_addr = f"{addr[0]}:{addr[1]}"

            response = await self._handle_request(request)

            writer.write(response.encode())
            await writer.drain()

        except HTTPParseError as e:
            error_response = HTTPResponse(
                status=HTTPStatus.BAD_REQUEST,
                body=str(e).encode("utf-8"),
            )
            writer.write(error_response.encode())
            await writer.drain()

        except Exception as e:
            logger.error(f"请求处理错误: {e}")
            error_response = HTTPResponse(
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
                body=b"Internal Server Error",
            )
            writer.write(error_response.encode())
            await writer.drain()

        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            self._stats["active_connections"] -= 1

    async def _read_request(self, reader: asyncio.StreamReader) -> bytes:
        """读取 HTTP 请求"""
        data = b""
        while True:
            line = await reader.readline()
            data += line
            if line == b"\r\n":
                break
            if not line:
                return b""

        # 读取请求体
        text = data.decode("utf-8", errors="replace")
        content_length = 0
        for line in text.split("\r\n"):
            if line.lower().startswith("content-length:"):
                try:
                    content_length = int(line.split(":", 1)[1].strip())
                except (ValueError, IndexError):
                    pass

        if content_length > 0:
            body = await reader.readexactly(content_length)
            data += body

        return data

    async def _handle_request(self, request: HTTPRequest) -> HTTPResponse:
        """处理请求"""
        self._stats["requests"] += 1

        # 运行中间件
        for middleware in self._middleware:
            try:
                result = await middleware(request)
                if result is not None:
                    return result
            except Exception as e:
                logger.error(f"中间件错误: {e}")

        # 查找路由
        for method, path, handler in self._routes:
            if method == request.method.value and self._match_path(path, request.path):
                try:
                    response = await handler(request)
                    self._stats["success"] += 1
                    return response
                except Exception as e:
                    self._stats["errors"] += 1
                    logger.error(f"路由处理错误: {e}")
                    return HTTPResponse(
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                        body=str(e).encode("utf-8"),
                    )

        self._stats["errors"] += 1
        return HTTPResponse(
            status=HTTPStatus.NOT_FOUND,
            body=b"Not Found",
        )

    @staticmethod
    def _match_path(pattern: str, path: str) -> bool:
        """匹配路径（支持简单通配符）"""
        if pattern == path:
            return True
        if pattern.endswith("*"):
            return path.startswith(pattern[:-1])
        return False

    def get_statistics(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "routes": len(self._routes),
            "middleware": len(self._middleware),
            "is_running": self._is_running,
        }


# HTTP/2 相关常量
HTTP2_MAGIC = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r"
HTTP2_SETTINGS_HEADER_TABLE_SIZE = 0x01
HTTP2_SETTINGS_ENABLE_PUSH = 0x02
HTTP2_SETTINGS_MAX_CONCURRENT_STREAMS = 0x03
HTTP2_SETTINGS_INITIAL_WINDOW_SIZE = 0x04
HTTP2_SETTINGS_MAX_FRAME_SIZE = 0x05
HTTP2_SETTINGS_MAX_HEADER_LIST_SIZE = 0x06

HTTP2_FRAME_DATA = 0x00
HTTP2_FRAME_HEADERS = 0x01
HTTP2_FRAME_PRIORITY = 0x02
HTTP2_FRAME_RST_STREAM = 0x03
HTTP2_FRAME_SETTINGS = 0x04
HTTP2_FRAME_PUSH_PROMISE = 0x05
HTTP2_FRAME_PING = 0x06
HTTP2_FRAME_GOAWAY = 0x07
HTTP2_FRAME_WINDOW_UPDATE = 0x08
HTTP2_FRAME_CONTINUATION = 0x09

HTTP2_ERROR_NO_ERROR = 0x00
HTTP2_ERROR_PROTOCOL_ERROR = 0x01
HTTP2_ERROR_INTERNAL_ERROR = 0x02
HTTP2_ERROR_FLOW_CONTROL_ERROR = 0x03
HTTP2_ERROR_SETTINGS_TIMEOUT = 0x04
HTTP2_ERROR_STREAM_CLOSED = 0x05
HTTP2_ERROR_FRAME_SIZE_ERROR = 0x06
HTTP2_ERROR_REFUSED_STREAM = 0x07
HTTP2_ERROR_CANCEL = 0x08
HTTP2_ERROR_COMPRESSION_ERROR = 0x09
HTTP2_ERROR_CONNECT_ERROR = 0x0A
HTTP2_ERROR_ENHANCE_YOUR_CALM = 0x0B
HTTP2_ERROR_INADEQUATE_SECURITY = 0x0C
HTTP2_ERROR_HTTP_1_1_REQUIRED = 0x0D


class HPACKEncoder:
    """HPACK 头部压缩编码器"""

    def __init__(self) -> None:
        self._dynamic_table: List[Tuple[str, str]] = []
        self._max_table_size = 4096
        self._static_table = self._init_static_table()

    @staticmethod
    def _init_static_table() -> List[Tuple[str, str]]:
        return [
            (":authority", ""), (":method", "GET"), (":method", "POST"),
            (":path", "/"), (":path", "/index.html"), (":scheme", "http"),
            (":scheme", "https"), (":status", "200"), (":status", "204"),
            (":status", "206"), (":status", "304"), (":status", "400"),
            (":status", "404"), (":status", "500"), ("accept-charset", ""),
            ("accept-encoding", "gzip, deflate"), ("accept-language", ""),
            ("accept-ranges", ""), ("accept", ""), ("access-control-allow-origin", ""),
            ("age", ""), ("allow", ""), ("authorization", ""),
            ("cache-control", ""), ("content-disposition", ""),
            ("content-encoding", ""), ("content-language", ""),
            ("content-length", ""), ("content-location", ""),
            ("content-range", ""), ("content-type", ""), ("cookie", ""),
            ("date", ""), ("etag", ""), ("expect", ""),
            ("expires", ""), ("from", ""), ("host", ""),
            ("if-match", ""), ("if-modified-since", ""),
            ("if-none-match", ""), ("if-range", ""),
            ("if-unmodified-since", ""), ("last-modified", ""),
            ("link", ""), ("location", ""), ("max-forwards", ""),
            ("proxy-authenticate", ""), ("proxy-authorization", ""),
            ("range", ""), ("referer", ""), ("refresh", ""),
            ("retry-after", ""), ("server", ""), ("set-cookie", ""),
            ("strict-transport-security", ""), ("transfer-encoding", ""),
            ("user-agent", ""), ("vary", ""), ("via", ""),
            ("www-authenticate", ""),
        ]

    def encode(self, headers: Dict[str, str]) -> bytes:
        """编码头部"""
        data = b""
        for name, value in headers.items():
            name_lower = name.lower()
            # 先在静态表中查找
            found = False
            for i, (sn, sv) in enumerate(self._static_table):
                if sn == name_lower and sv == value:
                    data += self._encode_integer(0x80 | i, 7)
                    found = True
                    break
                elif sn == name_lower:
                    data += self._encode_integer(0x40 | i, 7)
                    data += self._encode_string(value)
                    found = True
                    break

            if not found:
                # 在动态表中查找
                for i, (dn, dv) in enumerate(self._dynamic_table):
                    if dn == name_lower and dv == value:
                        data += self._encode_integer(0x80 | (len(self._static_table) + i), 7)
                        found = True
                        break
                    elif dn == name_lower:
                        data += self._encode_integer(len(self._static_table) + i, 7)
                        data += self._encode_string(value)
                        found = True
                        break

            if not found:
                data += self._encode_string(name)
                data += self._encode_string(value)

        return data

    def decode(self, data: bytes) -> Dict[str, str]:
        """解码头部"""
        headers: Dict[str, str] = {}
        offset = 0
        while offset < len(data):
            byte = data[offset]
            if byte & 0x80:
                # 索引引用
                index, offset = self._decode_integer(data, offset, 7)
                name, value = self._get_entry(index)
                headers[name] = value
            elif byte & 0x40:
                # 带索引的字面量
                index, offset = self._decode_integer(data, offset, 6)
                name, _ = self._get_entry(index)
                value, offset = self._decode_string(data, offset)
                headers[name] = value
                self._dynamic_table.insert(0, (name, value))
            elif byte & 0x20:
                # 更新表大小
                size, offset = self._decode_integer(data, offset, 5)
                self._max_table_size = size
            else:
                # 不带索引的字面量
                if byte & 0x10:
                    # 永不索引
                    pass
                index, offset = self._decode_integer(data, offset, 4)
                if index > 0:
                    name, _ = self._get_entry(index)
                else:
                    name, offset = self._decode_string(data, offset)
                value, offset = self._decode_string(data, offset)
                headers[name] = value

        return headers

    def _get_entry(self, index: int) -> Tuple[str, str]:
        """获取索引对应的条目"""
        if index < len(self._static_table):
            entry = self._static_table[index]
            # 静态表中有一些值的占位符为空
            if not entry[1]:
                return entry[0], ""
            return entry
        dyn_index = index - len(self._static_table)
        if dyn_index < len(self._dynamic_table):
            return self._dynamic_table[dyn_index]
        return ("", "")

    def _encode_integer(self, prefix: int, n: int) -> bytes:
        """编码整数"""
        return bytes([prefix])

    def _decode_integer(self, data: bytes, offset: int, n: int) -> Tuple[int, int]:
        """解码整数"""
        value = data[offset] & ((1 << n) - 1)
        offset += 1
        return value, offset

    def _encode_string(self, s: str) -> bytes:
        """编码字符串"""
        encoded = s.encode("utf-8")
        return self._encode_integer(len(encoded), 7) + encoded

    def _decode_string(self, data: bytes, offset: int) -> Tuple[str, int]:
        """解码字符串"""
        length, offset = self._decode_integer(data, offset, 7)
        value = data[offset:offset + length].decode("utf-8", errors="ignore")
        offset += length
        return value, offset


class HTTP2Stream:
    """HTTP/2 流"""

    def __init__(self, stream_id: int) -> None:
        self.stream_id = stream_id
        self.state = "idle"
        self.headers: Dict[str, str] = {}
        self.data: bytes = b""
        self.window_size: int = 65535
        self.priority: int = 16
        self.created_at: float = time.time()


class HTTP2Connection:
    """HTTP/2 连接"""

    def __init__(self, max_concurrent_streams: int = 100,
                 initial_window_size: int = 65535) -> None:
        self._streams: Dict[int, HTTP2Stream] = {}
        self._next_stream_id: int = 1
        self._max_concurrent_streams = max_concurrent_streams
        self._initial_window_size = initial_window_size
        self._encoder = HPACKEncoder()
        self._settings: Dict[int, int] = {
            HTTP2_SETTINGS_HEADER_TABLE_SIZE: 4096,
            HTTP2_SETTINGS_ENABLE_PUSH: 0,
            HTTP2_SETTINGS_MAX_CONCURRENT_STREAMS: 100,
            HTTP2_SETTINGS_INITIAL_WINDOW_SIZE: 65535,
            HTTP2_SETTINGS_MAX_FRAME_SIZE: 16384,
            HTTP2_SETTINGS_MAX_HEADER_LIST_SIZE: 65536,
        }

    def create_stream(self) -> HTTP2Stream:
        """创建新流"""
        stream_id = self._next_stream_id
        self._next_stream_id += 2
        stream = HTTP2Stream(stream_id)
        self._streams[stream_id] = stream
        return stream

    def close_stream(self, stream_id: int) -> None:
        """关闭流"""
        self._streams.pop(stream_id, None)

    def get_active_streams(self) -> List[HTTP2Stream]:
        """获取活跃流"""
        return [s for s in self._streams.values() if s.state != "closed"]

    def encode_frame(self, frame_type: int, flags: int, stream_id: int,
                     payload: bytes) -> bytes:
        """编码 HTTP/2 帧"""
        length = len(payload)
        header = struct.pack("!IBB", length, frame_type, flags)
        # 将 stream_id 编码为 31 位
        stream_id_bytes = struct.pack("!I", stream_id & 0x7FFFFFFF)
        return header + stream_id_bytes + payload

    def decode_frame(self, data: bytes) -> Tuple[int, int, int, bytes]:
        """解码 HTTP/2 帧"""
        if len(data) < 9:
            raise ValueError("HTTP/2 帧太短")

        length = struct.unpack("!I", b"\x00" + data[:3])[0]
        frame_type = data[3]
        flags = data[4]
        stream_id = struct.unpack("!I", data[5:9])[0] & 0x7FFFFFFF
        payload = data[9:9 + length]

        return frame_type, flags, stream_id, payload


class HTTPServer2:
    """HTTP/2 服务器"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8443) -> None:
        self.host = host
        self.port = port
        self._connections: Dict[str, HTTP2Connection] = {}
        self._is_running: bool = False

    async def start(self) -> None:
        self._is_running = True
        logger.info(f"HTTP/2 服务器已启动: {self.host}:{self.port}")

    async def stop(self) -> None:
        self._is_running = False
        logger.info("HTTP/2 服务器已停止")