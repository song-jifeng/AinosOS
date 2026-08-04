"""
Configuration management for Ainos Shell.

Handles loading, saving, and merging of configuration from multiple sources:
- Default settings
- System-wide config (/etc/ainosrc)
- User config (~/.ainoshrc, ~/.config/ainos/ainos.conf)
- Environment variables
- Command-line flags

Supports JSON, YAML, and TOML config formats with automatic detection.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import typing as t
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .utils import (
    IS_WINDOWS,
    get_config_dir,
    get_home_dir,
    file_exists,
    read_file,
    write_file,
    ensure_dir,
    expanduser,
    AnsiCode,
)

# ---------------------------------------------------------------------------
# Configuration data classes
# ---------------------------------------------------------------------------


@dataclass
class ThemeConfig:
    """Theme-related configuration."""
    name: str = "default"
    prompt_style: str = "powerline"  # plain, powerline, minimal, fish
    show_git_status: bool = True
    show_ai_status: bool = True
    show_time: bool = False
    show_exit_code: bool = True
    show_hostname: bool = False
    show_user: bool = False
    show_full_path: bool = False
    color_prompt: bool = True
    color_output: bool = True
    color_error: bool = True
    enable_256_colors: bool = True
    enable_truecolor: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ThemeConfig":
        valid_keys = set(cls.__dataclass_fields__.keys())
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**filtered)


@dataclass
class EditorConfig:
    """Editor-related configuration."""
    default_editor: str = "vim"
    line_numbers: bool = True
    syntax_highlight: bool = True
    auto_save: bool = False
    tab_width: int = 4
    expand_tabs: bool = True


@dataclass
class HistoryConfig:
    """History-related configuration."""
    enabled: bool = True
    file: str = ""  # Empty means default (~/.ainos/history.db)
    size: int = 10000
    dedup: bool = True
    ignore_dups: bool = True
    ignore_space: bool = True
    ignore_commands: list = field(default_factory=lambda: ["exit", "logout"])
    save_on_exit: bool = True
    share_between_sessions: bool = False
    max_lines: int = 10000


@dataclass
class CompletionConfig:
    """Completion-related configuration."""
    enabled: bool = True
    fuzzy: bool = True
    case_insensitive: bool = True
    min_prefix_length: int = 1
    max_suggestions: int = 20
    show_descriptions: bool = True
    ai_completion: bool = True
    file_completion: bool = True
    command_completion: bool = True
    variable_completion: bool = True
    history_completion: bool = True
    plugin_completion: bool = True


@dataclass
class AIConfig:
    """AI-related configuration."""
    enabled: bool = True
    provider: str = "openai"  # openai, anthropic, local, custom
    model: str = "gpt-4o"
    api_key: str = ""
    api_base: str = ""
    temperature: float = 0.3
    max_tokens: int = 1024
    timeout: int = 30
    suggest_commands: bool = True
    explain_errors: bool = True
    auto_complete: bool = True
    natural_language: bool = True
    cache_results: bool = True
    cache_ttl: int = 3600
    local_model_path: str = ""
    custom_endpoint: str = ""


@dataclass
class PluginConfig:
    """Plugin-related configuration."""
    enabled: bool = True
    load_on_startup: bool = True
    plugin_dirs: list = field(default_factory=lambda: [
        os.path.join(get_config_dir(), "plugins"),
    ])
    blacklist: list = field(default_factory=list)
    whitelist: list = field(default_factory=list)
    allow_remote: bool = False
    sandbox: bool = True


@dataclass
class BehaviorConfig:
    """Shell behavior configuration."""
    default_shell: str = "bash"
    interactive: bool = True
    login: bool = False
    pipefail: bool = True
    errexit: bool = False
    nounset: bool = False
    nocaseglob: bool = False
    dotglob: bool = False
    autocd: bool = True
    cdpath: list = field(default_factory=list)
    ignoreeof: bool = True
    mail_warning: bool = False
    notify: bool = False
    vi_mode: bool = False
    emacs_mode: bool = True
    beep: bool = True
    bell_style: str = "audible"
    log_file: str = ""
    log_level: str = "warning"


@dataclass
class KeyBindingsConfig:
    """Key binding configuration."""
    use_emacs_bindings: bool = True
    use_vi_bindings: bool = False
    custom_bindings: dict = field(default_factory=dict)


@dataclass
class AinosShellConfig:
    """Top-level configuration for Ainos Shell."""
    theme: ThemeConfig = field(default_factory=ThemeConfig)
    editor: EditorConfig = field(default_factory=EditorConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)
    completion: CompletionConfig = field(default_factory=CompletionConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    plugins: PluginConfig = field(default_factory=PluginConfig)
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)
    keybindings: KeyBindingsConfig = field(default_factory=KeyBindingsConfig)

    # Top-level settings
    shell_name: str = "ainos-sh"
    shell_version: str = "1.0.0"
    term: str = os.environ.get("TERM", "xterm-256color")
    lang: str = os.environ.get("LANG", "en_US.UTF-8")
    data_dir: str = field(default_factory=lambda: os.path.join(get_config_dir(), "data"))

    # Aliases
    aliases: dict = field(default_factory=lambda: {
        "ll": "ls -la",
        "la": "ls -a",
        "l": "ls -CF",
        "g": "grep",
        "..": "cd ..",
        "...": "cd ../..",
        "....": "cd ../../..",
        "cls": "clear",
        "h": "history",
        "q": "exit",
        "md": "mkdir -p",
        "rd": "rmdir",
        "rmf": "rm -rf",
        "cp": "cp -i",
        "mv": "mv -i",
        "python": "python3" if not IS_WINDOWS else "python",
    })

    # Environment variables to set on startup
    env: dict = field(default_factory=dict)

    # Startup commands to run
    startup_commands: list = field(default_factory=list)

    # Functions
    functions: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert config to a flat dictionary."""
        result = {}
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            if hasattr(value, "to_dict"):
                result[field_name] = value.to_dict()
            elif isinstance(value, (list, dict, str, int, float, bool, type(None))):
                result[field_name] = value
            else:
                result[field_name] = str(value)
        return result

    @classmethod
    def from_dict(cls, d: dict) -> "AinosShellConfig":
        """Create config from a dictionary, merging with defaults."""
        config = cls()

        # Map sub-config sections
        section_map = {
            "theme": "theme",
            "editor": "editor",
            "history": "history",
            "completion": "completion",
            "ai": "ai",
            "plugins": "plugins",
            "behavior": "behavior",
            "keybindings": "keybindings",
        }

        for key, value in d.items():
            if key in section_map and isinstance(value, dict):
                section_class = getattr(config, section_map[key]).__class__
                try:
                    setattr(config, section_map[key], section_class.from_dict(value))
                except Exception:
                    pass
            elif key in cls.__dataclass_fields__:
                setattr(config, key, value)

        return config


# ---------------------------------------------------------------------------
# Configuration file discovery
# ---------------------------------------------------------------------------

def get_config_paths() -> list:
    """Return ordered list of config file paths to search."""
    paths = []

    # System-wide config
    system_config = "/etc/ainosrc"
    if os.path.exists(system_config):
        paths.append(system_config)

    # User config via XDG
    xdg_config = os.environ.get(
        "XDG_CONFIG_HOME",
        os.path.join(get_home_dir(), ".config"),
    )
    xdg_config_file = os.path.join(xdg_config, "ainos", "ainos.conf")
    if os.path.exists(xdg_config_file):
        paths.append(xdg_config_file)

    # User config via ~/.ainoshrc
    user_rc = os.path.join(get_home_dir(), ".ainoshrc")
    if os.path.exists(user_rc):
        paths.append(user_rc)

    # User config via ~/.ainos/config
    ainos_config = os.path.join(get_config_dir(), "config")
    if os.path.exists(ainos_config):
        paths.append(ainos_config)

    # User config via ~/.ainos/ainos.conf
    ainos_conf = os.path.join(get_config_dir(), "ainos.conf")
    if os.path.exists(ainos_conf):
        paths.append(ainos_conf)

    # User config via ~/.config/ainosrc
    alt_config = os.path.join(get_home_dir(), ".config", "ainosrc")
    if os.path.exists(alt_config):
        paths.append(alt_config)

    return paths


def detect_config_format(path: str) -> str:
    """Detect config file format by extension."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".json",):
        return "json"
    elif ext in (".yaml", ".yml"):
        return "yaml"
    elif ext in (".toml",):
        return "toml"
    elif ext in (".conf", ".rc", ""):
        return "rc"  # Shell-style config
    return "rc"


# ---------------------------------------------------------------------------
# Config loading / saving
# ---------------------------------------------------------------------------

class ConfigManager:
    """Manages loading, merging, and saving configuration."""

    def __init__(self) -> None:
        self.config = AinosShellConfig()
        self.loaded_files: list = []
        self._dirty: bool = False

    def load_defaults(self) -> None:
        """Load default configuration values."""
        self.config = AinosShellConfig()

    def load_file(self, path: str) -> bool:
        """Load a config file, returning True on success."""
        if not os.path.exists(path):
            return False

        try:
            fmt = detect_config_format(path)
            content = read_file(path)

            if fmt == "json":
                data = json.loads(content)
                merged = self._merge_config(self.config.to_dict(), data)
                self.config = AinosShellConfig.from_dict(merged)
                self.loaded_files.append(path)
                return True

            elif fmt == "rc":
                data = self._parse_rc_file(content)
                merged = self._merge_config(self.config.to_dict(), data)
                self.config = AinosShellConfig.from_dict(merged)
                self.loaded_files.append(path)
                return True

            else:
                # Unsupported format, try as rc-style
                data = self._parse_rc_file(content)
                merged = self._merge_config(self.config.to_dict(), data)
                self.config = AinosShellConfig.from_dict(merged)
                self.loaded_files.append(path)
                return True

        except (json.JSONDecodeError, IOError, OSError) as e:
            raise ValueError(f"Error loading config {path}: {e}")

    def _parse_rc_file(self, content: str) -> dict:
        """Parse a shell-style rc config file into a config dict."""
        data: dict = {}
        current_section = "top"

        for line in content.split("\n"):
            line = line.strip()

            # Skip comments and empty lines
            if not line or line.startswith("#") or line.startswith(";"):
                continue

            # Section header: [section]
            section_match = re.match(r"^\[([^\]]+)\]$", line)
            if section_match:
                current_section = section_match.group(1).strip().lower()
                if current_section not in data:
                    data[current_section] = {}
                continue

            # Key-value: key = value
            kv_match = re.match(r"^\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*[:=]\s*(.*?)\s*$", line)
            if kv_match:
                key = kv_match.group(1).strip()
                value = kv_match.group(2).strip()

                # Remove surrounding quotes
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]

                # Parse value types
                parsed_value = self._parse_value(value)

                if current_section == "top":
                    data[key] = parsed_value
                else:
                    data.setdefault(current_section, {})
                    data[current_section][key] = parsed_value

        return data

    def _parse_value(self, value: str) -> t.Any:
        """Parse a config value string into its proper type."""
        # Boolean
        if value.lower() in ("true", "yes", "on", "1"):
            return True
        elif value.lower() in ("false", "no", "off", "0"):
            return False

        # None
        if value.lower() in ("none", "null", "nil"):
            return None

        # Integer
        try:
            return int(value)
        except ValueError:
            pass

        # Float
        try:
            return float(value)
        except ValueError:
            pass

        # List (comma-separated)
        if "," in value and not (value.startswith("'") or value.startswith('"')):
            parts = [p.strip() for p in value.split(",")]
            if parts:
                return parts

        # Dict (JSON-like)
        if value.startswith("{") and value.endswith("}"):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass

        return value

    def _merge_config(self, base: dict, override: dict) -> dict:
        """Deep merge override into base, returning a new dict."""
        result = deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_config(result[key], value)
            else:
                result[key] = deepcopy(value)
        return result

    def load_all(self) -> "ConfigManager":
        """Load configuration from all sources in order of precedence."""
        self.load_defaults()

        # Load environment variables as overrides
        self._load_from_env()

        # Load config files
        for path in get_config_paths():
            try:
                self.load_file(path)
            except (ValueError, IOError) as e:
                # Log but continue
                import logging
                logging.warning(f"Failed to load config {path}: {e}")

        return self

    def _load_from_env(self) -> None:
        """Load configuration from environment variables."""
        prefix = "AINOS_"
        for key, value in os.environ.items():
            if key.startswith(prefix):
                config_key = key[len(prefix):].lower()
                if config_key == "ai_api_key":
                    self.config.ai.api_key = value
                elif config_key == "ai_model":
                    self.config.ai.model = value
                elif config_key == "ai_provider":
                    self.config.ai.provider = value
                elif config_key == "ai_enabled":
                    self.config.ai.enabled = value.lower() in ("true", "1", "yes")
                elif config_key == "theme":
                    self.config.theme.name = value
                elif config_key == "editor":
                    self.config.editor.default_editor = value
                elif config_key == "history_size":
                    try:
                        self.config.history.size = int(value)
                    except ValueError:
                        pass

    def save(self, path: Optional[str] = None) -> bool:
        """Save configuration to a file."""
        if path is None:
            path = os.path.join(get_config_dir(), "config")

        ensure_dir(os.path.dirname(path))

        try:
            write_file(path, self._format_as_rc(self.config))
            self._dirty = False
            return True
        except (IOError, OSError) as e:
            import logging
            logging.error(f"Failed to save config to {path}: {e}")
            return False

    def _format_as_rc(self, config: AinosShellConfig) -> str:
        """Format the configuration as a shell-style rc file."""
        lines = []
        lines.append("# Ainos Shell Configuration")
        lines.append(f"# Generated by {config.shell_name} v{config.shell_version}")
        lines.append("")

        # Top-level settings
        lines.append("[core]")
        lines.append(f"shell_name = {config.shell_name}")
        lines.append(f"shell_version = {config.shell_version}")
        lines.append(f"term = {config.term}")
        lines.append(f"lang = {config.lang}")
        lines.append("")

        # Theme section
        lines.append("[theme]")
        for key, value in asdict(config.theme).items():
            lines.append(f"{key} = {self._format_value(value)}")
        lines.append("")

        # Editor section
        lines.append("[editor]")
        for key, value in asdict(config.editor).items():
            lines.append(f"{key} = {self._format_value(value)}")
        lines.append("")

        # History section
        lines.append("[history]")
        for key, value in asdict(config.history).items():
            lines.append(f"{key} = {self._format_value(value)}")
        lines.append("")

        # Completion section
        lines.append("[completion]")
        for key, value in asdict(config.completion).items():
            lines.append(f"{key} = {self._format_value(value)}")
        lines.append("")

        # AI section
        lines.append("[ai]")
        ai_dict = asdict(config.ai)
        # Mask API key
        if ai_dict.get("api_key"):
            ai_dict["api_key"] = "***"
        for key, value in ai_dict.items():
            lines.append(f"{key} = {self._format_value(value)}")
        lines.append("")

        # Plugins section
        lines.append("[plugins]")
        for key, value in asdict(config.plugins).items():
            lines.append(f"{key} = {self._format_value(value)}")
        lines.append("")

        # Behavior section
        lines.append("[behavior]")
        for key, value in asdict(config.behavior).items():
            lines.append(f"{key} = {self._format_value(value)}")
        lines.append("")

        # Aliases
        lines.append("[aliases]")
        for alias, command in config.aliases.items():
            lines.append(f"{alias} = {command}")
        lines.append("")

        # Environment
        lines.append("[env]")
        for key, value in config.env.items():
            lines.append(f"{key} = {value}")
        lines.append("")

        return "\n".join(lines)

    def _format_value(self, value: t.Any) -> str:
        """Format a value for the rc file."""
        if value is None:
            return "none"
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, list):
            return ", ".join(str(v) for v in value)
        else:
            return str(value)

    def get(self, key: str, default: t.Any = None) -> t.Any:
        """Get a flat config value by dot-separated key."""
        parts = key.split(".")
        obj = self.config
        for part in parts:
            if hasattr(obj, part):
                obj = getattr(obj, part)
            else:
                return default
        return obj

    def set(self, key: str, value: t.Any) -> None:
        """Set a config value by dot-separated key."""
        parts = key.split(".")
        obj = self.config
        for part in parts[:-1]:
            if hasattr(obj, part):
                obj = getattr(obj, part)
            else:
                raise KeyError(f"Invalid config key: {key}")

        if hasattr(obj, parts[-1]):
            setattr(obj, parts[-1], value)
            self._dirty = True
        else:
            raise KeyError(f"Invalid config key: {key}")

    def reload(self) -> None:
        """Reload configuration from all sources."""
        self.loaded_files.clear()
        self.load_all()

    def is_dirty(self) -> bool:
        """Check if configuration has been modified since last save."""
        return self._dirty

    def __repr__(self) -> str:
        return f"ConfigManager(loaded={len(self.loaded_files)} files, dirty={self._dirty})"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_config_manager: t.Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """Get the global config manager singleton."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
        _config_manager.load_all()
    return _config_manager


def get_config() -> AinosShellConfig:
    """Get the current shell configuration."""
    return get_config_manager().config


# ---------------------------------------------------------------------------
# Convenience accessors
# ---------------------------------------------------------------------------

def get_alias(name: str) -> t.Optional[str]:
    """Get an alias definition."""
    return get_config().aliases.get(name)


def set_alias(name: str, command: str) -> None:
    """Set an alias definition."""
    get_config().aliases[name] = command
    get_config_manager()._dirty = True


def unset_alias(name: str) -> bool:
    """Remove an alias definition. Returns True if existed."""
    return bool(get_config().aliases.pop(name, None))


def get_aliases() -> dict:
    """Get all aliases."""
    return dict(get_config().aliases)


def resolve_alias(name: str) -> str:
    """Resolve an alias, recursively expanding aliases."""
    visited = set()
    while name in get_config().aliases and name not in visited:
        visited.add(name)
        name = get_config().aliases[name]
    return name


__all__ = [
    "AinosShellConfig", "ThemeConfig", "EditorConfig", "HistoryConfig",
    "CompletionConfig", "AIConfig", "PluginConfig", "BehaviorConfig",
    "KeyBindingsConfig",
    "ConfigManager", "get_config_manager", "get_config",
    "get_config_paths", "detect_config_format",
    "get_alias", "set_alias", "unset_alias", "get_aliases", "resolve_alias",
]