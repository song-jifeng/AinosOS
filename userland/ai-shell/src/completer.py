"""
Tab completion for Ainos Shell.

Provides intelligent tab completion including:
- Command completion (builtins, external executables, aliases)
- File path completion (with glob support)
- Environment variable completion ($VAR)
- History-based completion
- AI-powered completion suggestions
- Plugin-based completion
- Argument completion for known commands
- Fuzzy matching for partial input
- Case-insensitive matching option
- Description display for completions
"""

from __future__ import annotations

import os
import re
import typing as t
from dataclasses import dataclass, field
from pathlib import Path

from .utils import (
    IS_WINDOWS,
    IS_POSIX,
    find_executable,
    expanduser,
    get_env,
    get_paths_from_env,
    terminal_width,
    list_files,
    truncate,
    AnsiCode,
    colorize,
)

# ---------------------------------------------------------------------------
# Completion result
# ---------------------------------------------------------------------------


@dataclass
class Completion:
    """A single completion suggestion."""
    text: str
    display: str = ""
    description: str = ""
    type: str = "file"  # file, dir, command, variable, alias, history, ai
    score: float = 1.0

    def __post_init__(self) -> None:
        if not self.display:
            self.display = self.text

    def __repr__(self) -> str:
        return f"Completion({self.text!r}, type={self.type})"


@dataclass
class CompletionResult:
    """Result of a completion operation."""
    completions: t.List[Completion] = field(default_factory=list)
    prefix: str = ""
    replacement_start: int = 0
    replacement_end: int = 0
    is_partial: bool = False

    @property
    def has_completions(self) -> bool:
        return len(self.completions) > 0

    @property
    def single_completion(self) -> t.Optional[Completion]:
        if len(self.completions) == 1:
            return self.completions[0]
        return None

    @property
    def common_prefix(self) -> str:
        """Find the common prefix of all completions."""
        if not self.completions:
            return ""
        if len(self.completions) == 1:
            return self.completions[0].text

        texts = [c.text for c in self.completions]
        prefix = texts[0]
        for text in texts[1:]:
            while not text.startswith(prefix):
                prefix = prefix[:-1]
                if not prefix:
                    return ""
        return prefix

    def display(self, max_suggestions: int = 20) -> str:
        """Format completions for display."""
        if not self.completions:
            return ""

        shown = self.completions[:max_suggestions]
        remaining = len(self.completions) - max_suggestions

        # Group by type for colored display
        lines: t.List[str] = []
        for comp in shown:
            display_text = comp.display
            if comp.description:
                display_text = f"{display_text:<30} {comp.description}"
            lines.append(display_text)

        if remaining > 0:
            lines.append(f"... and {remaining} more")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Completion sources
# ---------------------------------------------------------------------------

class CommandCompleter:
    """Completes command names (builtins, aliases, external executables)."""

    def __init__(self) -> None:
        self._cache: t.Dict[str, t.List[str]] = {}
        self._cache_time: t.Dict[str, float] = {}
        self._max_cache_age = 30.0  # seconds

    def get_completions(self, prefix: str, fuzzy: bool = False,
                        case_insensitive: bool = False) -> t.List[str]:
        """Get command completions matching the prefix."""
        commands: t.List[str] = []

        # Built-in commands
        from .builtins import BUILTINS
        for name in BUILTINS.keys():
            if self._matches(name, prefix, fuzzy, case_insensitive):
                commands.append(name)

        # Aliases
        from .config import get_aliases
        for name in get_aliases().keys():
            if self._matches(name, prefix, fuzzy, case_insensitive):
                commands.append(name)

        # External executables from PATH
        for path_dir in get_paths_from_env():
            if not os.path.isdir(path_dir):
                continue

            # Check cache
            if path_dir in self._cache:
                import time
                if time.time() - self._cache_time.get(path_dir, 0) < self._max_cache_age:
                    for cmd in self._cache[path_dir]:
                        if self._matches(cmd, prefix, fuzzy, case_insensitive):
                            commands.append(cmd)
                    continue

            # List directory
            try:
                entries = os.listdir(path_dir)
                cached = []
                for entry in entries:
                    full = os.path.join(path_dir, entry)
                    if os.path.isfile(full) and os.access(full, os.X_OK):
                        cached.append(entry)
                        if self._matches(entry, prefix, fuzzy, case_insensitive):
                            commands.append(entry)
                self._cache[path_dir] = cached
                import time
                self._cache_time[path_dir] = time.time()
            except (PermissionError, FileNotFoundError):
                continue

        # Deduplicate
        seen = set()
        unique = []
        for cmd in commands:
            if cmd not in seen:
                seen.add(cmd)
                unique.append(cmd)

        return sorted(unique)

    def _matches(self, name: str, prefix: str, fuzzy: bool,
                 case_insensitive: bool) -> bool:
        """Check if a name matches the prefix."""
        if case_insensitive:
            name = name.lower()
            prefix = prefix.lower()

        if fuzzy:
            # Fuzzy match: all characters in prefix appear in order
            it = iter(name)
            return all(c in it for c in prefix)
        else:
            return name.startswith(prefix)

    def clear_cache(self) -> None:
        """Clear the command cache."""
        self._cache.clear()
        self._cache_time.clear()


class PathCompleter:
    """Completes file and directory paths."""

    def get_completions(self, prefix: str, include_files: bool = True,
                        include_dirs: bool = True, include_hidden: bool = False,
                        fuzzy: bool = False, case_insensitive: bool = False) -> t.List[str]:
        """Get path completions matching the prefix."""
        if not prefix:
            prefix = "."

        # Handle tilde expansion
        if prefix.startswith("~/"):
            expanded = expanduser(prefix)
            base_dir = os.path.dirname(expanded)
            partial = os.path.basename(expanded)
        elif prefix.startswith("~"):
            # Complete usernames? For now, just expand
            expanded = expanduser(prefix)
            if expanded != prefix:
                base_dir = os.path.dirname(expanded)
                partial = os.path.basename(expanded)
            else:
                return []
        else:
            base_dir = os.path.dirname(prefix) or "."
            partial = os.path.basename(prefix)

        if not base_dir:
            base_dir = "."

        try:
            entries = os.listdir(base_dir)
        except (PermissionError, FileNotFoundError):
            return []

        completions: t.List[str] = []
        for entry in entries:
            if not include_hidden and entry.startswith("."):
                continue

            full = os.path.join(base_dir, entry)
            is_dir = os.path.isdir(full)

            if is_dir and not include_dirs:
                continue
            if not is_dir and not include_files:
                continue

            if self._matches(entry, partial, fuzzy, case_insensitive):
                # Add trailing slash for directories
                if is_dir:
                    completions.append(entry + os.sep)
                else:
                    completions.append(entry)

        return completions

    def _matches(self, name: str, prefix: str, fuzzy: bool,
                 case_insensitive: bool) -> bool:
        """Check if a filename matches the prefix."""
        if case_insensitive:
            name = name.lower()
            prefix = prefix.lower()

        if fuzzy:
            it = iter(name)
            return all(c in it for c in prefix)
        else:
            return name.startswith(prefix)


class VariableCompleter:
    """Completes environment variable names ($VAR)."""

    def get_completions(self, prefix: str, fuzzy: bool = False,
                        case_insensitive: bool = False) -> t.List[str]:
        """Get variable completions matching the prefix."""
        completions = []
        for key in sorted(os.environ.keys()):
            if self._matches(key, prefix, fuzzy, case_insensitive):
                completions.append(f"${key}")
        return completions

    def _matches(self, name: str, prefix: str, fuzzy: bool,
                 case_insensitive: bool) -> bool:
        """Check if a variable name matches the prefix."""
        # Remove leading $ for comparison
        p = prefix.lstrip("$")
        if case_insensitive:
            name = name.lower()
            p = p.lower()

        if fuzzy:
            it = iter(name)
            return all(c in it for c in p)
        else:
            return name.startswith(p)


class HistoryCompleter:
    """Completes from command history."""

    def get_completions(self, prefix: str, limit: int = 20) -> t.List[str]:
        """Get history completions matching the prefix."""
        from .history import get_history_manager
        history = get_history_manager()
        entries = history.search(prefix, limit=limit)
        completions = []
        seen = set()
        for entry in entries:
            cmd = entry.command
            if cmd not in seen and cmd.startswith(prefix):
                seen.add(cmd)
                completions.append(cmd)
        return completions


# ---------------------------------------------------------------------------
# Argument completer (per-command)
# ---------------------------------------------------------------------------

class ArgumentCompleter:
    """Provides argument completions for specific commands."""

    def __init__(self) -> None:
        self._completers: t.Dict[str, t.Callable] = {}

    def register(self, command: str, completer: t.Callable) -> None:
        """Register a completer for a command."""
        self._completers[command] = completer

    def get_completions(self, command: str, args: t.List[str],
                        current_arg: str) -> t.Optional[t.List[str]]:
        """Get argument completions for a specific command."""
        if command in self._completers:
            return self._completers[command](args, current_arg)
        return None

    def _default_completers(self) -> None:
        """Register default argument completers."""
        # cd
        self.register("cd", lambda args, cur: self._complete_path(cur, include_dirs=True, include_files=False))

        # ls
        self.register("ls", lambda args, cur: self._complete_path(cur) if not cur.startswith("-") else self._complete_flag(cur, ["-l", "-a", "-la", "-h", "-R", "-d"]))

        # cat, head, tail, rm, cp, mv, touch, grep
        for cmd in ("cat", "head", "tail", "rm", "touch", "grep", "wc", "sort", "uniq"):
            self.register(cmd, lambda args, cur: self._complete_path(cur))

        # mkdir, rmdir
        for cmd in ("mkdir", "rmdir", "cd"):
            self.register(cmd, lambda args, cur: self._complete_path(cur, include_files=False, include_dirs=True))

        # kill
        self.register("kill", lambda args, cur: self._complete_signal(cur) if cur.startswith("-") else [])

        # export, unset
        for cmd in ("export", "unset"):
            self.register(cmd, lambda args, cur: self._complete_variable(cur))

        # alias, unalias
        self.register("alias", lambda args, cur: self._complete_alias(cur) if "=" not in cur else [])
        self.register("unalias", lambda args, cur: self._complete_alias(cur))

        # type, which
        for cmd in ("type", "which"):
            self.register(cmd, lambda args, cur: self._complete_command(cur))

        history
        self.register("history", lambda args, cur: self._complete_history_flag(cur) if cur.startswith("-") else [])

        # help
        self.register("help", lambda args, cur: self._complete_command(cur))

        # source
        self.register("source", lambda args, cur: self._complete_path(cur))

        # find
        self.register("find", lambda args, cur: self._complete_find_flag(cur, args) if cur.startswith("-") else self._complete_path(cur, include_dirs=True, include_files=False))

    def _complete_path(self, prefix: str, include_files: bool = True,
                       include_dirs: bool = True) -> t.List[str]:
        """Complete file paths."""
        completer = PathCompleter()
        return completer.get_completions(prefix, include_files=include_files, include_dirs=include_dirs)

    def _complete_flag(self, prefix: str, flags: t.List[str]) -> t.List[str]:
        """Complete command flags."""
        return [f for f in flags if f.startswith(prefix)]

    def _complete_signal(self, prefix: str) -> t.List[str]:
        """Complete signal names."""
        signals = []
        for name in dir(signal):
            if name.startswith("SIG") and not name.startswith("SIG_"):
                signals.append(f"-{name[3:]}")
        return [s for s in signals if s.startswith(prefix)]

    def _complete_variable(self, prefix: str) -> t.List[str]:
        """Complete variable names."""
        return [k for k in os.environ.keys() if k.startswith(prefix)]

    def _complete_alias(self, prefix: str) -> t.List[str]:
        """Complete alias names."""
        from .config import get_aliases
        return [a for a in get_aliases().keys() if a.startswith(prefix)]

    def _complete_command(self, prefix: str) -> t.List[str]:
        """Complete command names."""
        completer = CommandCompleter()
        return completer.get_completions(prefix)

    def _complete_history_flag(self, prefix: str) -> t.List[str]:
        """Complete history command flags."""
        flags = ["-c", "-d", "-n", "--help"]
        return [f for f in flags if f.startswith(prefix)]

    def _complete_find_flag(self, prefix: str, args: t.List[str]) -> t.List[str]:
        """Complete find command flags."""
        flags = ["-name", "-type", "-size", "-mtime", "-user", "-group", "-perm", "-exec", "-ok", "-print", "-delete"]
        return [f for f in flags if f.startswith(prefix)]


# ---------------------------------------------------------------------------
# AI-powered completion
# ---------------------------------------------------------------------------

class AICompleter:
    """AI-powered completion suggestions."""

    def __init__(self) -> None:
        self._enabled = True

    def get_completions(self, text: str, cursor_pos: int) -> t.List[str]:
        """Get AI-powered completions for the current input."""
        if not self._enabled:
            return []

        # Simple prefix-based completions without external API calls
        # In a full implementation, this would call an LLM
        return []

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable AI completions."""
        self._enabled = enabled


# ---------------------------------------------------------------------------
# Main completer
# ---------------------------------------------------------------------------

class Completer:
    """Main tab completion orchestrator."""

    def __init__(self) -> None:
        self.command_completer = CommandCompleter()
        self.path_completer = PathCompleter()
        self.variable_completer = VariableCompleter()
        self.history_completer = HistoryCompleter()
        self.argument_completer = ArgumentCompleter()
        self.ai_completer = AICompleter()
        self.argument_completer._default_completers()

        self.fuzzy = True
        self.case_insensitive = True
        self.max_suggestions = 20

    def complete(self, text: str, cursor_pos: int) -> CompletionResult:
        """Get completions for the current input."""
        if not text:
            # Empty input - complete commands
            return self._complete_command("")

        # Split into words, considering cursor position
        words = text[:cursor_pos].split()
        if not words:
            return self._complete_command("")

        # Check if cursor is at the beginning of a new word
        current_word = words[-1] if text[:cursor_pos].endswith(words[-1]) else ""

        # Check if current word starts with $
        if current_word.startswith("$"):
            return self._complete_variable(current_word)

        # Check if we're completing the first word (command)
        is_first_word = len(words) == 1 and (text[:cursor_pos].strip() == current_word or not current_word)

        if is_first_word:
            return self._complete_command(current_word)

        # Complete arguments for the command
        command = words[0]
        args = words[1:-1] if current_word else words[1:]
        return self._complete_argument(command, args, current_word)

    def _complete_command(self, prefix: str) -> CompletionResult:
        """Complete command names."""
        completions = self.command_completer.get_completions(
            prefix, fuzzy=self.fuzzy, case_insensitive=self.case_insensitive
        )

        result = CompletionResult(
            prefix=prefix,
            replacement_end=len(prefix),
        )

        for cmd in completions:
            result.completions.append(Completion(
                text=cmd,
                type="command",
                description=self._get_command_description(cmd),
            ))

        return result

    def _complete_path(self, prefix: str) -> CompletionResult:
        """Complete file paths."""
        completions = self.path_completer.get_completions(
            prefix, fuzzy=self.fuzzy, case_insensitive=self.case_insensitive
        )

        result = CompletionResult(
            prefix=prefix,
            replacement_end=len(prefix),
        )

        for path in completions:
            full = os.path.join(os.path.dirname(prefix) or ".", path)
            is_dir = path.endswith(os.sep)
            result.completions.append(Completion(
                text=path,
                type="dir" if is_dir else "file",
                description=f"({os.path.getsize(os.path.normpath(full))} bytes)" if os.path.isfile(os.path.normpath(full)) else "",
            ))

        return result

    def _complete_variable(self, prefix: str) -> CompletionResult:
        """Complete environment variables."""
        completions = self.variable_completer.get_completions(
            prefix, fuzzy=self.fuzzy, case_insensitive=self.case_insensitive
        )

        result = CompletionResult(
            prefix=prefix,
            replacement_end=len(prefix),
        )

        for var in completions:
            name = var.lstrip("$")
            value = os.environ.get(name, "")
            desc = truncate(value, 40)
            result.completions.append(Completion(
                text=var,
                type="variable",
                description=desc,
            ))

        return result

    def _complete_argument(self, command: str, args: t.List[str],
                          current_word: str) -> CompletionResult:
        """Complete arguments for a specific command."""
        # Try argument completer first
        arg_completions = self.argument_completer.get_completions(command, args, current_word)
        if arg_completions:
            result = CompletionResult(
                prefix=current_word,
                replacement_end=len(current_word),
            )
            for comp in arg_completions:
                result.completions.append(Completion(
                    text=comp,
                    type="arg",
                ))
            return result

        # Fall back to path completion
        return self._complete_path(current_word)

    def _get_command_description(self, cmd: str) -> str:
        """Get a description for a command."""
        from .builtins import BUILTIN_HELP
        if cmd in BUILTIN_HELP:
            first_line = BUILTIN_HELP[cmd].split("\n")[0]
            return first_line
        return ""

    def get_completion_suggestions(self, text: str) -> t.List[str]:
        """Get sorted completion suggestions for display."""
        result = self.complete(text, len(text))
        return [c.text for c in result.completions[:self.max_suggestions]]

    def format_completions(self, completions: t.List[str]) -> str:
        """Format completions for display in the terminal."""
        if not completions:
            return ""

        width = terminal_width()
        max_len = max(len(c) for c in completions) + 2
        cols = max(1, width // max_len)
        rows = (len(completions) + cols - 1) // cols

        lines = []
        for row in range(rows):
            line = ""
            for col in range(cols):
                idx = row + col * rows
                if idx < len(completions):
                    line += completions[idx].ljust(max_len)
            lines.append(line.rstrip())

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level access
# ---------------------------------------------------------------------------

_completer: t.Optional[Completer] = None


def get_completer() -> Completer:
    """Get the global completer singleton."""
    global _completer
    if _completer is None:
        _completer = Completer()
    return _completer


def complete(text: str, state: int = 0) -> t.Optional[str]:
    """Readline-compatible completion function."""
    completer = get_completer()
    result = completer.complete(text, len(text))
    if state < len(result.completions):
        return result.completions[state].text
    return None


__all__ = [
    "Completion", "CompletionResult",
    "CommandCompleter", "PathCompleter", "VariableCompleter",
    "HistoryCompleter", "ArgumentCompleter", "AICompleter",
    "Completer", "get_completer", "complete",
]