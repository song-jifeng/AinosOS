#!/usr/bin/env python3
"""
AinosOS AI Profiler
====================
AI-powered performance profiler with benchmarking, statistical analysis,
flame graph generation, and comprehensive report capabilities.

Subcommands:
    benchmark   Run performance benchmarks
    profile     Profile a running process or script
    compare     Compare benchmark results (before/after)
    report      Generate performance reports from existing data
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import textwrap
import time
import subprocess
import tempfile
import statistics
import hashlib
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import (
    Any, Callable, Dict, Generator, List, Optional,
    Sequence, Set, Tuple, Type, Union,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "1.0.0"
APP_NAME = "ai-profiler"

DEFAULT_WARMUP = 1
DEFAULT_ITERATIONS = 10
DEFAULT_TIMEOUT = 60

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkResult:
    """Results from a single benchmark run."""
    name: str
    iterations: int = 0
    warmup_iterations: int = 0
    timings: List[float] = field(default_factory=list)
    memory_samples: List[int] = field(default_factory=list)
    cpu_samples: List[float] = field(default_factory=list)
    throughput: float = 0.0
    start_time: float = 0.0
    end_time: float = 0.0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def min_time(self) -> float:
        return min(self.timings) if self.timings else 0.0

    @property
    def max_time(self) -> float:
        return max(self.timings) if self.timings else 0.0

    @property
    def avg_time(self) -> float:
        return statistics.mean(self.timings) if self.timings else 0.0

    @property
    def median_time(self) -> float:
        return statistics.median(self.timings) if self.timings else 0.0

    @property
    def stdev_time(self) -> float:
        return statistics.stdev(self.timings) if len(self.timings) >= 2 else 0.0

    @property
    def p95_time(self) -> float:
        if not self.timings:
            return 0.0
        sorted_t = sorted(self.timings)
        idx = max(0, min(len(sorted_t) - 1, int(len(sorted_t) * 0.95)))
        return sorted_t[idx]

    @property
    def p99_time(self) -> float:
        if not self.timings:
            return 0.0
        sorted_t = sorted(self.timings)
        idx = max(0, min(len(sorted_t) - 1, int(len(sorted_t) * 0.99)))
        return sorted_t[idx]

    @property
    def total_time(self) -> float:
        return self.end_time - self.start_time if self.end_time > self.start_time else 0.0

    @property
    def ops_per_sec(self) -> float:
        avg = self.avg_time
        return 1.0 / avg if avg > 0 else 0.0

    @property
    def formatted_timings(self) -> str:
        if not self.timings:
            return "N/A"
        t = self.timings
        return (f"min={min(t):.4f}s, max={max(t):.4f}s, "
                f"avg={statistics.mean(t):.4f}s, "
                f"median={statistics.median(t):.4f}s, "
                f"p95={self.p95_time:.4f}s, p99={self.p99_time:.4f}s, "
                f"stdev={self.stdev_time:.4f}s")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "iterations": self.iterations,
            "timings": self.timings,
            "min_time": self.min_time,
            "max_time": self.max_time,
            "avg_time": self.avg_time,
            "median_time": self.median_time,
            "stdev_time": self.stdev_time,
            "p95_time": self.p95_time,
            "p99_time": self.p99_time,
            "ops_per_sec": self.ops_per_sec,
            "total_time": self.total_time,
            "error": self.error,
        }


@dataclass
class BenchmarkSuite:
    """A collection of benchmark results."""
    name: str
    results: List[BenchmarkResult] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    system_info: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_result(self, result: BenchmarkResult) -> None:
        self.results.append(result)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "timestamp": self.timestamp,
            "system_info": self.system_info,
            "results": [r.to_dict() for r in self.results],
            "metadata": self.metadata,
        }


@dataclass
class ComparisonResult:
    """Comparison between two benchmark results."""
    name: str
    baseline: BenchmarkResult
    current: BenchmarkResult
    abs_change: float = 0.0
    rel_change: float = 0.0
    regression: bool = False
    significance: float = 0.0

    @property
    def change_str(self) -> str:
        sign = "+" if self.rel_change >= 0 else ""
        return f"{sign}{self.rel_change:.2f}%"

    @property
    def verdict(self) -> str:
        if abs(self.rel_change) < 1.0:
            return "NO_CHANGE"
        if self.rel_change > 5.0:
            return "REGRESSION"
        if self.rel_change < -5.0:
            return "IMPROVEMENT"
        return "MINOR_CHANGE"


@dataclass
class FlameGraphData:
    """Data for flame graph generation."""
    stacks: List[Tuple[List[str], int]] = field(default_factory=list)
    total_samples: int = 0
    title: str = "CPU Profile"


# ---------------------------------------------------------------------------
# Benchmark framework
# ---------------------------------------------------------------------------

class Benchmark:
    """A single benchmark definition."""

    def __init__(self, name: str, fn: Optional[Callable] = None,
                 setup: Optional[Callable] = None, teardown: Optional[Callable] = None,
                 iterations: int = DEFAULT_ITERATIONS,
                 warmup: int = DEFAULT_WARMUP,
                 timeout: int = DEFAULT_TIMEOUT) -> None:
        self.name = name
        self.fn = fn
        self.setup = setup
        self.teardown = teardown
        self.iterations = iterations
        self.warmup = warmup
        self.timeout = timeout
        self._args: Tuple = ()
        self._kwargs: Dict[str, Any] = {}

    def args(self, *args: Any, **kwargs: Any) -> "Benchmark":
        """Set arguments for the benchmark function."""
        self._args = args
        self._kwargs = kwargs
        return self

    def run(self) -> BenchmarkResult:
        """Run the benchmark and return results."""
        result = BenchmarkResult(name=self.name, iterations=self.iterations,
                                 warmup_iterations=self.warmup)
        result.start_time = time.time()

        try:
            # Setup
            setup_result = None
            if self.setup:
                setup_result = self.setup()

            # Warmup
            for _ in range(self.warmup):
                if self.fn:
                    if setup_result is not None:
                        self.fn(setup_result, *self._args, **self._kwargs)
                    else:
                        self.fn(*self._args, **self._kwargs)

            # Timed iterations
            for _ in range(self.iterations):
                t0 = time.perf_counter()
                if self.fn:
                    if setup_result is not None:
                        self.fn(setup_result, *self._args, **self._kwargs)
                    else:
                        self.fn(*self._args, **self._kwargs)
                elapsed = time.perf_counter() - t0
                result.timings.append(elapsed)

            # Teardown
            if self.teardown:
                self.teardown()

            result.end_time = time.time()

        except Exception as e:
            result.error = str(e)
            result.end_time = time.time()

        return result

    def run_async(self) -> BenchmarkResult:
        """Run async benchmark (simplified - runs in current event loop)."""
        result = BenchmarkResult(name=self.name, iterations=self.iterations,
                                 warmup_iterations=self.warmup)
        result.start_time = time.time()

        try:
            import asyncio

            setup_result = None
            if self.setup:
                if asyncio.iscoroutinefunction(self.setup):
                    setup_result = asyncio.run(self.setup())
                else:
                    setup_result = self.setup()

            fn = self.fn
            if fn and asyncio.iscoroutinefunction(fn):
                async def run_iter():
                    if setup_result is not None:
                        await fn(setup_result, *self._args, **self._kwargs)
                    else:
                        await fn(*self._args, **self._kwargs)

                for _ in range(self.warmup):
                    asyncio.run(run_iter())

                for _ in range(self.iterations):
                    t0 = time.perf_counter()
                    asyncio.run(run_iter())
                    elapsed = time.perf_counter() - t0
                    result.timings.append(elapsed)
            else:
                # Fallback to sync
                for _ in range(self.iterations):
                    t0 = time.perf_counter()
                    if fn:
                        fn(*self._args, **self._kwargs)
                    elapsed = time.perf_counter() - t0
                    result.timings.append(elapsed)

            result.end_time = time.time()

        except Exception as e:
            result.error = str(e)
            result.end_time = time.time()

        return result


class BenchmarkRunner:
    """Run benchmarks and collect results."""

    def __init__(self) -> None:
        self.benchmarks: List[Benchmark] = []
        self.suite = BenchmarkSuite(name="benchmark_suite")

    def add(self, benchmark: Benchmark) -> None:
        """Add a benchmark to the runner."""
        self.benchmarks.append(benchmark)

    def add_function(self, name: str, fn: Callable, *args: Any,
                     iterations: int = DEFAULT_ITERATIONS,
                     warmup: int = DEFAULT_WARMUP, **kwargs: Any) -> None:
        """Add a function as a benchmark."""
        bench = Benchmark(name, fn, iterations=iterations, warmup=warmup)
        bench.args(*args, **kwargs)
        self.benchmarks.append(bench)

    def run_all(self, progress: bool = True) -> BenchmarkSuite:
        """Run all benchmarks."""
        total = len(self.benchmarks)
        for i, bench in enumerate(self.benchmarks):
            if progress:
                print(f"  [{i + 1}/{total}] {bench.name}...", file=sys.stderr)
            result = bench.run()
            self.suite.add_result(result)
            if progress and not result.error:
                print(f"    {result.formatted_timings}", file=sys.stderr)
            elif progress and result.error:
                print(f"    ERROR: {result.error}", file=sys.stderr)

        # Collect system info
        self.suite.system_info = self._get_system_info()
        return self.suite

    def _get_system_info(self) -> Dict[str, Any]:
        """Collect system information."""
        info: Dict[str, Any] = {
            "platform": sys.platform,
            "python_version": sys.version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            import platform
            info["processor"] = platform.processor()
            info["machine"] = platform.machine()
            info["cpu_count"] = os.cpu_count()
        except Exception:
            pass
        return info


# ---------------------------------------------------------------------------
# Statistical analysis
# ---------------------------------------------------------------------------

class StatisticalAnalyzer:
    """Statistical analysis of benchmark results."""

    @staticmethod
    def analyze(result: BenchmarkResult) -> Dict[str, Any]:
        """Perform statistical analysis on a benchmark result."""
        if not result.timings:
            return {"error": "No timings data"}

        timings = sorted(result.timings)
        n = len(timings)

        analysis: Dict[str, Any] = {
            "count": n,
            "min": min(timings),
            "max": max(timings),
            "mean": statistics.mean(timings),
            "median": statistics.median(timings),
            "stdev": statistics.stdev(timings) if n >= 2 else 0.0,
            "variance": statistics.variance(timings) if n >= 2 else 0.0,
        }

        # Percentiles
        for pct in [50, 75, 90, 95, 99, 99.9]:
            idx = max(0, min(n - 1, int(n * pct / 100)))
            analysis[f"p{pct}"] = timings[idx]

        # Quartiles
        q1_idx = max(0, min(n - 1, int(n * 0.25)))
        q3_idx = max(0, min(n - 1, int(n * 0.75)))
        analysis["q1"] = timings[q1_idx]
        analysis["q3"] = timings[q3_idx]
        analysis["iqr"] = timings[q3_idx] - timings[q1_idx]

        # Outlier detection (IQR method)
        iqr = analysis["q3"] - analysis["q1"]
        lower_fence = analysis["q1"] - 1.5 * iqr
        upper_fence = analysis["q3"] + 1.5 * iqr
        outliers = [t for t in timings if t < lower_fence or t > upper_fence]
        analysis["outlier_count"] = len(outliers)
        analysis["outlier_ratio"] = len(outliers) / n if n > 0 else 0.0

        # Coefficient of variation
        mean = analysis["mean"]
        analysis["cv"] = analysis["stdev"] / mean if mean > 0 else 0.0

        # Throughput
        analysis["ops_per_sec"] = 1.0 / mean if mean > 0 else 0.0

        # Confidence interval (95%)
        if n >= 2:
            import math
            z = 1.96  # 95% confidence
            se = analysis["stdev"] / math.sqrt(n)
            analysis["ci_95_lower"] = mean - z * se
            analysis["ci_95_upper"] = mean + z * se
            analysis["ci_95_range"] = analysis["ci_95_upper"] - analysis["ci_95_lower"]
            analysis["relative_error"] = (analysis["ci_95_range"] / 2) / mean * 100 if mean > 0 else 0.0

        return analysis

    @staticmethod
    def compare(baseline: BenchmarkResult, current: BenchmarkResult) -> ComparisonResult:
        """Compare two benchmark results."""
        b_avg = baseline.avg_time
        c_avg = current.avg_time

        abs_change = c_avg - b_avg
        rel_change = ((c_avg - b_avg) / b_avg * 100) if b_avg > 0 else 0.0

        # Statistical significance (simplified t-test)
        significance = 0.0
        if len(baseline.timings) >= 2 and len(current.timings) >= 2:
            b_var = statistics.variance(baseline.timings) / len(baseline.timings)
            c_var = statistics.variance(current.timings) / len(current.timings)
            se = math.sqrt(b_var + c_var)
            if se > 0:
                t_stat = abs_change / se
                significance = min(1.0, abs(t_stat) / 3.0)  # Normalized

        result = ComparisonResult(
            name=baseline.name,
            baseline=baseline,
            current=current,
            abs_change=abs_change,
            rel_change=rel_change,
            regression=rel_change > 1.0,
            significance=significance,
        )
        return result

    @staticmethod
    def compare_suites(baseline: BenchmarkSuite, current: BenchmarkSuite) -> List[ComparisonResult]:
        """Compare all benchmarks in two suites."""
        comparisons: List[ComparisonResult] = []
        b_map = {r.name: r for r in baseline.results}
        c_map = {r.name: r for r in current.results}

        all_names = set(b_map) | set(c_map)
        for name in sorted(all_names):
            b = b_map.get(name)
            c = c_map.get(name)
            if b and c:
                comparisons.append(StatisticalAnalyzer.compare(b, c))
            elif b:
                comparisons.append(ComparisonResult(
                    name=name, baseline=b, current=BenchmarkResult(name=name),
                    abs_change=float('inf'), rel_change=float('inf'),
                ))
            elif c:
                comparisons.append(ComparisonResult(
                    name=name, baseline=BenchmarkResult(name=name), current=c,
                    abs_change=float('inf'), rel_change=float('inf'),
                ))

        return comparisons


# ---------------------------------------------------------------------------
# External profiler wrappers
# ---------------------------------------------------------------------------

class Profiler:
    """Run external profilers (cProfile, perf, etc.)."""

    @staticmethod
    def run_cprofile(script_path: str, output_path: str,
                     args: Optional[List[str]] = None) -> Dict[str, Any]:
        """Run cProfile on a Python script."""
        cmd = [sys.executable, "-m", "cProfile", "-o", output_path, script_path]
        if args:
            cmd.extend(args)

        start = time.time()
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=DEFAULT_TIMEOUT)
            duration = time.time() - start
            return {
                "success": result.returncode == 0,
                "duration": duration,
                "output_file": output_path,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Timed out"}
        except FileNotFoundError:
            return {"success": False, "error": "Python not found"}

    @staticmethod
    def run_perf(script_path: str, output_path: str,
                 event: str = "cpu-clock") -> Dict[str, Any]:
        """Run perf on a script (Linux only)."""
        if sys.platform != "linux":
            return {"success": False, "error": "perf is only available on Linux"}

        cmd = [
            "perf", "record",
            "-e", event,
            "-o", output_path,
            "--", sys.executable, script_path,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=DEFAULT_TIMEOUT)
            return {
                "success": result.returncode == 0,
                "output_file": output_path,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Timed out"}
        except FileNotFoundError:
            return {"success": False, "error": "perf not found"}

    @staticmethod
    def parse_cprofile_stats(stats_file: str) -> FlameGraphData:
        """Parse cProfile stats into flame graph data."""
        try:
            import pstats
        except ImportError:
            return FlameGraphData()

        try:
            p = pstats.Stats(stats_file)
            # Convert to stack format
            stacks: List[Tuple[List[str], int]] = []
            for func, (cc, nc, tt, ct, callers) in p.stats.items():
                filename, lineno, func_name = func
                stack = [f"{func_name} ({filename}:{lineno})"]
                for caller in callers:
                    c_filename, c_lineno, c_func = caller
                    stack.append(f"{c_func} ({c_filename}:{c_lineno})")
                stacks.append((stack, int(tt * 1000)))  # Convert to ms

            total = sum(s[1] for s in stacks)
            return FlameGraphData(stacks=stacks, total_samples=total)
        except Exception:
            return FlameGraphData()


# ---------------------------------------------------------------------------
# Flame graph generation
# ---------------------------------------------------------------------------

class FlameGraphGenerator:
    """Generate flame graph SVG from stack data."""

    SVG_WIDTH = 1200
    SVG_HEIGHT = 800
    FRAME_HEIGHT = 16
    FONT_SIZE = 12
    PAD_TOP = 30
    PAD_BOTTOM = 10
    PAD_LEFT = 10
    PAD_RIGHT = 10

    def generate(self, data: FlameGraphData, output_path: str,
                 title: Optional[str] = None) -> str:
        """Generate a flame graph SVG file."""
        if not data.stacks:
            return self._empty_svg(output_path, title or "Flame Graph")

        # Build tree
        tree = self._build_tree(data.stacks)
        total = tree["count"]

        # Assign layout
        self._layout(tree, 0, self.SVG_WIDTH - self.PAD_LEFT - self.PAD_RIGHT, total)

        # Generate SVG
        svg = self._render_svg(tree, total, title or data.title)
        Path(output_path).write_text(svg, encoding="utf-8")
        return svg

    def _build_tree(self, stacks: List[Tuple[List[str], int]]) -> Dict[str, Any]:
        """Build a tree from stack data."""
        root: Dict[str, Any] = {"name": "root", "count": 0, "children": {}, "depth": 0}

        for stack, count in stacks:
            node = root
            node["count"] += count
            for frame in reversed(stack):  # root first
                if frame not in node["children"]:
                    node["children"][frame] = {
                        "name": frame, "count": 0, "children": {}, "depth": node["depth"] + 1
                    }
                node = node["children"][frame]
                node["count"] += count

        return root

    def _layout(self, node: Dict[str, Any], x_start: float, width: float,
                total: int, depth: int = 0) -> None:
        """Assign x-positions and widths to nodes."""
        node["x"] = x_start
        node["width"] = width * node["count"] / max(total, 1) if total > 0 else 0
        node["depth"] = depth

        children = list(node["children"].values())
        if not children:
            return

        children.sort(key=lambda c: c["count"], reverse=True)
        child_x = x_start
        for child in children:
            child_width = width * child["count"] / max(total, 1)
            self._layout(child, child_x, child_width, total, depth + 1)
            child_x += child_width

    def _render_svg(self, root: Dict[str, Any], total: int, title: str) -> str:
        """Render the tree as an SVG."""
        lines: List[str] = []
        w = self.SVG_WIDTH
        h = self.SVG_HEIGHT

        lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"')
        lines.append(f'     viewBox="0 0 {w} {h}" style="background:#fff">')
        lines.append(f'<style>')
        lines.append(f'  text {{ font-family: monospace; font-size: {self.FONT_SIZE}px; }}')
        lines.append(f'  .frame:hover {{ stroke: #000; stroke-width: 1.5; }}')
        lines.append(f'  .title {{ font-weight: bold; font-size: 14px; }}')
        lines.append(f'</style>')

        # Title
        lines.append(f'<text x="{w // 2}" y="20" text-anchor="middle" class="title">'
                     f'{self._escape(title)}</text>')
        lines.append(f'<text x="{self.PAD_LEFT}" y="20" font-size="11" fill="#666">'
                     f'Total: {total:,} samples</text>')

        # Collect all nodes
        nodes: List[Dict[str, Any]] = []
        self._collect_nodes(root, nodes)

        # Draw frames
        y_start = self.PAD_TOP + 10
        for node in nodes:
            if node["depth"] == 0:
                continue
            x = self.PAD_LEFT + node["x"]
            y = y_start + node["depth"] * self.FRAME_HEIGHT
            nw = node["width"]
            if nw < 1:
                continue

            # Color based on name hash
            color = self._name_color(node["name"])
            count = node["count"]
            pct = count / total * 100 if total > 0 else 0

            lines.append(f'<g class="frame" onmouseover="showTip(\'{self._escape(node["name"])}\','
                         f'{count},{pct:.1f})" onmouseout="hideTip()">')
            lines.append(f'  <rect x="{x:.1f}" y="{y}" width="{nw:.1f}" '
                         f'height="{self.FRAME_HEIGHT}" fill="{color}" rx="1" ry="1"/>')
            if nw > self.FONT_SIZE * 0.6 * 3:
                max_chars = max(1, int(nw / (self.FONT_SIZE * 0.6)))
                label = node["name"][:max_chars]
                if len(node["name"]) > max_chars:
                    label = label[:-2] + ".."
                lines.append(f'  <text x="{x + 3:.1f}" y="{y + self.FRAME_HEIGHT - 4}" '
                             f'font-size="{self.FONT_SIZE}">{self._escape(label)}</text>')
            lines.append(f'</g>')

        # Tooltip
        lines.append(f'<g id="tooltip" style="display:none">')
        lines.append(f'  <rect x="0" y="0" width="10" height="10" fill="#222" rx="2" ry="2"/>')
        lines.append(f'  <text id="tip-text" x="5" y="13" fill="#fff" font-size="11"></text>')
        lines.append(f'</g>')

        # JavaScript
        lines.append(f'<script type="text/javascript"><![CDATA[')
        lines.append(f'function showTip(name, count, pct) {{')
        lines.append(f'  var tip = document.getElementById("tooltip");')
        lines.append(f'  var txt = document.getElementById("tip-text");')
        lines.append(f'  txt.textContent = name + " — " + count + " (" + pct.toFixed(1) + "%)";')
        lines.append(f'  var bbox = txt.getBBox();')
        lines.append(f'  var bg = tip.querySelector("rect");')
        lines.append(f'  bg.setAttribute("width", bbox.width + 16);')
        lines.append(f'  bg.setAttribute("height", bbox.height + 8);')
        lines.append(f'  tip.style.display = "block";')
        lines.append(f'}}')
        lines.append(f'function hideTip() {{')
        lines.append(f'  document.getElementById("tooltip").style.display = "none";')
        lines.append(f'}}')
        lines.append(f']]></script>')

        lines.append(f'</svg>')
        return "\n".join(lines)

    def _empty_svg(self, output_path: str, title: str) -> str:
        """Generate an empty flame graph SVG."""
        w = self.SVG_WIDTH
        h = self.SVG_HEIGHT
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" style="background:#fff">\n'
            f'<text x="{w//2}" y="{h//2}" text-anchor="middle" fill="#999" '
            f'font-size="16" font-family="monospace">No profile data</text>\n'
            f'</svg>'
        )
        Path(output_path).write_text(svg, encoding="utf-8")
        return svg

    def _collect_nodes(self, node: Dict[str, Any], nodes: List[Dict[str, Any]]) -> None:
        """Collect all nodes into a flat list."""
        nodes.append(node)
        for child in node["children"].values():
            self._collect_nodes(child, nodes)

    def _name_color(self, name: str) -> str:
        """Generate a deterministic color for a function name."""
        h = int(hashlib.md5(name.encode()).hexdigest()[:8], 16)
        hue = (h % 30) + (h // 7 % 30)
        sat = 50 + (h // 3 % 30)
        val = 75 + (h // 11 % 20)
        r, g, b = self._hsv_to_rgb(hue, sat / 100.0, val / 100.0)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _hsv_to_rgb(self, h: float, s: float, v: float) -> Tuple[int, int, int]:
        h = h % 360.0
        c = v * s
        x = c * (1 - abs((h / 60.0) % 2 - 1))
        m = v - c
        if h < 60:
            r, g, b = c, x, 0.0
        elif h < 120:
            r, g, b = x, c, 0.0
        elif h < 180:
            r, g, b = 0.0, c, x
        elif h < 240:
            r, g, b = 0.0, x, c
        elif h < 300:
            r, g, b = x, 0.0, c
        else:
            r, g, b = c, 0.0, x
        return (int((r + m) * 255), int((g + m) * 255), int((b + m) * 255))

    def _escape(self, s: str) -> str:
        s = s.replace("&", "&amp;")
        s = s.replace("<", "&lt;")
        s = s.replace(">", "&gt;")
        s = s.replace('"', "&quot;")
        s = s.replace("'", "&#39;")
        return s


# ---------------------------------------------------------------------------
# Report generators
# ---------------------------------------------------------------------------

class MarkdownProfilerReport:
    """Generate Markdown profiler reports."""

    @staticmethod
    def generate_benchmark(suite: BenchmarkSuite) -> str:
        """Generate a benchmark report in Markdown."""
        lines: List[str] = []
        lines.append(f"# Benchmark Report: {suite.name}")
        lines.append("")
        lines.append(f"**Timestamp:** {suite.timestamp}")
        lines.append(f"**Platform:** {suite.system_info.get('platform', 'N/A')}")
        lines.append(f"**Python:** {suite.system_info.get('python_version', 'N/A')[:50]}")
        lines.append(f"**CPU Count:** {suite.system_info.get('cpu_count', 'N/A')}")
        lines.append("")

        lines.append("## Results")
        lines.append("")
        lines.append("| Benchmark | Iterations | Avg (s) | Min (s) | Max (s) | Median (s) | P95 (s) | StdDev | Ops/s |")
        lines.append("|-----------|------------|---------|---------|---------|------------|---------|--------|-------|")

        for r in suite.results:
            if r.error:
                lines.append(f"| {r.name} | ERROR | {r.error} | | | | | | |")
            else:
                lines.append(
                    f"| {r.name} | {r.iterations} | {r.avg_time:.4f} | {r.min_time:.4f} | "
                    f"{r.max_time:.4f} | {r.median_time:.4f} | {r.p95_time:.4f} | "
                    f"{r.stdev_time:.4f} | {r.ops_per_sec:.1f} |"
                )

        lines.append("")

        # Detailed analysis
        lines.append("## Statistical Analysis")
        lines.append("")
        for r in suite.results:
            if r.error:
                continue
            analysis = StatisticalAnalyzer.analyze(r)
            lines.append(f"### {r.name}")
            lines.append("")
            lines.append(f"- **Count:** {analysis['count']}")
            lines.append(f"- **Mean:** {analysis['mean']:.4f}s")
            lines.append(f"- **Median:** {analysis['median']:.4f}s")
            lines.append(f"- **StdDev:** {analysis['stdev']:.4f}s ({analysis['cv']*100:.1f}% CV)")
            lines.append(f"- **Min:** {analysis['min']:.4f}s, **Max:** {analysis['max']:.4f}s")
            lines.append(f"- **P50:** {analysis['p50']:.4f}s, **P90:** {analysis['p90']:.4f}s, "
                        f"**P95:** {analysis['p95']:.4f}s, **P99:** {analysis['p99']:.4f}s")
            lines.append(f"- **Q1:** {analysis['q1']:.4f}s, **Q3:** {analysis['q3']:.4f}s, "
                        f"**IQR:** {analysis['iqr']:.4f}s")
            lines.append(f"- **Outliers:** {analysis['outlier_count']} ({analysis['outlier_ratio']*100:.1f}%)")
            lines.append(f"- **Throughput:** {analysis['ops_per_sec']:.1f} ops/s")
            if 'ci_95_lower' in analysis:
                lines.append(f"- **95% CI:** [{analysis['ci_95_lower']:.4f}, {analysis['ci_95_upper']:.4f}] "
                            f"(±{analysis['relative_error']:.1f}%)")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def generate_comparison(comparisons: List[ComparisonResult]) -> str:
        """Generate a comparison report in Markdown."""
        lines: List[str] = []
        lines.append("# Benchmark Comparison Report")
        lines.append("")
        lines.append(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append("| Benchmark | Baseline (s) | Current (s) | Change | Verdict |")
        lines.append("|-----------|-------------|-------------|--------|---------|")

        regressions = 0
        improvements = 0
        for c in comparisons:
            if c.rel_change == float('inf'):
                continue
            lines.append(f"| {c.name} | {c.baseline.avg_time:.4f} | {c.current.avg_time:.4f} | "
                        f"{c.change_str} | {c.verdict} |")
            if c.verdict == "REGRESSION":
                regressions += 1
            elif c.verdict == "IMPROVEMENT":
                improvements += 1

        lines.append("")
        lines.append(f"**Regressions:** {regressions} | **Improvements:** {improvements}")
        lines.append("")

        # Detailed comparisons
        lines.append("## Detailed Comparison")
        lines.append("")
        for c in comparisons:
            if c.rel_change == float('inf'):
                continue
            lines.append(f"### {c.name}")
            lines.append("")
            lines.append(f"- **Baseline:** {c.baseline.avg_time:.4f}s (min={c.baseline.min_time:.4f}s, "
                        f"max={c.baseline.max_time:.4f}s)")
            lines.append(f"- **Current:** {c.current.avg_time:.4f}s (min={c.current.min_time:.4f}s, "
                        f"max={c.current.max_time:.4f}s)")
            lines.append(f"- **Absolute change:** {c.abs_change:+.4f}s")
            lines.append(f"- **Relative change:** {c.change_str}")
            lines.append(f"- **Verdict:** {c.verdict}")
            if c.significance > 0:
                lines.append(f"- **Significance:** {c.significance*100:.0f}%")
            lines.append("")

        return "\n".join(lines)


class HTMLProfilerReport:
    """Generate HTML profiler reports."""

    @staticmethod
    def generate_benchmark(suite: BenchmarkSuite) -> str:
        """Generate an HTML benchmark report."""
        md = MarkdownProfilerReport.generate_benchmark(suite)
        # Simple HTML wrapper
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Benchmark Report: {suite.name}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif;
           max-width: 960px; margin: 0 auto; padding: 20px; color: #333; }}
    h1 {{ border-bottom: 2px solid #4A90D9; padding-bottom: 8px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
    th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
    th {{ background: #f5f5f5; }}
    tr:nth-child(even) {{ background: #fafafa; }}
    .regression {{ color: #c0392b; }}
    .improvement {{ color: #27ae60; }}
    code {{ background: #f4f4f4; padding: 2px 5px; border-radius: 3px; }}
  </style>
</head>
<body>
  {self._md_to_html(md)}
</body>
</html>"""
        return html

    @staticmethod
    def _md_to_html(md: str) -> str:
        """Simple Markdown to HTML conversion."""
        html = ""
        for line in md.split("\n"):
            if line.startswith("# "):
                html += f"<h1>{line[2:]}</h1>\n"
            elif line.startswith("## "):
                html += f"<h2>{line[3:]}</h2>\n"
            elif line.startswith("### "):
                html += f"<h3>{line[4:]}</h3>\n"
            elif line.startswith("| "):
                if "---" not in line:
                    cells = [c.strip() for c in line.split("|")[1:-1]]
                    html += "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>\n"
            elif line.startswith("- "):
                html += f"<li>{line[2:]}</li>\n"
            elif line.strip():
                html += f"<p>{line}</p>\n"
        return html


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the main argument parser."""
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="AI-powered performance profiler and benchmark framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              %(prog)s benchmark -n 100 -w 5 my_benchmark.py     # Run benchmarks
              %(prog)s profile script.py -o profile.cprof         # Profile a script
              %(prog)s compare baseline.json current.json         # Compare results
              %(prog)s report results.json -f html -o report.html # Generate report
        """),
    )

    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # ------------------------------------------------------------------ #
    # benchmark subcommand
    # ------------------------------------------------------------------ #
    bench_parser = subparsers.add_parser("benchmark", help="Run benchmarks")
    bench_parser.add_argument("script", type=str, nargs="?", default="",
                              help="Python script containing benchmarks")
    bench_parser.add_argument("--output", "-o", type=str, default="",
                              help="Output file for results (JSON)")
    bench_parser.add_argument("--iterations", "-n", type=int, default=DEFAULT_ITERATIONS,
                              help=f"Number of iterations (default: {DEFAULT_ITERATIONS})")
    bench_parser.add_argument("--warmup", "-w", type=int, default=DEFAULT_WARMUP,
                              help=f"Warmup iterations (default: {DEFAULT_WARMUP})")
    bench_parser.add_argument("--format", "-f", choices=["text", "json", "markdown", "html"],
                              default="text", help="Output format (default: text)")
    bench_parser.add_argument("--flamegraph", type=str, default="",
                              help="Generate flame graph SVG to file")

    # ------------------------------------------------------------------ #
    # profile subcommand
    # ------------------------------------------------------------------ #
    profile_parser = subparsers.add_parser("profile", help="Profile a process or script")
    profile_parser.add_argument("target", type=str, help="Script or command to profile")
    profile_parser.add_argument("--output", "-o", type=str, default="profile.cprof",
                                help="Output file (default: profile.cprof)")
    profile_parser.add_argument("--profiler", choices=["cprofile", "perf"], default="cprofile",
                                help="Profiler to use (default: cprofile)")
    profile_parser.add_argument("--flamegraph", type=str, default="",
                                help="Generate flame graph SVG to file")
    profile_parser.add_argument("--event", type=str, default="cpu-clock",
                                help="Perf event (default: cpu-clock, Linux only)")

    # ------------------------------------------------------------------ #
    # compare subcommand
    # ------------------------------------------------------------------ #
    compare_parser = subparsers.add_parser("compare", help="Compare benchmark results")
    compare_parser.add_argument("baseline", type=str, help="Baseline results JSON file")
    compare_parser.add_argument("current", type=str, help="Current results JSON file")
    compare_parser.add_argument("--output", "-o", type=str, default="",
                                help="Output file")
    compare_parser.add_argument("--format", "-f", choices=["text", "markdown", "html", "json"],
                                default="text", help="Output format (default: text)")

    # ------------------------------------------------------------------ #
    # report subcommand
    # ------------------------------------------------------------------ #
    report_parser = subparsers.add_parser("report", help="Generate reports from data")
    report_parser.add_argument("input", type=str, help="Benchmark results JSON file")
    report_parser.add_argument("--output", "-o", type=str, default="",
                               help="Output file")
    report_parser.add_argument("--format", "-f", choices=["markdown", "html", "json"],
                               default="markdown", help="Output format (default: markdown)")

    return parser


def cmd_benchmark(args: argparse.Namespace) -> int:
    """Handle the 'benchmark' subcommand."""
    runner = BenchmarkRunner()

    if args.script:
        # Load benchmarks from a script
        script_path = args.script
        if not os.path.isfile(script_path):
            print(f"Error: Script not found: {script_path}", file=sys.stderr)
            return 1

        # Execute the script to get benchmark functions
        sys.path.insert(0, os.path.dirname(os.path.abspath(script_path)))
        script_globals: Dict[str, Any] = {}
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                code = f.read()
            exec(code, script_globals)
        except Exception as e:
            print(f"Error loading script: {e}", file=sys.stderr)
            return 1

        # Find benchmark functions
        for name, obj in script_globals.items():
            if callable(obj) and (name.startswith("bench_") or name.startswith("benchmark_")):
                runner.add_function(name, obj, iterations=args.iterations, warmup=args.warmup)
            elif isinstance(obj, Benchmark):
                obj.iterations = args.iterations
                obj.warmup = args.warmup
                runner.add(obj)

        if not runner.benchmarks:
            print(f"No benchmark functions found in {script_path}", file=sys.stderr)
            print("Benchmark functions should be named bench_* or benchmark_*", file=sys.stderr)
            return 1
    else:
        # Interactive mode - define a simple benchmark
        print("No script provided. Running in interactive mode.", file=sys.stderr)
        print("Define benchmark functions in a script and pass it as an argument.", file=sys.stderr)
        return 1

    print(f"Running {len(runner.benchmarks)} benchmarks ({args.iterations} iterations, "
          f"{args.warmup} warmup)...", file=sys.stderr)

    suite = runner.run_all(progress=True)

    # Save results
    if args.output:
        Path(args.output).write_text(
            json.dumps(suite.to_dict(), indent=2, default=str), encoding="utf-8"
        )
        if args.verbose:
            print(f"Results saved to {args.output}", file=sys.stderr)

    # Output
    if args.format == "json":
        print(json.dumps(suite.to_dict(), indent=2, default=str))
    elif args.format == "markdown":
        print(MarkdownProfilerReport.generate_benchmark(suite))
    elif args.format == "html":
        print(HTMLProfilerReport.generate_benchmark(suite))
    else:
        print(f"\nResults for: {suite.name}")
        print(f"Timestamp: {suite.timestamp}")
        print("")
        for r in suite.results:
            if r.error:
                print(f"  {r.name}: ERROR - {r.error}")
            else:
                print(f"  {r.name}: {r.formatted_timings}")
                print(f"    Throughput: {r.ops_per_sec:.1f} ops/s")

    # Flame graph
    if args.flamegraph:
        fg = FlameGraphGenerator()
        data = FlameGraphData(title=f"Benchmark: {suite.name}")
        fg.generate(data, args.flamegraph)
        if args.verbose:
            print(f"Flame graph saved to {args.flamegraph}", file=sys.stderr)

    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    """Handle the 'profile' subcommand."""
    target = args.target
    output = args.output

    if not os.path.isfile(target) and not target.endswith(".py"):
        print(f"Error: File not found: {target}", file=sys.stderr)
        return 1

    if args.profiler == "cprofile":
        if args.verbose:
            print(f"Profiling {target} with cProfile...", file=sys.stderr)
        result = Profiler.run_cprofile(target, output)
        if not result.get("success"):
            print(f"Profiling failed: {result.get('error', 'unknown error')}", file=sys.stderr)
            return 1
        if args.verbose:
            print(f"Profile saved to {output}", file=sys.stderr)

        # Flame graph
        if args.flamegraph:
            if args.verbose:
                print(f"Generating flame graph...", file=sys.stderr)
            data = Profiler.parse_cprofile_stats(output)
            fg = FlameGraphGenerator()
            fg.generate(data, args.flamegraph, title=f"Profile: {target}")
            if args.verbose:
                print(f"Flame graph saved to {args.flamegraph}", file=sys.stderr)

    elif args.profiler == "perf":
        result = Profiler.run_perf(target, output, event=args.event)
        if not result.get("success"):
            print(f"perf profiling failed: {result.get('error', 'unknown error')}",
                  file=sys.stderr)
            return 1
        if args.verbose:
            print(f"Perf profile saved to {output}", file=sys.stderr)

    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """Handle the 'compare' subcommand."""
    baseline_path = args.baseline
    current_path = args.current

    for path in [baseline_path, current_path]:
        if not os.path.isfile(path):
            print(f"Error: File not found: {path}", file=sys.stderr)
            return 1

    try:
        baseline_data = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
        current_data = json.loads(Path(current_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading JSON: {e}", file=sys.stderr)
        return 1

    # Reconstruct suites
    def _result_from_dict(d: Dict[str, Any]) -> BenchmarkResult:
        r = BenchmarkResult(name=d.get("name", "?"))
        r.iterations = d.get("iterations", 0)
        r.timings = d.get("timings", [])
        r.error = d.get("error")
        return r

    baseline_suite = BenchmarkSuite(
        name=baseline_data.get("name", "baseline"),
        results=[_result_from_dict(r) for r in baseline_data.get("results", [])],
    )
    current_suite = BenchmarkSuite(
        name=current_data.get("name", "current"),
        results=[_result_from_dict(r) for r in current_data.get("results", [])],
    )

    comparisons = StatisticalAnalyzer.compare_suites(baseline_suite, current_suite)

    if args.output:
        output_data = {
            "baseline": baseline_data.get("name", "baseline"),
            "current": current_data.get("name", "current"),
            "comparisons": [
                {
                    "name": c.name,
                    "baseline_avg": c.baseline.avg_time,
                    "current_avg": c.current.avg_time,
                    "abs_change": c.abs_change,
                    "rel_change": c.rel_change,
                    "verdict": c.verdict,
                }
                for c in comparisons
            ],
        }

        if args.format == "json":
            Path(args.output).write_text(
                json.dumps(output_data, indent=2, default=str), encoding="utf-8"
            )
        elif args.format == "markdown":
            Path(args.output).write_text(
                MarkdownProfilerReport.generate_comparison(comparisons), encoding="utf-8"
            )
        elif args.format == "html":
            Path(args.output).write_text(
                HTMLProfilerReport.generate_benchmark(
                    current_suite  # Use current suite for HTML
                ), encoding="utf-8"
            )

        if args.verbose:
            print(f"Comparison written to {args.output}", file=sys.stderr)
    else:
        if args.format == "json":
            print(json.dumps({
                "comparisons": [
                    {
                        "name": c.name,
                        "baseline_avg": c.baseline.avg_time,
                        "current_avg": c.current.avg_time,
                        "abs_change": c.abs_change,
                        "rel_change": c.rel_change,
                        "verdict": c.verdict,
                    }
                    for c in comparisons
                ],
            }, indent=2, default=str))
        elif args.format == "markdown":
            print(MarkdownProfilerReport.generate_comparison(comparisons))
        else:
            print("Benchmark Comparison")
            print("=" * 60)
            for c in comparisons:
                if c.rel_change == float('inf'):
                    continue
                verdict = c.verdict
                marker = ""
                if verdict == "REGRESSION":
                    marker = " [REGRESSION]"
                elif verdict == "IMPROVEMENT":
                    marker = " [IMPROVEMENT]"
                print(f"  {c.name}: {c.baseline.avg_time:.4f}s -> {c.current.avg_time:.4f}s "
                      f"({c.change_str}){marker}")

    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Handle the 'report' subcommand."""
    input_path = args.input

    if not os.path.isfile(input_path):
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        return 1

    try:
        data = json.loads(Path(input_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading JSON: {e}", file=sys.stderr)
        return 1

    # Reconstruct suite
    suite = BenchmarkSuite(
        name=data.get("name", "benchmark"),
        system_info=data.get("system_info", {}),
        timestamp=data.get("timestamp", ""),
        results=[BenchmarkResult(
            name=r.get("name", "?"),
            iterations=r.get("iterations", 0),
            timings=r.get("timings", []),
            error=r.get("error"),
        ) for r in data.get("results", [])],
    )

    if args.format == "json":
        output = json.dumps(suite.to_dict(), indent=2, default=str)
    elif args.format == "html":
        output = HTMLProfilerReport.generate_benchmark(suite)
    else:
        output = MarkdownProfilerReport.generate_benchmark(suite)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        if args.verbose:
            print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(output)

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "benchmark":
        return cmd_benchmark(args)
    elif args.command == "profile":
        return cmd_profile(args)
    elif args.command == "compare":
        return cmd_compare(args)
    elif args.command == "report":
        return cmd_report(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())