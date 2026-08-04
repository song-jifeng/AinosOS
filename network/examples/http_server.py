"""
HTTP 服务器示例
===============

展示如何使用内置 HTTP 服务器创建 REST API 服务。
"""

import asyncio
import json
import logging
from src.protocol.http import HTTPServer, HTTPResponse, HTTPStatus


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# 模拟数据存储
items = {
    1: {"id": 1, "name": "Item 1", "price": 10.99},
    2: {"id": 2, "name": "Item 2", "price": 20.49},
    3: {"id": 3, "name": "Item 3", "price": 15.00},
}


async def handle_index(request):
    """首页"""
    return HTTPResponse(
        status=HTTPStatus.OK,
        headers={"Content-Type": "text/html"},
        body=b"<h1>Welcome to Ainos HTTP Server</h1><p>Try /api/items</p>",
    )


async def handle_get_items(request):
    """获取所有项目"""
    return HTTPResponse(
        status=HTTPStatus.OK,
        headers={"Content-Type": "application/json"},
        body=json.dumps(list(items.values())).encode("utf-8"),
    )


async def handle_get_item(request):
    """获取单个项目"""
    try:
        item_id = int(request.path.split("/")[-1])
        item = items.get(item_id)
        if item:
            return HTTPResponse(
                status=HTTPStatus.OK,
                headers={"Content-Type": "application/json"},
                body=json.dumps(item).encode("utf-8"),
            )
        return HTTPResponse(
            status=HTTPStatus.NOT_FOUND,
            body=json.dumps({"error": "Item not found"}).encode("utf-8"),
        )
    except (ValueError, IndexError):
        return HTTPResponse(
            status=HTTPStatus.BAD_REQUEST,
            body=json.dumps({"error": "Invalid item ID"}).encode("utf-8"),
        )


async def handle_create_item(request):
    """创建新项目"""
    try:
        data = request.json()
        if not data or "name" not in data:
            return HTTPResponse(
                status=HTTPStatus.BAD_REQUEST,
                body=json.dumps({"error": "Name is required"}).encode("utf-8"),
            )

        new_id = max(items.keys()) + 1 if items else 1
        items[new_id] = {
            "id": new_id,
            "name": data["name"],
            "price": data.get("price", 0.0),
        }
        return HTTPResponse(
            status=HTTPStatus.CREATED,
            headers={"Content-Type": "application/json"},
            body=json.dumps(items[new_id]).encode("utf-8"),
        )
    except Exception as e:
        return HTTPResponse(
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            body=json.dumps({"error": str(e)}).encode("utf-8"),
        )


async def handle_delete_item(request):
    """删除项目"""
    try:
        item_id = int(request.path.split("/")[-1])
        if item_id in items:
            del items[item_id]
            return HTTPResponse(
                status=HTTPStatus.OK,
                body=json.dumps({"message": "Item deleted"}).encode("utf-8"),
            )
        return HTTPResponse(
            status=HTTPStatus.NOT_FOUND,
            body=json.dumps({"error": "Item not found"}).encode("utf-8"),
        )
    except (ValueError, IndexError):
        return HTTPResponse(
            status=HTTPStatus.BAD_REQUEST,
            body=json.dumps({"error": "Invalid item ID"}).encode("utf-8"),
        )


async def handle_static(request):
    """静态文件服务"""
    path = request.path
    if path == "/about":
        return HTTPResponse(
            status=HTTPStatus.OK,
            headers={"Content-Type": "text/html"},
            body=b"<h1>About Ainos Network Stack</h1><p>Version 2.1.0</p>",
        )
    return HTTPResponse(
        status=HTTPStatus.NOT_FOUND,
        body=b"<h1>404 Not Found</h1>",
    )


async def handle_logging_middleware(request):
    """日志中间件"""
    logger.info(f"{request.method.value} {request.path} - {request.remote_addr}")
    return None


async def handle_cors_middleware(request):
    """CORS 中间件"""
    if request.method.value == "OPTIONS":
        return HTTPResponse(
            status=HTTPStatus.OK,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, DELETE",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        )
    return None


async def main():
    server = HTTPServer(host="0.0.0.0", port=8080)

    # 添加中间件
    server.use(handle_logging_middleware)
    server.use(handle_cors_middleware)

    # 注册路由
    server.get("/")(handle_index)
    server.get("/api/items")(handle_get_items)
    server.get("/api/items/*")(handle_get_item)
    server.post("/api/items")(handle_create_item)
    server.delete("/api/items/*")(handle_delete_item)
    server.get("/about")(handle_static)

    logger.info("启动 HTTP 服务器...")
    await server.start()

    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())