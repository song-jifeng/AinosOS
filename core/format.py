"""
Locale-Aware Formatting
========================

Formats dates, times, numbers, and currencies according to locale-specific
conventions.  Uses the CLDR data from the locale registry to produce
human-readable output.

Supports:

* Date formatting: short, medium, long, full presets
* Time formatting: short, medium, long, full presets
* Number formatting with digit grouping and decimal separators
* Currency formatting with symbol and code
"""

from __future__ import annotations

import re
import datetime
import logging
from typing import Any

from ainos_i18n.core.locale import SUPPORTED_LOCALES, LocaleInfo

logger = logging.getLogger(__name__)


class Formatter:
    """Locale-aware formatter for dates, times, numbers, and currencies.

    Parameters
    ----------
    default_locale : str, optional
        Fallback locale. Defaults to ``"en_US"``.
    """

    def __init__(self, default_locale: str = "en_US") -> None:
        self._default_locale = default_locale

    # ------------------------------------------------------------------
    # Date formatting
    # ------------------------------------------------------------------

    DATE_PATTERNS: dict[str, dict[str, str]] = {
        "short": {
            "zh_CN": "YYYY-M-D",
            "en_US": "M/D/YY",
            "ja_JP": "YYYY/M/D",
            "ko_KR": "YYYY.M.D.",
            "fr_FR": "D/M/YYYY",
            "de_DE": "D.M.YYYY",
            "es_ES": "D/M/YYYY",
            "ru_RU": "D.M.YYYY",
            "ar_SA": "D/M/YYYY",
            "pt_BR": "D/M/YYYY",
        },
        "medium": {
            "zh_CN": "YYYY年M月D日",
            "en_US": "MMM D, YYYY",
            "ja_JP": "YYYY年M月D日",
            "ko_KR": "YYYY년 M월 D일",
            "fr_FR": "D MMM YYYY",
            "de_DE": "D. MMM YYYY",
            "es_ES": "D MMM YYYY",
            "ru_RU": "D MMM YYYY г.",
            "ar_SA": "D MMM YYYY",
            "pt_BR": "D de MMM de YYYY",
        },
        "long": {
            "zh_CN": "YYYY年M月D日",
            "en_US": "MMMM D, YYYY",
            "ja_JP": "YYYY年M月D日",
            "ko_KR": "YYYY년 M월 D일",
            "fr_FR": "D MMMM YYYY",
            "de_DE": "D. MMMM YYYY",
            "es_ES": "D de MMMM de YYYY",
            "ru_RU": "D MMMM YYYY г.",
            "ar_SA": "D MMMM YYYY",
            "pt_BR": "D de MMMM de YYYY",
        },
        "full": {
            "zh_CN": "YYYY年M月D日 星期E",
            "en_US": "EEEE, MMMM D, YYYY",
            "ja_JP": "YYYY年M月D日 曜日",
            "ko_KR": "YYYY년 M월 D일 EEEE",
            "fr_FR": "EEEE D MMMM YYYY",
            "de_DE": "EEEE, D. MMMM YYYY",
            "es_ES": "EEEE, D de MMMM de YYYY",
            "ru_RU": "EEEE, D MMMM YYYY г.",
            "ar_SA": "EEEE، D MMMM YYYY",
            "pt_BR": "EEEE, D de MMMM de YYYY",
        },
    }

    TIME_PATTERNS: dict[str, dict[str, str]] = {
        "short": {
            "zh_CN": "HH:mm",
            "en_US": "h:mm A",
            "ja_JP": "H:mm",
            "ko_KR": "HH:mm",
            "fr_FR": "HH:mm",
            "de_DE": "HH:mm",
            "es_ES": "H:mm",
            "ru_RU": "HH:mm",
            "ar_SA": "h:mm A",
            "pt_BR": "HH:mm",
        },
        "medium": {
            "zh_CN": "HH:mm:ss",
            "en_US": "h:mm:ss A",
            "ja_JP": "H:mm:ss",
            "ko_KR": "HH:mm:ss",
            "fr_FR": "HH:mm:ss",
            "de_DE": "HH:mm:ss",
            "es_ES": "H:mm:ss",
            "ru_RU": "HH:mm:ss",
            "ar_SA": "h:mm:ss A",
            "pt_BR": "HH:mm:ss",
        },
        "long": {
            "zh_CN": "HH:mm:ss",
            "en_US": "h:mm:ss A z",
            "ja_JP": "H:mm:ss z",
            "ko_KR": "HH:mm:ss z",
            "fr_FR": "HH:mm:ss z",
            "de_DE": "HH:mm:ss z",
            "es_ES": "H:mm:ss z",
            "ru_RU": "HH:mm:ss z",
            "ar_SA": "h:mm:ss A z",
            "pt_BR": "HH:mm:ss z",
        },
        "full": {
            "zh_CN": "HH:mm:ss z",
            "en_US": "h:mm:ss A z",
            "ja_JP": "H:mm:ss z",
            "ko_KR": "HH:mm:ss z",
            "fr_FR": "HH:mm:ss z",
            "de_DE": "HH:mm:ss z",
            "es_ES": "H:mm:ss z",
            "ru_RU": "HH:mm:ss z",
            "ar_SA": "h:mm:ss A z",
            "pt_BR": "HH:mm:ss z",
        },
    }

    # Month names for various locales
    MONTH_NAMES: dict[str, list[str]] = {
        "en_US": ["January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"],
        "fr_FR": ["janvier", "février", "mars", "avril", "mai", "juin",
                   "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
        "de_DE": ["Januar", "Februar", "März", "April", "Mai", "Juni",
                   "Juli", "August", "September", "Oktober", "November", "Dezember"],
        "es_ES": ["enero", "febrero", "marzo", "abril", "mayo", "junio",
                   "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
        "ru_RU": ["января", "февраля", "марта", "апреля", "мая", "июня",
                   "июля", "августа", "сентября", "октября", "ноября", "декабря"],
        "pt_BR": ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
                   "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"],
        "ar_SA": ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
                   "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"],
    }

    MONTH_NAMES_SHORT: dict[str, list[str]] = {
        "en_US": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        "fr_FR": ["janv.", "févr.", "mars", "avr.", "mai", "juin",
                   "juil.", "août", "sept.", "oct.", "nov.", "déc."],
        "de_DE": ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
                   "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"],
        "es_ES": ["ene.", "feb.", "mar.", "abr.", "may.", "jun.",
                   "jul.", "ago.", "sept.", "oct.", "nov.", "dic."],
        "ru_RU": ["янв.", "февр.", "мар.", "апр.", "мая", "июн.",
                   "июл.", "авг.", "сент.", "окт.", "нояб.", "дек."],
        "pt_BR": ["jan.", "fev.", "mar.", "abr.", "mai.", "jun.",
                   "jul.", "ago.", "set.", "out.", "nov.", "dez."],
        "ar_SA": ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
                   "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"],
    }

    DAY_NAMES: dict[str, list[str]] = {
        "en_US": ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"],
        "fr_FR": ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"],
        "de_DE": ["Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"],
        "es_ES": ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"],
        "ru_RU": ["воскресенье", "понедельник", "вторник", "среда", "четверг", "пятница", "суббота"],
        "pt_BR": ["domingo", "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado"],
        "ar_SA": ["الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت"],
    }

    DAY_NAMES_SHORT: dict[str, list[str]] = {
        "en_US": ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
        "fr_FR": ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."],
        "de_DE": ["So.", "Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa."],
        "es_ES": ["dom.", "lun.", "mar.", "mié.", "jue.", "vie.", "sáb."],
        "ru_RU": ["вс", "пн", "вт", "ср", "чт", "пт", "сб"],
        "pt_BR": ["dom.", "seg.", "ter.", "qua.", "qui.", "sex.", "sáb."],
        "ar_SA": ["الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت"],
    }

    def format_date(
        self,
        date: str | int | float | datetime.datetime | datetime.date,
        format_str: str = "medium",
        locale: str | None = None,
    ) -> str:
        """Format a date value.

        Parameters
        ----------
        date : str | int | float | datetime | date
            Date input -- ISO-8601 string, Unix timestamp, or datetime/date object.
        format_str : str, optional
            Preset: ``"short"``, ``"medium"``, ``"long"``, ``"full"``.
        locale : str, optional
            Locale code. Defaults to ``_default_locale``.

        Returns
        -------
        str
        """
        target_locale = self._resolve_locale(locale)
        dt = self._parse_date(date)

        # Get the pattern
        locale_patterns = self.DATE_PATTERNS.get(format_str, self.DATE_PATTERNS["medium"])
        pattern = locale_patterns.get(target_locale, locale_patterns.get("en_US", "YYYY-MM-DD"))

        return self._apply_date_pattern(dt, pattern, target_locale, format_str)

    def format_time(
        self,
        time: str | int | float | datetime.datetime | datetime.time,
        format_str: str = "medium",
        locale: str | None = None,
    ) -> str:
        """Format a time value.

        Parameters
        ----------
        time : str | int | float | datetime | time
            Time input.
        format_str : str, optional
            Preset: ``"short"``, ``"medium"``, ``"long"``, ``"full"``.
        locale : str, optional
            Locale code.

        Returns
        -------
        str
        """
        target_locale = self._resolve_locale(locale)
        dt = self._parse_date(time)

        locale_patterns = self.TIME_PATTERNS.get(format_str, self.TIME_PATTERNS["medium"])
        pattern = locale_patterns.get(target_locale, locale_patterns.get("en_US", "HH:mm:ss"))

        return self._apply_time_pattern(dt, pattern, target_locale)

    def format_datetime(
        self,
        value: str | int | float | datetime.datetime,
        date_format: str = "medium",
        time_format: str = "medium",
        locale: str | None = None,
    ) -> str:
        """Format a combined date and time.

        Parameters
        ----------
        value : str | int | float | datetime
            Date-time value.
        date_format : str, optional
            Date preset.
        time_format : str, optional
            Time preset.
        locale : str, optional
            Locale code.

        Returns
        -------
        str
        """
        date_part = self.format_date(value, date_format, locale)
        time_part = self.format_time(value, time_format, locale)
        return f"{date_part} {time_part}"

    # ------------------------------------------------------------------
    # Number formatting
    # ------------------------------------------------------------------

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
            Number of decimal places. If None, auto-detect from input.
        locale : str, optional
            Locale code.

        Returns
        -------
        str
        """
        target_locale = self._resolve_locale(locale)
        locale_info = self._get_locale_info(target_locale)

        if decimals is None:
            if isinstance(number, float):
                # Preserve input precision
                num_str = str(number)
                if "." in num_str:
                    decimals = len(num_str.split(".")[1])
                else:
                    decimals = 0
            else:
                decimals = 0

        # Format with given decimal places
        formatted = f"{number:.{decimals}f}"

        # Split integer and decimal parts
        if "." in formatted:
            int_part, dec_part = formatted.split(".")
        else:
            int_part, dec_part = formatted, ""

        # Apply digit grouping
        grouped = self._group_digits(int_part, locale_info.grouping_sep)

        # Reassemble
        if dec_part:
            return f"{grouped}{locale_info.decimal_sep}{dec_part}"
        return grouped

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
            ISO 4217 currency code.
        locale : str, optional
            Locale code.

        Returns
        -------
        str
        """
        target_locale = self._resolve_locale(locale)
        locale_info = self._get_locale_info(target_locale)

        # Format number with 2 decimal places
        num_str = self.format_number(amount, decimals=2, locale=target_locale)

        # Determine currency symbol
        currency_symbol = self._get_currency_symbol(currency, locale_info)

        # Format depends on locale conventions
        # Typical patterns: symbol + number, number + symbol, symbol + space + number
        currency_formats = {
            "en_US": f"{currency_symbol}{num_str}",
            "zh_CN": f"¥{num_str}",
            "ja_JP": f"¥{num_str}",
            "ko_KR": f"{num_str}원",
            "fr_FR": f"{num_str} {currency_symbol}",
            "de_DE": f"{num_str} {currency_symbol}",
            "es_ES": f"{num_str} {currency_symbol}",
            "ru_RU": f"{num_str} {currency_symbol}",
            "ar_SA": f"{currency_symbol}{num_str}",
            "pt_BR": f"{currency_symbol}{num_str}",
        }

        return currency_formats.get(target_locale, f"{currency_symbol}{num_str}")

    def format_percent(
        self,
        value: float,
        decimals: int = 1,
        locale: str | None = None,
    ) -> str:
        """Format a percentage value.

        Parameters
        ----------
        value : float
            The ratio (e.g. 0.25 for 25%).
        decimals : int, optional
            Decimal places.
        locale : str, optional
            Locale code.

        Returns
        -------
        str
        """
        target_locale = self._resolve_locale(locale)
        percentage = value * 100
        num_str = self.format_number(percentage, decimals=decimals, locale=target_locale)

        percent_formats = {
            "fr_FR": f"{num_str} %",
            "de_DE": f"{num_str} %",
            "es_ES": f"{num_str} %",
            "ru_RU": f"{num_str} %",
            "pt_BR": f"{num_str}%",
            "ar_SA": f"{num_str}%",
        }

        return percent_formats.get(target_locale, f"{num_str}%")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_locale(self, locale: str | None) -> str:
        """Resolve locale, falling back to default."""
        return locale if locale and locale in SUPPORTED_LOCALES else self._default_locale

    def _get_locale_info(self, locale: str) -> LocaleInfo:
        """Get LocaleInfo for a locale, falling back to en_US."""
        if locale in SUPPORTED_LOCALES:
            raw = SUPPORTED_LOCALES[locale]
            return LocaleInfo(code=locale, **raw)
        raw = SUPPORTED_LOCALES["en_US"]
        return LocaleInfo(code="en_US", **raw)

    def _parse_date(
        self,
        value: str | int | float | datetime.datetime | datetime.date | datetime.time,
    ) -> datetime.datetime:
        """Parse various date/time representations into a datetime."""
        if isinstance(value, datetime.datetime):
            return value
        if isinstance(value, datetime.date):
            return datetime.datetime.combine(value, datetime.time.min)
        if isinstance(value, datetime.time):
            now = datetime.datetime.now()
            return datetime.datetime.combine(now.date(), value)
        if isinstance(value, (int, float)):
            return datetime.datetime.fromtimestamp(value)
        if isinstance(value, str):
            # Try ISO-8601
            try:
                if "T" in value:
                    return datetime.datetime.fromisoformat(value)
                return datetime.datetime.fromisoformat(value)
            except (ValueError, TypeError):
                pass
            # Try common date formats
            for fmt in [
                "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y%m%d", "%d.%m.%Y", "%Y.%m.%d",
            ]:
                try:
                    return datetime.datetime.strptime(value, fmt)
                except ValueError:
                    continue
            raise ValueError(f"Unable to parse date string: {value!r}")
        raise TypeError(f"Unsupported date type: {type(value).__name__}")

    def _apply_date_pattern(
        self,
        dt: datetime.datetime,
        pattern: str,
        locale: str,
        format_str: str,
    ) -> str:
        """Apply a date pattern to a datetime object."""
        # Get month names for this locale
        month_names = self.MONTH_NAMES.get(locale, self.MONTH_NAMES["en_US"])
        month_names_short = self.MONTH_NAMES_SHORT.get(locale, self.MONTH_NAMES_SHORT["en_US"])
        day_names = self.DAY_NAMES.get(locale, self.DAY_NAMES["en_US"])
        day_names_short = self.DAY_NAMES_SHORT.get(locale, self.DAY_NAMES_SHORT["en_US"])

        y = dt.year
        m = dt.month
        d = dt.day
        wd = dt.weekday()  # 0=Monday

        # Map weekday to 0=Sunday for day name arrays
        wd_sun = (wd + 1) % 7

        result = pattern
        result = result.replace("YYYY", str(y))
        result = result.replace("YY", str(y)[-2:])
        result = result.replace("MMMM", month_names[m - 1])
        result = result.replace("MMM", month_names_short[m - 1])
        result = result.replace("M", str(m))
        result = result.replace("DD", f"{d:02d}")
        result = result.replace("D", str(d))
        result = result.replace("EEEE", day_names[wd_sun])
        result = result.replace("E", day_names_short[wd_sun])

        # Handle Chinese weekday
        if locale == "zh_CN":
            chinese_weekdays = ["日", "一", "二", "三", "四", "五", "六"]
            result = result.replace("星期E", f"星期{chinese_weekdays[wd_sun]}")

        return result

    def _apply_time_pattern(
        self,
        dt: datetime.datetime,
        pattern: str,
        locale: str,
    ) -> str:
        """Apply a time pattern to a datetime object."""
        h = dt.hour
        m = dt.minute
        s = dt.second

        # 12-hour clock
        h12 = h % 12
        if h12 == 0:
            h12 = 12
        am_pm = "AM" if h < 12 else "PM"

        result = pattern
        result = result.replace("HH", f"{h:02d}")
        result = result.replace("H", str(h))
        result = result.replace("hh", f"{h12:02d}")
        result = result.replace("h", str(h12))
        result = result.replace("mm", f"{m:02d}")
        result = result.replace("ss", f"{s:02d}")
        result = result.replace("A", am_pm)
        result = result.replace("z", "UTC")

        return result

    @staticmethod
    def _group_digits(int_part: str, sep: str) -> str:
        """Group digits with the locale separator.

        Parameters
        ----------
        int_part : str
            The integer part as a string of digits.
        sep : str
            Grouping separator character.

        Returns
        -------
        str
        """
        if len(int_part) <= 3:
            return int_part

        # Group from right to left
        groups: list[str] = []
        for i in range(len(int_part) - 3, -3, -3):
            start = max(0, i)
            groups.insert(0, int_part[start:start + 3])
        if len(int_part) % 3 != 0:
            groups.insert(0, int_part[:len(int_part) % 3])

        return sep.join(groups)

    @staticmethod
    def _get_currency_symbol(currency: str, locale_info: LocaleInfo) -> str:
        """Get the currency symbol for a currency code."""
        # Map currency codes to symbols
        currency_map: dict[str, str] = {
            "USD": "$",
            "EUR": "€",
            "GBP": "£",
            "JPY": "¥",
            "CNY": "¥",
            "KRW": "₩",
            "RUB": "₽",
            "BRL": "R$",
            "INR": "₹",
            "CAD": "CA$",
            "AUD": "A$",
            "CHF": "CHF",
            "SEK": "kr",
            "NOK": "kr",
            "DKK": "kr",
            "PLN": "zł",
            "TRY": "₺",
            "MXN": "MX$",
            "TWD": "NT$",
            "HKD": "HK$",
            "SGD": "S$",
            "NZD": "NZ$",
            "ZAR": "R",
            "SAR": "﷼",
            "AED": "د.إ",
            "ARS": "$",
            "CLP": "$",
            "COP": "$",
            "EGP": "E£",
            "IDR": "Rp",
            "ILS": "₪",
            "MYR": "RM",
            "PHP": "₱",
            "THB": "฿",
            "VND": "₫",
        }
        return currency_map.get(currency.upper(), locale_info.currency_symbol)

    def __repr__(self) -> str:
        return f"Formatter(default_locale={self._default_locale!r})"