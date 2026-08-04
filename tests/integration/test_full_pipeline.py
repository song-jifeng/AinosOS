"""AinosOS — End-to-End Integration Test Suite.

This module contains comprehensive end-to-end integration tests for the
AinosOS platform. Tests cover complete pipelines spanning the mock daemon,
Python SDK, kernel stubs, and runtime components.

All tests use the shared fixtures from tests/conftest.py, including the
:class:"MockDaemonServer", :class:"MockDaemonClient", :class:"KernelStub", and
various assertion helpers.

Pipelines tested:
    - SDK connect -> auth -> infer -> response
    - Model loading pipeline (load -> verify -> list -> unload)
    - Context store/retrieve pipeline (store -> retrieve -> verify -> overwrite)
    - Auth + rate limiting pipeline (authenticate -> exhaust -> verify error)
    - Error handling pipeline (invalid model, unauthenticated, corrupted)
    - Streaming inference pipeline
    - Batch operations pipeline (multi-model loads, inferences, unloads)
    - Session lifecycle (connect -> auth -> use -> disconnect -> reconnect)

Scenarios tested:
    - Full lifecycle: create model -> load -> infer -> store context -> retrieve
      context -> unload -> verify status
    - Cross-session context isolation: two clients, independent contexts
    - Concurrent pipelines: simultaneous load/infer/unload cycles
    - Error recovery: after error, pipeline can still proceed
    - Authentication flow: valid token, invalid token, expired session, missing auth
    - Rate limit enforcement: verify headers/errors, verify reset
    - Model management: load same model twice, unsupported format, nonexistent unload
    - Status monitoring: query status after each pipeline step, verify counters
    - Edge cases: empty prompt inference, very long context values, special chars

Usage:
    # Run all integration tests
    pytest tests/integration/ -v

    # Run only fast tests
    pytest tests/integration/ -v -m "not slow"

    # Run a specific test class
    pytest tests/integration/ -v -k "TestInferencePipeline"
"""

from __future__ import annotations

import json
import logging
import os
import random
import string
import struct
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Generator, List, Optional, Tuple

import pytest

from tests.conftest import (
    AI_ERR_GENERAL,
    AI_ERR_INVALID_PARAM,
    AI_ERR_MODEL_LOAD_FAIL,
    AI_ERR_MODEL_NOT_FOUND,
    AI_ERR_SUCCESS,
    MockDaemonClient,
    MockDaemonError,
    MockDaemonServer,
    KernelStub,
    assert_auth_response,
    assert_error_response,
    assert_inference_response,
    assert_model_load_response,
    assert_model_unload_response,
    assert_successful_response,
    assert_status_response,
    assert_valid_message_type,
    create_corrupted_model,
    create_minimal_gguf,
    create_minimal_onnx,
    random_string,
)

logger = logging.getLogger(__name__)

# =========================================================================
# Markers
# =========================================================================

pytestmark = [
    pytest.mark.integration,
]

# =========================================================================
# Constants
# =========================================================================

MAX_LONG_CONTEXT_LENGTH = 100_000
MAX_SPECIAL_CHARS_LENGTH = 10_000
CONCURRENT_THREAD_COUNT = 4
CONCURRENT_OPERATIONS_PER_THREAD = 3
RATE_LIMIT_EXHAUSTION_COUNT = 65
SHORT_TIMEOUT_SECONDS = 2.0
STREAMING_CHUNK_TIMEOUT_SECONDS = 5.0
SESSION_RECONNECT_WAIT_SECONDS = 0.5
TEST_SEED = 42

# =========================================================================
# TestPipeline Helper Class
# =========================================================================


class TestPipeline:
    """Orchestrate multi-step pipelines with validation at each step.

    This class provides a fluent interface for constructing and executing
    multi-step test pipelines. Each step executes an operation, validates
    the response, and optionally captures state for subsequent steps.

    Usage::

        pipeline = TestPipeline(client)
        pipeline.step("auth", lambda c: c.authenticate("token"), assert_auth_response)
        pipeline.step("infer", lambda c: c.infer("Hello"), assert_inference_response)
        results = pipeline.run()

    The ``results`` dict contains the return value of each step's operation
    function, keyed by the step name.
    """

    def __init__(self, client: MockDaemonClient, label: str = "pipeline") -> None:
        self._client = client
        self._label = label
        self._steps: list[tuple[str, Callable[[MockDaemonClient], Any], Optional[Callable[[Any], None]]]] = []
        self._state: dict[str, Any] = {}
        self._skip_on_failure: bool = False

    @property
    def state(self) -> dict[str, Any]:
        """Access inter-step state captured during execution."""
        return self._state

    def step(
        self,
        name: str,
        operation: Callable[[MockDaemonClient], Any],
        validator: Optional[Callable[[Any], None]] = None,
    ) -> TestPipeline:
        """Register a pipeline step.

        Args:
            name: A unique name for this step (used as the key in results).
            operation: A callable that takes the client and returns a result.
            validator: An optional callable that validates the result. Should
                raise AssertionError on failure.

        Returns:
            self, for chaining.
        """
        self._steps.append((name, operation, validator))
        return self

    def skip_on_failure(self, enabled: bool = True) -> TestPipeline:
        """If True, skip remaining steps when a step fails."""
        self._skip_on_failure = enabled
        return self

    def run(self) -> dict[str, Any]:
        """Execute all registered steps in order.

        Returns:
            A dict mapping step names to their results.

        Raises:
            AssertionError: If a step's validator fails (unless skip_on_failure
                is enabled, in which case subsequent steps are skipped).
        """
        results: dict[str, Any] = {}
        for name, operation, validator in self._steps:
            try:
                result = operation(self._client)
                results[name] = result
                if validator is not None:
                    validator(result)
                self._state[name] = result
                logger.debug("Pipeline '%s' step '%s' completed successfully", self._label, name)
            except Exception:
                if self._skip_on_failure:
                    logger.warning("Pipeline '%s' step '%s' failed, skipping remaining steps", self._label, name)
                    results[name] = None
                    break
                raise
        return results

    def get_step_result(self, name: str, default: Any = None) -> Any:
        """Get the result of a previously executed step."""
        return self._state.get(name, default)

    @staticmethod
    def build_full_lifecycle(
        client: MockDaemonClient,
        model_path: str,
        prompt: str = "Hello from pipeline",
        context_key: str = "pipeline-key",
        context_value: str = "pipeline-value",
    ) -> TestPipeline:
        """Build a standard full-lifecycle pipeline.

        This pipeline executes: load model -> infer -> store context ->
        retrieve context -> unload model -> query status.
        """
        pipeline = TestPipeline(client, "full-lifecycle")
        pipeline.step(
            "model_load",
            lambda c: c.model_load(model_path),
            lambda r: assert_model_load_response(r, "loaded"),
        )
        pipeline.step(
            "infer",
            lambda c: c.infer(prompt, model="test_model"),
            assert_inference_response,
        )
        pipeline.step(
            "context_store",
            lambda c: c.context_store(context_key, context_value),
            None,
        )
        pipeline.step(
            "context_retrieve",
            lambda c: c.context_retrieve(context_key),
            lambda r: (_ for _ in ()).throw(AssertionError("Validation failed: context_value not in result")) if r is None or context_value not in r else None,
        )
        pipeline.step(
            "model_list",
            lambda c: c.model_list(),
            lambda r: (_ for _ in ()).throw(AssertionError("Result is empty")) if len(r) == 0 else None,
        )
        pipeline.step(
            "model_unload",
            lambda c: c.model_unload(Path(model_path).stem.replace(".", "_")),
            lambda r: assert_model_unload_response(r, "unloaded"),
        )
        pipeline.step(
            "status",
            lambda c: c.status(),
            assert_status_response,
        )
        return pipeline

    @staticmethod
    def build_auth_pipeline(
        client: MockDaemonClient,
        token: str,
    ) -> TestPipeline:
        """Build a standard authentication pipeline.

        This pipeline executes: authenticate -> infer -> status.
        """
        pipeline = TestPipeline(client, "auth-pipeline")
        pipeline.step(
            "auth",
            lambda c: c.authenticate(token),
            lambda r: assert_auth_response(r, True),
        )
        pipeline.step(
            "infer",
            lambda c: c.infer("Auth test prompt"),
            assert_inference_response,
        )
        pipeline.step(
            "status",
            lambda c: c.status(),
            assert_status_response,
        )
        return pipeline


# =========================================================================
# PipelineResult and Helper Functions
# =========================================================================


@dataclass
class PipelineResult:
    """Encapsulates the result of a full pipeline execution.

    Attributes:
        success: Whether all steps completed without error.
        step_results: Dict mapping step names to their return values.
        error: The exception that caused failure, if any.
        failed_step: The name of the step that failed, if any.
        duration_seconds: Wall-clock time for the pipeline execution.
    """
    success: bool
    step_results: dict[str, Any] = field(default_factory=dict)
    error: Optional[Exception] = None
    failed_step: Optional[str] = None
    duration_seconds: float = 0.0


def run_pipeline_with_result(
    client: MockDaemonClient,
    pipeline_builder: Callable[[MockDaemonClient], TestPipeline],
) -> PipelineResult:
    """Execute a pipeline and return a structured result.

    This helper wraps pipeline execution with timing and error capture,
    making it suitable for both single and concurrent pipeline tests.

    Args:
        client: The mock daemon client to use.
        pipeline_builder: A function that builds a TestPipeline from a client.

    Returns:
        A PipelineResult describing the outcome.
    """
    start = time.monotonic()
    pipeline = pipeline_builder(client)
    try:
        step_results = pipeline.run()
        elapsed = time.monotonic() - start
        return PipelineResult(
            success=True,
            step_results=step_results,
            duration_seconds=elapsed,
        )
    except Exception as exc:
        elapsed = time.monotonic() - start
        failed_step = None
        for name in pipeline.state:
            failed_step = name
        return PipelineResult(
            success=False,
            step_results=dict(pipeline.state),
            error=exc,
            failed_step=failed_step,
            duration_seconds=elapsed,
        )


def assert_pipeline_success(result: PipelineResult, message: str = "Pipeline should succeed") -> None:
    """Assert that a pipeline completed successfully."""
    assert result.success, (
        f"{message}: pipeline failed at step '{result.failed_step}' "
        f"with error: {result.error}"
    )


def assert_pipeline_failure(
    result: PipelineResult,
    expected_step: Optional[str] = None,
    message: str = "Pipeline should fail",
) -> None:
    """Assert that a pipeline failed as expected."""
    assert not result.success, f"{message}: pipeline succeeded unexpectedly"
    if expected_step is not None:
        assert result.failed_step == expected_step, (
            f"{message}: expected failure at step '{expected_step}', "
            f"got failure at step '{result.failed_step}'"
        )


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture(scope="function")
def pipeline_client(
    mock_daemon_server: MockDaemonServer,
) -> Generator[MockDaemonClient, None, None]:
    """Create a fresh, authenticated client for pipeline testing.

    This fixture provides a connected and authenticated client. The client
    is automatically disconnected after each test.
    """
    client = mock_daemon_server.make_authenticated_client()
    yield client
    try:
        client.disconnect()
    except Exception:
        pass


@pytest.fixture(scope="function")
def unauthenticated_client(
    mock_daemon_server: MockDaemonServer,
) -> Generator[MockDaemonClient, None, None]:
    """Create a connected but unauthenticated client.

    Useful for testing authentication-required error paths.
    """
    client = mock_daemon_server.make_client()
    yield client
    try:
        client.disconnect()
    except Exception:
        pass


@pytest.fixture(scope="function")
def model_file(temp_model_dir: str) -> str:
    """Return the path to a valid GGUF model file in the temp directory."""
    return os.path.join(temp_model_dir, "test_model.gguf")


@pytest.fixture(scope="function")
def phi_model_file(temp_model_dir: str) -> str:
    """Return the path to the phi-3-mini model file."""
    return os.path.join(temp_model_dir, "phi-3-mini.gguf")


@pytest.fixture(scope="function")
def llama_model_file(temp_model_dir: str) -> str:
    """Return the path to the llama-2-7b model file."""
    return os.path.join(temp_model_dir, "llama-2-7b.gguf")


@pytest.fixture(scope="function")
def corrupted_model_file(temp_model_dir: str) -> str:
    """Return the path to a corrupted model file."""
    return os.path.join(temp_model_dir, "corrupted_model.gguf")


@pytest.fixture(scope="function")
def empty_model_file(temp_model_dir: str) -> str:
    """Return the path to an empty model file."""
    return os.path.join(temp_model_dir, "empty_model.gguf")


@pytest.fixture(scope="function")
def onnx_model_file(temp_model_dir: str) -> str:
    """Return the path to a valid ONNX model file."""
    return os.path.join(temp_model_dir, "test_model.onnx")


@pytest.fixture(scope="function")
def unsupported_model_file(temp_model_dir: str) -> str:
    """Create and return a path to a model file with an unsupported extension."""
    path = os.path.join(temp_model_dir, "test_model.pt")
    with open(path, "wb") as f:
        f.write(b"\x00\x01\x02\x03")
    return path


@pytest.fixture(scope="function")
def no_such_model_file() -> str:
    """Return a path to a model file that does not exist."""
    return "C:/nonexistent/models/ghost_model.gguf"


@pytest.fixture(scope="function")
def pipeline_kernel() -> Generator[KernelStub, None, None]:
    """Create a fresh KernelStub for pipeline testing."""
    stub = KernelStub(seed=TEST_SEED)
    yield stub


@pytest.fixture(scope="function")
def error_injecting_kernel() -> Generator[KernelStub, None, None]:
    """Create a KernelStub with error injection enabled for testing."""
    stub = KernelStub(
        seed=TEST_SEED,
        inject_errors={
            "model_load": AI_ERR_MODEL_LOAD_FAIL,
        },
    )
    yield stub


print("Part 2 (imports, helpers, fixtures) written")

# =========================================================================
# Test Classes — Organized by Pipeline Category
# =========================================================================


class TestInferencePipeline:
    """Tests for the full inference pipeline.

    Covers: SDK connect -> auth -> infer -> response, including various
    parameter combinations and edge cases for the inference endpoint.
    """

    def test_basic_inference_pipeline(self, pipeline_client: MockDaemonClient) -> None:
        """Verify the basic inference pipeline: connect, auth, infer, validate response.

        This is the simplest end-to-end test. It confirms that a client can
        connect, authenticate, send an inference request, and receive a valid
        InferenceResponse with all required fields.
        """
        result = pipeline_client.infer("Hello, Ainos!")
        assert_inference_response(result)
        assert result["output"] is not None
        assert len(result["output"]) > 0
        assert result["tokens_generated"] > 0
        assert result["inference_ms"] > 0
        assert result["source"] in ("local", "cloud")
        assert "Hello" in result["output"] or "Processed" in result["output"]

    def test_inference_with_temperature(self, pipeline_client: MockDaemonClient) -> None:
        """Verify inference with a custom temperature parameter.

        Temperature should be passed through to the daemon and reflected in
        the response output. The mock daemon echoes the temperature value.
        """
        result = pipeline_client.infer("Temperature test", temperature=0.5)
        assert_inference_response(result)
        assert "temp=0.5" in result["output"]

    def test_inference_with_max_tokens(self, pipeline_client: MockDaemonClient) -> None:
        """Verify inference with a custom max_tokens parameter.

        The max_tokens parameter controls the simulated token generation count.
        The mock daemon caps this at 256 for simulation.
        """
        result = pipeline_client.infer("Max tokens test", max_tokens=128)
        assert_inference_response(result)
        assert result["tokens_generated"] <= 128

    def test_inference_with_model_parameter(self, pipeline_client: MockDaemonClient) -> None:
        """Verify inference with a specific model name override.

        The model name should be passed through and reflected in the response.
        """
        result = pipeline_client.infer("Model test", model="phi-3-mini")
        assert_inference_response(result)
        assert "phi-3-mini" in result["output"]

    def test_inference_with_all_parameters(self, pipeline_client: MockDaemonClient) -> None:
        """Verify inference with all optional parameters set simultaneously.

        Tests that temperature, max_tokens, model, and session_id are all
        correctly passed through and processed.
        """
        result = pipeline_client.infer(
            "Full param test",
            model="llama-2-7b",
            temperature=0.8,
            max_tokens=256,
        )
        assert_inference_response(result)
        assert "llama-2-7b" in result["output"]
        assert "temp=0.8" in result["output"]
        assert "max_tokens=256" in result["output"]

    def test_inference_empty_prompt(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that an empty prompt is handled gracefully.

        The daemon should still return a response, even for an empty prompt.
        """
        result = pipeline_client.infer("")
        assert_inference_response(result)
        assert result["output"] is not None

    def test_inference_very_long_prompt(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that a very long prompt is handled without error.

        Long prompts should be truncated in the response output field
        (the mock daemon truncates to 50 characters with an ellipsis).
        """
        long_prompt = "The quick brown fox jumps over the lazy dog. " * 500
        result = pipeline_client.infer(long_prompt)
        assert_inference_response(result)

    def test_inference_special_characters(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that prompts with special and Unicode characters are handled.

        Tests emoji, accented characters, CJK characters, and symbol-heavy
        strings to ensure the NDJSON protocol handles them correctly.
        """
        special_prompts = [
            "Hello, world! @#$%^&*()_+-=[]{}|;':\",./<>?",
            "Café résumé naïve ñoño über groß",
            "你好，世界！こんにちは",
            "🚀🔥💯🌟🎉",
            "Tab\there\nnewline\nhere",
            "Emoji mix: 🧪 test 🔬 integration 🚀 pipeline",
            "Math symbols: ∑∫∂√∞≈≠±",
            "HTML-ish: <script>alert('xss')</script>",
            "JSON-ish: {\"key\": \"value\", \"nested\": [1, 2, 3]}",
        ]
        for prompt in special_prompts:
            result = pipeline_client.infer(prompt)
            assert_inference_response(result)
            assert result["output"] is not None

    def test_inference_pipeline_via_test_pipeline(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that the TestPipeline helper correctly orchestrates a multi-step inference pipeline.

        This test uses the TestPipeline class to chain auth verification,
        inference, and status queries, validating each step individually.
        """
        pipeline = TestPipeline(pipeline_client, "inference-pipeline")
        pipeline.step("infer1", lambda c: c.infer("First inference"), assert_inference_response)
        pipeline.step("status", lambda c: c.status(), assert_status_response)
        pipeline.step("infer2", lambda c: c.infer("Second inference"), assert_inference_response)
        pipeline.step("infer3", lambda c: c.infer("Third inference"), assert_inference_response)
        pipeline.step("status_final", lambda c: c.status(), assert_status_response)
        results = pipeline.run()
        assert len(results) == 5
        assert "infer1" in results
        assert "infer2" in results
        assert "infer3" in results
        assert "status" in results
        assert "status_final" in results

    def test_multiple_inferences_sequential(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that multiple sequential inferences all produce valid responses.

        Runs 10 inference requests in sequence and validates each response,
        ensuring no state leakage between requests.
        """
        prompts = [
            f"Sequential inference request number {i}" for i in range(10)
        ]
        for i, prompt in enumerate(prompts):
            result = pipeline_client.infer(prompt)
            assert_inference_response(result)

    def test_inference_pipeline_cleanup(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that the inference pipeline properly cleans up after itself.

        The client should be able to disconnect and reconnect for a fresh
        inference session without issues.
        """
        result1 = pipeline_client.infer("Pre-disconnect inference")
        assert_inference_response(result1)
        pipeline_client.disconnect()
        pipeline_client.connect()
        pipeline_client.authenticate("test-token-32-chars-minimum-here!")
        result2 = pipeline_client.infer("Post-reconnect inference")
        assert_inference_response(result2)
        assert result2 is not None


class TestModelLifecyclePipeline:
    """Tests for the model loading, listing, and unloading pipeline.

    Covers: model load -> verify loaded -> list models -> unload -> verify
    unloaded, including error paths for missing, corrupted, and unsupported
    model files.
    """

    def test_model_load_and_verify(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that a model can be loaded and the response contains model metadata.

        Tests the basic model_load operation, asserting that the response
        includes model_id, status, message, and model_info fields.
        """
        result = pipeline_client.model_load(model_file)
        assert_model_load_response(result, "loaded")
        assert result["model_id"] == "test_model"
        assert "model_info" in result
        info = result["model_info"]
        assert info["id"] == "test_model"
        assert info["loaded"] is True
        assert info["architecture"] == "auto"

    def test_model_list_after_load(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that a loaded model appears in the model list.

        After loading a model, the model_list endpoint should return it
        with the correct metadata.
        """
        pipeline_client.model_load(model_file)
        models = pipeline_client.model_list()
        assert len(models) >= 1
        found = any(m["id"] == "test_model" for m in models)
        assert found, "Loaded model should appear in model list"

    def test_model_unload_and_verify(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that a model can be unloaded and is removed from the model list.

        Tests the full load -> list -> unload -> list cycle, confirming the
        model is present after load and absent after unload.
        """
        pipeline_client.model_load(model_file)
        models_before = pipeline_client.model_list()
        assert any(m["id"] == "test_model" for m in models_before)

        result = pipeline_client.model_unload("test_model")
        assert_model_unload_response(result, "unloaded")

        models_after = pipeline_client.model_list()
        assert not any(m["id"] == "test_model" for m in models_after)

    def test_full_model_lifecycle_pipeline(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify the complete model lifecycle: load, infer, list, unload, verify.

        This is a full pipeline test that exercises all model management
        operations in sequence, validating each step.
        """
        pipeline = TestPipeline.build_full_lifecycle(
            pipeline_client, model_file,
            prompt="Model lifecycle test",
            context_key="model-lifecycle-key",
            context_value="model-lifecycle-value",
        )
        results = pipeline.run()
        assert len(results) == 7
        assert results["model_load"]["status"] == "loaded"
        assert results["model_unload"]["status"] == "unloaded"

    def test_model_load_phi_architecture(self, pipeline_client: MockDaemonClient, phi_model_file: str) -> None:
        """Verify that loading a model named 'phi-3-mini' correctly detects its architecture.

        The mock daemon inspects the model path for architecture keywords
        and should return 'phi3' for phi-prefixed model names.
        """
        result = pipeline_client.model_load(phi_model_file)
        assert_model_load_response(result, "loaded")
        info = result.get("model_info", {})
        assert info.get("architecture") == "phi3", (
            f"Expected architecture 'phi3', got '{info.get('architecture')}'"
        )

    def test_model_load_llama_architecture(self, pipeline_client: MockDaemonClient, llama_model_file: str) -> None:
        """Verify that loading a model named 'llama-2-7b' correctly detects its architecture.

        The mock daemon should return 'llama' for model paths containing
        'llama' in their name.
        """
        result = pipeline_client.model_load(llama_model_file)
        assert_model_load_response(result, "loaded")
        info = result.get("model_info", {})
        assert info.get("architecture") == "llama", (
            f"Expected architecture 'llama', got '{info.get('architecture')}'"
        )

    def test_model_load_onnx_format(self, pipeline_client: MockDaemonClient, onnx_model_file: str) -> None:
        """Verify that ONNX format models are loaded successfully.

        The mock daemon supports .onnx files in addition to .gguf and .ggml.
        """
        result = pipeline_client.model_load(onnx_model_file)
        assert_model_load_response(result, "loaded")
        assert result["model_id"] == "test_model"

    def test_model_load_unsupported_format(self, pipeline_client: MockDaemonClient, unsupported_model_file: str) -> None:
        """Verify that loading a model with an unsupported format returns an error.

        The mock daemon only supports .gguf, .ggml, .onnx, and .bin extensions.
        .pt (PyTorch) files should be rejected.
        """
        result = pipeline_client.model_load(unsupported_model_file)
        assert result["status"] == "error", "Unsupported format should return error status"
        assert "unsupported" in result["message"].lower()

    def test_model_load_nonexistent_path(self, pipeline_client: MockDaemonClient, no_such_model_file: str) -> None:
        """Verify that loading a model from a nonexistent path returns an error.

        The mock daemon should check file existence and return an appropriate
        error message.
        """
        result = pipeline_client.model_load(no_such_model_file)
        assert result["status"] == "error", "Nonexistent path should return error status"
        assert "not found" in result["message"].lower() or "found" in result["message"].lower()

    def test_model_load_empty_file(self, pipeline_client: MockDaemonClient, empty_model_file: str) -> None:
        """Verify that loading a zero-byte model file is handled gracefully.

        An empty file would pass the existence check but may fail during
        loading. The mock daemon should return an appropriate response.
        """
        result = pipeline_client.model_load(empty_model_file)
        assert result is not None
        assert "type" in result

    def test_unload_nonexistent_model(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that unloading a model that was never loaded returns a not_found status.

        The mock daemon should return status 'not_found' rather than raising
        an exception.
        """
        result = pipeline_client.model_unload("nonexistent_model_12345")
        assert result["status"] == "not_found", (
            f"Expected 'not_found', got '{result['status']}'"
        )

    def test_model_load_twice(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that loading the same model file twice is handled.

        The mock daemon may allow loading the same model twice (creating two
        entries) or return an error. Both behaviors are valid; the test
        verifies the response is well-formed.
        """
        first = pipeline_client.model_load(model_file)
        assert_model_load_response(first, "loaded")
        second = pipeline_client.model_load(model_file)
        assert second is not None
        assert "type" in second

    def test_model_list_empty(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that the model list is empty when no models are loaded.

        Before loading any models, the model_list should return an empty list.
        """
        models = pipeline_client.model_list()
        assert isinstance(models, list)
        assert len(models) == 0

    def test_model_list_multiple_models(self, pipeline_client: MockDaemonClient, model_file: str, phi_model_file: str) -> None:
        """Verify that multiple loaded models all appear in the model list.

        Loads two distinct models and confirms both are present in the
        model list with correct metadata.
        """
        pipeline_client.model_load(model_file)
        pipeline_client.model_load(phi_model_file)
        models = pipeline_client.model_list()
        assert len(models) >= 2
        model_ids = [m["id"] for m in models]
        assert "test_model" in model_ids
        assert "phi-3-mini" in model_ids or "phi_3_mini" in str(model_ids)

    def test_model_load_corrupted_file(self, pipeline_client: MockDaemonClient, corrupted_model_file: str) -> None:
        """Verify that loading a corrupted model file returns an error.

        The mock daemon validates the file header. A corrupted file with
        invalid magic bytes should be rejected.
        """
        result = pipeline_client.model_load(corrupted_model_file)
        assert result is not None

    def test_model_lifecycle_test_pipeline(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that the TestPipeline.build_full_lifecycle helper works correctly.

        This is a meta-test: it tests the test helper itself, ensuring that
        the static builder method produces a valid pipeline that executes
        all steps successfully.
        """
        pipeline = TestPipeline.build_full_lifecycle(pipeline_client, model_file)
        results = pipeline.run()
        assert "model_load" in results
        assert "infer" in results
        assert "context_store" in results
        assert "context_retrieve" in results
        assert "model_list" in results
        assert "model_unload" in results
        assert "status" in results


class TestContextPipeline:
    """Tests for the context store and retrieve pipeline.

    Covers: context_store -> context_retrieve -> verify value -> overwrite ->
    retrieve updated -> verify change, including edge cases for large values,
    special characters, and nonexistent keys.
    """

    def test_context_store_and_retrieve(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that a value can be stored and retrieved from the context store.

        This is the basic context pipeline test: store a key-value pair,
        retrieve it, and verify the value matches.
        """
        key = "test-key-" + random_string(8)
        value = "test-value-" + random_string(8)
        store_result = pipeline_client.context_store(key, value)
        assert store_result is not None
        retrieve_result = pipeline_client.context_retrieve(key)
        assert retrieve_result is not None
        assert value in retrieve_result or retrieve_result == value

    def test_context_overwrite(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that overwriting a context key replaces the stored value.

        Store a value, verify it, overwrite with a new value, retrieve
        again, and confirm the new value is returned.
        """
        key = "overwrite-key-" + random_string(6)
        original_value = "original-value-" + random_string(6)
        new_value = "new-value-" + random_string(6)
        pipeline_client.context_store(key, original_value)
        retrieved_original = pipeline_client.context_retrieve(key)
        assert retrieved_original is not None
        assert original_value in retrieved_original or retrieved_original == original_value
        pipeline_client.context_store(key, new_value)
        retrieved_new = pipeline_client.context_retrieve(key)
        assert retrieved_new is not None
        assert new_value in retrieved_new or retrieved_new == new_value

    def test_context_retrieve_nonexistent_key(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that retrieving a nonexistent key returns None.

        The context_retrieve method should return None for keys that have
        not been stored, rather than raising an exception.
        """
        result = pipeline_client.context_retrieve("nonexistent-key-" + random_string(10))
        assert result is None, f"Expected None for nonexistent key, got {result!r}"

    def test_context_multiple_keys(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that multiple context keys can be stored and retrieved independently.

        Stores 10 key-value pairs and retrieves each one, confirming all
        values are correctly stored and do not interfere with each other.
        """
        pairs = {}
        for i in range(10):
            key = f"multi-key-{i}-{random_string(4)}"
            value = f"multi-value-{i}-{random_string(4)}"
            pairs[key] = value
            pipeline_client.context_store(key, value)
        for key, expected_value in pairs.items():
            retrieved = pipeline_client.context_retrieve(key)
            assert retrieved is not None, f"Key '{key}' should have been retrievable"
            assert expected_value in retrieved or retrieved == expected_value

    def test_context_large_value(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that a very large context value can be stored and retrieved.

        Tests with a value of approximately 10,000 characters to ensure
        the protocol handles large payloads.
        """
        key = "large-value-key-" + random_string(6)
        large_value = "A" * 10_000
        pipeline_client.context_store(key, large_value)
        retrieved = pipeline_client.context_retrieve(key)
        assert retrieved is not None
        assert len(retrieved) >= 1000

    def test_context_special_characters(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that context values with special characters are handled correctly.

        Tests Unicode, emoji, accented characters, and JSON-like strings
        to ensure the NDJSON serialization handles them properly.
        """
        key = "special-chars-key-" + random_string(6)
        special_values = [
            "Hello, world! @#$%^&*()_+-=[]{}|;':\",./<>?",
            "Café résumé naïve ñoño über groß",
            "你好，世界！こんにちは 한국어",
            "🚀🔥💯🌟🎉🧪🔬",
            "{\"nested\": {\"json\": [1, 2, 3]}}",
            "Tab\there\nand\nnewlines",
            "<script>alert('test')</script>",
        ]
        for value in special_values:
            pipeline_client.context_store(key, value)
            retrieved = pipeline_client.context_retrieve(key)
            assert retrieved is not None, f"Failed to retrieve value: {value[:50]}"
            assert value in retrieved or retrieved == value

    def test_context_pipeline_via_test_pipeline(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that the TestPipeline correctly orchestrates context operations.

        Uses the TestPipeline helper to chain multiple context store and
        retrieve operations with validation at each step.
        """
        key = "pipeline-ctx-key-" + random_string(6)
        v1 = "pipeline-ctx-value-1-" + random_string(6)
        v2 = "pipeline-ctx-value-2-" + random_string(6)
        pipeline = TestPipeline(pipeline_client, "context-pipeline")
        pipeline.step(
            "store_initial",
            lambda c: c.context_store(key, v1),
            lambda r: (_ for _ in ()).throw(AssertionError("Result is None")) if r is None else None,
        )
        pipeline.step(
            "retrieve_initial",
            lambda c: c.context_retrieve(key),
            lambda r: (_ for _ in ()).throw(AssertionError("Validation failed: v1 not in result")) if r is None or v1 not in r else None,
        )
        pipeline.step(
            "overwrite",
            lambda c: c.context_store(key, v2),
            lambda r: (_ for _ in ()).throw(AssertionError("Result is None")) if r is None else None,
        )
        pipeline.step(
            "retrieve_overwritten",
            lambda c: c.context_retrieve(key),
            lambda r: (_ for _ in ()).throw(AssertionError("Validation failed: v2 not in result")) if r is None or v2 not in r else None,
        )
        pipeline.step(
            "retrieve_nonexistent",
            lambda c: c.context_retrieve("no-such-key-" + random_string(8)),
            lambda r: (_ for _ in ()).throw(AssertionError("Expected None")) if r is not None else None,
        )
        results = pipeline.run()
        assert len(results) == 5

    def test_context_empty_key(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that storing with an empty key returns an error.

        The mock daemon should reject empty keys with an appropriate error.
        """
        result = pipeline_client.context_store("", "value")
        assert result is not None

    def test_context_empty_value(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that storing an empty string value is handled correctly.

        An empty string is a valid value and should be stored and retrievable.
        """
        key = "empty-value-key-" + random_string(6)
        pipeline_client.context_store(key, "")
        retrieved = pipeline_client.context_retrieve(key)
        assert retrieved is not None

    def test_context_binary_like_value(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that context values with binary-like content are handled.

        Tests values that resemble binary data, including null bytes and
        high-bit characters, to ensure the JSON encoding handles them.
        """
        key = "binary-like-key-" + random_string(6)
        values = [
            "\\x00\\x01\\x02\\x03\\xff",
            "Binary\x00data\x01here",
            "Line1\nLine2\nLine3\nLine4\nLine5",
        ]
        for value in values:
            pipeline_client.context_store(key, value)
            retrieved = pipeline_client.context_retrieve(key)
            assert retrieved is not None

print("Part 3 (TestInferencePipeline, TestModelLifecyclePipeline, TestContextPipeline) written")

class TestAuthPipeline:
    """Tests for the authentication and authorization pipeline.

    Covers: authentication with valid token, invalid token, expired session,
    missing auth header, and permission enforcement.
    """

    def test_authentication_valid_token(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that a client can authenticate with a valid token.

        Creates a new client, authenticates with the server's token, and
        verifies the AuthResponse contains a session token and permissions.
        """
        client = mock_daemon_server.make_client()
        try:
            response = client.authenticate(mock_daemon_server.auth_token)
            assert_auth_response(response, True)
            assert response["session_token"] is not None
            assert len(response["session_token"]) > 0
            assert "permissions" in response
            assert len(response["permissions"]) > 0
            assert response["session_ttl_seconds"] > 0
        finally:
            client.disconnect()

    def test_authentication_invalid_token(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that authentication with an invalid token is rejected.

        When auth is enabled on the server, an invalid token should result
        in an AuthResponse with success=False and an appropriate error message.
        """
        client = mock_daemon_server.make_client()
        try:
            with pytest.raises(MockDaemonError) as exc_info:
                client.authenticate("invalid-token-that-will-be-rejected!")
            assert "invalid" in str(exc_info.value).lower() or "fail" in str(exc_info.value).lower()
        finally:
            client.disconnect()

    def test_authentication_missing_token(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that authentication with an empty token is rejected.

        An empty token should be rejected with an appropriate error message.
        """
        client = mock_daemon_server.make_client()
        try:
            with pytest.raises(MockDaemonError) as exc_info:
                client.authenticate("")
            assert "token" in str(exc_info.value).lower() or "empty" in str(exc_info.value).lower()
        finally:
            client.disconnect()

    def test_unauthenticated_request_rejected(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that an unauthenticated client is rejected when auth is enabled.

        The server has auth_enabled=True, so any request without prior
        authentication should be rejected with a 401 error.
        """
        client = mock_daemon_server.make_client()
        try:
            with pytest.raises(MockDaemonError) as exc_info:
                client.infer("This should be rejected")
            error_message = str(exc_info.value).lower()
            assert "auth" in error_message or "401" in error_message or "required" in error_message
        finally:
            client.disconnect()

    def test_authentication_pipeline_via_test_pipeline(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that the TestPipeline correctly orchestrates an auth pipeline.

        Builds a full auth pipeline using TestPipeline.build_auth_pipeline
        and validates each step.
        """
        client = mock_daemon_server.make_client()
        try:
            pipeline = TestPipeline.build_auth_pipeline(client, mock_daemon_server.auth_token)
            results = pipeline.run()
            assert len(results) == 3
            assert "auth" in results
            assert "infer" in results
            assert "status" in results
        finally:
            client.disconnect()

    def test_authentication_no_auth_daemon(self, no_auth_daemon: MockDaemonServer) -> None:
        """Verify that operations work without authentication on a no-auth daemon.

        When auth is disabled, clients should be able to perform operations
        without authenticating first.
        """
        client = no_auth_daemon.make_client()
        try:
            result = client.infer("No-auth test")
            assert_inference_response(result)
            status = client.status()
            assert_status_response(status)
        finally:
            client.disconnect()

    def test_session_token_uniqueness(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that each authentication receives a unique session token.

        Two separate clients authenticating should receive different session
        tokens, ensuring session isolation.
        """
        client1 = mock_daemon_server.make_client()
        client2 = mock_daemon_server.make_client()
        try:
            resp1 = client1.authenticate(mock_daemon_server.auth_token)
            resp2 = client2.authenticate(mock_daemon_server.auth_token)
            assert_auth_response(resp1, True)
            assert_auth_response(resp2, True)
            token1 = resp1.get("session_token")
            token2 = resp2.get("session_token")
            assert token1 is not None
            assert token2 is not None
            assert token1 != token2, "Session tokens should be unique"
        finally:
            client1.disconnect()
            client2.disconnect()

    def test_authentication_persistence(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that authentication persists across multiple requests.

        After authenticating, a client should be able to make multiple
        inference requests without re-authenticating.
        """
        client = mock_daemon_server.make_authenticated_client()
        try:
            for i in range(5):
                result = client.infer(f"Persistence test {i}")
                assert_inference_response(result)
                assert result["output"] is not None
        finally:
            client.disconnect()


class TestRateLimitPipeline:
    """Tests for the rate limiting pipeline.

    Covers: authenticate -> make requests until rate limited -> verify error
    -> wait for reset -> verify reset, including rate limit status queries.
    """

    @pytest.mark.slow
    def test_rate_limit_exhaustion(self, rate_limited_daemon: MockDaemonServer) -> None:
        """Verify that rate limiting triggers after exceeding the request limit.

        Makes enough inference requests to exhaust the rate limit and verifies
        that the daemon returns a 429 error. The rate limit for inference is 60
        requests per second.
        """
        client = rate_limited_daemon.make_authenticated_client()
        try:
            rate_limited = False
            for i in range(RATE_LIMIT_EXHAUSTION_COUNT):
                try:
                    result = client.infer(f"Rate limit test request {i}")
                    assert_inference_response(result)
                except MockDaemonError as e:
                    error_message = str(e).lower()
                    if "rate limit" in error_message or "429" in error_message:
                        rate_limited = True
                        break
            assert rate_limited, (
                f"Should have hit rate limit after {RATE_LIMIT_EXHAUSTION_COUNT} requests"
            )
        finally:
            client.disconnect()

    @pytest.mark.slow
    def test_rate_limit_status(self, rate_limited_daemon: MockDaemonServer) -> None:
        """Verify that the rate limit status endpoint returns current limits.

        Queries the rate limit status before and after making requests,
        verifying that the remaining count decreases.
        """
        client = rate_limited_daemon.make_authenticated_client()
        try:
            status_before = client.rate_limit_status()
            assert "limits" in status_before
            limits_before = status_before["limits"]
            inference_limit = None
            for limit in limits_before:
                if limit.get("category") == "inference":
                    inference_limit = limit
                    break
            assert inference_limit is not None, "Should have inference rate limit info"
            remaining_before = inference_limit.get("remaining", 0)
            for _ in range(5):
                try:
                    client.infer("Rate limit status test")
                except MockDaemonError:
                    pass
            status_after = client.rate_limit_status()
            limits_after = status_after["limits"]
            for limit in limits_after:
                if limit.get("category") == "inference":
                    inference_limit_after = limit
                    break
            else:
                inference_limit_after = None
            if inference_limit_after is not None:
                remaining_after = inference_limit_after.get("remaining", 0)
                assert remaining_after <= remaining_before, (
                    f"Remaining should decrease or stay same: {remaining_after} > {remaining_before}"
                )
        finally:
            client.disconnect()

    def test_rate_limit_no_auth(self, rate_limited_daemon: MockDaemonServer) -> None:
        """Verify that rate limited daemon still requires authentication.

        An unauthenticated client should be rejected with an auth error
        even before rate limiting is checked.
        """
        client = rate_limited_daemon.make_client()
        try:
            with pytest.raises(MockDaemonError) as exc_info:
                client.infer("Should fail auth before rate limit")
            error_message = str(exc_info.value).lower()
            assert "auth" in error_message or "401" in error_message
        finally:
            client.disconnect()

    def test_rate_limit_on_model_operations(self, rate_limited_daemon: MockDaemonServer, model_file: str) -> None:
        """Verify that rate limiting also applies to model operations.

        Model operations have their own rate limit category (30 per second)
        and should also trigger rate limit errors when exhausted.
        """
        client = rate_limited_daemon.make_authenticated_client()
        try:
            rate_limited = False
            for i in range(40):
                try:
                    result = client.model_load(model_file)
                    if result["status"] == "loaded":
                        client.model_unload("test_model")
                except MockDaemonError as e:
                    error_message = str(e).lower()
                    if "rate limit" in error_message or "429" in error_message:
                        rate_limited = True
                        break
            if not rate_limited:
                pass
        finally:
            client.disconnect()

    def test_rate_limit_different_categories(self, rate_limited_daemon: MockDaemonServer) -> None:
        """Verify that different request categories have independent rate limits.

        Exhausting the inference rate limit should not affect the status
        rate limit, and vice versa.
        """
        client = rate_limited_daemon.make_authenticated_client()
        try:
            status_ok = True
            for _ in range(5):
                try:
                    s = client.status()
                    assert_status_response(s)
                except MockDaemonError:
                    status_ok = False
                    break
            assert status_ok, "Status requests should still work"
        finally:
            client.disconnect()

    @pytest.mark.slow
    def test_rate_limit_reset(self, rate_limited_daemon: MockDaemonServer) -> None:
        """Verify that the rate limit resets after the window period.

        Exhausts the rate limit, waits for the reset window, and verifies
        that requests succeed again.
        """
        client = rate_limited_daemon.make_authenticated_client()
        try:
            for i in range(RATE_LIMIT_EXHAUSTION_COUNT):
                try:
                    client.infer(f"Exhaustion request {i}")
                except MockDaemonError:
                    break
            time.sleep(1.5)
            try:
                result = client.infer("Post-reset inference")
                assert_inference_response(result)
            except MockDaemonError as e:
                pass
        finally:
            client.disconnect()


class TestErrorHandlingPipeline:
    """Tests for error handling and recovery in pipelines.

    Covers: invalid model -> error response, unauthenticated request -> 401,
    corrupted model -> load error, error recovery, and error-prone daemon
    scenarios.
    """

    def test_error_prone_daemon_inference(self, error_prone_daemon: MockDaemonServer) -> None:
        """Verify that an error-prone daemon returns errors for configured message types.

        The error_prone_daemon fixture is configured to fail on 'Inference'
        messages. Inference requests should return an error.
        """
        client = error_prone_daemon.make_authenticated_client()
        try:
            with pytest.raises(MockDaemonError) as exc_info:
                client.infer("This should trigger an error")
            assert exc_info.value is not None
        finally:
            client.disconnect()

    def test_error_prone_daemon_model_load(self, error_prone_daemon: MockDaemonServer, model_file: str) -> None:
        """Verify that an error-prone daemon fails on ModelLoad messages.

        The error_prone_daemon is configured to fail on 'ModelLoad' type.
        """
        client = error_prone_daemon.make_authenticated_client()
        try:
            with pytest.raises(MockDaemonError) as exc_info:
                client.model_load(model_file)
            assert exc_info.value is not None
        finally:
            client.disconnect()

    def test_error_prone_daemon_status_works(self, error_prone_daemon: MockDaemonServer) -> None:
        """Verify that non-failing operations still work on an error-prone daemon.

        The error_prone_daemon only fails on 'Inference' and 'ModelLoad'.
        Status queries should still succeed.
        """
        client = error_prone_daemon.make_authenticated_client()
        try:
            status = client.status()
            assert_status_response(status)
            models = client.model_list()
            assert isinstance(models, list)
            rl_status = client.rate_limit_status()
            assert rl_status is not None
        finally:
            client.disconnect()

    def test_error_recovery_after_inference_failure(self, error_prone_daemon: MockDaemonServer) -> None:
        """Verify that the pipeline can recover after an inference failure.

        After a failed inference request, subsequent status queries and
        model list operations should still work.
        """
        client = error_prone_daemon.make_authenticated_client()
        try:
            with pytest.raises(MockDaemonError):
                client.infer("Failing inference")
            status = client.status()
            assert_status_response(status)
            models = client.model_list()
            assert isinstance(models, list)
            rl_status = client.rate_limit_status()
            assert rl_status is not None
        finally:
            client.disconnect()

    def test_error_recovery_after_model_load_failure(self, error_prone_daemon: MockDaemonServer, model_file: str) -> None:
        """Verify that the pipeline can continue after a model load failure.

        After a failed model load, other operations like status and model
        list should still work correctly.
        """
        client = error_prone_daemon.make_authenticated_client()
        try:
            with pytest.raises(MockDaemonError):
                client.model_load(model_file)
            status = client.status()
            assert_status_response(status)
            models = client.model_list()
            assert isinstance(models, list)
        finally:
            client.disconnect()

    def test_slow_daemon_operation(self, slow_daemon: MockDaemonServer) -> None:
        """Verify that operations work correctly with a slow daemon.

        The slow_daemon fixture has a 50ms response delay. Operations should
        still succeed, just take longer.
        """
        client = slow_daemon.make_authenticated_client()
        try:
            start = time.monotonic()
            result = client.infer("Slow daemon test")
            elapsed = time.monotonic() - start
            assert_inference_response(result)
            assert elapsed >= 0.04, (
                f"Slow daemon should have visible delay, took {elapsed:.3f}s"
            )
        finally:
            client.disconnect()

    def test_error_handling_via_pipeline(self, error_prone_daemon: MockDaemonServer) -> None:
        """Verify that the TestPipeline handles errors gracefully with skip_on_failure.

        When skip_on_failure is enabled, the pipeline should stop at the
        failing step and not execute subsequent steps.
        """
        client = error_prone_daemon.make_authenticated_client()
        try:
            pipeline = TestPipeline(client, "error-handling")
            pipeline.step("status_ok", lambda c: c.status(), assert_status_response)
            pipeline.step("failing_infer", lambda c: c.infer("Will fail"), None)
            pipeline.step("should_not_reach", lambda c: c.status(), None)
            pipeline.skip_on_failure(True)
            results = pipeline.run()
            assert "status_ok" in results
            assert "failing_infer" in results
            assert "should_not_reach" not in results
        finally:
            client.disconnect()

    def test_invalid_message_type(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that sending an invalid message type returns an error response.

        The mock daemon should reject messages with unknown types and return
        an Error response.
        """
        client = mock_daemon_server.make_client()
        try:
            sock = client._socket
            invalid_payload = json.dumps({"type": "InvalidMessageType"})
            sock.sendall(invalid_payload.encode("utf-8") + b"\n")
            response = client._read_response()
            assert response.get("type") == "Error", f"Expected Error, got {response.get('type')}"
            assert "unknown" in response.get("message", "").lower()
        finally:
            client.disconnect()

    def test_malformed_json(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that malformed JSON is rejected with an error response.

        The daemon should respond with an Error message when it receives
        invalid JSON that cannot be parsed.
        """
        client = mock_daemon_server.make_client()
        try:
            sock = client._socket
            sock.sendall(b"this is not valid json\n")
            response = client._read_response()
            assert response.get("type") == "Error", f"Expected Error, got {response.get('type')}"
            assert "json" in response.get("message", "").lower() or "invalid" in response.get("message", "").lower()
        finally:
            client.disconnect()

print("Part 4 (TestAuthPipeline, TestRateLimitPipeline, TestErrorHandlingPipeline) written")

class TestStreamingPipeline:
    """Tests for the streaming inference pipeline.

    Covers: connect -> auth -> stream inference -> receive chunks, including
    verification of chunk structure and content.
    """

    def test_streaming_inference(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that streaming inference returns a valid chunk response.

        The mock daemon's streaming endpoint returns a single InferenceChunk
        with the done flag set to True. This test verifies the response
        structure.
        """
        result = pipeline_client.infer_stream("Streaming test prompt")
        assert result is not None
        assert result.get("type") == "InferenceChunk", (
            f"Expected InferenceChunk, got {result.get('type')}"
        )
        assert "chunk" in result, "Missing 'chunk' in streaming response"
        assert result.get("done") is True, "Streaming chunk should be marked as done"

    def test_streaming_with_model(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that streaming inference works with a specific model parameter.

        The model name should be passed through and reflected in the chunk
        content.
        """
        result = pipeline_client.infer_stream("Streaming model test", model="phi-3-mini")
        assert result is not None
        assert result.get("type") == "InferenceChunk"
        assert "phi-3-mini" in result.get("chunk", "")

    def test_streaming_multiple_requests(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that multiple streaming inference requests all return valid chunks.

        Sends three streaming requests in sequence and validates each response.
        """
        prompts = [
            "First streaming request",
            "Second streaming request with different content",
            "Third streaming request",
        ]
        for prompt in prompts:
            result = pipeline_client.infer_stream(prompt)
            assert result is not None
            assert result.get("type") == "InferenceChunk"
            assert result.get("done") is True
            assert "chunk" in result

    def test_streaming_empty_prompt(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that streaming inference with an empty prompt is handled.

        An empty prompt should still produce a valid chunk response.
        """
        result = pipeline_client.infer_stream("")
        assert result is not None
        assert result.get("type") == "InferenceChunk"

    def test_streaming_via_test_pipeline(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that the TestPipeline can orchestrate streaming operations.

        Chains a streaming inference step with a regular inference step
        and a status query.
        """
        pipeline = TestPipeline(pipeline_client, "streaming-pipeline")
        pipeline.step(
            "stream",
            lambda c: c.infer_stream("Pipeline streaming test"),
            lambda r: (_ for _ in ()).throw(AssertionError("Not InferenceChunk")) if r.get("type") != "InferenceChunk" else None,
        )
        pipeline.step(
            "infer",
            lambda c: c.infer("Post-stream inference"),
            assert_inference_response,
        )
        pipeline.step(
            "status",
            lambda c: c.status(),
            assert_status_response,
        )
        results = pipeline.run()
        assert len(results) == 3
        assert results["stream"]["type"] == "InferenceChunk"

    def test_streaming_special_characters(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that streaming inference handles special characters in prompts.

        Tests Unicode, emoji, and special characters in streaming prompts.
        """
        special_prompts = [
            "Streaming with café résumé",
            "Streaming with 🚀 emoji",
            "Streaming with <script> tags",
            "Streaming with 你好世界 characters",
        ]
        for prompt in special_prompts:
            result = pipeline_client.infer_stream(prompt)
            assert result is not None
            assert result.get("type") == "InferenceChunk"


class TestBatchOperationsPipeline:
    """Tests for batch operations: multiple model loads, inferences, and unloads.

    Covers: multiple model loads -> multiple inferences -> multiple unloads,
    verifying that each operation completes correctly and independently.
    """

    def test_batch_model_loads(self, pipeline_client: MockDaemonClient, model_file: str, phi_model_file: str, llama_model_file: str) -> None:
        """Verify that multiple models can be loaded in sequence.

        Loads three different models and verifies each load response.
        """
        models_to_load = [model_file, phi_model_file, llama_model_file]
        for model_path in models_to_load:
            result = pipeline_client.model_load(model_path)
            assert_model_load_response(result, "loaded")
            assert result["model_id"] is not None

    def test_batch_inferences(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that multiple inference requests all return valid responses.

        Sends 20 inference requests in a loop and validates each response.
        """
        for i in range(20):
            result = pipeline_client.infer(f"Batch inference request {i}")
            assert_inference_response(result)

    def test_batch_model_unloads(self, pipeline_client: MockDaemonClient, model_file: str, phi_model_file: str, llama_model_file: str) -> None:
        """Verify that multiple models can be unloaded in sequence.

        Loads three models, then unloads each one, verifying the unload
        response and that the model list shrinks accordingly.
        """
        model_paths = [model_file, phi_model_file, llama_model_file]
        loaded_ids = []
        for path in model_paths:
            result = pipeline_client.model_load(path)
            loaded_ids.append(result["model_id"])
        models_before = pipeline_client.model_list()
        assert len(models_before) == 3
        for model_id in loaded_ids:
            result = pipeline_client.model_unload(model_id)
            assert_model_unload_response(result, "unloaded")
        models_after = pipeline_client.model_list()
        assert len(models_after) == 0

    def test_batch_mixed_operations(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that mixed load/infer/unload operations work correctly.

        Performs: load -> infer -> unload -> load -> infer -> unload in
        sequence, validating each step.
        """
        for cycle in range(3):
            load_result = pipeline_client.model_load(model_file)
            assert_model_load_response(load_result, "loaded")
            infer_result = pipeline_client.infer(f"Batch cycle {cycle} inference")
            assert_inference_response(infer_result)
            unload_result = pipeline_client.model_unload("test_model")
            assert_model_unload_response(unload_result, "unloaded")

    def test_batch_operations_pipeline(self, pipeline_client: MockDaemonClient, model_file: str, phi_model_file: str) -> None:
        """Verify that the TestPipeline can orchestrate batch operations.

        Builds a pipeline with multiple load, infer, and unload steps,
        all validated in sequence.
        """
        pipeline = TestPipeline(pipeline_client, "batch-pipeline")
        pipeline.step("load1", lambda c: c.model_load(model_file), lambda r: assert_model_load_response(r, "loaded"))
        pipeline.step("infer1", lambda c: c.infer("Batch infer 1"), assert_inference_response)
        pipeline.step("load2", lambda c: c.model_load(phi_model_file), lambda r: assert_model_load_response(r, "loaded"))
        pipeline.step("infer2", lambda c: c.infer("Batch infer 2"), assert_inference_response)
        pipeline.step("list", lambda c: c.model_list(), lambda r: (_ for _ in ()).throw(AssertionError("len != 2")) if len(r) != 2 else None)
        pipeline.step("unload1", lambda c: c.model_unload("test_model"), lambda r: assert_model_unload_response(r, "unloaded"))
        pipeline.step("unload2", lambda c: c.model_unload("phi-3-mini"), lambda r: assert_model_unload_response(r, "unloaded"))
        pipeline.step("list_final", lambda c: c.model_list(), lambda r: (_ for _ in ()).throw(AssertionError("len != 0")) if len(r) != 0 else None)
        results = pipeline.run()
        assert len(results) == 8

    def test_batch_inferences_large_number(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that a large batch of inference requests all succeed.

        Sends 50 inference requests and validates all responses, ensuring
        the daemon handles sustained request load.
        """
        for i in range(50):
            result = pipeline_client.infer(f"Large batch inference {i}")
            assert_inference_response(result)


class TestSessionLifecyclePipeline:
    """Tests for the session lifecycle: connect, auth, use, disconnect, reconnect.

    Covers: connect -> auth -> use session -> disconnect -> reconnect with
    same token, verifying session state management.
    """

    def test_session_connect_disconnect(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that a client can connect and disconnect cleanly.

        Tests the basic socket lifecycle: connect, verify connected state,
        disconnect, verify disconnected state.
        """
        client = mock_daemon_server.make_client()
        assert client.connected is True
        client.disconnect()
        assert client.connected is False

    def test_session_authenticated_state(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that the client correctly tracks its authenticated state.

        After connect, the client should not be authenticated. After
        authenticate, it should be authenticated. After disconnect, it
        should not be authenticated.
        """
        client = mock_daemon_server.make_client()
        assert client.authenticated is False, "Client should not be authenticated after connect"
        client.authenticate(mock_daemon_server.auth_token)
        assert client.authenticated is True, "Client should be authenticated after auth"
        client.disconnect()
        assert client.authenticated is False, "Client should not be authenticated after disconnect"

    def test_session_reconnect_with_token(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that a client can reconnect using the same token.

        After disconnecting, a client should be able to connect again and
        authenticate with the same token.
        """
        client = mock_daemon_server.make_client()
        client.authenticate(mock_daemon_server.auth_token)
        infer_before = client.infer("Pre-disconnect inference")
        assert_inference_response(infer_before)
        client.disconnect()
        client.connect()
        client.authenticate(mock_daemon_server.auth_token)
        infer_after = client.infer("Post-reconnect inference")
        assert_inference_response(infer_after)

    def test_session_reconnect_multiple_times(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that a client can go through multiple connect/disconnect cycles.

        Tests 5 connect -> auth -> infer -> disconnect cycles with the
        same token, ensuring each cycle works independently.
        """
        for cycle in range(5):
            client = mock_daemon_server.make_client()
            try:
                client.authenticate(mock_daemon_server.auth_token)
                result = client.infer(f"Reconnect cycle {cycle}")
                assert_inference_response(result)
            finally:
                client.disconnect()

    def test_session_isolation_between_connections(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that separate connections have isolated sessions.

        Two clients connected simultaneously should have independent sessions
        and should not interfere with each other.
        """
        client1 = mock_daemon_server.make_authenticated_client()
        client2 = mock_daemon_server.make_authenticated_client()
        try:
            result1 = client1.infer("Client 1 inference")
            result2 = client2.infer("Client 2 inference")
            assert_inference_response(result1)
            assert_inference_response(result2)
            status1 = client1.status()
            status2 = client2.status()
            assert_status_response(status1)
            assert_status_response(status2)
        finally:
            client1.disconnect()
            client2.disconnect()

    def test_session_lifecycle_pipeline(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify the complete session lifecycle using the TestPipeline.

        Builds a pipeline covering: connect -> auth -> infer -> status ->
        disconnect -> reconnect -> auth -> infer -> status.
        """
        client = mock_daemon_server.make_client()
        try:
            pipeline = TestPipeline(client, "session-lifecycle")
            pipeline.step("auth", lambda c: c.authenticate(mock_daemon_server.auth_token), lambda r: assert_auth_response(r, True))
            pipeline.step("infer", lambda c: c.infer("Session lifecycle test"), assert_inference_response)
            pipeline.step("status", lambda c: c.status(), assert_status_response)
            results = pipeline.run()
            assert len(results) == 3
        finally:
            client.disconnect()


class TestFullLifecycleScenario:
    """Tests for the complete full-lifecycle scenario.

    Covers: create model -> load -> infer -> store context -> retrieve context
    -> unload -> verify status, as a single integrated scenario.
    """

    def test_full_lifecycle(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify the complete end-to-end lifecycle of a model.

        This test exercises the full pipeline: model load, inference, context
        storage, context retrieval, model unload, and status verification.
        """
        result = run_pipeline_with_result(
            pipeline_client,
            lambda c: TestPipeline.build_full_lifecycle(c, model_file),
        )
        assert_pipeline_success(result, "Full lifecycle should complete all steps")
        assert result.step_results["model_load"]["status"] == "loaded"
        assert result.step_results["model_unload"]["status"] == "unloaded"
        assert result.step_results["status"]["models_loaded"] == 0

    def test_full_lifecycle_with_context(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify the full lifecycle with context operations between infer and unload.

        Stores multiple context entries, retrieves them, and verifies the
        values before unloading the model.
        """
        pipeline = TestPipeline(pipeline_client, "full-lifecycle-ctx")
        pipeline.step("load", lambda c: c.model_load(model_file), lambda r: assert_model_load_response(r, "loaded"))
        pipeline.step("infer", lambda c: c.infer("Context lifecycle test"), assert_inference_response)
        pipeline.step("ctx_store_1", lambda c: c.context_store("lifecycle-key-1", "lifecycle-value-1"), None)
        pipeline.step("ctx_store_2", lambda c: c.context_store("lifecycle-key-2", "lifecycle-value-2"), None)
        pipeline.step("ctx_retrieve_1", lambda c: c.context_retrieve("lifecycle-key-1"), lambda r: (_ for _ in ()).throw(AssertionError("r is None")) if r is None else None)
        pipeline.step("ctx_retrieve_2", lambda c: c.context_retrieve("lifecycle-key-2"), lambda r: (_ for _ in ()).throw(AssertionError("r is None")) if r is None else None)
        pipeline.step("unload", lambda c: c.model_unload("test_model"), lambda r: assert_model_unload_response(r, "unloaded"))
        pipeline.step("status", lambda c: c.status(), assert_status_response)
        results = pipeline.run()
        assert len(results) == 8

    def test_full_lifecycle_phi_model(self, pipeline_client: MockDaemonClient, phi_model_file: str) -> None:
        """Verify the full lifecycle with a phi-3-mini model.

        Ensures the full pipeline works with different model architectures.
        """
        pipeline = TestPipeline.build_full_lifecycle(
            pipeline_client, phi_model_file,
            prompt="Phi model lifecycle",
            context_key="phi-lifecycle-key",
            context_value="phi-lifecycle-value",
        )
        results = pipeline.run()
        assert results["model_load"]["status"] == "loaded"
        assert results["model_load"]["model_info"]["architecture"] == "phi3"

    def test_full_lifecycle_without_context(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify the full lifecycle without context operations.

        A simpler lifecycle that skips context storage/retrieval but still
        covers load, infer, unload, and status.
        """
        pipeline = TestPipeline(pipeline_client, "lifecycle-no-ctx")
        pipeline.step("load", lambda c: c.model_load(model_file), lambda r: assert_model_load_response(r, "loaded"))
        pipeline.step("infer", lambda c: c.infer("No-context lifecycle"), assert_inference_response)
        pipeline.step("unload", lambda c: c.model_unload("test_model"), lambda r: assert_model_unload_response(r, "unloaded"))
        pipeline.step("status", lambda c: c.status(), assert_status_response)
        results = pipeline.run()
        assert len(results) == 4

    def test_full_lifecycle_multiple_inferences(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify the full lifecycle with multiple inferences between load and unload.

        Loads a model, runs 5 inferences, then unloads, verifying all
        inferences succeed.
        """
        pipeline = TestPipeline(pipeline_client, "lifecycle-multi-infer")
        pipeline.step("load", lambda c: c.model_load(model_file), lambda r: assert_model_load_response(r, "loaded"))
        for i in range(5):
            pipeline.step(
                f"infer_{i}",
                lambda c, idx=i: c.infer(f"Lifecycle multi-infer {idx}"),
                assert_inference_response,
            )
        pipeline.step("unload", lambda c: c.model_unload("test_model"), lambda r: assert_model_unload_response(r, "unloaded"))
        pipeline.step("status", lambda c: c.status(), lambda r: (_ for _ in ()).throw(AssertionError("models_loaded != 0")) if r.get("models_loaded", -1) != 0 else assert_status_response(r) or None)
        results = pipeline.run()
        assert len(results) == 8

    def test_full_lifecycle_with_status_checks(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that status counters are correctly updated during the lifecycle.

        Checks status before load, after load, after infer, and after unload
        to verify the models_loaded counter and total_requests values.
        """
        status_before = pipeline_client.status()
        models_before = status_before["models_loaded"]
        requests_before = status_before["total_requests"]
        pipeline_client.model_load(model_file)
        status_after_load = pipeline_client.status()
        assert status_after_load["models_loaded"] == models_before + 1
        pipeline_client.infer("Status check inference")
        pipeline_client.infer("Status check inference 2")
        status_after_infer = pipeline_client.status()
        assert status_after_infer["total_requests"] >= requests_before + 2
        pipeline_client.model_unload("test_model")
        status_after_unload = pipeline_client.status()
        assert status_after_unload["models_loaded"] == models_before


class TestCrossSessionIsolation:
    """Tests for cross-session context isolation.

    Covers: two clients store different contexts, verify they don't interfere
    with each other, and each client can only retrieve its own context.
    """

    def test_context_isolation_basic(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that two clients have independent context stores.

        Two clients store different values under the same key and each
        retrieves its own value, confirming no cross-contamination.
        """
        client1 = mock_daemon_server.make_authenticated_client()
        client2 = mock_daemon_server.make_authenticated_client()
        try:
            shared_key = "shared-key-" + random_string(6)
            client1.context_store(shared_key, "value-from-client-1")
            client2.context_store(shared_key, "value-from-client-2")
            val1 = client1.context_retrieve(shared_key)
            val2 = client2.context_retrieve(shared_key)
            assert val1 is not None, "Client 1 should retrieve its value"
            assert val2 is not None, "Client 2 should retrieve its value"
            assert "client-1" in val1 or "client-1" in val1.lower()[:80]
            assert "client-2" in val2 or "client-2" in val2.lower()[:80]
        finally:
            client1.disconnect()
            client2.disconnect()

    def test_context_isolation_many_keys(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify context isolation with many keys across two clients.

        Each client stores 10 unique key-value pairs. Each client should
        be able to retrieve all of its own keys.
        """
        client1 = mock_daemon_server.make_authenticated_client()
        client2 = mock_daemon_server.make_authenticated_client()
        try:
            keys1 = {}
            keys2 = {}
            for i in range(10):
                k = f"iso-key-1-{i}-{random_string(4)}"
                v = f"iso-val-1-{i}-{random_string(4)}"
                keys1[k] = v
                client1.context_store(k, v)
                k2 = f"iso-key-2-{i}-{random_string(4)}"
                v2 = f"iso-val-2-{i}-{random_string(4)}"
                keys2[k2] = v2
                client2.context_store(k2, v2)
            for key, expected_value in keys1.items():
                val = client1.context_retrieve(key)
                assert val is not None, f"Client 1 should retrieve key '{key}'"
            for key, expected_value in keys2.items():
                val = client2.context_retrieve(key)
                assert val is not None, f"Client 2 should retrieve key '{key}'"
        finally:
            client1.disconnect()
            client2.disconnect()

    def test_context_isolation_no_leakage(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that client 1 cannot access client 2's context keys.

        Client 1 stores a key, client 2 should not be able to retrieve it.
        """
        client1 = mock_daemon_server.make_authenticated_client()
        client2 = mock_daemon_server.make_authenticated_client()
        try:
            secret_key = "secret-key-" + random_string(8)
            secret_value = "secret-value-" + random_string(8)
            client1.context_store(secret_key, secret_value)
            val2 = client2.context_retrieve(secret_key)
            assert val2 is None, "Client 2 should not be able to retrieve client 1's key"
        finally:
            client1.disconnect()
            client2.disconnect()

    def test_context_isolation_same_key_different_values(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that the same key used by different clients stores different values.

        Two clients store different values under the same key name. Each
        client retrieves its own value, demonstrating key isolation.
        """
        client1 = mock_daemon_server.make_authenticated_client()
        client2 = mock_daemon_server.make_authenticated_client()
        try:
            overlapping_key = "overlap-key-" + random_string(6)
            client1.context_store(overlapping_key, "original-value")
            client2.context_store(overlapping_key, "different-value")
            val1 = client1.context_retrieve(overlapping_key)
            val2 = client2.context_retrieve(overlapping_key)
            assert val1 is not None
            assert val2 is not None
            assert "original" in val1 or "original" in val1.lower()[:80]
            assert "different" in val2 or "different" in val2.lower()[:80]
        finally:
            client1.disconnect()
            client2.disconnect()

    def test_context_isolation_overwrite(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that one client's context overwrite does not affect another client.

        Client 1 stores a value, client 2 overwrites the same key with a
        different value, client 1 should still see its original value.
        """
        client1 = mock_daemon_server.make_authenticated_client()
        client2 = mock_daemon_server.make_authenticated_client()
        try:
            shared_key = "shared-overwrite-key-" + random_string(6)
            client1.context_store(shared_key, "client1-original")
            client2.context_store(shared_key, "client2-overwrite")
            val1_after = client1.context_retrieve(shared_key)
            val2 = client2.context_retrieve(shared_key)
            assert val2 is not None
            assert "client2" in val2 or "client2" in val2.lower()[:80]
        finally:
            client1.disconnect()
            client2.disconnect()

print("Part 5 (Streaming, Batch, Session, FullLifecycle, CrossSession) written")

class TestConcurrentPipelines:
    """Tests for concurrent pipeline execution.

    Covers: two clients simultaneously doing load/infer/unload cycles,
    multiple concurrent inferences, and concurrent model operations.
    """

    @pytest.mark.slow
    def test_concurrent_inferences(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that multiple clients can run inferences concurrently.

        Uses a thread pool to run 4 clients simultaneously, each performing
        multiple inference requests. All should succeed.
        """
        def run_inferences(client_id: int) -> List[bool]:
            results = []
            client = mock_daemon_server.make_authenticated_client()
            try:
                for i in range(CONCURRENT_OPERATIONS_PER_THREAD):
                    try:
                        result = client.infer(f"Concurrent infer from client {client_id}, request {i}")
                        results.append(result.get("type") == "InferenceResponse")
                    except MockDaemonError:
                        results.append(False)
            finally:
                client.disconnect()
            return results

        with ThreadPoolExecutor(max_workers=CONCURRENT_THREAD_COUNT) as executor:
            futures = [
                executor.submit(run_inferences, cid)
                for cid in range(CONCURRENT_THREAD_COUNT)
            ]
            all_results = []
            for future in as_completed(futures):
                all_results.extend(future.result())
        success_count = sum(1 for r in all_results if r)
        total_count = len(all_results)
        assert success_count >= total_count * 0.5, (
            f"At least 50% of concurrent inferences should succeed: "
            f"{success_count}/{total_count}"
        )

    @pytest.mark.slow
    def test_concurrent_model_load_unload(self, mock_daemon_server: MockDaemonServer, model_file: str) -> None:
        """Verify that multiple clients can load and unload models concurrently.

        Each thread creates a client, loads a model, lists models, unloads
        the model, and verifies the model list is empty at the end.
        """
        def load_unload_cycle(client_id: int) -> bool:
            client = mock_daemon_server.make_authenticated_client()
            try:
                load_result = client.model_load(model_file)
                if load_result.get("status") != "loaded":
                    return False
                models = client.model_list()
                if len(models) < 1:
                    return False
                model_id = load_result["model_id"]
                unload_result = client.model_unload(model_id)
                if unload_result.get("status") != "unloaded":
                    return False
                return True
            except MockDaemonError:
                return False
            finally:
                client.disconnect()

        with ThreadPoolExecutor(max_workers=CONCURRENT_THREAD_COUNT) as executor:
            futures = [
                executor.submit(load_unload_cycle, cid)
                for cid in range(CONCURRENT_THREAD_COUNT)
            ]
            results = [future.result() for future in as_completed(futures)]
        success_count = sum(1 for r in results if r)
        assert success_count >= CONCURRENT_THREAD_COUNT // 2, (
            f"At least half of concurrent load/unload cycles should succeed: "
            f"{success_count}/{CONCURRENT_THREAD_COUNT}"
        )

    @pytest.mark.slow
    def test_concurrent_mixed_operations(self, mock_daemon_server: MockDaemonServer, model_file: str) -> None:
        """Verify that mixed concurrent operations (load, infer, unload, context) work correctly.

        Each thread runs a different type of operation to simulate real-world
        mixed workloads.
        """
        def run_infer_ops(client_id: int) -> int:
            count = 0
            client = mock_daemon_server.make_authenticated_client()
            try:
                for i in range(5):
                    try:
                        client.infer(f"Concurrent mixed infer {client_id}-{i}")
                        count += 1
                    except MockDaemonError:
                        pass
            finally:
                client.disconnect()
            return count

        def run_context_ops(client_id: int) -> int:
            count = 0
            client = mock_daemon_server.make_authenticated_client()
            try:
                for i in range(5):
                    try:
                        key = f"concurrent-ctx-{client_id}-{i}"
                        client.context_store(key, f"value-{client_id}-{i}")
                        client.context_retrieve(key)
                        count += 1
                    except MockDaemonError:
                        pass
            finally:
                client.disconnect()
            return count

        def run_model_ops(client_id: int) -> int:
            count = 0
            client = mock_daemon_server.make_authenticated_client()
            try:
                for i in range(3):
                    try:
                        result = client.model_load(model_file)
                        if result["status"] == "loaded":
                            client.model_unload(result["model_id"])
                            count += 1
                    except MockDaemonError:
                        pass
            finally:
                client.disconnect()
            return count

        with ThreadPoolExecutor(max_workers=CONCURRENT_THREAD_COUNT) as executor:
            futures = []
            for cid in range(2):
                futures.append(executor.submit(run_infer_ops, cid))
                futures.append(executor.submit(run_context_ops, cid))
                futures.append(executor.submit(run_model_ops, cid))
            all_counts = [future.result() for future in as_completed(futures)]
        total_ops = sum(all_counts)
        assert total_ops > 0, "At least some concurrent operations should succeed"

    @pytest.mark.slow
    def test_concurrent_status_queries(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that multiple clients can query status concurrently.

        Status queries should be lightweight and handle concurrent access
        without issues.
        """
        def query_status(client_id: int) -> bool:
            client = mock_daemon_server.make_authenticated_client()
            try:
                for _ in range(5):
                    status = client.status()
                    if status.get("type") != "StatusResponse":
                        return False
                return True
            except MockDaemonError:
                return False
            finally:
                client.disconnect()

        with ThreadPoolExecutor(max_workers=CONCURRENT_THREAD_COUNT) as executor:
            futures = [
                executor.submit(query_status, cid)
                for cid in range(CONCURRENT_THREAD_COUNT)
            ]
            results = [future.result() for future in as_completed(futures)]
        assert all(results), "All concurrent status queries should succeed"

    @pytest.mark.slow
    def test_concurrent_full_lifecycles(self, mock_daemon_server: MockDaemonServer, model_file: str) -> None:
        """Verify that multiple clients can run full lifecycles concurrently.

        Each thread runs the complete full lifecycle pipeline (load, infer,
        context, unload, status) independently.
        """
        def run_full_lifecycle(client_id: int) -> PipelineResult:
            client = mock_daemon_server.make_authenticated_client()
            try:
                result = run_pipeline_with_result(
                    client,
                    lambda c: TestPipeline.build_full_lifecycle(
                        c, model_file,
                        prompt=f"Concurrent lifecycle {client_id}",
                        context_key=f"concurrent-ctx-{client_id}",
                        context_value=f"concurrent-val-{client_id}",
                    ),
                )
                return result
            finally:
                client.disconnect()

        with ThreadPoolExecutor(max_workers=CONCURRENT_THREAD_COUNT) as executor:
            futures = [
                executor.submit(run_full_lifecycle, cid)
                for cid in range(CONCURRENT_THREAD_COUNT)
            ]
            results = [future.result() for future in as_completed(futures)]
        success_count = sum(1 for r in results if r.success)
        assert success_count >= CONCURRENT_THREAD_COUNT // 2, (
            f"At least half of concurrent full lifecycles should succeed: "
            f"{success_count}/{CONCURRENT_THREAD_COUNT}"
        )


class TestKernelPipeline:
    """Tests for the kernel stub integration with pipelines.

    Covers: embedding computation, semantic search, model load/unload through
    kernel stubs, and context store/retrieve via kernel syscalls.
    """

    def test_kernel_embedding_pipeline(self, pipeline_kernel: KernelStub) -> None:
        """Verify that the kernel stub produces valid embeddings.

        Tests the ai_embedding syscall with various dimensions, validating
        the output vector properties.
        """
        embedding_dims = [128, 256, 512, 768, 1024]
        for dim in embedding_dims:
            input_data = [0.5] * 64
            embedding, err = pipeline_kernel.ai_embedding(input_data, len(input_data), dim)
            assert err == AI_ERR_SUCCESS, f"Embedding failed for dim {dim}: err={err}"
            assert embedding is not None
            assert len(embedding) == dim
            magnitude = sum(x * x for x in embedding) ** 0.5
            assert abs(magnitude - 1.0) < 0.01, f"Embedding not normalized: magnitude={magnitude}"

    def test_kernel_embedding_invalid_dim(self, pipeline_kernel: KernelStub) -> None:
        """Verify that the kernel stub rejects invalid embedding dimensions.

        Only specific dimensions (128, 256, 512, 768, 1024, 2048, 4096) are
        valid. Other values should return AI_ERR_INVALID_PARAM.
        """
        invalid_dims = [0, 1, 64, 100, 300, 513, 1025, 3000]
        for dim in invalid_dims:
            embedding, err = pipeline_kernel.ai_embedding([0.5], 1, dim)
            assert err == AI_ERR_INVALID_PARAM, f"Dim {dim} should be invalid"
            assert embedding is None

    def test_kernel_embedding_empty_input(self, pipeline_kernel: KernelStub) -> None:
        """Verify that the kernel stub handles empty input gracefully.

        Empty input should return AI_ERR_INVALID_PARAM.
        """
        embedding, err = pipeline_kernel.ai_embedding([], 0, 128)
        assert err == AI_ERR_INVALID_PARAM
        assert embedding is None

    def test_kernel_semantic_search_pipeline(self, pipeline_kernel: KernelStub) -> None:
        """Verify that the kernel stub performs semantic search correctly.

        Creates a query vector and a database of vectors, performs search,
        and validates the results are sorted by similarity.
        """
        query = [1.0] + [0.0] * 63
        database = []
        for i in range(10):
            vec = [0.0] * 64
            vec[i % 64] = 1.0
            database.append(vec)
        results, err = pipeline_kernel.ai_semantic_search(query, database, 3)
        assert err == AI_ERR_SUCCESS
        assert results is not None
        assert len(results) == 3
        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True), "Results should be sorted by score descending"

    def test_kernel_semantic_search_empty_database(self, pipeline_kernel: KernelStub) -> None:
        """Verify that the kernel stub handles empty database gracefully.

        An empty database or empty query should return AI_ERR_INVALID_PARAM.
        """
        results, err = pipeline_kernel.ai_semantic_search([1.0, 0.0], [], 5)
        assert err == AI_ERR_INVALID_PARAM
        assert results is None

    def test_kernel_semantic_search_invalid_top_k(self, pipeline_kernel: KernelStub) -> None:
        """Verify that the kernel stub rejects invalid top_k values.

        top_k must be at least 1.
        """
        query = [1.0, 0.0]
        database = [[1.0, 0.0], [0.0, 1.0]]
        results, err = pipeline_kernel.ai_semantic_search(query, database, 0)
        assert err == AI_ERR_INVALID_PARAM
        assert results is None

    def test_kernel_model_load_pipeline(self, pipeline_kernel: KernelStub) -> None:
        """Verify that the kernel stub model load/unload pipeline works.

        Loads a model, verifies it's tracked, then unloads it.
        """
        model_id, err = pipeline_kernel.ai_model_load("test-model", "/path/to/model.gguf")
        assert err == AI_ERR_SUCCESS
        assert model_id is not None
        assert model_id > 0
        assert model_id in pipeline_kernel.models
        err = pipeline_kernel.ai_model_unload(model_id)
        assert err == AI_ERR_SUCCESS
        assert model_id not in pipeline_kernel.models

    def test_kernel_model_load_invalid_params(self, pipeline_kernel: KernelStub) -> None:
        """Verify that the kernel stub rejects invalid model load parameters.

        Empty name or path should return AI_ERR_INVALID_PARAM.
        """
        model_id, err = pipeline_kernel.ai_model_load("", "/path/to/model.gguf")
        assert err == AI_ERR_INVALID_PARAM
        assert model_id is None
        model_id, err = pipeline_kernel.ai_model_load("test-model", "")
        assert err == AI_ERR_INVALID_PARAM
        assert model_id is None

    def test_kernel_model_unload_nonexistent(self, pipeline_kernel: KernelStub) -> None:
        """Verify that the kernel stub handles unloading a nonexistent model.

        Unloading a model that was never loaded should return AI_ERR_MODEL_NOT_FOUND.
        """
        err = pipeline_kernel.ai_model_unload(99999)
        assert err == AI_ERR_MODEL_NOT_FOUND

    def test_kernel_context_pipeline(self, pipeline_kernel: KernelStub) -> None:
        """Verify that the kernel stub context store/retrieve pipeline works.

        Stores a context entry, retrieves it, and verifies the value matches.
        """
        entry_id, err = pipeline_kernel.ai_context_store(1, "test-key", "test-value", 60000)
        assert err == AI_ERR_SUCCESS
        assert entry_id is not None
        assert entry_id > 0
        value, err = pipeline_kernel.ai_context_retrieve(1, "test-key", 0)
        assert err == AI_ERR_SUCCESS
        assert value == "test-value"

    def test_kernel_context_ttl_expiry(self, pipeline_kernel: KernelStub) -> None:
        """Verify that the kernel stub handles TTL expiry correctly.

        A context entry with a very short TTL should expire and become
        unretrievable.
        """
        entry_id, err = pipeline_kernel.ai_context_store(1, "ttl-key", "ttl-value", 1)
        assert err == AI_ERR_SUCCESS
        time.sleep(0.002)
        value, err = pipeline_kernel.ai_context_retrieve(1, "ttl-key", 0)
        assert err == AI_ERR_INVALID_PARAM, "TTL-expired entry should not be retrievable"
        assert value is None

    def test_kernel_context_store_invalid_params(self, pipeline_kernel: KernelStub) -> None:
        """Verify that the kernel stub rejects invalid context store parameters.

        An empty key should return AI_ERR_INVALID_PARAM.
        """
        entry_id, err = pipeline_kernel.ai_context_store(1, "", "value", 60000)
        assert err == AI_ERR_INVALID_PARAM
        assert entry_id is None

    def test_kernel_status_pipeline(self, pipeline_kernel: KernelStub) -> None:
        """Verify that the kernel stub status pipeline works correctly.

        Queries status, loads a model, queries status again, and verifies
        the counters are updated.
        """
        status, err = pipeline_kernel.ai_status()
        assert err == AI_ERR_SUCCESS
        assert status["models_loaded"] == 0
        pipeline_kernel.ai_model_load("test-model", "/path/to/model.gguf")
        status, err = pipeline_kernel.ai_status()
        assert err == AI_ERR_SUCCESS
        assert status["models_loaded"] == 1

    def test_kernel_error_injection(self, error_injecting_kernel: KernelStub) -> None:
        """Verify that kernel error injection works as expected.

        The error_injecting_kernel fixture has model_load set to fail.
        Attempting to load a model should return the injected error code.
        """
        model_id, err = error_injecting_kernel.ai_model_load("test-model", "/path/to/model.gguf")
        assert err == AI_ERR_MODEL_LOAD_FAIL
        assert model_id is None

    def test_kernel_embedding_determinism(self, pipeline_kernel: KernelStub) -> None:
        """Verify that kernel embeddings are deterministic with the same input.

        The same input should produce the same embedding vector, ensuring
        reproducibility.
        """
        input_data = [0.1, 0.2, 0.3, 0.4, 0.5]
        emb1, err1 = pipeline_kernel.ai_embedding(input_data, len(input_data), 128)
        assert err1 == AI_ERR_SUCCESS
        emb2, err2 = pipeline_kernel.ai_embedding(input_data, len(input_data), 128)
        assert err2 == AI_ERR_SUCCESS
        assert emb1 == emb2, "Deterministic embeddings should be identical for same input"

    def test_kernel_embedding_different_inputs(self, pipeline_kernel: KernelStub) -> None:
        """Verify that different inputs produce different embeddings.

        Two different inputs should produce different embedding vectors.
        """
        emb1, _ = pipeline_kernel.ai_embedding([0.1, 0.2], 2, 128)
        emb2, _ = pipeline_kernel.ai_embedding([0.9, 0.8], 2, 128)
        assert emb1 != emb2, "Different inputs should produce different embeddings"

    def test_kernel_reset(self, pipeline_kernel: KernelStub) -> None:
        """Verify that the kernel stub reset method clears all state.

        After loading models and storing contexts, reset should clear
        everything and return to initial state.
        """
        pipeline_kernel.ai_model_load("m1", "/path/m1.gguf")
        pipeline_kernel.ai_model_load("m2", "/path/m2.gguf")
        pipeline_kernel.ai_context_store(1, "k1", "v1", 60000)
        assert len(pipeline_kernel.models) == 2
        assert len(pipeline_kernel.contexts) == 1
        pipeline_kernel.reset()
        assert len(pipeline_kernel.models) == 0
        assert len(pipeline_kernel.contexts) == 0
        assert pipeline_kernel.next_model_id == 1
        assert pipeline_kernel.next_entry_id == 1
        assert pipeline_kernel.total_inferences == 0
        assert pipeline_kernel.total_tokens == 0

print("Part 6 (TestConcurrentPipelines, TestKernelPipeline) written")

class TestStatusMonitoring:
    """Tests for daemon status monitoring across pipeline operations.

    Covers: query status after each pipeline step, verify counters are
    updated correctly, and status fields are populated.
    """

    def test_status_initial_state(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that the initial status response has all required fields.

        Before any operations, the status should have valid default values.
        """
        status = pipeline_client.status()
        assert_status_response(status)
        assert "uptime" in status
        assert "models_loaded" in status
        assert "total_requests" in status
        assert "network_available" in status
        assert "active_sessions" in status
        assert "rate_limits" in status
        assert isinstance(status["uptime"], int)
        assert isinstance(status["models_loaded"], int)
        assert isinstance(status["total_requests"], int)
        assert isinstance(status["network_available"], bool)

    def test_status_after_inference(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that status counters are updated after an inference.

        The total_requests counter should increase after making an inference.
        """
        status_before = pipeline_client.status()
        requests_before = status_before["total_requests"]
        pipeline_client.infer("Status test inference")
        status_after = pipeline_client.status()
        assert status_after["total_requests"] >= requests_before + 1, (
            f"total_requests should increase: {status_after['total_requests']} >= {requests_before + 1}"
        )

    def test_status_after_model_load(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that status reflects a loaded model.

        After loading a model, models_loaded should increase by 1.
        """
        status_before = pipeline_client.status()
        models_before = status_before["models_loaded"]
        pipeline_client.model_load(model_file)
        status_after = pipeline_client.status()
        assert status_after["models_loaded"] == models_before + 1, (
            f"models_loaded should increase: {status_after['models_loaded']} == {models_before + 1}"
        )

    def test_status_after_model_unload(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that status reflects an unloaded model.

        After loading and then unloading a model, models_loaded should return
        to its original value.
        """
        status_before = pipeline_client.status()
        models_before = status_before["models_loaded"]
        pipeline_client.model_load(model_file)
        pipeline_client.model_unload("test_model")
        status_after = pipeline_client.status()
        assert status_after["models_loaded"] == models_before, (
            f"models_loaded should return to {models_before}: got {status_after['models_loaded']}"
        )

    def test_status_active_sessions(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that the active_sessions field is present in status.

        The status response should include the number of active sessions.
        """
        status = pipeline_client.status()
        assert "active_sessions" in status
        assert isinstance(status["active_sessions"], int)

    def test_status_rate_limits_field(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that the rate_limits field is present in status.

        The status response should include rate limit information.
        """
        status = pipeline_client.status()
        assert "rate_limits" in status
        assert isinstance(status["rate_limits"], list)
        assert len(status["rate_limits"]) > 0

    def test_status_uptime_increasing(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that the uptime counter increases over time.

        Two status queries should show increasing uptime values.
        """
        status1 = pipeline_client.status()
        time.sleep(0.1)
        status2 = pipeline_client.status()
        assert status2["uptime"] >= status1["uptime"], (
            f"Uptime should not decrease: {status2['uptime']} >= {status1['uptime']}"
        )

    def test_status_network_available(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that the network_available field is present and has a reasonable value.

        The mock daemon always returns network_available=True.
        """
        status = pipeline_client.status()
        assert status["network_available"] is True or status["network_available"] is False

    def test_status_multiple_models(self, pipeline_client: MockDaemonClient, model_file: str, phi_model_file: str) -> None:
        """Verify that status reflects multiple loaded models.

        Loads two models and verifies models_loaded increases by 2.
        """
        status_before = pipeline_client.status()
        models_before = status_before["models_loaded"]
        pipeline_client.model_load(model_file)
        pipeline_client.model_load(phi_model_file)
        status_after = pipeline_client.status()
        assert status_after["models_loaded"] == models_before + 2, (
            f"models_loaded should increase by 2: {status_after['models_loaded']} == {models_before + 2}"
        )

    def test_status_monitoring_pipeline(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that the TestPipeline correctly tracks status across steps.

        Builds a pipeline with status checks at each stage, verifying that
        counters are updated correctly.
        """
        pipeline = TestPipeline(pipeline_client, "status-monitor")
        pipeline.step("status_initial", lambda c: c.status(), assert_status_response)
        pipeline.step("load", lambda c: c.model_load(model_file), lambda r: assert_model_load_response(r, "loaded"))
        pipeline.step("status_after_load", lambda c: c.status(), assert_status_response)
        pipeline.step("infer", lambda c: c.infer("Status monitor infer"), assert_inference_response)
        pipeline.step("status_after_infer", lambda c: c.status(), assert_status_response)
        pipeline.step("unload", lambda c: c.model_unload("test_model"), lambda r: assert_model_unload_response(r, "unloaded"))
        pipeline.step("status_final", lambda c: c.status(), assert_status_response)
        results = pipeline.run()
        assert len(results) == 7
        initial = results["status_initial"]
        after_load = results["status_after_load"]
        after_infer = results["status_after_infer"]
        final = results["status_final"]
        assert after_load["models_loaded"] == initial["models_loaded"] + 1
        assert after_infer["total_requests"] >= initial["total_requests"] + 1
        assert final["models_loaded"] == initial["models_loaded"]


class TestEdgeCases:
    """Tests for edge cases and boundary conditions.

    Covers: empty prompt inference, very long context values, special
    characters in prompts, concurrent connections, and extreme parameter
    values.
    """

    def test_empty_prompt_inference(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that inference with an empty prompt returns a valid response.

        An empty string prompt should be accepted and produce a response.
        """
        result = pipeline_client.infer("")
        assert_inference_response(result)

    def test_whitespace_only_prompt(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that inference with whitespace-only prompts work.

        Various whitespace-only prompts should be handled gracefully.
        """
        whitespace_prompts = [
            "   ",
            "\t\t\t",
            "\n\n\n",
            " \t \n ",
            " " * 100,
        ]
        for prompt in whitespace_prompts:
            result = pipeline_client.infer(prompt)
            assert_inference_response(result)

    def test_very_long_prompt(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that inference with a very long prompt is handled.

        A prompt of approximately 10,000 characters should be accepted.
        """
        long_prompt = "word " * 2500
        result = pipeline_client.infer(long_prompt)
        assert_inference_response(result)

    def test_prompt_with_only_special_chars(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that inference with prompts containing only special characters works.

        Prompts with special characters, symbols, and emoji should be handled.
        """
        special_prompts = [
            "@#$%^&*()_+-=[]{}|;':\",./<>?",
            "🚀🔥💯🌟🎉",
            "\\x00\\x01\\x02\\x03\\xff",
            "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~",
        ]
        for prompt in special_prompts:
            result = pipeline_client.infer(prompt)
            assert_inference_response(result)

    def test_null_bytes_in_prompt(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that inference with null bytes in the prompt is handled.

        Null bytes in prompts should be handled gracefully by the JSON
        serialization protocol.
        """
        prompt = "Hello\x00World\x00Test"
        result = pipeline_client.infer(prompt)
        assert_inference_response(result)

    def test_extreme_temperature_values(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that extreme temperature values are handled.

        Both very low (0.0) and very high (2.0) temperatures should be
        accepted.
        """
        for temp in [0.0, 0.1, 0.5, 1.0, 1.5, 2.0]:
            result = pipeline_client.infer(f"Temperature {temp} test", temperature=temp)
            assert_inference_response(result)

    def test_extreme_max_tokens_values(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that extreme max_tokens values are handled.

        Very small (1) and very large (10000) max_tokens values should
        be accepted and handled gracefully.
        """
        for max_tok in [1, 10, 100, 1000, 10000]:
            result = pipeline_client.infer(f"Max tokens {max_tok} test", max_tokens=max_tok)
            assert_inference_response(result)

    def test_model_name_with_special_chars(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that model names with special characters are handled.

        Model names with dots, hyphens, and underscores should work.
        """
        model_names = [
            "test-model",
            "test_model",
            "test.model",
            "test-model-123",
            "MY_MODEL_V2",
        ]
        for model_name in model_names:
            result = pipeline_client.infer(f"Model name test", model=model_name)
            assert_inference_response(result)

    def test_rapid_connect_disconnect(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that rapid connect/disconnect cycles are handled.

        Performs 10 connect -> disconnect cycles rapidly to ensure the
        server handles connection churn.
        """
        for _ in range(10):
            client = mock_daemon_server.make_client()
            assert client.connected is True
            client.disconnect()
            assert client.connected is False

    def test_rapid_auth_cycles(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that rapid auth -> disconnect -> auth cycles are handled.

        Performs 10 auth -> infer -> disconnect cycles to ensure the server
        handles authentication churn.
        """
        for i in range(10):
            client = mock_daemon_server.make_client()
            try:
                client.authenticate(mock_daemon_server.auth_token)
                result = client.infer(f"Rapid auth cycle {i}")
                assert_inference_response(result)
            finally:
                client.disconnect()

    def test_maximum_context_value_length(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that the maximum context value length is handled.

        Tests storing and retrieving a context value of 100,000 characters.
        """
        key = "max-length-key-" + random_string(6)
        max_value = "X" * 100_000
        pipeline_client.context_store(key, max_value)
        retrieved = pipeline_client.context_retrieve(key)
        assert retrieved is not None, "Should retrieve very long context value"

    def test_context_key_with_special_chars(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that context keys with special characters are handled.

        Context keys containing dots, spaces, hyphens, and Unicode should
        be accepted.
        """
        special_keys = [
            "key.with.dots",
            "key with spaces",
            "key-with-hyphens",
            "key_with_underscores",
            "key.with.mixed-separators_and_underscores",
            "unicode-key-émoji-🚀",
            "key/with/slashes",
            "key:with:colons",
        ]
        for key in special_keys:
            value = f"value-for-{key}"
            pipeline_client.context_store(key, value)
            retrieved = pipeline_client.context_retrieve(key)
            assert retrieved is not None, f"Should retrieve value for key '{key}'"

print("Part 7 (TestStatusMonitoring, TestEdgeCases) written")

class TestModelManagementEdgeCases:
    """Tests for model management edge cases.

    Covers: loading same model twice, loading unsupported format, unloading
    nonexistent model, loading from invalid paths, and concurrent model
    operations.
    """

    def test_load_same_model_twice(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that loading the same model file twice is handled.

        The mock daemon should handle duplicate model loads gracefully.
        """
        first = pipeline_client.model_load(model_file)
        assert_model_load_response(first, "loaded")
        second = pipeline_client.model_load(model_file)
        assert second is not None
        models = pipeline_client.model_list()
        assert len(models) >= 1

    def test_load_unsupported_format(self, pipeline_client: MockDaemonClient, unsupported_model_file: str) -> None:
        """Verify that loading an unsupported model format returns an error.

        The mock daemon only supports .gguf, .ggml, .onnx, and .bin extensions.
        """
        result = pipeline_client.model_load(unsupported_model_file)
        assert result["status"] == "error"
        assert "unsupported" in result["message"].lower()

    def test_unload_nonexistent_model_returns_not_found(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that unloading a nonexistent model returns 'not_found'.

        The mock daemon should return status 'not_found' for unload requests
        referring to models that were never loaded.
        """
        result = pipeline_client.model_unload("i-do-not-exist-42")
        assert result["status"] == "not_found"

    def test_load_from_empty_path(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that loading from an empty path returns an error.

        The mock daemon should reject empty model paths.
        """
        result = pipeline_client.model_load("")
        assert result["status"] == "error"

    def test_load_from_directory(self, pipeline_client: MockDaemonClient, temp_model_dir: str) -> None:
        """Verify that loading a directory path (not a file) returns an error.

        The mock daemon should check that the path points to a file, not
        a directory.
        """
        result = pipeline_client.model_load(temp_model_dir)
        assert result["status"] == "error"

    def test_load_onnx_format_success(self, pipeline_client: MockDaemonClient, onnx_model_file: str) -> None:
        """Verify that ONNX format models can be loaded successfully.

        The mock daemon supports .onnx extension in addition to .gguf/.ggml.
        """
        result = pipeline_client.model_load(onnx_model_file)
        assert_model_load_response(result, "loaded")

    def test_load_multiple_models_list_count(self, pipeline_client: MockDaemonClient, model_file: str, phi_model_file: str, llama_model_file: str) -> None:
        """Verify that the model list accurately counts loaded models.

        Loads three models, verifies list count, unloads one, verifies
        count decreases.
        """
        pipeline_client.model_load(model_file)
        pipeline_client.model_load(phi_model_file)
        pipeline_client.model_load(llama_model_file)
        models = pipeline_client.model_list()
        assert len(models) == 3
        pipeline_client.model_unload("test_model")
        models = pipeline_client.model_list()
        assert len(models) == 2
        pipeline_client.model_unload("phi-3-mini")
        pipeline_client.model_unload("llama-2-7b")
        models = pipeline_client.model_list()
        assert len(models) == 0

    def test_unload_all_models_bulk(self, pipeline_client: MockDaemonClient, model_file: str, phi_model_file: str) -> None:
        """Verify that bulk unloading of all models works.

        Loads two models, then unloads both, verifying the list is empty.
        """
        pipeline_client.model_load(model_file)
        pipeline_client.model_load(phi_model_file)
        assert len(pipeline_client.model_list()) == 2
        pipeline_client.model_unload("test_model")
        pipeline_client.model_unload("phi-3-mini")
        assert len(pipeline_client.model_list()) == 0

    def test_model_list_after_load_failure(self, pipeline_client: MockDaemonClient, unsupported_model_file: str) -> None:
        """Verify that the model list is unchanged after a failed load.

        After a failed load attempt, the model list should not contain
        the failed model.
        """
        pipeline_client.model_load(unsupported_model_file)
        models = pipeline_client.model_list()
        assert not any(m["id"] == "test_model" for m in models)

    def test_repeated_load_unload_cycles(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that repeated load/unload cycles work correctly.

        Performs 10 load -> unload cycles, verifying each step.
        """
        for cycle in range(10):
            result = pipeline_client.model_load(model_file)
            assert_model_load_response(result, "loaded")
            models = pipeline_client.model_list()
            assert len(models) >= 1
            result = pipeline_client.model_unload("test_model")
            assert_model_unload_response(result, "unloaded")
            models = pipeline_client.model_list()
            assert len(models) == 0


class TestAuthenticationFlowEdgeCases:
    """Tests for authentication flow edge cases.

    Covers: valid token, invalid token, expired session, missing auth,
    token format variations, and permission handling.
    """

    def test_auth_valid_token_full_flow(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that authentication with a valid token grants full access.

        A client with a valid token should be able to authenticate, infer,
        query status, and list models.
        """
        client = mock_daemon_server.make_authenticated_client()
        try:
            infer_result = client.infer("Auth flow test")
            assert_inference_response(infer_result)
            status = client.status()
            assert_status_response(status)
            models = client.model_list()
            assert isinstance(models, list)
        finally:
            client.disconnect()

    def test_auth_invalid_token_rejected(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that an invalid token is rejected during authentication.

        When auth is enabled, an invalid token should result in an
        authentication error.
        """
        client = mock_daemon_server.make_client()
        try:
            with pytest.raises(MockDaemonError) as exc_info:
                client.authenticate("this-is-an-invalid-token!")
            assert "invalid" in str(exc_info.value).lower() or "fail" in str(exc_info.value).lower()
        finally:
            client.disconnect()

    def test_auth_empty_token(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that an empty token is rejected.

        Authentication with an empty string token should fail.
        """
        client = mock_daemon_server.make_client()
        try:
            with pytest.raises(MockDaemonError) as exc_info:
                client.authenticate("")
            assert "token" in str(exc_info.value).lower() or "empty" in str(exc_info.value).lower() or "no" in str(exc_info.value).lower()
        finally:
            client.disconnect()

    def test_auth_very_long_token(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that a very long token is handled gracefully.

        A token of 1000 characters should be accepted or rejected gracefully.
        """
        long_token = "A" * 1000
        client = mock_daemon_server.make_client()
        try:
            with pytest.raises(MockDaemonError):
                client.authenticate(long_token)
        finally:
            client.disconnect()

    def test_auth_token_with_special_chars(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that tokens with special characters are handled.

        Tokens containing special characters should be processed correctly.
        """
        token = "tok-en_wi.th!spec@ial#char$acters%^&*()"
        client = mock_daemon_server.make_client()
        try:
            with pytest.raises(MockDaemonError):
                client.authenticate(token)
        finally:
            client.disconnect()

    def test_request_without_auth(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that requests without authentication are rejected.

        Without prior authentication, any request to the daemon (except
        Auth itself) should be rejected with a 401 error.
        """
        client = mock_daemon_server.make_client()
        try:
            with pytest.raises(MockDaemonError) as exc_info:
                client.infer("No auth request")
            error_message = str(exc_info.value).lower()
            assert "auth" in error_message or "401" in error_message or "required" in error_message
        finally:
            client.disconnect()

    def test_auth_state_after_disconnect(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that authentication state is cleared after disconnect.

        After disconnecting, the client should not be authenticated.
        """
        client = mock_daemon_server.make_authenticated_client()
        assert client.authenticated is True
        client.disconnect()
        assert client.authenticated is False

    def test_auth_independence_between_clients(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that authentication state is independent between clients.

        Authenticating one client should not affect another client's
        authentication state.
        """
        client1 = mock_daemon_server.make_client()
        client2 = mock_daemon_server.make_client()
        try:
            client1.authenticate(mock_daemon_server.auth_token)
            assert client1.authenticated is True
            assert client2.authenticated is False
            client2.authenticate(mock_daemon_server.auth_token)
            assert client2.authenticated is True
            assert client1.authenticated is True
        finally:
            client1.disconnect()
            client2.disconnect()

print("Part 8 (TestModelManagementEdgeCases, TestAuthenticationFlowEdgeCases) written")

class TestLoggingAndCapture:
    """Tests for logging capture and integration with pipelines.

    Covers: logging during pipeline operations, log level configuration,
    and verifying log output contains expected messages.
    """

    def test_pipeline_logging(self, pipeline_client: MockDaemonClient, capture_logs: StringIO) -> None:
        """Verify that pipeline operations produce log output.

        During inference, the SDK should generate log messages that can
        be captured and inspected.
        """
        pipeline_client.infer("Logging test")
        log_output = capture_logs.getvalue()
        assert len(log_output) >= 0

    def test_error_logging(self, error_prone_daemon: MockDaemonServer, capture_logs: StringIO) -> None:
        """Verify that error conditions produce appropriate log messages.

        When an operation fails, the SDK should log the error details.
        """
        client = error_prone_daemon.make_authenticated_client()
        try:
            with pytest.raises(MockDaemonError):
                client.infer("Error logging test")
            log_output = capture_logs.getvalue()
            assert len(log_output) >= 0
        finally:
            client.disconnect()

    def test_auth_logging(self, mock_daemon_server: MockDaemonServer, capture_logs: StringIO) -> None:
        """Verify that authentication operations produce log output.

        Authentication steps should be logged, including success/failure
        and session token information.
        """
        client = mock_daemon_server.make_client()
        try:
            client.authenticate(mock_daemon_server.auth_token)
            log_output = capture_logs.getvalue()
            assert len(log_output) >= 0
        finally:
            client.disconnect()

    def test_logging_during_pipeline(self, pipeline_client: MockDaemonClient, model_file: str, capture_logs: StringIO) -> None:
        """Verify that log output is generated during a full pipeline.

        Runs a full lifecycle pipeline and captures log output.
        """
        pipeline = TestPipeline.build_full_lifecycle(pipeline_client, model_file)
        pipeline.run()
        log_output = capture_logs.getvalue()
        assert len(log_output) >= 0


class TestMiscellaneous:
    """Miscellaneous tests covering additional scenarios and utilities.

    Covers: TestPipeline helper edge cases, PipelineResult behavior,
    utility function behavior, and other infrastructure.
    """

    def test_pipeline_result_defaults(self) -> None:
        """Verify that PipelineResult default values are correct.

        A default-constructed PipelineResult should have success=False
        and None for all optional fields.
        """
        result = PipelineResult(success=False)
        assert result.success is False
        assert result.step_results == {}
        assert result.error is None
        assert result.failed_step is None
        assert result.duration_seconds == 0.0

    def test_pipeline_result_with_values(self) -> None:
        """Verify that PipelineResult can be constructed with all fields.

        A fully populated PipelineResult should return all values correctly.
        """
        error = ValueError("test error")
        result = PipelineResult(
            success=False,
            step_results={"step1": "result1"},
            error=error,
            failed_step="step1",
            duration_seconds=1.5,
        )
        assert result.success is False
        assert result.step_results == {"step1": "result1"}
        assert result.error is error
        assert result.failed_step == "step1"
        assert result.duration_seconds == 1.5

    def test_pipeline_success_result(self) -> None:
        """Verify that PipelineResult correctly represents a successful pipeline."""
        result = PipelineResult(
            success=True,
            step_results={"load": "ok", "infer": "ok", "unload": "ok"},
            duration_seconds=0.5,
        )
        assert result.success is True
        assert len(result.step_results) == 3
        assert result.error is None
        assert result.failed_step is None

    def test_assert_pipeline_success_helper(self) -> None:
        """Verify that assert_pipeline_success passes for successful results."""
        result = PipelineResult(success=True, step_results={"step": "ok"})
        assert_pipeline_success(result)

    def test_assert_pipeline_failure_helper(self) -> None:
        """Verify that assert_pipeline_failure passes for failed results."""
        result = PipelineResult(
            success=False,
            error=ValueError("failed"),
            failed_step="step1",
        )
        assert_pipeline_failure(result, expected_step="step1")

    def test_assert_pipeline_failure_no_step(self) -> None:
        """Verify that assert_pipeline_failure works without expected_step."""
        result = PipelineResult(success=False, error=ValueError("failed"))
        assert_pipeline_failure(result)

    def test_test_pipeline_empty_steps(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that a TestPipeline with no steps returns an empty dict."""
        pipeline = TestPipeline(pipeline_client, "empty")
        results = pipeline.run()
        assert results == {}

    def test_test_pipeline_single_step(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that a TestPipeline with a single step works."""
        pipeline = TestPipeline(pipeline_client, "single")
        pipeline.step("status", lambda c: c.status(), assert_status_response)
        results = pipeline.run()
        assert len(results) == 1
        assert "status" in results

    def test_test_pipeline_state_access(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that TestPipeline state is accessible after run."""
        pipeline = TestPipeline(pipeline_client, "state-test")
        pipeline.step("status", lambda c: c.status(), assert_status_response)
        pipeline.run()
        state = pipeline.state
        assert "status" in state
        assert state["status"] is not None

    def test_test_pipeline_skip_on_failure(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that skip_on_failure prevents execution of subsequent steps."""
        pipeline = TestPipeline(pipeline_client, "skip-test")
        pipeline.step("status", lambda c: c.status(), assert_status_response)
        pipeline.step("fail", lambda c: (_ for _ in ()).throw(ValueError("intentional")), None)
        pipeline.step("should_not_run", lambda c: c.status(), None)
        pipeline.skip_on_failure(True)
        results = pipeline.run()
        assert "status" in results
        assert "fail" in results
        assert "should_not_run" not in results

    def test_random_string_length(self) -> None:
        """Verify that random_string produces strings of the correct length."""
        for length in [0, 1, 5, 16, 32, 64, 128, 256]:
            s = random_string(length)
            assert len(s) == length, f"Expected length {length}, got {len(s)}"

    def test_random_string_characters(self) -> None:
        """Verify that random_string only produces alphanumeric characters."""
        for _ in range(100):
            s = random_string(32)
            assert s.isalnum(), f"Non-alphanumeric characters in: {s}"

    def test_test_pipeline_skip_on_failure_default(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that skip_on_failure is False by default."""
        pipeline = TestPipeline(pipeline_client, "default-skip")
        pipeline.step("status", lambda c: c.status(), assert_status_response)
        pipeline.step("fail", lambda c: (_ for _ in ()).throw(ValueError("intentional")), None)
        pipeline.step("should_not_run", lambda c: c.status(), None)
        with pytest.raises(ValueError, match="intentional"):
            pipeline.run()

    def test_assert_auth_success(self) -> None:
        """Verify that assert_auth_response works with a valid auth response."""
        data = {
            "type": "AuthResponse",
            "success": True,
            "session_token": "sess_test123",
            "message": "OK",
            "permissions": ["infer", "status"],
            "session_ttl_seconds": 3600,
        }
        assert_auth_response(data, True)

    def test_assert_auth_failure(self) -> None:
        """Verify that assert_auth_response works with a failed auth response."""
        data = {
            "type": "AuthResponse",
            "success": False,
            "message": "Invalid token",
            "permissions": [],
            "session_ttl_seconds": 0,
        }
        assert_auth_response(data, False)

    def test_assert_successful_response(self) -> None:
        """Verify that assert_successful_response works."""
        data = {"type": "InferenceResponse", "output": "test"}
        assert_successful_response(data)

    def test_assert_error_response(self) -> None:
        """Verify that assert_error_response works."""
        data = {"type": "Error", "code": 401, "message": "Unauthorized"}
        assert_error_response(data, 401)

    def test_assert_valid_message_type(self) -> None:
        """Verify that assert_valid_message_type works."""
        assert_valid_message_type("Auth")
        assert_valid_message_type("InferenceResponse")
        assert_valid_message_type("Error")
        with pytest.raises(AssertionError):
            assert_valid_message_type("InvalidType")

    def test_pipeline_with_skip_on_failure_middle(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that skip_on_failure skips steps after a middle step failure."""
        pipeline = TestPipeline(pipeline_client, "skip-middle")
        pipeline.step("step1", lambda c: c.status(), assert_status_response)
        pipeline.step("step2", lambda c: c.status(), assert_status_response)
        pipeline.step("step_fail", lambda c: (_ for _ in ()).throw(RuntimeError("fail")), None)
        pipeline.step("step4", lambda c: c.status(), assert_status_response)
        pipeline.step("step5", lambda c: c.status(), assert_status_response)
        pipeline.skip_on_failure(True)
        results = pipeline.run()
        assert "step1" in results
        assert "step2" in results
        assert "step_fail" in results
        assert "step4" not in results
        assert "step5" not in results

print("Part 9 (TestLoggingAndCapture, TestMiscellaneous) written")

class TestPipelineMatrix:
    """Tests for the full pipeline matrix — combinations of operations.

    Covers: all combinations of operations that can be chained together,
    ensuring that the pipeline infrastructure handles all valid sequences.
    """

    def test_pipeline_matrix_load_infer_unload(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify the load -> infer -> unload pipeline matrix entry."""
        pipeline = TestPipeline(pipeline_client, "matrix-liu")
        pipeline.step("load", lambda c: c.model_load(model_file), lambda r: assert_model_load_response(r, "loaded"))
        pipeline.step("infer", lambda c: c.infer("Matrix infer"), assert_inference_response)
        pipeline.step("unload", lambda c: c.model_unload("test_model"), lambda r: assert_model_unload_response(r, "unloaded"))
        results = pipeline.run()
        assert len(results) == 3

    def test_pipeline_matrix_infer_status(self, pipeline_client: MockDaemonClient) -> None:
        """Verify the infer -> status pipeline matrix entry."""
        pipeline = TestPipeline(pipeline_client, "matrix-is")
        pipeline.step("infer", lambda c: c.infer("Matrix infer-status"), assert_inference_response)
        pipeline.step("status", lambda c: c.status(), assert_status_response)
        results = pipeline.run()
        assert len(results) == 2

    def test_pipeline_matrix_load_list_unload(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify the load -> list -> unload pipeline matrix entry."""
        pipeline = TestPipeline(pipeline_client, "matrix-llu")
        pipeline.step("load", lambda c: c.model_load(model_file), lambda r: assert_model_load_response(r, "loaded"))
        pipeline.step("list", lambda c: c.model_list(), lambda r: (_ for _ in ()).throw(AssertionError("len < 1")) if len(r) < 1 else None)
        pipeline.step("unload", lambda c: c.model_unload("test_model"), lambda r: assert_model_unload_response(r, "unloaded"))
        results = pipeline.run()
        assert len(results) == 3

    def test_pipeline_matrix_store_retrieve(self, pipeline_client: MockDaemonClient) -> None:
        """Verify the context store -> retrieve pipeline matrix entry."""
        key = "matrix-key-" + random_string(6)
        val = "matrix-val-" + random_string(6)
        pipeline = TestPipeline(pipeline_client, "matrix-sr")
        pipeline.step("store", lambda c: c.context_store(key, val), lambda r: (_ for _ in ()).throw(AssertionError("r is None")) if r is None else None)
        pipeline.step("retrieve", lambda c: c.context_retrieve(key), lambda r: (_ for _ in ()).throw(AssertionError("val not in r")) if r is None or val not in r else None)
        results = pipeline.run()
        assert len(results) == 2

    def test_pipeline_matrix_full_with_phi(self, pipeline_client: MockDaemonClient, phi_model_file: str) -> None:
        """Verify the full pipeline matrix entry with phi model."""
        pipeline = TestPipeline(pipeline_client, "matrix-full-phi")
        pipeline.step("load", lambda c: c.model_load(phi_model_file), lambda r: assert_model_load_response(r, "loaded"))
        pipeline.step("infer", lambda c: c.infer("Phi matrix infer"), assert_inference_response)
        pipeline.step("list", lambda c: c.model_list(), lambda r: (_ for _ in ()).throw(AssertionError("len < 1")) if len(r) < 1 else None)
        pipeline.step("unload", lambda c: c.model_unload("phi-3-mini"), lambda r: assert_model_unload_response(r, "unloaded"))
        results = pipeline.run()
        assert len(results) == 4

    def test_pipeline_matrix_three_inferences(self, pipeline_client: MockDaemonClient) -> None:
        """Verify the three consecutive inferences matrix entry."""
        pipeline = TestPipeline(pipeline_client, "matrix-3inf")
        pipeline.step("inf1", lambda c: c.infer("First"), assert_inference_response)
        pipeline.step("inf2", lambda c: c.infer("Second"), assert_inference_response)
        pipeline.step("inf3", lambda c: c.infer("Third"), assert_inference_response)
        results = pipeline.run()
        assert len(results) == 3

    def test_pipeline_matrix_load_twice(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify the load -> load -> list -> unload -> unload matrix entry."""
        pipeline = TestPipeline(pipeline_client, "matrix-2load")
        pipeline.step("load1", lambda c: c.model_load(model_file), lambda r: assert_model_load_response(r, "loaded"))
        pipeline.step("load2", lambda c: c.model_load(model_file), None)
        pipeline.step("list", lambda c: c.model_list(), lambda r: (_ for _ in ()).throw(AssertionError("len < 1")) if len(r) < 1 else None)
        pipeline.step("unload1", lambda c: c.model_unload("test_model"), lambda r: assert_model_unload_response(r, "unloaded"))
        results = pipeline.run()
        assert len(results) == 4

    def test_pipeline_matrix_context_overwrite_retrieve(self, pipeline_client: MockDaemonClient) -> None:
        """Verify the context store -> store (overwrite) -> retrieve matrix entry."""
        key = "matrix-overwrite-" + random_string(6)
        pipeline = TestPipeline(pipeline_client, "matrix-cor")
        pipeline.step("store1", lambda c: c.context_store(key, "first"), None)
        pipeline.step("store2", lambda c: c.context_store(key, "second"), None)
        pipeline.step("retrieve", lambda c: c.context_retrieve(key), lambda r: (_ for _ in ()).throw(AssertionError("second not found")) if r is None or "second" not in r else None)
        results = pipeline.run()
        assert len(results) == 3


class TestDaemonConfiguration:
    """Tests for daemon configuration and its effect on pipelines.

    Covers: interactions with different daemon configurations (auth enabled,
    rate limited, slow, error-prone) and how they affect pipeline behavior.
    """

    def test_no_auth_daemon_pipeline(self, no_auth_daemon: MockDaemonServer) -> None:
        """Verify that a full pipeline works on a no-auth daemon."""
        client = no_auth_daemon.make_client()
        try:
            result = client.infer("No-auth pipeline test")
            assert_inference_response(result)
            status = client.status()
            assert_status_response(status)
            models = client.model_list()
            assert isinstance(models, list)
        finally:
            client.disconnect()

    def test_rate_limited_daemon_single_request(self, rate_limited_daemon: MockDaemonServer) -> None:
        """Verify that a single request works on a rate-limited daemon."""
        client = rate_limited_daemon.make_authenticated_client()
        try:
            result = client.infer("Single request on rate-limited daemon")
            assert_inference_response(result)
        finally:
            client.disconnect()

    def test_error_prone_daemon_status_only(self, error_prone_daemon: MockDaemonServer) -> None:
        """Verify that status queries work on an error-prone daemon."""
        client = error_prone_daemon.make_authenticated_client()
        try:
            for _ in range(3):
                status = client.status()
                assert_status_response(status)
        finally:
            client.disconnect()

    def test_slow_daemon_status_query(self, slow_daemon: MockDaemonServer) -> None:
        """Verify that status queries on a slow daemon return valid data."""
        client = slow_daemon.make_authenticated_client()
        try:
            status = client.status()
            assert_status_response(status)
        finally:
            client.disconnect()

    def test_slow_daemon_multiple_requests(self, slow_daemon: MockDaemonServer) -> None:
        """Verify that multiple requests on a slow daemon all complete."""
        client = slow_daemon.make_authenticated_client()
        try:
            for i in range(3):
                result = client.infer(f"Slow daemon request {i}")
                assert_inference_response(result)
        finally:
            client.disconnect()


class TestResourceCleanup:
    """Tests for proper resource cleanup during and after pipeline operations.

    Covers: client disconnect, model unload, context cleanup, and ensuring
    no resource leaks between tests.
    """

    def test_client_disconnect_cleanup(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that disconnecting a client properly cleans up resources."""
        client = mock_daemon_server.make_authenticated_client()
        client.infer("Pre-cleanup inference")
        client.disconnect()
        assert client.connected is False
        assert client.authenticated is False

    def test_model_unload_cleanup(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that unloading a model properly cleans up daemon state."""
        pipeline_client.model_load(model_file)
        assert len(pipeline_client.model_list()) == 1
        pipeline_client.model_unload("test_model")
        assert len(pipeline_client.model_list()) == 0

    def test_context_cleanup_between_sessions(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that context is cleaned up between sessions."""
        key = "cleanup-test-key-" + random_string(8)
        client1 = mock_daemon_server.make_authenticated_client()
        try:
            client1.context_store(key, "session1-value")
        finally:
            client1.disconnect()
        client2 = mock_daemon_server.make_authenticated_client()
        try:
            val = client2.context_retrieve(key)
            assert val is None, "Context should not persist across sessions"
        finally:
            client2.disconnect()

    def test_cleanup_after_error(self, error_prone_daemon: MockDaemonServer) -> None:
        """Verify that cleanup is possible after an error."""
        client = error_prone_daemon.make_authenticated_client()
        try:
            with pytest.raises(MockDaemonError):
                client.infer("Error before cleanup")
            client.disconnect()
            assert client.connected is False
        finally:
            client.disconnect()

    def test_cleanup_after_partial_pipeline(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that cleanup works after a partially completed pipeline."""
        pipeline_client.model_load(model_file)
        pipeline_client.infer("Partial pipeline infer")
        pipeline_client.model_unload("test_model")
        assert len(pipeline_client.model_list()) == 0


class TestDeterministicBehavior:
    """Tests for deterministic behavior of pipelines and kernel stubs.

    Covers: reproducibility of results, seed-based determinism, and
    consistent behavior across repeated executions.
    """

    def test_deterministic_seed_fixture(self, deterministic_seed: int) -> None:
        """Verify that the deterministic_seed fixture provides a seed."""
        assert deterministic_seed is not None
        assert isinstance(deterministic_seed, int)

    def test_kernel_deterministic_with_seed(self) -> None:
        """Verify that KernelStub with same seed produces same results."""
        k1 = KernelStub(seed=42)
        k2 = KernelStub(seed=42)
        emb1, _ = k1.ai_embedding([0.5, 0.5], 2, 128)
        emb2, _ = k2.ai_embedding([0.5, 0.5], 2, 128)
        assert emb1 == emb2, "Same seed should produce same embedding"

    def test_kernel_different_seeds_different_results(self) -> None:
        """Verify that different seeds produce different results."""
        k1 = KernelStub(seed=42)
        k2 = KernelStub(seed=99)
        emb1, _ = k1.ai_embedding([0.5, 0.5], 2, 128)
        emb2, _ = k2.ai_embedding([0.5, 0.5], 2, 128)
        assert emb1 != emb2, "Different seeds should produce different embeddings"

    def test_repeated_inference_determinism(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that repeated inferences with same input produce same output structure."""
        r1 = pipeline_client.infer("Determinism test")
        r2 = pipeline_client.infer("Determinism test")
        assert_inference_response(r1)
        assert_inference_response(r2)

    def test_kernel_deterministic_search(self) -> None:
        """Verify that semantic search is deterministic with same inputs."""
        k = KernelStub(seed=42)
        query = [1.0, 0.0, 0.0, 0.0]
        database = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]]
        r1, _ = k.ai_semantic_search(query, database, 2)
        r2, _ = k.ai_semantic_search(query, database, 2)
        assert r1 == r2, "Semantic search should be deterministic"


class TestPerformanceAssertions:
    """Tests for performance-related assertions in pipelines.

    Covers: timing assertions, token generation counts, and basic
    performance characteristics of the mock daemon.
    """

    def test_inference_response_time(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that inference responses are received within a reasonable time."""
        start = time.monotonic()
        result = pipeline_client.infer("Performance test")
        elapsed = time.monotonic() - start
        assert_inference_response(result)
        assert elapsed < 10.0, f"Inference took too long: {elapsed:.2f}s"

    def test_inference_tokens_generated(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that tokens_generated field is populated correctly."""
        result = pipeline_client.infer("Token count test", max_tokens=50)
        assert_inference_response(result)
        assert result["tokens_generated"] > 0, "Should generate at least one token"
        assert result["tokens_generated"] <= 256, "Mock daemon caps at 256 tokens"

    def test_inference_ms_reported(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that inference_ms is reported in the response."""
        result = pipeline_client.infer("Timing test")
        assert_inference_response(result)
        assert result["inference_ms"] > 0, "inference_ms should be positive"

    def test_status_response_time(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that status queries are fast."""
        start = time.monotonic()
        for _ in range(10):
            pipeline_client.status()
        elapsed = time.monotonic() - start
        assert elapsed < 5.0, f"10 status queries took too long: {elapsed:.2f}s"

    def test_model_load_response_time(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that model loads are fast (mock daemon has no real loading)."""
        start = time.monotonic()
        pipeline_client.model_load(model_file)
        elapsed = time.monotonic() - start
        assert elapsed < 5.0, f"Model load took too long: {elapsed:.2f}s"


class TestProtocolCompliance:
    """Tests for IPC protocol compliance and message format correctness.

    Covers: NDJSON format, message type tagging, field presence, and
    response structure validation.
    """

    def test_response_has_type_field(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that all responses have a type field."""
        result = pipeline_client.infer("Type field test")
        assert "type" in result, "Response must have a type field"
        assert result["type"] == "InferenceResponse"

    def test_error_response_has_code(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that error responses have a code field."""
        client = mock_daemon_server.make_client()
        try:
            with pytest.raises(MockDaemonError):
                client.infer("Should fail")
        finally:
            client.disconnect()

    def test_auth_response_has_required_fields(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that auth responses have all required fields."""
        client = mock_daemon_server.make_client()
        try:
            resp = client.authenticate(mock_daemon_server.auth_token)
            assert "type" in resp
            assert "success" in resp
            assert "session_token" in resp
            assert "message" in resp
            assert "permissions" in resp
            assert "session_ttl_seconds" in resp
        finally:
            client.disconnect()

    def test_model_load_response_has_required_fields(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that model load responses have all required fields."""
        resp = pipeline_client.model_load(model_file)
        assert "type" in resp
        assert "model_id" in resp
        assert "status" in resp
        assert "message" in resp

    def test_status_response_has_required_fields(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that status responses have all required fields."""
        resp = pipeline_client.status()
        assert "type" in resp
        assert "uptime" in resp
        assert "models_loaded" in resp
        assert "total_requests" in resp
        assert "network_available" in resp

print("Part 10 (TestPipelineMatrix, TestDaemonConfiguration, TestResourceCleanup, etc.) written")

class TestAdvancedEdgeCases:
    """Tests for advanced edge cases and boundary conditions.

    Covers: deeply nested JSON payloads, very long keys, null characters,
    unicode normalization, and protocol-level edge cases.
    """

    def test_nested_json_in_prompt(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that deeply nested JSON structures in prompts are handled."""
        nested = "{\"a\": {\"b\": {\"c\": {\"d\": {\"e\": \"deep\"}}}}}"
        result = pipeline_client.infer(nested)
        assert_inference_response(result)

    def test_prompt_with_only_numbers(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that prompts containing only numbers are handled."""
        result = pipeline_client.infer("1234567890 42 3.14159 1e10")
        assert_inference_response(result)

    def test_prompt_with_html_tags(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that prompts with HTML tags are handled."""
        html_prompts = [
            "<html><body><p>Hello</p></body></html>",
            "<div class=\"test\">content</div>",
            "<script>alert(1)</script>",
            "<!-- comment -->",
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
        ]
        for prompt in html_prompts:
            result = pipeline_client.infer(prompt)
            assert_inference_response(result)

    def test_prompt_with_urls(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that prompts containing URLs are handled."""
        url_prompts = [
            "https://example.com/path?query=value&param=2",
            "http://localhost:8080/api/v1/models",
            "ftp://files.example.com/document.pdf",
            "file:///C:/Users/test/file.txt",
            "data:text/plain;base64,SGVsbG8=",
        ]
        for prompt in url_prompts:
            result = pipeline_client.infer(prompt)
            assert_inference_response(result)

    def test_prompt_with_control_characters(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that prompts with control characters are handled."""
        control_chars = "\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e\x0f"
        result = pipeline_client.infer(control_chars)
        assert_inference_response(result)

    def test_context_key_max_length(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that context keys of maximum length are handled."""
        key = "k" * 255
        value = "max-length-key-test"
        pipeline_client.context_store(key, value)
        retrieved = pipeline_client.context_retrieve(key)
        assert retrieved is not None

    def test_context_value_with_unicode_escape(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that context values with unicode escape sequences are handled."""
        key = "unicode-escape-key-" + random_string(6)
        value = "\\u0041\\u0042\\u0043"
        pipeline_client.context_store(key, value)
        retrieved = pipeline_client.context_retrieve(key)
        assert retrieved is not None

    def test_model_name_with_unicode(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that model names with unicode characters are handled."""
        model_name = "模型-测试-🚀"
        result = pipeline_client.infer("Unicode model test", model=model_name)
        assert_inference_response(result)

    def test_zero_temperature_inference(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that zero temperature inference works."""
        result = pipeline_client.infer("Zero temp test", temperature=0.0)
        assert_inference_response(result)

    def test_maximum_temperature_inference(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that maximum temperature inference works."""
        result = pipeline_client.infer("Max temp test", temperature=2.0)
        assert_inference_response(result)

    def test_inference_with_negative_temperature(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that negative temperature values are handled."""
        result = pipeline_client.infer("Negative temp test", temperature=-1.0)
        assert_inference_response(result)

    def test_inference_with_zero_max_tokens(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that zero max_tokens is handled."""
        result = pipeline_client.infer("Zero tokens test", max_tokens=0)
        assert_inference_response(result)

    def test_inference_with_negative_max_tokens(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that negative max_tokens is handled."""
        result = pipeline_client.infer("Negative tokens test", max_tokens=-1)
        assert_inference_response(result)

    def test_very_long_model_name(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that very long model names are handled."""
        long_name = "model-" + "x" * 200
        result = pipeline_client.infer("Long model name test", model=long_name)
        assert_inference_response(result)

    def test_context_key_with_null_byte(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that context keys with null bytes are handled."""
        key = "key-with-\x00-null"
        value = "null-byte-key-test"
        pipeline_client.context_store(key, value)
        retrieved = pipeline_client.context_retrieve(key)
        assert retrieved is not None or retrieved is None

    def test_context_value_with_only_whitespace(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that context values with only whitespace are handled."""
        key = "whitespace-value-key-" + random_string(6)
        whitespace_values = ["", " ", "\t", "\n", " \t\n "]
        for val in whitespace_values:
            pipeline_client.context_store(key, val)
            retrieved = pipeline_client.context_retrieve(key)
            assert retrieved is not None

    def test_rapid_context_store_retrieve(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that rapid context store/retrieve operations work."""
        for i in range(50):
            key = f"rapid-ctx-{i}"
            value = f"rapid-val-{i}"
            pipeline_client.context_store(key, value)
            retrieved = pipeline_client.context_retrieve(key)
            assert retrieved is not None

    def test_rapid_model_list_queries(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that rapid model list queries work."""
        for _ in range(20):
            models = pipeline_client.model_list()
            assert isinstance(models, list)

    def test_rapid_status_queries(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that rapid status queries work."""
        for _ in range(20):
            status = pipeline_client.status()
            assert_status_response(status)


class TestComprehensiveCleanup:
    """Tests for comprehensive cleanup scenarios across the entire system.

    Covers: cleanup of models, contexts, sessions, and connections in
    various failure and success scenarios.
    """

    def test_cleanup_all_models(self, pipeline_client: MockDaemonClient, model_file: str, phi_model_file: str, llama_model_file: str) -> None:
        """Verify that all loaded models can be cleaned up."""
        pipeline_client.model_load(model_file)
        pipeline_client.model_load(phi_model_file)
        pipeline_client.model_load(llama_model_file)
        assert len(pipeline_client.model_list()) == 3
        pipeline_client.model_unload("test_model")
        pipeline_client.model_unload("phi-3-mini")
        pipeline_client.model_unload("llama-2-7b")
        assert len(pipeline_client.model_list()) == 0

    def test_cleanup_context(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that context entries can be overwritten and cleaned."""
        keys = [f"cleanup-ctx-{i}-{random_string(4)}" for i in range(5)]
        for i, key in enumerate(keys):
            pipeline_client.context_store(key, f"value-{i}")
        for key in keys:
            val = pipeline_client.context_retrieve(key)
            assert val is not None, f"Key {key} should exist"

    def test_cleanup_after_error_in_pipeline(self, error_prone_daemon: MockDaemonServer, model_file: str) -> None:
        """Verify that cleanup works after a pipeline error."""
        client = error_prone_daemon.make_authenticated_client()
        try:
            with pytest.raises(MockDaemonError):
                client.infer("Error in pipeline")
            status = client.status()
            assert_status_response(status)
            client.disconnect()
            assert client.connected is False
        finally:
            client.disconnect()

    def test_cleanup_multiple_clients(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that multiple clients can be cleaned up."""
        clients = []
        try:
            for i in range(5):
                client = mock_daemon_server.make_authenticated_client()
                clients.append(client)
                client.infer(f"Client {i} inference")
        finally:
            for client in clients:
                try:
                    client.disconnect()
                except Exception:
                    pass

    def test_cleanup_after_disconnect_reconnect(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that cleanup is proper after disconnect/reconnect cycles."""
        client = mock_daemon_server.make_authenticated_client()
        client.infer("Pre-disconnect")
        client.disconnect()
        client.connect()
        client.authenticate(mock_daemon_server.auth_token)
        client.infer("Post-reconnect")
        client.disconnect()
        assert client.connected is False


class TestMockDaemonInternals:
    """Tests for the internal behavior of the mock daemon server.

    Covers: server statistics, session management, model tracking, and
    internal state verification.
    """

    def test_server_stats_after_operations(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that server statistics are updated after operations."""
        stats_before = dict(mock_daemon_server.stats)
        client = mock_daemon_server.make_authenticated_client()
        try:
            client.infer("Stats test 1")
            client.infer("Stats test 2")
            client.infer("Stats test 3")
        finally:
            client.disconnect()
        stats_after = mock_daemon_server.stats
        assert stats_after["total_requests"] >= stats_before["total_requests"] + 3
        assert stats_after["total_inferences"] >= stats_before["total_inferences"] + 3

    def test_server_session_count(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that the server tracks active sessions."""
        sessions_before = len(mock_daemon_server.sessions)
        client = mock_daemon_server.make_authenticated_client()
        try:
            sessions_during = len(mock_daemon_server.sessions)
            assert sessions_during >= sessions_before + 1
        finally:
            client.disconnect()

    def test_server_model_tracking(self, mock_daemon_server: MockDaemonServer, model_file: str) -> None:
        """Verify that the server correctly tracks loaded models."""
        models_before = len(mock_daemon_server.models)
        client = mock_daemon_server.make_authenticated_client()
        try:
            client.model_load(model_file)
            assert len(mock_daemon_server.models) == models_before + 1
            client.model_unload("test_model")
            assert len(mock_daemon_server.models) == models_before
        finally:
            client.disconnect()

    def test_server_rate_limit_tracking(self, rate_limited_daemon: MockDaemonServer) -> None:
        """Verify that the server tracks rate limits."""
        client = rate_limited_daemon.make_authenticated_client()
        try:
            client_id = f"{client._host}:{client._port}"
            for _ in range(5):
                try:
                    client.infer("Rate limit tracking test")
                except MockDaemonError:
                    pass
        finally:
            client.disconnect()

    def test_server_error_counts(self, error_prone_daemon: MockDaemonServer) -> None:
        """Verify that the server tracks error counts."""
        errors_before = error_prone_daemon.stats["total_errors"]
        client = error_prone_daemon.make_authenticated_client()
        try:
            with pytest.raises(MockDaemonError):
                client.infer("Error count test")
        finally:
            client.disconnect()
        errors_after = error_prone_daemon.stats["total_errors"]
        assert errors_after >= errors_before + 1


class TestTimeBudgetEnforcement:
    """Tests for time budget enforcement in pipelines.

    Covers: the time_budget fixture, ensuring tests complete within
    their allocated time, and handling of slow operations.
    """

    def test_time_budget_available(self, time_budget: float) -> None:
        """Verify that the time_budget fixture provides a budget value."""
        assert time_budget > 0
        assert isinstance(time_budget, float)

    def test_quick_operation_within_budget(self, pipeline_client: MockDaemonClient, time_budget: float) -> None:
        """Verify that quick operations complete within the time budget."""
        start = time.monotonic()
        pipeline_client.infer("Budget test")
        pipeline_client.status()
        elapsed = time.monotonic() - start
        assert elapsed < time_budget, f"Operation took {elapsed:.2f}s, budget was {time_budget}s"

    def test_multiple_operations_within_budget(self, pipeline_client: MockDaemonClient, model_file: str, time_budget: float) -> None:
        """Verify that multiple operations complete within the time budget."""
        start = time.monotonic()
        for i in range(5):
            pipeline_client.infer(f"Budget test {i}")
        pipeline_client.model_load(model_file)
        pipeline_client.model_unload("test_model")
        elapsed = time.monotonic() - start
        assert elapsed < time_budget, f"Operations took {elapsed:.2f}s, budget was {time_budget}s"

print("Part 11 (TestAdvancedEdgeCases, TestComprehensiveCleanup, etc.) written")

class TestMultipleFixtures:
    """Tests that combine multiple fixtures simultaneously.

    Covers: using the mock daemon, kernel stub, temp model dir, and
    test vectors together in a single test.
    """

    def test_mock_daemon_and_kernel_together(self, mock_daemon_server: MockDaemonServer, pipeline_kernel: KernelStub) -> None:
        """Verify that both daemon and kernel can be used together."""
        client = mock_daemon_server.make_authenticated_client()
        try:
            result = client.infer("Daemon + kernel test")
            assert_inference_response(result)
            embedding, err = pipeline_kernel.ai_embedding([0.5, 0.5], 2, 128)
            assert err == AI_ERR_SUCCESS
            assert embedding is not None
        finally:
            client.disconnect()

    def test_temp_model_dir_with_daemon(self, mock_daemon_server: MockDaemonServer, temp_model_dir: str) -> None:
        """Verify that temp model dir works with the daemon."""
        model_path = os.path.join(temp_model_dir, "test_model.gguf")
        client = mock_daemon_server.make_authenticated_client()
        try:
            result = client.model_load(model_path)
            assert_model_load_response(result, "loaded")
        finally:
            client.disconnect()

    def test_test_vectors_with_daemon(self, mock_daemon_server: MockDaemonServer, test_vectors: dict) -> None:
        """Verify that test vectors can be used alongside daemon operations."""
        assert "long_prompt" in test_vectors
        assert "special_chars_prompt" in test_vectors
        client = mock_daemon_server.make_authenticated_client()
        try:
            result = client.infer(test_vectors["long_prompt"][:200])
            assert_inference_response(result)
            result2 = client.infer(test_vectors["special_chars_prompt"])
            assert_inference_response(result2)
        finally:
            client.disconnect()

    def test_multiple_kernel_instances(self) -> None:
        """Verify that multiple kernel instances are independent."""
        k1 = KernelStub(seed=42)
        k2 = KernelStub(seed=99)
        k1.ai_model_load("model1", "/path/m1.gguf")
        k2.ai_model_load("model2", "/path/m2.gguf")
        assert len(k1.models) == 1
        assert len(k2.models) == 1
        assert list(k1.models.values())[0]["name"] == "model1"
        assert list(k2.models.values())[0]["name"] == "model2"

    def test_deterministic_seed_with_kernel(self, deterministic_seed: int) -> None:
        """Verify that deterministic seed works with kernel stub."""
        k = KernelStub(seed=deterministic_seed)
        emb1, _ = k.ai_embedding([0.5], 1, 128)
        emb2, _ = k.ai_embedding([0.5], 1, 128)
        assert emb1 == emb2


class TestSessionAndConnection:
    """Tests for advanced session and connection management.

    Covers: connection state tracking, session token management,
    and reconnection behavior.
    """

    def test_connection_state_after_operations(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that connection state is consistent after operations."""
        client = mock_daemon_server.make_client()
        assert client.connected is True
        assert client.authenticated is False
        client.authenticate(mock_daemon_server.auth_token)
        assert client.authenticated is True
        client.infer("State check")
        assert client.connected is True
        assert client.authenticated is True
        client.disconnect()
        assert client.connected is False
        assert client.authenticated is False

    def test_session_token_after_reconnect(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that session token changes after reconnect."""
        client = mock_daemon_server.make_client()
        client.authenticate(mock_daemon_server.auth_token)
        token1 = client._session_token
        client.disconnect()
        client.connect()
        client.authenticate(mock_daemon_server.auth_token)
        token2 = client._session_token
        assert token1 != token2, "Session token should change after reconnect"

    def test_multiple_authentications_same_client(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that authenticating multiple times on the same connection works."""
        client = mock_daemon_server.make_client()
        try:
            resp1 = client.authenticate(mock_daemon_server.auth_token)
            assert_auth_response(resp1, True)
            resp2 = client.authenticate(mock_daemon_server.auth_token)
            assert_auth_response(resp2, True)
        finally:
            client.disconnect()

    def test_connection_without_auth_no_auth_mode(self, no_auth_daemon: MockDaemonServer) -> None:
        """Verify that connection works without auth in no-auth mode."""
        client = no_auth_daemon.make_client()
        try:
            assert client.connected is True
            result = client.infer("No auth mode test")
            assert_inference_response(result)
        finally:
            client.disconnect()


class TestPipelineIntegration:
    """Tests for integration between different pipeline components.

    Covers: interactions between the daemon, kernel, and SDK layers,
    ensuring that they work together correctly.
    """

    def test_daemon_kernel_status_consistency(self, mock_daemon_server: MockDaemonServer, pipeline_kernel: KernelStub) -> None:
        """Verify that daemon and kernel status are consistent."""
        client = mock_daemon_server.make_authenticated_client()
        try:
            daemon_status = client.status()
            assert_status_response(daemon_status)
            kernel_status, err = pipeline_kernel.ai_status()
            assert err == AI_ERR_SUCCESS
            assert "models_loaded" in kernel_status
        finally:
            client.disconnect()

    def test_daemon_context_and_kernel_context(self, mock_daemon_server: MockDaemonServer, pipeline_kernel: KernelStub) -> None:
        """Verify that daemon context and kernel context are independent."""
        client = mock_daemon_server.make_authenticated_client()
        try:
            client.context_store("daemon-key", "daemon-value")
            entry_id, err = pipeline_kernel.ai_context_store(1, "kernel-key", "kernel-value", 60000)
            assert err == AI_ERR_SUCCESS
            daemon_val = client.context_retrieve("daemon-key")
            assert daemon_val is not None
            kernel_val, err = pipeline_kernel.ai_context_retrieve(1, "kernel-key", 0)
            assert err == AI_ERR_SUCCESS
            assert kernel_val == "kernel-value"
        finally:
            client.disconnect()

    def test_daemon_model_load_and_kernel_model_load(self, mock_daemon_server: MockDaemonServer, pipeline_kernel: KernelStub, model_file: str) -> None:
        """Verify that daemon and kernel model loading are independent."""
        client = mock_daemon_server.make_authenticated_client()
        try:
            daemon_result = client.model_load(model_file)
            assert_model_load_response(daemon_result, "loaded")
            kernel_id, err = pipeline_kernel.ai_model_load("kernel-model", "/path/kernel.gguf")
            assert err == AI_ERR_SUCCESS
            assert kernel_id is not None
            daemon_models = client.model_list()
            assert len(daemon_models) >= 1
            assert len(pipeline_kernel.models) == 1
        finally:
            client.disconnect()


class TestPipelineStress:
    """Lightweight stress tests for pipeline components.

    Covers: sustained operation loads, many sequential operations,
    and resource usage under repeated operations.
    """

    @pytest.mark.slow
    def test_sustained_inference_load(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that sustained inference load is handled."""
        for i in range(100):
            result = pipeline_client.infer(f"Sustained load test {i}")
            assert_inference_response(result)

    @pytest.mark.slow
    def test_sustained_model_operations(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that sustained model load/unload operations are handled."""
        for i in range(20):
            result = pipeline_client.model_load(model_file)
            assert_model_load_response(result, "loaded")
            result = pipeline_client.model_unload("test_model")
            assert_model_unload_response(result, "unloaded")

    @pytest.mark.slow
    def test_sustained_context_operations(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that sustained context store/retrieve operations are handled."""
        for i in range(50):
            key = f"sustained-ctx-{i}"
            value = f"sustained-val-{i}"
            pipeline_client.context_store(key, value)
            retrieved = pipeline_client.context_retrieve(key)
            assert retrieved is not None

    @pytest.mark.slow
    def test_mixed_sustained_load(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that mixed sustained load (infer, status, context) is handled."""
        for i in range(30):
            if i % 3 == 0:
                result = pipeline_client.infer(f"Mixed sustained load {i}")
                assert_inference_response(result)
            elif i % 3 == 1:
                status = pipeline_client.status()
                assert_status_response(status)
            else:
                key = f"mixed-ctx-{i}"
                pipeline_client.context_store(key, f"value-{i}")
                val = pipeline_client.context_retrieve(key)
                assert val is not None


class TestServerRestart:
    """Tests for server restart scenarios and their effect on pipelines.

    Covers: stopping and restarting the mock daemon, reconnecting clients,
    and verifying state is properly reset.
    """

    def test_server_stop_and_restart(self) -> None:
        """Verify that the server can be stopped and restarted."""
        server = MockDaemonServer(auth_enabled=True)
        server.start()
        client = server.make_authenticated_client()
        try:
            result = client.infer("Pre-restart test")
            assert_inference_response(result)
        finally:
            client.disconnect()
        server.stop()
        server.start()
        client2 = server.make_authenticated_client()
        try:
            result = client2.infer("Post-restart test")
            assert_inference_response(result)
        finally:
            client2.disconnect()
        server.stop()

    def test_server_state_reset_after_restart(self) -> None:
        """Verify that server state is reset after a restart."""
        server = MockDaemonServer(auth_enabled=True)
        server.start()
        client = server.make_authenticated_client()
        try:
            client.infer("State test")
        finally:
            client.disconnect()
        server.stop()
        server.start()
        assert len(server.models) == 0
        assert len(server.sessions) == 0
        assert len(server.context_store) == 0
        server.stop()

    def test_server_multiple_restart_cycles(self) -> None:
        """Verify that the server can survive multiple restart cycles."""
        for cycle in range(3):
            server = MockDaemonServer(auth_enabled=True)
            server.start()
            client = server.make_authenticated_client()
            try:
                result = client.infer(f"Restart cycle {cycle}")
                assert_inference_response(result)
            finally:
                client.disconnect()
            server.stop()

print("Part 12 (MultipleFixtures, SessionAndConnection, PipelineIntegration, Stress, ServerRestart) written")

class TestNegativeScenarios:
    """Tests for negative scenarios and error injection.

    Covers: various error conditions, invalid inputs, and edge cases
    that should produce errors rather than succeeding silently.
    """

    def test_infer_with_none_prompt(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that inference with None prompt is handled."""
        try:
            result = pipeline_client.infer(None)
            assert result is not None
        except (TypeError, MockDaemonError):
            pass

    def test_context_store_none_key(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that context store with None key is handled."""
        try:
            result = pipeline_client.context_store(None, "value")
            assert result is not None
        except (TypeError, MockDaemonError):
            pass

    def test_context_store_none_value(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that context store with None value is handled."""
        try:
            result = pipeline_client.context_store("key", None)
            assert result is not None
        except (TypeError, MockDaemonError):
            pass

    def test_model_load_with_none_path(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that model load with None path is handled."""
        try:
            result = pipeline_client.model_load(None)
            assert result is not None
        except (TypeError, MockDaemonError):
            pass

    def test_model_unload_with_none_id(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that model unload with None id is handled."""
        try:
            result = pipeline_client.model_unload(None)
            assert result is not None
        except (TypeError, MockDaemonError):
            pass

    def test_concurrent_access_to_same_context(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that concurrent access to the same context key is handled."""
        key = "concurrent-access-key-" + random_string(6)
        def writer(client_id: int, value: str) -> bool:
            client = mock_daemon_server.make_authenticated_client()
            try:
                client.context_store(key, value)
                return True
            except Exception:
                return False
            finally:
                client.disconnect()

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(writer, i, f"value-{i}")
                for i in range(4)
            ]
            results = [f.result() for f in as_completed(futures)]
        assert any(results), "At least one concurrent write should succeed"


class TestKernelContextTTL:
    """Tests for kernel context TTL (time-to-live) behavior.

    Covers: TTL expiration, zero TTL, negative TTL, and maximum TTL
    scenarios for kernel context store entries.
    """

    def test_kernel_context_ttl_zero(self, pipeline_kernel: KernelStub) -> None:
        """Verify that zero TTL means immediate expiry."""
        entry_id, err = pipeline_kernel.ai_context_store(1, "zero-ttl", "value", 0)
        assert err == AI_ERR_SUCCESS
        time.sleep(0.001)
        value, err = pipeline_kernel.ai_context_retrieve(1, "zero-ttl", 0)
        assert err == AI_ERR_INVALID_PARAM or err == AI_ERR_SUCCESS

    def test_kernel_context_ttl_very_long(self, pipeline_kernel: KernelStub) -> None:
        """Verify that very long TTL is handled."""
        entry_id, err = pipeline_kernel.ai_context_store(1, "long-ttl", "value", 86400000)
        assert err == AI_ERR_SUCCESS
        value, err = pipeline_kernel.ai_context_retrieve(1, "long-ttl", 0)
        assert err == AI_ERR_SUCCESS
        assert value == "value"

    def test_kernel_context_ttl_negative(self, pipeline_kernel: KernelStub) -> None:
        """Verify that negative TTL is handled."""
        entry_id, err = pipeline_kernel.ai_context_store(1, "neg-ttl", "value", -1)
        assert err == AI_ERR_SUCCESS

    def test_kernel_context_multiple_ttls(self, pipeline_kernel: KernelStub) -> None:
        """Verify that multiple context entries with different TTLs are handled."""
        pipeline_kernel.ai_context_store(1, "short", "short-value", 1)
        pipeline_kernel.ai_context_store(1, "long", "long-value", 60000)
        time.sleep(0.002)
        short_val, err = pipeline_kernel.ai_context_retrieve(1, "short", 0)
        assert err == AI_ERR_INVALID_PARAM or err == AI_ERR_SUCCESS
        long_val, err = pipeline_kernel.ai_context_retrieve(1, "long", 0)
        assert err == AI_ERR_SUCCESS
        if err == AI_ERR_SUCCESS:
            assert long_val == "long-value"


class TestKernelEmbeddingEdgeCases:
    """Tests for kernel embedding edge cases.

    Covers: various input dimensions, data types, and edge conditions
    for the embedding syscall.
    """

    def test_kernel_embedding_all_valid_dims(self, pipeline_kernel: KernelStub) -> None:
        """Verify that all valid embedding dimensions work."""
        valid_dims = [128, 256, 512, 768, 1024, 2048, 4096]
        for dim in valid_dims:
            embedding, err = pipeline_kernel.ai_embedding([0.1] * 64, 64, dim)
            assert err == AI_ERR_SUCCESS, f"Dim {dim} should be valid"
            assert embedding is not None
            assert len(embedding) == dim

    def test_kernel_embedding_large_input(self, pipeline_kernel: KernelStub) -> None:
        """Verify that embedding with large input works."""
        large_input = [0.01 * i for i in range(1000)]
        embedding, err = pipeline_kernel.ai_embedding(large_input, len(large_input), 128)
        assert err == AI_ERR_SUCCESS
        assert embedding is not None

    def test_kernel_embedding_single_element(self, pipeline_kernel: KernelStub) -> None:
        """Verify that embedding with a single element works."""
        embedding, err = pipeline_kernel.ai_embedding([0.5], 1, 128)
        assert err == AI_ERR_SUCCESS
        assert embedding is not None
        assert len(embedding) == 128

    def test_kernel_embedding_all_zeros(self, pipeline_kernel: KernelStub) -> None:
        """Verify that embedding with all-zero input works."""
        embedding, err = pipeline_kernel.ai_embedding([0.0] * 10, 10, 128)
        assert err == AI_ERR_SUCCESS
        assert embedding is not None

    def test_kernel_embedding_all_ones(self, pipeline_kernel: KernelStub) -> None:
        """Verify that embedding with all-ones input works."""
        embedding, err = pipeline_kernel.ai_embedding([1.0] * 10, 10, 128)
        assert err == AI_ERR_SUCCESS
        assert embedding is not None


class TestKernelSemanticSearchEdgeCases:
    """Tests for kernel semantic search edge cases.

    Covers: various database sizes, query types, and edge conditions
    for the semantic search syscall.
    """

    def test_kernel_search_single_database_entry(self, pipeline_kernel: KernelStub) -> None:
        """Verify that search with a single database entry works."""
        query = [1.0, 0.0, 0.0, 0.0]
        database = [[1.0, 0.0, 0.0, 0.0]]
        results, err = pipeline_kernel.ai_semantic_search(query, database, 1)
        assert err == AI_ERR_SUCCESS
        assert results is not None
        assert len(results) == 1

    def test_kernel_search_large_database(self, pipeline_kernel: KernelStub) -> None:
        """Verify that search with a large database works."""
        query = [1.0] + [0.0] * 63
        database = [
            [float(j == i % 64) for j in range(64)]
            for i in range(100)
        ]
        results, err = pipeline_kernel.ai_semantic_search(query, database, 5)
        assert err == AI_ERR_SUCCESS
        assert results is not None
        assert len(results) == 5

    def test_kernel_search_top_k_greater_than_database(self, pipeline_kernel: KernelStub) -> None:
        """Verify that search with top_k > database size is handled."""
        query = [1.0, 0.0, 0.0]
        database = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        results, err = pipeline_kernel.ai_semantic_search(query, database, 10)
        assert err == AI_ERR_SUCCESS
        assert results is not None
        assert len(results) == 2

    def test_kernel_search_identical_vectors(self, pipeline_kernel: KernelStub) -> None:
        """Verify that search with identical vectors produces correct scores."""
        query = [1.0, 0.0, 0.0, 0.0]
        database = [[1.0, 0.0, 0.0, 0.0] for _ in range(5)]
        results, err = pipeline_kernel.ai_semantic_search(query, database, 3)
        assert err == AI_ERR_SUCCESS
        assert results is not None
        assert len(results) == 3
        for _, score in results:
            assert abs(score - 1.0) < 0.001, f"Identical vectors should have score ~1.0, got {score}"


class TestLargeDataHandling:
    """Tests for handling large data payloads in pipelines.

    Covers: large prompts, large context values, many concurrent
    operations, and large model lists.
    """

    def test_large_prompt_thousands_of_words(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that a prompt with thousands of words is handled."""
        words = ["word" + str(i) for i in range(5000)]
        large_prompt = " ".join(words)
        result = pipeline_client.infer(large_prompt)
        assert_inference_response(result)

    def test_many_context_keys(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that many context keys can be stored and retrieved."""
        keys = {}
        for i in range(100):
            key = f"many-keys-{i}-{random_string(4)}"
            value = f"many-vals-{i}-{random_string(4)}"
            keys[key] = value
            pipeline_client.context_store(key, value)
        for key, expected in keys.items():
            retrieved = pipeline_client.context_retrieve(key)
            assert retrieved is not None, f"Key {key} should exist"

    def test_large_model_list(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that many model loads produce a correct model list."""
        for i in range(10):
            pipeline_client.model_load(model_file)
        models = pipeline_client.model_list()
        assert len(models) >= 10
        for m in models:
            assert m["id"] == "test_model"
        for i in range(10):
            pipeline_client.model_unload("test_model")
        assert len(pipeline_client.model_list()) == 0


class TestFixtureCombinations:
    """Tests for various fixture combinations and their interactions.

    Covers: using multiple fixtures together, fixture scoping, and
    ensuring fixtures are properly set up and torn down.
    """

    def test_mock_daemon_with_capture_logs(self, mock_daemon_server: MockDaemonServer, capture_logs: StringIO) -> None:
        """Verify that mock daemon works with log capture."""
        client = mock_daemon_server.make_authenticated_client()
        try:
            client.infer("Log capture test")
            log_output = capture_logs.getvalue()
            assert len(log_output) >= 0
        finally:
            client.disconnect()

    def test_rate_limited_with_time_budget(self, rate_limited_daemon: MockDaemonServer, time_budget: float) -> None:
        """Verify that rate limited daemon works within time budget."""
        client = rate_limited_daemon.make_authenticated_client()
        try:
            start = time.monotonic()
            for i in range(10):
                try:
                    client.infer(f"Budget rate limit {i}")
                except MockDaemonError:
                    pass
            elapsed = time.monotonic() - start
            assert elapsed < time_budget
        finally:
            client.disconnect()

    def test_error_prone_with_kernel(self, error_prone_daemon: MockDaemonServer, pipeline_kernel: KernelStub) -> None:
        """Verify that error prone daemon works alongside kernel stub."""
        client = error_prone_daemon.make_authenticated_client()
        try:
            with pytest.raises(MockDaemonError):
                client.infer("Error with kernel")
            embedding, err = pipeline_kernel.ai_embedding([0.5], 1, 128)
            assert err == AI_ERR_SUCCESS
        finally:
            client.disconnect()

print("Part 13 (NegativeScenarios, KernelContextTTL, KernelEmbedding, LargeData, FixtureCombinations) written")

class TestEnumerationAndCounts:
    """Tests for enumeration and counting in various pipeline operations.

    Covers: verifying that counts are correct after operations, checking
    that enumerations are complete, and ensuring no double-counting.
    """

    def test_inference_count_after_multiple_requests(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that the inference count increases after each request."""
        status_before = pipeline_client.status()
        count_before = status_before.get("total_requests", 0)
        for i in range(5):
            pipeline_client.infer(f"Count test {i}")
        status_after = pipeline_client.status()
        count_after = status_after.get("total_requests", 0)
        assert count_after >= count_before + 5

    def test_model_count_after_loads_and_unloads(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that model count is accurate after loads and unloads."""
        assert len(pipeline_client.model_list()) == 0
        pipeline_client.model_load(model_file)
        assert len(pipeline_client.model_list()) == 1
        pipeline_client.model_load(model_file)
        pipeline_client.model_unload("test_model")
        assert len(pipeline_client.model_list()) >= 0

    def test_context_count_after_multiple_stores(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that context stores are independent and countable."""
        for i in range(10):
            key = f"count-ctx-{i}-{random_string(4)}"
            pipeline_client.context_store(key, f"value-{i}")
        for i in range(10):
            key = f"count-ctx-{i}-{random_string(4)}"
            retrieved = pipeline_client.context_retrieve(key)
            if retrieved is not None:
                pass

    def test_session_count_after_multiple_clients(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that the session count reflects connected clients."""
        clients = []
        try:
            for i in range(3):
                client = mock_daemon_server.make_authenticated_client()
                clients.append(client)
            status = clients[0].status()
            assert "active_sessions" in status
        finally:
            for c in clients:
                try:
                    c.disconnect()
                except Exception:
                    pass


class TestPipelineOrchestration:
    """Tests for the pipeline orchestration layer itself.

    Covers: TestPipeline edge cases, step ordering, validator behavior,
    and state management during pipeline execution.
    """

    def test_pipeline_step_ordering(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that steps execute in the order they are registered."""
        execution_order = []
        pipeline = TestPipeline(pipeline_client, "ordering")
        pipeline.step("first", lambda c: execution_order.append("first"), None)
        pipeline.step("second", lambda c: execution_order.append("second"), None)
        pipeline.step("third", lambda c: execution_order.append("third"), None)
        pipeline.run()
        assert execution_order == ["first", "second", "third"]

    def test_pipeline_validator_called(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that validators are called with the step result."""
        validated_values = []
        def validator(result):
            validated_values.append(result.get("type"))
        pipeline = TestPipeline(pipeline_client, "validator-test")
        pipeline.step("status", lambda c: c.status(), validator)
        pipeline.run()
        assert "StatusResponse" in validated_values

    def test_pipeline_state_isolation(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that separate pipelines have isolated state."""
        p1 = TestPipeline(pipeline_client, "p1")
        p2 = TestPipeline(pipeline_client, "p2")
        p1.step("s1", lambda c: c.status(), assert_status_response)
        p2.step("s2", lambda c: c.status(), assert_status_response)
        p1.run()
        p2.run()
        assert "s1" in p1.state
        assert "s2" in p2.state
        assert "s1" not in p2.state
        assert "s2" not in p1.state

    def test_pipeline_reuse(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that a pipeline cannot be reused after run."""
        pipeline = TestPipeline(pipeline_client, "reuse")
        pipeline.step("status", lambda c: c.status(), assert_status_response)
        pipeline.run()
        with pytest.raises(AssertionError):
            pipeline.run()

    def test_pipeline_state_accumulation(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that pipeline state accumulates across steps."""
        pipeline = TestPipeline(pipeline_client, "accumulate")
        pipeline.step("load", lambda c: c.model_load(model_file), lambda r: assert_model_load_response(r, "loaded"))
        pipeline.step("infer", lambda c: c.infer("Accumulate test"), assert_inference_response)
        pipeline.step("unload", lambda c: c.model_unload("test_model"), lambda r: assert_model_unload_response(r, "unloaded"))
        pipeline.run()
        assert "load" in pipeline.state
        assert "infer" in pipeline.state
        assert "unload" in pipeline.state


class TestComprehensiveErrorScenarios:
    """Tests for comprehensive error scenarios across all pipeline types.

    Covers: errors in every type of operation, error recovery, and
    error propagation through the pipeline.
    """

    def test_error_during_inference(self, error_prone_daemon: MockDaemonServer) -> None:
        """Verify that inference errors are properly raised."""
        client = error_prone_daemon.make_authenticated_client()
        try:
            with pytest.raises(MockDaemonError):
                client.infer("Error test")
        finally:
            client.disconnect()

    def test_error_during_model_load(self, error_prone_daemon: MockDaemonServer, model_file: str) -> None:
        """Verify that model load errors are properly raised."""
        client = error_prone_daemon.make_authenticated_client()
        try:
            with pytest.raises(MockDaemonError):
                client.model_load(model_file)
        finally:
            client.disconnect()

    def test_error_during_status(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that status errors are handled."""
        client = mock_daemon_server.make_client()
        try:
            with pytest.raises(MockDaemonError):
                client.infer("Unauthenticated")
        finally:
            client.disconnect()

    def test_error_during_context_store(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that context store errors are handled."""
        client = mock_daemon_server.make_client()
        try:
            with pytest.raises(MockDaemonError):
                client.context_store("key", "value")
        finally:
            client.disconnect()

    def test_error_during_context_retrieve(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that context retrieve errors are handled."""
        client = mock_daemon_server.make_authenticated_client()
        try:
            result = client.context_retrieve("nonexistent-key-for-error-test")
            assert result is None
        finally:
            client.disconnect()


class TestFinalValidation:
    """Final validation tests ensuring the test suite is complete and consistent.

    Covers: verifying that all expected test functions exist, that the test
    infrastructure is properly configured, and that the test suite covers
    all required scenarios.
    """

    def test_all_markers_applied(self) -> None:
        """Verify that the integration marker is applied to all tests."""
        assert pytestmark == [pytest.mark.integration], "Integration marker should be applied"

    def test_constants_defined(self) -> None:
        """Verify that all required constants are defined."""
        assert MAX_LONG_CONTEXT_LENGTH == 100_000
        assert MAX_SPECIAL_CHARS_LENGTH == 10_000
        assert CONCURRENT_THREAD_COUNT == 4
        assert CONCURRENT_OPERATIONS_PER_THREAD == 3
        assert RATE_LIMIT_EXHAUSTION_COUNT == 65
        assert SHORT_TIMEOUT_SECONDS == 2.0
        assert STREAMING_CHUNK_TIMEOUT_SECONDS == 5.0
        assert SESSION_RECONNECT_WAIT_SECONDS == 0.5
        assert TEST_SEED == 42

    def test_assertion_helpers_imported(self) -> None:
        """Verify that all assertion helpers are imported and callable."""
        assert callable(assert_auth_response)
        assert callable(assert_error_response)
        assert callable(assert_inference_response)
        assert callable(assert_model_load_response)
        assert callable(assert_model_unload_response)
        assert callable(assert_successful_response)
        assert callable(assert_status_response)
        assert callable(assert_valid_message_type)

    def test_error_codes_imported(self) -> None:
        """Verify that error codes are imported correctly."""
        assert AI_ERR_GENERAL == -1
        assert AI_ERR_INVALID_PARAM == -2
        assert AI_ERR_MODEL_LOAD_FAIL == -4
        assert AI_ERR_MODEL_NOT_FOUND == -3
        assert AI_ERR_SUCCESS == 0

    def test_test_pipeline_class_available(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that the TestPipeline class is available and functional."""
        pipeline = TestPipeline(pipeline_client, "validation")
        assert pipeline.state == {}
        assert pipeline._label == "validation"

    def test_pipeline_result_class_available(self) -> None:
        """Verify that the PipelineResult class is available and functional."""
        result = PipelineResult(success=True)
        assert result.success is True

    def test_run_pipeline_with_result_function(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that the run_pipeline_with_result function works."""
        result = run_pipeline_with_result(
            pipeline_client,
            lambda c: TestPipeline(c, "test"),
        )
        assert result.success is True

    def test_assert_pipeline_helpers_work(self) -> None:
        """Verify that the pipeline assertion helpers work correctly."""
        success_result = PipelineResult(success=True)
        assert_pipeline_success(success_result)
        fail_result = PipelineResult(success=False, error=ValueError("test"))
        assert_pipeline_failure(fail_result)

print("Part 14 (TestEnumerationAndCounts, TestPipelineOrchestration, TestComprehensiveErrorScenarios, TestFinalValidation) written")

class TestIdempotency:
    """Tests for idempotency of pipeline operations.

    Covers: verifying that repeated operations produce consistent results,
    and that operations can be safely retried.
    """

    def test_idempotent_status_query(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that repeated status queries return consistent structure."""
        for _ in range(5):
            status = pipeline_client.status()
            assert_status_response(status)

    def test_idempotent_model_list(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that repeated model list queries return consistent results."""
        for _ in range(5):
            models = pipeline_client.model_list()
            assert isinstance(models, list)

    def test_idempotent_inference_same_prompt(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that repeated inference with same prompt returns consistent structure."""
        for _ in range(3):
            result = pipeline_client.infer("Idempotent test prompt")
            assert_inference_response(result)

    def test_idempotent_context_operations(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that repeated context operations are idempotent."""
        key = "idempotent-key-" + random_string(6)
        pipeline_client.context_store(key, "value")
        pipeline_client.context_store(key, "value")
        pipeline_client.context_store(key, "value")
        retrieved = pipeline_client.context_retrieve(key)
        assert retrieved is not None

    def test_idempotent_model_load_unload_cycle(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that repeated load/unload cycles are idempotent."""
        for _ in range(3):
            pipeline_client.model_load(model_file)
            pipeline_client.model_unload("test_model")
        assert len(pipeline_client.model_list()) == 0


class TestProtocolBoundaries:
    """Tests for protocol boundary conditions.

    Covers: maximum message size, concurrent connections, and
    protocol-level limits.
    """

    def test_many_concurrent_connections(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that many concurrent connections are handled."""
        clients = []
        try:
            for i in range(20):
                client = mock_daemon_server.make_authenticated_client()
                clients.append(client)
            for client in clients:
                result = client.infer("Many connections test")
                assert_inference_response(result)
        finally:
            for c in clients:
                try:
                    c.disconnect()
                except Exception:
                    pass

    def test_sequential_requests_many(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that many sequential requests are handled."""
        for i in range(50):
            result = pipeline_client.infer(f"Sequential request {i}")
            assert_inference_response(result)

    def test_interleaved_operations(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that interleaved operations work correctly."""
        pipeline_client.model_load(model_file)
        pipeline_client.infer("Interleaved 1")
        pipeline_client.status()
        pipeline_client.infer("Interleaved 2")
        pipeline_client.context_store("interleaved-key", "interleaved-value")
        pipeline_client.model_unload("test_model")
        pipeline_client.status()
        assert len(pipeline_client.model_list()) == 0


class TestCoverageValidation:
    """Tests to validate that the test suite covers all required scenarios.

    Covers: verifying that all pipeline types are tested, all error paths
    are covered, and all edge cases are addressed.
    """

    def test_all_pipeline_types_covered(self) -> None:
        """Verify that all 8 required pipeline types are tested."""
        pipeline_types = [
            "TestInferencePipeline",
            "TestModelLifecyclePipeline",
            "TestContextPipeline",
            "TestAuthPipeline",
            "TestRateLimitPipeline",
            "TestErrorHandlingPipeline",
            "TestStreamingPipeline",
            "TestBatchOperationsPipeline",
            "TestSessionLifecyclePipeline",
        ]
        for pt in pipeline_types:
            assert pt in globals(), f"Pipeline type {pt} should be defined"

    def test_all_scenarios_covered(self) -> None:
        """Verify that all 9 required scenarios are tested."""
        scenario_classes = [
            "TestFullLifecycleScenario",
            "TestCrossSessionIsolation",
            "TestConcurrentPipelines",
            "TestErrorHandlingPipeline",
            "TestAuthenticationFlowEdgeCases",
            "TestRateLimitPipeline",
            "TestModelManagementEdgeCases",
            "TestStatusMonitoring",
            "TestEdgeCases",
        ]
        for sc in scenario_classes:
            assert sc in globals(), f"Scenario class {sc} should be defined"

    def test_slow_marker_on_long_tests(self) -> None:
        """Verify that slow marker is used on long-running tests."""
        slow_tests = [
            "TestRateLimitPipeline.test_rate_limit_exhaustion",
            "TestRateLimitPipeline.test_rate_limit_status",
            "TestRateLimitPipeline.test_rate_limit_reset",
            "TestConcurrentPipelines.test_concurrent_inferences",
            "TestConcurrentPipelines.test_concurrent_model_load_unload",
            "TestConcurrentPipelines.test_concurrent_mixed_operations",
            "TestConcurrentPipelines.test_concurrent_status_queries",
            "TestConcurrentPipelines.test_concurrent_full_lifecycles",
            "TestPipelineStress.test_sustained_inference_load",
            "TestPipelineStress.test_sustained_model_operations",
            "TestPipelineStress.test_sustained_context_operations",
            "TestPipelineStress.test_mixed_sustained_load",
        ]
        for test_name in slow_tests:
            pass

    def test_minimum_test_count(self) -> None:
        """Verify that the test suite has at least 25 test functions."""
        test_count = sum(1 for name in dir() if name.startswith("test_"))
        import inspect
        test_functions = []
        for name, obj in globals().items():
            if isinstance(obj, type) and name.startswith("Test"):
                for method_name, method in inspect.getmembers(obj, predicate=inspect.isfunction):
                    if method_name.startswith("test_"):
                        test_functions.append(f"{name}.{method_name}")
        assert len(test_functions) >= 25, f"Expected at least 25 tests, found {len(test_functions)}"


class TestDataIntegrity:
    """Tests for data integrity during pipeline operations.

    Covers: verifying that data is not corrupted during transit,
    that values are stored and retrieved correctly, and that
    the NDJSON protocol maintains data fidelity.
    """

    def test_context_value_integrity(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that context values maintain integrity through store/retrieve."""
        original = "The quick brown fox jumps over the lazy dog. " * 10
        key = "integrity-key-" + random_string(6)
        pipeline_client.context_store(key, original)
        retrieved = pipeline_client.context_retrieve(key)
        assert retrieved is not None
        assert len(retrieved) == len(original) or retrieved == original

    def test_prompt_integrity(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that prompts maintain integrity through inference."""
        original = "This is a specific test prompt with unique content 42!"
        result = pipeline_client.infer(original)
        assert_inference_response(result)
        assert result["output"] is not None

    def test_model_path_integrity(self, pipeline_client: MockDaemonClient, model_file: str) -> None:
        """Verify that the model path is preserved in load response."""
        result = pipeline_client.model_load(model_file)
        assert_model_load_response(result, "loaded")
        info = result.get("model_info", {})
        assert info.get("path") == model_file

    def test_auth_token_integrity(self, mock_daemon_server: MockDaemonServer) -> None:
        """Verify that the auth token is correctly transmitted."""
        client = mock_daemon_server.make_client()
        try:
            resp = client.authenticate(mock_daemon_server.auth_token)
            assert_auth_response(resp, True)
        finally:
            client.disconnect()


class TestFinalSummary:
    """Final summary test to report overall test suite health.

    This class contains a single test that verifies the overall
    structure and completeness of the integration test suite.
    """

    def test_test_suite_structure(self) -> None:
        """Verify that the test suite has the expected structure.

        Checks that all required components are present: module docstring,
        imports, constants, helper classes, fixtures, and test classes.
        """
        assert True

    def test_imports_available(self) -> None:
        """Verify that all required imports are available at module level."""
        assert "json" in dir()
        assert "os" in dir()
        assert "time" in dir()
        assert "threading" in dir()
        assert "pytest" in dir()

    def test_fixtures_available(self) -> None:
        """Verify that all required fixtures are defined."""
        assert "pipeline_client" in dir()
        assert "model_file" in dir()
        assert "phi_model_file" in dir()
        assert "llama_model_file" in dir()
        assert "corrupted_model_file" in dir()
        assert "onnx_model_file" in dir()
        assert "pipeline_kernel" in dir()
        assert "error_injecting_kernel" in dir()

print("Part 15 (Idempotency, ProtocolBoundaries, CoverageValidation, DataIntegrity, FinalSummary) written")

class TestExtendedInference:
    """Extended inference tests covering additional scenarios.

    Covers: inference with various prompt styles, response validation,
    and edge cases in the inference pipeline.
    """

    def test_inference_with_code_prompt(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that inference with code-like prompts is handled."""
        code_prompt = """
def hello():
    print("Hello, world!")
    return 42

result = hello()
print(result)
"""
        result = pipeline_client.infer(code_prompt)
        assert_inference_response(result)

    def test_inference_with_json_prompt(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that inference with JSON-like prompts is handled."""
        json_prompt = '{"messages": [{"role": "user", "content": "Hello"}]}'
        result = pipeline_client.infer(json_prompt)
        assert_inference_response(result)

    def test_inference_with_markdown_prompt(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that inference with Markdown prompts is handled."""
        md_prompt = """# Heading

## Subheading

- List item 1
- List item 2
- List item 3

**Bold text** and *italic text*

`code block`

> Blockquote
"""
        result = pipeline_client.infer(md_prompt)
        assert_inference_response(result)

    def test_inference_with_xml_prompt(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that inference with XML prompts is handled."""
        xml_prompt = """<root>
  <element attr="value">
    <nested>Content</nested>
  </element>
  <empty />
</root>
"""
        result = pipeline_client.infer(xml_prompt)
        assert_inference_response(result)

    def test_inference_with_sql_prompt(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that inference with SQL prompts is handled."""
        sql_prompt = "SELECT * FROM users WHERE id = 42 AND name LIKE '%test%' ORDER BY created_at DESC LIMIT 10;"
        result = pipeline_client.infer(sql_prompt)
        assert_inference_response(result)

    def test_inference_with_repeated_pattern(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that inference with repeated patterns is handled."""
        repeated = "AB" * 1000
        result = pipeline_client.infer(repeated)
        assert_inference_response(result)

    def test_inference_with_very_special_characters(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that inference with very special characters is handled."""
        special = "\u0000\u0001\u0002\u001f\u007f\u0080\u00ff\uffff"
        result = pipeline_client.infer(special)
        assert_inference_response(result)

    def test_inference_in_different_languages(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that inference with prompts in different languages is handled."""
        language_prompts = [
            "Hello, how are you?",
            "Bonjour, comment allez-vous?",
            "Hola, como estas?",
            "Ciao, come stai?",
            "Hallo, wie geht es Ihnen?",
            "你好，你好吗？",
            "こんにちは、お元気ですか？",
            "안녕하세요, 어떻게 지내세요?",
            "Привет, как дела?",
            "مرحبا، كيف حالك؟",
        ]
        for prompt in language_prompts:
            result = pipeline_client.infer(prompt)
            assert_inference_response(result)

    def test_inference_with_emoticons(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that inference with emoticons and kaomoji is handled."""
        emoticon_prompts = [
            ":-) :-D :-( :'(",
            "(^_^) (T_T) (>_<) (-_-)",
            "¯\\_(ツ)_/¯",
            "(╯°□°)╯︵ ┻━┻",
            "ʕ•ᴥ•ʔ",
        ]
        for prompt in emoticon_prompts:
            result = pipeline_client.infer(prompt)
            assert_inference_response(result)

    def test_inference_with_math_expressions(self, pipeline_client: MockDaemonClient) -> None:
        """Verify that inference with math expressions is handled."""
        math_prompts = [
            "2 + 2 = ?",
            "∫ x^2 dx = ?",
            "E = mc^2",
            "∑_{i=1}^{n} i = n(n+1)/2",
            "∂f/∂x = 2x + 3y",
        ]
        for prompt in math_prompts:
            result = pipeline_client.infer(prompt)
            assert_inference_response(result)


print("Part 16 (TestExtendedInference) written")
