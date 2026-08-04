"""
Web Panel Internationalization
================================

Internationalization support for the AinosOS Web Panel.

Provides locale-aware page titles, form labels, table headers, and
web-specific UI elements.
"""

from __future__ import annotations

import os
import logging
from typing import Any

from ainos_i18n import AinosI18n
from ainos_i18n.core.locale import LocaleManager

logger = logging.getLogger(__name__)


class WebI18n:
    """Internationalization for the Web Panel component.

    Translates web UI elements including page titles, form labels,
    table headers, navigation items, and error pages.

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
        self._locale_manager = LocaleManager()

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
        """Set the web panel locale."""
        self._i18n.set_locale(locale)

    def detect_from_request(self, accept_language: str) -> str:
        """Detect locale from an HTTP request's Accept-Language header.

        Parameters
        ----------
        accept_language : str
            The Accept-Language header value.

        Returns
        -------
        str
        """
        detected = self._locale_manager.detect_locale_from_accept_language(accept_language)
        self.set_locale(detected)
        return detected

    # ---- Translation ----

    def t(self, key: str, *args: object, **kwargs: object) -> str:
        """Translate a web UI key.

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

    # ---- Web-specific translations ----

    def page_title(self, page_key: str, **kwargs: object) -> str:
        """Get localized page title.

        Parameters
        ----------
        page_key : str
            Page identifier, e.g. ``"dashboard"``, ``"settings"``.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"web.page.{page_key}.title", **kwargs)

    def page_description(self, page_key: str, **kwargs: object) -> str:
        """Get localized page meta description.

        Parameters
        ----------
        page_key : str
            Page identifier.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"web.page.{page_key}.description", **kwargs)

    def nav_label(self, nav_key: str, **kwargs: object) -> str:
        """Get localized navigation item label.

        Parameters
        ----------
        nav_key : str
            Navigation item key, e.g. ``"home"``, ``"models"``, ``"inference"``.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"web.nav.{nav_key}", **kwargs)

    def breadcrumb_label(self, crumb_key: str, **kwargs: object) -> str:
        """Get localized breadcrumb label.

        Parameters
        ----------
        crumb_key : str
            Breadcrumb key.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"web.breadcrumb.{crumb_key}", **kwargs)

    def form_label(self, form_key: str, field: str, **kwargs: object) -> str:
        """Get localized form field label.

        Parameters
        ----------
        form_key : str
            Form identifier.
        field : str
            Field name.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"web.form.{form_key}.{field}.label", **kwargs)

    def form_placeholder(self, form_key: str, field: str, **kwargs: object) -> str:
        """Get localized form field placeholder.

        Parameters
        ----------
        form_key : str
            Form identifier.
        field : str
            Field name.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"web.form.{form_key}.{field}.placeholder", **kwargs)

    def form_validation_error(self, field: str, error_type: str, **kwargs: object) -> str:
        """Get localized form validation error message.

        Parameters
        ----------
        field : str
            Field name.
        error_type : str
            Error type, e.g. ``"required"``, ``"invalid"``, ``"too_long"``.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"web.validation.{field}.{error_type}", **kwargs)

    def table_header(self, table_key: str, column: str, **kwargs: object) -> str:
        """Get localized table column header.

        Parameters
        ----------
        table_key : str
            Table identifier.
        column : str
            Column name.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"web.table.{table_key}.{column}", **kwargs)

    def empty_state_message(self, resource_key: str, **kwargs: object) -> str:
        """Get localized empty state message.

        Parameters
        ----------
        resource_key : str
            Resource type, e.g. ``"models"``, ``"datasets"``.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"web.empty.{resource_key}", **kwargs)

    def error_page_title(self, error_code: int | str, **kwargs: object) -> str:
        """Get localized error page title.

        Parameters
        ----------
        error_code : int | str
            HTTP status code or error identifier.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"web.error.{error_code}.title", **kwargs)

    def error_page_message(self, error_code: int | str, **kwargs: object) -> str:
        """Get localized error page message.

        Parameters
        ----------
        error_code : int | str
            HTTP status code.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"web.error.{error_code}.message", **kwargs)

    def action_button(self, action_key: str, **kwargs: object) -> str:
        """Get localized action button text.

        Parameters
        ----------
        action_key : str
            Action key, e.g. ``"submit"``, ``"cancel"``, ``"retry"``.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"web.action.{action_key}", **kwargs)

    def toast_message(self, toast_key: str, **kwargs: object) -> str:
        """Get localized toast notification message.

        Parameters
        ----------
        toast_key : str
            Toast key, e.g. ``"save_success"``, ``"delete_confirm"``.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"web.toast.{toast_key}", **kwargs)

    def modal_title(self, modal_key: str, **kwargs: object) -> str:
        """Get localized modal dialog title.

        Parameters
        ----------
        modal_key : str
            Modal identifier.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"web.modal.{modal_key}.title", **kwargs)

    def modal_body(self, modal_key: str, **kwargs: object) -> str:
        """Get localized modal dialog body text.

        Parameters
        ----------
        modal_key : str
            Modal identifier.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"web.modal.{modal_key}.body", **kwargs)

    def tab_label(self, tab_group: str, tab_key: str, **kwargs: object) -> str:
        """Get localized tab label.

        Parameters
        ----------
        tab_group : str
            Tab group identifier.
        tab_key : str
            Tab identifier.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"web.tabs.{tab_group}.{tab_key}", **kwargs)

    def filter_label(self, filter_key: str, **kwargs: object) -> str:
        """Get localized filter label.

        Parameters
        ----------
        filter_key : str
            Filter identifier.
        **kwargs : object
            Format arguments.

        Returns
        -------
        str
        """
        return self._i18n.t(f"web.filter.{filter_key}", **kwargs)

    # ---- HTML helpers ----

    def html_lang_attr(self) -> str:
        """Get the HTML lang attribute value for the current locale.

        Returns
        -------
        str
            e.g. ``"zh-CN"``, ``"en"``, ``"ar-SA"``
        """
        return self.current_locale.replace("_", "-")

    def html_dir_attr(self) -> str:
        """Get the HTML dir attribute for the current locale.

        Returns
        -------
        str
            ``"ltr"`` or ``"rtl"``
        """
        return self._i18n.get_locale_info().direction

    def is_rtl(self) -> bool:
        """Check if the current locale is right-to-left.

        Returns
        -------
        bool
        """
        return self.html_dir_attr() == "rtl"

    # ---- JavaScript integration ----

    def get_locale_data(self) -> dict[str, Any]:
        """Get translation data for embedding in web pages.

        Returns a flat dict of key-value pairs for client-side use.

        Returns
        -------
        dict[str, Any]
        """
        locale = self.current_locale
        from ainos_i18n.loaders.json import JSONLoader
        loader = JSONLoader(self._default_dir())
        data = loader.load(locale)

        # Flatten for JavaScript consumption
        flat: dict[str, str] = {}

        def _flatten(d: dict[str, Any], prefix: str = "") -> None:
            for k, v in d.items():
                full_key = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    # Check if it's a plural form dict
                    if all(isinstance(sk, str) and len(sk) < 10 for sk in v):
                        import json
                        flat[full_key] = json.dumps(v, ensure_ascii=False)
                    else:
                        _flatten(v, full_key)
                else:
                    flat[full_key] = str(v)

        _flatten(data)
        return flat

    # ---- Underlying i18n access ----

    @property
    def i18n(self) -> AinosI18n:
        return self._i18n

    def __repr__(self) -> str:
        return f"WebI18n(locale={self._i18n.current_locale})"