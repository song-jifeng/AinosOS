"""
CLI Tools Internationalization
===============================

Internationalization support for AinosOS CLI tools.

Provides locale-aware argument descriptions, help text, status messages,
and progress indicators for command-line tools.
"""

from __future__ import annotations

import os
import sys
import logging
from typing import Any

from ainos_i18n import AinosI18n

logger = logging.getLogger(__name__)


class CLI18n:
    """Internationalization for CLI tools.

    Translates CLI-specific messages including argument help, command
    descriptions, progress indicators, and output formatting.

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
        try:
            from ainos_i18n import __file__ as f
            return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(f))), "locales")
        except ImportError:
            return None

    # ---- Locale management ----

    @property
    def current_locale(self) -> str:
        return self._i18n.current_locale

    def set_locale(self, locale: str) -> None:
        """Set the CLI locale."""
        self._i18n.set_locale(locale)

    # ---- Translation ----

    def t(self, key: str, *args: object, **kwargs: object) -> str:
        """Translate a CLI key.

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

    # ---- CLI-specific translations ----

    def cli_description(self, tool: str, **kwargs: object) -> str:
        """Get localized CLI tool description.

        Parameters
        ----------
        tool : str
            Tool name, e.g. ``"extract"``, ``"compile"``, ``"validate"``.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"cli.{tool}.description", **kwargs)

    def cli_epilog(self, tool: str, **kwargs: object) -> str:
        """Get localized CLI tool epilog text.

        Parameters
        ----------
        tool : str
            Tool name.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"cli.{tool}.epilog", **kwargs)

    def arg_help(self, tool: str, arg: str, **kwargs: object) -> str:
        """Get localized argument help text.

        Parameters
        ----------
        tool : str
            Tool name.
        arg : str
            Argument name, e.g. ``"locale"``, ``"output"``, ``"source"``.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"cli.{tool}.args.{arg}", **kwargs)

    def option_help(self, tool: str, option: str, **kwargs: object) -> str:
        """Get localized option help text.

        Parameters
        ----------
        tool : str
            Tool name.
        option : str
            Option name, e.g. ``"verbose"``, ``"quiet"``.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"cli.{tool}.options.{option}", **kwargs)

    def subcommand_help(self, tool: str, subcommand: str, **kwargs: object) -> str:
        """Get localized subcommand help text.

        Parameters
        ----------
        tool : str
            Parent tool name.
        subcommand : str
            Subcommand name.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"cli.{tool}.commands.{subcommand}", **kwargs)

    # ---- CLI output helpers ----

    def success_message(self, action: str, **kwargs: object) -> str:
        """Get a localized success message.

        Parameters
        ----------
        action : str
            Action that succeeded, e.g. ``"save"``, ``"export"``.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"cli.success.{action}", **kwargs)

    def error_message(self, error_key: str, **kwargs: object) -> str:
        """Get a localized CLI error message.

        Parameters
        ----------
        error_key : str
            Error key, e.g. ``"file_not_found"``, ``"permission_denied"``.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"cli.error.{error_key}", **kwargs)

    def warning_message(self, warning_key: str, **kwargs: object) -> str:
        """Get a localized CLI warning message.

        Parameters
        ----------
        warning_key : str
            Warning key.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"cli.warning.{warning_key}", **kwargs)

    def info_message(self, info_key: str, **kwargs: object) -> str:
        """Get a localized info message.

        Parameters
        ----------
        info_key : str
            Info key.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"cli.info.{info_key}", **kwargs)

    def progress_spinner_text(self, action: str, **kwargs: object) -> str:
        """Get localized text for a spinner/progress indicator.

        Parameters
        ----------
        action : str
            Action being performed.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"cli.progress.{action}", **kwargs)

    def confirm_prompt(self, action: str, **kwargs: object) -> str:
        """Get a localized confirmation prompt.

        Parameters
        ----------
        action : str
            Action to confirm, e.g. ``"delete"``, ``"overwrite"``.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"cli.confirm.{action}", **kwargs)

    def input_prompt(self, field: str, **kwargs: object) -> str:
        """Get a localized input prompt.

        Parameters
        ----------
        field : str
            Input field name, e.g. ``"locale"``, ``"path"``.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"cli.input.{field}", **kwargs)

    def table_header(self, column: str, **kwargs: object) -> str:
        """Get localized table column header for CLI output.

        Parameters
        ----------
        column : str
            Column name, e.g. ``"key"``, ``"locale"``, ``"status"``.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"cli.table.{column}", **kwargs)

    # ---- Result formatting ----

    def format_result_summary(self, action: str, count: int, **kwargs: object) -> str:
        """Format a result summary with count.

        Parameters
        ----------
        action : str
            Action name.
        count : int
            Item count.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.n(f"cli.result.{action}", count, count=count, **kwargs)

    def format_duration(self, seconds: float) -> str:
        """Format a duration for CLI display.

        Parameters
        ----------
        seconds : float
            Duration in seconds.

        Returns
        -------
        str
        """
        if seconds < 60:
            return self._i18n.t("cli.duration.seconds", seconds=f"{seconds:.2f}")
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = seconds % 60
            return self._i18n.t("cli.duration.minutes", minutes=minutes, seconds=f"{secs:.1f}")
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return self._i18n.t("cli.duration.hours", hours=hours, minutes=minutes)

    def format_file_size(self, size_bytes: int) -> str:
        """Format a file size for CLI display.

        Parameters
        ----------
        size_bytes : int
            Size in bytes.

        Returns
        -------
        str
        """
        if size_bytes < 1024:
            return self._i18n.t("cli.filesize.bytes", size=size_bytes)
        elif size_bytes < 1024 * 1024:
            return self._i18n.t("cli.filesize.kb", size=f"{size_bytes / 1024:.1f}")
        elif size_bytes < 1024 * 1024 * 1024:
            return self._i18n.t("cli.filesize.mb", size=f"{size_bytes / (1024 * 1024):.1f}")
        else:
            return self._i18n.t("cli.filesize.gb", size=f"{size_bytes / (1024 * 1024 * 1024):.1f}")

    # ---- ANSI color helpers ----

    COLOR_CODES: dict[str, str] = {
        "red": "\033[91m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "blue": "\033[94m",
        "magenta": "\033[95m",
        "cyan": "\033[96m",
        "white": "\033[97m",
        "bold": "\033[1m",
        "dim": "\033[2m",
        "reset": "\033[0m",
    }

    def colorize(self, text: str, color: str) -> str:
        """Wrap text in ANSI color codes.

        Parameters
        ----------
        text : str
            Text to colorize.
        color : str
            Color name: ``"red"``, ``"green"``, ``"yellow"``, etc.

        Returns
        -------
        str
        """
        if not sys.stdout.isatty():
            return text
        code = self.COLOR_CODES.get(color, "")
        reset = self.COLOR_CODES["reset"]
        return f"{code}{text}{reset}"

    def success_text(self, text: str) -> str:
        """Format text as success (green)."""
        return self.colorize(text, "green")

    def error_text(self, text: str) -> str:
        """Format text as error (red)."""
        return self.colorize(text, "red")

    def warning_text(self, text: str) -> str:
        """Format text as warning (yellow)."""
        return self.colorize(text, "yellow")

    def info_text(self, text: str) -> str:
        """Format text as info (cyan)."""
        return self.colorize(text, "cyan")

    def highlight_text(self, text: str) -> str:
        """Format text as highlighted (bold)."""
        return self.colorize(text, "bold")

    # ---- Underlying i18n access ----

    @property
    def i18n(self) -> AinosI18n:
        return self._i18n

    def __repr__(self) -> str:
        return f"CLI18n(locale={self._i18n.current_locale})"