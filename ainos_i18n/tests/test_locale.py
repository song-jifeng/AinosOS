"""
Tests for the LocaleManager module.
"""

import pytest
from ainos_i18n.core.locale import LocaleManager, LocaleInfo, SUPPORTED_LOCALES


class TestLocaleManager:
    """Test suite for LocaleManager."""

    def setup_method(self):
        self.manager = LocaleManager(default_locale="en_US")

    def test_default_locale(self):
        """Test default locale is set correctly."""
        assert self.manager.current_locale == "en_US"
        assert self.manager.default_locale == "en_US"

    def test_set_locale_valid(self):
        """Test setting a valid locale."""
        result = self.manager.set_locale("zh_CN")
        assert result == "zh_CN"
        assert self.manager.current_locale == "zh_CN"

    def test_set_locale_normalized(self):
        """Test that locale code is normalized."""
        result = self.manager.set_locale("zh-cn")
        assert result == "zh_CN"

    def test_set_locale_invalid(self):
        """Test that setting an invalid locale raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported locale"):
            self.manager.set_locale("xx_XX")

    def test_push_and_pop_locale(self):
        """Test locale stack operations."""
        self.manager.set_locale("zh_CN")
        result = self.manager.push_locale("fr_FR")
        assert result == "fr_FR"
        assert self.manager.current_locale == "fr_FR"

        result = self.manager.pop_locale()
        assert result == "zh_CN"
        assert self.manager.current_locale == "zh_CN"

    def test_pop_empty_stack(self):
        """Test that popping from an empty stack raises IndexError."""
        with pytest.raises(IndexError):
            self.manager.pop_locale()

    def test_list_locales(self):
        """Test listing all supported locales."""
        locales = self.manager.list_locales()
        assert "en_US" in locales
        assert "zh_CN" in locales
        assert "ja_JP" in locales
        assert "ko_KR" in locales
        assert "fr_FR" in locales
        assert "de_DE" in locales
        assert "es_ES" in locales
        assert "ru_RU" in locales
        assert "ar_SA" in locales
        assert "pt_BR" in locales
        assert len(locales) >= 10

    def test_get_locale_info(self):
        """Test getting locale metadata."""
        info = self.manager.get_locale_info("zh_CN")
        assert isinstance(info, LocaleInfo)
        assert info.code == "zh_CN"
        assert info.language == "Chinese"
        assert info.direction == "ltr"
        assert info.currency_symbol == "¥"

    def test_get_locale_info_en_us(self):
        """Test English locale metadata."""
        info = self.manager.get_locale_info("en_US")
        assert info.language == "English"
        assert info.direction == "ltr"
        assert info.plural_forms == ["one", "other"]

    def test_get_locale_info_ar_sa(self):
        """Test Arabic locale metadata (RTL)."""
        info = self.manager.get_locale_info("ar_SA")
        assert info.direction == "rtl"
        assert "zero" in info.plural_forms
        assert "one" in info.plural_forms
        assert "two" in info.plural_forms

    def test_get_locale_info_invalid(self):
        """Test getting info for an invalid locale."""
        with pytest.raises(ValueError):
            self.manager.get_locale_info("xx_XX")

    def test_is_supported(self):
        """Test is_supported method."""
        assert self.manager.is_supported("en_US") is True
        assert self.manager.is_supported("zh_CN") is True
        assert self.manager.is_supported("xx_XX") is False

    def test_is_rtl(self):
        """Test is_rtl method."""
        assert self.manager.is_rtl("ar_SA") is True
        assert self.manager.is_rtl("en_US") is False
        assert self.manager.is_rtl("zh_CN") is False

    def test_validate_locale_code(self):
        """Test locale code format validation."""
        assert LocaleManager.validate_locale_code("en_US") is True
        assert LocaleManager.validate_locale_code("zh_CN") is True
        assert LocaleManager.validate_locale_code("en") is True
        assert LocaleManager.validate_locale_code("eng_US") is True
        assert LocaleManager.validate_locale_code("en-US") is False  # hyphens not allowed
        assert LocaleManager.validate_locale_code("") is False
        assert LocaleManager.validate_locale_code("123") is False

    def test_detect_locale_from_accept_language(self):
        """Test locale detection from Accept-Language header."""
        locale = self.manager.detect_locale_from_accept_language("zh-CN,zh;q=0.9,en;q=0.8")
        assert locale == "zh_CN"

        locale = self.manager.detect_locale_from_accept_language("fr-FR,fr;q=0.9,en;q=0.5")
        assert locale == "fr_FR"

        locale = self.manager.detect_locale_from_accept_language("xx-XX")
        assert locale == "en_US"  # fallback to default

    def test_detect_locale_from_accept_language_quality(self):
        """Test that quality values are respected."""
        locale = self.manager.detect_locale_from_accept_language(
            "de-DE;q=0.5, fr-FR;q=0.9, en-US;q=0.1"
        )
        # fr_FR has highest quality
        assert locale == "fr_FR"

    def test_normalize_various_formats(self):
        """Test locale code normalization with various input formats."""
        assert LocaleManager._normalize("zh-CN") == "zh_CN"
        assert LocaleManager._normalize("zh-cn") == "zh_CN"
        assert LocaleManager._normalize("ZH_CN") == "zh_CN"
        assert LocaleManager._normalize("en") == "en_US"  # Maps to default
        assert LocaleManager._normalize("fr") == "fr_FR"
        assert LocaleManager._normalize("ja") == "ja_JP"

    def test_detect_locale(self):
        """Test system locale detection (may use system settings)."""
        # This is a basic test that locale detection doesn't crash
        locale = self.manager.detect_locale()
        assert isinstance(locale, str)
        assert len(locale) > 0

    def test_locale_info_dataclass(self):
        """Test LocaleInfo dataclass."""
        info = LocaleInfo(code="en_US")
        assert info.code == "en_US"
        assert info.direction == "ltr"  # default
        assert info.decimal_sep == "."  # default

    def test_locale_info_with_rtl(self):
        """Test that Arabic locale info has correct RTL direction."""
        info = self.manager.get_locale_info("ar_SA")
        assert info.direction == "rtl"
        assert info.currency_code == "SAR"
        assert info.first_day_of_week == 6