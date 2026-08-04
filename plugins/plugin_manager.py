"""
Ainos OS - Plugin Manager
=========================
Comprehensive plugin lifecycle manager supporting discovery, loading,
configuration, isolation, hot-reloading, and CLI management.

This module provides:
- PluginManager: Central orchestrator for all plugin operations
- PluginDiscovery: Scans filesystem for plugin packages
- PluginLifecycle: Manages init/start/stop/cleanup sequences
- PluginDependencyResolver: Resolves plugin dependency graphs
- PluginConfigManager: Persists and manages plugin configurations
- PluginIsolation: Runs plugins in subprocesses with restricted environments
- PluginCLI: Command-line interface for plugin management
- PluginHotReload: Watches plugin source files and reloads on change
"""

import argparse
import ast
import copy
import hashlib
import importlib
import importlib.util
import inspect
import json
import logging
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import traceback
import types
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Type,
    Union,
)

from .api import (
    API_VERSION,
    API_VERSION_MAJOR,
    API_VERSION_MINOR,
    Event,
    EventBus,
    EventPriority,
    HookPriority,
    HookRegistry,
    PluginAPI,
    PluginBase,
    PluginConfig,
    PluginMetadata,
    PluginState,
    PluginException,
    PluginLoadError,
    PluginDependencyError,
    PluginVersionError,
    ServiceRegistry,
)

logger = logging.getLogger("ainos.plugins.manager")

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

PLUGIN_ENTRY_POINT = "plugin.py"
PLUGIN_MANIFEST_FILE = "plugin.json"
PLUGIN_YAML_MANIFEST = "plugin.yaml"
PLUGIN_CONFIG_DIR = "config"
PLUGIN_DATA_DIR = "data"
DEFAULT_PLUGIN_DIRS = ["plugins"]
WATCH_INTERVAL_SEC = 2.0
MAX_RESTART_ATTEMPTS = 5
RESTART_BACKOFF_SEC = 2.0
ISOLATION_TIMEOUT_SEC = 30


# ──────────────────────────────────────────────
# Plugin Descriptor
# ──────────────────────────────────────────────

@dataclass
class PluginDescriptor:
    """
    Complete descriptor for a discovered plugin.

    This is the internal representation of a plugin, combining
    metadata from the filesystem manifest with runtime state.
    """
    name: str
    version: str
    path: str
    module_path: str
    entry_point: str
    metadata: PluginMetadata
    config: PluginConfig
    instance: Optional[PluginBase] = None
    state: PluginState = PluginState.CREATED
    error: Optional[str] = None
    pid: Optional[int] = None
    load_time: Optional[float] = None
    start_time: Optional[float] = None
    restart_count: int = 0
    last_error_time: Optional[float] = None
    source_hash: Optional[str] = None
    dependencies_resolved: bool = False
    is_isolated: bool = False
    isolation_process: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for API responses."""
        return {
            "name": self.name,
            "version": self.version,
            "path": self.path,
            "state": self.state.value,
            "error": self.error,
            "pid": self.pid,
            "load_time": self.load_time,
            "start_time": self.start_time,
            "restart_count": self.restart_count,
            "dependencies_resolved": self.dependencies_resolved,
            "is_isolated": self.is_isolated,
            "metadata": {
                "name": self.metadata.name,
                "version": self.metadata.version,
                "description": self.metadata.description,
                "author": self.metadata.author,
                "license": self.metadata.license,
                "api_version": self.metadata.api_version,
                "tags": self.metadata.tags,
                "dependencies": self.metadata.dependencies,
                "provides_services": self.metadata.provides_services,
                "requires_services": self.metadata.requires_services,
                "hooks": self.metadata.hooks,
                "events_listen": self.metadata.events_listen,
                "events_emit": self.metadata.events_emit,
                "permissions": self.metadata.permissions,
            },
            "config": {
                "enabled": self.config.enabled,
                "isolation": self.config.isolation,
                "settings": self.config.settings,
                "resource_limits": self.config.resource_limits,
            },
        }


# ──────────────────────────────────────────────
# Plugin Discovery
# ──────────────────────────────────────────────

class PluginDiscovery:
    """
    Discovers plugins from the filesystem.

    Scans configured directories for plugin packages and extracts
    their metadata from manifests and source code introspection.
    Supports multiple plugin layouts:
    - Single-file plugins: plugins/myplugin/plugin.py
    - Package plugins: plugins/myplugin/ with __init__.py
    - Manifest-based: plugins/myplugin/plugin.json + plugin.py
    """

    def __init__(self, plugin_dirs: Optional[List[str]] = None):
        self._plugin_dirs = plugin_dirs or list(DEFAULT_PLUGIN_DIRS)
        self._plugin_dirs = [os.path.abspath(d) for d in self._plugin_dirs]
        self._cache: Dict[str, PluginDescriptor] = {}
        self._lock = threading.RLock()

    def add_plugin_dir(self, directory: str) -> None:
        """Add a directory to search for plugins."""
        abs_dir = os.path.abspath(directory)
        if abs_dir not in self._plugin_dirs:
            self._plugin_dirs.append(abs_dir)
            logger.info(f"Added plugin directory: {abs_dir}")

    def remove_plugin_dir(self, directory: str) -> None:
        """Remove a directory from the plugin search path."""
        abs_dir = os.path.abspath(directory)
        if abs_dir in self._plugin_dirs:
            self._plugin_dirs.remove(abs_dir)

    @property
    def plugin_dirs(self) -> List[str]:
        """List of plugin directories being scanned."""
        return list(self._plugin_dirs)

    def discover_all(self, clear_cache: bool = False) -> Dict[str, PluginDescriptor]:
        """
        Discover all plugins in all configured directories.

        Args:
            clear_cache: If True, re-scan all directories

        Returns:
            Dict mapping plugin name to PluginDescriptor
        """
        if clear_cache:
            with self._lock:
                self._cache.clear()

        discovered: Dict[str, PluginDescriptor] = {}

        for plugin_dir in self._plugin_dirs:
            if not os.path.isdir(plugin_dir):
                logger.debug(f"Plugin directory not found: {plugin_dir}")
                continue

            dir_discovered = self._discover_directory(plugin_dir)
            for name, desc in dir_discovered.items():
                if name in discovered:
                    logger.warning(
                        f"Duplicate plugin '{name}' found in "
                        f"'{desc.path}' and '{discovered[name].path}'"
                    )
                discovered[name] = desc

        # Update cache
        with self._lock:
            self._cache.update(discovered)

        return discovered

    def discover_plugin(self, plugin_path: str) -> Optional[PluginDescriptor]:
        """
        Discover a single plugin by path.

        Args:
            plugin_path: Path to the plugin directory or file

        Returns:
            PluginDescriptor if valid, None otherwise
        """
        plugin_path = os.path.abspath(plugin_path)

        if os.path.isdir(plugin_path):
            return self._discover_plugin_dir(plugin_path)
        elif os.path.isfile(plugin_path) and plugin_path.endswith(".py"):
            return self._discover_plugin_file(plugin_path)
        else:
            logger.warning(f"Invalid plugin path: {plugin_path}")
            return None

    def _discover_directory(self, directory: str) -> Dict[str, PluginDescriptor]:
        """
        Scan a single directory for plugins.

        Each subdirectory is treated as a potential plugin.
        Also checks for single-file plugins at the top level.
        """
        discovered: Dict[str, PluginDescriptor] = {}

        try:
            entries = sorted(os.listdir(directory))
        except PermissionError:
            logger.warning(f"Permission denied: {directory}")
            return discovered

        for entry in entries:
            entry_path = os.path.join(directory, entry)

            # Directory-based plugin
            if os.path.isdir(entry_path):
                # Skip hidden directories and __pycache__
                if entry.startswith("__") or entry.startswith("."):
                    continue
                desc = self._discover_plugin_dir(entry_path)
                if desc:
                    discovered[desc.name] = desc

            # Single-file plugin
            elif entry.endswith(".py") and entry != "__init__.py":
                desc = self._discover_plugin_file(entry_path)
                if desc:
                    discovered[desc.name] = desc

        return discovered

    def _discover_plugin_dir(self, dir_path: str) -> Optional[PluginDescriptor]:
        """
        Discover a plugin from a directory.

        Tries to find:
        1. plugin.py (entry point file)
        2. plugin.json / plugin.yaml (manifest)
        3. __init__.py (package-based plugin)
        """
        dir_name = os.path.basename(dir_path)

        # Check for manifest file
        manifest = self._load_manifest(dir_path)

        # Check for entry point
        entry_point = os.path.join(dir_path, PLUGIN_ENTRY_POINT)
        init_file = os.path.join(dir_path, "__init__.py")

        if os.path.isfile(entry_point):
            module_path = entry_point
        elif os.path.isfile(init_file):
            module_path = init_file
        else:
            # Check if dir has any .py files
            py_files = list(Path(dir_path).glob("*.py"))
            if py_files:
                module_path = str(py_files[0])
            else:
                logger.debug(f"No plugin entry point found in {dir_path}")
                return None

        # Build metadata
        name = manifest.get("name", dir_name) if manifest else dir_name
        version = manifest.get("version", "0.1.0") if manifest else "0.1.0"

        metadata = PluginMetadata(
            name=name,
            version=version,
            description=manifest.get("description", "") if manifest else "",
            author=manifest.get("author", "") if manifest else "",
            license=manifest.get("license", "MIT") if manifest else "MIT",
            homepage=manifest.get("homepage", "") if manifest else "",
            api_version=manifest.get("api_version", API_VERSION) if manifest else API_VERSION,
            min_api_version=manifest.get("min_api_version", "1.0.0") if manifest else "1.0.0",
            tags=manifest.get("tags", []) if manifest else [],
            dependencies=manifest.get("dependencies", {}) if manifest else {},
            optional_dependencies=manifest.get("optional_dependencies", {}) if manifest else {},
            provides_services=manifest.get("provides_services", []) if manifest else [],
            requires_services=manifest.get("requires_services", []) if manifest else [],
            hooks=manifest.get("hooks", []) if manifest else [],
            events_listen=manifest.get("events_listen", []) if manifest else [],
            events_emit=manifest.get("events_emit", []) if manifest else [],
            permissions=manifest.get("permissions", []) if manifest else [],
        )

        config = PluginConfig(
            name=name,
            enabled=manifest.get("enabled", True) if manifest else True,
            settings=manifest.get("settings", {}) if manifest else {},
            isolation=manifest.get("isolation", None) if manifest else None,
            resource_limits=manifest.get("resource_limits", {
                "max_memory_mb": 256,
                "max_cpu_percent": 50,
            }) if manifest else {},
        )

        source_hash = self._compute_source_hash(module_path)

        return PluginDescriptor(
            name=name,
            version=version,
            path=dir_path,
            module_path=module_path,
            entry_point=os.path.basename(module_path),
            metadata=metadata,
            config=config,
            source_hash=source_hash,
        )

    def _discover_plugin_file(self, file_path: str) -> Optional[PluginDescriptor]:
        """
        Discover a single-file plugin.
        """
        file_name = os.path.basename(file_path)
        name = file_name.replace(".py", "")
        dir_path = os.path.dirname(file_path)

        # Check for adjacent manifest
        manifest = self._load_manifest(dir_path)

        # Extract metadata from source
        source_metadata = self._extract_metadata_from_source(file_path)

        if manifest:
            name = manifest.get("name", name)
            version = manifest.get("version", source_metadata.get("version", "0.1.0"))
        else:
            version = source_metadata.get("version", "0.1.0")

        metadata = PluginMetadata(
            name=name,
            version=version,
            description=source_metadata.get("description", ""),
            author=source_metadata.get("author", ""),
            license=manifest.get("license", "MIT") if manifest else source_metadata.get("license", "MIT"),
            api_version=manifest.get("api_version", API_VERSION) if manifest else API_VERSION,
            min_api_version=manifest.get("min_api_version", "1.0.0") if manifest else "1.0.0",
            tags=manifest.get("tags", []) if manifest else [],
            dependencies=manifest.get("dependencies", {}) if manifest else {},
            optional_dependencies=manifest.get("optional_dependencies", {}) if manifest else {},
            provides_services=manifest.get("provides_services", []) if manifest else [],
            requires_services=manifest.get("requires_services", []) if manifest else [],
            permissions=manifest.get("permissions", []) if manifest else [],
        )

        config = PluginConfig(
            name=name,
            enabled=manifest.get("enabled", True) if manifest else True,
            settings=manifest.get("settings", {}) if manifest else {},
            isolation=manifest.get("isolation", None) if manifest else None,
        )

        source_hash = self._compute_source_hash(file_path)

        return PluginDescriptor(
            name=name,
            version=version,
            path=dir_path,
            module_path=file_path,
            entry_point=file_name,
            metadata=metadata,
            config=config,
            source_hash=source_hash,
        )

    def _load_manifest(self, dir_path: str) -> Optional[Dict[str, Any]]:
        """
        Load a plugin manifest from a directory.

        Tries plugin.json first, then plugin.yaml.
        """
        json_path = os.path.join(dir_path, PLUGIN_MANIFEST_FILE)
        yaml_path = os.path.join(dir_path, PLUGIN_YAML_MANIFEST)

        if os.path.isfile(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Failed to load manifest {json_path}: {e}")
                return None

        if os.path.isfile(yaml_path):
            try:
                import yaml
                with open(yaml_path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f)
            except ImportError:
                logger.warning("PyYAML not available, skipping YAML manifest")
                return None
            except Exception as e:
                logger.warning(f"Failed to load manifest {yaml_path}: {e}")
                return None

        return None

    def _extract_metadata_from_source(self, file_path: str) -> Dict[str, str]:
        """
        Extract metadata from Python source file by parsing top-level
        module-level variables and docstrings.
        """
        metadata: Dict[str, str] = {}

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
        except Exception:
            return metadata

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return metadata

        # Extract docstring
        if (tree.body and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)
                and isinstance(tree.body[0].value.value, str)):
            docstring = tree.body[0].value.value
            # Parse simple metadata from docstring
            for line in docstring.split("\n"):
                line = line.strip()
                for key in ["version", "author", "license", "description"]:
                    prefix = f"{key}:"
                    if line.lower().startswith(prefix):
                        metadata[key] = line[len(prefix):].strip()
                        break

        # Extract module-level variables
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in (
                        "__version__", "__author__", "__license__", "__description__"
                    ):
                        if isinstance(node.value, ast.Constant):
                            key = target.id.replace("__", "")
                            metadata[key] = str(node.value.value)

        return metadata

    def _compute_source_hash(self, file_path: str) -> str:
        """Compute SHA-256 hash of source file for change detection."""
        try:
            with open(file_path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception:
            return ""

    def get_cached(self, plugin_name: str) -> Optional[PluginDescriptor]:
        """Get a cached plugin descriptor by name."""
        with self._lock:
            return self._cache.get(plugin_name)

    def invalidate_cache(self, plugin_name: Optional[str] = None) -> None:
        """Invalidate the discovery cache."""
        with self._lock:
            if plugin_name:
                self._cache.pop(plugin_name, None)
            else:
                self._cache.clear()

    def get_all_cached(self) -> Dict[str, PluginDescriptor]:
        """Get all cached plugin descriptors."""
        with self._lock:
            return dict(self._cache)


# ──────────────────────────────────────────────
# Plugin Dependency Resolver
# ──────────────────────────────────────────────

class DependencyGraph:
    """
    Represents a directed graph of plugin dependencies.

    Used to determine load order and detect circular dependencies.
    """

    def __init__(self):
        self._nodes: Set[str] = set()
        self._edges: Dict[str, Set[str]] = {}  # node -> set of dependencies
        self._optional_edges: Dict[str, Set[str]] = {}

    def add_node(self, name: str) -> None:
        """Add a plugin node to the graph."""
        self._nodes.add(name)
        if name not in self._edges:
            self._edges[name] = set()
        if name not in self._optional_edges:
            self._optional_edges[name] = set()

    def add_dependency(self, plugin: str, dependency: str) -> None:
        """Add a required dependency edge (plugin -> dependency)."""
        self.add_node(plugin)
        self.add_node(dependency)
        self._edges.setdefault(plugin, set()).add(dependency)

    def add_optional_dependency(self, plugin: str, dependency: str) -> None:
        """Add an optional dependency edge."""
        self.add_node(plugin)
        self.add_node(dependency)
        self._optional_edges.setdefault(plugin, set()).add(dependency)

    def has_circular_dependency(self) -> Optional[List[str]]:
        """
        Detect circular dependencies.

        Returns:
            A list of nodes in the cycle, or None if acyclic
        """
        visited: Set[str] = set()
        in_stack: Set[str] = set()
        stack: List[str] = []

        def dfs(node: str) -> bool:
            visited.add(node)
            in_stack.add(node)
            stack.append(node)

            for dep in self._edges.get(node, set()):
                if dep not in visited:
                    if dfs(dep):
                        return True
                elif dep in in_stack:
                    # Found a cycle — reconstruct it
                    cycle_start = stack.index(dep)
                    cycle = stack[cycle_start:] + [dep]
                    stack.clear()
                    stack.extend(cycle)
                    return True

            stack.pop()
            in_stack.discard(node)
            return False

        for node in sorted(self._nodes):
            if node not in visited:
                if dfs(node):
                    return list(stack)

        return None

    def topological_sort(self) -> List[str]:
        """
        Return plugins in dependency order (dependencies first).

        Raises:
            PluginDependencyError: If circular dependency detected
        """
        cycle = self.has_circular_dependency()
        if cycle:
            raise PluginDependencyError(
                f"Circular dependency detected: {' -> '.join(cycle)}"
            )

        visited: Set[str] = set()
        result: List[str] = []

        def visit(node: str) -> None:
            if node in visited:
                return
            visited.add(node)
            for dep in sorted(self._edges.get(node, set())):
                visit(dep)
            result.append(node)

        for node in sorted(self._nodes):
            visit(node)

        return result

    def get_dependencies(self, plugin: str) -> Set[str]:
        """Get all direct dependencies of a plugin."""
        return self._edges.get(plugin, set())

    def get_dependents(self, plugin: str) -> Set[str]:
        """Get all plugins that depend on a plugin."""
        dependents: Set[str] = set()
        for node, deps in self._edges.items():
            if plugin in deps:
                dependents.add(node)
        return dependents

    def get_all_dependencies(self, plugin: str) -> Set[str]:
        """Get all transitive dependencies of a plugin."""
        result: Set[str] = set()
        to_visit = list(self._edges.get(plugin, set()))

        while to_visit:
            dep = to_visit.pop()
            if dep not in result:
                result.add(dep)
                to_visit.extend(self._edges.get(dep, set()))

        return result

    def __repr__(self) -> str:
        return f"<DependencyGraph nodes={len(self._nodes)} edges={sum(len(e) for e in self._edges.values())}>"


class PluginDependencyResolver:
    """
    Resolves plugin dependencies with version constraints.

    Supports:
    - Required dependencies (must be present)
    - Optional dependencies (skipped if missing)
    - Version constraints (e.g., ">=1.0.0", "==2.0.0", ">=1.0,<2.0")
    - Circular dependency detection
    - Topological sort for correct load order

    Version constraint syntax:
    - "1.0.0" or "==1.0.0" — exact match
    - ">=1.0.0" — minimum version
    - "<=1.0.0" — maximum version
    - ">1.0.0" — strictly greater
    - "<1.0.0" — strictly less
    - ">=1.0.0,<2.0.0" — range
    - "*" — any version
    """

    def __init__(self):
        self._plugins: Dict[str, PluginDescriptor] = {}

    def register_plugin(self, descriptor: PluginDescriptor) -> None:
        """Register a plugin for dependency resolution."""
        self._plugins[descriptor.name] = descriptor

    def unregister_plugin(self, name: str) -> None:
        """Remove a plugin from resolution."""
        self._plugins.pop(name, None)

    def resolve(self, plugin_name: str) -> DependencyGraph:
        """
        Resolve dependencies for a plugin and its transitive dependencies.

        Args:
            plugin_name: Name of the plugin to resolve

        Returns:
            DependencyGraph with all resolved dependencies

        Raises:
            PluginDependencyError: If dependencies cannot be satisfied
        """
        graph = DependencyGraph()
        self._resolve_recursive(plugin_name, graph, set())
        return graph

    def resolve_all(self) -> DependencyGraph:
        """
        Resolve dependencies for all registered plugins.

        Returns:
            Complete dependency graph

        Raises:
            PluginDependencyError: If any dependency is missing
        """
        graph = DependencyGraph()

        for plugin_name in self._plugins:
            graph.add_node(plugin_name)
            descriptor = self._plugins[plugin_name]

            for dep_name, dep_version in descriptor.metadata.dependencies.items():
                graph.add_dependency(plugin_name, dep_name)

            for dep_name, dep_version in descriptor.metadata.optional_dependencies.items():
                graph.add_optional_dependency(plugin_name, dep_name)

        # Check circular deps
        cycle = graph.has_circular_dependency()
        if cycle:
            raise PluginDependencyError(
                f"Circular dependency detected: {' -> '.join(cycle)}"
            )

        # Verify all required dependencies exist
        for plugin_name in self._plugins:
            descriptor = self._plugins[plugin_name]
            for dep_name, dep_version in descriptor.metadata.dependencies.items():
                if dep_name not in self._plugins:
                    raise PluginDependencyError(
                        f"Plugin '{plugin_name}' requires '{dep_name}' "
                        f"({dep_version}), but it is not installed"
                    )

                # Version check
                self._check_version(
                    plugin_name, dep_name, dep_version,
                    self._plugins[dep_name].version
                )

        return graph

    def get_load_order(self) -> List[str]:
        """
        Get the optimal plugin load order based on dependencies.

        Returns:
            List of plugin names in load order

        Raises:
            PluginDependencyError: If dependency resolution fails
        """
        graph = self.resolve_all()
        return graph.topological_sort()

    def _resolve_recursive(
        self,
        plugin_name: str,
        graph: DependencyGraph,
        visited: Set[str],
    ) -> None:
        """Recursively resolve dependencies for a plugin."""
        if plugin_name in visited:
            return
        visited.add(plugin_name)

        if plugin_name not in self._plugins:
            raise PluginDependencyError(
                f"Plugin '{plugin_name}' not found"
            )

        descriptor = self._plugins[plugin_name]
        graph.add_node(plugin_name)

        # Required dependencies
        for dep_name, dep_version in descriptor.metadata.dependencies.items():
            if dep_name not in self._plugins:
                raise PluginDependencyError(
                    f"Plugin '{plugin_name}' requires '{dep_name}' "
                    f"({dep_version}), but it is not installed"
                )

            # Version check
            self._check_version(
                plugin_name, dep_name, dep_version,
                self._plugins[dep_name].version
            )

            graph.add_dependency(plugin_name, dep_name)
            self._resolve_recursive(dep_name, graph, visited)

        # Optional dependencies
        for dep_name, dep_version in descriptor.metadata.optional_dependencies.items():
            if dep_name in self._plugins:
                self._check_version(
                    plugin_name, dep_name, dep_version,
                    self._plugins[dep_name].version
                )
                graph.add_optional_dependency(plugin_name, dep_name)
                self._resolve_recursive(dep_name, graph, visited)

    def _check_version(
        self,
        plugin_name: str,
        dep_name: str,
        constraint: str,
        actual_version: str,
    ) -> None:
        """
        Check if a version satisfies a constraint.

        Args:
            plugin_name: Plugin that has the dependency
            dep_name: Dependency name
            constraint: Version constraint string
            actual_version: Installed version

        Raises:
            PluginDependencyError: If constraint not satisfied
        """
        if constraint == "*" or not constraint:
            return

        def parse_version(v: str) -> Tuple[int, ...]:
            """Parse version string into comparable tuple."""
            parts = v.replace("-", ".").split(".")
            result = []
            for part in parts:
                try:
                    result.append(int(part))
                except ValueError:
                    result.append(0)
            # Pad to 3 parts
            while len(result) < 3:
                result.append(0)
            return tuple(result[:3])

        def version_matches(actual: str, constraint: str) -> bool:
            """Check if actual version matches the constraint."""
            act = parse_version(actual)

            # Handle comma-separated ranges
            if "," in constraint:
                parts = [p.strip() for p in constraint.split(",")]
                return all(version_matches(actual, p) for p in parts)

            constraint = constraint.strip()
            if constraint.startswith(">="):
                return act >= parse_version(constraint[2:])
            elif constraint.startswith("<="):
                return act <= parse_version(constraint[2:])
            elif constraint.startswith(">"):
                return act > parse_version(constraint[1:])
            elif constraint.startswith("<"):
                return act < parse_version(constraint[1:])
            elif constraint.startswith("=="):
                return act == parse_version(constraint[2:])
            elif constraint.startswith("!="):
                return act != parse_version(constraint[2:])
            else:
                # Exact match
                return act == parse_version(constraint)

        if not version_matches(actual_version, constraint):
            raise PluginDependencyError(
                f"Plugin '{plugin_name}' requires '{dep_name}' "
                f"version {constraint}, but version {actual_version} is installed"
            )

    def get_missing_dependencies(self, plugin_name: str) -> Dict[str, str]:
        """Get dependencies that are missing for a plugin."""
        descriptor = self._plugins.get(plugin_name)
        if not descriptor:
            return {}

        missing = {}
        for dep_name, dep_version in descriptor.metadata.dependencies.items():
            if dep_name not in self._plugins:
                missing[dep_name] = dep_version

        return missing

    def get_unsatisfied_dependencies(self, plugin_name: str) -> Dict[str, str]:
        """Get dependencies with version mismatches."""
        descriptor = self._plugins.get(plugin_name)
        if not descriptor:
            return {}

        unsatisfied = {}
        for dep_name, dep_version in descriptor.metadata.dependencies.items():
            if dep_name in self._plugins:
                try:
                    self._check_version(
                        plugin_name, dep_name, dep_version,
                        self._plugins[dep_name].version
                    )
                except PluginDependencyError:
                    unsatisfied[dep_name] = dep_version

        return unsatisfied


# ──────────────────────────────────────────────
# Plugin Config Manager
# ──────────────────────────────────────────────

class PluginConfigManager:
    """
    Manages plugin configuration persistence.

    Stores plugin configurations in JSON files, supports
    hierarchical config overrides, and provides atomic saves.
    """

    def __init__(self, config_dir: Optional[str] = None):
        self._config_dir = config_dir or self._default_config_dir()
        self._configs: Dict[str, PluginConfig] = {}
        self._lock = threading.RLock()
        self._ensure_config_dir()

    def _default_config_dir(self) -> str:
        """Get the default configuration directory."""
        base = os.environ.get("AINOS_CONFIG_DIR", "")
        if not base:
            base = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "configs",
            )
        return os.path.join(base, "plugins")

    def _ensure_config_dir(self) -> None:
        """Ensure the configuration directory exists."""
        os.makedirs(self._config_dir, exist_ok=True)

    def _config_path(self, plugin_name: str) -> str:
        """Get the config file path for a plugin."""
        return os.path.join(self._config_dir, f"{plugin_name}.json")

    def load_config(self, plugin_name: str) -> Optional[PluginConfig]:
        """
        Load configuration for a plugin from disk.

        Args:
            plugin_name: Name of the plugin

        Returns:
            PluginConfig if found, None otherwise
        """
        config_path = self._config_path(plugin_name)
        if not os.path.isfile(config_path):
            return None

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            config = PluginConfig(
                name=data.get("name", plugin_name),
                enabled=data.get("enabled", True),
                settings=data.get("settings", {}),
                isolation=data.get("isolation", None),
                resource_limits=data.get("resource_limits", {
                    "max_memory_mb": 256,
                    "max_cpu_percent": 50,
                }),
            )

            with self._lock:
                self._configs[plugin_name] = config

            return config

        except Exception as e:
            logger.warning(f"Failed to load config for '{plugin_name}': {e}")
            return None

    def save_config(self, config: PluginConfig) -> bool:
        """
        Save configuration for a plugin to disk.

        Args:
            config: PluginConfig to save

        Returns:
            True if saved successfully
        """
        config_path = self._config_path(config.name)

        data = {
            "name": config.name,
            "enabled": config.enabled,
            "settings": config.settings,
            "isolation": config.isolation,
            "resource_limits": config.resource_limits,
        }

        try:
            # Atomic write
            tmp_path = config_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, config_path)

            with self._lock:
                self._configs[config.name] = config

            return True

        except Exception as e:
            logger.error(f"Failed to save config for '{config.name}': {e}")
            return False

    def get_config(self, plugin_name: str) -> Optional[PluginConfig]:
        """Get the in-memory config for a plugin."""
        with self._lock:
            return self._configs.get(plugin_name)

    def update_config(
        self,
        plugin_name: str,
        settings: Optional[Dict[str, Any]] = None,
        enabled: Optional[bool] = None,
        isolation: Optional[str] = None,
        resource_limits: Optional[Dict[str, Any]] = None,
    ) -> Optional[PluginConfig]:
        """
        Update a plugin's configuration.

        Args:
            plugin_name: Plugin name
            settings: Settings to merge
            enabled: Whether plugin is enabled
            isolation: Isolation mode
            resource_limits: Resource limits

        Returns:
            Updated PluginConfig, or None if not found
        """
        with self._lock:
            config = self._configs.get(plugin_name)
            if config is None:
                return None

            new_config = PluginConfig(
                name=config.name,
                enabled=enabled if enabled is not None else config.enabled,
                settings={**config.settings, **(settings or {})},
                isolation=isolation if isolation is not None else config.isolation,
                resource_limits={**config.resource_limits, **(resource_limits or {})},
            )
            self._configs[plugin_name] = new_config

        self.save_config(new_config)
        return new_config

    def delete_config(self, plugin_name: str) -> bool:
        """Delete a plugin's configuration file."""
        config_path = self._config_path(plugin_name)
        with self._lock:
            self._configs.pop(plugin_name, None)
        try:
            if os.path.isfile(config_path):
                os.remove(config_path)
                return True
        except Exception as e:
            logger.warning(f"Failed to delete config for '{plugin_name}': {e}")
        return False

    def list_configs(self) -> List[str]:
        """List all plugin names with saved configurations."""
        with self._lock:
            return list(self._configs.keys())

    def merge_with_default(self, config: PluginConfig, default_config: PluginConfig) -> PluginConfig:
        """
        Merge a loaded config with defaults, preferring loaded values.

        Args:
            config: Loaded configuration
            default_config: Default configuration

        Returns:
            Merged PluginConfig
        """
        return PluginConfig(
            name=config.name,
            enabled=config.enabled if config.enabled is not None else default_config.enabled,
            settings={**default_config.settings, **config.settings},
            isolation=config.isolation or default_config.isolation,
            resource_limits={**default_config.resource_limits, **config.resource_limits},
        )


# ──────────────────────────────────────────────
# Plugin Isolation (Subprocess)
# ──────────────────────────────────────────────

class PluginIsolation:
    """
    Runs plugins in isolated subprocesses.

    Provides:
    - Subprocess-based isolation with IPC communication
    - Resource limits (memory, CPU)
    - Timeout protection
    - Crash resilience
    - Communication via stdin/stdout JSON lines

    IPC Protocol:
    - Plugin receives JSON commands on stdin
    - Plugin sends JSON responses on stdout
    - Commands: init, start, stop, cleanup, call, event, config
    - Responses: ok, error, result
    """

    def __init__(self):
        self._processes: Dict[str, Any] = {}
        self._lock = threading.RLock()

    def start_isolated(
        self,
        descriptor: PluginDescriptor,
        runtime: PluginAPI,
        timeout: float = ISOLATION_TIMEOUT_SEC,
    ) -> bool:
        """
        Start a plugin in an isolated subprocess.

        Args:
            descriptor: Plugin descriptor
            runtime: PluginAPI to pass to the subprocess
            timeout: Startup timeout in seconds

        Returns:
            True if started successfully
        """
        import pickle

        try:
            # Prepare the subprocess script
            isolation_script = textwrap.dedent(f"""
            import sys
            import json
            import traceback
            import pickle

            # Add plugin path to sys.path
            sys.path.insert(0, {json.dumps(os.path.dirname(descriptor.module_path))})
            sys.path.insert(0, {json.dumps(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))})

            # Load the plugin module
            module_path = {json.dumps(descriptor.module_path)}
            module_name = {json.dumps(descriptor.name)}

            try:
                spec = importlib.util.spec_from_file_location(module_name, module_path)
                if spec is None or spec.loader is None:
                    raise ImportError(f"Could not load module from {{module_path}}")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Find PluginBase subclass
                plugin_instance = None
                from plugins.api import PluginBase, PluginAPI, PluginMetadata, PluginConfig

                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and issubclass(attr, PluginBase) and attr is not PluginBase:
                        # Reconstruct metadata and config
                        metadata = pickle.loads({json.dumps(pickle.dumps(descriptor.metadata))!r})
                        config = pickle.loads({json.dumps(pickle.dumps(descriptor.config))!r})
                        plugin_instance = attr(metadata, config)
                        break

                if plugin_instance is None:
                    print(json.dumps({{"type": "error", "message": "No PluginBase subclass found"}}))
                    sys.exit(1)

                # Initialize
                runtime = pickle.loads({json.dumps(pickle.dumps(runtime))!r})
                plugin_instance._initialize(runtime)

                # Signal ready
                print(json.dumps({{"type": "ready", "name": plugin_instance.name}}))
                sys.stdout.flush()

                # Main loop: read commands from stdin
                for line in sys.stdin:
                    try:
                        cmd = json.loads(line.strip())
                        cmd_type = cmd.get("type", "")

                        if cmd_type == "start":
                            plugin_instance._start()
                            print(json.dumps({{"type": "ok", "action": "start"}}))

                        elif cmd_type == "stop":
                            plugin_instance._stop()
                            print(json.dumps({{"type": "ok", "action": "stop"}}))

                        elif cmd_type == "cleanup":
                            plugin_instance._cleanup()
                            print(json.dumps({{"type": "ok", "action": "cleanup"}}))

                        elif cmd_type == "call":
                            method = cmd.get("method", "")
                            args = cmd.get("args", [])
                            kwargs = cmd.get("kwargs", {{}})
                            if hasattr(plugin_instance, method):
                                result = getattr(plugin_instance, method)(*args, **kwargs)
                                print(json.dumps({{"type": "result", "method": method, "result": str(result)}}))
                            else:
                                print(json.dumps({{"type": "error", "method": method, "message": "Method not found"}}))

                        elif cmd_type == "config":
                            new_config = pickle.loads(bytes.fromhex(cmd.get("config_hex", "")))
                            old_config = plugin_instance.config
                            plugin_instance.config = new_config
                            plugin_instance.on_config_change(old_config, new_config)
                            print(json.dumps({{"type": "ok", "action": "config"}}))

                        elif cmd_type == "shutdown":
                            plugin_instance._stop()
                            plugin_instance._cleanup()
                            print(json.dumps({{"type": "ok", "action": "shutdown"}}))
                            break

                        sys.stdout.flush()

                    except Exception as e:
                        print(json.dumps({{"type": "error", "message": str(e), "traceback": traceback.format_exc()}}))
                        sys.stdout.flush()

            except Exception as e:
                print(json.dumps({{"type": "fatal", "message": str(e), "traceback": traceback.format_exc()}}))
                sys.exit(1)
            """)

            # Start the subprocess
            import pickle as pickle_mod
            proc = subprocess.Popen(
                [sys.executable, "-c", isolation_script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=os.path.dirname(descriptor.path),
            )

            # Wait for ready signal
            ready_line = proc.stdout.readline() if proc.stdout else ""
            try:
                ready_msg = json.loads(ready_line.strip())
            except (json.JSONDecodeError, AttributeError):
                stderr = proc.stderr.read() if proc.stderr else ""
                proc.kill()
                logger.error(
                    f"Plugin '{descriptor.name}' isolation failed: "
                    f"no ready signal. Stderr: {stderr[:200]}"
                )
                return False

            if ready_msg.get("type") != "ready":
                stderr = proc.stderr.read() if proc.stderr else ""
                proc.kill()
                logger.error(
                    f"Plugin '{descriptor.name}' isolation failed: "
                    f"{ready_msg.get('message', 'unknown')}. Stderr: {stderr[:200]}"
                )
                return False

            with self._lock:
                self._processes[descriptor.name] = proc

            descriptor.is_isolated = True
            descriptor.isolation_process = proc
            descriptor.pid = proc.pid

            logger.info(
                f"Plugin '{descriptor.name}' running in isolated "
                f"subprocess (PID {proc.pid})"
            )
            return True

        except Exception as e:
            logger.error(
                f"Failed to start isolated plugin '{descriptor.name}': {e}",
                exc_info=True,
            )
            return False

    def send_command(
        self,
        plugin_name: str,
        command: Dict[str, Any],
        timeout: float = 10.0,
    ) -> Optional[Dict[str, Any]]:
        """
        Send a command to an isolated plugin subprocess.

        Args:
            plugin_name: Plugin name
            command: Command dict
            timeout: Response timeout in seconds

        Returns:
            Response dict, or None on failure
        """
        with self._lock:
            proc = self._processes.get(plugin_name)
            if proc is None:
                logger.warning(f"No isolated process for '{plugin_name}'")
                return None

        try:
            # Send command
            if proc.stdin:
                proc.stdin.write(json.dumps(command) + "\n")
                proc.stdin.flush()

            # Read response
            import select
            if hasattr(select, "select"):
                # Wait for response with timeout
                ready, _, _ = select.select([proc.stdout], [], [], timeout)
                if not ready:
                    logger.warning(
                        f"Timeout waiting for response from '{plugin_name}'"
                    )
                    return None
                response_line = proc.stdout.readline() if proc.stdout else ""
            else:
                response_line = proc.stdout.readline() if proc.stdout else ""

            if not response_line:
                return None

            return json.loads(response_line.strip())

        except Exception as e:
            logger.error(
                f"Failed to send command to '{plugin_name}': {e}"
            )
            return None

    def stop_isolated(self, plugin_name: str, timeout: float = 5.0) -> bool:
        """
        Stop an isolated plugin subprocess.

        Args:
            plugin_name: Plugin name
            timeout: Shutdown timeout

        Returns:
            True if stopped successfully
        """
        with self._lock:
            proc = self._processes.pop(plugin_name, None)
            if proc is None:
                return False

        try:
            # Send shutdown command
            if proc.stdin:
                proc.stdin.write(
                    json.dumps({"type": "shutdown"}) + "\n"
                )
                proc.stdin.flush()

            # Wait for process to exit
            proc.wait(timeout=timeout)
            return True

        except subprocess.TimeoutExpired:
            logger.warning(
                f"Plugin '{plugin_name}' isolation timed out, killing"
            )
            proc.kill()
            proc.wait(timeout=5)
            return False
        except Exception as e:
            logger.error(
                f"Failed to stop isolated plugin '{plugin_name}': {e}"
            )
            try:
                proc.kill()
            except Exception:
                pass
            return False

    def is_alive(self, plugin_name: str) -> bool:
        """Check if an isolated plugin process is still running."""
        with self._lock:
            proc = self._processes.get(plugin_name)
            if proc is None:
                return False
            return proc.poll() is None

    def get_alive_pids(self) -> Dict[str, int]:
        """Get PIDs of all running isolated plugins."""
        with self._lock:
            return {
                name: proc.pid
                for name, proc in self._processes.items()
                if proc.poll() is None
            }

    def shutdown_all(self, timeout: float = 10.0) -> None:
        """Stop all isolated plugin processes."""
        with self._lock:
            names = list(self._processes.keys())

        for name in names:
            self.stop_isolated(name, timeout=timeout)

    def __len__(self) -> int:
        with self._lock:
            return len(self._processes)


# ──────────────────────────────────────────────
# Plugin Hot Reload
# ──────────────────────────────────────────────

class PluginHotReload:
    """
    Watches plugin source files for changes and triggers hot reloads.

    Uses file modification timestamps and content hashing to detect
    changes without requiring external dependencies.
    """

    def __init__(
        self,
        check_interval: float = WATCH_INTERVAL_SEC,
        on_reload: Optional[Callable[[str], None]] = None,
    ):
        self._check_interval = check_interval
        self._on_reload = on_reload
        self._watched: Dict[str, str] = {}  # path -> hash
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._changed: Set[str] = set()

    def watch(self, plugin_name: str, file_path: str) -> None:
        """
        Start watching a plugin's source file for changes.

        Args:
            plugin_name: Plugin name
            file_path: Path to the source file
        """
        with self._lock:
            current_hash = self._compute_hash(file_path)
            self._watched[plugin_name] = file_path
            self._changed.discard(plugin_name)
            logger.debug(f"Watching '{plugin_name}' at {file_path}")

    def unwatch(self, plugin_name: str) -> None:
        """Stop watching a plugin."""
        with self._lock:
            self._watched.pop(plugin_name, None)
            self._changed.discard(plugin_name)

    def unwatch_all(self) -> None:
        """Stop watching all plugins."""
        with self._lock:
            self._watched.clear()
            self._changed.clear()

    def check_changes(self) -> List[str]:
        """
        Check for changed plugin files.

        Returns:
            List of plugin names with changed source files
        """
        changed: List[str] = []
        with self._lock:
            for plugin_name, file_path in list(self._watched.items()):
                current_hash = self._compute_hash(file_path)
                previous_hash = self._watched.get(plugin_name)

                if previous_hash and current_hash != previous_hash:
                    changed.append(plugin_name)
                    self._changed.add(plugin_name)
                    self._watched[plugin_name] = current_hash

        return changed

    def start_watching(self) -> None:
        """Start the background file watcher thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._watch_loop,
            daemon=True,
            name="plugin-hot-reload",
        )
        self._thread.start()
        logger.info("Plugin hot-reload watcher started")

    def stop_watching(self) -> None:
        """Stop the background file watcher thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("Plugin hot-reload watcher stopped")

    def _watch_loop(self) -> None:
        """Background loop that periodically checks for changes."""
        while self._running:
            try:
                changed = self.check_changes()
                for plugin_name in changed:
                    if self._on_reload:
                        try:
                            self._on_reload(plugin_name)
                        except Exception as e:
                            logger.error(
                                f"Hot-reload callback for '{plugin_name}' "
                                f"failed: {e}"
                            )
                time.sleep(self._check_interval)
            except Exception as e:
                logger.error(f"Hot-reload watcher error: {e}")
                time.sleep(self._check_interval)

    def _compute_hash(self, file_path: str) -> str:
        """Compute a hash of the file for change detection."""
        try:
            with open(file_path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception:
            return ""

    @property
    def is_running(self) -> bool:
        """Whether the watcher is running."""
        return self._running

    @property
    def watched_plugins(self) -> List[str]:
        """List of plugin names being watched."""
        with self._lock:
            return list(self._watched.keys())

    @property
    def changed_plugins(self) -> Set[str]:
        """Set of plugins that have pending changes."""
        with self._lock:
            return set(self._changed)


# ──────────────────────────────────────────────
# Plugin Manager (Main Orchestrator)
# ──────────────────────────────────────────────

class PluginManager:
    """
    Central plugin management system for Ainos OS.

    The PluginManager orchestrates all plugin operations:
    - Discovery: Find plugins on the filesystem
    - Loading: Import and initialize plugin modules
    - Lifecycle: Manage start/stop/cleanup sequences
    - Dependencies: Resolve and validate plugin deps
    - Configuration: Persist and manage plugin configs
    - Isolation: Run plugins in subprocesses
    - Hot-reload: Watch and reload changed plugins
    - CLI: Command-line interface for management

    Usage:
        manager = PluginManager()
        manager.discover_plugins()
        manager.load_all_plugins()
        manager.start_all_plugins()
        # ... use plugins ...
        manager.stop_all_plugins()
        manager.cleanup_all_plugins()
    """

    def __init__(
        self,
        plugin_dirs: Optional[List[str]] = None,
        config_dir: Optional[str] = None,
        enable_hot_reload: bool = False,
        enable_isolation: bool = False,
    ):
        # Core subsystems
        self.hook_registry = HookRegistry()
        self.event_bus = EventBus()
        self.service_registry = ServiceRegistry()
        self._api = PluginAPI(
            hook_registry=self.hook_registry,
            event_bus=self.event_bus,
            service_registry=self.service_registry,
        )

        # Plugin management subsystems
        self.discovery = PluginDiscovery(plugin_dirs)
        self.dependency_resolver = PluginDependencyResolver()
        self.config_manager = PluginConfigManager(config_dir)
        self.isolation = PluginIsolation()
        self.hot_reload = PluginHotReload(on_reload=self._on_hot_reload)

        # State
        self._plugins: Dict[str, PluginDescriptor] = {}
        self._load_lock = threading.RLock()
        self._enable_hot_reload = enable_hot_reload
        self._enable_isolation = enable_isolation
        self._initialized = False
        self._started = False

        # Register built-in hooks
        self._register_builtin_hooks()

        logger.info("PluginManager initialized")

    # ── Initialization ──

    def _register_builtin_hooks(self) -> None:
        """Register the standard system hooks."""
        from .api import HOOKS
        for name, description in HOOKS.items():
            self.hook_registry.register_hook(
                name=name,
                description=description,
                allow_short_circuit=("before" in name or "check" in name),
            )

    # ── Discovery ──

    def add_plugin_dir(self, directory: str) -> None:
        """Add a plugin directory to the search path."""
        self.discovery.add_plugin_dir(directory)

    def discover_plugins(self, clear_cache: bool = False) -> Dict[str, PluginDescriptor]:
        """
        Discover all plugins from configured directories.

        Args:
            clear_cache: Force re-scan

        Returns:
            Dict of discovered plugin descriptors
        """
        discovered = self.discovery.discover_all(clear_cache=clear_cache)

        # Register with dependency resolver
        for name, desc in discovered.items():
            self.dependency_resolver.register_plugin(desc)

        logger.info(f"Discovered {len(discovered)} plugins")
        return discovered

    # ── Loading ──

    def load_plugin(
        self,
        plugin_name: str,
        config: Optional[PluginConfig] = None,
    ) -> Optional[PluginBase]:
        """
        Load and initialize a single plugin.

        Steps:
        1. Find plugin descriptor
        2. Load configuration
        3. Resolve dependencies
        4. Import module
        5. Instantiate plugin class
        6. Initialize with API

        Args:
            plugin_name: Name of the plugin to load
            config: Optional configuration override

        Returns:
            Plugin instance, or None on failure
        """
        with self._load_lock:
            # Check if already loaded
            if plugin_name in self._plugins:
                desc = self._plugins[plugin_name]
                if desc.instance is not None:
                    logger.warning(f"Plugin '{plugin_name}' is already loaded")
                    return desc.instance

            # Get descriptor
            desc = self.discovery.get_cached(plugin_name)
            if desc is None:
                # Try to discover just this plugin
                for plugin_dir in self.discovery.plugin_dirs:
                    candidate = os.path.join(plugin_dir, plugin_name)
                    if os.path.exists(candidate):
                        desc = self.discovery.discover_plugin(candidate)
                        if desc:
                            break

            if desc is None:
                error = f"Plugin '{plugin_name}' not found"
                logger.error(error)
                raise PluginLoadError(error)

            # Trigger before-load hook
            self.hook_registry.trigger(
                "plugin.before_load",
                plugin_name=plugin_name,
            )

            # Resolve dependencies
            try:
                load_order = self.dependency_resolver.get_load_order()
                # Ensure dependencies are loaded
                deps = self.dependency_resolver.resolve(plugin_name)
                for dep_name in deps.topological_sort():
                    if dep_name != plugin_name and dep_name not in self._plugins:
                        self.load_plugin(dep_name)
            except PluginDependencyError as e:
                desc.error = str(e)
                desc.state = PluginState.ERROR
                logger.error(
                    f"Dependency resolution failed for '{plugin_name}': {e}"
                )
                raise

            # Load configuration
            saved_config = self.config_manager.load_config(plugin_name)
            if saved_config and config:
                config = self.config_manager.merge_with_default(config, saved_config)
            elif saved_config:
                config = saved_config
            elif config is None:
                config = desc.config

            # Check if plugin is disabled
            if not config.enabled:
                logger.info(f"Plugin '{plugin_name}' is disabled, skipping")
                desc.state = PluginState.DISABLED
                return None

            # Check API version compatibility
            self._check_api_version(desc.metadata)

            # Choose isolation mode
            effective_isolation = config.isolation or desc.config.isolation
            if effective_isolation == "subprocess" or self._enable_isolation:
                return self._load_isolated(desc, config)
            else:
                return self._load_inprocess(desc, config)

    def _load_inprocess(
        self,
        desc: PluginDescriptor,
        config: PluginConfig,
    ) -> Optional[PluginBase]:
        """
        Load a plugin in-process (same Python interpreter).
        """
        plugin_name = desc.name
        module_path = desc.module_path

        try:
            # Add plugin path to sys.path
            plugin_dir = os.path.dirname(module_path)
            if plugin_dir not in sys.path:
                sys.path.insert(0, plugin_dir)

            # Import the module
            module_name = f"ainos_plugin_{plugin_name}_{uuid.uuid4().hex[:8]}"
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec is None or spec.loader is None:
                raise PluginLoadError(f"Could not load module from {module_path}")

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find the PluginBase subclass
            plugin_class = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type)
                        and issubclass(attr, PluginBase)
                        and attr is not PluginBase):
                    plugin_class = attr
                    break

            if plugin_class is None:
                raise PluginLoadError(
                    f"No PluginBase subclass found in '{plugin_name}'"
                )

            # Instantiate
            instance = plugin_class(desc.metadata, config)
            instance.on_create()

            # Update descriptor
            desc.instance = instance
            desc.state = PluginState.INITIALIZED
            desc.config = config

            # Initialize with API
            instance._initialize(self._api)

            # Store
            with self._load_lock:
                self._plugins[plugin_name] = desc

            # Start watching for hot-reload
            if self._enable_hot_reload:
                self.hot_reload.watch(plugin_name, module_path)

            # Trigger after-load hook
            self.hook_registry.trigger(
                "plugin.after_load",
                plugin_name=plugin_name,
                instance=instance,
            )

            # Publish event
            self.event_bus.publish(Event(
                type="plugin.loaded",
                payload={
                    "name": plugin_name,
                    "version": desc.version,
                    "path": desc.path,
                },
                source="system",
            ))

            logger.info(
                f"Loaded plugin '{plugin_name}' v{desc.version}"
            )
            return instance

        except PluginLoadError:
            raise
        except Exception as e:
            desc.error = str(e)
            desc.state = PluginState.ERROR
            logger.error(
                f"Failed to load plugin '{plugin_name}': {e}",
                exc_info=True,
            )
            raise PluginLoadError(
                f"Failed to load plugin '{plugin_name}': {e}"
            ) from e

    def _load_isolated(
        self,
        desc: PluginDescriptor,
        config: PluginConfig,
    ) -> Optional[PluginBase]:
        """
        Load a plugin in an isolated subprocess.
        """
        plugin_name = desc.name

        # Store config
        desc.config = config

        # Start isolated process
        success = self.isolation.start_isolated(desc, self._api)
        if not success:
            desc.state = PluginState.ERROR
            desc.error = "Isolation startup failed"
            raise PluginLoadError(
                f"Failed to start isolated plugin '{plugin_name}'"
            )

        # Store
        with self._load_lock:
            self._plugins[plugin_name] = desc

        desc.state = PluginState.INITIALIZED

        if self._enable_hot_reload:
            self.hot_reload.watch(plugin_name, desc.module_path)

        # Trigger after-load hook
        self.hook_registry.trigger(
            "plugin.after_load",
            plugin_name=plugin_name,
        )

        self.event_bus.publish(Event(
            type="plugin.loaded",
            payload={
                "name": plugin_name,
                "version": desc.version,
                "pid": desc.pid,
                "isolated": True,
            },
            source="system",
        ))

        logger.info(
            f"Loaded isolated plugin '{plugin_name}' v{desc.version} "
            f"(PID {desc.pid})"
        )
        return None  # No instance available in-process

    def load_all_plugins(
        self,
        configs: Optional[Dict[str, PluginConfig]] = None,
    ) -> Dict[str, Optional[PluginBase]]:
        """
        Load all discovered plugins in dependency order.

        Args:
            configs: Optional dict of plugin_name -> config overrides

        Returns:
            Dict mapping plugin names to instances (or None for isolated)
        """
        # Discover plugins first
        self.discover_plugins()

        # Get load order
        try:
            load_order = self.dependency_resolver.get_load_order()
        except PluginDependencyError as e:
            logger.error(f"Dependency resolution failed: {e}")
            # Fall back to alphabetical order
            load_order = sorted(self.discovery.get_all_cached().keys())

        configs = configs or {}
        results: Dict[str, Optional[PluginBase]] = {}

        for plugin_name in load_order:
            config = configs.get(plugin_name)
            try:
                instance = self.load_plugin(plugin_name, config)
                results[plugin_name] = instance
            except Exception as e:
                logger.error(
                    f"Failed to load plugin '{plugin_name}': {e}"
                )
                results[plugin_name] = None

        # Start hot-reload watcher
        if self._enable_hot_reload and not self.hot_reload.is_running:
            self.hot_reload.start_watching()

        self._initialized = True
        logger.info(f"Loaded {sum(1 for v in results.values() if v is not None)} plugins")
        return results

    # ── Lifecycle ──

    def start_plugin(self, plugin_name: str) -> bool:
        """
        Start a loaded plugin.

        Args:
            plugin_name: Plugin name

        Returns:
            True if started successfully
        """
        with self._load_lock:
            desc = self._plugins.get(plugin_name)
            if desc is None:
                logger.warning(f"Plugin '{plugin_name}' not loaded")
                return False

        if desc.is_isolated:
            # Send start command to isolated process
            response = self.isolation.send_command(
                plugin_name, {"type": "start"}
            )
            success = response is not None and response.get("type") == "ok"
        else:
            instance = desc.instance
            if instance is None:
                return False
            try:
                instance._start()
                success = True
            except Exception as e:
                desc.error = str(e)
                desc.state = PluginState.ERROR
                logger.error(
                    f"Failed to start plugin '{plugin_name}': {e}",
                    exc_info=True,
                )
                success = False

        if success:
            desc.state = PluginState.STARTED
            desc.start_time = time.time()

            self.event_bus.publish(Event(
                type="plugin.started",
                payload={"name": plugin_name},
                source="system",
            ))

            logger.info(f"Plugin '{plugin_name}' started")
        else:
            self.event_bus.publish(Event(
                type="plugin.error",
                payload={
                    "name": plugin_name,
                    "error": desc.error or "start failed",
                },
                source="system",
            ))

        return success

    def start_all_plugins(self) -> Dict[str, bool]:
        """Start all loaded plugins."""
        results: Dict[str, bool] = {}
        for plugin_name in list(self._plugins.keys()):
            results[plugin_name] = self.start_plugin(plugin_name)
        self._started = True
        return results

    def stop_plugin(self, plugin_name: str) -> bool:
        """
        Stop a running plugin.

        Args:
            plugin_name: Plugin name

        Returns:
            True if stopped successfully
        """
        with self._load_lock:
            desc = self._plugins.get(plugin_name)
            if desc is None:
                return False

        if desc.is_isolated:
            response = self.isolation.send_command(
                plugin_name, {"type": "stop"}
            )
            success = True  # Best effort
        else:
            instance = desc.instance
            if instance is None:
                return False
            try:
                instance._stop()
                success = True
            except Exception as e:
                logger.error(
                    f"Plugin '{plugin_name}' stop error: {e}"
                )
                success = True  # Best effort

        desc.state = PluginState.STOPPED

        # Trigger hook
        self.hook_registry.trigger(
            "plugin.after_unload",
            plugin_name=plugin_name,
        )

        self.event_bus.publish(Event(
            type="plugin.stopped",
            payload={"name": plugin_name},
            source="system",
        ))

        logger.info(f"Plugin '{plugin_name}' stopped")
        return success

    def stop_all_plugins(self) -> None:
        """Stop all running plugins (reverse load order)."""
        # Stop in reverse dependency order
        try:
            load_order = self.dependency_resolver.get_load_order()
            for plugin_name in reversed(load_order):
                self.stop_plugin(plugin_name)
        except Exception:
            # Fall through to stopping everything
            pass

        # Also stop any remaining
        for plugin_name in list(self._plugins.keys()):
            self.stop_plugin(plugin_name)

        self._started = False

    def cleanup_plugin(self, plugin_name: str) -> bool:
        """
        Clean up a plugin's resources.

        Args:
            plugin_name: Plugin name

        Returns:
            True if cleaned up successfully
        """
        with self._load_lock:
            desc = self._plugins.get(plugin_name)
            if desc is None:
                return False

        if desc.is_isolated:
            success = self.isolation.stop_isolated(plugin_name)
        else:
            instance = desc.instance
            if instance is None:
                return False
            try:
                instance._cleanup()
                success = True
            except Exception as e:
                logger.error(
                    f"Plugin '{plugin_name}' cleanup error: {e}"
                )
                success = True

            # Unregister from hook registry
            self.hook_registry.unregister_plugin(plugin_name)

            # Unregister from event bus
            self.event_bus.unsubscribe_plugin(plugin_name)

            # Unregister services
            self.service_registry.unregister_plugin(plugin_name)

        # Unwatch
        if self._enable_hot_reload:
            self.hot_reload.unwatch(plugin_name)

        desc.state = PluginState.STOPPED
        desc.instance = None

        self.event_bus.publish(Event(
            type="plugin.unloaded",
            payload={"name": plugin_name},
            source="system",
        ))

        return success

    def cleanup_all_plugins(self) -> None:
        """Clean up all plugins."""
        for plugin_name in list(self._plugins.keys()):
            self.cleanup_plugin(plugin_name)

        self._plugins.clear()

        if self._enable_hot_reload:
            self.hot_reload.stop_watching()

    # ── Unloading ──

    def unload_plugin(self, plugin_name: str) -> bool:
        """
        Unload a plugin completely (stop + cleanup + unregister).

        Args:
            plugin_name: Plugin name

        Returns:
            True if unloaded successfully
        """
        self.hook_registry.trigger(
            "plugin.before_unload",
            plugin_name=plugin_name,
        )

        self.stop_plugin(plugin_name)
        self.cleanup_plugin(plugin_name)

        with self._load_lock:
            self._plugins.pop(plugin_name, None)
            self.dependency_resolver.unregister_plugin(plugin_name)

        logger.info(f"Plugin '{plugin_name}' unloaded")
        return True

    # ── Enable / Disable ──

    def enable_plugin(self, plugin_name: str) -> bool:
        """
        Enable a disabled plugin.

        Args:
            plugin_name: Plugin name

        Returns:
            True if enabled
        """
        self.hook_registry.trigger(
            "plugin.before_enable",
            plugin_name=plugin_name,
        )

        config = self.config_manager.update_config(
            plugin_name, enabled=True
        )
        if config is None:
            return False

        # Reload the plugin
        try:
            self.load_plugin(plugin_name)
        except Exception as e:
            logger.error(f"Failed to reload enabled plugin '{plugin_name}': {e}")
            return False

        self.hook_registry.trigger(
            "plugin.after_enable",
            plugin_name=plugin_name,
        )

        self.event_bus.publish(Event(
            type="plugin.enabled",
            payload={"name": plugin_name},
            source="system",
        ))

        return True

    def disable_plugin(self, plugin_name: str) -> bool:
        """
        Disable a plugin without unloading it.

        Args:
            plugin_name: Plugin name

        Returns:
            True if disabled
        """
        self.hook_registry.trigger(
            "plugin.before_disable",
            plugin_name=plugin_name,
        )

        self.unload_plugin(plugin_name)

        self.config_manager.update_config(
            plugin_name, enabled=False
        )

        self.hook_registry.trigger(
            "plugin.after_disable",
            plugin_name=plugin_name,
        )

        self.event_bus.publish(Event(
            type="plugin.disabled",
            payload={"name": plugin_name},
            source="system",
        ))

        return True

    # ── Hot Reload ──

    def reload_plugin(self, plugin_name: str) -> bool:
        """
        Hot-reload a plugin.

        This unloads the plugin and reloads it while preserving
        the runtime context (event bus, hooks, services).

        Args:
            plugin_name: Plugin name

        Returns:
            True if reloaded successfully
        """
        logger.info(f"Hot-reloading plugin '{plugin_name}'...")

        # Save current state
        desc = self._plugins.get(plugin_name)
        if desc is None:
            logger.warning(f"Cannot reload '{plugin_name}': not loaded")
            return False

        saved_config = desc.config

        # Unload
        self.unload_plugin(plugin_name)

        # Clear discovery cache for this plugin
        self.discovery.invalidate_cache(plugin_name)

        # Re-discover
        for plugin_dir in self.discovery.plugin_dirs:
            candidate = os.path.join(plugin_dir, plugin_name)
            if os.path.exists(candidate):
                new_desc = self.discovery.discover_plugin(candidate)
                if new_desc:
                    self.dependency_resolver.register_plugin(new_desc)
                    break

        # Reload
        try:
            self.load_plugin(plugin_name, saved_config)
            instance = self.get_plugin(plugin_name)
            if instance:
                instance.on_hot_reload()
            if self._started:
                self.start_plugin(plugin_name)
            logger.info(f"Plugin '{plugin_name}' hot-reloaded successfully")
            return True
        except Exception as e:
            logger.error(
                f"Failed to hot-reload plugin '{plugin_name}': {e}",
                exc_info=True,
            )
            return False

    def _on_hot_reload(self, plugin_name: str) -> None:
        """Callback for hot-reload watcher."""
        logger.info(f"Detected source change in plugin '{plugin_name}'")
        self.reload_plugin(plugin_name)

    # ── Query Methods ──

    def get_plugin(self, plugin_name: str) -> Optional[PluginBase]:
        """Get a plugin instance by name."""
        desc = self._plugins.get(plugin_name)
        if desc is None:
            return None
        return desc.instance

    def get_plugin_descriptor(self, plugin_name: str) -> Optional[PluginDescriptor]:
        """Get a plugin descriptor by name."""
        return self._plugins.get(plugin_name)

    def get_plugin_state(self, plugin_name: str) -> Optional[PluginState]:
        """Get the current state of a plugin."""
        desc = self._plugins.get(plugin_name)
        if desc is None:
            return None
        return desc.state

    def list_plugins(self, state: Optional[PluginState] = None) -> List[Dict[str, Any]]:
        """
        List all loaded plugins with their descriptors.

        Args:
            state: Optional filter by state

        Returns:
            List of plugin descriptor dicts
        """
        results = []
        with self._load_lock:
            for desc in self._plugins.values():
                if state is None or desc.state == state:
                    results.append(desc.to_dict())
        return results

    def list_discovered(self) -> List[Dict[str, Any]]:
        """List all discovered (but not necessarily loaded) plugins."""
        results = []
        for desc in self.discovery.get_all_cached().values():
            results.append(desc.to_dict())
        return results

    def get_plugin_count(self) -> int:
        """Get the number of loaded plugins."""
        return len(self._plugins)

    def is_loaded(self, plugin_name: str) -> bool:
        """Check if a plugin is loaded."""
        return plugin_name in self._plugins

    def is_running(self, plugin_name: str) -> bool:
        """Check if a plugin is in STARTED state."""
        desc = self._plugins.get(plugin_name)
        if desc is None:
            return False
        if desc.is_isolated:
            return self.isolation.is_alive(plugin_name)
        return desc.state == PluginState.STARTED

    # ── Configuration Management ──

    def get_plugin_config(self, plugin_name: str) -> Optional[PluginConfig]:
        """Get the configuration for a plugin."""
        # Check in-memory first
        desc = self._plugins.get(plugin_name)
        if desc and desc.config:
            return desc.config

        # Fall back to config manager
        return self.config_manager.get_config(plugin_name)

    def set_plugin_config(
        self,
        plugin_name: str,
        settings: Optional[Dict[str, Any]] = None,
        enabled: Optional[bool] = None,
        isolation: Optional[str] = None,
    ) -> bool:
        """
        Update plugin configuration.

        Args:
            plugin_name: Plugin name
            settings: Settings to merge
            enabled: Whether to enable/disable
            isolation: Isolation mode

        Returns:
            True if updated
        """
        config = self.config_manager.update_config(
            plugin_name,
            settings=settings,
            enabled=enabled,
            isolation=isolation,
        )
        if config is None:
            return False

        # Notify running plugin
        desc = self._plugins.get(plugin_name)
        if desc and desc.instance:
            old_config = desc.config
            desc.config = config
            try:
                desc.instance.on_config_change(old_config, config)
            except Exception as e:
                logger.error(
                    f"Config change notification failed for "
                    f"'{plugin_name}': {e}"
                )
        elif desc and desc.is_isolated:
            import pickle
            config_hex = pickle.dumps(config).hex()
            self.isolation.send_command(plugin_name, {
                "type": "config",
                "config_hex": config_hex,
            })

        return True

    # ── Installation / Removal ──

    def install_plugin(self, source_path: str, target_name: Optional[str] = None) -> bool:
        """
        Install a plugin from a source path.

        Args:
            source_path: Path to plugin directory or file
            target_name: Optional name for the installed plugin

        Returns:
            True if installed successfully
        """
        source_path = os.path.abspath(source_path)
        if not os.path.exists(source_path):
            logger.error(f"Plugin source not found: {source_path}")
            return False

        # Determine target directory
        plugin_dirs = self.discovery.plugin_dirs
        if not plugin_dirs:
            logger.error("No plugin directories configured")
            return False

        target_dir = plugin_dirs[0]
        target_name = target_name or os.path.basename(source_path)

        # Check if already installed
        target_path = os.path.join(target_dir, target_name)
        if os.path.exists(target_path):
            logger.warning(f"Plugin '{target_name}' already exists at {target_path}")
            return False

        try:
            if os.path.isdir(source_path):
                shutil.copytree(source_path, target_path)
            else:
                os.makedirs(target_path, exist_ok=True)
                shutil.copy2(source_path, os.path.join(target_path, os.path.basename(source_path)))

            logger.info(f"Installed plugin '{target_name}' from {source_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to install plugin '{target_name}': {e}")
            return False

    def remove_plugin(self, plugin_name: str) -> bool:
        """
        Remove a plugin (unload + delete from disk).

        Args:
            plugin_name: Plugin name

        Returns:
            True if removed successfully
        """
        # Unload if loaded
        if self.is_loaded(plugin_name):
            self.unload_plugin(plugin_name)

        # Delete config
        self.config_manager.delete_config(plugin_name)

        # Delete from disk
        desc = self.discovery.get_cached(plugin_name)
        if desc and os.path.exists(desc.path):
            try:
                if os.path.isdir(desc.path):
                    shutil.rmtree(desc.path)
                else:
                    os.remove(desc.path)
                logger.info(f"Removed plugin '{plugin_name}'")
                return True
            except Exception as e:
                logger.error(
                    f"Failed to remove plugin '{plugin_name}': {e}"
                )
                return False

        logger.warning(f"Plugin '{plugin_name}' not found on disk")
        return False

    # ── API Versioning ──

    def _check_api_version(self, metadata: PluginMetadata) -> None:
        """
        Check if a plugin's API version is compatible.

        Args:
            metadata: Plugin metadata

        Raises:
            PluginVersionError: If incompatible
        """
        try:
            plugin_min = metadata.min_api_version
            plugin_min_parts = [int(x) for x in plugin_min.split(".")[:2]]

            if plugin_min_parts[0] > API_VERSION_MAJOR:
                raise PluginVersionError(
                    f"Plugin '{metadata.name}' requires API v{plugin_min}, "
                    f"but system has v{API_VERSION}"
                )
            if plugin_min_parts[0] == API_VERSION_MAJOR and plugin_min_parts[1] > API_VERSION_MINOR:
                raise PluginVersionError(
                    f"Plugin '{metadata.name}' requires API v{plugin_min}, "
                    f"but system has v{API_VERSION}"
                )
        except (ValueError, IndexError):
            # Malformed version string — assume compatible
            logger.warning(
                f"Could not parse API version for '{metadata.name}': "
                f"{metadata.min_api_version}"
            )

    # ── Shutdown ──

    def shutdown(self) -> None:
        """Complete shutdown of the plugin system."""
        logger.info("PluginManager shutting down...")

        self.stop_all_plugins()
        self.cleanup_all_plugins()
        self.isolation.shutdown_all()

        if self._enable_hot_reload:
            self.hot_reload.stop_watching()

        self.hook_registry.clear()
        self.event_bus.clear()
        self.service_registry.clear()

        self._initialized = False
        self._started = False
        logger.info("PluginManager shutdown complete")

    # ── Properties ──

    @property
    def api(self) -> PluginAPI:
        """Get the PluginAPI container."""
        return self._api

    @property
    def is_initialized(self) -> bool:
        """Whether the manager has been initialized."""
        return self._initialized

    @property
    def is_started(self) -> bool:
        """Whether plugins have been started."""
        return self._started


# ──────────────────────────────────────────────
# Plugin CLI
# ──────────────────────────────────────────────

class PluginCLI:
    """
    Command-line interface for plugin management.

    Provides commands for listing, installing, removing, enabling,
    disabling, and inspecting plugins.

    Usage:
        cli = PluginCLI(manager)
        cli.run(["list"])
        cli.run(["install", "--path", "/path/to/plugin"])
    """

    def __init__(self, manager: PluginManager):
        self.manager = manager
        self._parser = self._build_parser()

    def _build_parser(self) -> argparse.ArgumentParser:
        """Build the argument parser for CLI commands."""
        parser = argparse.ArgumentParser(
            prog="ainos-plugin",
            description="Ainos OS Plugin Manager CLI",
        )
        parser.add_argument(
            "--verbose", "-v",
            action="store_true",
            help="Enable verbose output",
        )

        subparsers = parser.add_subparsers(
            dest="command",
            help="Available commands",
        )

        # List
        list_parser = subparsers.add_parser(
            "list", help="List all plugins"
        )
        list_parser.add_argument(
            "--state", "-s",
            help="Filter by state (e.g., started, stopped, error)",
        )
        list_parser.add_argument(
            "--discovered", "-d",
            action="store_true",
            help="Show discovered (not just loaded) plugins",
        )
        list_parser.add_argument(
            "--json", "-j",
            action="store_true",
            help="Output as JSON",
        )

        # Info
        info_parser = subparsers.add_parser(
            "info", help="Show plugin details"
        )
        info_parser.add_argument(
            "name",
            help="Plugin name",
        )

        # Install
        install_parser = subparsers.add_parser(
            "install", help="Install a plugin"
        )
        install_parser.add_argument(
            "--path", "-p",
            required=True,
            help="Path to plugin source",
        )
        install_parser.add_argument(
            "--name", "-n",
            help="Target plugin name",
        )

        # Remove
        remove_parser = subparsers.add_parser(
            "remove", help="Remove a plugin"
        )
        remove_parser.add_argument(
            "name",
            help="Plugin name to remove",
        )
        remove_parser.add_argument(
            "--force", "-f",
            action="store_true",
            help="Force removal",
        )

        # Enable
        enable_parser = subparsers.add_parser(
            "enable", help="Enable a plugin"
        )
        enable_parser.add_argument(
            "name",
            help="Plugin name to enable",
        )

        # Disable
        disable_parser = subparsers.add_parser(
            "disable", help="Disable a plugin"
        )
        disable_parser.add_argument(
            "name",
            help="Plugin name to disable",
        )

        # Reload
        reload_parser = subparsers.add_parser(
            "reload", help="Hot-reload a plugin"
        )
        reload_parser.add_argument(
            "name",
            help="Plugin name to reload",
        )

        # Load
        load_parser = subparsers.add_parser(
            "load", help="Load a plugin"
        )
        load_parser.add_argument(
            "name",
            help="Plugin name to load",
        )

        # Start
        start_parser = subparsers.add_parser(
            "start", help="Start a plugin"
        )
        start_parser.add_argument(
            "name",
            help="Plugin name to start",
        )

        # Stop
        stop_parser = subparsers.add_parser(
            "stop", help="Stop a plugin"
        )
        stop_parser.add_argument(
            "name",
            help="Plugin name to stop",
        )

        # Config
        config_parser = subparsers.add_parser(
            "config", help="View or update plugin configuration"
        )
        config_parser.add_argument(
            "name",
            help="Plugin name",
        )
        config_parser.add_argument(
            "--set", "-s",
            nargs=2,
            metavar=("KEY", "VALUE"),
            help="Set a configuration key-value pair",
        )
        config_parser.add_argument(
            "--json", "-j",
            action="store_true",
            help="Output as JSON",
        )

        # Dependencies
        deps_parser = subparsers.add_parser(
            "deps", help="Show plugin dependencies"
        )
        deps_parser.add_argument(
            "name",
            nargs="?",
            help="Plugin name (shows all if omitted)",
        )

        # Events
        subparsers.add_parser(
            "events", help="Show event bus statistics"
        )

        # Services
        subparsers.add_parser(
            "services", help="List registered services"
        )

        # Hooks
        subparsers.add_parser(
            "hooks", help="List registered hooks"
        )

        # Scan
        scan_parser = subparsers.add_parser(
            "scan", help="Rescan plugin directories"
        )
        scan_parser.add_argument(
            "--clear-cache",
            action="store_true",
            help="Clear discovery cache before scanning",
        )

        return parser

    def run(self, args: Optional[List[str]] = None) -> int:
        """
        Run the CLI with the given arguments.

        Args:
            args: Command-line arguments (defaults to sys.argv[1:])

        Returns:
            Exit code (0 for success, 1 for error)
        """
        if args is None:
            args = sys.argv[1:]

        parsed = self._parser.parse_args(args)

        if parsed.verbose:
            logging.getLogger("ainos.plugins").setLevel(logging.DEBUG)

        if not parsed.command:
            self._parser.print_help()
            return 0

        try:
            handler = getattr(
                self, f"_cmd_{parsed.command}", self._cmd_unknown
            )
            return handler(parsed)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            if parsed.verbose:
                traceback.print_exc()
            return 1

    def _cmd_list(self, args: argparse.Namespace) -> int:
        """Handle 'list' command."""
        if args.discovered:
            plugins = self.manager.list_discovered()
        else:
            state_filter = None
            if args.state:
                try:
                    state_filter = PluginState(args.state)
                except ValueError:
                    print(f"Invalid state: {args.state}")
                    return 1
            plugins = self.manager.list_plugins(state=state_filter)

        if args.json:
            print(json.dumps(plugins, indent=2, ensure_ascii=False))
            return 0

        if not plugins:
            print("No plugins found.")
            return 0

        # Table header
        print(f"{'Name':<25} {'Version':<12} {'State':<12} {'Author':<20}")
        print("-" * 75)

        for p in plugins:
            name = p["name"]
            version = p["version"]
            state = p["state"]
            author = p["metadata"].get("author", "")[:18]
            print(f"{name:<25} {version:<12} {state:<12} {author:<20}")

        print(f"\nTotal: {len(plugins)} plugin(s)")
        return 0

    def _cmd_info(self, args: argparse.Namespace) -> int:
        """Handle 'info' command."""
        name = args.name

        # Try loaded first
        desc = self.manager.get_plugin_descriptor(name)
        if desc is None:
            # Try discovered
            desc = self.manager.discovery.get_cached(name)

        if desc is None:
            print(f"Plugin '{name}' not found.")
            return 1

        print(f"\nPlugin: {desc.name}")
        print(f"  Version:     {desc.version}")
        print(f"  State:       {desc.state.value}")
        print(f"  Path:        {desc.path}")
        print(f"  Entry:       {desc.entry_point}")
        print(f"  Author:      {desc.metadata.author or 'N/A'}")
        print(f"  License:     {desc.metadata.license}")
        print(f"  Description: {desc.metadata.description or 'N/A'}")
        print(f"  API Version: {desc.metadata.api_version}")
        print(f"  Isolated:    {desc.is_isolated}")

        if desc.metadata.dependencies:
            print(f"  Dependencies:")
            for dep, ver in desc.metadata.dependencies.items():
                status = "✓" if self.manager.is_loaded(dep) else "✗"
                print(f"    {status} {dep} ({ver})")

        if desc.metadata.provides_services:
            print(f"  Services: {', '.join(desc.metadata.provides_services)}")

        if desc.metadata.permissions:
            print(f"  Permissions: {', '.join(desc.metadata.permissions)}")

        if desc.error:
            print(f"  Error: {desc.error}")

        print()
        return 0

    def _cmd_install(self, args: argparse.Namespace) -> int:
        """Handle 'install' command."""
        success = self.manager.install_plugin(
            args.path, args.name
        )
        if success:
            print(f"Plugin installed successfully.")
            return 0
        else:
            print(f"Failed to install plugin.", file=sys.stderr)
            return 1

    def _cmd_remove(self, args: argparse.Namespace) -> int:
        """Handle 'remove' command."""
        success = self.manager.remove_plugin(args.name)
        if success:
            print(f"Plugin '{args.name}' removed.")
            return 0
        else:
            print(f"Failed to remove plugin '{args.name}'.", file=sys.stderr)
            return 1

    def _cmd_enable(self, args: argparse.Namespace) -> int:
        """Handle 'enable' command."""
        if self.manager.enable_plugin(args.name):
            print(f"Plugin '{args.name}' enabled.")
            return 0
        else:
            print(f"Failed to enable plugin '{args.name}'.", file=sys.stderr)
            return 1

    def _cmd_disable(self, args: argparse.Namespace) -> int:
        """Handle 'disable' command."""
        if self.manager.disable_plugin(args.name):
            print(f"Plugin '{args.name}' disabled.")
            return 0
        else:
            print(f"Failed to disable plugin '{args.name}'.", file=sys.stderr)
            return 1

    def _cmd_reload(self, args: argparse.Namespace) -> int:
        """Handle 'reload' command."""
        if self.manager.reload_plugin(args.name):
            print(f"Plugin '{args.name}' reloaded.")
            return 0
        else:
            print(f"Failed to reload plugin '{args.name}'.", file=sys.stderr)
            return 1

    def _cmd_load(self, args: argparse.Namespace) -> int:
        """Handle 'load' command."""
        try:
            self.manager.load_plugin(args.name)
            print(f"Plugin '{args.name}' loaded.")
            return 0
        except Exception as e:
            print(f"Failed to load plugin '{args.name}': {e}", file=sys.stderr)
            return 1

    def _cmd_start(self, args: argparse.Namespace) -> int:
        """Handle 'start' command."""
        if self.manager.start_plugin(args.name):
            print(f"Plugin '{args.name}' started.")
            return 0
        else:
            print(f"Failed to start plugin '{args.name}'.", file=sys.stderr)
            return 1

    def _cmd_stop(self, args: argparse.Namespace) -> int:
        """Handle 'stop' command."""
        if self.manager.stop_plugin(args.name):
            print(f"Plugin '{args.name}' stopped.")
            return 0
        else:
            print(f"Failed to stop plugin '{args.name}'.", file=sys.stderr)
            return 1

    def _cmd_config(self, args: argparse.Namespace) -> int:
        """Handle 'config' command."""
        if args.set:
            key, value = args.set
            # Try to parse JSON value
            try:
                parsed_value = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                parsed_value = value

            success = self.manager.set_plugin_config(
                args.name,
                settings={key: parsed_value},
            )
            if success:
                print(f"Config '{key}' set for '{args.name}'.")
                return 0
            else:
                print(f"Failed to set config.", file=sys.stderr)
                return 1
        else:
            config = self.manager.get_plugin_config(args.name)
            if config is None:
                print(f"No config found for '{args.name}'.")
                return 1

            if args.json:
                print(json.dumps({
                    "name": config.name,
                    "enabled": config.enabled,
                    "settings": config.settings,
                    "isolation": config.isolation,
                    "resource_limits": config.resource_limits,
                }, indent=2, ensure_ascii=False))
            else:
                print(f"Config for '{args.name}':")
                print(f"  Enabled:  {config.enabled}")
                print(f"  Isolation: {config.isolation or 'none'}")
                print(f"  Settings: {json.dumps(config.settings, indent=4, ensure_ascii=False)}")
                print(f"  Limits: {json.dumps(config.resource_limits, indent=4, ensure_ascii=False)}")

            return 0

    def _cmd_deps(self, args: argparse.Namespace) -> int:
        """Handle 'deps' command."""
        if args.name:
            try:
                graph = self.manager.dependency_resolver.resolve(args.name)
                order = graph.topological_sort()
                print(f"Dependencies for '{args.name}':")
                for dep in order:
                    if dep == args.name:
                        print(f"  → {dep} (self)")
                    else:
                        print(f"  ├ {dep}")
                print(f"\n{len(order)} plugin(s) in dependency chain")
            except PluginDependencyError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1
        else:
            try:
                order = self.manager.dependency_resolver.get_load_order()
                print("All plugins (load order):")
                for i, name in enumerate(order, 1):
                    print(f"  {i:2d}. {name}")
                print(f"\n{len(order)} plugin(s) total")
            except PluginDependencyError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1
        return 0

    def _cmd_events(self, args: argparse.Namespace) -> int:
        """Handle 'events' command."""
        stats = self.manager.event_bus.get_stats()
        subs = self.manager.event_bus.get_subscription_count()

        print("Event Bus Statistics:")
        print(f"  Published:    {stats.get('published', 0)}")
        print(f"  Delivered:    {stats.get('delivered', 0)}")
        print(f"  Dropped:      {stats.get('dropped', 0)}")
        print(f"  Errors:       {stats.get('errors', 0)}")
        print(f"  Subscriptions: {subs}")
        return 0

    def _cmd_services(self, args: argparse.Namespace) -> int:
        """Handle 'services' command."""
        services = self.manager.service_registry.list_services()

        if not services:
            print("No services registered.")
            return 0

        print(f"{'Service':<30} {'Type':<12} {'Plugin':<20} {'Version':<10}")
        print("-" * 75)

        for svc in services:
            name = svc.get("name", "?")
            svc_type = svc.get("type", "?")
            plugin = svc.get("plugin_name", "")
            version = svc.get("version", "?")
            print(f"{name:<30} {svc_type:<12} {plugin:<20} {version:<10}")

        print(f"\n{len(services)} service(s) registered")
        return 0

    def _cmd_hooks(self, args: argparse.Namespace) -> int:
        """Handle 'hooks' command."""
        hook_names = self.manager.hook_registry.list_hooks()

        if not hook_names:
            print("No hooks registered.")
            return 0

        print(f"{'Hook':<40} {'Handlers':<10}")
        print("-" * 50)

        for name in hook_names:
            hook = self.manager.hook_registry.get_hook(name)
            count = hook.handler_count if hook else 0
            print(f"{name:<40} {count:<10}")

        print(f"\n{len(hook_names)} hook(s) registered")
        return 0

    def _cmd_scan(self, args: argparse.Namespace) -> int:
        """Handle 'scan' command."""
        discovered = self.manager.discover_plugins(
            clear_cache=args.clear_cache
        )
        print(f"Discovered {len(discovered)} plugin(s).")
        if discovered:
            print("Plugins found:")
            for name in sorted(discovered.keys()):
                desc = discovered[name]
                print(f"  - {name} v{desc.version} ({desc.path})")
        return 0

    def _cmd_unknown(self, args: argparse.Namespace) -> int:
        """Handle unknown command."""
        print(f"Unknown command: {args.command}", file=sys.stderr)
        self._parser.print_help()
        return 1


# ──────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────

def main():
    """
    Main entry point for the plugin CLI.

    Usage:
        python -m plugins.plugin_manager list
        python -m plugins.plugin_manager install --path /path/to/plugin
        python -m plugins.plugin_manager info myplugin
    """
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Create manager with default plugin directories
    manager = PluginManager()
    manager.discover_plugins()

    # Run CLI
    cli = PluginCLI(manager)
    sys.exit(cli.run())


if __name__ == "__main__":
    main()