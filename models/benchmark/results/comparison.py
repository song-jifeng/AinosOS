"""Result comparison tools for AinosOS model benchmarking.

Provides model comparison, regression detection, result formatting,
and statistical analysis utilities.
"""

from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Optional, Union

from .template import (
    BenchmarkResult,
    BenchmarkType,
    ComparisonResult,
    HardwareType,
    LatencyResult,
    MemoryResult,
    PrecisionType,
    ResultStatus,
    ResultSummary,
    ThroughputResult,
)


# ---------------------------------------------------------------------------
# ModelComparator
# ---------------------------------------------------------------------------

class ModelComparator:
    """Compare benchmark results across models, quantizations, and hardware."""

    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}

    def compare_models(
        self,
        results: list[BenchmarkResult],
        metric: str = "tokens_per_second",
        higher_is_better: bool = True,
    ) -> ComparisonResult:
        """Compare multiple models on a given metric.

        Args:
            results: List of benchmark results to compare.
            metric: Metric to compare (e.g., 'tokens_per_second', 'mean_ms').
            higher_is_better: Whether higher values are better for ranking.

        Returns:
            A ComparisonResult with rankings and speedups.
        """
        if not results:
            raise ValueError("At least one result is required for comparison.")

        model_name = results[0].metadata.model_name
        baseline = results[0]
        speedups: dict[str, float] = {}
        memory_reductions: dict[str, float] = {}
        rankings: dict[str, list[int]] = {}

        for i, result in enumerate(results):
            label = f"{result.metadata.model_name}"
            if i > 0:
                speedups[label] = self.compute_speedup(
                    baseline, result, metric, higher_is_better
                )
                memory_reductions[label] = self.compute_memory_reduction(
                    baseline, result
                )

        # Rank by various metrics
        rankings["latency"] = self.rank_by_latency(results)
        rankings["throughput"] = self.rank_by_throughput(results)
        rankings["memory_efficiency"] = self.rank_by_memory_efficiency(results)

        # Generate summary
        summary = self._build_comparison_summary(results, metric)

        return ComparisonResult(
            model_name=model_name,
            results=results,
            metric=metric,
            speedups=speedups,
            memory_reductions=memory_reductions,
            rankings=rankings,
            summary=summary,
        )

    def compare_quantizations(
        self,
        model_name: str,
        results: list[BenchmarkResult],
        metric: str = "tokens_per_second",
    ) -> ComparisonResult:
        """Compare different quantizations of the same model.

        Args:
            model_name: The base model name.
            results: Results for different quantizations of the model.
            metric: Metric to compare.

        Returns:
            A ComparisonResult with quantization comparisons.
        """
        if not results:
            raise ValueError(
                f"No results provided for model '{model_name}' quantizations."
            )

        # Filter to matching model name and sort by precision
        model_results = [
            r for r in results
            if r.metadata.model_name == model_name
        ]

        if not model_results:
            raise ValueError(
                f"No results found for model '{model_name}'."
            )

        # Use FP32 as baseline if available
        baseline_idx = 0
        for i, r in enumerate(model_results):
            if r.metadata.precision == PrecisionType.FP32:
                baseline_idx = i
                break

        baseline = model_results[baseline_idx]
        model_results.insert(0, model_results.pop(baseline_idx))

        return self.compare_models(model_results, metric)

    def compare_hardware(
        self,
        model_name: str,
        results: list[BenchmarkResult],
        metric: str = "tokens_per_second",
    ) -> ComparisonResult:
        """Compare the same model across different hardware platforms.

        Args:
            model_name: The model name to compare.
            results: Results for the same model on different hardware.
            metric: Metric to compare.

        Returns:
            A ComparisonResult with hardware comparisons.
        """
        if not results:
            raise ValueError(
                f"No results provided for model '{model_name}' on different hardware."
            )

        model_results = [
            r for r in results
            if r.metadata.model_name == model_name
        ]

        if not model_results:
            raise ValueError(
                f"No results found for model '{model_name}'."
            )

        return self.compare_models(model_results, metric)

    def generate_comparison_table(
        self,
        results: list[BenchmarkResult],
        metrics: Optional[list[str]] = None,
    ) -> str:
        """Generate a Markdown comparison table.

        Args:
            results: Results to compare.
            metrics: Specific metrics to include. If None, uses defaults.

        Returns:
            A Markdown-formatted string.
        """
        if not results:
            return "No results to compare."

        if metrics is None:
            metrics = [
                "tokens_per_second",
                "mean_ms",
                "p50_ms",
                "p95_ms",
                "peak_ram_mb",
                "peak_vram_mb",
            ]

        metric_labels = {
            "tokens_per_second": "Throughput (tokens/s)",
            "mean_ms": "Mean Latency (ms)",
            "p50_ms": "P50 Latency (ms)",
            "p95_ms": "P95 Latency (ms)",
            "p99_ms": "P99 Latency (ms)",
            "peak_ram_mb": "Peak RAM (MB)",
            "peak_vram_mb": "Peak VRAM (MB)",
            "steady_ram_mb": "Steady RAM (MB)",
            "memory_efficiency_pct": "Memory Efficiency (%)",
            "samples_per_second": "Samples/s",
            "requests_per_second": "Requests/s",
        }

        # Header
        lines = ["# Model Comparison Table\n", ""]
        header = ["Model", "Hardware", "Precision"]
        header += [metric_labels.get(m, m) for m in metrics]
        lines.append("| " + " | ".join(header) + " |")

        # Separator
        sep = ["---"] * len(header)
        lines.append("| " + " | ".join(sep) + " |")

        # Rows
        for r in results:
            row = [
                r.metadata.model_name,
                r.metadata.hardware_type.value,
                r.metadata.precision.value,
            ]
            for m in metrics:
                val = self._get_metric_value(r, m)
                if val is not None:
                    if isinstance(val, float):
                        row.append(f"{val:.2f}")
                    else:
                        row.append(str(val))
                else:
                    row.append("N/A")
            lines.append("| " + " | ".join(row) + " |")

        return "\n".join(lines)

    def compute_speedup(
        self,
        baseline: BenchmarkResult,
        optimized: BenchmarkResult,
        metric: str = "tokens_per_second",
        higher_is_better: bool = True,
    ) -> float:
        """Compute the speedup factor between two results.

        Args:
            baseline: The baseline result.
            optimized: The optimized result.
            metric: The metric to compare.
            higher_is_better: Whether higher metric values are better.

        Returns:
            Speedup factor (e.g., 1.5 means 1.5x faster).
        """
        baseline_val = self._get_metric_value(baseline, metric)
        optimized_val = self._get_metric_value(optimized, metric)

        if baseline_val is None or optimized_val is None:
            return 0.0

        if baseline_val == 0:
            return float("inf") if optimized_val > 0 else 1.0

        if higher_is_better:
            return optimized_val / baseline_val
        else:
            return baseline_val / optimized_val

    def compute_memory_reduction(
        self,
        baseline: BenchmarkResult,
        optimized: BenchmarkResult,
        metric: str = "peak_ram_mb",
    ) -> float:
        """Compute the memory reduction between two results.

        Args:
            baseline: The baseline result.
            optimized: The optimized result.
            metric: The memory metric to compare.

        Returns:
            Memory reduction factor (e.g., 0.5 means 50% less memory).
        """
        baseline_val = self._get_metric_value(baseline, metric)
        optimized_val = self._get_metric_value(optimized, metric)

        if baseline_val is None or optimized_val is None:
            return 0.0

        if baseline_val == 0:
            return 0.0

        return 1.0 - (optimized_val / baseline_val)

    def rank_by_latency(self, results: list[BenchmarkResult]) -> list[int]:
        """Rank results by latency (lower is better).

        Returns:
            List of indices into the original results list, sorted by latency.
        """
        indexed = [
            (i, r.latency.mean_ms if r.latency.mean_ms > 0 else float("inf"))
            for i, r in enumerate(results)
        ]
        indexed.sort(key=lambda x: x[1])
        return [i for i, _ in indexed]

    def rank_by_throughput(self, results: list[BenchmarkResult]) -> list[int]:
        """Rank results by throughput (higher is better).

        Returns:
            List of indices into the original results list, sorted by throughput.
        """
        indexed = [
            (i, r.throughput.tokens_per_second if r.throughput.tokens_per_second > 0 else float("-inf"))
            for i, r in enumerate(results)
        ]
        indexed.sort(key=lambda x: x[1], reverse=True)
        return [i for i, _ in indexed]

    def rank_by_memory_efficiency(self, results: list[BenchmarkResult]) -> list[int]:
        """Rank results by memory efficiency (lower memory usage is better).

        Returns:
            List of indices into the original results list, sorted by memory efficiency.
        """
        indexed = [
            (i, r.memory.peak_ram_mb if r.memory.peak_ram_mb > 0 else float("inf"))
            for i, r in enumerate(results)
        ]
        indexed.sort(key=lambda x: x[1])
        return [i for i, _ in indexed]

    def _get_metric_value(
        self,
        result: BenchmarkResult,
        metric: str,
    ) -> Optional[float]:
        """Extract a metric value from a benchmark result using dotted path."""
        parts = metric.split(".")
        obj: Any = result
        for part in parts:
            if hasattr(obj, part):
                obj = getattr(obj, part)
            elif isinstance(obj, dict):
                obj = obj.get(part)
            else:
                return None
        if isinstance(obj, (int, float)):
            return float(obj)
        return None

    def _build_comparison_summary(
        self,
        results: list[BenchmarkResult],
        metric: str,
    ) -> dict[str, Any]:
        """Build a summary dictionary from comparison results."""
        values = []
        for r in results:
            val = self._get_metric_value(r, metric)
            if val is not None:
                values.append(val)

        if not values:
            return {}

        best_idx = values.index(max(values)) if values else 0
        worst_idx = values.index(min(values)) if values else 0

        return {
            "metric": metric,
            "num_results": len(results),
            "best_result": results[best_idx].metadata.model_name,
            "best_value": values[best_idx] if values else 0,
            "worst_result": results[worst_idx].metadata.model_name,
            "worst_value": values[worst_idx] if values else 0,
            "mean": statistics.mean(values) if values else 0,
            "median": statistics.median(values) if values else 0,
            "std_dev": statistics.stdev(values) if len(values) > 1 else 0,
            "min": min(values) if values else 0,
            "max": max(values) if values else 0,
        }


# ---------------------------------------------------------------------------
# RegressionDetector
# ---------------------------------------------------------------------------

class RegressionDetector:
    """Detect performance regressions in benchmark results."""

    def __init__(
        self,
        regression_threshold: float = 0.05,
        warning_threshold: float = 0.10,
    ) -> None:
        """Initialize the regression detector.

        Args:
            regression_threshold: Minimum relative change to flag as regression (5%).
            warning_threshold: Relative change threshold for warnings (10%).
        """
        self.regression_threshold = regression_threshold
        self.warning_threshold = warning_threshold
        self.report: list[dict[str, Any]] = []

    def detect_regression(
        self,
        new_result: BenchmarkResult,
        previous_results: list[BenchmarkResult],
        metrics: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Detect regressions between a new result and historical results.

        Args:
            new_result: The latest benchmark result.
            previous_results: List of historical results.
            metrics: Metrics to check for regressions.

        Returns:
            List of regression findings, each with metric, baseline, new value,
            change percentage, and severity.
        """
        if metrics is None:
            metrics = [
                "latency.mean_ms",
                "latency.p50_ms",
                "latency.p95_ms",
                "latency.p99_ms",
                "throughput.tokens_per_second",
                "memory.peak_ram_mb",
                "memory.peak_vram_mb",
                "memory.steady_ram_mb",
            ]

        if not previous_results:
            return []

        findings: list[dict[str, Any]] = []

        for metric in metrics:
            baseline_values = [
                self._get_metric_value(r, metric)
                for r in previous_results
                if self._get_metric_value(r, metric) is not None
            ]

            if not baseline_values:
                continue

            new_value = self._get_metric_value(new_result, metric)
            if new_value is None:
                continue

            baseline_mean = statistics.mean(baseline_values)
            baseline_std = statistics.stdev(baseline_values) if len(baseline_values) > 1 else 0

            if baseline_mean == 0:
                continue

            change_pct = (new_value - baseline_mean) / baseline_mean

            # Determine if this is a regression
            is_latency_metric = "latency" in metric or "p50" in metric or "p95" in metric or "p99" in metric
            is_memory_metric = "memory" in metric or "ram" in metric or "vram" in metric
            is_throughput_metric = "throughput" in metric or "tokens_per_second" in metric

            # For latency and memory, increase is regression; for throughput, decrease is regression
            is_regression = False
            if is_throughput_metric:
                is_regression = change_pct < -self.regression_threshold
            else:
                is_regression = change_pct > self.regression_threshold

            # Determine severity
            abs_change = abs(change_pct)
            if abs_change >= self.warning_threshold:
                severity = "critical" if is_regression else "major_improvement"
            elif abs_change >= self.regression_threshold:
                severity = "regression" if is_regression else "improvement"
            else:
                severity = "stable"

            # Statistical significance
            significance = None
            if len(baseline_values) > 1 and baseline_std > 0:
                z_score = abs(new_value - baseline_mean) / baseline_std
                if z_score > 3:
                    significance = "high"
                elif z_score > 2:
                    significance = "medium"
                elif z_score > 1:
                    significance = "low"
                else:
                    significance = "none"

            finding = {
                "metric": metric,
                "baseline_mean": baseline_mean,
                "baseline_std": baseline_std,
                "baseline_count": len(baseline_values),
                "new_value": new_value,
                "change_pct": change_pct,
                "is_regression": is_regression,
                "severity": severity,
                "significance": significance,
                "z_score": (new_value - baseline_mean) / baseline_std if baseline_std > 0 else None,
            }
            findings.append(finding)

        self.report = findings
        return findings

    def compute_statistical_significance(
        self,
        baseline: list[float],
        target: list[float],
    ) -> dict[str, float]:
        """Compute statistical significance between two sets of measurements.

        Uses Welch's t-test for independent samples.

        Args:
            baseline: Baseline measurements.
            target: Target measurements.

        Returns:
            Dictionary with t-statistic, p-value, effect size (Cohen's d),
            and degrees of freedom.
        """
        if len(baseline) < 2 or len(target) < 2:
            return {"t_statistic": 0.0, "p_value": 1.0, "effect_size": 0.0, "df": 0.0}

        n1 = len(baseline)
        n2 = len(target)
        mean1 = statistics.mean(baseline)
        mean2 = statistics.mean(target)
        var1 = statistics.variance(baseline)
        var2 = statistics.variance(target)

        # Welch's t-test
        se = math.sqrt((var1 / n1) + (var2 / n2))
        if se == 0:
            return {"t_statistic": 0.0, "p_value": 1.0, "effect_size": 0.0, "df": 0.0}

        t_stat = (mean1 - mean2) / se

        # Welch-Satterthwaite degrees of freedom
        num = (var1 / n1 + var2 / n2) ** 2
        denom = ((var1 / n1) ** 2 / (n1 - 1)) + ((var2 / n2) ** 2 / (n2 - 1))
        df = num / denom if denom > 0 else 0

        # Approximate p-value using normal distribution (for large df)
        # For a more accurate p-value, use scipy.stats
        p_value = 2.0 * (1.0 - self._normal_cdf(abs(t_stat)))

        # Cohen's d effect size
        pooled_std = math.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
        effect_size = abs(mean1 - mean2) / pooled_std if pooled_std > 0 else 0

        return {
            "t_statistic": t_stat,
            "p_value": p_value,
            "effect_size": effect_size,
            "df": df,
        }

    def generate_regression_report(self, format: str = "text") -> str:
        """Generate a detailed regression report.

        Args:
            format: Output format ('text', 'json', 'markdown').

        Returns:
            Formatted regression report string.
        """
        if not self.report:
            return "No regression analysis performed yet."

        if format == "json":
            return json.dumps(self.report, indent=2, ensure_ascii=False)

        if format == "markdown":
            lines = ["# Regression Analysis Report\n", ""]
            lines.append("| Metric | Baseline | New Value | Change | Severity | Significance |")
            lines.append("|--------|----------|-----------|--------|----------|-------------|")
            for f in self.report:
                lines.append(
                    f"| {f['metric']} | {f['baseline_mean']:.4f} | {f['new_value']:.4f} "
                    f"| {f['change_pct'] * 100:+.2f}% | {f['severity']} | {f['significance'] or 'N/A'} |"
                )
            return "\n".join(lines)

        # Text format
        lines = ["=" * 60, "REGRESSION ANALYSIS REPORT", "=" * 60, ""]
        regressions = [f for f in self.report if f["is_regression"]]
        improvements = [f for f in self.report if not f["is_regression"] and abs(f["change_pct"]) > self.regression_threshold]
        stable = [f for f in self.report if abs(f["change_pct"]) <= self.regression_threshold]

        if regressions:
            lines.append(f"REGRESSIONS FOUND: {len(regressions)}")
            lines.append("-" * 40)
            for f in regressions:
                lines.append(f"  Metric:     {f['metric']}")
                lines.append(f"  Baseline:   {f['baseline_mean']:.4f} (n={f['baseline_count']})")
                lines.append(f"  New Value:  {f['new_value']:.4f}")
                lines.append(f"  Change:     {f['change_pct'] * 100:+.2f}%")
                lines.append(f"  Severity:   {f['severity']}")
                lines.append(f"  Z-Score:    {f['z_score']:.2f}" if f['z_score'] else "")
                lines.append("")

        if improvements:
            lines.append(f"IMPROVEMENTS: {len(improvements)}")
            lines.append("-" * 40)
            for f in improvements:
                lines.append(f"  Metric:     {f['metric']}")
                lines.append(f"  Baseline:   {f['baseline_mean']:.4f} (n={f['baseline_count']})")
                lines.append(f"  New Value:  {f['new_value']:.4f}")
                lines.append(f"  Change:     {f['change_pct'] * 100:+.2f}%")
                lines.append("")

        if stable:
            lines.append(f"STABLE METRICS: {len(stable)}")
            for f in stable:
                lines.append(f"  - {f['metric']}: {f['change_pct'] * 100:+.2f}%")

        return "\n".join(lines)

    def _get_metric_value(self, result: BenchmarkResult, metric: str) -> Optional[float]:
        parts = metric.split(".")
        obj: Any = result
        for part in parts:
            if hasattr(obj, part):
                obj = getattr(obj, part)
            elif isinstance(obj, dict):
                obj = obj.get(part)
            else:
                return None
        if isinstance(obj, (int, float)):
            return float(obj)
        return None

    @staticmethod
    def _normal_cdf(x: float) -> float:
        """Approximate the standard normal CDF."""
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ---------------------------------------------------------------------------
# ResultFormatter
# ---------------------------------------------------------------------------

class ResultFormatter:
    """Format benchmark results into various output formats."""

    def __init__(self, decimal_places: int = 4) -> None:
        self.decimal_places = decimal_places

    def format_as_text(self, result: BenchmarkResult) -> str:
        """Format a single benchmark result as plain text."""
        lines = ["=" * 60]
        lines.append(f"BENCHMARK RESULT: {result.result_id}")
        lines.append("=" * 60)
        lines.append("")
        lines.append("METADATA")
        lines.append("-" * 40)
        lines.append(f"  Model:          {result.metadata.model_name}")
        lines.append(f"  Version:        {result.metadata.model_version}")
        lines.append(f"  Family:         {result.metadata.model_family}")
        lines.append(f"  Benchmark:      {result.metadata.benchmark_type.value}")
        lines.append(f"  Hardware:       {result.metadata.hardware_type.value}")
        lines.append(f"  Precision:      {result.metadata.precision.value}")
        lines.append(f"  Batch Size:     {result.metadata.batch_size}")
        lines.append(f"  Context Length: {result.metadata.context_length}")
        lines.append(f"  Date:           {result.metadata.date}")
        lines.append(f"  Status:         {result.status.value}")
        lines.append("")

        if result.latency.mean_ms > 0:
            lines.append("LATENCY")
            lines.append("-" * 40)
            lines.append(f"  Mean:     {result.latency.mean_ms:.{self.decimal_places}f} ms")
            lines.append(f"  P50:      {result.latency.p50_ms:.{self.decimal_places}f} ms")
            lines.append(f"  P95:      {result.latency.p95_ms:.{self.decimal_places}f} ms")
            lines.append(f"  P99:      {result.latency.p99_ms:.{self.decimal_places}f} ms")
            lines.append(f"  Min:      {result.latency.min_ms:.{self.decimal_places}f} ms")
            lines.append(f"  Max:      {result.latency.max_ms:.{self.decimal_places}f} ms")
            lines.append(f"  Std Dev:  {result.latency.std_dev_ms:.{self.decimal_places}f} ms")
            lines.append(f"  TTFT:     {result.latency.time_to_first_token_ms:.{self.decimal_places}f} ms")
            lines.append("")

        if result.throughput.tokens_per_second > 0:
            lines.append("THROUGHPUT")
            lines.append("-" * 40)
            lines.append(f"  Tokens/s:        {result.throughput.tokens_per_second:.{self.decimal_places}f}")
            lines.append(f"  Requests/s:      {result.throughput.requests_per_second:.{self.decimal_places}f}")
            lines.append(f"  Total Tokens:    {result.throughput.total_tokens}")
            lines.append(f"  Total Time:      {result.throughput.total_time_seconds:.2f} s")
            lines.append("")

        if result.memory.peak_ram_mb > 0:
            lines.append("MEMORY")
            lines.append("-" * 40)
            lines.append(f"  Peak RAM:     {result.memory.peak_ram_mb:.{self.decimal_places}f} MB")
            lines.append(f"  Steady RAM:   {result.memory.steady_ram_mb:.{self.decimal_places}f} MB")
            lines.append(f"  Peak VRAM:    {result.memory.peak_vram_mb:.{self.decimal_places}f} MB")
            lines.append(f"  Efficiency:   {result.memory.memory_efficiency_pct:.{self.decimal_places}f}%")
            lines.append("")

        if result.score > 0:
            lines.append("OVERALL SCORE")
            lines.append("-" * 40)
            lines.append(f"  Score: {result.score:.{self.decimal_places}f}")
            if result.score_breakdown:
                lines.append("  Breakdown:")
                for k, v in result.score_breakdown.items():
                    lines.append(f"    {k}: {v:.{self.decimal_places}f}")
            lines.append("")

        if result.errors:
            lines.append("ERRORS")
            lines.append("-" * 40)
            for e in result.errors:
                lines.append(f"  - {e}")

        if result.warnings:
            lines.append("WARNINGS")
            lines.append("-" * 40)
            for w in result.warnings:
                lines.append(f"  - {w}")

        lines.append("=" * 60)
        return "\n".join(lines)

    def format_as_json(self, result: BenchmarkResult, indent: int = 2) -> str:
        """Format a benchmark result as a JSON string."""
        return json.dumps(result.to_dict(), indent=indent, ensure_ascii=False)

    def format_as_csv(self, results: list[BenchmarkResult]) -> str:
        """Format multiple benchmark results as CSV."""
        import csv
        import io

        output = io.StringIO()
        fieldnames = [
            "result_id",
            "model_name",
            "model_version",
            "benchmark_type",
            "hardware_type",
            "precision",
            "batch_size",
            "context_length",
            "date",
            "status",
            "latency_mean_ms",
            "latency_p50_ms",
            "latency_p95_ms",
            "latency_p99_ms",
            "latency_min_ms",
            "latency_max_ms",
            "latency_std_dev_ms",
            "latency_ttft_ms",
            "throughput_tokens_per_second",
            "throughput_requests_per_second",
            "throughput_total_tokens",
            "throughput_total_time_s",
            "memory_peak_ram_mb",
            "memory_steady_ram_mb",
            "memory_peak_vram_mb",
            "memory_efficiency_pct",
            "score",
        ]

        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        for r in results:
            d = r.to_dict()
            flat = {
                "result_id": r.result_id,
                "model_name": r.metadata.model_name,
                "model_version": r.metadata.model_version,
                "benchmark_type": r.metadata.benchmark_type.value,
                "hardware_type": r.metadata.hardware_type.value,
                "precision": r.metadata.precision.value,
                "batch_size": r.metadata.batch_size,
                "context_length": r.metadata.context_length,
                "date": r.metadata.date,
                "status": r.status.value,
                "latency_mean_ms": r.latency.mean_ms,
                "latency_p50_ms": r.latency.p50_ms,
                "latency_p95_ms": r.latency.p95_ms,
                "latency_p99_ms": r.latency.p99_ms,
                "latency_min_ms": r.latency.min_ms,
                "latency_max_ms": r.latency.max_ms,
                "latency_std_dev_ms": r.latency.std_dev_ms,
                "latency_ttft_ms": r.latency.time_to_first_token_ms,
                "throughput_tokens_per_second": r.throughput.tokens_per_second,
                "throughput_requests_per_second": r.throughput.requests_per_second,
                "throughput_total_tokens": r.throughput.total_tokens,
                "throughput_total_time_s": r.throughput.total_time_seconds,
                "memory_peak_ram_mb": r.memory.peak_ram_mb,
                "memory_steady_ram_mb": r.memory.steady_ram_mb,
                "memory_peak_vram_mb": r.memory.peak_vram_mb,
                "memory_efficiency_pct": r.memory.memory_efficiency_pct,
                "score": r.score,
            }
            writer.writerow(flat)

        return output.getvalue()

    def format_as_markdown(self, results: list[BenchmarkResult]) -> str:
        """Format results as a Markdown table."""
        if not results:
            return "No results to display."

        lines = ["| ID | Model | Hardware | Precision | Latency (ms) | Throughput (t/s) | Peak RAM (MB) | Score |"]
        lines.append("|----|-------|----------|-----------|-------------|-----------------|---------------|-------|")

        for r in results:
            latency = f"{r.latency.mean_ms:.2f}" if r.latency.mean_ms > 0 else "N/A"
            throughput = f"{r.throughput.tokens_per_second:.2f}" if r.throughput.tokens_per_second > 0 else "N/A"
            mem = f"{r.memory.peak_ram_mb:.1f}" if r.memory.peak_ram_mb > 0 else "N/A"
            score = f"{r.score:.2f}" if r.score > 0 else "N/A"

            # Truncate result_id for display
            short_id = r.result_id[:16] + "..." if len(r.result_id) > 20 else r.result_id

            lines.append(
                f"| {short_id} | {r.metadata.model_name} | "
                f"{r.metadata.hardware_type.value} | {r.metadata.precision.value} | "
                f"{latency} | {throughput} | {mem} | {score} |"
            )

        return "\n".join(lines)

    def format_as_html(self, results: list[BenchmarkResult]) -> str:
        """Format results as an HTML table."""
        if not results:
            return "<p>No results to display.</p>"

        rows_html = ""
        for r in results:
            latency = f"{r.latency.mean_ms:.2f}" if r.latency.mean_ms > 0 else "<em>N/A</em>"
            throughput = f"{r.throughput.tokens_per_second:.2f}" if r.throughput.tokens_per_second > 0 else "<em>N/A</em>"
            mem = f"{r.memory.peak_ram_mb:.1f}" if r.memory.peak_ram_mb > 0 else "<em>N/A</em>"
            score = f"{r.score:.2f}" if r.score > 0 else "<em>N/A</em>"

            rows_html += (
                f"<tr>"
                f"<td>{r.metadata.model_name}</td>"
                f"<td>{r.metadata.hardware_type.value}</td>"
                f"<td>{r.metadata.precision.value}</td>"
                f"<td>{latency}</td>"
                f"<td>{throughput}</td>"
                f"<td>{mem}</td>"
                f"<td>{score}</td>"
                f"</tr>\n"
            )

        return (
            "<table>\n"
            "<thead>\n"
            "<tr><th>Model</th><th>Hardware</th><th>Precision</th>"
            "<th>Latency (ms)</th><th>Throughput (t/s)</th>"
            "<th>Peak RAM (MB)</th><th>Score</th></tr>\n"
            "</thead>\n"
            "<tbody>\n"
            f"{rows_html}"
            "</tbody>\n"
            "</table>"
        )

    def format_as_latex(self, results: list[BenchmarkResult]) -> str:
        """Format results as a LaTeX table."""
        if not results:
            return "% No results to display."

        lines = [
            "\\begin{table}[htbp]",
            "\\centering",
            "\\begin{tabular}{|l|l|l|r|r|r|r|}",
            "\\hline",
            "Model & Hardware & Precision & Latency (ms) & Throughput (t/s) & Peak RAM (MB) & Score \\\\",
            "\\hline",
        ]

        for r in results:
            latency = f"{r.latency.mean_ms:.2f}" if r.latency.mean_ms > 0 else "N/A"
            throughput = f"{r.throughput.tokens_per_second:.2f}" if r.throughput.tokens_per_second > 0 else "N/A"
            mem = f"{r.memory.peak_ram_mb:.1f}" if r.memory.peak_ram_mb > 0 else "N/A"
            score = f"{r.score:.2f}" if r.score > 0 else "N/A"

            lines.append(
                f"{r.metadata.model_name} & {r.metadata.hardware_type.value} & "
                f"{r.metadata.precision.value} & {latency} & {throughput} & {mem} & {score} \\\\"
            )
            lines.append("\\hline")

        lines.extend([
            "\\end{tabular}",
            "\\caption{Benchmark Results}",
            "\\label{tab:benchmark_results}",
            "\\end{table}",
        ])

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Statistical Utility Functions
# ---------------------------------------------------------------------------

def calculate_percentiles(
    data: list[float],
    percentiles: Optional[list[float]] = None,
) -> dict[float, float]:
    """Calculate percentile values from a list of data.

    Args:
        data: List of numeric values.
        percentiles: List of percentile values to compute (0-100).

    Returns:
        Dictionary mapping percentile to value.
    """
    if percentiles is None:
        percentiles = [50, 90, 95, 99, 99.9]

    if not data:
        return {p: 0.0 for p in percentiles}

    sorted_data = sorted(data)
    n = len(sorted_data)
    result: dict[float, float] = {}

    for p in percentiles:
        if p <= 0:
            result[p] = sorted_data[0]
        elif p >= 100:
            result[p] = sorted_data[-1]
        else:
            idx = (p / 100.0) * (n - 1)
            lo = int(math.floor(idx))
            hi = int(math.ceil(idx))
            if lo == hi:
                result[p] = sorted_data[lo]
            else:
                frac = idx - lo
                result[p] = sorted_data[lo] * (1 - frac) + sorted_data[hi] * frac

    return result


def calculate_confidence_interval(
    data: list[float],
    confidence: float = 0.95,
) -> tuple[float, float, float]:
    """Calculate confidence interval for a sample.

    Args:
        data: List of numeric values.
        confidence: Confidence level (default 0.95 for 95%).

    Returns:
        Tuple of (mean, lower_bound, upper_bound).
    """
    if not data:
        return (0.0, 0.0, 0.0)

    n = len(data)
    mean = statistics.mean(data)

    if n < 2:
        return (mean, mean, mean)

    std_err = statistics.stdev(data) / math.sqrt(n)
    # Z-score for normal approximation
    z_scores = {0.90: 1.645, 0.95: 1.960, 0.99: 2.576}
    z = z_scores.get(confidence, 1.960)

    margin = z * std_err
    return (mean, mean - margin, mean + margin)


def detect_outliers(
    data: list[float],
    method: str = "iqr",
    threshold: float = 1.5,
) -> list[tuple[int, float, str]]:
    """Detect outliers in data.

    Args:
        data: List of numeric values.
        method: Detection method ('iqr' or 'zscore').
        threshold: IQR multiplier (for 'iqr') or Z-score threshold (for 'zscore').

    Returns:
        List of (index, value, reason) tuples for outliers.
    """
    if not data:
        return []

    outliers: list[tuple[int, float, str]] = []

    if method == "iqr":
        sorted_data = sorted(data)
        n = len(sorted_data)
        q1 = sorted_data[int(n * 0.25)]
        q3 = sorted_data[int(n * 0.75)]
        iqr = q3 - q1
        lower = q1 - threshold * iqr
        upper = q3 + threshold * iqr

        for i, val in enumerate(data):
            if val < lower:
                outliers.append((i, val, f"below lower fence ({lower:.4f})"))
            elif val > upper:
                outliers.append((i, val, f"above upper fence ({upper:.4f})"))

    elif method == "zscore":
        mean = statistics.mean(data)
        std = statistics.stdev(data) if len(data) > 1 else 0

        if std == 0:
            return []

        for i, val in enumerate(data):
            z = abs(val - mean) / std
            if z > threshold:
                outliers.append((i, val, f"Z-score = {z:.4f}"))

    return outliers


def normalize_scores(
    results: list[BenchmarkResult],
    metric: str = "tokens_per_second",
    higher_is_better: bool = True,
) -> dict[str, float]:
    """Normalize scores to 0-100 range.

    Args:
        results: List of benchmark results.
        metric: Metric to normalize.
        higher_is_better: Whether higher values are better.

    Returns:
        Dictionary mapping result_id to normalized score (0-100).
    """
    if not results:
        return {}

    values: list[tuple[str, float]] = []
    for r in results:
        parts = metric.split(".")
        obj: Any = r
        for part in parts:
            if hasattr(obj, part):
                obj = getattr(obj, part)
            else:
                obj = None
                break
        if isinstance(obj, (int, float)):
            values.append((r.result_id, float(obj)))

    if not values:
        return {}

    metric_values = [v for _, v in values]
    min_val = min(metric_values)
    max_val = max(metric_values)

    if max_val == min_val:
        return {rid: 100.0 for rid, _ in values}

    normalized: dict[str, float] = {}
    for rid, val in values:
        if higher_is_better:
            normalized[rid] = ((val - min_val) / (max_val - min_val)) * 100.0
        else:
            normalized[rid] = ((max_val - val) / (max_val - min_val)) * 100.0

    return normalized