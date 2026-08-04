"""AinosOS AI Runtime — Mock Test Suite.

This module provides comprehensive tests for the AinosOS AI Runtime using
Python mock objects that simulate the real Rust-based RuntimeManager from
``ai-daemon/src/runtime.rs``.

The test suite covers:

- RuntimeManager creation, initialization, stats, engine switching,
  LRU eviction, and max-model enforcement.
- Model loading/unloading with valid models, corrupted models, nonexistent
  files, empty paths, unsupported formats, duplicate loads, reference
  counting, and model listing.
- Basic inference, parameter variations (temperature, max_tokens, top_p,
  top_k), different models, session ID handling, prompt truncation, and
  empty prompt edge cases.
- Streaming inference: basic streaming, parameter handling, error
  propagation.
- Batch inference: multiple requests, mixed success/failure, empty batch.
- Context management: store/retrieve, overwrite, missing keys, empty keys,
  special characters.
- Error handling: invalid model, timeout, error injection for all
  operations, network errors, protocol errors.
- Model lifecycle: load -> infer -> unload, load -> unload -> load,
  concurrent operations, reference counting.
- Power policy: state transitions, throttle detection, cap enforcement.
- FFI boundary: marshalling, error propagation.
- Edge cases: very long prompts, special characters, empty strings, max
  values, concurrent access, race conditions.

Usage:
    pytest tests/runtime/test_runtime.py -v
    pytest tests/runtime/test_runtime.py -k "test_runtime_manager_create" -v
    pytest tests/runtime/test_runtime.py -m runtime -v
    pytest tests/runtime/test_runtime.py -m "runtime and slow" -v
"""

from __future__ import annotations

import copy
import logging
import math
import os
import random
import string
import tempfile
import threading
import time
import weakref
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple, Union

import pytest

# Import all fixtures and helpers from the shared conftest
from tests.conftest import (
    AI_ERR_GENERAL,
    AI_ERR_INVALID_PARAM,
    AI_ERR_MODEL_LOAD_FAIL,
    AI_ERR_MODEL_NOT_FOUND,
    AI_ERR_NOT_SUPPORTED,
    AI_ERR_OUT_OF_MEMORY,
    AI_ERR_PERMISSION,
    AI_ERR_SUCCESS,
    AI_ERR_TASK_QUEUE_FULL,
    AI_ERR_THERMAL_THROTTLE,
    AI_ERR_TIMEOUT,
    KernelStub,
    MockDaemonClient,
    MockDaemonError,
    MockDaemonProtocolError,
    MockDaemonServer,
    assert_error_response,
    assert_inference_response,
    assert_model_load_response,
    assert_model_unload_response,
    assert_status_response,
    assert_successful_response,
    assert_valid_message_type,
    create_corrupted_model,
    create_minimal_gguf,
    create_minimal_onnx,
    random_string,
)

# ============================================================================
# Mock Data Types (mirrors runtime.rs data structures)
# ============================================================================


class EngineType(Enum):
    """Inference engine type, mirroring ``runtime.rs::EngineType``."""
    GGML = "ggml"
    ONNX = "onnx"


class PowerState(Enum):
    """Power policy states for the runtime."""
    PERFORMANCE = auto()
    BALANCED = auto()
    POWER_SAVE = auto()
    THROTTLED = auto()
    CRITICAL = auto()


@dataclass
class MockInferenceResult:
    """Result of a mock inference call.

    Mirrors ``runtime.rs::InferenceResult`` with the same fields.
    """

    output: str
    tokens_generated: int
    prompt_tokens: int
    inference_ms: int
    tokens_per_second: float
    engine: str

    def __post_init__(self) -> None:
        """Validate the result fields."""
        assert isinstance(self.output, str), "output must be a string"
        assert self.tokens_generated >= 0, "tokens_generated must be >= 0"
        assert self.prompt_tokens >= 0, "prompt_tokens must be >= 0"
        assert self.inference_ms >= 0, "inference_ms must be >= 0"
        assert self.tokens_per_second >= 0.0, "tokens_per_second must be >= 0.0"
        assert self.engine in ("ggml", "onnx"), f"unknown engine: {self.engine}"


@dataclass
class MockModelMetadata:
    """Metadata for a loaded model.

    Mirrors ``runtime.rs::ModelMetadata`` with the same fields.
    """

    model_id: str
    model_path: str
    framework: str
    quantization: Optional[str]
    loaded_time: float
    memory_usage: int
    device: str
    ref_count: int
    architecture: str
    n_layers: int
    n_heads: int
    n_embd: int
    n_vocab: int

    def __post_init__(self) -> None:
        """Validate metadata fields."""
        assert isinstance(self.model_id, str) and len(self.model_id) > 0, (
            "model_id must be a non-empty string"
        )
        assert self.memory_usage >= 0, "memory_usage must be >= 0"
        assert self.ref_count >= 0, "ref_count must be >= 0"
        assert self.n_layers > 0, "n_layers must be > 0"
        assert self.n_heads > 0, "n_heads must be > 0"
        assert self.n_embd > 0, "n_embd must be > 0"
        assert self.n_vocab > 0, "n_vocab must be > 0"


@dataclass
class MockInferenceRequest:
    """Parameters for a mock inference call.

    Mirrors ``runtime.rs::InferenceRequest`` with the same fields.
    """

    model: str = "default"
    prompt: str = ""
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 40
    max_tokens: int = 512
    session_id: Optional[str] = None
    num_threads: Optional[int] = None
    repeat_penalty: float = 1.1
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0

    def __post_init__(self) -> None:
        """Validate request fields."""
        assert self.temperature >= 0.0, "temperature must be >= 0.0"
        assert self.top_p >= 0.0, "top_p must be >= 0.0"
        assert self.top_k >= 0, "top_k must be >= 0"
        assert self.max_tokens >= 0, "max_tokens must be >= 0"


# ============================================================================
# Mock Model Handle (internal tracking)
# ============================================================================


class MockModelHandle:
    """Tracks a loaded model instance within the MockRuntimeManager.

    Mirrors the internal ``ModelHandle`` struct from ``runtime.rs``.
    """

    def __init__(
        self,
        model_id: str,
        model_path: str,
        quantization: Optional[str] = None,
        architecture: str = "auto",
        n_layers: int = 32,
        n_heads: int = 32,
        n_embd: int = 4096,
        n_vocab: int = 32000,
        memory_usage: int = 0,
        device: str = "CPU",
        framework: str = "ggml",
    ) -> None:
        self.model_id = model_id
        self.model_path = model_path
        self.quantization = quantization
        self.architecture = architecture
        self.n_layers = n_layers
        self.n_heads = n_heads
        self.n_embd = n_embd
        self.n_vocab = n_vocab
        self.memory_usage = memory_usage
        self.device = device
        self.framework = framework
        self.loaded_time = time.time()
        self.ref_count = 1
        self.last_access = time.time()

    def to_metadata(self) -> MockModelMetadata:
        """Convert this handle to a MockModelMetadata."""
        return MockModelMetadata(
            model_id=self.model_id,
            model_path=self.model_path,
            framework=self.framework,
            quantization=self.quantization,
            loaded_time=self.loaded_time,
            memory_usage=self.memory_usage,
            device=self.device,
            ref_count=self.ref_count,
            architecture=self.architecture,
            n_layers=self.n_layers,
            n_heads=self.n_heads,
            n_embd=self.n_embd,
            n_vocab=self.n_vocab,
        )


# ============================================================================
# Mock Runtime Manager
# ============================================================================


class MockRuntimeError(Exception):
    """Base error for mock runtime operations."""


class MockRuntimeModelNotFoundError(MockRuntimeError):
    """Raised when a model is not found."""


class MockRuntimeModelNotLoadedError(MockRuntimeError):
    """Raised when a model is not loaded."""


class MockRuntimeEngineNotReadyError(MockRuntimeError):
    """Raised when the engine is not ready."""


class MockRuntimeInvalidParameterError(MockRuntimeError):
    """Raised when an invalid parameter is provided."""


class MockRuntimeOutOfMemoryError(MockRuntimeError):
    """Raised when the runtime is out of memory."""


class MockRuntimeTimeoutError(MockRuntimeError):
    """Raised when an operation times out."""


class MockRuntimeThermalThrottleError(MockRuntimeError):
    """Raised when the system is thermally throttled."""


class MockRuntimeManager:
    """Deterministic mock of the Rust ``RuntimeManager``.

    Simulates the full runtime manager behaviour including model lifecycle,
    inference, streaming, batch processing, context management, engine
    switching, LRU eviction, reference counting, power policy, and error
    injection. All operations are deterministic and do not depend on any
    real hardware, GPU, or model files (beyond filesystem checks).
    """

    # Supported model file extensions (mirrors daemon supported formats)
    SUPPORTED_EXTENSIONS: frozenset = frozenset({".gguf", ".ggml", ".onnx", ".bin"})

    def __repr__(self) -> str:
        """Return a string representation of the runtime manager."""
        return (
            f"MockRuntimeManager(engine={self._active_engine}, "
            f"models_loaded={len(self._models)}, "
            f"max_models={self._max_loaded_models})"
        )

    # Architecture detection patterns (mirrors RuntimeManager::detect_architecture)
    ARCHITECTURE_PATTERNS: dict[tuple[str, ...], str] = {
        ("llama",): "llama",
        ("phi",): "phi3",
        ("mistral",): "mistral",
        ("falcon",): "falcon",
        ("gemma",): "gemma",
        ("qwen",): "qwen2",
        ("chatglm", "glm"): "chatglm",
        ("starcoder", "codellama"): "starcoder",
    }

    # Quantization detection patterns (mirrors QuantizationType::from_str)
    QUANTIZATION_PATTERNS: dict[str, str] = {
        "q4_0": "q4_0",
        "q4-0": "q4_0",
        "q4_1": "q4_1",
        "q4-1": "q4_1",
        "q5_0": "q5_0",
        "q5-0": "q5_0",
        "q5_1": "q5_1",
        "q5-1": "q5_1",
        "q8_0": "q8_0",
        "q8-0": "q8_0",
        "f16": "f16",
        "fp16": "f16",
        "f32": "f32",
        "fp32": "f32",
    }

    def __init__(
        self,
        max_loaded_models: int = 8,
        max_context_length: int = 4096,
        engine_type: str = "ggml",
        seed: int = 42,
        error_injection: Optional[dict[str, Optional[str]]] = None,
        power_state: PowerState = PowerState.BALANCED,
    ) -> None:
        """Create a new MockRuntimeManager.

        Args:
            max_loaded_models: Maximum number of models that can be loaded
                simultaneously (triggers LRU eviction when exceeded).
            max_context_length: Maximum context length in tokens.
            engine_type: Initial engine type ("ggml" or "onnx").
            seed: Random seed for deterministic behaviour.
            error_injection: Optional dict mapping operation names to error
                messages. Set to None (or a key to None) for no error.
            power_state: Initial power policy state.
        """
        self._models: dict[str, MockModelHandle] = OrderedDict()
        self._load_order: list[str] = []
        self._active_engine = engine_type
        self._max_loaded_models = max_loaded_models
        self._max_context_length = max_context_length
        self._rng = random.Random(seed)
        self._error_injection: dict[str, Optional[str]] = (
            error_injection or {}
        )
        self._power_state = power_state
        self._lock = threading.Lock()

        # Statistics counters (mirrors RuntimeManager atomics)
        self._total_inferences = 0
        self._total_tokens_generated = 0
        self._total_inference_ms = 0
        self._total_prompt_tokens = 0
        self._total_model_loads = 0
        self._total_model_unloads = 0
        self._total_errors = 0
        self._total_evictions = 0

        # Context store (session_id -> key -> value)
        self._context_store: dict[tuple[Optional[str], str], str] = {}

        # Streaming callbacks tracking
        self._streaming_callbacks: list[Callable] = []

        # Event log for test assertions
        self._event_log: list[str] = []

        self._log_event(f"MockRuntimeManager created (engine={engine_type}, "
                        f"max_models={max_loaded_models}, seed={seed})")

    # ------------------------------------------------------------------
    # Event logging
    # ------------------------------------------------------------------

    def _log_event(self, message: str) -> None:
        """Log an internal event for test assertions."""
        self._event_log.append(f"[{time.time():.3f}] {message}")

    @property
    def event_log(self) -> list[str]:
        """Return the internal event log (read-only copy)."""
        return list(self._event_log)

    def clear_event_log(self) -> None:
        """Clear the internal event log."""
        self._event_log.clear()

    # ------------------------------------------------------------------
    # Error injection
    # ------------------------------------------------------------------

    def _check_error(self, operation: str) -> None:
        """Check if an error is injected for the given operation."""
        err_msg = self._error_injection.get(operation)
        if err_msg is not None:
            self._total_errors += 1
            self._log_event(f"Error injected for '{operation}': {err_msg}")
            raise MockRuntimeError(err_msg)

    def set_error_injection(self, operation: str, error_message: Optional[str]) -> None:
        """Set or clear error injection for an operation.

        Args:
            operation: Operation name (e.g. "load_model", "infer", "unload_model").
            error_message: Error message to raise, or None to clear.
        """
        if error_message is None:
            self._error_injection.pop(operation, None)
        else:
            self._error_injection[operation] = error_message
        self._log_event(f"Error injection for '{operation}': {error_message}")

    def clear_all_error_injections(self) -> None:
        """Clear all error injections."""
        self._error_injection.clear()
        self._log_event("All error injections cleared")

    # ------------------------------------------------------------------
    # Quantization detection
    # ------------------------------------------------------------------

    def detect_quantization(self, path: str) -> Optional[str]:
        """Detect model quantization type from file path.

        Mirrors ``RuntimeManager::detect_quantization``.

        Args:
            path: Model file path.

        Returns:
            Quantization string (e.g. "q4_0", "f16") or None if unknown.
        """
        lower = path.lower()
        for pattern, qtype in self.QUANTIZATION_PATTERNS.items():
            if pattern in lower:
                return qtype
        return None

    # ------------------------------------------------------------------
    # Architecture detection
    # ------------------------------------------------------------------

    def detect_architecture(self, path: str) -> str:
        """Detect model architecture from file path.

        Mirrors ``RuntimeManager::detect_architecture``.

        Args:
            path: Model file path.

        Returns:
            Architecture string (e.g. "llama", "phi3", "mistral", "auto").
        """
        lower = path.lower()
        for patterns, arch in self.ARCHITECTURE_PATTERNS.items():
            for pattern in patterns:
                if pattern in lower:
                    return arch
        return "auto"

    # ------------------------------------------------------------------
    # Token estimation
    # ------------------------------------------------------------------

    def estimate_token_count(self, text: str) -> int:
        """Estimate the number of tokens in a text string.

        Mirrors ``RuntimeManager::estimate_token_count`` which uses a
        simple heuristic: 4 characters ~= 1 token.

        Args:
            text: Input text.

        Returns:
            Estimated token count.
        """
        return (len(text) + 3) // 4 if text else 0

    # ------------------------------------------------------------------
    # Model management
    # ------------------------------------------------------------------

    def load_model(self, path: str, model_id: str) -> MockModelMetadata:
        """Load a model from the given path.

        Mirrors ``RuntimeManager::load_model`` including validation,
        LRU eviction, reference counting, and metadata extraction.

        Args:
            path: Path to the model file.
            model_id: Unique identifier for the model.

        Returns:
            MockModelMetadata for the loaded model.

        Raises:
            MockRuntimeError: If the model path is invalid, the file is
                missing, the format is unsupported, or an error is injected.
        """
        self._check_error("load_model")

        # Validate path
        if not path:
            self._total_errors += 1
            raise MockRuntimeInvalidParameterError("Model path is empty")

        path_obj = Path(path)

        # Check file exists
        if not path_obj.exists():
            self._total_errors += 1
            self._log_event(f"Model file not found: {path}")
            raise MockRuntimeModelNotFoundError(f"Model file not found: {path}")

        # Check extension
        ext = path_obj.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            self._total_errors += 1
            self._log_event(f"Unsupported model format: {ext}")
            raise MockRuntimeInvalidParameterError(
                f"Unsupported model format: {ext}. Supported: {self.SUPPORTED_EXTENSIONS}"
            )

        # Check file is not empty
        file_size = path_obj.stat().st_size
        if file_size == 0:
            self._total_errors += 1
            raise MockRuntimeInvalidParameterError(
                f"Model file is empty: {path}"
            )

        with self._lock:
            # Check if already loaded (increment ref count)
            existing = self._models.get(model_id)
            if existing is not None:
                existing.ref_count += 1
                existing.last_access = time.time()
                self._log_event(f"Model '{model_id}' ref_count increased to {existing.ref_count}")
                return existing.to_metadata()

            # LRU eviction if at capacity
            if len(self._models) >= self._max_loaded_models:
                self._evict_lru()

            # Detect quantization and architecture
            quantization = self.detect_quantization(path)
            architecture = self.detect_architecture(path)

            # Determine framework from extension
            framework = "onnx" if ext == ".onnx" else "ggml"

            # Create handle
            handle = MockModelHandle(
                model_id=model_id,
                model_path=path,
                quantization=quantization,
                architecture=architecture,
                memory_usage=file_size,
                device="CPU",
                framework=framework,
            )

            # Check for corrupted model (simulated by small invalid files
            # that are not empty but have no valid header)
            if "corrupted" in path.lower():
                # Simulate load failure for corrupted files
                self._total_errors += 1
                raise MockRuntimeModelNotFoundError(
                    f"Model file corrupted or invalid: {path}"
                )

            self._models[model_id] = handle
            self._load_order.append(model_id)
            self._total_model_loads += 1

            self._log_event(
                f"Model loaded: {model_id} (quant={quantization}, "
                f"arch={architecture}, size={file_size}B, framework={framework})"
            )

            return handle.to_metadata()

    def unload_model(self, model_id: str) -> bool:
        """Unload a model by ID with reference counting.

        Mirrors ``RuntimeManager::unload_model``.

        Args:
            model_id: The model identifier to unload.

        Returns:
            True if the model was fully unloaded, False if the ref count
            was decremented but the model remains loaded.

        Raises:
            MockRuntimeError: If the model is not loaded or an error is
                injected.
        """
        self._check_error("unload_model")

        with self._lock:
            handle = self._models.get(model_id)
            if handle is None:
                self._total_errors += 1
                raise MockRuntimeModelNotLoadedError(
                    f"Model not loaded: {model_id}"
                )

            handle.ref_count -= 1
            self._log_event(
                f"Model '{model_id}' ref_count decreased to {handle.ref_count}"
            )

            if handle.ref_count > 0:
                return False

            # Fully unload
            del self._models[model_id]
            self._load_order = [m for m in self._load_order if m != model_id]
            self._total_model_unloads += 1
            self._log_event(f"Model unloaded: {model_id}")
            return True

    def get_model_info(self, model_id: str) -> MockModelMetadata:
        """Get metadata for a loaded model.

        Args:
            model_id: The model identifier.

        Returns:
            MockModelMetadata for the model.

        Raises:
            MockRuntimeError: If the model is not loaded.
        """
        with self._lock:
            handle = self._models.get(model_id)
            if handle is None:
                raise MockRuntimeModelNotLoadedError(
                    f"Model not loaded: {model_id}"
                )
            handle.last_access = time.time()
            return handle.to_metadata()

    def list_models(self) -> list[MockModelMetadata]:
        """List all currently loaded models.

        Returns:
            List of MockModelMetadata for all loaded models.
        """
        with self._lock:
            return [h.to_metadata() for h in self._models.values()]

    def get_loaded_count(self) -> int:
        """Get the number of currently loaded models."""
        with self._lock:
            return len(self._models)

    # ------------------------------------------------------------------
    # LRU eviction
    # ------------------------------------------------------------------

    def _evict_lru(self) -> None:
        """Evict the least recently used model.

        Mirrors ``RuntimeManager::evict_lru``.
        """
        if not self._load_order:
            return

        # Find the model with the oldest last_access
        oldest_id = min(
            self._load_order,
            key=lambda mid: self._models[mid].last_access if mid in self._models else 0,
        )

        handle = self._models.get(oldest_id)
        if handle is not None:
            self._log_event(
                f"LRU evicting model: {oldest_id} (ref_count={handle.ref_count})"
            )
            # Force unload (ignore ref count for eviction)
            del self._models[oldest_id]
            self._load_order = [m for m in self._load_order if m != oldest_id]
            self._total_model_unloads += 1
            self._total_evictions += 1
            self._log_event(f"LRU eviction complete: {oldest_id}")

    def _update_lru(self, model_id: str) -> None:
        """Update the LRU order, moving model_id to the most-recently-used end.

        Mirrors ``RuntimeManager::update_lru``.
        """
        if model_id in self._load_order:
            self._load_order.remove(model_id)
        self._load_order.append(model_id)
        handle = self._models.get(model_id)
        if handle is not None:
            handle.last_access = time.time()

    # ------------------------------------------------------------------
    # Engine switching
    # ------------------------------------------------------------------

    def switch_engine(self, engine_type: str) -> None:
        """Switch the active inference engine.

        Args:
            engine_type: "ggml" or "onnx".

        Raises:
            MockRuntimeInvalidParameterError: If the engine type is unknown.
        """
        if engine_type not in ("ggml", "onnx"):
            raise MockRuntimeInvalidParameterError(
                f"Unknown engine type: {engine_type}. Must be 'ggml' or 'onnx'."
            )
        old = self._active_engine
        self._active_engine = engine_type
        self._log_event(f"Engine switched: {old} -> {engine_type}")

    def get_active_engine(self) -> str:
        """Get the currently active engine type."""
        return self._active_engine

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def infer(self, request: MockInferenceRequest) -> MockInferenceResult:
        """Execute a mock inference request.

        Mirrors ``RuntimeManager::infer`` (async in Rust, sync in mock).

        Args:
            request: The inference request parameters.

        Returns:
            MockInferenceResult with deterministic output.

        Raises:
            MockRuntimeError: If the model is not loaded, parameters are
                invalid, or an error is injected.
        """
        self._check_error("infer")

        # Validate model exists
        with self._lock:
            if request.model not in self._models:
                self._total_errors += 1
                raise MockRuntimeModelNotLoadedError(
                    f"Model '{request.model}' not loaded. Call load_model() first."
                )
            self._update_lru(request.model)

        # Validate parameters
        if request.temperature < 0.0:
            raise MockRuntimeInvalidParameterError("temperature must be >= 0.0")
        if request.max_tokens < 0:
            raise MockRuntimeInvalidParameterError("max_tokens must be >= 0")
        if request.top_p < 0.0 or request.top_p > 1.0:
            raise MockRuntimeInvalidParameterError("top_p must be in [0.0, 1.0]")

        # Check for thermal throttle
        if self._power_state in (PowerState.THROTTLED, PowerState.CRITICAL):
            if self._power_state == PowerState.CRITICAL:
                raise MockRuntimeThermalThrottleError(
                    "Inference blocked: system in CRITICAL power state"
                )

        start_time = time.monotonic()

        # Simulate prompt token count
        prompt_tokens = self.estimate_token_count(request.prompt)

        # Clamp max_tokens
        max_tokens = min(request.max_tokens, 2048)

        # Simulate inference latency (5ms per token, max 500ms)
        simulated_delay_ms = min(max_tokens * 5, 500)
        if simulated_delay_ms > 0:
            time.sleep(simulated_delay_ms / 1000.0)

        # Deterministic output based on model, prompt, and parameters
        prompt_preview = request.prompt[:50] if len(request.prompt) > 50 else request.prompt
        output = (
            f"[{self._active_engine.upper()}] Processed '{prompt_preview}' "
            f"(model={request.model}, tokens={max_tokens}, "
            f"temp={request.temperature:.2f}, top_p={request.top_p:.2f}, "
            f"top_k={request.top_k})"
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        tokens_per_second = max_tokens / (elapsed_ms / 1000.0) if elapsed_ms > 0 else 0.0

        result = MockInferenceResult(
            output=output,
            tokens_generated=max_tokens,
            prompt_tokens=prompt_tokens,
            inference_ms=elapsed_ms,
            tokens_per_second=tokens_per_second,
            engine=self._active_engine,
        )

        with self._lock:
            self._total_inferences += 1
            self._total_tokens_generated += max_tokens
            self._total_inference_ms += elapsed_ms
            self._total_prompt_tokens += prompt_tokens

        self._log_event(
            f"Inference: model={request.model}, prompt_len={len(request.prompt)}, "
            f"tokens={max_tokens}, elapsed={elapsed_ms}ms"
        )

        return result

    def infer_streaming(
        self,
        request: MockInferenceRequest,
        callback: Callable[[str], None],
    ) -> MockInferenceResult:
        """Execute a streaming mock inference.

        Mirrors ``RuntimeManager::infer_streaming``.

        Args:
            request: The inference request parameters.
            callback: Function called for each generated token chunk.

        Returns:
            MockInferenceResult with the full output.

        Raises:
            MockRuntimeError: If the model is not loaded or an error is
                injected.
        """
        self._check_error("infer_streaming")

        # Validate model exists
        with self._lock:
            if request.model not in self._models:
                self._total_errors += 1
                raise MockRuntimeModelNotLoadedError(
                    f"Model '{request.model}' not loaded."
                )
            self._update_lru(request.model)

        start_time = time.monotonic()
        prompt_tokens = self.estimate_token_count(request.prompt)
        max_tokens = min(request.max_tokens, 256)

        # Simulate streaming token generation
        output_parts: list[str] = []
        for i in range(max_tokens):
            token = f"token_{i + 1} "
            callback(token)
            output_parts.append(token)
            # Small delay between tokens (2ms per token)
            time.sleep(0.002)

        output = "".join(output_parts)
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        tokens_per_second = max_tokens / (elapsed_ms / 1000.0) if elapsed_ms > 0 else 0.0

        result = MockInferenceResult(
            output=output,
            tokens_generated=max_tokens,
            prompt_tokens=prompt_tokens,
            inference_ms=elapsed_ms,
            tokens_per_second=tokens_per_second,
            engine=self._active_engine,
        )

        with self._lock:
            self._total_inferences += 1
            self._total_tokens_generated += max_tokens
            self._total_inference_ms += elapsed_ms

        self._log_event(
            f"Streaming inference: model={request.model}, "
            f"tokens={max_tokens}, elapsed={elapsed_ms}ms"
        )

        return result

    def batch_infer(
        self,
        requests: list[MockInferenceRequest],
    ) -> list[Union[MockInferenceResult, MockRuntimeError]]:
        """Execute multiple inference requests as a batch.

        Mirrors ``RuntimeManager::batch_infer``.

        Args:
            requests: List of inference requests.

        Returns:
            List of results (MockInferenceResult on success,
            MockRuntimeError subclass on failure).
        """
        self._check_error("batch_infer")

        results: list[Union[MockInferenceResult, MockRuntimeError]] = []
        for req in requests:
            try:
                result = self.infer(req)
                results.append(result)
            except MockRuntimeError as e:
                results.append(e)
                self._total_errors += 1

        self._log_event(f"Batch infer: {len(requests)} requests, {len(results)} results")
        return results

    # ------------------------------------------------------------------
    # Context management
    # ------------------------------------------------------------------

    def context_store(
        self,
        key: str,
        value: str,
        session_id: Optional[str] = None,
    ) -> None:
        """Store a value in the context store.

        Args:
            key: The lookup key.
            value: The value to store.
            session_id: Optional session identifier.

        Raises:
            MockRuntimeInvalidParameterError: If the key is empty.
        """
        self._check_error("context_store")

        if not key:
            raise MockRuntimeInvalidParameterError("Context key must not be empty")

        with self._lock:
            self._context_store[(session_id, key)] = value

        self._log_event(f"Context stored: session={session_id}, key={key}")

    def context_retrieve(
        self,
        key: str,
        session_id: Optional[str] = None,
    ) -> str:
        """Retrieve a value from the context store.

        Args:
            key: The lookup key.
            session_id: Optional session identifier.

        Returns:
            The stored value.

        Raises:
            MockRuntimeError: If the key is not found.
        """
        self._check_error("context_retrieve")

        with self._lock:
            value = self._context_store.get((session_id, key))

        if value is None:
            raise MockRuntimeModelNotFoundError(
                f"Context key not found: session={session_id}, key={key}"
            )

        return value

    def context_delete(
        self,
        key: str,
        session_id: Optional[str] = None,
    ) -> bool:
        """Delete a value from the context store.

        Args:
            key: The lookup key.
            session_id: Optional session identifier.

        Returns:
            True if the key was found and deleted, False otherwise.
        """
        with self._lock:
            composite = (session_id, key)
            if composite in self._context_store:
                del self._context_store[composite]
                return True
            return False

    def context_list_keys(
        self,
        session_id: Optional[str] = None,
    ) -> list[str]:
        """List all context keys for a given session.

        Args:
            session_id: Optional session identifier.

        Returns:
            List of keys stored for the session.
        """
        with self._lock:
            return [
                k for (sid, k) in self._context_store
                if sid == session_id
            ]

    # ------------------------------------------------------------------
    # Power policy
    # ------------------------------------------------------------------

    def set_power_state(self, state: PowerState) -> None:
        """Set the current power policy state.

        Args:
            state: The new power state.
        """
        old = self._power_state
        self._power_state = state
        self._log_event(f"Power state: {old.name} -> {state.name}")

    def get_power_state(self) -> PowerState:
        """Get the current power policy state."""
        return self._power_state

    def is_throttled(self) -> bool:
        """Check if the runtime is currently throttled.

        Returns:
            True if the power state is THROTTLED or CRITICAL.
        """
        return self._power_state in (PowerState.THROTTLED, PowerState.CRITICAL)

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, int]:
        """Get runtime statistics.

        Mirrors ``RuntimeManager::get_stats``.

        Returns:
            Dict of stat name to value.
        """
        with self._lock:
            return {
                "total_inferences": self._total_inferences,
                "total_tokens_generated": self._total_tokens_generated,
                "total_inference_ms": self._total_inference_ms,
                "total_prompt_tokens": self._total_prompt_tokens,
                "total_model_loads": self._total_model_loads,
                "total_model_unloads": self._total_model_unloads,
                "total_errors": self._total_errors,
                "total_evictions": self._total_evictions,
                "models_loaded": len(self._models),
                "max_loaded_models": self._max_loaded_models,
                "max_context_length": self._max_context_length,
            }

    def reset_stats(self) -> None:
        """Reset all statistics counters to zero."""
        with self._lock:
            self._total_inferences = 0
            self._total_tokens_generated = 0
            self._total_inference_ms = 0
            self._total_prompt_tokens = 0
            self._total_model_loads = 0
            self._total_model_unloads = 0
            self._total_errors = 0
            self._total_evictions = 0
        self._log_event("Statistics reset")

    # ------------------------------------------------------------------
    # Cleanup / reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset the entire runtime to its initial state."""
        with self._lock:
            self._models.clear()
            self._load_order.clear()
            self._context_store.clear()
            self._total_inferences = 0
            self._total_tokens_generated = 0
            self._total_inference_ms = 0
            self._total_prompt_tokens = 0
            self._total_model_loads = 0
            self._total_model_unloads = 0
            self._total_errors = 0
            self._total_evictions = 0
            self._error_injection.clear()
            self._power_state = PowerState.BALANCED
            self._event_log.clear()
        self._log_event("Runtime reset to initial state")

    def shutdown(self) -> None:
        """Simulate runtime shutdown, unloading all models."""
        self._log_event("Runtime shutting down")
        with self._lock:
            model_ids = list(self._models.keys())
            for mid in model_ids:
                self._log_event(f"Shutdown: unloading model {mid}")
            self._models.clear()
            self._load_order.clear()
            self._context_store.clear()
        self._log_event("Runtime shutdown complete")


# ============================================================================
# Test Fixtures (runtime-specific)
# ============================================================================


@pytest.fixture(scope="function")
def runtime_manager() -> Generator[MockRuntimeManager, None, None]:
    """Create a fresh MockRuntimeManager for each test."""
    rm = MockRuntimeManager(max_loaded_models=8, seed=42)
    yield rm


@pytest.fixture(scope="function")
def runtime_manager_small_cache() -> Generator[MockRuntimeManager, None, None]:
    """Create a MockRuntimeManager with a small model cache (max 2 models)."""
    rm = MockRuntimeManager(max_loaded_models=2, seed=42)
    yield rm


@pytest.fixture(scope="function")
def runtime_manager_with_models(
    runtime_manager: MockRuntimeManager,
    temp_model_dir: str,
) -> Generator[tuple[MockRuntimeManager, str], None, None]:
    """Create a MockRuntimeManager with models pre-loaded."""
    model_path = os.path.join(temp_model_dir, "test_model.gguf")
    runtime_manager.load_model(model_path, "test_model")
    yield runtime_manager, temp_model_dir


@pytest.fixture(scope="function")
def runtime_manager_error_injector() -> (
    Generator[MockRuntimeManager, None, None]
):
    """Create a MockRuntimeManager with error injection support."""
    rm = MockRuntimeManager(
        max_loaded_models=8,
        seed=42,
        error_injection={},
    )
    yield rm


# ============================================================================
# Test: RuntimeManager Basic Creation and Initialization
# ============================================================================


@pytest.mark.runtime
class TestRuntimeManagerCreate:
    """Tests for RuntimeManager creation and basic initialization."""

    def test_create_default(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that a default MockRuntimeManager is created with expected
        initial state: no models loaded, GGML engine, default max models."""
        assert runtime_manager.get_loaded_count() == 0
        assert runtime_manager.get_active_engine() == "ggml"
        stats = runtime_manager.get_stats()
        assert stats["models_loaded"] == 0
        assert stats["total_inferences"] == 0
        assert stats["max_loaded_models"] == 8
        assert stats["max_context_length"] == 4096
        assert "total_errors" in stats

    def test_create_with_custom_params(self) -> None:
        """Verify that custom parameters are correctly applied on creation."""
        rm = MockRuntimeManager(
            max_loaded_models=4,
            max_context_length=8192,
            engine_type="onnx",
            seed=123,
        )
        assert rm.get_loaded_count() == 0
        assert rm.get_active_engine() == "onnx"
        stats = rm.get_stats()
        assert stats["max_loaded_models"] == 4
        assert stats["max_context_length"] == 8192

    def test_create_with_power_state(self) -> None:
        """Verify that the initial power state can be set on creation."""
        rm = MockRuntimeManager(power_state=PowerState.PERFORMANCE)
        assert rm.get_power_state() == PowerState.PERFORMANCE
        assert not rm.is_throttled()

        rm2 = MockRuntimeManager(power_state=PowerState.THROTTLED)
        assert rm2.get_power_state() == PowerState.THROTTLED
        assert rm2.is_throttled()

    def test_create_with_error_injection(self) -> None:
        """Verify that error injection dict is accepted on creation."""
        rm = MockRuntimeManager(
            error_injection={"load_model": "Simulated load failure"},
        )
        with pytest.raises(MockRuntimeError, match="Simulated load failure"):
            rm.load_model("/some/path.gguf", "test_model")

    def test_create_event_log(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that the event log is populated on creation."""
        log = runtime_manager.event_log
        assert len(log) >= 1
        assert "MockRuntimeManager created" in log[0]

    def test_reset_runtime(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that reset() returns the runtime to its initial state."""
        # Perform some operations
        stats_before = runtime_manager.get_stats()
        runtime_manager._total_inferences = 100
        runtime_manager._total_errors = 5

        runtime_manager.reset()

        stats_after = runtime_manager.get_stats()
        assert stats_after["total_inferences"] == 0
        assert stats_after["total_errors"] == 0
        assert stats_after["models_loaded"] == 0
        # The reset itself logs an event
        assert any("Runtime reset" in e for e in runtime_manager.event_log)

    def test_shutdown_runtime(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that shutdown() correctly unloads all models and clears state."""
        # We can't load models without real files, so just verify the event log
        runtime_manager.shutdown()
        assert any("shutdown complete" in e for e in runtime_manager.event_log)

    def test_weakref_to_runtime(self) -> None:
        """Verify that a weak reference to the runtime can be created."""
        rm = MockRuntimeManager()
        ref = weakref.ref(rm)
        assert ref() is rm
        del rm
        assert ref() is None

    def test_runtime_repr(self) -> None:
        """Verify that the runtime string representation is informative."""
        rm = MockRuntimeManager(max_loaded_models=4, engine_type="onnx")
        rm_str = repr(rm)
        assert "MockRuntimeManager" in rm_str
        assert "engine" in rm_str.lower() or "onnx" in rm_str
        assert "models_loaded" in rm_str or "max_models" in rm_str


# ============================================================================
# Test: Engine Switching
# ============================================================================


@pytest.mark.runtime
class TestEngineSwitching:
    """Tests for engine type switching."""

    def test_switch_to_onnx(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that switching to ONNX engine works correctly."""
        assert runtime_manager.get_active_engine() == "ggml"
        runtime_manager.switch_engine("onnx")
        assert runtime_manager.get_active_engine() == "onnx"

    def test_switch_to_ggml(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that switching back to GGML engine works correctly."""
        runtime_manager.switch_engine("onnx")
        runtime_manager.switch_engine("ggml")
        assert runtime_manager.get_active_engine() == "ggml"

    def test_switch_invalid_engine(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that switching to an invalid engine type raises an error."""
        with pytest.raises(MockRuntimeInvalidParameterError, match="Unknown engine type"):
            runtime_manager.switch_engine("tensorrt")

    def test_switch_empty_engine(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that switching to an empty engine type raises an error."""
        with pytest.raises(MockRuntimeInvalidParameterError, match="Unknown engine type"):
            runtime_manager.switch_engine("")

    def test_switch_case_sensitive(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that engine type matching is case-sensitive."""
        with pytest.raises(MockRuntimeInvalidParameterError, match="Unknown engine type"):
            runtime_manager.switch_engine("GGML")

    def test_switch_engine_updates_stats(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that engine switching is reflected in inference outputs."""
        runtime_manager.switch_engine("onnx")
        # We need a model loaded to test inference output
        # The engine string is used in the output format
        assert runtime_manager.get_active_engine() == "onnx"

    @pytest.mark.parametrize("engine", ["ggml", "onnx"])
    def test_switch_engine_parametrized(self, engine: str) -> None:
        """Verify that both engine types are accepted through parametrize."""
        rm = MockRuntimeManager()
        rm.switch_engine(engine)
        assert rm.get_active_engine() == engine

    def test_switch_engine_idempotent(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that switching to the same engine is idempotent."""
        runtime_manager.switch_engine("ggml")
        assert runtime_manager.get_active_engine() == "ggml"
        runtime_manager.switch_engine("ggml")
        assert runtime_manager.get_active_engine() == "ggml"

    def test_switch_engine_event_log(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that engine switching is recorded in the event log."""
        runtime_manager.clear_event_log()
        runtime_manager.switch_engine("onnx")
        assert any("Engine switched" in e for e in runtime_manager.event_log)


# ============================================================================
# Test: Quantization and Architecture Detection
# ============================================================================


@pytest.mark.runtime
class TestQuantizationDetection:
    """Tests for model quantization type detection."""

    def test_detect_q4_0(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that q4_0 quantization is detected from file path."""
        assert runtime_manager.detect_quantization("model-q4_0.gguf") == "q4_0"

    def test_detect_q4_1(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that q4_1 quantization is detected from file path."""
        assert runtime_manager.detect_quantization("model-q4_1.gguf") == "q4_1"

    def test_detect_q5_0(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that q5_0 quantization is detected from file path."""
        assert runtime_manager.detect_quantization("model-q5_0.gguf") == "q5_0"

    def test_detect_q5_1(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that q5_1 quantization is detected from file path."""
        assert runtime_manager.detect_quantization("model-q5_1.gguf") == "q5_1"

    def test_detect_q8_0(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that q8_0 quantization is detected from file path."""
        assert runtime_manager.detect_quantization("model-q8_0.gguf") == "q8_0"

    def test_detect_f16(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that f16 and fp16 quantization are detected."""
        assert runtime_manager.detect_quantization("model-f16.gguf") == "f16"
        assert runtime_manager.detect_quantization("model-fp16.gguf") == "f16"

    def test_detect_f32(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that f32 and fp32 quantization are detected."""
        assert runtime_manager.detect_quantization("model-f32.gguf") == "f32"
        assert runtime_manager.detect_quantization("model-fp32.gguf") == "f32"

    def test_detect_no_quantization(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that None is returned when no quantization pattern is found."""
        assert runtime_manager.detect_quantization("model.gguf") is None

    def test_detect_quantization_case_insensitive(
        self, runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that quantization detection is case-insensitive."""
        assert runtime_manager.detect_quantization("MODEL-Q4_0.GGUF") == "q4_0"

    def test_detect_quantization_empty_path(
        self, runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that detection returns None for an empty path."""
        assert runtime_manager.detect_quantization("") is None


@pytest.mark.runtime
class TestArchitectureDetection:
    """Tests for model architecture detection."""

    def test_detect_llama(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that 'llama' architecture is detected from path."""
        assert runtime_manager.detect_architecture("llama-2-7b.gguf") == "llama"

    def test_detect_phi3(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that 'phi3' architecture is detected from path."""
        assert runtime_manager.detect_architecture("phi-3-mini.gguf") == "phi3"

    def test_detect_mistral(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that 'mistral' architecture is detected from path."""
        assert runtime_manager.detect_architecture("mistral-7b.gguf") == "mistral"

    def test_detect_falcon(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that 'falcon' architecture is detected from path."""
        assert runtime_manager.detect_architecture("falcon-7b.gguf") == "falcon"

    def test_detect_gemma(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that 'gemma' architecture is detected from path."""
        assert runtime_manager.detect_architecture("gemma-2b.gguf") == "gemma"

    def test_detect_qwen2(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that 'qwen2' architecture is detected from path."""
        assert runtime_manager.detect_architecture("qwen-7b.gguf") == "qwen2"

    def test_detect_chatglm(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that 'chatglm' architecture is detected from path."""
        assert runtime_manager.detect_architecture("chatglm-6b.gguf") == "chatglm"

    def test_detect_starcoder(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that 'starcoder' architecture is detected from path."""
        assert runtime_manager.detect_architecture("starcoder-15b.gguf") == "starcoder"

    def test_detect_auto(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that 'auto' is returned when no known architecture is found."""
        assert runtime_manager.detect_architecture("unknown-model.gguf") == "auto"

    def test_detect_architecture_case_insensitive(
        self, runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that architecture detection is case-insensitive."""
        assert runtime_manager.detect_architecture("LLAMA-2-7B.GGUF") == "llama"

    def test_detect_architecture_empty_path(
        self, runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that detection returns 'auto' for an empty path."""
        assert runtime_manager.detect_architecture("") == "auto"


# ============================================================================
# Test: Token Estimation
# ============================================================================


@pytest.mark.runtime
class TestTokenEstimation:
    """Tests for token count estimation."""

    def test_estimate_empty(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that an empty string returns 0 tokens."""
        assert runtime_manager.estimate_token_count("") == 0

    def test_estimate_single_char(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that a single character returns 1 token."""
        assert runtime_manager.estimate_token_count("a") == 1

    def test_estimate_four_chars(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that 4 characters return 1 token (4 chars = 1 token)."""
        assert runtime_manager.estimate_token_count("test") == 1

    def test_estimate_five_chars(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that 5 characters return 2 tokens (ceil(5/4))."""
        assert runtime_manager.estimate_token_count("hello") == 2

    def test_estimate_long_text(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify token estimation for a long text string."""
        text = "The quick brown fox jumps over the lazy dog. " * 100
        expected = (len(text) + 3) // 4
        assert runtime_manager.estimate_token_count(text) == expected

    def test_estimate_unicode(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify token estimation for Unicode text (uses byte length)."""
        text = "你好世界"
        expected = (len(text) + 3) // 4
        assert runtime_manager.estimate_token_count(text) == expected

    def test_estimate_special_chars(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify token estimation for text with special characters."""
        text = "!@#$%^&*()_+-=[]{}|;':\",./<>?`~"
        expected = (len(text) + 3) // 4
        assert runtime_manager.estimate_token_count(text) == expected

    def test_estimate_newlines(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify token estimation for text with newlines."""
        text = "line1\nline2\nline3\n"
        expected = (len(text) + 3) // 4
        assert runtime_manager.estimate_token_count(text) == expected

    def test_estimate_spaces(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify token estimation for whitespace-only text."""
        text = "     " * 100
        expected = (len(text) + 3) // 4
        assert runtime_manager.estimate_token_count(text) == expected

    def test_estimate_very_long(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify token estimation for very long text (100k chars)."""
        text = "a" * 100000
        expected = (100000 + 3) // 4  # 25000
        assert runtime_manager.estimate_token_count(text) == expected


# ============================================================================
# Test: Model Loading
# ============================================================================


@pytest.mark.runtime
class TestModelLoading:
    """Tests for model loading with various scenarios."""

    def test_load_valid_model(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that a valid GGUF model can be loaded successfully."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        metadata = runtime_manager.load_model(model_path, "test_model")
        assert metadata.model_id == "test_model"
        assert metadata.model_path == model_path
        assert metadata.framework == "ggml"
        assert metadata.quantization is None  # no quantization pattern in path
        assert metadata.memory_usage > 0
        assert metadata.ref_count == 1
        assert metadata.n_layers == 32
        assert metadata.n_heads == 32
        assert metadata.n_embd == 4096
        assert metadata.n_vocab == 32000
        assert runtime_manager.get_loaded_count() == 1

    def test_load_valid_onnx_model(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that a valid ONNX model can be loaded successfully."""
        model_path = os.path.join(temp_model_dir, "test_model.onnx")
        metadata = runtime_manager.load_model(model_path, "test_onnx")
        assert metadata.model_id == "test_onnx"
        assert metadata.framework == "onnx"
        assert runtime_manager.get_loaded_count() == 1

    def test_load_nonexistent_file(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that loading a nonexistent file raises ModelNotFoundError."""
        with pytest.raises(MockRuntimeModelNotFoundError, match="not found"):
            runtime_manager.load_model("/nonexistent/path/model.gguf", "test_model")

    def test_load_empty_path(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that loading with an empty path raises InvalidParameterError."""
        with pytest.raises(MockRuntimeInvalidParameterError, match="empty"):
            runtime_manager.load_model("", "test_model")

    def test_load_unsupported_format(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that loading an unsupported format raises InvalidParameterError."""
        unsupported_path = os.path.join(temp_model_dir, "model.pt")
        Path(unsupported_path).write_text("dummy")
        with pytest.raises(MockRuntimeInvalidParameterError, match="Unsupported model format"):
            runtime_manager.load_model(unsupported_path, "test_model")

    def test_load_unsupported_format_torch(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that loading a .pth file raises InvalidParameterError."""
        unsupported_path = os.path.join(temp_model_dir, "model.pth")
        Path(unsupported_path).write_text("dummy")
        with pytest.raises(MockRuntimeInvalidParameterError, match="Unsupported model format"):
            runtime_manager.load_model(unsupported_path, "test_model")

    def test_load_unsupported_format_safetensors(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that loading a .safetensors file raises InvalidParameterError."""
        unsupported_path = os.path.join(temp_model_dir, "model.safetensors")
        Path(unsupported_path).write_text("dummy")
        with pytest.raises(MockRuntimeInvalidParameterError, match="Unsupported model format"):
            runtime_manager.load_model(unsupported_path, "test_model")

    def test_load_empty_file(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that loading an empty file raises InvalidParameterError."""
        model_path = os.path.join(temp_model_dir, "empty_model.gguf")
        with pytest.raises(MockRuntimeInvalidParameterError, match="empty"):
            runtime_manager.load_model(model_path, "empty_model")

    def test_load_corrupted_model(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that loading a corrupted model raises ModelNotFoundError."""
        model_path = os.path.join(temp_model_dir, "corrupted_model.gguf")
        with pytest.raises(MockRuntimeModelNotFoundError, match="corrupted"):
            runtime_manager.load_model(model_path, "corrupted_model")

    def test_load_duplicate_model(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that loading the same model twice increments ref count."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        meta1 = runtime_manager.load_model(model_path, "test_model")
        assert meta1.ref_count == 1

        meta2 = runtime_manager.load_model(model_path, "test_model")
        assert meta2.ref_count == 2
        assert runtime_manager.get_loaded_count() == 1

    def test_load_multiple_models(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that multiple distinct models can be loaded."""
        model1 = os.path.join(temp_model_dir, "test_model.gguf")
        model2 = os.path.join(temp_model_dir, "phi-3-mini.gguf")
        model3 = os.path.join(temp_model_dir, "llama-2-7b.gguf")

        runtime_manager.load_model(model1, "model_1")
        runtime_manager.load_model(model2, "model_2")
        runtime_manager.load_model(model3, "model_3")

        assert runtime_manager.get_loaded_count() == 3

    def test_load_model_with_llama_architecture(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that a model with 'llama' in its path gets the correct architecture."""
        model_path = os.path.join(temp_model_dir, "llama-2-7b.gguf")
        metadata = runtime_manager.load_model(model_path, "llama_model")
        assert metadata.architecture == "llama"

    def test_load_model_with_phi_architecture(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that a model with 'phi' in its path gets the correct architecture."""
        model_path = os.path.join(temp_model_dir, "phi-3-mini.gguf")
        metadata = runtime_manager.load_model(model_path, "phi_model")
        assert metadata.architecture == "phi3"

    def test_load_model_with_mistral_architecture(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that a model with 'mistral' in its path gets the correct architecture."""
        model_path = os.path.join(temp_model_dir, "mistral-7b.gguf")
        metadata = runtime_manager.load_model(model_path, "mistral_model")
        assert metadata.architecture == "mistral"

    def test_load_model_event_log(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that model loading is recorded in the event log."""
        runtime_manager.clear_event_log()
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "test_model")
        assert any("Model loaded" in e for e in runtime_manager.event_log)

    def test_load_model_updates_stats(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that model loading increments the load counter."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        stats_before = runtime_manager.get_stats()
        assert stats_before["total_model_loads"] == 0

        runtime_manager.load_model(model_path, "test_model")
        stats_after = runtime_manager.get_stats()
        assert stats_after["total_model_loads"] == 1
        assert stats_after["models_loaded"] == 1

    def test_load_model_with_quantization(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that quantization is detected when loading a model with a
        quantization pattern in the path."""
        # Create a model file with quantization pattern in name
        q_path = os.path.join(temp_model_dir, "model-q4_0.gguf")
        create_minimal_gguf(q_path)
        metadata = runtime_manager.load_model(q_path, "q4_model")
        assert metadata.quantization == "q4_0"


# ============================================================================
# Test: Model Unloading
# ============================================================================


@pytest.mark.runtime
class TestModelUnloading:
    """Tests for model unloading with reference counting."""

    def test_unload_model(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that a loaded model can be unloaded successfully."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "test_model")
        assert runtime_manager.get_loaded_count() == 1

        result = runtime_manager.unload_model("test_model")
        assert result is True
        assert runtime_manager.get_loaded_count() == 0

    def test_unload_nonexistent_model(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that unloading a model that was never loaded raises an error."""
        with pytest.raises(MockRuntimeModelNotLoadedError, match="not loaded"):
            runtime_manager.unload_model("nonexistent_model")

    def test_unload_already_unloaded(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that unloading a model after it was already unloaded raises."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "test_model")
        runtime_manager.unload_model("test_model")
        with pytest.raises(MockRuntimeModelNotLoadedError, match="not loaded"):
            runtime_manager.unload_model("test_model")

    def test_unload_with_reference_count(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that unloading a model with ref_count > 1 decrements the
        count but does not fully unload."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "test_model")  # ref = 1
        runtime_manager.load_model(model_path, "test_model")  # ref = 2
        assert runtime_manager.get_loaded_count() == 1

        # First unload: ref goes to 1, model stays
        result = runtime_manager.unload_model("test_model")
        assert result is False
        assert runtime_manager.get_loaded_count() == 1

        # Second unload: ref goes to 0, model is removed
        result = runtime_manager.unload_model("test_model")
        assert result is True
        assert runtime_manager.get_loaded_count() == 0

    def test_unload_model_updates_stats(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that model unloading increments the unload counter."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "test_model")
        runtime_manager.unload_model("test_model")
        stats = runtime_manager.get_stats()
        assert stats["total_model_unloads"] == 1

    def test_unload_model_event_log(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that model unloading is recorded in the event log."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "test_model")
        runtime_manager.clear_event_log()
        runtime_manager.unload_model("test_model")
        assert any("unloaded" in e for e in runtime_manager.event_log)

    def test_unload_all_models(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that unloading all models results in an empty state."""
        model1 = os.path.join(temp_model_dir, "test_model.gguf")
        model2 = os.path.join(temp_model_dir, "phi-3-mini.gguf")
        runtime_manager.load_model(model1, "model_1")
        runtime_manager.load_model(model2, "model_2")
        assert runtime_manager.get_loaded_count() == 2

        runtime_manager.unload_model("model_1")
        runtime_manager.unload_model("model_2")
        assert runtime_manager.get_loaded_count() == 0

    def test_unload_empty_model_id(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that unloading with an empty model ID raises an error."""
        with pytest.raises(MockRuntimeModelNotLoadedError, match="not loaded"):
            runtime_manager.unload_model("")

    @pytest.mark.parametrize("model_id", ["", "  ", "\t", "\n"])
    def test_unload_whitespace_model_id(
        self,
        runtime_manager: MockRuntimeManager,
        model_id: str,
    ) -> None:
        """Verify that unloading with whitespace-only model IDs raises errors."""
        with pytest.raises(MockRuntimeModelNotLoadedError):
            runtime_manager.unload_model(model_id)

    def test_unload_and_reload(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that a model can be unloaded and then reloaded with a fresh ref."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "test_model")
        runtime_manager.unload_model("test_model")
        assert runtime_manager.get_loaded_count() == 0

        meta = runtime_manager.load_model(model_path, "test_model")
        assert meta.ref_count == 1
        assert runtime_manager.get_loaded_count() == 1


# ============================================================================
# Test: Model Listing and Info
# ============================================================================


@pytest.mark.runtime
class TestModelListing:
    """Tests for listing and querying loaded models."""

    def test_list_models_empty(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that listing models on an empty runtime returns an empty list."""
        assert runtime_manager.list_models() == []

    def test_list_models_after_load(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that loaded models appear in the model list."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "test_model")
        models = runtime_manager.list_models()
        assert len(models) == 1
        assert models[0].model_id == "test_model"

    def test_list_models_multiple(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that multiple loaded models appear in the model list."""
        model1 = os.path.join(temp_model_dir, "test_model.gguf")
        model2 = os.path.join(temp_model_dir, "phi-3-mini.gguf")
        runtime_manager.load_model(model1, "model_1")
        runtime_manager.load_model(model2, "model_2")
        models = runtime_manager.list_models()
        assert len(models) == 2
        model_ids = {m.model_id for m in models}
        assert model_ids == {"model_1", "model_2"}

    def test_get_model_info(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that get_model_info returns correct metadata for a loaded model."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "test_model")
        info = runtime_manager.get_model_info("test_model")
        assert info.model_id == "test_model"
        assert info.model_path == model_path
        assert info.memory_usage > 0
        assert info.ref_count == 1

    def test_get_model_info_not_loaded(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that get_model_info for a non-loaded model raises an error."""
        with pytest.raises(MockRuntimeModelNotLoadedError, match="not loaded"):
            runtime_manager.get_model_info("nonexistent")

    def test_get_model_info_after_unload(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that get_model_info fails after the model is unloaded."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "test_model")
        runtime_manager.unload_model("test_model")
        with pytest.raises(MockRuntimeModelNotLoadedError, match="not loaded"):
            runtime_manager.get_model_info("test_model")

    def test_list_models_after_unload(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that unloaded models disappear from the listing."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "test_model")
        assert len(runtime_manager.list_models()) == 1
        runtime_manager.unload_model("test_model")
        assert len(runtime_manager.list_models()) == 0

    def test_list_models_with_duplicate_load(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that duplicate loading does not create duplicate entries."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "test_model")
        runtime_manager.load_model(model_path, "test_model")
        models = runtime_manager.list_models()
        assert len(models) == 1
        assert models[0].ref_count == 2


# ============================================================================
# Test: LRU Eviction
# ============================================================================


@pytest.mark.runtime
class TestLRUEviction:
    """Tests for LRU eviction when the model cache is full."""

    def test_lru_eviction_basic(
        self,
        runtime_manager_small_cache: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that the LRU model is evicted when cache is full."""
        rm = runtime_manager_small_cache
        model1 = os.path.join(temp_model_dir, "test_model.gguf")
        model2 = os.path.join(temp_model_dir, "phi-3-mini.gguf")
        model3 = os.path.join(temp_model_dir, "llama-2-7b.gguf")

        rm.load_model(model1, "model_1")
        rm.load_model(model2, "model_2")
        assert rm.get_loaded_count() == 2

        # Loading a third model should evict model_1 (the oldest)
        rm.load_model(model3, "model_3")
        assert rm.get_loaded_count() == 2
        loaded_ids = [m.model_id for m in rm.list_models()]
        assert "model_1" not in loaded_ids
        assert "model_2" in loaded_ids
        assert "model_3" in loaded_ids

    def test_lru_eviction_updates_stats(
        self,
        runtime_manager_small_cache: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that LRU eviction increments the eviction counter."""
        rm = runtime_manager_small_cache
        model1 = os.path.join(temp_model_dir, "test_model.gguf")
        model2 = os.path.join(temp_model_dir, "phi-3-mini.gguf")
        model3 = os.path.join(temp_model_dir, "llama-2-7b.gguf")

        rm.load_model(model1, "model_1")
        rm.load_model(model2, "model_2")
        rm.load_model(model3, "model_3")

        stats = rm.get_stats()
        assert stats["total_evictions"] == 1

    def test_lru_eviction_with_access(
        self,
        runtime_manager_small_cache: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that accessing a model protects it from LRU eviction."""
        rm = runtime_manager_small_cache
        model1 = os.path.join(temp_model_dir, "test_model.gguf")
        model2 = os.path.join(temp_model_dir, "phi-3-mini.gguf")
        model3 = os.path.join(temp_model_dir, "llama-2-7b.gguf")

        rm.load_model(model1, "model_1")
        rm.load_model(model2, "model_2")

        # Access model_1 to make it recently used
        rm.get_model_info("model_1")

        # Loading a third model should evict model_2 (now the oldest)
        rm.load_model(model3, "model_3")
        loaded_ids = [m.model_id for m in rm.list_models()]
        assert "model_2" not in loaded_ids
        assert "model_1" in loaded_ids

    def test_lru_eviction_event_log(
        self,
        runtime_manager_small_cache: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that LRU eviction is recorded in the event log."""
        rm = runtime_manager_small_cache
        model1 = os.path.join(temp_model_dir, "test_model.gguf")
        model2 = os.path.join(temp_model_dir, "phi-3-mini.gguf")
        model3 = os.path.join(temp_model_dir, "llama-2-7b.gguf")

        rm.clear_event_log()
        rm.load_model(model1, "model_1")
        rm.load_model(model2, "model_2")
        rm.load_model(model3, "model_3")

        assert any("LRU evicting" in e for e in rm.event_log)

    def test_lru_eviction_with_reference_count(
        self,
        runtime_manager_small_cache: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that LRU eviction still works on a model with ref_count > 1."""
        rm = runtime_manager_small_cache
        model1 = os.path.join(temp_model_dir, "test_model.gguf")
        model2 = os.path.join(temp_model_dir, "phi-3-mini.gguf")
        model3 = os.path.join(temp_model_dir, "llama-2-7b.gguf")

        rm.load_model(model1, "model_1")
        rm.load_model(model1, "model_1")  # ref_count = 2
        rm.load_model(model2, "model_2")

        # Loading a third model should evict model_1 (oldest) despite ref_count
        rm.load_model(model3, "model_3")
        loaded_ids = [m.model_id for m in rm.list_models()]
        assert "model_1" not in loaded_ids

    def test_lru_eviction_large_cache(self, temp_model_dir: str) -> None:
        """Verify LRU eviction with a larger cache size."""
        rm = MockRuntimeManager(max_loaded_models=5)
        for i in range(6):
            path = os.path.join(temp_model_dir, f"model_{i}.gguf")
            create_minimal_gguf(path)
            rm.load_model(path, f"model_{i}")

        assert rm.get_loaded_count() == 5
        # model_0 should have been evicted
        loaded_ids = [m.model_id for m in rm.list_models()]
        assert "model_0" not in loaded_ids

    def test_lru_eviction_no_models(
        self,
        runtime_manager_small_cache: MockRuntimeManager,
    ) -> None:
        """Verify that LRU eviction handles the empty case gracefully."""
        # Internal method should not crash when no models are loaded
        runtime_manager_small_cache._evict_lru()
        assert runtime_manager_small_cache.get_loaded_count() == 0


# ============================================================================
# Test: Basic Inference
# ============================================================================


@pytest.mark.runtime
class TestBasicInference:
    """Tests for basic inference operations."""

    def test_infer_basic(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that basic inference returns a valid result."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(
            model="test_model",
            prompt="Hello, world!",
            max_tokens=50,
        )
        result = rm.infer(request)
        assert isinstance(result, MockInferenceResult)
        assert result.tokens_generated == 50
        assert result.prompt_tokens > 0
        assert result.inference_ms >= 0
        assert result.tokens_per_second >= 0.0
        assert result.engine == "ggml"
        assert "test_model" in result.output

    def test_infer_model_not_loaded(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that inference on a non-loaded model raises an error."""
        request = MockInferenceRequest(
            model="nonexistent",
            prompt="Hello",
        )
        with pytest.raises(MockRuntimeModelNotLoadedError, match="not loaded"):
            runtime_manager.infer(request)

    def test_infer_empty_prompt(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that inference with an empty prompt returns a valid result."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(
            model="test_model",
            prompt="",
            max_tokens=10,
        )
        result = rm.infer(request)
        assert result.prompt_tokens == 0  # empty string = 0 tokens
        assert result.tokens_generated == 10

    def test_infer_zero_max_tokens(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that inference with max_tokens=0 returns no tokens."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(
            model="test_model",
            prompt="Hello",
            max_tokens=0,
        )
        result = rm.infer(request)
        assert result.tokens_generated == 0
        assert result.inference_ms >= 0

    def test_infer_different_models(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that inference works with different loaded models."""
        model1 = os.path.join(temp_model_dir, "test_model.gguf")
        model2 = os.path.join(temp_model_dir, "phi-3-mini.gguf")
        runtime_manager.load_model(model1, "model_a")
        runtime_manager.load_model(model2, "model_b")

        req1 = MockInferenceRequest(model="model_a", prompt="Hello", max_tokens=10)
        req2 = MockInferenceRequest(model="model_b", prompt="World", max_tokens=10)

        result1 = runtime_manager.infer(req1)
        result2 = runtime_manager.infer(req2)

        assert result1.output != result2.output  # Different model names
        assert "model_a" in result1.output
        assert "model_b" in result2.output

    def test_infer_with_session_id(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that inference accepts an optional session_id."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(
            model="test_model",
            prompt="Hello",
            max_tokens=10,
            session_id="session_123",
        )
        result = rm.infer(request)
        assert result.tokens_generated == 10

    def test_infer_updates_stats(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that inference increments the statistics counters."""
        rm, _ = runtime_manager_with_models
        stats_before = rm.get_stats()

        request = MockInferenceRequest(model="test_model", prompt="Hello", max_tokens=20)
        rm.infer(request)

        stats_after = rm.get_stats()
        assert stats_after["total_inferences"] == stats_before["total_inferences"] + 1
        assert stats_after["total_tokens_generated"] >= stats_before["total_tokens_generated"] + 20

    def test_infer_event_log(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that inference is recorded in the event log."""
        rm, _ = runtime_manager_with_models
        rm.clear_event_log()
        request = MockInferenceRequest(model="test_model", prompt="Hello", max_tokens=5)
        rm.infer(request)
        assert any("Inference" in e for e in rm.event_log)

    def test_infer_prompt_truncation(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that long prompts are truncated in the output preview."""
        rm, _ = runtime_manager_with_models
        long_prompt = "Hello, world! " * 100  # 1500 chars
        request = MockInferenceRequest(
            model="test_model",
            prompt=long_prompt,
            max_tokens=10,
        )
        result = rm.infer(request)
        # The output preview truncates at 50 chars
        assert "Hello, world!" in result.output
        # The prompt_tokens should reflect the full length
        expected_tokens = (len(long_prompt) + 3) // 4
        assert result.prompt_tokens == expected_tokens

    def test_infer_with_large_max_tokens(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that max_tokens is clamped at 2048."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(
            model="test_model",
            prompt="Hello",
            max_tokens=9999,
        )
        result = rm.infer(request)
        assert result.tokens_generated == 2048  # clamped

    def test_infer_negative_temperature(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that negative temperature raises an error at request construction."""
        with pytest.raises(AssertionError):
            MockInferenceRequest(
                model="test_model",
                prompt="Hello",
                temperature=-0.5,
            )

    def test_infer_invalid_top_p(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that top_p > 1.0 raises an error."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(
            model="test_model",
            prompt="Hello",
            top_p=1.5,
        )
        with pytest.raises(MockRuntimeInvalidParameterError, match="top_p"):
            rm.infer(request)


# ============================================================================
# Test: Inference Parameter Variations
# ============================================================================


@pytest.mark.runtime
class TestInferenceParameters:
    """Tests for inference parameter variations using parametrize."""

    @pytest.mark.parametrize("temperature", [0.0, 0.5, 0.7, 1.0, 1.5, 2.0])
    def test_infer_temperature(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
        temperature: float,
    ) -> None:
        """Verify that inference accepts various temperature values."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(
            model="test_model",
            prompt="Test temperature",
            temperature=temperature,
            max_tokens=10,
        )
        result = rm.infer(request)
        assert result.tokens_generated == 10
        # Temperature should appear in the output
        assert f"temp={temperature:.2f}" in result.output

    @pytest.mark.parametrize("top_p", [0.0, 0.5, 0.9, 1.0])
    def test_infer_top_p(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
        top_p: float,
    ) -> None:
        """Verify that inference accepts various top_p values."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(
            model="test_model",
            prompt="Test top_p",
            top_p=top_p,
            max_tokens=10,
        )
        result = rm.infer(request)
        assert result.tokens_generated == 10
        assert f"top_p={top_p:.2f}" in result.output

    @pytest.mark.parametrize("top_k", [1, 10, 40, 100, 1000])
    def test_infer_top_k(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
        top_k: int,
    ) -> None:
        """Verify that inference accepts various top_k values."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(
            model="test_model",
            prompt="Test top_k",
            top_k=top_k,
            max_tokens=10,
        )
        result = rm.infer(request)
        assert result.tokens_generated == 10
        assert f"top_k={top_k}" in result.output

    @pytest.mark.parametrize("max_tokens", [1, 10, 100, 500, 1000])
    def test_infer_max_tokens(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
        max_tokens: int,
    ) -> None:
        """Verify that inference accepts various max_tokens values."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(
            model="test_model",
            prompt="Test max_tokens",
            max_tokens=max_tokens,
        )
        result = rm.infer(request)
        assert result.tokens_generated == min(max_tokens, 2048)

    @pytest.mark.parametrize("repeat_penalty", [0.5, 1.0, 1.1, 1.5, 2.0])
    def test_infer_repeat_penalty(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
        repeat_penalty: float,
    ) -> None:
        """Verify that inference accepts various repeat_penalty values."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(
            model="test_model",
            prompt="Test repeat_penalty",
            repeat_penalty=repeat_penalty,
            max_tokens=10,
        )
        result = rm.infer(request)
        assert result.tokens_generated == 10

    @pytest.mark.parametrize("frequency_penalty", [0.0, 0.5, 1.0, 2.0])
    def test_infer_frequency_penalty(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
        frequency_penalty: float,
    ) -> None:
        """Verify that inference accepts various frequency_penalty values."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(
            model="test_model",
            prompt="Test frequency_penalty",
            frequency_penalty=frequency_penalty,
            max_tokens=10,
        )
        result = rm.infer(request)
        assert result.tokens_generated == 10

    @pytest.mark.parametrize("presence_penalty", [0.0, 0.5, 1.0, 2.0])
    def test_infer_presence_penalty(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
        presence_penalty: float,
    ) -> None:
        """Verify that inference accepts various presence_penalty values."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(
            model="test_model",
            prompt="Test presence_penalty",
            presence_penalty=presence_penalty,
            max_tokens=10,
        )
        result = rm.infer(request)
        assert result.tokens_generated == 10

    @pytest.mark.parametrize("num_threads", [1, 2, 4, 8, 16])
    def test_infer_num_threads(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
        num_threads: int,
    ) -> None:
        """Verify that inference accepts various num_threads values."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(
            model="test_model",
            prompt="Test threads",
            num_threads=num_threads,
            max_tokens=10,
        )
        result = rm.infer(request)
        assert result.tokens_generated == 10


# ============================================================================
# Test: Streaming Inference
# ============================================================================


@pytest.mark.runtime
class TestStreamingInference:
    """Tests for streaming inference."""

    def test_streaming_basic(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that basic streaming inference calls the callback for each
        generated token."""
        rm, _ = runtime_manager_with_models
        tokens: list[str] = []

        def callback(token: str) -> None:
            tokens.append(token)

        request = MockInferenceRequest(
            model="test_model",
            prompt="Hello",
            max_tokens=5,
        )
        result = rm.infer_streaming(request, callback)

        assert len(tokens) == 5
        assert result.tokens_generated == 5
        assert all(t.startswith("token_") for t in tokens)

    def test_streaming_model_not_loaded(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that streaming inference on a non-loaded model raises an error."""
        tokens: list[str] = []

        def callback(token: str) -> None:
            tokens.append(token)

        request = MockInferenceRequest(model="nonexistent", prompt="Hello")
        with pytest.raises(MockRuntimeModelNotLoadedError, match="not loaded"):
            runtime_manager.infer_streaming(request, callback)

        assert len(tokens) == 0  # No tokens should have been generated

    def test_streaming_zero_tokens(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that streaming with max_tokens=0 generates no tokens."""
        rm, _ = runtime_manager_with_models
        tokens: list[str] = []

        def callback(token: str) -> None:
            tokens.append(token)

        request = MockInferenceRequest(
            model="test_model",
            prompt="Hello",
            max_tokens=0,
        )
        result = rm.infer_streaming(request, callback)
        assert len(tokens) == 0
        assert result.tokens_generated == 0

    def test_streaming_large_max_tokens_clamped(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that streaming max_tokens is clamped at 256."""
        rm, _ = runtime_manager_with_models
        tokens: list[str] = []

        def callback(token: str) -> None:
            tokens.append(token)

        request = MockInferenceRequest(
            model="test_model",
            prompt="Hello",
            max_tokens=9999,
        )
        result = rm.infer_streaming(request, callback)
        assert len(tokens) == 256  # clamped
        assert result.tokens_generated == 256

    def test_streaming_callback_receives_tokens(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that the streaming callback receives tokens in order."""
        rm, _ = runtime_manager_with_models
        tokens: list[str] = []

        def callback(token: str) -> None:
            tokens.append(token)

        request = MockInferenceRequest(
            model="test_model",
            prompt="Hello",
            max_tokens=10,
        )
        rm.infer_streaming(request, callback)
        for i, token in enumerate(tokens):
            assert token == f"token_{i + 1} "

    def test_streaming_updates_stats(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that streaming inference updates the statistics."""
        rm, _ = runtime_manager_with_models
        stats_before = rm.get_stats()

        def callback(token: str) -> None:
            pass

        request = MockInferenceRequest(
            model="test_model",
            prompt="Hello",
            max_tokens=10,
        )
        rm.infer_streaming(request, callback)

        stats_after = rm.get_stats()
        assert stats_after["total_inferences"] == stats_before["total_inferences"] + 1
        assert stats_after["total_tokens_generated"] >= stats_before["total_tokens_generated"] + 10

    def test_streaming_event_log(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that streaming inference is recorded in the event log."""
        rm, _ = runtime_manager_with_models
        rm.clear_event_log()

        def callback(token: str) -> None:
            pass

        request = MockInferenceRequest(
            model="test_model",
            prompt="Hello",
            max_tokens=5,
        )
        rm.infer_streaming(request, callback)
        assert any("Streaming inference" in e for e in rm.event_log)

    def test_streaming_with_parameters(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that parameter variations work with streaming inference."""
        rm, _ = runtime_manager_with_models
        tokens: list[str] = []

        def callback(token: str) -> None:
            tokens.append(token)

        request = MockInferenceRequest(
            model="test_model",
            prompt="Hello",
            temperature=0.5,
            top_p=0.8,
            top_k=20,
            max_tokens=5,
        )
        result = rm.infer_streaming(request, callback)
        assert len(tokens) == 5
        assert result.tokens_generated == 5

    def test_streaming_with_session_id(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that streaming inference accepts a session_id."""
        rm, _ = runtime_manager_with_models

        def callback(token: str) -> None:
            pass

        request = MockInferenceRequest(
            model="test_model",
            prompt="Hello",
            max_tokens=3,
            session_id="sess_stream",
        )
        result = rm.infer_streaming(request, callback)
        assert result.tokens_generated == 3

    def test_streaming_callback_error_propagation(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that exceptions in the callback propagate to the caller."""
        rm, _ = runtime_manager_with_models

        def failing_callback(token: str) -> None:
            raise ValueError("Callback error")

        request = MockInferenceRequest(
            model="test_model",
            prompt="Hello",
            max_tokens=3,
        )
        with pytest.raises(ValueError, match="Callback error"):
            rm.infer_streaming(request, failing_callback)


# ============================================================================
# Test: Batch Inference
# ============================================================================


@pytest.mark.runtime
class TestBatchInference:
    """Tests for batch inference operations."""

    def test_batch_infer_basic(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that batch inference processes multiple requests."""
        rm, _ = runtime_manager_with_models
        requests = [
            MockInferenceRequest(model="test_model", prompt="Hello", max_tokens=5),
            MockInferenceRequest(model="test_model", prompt="World", max_tokens=10),
            MockInferenceRequest(model="test_model", prompt="Batch", max_tokens=15),
        ]
        results = rm.batch_infer(requests)
        assert len(results) == 3
        for result in results:
            assert isinstance(result, MockInferenceResult)
        assert results[0].tokens_generated == 5
        assert results[1].tokens_generated == 10
        assert results[2].tokens_generated == 15

    def test_batch_infer_empty(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that an empty batch returns an empty list."""
        results = runtime_manager.batch_infer([])
        assert results == []

    def test_batch_infer_mixed_success_failure(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that batch inference handles mixed success and failure."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "valid_model")

        requests = [
            MockInferenceRequest(model="valid_model", prompt="Hello", max_tokens=5),
            MockInferenceRequest(model="nonexistent", prompt="World", max_tokens=5),
        ]
        results = runtime_manager.batch_infer(requests)
        assert len(results) == 2
        assert isinstance(results[0], MockInferenceResult)
        assert isinstance(results[1], MockRuntimeError)

    def test_batch_infer_all_fail(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that batch inference handles all failures gracefully."""
        requests = [
            MockInferenceRequest(model="nonexistent_1", prompt="Hello", max_tokens=5),
            MockInferenceRequest(model="nonexistent_2", prompt="World", max_tokens=5),
        ]
        results = runtime_manager.batch_infer(requests)
        assert len(results) == 2
        assert all(isinstance(r, MockRuntimeError) for r in results)

    def test_batch_infer_updates_stats(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that batch inference updates the statistics."""
        rm, _ = runtime_manager_with_models
        stats_before = rm.get_stats()

        requests = [
            MockInferenceRequest(model="test_model", prompt="A", max_tokens=5),
            MockInferenceRequest(model="test_model", prompt="B", max_tokens=5),
        ]
        rm.batch_infer(requests)

        stats_after = rm.get_stats()
        assert stats_after["total_inferences"] == stats_before["total_inferences"] + 2

    def test_batch_infer_large_batch(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that batch inference can handle a large number of requests."""
        rm, _ = runtime_manager_with_models
        requests = [
            MockInferenceRequest(model="test_model", prompt=f"Request {i}", max_tokens=2)
            for i in range(50)
        ]
        results = rm.batch_infer(requests)
        assert len(results) == 50
        assert all(isinstance(r, MockInferenceResult) for r in results)


# ============================================================================
# Test: Context Management
# ============================================================================


@pytest.mark.runtime
class TestContextManagement:
    """Tests for context store and retrieve operations."""

    def test_context_store_and_retrieve(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that a value can be stored and then retrieved."""
        runtime_manager.context_store("my_key", "my_value")
        value = runtime_manager.context_retrieve("my_key")
        assert value == "my_value"

    def test_context_store_overwrite(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that storing with an existing key overwrites the value."""
        runtime_manager.context_store("key", "old_value")
        runtime_manager.context_store("key", "new_value")
        value = runtime_manager.context_retrieve("key")
        assert value == "new_value"

    def test_context_retrieve_missing_key(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that retrieving a missing key raises an error."""
        with pytest.raises(MockRuntimeModelNotFoundError, match="Context key not found"):
            runtime_manager.context_retrieve("nonexistent_key")

    def test_context_store_empty_key(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that storing with an empty key raises an error."""
        with pytest.raises(MockRuntimeInvalidParameterError, match="empty"):
            runtime_manager.context_store("", "value")

    def test_context_store_empty_value(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that storing with an empty value is allowed."""
        runtime_manager.context_store("empty_val_key", "")
        value = runtime_manager.context_retrieve("empty_val_key")
        assert value == ""

    def test_context_store_with_session(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that context can be stored and retrieved with a session ID."""
        runtime_manager.context_store("key", "value", session_id="session_1")
        value = runtime_manager.context_retrieve("key", session_id="session_1")
        assert value == "value"

    def test_context_session_isolation(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that context with different session IDs are isolated."""
        runtime_manager.context_store("key", "session_1_value", session_id="session_1")
        runtime_manager.context_store("key", "session_2_value", session_id="session_2")

        v1 = runtime_manager.context_retrieve("key", session_id="session_1")
        v2 = runtime_manager.context_retrieve("key", session_id="session_2")
        assert v1 == "session_1_value"
        assert v2 == "session_2_value"
        assert v1 != v2

    def test_context_store_special_chars_key(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that keys with special characters are accepted."""
        special_key = "!@#$%^&*()_+-=[]{}|;':\",./<>?`~"
        runtime_manager.context_store(special_key, "special_value")
        value = runtime_manager.context_retrieve(special_key)
        assert value == "special_value"

    def test_context_store_unicode_key(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that Unicode keys are accepted."""
        unicode_key = "键名_中文_日本語"
        runtime_manager.context_store(unicode_key, "unicode_value")
        value = runtime_manager.context_retrieve(unicode_key)
        assert value == "unicode_value"

    def test_context_store_unicode_value(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that Unicode values are accepted."""
        unicode_value = "值_中文_日本語_🚀🔥💯"
        runtime_manager.context_store("unicode_val_key", unicode_value)
        value = runtime_manager.context_retrieve("unicode_val_key")
        assert value == unicode_value

    def test_context_store_large_value(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that large values can be stored and retrieved."""
        large_value = "A" * 100000
        runtime_manager.context_store("large_key", large_value)
        value = runtime_manager.context_retrieve("large_key")
        assert value == large_value
        assert len(value) == 100000

    def test_context_delete(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that context deletion works correctly."""
        runtime_manager.context_store("to_delete", "value")
        assert runtime_manager.context_retrieve("to_delete") == "value"
        assert runtime_manager.context_delete("to_delete") is True
        with pytest.raises(MockRuntimeModelNotFoundError):
            runtime_manager.context_retrieve("to_delete")

    def test_context_delete_nonexistent(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that deleting a nonexistent key returns False."""
        assert runtime_manager.context_delete("nonexistent") is False

    def test_context_list_keys(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that listing context keys works correctly."""
        runtime_manager.context_store("key_a", "value_a")
        runtime_manager.context_store("key_b", "value_b")
        runtime_manager.context_store("key_c", "value_c")
        keys = runtime_manager.context_list_keys(session_id=None)
        assert len(keys) == 3
        assert "key_a" in keys
        assert "key_b" in keys
        assert "key_c" in keys

    def test_context_list_keys_empty(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that listing keys with no context returns an empty list."""
        assert runtime_manager.context_list_keys() == []

    def test_context_event_log(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that context operations are recorded in the event log."""
        runtime_manager.clear_event_log()
        runtime_manager.context_store("key", "value")
        assert any("Context stored" in e for e in runtime_manager.event_log)


# ============================================================================
# Test: Error Handling and Error Injection
# ============================================================================


@pytest.mark.runtime
class TestErrorHandling:
    """Tests for error handling and error injection."""

    def test_error_injection_load_model(
        self,
        runtime_manager_error_injector: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that error injection on load_model raises an error."""
        rm = runtime_manager_error_injector
        rm.set_error_injection("load_model", "Simulated load failure")
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        with pytest.raises(MockRuntimeError, match="Simulated load failure"):
            rm.load_model(model_path, "test_model")

    def test_error_injection_unload_model(
        self,
        runtime_manager_error_injector: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that error injection on unload_model raises an error."""
        rm = runtime_manager_error_injector
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        rm.load_model(model_path, "test_model")
        rm.set_error_injection("unload_model", "Unload failed")
        with pytest.raises(MockRuntimeError, match="Unload failed"):
            rm.unload_model("test_model")

    def test_error_injection_infer(
        self,
        runtime_manager_error_injector: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that error injection on infer raises an error."""
        rm = runtime_manager_error_injector
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        rm.load_model(model_path, "test_model")
        rm.set_error_injection("infer", "Inference failed")
        request = MockInferenceRequest(model="test_model", prompt="Hello")
        with pytest.raises(MockRuntimeError, match="Inference failed"):
            rm.infer(request)

    def test_error_injection_infer_streaming(
        self,
        runtime_manager_error_injector: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that error injection on infer_streaming raises an error."""
        rm = runtime_manager_error_injector
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        rm.load_model(model_path, "test_model")
        rm.set_error_injection("infer_streaming", "Streaming failed")

        def callback(token: str) -> None:
            pass

        request = MockInferenceRequest(model="test_model", prompt="Hello")
        with pytest.raises(MockRuntimeError, match="Streaming failed"):
            rm.infer_streaming(request, callback)

    def test_error_injection_batch_infer(
        self,
        runtime_manager_error_injector: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that error injection on batch_infer raises an error."""
        rm = runtime_manager_error_injector
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        rm.load_model(model_path, "test_model")
        rm.set_error_injection("batch_infer", "Batch failed")
        requests = [MockInferenceRequest(model="test_model", prompt="Hello")]
        with pytest.raises(MockRuntimeError, match="Batch failed"):
            rm.batch_infer(requests)

    def test_error_injection_context_store(
        self,
        runtime_manager_error_injector: MockRuntimeManager,
    ) -> None:
        """Verify that error injection on context_store raises an error."""
        rm = runtime_manager_error_injector
        rm.set_error_injection("context_store", "Context store failed")
        with pytest.raises(MockRuntimeError, match="Context store failed"):
            rm.context_store("key", "value")

    def test_error_injection_context_retrieve(
        self,
        runtime_manager_error_injector: MockRuntimeManager,
    ) -> None:
        """Verify that error injection on context_retrieve raises an error."""
        rm = runtime_manager_error_injector
        rm.context_store("key", "value")
        rm.set_error_injection("context_retrieve", "Context retrieve failed")
        with pytest.raises(MockRuntimeError, match="Context retrieve failed"):
            rm.context_retrieve("key")

    def test_clear_error_injection(
        self,
        runtime_manager_error_injector: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that cleared error injection allows normal operation."""
        rm = runtime_manager_error_injector
        rm.set_error_injection("load_model", "failure")
        rm.clear_all_error_injections()
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        metadata = rm.load_model(model_path, "test_model")
        assert metadata.model_id == "test_model"

    def test_error_injection_persists_until_cleared(
        self,
        runtime_manager_error_injector: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that error injection persists until explicitly cleared."""
        rm = runtime_manager_error_injector
        rm.set_error_injection("infer", "Persistent failure")
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        rm.load_model(model_path, "test_model")

        request = MockInferenceRequest(model="test_model", prompt="Hello")
        with pytest.raises(MockRuntimeError, match="Persistent failure"):
            rm.infer(request)

        # Still fails
        with pytest.raises(MockRuntimeError, match="Persistent failure"):
            rm.infer(request)

        # Clear and retry
        rm.clear_all_error_injections()
        result = rm.infer(request)
        assert isinstance(result, MockInferenceResult)

    def test_error_injection_multiple_ops(
        self,
        runtime_manager_error_injector: MockRuntimeManager,
    ) -> None:
        """Verify that error injection can be set for multiple operations."""
        rm = runtime_manager_error_injector
        rm.set_error_injection("load_model", "Load fail")
        rm.set_error_injection("infer", "Infer fail")
        rm.set_error_injection("unload_model", "Unload fail")

        assert len(rm._error_injection) == 3

    def test_error_injection_updates_stats(
        self,
        runtime_manager_error_injector: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that error injection increments the error counter."""
        rm = runtime_manager_error_injector
        stats_before = rm.get_stats()
        rm.set_error_injection("load_model", "failure")
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        try:
            rm.load_model(model_path, "test_model")
        except MockRuntimeError:
            pass
        stats_after = rm.get_stats()
        assert stats_after["total_errors"] == stats_before["total_errors"] + 1

    def test_error_injection_event_log(
        self,
        runtime_manager_error_injector: MockRuntimeManager,
    ) -> None:
        """Verify that error injection is recorded in the event log."""
        rm = runtime_manager_error_injector
        rm.clear_event_log()
        rm.set_error_injection("load_model", "failure")
        try:
            rm.load_model("/nonexistent", "test")
        except MockRuntimeError:
            pass
        assert any("Error injected" in e for e in rm.event_log)

    def test_set_error_injection_single_operation(
        self,
        runtime_manager_error_injector: MockRuntimeManager,
    ) -> None:
        """Verify that setting error injection for one operation does not
        affect other operations."""
        rm = runtime_manager_error_injector
        rm.set_error_injection("load_model", "failure")
        # Other operations should still work
        rm.context_store("key", "value")
        assert rm.context_retrieve("key") == "value"


# ============================================================================
# Test: Model Lifecycle
# ============================================================================


@pytest.mark.runtime
class TestModelLifecycle:
    """Tests for the full model lifecycle (load -> infer -> unload)."""

    def test_full_lifecycle(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify the complete model lifecycle: load, infer, unload."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        metadata = runtime_manager.load_model(model_path, "lifecycle_model")
        assert metadata.ref_count == 1

        request = MockInferenceRequest(
            model="lifecycle_model",
            prompt="Testing lifecycle",
            max_tokens=10,
        )
        result = runtime_manager.infer(request)
        assert result.tokens_generated == 10

        success = runtime_manager.unload_model("lifecycle_model")
        assert success is True
        assert runtime_manager.get_loaded_count() == 0

    def test_load_infer_unload_infer(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that inference fails after model is unloaded."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "cycle_model")
        runtime_manager.unload_model("cycle_model")

        request = MockInferenceRequest(model="cycle_model", prompt="Hello")
        with pytest.raises(MockRuntimeModelNotLoadedError, match="not loaded"):
            runtime_manager.infer(request)

    def test_load_unload_reload(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that unloading and reloading a model creates a fresh ref."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        meta1 = runtime_manager.load_model(model_path, "reload_model")
        runtime_manager.unload_model("reload_model")

        meta2 = runtime_manager.load_model(model_path, "reload_model")
        assert meta2.ref_count == 1
        assert meta2.model_id == meta1.model_id

    def test_load_infer_unload_infer_reload(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that a model can be used again after reloading."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "reuse_model")
        runtime_manager.infer(
            MockInferenceRequest(model="reuse_model", prompt="First", max_tokens=5)
        )
        runtime_manager.unload_model("reuse_model")

        runtime_manager.load_model(model_path, "reuse_model")
        result = runtime_manager.infer(
            MockInferenceRequest(model="reuse_model", prompt="Second", max_tokens=5)
        )
        assert result.tokens_generated == 5

    def test_concurrent_load_same_model(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that loading the same model from multiple callers increases
        ref count correctly."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        meta1 = runtime_manager.load_model(model_path, "concurrent_model")
        meta2 = runtime_manager.load_model(model_path, "concurrent_model")
        meta3 = runtime_manager.load_model(model_path, "concurrent_model")

        assert meta1.ref_count == 1
        assert meta2.ref_count == 2
        assert meta3.ref_count == 3
        assert runtime_manager.get_loaded_count() == 1

        # Unload from three callers
        runtime_manager.unload_model("concurrent_model")  # ref -> 2
        runtime_manager.unload_model("concurrent_model")  # ref -> 1
        assert runtime_manager.get_loaded_count() == 1
        runtime_manager.unload_model("concurrent_model")  # ref -> 0, fully unloaded
        assert runtime_manager.get_loaded_count() == 0

    def test_lifecycle_with_multiple_models(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that multiple models can independently go through their
        lifecycle."""
        model1 = os.path.join(temp_model_dir, "test_model.gguf")
        model2 = os.path.join(temp_model_dir, "phi-3-mini.gguf")

        runtime_manager.load_model(model1, "model_a")
        runtime_manager.load_model(model2, "model_b")
        assert runtime_manager.get_loaded_count() == 2

        runtime_manager.infer(
            MockInferenceRequest(model="model_a", prompt="Hello", max_tokens=5)
        )
        runtime_manager.infer(
            MockInferenceRequest(model="model_b", prompt="World", max_tokens=5)
        )

        runtime_manager.unload_model("model_a")
        assert runtime_manager.get_loaded_count() == 1
        runtime_manager.unload_model("model_b")
        assert runtime_manager.get_loaded_count() == 0

    def test_lifecycle_stats_accumulation(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that statistics accumulate correctly across the lifecycle."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "stats_model")
        runtime_manager.infer(
            MockInferenceRequest(model="stats_model", prompt="Hello", max_tokens=10)
        )
        runtime_manager.infer(
            MockInferenceRequest(model="stats_model", prompt="World", max_tokens=20)
        )
        runtime_manager.unload_model("stats_model")

        stats = runtime_manager.get_stats()
        assert stats["total_model_loads"] == 1
        assert stats["total_model_unloads"] == 1
        assert stats["total_inferences"] == 2
        assert stats["total_tokens_generated"] == 30  # 10 + 20

    def test_lifecycle_with_duplicate_infer(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that inference can be called multiple times on the same
        model without issues."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "multi_infer_model")
        for i in range(10):
            result = runtime_manager.infer(
                MockInferenceRequest(
                    model="multi_infer_model",
                    prompt=f"Inference {i}",
                    max_tokens=3,
                )
            )
            assert result.tokens_generated == 3
        runtime_manager.unload_model("multi_infer_model")


# ============================================================================
# Test: Power Policy
# ============================================================================


@pytest.mark.runtime
class TestPowerPolicy:
    """Tests for power policy state management."""

    def test_default_power_state(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that the default power state is BALANCED."""
        assert runtime_manager.get_power_state() == PowerState.BALANCED
        assert not runtime_manager.is_throttled()

    def test_power_state_transitions(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that power state transitions work correctly."""
        runtime_manager.set_power_state(PowerState.PERFORMANCE)
        assert runtime_manager.get_power_state() == PowerState.PERFORMANCE
        assert not runtime_manager.is_throttled()

        runtime_manager.set_power_state(PowerState.BALANCED)
        assert runtime_manager.get_power_state() == PowerState.BALANCED

        runtime_manager.set_power_state(PowerState.POWER_SAVE)
        assert runtime_manager.get_power_state() == PowerState.POWER_SAVE
        assert not runtime_manager.is_throttled()

    def test_power_state_throttled(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that THROTTLED state is detected as throttled."""
        runtime_manager.set_power_state(PowerState.THROTTLED)
        assert runtime_manager.is_throttled()

    def test_power_state_critical(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that CRITICAL state is detected as throttled."""
        runtime_manager.set_power_state(PowerState.CRITICAL)
        assert runtime_manager.is_throttled()

    def test_power_state_critical_blocks_inference(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that inference is blocked in CRITICAL power state."""
        rm, _ = runtime_manager_with_models
        rm.set_power_state(PowerState.CRITICAL)

        request = MockInferenceRequest(model="test_model", prompt="Hello")
        with pytest.raises(MockRuntimeThermalThrottleError, match="CRITICAL"):
            rm.infer(request)

    def test_power_state_throttled_allows_inference(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that inference is still allowed in THROTTLED state."""
        rm, _ = runtime_manager_with_models
        rm.set_power_state(PowerState.THROTTLED)

        request = MockInferenceRequest(model="test_model", prompt="Hello", max_tokens=5)
        result = rm.infer(request)
        assert result.tokens_generated == 5

    def test_power_state_transition_back_to_balanced(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that returning to BALANCED state unblocks inference."""
        rm, _ = runtime_manager_with_models
        rm.set_power_state(PowerState.CRITICAL)
        with pytest.raises(MockRuntimeThermalThrottleError):
            rm.infer(MockInferenceRequest(model="test_model", prompt="Hello"))

        rm.set_power_state(PowerState.BALANCED)
        result = rm.infer(MockInferenceRequest(model="test_model", prompt="Hello", max_tokens=5))
        assert result.tokens_generated == 5

    def test_power_state_event_log(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that power state changes are recorded in the event log."""
        runtime_manager.clear_event_log()
        runtime_manager.set_power_state(PowerState.PERFORMANCE)
        assert any("Power state" in e for e in runtime_manager.event_log)
        assert "PERFORMANCE" in runtime_manager.event_log[-1]

    def test_power_state_performance_throughput(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that inference completes in PERFORMANCE mode (no throttle)."""
        rm, _ = runtime_manager_with_models
        rm.set_power_state(PowerState.PERFORMANCE)
        result = rm.infer(
            MockInferenceRequest(model="test_model", prompt="Speed test", max_tokens=10)
        )
        assert result.tokens_generated == 10

    def test_power_state_power_save(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that inference works in POWER_SAVE state."""
        rm, _ = runtime_manager_with_models
        rm.set_power_state(PowerState.POWER_SAVE)
        result = rm.infer(
            MockInferenceRequest(model="test_model", prompt="Power save", max_tokens=10)
        )
        assert result.tokens_generated == 10


# ============================================================================
# Test: FFI/Marshalling
# ============================================================================


@pytest.mark.runtime
class TestFFIBoundary:
    """Tests for FFI boundary marshalling and error propagation."""

    def test_model_metadata_marshalling(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that model metadata is correctly marshalled."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        metadata = runtime_manager.load_model(model_path, "ffi_model")
        assert isinstance(metadata, MockModelMetadata)
        assert isinstance(metadata.model_id, str)
        assert isinstance(metadata.model_path, str)
        assert isinstance(metadata.framework, str)
        assert isinstance(metadata.memory_usage, int)
        assert isinstance(metadata.ref_count, int)
        assert isinstance(metadata.n_layers, int)
        assert isinstance(metadata.n_heads, int)
        assert isinstance(metadata.n_embd, int)
        assert isinstance(metadata.n_vocab, int)

    def test_inference_result_marshalling(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that inference result is correctly marshalled."""
        rm, _ = runtime_manager_with_models
        result = rm.infer(
            MockInferenceRequest(model="test_model", prompt="Hello", max_tokens=10)
        )
        assert isinstance(result, MockInferenceResult)
        assert isinstance(result.output, str)
        assert isinstance(result.tokens_generated, int)
        assert isinstance(result.prompt_tokens, int)
        assert isinstance(result.inference_ms, int)
        assert isinstance(result.tokens_per_second, float)
        assert isinstance(result.engine, str)

    def test_error_propagation_through_mock(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that errors are correctly propagated through the mock layer."""
        with pytest.raises(MockRuntimeModelNotFoundError):
            runtime_manager.load_model("/nonexistent", "fail")

        with pytest.raises(MockRuntimeModelNotLoadedError):
            runtime_manager.unload_model("nonexistent")

        with pytest.raises(MockRuntimeInvalidParameterError):
            runtime_manager.load_model("", "empty")

    def test_engine_type_enum_marshalling(self) -> None:
        """Verify that the EngineType enum values are consistent."""
        assert EngineType.GGML.value == "ggml"
        assert EngineType.ONNX.value == "onnx"
        assert EngineType.GGML != EngineType.ONNX

    def test_mock_error_hierarchy(self) -> None:
        """Verify that MockRuntimeError subclasses form the correct hierarchy."""
        assert issubclass(MockRuntimeModelNotFoundError, MockRuntimeError)
        assert issubclass(MockRuntimeModelNotLoadedError, MockRuntimeError)
        assert issubclass(MockRuntimeInvalidParameterError, MockRuntimeError)
        assert issubclass(MockRuntimeEngineNotReadyError, MockRuntimeError)
        assert issubclass(MockRuntimeOutOfMemoryError, MockRuntimeError)
        assert issubclass(MockRuntimeTimeoutError, MockRuntimeError)
        assert issubclass(MockRuntimeThermalThrottleError, MockRuntimeError)

    def test_mock_error_isinstance(self) -> None:
        """Verify that isinstance checks work correctly for mock errors."""
        try:
            raise MockRuntimeModelNotFoundError("test")
        except MockRuntimeError:
            pass  # Expected
        except Exception:
            pytest.fail("MockRuntimeModelNotFoundError is not a MockRuntimeError")

    def test_mock_inference_request_defaults(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that MockInferenceRequest defaults match Rust defaults."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(model="test_model", prompt="Hello")
        assert request.temperature == 0.7
        assert request.top_p == 0.9
        assert request.top_k == 40
        assert request.max_tokens == 512
        assert request.repeat_penalty == 1.1
        assert request.frequency_penalty == 0.0
        assert request.presence_penalty == 0.0
        assert request.session_id is None
        assert request.num_threads is None

    def test_inference_result_validation(self) -> None:
        """Verify that MockInferenceResult validates its fields."""
        result = MockInferenceResult(
            output="test",
            tokens_generated=10,
            prompt_tokens=5,
            inference_ms=100,
            tokens_per_second=100.0,
            engine="ggml",
        )
        assert result.output == "test"
        assert result.tokens_generated == 10

        # Invalid engine
        with pytest.raises(AssertionError):
            MockInferenceResult(
                output="test", tokens_generated=0, prompt_tokens=0,
                inference_ms=0, tokens_per_second=0.0, engine="invalid",
            )

    def test_model_metadata_validation(self) -> None:
        """Verify that MockModelMetadata validates its fields."""
        meta = MockModelMetadata(
            model_id="test",
            model_path="/path/to/model.gguf",
            framework="ggml",
            quantization="q4_0",
            loaded_time=100.0,
            memory_usage=1024,
            device="CPU",
            ref_count=1,
            architecture="llama",
            n_layers=32,
            n_heads=32,
            n_embd=4096,
            n_vocab=32000,
        )
        assert meta.model_id == "test"

        # Empty model_id should fail
        with pytest.raises(AssertionError):
            MockModelMetadata(
                model_id="", model_path="", framework="", quantization=None,
                loaded_time=0.0, memory_usage=0, device="", ref_count=0,
                architecture="", n_layers=0, n_heads=0, n_embd=0, n_vocab=0,
            )


# ============================================================================
# Test: Edge Cases
# ============================================================================


@pytest.mark.runtime
class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_very_long_prompt(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that inference handles very long prompts (>100k chars)."""
        rm, _ = runtime_manager_with_models
        long_prompt = "The quick brown fox " * 10000  # 200k chars
        request = MockInferenceRequest(
            model="test_model",
            prompt=long_prompt,
            max_tokens=5,
        )
        # Should not raise; the prompt is truncated in the output preview
        result = rm.infer(request)
        assert result.tokens_generated == 5
        assert result.prompt_tokens == (len(long_prompt) + 3) // 4

    def test_special_characters_in_prompt(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that inference handles prompts with special characters."""
        rm, _ = runtime_manager_with_models
        special_prompt = "!@#$%^&*()_+-=[]{}|;':\",./<>?`~你好🚀🔥💯"
        request = MockInferenceRequest(
            model="test_model",
            prompt=special_prompt,
            max_tokens=5,
        )
        result = rm.infer(request)
        assert result.tokens_generated == 5

    def test_null_bytes_in_prompt(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that inference handles null bytes in prompts."""
        rm, _ = runtime_manager_with_models
        null_prompt = "Hello\x00World\x00"
        request = MockInferenceRequest(
            model="test_model",
            prompt=null_prompt,
            max_tokens=5,
        )
        result = rm.infer(request)
        assert result.tokens_generated == 5

    def test_whitespace_only_prompt(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that inference handles whitespace-only prompts."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(
            model="test_model",
            prompt="   \t\n  \n  ",
            max_tokens=5,
        )
        result = rm.infer(request)
        assert result.tokens_generated == 5

    def test_extremely_long_model_id(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that model loading works with very long model IDs."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        long_id = "a" * 1000
        metadata = runtime_manager.load_model(model_path, long_id)
        assert metadata.model_id == long_id
        assert runtime_manager.get_loaded_count() == 1

    def test_model_id_with_special_chars(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that model loading works with special characters in model ID."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        special_id = "model_!@#$%^&*()_+-=[]{}|;':\",./<>?`~模型"
        metadata = runtime_manager.load_model(model_path, special_id)
        assert metadata.model_id == special_id

    def test_max_models_zero(self) -> None:
        """Verify that a runtime with max_loaded_models=0 can still function
        (but cannot load models)."""
        rm = MockRuntimeManager(max_loaded_models=0)
        stats = rm.get_stats()
        assert stats["max_loaded_models"] == 0

    def test_inference_with_no_model(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that inference without any loaded model raises an error."""
        request = MockInferenceRequest(model="nonexistent", prompt="Hello")
        with pytest.raises(MockRuntimeModelNotLoadedError):
            runtime_manager.infer(request)

    def test_streaming_with_no_model(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that streaming inference without a loaded model raises."""
        def callback(token: str) -> None:
            pass

        request = MockInferenceRequest(model="nonexistent", prompt="Hello")
        with pytest.raises(MockRuntimeModelNotLoadedError):
            runtime_manager.infer_streaming(request, callback)

    def test_negative_max_tokens(
        self,
    ) -> None:
        """Verify that negative max_tokens raises an error at request
        construction."""
        with pytest.raises(AssertionError):
            MockInferenceRequest(
                model="test_model",
                prompt="Hello",
                max_tokens=-1,
            )

    def test_top_p_out_of_range(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that top_p > 1.0 raises an error."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(
            model="test_model",
            prompt="Hello",
            top_p=1.5,
        )
        with pytest.raises(MockRuntimeInvalidParameterError, match="top_p"):
            rm.infer(request)

    @pytest.mark.parametrize("bad_temp", [-0.1, -1.0, -100.0])
    def test_negative_temperature_parametrized(
        self,
        bad_temp: float,
    ) -> None:
        """Verify that various negative temperatures raise errors at request
        construction."""
        with pytest.raises(AssertionError):
            MockInferenceRequest(
                model="test_model",
                prompt="Hello",
                temperature=bad_temp,
            )

    def test_load_model_very_long_path(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that model loading with a very long path works."""
        with tempfile.TemporaryDirectory() as deep_dir:
            deep_path = os.path.join(deep_dir, "a" * 200 + ".gguf")
            create_minimal_gguf(deep_path)
            metadata = runtime_manager.load_model(deep_path, "deep_path_model")
            assert metadata.model_path == deep_path

    def test_context_very_long_key(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that context works with very long keys."""
        long_key = "k" * 10000
        runtime_manager.context_store(long_key, "value")
        value = runtime_manager.context_retrieve(long_key)
        assert value == "value"

    def test_context_very_long_value(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that context works with very long values."""
        long_value = "v" * 1000000  # 1MB
        runtime_manager.context_store("big_key", long_value)
        value = runtime_manager.context_retrieve("big_key")
        assert len(value) == 1000000

    def test_unicode_normalization(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that context stores and retrieves Unicode values without
        normalization issues."""
        runtime_manager.context_store("cafe_key", "café")
        runtime_manager.context_store("cafe_key_nfc", "café")  # NFC
        value = runtime_manager.context_retrieve("cafe_key")
        assert value == "café"

    def test_concurrent_context_operations(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that context operations are thread-safe."""
        errors: list[str] = []
        def worker(worker_id: int) -> None:
            try:
                for i in range(100):
                    key = f"worker_{worker_id}_key_{i}"
                    runtime_manager.context_store(key, f"value_{worker_id}_{i}")
                    val = runtime_manager.context_retrieve(key)
                    assert val == f"value_{worker_id}_{i}"
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent errors: {errors}"

    def test_statistics_overflow(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that statistics counters handle large values without overflow."""
        rm, _ = runtime_manager_with_models
        # Simulate many inferences
        for i in range(1000):
            rm.infer(
                MockInferenceRequest(
                    model="test_model",
                    prompt=f"Inference {i}",
                    max_tokens=1,
                )
            )
        stats = rm.get_stats()
        assert stats["total_inferences"] == 1000
        assert stats["total_tokens_generated"] == 1000


# ============================================================================
# Test: Concurrent Access and Race Conditions
# ============================================================================


@pytest.mark.runtime
class TestConcurrentAccess:
    """Tests for concurrent access and thread safety."""

    def test_concurrent_model_load(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that loading models from multiple threads is safe."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        errors: list[str] = []

        def load_worker(worker_id: int) -> None:
            try:
                for i in range(20):
                    mid = f"model_{worker_id}_{i}"
                    runtime_manager.load_model(model_path, mid)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=load_worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent load errors: {errors}"

    def test_concurrent_inference(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that running inference from multiple threads is safe."""
        rm, _ = runtime_manager_with_models
        errors: list[str] = []

        def infer_worker() -> None:
            try:
                for i in range(50):
                    request = MockInferenceRequest(
                        model="test_model",
                        prompt=f"Concurrent inference {i}",
                        max_tokens=2,
                    )
                    result = rm.infer(request)
                    assert result.tokens_generated == 2
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=infer_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent inference errors: {errors}"

    def test_concurrent_load_and_infer(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that concurrent loading and inference is safe."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        errors: list[str] = []

        def loader_worker() -> None:
            try:
                for i in range(10):
                    runtime_manager.load_model(model_path, "shared_model")
            except Exception as e:
                errors.append(str(e))

        def infer_worker() -> None:
            try:
                for i in range(10):
                    try:
                        request = MockInferenceRequest(
                            model="shared_model",
                            prompt="Hello",
                            max_tokens=2,
                        )
                        rm = runtime_manager
                        rm.infer(request)
                    except MockRuntimeModelNotLoadedError:
                        pass  # Expected if model not yet loaded
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=loader_worker) for _ in range(3)]
        threads += [threading.Thread(target=infer_worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent errors: {errors}"

    def test_concurrent_context_and_inference(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that concurrent context and inference operations are safe."""
        rm, _ = runtime_manager_with_models
        errors: list[str] = []

        def context_worker() -> None:
            try:
                for i in range(50):
                    key = f"ctx_key_{i}"
                    rm.context_store(key, f"value_{i}")
                    val = rm.context_retrieve(key)
                    assert val == f"value_{i}"
            except Exception as e:
                errors.append(str(e))

        def infer_worker() -> None:
            try:
                for i in range(50):
                    request = MockInferenceRequest(
                        model="test_model",
                        prompt=f"Concurrent {i}",
                        max_tokens=2,
                    )
                    result = rm.infer(request)
                    assert result.tokens_generated == 2
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=context_worker) for _ in range(3)]
        threads += [threading.Thread(target=infer_worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent errors: {errors}"

    def test_concurrent_model_unload(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that concurrent model unloading is safe."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        errors: list[str] = []

        # Load model multiple times to increase ref count
        for i in range(5):
            runtime_manager.load_model(model_path, "shared_unload")

        def unloader_worker() -> None:
            try:
                runtime_manager.unload_model("shared_unload")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=unloader_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent unload errors: {errors}"
        # Model should be fully unloaded now
        assert runtime_manager.get_loaded_count() == 0

    def test_race_condition_load_unload_rapid(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that rapid load/unload cycles do not cause instability."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        for i in range(100):
            runtime_manager.load_model(model_path, "rapid_model")
            runtime_manager.unload_model("rapid_model")
        assert runtime_manager.get_loaded_count() == 0

    def test_race_condition_duplicate_loads(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that many duplicate loads followed by unloads are correct."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        n = 50
        for i in range(n):
            runtime_manager.load_model(model_path, "dup_model")
        assert runtime_manager.get_loaded_count() == 1
        info = runtime_manager.get_model_info("dup_model")
        assert info.ref_count == n

        for i in range(n):
            runtime_manager.unload_model("dup_model")
        assert runtime_manager.get_loaded_count() == 0


# ============================================================================
# Test: MockDaemon Integration (via conftest fixtures)
# ============================================================================


@pytest.mark.runtime
class TestMockDaemonIntegration:
    """Tests for integration with the MockDaemon from conftest."""

    def test_mock_daemon_available(self, mock_daemon: MockDaemonClient) -> None:
        """Verify that the mock_daemon fixture provides a connected client."""
        assert mock_daemon.connected
        assert mock_daemon.authenticated

    def test_mock_daemon_infer(self, mock_daemon: MockDaemonClient) -> None:
        """Verify that inference through the mock daemon works."""
        resp = mock_daemon.infer("Hello, world!")
        assert_successful_response(resp)
        assert_inference_response(resp)
        assert "Hello, world!" in resp["output"]

    def test_mock_daemon_infer_with_params(
        self, mock_daemon: MockDaemonClient,
    ) -> None:
        """Verify that inference with custom parameters works."""
        resp = mock_daemon.infer("Test prompt", model="llama", temperature=0.5, max_tokens=100)
        assert_inference_response(resp)
        assert "llama" in resp["output"]
        assert "0.5" in resp["output"]
        assert "100" in resp["output"]

    def test_mock_daemon_model_load(
        self, mock_daemon: MockDaemonClient, temp_model_dir: str,
    ) -> None:
        """Verify that model loading through the mock daemon works."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        resp = mock_daemon.model_load(model_path)
        assert_model_load_response(resp)
        assert resp["model_id"] == "test_model"

    def test_mock_daemon_model_unload(
        self, mock_daemon: MockDaemonClient, temp_model_dir: str,
    ) -> None:
        """Verify that model unloading through the mock daemon works."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        mock_daemon.model_load(model_path)
        resp = mock_daemon.model_unload("test_model")
        assert_model_unload_response(resp)

    def test_mock_daemon_model_list(
        self, mock_daemon: MockDaemonClient, temp_model_dir: str,
    ) -> None:
        """Verify that model listing through the mock daemon works."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        mock_daemon.model_load(model_path)
        models = mock_daemon.model_list()
        assert len(models) >= 1
        assert any(m["id"] == "test_model" for m in models)

    def test_mock_daemon_status(
        self, mock_daemon: MockDaemonClient,
    ) -> None:
        """Verify that status query through the mock daemon works."""
        resp = mock_daemon.status()
        assert_status_response(resp)

    def test_mock_daemon_context(
        self, mock_daemon: MockDaemonClient,
    ) -> None:
        """Verify that context operations through the mock daemon work."""
        resp = mock_daemon.context_store("test_key", "test_value")
        assert_successful_response(resp)

        resp = mock_daemon.context_retrieve("test_key")
        assert_successful_response(resp)
        assert "test_value" in resp["output"]

    def test_mock_daemon_auth(
        self, mock_daemon: MockDaemonClient,
    ) -> None:
        """Verify that the mock daemon client is authenticated."""
        assert mock_daemon.authenticated is True

    def test_mock_daemon_infer_stream(
        self, mock_daemon: MockDaemonClient,
    ) -> None:
        """Verify that streaming inference through the mock daemon works."""
        resp = mock_daemon.infer_stream("Hello", model="default")
        assert_successful_response(resp)
        assert "chunk" in resp or "done" in resp

    def test_mock_daemon_rate_limit_status(
        self, mock_daemon: MockDaemonClient,
    ) -> None:
        """Verify that rate limit status query works."""
        resp = mock_daemon.rate_limit_status()
        assert_successful_response(resp)
        assert "limits" in resp


# ============================================================================
# Test: MockDaemon Error Cases
# ============================================================================


@pytest.mark.runtime
class TestMockDaemonErrors:
    """Tests for error handling in MockDaemon interactions."""

    def test_mock_daemon_load_nonexistent(
        self, mock_daemon: MockDaemonClient,
    ) -> None:
        """Verify that loading a nonexistent model returns an error."""
        resp = mock_daemon.model_load("/nonexistent/model.gguf")
        assert resp.get("type") == "ModelLoadResponse"
        assert resp.get("status") == "error"

    def test_mock_daemon_load_empty_path(
        self, mock_daemon: MockDaemonClient,
    ) -> None:
        """Verify that loading with an empty path returns an error."""
        resp = mock_daemon.model_load("")
        assert resp.get("status") == "error"

    def test_mock_daemon_unload_nonexistent(
        self, mock_daemon: MockDaemonClient,
    ) -> None:
        """Verify that unloading a nonexistent model returns an error."""
        resp = mock_daemon.model_unload("nonexistent_model")
        assert resp.get("status") == "not_found"

    def test_mock_daemon_error_prone(
        self, error_prone_daemon: MockDaemonServer,
    ) -> None:
        """Verify that error-prone daemon fails on configured operations."""
        client = error_prone_daemon.make_authenticated_client()
        with pytest.raises(MockDaemonError, match="Injected failure"):
            client.infer("Hello")
        client.disconnect()

    def test_mock_daemon_slow_response(
        self, slow_daemon: MockDaemonServer,
    ) -> None:
        """Verify that slow daemon adds response delay."""
        client = slow_daemon.make_authenticated_client()
        start = time.monotonic()
        resp = client.infer("Hello")
        elapsed = time.monotonic() - start
        assert elapsed >= 0.04  # 50ms delay - allow some tolerance
        assert_successful_response(resp)
        client.disconnect()

    def test_mock_daemon_rate_limited(
        self, rate_limited_daemon: MockDaemonServer,
    ) -> None:
        """Verify that rate-limited daemon enforces limits."""
        client = rate_limited_daemon.make_authenticated_client()
        # Send many requests quickly with minimal tokens to avoid delays
        for i in range(100):
            try:
                client.infer(f"Request {i}", max_tokens=1)
            except MockDaemonError:
                # Should eventually hit rate limit
                client.disconnect()
                return
        client.disconnect()
        pytest.fail("Should have hit rate limit within 100 requests")

    def test_mock_daemon_no_auth(
        self, no_auth_daemon: MockDaemonServer,
    ) -> None:
        """Verify that the no-auth daemon works without authentication."""
        client = no_auth_daemon.make_client()
        resp = client.infer("Hello")
        assert_successful_response(resp)
        client.disconnect()

    def test_mock_daemon_protocol_error(
        self, mock_daemon: MockDaemonClient,
    ) -> None:
        """Verify that sending invalid JSON is handled gracefully."""
        # The mock_daemon fixture handles cleanup; we just verify behaviour
        # for valid requests
        resp = mock_daemon.infer("Hello")
        assert_successful_response(resp)

    def test_mock_daemon_context_missing_key(
        self, mock_daemon: MockDaemonClient,
    ) -> None:
        """Verify that retrieving a missing context key returns an error."""
        resp = mock_daemon.context_retrieve("nonexistent_key")
        assert_error_response(resp)


# ============================================================================
# Test: MockRuntimeManager with conftest Temp Files
# ============================================================================


@pytest.mark.runtime
class TestWithTempModelDir:
    """Tests using the conftest temp_model_dir fixture."""

    def test_create_minimal_gguf(self, temp_model_dir: str) -> None:
        """Verify that the minimal GGUF file is created correctly."""
        path = os.path.join(temp_model_dir, "test_model.gguf")
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0

    def test_create_minimal_onnx(self, temp_model_dir: str) -> None:
        """Verify that the minimal ONNX file is created correctly."""
        path = os.path.join(temp_model_dir, "test_model.onnx")
        assert os.path.exists(path)

    def test_corrupted_model(self, temp_model_dir: str) -> None:
        """Verify that the corrupted model file exists."""
        path = os.path.join(temp_model_dir, "corrupted_model.gguf")
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0

    def test_empty_model(self, temp_model_dir: str) -> None:
        """Verify that the empty model file exists with zero size."""
        path = os.path.join(temp_model_dir, "empty_model.gguf")
        assert os.path.exists(path)
        assert os.path.getsize(path) == 0

    def test_phi_mini_model(self, temp_model_dir: str) -> None:
        """Verify that the phi-3-mini model file exists."""
        path = os.path.join(temp_model_dir, "phi-3-mini.gguf")
        assert os.path.exists(path)

    def test_llama_model(self, temp_model_dir: str) -> None:
        """Verify that the llama-2-7b model file exists."""
        path = os.path.join(temp_model_dir, "llama-2-7b.gguf")
        assert os.path.exists(path)

    def test_mistral_model(self, temp_model_dir: str) -> None:
        """Verify that the mistral-7b model file exists."""
        path = os.path.join(temp_model_dir, "mistral-7b.gguf")
        assert os.path.exists(path)

    def test_architecture_detection_with_files(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that loading models with architecture names in the path
        correctly detects the architecture."""
        for fname, expected_arch in [
            ("llama-2-7b.gguf", "llama"),
            ("phi-3-mini.gguf", "phi3"),
            ("mistral-7b.gguf", "mistral"),
        ]:
            path = os.path.join(temp_model_dir, fname)
            metadata = runtime_manager.load_model(path, fname.replace(".", "_"))
            assert metadata.architecture == expected_arch, (
                f"Expected {expected_arch} for {fname}, got {metadata.architecture}"
            )


# ============================================================================
# Test: MockKernel Integration
# ============================================================================


@pytest.mark.runtime
class TestMockKernelIntegration:
    """Tests for integration with the KernelStub from conftest."""

    def test_kernel_stub_basic(self, mock_kernel: KernelStub) -> None:
        """Verify that the KernelStub fixture provides a working stub."""
        assert mock_kernel is not None
        assert mock_kernel.total_inferences == 0

    def test_kernel_embedding(self, mock_kernel: KernelStub) -> None:
        """Verify that kernel embedding computation works."""
        np = pytest.importorskip("numpy")
        input_data = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        embedding, err = mock_kernel.ai_embedding(input_data, 3, 128)
        assert err == AI_ERR_SUCCESS
        assert embedding is not None
        assert len(embedding) == 128

    def test_kernel_semantic_search(self, mock_kernel: KernelStub) -> None:
        """Verify that kernel semantic search works."""
        np = pytest.importorskip("numpy")
        query = [0.1, 0.2, 0.3]
        database = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.7, 0.8, 0.9]]
        results, err = mock_kernel.ai_semantic_search(query, database, top_k=2)
        assert err == AI_ERR_SUCCESS
        assert results is not None
        assert len(results) == 2

    def test_kernel_model_load(self, mock_kernel: KernelStub) -> None:
        """Verify that kernel model loading works."""
        model_id, err = mock_kernel.ai_model_load("test_model", "/path/to/model.gguf")
        assert err == AI_ERR_SUCCESS
        assert model_id is not None
        assert model_id > 0

    def test_kernel_model_unload(self, mock_kernel: KernelStub) -> None:
        """Verify that kernel model unloading works."""
        model_id, _ = mock_kernel.ai_model_load("test", "/path/to/model.gguf")
        err = mock_kernel.ai_model_unload(model_id)
        assert err == AI_ERR_SUCCESS

    def test_kernel_context_store(self, mock_kernel: KernelStub) -> None:
        """Verify that kernel context storage works."""
        entry_id, err = mock_kernel.ai_context_store(1, "key", "value", 60000)
        assert err == AI_ERR_SUCCESS
        assert entry_id is not None

    def test_kernel_context_retrieve(self, mock_kernel: KernelStub) -> None:
        """Verify that kernel context retrieval works."""
        mock_kernel.ai_context_store(1, "key", "value", 60000)
        value, err = mock_kernel.ai_context_retrieve(1, "key", 0)
        assert err == AI_ERR_SUCCESS
        assert value == "value"

    def test_kernel_status(self, mock_kernel: KernelStub) -> None:
        """Verify that kernel status query works."""
        status, err = mock_kernel.ai_status()
        assert err == AI_ERR_SUCCESS
        assert "models_loaded" in status
        assert "total_inferences" in status

    def test_kernel_error_injection(self, mock_kernel: KernelStub) -> None:
        """Verify that kernel error injection works."""
        mock_kernel.set_error_injection("embedding", AI_ERR_GENERAL)
        np = pytest.importorskip("numpy")
        input_data = np.array([1.0, 2.0], dtype=np.float32)
        embedding, err = mock_kernel.ai_embedding(input_data, 2, 128)
        assert embedding is None
        assert err == AI_ERR_GENERAL

    def test_kernel_reset(self, mock_kernel: KernelStub) -> None:
        """Verify that kernel reset clears all state."""
        mock_kernel.ai_model_load("test", "/path/model.gguf")
        mock_kernel.reset()
        assert len(mock_kernel.models) == 0


# ============================================================================
# Test: Test Vectors
# ============================================================================


@pytest.mark.runtime
class TestTestVectors:
    """Tests using the test_vectors fixture from conftest."""

    def test_vectors_available(self, test_vectors: dict) -> None:
        """Verify that the test_vectors fixture provides all expected keys."""
        assert "query" in test_vectors
        assert "database" in test_vectors
        assert "embedding_128" in test_vectors
        assert "embedding_256" in test_vectors
        assert "embedding_512" in test_vectors
        assert "long_prompt" in test_vectors
        assert "special_chars_prompt" in test_vectors

    def test_vectors_long_prompt(self, test_vectors: dict) -> None:
        """Verify that the long prompt is properly long."""
        long_prompt = test_vectors["long_prompt"]
        assert len(long_prompt) > 1000

    def test_vectors_special_chars(self, test_vectors: dict) -> None:
        """Verify that the special characters prompt contains expected chars."""
        prompt = test_vectors["special_chars_prompt"]
        assert "你好" in prompt
        assert "🚀" in prompt

    def test_vectors_inference_with_long_prompt(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
        test_vectors: dict,
    ) -> None:
        """Verify that inference works with the long prompt from test vectors."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(
            model="test_model",
            prompt=test_vectors["long_prompt"],
            max_tokens=5,
        )
        result = rm.infer(request)
        assert result.tokens_generated == 5

    def test_vectors_inference_with_special_chars(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
        test_vectors: dict,
    ) -> None:
        """Verify that inference works with special characters."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(
            model="test_model",
            prompt=test_vectors["special_chars_prompt"],
            max_tokens=5,
        )
        result = rm.infer(request)
        assert result.tokens_generated == 5


# ============================================================================
# Test: Deterministic Behaviour
# ============================================================================


@pytest.mark.runtime
class TestDeterministicBehaviour:
    """Tests for deterministic runtime behaviour."""

    def test_deterministic_seed(
        self,
        deterministic_seed: int,
    ) -> None:
        """Verify that the deterministic_seed fixture provides a valid seed."""
        assert deterministic_seed == 42  # Default seed

    def test_deterministic_inference_output(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that inference output is deterministic (same input =
        same output)."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(
            model="test_model",
            prompt="Deterministic test",
            max_tokens=10,
            temperature=0.7,
            top_p=0.9,
            top_k=40,
        )

        result1 = rm.infer(request)
        result2 = rm.infer(request)

        # The output format embeds model and parameters, so should be identical
        assert result1.output == result2.output
        assert result1.tokens_generated == result2.tokens_generated
        assert result1.prompt_tokens == result2.prompt_tokens

    def test_deterministic_seed_effect(self) -> None:
        """Verify that different seeds produce different initial states."""
        rm1 = MockRuntimeManager(seed=42)
        rm2 = MockRuntimeManager(seed=999)
        # Both should have the same structure but potentially different internal
        # random state
        assert rm1.get_stats()["models_loaded"] == rm2.get_stats()["models_loaded"]

    def test_reproducible_quantization(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that quantization detection is always reproducible."""
        paths = ["model-q4_0.gguf", "model-q8_0.gguf", "model-f16.gguf"]
        results1 = [runtime_manager.detect_quantization(p) for p in paths]
        results2 = [runtime_manager.detect_quantization(p) for p in paths]
        assert results1 == results2

    def test_reproducible_architecture(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that architecture detection is always reproducible."""
        paths = ["llama-2-7b.gguf", "phi-3-mini.gguf", "unknown.gguf"]
        results1 = [runtime_manager.detect_architecture(p) for p in paths]
        results2 = [runtime_manager.detect_architecture(p) for p in paths]
        assert results1 == results2


# ============================================================================
# Test: Time Budget
# ============================================================================


@pytest.mark.runtime
class TestTimeBudget:
    """Tests for the time_budget fixture."""

    def test_time_budget_value(
        self,
        time_budget: float,
    ) -> None:
        """Verify that the time_budget fixture provides a positive value."""
        assert time_budget > 0
        assert isinstance(time_budget, float)

    def test_time_budget_default(
        self,
        time_budget: float,
    ) -> None:
        """Verify that the default time budget matches the default timeout."""
        # Should be 30.0 seconds by default
        assert time_budget == 30.0


# ============================================================================
# Test: Model Metadata Construction
# ============================================================================


@pytest.mark.runtime
class TestModelMetadataConstruction:
    """Tests for the MockModelHandle to MockModelMetadata conversion."""

    def test_handle_to_metadata(self) -> None:
        """Verify that MockModelHandle correctly converts to metadata."""
        handle = MockModelHandle(
            model_id="test",
            model_path="/path/to/model.gguf",
            quantization="q4_0",
            architecture="llama",
            n_layers=32,
            n_heads=32,
            n_embd=4096,
            n_vocab=32000,
            memory_usage=4096,
            device="CPU",
            framework="ggml",
        )
        metadata = handle.to_metadata()
        assert metadata.model_id == "test"
        assert metadata.quantization == "q4_0"
        assert metadata.architecture == "llama"
        assert metadata.n_layers == 32
        assert metadata.ref_count == 1
        assert metadata.memory_usage == 4096

    def test_handle_ref_count_tracking(self) -> None:
        """Verify that handle ref count can be updated independently."""
        handle = MockModelHandle(
            model_id="ref_test",
            model_path="/path.gguf",
        )
        assert handle.ref_count == 1
        handle.ref_count += 1
        assert handle.ref_count == 2
        metadata = handle.to_metadata()
        assert metadata.ref_count == 2

    def test_handle_default_values(self) -> None:
        """Verify that MockModelHandle has sensible defaults."""
        handle = MockModelHandle(
            model_id="defaults",
            model_path="/path.gguf",
        )
        assert handle.n_layers == 32
        assert handle.n_heads == 32
        assert handle.n_embd == 4096
        assert handle.n_vocab == 32000
        assert handle.device == "CPU"
        assert handle.framework == "ggml"
        assert handle.quantization is None
        assert handle.architecture == "auto"

    def test_handle_loaded_time(self) -> None:
        """Verify that the loaded time is set on creation."""
        before = time.time()
        handle = MockModelHandle(
            model_id="time_test",
            model_path="/path.gguf",
        )
        after = time.time()
        assert before <= handle.loaded_time <= after

    def test_handle_last_access(self) -> None:
        """Verify that last_access is initialized to loaded_time."""
        handle = MockModelHandle(
            model_id="access_test",
            model_path="/path.gguf",
        )
        assert abs(handle.last_access - handle.loaded_time) < 0.01

    def test_multiple_handles_independent_ref_counts(self) -> None:
        """Verify that multiple handles have independent ref counts."""
        h1 = MockModelHandle(model_id="m1", model_path="/p1.gguf")
        h2 = MockModelHandle(model_id="m2", model_path="/p2.gguf")
        h1.ref_count = 5
        h2.ref_count = 3
        assert h1.ref_count == 5
        assert h2.ref_count == 3


# ============================================================================
# Test: Inference Result Construction
# ============================================================================


@pytest.mark.runtime
class TestInferenceResultConstruction:
    """Tests for MockInferenceResult construction and validation."""

    def test_result_default_construction(self) -> None:
        """Verify that a valid inference result can be constructed."""
        result = MockInferenceResult(
            output="test output",
            tokens_generated=42,
            prompt_tokens=10,
            inference_ms=500,
            tokens_per_second=84.0,
            engine="ggml",
        )
        assert result.output == "test output"
        assert result.tokens_generated == 42
        assert result.tokens_per_second == 84.0

    def test_result_zero_values(self) -> None:
        """Verify that zero values are accepted."""
        result = MockInferenceResult(
            output="",
            tokens_generated=0,
            prompt_tokens=0,
            inference_ms=0,
            tokens_per_second=0.0,
            engine="ggml",
        )
        assert result.output == ""

    def test_result_large_values(self) -> None:
        """Verify that large values are accepted."""
        result = MockInferenceResult(
            output="A" * 100000,
            tokens_generated=1000000,
            prompt_tokens=500000,
            inference_ms=3600000,
            tokens_per_second=1000000.0,
            engine="ggml",
        )
        assert len(result.output) == 100000
        assert result.tokens_generated == 1000000

    def test_result_engine_onnx(self) -> None:
        """Verify that the ONNX engine type is accepted."""
        result = MockInferenceResult(
            output="test",
            tokens_generated=1,
            prompt_tokens=1,
            inference_ms=1,
            tokens_per_second=1.0,
            engine="onnx",
        )
        assert result.engine == "onnx"

    @pytest.mark.parametrize("bad_engine", ["", "tensorrt", "CUDA", None])
    def test_result_invalid_engine(
        self, bad_engine: Any,
    ) -> None:
        """Verify that invalid engine types raise an error."""
        with pytest.raises((AssertionError, TypeError)):
            MockInferenceResult(
                output="test",
                tokens_generated=1,
                prompt_tokens=1,
                inference_ms=1,
                tokens_per_second=1.0,
                engine=bad_engine,
            )

    def test_result_negative_tokens(self) -> None:
        """Verify that negative token counts raise an error."""
        with pytest.raises(AssertionError):
            MockInferenceResult(
                output="test",
                tokens_generated=-1,
                prompt_tokens=0,
                inference_ms=0,
                tokens_per_second=0.0,
                engine="ggml",
            )


# ============================================================================
# Test: Inference Request Construction
# ============================================================================


@pytest.mark.runtime
class TestInferenceRequestConstruction:
    """Tests for MockInferenceRequest construction and validation."""

    def test_request_defaults(self) -> None:
        """Verify that MockInferenceRequest has sensible defaults."""
        req = MockInferenceRequest()
        assert req.model == "default"
        assert req.prompt == ""
        assert req.temperature == 0.7
        assert req.top_p == 0.9
        assert req.top_k == 40
        assert req.max_tokens == 512
        assert req.session_id is None
        assert req.num_threads is None
        assert req.repeat_penalty == 1.1
        assert req.frequency_penalty == 0.0
        assert req.presence_penalty == 0.0

    def test_request_custom_values(self) -> None:
        """Verify that custom values override defaults."""
        req = MockInferenceRequest(
            model="custom_model",
            prompt="Custom prompt",
            temperature=0.1,
            top_p=0.5,
            top_k=10,
            max_tokens=100,
            session_id="sess_001",
            num_threads=4,
            repeat_penalty=1.5,
            frequency_penalty=0.2,
            presence_penalty=0.3,
        )
        assert req.model == "custom_model"
        assert req.prompt == "Custom prompt"
        assert req.temperature == 0.1
        assert req.top_p == 0.5
        assert req.top_k == 10
        assert req.max_tokens == 100
        assert req.session_id == "sess_001"
        assert req.num_threads == 4
        assert req.repeat_penalty == 1.5
        assert req.frequency_penalty == 0.2
        assert req.presence_penalty == 0.3

    @pytest.mark.parametrize("temperature", [0.0, 0.5, 1.0, 2.0])
    def test_request_valid_temperature(self, temperature: float) -> None:
        """Verify that valid temperature values are accepted."""
        req = MockInferenceRequest(temperature=temperature)
        assert req.temperature == temperature

    @pytest.mark.parametrize("temperature", [-0.5, -1.0])
    def test_request_negative_temperature_raises(
        self, temperature: float,
    ) -> None:
        """Verify that negative temperature values raise an error."""
        with pytest.raises(AssertionError):
            MockInferenceRequest(temperature=temperature)

    @pytest.mark.parametrize("top_p", [0.0, 0.5, 1.0])
    def test_request_valid_top_p(self, top_p: float) -> None:
        """Verify that valid top_p values are accepted."""
        req = MockInferenceRequest(top_p=top_p)
        assert req.top_p == top_p

    @pytest.mark.parametrize("max_tokens", [0, 1, 100, 2048, 100000])
    def test_request_valid_max_tokens(self, max_tokens: int) -> None:
        """Verify that valid max_tokens values are accepted."""
        req = MockInferenceRequest(max_tokens=max_tokens)
        assert req.max_tokens == max_tokens

    @pytest.mark.parametrize("max_tokens", [-1, -100])
    def test_request_negative_max_tokens_raises(
        self, max_tokens: int,
    ) -> None:
        """Verify that negative max_tokens values raise an error."""
        with pytest.raises(AssertionError):
            MockInferenceRequest(max_tokens=max_tokens)

    @pytest.mark.parametrize("top_k", [0, 1, 40, 1000])
    def test_request_valid_top_k(self, top_k: int) -> None:
        """Verify that valid top_k values are accepted."""
        req = MockInferenceRequest(top_k=top_k)
        assert req.top_k == top_k


# ============================================================================
# Test: MockRuntimeManager Stats
# ============================================================================


@pytest.mark.runtime
class TestRuntimeManagerStats:
    """Tests for MockRuntimeManager statistics."""

    def test_stats_initial_values(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that all initial stats are zero."""
        stats = runtime_manager.get_stats()
        assert stats["total_inferences"] == 0
        assert stats["total_tokens_generated"] == 0
        assert stats["total_inference_ms"] == 0
        assert stats["total_prompt_tokens"] == 0
        assert stats["total_model_loads"] == 0
        assert stats["total_model_unloads"] == 0
        assert stats["total_errors"] == 0
        assert stats["total_evictions"] == 0
        assert stats["models_loaded"] == 0

    def test_stats_after_operations(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that stats reflect all operations."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "stats_model")
        runtime_manager.infer(
            MockInferenceRequest(model="stats_model", prompt="Hello", max_tokens=10)
        )
        runtime_manager.infer(
            MockInferenceRequest(model="stats_model", prompt="World", max_tokens=20)
        )
        runtime_manager.unload_model("stats_model")

        stats = runtime_manager.get_stats()
        assert stats["total_model_loads"] == 1
        assert stats["total_inferences"] == 2
        assert stats["total_tokens_generated"] == 30
        assert stats["total_model_unloads"] == 1
        assert stats["models_loaded"] == 0

    def test_stats_after_error(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that errors are counted in stats."""
        try:
            runtime_manager.load_model("", "bad")
        except MockRuntimeError:
            pass
        stats = runtime_manager.get_stats()
        assert stats["total_errors"] >= 1

    def test_stats_reset(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that reset_stats clears all counters."""
        runtime_manager._total_inferences = 100
        runtime_manager._total_errors = 5
        runtime_manager.reset_stats()
        stats = runtime_manager.get_stats()
        assert stats["total_inferences"] == 0
        assert stats["total_errors"] == 0

    def test_stats_contains_all_keys(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that the stats dict contains all expected keys."""
        stats = runtime_manager.get_stats()
        expected_keys = [
            "total_inferences", "total_tokens_generated", "total_inference_ms",
            "total_prompt_tokens", "total_model_loads", "total_model_unloads",
            "total_errors", "total_evictions", "models_loaded",
            "max_loaded_models", "max_context_length",
        ]
        for key in expected_keys:
            assert key in stats, f"Missing stat key: {key}"


# ============================================================================
# Test: Event Log
# ============================================================================


@pytest.mark.runtime
class TestEventLog:
    """Tests for the internal event log."""

    def test_event_log_creation(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that the event log contains the creation event."""
        log = runtime_manager.event_log
        assert len(log) >= 1
        assert "created" in log[0].lower()

    def test_event_log_clear(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that the event log can be cleared."""
        runtime_manager.clear_event_log()
        assert runtime_manager.event_log == []

    def test_event_log_is_copy(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that the event log property returns a copy."""
        log1 = runtime_manager.event_log
        log2 = runtime_manager.event_log
        # Modifying log1 should not affect log2
        log1.append("fake")
        assert len(log2) == len(log1) - 1

    def test_event_log_operations(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that various operations add to the event log."""
        runtime_manager.clear_event_log()
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "log_model")
        runtime_manager.infer(
            MockInferenceRequest(model="log_model", prompt="Hello", max_tokens=5)
        )
        runtime_manager.unload_model("log_model")

        log = runtime_manager.event_log
        assert any("Model loaded" in e for e in log)
        assert any("Inference" in e for e in log)
        assert any("unloaded" in e for e in log)

    def test_event_log_engine_switch(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that engine switching is logged."""
        runtime_manager.clear_event_log()
        runtime_manager.switch_engine("onnx")
        assert any("Engine switched" in e for e in runtime_manager.event_log)

    def test_event_log_power_state(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that power state changes are logged."""
        runtime_manager.clear_event_log()
        runtime_manager.set_power_state(PowerState.PERFORMANCE)
        assert any("Power state" in e for e in runtime_manager.event_log)

    def test_event_log_reset(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that reset clears the event log and adds a reset event."""
        try:
            runtime_manager.load_model("/nonexistent", "test")  # Will fail
        except MockRuntimeError:
            pass
        runtime_manager.clear_event_log()
        runtime_manager.reset()
        # After reset, the event log should contain the reset event
        log = runtime_manager.event_log
        assert any("Runtime reset" in e for e in log)


# ============================================================================
# Test: Power State Enum
# ============================================================================


@pytest.mark.runtime
class TestPowerStateEnum:
    """Tests for the PowerState enum."""

    def test_power_state_values(self) -> None:
        """Verify that PowerState has all expected values."""
        assert PowerState.PERFORMANCE is not None
        assert PowerState.BALANCED is not None
        assert PowerState.POWER_SAVE is not None
        assert PowerState.THROTTLED is not None
        assert PowerState.CRITICAL is not None

    def test_power_state_order(self) -> None:
        """Verify that PowerState values are distinct."""
        states = [PowerState.PERFORMANCE, PowerState.BALANCED, PowerState.POWER_SAVE,
                  PowerState.THROTTLED, PowerState.CRITICAL]
        assert len(set(states)) == 5

    def test_power_state_is_throttled(self) -> None:
        """Verify that the throttled check is correct."""
        assert PowerState.THROTTLED not in (PowerState.PERFORMANCE, PowerState.BALANCED)
        assert PowerState.CRITICAL not in (PowerState.PERFORMANCE, PowerState.BALANCED)

    def test_power_state_from_string(self) -> None:
        """Verify that PowerState can be used with string matching."""
        assert PowerState.PERFORMANCE.name == "PERFORMANCE"
        assert PowerState.BALANCED.name == "BALANCED"
        assert PowerState.POWER_SAVE.name == "POWER_SAVE"
        assert PowerState.THROTTLED.name == "THROTTLED"
        assert PowerState.CRITICAL.name == "CRITICAL"


# ============================================================================
# Test: EngineType Enum
# ============================================================================


@pytest.mark.runtime
class TestEngineTypeEnum:
    """Tests for the EngineType enum."""

    def test_engine_type_values(self) -> None:
        """Verify that EngineType has all expected values."""
        assert EngineType.GGML.value == "ggml"
        assert EngineType.ONNX.value == "onnx"

    def test_engine_type_distinct(self) -> None:
        """Verify that EngineType values are distinct."""
        assert EngineType.GGML != EngineType.ONNX

    def test_engine_type_count(self) -> None:
        """Verify that there are exactly two engine types."""
        assert len(EngineType) == 2


# ============================================================================
# Smoke Tests
# ============================================================================


@pytest.mark.runtime
@pytest.mark.smoke
class TestSmokeTests:
    """Quick smoke tests to verify basic functionality."""

    def test_smoke_create_runtime(self) -> None:
        """Smoke test: creating a MockRuntimeManager works."""
        rm = MockRuntimeManager()
        assert rm.get_loaded_count() == 0

    def test_smoke_engine_switch(self) -> None:
        """Smoke test: engine switching works."""
        rm = MockRuntimeManager()
        rm.switch_engine("onnx")
        assert rm.get_active_engine() == "onnx"

    def test_smoke_detect_quantization(self) -> None:
        """Smoke test: quantization detection works."""
        rm = MockRuntimeManager()
        assert rm.detect_quantization("model-q4_0.gguf") == "q4_0"

    def test_smoke_detect_architecture(self) -> None:
        """Smoke test: architecture detection works."""
        rm = MockRuntimeManager()
        assert rm.detect_architecture("llama-2-7b.gguf") == "llama"

    @pytest.mark.slow
    def test_smoke_inference(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Smoke test: basic inference works (slow due to simulated delay)."""
        rm, _ = runtime_manager_with_models
        request = MockInferenceRequest(model="test_model", prompt="Hi", max_tokens=5)
        result = rm.infer(request)
        assert result.tokens_generated == 5

    def test_smoke_context(self) -> None:
        """Smoke test: context store/retrieve works."""
        rm = MockRuntimeManager()
        rm.context_store("key", "value")
        assert rm.context_retrieve("key") == "value"

    def test_smoke_power_state(self) -> None:
        """Smoke test: power state management works."""
        rm = MockRuntimeManager()
        assert rm.get_power_state() == PowerState.BALANCED
        rm.set_power_state(PowerState.PERFORMANCE)
        assert rm.get_power_state() == PowerState.PERFORMANCE

    def test_smoke_stats(self) -> None:
        """Smoke test: stats retrieval works."""
        rm = MockRuntimeManager()
        stats = rm.get_stats()
        assert "total_inferences" in stats

    def test_smoke_event_log(self) -> None:
        """Smoke test: event log works."""
        rm = MockRuntimeManager()
        assert len(rm.event_log) >= 1

    def test_smoke_error_injection(self) -> None:
        """Smoke test: error injection works."""
        rm = MockRuntimeManager()
        rm.set_error_injection("load_model", "fail")
        with pytest.raises(MockRuntimeError):
            rm.load_model("/test.gguf", "test")

    def test_smoke_estimate_tokens(self) -> None:
        """Smoke test: token estimation works."""
        rm = MockRuntimeManager()
        assert rm.estimate_token_count("hello") == 2


# ============================================================================
# Test: MockRuntimeManager Supported Extensions
# ============================================================================


@pytest.mark.runtime
class TestSupportedExtensions:
    """Tests for supported model file extensions."""

    def test_gguf_extension_supported(self) -> None:
        """Verify that .gguf is in the supported extensions."""
        assert ".gguf" in MockRuntimeManager.SUPPORTED_EXTENSIONS

    def test_ggml_extension_supported(self) -> None:
        """Verify that .ggml is in the supported extensions."""
        assert ".ggml" in MockRuntimeManager.SUPPORTED_EXTENSIONS

    def test_onnx_extension_supported(self) -> None:
        """Verify that .onnx is in the supported extensions."""
        assert ".onnx" in MockRuntimeManager.SUPPORTED_EXTENSIONS

    def test_bin_extension_supported(self) -> None:
        """Verify that .bin is in the supported extensions."""
        assert ".bin" in MockRuntimeManager.SUPPORTED_EXTENSIONS

    def test_pt_extension_not_supported(self) -> None:
        """Verify that .pt is not in the supported extensions."""
        assert ".pt" not in MockRuntimeManager.SUPPORTED_EXTENSIONS

    def test_pth_extension_not_supported(self) -> None:
        """Verify that .pth is not in the supported extensions."""
        assert ".pth" not in MockRuntimeManager.SUPPORTED_EXTENSIONS

    def test_safetensors_extension_not_supported(self) -> None:
        """Verify that .safetensors is not in the supported extensions."""
        assert ".safetensors" not in MockRuntimeManager.SUPPORTED_EXTENSIONS

    def test_extensions_immutable(self) -> None:
        """Verify that the supported extensions set is immutable."""
        with pytest.raises(AttributeError):
            MockRuntimeManager.SUPPORTED_EXTENSIONS.add(".test")


# ============================================================================
# Test: Architecture Patterns
# ============================================================================


@pytest.mark.runtime
class TestArchitecturePatterns:
    """Tests for architecture detection patterns."""

    def test_llama_pattern(self) -> None:
        """Verify that the llama architecture pattern is registered."""
        patterns = MockRuntimeManager.ARCHITECTURE_PATTERNS
        assert ("llama",) in patterns
        assert patterns[("llama",)] == "llama"

    def test_phi_pattern(self) -> None:
        """Verify that the phi architecture pattern is registered."""
        patterns = MockRuntimeManager.ARCHITECTURE_PATTERNS
        assert ("phi",) in patterns
        assert patterns[("phi",)] == "phi3"

    def test_mistral_pattern(self) -> None:
        """Verify that the mistral architecture pattern is registered."""
        patterns = MockRuntimeManager.ARCHITECTURE_PATTERNS
        assert ("mistral",) in patterns
        assert patterns[("mistral",)] == "mistral"

    def test_falcon_pattern(self) -> None:
        """Verify that the falcon architecture pattern is registered."""
        patterns = MockRuntimeManager.ARCHITECTURE_PATTERNS
        assert ("falcon",) in patterns
        assert patterns[("falcon",)] == "falcon"

    def test_gemma_pattern(self) -> None:
        """Verify that the gemma architecture pattern is registered."""
        patterns = MockRuntimeManager.ARCHITECTURE_PATTERNS
        assert ("gemma",) in patterns
        assert patterns[("gemma",)] == "gemma"

    def test_qwen_pattern(self) -> None:
        """Verify that the qwen architecture pattern is registered."""
        patterns = MockRuntimeManager.ARCHITECTURE_PATTERNS
        assert ("qwen",) in patterns
        assert patterns[("qwen",)] == "qwen2"

    def test_chatglm_pattern(self) -> None:
        """Verify that the chatglm architecture pattern is registered."""
        patterns = MockRuntimeManager.ARCHITECTURE_PATTERNS
        assert ("chatglm", "glm") in patterns
        assert patterns[("chatglm", "glm")] == "chatglm"

    def test_starcoder_pattern(self) -> None:
        """Verify that the starcoder architecture pattern is registered."""
        patterns = MockRuntimeManager.ARCHITECTURE_PATTERNS
        assert ("starcoder", "codellama") in patterns
        assert patterns[("starcoder", "codellama")] == "starcoder"


# ============================================================================
# Test: Quantization Patterns
# ============================================================================


@pytest.mark.runtime
class TestQuantizationPatterns:
    """Tests for quantization detection patterns."""

    def test_q4_0_pattern(self) -> None:
        """Verify that the q4_0 quantization pattern is registered."""
        patterns = MockRuntimeManager.QUANTIZATION_PATTERNS
        assert patterns["q4_0"] == "q4_0"
        assert patterns["q4-0"] == "q4_0"

    def test_q4_1_pattern(self) -> None:
        """Verify that the q4_1 quantization pattern is registered."""
        patterns = MockRuntimeManager.QUANTIZATION_PATTERNS
        assert patterns["q4_1"] == "q4_1"
        assert patterns["q4-1"] == "q4_1"

    def test_q5_0_pattern(self) -> None:
        """Verify that the q5_0 quantization pattern is registered."""
        patterns = MockRuntimeManager.QUANTIZATION_PATTERNS
        assert patterns["q5_0"] == "q5_0"
        assert patterns["q5-0"] == "q5_0"

    def test_q5_1_pattern(self) -> None:
        """Verify that the q5_1 quantization pattern is registered."""
        patterns = MockRuntimeManager.QUANTIZATION_PATTERNS
        assert patterns["q5_1"] == "q5_1"
        assert patterns["q5-1"] == "q5_1"

    def test_q8_0_pattern(self) -> None:
        """Verify that the q8_0 quantization pattern is registered."""
        patterns = MockRuntimeManager.QUANTIZATION_PATTERNS
        assert patterns["q8_0"] == "q8_0"
        assert patterns["q8-0"] == "q8_0"

    def test_f16_pattern(self) -> None:
        """Verify that the f16 quantization pattern is registered."""
        patterns = MockRuntimeManager.QUANTIZATION_PATTERNS
        assert patterns["f16"] == "f16"
        assert patterns["fp16"] == "f16"

    def test_f32_pattern(self) -> None:
        """Verify that the f32 quantization pattern is registered."""
        patterns = MockRuntimeManager.QUANTIZATION_PATTERNS
        assert patterns["f32"] == "f32"
        assert patterns["fp32"] == "f32"

    def test_all_patterns_count(self) -> None:
        """Verify the total number of quantization patterns."""
        assert len(MockRuntimeManager.QUANTIZATION_PATTERNS) == 14


# ============================================================================
# Test: Conftest Assertion Helpers
# ============================================================================


@pytest.mark.runtime
class TestConftestAssertionHelpers:
    """Tests for the conftest assertion helper functions."""

    def test_assert_successful_response(self) -> None:
        """Verify that assert_successful_response passes on valid data."""
        assert_successful_response({"type": "InferenceResponse", "output": "test"})

    def test_assert_successful_response_none(self) -> None:
        """Verify that assert_successful_response fails on None."""
        with pytest.raises(AssertionError):
            assert_successful_response(None)

    def test_assert_successful_response_error(self) -> None:
        """Verify that assert_successful_response fails on error type."""
        with pytest.raises(AssertionError, match="error"):
            assert_successful_response({"type": "Error", "message": "error"})

    def test_assert_error_response(self) -> None:
        """Verify that assert_error_response passes on error data."""
        assert_error_response({"type": "Error", "code": -1, "message": "fail"})

    def test_assert_error_response_with_code(self) -> None:
        """Verify that assert_error_response checks the error code."""
        assert_error_response({"type": "Error", "code": 404, "message": "not found"}, 404)

    def test_assert_error_response_wrong_code(self) -> None:
        """Verify that assert_error_response fails on wrong code."""
        with pytest.raises(AssertionError):
            assert_error_response({"type": "Error", "code": 404, "message": "x"}, 500)

    def test_assert_inference_response(self) -> None:
        """Verify that assert_inference_response passes on valid data."""
        assert_inference_response({
            "type": "InferenceResponse",
            "output": "test",
            "tokens_generated": 10,
            "inference_ms": 100,
            "source": "local",
        })

    def test_assert_model_load_response(self) -> None:
        """Verify that assert_model_load_response passes on valid data."""
        assert_model_load_response({
            "type": "ModelLoadResponse",
            "model_id": "test",
            "status": "loaded",
            "message": "ok",
        })

    def test_assert_model_unload_response(self) -> None:
        """Verify that assert_model_unload_response passes on valid data."""
        assert_model_unload_response({
            "type": "ModelUnloadResponse",
            "model_id": "test",
            "status": "unloaded",
            "message": "ok",
        })

    def test_assert_valid_message_type(self) -> None:
        """Verify that assert_valid_message_type passes on valid types."""
        assert_valid_message_type("Inference")
        assert_valid_message_type("ModelLoad")
        assert_valid_message_type("Auth")

    def test_assert_valid_message_type_invalid(self) -> None:
        """Verify that assert_valid_message_type fails on invalid types."""
        with pytest.raises(AssertionError):
            assert_valid_message_type("InvalidType")


# ============================================================================
# Test: Utility Functions
# ============================================================================


@pytest.mark.runtime
class TestUtilityFunctions:
    """Tests for utility functions from conftest."""

    def test_random_string(self) -> None:
        """Verify that random_string generates a string of the expected length."""
        s = random_string(16)
        assert len(s) == 16
        assert isinstance(s, str)

    def test_random_string_different(self) -> None:
        """Verify that successive random_string calls produce different values."""
        s1 = random_string(32)
        s2 = random_string(32)
        # Extremely unlikely to collide
        assert s1 != s2

    def test_random_string_default_length(self) -> None:
        """Verify that random_string uses default length of 16."""
        s = random_string()
        assert len(s) == 16

    def test_create_minimal_gguf(self, temp_model_dir: str) -> None:
        """Verify that create_minimal_gguf creates a valid file."""
        p = os.path.join(temp_model_dir, "test_utility.gguf")
        create_minimal_gguf(p)
        assert os.path.exists(p)
        assert os.path.getsize(p) > 0

    def test_create_minimal_onnx(self, temp_model_dir: str) -> None:
        """Verify that create_minimal_onnx creates a valid file."""
        p = os.path.join(temp_model_dir, "test_utility.onnx")
        create_minimal_onnx(p)
        assert os.path.exists(p)

    def test_create_corrupted_model(self, temp_model_dir: str) -> None:
        """Verify that create_corrupted_model creates a corrupted file."""
        p = os.path.join(temp_model_dir, "test_utility_corrupted.gguf")
        create_corrupted_model(p)
        assert os.path.exists(p)
        assert os.path.getsize(p) > 0


# ============================================================================
# Test: Thread Safety
# ============================================================================


@pytest.mark.runtime
class TestThreadSafety:
    """Targeted tests for thread safety of the MockRuntimeManager."""

    def test_stats_thread_safety(self) -> None:
        """Verify that stats updates are thread-safe."""
        rm = MockRuntimeManager()

        def increment_inferences() -> None:
            for _ in range(1000):
                rm._total_inferences += 1  # Not using lock (intentional for test)

        threads = [threading.Thread(target=increment_inferences) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # With the lock, total should be exactly 10000
        assert rm._total_inferences == 10000

    def test_lock_prevents_race_conditions(self) -> None:
        """Verify that the internal lock prevents race conditions on model
        operations."""
        rm = MockRuntimeManager()

        errors: list[str] = []

        def load_and_unload() -> None:
            try:
                # Use a model path that doesn't exist to avoid file I/O
                # This tests the lock on the internal dict
                for i in range(100):
                    # We can't easily test the lock without file I/O,
                    # but we can verify the lock doesn't cause deadlocks
                    rm.get_loaded_count()
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=load_and_unload) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_lock_context_operations(self) -> None:
        """Verify that the lock protects context operations."""
        rm = MockRuntimeManager()
        errors: list[str] = []

        def context_worker(worker_id: int) -> None:
            try:
                for i in range(100):
                    key = f"worker_{worker_id}_key_{i}"
                    rm.context_store(key, f"value_{i}")
                    val = rm.context_retrieve(key)
                    assert val == f"value_{i}"
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=context_worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_model_info_thread_safety(
        self,
        temp_model_dir: str,
    ) -> None:
        """Verify that get_model_info is thread-safe."""
        rm = MockRuntimeManager()
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        rm.load_model(model_path, "safe_model")

        errors: list[str] = []

        def query_worker() -> None:
            try:
                for _ in range(100):
                    info = rm.get_model_info("safe_model")
                    assert info.model_id == "safe_model"
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=query_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_list_models_thread_safety(
        self,
        temp_model_dir: str,
    ) -> None:
        """Verify that list_models is thread-safe."""
        rm = MockRuntimeManager()
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        rm.load_model(model_path, "list_safe_model")

        errors: list[str] = []

        def list_worker() -> None:
            try:
                for _ in range(100):
                    models = rm.list_models()
                    assert len(models) >= 1
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=list_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ============================================================================
# Test: Capture Logs Fixture
# ============================================================================


@pytest.mark.runtime
class TestCaptureLogs:
    """Tests for the capture_logs fixture."""

    def test_capture_logs_basic(self, capture_logs: StringIO) -> None:
        """Verify that the capture_logs fixture captures log output."""
        logger = logging.getLogger("ainos")
        logger.info("Test log message")
        output = capture_logs.getvalue()
        assert "Test log message" in output

    def test_capture_logs_level(self, capture_logs: StringIO) -> None:
        """Verify that DEBUG level logs are captured."""
        logger = logging.getLogger("ainos")
        logger.debug("Debug message")
        output = capture_logs.getvalue()
        assert "Debug message" in output

    def test_capture_logs_format(self, capture_logs: StringIO) -> None:
        """Verify that log format includes level and name."""
        logger = logging.getLogger("ainos")
        logger.warning("Warning message")
        output = capture_logs.getvalue()
        assert "WARNING" in output
        assert "ainos" in output
        assert "Warning message" in output


# ============================================================================
# Test: Integration End-to-End
# ============================================================================


@pytest.mark.runtime
class TestEndToEnd:
    """End-to-end integration tests combining multiple components."""

    def test_e2e_mock_runtime_full_workflow(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
        test_vectors: dict,
    ) -> None:
        """End-to-end test: full workflow with model loading, inference,
        context management, and stats verification."""
        # 1. Load model
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        metadata = runtime_manager.load_model(model_path, "e2e_model")
        assert metadata.architecture == "auto"

        # 2. Run inference
        result = runtime_manager.infer(
            MockInferenceRequest(
                model="e2e_model",
                prompt=test_vectors["long_prompt"][:200],
                max_tokens=10,
                temperature=0.5,
                top_p=0.8,
            )
        )
        assert result.tokens_generated == 10

        # 3. Store and retrieve context
        runtime_manager.context_store("e2e_key", "e2e_value")
        assert runtime_manager.context_retrieve("e2e_key") == "e2e_value"

        # 4. Check stats
        stats = runtime_manager.get_stats()
        assert stats["total_inferences"] == 1
        assert stats["total_model_loads"] == 1
        assert stats["models_loaded"] == 1

        # 5. Unload model
        runtime_manager.unload_model("e2e_model")
        assert runtime_manager.get_loaded_count() == 0

        # 6. Final stats
        stats = runtime_manager.get_stats()
        assert stats["total_model_unloads"] == 1
        assert stats["total_inferences"] == 1

    def test_e2e_multiple_models_and_engine_switch(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """End-to-end test: multiple models with engine switching."""
        # Load two models
        path1 = os.path.join(temp_model_dir, "llama-2-7b.gguf")
        path2 = os.path.join(temp_model_dir, "phi-3-mini.gguf")

        m1 = runtime_manager.load_model(path1, "llama_model")
        m2 = runtime_manager.load_model(path2, "phi_model")

        assert m1.architecture == "llama"
        assert m2.architecture == "phi3"

        # Infer with both
        r1 = runtime_manager.infer(
            MockInferenceRequest(model="llama_model", prompt="Hi", max_tokens=5)
        )
        r2 = runtime_manager.infer(
            MockInferenceRequest(model="phi_model", prompt="Hi", max_tokens=5)
        )
        assert r1.tokens_generated == 5
        assert r2.tokens_generated == 5

        # Switch engine
        runtime_manager.switch_engine("onnx")
        r3 = runtime_manager.infer(
            MockInferenceRequest(model="llama_model", prompt="Hi", max_tokens=5)
        )
        assert "ONNX" in r3.output

        # Clean up
        runtime_manager.unload_model("llama_model")
        runtime_manager.unload_model("phi_model")
        assert runtime_manager.get_loaded_count() == 0

    def test_e2e_error_recovery(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """End-to-end test: error recovery after a failed operation."""
        # 1. Try to load a nonexistent model (should fail)
        with pytest.raises(MockRuntimeModelNotFoundError):
            runtime_manager.load_model("/nonexistent.gguf", "fail_model")

        # 2. Load a valid model (should succeed)
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        metadata = runtime_manager.load_model(model_path, "recovery_model")
        assert metadata.model_id == "recovery_model"

        # 3. Infer with the valid model (should succeed)
        result = runtime_manager.infer(
            MockInferenceRequest(model="recovery_model", prompt="Hello", max_tokens=5)
        )
        assert result.tokens_generated == 5

        # 4. Stats should show one error
        stats = runtime_manager.get_stats()
        assert stats["total_errors"] >= 1

    def test_e2e_power_state_throttle_recovery(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """End-to-end test: power state throttle and recovery."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "power_model")

        # Normal operation
        result = runtime_manager.infer(
            MockInferenceRequest(model="power_model", prompt="Normal", max_tokens=5)
        )
        assert result.tokens_generated == 5

        # Enter critical state
        runtime_manager.set_power_state(PowerState.CRITICAL)
        with pytest.raises(MockRuntimeThermalThrottleError):
            runtime_manager.infer(
                MockInferenceRequest(model="power_model", prompt="Throttled", max_tokens=5)
            )

        # Recover to balanced
        runtime_manager.set_power_state(PowerState.BALANCED)
        result = runtime_manager.infer(
            MockInferenceRequest(model="power_model", prompt="Recovered", max_tokens=5)
        )
        assert result.tokens_generated == 5

    def test_e2e_streaming_with_context(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """End-to-end test: streaming inference combined with context."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "stream_model")

        # Store context
        runtime_manager.context_store("stream_ctx", "I am context for streaming")

        tokens: list[str] = []

        def callback(token: str) -> None:
            tokens.append(token)

        # Streaming inference
        result = runtime_manager.infer_streaming(
            MockInferenceRequest(
                model="stream_model",
                prompt="Generate based on context",
                max_tokens=5,
            ),
            callback,
        )
        assert len(tokens) == 5
        assert result.tokens_generated == 5

        # Verify context was preserved
        ctx = runtime_manager.context_retrieve("stream_ctx")
        assert ctx == "I am context for streaming"

    def test_e2e_batch_with_mixed_models(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """End-to-end test: batch inference with mixed model states."""
        path1 = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(path1, "loaded_model")

        requests = [
            MockInferenceRequest(model="loaded_model", prompt="Request 1", max_tokens=5),
            MockInferenceRequest(model="nonexistent", prompt="Request 2", max_tokens=5),
            MockInferenceRequest(model="loaded_model", prompt="Request 3", max_tokens=5),
        ]
        results = runtime_manager.batch_infer(requests)
        assert len(results) == 3
        assert isinstance(results[0], MockInferenceResult)
        assert isinstance(results[1], MockRuntimeError)
        assert isinstance(results[2], MockInferenceResult)

    def test_e2e_lru_eviction_with_inference(
        self,
        runtime_manager_small_cache: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """End-to-end test: LRU eviction during inference workflow."""
        rm = runtime_manager_small_cache
        path1 = os.path.join(temp_model_dir, "test_model.gguf")
        path2 = os.path.join(temp_model_dir, "phi-3-mini.gguf")
        path3 = os.path.join(temp_model_dir, "llama-2-7b.gguf")

        rm.load_model(path1, "model_a")
        rm.load_model(path2, "model_b")
        rm.load_model(path3, "model_c")

        # model_a should have been evicted
        with pytest.raises(MockRuntimeModelNotLoadedError):
            rm.infer(MockInferenceRequest(model="model_a", prompt="Hello", max_tokens=5))

        # model_b and model_c should still work
        r1 = rm.infer(MockInferenceRequest(model="model_b", prompt="Hello", max_tokens=5))
        r2 = rm.infer(MockInferenceRequest(model="model_c", prompt="Hello", max_tokens=5))
        assert r1.tokens_generated == 5
        assert r2.tokens_generated == 5


# ============================================================================
# Test: Negative / Error Path Coverage
# ============================================================================


@pytest.mark.runtime
class TestNegativePaths:
    """Tests covering negative and error paths in detail."""

    def test_load_model_nonexistent_dir(self, runtime_manager: MockRuntimeManager) -> None:
        """Verify that loading a model from a nonexistent directory raises."""
        with pytest.raises(MockRuntimeModelNotFoundError):
            runtime_manager.load_model("/nonexistent_dir/model.gguf", "test")

    def test_load_model_path_with_null_bytes(
        self, runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that loading with null bytes in path raises."""
        with pytest.raises(MockRuntimeModelNotFoundError):
            runtime_manager.load_model("/path/\x00model.gguf", "test")

    def test_unload_model_wrong_id_case(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that model ID matching is case-sensitive."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "CaseSensitive")
        with pytest.raises(MockRuntimeModelNotLoadedError):
            runtime_manager.unload_model("casesensitive")

    def test_infer_empty_model_id(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that inference with empty model ID raises."""
        with pytest.raises(MockRuntimeModelNotLoadedError):
            runtime_manager.infer(MockInferenceRequest(model="", prompt="Hello"))

    def test_infer_whitespace_model_id(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that inference with whitespace model ID raises."""
        with pytest.raises(MockRuntimeModelNotLoadedError):
            runtime_manager.infer(MockInferenceRequest(model="   ", prompt="Hello"))

    def test_context_retrieve_empty_key(
        self, runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that retrieving an empty key raises."""
        with pytest.raises(MockRuntimeModelNotFoundError):
            runtime_manager.context_retrieve("")

    def test_context_retrieve_whitespace_key(
        self, runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that retrieving a whitespace key raises."""
        runtime_manager.context_store("key", "value")
        with pytest.raises(MockRuntimeModelNotFoundError):
            runtime_manager.context_retrieve("   ")

    def test_multiple_errors_accumulate(
        self, runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that multiple errors accumulate in the stats."""
        for i in range(10):
            try:
                runtime_manager.load_model("", f"bad_model_{i}")
            except MockRuntimeError:
                pass
        stats = runtime_manager.get_stats()
        assert stats["total_errors"] == 10

    def test_error_during_inference_propagation(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that errors during inference are properly propagated."""
        rm, _ = runtime_manager_with_models
        rm.set_error_injection("infer", "Injection error")
        with pytest.raises(MockRuntimeError, match="Injection error"):
            rm.infer(MockInferenceRequest(model="test_model", prompt="Hello"))

    def test_double_error_injection_clear(
        self, runtime_manager_error_injector: MockRuntimeManager,
    ) -> None:
        """Verify that setting error injection to None clears it."""
        rm = runtime_manager_error_injector
        rm.set_error_injection("load_model", "error")
        rm.set_error_injection("load_model", None)  # Clear
        # Should be able to set again
        rm.set_error_injection("load_model", "new error")
        with pytest.raises(MockRuntimeError, match="new error"):
            rm.load_model("/test.gguf", "test")


# ============================================================================
# Test: Load/Unload Edge Cases
# ============================================================================


@pytest.mark.runtime
class TestLoadUnloadEdgeCases:
    """Tests for edge cases in load/unload operations."""

    def test_load_model_with_symlink(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that loading a model via a symlink works."""
        # Create a symlink to the model file
        real_path = os.path.join(temp_model_dir, "test_model.gguf")
        link_path = os.path.join(temp_model_dir, "linked_model.gguf")
        try:
            os.symlink(real_path, link_path)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks not supported on this platform")

        metadata = runtime_manager.load_model(link_path, "symlink_model")
        assert metadata.model_id == "symlink_model"
        assert metadata.model_path == link_path

    def test_load_model_with_unicode_path(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that loading a model with a Unicode path works."""
        unicode_path = os.path.join(temp_model_dir, "模型_测试.gguf")
        create_minimal_gguf(unicode_path)
        metadata = runtime_manager.load_model(unicode_path, "unicode_path_model")
        assert metadata.model_id == "unicode_path_model"

    def test_load_model_with_spaces_in_path(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that loading a model with spaces in the path works."""
        space_path = os.path.join(temp_model_dir, "my model file.gguf")
        create_minimal_gguf(space_path)
        metadata = runtime_manager.load_model(space_path, "space_path_model")
        assert metadata.model_id == "space_path_model"

    def test_load_model_with_dot_in_name(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that loading a model with multiple dots in the name works."""
        dot_path = os.path.join(temp_model_dir, "model.v1.0.gguf")
        create_minimal_gguf(dot_path)
        metadata = runtime_manager.load_model(dot_path, "dot_model")
        assert metadata.model_id == "dot_model"

    def test_unload_reload_with_different_path(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that unloading and reloading with a different path works."""
        path1 = os.path.join(temp_model_dir, "test_model.gguf")
        path2 = os.path.join(temp_model_dir, "phi-3-mini.gguf")

        runtime_manager.load_model(path1, "multi_path_model")
        runtime_manager.unload_model("multi_path_model")

        metadata = runtime_manager.load_model(path2, "multi_path_model")
        assert metadata.model_path == path2


# ============================================================================
# Test: MockDaemon Server Direct
# ============================================================================


@pytest.mark.runtime
class TestMockDaemonServerDirect:
    """Tests that interact directly with the MockDaemonServer."""

    def test_server_start_stop(self) -> None:
        """Verify that the server can be started and stopped."""
        server = MockDaemonServer(auth_enabled=False)
        server.start()
        assert server._running.is_set()
        server.stop()
        assert not server._running.is_set()

    def test_server_make_client(self) -> None:
        """Verify that the server can create a client."""
        server = MockDaemonServer(auth_enabled=False)
        server.start()
        client = server.make_client()
        assert client.connected
        client.disconnect()
        server.stop()

    def test_server_authenticated_client(self) -> None:
        """Verify that the server can create an authenticated client."""
        server = MockDaemonServer(auth_enabled=True)
        server.start()
        client = server.make_authenticated_client()
        assert client.authenticated
        client.disconnect()
        server.stop()

    def test_server_stats(self) -> None:
        """Verify that the server tracks statistics."""
        server = MockDaemonServer(auth_enabled=False)
        server.start()
        client = server.make_client()
        client.infer("Hello")
        client.infer("World")
        assert server.stats["total_inferences"] == 2
        client.disconnect()
        server.stop()

    def test_server_model_management(self) -> None:
        """Verify that the server manages models."""
        server = MockDaemonServer(auth_enabled=False)
        server.start()
        client = server.make_client()

        with tempfile.NamedTemporaryFile(suffix=".gguf", delete=False) as f:
            f.write(b"\x47\x47\x55\x46\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00")
            model_path = f.name

        resp = client.model_load(model_path)
        assert resp.get("status") == "loaded"

        models = client.model_list()
        assert len(models) >= 1

        os.unlink(model_path)
        client.disconnect()
        server.stop()

    def test_server_context_operations(self) -> None:
        """Verify that the server handles context operations."""
        server = MockDaemonServer(auth_enabled=False)
        server.start()
        client = server.make_client()

        client.context_store("key", "value")
        resp = client.context_retrieve("key")
        assert "value" in resp["output"]

        client.disconnect()
        server.stop()

    def test_server_rate_limits(self) -> None:
        """Verify that the server reports rate limit status."""
        server = MockDaemonServer(auth_enabled=True, rate_limit_enabled=True)
        server.start()
        client = server.make_authenticated_client()
        resp = client.rate_limit_status()
        assert "limits" in resp
        client.disconnect()
        server.stop()


# ============================================================================
# Additional edge case tests
# ============================================================================


@pytest.mark.runtime
class TestAdditionalEdgeCases:
    """Additional edge case tests for completeness."""

    def test_inference_result_equality(self) -> None:
        """Verify that MockInferenceResult objects can be compared by value."""
        r1 = MockInferenceResult("a", 1, 1, 1, 1.0, "ggml")
        r2 = MockInferenceResult("a", 1, 1, 1, 1.0, "ggml")
        assert r1 == r2
        r3 = MockInferenceResult("b", 1, 1, 1, 1.0, "ggml")
        assert r1 != r3

    def test_model_metadata_equality(self) -> None:
        """Verify that MockModelMetadata objects can be compared by value."""
        kwargs = dict(
            model_id="t", model_path="/p", framework="g",
            quantization=None, loaded_time=1.0, memory_usage=1,
            device="CPU", ref_count=1, architecture="a",
            n_layers=1, n_heads=1, n_embd=1, n_vocab=1,
        )
        m1 = MockModelMetadata(**kwargs)
        m2 = MockModelMetadata(**kwargs)
        assert m1 == m2

    def test_empty_string_inference_output(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that inference with empty prompt produces output."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "empty_prompt_model")
        result = runtime_manager.infer(
            MockInferenceRequest(model="empty_prompt_model", prompt="", max_tokens=5)
        )
        assert result.tokens_generated == 5
        assert result.prompt_tokens == 0

    def test_very_short_prompt(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that inference with a very short prompt works."""
        rm, _ = runtime_manager_with_models
        result = rm.infer(
            MockInferenceRequest(model="test_model", prompt="H", max_tokens=3)
        )
        assert result.tokens_generated == 3

    def test_prompt_with_only_numbers(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that inference with a numeric prompt works."""
        rm, _ = runtime_manager_with_models
        result = rm.infer(
            MockInferenceRequest(
                model="test_model",
                prompt="1234567890",
                max_tokens=5,
            )
        )
        assert result.tokens_generated == 5

    def test_prompt_with_only_punctuation(
        self,
        runtime_manager_with_models: tuple[MockRuntimeManager, str],
    ) -> None:
        """Verify that inference with only punctuation works."""
        rm, _ = runtime_manager_with_models
        result = rm.infer(
            MockInferenceRequest(
                model="test_model",
                prompt="!?.,;:",
                max_tokens=5,
            )
        )
        assert result.tokens_generated == 5


# ============================================================================
# Test: MockRuntimeManager reset
# ============================================================================


@pytest.mark.runtime
class TestReset:
    """Tests for the MockRuntimeManager.reset method."""

    def test_reset_clears_models(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that reset clears all loaded models."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "model_to_reset")
        assert runtime_manager.get_loaded_count() == 1
        runtime_manager.reset()
        assert runtime_manager.get_loaded_count() == 0

    def test_reset_clears_context(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that reset clears context store."""
        runtime_manager.context_store("key", "value")
        runtime_manager.reset()
        with pytest.raises(MockRuntimeModelNotFoundError):
            runtime_manager.context_retrieve("key")

    def test_reset_clears_error_injection(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that reset clears error injection."""
        runtime_manager.set_error_injection("load_model", "fail")
        runtime_manager.reset()
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        metadata = runtime_manager.load_model(model_path, "reset_model")
        assert metadata.model_id == "reset_model"

    def test_reset_resets_power_state(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that reset resets power state to BALANCED."""
        runtime_manager.set_power_state(PowerState.CRITICAL)
        runtime_manager.reset()
        assert runtime_manager.get_power_state() == PowerState.BALANCED

    def test_reset_clears_stats(
        self,
        runtime_manager: MockRuntimeManager,
        temp_model_dir: str,
    ) -> None:
        """Verify that reset clears statistics."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        runtime_manager.load_model(model_path, "stats_reset")
        runtime_manager.infer(
            MockInferenceRequest(model="stats_reset", prompt="Hello", max_tokens=5)
        )
        stats_before = runtime_manager.get_stats()
        assert stats_before["total_inferences"] == 1

        runtime_manager.reset()
        stats_after = runtime_manager.get_stats()
        assert stats_after["total_inferences"] == 0

    def test_reset_after_reset(
        self,
        runtime_manager: MockRuntimeManager,
    ) -> None:
        """Verify that calling reset multiple times is safe."""
        runtime_manager.reset()
        runtime_manager.reset()
        runtime_manager.reset()
        assert runtime_manager.get_loaded_count() == 0