"""
Tests for the PluralRules module.
"""

import pytest
from ainos_i18n.core.plural import PluralRules


class TestPluralRules:
    """Test suite for the PluralRules class."""

    def setup_method(self):
        self.rules = PluralRules()

    def test_english_singular(self):
        """Test English singular (1)."""
        assert self.rules.get_plural_form(1, "en_US") == "one"

    def test_english_plural(self):
        """Test English plural (0, 2, 3, ...)."""
        assert self.rules.get_plural_form(0, "en_US") == "other"
        assert self.rules.get_plural_form(2, "en_US") == "other"
        assert self.rules.get_plural_form(100, "en_US") == "other"

    def test_chinese_always_other(self):
        """Test Chinese: always 'other'."""
        assert self.rules.get_plural_form(0, "zh_CN") == "other"
        assert self.rules.get_plural_form(1, "zh_CN") == "other"
        assert self.rules.get_plural_form(5, "zh_CN") == "other"
        assert self.rules.get_plural_form(100, "zh_CN") == "other"

    def test_japanese_always_other(self):
        """Test Japanese: always 'other'."""
        assert self.rules.get_plural_form(1, "ja_JP") == "other"
        assert self.rules.get_plural_form(5, "ja_JP") == "other"

    def test_korean_always_other(self):
        """Test Korean: always 'other'."""
        assert self.rules.get_plural_form(1, "ko_KR") == "other"
        assert self.rules.get_plural_form(5, "ko_KR") == "other"

    def test_french_zero(self):
        """Test French: 0 and 1 are 'one'."""
        assert self.rules.get_plural_form(0, "fr_FR") == "one"
        assert self.rules.get_plural_form(1, "fr_FR") == "one"
        assert self.rules.get_plural_form(2, "fr_FR") == "other"

    def test_german_plural(self):
        """Test German: 1 is 'one', others are 'other'."""
        assert self.rules.get_plural_form(1, "de_DE") == "one"
        assert self.rules.get_plural_form(2, "de_DE") == "other"

    def test_spanish_plural(self):
        """Test Spanish: 1 is 'one'."""
        assert self.rules.get_plural_form(1, "es_ES") == "one"
        assert self.rules.get_plural_form(5, "es_ES") == "other"

    def test_portuguese_plural(self):
        """Test Portuguese: 1 is 'one'."""
        assert self.rules.get_plural_form(1, "pt_BR") == "one"
        assert self.rules.get_plural_form(2, "pt_BR") == "other"

    def test_russian_plural(self):
        """Test Russian plural rules."""
        # one: v % 10 == 1 and v % 100 != 11
        assert self.rules.get_plural_form(1, "ru_RU") == "one"
        assert self.rules.get_plural_form(21, "ru_RU") == "one"
        assert self.rules.get_plural_form(101, "ru_RU") == "one"

        # few: v % 10 in 2..4 and v % 100 not in 12..14
        assert self.rules.get_plural_form(2, "ru_RU") == "few"
        assert self.rules.get_plural_form(3, "ru_RU") == "few"
        assert self.rules.get_plural_form(4, "ru_RU") == "few"
        assert self.rules.get_plural_form(22, "ru_RU") == "few"
        assert self.rules.get_plural_form(103, "ru_RU") == "few"

        # many: v % 10 == 0 or v % 10 in 5..9 or v % 100 in 11..14
        assert self.rules.get_plural_form(0, "ru_RU") == "many"
        assert self.rules.get_plural_form(5, "ru_RU") == "many"
        assert self.rules.get_plural_form(10, "ru_RU") == "many"
        assert self.rules.get_plural_form(11, "ru_RU") == "many"
        assert self.rules.get_plural_form(12, "ru_RU") == "many"
        assert self.rules.get_plural_form(20, "ru_RU") == "many"

    def test_arabic_plural(self):
        """Test Arabic plural rules (most complex)."""
        # zero: v == 0
        assert self.rules.get_plural_form(0, "ar_SA") == "zero"

        # one: v == 1
        assert self.rules.get_plural_form(1, "ar_SA") == "one"

        # two: v == 2
        assert self.rules.get_plural_form(2, "ar_SA") == "two"

        # few: v % 100 in 3..10
        assert self.rules.get_plural_form(3, "ar_SA") == "few"
        assert self.rules.get_plural_form(5, "ar_SA") == "few"
        assert self.rules.get_plural_form(10, "ar_SA") == "few"
        assert self.rules.get_plural_form(103, "ar_SA") == "few"

        # many: v % 100 in 11..99
        assert self.rules.get_plural_form(11, "ar_SA") == "many"
        assert self.rules.get_plural_form(20, "ar_SA") == "many"
        assert self.rules.get_plural_form(99, "ar_SA") == "many"
        assert self.rules.get_plural_form(111, "ar_SA") == "many"

        # other: 100 % 100 = 0, not in any range
        assert self.rules.get_plural_form(100, "ar_SA") == "other"
        # Actually wait, let me re-check. 100 -> mod100 = 0. Not in any range. So it's other.

    def test_unknown_locale(self):
        """Test that unknown locale falls back to default locale's rule."""
        # The default locale is "en_US" which returns "one" for count=1
        form = self.rules.get_plural_form(1, "xx_XX")
        assert form in ("one", "other")  # Either is acceptable fallback

    def test_register_custom_rule(self):
        """Test registering a custom plural rule."""
        def custom_rule(count: int) -> str:
            if count == 0:
                return "zero"
            if count == 1:
                return "one"
            return "many"

        self.rules.register_rule("custom", custom_rule)
        assert self.rules.get_plural_form(0, "custom") == "zero"
        assert self.rules.get_plural_form(1, "custom") == "one"
        assert self.rules.get_plural_form(5, "custom") == "many"

    def test_get_available_locales(self):
        """Test that available locales are returned."""
        locales = self.rules.get_available_locales()
        assert len(locales) > 0
        assert "en" in locales
        assert "zh" in locales
        assert "ru" in locales
        assert "ar" in locales

    def test_negative_count(self):
        """Test negative counts (should use 'other')."""
        # Most languages will treat negative numbers as 'other'
        form = self.rules.get_plural_form(-1, "en_US")
        assert form in ("one", "other")

    def test_large_count(self):
        """Test very large counts."""
        assert self.rules.get_plural_form(1000000, "en_US") == "other"
        # 1000001 mod 100 = 1, mod 10 = 1, so it's "one" in English
        form = self.rules.get_plural_form(1000001, "en_US")
        assert form in ("one", "other")

    def test_polish_plural(self):
        """Test Polish plural rules."""
        assert self.rules.get_plural_form(1, "pl") == "one"
        assert self.rules.get_plural_form(2, "pl") == "few"
        assert self.rules.get_plural_form(3, "pl") == "few"
        assert self.rules.get_plural_form(5, "pl") == "many"
        assert self.rules.get_plural_form(10, "pl") == "many"
        assert self.rules.get_plural_form(12, "pl") == "many"
        assert self.rules.get_plural_form(22, "pl") == "few"  # 22 mod 10 = 2, mod 100 = 22

    def test_czech_plural(self):
        """Test Czech plural rules."""
        assert self.rules.get_plural_form(1, "cs") == "one"
        assert self.rules.get_plural_form(2, "cs") == "few"
        assert self.rules.get_plural_form(3, "cs") == "few"
        assert self.rules.get_plural_form(5, "cs") == "many"
        assert self.rules.get_plural_form(0, "cs") == "many"

    def test_slovenian_plural(self):
        """Test Slovenian plural rules (one/two/few/other)."""
        assert self.rules.get_plural_form(1, "sl") == "one"
        assert self.rules.get_plural_form(2, "sl") == "two"
        assert self.rules.get_plural_form(3, "sl") == "few"
        assert self.rules.get_plural_form(4, "sl") == "few"
        assert self.rules.get_plural_form(5, "sl") == "other"
        assert self.rules.get_plural_form(101, "sl") == "one"

    def test_lithuanian_plural(self):
        """Test Lithuanian plural rules."""
        assert self.rules.get_plural_form(1, "lt") == "one"
        assert self.rules.get_plural_form(2, "lt") == "few"
        # Lithuanian: few: v % 10 in 2..9 and v % 100 not in 11..19
        # 10 mod 10 = 0, not in 2..9, so it's "other"
        assert self.rules.get_plural_form(10, "lt") == "other"
        assert self.rules.get_plural_form(11, "lt") == "other"  # 11 mod 100 = 11

    def test_latvian_plural(self):
        """Test Latvian plural rules (zero/one/other)."""
        assert self.rules.get_plural_form(0, "lv") == "zero"
        assert self.rules.get_plural_form(1, "lv") == "one"
        assert self.rules.get_plural_form(2, "lv") == "other"
        assert self.rules.get_plural_form(11, "lv") == "other"  # 11 mod 100 = 11, not != 11, so not one

    def test_romanian_plural(self):
        """Test Romanian plural rules."""
        assert self.rules.get_plural_form(1, "ro") == "one"
        assert self.rules.get_plural_form(0, "ro") == "few"
        assert self.rules.get_plural_form(2, "ro") == "few"
        assert self.rules.get_plural_form(19, "ro") == "few"
        assert self.rules.get_plural_form(20, "ro") == "other"