"""
Report Generator
=================

Base report generator for the benchmark suite. Provides common functionality
for generating reports from benchmark results, including data aggregation,
statistical analysis, and output formatting.

This module supports:
- HTML report generation with charts
- JSON report generation for programmatic access
- Chart generation for visual analysis
- Custom report templates
- Multi-benchmark comparison reports
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import numpy as np
from numpy.typing import NDArray

from benchmarks import ResultDict

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Base class for benchmark report generation.

    Provides common statistics computation and data aggregation methods
    shared by all report formats.

    Attributes:
        name: Name of this report generator.
        output_dir: Directory for output files.
        include_metadata: Whether to include benchmark metadata.
        include_raw_data: Whether to include raw timing data.
        config: Configuration dictionary.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the report generator.

        Args:
            config: Configuration dictionary. Expected keys: output_dir,
                include_metadata, include_raw_data.
        """
        self.name: str = "report_generator"
        self.config: dict[str, Any] = config or {}
        self.output_dir: str = self.config.get("output_dir", "reports/output")
        self.include_metadata: bool = self.config.get("include_metadata", True)
        self.include_raw_data: bool = self.config.get("include_raw_data", False)

        # Ensure output directory exists
        os.makedirs(self.output_dir, exist_ok=True)

        logger.info("Initialized ReportGenerator: output_dir=%s", self.output_dir)

    @staticmethod
    def compute_statistics(
        data: list[float] | NDArray[np.float64]
    ) -> dict[str, float]:
        """Compute comprehensive statistics from a list of values.

        Args:
            data: List or array of numeric values.

        Returns:
            Dictionary with statistical metrics.
        """
        arr: NDArray[np.float64] = np.array(data, dtype=np.float64)
        n: int = len(arr)

        if n == 0:
            return {}

        mean: float = float(np.mean(arr))
        median: float = float(np.median(arr))
        std: float = float(np.std(arr, ddof=1))
        variance: float = float(np.var(arr, ddof=1))
        minimum: float = float(np.min(arr))
        maximum: float = float(np.max(arr))
        data_range: float = maximum - minimum

        # Percentiles
        p50: float = float(np.percentile(arr, 50))
        p75: float = float(np.percentile(arr, 75))
        p90: float = float(np.percentile(arr, 90))
        p95: float = float(np.percentile(arr, 95))
        p99: float = float(np.percentile(arr, 99))
        p999: float = float(np.percentile(arr, 99.9))

        # Coefficient of variation
        cv: float = std / mean if mean > 0 else 0.0

        # Skewness and kurtosis
        skewness: float = float(np.mean((arr - mean) ** 3) / (std ** 3)) if std > 0 else 0.0
        kurtosis: float = float(np.mean((arr - mean) ** 4) / (std ** 4) - 3) if std > 0 else 0.0

        # Confidence interval (95%)
        z_score: float = 1.96
        ci_lower: float = mean - z_score * (std / np.sqrt(n))
        ci_upper: float = mean + z_score * (std / np.sqrt(n))

        # Outlier detection (Z-score method)
        z_scores: NDArray[np.float64] = np.abs((arr - mean) / std) if std > 0 else np.zeros_like(arr)
        num_outliers: int = int(np.sum(z_scores > 3.0))

        return {
            "count": n,
            "mean": mean,
            "median": median,
            "std": std,
            "variance": variance,
            "min": minimum,
            "max": maximum,
            "range": data_range,
            "p50": p50,
            "p75": p75,
            "p90": p90,
            "p95": p95,
            "p99": p99,
            "p999": p999,
            "cv": cv,
            "skewness": skewness,
            "kurtosis": kurtosis,
            "ci_lower": ci_lower,
            "ci_upper": ci_upper,
            "num_outliers": num_outliers,
            "sum": float(np.sum(arr)),
        }

    @staticmethod
    def aggregate_results(
        results: list[ResultDict], group_by: str = "benchmark"
    ) -> dict[str, list[ResultDict]]:
        """Aggregate benchmark results by a key.

        Args:
            results: List of benchmark result dictionaries.
            group_by: Key to group results by.

        Returns:
            Dictionary mapping group keys to lists of results.
        """
        aggregated: dict[str, list[ResultDict]] = {}
        for result in results:
            key = str(result.get(group_by, "unknown"))
            if key not in aggregated:
                aggregated[key] = []
            aggregated[key].append(result)
        return aggregated

    @staticmethod
    def filter_results(
        results: list[ResultDict], filters: dict[str, Any]
    ) -> list[ResultDict]:
        """Filter benchmark results by key-value pairs.

        Args:
            results: List of benchmark result dictionaries.
            filters: Dictionary of key-value pairs to filter by.

        Returns:
            Filtered list of results.
        """
        filtered = results
        for key, value in filters.items():
            filtered = [r for r in filtered if r.get(key) == value]
        return filtered

    @staticmethod
    def compare_results(
        results_a: list[ResultDict],
        results_b: list[ResultDict],
        metric: str = "mean_ms",
    ) -> dict[str, Any]:
        """Compare two sets of benchmark results.

        Args:
            results_a: First set of benchmark results.
            results_b: Second set of benchmark results.
            metric: Metric to compare.

        Returns:
            Dictionary with comparison results including percentage changes.
        """
        comparisons: dict[str, Any] = {
            "metric": metric,
            "comparisons": [],
            "summary": {},
        }

        # Match results by common keys
        for ra in results_a:
            # Find matching result in results_b
            match_keys = {k: ra[k] for k in ["benchmark", "size", "batch_size", "model"]
                         if k in ra}

            for rb in results_b:
                if all(rb.get(k) == v for k, v in match_keys.items()):
                    val_a = ra.get(metric, 0)
                    val_b = rb.get(metric, 0)
                    if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)) and val_a > 0:
                        pct_change = ((val_b - val_a) / val_a) * 100
                        comparisons["comparisons"].append({
                            "match_keys": match_keys,
                            "value_a": val_a,
                            "value_b": val_b,
                            "pct_change": pct_change,
                            "direction": "improved" if pct_change < 0 else "regressed",
                        })
                    break

        if comparisons["comparisons"]:
            pct_changes = [c["pct_change"] for c in comparisons["comparisons"]]
            comparisons["summary"] = {
                "mean_pct_change": float(np.mean(pct_changes)),
                "median_pct_change": float(np.median(pct_changes)),
                "min_pct_change": float(np.min(pct_changes)),
                "max_pct_change": float(np.max(pct_changes)),
                "num_comparisons": len(comparisons["comparisons"]),
                "num_improved": sum(1 for c in comparisons["comparisons"] if c["direction"] == "improved"),
                "num_regressed": sum(1 for c in comparisons["comparisons"] if c["direction"] == "regressed"),
            }

        return comparisons

    def generate_report(
        self, results: list[ResultDict], report_name: str = "benchmark_report"
    ) -> str:
        """Generate a report from benchmark results.

        This is the main entry point for report generation. Subclasses
        should override this method.

        Args:
            results: List of benchmark result dictionaries.
            report_name: Base name for the report file.

        Returns:
            Path to the generated report file.
        """
        raise NotImplementedError("Subclasses must implement generate_report()")

    @staticmethod
    def get_system_info() -> dict[str, Any]:
        """Gather system information for report metadata.

        Returns:
            Dictionary with system information.
        """
        info: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "platform": {},
        }

        try:
            import platform
            info["platform"] = {
                "system": platform.system(),
                "node": platform.node(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "python_version": platform.python_version(),
            }
        except Exception:
            pass

        try:
            import psutil
            info["cpu"] = {
                "count": psutil.cpu_count(),
                "physical_count": psutil.cpu_count(logical=False),
                "frequency": psutil.cpu_freq()._asdict() if psutil.cpu_freq() else {},
            }
            info["memory"] = {
                "total": psutil.virtual_memory().total,
                "available": psutil.virtual_memory().available,
            }
            info["disk"] = {
                "total": psutil.disk_usage("/").total,
                "free": psutil.disk_usage("/").free,
            }
        except Exception:
            pass

        return info


def main() -> None:
    """CLI entry point for report generation."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate benchmark reports")
    parser.add_argument("--input", "-i", required=True, help="Input JSON results file")
    parser.add_argument("--format", "-f", choices=["html", "json"], default="html",
                        help="Output format")
    parser.add_argument("--output", "-o", default="reports/output", help="Output directory")
    args = parser.parse_args()

    import json as std_json
    with open(args.input) as f:
        results = std_json.load(f)

    config = {"output_dir": args.output}

    if args.format == "html":
        from benchmarks.reports.html_report import HTMLReportGenerator
        generator = HTMLReportGenerator(config)
    else:
        from benchmarks.reports.json_report import JSONReportGenerator
        generator = JSONReportGenerator(config)

    report_path = generator.generate_report(results)
    print(f"Report generated: {report_path}")


if __name__ == "__main__":
    main()