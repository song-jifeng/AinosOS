#!/usr/bin/env python3
"""AI-powered git commit message generator.

Analyzes git diffs to generate Conventional Commits compliant messages
with support for multiple languages, interactive editing, and rich output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Dict,
    Final,
    FrozenSet,
    Generator,
    List,
    Match,
    Optional,
    Pattern,
    Set,
    Tuple,
    Union,
)

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.syntax import Syntax
    from rich.text import Text
    from rich.prompt import Prompt, Confirm
    from rich.markdown import Markdown
    from rich.rule import Rule
    from rich import box
    RICH_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    RICH_AVAILABLE = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION: Final[str] = "1.0.0"
APP_NAME: Final[str] = "ai-commit"
CONFIG_FILE_NAME: Final[str] = ".ai-commit.json"
DEFAULT_LANGUAGE: Final[str] = "en"
SUPPORTED_LANGUAGES: Final[FrozenSet[str]] = frozenset({"en", "zh"})
MAX_SUBJECT_LENGTH: Final[int] = 72
MAX_BODY_WIDTH: Final[int] = 72
GIT_DIFF_ARGS: Final[Tuple[str, ...]] = ("--staged", "--unified=5")
SCOPE_PATTERN: Final[Pattern[str]] = re.compile(r"^[a-z][a-z0-9_-]*$")


# ---------------------------------------------------------------------------
# CommitType
# ---------------------------------------------------------------------------


class CommitType(str, Enum):
    """Conventional Commits type enumeration.

    Each member represents a standard commit type with its display label
    and emoji indicator for rich output.
    """

    FEAT = "feat"
    FIX = "fix"
    DOCS = "docs"
    REFACTOR = "refactor"
    TEST = "test"
    CHORE = "chore"
    CI = "ci"
    PERF = "perf"
    STYLE = "style"
    BUILD = "build"
    REVERT = "revert"

    @property
    def label(self) -> str:
        """Return a human-readable label for the commit type.

        Returns:
            A capitalized, descriptive label string.
        """
        labels: Dict[CommitType, str] = {
            CommitType.FEAT: "Feature",
            CommitType.FIX: "Bug Fix",
            CommitType.DOCS: "Documentation",
            CommitType.REFACTOR: "Refactor",
            CommitType.TEST: "Test",
            CommitType.CHORE: "Chore",
            CommitType.CI: "CI/CD",
            CommitType.PERF: "Performance",
            CommitType.STYLE: "Style",
            CommitType.BUILD: "Build",
            CommitType.REVERT: "Revert",
        }
        return labels.get(self, self.value.capitalize())

    @property
    def emoji(self) -> str:
        """Return an emoji indicator for the commit type.

        Returns:
            A single emoji string representing the type.
        """
        emojis: Dict[CommitType, str] = {
            CommitType.FEAT: ":sparkles:",
            CommitType.FIX: ":bug:",
            CommitType.DOCS: ":books:",
            CommitType.REFACTOR: ":recycle:",
            CommitType.TEST: ":white_check_mark:",
            CommitType.CHORE: ":wrench:",
            CommitType.CI: ":green_heart:",
            CommitType.PERF: ":racehorse:",
            CommitType.STYLE: ":art:",
            CommitType.BUILD: ":package:",
            CommitType.REVERT: ":rewind:",
        }
        return emojis.get(self, ":question:")

    @classmethod
    def from_string(cls, value: str) -> CommitType:
        """Parse a commit type from a string, case-insensitively.

        Args:
            value: The string to parse (e.g. ``"feat"``, ``"Feat"``).

        Returns:
            The matching CommitType member.

        Raises:
            ValueError: If the string does not match any known type.
        """
        normalized: str = value.strip().lower()
        for member in cls:
            if member.value == normalized:
                return member
        raise ValueError(
            f"Unknown commit type: {value!r}. "
            f"Valid types: {', '.join(m.value for m in cls)}"
        )


# ---------------------------------------------------------------------------
# CommitMessage
# ---------------------------------------------------------------------------


@dataclass
class CommitMessage:
    """Structured representation of a Conventional Commits message.

    Attributes:
        commit_type: The primary commit type (e.g. ``feat``, ``fix``).
        scope: Optional scope indicating the affected module or area.
        subject: A brief imperative description of the change.
        body: Optional detailed description body, one paragraph per line.
        footer: Optional footer lines (e.g. ``BREAKING CHANGE``, issue refs).
        breaking: Whether this introduces a breaking change.
        raw_diff: The original git diff used to generate the message.
    """

    commit_type: CommitType = CommitType.CHORE
    scope: Optional[str] = None
    subject: str = ""
    body: Optional[str] = None
    footer: Optional[str] = None
    breaking: bool = False
    raw_diff: str = ""

    def __post_init__(self) -> None:
        """Validate the message after initialization."""
        if self.scope is not None and not SCOPE_PATTERN.match(self.scope):
            raise ValueError(
                f"Invalid scope: {self.scope!r}. "
                "Scope must match [a-z][a-z0-9_-]*"
            )
        if len(self.subject) > MAX_SUBJECT_LENGTH:
            self.subject = self.subject[:MAX_SUBJECT_LENGTH].rstrip()

    @property
    def formatted(self) -> str:
        """Build the full Conventional Commits formatted string.

        Returns:
            A string conforming to the Conventional Commits 1.0.0 spec.
        """
        header: str = self.commit_type.value
        if self.scope:
            header = f"{header}({self.scope})"
        if self.breaking:
            header = f"{header}!"
        header = f"{header}: {self.subject}"

        parts: List[str] = [header]

        if self.body:
            wrapped_body: str = textwrap.fill(
                self.body,
                width=MAX_BODY_WIDTH,
                break_long_words=False,
                replace_whitespace=False,
            )
            parts.extend(["", wrapped_body])

        if self.footer:
            parts.extend(["", self.footer])

        return "\n".join(parts)

    @property
    def one_line(self) -> str:
        """Return a single-line summary of the commit message.

        Returns:
            The formatted header line only.
        """
        return self.formatted.split("\n")[0]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the message to a JSON-compatible dictionary.

        Returns:
            A dictionary with all fields as plain Python types.
        """
        return {
            "type": self.commit_type.value,
            "scope": self.scope,
            "subject": self.subject,
            "body": self.body,
            "footer": self.footer,
            "breaking": self.breaking,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CommitMessage:
        """Deserialize a dictionary back into a CommitMessage.

        Args:
            data: A dictionary with keys matching the fields.

        Returns:
            A new CommitMessage instance.
        """
        raw_type: str = data.get("type", "chore")
        return cls(
            commit_type=CommitType.from_string(raw_type),
            scope=data.get("scope"),
            subject=data.get("subject", ""),
            body=data.get("body"),
            footer=data.get("footer"),
            breaking=data.get("breaking", False),
            raw_diff=data.get("raw_diff", ""),
        )

    @classmethod
    def empty(cls) -> CommitMessage:
        """Create an empty but valid CommitMessage placeholder.

        Returns:
            A CommitMessage with default values.
        """
        return cls(
            commit_type=CommitType.CHORE,
            subject="(empty — no changes detected)",
        )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class Config:
    """Configuration manager for ai-commit.

    Searches for configuration in the current directory and parent
    directories up to the git root. Supports both JSON config files
    and environment variable overrides.

    Attributes:
        language: Output language code (``en`` or ``zh``).
        max_subject_length: Maximum subject line length.
        max_body_width: Maximum body line width for wrapping.
        show_emoji: Whether to show emoji indicators in output.
        auto_commit: Whether to automatically commit without prompting.
        scope_hint: Optional scope to use if none can be detected.
        allow_breaking: Whether to allow breaking change markers.
        diff_context_lines: Number of context lines in git diff.
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        """Initialize configuration with defaults and optional file override.

        Args:
            config_path: Path to a JSON config file. If None, searches
                automatically from the current directory upward.
        """
        self.language: str = DEFAULT_LANGUAGE
        self.max_subject_length: int = MAX_SUBJECT_LENGTH
        self.max_body_width: int = MAX_BODY_WIDTH
        self.show_emoji: bool = True
        self.auto_commit: bool = False
        self.scope_hint: Optional[str] = None
        self.allow_breaking: bool = True
        self.diff_context_lines: int = 5

        if config_path is not None:
            self._load_from_path(config_path)
        else:
            self._auto_load()

        self._apply_env_overrides()

    # -- Public helpers ----------------------------------------------------

    def save(self, path: Path) -> None:
        """Persist current configuration to a JSON file.

        Args:
            path: Destination file path for the config file.
        """
        data: Dict[str, Any] = {
            "language": self.language,
            "max_subject_length": self.max_subject_length,
            "max_body_width": self.max_body_width,
            "show_emoji": self.show_emoji,
            "auto_commit": self.auto_commit,
            "scope_hint": self.scope_hint,
            "allow_breaking": self.allow_breaking,
            "diff_context_lines": self.diff_context_lines,
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def to_dict(self) -> Dict[str, Any]:
        """Export configuration as a dictionary.

        Returns:
            A dictionary of all config values.
        """
        return {
            "language": self.language,
            "max_subject_length": self.max_subject_length,
            "max_body_width": self.max_body_width,
            "show_emoji": self.show_emoji,
            "auto_commit": self.auto_commit,
            "scope_hint": self.scope_hint,
            "allow_breaking": self.allow_breaking,
            "diff_context_lines": self.diff_context_lines,
        }

    # -- Private helpers ---------------------------------------------------

    def _load_from_path(self, path: Path) -> None:
        """Load configuration from a specific JSON file.

        Args:
            path: Path to the JSON configuration file.
        """
        if not path.is_file():
            return
        try:
            raw: str = path.read_text(encoding="utf-8")
            data: Dict[str, Any] = json.loads(raw)
            self._update_from_dict(data)
        except (json.JSONDecodeError, OSError) as exc:
            if RICH_AVAILABLE:
                console = Console(stderr=True)
                console.print(f":warning:  Failed to load config {path}: {exc}")
            else:
                print(f"Warning: Failed to load config {path}: {exc}", file=sys.stderr)

    def _auto_load(self) -> None:
        """Search upward from the current directory for a config file."""
        current: Path = Path.cwd().resolve()
        for parent in [current] + list(current.parents):
            candidate: Path = parent / CONFIG_FILE_NAME
            if candidate.is_file():
                self._load_from_path(candidate)
                return
            git_dir: Path = parent / ".git"
            if git_dir.is_dir() or git_dir.is_file():
                # Reached the repository root; stop searching here.
                self._load_from_path(candidate)
                return

    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides to config values.

        Environment variables use the prefix ``AI_COMMIT_`` followed
        by the uppercase config key name.
        """
        env_map: Dict[str, str] = {
            "AI_COMMIT_LANGUAGE": "language",
            "AI_COMMIT_AUTO_COMMIT": "auto_commit",
            "AI_COMMIT_SCOPE_HINT": "scope_hint",
            "AI_COMMIT_SHOW_EMOJI": "show_emoji",
            "AI_COMMIT_ALLOW_BREAKING": "allow_breaking",
        }
        overrides: Dict[str, Any] = {}
        for env_key, config_key in env_map.items():
            value: Optional[str] = os.environ.get(env_key)
            if value is not None:
                overrides[config_key] = value

        if overrides:
            self._update_from_dict(overrides)

    def _update_from_dict(self, data: Dict[str, Any]) -> None:
        """Update config fields from a dictionary, validating types.

        Args:
            data: Dictionary of config key-value pairs.
        """
        if "language" in data and data["language"] in SUPPORTED_LANGUAGES:
            self.language = str(data["language"])
        if "max_subject_length" in data:
            self.max_subject_length = int(data["max_subject_length"])
        if "max_body_width" in data:
            self.max_body_width = int(data["max_body_width"])
        if "show_emoji" in data:
            self.show_emoji = self._to_bool(data["show_emoji"])
        if "auto_commit" in data:
            self.auto_commit = self._to_bool(data["auto_commit"])
        if "scope_hint" in data and data["scope_hint"] is not None:
            self.scope_hint = str(data["scope_hint"])
        if "allow_breaking" in data:
            self.allow_breaking = self._to_bool(data["allow_breaking"])
        if "diff_context_lines" in data:
            self.diff_context_lines = max(1, int(data["diff_context_lines"]))

    @staticmethod
    def _to_bool(value: Any) -> bool:
        """Convert a value to boolean, handling string representations.

        Args:
            value: The value to convert (bool, str, int, etc.).

        Returns:
            A boolean value.
        """
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on", "y")
        return bool(value)


# ---------------------------------------------------------------------------
# GitHelper
# ---------------------------------------------------------------------------


class GitError(Exception):
    """Raised when a git command fails."""


class GitHelper:
    """Wrapper around git CLI operations for diff analysis.

    Provides methods for retrieving staged diffs, file lists, and
    repository metadata. All methods raise ``GitError`` on failure.
    """

    def __init__(self, repo_path: Optional[Path] = None) -> None:
        """Initialize the git helper.

        Args:
            repo_path: Path to the repository root. If None, uses the
                current working directory.
        """
        self._repo_path: Path = (repo_path or Path.cwd()).resolve()

    # -- Public API --------------------------------------------------------

    def get_staged_diff(self, context_lines: int = 5) -> str:
        """Retrieve the staged (index) diff.

        Args:
            context_lines: Number of context lines to include in each hunk.

        Returns:
            The raw diff output as a string.

        Raises:
            GitError: If the git command fails.
        """
        cmd: List[str] = [
            "git",
            "diff",
            "--cached",
            f"--unified={context_lines}",
        ]
        return self._run(cmd)

    def get_staged_files(self) -> List[str]:
        """List files staged for commit.

        Returns:
            A list of relative file paths that are staged.
        """
        output: str = self._run(["git", "diff", "--cached", "--name-only"])
        return [line.strip() for line in output.splitlines() if line.strip()]

    def get_staged_status(self) -> List[str]:
        """Get the status of staged files with change indicators.

        Returns:
            Lines from ``git diff --cached --stat``.
        """
        output: str = self._run(["git", "diff", "--cached", "--stat"])
        return [line.strip() for line in output.splitlines() if line.strip()]

    def get_diff_for_file(self, file_path: str, context_lines: int = 5) -> str:
        """Get the staged diff for a single file.

        Args:
            file_path: Relative path to the file.
            context_lines: Number of context lines.

        Returns:
            Raw diff for the specified file.
        """
        cmd: List[str] = [
            "git",
            "diff",
            "--cached",
            f"--unified={context_lines}",
            "--",
            file_path,
        ]
        return self._run(cmd)

    def get_repo_root(self) -> Path:
        """Return the absolute path to the repository root.

        Returns:
            A Path to the repository root directory.

        Raises:
            GitError: If not inside a git repository.
        """
        output: str = self._run(["git", "rev-parse", "--show-toplevel"])
        return Path(output.strip())

    def get_current_branch(self) -> str:
        """Return the name of the current git branch.

        Returns:
            The branch name (e.g. ``main``, ``feature/foo``).
        """
        return self._run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip()

    def get_branch_commits(self, branch: str = "HEAD", count: int = 10) -> List[str]:
        """Return the last N commit subjects on a branch.

        Args:
            branch: Branch name or ref.
            count: Number of recent commits to retrieve.

        Returns:
            A list of commit subject lines.
        """
        output: str = self._run(
            ["git", "log", f"-{count}", "--oneline", branch, "--"]
        )
        return [line.strip() for line in output.splitlines() if line.strip()]

    def get_changed_file_extensions(self) -> Set[str]:
        """Return the set of file extensions among staged files.

        Returns:
            A set of extension strings without the leading dot (e.g.
            ``{'py', 'js', 'ts'}``).
        """
        files: List[str] = self.get_staged_files()
        exts: Set[str] = set()
        for f in files:
            ext: str = Path(f).suffix.lstrip(".").lower()
            if ext:
                exts.add(ext)
        return exts

    def commit(self, message: str) -> str:
        """Create a git commit with the given message.

        Args:
            message: The commit message (may be multi-line).

        Returns:
            The raw output of the git commit command.

        Raises:
            GitError: If the commit fails.
        """
        return self._run(["git", "commit", "--message", message])

    def amend(self, message: str) -> str:
        """Amend the last commit with a new message.

        Args:
            message: The new commit message.

        Returns:
            The raw output of the git commit --amend command.
        """
        return self._run(
            ["git", "commit", "--amend", "--message", message]
        )

    def has_staged_changes(self) -> bool:
        """Check whether there are any staged changes.

        Returns:
            True if there is at least one staged file.

        Raises:
            GitError: If the git command itself fails (e.g. not a repo).
        """
        try:
            result = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                capture_output=True,
                text=True,
                cwd=str(self._repo_path),
                timeout=30,
            )
            # git diff --cached --quiet returns exit code 0 if no changes,
            # exit code 1 if there are changes. Exit code 128+ means error.
            if result.returncode == 0:
                return False
            if result.returncode == 1:
                return True
            # Any other exit code (e.g. 128 for not a git repo) is an error
            stderr: str = result.stderr.strip()
            raise GitError(
                f"git diff --cached --quiet failed: {stderr}"
            )
        except FileNotFoundError:
            raise GitError("git executable not found. Is git installed?")
        except subprocess.TimeoutExpired:
            raise GitError("git command timed out after 30 seconds")

    # -- Private helpers ---------------------------------------------------

    def _run(
        self,
        cmd: List[str],
        check: bool = True,
    ) -> str:
        """Execute a git command and return its stdout.

        Args:
            cmd: The command as a list of strings.
            check: If True, raise GitError on non-zero exit.

        Returns:
            The command's stdout as a string.

        Raises:
            GitError: If the command fails and ``check`` is True.
        """
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self._repo_path),
                timeout=30,
            )
            if check and result.returncode != 0:
                stderr: str = result.stderr.strip()
                raise GitError(
                    f"git command failed: {' '.join(cmd)}\n{stderr}"
                )
            return result.stdout
        except FileNotFoundError:
            raise GitError("git executable not found. Is git installed?")
        except subprocess.TimeoutExpired:
            raise GitError("git command timed out after 30 seconds")

    def has_staged(self) -> bool:
        """Check if there are staged changes (alias for has_staged_changes).

        Returns:
            True if staged changes exist.
        """
        return self.has_staged_changes()


# ---------------------------------------------------------------------------
# DiffParser
# ---------------------------------------------------------------------------


class DiffParseError(Exception):
    """Raised when diff parsing encounters an unexpected format."""


@dataclass
class DiffHunk:
    """Represents a single hunk from a unified diff.

    Attributes:
        old_start: Starting line number in the old file.
        old_count: Number of lines in the old file hunk.
        new_start: Starting line number in the new file.
        new_count: Number of lines in the new file hunk.
        content: The raw lines of the hunk, including the header.
        added_lines: Count of added lines in this hunk.
        removed_lines: Count of removed lines in this hunk.
    """

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    content: List[str] = field(default_factory=list)
    added_lines: int = 0
    removed_lines: int = 0

    @property
    def is_empty(self) -> bool:
        """Check if the hunk contains no changes."""
        return self.added_lines == 0 and self.removed_lines == 0


@dataclass
class DiffFile:
    """Represents a single file's changes in a diff.

    Attributes:
        old_path: Path of the file in the old version.
        new_path: Path of the file in the new version.
        status: Change status (``modified``, ``added``, ``deleted``, ``renamed``).
        hunks: List of DiffHunk objects for this file.
        total_added: Total added lines across all hunks.
        total_removed: Total removed lines across all hunks.
    """

    old_path: str
    new_path: str
    status: str = "modified"
    hunks: List[DiffHunk] = field(default_factory=list)
    total_added: int = 0
    total_removed: int = 0

    @property
    def display_path(self) -> str:
        """Return the best path for display purposes."""
        return self.new_path if self.new_path != "/dev/null" else self.old_path

    @property
    def extension(self) -> str:
        """Return the file extension of the changed file."""
        return Path(self.display_path).suffix.lstrip(".").lower()


class DiffParser:
    """Parses unified git diff output into structured DiffFile objects.

    Handles standard unified diffs including file headers (``---/+++``),
    hunk headers (``@@ ... @@``), and line-level add/remove markers.
    """

    # Regex patterns for diff parsing
    _FILE_HEADER: Final[Pattern[str]] = re.compile(
        r"^diff --git a/(.+?) b/(.+?)$"
    )
    _OLD_FILE: Final[Pattern[str]] = re.compile(r"^--- (?:a/)?(.+)$")
    _NEW_FILE: Final[Pattern[str]] = re.compile(r"^\+\+\+ (?:b/)?(.+)$")
    _HUNK_HEADER: Final[Pattern[str]] = re.compile(
        r"^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@(?:\s+(.*))?$"
    )
    _NEW_FILE_MODE: Final[Pattern[str]] = re.compile(r"^new file mode")
    _DELETED_FILE_MODE: Final[Pattern[str]] = re.compile(r"^deleted file mode")
    _RENAME_FROM: Final[Pattern[str]] = re.compile(r"^rename from (.+)$")
    _RENAME_TO: Final[Pattern[str]] = re.compile(r"^rename to (.+)$")
    _INDEX_LINE: Final[Pattern[str]] = re.compile(r"^index ")

    def parse(self, diff_text: str) -> List[DiffFile]:
        """Parse a complete unified diff into structured DiffFile objects.

        Args:
            diff_text: The raw output of ``git diff``.

        Returns:
            A list of ``DiffFile`` objects, one per changed file.

        Raises:
            DiffParseError: If the diff format is unrecognizable.
        """
        if not diff_text.strip():
            return []

        files: List[DiffFile] = []
        current_file: Optional[DiffFile] = None
        current_hunk: Optional[DiffHunk] = None
        lines: List[str] = diff_text.splitlines()

        for line in lines:
            # Try file header
            file_match: Optional[Match[str]] = self._FILE_HEADER.match(line)
            if file_match:
                self._finalize_hunk(current_file, current_hunk)
                current_file = DiffFile(
                    old_path=file_match.group(1),
                    new_path=file_match.group(2),
                )
                files.append(current_file)
                current_hunk = None
                continue

            # Try new file mode
            if self._NEW_FILE_MODE.match(line) and current_file is not None:
                current_file.status = "added"
                continue

            # Try deleted file mode
            if self._DELETED_FILE_MODE.match(line) and current_file is not None:
                current_file.status = "deleted"
                continue

            # Try rename detection
            rename_from: Optional[Match[str]] = self._RENAME_FROM.match(line)
            if rename_from and current_file is not None:
                current_file.old_path = rename_from.group(1)
                current_file.status = "renamed"
                continue
            rename_to: Optional[Match[str]] = self._RENAME_TO.match(line)
            if rename_to and current_file is not None:
                current_file.new_path = rename_to.group(1)
                current_file.status = "renamed"
                continue

            # Try old file path (--- a/file or --- /dev/null)
            old_file_match: Optional[Match[str]] = self._OLD_FILE.match(line)
            if old_file_match and current_file is not None:
                current_file.old_path = old_file_match.group(1)
                continue

            # Try new file path (+++ b/file or +++ /dev/null)
            new_file_match: Optional[Match[str]] = self._NEW_FILE.match(line)
            if new_file_match and current_file is not None:
                current_file.new_path = new_file_match.group(1)
                continue

            # Try hunk header
            hunk_match: Optional[Match[str]] = self._HUNK_HEADER.match(line)
            if hunk_match and current_file is not None:
                self._finalize_hunk(current_file, current_hunk)
                old_start: int = int(hunk_match.group(1))
                old_count_str: str = hunk_match.group(2)
                old_count: int = int(old_count_str) if old_count_str else 1
                new_start: int = int(hunk_match.group(3))
                new_count_str: str = hunk_match.group(4)
                new_count: int = int(new_count_str) if new_count_str else 1
                current_hunk = DiffHunk(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                )
                current_hunk.content.append(line)
                continue

            # Content lines within a hunk
            if current_hunk is not None:
                current_hunk.content.append(line)
                if line.startswith("+"):
                    current_hunk.added_lines += 1
                elif line.startswith("-"):
                    current_hunk.removed_lines += 1

        # Finalize the last hunk
        self._finalize_hunk(current_file, current_hunk)

        return files

    def parse_summary(self, diff_text: str) -> Dict[str, Any]:
        """Produce a summary dictionary from a diff.

        Args:
            diff_text: Raw git diff output.

        Returns:
            A dictionary with keys: ``files``, ``total_added``,
            ``total_removed``, ``hunks``, ``extensions``.
        """
        files: List[DiffFile] = self.parse(diff_text)
        total_added: int = 0
        total_removed: int = 0
        total_hunks: int = 0
        extensions: Set[str] = set()

        for f in files:
            total_added += f.total_added
            total_removed += f.total_removed
            total_hunks += len(f.hunks)
            ext: str = f.extension
            if ext:
                extensions.add(ext)

        return {
            "files": files,
            "total_added": total_added,
            "total_removed": total_removed,
            "total_hunks": total_hunks,
            "extensions": sorted(extensions),
            "file_count": len(files),
        }

    # -- Private helpers ---------------------------------------------------

    @staticmethod
    def _finalize_hunk(
        file: Optional[DiffFile],
        hunk: Optional[DiffHunk],
    ) -> None:
        """Finalize a hunk by adding it to its parent file.

        Args:
            file: The parent DiffFile, if any.
            hunk: The DiffHunk to finalize, if any.
        """
        if file is None or hunk is None:
            return
        file.hunks.append(hunk)
        file.total_added += hunk.added_lines
        file.total_removed += hunk.removed_lines


# ---------------------------------------------------------------------------
# CommitTypeDetector
# ---------------------------------------------------------------------------


class CommitTypeDetector:
    """Detects the appropriate Conventional Commits type from a diff.

    Uses keyword heuristics, file patterns, and change characteristics
    to determine the most suitable commit type.
    """

    # Mapping of keywords to commit types
    KEYWORD_MAP: Final[Dict[Pattern[str], CommitType]] = {
        re.compile(r"\bfix\b", re.IGNORECASE): CommitType.FIX,
        re.compile(r"\bbug\b", re.IGNORECASE): CommitType.FIX,
        re.compile(r"\bhotfix\b", re.IGNORECASE): CommitType.FIX,
        re.compile(r"\berror\b", re.IGNORECASE): CommitType.FIX,
        re.compile(r"\bcrash\b", re.IGNORECASE): CommitType.FIX,
        re.compile(r"\bdocs?\b", re.IGNORECASE): CommitType.DOCS,
        re.compile(r"\bdocumentation\b", re.IGNORECASE): CommitType.DOCS,
        re.compile(r"\breadme\b", re.IGNORECASE): CommitType.DOCS,
        re.compile(r"\brefactor\b", re.IGNORECASE): CommitType.REFACTOR,
        re.compile(r"\brefactor\b", re.IGNORECASE): CommitType.REFACTOR,
        re.compile(r"\btest\b", re.IGNORECASE): CommitType.TEST,
        re.compile(r"\bspec\b", re.IGNORECASE): CommitType.TEST,
        re.compile(r"\bunittest\b", re.IGNORECASE): CommitType.TEST,
        re.compile(r"\bchore\b", re.IGNORECASE): CommitType.CHORE,
        re.compile(r"\bconfig\b", re.IGNORECASE): CommitType.CHORE,
        re.compile(r"\bci\b", re.IGNORECASE): CommitType.CI,
        re.compile(r"\bcd\b", re.IGNORECASE): CommitType.CI,
        re.compile(r"\bgithub.actions\b", re.IGNORECASE): CommitType.CI,
        re.compile(r"\bperf\b", re.IGNORECASE): CommitType.PERF,
        re.compile(r"\boptimize\b", re.IGNORECASE): CommitType.PERF,
        re.compile(r"\bperformance\b", re.IGNORECASE): CommitType.PERF,
        re.compile(r"\bstyle\b", re.IGNORECASE): CommitType.STYLE,
        re.compile(r"\blint\b", re.IGNORECASE): CommitType.STYLE,
        re.compile(r"\bformat\b", re.IGNORECASE): CommitType.STYLE,
        re.compile(r"\bbuild\b", re.IGNORECASE): CommitType.BUILD,
    }

    # File-path patterns that suggest a commit type
    PATH_PATTERNS: Final[Dict[Pattern[str], CommitType]] = {
        re.compile(r"^docs/"): CommitType.DOCS,
        re.compile(r"^test/"): CommitType.TEST,
        re.compile(r"^tests/"): CommitType.TEST,
        re.compile(r"^spec/"): CommitType.TEST,
        re.compile(r"\.spec\.\w+$"): CommitType.TEST,
        re.compile(r"\.test\.\w+$"): CommitType.TEST,
        re.compile(r"^\.github/workflows/"): CommitType.CI,
        re.compile(r"^\.gitlab-ci"): CommitType.CI,
        re.compile(r"^Jenkinsfile"): CommitType.CI,
        re.compile(r"^Makefile"): CommitType.BUILD,
        re.compile(r"^CMakeLists"): CommitType.BUILD,
        re.compile(r"^package\.json$"): CommitType.BUILD,
        re.compile(r"^setup\.py$"): CommitType.BUILD,
        re.compile(r"^pyproject\.toml$"): CommitType.BUILD,
        re.compile(r"^Cargo\.toml$"): CommitType.BUILD,
        re.compile(r"^go\.mod$"): CommitType.BUILD,
    }

    # Lines that suggest a feature addition
    FEATURE_PATTERNS: Final[List[Pattern[str]]] = [
        re.compile(r"^\+\s*(def |function |async function |public |private )", re.MULTILINE),
        re.compile(r"^\+\s*class \w+", re.MULTILINE),
        re.compile(r"^\+\s*interface \w+", re.MULTILINE),
        re.compile(r"^\+\s*type \w+", re.MULTILINE),
        re.compile(r"^\+\s*enum \w+", re.MULTILINE),
        re.compile(r"^\+\s*struct \w+", re.MULTILINE),
        re.compile(r"^\+\s*impl \w+", re.MULTILINE),
        re.compile(r"^\+\s*trait \w+", re.MULTILINE),
        re.compile(r"^\+\s*export (default |const |function |class )", re.MULTILINE),
        re.compile(r"^\+\s*defmodule ", re.MULTILINE),
        re.compile(r"^\+\s*defimpl ", re.MULTILINE),
        re.compile(r"^\+\s*@app\.route", re.MULTILINE),
        re.compile(r"^\+\s*@router\.(get|post|put|delete)", re.MULTILINE),
        re.compile(r"^\+\s*app\.(get|post|put|delete)", re.MULTILINE),
    ]

    # Lines that suggest a bug fix
    BUG_PATTERNS: Final[List[Pattern[str]]] = [
        re.compile(r"^\+\s*# (TODO|FIXME|HACK|BUG)", re.MULTILINE),
        re.compile(r"^\+\s*// (TODO|FIXME|HACK|BUG)", re.MULTILINE),
        re.compile(r"^\+\s*/\* (TODO|FIXME|HACK|BUG)", re.MULTILINE),
        re.compile(r"^\-\s*# (TODO|FIXME|HACK|BUG)", re.MULTILINE),
        re.compile(r"^\+\s*if\s+\(?\w+\s+(!=|==|is not|is)\s+None", re.MULTILINE),
        re.compile(r"^\+\s*if\s+\(?\w+\s+(!=|==)\s+null", re.MULTILINE),
        re.compile(r"^\+\s*if\s+\(?\w+\s+(!=|==)\s+undefined", re.MULTILINE),
        re.compile(r"^\+\s*try\s*[{:]", re.MULTILINE),
        re.compile(r"^\+\s*catch\s*\(", re.MULTILINE),
        re.compile(r"^\+\s*except\s+", re.MULTILINE),
        re.compile(r"^\+\s*raise\s+", re.MULTILINE),
        re.compile(r"^\-\s*try\s*[{:]", re.MULTILINE),
        re.compile(r"^\-\s*catch\s*\(", re.MULTILINE),
        re.compile(r"^\-\s*except\s+", re.MULTILINE),
        re.compile(r"^\+\s*assert\b", re.MULTILINE),
        re.compile(r"^\+\s*guard\b", re.MULTILINE),
        re.compile(r"^\+\s*if\s+.+?(?:return|break|continue|raise|throw)", re.MULTILINE),
    ]

    def detect(
        self,
        diff_files: List[DiffFile],
        diff_text: str,
    ) -> CommitType:
        """Detect the most appropriate commit type for a diff.

        Uses a scoring system: path patterns, keyword analysis, and
        line-level patterns all contribute to the final classification.

        Args:
            diff_files: Parsed DiffFile objects from the diff.
            diff_text: The raw diff text for keyword scanning.

        Returns:
            The detected CommitType. Defaults to ``feat`` if no strong
            signal is found (for new code) or ``chore`` otherwise.
        """
        scores: Dict[CommitType, int] = {t: 0 for t in CommitType}

        # Score based on file paths
        for diff_file in diff_files:
            path: str = diff_file.display_path
            for pattern, ctype in self.PATH_PATTERNS.items():
                if pattern.search(path):
                    scores[ctype] += 3

        # Score based on keywords in the diff
        for pattern, ctype in self.KEYWORD_MAP.items():
            matches: List[str] = pattern.findall(diff_text)
            scores[ctype] += len(matches)

        # Score based on line-level patterns for features
        for pattern in self.FEATURE_PATTERNS:
            matches = pattern.findall(diff_text)
            scores[CommitType.FEAT] += len(matches) * 2

        # Score based on line-level patterns for bug fixes
        for pattern in self.BUG_PATTERNS:
            matches = pattern.findall(diff_text)
            scores[CommitType.FIX] += len(matches) * 2

        # If most changes are in test files, default to test
        test_files: int = sum(
            1 for f in diff_files
            if "test" in f.display_path.lower()
            or "spec" in f.display_path.lower()
        )
        if diff_files and test_files / len(diff_files) > 0.5:
            scores[CommitType.TEST] += 5

        # If most changes are in doc files, default to docs
        doc_files: int = sum(
            1 for f in diff_files
            if f.extension in {"md", "rst", "txt", "adoc", "asciidoc"}
        )
        if diff_files and doc_files / len(diff_files) > 0.5:
            scores[CommitType.DOCS] += 5

        # Pick the type with the highest score
        best: CommitType = max(scores, key=lambda t: scores[t])  # type: ignore[type-var]

        # If no strong signal, default based on whether there are new features
        if scores[best] == 0:
            has_new_code: bool = any(
                "def " in line or "function " in line or "class " in line
                for line in diff_text.splitlines()
                if line.startswith("+")
            )
            return CommitType.FEAT if has_new_code else CommitType.CHORE

        return best

    def detect_scope(self, diff_files: List[DiffFile]) -> Optional[str]:
        """Detect a scope from the changed file paths.

        Attempts to identify a common directory prefix or module name
        that would serve as a good scope indicator.

        Args:
            diff_files: Parsed DiffFile objects.

        Returns:
            A scope string if identifiable, otherwise None.
        """
        if not diff_files:
            return None

        paths: List[str] = [f.display_path for f in diff_files]

        # If only one file, try to infer scope from the directory
        if len(paths) == 1:
            parts: List[str] = Path(paths[0]).parts
            if len(parts) >= 2:
                candidate: str = parts[0].replace("_", "-").lower()
                if SCOPE_PATTERN.match(candidate):
                    return candidate
            return None

        # Multiple files: find the common ancestor directory
        try:
            common: str = os.path.commonpath(paths)
            if common and common != ".":
                parts = Path(common).parts
                if parts:
                    candidate = parts[0].replace("_", "-").lower()
                    if SCOPE_PATTERN.match(candidate):
                        return candidate
        except ValueError:
            pass

        return None

    def detect_breaking_change(self, diff_files: List[DiffFile]) -> bool:
        """Determine whether the diff introduces a breaking change.

        Checks for indicators like removed public APIs, changed function
        signatures, or explicit ``BREAKING CHANGE`` markers.

        Args:
            diff_files: Parsed DiffFile objects.

        Returns:
            True if a breaking change is detected.
        """
        for diff_file in diff_files:
            for hunk in diff_file.hunks:
                for line in hunk.content:
                    if "BREAKING CHANGE" in line or "BREAKING-CHANGE" in line:
                        return True
                    # Detect removed function definitions
                    if line.startswith("-") and re.search(
                        r"\b(def |function |pub (fn|struct|enum|trait) )",
                        line,
                    ):
                        return True
        return False


# ---------------------------------------------------------------------------
# FunctionExtractor
# ---------------------------------------------------------------------------


class FunctionExtractor:
    """Extracts the names of changed functions and methods from a diff.

    Supports multiple programming languages by pattern-matching common
    function/method definition syntaxes in added/modified lines.
    """

    # Language-specific function definition patterns
    FUNCTION_PATTERNS: Final[Dict[str, List[Pattern[str]]]] = {
        "python": [
            re.compile(r"^\+\s*async\s+def\s+(\w+)\s*\("),
            re.compile(r"^\+\s*def\s+(\w+)\s*\("),
            re.compile(r"^\+\s*class\s+(\w+)\s*(?:\(|:)"),
        ],
        "javascript": [
            re.compile(r"^\+\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\("),
            re.compile(r"^\+\s*(?:export\s+)?(?:async\s+)?function\s*\*?\s*(\w+)\s*\("),
            re.compile(r"^\+\s*const\s+(\w+)\s*=\s*(?:async\s*)?\(?.*\)?\s*=>"),
            re.compile(r"^\+\s*class\s+(\w+)\s*(?:extends\s+\w+\s*)?{"),
            re.compile(r"^\+\s*(\w+)\s*\([^)]*\)\s*{"),
            re.compile(r"^\+\s*(?:export\s+)?default\s+(?:async\s+)?function\s+(\w+)"),
        ],
        "typescript": [
            re.compile(r"^\+\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\("),
            re.compile(r"^\+\s*(?:export\s+)?(?:async\s+)?function\s*\*?\s*(\w+)\s*\("),
            re.compile(r"^\+\s*const\s+(\w+)\s*[=:]\s*(?:async\s*)?\(?.*\)?\s*[=:]>"),
            re.compile(r"^\+\s*class\s+(\w+)\s*(?:extends\s+\w+\s*)?(?:implements\s+.+)?{"),
            re.compile(r"^\+\s*interface\s+(\w+)\s*(?:extends\s+.+)?{"),
            re.compile(r"^\+\s*type\s+(\w+)\s*="),
            re.compile(r"^\+\s*enum\s+(\w+)\s*{"),
            re.compile(r"^\+\s*abstract\s+class\s+(\w+)"),
            re.compile(r"^\+\s*(?:public|private|protected)\s+(?:static\s+)?(\w+)\s*\("),
        ],
        "java": [
            re.compile(r"^\+\s*(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?\w+\s+(\w+)\s*\("),
            re.compile(r"^\+\s*class\s+(\w+)\s*(?:extends\s+\w+\s*)?(?:implements\s+.+)?{"),
            re.compile(r"^\+\s*interface\s+(\w+)\s*(?:extends\s+.+)?{"),
            re.compile(r"^\+\s*enum\s+(\w+)\s*(?:implements\s+.+)?{"),
            re.compile(r"^\+\s*@Override\s*$"),
            re.compile(r"^\+\s*(?:public|private|protected)\s+(\w+)\s*\("),
        ],
        "rust": [
            re.compile(r"^\+\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*\("),
            re.compile(r"^\+\s*(?:pub\s+)?struct\s+(\w+)\s*(?:<[^>]+>)?(?:;|{)?"),
            re.compile(r"^\+\s*(?:pub\s+)?enum\s+(\w+)\s*(?:<[^>]+>)?(?:;|{)?"),
            re.compile(r"^\+\s*(?:pub\s+)?trait\s+(\w+)\s*(?:<[^>]+>)?(?:;|{)?"),
            re.compile(r"^\+\s*(?:pub\s+)?impl\s+(\w+)\s*(?:<[^>]+>)?(?: for .+)?\s*{"),
            re.compile(r"^\+\s*(?:pub\s+)?macro_rules!\s*(\w+)"),
            re.compile(r"^\+\s*(?:pub\s+)?type\s+(\w+)\s*="),
            re.compile(r"^\+\s*(?:pub\s+)?(?:unsafe\s+)?fn\s+(\w+)\s*\("),
        ],
        "go": [
            re.compile(r"^\+\s*func\s+(\w+)\s*\("),
            re.compile(r"^\+\s*func\s+\(?\w+\s+\*?\w+\)?\s+(\w+)\s*\("),
            re.compile(r"^\+\s*type\s+(\w+)\s+(struct|interface)\s*{"),
            re.compile(r"^\+\s*func\s+\(?\w+\s+\*?\w+\)?\s+(\w+)\s*\("),
        ],
    }

    # Catch-all patterns for unknown languages
    FALLBACK_PATTERNS: Final[List[Pattern[str]]] = [
        re.compile(r"^\+\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\("),
        re.compile(r"^\+\s*(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?\w+\s+(\w+)\s*\("),
        re.compile(r"^\+\s*def\s+(\w+)\s*\("),
        re.compile(r"^\+\s*fn\s+(\w+)\s*\("),
        re.compile(r"^\+\s*func\s+(\w+)\s*\("),
        re.compile(r"^\+\s*class\s+(\w+)"),
        re.compile(r"^\+\s*interface\s+(\w+)"),
        re.compile(r"^\+\s*struct\s+(\w+)"),
        re.compile(r"^\+\s*enum\s+(\w+)"),
        re.compile(r"^\+\s*trait\s+(\w+)"),
        re.compile(r"^\+\s*type\s+(\w+)\s*[=:]"),
    ]

    def __init__(self) -> None:
        """Initialize the extractor with per-language pattern caches."""
        self._pattern_cache: Dict[str, List[Pattern[str]]] = {}

    def extract(
        self,
        diff_files: List[DiffFile],
        language_hint: Optional[str] = None,
    ) -> List[str]:
        """Extract names of changed functions/methods from diff files.

        Args:
            diff_files: Parsed DiffFile objects.
            language_hint: Optional language override. If None, inferred
                from file extensions.

        Returns:
            A sorted, unique list of function/method/class names that
            appear in the diff.
        """
        extracted: Set[str] = set()

        for diff_file in diff_files:
            ext: str = diff_file.extension
            patterns: List[Pattern[str]] = self._get_patterns_for_ext(ext, language_hint)

            for hunk in diff_file.hunks:
                for line in hunk.content:
                    for pattern in patterns:
                        match: Optional[Match[str]] = pattern.search(line)
                        if match:
                            name: str = match.group(1)
                            # Filter out keywords and common false positives
                            if name and not self._is_false_positive(name):
                                extracted.add(name)

        return sorted(extracted)

    def extract_with_context(
        self,
        diff_files: List[DiffFile],
        language_hint: Optional[str] = None,
    ) -> Dict[str, List[str]]:
        """Extract functions with the file paths they appear in.

        Args:
            diff_files: Parsed DiffFile objects.
            language_hint: Optional language override.

        Returns:
            A dictionary mapping function names to lists of file paths.
        """
        result: Dict[str, List[str]] = {}

        for diff_file in diff_files:
            ext: str = diff_file.extension
            patterns: List[Pattern[str]] = self._get_patterns_for_ext(ext, language_hint)

            for hunk in diff_file.hunks:
                for line in hunk.content:
                    for pattern in patterns:
                        match: Optional[Match[str]] = pattern.search(line)
                        if match:
                            name: str = match.group(1)
                            if name and not self._is_false_positive(name):
                                result.setdefault(name, []).append(diff_file.display_path)

        return result

    # -- Private helpers ---------------------------------------------------

    def _get_patterns_for_ext(
        self,
        extension: str,
        language_hint: Optional[str] = None,
    ) -> List[Pattern[str]]:
        """Get the appropriate function patterns for a file extension.

        Args:
            extension: File extension without dot (e.g. ``py``, ``js``).
            language_hint: Explicit language override.

        Returns:
            A list of compiled regex patterns.
        """
        if language_hint:
            return self.FUNCTION_PATTERNS.get(
                language_hint, self.FALLBACK_PATTERNS
            )

        # Map extensions to language names
        ext_map: Dict[str, str] = {
            "py": "python",
            "js": "javascript",
            "jsx": "javascript",
            "mjs": "javascript",
            "cjs": "javascript",
            "ts": "typescript",
            "tsx": "typescript",
            "java": "java",
            "kt": "java",
            "scala": "java",
            "rs": "rust",
            "go": "go",
            "golang": "go",
        }

        lang: Optional[str] = ext_map.get(extension)
        if lang:
            return self.FUNCTION_PATTERNS.get(lang, self.FALLBACK_PATTERNS)

        return self.FALLBACK_PATTERNS

    @staticmethod
    def _is_false_positive(name: str) -> bool:
        """Check if an extracted name is likely a false positive.

        Args:
            name: The extracted identifier name.

        Returns:
            True if the name should be discarded.
        """
        # Skip common non-function identifiers
        false_positives: FrozenSet[str] = frozenset({
            "if", "for", "while", "switch", "catch", "class", "function",
            "return", "import", "export", "default", "extends", "implements",
            "async", "await", "yield", "throw", "new", "delete", "void",
            "let", "const", "var", "val", "var", "this", "super", "static",
            "public", "private", "protected", "readonly", "abstract",
            "self", "mut", "ref", "dyn", "impl", "trait", "struct", "enum",
            "true", "false", "none", "null", "undefined", "nil",
        })
        return name.lower() in false_positives


# ---------------------------------------------------------------------------
# MessageGenerator
# ---------------------------------------------------------------------------


class MessageGenerator:
    """Generates Conventional Commits messages from parsed diff data.

    Supports multiple languages and customizable templates for the
    commit subject and body.
    """

    # Template strings for different languages
    SUBJECT_TEMPLATES: Final[Dict[str, str]] = {
        "en": "{verb} {description}",
        "zh": "{verb}{description}",
    }

    VERBS: Final[Dict[str, Dict[str, str]]] = {
        "en": {
            CommitType.FEAT.value: "add",
            CommitType.FIX.value: "fix",
            CommitType.DOCS.value: "update",
            CommitType.REFACTOR.value: "refactor",
            CommitType.TEST.value: "add tests for",
            CommitType.CHORE.value: "update",
            CommitType.CI.value: "update CI configuration for",
            CommitType.PERF.value: "improve performance of",
            CommitType.STYLE.value: "format",
            CommitType.BUILD.value: "update build configuration for",
            CommitType.REVERT.value: "revert",
        },
        "zh": {
            CommitType.FEAT.value: "新增",
            CommitType.FIX.value: "修复",
            CommitType.DOCS.value: "更新文档",
            CommitType.REFACTOR.value: "重构",
            CommitType.TEST.value: "补充测试",
            CommitType.CHORE.value: "更新",
            CommitType.CI.value: "更新CI配置",
            CommitType.PERF.value: "优化性能",
            CommitType.STYLE.value: "格式化",
            CommitType.BUILD.value: "更新构建配置",
            CommitType.REVERT.value: "回滚",
        },
    }

    DESCRIPTION_TEMPLATES: Final[Dict[str, str]] = {
        "en": "{scope_prefix}{change_summary}",
        "zh": "{scope_prefix}{change_summary}",
    }

    BODY_TEMPLATE: Final[Dict[str, str]] = {
        "en": (
            "## Summary\n\n"
            "{change_summary}\n\n"
            "### Changes\n\n"
            "{file_list}\n\n"
            "### Details\n\n"
            "Files changed: {file_count} | "
            "Additions: {additions} | "
            "Deletions: {deletions}"
        ),
        "zh": (
            "## 变更摘要\n\n"
            "{change_summary}\n\n"
            "### 变更文件\n\n"
            "{file_list}\n\n"
            "### 统计\n\n"
            "修改文件: {file_count} | "
            "新增行: {additions} | "
            "删除行: {deletions}"
        ),
    }

    FOOTER_TEMPLATE: Final[Dict[str, str]] = {
        "en": "Reviewed-by: ai-commit v{version}",
        "zh": "Reviewed-by: ai-commit v{version}",
    }

    BREAKING_FOOTER: Final[str] = "BREAKING CHANGE: {description}"

    def __init__(self, config: Config) -> None:
        """Initialize the message generator.

        Args:
            config: Application configuration (language, style settings).
        """
        self._config: Config = config
        self._lang: str = config.language

    def generate(
        self,
        diff_files: List[DiffFile],
        commit_type: CommitType,
        scope: Optional[str] = None,
        functions: Optional[List[str]] = None,
        is_breaking: bool = False,
    ) -> CommitMessage:
        """Generate a complete CommitMessage from diff analysis.

        Args:
            diff_files: Parsed diff file objects.
            commit_type: The detected commit type.
            scope: Optional scope string.
            functions: List of extracted function/class names.
            is_breaking: Whether the change is breaking.

        Returns:
            A fully populated CommitMessage.
        """
        # Build a summary of changes
        change_summary: str = self._build_change_summary(diff_files, functions)
        subject: str = self._build_subject(commit_type, change_summary, scope)
        file_list_text: str = self._build_file_list(diff_files)

        total_added: int = sum(f.total_added for f in diff_files)
        total_removed: int = sum(f.total_removed for f in diff_files)

        body: str = self.BODY_TEMPLATE[self._lang].format(
            change_summary=change_summary,
            file_list=file_list_text,
            file_count=len(diff_files),
            additions=total_added,
            deletions=total_removed,
        )

        footer: str = self.FOOTER_TEMPLATE[self._lang].format(version=VERSION)

        if is_breaking:
            breaking_desc: str = self._build_breaking_description(diff_files)
            if self._lang == "zh":
                footer = f"{footer}\n\nBREAKING CHANGE: {breaking_desc}"
            else:
                footer = f"{footer}\n\nBREAKING CHANGE: {breaking_desc}"

        return CommitMessage(
            commit_type=commit_type,
            scope=scope,
            subject=subject,
            body=body,
            footer=footer,
            breaking=is_breaking,
        )

    def generate_subject_only(
        self,
        diff_files: List[DiffFile],
        commit_type: CommitType,
        scope: Optional[str] = None,
        functions: Optional[List[str]] = None,
    ) -> str:
        """Generate just the subject line of a commit message.

        Args:
            diff_files: Parsed diff file objects.
            commit_type: The detected commit type.
            scope: Optional scope string.
            functions: List of extracted function/class names.

        Returns:
            A single-line subject string.
        """
        change_summary = self._build_change_summary(diff_files, functions)
        return self._build_subject(commit_type, change_summary, scope)

    # -- Private helpers ---------------------------------------------------

    def _build_subject(
        self,
        commit_type: CommitType,
        change_summary: str,
        scope: Optional[str] = None,
    ) -> str:
        """Construct the subject line from components.

        Args:
            commit_type: The commit type.
            change_summary: A brief description of the change.
            scope: Optional scope.

        Returns:
            The formatted subject line.
        """
        verb: str = self.VERBS.get(self._lang, self.VERBS["en"]).get(
            commit_type.value, "update"
        )

        if self._lang == "zh":
            subject: str = f"{verb}{change_summary}"
        else:
            subject: str = f"{verb} {change_summary}"

        # Truncate to max length
        if len(subject) > self._config.max_subject_length:
            subject = subject[: self._config.max_subject_length - 3].rstrip() + "..."

        return subject

    def _build_change_summary(
        self,
        diff_files: List[DiffFile],
        functions: Optional[List[str]] = None,
    ) -> str:
        """Build a human-readable summary of the changes.

        Args:
            diff_files: Parsed diff file objects.
            functions: Extracted function/class names.

        Returns:
            A summary string.
        """
        file_count: int = len(diff_files)

        if functions:
            func_str: str = ", ".join(functions[:5])
            if len(functions) > 5:
                if self._lang == "zh":
                    func_str += f" 等 {len(functions)} 个"
                else:
                    func_str += f" and {len(functions) - 5} more"
            if self._lang == "zh":
                return f"{func_str}"
            return f"{func_str}"

        # No functions detected — summarize by file paths
        paths: List[str] = [f.display_path for f in diff_files]

        if file_count == 1:
            return Path(paths[0]).name

        # Try to find common prefix
        try:
            common: str = os.path.commonpath(paths)
            if common and common != ".":
                if self._lang == "zh":
                    return f"{common} 中的 {file_count} 个文件"
                return f"{file_count} files in {common}"
        except ValueError:
            pass

        if self._lang == "zh":
            return f"{file_count} 个文件"
        return f"{file_count} files"

    def _build_file_list(self, diff_files: List[DiffFile]) -> str:
        """Build a formatted file list for the body.

        Args:
            diff_files: Parsed diff file objects.

        Returns:
            A bulleted list of file paths with change stats.
        """
        lines: List[str] = []
        for f in diff_files:
            status_symbol: str = {
                "added": "+",
                "deleted": "-",
                "renamed": "~",
                "modified": "M",
            }.get(f.status, "M")
            added_str: str = f"+{f.total_added}" if f.total_added else ""
            removed_str: str = f"-{f.total_removed}" if f.total_removed else ""
            stats: str = f" ({added_str}{removed_str})".strip() if (added_str or removed_str) else ""
            lines.append(f"  - {status_symbol} {f.display_path}{stats}")
        return "\n".join(lines)

    def _build_breaking_description(self, diff_files: List[DiffFile]) -> str:
        """Build a description of breaking changes.

        Args:
            diff_files: Parsed diff file objects.

        Returns:
            A description of what breaking changes were detected.
        """
        removed_apis: List[str] = []
        for f in diff_files:
            for hunk in f.hunks:
                for line in hunk.content:
                    match: Optional[Match[str]] = re.search(
                        r"\b(def |function |pub (fn|struct|enum|trait) )(\w+)",
                        line,
                    )
                    if match and line.startswith("-"):
                        removed_apis.append(match.group(3))

        if removed_apis:
            unique: List[str] = sorted(set(removed_apis))
            if self._lang == "zh":
                return f"移除了公共 API: {', '.join(unique[:5])}"
            return f"Removed public API: {', '.join(unique[:5])}"

        if self._lang == "zh":
            return "此变更可能破坏向后兼容性"
        return "This change may break backward compatibility"


# ---------------------------------------------------------------------------
# InteractiveEditor
# ---------------------------------------------------------------------------


class InteractiveEditor:
    """Provides interactive editing and confirmation of commit messages.

    Uses the rich library for terminal output and the system editor
    for multi-line body editing.
    """

    def __init__(self, config: Config) -> None:
        """Initialize the interactive editor.

        Args:
            config: Application configuration.
        """
        self._config: Config = config
        self._console: Console = Console() if RICH_AVAILABLE else None  # type: ignore[arg-type]

    def confirm_message(self, message: CommitMessage) -> Optional[CommitMessage]:
        """Present the commit message to the user and allow editing.

        Shows the proposed message, asks for confirmation, and provides
        options to edit the subject, body, scope, or type.

        Args:
            message: The proposed CommitMessage.

        Returns:
            The confirmed/edited CommitMessage, or None if the user
            cancels the commit.
        """
        if not RICH_AVAILABLE:
            return self._simple_confirm(message)

        self._display_message(message)

        while True:
            action: str = Prompt.ask(
                "\n[bold]Action[/bold]",
                default="yes",
                choices=[
                    "yes",
                    "edit",
                    "type",
                    "scope",
                    "subject",
                    "body",
                    "retry",
                    "abort",
                ],
            )

            action = action.strip().lower()

            if action in ("yes", "y", ""):
                return message

            if action in ("abort", "a"):
                self._console.print("[yellow]Commit aborted by user.[/yellow]")
                return None

            if action in ("retry", "r"):
                return None  # Signal caller to retry generation

            if action in ("edit", "e"):
                edited: Optional[CommitMessage] = self._edit_in_editor(message)
                if edited is not None:
                    message = edited
                    self._display_message(message)
                continue

            if action in ("type", "t"):
                new_type: Optional[CommitType] = self._edit_type(message.commit_type)
                if new_type is not None:
                    message.commit_type = new_type
                    self._display_message(message)
                continue

            if action in ("scope", "s"):
                new_scope: Optional[str] = self._edit_scope(message.scope)
                if new_scope is not None:
                    message.scope = new_scope if new_scope else None
                    self._display_message(message)
                continue

            if action in ("subject", "subj"):
                new_subject: Optional[str] = self._edit_subject(message.subject)
                if new_subject is not None:
                    message.subject = new_subject
                    self._display_message(message)
                continue

            if action in ("body", "b"):
                new_body: Optional[str] = self._edit_body(message.body)
                if new_body is not None:
                    message.body = new_body
                    self._display_message(message)
                continue

    def edit_message(self, message: CommitMessage) -> CommitMessage:
        """Open the full message in the system editor.

        Args:
            message: The CommitMessage to edit.

        Returns:
            The edited CommitMessage.
        """
        edited: Optional[CommitMessage] = self._edit_in_editor(message)
        return edited if edited is not None else message

    def show_summary(
        self,
        files: List[DiffFile],
        functions: List[str],
        commit_type: CommitType,
        scope: Optional[str],
    ) -> None:
        """Display a summary of the diff analysis.

        Args:
            files: Parsed diff file objects.
            functions: Extracted function names.
            commit_type: Detected commit type.
            scope: Detected scope (if any).
        """
        if not RICH_AVAILABLE:
            return

        self._console.print()
        self._console.print(Rule("[bold blue]Diff Analysis Summary"))
        self._console.print()

        # File table
        table = Table(
            title="Changed Files",
            box=box.ROUNDED,
            title_style="bold",
        )
        table.add_column("File", style="cyan")
        table.add_column("Status", style="yellow")
        table.add_column("+", style="green")
        table.add_column("-", style="red")

        for f in files:
            table.add_row(
                f.display_path,
                f.status,
                str(f.total_added) if f.total_added > 0 else "",
                str(f.total_removed) if f.total_removed > 0 else "",
            )
        self._console.print(table)

        # Functions
        if functions:
            func_text: Text = Text(", ".join(functions))
            func_text.stylize("bold magenta")
            self._console.print(Panel(func_text, title="Changed Functions"))

        # Type & scope
        type_text = Text(str(commit_type.value))
        type_text.stylize("bold green")
        scope_text = Text(scope or "(none)")
        scope_text.stylize("bold yellow")

        info_table = Table(box=box.SIMPLE, show_header=False)
        info_table.add_column("Key", style="bold")
        info_table.add_column("Value")
        info_table.add_row("Commit Type", commit_type.label)
        info_table.add_row("Scope", scope or "(none)")
        info_table.add_row("Functions", str(len(functions)))
        info_table.add_row("Files", str(len(files)))
        self._console.print(info_table)

    # -- Private helpers ---------------------------------------------------

    def _display_message(self, message: CommitMessage) -> None:
        """Display the formatted commit message in a panel.

        Args:
            message: The CommitMessage to display.
        """
        full_text: str = message.formatted
        self._console.print()
        self._console.print(
            Panel(
                Syntax(full_text, "git-rebase", theme="default"),
                title="[bold green]Proposed Commit Message",
                border_style="green",
            )
        )
        self._console.print()

    def _edit_subject(self, current: str) -> Optional[str]:
        """Prompt the user to edit the subject line.

        Args:
            current: The current subject text.

        Returns:
            The new subject, or None if unchanged.
        """
        result: str = Prompt.ask("[bold]Subject[/bold]", default=current)
        return result if result != current else None

    def _edit_scope(self, current: Optional[str]) -> Optional[str]:
        """Prompt the user to edit the scope.

        Args:
            current: The current scope value.

        Returns:
            The new scope, or None if unchanged.
        """
        default: str = current or ""
        result: str = Prompt.ask("[bold]Scope[/bold]", default=default)
        if result == default:
            return None
        return result if result else ""

    def _edit_type(self, current: CommitType) -> Optional[CommitType]:
        """Prompt the user to change the commit type.

        Args:
            current: The current commit type.

        Returns:
            The new CommitType, or None if unchanged.
        """
        choices: str = ", ".join(m.value for m in CommitType)
        result: str = Prompt.ask(
            f"[bold]Commit type[/bold] ({choices})",
            default=current.value,
        )
        try:
            new_type: CommitType = CommitType.from_string(result)
            return new_type if new_type != current else None
        except ValueError:
            self._console.print("[red]Invalid commit type, keeping current.[/red]")
            return None

    def _edit_body(self, current: Optional[str]) -> Optional[str]:
        """Prompt the user to edit the body text.

        Args:
            current: The current body text.

        Returns:
            The new body, or None if unchanged.
        """
        if not current:
            current = ""
        lines: List[str] = current.split("\n")

        self._console.print("[bold]Current body:[/bold]")
        for line in lines:
            self._console.print(f"  {line}")

        self._console.print("\n[bold]Enter new body[/bold] (type 'END' on a new line to finish):")
        new_lines: List[str] = []

        try:
            while True:
                line: str = input()
                if line.strip().upper() == "END":
                    break
                new_lines.append(line)
        except (EOFError, KeyboardInterrupt):
            self._console.print("\n[yellow]Body edit cancelled.[/yellow]")
            return None

        new_body: str = "\n".join(new_lines)
        if new_body == current:
            return None
        return new_body if new_body else None

    def _edit_in_editor(self, message: CommitMessage) -> Optional[CommitMessage]:
        """Open the commit message in the system editor.

        Writes the message to a temp file, opens the editor, and
        reads the result.

        Args:
            message: The CommitMessage to edit.

        Returns:
            The edited CommitMessage, or None if cancelled.
        """
        editor: str = os.environ.get("EDITOR", os.environ.get("VISUAL", ""))
        if not editor:
            self._console.print(
                "[yellow]No EDITOR or VISUAL set in environment. "
                "Falling back to subject/body editing.[/yellow]"
            )
            # Fallback: edit subject and body separately
            new_subject: Optional[str] = self._edit_subject(message.subject)
            new_body: Optional[str] = self._edit_body(message.body)
            if new_subject is not None:
                message.subject = new_subject
            if new_body is not None:
                message.body = new_body
            return message

        content: str = message.formatted
        content += (
            "\n\n"
            "# Everything below this line is ignored.\n"
            "# Edit the message above. Lines starting with '#' are stripped.\n"
        )

        try:
            with tempfile.NamedTemporaryFile(
                mode="w+",
                suffix=".txt",
                delete=False,
                encoding="utf-8",
            ) as tmp:
                tmp_path: str = tmp.name
                tmp.write(content)

            # Open the editor
            subprocess.run([editor, tmp_path], check=True)

            # Read the result
            edited_content: str = Path(tmp_path).read_text(encoding="utf-8")

            # Strip comment lines and leading/trailing whitespace
            clean_lines: List[str] = [
                line for line in edited_content.splitlines()
                if not line.startswith("#")
            ]
            clean_text: str = "\n".join(clean_lines).strip()

            # Parse the result into a CommitMessage
            if clean_text:
                parsed: CommitMessage = self._parse_edited_message(message, clean_text)
                return parsed

        except (OSError, subprocess.CalledProcessError) as exc:
            self._console.print(f"[red]Editor error: {exc}[/red]")
            return None
        finally:
            # Clean up temp file
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass

        return None

    @staticmethod
    def _parse_edited_message(
        original: CommitMessage,
        edited_text: str,
    ) -> CommitMessage:
        """Parse an edited message string back into a CommitMessage.

        Args:
            original: The original CommitMessage (for fallback values).
            edited_text: The user-edited text.

        Returns:
            A new CommitMessage with the edited values.
        """
        lines: List[str] = edited_text.splitlines()
        if not lines:
            return original

        header: str = lines[0]

        # Try to parse header: type(scope)!: subject
        header_pattern: Pattern[str] = re.compile(
            r"^(\w+)(?:\(([^)]+)\))?(!)?\s*:\s*(.+)$"
        )
        match: Optional[Match[str]] = header_pattern.match(header)

        if match:
            raw_type: str = match.group(1)
            raw_scope: Optional[str] = match.group(2)
            breaking: bool = match.group(3) == "!"
            subject: str = match.group(4)

            try:
                commit_type: CommitType = CommitType.from_string(raw_type)
            except ValueError:
                commit_type = original.commit_type

            # Remaining lines are body + footer
            remaining: str = "\n".join(lines[1:]).strip()
            body: Optional[str] = None
            footer: Optional[str] = None

            if remaining:
                # Split on first blank line to separate body from footer
                parts: List[str] = re.split(r"\n\n+", remaining, maxsplit=1)
                body = parts[0].strip() if parts else None
                footer = parts[1].strip() if len(parts) > 1 else None

            return CommitMessage(
                commit_type=commit_type,
                scope=raw_scope,
                subject=subject,
                body=body or original.body,
                footer=footer or original.footer,
                breaking=breaking or original.breaking,
                raw_diff=original.raw_diff,
            )

        # Fallback: treat the whole thing as a subject
        return CommitMessage(
            commit_type=original.commit_type,
            scope=original.scope,
            subject=edited_text[:MAX_SUBJECT_LENGTH],
            body=original.body,
            footer=original.footer,
            breaking=original.breaking,
            raw_diff=original.raw_diff,
        )

    @staticmethod
    def _simple_confirm(message: CommitMessage) -> Optional[CommitMessage]:
        """Fallback confirmation when rich is not available.

        Args:
            message: The proposed CommitMessage.

        Returns:
            The confirmed message, or None if cancelled.
        """
        print("\n=== Proposed Commit Message ===")
        print(message.formatted)
        print("\n================================")

        try:
            response: str = input("\nConfirm? (Y/n/e/d/a): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return None

        if response in ("", "y", "yes"):
            return message
        if response in ("e", "edit"):
            print("Edit mode not available without rich library.")
            return message
        if response in ("a", "abort"):
            print("Aborted.")
            return None

        return message


# ---------------------------------------------------------------------------
# AICommitCLI
# ---------------------------------------------------------------------------


class AICommitCLI:
    """Main CLI orchestrator for the ai-commit tool.

    Coordinates diff analysis, commit type detection, function extraction,
    message generation, and interactive editing.
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        """Initialize the CLI orchestrator.

        Args:
            config: Optional Config instance. If None, auto-loads.
        """
        self._config: Config = config or Config()
        self._git: GitHelper = GitHelper()
        self._parser: DiffParser = DiffParser()
        self._detector: CommitTypeDetector = CommitTypeDetector()
        self._extractor: FunctionExtractor = FunctionExtractor()
        self._generator: MessageGenerator = MessageGenerator(self._config)
        self._editor: InteractiveEditor = InteractiveEditor(self._config)
        self._console: Optional[Console] = Console() if RICH_AVAILABLE else None

    def run(self, args: argparse.Namespace) -> int:
        """Execute the CLI workflow based on parsed arguments.

        Args:
            args: Parsed command-line arguments.

        Returns:
            Exit code (0 for success, 1 for failure).
        """
        # Handle subcommands
        if hasattr(args, "func"):
            return args.func(args)

        # Default: generate commit message
        return self._generate_and_commit(args)

    def _generate_and_commit(self, args: argparse.Namespace) -> int:
        """Full workflow: analyze, generate, confirm, and commit.

        Args:
            args: Parsed command-line arguments.

        Returns:
            Exit code.
        """
        # Check for staged changes
        if not self._git.has_staged_changes():
            message: str = "No staged changes found. Stage your changes with 'git add' first."
            if self._console:
                self._console.print(f"[red]:warning:  {message}[/red]")
            else:
                print(f"Error: {message}", file=sys.stderr)
            return 1

        # Get diff
        raw_diff: str = self._git.get_staged_diff(
            context_lines=args.context_lines or self._config.diff_context_lines
        )

        # Parse diff
        diff_files: List[DiffFile] = self._parser.parse(raw_diff)

        if not diff_files:
            if self._console:
                self._console.print("[yellow]No changes detected in staged files.[/yellow]")
            else:
                print("No changes detected in staged files.")
            return 0

        # Detect type and scope
        commit_type: CommitType = (
            CommitType.from_string(args.type)
            if args.type
            else self._detector.detect(diff_files, raw_diff)
        )
        scope: Optional[str] = args.scope or self._detector.detect_scope(diff_files)
        is_breaking: bool = self._detector.detect_breaking_change(diff_files)

        # Extract functions
        language_hint: Optional[str] = None
        if hasattr(args, "language") and args.language:
            language_hint = args.language
        functions: List[str] = self._extractor.extract(diff_files, language_hint)

        # Show summary
        if not args.quiet:
            self._editor.show_summary(diff_files, functions, commit_type, scope)

        # Generate message
        message: CommitMessage = self._generator.generate(
            diff_files=diff_files,
            commit_type=commit_type,
            scope=scope,
            functions=functions,
            is_breaking=is_breaking,
        )
        message.raw_diff = raw_diff

        # If --dry-run, print and exit
        if args.dry_run:
            if self._console:
                self._console.print(
                    Panel(
                        Syntax(message.formatted, "git-rebase", theme="default"),
                        title="[bold]Generated Commit Message (dry-run)",
                        border_style="blue",
                    )
                )
            else:
                print(message.formatted)
            return 0

        # If --subject-only, print just the subject
        if args.subject_only:
            print(message.one_line)
            return 0

        # If --output, write to file
        if args.output:
            output_path: Path = Path(args.output)
            output_path.write_text(message.formatted, encoding="utf-8")
            if self._console:
                self._console.print(f"[green]Message written to {output_path}[/green]")
            return 0

        # Interactive confirmation
        if not args.yes:
            confirmed: Optional[CommitMessage] = self._editor.confirm_message(message)
            if confirmed is None:
                return 0  # User cancelled or wants retry
            message = confirmed

        # Commit
        if not args.no_commit:
            try:
                result: str = self._git.commit(message.formatted)
                if self._console:
                    self._console.print(f"[green]:white_check_mark:  Commit successful[/green]")
                    # Print the commit summary
                    for line in result.splitlines():
                        if line.strip():
                            self._console.print(f"  {line}")
                else:
                    print(result)
            except GitError as exc:
                if self._console:
                    self._console.print(f"[red]Commit failed: {exc}[/red]")
                else:
                    print(f"Commit failed: {exc}", file=sys.stderr)
                return 1
        else:
            if self._console:
                self._console.print(
                    Panel(message.formatted, title="[yellow]Message (not committed)"))
            else:
                print(message.formatted)

        return 0

    # -- Subcommand handlers -----------------------------------------------

    def _cmd_init(self, args: argparse.Namespace) -> int:
        """Initialize a config file in the current directory.

        Args:
            args: Parsed command-line arguments.

        Returns:
            Exit code.
        """
        config_path: Path = Path.cwd() / CONFIG_FILE_NAME
        if config_path.exists() and not args.force:
            if self._console:
                self._console.print(
                    f"[yellow]{CONFIG_FILE_NAME} already exists. Use --force to overwrite.[/yellow]"
                )
            else:
                print(f"{CONFIG_FILE_NAME} already exists. Use --force to overwrite.")
            return 1

        self._config.save(config_path)
        if self._console:
            self._console.print(f"[green]Created {config_path}[/green]")
        else:
            print(f"Created {config_path}")
        return 0

    def _cmd_show_config(self, args: argparse.Namespace) -> int:
        """Display the current configuration.

        Args:
            args: Parsed command-line arguments.

        Returns:
            Exit code.
        """
        data: Dict[str, Any] = self._config.to_dict()
        if self._console:
            table = Table(title="Current Configuration", box=box.ROUNDED)
            table.add_column("Key", style="bold cyan")
            table.add_column("Value", style="yellow")
            for key, value in data.items():
                table.add_row(key, str(value))
            self._console.print(table)
        else:
            for key, value in data.items():
                print(f"{key}: {value}")
        return 0

    def _cmd_show_diff(self, args: argparse.Namespace) -> int:
        """Show the parsed diff summary.

        Args:
            args: Parsed command-line arguments.

        Returns:
            Exit code.
        """
        if not self._git.has_staged_changes():
            if self._console:
                self._console.print("[red]No staged changes found.[/red]")
            else:
                print("No staged changes found.")
            return 1

        raw_diff: str = self._git.get_staged_diff(
            context_lines=args.context_lines or self._config.diff_context_lines
        )
        diff_files: List[DiffFile] = self._parser.parse(raw_diff)

        if not diff_files:
            if self._console:
                self._console.print("[yellow]No changes to display.[/yellow]")
            return 0

        self._editor.show_summary(
            files=diff_files,
            functions=self._extractor.extract(diff_files),
            commit_type=self._detector.detect(diff_files, raw_diff),
            scope=self._detector.detect_scope(diff_files),
        )
        return 0


# ---------------------------------------------------------------------------
# CLI Argument Parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the ai-commit CLI.

    Returns:
        A configured ArgumentParser instance.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="AI-powered git commit message generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              %(prog)s                     # Generate and commit
              %(prog)s --dry-run           # Preview without committing
              %(prog)s --subject-only      # Print only the subject line
              %(prog)s --type feat         # Override commit type
              %(prog)s --scope auth        # Override scope
              %(prog)s --no-commit         # Generate message only
              %(prog)s --lang zh           # Use Chinese output
              %(prog)s init                # Create config file
              %(prog)s show-config         # Display current config
              %(prog)s diff                # Show diff analysis
        """),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )

    # Global options
    parser.add_argument(
        "--type", "-t",
        choices=[t.value for t in CommitType],
        help="Override the detected commit type",
    )
    parser.add_argument(
        "--scope", "-s",
        help="Override the detected scope",
    )
    parser.add_argument(
        "--lang", "-l",
        choices=sorted(SUPPORTED_LANGUAGES),
        default=None,
        help="Output language (default: from config or en)",
    )
    parser.add_argument(
        "--context-lines", "-C",
        type=int,
        default=None,
        help="Number of context lines in diff (default: 5)",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Generate message without committing (alias for --no-commit --quiet)",
    )
    parser.add_argument(
        "--no-commit",
        action="store_true",
        help="Generate message but do not commit",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress diff analysis summary",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Write commit message to a file instead of committing",
    )
    parser.add_argument(
        "--subject-only",
        action="store_true",
        help="Print only the subject line",
    )

    # Subcommands
    subparsers = parser.add_subparsers(title="Commands")

    # init
    init_parser = subparsers.add_parser("init", help="Create a config file")
    init_parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Overwrite existing config file",
    )
    init_parser.set_defaults(func=lambda a: None)  # placeholder

    # show-config
    show_config_parser = subparsers.add_parser(
        "show-config", help="Show current configuration"
    )
    show_config_parser.set_defaults(func=lambda a: None)

    # diff
    diff_parser = subparsers.add_parser("diff", help="Show parsed diff analysis")
    diff_parser.add_argument(
        "--context-lines", "-C",
        type=int,
        default=None,
        help="Number of context lines in diff",
    )
    diff_parser.set_defaults(func=lambda a: None)

    return parser


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point for the ai-commit CLI.

    Args:
        argv: Command-line argument list. If None, uses sys.argv[1:].

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    parser: argparse.ArgumentParser = build_parser()
    args: argparse.Namespace = parser.parse_args(argv)

    # Load config (with language override if provided)
    config: Config = Config()
    if args.lang:
        config.language = args.lang

    # Handle subcommands
    if hasattr(args, "func"):
        cli: AICommitCLI = AICommitCLI(config)
        if args.func is not None:
            # Map subcommand to handler
            if args.func.__name__ == "<lambda>":
                subcommand_map: Dict[str, str] = {
                    "init": "_cmd_init",
                    "show-config": "_cmd_show_config",
                    "diff": "_cmd_show_diff",
                }
                # Find which subcommand was invoked
                cmd_args: List[str] = argv if argv is not None else sys.argv[1:]
                invoked: str = cmd_args[0] if cmd_args else ""
                handler_name: Optional[str] = subcommand_map.get(invoked)
                if handler_name:
                    handler = getattr(cli, handler_name, None)
                    if handler:
                        return handler(args)

    # Default: run the full workflow
    cli = AICommitCLI(config)
    return cli._generate_and_commit(args)


if __name__ == "__main__":
    sys.exit(main())