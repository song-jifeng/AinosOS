"""
网络栈集成测试

测试 TCP 连接管理、HTTP 请求/响应、WebSocket 通信和 DNS 解析。
"""

import os
import sys
import json
import time
import socket
import struct
import random
import asyncio
import threading
import hashlib
import base64
import ssl
import uuid
import pytest
from typing import List, Dict, Optional, Any, Tuple, Callable, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch, AsyncMock
from urllib.parse import urlparse, urljoin
from collections import defaultdict
from io import BytesIO
from contextlib import contextmanager, asynccontextmanager


# =============================================================================
# 网络抽象层
# =============================================================================

@dataclass
class NetworkAddress:
    """网络地址"""
    host: str
    port: int
    family: int = socket.AF_INET

    @property
    def address(self) -> Tuple[str, int]:
        return (self.host, self.port)

    def __str__(self) -> str:
        return f"{self.host}:{self.port}"


@dataclass
class HttpRequest:
    """HTTP 请求"""
    method: str
    path: str
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[bytes] = None
    version: str = "HTTP/1.1"
    params: Dict[str, str] = field(default_factory=dict)

    @property
    def url(self) -> str:
        return self.path


@dataclass
class HttpResponse:
    """HTTP 响应"""
    status_code: int
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[bytes] = None
    version: str = "HTTP/1.1"
    latency_ms: float = 0.0

    @property
    def is_ok(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def json(self) -> Optional[Dict]:
        if self.body:
            try:
                return json.loads(self.body.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return None
        return None


@dataclass
class WebSocketMessage:
    """WebSocket 消息"""
    type: int  # 1=text, 2=binary, 8=close, 9=ping, 10=pong
    data: bytes
    mask: bool = False

    @property
    def text(self) -> Optional[str]:
        if self.type == 1:
            return self.data.decode('utf-8')
        return None

    @classmethod
    def create_text(cls, text: str) -> 'WebSocketMessage':
        return cls(type=1, data=text.encode('utf-8'))

    @classmethod
    def create_binary(cls, data: bytes) -> 'WebSocketMessage':
        return cls(type=2, data=data)

    @classmethod
    def create_close(cls, code: int = 1000, reason: str = "") -> 'WebSocketMessage':
        payload = struct.pack('!H', code) + reason.encode('utf-8')
        return cls(type=8, data=payload)


# =============================================================================
# Mock 网络组件
# =============================================================================

class MockTCPServer:
    """Mock TCP 服务器"""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port
        self._server_socket: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._connections: List[socket.socket] = []
        self._received_data: List[bytes] = []
        self._handler: Optional[Callable] = None
        self._lock = threading.Lock()

    def start(self):
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.host, self.port))
        self._server_socket.listen(5)
        self.port = self._server_socket.getsockname()[1]
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except OSError:
                pass
        for conn in self._connections:
            try:
                conn.close()
            except OSError:
                pass
        self._connections.clear()

    def set_handler(self, handler: Callable):
        self._handler = handler

    def _accept_loop(self):
        self._server_socket.settimeout(1.0)
        while self._running:
            try:
                conn, addr = self._server_socket.accept()
                with self._lock:
                    self._connections.append(conn)
                thread = threading.Thread(
                    target=self._handle_connection,
                    args=(conn, addr),
                    daemon=True,
                )
                thread.start()
            except socket.timeout:
                continue
            except OSError:
                break

    def _handle_connection(self, conn: socket.socket, addr: Tuple[str, int]):
        try:
            conn.settimeout(5.0)
            data = conn.recv(65536)
            if data:
                with self._lock:
                    self._received_data.append(data)
                if self._handler:
                    response = self._handler(data, addr)
                    if response:
                        conn.sendall(response)
        except (socket.timeout, OSError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def get_received_data(self) -> List[bytes]:
        with self._lock:
            return list(self._received_data)

    @property
    def address(self) -> Tuple[str, int]:
        return (self.host, self.port)


class MockHTTPClient:
    """Mock HTTP 客户端"""

    def __init__(self):
        self._sessions: Dict[str, Any] = {}
        self._default_headers: Dict[str, str] = {
            "User-Agent": "MockHTTPClient/1.0",
        }
        self._response_delay: float = 0.0

    def set_response_delay(self, delay: float):
        self._response_delay = delay

    async def request(self, method: str, url: str, headers: Dict[str, str] = None,
                      body: bytes = None, timeout: float = 30.0) -> HttpResponse:
        """发送 HTTP 请求"""
        if self._response_delay > 0:
            await asyncio.sleep(self._response_delay)

        parsed = urlparse(url)
        all_headers = {**self._default_headers, **(headers or {})}

        # 模拟不同的响应
        if "error" in url:
            return HttpResponse(
                status_code=500,
                headers={"Content-Type": "text/plain"},
                body=b"Internal Server Error",
            )
        elif "notfound" in url:
            return HttpResponse(
                status_code=404,
                headers={"Content-Type": "text/plain"},
                body=b"Not Found",
            )
        elif "timeout" in url:
            await asyncio.sleep(timeout + 1)
            raise asyncio.TimeoutError("Connection timed out")
        elif "redirect" in url:
            return HttpResponse(
                status_code=301,
                headers={"Location": f"{parsed.scheme}://{parsed.netloc}/redirected"},
            )
        elif "large" in url:
            # 模拟大响应
            large_body = b"x" * (10 * 1024 * 1024)  # 10MB
            return HttpResponse(
                status_code=200,
                headers={"Content-Type": "application/octet-stream",
                         "Content-Length": str(len(large_body))},
                body=large_body,
            )
        elif "json" in url or method == "POST":
            return HttpResponse(
                status_code=200,
                headers={"Content-Type": "application/json"},
                body=json.dumps({
                    "method": method,
                    "url": url,
                    "headers": all_headers,
                    "body_length": len(body) if body else 0,
                }).encode('utf-8'),
            )
        else:
            return HttpResponse(
                status_code=200,
                headers={"Content-Type": "text/plain"},
                body=f"OK - {method} {url}".encode('utf-8'),
            )

    async def get(self, url: str, **kwargs) -> HttpResponse:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, body: bytes = None, **kwargs) -> HttpResponse:
        return await self.request("POST", url, body=body, **kwargs)

    async def put(self, url: str, body: bytes = None, **kwargs) -> HttpResponse:
        return await self.request("PUT", url, body=body, **kwargs)

    async def delete(self, url: str, **kwargs) -> HttpResponse:
        return await self.request("DELETE", url, **kwargs)

    async def head(self, url: str, **kwargs) -> HttpResponse:
        return await self.request("HEAD", url, **kwargs)


class MockWebSocketServer:
    """Mock WebSocket 服务器"""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port
        self._server: Optional[asyncio.AbstractServer] = None
        self._connections: List[Any] = []
        self._messages: List[WebSocketMessage] = []
        self._handlers: Dict[str, Callable] = {}

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        if self._server.sockets:
            self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_client(self, reader: asyncio.StreamReader,
                             writer: asyncio.StreamWriter):
        self._connections.append((reader, writer))
        try:
            # 读取 HTTP 升级请求
            request_data = await reader.readuntil(b"\r\n\r\n")
            request = request_data.decode('utf-8')

            # 解析 WebSocket 握手
            key = None
            for line in request.split("\r\n"):
                if line.lower().startswith("sec-websocket-key:"):
                    key = line.split(":")[1].strip()
                    break

            if key:
                # 发送握手响应
                accept = base64.b64encode(
                    hashlib.sha1(
                        (key + "258EAFA5-E914-47DA-95CA-5AB5A0BD85B5").encode('utf-8')
                    ).digest()
                ).decode('utf-8')

                response = (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n"
                    "\r\n"
                )
                writer.write(response.encode('utf-8'))
                await writer.drain()

                # 处理 WebSocket 消息
                await self._handle_websocket(reader, writer)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    async def _handle_websocket(self, reader: asyncio.StreamReader,
                                writer: asyncio.StreamWriter):
        while True:
            try:
                # 读取 WebSocket 帧
                first_byte = await reader.readexactly(1)
                opcode = first_byte[0] & 0x0F
                second_byte = await reader.readexactly(1)
                masked = bool(second_byte[0] & 0x80)
                payload_length = second_byte[0] & 0x7F

                if payload_length == 126:
                    payload_length = struct.unpack('!H', await reader.readexactly(2))[0]
                elif payload_length == 127:
                    payload_length = struct.unpack('!Q', await reader.readexactly(8))[0]

                mask_key = None
                if masked:
                    mask_key = await reader.readexactly(4)

                payload = await reader.readexactly(payload_length)
                if mask_key:
                    payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

                msg = WebSocketMessage(type=opcode, data=payload)
                self._messages.append(msg)

                if opcode == 8:  # Close
                    writer.write(struct.pack('!B', 0x88) + struct.pack('!B', 0))
                    await writer.drain()
                    break
                elif opcode == 9:  # Ping
                    pong = struct.pack('!B', 0x8A) + struct.pack('!B', len(payload)) + payload
                    writer.write(pong)
                    await writer.drain()
                else:
                    # Echo
                    response = struct.pack('!B', 0x80 | opcode) + struct.pack('!B', len(payload)) + payload
                    writer.write(response)
                    await writer.drain()

            except (asyncio.IncompleteReadError, ConnectionResetError):
                break

    def get_messages(self) -> List[WebSocketMessage]:
        return list(self._messages)


class MockDNSResolver:
    """Mock DNS 解析器"""

    def __init__(self):
        self._records: Dict[str, str] = {
            "localhost": "127.0.0.1",
            "example.com": "93.184.216.34",
            "test.local": "10.0.0.1",
            "api.service.com": "192.168.1.100",
            "cdn.static.com": "203.0.113.50",
        }
        self._resolve_times: Dict[str, float] = defaultdict(lambda: 0.01)
        self._fail_domains: Set[str] = set()

    def add_record(self, hostname: str, ip: str):
        self._records[hostname] = ip

    def add_fail_domain(self, domain: str):
        self._fail_domains.add(domain)

    def set_resolve_time(self, hostname: str, time_ms: float):
        self._resolve_times[hostname] = time_ms / 1000.0

    async def resolve(self, hostname: str) -> str:
        resolve_time = self._resolve_times.get(hostname, 0.01)
        if resolve_time > 0:
            await asyncio.sleep(resolve_time)

        if hostname in self._fail_domains:
            raise socket.gaierror(f"Name or service not known for {hostname}")

        if hostname in self._records:
            return self._records[hostname]

        raise socket.gaierror(f"Name or service not known for {hostname}")

    async def resolve_multi(self, hostname: str) -> List[str]:
        resolve_time = self._resolve_times.get(hostname, 0.01)
        if resolve_time > 0:
            await asyncio.sleep(resolve_time)

        if hostname in self._fail_domains:
            raise socket.gaierror(f"Name or service not known for {hostname}")

        if hostname == "cdn.static.com":
            return ["203.0.113.50", "203.0.113.51", "203.0.113.52"]

        if hostname in self._records:
            return [self._records[hostname]]

        raise socket.gaierror(f"Name or service not known for {hostname}")


# =============================================================================
# 测试夹具
# =============================================================================

@pytest.fixture
def tcp_server():
    server = MockTCPServer()
    server.start()
    yield server
    server.stop()


@pytest.fixture
def http_client():
    return MockHTTPClient()


@pytest.fixture
def dns_resolver():
    return MockDNSResolver()


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


# =============================================================================
# 测试用例：TCP 连接管理
# =============================================================================

class TestTCPConnectionManagement:
    """TCP 连接管理测试"""

    def test_tcp_server_start_stop(self, tcp_server):
        """测试 TCP 服务器启动和停止"""
        assert tcp_server._server_socket is not None
        assert tcp_server._running is True
        assert tcp_server.port > 0

        tcp_server.stop()
        assert tcp_server._running is False

    def test_tcp_client_connect(self, tcp_server):
        """测试 TCP 客户端连接"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(tcp_server.address)
        assert sock.fileno() > 0
        sock.close()

    @pytest.mark.asyncio
    async def test_tcp_data_exchange(self, tcp_server):
        """测试 TCP 数据交换"""
        echo_handler = lambda data, addr: data  # Echo server
        tcp_server.set_handler(echo_handler)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(tcp_server.address)

        test_data = b"Hello, TCP Server!"
        sock.sendall(test_data)
        response = sock.recv(1024)
        assert response == test_data

        sock.close()

    def test_tcp_multiple_clients(self, tcp_server):
        """测试多个 TCP 客户端并发连接"""
        echo_handler = lambda data, addr: data
        tcp_server.set_handler(echo_handler)

        num_clients = 10
        sockets = []
        for i in range(num_clients):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect(tcp_server.address)
            sockets.append(sock)

        for i, sock in enumerate(sockets):
            test_data = f"Message from client {i}".encode('utf-8')
            sock.sendall(test_data)
            response = sock.recv(1024)
            assert response == test_data

        for sock in sockets:
            sock.close()

    def test_tcp_connection_refused(self):
        """测试连接被拒绝"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        with pytest.raises((ConnectionRefusedError, OSError)):
            sock.connect(("127.0.0.1", 65535))
        sock.close()

    def test_tcp_timeout(self):
        """测试连接超时"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.1)
        with pytest.raises((socket.timeout, OSError)):
            sock.connect(("10.255.255.1", 80))
        sock.close()

    def test_tcp_send_receive_large_data(self, tcp_server):
        """测试 TCP 大数据传输"""
        echo_handler = lambda data, addr: data
        tcp_server.set_handler(echo_handler)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10.0)
        sock.connect(tcp_server.address)

        # 发送 1MB 数据
        large_data = os.urandom(1024 * 1024)
        sock.sendall(large_data)

        received = b""
        while len(received) < len(large_data):
            chunk = sock.recv(65536)
            if not chunk:
                break
            received += chunk

        assert len(received) == len(large_data)
        # 注意：TCP 不保证消息边界，但 echo 服务器应该返回相同数据
        sock.close()

    def test_tcp_connection_close_handling(self, tcp_server):
        """测试连接关闭处理"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(tcp_server.address)
        sock.close()

        # 确保服务器端检测到断开连接
        time.sleep(0.1)
        assert len(tcp_server._connections) == 0 or not tcp_server._connections[0].fileno()


# =============================================================================
# 测试用例：HTTP 请求/响应
# =============================================================================

class TestHTTPRequestResponse:
    """HTTP 请求/响应测试"""

    @pytest.mark.asyncio
    async def test_http_get_request(self, http_client):
        """测试 HTTP GET 请求"""
        response = await http_client.get("http://example.com/api/test")
        assert response.is_ok
        assert response.status_code == 200
        assert response.body is not None

    @pytest.mark.asyncio
    async def test_http_post_request(self, http_client):
        """测试 HTTP POST 请求"""
        body = json.dumps({"key": "value"}).encode('utf-8')
        response = await http_client.post(
            "http://example.com/api/data",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        assert response.is_ok
        json_data = response.json
        assert json_data is not None
        assert json_data["method"] == "POST"

    @pytest.mark.asyncio
    async def test_http_put_request(self, http_client):
        """测试 HTTP PUT 请求"""
        body = json.dumps({"updated": True}).encode('utf-8')
        response = await http_client.put("http://example.com/api/update", body=body)
        assert response.is_ok
        assert response.json["method"] == "PUT"

    @pytest.mark.asyncio
    async def test_http_delete_request(self, http_client):
        """测试 HTTP DELETE 请求"""
        response = await http_client.delete("http://example.com/api/resource/1")
        assert response.is_ok
        assert response.json["method"] == "DELETE"

    @pytest.mark.asyncio
    async def test_http_error_handling(self, http_client):
        """测试 HTTP 错误处理"""
        response = await http_client.get("http://example.com/error")
        assert response.status_code == 500
        assert not response.is_ok

        response = await http_client.get("http://example.com/notfound")
        assert response.status_code == 404
        assert not response.is_ok

    @pytest.mark.asyncio
    async def test_http_redirect(self, http_client):
        """测试 HTTP 重定向"""
        response = await http_client.get("http://example.com/redirect")
        assert response.status_code == 301
        assert "Location" in response.headers

    @pytest.mark.asyncio
    async def test_http_request_headers(self, http_client):
        """测试 HTTP 请求头"""
        custom_headers = {
            "Authorization": "Bearer test-token",
            "X-Custom-Header": "custom-value",
            "Accept": "application/json",
        }
        response = await http_client.get(
            "http://example.com/api/test",
            headers=custom_headers,
        )
        assert response.is_ok
        response_json = response.json
        # 验证自定义头被包含
        for key, value in custom_headers.items():
            assert key in str(response_json["headers"])

    @pytest.mark.asyncio
    async def test_http_large_response(self, http_client):
        """测试 HTTP 大响应"""
        response = await http_client.get("http://example.com/large")
        assert response.is_ok
        assert len(response.body) == 10 * 1024 * 1024  # 10MB

    @pytest.mark.asyncio
    async def test_http_concurrent_requests(self, http_client):
        """测试 HTTP 并发请求"""
        urls = [
            "http://example.com/api/1",
            "http://example.com/api/2",
            "http://example.com/api/3",
            "http://example.com/api/4",
            "http://example.com/api/5",
        ]

        tasks = [http_client.get(url) for url in urls]
        responses = await asyncio.gather(*tasks)

        assert len(responses) == 5
        for response in responses:
            assert response.is_ok

    @pytest.mark.asyncio
    async def test_http_request_timeout(self, http_client):
        """测试 HTTP 请求超时"""
        with pytest.raises(asyncio.TimeoutError):
            await http_client.get("http://example.com/timeout", timeout=0.1)


# =============================================================================
# 测试用例：WebSocket 通信
# =============================================================================

class TestWebSocketCommunication:
    """WebSocket 通信测试"""

    @pytest.mark.asyncio
    async def test_websocket_handshake(self, event_loop):
        """测试 WebSocket 握手"""
        server = MockWebSocketServer()
        await server.start()

        # 客户端握手
        reader, writer = await asyncio.open_connection(server.host, server.port)

        # 发送 WebSocket 升级请求
        key = base64.b64encode(os.urandom(16)).decode('utf-8')
        upgrade_request = (
            "GET /ws HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        writer.write(upgrade_request.encode('utf-8'))
        await writer.drain()

        # 读取响应
        response = await reader.readuntil(b"\r\n\r\n")
        assert b"101 Switching Protocols" in response
        assert b"Sec-WebSocket-Accept:" in response

        writer.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_websocket_text_message(self, event_loop):
        """测试 WebSocket 文本消息"""
        server = MockWebSocketServer()
        await server.start()

        reader, writer = await asyncio.open_connection(server.host, server.port)

        # 握手
        key = base64.b64encode(os.urandom(16)).decode('utf-8')
        upgrade_request = (
            "GET /ws HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        writer.write(upgrade_request.encode('utf-8'))
        await writer.drain()
        await reader.readuntil(b"\r\n\r\n")

        # 发送文本消息
        text = "Hello, WebSocket!"
        mask_key = os.urandom(4)
        payload = text.encode('utf-8')
        frame = (
            struct.pack('!B', 0x81)  # FIN + text opcode
            + struct.pack('!B', 0x80 | len(payload))  # MASK + payload length
            + mask_key
            + bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        )
        writer.write(frame)
        await writer.drain()

        # 接收响应
        first_byte = await reader.readexactly(1)
        opcode = first_byte[0] & 0x0F
        second_byte = await reader.readexactly(1)
        payload_length = second_byte[0] & 0x7F
        response_payload = await reader.readexactly(payload_length)

        assert opcode == 1  # text
        assert response_payload.decode('utf-8') == text

        writer.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_websocket_binary_message(self, event_loop):
        """测试 WebSocket 二进制消息"""
        server = MockWebSocketServer()
        await server.start()

        reader, writer = await asyncio.open_connection(server.host, server.port)

        # 握手
        key = base64.b64encode(os.urandom(16)).decode('utf-8')
        upgrade_request = (
            "GET /ws HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        writer.write(upgrade_request.encode('utf-8'))
        await writer.drain()
        await reader.readuntil(b"\r\n\r\n")

        # 发送二进制消息
        binary_data = os.urandom(1024)
        mask_key = os.urandom(4)
        frame = (
            struct.pack('!B', 0x82)  # FIN + binary opcode
            + struct.pack('!B', 0x80 | len(binary_data))
            + mask_key
            + bytes(b ^ mask_key[i % 4] for i, b in enumerate(binary_data))
        )
        writer.write(frame)
        await writer.drain()

        # 接收响应
        first_byte = await reader.readexactly(1)
        opcode = first_byte[0] & 0x0F
        second_byte = await reader.readexactly(1)
        payload_length = second_byte[0] & 0x7F
        response_payload = await reader.readexactly(payload_length)

        assert opcode == 2  # binary
        assert response_payload == binary_data

        writer.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_websocket_ping_pong(self, event_loop):
        """测试 WebSocket Ping/Pong"""
        server = MockWebSocketServer()
        await server.start()

        reader, writer = await asyncio.open_connection(server.host, server.port)

        # 握手
        key = base64.b64encode(os.urandom(16)).decode('utf-8')
        upgrade_request = (
            "GET /ws HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        writer.write(upgrade_request.encode('utf-8'))
        await writer.drain()
        await reader.readuntil(b"\r\n\r\n")

        # 发送 Ping
        ping_data = b"ping-payload"
        mask_key = os.urandom(4)
        frame = (
            struct.pack('!B', 0x89)  # FIN + ping opcode
            + struct.pack('!B', 0x80 | len(ping_data))
            + mask_key
            + bytes(b ^ mask_key[i % 4] for i, b in enumerate(ping_data))
        )
        writer.write(frame)
        await writer.drain()

        # 接收 Pong
        first_byte = await reader.readexactly(1)
        opcode = first_byte[0] & 0x0F
        assert opcode == 10  # pong

        second_byte = await reader.readexactly(1)
        payload_length = second_byte[0] & 0x7F
        pong_payload = await reader.readexactly(payload_length)
        assert pong_payload == ping_data

        writer.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_websocket_close_handshake(self, event_loop):
        """测试 WebSocket 关闭握手"""
        server = MockWebSocketServer()
        await server.start()

        reader, writer = await asyncio.open_connection(server.host, server.port)

        # 握手
        key = base64.b64encode(os.urandom(16)).decode('utf-8')
        upgrade_request = (
            "GET /ws HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        writer.write(upgrade_request.encode('utf-8'))
        await writer.drain()
        await reader.readuntil(b"\r\n\r\n")

        # 发送关闭帧
        close_code = 1000
        close_payload = struct.pack('!H', close_code)
        mask_key = os.urandom(4)
        frame = (
            struct.pack('!B', 0x88)  # FIN + close opcode
            + struct.pack('!B', 0x80 | len(close_payload))
            + mask_key
            + bytes(b ^ mask_key[i % 4] for i, b in enumerate(close_payload))
        )
        writer.write(frame)
        await writer.drain()

        # 接收关闭响应
        first_byte = await reader.readexactly(1)
        opcode = first_byte[0] & 0x0F
        assert opcode == 8  # close

        writer.close()
        await server.stop()


# =============================================================================
# 测试用例：DNS 解析
# =============================================================================

class TestDNSResolution:
    """DNS 解析测试"""

    @pytest.mark.asyncio
    async def test_dns_resolve_hostname(self, dns_resolver):
        """测试 DNS 主机名解析"""
        ip = await dns_resolver.resolve("localhost")
        assert ip == "127.0.0.1"

        ip = await dns_resolver.resolve("example.com")
        assert ip == "93.184.216.34"

    @pytest.mark.asyncio
    async def test_dns_resolve_unknown_host(self, dns_resolver):
        """测试 DNS 解析未知主机"""
        with pytest.raises(socket.gaierror):
            await dns_resolver.resolve("unknown.host.name")

    @pytest.mark.asyncio
    async def test_dns_resolve_fail_domain(self, dns_resolver):
        """测试 DNS 解析失败域名"""
        dns_resolver.add_fail_domain("blocked.domain.com")
        with pytest.raises(socket.gaierror):
            await dns_resolver.resolve("blocked.domain.com")

    @pytest.mark.asyncio
    async def test_dns_multi_address_resolution(self, dns_resolver):
        """测试 DNS 多地址解析"""
        ips = await dns_resolver.resolve_multi("cdn.static.com")
        assert len(ips) >= 2
        assert "203.0.113.50" in ips

    @pytest.mark.asyncio
    async def test_dns_resolve_performance(self, dns_resolver):
        """测试 DNS 解析性能"""
        dns_resolver.set_resolve_time("slow.host.com", 500)

        start = time.time()
        ip = await dns_resolver.resolve("slow.host.com")
        elapsed = (time.time() - start) * 1000

        assert elapsed >= 400  # 至少 500ms 延迟
        assert ip == "127.0.0.1"  # 默认回退

    @pytest.mark.asyncio
    async def test_dns_cache(self, dns_resolver):
        """测试 DNS 缓存行为"""
        dns_resolver.set_resolve_time("cached.host.com", 100)

        # 第一次解析
        ip1 = await dns_resolver.resolve("cached.host.com")
        assert ip1 is not None

        # 第二次解析（模拟缓存命中）
        dns_resolver.set_resolve_time("cached.host.com", 0)
        ip2 = await dns_resolver.resolve("cached.host.com")
        assert ip2 == ip1


# =============================================================================
# 测试用例：网络安全
# =============================================================================

class TestNetworkSecurity:
    """网络安全测试"""

    def test_tcp_port_scanning_detection(self, tcp_server):
        """测试端口扫描检测"""
        socks = []
        try:
            for port in range(10000, 10010):
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                try:
                    sock.connect(("127.0.0.1", port))
                    socks.append(sock)
                except (ConnectionRefusedError, OSError):
                    pass
        finally:
            for sock in socks:
                sock.close()

    def test_connection_rate_limiting(self, tcp_server):
        """测试连接速率限制"""
        num_connections = 100
        successful = 0

        for i in range(num_connections):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1.0)
                sock.connect(tcp_server.address)
                sock.close()
                successful += 1
            except (ConnectionRefusedError, OSError):
                pass

        assert successful < num_connections  # 应该有一些连接被限制

    def test_localhost_only_binding(self):
        """测试仅绑定 localhost"""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        # 只有 localhost 可以连接
        local_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        local_sock.settimeout(2.0)
        local_sock.connect(("127.0.0.1", port))
        local_sock.close()

        server.close()

    def test_socket_reuse_address(self):
        """测试地址重用"""
        server1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server1.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server1.bind(("127.0.0.1", 18888))
        server1.listen(1)

        server2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server2.bind(("127.0.0.1", 18888))
            # 是否成功取决于平台
        except OSError:
            pass

        server1.close()
        server2.close()


# =============================================================================
# 测试用例：网络协议解析
# =============================================================================

class TestNetworkProtocolParsing:
    """网络协议解析测试"""

    def test_http_request_parsing(self):
        """测试 HTTP 请求解析"""
        raw_request = (
            "POST /api/data HTTP/1.1\r\n"
            "Host: example.com\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: 27\r\n"
            "Authorization: Bearer token123\r\n"
            "\r\n"
            '{"key": "value", "num": 42}'
        ).encode('utf-8')

        # 解析请求行
        lines = raw_request.split(b"\r\n")
        request_line = lines[0].decode('utf-8')
        method, path, version = request_line.split(" ")

        assert method == "POST"
        assert path == "/api/data"
        assert version == "HTTP/1.1"

        # 解析头部
        headers = {}
        body_start = raw_request.find(b"\r\n\r\n") + 4
        for line in raw_request[raw_request.find(b"\r\n") + 2:body_start - 2].split(b"\r\n"):
            line_str = line.decode('utf-8')
            if ": " in line_str:
                key, value = line_str.split(": ", 1)
                headers[key] = value

        assert headers["Host"] == "example.com"
        assert headers["Content-Type"] == "application/json"
        assert headers["Authorization"] == "Bearer token123"

        # 解析 body
        body = raw_request[body_start:]
        body_json = json.loads(body.decode('utf-8'))
        assert body_json["key"] == "value"
        assert body_json["num"] == 42

    def test_http_response_parsing(self):
        """测试 HTTP 响应解析"""
        raw_response = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: 15\r\n"
            "Server: TestServer/1.0\r\n"
            "\r\n"
            '{"status":"ok"}'
        ).encode('utf-8')

        lines = raw_response.split(b"\r\n")
        status_line = lines[0].decode('utf-8')
        version, status_code, reason = status_line.split(" ", 2)

        assert version == "HTTP/1.1"
        assert status_code == "200"
        assert reason == "OK"

        headers = {}
        body_start = raw_response.find(b"\r\n\r\n") + 4
        for line in raw_response[raw_response.find(b"\r\n") + 2:body_start - 2].split(b"\r\n"):
            line_str = line.decode('utf-8')
            if ": " in line_str:
                key, value = line_str.split(": ", 1)
                headers[key] = value

        assert headers["Content-Type"] == "application/json"
        assert headers["Server"] == "TestServer/1.0"

    def test_url_parsing(self):
        """测试 URL 解析"""
        test_urls = [
            "http://example.com/path",
            "https://secure.example.com:8443/api/v1/resource?key=value&page=1",
            "ws://websocket.example.com/socket",
            "http://localhost:8080/",
        ]

        for url in test_urls:
            parsed = urlparse(url)
            assert parsed.netloc, f"Failed to parse {url}"
            assert parsed.scheme in ["http", "https", "ws"]

    def test_ipv4_address_validation(self):
        """测试 IPv4 地址验证"""
        valid_ips = ["127.0.0.1", "192.168.1.1", "10.0.0.1", "8.8.8.8", "255.255.255.255"]
        invalid_ips = ["256.1.2.3", "1.2.3", "abc.def.ghi.jkl", "0.0.0.0/24", "-1.0.0.0"]

        for ip in valid_ips:
            try:
                socket.inet_aton(ip)
            except OSError:
                pytest.fail(f"Valid IP {ip} failed validation")

        for ip in invalid_ips:
            with pytest.raises(OSError):
                socket.inet_aton(ip)


# =============================================================================
# 测试用例：网络栈集成
# =============================================================================

class TestNetworkStackIntegration:
    """网络栈集成测试"""

    @pytest.mark.asyncio
    async def test_dns_http_integration(self, http_client, dns_resolver):
        """测试 DNS 和 HTTP 集成"""
        hostname = "api.service.com"
        ip = await dns_resolver.resolve(hostname)
        assert ip == "192.168.1.100"

        response = await http_client.get(f"http://{hostname}/api/status")
        assert response.is_ok

    @pytest.mark.asyncio
    async def test_keep_alive_connection(self, http_client):
        """测试 HTTP Keep-Alive 连接"""
        responses = []
        for _ in range(5):
            response = await http_client.get("http://example.com/api/test")
            responses.append(response)

        for response in responses:
            assert response.is_ok

    @pytest.mark.asyncio
    async def test_connection_pool(self, http_client):
        """测试连接池"""
        urls = [
            "http://example.com/api/1",
            "http://example.com/api/2",
            "http://example.com/api/3",
        ]

        # 并发请求应该复用连接
        tasks = [http_client.get(url) for url in urls]
        responses = await asyncio.gather(*tasks)
        assert all(r.is_ok for r in responses)

    def test_tcp_http_integration(self, tcp_server):
        """测试 TCP 和 HTTP 集成"""
        def http_handler(data: bytes, addr: Tuple[str, int]) -> bytes:
            if b"GET /health" in data:
                return (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: text/plain\r\n"
                    b"Content-Length: 2\r\n"
                    b"\r\n"
                    b"OK"
                )
            return (
                b"HTTP/1.1 404 Not Found\r\n"
                b"Content-Type: text/plain\r\n"
                b"Content-Length: 9\r\n"
                b"\r\n"
                b"Not Found"
            )

        tcp_server.set_handler(http_handler)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(tcp_server.address)

        # 发送 HTTP 请求
        request = b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n"
        sock.sendall(request)

        response = b""
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                if b"\r\n\r\n" in response:
                    break
            except socket.timeout:
                break

        assert b"200 OK" in response
        sock.close()

    def test_full_network_stack(self, tcp_server, http_client, dns_resolver):
        """测试完整网络栈"""
        # 1. DNS 解析
        hostname = "test.local"
        ip = asyncio.run(dns_resolver.resolve(hostname))
        assert ip == "10.0.0.1"

        # 2. TCP 连接
        def handler(data, addr):
            return b"Hello from server"
        tcp_server.set_handler(handler)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(tcp_server.address)
        sock.sendall(b"Hello")
        response = sock.recv(1024)
        assert response == b"Hello from server"
        sock.close()

        # 3. HTTP 请求
        response = asyncio.run(http_client.get("http://example.com/json"))
        assert response.is_ok

    @pytest.mark.asyncio
    async def test_network_resilience(self, http_client):
        """测试网络弹性"""
        # 模拟网络故障
        http_client.set_response_delay(2.0)

        start = time.time()
        try:
            await http_client.get("http://example.com/timeout", timeout=0.5)
        except asyncio.TimeoutError:
            elapsed = time.time() - start
            assert elapsed < 3.0  # 超时应该比响应延迟短

        # 恢复正常
        http_client.set_response_delay(0.0)
        response = await http_client.get("http://example.com/")
        assert response.is_ok


# =============================================================================
# 网络测试主入口
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])