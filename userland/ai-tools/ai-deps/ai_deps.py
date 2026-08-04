#!/usr/bin/env python3
"""
AI-Deps: AI-Powered Dependency Analyzer for Projects.

Analyzes source code to build dependency graphs, detect circular dependencies,
find unused dependencies, and generate visualizations in multiple formats.

Supports Python, JavaScript/TypeScript, Java, Go, Rust, and other languages.

Usage:
    python ai_deps.py analyze --path /path/to/project
    python ai_deps.py analyze --path /path/to/project --format mermaid
    python ai_deps.py analyze --path /path/to/project --depth 3
    python ai_deps.py detect-circular --path /path/to/project
    python ai_deps.py find-unused --path /path/to/project
    python ai_deps.py report --path /path/to/project --output report.html
"""

from __future__ import annotations

import argparse
import ast
import csv
import enum
import fnmatch
import html
import importlib.util
import itertools
import json
import logging
import os
import re
import sys
import textwrap
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    Generic,
    Iterable,
    Iterator,
    List,
    Match,
    Optional,
    Sequence,
    Set,
    Tuple,
    TypeVar,
    Union,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("ai_deps")
_log_initialized = False


def _setup_logging(verbose: bool = False) -> None:
    """Configure the ai_deps logger with a stream handler and formatter.

    Args:
        verbose: If True, set log level to DEBUG; otherwise INFO.
    """
    global _log_initialized
    if _log_initialized:
        return
    handler = logging.StreamHandler(sys.stderr)
    fmt = logging.Formatter("%(levelname)-8s | %(name)s | %(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    _log_initialized = True


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

__version__ = "1.0.0"
__author__ = "AI-Deps Team"
__description__ = "AI-Powered Dependency Analyzer for Multi-Language Projects"


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------


class AiDepsError(Exception):
    """Base exception for all ai-deps errors."""

    pass


class ConfigError(AiDepsError):
    """Raised when there is a problem with configuration."""

    pass


class ParseError(AiDepsError):
    """Raised when a source file cannot be parsed."""

    pass


class GraphError(AiDepsError):
    """Raised when an operation on the dependency graph fails."""

    pass


class ReportError(AiDepsError):
    """Raised when report generation fails."""

    pass


# ---------------------------------------------------------------------------
# Type Aliases
# ---------------------------------------------------------------------------

NodeId = str
"""Unique identifier for a node in the dependency graph (typically a module path)."""

EdgeWeight = int
"""Weight of an edge, representing the number of import occurrences."""

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Config Management
# ---------------------------------------------------------------------------


@dataclass
class AiDepsConfig:
    """Configuration for the dependency analyzer.

    Attributes:
        project_path: Root path of the project to analyze.
        depth: Maximum depth for dependency traversal (0 = unlimited).
        exclude_patterns: Glob patterns for files/directories to exclude.
        include_patterns: Glob patterns for files to include (empty = all).
        language: Force a specific language (None = auto-detect).
        follow_links: Whether to follow symbolic links.
        ignore_errors: Whether to ignore parse errors and continue.
        output_format: Output format for visualization (mermaid, dot, json, html).
        output_file: Path to write output (None = stdout).
        verbose: Enable verbose logging.
        config_file: Path to a JSON/YAML config file.
        cache_results: Whether to cache analysis results.
        cache_dir: Directory for cache files.
        show_progress: Whether to show progress bars.
        max_file_size: Maximum file size in bytes to analyze (0 = unlimited).
        alias: Package aliases for resolving imports.
    """

    project_path: Path = Path(".")
    depth: int = 0
    exclude_patterns: List[str] = field(default_factory=lambda: [
        "node_modules/**",
        ".git/**",
        "__pycache__/**",
        "*.pyc",
        "*.pyo",
        ".tox/**",
        ".venv/**",
        "venv/**",
        "env/**",
        ".env/**",
        "dist/**",
        "build/**",
        "*.egg-info/**",
        ".mypy_cache/**",
        ".pytest_cache/**",
        ".coverage/**",
        "htmlcov/**",
        ".next/**",
        ".nuxt/**",
        "target/**",
        "vendor/**",
        ".idea/**",
        ".vscode/**",
        "*.min.js",
        "*.bundle.js",
        "*.bundle.min.js",
    ])
    include_patterns: List[str] = field(default_factory=list)
    language: Optional[str] = None
    follow_links: bool = False
    ignore_errors: bool = True
    output_format: str = "json"
    output_file: Optional[str] = None
    verbose: bool = False
    config_file: Optional[str] = None
    cache_results: bool = False
    cache_dir: Optional[str] = None
    show_progress: bool = False
    max_file_size: int = 1024 * 1024  # 1 MB
    alias: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate config values after initialization."""
        if isinstance(self.project_path, str):
            self.project_path = Path(self.project_path)
        if self.depth < 0:
            raise ConfigError(f"depth must be >= 0, got {self.depth}")
        valid_formats = {"mermaid", "dot", "json", "html", "csv", "text"}
        if self.output_format not in valid_formats:
            raise ConfigError(
                f"output_format must be one of {valid_formats}, "
                f"got '{self.output_format}'"
            )
        if self.language is not None:
            valid_languages = {
                "python", "javascript", "typescript", "js", "ts",
                "java", "go", "rust", "c", "cpp", "ruby", "php",
            }
            lang_normalized = self.language.lower().replace("-", "").replace("_", "")
            if lang_normalized not in valid_languages:
                logger.warning(
                    "Language '%s' may not be fully supported. "
                    "Supported: %s",
                    self.language,
                    ", ".join(sorted(valid_languages)),
                )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AiDepsConfig":
        """Create a config from a dictionary, ignoring unknown keys.

        Args:
            data: Dictionary of configuration values.

        Returns:
            An AiDepsConfig instance.

        Raises:
            ConfigError: If required values are missing or invalid.
        """
        valid_field_names = {f.name for f in fields(cls)}
        filtered = {}
        for key, value in data.items():
            if key in valid_field_names:
                filtered[key] = value
            else:
                logger.debug("Ignoring unknown config key: %s", key)
        return cls(**filtered)

    @classmethod
    def from_json(cls, path: Union[str, Path]) -> "AiDepsConfig":
        """Load configuration from a JSON file.

        Args:
            path: Path to the JSON config file.

        Returns:
            An AiDepsConfig instance.

        Raises:
            ConfigError: If the file cannot be read or parsed.
        """
        path = Path(path)
        if not path.exists():
            raise ConfigError(f"Config file not found: {path}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            raise ConfigError(f"Failed to parse config file: {exc}") from exc
        return cls.from_dict(data)

    def merge(self, other: "AiDepsConfig") -> "AiDepsConfig":
        """Merge another config into this one (other values take precedence).

        Args:
            other: Config whose values override this instance's values.

        Returns:
            A new merged AiDepsConfig instance.
        """
        merged_data = {}
        for f in fields(self):
            self_val = getattr(self, f.name)
            other_val = getattr(other, f.name, None)
            if other_val is not None and other_val != f.default:
                merged_data[f.name] = other_val
            else:
                merged_data[f.name] = self_val
        return AiDepsConfig(**merged_data)


# ---------------------------------------------------------------------------
# DepGraph: Directed Graph Representation
# ---------------------------------------------------------------------------


@dataclass
class Edge:
    """Represents a directed edge in the dependency graph.

    Attributes:
        source: Source node ID.
        target: Target node ID.
        weight: Number of import occurrences.
        metadata: Arbitrary metadata attached to the edge.
    """
    source: NodeId
    target: NodeId
    weight: EdgeWeight = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        return hash((self.source, self.target))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Edge):
            return NotImplemented
        return self.source == other.source and self.target == other.target


@dataclass
class Node:
    """Represents a node in the dependency graph.

    Attributes:
        id: Unique identifier for the node (module path).
        file_path: Optional filesystem path to the source file.
        node_type: Type of node (module, file, package, external).
        language: Programming language of the source file.
        size: Size of the source file in bytes.
        metadata: Arbitrary metadata attached to the node.
    """
    id: NodeId
    file_path: Optional[str] = None
    node_type: str = "module"
    language: Optional[str] = None
    size: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Node):
            return NotImplemented
        return self.id == other.id


class DepGraph:
    """A directed graph representing dependencies between modules.

    Supports weighted edges, node metadata, and graph traversal operations.

    Attributes:
        nodes: Dictionary mapping node IDs to Node objects.
        edges: Set of Edge objects in the graph.
        _adjacency: Internal adjacency list for efficient traversal.
        _reverse_adj: Internal reverse adjacency list.
    """

    def __init__(self) -> None:
        """Initialize an empty dependency graph."""
        self.nodes: Dict[NodeId, Node] = {}
        self.edges: Set[Edge] = set()
        self._adjacency: Dict[NodeId, Set[NodeId]] = defaultdict(set)
        self._reverse_adj: Dict[NodeId, Set[NodeId]] = defaultdict(set)

    def add_node(self, node: Node) -> None:
        """Add a node to the graph. If the node already exists, update it.

        Args:
            node: The Node to add or update.
        """
        if node.id in self.nodes:
            existing = self.nodes[node.id]
            if node.file_path and not existing.file_path:
                existing.file_path = node.file_path
            if node.language and not existing.language:
                existing.language = node.language
            if node.node_type != "module" and existing.node_type == "module":
                existing.node_type = node.node_type
            if node.size > 0 and existing.size == 0:
                existing.size = node.size
            if node.metadata:
                existing.metadata.update(node.metadata)
        else:
            self.nodes[node.id] = node

    def get_node(self, node_id: NodeId) -> Optional[Node]:
        """Get a node by its ID.

        Args:
            node_id: The ID of the node to retrieve.

        Returns:
            The Node if found, or None.
        """
        return self.nodes.get(node_id)

    def add_edge(self, edge: Edge) -> None:
        """Add a directed edge to the graph.

        If the edge already exists, its weight is incremented.

        Args:
            edge: The Edge to add.
        """
        if edge in self.edges:
            existing = next(e for e in self.edges if e == edge)
            existing.weight += edge.weight
            if edge.metadata:
                existing.metadata.update(edge.metadata)
        else:
            self.edges.add(edge)
            self._adjacency[edge.source].add(edge.target)
            self._reverse_adj[edge.target].add(edge.source)

        if edge.source not in self.nodes:
            self.add_node(Node(id=edge.source))
        if edge.target not in self.nodes:
            self.add_node(Node(id=edge.target))

    def add_dependency(
        self,
        source: NodeId,
        target: NodeId,
        weight: int = 1,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Convenience method to add a dependency edge.

        Args:
            source: Source module ID.
            target: Target module ID (the dependency).
            weight: Number of import occurrences.
            metadata: Optional metadata for the edge.
        """
        self.add_edge(
            Edge(
                source=source,
                target=target,
                weight=weight,
                metadata=metadata or {},
            )
        )

    def remove_node(self, node_id: NodeId) -> None:
        """Remove a node and all its incident edges.

        Args:
            node_id: The ID of the node to remove.
        """
        self.nodes.pop(node_id, None)
        edges_to_remove = {
            e for e in self.edges
            if e.source == node_id or e.target == node_id
        }
        self.edges -= edges_to_remove
        self._adjacency.pop(node_id, None)
        self._reverse_adj.pop(node_id, None)
        for adj in self._adjacency.values():
            adj.discard(node_id)
        for adj in self._reverse_adj.values():
            adj.discard(node_id)

    def remove_edge(self, source: NodeId, target: NodeId) -> None:
        """Remove the edge between source and target.

        Args:
            source: Source node ID.
            target: Target node ID.
        """
        edge = Edge(source=source, target=target)
        self.edges.discard(edge)
        self._adjacency.get(source, set()).discard(target)
        self._reverse_adj.get(target, set()).discard(source)

    def successors(self, node_id: NodeId) -> Set[NodeId]:
        """Get all direct successors (dependencies) of a node.

        Args:
            node_id: The node to query.

        Returns:
            Set of successor node IDs.
        """
        return self._adjacency.get(node_id, set()).copy()

    def predecessors(self, node_id: NodeId) -> Set[NodeId]:
        """Get all direct predecessors (dependents) of a node.

        Args:
            node_id: The node to query.

        Returns:
            Set of predecessor node IDs.
        """
        return self._reverse_adj.get(node_id, set()).copy()

    def has_node(self, node_id: NodeId) -> bool:
        """Check if a node exists in the graph.

        Args:
            node_id: The node ID to check.

        Returns:
            True if the node exists, False otherwise.
        """
        return node_id in self.nodes

    def has_edge(self, source: NodeId, target: NodeId) -> bool:
        """Check if an edge exists between source and target.

        Args:
            source: Source node ID.
            target: Target node ID.

        Returns:
            True if the edge exists, False otherwise.
        """
        return Edge(source=source, target=target) in self.edges

    def node_count(self) -> int:
        """Return the number of nodes in the graph.

        Returns:
            Node count.
        """
        return len(self.nodes)

    def edge_count(self) -> int:
        """Return the number of edges in the graph.

        Returns:
            Edge count.
        """
        return len(self.edges)

    def is_empty(self) -> bool:
        """Check if the graph has no nodes.

        Returns:
            True if the graph is empty, False otherwise.
        """
        return len(self.nodes) == 0

    def subgraph(self, node_ids: Set[NodeId]) -> "DepGraph":
        """Extract a subgraph containing only the specified nodes and edges between them.

        Args:
            node_ids: Set of node IDs to include in the subgraph.

        Returns:
            A new DepGraph containing only the given nodes.
        """
        sub = DepGraph()
        for nid in node_ids:
            if nid in self.nodes:
                sub.add_node(self.nodes[nid])
        for edge in self.edges:
            if edge.source in node_ids and edge.target in node_ids:
                sub.add_edge(edge)
        return sub

    def transitive_reduction(self) -> "DepGraph":
        """Compute the transitive reduction of the graph.

        Returns:
            A new DepGraph with transitive edges removed.

        Note:
            This is an O(n^3) operation and should be used sparingly on large graphs.
        """
        reduced = DepGraph()
        for node in self.nodes.values():
            reduced.add_node(node)
        for edge in self.edges:
            reduced.add_edge(edge)

        # For each edge, check if there's an alternative path
        for edge in list(reduced.edges):
            # BFS/DFS from source to target, excluding the direct edge
            visited: Set[NodeId] = set()
            queue: deque[NodeId] = deque()
            queue.append(edge.source)
            visited.add(edge.source)
            while queue:
                current = queue.popleft()
                for neighbor in reduced._adjacency.get(current, set()):
                    if neighbor == edge.target and current != edge.source:
                        # Found alternative path
                        reduced.remove_edge(edge.source, edge.target)
                        queue.clear()
                        break
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)
        return reduced

    def topological_sort(self) -> List[NodeId]:
        """Perform a topological sort of the graph.

        Returns:
            List of node IDs in topological order.

        Raises:
            GraphError: If the graph contains a cycle.
        """
        in_degree: Dict[NodeId, int] = {}
        for node_id in self.nodes:
            in_degree[node_id] = len(self._reverse_adj.get(node_id, set()))

        queue: deque[NodeId] = deque()
        for node_id, degree in in_degree.items():
            if degree == 0:
                queue.append(node_id)

        result: List[NodeId] = []
        while queue:
            node_id = queue.popleft()
            result.append(node_id)
            for successor in self._adjacency.get(node_id, set()):
                in_degree[successor] -= 1
                if in_degree[successor] == 0:
                    queue.append(successor)

        if len(result) != len(self.nodes):
            raise GraphError(
                "Graph contains a cycle; topological sort is not possible."
            )
        return result

    def bfs(self, start: NodeId) -> Iterator[NodeId]:
        """Traverse the graph in breadth-first order from a start node.

        Args:
            start: The starting node ID.

        Yields:
            Node IDs in BFS order.
        """
        visited: Set[NodeId] = set()
        queue: deque[NodeId] = deque()
        queue.append(start)
        visited.add(start)
        while queue:
            node_id = queue.popleft()
            yield node_id
            for neighbor in self._adjacency.get(node_id, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

    def dfs(self, start: NodeId) -> Iterator[NodeId]:
        """Traverse the graph in depth-first order from a start node.

        Args:
            start: The starting node ID.

        Yields:
            Node IDs in DFS order.
        """
        visited: Set[NodeId] = set()
        stack: List[NodeId] = [start]
        while stack:
            node_id = stack.pop()
            if node_id in visited:
                continue
            visited.add(node_id)
            yield node_id
            for neighbor in self._adjacency.get(node_id, set()):
                if neighbor not in visited:
                    stack.append(neighbor)

    def to_json(self) -> Dict[str, Any]:
        """Serialize the graph to a JSON-compatible dictionary.

        Returns:
            Dictionary representation of the graph.
        """
        return {
            "nodes": [
                {
                    "id": n.id,
                    "file_path": n.file_path,
                    "node_type": n.node_type,
                    "language": n.language,
                    "size": n.size,
                    "metadata": n.metadata,
                }
                for n in self.nodes.values()
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "weight": e.weight,
                    "metadata": e.metadata,
                }
                for e in self.edges
            ],
            "stats": {
                "node_count": self.node_count(),
                "edge_count": self.edge_count(),
            },
        }

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "DepGraph":
        """Deserialize a graph from a JSON-compatible dictionary.

        Args:
            data: Dictionary representation of the graph.

        Returns:
            A DepGraph instance.
        """
        graph = cls()
        for node_data in data.get("nodes", []):
            graph.add_node(Node(**node_data))
        for edge_data in data.get("edges", []):
            graph.add_edge(Edge(**edge_data))
        return graph

    def __repr__(self) -> str:
        return (
            f"DepGraph(nodes={self.node_count()}, edges={self.edge_count()})"
        )

    def __str__(self) -> str:
        return (
            f"Dependency Graph with {self.node_count()} nodes "
            f"and {self.edge_count()} edges"
        )


# ---------------------------------------------------------------------------
# ImportParser: Language-Specific Import Parsers
# ---------------------------------------------------------------------------


class ImportParser:
    """Base parser for extracting import/require statements from source files.

    Each language-specific parser should extend this class and implement
    the ``parse`` method.
    """

    # Language identifier
    language: str = "unknown"

    # File extensions this parser handles
    extensions: Tuple[str, ...] = tuple()

    def __init__(self, config: Optional[AiDepsConfig] = None) -> None:
        """Initialize the parser with optional configuration.

        Args:
            config: Analysis configuration (may contain alias mappings).
        """
        self.config = config or AiDepsConfig()
        self._stats: Dict[str, Any] = {
            "files_parsed": 0,
            "files_failed": 0,
            "imports_found": 0,
            "errors": [],
        }

    def parse(self, file_path: Path) -> List[Tuple[str, int]]:
        """Parse a source file and extract import statements.

        Args:
            file_path: Path to the source file.

        Returns:
            List of (module_name, line_number) tuples.

        Raises:
            ParseError: If the file cannot be parsed.

        This method must be overridden by subclasses.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement parse()"
        )

    def can_parse(self, file_path: Path) -> bool:
        """Check if this parser can handle the given file.

        Args:
            file_path: Path to the file to check.

        Returns:
            True if the file extension matches this parser.
        """
        return file_path.suffix.lower() in self.extensions

    def stats(self) -> Dict[str, Any]:
        """Return parser statistics.

        Returns:
            Dictionary with parsing statistics.
        """
        return dict(self._stats)

    def resolve_alias(self, module_name: str) -> str:
        """Resolve a module name through configured aliases.

        Args:
            module_name: The module name to resolve.

        Returns:
            The resolved module name (possibly aliased).
        """
        if module_name in self.config.alias:
            return self.config.alias[module_name]
        # Check for prefix aliases
        for prefix, replacement in self.config.alias.items():
            if module_name.startswith(prefix):
                return replacement + module_name[len(prefix):]
        return module_name


class PythonImportParser(ImportParser):
    """Parser for Python import statements using AST parsing.

    Handles:
    - ``import X``
    - ``from X import Y``
    - ``from X import Y as Z``
    - ``import X as Y``
    - Relative imports (``from . import X``, ``from ..module import X``)
    """

    language = "python"
    extensions = (".py", ".pyi", ".pyx")

    def parse(self, file_path: Path) -> List[Tuple[str, int]]:
        """Parse a Python file for imports using AST.

        Args:
            file_path: Path to the Python source file.

        Returns:
            List of (module_name, line_number) tuples.

        Raises:
            ParseError: If the file cannot be parsed by the AST.
        """
        self._stats["files_parsed"] += 1
        imports: List[Tuple[str, int]] = []

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as exc:
            self._stats["files_failed"] += 1
            err_msg = f"Syntax error in {file_path}: {exc}"
            self._stats["errors"].append(err_msg)
            if not self.config.ignore_errors:
                raise ParseError(err_msg) from exc
            logger.warning("Skipping %s: %s", file_path, exc)
            return imports
        except OSError as exc:
            self._stats["files_failed"] += 1
            err_msg = f"OS error reading {file_path}: {exc}"
            self._stats["errors"].append(err_msg)
            if not self.config.ignore_errors:
                raise ParseError(err_msg) from exc
            logger.warning("Skipping %s: %s", file_path, exc)
            return imports

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = self.resolve_alias(
                        alias.name.split(".")[0]
                    )
                    imports.append((module, node.lineno))
                    self._stats["imports_found"] += 1
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                # Resolve relative imports
                level = node.level or 0
                if level > 0:
                    # Relative import - resolve relative to the file's package
                    parts = file_path.resolve().parts
                    try:
                        # Find the package root
                        pkg_idx = -1
                        for i, part in enumerate(parts):
                            if part == "__init__.py" or part.endswith(".py"):
                                continue
                            if part in ("site-packages", "lib", "Lib"):
                                continue
                        # Simplified: use the module name directly
                        relative_parts = node.module.split(".")
                        if level > 0:
                            # Go up 'level' directories
                            base = Path(*parts[:-1])  # file's directory
                            for _ in range(level - 1):
                                base = base.parent
                            resolved_parts = list(base.parts)
                            # Remove things that look like package roots
                            resolved_parts.extend(relative_parts)
                            module = ".".join(
                                p for p in resolved_parts
                                if p not in (
                                    "site-packages", "lib", "Lib",
                                    "dist-packages",
                                )
                                and not p.endswith(".py")
                            )
                        else:
                            module = node.module
                    except Exception:
                        module = node.module
                else:
                    module = node.module
                module = self.resolve_alias(module.split(".")[0])
                imports.append((module, node.lineno))
                self._stats["imports_found"] += 1

        return imports


class JavaScriptImportParser(ImportParser):
    """Parser for JavaScript/TypeScript import/require statements.

    Handles:
    - ``import X from 'module'``
    - ``import { X } from 'module'``
    - ``import * as X from 'module'``
    - ``const X = require('module')``
    - ``require('module')``
    - ``import('module')`` dynamic imports
    - ``export ... from 'module'`` re-exports
    """

    language = "javascript"
    extensions = (".js", ".jsx", ".mjs", ".cjs")

    _IMPORT_RE = re.compile(
        r"""
        (?:import|export)\s+
        (?:
            (?:[\w*\s{},]*\s+from\s+)?
            ['"]([^'"]+)['"]
        )
        """,
        re.VERBOSE | re.MULTILINE,
    )

    _REQUIRE_RE = re.compile(
        r"""
        (?:require|import)\s*\(\s*['"]([^'"]+)['"]\s*\)
        """,
        re.VERBOSE | re.MULTILINE,
    )

    _DYNAMIC_IMPORT_RE = re.compile(
        r"""
        import\s*\(\s*['"]([^'"]+)['"]\s*\)
        """,
        re.VERBOSE | re.MULTILINE,
    )

    def parse(self, file_path: Path) -> List[Tuple[str, int]]:
        """Parse a JavaScript/TypeScript file for imports.

        Args:
            file_path: Path to the JS/TS source file.

        Returns:
            List of (module_name, line_number) tuples.
        """
        self._stats["files_parsed"] += 1
        imports: List[Tuple[str, int]] = []

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._stats["files_failed"] += 1
            err_msg = f"Error reading {file_path}: {exc}"
            self._stats["errors"].append(err_msg)
            if not self.config.ignore_errors:
                raise ParseError(err_msg) from exc
            logger.warning("Skipping %s: %s", file_path, exc)
            return imports

        lines = source.split("\n")

        for line_no, line in enumerate(lines, 1):
            # Check for static imports/exports
            for match in self._IMPORT_RE.finditer(line):
                module = self.resolve_alias(match.group(1))
                imports.append((module, line_no))
                self._stats["imports_found"] += 1

            # Check for require() calls
            for match in self._REQUIRE_RE.finditer(line):
                module = self.resolve_alias(match.group(1))
                imports.append((module, line_no))
                self._stats["imports_found"] += 1

            # Check for dynamic imports
            for match in self._DYNAMIC_IMPORT_RE.finditer(line):
                module = self.resolve_alias(match.group(1))
                imports.append((module, line_no))
                self._stats["imports_found"] += 1

        return imports


class TypeScriptImportParser(JavaScriptImportParser):
    """Parser for TypeScript import statements.

    Extends JavaScriptImportParser to handle TypeScript-specific syntax
    like type-only imports and path aliases.
    """

    language = "typescript"
    extensions = (".ts", ".tsx", ".mts", ".cts")

    _TYPE_IMPORT_RE = re.compile(
        r"""
        (?:import\s+(?:type\s+)?\{[^}]*\}\s+from\s+|
         import\s+type\s+\{[^}]*\}\s+from\s+|
         import\s+type\s+\w+\s+from\s+)
        ['"]([^'"]+)['"]
        """,
        re.VERBOSE | re.MULTILINE,
    )

    def parse(self, file_path: Path) -> List[Tuple[str, int]]:
        """Parse a TypeScript file for imports.

        Args:
            file_path: Path to the TypeScript source file.

        Returns:
            List of (module_name, line_number) tuples.
        """
        # Use parent class parsing first
        imports = super().parse(file_path)

        # Also parse type-only imports with the specific regex
        if not self._stats["files_failed"]:
            try:
                source = file_path.read_text(encoding="utf-8", errors="replace")
                for match in self._TYPE_IMPORT_RE.finditer(source):
                    # Find the line number
                    line_no = source[: match.start()].count("\n") + 1
                    module = self.resolve_alias(match.group(1))
                    imports.append((module, line_no))
                    self._stats["imports_found"] += 1
            except OSError:
                pass

        return imports


class JavaImportParser(ImportParser):
    """Parser for Java import statements.

    Handles:
    - ``import com.example.Module;``
    - ``import static com.example.Module.method;``
    - ``import com.example.*;``
    """

    language = "java"
    extensions = (".java",)

    _IMPORT_RE = re.compile(
        r"""
        ^\s*import\s+
        (?:static\s+)?
        ([\w.*]+)
        \s*;\s*
        """,
        re.VERBOSE | re.MULTILINE,
    )

    def parse(self, file_path: Path) -> List[Tuple[str, int]]:
        """Parse a Java file for imports.

        Args:
            file_path: Path to the Java source file.

        Returns:
            List of (module_name, line_number) tuples.
        """
        self._stats["files_parsed"] += 1
        imports: List[Tuple[str, int]] = []

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._stats["files_failed"] += 1
            err_msg = f"Error reading {file_path}: {exc}"
            self._stats["errors"].append(err_msg)
            if not self.config.ignore_errors:
                raise ParseError(err_msg) from exc
            logger.warning("Skipping %s: %s", file_path, exc)
            return imports

        for match in self._IMPORT_RE.finditer(source):
            module = match.group(1)
            # Skip star imports for dependency tracking
            if module.endswith(".*"):
                module = module[:-2]
            module = self.resolve_alias(module)
            line_no = source[: match.start()].count("\n") + 1
            imports.append((module, line_no))
            self._stats["imports_found"] += 1

        return imports


class GoImportParser(ImportParser):
    """Parser for Go import statements.

    Handles:
    - ``import "module/path"``
    - ``import alias "module/path"``
    - ``import (\n "pkg1"\n "pkg2"\n )``
    """

    language = "go"
    extensions = (".go",)

    _SINGLE_IMPORT_RE = re.compile(
        r"""
        ^\s*import\s+
        (?:[\w.]+\s+)?
        "([^"]+)"
        """,
        re.VERBOSE | re.MULTILINE,
    )

    _GROUP_IMPORT_RE = re.compile(
        r"""
        import\s*\(\s*
        (.*?)
        \s*\)
        """,
        re.VERBOSE | re.DOTALL,
    )

    _STRING_IN_GROUP_RE = re.compile(r'"([^"]+)"')

    def parse(self, file_path: Path) -> List[Tuple[str, int]]:
        """Parse a Go file for imports.

        Args:
            file_path: Path to the Go source file.

        Returns:
            List of (module_name, line_number) tuples.
        """
        self._stats["files_parsed"] += 1
        imports: List[Tuple[str, int]] = []

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._stats["files_failed"] += 1
            err_msg = f"Error reading {file_path}: {exc}"
            self._stats["errors"].append(err_msg)
            if not self.config.ignore_errors:
                raise ParseError(err_msg) from exc
            logger.warning("Skipping %s: %s", file_path, exc)
            return imports

        lines = source.split("\n")

        # Find single-line imports
        for line_no, line in enumerate(lines, 1):
            match = self._SINGLE_IMPORT_RE.match(line)
            if match:
                module = self.resolve_alias(match.group(1))
                imports.append((module, line_no))
                self._stats["imports_found"] += 1

        # Find grouped imports
        for match in self._GROUP_IMPORT_RE.finditer(source):
            block = match.group(1)
            for str_match in self._STRING_IN_GROUP_RE.finditer(block):
                module = self.resolve_alias(str_match.group(1))
                # Approximate line number
                line_no = source[: match.start() + str_match.start()].count("\n") + 1
                imports.append((module, line_no))
                self._stats["imports_found"] += 1

        return imports


class RustImportParser(ImportParser):
    """Parser for Rust use/import statements.

    Handles:
    - ``use crate::module;``
    - ``use std::collections::HashMap;``
    - ``use module::submodule::Item;``
    - ``extern crate module;``
    - ``mod module;`` (declarations)
    """

    language = "rust"
    extensions = (".rs",)

    _USE_RE = re.compile(
        r"""
        ^\s*use\s+
        (?:pub\s+(?:\([^)]*\)\s+)?)?
        (crate|self|super|[\w:]+)
        (?:::[\w*{}]+)*
        \s*;
        """,
        re.VERBOSE | re.MULTILINE,
    )

    _EXTERN_CRATE_RE = re.compile(
        r"""
        ^\s*extern\s+crate\s+
        ([\w_]+)
        \s*;
        """,
        re.VERBOSE | re.MULTILINE,
    )

    _MOD_DECL_RE = re.compile(
        r"""
        ^\s*(?:pub\s+)?mod\s+
        ([\w_]+)
        \s*;
        """,
        re.VERBOSE | re.MULTILINE,
    )

    def parse(self, file_path: Path) -> List[Tuple[str, int]]:
        """Parse a Rust file for imports.

        Args:
            file_path: Path to the Rust source file.

        Returns:
            List of (module_name, line_number) tuples.
        """
        self._stats["files_parsed"] += 1
        imports: List[Tuple[str, int]] = []

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._stats["files_failed"] += 1
            err_msg = f"Error reading {file_path}: {exc}"
            self._stats["errors"].append(err_msg)
            if not self.config.ignore_errors:
                raise ParseError(err_msg) from exc
            logger.warning("Skipping %s: %s", file_path, exc)
            return imports

        lines = source.split("\n")

        for line_no, line in enumerate(lines, 1):
            # use statements
            use_match = self._USE_RE.match(line)
            if use_match:
                module_path = use_match.group(1)
                # Extract the top-level module
                module = module_path.split("::")[0]
                if module in ("crate", "self", "super"):
                    continue  # Skip self-references
                module = self.resolve_alias(module)
                imports.append((module, line_no))
                self._stats["imports_found"] += 1

            # extern crate
            ext_match = self._EXTERN_CRATE_RE.match(line)
            if ext_match:
                module = self.resolve_alias(ext_match.group(1))
                imports.append((module, line_no))
                self._stats["imports_found"] += 1

            # mod declarations
            mod_match = self._MOD_DECL_RE.match(line)
            if mod_match:
                module = self.resolve_alias(mod_match.group(1))
                imports.append((module, line_no))
                self._stats["imports_found"] += 1

        return imports


class CppImportParser(ImportParser):
    """Parser for C/C++ #include directives.

    Handles:
    - ``#include <header>`` (system headers)
    - ``#include "header"`` (local headers)
    """

    language = "cpp"
    extensions = (".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx", ".hh")

    _INCLUDE_RE = re.compile(
        r"""
        ^\s*#\s*include\s+
        (?:<([^>]+)>|"([^"]+)")
        """,
        re.VERBOSE | re.MULTILINE,
    )

    def parse(self, file_path: Path) -> List[Tuple[str, int]]:
        """Parse a C/C++ file for includes.

        Args:
            file_path: Path to the C/C++ source file.

        Returns:
            List of (module_name, line_number) tuples.
        """
        self._stats["files_parsed"] += 1
        imports: List[Tuple[str, int]] = []

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._stats["files_failed"] += 1
            err_msg = f"Error reading {file_path}: {exc}"
            self._stats["errors"].append(err_msg)
            if not self.config.ignore_errors:
                raise ParseError(err_msg) from exc
            logger.warning("Skipping %s: %s", file_path, exc)
            return imports

        for match in self._INCLUDE_RE.finditer(source):
            module = match.group(1) or match.group(2)
            module = self.resolve_alias(module)
            line_no = source[: match.start()].count("\n") + 1
            imports.append((module, line_no))
            self._stats["imports_found"] += 1

        return imports


class RubyImportParser(ImportParser):
    """Parser for Ruby require/include statements.

    Handles:
    - ``require 'module'``
    - ``require_relative 'module'``
    - ``include Module``
    - ``extend Module``
    - ``load 'module'``
    """

    language = "ruby"
    extensions = (".rb", ".rake")

    _REQUIRE_RE = re.compile(
        r"""
        ^\s*
        (?:require|require_relative|load|autoload)\s+
        ['"]([^'"]+)['"]
        """,
        re.VERBOSE | re.MULTILINE,
    )

    def parse(self, file_path: Path) -> List[Tuple[str, int]]:
        """Parse a Ruby file for requires.

        Args:
            file_path: Path to the Ruby source file.

        Returns:
            List of (module_name, line_number) tuples.
        """
        self._stats["files_parsed"] += 1
        imports: List[Tuple[str, int]] = []

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._stats["files_failed"] += 1
            err_msg = f"Error reading {file_path}: {exc}"
            self._stats["errors"].append(err_msg)
            if not self.config.ignore_errors:
                raise ParseError(err_msg) from exc
            logger.warning("Skipping %s: %s", file_path, exc)
            return imports

        for match in self._REQUIRE_RE.finditer(source):
            module = self.resolve_alias(match.group(1))
            line_no = source[: match.start()].count("\n") + 1
            imports.append((module, line_no))
            self._stats["imports_found"] += 1

        return imports


class PhpImportParser(ImportParser):
    """Parser for PHP use/require/include statements.

    Handles:
    - ``use Namespace\\Class;``
    - ``require 'file.php';``
    - ``require_once 'file.php';``
    - ``include 'file.php';``
    - ``include_once 'file.php';``
    """

    language = "php"
    extensions = (".php", ".phtml", ".php3", ".php4", ".php5", ".phps")

    _USE_RE = re.compile(
        r"""
        ^\s*use\s+
        ([\w\\\\]+)
        (?:\s+as\s+\w+)?
        \s*;
        """,
        re.VERBOSE | re.MULTILINE,
    )

    _INCLUDE_RE = re.compile(
        r"""
        (?:require|require_once|include|include_once)\s*
        \(?\s*['"]([^'"]+)['"]\s*\)?
        """,
        re.VERBOSE | re.MULTILINE,
    )

    def parse(self, file_path: Path) -> List[Tuple[str, int]]:
        """Parse a PHP file for imports.

        Args:
            file_path: Path to the PHP source file.

        Returns:
            List of (module_name, line_number) tuples.
        """
        self._stats["files_parsed"] += 1
        imports: List[Tuple[str, int]] = []

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._stats["files_failed"] += 1
            err_msg = f"Error reading {file_path}: {exc}"
            self._stats["errors"].append(err_msg)
            if not self.config.ignore_errors:
                raise ParseError(err_msg) from exc
            logger.warning("Skipping %s: %s", file_path, exc)
            return imports

        lines = source.split("\n")

        for line_no, line in enumerate(lines, 1):
            use_match = self._USE_RE.match(line)
            if use_match:
                module = use_match.group(1).replace("\\\\", ".")
                module = self.resolve_alias(module)
                imports.append((module, line_no))
                self._stats["imports_found"] += 1

            inc_match = self._INCLUDE_RE.search(line)
            if inc_match:
                module = self.resolve_alias(inc_match.group(1))
                imports.append((module, line_no))
                self._stats["imports_found"] += 1

        return imports


def get_parser_for_file(
    file_path: Path, config: Optional[AiDepsConfig] = None
) -> Optional[ImportParser]:
    """Get the appropriate import parser for a given file.

    Args:
        file_path: Path to the source file.
        config: Optional analysis configuration.

    Returns:
        An ImportParser instance if a matching parser is found, None otherwise.
    """
    parsers: List[ImportParser] = [
        PythonImportParser(config),
        JavaScriptImportParser(config),
        TypeScriptImportParser(config),
        JavaImportParser(config),
        GoImportParser(config),
        RustImportParser(config),
        CppImportParser(config),
        RubyImportParser(config),
        PhpImportParser(config),
    ]
    for parser in parsers:
        if parser.can_parse(file_path):
            return parser
    return None


# ---------------------------------------------------------------------------
# GraphBuilder: Builds Dependency Graph from File Analysis
# ---------------------------------------------------------------------------


class GraphBuilder:
    """Builds a DepGraph by analyzing source files in a project directory.

    The builder walks the project tree, identifies source files, parses
    imports using the appropriate language parser, and assembles the
    dependency graph.

    Attributes:
        config: Configuration for the analysis.
        graph: The constructed dependency graph.
        parsers: Dictionary mapping file extensions to parser instances.
        _file_map: Mapping from node IDs to file paths.
    """

    def __init__(self, config: Optional[AiDepsConfig] = None) -> None:
        """Initialize the graph builder.

        Args:
            config: Configuration for the analysis.
        """
        self.config = config or AiDepsConfig()
        self.graph = DepGraph()
        self._parsers: Dict[str, ImportParser] = {}
        self._file_map: Dict[NodeId, Path] = {}
        self._all_imports: Dict[NodeId, List[Tuple[str, int]]] = {}
        self._stats: Dict[str, Any] = {
            "total_files": 0,
            "parsed_files": 0,
            "skipped_files": 0,
            "external_deps": 0,
            "internal_deps": 0,
            "total_imports": 0,
            "start_time": time.time(),
            "end_time": None,
            "duration_ms": 0,
        }

    def _get_parser(self, file_path: Path) -> Optional[ImportParser]:
        """Get or create a parser for the given file.

        Args:
            file_path: Path to the file to parse.

        Returns:
            An ImportParser instance, or None if no parser is available.
        """
        ext = file_path.suffix.lower()
        if ext not in self._parsers:
            parser = get_parser_for_file(file_path, self.config)
            if parser is not None:
                self._parsers[ext] = parser
        return self._parsers.get(ext)

    def _should_include(self, file_path: Path) -> bool:
        """Check if a file should be included in the analysis.

        Args:
            file_path: Path to the file to check.

        Returns:
            True if the file should be analyzed, False otherwise.
        """
        # Check file size
        if self.config.max_file_size > 0:
            try:
                if file_path.stat().st_size > self.config.max_file_size:
                    return False
            except OSError:
                return False

        # Check include patterns
        if self.config.include_patterns:
            rel_path = str(file_path.relative_to(self.config.project_path))
            for pattern in self.config.include_patterns:
                if fnmatch.fnmatch(rel_path, pattern):
                    return True
            return False

        return True

    def _should_exclude(self, path: Path) -> bool:
        """Check if a path should be excluded from analysis.

        Args:
            path: Path to check.

        Returns:
            True if the path should be excluded, False otherwise.
        """
        rel_path = str(path.relative_to(self.config.project_path))
        for pattern in self.config.exclude_patterns:
            if fnmatch.fnmatch(rel_path, pattern):
                return True
            # Also check if the path is a parent of a pattern
            if pattern.endswith("/**"):
                parent = pattern[:-3]
                if fnmatch.fnmatch(rel_path, parent) or rel_path.startswith(parent):
                    return True
        return False

    def _collect_files(self) -> List[Path]:
        """Collect all source files in the project directory.

        Returns:
            List of file paths to analyze.

        Raises:
            GraphError: If the project path does not exist.
        """
        project_path = self.config.project_path
        if not project_path.exists():
            raise GraphError(f"Project path does not exist: {project_path}")
        if not project_path.is_dir():
            return [project_path] if self._should_include(project_path) else []

        files: List[Path] = []
        for root, dirs, filenames in os.walk(
            str(project_path),
            followlinks=self.config.follow_links,
            topdown=True,
        ):
            root_path = Path(root)

            # Check if this directory should be excluded
            try:
                if self._should_exclude(root_path):
                    dirs.clear()
                    continue
            except (ValueError, OSError):
                dirs.clear()
                continue

            # Filter directories in-place to prevent walking into excluded dirs
            filtered_dirs: List[str] = []
            for d in dirs:
                dir_full = root_path / d
                try:
                    if not self._should_exclude(dir_full):
                        filtered_dirs.append(d)
                except (ValueError, OSError):
                    continue
            dirs[:] = filtered_dirs

            for filename in filenames:
                file_path = root_path / filename
                try:
                    if self._should_include(file_path) and not self._should_exclude(file_path):
                        parser = self._get_parser(file_path)
                        if parser is not None:
                            files.append(file_path)
                except (ValueError, OSError):
                    continue

        self._stats["total_files"] = len(files)
        return files

    def _resolve_module_id(self, file_path: Path, import_name: str) -> str:
        """Resolve an import name to a module ID.

        Handles relative imports, package resolution, and alias mapping.

        Args:
            file_path: The source file path (for relative resolution).
            import_name: The import name as written in source.

        Returns:
            A resolved module ID string.
        """
        # Normalize: replace path separators with dots
        normalized = import_name.replace("/", ".").replace("\\", ".")

        # Check if it's a relative path-like import
        if normalized.startswith(".") or normalized.startswith(".."):
            # Relative import - resolve from the file's directory
            file_dir = file_path.parent
            parts = normalized.split(".")
            level = 0
            for part in parts:
                if part == "" or part == ".":
                    level += 1
                else:
                    break
            rel_dir = file_dir
            for _ in range(level - 1):
                rel_dir = rel_dir.parent
            remaining = ".".join(p for p in parts[level:] if p)
            if remaining:
                return str(rel_dir / remaining.replace(".", "/")).replace("\\", "/")
            return str(rel_dir).replace("\\", "/")

        return normalized

    def _is_external_dependency(self, module_id: str, file_path: Path) -> bool:
        """Determine if a module is an external (third-party) dependency.

        Args:
            module_id: The resolved module ID.
            file_path: The source file path (for context).

        Returns:
            True if the module appears to be external.
        """
        # Check if it matches a source file in the project
        project_path = self.config.project_path
        for node_id, _ in self._file_map.items():
            if module_id == node_id or module_id.startswith(node_id + "."):
                return False
        # Check if the module path exists relative to the project
        potential_path = project_path / module_id.replace(".", "/")
        if potential_path.exists() or potential_path.with_suffix(".py").exists():
            return False
        # If it's in the same directory as the file, it's internal
        file_dir = file_path.parent
        potential_local = (file_dir / module_id.replace(".", "/")).resolve()
        try:
            if str(potential_local).startswith(str(project_path.resolve())):
                return False
        except (ValueError, OSError):
            pass
        return True

    def build(self) -> DepGraph:
        """Build the dependency graph by analyzing all project files.

        Returns:
            The fully constructed DepGraph.

        Raises:
            GraphError: If the project path is invalid or inaccessible.
        """
        logger.info("Building dependency graph for %s", self.config.project_path)
        self._stats["start_time"] = time.time()

        files = self._collect_files()
        logger.info("Found %d source files to analyze", len(files))

        # Pass 1: Create nodes for all files
        for file_path in files:
            module_id = self._resolve_module_id(file_path, file_path.stem)
            self._file_map[module_id] = file_path

            try:
                file_size = file_path.stat().st_size
            except OSError:
                file_size = 0

            parser = self._get_parser(file_path)
            language = parser.language if parser else None

            node = Node(
                id=module_id,
                file_path=str(file_path.resolve()),
                node_type="file",
                language=language,
                size=file_size,
            )
            self.graph.add_node(node)
            self._stats["parsed_files"] += 1

        # Pass 2: Parse imports and build edges
        for file_path in files:
            module_id = self._resolve_module_id(file_path, file_path.stem)
            parser = self._get_parser(file_path)

            if parser is None:
                self._stats["skipped_files"] += 1
                continue

            try:
                imports = parser.parse(file_path)
                self._all_imports[module_id] = imports
            except ParseError:
                self._stats["skipped_files"] += 1
                continue

            for import_name, line_no in imports:
                resolved = self._resolve_module_id(file_path, import_name)
                is_external = self._is_external_dependency(resolved, file_path)

                if is_external:
                    if not self.graph.has_node(resolved):
                        ext_node = Node(
                            id=resolved,
                            node_type="external",
                            metadata={"source": str(file_path)},
                        )
                        self.graph.add_node(ext_node)
                    self._stats["external_deps"] += 1
                else:
                    self._stats["internal_deps"] += 1

                self.graph.add_dependency(
                    source=module_id,
                    target=resolved,
                    weight=1,
                    metadata={"line": line_no, "file": str(file_path)},
                )
                self._stats["total_imports"] += 1

        self._stats["end_time"] = time.time()
        self._stats["duration_ms"] = int(
            (self._stats["end_time"] - self._stats["start_time"]) * 1000
        )

        logger.info(
            "Graph built: %d nodes, %d edges in %d ms",
            self.graph.node_count(),
            self.graph.edge_count(),
            self._stats["duration_ms"],
        )
        return self.graph

    def stats(self) -> Dict[str, Any]:
        """Return builder statistics.

        Returns:
            Dictionary with build statistics.
        """
        stats = dict(self._stats)
        if self.graph is not None:
            stats["node_count"] = self.graph.node_count()
            stats["edge_count"] = self.graph.edge_count()
        return stats


# ---------------------------------------------------------------------------
# CircularDetector: Cycle Detection Algorithms
# ---------------------------------------------------------------------------


@dataclass
class CycleInfo:
    """Information about a detected circular dependency.

    Attributes:
        nodes: Ordered list of node IDs forming the cycle.
        length: Number of nodes in the cycle.
        strength: Severity rating based on cycle length.
        edges: The edges involved in the cycle.
    """
    nodes: List[NodeId]
    length: int = 0
    strength: str = "low"
    edges: List[Edge] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Compute derived fields after initialization."""
        if self.length == 0:
            self.length = len(self.nodes)
        if self.length <= 3:
            self.strength = "high"
        elif self.length <= 6:
            self.strength = "medium"
        else:
            self.strength = "low"

    def __str__(self) -> str:
        path = " -> ".join(self.nodes) + f" -> {self.nodes[0]}"
        return f"Cycle ({self.strength}, {self.length} nodes): {path}"


class CircularDetector:
    """Detects circular dependencies in a dependency graph.

    Uses multiple algorithms:
    - DFS-based cycle detection (efficient for finding *if* cycles exist)
    - Tarjan's strongly connected components algorithm (finds all cycles)

    Attributes:
        graph: The dependency graph to analyze.
        cycles: List of detected cycles.
    """

    def __init__(self, graph: DepGraph) -> None:
        """Initialize the detector with a graph.

        Args:
            graph: The dependency graph to analyze.
        """
        self.graph = graph
        self.cycles: List[CycleInfo] = []
        self._stats: Dict[str, Any] = {
            "detection_time_ms": 0,
            "algorithm_used": None,
            "total_cycles": 0,
            "nodes_in_cycles": 0,
            "strongly_connected_components": 0,
        }

    def detect_dfs(self) -> List[CycleInfo]:
        """Detect cycles using DFS-based coloring algorithm.

        Uses three coloring states: WHITE (unvisited), GRAY (in-progress),
        BLACK (finished). A back-edge to a GRAY node indicates a cycle.

        Returns:
            List of CycleInfo objects for all detected cycles.

        Time complexity: O(V + E)
        Space complexity: O(V)
        """
        start = time.time()
        self.cycles = []
        self._stats["algorithm_used"] = "DFS"

        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[NodeId, int] = {n: WHITE for n in self.graph.nodes}
        parent: Dict[NodeId, Optional[NodeId]] = {n: None for n in self.graph.nodes}

        def dfs_visit(node: NodeId) -> None:
            """Visit a node and its neighbors recursively."""
            color[node] = GRAY
            for neighbor in self.graph.successors(node):
                if color[neighbor] == GRAY:
                    # Found a cycle - reconstruct the path
                    cycle_nodes: List[NodeId] = []
                    cycle_nodes.append(neighbor)
                    # Walk back from node to neighbor
                    current = node
                    while current is not None and current != neighbor:
                        cycle_nodes.append(current)
                        current = parent.get(current)
                    cycle_nodes.reverse()

                    # Collect edges in the cycle
                    cycle_edges: List[Edge] = []
                    cycle_set = set(cycle_nodes)
                    for edge in self.graph.edges:
                        if edge.source in cycle_set and edge.target in cycle_set:
                            cycle_edges.append(edge)

                    self.cycles.append(
                        CycleInfo(
                            nodes=cycle_nodes,
                            edges=cycle_edges,
                        )
                    )
                elif color[neighbor] == WHITE:
                    parent[neighbor] = node
                    dfs_visit(neighbor)
            color[node] = BLACK

        for node_id in self.graph.nodes:
            if color[node_id] == WHITE:
                dfs_visit(node_id)

        # Deduplicate cycles (same set of nodes, different starting points)
        self._deduplicate_cycles()

        self._stats["detection_time_ms"] = int((time.time() - start) * 1000)
        self._stats["total_cycles"] = len(self.cycles)
        self._stats["nodes_in_cycles"] = self._count_nodes_in_cycles()

        return self.cycles

    def detect_tarjan(self) -> List[CycleInfo]:
        """Detect cycles using Tarjan's strongly connected components algorithm.

        Finds all SCCs; any SCC with more than one node (or a self-loop) contains
        a cycle. This is more comprehensive than DFS-based detection.

        Returns:
            List of CycleInfo objects for all detected cycles.

        Time complexity: O(V + E)
        Space complexity: O(V)
        """
        start = time.time()
        self.cycles = []
        self._stats["algorithm_used"] = "Tarjan"

        index_counter: List[int] = [0]
        stack: List[NodeId] = []
        on_stack: Set[NodeId] = set()
        index: Dict[NodeId, int] = {}
        lowlink: Dict[NodeId, int] = {}

        def strongconnect(node: NodeId) -> None:
            """Perform Tarjan's SCC algorithm starting from a node."""
            index[node] = index_counter[0]
            lowlink[node] = index_counter[0]
            index_counter[0] += 1
            stack.append(node)
            on_stack.add(node)

            for neighbor in self.graph.successors(node):
                if neighbor not in index:
                    strongconnect(neighbor)
                    lowlink[node] = min(lowlink[node], lowlink[neighbor])
                elif neighbor in on_stack:
                    lowlink[node] = min(lowlink[node], index[neighbor])

            # If node is a root of an SCC, pop the SCC
            if lowlink[node] == index[node]:
                scc_nodes: List[NodeId] = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    scc_nodes.append(w)
                    if w == node:
                        break

                if len(scc_nodes) > 1:
                    # This SCC contains cycles
                    # Extract all simple cycles from the SCC
                    cycles_found = self._extract_cycles_from_scc(scc_nodes)
                    self.cycles.extend(cycles_found)
                elif len(scc_nodes) == 1:
                    # Check for self-loop
                    nid = scc_nodes[0]
                    if self.graph.has_edge(nid, nid):
                        self.cycles.append(
                            CycleInfo(
                                nodes=[nid],
                                edges=[
                                    e for e in self.graph.edges
                                    if e.source == nid and e.target == nid
                                ],
                            )
                        )

        for node_id in self.graph.nodes:
            if node_id not in index:
                strongconnect(node_id)

        # Deduplicate
        self._deduplicate_cycles()

        self._stats["detection_time_ms"] = int((time.time() - start) * 1000)
        self._stats["total_cycles"] = len(self.cycles)
        self._stats["nodes_in_cycles"] = self._count_nodes_in_cycles()
        self._stats["strongly_connected_components"] = index_counter[0]

        return self.cycles

    def detect(self, algorithm: str = "tarjan") -> List[CycleInfo]:
        """Detect cycles using the specified algorithm.

        Args:
            algorithm: Either 'dfs' or 'tarjan'.

        Returns:
            List of detected cycles.

        Raises:
            ValueError: If an unknown algorithm is specified.
        """
        algo = algorithm.lower().strip()
        if algo == "dfs":
            return self.detect_dfs()
        elif algo in ("tarjan", "scc"):
            return self.detect_tarjan()
        else:
            raise ValueError(
                f"Unknown algorithm: '{algorithm}'. "
                "Use 'dfs' or 'tarjan'."
            )

    def has_cycles(self) -> bool:
        """Quick check if the graph has any cycles.

        Uses DFS-based detection and returns early.

        Returns:
            True if at least one cycle exists.
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[NodeId, int] = {n: WHITE for n in self.graph.nodes}

        def dfs_visit(node: NodeId) -> bool:
            color[node] = GRAY
            for neighbor in self.graph.successors(node):
                if color[neighbor] == GRAY:
                    return True
                if color[neighbor] == WHITE:
                    if dfs_visit(neighbor):
                        return True
            color[node] = BLACK
            return False

        for node_id in self.graph.nodes:
            if color[node_id] == WHITE:
                if dfs_visit(node_id):
                    return True
        return False

    def _extract_cycles_from_scc(
        self, scc_nodes: List[NodeId]
    ) -> List[CycleInfo]:
        """Extract simple cycles from a strongly connected component.

        Uses a DFS-based path enumeration within the SCC.

        Args:
            scc_nodes: List of nodes in the SCC.

        Returns:
            List of CycleInfo objects for cycles found in the SCC.
        """
        scc_set = set(scc_nodes)
        cycles: List[CycleInfo] = []
        seen: Set[Tuple[NodeId, ...]] = set()

        def dfs_path(start: NodeId, current: NodeId, path: List[NodeId]) -> None:
            """Enumerate paths from start looking for cycles."""
            for neighbor in self.graph.successors(current):
                if neighbor == start and len(path) > 1:
                    # Found a cycle back to start
                    cycle_tuple = tuple(path)
                    if cycle_tuple not in seen:
                        seen.add(cycle_tuple)
                        cycle_edges = [
                            e for e in self.graph.edges
                            if e.source in scc_set and e.target in scc_set
                        ]
                        cycles.append(
                            CycleInfo(
                                nodes=list(path),
                                edges=cycle_edges,
                            )
                        )
                elif neighbor in scc_set and neighbor not in path:
                    dfs_path(start, neighbor, path + [neighbor])

        # Limit: only search from each node to avoid O(n!) explosion
        # Only search from the first few nodes in large SCCs
        search_nodes = scc_nodes[: min(10, len(scc_nodes))]
        for node in search_nodes:
            dfs_path(node, node, [node])

        return cycles

    def _deduplicate_cycles(self) -> None:
        """Remove duplicate cycles (same node set, different rotation/order)."""
        seen: Set[FrozenSet[NodeId]] = set()
        unique_cycles: List[CycleInfo] = []
        for cycle in self.cycles:
            node_set = frozenset(cycle.nodes)
            if node_set not in seen:
                seen.add(node_set)
                unique_cycles.append(cycle)
        self.cycles = unique_cycles

    def _count_nodes_in_cycles(self) -> int:
        """Count the number of unique nodes that participate in cycles.

        Returns:
            Count of unique node IDs in cycles.
        """
        nodes: Set[NodeId] = set()
        for cycle in self.cycles:
            nodes.update(cycle.nodes)
        return len(nodes)

    def stats(self) -> Dict[str, Any]:
        """Return detection statistics.

        Returns:
            Dictionary with detection statistics.
        """
        return dict(self._stats)

    def summary(self) -> str:
        """Return a human-readable summary of cycle detection results.

        Returns:
            Formatted summary string.
        """
        if not self.cycles:
            return "No circular dependencies detected."
        lines = [
            f"Found {len(self.cycles)} circular dependenc{'y' if len(self.cycles) == 1 else 'ies'}:",
            f"  Total nodes in cycles: {self._count_nodes_in_cycles()}",
            f"  Detection algorithm: {self._stats.get('algorithm_used', 'N/A')}",
            f"  Detection time: {self._stats.get('detection_time_ms', 0)} ms",
        ]
        for i, cycle in enumerate(self.cycles[:10], 1):
            lines.append(f"  {i}. {cycle}")
        if len(self.cycles) > 10:
            lines.append(f"  ... and {len(self.cycles) - 10} more cycles.")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# UnusedDepFinder: Find Unused Dependencies
# ---------------------------------------------------------------------------


class UnusedDepFinder:
    """Finds dependencies that are declared but not used in the project.

    The finder compares declared dependencies (from package manifests or
    import statements) with actual usage across the source code.

    Attributes:
        graph: The dependency graph to analyze.
        config: Analysis configuration.
    """

    def __init__(
        self, graph: DepGraph, config: Optional[AiDepsConfig] = None
    ) -> None:
        """Initialize the unused dependency finder.

        Args:
            graph: The dependency graph to analyze.
            config: Analysis configuration.
        """
        self.graph = graph
        self.config = config or AiDepsConfig()
        self._unused: Set[NodeId] = set()
        self._stats: Dict[str, Any] = {
            "total_dependencies": 0,
            "unused_count": 0,
            "used_count": 0,
            "analysis_time_ms": 0,
        }

    def find_by_degree(self) -> Set[NodeId]:
        """Find potentially unused dependencies using in-degree analysis.

        Nodes with zero in-degree (no other module depends on them) may
        be unused, unless they are entry points.

        Returns:
            Set of node IDs that are potentially unused.
        """
        start = time.time()
        self._unused = set()

        for node_id in self.graph.nodes:
            node = self.graph.get_node(node_id)
            if node is None:
                continue
            # Skip external nodes that are dependencies of others
            predecessors = self.graph.predecessors(node_id)
            if len(predecessors) == 0:
                # Check if this node is an entry point (has out-edges but no in-edges)
                successors = self.graph.successors(node_id)
                if len(successors) > 0:
                    # Has dependencies but nothing depends on it
                    # Could be an entry point, not unused
                    continue
                self._unused.add(node_id)

        self._stats["unused_count"] = len(self._unused)
        self._stats["analysis_time_ms"] = int((time.time() - start) * 1000)
        return self._unused.copy()

    def find_orphaned_external(self) -> Set[NodeId]:
        """Find external dependencies that are imported but never resolved.

        These are external packages that appear in imports but are not
        declared in the project's own file tree.

        Returns:
            Set of external node IDs that are orphaned.
        """
        start = time.time()
        orphaned: Set[NodeId] = set()

        for node_id, node in self.graph.nodes.items():
            if node.node_type == "external":
                # Check if any internal node depends on this
                predecessors = self.graph.predecessors(node_id)
                has_internal_predecessor = any(
                    self.graph.get_node(p) is not None
                    and self.graph.get_node(p).node_type != "external"
                    for p in predecessors
                )
                if not has_internal_predecessor:
                    orphaned.add(node_id)

        self._stats["analysis_time_ms"] = int((time.time() - start) * 1000)
        return orphaned

    def find_unused_by_reachability(self, entry_points: List[NodeId]) -> Set[NodeId]:
        """Find nodes not reachable from any entry point.

        Modules that cannot be reached from any entry point are likely unused.

        Args:
            entry_points: List of node IDs to consider as entry points.

        Returns:
            Set of unreachable node IDs.
        """
        start = time.time()

        # BFS from all entry points
        reachable: Set[NodeId] = set()
        queue: deque[NodeId] = deque()

        for ep in entry_points:
            if ep in self.graph.nodes:
                queue.append(ep)
                reachable.add(ep)

        while queue:
            current = queue.popleft()
            for successor in self.graph.successors(current):
                if successor not in reachable:
                    reachable.add(successor)
                    queue.append(successor)

        # Also traverse reverse from entry points (dependents)
        queue = deque(entry_points)
        visited: Set[NodeId] = set(entry_points)
        while queue:
            current = queue.popleft()
            for predecessor in self.graph.predecessors(current):
                if predecessor not in visited:
                    visited.add(predecessor)
                    queue.append(predecessor)

        reachable.update(visited)
        unused = set(self.graph.nodes.keys()) - reachable

        self._unused = unused
        self._stats["unused_count"] = len(unused)
        self._stats["analysis_time_ms"] = int((time.time() - start) * 1000)
        return unused.copy()

    def find(self, entry_points: Optional[List[NodeId]] = None) -> Set[NodeId]:
        """Comprehensive unused dependency detection.

        Combines multiple strategies for best results.

        Args:
            entry_points: Optional list of entry point node IDs.

        Returns:
            Set of unused node IDs.
        """
        unused: Set[NodeId] = set()

        # Strategy 1: Degree-based analysis
        unused_by_degree = self.find_by_degree()
        unused.update(unused_by_degree)

        # Strategy 2: Orphaned external deps
        orphaned = self.find_orphaned_external()
        unused.update(orphaned)

        # Strategy 3: Reachability analysis if entry points provided
        if entry_points:
            unreachable = self.find_unused_by_reachability(entry_points)
            unused.update(unreachable)

        # Filter out entry points themselves
        if entry_points:
            unused -= set(entry_points)

        self._unused = unused
        self._stats["unused_count"] = len(unused)
        self._stats["total_dependencies"] = len(self.graph.nodes)
        self._stats["used_count"] = self._stats["total_dependencies"] - len(unused)
        return unused.copy()

    def stats(self) -> Dict[str, Any]:
        """Return finder statistics.

        Returns:
            Dictionary with analysis statistics.
        """
        return dict(self._stats)

    def summary(self) -> str:
        """Return a human-readable summary of unused dependencies.

        Returns:
            Formatted summary string.
        """
        if not self._unused:
            return "No unused dependencies found."
        lines = [
            f"Found {len(self._unused)} potentially unused dependenc{'y' if len(self._unused) == 1 else 'ies'}:",
        ]
        for i, dep in enumerate(sorted(self._unused)[:20], 1):
            node = self.graph.get_node(dep)
            if node and node.file_path:
                lines.append(f"  {i}. {dep} ({node.file_path})")
            else:
                lines.append(f"  {i}. {dep}")
        if len(self._unused) > 20:
            lines.append(f"  ... and {len(self._unused) - 20} more.")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# MermaidGenerator: Mermaid.js Graph Output
# ---------------------------------------------------------------------------


class MermaidGenerator:
    """Generates Mermaid.js flowchart diagrams from a DepGraph.

    Produces Markdown-compatible Mermaid syntax for dependency visualization.
    Supports graph direction, subgraphs, and styling.
    """

    def __init__(self, graph: DepGraph, config: Optional[AiDepsConfig] = None) -> None:
        """Initialize the Mermaid generator.

        Args:
            graph: The dependency graph to visualize.
            config: Optional configuration.
        """
        self.graph = graph
        self.config = config or AiDepsConfig()

    def generate(
        self,
        direction: str = "LR",
        show_external: bool = True,
        max_nodes: int = 100,
        group_by_type: bool = True,
    ) -> str:
        """Generate a Mermaid flowchart string.

        Args:
            direction: Graph direction (LR = left-to-right, TD = top-down).
            show_external: Whether to include external dependency nodes.
            max_nodes: Maximum number of nodes to include.
            group_by_type: Whether to group nodes by type using subgraphs.

        Returns:
            Mermaid flowchart syntax as a string.
        """
        lines: List[str] = []
        lines.append(f"```mermaid")
        lines.append(f"flowchart {direction}")

        if self.graph.is_empty():
            lines.append("    %% No dependencies found")
            lines.append("```")
            return "\n".join(lines)

        # Select nodes to include
        nodes_to_include = self._select_nodes(
            show_external=show_external, max_nodes=max_nodes
        )
        node_set = set(nodes_to_include)
        edges_to_include = [
            e for e in self.graph.edges
            if e.source in node_set and e.target in node_set
        ]

        # Group nodes by type
        if group_by_type:
            self._add_subgraphs(lines, nodes_to_include, edges_to_include)
        else:
            # Add nodes
            for node_id in nodes_to_include:
                node = self.graph.get_node(node_id)
                safe_id = self._safe_id(node_id)
                label = self._node_label(node_id)
                if node and node.node_type == "external":
                    lines.append(f"    {safe_id}([\"{label}\"])")
                elif node and node.node_type == "file":
                    lines.append(f"    {safe_id}[\"{label}\"]")
                else:
                    lines.append(f"    {safe_id}(\"{label}\")")

            # Add edges
            for edge in edges_to_include:
                safe_src = self._safe_id(edge.source)
                safe_tgt = self._safe_id(edge.target)
                if edge.weight > 1:
                    lines.append(f"    {safe_src} -->|{edge.weight}x| {safe_tgt}")
                else:
                    lines.append(f"    {safe_src} --> {safe_tgt}")

        # Style cycles
        self._style_cycles(lines, nodes_to_include)

        lines.append("```")
        return "\n".join(lines)

    def _select_nodes(
        self, show_external: bool = True, max_nodes: int = 100
    ) -> List[NodeId]:
        """Select which nodes to include in the visualization.

        Prioritizes nodes with the most connections.

        Args:
            show_external: Whether to include external nodes.
            max_nodes: Maximum number of nodes.

        Returns:
            List of selected node IDs.
        """
        candidates = []
        for node_id, node in self.graph.nodes.items():
            if not show_external and node.node_type == "external":
                continue
            degree = len(self.graph.successors(node_id)) + len(
                self.graph.predecessors(node_id)
            )
            candidates.append((degree, node_id))

        # Sort by degree (highest first)
        candidates.sort(key=lambda x: -x[0])
        return [nid for _, nid in candidates[:max_nodes]]

    def _add_subgraphs(
        self,
        lines: List[str],
        nodes: List[NodeId],
        edges: List[Edge],
    ) -> None:
        """Add nodes grouped by type into subgraphs.

        Args:
            lines: Output lines to append to.
            nodes: List of node IDs to include.
            edges: List of edges to include.
        """
        node_set = set(nodes)
        # Group by type
        by_type: Dict[str, List[NodeId]] = defaultdict(list)
        for node_id in nodes:
            node = self.graph.get_node(node_id)
            ntype = node.node_type if node else "unknown"
            by_type[ntype].append(node_id)

        type_order = ["file", "module", "external", "unknown"]
        for ntype in type_order:
            if ntype not in by_type:
                continue
            type_nodes = by_type[ntype]
            type_label = ntype.capitalize()
            lines.append(f"    subgraph {type_label}")

            for node_id in type_nodes:
                safe_id = self._safe_id(node_id)
                label = self._node_label(node_id)
                lines.append(f"        {safe_id}[\"{label}\"]")

            lines.append(f"    end")

        # Add edges between subgraphs
        for edge in edges:
            if edge.source in node_set and edge.target in node_set:
                safe_src = self._safe_id(edge.source)
                safe_tgt = self._safe_id(edge.target)
                if edge.weight > 1:
                    lines.append(f"    {safe_src} -->|{edge.weight}x| {safe_tgt}")
                else:
                    lines.append(f"    {safe_src} --> {safe_tgt}")

    def _style_cycles(
        self, lines: List[str], nodes: List[NodeId]
    ) -> None:
        """Add styling for nodes involved in cycles.

        Args:
            lines: Output lines to append to.
            nodes: List of node IDs in the visualization.
        """
        detector = CircularDetector(self.graph)
        if not detector.has_cycles():
            return

        cycles = detector.detect("dfs")
        cycle_nodes: Set[NodeId] = set()
        for cycle in cycles:
            cycle_nodes.update(cycle.nodes)

        # Only style nodes that are in the visualization
        for node_id in nodes:
            if node_id in cycle_nodes:
                safe_id = self._safe_id(node_id)
                lines.append(f"    style {safe_id} fill:#ff6b6b,stroke:#c0392b,color:#fff")

    @staticmethod
    def _safe_id(node_id: NodeId) -> str:
        """Convert a node ID to a safe Mermaid identifier.

        Args:
            node_id: The node ID to sanitize.

        Returns:
            A Mermaid-safe identifier.
        """
        safe = node_id.replace("/", "_").replace("\\", "_")
        safe = safe.replace(".", "_").replace("-", "_").replace(":", "_")
        safe = safe.replace("@", "_").replace("~", "_")
        # Ensure it starts with a letter
        if safe and safe[0].isdigit():
            safe = "n_" + safe
        # Truncate to avoid overly long IDs
        if len(safe) > 80:
            safe = safe[:80]
        return safe if safe else "node"

    @staticmethod
    def _node_label(node_id: NodeId) -> str:
        """Create a display label for a node.

        Args:
            node_id: The node ID to label.

        Returns:
            Short display label.
        """
        # Use the last 2-3 parts of the path
        parts = node_id.replace("/", ".").split(".")
        if len(parts) > 3:
            return "...".join(parts[-3:])
        return node_id


# ---------------------------------------------------------------------------
# GraphvizGenerator: DOT Format Output
# ---------------------------------------------------------------------------


class GraphvizGenerator:
    """Generates Graphviz DOT format output from a DepGraph.

    Produces DOT language syntax for use with Graphviz tools (dot, neato, etc.).
    """

    def __init__(self, graph: DepGraph, config: Optional[AiDepsConfig] = None) -> None:
        """Initialize the Graphviz generator.

        Args:
            graph: The dependency graph to visualize.
            config: Optional configuration.
        """
        self.graph = graph
        self.config = config or AiDepsConfig()

    def generate(
        self,
        graph_name: str = "dependency_graph",
        direction: str = "LR",
        show_external: bool = True,
        max_nodes: int = 200,
    ) -> str:
        """Generate a DOT format string.

        Args:
            graph_name: Name for the graph.
            direction: Graph direction (LR or TD).
            show_external: Whether to include external nodes.
            max_nodes: Maximum number of nodes to include.

        Returns:
            DOT format string.
        """
        lines: List[str] = []
        rankdir = "LR" if direction.upper() == "LR" else "TB"
        lines.append(f"digraph \"{graph_name}\" {{")
        lines.append(f"    rankdir={rankdir};")
        lines.append("    bgcolor=\"#ffffff\";")
        lines.append("    node [fontname=\"Helvetica\", fontsize=10];")
        lines.append("    edge [fontname=\"Helvetica\", fontsize=8];")
        lines.append("")

        if self.graph.is_empty():
            lines.append("    /* No dependencies found */")
            lines.append("}")
            return "\n".join(lines)

        # Select nodes
        nodes_to_include = self._select_nodes(
            show_external=show_external, max_nodes=max_nodes
        )
        node_set = set(nodes_to_include)

        # Add nodes
        for node_id in nodes_to_include:
            node = self.graph.get_node(node_id)
            safe_id = self._safe_id(node_id)
            label = self._dot_label(node_id)

            if node and node.node_type == "external":
                lines.append(
                    f"    {safe_id} [label=\"{label}\", shape=folder, "
                    f"style=filled, fillcolor=\"#e8f4f8\", color=\"#2980b9\"];"
                )
            elif node and node.node_type == "file":
                lines.append(
                    f"    {safe_id} [label=\"{label}\", shape=box, "
                    f"style=filled, fillcolor=\"#f0f0f0\", color=\"#7f8c8d\"];"
                )
            else:
                lines.append(
                    f"    {safe_id} [label=\"{label}\", shape=ellipse, "
                    f"style=filled, fillcolor=\"#f9f9f9\", color=\"#bdc3c7\"];"
                )

        lines.append("")

        # Style cycle nodes
        detector = CircularDetector(self.graph)
        if detector.has_cycles():
            cycles = detector.detect("dfs")
            cycle_nodes: Set[NodeId] = set()
            for cycle in cycles:
                cycle_nodes.update(cycle.nodes)
            for node_id in cycle_nodes:
                if node_id in node_set:
                    safe_id = self._safe_id(node_id)
                    lines.append(
                        f"    {safe_id} [style=filled, fillcolor=\"#ffcccc\", "
                        f"color=\"#e74c3c\", penwidth=2];"
                    )
            lines.append("")

        # Add edges
        for edge in self.graph.edges:
            if edge.source in node_set and edge.target in node_set:
                safe_src = self._safe_id(edge.source)
                safe_tgt = self._safe_id(edge.target)
                if edge.weight > 1:
                    lines.append(
                        f"    {safe_src} -> {safe_tgt} [label=\"{edge.weight}x\", "
                        f"penwidth={min(edge.weight, 5)}];"
                    )
                else:
                    lines.append(f"    {safe_src} -> {safe_tgt};")

        lines.append("}")
        return "\n".join(lines)

    def _select_nodes(
        self, show_external: bool = True, max_nodes: int = 200
    ) -> List[NodeId]:
        """Select the most important nodes for visualization.

        Args:
            show_external: Whether to include external nodes.
            max_nodes: Maximum number of nodes.

        Returns:
            List of selected node IDs.
        """
        candidates = []
        for node_id, node in self.graph.nodes.items():
            if not show_external and node.node_type == "external":
                continue
            degree = len(self.graph.successors(node_id)) + len(
                self.graph.predecessors(node_id)
            )
            candidates.append((degree, node_id))

        candidates.sort(key=lambda x: -x[0])
        return [nid for _, nid in candidates[:max_nodes]]

    @staticmethod
    def _safe_id(node_id: NodeId) -> str:
        """Convert a node ID to a safe DOT identifier.

        Args:
            node_id: The node ID to sanitize.

        Returns:
            A DOT-safe identifier.
        """
        safe = node_id.replace("/", "_").replace("\\", "_")
        safe = safe.replace(".", "_").replace("-", "_").replace(":", "_")
        safe = safe.replace("@", "_").replace("(", "_").replace(")", "_")
        if safe and safe[0].isdigit():
            safe = "n_" + safe
        if len(safe) > 80:
            safe = safe[:80]
        return f'"{safe}"' if " " in safe or "-" in safe else safe

    @staticmethod
    def _dot_label(node_id: NodeId) -> str:
        """Create a display label for a DOT node.

        Args:
            node_id: The node ID to label.

        Returns:
            Escaped display label.
        """
        parts = node_id.replace("/", ".").split(".")
        if len(parts) > 3:
            label = "...".join(parts[-3:])
        else:
            label = node_id
        return label.replace('"', '\\"')


# ---------------------------------------------------------------------------
# HTMLReportGenerator: Interactive Reports
# ---------------------------------------------------------------------------


class HTMLReportGenerator:
    """Generates interactive HTML reports for dependency analysis.

    Produces a self-contained HTML file with embedded CSS and JavaScript
    for interactive exploration of the dependency graph.
    """

    TEMPLATE_HEADER = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI-Deps Dependency Analysis Report</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f7fa; color: #2c3e50; line-height: 1.6; }}
.header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 2rem 3rem; }}
.header h1 {{ font-size: 2rem; margin-bottom: 0.5rem; }}
.header p {{ opacity: 0.9; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 2rem; }}
.card {{ background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); padding: 1.5rem; margin-bottom: 1.5rem; }}
.card h2 {{ font-size: 1.3rem; margin-bottom: 1rem; color: #2c3e50; border-bottom: 2px solid #eee; padding-bottom: 0.5rem; }}
.stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; }}
.stat-item {{ text-align: center; padding: 1rem; background: #f8f9fa; border-radius: 6px; }}
.stat-value {{ font-size: 2rem; font-weight: bold; color: #667eea; }}
.stat-label {{ font-size: 0.85rem; color: #7f8c8d; text-transform: uppercase; letter-spacing: 0.05em; }}
.cycle-list {{ list-style: none; }}
.cycle-list li {{ padding: 0.5rem; margin: 0.25rem 0; background: #fff5f5; border-left: 3px solid #e74c3c; border-radius: 3px; font-family: monospace; font-size: 0.9rem; }}
.unused-list {{ list-style: none; }}
.unused-list li {{ padding: 0.5rem; margin: 0.25rem 0; background: #fffaf0; border-left: 3px solid #f39c12; border-radius: 3px; font-family: monospace; font-size: 0.9rem; }}
.mermaid-container {{ background: white; border-radius: 8px; padding: 1rem; overflow-x: auto; }}
.dep-table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
.dep-table th, .dep-table td {{ padding: 0.5rem; text-align: left; border-bottom: 1px solid #eee; font-size: 0.9rem; }}
.dep-table th {{ background: #f8f9fa; font-weight: 600; }}
.dep-table tr:hover {{ background: #f0f4ff; }}
.badge {{ display: inline-block; padding: 0.2rem 0.5rem; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }}
.badge-high {{ background: #ffe0e0; color: #c0392b; }}
.badge-medium {{ background: #fff3cd; color: #856404; }}
.badge-low {{ background: #d4edda; color: #155724; }}
.footer {{ text-align: center; padding: 2rem; color: #95a5a6; font-size: 0.85rem; }}
</style>
</head>
<body>
<div class="header">
<h1>AI-Deps Dependency Analysis Report</h1>
<p>Generated: {generated_at}</p>
<p>Project: {project_path}</p>
</div>
<div class="container">
"""

    TEMPLATE_FOOTER = """
</div>
<div class="footer">
<p>Generated by AI-Deps v{version} | {stats_summary}</p>
</div>
</body>
</html>"""

    def __init__(
        self,
        graph: DepGraph,
        config: Optional[AiDepsConfig] = None,
        cycles: Optional[List[CycleInfo]] = None,
        unused: Optional[Set[NodeId]] = None,
    ) -> None:
        """Initialize the HTML report generator.

        Args:
            graph: The dependency graph.
            config: Optional configuration.
            cycles: Optional list of detected cycles.
            unused: Optional set of unused dependency node IDs.
        """
        self.graph = graph
        self.config = config or AiDepsConfig()
        self.cycles = cycles or []
        self.unused = unused or set()

    def generate(self) -> str:
        """Generate the complete HTML report.

        Returns:
            Complete HTML string for the report.
        """
        sections: List[str] = []
        sections.append(self._stats_section())
        sections.append(self._cycles_section())
        sections.append(self._unused_section())
        sections.append(self._graph_section())
        sections.append(self._dependency_table_section())

        header = self.TEMPLATE_HEADER.format(
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            project_path=str(self.config.project_path.resolve()),
        )
        footer = self.TEMPLATE_FOOTER.format(
            version=__version__,
            stats_summary=f"{self.graph.node_count()} nodes, {self.graph.edge_count()} edges",
        )
        return header + "\n".join(sections) + footer

    def _stats_section(self) -> str:
        """Generate the statistics summary card.

        Returns:
            HTML string for the stats section.
        """
        external_count = sum(
            1 for n in self.graph.nodes.values() if n.node_type == "external"
        )
        internal_count = self.graph.node_count() - external_count

        lines = """
<div class="card">
<h2>Analysis Summary</h2>
<div class="stats-grid">
    <div class="stat-item">
        <div class="stat-value">{nodes}</div>
        <div class="stat-label">Total Nodes</div>
    </div>
    <div class="stat-item">
        <div class="stat-value">{edges}</div>
        <div class="stat-label">Total Edges</div>
    </div>
    <div class="stat-item">
        <div class="stat-value">{internal}</div>
        <div class="stat-label">Internal Modules</div>
    </div>
    <div class="stat-item">
        <div class="stat-value">{external}</div>
        <div class="stat-label">External Dependencies</div>
    </div>
    <div class="stat-item">
        <div class="stat-value">{cycles}</div>
        <div class="stat-label">Circular Dependencies</div>
    </div>
    <div class="stat-item">
        <div class="stat-value">{unused}</div>
        <div class="stat-label">Unused Dependencies</div>
    </div>
</div>
</div>""".format(
            nodes=self.graph.node_count(),
            edges=self.graph.edge_count(),
            internal=internal_count,
            external=external_count,
            cycles=len(self.cycles),
            unused=len(self.unused),
        )
        return lines

    def _cycles_section(self) -> str:
        """Generate the circular dependencies section.

        Returns:
            HTML string for the cycles section.
        """
        if not self.cycles:
            return ""

        lines = """
<div class="card">
<h2>Circular Dependencies</h2>
<p>Found {count} circular dependenc{plural}.</p>
<ul class="cycle-list">""".format(
            count=len(self.cycles),
            plural="y" if len(self.cycles) == 1 else "ies",
        )

        for cycle in self.cycles[:20]:
            badge_class = f"badge-{cycle.strength}"
            path = " -> ".join(cycle.nodes) + f" -> {cycle.nodes[0]}"
            lines += f"""
    <li>
        <span class="badge {badge_class}">{cycle.strength}</span>
        <span class="badge">{cycle.length} nodes</span>
        <code>{html.escape(path)}</code>
    </li>"""

        if len(self.cycles) > 20:
            lines += f"<li><em>... and {len(self.cycles) - 20} more cycles.</em></li>"

        lines += "\n</ul>\n</div>"
        return lines

    def _unused_section(self) -> str:
        """Generate the unused dependencies section.

        Returns:
            HTML string for the unused dependencies section.
        """
        if not self.unused:
            return ""

        lines = """
<div class="card">
<h2>Unused Dependencies</h2>
<p>Found {count} potentially unused dependenc{plural}.</p>
<ul class="unused-list">""".format(
            count=len(self.unused),
            plural="y" if len(self.unused) == 1 else "ies",
        )

        for dep_id in sorted(self.unused)[:30]:
            node = self.graph.get_node(dep_id)
            if node and node.file_path:
                lines += f'<li><code>{html.escape(dep_id)}</code> <small>({html.escape(node.file_path)})</small></li>'
            else:
                lines += f'<li><code>{html.escape(dep_id)}</code></li>'

        if len(self.unused) > 30:
            lines += f"<li><em>... and {len(self.unused) - 30} more.</em></li>"

        lines += "\n</ul>\n</div>"
        return lines

    def _graph_section(self) -> str:
        """Generate the Mermaid graph visualization section.

        Returns:
            HTML string for the graph visualization section.
        """
        mermaid_gen = MermaidGenerator(self.graph, self.config)
        mermaid_code = mermaid_gen.generate(
            direction="TD",
            show_external=False,
            max_nodes=50,
        )

        lines = """
<div class="card">
<h2>Dependency Graph</h2>
<div class="mermaid-container">
{mermaid}
</div>
</div>""".format(mermaid=mermaid_code)
        return lines

    def _dependency_table_section(self) -> str:
        """Generate the dependency detail table.

        Returns:
            HTML string for the dependency table section.
        """
        # Build rows sorted by number of outgoing edges (dependencies)
        rows: List[Tuple[str, int, int, str]] = []
        for node_id, node in self.graph.nodes.items():
            if node.node_type == "external":
                continue
            deps = len(self.graph.successors(node_id))
            dependents = len(self.graph.predecessors(node_id))
            file_path = node.file_path or ""
            rows.append((node_id, deps, dependents, file_path))

        rows.sort(key=lambda r: -r[1])

        lines = """
<div class="card">
<h2>Module Dependencies</h2>
<table class="dep-table">
<thead>
<tr>
    <th>Module</th>
    <th>Dependencies</th>
    <th>Dependents</th>
    <th>File Path</th>
</tr>
</thead>
<tbody>"""

        for node_id, deps, dependents, file_path in rows[:100]:
            lines += f"""
<tr>
    <td><code>{html.escape(node_id)}</code></td>
    <td>{deps}</td>
    <td>{dependents}</td>
    <td><small>{html.escape(file_path)}</small></td>
</tr>"""

        if len(rows) > 100:
            lines += f"<tr><td colspan='4'><em>... and {len(rows) - 100} more modules.</em></td></tr>"

        lines += "\n</tbody>\n</table>\n</div>"
        return lines


# ---------------------------------------------------------------------------
# CSV Generator
# ---------------------------------------------------------------------------


class CSVGenerator:
    """Generates CSV output of the dependency graph for spreadsheet analysis."""

    def __init__(self, graph: DepGraph) -> None:
        """Initialize the CSV generator.

        Args:
            graph: The dependency graph.
        """
        self.graph = graph

    def generate_edges(self, output: Optional[str] = None) -> str:
        """Generate CSV of all edges (dependencies).

        Args:
            output: Optional file path to write to.

        Returns:
            CSV string of edges.
        """
        import io
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["source", "target", "weight", "source_type", "target_type"])

        for edge in self.graph.edges:
            src_node = self.graph.get_node(edge.source)
            tgt_node = self.graph.get_node(edge.target)
            writer.writerow([
                edge.source,
                edge.target,
                edge.weight,
                src_node.node_type if src_node else "",
                tgt_node.node_type if tgt_node else "",
            ])

        result = buf.getvalue()
        if output:
            Path(output).write_text(result, encoding="utf-8")
        return result

    def generate_nodes(self, output: Optional[str] = None) -> str:
        """Generate CSV of all nodes.

        Args:
            output: Optional file path to write to.

        Returns:
            CSV string of nodes.
        """
        import io
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "file_path", "node_type", "language", "size"])

        for node in self.graph.nodes.values():
            writer.writerow([
                node.id,
                node.file_path or "",
                node.node_type,
                node.language or "",
                node.size,
            ])

        result = buf.getvalue()
        if output:
            Path(output).write_text(result, encoding="utf-8")
        return result


# ---------------------------------------------------------------------------
# CLI: Command-Line Interface
# ---------------------------------------------------------------------------


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for the CLI.

    Returns:
        Configured argument parser.
    """
    parser = argparse.ArgumentParser(
        prog="ai-deps",
        description=__description__,
        epilog=(
            "Examples:\n"
            "  ai-deps analyze --path ./myproject\n"
            "  ai-deps analyze --path ./myproject --format mermaid --depth 2\n"
            "  ai-deps detect-circular --path ./myproject\n"
            "  ai-deps find-unused --path ./myproject --entry-points main.py\n"
            "  ai-deps report --path ./myproject --output report.html\n"
            "  ai-deps stats --path ./myproject --format json\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    # Global options on the main parser (for use without subcommands)
    parser.add_argument(
        "--path", "-p",
        type=str,
        default=".",
        help="Project root path (default: current directory)",
    )

    # Parent parser with common arguments shared across subcommands
    common_parent = argparse.ArgumentParser(add_help=False)
    common_parent.add_argument(
        "--path", "-p",
        type=str,
        default=".",
        help="Project root path (default: current directory)",
    )
    common_parent.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="Path to JSON config file",
    )
    common_parent.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    common_parent.add_argument(
        "--exclude",
        type=str,
        nargs="*",
        default=[],
        help="Additional exclude patterns",
    )
    common_parent.add_argument(
        "--include",
        type=str,
        nargs="*",
        default=[],
        help="Include patterns (only process matching files)",
    )
    common_parent.add_argument(
        "--depth",
        type=int,
        default=0,
        help="Maximum analysis depth (0 = unlimited)",
    )
    common_parent.add_argument(
        "--language", "-l",
        type=str,
        default=None,
        help="Force language (python, javascript, typescript, java, go, rust, ruby, php)",
    )
    common_parent.add_argument(
        "--ignore-errors",
        action="store_true",
        default=True,
        help="Ignore parse errors and continue (default: true)",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        help="Available commands",
    )

    # analyze command
    analyze_parser = subparsers.add_parser(
        "analyze",
        parents=[common_parent],
        help="Build and display the dependency graph",
    )
    analyze_parser.add_argument(
        "--format", "-f",
        type=str,
        default="json",
        choices=["json", "mermaid", "dot", "csv", "text"],
        help="Output format (default: json)",
    )
    analyze_parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output file path",
    )
    analyze_parser.add_argument(
        "--max-nodes",
        type=int,
        default=100,
        help="Maximum nodes in visualization (default: 100)",
    )
    analyze_parser.add_argument(
        "--show-external",
        action="store_true",
        default=True,
        help="Include external dependencies in output",
    )

    # detect-circular command
    circular_parser = subparsers.add_parser(
        "detect-circular",
        parents=[common_parent],
        help="Detect circular dependencies",
    )
    circular_parser.add_argument(
        "--algorithm",
        type=str,
        default="tarjan",
        choices=["dfs", "tarjan"],
        help="Detection algorithm (default: tarjan)",
    )
    circular_parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output file for JSON results",
    )

    # find-unused command
    unused_parser = subparsers.add_parser(
        "find-unused",
        parents=[common_parent],
        help="Find unused dependencies",
    )
    unused_parser.add_argument(
        "--entry-points",
        type=str,
        nargs="*",
        default=[],
        help="Entry point module IDs for reachability analysis",
    )
    unused_parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output file for results",
    )

    # report command
    report_parser = subparsers.add_parser(
        "report",
        parents=[common_parent],
        help="Generate an HTML report",
    )
    report_parser.add_argument(
        "--output", "-o",
        type=str,
        default="deps-report.html",
        help="Output HTML file path (default: deps-report.html)",
    )

    # stats command
    stats_parser = subparsers.add_parser(
        "stats",
        parents=[common_parent],
        help="Show dependency statistics",
    )
    stats_parser.add_argument(
        "--format", "-f",
        type=str,
        default="text",
        choices=["text", "json"],
        help="Output format (default: text)",
    )

    # graph command
    graph_parser = subparsers.add_parser(
        "graph",
        parents=[common_parent],
        help="Export dependency graph in a specific format",
    )
    graph_parser.add_argument(
        "--format", "-f",
        type=str,
        default="dot",
        choices=["dot", "mermaid", "json", "csv-edges", "csv-nodes"],
        help="Output format (default: dot)",
    )
    graph_parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output file path",
    )
    graph_parser.add_argument(
        "--max-nodes",
        type=int,
        default=200,
        help="Maximum nodes in output (default: 200)",
    )

    # config command
    config_parser = subparsers.add_parser(
        "config",
        parents=[common_parent],
        help="Show or generate a default config",
    )
    config_parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate a default config file",
    )
    config_parser.add_argument(
        "--output", "-o",
        type=str,
        default="ai-deps-config.json",
        help="Output file for generated config (default: ai-deps-config.json)",
    )

    return parser


def _build_config(args: argparse.Namespace) -> AiDepsConfig:
    """Build a configuration from parsed CLI arguments.

    Args:
        args: Parsed command-line arguments.

    Returns:
        AiDepsConfig instance.
    """
    config = AiDepsConfig()

    # Load from config file if specified
    if getattr(args, "config", None):
        config = AiDepsConfig.from_json(args.config)

    # Override with CLI arguments
    config.project_path = Path(getattr(args, "path", "."))
    config.verbose = getattr(args, "verbose", False) or config.verbose
    config.depth = getattr(args, "depth", 0) or config.depth
    config.language = getattr(args, "language", None) or config.language
    config.ignore_errors = getattr(args, "ignore_errors", True) and config.ignore_errors

    # Exclude patterns
    extra_excludes = getattr(args, "exclude", [])
    if extra_excludes:
        config.exclude_patterns = list(config.exclude_patterns) + extra_excludes

    # Include patterns
    extra_includes = getattr(args, "include", [])
    if extra_includes:
        config.include_patterns = list(config.include_patterns) + extra_includes

    # Output format
    if hasattr(args, "format") and args.format:
        config.output_format = args.format

    # Output file
    if hasattr(args, "output") and args.output:
        config.output_file = args.output

    return config


def _cmd_analyze(args: argparse.Namespace) -> None:
    """Handle the 'analyze' command.

    Args:
        args: Parsed command-line arguments.
    """
    config = _build_config(args)
    _setup_logging(config.verbose)

    builder = GraphBuilder(config)
    graph = builder.build()

    if config.output_format == "json":
        result = json.dumps(graph.to_json(), indent=2, ensure_ascii=False)
        _write_output(result, config.output_file)
    elif config.output_format == "mermaid":
        generator = MermaidGenerator(graph, config)
        result = generator.generate(
            show_external=getattr(args, "show_external", True),
            max_nodes=getattr(args, "max_nodes", 100),
        )
        _write_output(result, config.output_file)
    elif config.output_format == "dot":
        generator = GraphvizGenerator(graph, config)
        result = generator.generate(
            show_external=getattr(args, "show_external", True),
            max_nodes=getattr(args, "max_nodes", 200),
        )
        _write_output(result, config.output_file)
    elif config.output_format == "csv":
        csv_gen = CSVGenerator(graph)
        result = csv_gen.generate_edges()
        _write_output(result, config.output_file)
    elif config.output_format == "text":
        lines = [
            "=" * 60,
            "Dependency Analysis Results",
            "=" * 60,
            f"Nodes: {graph.node_count()}",
            f"Edges: {graph.edge_count()}",
            "",
            "Nodes:",
        ]
        for node_id, node in sorted(graph.nodes.items()):
            deps = len(graph.successors(node_id))
            dep_by = len(graph.predecessors(node_id))
            lines.append(
                f"  {node_id} ({node.node_type}) "
                f"[deps: {deps}, depended-by: {dep_by}]"
            )
        lines.append("")
        lines.append("Edges:")
        for edge in sorted(graph.edges, key=lambda e: (e.source, e.target)):
            lines.append(f"  {edge.source} -> {edge.target} (weight: {edge.weight})")
        _write_output("\n".join(lines), config.output_file)

    if config.output_file:
        logger.info("Output written to %s", config.output_file)


def _cmd_detect_circular(args: argparse.Namespace) -> None:
    """Handle the 'detect-circular' command.

    Args:
        args: Parsed command-line arguments.
    """
    config = _build_config(args)
    _setup_logging(config.verbose)

    builder = GraphBuilder(config)
    graph = builder.build()

    detector = CircularDetector(graph)
    cycles = detector.detect(algorithm=getattr(args, "algorithm", "tarjan"))

    if getattr(args, "output", None):
        result = json.dumps(
            {
                "cycles": [
                    {"nodes": c.nodes, "length": c.length, "strength": c.strength}
                    for c in cycles
                ],
                "stats": detector.stats(),
            },
            indent=2,
            ensure_ascii=False,
        )
        Path(args.output).write_text(result, encoding="utf-8")
        logger.info("Results written to %s", args.output)
    else:
        print(detector.summary())

    # Log detailed stats
    logger.info(
        "Detection completed in %d ms using %s",
        detector.stats().get("detection_time_ms", 0),
        detector.stats().get("algorithm_used", "N/A"),
    )


def _cmd_find_unused(args: argparse.Namespace) -> None:
    """Handle the 'find-unused' command.

    Args:
        args: Parsed command-line arguments.
    """
    config = _build_config(args)
    _setup_logging(config.verbose)

    builder = GraphBuilder(config)
    graph = builder.build()

    finder = UnusedDepFinder(graph, config)
    entry_points = getattr(args, "entry_points", []) or None
    unused = finder.find(entry_points=entry_points)

    if getattr(args, "output", None):
        result = json.dumps(
            {
                "unused": sorted(unused),
                "stats": finder.stats(),
            },
            indent=2,
            ensure_ascii=False,
        )
        Path(args.output).write_text(result, encoding="utf-8")
        logger.info("Results written to %s", args.output)
    else:
        print(finder.summary())

    logger.info(
        "Found %d unused dependencies out of %d total",
        finder.stats().get("unused_count", 0),
        finder.stats().get("total_dependencies", 0),
    )


def _cmd_report(args: argparse.Namespace) -> None:
    """Handle the 'report' command.

    Args:
        args: Parsed command-line arguments.
    """
    config = _build_config(args)
    config.output_format = "html"
    _setup_logging(config.verbose)

    builder = GraphBuilder(config)
    graph = builder.build()

    # Detect cycles
    detector = CircularDetector(graph)
    cycles = detector.detect("tarjan")

    # Find unused
    finder = UnusedDepFinder(graph, config)
    unused = finder.find()

    # Generate report
    reporter = HTMLReportGenerator(graph, config, cycles=cycles, unused=unused)
    html = reporter.generate()

    output_path = getattr(
        args, "output", config.output_file or "deps-report.html"
    )
    if output_path:
        Path(output_path).write_text(html, encoding="utf-8")
        logger.info("HTML report written to %s", output_path)
        print(f"Report generated: {os.path.abspath(output_path)}")
    else:
        print(html)


def _cmd_stats(args: argparse.Namespace) -> None:
    """Handle the 'stats' command.

    Args:
        args: Parsed command-line arguments.
    """
    config = _build_config(args)
    _setup_logging(config.verbose)

    builder = GraphBuilder(config)
    graph = builder.build()

    # Detect cycles
    detector = CircularDetector(graph)
    has_cycles = detector.has_cycles()
    if has_cycles:
        cycles = detector.detect("tarjan")
    else:
        cycles = []

    # Count external vs internal
    external_count = sum(
        1 for n in graph.nodes.values() if n.node_type == "external"
    )
    internal_count = graph.node_count() - external_count

    stats = {
        "node_count": graph.node_count(),
        "edge_count": graph.edge_count(),
        "internal_modules": internal_count,
        "external_dependencies": external_count,
        "has_cycles": has_cycles,
        "cycle_count": len(cycles),
        "build_time_ms": builder.stats().get("duration_ms", 0),
        "files_parsed": builder.stats().get("parsed_files", 0),
        "total_files": builder.stats().get("total_files", 0),
    }

    if getattr(args, "format", "text") == "json":
        print(json.dumps(stats, indent=2, ensure_ascii=False))
    else:
        print("=" * 50)
        print("AI-Deps Statistics")
        print("=" * 50)
        print(f"  Project:          {config.project_path.resolve()}")
        print(f"  Total nodes:      {stats['node_count']}")
        print(f"  Total edges:      {stats['edge_count']}")
        print(f"  Internal modules: {stats['internal_modules']}")
        print(f"  External deps:    {stats['external_dependencies']}")
        print(f"  Has cycles:       {stats['has_cycles']}")
        if stats['cycle_count'] > 0:
            print(f"  Cycle count:      {stats['cycle_count']}")
        print(f"  Files parsed:     {stats['files_parsed']} / {stats['total_files']}")
        print(f"  Build time:       {stats['build_time_ms']} ms")
        print("=" * 50)


def _cmd_graph(args: argparse.Namespace) -> None:
    """Handle the 'graph' command.

    Args:
        args: Parsed command-line arguments.
    """
    config = _build_config(args)
    _setup_logging(config.verbose)

    builder = GraphBuilder(config)
    graph = builder.build()

    fmt = getattr(args, "format", "dot")
    max_nodes = getattr(args, "max_nodes", 200)

    if fmt == "json":
        result = json.dumps(graph.to_json(), indent=2, ensure_ascii=False)
    elif fmt == "mermaid":
        gen = MermaidGenerator(graph, config)
        result = gen.generate(max_nodes=max_nodes)
    elif fmt == "dot":
        gen = GraphvizGenerator(graph, config)
        result = gen.generate(max_nodes=max_nodes)
    elif fmt == "csv-edges":
        gen = CSVGenerator(graph)
        result = gen.generate_edges()
    elif fmt == "csv-nodes":
        gen = CSVGenerator(graph)
        result = gen.generate_nodes()
    else:
        logger.error("Unknown format: %s", fmt)
        return

    output_path = getattr(args, "output", None) or config.output_file
    _write_output(result, output_path)


def _cmd_config(args: argparse.Namespace) -> None:
    """Handle the 'config' command.

    Args:
        args: Parsed command-line arguments.
    """
    if getattr(args, "generate", False):
        default_config = {
            "project_path": ".",
            "depth": 0,
            "exclude_patterns": [
                "node_modules/**",
                ".git/**",
                "__pycache__/**",
                "*.pyc",
                "dist/**",
                "build/**",
                "venv/**",
                ".venv/**",
            ],
            "include_patterns": [],
            "language": None,
            "follow_links": False,
            "ignore_errors": True,
            "output_format": "json",
            "output_file": None,
            "verbose": False,
            "cache_results": False,
            "max_file_size": 1048576,
            "alias": {},
        }
        output_path = getattr(args, "output", "ai-deps-config.json")
        Path(output_path).write_text(
            json.dumps(default_config, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Default config written to {output_path}")
    else:
        print("Current configuration:")
        config = _build_config(args)
        for f in fields(config):
            print(f"  {f.name}: {getattr(config, f.name)}")


def _write_output(content: str, output_path: Optional[str] = None) -> None:
    """Write output to a file or stdout.

    Args:
        content: The string content to write.
        output_path: Optional file path. If None, writes to stdout.
    """
    if output_path:
        Path(output_path).write_text(content, encoding="utf-8")
        logger.info("Output written to %s", output_path)
    else:
        print(content)


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point for the AI-Deps CLI.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code (0 for success, 1 for error).
    """
    parser = create_parser()

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1

    # Setup logging
    _setup_logging(verbose=getattr(args, "verbose", False))

    # If no command specified, default to analyze
    if not args.command:
        logger.debug("No command specified, defaulting to 'analyze'")
        args.command = "analyze"
        args.format = "json"
        args.output = None
        args.max_nodes = 100
        args.show_external = True

    try:
        if args.command == "analyze":
            _cmd_analyze(args)
        elif args.command == "detect-circular":
            _cmd_detect_circular(args)
        elif args.command == "find-unused":
            _cmd_find_unused(args)
        elif args.command == "report":
            _cmd_report(args)
        elif args.command == "stats":
            _cmd_stats(args)
        elif args.command == "graph":
            _cmd_graph(args)
        elif args.command == "config":
            _cmd_config(args)
        else:
            logger.error("Unknown command: %s", args.command)
            parser.print_help()
            return 1
    except AiDepsError as exc:
        logger.error("Analysis error: %s", exc)
        return 1
    except SystemExit as exc:
        # argparse calls sys.exit(); return the code directly
        return exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        return 1

    return 0


# ---------------------------------------------------------------------------
# Python entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(main())