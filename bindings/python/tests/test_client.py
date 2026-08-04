"""
Ainos SDK - Client Tests
=========================

Tests for the AinosClient class, covering connection management, inference,
model management, context store, health checks, and error handling.
"""

from __future__ import annotations

import asyncio
import json
import typing as t
from typing import Any, AsyncGenerator

import pytest

from ainos import AinosClient
from ainos.errors import (
    AuthenticationError,
    ConnectionError,
    ConnectionTimeoutError,
    InferenceError,
    ModelLoadError,
    ModelNotFoundError,
    ModelNotLoadedError,
    RequestError,
    RequestTimeoutError,
    TransportClosedError,
)
from ainos.types import (
    HealthStatus,
    InferenceChunk,
    InferenceResponse,
    ModelInfo,
    SystemStatus,
    TokenUsage,
)

# Re-export the mock daemon error for test use
from tests.conftest import MockDaemonError, mock_daemon, mock_handlers


# ---------------------------------------------------------------------------
# Connection tests
# ---------------------------------------------------------------------------


class TestConnection:
    """Tests for connection management."""

    @pytest.mark.asyncio
    async def test_connect_success(
        self,
        mock_daemon: tuple[str, int],
    ) -> None:
        """Test successful connection to the daemon."""
        host, port = mock_daemon
        client: AinosClient = AinosClient(
            host=host,
            port=port,
            auth_token="valid-token",
            auto_connect=False,
            connect_timeout=5.0,
        )
        result: bool = await client.connect()
        assert result is True
        assert client.connected is True
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_connect_with_auth(
        self,
        mock_daemon: tuple[str, int],
    ) -> None:
        """Test connection with valid authentication."""
        host, port = mock_daemon
        client: AinosClient = AinosClient(
            host=host,
            port=port,
            auth_token="valid-token",
            auto_connect=False,
        )
        await client.connect()
        assert client.connected is True
        assert client.is_authenticated is True
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_connect_timeout(self) -> None:
        """Test connection timeout to an unreachable host."""
        client: AinosClient = AinosClient(
            host="127.0.0.1",
            port=1,  # Port 1 is unlikely to be open
            connect_timeout=0.5,
            auto_connect=False,
        )
        with pytest.raises((ConnectionError, ConnectionTimeoutError, OSError)):
            await client.connect()

    @pytest.mark.asyncio
    async def test_double_connect(
        self,
        client: AinosClient,
    ) -> None:
        """Test that connecting twice is a no-op."""
        result: bool = await client.connect()
        assert result is True
        assert client.connected is True

    @pytest.mark.asyncio
    async def test_disconnect(
        self,
        client: AinosClient,
    ) -> None:
        """Test disconnection."""
        assert client.connected is True
        await client.disconnect()
        assert client.connected is False

    @pytest.mark.asyncio
    async def test_double_disconnect(
        self,
        client: AinosClient,
    ) -> None:
        """Test that disconnecting twice is safe."""
        await client.disconnect()
        await client.disconnect()
        assert client.connected is False

    @pytest.mark.asyncio
    async def test_send_after_disconnect(
        self,
        client: AinosClient,
    ) -> None:
        """Test that sending a request after disconnect returns a health status."""
        await client.disconnect()
        # health() catches the error and returns an unhealthy status
        health: HealthStatus = await client.health()
        assert health.healthy is False


# ---------------------------------------------------------------------------
# Health and status tests
# ---------------------------------------------------------------------------


class TestHealthAndStatus:
    """Tests for health and status endpoints."""

    @pytest.mark.asyncio
    async def test_health(self, client: AinosClient) -> None:
        """Test health check."""
        health: HealthStatus = await client.health()
        assert health.healthy is True
        assert health.status == "running"
        assert health.version == "0.1.0"
        assert health.uptime_seconds > 0
        assert health.active_models == 1

    @pytest.mark.asyncio
    async def test_health_as_dict(self, client: AinosClient) -> None:
        """Test health check returns a HealthStatus object."""
        health: HealthStatus = await client.health()
        assert isinstance(health, HealthStatus)
        assert isinstance(health.healthy, bool)
        assert isinstance(health.status, str)

    @pytest.mark.asyncio
    async def test_status(self, client: AinosClient) -> None:
        """Test system status."""
        status: SystemStatus = await client.status()
        assert isinstance(status, SystemStatus)
        assert status.version == "0.1.0"
        assert status.uptime_seconds == 3600.0
        assert status.active_models == 1
        assert status.total_models == 2
        assert status.memory_used_mb > 0
        assert status.cpu_usage_percent >= 0
        assert status.gpu_usage_percent is not None
        assert status.active_requests == 2
        assert status.status == "running"

    @pytest.mark.asyncio
    async def test_status_fields(self, client: AinosClient) -> None:
        """Test that all status fields are populated correctly."""
        status: SystemStatus = await client.status()
        assert status.memory_total_mb == 16384.0
        assert status.gpu_memory_used_mb == 2048.0
        assert status.gpu_memory_total_mb == 8192.0
        assert status.queued_requests == 0
        assert status.errors is None


# ---------------------------------------------------------------------------
# Inference tests
# ---------------------------------------------------------------------------


class TestInference:
    """Tests for inference operations."""

    @pytest.mark.asyncio
    async def test_infer_basic(self, client: AinosClient) -> None:
        """Test basic non-streaming inference."""
        response: InferenceResponse = await client.infer(
            model="test-model",
            prompt="Hello, world!",
        )
        assert isinstance(response, InferenceResponse)
        assert response.text == "This is a mock inference response from the Ainos daemon."
        assert response.finish_reason == "stop"
        assert response.model == "test-model"

    @pytest.mark.asyncio
    async def test_infer_with_usage(self, client: AinosClient) -> None:
        """Test that inference returns token usage."""
        response: InferenceResponse = await client.infer(
            model="test-model",
            prompt="Hello",
        )
        assert response.usage is not None
        assert isinstance(response.usage, TokenUsage)
        assert response.usage.prompt_tokens == 10
        assert response.usage.completion_tokens == 8
        assert response.usage.total_tokens == 18

    @pytest.mark.asyncio
    async def test_infer_with_params(self, client: AinosClient) -> None:
        """Test inference with additional parameters."""
        response: InferenceResponse = await client.infer(
            model="test-model",
            prompt="Hello",
            temperature=0.8,
            max_tokens=100,
            top_p=0.9,
            top_k=40,
            stop=["\n", "###"],
            presence_penalty=0.5,
            frequency_penalty=0.5,
        )
        assert response.text is not None

    @pytest.mark.asyncio
    async def test_infer_with_system_prompt(self, client: AinosClient) -> None:
        """Test inference with system prompt."""
        response: InferenceResponse = await client.infer(
            model="test-model",
            prompt="Hello",
            system_prompt="Be helpful.",
        )
        assert response.text is not None

    @pytest.mark.asyncio
    async def test_infer_streaming(self, client: AinosClient) -> None:
        """Test streaming inference."""
        stream = client.infer_stream(
            model="test-model",
            prompt="Hello",
            max_tokens=50,
        )
        assert stream is not None

    @pytest.mark.asyncio
    async def test_infer_model_not_found(
        self,
        mock_daemon: tuple[str, int],
        mock_handlers: dict[str, t.Callable[[dict[str, t.Any]], dict[str, t.Any]]],
    ) -> None:
        """Test error handling when model is not found."""
        # Override the infer handler to return a model-not-loaded error
        def error_handler(params: dict[str, t.Any]) -> dict[str, t.Any]:
            raise MockDaemonError(-32004, "Model not loaded")

        mock_handlers["infer"] = error_handler

        host, port = mock_daemon
        client = AinosClient(
            host=host,
            port=port,
            auth_token="valid-token",
            auto_connect=False,
        )
        await client.connect()

        with pytest.raises(ModelNotLoadedError):
            await client.infer(model="unknown-model", prompt="Hello")

        await client.disconnect()


# ---------------------------------------------------------------------------
# Model management tests
# ---------------------------------------------------------------------------


class TestModelManagement:
    """Tests for model management operations."""

    @pytest.mark.asyncio
    async def test_model_list(self, client: AinosClient) -> None:
        """Test listing models."""
        models: list[ModelInfo] = await client.model_list()
        assert len(models) == 2
        assert isinstance(models[0], ModelInfo)

    @pytest.mark.asyncio
    async def test_model_list_contents(self, client: AinosClient) -> None:
        """Test model list contents."""
        models: list[ModelInfo] = await client.model_list()

        model1: ModelInfo = models[0]
        assert model1.id == "model-1"
        assert model1.name == "test-model"
        assert model1.status == "loaded"
        assert model1.backend == "llama.cpp"
        assert model1.device == "cuda:0"
        assert model1.context_length == 4096
        assert model1.size_bytes == 4_000_000_000

        model2: ModelInfo = models[1]
        assert model2.id == "model-2"
        assert model2.name == "other-model"
        assert model2.status == "unloaded"
        assert model2.loaded_at is None

    @pytest.mark.asyncio
    async def test_model_load(self, client: AinosClient) -> None:
        """Test loading a model."""
        info: ModelInfo = await client.model_load(
            name="my-model",
            path="/models/my-model.gguf",
            backend="llama.cpp",
            context_length=8192,
        )
        assert isinstance(info, ModelInfo)
        assert info.name == "my-model"
        assert info.status == "loaded"
        assert info.backend == "llama.cpp"
        assert info.context_length == 8192

    @pytest.mark.asyncio
    async def test_model_unload(self, client: AinosClient) -> None:
        """Test unloading a model."""
        result: bool = await client.model_unload("model-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_model_manager(self, client: AinosClient) -> None:
        """Test model manager convenience methods."""
        mgr = client.model_manager
        assert mgr is not None

        # is_loaded
        loaded: bool = await mgr.is_loaded("model-1")
        assert loaded is True

        # is_busy
        busy: bool = await mgr.is_busy("model-1")
        assert busy is False

        # find_model
        found: list[ModelInfo] = await mgr.find_model(loaded=True)
        assert len(found) >= 1


# ---------------------------------------------------------------------------
# Context store tests
# ---------------------------------------------------------------------------


class TestContextStore:
    """Tests for context store operations."""

    @pytest.mark.asyncio
    async def test_context_store(self, client: AinosClient) -> None:
        """Test storing a value in the context store."""
        result: bool = await client.context_store(
            key="test_key",
            value={"hello": "world"},
            ttl=60,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_context_retrieve(self, client: AinosClient) -> None:
        """Test retrieving a value from the context store."""
        value: t.Any = await client.context_retrieve("test_key")
        assert value == {"stored": "data"}

    @pytest.mark.asyncio
    async def test_context_store_roundtrip(self, client: AinosClient) -> None:
        """Test store then retrieve."""
        await client.context_store("roundtrip", 42, ttl=3600)
        value = await client.context_retrieve("roundtrip")
        assert value is not None


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestAuthentication:
    """Tests for authentication."""

    @pytest.mark.asyncio
    async def test_auth_success(
        self,
        mock_daemon: tuple[str, int],
    ) -> None:
        """Test successful authentication."""
        host, port = mock_daemon
        client: AinosClient = AinosClient(
            host=host,
            port=port,
            auth_token="valid-token",
            auto_connect=False,
        )
        await client.connect()
        assert client.connected is True
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_auth_no_token(
        self,
        mock_daemon: tuple[str, int],
    ) -> None:
        """Test connection without a token (should work if daemon allows)."""
        host, port = mock_daemon
        client: AinosClient = AinosClient(
            host=host,
            port=port,
            auto_connect=False,
        )
        await client.connect()
        assert client.connected is True
        await client.disconnect()


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_connection_error(self) -> None:
        """Test connection error to an unreachable daemon."""
        client: AinosClient = AinosClient(
            host="192.0.2.1",  # TEST-NET address, unreachable
            port=9500,
            connect_timeout=0.5,
            auto_connect=False,
        )
        with pytest.raises((ConnectionError, OSError)):
            await client.connect()

    @pytest.mark.asyncio
    async def test_health_after_disconnect(
        self,
        client: AinosClient,
    ) -> None:
        """Test that health check returns unhealthy after disconnect."""
        await client.disconnect()
        # health() catches transport errors and returns unhealthy status
        health: HealthStatus = await client.health()
        assert health.healthy is False

    @pytest.mark.asyncio
    async def test_context_manager(
        self,
        mock_daemon: tuple[str, int],
    ) -> None:
        """Test using the client as an async context manager."""
        host, port = mock_daemon
        async with AinosClient(
            host=host,
            port=port,
            auth_token="valid-token",
            auto_connect=False,
            connect_timeout=5.0,
        ) as client:
            health: HealthStatus = await client.health()
            assert health.healthy is True
        assert client.connected is False


# ---------------------------------------------------------------------------
# Client configuration tests
# ---------------------------------------------------------------------------


class TestClientConfiguration:
    """Tests for client configuration."""

    def test_default_config(self) -> None:
        """Test default client configuration."""
        client: AinosClient = AinosClient(
            auto_connect=False,
        )
        assert client.host == "127.0.0.1"
        assert client.port == 9500
        assert client.config.connect_timeout == 10.0
        assert client.config.request_timeout == 60.0
        assert client.config.reconnect_attempts == 3
        assert client.config.pool_size == 4

    def test_custom_config(self) -> None:
        """Test custom client configuration."""
        client: AinosClient = AinosClient(
            host="10.0.0.1",
            port=9000,
            connect_timeout=30.0,
            request_timeout=120.0,
            reconnect_attempts=5,
            pool_size=8,
            auto_connect=False,
        )
        assert client.host == "10.0.0.1"
        assert client.port == 9000
        assert client.config.connect_timeout == 30.0
        assert client.config.request_timeout == 120.0
        assert client.config.reconnect_attempts == 5
        assert client.config.pool_size == 8

    def test_ssl_config(self) -> None:
        """Test SSL configuration."""
        client: AinosClient = AinosClient(
            host="10.0.0.1",
            port=9500,
            ssl=True,
            ssl_ca_cert="/path/to/ca.pem",
            auto_connect=False,
        )
        assert client.config.ssl is True
        assert client.config.ssl_ca_cert == "/path/to/ca.pem"

    def test_auth_config(self) -> None:
        """Test authentication configuration."""
        client: AinosClient = AinosClient(
            auth_token="my-secret-token",
            auto_connect=False,
        )
        assert client._auth_manager is not None

    def test_repr(self) -> None:
        """Test string representation."""
        client: AinosClient = AinosClient(
            host="127.0.0.1",
            port=9500,
            auto_connect=False,
        )
        repr_str: str = repr(client)
        assert "AinosClient" in repr_str
        assert "127.0.0.1" in repr_str
        assert "9500" in repr_str