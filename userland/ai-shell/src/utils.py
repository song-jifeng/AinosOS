"""
Utility functions for Ainos Shell.

Provides cross-cutting utilities used throughout the shell: file system helpers,
string manipulation, ANSI color handling, process utilities, and platform
abstractions.
"""

from __future__ import annotations

import os
import platform
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import textwrap
import time
import typing as t
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import IO, Any, Callable, Deque, Dict, List, Optional, Sequence, Tuple, Union

# Platform-specific imports
IS_WINDOWS: bool = platform.system().lower() == "windows"
IS_LINUX: bool = platform.system().lower() == "linux"
IS_MACOS: bool = platform.system().lower() == "darwin"
IS_POSIX: bool = not IS_WINDOWS

if IS_WINDOWS:
    import ctypes
    import msvcrt
if IS_POSIX:
    import errno
    import fcntl
    import struct
    import termios
    import pwd
    import grp

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

PLATFORM: str = platform.system().lower()
IS_64BIT: bool = sys.maxsize > 2**32

# ---------------------------------------------------------------------------
# ANSI color / styling helpers
# ---------------------------------------------------------------------------

class AnsiCode:
    """ANSI escape code constants and utilities."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"
    BLINK = "\033[5m"
    REVERSE = "\033[7m"
    HIDDEN = "\033[8m"
    STRIKETHROUGH = "\033[9m"

    # Foreground colors (standard)
    FG_BLACK = "\033[30m"
    FG_RED = "\033[31m"
    FG_GREEN = "\033[32m"
    FG_YELLOW = "\033[33m"
    FG_BLUE = "\033[34m"
    FG_MAGENTA = "\033[35m"
    FG_CYAN = "\033[36m"
    FG_WHITE = "\033[37m"
    FG_DEFAULT = "\033[39m"

    # Foreground colors (bright)
    FG_BRIGHT_BLACK = "\033[90m"
    FG_BRIGHT_RED = "\033[91m"
    FG_BRIGHT_GREEN = "\033[92m"
    FG_BRIGHT_YELLOW = "\033[93m"
    FG_BRIGHT_BLUE = "\033[94m"
    FG_BRIGHT_MAGENTA = "\033[95m"
    FG_BRIGHT_CYAN = "\033[96m"
    FG_BRIGHT_WHITE = "\033[97m"

    # Background colors
    BG_BLACK = "\033[40m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN = "\033[46m"
    BG_WHITE = "\033[47m"
    BG_DEFAULT = "\033[49m"

    # Background colors (bright)
    BG_BRIGHT_BLACK = "\033[100m"
    BG_BRIGHT_RED = "\033[101m"
    BG_BRIGHT_GREEN = "\033[102m"
    BG_BRIGHT_YELLOW = "\033[103m"
    BG_BRIGHT_BLUE = "\033[104m"
    BG_BRIGHT_MAGENTA = "\033[105m"
    BG_BRIGHT_CYAN = "\033[106m"
    BG_BRIGHT_WHITE = "\033[107m"

    # 256-color and truecolor helpers
    @staticmethod
    def fg_256(code: int) -> str:
        """Return ANSI escape for 256-color foreground."""
        return f"\033[38;5;{code}m"

    @staticmethod
    def bg_256(code: int) -> str:
        """Return ANSI escape for 256-color background."""
        return f"\033[48;5;{code}m"

    @staticmethod
    def fg_rgb(r: int, g: int, b: int) -> str:
        """Return ANSI escape for truecolor foreground."""
        return f"\033[38;2;{r};{g};{b}m"

    @staticmethod
    def bg_rgb(r: int, g: int, b: int) -> str:
        """Return ANSI escape for truecolor background."""
        return f"\033[48;2;{r};{g};{b}m"

    @staticmethod
    def strip_ansi(text: str) -> str:
        """Remove all ANSI escape sequences from a string."""
        return re.sub(r"\033\[[0-9;]*[a-zA-Z]", "", text)

    @staticmethod
    def len_without_ansi(text: str) -> int:
        """Return visible length of a string (excluding ANSI escapes)."""
        return len(AnsiCode.strip_ansi(text))

    @staticmethod
    def pad_to(text: str, width: int) -> str:
        """Pad text to width, accounting for ANSI escape codes."""
        visible_len = AnsiCode.len_without_ansi(text)
        padding = max(0, width - visible_len)
        return text + " " * padding


def colorize(text: str, color: str, bold: bool = False) -> str:
    """Wrap text with ANSI color codes."""
    prefix = AnsiCode.BOLD if bold else ""
    return f"{prefix}{color}{text}{AnsiCode.RESET}"


def colorize_path(path: str) -> str:
    """Colorize a file system path segment."""
    p = Path(path)
    if p.is_dir():
        return colorize(p.name, AnsiCode.FG_BLUE, bold=True)
    elif p.is_symlink():
        return colorize(p.name, AnsiCode.FG_CYAN)
    elif p.is_file():
        # Check if executable
        if os.access(p, os.X_OK):
            return colorize(p.name, AnsiCode.FG_GREEN)
        return p.name
    return p.name


# ---------------------------------------------------------------------------
# Terminal utilities
# ---------------------------------------------------------------------------

def get_terminal_size() -> Tuple[int, int]:
    """Get terminal width and height. Returns (columns, lines)."""
    try:
        columns, lines = shutil.get_terminal_size()
        return columns, lines
    except Exception:
        return 80, 24


def terminal_width() -> int:
    """Get terminal width (columns)."""
    return get_terminal_size()[0]


def terminal_height() -> int:
    """Get terminal height (lines)."""
    return get_terminal_size()[1]


def is_tty(stream: t.Optional[IO] = None) -> bool:
    """Check if a stream is a terminal (TTY)."""
    if stream is None:
        stream = sys.stdout
    try:
        return stream.isatty()
    except Exception:
        return False


def enable_virtual_terminal() -> bool:
    """Enable ANSI escape processing on Windows (if applicable)."""
    if not IS_WINDOWS:
        return True
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            DISABLE_NEWLINE_AUTO_RETURN = 0x0008
            new_mode = mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING | DISABLE_NEWLINE_AUTO_RETURN
            kernel32.SetConsoleMode(handle, new_mode)
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# File system utilities
# ---------------------------------------------------------------------------

def expanduser(path: str) -> str:
    """Expand ~ and ~user constructs in path."""
    return os.path.expanduser(path)


def expandvars(path: str, env: Optional[Dict[str, str]] = None) -> str:
    """Expand $VAR and ${VAR} in path."""
    if env is None:
        env = os.environ

    def _replace_var(m: re.Match) -> str:
        name = m.group(1) or m.group(2) or ""
        return env.get(name, m.group(0))

    pattern = r"\$\{([^}]+)\}|\$([a-zA-Z_][a-zA-Z0-9_]*)"
    return re.sub(pattern, _replace_var, path)


def resolve_path(path: str, cwd: Optional[str] = None) -> str:
    """Resolve a path relative to cwd, expanding ~ and variables."""
    if cwd is None:
        cwd = os.getcwd()
    expanded = expanduser(path)
    if not os.path.isabs(expanded):
        expanded = os.path.join(cwd, expanded)
    return os.path.normpath(expanded)


def find_executable(name: str) -> Optional[str]:
    """Find an executable in PATH, similar to `which`."""
    return shutil.which(name)


def list_files(path: str, include_hidden: bool = False) -> List[str]:
    """List files in a directory, returning full paths."""
    try:
        entries = os.listdir(path)
    except PermissionError:
        return []
    except FileNotFoundError:
        return []

    if not include_hidden:
        entries = [e for e in entries if not e.startswith(".")]

    result: List[str] = []
    for entry in sorted(entries):
        full = os.path.join(path, entry)
        result.append(full)
    return result


def is_executable(path: str) -> bool:
    """Check if a path is an executable file."""
    return os.path.isfile(path) and os.access(path, os.X_OK)


def file_size(path: str) -> int:
    """Get file size in bytes."""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def file_modified_time(path: str) -> float:
    """Get file modification timestamp."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def human_readable_size(size: int) -> str:
    """Convert bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(size) < 1024.0:
            return f"{size:3.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}PB"


def human_readable_time(timestamp: float) -> str:
    """Convert unix timestamp to human-readable string."""
    import datetime
    dt = datetime.datetime.fromtimestamp(timestamp)
    now = datetime.datetime.now()
    if dt.date() == now.date():
        return dt.strftime("%H:%M:%S")
    elif dt.year == now.year:
        return dt.strftime("%b %d %H:%M")
    return dt.strftime("%b %d  %Y")


# ---------------------------------------------------------------------------
# String / text utilities
# ---------------------------------------------------------------------------

def truncate(text: str, max_len: int, suffix: str = "...") -> str:
    """Truncate text to max_len, appending suffix if truncated."""
    if len(text) <= max_len:
        return text
    return text[: max_len - len(suffix)] + suffix


def wrap_text(text: str, width: Optional[int] = None) -> str:
    """Wrap text to terminal width."""
    if width is None:
        width = terminal_width()
    return textwrap.fill(text, width=width)


def escape_shell_token(token: str) -> str:
    """Escape a token for safe shell usage."""
    return shlex.quote(token)


def unescape_shell_token(token: str) -> str:
    """Unescape a shell token."""
    # Manual unescape for simplicity
    result = token
    if len(result) >= 2:
        if (result.startswith("'") and result.endswith("'")):
            result = result[1:-1]
        elif (result.startswith('"') and result.endswith('"')):
            result = result[1:-1]
    return result


def split_quoted(text: str) -> List[str]:
    """Split text into tokens, respecting quotes."""
    return shlex.split(text)


def glob_match(pattern: str, name: str) -> bool:
    """Check if name matches a glob pattern (supports *, ?, [chars])."""
    import fnmatch
    return fnmatch.fnmatch(name, pattern)


def is_glob_pattern(pattern: str) -> bool:
    """Check if a string contains glob characters."""
    return bool(set(pattern) & set("*?["))


def expand_glob(pattern: str, cwd: Optional[str] = None) -> List[str]:
    """Expand a glob pattern into matching file paths."""
    import glob as glob_module
    if cwd is None:
        cwd = os.getcwd()
    full_pattern = os.path.join(cwd, pattern) if not os.path.isabs(pattern) else pattern
    return glob_module.glob(full_pattern, recursive=True)


# ---------------------------------------------------------------------------
# Process utilities
# ---------------------------------------------------------------------------

def get_pid() -> int:
    """Get current process ID."""
    return os.getpid()


def get_ppid() -> int:
    """Get parent process ID."""
    return os.getppid()


def list_processes() -> List[Dict[str, Any]]:
    """List running processes (platform-specific)."""
    processes: List[Dict[str, Any]] = []
    if IS_POSIX:
        try:
            for pid_entry in os.listdir("/proc"):
                if not pid_entry.isdigit():
                    continue
                pid = int(pid_entry)
                try:
                    with open(f"/proc/{pid}/stat", "r") as f:
                        stat_data = f.read()
                    # Parse stat
                    comm_end = stat_data.rfind(")")
                    comm = stat_data[stat_data.find("(") + 1:comm_end]
                    parts = stat_data[comm_end + 2:].split()
                    state = parts[0] if parts else "?"
                    ppid = int(parts[1]) if len(parts) > 1 else 0
                    processes.append({
                        "pid": pid,
                        "comm": comm,
                        "state": state,
                        "ppid": ppid,
                    })
                except (IOError, OSError, ValueError, IndexError):
                    continue
        except FileNotFoundError:
            # Fallback to ps
            pass

    # If /proc not available, use ps
    if not processes:
        try:
            if IS_WINDOWS:
                result = subprocess.run(
                    ["tasklist", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = line.strip().split(",")
                    if len(parts) >= 2:
                        name = parts[0].strip('"')
                        pid_str = parts[1].strip('"')
                        if pid_str.isdigit():
                            processes.append({
                                "pid": int(pid_str),
                                "comm": name,
                                "state": "?",
                                "ppid": 0,
                            })
            else:
                result = subprocess.run(
                    ["ps", "-eo", "pid,ppid,stat,comm", "--no-headers"],
                    capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = line.strip().split(None, 3)
                    if len(parts) >= 4 and parts[0].isdigit():
                        processes.append({
                            "pid": int(parts[0]),
                            "ppid": int(parts[1]) if parts[1].isdigit() else 0,
                            "state": parts[2],
                            "comm": parts[3],
                        })
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

    return processes


def kill_process(pid: int, sig: int = signal.SIGTERM) -> bool:
    """Send a signal to a process."""
    try:
        os.kill(pid, sig)
        return True
    except OSError:
        return False


def process_exists(pid: int) -> bool:
    """Check if a process with the given PID exists."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Environment utilities
# ---------------------------------------------------------------------------

def get_env(name: str, default: str = "") -> str:
    """Get an environment variable with a default."""
    return os.environ.get(name, default)


def set_env(name: str, value: str) -> None:
    """Set an environment variable."""
    os.environ[name] = value


def unset_env(name: str) -> None:
    """Unset an environment variable."""
    os.environ.pop(name, None)


def get_paths_from_env() -> List[str]:
    """Get PATH as a list of directories."""
    path = os.environ.get("PATH", "")
    return [p for p in path.split(os.pathsep) if p]


# ---------------------------------------------------------------------------
# Shell / command parsing helpers
# ---------------------------------------------------------------------------

@dataclass
class CommandToken:
    """Represents a single token in a parsed command line."""
    text: str
    quoted: bool = False
    escaped: bool = False
    is_variable: bool = False
    is_glob: bool = False

    def __repr__(self) -> str:
        return f"Token({self.text!r}, q={self.quoted}, e={self.escaped}, v={self.is_variable})"


@dataclass
class RedirectInfo:
    """Represents a single I/O redirection."""
    class Type(Enum):
        INPUT = auto()          # <
        OUTPUT = auto()         # >
        APPEND = auto()         # >>
        HEREDOC = auto()        # <<
        HERESTR = auto()        # <<<
        STDERR_OUTPUT = auto()  # 2>
        STDERR_APPEND = auto()  # 2>>
        STDERR_MERGE = auto()   # 2>&1
        OUTPUT_MERGE = auto()   # &>
        ALL_APPEND = auto()     # &>>

    type: Type
    target: str  # File path or FD number
    fd: int = -1  # Source FD (-1 = unspecified)

    def __repr__(self) -> str:
        type_names = {
            self.Type.INPUT: "<",
            self.Type.OUTPUT: ">",
            self.Type.APPEND: ">>",
            self.Type.HEREDOC: "<<",
            self.Type.HERESTR: "<<<",
            self.Type.STDERR_OUTPUT: "2>",
            self.Type.STDERR_APPEND: "2>>",
            self.Type.STDERR_MERGE: "2>&1",
            self.Type.OUTPUT_MERGE: "&>",
            self.Type.ALL_APPEND: "&>>",
        }
        name = type_names.get(self.type, "?")
        return f"Redirect({name} {self.target})"


@dataclass
class Pipeline:
    """Represents a pipeline of commands connected by |."""
    commands: List["ParsedCommand"] = field(default_factory=list)
    background: bool = False

    def __repr__(self) -> str:
        cmds = " | ".join(str(c) for c in self.commands)
        bg = " &" if self.background else ""
        return f"Pipeline({cmds}{bg})"


@dataclass
class ParsedCommand:
    """Represents a single parsed command with its arguments and redirections."""
    command: str = ""
    args: List[str] = field(default_factory=list)
    redirects: List[RedirectInfo] = field(default_factory=list)
    env_vars: Dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        env = " ".join(f"{k}={v}" for k, v in self.env_vars.items())
        env_prefix = f"({env}) " if self.env_vars else ""
        rd = " ".join(str(r) for r in self.redirects)
        rd_suffix = f" {rd}" if self.redirects else ""
        return f"Cmd({env_prefix}{self.command} {' '.join(self.args)}{rd_suffix})"


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------

class SignalHandler:
    """Context manager for temporarily setting signal handlers."""

    def __init__(self, sig: int, handler: t.Callable) -> None:
        self.sig = sig
        self.handler = handler
        self.old_handler: Any = None

    def __enter__(self) -> "SignalHandler":
        if IS_POSIX:
            self.old_handler = signal.signal(self.sig, self.handler)
        return self

    def __exit__(self, *args: Any) -> None:
        if IS_POSIX and self.old_handler is not None:
            signal.signal(self.sig, self.old_handler)


# ---------------------------------------------------------------------------
# Timing / profiling
# ---------------------------------------------------------------------------

class Timer:
    """Simple timer for measuring command execution time."""

    def __init__(self) -> None:
        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.elapsed: float = 0.0

    def __enter__(self) -> "Timer":
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()

    def start(self) -> None:
        """Start the timer."""
        self.start_time = time.monotonic()

    def stop(self) -> float:
        """Stop the timer and return elapsed seconds."""
        self.end_time = time.monotonic()
        self.elapsed = self.end_time - self.start_time
        return self.elapsed

    def elapsed_str(self) -> str:
        """Return elapsed time as a human-readable string."""
        if self.elapsed < 0.001:
            return f"{self.elapsed * 1000000:.0f}us"
        elif self.elapsed < 1.0:
            return f"{self.elapsed * 1000:.1f}ms"
        elif self.elapsed < 60.0:
            return f"{self.elapsed:.2f}s"
        else:
            minutes = int(self.elapsed // 60)
            seconds = self.elapsed % 60
            return f"{minutes}m {seconds:.1f}s"


# ---------------------------------------------------------------------------
# Configuration / file helpers
# ---------------------------------------------------------------------------

def ensure_dir(path: str) -> str:
    """Ensure a directory exists, creating it if necessary."""
    os.makedirs(path, exist_ok=True)
    return path


def read_file(path: str, encoding: str = "utf-8") -> str:
    """Read a file's contents as a string."""
    with open(path, "r", encoding=encoding) as f:
        return f.read()


def write_file(path: str, content: str, encoding: str = "utf-8") -> None:
    """Write a string to a file."""
    with open(path, "w", encoding=encoding) as f:
        f.write(content)


def append_file(path: str, content: str, encoding: str = "utf-8") -> None:
    """Append a string to a file."""
    with open(path, "a", encoding=encoding) as f:
        f.write(content)


def file_exists(path: str) -> bool:
    """Check if a file exists."""
    return os.path.isfile(path)


def dir_exists(path: str) -> bool:
    """Check if a directory exists."""
    return os.path.isdir(path)


def path_exists(path: str) -> bool:
    """Check if any path exists."""
    return os.path.exists(path)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class LRUCache:
    """Least Recently Used cache with max size."""

    def __init__(self, maxsize: int = 128) -> None:
        self.maxsize = maxsize
        self._cache: Dict[str, Any] = {}
        self._order: Deque[str] = deque()

    def get(self, key: str, default: Any = None) -> Any:
        """Get value by key, moving it to front."""
        if key in self._cache:
            self._order.remove(key)
            self._order.append(key)
            return self._cache[key]
        return default

    def put(self, key: str, value: Any) -> None:
        """Put a key-value pair into the cache."""
        if key in self._cache:
            self._order.remove(key)
        elif len(self._cache) >= self.maxsize:
            oldest = self._order.popleft()
            del self._cache[oldest]
        self._cache[key] = value
        self._order.append(key)

    def remove(self, key: str) -> None:
        """Remove a key from the cache."""
        if key in self._cache:
            del self._cache[key]
            self._order.remove(key)

    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()
        self._order.clear()

    def __contains__(self, key: str) -> bool:
        return key in self._cache

    def __len__(self) -> int:
        return len(self._cache)

    def __repr__(self) -> str:
        return f"LRUCache({len(self)}/{self.maxsize})"


class RingBuffer:
    """Fixed-size ring buffer (circular buffer)."""

    def __init__(self, maxsize: int = 1000) -> None:
        self.maxsize = maxsize
        self._buffer: Deque[Any] = deque(maxlen=maxsize)

    def append(self, item: Any) -> None:
        """Append an item to the buffer."""
        self._buffer.append(item)

    def extend(self, items: t.Iterable[Any]) -> None:
        """Extend buffer with multiple items."""
        self._buffer.extend(items)

    def __getitem__(self, index: int) -> Any:
        return self._buffer[index]

    def __len__(self) -> int:
        return len(self._buffer)

    def __iter__(self) -> t.Iterator[Any]:
        return iter(self._buffer)

    def __reversed__(self) -> t.Iterator[Any]:
        return reversed(self._buffer)

    def clear(self) -> None:
        """Clear the buffer."""
        self._buffer.clear()

    def to_list(self) -> List[Any]:
        """Convert buffer to list."""
        return list(self._buffer)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class ShellError(Exception):
    """Base exception for all shell errors."""
    def __init__(self, message: str, exit_code: int = 1) -> None:
        self.message = message
        self.exit_code = exit_code
        super().__init__(message)


class CommandNotFoundError(ShellError):
    """Raised when a command is not found."""
    def __init__(self, command: str) -> None:
        self.command = command
        super().__init__(f"Command not found: {command}", exit_code=127)


class PermissionDeniedError(ShellError):
    """Raised when permission is denied."""
    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"Permission denied: {path}", exit_code=126)


class SyntaxError_(ShellError):
    """Raised for shell syntax errors."""
    def __init__(self, message: str) -> None:
        super().__init__(f"Syntax error: {message}", exit_code=2)


class ExitRequested(Exception):
    """Raised to request shell exit."""
    def __init__(self, exit_code: int = 0) -> None:
        self.exit_code = exit_code
        super().__init__()


# ---------------------------------------------------------------------------
# Miscellaneous
# ---------------------------------------------------------------------------

def generate_uuid() -> str:
    """Generate a UUID4 string."""
    import uuid
    return str(uuid.uuid4())


def hash_string(text: str) -> str:
    """Return SHA-256 hex digest of a string."""
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


def get_home_dir() -> str:
    """Get the user's home directory."""
    return str(Path.home())


def get_config_dir() -> str:
    """Get the Ainos shell config directory.

    Uses AINOS_HOME environment variable if set (e.g. D:/Ainos/.ainos-data),
    otherwise falls back to ~/.ainos.
    """
    return os.environ.get("AINOS_HOME", os.path.join(get_home_dir(), ".ainos"))


def get_data_dir() -> str:
    """Get the Ainos shell data directory."""
    return os.path.join(get_config_dir(), "data")


def uniqid(prefix: str = "") -> str:
    """Generate a unique ID string."""
    return f"{prefix}{int(time.time() * 1000000)}"


def version_tuple(v: str) -> Tuple[int, ...]:
    """Convert a version string like '1.2.3' to a tuple of ints."""
    return tuple(int(x) for x in v.split("."))


# ---------------------------------------------------------------------------
# Module-level initialization
# ---------------------------------------------------------------------------

# Enable virtual terminal on Windows at import time
enable_virtual_terminal()

# Ensure config/data directories exist
ensure_dir(get_config_dir())
ensure_dir(get_data_dir())

__all__ = [
    "AnsiCode", "colorize", "colorize_path",
    "CommandToken", "RedirectInfo", "ParsedCommand", "Pipeline",
    "ShellError", "CommandNotFoundError", "PermissionDeniedError",
    "SyntaxError_", "ExitRequested",
    "LRUCache", "RingBuffer", "Timer", "SignalHandler",
    "PLATFORM", "IS_WINDOWS", "IS_LINUX", "IS_MACOS", "IS_POSIX",
    "get_terminal_size", "terminal_width", "terminal_height", "is_tty",
    "enable_virtual_terminal",
    "expanduser", "expandvars", "resolve_path",
    "find_executable", "list_files", "is_executable",
    "file_size", "file_modified_time",
    "human_readable_size", "human_readable_time",
    "truncate", "wrap_text", "escape_shell_token", "split_quoted",
    "glob_match", "is_glob_pattern", "expand_glob",
    "list_processes", "kill_process", "process_exists",
    "get_env", "set_env", "unset_env", "get_paths_from_env",
    "get_home_dir", "get_config_dir", "get_data_dir",
    "ensure_dir", "read_file", "write_file", "append_file",
    "file_exists", "dir_exists", "path_exists",
    "generate_uuid", "hash_string", "uniqid", "version_tuple",
]