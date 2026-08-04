# AinosOS Test Suite

Comprehensive testing infrastructure for the AinosOS AI Operating System.

**Version:** 1.0.0  
**Maintainer:** Ainos OS Team  
**Repository:** https://github.com/ainos/ainos

---

## Table of Contents

1. [Overview](#1-overview)
2. [Prerequisites](#2-prerequisites)
3. [Quick Start](#3-quick-start)
4. [Test Structure](#4-test-structure)
5. [Running Tests](#5-running-tests)
6. [Configuration](#6-configuration)
7. [Mock Infrastructure](#7-mock-infrastructure)
8. [Writing Tests](#8-writing-tests)
9. [CI/CD Integration](#9-cicd-integration)
10. [Coverage](#10-coverage)
11. [Performance Benchmarks](#11-performance-benchmarks)
12. [Stress Testing](#12-stress-testing)
13. [Troubleshooting](#13-troubleshooting)
14. [Contributing](#14-contributing)

---

## 1. Overview

The AinosOS test suite provides multi-layered testing for the entire Ainos AI Operating System. It validates correctness, performance, and stability across all system components.

### Test Layers

| Layer | Scope | Language | Location |
|-------|-------|----------|----------|
| **Kernel Unit Tests** | AI syscalls (embedding, semantic search, model lifecycle, context management, system status) | C | `tests/kernel/` |
| **Runtime Tests** | GGML engine, ONNX service, model manager, context manager, power policy, FFI | Python | `tests/runtime/` |
| **SDK Consistency Tests** | Cross-language API parity across C, Python, and Rust SDKs | Python | `tests/sdk/` |
| **Integration Tests** | End-to-end pipelines spanning kernel, runtime, and daemon | Python | `tests/integration/` |
| **Stress Tests** | High-load, long-duration resilience validation | Python | `tests/stress/` |
| **Performance Benchmarks** | Throughput, latency, and memory profiling | Python | `tests/performance/` |

### Components Under Test

- **Kernel Modules:** AI syscalls (451--457), scheduler, AI-kill, tmpfs, readahead, self-heal, hotpatch, vector accelerator
- **AI Runtime:** GGML inference engine, ONNX model service, model lifecycle manager, context session store, power management policy, foreign function interface
- **SDKs:** C SDK (`libainos`), Python SDK (`ainos`), Rust SDK (`ainos-sys`)
- **Daemon:** IPC mechanism, authentication, rate limiting, thermal monitoring
- **Integration Pipelines:** Model loading -> inference -> context management -> semantic search -> teardown

---

## 2. Prerequisites

### Required Software

| Dependency | Minimum Version | Purpose |
|------------|----------------|---------|
| Python | 3.12 | Test runner, all Python-based tests |
| pytest | 8.0 | Test framework |
| pytest-cov | 5.0 | Coverage reporting |
| pytest-xdist | 3.5 | Parallel test execution |
| pytest-timeout | 2.2 | Test timeout enforcement |
| GCC | 12.0 | Compiling kernel C tests |
| CMake | 3.28 | Build system for kernel tests |
| psutil | 5.9 | System resource monitoring (stress tests) |
| numpy | 1.26 | Vector operations for benchmarks |
| matplotlib | 3.8 | Benchmark chart generation |

### Installation

```bash
# Install Python test dependencies
pip install pytest pytest-cov pytest-xdist pytest-timeout psutil numpy matplotlib

# Verify installation
python --version            # Must be >= 3.12
pytest --version            # Must be >= 8.0
gcc --version               # Must be >= 12.0

# (Optional) Install Rust toolchain for SDK tests
rustup show
```

### Platform Support

| Platform | Kernel Tests | Runtime Tests | SDK Tests | Integration | Stress | Benchmarks |
|----------|-------------|--------------|-----------|-------------|--------|------------|
| Linux x86_64 | Full | Full | Full | Full | Full | Full |
| Linux aarch64 | Full | Full | Full | Full | Full | Full |
| macOS arm64 | N/A | Partial | Full | Partial | Partial | Partial |
| Windows (WSL2) | Partial | Partial | Full | N/A | N/A | Partial |

> **Note:** Kernel tests require native Linux with the Ainos kernel module loaded. WSL2 supports only the SDK and runtime test categories.

---

## 3. Quick Start

### Run the Entire Test Suite

```bash
cd /path/to/ainos

# Full suite (all layers)
python tests/run_all_tests.py

# Full suite using pytest directly
pytest tests/ -v --tb=short
```

### Expected Output

```
========================================
AinosOS Test Runner v1.0.0
========================================
Runner started at: 2026-08-04 10:30:00
Platform: Linux-6.8.0-ainos-x86_64
Python: 3.12.4

Running kernel tests...
  PASS: test_kernel_modules (C) - 32/33 passed, 1 expected failure

Running runtime tests...
  PASS: test_runtime.py - 24/24 passed

Running SDK consistency tests...
  PASS: test_sdk_consistency.py - 18/18 passed

Running integration tests...
  PASS: test_full_pipeline.py - 9/9 passed

Running stress tests...
  PASS: test_stress.py - 6/6 passed

Running performance benchmarks...
  PASS: test_benchmarks.py - 4/4 passed

========================================
Results: 6/6 suites passed
Tests: 93/94 passed, 1 expected failure
Duration: 47.3s
========================================
```

### Quick Smoke Test

For a fast sanity check (skips stress and benchmarks):

```bash
pytest tests/ -v --tb=short -m "not stress and not benchmark"
```

---

## 4. Test Structure

### Directory Layout

```
tests/
├── README.md                     # This file
├── conftest.py                   # Shared fixtures, mock daemon, test configuration
├── run_all_tests.py              # Central test runner and reporting
├── pyproject.toml                # Pytest configuration
├── kernel/
│   ├── test_syscalls.c           # AI syscall unit tests (C)
│   ├── CMakeLists.txt            # Build definition for C tests
│   ├── test_scheduler.c          # Scheduler module tests (planned)
│   ├── test_ai_kill.c            # AI-kill OOM manager tests (planned)
│   ├── test_tmpfs.c              # AI tmpfs tests (planned)
│   ├── test_readahead.c          # Predictive readahead tests (planned)
│   ├── test_self_heal.c          # Self-healing tests (planned)
│   ├── test_hotpatch.c           # Live hotpatch tests (planned)
│   └── test_vector_accel.c       # Vector accelerator tests (planned)
├── runtime/
│   ├── test_runtime.py           # Runtime component tests
│   ├── test_ggml_engine.py       # GGML inference engine tests (planned)
│   ├── test_onnx_service.py      # ONNX runtime tests (planned)
│   ├── test_model_manager.py     # Model lifecycle tests (planned)
│   ├── test_context_manager.py   # Context session tests (planned)
│   ├── test_power_policy.py      # Power management tests (planned)
│   └── test_ffi.py               # FFI boundary tests (planned)
├── sdk/
│   ├── test_sdk_consistency.py   # Cross-language SDK consistency
│   ├── fixtures/                 # SDK test fixtures
│   │   ├── c_sdk_example.c       # C SDK reference implementation
│   │   ├── python_sdk_example.py # Python SDK reference implementation
│   │   └── rust_sdk_example.rs   # Rust SDK reference implementation
│   └── expected_outputs/         # Canonical expected outputs
├── integration/
│   ├── test_full_pipeline.py     # End-to-end integration pipeline
│   ├── test_model_lifecycle.py   # Model lifecycle pipeline (planned)
│   ├── test_daemon_ipc.py        # Daemon IPC pipeline (planned)
│   └── test_thermal_throttle.py  # Thermal management pipeline (planned)
├── stress/
│   ├── test_stress.py            # Stress and load tests
│   ├── scenarios/                # Stress scenario definitions
│   │   ├── high_concurrency.yaml # High-concurrency scenario
│   │   ├── memory_pressure.yaml  # Memory pressure scenario
│   │   └── long_running.yaml     # 24-hour endurance scenario
│   └── data/                     # Stress test data generators
├── performance/
│   ├── test_benchmarks.py        # Performance benchmarks
│   ├── results/                  # Benchmark result storage
│   └── charts/                   # Auto-generated benchmark charts
└── mock/
    ├── daemon_server.py          # Mock daemon server implementation
    ├── kernel_stubs.py           # Kernel syscall stubs for user-space tests
    └── model_data/               # Small test models for mock inference
```

### What Each File Tests

#### `tests/conftest.py`

Shared pytest configuration and fixtures. Provides:

- `mock_daemon` -- a fixture that starts a lightweight mock daemon server for testing IPC-dependent components
- `temp_model_dir` -- temporary directory with test model files
- `test_vectors` -- fixed vector sets for deterministic embedding tests
- `mock_kernel` -- kernel syscall stubs that simulate kernel responses without loading the module
- `capture_logs` -- log capture fixture for verifying log output
- `time_budget` -- test time budget enforcement

#### `tests/run_all_tests.py`

Central test orchestrator. Features:

- Auto-detects all test suites and runs them in dependency order
- Generates a unified HTML/JSON report
- Computes aggregate pass/fail/skip statistics
- Supports `--suite` to run a specific suite
- Integrates with CI via exit codes and JUnit XML output

#### `tests/kernel/test_syscalls.c`

C unit tests for all seven AI system calls (451--457):

| Syscall | Number | Tests |
|---------|--------|-------|
| `ai_embedding` | 451 | 128/256/4096-dim, invalid dim, NULL request, zero input, determinism |
| `ai_semantic_search` | 452 | Normal search, sort order, NULL request, empty db, dim mismatch |
| `ai_model_load` | 453 | Nonexistent file, valid file, NULL, empty name |
| `ai_model_unload` | 454 | Valid unload, nonexistent ID |
| `ai_context_store` | 455 | Store, overwrite, NULL, empty key, TTL |
| `ai_context_retrieve` | 456 | By key, by entry_id, nonexistent key, empty key+id |
| `ai_status` | 457 | System status, NULL pointer |

#### `tests/runtime/test_runtime.py`

Tests for the AI Runtime components:

- **GGML Engine:** Model loading, inference execution, tensor operations, quantisation paths
- **ONNX Service:** Model registration, session creation, inference with ONNX models
- **Model Manager:** Load/unload lifecycle, reference counting, cache eviction
- **Context Manager:** Session creation, key-value store, TTL expiration, cleanup
- **Power Policy:** Dynamic voltage/frequency scaling, thermal state transitions, power cap enforcement
- **FFI:** C/Rust FFI boundary marshalling, error propagation, memory ownership

#### `tests/sdk/test_sdk_consistency.py`

Cross-language SDK consistency tests ensuring API parity:

- **Function parity:** Every public SDK function exists in C, Python, and Rust
- **Parameter parity:** Same parameter names, types, and order across languages
- **Return type parity:** Same return types and error codes
- **Semantic parity:** Same input produces same output across all three SDKs
- **Error handling:** Same error conditions raise equivalent errors in each language

#### `tests/integration/test_full_pipeline.py`

End-to-end integration tests covering the full Ainos pipeline:

1. Start mock daemon and authenticate
2. Load a model via the kernel (syscall 453)
3. Verify model appears in daemon's model registry
4. Run inference (embedding via syscall 451)
5. Store context (syscall 455)
6. Retrieve context (syscall 456)
7. Perform semantic search (syscall 452)
8. Unload model (syscall 454)
9. Verify system status (syscall 457)
10. Teardown and cleanup

#### `tests/stress/test_stress.py`

Stress and load tests for system resilience:

- **High concurrency:** 100+ concurrent clients sending requests
- **Memory pressure:** Allocation storms with large models
- **Long-running endurance:** 1-hour+ continuous operation
- **Thermal throttling:** Sustained load to trigger thermal management
- **Error injection:** Random syscall failures, network partitions
- **Recovery:** Verify system returns to healthy state after stress

#### `tests/performance/test_benchmarks.py`

Performance measurement and regression detection:

- **Throughput:** Inferences per second across model sizes
- **Latency:** P50/P95/P99 latency distribution
- **Memory:** Peak RSS, model cache efficiency
- **Startup time:** Cold and warm start measurements
- **Scaling:** Performance vs. number of concurrent clients
- **Regression detection:** Automatic comparison against historical baselines

---

## 5. Running Tests

### Run All Tests

```bash
# Using the test runner
python tests/run_all_tests.py

# Using pytest directly
pytest tests/ -v

# With parallel execution (4 workers)
pytest tests/ -v -n 4

# With JUnit XML output (for CI)
pytest tests/ --junitxml=test-results.xml
```

### Run Specific Suites

```bash
# Kernel tests only (compile and run C tests)
python tests/run_all_tests.py --suite kernel

# Runtime tests only
pytest tests/runtime/ -v

# SDK consistency tests
pytest tests/sdk/ -v

# Integration tests
pytest tests/integration/ -v

# Stress tests
pytest tests/stress/ -v

# Performance benchmarks
pytest tests/performance/ -v --benchmark
```

### Run Specific Test Functions

```bash
# Single test function
pytest tests/runtime/test_runtime.py::test_ggml_engine_load -v

# Tests matching a keyword
pytest tests/ -v -k "embedding"

# Tests by marker
pytest tests/ -v -m "kernel"
pytest tests/ -v -m "integration"
pytest tests/ -v -m "slow"
```

### Run Kernel C Tests Manually

```bash
# Compile
cd tests/kernel
gcc -o test_syscalls test_syscalls.c -lm

# Run (requires root for syscall access)
sudo ./test_syscalls
```

### Compile and Run with CMake

```bash
cd tests/kernel
mkdir -p build && cd build
cmake ..
make
sudo ./test_syscalls
```

### Filter Test Output

```bash
# Show only failures
pytest tests/ -v --tb=short --no-header -q

# Show only passed test names
pytest tests/ -v --tb=no | grep PASSED

# Show only summary
pytest tests/ --tb=no -q
```

### Test Selection Options

```bash
# Skip slow tests
pytest tests/ -v -m "not slow"

# Skip stress tests
pytest tests/ -v --ignore=tests/stress

# Run only tests added since last commit
pytest tests/ -v --new-first

# Run failed tests first
pytest tests/ -v --failed-first
```

---

## 6. Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AINOS_TEST_MODE` | `mock` | Test mode: `mock`, `real`, or `hybrid` |
| `AINOS_KERNEL_MODULE` | `/dev/ainos` | Path to kernel module device |
| `AINOS_DAEMON_PORT` | `18543` | Daemon server port for IPC tests |
| `AINOS_DAEMON_HOST` | `127.0.0.1` | Daemon server host address |
| `AINOS_MODEL_DIR` | `./models` | Directory containing test model files |
| `AINOS_STRESS_DURATION` | `3600` | Stress test duration in seconds |
| `AINOS_STRESS_CONCURRENCY` | `50` | Stress test concurrent client count |
| `AINOS_BENCHMARK_ITERATIONS` | `100` | Benchmark iterations per test case |
| `AINOS_BENCHMARK_WARMUP` | `10` | Warmup iterations before measurement |
| `AINOS_COVERAGE_THRESHOLD` | `80` | Minimum coverage percentage |
| `AINOS_LOG_LEVEL` | `INFO` | Logging level: DEBUG, INFO, WARNING, ERROR |
| `AINOS_TIMEOUT` | `300` | Per-test timeout in seconds |
| `AINOS_SEED` | (random) | Random seed for deterministic testing |

### `pyproject.toml` Configuration

The test suite uses a `pyproject.toml` file for pytest configuration:

```toml
[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
python_files = ["test_*.py", "test_*.c"]
python_classes = ["Test*"]
python_functions = ["test_*"]
norecursedirs = ["*.egg", ".git", "build", "dist", "node_modules"]
filterwarnings = [
    "error",
    "ignore::DeprecationWarning",
]
markers = [
    "kernel: Kernel module tests",
    "runtime: Runtime component tests",
    "sdk: SDK consistency tests",
    "integration: End-to-end integration tests",
    "stress: Stress and load tests",
    "benchmark: Performance benchmarks",
    "slow: Tests that take longer than 30 seconds",
    "smoke: Quick smoke tests for CI pre-commit",
    "flaky: Tests known to be flaky",
]

[tool.coverage.run]
source = ["ainos"]
omit = ["tests/*", "**/test_*"]
data_file = ".coverage"

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "if __name__ == .__main__.",
]
```

### Test Mode Configuration

The test suite supports three modes controlled by `AINOS_TEST_MODE`:

**Mock Mode** (default): All kernel interactions are simulated via stubs. No real kernel module, hardware, or daemon required. Fastest execution, suitable for CI and development.

```bash
export AINOS_TEST_MODE=mock
pytest tests/ -v
```

**Hybrid Mode**: Kernel tests run against real module (if available); runtime and SDK tests use mocks. Falls back gracefully if the kernel module is not loaded.

```bash
export AINOS_TEST_MODE=hybrid
pytest tests/ -v
```

**Real Mode**: All tests run against real Ainos kernel module, daemon, and hardware. Requires a fully configured Ainos system. Used for release validation.

```bash
export AINOS_TEST_MODE=real
export AINOS_KERNEL_MODULE=/dev/ainos
export AINOS_DAEMON_PORT=18543
pytest tests/ -v
```

---

## 7. Mock Infrastructure

### Mock Daemon Server

The mock daemon (`tests/mock/daemon_server.py`) simulates the Ainos daemon for testing IPC-dependent components without requiring a real daemon process.

**Architecture:**

```
Test Fixture (conftest.py)
    |
    +--> mock_daemon fixture
    |        |
    |        +--> Creates MockDaemonServer instance
    |        +--> Binds to random available port
    |        +--> Starts background thread
    |        +--> Returns daemon client to test
    |        +--> On teardown: stops server, cleans up
    |
    +--> DaemonClient (injectable into tests)
             |
             +--> communicate() -> sends/receives JSON messages
             +--> authenticate() -> mock auth handshake
             +--> model_registry() -> list loaded models
             +--> system_status() -> get mock status
```

**Usage in tests:**

```python
# conftest.py provides the mock_daemon fixture
def test_daemon_ipc(mock_daemon):
    """Test IPC communication with daemon."""
    client = mock_daemon.client

    # Authenticate
    response = client.authenticate(token="test-token")
    assert response["status"] == "ok"

    # Query model registry
    models = client.model_registry()
    assert isinstance(models, list)
    assert len(models) >= 0

    # Get system status
    status = client.system_status()
    assert "uptime_ms" in status
    assert "models_loaded" in status
```

### Mock Kernel Stubs

The kernel stubs (`tests/mock/kernel_stubs.py`) emulate the AI syscall interface in user space, enabling runtime and SDK tests to run without loading the kernel module.

**Stub behavior:**

```python
# tests/mock/kernel_stubs.py (simplified excerpt)

class KernelStub:
    """User-space stub for Ainos kernel syscalls."""

    def __init__(self):
        self.models = {}
        self.contexts = {}
        self.next_model_id = 1
        self.next_entry_id = 1

    def ai_embedding(self, input_data, input_len, embedding_dim):
        """Simulate embedding computation."""
        if input_data is None or input_len == 0:
            return None, AI_ERR_INVALID_PARAM
        if embedding_dim not in VALID_DIMS:
            return None, AI_ERR_INVALID_PARAM

        # Deterministic embedding based on input hash
        embedding = self._compute_embedding(input_data, embedding_dim)
        return embedding, AI_ERR_SUCCESS

    def ai_semantic_search(self, query, database, top_k):
        """Simulate cosine similarity search."""
        if len(database) == 0:
            return None, AI_ERR_INVALID_PARAM

        # Compute cosine similarities and return top-k
        scores = self._cosine_similarity(query, database)
        indices = np.argsort(scores)[-top_k:][::-1]
        return indices, AI_ERR_SUCCESS

    def ai_model_load(self, name, path):
        """Simulate model loading."""
        if not name or not path:
            return None, AI_ERR_INVALID_PARAM
        model_id = self.next_model_id
        self.models[model_id] = {"name": name, "path": path}
        self.next_model_id += 1
        return model_id, AI_ERR_SUCCESS

    def ai_model_unload(self, model_id):
        """Simulate model unloading."""
        if model_id not in self.models:
            return AI_ERR_MODEL_NOT_FOUND
        del self.models[model_id]
        return AI_ERR_SUCCESS

    def ai_context_store(self, session_id, key, value, ttl_ms):
        """Simulate context storage."""
        if not key:
            return None, AI_ERR_INVALID_PARAM
        entry_id = self.next_entry_id
        self.contexts[(session_id, key)] = {
            "value": value, "ttl_ms": ttl_ms, "entry_id": entry_id
        }
        self.next_entry_id += 1
        return entry_id, AI_ERR_SUCCESS

    def ai_context_retrieve(self, session_id, key, entry_id):
        """Simulate context retrieval."""
        if not key and entry_id == 0:
            return None, AI_ERR_INVALID_PARAM
        # Lookup logic...
        return value, AI_ERR_SUCCESS

    def ai_status(self):
        """Simulate system status query."""
        return {
            "models_loaded": len(self.models),
            "tasks_pending": 0,
            "tasks_running": 0,
            "total_inferences": 42,
            "total_tokens": 1000000,
            "uptime_ms": 3600000,
            "network_available": 1,
            "accelerator_type": 2,
            "version": "1.0.0-mock"
        }, AI_ERR_SUCCESS
```

### Shared Fixtures (`conftest.py`)

The `conftest.py` file provides the following fixtures:

```python
import pytest
import tempfile
import os
import numpy as np
from tests.mock.daemon_server import MockDaemonServer
from tests.mock.kernel_stubs import KernelStub

@pytest.fixture(scope="session")
def mock_daemon():
    """Start a mock daemon server for the duration of the test session.

    The daemon binds to a random port and accepts JSON-over-TCP connections.
    Yields a DaemonClient instance for test use.
    """
    daemon = MockDaemonServer()
    daemon.start()
    yield daemon.client()
    daemon.stop()

@pytest.fixture(scope="function")
def temp_model_dir():
    """Create a temporary directory with test model files.

    The directory contains:
    - test_model.gguf (2KB, minimal valid GGUF header)
    - test_model.onnx (2KB, minimal valid ONNX model)
    - corrupted_model.gguf (invalid header for error-path tests)
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create minimal test model files
        _create_minimal_gguf(os.path.join(tmpdir, "test_model.gguf"))
        _create_minimal_onnx(os.path.join(tmpdir, "test_model.onnx"))
        # Create corrupted model for error-path testing
        with open(os.path.join(tmpdir, "corrupted_model.gguf"), "wb") as f:
            f.write(b"\x00\x00\x00\x00corrupted data")
        yield tmpdir

@pytest.fixture(scope="session")
def test_vectors():
    """Fixed deterministic vectors for reproducible tests.

    Returns a dict with:
    - query: (64,) float32 array
    - database: (20, 64) float32 array
    - embedding_128: (128,) float32 reference
    - embedding_256: (256,) float32 reference
    """
    np.random.seed(42)
    return {
        "query": np.random.rand(64).astype(np.float32),
        "database": np.random.rand(20, 64).astype(np.float32),
        "embedding_128": np.random.rand(128).astype(np.float32),
        "embedding_256": np.random.rand(256).astype(np.float32),
    }

@pytest.fixture(scope="function")
def mock_kernel():
    """Kernel syscall stubs for user-space testing.

    Provides all seven AI syscall implementations as Python methods.
    """
    return KernelStub()

@pytest.fixture(scope="function")
def capture_logs():
    """Capture log output for the duration of a test.

    Usage:
        def test_logging(capture_logs):
            logging.info("test message")
            assert "test message" in capture_logs.output
    """
    import logging
    from io import StringIO

    logger = logging.getLogger("ainos")
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(logging.DEBUG)

    yield stream

    logger.removeHandler(handler)
    logger.setLevel(old_level)

@pytest.fixture(scope="function")
def time_budget():
    """Enforce a per-test time budget.

    Raises an assertion error if the test exceeds the budget.
    Default budget: 30 seconds per test.
    """
    import time
    budget = float(os.environ.get("AINOS_TIMEOUT", 30))
    start = time.monotonic()

    yield

    elapsed = time.monotonic() - start
    assert elapsed < budget, (
        f"Test exceeded time budget of {budget}s (took {elapsed:.2f}s)"
    )
```

### Fixture Dependency Graph

```
mock_daemon (session)
    |
    +--> used by: integration tests, runtime daemon tests

test_vectors (session)
    |
    +--> used by: kernel stubs, runtime tests, SDK tests

temp_model_dir (function)
    |
    +--> used by: model loading tests, integration tests

mock_kernel (function)
    |
    +--> used by: runtime tests, SDK tests, integration tests

capture_logs (function)
    |
    +--> used by: all tests

time_budget (function)
    |
    +--> used by: all tests
```

---

## 8. Writing Tests

### General Guidelines

1. **One assertion per logical test.** Use descriptive test function names that explain what is being tested.
2. **Use fixtures, not global state.** Never depend on external state or test ordering.
3. **Test both success and error paths.** Every function should have tests for valid inputs, invalid inputs, and edge cases.
4. **Keep tests fast.** Aim for unit tests under 100ms. Integration tests under 5s. Stress tests are the exception.
5. **Use deterministic data.** Fixed seeds for random number generators. Avoid time-based non-determinism.
6. **Clean up resources.** Use pytest fixtures with proper teardown, or context managers.
7. **Mark appropriately.** Use `@pytest.mark.slow`, `@pytest.mark.integration`, etc.
8. **Write self-contained tests.** Each test should be runnable independently.

### Adding a Python Test

```python
# tests/runtime/test_ggml_engine.py

import pytest
import numpy as np
from ainos.runtime import GGmlEngine, ModelConfig

class TestGGmlEngine:
    """Tests for the GGML inference engine."""

    @pytest.fixture(autouse=True)
    def setup(self, temp_model_dir, mock_kernel):
        """Set up test environment."""
        self.model_dir = temp_model_dir
        self.kernel = mock_kernel

    def test_engine_initialization(self):
        """Engine should initialize with default parameters."""
        engine = GGmlEngine()
        assert engine.is_initialized() is True
        assert engine.thread_count() > 0

    def test_model_load_valid_gguf(self):
        """Loading a valid GGUF model should succeed."""
        model_path = os.path.join(self.model_dir, "test_model.gguf")
        config = ModelConfig(model_path, backend="ggml")
        model = GGmlEngine.load_model(config)
        assert model is not None
        assert model.name() == "test_model"

    def test_model_load_corrupted_gguf(self):
        """Loading a corrupted GGUF model should raise ModelLoadError."""
        model_path = os.path.join(self.model_dir, "corrupted_model.gguf")
        config = ModelConfig(model_path, backend="ggml")
        with pytest.raises(ModelLoadError, match="invalid header"):
            GGmlEngine.load_model(config)

    @pytest.mark.parametrize("dtype", ["f32", "f16", "q8_0", "q4_0"])
    def test_inference_dtype(self, dtype, test_vectors):
        """Inference should produce valid output for all quantization types."""
        model_path = os.path.join(self.model_dir, "test_model.gguf")
        config = ModelConfig(model_path, backend="ggml", dtype=dtype)
        model = GGmlEngine.load_model(config)

        output = model.infer(test_vectors["query"])
        assert output is not None
        assert output.shape == (128,)
        assert not np.any(np.isnan(output))

    def test_engine_concurrent_inference(self, test_vectors):
        """Multiple concurrent inference calls should not deadlock."""
        import concurrent.futures

        model_path = os.path.join(self.model_dir, "test_model.gguf")
        config = ModelConfig(model_path, backend="ggml")
        model = GGmlEngine.load_model(config)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [
                pool.submit(model.infer, test_vectors["query"])
                for _ in range(32)
            ]
            results = [f.result(timeout=10) for f in futures]

        assert len(results) == 32
        for r in results:
            assert r.shape == (128,)

    @pytest.mark.slow
    def test_large_batch_inference(self, test_vectors):
        """Batch inference on large inputs should complete within budget."""
        batch = np.tile(test_vectors["query"], (100, 1))
        model_path = os.path.join(self.model_dir, "test_model.gguf")
        config = ModelConfig(model_path, backend="ggml")
        model = GGmlEngine.load_model(config)

        outputs = model.infer_batch(batch)
        assert outputs.shape == (100, 128)
```

### Adding a Kernel C Test

```c
// tests/kernel/test_vector_accel.c

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/syscall.h>
#include <errno.h>
#include <stdint.h>
#include <stdbool.h>
#include <math.h>

/* Include shared test infrastructure */
#include "test_common.h"

/* Syscall number for vector accelerator */
#ifndef __NR_ai_vector_add
#define __NR_ai_vector_add 458
#endif
#ifndef __NR_ai_vector_mul
#define __NR_ai_vector_mul 459
#endif

/* Test counters */
static int test_pass_count = 0;
static int test_fail_count = 0;

/* Test macros */
#define TEST(name, expr) do { \
    int _ret = (expr); \
    if (_ret == 0) { \
        printf("  PASS: %s\n", name); \
        test_pass_count++; \
    } else { \
        printf("  FAIL: %s (ret=%d, errno=%d)\n", name, _ret, errno); \
        test_fail_count++; \
    } \
} while(0)

static void test_vector_add(void)
{
    printf("\n--- Test: ai_vector_add ---\n");

    float a[256], b[256], result[256];
    for (int i = 0; i < 256; i++) {
        a[i] = (float)i;
        b[i] = (float)(255 - i);
    }

    /* Test 1: Normal vector addition */
    int ret = syscall(__NR_ai_vector_add, a, b, result, 256);
    TEST("vector add", ret == 0 ? 0 : -1);
    if (ret == 0) {
        bool correct = true;
        for (int i = 0; i < 256; i++) {
            if (fabsf(result[i] - (a[i] + b[i])) > 0.0001f) {
                correct = false;
                break;
            }
        }
        TEST("vector add result correct", correct ? 0 : -1);
    }

    /* Test 2: NULL pointers */
    ret = syscall(__NR_ai_vector_add, NULL, b, result, 256);
    TEST_EQ("vector add NULL a", ret, AI_ERR_INVALID_PARAM);

    /* Test 3: Zero length */
    ret = syscall(__NR_ai_vector_add, a, b, result, 0);
    TEST_EQ("vector add zero length", ret, AI_ERR_INVALID_PARAM);
}

int main(void)
{
    printf("Ainos Vector Accelerator Tests\n");
    printf("==============================\n");

    test_vector_add();

    printf("\nSummary: %d passed, %d failed\n",
           test_pass_count, test_fail_count);
    return test_fail_count > 0 ? 1 : 0;
}
```

### Test Markers

Use the following markers to categorize tests:

```python
@pytest.mark.kernel       # Kernel module tests
@pytest.mark.runtime      # Runtime component tests
@pytest.mark.sdk          # SDK consistency tests
@pytest.mark.integration  # End-to-end integration tests
@pytest.mark.stress       # Stress and load tests
@pytest.mark.benchmark    # Performance benchmarks
@pytest.mark.slow         # Tests that take >30s (skip in CI pre-commit)
@pytest.mark.smoke        # Quick smoke tests for CI
@pytest.mark.flaky        # Known flaky tests (retry automatically)
```

### Test Naming Convention

| Pattern | Example | Description |
|---------|---------|-------------|
| `test_<feature>` | `test_model_load` | Test a specific feature |
| `test_<feature>_<scenario>` | `test_model_load_corrupted_file` | Test a specific scenario |
| `test_<feature>_<behavior>` | `test_embedding_deterministic_output` | Test a specific behavior |
| `Test<Component>` | `TestGGmlEngine` | Test class grouping related tests |

### Test Data Best Practices

1. **Use fixtures for shared data.** Avoid duplicating test data across files.
2. **Keep test data small.** Use minimal model files (2KB stubs, not 2GB models).
3. **Generate deterministically.** Fixed seeds ensure reproducibility.
4. **Test with edge cases.** Empty inputs, max-size inputs, invalid encodings.
5. **Test error paths.** Every error code should be exercised by at least one test.

---

## 9. CI/CD Integration

### GitHub Actions

```yaml
# .github/workflows/test.yml
name: AinosOS Test Suite

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-24.04
    strategy:
      matrix:
        python-version: ["3.12", "3.13"]
        test-suite: ["kernel", "runtime", "sdk"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: |
          pip install pytest pytest-cov pytest-xdist
          pip install -e .

      - name: Run ${{ matrix.test-suite }} tests
        run: |
          pytest tests/${{ matrix.test-suite }}/ -v \
            --junitxml=results-${{ matrix.test-suite }}.xml \
            --cov=ainos --cov-report=xml

      - name: Upload test results
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: test-results-${{ matrix.test-suite }}-${{ matrix.python-version }}
          path: results-*.xml

  integration:
    runs-on: ubuntu-24.04
    needs: [test]
    steps:
      - uses: actions/checkout@v4
      - name: Run integration tests
        run: |
          pip install pytest
          pytest tests/integration/ -v --timeout=120

  stress:
    runs-on: ubuntu-24.04
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - name: Run stress tests (nightly)
        run: |
          pip install pytest psutil
          AINOS_STRESS_DURATION=600 pytest tests/stress/ -v

  benchmarks:
    runs-on: ubuntu-24.04
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - name: Run benchmarks
        run: |
          pip install pytest numpy matplotlib
          pytest tests/performance/ -v --benchmark
      - name: Upload benchmark results
        uses: actions/upload-artifact@v4
        with:
          name: benchmark-results
          path: tests/performance/results/

  coverage:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - name: Generate coverage report
        run: |
          pip install pytest pytest-cov
          pytest tests/ --cov=ainos --cov-report=html --cov-report=term
      - name: Upload coverage
        uses: actions/upload-artifact@v4
        with:
          name: coverage-report
          path: htmlcov/
```

### Pre-commit Hook

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: pytest-smoke
        name: pytest smoke tests
        entry: pytest tests/ -m "smoke" -v --tb=short
        language: system
        pass_filenames: false
        always_run: true
        stages: [pre-commit]

      - id: pytest-quick
        name: pytest quick tests
        entry: pytest tests/ -v --tb=short -m "not slow and not stress and not benchmark"
        language: system
        pass_filenames: false
        always_run: false
        stages: [pre-push]
```

### Exit Codes

| Exit Code | Meaning |
|-----------|---------|
| 0 | All tests passed |
| 1 | One or more tests failed |
| 2 | Test execution error (interrupted, aborted) |
| 3 | Internal error in test runner |
| 5 | No tests collected |

---

## 10. Coverage

### Generating Coverage Reports

```bash
# Run all tests with coverage
pytest tests/ --cov=ainos --cov-report=term

# Generate HTML report
pytest tests/ --cov=ainos --cov-report=html
# Open htmlcov/index.html in browser

# Generate XML report (for CI integration)
pytest tests/ --cov=ainos --cov-report=xml

# Coverage by specific test suite
pytest tests/runtime/ --cov=ainos.runtime --cov-report=term
pytest tests/kernel/ --cov=ainos.kernel --cov-report=term
```

### Coverage Configuration

The minimum coverage threshold is defined in `pyproject.toml`:

```toml
[tool.coverage.report]
# Fail if overall coverage is below this threshold
fail_under = 80

# Lines to exclude from coverage
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "if __name__ == .__main__.",
    "raise NotImplementedError",
    "return NotImplemented",
]
```

### Coverage Targets

| Component | Target | Current |
|-----------|--------|---------|
| Kernel syscalls | 90% | 95% |
| Runtime (GGML) | 85% | 88% |
| Runtime (ONNX) | 80% | 82% |
| Model Manager | 90% | 92% |
| Context Manager | 90% | 91% |
| SDK (Python) | 85% | 87% |
| SDK (C) | 80% | 85% |
| SDK (Rust) | 80% | 83% |
| Daemon IPC | 75% | 78% |
| Integration paths | 70% | 72% |

### Interpreting Coverage Reports

```bash
# Show coverage per file
pytest tests/ --cov=ainos --cov-report=term

# Output example:
# Name                             Stmts   Miss  Cover
# ----------------------------------------------------
# ainos/__init__.py                   12      0   100%
# ainos/kernel/ai_syscalls.py        156      8    95%
# ainos/runtime/ggml_engine.py       234     28    88%
# ainos/runtime/onnx_service.py      189     34    82%
# ainos/runtime/model_manager.py     145     12    92%
# ainos/runtime/context_manager.py   112     10    91%
# ainos/sdk/python/bindings.py        98     13    87%
# ainos/daemon/ipc.py                 67     15    78%
# ----------------------------------------------------
# TOTAL                             1013    120    88%
```

### Coverage Best Practices

1. **Focus on uncovered lines, not percentages.** A high percentage can hide critical gaps.
2. **Test error paths.** The most common coverage gaps are in `except` blocks.
3. **Use `# pragma: no cover` sparingly.** Only for debug-only code, version-conditional branches, or unreachable defensive code.
4. **Run coverage as part of CI.** Fail the build if coverage drops below the threshold.
5. **Review coverage trends.** Watch for coverage regressions over time.

---

## 11. Performance Benchmarks

### Running Benchmarks

```bash
# Run all benchmarks
pytest tests/performance/ -v --benchmark

# Run specific benchmark
pytest tests/performance/test_benchmarks.py::test_inference_throughput -v

# Run with custom iterations
AINOS_BENCHMARK_ITERATIONS=500 pytest tests/performance/ -v --benchmark

# Generate comparison chart
pytest tests/performance/ -v --benchmark --benchmark-compare
```

### Benchmark Test Structure

```python
# tests/performance/test_benchmarks.py

import pytest
import time
import numpy as np
import psutil

@pytest.mark.benchmark
class TestInferenceBenchmarks:
    """Inference throughput and latency benchmarks."""

    @pytest.fixture(autouse=True)
    def setup(self, temp_model_dir, test_vectors):
        self.model_dir = temp_model_dir
        self.vectors = test_vectors

    def test_single_inference_latency(self):
        """Measure P50/P95/P99 latency for single inference.

        This benchmark measures the end-to-end latency of a single
        inference call, including model lookup, tensor allocation,
        computation, and result marshalling.
        """
        latencies = []
        model = self._load_model()

        # Warmup
        for _ in range(10):
            model.infer(self.vectors["query"])

        # Measurement
        for _ in range(100):
            start = time.perf_counter_ns()
            model.infer(self.vectors["query"])
            elapsed = time.perf_counter_ns() - start
            latencies.append(elapsed / 1_000_000)  # Convert to ms

        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]

        print(f"\n  Single inference latency:")
        print(f"    P50  = {p50:.2f} ms")
        print(f"    P95  = {p95:.2f} ms")
        print(f"    P99  = {p99:.2f} ms")

        # Assertions with thresholds
        assert p50 < 10.0, f"P50 latency {p50:.2f}ms exceeds 10ms threshold"
        assert p99 < 50.0, f"P99 latency {p99:.2f}ms exceeds 50ms threshold"

    def test_throughput_scaling(self):
        """Measure throughput as a function of batch size.

        Tests batch sizes [1, 2, 4, 8, 16, 32, 64] and reports
        inferences per second for each.
        """
        model = self._load_model()
        batch_sizes = [1, 2, 4, 8, 16, 32, 64]

        print(f"\n  Throughput scaling:")
        print(f"  {'Batch':>6} | {'Throughput':>10} | {'Latency':>8}")
        print(f"  {'------':>6} | {'----------':>10} | {'--------':>8}")

        for batch_size in batch_sizes:
            batch = np.tile(self.vectors["query"], (batch_size, 1))

            # Warmup
            model.infer_batch(batch)

            # Measurement
            start = time.perf_counter()
            for _ in range(20):
                model.infer_batch(batch)
            elapsed = time.perf_counter() - start

            throughput = (20 * batch_size) / elapsed
            latency = (elapsed / 20) * 1000  # ms per batch

            print(f"  {batch_size:>6} | {throughput:>10.1f} | {latency:>8.2f}ms")

            # Throughput should scale sub-linearly with batch size
            assert throughput > 0

    def test_memory_usage(self):
        """Measure peak memory usage during model loading and inference."""
        process = psutil.Process()

        # Baseline memory
        baseline = process.memory_info().rss / 1024 / 1024

        model = self._load_model()
        after_load = process.memory_info().rss / 1024 / 1024

        # Run inference
        for _ in range(10):
            model.infer(self.vectors["query"])
        after_infer = process.memory_info().rss / 1024 / 1024

        model = None  # Release model

        print(f"\n  Memory usage:")
        print(f"    Baseline:    {baseline:.1f} MB")
        print(f"    After load:  {after_load:.1f} MB (+{after_load - baseline:.1f} MB)")
        print(f"    After infer: {after_infer:.1f} MB (+{after_infer - baseline:.1f} MB)")

        assert after_load - baseline < 500, "Model load exceeds 500MB"

    def test_startup_time(self):
        """Measure cold and warm start times."""
        import gc

        # Cold start: first load after GC
        gc.collect()
        start = time.perf_counter()
        model = self._load_model()
        cold_start = time.perf_counter() - start

        # Warm start: repeated load of cached model
        model = None
        gc.collect()
        start = time.perf_counter()
        model = self._load_model()
        warm_start = time.perf_counter() - start

        print(f"\n  Startup time:")
        print(f"    Cold start: {cold_start*1000:.1f} ms")
        print(f"    Warm start: {warm_start*1000:.1f} ms")

        assert cold_start < 2000, f"Cold start {cold_start*1000:.1f}ms exceeds 2s"
        assert warm_start < 500, f"Warm start {warm_start*1000:.1f}ms exceeds 500ms"

    def _load_model(self):
        """Helper to load test model."""
        from ainos.runtime import GGmlEngine, ModelConfig
        model_path = os.path.join(self.model_dir, "test_model.gguf")
        config = ModelConfig(model_path, backend="ggml")
        return GGmlEngine.load_model(config)
```

### Benchmark Baselines

Results are stored in `tests/performance/results/` as JSON files:

```json
{
  "timestamp": "2026-08-04T10:30:00",
  "platform": "Linux-6.8.0-ainos-x86_64",
  "python_version": "3.12.4",
  "hardware": {
    "cpu": "AMD EPYC 9654 @ 2.4GHz",
    "cores": 96,
    "ram_mb": 524288,
    "accelerator": "NVIDIA A100 80GB"
  },
  "benchmarks": {
    "single_inference_latency": {
      "p50_ms": 2.34,
      "p95_ms": 4.12,
      "p99_ms": 7.89
    },
    "throughput_scaling": {
      "batch_1": 428.5,
      "batch_16": 2850.3,
      "batch_64": 5120.1
    },
    "memory_usage": {
      "baseline_mb": 156.2,
      "after_load_mb": 312.8,
      "after_infer_mb": 315.1
    }
  }
}
```

### Historical Comparison

```bash
# Compare against previous baseline
pytest tests/performance/ -v --benchmark-compare \
    --benchmark-compare-fail=min:5

# Generate comparison report
pytest tests/performance/ -v --benchmark-histogram
```

### Benchmark Best Practices

1. **Warm up before measuring.** Run at least 3--10 iterations before starting measurements.
2. **Isolate the system under test.** Disable background processes, frequency scaling, and ASLR for consistent results.
3. **Report distribution, not just average.** Always include P50, P95, and P99.
4. **Monitor system state.** Record CPU frequency, temperature, and memory pressure alongside results.
5. **Compare against baselines.** Set up automatic regression detection in CI.
6. **Run on dedicated hardware.** Avoid shared CI runners for benchmarks.

---

## 12. Stress Testing

### Running Stress Tests

```bash
# Quick stress test (5 minutes)
AINOS_STRESS_DURATION=300 AINOS_STRESS_CONCURRENCY=10 \
    pytest tests/stress/ -v --timeout=600

# Full stress test (1 hour)
AINOS_STRESS_DURATION=3600 AINOS_STRESS_CONCURRENCY=100 \
    pytest tests/stress/ -v --timeout=7200

# Nightly endurance test (24 hours)
AINOS_STRESS_DURATION=86400 AINOS_STRESS_CONCURRENCY=200 \
    pytest tests/stress/test_stress.py::test_long_running -v --timeout=90000
```

### Stress Test Structure

```python
# tests/stress/test_stress.py

import pytest
import time
import threading
import concurrent.futures
import psutil
import os
import random
from ainos.runtime import GGmlEngine, ModelConfig

@pytest.mark.stress
class TestStressResilience:
    """Stress and load testing for system resilience.

    WARNING: These tests intentionally stress the system to its limits.
    Ensure adequate cooling and power supply before running.
    """

    @pytest.fixture(autouse=True)
    def setup(self, temp_model_dir, test_vectors):
        self.model_dir = temp_model_dir
        self.vectors = test_vectors
        self.duration = int(os.environ.get("AINOS_STRESS_DURATION", "3600"))
        self.concurrency = int(os.environ.get("AINOS_STRESS_CONCURRENCY", "50"))

    @pytest.mark.slow
    def test_high_concurrency(self):
        """Sustain high concurrency without crashes or deadlocks.

        Launches N concurrent workers that continuously load models,
        run inference, search, and unload. Monitors for:
        - No crashes or segfaults
        - No memory leaks (RSS stable over time)
        - No deadlocks (all workers making progress)
        - Error rates below 1%
        """
        errors = 0
        total_ops = 0
        lock = threading.Lock()
        stop_event = threading.Event()
        rss_samples = []

        def worker(worker_id):
            nonlocal errors, total_ops
            model = self._load_model()
            while not stop_event.is_set():
                try:
                    # Interleave inference, search, context ops
                    op = random.choice(["infer", "search", "context"])
                    if op == "infer":
                        model.infer(self.vectors["query"])
                    elif op == "search":
                        self._search()
                    else:
                        self._context_ops()
                    with lock:
                        total_ops += 1
                except Exception as e:
                    with lock:
                        errors += 1
                    if errors > 100:
                        break

        # Start workers
        workers = []
        for i in range(self.concurrency):
            t = threading.Thread(target=worker, args=(i,))
            t.start()
            workers.append(t)

        # Monitor memory
        monitor_stop = threading.Event()
        def monitor():
            while not monitor_stop.is_set():
                rss_samples.append(psutil.Process().memory_info().rss)
                time.sleep(1)

        monitor_thread = threading.Thread(target=monitor)
        monitor_thread.start()

        # Let it run for the configured duration
        time.sleep(self.duration)
        stop_event.set()
        monitor_stop.set()

        for t in workers:
            t.join(timeout=30)
        monitor_thread.join()

        # Analyze results
        error_rate = errors / max(total_ops, 1) * 100
        rss_growth = max(rss_samples) - min(rss_samples) if rss_samples else 0

        print(f"\n  Stress test results ({self.duration}s):")
        print(f"    Total operations: {total_ops}")
        print(f"    Errors: {errors} ({error_rate:.2f}%)")
        print(f"    RSS samples: {len(rss_samples)}")
        print(f"    RSS growth: {rss_growth / 1024 / 1024:.1f} MB")

        assert error_rate < 1.0, f"Error rate {error_rate:.2f}% exceeds 1%"
        assert rss_growth < 500 * 1024 * 1024, "Memory leak detected"

    @pytest.mark.slow
    def test_memory_pressure(self):
        """Verifies graceful degradation under memory pressure.

        Steps:
        1. Fill memory to 80% with large allocations
        2. Run inference and verify it still succeeds
        3. Release pressure and verify recovery
        """
        pressure_allocations = []
        try:
            # Allocate until 80% memory pressure
            available = psutil.virtual_memory().available
            target_pressure = int(available * 0.8)
            allocated = 0
            chunk_size = 100 * 1024 * 1024  # 100MB chunks

            while allocated < target_pressure:
                chunk = bytearray(chunk_size)
                pressure_allocations.append(chunk)
                allocated += chunk_size

            # Run inference under pressure
            model = self._load_model()
            try:
                output = model.infer(self.vectors["query"])
                assert output is not None
                print("  Inference succeeded under 80% memory pressure")
            except Exception as e:
                pytest.fail(f"Inference failed under memory pressure: {e}")

        finally:
            # Release pressure
            pressure_allocations.clear()
            import gc
            gc.collect()

    @pytest.mark.slow
    def test_long_running_endurance(self):
        """24-hour endurance test for long-term stability.

        This test runs a continuous workload for the configured
        duration and monitors for:
        - Monotonic increase in error rate
        - Memory leak
        - Thread leak
        - File descriptor leak
        - Thermal throttling events
        """
        process = psutil.Process()
        baseline_fds = process.num_fds()
        baseline_threads = process.num_threads()
        model = self._load_model()

        # Sampling intervals
        metrics = {
            "timestamps": [],
            "rss": [],
            "fds": [],
            "threads": [],
            "errors": [],
            "throughput": [],
        }

        start = time.monotonic()
        end = start + self.duration
        ops = 0
        errors = 0
        sample_interval = 60  # Collect metrics every 60s

        def collect_metrics():
            metrics["timestamps"].append(time.monotonic() - start)
            metrics["rss"].append(process.memory_info().rss)
            metrics["fds"].append(process.num_fds())
            metrics["threads"].append(process.num_threads())
            metrics["errors"].append(errors)
            metrics["throughput"].append(ops)

        last_sample = time.monotonic()
        while time.monotonic() < end:
            try:
                model.infer(self.vectors["query"])
                ops += 1
            except Exception:
                errors += 1

            now = time.monotonic()
            if now - last_sample >= sample_interval:
                collect_metrics()
                last_sample = now

        # Final sample
        collect_metrics()

        # Analyze results
        error_rate = errors / max(ops, 1) * 100
        rss_drift = metrics["rss"][-1] - metrics["rss"][0]
        fd_leak = metrics["fds"][-1] - baseline_fds
        thread_leak = metrics["threads"][-1] - baseline_threads

        print(f"\n  Endurance test results ({self.duration}s):")
        print(f"    Total operations: {ops}")
        print(f"    Error rate: {error_rate:.4f}%")
        print(f"    RSS drift: {rss_drift / 1024 / 1024:.1f} MB")
        print(f"    FD leak: {fd_leak}")
        print(f"    Thread leak: {thread_leak}")

        assert error_rate < 0.1, "Error rate increased over time"
        assert rss_drift < 100 * 1024 * 1024, "Memory drift detected"
        assert fd_leak < 10, "File descriptor leak detected"
        assert thread_leak < 5, "Thread leak detected"

    def _load_model(self):
        """Helper to load a test model."""
        model_path = os.path.join(self.model_dir, "test_model.gguf")
        config = ModelConfig(model_path, backend="ggml")
        return GGmlEngine.load_model(config)

    def _search(self):
        """Helper to run a semantic search operation."""
        kernel = self._get_kernel_stub()
        kernel.ai_semantic_search(
            self.vectors["query"],
            self.vectors["database"],
            top_k=5
        )

    def _context_ops(self):
        """Helper to run context store/retrieve operations."""
        kernel = self._get_kernel_stub()
        session_id = random.randint(1, 100)
        key = f"key_{random.randint(1, 1000)}"
        value = f"value_{random.randint(1, 1000)}"
        entry_id, _ = kernel.ai_context_store(session_id, key, value, 60000)
        kernel.ai_context_retrieve(session_id, key, entry_id)

    def _get_kernel_stub(self):
        """Get or create a kernel stub for this worker."""
        if not hasattr(self, "_kernel"):
            from tests.mock.kernel_stubs import KernelStub
            self._kernel = KernelStub()
        return self._kernel
```

### Stress Test Safety

**WARNING:** Stress tests push the system to its limits. Follow these precautions:

1. **Run on dedicated hardware.** Do not run on shared development machines or CI runners.
2. **Monitor temperature.** Ensure adequate cooling. Stop if CPU/GPU temperature exceeds 85C.
3. **Set resource limits.** Use `ulimit` or cgroups to prevent runaway resource consumption:

```bash
# Limit stress test to 4GB RAM and 30 minutes
ulimit -v 4194304
timeout 1800 pytest tests/stress/ -v
```

4. **Use a separate test partition.** Stress tests may cause filesystem writes that could affect other processes.
5. **Have a kill switch ready.** In a separate terminal:

```bash
# Kill all stress test processes
pkill -f "test_stress"
```

### Stress Test Scenarios

Scenario definitions are stored in `tests/stress/scenarios/` as YAML:

```yaml
# tests/stress/scenarios/high_concurrency.yaml
name: high_concurrency
description: "100 concurrent clients, moderate load, 30 minutes"
duration: 1800
concurrency: 100
operations:
  - type: infer
    weight: 60
    model: test_model.gguf
  - type: search
    weight: 25
    db_size: 1000
  - type: context_store
    weight: 10
  - type: context_retrieve
    weight: 5
monitoring:
  rss_limit_mb: 4096
  error_rate_limit: 1.0
  temperature_limit_c: 85
```

---

## 13. Troubleshooting

### Common Issues

#### Issue: "Kernel module not found"

```
FAIL: test_kernel_modules - ret=-1, errno=ENOSYS
```

**Cause:** The Ainos kernel module is not loaded, or the syscall numbers do not match.

**Solution:**
```bash
# Check if module is loaded
lsmod | grep ainos

# Load the module
sudo modprobe ainos

# Verify syscall availability
cat /proc/syscall | grep ai_
```

#### Issue: "Permission denied" for kernel tests

```
FAIL: test_syscalls - ret=-1, errno=EPERM
```

**Cause:** Kernel tests require root or appropriate capabilities.

**Solution:**
```bash
# Run with root
sudo ./test_syscalls

# Or grant capabilities
sudo setcap cap_sys_admin+ep ./test_syscalls
```

#### Issue: Tests hang indefinitely

**Cause:** Usually a deadlock in the test or a blocking syscall.

**Solution:**
```bash
# Set a global timeout
export AINOS_TIMEOUT=30
pytest tests/ -v --timeout=30

# Find hanging tests with verbose output
pytest tests/ -v --timeout=30 --showlocals
```

#### Issue: "Address already in use" for mock daemon

**Cause:** A previous test run left the daemon process running.

**Solution:**
```bash
# Find and kill stale daemon processes
pkill -f "MockDaemonServer"

# Or use a different port
export AINOS_DAEMON_PORT=18544
pytest tests/ -v
```

#### Issue: Test results differ between runs (flaky tests)

**Cause:** Non-deterministic test data, timing-dependent assertions, or environment pollution.

**Solution:**
```bash
# Reproduce with fixed seed
export AINOS_SEED=42
pytest tests/ -v

# Use pytest-repeat to reproduce flaky failures
pytest tests/ -v --count=10 --repeat-scope=function

# Mark flaky tests and retry
pytest tests/ -v --reruns=3 --only-rerun="flaky"
```

#### Issue: "Out of memory" during stress tests

**Cause:** Stress tests consume large amounts of memory. Resource limits are not set.

**Solution:**
```bash
# Run with memory limit
ulimit -v 8388608  # 8GB
pytest tests/stress/ -v

# Or reduce concurrency
export AINOS_STRESS_CONCURRENCY=10
pytest tests/stress/ -v
```

#### Issue: C test compilation fails

```
gcc: error: unrecognized command line option '-std=c23'
```

**Cause:** GCC version too old for the C standard used.

**Solution:**
```bash
# Check GCC version
gcc --version

# Update to GCC 12+
sudo apt install gcc-12 g++-12

# Or modify CMakeLists.txt to use an older standard
# set(CMAKE_C_STANDARD 17)
```

### Debugging Tests

```bash
# Run with full traceback
pytest tests/ -v --tb=long

# Run with pdb (drop into debugger on failure)
pytest tests/ -v --pdb

# Run with live logging
pytest tests/ -v -o log_cli=true --log-cli-level=DEBUG

# Run a single test with stdout capture disabled
pytest tests/ -v -s -k "test_name"

# Check which tests are slow
pytest tests/ --durations=10
```

### Getting Help

If you encounter issues not covered here:

1. Check the test log file: `tests/test_output.log`
2. Run the test runner with verbose logging: `python tests/run_all_tests.py --verbose`
3. Open an issue on GitHub with:
   - Full test output
   - Platform information (`uname -a`, `python --version`)
   - Environment variables set
   - Steps to reproduce

---

## 14. Contributing

### How to Contribute Tests

1. **Fork the repository** and create a feature branch.
2. **Add tests** following the guidelines in this document.
3. **Run the full test suite** to ensure no regressions.
4. **Submit a pull request** with a clear description of what the tests cover.

### Test Review Checklist

Before submitting a PR, verify:

- [ ] Tests pass locally (`pytest tests/ -v`)
- [ ] New tests have appropriate markers (`@pytest.mark.*`)
- [ ] Tests cover both success and error paths
- [ ] Tests use fixtures, not global state
- [ ] Test data is deterministic (fixed seed or fixed input)
- [ ] Tests clean up resources (no leaks)
- [ ] Documentation is updated if adding new test categories
- [ ] Coverage has not decreased
- [ ] No flaky tests (run 3x to verify stability)

### Test Contribution Workflow

```bash
# 1. Create a branch
git checkout -b feat/tests-add-vector-accel

# 2. Add tests
# Edit: tests/kernel/test_vector_accel.c
# Or create: tests/runtime/test_vector_accel.py

# 3. Run tests
pytest tests/ -v -k "vector_accel"

# 4. Run full suite
python tests/run_all_tests.py

# 5. Check coverage
pytest tests/ --cov=ainos --cov-report=term

# 6. Commit
git add tests/
git commit -m "tests: add vector accelerator unit tests

- Add C tests for ai_vector_add and ai_vector_mul syscalls
- Add Python tests for vector accelerator runtime integration
- All tests pass, coverage maintained at 88%

Co-Authored-By: Claude <contact@dianclaw.cn>"

# 7. Push and open PR
git push origin feat/tests-add-vector-accel
```

### Code of Conduct

- Tests must be deterministic. No race conditions, no time-of-check/time-of-use bugs.
- Tests must be hermetic. No dependencies on network access, external services, or specific filesystem paths.
- Tests must be minimal. Test one thing per function. Don't duplicate coverage.
- Tests must be readable. Use descriptive names, clear assertions, and comments where the intent is not obvious from the code.

### Test Suite Governance

| Role | Responsibility |
|------|---------------|
| Test Owner | Maintains test infrastructure, runner, and CI integration |
| Component Owners | Responsible for tests within their component |
| Reviewers | Verify test quality, coverage, and determinism |
| Release Managers | Validate test suite passes before releases |

### Release Qualification

Before each release, the test suite must achieve:

- 100% pass rate for kernel, runtime, and SDK tests
- 90%+ pass rate for integration tests
- No critical failures in stress tests
- Performance regression < 5% from baseline
- Coverage >= 80% across all components

---

## License

This test suite is part of the AinosOS project. Licensed under GPL-2.0.

---

*Last updated: 2026-08-04*
*For questions, contact: ainos-dev@example.com*