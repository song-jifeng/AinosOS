"""
Translation Extraction Tool
============================

Extracts translatable strings from source code files.

Supports multiple source file types:
* Python (``.py``) -- ``_()``, ``i18n.t()``, ``i18n.n()`` calls
* JavaScript/TypeScript (``.js``, ``.ts``, ``.jsx``, ``.tsx``) -- ``t()``, ``i18n()`` calls
* HTML templates (``.html``, ``.htm``)
* Vue (``.vue``) -- template and script sections
* React (``.jsx``, ``.tsx``) -- JSX attributes and function calls

Produces a structured output (JSON or POT) that can be used as input
for translation management.
"""

from __future__ import annotations

import os
import re
import json
import glob
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ExtractionTool:
    """Extract translatable strings from source code files.

    Parameters
    ----------
    source_dir : str
        Root directory of the source code to scan.
    output_file : str, optional
        Path to write the extraction results. If None, results are
        returned in memory.
    file_patterns : list[str], optional
        Glob patterns for files to scan. Defaults to common source files.
    """

    # Default file patterns to scan
    DEFAULT_PATTERNS: list[str] = [
        "**/*.py",
        "**/*.js",
        "**/*.ts",
        "**/*.jsx",
        "**/*.tsx",
        "**/*.vue",
        "**/*.html",
        "**/*.htm",
        "**/*.java",
        "**/*.kt",
        "**/*.swift",
        "**/*.rb",
        "**/*.php",
    ]

    # Patterns to exclude
    EXCLUDE_PATTERNS: list[str] = [
        "**/node_modules/**",
        "**/venv/**",
        "**/.venv/**",
        "**/__pycache__/**",
        "**/.git/**",
        "**/dist/**",
        "**/build/**",
        "**/.next/**",
        "**/target/**",
        "**/vendor/**",
        "**/bower_components/**",
        "**/*.min.*",
        "**/*.bundle.*",
    ]

    def __init__(
        self,
        source_dir: str,
        output_file: str | None = None,
        file_patterns: list[str] | None = None,
    ) -> None:
        self._source_dir = source_dir
        self._output_file = output_file
        self._file_patterns = file_patterns or list(self.DEFAULT_PATTERNS)

    # ---- Extraction ----

    def extract(
        self,
        locale: str = "en_US",
        mark_as_extracted: bool = False,
    ) -> dict[str, Any]:
        """Extract all translatable strings from source files.

        Parameters
        ----------
        locale : str, optional
            Locale to use as the source language reference.
        mark_as_extracted : bool, optional
            If True, add extraction metadata to output.

        Returns
        -------
        dict[str, Any]
            Extracted strings with metadata:
            ``{"strings": {...}, "meta": {...}}``
        """
        source_files = self._find_source_files()
        extracted: dict[str, dict[str, Any]] = {}

        for file_path in source_files:
            try:
                file_strings = self._extract_from_file(file_path)
                for key, info in file_strings.items():
                    if key not in extracted:
                        extracted[key] = {
                            "locations": [],
                            "contexts": set(),
                            "files": set(),
                        }
                    extracted[key]["locations"].append({
                        "file": os.path.relpath(file_path, self._source_dir),
                        "line": info["line"],
                        "column": info.get("column", 0),
                    })
                    if info.get("context"):
                        extracted[key]["contexts"].add(info["context"])
                    extracted[key]["files"].add(os.path.relpath(file_path, self._source_dir))
            except Exception as exc:
                logger.warning("Error extracting from %s: %s", file_path, exc)

        # Convert sets to lists for JSON serialization
        result_strings: dict[str, dict[str, Any]] = {}
        for key, info in extracted.items():
            result_strings[key] = {
                "locations": info["locations"],
                "contexts": list(info["contexts"]),
                "files": list(info["files"]),
            }

        result: dict[str, Any] = {
            "strings": result_strings,
            "meta": {
                "locale": locale,
                "source_dir": self._source_dir,
                "files_scanned": len(source_files),
                "strings_found": len(result_strings),
                "extracted_at": self._get_timestamp(),
            },
        }

        if mark_as_extracted:
            result["meta"]["extracted"] = True

        # Write output if file specified
        if self._output_file:
            os.makedirs(os.path.dirname(self._output_file) or ".", exist_ok=True)
            with open(self._output_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            logger.info("Extraction results written to: %s", self._output_file)

        return result

    def extract_to_pot(self, output_file: str | None = None) -> str:
        """Extract strings and output in GNU gettext POT format.

        Parameters
        ----------
        output_file : str, optional
            Path to write the POT file.

        Returns
        -------
        str
            POT format content.
        """
        extracted = self.extract()
        lines: list[str] = [
            '# Ainos i18n Translation Template',
            '# Generated by Ainos i18n Extraction Tool',
            f'# Date: {self._get_timestamp()}',
            '#',
            'msgid ""',
            'msgstr ""',
            '"Project-Id-Version: AinosOS\\n"',
            '"MIME-Version: 1.0\\n"',
            '"Content-Type: text/plain; charset=UTF-8\\n"',
            '"Content-Transfer-Encoding: 8bit\\n"',
            '"Plural-Forms: nplurals=2; plural=(n != 1);\\n"',
            '',
        ]

        for key, info in sorted(extracted["strings"].items()):
            # Add location comments
            for loc in info["locations"]:
                lines.append(f'#: {loc["file"]}:{loc["line"]}')

            # Add context if any
            if info["contexts"]:
                for ctx in info["contexts"]:
                    lines.append(f'#. context: {ctx}')

            # Escape the key for POT format
            escaped_key = self._escape_pot(key)
            lines.append(f'msgid "{escaped_key}"')
            lines.append('msgstr ""')
            lines.append('')

        content = "\n".join(lines)

        out_path = output_file or self._output_file
        if out_path:
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info("POT file written to: %s", out_path)

        return content

    # ---- Internal extraction logic ----

    def _find_source_files(self) -> list[str]:
        """Find all source files matching the configured patterns."""
        files: list[str] = []
        for pattern in self._file_patterns:
            matched = glob.glob(
                os.path.join(self._source_dir, pattern),
                recursive=True,
            )
            for file_path in matched:
                if os.path.isfile(file_path) and not self._is_excluded(file_path):
                    files.append(file_path)
        return sorted(set(files))

    def _is_excluded(self, file_path: str) -> bool:
        """Check if a file path matches any exclusion pattern."""
        rel_path = os.path.relpath(file_path, self._source_dir)
        for pattern in self.EXCLUDE_PATTERNS:
            if glob.fnmatch.fnmatch(rel_path, pattern):
                return True
            # Also check with forward slashes for cross-platform
            if glob.fnmatch.fnmatch(rel_path.replace("\\", "/"), pattern.replace("\\", "/")):
                return True
        return False

    def _extract_from_file(self, file_path: str) -> dict[str, dict[str, Any]]:
        """Extract translatable strings from a single file.

        Dispatches to language-specific extractors based on file extension.
        """
        ext = os.path.splitext(file_path)[1].lower()
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        extractors = {
            ".py": self._extract_python,
            ".js": self._extract_javascript,
            ".ts": self._extract_javascript,
            ".jsx": self._extract_javascript,
            ".tsx": self._extract_javascript,
            ".vue": self._extract_vue,
            ".html": self._extract_html,
            ".htm": self._extract_html,
            ".java": self._extract_java,
            ".kt": self._extract_java,
            ".swift": self._extract_swift,
            ".rb": self._extract_ruby,
            ".php": self._extract_php,
        }

        extractor = extractors.get(ext)
        if extractor is None:
            # Try generic extraction
            return self._extract_generic(content, file_path)

        return extractor(content, file_path)

    # ---- Language-specific extractors ----

    PYTHON_PATTERNS = [
        # _("string") or _('string')
        re.compile(r'(?<!\w)_\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*\)'),
        # i18n.t("string", ...)
        re.compile(r'i18n\.t\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*[,\)]'),
        # i18n.n("string", ...)
        re.compile(r'i18n\.n\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*,'),
        # translator.translate("string", ...)
        re.compile(r'translate\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*[,\)]'),
        # gettext.gettext("string")
        re.compile(r'gettext\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*\)'),
        # lazy_gettext("string")
        re.compile(r'lazy_gettext\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*\)'),
        # _p("context|string")  (context-aware)
        re.compile(r'_p\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*\)'),
    ]

    def _extract_python(self, content: str, file_path: str) -> dict[str, dict[str, Any]]:
        """Extract from Python source files."""
        result: dict[str, dict[str, Any]] = {}
        lines = content.split("\n")

        for line_no, line in enumerate(lines, 1):
            for pattern in self.PYTHON_PATTERNS:
                for m in pattern.finditer(line):
                    key = self._clean_string(m.group(1))
                    if key:
                        info: dict[str, Any] = {
                            "line": line_no,
                            "column": m.start() + 1,
                            "context": "",
                        }
                        # Check for context-aware pattern
                        if m.re == self.PYTHON_PATTERNS[-1] and "|" in key:
                            parts = key.split("|", 1)
                            info["context"] = parts[0]
                            key = parts[1]
                        result[key] = info
        return result

    JAVASCRIPT_PATTERNS = [
        # t("string") or t('string')
        re.compile(r'(?<!\w)t\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*[,\)]'),
        # i18n.t("string")
        re.compile(r'i18n\.t\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*[,\)]'),
        # $t("string") (Vue)
        re.compile(r'\$t\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*[,\)]'),
        # __("string")
        re.compile(r'__\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*[,\)]'),
        # trans("string")
        re.compile(r'trans\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*[,\)]'),
        # formatMessage({ id: "string" })
        re.compile(r'(?:id|defaultMessage):\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')'),
        # <FormattedMessage id="string" />
        re.compile(r'<FormattedMessage[^>]*\sid\s*=\s*("(?:[^"\\]|\\.)*")'),
        # intl.formatMessage({ id: "string" })
        re.compile(r'formatMessage\(\s*\{\s*id:\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')'),
    ]

    def _extract_javascript(self, content: str, file_path: str) -> dict[str, dict[str, Any]]:
        """Extract from JavaScript/TypeScript source files."""
        result: dict[str, dict[str, Any]] = {}
        lines = content.split("\n")

        for line_no, line in enumerate(lines, 1):
            for pattern in self.JAVASCRIPT_PATTERNS:
                for m in pattern.finditer(line):
                    key = self._clean_string(m.group(1))
                    if key:
                        result[key] = {
                            "line": line_no,
                            "column": m.start() + 1,
                            "context": "",
                        }
        return result

    def _extract_vue(self, content: str, file_path: str) -> dict[str, dict[str, Any]]:
        """Extract from Vue single-file components."""
        result: dict[str, dict[str, Any]] = {}

        # Extract from <template> section
        template_match = re.search(r'<template>(.*?)</template>', content, re.DOTALL)
        if template_match:
            template_content = template_match.group(1)
            result.update(self._extract_html(template_content, file_path))

        # Extract from <script> section
        script_match = re.search(r'<script[^>]*>(.*?)</script>', content, re.DOTALL)
        if script_match:
            script_content = script_match.group(1)
            result.update(self._extract_javascript(script_content, file_path))

        # Adjust line numbers for template section
        if template_match:
            offset = content[:template_match.start()].count("\n") + 1
            for key in result:
                if "line" in result[key]:
                    result[key]["line"] += offset

        return result

    HTML_PATTERNS = [
        # {{ "string" | trans }} (Twig/Symfony)
        re.compile(r'\{\{\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*\|'),
        # {% trans %}string{% endtrans %}
        re.compile(r'\{%\s*trans\s*%\}(.*?)\{%\s*endtrans\s*%\}', re.DOTALL),
        # data-i18n attribute
        re.compile(r'data-i18n\s*=\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')'),
        # title attribute with i18n marker
        re.compile(r'i18n-title\s*=\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')'),
        # placeholder attribute with i18n marker
        re.compile(r'i18n-placeholder\s*=\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')'),
    ]

    def _extract_html(self, content: str, file_path: str) -> dict[str, dict[str, Any]]:
        """Extract from HTML templates."""
        result: dict[str, dict[str, Any]] = {}
        lines = content.split("\n")

        for line_no, line in enumerate(lines, 1):
            for pattern in self.HTML_PATTERNS:
                for m in pattern.finditer(line):
                    key = self._clean_string(m.group(1))
                    if key:
                        result[key] = {
                            "line": line_no,
                            "column": m.start() + 1,
                            "context": "",
                        }

        # Extract {% trans %}...{% endtrans %} blocks
        for m in self.HTML_PATTERNS[1].finditer(content):
            key = m.group(1).strip()
            if key:
                line_no = content[:m.start()].count("\n") + 1
                result[key] = {
                    "line": line_no,
                    "column": 1,
                    "context": "",
                }

        return result

    def _extract_java(self, content: str, file_path: str) -> dict[str, dict[str, Any]]:
        """Extract from Java/Kotlin source files."""
        result: dict[str, dict[str, Any]] = {}
        lines = content.split("\n")

        patterns = [
            re.compile(r'getString\(\s*("(?:[^"\\]|\\.)*")\s*[,\)]'),
            re.compile(r'Resources\.getString\(\s*("(?:[^"\\]|\\.)*")\s*[,\)]'),
            re.compile(r'@StringRes\s+(\w+)\s*=\s*R\.string\.(\w+)'),
            re.compile(r'[Rr]\.string\.(\w+)'),
            re.compile(r'i18n\(\s*("(?:[^"\\]|\\.)*")\s*[,\)]'),
        ]

        for line_no, line in enumerate(lines, 1):
            for pattern in patterns:
                for m in pattern.finditer(line):
                    key = m.group(1) if m.lastindex >= 1 else m.group(0)
                    key = self._clean_string(key)
                    if key:
                        result[key] = {"line": line_no, "column": m.start() + 1, "context": ""}
        return result

    def _extract_swift(self, content: str, file_path: str) -> dict[str, dict[str, Any]]:
        """Extract from Swift source files."""
        result: dict[str, dict[str, Any]] = {}
        lines = content.split("\n")

        patterns = [
            re.compile(r'NSLocalizedString\(\s*("(?:[^"\\]|\\.)*")\s*[,\)]'),
            re.compile(r'LocalizedStringKey\(\s*("(?:[^"\\]|\\.)*")\s*[,\)]'),
            re.compile(r'LocalizedStringResource\(\s*("(?:[^"\\]|\\.)*")\s*[,\)]'),
            re.compile(r'String\.init\(\s*localized:\s*("(?:[^"\\]|\\.)*")\s*[,\)]'),
            re.compile(r'Text\(\s*("(?:[^"\\]|\\.)*")\s*[,\)]'),
        ]

        for line_no, line in enumerate(lines, 1):
            for pattern in patterns:
                for m in pattern.finditer(line):
                    key = self._clean_string(m.group(1))
                    if key:
                        result[key] = {"line": line_no, "column": m.start() + 1, "context": ""}
        return result

    def _extract_ruby(self, content: str, file_path: str) -> dict[str, dict[str, Any]]:
        """Extract from Ruby source files."""
        result: dict[str, dict[str, Any]] = {}
        lines = content.split("\n")

        patterns = [
            re.compile(r'I18n\.t\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*[,\)]'),
            re.compile(r'I18n\.translate\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*[,\)]'),
            re.compile(r't\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*[,\)]'),
            re.compile(r'l\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*[,\)]'),
        ]

        for line_no, line in enumerate(lines, 1):
            for pattern in patterns:
                for m in pattern.finditer(line):
                    key = self._clean_string(m.group(1))
                    if key:
                        result[key] = {"line": line_no, "column": m.start() + 1, "context": ""}
        return result

    def _extract_php(self, content: str, file_path: str) -> dict[str, dict[str, Any]]:
        """Extract from PHP source files."""
        result: dict[str, dict[str, Any]] = {}
        lines = content.split("\n")

        patterns = [
            re.compile(r'__\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*[,\)]'),
            re.compile(r'_e\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*[,\)]'),
            re.compile(r'\$this->lang->line\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*[,\)]'),
            re.compile(r'trans\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*[,\)]'),
            re.compile(r'gettext\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*\)'),
        ]

        for line_no, line in enumerate(lines, 1):
            for pattern in patterns:
                for m in pattern.finditer(line):
                    key = self._clean_string(m.group(1))
                    if key:
                        result[key] = {"line": line_no, "column": m.start() + 1, "context": ""}
        return result

    def _extract_generic(self, content: str, file_path: str) -> dict[str, dict[str, Any]]:
        """Generic extraction: look for common translation function calls."""
        result: dict[str, dict[str, Any]] = {}
        lines = content.split("\n")

        pattern = re.compile(r'[_\$]?[tT]\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*[,\)]')

        for line_no, line in enumerate(lines, 1):
            for m in pattern.finditer(line):
                key = self._clean_string(m.group(1))
                if key and len(key) > 2 and len(key) < 500:
                    result[key] = {"line": line_no, "column": m.start() + 1, "context": ""}
        return result

    # ---- Utility methods ----

    @staticmethod
    def _clean_string(s: str) -> str:
        """Clean a quoted string by removing surrounding quotes and unescaping."""
        if not s or len(s) < 2:
            return ""

        # Remove surrounding quotes
        if s[0] in ('"', "'") and s[-1] == s[0]:
            s = s[1:-1]

        # Unescape common escape sequences
        s = s.replace("\\n", "\n")
        s = s.replace("\\t", "\t")
        s = s.replace("\\r", "\r")
        s = s.replace('\\"', '"')
        s = s.replace("\\'", "'")
        s = s.replace("\\\\", "\\")

        return s.strip()

    @staticmethod
    def _escape_pot(s: str) -> str:
        """Escape a string for POT format."""
        s = s.replace("\\", "\\\\")
        s = s.replace('"', '\\"')
        s = s.replace("\n", "\\n")
        s = s.replace("\r", "\\r")
        s = s.replace("\t", "\\t")
        return s

    @staticmethod
    def _get_timestamp() -> str:
        """Get current timestamp string."""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def __repr__(self) -> str:
        return (
            f"ExtractionTool(source_dir={self._source_dir!r}, "
            f"output_file={self._output_file!r})"
        )