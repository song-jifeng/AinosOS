"""
Chart Generator
================

Generates various chart types for visualizing benchmark results. Supports
multiple chart types including bar charts, line charts, heatmaps, and
distribution plots.

This module supports:
- Latency comparison bar charts
- Throughput bar charts
- Latency distribution histograms
- Performance trend line charts
- Correlation heatmaps
- Radar charts for multi-dimensional comparison
- Customizable styles and color palettes
"""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np
from numpy.typing import NDArray

from benchmarks import ResultDict

logger = logging.getLogger(__name__)


class ChartGenerator:
    """Generator for benchmark result charts and visualizations.

    Creates publication-quality charts using matplotlib/seaborn for
    inclusion in HTML reports.

    Attributes:
        name: Name of this chart generator.
        format: Image format (png, svg, pdf).
        dpi: Image resolution.
        width: Chart width in inches.
        height: Chart height in inches.
        style: Matplotlib style sheet name.
        color_palette: Seaborn color palette name.
        include_trend_lines: Whether to add trend lines.
        include_error_bars: Whether to add error bars.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the chart generator.

        Args:
            config: Configuration dictionary. Expected keys: format, dpi,
                width, height, style, color_palette, include_trend_lines,
                include_error_bars.
        """
        self.name: str = "chart_generator"
        self.config: dict[str, Any] = config or {}

        self.format: str = self.config.get("format", "png")
        self.dpi: int = self.config.get("dpi", 150)
        self.width: int = self.config.get("width", 12)
        self.height: int = self.config.get("height", 8)
        self.style: str = self.config.get("style", "seaborn-v0_8")
        self.color_palette: str = self.config.get("color_palette", "viridis")
        self.include_trend_lines: bool = self.config.get("include_trend_lines", True)
        self.include_error_bars: bool = self.config.get("include_error_bars", True)

        # Import matplotlib/seaborn lazily
        self._mpl: Any = None
        self._sns: Any = None
        self._plt: Any = None

    def _import_plotting(self) -> None:
        """Import matplotlib and seaborn lazily."""
        if self._plt is not None:
            return
        try:
            import matplotlib as mpl
            mpl.use("Agg")  # Non-interactive backend
            import matplotlib.pyplot as plt
            import seaborn as sns

            self._mpl = mpl
            self._plt = plt
            self._sns = sns

            # Apply style
            try:
                plt.style.use(self.style)
            except Exception:
                plt.style.use("default")

            sns.set_palette(self.color_palette)
            sns.set_style("whitegrid")

        except ImportError as exc:
            logger.warning("Matplotlib/seaborn not available: %s", exc)
            raise

    def _save_figure(self, filepath: str) -> None:
        """Save the current figure to a file.

        Args:
            filepath: Path to save the figure.
        """
        if self._plt is None:
            return
        self._plt.tight_layout()
        self._plt.savefig(filepath, dpi=self.dpi, format=self.format,
                          bbox_inches="tight", facecolor="white")
        self._plt.close()
        logger.debug("Saved chart: %s", filepath)

    def _extract_metric(
        self, results: list[ResultDict], metric: str = "mean_ms"
    ) -> list[tuple[str, float, float]]:
        """Extract a metric with standard deviation from results.

        Args:
            results: List of benchmark result dictionaries.
            metric: Metric key to extract (e.g., 'mean_ms', 'mean_s').

        Returns:
            List of tuples (label, value, std).
        """
        data: list[tuple[str, float, float]] = []
        std_key = metric.replace("mean_", "std_") if "mean_" in metric else f"std_{metric}"

        for r in results:
            if "error" in r:
                continue
            label = str(r.get("size", r.get("batch_size", r.get("model", r.get("benchmark", "unknown")))))
            value = r.get(metric)
            std = r.get(std_key, 0)
            if isinstance(value, (int, float)):
                data.append((label, float(value), float(std) if isinstance(std, (int, float)) else 0.0))

        return data

    def plot_latency_comparison(
        self, results: list[ResultDict], filepath: str
    ) -> str:
        """Generate a latency comparison bar chart.

        Creates a grouped bar chart comparing latencies across different
        benchmark configurations.

        Args:
            results: List of benchmark result dictionaries.
            filepath: Path to save the chart image.

        Returns:
            Path to the saved chart image.
        """
        try:
            self._import_plotting()
        except ImportError:
            logger.warning("Cannot generate chart: plotting libraries not available")
            return filepath

        fig, ax = self._plt.subplots(figsize=(self.width, self.height))

        # Extract latency data
        data = self._extract_metric(results, "mean_ms")
        if not data:
            logger.warning("No latency data to plot")
            self._plt.close()
            return filepath

        labels = [d[0] for d in data]
        values = [d[1] for d in data]
        errors = [d[2] for d in data]

        x_pos = np.arange(len(labels))
        bars = ax.bar(x_pos, values, yerr=errors if self.include_error_bars else None,
                      capsize=5, alpha=0.8, color=self._sns.color_palette(self.color_palette, len(labels)))

        ax.set_xlabel("Configuration")
        ax.set_ylabel("Latency (ms)")
        ax.set_title("Latency Comparison")
        ax.set_xticks(x_pos)
        ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.grid(True, alpha=0.3)

        # Add value labels on bars
        for bar, val in zip(bars, values):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                        f"{val:.1f}", ha="center", va="bottom", fontsize=8)

        self._save_figure(filepath)
        return filepath

    def plot_throughput(
        self, results: list[ResultDict], filepath: str
    ) -> str:
        """Generate a throughput bar chart.

        Args:
            results: List of benchmark result dictionaries.
            filepath: Path to save the chart image.

        Returns:
            Path to the saved chart image.
        """
        try:
            self._import_plotting()
        except ImportError:
            return filepath

        fig, ax = self._plt.subplots(figsize=(self.width, self.height))

        # Look for throughput metrics
        throughput_keys = ["requests_per_sec", "throughput_MBps", "gflops",
                           "queries_per_sec", "texts_per_sec", "samples_per_sec"]
        tp_key = None
        for key in throughput_keys:
            for r in results:
                if key in r and isinstance(r[key], (int, float)):
                    tp_key = key
                    break
            if tp_key:
                break

        if not tp_key:
            logger.warning("No throughput data found")
            self._plt.close()
            return filepath

        data = self._extract_metric(results, tp_key)
        if not data:
            logger.warning("No throughput data to plot")
            self._plt.close()
            return filepath

        labels = [d[0] for d in data]
        values = [d[1] for d in data]

        x_pos = np.arange(len(labels))
        ax.bar(x_pos, values, alpha=0.8,
               color=self._sns.color_palette(self.color_palette, len(labels)))

        ax.set_xlabel("Configuration")
        ax.set_ylabel(tp_key.replace("_", " ").title())
        ax.set_title("Throughput Comparison")
        ax.set_xticks(x_pos)
        ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.grid(True, alpha=0.3)

        self._save_figure(filepath)
        return filepath

    def plot_latency_distribution(
        self, results: list[ResultDict], filepath: str
    ) -> str:
        """Generate a latency distribution histogram.

        Creates a histogram showing the distribution of latency measurements.

        Args:
            results: List of benchmark result dictionaries.
            filepath: Path to save the chart image.

        Returns:
            Path to the saved chart image.
        """
        try:
            self._import_plotting()
        except ImportError:
            return filepath

        fig, ax = self._plt.subplots(figsize=(self.width, self.height))

        # Collect all raw times
        all_times: list[float] = []
        for r in results:
            raw = r.get("raw_times", [])
            if isinstance(raw, list) and raw:
                if isinstance(raw[0], (int, float)):
                    all_times.extend(raw)

        if not all_times:
            logger.warning("No raw time data for distribution")
            self._plt.close()
            return filepath

        # Convert to ms
        # Try to detect if times are in seconds or nanoseconds
        times_arr = np.array(all_times, dtype=np.float64)
        if np.median(times_arr) > 1:  # Likely nanoseconds
            times_ms = times_arr / 1e6
            unit = "ms"
        elif np.median(times_arr) > 0.001:  # Likely seconds
            times_ms = times_arr * 1000
            unit = "ms"
        else:
            times_ms = times_arr
            unit = "s"

        # Remove outliers for better visualization
        q99 = np.percentile(times_ms, 99)
        times_filtered = times_ms[times_ms <= q99]

        ax.hist(times_filtered, bins=50, alpha=0.7, density=True,
                color=self._sns.color_palette(self.color_palette)[0],
                edgecolor="white")

        # Add KDE
        try:
            self._sns.kdeplot(times_filtered, ax=ax, color="red", linewidth=2)
        except Exception:
            pass

        # Add statistics lines
        mean_val = float(np.mean(times_filtered))
        median_val = float(np.median(times_filtered))
        ax.axvline(mean_val, color="red", linestyle="--", linewidth=2, label=f"Mean: {mean_val:.3f}{unit}")
        ax.axvline(median_val, color="green", linestyle="--", linewidth=2, label=f"Median: {median_val:.3f}{unit}")

        ax.set_xlabel(f"Latency ({unit})")
        ax.set_ylabel("Density")
        ax.set_title("Latency Distribution")
        ax.legend()
        ax.grid(True, alpha=0.3)

        self._save_figure(filepath)
        return filepath

    def plot_performance_trend(
        self, results: list[ResultDict], filepath: str
    ) -> str:
        """Generate a performance trend line chart.

        Shows how performance scales with a parameter (size, batch, etc.).

        Args:
            results: List of benchmark result dictionaries.
            filepath: Path to save the chart image.

        Returns:
            Path to the saved chart image.
        """
        try:
            self._import_plotting()
        except ImportError:
            return filepath

        fig, ax = self._plt.subplots(figsize=(self.width, self.height))

        # Find a scaling parameter
        scale_params = ["size", "batch_size", "dataset_size", "message_size",
                        "buffer_size_bytes", "sequence_length", "num_threads"]
        scale_key = None
        for key in scale_params:
            for r in results:
                if key in r and isinstance(r[key], (int, float)):
                    scale_key = key
                    break
            if scale_key:
                break

        if not scale_key:
            logger.warning("No scaling parameter found for trend chart")
            self._plt.close()
            return filepath

        # Group by benchmark name for multiple lines
        grouped: dict[str, list[tuple[float, float]]] = {}
        for r in results:
            if "error" in r:
                continue
            bname = str(r.get("benchmark", r.get("model", r.get("sdk", "unknown"))))
            x_val = r.get(scale_key)
            y_val = r.get("mean_ms", r.get("mean_s", r.get("mean_ns", None)))
            if isinstance(x_val, (int, float)) and isinstance(y_val, (int, float)):
                if bname not in grouped:
                    grouped[bname] = []
                grouped[bname].append((float(x_val), float(y_val)))

        if not grouped:
            logger.warning("No trend data to plot")
            self._plt.close()
            return filepath

        colors = self._sns.color_palette(self.color_palette, len(grouped))
        for (bname, points), color in zip(grouped.items(), colors):
            points.sort(key=lambda p: p[0])
            x_vals = [p[0] for p in points]
            y_vals = [p[1] for p in points]

            ax.plot(x_vals, y_vals, marker="o", linewidth=2, label=bname, color=color)

            # Add trend line
            if self.include_trend_lines and len(x_vals) > 2:
                try:
                    z = np.polyfit(x_vals, y_vals, 2)
                    p = np.poly1d(z)
                    x_smooth = np.linspace(min(x_vals), max(x_vals), 100)
                    ax.plot(x_smooth, p(x_smooth), linestyle="--", alpha=0.5, color=color)
                except Exception:
                    pass

        ax.set_xlabel(scale_key.replace("_", " ").title())
        ax.set_ylabel("Latency")
        ax.set_title(f"Performance Scaling by {scale_key.replace('_', ' ').title()}")
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.set_xscale("log", base=2)

        self._save_figure(filepath)
        return filepath

    def plot_correlation_heatmap(
        self, results: list[ResultDict], filepath: str
    ) -> str:
        """Generate a correlation heatmap of benchmark metrics.

        Args:
            results: List of benchmark result dictionaries.
            filepath: Path to save the chart image.

        Returns:
            Path to the saved chart image.
        """
        try:
            self._import_plotting()
        except ImportError:
            return filepath

        # Extract numeric metrics
        metric_keys = ["mean_ms", "median_ms", "std_ms", "min_ms", "max_ms",
                       "p50_ms", "p90_ms", "p95_ms", "p99_ms",
                       "mean_s", "mean_ns", "requests_per_sec", "throughput_MBps",
                       "gflops", "bandwidth_GBs", "rss_MB", "vms_MB"]

        data_dict: dict[str, list[float]] = {k: [] for k in metric_keys}

        for r in results:
            for key in metric_keys:
                val = r.get(key)
                if isinstance(val, (int, float)):
                    data_dict[key].append(float(val))

        # Filter to keys with sufficient data
        valid_keys = [k for k, v in data_dict.items() if len(v) >= 5]
        if len(valid_keys) < 2:
            logger.warning("Insufficient data for correlation heatmap")
            self._plt.close()
            return filepath

        # Build correlation matrix
        matrix_data = np.array([data_dict[k][:min(len(v) for v in data_dict.values() if len(v) >= 5)]
                                for k in valid_keys])
        if matrix_data.size == 0:
            self._plt.close()
            return filepath

        try:
            corr_matrix = np.corrcoef(matrix_data)
        except Exception:
            logger.warning("Failed to compute correlation matrix")
            self._plt.close()
            return filepath

        fig, ax = self._plt.subplots(figsize=(self.width, self.height))

        # Create heatmap
        mask = np.triu(np.ones_like(corr_matrix, dtype=bool))
        self._sns.heatmap(corr_matrix, mask=mask, annot=True, fmt=".2f",
                          xticklabels=valid_keys, yticklabels=valid_keys,
                          cmap=self.color_palette, center=0, square=True,
                          linewidths=0.5, ax=ax)

        ax.set_title("Metric Correlation Heatmap")
        self._plt.xticks(rotation=45, ha="right")

        self._save_figure(filepath)
        return filepath

    def plot_radar_comparison(
        self, results: list[ResultDict], filepath: str
    ) -> str:
        """Generate a radar chart for multi-dimensional comparison.

        Useful for comparing multiple SDKs or models across several metrics.

        Args:
            results: List of benchmark result dictionaries.
            filepath: Path to save the chart image.

        Returns:
            Path to the saved chart image.
        """
        try:
            self._import_plotting()
        except ImportError:
            return filepath

        # Find groups and metrics
        group_key = "sdk" if any("sdk" in r for r in results) else "model"
        groups = list(set(str(r.get(group_key, "unknown")) for r in results if group_key in r))
        groups = [g for g in groups if g != "unknown"]

        if len(groups) < 2:
            logger.warning("Need at least 2 groups for radar chart")
            self._plt.close()
            return filepath

        # Define metrics for radar
        radar_metrics = ["mean_ms", "p50_ms", "p90_ms", "p99_ms", "std_ms"]
        available_metrics = [m for m in radar_metrics
                            if any(m in r and isinstance(r[m], (int, float)) for r in results)]

        if len(available_metrics) < 3:
            logger.warning("Need at least 3 metrics for radar chart")
            self._plt.close()
            return filepath

        # Normalize metrics per group
        metric_values: dict[str, list[float]] = {g: [] for g in groups}
        for metric in available_metrics:
            vals = [r.get(metric, 0) for r in results if r.get(group_key) in groups
                    and isinstance(r.get(metric), (int, float))]
            if not vals:
                continue
            max_val = max(vals) if max(vals) > 0 else 1.0
            for g in groups:
                g_vals = [r.get(metric, 0) for r in results if r.get(group_key) == g
                         and isinstance(r.get(metric), (int, float))]
                avg_val = float(np.mean(g_vals)) if g_vals else 0
                metric_values[g].append(avg_val / max_val * 100)  # Normalize to 0-100

        # Create radar chart
        n_metrics = len(available_metrics)
        angles = np.linspace(0, 2 * np.pi, n_metrics, endpoint=False).tolist()
        angles += angles[:1]  # Close the polygon

        fig, ax = self._plt.subplots(figsize=(self.width, self.height), subplot_kw={"projection": "polar"})

        colors = self._sns.color_palette(self.color_palette, len(groups))
        for g, color in zip(groups, colors):
            values = metric_values.get(g, [0] * n_metrics)
            values += values[:1]  # Close the polygon
            ax.plot(angles, values, "o-", linewidth=2, label=g, color=color)
            ax.fill(angles, values, alpha=0.1, color=color)

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(available_metrics)
        ax.set_title("Multi-dimensional Performance Comparison")
        ax.legend(loc="upper right")

        self._save_figure(filepath)
        return filepath

    def get_info(self) -> dict[str, Any]:
        """Return metadata about this chart generator configuration.

        Returns:
            Dictionary with chart generator metadata.
        """
        return {
            "name": self.name,
            "description": "Benchmark result chart generation",
            "format": self.format,
            "dpi": self.dpi,
            "width": self.width,
            "height": self.height,
            "style": self.style,
            "color_palette": self.color_palette,
            "include_trend_lines": self.include_trend_lines,
            "include_error_bars": self.include_error_bars,
        }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate benchmark charts")
    parser.add_argument("--input", "-i", required=True, help="Input JSON results file")
    parser.add_argument("--output", "-o", default="reports/output/charts", help="Output directory")
    args = parser.parse_args()

    import json as std_json
    with open(args.input) as f:
        results = std_json.load(f)

    os.makedirs(args.output, exist_ok=True)
    gen = ChartGenerator()

    # Generate all chart types
    gen.plot_latency_comparison(results, os.path.join(args.output, "latency_comparison.png"))
    gen.plot_throughput(results, os.path.join(args.output, "throughput.png"))
    gen.plot_latency_distribution(results, os.path.join(args.output, "latency_distribution.png"))
    gen.plot_performance_trend(results, os.path.join(args.output, "performance_trend.png"))
    gen.plot_correlation_heatmap(results, os.path.join(args.output, "correlation_heatmap.png"))
    print(f"Charts generated in: {args.output}")