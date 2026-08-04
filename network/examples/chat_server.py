"""
简易聊天服务器示例
==================

基于 WebSocket 的多人聊天服务器。
"""

import asyncio
import json
import logging
from src.protocol.websocket import WebSocketServer, WebSocket


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ChatServer:
    """聊天服务器"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self._server = WebSocketServer(host, port)
        self._clients: dict = {}
        self._usernames: dict = {}

    async def start(self) -> None:
        """启动聊天服务器"""
        self._server.on_connect(self._on_connect)
        self._server.on_message(self._on_message)
        self._server.on_close(self._on_close)
        await self._server.start()
        logger.info(f"聊天服务器已启动: ws://{self.host}:{self.port}")

        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await self._server.stop()

    async def _on_connect(self, ws: WebSocket, conn_id: int) -> None:
        """新连接处理"""
        self._clients[conn_id] = ws
        self._usernames[conn_id] = f"用户{conn_id}"
        logger.info(f"新用户加入: {conn_id}")
        await self._broadcast({
            "type": "system",
            "message": f"用户 {self._usernames[conn_id]} 加入了聊天室",
        })

    async def _on_message(self, ws: WebSocket, conn_id: int, message: str) -> None:
        """消息处理"""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "message")

            if msg_type == "message":
                await self._broadcast({
                    "type": "message",
                    "username": self._usernames.get(conn_id, "匿名"),
                    "content": data.get("content", ""),
                    "timestamp": __import__("time").time(),
                })
            elif msg_type == "set_name":
                new_name = data.get("name", f"用户{conn_id}")
                old_name = self._usernames.get(conn_id, "匿名")
                self._usernames[conn_id] = new_name
                await self._broadcast({
                    "type": "system",
                    "message": f"{old_name} 改名为 {new_name}",
                })
            elif msg_type == "ping":
                await ws.send_json({"type": "pong"})

        except json.JSONDecodeError:
            await ws.send_json({"type": "error", "message": "无效的消息格式"})

    async def _on_close(self, ws: WebSocket, conn_id: int) -> None:
        """连接关闭处理"""
        if conn_id in self._clients:
            del self._clients[conn_id]
            username = self._usernames.pop(conn_id, "匿名")
            logger.info(f"用户离开: {conn_id}")
            await self._broadcast({
                "type": "system",
                "message": f"{username} 离开了聊天室",
            })

    async def _broadcast(self, message: dict) -> None:
        """广播消息"""
        data = json.dumps(message, ensure_ascii=False)
        for conn_id, ws in list(self._clients.items()):
            try:
                await ws.send(data)
            except Exception:
                pass


async def main():
    server = ChatServer()
    await server.start()


if __name__ == "__main__":
    asyncio.run(main())