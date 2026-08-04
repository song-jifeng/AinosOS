"""
Embedding Speed Benchmark
==========================

Measures the speed of text embedding generation using various embedding
models. This benchmark is critical for understanding the performance of
semantic search and retrieval-augmented generation (RAG) pipelines.

This benchmark evaluates:
- Embedding generation latency for various text lengths
- Batch processing throughput for embeddings
- Comparison across embedding models
- Normalization overhead
- Memory usage during embedding generation
"""

from __future__ import annotations

import logging
import math
import time
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


class EmbeddingSpeedBenchmark:
    """Benchmark for text embedding generation speed.

    Measures the time taken to generate embeddings for text inputs
    of varying lengths and batch sizes.

    Attributes:
        name: Unique identifier for this benchmark.
        embedders: List of embedding model names to test.
        batch_sizes: List of batch sizes to test.
        text_lengths: List of text lengths (in tokens/characters) to test.
        iterations: Number of measurement iterations per configuration.
        warmup: Number of warmup iterations.
        normalize_embeddings: Whether to normalize output embeddings.
        provider: Embedding provider (sentence-transformers, etc.).
        timeout: Maximum time per measurement in seconds.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the embedding speed benchmark.

        Args:
            config: Configuration dictionary. Expected keys: embedders,
                batch_sizes, text_lengths, iterations, warmup,
                normalize_embeddings, provider, timeout.

        Raises:
            BenchmarkConfigError: If configuration is invalid.
        """
        self.name: str = "embedding_speed"
        self.config: dict[str, Any] = config or {}

        self.embedders: list[str] = self.config.get(
            "embedders", [
                "sentence-transformers/all-MiniLM-L6-v2",
                "text-embedding-ada-002",
                "BAAI/bge-small-en-v1.5",
            ]
        )
        self.batch_sizes: list[int] = self.config.get(
            "batch_sizes", [1, 8, 32, 64, 128]
        )
        self.text_lengths: list[int] = self.config.get(
            "text_lengths", [16, 64, 256, 512, 1024]
        )
        self.iterations: int = self.config.get("iterations", DEFAULT_BENCHMARK_ITERATIONS)
        self.warmup: int = self.config.get("warmup", DEFAULT_WARMUP_ITERATIONS)
        self.normalize_embeddings: bool = self.config.get("normalize_embeddings", True)
        self.provider: str = self.config.get("provider", "sentence-transformers")
        self.timeout: int = self.config.get("timeout", DEFAULT_TIMEOUT_SECONDS)

        logger.info(
            "Initialized EmbeddingSpeedBenchmark: %d embedders, "
            "batch_sizes=%s, text_lengths=%d, normalize=%s",
            len(self.embedders), self.batch_sizes,
            len(self.text_lengths), self.normalize_embeddings,
        )

    def _generate_text(self, length: int) -> str:
        """Generate text of approximately the given length.

        Args:
            length: Target text length in characters.

        Returns:
            Generated text string.
        """
        words = [
            "the", "quick", "brown", "fox", "jumps", "over", "lazy", "dog",
            "machine", "learning", "artificial", "intelligence", "deep",
            "neural", "network", "transformer", "attention", "embedding",
            "semantic", "search", "retrieval", "augmented", "generation",
            "performance", "benchmark", "latency", "throughput", "optimization",
            "vector", "database", "index", "quantization", "similarity",
            "cosine", "distance", "metric", "training", "inference", "model",
        ]

        text = " ".join(words * (length // 10 + 1))
        return text[:length]

    def _generate_batch_texts(self, length: int, batch_size: int) -> list[str]:
        """Generate a batch of texts.

        Args:
            length: Target text length in characters.
            batch_size: Number of texts to generate.

        Returns:
            List of generated text strings.
        """
        return [self._generate_text(length) for _ in range(batch_size)]

    def _simulate_embedding(
        self, texts: list[str], model_name: str
    ) -> tuple[float, int]:
        """Simulate embedding generation.

        Args:
            texts: List of input texts.
            model_name: Name of the embedding model.

        Returns:
            Tuple of (latency in seconds, embedding dimension).
        """
        total_chars = sum(len(t) for t in texts)
        batch_size = len(texts)

        # Model-specific embedding dimensions and compute requirements
        model_info: dict[str, dict[str, float]] = {
            "sentence-transformers/all-MiniLM-L6-v2": {"dim": 384, "flops_per_char": 500},
            "text-embedding-ada-002": {"dim": 1536, "flops_per_char": 2000},
            "BAAI/bge-small-en-v1.5": {"dim": 384, "flops_per_char": 400},
        }

        info = model_info.get(model_name, {"dim": 768, "flops_per_char": 1000})
        dim = int(info["dim"])
        flops_per_char = info["flops_per_char"]

        # Compute latency
        total_flops = total_chars * flops_per_char * batch_size
        cpu_flops = 50e9
        latency = total_flops / cpu_flops

        # Normalization overhead
        if self.normalize_embeddings:
            latency += batch_size * dim * 1e-9  # ~1ns per element for normalization

        # Add noise
        noise = np.random.normal(1.0, 0.05)
        return max(0.0001, latency * noise), dim

    def _measure_single_config(
        self, model_name: str, batch_size: int, text_length: int
    ) -> dict[str, Any]:
        """Measure embedding speed for a single configuration.

        Args:
            model_name: Name of the embedding model.
            batch_size: Batch size.
            text_length: Text length in characters.

        Returns:
            Dictionary with timing statistics.

        Raises:
            BenchmarkExecutionError: If measurement fails.
        """
        texts = self._generate_batch_texts(text_length, batch_size)
        latencies: list[float] = []

        # Warmup
        for _ in range(self.warmup):
            self._simulate_embedding(texts, model_name)

        # Measurement
        start_time = time.monotonic()
        for i in range(self.iterations):
            if time.monotonic() - start_time > self.timeout:
                raise BenchmarkTimeoutError(self.timeout)

            # Refresh texts periodically
            if i % 10 == 0:
                texts = self._generate_batch_texts(text_length, batch_size)

            t0 = time.perf_counter()
            _, dim = self._simulate_embedding(texts, model_name)
            t1 = time.perf_counter()
            latencies.append(t1 - t0)

        if not latencies:
            return {"error": "No measurements recorded", "raw_times": []}

        lat_arr = np.array(latencies, dtype=np.float64)
        mean_time = float(np.mean(lat_arr))
        median_time = float(np.median(lat_arr))

        total_chars = sum(len(t) for t in texts)
        chars_per_sec = (batch_size * total_chars / batch_size) / mean_time if mean_time > 0 else 0.0
        texts_per_sec = batch_size / mean_time if mean_time > 0 else 0.0
        embeddings_per_sec = 1.0 / (mean_time / batch_size) if mean_time > 0 else 0.0

        return {
            "mean_s": mean_time,
            "mean_ms": mean_time * 1000,
            "median_s": median_time,
            "median_ms": median_time * 1000,
            "std_s": float(np.std(lat_arr, ddof=1)),
            "std_ms": float(np.std(lat_arr, ddof=1)) * 1000,
            "min_s": float(np.min(lat_arr)),
            "min_ms": float(np.min(lat_arr)) * 1000,
            "max_s": float(np.max(lat_arr)),
            "max_ms": float(np.max(lat_arr)) * 1000,
            "p50_ms": float(np.percentile(lat_arr, 50)) * 1000,
            "p90_ms": float(np.percentile(lat_arr, 90)) * 1000,
            "p95_ms": float(np.percentile(lat_arr, 95)) * 1000,
            "p99_ms": float(np.percentile(lat_arr, 99)) * 1000,
            "texts_per_sec": texts_per_sec,
            "embeddings_per_sec": embeddings_per_sec,
            "chars_per_sec": chars_per_sec,
            "embedding_dim": dim,
            "normalized": self.normalize_embeddings,
            "n_samples": len(latencies),
            "raw_times": latencies,
        }

    def run(self) -> list[ResultDict]:
        """Execute the full embedding speed benchmark.

        Runs embedding speed measurements across all models, batch sizes,
        and text lengths.

        Returns:
            List of result dictionaries with timing metrics.
        """
        logger.info("Starting embedding speed benchmark")
        logger.info(
            "Embedders: %s, Batch sizes: %s, Text lengths: %s",
            self.embedders, self.batch_sizes, self.text_lengths,
        )

        results: list[ResultDict] = []
        total_start = time.monotonic()
        successful: int = 0
        total_configs: int = 0

        for model_name in self.embedders:
            logger.info("Benchmarking embedder: %s", model_name)

            for batch_size in self.batch_sizes:
                for text_length in self.text_lengths:
                    total_configs += 1
                    logger.debug(
                        "  Embedder=%s batch=%d text_len=%d",
                        model_name, batch_size, text_length,
                    )

                    try:
                        measure_results = self._measure_single_config(
                            model_name, batch_size, text_length
                        )

                        result: ResultDict = {
                            "benchmark": self.name,
                            "embedder": model_name,
                            "batch_size": batch_size,
                            "text_length": text_length,
                            "provider": self.provider,
                            "normalize": self.normalize_embeddings,
                        }

                        if "error" in measure_results:
                            result["error"] = measure_results["error"]
                        else:
                            for key, value in measure_results.items():
                                if isinstance(value, (int, float, str)):
                                    result[key] = value
                                elif key == "raw_times":
                                    result[key] = value
                            successful += 1

                        results.append(result)

                    except Exception as exc:
                        logger.error("Embedder '%s' batch=%d len=%d failed: %s",
                                     model_name, batch_size, text_length, exc)
                        results.append({
                            "benchmark": self.name,
                            "embedder": model_name,
                            "batch_size": batch_size,
                            "text_length": text_length,
                            "error": str(exc),
                        })

        total_elapsed = time.monotonic() - total_start
        logger.info(
            "Embedding speed benchmark completed in %.2fs. "
            "Successful: %d/%d configurations",
            total_elapsed, successful, total_configs,
        )

        return results

    def get_info(self) -> dict[str, Any]:
        """Return metadata about this benchmark configuration.

        Returns:
            Dictionary with benchmark metadata.
        """
        return {
            "name": self.name,
            "description": "Text embedding generation speed benchmark",
            "embedders": self.embedders,
            "batch_sizes": self.batch_sizes,
            "text_lengths": self.text_lengths,
            "iterations": self.iterations,
            "warmup": self.warmup,
            "normalize_embeddings": self.normalize_embeddings,
            "provider": self.provider,
            "timeout": self.timeout,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    bench = EmbeddingSpeedBenchmark()
    results = bench.run()
    print(f"Completed {len(results)} benchmark runs")

    for r in results:
        if "error" not in r:
            print(f"  {r['embedder'][:30]:>30s} batch={r['batch_size']:3d} "
                  f"len={r['text_length']:4d}: "
                  f"mean={r['mean_ms']:8.2f}ms  "
                  f"{r['embeddings_per_sec']:8.2f} emb/s")