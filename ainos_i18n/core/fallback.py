"""
Fallback Strategy
==================

Configurable fallback strategies for resolving missing translation keys.

Provides multiple strategies to handle cases where a translation key is
not found in the target locale:

* ``KEY_CHAIN`` -- try the key as-is, then try parent keys (e.g. ``errors.network.timeout``
  falls back to ``errors.network``, then ``errors``), then try the default, then the key.
* ``LOCALE_CHAIN`` -- try the locale, then parent locales (e.g. ``zh_CN`` -> ``zh``),
  then ``en_US``, then the default, then the key.
* ``KEY_AND_LOCALE_CHAIN`` -- combine both strategies.
* ``DEFAULT_ONLY`` -- only use the provided default text.
* ``KEY_ONLY`` -- return the key itself.
"""

from __future__ import annotations

import enum
import logging
from typing import Any

from ainos_i18n.core.plural import PluralRules

logger = logging.getLogger(__name__)


class FallbackPolicy(enum.Enum):
    """Enumeration of available fallback policies."""

    KEY_CHAIN = "key_chain"
    """Try parent keys in the key hierarchy."""

    LOCALE_CHAIN = "locale_chain"
    """Try parent locales in the locale hierarchy."""

    KEY_AND_LOCALE_CHAIN = "key_and_locale_chain"
    """Combine both key and locale chain strategies."""

    DEFAULT_ONLY = "default_only"
    """Only use the provided default text."""

    KEY_ONLY = "key_only"
    """Return the key itself as the translation."""

    def __str__(self) -> str:
        return self.value


class FallbackStrategy:
    """Configurable fallback strategy for missing translations.

    Parameters
    ----------
    policy : FallbackPolicy or str
        The fallback policy to use.
    """

    def __init__(self, policy: FallbackPolicy | str = FallbackPolicy.KEY_AND_LOCALE_CHAIN) -> None:
        if isinstance(policy, str):
            try:
                self._policy = FallbackPolicy(policy)
            except ValueError:
                logger.warning("Unknown fallback policy: %s; using KEY_AND_LOCALE_CHAIN", policy)
                self._policy = FallbackPolicy.KEY_AND_LOCALE_CHAIN
        else:
            self._policy = policy

    @property
    def policy(self) -> FallbackPolicy:
        """Get the current fallback policy."""
        return self._policy

    def set_policy(self, policy: FallbackPolicy | str) -> None:
        """Change the fallback policy at runtime.

        Parameters
        ----------
        policy : FallbackPolicy or str
        """
        if isinstance(policy, str):
            self._policy = FallbackPolicy(policy)
        else:
            self._policy = policy

    def resolve(
        self,
        key: str,
        locale: str,
        translations: dict[str, dict[str, Any]],
        default: str | None = None,
        plural_rules: PluralRules | None = None,
        count: int | None = None,
        context: str | None = None,
    ) -> str:
        """Resolve a missing translation key using the configured policy.

        Parameters
        ----------
        key : str
            The original translation key.
        locale : str
            The target locale.
        translations : dict[str, dict[str, Any]]
            All loaded translations, keyed by locale code.
        default : str, optional
            User-provided default text.
        plural_rules : PluralRules, optional
            For plural-aware fallback.
        count : int, optional
            Plural count.
        context : str, optional
            Translation context.

        Returns
        -------
        str
            The resolved fallback text.
        """
        if self._policy == FallbackPolicy.KEY_ONLY:
            return key

        if self._policy == FallbackPolicy.DEFAULT_ONLY:
            return default if default is not None else key

        if self._policy == FallbackPolicy.KEY_CHAIN:
            return self._key_chain_fallback(key, locale, translations, default, plural_rules, count, context)

        if self._policy == FallbackPolicy.LOCALE_CHAIN:
            return self._locale_chain_fallback(key, locale, translations, default, plural_rules, count, context)

        # KEY_AND_LOCALE_CHAIN
        return self._combined_fallback(key, locale, translations, default, plural_rules, count, context)

    # ---- Individual strategies ----

    def _key_chain_fallback(
        self,
        key: str,
        locale: str,
        translations: dict[str, dict[str, Any]],
        default: str | None,
        plural_rules: PluralRules | None,
        count: int | None,
        context: str | None,
    ) -> str:
        """Try parent keys in the key hierarchy.

        For ``errors.network.timeout``, tries:
        ``errors.network.timeout`` -> ``errors.network`` -> ``errors`` -> default -> key
        """
        locale_data = translations.get(locale, {})
        parts = key.split(".")

        # Try progressively shorter keys
        for i in range(len(parts), 0, -1):
            parent_key = ".".join(parts[:i])
            val = self._deep_get(locale_data, parent_key)
            if val is not None:
                if isinstance(val, dict):
                    # If we get a dict, try to find the "other" plural form
                    if plural_rules and count is not None:
                        plural_form = plural_rules.get_plural_form(count, locale)
                        if plural_form in val:
                            return str(val[plural_form])
                    if "other" in val:
                        return str(val["other"])
                    # Return the first string value
                    for v in val.values():
                        if isinstance(v, str):
                            return v
                    continue
                return str(val)

        if default is not None:
            return default
        return key

    def _locale_chain_fallback(
        self,
        key: str,
        locale: str,
        translations: dict[str, dict[str, Any]],
        default: str | None,
        plural_rules: PluralRules | None,
        count: int | None,
        context: str | None,
    ) -> str:
        """Try parent locales in the locale hierarchy.

        For ``zh_CN``, tries: ``zh_CN`` -> ``zh`` -> ``en_US`` -> default -> key
        """
        # Build locale chain
        locales_to_try = self._build_locale_chain(locale)

        for loc in locales_to_try:
            locale_data = translations.get(loc)
            if not locale_data:
                continue
            val = self._deep_get(locale_data, key)
            if val is not None:
                if isinstance(val, dict) and plural_rules and count is not None:
                    plural_form = plural_rules.get_plural_form(count, loc)
                    if plural_form in val:
                        return str(val[plural_form])
                    if "other" in val:
                        return str(val["other"])
                if isinstance(val, str):
                    return val
                return str(val)

        if default is not None:
            return default
        return key

    def _combined_fallback(
        self,
        key: str,
        locale: str,
        translations: dict[str, dict[str, Any]],
        default: str | None,
        plural_rules: PluralRules | None,
        count: int | None,
        context: str | None,
    ) -> str:
        """Combine key chain and locale chain strategies.

        For each locale in the chain, try the key chain.
        """
        locales_to_try = self._build_locale_chain(locale)

        for loc in locales_to_try:
            locale_data = translations.get(loc, {})
            parts = key.split(".")

            for i in range(len(parts), 0, -1):
                parent_key = ".".join(parts[:i])
                val = self._deep_get(locale_data, parent_key)
                if val is not None:
                    if isinstance(val, dict) and plural_rules and count is not None:
                        plural_form = plural_rules.get_plural_form(count, loc)
                        if plural_form in val:
                            return str(val[plural_form])
                        if "other" in val:
                            return str(val["other"])
                    if isinstance(val, str):
                        return val
                    return str(val)

        if default is not None:
            return default
        return key

    # ---- Internal helpers ----

    @staticmethod
    def _deep_get(data: dict[str, Any], dot_key: str) -> Any:
        """Traverse nested dicts using dot notation."""
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

    @staticmethod
    def _build_locale_chain(locale: str) -> list[str]:
        """Build a locale fallback chain.

        For ``zh_CN``: ``["zh_CN", "zh", "en_US"]``
        For ``fr_FR``: ``["fr_FR", "fr", "en_US"]``
        """
        chain: list[str] = [locale]

        # Extract the base language
        if "_" in locale:
            lang = locale.split("_")[0]
            if lang != locale:
                chain.append(lang)

        # Add English as ultimate fallback
        if "en_US" not in chain:
            chain.append("en_US")
        if "en" not in chain:
            chain.append("en")

        return chain

    def __repr__(self) -> str:
        return f"FallbackStrategy(policy={self._policy.value})"