"""
JSON Report Generator
======================

Generates JSON-formatted benchmark reports for programmatic consumption
and integration with external tools and dashboards.

This module supports:
- Structured JSON output with metadata
- Raw data inclusion option
- Pretty-printed output
- Schema-compliant result format
- Multi-run comparison support
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

from benchmarks import ResultDict
from benchmarks.reports.report_generator import ReportGenerator

logger = logging.getLogger(__name__)


class JSONReportGenerator(ReportGenerator):
    """JSON report generator for benchmark results.

    Creates structured JSON reports suitable for programmatic parsing
    and integration with external tools.

    Attributes:
        name: Name of this report generator.
        pretty_print: Whether to format JSON with indentation.
        output_file: Name of the output JSON file.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the JSON report generator.

        Args:
            config: Configuration dictionary. Expected keys: pretty_print,
                output_file.
        """
        super().__init__(config)
        self.name = "json_report"
        self.pretty_print: bool = self.config.get("pretty_print", True)
        self.output_file: str = self.config.get("output_file", "benchmark_data.json")

    def _serialize_result(self, result: ResultDict) -> dict[str, Any]:
        """Serialize a single result to JSON-compatible format.

        Handles special types like numpy arrays and lists.

        Args:
            result: Result dictionary to serialize.

        Returns:
            JSON-serializable dictionary.
        """
        serialized: dict[str, Any] = {}
        for key, value in result.items():
            if isinstance(value, np.ndarray):
                serialized[key] = value.tolist() if self.include_raw_data else []
            elif isinstance(value, (np.integer,)):
                serialized[key] = int(value)
            elif isinstance(value, (np.floating,)):
                serialized[key] = float(value)
            elif isinstance(value, (list,)):
                if self.include_raw_data:
                    serialized[key] = [float(v) if isinstance(v, (np.floating,)) else v for v in value]
                else:
                    serialized[key] = []
            elif isinstance(value, dict):
                serialized[key] = self._serialize_result(value)
            else:
                serialized[key] = value
        return serialized

    def _build_report_structure(
        self, results: list[ResultDict]
    ) -> dict[str, Any]:
        """Build the complete report JSON structure.

        Args:
            results: List of benchmark result dictionaries.

        Returns:
            Complete report dictionary with metadata.
        """
        # Serialize all results
        serialized_results = [self._serialize_result(r) for r in results]

        # Compute summary statistics
        total = len(results)
        successful = sum(1 for r in results if "error" not in r)

        # Group by benchmark type
        benchmark_types: dict[str, int] = {}
        for r in results:
            btype = str(r.get("benchmark", "unknown"))
            benchmark_types[btype] = benchmark_types.get(btype, 0) + 1

        # Build report
        report: dict[str, Any] = {
            "report_metadata": {
                "generator": "Ainos Performance Benchmark Suite",
                "version": "1.0.0",
                "generated_at": datetime.now().isoformat(),
                "total_results": total,
                "successful_results": successful,
                "failed_results": total - successful,
                "benchmark_types": benchmark_types,
            },
            "results": serialized_results,
        }

        # Add system info if requested
        if self.include_metadata:
            report["system_info"] = self.get_system_info()

        return report

    def generate_report(
        self, results: list[ResultDict], report_name: str = "benchmark_report"
    ) -> str:
        """Generate a JSON report from benchmark results.

        Args:
            results: List of benchmark result dictionaries.
            report_name: Base name for the report file.

        Returns:
            Path to the generated JSON file.
        """
        logger.info("Generating JSON report with %d results", len(results))

        report = self._build_report_structure(results)

        # Serialize to JSON
        json_kwargs: dict[str, Any] = {"cls": _BenchmarkEncoder}
        if self.pretty_print:
            json_kwargs["indent"] = 2
            json_kwargs["sort_keys"] = True

        json_str = json.dumps(report, **json_kwargs)

        # Write to file
        report_path = os.path.join(self.output_dir, self.output_file)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(json_str)

        logger.info("JSON report saved to %s", report_path)
        return report_path

    def export_csv(
        self, results: list[ResultDict], output_path: str | None = None
    ) -> str:
        """Export results to CSV format.

        Args:
            results: List of benchmark result dictionaries.
            output_path: Path for the CSV file.

        Returns:
            Path to the generated CSV file.
        """
        import csv

        if output_path is None:
            output_path = os.path.join(self.output_dir, "benchmark_results.csv")

        # Determine all columns
        all_keys: set[str] = set()
        for r in results:
            all_keys.update(r.keys())

        # Remove raw_times from CSV
        columns = [k for k in sorted(all_keys) if k != "raw_times"]

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for r in results:
                row = {k: v for k, v in r.items() if k != "raw_times"}
                # Convert numpy types
                for k, v in row.items():
                    if isinstance(v, (np.integer,)):
                        row[k] = int(v)
                    elif isinstance(v, (np.floating,)):
                        row[k] = float(v)
                    elif isinstance(v, list):
                        row[k] = f"[{len(v)} samples]"
                writer.writerow(row)

        logger.info("CSV export saved to %s", output_path)
        return output_path


class _BenchmarkEncoder(json.JSONEncoder):
    """Custom JSON encoder for benchmark data types."""

    def default(self, obj: Any) -> Any:
        """Handle special types for JSON serialization.

        Args:
            obj: Object to serialize.

        Returns:
            JSON-serializable representation.
        """
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, (datetime,)):
            return obj.isoformat()
        if isinstance(obj, (set,)):
            return list(obj)
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate JSON benchmark report")
    parser.add_argument("--input", "-i", required=True, help="Input JSON results file")
    parser.add_argument("--output", "-o", default="reports/output", help="Output directory")
    parser.add_argument("--csv", action="store_true", help="Also export as CSV")
    args = parser.parse_args()

    import json as std_json
    with open(args.input) as f:
        results = std_json.load(f)

    config = {"output_dir": args.output}
    gen = JSONReportGenerator(config)
    path = gen.generate_report(results)
    print(f"JSON report saved to: {path}")

    if args.csv:
        csv_path = gen.export_csv(results)
        print(f"CSV export saved to: {csv_path}")