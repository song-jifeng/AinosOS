"""
Tests for the benchmark runner and core components.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Add the project root to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from benchmarks import (
    BenchmarkConfigError,
    BenchmarkError,
    BenchmarkExecutionError,
    BenchmarkTimeoutError,
    DEFAULT_BENCHMARK_ITERATIONS,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_WARMUP_ITERATIONS,
)
from benchmarks.runner import BaseBenchmark, BenchmarkRunner


class TestBenchmarkErrors:
    """Tests for benchmark exception classes."""

    def test_benchmark_error_base(self) -> None:
        """Test basic BenchmarkError creation and string representation."""
        error = BenchmarkError("Test error")
        assert "Test error" in str(error)
        assert error.benchmark_name is None

    def test_benchmark_error_with_name(self) -> None:
        """Test BenchmarkError with benchmark name."""
        error = BenchmarkError("Test error", benchmark_name="test_bench")
        assert "test_bench" in str(error)
        assert error.benchmark_name == "test_bench"

    def test_benchmark_config_error(self) -> None:
        """Test BenchmarkConfigError with config key."""
        error = BenchmarkConfigError("Invalid config", config_key="sizes")
        assert "sizes" in str(error)
        assert error.config_key == "sizes"

    def test_benchmark_execution_error(self) -> None:
        """Test BenchmarkExecutionError with exit code."""
        error = BenchmarkExecutionError("Execution failed", exit_code=1)
        assert "exit=1" in str(error)
        assert error.exit_code == 1

    def test_benchmark_timeout_error(self) -> None:
        """Test BenchmarkTimeoutError."""
        error = BenchmarkTimeoutError(30)
        assert "30" in str(error)
        assert error.timeout_seconds == 30


class TestBaseBenchmark:
    """Tests for the BaseBenchmark class."""

    def test_initialization(self) -> None:
        """Test basic benchmark initialization."""
        bench = BaseBenchmark("test_bench", {"key": "value"})
        assert bench.name == "test_bench"
        assert bench.config == {"key": "value"}

    def test_default_config(self) -> None:
        """Test initialization with default config."""
        bench = BaseBenchmark("test_bench")
        assert bench.name == "test_bench"
        assert bench.config == {}

    def test_run_not_implemented(self) -> None:
        """Test that run() raises NotImplementedError."""
        bench = BaseBenchmark("test_bench")
        with pytest.raises(NotImplementedError):
            bench.run()

    def test_warmup(self) -> None:
        """Test warmup method (should not raise)."""
        bench = BaseBenchmark("test_bench")
        bench.warmup(5)  # Should not raise

    def test_get_info(self) -> None:
        """Test get_info returns expected structure."""
        bench = BaseBenchmark("test_bench")
        info = bench.get_info()
        assert info["name"] == "test_bench"
        assert "description" in info


class TestBenchmarkRunner:
    """Tests for the BenchmarkRunner class."""

    def test_initialization(self) -> None:
        """Test runner initialization."""
        runner = BenchmarkRunner(config={"global": {"output_dir": "/tmp"}})
        assert runner.config is not None
        assert runner.results == []

    def test_initialization_with_config_path(self, config_path: str) -> None:
        """Test runner initialization with config file path."""
        runner = BenchmarkRunner(config_path=config_path)
        assert runner.config is not None

    def test_initialization_with_invalid_config_path(self) -> None:
        """Test runner initialization with invalid config path."""
        with pytest.raises(BenchmarkConfigError):
            BenchmarkRunner(config_path="/nonexistent/config.yaml")

    def test_discover_micro_benchmarks(self) -> None:
        """Test discovering micro-benchmarks."""
        runner = BenchmarkRunner()
        benchmarks = runner.discover_benchmarks("micro")
        assert len(benchmarks) > 0
        for b in benchmarks:
            assert hasattr(b, "run")
            assert hasattr(b, "name")

    def test_discover_kernel_benchmarks(self) -> None:
        """Test discovering kernel benchmarks."""
        runner = BenchmarkRunner()
        benchmarks = runner.discover_benchmarks("kernel")
        assert len(benchmarks) > 0

    def test_discover_ai_benchmarks(self) -> None:
        """Test discovering AI benchmarks."""
        runner = BenchmarkRunner()
        benchmarks = runner.discover_benchmarks("ai")
        assert len(benchmarks) > 0

    def test_discover_sdk_benchmarks(self) -> None:
        """Test discovering SDK benchmarks."""
        runner = BenchmarkRunner()
        benchmarks = runner.discover_benchmarks("sdk")
        assert len(benchmarks) > 0

    def test_discover_all_benchmarks(self) -> None:
        """Test discovering all benchmarks."""
        runner = BenchmarkRunner()
        benchmarks = runner.discover_benchmarks()
        assert len(benchmarks) > 0

    def test_discover_unknown_category(self) -> None:
        """Test discovering benchmarks from unknown category."""
        runner = BenchmarkRunner()
        benchmarks = runner.discover_benchmarks("nonexistent")
        assert len(benchmarks) == 0

    @pytest.mark.slow
    def test_run_micro_benchmarks(self, benchmark_config: dict[str, Any]) -> None:
        """Test running micro-benchmarks."""
        runner = BenchmarkRunner(config=benchmark_config)
        results = runner.run_category("micro", "test_micro_run")
        assert len(results) > 0
        # Check some results have expected structure
        for r in results:
            assert "benchmark" in r
            if "error" not in r:
                assert "mean_s" in r or "mean_ms" in r or "mean_ns" in r

    @pytest.mark.slow
    def test_run_kernel_benchmarks(self, benchmark_config: dict[str, Any]) -> None:
        """Test running kernel benchmarks."""
        runner = BenchmarkRunner(config=benchmark_config)
        results = runner.run_category("kernel", "test_kernel_run")
        assert len(results) > 0

    @pytest.mark.slow
    def test_run_ai_benchmarks(self, benchmark_config: dict[str, Any]) -> None:
        """Test running AI benchmarks."""
        runner = BenchmarkRunner(config=benchmark_config)
        results = runner.run_category("ai", "test_ai_run")
        assert len(results) > 0

    @pytest.mark.slow
    def test_run_sdk_benchmarks(self, benchmark_config: dict[str, Any]) -> None:
        """Test running SDK benchmarks."""
        runner = BenchmarkRunner(config=benchmark_config)
        results = runner.run_category("sdk", "test_sdk_run")
        assert len(results) > 0

    def test_run_disabled_category(self, benchmark_config: dict[str, Any]) -> None:
        """Test running a disabled category."""
        config = benchmark_config.copy()
        config["micro"] = {"enabled": False, "matrix_mul": {"enabled": False}}
        runner = BenchmarkRunner(config=config)
        results = runner.run_category("micro", "test_disabled")
        assert len(results) == 0

    @pytest.mark.slow
    def test_run_all_benchmarks(self, benchmark_config: dict[str, Any]) -> None:
        """Test running all benchmarks."""
        runner = BenchmarkRunner(config=benchmark_config)
        results = runner.run_all("test_all_run")
        assert len(results) > 0

    @pytest.mark.slow
    def test_benchmark_results_structure(self, benchmark_config: dict[str, Any]) -> None:
        """Test that benchmark results have expected structure."""
        runner = BenchmarkRunner(config=benchmark_config)
        results = runner.run_category("micro", "test_structure")

        for r in results:
            assert "benchmark" in r
            assert isinstance(r["benchmark"], str)
            if "error" not in r:
                # Must have at least one timing metric
                has_timing = any(
                    key in r for key in
                    ["mean_s", "mean_ms", "mean_ns", "mean_us", "throughput_MBps",
                     "requests_per_sec", "gflops", "bandwidth_GBs", "mean_rss_MB"]
                )
                assert has_timing, f"Result for {r['benchmark']} has no timing metric: {r.keys()}"

    def test_generate_html_report(self, temp_output_dir: str, sample_results: list[dict[str, Any]]) -> None:
        """Test generating HTML report."""
        runner = BenchmarkRunner(config={"reports": {"output_dir": temp_output_dir}})
        report_path = runner.generate_report(sample_results, format="html")
        assert report_path is not None
        assert os.path.exists(report_path), f"Report not found at {report_path}"
        with open(report_path) as f:
            content = f.read()
            assert "Ainos" in content or "Benchmark" in content

    def test_generate_json_report(self, temp_output_dir: str, sample_results: list[dict[str, Any]]) -> None:
        """Test generating JSON report."""
        runner = BenchmarkRunner(config={"reports": {"output_dir": temp_output_dir}})
        report_path = runner.generate_report(sample_results, format="json")
        assert report_path is not None
        assert os.path.exists(report_path)
        with open(report_path) as f:
            data = json.load(f)
            assert "results" in data
            assert len(data["results"]) == len(sample_results)

    def test_export_json(self, temp_output_dir: str, sample_results: list[dict[str, Any]]) -> None:
        """Test exporting results as JSON."""
        runner = BenchmarkRunner(config={"reports": {"output_dir": temp_output_dir}})
        export_path = runner.export_results(sample_results, format="json")
        assert export_path is not None
        assert os.path.exists(export_path)

    def test_export_csv(self, temp_output_dir: str, sample_results: list[dict[str, Any]]) -> None:
        """Test exporting results as CSV."""
        runner = BenchmarkRunner(config={"reports": {"output_dir": temp_output_dir}})
        from benchmarks.reports.json_report import JSONReportGenerator
        gen = JSONReportGenerator({"output_dir": temp_output_dir})
        csv_path = gen.export_csv(sample_results)
        assert csv_path is not None
        assert os.path.exists(csv_path)

    def test_generate_report_no_results(self, temp_output_dir: str) -> None:
        """Test generating report with no results."""
        runner = BenchmarkRunner(config={"reports": {"output_dir": temp_output_dir}})
        report_path = runner.generate_report([], format="html")
        assert report_path == ""

    def test_deep_merge(self) -> None:
        """Test deep merge utility."""
        base = {"a": 1, "b": {"c": 2, "d": 3}}
        override = {"b": {"c": 4, "e": 5}, "f": 6}
        BenchmarkRunner._deep_merge(base, override)
        assert base["a"] == 1
        assert base["b"]["c"] == 4
        assert base["b"]["d"] == 3
        assert base["b"]["e"] == 5
        assert base["f"] == 6

    def test_benchmark_error_accumulation(self, benchmark_config: dict[str, Any]) -> None:
        """Test that errors are properly accumulated during benchmark runs."""
        runner = BenchmarkRunner(config=benchmark_config)
        # Run with minimal config to ensure no real errors
        results = runner.run_category("micro", "test_errors")
        # Check that error results are properly structured
        for r in results:
            if "error" in r:
                assert isinstance(r["error"], str)
                assert "benchmark" in r


class TestMicroBenchmarks:
    """Tests for micro-benchmarks."""

    @pytest.mark.micro
    def test_matrix_mul_benchmark(self, benchmark_config: dict[str, Any]) -> None:
        """Test matrix multiplication benchmark."""
        from benchmarks.micro.matrix_mul import MatrixMultiplicationBenchmark
        bench = MatrixMultiplicationBenchmark(benchmark_config["micro"]["matrix_mul"])
        results = bench.run()
        assert len(results) > 0
        for r in results:
            if "error" not in r:
                assert r["size"] in [16, 32]
                assert "gflops" in r
                assert r["gflops"] > 0

    @pytest.mark.micro
    def test_memory_bandwidth_benchmark(self, benchmark_config: dict[str, Any]) -> None:
        """Test memory bandwidth benchmark."""
        from benchmarks.micro.memory_bandwidth import MemoryBandwidthBenchmark
        bench = MemoryBandwidthBenchmark(benchmark_config["micro"]["memory_bandwidth"])
        results = bench.run()
        assert len(results) > 0
        for r in results:
            if "error" not in r:
                assert "buffer_size_bytes" in r
                assert "read_bandwidth_GBs" in r or "read_bandwidth_GBs" in r

    @pytest.mark.micro
    def test_cache_latency_benchmark(self, benchmark_config: dict[str, Any]) -> None:
        """Test cache latency benchmark."""
        from benchmarks.micro.cache_latency import CacheLatencyBenchmark
        bench = CacheLatencyBenchmark(benchmark_config["micro"]["cache_latency"])
        results = bench.run()
        assert len(results) > 0

    @pytest.mark.micro
    def test_vector_ops_benchmark(self, benchmark_config: dict[str, Any]) -> None:
        """Test vector operations benchmark."""
        from benchmarks.micro.vector_ops import VectorOpsBenchmark
        bench = VectorOpsBenchmark(benchmark_config["micro"]["vector_ops"])
        results = bench.run()
        assert len(results) > 0
        for r in results:
            if "error" not in r:
                assert "operation" in r
                assert "throughput_ops_s" in r

    @pytest.mark.micro
    def test_tcp_throughput_benchmark(self, benchmark_config: dict[str, Any]) -> None:
        """Test TCP throughput benchmark."""
        from benchmarks.micro.tcp_throughput import TCPThroughputBenchmark
        bench = TCPThroughputBenchmark(benchmark_config["micro"]["tcp_throughput"])
        results = bench.run()
        assert len(results) > 0

    @pytest.mark.micro
    def test_json_parse_benchmark(self, benchmark_config: dict[str, Any]) -> None:
        """Test JSON parse benchmark."""
        from benchmarks.micro.json_parse import JSONParseBenchmark
        bench = JSONParseBenchmark(benchmark_config["micro"]["json_parse"])
        results = bench.run()
        assert len(results) > 0
        for r in results:
            if "error" not in r:
                assert "library" in r
                assert "throughput_MBps" in r or "mean_s" in r


class TestKernelBenchmarks:
    """Tests for kernel benchmarks."""

    @pytest.mark.kernel
    def test_syscall_latency_benchmark(self, benchmark_config: dict[str, Any]) -> None:
        """Test syscall latency benchmark."""
        from benchmarks.kernel.syscall_latency import SyscallLatencyBenchmark
        bench = SyscallLatencyBenchmark(benchmark_config["kernel"]["syscall_latency"])
        results = bench.run()
        assert len(results) > 0
        for r in results:
            if "error" not in r:
                assert "syscall" in r
                assert "mean_ns" in r

    @pytest.mark.kernel
    def test_context_switch_benchmark(self, benchmark_config: dict[str, Any]) -> None:
        """Test context switch benchmark."""
        from benchmarks.kernel.context_switch import ContextSwitchBenchmark
        bench = ContextSwitchBenchmark(benchmark_config["kernel"]["context_switch"])
        results = bench.run()
        assert len(results) > 0

    @pytest.mark.kernel
    def test_ipc_throughput_benchmark(self, benchmark_config: dict[str, Any]) -> None:
        """Test IPC throughput benchmark."""
        from benchmarks.kernel.ipc_throughput import IPCThroughputBenchmark
        bench = IPCThroughputBenchmark(benchmark_config["kernel"]["ipc_throughput"])
        results = bench.run()
        assert len(results) > 0

    @pytest.mark.kernel
    def test_memory_alloc_benchmark(self, benchmark_config: dict[str, Any]) -> None:
        """Test memory allocation benchmark."""
        from benchmarks.kernel.memory_alloc import MemoryAllocBenchmark
        bench = MemoryAllocBenchmark(benchmark_config["kernel"]["memory_alloc"])
        results = bench.run()
        assert len(results) > 0


class TestAI_Benchmarks:
    """Tests for AI benchmarks."""

    @pytest.mark.ai
    def test_inference_latency_benchmark(self, benchmark_config: dict[str, Any]) -> None:
        """Test inference latency benchmark."""
        from benchmarks.ai.inference_latency import InferenceLatencyBenchmark
        bench = InferenceLatencyBenchmark(benchmark_config["ai"]["inference_latency"])
        results = bench.run()
        assert len(results) > 0

    @pytest.mark.ai
    def test_inference_throughput_benchmark(self, benchmark_config: dict[str, Any]) -> None:
        """Test inference throughput benchmark."""
        from benchmarks.ai.inference_throughput import InferenceThroughputBenchmark
        bench = InferenceThroughputBenchmark(benchmark_config["ai"]["inference_throughput"])
        results = bench.run()
        assert len(results) > 0

    @pytest.mark.ai
    def test_embedding_speed_benchmark(self, benchmark_config: dict[str, Any]) -> None:
        """Test embedding speed benchmark."""
        from benchmarks.ai.embedding_speed import EmbeddingSpeedBenchmark
        bench = EmbeddingSpeedBenchmark(benchmark_config["ai"]["embedding_speed"])
        results = bench.run()
        assert len(results) > 0

    @pytest.mark.ai
    def test_search_latency_benchmark(self, benchmark_config: dict[str, Any]) -> None:
        """Test search latency benchmark."""
        from benchmarks.ai.search_latency import SearchLatencyBenchmark
        bench = SearchLatencyBenchmark(benchmark_config["ai"]["search_latency"])
        results = bench.run()
        assert len(results) > 0

    @pytest.mark.ai
    def test_model_load_benchmark(self, benchmark_config: dict[str, Any]) -> None:
        """Test model load benchmark."""
        from benchmarks.ai.model_load import ModelLoadBenchmark
        bench = ModelLoadBenchmark(benchmark_config["ai"]["model_load"])
        results = bench.run()
        assert len(results) > 0


class TestSDKBenchmarks:
    """Tests for SDK benchmarks."""

    @pytest.mark.sdk
    def test_sdk_latency_benchmark(self, benchmark_config: dict[str, Any]) -> None:
        """Test SDK latency benchmark."""
        from benchmarks.sdk.sdk_latency import SDKLatencyBenchmark
        bench = SDKLatencyBenchmark(benchmark_config["sdk"]["sdk_latency"])
        results = bench.run()
        assert len(results) > 0

    @pytest.mark.sdk
    def test_sdk_throughput_benchmark(self, benchmark_config: dict[str, Any]) -> None:
        """Test SDK throughput benchmark."""
        from benchmarks.sdk.sdk_throughput import SDKThroughputBenchmark
        bench = SDKThroughputBenchmark(benchmark_config["sdk"]["sdk_throughput"])
        results = bench.run()
        assert len(results) > 0

    @pytest.mark.sdk
    def test_sdk_memory_benchmark(self, benchmark_config: dict[str, Any]) -> None:
        """Test SDK memory benchmark."""
        from benchmarks.sdk.sdk_memory import SDKMemoryBenchmark
        bench = SDKMemoryBenchmark(benchmark_config["sdk"]["sdk_memory"])
        results = bench.run()
        assert len(results) > 0


class TestReports:
    """Tests for report generation."""

    def test_report_generator_statistics(self) -> None:
        """Test statistics computation."""
        from benchmarks.reports.report_generator import ReportGenerator
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        stats = ReportGenerator.compute_statistics(data)
        assert stats["count"] == 5
        assert stats["mean"] == 3.0
        assert stats["median"] == 3.0
        assert stats["min"] == 1.0
        assert stats["max"] == 5.0
        assert stats["p50"] == 3.0
        assert stats["p90"] == 4.6

    def test_report_generator_statistics_empty(self) -> None:
        """Test statistics computation with empty data."""
        from benchmarks.reports.report_generator import ReportGenerator
        stats = ReportGenerator.compute_statistics([])
        assert stats == {}

    def test_aggregate_results(self, sample_results: list[dict[str, Any]]) -> None:
        """Test result aggregation."""
        from benchmarks.reports.report_generator import ReportGenerator
        aggregated = ReportGenerator.aggregate_results(sample_results, "benchmark")
        assert "matrix_mul" in aggregated
        assert len(aggregated["matrix_mul"]) == len(sample_results)

    def test_filter_results(self, sample_results: list[dict[str, Any]]) -> None:
        """Test result filtering."""
        from benchmarks.reports.report_generator import ReportGenerator
        filtered = ReportGenerator.filter_results(sample_results, {"size": 64})
        assert len(filtered) == 1
        assert filtered[0]["size"] == 64

    def test_compare_results(self, sample_results: list[dict[str, Any]]) -> None:
        """Test result comparison."""
        from benchmarks.reports.report_generator import ReportGenerator
        # Split results into two groups
        results_a = [r for r in sample_results if r["size"] == 64]
        results_b = [r for r in sample_results if r["size"] == 128]
        if results_a and results_b:
            comparison = ReportGenerator.compare_results(results_a, results_b, "mean_ms")
            assert "comparisons" in comparison
            assert "summary" in comparison

    def test_html_report_generation(self, temp_output_dir: str, sample_results: list[dict[str, Any]]) -> None:
        """Test full HTML report generation."""
        from benchmarks.reports.html_report import HTMLReportGenerator
        gen = HTMLReportGenerator({"output_dir": temp_output_dir})
        path = gen.generate_report(sample_results, "test_report")
        assert os.path.exists(path)
        with open(path) as f:
            content = f.read()
            assert "Ainos" in content or "Benchmark" in content
            assert "summary" in content.lower() or "Summary" in content

    def test_json_report_generation(self, temp_output_dir: str, sample_results: list[dict[str, Any]]) -> None:
        """Test full JSON report generation."""
        from benchmarks.reports.json_report import JSONReportGenerator
        gen = JSONReportGenerator({"output_dir": temp_output_dir, "pretty_print": True})
        path = gen.generate_report(sample_results, "test_report")
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
            assert "report_metadata" in data
            assert "results" in data
            assert data["report_metadata"]["total_results"] == len(sample_results)

    def test_json_report_metadata(self, temp_output_dir: str, sample_results: list[dict[str, Any]]) -> None:
        """Test JSON report metadata inclusion."""
        from benchmarks.reports.json_report import JSONReportGenerator
        gen = JSONReportGenerator({"output_dir": temp_output_dir, "include_metadata": True})
        path = gen.generate_report(sample_results)
        with open(path) as f:
            data = json.load(f)
            assert "system_info" in data

    def test_chart_generation(self, temp_output_dir: str, sample_results: list[dict[str, Any]]) -> None:
        """Test chart generation."""
        try:
            from benchmarks.reports.chart import ChartGenerator
            gen = ChartGenerator({"output_dir": temp_output_dir, "dpi": 72})

            chart_path = os.path.join(temp_output_dir, "test_chart.png")
            result = gen.plot_latency_comparison(sample_results, chart_path)
            # Chart generation might fail without matplotlib
            assert result is not None
        except ImportError:
            pytest.skip("Matplotlib not available for chart generation")


class TestDataPersistence:
    """Tests for data persistence modules."""

    def test_results_store_creation(self, temp_output_dir: str) -> None:
        """Test results store creation and schema initialization."""
        from benchmarks.data.results_store import ResultsStore
        db_path = os.path.join(temp_output_dir, "test_results.db")
        store = ResultsStore({"path": db_path, "wal_mode": False})
        assert store.db_path == db_path
        store.close()

    def test_create_run(self, temp_output_dir: str) -> None:
        """Test creating a benchmark run."""
        from benchmarks.data.results_store import ResultsStore
        db_path = os.path.join(temp_output_dir, "test_create.db")
        store = ResultsStore({"path": db_path, "wal_mode": False})
        run_id = store.create_run("test_run", "matrix_mul", {"size": 64})
        assert run_id > 0

        run = store.get_run(run_id)
        assert run is not None
        assert run["run_name"] == "test_run"
        assert run["benchmark_name"] == "matrix_mul"
        store.close()

    def test_store_and_retrieve_results(self, temp_output_dir: str, sample_results: list[dict[str, Any]]) -> None:
        """Test storing and retrieving benchmark results."""
        from benchmarks.data.results_store import ResultsStore
        db_path = os.path.join(temp_output_dir, "test_store.db")
        store = ResultsStore({"path": db_path, "wal_mode": False})

        run_id = store.create_run("test_store", "matrix_mul")
        stored_ids = store.store_results(run_id, sample_results)
        assert len(stored_ids) == len(sample_results)

        retrieved = store.get_results(run_id)
        assert len(retrieved) == len(sample_results)
        store.close()

    def test_complete_run(self, temp_output_dir: str) -> None:
        """Test completing a benchmark run."""
        from benchmarks.data.results_store import ResultsStore
        db_path = os.path.join(temp_output_dir, "test_complete.db")
        store = ResultsStore({"path": db_path, "wal_mode": False})

        run_id = store.create_run("test_complete", "matrix_mul")
        store.complete_run(run_id, "completed")

        run = store.get_run(run_id)
        assert run["status"] == "completed"
        assert run["end_time"] is not None
        store.close()

    def test_recent_runs(self, temp_output_dir: str) -> None:
        """Test retrieving recent runs."""
        from benchmarks.data.results_store import ResultsStore
        db_path = os.path.join(temp_output_dir, "test_recent.db")
        store = ResultsStore({"path": db_path, "wal_mode": False})

        for i in range(3):
            store.create_run(f"run_{i}", "matrix_mul")

        recent = store.get_recent_runs(limit=2)
        assert len(recent) == 2
        store.close()

    def test_delete_run(self, temp_output_dir: str, sample_results: list[dict[str, Any]]) -> None:
        """Test deleting a benchmark run."""
        from benchmarks.data.results_store import ResultsStore
        db_path = os.path.join(temp_output_dir, "test_delete.db")
        store = ResultsStore({"path": db_path, "wal_mode": False})

        run_id = store.create_run("test_delete", "matrix_mul")
        store.store_results(run_id, sample_results)

        assert store.delete_run(run_id) is True
        assert store.get_run(run_id) is None
        assert len(store.get_results(run_id)) == 0
        store.close()

    def test_run_summary(self, temp_output_dir: str, sample_results: list[dict[str, Any]]) -> None:
        """Test run summary generation."""
        from benchmarks.data.results_store import ResultsStore
        db_path = os.path.join(temp_output_dir, "test_summary.db")
        store = ResultsStore({"path": db_path, "wal_mode": False})

        run_id = store.create_run("test_summary", "matrix_mul")
        store.store_results(run_id, sample_results)
        store.complete_run(run_id, "completed")

        summary = store.get_run_summary(run_id)
        assert summary["total_results"] == len(sample_results)
        store.close()

    def test_metadata_storage(self, temp_output_dir: str) -> None:
        """Test storing and retrieving metadata."""
        from benchmarks.data.results_store import ResultsStore
        db_path = os.path.join(temp_output_dir, "test_meta.db")
        store = ResultsStore({"path": db_path, "wal_mode": False})

        run_id = store.create_run("test_meta", "matrix_mul")
        store.store_metadata(run_id, {"key1": "value1", "key2": 42})

        # Metadata is stored but not directly retrievable via public API
        # This just tests that no exception is raised
        store.close()

    def test_export_run_json(self, temp_output_dir: str, sample_results: list[dict[str, Any]]) -> None:
        """Test exporting a run as JSON."""
        from benchmarks.data.results_store import ResultsStore
        db_path = os.path.join(temp_output_dir, "test_export.db")
        store = ResultsStore({"path": db_path, "wal_mode": False})

        run_id = store.create_run("test_export", "matrix_mul")
        store.store_results(run_id, sample_results)
        store.complete_run(run_id, "completed")

        json_str = store.export_run_json(run_id)
        assert json_str is not None
        data = json.loads(json_str)
        assert data["run"]["run_name"] == "test_export"
        assert len(data["results"]) == len(sample_results)
        store.close()

    def test_history_tracker(self, temp_output_dir: str, sample_results: list[dict[str, Any]]) -> None:
        """Test history tracker."""
        from benchmarks.data.results_store import ResultsStore
        from benchmarks.data.history import HistoryTracker

        db_path = os.path.join(temp_output_dir, "test_history.db")
        store = ResultsStore({"path": db_path, "wal_mode": False})
        tracker = HistoryTracker({}, store)

        run_id = store.create_run("test_history", "matrix_mul")
        store.store_results(run_id, sample_results)
        count = tracker.record_run(run_id, sample_results)
        assert count > 0
        store.complete_run(run_id, "completed")

        trend = tracker.get_trend("matrix_mul", "mean_ms", days=30)
        assert trend["data_points"] > 0
        store.close()

    def test_comparison_analyzer(self, sample_results: list[dict[str, Any]]) -> None:
        """Test comparison analyzer."""
        from benchmarks.data.comparison import ComparisonAnalyzer

        analyzer = ComparisonAnalyzer()
        results_a = [r for r in sample_results if r["size"] == 64]
        results_b = [r for r in sample_results if r["size"] == 128]

        if results_a and results_b:
            comparison = analyzer.compare_results(results_a, results_b, "mean_ms")
            assert "comparisons" in comparison
            assert "summary" in comparison

    def test_statistical_tests(self) -> None:
        """Test statistical test functions."""
        from benchmarks.data.comparison import ComparisonAnalyzer

        analyzer = ComparisonAnalyzer()

        # Paired t-test
        baseline = [100, 102, 98, 101, 99]
        target = [95, 97, 93, 96, 94]
        result = analyzer.paired_ttest(baseline, target)
        assert "t_statistic" in result
        assert "p_value" in result
        assert result["p_value"] < 0.05  # Should be significant

        # Independent t-test
        result = analyzer.independent_ttest(baseline, target)
        assert "t_statistic" in result

        # Mann-Whitney
        result = analyzer.mann_whitney_test(baseline, target)
        assert "u_statistic" in result

    def test_speedup_computation(self) -> None:
        """Test speedup computation."""
        from benchmarks.data.comparison import ComparisonAnalyzer

        speedup = ComparisonAnalyzer.compute_speedup(100, 50)
        assert speedup["speedup"] == 0.5
        assert speedup["pct_change"] == -50.0
        assert speedup["direction"] == "improved"

        speedup = ComparisonAnalyzer.compute_speedup(100, 150)
        assert speedup["speedup"] == 1.5
        assert speedup["pct_change"] == 50.0
        assert speedup["direction"] == "regressed"

    def test_regression_detection(self, sample_latency_results: list[dict[str, Any]]) -> None:
        """Test regression detection."""
        from benchmarks.data.comparison import ComparisonAnalyzer

        analyzer = ComparisonAnalyzer()
        # Create slight regression in results
        regressed = []
        for r in sample_latency_results:
            if "error" not in r:
                r = r.copy()
                r["mean_ms"] = r["mean_ms"] * 1.15  # 15% regression
                regressed.append(r)

        if sample_latency_results and regressed:
            regressions = analyzer.detect_regressions(
                sample_latency_results, regressed, "mean_ms", regression_threshold=5.0
            )
            assert len(regressions) > 0


class TestImportAndPackage:
    """Tests for package imports and structure."""

    def test_import_benchmarks(self) -> None:
        """Test that the benchmarks package can be imported."""
        import benchmarks
        assert benchmarks.__version__ == "1.0.0"

    def test_import_micro(self) -> None:
        """Test importing micro-benchmark modules."""
        from benchmarks.micro import (
            MatrixMultiplicationBenchmark,
            MemoryBandwidthBenchmark,
            CacheLatencyBenchmark,
            VectorOpsBenchmark,
            TCPThroughputBenchmark,
            JSONParseBenchmark,
        )
        assert MatrixMultiplicationBenchmark is not None
        assert MemoryBandwidthBenchmark is not None
        assert CacheLatencyBenchmark is not None
        assert VectorOpsBenchmark is not None
        assert TCPThroughputBenchmark is not None
        assert JSONParseBenchmark is not None

    def test_import_kernel(self) -> None:
        """Test importing kernel benchmark modules."""
        from benchmarks.kernel import (
            SyscallLatencyBenchmark,
            ContextSwitchBenchmark,
            IPCThroughputBenchmark,
            MemoryAllocBenchmark,
        )
        assert SyscallLatencyBenchmark is not None
        assert ContextSwitchBenchmark is not None
        assert IPCThroughputBenchmark is not None
        assert MemoryAllocBenchmark is not None

    def test_import_ai(self) -> None:
        """Test importing AI benchmark modules."""
        from benchmarks.ai import (
            InferenceLatencyBenchmark,
            InferenceThroughputBenchmark,
            EmbeddingSpeedBenchmark,
            SearchLatencyBenchmark,
            ModelLoadBenchmark,
        )
        assert InferenceLatencyBenchmark is not None
        assert InferenceThroughputBenchmark is not None
        assert EmbeddingSpeedBenchmark is not None
        assert SearchLatencyBenchmark is not None
        assert ModelLoadBenchmark is not None

    def test_import_sdk(self) -> None:
        """Test importing SDK benchmark modules."""
        from benchmarks.sdk import (
            SDKLatencyBenchmark,
            SDKThroughputBenchmark,
            SDKMemoryBenchmark,
        )
        assert SDKLatencyBenchmark is not None
        assert SDKThroughputBenchmark is not None
        assert SDKMemoryBenchmark is not None

    def test_import_reports(self) -> None:
        """Test importing report modules."""
        from benchmarks.reports import (
            ReportGenerator,
            HTMLReportGenerator,
            JSONReportGenerator,
            ChartGenerator,
        )
        assert ReportGenerator is not None
        assert HTMLReportGenerator is not None
        assert JSONReportGenerator is not None
        assert ChartGenerator is not None

    def test_import_data(self) -> None:
        """Test importing data modules."""
        from benchmarks.data import (
            ResultsStore,
            ComparisonAnalyzer,
            HistoryTracker,
        )
        assert ResultsStore is not None
        assert ComparisonAnalyzer is not None
        assert HistoryTracker is not None


class TestBenchmarkEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_config(self) -> None:
        """Test benchmarks with empty configuration."""
        from benchmarks.micro.matrix_mul import MatrixMultiplicationBenchmark
        bench = MatrixMultiplicationBenchmark({})
        # Should use defaults
        assert bench.sizes is not None
        assert bench.iterations > 0

    def test_invalid_dtype(self) -> None:
        """Test benchmark with invalid dtype configuration."""
        from benchmarks.micro.matrix_mul import MatrixMultiplicationBenchmark
        with pytest.raises(BenchmarkConfigError):
            MatrixMultiplicationBenchmark({"dtype": "invalid"})

    def test_negative_size(self) -> None:
        """Test benchmark with negative size."""
        from benchmarks.micro.matrix_mul import MatrixMultiplicationBenchmark
        with pytest.raises(BenchmarkConfigError):
            MatrixMultiplicationBenchmark({"sizes": [-1]})

    def test_zero_iterations(self) -> None:
        """Test benchmark with zero iterations."""
        from benchmarks.micro.matrix_mul import MatrixMultiplicationBenchmark
        with pytest.raises(BenchmarkConfigError):
            MatrixMultiplicationBenchmark({"iterations": 0})

    def test_benchmark_info(self) -> None:
        """Test benchmark info method."""
        from benchmarks.micro.matrix_mul import MatrixMultiplicationBenchmark
        bench = MatrixMultiplicationBenchmark()
        info = bench.get_info()
        assert info["name"] == "matrix_mul"
        assert "description" in info
        assert "sizes" in info

    @pytest.mark.slow
    def test_blocked_comparison(self) -> None:
        """Test blocked vs BLAS comparison."""
        from benchmarks.micro.matrix_mul import MatrixMultiplicationBenchmark
        bench = MatrixMultiplicationBenchmark({"sizes": [32], "iterations": 2, "warmup": 1})
        comparison = bench.run_blocked_comparison(size=32)
        assert "blas_mean_s" in comparison
        assert "blocked_mean_s" in comparison
        assert "speedup" in comparison

    def test_memory_profile(self) -> None:
        """Test memory profiling."""
        from benchmarks.micro.matrix_mul import MatrixMultiplicationBenchmark
        bench = MatrixMultiplicationBenchmark()
        profile = bench.profile_memory_usage(size=32)
        assert "matrix_a_bytes" in profile
        assert "peak_memory_bytes" in profile

    def test_cache_detection(self) -> None:
        """Test cache hierarchy detection."""
        from benchmarks.micro.cache_latency import CacheLatencyBenchmark
        bench = CacheLatencyBenchmark()
        cache_info = bench.detect_cache_sizes()
        assert "l1_latency_ns" in cache_info
        assert "ram_latency_ns" in cache_info

    def test_bandwidth_cache_analysis(self) -> None:
        """Test cache hierarchy analysis from bandwidth benchmark."""
        from benchmarks.micro.memory_bandwidth import MemoryBandwidthBenchmark
        bench = MemoryBandwidthBenchmark({"buffer_sizes": ["1KB", "1MB"], "iterations": 2, "warmup": 1})
        analysis = bench.analyze_cache_hierarchy()
        assert "peak_read_bandwidth_GBs" in analysis
        assert "cache_drops" in analysis

    def test_simd_comparison(self) -> None:
        """Test SIMD comparison."""
        from benchmarks.micro.vector_ops import VectorOpsBenchmark
        bench = VectorOpsBenchmark({"sizes": [100], "iterations": 2, "warmup": 1})
        comparison = bench.simd_comparison(size=100)
        assert "comparisons" in comparison

    def test_format_comparison(self) -> None:
        """Test model format comparison."""
        from benchmarks.ai.model_load import ModelLoadBenchmark
        bench = ModelLoadBenchmark({"model_types": ["bert-base-uncased"], "formats": ["pytorch"],
                                    "iterations": 2, "warmup": 1})
        comparison = bench.format_comparison("bert-base-uncased")
        assert "comparisons" in comparison

    def test_batch_scaling(self) -> None:
        """Test batch size scaling analysis."""
        from benchmarks.ai.inference_latency import InferenceLatencyBenchmark
        bench = InferenceLatencyBenchmark({"model_types": ["bert-base-uncased"],
                                           "batch_sizes": [1, 2], "iterations": 2, "warmup": 1})
        analysis = bench.batch_size_scaling_analysis("bert-base-uncased")
        assert "batch_sizes" in analysis
        assert "scaling_efficiency" in analysis