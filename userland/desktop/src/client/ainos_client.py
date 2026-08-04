#!/usr/bin/env python3
"""Ainos Desktop - Backend Client.

This module provides the high-level client for communicating with the
Ainos backend service. It manages connections, model operations,
inference requests, and system monitoring.
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Callable

from .transport import TCPTransport, TransportError, ConnectionError, TimeoutError
from .models import (
    ModelInfo,
    ModelStatus,
    InferenceRequest,
    InferenceResponse,
    ContextEntry,
    SystemMetrics,
    ConnectionConfig,
    BackendInfo,
    GenerationConfig,
    TokenUsage,
)

logger = logging.getLogger(__name__)


class AinosClient:
    """High-level client for the Ainos AI backend.

    Provides a clean API for model management, inference, and monitoring.
    Operations are asynchronous and non-blocking by design.
    """

    def __init__(self, config: ConnectionConfig | None = None):
        """Initialize the Ainos client.

        Args:
            config: Connection configuration. Uses defaults if not provided.
        """
        self._config = config or ConnectionConfig()
        self._transport = TCPTransport(
            host=self._config.host,
            port=self._config.port,
            use_ssl=self._config.use_ssl,
            timeout_ms=self._config.timeout_ms,
            reconnect_interval_ms=self._config.reconnect_interval_ms,
            max_reconnect_attempts=self._config.max_reconnect_attempts,
            heartbeat_interval_ms=self._config.heartbeat_interval_ms,
        )

        # Connection state
        self._connected = False
        self._backend_info: BackendInfo | None = None

        # Callbacks
        self._on_connected: Callable | None = None
        self._on_disconnected: Callable | None = None
        self._on_error: Callable | None = None
        self._on_model_update: Callable | None = None
        self._on_metrics_update: Callable | None = None

        # Cache
        self._models: list[ModelInfo] = []
        self._last_metrics: SystemMetrics | None = None

        # Async lock
        self._lock = asyncio.Lock()

        # Setup transport callbacks
        self._transport.set_callbacks(
            on_connected=self._on_transport_connected,
            on_disconnected=self._on_transport_disconnected,
            on_error=self._on_transport_error,
        )

        # Event loop reference
        self._loop: asyncio.AbstractEventLoop | None = None

        logger.info("AinosClient initialized for %s:%d", self._config.host, self._config.port)

    @property
    def is_connected(self) -> bool:
        """Check if the client is connected to the backend.

        Returns:
            True if connected.
        """
        return self._connected and self._transport.is_connected

    @property
    def config(self) -> ConnectionConfig:
        """Get the current connection configuration.

        Returns:
            The ConnectionConfig instance.
        """
        return self._config

    @property
    def backend_info(self) -> BackendInfo | None:
        """Get cached backend information.

        Returns:
            BackendInfo or None if not yet fetched.
        """
        return self._backend_info

    @property
    def models(self) -> list[ModelInfo]:
        """Get cached model list.

        Returns:
            List of ModelInfo objects.
        """
        return self._models

    def set_callbacks(
        self,
        on_connected: Callable | None = None,
        on_disconnected: Callable | None = None,
        on_error: Callable | None = None,
        on_model_update: Callable | None = None,
        on_metrics_update: Callable | None = None,
    ) -> None:
        """Set event callbacks for client events.

        Args:
            on_connected: Called when connected to backend.
            on_disconnected: Called when disconnected.
            on_error: Called on errors.
            on_model_update: Called when model list is updated.
            on_metrics_update: Called when system metrics are updated.
        """
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._on_error = on_error
        self._on_model_update = on_model_update
        self._on_metrics_update = on_metrics_update

    async def connect(self) -> bool:
        """Connect to the Ainos backend.

        Returns:
            True if connection was successful.

        Raises:
            ConnectionError: If connection fails.
        """
        self._loop = asyncio.get_event_loop()

        try:
            result = await self._transport.connect()
            if result:
                self._connected = True
                # Fetch initial backend info
                try:
                    self._backend_info = await self.get_backend_info()
                except Exception as e:
                    logger.warning("Failed to fetch backend info: %s", e)
                # Fetch initial model list
                try:
                    self._models = await self.list_models()
                except Exception as e:
                    logger.warning("Failed to fetch models: %s", e)
            return result
        except (ConnectionError, TimeoutError) as e:
            self._connected = False
            logger.error("Connection failed: %s", e)
            raise

    async def disconnect(self) -> None:
        """Disconnect from the backend."""
        self._connected = False
        await self._transport.disconnect()

    async def get_backend_info(self) -> BackendInfo:
        """Get information about the backend service.

        Returns:
            BackendInfo with version, status, and capabilities.

        Raises:
            TransportError: If the request fails.
        """
        request_id = str(uuid.uuid4())
        response = await self._transport.send_request(
            request_id, "get_backend_info"
        )
        self._backend_info = BackendInfo.from_dict(response)
        return self._backend_info

    async def list_models(self) -> list[ModelInfo]:
        """List all available models from the backend.

        Returns:
            List of ModelInfo objects.

        Raises:
            TransportError: If the request fails.
        """
        request_id = str(uuid.uuid4())
        response = await self._transport.send_request(
            request_id, "list_models"
        )

        models_data = response.get("models", [])
        self._models = [ModelInfo.from_dict(m) for m in models_data]

        # Notify
        if self._on_model_update:
            try:
                self._on_model_update(self._models)
            except Exception as e:
                logger.error("Error in on_model_update: %s", e)

        return self._models

    async def load_model(self, model_id: str, options: dict[str, Any] | None = None) -> ModelInfo:
        """Load a model on the backend.

        Args:
            model_id: Identifier of the model to load.
            options: Optional loading parameters (quantization, GPU layers, etc.).

        Returns:
            Updated ModelInfo with current status.

        Raises:
            TransportError: If the request fails.
        """
        request_id = str(uuid.uuid4())
        params = {"model_id": model_id, "options": options or {}}
        response = await self._transport.send_request(
            request_id, "load_model", params
        )

        model_info = ModelInfo.from_dict(response.get("model", {}))
        self._update_model_in_cache(model_info)

        if self._on_model_update:
            try:
                self._on_model_update(self._models)
            except Exception as e:
                logger.error("Error in on_model_update: %s", e)

        return model_info

    async def unload_model(self, model_id: str) -> ModelInfo:
        """Unload a model from the backend.

        Args:
            model_id: Identifier of the model to unload.

        Returns:
            Updated ModelInfo with current status.

        Raises:
            TransportError: If the request fails.
        """
        request_id = str(uuid.uuid4())
        response = await self._transport.send_request(
            request_id, "unload_model", {"model_id": model_id}
        )

        model_info = ModelInfo.from_dict(response.get("model", {}))
        self._update_model_in_cache(model_info)

        if self._on_model_update:
            try:
                self._on_model_update(self._models)
            except Exception as e:
                logger.error("Error in on_model_update: %s", e)

        return model_info

    async def get_model_info(self, model_id: str) -> ModelInfo:
        """Get detailed information about a specific model.

        Args:
            model_id: Identifier of the model.

        Returns:
            ModelInfo with detailed model information.

        Raises:
            TransportError: If the request fails.
        """
        request_id = str(uuid.uuid4())
        response = await self._transport.send_request(
            request_id, "get_model_info", {"model_id": model_id}
        )

        model_info = ModelInfo.from_dict(response.get("model", {}))
        self._update_model_in_cache(model_info)
        return model_info

    async def infer(
        self,
        request: InferenceRequest,
        on_chunk: Callable[[InferenceResponse], None] | None = None,
    ) -> InferenceResponse:
        """Run inference on a model.

        Args:
            request: The inference request with prompt and config.
            on_chunk: Optional callback for streaming chunks.

        Returns:
            Final InferenceResponse with generated text.

        Raises:
            TransportError: If the request fails.
        """
        if on_chunk:

            def chunk_handler(data: dict[str, Any]) -> None:
                response = InferenceResponse.from_dict(data)
                try:
                    on_chunk(response)
                except Exception as e:
                    logger.error("Error in chunk handler: %s", e)

            response_data = await self._transport.send_stream_request(
                request.id,
                "infer",
                request.to_dict(),
                on_chunk=chunk_handler,
            )
        else:
            response_data = await self._transport.send_request(
                request.id, "infer", request.to_dict()
            )

        return InferenceResponse.from_dict(response_data.get("response", {}))

    async def cancel_inference(self, request_id: str) -> bool:
        """Cancel a running inference request.

        Args:
            request_id: ID of the request to cancel.

        Returns:
            True if the request was cancelled successfully.

        Raises:
            TransportError: If the request fails.
        """
        response = await self._transport.send_request(
            request_id, "cancel_inference", {"request_id": request_id}
        )
        return response.get("cancelled", False)

    async def get_system_metrics(self) -> SystemMetrics:
        """Get current system performance metrics.

        Returns:
            SystemMetrics with CPU, memory, GPU, and other metrics.

        Raises:
            TransportError: If the request fails.
        """
        request_id = str(uuid.uuid4())
        response = await self._transport.send_request(
            request_id, "get_system_metrics"
        )

        self._last_metrics = SystemMetrics.from_dict(response.get("metrics", {}))

        if self._on_metrics_update:
            try:
                self._on_metrics_update(self._last_metrics)
            except Exception as e:
                logger.error("Error in on_metrics_update: %s", e)

        return self._last_metrics

    async def list_contexts(self) -> list[dict[str, Any]]:
        """List all inference contexts.

        Returns:
            List of context summary dictionaries.

        Raises:
            TransportError: If the request fails.
        """
        request_id = str(uuid.uuid4())
        response = await self._transport.send_request(
            request_id, "list_contexts"
        )
        return response.get("contexts", [])

    async def get_context(self, context_id: str) -> list[ContextEntry]:
        """Get all entries in a context.

        Args:
            context_id: ID of the context.

        Returns:
            List of ContextEntry objects.

        Raises:
            TransportError: If the request fails.
        """
        request_id = str(uuid.uuid4())
        response = await self._transport.send_request(
            request_id, "get_context", {"context_id": context_id}
        )
        entries = response.get("entries", [])
        return [ContextEntry.from_dict(e) for e in entries]

    async def delete_context(self, context_id: str) -> bool:
        """Delete an inference context.

        Args:
            context_id: ID of the context to delete.

        Returns:
            True if deletion was successful.

        Raises:
            TransportError: If the request fails.
        """
        request_id = str(uuid.uuid4())
        response = await self._transport.send_request(
            request_id, "delete_context", {"context_id": context_id}
        )
        return response.get("deleted", False)

    async def clear_all_contexts(self) -> bool:
        """Clear all inference contexts.

        Returns:
            True if all contexts were cleared.

        Raises:
            TransportError: If the request fails.
        """
        request_id = str(uuid.uuid4())
        response = await self._transport.send_request(
            request_id, "clear_all_contexts"
        )
        return response.get("cleared", False)

    async def search_contexts(
        self, query: str, max_results: int = 50
    ) -> list[dict[str, Any]]:
        """Search across contexts for matching content.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.

        Returns:
            List of matching context entries with metadata.

        Raises:
            TransportError: If the request fails.
        """
        request_id = str(uuid.uuid4())
        response = await self._transport.send_request(
            request_id,
            "search_contexts",
            {"query": query, "max_results": max_results},
        )
        return response.get("results", [])

    async def export_context(self, context_id: str, format: str = "json") -> str:
        """Export a context in the specified format.

        Args:
            context_id: ID of the context to export.
            format: Export format ('json', 'markdown', 'text').

        Returns:
            Exported context as a string.

        Raises:
            TransportError: If the request fails.
        """
        request_id = str(uuid.uuid4())
        response = await self._transport.send_request(
            request_id,
            "export_context",
            {"context_id": context_id, "format": format},
        )
        return response.get("content", "")

    async def send_event(
        self, event_type: str, data: dict[str, Any] | None = None
    ) -> None:
        """Send a custom event to the backend.

        Args:
            event_type: Event type identifier.
            data: Event data payload.

        Raises:
            TransportError: If the request fails.
        """
        await self._transport.send_event(event_type, data)

    async def health_check(self) -> dict[str, Any]:
        """Perform a health check on the backend.

        Returns:
            Health status dictionary with 'status' and 'timestamp'.

        Raises:
            TransportError: If the request fails.
        """
        request_id = str(uuid.uuid4())
        try:
            response = await self._transport.send_request(
                request_id, "health_check", timeout_ms=5000
            )
            return response
        except (ConnectionError, TimeoutError) as e:
            return {"status": "unreachable", "error": str(e), "timestamp": time.time()}

    def _update_model_in_cache(self, model: ModelInfo) -> None:
        """Update a model in the local cache.

        Args:
            model: ModelInfo to update or add.
        """
        for i, m in enumerate(self._models):
            if m.id == model.id:
                self._models[i] = model
                return
        self._models.append(model)

    def _on_transport_connected(self) -> None:
        """Handle transport connection event."""
        self._connected = True
        logger.info("Client connected to backend")

        if self._on_connected:
            try:
                self._on_connected()
            except Exception as e:
                logger.error("Error in on_connected: %s", e)

    def _on_transport_disconnected(self) -> None:
        """Handle transport disconnection event."""
        self._connected = False
        logger.warning("Client disconnected from backend")

        if self._on_disconnected:
            try:
                self._on_disconnected()
            except Exception as e:
                logger.error("Error in on_disconnected: %s", e)

    def _on_transport_error(self, error: str) -> None:
        """Handle transport error event.

        Args:
            error: Error description string.
        """
        logger.error("Transport error: %s", error)

        if self._on_error:
            try:
                self._on_error(error)
            except Exception as e:
                logger.error("Error in on_error: %s", e)

    async def __aenter__(self) -> "AinosClient":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, *args) -> None:
        """Async context manager exit."""
        await self.disconnect()