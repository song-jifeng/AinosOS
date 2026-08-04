"""
Locale Management
==================

Locale detection, validation, and metadata management for the Ainos i18n system.

Provides:

* ``LocaleManager`` -- set, detect, and list locales
* ``LocaleInfo`` -- metadata about a locale (language, region, script, direction)
* ``SUPPORTED_LOCALES`` -- registry of all supported locale codes
"""

from __future__ import annotations

import os
import locale as _sys_locale
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Supported locales registry
# ---------------------------------------------------------------------------

SUPPORTED_LOCALES: dict[str, dict[str, Any]] = {
    "zh_CN": {
        "language": "Chinese",
        "language_code": "zh",
        "region": "China",
        "region_code": "CN",
        "script": "Hans",
        "direction": "ltr",
        "plural_forms": ["other"],
        "decimal_sep": ".",
        "grouping_sep": ",",
        "currency_symbol": "¥",
        "currency_code": "CNY",
        "date_format": "YYYY-MM-DD",
        "time_format": "HH:mm:ss",
        "date_time_format": "YYYY-MM-DD HH:mm:ss",
        "first_day_of_week": 1,
    },
    "en_US": {
        "language": "English",
        "language_code": "en",
        "region": "United States",
        "region_code": "US",
        "script": "Latn",
        "direction": "ltr",
        "plural_forms": ["one", "other"],
        "decimal_sep": ".",
        "grouping_sep": ",",
        "currency_symbol": "$",
        "currency_code": "USD",
        "date_format": "MM/DD/YYYY",
        "time_format": "hh:mm:ss A",
        "date_time_format": "MM/DD/YYYY hh:mm:ss A",
        "first_day_of_week": 0,
    },
    "ja_JP": {
        "language": "Japanese",
        "language_code": "ja",
        "region": "Japan",
        "region_code": "JP",
        "script": "Jpan",
        "direction": "ltr",
        "plural_forms": ["other"],
        "decimal_sep": ".",
        "grouping_sep": ",",
        "currency_symbol": "¥",
        "currency_code": "JPY",
        "date_format": "YYYY年MM月DD日",
        "time_format": "HH:mm:ss",
        "date_time_format": "YYYY年MM月DD日 HH:mm:ss",
        "first_day_of_week": 1,
    },
    "ko_KR": {
        "language": "Korean",
        "language_code": "ko",
        "region": "South Korea",
        "region_code": "KR",
        "script": "Kore",
        "direction": "ltr",
        "plural_forms": ["other"],
        "decimal_sep": ".",
        "grouping_sep": ",",
        "currency_symbol": "₩",
        "currency_code": "KRW",
        "date_format": "YYYY-MM-DD",
        "time_format": "HH:mm:ss",
        "date_time_format": "YYYY-MM-DD HH:mm:ss",
        "first_day_of_week": 1,
    },
    "fr_FR": {
        "language": "French",
        "language_code": "fr",
        "region": "France",
        "region_code": "FR",
        "script": "Latn",
        "direction": "ltr",
        "plural_forms": ["one", "other"],
        "decimal_sep": ",",
        "grouping_sep": " ",
        "currency_symbol": "€",
        "currency_code": "EUR",
        "date_format": "DD/MM/YYYY",
        "time_format": "HH:mm:ss",
        "date_time_format": "DD/MM/YYYY HH:mm:ss",
        "first_day_of_week": 1,
    },
    "de_DE": {
        "language": "German",
        "language_code": "de",
        "region": "Germany",
        "region_code": "DE",
        "script": "Latn",
        "direction": "ltr",
        "plural_forms": ["one", "other"],
        "decimal_sep": ",",
        "grouping_sep": ".",
        "currency_symbol": "€",
        "currency_code": "EUR",
        "date_format": "DD.MM.YYYY",
        "time_format": "HH:mm:ss",
        "date_time_format": "DD.MM.YYYY HH:mm:ss",
        "first_day_of_week": 1,
    },
    "es_ES": {
        "language": "Spanish",
        "language_code": "es",
        "region": "Spain",
        "region_code": "ES",
        "script": "Latn",
        "direction": "ltr",
        "plural_forms": ["one", "other"],
        "decimal_sep": ",",
        "grouping_sep": ".",
        "currency_symbol": "€",
        "currency_code": "EUR",
        "date_format": "DD/MM/YYYY",
        "time_format": "H:mm:ss",
        "date_time_format": "DD/MM/YYYY H:mm:ss",
        "first_day_of_week": 1,
    },
    "ru_RU": {
        "language": "Russian",
        "language_code": "ru",
        "region": "Russia",
        "region_code": "RU",
        "script": "Cyrl",
        "direction": "ltr",
        "plural_forms": ["one", "few", "many", "other"],
        "decimal_sep": ",",
        "grouping_sep": " ",
        "currency_symbol": "₽",
        "currency_code": "RUB",
        "date_format": "DD.MM.YYYY",
        "time_format": "HH:mm:ss",
        "date_time_format": "DD.MM.YYYY HH:mm:ss",
        "first_day_of_week": 1,
    },
    "ar_SA": {
        "language": "Arabic",
        "language_code": "ar",
        "region": "Saudi Arabia",
        "region_code": "SA",
        "script": "Arab",
        "direction": "rtl",
        "plural_forms": ["zero", "one", "two", "few", "many", "other"],
        "decimal_sep": ".",
        "grouping_sep": ",",
        "currency_symbol": "﷼",
        "currency_code": "SAR",
        "date_format": "DD/MM/YYYY",
        "time_format": "hh:mm:ss A",
        "date_time_format": "DD/MM/YYYY hh:mm:ss A",
        "first_day_of_week": 6,
    },
    "pt_BR": {
        "language": "Portuguese",
        "language_code": "pt",
        "region": "Brazil",
        "region_code": "BR",
        "script": "Latn",
        "direction": "ltr",
        "plural_forms": ["one", "other"],
        "decimal_sep": ",",
        "grouping_sep": ".",
        "currency_symbol": "R$",
        "currency_code": "BRL",
        "date_format": "DD/MM/YYYY",
        "time_format": "HH:mm:ss",
        "date_time_format": "DD/MM/YYYY HH:mm:ss",
        "first_day_of_week": 0,
    },
}


@dataclass
class LocaleInfo:
    """Metadata about a locale.

    Attributes
    ----------
    code : str
        Locale code, e.g. ``"zh_CN"``.
    language : str
        Human-readable language name, e.g. ``"Chinese"``.
    language_code : str
        ISO 639-1 language code, e.g. ``"zh"``.
    region : str
        Human-readable region name, e.g. ``"China"``.
    region_code : str
        ISO 3166-1 alpha-2 region code, e.g. ``"CN"``.
    script : str
        ISO 15924 script code, e.g. ``"Hans"``.
    direction : str
        Text direction: ``"ltr"`` or ``"rtl"``.
    plural_forms : list[str]
        CLDR plural form categories for this locale.
    decimal_sep : str
        Decimal separator character.
    grouping_sep : str
        Digit grouping separator character.
    currency_symbol : str
        Local currency symbol.
    currency_code : str
        ISO 4217 currency code.
    date_format : str
        Standard date format pattern.
    time_format : str
        Standard time format pattern.
    date_time_format : str
        Combined date-time format pattern.
    first_day_of_week : int
        First day of week (0=Sunday, 1=Monday, ...).
    """

    code: str
    language: str = ""
    language_code: str = ""
    region: str = ""
    region_code: str = ""
    script: str = ""
    direction: str = "ltr"
    plural_forms: list[str] = field(default_factory=list)
    decimal_sep: str = "."
    grouping_sep: str = ","
    currency_symbol: str = "$"
    currency_code: str = "USD"
    date_format: str = "YYYY-MM-DD"
    time_format: str = "HH:mm:ss"
    date_time_format: str = "YYYY-MM-DD HH:mm:ss"
    first_day_of_week: int = 1


class LocaleManager:
    """Manage locale selection, detection, and enumeration.

    Parameters
    ----------
    default_locale : str, optional
        Fallback locale if detection fails. Defaults to ``"en_US"``.
    """

    def __init__(self, default_locale: str = "en_US") -> None:
        self._default_locale = default_locale
        self._current_locale: str = default_locale
        self._locale_stack: list[str] = []

    # ---- Properties ----

    @property
    def current_locale(self) -> str:
        """Get the currently active locale code."""
        return self._current_locale

    @property
    def default_locale(self) -> str:
        """Get the default locale code."""
        return self._default_locale

    # ---- Locale setting ----

    def set_locale(self, locale: str) -> str:
        """Set the active locale.

        Parameters
        ----------
        locale : str
            Locale code to activate. Must be in ``SUPPORTED_LOCALES``.

        Returns
        -------
        str
            The locale code that was actually set.

        Raises
        ------
        ValueError
            If the locale code is not supported.
        """
        normalized = self._normalize(locale)
        if normalized not in SUPPORTED_LOCALES:
            raise ValueError(
                f"Unsupported locale: {locale!r}. "
                f"Supported locales: {', '.join(SUPPORTED_LOCALES)}"
            )
        self._current_locale = normalized
        logger.info("Locale set to: %s", normalized)
        return normalized

    def push_locale(self, locale: str) -> str:
        """Push the current locale onto a stack and set a new one.

        Useful for temporary locale switches (e.g., rendering a
        template in a different language).

        Parameters
        ----------
        locale : str
            New locale to activate.

        Returns
        -------
        str
            The newly set locale.
        """
        self._locale_stack.append(self._current_locale)
        return self.set_locale(locale)

    def pop_locale(self) -> str:
        """Restore the previous locale from the stack.

        Returns
        -------
        str
            The restored locale.

        Raises
        ------
        IndexError
            If the stack is empty.
        """
        previous = self._locale_stack.pop()
        self._current_locale = previous
        logger.debug("Locale restored to: %s", previous)
        return previous

    # ---- Detection ----

    def detect_locale(self) -> str:
        """Auto-detect the system locale.

        Uses Python's ``locale.getdefaultlocale()`` and maps to the
        closest supported locale.  Falls back to ``self._default_locale``.

        Returns
        -------
        str
        """
        try:
            sys_loc, _ = _sys_locale.getdefaultlocale()
            if sys_loc:
                normalized = self._normalize(sys_loc)
                if normalized in SUPPORTED_LOCALES:
                    self._current_locale = normalized
                    logger.info("Detected system locale: %s", normalized)
                    return normalized

                # Try to match by language code only
                lang_code = sys_loc.split("_")[0].lower()
                for code in SUPPORTED_LOCALES:
                    if code.startswith(lang_code):
                        self._current_locale = code
                        logger.info("Detected locale (by language): %s", code)
                        return code
        except Exception as exc:
            logger.warning("Locale detection failed: %s", exc)

        # Fallback to environment variable
        env_locale = os.environ.get("LANG") or os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES")
        if env_locale:
            normalized = self._normalize(env_locale)
            if normalized in SUPPORTED_LOCALES:
                self._current_locale = normalized
                logger.info("Detected locale from env: %s", normalized)
                return normalized

        self._current_locale = self._default_locale
        logger.info("Using default locale: %s", self._default_locale)
        return self._default_locale

    def detect_locale_from_accept_language(self, accept_language: str) -> str:
        """Detect locale from an HTTP Accept-Language header.

        Parameters
        ----------
        accept_language : str
            The ``Accept-Language`` header value.

        Returns
        -------
        str
        """
        if not accept_language:
            return self._default_locale

        # Parse the header
        languages: list[tuple[str, float]] = []
        for part in accept_language.split(","):
            part = part.strip()
            if not part:
                continue
            if ";" in part:
                lang, q = part.split(";", 1)
                q = q.strip()
                try:
                    q_value = float(q.split("=")[1]) if "=" in q else 1.0
                except (ValueError, IndexError):
                    q_value = 1.0
            else:
                lang = part
                q_value = 1.0
            languages.append((lang, q_value))

        # Sort by quality (descending)
        languages.sort(key=lambda x: x[1], reverse=True)

        for lang, _ in languages:
            normalized = self._normalize(lang)
            if normalized in SUPPORTED_LOCALES:
                return normalized
            # Try matching by language code
            lang_code = lang.split("-")[0].lower()
            for code in SUPPORTED_LOCALES:
                if code.startswith(lang_code):
                    return code

        return self._default_locale

    # ---- Enumeration ----

    def list_locales(self) -> list[str]:
        """List all supported locale codes, sorted.

        Returns
        -------
        list[str]
        """
        return sorted(SUPPORTED_LOCALES.keys())

    def get_locale_info(self, locale: str | None = None) -> LocaleInfo:
        """Get metadata for a locale.

        Parameters
        ----------
        locale : str, optional
            Locale code. Defaults to current locale.

        Returns
        -------
        LocaleInfo
        """
        code = locale or self._current_locale
        if code not in SUPPORTED_LOCALES:
            raise ValueError(f"Unsupported locale: {code!r}")
        raw = SUPPORTED_LOCALES[code]
        return LocaleInfo(code=code, **raw)

    def is_supported(self, locale: str) -> bool:
        """Check if a locale code is supported.

        Parameters
        ----------
        locale : str
            Locale code to check.

        Returns
        -------
        bool
        """
        return self._normalize(locale) in SUPPORTED_LOCALES

    def is_rtl(self, locale: str | None = None) -> bool:
        """Check if a locale uses right-to-left text direction.

        Parameters
        ----------
        locale : str, optional
            Locale code. Defaults to current.

        Returns
        -------
        bool
        """
        info = self.get_locale_info(locale)
        return info.direction == "rtl"

    # ---- Validation ----

    @staticmethod
    def validate_locale_code(code: str) -> bool:
        """Validate a locale code format (language_REGION).

        Must match ISO 639-1 language code (2-3 letters), optionally
        followed by underscore and ISO 3166-1 alpha-2 region code.

        Parameters
        ----------
        code : str
            Locale code to validate.

        Returns
        -------
        bool
        """
        import re
        pattern = r"^[a-z]{2,3}(_[A-Z]{2})?$"
        return bool(re.match(pattern, code))

    # ---- Internal ----

    @staticmethod
    def _normalize(locale: str) -> str:
        """Normalize a locale code to language_REGION format.

        Handles various input formats:
        * ``zh_CN``, ``zh-CN``, ``zh-cn``, ``ZH_CN``
        * ``en``, ``en_US``, ``en-us``
        * ``zh-Hans-CN`` (simplified)
        """
        # Replace hyphens with underscores
        normalized = locale.replace("-", "_")

        # Split into parts
        parts = normalized.split("_")
        if len(parts) >= 2:
            # Normalize: lowercase language, uppercase region
            language = parts[0].lower()
            # Find the region part (skip script if present, e.g. zh_Hans_CN)
            region = None
            for i in range(1, len(parts)):
                if len(parts[i]) == 2 or len(parts[i]) == 4:
                    region = parts[i].upper()
                    break
            if region:
                normalized = f"{language}_{region}"
            else:
                normalized = language
        else:
            normalized = parts[0].lower()

        # Check if it's a base language that maps to a default locale
        lang_to_default = {
            "zh": "zh_CN",
            "en": "en_US",
            "ja": "ja_JP",
            "ko": "ko_KR",
            "fr": "fr_FR",
            "de": "de_DE",
            "es": "es_ES",
            "ru": "ru_RU",
            "ar": "ar_SA",
            "pt": "pt_BR",
        }
        if normalized in lang_to_default and normalized not in SUPPORTED_LOCALES:
            return lang_to_default[normalized]

        return normalized

    def __repr__(self) -> str:
        return (
            f"LocaleManager(current={self._current_locale!r}, "
            f"default={self._default_locale!r}, "
            f"stack_depth={len(self._locale_stack)})"
        )