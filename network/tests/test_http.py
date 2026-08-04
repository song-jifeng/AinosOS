"""
HTTP 协议单元测试
=================
"""

import pytest
from src.protocol.http import (
    HTTPRequest, HTTPResponse, HTTPClient, HTTPServer,
    HTTPMethod, HTTPStatus, HTTPVersion, HTTPError,
    HTTPConnectionError, HTTPParseError,
)


class TestHTTPRequest:
    """HTTP 请求测试"""

    def test_create_request(self):
        """测试创建请求"""
        request = HTTPRequest(
            method=HTTPMethod.GET,
            path="/index.html",
            headers={"Host": "example.com"},
        )
        assert request.method == HTTPMethod.GET
        assert request.path == "/index.html"
        assert request.host == "example.com"

    def test_request_encode_decode(self, sample_http_request):
        """测试请求编码和解码"""
        request = HTTPRequest.decode(sample_http_request)
        assert request.method == HTTPMethod.GET
        assert request.path == "/"
        assert request.version == HTTPVersion.HTTP_1_1
        assert request.host == "example.com"

        encoded = request.encode()
        assert b"GET / HTTP/1.1" in encoded

    def test_request_with_body(self):
        """测试带请求体的请求"""
        request = HTTPRequest(
            method=HTTPMethod.POST,
            path="/api/data",
            headers={
                "Content-Type": "application/json",
                "Content-Length": "18",
            },
            body=b'{"key": "value"}',
        )
        assert request.content_type == "application/json"
        assert request.content_length == 18
        json_data = request.json()
        assert json_data["key"] == "value"

    def test_request_invalid(self):
        """测试无效的请求"""
        with pytest.raises(HTTPParseError):
            HTTPRequest.decode(b"")
        with pytest.raises(HTTPParseError):
            HTTPRequest.decode(b"INVALID")


class TestHTTPResponse:
    """HTTP 响应测试"""

    def test_create_response(self):
        """测试创建响应"""
        response = HTTPResponse(
            status=HTTPStatus.OK,
            headers={"Content-Type": "text/plain"},
            body=b"Hello World",
        )
        assert response.is_success
        assert not response.is_error
        assert response.status_code == 200
        assert response.reason_phrase == "OK"

    def test_response_encode_decode(self, sample_http_response):
        """测试响应编码和解码"""
        response = HTTPResponse.decode(sample_http_response)
        assert response.status_code == 200
        assert response.is_success
        assert response.content_type == "text/plain"
        assert response.text() == "Hello World!"

        encoded = response.encode()
        assert b"HTTP/1.1 200 OK" in encoded

    def test_redirect_response(self):
        """测试重定向响应"""
        response = HTTPResponse(
            status=HTTPStatus.MOVED_PERMANENTLY,
            headers={"Location": "https://example.com/new"},
        )
        assert response.is_redirect
        assert response.location == "https://example.com/new"

    def test_error_response(self):
        """测试错误响应"""
        response = HTTPResponse(status=HTTPStatus.NOT_FOUND, body=b"Not Found")
        assert response.is_error

        response = HTTPResponse(status=HTTPStatus.INTERNAL_SERVER_ERROR)
        assert response.is_error


class TestHTTPClient:
    """HTTP 客户端测试"""

    @pytest.mark.asyncio
    async def test_client_creation(self):
        """测试客户端创建"""
        client = HTTPClient()
        assert client is not None
        stats = client.get_statistics()
        assert stats["requests"] == 0

    @pytest.mark.asyncio
    async def test_request_failure(self):
        """测试请求失败"""
        client = HTTPClient(timeout=1.0)
        with pytest.raises((HTTPConnectionError, HTTPError)):
            await client.get("http://192.0.2.1:1/")

    def test_default_headers(self):
        """测试默认请求头"""
        client = HTTPClient()
        client.set_default_header("X-Custom", "test")
        assert "X-Custom" in client._default_headers


class TestHTTPServer:
    """HTTP 服务器测试"""

    @pytest.mark.asyncio
    async def test_server_start_stop(self):
        """测试服务器启动和停止"""
        server = HTTPServer(port=0)
        # 端口 0 会失败，但测试启动和停止逻辑
        try:
            await server.start()
        except OSError:
            pass
        await server.stop()

    def test_route_registration(self):
        """测试路由注册"""
        server = HTTPServer()

        @server.get("/")
        async def index(request):
            return HTTPResponse(body=b"Hello")

        @server.post("/api")
        async def api(request):
            return HTTPResponse(body=b"OK")

        assert len(server._routes) == 2

    def test_path_matching(self):
        """测试路径匹配"""
        assert HTTPServer._match_path("/", "/")
        assert HTTPServer._match_path("/api/*", "/api/users")
        assert not HTTPServer._match_path("/api", "/api/users")

    def test_middleware(self):
        """测试中间件"""
        server = HTTPServer()
        called = []

        async def middleware(request):
            called.append(True)
            return None

        server.use(middleware)
        assert len(server._middleware) == 1