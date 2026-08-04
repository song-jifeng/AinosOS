#!/usr/bin/env python3
"""AI-Powered Code Formatting Tool.

An intelligent code formatter that supports multiple languages,
custom rule configuration, style checking, and auto-fix capabilities.
Integrates with popular external formatters while providing its own
analysis and formatting pipeline.
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field, fields
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

__version__ = "1.0.0"
__author__ = "AI-Formatter Team"

PROJECT_NAME = "ai-formatter"
CONFIG_FILENAMES: Tuple[str, ...] = (
    ".ai-formatter.yml",
    ".ai-formatter.yaml",
    ".ai-formatter.json",
    "ai-formatter.yml",
    "ai-formatter.yaml",
    "ai-formatter.json",
    "pyproject.toml",
)

SUPPORTED_LANGUAGES: Tuple[str, ...] = (
    "python",
    "c",
    "rust",
    "java",
    "go",
)

EXTERNAL_FORMATTERS: Dict[str, str] = {
    "python": "black",
    "c": "clang-format",
    "rust": "rustfmt",
    "java": "google-java-format",
    "go": "gofmt",
}

DEFAULT_INDENT_SIZE: int = 4
DEFAULT_LINE_LENGTH: int = 88
DEFAULT_ENCODING: str = "utf-8"

STYLE_NAMES: Tuple[str, ...] = (
    "pep8",
    "google",
    "mozilla",
    "webkit",
    "rust",
    "go",
    "custom",
)


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------


class AIFormatterError(Exception):
    """Base exception for all AI formatter errors."""

    def __init__(self, message: str, code: int = 1) -> None:
        """Initialize the base formatter error.

        Args:
            message: Human-readable error description.
            code: Exit code suitable for CLI usage.
        """
        super().__init__(message)
        self.code = code
        self.message = message


class ConfigError(AIFormatterError):
    """Raised when configuration loading or parsing fails."""

    def __init__(self, message: str, path: Optional[Path] = None) -> None:
        """Initialize a configuration error.

        Args:
            message: Description of the configuration problem.
            path: Optional file path that caused the error.
        """
        super().__init__(message, code=2)
        self.config_path = path


class ParseError(AIFormatterError):
    """Raised when source code parsing fails."""

    def __init__(self, message: str, lineno: int = 0) -> None:
        """Initialize a parse error.

        Args:
            message: Description of the parse failure.
            lineno: Approximate line number where parsing failed.
        """
        super().__init__(message, code=3)
        self.lineno = lineno


class FormatError(AIFormatterError):
    """Raised when formatting operations fail."""

    def __init__(self, message: str, language: str = "") -> None:
        """Initialize a format error.

        Args:
            message: Description of the formatting failure.
            language: The language being formatted when the error occurred.
        """
        super().__init__(message, code=4)
        self.language = language


class ExternalToolError(AIFormatterError):
    """Raised when an external formatting tool fails."""

    def __init__(
        self,
        message: str,
        tool_name: str = "",
        return_code: int = -1,
        stderr: str = "",
    ) -> None:
        """Initialize an external tool error.

        Args:
            message: Description of the tool failure.
            tool_name: Name of the external tool that failed.
            return_code: Exit code from the tool.
            stderr: Standard error output from the tool.
        """
        super().__init__(message, code=5)
        self.tool_name = tool_name
        self.return_code = return_code
        self.stderr = stderr


class StyleViolationError(AIFormatterError):
    """Raised to indicate style violations (check mode)."""

    def __init__(self, message: str, violations: int = 0) -> None:
        """Initialize a style violation error.

        Args:
            message: Summary of style violations.
            violations: Count of violations found.
        """
        super().__init__(message, code=6)
        self.violation_count = violations


# ---------------------------------------------------------------------------
# Enums and Simple Data Types
# ---------------------------------------------------------------------------


class Severity(Enum):
    """Severity level for formatting issues and style violations."""

    ERROR = auto()
    WARNING = auto()
    INFO = auto()
    HINT = auto()


class FixMode(Enum):
    """Auto-fix mode selection."""

    NONE = "none"
    SAFE = "safe"
    ALL = "all"


@dataclass(frozen=True)
class Violation:
    """Represents a single style violation or formatting issue.

    Attributes:
        lineno: Line number where the violation occurs.
        col_offset: Column offset for the violation.
        code: Short identifier for the violation type.
        message: Human-readable description.
        severity: Severity level of the violation.
        suggestion: Suggested replacement text, if any.
    """

    lineno: int
    col_offset: int
    code: str
    message: str
    severity: Severity
    suggestion: str = ""


@dataclass
class FormatResult:
    """Result of a formatting operation on a single file.

    Attributes:
        path: Path to the formatted file.
        success: Whether formatting succeeded.
        changed: Whether the file content changed.
        diff: Unified diff of changes, if any.
        violations: List of style violations found.
        errors: List of error messages encountered.
        elapsed_ms: Elapsed time in milliseconds.
    """

    path: Path
    success: bool = True
    changed: bool = False
    diff: str = ""
    violations: List[Violation] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    elapsed_ms: float = 0.0


@dataclass
class Rule:
    """A single formatting or style rule.

    Attributes:
        name: Unique rule identifier.
        description: Human-readable description of the rule.
        language: Target language, or '*' for all languages.
        enabled: Whether the rule is active.
        severity: Severity when this rule is violated.
        pattern: Regex pattern or rule-specific data.
        fix: Optional fix expression or callable name.
        options: Additional rule-specific key-value options.
    """

    name: str
    description: str = ""
    language: str = "*"
    enabled: bool = True
    severity: Severity = Severity.WARNING
    pattern: str = ""
    fix: str = ""
    options: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Diff Output
# ---------------------------------------------------------------------------


class DiffOutput:
    """Generates and manages unified diff output for formatted files."""

    def __init__(self, context_lines: int = 3) -> None:
        """Initialize diff output generator.

        Args:
            context_lines: Number of context lines to show around changes.
        """
        self.context_lines = context_lines

    def generate(
        self,
        original: str,
        formatted: str,
        file_path: Union[str, Path],
    ) -> str:
        """Generate a unified diff string between original and formatted text.

        Args:
            original: The original source code content.
            formatted: The formatted source code content.
            file_path: Path to the file (used in the diff header).

        Returns:
            A string containing the unified diff.
        """
        original_lines = original.splitlines(keepends=True)
        formatted_lines = formatted.splitlines(keepends=True)

        diff = difflib.unified_diff(
            original_lines,
            formatted_lines,
            fromfile=str(file_path),
            tofile=str(file_path),
            fromfiledate="(original)",
            tofiledate="(formatted)",
            n=self.context_lines,
        )

        return "".join(diff)

    def generate_from_file(
        self, original_path: Path, formatted_path: Path
    ) -> str:
        """Generate a diff between two files on disk.

        Args:
            original_path: Path to the original file.
            formatted_path: Path to the formatted file.

        Returns:
            A string containing the unified diff.
        """
        original = original_path.read_text(encoding=DEFAULT_ENCODING)
        formatted = formatted_path.read_text(encoding=DEFAULT_ENCODING)
        return self.generate(original, formatted, original_path)

    def has_changes(self, original: str, formatted: str) -> bool:
        """Check if formatting produced any changes.

        Args:
            original: The original source code content.
            formatted: The formatted source code content.

        Returns:
            True if the content differs, False otherwise.
        """
        return original != formatted

    @staticmethod
    def colorize_diff(diff_text: str) -> str:
        """Add ANSI color codes to a diff string for terminal display.

        Args:
            diff_text: A unified diff string.

        Returns:
            The diff string with ANSI color codes added.
        """
        lines: List[str] = []
        for line in diff_text.splitlines(keepends=True):
            if line.startswith("+++") or line.startswith("---"):
                lines.append(f"\033[1;34m{line}\033[0m")  # Bold blue
            elif line.startswith("@@"):
                lines.append(f"\033[36m{line}\033[0m")  # Cyan
            elif line.startswith("+"):
                lines.append(f"\033[32m{line}\033[0m")  # Green
            elif line.startswith("-"):
                lines.append(f"\033[31m{line}\033[0m")  # Red
            else:
                lines.append(line)
        return "".join(lines)

    @staticmethod
    def compute_statistics(diff_text: str) -> Dict[str, int]:
        """Compute statistics from a diff string.

        Args:
            diff_text: A unified diff string.

        Returns:
            Dictionary with keys 'additions', 'deletions', 'files_changed'.
        """
        additions = 0
        deletions = 0
        files_changed = 0

        for line in diff_text.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                files_changed += 1
            elif line.startswith("+") and not line.startswith("+++"):
                additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1

        return {
            "additions": additions,
            "deletions": deletions,
            "files_changed": files_changed // 2,
        }


# ---------------------------------------------------------------------------
# Rule Management
# ---------------------------------------------------------------------------


class RuleManager:
    """Manages formatting and style rules including loading, validation,
    and application of rules to source code."""

    def __init__(self) -> None:
        """Initialize the rule manager with an empty rule registry."""
        self._rules: Dict[str, Rule] = {}
        self._language_rules: Dict[str, List[str]] = defaultdict(list)
        self._builtin_rules: Set[str] = set()

    def register_rule(self, rule: Rule) -> None:
        """Register a single rule.

        Args:
            rule: The Rule instance to register.

        Raises:
            ValueError: If a rule with the same name is already registered.
        """
        if rule.name in self._rules:
            raise ValueError(
                f"Rule '{rule.name}' is already registered."
            )
        self._rules[rule.name] = rule
        self._language_rules[rule.language].append(rule.name)

    def register_builtin_rules(self) -> None:
        """Register all built-in formatting and style rules."""
        builtins: List[Rule] = [
            Rule(
                name="trailing-whitespace",
                description="Remove trailing whitespace from lines.",
                language="*",
                severity=Severity.INFO,
                pattern=r"[ \t]+$",
                fix="strip_trailing_whitespace",
            ),
            Rule(
                name="missing-newline-eof",
                description="File must end with a single newline.",
                language="*",
                severity=Severity.WARNING,
                pattern=r"[^\n]\Z",
                fix="ensure_final_newline",
            ),
            Rule(
                name="indent-inconsistent",
                description="Indentation should be consistent (tabs vs spaces).",
                language="*",
                severity=Severity.WARNING,
                pattern=r"^(\t+|[ ]+)(?=\S)",
                fix="normalize_indent",
            ),
            Rule(
                name="line-length",
                description="Line exceeds maximum length.",
                language="*",
                severity=Severity.WARNING,
                pattern=r"^.{80,}$",
                fix="",
            ),
            Rule(
                name="python-import-order",
                description="Imports should follow PEP 8 grouping.",
                language="python",
                severity=Severity.WARNING,
                pattern=r"",
                fix="sort_imports",
            ),
            Rule(
                name="python-blank-lines",
                description="Expected 2 blank lines before class/top-level def.",
                language="python",
                severity=Severity.WARNING,
                pattern=r"",
                fix="adjust_blank_lines",
            ),
            Rule(
                name="c-brace-style",
                description="Braces should follow the configured style.",
                language="c",
                severity=Severity.WARNING,
                pattern=r"",
                fix="fix_brace_style",
            ),
            Rule(
                name="c-pointer-placement",
                description="Pointer asterisk should be consistent.",
                language="c",
                severity=Severity.INFO,
                pattern=r"(\w+)\s*\*\s*(\w+)",
                fix="",
            ),
            Rule(
                name="rust-naming-convention",
                description="Follow Rust naming conventions (snake_case, CamelCase).",
                language="rust",
                severity=Severity.ERROR,
                pattern=r"",
                fix="",
            ),
            Rule(
                name="java-javadoc-style",
                description="Javadoc comments should follow standard formatting.",
                language="java",
                severity=Severity.WARNING,
                pattern=r"/\*\*.*?\*/",
                fix="",
            ),
            Rule(
                name="go-err-check",
                description="Errors should be explicitly checked in Go.",
                language="go",
                severity=Severity.WARNING,
                pattern=r"",
                fix="",
            ),
        ]

        for rule in builtins:
            self.register_rule(rule)
            self._builtin_rules.add(rule.name)

    def get_rule(self, name: str) -> Optional[Rule]:
        """Get a rule by name.

        Args:
            name: The name of the rule to retrieve.

        Returns:
            The Rule instance if found, None otherwise.
        """
        return self._rules.get(name)

    def get_rules_for_language(
        self, language: str, enabled_only: bool = True
    ) -> List[Rule]:
        """Get all rules applicable to a given language.

        Args:
            language: Target language identifier.
            enabled_only: If True, only return enabled rules.

        Returns:
            List of Rule instances applicable to the language.
        """
        result: List[Rule] = []
        seen: Set[str] = set()

        for lang in ("*", language):
            for name in self._language_rules.get(lang, []):
                if name not in seen:
                    seen.add(name)
                    rule = self._rules.get(name)
                    if rule is not None:
                        if enabled_only and not rule.enabled:
                            continue
                        result.append(rule)

        return result

    def enable_rule(self, name: str, enabled: bool = True) -> None:
        """Enable or disable a rule.

        Args:
            name: The name of the rule.
            enabled: True to enable, False to disable.

        Raises:
            KeyError: If the rule name is not found.
        """
        if name not in self._rules:
            raise KeyError(f"Rule '{name}' not found.")
        self._rules[name].enabled = enabled

    def remove_rule(self, name: str) -> None:
        """Remove a custom rule. Built-in rules cannot be removed.

        Args:
            name: The name of the rule to remove.

        Raises:
            KeyError: If the rule is not found or is built-in.
        """
        if name not in self._rules:
            raise KeyError(f"Rule '{name}' not found.")
        if name in self._builtin_rules:
            raise KeyError(
                f"Rule '{name}' is a built-in rule and cannot be removed."
            )
        rule = self._rules.pop(name)
        self._language_rules[rule.language].remove(name)

    def load_rules_from_config(self, config: Dict[str, Any]) -> int:
        """Load rules from a configuration dictionary.

        Args:
            config: Dictionary with rule definitions. Expected format:
                {
                    "rules": [
                        {"name": "...", "enabled": true, ...},
                        ...
                    ]
                }

        Returns:
            Number of rules successfully loaded.

        Raises:
            ConfigError: If the configuration format is invalid.
        """
        if not isinstance(config, dict):
            raise ConfigError("Rules configuration must be a dictionary.")

        rules_data = config.get("rules", [])
        if not isinstance(rules_data, list):
            raise ConfigError("'rules' must be a list.")

        count = 0
        for item in rules_data:
            if not isinstance(item, dict):
                continue

            name = item.get("name", "")
            if not name:
                continue

            severity_str = item.get("severity", "WARNING").upper()
            try:
                severity = Severity[severity_str]
            except KeyError:
                severity = Severity.WARNING

            rule = Rule(
                name=name,
                description=item.get("description", ""),
                language=item.get("language", "*"),
                enabled=item.get("enabled", True),
                severity=severity,
                pattern=item.get("pattern", ""),
                fix=item.get("fix", ""),
                options=item.get("options", {}),
            )

            if name in self._rules:
                self._rules[name] = rule
            else:
                self.register_rule(rule)

            count += 1

        return count

    def list_rules(
        self, language: Optional[str] = None, verbose: bool = False
    ) -> List[str]:
        """List registered rules, optionally filtered by language.

        Args:
            language: If set, only list rules for this language.
            verbose: If True, include full rule details.

        Returns:
            List of formatted rule strings.
        """
        if language:
            rules = self.get_rules_for_language(language, enabled_only=False)
        else:
            rules = list(self._rules.values())

        if not verbose:
            return [
                f"{'[x]' if r.enabled else '[ ]'} {r.name} ({r.language})"
                for r in sorted(rules, key=lambda x: x.name)
            ]

        output: List[str] = []
        for r in sorted(rules, key=lambda x: x.name):
            tag = "BUILTIN" if r.name in self._builtin_rules else "CUSTOM"
            output.append(
                f"{'[x]' if r.enabled else '[ ]'} {r.name} [{tag}]"
            )
            output.append(f"      Language: {r.language}")
            output.append(f"      Severity: {r.severity.name}")
            if r.description:
                output.append(f"      Description: {r.description}")
            if r.pattern:
                output.append(f"      Pattern: {r.pattern}")
            output.append("")

        return output

    @property
    def rule_count(self) -> int:
        """Return the total number of registered rules."""
        return len(self._rules)

    @property
    def builtin_count(self) -> int:
        """Return the number of built-in rules."""
        return len(self._builtin_rules)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class FormatterConfig:
    """Manages configuration loading, validation, and access for the
    AI formatter. Supports YAML, JSON, and TOML (pyproject.toml) formats."""

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        """Initialize the configuration manager.

        Args:
            config_dir: Directory to search for config files. If None,
                        uses the current working directory.
        """
        self._config_dir: Path = config_dir or Path.cwd()
        self._data: Dict[str, Any] = self._defaults()
        self._loaded_path: Optional[Path] = None

    @staticmethod
    def _defaults() -> Dict[str, Any]:
        """Return the default configuration dictionary.

        Returns:
            Dictionary with default configuration values.
        """
        return {
            "language": "python",
            "line_length": DEFAULT_LINE_LENGTH,
            "indent_size": DEFAULT_INDENT_SIZE,
            "indent_style": "space",  # space | tab
            "style": "pep8",
            "fix_mode": "safe",
            "check_only": False,
            "diff": False,
            "quiet": False,
            "verbose": False,
            "external_formatter": True,
            "respect_gitignore": True,
            "include": [],
            "exclude": [],
            "rules": [],
            "formatter_options": {},
        }

    def load(self, path: Optional[Path] = None) -> bool:
        """Load configuration from a file.

        Searches for a config file in the config directory if no path
        is given. Looks for .ai-formatter.yml, .ai-formatter.json, etc.

        Args:
            path: Optional explicit path to a config file.

        Returns:
            True if a config file was loaded, False if none found.

        Raises:
            ConfigError: If the config file format is invalid.
        """
        if path is not None:
            return self._load_file(path)

        for filename in CONFIG_FILENAMES:
            candidate = self._config_dir / filename
            if candidate.is_file():
                return self._load_file(candidate)

        return False

    def _load_file(self, path: Path) -> bool:
        """Load configuration from a specific file path.

        Args:
            path: Path to the configuration file.

        Returns:
            True if the file was loaded successfully.

        Raises:
            ConfigError: If the file format is not supported or parsing fails.
        """
        if not path.is_file():
            raise ConfigError(f"Config file not found: {path}", path=path)

        suffix = path.suffix.lower()
        try:
            raw = path.read_text(encoding=DEFAULT_ENCODING)
        except OSError as e:
            raise ConfigError(
                f"Cannot read config file: {e}", path=path
            ) from e

        if suffix in (".yml", ".yaml"):
            if yaml is None:
                raise ConfigError(
                    "PyYAML is required to load .yml/.yaml config files. "
                    "Install it with: pip install pyyaml",
                    path=path,
                )
            try:
                data = yaml.safe_load(raw)
            except yaml.YAMLError as e:
                raise ConfigError(
                    f"Invalid YAML config: {e}", path=path
                ) from e
        elif suffix == ".json":
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ConfigError(
                    f"Invalid JSON config: {e}", path=path
                ) from e
        elif suffix == ".toml" or path.name == "pyproject.toml":
            data = self._parse_toml(raw, path)
        else:
            raise ConfigError(
                f"Unsupported config file format: {suffix}", path=path
            )

        if data is None:
            data = {}

        if not isinstance(data, dict):
            raise ConfigError(
                "Config file must contain a top-level dictionary.",
                path=path,
            )

        # If pyproject.toml, look for [tool.ai-formatter] section
        if path.name == "pyproject.toml":
            data = data.get("tool", {}).get("ai-formatter", {})

        if not isinstance(data, dict):
            raise ConfigError(
                "Config data must be a dictionary.", path=path
            )

        self._validate(data)
        self._data.update(data)
        self._loaded_path = path
        return True

    @staticmethod
    def _parse_toml(raw: str, path: Path) -> Dict[str, Any]:
        """Parse TOML configuration (basic parser without toml dependency).

        Args:
            raw: Raw TOML content.
            path: Path to the file (for error reporting).

        Returns:
            Parsed dictionary.

        Raises:
            ConfigError: If a `toml` library import is required.
        """
        # Try to use the `tomllib` (Python 3.11+) or `toml` third-party lib.
        # Fall back to a minimal inline parser for simple cases.
        if sys.version_info >= (3, 11):
            try:
                import tomllib
                return tomllib.loads(raw)
            except ImportError:
                pass
            except Exception as e:
                raise ConfigError(
                    f"Invalid TOML config: {e}", path=path
                ) from e

        try:
            import tomllib
            return tomllib.loads(raw)
        except ImportError:
            pass

        try:
            import toml
            return toml.loads(raw)
        except ImportError:
            pass
        except Exception as e:
            raise ConfigError(
                f"Invalid TOML config: {e}", path=path
            ) from e

        # Minimal fallback: warn and return empty
        raise ConfigError(
            "tomllib (Python 3.11+) or the 'toml' package is required "
            "to parse pyproject.toml. Install with: pip install toml",
            path=path,
        )

    @staticmethod
    def _validate(data: Dict[str, Any]) -> None:
        """Validate configuration data types and values.

        Args:
            data: The configuration dictionary to validate.

        Raises:
            ConfigError: If any configuration value is invalid.
        """
        valid_keys: Set[str] = {
            "language", "line_length", "indent_size", "indent_style",
            "style", "fix_mode", "check_only", "diff", "quiet", "verbose",
            "external_formatter", "respect_gitignore", "include", "exclude",
            "rules", "formatter_options",
        }

        for key in data:
            if key not in valid_keys:
                raise ConfigError(f"Unknown configuration key: '{key}'.")

        if "language" in data:
            lang = data["language"]
            if lang not in SUPPORTED_LANGUAGES:
                raise ConfigError(
                    f"Unsupported language: '{lang}'. "
                    f"Supported: {', '.join(SUPPORTED_LANGUAGES)}."
                )

        if "line_length" in data:
            ll = data["line_length"]
            if not isinstance(ll, int) or ll < 1:
                raise ConfigError(
                    f"'line_length' must be a positive integer, got {ll}."
                )

        if "indent_size" in data:
            indent = data["indent_size"]
            if not isinstance(indent, int) or indent < 1:
                raise ConfigError(
                    f"'indent_size' must be a positive integer, got {indent}."
                )

        if "indent_style" in data:
            style = data["indent_style"]
            if style not in ("space", "tab"):
                raise ConfigError(
                    f"'indent_style' must be 'space' or 'tab', got '{style}'."
                )

        if "style" in data:
            style = data["style"]
            if style not in STYLE_NAMES:
                raise ConfigError(
                    f"Unsupported style: '{style}'. "
                    f"Supported: {', '.join(STYLE_NAMES)}."
                )

        if "fix_mode" in data:
            mode = data["fix_mode"]
            valid_modes = [m.value for m in FixMode]
            if mode not in valid_modes:
                raise ConfigError(
                    f"'fix_mode' must be one of {valid_modes}, got '{mode}'."
                )

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value.

        Args:
            key: The configuration key.
            default: Default value if the key is not found.

        Returns:
            The configuration value or default.
        """
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value at runtime.

        Args:
            key: The configuration key to set.
            value: The value to assign.
        """
        self._validate({key: value})
        self._data[key] = value

    def as_dict(self) -> Dict[str, Any]:
        """Return a copy of the current configuration as a dictionary.

        Returns:
            Dictionary with all configuration values.
        """
        return dict(self._data)

    def save(self, path: Path, fmt: str = "json") -> None:
        """Save the current configuration to a file.

        Args:
            path: Destination file path.
            fmt: Format to use: 'json' or 'yaml'.

        Raises:
            ConfigError: If the format is unsupported or serialization fails.
        """
        parent = path.parent
        if not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)

        try:
            if fmt == "json":
                path.write_text(
                    json.dumps(self._data, indent=2, ensure_ascii=False),
                    encoding=DEFAULT_ENCODING,
                )
            elif fmt == "yaml":
                if yaml is None:
                    raise ConfigError(
                        "PyYAML is required to save YAML config files."
                    )
                path.write_text(
                    yaml.dump(self._data, default_flow_style=False),
                    encoding=DEFAULT_ENCODING,
                )
            else:
                raise ConfigError(f"Unsupported config format: '{fmt}'.")
        except OSError as e:
            raise ConfigError(f"Failed to save config: {e}", path=path) from e

    @property
    def loaded_path(self) -> Optional[Path]:
        """Return the path of the loaded config file, if any."""
        return self._loaded_path

    @property
    def language(self) -> str:
        """Return the configured target language."""
        return self._data.get("language", "python")

    @property
    def line_length(self) -> int:
        """Return the configured line length limit."""
        return self._data.get("line_length", DEFAULT_LINE_LENGTH)

    @property
    def indent_size(self) -> int:
        """Return the configured indent size."""
        return self._data.get("indent_size", DEFAULT_INDENT_SIZE)

    @property
    def fix_mode(self) -> FixMode:
        """Return the configured fix mode."""
        mode_str = self._data.get("fix_mode", "safe")
        try:
            return FixMode(mode_str)
        except ValueError:
            return FixMode.SAFE


# ---------------------------------------------------------------------------
# Style Checker
# ---------------------------------------------------------------------------


class StyleChecker:
    """Validates source code against configurable style guides.

    Supports PEP 8, Google Style, Mozilla Style, WebKit Style,
    and custom style definitions.
    """

    def __init__(
        self,
        config: FormatterConfig,
        rule_manager: Optional[RuleManager] = None,
    ) -> None:
        """Initialize the style checker.

        Args:
            config: Formatter configuration defining style and rules.
            rule_manager: Optional RuleManager for rule-based checking.
        """
        self._config = config
        self._rule_manager = rule_manager or RuleManager()
        self._style_name: str = config.get("style", "pep8")

    def check(
        self, source: str, language: str, file_path: Optional[Path] = None
    ) -> List[Violation]:
        """Run style checks on source code.

        Args:
            source: The source code string to check.
            language: The programming language of the source code.
            file_path: Optional file path for context in error messages.

        Returns:
            List of Violation instances found.
        """
        violations: List[Violation] = []

        # Run general checks
        violations.extend(self._check_line_length(source, language))
        violations.extend(self._check_trailing_whitespace(source))
        violations.extend(self._check_final_newline(source))
        violations.extend(self._check_indentation(source, language))

        # Run language-specific checks
        language_checker = self._get_language_checker(language)
        if language_checker:
            violations.extend(language_checker(source, file_path))

        # Run rule-based checks
        rules = self._rule_manager.get_rules_for_language(language)
        for rule in rules:
            if rule.pattern:
                try:
                    violations.extend(
                        self._check_rule_pattern(source, rule)
                    )
                except re.error:
                    continue

        return violations

    def _check_line_length(
        self, source: str, language: str
    ) -> List[Violation]:
        """Check for lines exceeding the maximum line length.

        Args:
            source: Source code to check.
            language: Language identifier (some languages may have exceptions).

        Returns:
            List of violations for overly long lines.
        """
        violations: List[Violation] = []
        max_length = self._config.line_length

        for i, line in enumerate(source.splitlines(), start=1):
            # Skip shebang lines and imports for some leniency
            stripped = line.rstrip()
            if len(stripped) > max_length:
                violations.append(
                    Violation(
                        lineno=i,
                        col_offset=max_length,
                        code="E501",
                        message=(
                            f"Line too long ({len(stripped)} > {max_length} "
                            f"characters)"
                        ),
                        severity=Severity.WARNING,
                        suggestion=stripped[:max_length] + "...",
                    )
                )

        return violations

    def _check_trailing_whitespace(self, source: str) -> List[Violation]:
        """Check for trailing whitespace on lines.

        Args:
            source: Source code to check.

        Returns:
            List of violations for trailing whitespace.
        """
        violations: List[Violation] = []
        pattern = re.compile(r"[ \t]+$")

        for i, line in enumerate(source.splitlines(), start=1):
            if pattern.search(line):
                violations.append(
                    Violation(
                        lineno=i,
                        col_offset=len(line.rstrip()),
                        code="W291",
                        message="Trailing whitespace",
                        severity=Severity.INFO,
                        suggestion=line.rstrip(),
                    )
                )

        return violations

    def _check_final_newline(self, source: str) -> List[Violation]:
        """Check that the file ends with a single newline.

        Args:
            source: Source code to check.

        Returns:
            List of violations if the file doesn't end correctly.
        """
        violations: List[Violation] = []

        if not source.endswith("\n"):
            violations.append(
                Violation(
                    lineno=len(source.splitlines()),
                    col_offset=0,
                    code="W292",
                    message="No newline at end of file",
                    severity=Severity.WARNING,
                    suggestion="\n",
                )
            )
        elif source.endswith("\n\n\n"):
            violations.append(
                Violation(
                    lineno=len(source.splitlines()),
                    col_offset=0,
                    code="W391",
                    message="Blank line at end of file",
                    severity=Severity.INFO,
                )
            )

        return violations

    def _check_indentation(
        self, source: str, language: str
    ) -> List[Violation]:
        """Check indentation consistency.

        Args:
            source: Source code to check.
            language: Language identifier.

        Returns:
            List of indentation violations.
        """
        violations: List[Violation] = []
        lines = source.splitlines()

        # Skip if no lines to check
        if not lines:
            return violations

        expected_indent = self._config.indent_size
        expected_char = " " if self._config.get("indent_style") == "space" else "\t"

        # Check inconsistent indentation style
        has_tabs = False
        has_spaces = False

        for i, line in enumerate(lines, start=1):
            if not line.strip():
                continue

            # Check if this single line has mixed tabs and spaces in leading whitespace
            leading = line[:len(line) - len(line.lstrip())]
            if "\t" in leading and " " in leading:
                violations.append(
                    Violation(
                        lineno=i,
                        col_offset=0,
                        code="E101",
                        message="Indentation contains mixed spaces and tabs",
                        severity=Severity.ERROR,
                    )
                )
                break

            if line.startswith("\t"):
                has_tabs = True
            elif line.startswith(" "):
                has_spaces = True

            if has_tabs and has_spaces:
                violations.append(
                    Violation(
                        lineno=i,
                        col_offset=0,
                        code="E101",
                        message="Indentation contains mixed spaces and tabs",
                        severity=Severity.ERROR,
                    )
                )
                break

        # Check indentation width for space-indented files
        if expected_char == " " and not has_tabs:
            for i, line in enumerate(lines, start=1):
                stripped = line.rstrip()
                if not stripped:
                    continue
                leading_spaces = len(line) - len(line.lstrip())
                if leading_spaces > 0 and leading_spaces % expected_indent != 0:
                    violations.append(
                        Violation(
                            lineno=i,
                            col_offset=0,
                            code="E111",
                            message=(
                                f"Indentation is not a multiple of "
                                f"{expected_indent} (found {leading_spaces})"
                            ),
                            severity=Severity.WARNING,
                        )
                    )

        return violations

    def _check_rule_pattern(
        self, source: str, rule: Rule
    ) -> List[Violation]:
        """Check a single rule's regex pattern against source code.

        Args:
            source: Source code to check.
            rule: The Rule to apply.

        Returns:
            List of violations matching the pattern.
        """
        violations: List[Violation] = []
        try:
            pattern = re.compile(rule.pattern, re.MULTILINE)
        except re.error:
            return violations

        for match in pattern.finditer(source):
            lineno = source[: match.start()].count("\n") + 1
            violations.append(
                Violation(
                    lineno=lineno,
                    col_offset=match.start() - source.rfind("\n", 0, match.start()) - 1,
                    code=rule.name.upper(),
                    message=rule.description or f"Violation of rule '{rule.name}'",
                    severity=rule.severity,
                    suggestion=match.group(0),
                )
            )

        return violations

    def _get_language_checker(
        self, language: str
    ) -> Optional[Callable[[str, Optional[Path]], List[Violation]]]:
        """Get the language-specific check function.

        Args:
            language: Language identifier.

        Returns:
            Callable if a language checker exists, None otherwise.
        """
        checkers: Dict[str, Callable[[str, Optional[Path]], List[Violation]]] = {
            "python": self._check_python_specific,
            "c": self._check_c_specific,
            "rust": self._check_rust_specific,
            "java": self._check_java_specific,
            "go": self._check_go_specific,
        }
        return checkers.get(language)

    def _check_python_specific(
        self, source: str, file_path: Optional[Path] = None
    ) -> List[Violation]:
        """Run Python-specific style checks.

        Args:
            source: Python source code.
            file_path: Optional file path.

        Returns:
            List of Python-specific violations.
        """
        violations: List[Violation] = []
        lines = source.splitlines()

        # Check for missing blank lines after class/function definitions
        for i, line in enumerate(lines):
            if re.match(r"^(class|def)\s", line):
                if i + 1 < len(lines) and lines[i + 1].strip():
                    if not lines[i + 1].startswith((" ", "\t", ")", "]")):
                        violations.append(
                            Violation(
                                lineno=i + 1,
                                col_offset=0,
                                code="E302",
                                message=(
                                    "Expected 2 blank lines before "
                                    f"{'class' if line.startswith('class') else 'function'} "
                                    f"definition, found 0"
                                ),
                                severity=Severity.WARNING,
                            )
                        )

        # Check for missing module docstring
        if not source.startswith(('"""', "'''", "#")) and not source.strip().startswith(('"""', "'''", "#")):
            # Only flag if there's a non-comment first line
            first_line = lines[0].strip() if lines else ""
            if first_line and not first_line.startswith("#"):
                violations.append(
                    Violation(
                        lineno=1,
                        col_offset=0,
                        code="D100",
                        message="Missing module docstring",
                        severity=Severity.INFO,
                    )
                )

        return violations

    def _check_c_specific(
        self, source: str, file_path: Optional[Path] = None
    ) -> List[Violation]:
        """Run C-specific style checks.

        Args:
            source: C source code.
            file_path: Optional file path.

        Returns:
            List of C-specific violations.
        """
        violations: List[Violation] = []
        lines = source.splitlines()

        # Check brace placement consistency
        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.endswith("{"):
                if i > 1:
                    prev = lines[i - 2].strip() if i >= 2 else ""
                    if prev and not prev.endswith(("{", "(", ",")):
                        pass  # Same-line brace is okay in some styles
            elif stripped == "}" and i < len(lines):
                next_line = lines[i].strip() if i < len(lines) else ""
                if next_line and next_line not in ("}", "else", "while", "catch"):
                    pass

        return violations

    def _check_rust_specific(
        self, source: str, file_path: Optional[Path] = None
    ) -> List[Violation]:
        """Run Rust-specific style checks.

        Args:
            source: Rust source code.
            file_path: Optional file path.

        Returns:
            List of Rust-specific violations.
        """
        violations: List[Violation] = []
        lines = source.splitlines()

        for i, line in enumerate(lines, start=1):
            stripped = line.strip()

            # Check for function naming (should be snake_case)
            fn_match = re.match(r"fn\s+([a-zA-Z_][a-zA-Z0-9_]*)", stripped)
            if fn_match:
                fn_name = fn_match.group(1)
                if fn_name != fn_name.lower() and not fn_name.startswith("__"):
                    violations.append(
                        Violation(
                            lineno=i,
                            col_offset=stripped.find(fn_name),
                            code="RUST-FN-CASE",
                            message=(
                                f"Function '{fn_name}' should be snake_case"
                            ),
                            severity=Severity.WARNING,
                            suggestion=fn_name.lower(),
                        )
                    )

            # Check for type naming (should be CamelCase)
            type_match = re.match(
                r"(struct|enum|trait|type)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
                stripped,
            )
            if type_match:
                type_name = type_match.group(2)
                if type_name[0].islower():
                    violations.append(
                        Violation(
                            lineno=i,
                            col_offset=stripped.find(type_name),
                            code="RUST-TYPE-CASE",
                            message=(
                                f"Type '{type_name}' should be CamelCase"
                            ),
                            severity=Severity.WARNING,
                            suggestion=type_name[0].upper() + type_name[1:],
                        )
                    )

        return violations

    def _check_java_specific(
        self, source: str, file_path: Optional[Path] = None
    ) -> List[Violation]:
        """Run Java-specific style checks.

        Args:
            source: Java source code.
            file_path: Optional file path.

        Returns:
            List of Java-specific violations.
        """
        violations: List[Violation] = []
        lines = source.splitlines()

        for i, line in enumerate(lines, start=1):
            stripped = line.strip()

            # Check for missing Javadoc on public classes
            if stripped.startswith("public class") or stripped.startswith("public interface"):
                # Look back for Javadoc
                if i >= 2:
                    prev = lines[i - 2].strip() if i >= 2 else ""
                    if not prev.startswith("/**"):
                        violations.append(
                            Violation(
                                lineno=i,
                                col_offset=0,
                                code="JAVA-JAVADOC",
                                message="Missing Javadoc for public class/interface",
                                severity=Severity.INFO,
                            )
                        )

        return violations

    def _check_go_specific(
        self, source: str, file_path: Optional[Path] = None
    ) -> List[Violation]:
        """Run Go-specific style checks.

        Args:
            source: Go source code.
            file_path: Optional file path.

        Returns:
            List of Go-specific violations.
        """
        violations: List[Violation] = []
        lines = source.splitlines()

        for i, line in enumerate(lines, start=1):
            stripped = line.strip()

            # Check for if err != nil { ... } patterns
            if re.match(r"if\s+\w+\s*!=\s*nil", stripped):
                pass  # Proper error handling

            # Check for unused imports (simple heuristic)
            if stripped.startswith("import "):
                violations.append(
                    Violation(
                        lineno=i,
                        col_offset=0,
                        code="GO-IMPORT",
                        message="Verify imports are used (gofmt/goimports recommended)",
                        severity=Severity.HINT,
                    )
                )

        return violations

    @property
    def style_name(self) -> str:
        """Return the name of the active style guide."""
        return self._style_name


# ---------------------------------------------------------------------------
# Auto Fixer
# ---------------------------------------------------------------------------


class AutoFixer:
    """Automatically fixes formatting and style issues in source code.

    Applies safe fixes by default, with an option to apply all
    available fixes.
    """

    def __init__(self, config: FormatterConfig) -> None:
        """Initialize the auto-fixer.

        Args:
            config: Formatter configuration for fix mode and options.
        """
        self._config = config
        self._fix_mode: FixMode = config.fix_mode
        self._fix_count: int = 0

    def fix(self, source: str, language: str) -> str:
        """Apply all applicable fixes to the source code.

        Args:
            source: The source code to fix.
            language: The programming language of the source.

        Returns:
            The fixed source code as a string.
        """
        result = source
        result = self._fix_trailing_whitespace(result)
        result = self._fix_final_newline(result)
        result = self._fix_indentation(result, language)

        if self._fix_mode == FixMode.ALL:
            result = self._fix_line_length(result, language)

        return result

    def _fix_trailing_whitespace(self, source: str) -> str:
        """Remove trailing whitespace from all lines.

        Args:
            source: Source code to fix.

        Returns:
            Source with trailing whitespace removed.
        """
        fixed = "\n".join(line.rstrip() for line in source.splitlines())
        if fixed != source:
            self._fix_count += 1
        return fixed

    def _fix_final_newline(self, source: str) -> str:
        """Ensure the file ends with exactly one newline.

        Args:
            source: Source code to fix.

        Returns:
            Source with proper final newline.
        """
        if not source.endswith("\n"):
            self._fix_count += 1
            return source + "\n"

        # Remove extra trailing newlines
        stripped = source.rstrip("\n")
        if stripped + "\n" != source:
            self._fix_count += 1
            return stripped + "\n"

        return source

    def _fix_indentation(self, source: str, language: str) -> str:
        """Normalize indentation to the configured style.

        Args:
            source: Source code to fix.
            language: Language identifier (unused here but kept for extensibility).

        Returns:
            Source with normalized indentation.
        """
        indent_style = self._config.get("indent_style", "space")
        indent_size = self._config.indent_size

        if indent_style == "tab":
            target_indent = "\t"
        else:
            target_indent = " " * indent_size

        lines = source.splitlines(keepends=True)
        fixed_lines: List[str] = []

        changed = False
        for line in lines:
            if not line.strip():
                fixed_lines.append(line)
                continue

            leading = line[: len(line) - len(line.lstrip())]
            content = line[len(leading):]

            # Normalize leading whitespace
            if "\t" in leading and indent_style == "space":
                # Convert tabs to spaces
                fixed_leading = leading.replace("\t", " " * indent_size)
                if fixed_leading != leading:
                    changed = True
                fixed_lines.append(fixed_leading + content)
            elif indent_style == "tab" and " " in leading:
                # Try to convert spaces to tabs (approximate)
                space_count = len(leading)
                tab_count = space_count // indent_size
                remainder = space_count % indent_size
                fixed_leading = "\t" * tab_count + " " * remainder
                if fixed_leading != leading:
                    changed = True
                fixed_lines.append(fixed_leading + content)
            else:
                fixed_lines.append(line)

        if changed:
            self._fix_count += 1

        return "".join(fixed_lines)

    def _fix_line_length(self, source: str, language: str) -> str:
        """Attempt to fix lines that exceed the maximum line length.

        This is a best-effort fix that handles simple cases like
        long strings, comments, and import lines.

        Args:
            source: Source code to fix.
            language: Language identifier for language-specific strategies.

        Returns:
            Source with some long lines wrapped.
        """
        max_length = self._config.line_length
        lines = source.splitlines(keepends=True)
        fixed_lines: List[str] = []
        changed = False

        for line in lines:
            stripped = line.rstrip("\n")
            if len(stripped) <= max_length or not stripped.strip():
                fixed_lines.append(line)
                continue

            # Try to split long lines (simple heuristic)
            if language == "python" and stripped.strip().startswith("#"):
                # Wrap long comments
                wrapped = textwrap.fill(
                    stripped.strip("# "),
                    width=max_length - 2,
                    initial_indent="# ",
                    subsequent_indent="# ",
                )
                fixed_lines.append(wrapped + "\n")
                changed = True
            elif "," in stripped:
                # Try to split at commas for function args / lists
                indent = " " * (len(stripped) - len(stripped.lstrip()) + 4)
                parts = stripped.split(",")
                new_line = parts[0]
                for part in parts[1:]:
                    if len(new_line) + len(part) + 1 > max_length:
                        fixed_lines.append(new_line.strip() + ",\n")
                        new_line = indent + part.strip()
                        changed = True
                    else:
                        new_line += "," + part
                if new_line.strip():
                    fixed_lines.append(new_line.strip() + "\n")
                    changed = True
                else:
                    fixed_lines.append(line)
            else:
                fixed_lines.append(line)

        if changed:
            self._fix_count += 1

        return "".join(fixed_lines)

    @property
    def fix_count(self) -> int:
        """Return the number of fixes applied."""
        return self._fix_count

    def reset_count(self) -> None:
        """Reset the fix counter."""
        self._fix_count = 0


# ---------------------------------------------------------------------------
# External Formatter Integration
# ---------------------------------------------------------------------------


class ExternalFormatter:
    """Integrates with external code formatting tools like Black,
    clang-format, rustfmt, google-java-format, and gofmt."""

    def __init__(self, config: FormatterConfig) -> None:
        """Initialize the external formatter wrapper.

        Args:
            config: Formatter configuration for tool options.
        """
        self._config = config
        self._tool_map: Dict[str, str] = dict(EXTERNAL_FORMATTERS)

    def format(self, source: str, language: str, file_path: Path) -> str:
        """Format source code using the appropriate external tool.

        Args:
            source: Source code to format.
            language: Target programming language.
            file_path: Path to the file (used for temp file creation).

        Returns:
            Formatted source code.

        Raises:
            ExternalToolError: If the tool is not found or fails.
            FormatError: If the language has no registered external tool.
        """
        if language not in self._tool_map:
            raise FormatError(
                f"No external formatter registered for '{language}'.",
                language=language,
            )

        tool_name = self._tool_map[language]
        tool_path = shutil.which(tool_name)

        if tool_path is None:
            raise ExternalToolError(
                f"External formatter '{tool_name}' not found in PATH. "
                f"Please install it.",
                tool_name=tool_name,
            )

        # Write source to temp file and run the tool
        suffix = self._get_suffix(language)
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=suffix,
            delete=False,
            encoding=DEFAULT_ENCODING,
        ) as tmp:
            tmp.write(source)
            tmp_path = tmp.name

        try:
            cmd = self._build_command(tool_path, language, Path(tmp_path))
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                raise ExternalToolError(
                    f"External formatter '{tool_name}' failed with "
                    f"exit code {result.returncode}.",
                    tool_name=tool_name,
                    return_code=result.returncode,
                    stderr=result.stderr,
                )

            formatted = Path(tmp_path).read_text(encoding=DEFAULT_ENCODING)
            return formatted

        except subprocess.TimeoutExpired as e:
            raise ExternalToolError(
                f"External formatter '{tool_name}' timed out.",
                tool_name=tool_name,
            ) from e

        except OSError as e:
            raise ExternalToolError(
                f"Failed to run '{tool_name}': {e}",
                tool_name=tool_name,
            ) from e

        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _build_command(
        self, tool_path: str, language: str, file_path: Path
    ) -> List[str]:
        """Build the command-line invocation for the external tool.

        Args:
            tool_path: Full path to the tool executable.
            language: Target language.
            file_path: Path to the file to format.

        Returns:
            List of command arguments.
        """
        options = self._config.get("formatter_options", {})

        if language == "python":
            cmd = [
                tool_path,
                "--quiet",
                f"--line-length={self._config.line_length}",
                file_path,
            ]
            if options.get("black", {}).get("skip_string_normalization"):
                cmd.append("--skip-string-normalization")

        elif language == "c":
            style = options.get("clang-format", {}).get("style", "file")
            cmd = [tool_path, f"--style={style}", "-i", file_path]

        elif language == "rust":
            cmd = [tool_path, file_path]

        elif language == "java":
            length_arg = str(self._config.line_length)
            if "aosp" in options.get("java", {}).get("style", ""):
                cmd = [tool_path, "--aosp", f"--length={length_arg}", file_path]
            else:
                cmd = [tool_path, f"--length={length_arg}", file_path]

        elif language == "go":
            cmd = [tool_path, file_path]

        else:
            cmd = [tool_path, file_path]

        return cmd

    @staticmethod
    def _get_suffix(language: str) -> str:
        """Get the file suffix for the given language.

        Args:
            language: Language identifier.

        Returns:
            File extension including the dot.
        """
        suffixes: Dict[str, str] = {
            "python": ".py",
            "c": ".c",
            "rust": ".rs",
            "java": ".java",
            "go": ".go",
        }
        return suffixes.get(language, ".txt")

    @staticmethod
    def is_tool_available(language: str) -> bool:
        """Check if the external formatter for a language is available.

        Args:
            language: Language identifier.

        Returns:
            True if the tool is installed and in PATH.
        """
        tool = EXTERNAL_FORMATTERS.get(language, "")
        if not tool:
            return False
        return shutil.which(tool) is not None


# ---------------------------------------------------------------------------
# Base Code Formatter
# ---------------------------------------------------------------------------


class CodeFormatter(ABC):
    """Abstract base class for language-specific code formatters.

    Provides the common formatting pipeline: check style, apply fixes,
    integrate with external formatters, and produce diff output.
    """

    def __init__(self, config: FormatterConfig) -> None:
        """Initialize the base code formatter.

        Args:
            config: Formatter configuration instance.
        """
        self._config = config
        self._rule_manager = RuleManager()
        self._rule_manager.register_builtin_rules()
        self._style_checker = StyleChecker(config, self._rule_manager)
        self._auto_fixer = AutoFixer(config)
        self._diff_output = DiffOutput()
        self._external_formatter = ExternalFormatter(config)

        self._language: str = ""

    @property
    @abstractmethod
    def language(self) -> str:
        """Return the language identifier for this formatter."""
        ...

    @abstractmethod
    def format_code(self, source: str) -> str:
        """Apply language-specific formatting to the source code.

        Subclasses should override this method to implement
        language-specific formatting rules.

        Args:
            source: The source code to format.

        Returns:
            The formatted source code.
        """
        ...

    def format_file(self, file_path: Path) -> FormatResult:
        """Format a single file.

        This is the main entry point for formatting a file. It runs
        the full pipeline: load, check, format, fix, and optionally
        run external formatters.

        Args:
            file_path: Path to the file to format.

        Returns:
            FormatResult with the outcome of the operation.
        """
        start = datetime.now()
        result = FormatResult(path=file_path)

        try:
            source = file_path.read_text(encoding=DEFAULT_ENCODING)
        except OSError as e:
            result.success = False
            result.errors.append(str(e))
            return result

        # Step 1: Run external formatter if configured and available
        formatted = source
        if self._config.get("external_formatter", True):
            try:
                if ExternalFormatter.is_tool_available(self.language):
                    formatted = self._external_formatter.format(
                        source, self.language, file_path
                    )
            except (ExternalToolError, FormatError) as e:
                result.errors.append(str(e))

        # Step 2: Apply language-specific formatting
        try:
            formatted = self.format_code(formatted)
        except (ParseError, FormatError) as e:
            result.success = False
            result.errors.append(str(e))
            return result

        # Step 3: Check style violations
        violations = self._style_checker.check(
            formatted, self.language, file_path
        )
        result.violations = violations

        # Step 4: Auto-fix if mode is not NONE
        if self._config.fix_mode != FixMode.NONE:
            try:
                formatted = self._auto_fixer.fix(formatted, self.language)
            except Exception as e:
                result.errors.append(f"Auto-fix error: {e}")

        # Step 5: Generate diff if changes occurred
        if self._diff_output.has_changes(source, formatted):
            result.changed = True
            result.diff = self._diff_output.generate(
                source, formatted, file_path
            )

        # Step 6: Write back if changed and not check-only
        if result.changed and not self._config.get("check_only", False):
            try:
                file_path.write_text(formatted, encoding=DEFAULT_ENCODING)
            except OSError as e:
                result.success = False
                result.errors.append(str(e))
                return result

        elapsed = datetime.now() - start
        result.elapsed_ms = elapsed.total_seconds() * 1000
        return result

    def format_string(self, source: str, file_path: Optional[Path] = None) -> FormatResult:
        """Format a source code string.

        Args:
            source: The source code string to format.
            file_path: Optional file path for context.

        Returns:
            FormatResult with the outcome of the operation.
        """
        path = file_path or Path("string_input")
        start = datetime.now()
        result = FormatResult(path=path)

        formatted = source

        # Run external formatter
        if self._config.get("external_formatter", True):
            try:
                if ExternalFormatter.is_tool_available(self.language):
                    formatted = self._external_formatter.format(
                        source, self.language, path
                    )
            except (ExternalToolError, FormatError) as e:
                result.errors.append(str(e))

        # Language-specific formatting
        try:
            formatted = self.format_code(formatted)
        except (ParseError, FormatError) as e:
            result.success = False
            result.errors.append(str(e))
            return result

        # Style checking
        result.violations = self._style_checker.check(
            formatted, self.language, path
        )

        # Auto-fix
        if self._config.fix_mode != FixMode.NONE:
            try:
                formatted = self._auto_fixer.fix(formatted, self.language)
            except Exception as e:
                result.errors.append(f"Auto-fix error: {e}")

        if self._diff_output.has_changes(source, formatted):
            result.changed = True
            result.diff = self._diff_output.generate(
                source, formatted, path
            )

        result.success = True
        elapsed = datetime.now() - start
        result.elapsed_ms = elapsed.total_seconds() * 1000
        return result

    def check_style(self, source: str) -> List[Violation]:
        """Run style checking on the source code.

        Args:
            source: Source code to check.

        Returns:
            List of style violations found.
        """
        return self._style_checker.check(source, self.language)

    def get_rule_manager(self) -> RuleManager:
        """Return the rule manager instance.

        Returns:
            The RuleManager associated with this formatter.
        """
        return self._rule_manager

    def get_config(self) -> FormatterConfig:
        """Return the formatter configuration.

        Returns:
            The FormatterConfig instance.
        """
        return self._config


# ---------------------------------------------------------------------------
# Language-Specific Formatters
# ---------------------------------------------------------------------------


class PythonFormatter(CodeFormatter):
    """Formatter for Python source code.

    Applies PEP 8 conventions, manages import ordering,
    blank lines, and docstring formatting.
    """

    @property
    def language(self) -> str:
        """Return 'python' as the language identifier."""
        return "python"

    def format_code(self, source: str) -> str:
        """Apply Python-specific formatting rules.

        - Normalizes blank lines around classes and functions
        - Ensures consistent import ordering
        - Removes多余的 blank lines inside functions

        Args:
            source: Python source code to format.

        Returns:
            Formatted Python source code.
        """
        lines = source.splitlines(keepends=True)
        result: List[str] = []
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.rstrip("\n")

            # Ensure 2 blank lines before top-level class/def
            if re.match(r"^(class|def)\s", stripped):
                # Count preceding blank lines
                blank_count = 0
                j = len(result) - 1
                while j >= 0 and result[j].strip() == "":
                    blank_count += 1
                    j -= 1

                if blank_count < 2 and len(result) > 0:
                    # Add missing blank lines
                    needed = 2 - blank_count
                    # Remove trailing blank lines then add proper amount
                    while result and result[-1].strip() == "":
                        result.pop()
                    for _ in range(2):
                        result.append("\n")

            # Ensure 1 blank line before inner class/def (inside another class)
            if re.match(r"^\s+(class|def)\s", stripped):
                blank_count = 0
                j = len(result) - 1
                while j >= 0 and result[j].strip() == "":
                    blank_count += 1
                    j -= 1

                if blank_count < 1 and len(result) > 0:
                    while result and result[-1].strip() == "":
                        result.pop()
                    result.append("\n")

            result.append(line)
            i += 1

        # Remove excessive blank lines at end
        while result and result[-1].strip() == "":
            result.pop()
        result.append("\n")

        return "".join(result)

    def format_file(self, file_path: Path) -> FormatResult:
        """Format a Python file, with special handling for imports.

        Args:
            file_path: Path to the Python file.

        Returns:
            FormatResult with formatting outcome.
        """
        return super().format_file(file_path)


class CFormatter(CodeFormatter):
    """Formatter for C source code.

    Manages brace placement, pointer notation, and
    comment formatting.
    """

    @property
    def language(self) -> str:
        """Return 'c' as the language identifier."""
        return "c"

    def format_code(self, source: str) -> str:
        """Apply C-specific formatting rules.

        - Normalizes brace placement
        - Ensures consistent indentation
        - Manages whitespace around operators

        Args:
            source: C source code to format.

        Returns:
            Formatted C source code.
        """
        lines = source.splitlines(keepends=True)
        result: List[str] = []
        indent_level = 0
        indent_str = " " * self._config.indent_size

        for line in lines:
            stripped = line.rstrip()
            if not stripped:
                result.append(line)
                continue

            # Decrease indent for closing braces
            if stripped.startswith("}") or stripped.startswith("})"):
                indent_level = max(0, indent_level - 1)

            # Apply indentation
            leading = line[: len(line) - len(line.lstrip())]
            if not leading.startswith("\t"):
                result.append(indent_str * indent_level + stripped + "\n")
            else:
                result.append(line)

            # Increase indent after opening braces
            if stripped.endswith("{") or stripped.endswith("("):
                indent_level += 1

        return "".join(result)


class RustFormatter(CodeFormatter):
    """Formatter for Rust source code.

    Follows Rust standard style conventions and
    works with rustfmt for external formatting.
    """

    @property
    def language(self) -> str:
        """Return 'rust' as the language identifier."""
        return "rust"

    def format_code(self, source: str) -> str:
        """Apply Rust-specific formatting rules.

        - Manages module declarations
        - Ensures consistent trailing semicolons
        - Normalizes whitespace around generics

        Args:
            source: Rust source code to format.

        Returns:
            Formatted Rust source code.
        """
        lines = source.splitlines(keepends=True)
        result: List[str] = []

        for line in lines:
            stripped = line.rstrip()
            if not stripped:
                result.append(line)
                continue

            # Ensure space after "fn", "if", "while", "for", "match"
            modified = re.sub(
                r"\b(fn|if|while|for|match|unsafe|impl|trait|enum|struct)\b(?!\s)",
                r"\1 ",
                stripped,
            )

            # Normalize whitespace around -> for return types
            modified = re.sub(r"\s*->\s*", " -> ", modified)

            # Ensure closing braces are on their own line for functions
            if modified.strip() == "}" and result:
                result.append(modified + "\n")
            else:
                result.append(modified + "\n")

        return "".join(result)


class JavaFormatter(CodeFormatter):
    """Formatter for Java source code.

    Follows Google Java Style conventions and
    works with google-java-format.
    """

    @property
    def language(self) -> str:
        """Return 'java' as the language identifier."""
        return "java"

    def format_code(self, source: str) -> str:
        """Apply Java-specific formatting rules.

        - Manages class and method brace placement
        - Normalizes annotation formatting
        - Ensures consistent import grouping

        Args:
            source: Java source code to format.

        Returns:
            Formatted Java source code.
        """
        lines = source.splitlines(keepends=True)
        result: List[str] = []
        indent_level = 0
        indent_str = " " * self._config.indent_size

        for line in lines:
            stripped = line.rstrip()
            if not stripped:
                result.append(line)
                continue

            # Count braces for indentation
            open_braces = stripped.count("{")
            close_braces = stripped.count("}")

            # Decrease indent for lines starting with closing brace
            if stripped.lstrip().startswith("}"):
                indent_level = max(0, indent_level - 1)

            # Apply indentation (if not already indented with tabs)
            leading = line[: len(line) - len(line.lstrip())]
            if not leading.startswith("\t"):
                result.append(indent_str * indent_level + stripped + "\n")
            else:
                result.append(line)

            # Increase indent after opening braces
            net = open_braces - close_braces
            if net > 0 and stripped.endswith("{"):
                indent_level += net

        return "".join(result)


class GoFormatter(CodeFormatter):
    """Formatter for Go source code.

    Follows Go standard formatting conventions and
    works with gofmt for external formatting.
    """

    @property
    def language(self) -> str:
        """Return 'go' as the language identifier."""
        return "go"

    def format_code(self, source: str) -> str:
        """Apply Go-specific formatting rules.

        - Uses tabs for indentation (Go standard)
        - Manages struct and interface formatting
        - Ensures consistent error handling patterns

        Args:
            source: Go source code to format.

        Returns:
            Formatted Go source code.
        """
        lines = source.splitlines(keepends=True)
        result: List[str] = []
        indent_level = 0

        for line in lines:
            stripped = line.rstrip()
            if not stripped:
                result.append(line)
                continue

            # Go uses tabs
            indent = "\t" * indent_level

            # Decrease indent for closing braces
            if stripped.startswith("}"):
                indent_level = max(0, indent_level - 1)
                indent = "\t" * indent_level

            result.append(indent + stripped + "\n")

            # Increase indent after opening braces
            if stripped.endswith("{") or stripped.endswith("("):
                indent_level += 1

            # Handle else/else if on same line
            if stripped.endswith("}") and any(
                kw in stripped for kw in ("else", "for", "switch", "select")
            ):
                pass  # Stay at same level

        return "".join(result)


# ---------------------------------------------------------------------------
# Formatter Factory
# ---------------------------------------------------------------------------


class FormatterFactory:
    """Factory for creating language-specific formatter instances."""

    _formatter_registry: Dict[str, type] = {
        "python": PythonFormatter,
        "c": CFormatter,
        "rust": RustFormatter,
        "java": JavaFormatter,
        "go": GoFormatter,
    }

    @classmethod
    def create_formatter(
        cls, language: str, config: Optional[FormatterConfig] = None
    ) -> CodeFormatter:
        """Create a formatter for the given language.

        Args:
            language: Target language identifier (e.g., 'python', 'c').
            config: Optional configuration. If None, a default config is used.

        Returns:
            An instance of the appropriate CodeFormatter subclass.

        Raises:
            ValueError: If the language is not supported.
        """
        if config is None:
            config = FormatterConfig()
            config.set("language", language)

        formatter_class = cls._formatter_registry.get(language)
        if formatter_class is None:
            raise ValueError(
                f"Unsupported language: '{language}'. "
                f"Supported: {', '.join(cls._formatter_registry.keys())}."
            )

        return formatter_class(config)

    @classmethod
    def register_formatter(
        cls, language: str, formatter_class: type
    ) -> None:
        """Register a custom formatter class for a language.

        Args:
            language: Language identifier.
            formatter_class: A subclass of CodeFormatter.

        Raises:
            TypeError: If formatter_class is not a subclass of CodeFormatter.
        """
        if not issubclass(formatter_class, CodeFormatter):
            raise TypeError(
                f"'{formatter_class.__name__}' must be a subclass of "
                "CodeFormatter."
            )
        cls._formatter_registry[language] = formatter_class

    @classmethod
    def supported_languages(cls) -> List[str]:
        """Return the list of supported languages.

        Returns:
            Sorted list of language identifiers.
        """
        return sorted(cls._formatter_registry.keys())

    @classmethod
    def detect_language(cls, file_path: Path) -> str:
        """Detect the programming language from a file extension.

        Args:
            file_path: Path to the file to detect language for.

        Returns:
            Language identifier string.

        Raises:
            ValueError: If the file extension is not recognized.
        """
        ext_to_lang: Dict[str, str] = {
            ".py": "python",
            ".pyw": "python",
            ".c": "c",
            ".h": "c",
            ".rs": "rust",
            ".java": "java",
            ".go": "go",
        }

        ext = file_path.suffix.lower()
        lang = ext_to_lang.get(ext)

        if lang is None:
            raise ValueError(
                f"Unrecognized file extension '{ext}' for file "
                f"'{file_path.name}'. Supported extensions: "
                f"{', '.join(ext_to_lang.keys())}."
            )

        return lang


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog=PROJECT_NAME,
        description="AI-Powered Code Formatting Tool",
        epilog=(
            "Examples:\n"
            "  %(prog)s file.py\n"
            "  %(prog)s --check file.py\n"
            "  %(prog)s --diff --language python file.py\n"
            "  %(prog)s --config .ai-formatter.yml src/\n"
            "  %(prog)s --list-rules --verbose\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Version
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    # Positional arguments
    parser.add_argument(
        "files",
        metavar="FILE",
        nargs="*",
        type=str,
        help="File(s) or directory(s) to format",
    )

    # Language selection
    parser.add_argument(
        "-l",
        "--language",
        type=str,
        choices=SUPPORTED_LANGUAGES,
        help="Target programming language (default: auto-detect from extension)",
    )

    # Config
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        metavar="PATH",
        help="Path to configuration file",
    )

    # Mode flags
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check style without modifying files (exit 1 if violations found)",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="Show diff of changes without modifying files",
    )
    parser.add_argument(
        "--fix",
        type=str,
        choices=[m.value for m in FixMode],
        default=None,
        help="Auto-fix mode: 'none', 'safe', or 'all' (default: from config)",
    )

    # Output control
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress non-error output",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v, -vv)",
    )

    # Style
    parser.add_argument(
        "--style",
        type=str,
        choices=STYLE_NAMES,
        help="Style guide to follow (default: from config)",
    )
    parser.add_argument(
        "--line-length",
        type=int,
        help="Maximum line length (default: 88)",
    )

    # Rule management
    parser.add_argument(
        "--list-rules",
        action="store_true",
        help="List all registered rules",
    )
    parser.add_argument(
        "--list-rules-verbose",
        action="store_true",
        help="List all rules with full details",
    )

    # External formatter
    parser.add_argument(
        "--no-external",
        action="store_true",
        help="Skip external formatters (black, clang-format, etc.)",
    )

    # Init config
    parser.add_argument(
        "--init",
        type=str,
        nargs="?",
        const=".ai-formatter.json",
        metavar="PATH",
        help="Generate a default config file (default: .ai-formatter.json)",
    )

    return parser


def _find_files(
    paths: List[str],
    config: FormatterConfig,
    language: str,
) -> List[Path]:
    """Find all matching files from the given paths.

    Args:
        paths: List of file or directory paths.
        config: Configuration for include/exclude patterns.
        language: Target language to filter by extension.

    Returns:
        Sorted list of unique file paths.
    """
    ext_map: Dict[str, str] = {
        "python": (".py", ".pyw"),
        "c": (".c", ".h"),
        "rust": (".rs",),
        "java": (".java",),
        "go": (".go",),
    }

    extensions = ext_map.get(language, ())
    include_patterns = config.get("include", [])
    exclude_patterns = config.get("exclude", [])
    files: List[Path] = []

    for p in paths:
        path = Path(p)
        if path.is_file():
            if path.suffix in extensions:
                files.append(path)
        elif path.is_dir():
            for ext in extensions:
                files.extend(path.rglob(f"*{ext}"))

    # Deduplicate and sort
    unique = sorted(set(files))

    # Apply exclude patterns
    if exclude_patterns:
        filtered: List[Path] = []
        for f in unique:
            excluded = False
            for pat in exclude_patterns:
                if f.match(pat) or pat in str(f):
                    excluded = True
                    break
            if not excluded:
                filtered.append(f)
        unique = filtered

    return unique


def _format_files(
    formatter: CodeFormatter,
    files: List[Path],
    config: FormatterConfig,
    args: argparse.Namespace,
) -> int:
    """Format or check a list of files.

    Args:
        formatter: CodeFormatter instance.
        files: List of file paths to process.
        config: Formatter configuration.
        args: Parsed command-line arguments.

    Returns:
        Exit code: 0 for success, 1 if any violations found.
    """
    check_only = args.check or config.get("check_only", False)
    show_diff = args.diff or config.get("diff", False)
    total_violations = 0
    changed_files = 0
    error_files = 0

    if check_only:
        # Check mode: report violations without modifying
        for file_path in files:
            source = file_path.read_text(encoding=DEFAULT_ENCODING)
            violations = formatter.check_style(source)
            if violations:
                total_violations += len(violations)
                if not args.quiet:
                    print(f"\n{file_path}:")
                    for v in violations:
                        severity_tag = v.severity.name.lower()
                        print(
                            f"  {file_path}:{v.lineno}:{v.col_offset}: "
                            f"{severity_tag}: {v.code} {v.message}"
                        )
        if total_violations > 0:
            print(
                f"\nFound {total_violations} style violation(s) in "
                f"{len(files)} file(s)."
            )
            return 1
        return 0

    # Format mode
    for file_path in files:
        try:
            result = formatter.format_file(file_path)
        except Exception as e:
            if not args.quiet:
                print(f"Error formatting {file_path}: {e}", file=sys.stderr)
            error_files += 1
            continue

        if result.errors:
            if not args.quiet:
                for err in result.errors:
                    print(
                        f"Warning: {file_path}: {err}",
                        file=sys.stderr,
                    )

        if result.changed:
            changed_files += 1
            if not args.quiet:
                print(f"Formatted {file_path}")

        if result.violations:
            total_violations += len(result.violations)
            if not args.quiet and args.verbose:
                print(f"  {len(result.violations)} violation(s) remaining")

        if show_diff and result.diff:
            if not args.quiet:
                print(DiffOutput.colorize_diff(result.diff))

    # Summary
    if not args.quiet:
        summary = (
            f"Processed {len(files)} file(s): "
            f"{changed_files} formatted, "
            f"{len(files) - changed_files - error_files} unchanged, "
            f"{error_files} error(s)"
        )
        if total_violations:
            summary += f", {total_violations} violation(s) remaining"
        print(f"\n{summary}")

    return 1 if total_violations > 0 else 0


def _init_config(path: str) -> int:
    """Generate a default configuration file.

    Args:
        path: Path to write the config file (JSON or YAML).

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    config = FormatterConfig()
    config_path = Path(path)

    if config_path.suffix in (".yml", ".yaml"):
        fmt = "yaml"
    else:
        fmt = "json"

    try:
        config.save(config_path, fmt=fmt)
        print(f"Generated default config: {config_path}")
        return 0
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Main entry point for the AI formatter CLI.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code: 0 for success, non-zero for errors.
    """
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # --init: generate config file and exit
    if args.init:
        return _init_config(args.init)

    # Load configuration
    config = FormatterConfig()
    if args.config:
        try:
            config.load(Path(args.config))
        except ConfigError as e:
            print(f"Config error: {e}", file=sys.stderr)
            return 2
    else:
        config.load()

    # Apply CLI overrides
    if args.language:
        config.set("language", args.language)
    if args.style:
        config.set("style", args.style)
    if args.line_length is not None:
        config.set("line_length", args.line_length)
    if args.fix is not None:
        config.set("fix_mode", args.fix)
    if args.check:
        config.set("check_only", True)
    if args.diff:
        config.set("diff", True)
    if args.quiet:
        config.set("quiet", True)
    if args.verbose:
        config.set("verbose", True)
    if args.no_external:
        config.set("external_formatter", False)

    language = config.language

    # Create formatter
    try:
        formatter = FormatterFactory.create_formatter(language, config)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    # --list-rules: list rules and exit
    if args.list_rules or args.list_rules_verbose:
        rule_manager = formatter.get_rule_manager()
        lines = rule_manager.list_rules(
            language=language if args.list_rules_verbose else None,
            verbose=args.list_rules_verbose,
        )
        for line in lines:
            print(line)
        return 0

    # If no files specified, read from stdin or show help
    if not args.files:
        # Try to read from stdin if not a TTY
        if not sys.stdin.isatty():
            source = sys.stdin.read()
            result = formatter.format_string(source)
            if result.diff:
                print(DiffOutput.colorize_diff(result.diff))
            if not result.success:
                return 1
            return 0
        parser.print_help()
        return 0

    # Find and format files
    try:
        files = _find_files(args.files, config, language)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    if not files:
        if not args.quiet:
            print(f"No {language} files found.")
        return 0

    return _format_files(formatter, files, config, args)


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(main())