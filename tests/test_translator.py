"""
Tests for the Translator module.
"""

import pytest
from ainos_i18n.core.translator import Translator, TranslationResult, TranslationOptions
from ainos_i18n.core.fallback import FallbackStrategy, FallbackPolicy
from ainos_i18n.core.plural import PluralRules
from ainos_i18n.core.format import Formatter
from ainos_i18n.core.context import ContextTranslator


class MockLoader:
    """Mock loader for testing."""

    def __init__(self, data: dict | None = None):
        self._data = data or {}

    def load(self, locale: str) -> dict:
        return self._data.get(locale, {})


def make_translator(translations: dict | None = None) -> Translator:
    """Helper to create a Translator with test data."""
    if translations is None:
        translations = {
            "en_US": {
                "welcome": "Welcome",
                "goodbye": "Goodbye",
                "items": {
                    "one": "1 item",
                    "other": "{count} items",
                },
                "errors": {
                    "timeout": "Request timed out",
                    "not_found": "Not found: {resource}",
                },
                "nested": {
                    "deep": {
                        "key": "Deep value",
                    },
                },
            },
        }
    loader = MockLoader(translations)
    fallback = FallbackStrategy(FallbackPolicy.KEY_AND_LOCALE_CHAIN)
    plural_rules = PluralRules()
    formatter = Formatter()
    context_translator = ContextTranslator()
    translator = Translator(loader, fallback, plural_rules, formatter, context_translator)
    translator.load_translations("en_US")
    return translator


class TestTranslator:
    """Test suite for the Translator class."""

    def test_simple_translation(self):
        """Test basic key-value lookup."""
        t = make_translator()
        result = t.translate("welcome")
        assert result == "Welcome"

    def test_nested_translation(self):
        """Test dot-notation nested key lookup."""
        t = make_translator()
        result = t.translate("nested.deep.key")
        assert result == "Deep value"

    def test_missing_key_returns_key(self):
        """Test that missing keys return the key itself."""
        t = make_translator()
        result = t.translate("nonexistent.key")
        assert result == "nonexistent.key"

    def test_missing_key_with_default(self):
        """Test default value for missing key."""
        t = make_translator()
        result = t.translate("nonexistent", default="Fallback")
        assert result == "Fallback"

    def test_named_interpolation(self):
        """Test named argument interpolation."""
        t = make_translator()
        result = t.translate("errors.not_found", resource="file.txt")
        assert result == "Not found: file.txt"

    def test_positional_interpolation(self):
        """Test positional argument interpolation."""
        translations = {
            "en_US": {
                "welcome": "Hello, {}!",
            },
        }
        t = make_translator(translations)
        result = t.translate("welcome", "World")
        assert result == "Hello, World!"

    def test_plural_one(self):
        """Test singular plural form."""
        t = make_translator()
        result = t.translate("items", count=1)
        assert result == "1 item"

    def test_plural_other(self):
        """Test plural 'other' form."""
        t = make_translator()
        result = t.translate("items", count=5)
        assert result == "5 items"

    def test_plural_with_interpolation(self):
        """Test plural with count interpolation."""
        translations = {
            "en_US": {
                "items": {
                    "one": "1 item",
                    "other": "{count} items",
                },
            },
        }
        t = make_translator(translations)
        result = t.translate("items", count=3)
        assert result == "3 items"

    def test_translate_result_found(self):
        """Test TranslationResult for a found key."""
        t = make_translator()
        result = t.translate_result("welcome")
        assert result.found is True
        assert result.value == "Welcome"
        assert result.key == "welcome"
        assert result.source == "translation"

    def test_translate_result_not_found(self):
        """Test TranslationResult for a missing key."""
        t = make_translator()
        result = t.translate_result("missing", default="Custom default")
        assert result.found is False
        assert result.value == "Custom default"
        assert result.source == "default"

    def test_exists(self):
        """Test exists() method."""
        t = make_translator()
        assert t.exists("welcome") is True
        assert t.exists("nonexistent") is False

    def test_exists_nested(self):
        """Test exists() with nested keys."""
        t = make_translator()
        assert t.exists("nested.deep.key") is True
        assert t.exists("nested.missing") is False

    def test_get_all_keys(self):
        """Test get_all_keys() returns all leaf keys."""
        t = make_translator()
        keys = t.get_all_keys("en_US")
        assert "welcome" in keys
        assert "goodbye" in keys
        assert "items" in keys
        assert "errors.timeout" in keys
        assert "errors.not_found" in keys
        assert "nested.deep.key" in keys

    def test_load_translations_empty(self):
        """Test loading a locale with no data."""
        t = make_translator()
        t.load_translations("nonexistent")
        assert t.exists("welcome", locale="nonexistent") is False

    def test_reload_all(self):
        """Test reloading all translations."""
        t = make_translator()
        t.reload_all()
        assert t.exists("welcome") is True

    def test_translation_options(self):
        """Test TranslationOptions initialization."""
        opts = TranslationOptions(
            locale="en_US",
            count=5,
            context="button",
            default="Click me",
            domain="messages",
        )
        assert opts.locale == "en_US"
        assert opts.count == 5
        assert opts.context == "button"
        assert opts.default == "Click me"
        assert opts.domain == "messages"

    def test_translation_result_repr(self):
        """Test TranslationResult string representation."""
        result = TranslationResult("Hello", "greeting", "en_US", True, "translation")
        assert "Hello" in repr(result)
        assert "greeting" in repr(result)

    def test_translation_options_repr(self):
        """Test TranslationOptions string representation."""
        opts = TranslationOptions(locale="en_US", count=3)
        assert "en_US" in repr(opts)

    def test_icu_plural_string(self):
        """Test ICU plural syntax embedded in a string."""
        translations = {
            "en_US": {
                "items": "{count, plural, one {1 item} other {{count} items}}",
            },
        }
        t = make_translator(translations)
        result = t.translate("items", count=1)
        assert result == "1 item"
        result = t.translate("items", count=5)
        assert result == "5 items"

    def test_multiple_loaded_locales(self):
        """Test that translations work across multiple locales."""
        translations = {
            "en_US": {"hello": "Hello"},
            "fr_FR": {"hello": "Bonjour"},
        }
        t = make_translator(translations)
        t.load_translations("fr_FR")
        result = t.translate("hello", locale="fr_FR")
        assert result == "Bonjour"
        # Check that en_US still works
        result = t.translate("hello", locale="en_US")
        assert result == "Hello"

    def test_translate_with_context(self):
        """Test context-aware translation."""
        translations = {
            "en_US": {
                "run": "run",
                "run___verb": "to run",
                "run___noun": "a run",
            },
        }
        t = make_translator(translations)
        result = t.translate("run", context="verb")
        assert result == "to run"
        result = t.translate("run", context="noun")
        assert result != "to run"  # Should be different

    def test_dict_value_interpolation(self):
        """Test that dict values are handled correctly."""
        translations = {
            "en_US": {
                "status": {
                    "ok": "OK",
                    "error": "Error",
                },
            },
        }
        t = make_translator(translations)
        result = t.translate("status.ok")
        assert result == "OK"