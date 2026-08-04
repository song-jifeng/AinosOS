"""
Conftest for benchmark tests.
Provides shared fixtures and configuration for the test suite.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import pytest

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest for the benchmark test suite.

    Args:
        config: Pytest configuration object.
    """
    # Register custom markers
    config.addinivalue_line("markers", "micro: micro-benchmark tests")
    config.addinivalue_line("markers", "kernel: kernel benchmark tests")
    config.addinivalue_line("markers", "ai: AI benchmark tests")
    config.addinivalue_line("markers", "sdk: SDK benchmark tests")
    config.addinivalue_line("markers", "slow: slow tests that may take minutes")
    config.addinivalue_line("markers", "integration: integration tests")

    # Configure logging for tests
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


@pytest.fixture(scope="session")
def benchmark_config() -> dict[str, Any]:
    """Provide a minimal benchmark configuration for testing.

    Returns:
        Configuration dictionary with minimal test settings.
    """
    return {
        "global": {
            "default_timeout": 60,
            "default_warmup_iterations": 2,
            "default_benchmark_iterations": 5,
            "log_level": "WARNING",
        },
        "micro": {
            "matrix_mul": {
                "sizes": [16, 32],
                "iterations": 3,
                "warmup": 1,
            },
            "memory_bandwidth": {
                "buffer_sizes": ["1KB", "4KB"],
                "iterations": 3,
                "warmup": 1,
            },
            "cache_latency": {
                "buffer_sizes": ["1KB", "4KB"],
                "strides": [1, 4],
                "iterations": 3,
                "warmup": 1,
            },
            "vector_ops": {
                "sizes": [100, 1000],
                "operations": ["add", "mul"],
                "iterations": 3,
                "warmup": 1,
            },
            "tcp_throughput": {
                "message_sizes": [64, 256],
                "iterations": 3,
                "warmup": 1,
            },
            "json_parse": {
                "file_sizes": ["1KB"],
                "libraries": ["json"],
                "iterations": 3,
                "warmup": 1,
            },
        },
        "kernel": {
            "syscall_latency": {
                "syscalls": ["getpid", "clock_gettime"],
                "iterations": 100,
                "warmup": 10,
            },
            "context_switch": {
                "methods": ["pipe"],
                "thread_counts": [2],
                "iterations": 50,
                "warmup": 10,
            },
            "ipc_throughput": {
                "methods": ["pipe"],
                "message_sizes": [64],
                "iterations": 50,
                "warmup": 10,
            },
            "memory_alloc": {
                "allocators": ["malloc"],
                "sizes": [16, 64],
                "patterns": ["single"],
                "iterations": 50,
                "warmup": 10,
            },
        },
        "ai": {
            "inference_latency": {
                "model_types": ["bert-base-uncased"],
                "batch_sizes": [1],
                "sequence_lengths": [32],
                "iterations": 3,
                "warmup": 1,
            },
            "inference_throughput": {
                "model_types": ["bert-base-uncased"],
                "batch_sizes": [1],
                "duration_seconds": 2,
                "warmup_seconds": 1,
            },
            "embedding_speed": {
                "embedders": ["sentence-transformers/all-MiniLM-L6-v2"],
                "batch_sizes": [1],
                "text_lengths": [16],
                "iterations": 3,
                "warmup": 1,
            },
            "search_latency": {
                "index_types": ["flat"],
                "dimensions": [128],
                "dataset_sizes": [100],
                "top_k": [10],
                "queries": 10,
            },
            "model_load": {
                "model_types": ["bert-base-uncased"],
                "formats": ["pytorch"],
                "iterations": 2,
                "warmup": 1,
            },
        },
        "sdk": {
            "sdk_latency": {
                "sdks": ["python"],
                "operations": ["init", "completion"],
                "model_sizes": ["small"],
                "iterations": 3,
                "warmup": 1,
            },
            "sdk_throughput": {
                "sdks": ["python"],
                "concurrent_requests": [1],
                "duration_seconds": 2,
                "warmup_seconds": 1,
                "operations": ["completion"],
            },
            "sdk_memory": {
                "sdks": ["python"],
                "operations": ["init", "idle"],
                "iterations": 3,
            },
        },
        "reports": {
            "output_dir": "reports/test_output",
            "html": {"enabled": True, "theme": "light"},
            "json": {"enabled": True, "pretty_print": True},
            "charts": {"enabled": True, "format": "png", "dpi": 72},
        },
        "storage": {
            "database": {
                "type": "sqlite",
                "path": "data/test_benchmark_results.db",
                "wal_mode": False,
            },
            "history": {
                "max_entries": 100,
                "auto_cleanup": False,
                "retention_days": 30,
            },
        },
    }


@pytest.fixture(scope="function")
def temp_output_dir(tmp_path: Any) -> str:
    """Create a temporary output directory for test artifacts.

    Args:
        tmp_path: Pytest temporary path fixture.

    Returns:
        Path string to the temporary directory.
    """
    output_dir = tmp_path / "benchmark_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return str(output_dir)


@pytest.fixture(scope="function")
def sample_results() -> list[dict[str, Any]]:
    """Provide sample benchmark results for testing reports and analysis.

    Returns:
        List of sample result dictionaries.
    """
    import numpy as np

    rng = np.random.default_rng(42)

    results = []
    for i, size in enumerate([64, 128, 256]):
        raw_times = list(rng.normal(0.001 * size / 64, 0.0001, 20))
        results.append({
            "benchmark": "matrix_mul",
            "size": size,
            "dtype": "float64",
            "use_blas": True,
            "mean_s": float(np.mean(raw_times)),
            "median_s": float(np.median(raw_times)),
            "std_s": float(np.std(raw_times, ddof=1)),
            "min_s": float(np.min(raw_times)),
            "max_s": float(np.max(raw_times)),
            "p50_s": float(np.percentile(raw_times, 50)),
            "p90_s": float(np.percentile(raw_times, 90)),
            "p95_s": float(np.percentile(raw_times, 95)),
            "p99_s": float(np.percentile(raw_times, 99)),
            "gflops": 2.0 * size**3 / (float(np.mean(raw_times)) * 1e9),
            "mean_ms": float(np.mean(raw_times)) * 1000,
            "raw_times": raw_times,
            "run_name": "test_run",
            "timestamp": "2024-01-01T00:00:00",
        })

    return results


@pytest.fixture(scope="function")
def sample_latency_results() -> list[dict[str, Any]]:
    """Provide sample latency benchmark results for testing.

    Returns:
        List of sample latency result dictionaries.
    """
    import numpy as np

    rng = np.random.default_rng(42)

    results = []
    for model in ["bert-base-uncased", "gpt2"]:
        for batch_size in [1, 4]:
            for seq_len in [32, 64]:
                raw_times = list(rng.normal(0.05 * batch_size * seq_len / 32, 0.005, 10))
                results.append({
                    "benchmark": "inference_latency",
                    "model": model,
                    "batch_size": batch_size,
                    "sequence_length": seq_len,
                    "precision": "fp32",
                    "device": "cpu",
                    "mean_ms": float(np.mean(raw_times)) * 1000,
                    "median_ms": float(np.median(raw_times)) * 1000,
                    "std_ms": float(np.std(raw_times, ddof=1)) * 1000,
                    "p50_ms": float(np.percentile(raw_times, 50)) * 1000,
                    "p90_ms": float(np.percentile(raw_times, 90)) * 1000,
                    "p95_ms": float(np.percentile(raw_times, 95)) * 1000,
                    "p99_ms": float(np.percentile(raw_times, 99)) * 1000,
                    "per_sample_ms": float(np.mean(raw_times)) * 1000 / batch_size,
                    "raw_times": raw_times,
                })

    return results


@pytest.fixture(scope="function")
def config_path(temp_output_dir: Any) -> str:
    """Create a temporary configuration file for testing.

    Args:
        temp_output_dir: Temporary output directory.

    Returns:
        Path to the created configuration file.
    """
    import yaml
    config = {
        "global": {
            "default_timeout": 30,
            "default_warmup_iterations": 2,
            "default_benchmark_iterations": 5,
            "log_level": "WARNING",
            "output_dir": temp_output_dir,
        },
        "micro": {
            "matrix_mul": {"sizes": [16], "iterations": 2, "warmup": 1},
        },
        "reports": {"output_dir": temp_output_dir},
        "storage": {"database": {"path": os.path.join(temp_output_dir, "test.db")}},
    }
    path = os.path.join(temp_output_dir, "test_config.yaml")
    with open(path, "w") as f:
        yaml.dump(config, f)
    return path