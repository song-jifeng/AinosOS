"""
Tests for the TCP server with NDJSON protocol.

Tests cover:
- Request/response serialization
- Method routing
- Client connection handling
- Error handling
"""

import pytest
import json
import sys
import os
import socket
import threading
import time
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from server.protocol import (
    Protocol, Request, Response, Event, Heartbeat,
    ErrorCode, SUPPORTED_METHODS, METHOD_SCHEMAS, NDJSONMessage
)
from server.handler import RequestHandler
from server.server import VectorDatabaseServer, ClientConnection
from database import VectorDatabase
from utils.config import ServerConfig


class TestProtocol:
    """Tests for the NDJSON protocol."""

    def test_parse_request(self):
        """Test parsing a request message."""
        line = json.dumps({
            "type": "request",
            "id": "test-1",
            "method": "ping",
            "params": {},
            "version": "1.0"
        })
        msg = Protocol.parse(line)
        assert isinstance(msg, Request)
        assert msg.id == "test-1"
        assert msg.method == "ping"
        assert msg.params == {}

    def test_parse_response(self):
        """Test parsing a response message."""
        line = json.dumps({
            "type": "response",
            "id": "test-1",
            "success": True,
            "result": "pong",
            "version": "1.0"
        })
        msg = Protocol.parse(line)
        assert isinstance(msg, Response)
        assert msg.id == "test-1"
        assert msg.success is True
        assert msg.result == "pong"

    def test_create_request(self):
        """Test creating a request string."""
        ndjson = Protocol.create_request("search", {"collection": "test", "top_k": 10})
        data = json.loads(ndjson.strip())
        assert data["type"] == "request"
        assert data["method"] == "search"
        assert data["params"]["collection"] == "test"
        assert data["params"]["top_k"] == 10

    def test_create_success_response(self):
        """Test creating a success response."""
        ndjson = Protocol.create_success_response("req-1", {"result": "ok"})
        data = json.loads(ndjson.strip())
        assert data["type"] == "response"
        assert data["id"] == "req-1"
        assert data["success"] is True
        assert data["result"]["result"] == "ok"

    def test_create_error_response(self):
        """Test creating an error response."""
        ndjson = Protocol.create_error_response("req-1", ErrorCode.INVALID_PARAMS, "Bad params")
        data = json.loads(ndjson.strip())
        assert data["type"] == "response"
        assert data["success"] is False
        assert data["error"]["code"] == ErrorCode.INVALID_PARAMS
        assert data["error"]["message"] == "Bad params"

    def test_create_event(self):
        """Test creating an event message."""
        ndjson = Protocol.create_event("insert", {"count": 10})
        data = json.loads(ndjson.strip())
        assert data["type"] == "event"
        assert data["event"] == "insert"
        assert data["data"]["count"] == 10

    def test_create_heartbeat(self):
        """Test creating a heartbeat message."""
        ndjson = Protocol.create_heartbeat()
        data = json.loads(ndjson.strip())
        assert data["type"] == "heartbeat"

    def test_parse_batch(self):
        """Test parsing multiple NDJSON lines."""
        lines = (
            Protocol.create_request("ping", {}) +
            Protocol.create_request("stats", {})
        )
        messages = Protocol.parse_batch(lines)
        assert len(messages) == 2
        assert all(isinstance(m, Request) for m in messages)

    def test_empty_line(self):
        """Test parsing empty line."""
        msg = Protocol.parse("")
        assert msg is None

    def test_invalid_json(self):
        """Test parsing invalid JSON."""
        msg = Protocol.parse("not json at all")
        assert msg is None

    def test_unknown_type(self):
        """Test parsing message with unknown type."""
        line = json.dumps({"type": "unknown", "data": "test"})
        msg = Protocol.parse(line)
        assert msg is None

    def test_supported_methods(self):
        """Test that all supported methods have schemas."""
        for method in SUPPORTED_METHODS:
            assert method in METHOD_SCHEMAS, f"Missing schema for {method}"

    def test_method_schemas(self):
        """Test method schemas have required fields."""
        for method, schema in METHOD_SCHEMAS.items():
            assert 'required' in schema
            assert 'optional' in schema


class TestRequestHandler:
    """Tests for the request handler."""

    @pytest.fixture
    def handler(self):
        db = VectorDatabase()
        return RequestHandler(db)

    def test_ping(self, handler):
        """Test ping request."""
        request = Request(id="1", method="ping")
        response = handler.handle_request(request)
        data = json.loads(response.strip())
        assert data["success"] is True
        assert data["result"] == "pong"

    def test_health(self, handler):
        """Test health request."""
        request = Request(id="1", method="health")
        response = handler.handle_request(request)
        data = json.loads(response.strip())
        assert data["success"] is True
        assert data["result"]["status"] == "ok"

    def test_unknown_method(self, handler):
        """Test unknown method."""
        request = Request(id="1", method="nonexistent")
        response = handler.handle_request(request)
        data = json.loads(response.strip())
        assert data["success"] is False
        assert data["error"]["code"] == ErrorCode.METHOD_NOT_FOUND

    def test_missing_required_params(self, handler):
        """Test missing required parameters."""
        request = Request(id="1", method="create_index", params={})
        response = handler.handle_request(request)
        data = json.loads(response.strip())
        assert data["success"] is False
        assert data["error"]["code"] == ErrorCode.INVALID_PARAMS

    def test_create_index(self, handler):
        """Test create_index request."""
        request = Request(id="1", method="create_index", params={
            "name": "test",
            "dimension": 128,
            "index_type": "flat",
            "metric": "cosine"
        })
        response = handler.handle_request(request)
        data = json.loads(response.strip())
        assert data["success"] is True
        assert data["result"] is True

    def test_create_index_twice(self, handler):
        """Test creating duplicate index (should fail)."""
        handler.handle_request(Request(id="1", method="create_index", params={
            "name": "dup", "dimension": 64
        }))
        response = handler.handle_request(Request(id="2", method="create_index", params={
            "name": "dup", "dimension": 64
        }))
        data = json.loads(response.strip())
        assert data["success"] is False

    def test_insert_and_search(self, handler):
        """Test insert then search."""
        # Create index
        handler.handle_request(Request(id="1", method="create_index", params={
            "name": "test", "dimension": 3, "metric": "cosine"
        }))

        # Insert vectors
        handler.handle_request(Request(id="2", method="insert", params={
            "collection": "test",
            "vectors": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        }))

        # Search
        response = handler.handle_request(Request(id="3", method="search", params={
            "collection": "test",
            "query_vector": [1.0, 0.0, 0.0],
            "top_k": 2
        }))
        data = json.loads(response.strip())
        assert data["success"] is True
        assert len(data["result"]) == 2

    def test_list_collections(self, handler):
        """Test listing collections."""
        handler.handle_request(Request(id="1", method="create_index", params={
            "name": "a", "dimension": 64
        }))
        handler.handle_request(Request(id="2", method="create_index", params={
            "name": "b", "dimension": 64
        }))

        response = handler.handle_request(Request(id="3", method="list_collections"))
        data = json.loads(response.strip())
        assert data["success"] is True
        assert len(data["result"]) == 2
        assert "a" in data["result"]
        assert "b" in data["result"]

    def test_delete(self, handler):
        """Test delete request."""
        handler.handle_request(Request(id="1", method="create_index", params={
            "name": "test", "dimension": 3
        }))
        handler.handle_request(Request(id="2", method="insert", params={
            "collection": "test",
            "vectors": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        }))

        response = handler.handle_request(Request(id="3", method="delete", params={
            "collection": "test", "ids": [0]
        }))
        data = json.loads(response.strip())
        assert data["success"] is True

    def test_stats(self, handler):
        """Test stats request."""
        handler.handle_request(Request(id="1", method="create_index", params={
            "name": "test", "dimension": 64
        }))

        response = handler.handle_request(Request(id="2", method="stats"))
        data = json.loads(response.strip())
        assert data["success"] is True


class TestClientConnection:
    """Tests for ClientConnection."""

    def test_client_creation(self):
        """Test creating a client connection."""
        import socket as sock_module
        config = ServerConfig()
        db = VectorDatabase()
        handler = RequestHandler(db)

        # Create a pair of connected sockets
        a, b = sock_module.socketpair()
        client = ClientConnection(a, ("127.0.0.1", 12345), handler, config)
        assert not client.closed
        assert client.is_alive()
        client.close()
        b.close()


class TestServerIntegration:
    """Integration tests for the server."""

    @pytest.fixture
    def server(self):
        """Create and start a test server."""
        config = ServerConfig(host="127.0.0.1", port=19600, max_workers=2)
        server = VectorDatabaseServer(config=config)
        server.start()
        time.sleep(0.5)  # Wait for server to start
        yield server
        server.stop()

    def test_server_connect(self, server):
        """Test connecting to the server."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        try:
            sock.connect(("127.0.0.1", 19600))
            # Send ping
            ping_msg = Protocol.create_request("ping", {})
            sock.sendall(ping_msg.encode('utf-8'))

            # Receive response
            response = sock.recv(4096).decode('utf-8')
            data = json.loads(response.strip())
            assert data["success"] is True
            assert data["result"] == "pong"
        finally:
            sock.close()

    def test_end_to_end(self, server):
        """Test end-to-end insert and search."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)

        try:
            sock.connect(("127.0.0.1", 19600))

            # Helper to send request and get response
            def send_request(method, params):
                msg = Protocol.create_request(method, params)
                sock.sendall(msg.encode('utf-8'))
                resp = sock.recv(65536).decode('utf-8')
                return json.loads(resp.strip())

            # Create index
            resp = send_request("create_index", {
                "name": "demo", "dimension": 4, "metric": "cosine"
            })
            assert resp["success"] is True

            # Insert vectors
            resp = send_request("insert", {
                "collection": "demo",
                "vectors": [
                    [1.0, 0.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0, 0.0],
                    [0.0, 0.0, 1.0, 0.0],
                    [1.0, 1.0, 0.0, 0.0],
                ]
            })
            assert resp["success"] is True

            # Search
            resp = send_request("search", {
                "collection": "demo",
                "query_vector": [1.0, 0.0, 0.0, 0.0],
                "top_k": 2
            })
            assert resp["success"] is True
            assert len(resp["result"]) == 2

            # Stats
            resp = send_request("stats", {})
            assert resp["success"] is True

        finally:
            sock.close()

    def test_multiple_clients(self, server):
        """Test multiple concurrent clients."""
        def client_task(client_id, results):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5.0)
                sock.connect(("127.0.0.1", 19600))

                msg = Protocol.create_request("ping", {})
                sock.sendall(msg.encode('utf-8'))
                resp = sock.recv(4096).decode('utf-8')
                data = json.loads(resp.strip())
                results[client_id] = data["success"]
                sock.close()
            except Exception as e:
                results[client_id] = False

        results = {}
        threads = []
        for i in range(5):
            t = threading.Thread(target=client_task, args=(i, results))
            t.start()
            threads.append(t)

        for t in threads:
            t.join(timeout=10)

        assert all(results.values())
        assert len(results) == 5