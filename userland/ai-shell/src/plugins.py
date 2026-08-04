"""
Plugin system for Ainos Shell.

Provides a plugin framework for extending shell functionality:
- Plugin discovery and loading
- Plugin lifecycle management (init, activate, deactivate)
- Hook system for shell events
- Plugin dependencies
- Configuration per plugin
- Sandboxed execution
- Plugin API for shell integration
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import sys
import threading
import time
import typing as t
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

from .utils import (
    AnsiCode,
    colorize,
    get_config_dir,
    ensure_dir,
    file_exists,
    read_file,
    write_file,
)
from .config import get_config

# ---------------------------------------------------------------------------
# Plugin hook types
# ---------------------------------------------------------------------------


class HookType(Enum):
    """Types of hooks that plugins can register for."""
    PRE_COMMAND = auto()       # Before command execution
    POST_COMMAND = auto()      # After command execution
    PRE_PROMPT = auto()        # Before prompt rendering
    POST_PROMPT = auto()       # After prompt rendering
    PRE_COMPLETION = auto()    # Before tab completion
    POST_COMPLETION = auto()   # After tab completion
    PRE_CD = auto()            # Before directory change
    POST_CD = auto()           # After directory change
    SHELL_START = auto()       # Shell startup
    SHELL_EXIT = auto()        # Shell exit
    PRE_HISTORY = auto()       # Before history add
    POST_HISTORY = auto()      # After history add
    COMMAND_NOT_FOUND = auto() # Command not found
    SIGNAL_RECEIVED = auto()   # Signal received
    PRE_REDRAW = auto()        # Before screen redraw
    CONFIG_CHANGE = auto()     # Configuration change


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------


@dataclass
class PluginInfo:
    """Metadata about a plugin."""
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    homepage: str = ""
    license: str = ""
    dependencies: list = field(default_factory=list)
    optional_dependencies: list = field(default_factory=list)
    min_shell_version: str = "1.0.0"
    max_shell_version: str = ""
    tags: list = field(default_factory=list)
    enabled: bool = True
    priority: int = 100  # Lower = higher priority

    def __repr__(self) -> str:
        return f"PluginInfo({self.name} v{self.version})"


@dataclass
class PluginContext:
    """Context provided to plugins during execution."""
    shell: t.Any = None
    config: dict = field(default_factory=dict)
    cwd: str = ""
    last_command: str = ""
    last_exit_code: int = 0
    env: dict = field(default_factory=dict)
    args: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Base plugin class
# ---------------------------------------------------------------------------

class Plugin:
    """Base class for all plugins."""

    # Plugin metadata - override in subclasses
    info: PluginInfo = PluginInfo()

    def __init__(self, context: t.Optional[PluginContext] = None) -> None:
        self.context = context or PluginContext()
        self._active = False
        self._hooks: t.Dict[HookType, t.List[t.Callable]] = {
            hook_type: [] for hook_type in HookType
        }
        self._config: dict = {}

    def initialize(self) -> None:
        """Initialize the plugin. Called after loading."""
        pass

    def activate(self) -> None:
        """Activate the plugin. Called when enabled."""
        self._active = True

    def deactivate(self) -> None:
        """Deactivate the plugin. Called when disabled."""
        self._active = False

    @property
    def is_active(self) -> bool:
        """Check if the plugin is active."""
        return self._active

    # Hook registration methods
    def on_pre_command(self, func: t.Callable) -> None:
        """Register a pre-command hook."""
        self._hooks[HookType.PRE_COMMAND].append(func)

    def on_post_command(self, func: t.Callable) -> None:
        """Register a post-command hook."""
        self._hooks[HookType.POST_COMMAND].append(func)

    def on_pre_prompt(self, func: t.Callable) -> None:
        """Register a pre-prompt hook."""
        self._hooks[HookType.PRE_PROMPT].append(func)

    def on_post_prompt(self, func: t.Callable) -> None:
        """Register a post-prompt hook."""
        self._hooks[HookType.POST_PROMPT].append(func)

    def on_pre_cd(self, func: t.Callable) -> None:
        """Register a pre-cd hook."""
        self._hooks[HookType.PRE_CD].append(func)

    def on_post_cd(self, func: t.Callable) -> None:
        """Register a post-cd hook."""
        self._hooks[HookType.POST_CD].append(func)

    def on_shell_start(self, func: t.Callable) -> None:
        """Register a shell-start hook."""
        self._hooks[HookType.SHELL_START].append(func)

    def on_shell_exit(self, func: t.Callable) -> None:
        """Register a shell-exit hook."""
        self._hooks[HookType.SHELL_EXIT].append(func)

    def on_command_not_found(self, func: t.Callable) -> None:
        """Register a command-not-found hook."""
        self._hooks[HookType.COMMAND_NOT_FOUND].append(func)

    def on_config_change(self, func: t.Callable) -> None:
        """Register a config-change hook."""
        self._hooks[HookType.CONFIG_CHANGE].append(func)

    def get_hooks(self, hook_type: HookType) -> t.List[t.Callable]:
        """Get all hooks for a type."""
        return self._hooks.get(hook_type, [])

    def get_config(self, key: str, default: t.Any = None) -> t.Any:
        """Get a plugin configuration value."""
        return self._config.get(key, default)

    def set_config(self, key: str, value: t.Any) -> None:
        """Set a plugin configuration value."""
        self._config[key] = value

    def load_config(self, config_dict: dict) -> None:
        """Load configuration from a dictionary."""
        self._config.update(config_dict)

    def __repr__(self) -> str:
        status = "active" if self._active else "inactive"
        return f"Plugin({self.info.name}, {status})"


# ---------------------------------------------------------------------------
# Plugin loader
# ---------------------------------------------------------------------------

class PluginLoader:
    """Discovers and loads plugins from various sources."""

    def __init__(self) -> None:
        self._plugin_dirs: t.List[str] = []
        self._discovered: t.Dict[str, t.Type[Plugin]] = {}
        self._loaded: t.Dict[str, Plugin] = {}

    def add_directory(self, directory: str) -> None:
        """Add a directory to search for plugins."""
        if directory not in self._plugin_dirs:
            self._plugin_dirs.append(directory)

    def discover(self) -> t.Dict[str, t.Type[Plugin]]:
        """Discover plugins in configured directories."""
        self._discovered = {}

        for directory in self._plugin_dirs:
            if not os.path.isdir(directory):
                continue

            # Add to path for import
            if directory not in sys.path:
                sys.path.insert(0, directory)

            for filename in os.listdir(directory):
                if filename.startswith("_"):
                    continue

                if filename.endswith(".py"):
                    module_name = filename[:-3]
                    self._discover_module(module_name, directory)

                elif os.path.isdir(os.path.join(directory, filename)):
                    # Check for __init__.py
                    init_file = os.path.join(directory, filename, "__init__.py")
                    if os.path.isfile(init_file):
                        self._discover_module(filename, directory)

        return self._discovered

    def _discover_module(self, module_name: str, directory: str) -> None:
        """Discover plugins within a module."""
        try:
            spec = importlib.util.spec_from_file_location(
                module_name,
                os.path.join(directory, f"{module_name}.py"),
            )
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Find Plugin subclasses
                for name, obj in inspect.getmembers(module):
                    if (inspect.isclass(obj) and issubclass(obj, Plugin)
                            and obj is not Plugin):
                        plugin_name = getattr(obj.info, "name", name)
                        self._discovered[plugin_name] = obj
        except Exception as e:
            import logging
            logging.warning(f"Failed to discover plugin {module_name}: {e}")

    def load_plugin(self, name: str, context: t.Optional[PluginContext] = None) -> t.Optional[Plugin]:
        """Load a specific plugin by name."""
        if name in self._loaded:
            return self._loaded[name]

        plugin_class = self._discovered.get(name)
        if plugin_class is None:
            return None

        try:
            plugin = plugin_class(context)
            plugin.initialize()
            self._loaded[name] = plugin
            return plugin
        except Exception as e:
            import logging
            logging.error(f"Failed to load plugin {name}: {e}")
            return None

    def load_all(self, context: t.Optional[PluginContext] = None) -> t.Dict[str, Plugin]:
        """Load all discovered plugins."""
        for name in self._discovered:
            self.load_plugin(name, context)
        return self._loaded

    def unload_plugin(self, name: str) -> bool:
        """Unload a plugin."""
        if name in self._loaded:
            plugin = self._loaded[name]
            if plugin.is_active:
                plugin.deactivate()
            del self._loaded[name]
            return True
        return False

    def get_loaded_plugins(self) -> t.Dict[str, Plugin]:
        """Get all loaded plugins."""
        return dict(self._loaded)

    def get_plugin(self, name: str) -> t.Optional[Plugin]:
        """Get a loaded plugin by name."""
        return self._loaded.get(name)

    def __repr__(self) -> str:
        return f"PluginLoader(discovered={len(self._discovered)}, loaded={len(self._loaded)})"


# ---------------------------------------------------------------------------
# Plugin manager
# ---------------------------------------------------------------------------

class PluginManager:
    """Manages the complete plugin lifecycle."""

    def __init__(self) -> None:
        self.loader = PluginLoader()
        self._hook_registry: t.Dict[HookType, t.List[t.Tuple[Plugin, t.Callable]]] = {
            hook_type: [] for hook_type in HookType
        }
        self._initialized = False

    def initialize(self, context: t.Optional[PluginContext] = None) -> None:
        """Initialize the plugin system."""
        if self._initialized:
            return

        # Add default plugin directories
        builtin_plugin_dir = os.path.join(os.path.dirname(__file__), "..", "plugins")
        if os.path.isdir(builtin_plugin_dir):
            self.loader.add_directory(builtin_plugin_dir)

        # Add user plugin directories
        config = get_config()
        for plugin_dir in config.plugins.plugin_dirs:
            if os.path.isdir(plugin_dir):
                self.loader.add_directory(plugin_dir)

        # Add custom plugin dirs from config
        custom_dirs = get_config().plugins.plugin_dirs
        for d in custom_dirs:
            if os.path.isdir(d):
                self.loader.add_directory(d)

        # Discover plugins
        self.loader.discover()

        # Load plugins
        if context is None:
            context = PluginContext()

        self.loader.load_all(context)

        # Register hooks
        for plugin in self.loader.get_loaded_plugins().values():
            self._register_plugin_hooks(plugin)

        # Activate all plugins
        for plugin in self.loader.get_loaded_plugins().values():
            if plugin.info.enabled:
                plugin.activate()

        self._initialized = True

    def _register_plugin_hooks(self, plugin: Plugin) -> None:
        """Register all hooks from a plugin."""
        for hook_type in HookType:
            for hook_func in plugin.get_hooks(hook_type):
                self._hook_registry[hook_type].append((plugin, hook_func))

    def trigger_hook(self, hook_type: HookType, *args: t.Any, **kwargs: t.Any) -> None:
        """Trigger all hooks of a given type."""
        for plugin, hook_func in self._hook_registry.get(hook_type, []):
            if not plugin.is_active:
                continue
            try:
                hook_func(*args, **kwargs)
            except Exception as e:
                import logging
                logging.warning(f"Plugin hook error in {plugin.info.name}: {e}")

    def trigger_hook_with_return(self, hook_type: HookType, *args: t.Any,
                                  **kwargs: t.Any) -> t.List[t.Any]:
        """Trigger hooks and collect return values."""
        results = []
        for plugin, hook_func in self._hook_registry.get(hook_type, []):
            if not plugin.is_active:
                continue
            try:
                result = hook_func(*args, **kwargs)
                if result is not None:
                    results.append((plugin, result))
            except Exception as e:
                import logging
                logging.warning(f"Plugin hook error in {plugin.info.name}: {e}")
        return results

    def get_plugin(self, name: str) -> t.Optional[Plugin]:
        """Get a loaded plugin by name."""
        return self.loader.get_plugin(name)

    def get_plugins(self) -> t.List[Plugin]:
        """Get all loaded plugins."""
        return list(self.loader.get_loaded_plugins().values())

    def enable_plugin(self, name: str) -> bool:
        """Enable a plugin."""
        plugin = self.loader.get_plugin(name)
        if plugin:
            plugin.info.enabled = True
            plugin.activate()
            return True
        return False

    def disable_plugin(self, name: str) -> bool:
        """Disable a plugin."""
        plugin = self.loader.get_plugin(name)
        if plugin:
            plugin.info.enabled = False
            plugin.deactivate()
            return True
        return False

    def reload_plugins(self) -> None:
        """Reload all plugins."""
        # Deactivate all
        for plugin in self.loader.get_loaded_plugins().values():
            plugin.deactivate()

        # Clear and reload
        self._hook_registry = {hook_type: [] for hook_type in HookType}
        self.loader._loaded.clear()
        self.loader._discovered.clear()
        self._initialized = False
        self.initialize()

    def shutdown(self) -> None:
        """Shutdown the plugin system."""
        for plugin in self.loader.get_loaded_plugins().values():
            plugin.deactivate()

        self.trigger_hook(HookType.SHELL_EXIT)

    def list_plugins(self) -> t.List[dict]:
        """List all loaded plugins with metadata."""
        return [
            {
                "name": plugin.info.name,
                "version": plugin.info.version,
                "description": plugin.info.description,
                "author": plugin.info.author,
                "enabled": plugin.info.enabled,
                "active": plugin.is_active,
            }
            for plugin in self.loader.get_loaded_plugins().values()
        ]

    def __repr__(self) -> str:
        return f"PluginManager(plugins={len(self.loader.get_loaded_plugins())})"


# ---------------------------------------------------------------------------
# Module-level access
# ---------------------------------------------------------------------------

_plugin_manager: t.Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    """Get the global plugin manager singleton."""
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
    return _plugin_manager


__all__ = [
    "Plugin", "PluginInfo", "PluginContext",
    "PluginLoader", "PluginManager",
    "HookType",
    "get_plugin_manager",
]