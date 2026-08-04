"""
Ainos i18n Internationalization System
========================================

A comprehensive internationalization (i18n) and localization (l10n) framework
designed for the AinosOS ecosystem. Supports key-value and ICU message format
translations, CLDR-compliant plural rules, date/number/currency formatting,
multiple translation loaders, and deep integration with AinosOS components.

Typical usage::

    from ainos_i18n import AinosI18n

    i18n = AinosI18n()
    i18n.set_locale("zh_CN")
    print(i18n.t("welcome", name="张伟"))  # "欢迎, 张伟!"
    print(i18n.n("items", 5))              # "5 个项目"
    print(i18n.format_date("2026-08-04"))  # "2026年8月4日"
"""

__version__ = "1.0.0"
__author__ = "AinosOS Internationalization Team"
__license__ = "MIT"

from ainos_i18n.core.translator import (
    Translator,
    TranslationResult,
    TranslationOptions,
)
from ainos_i18n.core.locale import (
    LocaleManager,
    LocaleInfo,
    SUPPORTED_LOCALES,
)
from ainos_i18n.core.plural import PluralRules
from ainos_i18n.core.format import Formatter
from ainos_i18n.core.context import ContextTranslator
from ainos_i18n.core.fallback import FallbackStrategy, FallbackPolicy

from ainos_i18n.loaders.base import Loader
from ainos_i18n.loaders.json import JSONLoader
from ainos_i18n.loaders.yaml import YAMLLoader
from ainos_i18n.loaders.gettext import GettextLoader
from ainos_i18n.loaders.database import DatabaseLoader

from ainos_i18n.tools.extract import ExtractionTool
from ainos_i18n.tools.compile import CompilationTool
from ainos_i18n.tools.validate import ValidationTool
from ainos_i18n.tools.sync import SyncTool


class AinosI18n:
    """Central facade for the Ainos i18n system.

    This class orchestrates translation, locale management, formatting,
    pluralization, and fallback strategies into a single unified API.

    Parameters
    ----------
    locale : str, optional
        Initial locale code (e.g. ``"zh_CN"``). Auto-detected if omitted.
    loader : Loader, optional
        Translation loader instance. Defaults to JSONLoader.
    fallback_policy : FallbackPolicy or str, optional
        Fallback strategy when a translation key is missing.
    translation_dir : str, optional
        Directory containing locale translation files.
    """

    def __init__(
        self,
        locale: str | None = None,
        loader: Loader | None = None,
        fallback_policy: FallbackPolicy | str = FallbackPolicy.KEY_CHAIN,
        translation_dir: str | None = None,
    ) -> None:
        self._locale_manager = LocaleManager()
        self._formatter = Formatter()
        self._plural_rules = PluralRules()
        self._fallback_strategy = FallbackStrategy(fallback_policy)
        self._loader = loader or JSONLoader(translation_dir)
        self._context_translator = ContextTranslator()

        self._translator = Translator(
            loader=self._loader,
            fallback=self._fallback_strategy,
            plural_rules=self._plural_rules,
            formatter=self._formatter,
            context_translator=self._context_translator,
        )

        if locale:
            self.set_locale(locale)

    # ---- Locale ----

    @property
    def current_locale(self) -> str:
        """Get the current active locale code."""
        return self._locale_manager.current_locale

    def set_locale(self, locale: str) -> None:
        """Set the active locale.

        Parameters
        ----------
        locale : str
            Locale code, e.g. ``"zh_CN"``, ``"en_US"``.
        """
        self._locale_manager.set_locale(locale)
        self._translator.load_translations(locale)

    def detect_locale(self) -> str:
        """Auto-detect the system locale and apply it.

        Returns
        -------
        str
            The detected locale code.
        """
        detected = self._locale_manager.detect_locale()
        self.set_locale(detected)
        return detected

    def list_locales(self) -> list[str]:
        """List all available locales.

        Returns
        -------
        list[str]
            Sorted list of locale codes.
        """
        return self._locale_manager.list_locales()

    def get_locale_info(self, locale: str | None = None) -> LocaleInfo:
        """Get metadata about a locale.

        Parameters
        ----------
        locale : str, optional
            Locale code. Defaults to current locale.

        Returns
        -------
        LocaleInfo
        """
        return self._locale_manager.get_locale_info(locale or self.current_locale)

    # ---- Translation ----

    def t(
        self,
        key: str,
        *args: object,
        locale: str | None = None,
        count: int | None = None,
        context: str | None = None,
        default: str | None = None,
        **kwargs: object,
    ) -> str:
        """Translate a key.

        Parameters
        ----------
        key : str
            Translation key, supports dot notation (e.g. ``"errors.timeout"``).
        *args : object
            Positional format arguments.
        locale : str, optional
            Override locale for this lookup.
        count : int, optional
            Pluralization count.
        context : str, optional
            Translation context/disambiguation.
        default : str, optional
            Fallback text if key is not found.
        **kwargs : object
            Named format arguments.

        Returns
        -------
        str
            Translated string.
        """
        return self._translator.translate(
            key,
            *args,
            locale=locale,
            count=count,
            context=context,
            default=default,
            **kwargs,
        )

    def n(self, key: str, count: int, *args: object, **kwargs: object) -> str:
        """Translate with pluralization by count.

        Shortcut for ``t(key, count=count, ...)``.

        Parameters
        ----------
        key : str
            Translation key.
        count : int
            Numeric count for plural selection.
        *args : object
            Positional format arguments.
        **kwargs : object
            Named format arguments.

        Returns
        -------
        str
        """
        return self._translator.translate(key, *args, count=count, **kwargs)

    def exists(self, key: str, locale: str | None = None) -> bool:
        """Check if a translation key exists.

        Parameters
        ----------
        key : str
            Translation key.
        locale : str, optional
            Locale to check. Defaults to current.

        Returns
        -------
        bool
        """
        return self._translator.exists(key, locale=locale)

    # ---- Formatting ----

    def format_date(
        self,
        date: str | int | float,
        format_str: str = "medium",
        locale: str | None = None,
    ) -> str:
        """Format a date value.

        Parameters
        ----------
        date : str | int | float
            Date string (ISO-8601), Unix timestamp, or ``datetime``-compatible.
        format_str : str, optional
            Preset: ``"short"``, ``"medium"``, ``"long"``, ``"full"``.
        locale : str, optional
            Locale for formatting.

        Returns
        -------
        str
        """
        return self._formatter.format_date(date, format_str, locale or self.current_locale)

    def format_time(
        self,
        time: str | int | float,
        format_str: str = "medium",
        locale: str | None = None,
    ) -> str:
        """Format a time value.

        Parameters
        ----------
        time : str | int | float
            Time string, Unix timestamp, etc.
        format_str : str, optional
            Preset: ``"short"``, ``"medium"``, ``"long"``, ``"full"``.
        locale : str, optional
            Locale for formatting.

        Returns
        -------
        str
        """
        return self._formatter.format_time(time, format_str, locale or self.current_locale)

    def format_number(
        self,
        number: int | float,
        decimals: int | None = None,
        locale: str | None = None,
    ) -> str:
        """Format a number with locale-aware digit grouping.

        Parameters
        ----------
        number : int | float
            The number to format.
        decimals : int, optional
            Decimal places. Omitted = auto.
        locale : str, optional
            Locale for formatting.

        Returns
        -------
        str
        """
        return self._formatter.format_number(number, decimals, locale or self.current_locale)

    def format_currency(
        self,
        amount: int | float,
        currency: str = "USD",
        locale: str | None = None,
    ) -> str:
        """Format a monetary amount.

        Parameters
        ----------
        amount : int | float
            Monetary value.
        currency : str, optional
            ISO 4217 currency code (default ``"USD"``).
        locale : str, optional
            Locale for formatting.

        Returns
        -------
        str
        """
        return self._formatter.format_currency(amount, currency, locale or self.current_locale)

    # ---- Context translation ----

    def with_context(self, context: str) -> "ContextTranslator":
        """Get a context-bound translator for disambiguation.

        Parameters
        ----------
        context : str
            Context identifier, e.g. ``"button"``, ``"menu"``.

        Returns
        -------
        ContextTranslator
        """
        return self._context_translator.with_context(context)

    # ---- Reload ----

    def reload(self, locale: str | None = None) -> None:
        """Reload translations for the given or current locale."""
        self._translator.load_translations(locale or self.current_locale)

    # ---- Plural rules ----

    def get_plural_form(self, count: int, locale: str | None = None) -> str:
        """Get the CLDR plural form name for a count.

        Parameters
        ----------
        count : int
            The numeric count.
        locale : str, optional
            Locale to evaluate against.

        Returns
        -------
        str
            One of: ``"zero"``, ``"one"``, ``"two"``, ``"few"``, ``"many"``, ``"other"``.
        """
        return self._plural_rules.get_plural_form(count, locale or self.current_locale)


__all__ = [
    "AinosI18n",
    "Translator",
    "TranslationResult",
    "TranslationOptions",
    "LocaleManager",
    "LocaleInfo",
    "SUPPORTED_LOCALES",
    "PluralRules",
    "Formatter",
    "ContextTranslator",
    "FallbackStrategy",
    "FallbackPolicy",
    "Loader",
    "JSONLoader",
    "YAMLLoader",
    "GettextLoader",
    "DatabaseLoader",
    "ExtractionTool",
    "CompilationTool",
    "ValidationTool",
    "SyncTool",
]