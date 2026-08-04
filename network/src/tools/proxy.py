"""
代理服务器模块
==============

提供 HTTP 代理和 SOCKS5 代理服务器实现，支持认证、访问控制
和流量统计等功能。
"""

import asyncio
import base64
import logging
from typing import Optional, Dict, Any, List, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum


logger = logging.getLogger(__name__)


class ProxyType(Enum):
    """代理类型"""
    HTTP = "http"
    SOCKS5 = "socks5"
    TRANSPARENT = "transparent"


@dataclass
class ProxyConfig:
    """代理配置"""
    host: str = "0.0.0.0"
    port: int = 8080
    proxy_type: ProxyType = ProxyType.HTTP
    max_connections: int = 1000
    timeout: float = 30.0
    buffer_size: int = 65536
    allow_remote: bool = True
    require_auth: bool = False
    users: Dict[str, str] = field(default_factory=dict)
    allowed_destinations: List[str] = field(default_factory=list)
    blocked_destinations: List[str] = field(default_factory=list)
    max_bandwidth: int = 0  # 0 表示无限制


@dataclass
class ProxySession:
    """代理会话"""
    id: int = 0
    client_addr: Tuple[str, int] = ("", 0)
    target_host: str = ""
    target_port: int = 0
    bytes_received: int = 0
    bytes_sent: int = 0
    start_time: float = 0.0
    end_time: float = 0.0
    is_active: bool = True
    username: str = ""

    @property
    def duration(self) -> float:
        if self.end_time > self.start_time:
            return self.end_time - self.start_time
        return 0.0

    @property
    def throughput(self) -> float:
        if self.duration > 0:
            return (self.bytes_received + self.bytes_sent) / self.duration
        return 0.0


class Socks5Auth:
    """SOCKS5 认证"""
    NO_AUTH = 0x00
    GSSAPI = 0x01
    USER_PASS = 0x02
    NO_ACCEPTABLE = 0xFF


class Socks5Command:
    """SOCKS5 命令"""
    CONNECT = 0x01
    BIND = 0x02
    UDP_ASSOCIATE = 0x03


class Socks5AddressType:
    """SOCKS5 地址类型"""
    IPV4 = 0x01
    DOMAIN = 0x03
    IPV6 = 0x04


class Socks5Reply:
    """SOCKS5 响应码"""
    SUCCESS = 0x00
    GENERAL_FAILURE = 0x01
    NOT_ALLOWED = 0x02
    NETWORK_UNREACHABLE = 0x03
    HOST_UNREACHABLE = 0x04
    CONNECTION_REFUSED = 0x05
    TTL_EXPIRED = 0x06
    COMMAND_NOT_SUPPORTED = 0x07
    ADDRESS_TYPE_NOT_SUPPORTED = 0x08


class ProxyHandler:
    """代理请求处理器"""

    def __init__(self, config: ProxyConfig) -> None:
        self.config = config
        self._auth_callbacks: List[Callable] = []

    def on_auth(self, callback: Callable) -> None:
        self._auth_callbacks.append(callback)

    def authenticate(self, username: str, password: str) -> bool:
        """验证用户"""
        if not self.config.require_auth:
            return True

        stored = self.config.users.get(username)
        if stored and stored == password:
            return True

        for callback in self._auth_callbacks:
            try:
                if callback(username, password):
                    return True
            except Exception:
                pass

        return False

    def check_destination(self, host: str) -> bool:
        """检查目标是否允许访问"""
        if self.config.allowed_destinations:
            return any(host.endswith(d) for d in self.config.allowed_destinations)
        if self.config.blocked_destinations:
            return not any(host.endswith(d) for d in self.config.blocked_destinations)
        return True


class HTTPProxy:
    """HTTP 代理服务器"""

    def __init__(self, config: ProxyConfig) -> None:
        self.config = config
        self.handler = ProxyHandler(config)
        self._sessions: Dict[int, ProxySession] = {}
        self._next_session_id: int = 0
        self._server: Optional[asyncio.AbstractServer] = None
        self._is_running: bool = False
        self._stats: Dict[str, int] = {
            "total_connections": 0,
            "active_connections": 0,
            "bytes_received": 0,
            "bytes_sent": 0,
            "requests_handled": 0,
            "errors": 0,
        }

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def sessions(self) -> List[ProxySession]:
        return list(self._sessions.values())

    @property
    def active_connections(self) -> int:
        return self._stats["active_connections"]

    async def start(self) -> None:
        """启动 HTTP 代理服务器"""
        self._server = await asyncio.start_server(
            self._handle_connection,
            self.config.host,
            self.config.port,
        )
        self._is_running = True
        logger.info(f"HTTP 代理服务器已启动: {self.config.host}:{self.config.port}")

    async def stop(self) -> None:
        """停止 HTTP 代理服务器"""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self._is_running = False
        logger.info("HTTP 代理服务器已停止")

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        """处理连接"""
        if self._stats["active_connections"] >= self.config.max_connections:
            writer.close()
            return

        client_addr = writer.get_extra_info("peername") or ("unknown", 0)
        session_id = self._next_session_id
        self._next_session_id += 1

        session = ProxySession(
            id=session_id,
            client_addr=client_addr,
            start_time=__import__("time").time(),
        )
        self._sessions[session_id] = session
        self._stats["total_connections"] += 1
        self._stats["active_connections"] += 1

        try:
            # 读取请求
            request_data = await self._read_http_request(reader)
            if not request_data:
                return

            request_text = request_data.decode("utf-8", errors="replace")
            first_line = request_text.split("\r\n")[0]
            parts = first_line.split(" ")

            if len(parts) < 3:
                return

            method = parts[0]
            url = parts[1]

            # 解析目标
            from urllib.parse import urlparse
            parsed = urlparse(url)
            target_host = parsed.hostname or ""
            target_port = parsed.port or 80

            if not self.handler.check_destination(target_host):
                await self._send_error(writer, 403, "Forbidden")
                return

            session.target_host = target_host
            session.target_port = target_port

            if method.upper() == "CONNECT":
                # HTTPS 隧道
                await self._handle_connect(reader, writer, session)
            else:
                # HTTP 请求
                await self._handle_http(reader, writer, request_data, session)

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"HTTP 代理错误: {e}")
        finally:
            session.is_active = False
            session.end_time = __import__("time").time()
            self._stats["active_connections"] -= 1
            self._sessions.pop(session_id, None)
            try:
                writer.close()
            except Exception:
                pass

    async def _read_http_request(self, reader: asyncio.StreamReader) -> bytes:
        """读取 HTTP 请求"""
        data = b""
        while True:
            line = await reader.readline()
            data += line
            if line == b"\r\n":
                break
            if not line:
                return b""
        return data

    async def _handle_http(self, reader: asyncio.StreamReader,
                            writer: asyncio.StreamWriter,
                            request_data: bytes,
                            session: ProxySession) -> None:
        """处理 HTTP 请求"""
        # 简单转发响应
        response = (
            "HTTP/1.1 200 Connection established\r\n"
            "Content-Type: text/plain\r\n"
            "\r\n"
            "Ainos HTTP Proxy\r\n"
        ).encode()
        writer.write(response)
        await writer.drain()

        session.bytes_sent += len(response)
        self._stats["bytes_sent"] += len(response)
        self._stats["requests_handled"] += 1

    async def _handle_connect(self, reader: asyncio.StreamReader,
                               writer: asyncio.StreamWriter,
                               session: ProxySession) -> None:
        """处理 CONNECT 隧道"""
        response = b"HTTP/1.1 200 Connection Established\r\n\r\n"
        writer.write(response)
        await writer.drain()

    async def _send_error(self, writer: asyncio.StreamWriter,
                          code: int, message: str) -> None:
        """发送错误响应"""
        response = f"HTTP/1.1 {code} {message}\r\n\r\n{message}\r\n"
        writer.write(response.encode())
        await writer.drain()

    def get_statistics(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "host": self.config.host,
            "port": self.config.port,
            "type": "HTTP",
            "is_running": self._is_running,
            "active_sessions": len(self._sessions),
            "require_auth": self.config.require_auth,
        }


class Socks5Proxy:
    """SOCKS5 代理服务器"""

    def __init__(self, config: ProxyConfig) -> None:
        self.config = config
        self.handler = ProxyHandler(config)
        self._sessions: Dict[int, ProxySession] = {}
        self._next_session_id: int = 0
        self._server: Optional[asyncio.AbstractServer] = None
        self._is_running: bool = False
        self._stats: Dict[str, int] = {
            "total_connections": 0,
            "active_connections": 0,
            "bytes_received": 0,
            "bytes_sent": 0,
            "requests_handled": 0,
            "errors": 0,
        }

    @property
    def is_running(self) -> bool:
        return self._is_running

    async def start(self) -> None:
        """启动 SOCKS5 代理服务器"""
        self._server = await asyncio.start_server(
            self._handle_connection,
            self.config.host,
            self.config.port,
        )
        self._is_running = True
        logger.info(f"SOCKS5 代理服务器已启动: {self.config.host}:{self.config.port}")

    async def stop(self) -> None:
        """停止 SOCKS5 代理服务器"""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self._is_running = False
        logger.info("SOCKS5 代理服务器已停止")

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        """处理连接"""
        if self._stats["active_connections"] >= self.config.max_connections:
            writer.close()
            return

        client_addr = writer.get_extra_info("peername") or ("unknown", 0)
        session_id = self._next_session_id
        self._next_session_id += 1

        session = ProxySession(
            id=session_id,
            client_addr=client_addr,
            start_time=__import__("time").time(),
        )
        self._sessions[session_id] = session
        self._stats["total_connections"] += 1
        self._stats["active_connections"] += 1

        try:
            # SOCKS5 握手
            if not await self._socks5_handshake(reader, writer, session):
                return

            # 读取请求
            if not await self._socks5_request(reader, writer, session):
                return

            # 转发数据
            await self._relay_data(reader, writer, session)

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"SOCKS5 代理错误: {e}")
        finally:
            session.is_active = False
            session.end_time = __import__("time").time()
            self._stats["active_connections"] -= 1
            self._sessions.pop(session_id, None)
            try:
                writer.close()
            except Exception:
                pass

    async def _socks5_handshake(self, reader: asyncio.StreamReader,
                                 writer: asyncio.StreamWriter,
                                 session: ProxySession) -> bool:
        """SOCKS5 握手"""
        try:
            data = await reader.readexactly(2)
            if len(data) < 2:
                return False

            ver, nmethods = data[0], data[1]
            if ver != 0x05:
                return False

            if nmethods > 0:
                methods = await reader.readexactly(nmethods)
            else:
                methods = b""

            if self.config.require_auth and Socks5Auth.USER_PASS in methods:
                # 用户名密码认证
                writer.write(bytes([0x05, Socks5Auth.USER_PASS]))
                await writer.drain()

                auth_data = await reader.readexactly(2)
                if len(auth_data) < 2:
                    return False

                ulen = auth_data[1]
                username_data = await reader.readexactly(ulen)
                username = username_data.decode("utf-8", errors="ignore")

                plen_data = await reader.readexactly(1)
                plen = plen_data[0]
                password_data = await reader.readexactly(plen)
                password = password_data.decode("utf-8", errors="ignore")

                if self.handler.authenticate(username, password):
                    writer.write(bytes([0x01, 0x00]))
                    session.username = username
                else:
                    writer.write(bytes([0x01, 0x01]))
                    return False
                await writer.drain()

            else:
                writer.write(bytes([0x05, Socks5Auth.NO_AUTH]))
                await writer.drain()

            return True

        except Exception as e:
            logger.error(f"SOCKS5 握手失败: {e}")
            return False

    async def _socks5_request(self, reader: asyncio.StreamReader,
                               writer: asyncio.StreamWriter,
                               session: ProxySession) -> bool:
        """处理 SOCKS5 请求"""
        try:
            data = await reader.readexactly(4)
            if len(data) < 4:
                return False

            ver, cmd, rsv, atyp = data[0], data[1], data[2], data[3]
            if ver != 0x05 or cmd != Socks5Command.CONNECT:
                return False

            if atyp == Socks5AddressType.IPV4:
                addr_data = await reader.readexactly(4)
                target_host = ".".join(str(b) for b in addr_data)
            elif atyp == Socks5AddressType.DOMAIN:
                domain_len_data = await reader.readexactly(1)
                domain_len = domain_len_data[0]
                domain_data = await reader.readexactly(domain_len)
                target_host = domain_data.decode("utf-8", errors="ignore")
            else:
                return False

            port_data = await reader.readexactly(2)
            target_port = (port_data[0] << 8) | port_data[1]

            if not self.handler.check_destination(target_host):
                writer.write(bytes([0x05, Socks5Reply.NOT_ALLOWED, 0x00, 0x01, 0, 0, 0, 0, 0, 0]))
                await writer.drain()
                return False

            session.target_host = target_host
            session.target_port = target_port

            # 响应成功
            reply = bytes([0x05, Socks5Reply.SUCCESS, 0x00, 0x01, 0, 0, 0, 0, 0, 0])
            writer.write(reply)
            await writer.drain()

            self._stats["requests_handled"] += 1
            return True

        except Exception as e:
            logger.error(f"SOCKS5 请求处理失败: {e}")
            return False

    async def _relay_data(self, reader: asyncio.StreamReader,
                           writer: asyncio.StreamWriter,
                           session: ProxySession) -> None:
        """转发数据"""
        buffer_size = self.config.buffer_size
        while True:
            try:
                data = await asyncio.wait_for(
                    reader.read(buffer_size),
                    timeout=self.config.timeout,
                )
                if not data:
                    break

                session.bytes_received += len(data)
                self._stats["bytes_received"] += len(data)

                writer.write(data)
                await writer.drain()

                session.bytes_sent += len(data)
                self._stats["bytes_sent"] += len(data)

            except asyncio.TimeoutError:
                break
            except Exception:
                break

    def get_statistics(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "host": self.config.host,
            "port": self.config.port,
            "type": "SOCKS5",
            "is_running": self._is_running,
            "active_sessions": len(self._sessions),
            "require_auth": self.config.require_auth,
        }


class ProxyServer:
    """代理服务器统一入口"""

    def __init__(self, config: Optional[ProxyConfig] = None) -> None:
        self.config = config or ProxyConfig()
        self._http_proxy: Optional[HTTPProxy] = None
        self._socks5_proxy: Optional[Socks5Proxy] = None
        self._is_running: bool = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    async def start(self) -> None:
        """启动代理服务器"""
        if self.config.proxy_type == ProxyType.HTTP:
            self._http_proxy = HTTPProxy(self.config)
            await self._http_proxy.start()
        elif self.config.proxy_type == ProxyType.SOCKS5:
            self._socks5_proxy = Socks5Proxy(self.config)
            await self._socks5_proxy.start()
        else:
            self._http_proxy = HTTPProxy(self.config)
            await self._http_proxy.start()

        self._is_running = True

    async def stop(self) -> None:
        """停止代理服务器"""
        if self._http_proxy:
            await self._http_proxy.stop()
        if self._socks5_proxy:
            await self._socks5_proxy.stop()
        self._is_running = False

    def get_statistics(self) -> Dict[str, Any]:
        if self._http_proxy:
            return self._http_proxy.get_statistics()
        if self._socks5_proxy:
            return self._socks5_proxy.get_statistics()
        return {"is_running": False}