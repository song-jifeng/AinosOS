#!/usr/bin/env python3
"""Flame Graph Generator — interactive SVG flame graphs from CPU profiling data.

Generates self-contained interactive SVG flame graphs from collapsed stack
samples, perf script output, or custom stack lists. Supports multiple color
schemes, differential (delta) flame graphs, icicle layouts, and search/highlight
functionality — all with zero external dependencies.

Input formats
-------------
- Collapsed / folded stack format : ``func1;func2;func3 count``
- perf script output
- Custom list of (stack, count) tuples

Output
------
A single self-contained SVG file with inline CSS and JavaScript for interactivity
(tooltips, click-to-zoom, search, highlight).

Typical usage::

    python flamegraph.py -i collapsed_stacks.txt -o flame.svg --title "My Profile"
    python flamegraph.py -i before.txt -I after.txt -o delta.svg --differential
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import math
import os
import re
import sys
import textwrap
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple, Union


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "2.0.0"

DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 800
DEFAULT_FONT_SIZE = 12
DEFAULT_FONT_FAMILY = "monospace"
DEFAULT_MIN_FRAME_WIDTH = 1  # px — frames narrower than this are still drawn
DEFAULT_FRAME_HEIGHT = 16
DEFAULT_PAD_TOP = 24
DEFAULT_PAD_BOTTOM = 8
DEFAULT_PAD_LEFT = 8
DEFAULT_PAD_RIGHT = 8

# Colour schemes
SCHEMES = ("hot", "cold", "mem", "io", "java", "js", "default", "neutral")

# ---------------------------------------------------------------------------
# FrameNode
# ---------------------------------------------------------------------------


class FrameNode:
    """Represents a single frame in the flame graph call tree.

    Parameters
    ----------
    name : str
        Function / symbol name for this frame.
    count : int
        Sample count (weight) for this frame.
    depth : int
        Stack depth (root = 0).
    parent : FrameNode or None
        Parent frame, or ``None`` for the root.
    """

    __slots__ = (
        "name",
        "count",
        "depth",
        "parent",
        "children",
        "x",
        "width",
        "color",
        "highlighted",
        "id",
    )

    def __init__(
        self,
        name: str,
        count: int = 0,
        depth: int = 0,
        parent: Optional["FrameNode"] = None,
    ) -> None:
        self.name = name
        self.count = count
        self.depth = depth
        self.parent = parent
        self.children: List[FrameNode] = []
        self.x: float = 0.0
        self.width: float = 0.0
        self.color: str = "#cccccc"
        self.highlighted: bool = False
        self.id: str = ""

    def add_child(self, child: "FrameNode") -> None:
        """Add a child frame."""
        self.children.append(child)

    def get_child(self, name: str) -> Optional["FrameNode"]:
        """Return an existing child by name, or ``None``."""
        for c in self.children:
            if c.name == name:
                return c
        return None

    def get_or_create_child(self, name: str, depth: int) -> "FrameNode":
        """Return an existing child, or create a new one."""
        child = self.get_child(name)
        if child is None:
            child = FrameNode(name, depth=depth, parent=self)
            self.children.append(child)
        return child

    def total_count(self) -> int:
        """Return the count of this node (aggregated from all samples)."""
        return self.count

    def is_leaf(self) -> bool:
        """True if this node has no children."""
        return len(self.children) == 0

    def ancestors(self) -> List["FrameNode"]:
        """Return list of ancestors from root to self."""
        nodes: List[FrameNode] = []
        cur: Optional[FrameNode] = self
        while cur is not None:
            nodes.append(cur)
            cur = cur.parent
        nodes.reverse()
        return nodes

    def path_string(self, sep: str = ";") -> str:
        """Return the full path from root as a separated string."""
        return sep.join(n.name for n in self.ancestors())

    def __repr__(self) -> str:
        return (
            f"FrameNode(name={self.name!r}, count={self.count}, "
            f"depth={self.depth}, children={len(self.children)})"
        )


# ---------------------------------------------------------------------------
# FlameGraphConfig
# ---------------------------------------------------------------------------


@dataclass
class FlameGraphConfig:
    """Configuration for flame graph generation.

    Parameters
    ----------
    width : int
        SVG viewport width (default 1200).
    height : int
        SVG viewport height (default 800).
    font_size : int
        Base font size in px (default 12).
    font_family : str
        Font family (default ``'monospace'``).
    colors : str
        Colour scheme name (default ``'default'``).
    bg_color : str
        Background colour (default ``'#ffffff'``).
    title : str
        Main title displayed at the top.
    subtitle : str
        Optional subtitle displayed below the title.
    min_frame_width : int
        Minimum pixel width for a visible frame (default 1).
    frame_height : int
        Height of each frame row in px (default 16).
    sort_by_count : bool
        If True sort children by count descending (default True).
    reverse : bool
        If True reverse the sort order (default False).
    icicle : bool
        If True use icicle (top-down) layout (default False).
    search : str
        Optional search term to pre-highlight.
    differential : bool
        If True generate a differential flame graph.
    count_label : str
        Label for the count axis (e.g. ``'samples'``, ``'bytes'``).
    pad_top : int
        Top padding in px.
    pad_bottom : int
        Bottom padding in px.
    pad_left : int
        Left padding in px.
    pad_right : int
        Right padding in px.
    total_count : int or None
        Total count override (used for differential graphs).
    hash_colors : bool
        If True use deterministic name-based colours for the default scheme.
    """

    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    font_size: int = DEFAULT_FONT_SIZE
    font_family: str = DEFAULT_FONT_FAMILY
    colors: str = "default"
    bg_color: str = "#ffffff"
    title: str = "Flame Graph"
    subtitle: str = ""
    min_frame_width: int = DEFAULT_MIN_FRAME_WIDTH
    frame_height: int = DEFAULT_FRAME_HEIGHT
    sort_by_count: bool = True
    reverse: bool = False
    icicle: bool = False
    search: str = ""
    differential: bool = False
    count_label: str = "samples"
    pad_top: int = DEFAULT_PAD_TOP
    pad_bottom: int = DEFAULT_PAD_BOTTOM
    pad_left: int = DEFAULT_PAD_LEFT
    pad_right: int = DEFAULT_PAD_RIGHT
    total_count: Optional[int] = None
    hash_colors: bool = True


# ---------------------------------------------------------------------------
# Colour scheme helpers
# ---------------------------------------------------------------------------


def _name_hash(name: str) -> int:
    """Deterministic integer hash of a frame name."""
    return int(hashlib.md5(name.encode("utf-8")).hexdigest()[:8], 16)


def _hsv_to_rgb(h: float, s: float, v: float) -> Tuple[int, int, int]:
    """Convert HSV to RGB tuple (0-255)."""
    h = h % 360.0
    s = max(0.0, min(1.0, s))
    v = max(0.0, min(1.0, v))
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


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert RGB triplet to hex colour string."""
    return f"#{r:02x}{g:02x}{b:02x}"


def _blend(fg: Tuple[int, int, int], bg: Tuple[int, int, int],
           alpha: float) -> Tuple[int, int, int]:
    """Alpha-blend foreground over background."""
    return (
        int(fg[0] * alpha + bg[0] * (1 - alpha)),
        int(fg[1] * alpha + bg[1] * (1 - alpha)),
        int(fg[2] * alpha + bg[2] * (1 - alpha)),
    )


# ---------------------------------------------------------------------------
# Color scheme generators
# ---------------------------------------------------------------------------


def color_default(name: str, count: int, total: int) -> str:
    """Default random warm colour scheme based on name hash."""
    h = _name_hash(name)
    hue = (h % 30) + (h // 7 % 30)  # 0-60 range (warm)
    sat = 50 + (h // 3 % 30)  # 50-80
    val = 75 + (h // 11 % 20)  # 75-95
    return _rgb_to_hex(*_hsv_to_rgb(hue, sat / 100.0, val / 100.0))


def color_hot(name: str, count: int, total: int) -> str:
    """Hot colour scheme: reds, oranges, yellows by intensity."""
    ratio = count / max(total, 1)
    hue = 0 + (1 - ratio) * 40  # 0 (red) -> 40 (orange)
    sat = 80 + ratio * 20
    val = 70 + ratio * 25
    return _rgb_to_hex(*_hsv_to_rgb(hue, min(sat, 100) / 100.0,
                                     min(val, 100) / 100.0))


def color_cold(name: str, count: int, total: int) -> str:
    """Cold colour scheme: blues, purples, greens by intensity."""
    ratio = count / max(total, 1)
    hue = 180 + ratio * 80  # 180 (cyan) -> 260 (purple)
    sat = 60 + ratio * 30
    val = 60 + ratio * 35
    return _rgb_to_hex(*_hsv_to_rgb(hue, min(sat, 100) / 100.0,
                                     min(val, 100) / 100.0))


def color_mem(name: str, count: int, total: int) -> str:
    """Memory profile colour scheme: blues for allocations."""
    ratio = count / max(total, 1)
    hue = 200 + (1 - ratio) * 40  # 200-240 (blue range)
    sat = 50 + ratio * 40
    val = 50 + ratio * 40
    return _rgb_to_hex(*_hsv_to_rgb(hue, min(sat, 100) / 100.0,
                                     min(val, 100) / 100.0))


def color_io(name: str, count: int, total: int) -> str:
    """I/O colour scheme: greens for I/O operations."""
    ratio = count / max(total, 1)
    hue = 100 + (1 - ratio) * 40  # 100-140 (green range)
    sat = 50 + ratio * 40
    val = 50 + ratio * 40
    return _rgb_to_hex(*_hsv_to_rgb(hue, min(sat, 100) / 100.0,
                                     min(val, 100) / 100.0))


def color_java(name: str, count: int, total: int) -> str:
    """Java-specific colour scheme.

    Uses distinct colours for well-known Java package prefixes.
    """
    if name.startswith("java.") or name.startswith("javax."):
        base = _hsv_to_rgb(210, 0.5, 0.85)  # blue
    elif name.startswith("org."):
        base = _hsv_to_rgb(30, 0.6, 0.80)  # orange
    elif name.startswith("com."):
        base = _hsv_to_rgb(120, 0.5, 0.75)  # green
    elif name.startswith("sun.") or name.startswith("jdk."):
        base = _hsv_to_rgb(0, 0.5, 0.80)  # red
    elif name.startswith("kotlin."):
        base = _hsv_to_rgb(270, 0.5, 0.80)  # purple
    elif name.startswith("scala."):
        base = _hsv_to_rgb(0, 0.6, 0.85)  # red
    else:
        h = _name_hash(name)
        base = _hsv_to_rgb(h % 360, 0.5, 0.75)
    ratio = count / max(total, 1)
    # vary intensity
    factor = 0.6 + 0.4 * ratio
    return _rgb_to_hex(
        int(base[0] * factor),
        int(base[1] * factor),
        int(base[2] * factor),
    )


def color_js(name: str, count: int, total: int) -> str:
    """JavaScript-specific colour scheme.

    Uses yellows/browns for JS frames, with different tints for
    native vs. JS functions.
    """
    ratio = count / max(total, 1)
    if name.startswith("  ") or name.startswith("native "):
        # Native frames — cool tint
        hue = 200 + (1 - ratio) * 40
        sat = 40 + ratio * 30
        val = 50 + ratio * 30
    else:
        # JS frames — warm yellows
        hue = 40 + (1 - ratio) * 30
        sat = 60 + ratio * 30
        val = 60 + ratio * 30
    return _rgb_to_hex(*_hsv_to_rgb(hue, min(sat, 100) / 100.0,
                                     min(val, 100) / 100.0))


def color_neutral(name: str, count: int, total: int) -> str:
    """Neutral grey colour scheme, intensity by count ratio."""
    ratio = count / max(total, 1)
    val = int(160 + 80 * ratio)
    return _rgb_to_hex(val, val, val)


def color_delta_increase(name: str, count: int, total: int) -> str:
    """Red hue for increased samples in differential flame graphs."""
    ratio = min(count / max(total, 1), 1.0)
    # Red: hue ~0
    sat = 0.5 + 0.5 * ratio
    val = 0.5 + 0.5 * ratio
    return _rgb_to_hex(*_hsv_to_rgb(0, min(sat, 1.0), min(val, 1.0)))


def color_delta_decrease(name: str, count: int, total: int) -> str:
    """Green hue for decreased samples in differential flame graphs."""
    ratio = min(count / max(total, 1), 1.0)
    sat = 0.5 + 0.5 * ratio
    val = 0.5 + 0.5 * ratio
    return _rgb_to_hex(*_hsv_to_rgb(120, min(sat, 1.0), min(val, 1.0)))


def color_delta_new(name: str, count: int, total: int) -> str:
    """Yellow for new frames in differential flame graphs."""
    return "#ffd700"


_COLOR_FUNCTIONS = {
    "default": color_default,
    "hot": color_hot,
    "cold": color_cold,
    "mem": color_mem,
    "io": color_io,
    "java": color_java,
    "js": color_js,
    "neutral": color_neutral,
}


def get_color_fn(scheme: str):
    """Return the colour function for a named scheme."""
    fn = _COLOR_FUNCTIONS.get(scheme)
    if fn is None:
        raise ValueError(f"Unknown colour scheme {scheme!r}; "
                         f"choose from {list(_COLOR_FUNCTIONS)}")
    return fn


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_collapsed_stack(
    data: str,
    sep: str = ";",
    count_sep: Optional[str] = None,
) -> List[Tuple[List[str], int]]:
    """Parse collapsed / folded stack format.

    Each line is: ``func1;func2;func3 <count>``

    Parameters
    ----------
    data : str
        Multi-line string in collapsed stack format.
    sep : str
        Stack frame separator (default ``';'``).
    count_sep : str or None
        Optional separator before the count field.

    Returns
    -------
    list of (stack, count)
    """
    results: List[Tuple[List[str], int]] = []
    for line in data.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Split off the count at the end
        if count_sep is not None:
            parts = line.rsplit(count_sep, 1)
        else:
            parts = line.rsplit(None, 1)

        if len(parts) != 2:
            continue

        stack_str, count_str = parts
        try:
            count = int(count_str)
        except ValueError:
            # Try float and round
            try:
                count = int(round(float(count_str)))
            except ValueError:
                continue

        frames = stack_str.split(sep)
        results.append((frames, max(count, 1)))
    return results


def parse_collapsed_file(filepath: str) -> List[Tuple[List[str], int]]:
    """Read and parse a collapsed stack file.

    Supports ``.gz`` files transparently.
    """
    if filepath.endswith(".gz"):
        with gzip.open(filepath, "rt", encoding="utf-8", errors="replace") as f:
            data = f.read()
    else:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            data = f.read()
    return parse_collapsed_stack(data)


def parse_perf_script(
    data: str,
    event: str = "cpu-clock",
) -> List[Tuple[List[str], int]]:
    """Parse ``perf script`` output into collapsed stacks.

    Parameters
    ----------
    data : str
        Raw ``perf script`` output.
    event : str
        Event name to filter (default ``'cpu-clock'``).

    Returns
    -------
    list of (stack, count)
    """
    stacks: dict = defaultdict(int)
    current_stack: List[str] = []
    in_trace = False

    for line in data.splitlines():
        # Skip empty
        if not line.strip():
            continue

        # Check for event header line: e.g. "swapper 0 [000] 1234.5678: cpu-clock:"
        if event in line and ":" in line:
            # Flush previous stack
            if current_stack:
                stack_key = tuple(current_stack)
                stacks[stack_key] += 1
                current_stack = []
            in_trace = True
            continue

        if not in_trace:
            continue

        # Stack frame lines from perf: typically "    frame_name+0xoffset"
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # perf stack frames often have format like "func+0xoffset"
        # or "func (libc.so)" etc.
        if stripped.startswith("0x"):
            # raw address — skip
            continue

        # Extract function name (before + or space)
        func = stripped.split("+")[0].strip()
        func = func.split()[0].strip()
        if func and func != "0":
            current_stack.append(func)

    # Flush last stack
    if current_stack:
        stack_key = tuple(current_stack)
        stacks[stack_key] += 1

    return [(list(frames), count) for frames, count in stacks.items()]


def parse_perf_script_file(filepath: str, event: str = "cpu-clock") -> List[Tuple[List[str], int]]:
    """Read and parse a perf script file."""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        data = f.read()
    return parse_perf_script(data, event=event)


def collapse_stacks(stacks: List[Tuple[List[str], int]],
                    sep: str = ";") -> str:
    """Convert a list of (stack, count) to collapsed text format.

    Parameters
    ----------
    stacks : list of (list of str, int)
        Stack traces with counts.
    sep : str
        Separator for stack frames.

    Returns
    -------
    str
        Collapsed format text.
    """
    lines: List[str] = []
    for frames, count in stacks:
        line = sep.join(frames) + " " + str(count)
        lines.append(line)
    return "\n".join(lines) + "\n"


def stack_to_folded(frames: List[str], count: int, sep: str = ";") -> str:
    """Format a single stack as a folded string.

    Parameters
    ----------
    frames : list of str
        Stack frames from root to leaf.
    count : int
        Sample count.
    sep : str
        Frame separator.

    Returns
    -------
    str
        ``"func1;func2;func3 count"``
    """
    return sep.join(frames) + " " + str(count)


# ---------------------------------------------------------------------------
# Tree building
# ---------------------------------------------------------------------------


def build_tree(stacks: List[Tuple[List[str], int]],
               root_name: str = "all") -> FrameNode:
    """Build a FrameNode tree from parsed stack data.

    Parameters
    ----------
    stacks : list of (list of str, int)
        Stack traces with counts.
    root_name : str
        Name for the root node.

    Returns
    -------
    FrameNode
        Root node of the tree.
    """
    root = FrameNode(root_name, count=0, depth=0)

    for frames, sample_count in stacks:
        if not frames:
            continue
        node = root
        node.count += sample_count
        for depth, fname in enumerate(frames, start=1):
            child = node.get_or_create_child(fname, depth)
            child.count += sample_count
            node = child

    # Prune empty children if any
    _prune_empty(root)
    return root


def _prune_empty(node: FrameNode) -> None:
    """Remove children with zero count (recursive)."""
    node.children = [c for c in node.children if c.count > 0]
    for c in node.children:
        _prune_empty(c)


def _sort_children(node: FrameNode, by_count: bool = True,
                   reverse: bool = False) -> None:
    """Sort children of a node (recursive).

    Parameters
    ----------
    node : FrameNode
        Root to sort from.
    by_count : bool
        Sort by count descending (otherwise alphabetically by name).
    reverse : bool
        Reverse the sort order.
    """
    if by_count:
        node.children.sort(key=lambda c: c.count, reverse=not reverse)
    else:
        node.children.sort(key=lambda c: c.name, reverse=reverse)
    for c in node.children:
        _sort_children(c, by_count=by_count, reverse=reverse)


def _assign_layout(node: FrameNode,
                   x_start: float,
                   x_end: float,
                   total: int,
                   min_width: float = 0.0) -> None:
    """Assign x-positions and widths to all nodes recursively.

    Parameters
    ----------
    node : FrameNode
        Current node.
    x_start : float
        Left edge in pixel space.
    x_end : float
        Right edge.
    total : int
        Total count for width calculation.
    min_width : float
        Minimum width for a frame.
    """
    total_count = max(total, 1)
    w = (node.count / total_count) * (x_end - x_start)
    node.x = x_start
    node.width = max(w, min_width)
    node.width = w  # keep actual width; rendering will clamp

    if not node.children:
        return

    # Sort children first
    child_x = x_start
    for child in node.children:
        child_width = (child.count / total_count) * (x_end - x_start)
        _assign_layout(child, child_x, child_x + child_width, total, min_width)
        child_x += child_width


def _assign_colors(node: FrameNode,
                   color_fn,
                   total: int,
                   delta_data: Optional[Dict[str, float]] = None) -> None:
    """Assign colours to all nodes recursively.

    Parameters
    ----------
    node : FrameNode
        Current node.
    color_fn : callable
        Colour function ``(name, count, total) -> str``.
    total : int
        Total count for intensity calculation.
    delta_data : dict or None
        For differential graphs: ``{path_string: delta_ratio}``.
    """
    if delta_data:
        path = node.path_string()
        delta = delta_data.get(path, 0.0)
        if delta > 0.02:
            node.color = color_delta_increase(node.name, node.count, total)
        elif delta < -0.02:
            node.color = color_delta_decrease(node.name, abs(node.count), total)
        else:
            node.color = color_delta_new(node.name, node.count, total)
    else:
        node.color = color_fn(node.name, node.count, total)

    for child in node.children:
        _assign_colors(child, color_fn, total, delta_data)


def _collect_nodes(node: FrameNode,
                   nodes: Optional[List[FrameNode]] = None) -> List[FrameNode]:
    """Collect all nodes in the tree into a flat list."""
    if nodes is None:
        nodes = []
    nodes.append(node)
    for child in node.children:
        _collect_nodes(child, nodes)
    return nodes


# ---------------------------------------------------------------------------
# Differential flame graph helpers
# ---------------------------------------------------------------------------


def compute_delta(before: FrameNode, after: FrameNode) -> Dict[str, float]:
    """Compute per-frame delta ratios for differential flame graphs.

    Returns a dict ``{path_string: delta_ratio}`` where delta_ratio is
    ``(after_count - before_count) / max(before_count, 1)``.
    """
    before_counts: Dict[str, int] = {}
    after_counts: Dict[str, int] = {}

    for node in _collect_nodes(before):
        before_counts[node.path_string()] = node.count
    for node in _collect_nodes(after):
        after_counts[node.path_string()] = node.count

    all_paths = set(before_counts) | set(after_counts)
    delta: Dict[str, float] = {}
    for path in all_paths:
        b = before_counts.get(path, 0)
        a = after_counts.get(path, 0)
        delta[path] = (a - b) / max(b, 1)
    return delta


def build_differential_tree(before: FrameNode, after: FrameNode) -> FrameNode:
    """Build a combined tree for differential flame graph display.

    Uses the ``after`` tree structure with counts from ``after``,
    storing delta information for colouring.
    """
    # We use the 'after' tree as the base shape
    return after


# ---------------------------------------------------------------------------
# SVG generation
# ---------------------------------------------------------------------------

SVG_HEADER = '''<?xml version="1.0" encoding="utf-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:xlink="http://www.w3.org/1999/xlink"
     version="1.1"
     width="{width}"
     height="{height}"
     viewBox="0 0 {width} {height}"
     style="background-color: {bg_color};"
     class="flame-graph">
  <defs>
    <linearGradient id="bg_grad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{bg_grad_top}"/>
      <stop offset="100%" stop-color="{bg_grad_bottom}"/>
    </linearGradient>
    <filter id="shadow" x="-2" y="-2" width="8" height="8">
      <feDropShadow dx="0" dy="1" stdDeviation="1" flood-opacity="0.3"/>
    </filter>
  </defs>
  <rect width="100%" height="100%" fill="url(#bg_grad)"/>
'''

SVG_FOOTER = '''
</svg>'''

CSS_STYLE = '''
  <style>
    .flame-graph { font-family: {font_family}; font-size: {font_size}px; }
    .frame { cursor: pointer; }
    .frame:hover {{ stroke: #000; stroke-width: 1.5; filter: url(#shadow); }}
    .frame-rect {{ stroke: {frame_border_color}; stroke-width: 0.5; }}
    .frame-label {{ pointer-events: none; user-select: none;
                    fill: {text_color}; font-size: {font_size}px;
                    font-family: {font_family}; }}
    .title {{ fill: {title_color}; font-size: {title_size}px; font-weight: bold; }}
    .subtitle {{ fill: {subtitle_color}; font-size: {subtitle_size}px; }}
    .info-text {{ fill: {info_color}; font-size: {info_size}px; }}
    .tooltip {{ position: absolute; display: none;
                background: {tooltip_bg}; color: {tooltip_color};
                padding: 6px 10px; border-radius: 4px;
                font-size: {tooltip_size}px; font-family: {font_family};
                pointer-events: none; white-space: nowrap;
                box-shadow: 0 2px 6px rgba(0,0,0,0.3);
                z-index: 1000; }}
    .search-highlight {{ stroke: {search_stroke}; stroke-width: 2; }}
    .search-match {{ stroke: {search_stroke}; stroke-width: 2;
                     stroke-dasharray: 4,2; }}
    .legend {{ fill: {info_color}; font-size: {legend_size}px; }}
    .zoom-btn {{ cursor: pointer; }}
    .zoom-btn:hover {{ text-decoration: underline; }}
  </style>
'''


def _escape_html(s: str) -> str:
    """Escape HTML special characters."""
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace('"', "&quot;")
    s = s.replace("'", "&#39;")
    return s


def _truncate_text(text: str, max_width: float, char_width: float) -> str:
    """Truncate text to fit within a given pixel width."""
    max_chars = max(1, int(max_width / char_width))
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[:max_chars - 2] + ".."


def _wrap_text(text: str, max_width: float, char_width: float) -> List[str]:
    """Wrap text to fit within a given pixel width.

    Returns a list of lines.
    """
    max_chars = max(1, int(max_width / char_width))
    if max_chars <= 0:
        return [""]
    if len(text) <= max_chars:
        return [text]
    lines: List[str] = []
    while text:
        if len(text) <= max_chars:
            lines.append(text)
            break
        lines.append(text[:max_chars])
        text = text[max_chars:]
    return lines


class FlameGraph:
    """Main flame graph generator.

    Builds an interactive SVG flame graph from stack sample data.

    Parameters
    ----------
    config : FlameGraphConfig or None
        Configuration for the flame graph. Uses defaults if omitted.
    """

    def __init__(self, config: Optional[FlameGraphConfig] = None) -> None:
        self.config = config or FlameGraphConfig()
        self.root: Optional[FrameNode] = None
        self.total_count: int = 0
        self.all_nodes: List[FrameNode] = []
        self._node_counter: int = 0
        self._delta_data: Optional[Dict[str, float]] = None

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_collapsed(self, data: str, sep: str = ";") -> None:
        """Load data from collapsed stack format string."""
        stacks = parse_collapsed_stack(data, sep=sep)
        self._from_stacks(stacks)

    def load_collapsed_file(self, filepath: str) -> None:
        """Load data from a collapsed stack file."""
        stacks = parse_collapsed_file(filepath)
        self._from_stacks(stacks)

    def load_perf_script(self, data: str, event: str = "cpu-clock") -> None:
        """Load data from perf script output string."""
        stacks = parse_perf_script(data, event=event)
        self._from_stacks(stacks)

    def load_perf_script_file(self, filepath: str,
                              event: str = "cpu-clock") -> None:
        """Load data from a perf script file."""
        stacks = parse_perf_script_file(filepath, event=event)
        self._from_stacks(stacks)

    def load_stacks(self, stacks: List[Tuple[List[str], int]]) -> None:
        """Load data from a custom stack list."""
        self._from_stacks(stacks)

    def _from_stacks(self, stacks: List[Tuple[List[str], int]]) -> None:
        """Build the tree from parsed stack data."""
        if not stacks:
            self.root = FrameNode("all", count=0)
            self.total_count = 0
            self.all_nodes = []
            return

        self.root = build_tree(stacks)
        self.total_count = self.root.count
        self.all_nodes = _collect_nodes(self.root)

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------

    def _usable_width(self) -> float:
        """Return the usable drawing width in px."""
        return float(self.config.width - self.config.pad_left - self.config.pad_right)

    def _usable_height(self) -> float:
        """Return the usable drawing height in px."""
        return float(self.config.height - self.config.pad_top - self.config.pad_bottom)

    def _char_width(self) -> float:
        """Approximate character width for the configured font."""
        return self.config.font_size * 0.6

    def _depth_count(self) -> int:
        """Return the maximum depth of the tree."""
        if self.root is None:
            return 0
        max_depth = 0
        stack = [(self.root, 0)]
        while stack:
            node, depth = stack.pop()
            max_depth = max(max_depth, depth)
            for child in node.children:
                stack.append((child, depth + 1))
        return max_depth + 1

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _layout_tree(self) -> None:
        """Compute layout (x-positions, widths, colours) for all nodes."""
        if self.root is None or self.root.count == 0:
            return

        total = self.config.total_count or self.total_count
        width = self._usable_width()

        # Sort
        _sort_children(self.root, by_count=self.config.sort_by_count,
                       reverse=self.config.reverse)

        # Assign positions
        _assign_layout(self.root, 0.0, width, total, self.config.min_frame_width)

        # Assign colours
        color_fn = get_color_fn(self.config.colors)
        _assign_colors(self.root, color_fn, total, self._delta_data)

    # ------------------------------------------------------------------
    # SVG building
    # ------------------------------------------------------------------

    def _assign_ids(self) -> None:
        """Assign unique IDs to all nodes."""
        self._node_counter = 0
        for node in self.all_nodes:
            node.id = f"f{self._node_counter}"
            self._node_counter += 1

    def build_svg(self) -> str:
        """Generate the complete SVG document.

        Returns
        -------
        str
            Self-contained SVG string.
        """
        if self.root is None:
            return self._empty_svg()

        self._assign_ids()
        self._layout_tree()

        cfg = self.config
        w = cfg.width
        h = cfg.height
        usable_w = self._usable_width()

        # SVG parts
        parts: List[str] = []

        # Header
        bg_grad_top = _lighten_color(cfg.bg_color, 0.05)
        bg_grad_bottom = _darken_color(cfg.bg_color, 0.05)
        parts.append(SVG_HEADER.format(
            width=w, height=h, bg_color=cfg.bg_color,
            bg_grad_top=bg_grad_top, bg_grad_bottom=bg_grad_bottom,
        ))

        # CSS
        frame_border = "rgba(0,0,0,0.15)"
        text_color = "#000000"
        title_color = "#333333"
        subtitle_color = "#666666"
        info_color = "#555555"
        tooltip_bg = "#222222"
        tooltip_color = "#ffffff"
        search_stroke = "#ff0000"
        title_size = cfg.font_size + 4
        subtitle_size = cfg.font_size
        info_size = cfg.font_size - 1
        tooltip_size = cfg.font_size
        legend_size = cfg.font_size - 1

        parts.append(CSS_STYLE.format(
            font_family=cfg.font_family,
            font_size=cfg.font_size,
            frame_border_color=frame_border,
            text_color=text_color,
            title_color=title_color,
            subtitle_color=subtitle_color,
            info_color=info_color,
            tooltip_bg=tooltip_bg,
            tooltip_color=tooltip_color,
            tooltip_size=tooltip_size,
            search_stroke=search_stroke,
            legend_size=legend_size,
            title_size=title_size,
            subtitle_size=subtitle_size,
            info_size=info_size,
        ))

        # Title
        title_y = cfg.pad_top - 6
        parts.append(f'<text x="{w // 2}" y="{title_y}" '
                     f'text-anchor="middle" class="title">'
                     f'{_escape_html(cfg.title)}</text>\n')

        if cfg.subtitle:
            sub_y = title_y + title_size + 2
            parts.append(f'<text x="{w // 2}" y="{sub_y}" '
                         f'text-anchor="middle" class="subtitle">'
                         f'{_escape_html(cfg.subtitle)}</text>\n')

        # Info line
        if self.total_count > 0:
            info_y = cfg.pad_top - 6
            info_text = f"Total samples: {self.total_count:,}"
            if cfg.differential:
                info_text += " (differential mode)"
            parts.append(f'<text x="{cfg.pad_left}" y="{info_y}" '
                         f'class="info-text">{_escape_html(info_text)}</text>\n')

        # Zoom reset button
        parts.append(
            f'<text id="zoom-reset" x="{w - cfg.pad_right}" y="{info_y}" '
            f'text-anchor="end" class="zoom-btn info-text" '
            f'onclick="fg_reset()" style="display:none;">'
            f'&larr; Reset Zoom</text>\n'
        )

        # Draw frames
        frame_y_start = cfg.pad_top + 20  # leave room for title
        available_h = h - frame_y_start - cfg.pad_bottom
        frame_h = cfg.frame_height

        # Calculate how many levels fit
        max_depth = self._depth_count()
        total_frame_h = max_depth * frame_h
        if total_frame_h > available_h:
            scale = available_h / total_frame_h
            frame_h = max(8, int(frame_h * scale))

        # Build frame elements
        svg_frames: List[str] = []
        js_frames_data: List[str] = []

        for node in self.all_nodes:
            if node.depth == 0:
                continue  # skip root

            y = frame_y_start + node.depth * frame_h
            x = cfg.pad_left + node.x
            nw = node.width

            # Skip if off-screen or too narrow
            vis_width = max(nw - 1, 0)  # 1px border
            if vis_width < cfg.min_frame_width:
                continue

            # Color
            fill = node.color

            # Rect
            svg_frames.append(
                f'<g class="frame" id="{node.id}" '
                f'onclick="fg_zoom(\'{node.id}\')" '
                f'onmouseover="fg_show_tooltip(event,\'{node.id}\')" '
                f'onmouseout="fg_hide_tooltip()">\n'
                f'<rect class="frame-rect" '
                f'x="{x:.2f}" y="{y}" width="{nw:.2f}" '
                f'height="{frame_h}" fill="{fill}" '
                f'rx="1" ry="1"/>\n'
            )

            # Label
            if vis_width > self._char_width() * 3:
                label = _truncate_text(node.name, vis_width,
                                       self._char_width())
                label_x = x + 3
                label_y = y + frame_h - 4
                svg_frames.append(
                    f'<text class="frame-label" x="{label_x:.2f}" '
                    f'y="{label_y}">{_escape_html(label)}</text>\n'
                )

            svg_frames.append('</g>\n')

            # JS data for this frame
            pct = (node.count / max(self.total_count, 1)) * 100.0
            js_frames_data.append(
                f'{{id:"{node.id}",name:"{_escape_html(node.name)}",'
                f'count:{node.count},depth:{node.depth},'
                f'pct:{pct:.2f},x:{node.x:.2f},w:{node.width:.2f},'
                f'parent:"{node.parent.id if node.parent else ""}"}}'
            )

        parts.extend(svg_frames)

        # Tooltip div (foreignObject for SVG)
        # We use a regular SVG text for tooltip, plus a foreignObject
        # for more complex tooltip or just use pure SVG text.
        # For simplicity, we'll use a rect + text that appears on hover.
        # However, since we need mouse-follow, we use JS to update text.
        # We'll create a tooltip group that gets shown/hidden.
        parts.append(
            f'<g id="tooltip" style="display:none;">\n'
            f'<rect id="tooltip-bg" x="0" y="0" width="10" height="10" '
            f'rx="3" ry="3" fill="{tooltip_bg}" opacity="0.9"/>\n'
            f'<text id="tooltip-text" x="5" y="14" '
            f'fill="{tooltip_color}" font-size="{tooltip_size}px" '
            f'font-family="{cfg.font_family}"></text>\n'
            f'</g>\n'
        )

        # Legend
        legend_y = h - cfg.pad_bottom + 2
        leg_text = f"Each frame is a function call. Width ~ sample count. Hover for details, click to zoom."
        parts.append(
            f'<text x="{w // 2}" y="{legend_y}" text-anchor="middle" '
            f'class="legend">{_escape_html(leg_text)}</text>\n'
        )

        # JavaScript
        js = self._generate_js(js_frames_data, w, h)
        parts.append(js)

        # Footer
        parts.append(SVG_FOOTER)

        return "".join(parts)

    def _empty_svg(self) -> str:
        """Return an empty SVG with a message."""
        cfg = self.config
        w = cfg.width
        h = cfg.height
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" '
            f'height="{h}" viewBox="0 0 {w} {h}">\n'
            f'<rect width="100%" height="100%" fill="{cfg.bg_color}"/>\n'
            f'<text x="{w // 2}" y="{h // 2}" text-anchor="middle" '
            f'fill="#999" font-size="16" font-family="{cfg.font_family}">'
            f'No data</text>\n'
            f'</svg>'
        )

    def _generate_js(self, frames_data: List[str], width: int,
                     height: int) -> str:
        """Generate the JavaScript for interactivity.

        Parameters
        ----------
        frames_data : list of str
            JS object literals for each frame.
        width : int
        height : int

        Returns
        -------
        str
            ``<script>...</script>`` block.
        """
        cfg = self.config
        search_term = _escape_html(cfg.search)
        frame_h = cfg.frame_height

        js = f'''
<script type="text/javascript"><![CDATA[
var fg_frames = [{','.join(frames_data)}];
var fg_map = {{}};
var fg_root = null;
var fg_zoom_id = null;
var fg_total = {self.total_count};
var fg_width = {width};
var fg_chw = {self._char_width():.2f};
var fg_fh = {frame_h};
var fg_search = "{search_term}";

(function() {{
    for (var i = 0; i < fg_frames.length; i++) {{
        var f = fg_frames[i];
        fg_map[f.id] = f;
        if (f.depth === 0) fg_root = f;
    }}
    // Build parent-child relationships
    for (var i = 0; i < fg_frames.length; i++) {{
        var f = fg_frames[i];
        if (f.parent && fg_map[f.parent]) {{
            if (!fg_map[f.parent].children) fg_map[f.parent].children = [];
            fg_map[f.parent].children.push(f);
        }}
    }}
    // Apply initial search if set
    if (fg_search) {{
        fg_apply_search(fg_search);
    }}
}})();

function fg_show_tooltip(event, id) {{
    var f = fg_map[id];
    if (!f) return;
    var tip = document.getElementById('tooltip');
    var tipText = document.getElementById('tooltip-text');
    var tipBg = document.getElementById('tooltip-bg');
    if (!tip || !tipText) return;

    var pct = (f.count / fg_total * 100).toFixed(2);
    var text = f.name + ' — ' + f.count + ' samples (' + pct + '%)';
    // Add parent info
    if (f.parent && fg_map[f.parent]) {{
        text = f.name + ' \\u2190 ' + fg_map[f.parent].name + ' — ' + f.count + ' (' + pct + '%)';
    }}

    tipText.textContent = text;
    var bbox = tipText.getBBox();
    var pad = 8;
    tipBg.setAttribute('x', 0);
    tipBg.setAttribute('y', 0);
    tipBg.setAttribute('width', bbox.width + pad * 2);
    tipBg.setAttribute('height', bbox.height + pad);

    // Position near mouse
    var svg = document.querySelector('svg');
    var rect = svg.getBoundingClientRect();
    var mx = event.clientX - rect.left;
    var my = event.clientY - rect.top;
    var tx = mx + 12;
    var ty = my - 30;
    if (tx + bbox.width + pad * 2 > fg_width) {{
        tx = mx - bbox.width - pad * 2 - 12;
    }}
    if (ty < 0) ty = my + 12;
    tip.setAttribute('transform', 'translate(' + tx + ',' + ty + ')');
    tip.style.display = 'block';
}}

function fg_hide_tooltip() {{
    var tip = document.getElementById('tooltip');
    if (tip) tip.style.display = 'none';
}}

function fg_zoom(id) {{
    var f = fg_map[id];
    if (!f) return;

    fg_zoom_id = id;
    var visible = {{}};
    var queue = [id];
    visible[id] = true;
    while (queue.length > 0) {{
        var cur = queue.shift();
        var node = fg_map[cur];
        if (node && node.children) {{
            for (var i = 0; i < node.children.length; i++) {{
                var cid = node.children[i].id;
                visible[cid] = true;
                queue.push(cid);
            }}
        }}
    }}

    // Show/hide and rescale
    var zoomWidth = f.w;
    var zoomX = f.x;
    for (var i = 0; i < fg_frames.length; i++) {{
        var frame = fg_frames[i];
        var el = document.getElementById(frame.id);
        if (!el) continue;
        if (visible[frame.id]) {{
            el.style.display = '';
            // Rescale x and width
            var rect = el.querySelector('rect');
            var text = el.querySelector('text');
            if (rect) {{
                var newX = (frame.x - zoomX) / zoomWidth * fg_width;
                var newW = frame.w / zoomWidth * fg_width;
                rect.setAttribute('x', newX);
                rect.setAttribute('width', Math.max(newW, 1));
            }}
            if (text) {{
                var newX2 = (frame.x - zoomX) / zoomWidth * fg_width + 3;
                text.setAttribute('x', newX2);
                var newW2 = frame.w / zoomWidth * fg_width;
                // Truncate text
                var maxChars = Math.max(1, Math.floor(newW2 / fg_chw));
                var label = frame.name;
                if (label.length > maxChars) {{
                    if (maxChars > 3) label = label.substring(0, maxChars - 2) + '..';
                    else label = label.substring(0, maxChars);
                }}
                text.textContent = label;
            }}
        }} else {{
            el.style.display = 'none';
        }}
    }}

    // Show reset button
    var resetBtn = document.getElementById('zoom-reset');
    if (resetBtn) resetBtn.style.display = '';
}}

function fg_reset() {{
    fg_zoom_id = null;
    for (var i = 0; i < fg_frames.length; i++) {{
        var frame = fg_frames[i];
        var el = document.getElementById(frame.id);
        if (!el) continue;
        el.style.display = '';
        var rect = el.querySelector('rect');
        var text = el.querySelector('text');
        if (rect) {{
            rect.setAttribute('x', frame.x);
            rect.setAttribute('width', Math.max(frame.w, 1));
        }}
        if (text) {{
            text.setAttribute('x', frame.x + 3);
            var maxChars = Math.max(1, Math.floor(frame.w / fg_chw));
            var label = frame.name;
            if (label.length > maxChars) {{
                if (maxChars > 3) label = label.substring(0, maxChars - 2) + '..';
                else label = label.substring(0, maxChars);
            }}
            text.textContent = label;
        }}
    }}
    var resetBtn = document.getElementById('zoom-reset');
    if (resetBtn) resetBtn.style.display = 'none';
}}

function fg_search(term) {{
    fg_apply_search(term);
}}

function fg_apply_search(term) {{
    if (!term) {{
        // Clear all highlights
        for (var i = 0; i < fg_frames.length; i++) {{
            var el = document.getElementById(fg_frames[i].id);
            if (el) {{
                var rect = el.querySelector('rect');
                if (rect) rect.classList.remove('search-highlight');
            }}
        }}
        return;
    }}
    term = term.toLowerCase();
    for (var i = 0; i < fg_frames.length; i++) {{
        var frame = fg_frames[i];
        var el = document.getElementById(frame.id);
        if (!el) continue;
        var rect = el.querySelector('rect');
        if (!rect) continue;
        if (frame.name.toLowerCase().indexOf(term) >= 0) {{
            rect.classList.add('search-highlight');
        }} else {{
            rect.classList.remove('search-highlight');
        }}
    }}
}}
]]></script>'''
        return js

    # ------------------------------------------------------------------
    # Save to file
    # ------------------------------------------------------------------

    def save_svg(self, filepath: str) -> str:
        """Generate and save the SVG to a file.

        Parameters
        ----------
        filepath : str
            Output file path.

        Returns
        -------
        str
            The generated SVG string.
        """
        svg = self.build_svg()
        if filepath.endswith(".gz"):
            with gzip.open(filepath, "wt", encoding="utf-8") as f:
                f.write(svg)
        else:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(svg)
        return svg


# ---------------------------------------------------------------------------
# Colour utility functions
# ---------------------------------------------------------------------------


def _parse_color(hex_color: str) -> Tuple[int, int, int]:
    """Parse a hex colour string to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


def _lighten_color(hex_color: str, factor: float = 0.1) -> str:
    """Lighten a hex colour by blending toward white."""
    r, g, b = _parse_color(hex_color)
    factor = max(0.0, min(1.0, factor))
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return _rgb_to_hex(r, g, b)


def _darken_color(hex_color: str, factor: float = 0.1) -> str:
    """Darken a hex colour by blending toward black."""
    r, g, b = _parse_color(hex_color)
    factor = max(0.0, min(1.0, factor))
    r = int(r * (1 - factor))
    g = int(g * (1 - factor))
    b = int(b * (1 - factor))
    return _rgb_to_hex(r, g, b)


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def generate_flamegraph(
    stacks: List[Tuple[List[str], int]],
    output: str = "flamegraph.svg",
    title: str = "Flame Graph",
    colors: str = "default",
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    font_size: int = DEFAULT_FONT_SIZE,
    **kwargs,
) -> str:
    """Convenience function to generate a flame graph from stack data.

    Parameters
    ----------
    stacks : list of (list of str, int)
        Stack traces with sample counts.
    output : str
        Output SVG file path.
    title : str
        Graph title.
    colors : str
        Colour scheme name.
    width : int
        SVG width.
    height : int
        SVG height.
    font_size : int
        Font size in px.
    **kwargs
        Additional :class:`FlameGraphConfig` fields.

    Returns
    -------
    str
        Generated SVG content.
    """
    config = FlameGraphConfig(
        width=width,
        height=height,
        font_size=font_size,
        colors=colors,
        title=title,
        **kwargs,
    )
    fg = FlameGraph(config)
    fg.load_stacks(stacks)
    return fg.save_svg(output)


# ---------------------------------------------------------------------------
# Differential flame graph
# ---------------------------------------------------------------------------


def generate_differential(
    before_stacks: List[Tuple[List[str], int]],
    after_stacks: List[Tuple[List[str], int]],
    output: str = "delta.svg",
    title: str = "Differential Flame Graph",
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    **kwargs,
) -> str:
    """Generate a differential flame graph comparing two profiles.

    Parameters
    ----------
    before_stacks : list of (list of str, int)
        Baseline profile.
    after_stacks : list of (list of str, int)
        New profile to compare.
    output : str
        Output SVG file path.
    title : str
        Graph title.
    width : int
        SVG width.
    height : int
        SVG height.
    **kwargs
        Additional :class:`FlameGraphConfig` fields.

    Returns
    -------
    str
        Generated SVG content.
    """
    config = FlameGraphConfig(
        width=width,
        height=height,
        colors="default",
        title=title,
        differential=True,
        **kwargs,
    )

    before_tree = build_tree(before_stacks)
    after_tree = build_tree(after_stacks)
    delta_data = compute_delta(before_tree, after_tree)

    fg = FlameGraph(config)
    fg.load_stacks(after_stacks)
    fg._delta_data = delta_data
    return fg.save_svg(output)


# ===========================================================================
# CLI
# ===========================================================================


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate interactive SVG flame graphs from profiling data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              %(prog)s -i collapsed.txt -o flame.svg
              %(prog)s -i collapsed.txt --title "My App" --colors hot
              %(prog)s -i before.txt -I after.txt -o delta.svg --differential
              %(prog)s -i perf.txt --perf-script
        """),
    )

    # Input / Output
    parser.add_argument(
        "--input", "-i", type=str, default="",
        help="Input file (collapsed stack format, or perf script with --perf-script)"
    )
    parser.add_argument(
        "--input2", "-I", type=str, default="",
        help="Second input file (for differential flame graphs)"
    )
    parser.add_argument(
        "--output", "-o", type=str, default="flamegraph.svg",
        help="Output SVG file (default: flamegraph.svg)"
    )

    # Input format
    parser.add_argument(
        "--perf-script", action="store_true",
        help="Parse input as perf script output"
    )
    parser.add_argument(
        "--event", type=str, default="cpu-clock",
        help="Perf event name (default: cpu-clock)"
    )

    # Appearance
    parser.add_argument(
        "--title", type=str, default="Flame Graph",
        help="Graph title (default: Flame Graph)"
    )
    parser.add_argument(
        "--subtitle", type=str, default="",
        help="Optional subtitle"
    )
    parser.add_argument(
        "--colors", type=str, default="default",
        choices=SCHEMES,
        help=f"Colour scheme (default: default). Choices: {', '.join(SCHEMES)}"
    )
    parser.add_argument(
        "--width", type=int, default=DEFAULT_WIDTH,
        help=f"SVG width in px (default: {DEFAULT_WIDTH})"
    )
    parser.add_argument(
        "--height", type=int, default=DEFAULT_HEIGHT,
        help=f"SVG height in px (default: {DEFAULT_HEIGHT})"
    )
    parser.add_argument(
        "--font-size", type=int, default=DEFAULT_FONT_SIZE,
        help=f"Font size in px (default: {DEFAULT_FONT_SIZE})"
    )
    parser.add_argument(
        "--font-family", type=str, default=DEFAULT_FONT_FAMILY,
        help=f"Font family (default: {DEFAULT_FONT_FAMILY})"
    )
    parser.add_argument(
        "--bg-color", type=str, default="#ffffff",
        help="Background colour (default: #ffffff)"
    )
    parser.add_argument(
        "--frame-height", type=int, default=DEFAULT_FRAME_HEIGHT,
        help=f"Frame height in px (default: {DEFAULT_FRAME_HEIGHT})"
    )
    parser.add_argument(
        "--min-frame-width", type=int, default=DEFAULT_MIN_FRAME_WIDTH,
        help=f"Minimum frame width in px (default: {DEFAULT_MIN_FRAME_WIDTH})"
    )

    # Options
    parser.add_argument(
        "--differential", action="store_true",
        help="Generate differential flame graph (requires --input and --input2)"
    )
    parser.add_argument(
        "--sort-by-count", action="store_true", default=True,
        help="Sort frames by count (default: True)"
    )
    parser.add_argument(
        "--no-sort-by-count", action="store_false", dest="sort_by_count",
        help="Sort frames alphabetically"
    )
    parser.add_argument(
        "--reverse", action="store_true",
        help="Reverse sort order"
    )
    parser.add_argument(
        "--search", type=str, default="",
        help="Initial search term to highlight"
    )
    parser.add_argument(
        "--count-label", type=str, default="samples",
        help="Label for count axis (default: samples)"
    )
    parser.add_argument(
        "--version", action="version",
        version=f"%(prog)s {VERSION}"
    )

    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for flame graph generation.

    Parameters
    ----------
    argv : list of str or None
        Command-line arguments (uses ``sys.argv[1:]`` if None).

    Returns
    -------
    int
        Exit code (0 on success).
    """
    args = _parse_args(argv)

    config = FlameGraphConfig(
        width=args.width,
        height=args.height,
        font_size=args.font_size,
        font_family=args.font_family,
        colors=args.colors,
        bg_color=args.bg_color,
        title=args.title,
        subtitle=args.subtitle,
        min_frame_width=args.min_frame_width,
        frame_height=args.frame_height,
        sort_by_count=args.sort_by_count,
        reverse=args.reverse,
        search=args.search,
        differential=args.differential,
        count_label=args.count_label,
    )

    # ---------------------------------------------------------------
    # Differential mode
    # ---------------------------------------------------------------
    if args.differential:
        if not args.input or not args.input2:
            print("error: --differential requires both --input and --input2",
                  file=sys.stderr)
            return 1

        if args.perf_script:
            before_stacks = parse_perf_script_file(args.input, event=args.event)
            after_stacks = parse_perf_script_file(args.input2, event=args.event)
        else:
            before_stacks = parse_collapsed_file(args.input)
            after_stacks = parse_collapsed_file(args.input2)

        if not before_stacks or not after_stacks:
            print("error: one or both input files contain no valid data",
                  file=sys.stderr)
            return 1

        svg = generate_differential(
            before_stacks, after_stacks,
            output=args.output,
            title=args.title,
            width=args.width,
            height=args.height,
        )
        print(f"Wrote differential flame graph to {args.output}")
        return 0

    # ---------------------------------------------------------------
    # Single input mode
    # ---------------------------------------------------------------
    if not args.input:
        print("error: --input is required (use --help for usage)",
              file=sys.stderr)
        return 1

    fg = FlameGraph(config)

    if args.perf_script:
        try:
            fg.load_perf_script_file(args.input, event=args.event)
        except FileNotFoundError:
            print(f"error: input file not found: {args.input}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"error parsing perf script: {e}", file=sys.stderr)
            return 1
    else:
        try:
            fg.load_collapsed_file(args.input)
        except FileNotFoundError:
            print(f"error: input file not found: {args.input}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"error parsing collapsed stacks: {e}", file=sys.stderr)
            return 1

    if fg.total_count == 0:
        print("warning: no samples found in input", file=sys.stderr)

    try:
        svg = fg.save_svg(args.output)
        print(f"Wrote flame graph to {args.output} "
              f"({fg.total_count:,} samples, "
              f"{len(fg.all_nodes)} frames)")
    except Exception as e:
        print(f"error writing SVG: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())