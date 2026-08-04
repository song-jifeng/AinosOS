"""
JSON Parse Benchmark
=====================

Measures JSON parsing and serialization performance across different
JSON libraries and data complexity levels. This benchmark is critical
for understanding API server and data pipeline performance.

This benchmark evaluates:
- Parsing performance across multiple JSON libraries (json, orjson, ujson, simdjson)
- Serialization performance across libraries
- Various data complexity levels (simple, nested, array, mixed)
- Large file parsing performance
- Schema validation overhead
"""

from __future__ import annotations

import logging
import math
import time
import sys
from typing import Any

import numpy as np
from numpy.typing import NDArray

from benchmarks import (
    BenchmarkConfigError,
    BenchmarkExecutionError,
    BenchmarkTimeoutError,
    DEFAULT_BENCHMARK_ITERATIONS,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_WARMUP_ITERATIONS,
    ResultDict,
)

logger = logging.getLogger(__name__)


# Size parsing
_SIZE_UNITS: dict[str, int] = {
    "B": 1,
    "KB": 1024,
    "MB": 1024 * 1024,
    "GB": 1024 * 1024 * 1024,
}


def _parse_size(size_str: str) -> int:
    """Parse a human-readable size string into bytes.

    Args:
        size_str: Size string like "1KB", "10MB".

    Returns:
        Size in bytes as integer.
    """
    size_str = size_str.strip().upper()
    for unit, multiplier in sorted(_SIZE_UNITS.items(), key=lambda x: -len(x[0])):
        if size_str.endswith(unit):
            try:
                return int(float(size_str[: -len(unit)]) * multiplier)
            except ValueError:
                continue
    try:
        return int(size_str)
    except ValueError:
        raise ValueError(f"Cannot parse size string: {size_str}")


class JSONParseBenchmark:
    """Benchmark for JSON parsing and serialization performance.

    Compares multiple JSON libraries across different data sizes and
    complexity levels.

    Attributes:
        name: Unique identifier for this benchmark.
        file_sizes: List of data sizes to test (human-readable strings).
        file_bytes: List of data sizes converted to bytes.
        iterations: Number of measurement iterations per configuration.
        warmup: Number of warmup iterations.
        libraries: List of JSON libraries to benchmark.
        complexity_levels: List of data complexity types.
        schema_validation: Whether to test schema validation.
        timeout: Maximum time per measurement in seconds.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the JSON parse benchmark.

        Args:
            config: Configuration dictionary. Expected keys: file_sizes,
                iterations, warmup, libraries, complexity_levels,
                schema_validation, timeout.

        Raises:
            BenchmarkConfigError: If configuration is invalid.
        """
        self.name: str = "json_parse"
        self.config: dict[str, Any] = config or {}

        size_strings: list[str] = self.config.get(
            "file_sizes", ["1KB", "10KB", "100KB", "1MB", "10MB"]
        )
        self.file_bytes: list[int] = [_parse_size(s) for s in size_strings]
        self.file_sizes: list[str] = size_strings

        self.iterations: int = self.config.get("iterations", DEFAULT_BENCHMARK_ITERATIONS)
        self.warmup: int = self.config.get("warmup", DEFAULT_WARMUP_ITERATIONS)
        self.libraries: list[str] = self.config.get(
            "libraries", ["json", "orjson", "ujson", "simdjson"]
        )
        self.complexity_levels: list[str] = self.config.get(
            "complexity_levels", ["simple", "nested", "array", "mixed"]
        )
        self.schema_validation: bool = self.config.get("schema_validation", False)
        self.timeout: int = self.config.get("timeout", DEFAULT_TIMEOUT_SECONDS)

        # Validate libraries
        valid_libs = {"json", "orjson", "ujson", "simdjson"}
        for lib in self.libraries:
            if lib not in valid_libs:
                logger.warning("Unknown library '%s', will attempt import anyway", lib)

        # Check available libraries
        self._available_libs: dict[str, bool] = {}
        for lib in self.libraries:
            self._available_libs[lib] = self._check_library(lib)

        logger.info(
            "Initialized JSONParseBenchmark: %d sizes, %d libs, %d complexity levels, "
            "schema_validation=%s",
            len(self.file_bytes), len(self.libraries),
            len(self.complexity_levels), self.schema_validation,
        )

    @staticmethod
    def _check_library(lib_name: str) -> bool:
        """Check if a JSON library is available.

        Args:
            lib_name: Name of the library to check.

        Returns:
            True if the library can be imported.
        """
        try:
            __import__(lib_name)
            return True
        except ImportError:
            logger.warning("Library '%s' not available", lib_name)
            return False

    def _generate_json_data(self, size_bytes: int, complexity: str) -> Any:
        """Generate JSON data of specified size and complexity.

        Creates realistic JSON data structures of the target size.

        Args:
            size_bytes: Target size of the JSON string in bytes.
            complexity: Complexity level ('simple', 'nested', 'array', 'mixed').

        Returns:
            Python object that can be serialized to JSON.

        Raises:
            BenchmarkExecutionError: If generation fails.
        """
        target_size = size_bytes

        if complexity == "simple":
            # Flat key-value pairs
            data: dict[str, Any] = {}
            i = 0
            while len(json.dumps(data)) < target_size and i < 10000:
                data[f"key_{i}"] = f"value_{i}_" + "x" * 10
                i += 1
            return data

        elif complexity == "nested":
            # Deeply nested structure
            depth = 0
            current: dict[str, Any] = {}
            root = current
            while len(json.dumps(root)) < target_size and depth < 100:
                next_level: dict[str, Any] = {}
                for i in range(10):
                    current[f"key_{depth}_{i}"] = f"value_{i}_" + "x" * 5
                current["nested"] = next_level
                current = next_level
                depth += 1
            return root

        elif complexity == "array":
            # Large array of simple objects
            arr: list[dict[str, Any]] = []
            i = 0
            while len(json.dumps(arr)) < target_size and i < 50000:
                arr.append({
                    "id": i,
                    "name": f"item_{i}",
                    "value": math.sin(i),
                    "active": i % 2 == 0,
                    "tags": [f"tag_{j}" for j in range(5)],
                })
                i += 1
            return arr

        elif complexity == "mixed":
            # Mixed data with various types
            mixed: dict[str, Any] = {
                "metadata": {
                    "version": "1.0.0",
                    "timestamp": time.time(),
                    "author": "benchmark",
                    "count": 1000,
                },
                "data": [],
                "summary": {
                    "total": 0,
                    "average": 0.0,
                    "tags": [],
                },
            }
            i = 0
            while len(json.dumps(mixed)) < target_size and i < 5000:
                mixed["data"].append({
                    "id": i,
                    "type": "test" if i % 2 == 0 else "prod",
                    "values": [float(j) for j in range(20)],
                    "nested": {
                        "a": {"b": {"c": i}},
                        "coordinates": [float(i), float(-i)],
                    },
                    "metadata": {
                        "created": "2024-01-01T00:00:00Z",
                        "priority": i % 5,
                        "flags": [True, False, None],
                    },
                })
                mixed["summary"]["total"] = i + 1
                i += 1
            return mixed

        else:
            raise BenchmarkConfigError(f"Unknown complexity: {complexity}")

    def _measure_parse(
        self, json_str: bytes | str, lib_name: str
    ) -> dict[str, float | list[float] | None]:
        """Measure JSON parsing time for a specific library.

        Args:
            json_str: JSON string to parse.
            lib_name: Name of the library to use.

        Returns:
            Dictionary with timing statistics.

        Raises:
            BenchmarkExecutionError: If library is not available or parsing fails.
        """
        if not self._available_libs.get(lib_name, False):
            return {"error": f"Library '{lib_name}' not available"}

        lib = __import__(lib_name)

        # Determine the parse function
        if lib_name == "json":
            parse_fn = lib.loads
        elif lib_name == "orjson":
            parse_fn = lib.loads
        elif lib_name == "ujson":
            parse_fn = lib.loads
        elif lib_name == "simdjson":
            # simdjson uses a different API
            if hasattr(lib, "loads"):
                parse_fn = lib.loads
            else:
                parser = lib.Parser()
                parse_fn = parser.parse
        else:
            parse_fn = lib.loads

        times: list[float] = []

        # Warmup
        for _ in range(self.warmup):
            try:
                _ = parse_fn(json_str)
            except Exception as exc:
                raise BenchmarkExecutionError(
                    f"Parse warmup failed for {lib_name}: {exc}"
                ) from exc

        # Measurement
        start_time = time.monotonic()
        for i in range(self.iterations):
            if time.monotonic() - start_time > self.timeout:
                raise BenchmarkTimeoutError(self.timeout)

            t0 = time.perf_counter()
            try:
                _ = parse_fn(json_str)
            except Exception as exc:
                raise BenchmarkExecutionError(
                    f"Parse failed for {lib_name} at iteration {i}: {exc}"
                ) from exc
            t1 = time.perf_counter()
            times.append(t1 - t0)

        # Compute statistics
        times_arr = np.array(times, dtype=np.float64)
        mean_time = float(np.mean(times_arr))
        median_time = float(np.median(times_arr))
        std_time = float(np.std(times_arr, ddof=1))

        # Throughput
        input_size = len(json_str) if isinstance(json_str, bytes) else len(json_str.encode())
        throughput_mbps = (input_size / mean_time) / (1024 * 1024) if mean_time > 0 else 0.0

        return {
            "mean_s": mean_time,
            "median_s": median_time,
            "std_s": std_time,
            "min_s": float(np.min(times_arr)),
            "max_s": float(np.max(times_arr)),
            "p50_s": float(np.percentile(times_arr, 50)),
            "p90_s": float(np.percentile(times_arr, 90)),
            "p95_s": float(np.percentile(times_arr, 95)),
            "p99_s": float(np.percentile(times_arr, 99)),
            "throughput_MBps": throughput_mbps,
            "input_size_bytes": input_size,
            "n_samples": len(times),
            "raw_times": times,
        }

    def _measure_serialize(
        self, data: Any, lib_name: str
    ) -> dict[str, float | list[float] | None]:
        """Measure JSON serialization time for a specific library.

        Args:
            data: Python object to serialize.
            lib_name: Name of the library to use.

        Returns:
            Dictionary with timing statistics.

        Raises:
            BenchmarkExecutionError: If library is not available or serialization fails.
        """
        if not self._available_libs.get(lib_name, False):
            return {"error": f"Library '{lib_name}' not available"}

        lib = __import__(lib_name)

        # Determine the serialize function
        if lib_name == "json":
            serialize_fn = lib.dumps
        elif lib_name == "orjson":
            serialize_fn = lib.dumps
        elif lib_name == "ujson":
            serialize_fn = lib.dumps
        elif lib_name == "simdjson":
            if hasattr(lib, "dumps"):
                serialize_fn = lib.dumps
            else:
                return {"error": "simdjson does not support serialization"}
        else:
            serialize_fn = lib.dumps

        times: list[float] = []

        # Warmup
        for _ in range(self.warmup):
            try:
                _ = serialize_fn(data)
            except Exception as exc:
                raise BenchmarkExecutionError(
                    f"Serialize warmup failed for {lib_name}: {exc}"
                ) from exc

        # Measurement
        start_time = time.monotonic()
        for _ in range(self.iterations):
            if time.monotonic() - start_time > self.timeout:
                raise BenchmarkTimeoutError(self.timeout)

            t0 = time.perf_counter()
            try:
                _ = serialize_fn(data)
            except Exception as exc:
                raise BenchmarkExecutionError(
                    f"Serialize failed for {lib_name}: {exc}"
                ) from exc
            t1 = time.perf_counter()
            times.append(t1 - t0)

        # Compute statistics
        times_arr = np.array(times, dtype=np.float64)
        mean_time = float(np.mean(times_arr))
        median_time = float(np.median(times_arr))

        return {
            "mean_s": mean_time,
            "median_s": median_time,
            "std_s": float(np.std(times_arr, ddof=1)),
            "min_s": float(np.min(times_arr)),
            "max_s": float(np.max(times_arr)),
            "p50_s": float(np.percentile(times_arr, 50)),
            "p90_s": float(np.percentile(times_arr, 90)),
            "p95_s": float(np.percentile(times_arr, 95)),
            "p99_s": float(np.percentile(times_arr, 99)),
            "n_samples": len(times),
            "raw_times": times,
        }

    def run(self) -> list[ResultDict]:
        """Execute the full JSON parse benchmark.

        Runs parsing and serialization benchmarks across all sizes,
        libraries, and complexity levels.

        Returns:
            List of result dictionaries with timing metrics.

        Raises:
            BenchmarkExecutionError: If all measurements fail.
        """
        logger.info("Starting JSON parse benchmark")
        logger.info(
            "Libraries: %s, Sizes: %s, Complexities: %s",
            self.libraries, self.file_sizes, self.complexity_levels,
        )

        import json as std_json

        results: list[ResultDict] = []
        total_start = time.monotonic()

        # Generate test data once per complexity
        test_data: dict[str, tuple[Any, str]] = {}
        for complexity in self.complexity_levels:
            for size_bytes in self.file_bytes:
                key = f"{complexity}_{size_bytes}"
                try:
                    data = self._generate_json_data(size_bytes, complexity)
                    json_str = std_json.dumps(data)
                    test_data[key] = (data, json_str)
                    logger.debug(
                        "Generated %s data for %s: %d bytes",
                        complexity, self._format_bytes(size_bytes), len(json_str),
                    )
                except Exception as exc:
                    logger.error("Failed to generate data for %s: %s", key, exc)

        successful: int = 0

        # Parse benchmarks
        for complexity in self.complexity_levels:
            for size_bytes, size_label in zip(self.file_bytes, self.file_sizes):
                key = f"{complexity}_{size_bytes}"
                if key not in test_data:
                    continue

                _, json_str = test_data[key]

                for lib_name in self.libraries:
                    result: ResultDict = {
                        "benchmark": self.name,
                        "test_type": "parse",
                        "library": lib_name,
                        "complexity": complexity,
                        "size_bytes": size_bytes,
                        "size_label": size_label,
                        "library_available": self._available_libs.get(lib_name, False),
                    }

                    try:
                        parse_results = self._measure_parse(json_str, lib_name)
                        if "error" in parse_results:
                            result["error"] = parse_results["error"]
                        else:
                            for key2, value in parse_results.items():
                                if isinstance(value, (int, float, str)):
                                    result[key2] = value
                                elif key2 == "raw_times":
                                    result[key2] = value
                            successful += 1
                    except Exception as exc:
                        result["error"] = str(exc)

                    results.append(result)

        # Serialize benchmarks
        for complexity in self.complexity_levels:
            for size_bytes, size_label in zip(self.file_bytes, self.file_sizes):
                key = f"{complexity}_{size_bytes}"
                if key not in test_data:
                    continue

                data, _ = test_data[key]

                for lib_name in self.libraries:
                    result = {
                        "benchmark": self.name,
                        "test_type": "serialize",
                        "library": lib_name,
                        "complexity": complexity,
                        "size_bytes": size_bytes,
                        "size_label": size_label,
                        "library_available": self._available_libs.get(lib_name, False),
                    }

                    try:
                        ser_results = self._measure_serialize(data, lib_name)
                        if "error" in ser_results:
                            result["error"] = ser_results["error"]
                        else:
                            for key2, value in ser_results.items():
                                if isinstance(value, (int, float, str)):
                                    result[key2] = value
                                elif key2 == "raw_times":
                                    result[key2] = value
                            successful += 1
                    except Exception as exc:
                        result["error"] = str(exc)

                    results.append(result)

        total_elapsed = time.monotonic() - total_start
        logger.info(
            "JSON parse benchmark completed in %.2fs. "
            "Successful: %d/%d configurations",
            total_elapsed, successful, len(results),
        )

        return results

    @staticmethod
    def _format_bytes(n_bytes: int) -> str:
        """Format byte count to a human-readable string.

        Args:
            n_bytes: Number of bytes.

        Returns:
            Formatted string.
        """
        if n_bytes < 1024:
            return f"{n_bytes}B"
        elif n_bytes < 1024 * 1024:
            return f"{n_bytes / 1024:.1f}KB"
        elif n_bytes < 1024 * 1024 * 1024:
            return f"{n_bytes / (1024 * 1024):.1f}MB"
        else:
            return f"{n_bytes / (1024 * 1024 * 1024):.2f}GB"

    def get_info(self) -> dict[str, Any]:
        """Return metadata about this benchmark configuration.

        Returns:
            Dictionary with benchmark metadata.
        """
        return {
            "name": self.name,
            "description": "JSON parsing and serialization performance benchmark",
            "file_sizes": self.file_sizes,
            "iterations": self.iterations,
            "warmup": self.warmup,
            "libraries": self.libraries,
            "available_libraries": {k: v for k, v in self._available_libs.items()},
            "complexity_levels": self.complexity_levels,
            "schema_validation": self.schema_validation,
            "timeout": self.timeout,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bench = JSONParseBenchmark()
    results = bench.run()
    print(f"Completed {len(results)} benchmark runs")

    for r in results:
        if "error" not in r:
            print(f"  [{r['test_type']:>8s}] {r['library']:>8s} {r['complexity']:>8s} "
                  f"{r['size_label']:>5s}: {r['mean_s']*1000:8.3f}ms")