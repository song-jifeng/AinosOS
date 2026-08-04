"""
AI Shell Internationalization
===============================

Internationalization support for the Ainos AI Shell component.

Provides locale-aware prompts, command help text, and output messages
for the interactive AI shell environment.
"""

from __future__ import annotations

import os
import logging
from typing import Any

from ainos_i18n import AinosI18n

logger = logging.getLogger(__name__)


class ShellI18n:
    """Internationalization for the AI Shell component.

    Provides translation methods tailored for shell prompts, command
    descriptions, help text, and interactive feedback messages.

    Parameters
    ----------
    translation_dir : str, optional
        Directory containing locale files.
    locale : str, optional
        Initial locale. Auto-detected if omitted.
    """

    def __init__(
        self,
        translation_dir: str | None = None,
        locale: str | None = None,
    ) -> None:
        self._i18n = AinosI18n(
            locale=locale,
            translation_dir=translation_dir or self._default_dir(),
        )

    @staticmethod
    def _default_dir() -> str | None:
        """Get the default locales directory."""
        try:
            from ainos_i18n import __file__ as f
            return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(f))), "locales")
        except ImportError:
            return None

    # ---- Shell-specific translations ----

    @property
    def current_locale(self) -> str:
        """Get the current locale."""
        return self._i18n.current_locale

    def set_locale(self, locale: str) -> None:
        """Set the shell locale."""
        self._i18n.set_locale(locale)

    def t(self, key: str, *args: object, **kwargs: object) -> str:
        """Translate a shell message key.

        Parameters
        ----------
        key : str
            Translation key.
        *args : object
            Positional format arguments.
        **kwargs : object
            Named format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(key, *args, **kwargs)

    # ---- Shell prompt translations ----

    def prompt_message(self, key: str = "shell.prompt", **kwargs: object) -> str:
        """Get the shell prompt message.

        Parameters
        ----------
        key : str, optional
            Prompt key.
        **kwargs : object
            Format arguments (e.g. ``user="admin"``).

        Returns
        -------
        str
        """
        return self._i18n.t(key, **kwargs)

    def welcome_message(self, **kwargs: object) -> str:
        """Get the welcome message displayed on shell startup.

        Returns
        -------
        str
        """
        return self._i18n.t("shell.welcome", **kwargs)

    def goodbye_message(self, **kwargs: object) -> str:
        """Get the goodbye message on shell exit.

        Returns
        -------
        str
        """
        return self._i18n.t("shell.goodbye", **kwargs)

    def error_message(self, key: str = "shell.error", **kwargs: object) -> str:
        """Get a localized error message for the shell.

        Parameters
        ----------
        key : str, optional
            Error key.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(key, **kwargs)

    def help_text(self, command: str = "") -> str:
        """Get localized help text for a command.

        Parameters
        ----------
        command : str, optional
            Command name.

        Returns
        -------
        str
        """
        if command:
            return self._i18n.t(f"shell.help.{command}", default=f"No help available for '{command}'")
        return self._i18n.t("shell.help", default="Available commands: type 'help <command>' for details.")

    def command_description(self, command: str) -> str:
        """Get localized description of a command.

        Parameters
        ----------
        command : str
            Command name.

        Returns
        -------
        str
        """
        return self._i18n.t(f"shell.commands.{command}.description", default=command)

    def command_usage(self, command: str) -> str:
        """Get localized usage string for a command.

        Parameters
        ----------
        command : str
            Command name.

        Returns
        -------
        str
        """
        return self._i18n.t(f"shell.commands.{command}.usage", default=f"Usage: {command} [options]")

    # ---- Shell output helpers ----

    def format_output(self, key: str, *args: object, **kwargs: object) -> str:
        """Format and translate shell output, applying ANSI codes.

        Parameters
        ----------
        key : str
            Translation key.
        *args : object
            Format arguments.
        **kwargs : object
            Named format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(key, *args, **kwargs)

    def confirm_action(self, action: str, **kwargs: object) -> str:
        """Get a confirmation prompt for an action.

        Parameters
        ----------
        action : str
            Action description key.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t("shell.confirm", action=action, **kwargs)

    def progress_message(self, percent: float, **kwargs: object) -> str:
        """Get a localized progress message.

        Parameters
        ----------
        percent : float
            Progress percentage (0-100).
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t("shell.progress", percent=f"{percent:.1f}", **kwargs)

    def status_message(self, status: str, **kwargs: object) -> str:
        """Get a localized status message.

        Parameters
        ----------
        status : str
            Status key (e.g. "running", "completed", "failed").
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"shell.status.{status}", **kwargs)

    # ---- Underlying i18n access ----

    @property
    def i18n(self) -> AinosI18n:
        """Get the underlying AinosI18n instance."""
        return self._i18n

    def __repr__(self) -> str:
        return f"ShellI18n(locale={self._i18n.current_locale})"