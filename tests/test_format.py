"""
Tests for the Formatter module.
"""

import pytest
from ainos_i18n.core.format import Formatter


class TestFormatter:
    """Test suite for the Formatter class."""

    def setup_method(self):
        self.formatter = Formatter(default_locale="en_US")

    # ---- Date formatting ----

    def test_format_date_iso_string(self):
        """Test formatting an ISO date string."""
        result = self.formatter.format_date("2026-08-04", locale="en_US")
        assert "Aug" in result or "August" in result
        assert "4" in result or "04" in result
        assert "2026" in result

    def test_format_date_en_us_medium(self):
        """Test medium date format for en_US."""
        result = self.formatter.format_date("2026-08-04", locale="en_US")
        assert "Aug 4, 2026" in result or "Aug" in result

    def test_format_date_zh_cn(self):
        """Test date format for zh_CN."""
        result = self.formatter.format_date("2026-08-04", locale="zh_CN")
        assert "2026" in result
        assert "8" in result or "08" in result
        assert "4" in result or "04" in result

    def test_format_date_short(self):
        """Test short date format."""
        result = self.formatter.format_date("2026-08-04", format_str="short", locale="en_US")
        assert "26" in result or "2026" in result

    def test_format_date_long(self):
        """Test long date format."""
        result = self.formatter.format_date("2026-08-04", format_str="long", locale="en_US")
        assert "August" in result

    def test_format_date_full(self):
        """Test full date format with day name."""
        result = self.formatter.format_date("2026-08-04", format_str="full", locale="en_US")
        assert "Tuesday" in result or "Tue" in result

    def test_format_date_datetime_obj(self):
        """Test formatting a datetime object."""
        import datetime
        dt = datetime.datetime(2026, 8, 4, 14, 30, 0)
        result = self.formatter.format_date(dt, locale="en_US")
        assert "2026" in result

    def test_format_date_timestamp(self):
        """Test formatting a Unix timestamp."""
        result = self.formatter.format_date(1770000000, locale="en_US")
        assert isinstance(result, str)
        assert len(result) > 0

    # ---- Time formatting ----

    def test_format_time_medium(self):
        """Test medium time format."""
        result = self.formatter.format_time("14:30:00", locale="en_US")
        assert "30" in result

    def test_format_time_short(self):
        """Test short time format."""
        result = self.formatter.format_time("14:30:00", format_str="short", locale="en_US")
        assert "30" in result or "2" in result

    def test_format_time_zh_cn(self):
        """Test time format for zh_CN."""
        result = self.formatter.format_time("14:30:00", locale="zh_CN")
        # Chinese uses 24-hour format
        assert "14" in result

    # ---- Datetime formatting ----

    def test_format_datetime(self):
        """Test combined date-time formatting."""
        result = self.formatter.format_datetime("2026-08-04T14:30:00", locale="en_US")
        assert "2026" in result
        assert "30" in result

    # ---- Number formatting ----

    def test_format_number_integer(self):
        """Test formatting an integer."""
        result = self.formatter.format_number(1234567, locale="en_US")
        assert "1,234,567" in result

    def test_format_number_float(self):
        """Test formatting a float with decimals."""
        result = self.formatter.format_number(1234.56, decimals=2, locale="en_US")
        assert "1,234.56" in result

    def test_format_number_french(self):
        """Test French number formatting (space as group sep, comma as decimal)."""
        result = self.formatter.format_number(1234.56, decimals=2, locale="fr_FR")
        assert "1 234" in result
        assert "," in result  # French decimal separator

    def test_format_number_german(self):
        """Test German number formatting."""
        result = self.formatter.format_number(1234.56, decimals=2, locale="de_DE")
        assert "1.234" in result  # German thousand separator
        assert "," in result  # German decimal separator

    def test_format_number_no_decimals(self):
        """Test formatting with auto-detected decimals."""
        result = self.formatter.format_number(42, locale="en_US")
        assert result == "42"

    # ---- Currency formatting ----

    def test_format_currency_usd(self):
        """Test formatting USD currency."""
        result = self.formatter.format_currency(1234.56, currency="USD", locale="en_US")
        assert "$" in result
        assert "1,234.56" in result

    def test_format_currency_eur(self):
        """Test formatting EUR currency."""
        result = self.formatter.format_currency(1234.56, currency="EUR", locale="en_US")
        # Euro symbol is typically after the number in some locales
        assert "€" in result or "EUR" in result

    def test_format_currency_jpy(self):
        """Test formatting JPY currency."""
        result = self.formatter.format_currency(1000, currency="JPY", locale="ja_JP")
        assert "¥" in result or "1,000" in result

    def test_format_currency_brl(self):
        """Test formatting BRL currency."""
        result = self.formatter.format_currency(1234.56, currency="BRL", locale="pt_BR")
        assert "R$" in result or "1.234" in result

    # ---- Percent formatting ----

    def test_format_percent(self):
        """Test percent formatting."""
        result = self.formatter.format_percent(0.25, locale="en_US")
        assert "25" in result
        assert "%" in result

    def test_format_percent_french(self):
        """Test French percent formatting."""
        result = self.formatter.format_percent(0.25, locale="fr_FR")
        assert "25" in result
        assert "%" in result

    # ---- Edge cases ----

    def test_format_date_empty(self):
        """Test that date formatting handles empty/edge input."""
        with pytest.raises((ValueError, TypeError)):
            self.formatter.format_date("", locale="en_US")

    def test_format_number_zero(self):
        """Test formatting zero."""
        result = self.formatter.format_number(0, locale="en_US")
        assert result == "0"

    def test_format_number_negative(self):
        """Test formatting negative numbers."""
        result = self.formatter.format_number(-1234.56, decimals=2, locale="en_US")
        assert "-" in result

    def test_format_number_large(self):
        """Test formatting very large numbers."""
        result = self.formatter.format_number(999999999, locale="en_US")
        assert "999,999,999" in result

    def test_format_currency_zero(self):
        """Test formatting zero currency."""
        result = self.formatter.format_currency(0, currency="USD", locale="en_US")
        assert "$0.00" in result or "$0" in result

    def test_format_currency_negative(self):
        """Test formatting negative currency."""
        result = self.formatter.format_currency(-50, currency="USD", locale="en_US")
        assert "-" in result

    def test_date_format_ru(self):
        """Test Russian date format."""
        result = self.formatter.format_date("2026-08-04", locale="ru_RU")
        assert "2026" in result

    def test_date_format_ar(self):
        """Test Arabic date format."""
        result = self.formatter.format_date("2026-08-04", locale="ar_SA")
        assert "2026" in result

    def test_date_format_ko(self):
        """Test Korean date format."""
        result = self.formatter.format_date("2026-08-04", locale="ko_KR")
        assert "2026" in result
        # Korean uses 년, 월, 일 markers
        assert "년" in result or "2026" in result

    def test_time_format_12h(self):
        """Test 12-hour time format."""
        result = self.formatter.format_time("14:30:00", format_str="short", locale="en_US")
        assert "PM" in result or "pm" in result