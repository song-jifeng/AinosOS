#!/usr/bin/env python3
"""
AI-Powered Security Auditing Tool.

A comprehensive static analysis tool for detecting common security vulnerabilities
in source code, including SQL injection, XSS, command injection, path traversal,
and weak credentials. Supports multiple output formats (JSON, HTML, SARIF) and
batch directory scanning with configurable exclusion patterns.

Usage:
    python ai_security.py scan <target> [options]
    python ai_security.py config [options]

Example:
    python ai_security.py scan /path/to/project --output report.json --format json
    python ai_security.py scan /path/to/project --exclude "*.min.js" --severity HIGH
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import html
import json
import logging
import os
import re
import sys
import time
import traceback
from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Pattern, Set, Tuple, Union

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ai_security")


# ---------------------------------------------------------------------------
# Severity enumeration
# ---------------------------------------------------------------------------

class Severity:
    """Severity levels for security findings."""

    CRITICAL: str = "CRITICAL"
    HIGH: str = "HIGH"
    MEDIUM: str = "MEDIUM"
    LOW: str = "LOW"
    INFO: str = "INFO"

    _ORDER: Dict[str, int] = {
        CRITICAL: 5,
        HIGH: 4,
        MEDIUM: 3,
        LOW: 2,
        INFO: 1,
    }

    @classmethod
    def levels(cls) -> List[str]:
        """Return all severity levels ordered from most to least severe."""
        return [cls.CRITICAL, cls.HIGH, cls.MEDIUM, cls.LOW, cls.INFO]

    @classmethod
    def from_int(cls, value: int) -> str:
        """Convert an integer severity score to a label."""
        if value >= 9:
            return cls.CRITICAL
        elif value >= 7:
            return cls.HIGH
        elif value >= 5:
            return cls.MEDIUM
        elif value >= 3:
            return cls.LOW
        return cls.INFO

    @classmethod
    def numeric(cls, severity: str) -> int:
        """Return the numeric weight of a severity label."""
        return cls._ORDER.get(severity, 0)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    """A single security finding / vulnerability detected in source code."""

    rule_id: str
    severity: str
    message: str
    file_path: str
    line_number: int
    column: int = 0
    snippet: str = ""
    confidence: float = 1.0  # 0.0 – 1.0
    recommendation: str = ""
    cwe: str = ""
    detector: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the finding to a dictionary."""
        return asdict(self)

    def to_sarif(self) -> Dict[str, Any]:
        """Convert the finding to a SARIF result object."""
        return {
            "ruleId": self.rule_id,
            "level": "error" if self.severity in (Severity.CRITICAL, Severity.HIGH) else "warning",
            "message": {"text": self.message},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": self.file_path},
                        "region": {
                            "startLine": self.line_number,
                            "startColumn": max(self.column, 1),
                        },
                    }
                }
            ],
            "properties": {
                "severity": self.severity,
                "confidence": self.confidence,
                "cwe": self.cwe,
                "detector": self.detector,
                "recommendation": self.recommendation,
            },
        }


@dataclass
class ScanResult:
    """Aggregated result of a security scan."""

    target: str
    scan_time: str = ""
    duration_seconds: float = 0.0
    total_files: int = 0
    scanned_files: int = 0
    findings: List[Finding] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> Dict[str, int]:
        """Return a severity-count summary of findings."""
        counts: Dict[str, int] = {s: 0 for s in Severity.levels()}
        for f in self.findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the scan result to a dictionary."""
        return {
            "target": self.target,
            "scan_time": self.scan_time,
            "duration_seconds": self.duration_seconds,
            "total_files": self.total_files,
            "scanned_files": self.scanned_files,
            "summary": self.summary(),
            "findings": [f.to_dict() for f in self.findings],
            "errors": self.errors,
            "config": self.config,
        }


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: Dict[str, Any] = {
    "severity_threshold": Severity.INFO,
    "exclude_patterns": [
        "*.pyc",
        "__pycache__/*",
        ".git/*",
        ".svn/*",
        ".hg/*",
        "node_modules/*",
        "vendor/*",
        ".tox/*",
        "*.egg-info/*",
        "dist/*",
        "build/*",
        ".venv/*",
        "venv/*",
        "env/*",
        ".env/*",
        "*.min.js",
        "*.min.css",
        "*.map",
        "*.swp",
        "*.swo",
        "*~",
        ".DS_Store",
        "Thumbs.db",
    ],
    "max_file_size_kb": 1024,  # Skip files larger than 1 MB
    "enabled_detectors": [
        "sql_injection",
        "xss",
        "command_injection",
        "path_traversal",
        "weak_credentials",
    ],
    "custom_patterns": {},
    "confidence_threshold": 0.3,
    "output_format": "json",
    "show_progress": True,
}

CONFIG_FILENAMES: List[str] = [
    ".ai-security.json",
    ".ai-security.yaml",
    ".ai-security.yml",
    "ai-security.json",
    "ai-security.yaml",
    "ai-security.yml",
]


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration from a file, merging with defaults.

    Args:
        path: Optional explicit path to a config file. If None, searches
              for known config filenames in the current directory.

    Returns:
        A dictionary of configuration values.

    Raises:
        FileNotFoundError: If the explicit path does not exist.
        ValueError: If the config file format is not supported.
    """
    config: Dict[str, Any] = dict(DEFAULT_CONFIG)

    search_paths: List[Path] = []
    if path:
        search_paths.append(Path(path))
    else:
        for name in CONFIG_FILENAMES:
            p = Path(name)
            if p.exists():
                search_paths.append(p)
                break

    for cfg_path in search_paths:
        if not cfg_path.exists():
            if path:
                raise FileNotFoundError(f"Config file not found: {cfg_path}")
            continue

        suffix = cfg_path.suffix.lower()
        if suffix == ".json":
            with open(cfg_path, "r", encoding="utf-8") as f:
                data: Dict[str, Any] = json.load(f)
            config.update(data)
        elif suffix in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore[import-untyped]
            except ImportError:
                logger.warning(
                    "PyYAML is not installed. Install with: pip install pyyaml"
                )
                logger.warning("Falling back to JSON config parsing.")
                with open(cfg_path, "r", encoding="utf-8") as f:
                    content = f.read()
                config.update(json.loads(content))
            else:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if data and isinstance(data, dict):
                    config.update(data)
        else:
            raise ValueError(f"Unsupported config file format: {suffix}")

    # Ensure severity threshold is valid
    threshold = config.get("severity_threshold", Severity.INFO)
    if threshold not in Severity.levels():
        config["severity_threshold"] = Severity.INFO

    logger.debug("Loaded configuration: %s", config)
    return config


# ---------------------------------------------------------------------------
# Pattern helpers
# ---------------------------------------------------------------------------

# Compiled regex cache
_pattern_cache: Dict[str, Pattern[str]] = {}


def _compile(pattern: str, flags: int = re.IGNORECASE | re.MULTILINE) -> Pattern[str]:
    """Compile and cache a regular expression pattern."""
    key = f"{pattern}:{flags}"
    if key not in _pattern_cache:
        _pattern_cache[key] = re.compile(pattern, flags)
    return _pattern_cache[key]


# ---------------------------------------------------------------------------
# Base detector
# ---------------------------------------------------------------------------

class SecurityScanner(ABC):
    """Abstract base class for all security vulnerability detectors.

    Subclasses must implement the ``detect`` method and set class-level
    metadata attributes.
    """

    #: Unique identifier for the detector rule.
    rule_id: str = "BASE-000"
    #: Human-readable name.
    name: str = "Base Detector"
    #: Description of the vulnerability class.
    description: str = ""
    #: Associated CWE identifier.
    cwe: str = ""

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize the detector with the given configuration.

        Args:
            config: A dictionary of configuration values.
        """
        self.config: Dict[str, Any] = config
        self.logger: logging.Logger = logging.getLogger(f"ai_security.{self.__class__.__name__}")

    @abstractmethod
    def detect(self, file_path: str, content: str) -> List[Finding]:
        """Analyze file content and return a list of findings.

        Args:
            file_path: Absolute path to the file being analyzed.
            content: The full text content of the file.

        Returns:
            A list of Finding objects for any vulnerabilities detected.
        """
        ...

    def _make_finding(
        self,
        message: str,
        file_path: str,
        line_number: int,
        severity: str = Severity.MEDIUM,
        column: int = 0,
        snippet: str = "",
        confidence: float = 1.0,
        recommendation: str = "",
    ) -> Finding:
        """Convenience factory for creating a Finding tied to this detector.

        Args:
            message: Description of the vulnerability.
            file_path: Path to the affected file.
            line_number: Line number where the vulnerability was found.
            severity: Severity level (default MEDIUM).
            column: Column offset (default 0).
            snippet: Code snippet surrounding the finding.
            confidence: Confidence score 0.0–1.0 (default 1.0).
            recommendation: Remediation advice.

        Returns:
            A populated Finding instance.
        """
        threshold = self.config.get("severity_threshold", Severity.INFO)
        if Severity.numeric(severity) < Severity.numeric(threshold):
            self.logger.debug("Skipping finding below severity threshold: %s", severity)
        return Finding(
            rule_id=self.rule_id,
            severity=severity,
            message=message,
            file_path=file_path,
            line_number=line_number,
            column=column,
            snippet=snippet,
            confidence=confidence,
            recommendation=recommendation or self._default_recommendation(),
            cwe=self.cwe,
            detector=self.__class__.__name__,
        )

    def _default_recommendation(self) -> str:
        """Return a generic remediation recommendation for this detector."""
        return (
            f"Review the code at this location for potential {self.name.lower()} "
            f"vulnerabilities. Consider using parameterized queries, input validation, "
            f"output encoding, or a security linter."
        )


# ---------------------------------------------------------------------------
# SQL Injection Detector
# ---------------------------------------------------------------------------

class SQLInjectionDetector(SecurityScanner):
    """Detector for SQL injection vulnerabilities.

    Identifies string concatenation and unsafe interpolation in SQL queries,
    dangerous ORM methods, and dynamic query construction patterns.
    """

    rule_id: str = "SQL-001"
    name: str = "SQL Injection"
    description: str = (
        "Detects raw string concatenation and interpolation in SQL queries, "
        "unsafe ORM usage, and dynamic query building that could lead to "
        "SQL injection attacks."
    )
    cwe: str = "CWE-89"

    # Patterns for SQL injection in various languages
    SQL_PATTERNS: List[Tuple[str, str, str]] = [
        # Python string formatting with SQL
        (r'''["'](select|insert|update|delete|drop|alter|create|truncate)\s.*?["']\s*[%+]''',
         Severity.CRITICAL, "SQL query built with string concatenation or formatting"),
        (r'''["'](select|insert|update|delete|drop|alter|create|truncate)\s.*?["']\s*\.\s*format\s*\(''',
         Severity.CRITICAL, "SQL query built with str.format()"),
        (r'''["'](select|insert|update|delete|drop|alter|create|truncate)\s.*?["']\s*%''',
         Severity.CRITICAL, "SQL query built with % formatting"),
        (r'''f["'](select|insert|update|delete|drop|alter|create|truncate).*?\{''',
         Severity.CRITICAL, "Potential SQL injection via f-string"),
        (r'''execute\s*\(\s*["']\s*(select|insert|update|delete|drop|alter|create|truncate)''',
         Severity.HIGH, "Raw SQL execution with execute()"),
        (r'''executemany\s*\(\s*["']\s*(select|insert|update|delete|drop|alter|create|truncate)''',
         Severity.HIGH, "Raw SQL execution with executemany()"),
        # Dangerous ORM methods
        (r'''\.raw\s*\(\s*["']''',
         Severity.HIGH, "Raw SQL query via ORM .raw() method"),
        (r'''RawSQL\s*\(\s*["']''',
         Severity.HIGH, "Django RawSQL usage"),
        (r'''extra\s*\(\s*.*?where\s*=[^=]''',
         Severity.MEDIUM, "Django extra() with raw WHERE clause"),
        (r'''connection\.execute\s*\(\s*["']''',
         Severity.HIGH, "Direct database connection execute()"),
        (r'''cursor\.execute\s*\(\s*["']''',
         Severity.HIGH, "Cursor execute() with raw SQL"),
        # PHP
        (r'''\$\w+\s*=\s*["'](select|insert|update|delete|drop|alter|create|truncate).*?\$''',
         Severity.CRITICAL, "PHP SQL query with variable interpolation"),
        (r'''mysql_query\s*\(\s*["']''',
         Severity.CRITICAL, "Deprecated mysql_query() function"),
        (r'''mysqli_query\s*\(\s*["']''',
         Severity.HIGH, "mysqli_query() with raw query"),
        (r'''query\s*\(\s*["']\s*(select|insert|update|delete)''',
         Severity.HIGH, "Raw SQL query via query() method"),
        # Java
        (r'''Statement\s''',
         Severity.HIGH, "Java Statement object (use PreparedStatement)"),
        (r'''\.createStatement\s*\(\s*\)''',
         Severity.HIGH, "createStatement() used instead of PreparedStatement"),
        # JavaScript / Node
        (r'''\.query\s*\(\s*`[^`]*?\$\{''',
         Severity.CRITICAL, "SQL query with template literal interpolation"),
        (r'''\.query\s*\(\s*["'].*?[%+]''',
         Severity.CRITICAL, "SQL query with string concatenation"),
        # .NET
        (r'''SqlCommand\s*\(\s*["'].*?[%+]''',
         Severity.HIGH, "SqlCommand with string concatenation"),
        # Generic
        (r'''\$\w+\s*\.\s*query\s*\(\s*["']\s*(select|insert|update|delete)''',
         Severity.HIGH, "Dynamic query method called with string literal"),
        (r'''("|')\s*select\s+.*?\s+from\s+.*?\s+where\s+.*?=\s*("|')\s*\+\s''',
         Severity.CRITICAL, "SQL query with string concatenation in WHERE clause"),
    ]

    # AST-based patterns (Python)
    AST_DANGEROUS_METHODS: Set[str] = {
        "execute", "executemany", "raw", "RawSQL", "extra",
        "mysql_query", "mysqli_query", "pg_query", "sqlsrv_query",
    }

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize the SQL injection detector.

        Args:
            config: Application configuration dictionary.
        """
        super().__init__(config)
        self._compiled_patterns: List[Tuple[Pattern[str], str, str]] = [
            (_compile(p), sev, msg) for p, sev, msg in self.SQL_PATTERNS
        ]

    def detect(self, file_path: str, content: str) -> List[Finding]:
        """Scan file content for SQL injection vulnerabilities.

        Args:
            file_path: Path to the file being analyzed.
            content: Raw text content of the file.

        Returns:
            A list of findings for SQL injection vulnerabilities.
        """
        findings: List[Finding] = []
        lines: List[str] = content.split("\n")

        # Regex-based scanning
        for pattern, severity, message in self._compiled_patterns:
            for match in pattern.finditer(content):
                line_num = content[: match.start()].count("\n") + 1
                start = max(0, match.start() - content[: match.start()].rfind("\n") - 1)
                snippet = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                confidence = 0.9 if severity in (Severity.CRITICAL, Severity.HIGH) else 0.7
                findings.append(
                    self._make_finding(
                        message=message,
                        file_path=file_path,
                        line_number=line_num,
                        severity=severity,
                        snippet=snippet[:200],
                        confidence=confidence,
                        column=start + 1,
                    )
                )

        # AST-based scanning for Python files
        if file_path.endswith(".py") and not file_path.endswith(".pyc"):
            try:
                findings.extend(self._ast_scan(file_path, content))
            except SyntaxError:
                self.logger.debug("Syntax error in %s, skipping AST analysis", file_path)

        return findings

    def _ast_scan(self, file_path: str, content: str) -> List[Finding]:
        """Use Python AST to detect unsafe SQL patterns.

        Args:
            file_path: Path to the Python file.
            content: Source code content.

        Returns:
            A list of findings from AST analysis.
        """
        findings: List[Finding] = []
        tree = ast.parse(content)

        for node in ast.walk(tree):
            # Detect direct calls to dangerous methods
            if isinstance(node, ast.Call):
                func = node.func
                # Direct method calls like obj.execute(...)
                if isinstance(func, ast.Attribute) and func.attr in self.AST_DANGEROUS_METHODS:
                    # Check if first arg is a string literal (raw SQL)
                    args = node.args
                    if args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
                        line_num = getattr(node, "lineno", 0)
                        lines = content.split("\n")
                        snippet = lines[line_num - 1].strip() if 0 < line_num <= len(lines) else ""
                        findings.append(
                            self._make_finding(
                                message=f"Unsafe ORM method '{func.attr}' called with raw SQL string",
                                file_path=file_path,
                                line_number=line_num,
                                severity=Severity.HIGH,
                                snippet=snippet[:200],
                                confidence=0.85,
                            )
                        )

                # Detecting string concatenation in SQL calls
                if isinstance(func, ast.Attribute) and func.attr in ("execute", "executemany", "query"):
                    args = node.args
                    if args:
                        self._check_binop_concat(args[0], file_path, findings, node)

        return findings

    def _check_binop_concat(
        self,
        node: ast.AST,
        file_path: str,
        findings: List[Finding],
        parent: ast.AST,
    ) -> None:
        """Recursively check for string concatenation in AST nodes.

        Args:
            node: The AST node to check.
            file_path: Source file path.
            findings: Accumulator list for findings.
            parent: Parent AST node (for line number information).
        """
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
            line_num = getattr(parent, "lineno", 0)
            lines = []
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.read().split("\n")
            except Exception:
                return
            snippet = lines[line_num - 1].strip() if 0 < line_num <= len(lines) else ""
            findings.append(
                self._make_finding(
                    message="SQL query constructed with string concatenation or formatting",
                    file_path=file_path,
                    line_number=line_num,
                    severity=Severity.CRITICAL,
                    snippet=snippet[:200],
                    confidence=0.9,
                )
            )


# ---------------------------------------------------------------------------
# XSS Detector
# ---------------------------------------------------------------------------

class XSSDetector(SecurityScanner):
    """Detector for Cross-Site Scripting (XSS) vulnerabilities.

    Identifies unsafe HTML rendering, missing output escaping, dangerous
    DOM manipulation, and template injection patterns.
    """

    rule_id: str = "XSS-001"
    name: str = "Cross-Site Scripting (XSS)"
    description: str = (
        "Detects patterns that may lead to Cross-Site Scripting vulnerabilities, "
        "including unsafe HTML rendering, missing escaping, and dangerous DOM APIs."
    )
    cwe: str = "CWE-79"

    XSS_PATTERNS: List[Tuple[str, str, str]] = [
        # Python / Jinja2 / Django templates
        (r'''\|\s*safe\b''',
         Severity.MEDIUM, "Marked as safe HTML without escaping (|safe filter)"),
        (r'''\{%\s*(autoescape|mark_safe)''',
         Severity.HIGH, "Autoescape disabled or mark_safe used"),
        (r'''mark_safe\s*\(''',
         Severity.HIGH, "Django mark_safe() used - potential XSS"),
        (r'''format_html\s*\(.*?%s''',
         Severity.MEDIUM, "format_html with string formatting (use positional args)"),
        (r'''__html__\s*=\s*''',
         Severity.MEDIUM, "__html__ method defined - custom HTML rendering"),
        # JavaScript / DOM
        (r'''\.innerHTML\s*=''',
         Severity.CRITICAL, "Direct innerHTML assignment - potential XSS"),
        (r'''\.outerHTML\s*=''',
         Severity.CRITICAL, "Direct outerHTML assignment - potential XSS"),
        (r'''document\.write\s*\(''',
         Severity.CRITICAL, "document.write() - potential XSS"),
        (r'''\.insertAdjacentHTML\s*\(''',
         Severity.HIGH, "insertAdjacentHTML() - potential XSS"),
        (r'''eval\s*\(''',
         Severity.CRITICAL, "eval() execution - potential XSS"),
        (r'''setTimeout\s*\(\s*["']''',
         Severity.HIGH, "setTimeout with string argument (like eval)"),
        (r'''setInterval\s*\(\s*["']''',
         Severity.HIGH, "setInterval with string argument (like eval)"),
        (r'''new\s+Function\s*\(''',
         Severity.HIGH, "new Function() constructor (like eval)"),
        (r'''\.html\s*\(\s*\w''',
         Severity.MEDIUM, "jQuery .html() with variable - potential XSS"),
        (r'''\$\s*\(\s*["'].*?["']\s*\)\s*\.\s*html\s*\(\s*\w''',
         Severity.MEDIUM, "jQuery .html() with variable input"),
        (r'''\.append\s*\(\s*\w''',
         Severity.MEDIUM, "jQuery .append() with variable"),
        (r'''v-html\s*=''',
         Severity.HIGH, "Vue.js v-html binding - potential XSS"),
        (r'''dangerouslySetInnerHTML\s*=''',
         Severity.HIGH, "React dangerouslySetInnerHTML - potential XSS"),
        # HTTP response headers
        (r'''response\.write\s*\(''',
         Severity.MEDIUM, "Direct response.write() - potential XSS"),
        # Template injection
        (r'''render_template_string\s*\(''',
         Severity.HIGH, "Rendering template from string - template injection risk"),
        (r'''Template\s*\(\s*["']''',
         Severity.HIGH, "Template from string literal - potential injection"),
        # General
        (r'''\$\{.*?\}\s*\+?\s*["']\s*<''',
         Severity.MEDIUM, "Template literal with HTML concatenation"),
        (r'''("|')\s*\+\s*["']\s*<''',
         Severity.MEDIUM, "String concatenation with HTML tags"),
    ]

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize the XSS detector.

        Args:
            config: Application configuration dictionary.
        """
        super().__init__(config)
        self._compiled_patterns: List[Tuple[Pattern[str], str, str]] = [
            (_compile(p), sev, msg) for p, sev, msg in self.XSS_PATTERNS
        ]

    def detect(self, file_path: str, content: str) -> List[Finding]:
        """Scan file content for XSS vulnerabilities.

        Args:
            file_path: Path to the file being analyzed.
            content: Raw text content of the file.

        Returns:
            A list of findings for XSS vulnerabilities.
        """
        findings: List[Finding] = []
        lines: List[str] = content.split("\n")

        for pattern, severity, message in self._compiled_patterns:
            for match in pattern.finditer(content):
                line_num = content[: match.start()].count("\n") + 1
                start = max(0, match.start() - content[: match.start()].rfind("\n") - 1)
                snippet = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                confidence = 0.9 if severity in (Severity.CRITICAL, Severity.HIGH) else 0.6
                findings.append(
                    self._make_finding(
                        message=message,
                        file_path=file_path,
                        line_number=line_num,
                        severity=severity,
                        snippet=snippet[:200],
                        confidence=confidence,
                        column=start + 1,
                    )
                )

        # Check for missing CSRF/XSS protections in templates
        if file_path.endswith(".html") or file_path.endswith(".htm"):
            findings.extend(self._check_template_protections(file_path, content))

        return findings

    def _check_template_protections(self, file_path: str, content: str) -> List[Finding]:
        """Check HTML templates for missing XSS protections.

        Args:
            file_path: Path to the template file.
            content: Template content.

        Returns:
            A list of findings for missing protections.
        """
        findings: List[Finding] = []
        lines = content.split("\n")

        # Check for missing CSP meta tag
        if "text/html" in content or "<html" in content or "<!DOCTYPE html" in content:
            has_csp = bool(re.search(r'<meta[^>]*http-equiv=["\']Content-Security-Policy["\']', content, re.IGNORECASE))
            if not has_csp:
                # Check if it's a full HTML document
                if re.search(r'<html[^>]*>', content, re.IGNORECASE):
                    findings.append(
                        self._make_finding(
                            message="Missing Content-Security-Policy (CSP) header in HTML document",
                            file_path=file_path,
                            line_number=1,
                            severity=Severity.MEDIUM,
                            snippet="",
                            confidence=0.5,
                            recommendation="Add a Content-Security-Policy meta tag or HTTP header to mitigate XSS attacks.",
                        )
                    )

        # Check for missing X-XSS-Protection (legacy but still relevant)
        has_xss_protection = bool(re.search(r'X-XSS-Protection', content, re.IGNORECASE))
        # Only flag if it seems like a server response
        if "text/html" in content[:500]:
            if not has_xss_protection:
                findings.append(
                    self._make_finding(
                        message="Missing X-XSS-Protection header",
                        file_path=file_path,
                        line_number=1,
                        severity=Severity.LOW,
                        snippet="",
                        confidence=0.3,
                    )
                )

        return findings


# ---------------------------------------------------------------------------
# Command Injection Detector
# ---------------------------------------------------------------------------

class CommandInjectionDetector(SecurityScanner):
    """Detector for command injection vulnerabilities.

    Identifies unsafe use of os.system, subprocess with shell=True,
    os.popen, and other methods that execute shell commands.
    """

    rule_id: str = "CMD-001"
    name: str = "Command Injection"
    description: str = (
        "Detects execution of shell commands via dangerous functions, "
        "particularly when user input may be involved."
    )
    cwe: str = "CWE-78"

    CMD_PATTERNS: List[Tuple[str, str, str]] = [
        # Python
        (r'''os\.system\s*\(''',
         Severity.CRITICAL, "os.system() called - shell injection risk"),
        (r'''os\.popen\s*\(''',
         Severity.CRITICAL, "os.popen() called - shell injection risk"),
        (r'''subprocess\.\w+\s*\(.*?shell\s*=\s*True''',
         Severity.CRITICAL, "subprocess with shell=True - command injection risk"),
        (r'''subprocess\.\w+\s*\(.*?shell\s*=\s*1''',
         Severity.CRITICAL, "subprocess with shell=True (numeric) - command injection risk"),
        (r'''subprocess\.call\s*\(\s*["']''',
         Severity.HIGH, "subprocess.call() with string argument"),
        (r'''subprocess\.Popen\s*\(\s*["']''',
         Severity.HIGH, "subprocess.Popen() with string argument"),
        (r'''subprocess\.check_output\s*\(\s*["']''',
         Severity.HIGH, "subprocess.check_output() with string argument"),
        (r'''subprocess\.check_call\s*\(\s*["']''',
         Severity.HIGH, "subprocess.check_call() with string argument"),
        (r'''os\.exec[lv]\w*\s*\(''',
         Severity.HIGH, "os.exec*() called"),
        (r'''os\.spawn[lv]\w*\s*\(''',
         Severity.HIGH, "os.spawn*() called"),
        (r'''commands\.getoutput\s*\(''',
         Severity.HIGH, "commands.getoutput() called (deprecated)"),
        (r'''commands\.getstatusoutput\s*\(''',
         Severity.HIGH, "commands.getstatusoutput() called (deprecated)"),
        (r'''pty\.spawn\s*\(''',
         Severity.MEDIUM, "pty.spawn() used"),
        # PHP
        (r'''shell_exec\s*\(''',
         Severity.CRITICAL, "shell_exec() called"),
        (r'''exec\s*\(\s*["']''',
         Severity.CRITICAL, "PHP exec() called"),
        (r'''system\s*\(\s*["']''',
         Severity.CRITICAL, "PHP system() called"),
        (r'''passthru\s*\(''',
         Severity.CRITICAL, "passthru() called"),
        (r'''popen\s*\(''',
         Severity.CRITICAL, "PHP popen() called"),
        (r'''backtick\s*`\s*.*?`\s*;''',
         Severity.HIGH, "Backtick shell execution in PHP"),
        (r'''`\s*.*?\$''',
         Severity.CRITICAL, "Backtick shell execution with variable interpolation"),
        # Java
        (r'''Runtime\.getRuntime\(\)\.exec\s*\(''',
         Severity.HIGH, "Runtime.exec() called"),
        (r'''ProcessBuilder\s*\(''',
         Severity.MEDIUM, "ProcessBuilder used"),
        # Node.js
        (r'''child_process\.exec\s*\(''',
         Severity.CRITICAL, "child_process.exec() called"),
        (r'''child_process\.execSync\s*\(''',
         Severity.CRITICAL, "child_process.execSync() called"),
        (r'''child_process\.execFile\s*\(''',
         Severity.MEDIUM, "child_process.execFile() called (ensure no shell)"),
        (r'''require\(['"]child_process['"]\)''',
         Severity.MEDIUM, "child_process module required"),
        # .NET
        (r'''Process\.Start\s*\(''',
         Severity.MEDIUM, "Process.Start() called"),
        (r'''ShellExecute\s*=''',
         Severity.MEDIUM, "ShellExecute enabled"),
        # Ruby
        (r'''`[^`]*?#\{''',
         Severity.CRITICAL, "Shell command with interpolation in backticks"),
        (r'''%x\(.*?#\{''',
         Severity.CRITICAL, "Shell command with interpolation in %x()"),
        (r'''system\s+['"][^'"]*?['"]\s*\),''',
         Severity.HIGH, "Ruby system() call"),
        (r'''Open3\.popen3\s*\(''',
         Severity.MEDIUM, "Open3.popen3() called"),
        # Shell scripts
        (r'''\$\(.+?\)''',
         Severity.LOW, "Command substitution in shell script"),
        (r'''`[^`]+`''',
         Severity.LOW, "Backtick command substitution in shell script"),
        # Generic
        (r'''eval\s*\(\s*["']''',
         Severity.CRITICAL, "eval() with string argument - potential code injection"),
    ]

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize the command injection detector.

        Args:
            config: Application configuration dictionary.
        """
        super().__init__(config)
        self._compiled_patterns: List[Tuple[Pattern[str], str, str]] = [
            (_compile(p), sev, msg) for p, sev, msg in self.CMD_PATTERNS
        ]

    def detect(self, file_path: str, content: str) -> List[Finding]:
        """Scan file content for command injection vulnerabilities.

        Args:
            file_path: Path to the file being analyzed.
            content: Raw text content of the file.

        Returns:
            A list of findings for command injection vulnerabilities.
        """
        findings: List[Finding] = []
        lines: List[str] = content.split("\n")

        for pattern, severity, message in self._compiled_patterns:
            for match in pattern.finditer(content):
                line_num = content[: match.start()].count("\n") + 1
                start = max(0, match.start() - content[: match.start()].rfind("\n") - 1)
                snippet = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                confidence = 0.9 if severity in (Severity.CRITICAL, Severity.HIGH) else 0.6
                findings.append(
                    self._make_finding(
                        message=message,
                        file_path=file_path,
                        line_number=line_num,
                        severity=severity,
                        snippet=snippet[:200],
                        confidence=confidence,
                        column=start + 1,
                    )
                )

        # Check subprocess calls with shell=True via AST for Python files
        if file_path.endswith(".py"):
            try:
                findings.extend(self._ast_scan_subprocess(file_path, content))
            except SyntaxError:
                self.logger.debug("Syntax error in %s, skipping AST analysis", file_path)

        return findings

    def _ast_scan_subprocess(self, file_path: str, content: str) -> List[Finding]:
        """Use AST to detect subprocess calls with shell=True more precisely.

        Args:
            file_path: Path to the Python file.
            content: Source code content.

        Returns:
            A list of additional findings.
        """
        findings: List[Finding] = []
        tree = ast.parse(content)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and "subprocess" in func.attr.lower():
                    # Check for shell=True keyword argument
                    for kw in node.keywords:
                        if kw.arg == "shell" and isinstance(kw.value, ast.Constant):
                            if kw.value.value is True or kw.value.value == 1:
                                line_num = getattr(node, "lineno", 0)
                                lines = content.split("\n")
                                snippet = lines[line_num - 1].strip() if 0 < line_num <= len(lines) else ""
                                findings.append(
                                    self._make_finding(
                                        message=f"subprocess.{func.attr}() called with shell=True - command injection risk",
                                        file_path=file_path,
                                        line_number=line_num,
                                        severity=Severity.CRITICAL,
                                        snippet=snippet[:200],
                                        confidence=0.95,
                                    )
                                )

        return findings


# ---------------------------------------------------------------------------
# Path Traversal Detector
# ---------------------------------------------------------------------------

class PathTraversalDetector(SecurityScanner):
    """Detector for path traversal vulnerabilities.

    Identifies unsafe file operations that may allow directory traversal
    attacks, such as insufficient input validation in file paths.
    """

    rule_id: str = "PTV-001"
    name: str = "Path Traversal"
    description: str = (
        "Detects unsafe file path construction that could allow directory "
        "traversal attacks, including missing path sanitization and dangerous "
        "file operations."
    )
    cwe: str = "CWE-22"

    PATH_PATTERNS: List[Tuple[str, str, str]] = [
        # Python
        (r'''open\s*\(\s*["'].*?\.\.\s*[/\\]''',
         Severity.HIGH, "open() call with potential path traversal (../)"),
        (r'''open\s*\(\s*["'][^"']*["']\s*[+%]''',
         Severity.HIGH, "open() with string concatenation - potential path injection"),
        (r'''Path\s*\(\s*[^"'\s)]+\s*[+%\/]''',
         Severity.MEDIUM, "Path() with concatenation or unsafe join"),
        (r'''os\.path\.join\s*\(\s*[^,]+,\s*[^"'\s)]''',
         Severity.MEDIUM, "os.path.join() with non-constant argument"),
        (r'''os\.remove\s*\(\s*[^"'\s)]''',
         Severity.MEDIUM, "os.remove() with non-constant path"),
        (r'''os\.unlink\s*\(\s*[^"'\s)]''',
         Severity.MEDIUM, "os.unlink() with non-constant path"),
        (r'''shutil\.copy\s*\(\s*[^"'\s,)]+''',
         Severity.MEDIUM, "shutil.copy() with non-constant source path"),
        (r'''shutil\.move\s*\(\s*[^"'\s,)]+''',
         Severity.MEDIUM, "shutil.move() with non-constant path"),
        (r'''send_file\s*\(\s*[^"'\s)]''',
         Severity.HIGH, "send_file() with non-constant path (Flask)"),
        (r'''send_from_directory\s*\(\s*[^"']+,\s*[^"'\s)]''',
         Severity.MEDIUM, "send_from_directory() with non-constant filename"),
        (r'''os\.walk\s*\(\s*[^"'\s)]''',
         Severity.LOW, "os.walk() with non-constant path"),
        # Path traversal in URLs / web
        (r'''\.\./''',
         Severity.LOW, "Directory traversal pattern (../) in string"),
        (r'''\.\.\\\\''',
         Severity.LOW, "Directory traversal pattern (..\\) in string"),
        # Java
        (r'''new\s+File\s*\(\s*[^"'\s,)]+''',
         Severity.MEDIUM, "File() with non-constant path"),
        (r'''getResourceAsStream\s*\(\s*[^"'\s)]''',
         Severity.MEDIUM, "getResourceAsStream() with non-constant path"),
        # Node
        (r'''fs\.readFile\s*\(\s*[^"'\s)]''',
         Severity.MEDIUM, "fs.readFile() with non-constant path"),
        (r'''fs\.readFileSync\s*\(\s*[^"'\s)]''',
         Severity.MEDIUM, "fs.readFileSync() with non-constant path"),
        (r'''fs\.writeFile\s*\(\s*[^"'\s)]''',
         Severity.MEDIUM, "fs.writeFile() with non-constant path"),
        (r'''fs\.writeFileSync\s*\(\s*[^"'\s)]''',
         Severity.MEDIUM, "fs.writeFileSync() with non-constant path"),
        # PHP
        (r'''include\s*\(\s*\$''',
         Severity.HIGH, "include() with variable path"),
        (r'''require\s*\(\s*\$''',
         Severity.HIGH, "require() with variable path"),
        (r'''include_once\s*\(\s*\$''',
         Severity.HIGH, "include_once() with variable path"),
        (r'''require_once\s*\(\s*\$''',
         Severity.HIGH, "require_once() with variable path"),
        (r'''fopen\s*\(\s*\$''',
         Severity.HIGH, "fopen() with variable path"),
        (r'''file_get_contents\s*\(\s*\$''',
         Severity.HIGH, "file_get_contents() with variable path"),
        (r'''file_put_contents\s*\(\s*\$''',
         Severity.HIGH, "file_put_contents() with variable path"),
        (r'''unlink\s*\(\s*\$''',
         Severity.MEDIUM, "unlink() with variable path"),
        (r'''move_uploaded_file\s*\(''',
         Severity.HIGH, "move_uploaded_file() called"),
        # Generic
        (r'''request\.files\[''',
         Severity.MEDIUM, "File upload handling - path traversal risk"),
        (r'''filename\s*=\s*request\.''',
         Severity.MEDIUM, "User-controlled filename - path traversal risk"),
        (r'''save\s*\(\s*[^"'\s)]''',
         Severity.MEDIUM, "File save with non-constant path"),
    ]

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize the path traversal detector.

        Args:
            config: Application configuration dictionary.
        """
        super().__init__(config)
        self._compiled_patterns: List[Tuple[Pattern[str], str, str]] = [
            (_compile(p), sev, msg) for p, sev, msg in self.PATH_PATTERNS
        ]

    def detect(self, file_path: str, content: str) -> List[Finding]:
        """Scan file content for path traversal vulnerabilities.

        Args:
            file_path: Path to the file being analyzed.
            content: Raw text content of the file.

        Returns:
            A list of findings for path traversal vulnerabilities.
        """
        findings: List[Finding] = []
        lines: List[str] = content.split("\n")

        for pattern, severity, message in self._compiled_patterns:
            for match in pattern.finditer(content):
                line_num = content[: match.start()].count("\n") + 1
                start = max(0, match.start() - content[: match.start()].rfind("\n") - 1)
                snippet = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                confidence = 0.8 if severity == Severity.HIGH else 0.5
                findings.append(
                    self._make_finding(
                        message=message,
                        file_path=file_path,
                        line_number=line_num,
                        severity=severity,
                        snippet=snippet[:200],
                        confidence=confidence,
                        column=start + 1,
                    )
                )

        return findings


# ---------------------------------------------------------------------------
# Weak Credential Detector
# ---------------------------------------------------------------------------

class WeakCredentialDetector(SecurityScanner):
    """Detector for weak passwords, hardcoded credentials, and insecure tokens.

    Identifies hardcoded passwords, API keys, secret tokens, weak encryption
    keys, and other credential-related security issues.
    """

    rule_id: str = "CRED-001"
    name: str = "Weak Credentials"
    description: str = (
        "Detects hardcoded passwords, API keys, weak cryptographic keys, "
        "insecure tokens, and other credential management issues."
    )
    cwe: str = "CWE-798"

    CRED_PATTERNS: List[Tuple[str, str, str]] = [
        # Hardcoded password patterns
        (r'''password\s*=\s*["'][^"'\s]{3,}["']''',
         Severity.CRITICAL, "Hardcoded password found"),
        (r'''passwd\s*=\s*["'][^"'\s]{3,}["']''',
         Severity.CRITICAL, "Hardcoded password found"),
        (r'''pwd\s*=\s*["'][^"'\s]{3,}["']''',
         Severity.HIGH, "Hardcoded password (pwd) found"),
        (r'''secret\s*=\s*["'][^"'\s]{8,}["']''',
         Severity.CRITICAL, "Hardcoded secret found"),
        # API keys and tokens
        (r'''(api[_-]?key|apikey)\s*=\s*["'][^"'\s]{8,}["']''',
         Severity.CRITICAL, "Hardcoded API key found"),
        (r'''(api[_-]?secret|apisecret)\s*=\s*["'][^"'\s]{8,}["']''',
         Severity.CRITICAL, "Hardcoded API secret found"),
        (r'''token\s*=\s*["'][^"'\s]{16,}["']''',
         Severity.HIGH, "Hardcoded token found"),
        (r'''access[_-]?token\s*=\s*["'][^"'\s]{8,}["']''',
         Severity.CRITICAL, "Hardcoded access token found"),
        (r'''auth[_-]?token\s*=\s*["'][^"'\s]{8,}["']''',
         Severity.CRITICAL, "Hardcoded auth token found"),
        (r'''bearer\s+['"][A-Za-z0-9\-._~+/]+=*['"]''',
         Severity.CRITICAL, "Hardcoded Bearer token found"),
        # JWT tokens
        (r'''eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+''',
         Severity.HIGH, "Hardcoded JWT token found"),
        # Private keys
        (r'''-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----''',
         Severity.CRITICAL, "Private key found in source code"),
        (r'''-----BEGIN\s+OPENSSH\s+PRIVATE\s+KEY-----''',
         Severity.CRITICAL, "OpenSSH private key found in source code"),
        # Connection strings
        (r'''connection\s*string\s*=\s*["']''',
         Severity.HIGH, "Connection string found - may contain credentials"),
        (r'''connectionString\s*=\s*["']''',
         Severity.HIGH, "Connection string found - may contain credentials"),
        # Database URLs with credentials
        (r'''(mysql|postgres|mongodb|redis|sqlite|oracle)://\w+:\w+@''',
         Severity.CRITICAL, "Database URL with embedded credentials"),
        # Weak encryption keys
        (r'''encryption[_-]?key\s*=\s*["'][^"'\s]{1,16}["']''',
         Severity.HIGH, "Suspiciously short encryption key (< 16 chars)"),
        (r'''secret[_-]?key\s*=\s*["'][^"'\s]{1,16}["']''',
         Severity.HIGH, "Suspiciously short secret key (< 16 chars)"),
        # Default credentials
        (r'''(username|user)\s*=\s*["'](admin|root|administrator|sa|postgres)["']''',
         Severity.MEDIUM, "Default/well-known username found"),
        (r'''password\s*=\s*["'](password|admin|123456|root|test|qwerty|letmein)["']''',
         Severity.CRITICAL, "Weak/default password found"),
        # AWS keys
        (r'''AKIA[0-9A-Z]{16}''',
         Severity.CRITICAL, "AWS Access Key ID found"),
        (r'''aws[_-]?access[_-]?key[_-]?id\s*=\s*["']''',
         Severity.CRITICAL, "AWS access key configuration found"),
        (r'''aws[_-]?secret[_-]?access[_-]?key\s*=\s*["']''',
         Severity.CRITICAL, "AWS secret access key found"),
        # GitHub tokens
        (r'''gh[ps]_[A-Za-z0-9_]{36,}''',
         Severity.CRITICAL, "GitHub token found"),
        # Slack tokens
        (r'''xox[abpors]-[A-Za-z0-9-]{10,}''',
         Severity.CRITICAL, "Slack token found"),
        # Generic hashes that look like they could be hardcoded
        (r'''hash\s*=\s*["'][A-Fa-f0-9]{32,}["']''',
         Severity.MEDIUM, "Hardcoded hash value found"),
        # Password in URL
        (r'''://\w+:\w+@''',
         Severity.HIGH, "URL contains embedded credentials (user:password@host)"),
    ]

    # Weak password list (common passwords)
    WEAK_PASSWORDS: Set[str] = {
        "password", "password123", "123456", "12345678", "123456789",
        "qwerty", "qwerty123", "admin", "admin123", "letmein",
        "welcome", "monkey", "dragon", "master", "sunshine",
        "princess", "football", "iloveyou", "trustno1", "abc123",
        "passw0rd", "p@ssword", "changeme", "default", "temp123",
        "test123", "guest", "root", "toor", "!@#$%^&*",
        "111111", "000000", "login", "pass", "password1",
    }

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize the weak credential detector.

        Args:
            config: Application configuration dictionary.
        """
        super().__init__(config)
        self._compiled_patterns: List[Tuple[Pattern[str], str, str]] = [
            (_compile(p), sev, msg) for p, sev, msg in self.CRED_PATTERNS
        ]

    def detect(self, file_path: str, content: str) -> List[Finding]:
        """Scan file content for weak credentials and hardcoded secrets.

        Args:
            file_path: Path to the file being analyzed.
            content: Raw text content of the file.

        Returns:
            A list of findings for credential-related vulnerabilities.
        """
        findings: List[Finding] = []
        lines: List[str] = content.split("\n")

        # Regex-based scanning
        for pattern, severity, message in self._compiled_patterns:
            for match in pattern.finditer(content):
                line_num = content[: match.start()].count("\n") + 1
                start = max(0, match.start() - content[: match.start()].rfind("\n") - 1)
                snippet = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                confidence = 0.9 if severity == Severity.CRITICAL else 0.7

                # Verify the match is not in a comment/docstring/example/test
                verification = self._verify_credential_finding(content, match, line_num)
                if not verification["valid"]:
                    continue

                findings.append(
                    self._make_finding(
                        message=verification.get("message", message),
                        file_path=file_path,
                        line_number=line_num,
                        severity=verification.get("severity", severity),
                        snippet=snippet[:200],
                        confidence=confidence,
                        column=start + 1,
                        recommendation="Remove hardcoded credentials from source code. "
                            "Use environment variables, a secrets manager, or a vault service instead.",
                    )
                )

        # Check for password variable assignments with weak values
        findings.extend(self._check_weak_password_values(file_path, content))

        return findings

    def _verify_credential_finding(
        self, content: str, match: re.Match, line_num: int
    ) -> Dict[str, Any]:
        """Verify that a credential finding is likely a real issue (not a test or example).

        Args:
            content: Full file content.
            match: The regex match object.
            line_num: Line number of the match.

        Returns:
            A dict with 'valid' (bool), and optionally 'message' and 'severity' overrides.
        """
        matched_text = match.group(0)
        line = content.split("\n")[line_num - 1] if 0 < line_num <= len(content.split("\n")) else ""

        # Extract the value from the match (the part in quotes, if any)
        value_match = re.search(r'''["']([^"']+)["']''', matched_text)
        matched_value = value_match.group(1) if value_match else matched_text

        # Skip if the matched value is a known placeholder pattern
        # (check the whole value, not just a substring, to avoid false
        # negatives like AKIAIOSFODNN7EXAMPLE which contains "EXAMPLE")
        placeholder_patterns = [
            r'^your[-_]?(key|secret|token|password|api.?key).*$',
            r'^changeme$',
            r'^placeholder$',
            r'^todo$',
            r'^sample$',
            r'^example$',
            r'^your-key-here$',
            r'^your_secret_here$',
        ]
        for pp in placeholder_patterns:
            if re.match(pp, matched_value, re.IGNORECASE):
                return {"valid": False}

        # Skip if it's a known false positive pattern (e.g., documentation)
        if re.search(r'https?://example\.com', line):
            return {"valid": False}

        # Check if the value is a well-known weak password
        if value_match:
            value = value_match.group(1).lower()
            if value in self.WEAK_PASSWORDS:
                return {
                    "valid": True,
                    "message": f"Weak credential found: '{value}' is a known weak/default password",
                    "severity": Severity.CRITICAL,
                }

        return {"valid": True}

    def _check_weak_password_values(self, file_path: str, content: str) -> List[Finding]:
        """Scan for variable assignments containing weak password values.

        Args:
            file_path: Path to the file.
            content: File content.

        Returns:
            A list of findings for weak password values.
        """
        findings: List[Finding] = []
        lines = content.split("\n")

        for i, line in enumerate(lines, 1):
            # Look for password-like variable assignments
            pwd_match = re.search(r'''(password|passwd|pwd|secret)\s*[:=]\s*["']([^"']+)["']''', line)
            if pwd_match:
                value = pwd_match.group(2).lower()
                if value in self.WEAK_PASSWORDS:
                    findings.append(
                        self._make_finding(
                            message=f"Weak password value detected: '{pwd_match.group(2)}' is a known weak password",
                            file_path=file_path,
                            line_number=i,
                            severity=Severity.CRITICAL,
                            snippet=line.strip()[:200],
                            confidence=1.0,
                            recommendation="Choose a strong password with at least 12 characters, "
                                "including uppercase, lowercase, digits, and special characters.",
                        )
                    )

        return findings


# ---------------------------------------------------------------------------
# File Analyzer
# ---------------------------------------------------------------------------

class FileAnalyzer:
    """Orchestrates analysis of source files using multiple detectors.

    The FileAnalyzer takes a set of detectors, processes files by reading
    their content, and aggregates findings. It supports exclusion patterns
    and file size limits.
    """

    def __init__(
        self,
        detectors: List[SecurityScanner],
        config: Dict[str, Any],
    ) -> None:
        """Initialize the file analyzer.

        Args:
            detectors: A list of detector instances to run on each file.
            config: Configuration dictionary.
        """
        self.detectors: List[SecurityScanner] = detectors
        self.config: Dict[str, Any] = config
        self.logger: logging.Logger = logging.getLogger("ai_security.FileAnalyzer")
        self._exclude_patterns: List[str] = config.get("exclude_patterns", [])
        self._max_file_size: int = config.get("max_file_size_kb", 1024) * 1024
        self._confidence_threshold: float = config.get("confidence_threshold", 0.3)

        # Binary file extensions to skip
        self._binary_extensions: Set[str] = {
            ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
            ".woff", ".woff2", ".ttf", ".eot",
            ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
            ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
            ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".flv",
            ".exe", ".dll", ".so", ".dylib", ".bin",
            ".pyc", ".pyo", ".pyd",
            ".o", ".a", ".obj", ".lib",
            ".class", ".jar", ".war",
            ".iso", ".img", ".vmdk",
            ".db", ".sqlite", ".sqlite3",
            ".min.js", ".min.css",
            ".map",
        }

    def should_skip(self, file_path: str) -> Tuple[bool, str]:
        """Determine if a file should be skipped based on path and size.

        Args:
            file_path: Absolute path to the file.

        Returns:
            A tuple of (should_skip: bool, reason: str).
        """
        path = Path(file_path)

        # Check extension
        suffix = path.suffix.lower()
        if suffix in self._binary_extensions:
            return True, "binary file type"

        # Check exclude patterns against the full path, basename, and
        # each individual path component (normalized for fnmatch).
        path_str = str(path)
        name_str = path.name
        # Also check parts like "node_modules" matching "node_modules/*"
        parts = path.parts
        for pattern in self._exclude_patterns:
            if fnmatch.fnmatch(path_str, pattern) or fnmatch.fnmatch(name_str, pattern):
                return True, f"matches exclude pattern '{pattern}'"
            # Check if any subdirectory + filename matches the pattern
            for i in range(len(parts)):
                subpath = str(Path(*parts[i:]))
                if fnmatch.fnmatch(subpath, pattern):
                    return True, f"matches exclude pattern '{pattern}'"

        # Check file size (only if the file exists)
        if path.exists():
            try:
                size = path.stat().st_size
                if size > self._max_file_size:
                    return True, f"file too large ({size / 1024:.1f} KB > {self._max_file_size / 1024:.0f} KB)"
            except OSError as e:
                return True, f"cannot stat file: {e}"
        else:
            # File does not exist locally — still let it be scanned if
            # patterns don't exclude it; the caller will handle non-existent paths.
            pass

        return False, ""

    def analyze_file(self, file_path: str) -> List[Finding]:
        """Run all detectors on a single file.

        Args:
            file_path: Absolute path to the file to analyze.

        Returns:
            A list of findings from all detectors.

        Raises:
            FileNotFoundError: If the file does not exist.
            PermissionError: If the file cannot be read.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        if not path.is_file():
            raise ValueError(f"Not a file: {file_path}")

        should_skip, reason = self.should_skip(file_path)
        if should_skip:
            self.logger.debug("Skipping %s: %s", file_path, reason)
            return []

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except (UnicodeDecodeError, PermissionError) as e:
            self.logger.warning("Cannot read %s: %s", file_path, e)
            return []

        all_findings: List[Finding] = []
        for detector in self.detectors:
            try:
                findings = detector.detect(file_path, content)
                # Filter by confidence threshold
                findings = [
                    f for f in findings
                    if f.confidence >= self._confidence_threshold
                ]
                all_findings.extend(findings)
            except Exception as e:
                self.logger.error(
                    "Detector %s failed on %s: %s",
                    detector.__class__.__name__,
                    file_path,
                    e,
                )
                self.logger.debug(traceback.format_exc())

        # Deduplicate findings on the same line for the same rule
        all_findings = self._deduplicate(all_findings)

        return all_findings

    def _deduplicate(self, findings: List[Finding]) -> List[Finding]:
        """Remove duplicate findings on the same line and rule.

        Args:
            findings: A list of findings that may contain duplicates.

        Returns:
            A deduplicated list of findings.
        """
        seen: Set[Tuple[str, str, int]] = set()
        unique: List[Finding] = []
        for f in findings:
            key = (f.rule_id, f.file_path, f.line_number)
            if key not in seen:
                seen.add(key)
                unique.append(f)
        return unique


# ---------------------------------------------------------------------------
# Report generators
# ---------------------------------------------------------------------------

class ReportGenerator:
    """Generate security scan reports in various formats."""

    @staticmethod
    def generate_json(result: ScanResult, output_path: str) -> None:
        """Generate a JSON report file.

        Args:
            result: The scan result to serialize.
            output_path: Path to write the JSON file.

        Raises:
            IOError: If the file cannot be written.
        """
        data = result.to_dict()
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info("JSON report written to %s", output_path)

    @staticmethod
    def generate_html(result: ScanResult, output_path: str) -> None:
        """Generate an HTML report file with a visual summary.

        Args:
            result: The scan result to render.
            output_path: Path to write the HTML file.

        Raises:
            IOError: If the file cannot be written.
        """
        summary = result.summary()
        total = len(result.findings)
        critical = summary.get(Severity.CRITICAL, 0)
        high = summary.get(Severity.HIGH, 0)
        medium = summary.get(Severity.MEDIUM, 0)
        low = summary.get(Severity.LOW, 0)
        info = summary.get(Severity.INFO, 0)

        # Build findings table rows
        rows_html = ""
        for f in result.findings:
            severity_class = f.severity.lower()
            snippet_esc = html.escape(f.snippet[:150])
            message_esc = html.escape(f.message)
            rec_esc = html.escape(f.recommendation[:200])
            rows_html += f"""\
            <tr class="{severity_class}">
                <td><span class="badge badge-{severity_class}">{html.escape(f.severity)}</span></td>
                <td>{html.escape(f.rule_id)}</td>
                <td title="{message_esc}">{message_esc[:80]}{'...' if len(message_esc) > 80 else ''}</td>
                <td>{html.escape(f.file_path)}:{f.line_number}</td>
                <td><code>{snippet_esc}</code></td>
                <td>{rec_esc[:80]}{'...' if len(rec_esc) > 80 else ''}</td>
            </tr>
            """

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Security Audit Report - {html.escape(result.target)}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f7fa; color: #333; line-height: 1.6; }}
.container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: #fff; padding: 30px; border-radius: 12px; margin-bottom: 24px; }}
header h1 {{ font-size: 28px; margin-bottom: 8px; }}
header p {{ opacity: 0.9; }}
.summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 16px; margin-bottom: 24px; }}
.summary-card {{ background: #fff; border-radius: 10px; padding: 20px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
.summary-card .count {{ font-size: 36px; font-weight: 700; }}
.summary-card .label {{ font-size: 14px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; }}
.summary-card.critical {{ border-top: 4px solid #e53e3e; }}
.summary-card.critical .count {{ color: #e53e3e; }}
.summary-card.high {{ border-top: 4px solid #ed8936; }}
.summary-card.high .count {{ color: #ed8936; }}
.summary-card.medium {{ border-top: 4px solid #ecc94b; }}
.summary-card.medium .count {{ color: #d69e2e; }}
.summary-card.low {{ border-top: 4px solid #48bb78; }}
.summary-card.low .count {{ color: #48bb78; }}
.summary-card.info {{ border-top: 4px solid #4299e1; }}
.summary-card.info .count {{ color: #4299e1; }}
table {{ width: 100%; background: #fff; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
th {{ background: #f7fafc; padding: 12px 16px; text-align: left; font-weight: 600; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; color: #555; border-bottom: 2px solid #e2e8f0; }}
td {{ padding: 12px 16px; border-bottom: 1px solid #edf2f7; font-size: 14px; }}
tr:hover {{ background: #f7fafc; }}
tr.critical td {{ border-left: 3px solid #e53e3e; }}
tr.high td {{ border-left: 3px solid #ed8936; }}
tr.medium td {{ border-left: 3px solid #ecc94b; }}
tr.low td {{ border-left: 3px solid #48bb78; }}
tr.info td {{ border-left: 3px solid #4299e1; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; text-transform: uppercase; }}
.badge-critical {{ background: #fed7d7; color: #c53030; }}
.badge-high {{ background: #fefcbf; color: #b7791f; }}
.badge-medium {{ background: #fefcbf; color: #b7791f; }}
.badge-low {{ background: #c6f6d5; color: #276749; }}
.badge-info {{ background: #bee3f8; color: #2b6cb0; }}
code {{ background: #edf2f7; padding: 2px 6px; border-radius: 3px; font-size: 12px; word-break: break-all; }}
.meta {{ background: #fff; border-radius: 10px; padding: 20px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
.meta h2 {{ font-size: 18px; margin-bottom: 12px; color: #4a5568; }}
.meta-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }}
.meta-item {{ font-size: 14px; }}
.meta-item strong {{ color: #4a5568; }}
.footer {{ text-align: center; margin-top: 24px; color: #a0aec0; font-size: 13px; }}
</style>
</head>
<body>
<div class="container">
<header>
    <h1>AI Security Audit Report</h1>
    <p>Target: <strong>{html.escape(result.target)}</strong> &nbsp;|&nbsp; Scanned: {result.scan_time}</p>
    <p>Duration: {result.duration_seconds:.2f}s &nbsp;|&nbsp; Files: {result.scanned_files}/{result.total_files}</p>
</header>

<div class="meta">
    <h2>Scan Overview</h2>
    <div class="meta-grid">
        <div class="meta-item"><strong>Target</strong><br>{html.escape(result.target)}</div>
        <div class="meta-item"><strong>Scan Time</strong><br>{result.scan_time}</div>
        <div class="meta-item"><strong>Duration</strong><br>{result.duration_seconds:.2f} seconds</div>
        <div class="meta-item"><strong>Total Files</strong><br>{result.total_files}</div>
        <div class="meta-item"><strong>Scanned Files</strong><br>{result.scanned_files}</div>
        <div class="meta-item"><strong>Total Findings</strong><br>{total}</div>
    </div>
</div>

<div class="summary">
    <div class="summary-card critical">
        <div class="count">{critical}</div>
        <div class="label">Critical</div>
    </div>
    <div class="summary-card high">
        <div class="count">{high}</div>
        <div class="label">High</div>
    </div>
    <div class="summary-card medium">
        <div class="count">{medium}</div>
        <div class="label">Medium</div>
    </div>
    <div class="summary-card low">
        <div class="count">{low}</div>
        <div class="label">Low</div>
    </div>
    <div class="summary-card info">
        <div class="count">{info}</div>
        <div class="label">Info</div>
    </div>
</div>

<table>
<thead>
<tr>
    <th>Severity</th>
    <th>Rule</th>
    <th>Message</th>
    <th>Location</th>
    <th>Snippet</th>
    <th>Recommendation</th>
</tr>
</thead>
<tbody>
{rows_html if rows_html else '<tr><td colspan="6" style="text-align:center;color:#a0aec0;padding:40px;">No findings — clean scan!</td></tr>'}
</tbody>
</table>

<div class="footer">
    Generated by AI Security Auditor &mdash; {result.scan_time}
</div>
</div>
</body>
</html>"""

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        logger.info("HTML report written to %s", output_path)

    @staticmethod
    def generate_sarif(result: ScanResult, output_path: str) -> None:
        """Generate a SARIF (Static Analysis Results Interchange Format) report.

        Args:
            result: The scan result to convert.
            output_path: Path to write the SARIF file.

        Raises:
            IOError: If the file cannot be written.
        """
        # Collect unique rules
        rules: Dict[str, Dict[str, Any]] = {}
        for f in result.findings:
            if f.rule_id not in rules:
                rules[f.rule_id] = {
                    "id": f.rule_id,
                    "name": f.detector,
                    "shortDescription": {"text": f.message},
                    "fullDescription": {"text": f.recommendation},
                    "defaultConfiguration": {"level": "error"},
                    "properties": {
                        "cwe": f.cwe,
                        "severity": f.severity,
                    },
                }

        sarif_data = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "ai-security-auditor",
                            "version": "1.0.0",
                            "informationUri": "https://github.com/example/ai-security",
                            "rules": list(rules.values()),
                        }
                    },
                    "results": [f.to_sarif() for f in result.findings],
                    "artifacts": [
                        {
                            "location": {"uri": result.target},
                            "description": {"text": "Scan target"},
                        }
                    ],
                    "properties": {
                        "scan_time": result.scan_time,
                        "duration_seconds": result.duration_seconds,
                        "total_files": result.total_files,
                        "scanned_files": result.scanned_files,
                    },
                }
            ],
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(sarif_data, f, indent=2, ensure_ascii=False)
        logger.info("SARIF report written to %s", output_path)


# ---------------------------------------------------------------------------
# Scanner orchestration
# ---------------------------------------------------------------------------

class Scanner:
    """High-level scanner that orchestrates directory traversal and analysis.

    The Scanner walks directories, discovers files, delegates analysis to
    FileAnalyzer, and aggregates results into a ScanResult.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize the scanner with configuration.

        Args:
            config: Configuration dictionary.
        """
        self.config: Dict[str, Any] = config
        self.logger: logging.Logger = logging.getLogger("ai_security.Scanner")

        # Build detector list based on config
        self.detectors: List[SecurityScanner] = self._build_detectors()
        self.analyzer: FileAnalyzer = FileAnalyzer(self.detectors, config)

    def _build_detectors(self) -> List[SecurityScanner]:
        """Instantiate enabled detectors based on configuration.

        Returns:
            A list of detector instances.
        """
        enabled = self.config.get("enabled_detectors", [])
        detector_map: Dict[str, type] = {
            "sql_injection": SQLInjectionDetector,
            "xss": XSSDetector,
            "command_injection": CommandInjectionDetector,
            "path_traversal": PathTraversalDetector,
            "weak_credentials": WeakCredentialDetector,
        }

        detectors: List[SecurityScanner] = []
        for name in enabled:
            cls = detector_map.get(name)
            if cls:
                detectors.append(cls(self.config))
                self.logger.debug("Enabled detector: %s", name)
            else:
                self.logger.warning("Unknown detector: %s", name)

        if not detectors:
            self.logger.warning("No detectors enabled. Using all detectors.")
            for cls in detector_map.values():
                detectors.append(cls(self.config))

        return detectors

    def scan_path(self, target: str) -> ScanResult:
        """Scan a file or directory for security vulnerabilities.

        Args:
            target: Path to a file or directory to scan.

        Returns:
            A ScanResult with all findings.

        Raises:
            FileNotFoundError: If the target does not exist.
        """
        start_time = time.time()
        result = ScanResult(
            target=os.path.abspath(target),
            scan_time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            config=self.config,
        )

        path = Path(target)
        if not path.exists():
            raise FileNotFoundError(f"Target not found: {target}")

        # Collect files
        files_to_scan: List[str] = []
        if path.is_file():
            files_to_scan.append(str(path.resolve()))
            result.total_files = 1
        else:
            all_files = list(path.rglob("*"))
            result.total_files = len(all_files)
            for f in all_files:
                if f.is_file():
                    files_to_scan.append(str(f.resolve()))

        # Scan each file
        for i, file_path in enumerate(files_to_scan):
            should_skip, reason = self.analyzer.should_skip(file_path)
            if should_skip:
                self.logger.debug("Skipping %s: %s", file_path, reason)
                continue

            try:
                if self.config.get("show_progress", False) and len(files_to_scan) > 10:
                    self._print_progress(i + 1, len(files_to_scan), file_path)

                findings = self.analyzer.analyze_file(file_path)
                result.findings.extend(findings)
                result.scanned_files += 1
            except Exception as e:
                self.logger.error("Error scanning %s: %s", file_path, e)
                result.errors.append({
                    "file": file_path,
                    "error": str(e),
                })

        result.duration_seconds = round(time.time() - start_time, 3)

        # Sort findings by severity (most severe first) then by file path
        result.findings.sort(
            key=lambda f: (
                -Severity.numeric(f.severity),
                f.file_path,
                f.line_number,
            )
        )

        self._print_scan_summary(result)
        return result

    def _print_progress(self, current: int, total: int, file_path: str) -> None:
        """Print a progress indicator to stderr.

        Args:
            current: Current file index (1-based).
            total: Total number of files.
            file_path: Path of the current file being scanned.
        """
        pct = (current / total) * 100
        filename = os.path.basename(file_path)
        # Use carriage return to update in-place
        print(
            f"\r  Scanning: [{current}/{total}] {pct:5.1f}% - {filename:<60}",
            end="",
            file=sys.stderr,
        )
        if current == total:
            print(file=sys.stderr)

    def _print_scan_summary(self, result: ScanResult) -> None:
        """Print a summary of scan results to the console.

        Args:
            result: The completed scan result.
        """
        summary = result.summary()
        total = len(result.findings)
        print(f"\nScan Summary", file=sys.stderr)
        print(f"{'=' * 60}", file=sys.stderr)
        print(f"  Target:      {result.target}", file=sys.stderr)
        print(f"  Duration:    {result.duration_seconds:.2f}s", file=sys.stderr)
        print(f"  Files:       {result.scanned_files}/{result.total_files} scanned", file=sys.stderr)
        print(f"  Findings:    {total}", file=sys.stderr)
        if total > 0:
            print(f"    Critical:  {summary.get(Severity.CRITICAL, 0)}", file=sys.stderr)
            print(f"    High:      {summary.get(Severity.HIGH, 0)}", file=sys.stderr)
            print(f"    Medium:    {summary.get(Severity.MEDIUM, 0)}", file=sys.stderr)
            print(f"    Low:       {summary.get(Severity.LOW, 0)}", file=sys.stderr)
            print(f"    Info:      {summary.get(Severity.INFO, 0)}", file=sys.stderr)
        if result.errors:
            print(f"  Errors:    {len(result.errors)}", file=sys.stderr)
        print(f"{'=' * 60}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser for the CLI.

    Returns:
        A configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="ai-security",
        description="AI-Powered Security Auditing Tool - detect vulnerabilities in source code.",
        epilog="For more information, see the documentation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--version",
        action="version",
        version="ai-security 1.0.0",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Scan command
    scan_parser = subparsers.add_parser("scan", help="Scan a file or directory for vulnerabilities")
    scan_parser.add_argument(
        "target",
        help="Target file or directory to scan",
    )
    scan_parser.add_argument(
        "-o", "--output",
        help="Output file path for the report",
        default=None,
    )
    scan_parser.add_argument(
        "-f", "--format",
        help="Report format",
        choices=["json", "html", "sarif"],
        default="json",
    )
    scan_parser.add_argument(
        "-e", "--exclude",
        help="Additional exclude pattern (glob)",
        action="append",
        default=[],
    )
    scan_parser.add_argument(
        "-s", "--severity",
        help="Minimum severity threshold",
        choices=Severity.levels(),
        default=Severity.INFO,
    )
    scan_parser.add_argument(
        "-c", "--config",
        help="Path to configuration file",
        default=None,
    )
    scan_parser.add_argument(
        "-d", "--detectors",
        help="Comma-separated list of detectors to enable",
        default=None,
    )
    scan_parser.add_argument(
        "--no-progress",
        help="Disable progress display",
        action="store_true",
    )
    scan_parser.add_argument(
        "--confidence",
        help="Minimum confidence threshold (0.0-1.0)",
        type=float,
        default=None,
    )

    # Config command
    config_parser = subparsers.add_parser("config", help="Configuration management")
    config_parser.add_argument(
        "--init",
        help="Generate a default configuration file",
        action="store_true",
    )
    config_parser.add_argument(
        "--path",
        help="Path for the generated config file",
        default=".ai-security.json",
    )
    config_parser.add_argument(
        "--show",
        help="Show current configuration",
        action="store_true",
    )

    # List detectors command
    list_parser = subparsers.add_parser("list", help="List available detectors")
    list_parser.add_argument(
        "--verbose",
        help="Show detailed detector information",
        action="store_true",
    )

    return parser


def cmd_scan(args: argparse.Namespace) -> int:
    """Execute the 'scan' command.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 = success, 1 = error).
    """
    try:
        # Load config
        config = load_config(args.config)

        # Override with CLI arguments
        if args.severity:
            config["severity_threshold"] = args.severity
        if args.exclude:
            config["exclude_patterns"] = list(set(config["exclude_patterns"] + args.exclude))
        if args.detectors:
            config["enabled_detectors"] = [d.strip() for d in args.detectors.split(",")]
        if args.no_progress:
            config["show_progress"] = False
        if args.confidence is not None:
            config["confidence_threshold"] = max(0.0, min(1.0, args.confidence))

        # Run scan
        scanner = Scanner(config)
        result = scanner.scan_path(args.target)

        # Generate report
        if args.output:
            output_path = args.output
        else:
            base = os.path.splitext(os.path.basename(args.target))[0] or "scan"
            output_path = f"{base}-security-report.{args.format}"

        if args.format == "json":
            ReportGenerator.generate_json(result, output_path)
        elif args.format == "html":
            ReportGenerator.generate_html(result, output_path)
        elif args.format == "sarif":
            ReportGenerator.generate_sarif(result, output_path)

        # Return exit code based on findings
        summary = result.summary()
        if summary.get(Severity.CRITICAL, 0) > 0:
            return 2
        if summary.get(Severity.HIGH, 0) > 0:
            return 1
        return 0

    except Exception as e:
        logger.error("Scan failed: %s", e)
        logger.debug(traceback.format_exc())
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_config(args: argparse.Namespace) -> int:
    """Execute the 'config' command.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 = success).
    """
    if args.init:
        path = args.path
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
            print(f"Default configuration written to {path}")
        except IOError as e:
            print(f"Error writing config file: {e}", file=sys.stderr)
            return 1
        return 0

    if args.show:
        config = load_config(args.path)
        print(json.dumps(config, indent=2, ensure_ascii=False))
        return 0

    print("No action specified. Use --init or --show.", file=sys.stderr)
    return 1


def cmd_list(args: argparse.Namespace) -> int:
    """Execute the 'list' command to show available detectors.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 = success).
    """
    detectors: List[Tuple[str, type]] = [
        ("SQL Injection", SQLInjectionDetector),
        ("Cross-Site Scripting", XSSDetector),
        ("Command Injection", CommandInjectionDetector),
        ("Path Traversal", PathTraversalDetector),
        ("Weak Credentials", WeakCredentialDetector),
    ]

    print(f"\nAvailable Detectors:")
    print(f"{'=' * 60}")
    for name, cls in detectors:
        cwe = cls.cwe
        print(f"  {name:25s}  Rule: {cls.rule_id:10s}  CWE: {cwe}")
        if args.verbose:
            desc = cls.description
            # Wrap description
            while desc:
                line, desc = desc[:80], desc[80:]
                print(f"    {'':1s}{line}")
            print()

    print(f"{'=' * 60}")
    return 0


def main() -> int:
    """Main entry point for the CLI.

    Parses command-line arguments and dispatches to the appropriate
    command handler.

    Returns:
        Exit code (0 = success, non-zero = error).
    """
    parser = create_parser()
    args = parser.parse_args()

    if args.command == "scan":
        return cmd_scan(args)
    elif args.command == "config":
        return cmd_config(args)
    elif args.command == "list":
        return cmd_list(args)
    else:
        parser.print_help()
        return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(main())