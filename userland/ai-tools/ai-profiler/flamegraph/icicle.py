#!/usr/bin/env python3
"""Icicle Graph Generator — top-down interactive SVG visualizations for profiling data.

An icicle graph is a top-down (root-at-top) layout, functionally the inverse of a
flame graph. It is particularly useful for memory and allocation profiling, where
the call tree is visualised from the root outward.

This module provides a full-featured icicle graph generator with SVG output,
interactive tooltips, click-to-zoom, search/highlight, and multiple colour
schemes designed for memory, allocation, and general-purpose profiling.

Input formats
-------------
- Collapsed / folded stack format : ``func1;func2;func3 count``
- Brendan Gregg's folded format
- Custom list of (stack, count) tuples
- flame graph FrameNode tree (via conversion functions)

Output
------
A single self-contained SVG file with inline CSS and JavaScript for interactivity.

Typical usage::

    python icicle.py -i collapsed_stacks.txt -o icicle.svg --title "Memory Profile"
    python icicle.py -i collapsed.txt -o alloc.svg --colors mem --title "Allocations"
    python icicle.py -i collapsed.txt -o icicle.svg --icicle-layout top-down
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import math
import os
import sys
import textwrap
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple, Union


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "1.0.0"

DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 800
DEFAULT_FONT_SIZE = 12
DEFAULT_FONT_FAMILY = "monospace"
DEFAULT_MIN_FRAME_WIDTH = 1
DEFAULT_FRAME_HEIGHT = 18
DEFAULT_PAD_TOP = 32
DEFAULT_PAD_BOTTOM = 8
DEFAULT_PAD_LEFT = 8
DEFAULT_PAD_RIGHT = 8

ICICLE_SCHEMES = ("mem", "alloc", "hot", "cold", "default", "neutral", "pastel")


# ---------------------------------------------------------------------------
# IcicleGraphConfig
# ---------------------------------------------------------------------------


@dataclass
class IcicleGraphConfig:
    """Configuration for icicle graph generation.

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
        Colour scheme name (default ``'mem'``).
    bg_color : str
        Background colour (default ``'#ffffff'``).
    title : str
        Main title displayed at the top.
    subtitle : str
        Optional subtitle displayed below the title.
    min_frame_width : int
        Minimum pixel width for a visible frame (default 1).
    frame_height : int
        Height of each frame row in px (default 18).
    sort_by_count : bool
        If True sort children by count descending (default True).
    reverse : bool
        If True reverse the sort order (default False).
    search : str
        Optional search term to pre-highlight.
    count_label : str
        Label for the count axis (e.g. ``'bytes'``, ``'samples'``).
    pad_top : int
        Top padding in px.
    pad_bottom : int
        Bottom padding in px.
    pad_left : int
        Left padding in px.
    pad_right : int
        Right padding in px.
    total_count : int or None
        Total count override.
    hash_colors : bool
        If True use deterministic name-based colours.
    show_root : bool
        If True display the root node as a frame.
    rounded_corners : bool
        If True apply rounded corners to frames.
    """

    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    font_size: int = DEFAULT_FONT_SIZE
    font_family: str = DEFAULT_FONT_FAMILY
    colors: str = "mem"
    bg_color: str = "#ffffff"
    title: str = "Icicle Graph"
    subtitle: str = ""
    min_frame_width: int = DEFAULT_MIN_FRAME_WIDTH
    frame_height: int = DEFAULT_FRAME_HEIGHT
    sort_by_count: bool = True
    reverse: bool = False
    search: str = ""
    count_label: str = "bytes"
    pad_top: int = DEFAULT_PAD_TOP
    pad_bottom: int = DEFAULT_PAD_BOTTOM
    pad_left: int = DEFAULT_PAD_LEFT
    pad_right: int = DEFAULT_PAD_RIGHT
    total_count: Optional[int] = None
    hash_colors: bool = True
    show_root: bool = False
    rounded_corners: bool = True


# ---------------------------------------------------------------------------
# FrameNode (re-implemented for icicle independence)
# ---------------------------------------------------------------------------


class IcicleFrameNode:
    """Represents a single frame in the icicle graph call tree.

    Parameters
    ----------
    name : str
        Function / symbol name for this frame.
    count : int
        Sample count (weight) for this frame.
    depth : int
        Depth in the tree (root = 0).
    parent : IcicleFrameNode or None
        Parent frame, or ``None`` for the root.
    """

    __slots__ = (
        "name", "count", "depth", "parent", "children",
        "x", "width", "color", "highlighted", "id",
    )

    def __init__(
        self,
        name: str,
        count: int = 0,
        depth: int = 0,
        parent: Optional["IcicleFrameNode"] = None,
    ) -> None:
        self.name = name
        self.count = count
        self.depth = depth
        self.parent = parent
        self.children: List[IcicleFrameNode] = []
        self.x: float = 0.0
        self.width: float = 0.0
        self.color: str = "#cccccc"
        self.highlighted: bool = False
        self.id: str = ""

    def add_child(self, child: "IcicleFrameNode") -> None:
        """Add a child frame."""
        self.children.append(child)

    def get_child(self, name: str) -> Optional["IcicleFrameNode"]:
        """Return an existing child by name, or ``None``."""
        for c in self.children:
            if c.name == name:
                return c
        return None

    def get_or_create_child(self, name: str, depth: int) -> "IcicleFrameNode":
        """Return an existing child, or create a new one."""
        child = self.get_child(name)
        if child is None:
            child = IcicleFrameNode(name, depth=depth, parent=self)
            self.children.append(child)
        return child

    def total_count(self) -> int:
        return self.count

    def is_leaf(self) -> bool:
        return len(self.children) == 0

    def ancestors(self) -> List["IcicleFrameNode"]:
        nodes: List[IcicleFrameNode] = []
        cur: Optional[IcicleFrameNode] = self
        while cur is not None:
            nodes.append(cur)
            cur = cur.parent
        nodes.reverse()
        return nodes

    def path_string(self, sep: str = ";") -> str:
        return sep.join(n.name for n in self.ancestors())

    def __repr__(self) -> str:
        return (
            f"IcicleFrameNode(name={self.name!r}, count={self.count}, "
            f"depth={self.depth}, children={len(self.children)})"
        )


# ---------------------------------------------------------------------------
# Colour scheme helpers
# ---------------------------------------------------------------------------


def _name_hash(name: str) -> int:
    return int(hashlib.md5(name.encode("utf-8")).hexdigest()[:8], 16)


def _hsv_to_rgb(h: float, s: float, v: float) -> Tuple[int, int, int]:
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
    return f"#{r:02x}{g:02x}{b:02x}"


# ---------------------------------------------------------------------------
# Icicle colour schemes
# ---------------------------------------------------------------------------


def icicle_color_mem(name: str, count: int, total: int) -> str:
    """Memory profile colour scheme: blue-toned, intensity by allocation size."""
    ratio = count / max(total, 1)
    # Blue range: 200-240
    hue = 210 + (1 - ratio) * 30
    sat = 40 + ratio * 45
    val = 50 + ratio * 40
    return _rgb_to_hex(*_hsv_to_rgb(hue, min(sat, 100) / 100.0,
                                     min(val, 100) / 100.0))


def icicle_color_alloc(name: str, count: int, total: int) -> str:
    """Allocation profile colour scheme: green-to-blue based on size."""
    ratio = count / max(total, 1)
    # Green to blue-green: 140-190
    hue = 140 + ratio * 50
    sat = 50 + ratio * 35
    val = 50 + ratio * 40
    return _rgb_to_hex(*_hsv_to_rgb(hue, min(sat, 100) / 100.0,
                                     min(val, 100) / 100.0))


def icicle_color_hot(name: str, count: int, total: int) -> str:
    """Hot colour scheme: reds, oranges, yellows by intensity."""
    ratio = count / max(total, 1)
    hue = 0 + (1 - ratio) * 40
    sat = 70 + ratio * 25
    val = 65 + ratio * 30
    return _rgb_to_hex(*_hsv_to_rgb(hue, min(sat, 100) / 100.0,
                                     min(val, 100) / 100.0))


def icicle_color_cold(name: str, count: int, total: int) -> str:
    """Cold colour scheme: blues, purples by intensity."""
    ratio = count / max(total, 1)
    hue = 200 + ratio * 60
    sat = 50 + ratio * 35
    val = 55 + ratio * 40
    return _rgb_to_hex(*_hsv_to_rgb(hue, min(sat, 100) / 100.0,
                                     min(val, 100) / 100.0))


def icicle_color_default(name: str, count: int, total: int) -> str:
    """Default colour scheme: warm name-based colours."""
    h = _name_hash(name)
    hue = (h % 30) + (h // 7 % 30)
    sat = 50 + (h // 3 % 30)
    val = 70 + (h // 11 % 20)
    return _rgb_to_hex(*_hsv_to_rgb(hue, sat / 100.0, val / 100.0))


def icicle_color_neutral(name: str, count: int, total: int) -> str:
    """Neutral grey scheme, intensity by ratio."""
    ratio = count / max(total, 1)
    v = int(150 + 90 * ratio)
    return _rgb_to_hex(v, v, v)


def icicle_color_pastel(name: str, count: int, total: int) -> str:
    """Pastel colours: soft, light tones."""
    h = _name_hash(name) % 360
    sat = 30 + (count / max(total, 1)) * 20
    val = 90
    return _rgb_to_hex(*_hsv_to_rgb(h, min(sat, 100) / 100.0, val / 100.0))


_ICICLE_COLOR_FUNCTIONS = {
    "mem": icicle_color_mem,
    "alloc": icicle_color_alloc,
    "hot": icicle_color_hot,
    "cold": icicle_color_cold,
    "default": icicle_color_default,
    "neutral": icicle_color_neutral,
    "pastel": icicle_color_pastel,
}


def get_icicle_color_fn(scheme: str):
    """Return the colour function for a named icicle scheme."""
    fn = _ICICLE_COLOR_FUNCTIONS.get(scheme)
    if fn is None:
        raise ValueError(
            f"Unknown icicle colour scheme {scheme!r}; "
            f"choose from {list(_ICICLE_COLOR_FUNCTIONS)}"
        )
    return fn


# ---------------------------------------------------------------------------
# Parsing (shared with flamegraph)
# ---------------------------------------------------------------------------


def parse_collapsed_stack(
    data: str,
    sep: str = ";",
) -> List[Tuple[List[str], int]]:
    """Parse collapsed / folded stack format.

    Each line is: ``func1;func2;func3 <count>``
    """
    results: List[Tuple[List[str], int]] = []
    for line in data.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.rsplit(None, 1)
        if len(parts) != 2:
            continue
        stack_str, count_str = parts
        try:
            count = int(count_str)
        except ValueError:
            try:
                count = int(round(float(count_str)))
            except ValueError:
                continue
        frames = stack_str.split(sep)
        results.append((frames, max(count, 1)))
    return results


def parse_collapsed_file(filepath: str) -> List[Tuple[List[str], int]]:
    """Read and parse a collapsed stack file (supports .gz)."""
    if filepath.endswith(".gz"):
        with gzip.open(filepath, "rt", encoding="utf-8", errors="replace") as f:
            data = f.read()
    else:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            data = f.read()
    return parse_collapsed_stack(data)


# ---------------------------------------------------------------------------
# Tree building
# ---------------------------------------------------------------------------


def build_icicle_tree(
    stacks: List[Tuple[List[str], int]],
    root_name: str = "all",
) -> IcicleFrameNode:
    """Build an IcicleFrameNode tree from parsed stack data.

    Parameters
    ----------
    stacks : list of (list of str, int)
        Stack traces with counts.
    root_name : str
        Name for the root node.

    Returns
    -------
    IcicleFrameNode
        Root node of the tree.
    """
    root = IcicleFrameNode(root_name, count=0, depth=0)
    for frames, sample_count in stacks:
        if not frames:
            continue
        node = root
        node.count += sample_count
        for depth, fname in enumerate(frames, start=1):
            child = node.get_or_create_child(fname, depth)
            child.count += sample_count
            node = child
    # Prune empty children
    _prune_empty(root)
    return root


def _prune_empty(node: IcicleFrameNode) -> None:
    """Remove children with zero count (recursive)."""
    node.children = [c for c in node.children if c.count > 0]
    for c in node.children:
        _prune_empty(c)


def _sort_children(
    node: IcicleFrameNode,
    by_count: bool = True,
    reverse: bool = False,
) -> None:
    """Sort children of a node recursively."""
    if by_count:
        node.children.sort(key=lambda c: c.count, reverse=not reverse)
    else:
        node.children.sort(key=lambda c: c.name, reverse=reverse)
    for c in node.children:
        _sort_children(c, by_count=by_count, reverse=reverse)


def _assign_layout(
    node: IcicleFrameNode,
    x_start: float,
    x_end: float,
    total: int,
    min_width: float = 0.0,
) -> None:
    """Assign x-positions and widths to all nodes recursively."""
    total_count = max(total, 1)
    node.x = x_start
    w = (node.count / total_count) * (x_end - x_start)
    node.width = w

    if not node.children:
        return

    child_x = x_start
    for child in node.children:
        child_width = (child.count / total_count) * (x_end - x_start)
        _assign_layout(child, child_x, child_x + child_width, total, min_width)
        child_x += child_width


def _assign_colors(
    node: IcicleFrameNode,
    color_fn,
    total: int,
) -> None:
    """Assign colours to all nodes recursively."""
    node.color = color_fn(node.name, node.count, total)
    for child in node.children:
        _assign_colors(child, color_fn, total)


def _collect_nodes(
    node: IcicleFrameNode,
    nodes: Optional[List[IcicleFrameNode]] = None,
) -> List[IcicleFrameNode]:
    """Collect all nodes into a flat list."""
    if nodes is None:
        nodes = []
    nodes.append(node)
    for child in node.children:
        _collect_nodes(child, nodes)
    return nodes


def _depth_count(node: IcicleFrameNode) -> int:
    """Return the maximum depth of the tree."""
    if not node.children:
        return 1
    return 1 + max(_depth_count(c) for c in node.children)


# ---------------------------------------------------------------------------
# Conversion from flame graph data
# ---------------------------------------------------------------------------


def flamegraph_to_icicle(stacks: List[Tuple[List[str], int]]) -> List[Tuple[List[str], int]]:
    """Convert flame graph stack data to icicle format.

    For icicle graphs, the stack order is the same (root first, leaf last),
    but the visualisation is top-down. This function is a pass-through for
    compatibility; the layout difference is handled by the IcicleGraph class.

    Parameters
    ----------
    stacks : list of (list of str, int)
        Stack traces (root-to-leaf) with counts.

    Returns
    -------
    list of (list of str, int)
        Same stacks, compatible with icicle graph input.
    """
    return stacks


def convert_flamegraph_node(
    flame_node,
    parent: Optional[IcicleFrameNode] = None,
    depth: int = 0,
) -> IcicleFrameNode:
    """Convert a flamegraph FrameNode into an IcicleFrameNode.

    Parameters
    ----------
    flame_node : FrameNode
        Node from a flame graph tree.
    parent : IcicleFrameNode or None
        Parent for the new node.
    depth : int
        Depth for the new node.

    Returns
    -------
    IcicleFrameNode
        Converted node.
    """
    icicle_node = IcicleFrameNode(
        name=flame_node.name,
        count=flame_node.count,
        depth=depth,
        parent=parent,
    )
    for child in flame_node.children:
        icicle_child = convert_flamegraph_node(child, icicle_node, depth + 1)
        icicle_node.children.append(icicle_child)
    return icicle_node


# ---------------------------------------------------------------------------
# SVG generation
# ---------------------------------------------------------------------------

ICICLE_SVG_HEADER = '''<?xml version="1.0" encoding="utf-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:xlink="http://www.w3.org/1999/xlink"
     version="1.1"
     width="{width}"
     height="{height}"
     viewBox="0 0 {width} {height}"
     style="background-color: {bg_color};"
     class="icicle-graph">
  <defs>
    <linearGradient id="icicle_bg_grad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{bg_grad_top}"/>
      <stop offset="100%" stop-color="{bg_grad_bottom}"/>
    </linearGradient>
    <filter id="icicle_shadow" x="-2" y="-2" width="8" height="8">
      <feDropShadow dx="0" dy="1" stdDeviation="1" flood-opacity="0.25"/>
    </filter>
  </defs>
  <rect width="100%" height="100%" fill="url(#icicle_bg_grad)"/>
'''

ICICLE_SVG_FOOTER = "\n</svg>"

ICICLE_CSS = '''  <style>
    .icicle-graph { font-family: {font_family}; font-size: {font_size}px; }
    .icicle-frame { cursor: pointer; }
    .icicle-frame:hover {{ stroke: #000; stroke-width: 1.5; filter: url(#icicle_shadow); }}
    .icicle-frame-rect {{ stroke: {frame_border_color}; stroke-width: 0.5; }}
    .icicle-frame-label {{ pointer-events: none; user-select: none;
                          fill: {text_color}; font-size: {font_size}px;
                          font-family: {font_family}; }}
    .icicle-title {{ fill: {title_color}; font-size: {title_size}px; font-weight: bold; }}
    .icicle-subtitle {{ fill: {subtitle_color}; font-size: {subtitle_size}px; }}
    .icicle-info {{ fill: {info_color}; font-size: {info_size}px; }}
    .icicle-tooltip {{ position: absolute; display: none;
                      background: {tooltip_bg}; color: {tooltip_color};
                      padding: 6px 10px; border-radius: 4px;
                      font-size: {tooltip_size}px; font-family: {font_family};
                      pointer-events: none; white-space: nowrap;
                      box-shadow: 0 2px 6px rgba(0,0,0,0.3);
                      z-index: 1000; }}
    .icicle-search-highlight {{ stroke: {search_stroke}; stroke-width: 2.5; }}
    .icicle-legend {{ fill: {info_color}; font-size: {legend_size}px; }}
    .icicle-zoom-btn {{ cursor: pointer; }}
    .icicle-zoom-btn:hover {{ text-decoration: underline; }}
  </style>'''


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _escape_html(s: str) -> str:
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace('"', "&quot;")
    s = s.replace("'", "&#39;")
    return s


def _truncate_text(text: str, max_width: float, char_width: float) -> str:
    max_chars = max(1, int(max_width / char_width))
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[:max_chars - 2] + ".."


def _parse_color(hex_color: str) -> Tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


def _lighten_color(hex_color: str, factor: float = 0.05) -> str:
    r, g, b = _parse_color(hex_color)
    factor = max(0.0, min(1.0, factor))
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return _rgb_to_hex(r, g, b)


def _darken_color(hex_color: str, factor: float = 0.05) -> str:
    r, g, b = _parse_color(hex_color)
    factor = max(0.0, min(1.0, factor))
    r = int(r * (1 - factor))
    g = int(g * (1 - factor))
    b = int(b * (1 - factor))
    return _rgb_to_hex(r, g, b)


# ---------------------------------------------------------------------------
# IcicleGraph
# ---------------------------------------------------------------------------


class IcicleGraph:
    """Icicle graph generator — top-down interactive SVG visualisation.

    Builds an interactive SVG icicle graph from stack sample data, with
    root at the top and children extending downward.

    Parameters
    ----------
    config : IcicleGraphConfig or None
        Configuration for the icicle graph. Uses defaults if omitted.
    """

    def __init__(self, config: Optional[IcicleGraphConfig] = None) -> None:
        self.config = config or IcicleGraphConfig()
        self.root: Optional[IcicleFrameNode] = None
        self.total_count: int = 0
        self.all_nodes: List[IcicleFrameNode] = []
        self._node_counter: int = 0

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

    def load_stacks(self, stacks: List[Tuple[List[str], int]]) -> None:
        """Load data from a custom stack list."""
        self._from_stacks(stacks)

    def _from_stacks(self, stacks: List[Tuple[List[str], int]]) -> None:
        """Build the tree from parsed stack data."""
        if not stacks:
            self.root = IcicleFrameNode("all", count=0)
            self.total_count = 0
            self.all_nodes = []
            return
        self.root = build_icicle_tree(stacks)
        self.total_count = self.root.count
        self.all_nodes = _collect_nodes(self.root)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _usable_width(self) -> float:
        return float(self.config.width - self.config.pad_left - self.config.pad_right)

    def _usable_height(self) -> float:
        return float(self.config.height - self.config.pad_top - self.config.pad_bottom)

    def _char_width(self) -> float:
        return self.config.font_size * 0.6

    def _layout_tree(self) -> None:
        """Compute layout (x-positions, widths, colours) for all nodes."""
        if self.root is None or self.root.count == 0:
            return
        total = self.config.total_count or self.total_count
        width = self._usable_width()
        _sort_children(self.root, by_count=self.config.sort_by_count,
                       reverse=self.config.reverse)
        _assign_layout(self.root, 0.0, width, total, self.config.min_frame_width)
        color_fn = get_icicle_color_fn(self.config.colors)
        _assign_colors(self.root, color_fn, total)

    # ------------------------------------------------------------------
    # SVG building
    # ------------------------------------------------------------------

    def _assign_ids(self) -> None:
        self._node_counter = 0
        for node in self.all_nodes:
            node.id = f"ic{self._node_counter}"
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

        parts: List[str] = []

        # Header
        bg_grad_top = _lighten_color(cfg.bg_color, 0.05)
        bg_grad_bottom = _darken_color(cfg.bg_color, 0.05)
        parts.append(ICICLE_SVG_HEADER.format(
            width=w, height=h, bg_color=cfg.bg_color,
            bg_grad_top=bg_grad_top, bg_grad_bottom=bg_grad_bottom,
        ))

        # CSS
        frame_border = "rgba(0,0,0,0.12)"
        text_color = "#000000"
        title_color = "#333333"
        subtitle_color = "#666666"
        info_color = "#555555"
        tooltip_bg = "#222222"
        tooltip_color = "#ffffff"
        search_stroke = "#ff4400"
        title_size = cfg.font_size + 4
        subtitle_size = cfg.font_size
        info_size = cfg.font_size - 1
        tooltip_size = cfg.font_size
        legend_size = cfg.font_size - 1

        parts.append(ICICLE_CSS.format(
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
        parts.append(
            f'<text x="{w // 2}" y="{title_y}" text-anchor="middle" '
            f'class="icicle-title">{_escape_html(cfg.title)}</text>\n'
        )
        if cfg.subtitle:
            sub_y = title_y + title_size + 2
            parts.append(
                f'<text x="{w // 2}" y="{sub_y}" text-anchor="middle" '
                f'class="icicle-subtitle">{_escape_html(cfg.subtitle)}</text>\n'
            )

        # Info line
        info_y = cfg.pad_top - 6
        info_text = f"Total: {self.total_count:,} {cfg.count_label}"
        parts.append(
            f'<text x="{cfg.pad_left}" y="{info_y}" '
            f'class="icicle-info">{_escape_html(info_text)}</text>\n'
        )

        # Zoom reset
        parts.append(
            f'<text id="icicle-zoom-reset" x="{w - cfg.pad_right}" y="{info_y}" '
            f'text-anchor="end" class="icicle-zoom-btn icicle-info" '
            f'onclick="ic_reset()" style="display:none;">'
            f'&larr; Reset Zoom</text>\n'
        )

        # Draw frames
        frame_y_start = cfg.pad_top + 20
        available_h = h - frame_y_start - cfg.pad_bottom
        frame_h = cfg.frame_height

        max_depth = _depth_count(self.root) if self.root else 0
        total_frame_h = max_depth * frame_h
        if total_frame_h > available_h:
            scale = available_h / total_frame_h
            frame_h = max(8, int(frame_h * scale))

        svg_frames: List[str] = []
        js_frames_data: List[str] = []

        for node in self.all_nodes:
            if node.depth == 0 and not cfg.show_root:
                continue

            y = frame_y_start + node.depth * frame_h
            x = cfg.pad_left + node.x
            nw = node.width
            vis_width = max(nw - 1, 0)
            if vis_width < cfg.min_frame_width:
                continue

            fill = node.color
            rx = 2 if cfg.rounded_corners else 0
            ry = rx

            svg_frames.append(
                f'<g class="icicle-frame" id="{node.id}" '
                f'onclick="ic_zoom(\'{node.id}\')" '
                f'onmouseover="ic_show_tooltip(event,\'{node.id}\')" '
                f'onmouseout="ic_hide_tooltip()">\n'
                f'<rect class="icicle-frame-rect" '
                f'x="{x:.2f}" y="{y}" width="{nw:.2f}" '
                f'height="{frame_h}" fill="{fill}" '
                f'rx="{rx}" ry="{ry}"/>\n'
            )

            if vis_width > self._char_width() * 3:
                label = _truncate_text(node.name, vis_width,
                                       self._char_width())
                label_x = x + 3
                label_y = y + frame_h - 4
                svg_frames.append(
                    f'<text class="icicle-frame-label" x="{label_x:.2f}" '
                    f'y="{label_y}">{_escape_html(label)}</text>\n'
                )

            svg_frames.append('</g>\n')

            pct = (node.count / max(self.total_count, 1)) * 100.0
            js_frames_data.append(
                f'{{id:"{node.id}",name:"{_escape_html(node.name)}",'
                f'count:{node.count},depth:{node.depth},'
                f'pct:{pct:.2f},x:{node.x:.2f},w:{node.width:.2f},'
                f'parent:"{node.parent.id if node.parent else ""}"}}'
            )

        parts.extend(svg_frames)

        # Tooltip
        parts.append(
            f'<g id="icicle-tooltip" style="display:none;">\n'
            f'<rect id="icicle-tooltip-bg" x="0" y="0" width="10" height="10" '
            f'rx="3" ry="3" fill="{tooltip_bg}" opacity="0.9"/>\n'
            f'<text id="icicle-tooltip-text" x="5" y="14" '
            f'fill="{tooltip_color}" font-size="{tooltip_size}px" '
            f'font-family="{cfg.font_family}"></text>\n'
            f'</g>\n'
        )

        # Legend
        legend_y = h - cfg.pad_bottom + 2
        leg_text = (
            "Icicle graph: root at top, children below. "
            "Width ~ relative count. Hover for details, click to zoom."
        )
        parts.append(
            f'<text x="{w // 2}" y="{legend_y}" text-anchor="middle" '
            f'class="icicle-legend">{_escape_html(leg_text)}</text>\n'
        )

        # JavaScript
        js = self._generate_js(js_frames_data, w, h)
        parts.append(js)

        parts.append(ICICLE_SVG_FOOTER)
        return "".join(parts)

    def _empty_svg(self) -> str:
        cfg = self.config
        w = cfg.width
        h = cfg.height
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" '
            f'height="{h}" viewBox="0 0 {w} {h}">\n'
            f'<rect width="100%" height="100%" fill="{cfg.bg_color}"/>\n'
            f'<text x="{w // 2}" y="{h // 2}" text-anchor="middle" '
            f'fill="#999" font-size="16" font-family="{cfg.font_family}">'
            f'No data</text>\n</svg>'
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
            ``<script>`` block.
        """
        cfg = self.config
        search_term = _escape_html(cfg.search)
        frame_h = cfg.frame_height

        js = f'''
<script type="text/javascript"><![CDATA[
var ic_frames = [{','.join(frames_data)}];
var ic_map = {{}};
var ic_zoom_id = null;
var ic_total = {self.total_count};
var ic_width = {width};
var ic_chw = {self._char_width():.2f};
var ic_fh = {frame_h};
var ic_search = "{search_term}";

(function() {{
    for (var i = 0; i < ic_frames.length; i++) {{
        var f = ic_frames[i];
        ic_map[f.id] = f;
    }}
    for (var i = 0; i < ic_frames.length; i++) {{
        var f = ic_frames[i];
        if (f.parent && ic_map[f.parent]) {{
            if (!ic_map[f.parent].children) ic_map[f.parent].children = [];
            ic_map[f.parent].children.push(f);
        }}
    }}
    if (ic_search) {{
        ic_apply_search(ic_search);
    }}
}})();

function ic_show_tooltip(event, id) {{
    var f = ic_map[id];
    if (!f) return;
    var tip = document.getElementById('icicle-tooltip');
    var tipText = document.getElementById('icicle-tooltip-text');
    var tipBg = document.getElementById('icicle-tooltip-bg');
    if (!tip || !tipText) return;
    var pct = (f.count / ic_total * 100).toFixed(2);
    var text = f.name + ' \\u2014 ' + f.count + ' (' + pct + '%)';
    if (f.parent && ic_map[f.parent]) {{
        text = f.name + ' \\u2190 ' + ic_map[f.parent].name + ' \\u2014 ' + f.count + ' (' + pct + '%)';
    }}
    tipText.textContent = text;
    var bbox = tipText.getBBox();
    var pad = 8;
    tipBg.setAttribute('x', 0);
    tipBg.setAttribute('y', 0);
    tipBg.setAttribute('width', bbox.width + pad * 2);
    tipBg.setAttribute('height', bbox.height + pad);
    var svg = document.querySelector('svg');
    var rect = svg.getBoundingClientRect();
    var mx = event.clientX - rect.left;
    var my = event.clientY - rect.top;
    var tx = mx + 12;
    var ty = my - 30;
    if (tx + bbox.width + pad * 2 > ic_width) {{
        tx = mx - bbox.width - pad * 2 - 12;
    }}
    if (ty < 0) ty = my + 12;
    tip.setAttribute('transform', 'translate(' + tx + ',' + ty + ')');
    tip.style.display = 'block';
}}

function ic_hide_tooltip() {{
    var tip = document.getElementById('icicle-tooltip');
    if (tip) tip.style.display = 'none';
}}

function ic_zoom(id) {{
    var f = ic_map[id];
    if (!f) return;
    ic_zoom_id = id;
    var visible = {{}};
    var queue = [id];
    visible[id] = true;
    while (queue.length > 0) {{
        var cur = queue.shift();
        var node = ic_map[cur];
        if (node && node.children) {{
            for (var i = 0; i < node.children.length; i++) {{
                var cid = node.children[i].id;
                visible[cid] = true;
                queue.push(cid);
            }}
        }}
    }}
    var zoomWidth = f.w;
    var zoomX = f.x;
    for (var i = 0; i < ic_frames.length; i++) {{
        var frame = ic_frames[i];
        var el = document.getElementById(frame.id);
        if (!el) continue;
        if (visible[frame.id]) {{
            el.style.display = '';
            var rect = el.querySelector('rect');
            var text = el.querySelector('text');
            if (rect) {{
                var newX = (frame.x - zoomX) / zoomWidth * ic_width;
                var newW = frame.w / zoomWidth * ic_width;
                rect.setAttribute('x', newX);
                rect.setAttribute('width', Math.max(newW, 1));
            }}
            if (text) {{
                var newX2 = (frame.x - zoomX) / zoomWidth * ic_width + 3;
                text.setAttribute('x', newX2);
                var newW2 = frame.w / zoomWidth * ic_width;
                var maxChars = Math.max(1, Math.floor(newW2 / ic_chw));
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
    var resetBtn = document.getElementById('icicle-zoom-reset');
    if (resetBtn) resetBtn.style.display = '';
}}

function ic_reset() {{
    ic_zoom_id = null;
    for (var i = 0; i < ic_frames.length; i++) {{
        var frame = ic_frames[i];
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
            var maxChars = Math.max(1, Math.floor(frame.w / ic_chw));
            var label = frame.name;
            if (label.length > maxChars) {{
                if (maxChars > 3) label = label.substring(0, maxChars - 2) + '..';
                else label = label.substring(0, maxChars);
            }}
            text.textContent = label;
        }}
    }}
    var resetBtn = document.getElementById('icicle-zoom-reset');
    if (resetBtn) resetBtn.style.display = 'none';
}}

function ic_search(term) {{
    ic_apply_search(term);
}}

function ic_apply_search(term) {{
    if (!term) {{
        for (var i = 0; i < ic_frames.length; i++) {{
            var el = document.getElementById(ic_frames[i].id);
            if (el) {{
                var rect = el.querySelector('rect');
                if (rect) rect.classList.remove('icicle-search-highlight');
            }}
        }}
        return;
    }}
    term = term.toLowerCase();
    for (var i = 0; i < ic_frames.length; i++) {{
        var frame = ic_frames[i];
        var el = document.getElementById(frame.id);
        if (!el) continue;
        var rect = el.querySelector('rect');
        if (!rect) continue;
        if (frame.name.toLowerCase().indexOf(term) >= 0) {{
            rect.classList.add('icicle-search-highlight');
        }} else {{
            rect.classList.remove('icicle-search-highlight');
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
# Convenience functions
# ---------------------------------------------------------------------------


def generate_icicle(
    stacks: List[Tuple[List[str], int]],
    output: str = "icicle.svg",
    title: str = "Icicle Graph",
    colors: str = "mem",
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    font_size: int = DEFAULT_FONT_SIZE,
    **kwargs,
) -> str:
    """Convenience function to generate an icicle graph from stack data.

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
        Additional :class:`IcicleGraphConfig` fields.

    Returns
    -------
    str
        Generated SVG content.
    """
    config = IcicleGraphConfig(
        width=width,
        height=height,
        font_size=font_size,
        colors=colors,
        title=title,
        **kwargs,
    )
    ig = IcicleGraph(config)
    ig.load_stacks(stacks)
    return ig.save_svg(output)


def generate_memory_profile(
    stacks: List[Tuple[List[str], int]],
    output: str = "memory_profile.svg",
    title: str = "Memory Profile",
    **kwargs,
) -> str:
    """Generate a memory profile visualisation (icicle graph with 'mem' scheme).

    Parameters
    ----------
    stacks : list of (list of str, int)
        Stack traces with allocation counts/bytes.
    output : str
        Output SVG file path.
    title : str
        Graph title.
    **kwargs
        Additional :class:`IcicleGraphConfig` fields.

    Returns
    -------
    str
        Generated SVG content.
    """
    return generate_icicle(
        stacks,
        output=output,
        title=title,
        colors="mem",
        count_label="bytes",
        **kwargs,
    )


def generate_allocation_profile(
    stacks: List[Tuple[List[str], int]],
    output: str = "alloc_profile.svg",
    title: str = "Allocation Profile",
    **kwargs,
) -> str:
    """Generate an allocation profile visualisation (icicle graph with 'alloc' scheme).

    Parameters
    ----------
    stacks : list of (list of str, int)
        Stack traces with allocation counts.
    output : str
        Output SVG file path.
    title : str
        Graph title.
    **kwargs
        Additional :class:`IcicleGraphConfig` fields.

    Returns
    -------
    str
        Generated SVG content.
    """
    return generate_icicle(
        stacks,
        output=output,
        title=title,
        colors="alloc",
        count_label="allocations",
        **kwargs,
    )


# ===========================================================================
# CLI
# ===========================================================================


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate interactive SVG icicle graphs from profiling data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              %(prog)s -i collapsed.txt -o icicle.svg
              %(prog)s -i collapsed.txt --title "Memory" --colors mem
              %(prog)s -i collapsed.txt --colors pastel --rounded-corners
        """),
    )

    parser.add_argument(
        "--input", "-i", type=str, required=True,
        help="Input file (collapsed stack format)"
    )
    parser.add_argument(
        "--output", "-o", type=str, default="icicle.svg",
        help="Output SVG file (default: icicle.svg)"
    )

    # Appearance
    parser.add_argument(
        "--title", type=str, default="Icicle Graph",
        help="Graph title (default: Icicle Graph)"
    )
    parser.add_argument(
        "--subtitle", type=str, default="",
        help="Optional subtitle"
    )
    parser.add_argument(
        "--colors", type=str, default="mem",
        choices=ICICLE_SCHEMES,
        help=f"Colour scheme (default: mem). Choices: {', '.join(ICICLE_SCHEMES)}"
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
    parser.add_argument(
        "--count-label", type=str, default="bytes",
        help="Label for count axis (default: bytes)"
    )

    # Options
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
        "--rounded-corners", action="store_true", default=True,
        help="Apply rounded corners to frames (default: True)"
    )
    parser.add_argument(
        "--no-rounded-corners", action="store_false", dest="rounded_corners",
        help="Use sharp corners"
    )
    parser.add_argument(
        "--show-root", action="store_true",
        help="Display the root node as a frame"
    )
    parser.add_argument(
        "--memory-profile", action="store_true",
        help="Shortcut for memory profile (--colors mem --count-label bytes)"
    )
    parser.add_argument(
        "--alloc-profile", action="store_true",
        help="Shortcut for allocation profile (--colors alloc --count-label allocations)"
    )
    parser.add_argument(
        "--version", action="version",
        version=f"%(prog)s {VERSION}"
    )

    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for icicle graph generation.

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

    # Apply shortcuts
    colors = args.colors
    count_label = args.count_label
    if args.memory_profile:
        colors = "mem"
        count_label = "bytes"
    elif args.alloc_profile:
        colors = "alloc"
        count_label = "allocations"

    config = IcicleGraphConfig(
        width=args.width,
        height=args.height,
        font_size=args.font_size,
        font_family=args.font_family,
        colors=colors,
        bg_color=args.bg_color,
        title=args.title,
        subtitle=args.subtitle,
        min_frame_width=args.min_frame_width,
        frame_height=args.frame_height,
        sort_by_count=args.sort_by_count,
        reverse=args.reverse,
        search=args.search,
        count_label=count_label,
        rounded_corners=args.rounded_corners,
        show_root=args.show_root,
    )

    ig = IcicleGraph(config)

    try:
        ig.load_collapsed_file(args.input)
    except FileNotFoundError:
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error parsing input: {e}", file=sys.stderr)
        return 1

    if ig.total_count == 0:
        print("warning: no samples found in input", file=sys.stderr)

    try:
        ig.save_svg(args.output)
        print(f"Wrote icicle graph to {args.output} "
              f"({ig.total_count:,} {count_label}, "
              f"{len(ig.all_nodes)} frames)")
    except Exception as e:
        print(f"error writing SVG: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())