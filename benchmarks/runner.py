"""
Benchmark Runner
=================

Main entry point for running performance benchmarks. Provides a unified
interface for discovering, configuring, and executing all benchmark types.

This module supports:
- CLI interface for running benchmarks
- Benchmark discovery and registration
- Configuration management (YAML)
- Result aggregation and reporting
- Progress tracking and logging
- Multi-benchmark orchestration
"""

from __future__ import annotations

import argparse
import inspect
import logging
import os
import sys
import time
import yaml
from typing import Any

from benchmarks import (
    BenchmarkConfigError,
    BenchmarkExecutionError,
    BenchmarkError,
    BenchmarkTimeoutError,
    DEFAULT_BENCHMARK_ITERATIONS,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_WARMUP_ITERATIONS,
    ResultDict,
)

logger = logging.getLogger(__name__)


class BaseBenchmark:
    """Base class for all benchmarks.

    Provides common functionality for benchmark initialization, execution,
    and result reporting.

    Attributes:
        name: Unique identifier for this benchmark.
        config: Configuration dictionary.
    """

    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:
        """Initialize the benchmark.

        Args:
            name: Unique identifier for this benchmark.
            config: Configuration dictionary.
        """
        self.name: str = name
        self.config: dict[str, Any] = config or {}

    def run(self) -> list[ResultDict]:
        """Execute the benchmark.

        Returns:
            List of result dictionaries.

        Raises:
            NotImplementedError: Subclasses must implement this method.
        """
        raise NotImplementedError(f"Benchmark '{self.name}' must implement run()")

    def warmup(self, iterations: int = DEFAULT_WARMUP_ITERATIONS) -> None:
        """Perform warmup iterations.

        Args:
            iterations: Number of warmup iterations.
        """
        logger.info("Warming up %s (%d iterations)", self.name, iterations)

    def get_info(self) -> dict[str, Any]:
        """Return metadata about this benchmark.

        Returns:
            Dictionary with benchmark metadata.
        """
        return {
            "name": self.name,
            "description": "Base benchmark class",
        }


class BenchmarkRunner:
    """Main runner for discovering and executing benchmarks.

    Orchestrates the benchmark execution process including configuration
    loading, benchmark discovery, execution, and result aggregation.

    Attributes:
        config: Global configuration dictionary.
        results: List of all benchmark results accumulated during runs.
        verbose: Whether to enable verbose logging.
        output_dir: Directory for output files.
    """

    def __init__(self, config_path: str | None = None, config: dict[str, Any] | None = None) -> None:
        """Initialize the benchmark runner.

        Args:
            config_path: Path to YAML configuration file.
            config: Configuration dictionary (overrides loaded config).

        Raises:
            BenchmarkConfigError: If configuration loading fails.
        """
        self.config: dict[str, Any] = config or {}
        self.results: list[ResultDict] = []
        self.verbose: bool = False
        self.output_dir: str = "reports/output"

        # Load configuration from file if specified
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    file_config = yaml.safe_load(f)
                if file_config:
                    # Deep merge
                    self._deep_merge(self.config, file_config)
                logger.info("Loaded configuration from %s", config_path)
            except Exception as exc:
                raise BenchmarkConfigError(f"Failed to load config from {config_path}: {exc}")

        # Set defaults from config
        self._apply_config_defaults()

        logger.info("Initialized BenchmarkRunner")

    def _apply_config_defaults(self) -> None:
        """Apply default values from configuration."""
        global_config = self.config.get("global", {})

        self.output_dir = global_config.get("output_dir", self.output_dir)

        # Logging setup
        log_level = global_config.get("log_level", "INFO").upper()
        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
        """Deep merge two dictionaries.

        Args:
            base: Base dictionary (modified in place).
            override: Override dictionary.
        """
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                BenchmarkRunner._deep_merge(base[key], value)
            else:
                base[key] = value

    def discover_benchmarks(
        self, category: str | None = None
    ) -> list[BaseBenchmark]:
        """Discover available benchmarks.

        Args:
            category: Optional category filter (micro, kernel, ai, sdk).

        Returns:
            List of instantiated benchmark objects.

        Raises:
            BenchmarkConfigError: If benchmark discovery fails.
        """
        benchmarks: list[BaseBenchmark] = []

        # Define benchmark registry
        registry: dict[str, list[tuple[str, str, str]]] = {
            "micro": [
                ("matrix_mul", "benchmarks.micro.matrix_mul", "MatrixMultiplicationBenchmark"),
                ("memory_bandwidth", "benchmarks.micro.memory_bandwidth", "MemoryBandwidthBenchmark"),
                ("cache_latency", "benchmarks.micro.cache_latency", "CacheLatencyBenchmark"),
                ("vector_ops", "benchmarks.micro.vector_ops", "VectorOpsBenchmark"),
                ("tcp_throughput", "benchmarks.micro.tcp_throughput", "TCPThroughputBenchmark"),
                ("json_parse", "benchmarks.micro.json_parse", "JSONParseBenchmark"),
            ],
            "kernel": [
                ("syscall_latency", "benchmarks.kernel.syscall_latency", "SyscallLatencyBenchmark"),
                ("context_switch", "benchmarks.kernel.context_switch", "ContextSwitchBenchmark"),
                ("ipc_throughput", "benchmarks.kernel.ipc_throughput", "IPCThroughputBenchmark"),
                ("memory_alloc", "benchmarks.kernel.memory_alloc", "MemoryAllocBenchmark"),
            ],
            "ai": [
                ("inference_latency", "benchmarks.ai.inference_latency", "InferenceLatencyBenchmark"),
                ("inference_throughput", "benchmarks.ai.inference_throughput", "InferenceThroughputBenchmark"),
                ("embedding_speed", "benchmarks.ai.embedding_speed", "EmbeddingSpeedBenchmark"),
                ("search_latency", "benchmarks.ai.search_latency", "SearchLatencyBenchmark"),
                ("model_load", "benchmarks.ai.model_load", "ModelLoadBenchmark"),
            ],
            "sdk": [
                ("sdk_latency", "benchmarks.sdk.sdk_latency", "SDKLatencyBenchmark"),
                ("sdk_throughput", "benchmarks.sdk.sdk_throughput", "SDKThroughputBenchmark"),
                ("sdk_memory", "benchmarks.sdk.sdk_memory", "SDKMemoryBenchmark"),
            ],
        }

        categories = [category] if category else list(registry.keys())

        for cat in categories:
            if cat not in registry:
                logger.warning("Unknown benchmark category: %s", cat)
                continue

            for bench_name, module_path, class_name in registry[cat]:
                try:
                    # Import the module
                    import importlib
                    module = importlib.import_module(module_path)
                    bench_class = getattr(module, class_name)

                    # Get category-specific config
                    cat_config = self.config.get(cat, {})
                    bench_config = cat_config.get(bench_name, {})

                    # Instantiate
                    bench_instance = bench_class(bench_config)
                    benchmarks.append(bench_instance)

                    logger.debug("Discovered benchmark: %s (%s)", bench_name, class_name)

                except ImportError as exc:
                    logger.warning("Could not import benchmark %s: %s", bench_name, exc)
                except Exception as exc:
                    logger.warning("Could not instantiate benchmark %s: %s", bench_name, exc)

        logger.info("Discovered %d benchmarks", len(benchmarks))
        return benchmarks

    def run_benchmarks(
        self,
        benchmarks: list[BaseBenchmark],
        run_name: str | None = None,
        store_results: bool = True,
    ) -> list[ResultDict]:
        """Run a list of benchmarks and collect results.

        Args:
            benchmarks: List of benchmark instances to run.
            run_name: Optional name for this benchmark run.
            store_results: Whether to store results in the database.

        Returns:
            List of all result dictionaries from all benchmarks.

        Raises:
            BenchmarkExecutionError: If a benchmark fails critically.
        """
        if run_name is None:
            run_name = f"benchmark_run_{time.strftime('%Y%m%d_%H%M%S')}"

        all_results: list[ResultDict] = []
        errors: list[tuple[str, str]] = []

        # Initialize results store if needed
        store = None
        run_id = None
        if store_results:
            try:
                from benchmarks.data.results_store import ResultsStore
                store_config = self.config.get("storage", {})
                store = ResultsStore(store_config)
                run_id = store.create_run(run_name, "full_benchmark_suite", self.config)
            except Exception as exc:
                logger.warning("Could not initialize results store: %s", exc)
                store = None

        total_benchmarks = len(benchmarks)
        logger.info("Starting benchmark run: %s (%d benchmarks)", run_name, total_benchmarks)

        for i, benchmark in enumerate(benchmarks, 1):
            logger.info(
                "[%d/%d] Running benchmark: %s",
                i, total_benchmarks, benchmark.name,
            )

            try:
                start_time = time.monotonic()
                results = benchmark.run()
                elapsed = time.monotonic() - start_time

                # Add metadata to results
                for r in results:
                    r["run_name"] = run_name
                    r["timestamp"] = time.strftime('%Y-%m-%dT%H:%M:%S')

                all_results.extend(results)

                # Store results
                if store is not None and run_id is not None:
                    try:
                        store.store_results(run_id, results)
                    except Exception as exc:
                        logger.warning("Failed to store results: %s", exc)

                successful = sum(1 for r in results if "error" not in r)
                failed = len(results) - successful
                logger.info(
                    "  Completed in %.2fs: %d/%d successful",
                    elapsed, successful, len(results),
                )

            except BenchmarkTimeoutError as exc:
                logger.error("  TIMEOUT: %s", exc)
                errors.append((benchmark.name, str(exc)))
                all_results.append({
                    "benchmark": benchmark.name,
                    "error": f"Timeout: {exc}",
                    "run_name": run_name,
                })

            except BenchmarkExecutionError as exc:
                logger.error("  ERROR: %s", exc)
                errors.append((benchmark.name, str(exc)))
                all_results.append({
                    "benchmark": benchmark.name,
                    "error": str(exc),
                    "run_name": run_name,
                })

            except Exception as exc:
                logger.error("  UNEXPECTED ERROR: %s", exc)
                errors.append((benchmark.name, str(exc)))
                all_results.append({
                    "benchmark": benchmark.name,
                    "error": f"Unexpected: {exc}",
                    "run_name": run_name,
                })

        # Finalize run
        if store is not None and run_id is not None:
            status = "completed" if not errors else "partial"
            store.complete_run(run_id, status)
            store.close()

        # Summary
        total_results = len(all_results)
        total_success = sum(1 for r in all_results if "error" not in r)
        total_failed = total_results - total_success

        logger.info(
            "Benchmark run '%s' completed: %d results (%d success, %d errors)",
            run_name, total_results, total_success, total_failed,
        )

        if errors:
            logger.warning("Errors encountered:")
            for bench_name, error in errors:
                logger.warning("  - %s: %s", bench_name, error)

        self.results.extend(all_results)
        return all_results

    def run_category(
        self, category: str, run_name: str | None = None
    ) -> list[ResultDict]:
        """Run all benchmarks in a specific category.

        Args:
            category: Category name (micro, kernel, ai, sdk).
            run_name: Optional name for this benchmark run.

        Returns:
            List of result dictionaries.
        """
        logger.info("Running benchmark category: %s", category)

        # Check if enabled in config
        cat_config = self.config.get(category, {})
        if cat_config.get("enabled") is False:
            logger.info("Category '%s' is disabled in configuration", category)
            return []

        benchmarks = self.discover_benchmarks(category)
        results = self.run_benchmarks(benchmarks, run_name or f"{category}_benchmarks")

        return results

    def run_all(self, run_name: str | None = None) -> list[ResultDict]:
        """Run all available benchmarks.

        Args:
            run_name: Optional name for this benchmark run.

        Returns:
            List of all result dictionaries.
        """
        logger.info("Running ALL benchmarks")
        benchmarks = self.discover_benchmarks()
        results = self.run_benchmarks(benchmarks, run_name or "full_benchmark_suite")
        return results

    def generate_report(
        self,
        results: list[ResultDict] | None = None,
        format: str = "html",
    ) -> str:
        """Generate a report from benchmark results.

        Args:
            results: Results to include in the report. Uses accumulated
                results if None.
            format: Report format ('html' or 'json').

        Returns:
            Path to the generated report file.
        """
        if results is None:
            results = self.results

        if not results:
            logger.warning("No results to generate report from")
            return ""

        report_config = self.config.get("reports", {})
        output_dir = report_config.get(format, {}).get("output_dir", self.output_dir) or self.output_dir

        if format == "html":
            from benchmarks.reports.html_report import HTMLReportGenerator
            gen = HTMLReportGenerator(report_config)
        elif format == "json":
            from benchmarks.reports.json_report import JSONReportGenerator
            gen = JSONReportGenerator(report_config)
        else:
            logger.error("Unknown report format: %s", format)
            return ""

        return gen.generate_report(results)

    def export_results(self, results: list[ResultDict] | None = None, format: str = "json") -> str:
        """Export results to a file.

        Args:
            results: Results to export. Uses accumulated results if None.
            format: Export format ('json' or 'csv').

        Returns:
            Path to the exported file.
        """
        if results is None:
            results = self.results

        if not results:
            logger.warning("No results to export")
            return ""

        from benchmarks.reports.json_report import JSONReportGenerator
        gen = JSONReportGenerator(self.config.get("reports", {}))

        if format == "csv":
            return gen.export_csv(results)
        else:
            return gen.generate_report(results)


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the benchmark runner.

    Args:
        verbose: Whether to enable debug-level logging.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> None:
    """CLI entry point for the benchmark runner.

    Parses command-line arguments and executes the requested benchmarks.
    """
    parser = argparse.ArgumentParser(
        description="Ainos Performance Benchmark Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ainos-bench run all                  # Run all benchmarks
  ainos-bench run micro                # Run micro-benchmarks only
  ainos-bench run kernel ai            # Run kernel and AI benchmarks
  ainos-bench run micro --filter matrix  # Run matrix multiplication only
  ainos-bench report --format html     # Generate HTML report from last run
  ainos-bench list                     # List available benchmarks
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run benchmarks")
    run_parser.add_argument(
        "categories", nargs="+",
        choices=["all", "micro", "kernel", "ai", "sdk"],
        help="Benchmark categories to run",
    )
    run_parser.add_argument("--config", "-c", default="config.yaml", help="Configuration file")
    run_parser.add_argument("--filter", "-f", help="Filter benchmarks by name")
    run_parser.add_argument("--name", "-n", help="Run name")
    run_parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    run_parser.add_argument("--no-store", dest="store", action="store_false",
                          help="Don't store results in database")

    # Report command
    report_parser = subparsers.add_parser("report", help="Generate report")
    report_parser.add_argument("--format", "-f", choices=["html", "json"], default="html",
                              help="Report format")
    report_parser.add_argument("--input", "-i", help="Input results file (JSON)")
    report_parser.add_argument("--output", "-o", default="reports/output", help="Output directory")
    report_parser.add_argument("--config", "-c", default="config.yaml", help="Configuration file")

    # List command
    list_parser = subparsers.add_parser("list", help="List available benchmarks")
    list_parser.add_argument("--config", "-c", default="config.yaml", help="Configuration file")

    # Compare command
    compare_parser = subparsers.add_parser("compare", help="Compare two result sets")
    compare_parser.add_argument("baseline", help="Baseline results file (JSON)")
    compare_parser.add_argument("target", help="Target results file (JSON)")
    compare_parser.add_argument("--metric", default="mean_ms", help="Metric to compare")
    compare_parser.add_argument("--output", "-o", default="reports/output", help="Output directory")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    # Setup logging
    verbose = getattr(args, "verbose", False)
    setup_logging(verbose)

    if args.command == "list":
        runner = BenchmarkRunner(config_path=getattr(args, "config", "config.yaml"))
        benchmarks = runner.discover_benchmarks()
        print(f"\nDiscovered {len(benchmarks)} benchmarks:")
        categories = {"micro": [], "kernel": [], "ai": [], "sdk": []}
        for b in benchmarks:
            for cat, bench_list in categories.items():
                if b.name in [m[0] for m in [
                    ("matrix_mul",), ("memory_bandwidth",), ("cache_latency",),
                    ("vector_ops",), ("tcp_throughput",), ("json_parse",),
                ]]:
                    categories["micro"].append(b)
                    break
                elif b.name in [m[0] for m in [
                    ("syscall_latency",), ("context_switch",), ("ipc_throughput",), ("memory_alloc",),
                ]]:
                    categories["kernel"].append(b)
                    break
                elif b.name in [m[0] for m in [
                    ("inference_latency",), ("inference_throughput",), ("embedding_speed",),
                    ("search_latency",), ("model_load",),
                ]]:
                    categories["ai"].append(b)
                    break
                elif b.name in [m[0] for m in [
                    ("sdk_latency",), ("sdk_throughput",), ("sdk_memory",),
                ]]:
                    categories["sdk"].append(b)
                    break

        for cat, bench_list in categories.items():
            if bench_list:
                print(f"\n  {cat.upper()}:")
                for b in bench_list:
                    info = b.get_info()
                    print(f"    - {b.name}: {info.get('description', 'No description')}")
        return

    if args.command == "run":
        runner = BenchmarkRunner(config_path=args.config)
        all_results = []

        for category in args.categories:
            if category == "all":
                results = runner.run_all(args.name)
            else:
                results = runner.run_category(category, args.name)

            all_results.extend(results)

        # Generate report
        if all_results:
            report_path = runner.generate_report(all_results, format="html")
            if report_path:
                print(f"\nReport generated: {report_path}")

            json_path = runner.export_results(all_results, format="json")
            if json_path:
                print(f"Results exported: {json_path}")

        # Print summary
        total = len(all_results)
        success = sum(1 for r in all_results if "error" not in r)
        print(f"\n{'='*60}")
        print(f"Benchmark Run Complete")
        print(f"{'='*60}")
        print(f"  Total results: {total}")
        print(f"  Successful:    {success}")
        print(f"  Failed:        {total - success}")
        print(f"{'='*60}")

        return

    if args.command == "report":
        runner = BenchmarkRunner(config_path=args.config)

        if args.input:
            import json as std_json
            with open(args.input) as f:
                results = std_json.load(f)
            if isinstance(results, dict) and "results" in results:
                results = results["results"]
        else:
            results = runner.results

        if not results:
            print("No results to report. Run benchmarks first or specify --input.")
            return

        report_path = runner.generate_report(results, format=args.format)
        if report_path:
            print(f"Report generated: {report_path}")

        return

    if args.command == "compare":
        import json as std_json
        from benchmarks.data.comparison import ComparisonAnalyzer

        with open(args.baseline) as f:
            baseline = std_json.load(f)
        with open(args.target) as f:
            target = std_json.load(f)

        if isinstance(baseline, dict) and "results" in baseline:
            baseline = baseline["results"]
        if isinstance(target, dict) and "results" in target:
            target = target["results"]

        analyzer = ComparisonAnalyzer()
        comparison = analyzer.compare_results(baseline, target, metric=args.metric)

        print(f"\n{'='*60}")
        print(f"Comparison Results")
        print(f"{'='*60}")
        print(f"  Total comparisons: {comparison['summary']['total_comparisons']}")
        print(f"  Mean change:       {comparison['summary'].get('mean_pct_change', 0):.2f}%")
        print(f"  Improved:          {comparison['summary'].get('num_improved', 0)}")
        print(f"  Regressed:         {comparison['summary'].get('num_regressed', 0)}")
        print(f"{'='*60}")

        for comp in comparison["comparisons"][:10]:
            match = comp["match_criteria"]
            speedup = comp["speedup"]
            print(f"  {match}: {speedup['pct_change']:+.2f}% ({speedup['direction']})")

        return


if __name__ == "__main__":
    main()