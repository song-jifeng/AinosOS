"""
WebSocket 实现
==============

提供完整的 WebSocket 客户端和服务器实现，支持 RFC 6455 协议，
包括帧编解码、掩码处理、分片消息重组和 Ping/Pong 保活。
"""

import asyncio
import struct
import hashlib
import base64
import random
import time
import logging
from typing import Optional, Dict, Any, List, Tuple, Callable
from dataclasses import dataclass, field
from enum import IntEnum


logger = logging.getLogger(__name__)


class WebSocketOpcode(IntEnum):
    """WebSocket 操作码"""
    CONTINUATION = 0x0
    TEXT = 0x1
    BINARY = 0x2
    CLOSE = 0x8
    PING = 0x9
    PONG = 0xA


class WebSocketCloseCode(IntEnum):
    """WebSocket 关闭代码"""
    NORMAL_CLOSURE = 1000
    GOING_AWAY = 1001
    PROTOCOL_ERROR = 1002
    UNSUPPORTED_DATA = 1003
    RESERVED = 1004
    NO_STATUS_RECEIVED = 1005
    ABNORMAL_CLOSURE = 1006
    INVALID_PAYLOAD_DATA = 1007
    POLICY_VIOLATION = 1008
    MESSAGE_TOO_BIG = 1009
    MANDATORY_EXTENSION = 1010
    INTERNAL_ERROR = 1011
    SERVICE_RESTART = 1012
    TRY_AGAIN_LATER = 1013
    BAD_GATEWAY = 1014
    TLS_HANDSHAKE_FAIL = 1015


class WebSocketError(Exception):
    """WebSocket 错误"""
    pass


class WebSocketConnectionClosed(WebSocketError):
    """WebSocket 连接已关闭"""
    pass


class WebSocketProtocolError(WebSocketError):
    """WebSocket 协议错误"""
    pass


@dataclass
class WebSocketFrame:
    """WebSocket 帧"""
    fin: bool = True
    rsv1: bool = False
    rsv2: bool = False
    rsv3: bool = False
    opcode: WebSocketOpcode = WebSocketOpcode.TEXT
    mask: bool = False
    masking_key: bytes = b""
    payload: bytes = b""
    length: int = 0

    def __post_init__(self) -> None:
        self.length = len(self.payload)

    @property
    def is_control_frame(self) -> bool:
        return self.opcode in (WebSocketOpcode.CLOSE, WebSocketOpcode.PING, WebSocketOpcode.PONG)

    @property
    def is_data_frame(self) -> bool:
        return self.opcode in (WebSocketOpcode.TEXT, WebSocketOpcode.BINARY, WebSocketOpcode.CONTINUATION)

    def encode(self) -> bytes:
        """编码帧为字节"""
        # 第一个字节
        first_byte = 0x00
        if self.fin:
            first_byte |= 0x80
        if self.rsv1:
            first_byte |= 0x40
        if self.rsv2:
            first_byte |= 0x20
        if self.rsv3:
            first_byte |= 0x10
        first_byte |= self.opcode

        # 第二个字节
        second_byte = 0x00
        if self.mask:
            second_byte |= 0x80

        payload = self.payload
        if self.mask and self.masking_key:
            payload = self._apply_mask(payload, self.masking_key)

        if self.length < 126:
            second_byte |= self.length
            header = bytes([first_byte, second_byte])
        elif self.length < 65536:
            second_byte |= 126
            header = bytes([first_byte, second_byte]) + struct.pack("!H", self.length)
        else:
            second_byte |= 127
            header = bytes([first_byte, second_byte]) + struct.pack("!Q", self.length)

        if self.mask:
            header += self.masking_key

        return header + payload

    @classmethod
    def decode(cls, data: bytes) -> "WebSocketFrame":
        """从字节解码帧"""
        if len(data) < 2:
            raise WebSocketProtocolError(f"WebSocket 帧太短: {len(data)} 字节")

        first_byte = data[0]
        second_byte = data[1]

        fin = bool(first_byte & 0x80)
        rsv1 = bool(first_byte & 0x40)
        rsv2 = bool(first_byte & 0x20)
        rsv3 = bool(first_byte & 0x10)
        opcode = WebSocketOpcode(first_byte & 0x0F)

        mask = bool(second_byte & 0x80)
        length = second_byte & 0x7F

        offset = 2

        if length == 126:
            if len(data) < 4:
                raise WebSocketProtocolError("WebSocket 帧被截断")
            length = struct.unpack("!H", data[offset:offset + 2])[0]
            offset += 2
        elif length == 127:
            if len(data) < 10:
                raise WebSocketProtocolError("WebSocket 帧被截断")
            length = struct.unpack("!Q", data[offset:offset + 8])[0]
            offset += 8

        masking_key = b""
        if mask:
            if len(data) < offset + 4:
                raise WebSocketProtocolError("WebSocket 帧被截断")
            masking_key = data[offset:offset + 4]
            offset += 4

        if len(data) < offset + length:
            raise WebSocketProtocolError(f"WebSocket 帧被截断: 需要 {length} 字节，实际 {len(data) - offset}")

        payload = data[offset:offset + length]
        if mask:
            payload = cls._apply_mask(payload, masking_key)

        return cls(
            fin=fin,
            rsv1=rsv1,
            rsv2=rsv2,
            rsv3=rsv3,
            opcode=opcode,
            mask=mask,
            masking_key=masking_key,
            payload=payload,
            length=length,
        )

    @staticmethod
    def _apply_mask(data: bytes, mask_key: bytes) -> bytes:
        """应用掩码"""
        if len(mask_key) != 4:
            return data
        return bytes(b ^ mask_key[i % 4] for i, b in enumerate(data))

    @staticmethod
    def generate_masking_key() -> bytes:
        """生成随机掩码键"""
        return bytes([random.randint(0, 255) for _ in range(4)])


class WebSocket:
    """WebSocket 连接"""

    WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-5AB5A514648A"

    def __init__(self, host: str = "0.0.0.0", port: int = 8080,
                 max_message_size: int = 1048576,
                 ping_interval: float = 30.0,
                 ping_timeout: float = 10.0) -> None:
        self.host = host
        self.port = port
        self.max_message_size = max_message_size
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._is_closed: bool = False
        self._is_server: bool = False
        self._on_message: Optional[Callable] = None
        self._on_close: Optional[Callable] = None
        self._on_error: Optional[Callable] = None
        self._buffer: bytes = b""
        self._message_buffer: bytes = b""
        self._message_opcode: Optional[WebSocketOpcode] = None
        self._last_pong: float = time.time()
        self._close_code: Optional[int] = None
        self._close_reason: str = ""
        self._bytes_sent: int = 0
        self._bytes_received: int = 0
        self._frames_sent: int = 0
        self._frames_received: int = 0
        self._stats: Dict[str, int] = {
            "messages_sent": 0,
            "messages_received": 0,
            "pings_sent": 0,
            "pongs_received": 0,
        }

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return not self._is_closed and self._writer is not None

    @property
    def close_code(self) -> Optional[int]:
        return self._close_code

    @property
    def close_reason(self) -> str:
        return self._close_reason

    @staticmethod
    def compute_accept_key(key: str) -> str:
        """计算 WebSocket 接受键"""
        combined = key + WebSocket.WEBSOCKET_GUID
        sha1 = hashlib.sha1(combined.encode()).digest()
        return base64.b64encode(sha1).decode()

    @staticmethod
    def generate_key() -> str:
        """生成 WebSocket 请求键"""
        return base64.b64encode(bytes(random.randint(0, 255) for _ in range(16))).decode()

    async def accept(self, reader: asyncio.StreamReader,
                     writer: asyncio.StreamWriter,
                     request_key: str = "") -> bool:
        """接受 WebSocket 连接（服务端）"""
        self._reader = reader
        self._writer = writer
        self._is_server = True
        self._is_closed = False

        if request_key:
            accept_key = self.compute_accept_key(request_key)
            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept_key}\r\n"
                "\r\n"
            )
            writer.write(response.encode())
            await writer.drain()

        return True

    async def connect(self, url: str) -> bool:
        """建立 WebSocket 连接（客户端）"""
        import urllib.parse
        parsed = urllib.parse.urlparse(url)
        scheme = parsed.scheme
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        ssl = scheme == "wss"

        try:
            self._reader, self._writer = await asyncio.open_connection(
                host, port, ssl=ssl
            )
        except OSError as e:
            raise WebSocketError(f"连接失败: {e}")

        # 发送握手请求
        key = self.generate_key()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self._writer.write(request.encode())
        await self._writer.drain()

        # 读取握手响应
        response = b""
        while True:
            line = await self._reader.readline()
            response += line
            if line == b"\r\n":
                break

        response_text = response.decode("utf-8", errors="replace")
        if "101" not in response_text.split("\r\n")[0]:
            raise WebSocketError(f"握手失败: {response_text}")

        self._is_closed = False
        return True

    async def send(self, data: Any, opcode: WebSocketOpcode = WebSocketOpcode.TEXT) -> bool:
        """发送数据

        Args:
            data: 要发送的数据（字符串或字节）
            opcode: 操作码

        Returns:
            是否成功发送
        """
        if self._is_closed or not self._writer:
            raise WebSocketConnectionClosed("WebSocket 连接已关闭")

        if isinstance(data, str):
            payload = data.encode("utf-8")
            opcode = WebSocketOpcode.TEXT
        elif isinstance(data, bytes):
            payload = data
            opcode = WebSocketOpcode.BINARY
        else:
            raise TypeError(f"不支持的数据类型: {type(data)}")

        if len(payload) > self.max_message_size:
            raise WebSocketError(f"消息太大: {len(payload)} > {self.max_message_size}")

        # 客户端发送需要掩码
        mask = not self._is_server
        masking_key = WebSocketFrame.generate_masking_key() if mask else b""

        frame = WebSocketFrame(
            fin=True,
            opcode=opcode,
            mask=mask,
            masking_key=masking_key,
            payload=payload,
        )

        try:
            self._writer.write(frame.encode())
            await self._writer.drain()
            self._bytes_sent += len(payload)
            self._frames_sent += 1
            self._stats["messages_sent"] += 1
            return True
        except OSError as e:
            self._is_closed = True
            raise WebSocketConnectionClosed(f"发送失败: {e}")

    async def send_text(self, text: str) -> bool:
        """发送文本消息"""
        return await self.send(text, WebSocketOpcode.TEXT)

    async def send_bytes(self, data: bytes) -> bool:
        """发送二进制消息"""
        return await self.send(data, WebSocketOpcode.BINARY)

    async def send_json(self, data: Any) -> bool:
        """发送 JSON 消息"""
        import json
        return await self.send(json.dumps(data), WebSocketOpcode.TEXT)

    async def recv(self) -> Any:
        """接收数据

        Returns:
            接收到的消息（字符串或字节）
        """
        if self._is_closed:
            raise WebSocketConnectionClosed("WebSocket 连接已关闭")

        while True:
            try:
                frame = await self._read_frame()
            except WebSocketConnectionClosed:
                raise

            self._frames_received += 1
            self._bytes_received += len(frame.payload)

            if frame.opcode == WebSocketOpcode.CONTINUATION:
                self._message_buffer += frame.payload
                if frame.fin:
                    message = self._message_buffer
                    opcode = self._message_opcode
                    self._message_buffer = b""
                    self._message_opcode = None
                    self._stats["messages_received"] += 1

                    if opcode == WebSocketOpcode.TEXT:
                        return message.decode("utf-8", errors="replace")
                    return message

            elif frame.opcode in (WebSocketOpcode.TEXT, WebSocketOpcode.BINARY):
                if frame.fin:
                    self._stats["messages_received"] += 1
                    if frame.opcode == WebSocketOpcode.TEXT:
                        return frame.payload.decode("utf-8", errors="replace")
                    return frame.payload
                else:
                    self._message_buffer = frame.payload
                    self._message_opcode = frame.opcode

            elif frame.opcode == WebSocketOpcode.PING:
                await self._send_pong(frame.payload)

            elif frame.opcode == WebSocketOpcode.PONG:
                self._last_pong = time.time()
                self._stats["pongs_received"] += 1

            elif frame.opcode == WebSocketOpcode.CLOSE:
                await self._handle_close(frame.payload)
                raise WebSocketConnectionClosed("连接已关闭")

    async def _read_frame(self) -> WebSocketFrame:
        """读取一个 WebSocket 帧"""
        if self._is_closed or not self._reader:
            raise WebSocketConnectionClosed("连接已关闭")

        try:
            # 读取前 2 字节
            header = await self._reader.readexactly(2)
        except (asyncio.IncompleteReadError, OSError) as e:
            self._is_closed = True
            raise WebSocketConnectionClosed(f"读取失败: {e}")

        first_byte = header[0]
        second_byte = header[1]

        fin = bool(first_byte & 0x80)
        opcode = WebSocketOpcode(first_byte & 0x0F)
        mask = bool(second_byte & 0x80)
        length = second_byte & 0x7F

        if length == 126:
            try:
                ext_data = await self._reader.readexactly(2)
                length = struct.unpack("!H", ext_data)[0]
            except asyncio.IncompleteReadError:
                raise WebSocketConnectionClosed("帧被截断")

        elif length == 127:
            try:
                ext_data = await self._reader.readexactly(8)
                length = struct.unpack("!Q", ext_data)[0]
            except asyncio.IncompleteReadError:
                raise WebSocketConnectionClosed("帧被截断")

        masking_key = b""
        if mask:
            try:
                masking_key = await self._reader.readexactly(4)
            except asyncio.IncompleteReadError:
                raise WebSocketConnectionClosed("帧被截断")

        try:
            payload = await self._reader.readexactly(length)
        except asyncio.IncompleteReadError:
            raise WebSocketConnectionClosed("帧被截断")

        if mask:
            payload = WebSocketFrame._apply_mask(payload, masking_key)

        return WebSocketFrame(
            fin=fin,
            opcode=opcode,
            mask=mask,
            masking_key=masking_key,
            payload=payload,
            length=length,
        )

    async def _send_pong(self, payload: bytes = b"") -> None:
        """发送 Pong 帧"""
        if self._writer and not self._is_closed:
            frame = WebSocketFrame(
                fin=True,
                opcode=WebSocketOpcode.PONG,
                payload=payload,
            )
            try:
                self._writer.write(frame.encode())
                await self._writer.drain()
            except OSError:
                pass

    async def ping(self) -> bool:
        """发送 Ping 帧"""
        if self._is_closed or not self._writer:
            return False

        payload = struct.pack("!Q", int(time.time()))
        frame = WebSocketFrame(
            fin=True,
            opcode=WebSocketOpcode.PING,
            payload=payload,
        )

        try:
            self._writer.write(frame.encode())
            await self._writer.drain()
            self._stats["pings_sent"] += 1
            return True
        except OSError:
            self._is_closed = True
            return False

    async def _handle_close(self, payload: bytes) -> None:
        """处理关闭帧"""
        code = WebSocketCloseCode.NORMAL_CLOSURE
        reason = ""

        if len(payload) >= 2:
            code = struct.unpack("!H", payload[:2])[0]
            if len(payload) > 2:
                reason = payload[2:].decode("utf-8", errors="replace")

        self._close_code = code
        self._close_reason = reason

        # 发送关闭响应
        if not self._is_closed:
            response = struct.pack("!H", code)
            frame = WebSocketFrame(
                fin=True,
                opcode=WebSocketOpcode.CLOSE,
                payload=response,
            )
            try:
                self._writer.write(frame.encode())
                await self._writer.drain()
            except OSError:
                pass

        self._is_closed = True

        if self._on_close:
            try:
                self._on_close(code, reason)
            except Exception as e:
                logger.error(f"关闭回调执行出错: {e}")

    async def close(self, code: int = WebSocketCloseCode.NORMAL_CLOSURE,
                    reason: str = "") -> None:
        """关闭 WebSocket 连接"""
        if self._is_closed:
            return

        payload = struct.pack("!H", code)
        if reason:
            payload += reason.encode("utf-8")[:123]

        frame = WebSocketFrame(
            fin=True,
            opcode=WebSocketOpcode.CLOSE,
            payload=payload,
        )

        try:
            self._writer.write(frame.encode())
            await self._writer.drain()
        except OSError:
            pass

        self._is_closed = True
        self._close_code = code
        self._close_reason = reason

        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass

    def on_message(self, callback: Callable) -> None:
        """注册消息回调"""
        self._on_message = callback

    def on_close(self, callback: Callable) -> None:
        """注册关闭回调"""
        self._on_close = callback

    def on_error(self, callback: Callable) -> None:
        """注册错误回调"""
        self._on_error = callback

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "is_connected": self.is_connected,
            "is_server": self._is_server,
            "bytes_sent": self._bytes_sent,
            "bytes_received": self._bytes_received,
            "frames_sent": self._frames_sent,
            "frames_received": self._frames_received,
            **self._stats,
            "close_code": self._close_code,
            "close_reason": self._close_reason,
        }


class WebSocketServer:
    """WebSocket 服务器"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080,
                 max_connections: int = 1000) -> None:
        self.host = host
        self.port = port
        self.max_connections = max_connections
        self._server: Optional[asyncio.AbstractServer] = None
        self._connections: Dict[int, WebSocket] = {}
        self._on_connect: Optional[Callable] = None
        self._on_message: Optional[Callable] = None
        self._on_close: Optional[Callable] = None
        self._is_running: bool = False
        self._next_id: int = 0
        self._stats: Dict[str, int] = {
            "total_connections": 0,
            "active_connections": 0,
            "messages_received": 0,
            "messages_sent": 0,
        }

    @property
    def active_connections(self) -> int:
        return len(self._connections)

    @property
    def total_connections(self) -> int:
        return self._stats["total_connections"]

    def on_connect(self, callback: Callable) -> None:
        """注册连接回调"""
        self._on_connect = callback

    def on_message(self, callback: Callable) -> None:
        """注册消息回调"""
        self._on_message = callback

    def on_close(self, callback: Callable) -> None:
        """注册关闭回调"""
        self._on_close = callback

    async def start(self) -> None:
        """启动服务器"""
        self._server = await asyncio.start_server(
            self._handle_connection,
            self.host,
            self.port,
        )
        self._is_running = True
        logger.info(f"WebSocket 服务器已启动: {self.host}:{self.port}")

    async def stop(self) -> None:
        """停止服务器"""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self._is_running = False

        # 关闭所有连接
        for conn_id, ws in list(self._connections.items()):
            try:
                await ws.close(WebSocketCloseCode.SERVICE_RESTART, "Server shutting down")
            except Exception:
                pass
        self._connections.clear()
        logger.info("WebSocket 服务器已停止")

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        """处理新连接"""
        if len(self._connections) >= self.max_connections:
            writer.close()
            return

        try:
            # 读取 HTTP 握手请求
            request = b""
            while True:
                line = await reader.readline()
                request += line
                if line == b"\r\n":
                    break

            request_text = request.decode("utf-8", errors="replace")
            key = ""
            for line in request_text.split("\r\n"):
                if line.lower().startswith("sec-websocket-key:"):
                    key = line.split(":", 1)[1].strip()
                    break

            if not key:
                writer.close()
                return

            ws = WebSocket()
            await ws.accept(reader, writer, key)

            conn_id = self._next_id
            self._next_id += 1
            self._connections[conn_id] = ws
            self._stats["total_connections"] += 1
            self._stats["active_connections"] += 1

            if self._on_connect:
                try:
                    await self._on_connect(ws, conn_id)
                except Exception as e:
                    logger.error(f"连接回调执行出错: {e}")

            # 消息循环
            try:
                while True:
                    message = await ws.recv()
                    self._stats["messages_received"] += 1
                    if self._on_message:
                        try:
                            await self._on_message(ws, conn_id, message)
                        except Exception as e:
                            logger.error(f"消息回调执行出错: {e}")
            except (WebSocketConnectionClosed, WebSocketError):
                pass
            finally:
                self._connections.pop(conn_id, None)
                self._stats["active_connections"] -= 1
                if self._on_close:
                    try:
                        await self._on_close(ws, conn_id)
                    except Exception as e:
                        logger.error(f"关闭回调执行出错: {e}")

        except Exception as e:
            logger.error(f"连接处理错误: {e}")
            try:
                writer.close()
            except Exception:
                pass

    async def broadcast(self, message: Any) -> int:
        """广播消息到所有连接

        Args:
            message: 要广播的消息

        Returns:
            成功发送的连接数
        """
        sent = 0
        for conn_id, ws in list(self._connections.items()):
            try:
                await ws.send(message)
                self._stats["messages_sent"] += 1
                sent += 1
            except Exception:
                pass
        return sent

    async def send_to(self, conn_id: int, message: Any) -> bool:
        """发送消息到指定连接"""
        ws = self._connections.get(conn_id)
        if ws:
            try:
                await ws.send(message)
                self._stats["messages_sent"] += 1
                return True
            except Exception:
                pass
        return False

    def get_statistics(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "max_connections": self.max_connections,
            "is_running": self._is_running,
        }


class WebSocketClient:
    """WebSocket 客户端"""

    def __init__(self, ping_interval: float = 30.0,
                 ping_timeout: float = 10.0) -> None:
        self._ws = WebSocket(ping_interval=ping_interval, ping_timeout=ping_timeout)
        self._on_message: Optional[Callable] = None
        self._on_close: Optional[Callable] = None
        self._is_connected: bool = False

    async def connect(self, url: str) -> bool:
        """连接到 WebSocket 服务器"""
        result = await self._ws.connect(url)
        self._is_connected = result
        return result

    async def send(self, data: Any) -> bool:
        """发送数据"""
        return await self._ws.send(data)

    async def recv(self) -> Any:
        """接收数据"""
        return await self._ws.recv()

    async def close(self, code: int = WebSocketCloseCode.NORMAL_CLOSURE,
                    reason: str = "") -> None:
        """关闭连接"""
        await self._ws.close(code, reason)
        self._is_connected = False

    def on_message(self, callback: Callable) -> None:
        self._ws.on_message(callback)

    def on_close(self, callback: Callable) -> None:
        self._ws.on_close(callback)

    @property
    def is_connected(self) -> bool:
        return self._is_connected and self._ws.is_connected