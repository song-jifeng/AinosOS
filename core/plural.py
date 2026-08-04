"""
Plural Rules
=============

CLDR-compliant plural rule evaluation for the Ainos i18n system.

Supports six CLDR plural categories:

* ``zero`` -- used by Arabic, Latvian, etc.
* ``one`` -- used by English, French, German, etc.
* ``two`` -- used by Arabic, Slovenian, Welsh, etc.
* ``few`` -- used by Russian, Polish, Croatian, etc.
* ``many`` -- used by Russian, Arabic, Polish, etc.
* ``other`` -- universal fallback, used by all languages

Each language has a cardinal plural rule function that maps an integer
count to one of these categories, following the CLDR specification
(https://cldr.unicode.org/).
"""

from __future__ import annotations

import abc
import logging
import functools
from typing import Callable

logger = logging.getLogger(__name__)

# Type alias for a plural rule function: takes an int count, returns a category string.
PluralRuleFunc = Callable[[int], str]


class PluralRules:
    """CLDR-compliant plural rule evaluator.

    Maintains a registry of plural rule functions keyed by locale code.
    Supports cardinal pluralization (used for ``count`` in translations).

    Parameters
    ----------
    default_locale : str, optional
        Fallback locale for rule lookup. Defaults to ``"en_US"``.
    """

    # Registry of plural rule functions
    _rules: dict[str, PluralRuleFunc] = {}

    def __init__(self, default_locale: str = "en_US") -> None:
        self._default_locale = default_locale
        self._register_default_rules()

    def get_plural_form(self, count: int, locale: str) -> str:
        """Get the CLDR plural category for a count in the given locale.

        Parameters
        ----------
        count : int
            The numeric count.
        locale : str
            Locale code.

        Returns
        -------
        str
            One of: ``"zero"``, ``"one"``, ``"two"``, ``"few"``, ``"many"``, ``"other"``.
        """
        # Normalize locale to get the base language
        lang = locale.split("_")[0].lower()

        rule_func = self._rules.get(locale) or self._rules.get(lang)
        if rule_func is None:
            rule_func = self._rules.get(self._default_locale.split("_")[0].lower())
        if rule_func is None:
            return "other"

        try:
            return rule_func(count)
        except Exception as exc:
            logger.warning("Plural rule evaluation failed for locale=%s, count=%d: %s", locale, count, exc)
            return "other"

    def get_available_locales(self) -> list[str]:
        """Get list of locales with registered plural rules.

        Returns
        -------
        list[str]
        """
        return sorted(self._rules.keys())

    def register_rule(self, locale: str, func: PluralRuleFunc) -> None:
        """Register a custom plural rule for a locale.

        Parameters
        ----------
        locale : str
            Locale code.
        func : PluralRuleFunc
            Function that takes an int and returns a plural category.
        """
        self._rules[locale] = func
        logger.debug("Registered plural rule for locale: %s", locale)

    def _register_default_rules(self) -> None:
        """Register all built-in CLDR plural rules."""
        if self._rules:
            return  # Already registered

        # ---- Asian languages (no plural distinction) ----
        # Chinese, Japanese, Korean, Vietnamese, Thai, etc.
        # These languages only have "other".
        for lang in ["zh", "ja", "ko", "th", "vi", "my", "km", "lo", "id", "ms"]:
            self._rules[lang] = _asian_rule

        # ---- English-like (one / other) ----
        # English, German, Dutch, Danish, Swedish, Norwegian, etc.
        for lang in ["en", "de", "nl", "da", "sv", "no", "nb", "nn", "fi", "et", "el", "it", "es", "pt", "ca", "eu", "gl", "bg", "tr", "az", "is"]:
            self._rules[lang] = _english_like_rule

        # ---- French-like (one / other, with special 0 handling) ----
        for lang in ["fr", "ff", "kab"]:
            self._rules[lang] = _french_like_rule

        # ---- Russian-like (one / few / many / other) ----
        # Slavic languages with complex plural rules
        for lang in ["ru", "uk", "be", "sr", "hr", "bs", "sh"]:
            self._rules[lang] = _russian_like_rule

        # ---- Polish (one / few / many / other) ----
        self._rules["pl"] = _polish_rule

        # ---- Czech / Slovak (one / few / many / other) ----
        for lang in ["cs", "sk"]:
            self._rules[lang] = _czech_rule

        # ---- Arabic (zero / one / two / few / many / other) ----
        self._rules["ar"] = _arabic_rule

        # ---- Lithuanian (one / few / other) ----
        self._rules["lt"] = _lithuanian_rule

        # ---- Latvian (zero / one / other) ----
        self._rules["lv"] = _latvian_rule

        # ---- Romanian (one / few / other) ----
        self._rules["ro"] = _romanian_rule

        # ---- Slovenian (one / two / few / other) ----
        self._rules["sl"] = _slovenian_rule

        # ---- Hebrew (one / other) ----
        self._rules["he"] = _english_like_rule
        self._rules["iw"] = _english_like_rule

        # ---- Hindi (one / other) ----
        self._rules["hi"] = _english_like_rule

        # ---- Hungarian (one / other) ----
        self._rules["hu"] = _english_like_rule

        # ---- Finnish (one / other) ----
        self._rules["fi"] = _english_like_rule

        # ---- Also register full locale codes ----
        for locale_code, meta in [
            ("zh_CN", "zh"), ("zh_TW", "zh"), ("zh_HK", "zh"),
            ("en_US", "en"), ("en_GB", "en"), ("en_AU", "en"), ("en_CA", "en"),
            ("ja_JP", "ja"), ("ko_KR", "ko"),
            ("fr_FR", "fr"), ("fr_CA", "fr"), ("fr_BE", "fr"),
            ("de_DE", "de"), ("de_AT", "de"), ("de_CH", "de"),
            ("es_ES", "es"), ("es_MX", "es"), ("es_AR", "es"),
            ("pt_BR", "pt"), ("pt_PT", "pt"),
            ("ru_RU", "ru"), ("ar_SA", "ar"),
            ("it_IT", "it"), ("nl_NL", "nl"),
            ("pl_PL", "pl"), ("cs_CZ", "cs"),
            ("sv_SE", "sv"), ("da_DK", "da"),
            ("nb_NO", "nb"), ("fi_FI", "fi"),
            ("el_GR", "el"), ("hu_HU", "hu"),
            ("tr_TR", "tr"), ("he_IL", "he"),
            ("ro_RO", "ro"), ("sl_SI", "sl"),
            ("hr_HR", "hr"), ("sr_RS", "sr"),
            ("uk_UA", "uk"), ("lt_LT", "lt"),
            ("lv_LV", "lv"), ("bg_BG", "bg"),
            ("ca_ES", "ca"), ("eu_ES", "eu"),
            ("gl_ES", "gl"), ("et_EE", "et"),
            ("is_IS", "is"), ("hi_IN", "hi"),
            ("id_ID", "id"), ("ms_MY", "ms"),
            ("th_TH", "th"), ("vi_VN", "vi"),
        ]:
            base_func = self._rules.get(meta)
            if base_func:
                self._rules[locale_code] = base_func


# ---------------------------------------------------------------------------
# CLDR Plural Rule Functions
# ---------------------------------------------------------------------------

def _asian_rule(count: int) -> str:
    """Asian languages: no plural distinction, always 'other'.

    Applies to: Chinese, Japanese, Korean, Thai, Vietnamese, etc.
    """
    return "other"


def _english_like_rule(count: int) -> str:
    """English-like: 'one' for 1, 'other' otherwise.

    Applies to: English, German, Dutch, Spanish, Italian, Portuguese, etc.
    """
    if count == 1:
        return "one"
    return "other"


def _french_like_rule(count: int) -> str:
    """French-like: 'one' for 0 or 1, 'other' otherwise.

    Applies to: French, Fulah, Kabyle.
    """
    if count == 0 or count == 1:
        return "one"
    return "other"


def _russian_like_rule(count: int) -> str:
    """Russian-like Slavic plural: one / few / many / other.

    Applies to: Russian, Ukrainian, Belarusian, Serbian, Croatian, etc.

    Rules:
    - one  : v % 10 == 1 and v % 100 != 11
    - few  : v % 10 in 2..4 and v % 100 not in 12..14
    - many : v % 10 == 0 or v % 10 in 5..9 or v % 100 in 11..14
    - other: otherwise
    """
    mod10 = count % 10
    mod100 = count % 100

    if mod10 == 1 and mod100 != 11:
        return "one"
    if 2 <= mod10 <= 4 and (mod100 < 12 or mod100 > 14):
        return "few"
    if mod10 == 0 or (5 <= mod10 <= 9) or (11 <= mod100 <= 14):
        return "many"
    return "other"


def _polish_rule(count: int) -> str:
    """Polish plural: one / few / many / other.

    Rules:
    - one  : v == 1
    - few  : v % 10 in 2..4 and v % 100 not in 12..14
    - many : v != 1 and v % 10 in 0..1 or v % 10 in 5..9 or v % 100 in 12..14
    - other: (not used)
    """
    if count == 1:
        return "one"
    mod10 = count % 10
    mod100 = count % 100

    if 2 <= mod10 <= 4 and (mod100 < 12 or mod100 > 14):
        return "few"
    if (mod10 == 0 or mod10 == 1) or (5 <= mod10 <= 9) or (12 <= mod100 <= 14):
        return "many"
    return "other"


def _czech_rule(count: int) -> str:
    """Czech / Slovak plural: one / few / many / other.

    Rules:
    - one  : v == 1
    - few  : v in 2..4
    - many : v is 0 or v >= 5
    - other: (not used for cardinal)
    """
    if count == 1:
        return "one"
    if 2 <= count <= 4:
        return "few"
    if count == 0 or count >= 5:
        return "many"
    return "other"


def _arabic_rule(count: int) -> str:
    """Arabic plural: zero / one / two / few / many / other.

    The most complex plural rule set in CLDR.

    Rules:
    - zero : v == 0
    - one  : v == 1
    - two  : v == 2
    - few  : v % 100 in 3..10
    - many : v % 100 in 11..99
    - other: otherwise
    """
    if count == 0:
        return "zero"
    if count == 1:
        return "one"
    if count == 2:
        return "two"
    mod100 = count % 100
    if 3 <= mod100 <= 10:
        return "few"
    if 11 <= mod100 <= 99:
        return "many"
    return "other"


def _lithuanian_rule(count: int) -> str:
    """Lithuanian plural: one / few / other.

    Rules:
    - one : v % 10 == 1 and v % 100 not in 11..19
    - few : v % 10 in 2..9 and v % 100 not in 11..19
    """
    mod10 = count % 10
    mod100 = count % 100

    if mod10 == 1 and (mod100 < 11 or mod100 > 19):
        return "one"
    if 2 <= mod10 <= 9 and (mod100 < 11 or mod100 > 19):
        return "few"
    return "other"


def _latvian_rule(count: int) -> str:
    """Latvian plural: zero / one / other.

    Rules:
    - zero : v == 0
    - one  : v % 10 == 1 and v % 100 != 11
    """
    if count == 0:
        return "zero"
    mod10 = count % 10
    mod100 = count % 100
    if mod10 == 1 and mod100 != 11:
        return "one"
    return "other"


def _romanian_rule(count: int) -> str:
    """Romanian plural: one / few / other.

    Rules:
    - one : v == 1
    - few : v == 0 or v % 100 in 1..19
    """
    if count == 1:
        return "one"
    if count == 0 or (1 <= count % 100 <= 19):
        return "few"
    return "other"


def _slovenian_rule(count: int) -> str:
    """Slovenian plural: one / two / few / other.

    Rules:
    - one : v % 100 == 1
    - two : v % 100 == 2
    - few : v % 100 in 3..4
    """
    mod100 = count % 100
    if mod100 == 1:
        return "one"
    if mod100 == 2:
        return "two"
    if 3 <= mod100 <= 4:
        return "few"
    return "other"