"""
Ainos Performance Benchmark Suite
==================================

Comprehensive performance benchmarking framework for micro-benchmarks,
kernel-level benchmarks, AI inference benchmarks, and SDK performance comparisons.

This package provides:
- Micro-benchmarks: matrix multiplication, memory bandwidth, cache latency, vector ops, TCP throughput, JSON parsing
- Kernel benchmarks: syscall latency, context switching, IPC throughput, memory allocation
- AI benchmarks: inference latency/throughput, embedding speed, search latency, model loading
- SDK benchmarks: multi-language SDK latency/throughput/memory comparisons
- Reporting: HTML/JSON reports with charts and comparative analysis
- Results storage: SQLite persistence with historical tracking
"""

import logging
from typing import Final, ClassVar

__version__: Final[str] = "1.0.0"
__author__: Final[str] = "Ainos Performance Engineering"

# Package-level logger
logger = logging.getLogger(__name__)

# Default benchmark configurations
DEFAULT_WARMUP_ITERATIONS: Final[int] = 10
DEFAULT_BENCHMARK_ITERATIONS: Final[int] = 100
DEFAULT_TIMEOUT_SECONDS: Final[int] = 300
DEFAULT_TOLERANCE: Final[float] = 0.05  # 5% tolerance for statistical significance


class BenchmarkError(Exception):
    """Base exception for all benchmark-related errors."""

    def __init__(self, message: str, benchmark_name: str | None = None) -> None:
        self.benchmark_name = benchmark_name
        super().__init__(f"[{benchmark_name}] {message}" if benchmark_name else message)


class BenchmarkConfigError(BenchmarkError):
    """Raised when benchmark configuration is invalid."""

    def __init__(self, message: str, config_key: str | None = None) -> None:
        self.config_key = config_key
        super().__init__(f"Configuration error for '{config_key}': {message}")


class BenchmarkExecutionError(BenchmarkError):
    """Raised when benchmark execution fails."""

    def __init__(self, message: str, exit_code: int | None = None) -> None:
        self.exit_code = exit_code
        super().__init__(f"Execution failed (exit={exit_code}): {message}")


class BenchmarkTimeoutError(BenchmarkError):
    """Raised when a benchmark exceeds its allotted time."""

    def __init__(self, timeout_seconds: int) -> None:
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Benchmark timed out after {timeout_seconds}s")


# Statistical result type alias
type ResultDict = dict[str, float | int | str | list[float] | None]
type BenchmarkResults = list[ResultDict]