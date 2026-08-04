"""Report generation for AinosOS model benchmark results.

Provides report generation in multiple formats (text, JSON, CSV, Markdown, HTML)
with support for templates, sections, and embedded charts.
"""

from __future__ import annotations

import csv
import html
import json
import os
import textwrap
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Optional, Union

from .template import (
    BenchmarkResult,
    BenchmarkType,
    ComparisonResult,
    HardwareType,
    PrecisionType,
    ResultStatus,
    ResultSummary,
)


# ---------------------------------------------------------------------------
# ReportSection - nested report content container
# ---------------------------------------------------------------------------

class ReportSection:
    """A hierarchical section of a report with title, content, and subsections."""

    def __init__(
        self,
        title: str = "",
        content: str = "",
        level: int = 1,
        sections: Optional[list[ReportSection]] = None,
    ) -> None:
        self.title = title
        self.content = content
        self.level = level
        self.sections = sections or []

    def add_section(self, section: ReportSection) -> None:
        """Add a subsection."""
        self.sections.append(section)

    def add_content(self, content: str) -> None:
        """Append content to this section."""
        if self.content:
            self.content += "\n" + content
        else:
            self.content = content

    def render_text(self, indent: int = 0) -> str:
        """Render the section as plain text."""
        lines: list[str] = []
        prefix = "  " * indent

        if self.title:
            if self.level == 1:
                lines.append("")
                lines.append("=" * 60)
                lines.append(f"{prefix}{self.title}")
                lines.append("=" * 60)
            elif self.level == 2:
                lines.append("")
                lines.append(f"{prefix}{self.title}")
                lines.append(f"{prefix}{'-' * 40}")
            elif self.level == 3:
                lines.append(f"\n{prefix}{self.title}")
                lines.append(f"{prefix}{'.' * 30}")
            else:
                lines.append(f"\n{prefix}{self.title}:")

        if self.content:
            wrapped = textwrap.fill(self.content, width=80, initial_indent=prefix, subsequent_indent=prefix + "  ")
            lines.append(wrapped)

        for section in self.sections:
            lines.append(section.render_text(indent + 1))

        return "\n".join(lines)

    def render_markdown(self) -> str:
        """Render the section as Markdown."""
        lines: list[str] = []

        if self.title:
            heading_marker = "#" * min(self.level, 6)
            lines.append(f"\n{heading_marker} {self.title}\n")

        if self.content:
            lines.append(self.content)
            lines.append("")

        for section in self.sections:
            rendered = section.render_markdown()
            if rendered:
                lines.append(rendered)

        return "\n".join(lines)

    def render_html(self) -> str:
        """Render the section as HTML."""
        parts: list[str] = []

        if self.title:
            tag = f"h{min(self.level, 6)}"
            escaped_title = html.escape(self.title)
            parts.append(f"<{tag}>{escaped_title}</{tag}>")

        if self.content:
            escaped_content = html.escape(self.content)
            # Convert simple Markdown-like formatting
            escaped_content = escaped_content.replace("\n", "<br>\n")
            parts.append(f"<p>{escaped_content}</p>")

        for section in self.sections:
            parts.append(section.render_html())

        return "\n".join(parts)


# ---------------------------------------------------------------------------
# ReportTemplate
# ---------------------------------------------------------------------------

class ReportTemplate:
    """Loadable report template for filling with benchmark data."""

    def __init__(self, name: str = "", template_str: str = "") -> None:
        self.name = name
        self.template_str = template_str

    def load_template(self, name: str) -> str:
        """Load a template by name.

        Args:
            name: The template name.

        Returns:
            The template string.
        """
        if name in BUILTIN_TEMPLATES:
            return BUILTIN_TEMPLATES[name]
        raise ValueError(f"Unknown template: {name}")

    def render(self, data: dict[str, Any]) -> str:
        """Fill the template with data.

        Performs simple variable substitution using {{ variable }} syntax.

        Args:
            data: Dictionary of variables to substitute.

        Returns:
            The rendered template string.
        """
        result = self.template_str
        for key, value in data.items():
            placeholder = "{{ " + key + " }}"
            if isinstance(value, float):
                str_value = f"{value:.4f}"
            else:
                str_value = str(value)
            result = result.replace(placeholder, str_value)
        return result


# ---------------------------------------------------------------------------
# Built-in report templates
# ---------------------------------------------------------------------------

BUILTIN_TEMPLATES: dict[str, str] = {
    "standard": """# Benchmark Report: {{ model_name }}

**Date:** {{ date }}
**Hardware:** {{ hardware }}
**Precision:** {{ precision }}
**Benchmark Type:** {{ benchmark_type }}

## Summary

| Metric | Value |
|--------|-------|
| Mean Latency | {{ mean_latency }} ms |
| P50 Latency | {{ p50_latency }} ms |
| P95 Latency | {{ p95_latency }} ms |
| P99 Latency | {{ p99_latency }} ms |
| Throughput | {{ throughput }} tokens/s |
| Peak RAM | {{ peak_ram }} MB |
| Peak VRAM | {{ peak_vram }} MB |
| Overall Score | {{ score }} |

## Configuration

- **Batch Size:** {{ batch_size }}
- **Context Length:** {{ context_length }}
- **Prompt Length:** {{ prompt_length }}
- **Generated Tokens:** {{ num_tokens }}
- **Warmup Runs:** {{ warmup_runs }}
- **Measured Runs:** {{ num_runs }}

## Notes

{{ notes }}
""",

    "comparison": """# Model Comparison Report

**Date:** {{ date }}
**Comparison Metric:** {{ metric }}

## Results Overview

{{ comparison_table }}

## Rankings

### By Latency (lower is better)
{{ latency_ranking }}

### By Throughput (higher is better)
{{ throughput_ranking }}

### By Memory Efficiency (lower is better)
{{ memory_ranking }}

## Speedups vs Baseline

{{ speedup_table }}

## Detailed Results

{{ detailed_results }}
""",

    "summary": """# Executive Summary - Benchmark Results

**Generated:** {{ date }}
**Models Tested:** {{ num_models }}
**Total Runs:** {{ total_runs }}

## Top Performers

### Fastest Model
{{ fastest_model }} - {{ fastest_latency }} ms mean latency

### Highest Throughput
{{ highest_throughput_model }} - {{ highest_throughput_value }} tokens/s

### Most Memory Efficient
{{ most_efficient_model }} - {{ most_efficient_memory }} MB peak RAM

## Key Findings

{{ key_findings }}

## Recommendations

{{ recommendations }}
""",

    "regression": """# Regression Analysis Report

**Model:** {{ model_name }}
**Analysis Date:** {{ date }}
**Baseline Period:** {{ baseline_period }}
**Current Period:** {{ current_period }}

## Summary

**Status:** {{ status }}
**Regressions Detected:** {{ num_regressions }}
**Improvements Detected:** {{ num_improvements }}

## Regressions

{{ regression_details }}

## Improvements

{{ improvement_details }}

## Statistical Significance

{{ significance_table }}

## Recommendations

{{ recommendations }}
""",

    "detailed": """# Detailed Benchmark Report: {{ model_name }}

**Report ID:** {{ report_id }}
**Generated:** {{ generated_at }}

## 1. Metadata

| Field | Value |
|-------|-------|
| Model | {{ model_name }} |
| Version | {{ model_version }} |
| Family | {{ model_family }} |
| Benchmark Type | {{ benchmark_type }} |
| Hardware | {{ hardware }} |
| Precision | {{ precision }} |
| Framework | {{ framework }} |
| Framework Version | {{ framework_version }} |
| Date | {{ date }} |
| Runner Version | {{ runner_version }} |
| Commit Hash | {{ commit_hash }} |

## 2. Latency Analysis

| Metric | Value (ms) |
|--------|-----------|
| Mean | {{ mean_latency }} |
| P50 | {{ p50_latency }} |
| P95 | {{ p95_latency }} |
| P99 | {{ p99_latency }} |
| Min | {{ min_latency }} |
| Max | {{ max_latency }} |
| Std Dev | {{ std_dev_latency }} |
| TTFT | {{ ttft_latency }} |
| Inter-Token | {{ inter_token_latency }} |
| Prefill | {{ prefill_latency }} |
| Decode | {{ decode_latency }} |

## 3. Throughput Analysis

| Metric | Value |
|--------|-------|
| Tokens/s | {{ throughput }} |
| Requests/s | {{ requests_per_second }} |
| Samples/s | {{ samples_per_second }} |
| Total Tokens | {{ total_tokens }} |
| Total Time | {{ total_time }} s |
| Batch Size | {{ batch_size }} |
| Concurrent Requests | {{ concurrent_requests }} |

## 4. Memory Analysis

| Metric | Value (MB) |
|--------|-----------|
| Peak RAM | {{ peak_ram }} |
| Steady RAM | {{ steady_ram }} |
| Peak VRAM | {{ peak_vram }} |
| Steady VRAM | {{ steady_vram }} |
| Swap Usage | {{ swap_usage }} |
| Memory Efficiency | {{ memory_efficiency }}% |

## 5. Raw Timing Data

{{ raw_timings }}

## 6. Environment

{{ environment }}

## 7. Errors and Warnings

{{ errors_warnings }}

""",
}


# ---------------------------------------------------------------------------
# ReportGenerator
# ---------------------------------------------------------------------------

class ReportGenerator:
    """Generate benchmark reports in various formats."""

    def __init__(self, output_dir: Optional[Path] = None) -> None:
        """Initialize the report generator.

        Args:
            output_dir: Default output directory for reports.
        """
        self.output_dir = Path(output_dir) if output_dir else Path.cwd()
        self._generated_at = datetime.now(timezone.utc)

    def _auto_filename(
        self,
        result: BenchmarkResult,
        suffix: str = "",
        ext: str = ".txt",
    ) -> str:
        """Generate an automatic filename for a report.

        Format: {model_name}_{benchmark_type}_{hardware}_{date}_{id}{suffix}{ext}
        """
        model = result.metadata.model_name.replace("/", "_").replace(" ", "_")
        btype = result.metadata.benchmark_type.value
        hw = result.metadata.hardware_type.value
        date = result.metadata.date.replace("-", "")
        rid = result.result_id[-8:] if len(result.result_id) > 8 else result.result_id
        base = f"{model}_{btype}_{hw}_{date}_{rid}"
        if suffix:
            base += f"_{suffix}"
        return base + ext

    def _ensure_output_dir(self, output_path: Optional[Path] = None) -> Path:
        """Ensure output directory exists and return the path."""
        out = Path(output_path) if output_path else self.output_dir
        out.mkdir(parents=True, exist_ok=True)
        return out

    # ---- Text report ----

    def generate_text_report(
        self,
        result: BenchmarkResult,
        output_path: Optional[Path] = None,
    ) -> str:
        """Generate a plain-text report for a single result.

        Args:
            result: The benchmark result.
            output_path: Optional path to write the report to.

        Returns:
            The report text.
        """
        from .comparison import ResultFormatter
        formatter = ResultFormatter()
        report = formatter.format_as_text(result)

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report, encoding="utf-8")

        return report

    # ---- JSON report ----

    def generate_json_report(
        self,
        result: BenchmarkResult,
        output_path: Optional[Path] = None,
        indent: int = 2,
    ) -> str:
        """Generate a JSON report for a single result.

        Args:
            result: The benchmark result.
            output_path: Optional path to write the report to.
            indent: JSON indentation level.

        Returns:
            The JSON string.
        """
        report = json.dumps(result.to_dict(), indent=indent, ensure_ascii=False)

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report, encoding="utf-8")

        return report

    # ---- CSV report ----

    def generate_csv_report(
        self,
        results: list[BenchmarkResult],
        output_path: Optional[Path] = None,
    ) -> str:
        """Generate a CSV report for multiple results.

        Args:
            results: List of benchmark results.
            output_path: Optional path to write the CSV to.

        Returns:
            The CSV string.
        """
        from .comparison import ResultFormatter
        formatter = ResultFormatter()
        csv_str = formatter.format_as_csv(results)

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(csv_str, encoding="utf-8")

        return csv_str

    # ---- Markdown report ----

    def generate_markdown_report(
        self,
        result: BenchmarkResult,
        output_path: Optional[Path] = None,
    ) -> str:
        """Generate a Markdown report for a single result.

        Args:
            result: The benchmark result.
            output_path: Optional path to write the report to.

        Returns:
            The Markdown string.
        """
        lines = [
            f"# Benchmark Report: {result.metadata.model_name}",
            "",
            f"**Result ID:** {result.result_id}",
            f"**Date:** {result.metadata.date}",
            f"**Status:** {result.status.value}",
            "",
            "## Metadata",
            "",
            "| Field | Value |",
            "|-------|-------|",
            f"| Model | {result.metadata.model_name} |",
            f"| Version | {result.metadata.model_version} |",
            f"| Family | {result.metadata.model_family} |",
            f"| Benchmark Type | {result.metadata.benchmark_type.value} |",
            f"| Hardware | {result.metadata.hardware_type.value} |",
            f"| Precision | {result.metadata.precision.value} |",
            f"| Batch Size | {result.metadata.batch_size} |",
            f"| Context Length | {result.metadata.context_length} |",
            f"| Prompt Length | {result.metadata.prompt_length} |",
            f"| Runs | {result.metadata.num_runs} |",
            "",
        ]

        if result.latency.mean_ms > 0:
            lines.extend([
                "## Latency",
                "",
                "| Metric | Value (ms) |",
                "|--------|-----------|",
                f"| Mean | {result.latency.mean_ms:.4f} |",
                f"| P50 | {result.latency.p50_ms:.4f} |",
                f"| P95 | {result.latency.p95_ms:.4f} |",
                f"| P99 | {result.latency.p99_ms:.4f} |",
                f"| Min | {result.latency.min_ms:.4f} |",
                f"| Max | {result.latency.max_ms:.4f} |",
                f"| Std Dev | {result.latency.std_dev_ms:.4f} |",
                f"| TTFT | {result.latency.time_to_first_token_ms:.4f} |",
                f"| Inter-Token | {result.latency.inter_token_latency_ms:.4f} |",
                "",
            ])

        if result.throughput.tokens_per_second > 0:
            lines.extend([
                "## Throughput",
                "",
                "| Metric | Value |",
                "|--------|-------|",
                f"| Tokens/s | {result.throughput.tokens_per_second:.4f} |",
                f"| Requests/s | {result.throughput.requests_per_second:.4f} |",
                f"| Total Tokens | {result.throughput.total_tokens} |",
                f"| Total Time | {result.throughput.total_time_seconds:.2f} s |",
                "",
            ])

        if result.memory.peak_ram_mb > 0:
            lines.extend([
                "## Memory",
                "",
                "| Metric | Value (MB) |",
                "|--------|-----------|",
                f"| Peak RAM | {result.memory.peak_ram_mb:.2f} |",
                f"| Steady RAM | {result.memory.steady_ram_mb:.2f} |",
                f"| Peak VRAM | {result.memory.peak_vram_mb:.2f} |",
                f"| Memory Efficiency | {result.memory.memory_efficiency_pct:.2f}% |",
                "",
            ])

        if result.score > 0:
            lines.extend([
                "## Overall Score",
                "",
                f"**Score:** {result.score:.4f}",
                "",
            ])
            if result.score_breakdown:
                lines.append("### Score Breakdown\n")
                for k, v in result.score_breakdown.items():
                    lines.append(f"- **{k}:** {v:.4f}")
                lines.append("")

        if result.errors:
            lines.extend(["## Errors", ""])
            for e in result.errors:
                lines.append(f"- {e}")
            lines.append("")

        if result.warnings:
            lines.extend(["## Warnings", ""])
            for w in result.warnings:
                lines.append(f"- {w}")
            lines.append("")

        report = "\n".join(lines)

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report, encoding="utf-8")

        return report

    # ---- HTML report ----

    def generate_html_report(
        self,
        result: BenchmarkResult,
        output_path: Optional[Path] = None,
        include_charts: bool = True,
    ) -> str:
        """Generate an HTML report with inline CSS and optional SVG charts.

        Args:
            result: The benchmark result.
            output_path: Optional path to write the HTML to.
            include_charts: Whether to include simple bar charts.

        Returns:
            The HTML string.
        """
        css = """
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                   max-width: 960px; margin: 0 auto; padding: 20px; color: #333; }
            h1 { color: #1a1a2e; border-bottom: 3px solid #4a90d9; padding-bottom: 10px; }
            h2 { color: #16213e; border-bottom: 1px solid #ddd; padding-bottom: 5px; margin-top: 30px; }
            h3 { color: #0f3460; }
            table { border-collapse: collapse; width: 100%; margin: 15px 0; }
            th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
            th { background-color: #4a90d9; color: white; }
            tr:nth-child(even) { background-color: #f9f9f9; }
            tr:hover { background-color: #f1f1f1; }
            .status-completed { color: #28a745; font-weight: bold; }
            .status-failed { color: #dc3545; font-weight: bold; }
            .status-warning { color: #ffc107; font-weight: bold; }
            .score { font-size: 1.2em; font-weight: bold; color: #4a90d9; }
            .bar-chart { margin: 10px 0; }
            .bar { height: 24px; margin: 4px 0; background: linear-gradient(90deg, #4a90d9, #357abd);
                   border-radius: 4px; color: white; padding: 2px 8px; font-size: 12px;
                   display: flex; align-items: center; min-width: 60px; }
            .bar-label { margin-right: 8px; white-space: nowrap; }
            .bar-value { margin-left: auto; }
            .metadata-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
            .metadata-item { padding: 8px; background: #f8f9fa; border-radius: 4px; }
            .metadata-label { font-weight: bold; color: #666; font-size: 0.85em; }
            .metadata-value { font-size: 1.1em; }
            .footer { margin-top: 30px; padding-top: 10px; border-top: 1px solid #ddd;
                      font-size: 0.85em; color: #666; }
        </style>
        """

        def _bar(label: str, value: float, max_val: float, unit: str = "") -> str:
            pct = (value / max_val * 100) if max_val > 0 else 0
            width = max(pct, 5)  # minimum 5% for visibility
            display = f"{value:.2f}{unit}" if unit else f"{value:.2f}"
            return (
                f'<div class="bar" style="width: {min(width, 100):.1f}%;">'
                f'<span class="bar-label">{html.escape(label)}</span>'
                f'<span class="bar-value">{html.escape(display)}</span>'
                f"</div>"
            )

        # Determine max values for bar scaling
        max_latency = max(result.latency.mean_ms, result.latency.p50_ms,
                          result.latency.p95_ms, result.latency.p99_ms, 1)
        max_throughput = max(result.throughput.tokens_per_second, 1)
        max_memory = max(result.memory.peak_ram_mb, result.memory.steady_ram_mb, 1)

        status_class = f"status-{result.status.value}"

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Benchmark Report: {html.escape(result.metadata.model_name)}</title>
    {css}
</head>
<body>
    <h1>Benchmark Report: {html.escape(result.metadata.model_name)}</h1>
    <p>
        <strong>Result ID:</strong> {html.escape(result.result_id)}<br>
        <strong>Date:</strong> {html.escape(result.metadata.date)}<br>
        <strong>Status:</strong> <span class="{status_class}">{result.status.value}</span>
    </p>

    <h2>Metadata</h2>
    <div class="metadata-grid">
        <div class="metadata-item">
            <div class="metadata-label">Benchmark Type</div>
            <div class="metadata-value">{result.metadata.benchmark_type.value}</div>
        </div>
        <div class="metadata-item">
            <div class="metadata-label">Hardware</div>
            <div class="metadata-value">{result.metadata.hardware_type.value}</div>
        </div>
        <div class="metadata-item">
            <div class="metadata-label">Precision</div>
            <div class="metadata-value">{result.metadata.precision.value}</div>
        </div>
        <div class="metadata-item">
            <div class="metadata-label">Batch Size</div>
            <div class="metadata-value">{result.metadata.batch_size}</div>
        </div>
        <div class="metadata-item">
            <div class="metadata-label">Context Length</div>
            <div class="metadata-value">{result.metadata.context_length}</div>
        </div>
        <div class="metadata-item">
            <div class="metadata-label">Framework</div>
            <div class="metadata-value">{html.escape(result.metadata.framework)}</div>
        </div>
    </div>

    <h2>Latency</h2>
    <table>
        <tr><th>Metric</th><th>Value (ms)</th></tr>
        <tr><td>Mean</td><td>{result.latency.mean_ms:.4f}</td></tr>
        <tr><td>P50</td><td>{result.latency.p50_ms:.4f}</td></tr>
        <tr><td>P95</td><td>{result.latency.p95_ms:.4f}</td></tr>
        <tr><td>P99</td><td>{result.latency.p99_ms:.4f}</td></tr>
        <tr><td>Min</td><td>{result.latency.min_ms:.4f}</td></tr>
        <tr><td>Max</td><td>{result.latency.max_ms:.4f}</td></tr>
        <tr><td>Std Dev</td><td>{result.latency.std_dev_ms:.4f}</td></tr>
        <tr><td>TTFT</td><td>{result.latency.time_to_first_token_ms:.4f}</td></tr>
    </table>
"""

        if include_charts and result.latency.mean_ms > 0:
            html_content += """
    <h3>Latency Distribution</h3>
    <div class="bar-chart">
""" + _bar("P50", result.latency.p50_ms, max_latency, " ms") + "\n"
            html_content += _bar("P95", result.latency.p95_ms, max_latency, " ms") + "\n"
            html_content += _bar("P99", result.latency.p99_ms, max_latency, " ms") + "\n"
            html_content += _bar("Mean", result.latency.mean_ms, max_latency, " ms") + "\n"
            html_content += """    </div>
"""

        if result.throughput.tokens_per_second > 0:
            html_content += f"""
    <h2>Throughput</h2>
    <table>
        <tr><th>Metric</th><th>Value</th></tr>
        <tr><td>Tokens/s</td><td>{result.throughput.tokens_per_second:.4f}</td></tr>
        <tr><td>Requests/s</td><td>{result.throughput.requests_per_second:.4f}</td></tr>
        <tr><td>Total Tokens</td><td>{result.throughput.total_tokens}</td></tr>
        <tr><td>Total Time</td><td>{result.throughput.total_time_seconds:.2f} s</td></tr>
    </table>
"""
            if include_charts:
                html_content += """
    <h3>Throughput</h3>
    <div class="bar-chart">
""" + _bar("Tokens/s", result.throughput.tokens_per_second, max_throughput, " t/s") + "\n"
                if result.throughput.requests_per_second > 0:
                    html_content += _bar("Requests/s", result.throughput.requests_per_second, max_throughput, " r/s") + "\n"
                html_content += """    </div>
"""

        if result.memory.peak_ram_mb > 0:
            html_content += f"""
    <h2>Memory</h2>
    <table>
        <tr><th>Metric</th><th>Value (MB)</th></tr>
        <tr><td>Peak RAM</td><td>{result.memory.peak_ram_mb:.2f}</td></tr>
        <tr><td>Steady RAM</td><td>{result.memory.steady_ram_mb:.2f}</td></tr>
        <tr><td>Peak VRAM</td><td>{result.memory.peak_vram_mb:.2f}</td></tr>
        <tr><td>Memory Efficiency</td><td>{result.memory.memory_efficiency_pct:.2f}%</td></tr>
    </table>
"""
            if include_charts:
                html_content += """
    <h3>Memory Usage</h3>
    <div class="bar-chart">
""" + _bar("Peak RAM", result.memory.peak_ram_mb, max_memory, " MB") + "\n"
                html_content += _bar("Steady RAM", result.memory.steady_ram_mb, max_memory, " MB") + "\n"
                if result.memory.peak_vram_mb > 0:
                    html_content += _bar("Peak VRAM", result.memory.peak_vram_mb, max_memory, " MB") + "\n"
                html_content += """    </div>
"""

        if result.score > 0:
            html_content += f"""
    <h2>Overall Score</h2>
    <p class="score">{result.score:.4f}</p>
"""
            if result.score_breakdown:
                html_content += """    <h3>Score Breakdown</h3>
    <table><tr><th>Component</th><th>Score</th></tr>
"""
                for k, v in result.score_breakdown.items():
                    html_content += f"        <tr><td>{html.escape(k)}</td><td>{v:.4f}</td></tr>\n"
                html_content += "    </table>\n"

        if result.errors:
            html_content += """    <h2>Errors</h2>
    <ul>
"""
            for e in result.errors:
                html_content += f"        <li>{html.escape(e)}</li>\n"
            html_content += "    </ul>\n"

        if result.warnings:
            html_content += """    <h2>Warnings</h2>
    <ul>
"""
            for w in result.warnings:
                html_content += f"        <li>{html.escape(w)}</li>\n"
            html_content += "    </ul>\n"

        html_content += f"""
    <div class="footer">
        Generated by AinosOS Benchmark System on {self._generated_at.strftime("%Y-%m-%d %H:%M:%S UTC")}
    </div>
</body>
</html>
"""

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(html_content, encoding="utf-8")

        return html_content

    # ---- Comparison report ----

    def generate_comparison_report(
        self,
        results: list[BenchmarkResult],
        output_path: Optional[Path] = None,
        format: str = "markdown",
    ) -> str:
        """Generate a comparison report for multiple results.

        Args:
            results: List of benchmark results to compare.
            output_path: Optional path to write the report to.
            format: Output format ('text', 'json', 'markdown', 'html').

        Returns:
            The report string.
        """
        from .comparison import ModelComparator, ResultFormatter

        comparator = ModelComparator()
        comparison = comparator.compare_models(results)

        if format == "json":
            report = json.dumps(comparison.to_dict(), indent=2, ensure_ascii=False)
        elif format == "html":
            report = self._generate_comparison_html(results)
        elif format == "text":
            report = self._generate_comparison_text(results, comparator)
        else:
            # Default: markdown
            report = comparator.generate_comparison_table(results)

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report, encoding="utf-8")

        return report

    def _generate_comparison_text(
        self,
        results: list[BenchmarkResult],
        comparator: ModelComparator,
    ) -> str:
        """Generate a plain-text comparison report."""
        lines = ["=" * 60, "MODEL COMPARISON REPORT", "=" * 60, ""]

        for i, r in enumerate(results):
            lines.append(f"  [{i+1}] {r.metadata.model_name}")
            lines.append(f"       Hardware: {r.metadata.hardware_type.value}")
            lines.append(f"       Precision: {r.metadata.precision.value}")
            lines.append(f"       Latency: {r.latency.mean_ms:.2f} ms")
            lines.append(f"       Throughput: {r.throughput.tokens_per_second:.2f} t/s")
            lines.append(f"       Memory: {r.memory.peak_ram_mb:.1f} MB")
            lines.append(f"       Score: {r.score:.4f}")
            lines.append("")

        lines.append("-" * 40)
        lines.append("RANKINGS")
        lines.append("-" * 40)

        rankings = comparator.rank_by_latency(results)
        lines.append("\nBy Latency (lower is better):")
        for rank, idx in enumerate(rankings, 1):
            r = results[idx]
            lines.append(f"  {rank}. {r.metadata.model_name} - {r.latency.mean_ms:.2f} ms")

        rankings = comparator.rank_by_throughput(results)
        lines.append("\nBy Throughput (higher is better):")
        for rank, idx in enumerate(rankings, 1):
            r = results[idx]
            lines.append(f"  {rank}. {r.metadata.model_name} - {r.throughput.tokens_per_second:.2f} t/s")

        lines.append("=" * 60)
        return "\n".join(lines)

    def _generate_comparison_html(
        self,
        results: list[BenchmarkResult],
    ) -> str:
        """Generate an HTML comparison report."""
        css = """
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                   max-width: 1100px; margin: 0 auto; padding: 20px; color: #333; }
            h1 { color: #1a1a2e; border-bottom: 3px solid #4a90d9; padding-bottom: 10px; }
            h2 { color: #16213e; border-bottom: 1px solid #ddd; padding-bottom: 5px; margin-top: 30px; }
            table { border-collapse: collapse; width: 100%; margin: 15px 0; }
            th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
            th { background-color: #4a90d9; color: white; }
            tr:nth-child(even) { background-color: #f9f9f9; }
            .best { background-color: #d4edda !important; }
            .worst { background-color: #f8d7da !important; }
            .footer { margin-top: 30px; padding-top: 10px; border-top: 1px solid #ddd;
                      font-size: 0.85em; color: #666; }
        </style>
        """

        rows = ""
        for r in results:
            latency = f"{r.latency.mean_ms:.2f}" if r.latency.mean_ms > 0 else "N/A"
            throughput = f"{r.throughput.tokens_per_second:.2f}" if r.throughput.tokens_per_second > 0 else "N/A"
            mem = f"{r.memory.peak_ram_mb:.1f}" if r.memory.peak_ram_mb > 0 else "N/A"
            score = f"{r.score:.4f}" if r.score > 0 else "N/A"

            rows += (
                f"<tr>"
                f"<td>{html.escape(r.metadata.model_name)}</td>"
                f"<td>{r.metadata.hardware_type.value}</td>"
                f"<td>{r.metadata.precision.value}</td>"
                f"<td>{latency}</td>"
                f"<td>{throughput}</td>"
                f"<td>{mem}</td>"
                f"<td>{score}</td>"
                f"</tr>\n"
            )

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Model Comparison Report</title>
    {css}
</head>
<body>
    <h1>Model Comparison Report</h1>
    <p>Generated on {self._generated_at.strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
    <p><strong>Models compared:</strong> {len(results)}</p>

    <h2>Results Overview</h2>
    <table>
        <thead>
            <tr>
                <th>Model</th>
                <th>Hardware</th>
                <th>Precision</th>
                <th>Latency (ms)</th>
                <th>Throughput (t/s)</th>
                <th>Peak RAM (MB)</th>
                <th>Score</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>

    <div class="footer">
        Generated by AinosOS Benchmark System
    </div>
</body>
</html>
"""
        return html_content

    # ---- Summary report ----

    def generate_summary_report(
        self,
        results: list[BenchmarkResult],
        output_path: Optional[Path] = None,
    ) -> str:
        """Generate an executive summary report.

        Args:
            results: List of benchmark results to summarize.
            output_path: Optional path to write the report to.

        Returns:
            The summary text.
        """
        from .comparison import ModelComparator

        if not results:
            return "No results to summarize."

        comparator = ModelComparator()

        # Find best performers
        latency_ranking = comparator.rank_by_latency(results)
        throughput_ranking = comparator.rank_by_throughput(results)
        memory_ranking = comparator.rank_by_memory_efficiency(results)

        best_latency = results[latency_ranking[0]]
        best_throughput = results[throughput_ranking[0]]
        best_memory = results[memory_ranking[0]]

        lines = [
            "=" * 60,
            "EXECUTIVE SUMMARY - BENCHMARK RESULTS",
            "=" * 60,
            "",
            f"Generated: {self._generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"Models Tested: {len(results)}",
            "",
            "-" * 40,
            "TOP PERFORMERS",
            "-" * 40,
            "",
            f"Fastest Model:",
            f"  {best_latency.metadata.model_name}",
            f"  Mean Latency: {best_latency.latency.mean_ms:.2f} ms",
            f"  Hardware: {best_latency.metadata.hardware_type.value}",
            f"  Precision: {best_latency.metadata.precision.value}",
            "",
            f"Highest Throughput:",
            f"  {best_throughput.metadata.model_name}",
            f"  Throughput: {best_throughput.throughput.tokens_per_second:.2f} tokens/s",
            f"  Hardware: {best_throughput.metadata.hardware_type.value}",
            f"  Precision: {best_throughput.metadata.precision.value}",
            "",
            f"Most Memory Efficient:",
            f"  {best_memory.metadata.model_name}",
            f"  Peak RAM: {best_memory.memory.peak_ram_mb:.1f} MB",
            f"  Hardware: {best_memory.metadata.hardware_type.value}",
            f"  Precision: {best_memory.metadata.precision.value}",
            "",
            "-" * 40,
            "PERFORMANCE RANKINGS",
            "-" * 40,
            "",
            "By Latency (lower is better):",
        ]

        for rank, idx in enumerate(latency_ranking, 1):
            r = results[idx]
            lines.append(f"  {rank}. {r.metadata.model_name} - {r.latency.mean_ms:.2f} ms")

        lines.extend(["", "By Throughput (higher is better):"])
        for rank, idx in enumerate(throughput_ranking, 1):
            r = results[idx]
            lines.append(f"  {rank}. {r.metadata.model_name} - {r.throughput.tokens_per_second:.2f} t/s")

        lines.extend(["", "By Memory Efficiency (lower is better):"])
        for rank, idx in enumerate(memory_ranking, 1):
            r = results[idx]
            lines.append(f"  {rank}. {r.metadata.model_name} - {r.memory.peak_ram_mb:.1f} MB")

        lines.extend([
            "",
            "-" * 40,
            "OVERALL SCORES",
            "-" * 40,
            "",
        ])

        # Sort by score
        scored = [(r.score, r.metadata.model_name, r.metadata.hardware_type.value, r.metadata.precision.value)
                  for r in results if r.score > 0]
        scored.sort(reverse=True)

        for rank, (score, name, hw, prec) in enumerate(scored, 1):
            lines.append(f"  {rank}. {name} ({hw}/{prec}): {score:.4f}")

        lines.append("")
        lines.append("=" * 60)

        report = "\n".join(lines)

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report, encoding="utf-8")

        return report

    # ---- Batch report generation ----

    def generate_reports(
        self,
        results: list[BenchmarkResult],
        formats: list[str],
        output_dir: Optional[Path] = None,
    ) -> dict[str, list[Path]]:
        """Generate reports in multiple formats for a list of results.

        Args:
            results: List of benchmark results.
            formats: List of formats ('text', 'json', 'csv', 'markdown', 'html').
            output_dir: Output directory for reports.

        Returns:
            Dictionary mapping format to list of output file paths.
        """
        out_dir = self._ensure_output_dir(output_dir)
        generated: dict[str, list[Path]] = {f: [] for f in formats}

        for result in results:
            for fmt in formats:
                ext_map = {
                    "text": ".txt",
                    "json": ".json",
                    "csv": ".csv",
                    "markdown": ".md",
                    "html": ".html",
                }
                ext = ext_map.get(fmt, ".txt")
                fname = self._auto_filename(result, ext=ext)
                fpath = out_dir / fname

                if fmt == "text":
                    self.generate_text_report(result, fpath)
                elif fmt == "json":
                    self.generate_json_report(result, fpath)
                elif fmt == "markdown":
                    self.generate_markdown_report(result, fpath)
                elif fmt == "html":
                    self.generate_html_report(result, fpath)
                elif fmt == "csv":
                    # CSV is for multiple results, handled separately
                    continue

                generated[fmt].append(fpath)

        if "csv" in formats and results:
            fname = f"benchmark_results_{self._generated_at.strftime('%Y%m%d_%H%M%S')}.csv"
            fpath = out_dir / fname
            self.generate_csv_report(results, fpath)
            generated["csv"].append(fpath)

        return generated