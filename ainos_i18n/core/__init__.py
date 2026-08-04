"""
Core i18n engine components.

This package provides the fundamental building blocks of the Ainos i18n system:

* ``translator`` -- key-value and ICU message translation engine
* ``locale`` -- locale detection, management, and metadata
* ``plural`` -- CLDR-compliant plural rule evaluation
* ``format`` -- locale-aware date, time, number, and currency formatting
* ``context`` -- context-aware translation disambiguation
* ``fallback`` -- configurable fallback strategies for missing keys
"""

from ainos_i18n.core.translator import Translator, TranslationResult, TranslationOptions
from ainos_i18n.core.locale import LocaleManager, LocaleInfo, SUPPORTED_LOCALES
from ainos_i18n.core.plural import PluralRules
from ainos_i18n.core.format import Formatter
from ainos_i18n.core.context import ContextTranslator
from ainos_i18n.core.fallback import FallbackStrategy, FallbackPolicy

__all__ = [
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
]