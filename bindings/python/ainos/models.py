"""
Ainos SDK - Model Management
=============================

Provides the ModelManager class for managing models loaded in the Ainos
daemon.

Models are the core unit of inference. The daemon can load, unload, and
manage multiple models simultaneously. The ModelManager provides a
client-side interface for these operations.

Classes:
    - ModelManager: High-level model management operations.
    - ModelConfig: Configuration for loading a model.
    - ModelRegistry: Local cache of model metadata.

Usage::

    manager = ModelManager(client)
    models = await manager.list_models()
    info = await manager.load_model("my-model", "/path/to/model.gguf")
    await manager.unload_model(info.id)
"""

from __future__ import annotations

import logging
import typing as t
from dataclasses import dataclass, field
from enum import Enum

from ainos.errors import (
    ModelBusyError,
    ModelError,
    ModelLoadError,
    ModelNotFoundError,
    ModelNotLoadedError,
    ModelUnloadError,
)
from ainos.types import JSONObject, ModelInfo, ModelConfig as ModelConfigType

log: logging.Logger = logging.getLogger("ainos.models")


# ---------------------------------------------------------------------------
# Model status enum
# ---------------------------------------------------------------------------


class ModelStatus(str, Enum):
    """Enumeration of possible model statuses.

    Attributes:
        UNKNOWN: Status is not known.
        LOADING: Model is being loaded into memory.
        LOADED: Model is loaded and ready for inference.
        UNLOADING: Model is being unloaded.
        UNLOADED: Model is not loaded.
        ERROR: Model encountered an error.
        BUSY: Model is busy processing a request.
    """

    UNKNOWN = "unknown"
    LOADING = "loading"
    LOADED = "loaded"
    UNLOADING = "unloading"
    UNLOADED = "unloaded"
    ERROR = "error"
    BUSY = "busy"


# ---------------------------------------------------------------------------
# Model events
# ---------------------------------------------------------------------------


@dataclass
class ModelEvent:
    """An event related to model lifecycle.

    Attributes:
        type: Event type (``"loaded"``, ``"unloaded"``, ``"error"``).
        model_id: The affected model's ID.
        timestamp: When the event occurred.
        detail: Optional additional detail.
    """

    type: str
    model_id: str
    timestamp: float
    detail: t.Optional[str] = None


# ---------------------------------------------------------------------------
# ModelRegistry
# ---------------------------------------------------------------------------


class ModelRegistry:
    """A local cache of model metadata.

    The registry maintains an up-to-date view of all models known to the
    daemon. It can be refreshed on demand.

    Attributes:
        models: Dictionary mapping model IDs to ModelInfo.
    """

    def __init__(self) -> None:
        """Initialise an empty registry."""
        self._models: t.Dict[str, ModelInfo] = {}
        self._lock: t.Any = None  # Would be asyncio.Lock in async context
        self._last_refresh: float = 0.0
        self._events: t.List[ModelEvent] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def models(self) -> t.Dict[str, ModelInfo]:
        """Get the model registry as a dictionary."""
        return dict(self._models)

    @property
    def model_count(self) -> int:
        """Number of models in the registry."""
        return len(self._models)

    @property
    def last_refresh(self) -> float:
        """Unix timestamp of the last refresh."""
        return self._last_refresh

    @property
    def loaded_models(self) -> t.List[ModelInfo]:
        """Get only loaded models."""
        return [
            m for m in self._models.values()
            if m.status == ModelStatus.LOADED.value
        ]

    # ------------------------------------------------------------------
    # Registry operations
    # ------------------------------------------------------------------

    def update(self, models: t.List[ModelInfo]) -> None:
        """Update the registry with a list of models.

        Args:
            models: List of ModelInfo instances to update or add.
        """
        for model in models:
            self._models[model.id] = model

    def update_one(self, model: ModelInfo) -> None:
        """Update or add a single model in the registry.

        Args:
            model: The ModelInfo to update or add.
        """
        self._models[model.id] = model

    def remove(self, model_id: str) -> t.Optional[ModelInfo]:
        """Remove a model from the registry.

        Args:
            model_id: The ID of the model to remove.

        Returns:
            The removed ModelInfo, or None if the model was not found.
        """
        return self._models.pop(model_id, None)

    def get(self, model_id: str) -> t.Optional[ModelInfo]:
        """Get a model by ID.

        Args:
            model_id: The model identifier.

        Returns:
            The ModelInfo, or None if not found.
        """
        return self._models.get(model_id)

    def get_by_name(self, name: str) -> t.Optional[ModelInfo]:
        """Find a model by its human-readable name.

        Args:
            name: The model name.

        Returns:
            The first ModelInfo with a matching name, or None.
        """
        for model in self._models.values():
            if model.name == name:
                return model
        return None

    def clear(self) -> None:
        """Clear all models from the registry."""
        self._models.clear()

    # ------------------------------------------------------------------
        # Events
    # ------------------------------------------------------------------

    def add_event(self, event: ModelEvent) -> None:
        """Record a model lifecycle event.

        Args:
            event: The event to record.
        """
        self._events.append(event)
        # Keep only the last 100 events
        if len(self._events) > 100:
            self._events = self._events[-100:]

    def get_events(
        self,
        *,
        model_id: t.Optional[str] = None,
        limit: int = 10,
    ) -> t.List[ModelEvent]:
        """Get recent model events, optionally filtered by model ID.

        Args:
            model_id: Optional model ID to filter by.
            limit: Maximum number of events to return.

        Returns:
            A list of recent ModelEvent instances.
        """
        events: t.List[ModelEvent] = self._events
        if model_id:
            events = [e for e in events if e.model_id == model_id]
        return events[-limit:]

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> JSONObject:
        """Convert the registry to a JSON-compatible dictionary.

        Returns:
            A dictionary with model IDs as keys and model info dicts as values.
        """
        return {
            mid: {
                "id": info.id,
                "name": info.name,
                "path": info.path,
                "status": info.status,
                "backend": info.backend,
                "size_bytes": info.size_bytes,
                "device": info.device,
                "context_length": info.context_length,
            }
            for mid, info in self._models.items()
        }

    def __repr__(self) -> str:
        """Return a string representation of the registry."""
        loaded: int = len(self.loaded_models)
        return (
            f"ModelRegistry(models={self.model_count}, "
            f"loaded={loaded})"
        )


# ---------------------------------------------------------------------------
# ModelManager
# ---------------------------------------------------------------------------


class ModelManager:
    """High-level model management interface.

    The ModelManager wraps the AinosClient's model-related RPC methods and
    provides a convenient, error-safe API for managing models.

    It maintains a local registry of model metadata for fast lookups.

    Attributes:
        client: The AinosClient instance used for RPC calls.
        registry: The local model registry.
    """

    def __init__(
        self,
        client: t.Any,  # Forward reference to AinosClient
    ) -> None:
        """Initialise the model manager.

        Args:
            client: An AinosClient instance used for RPC calls.
        """
        self._client: t.Any = client
        self.registry: ModelRegistry = ModelRegistry()

    # ------------------------------------------------------------------
    # Model operations
    # ------------------------------------------------------------------

    async def list_models(
        self,
        *,
        refresh: bool = True,
    ) -> t.List[ModelInfo]:
        """List all models known to the daemon.

        Args:
            refresh: If True, fetch fresh data from the daemon instead of
                using the cached registry.

        Returns:
            A list of ModelInfo instances.

        Raises:
            ConnectionError: If the daemon is unreachable.
            ModelError: If the daemon returns an error.
        """
        if refresh or self.registry.model_count == 0:
            try:
                response: JSONObject = await self._client._send_request(
                    "model_list",
                    {},
                )
                models_data: t.List[JSONObject] = response.get("result", [])
                models: t.List[ModelInfo] = [
                    ModelInfo.from_dict(m) for m in models_data
                ]
                self.registry.update(models)
                return models
            except Exception as exc:
                raise ModelError(
                    "Failed to list models",
                    cause=exc,
                ) from exc

        return list(self.registry.models.values())

    async def get_model(
        self,
        model_id: str,
        *,
        refresh: bool = False,
    ) -> ModelInfo:
        """Get information about a specific model.

        Args:
            model_id: The model identifier.
            refresh: If True, fetch fresh data from the daemon.

        Returns:
            The ModelInfo for the requested model.

        Raises:
            ModelNotFoundError: If the model is not found.
            ConnectionError: If the daemon is unreachable.
        """
        # Check local cache first
        if not refresh:
            cached: t.Optional[ModelInfo] = self.registry.get(model_id)
            if cached is not None:
                return cached

        # Get by name if not found by ID
        if not refresh:
            by_name: t.Optional[ModelInfo] = self.registry.get_by_name(model_id)
            if by_name is not None:
                return by_name

        # Fetch from daemon
        try:
            response = await self._client._send_request(
                "model_get",
                {"model_id": model_id},
            )
            result: t.Optional[JSONObject] = response.get("result")
            if result is None:
                raise ModelNotFoundError(model_id)

            info: ModelInfo = ModelInfo.from_dict(result)
            self.registry.update_one(info)
            return info
        except ModelNotFoundError:
            raise
        except Exception as exc:
            raise ModelNotFoundError(
                model_id,
                cause=exc,
            ) from exc

    async def load_model(
        self,
        name: str,
        path: str,
        *,
        backend: t.Optional[str] = None,
        context_length: t.Optional[int] = None,
        gpu_layers: t.Optional[int] = None,
        quantisation: t.Optional[str] = None,
        device: t.Optional[str] = None,
        extra_options: t.Optional[t.Dict[str, t.Any]] = None,
        wait_ready: bool = True,
        wait_timeout: float = 120.0,
    ) -> ModelInfo:
        """Load a model into the daemon.

        Args:
            name: A human-readable name for the model.
            path: File path to the model weights.
            backend: Inference backend (auto-detected if not specified).
            context_length: Maximum context length override.
            gpu_layers: Number of layers to offload to GPU.
            quantisation: Quantisation type (e.g. ``"q4_0"``).
            device: Device to load the model on.
            extra_options: Additional backend-specific options.
            wait_ready: If True, wait for the model to finish loading.
            wait_timeout: Maximum time to wait for loading, in seconds.

        Returns:
            The ModelInfo for the loaded model.

        Raises:
            ModelLoadError: If the model fails to load.
            ConnectionError: If the daemon is unreachable.
        """
        config: ModelConfigType = ModelConfigType(
            name=name,
            path=path,
            backend=backend,
            context_length=context_length,
            gpu_layers=gpu_layers,
            quantisation=quantisation,
            device=device,
            extra_options=extra_options,
        )

        try:
            response = await self._client._send_request(
                "model_load",
                config.to_dict(),
                timeout=wait_timeout if wait_ready else None,
            )
            result: t.Optional[JSONObject] = response.get("result")
            if result is None:
                error_data: t.Optional[JSONObject] = response.get("error")
                if error_data:
                    raise ModelLoadError(
                        name,
                        path,
                        detail=error_data.get("message", ""),
                    )
                raise ModelLoadError(name, path, detail="Unknown error")

            info: ModelInfo = ModelInfo.from_dict(result)
            self.registry.update_one(info)

            self.registry.add_event(
                ModelEvent(
                    type="loaded",
                    model_id=info.id,
                    timestamp=info.loaded_at or 0.0,
                    detail=f"Loaded from {path}",
                )
            )

            log.info("Model loaded: %s (id=%s, backend=%s)", name, info.id, info.backend)
            return info
        except ModelLoadError:
            raise
        except Exception as exc:
            raise ModelLoadError(
                name,
                path,
                detail=str(exc),
                cause=exc,
            ) from exc

    async def unload_model(
        self,
        model_id: str,
        *,
        force: bool = False,
    ) -> bool:
        """Unload a model from the daemon.

        Args:
            model_id: The model identifier to unload.
            force: If True, force unload even if the model is busy.

        Returns:
            True if the model was unloaded successfully.

        Raises:
            ModelNotFoundError: If the model is not found.
            ModelBusyError: If the model is busy and force is False.
            ModelUnloadError: If the unload operation fails.
        """
        try:
            params: JSONObject = {"model_id": model_id}
            if force:
                params["force"] = True

            response = await self._client._send_request(
                "model_unload",
                params,
            )
            error_data = response.get("error")
            if error_data:
                code: int = error_data.get("code", 0)
                msg: str = error_data.get("message", "")
                if code == -32003:  # ModelBusyError
                    raise ModelBusyError(model_id)
                if code == -32000:  # ModelNotFoundError
                    raise ModelNotFoundError(model_id)
                raise ModelUnloadError(model_id, detail=msg)

            self.registry.remove(model_id)
            self.registry.add_event(
                ModelEvent(
                    type="unloaded",
                    model_id=model_id,
                    timestamp=0.0,
                )
            )

            log.info("Model unloaded: %s", model_id)
            return True
        except (ModelNotFoundError, ModelBusyError, ModelUnloadError):
            raise
        except Exception as exc:
            raise ModelUnloadError(
                model_id,
                detail=str(exc),
                cause=exc,
            ) from exc

    async def refresh_registry(self) -> int:
        """Refresh the local model registry from the daemon.

        Returns:
            The number of models in the registry after refresh.
        """
        await self.list_models(refresh=True)
        return self.registry.model_count

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    async def is_loaded(self, model_id: str) -> bool:
        """Check if a model is currently loaded and ready.

        Args:
            model_id: The model identifier.

        Returns:
            True if the model is loaded, False otherwise.
        """
        try:
            info: ModelInfo = await self.get_model(model_id, refresh=True)
            return info.status == ModelStatus.LOADED.value
        except ModelNotFoundError:
            return False

    async def is_busy(self, model_id: str) -> bool:
        """Check if a model is currently busy.

        Args:
            model_id: The model identifier.

        Returns:
            True if the model is busy, False otherwise.
        """
        try:
            info: ModelInfo = await self.get_model(model_id, refresh=True)
            return info.status == ModelStatus.BUSY.value
        except ModelNotFoundError:
            return False

    async def find_model(
        self,
        *,
        name: t.Optional[str] = None,
        backend: t.Optional[str] = None,
        loaded: t.Optional[bool] = None,
    ) -> t.List[ModelInfo]:
        """Find models matching the given criteria.

        Args:
            name: Filter by model name (partial match).
            backend: Filter by inference backend.
            loaded: Filter by load status.

        Returns:
            A list of matching ModelInfo instances.
        """
        models: t.List[ModelInfo] = await self.list_models(refresh=False)

        result: t.List[ModelInfo] = []
        for model in models:
            if name and name.lower() not in model.name.lower():
                continue
            if backend and model.backend != backend:
                continue
            if loaded is not None:
                is_loaded: bool = model.status == ModelStatus.LOADED.value
                if loaded != is_loaded:
                    continue
            result.append(model)

        return result

    async def get_loaded_model_count(self) -> int:
        """Get the number of currently loaded models.

        Returns:
            The count of loaded models.
        """
        await self.list_models(refresh=True)
        return len(self.registry.loaded_models)

    # ------------------------------------------------------------------
        # Batch operations
    # ------------------------------------------------------------------

    async def load_models(
        self,
        configs: t.List[ModelConfigType],
        *,
        sequential: bool = True,
        wait_ready: bool = True,
    ) -> t.List[ModelInfo]:
        """Load multiple models in sequence or parallel.

        Args:
            configs: List of model configurations to load.
            sequential: If True, load models one at a time.
                If False, load them concurrently.
            wait_ready: If True, wait for each model to finish loading.

        Returns:
            A list of ModelInfo for successfully loaded models.

        Raises:
            ModelLoadError: If any model fails to load and sequential is True.
        """
        results: t.List[ModelInfo] = []

        if sequential:
            for config in configs:
                try:
                    info: ModelInfo = await self.load_model(
                        config.name,
                        config.path,
                        backend=config.backend,
                        context_length=config.context_length,
                        gpu_layers=config.gpu_layers,
                        quantisation=config.quantisation,
                        device=config.device,
                        extra_options=config.extra_options,
                        wait_ready=wait_ready,
                    )
                    results.append(info)
                except ModelLoadError as exc:
                    log.error("Failed to load model '%s': %s", config.name, exc)
                    if sequential:
                        raise
        else:
            # Concurrent loading
            import asyncio
            tasks: list[asyncio.Task[ModelInfo]] = [
                asyncio.create_task(
                    self.load_model(
                        config.name,
                        config.path,
                        backend=config.backend,
                        context_length=config.context_length,
                        gpu_layers=config.gpu_layers,
                        quantisation=config.quantisation,
                        device=config.device,
                        extra_options=config.extra_options,
                        wait_ready=wait_ready,
                    )
                )
                for config in configs
            ]
            completed: list[ModelInfo] = await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )
            for item in completed:
                if isinstance(item, ModelInfo):
                    results.append(item)
                elif isinstance(item, BaseException):
                    log.error("Concurrent model load failed: %s", item)

        return results

    async def unload_all(
        self,
        *,
        force: bool = False,
    ) -> int:
        """Unload all currently loaded models.

        Args:
            force: If True, force unload busy models.

        Returns:
            The number of models successfully unloaded.
        """
        models: t.List[ModelInfo] = await self.list_models(refresh=True)
        count: int = 0

        for model in models:
            if model.status == ModelStatus.LOADED.value:
                try:
                    await self.unload_model(model.id, force=force)
                    count += 1
                except ModelError as exc:
                    log.warning("Failed to unload '%s': %s", model.id, exc)

        return count

    # ------------------------------------------------------------------
    # String representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        """Return a string representation of the model manager."""
        return (
            f"ModelManager(registry={self.registry})"
        )


__all__: list[str] = [
    "ModelManager",
    "ModelRegistry",
    "ModelStatus",
    "ModelEvent",
]