"""Flamegraph package for AI Profiler.

Provides interactive SVG flame graph and icicle graph generation from
profiling data. Supports collapsed stack format, perf script output,
and custom stack data with multiple colour schemes.

Modules:
    flamegraph: Interactive SVG flame graph generator (bottom-up view)
    icicle: Interactive SVG icicle graph generator (top-down view)
"""

from .flamegraph import FlameGraph, FlameGraphConfig, FrameNode, generate_flamegraph
from .icicle import IcicleGraph, IcicleGraphConfig, IcicleFrameNode, generate_icicle

__all__ = [
    "FlameGraph",
    "FlameGraphConfig",
    "FrameNode",
    "generate_flamegraph",
    "IcicleGraph",
    "IcicleGraphConfig",
    "IcicleFrameNode",
    "generate_icicle",
]