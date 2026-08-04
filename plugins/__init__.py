"""
Ainos OS - Plugin System
========================
A comprehensive plugin system for Ainos OS that supports plugin discovery,
lifecycle management, hot-reloading, dependency resolution, and isolation.

This package provides:
- PluginBase: Abstract base class for all plugins
- PluginManager: Central manager for plugin lifecycle and discovery
- Hook system for intercepting events
- Event bus for async communication
- Service registry for plugin service discovery
- API versioning for backward compatibility
"""

from .api import (
    PluginBase,
    Hook,
    HookPriority,
    HookRegistry,
    Event,
    EventBus,
    EventPriority,
    ServiceRegistry,
    PluginAPI,
    API_VERSION,
    PluginConfig,
    PluginMetadata,
    PluginState,
    PluginException,
    HookException,
    EventException,
    ServiceException,
    PluginLoadError,
    PluginDependencyError,
    PluginVersionError,
)

from .plugin_manager import (
    PluginManager,
    PluginDiscovery,
    PluginLifecycle,
    PluginDependencyResolver,
    PluginConfigManager,
    PluginIsolation,
    PluginCLI,
    PluginHotReload,
)

__all__ = [
    # API
    "PluginBase",
    "Hook",
    "HookPriority",
    "HookRegistry",
    "Event",
    "EventBus",
    "EventPriority",
    "ServiceRegistry",
    "PluginAPI",
    "API_VERSION",
    "PluginConfig",
    "PluginMetadata",
    "PluginState",
    "PluginException",
    "HookException",
    "EventException",
    "ServiceException",
    "PluginLoadError",
    "PluginDependencyError",
    "PluginVersionError",
    # Manager
    "PluginManager",
    "PluginDiscovery",
    "PluginLifecycle",
    "PluginDependencyResolver",
    "PluginConfigManager",
    "PluginIsolation",
    "PluginCLI",
    "PluginHotReload",
]

__version__ = "0.1.0"