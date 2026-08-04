"""
GNU Gettext Loader
==================

Loads translations from GNU gettext ``.mo`` and ``.po`` files.

Supports both compiled (``.mo``) and source (``.po``) file formats.
The loader follows the standard gettext directory layout::

    <locale_dir>/
    ├── zh_CN/
    │   └── LC_MESSAGES/
    │       ├── messages.po
    │       ├── messages.mo
    │       ├── errors.po
    │       └── errors.mo
    ├── en_US/
    │   └── LC_MESSAGES/
    │       └── ...
    └── ...

``.mo`` files are preferred over ``.po`` files when both exist.
"""

from __future__ import annotations

import os
import re
import glob
import struct
import logging
from typing import Any

from ainos_i18n.loaders.base import Loader, LoaderError, LoaderNotFoundError, LoaderParseError

logger = logging.getLogger(__name__)


class GettextLoader(Loader):
    """Load translations from GNU gettext ``.mo`` / ``.po`` files.

    Parameters
    ----------
    source_dir : str, optional
        Base directory for locale data.
    domain : str, optional
        Gettext domain name. Defaults to ``"messages"``.
    use_mo : bool, optional
        Prefer ``.mo`` files over ``.po``. Defaults to True.
    encoding : str, optional
        File encoding for ``.po`` files. Defaults to ``"utf-8"``.
    """

    def __init__(
        self,
        source_dir: str | None = None,
        domain: str = "messages",
        use_mo: bool = True,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__(source_dir)
        self._domain = domain
        self._use_mo = use_mo
        self._encoding = encoding
        self._cache: dict[str, dict[str, Any]] = {}

    # ---- Loader API ----

    def load(self, locale: str) -> dict[str, Any]:
        """Load translations for a locale from gettext files.

        Parameters
        ----------
        locale : str
            Locale code.

        Returns
        -------
        dict[str, Any]
        """
        if locale in self._cache:
            return dict(self._cache[locale])

        locale_dir = self._find_locale_dir(locale)
        if not locale_dir:
            logger.warning("Gettext locale directory not found for: %s", locale)
            return {}

        # .mo directory: locale_dir/LC_MESSAGES/
        mo_dir = os.path.join(locale_dir, "LC_MESSAGES")
        if not os.path.isdir(mo_dir):
            # Try without LC_MESSAGES
            mo_dir = locale_dir

        # Find all .mo and .po files
        merged: dict[str, Any] = {}
        loaded_files: list[str] = []

        # Try loading .mo files
        if self._use_mo:
            mo_files = sorted(glob.glob(os.path.join(mo_dir, "*.mo")))
            for file_path in mo_files:
                try:
                    data = self._load_mo(file_path)
                    merged.update(data)
                    loaded_files.append(file_path)
                except Exception as exc:
                    logger.warning("Failed to load .mo file %s: %s", file_path, exc)

        # Also load .po files (for keys not in .mo)
        po_files = sorted(glob.glob(os.path.join(mo_dir, "*.po")))
        for file_path in po_files:
            try:
                data = self._load_po(file_path)
                # Only add keys not already loaded
                for k, v in data.items():
                    if k not in merged:
                        merged[k] = v
                loaded_files.append(file_path)
            except Exception as exc:
                logger.warning("Failed to load .po file %s: %s", file_path, exc)

        self._cache[locale] = dict(merged)
        if loaded_files:
            logger.info("Loaded %d keys for locale '%s' from %d gettext files", len(merged), locale, len(loaded_files))
        return merged

    def get_available_locales(self) -> list[str]:
        """Get list of locales with gettext files.

        Returns
        -------
        list[str]
        """
        if not self._source_dir or not os.path.isdir(self._source_dir):
            return []

        locales: list[str] = []
        for entry in sorted(os.listdir(self._source_dir)):
            path = os.path.join(self._source_dir, entry)
            # Check for LC_MESSAGES subdirectory
            lc_messages = os.path.join(path, "LC_MESSAGES")
            if os.path.isdir(lc_messages):
                if glob.glob(os.path.join(lc_messages, "*.mo")) or glob.glob(os.path.join(lc_messages, "*.po")):
                    locales.append(entry)
            elif os.path.isdir(path):
                if glob.glob(os.path.join(path, "*.mo")) or glob.glob(os.path.join(path, "*.po")):
                    locales.append(entry)
        return locales

    # ---- .mo file parsing ----

    def _load_mo(self, file_path: str) -> dict[str, str]:
        """Parse a binary ``.mo`` file.

        Implements the GNU MO file format specification.

        Parameters
        ----------
        file_path : str
            Path to ``.mo`` file.

        Returns
        -------
        dict[str, str]
            msgid -> msgstr mappings.

        Raises
        ------
        LoaderParseError
            If the file is invalid.
        """
        if not os.path.isfile(file_path):
            raise LoaderNotFoundError(f"File not found: {file_path}")

        try:
            with open(file_path, "rb") as f:
                data = f.read()
        except OSError as exc:
            raise LoaderNotFoundError(f"Error reading {file_path}: {exc}", cause=exc) from exc

        if len(data) < 20:
            raise LoaderParseError(f"File too small for .mo format: {file_path}")

        # Parse MO header
        magic = struct.unpack("<I", data[:4])[0]
        if magic == 0x950412DE:
            # Little-endian
            endian = "<"
        elif magic == 0xDE120495:
            # Big-endian
            endian = ">"
        else:
            raise LoaderParseError(f"Invalid .mo magic number: 0x{magic:08X} in {file_path}")

        # Read version, count, offsets
        version = struct.unpack(f"{endian}I", data[4:8])[0]
        if version not in (0, 1):
            raise LoaderParseError(f"Unsupported .mo version: {version} in {file_path}")

        num_strings = struct.unpack(f"{endian}I", data[8:12])[0]
        orig_offset = struct.unpack(f"{endian}I", data[12:16])[0]
        trans_offset = struct.unpack(f"{endian}I", data[16:20])[0]

        if num_strings == 0:
            return {}

        result: dict[str, str] = {}

        # Helper to read string table entries
        def _read_string_table(offset: int, count: int) -> list[tuple[int, int]]:
            entries: list[tuple[int, int]] = []
            for i in range(count):
                entry_offset = offset + i * 8
                if entry_offset + 8 > len(data):
                    break
                length = struct.unpack(f"{endian}I", data[entry_offset:entry_offset + 4])[0]
                str_offset = struct.unpack(f"{endian}I", data[entry_offset + 4:entry_offset + 8])[0]
                entries.append((length, str_offset))
            return entries

        # Read original strings
        orig_entries = _read_string_table(orig_offset, num_strings)
        trans_entries = _read_string_table(trans_offset, num_strings)

        for i in range(min(len(orig_entries), len(trans_entries))):
            orig_len, orig_start = orig_entries[i]
            trans_len, trans_start = trans_entries[i]

            if orig_start + orig_len > len(data) or trans_start + trans_len > len(data):
                continue

            msgid = data[orig_start:orig_start + orig_len].decode(self._encoding, errors="replace")
            msgstr = data[trans_start:trans_start + trans_len].decode(self._encoding, errors="replace")

            # Skip empty msgid (header)
            if msgid:
                result[msgid] = msgstr

        return result

    # ---- .po file parsing ----

    def _load_po(self, file_path: str) -> dict[str, str]:
        """Parse a ``.po`` file.

        Parameters
        ----------
        file_path : str
            Path to ``.po`` file.

        Returns
        -------
        dict[str, str]
            msgid -> msgstr mappings.

        Raises
        ------
        LoaderParseError
            If the file cannot be parsed.
        """
        if not os.path.isfile(file_path):
            raise LoaderNotFoundError(f"File not found: {file_path}")

        try:
            with open(file_path, "r", encoding=self._encoding) as f:
                content = f.read()
        except OSError as exc:
            raise LoaderNotFoundError(f"Error reading {file_path}: {exc}", cause=exc) from exc

        return self._parse_po_string(content)

    @staticmethod
    def _parse_po_string(content: str) -> dict[str, str]:
        """Parse a PO file string into msgid -> msgstr mappings.

        Handles:
        * Basic msgid / msgstr pairs
        * Multi-line strings (enclosed in double quotes)
        * msgid_plural / msgstr[0], msgstr[1], ... (plural forms)
        * Comments and blank lines
        * Escape sequences
        """
        result: dict[str, str] = {}

        # Current entry being parsed
        current_msgid: str | None = None
        current_msgid_plural: str | None = None
        current_msgstr: str | None = None
        current_msgstr_plural: dict[int, str] = {}
        in_msgid = False
        in_msgstr = False
        in_msgid_plural = False
        in_msgstr_plural = False
        msgstr_plural_idx: int = -1

        # Pattern for matching PO entry lines
        msgid_pattern = re.compile(r'^msgid\s+"(.*)"\s*$')
        msgid_plural_pattern = re.compile(r'^msgid_plural\s+"(.*)"\s*$')
        msgstr_pattern = re.compile(r'^msgstr\s+"(.*)"\s*$')
        msgstr_plural_pattern = re.compile(r'^msgstr\[(\d+)\]\s+"(.*)"\s*$')
        continuation_pattern = re.compile(r'^"(.*)"\s*$')

        for line in content.splitlines():
            line = line.strip()

            # Skip comments and empty lines
            if not line or line.startswith("#"):
                # Flush current entry when hitting a comment
                if current_msgid is not None and current_msgstr is not None:
                    result[current_msgid] = current_msgstr
                elif current_msgid is not None and current_msgstr_plural:
                    # Store plural forms as a JSON string
                    import json
                    result[current_msgid] = json.dumps(current_msgstr_plural, ensure_ascii=False)
                elif current_msgid_plural is not None and current_msgstr_plural:
                    result[current_msgid_plural] = json.dumps(current_msgstr_plural, ensure_ascii=False)

                current_msgid = None
                current_msgid_plural = None
                current_msgstr = None
                current_msgstr_plural = {}
                in_msgid = False
                in_msgstr = False
                in_msgid_plural = False
                in_msgstr_plural = False
                continue

            # Match msgid
            m = msgid_pattern.match(line)
            if m:
                # Flush previous entry
                if current_msgid is not None and current_msgstr is not None:
                    result[current_msgid] = current_msgstr
                elif current_msgid is not None and current_msgstr_plural:
                    import json
                    result[current_msgid] = json.dumps(current_msgstr_plural, ensure_ascii=False)

                current_msgid = GettextLoader._unescape_po_string(m.group(1))
                current_msgstr = None
                current_msgstr_plural = {}
                in_msgid = True
                in_msgstr = False
                in_msgid_plural = False
                in_msgstr_plural = False
                continue

            # Match msgid_plural
            m = msgid_plural_pattern.match(line)
            if m:
                current_msgid_plural = GettextLoader._unescape_po_string(m.group(1))
                in_msgid = False
                in_msgid_plural = True
                continue

            # Match msgstr (singular)
            m = msgstr_pattern.match(line)
            if m:
                current_msgstr = GettextLoader._unescape_po_string(m.group(1))
                in_msgstr = True
                in_msgid = False
                in_msgid_plural = False
                in_msgstr_plural = False
                continue

            # Match msgstr[0], msgstr[1], etc.
            m = msgstr_plural_pattern.match(line)
            if m:
                idx = int(m.group(1))
                text = GettextLoader._unescape_po_string(m.group(2))
                current_msgstr_plural[idx] = text
                in_msgstr_plural = True
                in_msgstr = False
                in_msgid = False
                in_msgid_plural = False
                continue

            # Continuation line
            m = continuation_pattern.match(line)
            if m:
                text = GettextLoader._unescape_po_string(m.group(1))
                if in_msgid and current_msgid is not None:
                    current_msgid += text
                elif in_msgid_plural and current_msgid_plural is not None:
                    current_msgid_plural += text
                elif in_msgstr and current_msgstr is not None:
                    current_msgstr += text
                elif in_msgstr_plural and current_msgstr_plural:
                    max_idx = max(current_msgstr_plural.keys()) if current_msgstr_plural else 0
                    current_msgstr_plural[max_idx] = current_msgstr_plural.get(max_idx, "") + text

        # Flush last entry
        if current_msgid is not None and current_msgstr is not None:
            result[current_msgid] = current_msgstr
        elif current_msgid is not None and current_msgstr_plural:
            import json
            result[current_msgid] = json.dumps(current_msgstr_plural, ensure_ascii=False)
        elif current_msgid_plural is not None and current_msgstr_plural:
            import json
            result[current_msgid_plural] = json.dumps(current_msgstr_plural, ensure_ascii=False)

        return result

    @staticmethod
    def _unescape_po_string(s: str) -> str:
        """Unescape a PO string, handling C-style escape sequences.

        Handles: ``\\n``, ``\\t``, ``\\r``, ``\\\"``, ``\\\\``, ``\\`` at
        end of line (continuation), and octal/hex escapes.
        """
        result = s
        # Handle escaped characters
        replacements = [
            ("\\\\", "\\"),
            ("\\n", "\n"),
            ("\\t", "\t"),
            ("\\r", "\r"),
            ('\\"', '"'),
        ]
        for escaped, actual in replacements:
            result = result.replace(escaped, actual)
        return result

    # ---- Internal ----

    def _find_locale_dir(self, locale: str) -> str | None:
        """Search for a gettext locale directory."""
        search_paths = [
            self._source_dir,
            os.path.join(os.path.dirname(__file__), "..", "locales"),
            os.path.join(os.getcwd(), "locales"),
            os.path.join(os.getcwd(), "i18n", "locales"),
        ]

        for base in search_paths:
            if base:
                # Direct check for locale directory
                candidate = os.path.join(base, locale)
                if os.path.isdir(candidate):
                    return candidate
                # Check for LC_MESSAGES inside
                lc_candidate = os.path.join(base, locale, "LC_MESSAGES")
                if os.path.isdir(lc_candidate):
                    return os.path.join(base, locale)
        return None

    def __repr__(self) -> str:
        return (
            f"GettextLoader(source_dir={self._source_dir!r}, "
            f"domain={self._domain!r}, use_mo={self._use_mo})"
        )