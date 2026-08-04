"""
Prompt rendering for Ainos Shell.

Renders the shell prompt with:
- Current directory path (with color)
- Git branch and status
- AI assistant status
- Virtual environment indicator
- Background job count
- Exit code of last command
- Timestamp
- Configurable themes
- Powerline-style segments
- Multi-line prompt support
- Right-aligned prompt (RPROMPT)
"""

from __future__ import annotations

import os
import re
import subprocess
import typing as t
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .utils import (
    IS_WINDOWS,
    IS_POSIX,
    AnsiCode,
    colorize,
    terminal_width,
    get_home_dir,
    get_config,
)
from .themes import (
    Theme,
    ColorScheme,
    get_theme_manager,
    render_prompt_segment,
)

# ---------------------------------------------------------------------------
# Git status cache
# ---------------------------------------------------------------------------

_git_status_cache: t.Dict[str, t.Any] = {}
_git_cache_time: float = 0
_GIT_CACHE_TTL = 2.0  # seconds


@dataclass
class GitStatus:
    """Git repository status."""
    branch: str = ""
    ahead: int = 0
    behind: int = 0
    staged: int = 0
    unstaged: int = 0
    untracked: int = 0
    stashes: int = 0
    has_conflicts: bool = False
    is_dirty: bool = False
    is_detached: bool = False

    @property
    def is_repo(self) -> bool:
        return bool(self.branch)

    @property
    def clean(self) -> bool:
        return self.staged == 0 and self.unstaged == 0 and self.untracked == 0

    def __repr__(self) -> str:
        return f"GitStatus(branch={self.branch}, dirty={self.is_dirty})"


def get_git_status(cwd: str) -> GitStatus:
    """Get the git status for the current directory."""
    global _git_status_cache, _git_cache_time

    # Check cache
    now = datetime.now().timestamp()
    if cwd in _git_status_cache and (now - _git_cache_time) < _GIT_CACHE_TTL:
        return _git_status_cache[cwd]

    status = GitStatus()

    try:
        # Check if we're in a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=cwd, capture_output=True, text=True, timeout=1
        )
        if result.returncode != 0:
            return status

        # Get branch name
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=1
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            if branch == "HEAD":
                status.is_detached = True
                result = subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    cwd=cwd, capture_output=True, text=True, timeout=1
                )
                status.branch = f"({result.stdout.strip()})" if result.returncode == 0 else "(detached)"
            else:
                status.branch = branch

        # Get status information
        result = subprocess.run(
            ["git", "status", "--porcelain", "-b"],
            cwd=cwd, capture_output=True, text=True, timeout=1
        )

        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            # Count staged, unstaged, untracked
            for line in lines:
                if not line.strip():
                    continue
                if line.startswith("##"):
                    # Branch line - check ahead/behind
                    match = re.search(r"ahead (\d+)", line)
                    if match:
                        status.ahead = int(match.group(1))
                    match = re.search(r"behind (\d+)", line)
                    if match:
                        status.behind = int(match.group(1))
                    continue

                if line.startswith("??"):
                    status.untracked += 1
                elif line[0] != " " and line[0] != "?":
                    status.staged += 1
                elif line[1] != " " and line[1] != "?":
                    status.unstaged += 1

                if "UU" in line[:2]:
                    status.has_conflicts = True

            status.is_dirty = status.staged > 0 or status.unstaged > 0 or status.untracked > 0

        # Get stash count
        result = subprocess.run(
            ["git", "stash", "list"],
            cwd=cwd, capture_output=True, text=True, timeout=1
        )
        if result.returncode == 0:
            stash_lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
            status.stashes = len(stash_lines)

        # Cache it
        _git_status_cache[cwd] = status
        _git_cache_time = now

    except (subprocess.SubprocessError, FileNotFoundError, OSError, TimeoutError):
        pass

    return status


# ---------------------------------------------------------------------------
# Prompt renderer
# ---------------------------------------------------------------------------

class PromptRenderer:
    """Renders the shell prompt with all configured elements."""

    def __init__(self) -> None:
        self._last_exit_code: int = 0
        self._ai_status: str = "ready"
        self._ai_loading: bool = False

    def set_last_exit_code(self, code: int) -> None:
        """Set the exit code of the last command."""
        self._last_exit_code = code

    def set_ai_status(self, status: str) -> None:
        """Set the AI assistant status."""
        self._ai_status = status

    def set_ai_loading(self, loading: bool) -> None:
        """Set whether AI is loading."""
        self._ai_loading = loading

    def render(self, theme: t.Optional[Theme] = None) -> str:
        """Render the main prompt."""
        if theme is None:
            theme = get_theme_manager().get_current_theme()

        colors = theme.colors
        cwd = os.getcwd()
        home = get_home_dir()

        # Format directory path
        dir_display = self._format_path(cwd, home, theme.show_full_path)

        # Build prompt segments
        segments: t.List[str] = []

        # User@host
        if theme.show_user or theme.show_hostname:
            segments.append(self._render_user_host(theme))

        # Directory
        segments.append(self._render_directory(dir_display, theme))

        # Git status
        if theme.show_git:
            git_status = get_git_status(cwd)
            if git_status.is_repo:
                segments.append(self._render_git(git_status, theme))

        # AI status
        if theme.show_ai:
            segments.append(self._render_ai(theme))

        # Virtual environment
        if theme.show_venv:
            venv = self._get_venv()
            if venv:
                segments.append(self._render_venv(venv, theme))

        # Background jobs
        if theme.show_jobs:
            jobs = self._get_job_count()
            if jobs > 0:
                segments.append(self._render_jobs(jobs, theme))

        # Time
        if theme.show_time:
            segments.append(self._render_time(theme))

        # Exit code
        if theme.show_exit_code:
            if self._last_exit_code != 0:
                segments.append(self._render_exit_code(theme))

        # Prompt character
        prompt_char = theme.prompt_char_root if os.geteuid() == 0 else theme.prompt_char
        segments.append(self._render_prompt_char(theme, prompt_char))

        # Join segments
        if theme.prompt_style == "powerline" and theme.use_powerline_symbols:
            prompt = self._render_powerline(segments, theme)
        else:
            prompt = " ".join(segments)

        # Add newline for multiline prompts
        if theme.show_newline:
            prompt = prompt + "\n"

        return prompt

    def render_rprompt(self, theme: t.Optional[Theme] = None) -> str:
        """Render the right-side prompt."""
        if theme is None:
            theme = get_theme_manager().get_current_theme()

        parts = []
        cwd = os.getcwd()

        # Time
        if theme.show_time:
            time_str = datetime.now().strftime("%H:%M:%S")
            parts.append(time_str)

        # Git status
        if theme.show_git:
            git_status = get_git_status(cwd)
            if git_status.is_repo:
                git_str = f"{git_status.branch}"
                if git_status.is_dirty:
                    git_str += " *"
                parts.append(git_str)

        if parts:
            rprompt = " ".join(parts)
            # Right-align
            width = terminal_width()
            visible_len = AnsiCode.len_without_ansi(rprompt)
            if visible_len < width:
                rprompt = " " * (width - visible_len) + rprompt
            return rprompt

        return ""

    def _render_powerline(self, segments: t.List[str], theme: Theme) -> str:
        """Render segments in powerline style with separators."""
        colors = theme.colors
        result = ""
        prev_bg = ""

        # Simplified powerline rendering
        for i, segment in enumerate(segments):
            if i < len(segments):
                result += segment + " "

        return result

    def _render_user_host(self, theme: Theme) -> str:
        """Render user@host segment."""
        import getpass
        colors = theme.colors
        user = getpass.getuser()
        host = os.uname().nodename if hasattr(os, 'uname') else os.environ.get('COMPUTERNAME', '')

        is_root = os.geteuid() == 0 if hasattr(os, 'geteuid') else False
        user_color = colors.root_fg if is_root else colors.user_fg

        user_str = colorize(user, colors.get_ansi(user_color))
        host_str = colorize(host, colors.get_ansi(colors.host_fg))

        return f"{user_str}@{host_str}"

    def _render_directory(self, display: str, theme: Theme) -> str:
        """Render directory segment."""
        colors = theme.colors
        dir_color = colors.get_ansi(colors.dir_fg)
        return colorize(display, dir_color, bold=True)

    def _render_git(self, git_status: GitStatus, theme: Theme) -> str:
        """Render git status segment."""
        colors = theme.colors

        if git_status.is_dirty:
            branch_color = colors.get_ansi(colors.git_dirty_fg)
        else:
            branch_color = colors.get_ansi(colors.git_branch_fg)

        branch = git_status.branch
        info = ""

        if git_status.ahead > 0 or git_status.behind > 0:
            arrows = []
            if git_status.ahead > 0:
                arrows.append(f"+{git_status.ahead}")
            if git_status.behind > 0:
                arrows.append(f"-{git_status.behind}")
            info = " " + "".join(arrows)

        if git_status.stashes > 0:
            info += f" S{git_status.stashes}"

        git_str = f"{branch}{info}"
        return colorize(git_str, branch_color)

    def _render_ai(self, theme: Theme) -> str:
        """Render AI status segment."""
        colors = theme.colors

        if self._ai_loading:
            status = "AI..."
            status_color = colors.get_ansi(colors.ai_loading_fg)
        elif self._ai_status == "ready":
            status = "AI"
            status_color = colors.get_ansi(colors.ai_ready_fg)
        else:
            status = f"AI:{self._ai_status}"
            status_color = colors.get_ansi(colors.ai_fg)

        return colorize(status, status_color)

    def _render_venv(self, venv_name: str, theme: Theme) -> str:
        """Render virtual environment segment."""
        colors = theme.colors
        return colorize(f"({venv_name})", colors.get_ansi(colors.info_fg))

    def _render_jobs(self, count: int, theme: Theme) -> str:
        """Render background job count segment."""
        colors = theme.colors
        return colorize(f"&{count}", colors.get_ansi(colors.warning_fg))

    def _render_time(self, theme: Theme) -> str:
        """Render time segment."""
        colors = theme.colors
        time_str = datetime.now().strftime("%H:%M:%S")
        return colorize(time_str, colors.get_ansi(colors.time_fg))

    def _render_exit_code(self, theme: Theme) -> str:
        """Render exit code segment."""
        colors = theme.colors
        return colorize(f"✗ {self._last_exit_code}", colors.get_ansi(colors.error_fg))

    def _render_prompt_char(self, theme: Theme, char: str) -> str:
        """Render the prompt character."""
        colors = theme.colors

        if self._last_exit_code == 0:
            char_color = colors.get_ansi(colors.prompt_fg)
        else:
            char_color = colors.get_ansi(colors.prompt_error_fg)

        return colorize(char, char_color, bold=True)

    def _format_path(self, cwd: str, home: str, show_full: bool = False) -> str:
        """Format the current directory path for display."""
        if show_full:
            return cwd

        # Try to show relative to home
        if cwd.startswith(home):
            rel = cwd[len(home):]
            if rel == "":
                return "~"
            return "~" + rel

        # Show last two components
        parts = cwd.replace("\\", "/").split("/")
        if len(parts) > 2:
            return ".../" + "/".join(parts[-2:])
        return cwd

    def _get_venv(self) -> t.Optional[str]:
        """Get the current virtual environment name."""
        venv = os.environ.get("VIRTUAL_ENV", "")
        if venv:
            return os.path.basename(venv)

        conda_env = os.environ.get("CONDA_DEFAULT_ENV", "")
        if conda_env:
            return conda_env

        return None

    def _get_job_count(self) -> int:
        """Get the number of background jobs."""
        try:
            from .executor import get_executor
            return len(get_executor().get_running_background())
        except Exception:
            return 0

    def render_continuation_prompt(self, theme: t.Optional[Theme] = None) -> str:
        """Render a continuation prompt for multi-line input."""
        if theme is None:
            theme = get_theme_manager().get_current_theme()

        char = theme.prompt_char_continuation
        prompt = " " * 3 + char + " "
        return prompt

    def to_dict(self) -> dict:
        return {
            "last_exit_code": self._last_exit_code,
            "ai_status": self._ai_status,
            "ai_loading": self._ai_loading,
        }


# ---------------------------------------------------------------------------
# Module-level access
# ---------------------------------------------------------------------------

_prompt_renderer: t.Optional[PromptRenderer] = None


def get_prompt_renderer() -> PromptRenderer:
    """Get the global prompt renderer singleton."""
    global _prompt_renderer
    if _prompt_renderer is None:
        _prompt_renderer = PromptRenderer()
    return _prompt_renderer


def render_prompt() -> str:
    """Render the shell prompt."""
    return get_prompt_renderer().render()


def render_rprompt() -> str:
    """Render the right-side prompt."""
    return get_prompt_renderer().render_rprompt()


__all__ = [
    "GitStatus",
    "PromptRenderer",
    "get_prompt_renderer",
    "render_prompt",
    "render_rprompt",
    "get_git_status",
]