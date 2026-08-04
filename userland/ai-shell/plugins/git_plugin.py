"""
Git integration plugin for Ainos Shell.

Provides enhanced Git integration:
- Git status in prompt
- Git command shortcuts
- Branch switching helpers
- Status summaries
- Git-aware tab completion
- Auto-fetch status for prompt
"""

from __future__ import annotations

import os
import re
import subprocess
import typing as t
from dataclasses import dataclass, field

from ..src.plugins import Plugin, PluginInfo, HookType, PluginContext
from ..src.utils import AnsiCode, colorize


@dataclass
class GitStatus:
    """Git repository status information."""
    branch: str = ""
    ahead: int = 0
    behind: int = 0
    staged: int = 0
    modified: int = 0
    deleted: int = 0
    untracked: int = 0
    conflicts: int = 0
    stashes: int = 0
    is_detached: bool = False
    has_remote: bool = False
    last_commit_time: str = ""
    last_commit_msg: str = ""

    @property
    def is_dirty(self) -> bool:
        return (self.staged + self.modified + self.deleted + self.untracked) > 0

    @property
    def is_clean(self) -> bool:
        return not self.is_dirty

    @property
    def short_status(self) -> str:
        if self.is_clean:
            return f"{self.branch} ✓"
        return f"{self.branch} ✗{self.modified + self.staged}"

    def __repr__(self) -> str:
        return f"GitStatus(branch={self.branch}, dirty={self.is_dirty})"


class GitPlugin(Plugin):
    """Git integration plugin."""

    info = PluginInfo(
        name="git",
        version="1.0.0",
        description="Git integration for prompt and shortcuts",
        author="Ainos Team",
        tags=["git", "vcs", "prompt"],
        priority=50,
    )

    def __init__(self, context: t.Optional[PluginContext] = None) -> None:
        super().__init__(context)
        self._status_cache: t.Dict[str, t.Tuple[float, GitStatus]] = {}
        self._cache_ttl = 2.0  # seconds

        # Register hooks
        self.on_pre_prompt(self._update_prompt_git)

    def initialize(self) -> None:
        """Initialize the plugin."""
        self.set_config("show_in_prompt", True)
        self.set_config("auto_fetch", False)
        self.set_config("fetch_interval", 60)

    def get_status(self, path: t.Optional[str] = None) -> GitStatus:
        """Get the git status for a directory."""
        import time
        cwd = path or os.getcwd()

        # Check cache
        if cwd in self._status_cache:
            cached_time, cached_status = self._status_cache[cwd]
            if time.time() - cached_time < self._cache_ttl:
                return cached_status

        status = GitStatus()

        try:
            # Check if in git repo
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=cwd, capture_output=True, text=True, timeout=2
            )
            if result.returncode != 0:
                return status

            # Get branch name
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=cwd, capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                branch = result.stdout.strip()
                if branch == "HEAD":
                    status.is_detached = True
                    result = subprocess.run(
                        ["git", "rev-parse", "--short", "HEAD"],
                        cwd=cwd, capture_output=True, text=True, timeout=2
                    )
                    status.branch = result.stdout.strip() if result.returncode == 0 else "(detached)"
                else:
                    status.branch = branch

            # Get full status
            result = subprocess.run(
                ["git", "status", "--porcelain", "-b"],
                cwd=cwd, capture_output=True, text=True, timeout=2
            )

            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    if line.startswith("##"):
                        # Branch line - check ahead/behind
                        m = re.search(r"ahead (\d+)", line)
                        if m:
                            status.ahead = int(m.group(1))
                        m = re.search(r"behind (\d+)", line)
                        if m:
                            status.behind = int(m.group(1))
                        if "..." in line:
                            status.has_remote = True
                        continue

                    if line.startswith("??"):
                        status.untracked += 1
                    elif line.startswith("UU") or line.startswith("AA"):
                        status.conflicts += 1
                    elif line[0] != " " and line[0] != "?":
                        status.staged += 1
                    elif line[1] != " " and line[1] != "?":
                        status.modified += 1

            # Get stash count
            result = subprocess.run(
                ["git", "stash", "list"],
                cwd=cwd, capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                status.stashes = len([l for l in result.stdout.strip().split("\n") if l.strip()])

            # Get last commit info
            result = subprocess.run(
                ["git", "log", "-1", "--format=%ar|%s"],
                cwd=cwd, capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split("|", 1)
                if len(parts) == 2:
                    status.last_commit_time = parts[0]
                    status.last_commit_msg = parts[1]

            # Cache the result
            self._status_cache[cwd] = (time.time(), status)

        except (subprocess.SubprocessError, FileNotFoundError, OSError, TimeoutError):
            pass

        return status

    def _update_prompt_git(self) -> None:
        """Update git status for prompt display (called before prompt)."""
        # This is handled by the prompt renderer, but we keep the cache warm
        if self.get_config("show_in_prompt", True):
            self.get_status()

    def get_shortcuts(self) -> t.Dict[str, str]:
        """Get git command shortcuts."""
        return {
            "gs": "git status",
            "ga": "git add",
            "gc": "git commit",
            "gcm": "git commit -m",
            "gp": "git push",
            "gpl": "git pull",
            "gd": "git diff",
            "gco": "git checkout",
            "gb": "git branch",
            "gl": "git log --oneline --graph --decorate",
            "gst": "git stash",
            "gsta": "git stash apply",
            "gstp": "git stash pop",
            "gcl": "git clone",
            "gfa": "git fetch --all",
            "grh": "git reset HEAD",
            "grhh": "git reset --hard HEAD",
            "gcp": "git cherry-pick",
            "gbl": "git blame",
        }

    def activate(self) -> None:
        """Activate the plugin."""
        super().activate()
        # Register git command shortcuts as aliases
        from ..src.config import set_alias
        for shortcut, command in self.get_shortcuts().items():
            set_alias(shortcut, command)

    def deactivate(self) -> None:
        """Deactivate the plugin."""
        super().deactivate()
        # Remove git shortcuts
        from ..src.config import unset_alias
        for shortcut in self.get_shortcuts().keys():
            unset_alias(shortcut)

    def __repr__(self) -> str:
        return f"GitPlugin(active={self.is_active})"