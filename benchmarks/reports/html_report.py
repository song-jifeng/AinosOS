"""
HTML Report Generator
======================

Generates comprehensive HTML reports from benchmark results, including
interactive charts, sortable tables, and system information.

This module supports:
- Fully self-contained HTML reports
- Interactive charts using Plotly
- Sortable and filterable result tables
- Performance distribution histograms
- Comparative analysis sections
- System information display
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

import numpy as np

from benchmarks import ResultDict
from benchmarks.reports.report_generator import ReportGenerator

logger = logging.getLogger(__name__)


class HTMLReportGenerator(ReportGenerator):
    """HTML report generator for benchmark results.

    Creates interactive HTML reports with embedded charts, tables,
    and system information.

    Attributes:
        name: Name of this report generator.
        template: HTML template name to use.
        include_charts: Whether to include charts.
        include_tables: Whether to include data tables.
        theme: Report theme ('light' or 'dark').
        output_file: Name of the output HTML file.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the HTML report generator.

        Args:
            config: Configuration dictionary. Expected keys: template,
                include_charts, include_tables, theme, output_file.
        """
        super().__init__(config)
        self.name = "html_report"
        self.template: str = self.config.get("template", "default")
        self.include_charts: bool = self.config.get("include_charts", True)
        self.include_tables: bool = self.config.get("include_tables", True)
        self.theme: str = self.config.get("theme", "light")
        self.output_file: str = self.config.get("output_file", "benchmark_report.html")

    def _generate_charts_html(self, results: list[ResultDict]) -> str:
        """Generate HTML with embedded charts.

        Args:
            results: List of benchmark result dictionaries.

        Returns:
            HTML string with chart elements.
        """
        charts_html = ""

        try:
            from benchmarks.reports.chart import ChartGenerator
            chart_gen = ChartGenerator(self.config)

            # Generate chart images
            chart_dir = os.path.join(self.output_dir, "charts")
            os.makedirs(chart_dir, exist_ok=True)

            # Latency comparison chart
            latency_path = os.path.join(chart_dir, "latency_comparison.png")
            chart_gen.plot_latency_comparison(results, latency_path)
            charts_html += f'<div class="chart"><h3>Latency Comparison</h3>'
            charts_html += f'<img src="charts/latency_comparison.png" alt="Latency Comparison"></div>\n'

            # Throughput chart
            throughput_path = os.path.join(chart_dir, "throughput.png")
            chart_gen.plot_throughput(results, throughput_path)
            charts_html += f'<div class="chart"><h3>Throughput</h3>'
            charts_html += f'<img src="charts/throughput.png" alt="Throughput"></div>\n'

            # Distribution chart
            dist_path = os.path.join(chart_dir, "latency_distribution.png")
            chart_gen.plot_latency_distribution(results, dist_path)
            charts_html += f'<div class="chart"><h3>Latency Distribution</h3>'
            charts_html += f'<img src="charts/latency_distribution.png" alt="Distribution"></div>\n'

            # Trend chart
            trend_path = os.path.join(chart_dir, "performance_trend.png")
            chart_gen.plot_performance_trend(results, trend_path)
            charts_html += f'<div class="chart"><h3>Performance Trend</h3>'
            charts_html += f'<img src="charts/performance_trend.png" alt="Trend"></div>\n'

            # Heatmap
            heatmap_path = os.path.join(chart_dir, "correlation_heatmap.png")
            chart_gen.plot_correlation_heatmap(results, heatmap_path)
            charts_html += f'<div class="chart"><h3>Correlation Heatmap</h3>'
            charts_html += f'<img src="charts/correlation_heatmap.png" alt="Heatmap"></div>\n'

        except Exception as exc:
            logger.warning("Failed to generate charts: %s", exc)
            charts_html = f'<p class="error">Chart generation failed: {exc}</p>'

        return charts_html

    def _generate_tables_html(self, results: list[ResultDict]) -> str:
        """Generate HTML with result tables.

        Args:
            results: List of benchmark result dictionaries.

        Returns:
            HTML string with table elements.
        """
        tables_html = ""

        # Group results by benchmark type
        grouped = self.aggregate_results(results)

        for bench_name, bench_results in grouped.items():
            tables_html += f'<div class="table-section">\n'
            tables_html += f'<h3>{bench_name}</h3>\n'
            tables_html += '<table class="results-table">\n'
            tables_html += '<thead><tr>\n'

            # Determine columns from first result
            if bench_results:
                # Key columns to display
                key_columns = [
                    "benchmark", "model", "size", "batch_size", "operation",
                    "method", "sdk", "library", "index_type", "allocator",
                ]
                metric_columns = [
                    "mean_ms", "median_ms", "p50_ms", "p90_ms", "p95_ms", "p99_ms",
                    "std_ms", "min_ms", "max_ms", "mean_s", "mean_ns",
                    "throughput_MBps", "requests_per_sec", "gflops",
                    "bandwidth_GBs", "mean_rss_MB", "mean_vms_MB",
                ]

                # Add relevant columns
                cols = []
                for kc in key_columns:
                    if kc in bench_results[0]:
                        cols.append(kc)
                for mc in metric_columns:
                    if mc in bench_results[0]:
                        cols.append(mc)

                # Add error column if present
                if any("error" in r for r in bench_results):
                    cols.append("error")

                for col in cols:
                    tables_html += f'<th>{col}</th>\n'
                tables_html += '</tr></thead>\n<tbody>\n'

                for r in bench_results:
                    tables_html += '<tr'
                    if "error" in r:
                        tables_html += ' class="error"'
                    tables_html += '>\n'
                    for col in cols:
                        val = r.get(col, "")
                        if isinstance(val, float):
                            if "ms" in col or "ns" in col:
                                val_str = f"{val:.3f}"
                            elif val > 1000:
                                val_str = f"{val:.1f}"
                            else:
                                val_str = f"{val:.4f}"
                        elif isinstance(val, list):
                            val_str = f"[{len(val)} samples]"
                        elif val is None:
                            val_str = ""
                        else:
                            val_str = str(val)
                        tables_html += f'<td>{val_str}</td>\n'
                    tables_html += '</tr>\n'

            tables_html += '</tbody></table>\n</div>\n'

        return tables_html

    def _generate_summary_html(self, results: list[ResultDict]) -> str:
        """Generate HTML summary section.

        Args:
            results: List of benchmark result dictionaries.

        Returns:
            HTML string with summary.
        """
        total = len(results)
        successful = sum(1 for r in results if "error" not in r)
        failed = total - successful

        # Collect benchmark types
        bench_types = set(r.get("benchmark", "unknown") for r in results)

        # Compute overall statistics
        mean_values = []
        for r in results:
            for key in ("mean_ms", "mean_s", "mean_ns"):
                val = r.get(key)
                if isinstance(val, (int, float)):
                    mean_values.append(val)
                    break

        summary = f"""
        <div class="summary">
            <h2>Benchmark Summary</h2>
            <div class="summary-grid">
                <div class="summary-card">
                    <h4>Total Runs</h4>
                    <p class="big-number">{total}</p>
                </div>
                <div class="summary-card">
                    <h4>Successful</h4>
                    <p class="big-number success">{successful}</p>
                </div>
                <div class="summary-card">
                    <h4>Failed</h4>
                    <p class="big-number {'error' if failed > 0 else 'success'}">{failed}</p>
                </div>
                <div class="summary-card">
                    <h4>Benchmark Types</h4>
                    <p class="big-number">{len(bench_types)}</p>
                </div>
            </div>
            <h3>Benchmark Categories</h3>
            <ul>
        """
        for bt in sorted(bench_types):
            count = sum(1 for r in results if r.get("benchmark") == bt)
            err_count = sum(1 for r in results if r.get("benchmark") == bt and "error" in r)
            summary += f'<li>{bt}: {count} runs ({err_count} errors)</li>\n'

        summary += "</ul></div>"
        return summary

    def _generate_system_info_html(self) -> str:
        """Generate HTML for system information section.

        Returns:
            HTML string with system information.
        """
        info = self.get_system_info()
        html = '<div class="system-info">\n<h2>System Information</h2>\n<table>\n'

        for category, data in info.items():
            if isinstance(data, dict):
                html += f'<tr><th colspan="2">{category}</th></tr>\n'
                for key, value in data.items():
                    html += f'<tr><td>{key}</td><td>{value}</td></tr>\n'

        html += '</table>\n</div>\n'
        return html

    def generate_report(
        self, results: list[ResultDict], report_name: str = "benchmark_report"
    ) -> str:
        """Generate a complete HTML report from benchmark results.

        Args:
            results: List of benchmark result dictionaries.
            report_name: Base name for the report file.

        Returns:
            Path to the generated HTML file.
        """
        logger.info("Generating HTML report with %d results", len(results))

        # Build report sections
        summary_html = self._generate_summary_html(results)
        tables_html = self._generate_tables_html(results) if self.include_tables else ""
        charts_html = self._generate_charts_html(results) if self.include_charts else ""
        system_info_html = self._generate_system_info_html() if self.include_metadata else ""

        # CSS styles
        theme_bg = "#ffffff" if self.theme == "light" else "#1a1a2e"
        theme_text = "#333333" if self.theme == "light" else "#e0e0e0"
        theme_card = "#f5f5f5" if self.theme == "light" else "#16213e"

        report_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ainos Benchmark Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, sans-serif;
            background-color: {theme_bg};
            color: {theme_text};
            line-height: 1.6;
            padding: 20px;
            max-width: 1400px;
            margin: 0 auto;
        }}
        h1, h2, h3, h4 {{ margin-top: 1.5em; margin-bottom: 0.5em; }}
        h1 {{ border-bottom: 2px solid #4a90d9; padding-bottom: 10px; }}
        .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 20px 0; }}
        .summary-card {{ background: {theme_card}; padding: 20px; border-radius: 8px; text-align: center; }}
        .big-number {{ font-size: 2em; font-weight: bold; color: #4a90d9; }}
        .success {{ color: #27ae60; }}
        .error {{ color: #e74c3c; }}
        .results-table {{ width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 0.9em; }}
        .results-table th {{ background: #4a90d9; color: white; padding: 10px; text-align: left; }}
        .results-table td {{ padding: 8px 10px; border-bottom: 1px solid #ddd; }}
        .results-table tr:hover {{ background: rgba(74, 144, 217, 0.1); }}
        .results-table tr.error {{ background: rgba(231, 76, 60, 0.1); }}
        .chart {{ margin: 30px 0; text-align: center; }}
        .chart img {{ max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .system-info table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        .system-info th {{ background: {theme_card}; padding: 8px; text-align: left; }}
        .system-info td {{ padding: 6px 10px; border-bottom: 1px solid #ddd; }}
        .table-section h3 {{ color: #4a90d9; }}
        .summary ul {{ margin-left: 20px; }}
        .summary li {{ margin: 5px 0; }}
        .footer {{ margin-top: 40px; padding: 20px; text-align: center; font-size: 0.8em; color: #999; }}
    </style>
</head>
<body>
    <h1>Ainos Performance Benchmark Report</h1>
    <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

    {summary_html}
    {charts_html}
    {tables_html}
    {system_info_html}

    <div class="footer">
        <p>Ainos Performance Benchmark Suite v1.0.0</p>
        <p>Report generated by Ainos Benchmarks</p>
    </div>
</body>
</html>"""

        # Write report
        report_path = os.path.join(self.output_dir, self.output_file)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_html)

        logger.info("HTML report saved to %s", report_path)
        return report_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate HTML benchmark report")
    parser.add_argument("--input", "-i", required=True, help="Input JSON results file")
    parser.add_argument("--output", "-o", default="reports/output", help="Output directory")
    args = parser.parse_args()

    import json as std_json
    with open(args.input) as f:
        results = std_json.load(f)

    config = {"output_dir": args.output}
    gen = HTMLReportGenerator(config)
    path = gen.generate_report(results)
    print(f"Report saved to: {path}")