"""
Theme system for Ainos Shell.

Provides a flexible theme system supporting:
- Multiple built-in themes (default, minimal, powerline, fish, starship-inspired)
- Custom color definitions
- Powerline-style prompt segments
- Git status integration
- 256-color and truecolor support
- Live theme switching
- Theme file loading from JSON/YAML
"""

from __future__ import annotations

import json
import os
import re
import typing as t
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .utils import (
    AnsiCode,
    IS_WINDOWS,
    IS_POSIX,
    colorize,
    get_config_dir,
    file_exists,
    read_file,
    write_file,
    ensure_dir,
    terminal_width,
)

# ---------------------------------------------------------------------------
# Color definitions
# ---------------------------------------------------------------------------

# Standard color palette
COLOR_PALETTE = {
    # Basic colors
    "black": (0, 0, 0),
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "yellow": (255, 255, 0),
    "blue": (0, 0, 255),
    "magenta": (255, 0, 255),
    "cyan": (0, 255, 255),
    "white": (255, 255, 255),
    "bright_black": (128, 128, 128),
    "bright_red": (255, 85, 85),
    "bright_green": (85, 255, 85),
    "bright_yellow": (255, 255, 85),
    "bright_blue": (85, 85, 255),
    "bright_magenta": (255, 85, 255),
    "bright_cyan": (85, 255, 255),
    "bright_white": (255, 255, 255),

    # Extended palette
    "orange": (255, 165, 0),
    "purple": (128, 0, 128),
    "pink": (255, 192, 203),
    "brown": (165, 42, 42),
    "grey": (128, 128, 128),
    "gray": (128, 128, 128),
    "dark_grey": (64, 64, 64),
    "light_grey": (192, 192, 192),
    "dark_red": (139, 0, 0),
    "dark_green": (0, 100, 0),
    "dark_blue": (0, 0, 139),
    "dark_yellow": (184, 134, 11),
    "dark_cyan": (0, 139, 139),
    "dark_magenta": (139, 0, 139),
    "teal": (0, 128, 128),
    "navy": (0, 0, 128),
    "olive": (128, 128, 0),
    "maroon": (128, 0, 0),
    "lime": (0, 255, 0),
    "aqua": (0, 255, 255),
    "fuchsia": (255, 0, 255),
    "silver": (192, 192, 192),
}

# 256-color mapping (approximate)
COLOR_256_MAP: dict = {
    "black": 0, "red": 1, "green": 2, "yellow": 3, "blue": 4,
    "magenta": 5, "cyan": 6, "white": 7,
    "bright_black": 8, "bright_red": 9, "bright_green": 10,
    "bright_yellow": 11, "bright_blue": 12, "bright_magenta": 13,
    "bright_cyan": 14, "bright_white": 15,
}


# ---------------------------------------------------------------------------
# Prompt segment definition
# ---------------------------------------------------------------------------

@dataclass
class PromptSegment:
    """A single segment in the prompt."""
    text: str
    fg: str = ""
    bg: str = ""
    bold: bool = False
    italic: bool = False
    separator: str = " "
    show_separator: bool = True

    def render(self, use_color: bool = True) -> str:
        """Render the segment with ANSI color codes."""
        if not use_color or not (self.fg or self.bg):
            return self.text

        codes = ""
        if self.bold:
            codes += AnsiCode.BOLD
        if self.italic:
            codes += AnsiCode.ITALIC

        result = ""
        if self.bg:
            result += self.bg
        if self.fg:
            result += self.fg
        result += codes + self.text + AnsiCode.RESET

        return result

    def __len__(self) -> int:
        return AnsiCode.len_without_ansi(self.text)

    def __repr__(self) -> str:
        return f"Segment({self.text!r}, fg={self.fg}, bg={self.bg})"


@dataclass
class PromptLine:
    """A single line in a multi-line prompt."""
    segments: list = field(default_factory=list)

    def add(self, segment: PromptSegment) -> "PromptLine":
        self.segments.append(segment)
        return self

    def render(self, use_color: bool = True) -> str:
        return "".join(s.render(use_color) for s in self.segments)

    def visible_length(self) -> int:
        return sum(len(s) for s in self.segments)

    def __repr__(self) -> str:
        return f"PromptLine(segments={len(self.segments)})"


# ---------------------------------------------------------------------------
# Theme definition
# ---------------------------------------------------------------------------

@dataclass
class ColorScheme:
    """Color scheme for a theme."""
    # Prompt colors
    prompt_fg: str = "bright_white"
    prompt_bg: str = "dark_blue"
    prompt_error_fg: str = "white"
    prompt_error_bg: str = "red"

    # Directory colors
    dir_fg: str = "bright_cyan"
    dir_bg: str = ""
    dir_separator_fg: str = "cyan"

    # Git colors
    git_branch_fg: str = "white"
    git_branch_bg: str = "dark_green"
    git_dirty_fg: str = "yellow"
    git_clean_fg: str = "green"
    git_stash_fg: str = "cyan"

    # AI status colors
    ai_fg: str = "white"
    ai_bg: str = "purple"
    ai_loading_fg: str = "yellow"
    ai_ready_fg: str = "green"

    # Command colors
    cmd_fg: str = "white"
    cmd_bg: str = ""
    cmd_error_fg: str = "red"
    cmd_success_fg: str = "green"

    # Output colors
    output_fg: str = "white"
    output_bg: str = ""
    error_fg: str = "bright_red"
    error_bg: str = ""
    warning_fg: str = "yellow"
    info_fg: str = "cyan"

    # Time colors
    time_fg: str = "dark_grey"
    time_bg: str = ""

    # Status colors
    status_fg: str = "white"
    status_bg: str = "dark_grey"

    # Host/user colors
    host_fg: str = "bright_yellow"
    user_fg: str = "bright_green"
    root_fg: str = "red"

    # Separator colors
    separator_fg: str = "dark_grey"
    separator_bg: str = ""

    def get_ansi(self, color_name: str, is_bg: bool = False) -> str:
        """Get ANSI escape code for a named color."""
        name = color_name.lower().strip()
        prefix = "BG_" if is_bg else "FG_"

        # Try direct attribute
        attr_name = f"{prefix}{name.upper()}"
        if hasattr(AnsiCode, attr_name):
            return getattr(AnsiCode, attr_name)

        # Try bright variant
        bright_attr_name = f"{prefix}BRIGHT_{name.upper()}"
        if hasattr(AnsiCode, bright_attr_name):
            return getattr(AnsiCode, bright_attr_name)

        # Try 256-color
        if name in COLOR_256_MAP:
            code = COLOR_256_MAP[name]
            if is_bg:
                return AnsiCode.bg_256(code)
            return AnsiCode.fg_256(code)

        # Try RGB from palette
        if name in COLOR_PALETTE:
            r, g, b = COLOR_PALETTE[name]
            if is_bg:
                return AnsiCode.bg_rgb(r, g, b)
            return AnsiCode.fg_rgb(r, g, b)

        return ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ColorScheme":
        valid_keys = set(cls.__dataclass_fields__.keys())
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**filtered)


@dataclass
class Theme:
    """Complete theme definition."""
    name: str = "default"
    description: str = "Default Ainos Shell theme"
    author: str = "Ainos Team"
    version: str = "1.0.0"

    # Prompt style
    prompt_style: str = "powerline"  # plain, powerline, minimal, fish, starship
    multiline_prompt: bool = False
    show_hostname: bool = False
    show_user: bool = False
    show_time: bool = False
    show_exit_code: bool = True
    show_git: bool = True
    show_ai: bool = True
    show_full_path: bool = False
    show_newline: bool = True
    show_venv: bool = True
    show_jobs: bool = True

    # Colors
    colors: ColorScheme = field(default_factory=ColorScheme)

    # Separator characters
    separator: str = " "  # Between segments
    prompt_char: str = "$"  # Normal user prompt
    prompt_char_root: str = "#"  # Root prompt
    prompt_char_continuation: str = ">"
    powerline_separator: str = ""  #  (right-pointing triangle)
    powerline_separator_thin: str = ""  #  (small triangle)
    segment_separator: str = " "

    # Icons (for non-powerline)
    dir_icon: str = " "
    git_icon: str = " "
    python_icon: str = " "
    clock_icon: str = " "
    error_icon: str = " "
    jobs_icon: str = " "

    # Format strings
    prompt_format: str = "{user_host}{dir}{git}{ai}{venv}{jobs}{time}{status}{prompt_char}"
    rprompt_format: str = "{time}{status}{git}"

    # Powerline-specific
    powerline_pad: str = " "  # Padding inside segments
    use_powerline_symbols: bool = True

    def to_dict(self) -> dict:
        result = asdict(self)
        result["colors"] = self.colors.to_dict()
        return result

    @classmethod
    def from_dict(cls, d: dict) -> "Theme":
        theme = cls()
        for key, value in d.items():
            if key == "colors" and isinstance(value, dict):
                theme.colors = ColorScheme.from_dict(value)
            elif key in cls.__dataclass_fields__:
                setattr(theme, key, value)
        return theme

    def __repr__(self) -> str:
        return f"Theme({self.name!r}, style={self.prompt_style})"


# ---------------------------------------------------------------------------
# Built-in themes
# ---------------------------------------------------------------------------

def create_default_theme() -> Theme:
    """Create the default theme."""
    theme = Theme(
        name="default",
        description="Default Ainos Shell theme with powerline-ish styling",
        prompt_style="powerline",
        colors=ColorScheme(),
    )
    return theme


def create_minimal_theme() -> Theme:
    """Create a minimal theme."""
    return Theme(
        name="minimal",
        description="Minimal prompt with just the essentials",
        prompt_style="minimal",
        show_git=False,
        show_ai=False,
        show_time=False,
        show_exit_code=False,
        show_venv=False,
        show_jobs=False,
        show_hostname=False,
        show_user=False,
        show_full_path=False,
        multiline_prompt=False,
        prompt_char="$",
        colors=ColorScheme(
            prompt_fg="green",
            dir_fg="cyan",
            git_branch_fg="white",
            ai_fg="white",
        ),
    )


def create_fish_theme() -> Theme:
    """Create a fish-inspired theme."""
    return Theme(
        name="fish",
        description="Fish shell-inspired prompt",
        prompt_style="fish",
        show_git=True,
        show_ai=False,
        show_time=False,
        show_exit_code=True,
        show_venv=True,
        show_jobs=False,
        show_hostname=False,
        show_user=False,
        show_full_path=False,
        multiline_prompt=True,
        prompt_char="> ",
        colors=ColorScheme(
            prompt_fg="bright_white",
            dir_fg="bright_cyan",
            dir_bg="",
            git_branch_fg="bright_yellow",
            git_branch_bg="",
            git_dirty_fg="yellow",
            ai_fg="white",
            ai_bg="",
            cmd_success_fg="green",
            cmd_error_fg="red",
        ),
    )


def create_powerline_theme() -> Theme:
    """Create a full powerline theme."""
    return Theme(
        name="powerline",
        description="Full powerline-style prompt with segments",
        prompt_style="powerline",
        use_powerline_symbols=True,
        powerline_separator="",
        show_git=True,
        show_ai=True,
        show_time=True,
        show_exit_code=True,
        show_venv=True,
        show_jobs=True,
        show_hostname=True,
        show_user=True,
        show_full_path=False,
        multiline_prompt=False,
        colors=ColorScheme(
            prompt_fg="bright_white",
            prompt_bg="dark_blue",
            prompt_error_fg="white",
            prompt_error_bg="red",
            dir_fg="bright_white",
            dir_bg="bright_blue",
            git_branch_fg="white",
            git_branch_bg="dark_green",
            git_dirty_fg="yellow",
            ai_fg="white",
            ai_bg="purple",
            time_fg="dark_grey",
            host_fg="bright_yellow",
            user_fg="bright_green",
            root_fg="red",
        ),
    )


def create_starship_theme() -> Theme:
    """Create a Starship-inspired theme."""
    return Theme(
        name="starship",
        description="Starship-inspired prompt with context sections",
        prompt_style="starship",
        use_powerline_symbols=True,
        show_git=True,
        show_ai=True,
        show_time=False,
        show_exit_code=True,
        show_venv=True,
        show_jobs=True,
        show_hostname=False,
        show_user=False,
        show_full_path=False,
        multiline_prompt=True,
        prompt_char=" ",
        colors=ColorScheme(
            prompt_fg="bright_white",
            prompt_bg="",
            dir_fg="bright_cyan",
            git_branch_fg="bright_yellow",
            git_branch_bg="",
            git_dirty_fg="yellow",
            ai_fg="bright_magenta",
            ai_bg="",
            time_fg="dark_grey",
            cmd_success_fg="green",
            cmd_error_fg="red",
        ),
    )


def create_plain_theme() -> Theme:
    """Create a plain, no-color theme."""
    return Theme(
        name="plain",
        description="Plain theme with no colors or special characters",
        prompt_style="plain",
        use_powerline_symbols=False,
        show_git=False,
        show_ai=False,
        show_time=False,
        show_exit_code=False,
        show_venv=False,
        show_jobs=False,
        show_hostname=False,
        show_user=False,
        show_full_path=False,
        multiline_prompt=False,
        prompt_char="$",
        colors=ColorScheme(
            prompt_fg="white",
            dir_fg="white",
            git_branch_fg="white",
            ai_fg="white",
        ),
    )


# ---------------------------------------------------------------------------
# Theme manager
# ---------------------------------------------------------------------------

BUILTIN_THEMES: t.Dict[str, t.Callable[[], Theme]] = {
    "default": create_default_theme,
    "minimal": create_minimal_theme,
    "fish": create_fish_theme,
    "powerline": create_powerline_theme,
    "starship": create_starship_theme,
    "plain": create_plain_theme,
}


class ThemeManager:
    """Manages themes: loading, switching, and custom theme files."""

    def __init__(self) -> None:
        self._themes: t.Dict[str, Theme] = {}
        self._current_theme_name: str = "default"
        self._load_builtin_themes()

    def _load_builtin_themes(self) -> None:
        """Load all built-in themes."""
        for name, factory in BUILTIN_THEMES.items():
            self._themes[name] = factory()

    def get_theme(self, name: str) -> t.Optional[Theme]:
        """Get a theme by name."""
        return self._themes.get(name)

    def get_current_theme(self) -> Theme:
        """Get the current active theme."""
        return self._themes.get(self._current_theme_name, self._themes["default"])

    def set_theme(self, name: str) -> bool:
        """Switch to a theme by name. Returns True if found."""
        if name in self._themes:
            self._current_theme_name = name
            return True
        return False

    def list_themes(self) -> list:
        """List all available themes."""
        return [
            {
                "name": name,
                "description": theme.description,
                "current": name == self._current_theme_name,
            }
            for name, theme in self._themes.items()
        ]

    def add_theme(self, name: str, theme: Theme) -> None:
        """Add a custom theme."""
        self._themes[name] = theme

    def remove_theme(self, name: str) -> bool:
        """Remove a theme. Returns True if removed."""
        if name in BUILTIN_THEMES:
            return False  # Cannot remove built-in themes
        return bool(self._themes.pop(name, None))

    def load_theme_file(self, path: str) -> bool:
        """Load a theme from a JSON file."""
        if not file_exists(path):
            return False

        try:
            content = read_file(path)
            data = json.loads(content)
            theme = Theme.from_dict(data)
            self._themes[theme.name] = theme
            return True
        except (json.JSONDecodeError, IOError, OSError):
            return False

    def save_theme(self, theme: Theme, path: t.Optional[str] = None) -> bool:
        """Save a theme to a JSON file."""
        if path is None:
            theme_dir = os.path.join(get_config_dir(), "themes")
            ensure_dir(theme_dir)
            path = os.path.join(theme_dir, f"{theme.name}.json")

        try:
            ensure_dir(os.path.dirname(path))
            data = json.dumps(theme.to_dict(), indent=2, ensure_ascii=False)
            write_file(path, data)
            return True
        except (IOError, OSError):
            return False

    def load_custom_themes(self) -> None:
        """Load all custom themes from the themes directory."""
        theme_dir = os.path.join(get_config_dir(), "themes")
        if not os.path.isdir(theme_dir):
            return

        for filename in os.listdir(theme_dir):
            if filename.endswith((".json", ".theme")):
                path = os.path.join(theme_dir, filename)
                self.load_theme_file(path)

    def customize(self, name: str, **kwargs: t.Any) -> t.Optional[Theme]:
        """Create a customized version of a theme."""
        base = self.get_theme(name)
        if base is None:
            return None

        theme_dict = base.to_dict()
        for key, value in kwargs.items():
            if key == "colors" and isinstance(value, dict):
                theme_dict["colors"] = {**theme_dict.get("colors", {}), **value}
            elif key in theme_dict:
                theme_dict[key] = value

        new_theme = Theme.from_dict(theme_dict)
        new_theme.name = f"{name}_custom"
        return new_theme

    def __repr__(self) -> str:
        return f"ThemeManager(current={self._current_theme_name}, themes={len(self._themes)})"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_theme_manager: t.Optional[ThemeManager] = None


def get_theme_manager() -> ThemeManager:
    """Get the global theme manager singleton."""
    global _theme_manager
    if _theme_manager is None:
        _theme_manager = ThemeManager()
    return _theme_manager


def get_current_theme() -> Theme:
    """Get the current active theme."""
    return get_theme_manager().get_current_theme()


def available_themes() -> list:
    """Get list of available themes."""
    return get_theme_manager().list_themes()


# ---------------------------------------------------------------------------
# Prompt rendering helpers
# ---------------------------------------------------------------------------

def render_prompt_segment(
    text: str,
    fg: str,
    bg: str = "",
    bold: bool = False,
    separator: str = " ",
    style: str = "powerline",
    use_color: bool = True,
    powerline_char: str = "",
    next_bg: str = "",
) -> str:
    """Render a single prompt segment with optional powerline separator."""
    if not use_color:
        return text + separator

    if style == "powerline" and bg:
        # Render with powerline separator
        colors = ColorScheme()
        fg_ansi = colors.get_ansi(fg)
        bg_ansi = colors.get_ansi(bg, is_bg=True)
        next_bg_ansi = colors.get_ansi(next_bg, is_bg=True) if next_bg else ""

        bold_ansi = AnsiCode.BOLD if bold else ""
        segment = f"{bg_ansi}{fg_ansi}{bold_ansi} {text} {AnsiCode.RESET}"

        if next_bg:
            # Add separator in the next segment's background color
            sep = f"{next_bg_ansi}{colors.get_ansi(fg)}{powerline_char}{AnsiCode.RESET}"
        else:
            sep = ""

        return segment + sep

    else:
        # Plain rendering
        colors = ColorScheme()
        fg_ansi = colors.get_ansi(fg) if fg else ""
        bg_ansi = colors.get_ansi(bg, is_bg=True) if bg else ""
        bold_ansi = AnsiCode.BOLD if bold else ""

        if fg or bg:
            result = f"{bg_ansi}{fg_ansi}{bold_ansi}{text}{AnsiCode.RESET}"
        else:
            result = text

        return result + separator


# ---------------------------------------------------------------------------
# Color conversion utilities
# ---------------------------------------------------------------------------

def hex_to_rgb(hex_color: str) -> t.Tuple[int, int, int]:
    """Convert a hex color string (#RRGGBB) to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    return (int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))


def rgb_to_256(r: int, g: int, b: int) -> int:
    """Convert RGB color to the nearest 256-color code."""
    if r == g == b:
        # Grayscale
        if r < 8:
            return 16
        if r > 248:
            return 231
        return 232 + round((r - 8) / 247 * 23)

    # Color cube
    r_idx = round(r / 255 * 5)
    g_idx = round(g / 255 * 5)
    b_idx = round(b / 255 * 5)
    return 16 + 36 * r_idx + 6 * g_idx + b_idx


def name_to_rgb(color_name: str) -> t.Optional[t.Tuple[int, int, int]]:
    """Convert a color name to RGB tuple."""
    return COLOR_PALETTE.get(color_name.lower())


def blend_colors(c1: t.Tuple[int, int, int], c2: t.Tuple[int, int, int], ratio: float = 0.5) -> t.Tuple[int, int, int]:
    """Blend two colors together."""
    r = int(c1[0] * (1 - ratio) + c2[0] * ratio)
    g = int(c1[1] * (1 - ratio) + c2[1] * ratio)
    b = int(c1[2] * (1 - ratio) + c2[2] * ratio)
    return (r, g, b)


__all__ = [
    "Theme", "ColorScheme", "PromptSegment", "PromptLine",
    "ThemeManager", "get_theme_manager", "get_current_theme", "available_themes",
    "create_default_theme", "create_minimal_theme", "create_fish_theme",
    "create_powerline_theme", "create_starship_theme", "create_plain_theme",
    "render_prompt_segment",
    "hex_to_rgb", "rgb_to_256", "name_to_rgb", "blend_colors",
    "COLOR_PALETTE", "COLOR_256_MAP",
]