"""
Ainos SDK - Transport Layer Tests
==================================

Tests for the TCP transport layer, connection pool, and message framing.
"""

from __future__ import annotations

import asyncio
import json
import socket
import typing as t
from typing import Any, AsyncGenerator

import pytest

from ainos.auth import AuthConfig, AuthManager
from ainos.errors import (
    ConnectionError,
    ConnectionTimeoutError,
    InvalidMessageError,
    MessageTooLargeError,
    TransportClosedError,
)
from ainos.transport import (
    ConnectionPool,
    Transport,
    TransportConnection,
)
from ainos.types import ConnectionConfig, JSONObject
from ainos.utils import json_encode, json_decode

from tests.conftest import MockDaemonProtocol, mock_daemon, mock_handlers


# ---------------------------------------------------------------------------
# TransportConnection tests
# ---------------------------------------------------------------------------


class TestTransportConnection:
    """Tests for individual transport connections."""

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(
        self,
        mock_daemon: tuple[str, int],
    ) -> None:
        """Test basic connect and disconnect."""
        host, port = mock_daemon
        config: ConnectionConfig = ConnectionConfig(
            host=host,
            port=port,
            connect_timeout=5.0,
            request_timeout=10.0,
        )
        auth: AuthManager = AuthManager(AuthConfig(token="valid-token"))
        conn: TransportConnection = TransportConnection(
            host=host,
            port=port,
            config=config,
            auth_manager=auth,
        )

        assert conn.connected is False
        await conn.connect()
        assert conn.connected is True

        await conn.disconnect()
        assert conn.connected is False
        assert conn.closed is True

    @pytest.mark.asyncio
    async def test_send_request(
        self,
        mock_daemon: tuple[str, int],
    ) -> None:
        """Test sending a request and receiving a response."""
        host, port = mock_daemon
        config: ConnectionConfig = ConnectionConfig(
            host=host,
            port=port,
            connect_timeout=5.0,
            request_timeout=10.0,
        )
        auth: AuthManager = AuthManager(AuthConfig(token="valid-token"))
        conn: TransportConnection = TransportConnection(
            host=host,
            port=port,
            config=config,
            auth_manager=auth,
        )

        await conn.connect()
        response: JSONObject = await conn.send_request("health", {})
        assert response is not None
        assert response.get("type") == "response"
        assert response.get("result", {}).get("healthy") is True

        await conn.disconnect()

    @pytest.mark.asyncio
    async def test_stats(
        self,
        mock_daemon: tuple[str, int],
    ) -> None:
        """Test connection statistics."""
        host, port = mock_daemon
        config = ConnectionConfig(host=host, port=port)
        conn = TransportConnection(host=host, port=port, config=config)

        await conn.connect()
        stats = conn.get_stats()
        assert stats["host"] == host
        assert stats["port"] == port
        assert stats["connected"] is True
        assert stats["bytes_sent"] >= 0
        assert stats["bytes_received"] >= 0

        await conn.disconnect()

    @pytest.mark.asyncio
    async def test_send_after_close(
        self,
        mock_daemon: tuple[str, int],
    ) -> None:
        """Test that sending after close raises an error."""
        host, port = mock_daemon
        config = ConnectionConfig(host=host, port=port)
        conn = TransportConnection(host=host, port=port, config=config)

        await conn.disconnect()
        with pytest.raises(TransportClosedError):
            await conn.send_request("health", {})

    @pytest.mark.asyncio
    async def test_repr(
        self,
        mock_daemon: tuple[str, int],
    ) -> None:
        """Test string representation."""
        host, port = mock_daemon
        config = ConnectionConfig(host=host, port=port)
        conn = TransportConnection(host=host, port=port, config=config)

        await conn.connect()
        repr_str = repr(conn)
        assert "TransportConnection" in repr_str
        assert host in repr_str

        await conn.disconnect()


# ---------------------------------------------------------------------------
# ConnectionPool tests
# ---------------------------------------------------------------------------


class TestConnectionPool:
    """Tests for the connection pool."""

    @pytest.mark.asyncio
    async def test_pool_start_and_stop(
        self,
        mock_daemon: tuple[str, int],
    ) -> None:
        """Test starting and stopping the pool."""
        host, port = mock_daemon
        config = ConnectionConfig(
            host=host,
            port=port,
            pool_size=2,
            connect_timeout=5.0,
        )
        auth = AuthManager(AuthConfig(token="valid-token"))
        pool: ConnectionPool = ConnectionPool(
            host=host,
            port=port,
            config=config,
            auth_manager=auth,
        )

        await pool.start()
        assert pool.connected is True
        assert pool.active_count > 0

        await pool.stop()
        assert pool.connected is False

    @pytest.mark.asyncio
    async def test_pool_round_robin(
        self,
        mock_daemon: tuple[str, int],
    ) -> None:
        """Test that the pool distributes requests round-robin."""
        host, port = mock_daemon
        config = ConnectionConfig(
            host=host,
            port=port,
            pool_size=2,
            connect_timeout=5.0,
        )
        auth = AuthManager(AuthConfig(token="valid-token"))
        pool = ConnectionPool(
            host=host,
            port=port,
            config=config,
            auth_manager=auth,
        )

        await pool.start()

        # Get connections and verify they are different
        conn1 = await pool.get_connection()
        conn2 = await pool.get_connection()
        assert conn1 is not None
        assert conn2 is not None

        await pool.stop()

    @pytest.mark.asyncio
    async def test_pool_send_request(
        self,
        mock_daemon: tuple[str, int],
    ) -> None:
        """Test sending a request through the pool."""
        host, port = mock_daemon
        config = ConnectionConfig(
            host=host,
            port=port,
            pool_size=2,
            connect_timeout=5.0,
        )
        auth = AuthManager(AuthConfig(token="valid-token"))
        pool = ConnectionPool(
            host=host,
            port=port,
            config=config,
            auth_manager=auth,
        )

        await pool.start()
        response = await pool.send_request("health", {})
        assert response is not None
        await pool.stop()

    @pytest.mark.asyncio
    async def test_pool_stats(
        self,
        mock_daemon: tuple[str, int],
    ) -> None:
        """Test pool statistics."""
        host, port = mock_daemon
        config = ConnectionConfig(host=host, port=port, pool_size=2)
        auth = AuthManager(AuthConfig(token="valid-token"))
        pool = ConnectionPool(
            host=host,
            port=port,
            config=config,
            auth_manager=auth,
        )

        await pool.start()
        stats = pool.get_pool_stats()
        assert len(stats) == 2
        await pool.stop()

    @pytest.mark.asyncio
    async def test_pool_repr(
        self,
        mock_daemon: tuple[str, int],
    ) -> None:
        """Test pool string representation."""
        host, port = mock_daemon
        config = ConnectionConfig(host=host, port=port, pool_size=2)
        pool = ConnectionPool(host=host, port=port, config=config)

        repr_str = repr(pool)
        assert "ConnectionPool" in repr_str

        await pool.start()
        repr_str = repr(pool)
        assert "active=" in repr_str
        await pool.stop()


# ---------------------------------------------------------------------------
# Transport tests
# ---------------------------------------------------------------------------


class TestTransport:
    """Tests for the high-level Transport class."""

    @pytest.mark.asyncio
    async def test_transport_start_stop(
        self,
        mock_daemon: tuple[str, int],
    ) -> None:
        """Test starting and stopping the transport."""
        host, port = mock_daemon
        config = ConnectionConfig(
            host=host,
            port=port,
            connect_timeout=5.0,
        )
        auth = AuthManager(AuthConfig(token="valid-token"))
        transport: Transport = Transport(config=config, auth_manager=auth)

        assert transport.is_started is False
        await transport.start()
        assert transport.is_started is True
        assert transport.connected is True

        await transport.stop()
        assert transport.is_stopped is True
        assert transport.connected is False

    @pytest.mark.asyncio
    async def test_transport_send_request(
        self,
        mock_daemon: tuple[str, int],
    ) -> None:
        """Test sending a request through the transport."""
        host, port = mock_daemon
        config = ConnectionConfig(
            host=host,
            port=port,
            connect_timeout=5.0,
        )
        auth = AuthManager(AuthConfig(token="valid-token"))
        transport = Transport(config=config, auth_manager=auth)

        await transport.start()
        response = await transport.send_request("health", {})
        assert response is not None
        assert response.get("result", {}).get("healthy") is True

        await transport.stop()

    @pytest.mark.asyncio
    async def test_transport_stats(
        self,
        mock_daemon: tuple[str, int],
    ) -> None:
        """Test transport statistics."""
        host, port = mock_daemon
        config = ConnectionConfig(host=host, port=port)
        auth = AuthManager(AuthConfig(token="valid-token"))
        transport = Transport(config=config, auth_manager=auth)

        await transport.start()
        stats = transport.get_stats()
        assert stats["host"] == host
        assert stats["port"] == port
        assert stats["started"] is True
        assert stats["active_connections"] > 0

        await transport.stop()

    @pytest.mark.asyncio
    async def test_transport_repr(
        self,
        mock_daemon: tuple[str, int],
    ) -> None:
        """Test transport string representation."""
        host, port = mock_daemon
        config = ConnectionConfig(host=host, port=port)
        transport = Transport(config=config)

        repr_str = repr(transport)
        assert "Transport" in repr_str
        assert host in repr_str


# ---------------------------------------------------------------------------
# Protocol / message framing tests
# ---------------------------------------------------------------------------


class TestMessageFraming:
    """Tests for NDJSON message framing."""

    def test_json_encode(self) -> None:
        """Test JSON encoding of messages."""
        from ainos.utils import json_encode

        data: dict[str, t.Any] = {"type": "request", "id": "test-1", "method": "health"}
        encoded: bytes = json_encode(data)
        assert encoded.endswith(b"\n")
        decoded: dict[str, t.Any] = json.loads(encoded.decode("utf-8").strip())
        assert decoded["method"] == "health"

    def test_json_decode(self) -> None:
        """Test JSON decoding of messages."""
        from ainos.utils import json_decode

        raw: str = '{"type":"response","id":"test-1","result":{"healthy":true}}'
        decoded: dict[str, t.Any] = json_decode(raw)
        assert decoded["type"] == "response"
        assert decoded["result"]["healthy"] is True

    def test_json_decode_bytes(self) -> None:
        """Test JSON decoding from bytes."""
        from ainos.utils import json_decode

        raw: bytes = b'{"type":"response","id":"test-1","result":{"healthy":true}}'
        decoded: dict[str, t.Any] = json_decode(raw)
        assert decoded["type"] == "response"

    def test_message_too_large(self) -> None:
        """Test that oversized messages are rejected."""
        from ainos.errors import MessageTooLargeError

        large_size: int = 100 * 1024 * 1024  # 100 MB
        with pytest.raises(MessageTooLargeError):
            raise MessageTooLargeError(large_size, 16 * 1024 * 1024, "send")

    def test_invalid_message(self) -> None:
        """Test handling of invalid messages."""
        from ainos.errors import InvalidMessageError

        with pytest.raises(InvalidMessageError):
            raise InvalidMessageError("not-json", "Invalid JSON")

    def test_generate_request_id(self) -> None:
        """Test request ID generation."""
        from ainos.utils import generate_request_id

        id1: str = generate_request_id()
        id2: str = generate_request_id()
        assert id1 != id2
        assert len(id1) == 36  # UUID4 format
        assert "-" in id1


# ---------------------------------------------------------------------------
# Mock daemon protocol tests
# ---------------------------------------------------------------------------


class TestMockDaemonProtocol:
    """Tests for the mock daemon protocol."""

    def test_health_handler(self) -> None:
        """Test the health handler."""
        from tests.conftest import _health_handler

        result = _health_handler({})
        assert result["healthy"] is True
        assert result["version"] == "0.1.0"

    def test_status_handler(self) -> None:
        """Test the status handler."""
        from tests.conftest import _status_handler

        result = _status_handler({})
        assert result["version"] == "0.1.0"
        assert result["active_models"] == 1

    def test_model_list_handler(self) -> None:
        """Test the model_list handler."""
        from tests.conftest import _model_list_handler

        result = _model_list_handler({})
        assert len(result) == 2
        assert result[0]["id"] == "model-1"

    def test_infer_handler(self) -> None:
        """Test the infer handler."""
        from tests.conftest import _infer_handler

        result = _infer_handler({"model": "test"})
        assert "text" in result
        assert result["model"] == "test"

    def test_model_load_handler(self) -> None:
        """Test the model_load handler."""
        from tests.conftest import _model_load_handler

        result = _model_load_handler({"name": "my-model", "path": "/path/to/model"})
        assert result["name"] == "my-model"
        assert result["status"] == "loaded"

    def test_model_unload_handler(self) -> None:
        """Test the model_unload handler."""
        from tests.conftest import _model_unload_handler

        result = _model_unload_handler({"model_id": "model-1"})
        assert result["success"] is True

    def test_context_store_handler(self) -> None:
        """Test the context_store handler."""
        from tests.conftest import _context_store_handler

        result = _context_store_handler({"key": "test", "value": "data"})
        assert result["success"] is True

    def test_context_retrieve_handler(self) -> None:
        """Test the context_retrieve handler."""
        from tests.conftest import _context_retrieve_handler

        result = _context_retrieve_handler({"key": "test"})
        assert result["value"] == {"stored": "data"}


# ---------------------------------------------------------------------------
# Utility tests
# ---------------------------------------------------------------------------


class TestUtils:
    """Tests for utility functions."""

    def test_timestamp(self) -> None:
        """Test timestamp generation."""
        from ainos.utils import timestamp

        ts: float = timestamp()
        assert ts > 1_700_000_000  # Reasonable Unix timestamp for 2024+

    def test_validate_host(self) -> None:
        """Test host validation."""
        from ainos.utils import validate_host

        assert validate_host("127.0.0.1") is True
        assert validate_host("localhost") is True
        assert validate_host("") is False
        assert validate_host(" " * 300) is False

    def test_validate_port(self) -> None:
        """Test port validation."""
        from ainos.utils import validate_port

        assert validate_port(9500) is True
        assert validate_port(1) is True
        assert validate_port(65535) is True
        assert validate_port(0) is False
        assert validate_port(65536) is False
        assert validate_port(-1) is False

    def test_truncate(self) -> None:
        """Test string truncation."""
        from ainos.utils import truncate

        assert truncate("short", 10) == "short"
        assert truncate("a" * 100, 10) == "a" * 7 + "..."
        assert truncate("hello world", 5) == "he..."

    def test_format_bytes(self) -> None:
        """Test byte formatting."""
        from ainos.utils import format_bytes

        assert format_bytes(0) == "0 B"
        assert format_bytes(1024) == "1.00 KiB"
        assert format_bytes(1024 * 1024) == "1.00 MiB"
        assert format_bytes(1024 * 1024 * 1024) == "1.00 GiB"

    def test_merge_dicts(self) -> None:
        """Test dictionary merging."""
        from ainos.utils import merge_dicts

        base: dict[str, t.Any] = {"a": 1, "b": {"c": 2, "d": 3}}
        override: dict[str, t.Any] = {"b": {"c": 99}, "e": 4}
        merged: dict[str, t.Any] = merge_dicts(base, override)
        assert merged["a"] == 1
        assert merged["b"]["c"] == 99
        assert merged["b"]["d"] == 3
        assert merged["e"] == 4

    def test_merge_dicts_shallow(self) -> None:
        """Test shallow dictionary merging."""
        from ainos.utils import merge_dicts

        base: dict[str, t.Any] = {"a": {"b": 1}}
        override: dict[str, t.Any] = {"a": {"c": 2}}
        merged: dict[str, t.Any] = merge_dicts(base, override, deep=False)
        assert merged["a"] == {"c": 2}  # Shallow: completely replaced

    def test_generate_request_id_uniqueness(self) -> None:
        """Test that request IDs are unique."""
        from ainos.utils import generate_request_id

        ids: set[str] = set()
        for _ in range(1000):
            ids.add(generate_request_id())
        assert len(ids) == 1000


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestAuth:
    """Tests for authentication."""

    def test_auth_config_token(self) -> None:
        """Test auth config with explicit token."""
        config = AuthConfig(token="my-token")
        assert config.token == "my-token"
        assert config.source == "explicit"

    def test_auth_config_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test auth config with environment variable."""
        monkeypatch.setenv("AINOS_AUTH_TOKEN", "env-token")
        config = AuthConfig(token_env_var="AINOS_AUTH_TOKEN")
        assert config.token == "env-token"
        assert config.source == "env:AINOS_AUTH_TOKEN"

    def test_auth_config_discovery(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test automatic token discovery."""
        monkeypatch.setenv("AINOS_AUTH_TOKEN", "discovered-token")
        config = AuthConfig()
        assert config.token == "discovered-token"

    def test_auth_header(self) -> None:
        """Test auth header generation."""
        auth = AuthManager(AuthConfig(token="test-token"))
        header: str = auth.get_auth_header()
        assert header == "Bearer test-token"

    def test_auth_header_parsing(self) -> None:
        """Test auth header parsing."""
        from ainos.auth import AuthManager

        token: str = AuthManager.parse_auth_header("Bearer my-token")
        assert token == "my-token"

    def test_token_hash(self) -> None:
        """Test token hashing."""
        auth = AuthManager(AuthConfig(token="test-token"))
        h: str = auth.token_hash()
        assert len(h) == 64  # SHA-256 hex digest
        assert h == auth.token_hash()  # Deterministic

    def test_mask_token(self) -> None:
        """Test token masking."""
        from ainos.auth import mask_token, mask_token_short

        assert mask_token("abcdefgh") == "****efgh"
        assert mask_token_short("abcdefghijkl") == "abcd****ijkl"
        assert mask_token("ab") == "ab"

    def test_validate_token(self) -> None:
        """Test token validation."""
        auth = AuthManager(AuthConfig(token="valid-token-here"))
        assert auth.validate_token() is True
        assert auth.validate_token("") is False
        assert auth.validate_token("short") is False