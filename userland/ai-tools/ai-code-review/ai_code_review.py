#!/usr/bin/env python3
"""
AinosOS AI Code Review Tool
============================
Comprehensive AI-powered code review tool with AST-based static analysis,
rule engine, and multi-format report generation.

Subcommands:
    review       Run code review on files or directories
    list-rules   List available review rules
    check        Check a specific rule against a file

Supports Python, C, and Rust source code analysis with configurable
rule severity levels, gitignore integration, and GitHub PR integration.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import re
import sys
import textwrap
import time
import fnmatch
import hashlib
import uuid
import inspect
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import (
    Any, Callable, Dict, Generator, List, Optional,
    Sequence, Set, Tuple, Type, Union,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "1.0.0"
APP_NAME = "ai-code-review"
DEFAULT_CONFIG_FILE = ".ainos-review.yml"

SEVERITY_LEVELS = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
SEVERITY_ORDER = {s: i for i, s in enumerate(SEVERITY_LEVELS)}
SUPPORTED_EXTENSIONS = {".py", ".c", ".h", ".rs", ".cpp", ".hpp", ".cc", ".cxx", ".hh"}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class Severity(Enum):
    """Rule severity levels."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

    def __lt__(self, other: "Severity") -> bool:
        return SEVERITY_ORDER[self.value] < SEVERITY_ORDER[other.value]

    def __ge__(self, other: "Severity") -> bool:
        return SEVERITY_ORDER[self.value] >= SEVERITY_ORDER[other.value]


@dataclass
class ReviewIssue:
    """A single issue found during code review."""
    rule_id: str
    rule_name: str
    severity: str
    message: str
    file_path: str
    line_number: int
    column: int = 0
    end_line: int = 0
    end_column: int = 0
    snippet: str = ""
    remediation: str = ""
    category: str = ""
    cwe: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_sarif(self) -> Dict[str, Any]:
        """Convert to SARIF result format."""
        return {
            "ruleId": self.rule_id,
            "ruleIndex": 0,
            "level": "error" if self.severity in ("CRITICAL", "HIGH") else "warning",
            "message": {"text": self.message},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": self.file_path},
                    "region": {
                        "startLine": self.line_number,
                        "startColumn": self.column or 1,
                        "endLine": self.end_line or self.line_number,
                        "endColumn": self.end_column or (self.column or 1) + 1,
                    },
                },
            }],
            "properties": {
                "severity": self.severity,
                "remediation": self.remediation,
                "category": self.category,
                "cwe": self.cwe,
            },
        }


@dataclass
class ReviewResult:
    """Results from a complete code review run."""
    issues: List[ReviewIssue] = field(default_factory=list)
    files_scanned: int = 0
    files_skipped: int = 0
    total_lines: int = 0
    duration_ms: float = 0.0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "CRITICAL")

    @property
    def high_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "HIGH")

    @property
    def medium_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "MEDIUM")

    @property
    def low_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "LOW")

    @property
    def info_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "INFO")

    def severity_counts(self) -> Dict[str, int]:
        return {
            "CRITICAL": self.critical_count,
            "HIGH": self.high_count,
            "MEDIUM": self.medium_count,
            "LOW": self.low_count,
            "INFO": self.info_count,
        }

    def issues_by_severity(self) -> Dict[str, List[ReviewIssue]]:
        grouped: Dict[str, List[ReviewIssue]] = {s: [] for s in SEVERITY_LEVELS}
        for issue in self.issues:
            grouped[issue.severity].append(issue)
        return grouped

    def issues_by_file(self) -> Dict[str, List[ReviewIssue]]:
        grouped: Dict[str, List[ReviewIssue]] = defaultdict(list)
        for issue in self.issues:
            grouped[issue.file_path].append(issue)
        return dict(grouped)

    def issues_by_rule(self) -> Dict[str, List[ReviewIssue]]:
        grouped: Dict[str, List[ReviewIssue]] = defaultdict(list)
        for issue in self.issues:
            key = f"{issue.rule_id}: {issue.rule_name}"
            grouped[key].append(issue)
        return dict(grouped)


# ---------------------------------------------------------------------------
# Abstract base rule
# ---------------------------------------------------------------------------

class BaseReviewRule(ABC):
    """Abstract base class for all review rules."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._rule_id: str = ""
        self._name: str = ""
        self._description: str = ""
        self._severity: str = "MEDIUM"
        self._languages: List[str] = ["python"]
        self._category: str = "general"
        self._enabled: bool = True

    @property
    @abstractmethod
    def rule_id(self) -> str:
        """Unique rule identifier (e.g. 'REVIEW-001')."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable rule name."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Description of what the rule detects."""

    @property
    def severity(self) -> str:
        return self._severity

    @severity.setter
    def severity(self, value: str) -> None:
        if value.upper() in SEVERITY_LEVELS:
            self._severity = value.upper()

    @property
    def languages(self) -> List[str]:
        return self._languages

    @property
    def category(self) -> str:
        return self._category

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def applies_to(self, file_path: str) -> bool:
        """Check if this rule applies to a given file."""
        ext = os.path.splitext(file_path)[1].lower()
        lang_map = {
            ".py": "python",
            ".c": "c", ".h": "c",
            ".cpp": "c", ".hpp": "c", ".cc": "c", ".cxx": "c", ".hh": "c",
            ".rs": "rust",
        }
        lang = lang_map.get(ext, "")
        return lang in self.languages

    @abstractmethod
    def check(self, tree: ast.AST, file_path: str, source_code: str) -> List[ReviewIssue]:
        """Run the rule check and return a list of issues."""

    def get_metadata(self) -> Dict[str, Any]:
        """Return rule metadata for listing."""
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "severity": self.severity,
            "languages": self.languages,
            "category": getattr(self, 'category', 'general'),
            "enabled": getattr(self, 'enabled', True),
        }


# ---------------------------------------------------------------------------
# Core review engine
# ---------------------------------------------------------------------------

class ReviewEngine:
    """Core review engine that discovers files and runs rules."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self.rules: List[BaseReviewRule] = []
        self._register_builtin_rules()

    def _register_builtin_rules(self) -> None:
        """Register all built-in review rules."""
        try:
            from rules.performance_rules import get_all_performance_rules
            perf_rules = get_all_performance_rules(self.config)
            self.rules.extend(perf_rules)
        except (ImportError, AttributeError):
            pass

        try:
            from rules.security_rules import get_all_security_rules
            sec_rules = get_all_security_rules(self.config)
            self.rules.extend(sec_rules)
        except (ImportError, AttributeError):
            pass

        self.rules.extend(self._get_builtin_general_rules())

    def _get_builtin_general_rules(self) -> List[BaseReviewRule]:
        """Return built-in general-purpose review rules."""
        return [
            NamingConventionRule(self.config),
            DocstringRule(self.config),
            LineLengthRule(self.config),
            TodoFixmeRule(self.config),
            ImportOrderRule(self.config),
            ShadowedBuiltinsRule(self.config),
            DuplicateCodeRule(self.config),
            ComplexityRule(self.config),
            ErrorHandlingRule(self.config),
            TypeAnnotationRule(self.config),
            MagicNumberRule(self.config),
            UnusedVariableRule(self.config),
            ResourceLeakRule(self.config),
            ConcurrencyRule(self.config),
            LoggingRule(self.config),
        ]

    def register_rule(self, rule: BaseReviewRule) -> None:
        """Register a new rule."""
        self.rules.append(rule)

    def register_rules(self, rules: List[BaseReviewRule]) -> None:
        """Register multiple rules."""
        self.rules.extend(rules)

    def get_rules(self, language: Optional[str] = None,
                  category: Optional[str] = None,
                  severity: Optional[str] = None,
                  enabled_only: bool = True) -> List[BaseReviewRule]:
        """Get rules filtered by criteria."""
        result = []
        for rule in self.rules:
            if enabled_only:
                is_enabled = getattr(rule, 'enabled', True)
                if not is_enabled:
                    continue
            if language and language not in getattr(rule, 'languages', []):
                continue
            if category and getattr(rule, 'category', '') != category:
                continue
            if severity and getattr(rule, 'severity', '') != severity:
                continue
            result.append(rule)
        return result

    def get_rule_by_id(self, rule_id: str) -> Optional[BaseReviewRule]:
        """Get a specific rule by ID."""
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        return None

    # ------------------------------------------------------------------ #
    #  File discovery
    # ------------------------------------------------------------------ #

    def discover_files(self, paths: List[str], recursive: bool = True,
                       gitignore: bool = True) -> Tuple[List[str], int]:
        """Discover source files to review.

        Args:
            paths: List of file or directory paths.
            recursive: Whether to recurse into directories.
            gitignore: Whether to respect .gitignore patterns.

        Returns:
            Tuple of (file_paths, skipped_count).
        """
        files: List[str] = []
        skipped = 0
        gitignore_patterns = self._load_gitignore_patterns(paths) if gitignore else []

        for path in paths:
            path = os.path.abspath(path)
            if os.path.isfile(path):
                ext = os.path.splitext(path)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    if not self._is_ignored(path, gitignore_patterns):
                        files.append(path)
                    else:
                        skipped += 1
                else:
                    skipped += 1
            elif os.path.isdir(path):
                for root, dirs, dir_files in os.walk(path):
                    if not recursive and root != path:
                        break
                    # Skip hidden directories and common non-source dirs
                    dirs[:] = [d for d in dirs
                               if not d.startswith(".")
                               and d not in ("__pycache__", "node_modules",
                                             "venv", ".venv", "env", ".env",
                                             "build", "dist", "target",
                                             "third_party", "third-party")]
                    for f in dir_files:
                        fpath = os.path.join(root, f)
                        ext = os.path.splitext(f)[1].lower()
                        if ext in SUPPORTED_EXTENSIONS:
                            if not self._is_ignored(fpath, gitignore_patterns):
                                files.append(fpath)
                            else:
                                skipped += 1
                        else:
                            skipped += 1
            else:
                skipped += 1

        return sorted(files), skipped

    def _load_gitignore_patterns(self, paths: List[str]) -> List[str]:
        """Load .gitignore patterns from project directories."""
        patterns: List[str] = []
        for path in paths:
            path = os.path.abspath(path)
            if os.path.isdir(path):
                gitignore_path = os.path.join(path, ".gitignore")
            else:
                gitignore_path = os.path.join(os.path.dirname(path), ".gitignore")

            if os.path.isfile(gitignore_path):
                try:
                    with open(gitignore_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#"):
                                patterns.append(line)
                except (OSError, UnicodeDecodeError):
                    pass
        return patterns

    def _is_ignored(self, filepath: str, patterns: List[str]) -> bool:
        """Check if a file matches any gitignore pattern."""
        for pattern in patterns:
            if fnmatch.fnmatch(os.path.basename(filepath), pattern):
                return True
            if fnmatch.fnmatch(filepath, pattern):
                return True
            # Check relative path components
            parts = filepath.replace("\\", "/").split("/")
            for part in parts:
                if fnmatch.fnmatch(part, pattern):
                    return True
        return False

    # ------------------------------------------------------------------ #
    #  File reading
    # ------------------------------------------------------------------ #

    def read_file(self, filepath: str) -> Optional[str]:
        """Read a source file with encoding detection."""
        encodings = ["utf-8", "latin-1", "cp1252", "iso-8859-1"]
        for enc in encodings:
            try:
                with open(filepath, "r", encoding=enc) as f:
                    return f.read()
            except (UnicodeDecodeError, OSError):
                continue
        return None

    # ------------------------------------------------------------------ #
    #  Parsing
    # ------------------------------------------------------------------ #

    def parse_file(self, source: str, filepath: str) -> Optional[ast.AST]:
        """Parse a source file into an AST. Returns None on failure."""
        ext = os.path.splitext(filepath)[1].lower()

        if ext == ".py":
            try:
                return ast.parse(source, filename=filepath)
            except SyntaxError as e:
                return None
        elif ext in (".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hh"):
            # For C/C++, we create a mock AST with the source text
            return _create_c_ast(source, filepath)
        elif ext == ".rs":
            return _create_rust_ast(source, filepath)
        return None

    # ------------------------------------------------------------------ #
    #  Run review
    # ------------------------------------------------------------------ #

    def review(self, files: List[str],
               rules: Optional[List[BaseReviewRule]] = None,
               min_severity: str = "INFO",
               progress_callback: Optional[Callable] = None) -> ReviewResult:
        """Run a full code review on the given files.

        Args:
            files: List of file paths to review.
            rules: Specific rules to run (default: all enabled rules).
            min_severity: Minimum severity to report.
            progress_callback: Optional callback for progress updates.

        Returns:
            ReviewResult with all found issues.
        """
        result = ReviewResult()
        result.files_scanned = len(files)
        start_time = time.time()

        rules_to_run = rules or self.get_rules()
        # Filter rules by minimum severity (lower number = more severe)
        min_order = SEVERITY_ORDER.get(min_severity.upper(), SEVERITY_ORDER["INFO"])
        rules_to_run = [r for r in rules_to_run
                        if SEVERITY_ORDER.get(r.severity, SEVERITY_ORDER["INFO"]) <= min_order]

        total_lines = 0

        for idx, filepath in enumerate(files):
            if progress_callback:
                progress_callback(idx + 1, len(files), filepath)

            source = self.read_file(filepath)
            if source is None:
                result.errors.append(f"Failed to read file: {filepath}")
                continue

            lines = source.splitlines()
            total_lines += len(lines)

            tree = self.parse_file(source, filepath)
            if tree is None:
                # Do line-based checks even without AST
                tree = _create_text_ast(source, filepath)

            # Run applicable rules
            for rule in rules_to_run:
                # Check if rule applies to this file (handle both BaseReviewRule and external rules)
                rule_languages = getattr(rule, 'languages', ['python'])
                ext = os.path.splitext(filepath)[1].lower()
                lang_map = {".py": "python", ".c": "c", ".h": "c",
                           ".cpp": "c", ".hpp": "c", ".cc": "c", ".cxx": "c", ".hh": "c",
                           ".rs": "rust"}
                file_lang = lang_map.get(ext, "")
                if file_lang and file_lang not in rule_languages:
                    continue
                try:
                    rule_result = rule.check(tree, filepath, source)
                    # Handle different rule result types
                    if hasattr(rule_result, 'issues'):
                        # External rule result (PerfRuleResult, SecurityRuleResult)
                        ext_issues = rule_result.issues
                        for ext_issue in ext_issues:
                            issue = ReviewIssue(
                                rule_id=getattr(ext_issue, 'rule_id', rule.rule_id),
                                rule_name=getattr(ext_issue, 'rule_name', rule.name),
                                severity=getattr(ext_issue, 'severity', 'MEDIUM'),
                                message=getattr(ext_issue, 'message', ''),
                                file_path=getattr(ext_issue, 'file_path', filepath),
                                line_number=getattr(ext_issue, 'line_number', 0),
                                column=getattr(ext_issue, 'column', 0),
                                end_line=getattr(ext_issue, 'end_line', 0),
                                end_column=getattr(ext_issue, 'end_column', 0),
                                snippet=getattr(ext_issue, 'snippet', ''),
                                remediation=getattr(ext_issue, 'remediation', ''),
                                category=getattr(ext_issue, 'category', ''),
                                cwe=getattr(ext_issue, 'cwe', ''),
                            )
                            if SEVERITY_ORDER.get(issue.severity, SEVERITY_ORDER["INFO"]) <= min_order:
                                result.issues.append(issue)
                    elif isinstance(rule_result, list):
                        # ReviewIssue list
                        for issue in rule_result:
                            if SEVERITY_ORDER.get(issue.severity, SEVERITY_ORDER["INFO"]) <= min_order:
                                result.issues.append(issue)
                except Exception as e:
                    result.errors.append(
                        f"Rule {rule.rule_id} failed on {filepath}: {e}"
                    )

        result.total_lines = total_lines
        result.duration_ms = (time.time() - start_time) * 1000
        return result


# ---------------------------------------------------------------------------
# General-purpose review rules
# ---------------------------------------------------------------------------

class NamingConventionRule(BaseReviewRule):
    """Check naming conventions (snake_case, CamelCase, etc.)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._rule_id = "REVIEW-NAMING-001"
        self._name = "Naming Convention"
        self._description = "Enforces naming conventions (snake_case for functions/variables, CamelCase for classes)"
        self._severity = "LOW"
        self._languages = ["python"]
        self._category = "style"

    @property
    def rule_id(self) -> str: return self._rule_id
    @property
    def name(self) -> str: return self._name
    @property
    def description(self) -> str: return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> List[ReviewIssue]:
        issues: List[ReviewIssue] = []
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if not node.name.startswith("_") and not re.match(r'^[a-z_][a-z0-9_]*$', node.name):
                    issues.append(ReviewIssue(
                        rule_id=self.rule_id, rule_name=self.name,
                        severity="LOW",
                        message=f"Function '{node.name}' should use snake_case naming",
                        file_path=file_path, line_number=node.lineno,
                        snippet=lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                        remediation=f"Rename '{node.name}' to use snake_case (e.g., {self._to_snake_case(node.name)})",
                        category="style",
                    ))
            elif isinstance(node, ast.ClassDef):
                if not re.match(r'^[A-Z][a-zA-Z0-9]*$', node.name):
                    issues.append(ReviewIssue(
                        rule_id=self.rule_id, rule_name=self.name,
                        severity="LOW",
                        message=f"Class '{node.name}' should use CamelCase naming",
                        file_path=file_path, line_number=node.lineno,
                        snippet=lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                        remediation=f"Rename '{node.name}' to use CamelCase (e.g., {node.name.capitalize()})",
                        category="style",
                    ))

        return issues

    def _to_snake_case(self, name: str) -> str:
        s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


class DocstringRule(BaseReviewRule):
    """Check that functions and classes have docstrings."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._rule_id = "REVIEW-DOC-001"
        self._name = "Missing Docstring"
        self._description = "Checks that public functions, classes, and methods have docstrings"
        self._severity = "LOW"
        self._languages = ["python"]
        self._category = "documentation"

    @property
    def rule_id(self) -> str: return self._rule_id
    @property
    def name(self) -> str: return self._name
    @property
    def description(self) -> str: return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> List[ReviewIssue]:
        issues: List[ReviewIssue] = []
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("__") and node.name != "__init__":
                    continue
                docstring = ast.get_docstring(node)
                if not docstring:
                    issues.append(ReviewIssue(
                        rule_id=self.rule_id, rule_name=self.name,
                        severity="LOW" if not node.name.startswith("_") else "INFO",
                        message=f"Missing docstring for {'function' if not isinstance(node, ast.AsyncFunctionDef) else 'async function'} '{node.name}'",
                        file_path=file_path, line_number=node.lineno,
                        snippet=lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                        remediation=f"Add a docstring describing the purpose, parameters, and return value of '{node.name}'",
                        category="documentation",
                    ))
            elif isinstance(node, ast.ClassDef):
                docstring = ast.get_docstring(node)
                if not docstring:
                    issues.append(ReviewIssue(
                        rule_id=self.rule_id, rule_name=self.name,
                        severity="LOW",
                        message=f"Missing docstring for class '{node.name}'",
                        file_path=file_path, line_number=node.lineno,
                        snippet=lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                        remediation=f"Add a class-level docstring describing the purpose of '{node.name}'",
                        category="documentation",
                    ))

        # Check module-level docstring
        if isinstance(tree, ast.Module):
            module_doc = ast.get_docstring(tree)
            if not module_doc and file_path.endswith(".py"):
                module_name = os.path.basename(file_path)
                if module_name != "__init__.py":
                    issues.append(ReviewIssue(
                        rule_id=self.rule_id, rule_name=self.name,
                        severity="INFO",
                        message=f"Missing module-level docstring in '{os.path.basename(file_path)}'",
                        file_path=file_path, line_number=1,
                        remediation="Add a module-level docstring describing the module's purpose",
                        category="documentation",
                    ))

        return issues


class LineLengthRule(BaseReviewRule):
    """Check line length exceeds recommended limits."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._rule_id = "REVIEW-STYLE-001"
        self._name = "Line Length"
        self._description = "Checks that lines do not exceed the maximum recommended length"
        self._severity = "INFO"
        self._languages = ["python", "c", "rust"]
        self._category = "style"
        self._max_length = self.config.get("max_line_length", 100)

    @property
    def rule_id(self) -> str: return self._rule_id
    @property
    def name(self) -> str: return self._name
    @property
    def description(self) -> str: return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> List[ReviewIssue]:
        issues: List[ReviewIssue] = []
        lines = source_code.splitlines()

        for i, line in enumerate(lines, 1):
            if len(line) > self._max_length and not line.rstrip().startswith("#"):
                issues.append(ReviewIssue(
                    rule_id=self.rule_id, rule_name=self.name,
                    severity="INFO",
                    message=f"Line {i} exceeds {self._max_length} characters ({len(line)} chars)",
                    file_path=file_path, line_number=i,
                    snippet=line[:80] + "..." if len(line) > 80 else line,
                    remediation=f"Split this line into multiple lines or refactor to reduce its length below {self._max_length} characters",
                    category="style",
                ))

        return issues


class TodoFixmeRule(BaseReviewRule):
    """Flag TODO, FIXME, HACK, XXX comments."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._rule_id = "REVIEW-TODO-001"
        self._name = "TODO/FIXME Detected"
        self._description = "Flags TODO, FIXME, HACK, XXX, and NOTE comments that may need attention"
        self._severity = "INFO"
        self._languages = ["python", "c", "rust"]
        self._category = "maintainability"

    @property
    def rule_id(self) -> str: return self._rule_id
    @property
    def name(self) -> str: return self._name
    @property
    def description(self) -> str: return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> List[ReviewIssue]:
        issues: List[ReviewIssue] = []
        lines = source_code.splitlines()

        patterns = [
            (r'#\s*TODO\b', "TODO", "INFO"),
            (r'#\s*FIXME\b', "FIXME", "MEDIUM"),
            (r'#\s*HACK\b', "HACK", "MEDIUM"),
            (r'#\s*XXX\b', "XXX", "LOW"),
            (r'#\s*NOTE\b', "NOTE", "INFO"),
            (r'#\s*OPTIMIZE\b', "OPTIMIZE", "LOW"),
            (r'//\s*TODO\b', "TODO", "INFO"),
            (r'//\s*FIXME\b', "FIXME", "MEDIUM"),
            (r'//\s*HACK\b', "HACK", "MEDIUM"),
            (r'/\*\s*TODO\b', "TODO", "INFO"),
            (r'/\*\s*FIXME\b', "FIXME", "MEDIUM"),
        ]

        for i, line in enumerate(lines, 1):
            for pattern, tag, severity in patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    comment_text = line[match.start():].strip()
                    issues.append(ReviewIssue(
                        rule_id=self.rule_id, rule_name=self.name,
                        severity=severity,
                        message=f"{tag} comment found at line {i}: {comment_text[:80]}",
                        file_path=file_path, line_number=i,
                        snippet=line.strip(),
                        remediation=f"Address the {tag} comment: {comment_text}",
                        category="maintainability",
                        evidence={"tag": tag, "text": comment_text},
                    ))
                    break

        return issues


class ImportOrderRule(BaseReviewRule):
    """Check import ordering (stdlib, third-party, local)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._rule_id = "REVIEW-IMPORT-001"
        self._name = "Import Order"
        self._description = "Checks that imports are grouped and ordered correctly (stdlib, third-party, local)"
        self._severity = "LOW"
        self._languages = ["python"]
        self._category = "style"

    @property
    def rule_id(self) -> str: return self._rule_id
    @property
    def name(self) -> str: return self._name
    @property
    def description(self) -> str: return self._description

    # Python stdlib modules for import ordering
    STDLIB_MODULES = {
        "abc", "ast", "asyncio", "base64", "collections", "copy", "csv",
        "datetime", "decimal", "enum", "functools", "glob", "hashlib",
        "html", "http", "importlib", "inspect", "io", "itertools", "json",
        "logging", "math", "os", "pathlib", "pickle", "platform", "pprint",
        "queue", "random", "re", "secrets", "shutil", "signal", "socket",
        "sqlite3", "ssl", "statistics", "string", "struct", "subprocess",
        "sys", "tempfile", "textwrap", "threading", "time", "traceback",
        "typing", "unittest", "urllib", "uuid", "warnings", "weakref",
        "xml", "zipfile", "zlib", "dataclasses", "argparse", "configparser",
        "contextlib", "contextvars", "dis", "doctest", "filecmp",
        "fnmatch", "fractions", "getopt", "getpass", "gettext",
        "gzip", "hashlib", "keyword", "linecache", "locale",
        "marshal", "mimetypes", "numbers", "operator", "optparse",
    }

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> List[ReviewIssue]:
        issues: List[ReviewIssue] = []
        lines = source_code.splitlines()

        # Collect import groups
        stdlib_imports: List[int] = []
        third_party_imports: List[int] = []
        local_imports: List[int] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    base = alias.name.split(".")[0]
                    if base in self.STDLIB_MODULES:
                        stdlib_imports.append(node.lineno)
                    elif alias.name.startswith("."):
                        local_imports.append(node.lineno)
                    else:
                        third_party_imports.append(node.lineno)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    base = node.module.split(".")[0]
                    if node.level and node.level > 0:
                        local_imports.append(node.lineno)
                    elif base in self.STDLIB_MODULES:
                        stdlib_imports.append(node.lineno)
                    else:
                        third_party_imports.append(node.lineno)

        # Check ordering: stdlib > third-party > local
        all_imports = sorted(stdlib_imports + third_party_imports + local_imports)
        expected_order = sorted(stdlib_imports) + sorted(third_party_imports) + sorted(local_imports)

        if all_imports != expected_order and all_imports:
            # Find first misordered import
            for actual, expected in zip(all_imports, expected_order):
                if actual != expected:
                    line_idx = actual
                    issues.append(ReviewIssue(
                        rule_id=self.rule_id, rule_name=self.name,
                        severity="LOW",
                        message=f"Import at line {line_idx} is out of order. Expected order: stdlib, third-party, then local imports",
                        file_path=file_path, line_number=line_idx,
                        snippet=lines[line_idx - 1] if line_idx <= len(lines) else "",
                        remediation="Group imports in this order: standard library, third-party packages, then local modules. Separate groups with a blank line.",
                        category="style",
                    ))
                    break

        # Check for blank line separation between groups
        if stdlib_imports and third_party_imports:
            last_stdlib = max(stdlib_imports)
            first_third = min(third_party_imports)
            if first_third - last_stdlib < 2:
                issues.append(ReviewIssue(
                    rule_id=self.rule_id, rule_name=self.name,
                    severity="INFO",
                    message="No blank line between stdlib and third-party imports",
                    file_path=file_path, line_number=last_stdlib,
                    remediation="Add a blank line between stdlib and third-party import groups",
                    category="style",
                ))

        return issues


class ShadowedBuiltinsRule(BaseReviewRule):
    """Detect shadowing of Python built-in names."""

    BUILTINS = {
        "abs", "all", "any", "bin", "bool", "bytearray", "bytes", "callable",
        "chr", "classmethod", "compile", "complex", "delattr", "dict", "dir",
        "divmod", "enumerate", "eval", "exec", "filter", "float", "format",
        "frozenset", "getattr", "globals", "hasattr", "hash", "hex", "id",
        "input", "int", "isinstance", "issubclass", "iter", "len", "list",
        "locals", "map", "max", "memoryview", "min", "next", "object", "oct",
        "open", "ord", "pow", "print", "property", "range", "repr", "reversed",
        "round", "set", "setattr", "slice", "sorted", "staticmethod", "str",
        "sum", "super", "tuple", "type", "vars", "zip", "__import__",
        "Exception", "BaseException", "ValueError", "TypeError", "KeyError",
        "IndexError", "AttributeError", "ImportError", "StopIteration",
        "RuntimeError", "OSError", "IOError", "FileNotFoundError",
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._rule_id = "REVIEW-SHADOW-001"
        self._name = "Shadowed Builtins"
        self._description = "Detects variable names that shadow Python built-in names"
        self._severity = "LOW"
        self._languages = ["python"]
        self._category = "correctness"

    @property
    def rule_id(self) -> str: return self._rule_id
    @property
    def name(self) -> str: return self._name
    @property
    def description(self) -> str: return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> List[ReviewIssue]:
        issues: List[ReviewIssue] = []
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if node.name in self.BUILTINS:
                    issues.append(ReviewIssue(
                        rule_id=self.rule_id, rule_name=self.name,
                        severity="LOW",
                        message=f"Function '{node.name}' shadows Python built-in name",
                        file_path=file_path, line_number=node.lineno,
                        snippet=lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                        remediation=f"Rename function '{node.name}' to avoid shadowing the built-in",
                        category="correctness",
                    ))
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                if node.id in self.BUILTINS:
                    issues.append(ReviewIssue(
                        rule_id=self.rule_id, rule_name=self.name,
                        severity="INFO",
                        message=f"Variable '{node.id}' shadows Python built-in name",
                        file_path=file_path, line_number=node.lineno,
                        snippet=lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                        remediation=f"Rename variable '{node.id}' to avoid shadowing the built-in",
                        category="correctness",
                    ))

        return issues


class ComplexityRule(BaseReviewRule):
    """Flag overly complex functions."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._rule_id = "REVIEW-COMPLEX-001"
        self._name = "Function Complexity"
        self._description = "Flags functions with high cyclomatic complexity, excessive parameters, or excessive length"
        self._severity = "MEDIUM"
        self._languages = ["python"]
        self._category = "maintainability"
        self._max_complexity = self.config.get("max_complexity", 10)
        self._max_params = self.config.get("max_params", 6)
        self._max_lines = self.config.get("max_function_lines", 50)

    @property
    def rule_id(self) -> str: return self._rule_id
    @property
    def name(self) -> str: return self._name
    @property
    def description(self) -> str: return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> List[ReviewIssue]:
        issues: List[ReviewIssue] = []
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_lines = (node.end_lineno or node.lineno) - node.lineno
                param_count = len(node.args.args) + len(node.args.kwonlyargs)
                if node.args.vararg:
                    param_count += 1
                if node.args.kwarg:
                    param_count += 1

                complexity = self._compute_cyclomatic(node)

                if complexity > self._max_complexity:
                    issues.append(ReviewIssue(
                        rule_id=self.rule_id, rule_name=self.name,
                        severity="MEDIUM",
                        message=f"Function '{node.name}' has high cyclomatic complexity ({complexity}, max: {self._max_complexity})",
                        file_path=file_path, line_number=node.lineno,
                        snippet=lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                        remediation=f"Refactor '{node.name}' into smaller functions to reduce complexity below {self._max_complexity}",
                        category="maintainability",
                        evidence={"complexity": complexity, "max": self._max_complexity},
                    ))

                if param_count > self._max_params:
                    issues.append(ReviewIssue(
                        rule_id=self.rule_id, rule_name=self.name,
                        severity="MEDIUM",
                        message=f"Function '{node.name}' has {param_count} parameters (max: {self._max_params})",
                        file_path=file_path, line_number=node.lineno,
                        snippet=lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                        remediation=f"Consider reducing the number of parameters by using a data class or **kwargs",
                        category="maintainability",
                    ))

                if func_lines > self._max_lines:
                    issues.append(ReviewIssue(
                        rule_id=self.rule_id, rule_name=self.name,
                        severity="LOW",
                        message=f"Function '{node.name}' is {func_lines} lines long (max: {self._max_lines})",
                        file_path=file_path, line_number=node.lineno,
                        snippet=lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                        remediation=f"Consider breaking '{node.name}' into smaller functions",
                        category="maintainability",
                    ))

        return issues

    def _compute_cyclomatic(self, node: ast.AST) -> int:
        """Compute McCabe's cyclomatic complexity for a function."""
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor,
                                  ast.ExceptHandler, ast.Assert)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
        return complexity


class ErrorHandlingRule(BaseReviewRule):
    """Check for proper error handling patterns."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._rule_id = "REVIEW-ERROR-001"
        self._name = "Error Handling"
        self._description = "Detects bare except clauses, missing error handling, and overly broad exception handling"
        self._severity = "MEDIUM"
        self._languages = ["python"]
        self._category = "correctness"

    @property
    def rule_id(self) -> str: return self._rule_id
    @property
    def name(self) -> str: return self._name
    @property
    def description(self) -> str: return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> List[ReviewIssue]:
        issues: List[ReviewIssue] = []
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            # Bare except
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                issues.append(ReviewIssue(
                    rule_id=self.rule_id, rule_name=self.name,
                    severity="MEDIUM",
                    message="Bare 'except:' clause catches all exceptions including SystemExit and KeyboardInterrupt",
                    file_path=file_path, line_number=node.lineno,
                    snippet=lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                    remediation="Specify the exception type (e.g., 'except ValueError:') or use 'except Exception:' if you must catch all",
                    category="correctness",
                ))

            # Overly broad except
            if isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Name):
                if node.type.id == "Exception" and node.lineno:
                    # Check if the body just passes or logs
                    body_has_action = any(
                        not isinstance(stmt, (ast.Pass, ast.Expr))
                        for stmt in node.body
                    )
                    if not body_has_action:
                        issues.append(ReviewIssue(
                            rule_id=self.rule_id, rule_name=self.name,
                            severity="LOW",
                            message=f"Bare 'except Exception:' at line {node.lineno} silently swallows all exceptions",
                            file_path=file_path, line_number=node.lineno,
                            snippet=lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                            remediation="Log the exception or handle specific exception types instead of catching all",
                            category="correctness",
                        ))

            # Empty try block
            if isinstance(node, ast.Try):
                if not node.body or all(isinstance(stmt, ast.Pass) for stmt in node.body):
                    issues.append(ReviewIssue(
                        rule_id=self.rule_id, rule_name=self.name,
                        severity="MEDIUM",
                        message="Empty try block at line {node.lineno}",
                        file_path=file_path, line_number=node.lineno,
                        snippet=lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                        remediation="Remove the empty try block or add code that may raise an exception",
                        category="correctness",
                    ))

        return issues


class TypeAnnotationRule(BaseReviewRule):
    """Check for missing type annotations."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._rule_id = "REVIEW-TYPE-001"
        self._name = "Type Annotation"
        self._description = "Checks for missing type annotations on function parameters and return values"
        self._severity = "LOW"
        self._languages = ["python"]
        self._category = "type_safety"

    @property
    def rule_id(self) -> str: return self._rule_id
    @property
    def name(self) -> str: return self._name
    @property
    def description(self) -> str: return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> List[ReviewIssue]:
        issues: List[ReviewIssue] = []
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in ("__init__", "__new__", "__post_init__"):
                    continue

                # Check return annotation
                if node.returns is None and not node.name.startswith("_"):
                    issues.append(ReviewIssue(
                        rule_id=self.rule_id, rule_name=self.name,
                        severity="INFO",
                        message=f"Function '{node.name}' is missing return type annotation",
                        file_path=file_path, line_number=node.lineno,
                        snippet=lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                        remediation=f"Add return type annotation to '{node.name}': def {node.name}(...) -> <type>:",
                        category="type_safety",
                    ))

                # Check parameter annotations
                for arg in node.args.args:
                    if arg.annotation is None and arg.arg not in ("self", "cls"):
                        issues.append(ReviewIssue(
                            rule_id=self.rule_id, rule_name=self.name,
                            severity="INFO",
                            message=f"Parameter '{arg.arg}' in function '{node.name}' is missing type annotation",
                            file_path=file_path, line_number=node.lineno,
                            snippet=lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                            remediation=f"Add type annotation to parameter '{arg.arg}'",
                            category="type_safety",
                        ))

        return issues


class MagicNumberRule(BaseReviewRule):
    """Detect magic numbers (unnamed numeric constants)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._rule_id = "REVIEW-MAGIC-001"
        self._name = "Magic Number"
        self._description = "Detects unnamed numeric constants (magic numbers) that should be named constants"
        self._severity = "LOW"
        self._languages = ["python"]
        self._category = "maintainability"

    @property
    def rule_id(self) -> str: return self._rule_id
    @property
    def name(self) -> str: return self._name
    @property
    def description(self) -> str: return self._description

    # Common non-magic numbers (0, 1, -1, etc.)
    SAFE_NUMBERS = {0, 1, -1, 0.0, 1.0, -1.0, 100, 2, 0.5, 60, 24, 12, 7, 365}

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> List[ReviewIssue]:
        issues: List[ReviewIssue] = []
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, ast.Constant):
                if isinstance(node.value, (int, float)) and node.value not in self.SAFE_NUMBERS:
                    # Check if it's assigned to a constant or used in a comparison
                    parent = self._find_parent(node, tree)
                    if parent and not isinstance(parent, ast.Assign):
                        # Skip if it's a common value like 0, 1, 100, etc.
                        if abs(node.value) > 1 and node.value != 100:
                            issues.append(ReviewIssue(
                                rule_id=self.rule_id, rule_name=self.name,
                                severity="INFO",
                                message=f"Magic number {node.value} found at line {node.lineno}. Consider defining it as a named constant.",
                                file_path=file_path, line_number=node.lineno,
                                snippet=lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                                remediation=f"Replace {node.value} with a named constant (e.g., UPPER_CASE_VARIABLE = {node.value})",
                                category="maintainability",
                            ))

        return issues

    def _find_parent(self, target: ast.AST, tree: ast.AST) -> Optional[ast.AST]:
        """Find the parent AST node of a given node."""
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                if child is target:
                    return node
        return None


class UnusedVariableRule(BaseReviewRule):
    """Detect unused variables and imports."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._rule_id = "REVIEW-UNUSED-001"
        self._name = "Unused Variable"
        self._description = "Detects variables that are assigned but never used"
        self._severity = "LOW"
        self._languages = ["python"]
        self._category = "correctness"

    @property
    def rule_id(self) -> str: return self._rule_id
    @property
    def name(self) -> str: return self._name
    @property
    def description(self) -> str: return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> List[ReviewIssue]:
        issues: List[ReviewIssue] = []
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Find variables assigned in this function
                assigned: Set[str] = set()
                used: Set[str] = set()

                for child in ast.walk(node):
                    if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                        if child.id not in ("self", "cls"):
                            assigned.add(child.id)
                    if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                        used.add(child.id)

                unused = assigned - used - {"_"}
                for var_name in unused:
                    # Find the line where it was assigned
                    for child in ast.walk(node):
                        if isinstance(child, ast.Name) and child.id == var_name and isinstance(child.ctx, ast.Store):
                            if child.lineno:
                                issues.append(ReviewIssue(
                                    rule_id=self.rule_id, rule_name=self.name,
                                    severity="LOW",
                                    message=f"Unused variable '{var_name}' in function '{node.name}'",
                                    file_path=file_path, line_number=child.lineno,
                                    snippet=lines[child.lineno - 1] if child.lineno <= len(lines) else "",
                                    remediation=f"Remove '{var_name}' or prefix with underscore if intentionally unused",
                                    category="correctness",
                                ))
                                break

        return issues


class DuplicateCodeRule(BaseReviewRule):
    """Detect duplicate code blocks (simple text-based detection)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._rule_id = "REVIEW-DUP-001"
        self._name = "Duplicate Code"
        self._description = "Detects duplicate or near-duplicate code blocks within a file"
        self._severity = "MEDIUM"
        self._languages = ["python", "c", "rust"]
        self._category = "maintainability"
        self._min_lines = self.config.get("min_duplicate_lines", 6)

    @property
    def rule_id(self) -> str: return self._rule_id
    @property
    def name(self) -> str: return self._name
    @property
    def description(self) -> str: return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> List[ReviewIssue]:
        issues: List[ReviewIssue] = []
        lines = source_code.splitlines()

        if len(lines) < self._min_lines * 2:
            return issues

        # Simple hash-based duplicate detection
        # Hash each line and look for repeated sequences
        line_hashes = []
        for line in lines:
            # Normalize: remove whitespace, lowercase
            normalized = re.sub(r'\s+', '', line).lower()
            line_hashes.append(hash(normalized))

        # Look for repeated sequences of min_lines length
        seen_sequences: Dict[Tuple[int, ...], int] = {}

        for i in range(len(lines) - self._min_lines + 1):
            seq = tuple(line_hashes[i:i + self._min_lines])
            if seq in seen_sequences:
                prev_line = seen_sequences[seq]
                # Only report if not already reported for this range
                if abs(prev_line - i) > self._min_lines:
                    issues.append(ReviewIssue(
                        rule_id=self.rule_id, rule_name=self.name,
                        severity="MEDIUM",
                        message=f"Duplicate code block (lines {prev_line + 1}-{prev_line + self._min_lines}) similar to lines {i + 1}-{i + self._min_lines}",
                        file_path=file_path, line_number=i + 1,
                        snippet=lines[i + 1] if i + 1 < len(lines) else "",
                        remediation="Extract the duplicated code into a shared function or loop",
                        category="maintainability",
                        evidence={"start_line_1": prev_line + 1, "start_line_2": i + 1},
                    ))
                    break  # One report per set
            else:
                seen_sequences[seq] = i

        return issues


class ResourceLeakRule(BaseReviewRule):
    """Detect potential resource leaks (unclosed files, connections)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._rule_id = "REVIEW-RESOURCE-001"
        self._name = "Resource Leak"
        self._description = "Detects unclosed file handles, connections, and other resources"
        self._severity = "HIGH"
        self._languages = ["python", "c", "rust"]
        self._category = "correctness"

    @property
    def rule_id(self) -> str: return self._rule_id
    @property
    def name(self) -> str: return self._name
    @property
    def description(self) -> str: return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> List[ReviewIssue]:
        issues: List[ReviewIssue] = []
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Check for open() without context manager
                if isinstance(node.func, ast.Name) and node.func.id == "open":
                    if not self._is_in_with(node, tree):
                        issues.append(ReviewIssue(
                            rule_id=self.rule_id, rule_name=self.name,
                            severity="MEDIUM",
                            message=f"File opened with open() at line {node.lineno} without using a context manager ('with' statement)",
                            file_path=file_path, line_number=node.lineno,
                            snippet=lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                            remediation="Use 'with open(...) as f:' to ensure the file is properly closed, even if an exception occurs",
                            category="correctness",
                        ))

        # C: check for fopen without fclose
        if file_path.endswith((".c", ".h", ".cpp", ".hpp")):
            fopen_count = len(re.findall(r'\bfopen\s*\(', source_code))
            fclose_count = len(re.findall(r'\bfclose\s*\(', source_code))
            malloc_count = len(re.findall(r'\bmalloc\s*\(', source_code))
            free_count = len(re.findall(r'\bfree\s*\(', source_code))

            if fopen_count > fclose_count:
                issues.append(ReviewIssue(
                    rule_id=self.rule_id, rule_name=self.name,
                    severity="HIGH",
                    message=f"Potential file handle leak: {fopen_count} fopen() calls but only {fclose_count} fclose() calls",
                    file_path=file_path, line_number=1,
                    remediation="Ensure every fopen() call has a matching fclose() call, preferably in a cleanup section",
                    category="correctness",
                ))

            if malloc_count > free_count + 5:
                issues.append(ReviewIssue(
                    rule_id=self.rule_id, rule_name=self.name,
                    severity="HIGH",
                    message=f"Potential memory leak: {malloc_count} malloc() calls but only {free_count} free() calls",
                    file_path=file_path, line_number=1,
                    remediation="Ensure every malloc() has a matching free() call",
                    category="correctness",
                ))

        return issues

    def _is_in_with(self, call_node: ast.Call, tree: ast.AST) -> bool:
        """Check if a call node is inside a 'with' statement."""
        for node in ast.walk(tree):
            if isinstance(node, ast.With):
                for item in node.items:
                    if item.context_expr is call_node:
                        return True
                    # Check if the call is the context_expr
                    context_vars = [c for c in ast.walk(item.context_expr)]
                    if call_node in context_vars and call_node is not item.context_expr:
                        return True
        return False


class ConcurrencyRule(BaseReviewRule):
    """Check for common concurrency issues."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._rule_id = "REVIEW-CONCUR-001"
        self._name = "Concurrency Issues"
        self._description = "Detects common concurrency issues like shared state without locks and thread-unsafe patterns"
        self._severity = "HIGH"
        self._languages = ["python"]
        self._category = "concurrency"

    @property
    def rule_id(self) -> str: return self._rule_id
    @property
    def name(self) -> str: return self._name
    @property
    def description(self) -> str: return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> List[ReviewIssue]:
        issues: List[ReviewIssue] = []
        lines = source_code.splitlines()

        has_threading = False
        has_lock = False
        has_shared_state = False

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "threading" or alias.name.startswith("threading."):
                        has_threading = True
                    if alias.name in ("asyncio", "concurrent"):
                        has_threading = True
            elif isinstance(node, ast.ImportFrom):
                if node.module and "threading" in node.module:
                    has_threading = True
                    for alias in node.names:
                        if alias.name in ("Lock", "RLock", "Semaphore"):
                            has_lock = True

        if has_threading and not has_lock:
            # Check for shared global variables
            for node in ast.walk(tree):
                if isinstance(node, ast.Global):
                    has_shared_state = True
                    break

            if has_shared_state:
                issues.append(ReviewIssue(
                    rule_id=self.rule_id, rule_name=self.name,
                    severity="HIGH",
                    message="Shared global state accessed in threaded code without locks",
                    file_path=file_path, line_number=1,
                    remediation="Protect shared state with threading.Lock() or use thread-safe data structures like queue.Queue",
                    category="concurrency",
                ))

        # Check for time.sleep() in async functions
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                for child in ast.walk(node):
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                        if child.func.attr == "sleep" and isinstance(child.func.value, ast.Name) and child.func.value.id == "time":
                            issues.append(ReviewIssue(
                                rule_id=self.rule_id, rule_name=self.name,
                                severity="HIGH",
                                message=f"Blocking call time.sleep() in async function '{node.name}' at line {child.lineno}",
                                file_path=file_path, line_number=child.lineno or 0,
                                snippet=lines[(child.lineno or 1) - 1] if child.lineno and child.lineno <= len(lines) else "",
                                remediation="Use asyncio.sleep() instead of time.sleep() in async functions",
                                category="concurrency",
                            ))

        return issues


class LoggingRule(BaseReviewRule):
    """Check for proper logging practices."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self._rule_id = "REVIEW-LOG-001"
        self._name = "Logging Practices"
        self._description = "Checks for proper logging practices (avoid print(), use logging, proper string formatting)"
        self._severity = "LOW"
        self._languages = ["python"]
        self._category = "best_practice"

    @property
    def rule_id(self) -> str: return self._rule_id
    @property
    def name(self) -> str: return self._name
    @property
    def description(self) -> str: return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> List[ReviewIssue]:
        issues: List[ReviewIssue] = []
        lines = source_code.splitlines()

        has_logging = False
        print_count = 0

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "logging":
                        has_logging = True
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module == "logging":
                    has_logging = True
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "print":
                    print_count += 1

        if print_count > 2 and not has_logging:
            issues.append(ReviewIssue(
                rule_id=self.rule_id, rule_name=self.name,
                severity="LOW",
                message=f"File uses print() {print_count} times but does not use the logging module",
                file_path=file_path, line_number=1,
                remediation="Use the 'logging' module instead of print() for production code. Configure appropriate log levels (debug, info, warning, error).",
                category="best_practice",
            ))

        # Check for f-string in logging calls (lazy formatting preferred)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("debug", "info", "warning", "error", "critical"):
                    if node.args and isinstance(node.args[0], ast.JoinedStr):
                        issues.append(ReviewIssue(
                            rule_id=self.rule_id, rule_name=self.name,
                            severity="INFO",
                            message=f"f-string in logging call at line {node.lineno}. Use lazy % formatting instead.",
                            file_path=file_path, line_number=node.lineno or 0,
                            snippet=lines[(node.lineno or 1) - 1] if node.lineno and node.lineno <= len(lines) else "",
                            remediation="Replace f-string with lazy formatting: logger.info('message %s', variable)",
                            category="best_practice",
                        ))

        return issues


# ---------------------------------------------------------------------------
# C/C++ AST mock
# ---------------------------------------------------------------------------

class _CModuleNode(ast.AST):
    """Mock AST node for C source files."""
    _fields = ("body",)
    def __init__(self, body: Optional[List[ast.AST]] = None) -> None:
        super().__init__()
        self.body = body or []
        self.lineno = 1
        self.end_lineno = 1


class _RustModuleNode(ast.AST):
    """Mock AST node for Rust source files."""
    _fields = ("body",)
    def __init__(self, body: Optional[List[ast.AST]] = None) -> None:
        super().__init__()
        self.body = body or []
        self.lineno = 1
        self.end_lineno = 1


class _TextModuleNode(ast.AST):
    """Mock AST node for text-based analysis."""
    _fields = ("body",)
    def __init__(self, body: Optional[List[ast.AST]] = None) -> None:
        super().__init__()
        self.body = body or []
        self.lineno = 1
        self.end_lineno = 1


def _create_c_ast(source: str, filepath: str) -> _CModuleNode:
    """Create a mock AST for C/C++ source files."""
    return _CModuleNode()


def _create_rust_ast(source: str, filepath: str) -> _RustModuleNode:
    """Create a mock AST for Rust source files."""
    return _RustModuleNode()


def _create_text_ast(source: str, filepath: str) -> _TextModuleNode:
    """Create a mock AST for text-based analysis."""
    return _TextModuleNode()


# ---------------------------------------------------------------------------
# Report generators
# ---------------------------------------------------------------------------

class MarkdownReport:
    """Generate Markdown-format review reports."""

    @staticmethod
    def generate(result: ReviewResult, title: str = "Code Review Report") -> str:
        """Generate a Markdown report."""
        lines: List[str] = []
        lines.append(f"# {title}")
        lines.append("")
        lines.append(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        lines.append(f"**Files scanned:** {result.files_scanned}")
        lines.append(f"**Total issues:** {result.issue_count}")
        lines.append(f"**Duration:** {result.duration_ms:.0f}ms")
        lines.append("")

        # Summary table
        lines.append("## Summary")
        lines.append("")
        lines.append("| Severity | Count |")
        lines.append("|----------|-------|")
        counts = result.severity_counts()
        for sev in SEVERITY_LEVELS:
            count = counts.get(sev, 0)
            if count > 0:
                lines.append(f"| **{sev}** | {count} |")
        lines.append("")

        # Issues by severity
        if result.issues:
            lines.append("## Issues")
            lines.append("")

            for severity in SEVERITY_LEVELS:
                sev_issues = [i for i in result.issues if i.severity == severity]
                if not sev_issues:
                    continue

                lines.append(f"### {severity}")
                lines.append("")

                for i, issue in enumerate(sev_issues, 1):
                    rel_path = os.path.relpath(issue.file_path) if issue.file_path else "?"
                    lines.append(f"**{i}. [{issue.rule_id}] {issue.message}**")
                    lines.append("")
                    lines.append(f"- **File:** `{rel_path}`")
                    lines.append(f"- **Line:** {issue.line_number}")
                    lines.append(f"- **Rule:** {issue.rule_name}")
                    lines.append(f"- **Severity:** {issue.severity}")
                    if issue.snippet:
                        lines.append(f"- **Snippet:** `{issue.snippet.strip()}`")
                    if issue.remediation:
                        lines.append(f"- **Remediation:** {issue.remediation}")
                    if issue.category:
                        lines.append(f"- **Category:** {issue.category}")
                    lines.append("")

        # File summary
        lines.append("## Files Scanned")
        lines.append("")
        lines.append(f"- Total files: {result.files_scanned}")
        lines.append(f"- Files skipped: {result.files_skipped}")
        lines.append(f"- Total lines: {result.total_lines}")
        lines.append("")

        if result.errors:
            lines.append("## Errors")
            lines.append("")
            for err in result.errors:
                lines.append(f"- {err}")
            lines.append("")

        return "\n".join(lines)


class JSONReport:
    """Generate JSON-format review reports."""

    @staticmethod
    def generate(result: ReviewResult, pretty: bool = True) -> str:
        """Generate a JSON report."""
        report = {
            "version": VERSION,
            "app_name": APP_NAME,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "files_scanned": result.files_scanned,
                "files_skipped": result.files_skipped,
                "total_lines": result.total_lines,
                "total_issues": result.issue_count,
                "duration_ms": result.duration_ms,
                "severity_counts": result.severity_counts(),
            },
            "issues": [issue.to_dict() for issue in result.issues],
            "errors": result.errors,
            "warnings": result.warnings,
            "config": result.config,
        }
        indent = 2 if pretty else None
        return json.dumps(report, indent=indent, default=str)


class SARIFReport:
    """Generate SARIF (Static Analysis Results Interchange Format) reports."""

    @staticmethod
    def generate(result: ReviewResult) -> str:
        """Generate a SARIF 2.1 report."""
        # Build rule dictionary
        rules_dict: Dict[str, Dict[str, Any]] = {}
        for issue in result.issues:
            if issue.rule_id not in rules_dict:
                rules_dict[issue.rule_id] = {
                    "id": issue.rule_id,
                    "name": issue.rule_name,
                    "shortDescription": {"text": issue.message[:100]},
                    "fullDescription": {"text": issue.message},
                    "defaultConfiguration": {"level": "error" if issue.severity in ("CRITICAL", "HIGH") else "warning"},
                    "properties": {
                        "severity": issue.severity,
                        "category": issue.category,
                    },
                }

        sarif = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [{
                "tool": {
                    "driver": {
                        "name": APP_NAME,
                        "version": VERSION,
                        "informationUri": "https://github.com/ainos/ai-code-review",
                        "rules": list(rules_dict.values()),
                    },
                },
                "results": [issue.to_sarif() for issue in result.issues],
                "properties": {
                    "files_scanned": result.files_scanned,
                    "total_lines": result.total_lines,
                    "duration_ms": result.duration_ms,
                },
            }],
        }

        return json.dumps(sarif, indent=2, default=str)


# ---------------------------------------------------------------------------
# GitHub PR integration
# ---------------------------------------------------------------------------

class GitHubPRReviewer:
    """Post review comments to GitHub PRs."""

    def __init__(self, token: str, repo: str, pr_number: int) -> None:
        self.token = token
        self.repo = repo
        self.pr_number = pr_number
        self._enabled = True

    @classmethod
    def from_env(cls) -> Optional["GitHubPRReviewer"]:
        """Create from environment variables."""
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        repo = os.environ.get("GITHUB_REPOSITORY")
        pr_str = os.environ.get("GITHUB_PR_NUMBER") or os.environ.get("PR_NUMBER")

        if not token or not repo or not pr_str:
            return None

        try:
            pr_number = int(pr_str)
        except (ValueError, TypeError):
            return None

        return cls(token, repo, pr_number)

    def post_review(self, result: ReviewResult, commit_sha: Optional[str] = None) -> bool:
        """Post review comments to the PR."""
        if not self._enabled:
            return False

        try:
            import requests
        except ImportError:
            return False

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
        }
        api_base = f"https://api.github.com/repos/{self.repo}"

        # Post a single review with all comments
        comments = []
        for issue in result.issues[:50]:  # Limit to 50 comments
            if issue.line_number > 0:
                comments.append({
                    "path": self._get_relative_path(issue.file_path),
                    "line": issue.line_number,
                    "body": f"**{issue.rule_id}** ({issue.severity}): {issue.message}\n\n"
                            f"> {issue.remediation}" if issue.remediation else issue.message,
                })

        if not comments:
            return True

        try:
            summary = (
                f"## AI Code Review Results\n\n"
                f"Found **{result.issue_count}** issues "
                f"({result.critical_count} critical, "
                f"{result.high_count} high, "
                f"{result.medium_count} medium, "
                f"{result.low_count} low).\n\n"
                f"Scanned {result.files_scanned} files in {result.duration_ms:.0f}ms."
            )

            response = requests.post(
                f"{api_base}/pulls/{self.pr_number}/reviews",
                headers=headers,
                json={
                    "body": summary,
                    "event": "COMMENT",
                    "comments": comments,
                },
                timeout=30,
            )
            return response.status_code in (200, 201)
        except Exception:
            return False

    def _get_relative_path(self, filepath: str) -> str:
        """Get the repository-relative path."""
        # Try to find the repo root from the filepath
        for root_marker in [".git", "pyproject.toml", "Cargo.toml"]:
            parts = filepath.replace("\\", "/").split("/")
            for i in range(len(parts), 0, -1):
                candidate = "/".join(parts[:i])
                if os.path.exists(os.path.join(candidate, root_marker)):
                    return "/".join(parts[i:])
        return filepath.replace("\\", "/")


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the main argument parser."""
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="AI-powered code review tool with AST-based static analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              %(prog)s review src/                      # Review a directory
              %(prog)s review main.py lib/               # Review specific files
              %(prog)s review . --format json -o report.json
              %(prog)s review . --min-severity HIGH      # Only HIGH/CRITICAL
              %(prog)s list-rules                         # List all rules
              %(prog)s check NAMING-001 file.py           # Check a specific rule
        """),
    )

    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # ------------------------------------------------------------------ #
    # review subcommand
    # ------------------------------------------------------------------ #
    review_parser = subparsers.add_parser("review", help="Run code review on files/directories")
    review_parser.add_argument("paths", nargs="+", help="Files or directories to review")
    review_parser.add_argument("--format", "-f", choices=["markdown", "json", "sarif"],
                               default="markdown", help="Output format (default: markdown)")
    review_parser.add_argument("--output", "-o", type=str, help="Output file (default: stdout)")
    review_parser.add_argument("--min-severity", choices=SEVERITY_LEVELS, default="INFO",
                               help="Minimum severity to report (default: INFO)")
    review_parser.add_argument("--recursive", "-r", action="store_true", default=True,
                               help="Recurse into directories (default: True)")
    review_parser.add_argument("--no-recursive", action="store_false", dest="recursive",
                               help="Don't recurse into directories")
    review_parser.add_argument("--no-gitignore", action="store_true",
                               help="Don't respect .gitignore patterns")
    review_parser.add_argument("--rules", nargs="*", help="Specific rule IDs to run")
    review_parser.add_argument("--severity-override", nargs="*",
                               help="Override rule severities (e.g., 'REVIEW-TODO-001=HIGH')")
    review_parser.add_argument("--github-pr", action="store_true",
                               help="Post review as GitHub PR comment")
    review_parser.add_argument("--title", type=str, default="AI Code Review Report",
                               help="Report title")

    # ------------------------------------------------------------------ #
    # list-rules subcommand
    # ------------------------------------------------------------------ #
    list_parser = subparsers.add_parser("list-rules", help="List available review rules")
    list_parser.add_argument("--language", choices=["python", "c", "rust"], help="Filter by language")
    list_parser.add_argument("--category", type=str, help="Filter by category")
    list_parser.add_argument("--severity", choices=SEVERITY_LEVELS, help="Filter by severity")
    list_parser.add_argument("--format", choices=["table", "json"], default="table",
                             help="Output format (default: table)")

    # ------------------------------------------------------------------ #
    # check subcommand
    # ------------------------------------------------------------------ #
    check_parser = subparsers.add_parser("check", help="Check a specific rule against a file")
    check_parser.add_argument("rule_id", type=str, help="Rule ID to check (e.g., 'REVIEW-DOC-001')")
    check_parser.add_argument("file", type=str, help="File to check")
    check_parser.add_argument("--format", "-f", choices=["markdown", "json", "sarif"],
                              default="markdown", help="Output format")

    return parser


def cmd_review(args: argparse.Namespace) -> int:
    """Handle the 'review' subcommand."""
    engine = ReviewEngine()

    # Rule filtering
    if args.rules:
        rules = []
        for rule_id in args.rules:
            rule = engine.get_rule_by_id(rule_id)
            if rule:
                rules.append(rule)
            else:
                print(f"Warning: Rule '{rule_id}' not found", file=sys.stderr)
    else:
        rules = None

    # Severity overrides
    if args.severity_override:
        for override in args.severity_override:
            if "=" in override:
                rule_id, sev = override.split("=", 1)
                rule = engine.get_rule_by_id(rule_id.strip())
                if rule:
                    rule.severity = sev.strip()

    # Discover files
    files, skipped = engine.discover_files(
        args.paths, recursive=args.recursive, gitignore=not args.no_gitignore
    )

    if not files:
        print("No supported source files found.", file=sys.stderr)
        return 1

    if args.verbose:
        print(f"Found {len(files)} files ({skipped} skipped)", file=sys.stderr)

    # Define progress callback
    def on_progress(current: int, total: int, filepath: str) -> None:
        if args.verbose:
            rel = os.path.relpath(filepath)
            print(f"  [{current}/{total}] {rel}", file=sys.stderr)

    # Run review
    result = engine.review(files, rules=rules, min_severity=args.min_severity,
                           progress_callback=on_progress if args.verbose else None)

    # Generate report
    if args.format == "json":
        report = JSONReport.generate(result)
    elif args.format == "sarif":
        report = SARIFReport.generate(result)
    else:
        report = MarkdownReport.generate(result, title=args.title)

    # Output
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        if args.verbose:
            print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(report)

    # GitHub PR integration
    if args.github_pr:
        reviewer = GitHubPRReviewer.from_env()
        if reviewer:
            if args.verbose:
                print("Posting review to GitHub PR...", file=sys.stderr)
            reviewer.post_review(result)
        else:
            print("Warning: GitHub PR integration requires GITHUB_TOKEN, "
                  "GITHUB_REPOSITORY, and GITHUB_PR_NUMBER environment variables",
                  file=sys.stderr)

    # Print summary to stderr
    print(f"\nReview complete: {result.issue_count} issues found "
          f"({result.critical_count} critical, {result.high_count} high, "
          f"{result.medium_count} medium, {result.low_count} low, "
          f"{result.info_count} info) in {result.files_scanned} files "
          f"({result.duration_ms:.0f}ms)",
          file=sys.stderr)

    if result.errors:
        for err in result.errors:
            print(f"  Error: {err}", file=sys.stderr)

    return 1 if result.critical_count > 0 else 0


def cmd_list_rules(args: argparse.Namespace) -> int:
    """Handle the 'list-rules' subcommand."""
    engine = ReviewEngine()
    rules = engine.get_rules(
        language=args.language,
        category=args.category,
        severity=args.severity,
    )

    if not rules:
        print("No rules match the specified filters.")
        return 0

    if args.format == "json":
        rules_data = [{
            "rule_id": r.rule_id,
            "name": r.name,
            "description": r.description,
            "severity": r.severity,
            "languages": r.languages,
            "category": getattr(r, 'category', 'general'),
        } for r in rules]
        print(json.dumps(rules_data, indent=2))
    else:
        # Table format
        print(f"{'Rule ID':<25} {'Name':<35} {'Severity':<10} {'Category':<20} {'Languages':<15}")
        print("-" * 105)
        for rule in sorted(rules, key=lambda r: r.rule_id):
            langs = ", ".join(
                getattr(rule, 'languages', ['python'])
            )
            cat = getattr(rule, 'category', 'general')
            print(f"{rule.rule_id:<25} {rule.name:<35} {rule.severity:<10} "
                  f"{cat:<20} {langs:<15}")
        print(f"\n{len(rules)} rules total")

    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Handle the 'check' subcommand."""
    engine = ReviewEngine()
    rule = engine.get_rule_by_id(args.rule_id)

    if not rule:
        print(f"Error: Rule '{args.rule_id}' not found", file=sys.stderr)
        return 1

    if not os.path.isfile(args.file):
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        return 1

    source = engine.read_file(args.file)
    if source is None:
        print(f"Error: Could not read file: {args.file}", file=sys.stderr)
        return 1

    tree = engine.parse_file(source, args.file)
    if tree is None:
        print(f"Error: Could not parse file: {args.file}", file=sys.stderr)
        return 1

    issues = rule.check(tree, args.file, source)

    result = ReviewResult(issues=issues, files_scanned=1, total_lines=len(source.splitlines()))

    if args.format == "json":
        print(JSONReport.generate(result))
    elif args.format == "sarif":
        print(SARIFReport.generate(result))
    else:
        print(MarkdownReport.generate(result, title=f"Rule Check: {rule.rule_id}"))

    if not issues:
        print(f"\nNo issues found for rule '{rule.rule_id}' in {args.file}")

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "review":
        return cmd_review(args)
    elif args.command == "list-rules":
        return cmd_list_rules(args)
    elif args.command == "check":
        return cmd_check(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())