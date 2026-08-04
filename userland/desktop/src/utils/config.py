#!/usr/bin/env python3
"""Ainos Desktop - Configuration Manager.

This module provides centralized configuration management using
YAML files with JSON fallback, supporting hot-reload and defaults.
"""

import os
import json
import yaml
import logging
import threading
from typing import Any
from datetime import datetime
from copy import deepcopy

logger = logging.getLogger(__name__)


class ConfigManager:
    """Centralized configuration manager with file persistence.

    Supports YAML and JSON formats, nested key access with dot notation,
    default values, and automatic saving.
    """

    DEFAULT_CONFIG: dict[str, Any] = {
        # Connection settings
        "connection": {
            "host": "127.0.0.1",
            "port": 8765,
            "use_ssl": False,
            "api_key": "",
            "timeout_ms": 30000,
            "reconnect_interval_ms": 5000,
            "max_reconnect_attempts": 10,
            "heartbeat_interval_ms": 15000,
        },
        # Theme settings
        "theme": "dark",
        "language": "en",
        # Window settings
        "window": {
            "geometry": "",
            "maximized": False,
            "fullscreen": False,
            "minimized": False,
            "minimize_on_close": True,
        },
        # Tray settings
        "tray": {
            "enabled": True,
            "minimize_on_close": True,
        },
        # Inference defaults
        "inference": {
            "temperature": 0.7,
            "top_p": 0.9,
            "top_k": 40,
            "max_tokens": 2048,
            "stream": True,
            "default_model": "",
        },
        # Logging settings
        "logging": {
            "level": "INFO",
            "file": "",
            "max_size_mb": 100,
            "backup_count": 5,
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        },
        # Monitor settings
        "monitor": {
            "update_interval_ms": 2000,
            "history_seconds": 60,
            "show_gpu": True,
            "show_cpu": True,
            "show_memory": True,
            "show_disk": True,
            "show_network": False,
        },
        # Dashboard settings
        "dashboard": {
            "update_interval_ms": 3000,
            "chart_style": "line",
            "show_legend": True,
            "max_data_points": 300,
        },
        # Model manager settings
        "model_manager": {
            "show_system_models": False,
            "auto_refresh": True,
            "refresh_interval_ms": 30000,
            "confirm_unload": True,
        },
        # Context settings
        "context_viewer": {
            "max_entries_per_page": 100,
            "default_format": "json",
            "show_metadata": True,
            "auto_refresh": True,
            "refresh_interval_ms": 10000,
        },
        # Log viewer settings
        "log_viewer": {
            "max_lines": 10000,
            "auto_scroll": True,
            "show_timestamps": True,
            "filter_level": "DEBUG",
            "wrap_lines": False,
        },
        # Auto-save
        "auto_save_interval": 300000,  # 5 minutes
        # UI settings
        "ui": {
            "font_size": 10,
            "font_family": "",
            "zoom_level": 1.0,
            "sidebar_width": 250,
            "show_toolbar": True,
            "show_status_bar": True,
            "compact_mode": False,
        },
        # Recent files
        "recent_files": [],
        "recent_models": [],
    }

    def __init__(self, config_dir: str | None = None):
        """Initialize the configuration manager.

        Args:
            config_dir: Directory for configuration files. Uses default
                       platform-specific location if None.
        """
        self._config_dir = config_dir or self._get_default_config_dir()
        self._config_file = os.path.join(self._config_dir, "config.yaml")
        self._config: dict[str, Any] = deepcopy(self.DEFAULT_CONFIG)
        self._lock = threading.RLock()
        self._dirty = False
        self._watcher_active = False
        self._watch_thread: threading.Thread | None = None
        self._last_load_time: float = 0.0
        self._change_callbacks: list[callable] = []

        # Ensure config directory exists
        os.makedirs(self._config_dir, exist_ok=True)

        # Load existing configuration
        self.load()

        logger.info("ConfigManager initialized at %s", self._config_file)

    def _get_default_config_dir(self) -> str:
        """Get the default platform-specific configuration directory.

        Returns:
            Path to the configuration directory.
        """
        if os.name == "nt":  # Windows
            base = os.environ.get("APPDATA", os.path.expanduser("~"))
            return os.path.join(base, "Ainos", "Desktop")
        elif os.uname().sysname == "Darwin":  # macOS
            return os.path.join(
                os.path.expanduser("~"),
                "Library", "Application Support", "Ainos", "Desktop"
            )
        else:  # Linux
            xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
            return os.path.join(xdg, "ainos", "desktop")

    def load(self) -> dict[str, Any]:
        """Load configuration from file.

        Returns:
            The loaded configuration dictionary.

        Raises:
            IOError: If the file exists but cannot be read.
        """
        with self._lock:
            if not os.path.isfile(self._config_file):
                logger.debug("No config file found at %s, using defaults", self._config_file)
                return deepcopy(self._config)

            try:
                with open(self._config_file, "r", encoding="utf-8") as f:
                    if self._config_file.endswith(".yaml") or self._config_file.endswith(".yml"):
                        loaded = yaml.safe_load(f) or {}
                    else:
                        loaded = json.load(f)

                # Merge loaded config with defaults (preserving defaults for missing keys)
                self._deep_merge(self._config, loaded)
                self._last_load_time = os.path.getmtime(self._config_file)
                self._dirty = False

                logger.info("Configuration loaded from %s", self._config_file)
                return deepcopy(self._config)

            except (yaml.YAMLError, json.JSONDecodeError) as e:
                logger.error("Failed to parse config file: %s", e)
                return deepcopy(self._config)
            except (IOError, OSError) as e:
                logger.error("Failed to read config file: %s", e)
                raise

    def save(self) -> bool:
        """Save configuration to file.

        Returns:
            True if saved successfully.

        Raises:
            IOError: If the file cannot be written.
        """
        with self._lock:
            if not self._dirty:
                return True

            try:
                # Ensure directory exists
                os.makedirs(self._config_dir, exist_ok=True)

                # Write to a temporary file first
                temp_file = self._config_file + ".tmp"
                with open(temp_file, "w", encoding="utf-8") as f:
                    if self._config_file.endswith(".yaml") or self._config_file.endswith(".yml"):
                        yaml.dump(
                            self._config,
                            f,
                            default_flow_style=False,
                            allow_unicode=True,
                            indent=2,
                            sort_keys=False,
                        )
                    else:
                        json.dump(self._config, f, indent=2, ensure_ascii=False)

                # Atomic rename
                os.replace(temp_file, self._config_file)
                self._dirty = False
                self._last_load_time = os.path.getmtime(self._config_file)

                logger.debug("Configuration saved to %s", self._config_file)
                return True

            except (IOError, OSError) as e:
                logger.error("Failed to save config file: %s", e)
                raise

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by dot-separated key.

        Args:
            key: Dot-separated key path (e.g., 'connection.host').
            default: Default value if key is not found.

        Returns:
            Configuration value or default.
        """
        with self._lock:
            keys = key.split(".")
            value = self._config
            for k in keys:
                if isinstance(value, dict):
                    value = value.get(k)
                else:
                    return default
                if value is None:
                    return default
            return value

    def set(self, key: str, value: Any, save: bool = False) -> None:
        """Set a configuration value by dot-separated key.

        Args:
            key: Dot-separated key path (e.g., 'connection.host').
            value: Value to set.
            save: If True, immediately save to file.
        """
        with self._lock:
            keys = key.split(".")
            target = self._config
            for k in keys[:-1]:
                if k not in target:
                    target[k] = {}
                target = target[k]
            target[keys[-1]] = value
            self._dirty = True

            # Notify change callbacks
            for callback in self._change_callbacks:
                try:
                    callback(key, value)
                except Exception as e:
                    logger.error("Config change callback error: %s", e)

            if save:
                self.save()

            logger.debug("Config set: %s = %s", key, value)

    def get_all(self) -> dict[str, Any]:
        """Get the entire configuration dictionary.

        Returns:
            Deep copy of the configuration.
        """
        with self._lock:
            return deepcopy(self._config)

    def reset(self, key: str | None = None) -> None:
        """Reset configuration to defaults.

        Args:
            key: Optional dot-separated key to reset. If None, resets all.
        """
        with self._lock:
            if key is None:
                self._config = deepcopy(self.DEFAULT_CONFIG)
            else:
                default_value = self.get_from_defaults(key)
                self.set(key, default_value)
            self._dirty = True
            logger.info("Configuration reset: %s", key if key else "all")

    def get_from_defaults(self, key: str) -> Any:
        """Get a value from the default configuration.

        Args:
            key: Dot-separated key path.

        Returns:
            Default value or None.
        """
        keys = key.split(".")
        value = self.DEFAULT_CONFIG
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return None
        return value

    def load_from_file(self, path: str) -> bool:
        """Load configuration from a specific file path.

        Args:
            path: Path to the configuration file.

        Returns:
            True if loaded successfully.
        """
        old_config_file = self._config_file
        self._config_file = os.path.abspath(path)
        try:
            self.load()
            self._dirty = True
            logger.info("Configuration loaded from: %s", path)
            return True
        except Exception as e:
            self._config_file = old_config_file
            logger.error("Failed to load config from %s: %s", path, e)
            return False

    def on_change(self, callback: callable) -> None:
        """Register a callback for configuration changes.

        Args:
            callback: Callable with signature (key, value).
        """
        if callback not in self._change_callbacks:
            self._change_callbacks.append(callback)

    def remove_change_callback(self, callback: callable) -> None:
        """Remove a previously registered change callback.

        Args:
            callback: The callback to remove.
        """
        if callback in self._change_callbacks:
            self._change_callbacks.remove(callback)

    def watch_file(self, interval_ms: int = 5000) -> None:
        """Start watching the config file for external changes.

        Args:
            interval_ms: Polling interval in milliseconds.
        """
        if self._watcher_active:
            return

        self._watcher_active = True

        def _watch_loop():
            while self._watcher_active:
                try:
                    if os.path.isfile(self._config_file):
                        mtime = os.path.getmtime(self._config_file)
                        if mtime > self._last_load_time:
                            logger.info("Config file changed externally, reloading...")
                            self.load()
                except Exception as e:
                    logger.debug("Config watch error: %s", e)

                threading.Event().wait(interval_ms / 1000.0)

        self._watch_thread = threading.Thread(target=_watch_loop, daemon=True)
        self._watch_thread.start()
        logger.info("Config file watcher started (interval: %dms)", interval_ms)

    def stop_watching(self) -> None:
        """Stop watching the config file."""
        self._watcher_active = False
        if self._watch_thread:
            self._watch_thread.join(timeout=2.0)
            self._watch_thread = None
        logger.info("Config file watcher stopped")

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> None:
        """Recursively merge override dict into base dict.

        Args:
            base: Base dictionary to merge into.
            override: Dictionary with values to override.
        """
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                ConfigManager._deep_merge(base[key], value)
            else:
                base[key] = deepcopy(value)

    @property
    def config_file(self) -> str:
        """Get the path to the configuration file.

        Returns:
            Absolute path to the config file.
        """
        return self._config_file

    @property
    def config_dir(self) -> str:
        """Get the configuration directory path.

        Returns:
            Absolute path to the config directory.
        """
        return self._config_dir