"""
Desktop GUI Internationalization
==================================

Internationalization support for the AinosOS Desktop GUI.

Provides locale-aware UI text, menu labels, tooltips, dialog messages,
and system tray notifications.
"""

from __future__ import annotations

import os
import logging
from typing import Any

from ainos_i18n import AinosI18n

logger = logging.getLogger(__name__)


class DesktopI18n:
    """Internationalization for the Desktop GUI component.

    Translates UI elements, menus, dialogs, notifications, and tooltips
    for the desktop environment.

    Parameters
    ----------
    translation_dir : str, optional
        Directory containing locale files.
    locale : str, optional
        Initial locale.
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
        """Set the desktop UI locale."""
        self._i18n.set_locale(locale)
        logger.info("Desktop UI locale set to: %s", locale)

    # ---- Translation ----

    def t(self, key: str, *args: object, **kwargs: object) -> str:
        """Translate a UI key.

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

    # ---- Desktop-specific translations ----

    def menu_label(self, menu_key: str, **kwargs: object) -> str:
        """Get a localized menu label.

        Parameters
        ----------
        menu_key : str
            Menu key, e.g. ``"file"``, ``"edit"``, ``"view"``.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"desktop.menu.{menu_key}", **kwargs)

    def menu_item_label(self, menu: str, item: str, **kwargs: object) -> str:
        """Get a localized menu item label.

        Parameters
        ----------
        menu : str
            Parent menu name.
        item : str
            Menu item name.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"desktop.menu.{menu}.{item}", **kwargs)

    def toolbar_label(self, action: str, **kwargs: object) -> str:
        """Get a localized toolbar button label.

        Parameters
        ----------
        action : str
            Action name, e.g. ``"new"``, ``"open"``, ``"save"``.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"desktop.toolbar.{action}", **kwargs)

    def toolbar_tooltip(self, action: str, **kwargs: object) -> str:
        """Get a localized toolbar tooltip.

        Parameters
        ----------
        action : str
            Action name.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"desktop.toolbar.{action}.tooltip", **kwargs)

    def dialog_title(self, dialog_key: str, **kwargs: object) -> str:
        """Get a localized dialog title.

        Parameters
        ----------
        dialog_key : str
            Dialog identifier, e.g. ``"confirm_delete"``, ``"settings"``.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"desktop.dialog.{dialog_key}.title", **kwargs)

    def dialog_message(self, dialog_key: str, **kwargs: object) -> str:
        """Get a localized dialog message.

        Parameters
        ----------
        dialog_key : str
            Dialog identifier.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"desktop.dialog.{dialog_key}.message", **kwargs)

    def dialog_button(self, button_key: str, **kwargs: object) -> str:
        """Get localized dialog button text.

        Parameters
        ----------
        button_key : str
            Button key, e.g. ``"ok"``, ``"cancel"``, ``"yes"``, ``"no"``.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"desktop.dialog.button.{button_key}", **kwargs)

    def notification_title(self, notif_key: str, **kwargs: object) -> str:
        """Get a localized notification title.

        Parameters
        ----------
        notif_key : str
            Notification key.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"desktop.notification.{notif_key}.title", **kwargs)

    def notification_message(self, notif_key: str, **kwargs: object) -> str:
        """Get a localized notification message body.

        Parameters
        ----------
        notif_key : str
            Notification key.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"desktop.notification.{notif_key}.message", **kwargs)

    def statusbar_text(self, status_key: str, **kwargs: object) -> str:
        """Get localized status bar text.

        Parameters
        ----------
        status_key : str
            Status key, e.g. ``"ready"``, ``"loading"``, ``"saving"``.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"desktop.statusbar.{status_key}", **kwargs)

    def context_menu_label(self, item_key: str, **kwargs: object) -> str:
        """Get a localized context menu item label.

        Parameters
        ----------
        item_key : str
            Context menu item key.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"desktop.context_menu.{item_key}", **kwargs)

    def shortcut_label(self, action: str, **kwargs: object) -> str:
        """Get a localized keyboard shortcut description.

        Parameters
        ----------
        action : str
            Action name.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"desktop.shortcuts.{action}", **kwargs)

    def settings_label(self, section: str, key: str, **kwargs: object) -> str:
        """Get a localized settings label.

        Parameters
        ----------
        section : str
            Settings section, e.g. ``"general"``, ``"appearance"``.
        key : str
            Setting key, e.g. ``"language"``, ``"theme"``.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"desktop.settings.{section}.{key}", **kwargs)

    # ---- Formatting helpers ----

    def format_window_title(self, app_name: str, **kwargs: object) -> str:
        """Format a window title.

        Parameters
        ----------
        app_name : str
            Application name.
        **kwargs : object
            Additional format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t("desktop.window.title", app_name=app_name, **kwargs)

    def format_date_display(self, date_val: str | int | float, format_str: str = "medium") -> str:
        """Format a date for desktop display.

        Parameters
        ----------
        date_val : str | int | float
            Date value.
        format_str : str, optional
            Format preset.

        Returns
        -------
        str
        """
        return self._i18n.format_date(date_val, format_str)

    def format_time_display(self, time_val: str | int | float, format_str: str = "short") -> str:
        """Format a time for desktop display."""
        return self._i18n.format_time(time_val, format_str)

    # ---- Underlying i18n access ----

    @property
    def i18n(self) -> AinosI18n:
        return self._i18n

    def __repr__(self) -> str:
        return f"DesktopI18n(locale={self._i18n.current_locale})"