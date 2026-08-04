"""
Translation Engine
===================

Core translation engine supporting key-value lookups, ICU message format,
nested key resolution via dot notation, positional and named interpolation,
pluralization, and context-aware translation.

Key components:

* ``Translator`` -- main translation orchestrator
* ``TranslationResult`` -- typed result of a translation lookup
* ``TranslationOptions`` -- options bag passed to the translator
"""

from __future__ import annotations

import re
import json
import logging
import functools
from typing import Any

from ainos_i18n.loaders.base import Loader
from ainos_i18n.core.fallback import FallbackStrategy
from ainos_i18n.core.plural import PluralRules
from ainos_i18n.core.format import Formatter
from ainos_i18n.core.context import ContextTranslator

logger = logging.getLogger(__name__)

# Regex for ICU message placeholders: {var}, {var, plural, ...}
_ICU_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")
_ICU_PLURAL_RE = re.compile(
    r"\{(\w+),\s*plural,\s*(.+?)\}",
    re.DOTALL,
)
_ICU_SELECT_RE = re.compile(
    r"\{(\w+),\s*select,\s*(.+?)\}",
    re.DOTALL,
)

# Regex for simple Python-style %-formatting
_PYTHON_FORMAT_RE = re.compile(r"%\((\w+)\)s")


class TranslationOptions:
    """Options bag for a single translation lookup.

    Parameters
    ----------
    locale : str | None
        Target locale.
    count : int | None
        Pluralization count.
    context : str | None
        Translation context / disambiguation key.
    default : str | None
        Fallback literal if the key is not found.
    domain : str | None
        Translation domain (e.g. ``"messages"``, ``"errors"``).
    """

    __slots__ = ("locale", "count", "context", "default", "domain")

    def __init__(
        self,
        locale: str | None = None,
        count: int | None = None,
        context: str | None = None,
        default: str | None = None,
        domain: str | None = None,
    ) -> None:
        self.locale = locale
        self.count = count
        self.context = context
        self.default = default
        self.domain = domain

    def __repr__(self) -> str:
        return (
            f"TranslationOptions(locale={self.locale!r}, count={self.count!r}, "
            f"context={self.context!r}, default={self.default!r}, domain={self.domain!r})"
        )


class TranslationResult:
    """Typed result of a translation lookup.

    Attributes
    ----------
    value : str
        The resolved translation text.
    key : str
        The original lookup key.
    locale : str
        The locale the translation was resolved in.
    found : bool
        Whether the key was found in the translation data.
    source : str
        Source of the result: ``"translation"``, ``"fallback"``, ``"default"``, or ``"key"``.
    """

    __slots__ = ("value", "key", "locale", "found", "source")

    def __init__(
        self,
        value: str,
        key: str,
        locale: str,
        found: bool = True,
        source: str = "translation",
    ) -> None:
        self.value = value
        self.key = key
        self.locale = locale
        self.found = found
        self.source = source

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return (
            f"TranslationResult(value={self.value!r}, key={self.key!r}, "
            f"locale={self.locale!r}, found={self.found}, source={self.source!r})"
        )


class Translator:
    """Core translation engine.

    Resolves translation keys against loaded locale data, applies
    interpolation, pluralization, context disambiguation, and
    fallback strategies.

    Parameters
    ----------
    loader : Loader
        Translation data loader.
    fallback : FallbackStrategy
        Fallback strategy for missing keys.
    plural_rules : PluralRules
        CLDR plural rule evaluator.
    formatter : Formatter | None
        Locale-aware formatter (optional).
    context_translator : ContextTranslator | None
        Context-aware translation helper.
    """

    def __init__(
        self,
        loader: Loader,
        fallback: FallbackStrategy,
        plural_rules: PluralRules,
        formatter: Formatter | None = None,
        context_translator: ContextTranslator | None = None,
    ) -> None:
        self._loader = loader
        self._fallback = fallback
        self._plural_rules = plural_rules
        self._formatter = formatter or Formatter()
        self._context_translator = context_translator or ContextTranslator()
        self._translations: dict[str, dict[str, Any]] = {}
        self._loaded_locales: set[str] = set()

    # ---- Public API ----

    def translate(
        self,
        key: str,
        *args: object,
        locale: str | None = None,
        count: int | None = None,
        context: str | None = None,
        default: str | None = None,
        **kwargs: object,
    ) -> str:
        """Translate a key to the target locale.

        Parameters
        ----------
        key : str
            Translation key, dot-separated for nested access.
        *args : object
            Positional interpolation arguments.
        locale : str, optional
            Target locale.  Falls back to the last loaded locale.
        count : int, optional
            Pluralization count.
        context : str, optional
            Disambiguation context.
        default : str, optional
            Literal fallback text.
        **kwargs : object
            Named interpolation arguments.

        Returns
        -------
        str
            The resolved translation string.
        """
        # Resolve locale
        target_locale = locale or self._last_loaded_locale()
        if not target_locale:
            logger.warning("No locale set; returning key as-is: %s", key)
            return self._apply_interpolation(key, args, kwargs)

        # Ensure translations are loaded
        if target_locale not in self._loaded_locales:
            self.load_translations(target_locale)

        # Resolve value
        raw = self._resolve_value(key, target_locale, context)

        if raw is not None:
            # Apply pluralization if needed
            if count is not None:
                raw = self._apply_plural(raw, count, target_locale)
            result_str = self._apply_interpolation(str(raw), args, kwargs)
            return result_str

        # --- Fallback chain ---
        result = self._fallback.resolve(
            key=key,
            locale=target_locale,
            translations=self._translations,
            default=default,
            plural_rules=self._plural_rules,
            count=count,
            context=context,
        )

        # Apply interpolation to the final fallback value
        result_str = self._apply_interpolation(result, args, kwargs)
        return result_str

    def translate_result(
        self,
        key: str,
        *args: object,
        locale: str | None = None,
        count: int | None = None,
        context: str | None = None,
        default: str | None = None,
        **kwargs: object,
    ) -> TranslationResult:
        """Translate and return a typed result with metadata.

        Parameters are identical to ``translate()``.

        Returns
        -------
        TranslationResult
        """
        target_locale = locale or self._last_loaded_locale()
        if not target_locale:
            return TranslationResult(
                value=self._apply_interpolation(key, args, kwargs),
                key=key,
                locale="unknown",
                found=False,
                source="key",
            )

        if target_locale not in self._loaded_locales:
            self.load_translations(target_locale)

        raw = self._resolve_value(key, target_locale, context)

        if raw is not None:
            if count is not None:
                raw = self._apply_plural(raw, count, target_locale)
            result_str = self._apply_interpolation(str(raw), args, kwargs)
            return TranslationResult(
                value=result_str,
                key=key,
                locale=target_locale,
                found=True,
                source="translation",
            )

        # Fallback
        fallback_value = self._fallback.resolve(
            key=key,
            locale=target_locale,
            translations=self._translations,
            default=default,
            plural_rules=self._plural_rules,
            count=count,
            context=context,
        )
        result_str = self._apply_interpolation(fallback_value, args, kwargs)

        source = "default" if default else "key"
        return TranslationResult(
            value=result_str,
            key=key,
            locale=target_locale,
            found=False,
            source=source,
        )

    def exists(self, key: str, locale: str | None = None) -> bool:
        """Check whether a translation key exists.

        Parameters
        ----------
        key : str
            Translation key.
        locale : str, optional
            Locale to check.

        Returns
        -------
        bool
        """
        target_locale = locale or self._last_loaded_locale()
        if not target_locale:
            return False
        if target_locale not in self._loaded_locales:
            self.load_translations(target_locale)
        return self._resolve_value(key, target_locale) is not None

    def load_translations(self, locale: str) -> None:
        """Load translation data for a locale from the loader.

        Parameters
        ----------
        locale : str
            Locale code.
        """
        try:
            data = self._loader.load(locale)
            if data:
                self._translations[locale] = data
                self._loaded_locales.add(locale)
                logger.debug("Loaded translations for locale: %s (%d keys)", locale, self._count_keys(data))
            else:
                logger.warning("Loader returned empty data for locale: %s", locale)
                self._translations.setdefault(locale, {})
                self._loaded_locales.add(locale)
        except Exception as exc:
            logger.error("Failed to load translations for locale '%s': %s", locale, exc)
            self._translations.setdefault(locale, {})
            self._loaded_locales.add(locale)

    def get_all_keys(self, locale: str | None = None) -> set[str]:
        """Get all translation keys for a locale.

        Parameters
        ----------
        locale : str, optional
            Locale code.

        Returns
        -------
        set[str]
        """
        target_locale = locale or self._last_loaded_locale()
        if not target_locale or target_locale not in self._translations:
            return set()
        return self._collect_keys(self._translations[target_locale], "")

    def reload_all(self) -> None:
        """Reload translations for all previously loaded locales."""
        locales = list(self._loaded_locales)
        self._translations.clear()
        self._loaded_locales.clear()
        for loc in locales:
            self.load_translations(loc)

    # ---- Internal helpers ----

    def _last_loaded_locale(self) -> str | None:
        """Return the most recently loaded locale, or None."""
        if not self._loaded_locales:
            return None
        # Return the last added locale (insertion order preserved in 3.7+)
        return list(self._loaded_locales)[-1]

    def _resolve_value(
        self,
        key: str,
        locale: str,
        context: str | None = None,
    ) -> Any:
        """Resolve a dot-separated key in the translation tree.

        Attempts context-aware lookup first if context is provided.
        """
        locale_data = self._translations.get(locale)
        if not locale_data:
            return None

        # Context-aware lookup
        if context:
            context_key = f"{key}___{context}"
            val = self._deep_get(locale_data, context_key)
            if val is not None:
                return val

        # Standard lookup
        val = self._deep_get(locale_data, key)
        if val is not None:
            return val

        # Try with context suffix in the key itself
        if context:
            alt_key = f"{key}.{context}"
            val = self._deep_get(locale_data, alt_key)
            if val is not None:
                return val

        return None

    @staticmethod
    def _deep_get(data: dict[str, Any], dot_key: str) -> Any:
        """Traverse nested dicts using dot notation.

        Examples
        --------
        >>> _deep_get({"a": {"b": "c"}}, "a.b")
        'c'
        """
        if not dot_key:
            return None
        parts = dot_key.split(".")
        current: Any = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
            if current is None:
                return None
        return current

    def _apply_plural(self, value: Any, count: int, locale: str) -> str:
        """Resolve plural forms in a translation value.

        Supports both:

        * Simple dict form: ``{"one": "item", "other": "items"}``
        * ICU plural embedded in string: ``{count, plural, one {item} other {items}}``
        """
        if isinstance(value, dict):
            plural_form = self._plural_rules.get_plural_form(count, locale)
            if plural_form in value:
                return str(value[plural_form])
            if "other" in value:
                return str(value["other"])
            return str(value)

        if isinstance(value, str):
            # ICU plural syntax
            def _replace_icu_plural(m: re.Match) -> str:
                var_name = m.group(1)
                body = m.group(2)
                forms = self._parse_icu_plural_forms(body)
                plural_form = self._plural_rules.get_plural_form(count, locale)
                # Also inject the count variable
                result = forms.get(plural_form) or forms.get("other", "")
                # Replace {var} in the resolved form
                result = result.replace(f"{{{var_name}}}", str(count))
                return result

            result = _ICU_PLURAL_RE.sub(_replace_icu_plural, value)
            # Also handle simple {var} placeholders
            result = result.replace("{count}", str(count))
            # Handle select forms
            result = _ICU_SELECT_RE.sub(self._replace_icu_select, result)
            return result

        return str(value)

    @staticmethod
    def _replace_icu_select(m: re.Match) -> str:
        """Replace an ICU select clause with the matching variant."""
        var_name = m.group(1)
        body = m.group(2)
        # For select, we don't have enough info here; return the key as placeholder
        # (the caller should handle select via the context translator)
        return f"{{{var_name}}}"

    @staticmethod
    def _parse_icu_plural_forms(body: str) -> dict[str, str]:
        """Parse ICU plural body into a dict of form -> text.

        Example input: ``one {item} other {items}``
        """
        result: dict[str, str] = {}
        # Match patterns like: one { ... } other { ... }
        pattern = re.compile(r"(\w+)\s*\{([^}]*)\}")
        for m in pattern.finditer(body):
            form = m.group(1)
            text = m.group(2).strip()
            result[form] = text
        return result

    @staticmethod
    def _apply_interpolation(template: str, args: tuple[object, ...], kwargs: dict[str, object]) -> str:
        """Apply positional and named interpolation to a template string.

        Supports:
        * Python ``%``-formatting: ``%(name)s``
        * ``str.format``-style: ``{name}``
        * Positional ``{}`` placeholders
        """
        if not args and not kwargs:
            return template

        result = template

        # Named kwargs with str.format style
        if kwargs:
            try:
                result = result.format(**kwargs)
            except (KeyError, ValueError, IndexError):
                # Fall back to manual replacement
                for k, v in kwargs.items():
                    result = result.replace(f"{{{k}}}", str(v))

        # Named kwargs with %-style
        if kwargs:
            try:
                result = result % kwargs
            except (KeyError, ValueError, TypeError):
                pass

        # Positional args
        if args:
            try:
                result = result.format(*args)
            except (KeyError, ValueError, IndexError):
                # Manual positional replacement
                for i, arg in enumerate(args):
                    result = result.replace("{}", str(arg), 1)

        return result

    @staticmethod
    def _count_keys(data: dict[str, Any], prefix: str = "") -> int:
        """Recursively count leaf keys in a translation dict."""
        count = 0
        for k, v in data.items():
            if isinstance(v, dict):
                count += Translator._count_keys(v, f"{prefix}{k}.")
            else:
                count += 1
        return count

    @staticmethod
    def _collect_keys(data: dict[str, Any], prefix: str = "") -> set[str]:
        """Recursively collect all dot-separated leaf keys."""
        keys: set[str] = set()
        for k, v in data.items():
            full_key = f"{prefix}{k}" if prefix else k
            if isinstance(v, dict):
                keys |= Translator._collect_keys(v, f"{full_key}.")
            else:
                keys.add(full_key)
        return keys

    def __repr__(self) -> str:
        return (
            f"Translator(loaded_locales={list(self._loaded_locales)}, "
            f"loader={self._loader.__class__.__name__})"
        )