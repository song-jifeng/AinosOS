#!/usr/bin/env python3
"""Comprehensive test suite for the AI-Deps dependency analyzer."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Now safe to import ai_deps
from ai_deps import (
    AiDepsConfig,
    CSVGenerator,
    CircularDetector,
    ConfigError,
    CycleInfo,
    DepGraph,
    Edge,
    GraphBuilder,
    GraphError,
    GraphvizGenerator,
    HTMLReportGenerator,
    ImportParser,
    JavaScriptImportParser,
    MermaidGenerator,
    Node,
    ParseError,
    PythonImportParser,
    UnusedDepFinder,
    __version__,
    get_parser_for_file,
    main,
)


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def empty_graph() -> DepGraph:
    """Fixture: an empty dependency graph."""
    return DepGraph()


@pytest.fixture
def simple_graph() -> DepGraph:
    """Fixture: a simple acyclic graph.

    a -> b -> c
    a -> c
    """
    graph = DepGraph()
    graph.add_node(Node(id="a", node_type="file"))
    graph.add_node(Node(id="b", node_type="file"))
    graph.add_node(Node(id="c", node_type="file"))
    graph.add_edge(Edge(source="a", target="b"))
    graph.add_edge(Edge(source="b", target="c"))
    graph.add_edge(Edge(source="a", target="c"))
    return graph


@pytest.fixture
def graph_with_cycle() -> DepGraph:
    """Fixture: a graph with a simple cycle.

    a -> b -> c -> a
    """
    graph = DepGraph()
    graph.add_node(Node(id="a", node_type="file"))
    graph.add_node(Node(id="b", node_type="file"))
    graph.add_node(Node(id="c", node_type="file"))
    graph.add_edge(Edge(source="a", target="b"))
    graph.add_edge(Edge(source="b", target="c"))
    graph.add_edge(Edge(source="c", target="a"))
    return graph


@pytest.fixture
def graph_with_external() -> DepGraph:
    """Fixture: a graph with external dependencies."""
    graph = DepGraph()
    graph.add_node(Node(id="main", node_type="file"))
    graph.add_node(Node(id="utils", node_type="file"))
    graph.add_node(Node(id="numpy", node_type="external"))
    graph.add_node(Node(id="requests", node_type="external"))
    graph.add_edge(Edge(source="main", target="utils"))
    graph.add_edge(Edge(source="main", target="numpy"))
    graph.add_edge(Edge(source="utils", target="requests"))
    return graph


@pytest.fixture
def temp_project() -> Path:
    """Fixture: create a temporary Python project for testing."""
    tmpdir = Path(tempfile.mkdtemp(prefix="ai_deps_test_"))

    # Create main.py
    main_py = tmpdir / "main.py"
    main_py.write_text(textwrap.dedent("""\
        import os
        import sys
        from collections import defaultdict
        from utils.helper import process_data

        def main():
            data = process_data()
            print(data)

        if __name__ == "__main__":
            main()
    """))

    # Create utils directory
    utils_dir = tmpdir / "utils"
    utils_dir.mkdir()
    (utils_dir / "__init__.py").write_text("")

    # Create helper.py
    helper_py = utils_dir / "helper.py"
    helper_py.write_text(textwrap.dedent("""\
        import json
        from pathlib import Path
        from typing import List, Dict, Any

        def process_data() -> Dict[str, Any]:
            return {"status": "ok"}

        def load_config(path: str) -> Dict[str, Any]:
            with open(path) as f:
                return json.load(f)
    """))

    # Create models.py
    models_py = tmpdir / "models.py"
    models_py.write_text(textwrap.dedent("""\
        from dataclasses import dataclass
        from typing import Optional

        @dataclass
        class User:
            id: int
            name: str
            email: Optional[str] = None
    """))

    yield tmpdir

    # Cleanup
    import shutil
    shutil.rmtree(str(tmpdir), ignore_errors=True)


# =========================================================================
# Tests: DepGraph
# =========================================================================


class TestDepGraph:
    """Tests for the DepGraph class."""

    def test_empty_graph(self, empty_graph: DepGraph) -> None:
        """Test that an empty graph has no nodes or edges."""
        assert empty_graph.node_count() == 0
        assert empty_graph.edge_count() == 0
        assert empty_graph.is_empty()
        assert str(empty_graph) == "Dependency Graph with 0 nodes and 0 edges"

    def test_add_node(self, empty_graph: DepGraph) -> None:
        """Test adding nodes to the graph."""
        node = Node(id="test_module", node_type="file", language="python")
        empty_graph.add_node(node)
        assert empty_graph.node_count() == 1
        assert empty_graph.has_node("test_module")
        retrieved = empty_graph.get_node("test_module")
        assert retrieved is not None
        assert retrieved.id == "test_module"
        assert retrieved.node_type == "file"
        assert retrieved.language == "python"

    def test_add_duplicate_node(self, empty_graph: DepGraph) -> None:
        """Test that adding a duplicate node updates its metadata."""
        node1 = Node(id="mod", node_type="file", size=100)
        node2 = Node(id="mod", node_type="file", size=200, language="python")
        empty_graph.add_node(node1)
        empty_graph.add_node(node2)
        assert empty_graph.node_count() == 1
        retrieved = empty_graph.get_node("mod")
        assert retrieved is not None
        # First size should be kept (already set)
        assert retrieved.size == 100
        # Language should be set from second
        assert retrieved.language == "python"

    def test_add_edge(self, empty_graph: DepGraph) -> None:
        """Test adding edges to the graph."""
        edge = Edge(source="a", target="b", weight=1)
        empty_graph.add_edge(edge)
        assert empty_graph.edge_count() == 1
        assert empty_graph.has_edge("a", "b")
        assert empty_graph.has_node("a")
        assert empty_graph.has_node("b")

    def test_add_duplicate_edge(self, empty_graph: DepGraph) -> None:
        """Test that adding a duplicate edge increments weight."""
        empty_graph.add_edge(Edge(source="a", target="b", weight=1))
        empty_graph.add_edge(Edge(source="a", target="b", weight=1))
        assert empty_graph.edge_count() == 1
        # Find the edge
        for e in empty_graph.edges:
            assert e.weight == 2
            break

    def test_add_dependency(self, empty_graph: DepGraph) -> None:
        """Test the convenience method add_dependency."""
        empty_graph.add_dependency("source", "target", weight=3)
        assert empty_graph.has_edge("source", "target")
        for e in empty_graph.edges:
            assert e.weight == 3
            break

    def test_remove_node(self, simple_graph: DepGraph) -> None:
        """Test removing a node and its incident edges."""
        simple_graph.remove_node("b")
        assert not simple_graph.has_node("b")
        assert not simple_graph.has_edge("a", "b")
        assert not simple_graph.has_edge("b", "c")
        assert simple_graph.has_edge("a", "c")

    def test_remove_edge(self, simple_graph: DepGraph) -> None:
        """Test removing an edge."""
        simple_graph.remove_edge("a", "b")
        assert not simple_graph.has_edge("a", "b")
        assert simple_graph.has_edge("b", "c")
        assert simple_graph.has_edge("a", "c")

    def test_successors(self, simple_graph: DepGraph) -> None:
        """Test getting successors of a node."""
        assert simple_graph.successors("a") == {"b", "c"}
        assert simple_graph.successors("b") == {"c"}
        assert simple_graph.successors("c") == set()

    def test_predecessors(self, simple_graph: DepGraph) -> None:
        """Test getting predecessors of a node."""
        assert simple_graph.predecessors("a") == set()
        assert simple_graph.predecessors("b") == {"a"}
        assert simple_graph.predecessors("c") == {"a", "b"}

    def test_subgraph(self, simple_graph: DepGraph) -> None:
        """Test extracting a subgraph."""
        sub = simple_graph.subgraph({"a", "b"})
        assert sub.node_count() == 2
        assert sub.has_node("a")
        assert sub.has_node("b")
        assert not sub.has_node("c")
        assert sub.has_edge("a", "b")

    def test_topological_sort(self, simple_graph: DepGraph) -> None:
        """Test topological sort on an acyclic graph."""
        order = simple_graph.topological_sort()
        # a must come before b and c, b must come before c
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")
        assert order.index("b") < order.index("c")

    def test_topological_sort_with_cycle(self, graph_with_cycle: DepGraph) -> None:
        """Test topological sort raises on a cyclic graph."""
        with pytest.raises(GraphError, match="contains a cycle"):
            graph_with_cycle.topological_sort()

    def test_bfs(self, simple_graph: DepGraph) -> None:
        """Test BFS traversal."""
        result = list(simple_graph.bfs("a"))
        assert len(result) == 3
        assert result[0] == "a"

    def test_dfs(self, simple_graph: DepGraph) -> None:
        """Test DFS traversal."""
        result = list(simple_graph.dfs("a"))
        assert len(result) == 3
        assert result[0] == "a"

    def test_to_json(self, simple_graph: DepGraph) -> None:
        """Test JSON serialization."""
        data = simple_graph.to_json()
        assert "nodes" in data
        assert "edges" in data
        assert "stats" in data
        assert data["stats"]["node_count"] == 3
        assert data["stats"]["edge_count"] == 3

    def test_from_json(self) -> None:
        """Test JSON deserialization."""
        data = {
            "nodes": [
                {"id": "x", "node_type": "file"},
                {"id": "y", "node_type": "file"},
            ],
            "edges": [
                {"source": "x", "target": "y", "weight": 1},
            ],
            "stats": {"node_count": 2, "edge_count": 1},
        }
        graph = DepGraph.from_json(data)
        assert graph.node_count() == 2
        assert graph.edge_count() == 1
        assert graph.has_edge("x", "y")

    def test_transitive_reduction(self, simple_graph: DepGraph) -> None:
        """Test transitive reduction."""
        reduced = simple_graph.transitive_reduction()
        # Edge a->c should be removed (a->b->c exists)
        assert reduced.has_edge("a", "b")
        assert reduced.has_edge("b", "c")
        assert not reduced.has_edge("a", "c")
        assert reduced.node_count() == 3

    def test_edge_hash(self) -> None:
        """Test that edges are hashable."""
        e1 = Edge(source="a", target="b")
        e2 = Edge(source="a", target="b")
        e3 = Edge(source="a", target="c")
        assert hash(e1) == hash(e2)
        assert hash(e1) != hash(e3)

    def test_node_equality(self) -> None:
        """Test node equality."""
        n1 = Node(id="a")
        n2 = Node(id="a")
        n3 = Node(id="b")
        assert n1 == n2
        assert n1 != n3


# =========================================================================
# Tests: Config
# =========================================================================


class TestAiDepsConfig:
    """Tests for the AiDepsConfig class."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = AiDepsConfig()
        assert config.project_path == Path(".")
        assert config.depth == 0
        assert len(config.exclude_patterns) > 0
        assert config.ignore_errors is True
        assert config.verbose is False

    def test_invalid_depth(self) -> None:
        """Test that negative depth raises ConfigError."""
        with pytest.raises(ConfigError, match="depth must be >= 0"):
            AiDepsConfig(depth=-1)

    def test_invalid_format(self) -> None:
        """Test that invalid output format raises ConfigError."""
        with pytest.raises(ConfigError, match="output_format"):
            AiDepsConfig(output_format="invalid")

    def test_from_dict(self) -> None:
        """Test creating config from dictionary."""
        data = {
            "project_path": "/tmp/test",
            "depth": 3,
            "verbose": True,
            "unknown_key": "should_be_ignored",
        }
        config = AiDepsConfig.from_dict(data)
        # On Windows, Path("/tmp/test") becomes \tmp\test
        assert str(config.project_path).replace("\\", "/").endswith("/tmp/test")
        assert config.depth == 3
        assert config.verbose is True
        # Should not have unknown key
        assert not hasattr(config, "unknown_key")

    def test_from_json(self) -> None:
        """Test loading config from JSON file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({"depth": 5, "verbose": True}, f)
            f.flush()
            config_path = f.name

        try:
            config = AiDepsConfig.from_json(config_path)
            assert config.depth == 5
            assert config.verbose is True
        finally:
            os.unlink(config_path)

    def test_from_json_not_found(self) -> None:
        """Test that missing config file raises ConfigError."""
        with pytest.raises(ConfigError, match="not found"):
            AiDepsConfig.from_json("/nonexistent/config.json")

    def test_merge(self) -> None:
        """Test merging two configs."""
        base = AiDepsConfig(depth=2, verbose=False)
        override = AiDepsConfig(depth=5, verbose=True)
        merged = base.merge(override)
        assert merged.depth == 5
        assert merged.verbose is True
        # Other values should remain from base
        assert merged.ignore_errors is True


# =========================================================================
# Tests: PythonImportParser
# =========================================================================


class TestPythonImportParser:
    """Tests for the Python import parser."""

    @pytest.fixture
    def parser(self) -> PythonImportParser:
        return PythonImportParser()

    def test_parse_import(self, parser: PythonImportParser, tmp_path: Path) -> None:
        """Test parsing simple import statements."""
        py_file = tmp_path / "test.py"
        py_file.write_text("import os\nimport sys\nimport json\n")
        imports = parser.parse(py_file)
        modules = [m for m, _ in imports]
        assert "os" in modules
        assert "sys" in modules
        assert "json" in modules
        assert len(imports) == 3

    def test_parse_from_import(self, parser: PythonImportParser, tmp_path: Path) -> None:
        """Test parsing 'from X import Y' statements."""
        py_file = tmp_path / "test.py"
        py_file.write_text(
            "from collections import defaultdict\n"
            "from pathlib import Path\n"
        )
        imports = parser.parse(py_file)
        modules = [m for m, _ in imports]
        assert "collections" in modules
        assert "pathlib" in modules

    def test_parse_import_alias(self, parser: PythonImportParser, tmp_path: Path) -> None:
        """Test parsing import aliases."""
        py_file = tmp_path / "test.py"
        py_file.write_text("import numpy as np\nimport pandas as pd\n")
        imports = parser.parse(py_file)
        modules = [m for m, _ in imports]
        assert "numpy" in modules
        assert "pandas" in modules

    def test_parse_multiline_import(self, parser: PythonImportParser, tmp_path: Path) -> None:
        """Test parsing multiline imports."""
        py_file = tmp_path / "test.py"
        py_file.write_text(
            "from typing import (\n"
            "    List,\n"
            "    Dict,\n"
            "    Optional,\n"
            ")\n"
        )
        imports = parser.parse(py_file)
        modules = [m for m, _ in imports]
        assert "typing" in modules

    def test_parse_syntax_error(self, parser: PythonImportParser, tmp_path: Path) -> None:
        """Test parsing a file with syntax errors."""
        py_file = tmp_path / "broken.py"
        py_file.write_text("import os\nthis is not valid python\nimport sys\n")
        config = AiDepsConfig(ignore_errors=True)
        parser.config = config
        imports = parser.parse(py_file)
        # Should return empty list with ignore_errors=True
        assert len(imports) == 0
        assert parser.stats()["files_failed"] == 1

    def test_parse_syntax_error_raise(self, parser: PythonImportParser, tmp_path: Path) -> None:
        """Test that syntax errors raise ParseError when ignore_errors=False."""
        py_file = tmp_path / "broken.py"
        py_file.write_text("import os\nthis is not valid python\n")
        parser.config = AiDepsConfig(ignore_errors=False)
        with pytest.raises(ParseError, match="Syntax error"):
            parser.parse(py_file)

    def test_parse_file_not_found(self, parser: PythonImportParser) -> None:
        """Test parsing a non-existent file."""
        imports = parser.parse(Path("/nonexistent/file.py"))
        assert len(imports) == 0
        assert parser.stats()["files_failed"] == 1

    def test_can_parse(self, parser: PythonImportParser) -> None:
        """Test file extension detection."""
        assert parser.can_parse(Path("test.py"))
        assert parser.can_parse(Path("test.pyi"))
        assert parser.can_parse(Path("test.pyx"))
        assert not parser.can_parse(Path("test.js"))
        assert not parser.can_parse(Path("test.java"))

    def test_stats(self, parser: PythonImportParser, tmp_path: Path) -> None:
        """Test parser statistics."""
        py_file = tmp_path / "test.py"
        py_file.write_text("import os\nimport sys\n")
        parser.parse(py_file)
        stats = parser.stats()
        assert stats["files_parsed"] == 1
        assert stats["imports_found"] == 2
        assert stats["files_failed"] == 0


# =========================================================================
# Tests: JavaScriptImportParser
# =========================================================================


class TestJavaScriptImportParser:
    """Tests for the JavaScript import parser."""

    @pytest.fixture
    def parser(self) -> JavaScriptImportParser:
        return JavaScriptImportParser()

    def test_es6_import(self, parser: JavaScriptImportParser, tmp_path: Path) -> None:
        """Test parsing ES6 import statements."""
        js_file = tmp_path / "test.js"
        js_file.write_text(
            "import React from 'react';\n"
            "import { useState } from 'react';\n"
            "import * as axios from 'axios';\n"
        )
        imports = parser.parse(js_file)
        modules = [m for m, _ in imports]
        assert "react" in modules
        assert "axios" in modules

    def test_require(self, parser: JavaScriptImportParser, tmp_path: Path) -> None:
        """Test parsing require() calls."""
        js_file = tmp_path / "test.js"
        js_file.write_text(
            "const fs = require('fs');\n"
            "const path = require('path');\n"
        )
        imports = parser.parse(js_file)
        modules = [m for m, _ in imports]
        assert "fs" in modules
        assert "path" in modules

    def test_dynamic_import(self, parser: JavaScriptImportParser, tmp_path: Path) -> None:
        """Test parsing dynamic import() expressions."""
        js_file = tmp_path / "test.js"
        js_file.write_text(
            "const module = await import('./lazy.js');\n"
        )
        imports = parser.parse(js_file)
        modules = [m for m, _ in imports]
        assert "./lazy.js" in modules or "lazy" in modules or "./lazy" in modules

    def test_export_from(self, parser: JavaScriptImportParser, tmp_path: Path) -> None:
        """Test parsing re-export statements."""
        js_file = tmp_path / "test.js"
        js_file.write_text("export { fetchData } from './api';\n")
        imports = parser.parse(js_file)
        assert len(imports) > 0

    def test_can_parse(self, parser: JavaScriptImportParser) -> None:
        """Test file extension detection."""
        assert parser.can_parse(Path("test.js"))
        assert parser.can_parse(Path("test.jsx"))
        assert parser.can_parse(Path("test.mjs"))
        assert parser.can_parse(Path("test.cjs"))
        assert not parser.can_parse(Path("test.py"))
        assert not parser.can_parse(Path("test.ts"))


# =========================================================================
# Tests: GraphBuilder
# =========================================================================


class TestGraphBuilder:
    """Tests for the GraphBuilder class."""

    def test_build_empty_project(self, tmp_path: Path) -> None:
        """Test building a graph from an empty directory."""
        config = AiDepsConfig(project_path=tmp_path)
        builder = GraphBuilder(config)
        graph = builder.build()
        assert graph.is_empty()

    def test_build_python_project(self, temp_project: Path) -> None:
        """Test building a graph from a Python project."""
        config = AiDepsConfig(project_path=temp_project)
        builder = GraphBuilder(config)
        graph = builder.build()
        assert graph.node_count() >= 3  # main, utils.helper, models
        assert graph.edge_count() >= 2  # main -> utils.helper, etc.

    def test_build_python_project_internal_deps(self, temp_project: Path) -> None:
        """Test that internal dependencies are detected."""
        config = AiDepsConfig(project_path=temp_project)
        builder = GraphBuilder(config)
        graph = builder.build()
        # main.py should depend on utils.helper
        has_main = any("main" in n for n in graph.nodes)
        has_helper = any("helper" in n for n in graph.nodes)
        assert has_main or has_helper

    def test_build_with_exclude(self, temp_project: Path) -> None:
        """Test that exclude patterns work."""
        # Create a node_modules directory that should be excluded
        node_modules = temp_project / "node_modules"
        node_modules.mkdir()
        (node_modules / "bad.js").write_text("require('something');")

        config = AiDepsConfig(
            project_path=temp_project,
            exclude_patterns=["node_modules/**"],
        )
        builder = GraphBuilder(config)
        graph = builder.build()
        # Should not contain node_modules files
        for node_id in graph.nodes:
            assert "node_modules" not in node_id

    def test_build_with_include(self, temp_project: Path) -> None:
        """Test that include patterns work."""
        config = AiDepsConfig(
            project_path=temp_project,
            include_patterns=["*.py"],
        )
        builder = GraphBuilder(config)
        graph = builder.build()
        # Should include .py files
        assert graph.node_count() >= 1

    def test_build_stats(self, temp_project: Path) -> None:
        """Test that builder statistics are populated."""
        config = AiDepsConfig(project_path=temp_project)
        builder = GraphBuilder(config)
        builder.build()
        stats = builder.stats()
        assert stats["total_files"] > 0
        assert stats["parsed_files"] > 0
        assert stats["duration_ms"] >= 0

    def test_build_invalid_path(self) -> None:
        """Test that building on an invalid path raises GraphError."""
        config = AiDepsConfig(project_path=Path("/nonexistent/path/xyz123"))
        builder = GraphBuilder(config)
        with pytest.raises(GraphError, match="does not exist"):
            builder.build()


# =========================================================================
# Tests: CircularDetector
# =========================================================================


class TestCircularDetector:
    """Tests for the CircularDetector class."""

    def test_no_cycles(self, simple_graph: DepGraph) -> None:
        """Test that no cycles are detected in an acyclic graph."""
        detector = CircularDetector(simple_graph)
        assert not detector.has_cycles()
        cycles = detector.detect("dfs")
        assert len(cycles) == 0

    def test_dfs_detection(self, graph_with_cycle: DepGraph) -> None:
        """Test DFS cycle detection."""
        detector = CircularDetector(graph_with_cycle)
        assert detector.has_cycles()
        cycles = detector.detect("dfs")
        assert len(cycles) >= 1
        # Check cycle content
        cycle_nodes = set(cycles[0].nodes)
        assert "a" in cycle_nodes
        assert "b" in cycle_nodes
        assert "c" in cycle_nodes

    def test_tarjan_detection(self, graph_with_cycle: DepGraph) -> None:
        """Test Tarjan's SCC cycle detection."""
        detector = CircularDetector(graph_with_cycle)
        cycles = detector.detect("tarjan")
        assert len(cycles) >= 1
        assert detector.stats()["algorithm_used"] == "Tarjan"

    def test_self_loop(self, empty_graph: DepGraph) -> None:
        """Test detection of self-loop cycles."""
        empty_graph.add_node(Node(id="a"))
        empty_graph.add_edge(Edge(source="a", target="a"))
        detector = CircularDetector(empty_graph)
        cycles = detector.detect("tarjan")
        assert len(cycles) >= 1

    def test_complex_cycle(self) -> None:
        """Test detection of a more complex cycle."""
        graph = DepGraph()
        for node_id in ["a", "b", "c", "d", "e"]:
            graph.add_node(Node(id=node_id))
        # a -> b -> c -> d -> e -> c (cycle: c -> d -> e -> c)
        graph.add_edge(Edge(source="a", target="b"))
        graph.add_edge(Edge(source="b", target="c"))
        graph.add_edge(Edge(source="c", target="d"))
        graph.add_edge(Edge(source="d", target="e"))
        graph.add_edge(Edge(source="e", target="c"))

        detector = CircularDetector(graph)
        cycles = detector.detect("tarjan")
        assert len(cycles) >= 1

    def test_cycle_info(self, graph_with_cycle: DepGraph) -> None:
        """Test CycleInfo dataclass."""
        detector = CircularDetector(graph_with_cycle)
        cycles = detector.detect("dfs")
        assert len(cycles) >= 1
        cycle = cycles[0]
        assert len(cycle.nodes) >= 2
        assert cycle.length >= 2
        assert cycle.strength in ("high", "medium", "low")
        # String representation should include nodes
        assert "->" in str(cycle)

    def test_invalid_algorithm(self, simple_graph: DepGraph) -> None:
        """Test that invalid algorithm name raises ValueError."""
        detector = CircularDetector(simple_graph)
        with pytest.raises(ValueError, match="Unknown algorithm"):
            detector.detect("invalid")

    def test_summary(self, graph_with_cycle: DepGraph) -> None:
        """Test the summary output."""
        detector = CircularDetector(graph_with_cycle)
        detector.detect("tarjan")
        summary = detector.summary()
        assert "Found" in summary
        assert "circular" in summary

    def test_summary_no_cycles(self, simple_graph: DepGraph) -> None:
        """Test summary when no cycles exist."""
        detector = CircularDetector(simple_graph)
        summary = detector.summary()
        assert "No circular dependencies" in summary


# =========================================================================
# Tests: UnusedDepFinder
# =========================================================================


class TestUnusedDepFinder:
    """Tests for the UnusedDepFinder class."""

    def test_find_by_degree(self, empty_graph: DepGraph) -> None:
        """Test degree-based unused detection."""
        # Create a graph with an isolated node (no predecessors, no successors)
        empty_graph.add_node(Node(id="used", node_type="file"))
        empty_graph.add_node(Node(id="unused", node_type="file"))
        empty_graph.add_dependency("used", "dep")
        # 'unused' has no predecessors and no successors - should be detected
        finder = UnusedDepFinder(empty_graph)
        unused = finder.find_by_degree()
        assert "unused" in unused
        # 'used' has outgoing edges so it's not unused by degree
        # (it looks like an entry point)
        assert "used" not in unused

    def test_orphaned_external(self, empty_graph: DepGraph) -> None:
        """Test orphaned external detection."""
        # Create graph with an external node that has no internal predecessor
        empty_graph.add_node(Node(id="main", node_type="file"))
        empty_graph.add_node(Node(id="used_external", node_type="external"))
        empty_graph.add_node(Node(id="orphaned_external", node_type="external"))
        empty_graph.add_dependency("main", "used_external")
        # orphaned_external has no predecessors - should be detected
        finder = UnusedDepFinder(empty_graph)
        orphaned = finder.find_orphaned_external()
        assert "orphaned_external" in orphaned
        assert "used_external" not in orphaned

    def test_reachability(self, graph_with_external: DepGraph) -> None:
        """Test reachability-based unused detection."""
        finder = UnusedDepFinder(graph_with_external)
        unused = finder.find_unused_by_reachability(entry_points=["main"])
        # Everything reachable from main should be used
        assert "main" not in unused
        assert "utils" not in unused

    def test_find_no_entry_points(self, simple_graph: DepGraph) -> None:
        """Test find with no entry points."""
        finder = UnusedDepFinder(simple_graph)
        unused = finder.find(entry_points=None)
        # Should still find some unused nodes
        assert isinstance(unused, set)

    def test_find_with_entry_points(self, graph_with_external: DepGraph) -> None:
        """Test comprehensive find with entry points."""
        finder = UnusedDepFinder(graph_with_external)
        unused = finder.find(entry_points=["main"])
        # main is an entry point, so it should not be unused
        assert "main" not in unused

    def test_stats(self, simple_graph: DepGraph) -> None:
        """Test finder statistics."""
        finder = UnusedDepFinder(simple_graph)
        finder.find_by_degree()
        stats = finder.stats()
        assert "analysis_time_ms" in stats
        assert "unused_count" in stats

    def test_summary(self, empty_graph: DepGraph) -> None:
        """Test summary output."""
        empty_graph.add_node(Node(id="unused_node", node_type="file"))
        finder = UnusedDepFinder(empty_graph)
        finder.find_by_degree()
        summary = finder.summary()
        assert "Found" in summary
        assert "unused_node" in summary

    def test_summary_no_unused(self, empty_graph: DepGraph) -> None:
        """Test summary when no unused dependencies."""
        finder = UnusedDepFinder(empty_graph)
        finder.find_by_degree()
        summary = finder.summary()
        assert "No unused dependencies" in summary


# =========================================================================
# Tests: MermaidGenerator
# =========================================================================


class TestMermaidGenerator:
    """Tests for the MermaidGenerator class."""

    def test_empty_graph(self, empty_graph: DepGraph) -> None:
        """Test generating Mermaid for an empty graph."""
        gen = MermaidGenerator(empty_graph)
        output = gen.generate()
        assert "```mermaid" in output
        assert "No dependencies found" in output

    def test_simple_graph(self, simple_graph: DepGraph) -> None:
        """Test generating Mermaid for a simple graph."""
        gen = MermaidGenerator(simple_graph)
        output = gen.generate()
        assert "```mermaid" in output
        assert "flowchart" in output
        assert "a" in output
        assert "b" in output
        assert "c" in output
        assert "-->" in output

    def test_graph_with_cycle(self, graph_with_cycle: DepGraph) -> None:
        """Test that cycle nodes get styling."""
        gen = MermaidGenerator(graph_with_cycle)
        output = gen.generate()
        assert "fill:#ff6b6b" in output

    def test_direction(self, simple_graph: DepGraph) -> None:
        """Test graph direction."""
        gen = MermaidGenerator(simple_graph)
        output_lr = gen.generate(direction="LR")
        assert "flowchart LR" in output_lr
        output_td = gen.generate(direction="TD")
        assert "flowchart TD" in output_td

    def test_subgraphs(self, graph_with_external: DepGraph) -> None:
        """Test subgraph grouping."""
        gen = MermaidGenerator(graph_with_external)
        output = gen.generate(group_by_type=True)
        assert "subgraph" in output

    def test_safe_id(self) -> None:
        """Test safe ID generation."""
        assert MermaidGenerator._safe_id("a/b/c") == "a_b_c"
        assert MermaidGenerator._safe_id("123") == "n_123"
        assert MermaidGenerator._safe_id("") == "node"

    def test_node_label(self) -> None:
        """Test node label generation."""
        assert MermaidGenerator._node_label("a.b.c") == "a.b.c"
        assert "..." in MermaidGenerator._node_label("a.b.c.d.e")


# =========================================================================
# Tests: GraphvizGenerator
# =========================================================================


class TestGraphvizGenerator:
    """Tests for the GraphvizGenerator class."""

    def test_empty_graph(self, empty_graph: DepGraph) -> None:
        """Test generating DOT for an empty graph."""
        gen = GraphvizGenerator(empty_graph)
        output = gen.generate()
        assert "digraph" in output
        assert "No dependencies found" in output

    def test_simple_graph(self, simple_graph: DepGraph) -> None:
        """Test generating DOT for a simple graph."""
        gen = GraphvizGenerator(simple_graph)
        output = gen.generate()
        assert "digraph" in output
        assert "rankdir" in output
        assert "a" in output
        assert "b" in output
        assert "c" in output
        assert "->" in output

    def test_graph_with_external(self, graph_with_external: DepGraph) -> None:
        """Test DOT output with external nodes."""
        gen = GraphvizGenerator(graph_with_external)
        output = gen.generate()
        assert "numpy" in output or "requests" in output

    def test_graph_with_cycle(self, graph_with_cycle: DepGraph) -> None:
        """Test that cycle nodes get styling."""
        gen = GraphvizGenerator(graph_with_cycle)
        output = gen.generate()
        assert "fillcolor" in output

    def test_max_nodes(self, simple_graph: DepGraph) -> None:
        """Test max_nodes parameter."""
        gen = GraphvizGenerator(simple_graph)
        output = gen.generate(max_nodes=2)
        # Should still work with fewer nodes
        assert "digraph" in output


# =========================================================================
# Tests: CSVGenerator
# =========================================================================


class TestCSVGenerator:
    """Tests for the CSVGenerator class."""

    def test_generate_edges(self, simple_graph: DepGraph) -> None:
        """Test generating edges CSV."""
        gen = CSVGenerator(simple_graph)
        csv_output = gen.generate_edges()
        assert "source,target,weight" in csv_output
        assert "a,b,1" in csv_output
        assert "b,c,1" in csv_output

    def test_generate_nodes(self, simple_graph: DepGraph) -> None:
        """Test generating nodes CSV."""
        gen = CSVGenerator(simple_graph)
        csv_output = gen.generate_nodes()
        assert "id,file_path,node_type" in csv_output
        assert 'a' in csv_output
        assert 'b' in csv_output
        assert 'c' in csv_output

    def test_edges_to_file(self, simple_graph: DepGraph, tmp_path: Path) -> None:
        """Test writing edges CSV to a file."""
        output = tmp_path / "edges.csv"
        gen = CSVGenerator(simple_graph)
        gen.generate_edges(output=str(output))
        assert output.exists()
        content = output.read_text()
        assert "source,target,weight" in content


# =========================================================================
# Tests: HTMLReportGenerator
# =========================================================================


class TestHTMLReportGenerator:
    """Tests for the HTMLReportGenerator class."""

    def test_generate_basic(self, simple_graph: DepGraph) -> None:
        """Test basic HTML report generation."""
        gen = HTMLReportGenerator(simple_graph)
        html = gen.generate()
        assert "<!DOCTYPE html>" in html
        assert "AI-Deps" in html
        assert "Dependency Analysis Report" in html
        assert "Analysis Summary" in html

    def test_with_cycles(self, graph_with_cycle: DepGraph) -> None:
        """Test HTML report with cycle information."""
        detector = CircularDetector(graph_with_cycle)
        cycles = detector.detect("tarjan")
        gen = HTMLReportGenerator(graph_with_cycle, cycles=cycles)
        html = gen.generate()
        assert "Circular" in html
        assert "high" in html or "medium" in html or "low" in html

    def test_with_unused(self, simple_graph: DepGraph) -> None:
        """Test HTML report with unused dependency information."""
        finder = UnusedDepFinder(simple_graph)
        unused = finder.find_by_degree()
        gen = HTMLReportGenerator(simple_graph, unused=unused)
        html = gen.generate()
        assert "Unused" in html

    def test_stats_section(self, simple_graph: DepGraph) -> None:
        """Test the stats section of the report."""
        gen = HTMLReportGenerator(simple_graph)
        html = gen.generate()
        assert "Total Nodes" in html
        assert "Total Edges" in html
        assert "3" in html  # 3 nodes

    def test_dependency_table(self, simple_graph: DepGraph) -> None:
        """Test the dependency table in the report."""
        gen = HTMLReportGenerator(simple_graph)
        html = gen.generate()
        assert "Module Dependencies" in html
        assert "Dependencies" in html
        assert "Dependents" in html


# =========================================================================
# Tests: ImportParser (base class)
# =========================================================================


class TestImportParser:
    """Tests for the base ImportParser class."""

    def test_parse_not_implemented(self) -> None:
        """Test that base class parse raises NotImplementedError."""
        parser = ImportParser()
        with pytest.raises(NotImplementedError):
            parser.parse(Path("test.py"))

    def test_can_parse_unknown(self) -> None:
        """Test that base class can_parse returns False."""
        parser = ImportParser()
        assert not parser.can_parse(Path("test.py"))
        assert not parser.can_parse(Path("test.js"))

    def test_resolve_alias(self) -> None:
        """Test alias resolution."""
        config = AiDepsConfig(alias={"numpy": "np", "torch": "pt"})
        parser = ImportParser(config=config)
        assert parser.resolve_alias("numpy") == "np"
        assert parser.resolve_alias("torch") == "pt"
        assert parser.resolve_alias("unknown") == "unknown"


# =========================================================================
# Tests: get_parser_for_file
# =========================================================================


class TestGetParserForFile:
    """Tests for the get_parser_for_file function."""

    def test_python(self) -> None:
        """Test getting Python parser."""
        parser = get_parser_for_file(Path("test.py"))
        assert isinstance(parser, PythonImportParser)

    def test_javascript(self) -> None:
        """Test getting JavaScript parser."""
        parser = get_parser_for_file(Path("test.js"))
        assert isinstance(parser, JavaScriptImportParser)

    def test_unknown(self) -> None:
        """Test getting parser for unknown extension."""
        parser = get_parser_for_file(Path("test.xyz"))
        assert parser is None


# =========================================================================
# Tests: Integration Tests
# =========================================================================


class TestIntegration:
    """Integration tests for the AI-Deps analyzer."""

    def test_end_to_end_analysis(self, temp_project: Path) -> None:
        """Test end-to-end analysis of a project."""
        config = AiDepsConfig(project_path=temp_project)
        builder = GraphBuilder(config)
        graph = builder.build()

        # Verify graph structure
        assert graph.node_count() > 0
        assert graph.edge_count() > 0

        # Detect cycles
        detector = CircularDetector(graph)
        assert not detector.has_cycles()  # This project is acyclic

        # Find unused
        finder = UnusedDepFinder(graph, config)
        unused = finder.find()
        assert isinstance(unused, set)

        # Generate visualizations
        mermaid = MermaidGenerator(graph, config)
        mermaid_output = mermaid.generate()
        assert "```mermaid" in mermaid_output

        dot = GraphvizGenerator(graph, config)
        dot_output = dot.generate()
        assert "digraph" in dot_output

        # Generate report
        report = HTMLReportGenerator(graph, config)
        html = report.generate()
        assert "<!DOCTYPE html>" in html

    def test_cycle_project(self, tmp_path: Path) -> None:
        """Test analysis of a project with circular dependencies."""
        # Create a project with circular imports
        a_py = tmp_path / "a.py"
        a_py.write_text("import b\n")
        b_py = tmp_path / "b.py"
        b_py.write_text("import c\n")
        c_py = tmp_path / "c.py"
        c_py.write_text("import a\n")

        config = AiDepsConfig(project_path=tmp_path, ignore_errors=True)
        builder = GraphBuilder(config)
        graph = builder.build()

        detector = CircularDetector(graph)
        cycles = detector.detect("tarjan")
        assert len(cycles) >= 1

    def test_js_project_analysis(self, tmp_path: Path) -> None:
        """Test analysis of a JavaScript project."""
        # Create a JS project
        index_js = tmp_path / "index.js"
        index_js.write_text(
            "import { greet } from './utils';\n"
            "import React from 'react';\n"
        )
        utils_js = tmp_path / "utils.js"
        utils_js.write_text(
            "const fs = require('fs');\n"
            "export function greet(name) {\n"
            "  return `Hello, ${name}`;\n"
            "}\n"
        )

        config = AiDepsConfig(project_path=tmp_path, ignore_errors=True)
        builder = GraphBuilder(config)
        graph = builder.build()
        assert graph.node_count() >= 2


# =========================================================================
# Tests: CLI / main()
# =========================================================================


class TestCLI:
    """Tests for the CLI entry point."""

    def test_analyze_command(self, temp_project: Path) -> None:
        """Test the analyze command."""
        exit_code = main([
            "analyze",
            "--path", str(temp_project),
            "--format", "json",
        ])
        assert exit_code == 0

    def test_analyze_command_mermaid(self, temp_project: Path) -> None:
        """Test the analyze command with mermaid output."""
        exit_code = main([
            "analyze",
            "--path", str(temp_project),
            "--format", "mermaid",
        ])
        assert exit_code == 0

    def test_analyze_command_dot(self, temp_project: Path) -> None:
        """Test the analyze command with dot output."""
        exit_code = main([
            "analyze",
            "--path", str(temp_project),
            "--format", "dot",
        ])
        assert exit_code == 0

    def test_detect_circular_command(self, temp_project: Path) -> None:
        """Test the detect-circular command."""
        exit_code = main([
            "detect-circular",
            "--path", str(temp_project),
        ])
        assert exit_code == 0

    def test_find_unused_command(self, temp_project: Path) -> None:
        """Test the find-unused command."""
        exit_code = main([
            "find-unused",
            "--path", str(temp_project),
        ])
        assert exit_code == 0

    def test_stats_command(self, temp_project: Path) -> None:
        """Test the stats command."""
        exit_code = main([
            "stats",
            "--path", str(temp_project),
        ])
        assert exit_code == 0

    def test_stats_command_json(self, temp_project: Path) -> None:
        """Test the stats command with JSON output."""
        exit_code = main([
            "stats",
            "--path", str(temp_project),
            "--format", "json",
        ])
        assert exit_code == 0

    def test_report_command(self, temp_project: Path) -> None:
        """Test the report command."""
        report_path = temp_project / "report.html"
        exit_code = main([
            "report",
            "--path", str(temp_project),
            "--output", str(report_path),
        ])
        assert exit_code == 0
        assert report_path.exists()

    def test_graph_command(self, temp_project: Path) -> None:
        """Test the graph command."""
        exit_code = main([
            "graph",
            "--path", str(temp_project),
            "--format", "json",
        ])
        assert exit_code == 0

    def test_config_command(self, temp_project: Path) -> None:
        """Test the config command."""
        exit_code = main([
            "config",
            "--generate",
            "--output", str(temp_project / "config.json"),
        ])
        assert exit_code == 0
        assert (temp_project / "config.json").exists()

    def test_version(self) -> None:
        """Test --version flag."""
        exit_code = main(["--version"])
        assert exit_code == 0

    def test_verbose(self, temp_project: Path) -> None:
        """Test verbose mode."""
        exit_code = main([
            "analyze",
            "--path", str(temp_project),
            "--verbose",
        ])
        assert exit_code == 0

    def test_no_command(self, temp_project: Path) -> None:
        """Test running with no command (should default to analyze)."""
        exit_code = main(["--path", str(temp_project)])
        assert exit_code == 0

    def test_unknown_command(self) -> None:
        """Test unknown command."""
        exit_code = main(["unknown-command"])
        assert exit_code == 2

    def test_invalid_path(self) -> None:
        """Test with invalid path."""
        exit_code = main([
            "analyze",
            "--path", "/nonexistent/path/xyz_123_test",
        ])
        assert exit_code == 1

    def test_output_to_file(self, temp_project: Path) -> None:
        """Test writing output to a file."""
        output_file = temp_project / "output.json"
        exit_code = main([
            "analyze",
            "--path", str(temp_project),
            "--format", "json",
            "--output", str(output_file),
        ])
        assert exit_code == 0
        assert output_file.exists()
        # Verify it's valid JSON
        data = json.loads(output_file.read_text())
        assert "nodes" in data
        assert "edges" in data


# =========================================================================
# Tests: Edge Cases & Error Handling
# =========================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_graph_with_self_loop(self) -> None:
        """Test handling of self-loop dependencies."""
        graph = DepGraph()
        graph.add_node(Node(id="a"))
        graph.add_edge(Edge(source="a", target="a"))
        assert graph.edge_count() == 1
        assert graph.has_edge("a", "a")
        # Topological sort should fail
        with pytest.raises(GraphError):
            graph.topological_sort()

    def test_disconnected_graph(self) -> None:
        """Test a graph with disconnected components."""
        graph = DepGraph()
        graph.add_node(Node(id="a"))
        graph.add_node(Node(id="b"))
        graph.add_node(Node(id="c"))
        graph.add_edge(Edge(source="a", target="b"))
        # c is disconnected
        order = graph.topological_sort()
        assert len(order) == 3

    def test_large_graph_performance(self) -> None:
        """Test with a larger graph for performance."""
        graph = DepGraph()
        n = 100
        for i in range(n):
            graph.add_node(Node(id=f"node_{i}"))
        for i in range(n - 1):
            graph.add_edge(Edge(source=f"node_{i}", target=f"node_{i+1}"))
        assert graph.node_count() == n
        assert graph.edge_count() == n - 1
        order = graph.topological_sort()
        assert len(order) == n

    def test_empty_file_parsing(self, tmp_path: Path) -> None:
        """Test parsing an empty file."""
        py_file = tmp_path / "empty.py"
        py_file.write_text("")
        parser = PythonImportParser()
        imports = parser.parse(py_file)
        assert len(imports) == 0

    def test_binary_file_parsing(self, tmp_path: Path) -> None:
        """Test parsing a binary file (should not crash)."""
        bin_file = tmp_path / "binary.py"
        bin_file.write_bytes(b"\x00\x01\x02\x03\xff\xfe")
        parser = PythonImportParser(AiDepsConfig(ignore_errors=True))
        imports = parser.parse(bin_file)
        # Should either return empty or raise ParseError that's caught
        assert isinstance(imports, list)

    def test_version_string(self) -> None:
        """Test that version is a valid string."""
        assert isinstance(__version__, str)
        parts = __version__.split(".")
        assert len(parts) == 3


# =========================================================================
# Tests: Node and Edge dataclasses
# =========================================================================


class TestNodeEdge:
    """Tests for Node and Edge dataclasses."""

    def test_node_defaults(self) -> None:
        """Test Node default values."""
        node = Node(id="test")
        assert node.node_type == "module"
        assert node.file_path is None
        assert node.language is None
        assert node.size == 0
        assert node.metadata == {}

    def test_node_hash(self) -> None:
        """Test Node hashing."""
        n1 = Node(id="a")
        n2 = Node(id="a")
        n3 = Node(id="b")
        assert hash(n1) == hash(n2)
        assert hash(n1) != hash(n3)

    def test_edge_defaults(self) -> None:
        """Test Edge default values."""
        edge = Edge(source="a", target="b")
        assert edge.weight == 1
        assert edge.metadata == {}

    def test_edge_hash(self) -> None:
        """Test Edge hashing."""
        e1 = Edge(source="a", target="b")
        e2 = Edge(source="a", target="b")
        e3 = Edge(source="b", target="a")
        assert hash(e1) == hash(e2)
        assert hash(e1) != hash(e3)

    def test_cycle_info_defaults(self) -> None:
        """Test CycleInfo default values."""
        info = CycleInfo(nodes=["a", "b", "c"])
        assert info.length == 3
        assert info.strength == "high"
        assert "->" in str(info)

    def test_cycle_info_strength(self) -> None:
        """Test CycleInfo strength calculation."""
        small = CycleInfo(nodes=["a", "b"])
        assert small.strength == "high"
        medium = CycleInfo(nodes=["a", "b", "c", "d", "e"])
        assert medium.strength == "medium"
        large = CycleInfo(nodes=["a", "b", "c", "d", "e", "f", "g"])
        assert large.strength == "low"