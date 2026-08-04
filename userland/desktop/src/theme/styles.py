#!/usr/bin/env python3
"""Ainos Desktop - Style Manager.

Provides utilities for loading, managing, and applying
QSS stylesheets across the application.
"""

import os
import logging
from typing import Any

logger = logging.getLogger(__name__)


class StyleManager:
    """Manages stylesheet loading and application.

    Provides centralized stylesheet management with support for
    dynamic styling and partial style overrides.
    """

    def __init__(self):
        """Initialize the style manager."""
        self._stylesheets: dict[str, str] = {}
        self._current_theme: str = "dark"
        self._custom_styles: list[str] = []
        self._active_stylesheet: str = ""

    def register_stylesheet(self, name: str, stylesheet: str) -> None:
        """Register a named stylesheet.

        Args:
            name: Name identifier for the stylesheet.
            stylesheet: The QSS stylesheet content.
        """
        self._stylesheets[name] = stylesheet
        logger.debug("Stylesheet registered: %s (%d chars)", name, len(stylesheet))

    def load_from_file(self, filepath: str, name: str | None = None) -> bool:
        """Load a stylesheet from a file.

        Args:
            filepath: Path to the QSS file.
            name: Optional name to register under. Uses filename if not provided.

        Returns:
            True if loaded successfully.
        """
        if not os.path.isfile(filepath):
            logger.warning("Stylesheet file not found: %s", filepath)
            return False

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            stylesheet_name = name or os.path.splitext(os.path.basename(filepath))[0]
            self.register_stylesheet(stylesheet_name, content)
            return True

        except (IOError, OSError) as e:
            logger.error("Failed to load stylesheet from %s: %s", filepath, e)
            return False

    def add_custom_style(self, style: str) -> None:
        """Add custom QSS style rules.

        Args:
            style: QSS style rules to append.
        """
        self._custom_styles.append(style)
        self._rebuild_active()

    def remove_custom_style(self, style: str) -> bool:
        """Remove a previously added custom style.

        Args:
            style: The style string to remove.

        Returns:
            True if found and removed.
        """
        if style in self._custom_styles:
            self._custom_styles.remove(style)
            self._rebuild_active()
            return True
        return False

    def clear_custom_styles(self) -> None:
        """Clear all custom style rules."""
        self._custom_styles.clear()
        self._rebuild_active()

    def get_active_stylesheet(self) -> str:
        """Get the currently active combined stylesheet.

        Returns:
            Complete QSS stylesheet string.
        """
        return self._active_stylesheet

    def set_theme(self, theme_name: str, stylesheet: str) -> None:
        """Set the active theme stylesheet.

        Args:
            theme_name: Theme name.
            stylesheet: Theme QSS stylesheet.
        """
        self._current_theme = theme_name
        self.register_stylesheet(f"theme_{theme_name}", stylesheet)
        self._rebuild_active()

    def _rebuild_active(self) -> None:
        """Rebuild the active combined stylesheet."""
        parts = []

        # Add theme stylesheet
        theme_key = f"theme_{self._current_theme}"
        if theme_key in self._stylesheets:
            parts.append(self._stylesheets[theme_key])

        # Add base stylesheets (non-theme specific)
        for name, ss in self._stylesheets.items():
            if not name.startswith("theme_"):
                parts.append(ss)

        # Add custom styles
        parts.extend(self._custom_styles)

        self._active_stylesheet = "\n\n".join(parts)

    @property
    def current_theme(self) -> str:
        """Get the current theme name.

        Returns:
            Current theme name.
        """
        return self._current_theme


# Global style manager instance
_style_manager = StyleManager()


def get_style_manager() -> StyleManager:
    """Get the global StyleManager instance.

    Returns:
        The global StyleManager.
    """
    return _style_manager


def load_stylesheet(path: str) -> str | None:
    """Load a stylesheet from a file path.

    Convenience function for one-off stylesheet loading.

    Args:
        path: Path to the QSS file.

    Returns:
        Stylesheet content as string, or None on failure.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except (IOError, OSError) as e:
        logger.error("Failed to load stylesheet: %s", e)
        return None