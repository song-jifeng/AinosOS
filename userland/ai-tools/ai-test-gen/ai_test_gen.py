#!/usr/bin/env python3
"""
AinosOS AI Test Generator
===========================
AI-powered test case generator that parses function signatures from Python,
C, and Rust source files and automatically generates comprehensive test cases
in multiple output formats.

Subcommands:
    generate    Generate test cases for source files
    analyze     Analyze source code for testability
    run         Run generated tests with coverage tracking

Supports pytest, unittest, doctest, cmocka, and libtest output formats.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import re
import subprocess
import sys
import textwrap
import time
import hashlib
import inspect
from abc import ABC, abstractmethod
from collections import defaultdict, Counter
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
APP_NAME = "ai-test-gen"

SUPPORTED_EXTENSIONS = {".py", ".c", ".h", ".rs", ".cpp", ".hpp", ".cc", ".cxx", ".hh"}

OUTPUT_FORMATS = ("pytest", "unittest", "doctest", "cmocka", "libtest")

# Type mappings for test value generation
TYPE_TEST_VALUES: Dict[str, List[str]] = {
    "int": ["0", "1", "-1", "42", "-42"],
    "float": ["0.0", "1.0", "-1.0", "3.14159"],
    "str": ['""', '"hello"', '"a"', '"123"'],
    "bool": ["True", "False"],
    "bytes": ['b""', 'b"hello"'],
    "list": ["[]", "[1, 2, 3]", '["a", "b"]'],
    "dict": ["{}", '{"a": 1}'],
    "tuple": ["()", "(1,)", "(1, 2, 3)"],
    "set": ["set()", "{1, 2, 3}"],
    "None": ["None"],
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class Language(Enum):
    """Supported programming languages."""
    PYTHON = "python"
    C = "c"
    RUST = "rust"

    @classmethod
    def from_extension(cls, ext: str) -> Optional["Language"]:
        mapping = {
            ".py": cls.PYTHON,
            ".c": cls.C, ".h": cls.C,
            ".cpp": cls.C, ".hpp": cls.C, ".cc": cls.C, ".cxx": cls.C, ".hh": cls.C,
            ".rs": cls.RUST,
        }
        return mapping.get(ext.lower())


class ParameterKind(Enum):
    """Kinds of function parameters."""
    POSITIONAL_ONLY = auto()
    POSITIONAL_OR_KEYWORD = auto()
    VAR_POSITIONAL = auto()
    KEYWORD_ONLY = auto()
    VAR_KEYWORD = auto()


@dataclass
class Parameter:
    """Represents a single function parameter."""
    name: str
    type_hint: Optional[str] = None
    default_value: Optional[str] = None
    kind: ParameterKind = ParameterKind.POSITIONAL_OR_KEYWORD
    is_optional: bool = False
    description: Optional[str] = None


@dataclass
class FunctionSignature:
    """Represents a parsed function/method signature."""
    name: str
    parameters: List[Parameter] = field(default_factory=list)
    return_type: Optional[str] = None
    is_method: bool = False
    is_static: bool = False
    is_async: bool = False
    is_generator: bool = False
    decorators: List[str] = field(default_factory=list)
    docstring: Optional[str] = None
    source_file: Optional[str] = None
    line_number: int = 0
    language: Language = Language.PYTHON
    body_lines: int = 0
    attributes: Dict[str, Any] = field(default_factory=dict)

    @property
    def parameter_count(self) -> int:
        return len(self.parameters)

    @property
    def has_return(self) -> bool:
        return self.return_type is not None and self.return_type not in (
            "None", "void", "()", "!"
        )


@dataclass
class ClassInfo:
    """Represents a parsed class definition."""
    name: str
    bases: List[str] = field(default_factory=list)
    methods: List[FunctionSignature] = field(default_factory=list)
    docstring: Optional[str] = None
    source_file: Optional[str] = None
    line_number: int = 0
    language: Language = Language.PYTHON
    is_abstract: bool = False
    decorators: List[str] = field(default_factory=list)


@dataclass
class TestCase:
    """A single generated test case."""
    name: str
    body: str
    decorators: List[str] = field(default_factory=list)
    is_parametrized: bool = False
    parametrize_args: Optional[str] = None
    parametrize_values: Optional[str] = None

    def render(self, indent: int = 4, output_format: str = "pytest") -> str:
        """Render the test case as source code."""
        lines: List[str] = []
        prefix = " " * indent

        for dec in self.decorators:
            lines.append(f"{prefix}{dec}")

        if self.is_parametrized and self.parametrize_args and self.parametrize_values:
            lines.append(f'{prefix}@pytest.mark.parametrize({self.parametrize_args}, {self.parametrize_values})')

        def_prefix = "def " if output_format in ("pytest", "unittest") else ""
        lines.append(f"{prefix}{def_prefix}{self.name}:")
        for body_line in self.body.strip().split('\n'):
            lines.append(f"{prefix}    {body_line.strip()}")
        lines.append("")

        return '\n'.join(lines)


@dataclass
class TestClass:
    """A generated test class."""
    name: str
    test_cases: List[TestCase] = field(default_factory=list)
    fixtures: List[str] = field(default_factory=list)
    setup_method: Optional[str] = None
    teardown_method: Optional[str] = None

    def render(self, indent: int = 0, output_format: str = "pytest") -> str:
        """Render the test class as source code."""
        lines: List[str] = []
        prefix = " " * indent

        if output_format == "unittest":
            lines.append(f"{prefix}class {self.name}(unittest.TestCase):")
        else:
            lines.append(f"{prefix}class {self.name}:")

        if self.setup_method:
            for line in self.setup_method.strip().split('\n'):
                lines.append(f"{prefix}    {line.strip()}")
        if self.teardown_method:
            for line in self.teardown_method.strip().split('\n'):
                lines.append(f"{prefix}    {line.strip()}")

        for fixture in self.fixtures:
            for line in fixture.strip().split('\n'):
                lines.append(f"{prefix}    {line.strip()}")

        for tc in self.test_cases:
            lines.append(tc.render(4, output_format))

        lines.append("")
        return '\n'.join(lines)


@dataclass
class CoverageReport:
    """Coverage analysis report."""
    total_functions: int = 0
    covered_functions: int = 0
    branch_coverage: float = 0.0
    line_coverage: float = 0.0
    uncovered_lines: Dict[str, List[int]] = field(default_factory=dict)
    weak_areas: List[str] = field(default_factory=list)


@dataclass
class TestGenerationResult:
    """Result of test generation."""
    source_file: str
    language: Language
    test_code: str = ""
    test_count: int = 0
    assertion_count: int = 0
    mock_count: int = 0
    fixture_count: int = 0
    errors: List[str] = field(default_factory=list)
    generated_files: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Signature Analyzer (Python, C, Rust)
# ---------------------------------------------------------------------------

class SignatureAnalyzer:
    """Analyzes source code to extract function/method signatures."""

    # ------------------------------------------------------------------ #
    #  Python AST-based analysis
    # ------------------------------------------------------------------ #

    @staticmethod
    def _get_annotation_str(node: Optional[ast.AST]) -> Optional[str]:
        """Convert an AST annotation node to a string."""
        if node is None:
            return None
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            value = SignatureAnalyzer._get_annotation_str(node.value) or ""
            return f"{value}.{node.attr}"
        if isinstance(node, ast.Subscript):
            value = SignatureAnalyzer._get_annotation_str(node.value) or ""
            if isinstance(node.slice, ast.Tuple):
                slices = ", ".join(
                    SignatureAnalyzer._get_annotation_str(el) or "?"
                    for el in node.slice.elts
                )
                return f"{value}[{slices}]"
            sl = SignatureAnalyzer._get_annotation_str(node.slice) or "?"
            return f"{value}[{sl}]"
        if isinstance(node, ast.Constant):
            return repr(node.value)
        if isinstance(node, ast.Index):
            return SignatureAnalyzer._get_annotation_str(node.value)
        return None

    @staticmethod
    def _get_docstring(body: List[ast.stmt]) -> Optional[str]:
        """Extract docstring from a list of statements."""
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            val = body[0].value.value
            if isinstance(val, str):
                return val
        return None

    def analyze_python(self, source: str, filepath: Optional[str] = None) -> Tuple[List[FunctionSignature], List[ClassInfo]]:
        """Parse Python source and return function and class signatures."""
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            raise ValueError(f"Failed to parse Python source: {e}") from e

        functions: List[FunctionSignature] = []
        classes: List[ClassInfo] = []
        self._walk_python_body(tree.body, functions, classes, filepath=filepath)
        return functions, classes

    def _walk_python_body(self, body: List[ast.stmt], functions: List[FunctionSignature],
                          classes: List[ClassInfo], filepath: Optional[str] = None,
                          class_context: Optional[ClassInfo] = None) -> None:
        """Walk AST body collecting functions and classes."""
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                sig = self._parse_function(node, filepath, class_context)
                if sig is not None:
                    functions.append(sig)
                    if class_context is not None:
                        class_context.methods.append(sig)
            elif isinstance(node, ast.ClassDef):
                cls = ClassInfo(
                    name=node.name,
                    docstring=self._get_docstring(node.body),
                    line_number=node.lineno,
                    language=Language.PYTHON,
                    source_file=filepath,
                    decorators=[self._decorator_name(d) for d in node.decorator_list],
                )
                for base in node.bases:
                    b = self._get_annotation_str(base)
                    if b:
                        cls.bases.append(b)
                classes.append(cls)
                self._walk_python_body(node.body, functions, classes, filepath, cls)

    def _parse_function(self, node: ast.AST, filepath: Optional[str] = None,
                        class_context: Optional[ClassInfo] = None) -> Optional[FunctionSignature]:
        """Parse a function definition from AST."""
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return None

        sig = FunctionSignature(
            name=node.name,
            return_type=self._get_annotation_str(node.returns),
            is_async=isinstance(node, ast.AsyncFunctionDef),
            decorators=[self._decorator_name(d) for d in node.decorator_list],
            docstring=self._get_docstring(node.body),
            line_number=node.lineno,
            language=Language.PYTHON,
            source_file=filepath,
            body_lines=(node.end_lineno or node.lineno) - node.lineno,
        )

        if class_context is not None:
            sig.is_method = True
            for d in node.decorator_list:
                name = self._decorator_name(d)
                if name == "staticmethod":
                    sig.is_static = True

        # Check for generator
        for child in ast.walk(node):
            if isinstance(child, (ast.Yield, ast.YieldFrom)):
                sig.is_generator = True
                break

        # Process parameters
        args = node.args

        # Positional parameters
        defaults_start = len(args.args) - len(args.defaults)
        for i, arg in enumerate(args.args):
            param = Parameter(
                name=arg.arg,
                type_hint=self._get_annotation_str(arg.annotation),
            )
            if i >= defaults_start:
                default_idx = i - defaults_start
                if default_idx < len(args.defaults):
                    try:
                        param.default_value = ast.unparse(args.defaults[default_idx])
                    except Exception:
                        param.default_value = "..."
                    param.is_optional = True
            # Skip self/cls for methods
            if sig.is_method and i == 0 and arg.arg in ("self", "cls"):
                continue
            sig.parameters.append(param)

        # *args
        if args.vararg:
            sig.parameters.append(Parameter(
                name=args.vararg.arg,
                type_hint=self._get_annotation_str(args.vararg.annotation),
                kind=ParameterKind.VAR_POSITIONAL,
            ))

        # Keyword-only parameters
        for i, arg in enumerate(args.kwonlyargs):
            param = Parameter(
                name=arg.arg,
                type_hint=self._get_annotation_str(arg.annotation),
                kind=ParameterKind.KEYWORD_ONLY,
            )
            if i < len(args.kw_defaults) and args.kw_defaults[i] is not None:
                try:
                    param.default_value = ast.unparse(args.kw_defaults[i])
                except Exception:
                    param.default_value = "..."
                param.is_optional = True
            sig.parameters.append(param)

        # **kwargs
        if args.kwarg:
            sig.parameters.append(Parameter(
                name=args.kwarg.arg,
                type_hint=self._get_annotation_str(args.kwarg.annotation),
                kind=ParameterKind.VAR_KEYWORD,
            ))

        return sig

    def _decorator_name(self, node: ast.AST) -> str:
        """Get the name of a decorator."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self._decorator_name(node.value)}.{node.attr}"
        if isinstance(node, ast.Call):
            return self._decorator_name(node.func)
        return str(node)

    # ------------------------------------------------------------------ #
    #  C signature analysis
    # ------------------------------------------------------------------ #

    C_FUNC_PATTERN = re.compile(
        r'(?:(?:static|inline|extern|const|volatile)\s+)*'
        r'(\w+(?:\s*\*+)?\s+\w+)\s*\(([^)]*)\)\s*;',
        re.MULTILINE,
    )

    C_FUNC_DEF_PATTERN = re.compile(
        r'(?:(?:static|inline|extern|const|volatile)\s+)*'
        r'(\w+(?:\s*\*+)?\s+\w+)\s*\(([^)]*)\)\s*\{',
        re.MULTILINE,
    )

    C_PARAM_PATTERN = re.compile(
        r'(?:(?:const|volatile|register)\s+)?'
        r'(\w+(?:\s*\*+)?)\s+(\w+)'
        r'(?:\s*=\s*([^,)]+))?',
    )

    def analyze_c(self, source: str, filepath: Optional[str] = None) -> Tuple[List[FunctionSignature], List[ClassInfo]]:
        """Parse C source and return function signatures."""
        # Remove comments
        cleaned = re.sub(r'/\*[\s\S]*?\*/', '', source)
        cleaned = re.sub(r'//.*', '', cleaned)

        functions: List[FunctionSignature] = []
        structs: List[ClassInfo] = []

        # Extract structs
        struct_pattern = re.compile(
            r'(?:typedef\s+)?struct\s+(\w+)\s*\{([^}]*)\}(?:\s*(\w+))?\s*;',
            re.DOTALL,
        )
        for match in struct_pattern.finditer(cleaned):
            name = match.group(3) or match.group(1)
            structs.append(ClassInfo(
                name=name,
                line_number=source[:match.start()].count("\n") + 1,
                language=Language.C,
                source_file=filepath,
            ))

        # Extract function definitions
        for match in self.C_FUNC_DEF_PATTERN.finditer(cleaned):
            ret_and_name = match.group(1).strip()
            params_str = match.group(2).strip()
            line_no = source[:match.start()].count("\n") + 1

            # Split return type and name
            parts = ret_and_name.rsplit(None, 1)
            if len(parts) != 2:
                continue
            ret_type = parts[0]
            name = parts[1]

            if name in ("if", "while", "for", "switch", "return", "sizeof"):
                continue

            sig = FunctionSignature(
                name=name,
                return_type=ret_type,
                language=Language.C,
                source_file=filepath,
                line_number=line_no,
            )
            self._parse_c_params(params_str, sig)
            functions.append(sig)

        return functions, structs

    def _parse_c_params(self, params_str: str, sig: FunctionSignature) -> None:
        """Parse C function parameters."""
        if not params_str or params_str.strip() == "void":
            return

        parts = self._split_by_commas(params_str)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            match = self.C_PARAM_PATTERN.match(part)
            if match:
                sig.parameters.append(Parameter(
                    name=match.group(2),
                    type_hint=match.group(1).strip(),
                    default_value=match.group(3),
                    is_optional=match.group(3) is not None,
                ))
            else:
                sig.parameters.append(Parameter(
                    name=f"arg{len(sig.parameters) + 1}",
                    type_hint=part,
                ))

    # ------------------------------------------------------------------ #
    #  Rust signature analysis
    # ------------------------------------------------------------------ #

    RUST_FN_PATTERN = re.compile(
        r'(?:(?:pub\s+)?(?:async\s+)?(?:unsafe\s+)?(?:extern\s+"[^"]*"\s+)?)?'
        r'fn\s+(\w+)(?:\s*<\s*([^>]+)\s*>)?\s*\(([^)]*)\)'
        r'(?:\s*->\s*([^{;]+))?',
    )

    RUST_PARAM_PATTERN = re.compile(
        r'(?:(?:mut\s+)?(\w+)\s*:\s*([^,=)]+?))'
        r'(?:\s*=\s*([^,)]+))?',
    )

    RUST_STRUCT_PATTERN = re.compile(
        r'(?:pub\s+)?struct\s+(\w+)(?:<\s*([^>]+)\s*>)?\s*(?:\{|;|\()',
    )

    def analyze_rust(self, source: str, filepath: Optional[str] = None) -> Tuple[List[FunctionSignature], List[ClassInfo]]:
        """Parse Rust source and return function signatures."""
        cleaned = re.sub(r'///.*', '', source)
        cleaned = re.sub(r'//!.*', '', cleaned)
        cleaned = re.sub(r'/\*[\s\S]*?\*/', '', cleaned)
        cleaned = re.sub(r'//.*', '', cleaned)

        functions: List[FunctionSignature] = []
        types: List[ClassInfo] = []

        # Extract structs
        for match in self.RUST_STRUCT_PATTERN.finditer(cleaned):
            types.append(ClassInfo(
                name=match.group(1),
                line_number=source[:match.start()].count("\n") + 1,
                language=Language.RUST,
                source_file=filepath,
            ))

        # Extract enums
        enum_pattern = re.compile(r'(?:pub\s+)?enum\s+(\w+)(?:<\s*([^>]+)\s*>)?\s*\{')
        for match in enum_pattern.finditer(cleaned):
            types.append(ClassInfo(
                name=match.group(1),
                line_number=source[:match.start()].count("\n") + 1,
                language=Language.RUST,
                source_file=filepath,
            ))

        # Extract traits
        trait_pattern = re.compile(r'(?:pub\s+)?(?:unsafe\s+)?trait\s+(\w+)(?:<\s*([^>]+)\s*>)?')
        for match in trait_pattern.finditer(cleaned):
            types.append(ClassInfo(
                name=match.group(1),
                line_number=source[:match.start()].count("\n") + 1,
                language=Language.RUST,
                source_file=filepath,
                is_abstract=True,
            ))

        # Extract functions
        for match in self.RUST_FN_PATTERN.finditer(cleaned):
            name = match.group(1)
            params_str = match.group(3) or ""
            return_type = match.group(4)
            preceding = source[:match.start()]

            sig = FunctionSignature(
                name=name,
                return_type=return_type.strip() if return_type else None,
                language=Language.RUST,
                source_file=filepath,
                line_number=source[:match.start()].count("\n") + 1,
                is_async="async" in preceding[-200:],
                attributes={"unsafe": "unsafe" in preceding[-200:]},
            )
            self._parse_rust_params(params_str, sig)

            # Check if method (has self parameter)
            if sig.parameters and sig.parameters[0].name == "self":
                sig.is_method = True

            functions.append(sig)

        return functions, types

    def _parse_rust_params(self, params_str: str, sig: FunctionSignature) -> None:
        """Parse Rust function parameters."""
        if not params_str.strip():
            return

        parts = self._split_by_commas(params_str)
        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Handle self
            if part in ("self", "&self", "&mut self", "mut self"):
                sig.parameters.append(Parameter(name="self", type_hint=part))
                continue

            match = self.RUST_PARAM_PATTERN.match(part)
            if match:
                sig.parameters.append(Parameter(
                    name=match.group(1),
                    type_hint=match.group(2).strip(),
                    default_value=match.group(3),
                    is_optional=match.group(3) is not None,
                ))
            elif ":" in part:
                name, _, typ = part.partition(":")
                sig.parameters.append(Parameter(
                    name=name.strip(),
                    type_hint=typ.strip(),
                ))

    @staticmethod
    def _split_by_commas(s: str) -> List[str]:
        """Split a string by commas, respecting nested brackets/parens."""
        parts: List[str] = []
        depth = 0
        current: List[str] = []
        for ch in s:
            if ch in '<(':
                depth += 1
                current.append(ch)
            elif ch in ')>':
                depth -= 1
                current.append(ch)
            elif ch == ',' and depth == 0:
                parts.append(''.join(current))
                current = []
            else:
                current.append(ch)
        if current:
            parts.append(''.join(current))
        return parts

    # ------------------------------------------------------------------ #
    #  Combined analysis
    # ------------------------------------------------------------------ #

    def analyze_file(self, filepath: str) -> Tuple[List[FunctionSignature], List[ClassInfo]]:
        """Analyze a source file, detecting language from extension."""
        path = Path(filepath)
        source = path.read_text(encoding="utf-8", errors="replace")
        ext = path.suffix.lower()
        lang = Language.from_extension(ext)
        if lang is None:
            raise ValueError(f"Unsupported file extension: {ext}")

        if lang == Language.PYTHON:
            return self.analyze_python(source, filepath)
        elif lang == Language.C:
            return self.analyze_c(source, filepath)
        elif lang == Language.RUST:
            return self.analyze_rust(source, filepath)
        return [], []

    def analyze_directory(self, directory: str) -> Dict[str, Tuple[List[FunctionSignature], List[ClassInfo]]]:
        """Analyze all supported source files in a directory."""
        results: Dict[str, Tuple[List[FunctionSignature], List[ClassInfo]]] = {}
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    fpath = os.path.join(root, f)
                    try:
                        results[fpath] = self.analyze_file(fpath)
                    except Exception as e:
                        results[fpath] = ([], [])
        return results


# ---------------------------------------------------------------------------
# Complexity Analyzer
# ---------------------------------------------------------------------------

class ComplexityAnalyzer:
    """Analyzes code complexity metrics."""

    def compute_cyclomatic(self, source: str, language: Language = Language.PYTHON) -> int:
        """Compute McCabe's cyclomatic complexity."""
        if language == Language.PYTHON:
            return self._py_cyclomatic(source)
        elif language == Language.C:
            return self._c_cyclomatic(source)
        elif language == Language.RUST:
            return self._rust_cyclomatic(source)
        return 1

    def _py_cyclomatic(self, source: str) -> int:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return 1
        complexity = 1
        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.While, ast.For, ast.AsyncFor,
                                  ast.ExceptHandler, ast.Assert)):
                complexity += 1
            elif isinstance(node, ast.BoolOp):
                complexity += len(node.values) - 1
        return complexity

    def _c_cyclomatic(self, source: str) -> int:
        cleaned = re.sub(r'"[^"]*"', '', source)
        cleaned = re.sub(r"'[^']*'", '', cleaned)
        cleaned = re.sub(r'/\*[\s\S]*?\*/', '', cleaned)
        cleaned = re.sub(r'//.*', '', cleaned)
        complexity = 1
        patterns = [r'\bif\s*\(', r'\belse\s+if\b', r'\bwhile\s*\(', r'\bfor\s*\(',
                    r'\bcase\s+', r'\bcatch\s*\(', r'\b&&\b', r'\b\|\|\b', r'\?.*:']
        for p in patterns:
            complexity += len(re.findall(p, cleaned))
        return complexity

    def _rust_cyclomatic(self, source: str) -> int:
        cleaned = re.sub(r'"[^"]*"', '', source)
        cleaned = re.sub(r"'[^']*'", '', cleaned)
        cleaned = re.sub(r'/\*[\s\S]*?\*/', '', cleaned)
        cleaned = re.sub(r'//.*', '', cleaned)
        complexity = 1
        patterns = [r'\bif\b', r'\belse\b', r'\bwhile\b', r'\bfor\b', r'\bmatch\b',
                    r'\b&&\b', r'\b\|\|\b']
        for p in patterns:
            complexity += len(re.findall(p, cleaned))
        return complexity

    def compute_cognitive(self, source: str, language: Language = Language.PYTHON) -> int:
        """Compute cognitive complexity (SonarQube-style)."""
        if language == Language.PYTHON:
            return self._py_cognitive(source)
        return 0

    def _py_cognitive(self, source: str) -> int:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return 0
        return self._walk_cognitive(tree)

    def _walk_cognitive(self, node: ast.AST, nesting: int = 0) -> int:
        score = 0
        if isinstance(node, ast.If):
            score += 1 + nesting
            for child in node.body:
                score += self._walk_cognitive(child, nesting + 1)
            for child in node.orelse:
                if isinstance(child, ast.If):
                    score += self._walk_cognitive(child, nesting)
                else:
                    score += 1 + nesting
                    score += self._walk_cognitive(child, nesting + 1)
        elif isinstance(node, (ast.While, ast.For, ast.AsyncFor)):
            score += 1 + nesting
            for child in node.body:
                score += self._walk_cognitive(child, nesting + 1)
        elif isinstance(node, ast.ExceptHandler):
            score += 1 + nesting
            for child in node.body:
                score += self._walk_cognitive(child, nesting + 1)
        elif isinstance(node, ast.Try):
            score += 1 + nesting
            for child in node.body:
                score += self._walk_cognitive(child, nesting + 1)
        elif isinstance(node, ast.Assert):
            score += 1 + nesting
        elif isinstance(node, ast.BoolOp):
            score += len(node.values) - 1
        else:
            for child in ast.iter_child_nodes(node):
                score += self._walk_cognitive(child, nesting)
        return score

    def analyze_function(self, func: FunctionSignature, source: Optional[str] = None) -> Dict[str, Any]:
        """Compute full complexity metrics for a function."""
        metrics: Dict[str, Any] = {
            "parameter_count": func.parameter_count,
            "body_lines": func.body_lines,
            "cyclomatic_complexity": 1,
            "cognitive_complexity": 0,
            "test_priority": 0.0,
        }
        if source:
            metrics["cyclomatic_complexity"] = self.compute_cyclomatic(source, func.language)
            metrics["cognitive_complexity"] = self.compute_cognitive(source, func.language)
            # Test priority: 0-100
            cc = metrics["cyclomatic_complexity"]
            if cc <= 1:
                metrics["test_priority"] = 10
            elif cc <= 5:
                metrics["test_priority"] = 30
            elif cc <= 10:
                metrics["test_priority"] = 50
            elif cc <= 20:
                metrics["test_priority"] = 70
            else:
                metrics["test_priority"] = 90
        return metrics


# ---------------------------------------------------------------------------
# Dependency Analyzer
# ---------------------------------------------------------------------------

class DependencyAnalyzer:
    """Analyzes dependencies for mock generation."""

    STDLIB_MODULES = {
        "abc", "ast", "asyncio", "base64", "collections", "copy", "csv",
        "datetime", "decimal", "enum", "functools", "glob", "hashlib",
        "inspect", "io", "itertools", "json", "logging", "math", "os",
        "pathlib", "pickle", "random", "re", "shutil", "socket", "sqlite3",
        "string", "struct", "subprocess", "sys", "tempfile", "textwrap",
        "threading", "time", "traceback", "typing", "unittest", "urllib",
        "uuid", "warnings", "weakref", "xml", "zipfile", "zlib",
        "dataclasses", "argparse", "contextlib", "configparser",
    }

    def analyze_python(self, source: str) -> Dict[str, Any]:
        """Analyze Python source for dependencies."""
        result: Dict[str, Any] = {
            "imports": [],
            "external_packages": set(),
            "function_calls": defaultdict(list),
            "mock_candidates": [],
        }

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return result

        # Collect imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    result["imports"].append(alias.name)
                    base = alias.name.split(".")[0]
                    if base not in self.STDLIB_MODULES:
                        result["external_packages"].add(base)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    result["imports"].append(node.module)
                    base = node.module.split(".")[0]
                    if base not in self.STDLIB_MODULES and node.level == 0:
                        result["external_packages"].add(base)

        # Collect function calls
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        name = self._get_call_name(child.func)
                        if name and name not in {"range", "len", "int", "str",
                                                  "float", "list", "dict", "set",
                                                  "tuple", "print", "isinstance",
                                                  "hasattr", "getattr", "setattr",
                                                  "type", "super", "property",
                                                  "classmethod", "staticmethod",
                                                  "min", "max", "sum", "abs",
                                                  "any", "all", "sorted",
                                                  "reversed", "enumerate", "zip",
                                                  "map", "filter", "repr",
                                                  "open", "id", "hash", "ord",
                                                  "chr", "bin", "hex", "oct",
                                                  "round", "pow", "divmod",
                                                  "iter", "next", "bool"}:
                            result["function_calls"][node.name].append(name)

        # Generate mock candidates
        for pkg in sorted(result["external_packages"]):
            result["mock_candidates"].append({
                "name": pkg,
                "reason": f"External package '{pkg}' should be mocked in tests",
                "mock_type": "unittest.mock.patch" if pkg in ("os", "sys", "subprocess") else "unittest.mock.MagicMock",
                "priority": 10 if pkg in {"requests", "boto3", "redis"} else 5,
            })

        result["external_packages"] = sorted(result["external_packages"])
        return result

    def _get_call_name(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, (ast.Name, ast.Attribute)):
                inner = self._get_call_name(node.value)
                if inner:
                    return f"{inner}.{node.attr}"
            return node.attr
        return None


# ---------------------------------------------------------------------------
# Test Generators
# ---------------------------------------------------------------------------

class PythonTestGenerator:
    """Generate Python test cases (pytest, unittest, doctest)."""

    def __init__(self) -> None:
        self.complexity = ComplexityAnalyzer()
        self.dependencies = DependencyAnalyzer()

    def generate(self, source: str, functions: List[FunctionSignature],
                 classes: List[ClassInfo], output_format: str = "pytest",
                 module_name: Optional[str] = None,
                 include_property: bool = True, include_boundary: bool = True,
                 include_edge: bool = True, include_mock: bool = True) -> str:
        """Generate test cases for Python source."""
        if output_format == "doctest":
            return self._generate_doctest(functions, classes)
        elif output_format == "unittest":
            return self._generate_unittest(source, functions, classes, module_name)
        else:
            return self._generate_pytest(source, functions, classes, module_name,
                                         include_property, include_boundary,
                                         include_edge, include_mock)

    def _generate_pytest(self, source: str, functions: List[FunctionSignature],
                         classes: List[ClassInfo], module_name: Optional[str] = None,
                         include_property: bool = True, include_boundary: bool = True,
                         include_edge: bool = True, include_mock: bool = True) -> str:
        """Generate pytest-style test cases."""
        lines: List[str] = [
            f'"""Tests for {module_name or "module"}."""',
            "",
            "import sys",
            "import math",
            "import pytest",
            "from unittest.mock import MagicMock, patch, AsyncMock, PropertyMock, call",
            "from typing import Any, Dict, List, Optional",
            "",
        ]

        if module_name:
            names = []
            for func in functions:
                if not func.is_method:
                    names.append(func.name)
            for cls in classes:
                names.append(cls.name)
            if names:
                lines.append(f"from {module_name} import (")
                lines.append("    " + ",\n    ".join(names) + ",")
                lines.append(")")
                lines.append("")

        # Add fixtures from dependencies
        if module_name and include_mock:
            deps = self.dependencies.analyze_python(source)
            for cand in deps.get("mock_candidates", []):
                lines.append(f"@pytest.fixture")
                lines.append(f"def mock_{cand['name']}():")
                lines.append(f'    """Mock {cand["name"]} calls."""')
                if cand["name"] in ("requests", "urllib"):
                    lines.append("    with patch('{cand['name']}') as mock:")
                    lines.append("        mock_response = MagicMock()")
                    lines.append("        mock_response.status_code = 200")
                    lines.append("        mock_response.json.return_value = {}")
                    lines.append("        mock.get.return_value = mock_response")
                    lines.append("        yield mock")
                else:
                    lines.append("    mock = MagicMock()")
                    lines.append("    return mock")
                lines.append("")

        # Generate tests for module-level functions
        for func in functions:
            if func.is_method:
                continue
            test_cases = self._generate_func_tests(func, include_property,
                                                   include_boundary, include_edge, include_mock)
            for tc in test_cases:
                lines.append(tc.render(0, "pytest"))
                lines.append("")

        # Generate test classes
        for cls in classes:
            if not cls.methods:
                continue
            lines.append(f"class Test{cls.name}:")
            lines.append("")
            lines.append(f"    @pytest.fixture")
            lines.append(f"    def instance(self):")
            lines.append(f"        return {cls.name}()")
            lines.append("")

            for method in cls.methods:
                if method.name.startswith("__") and method.name not in ("__init__", "__str__", "__repr__"):
                    continue
                test_cases = self._generate_method_tests(method, cls.name)
                for tc in test_cases:
                    lines.append(f"    {tc.render(4, 'pytest')}")
                    lines.append("")

        return "\n".join(lines)

    def _generate_unittest(self, source: str, functions: List[FunctionSignature],
                           classes: List[ClassInfo], module_name: Optional[str] = None) -> str:
        """Generate unittest-style test cases."""
        lines: List[str] = [
            f'"""Tests for {module_name or "module"} using unittest."""',
            "",
            "import sys",
            "import math",
            "import unittest",
            "from unittest.mock import MagicMock, patch, AsyncMock, PropertyMock, call",
            "from typing import Any, Dict, List, Optional",
            "",
        ]

        if module_name:
            names = []
            for func in functions:
                if not func.is_method:
                    names.append(func.name)
            for cls in classes:
                names.append(cls.name)
            if names:
                lines.append(f"from {module_name} import (")
                lines.append("    " + ",\n    ".join(names) + ",")
                lines.append(")")
                lines.append("")

        # Module-level function tests
        mod_funcs = [f for f in functions if not f.is_method]
        if mod_funcs:
            lines.append("class TestModuleFunctions(unittest.TestCase):")
            lines.append('    """Test cases for module-level functions."""')
            lines.append("")
            for func in mod_funcs:
                test_cases = self._generate_func_tests(func, False, True, True, True)
                for tc in test_cases:
                    lines.append(f"    {tc.render(4, 'unittest')}")
            lines.append("")

        # Class tests
        for cls in classes:
            lines.append(f"class Test{cls.name}(unittest.TestCase):")
            lines.append(f'    """Test cases for {cls.name}."""')
            lines.append("")
            lines.append("    def setUp(self):")
            lines.append(f"        self.instance = {cls.name}()")
            lines.append("")

            for method in cls.methods:
                if method.name.startswith("__"):
                    continue
                test_cases = self._generate_method_tests(method, cls.name)
                for tc in test_cases:
                    lines.append(f"    {tc.render(4, 'unittest')}")

            lines.append("")

        lines.append("")
        lines.append('if __name__ == "__main__":')
        lines.append("    unittest.main()")
        return "\n".join(lines)

    def _generate_doctest(self, functions: List[FunctionSignature],
                          classes: List[ClassInfo]) -> str:
        """Generate doctest-style examples."""
        lines = ['"""',
                 "Module doctests.",
                 "",
                 "Usage:",
                 "    python -m doctest this_module.py",
                 ""]
        for func in functions:
            if func.is_method:
                continue
            if not func.parameters:
                lines.append(f">>> {func.name}()  # doctest: +SKIP")
            else:
                args = ", ".join(f"{p.name}=..." for p in func.parameters)
                lines.append(f">>> {func.name}({args})  # doctest: +SKIP")
            lines.append("...")

        for cls in classes:
            for method in cls.methods:
                if method.name.startswith("_"):
                    continue
                lines.append(f">>> {cls.name}().{method.name}()  # doctest: +SKIP")
                lines.append("...")

        lines.append('"""')
        return "\n".join(lines)

    def _generate_func_tests(self, func: FunctionSignature,
                             include_property: bool, include_boundary: bool,
                             include_edge: bool, include_mock: bool) -> List[TestCase]:
        """Generate all test cases for a single function."""
        tests: List[TestCase] = []

        # Basic test
        tests.append(self._basic_test(func))

        # Return type test
        if func.return_type and func.return_type not in ("None", "NoneType"):
            tests.append(self._return_type_test(func))

        # Edge case tests
        if include_edge:
            for param in func.parameters:
                if param.type_hint and "str" in param.type_hint:
                    tests.append(TestCase(
                        name=f"test_{func.name}_edge_empty_{param.name}",
                        body=f"# Edge case: empty string for {param.name}\n"
                             f"result = {func.name}({param.name}='')",
                    ))
                elif param.type_hint and "list" in param.type_hint:
                    tests.append(TestCase(
                        name=f"test_{func.name}_edge_empty_{param.name}",
                        body=f"# Edge case: empty list for {param.name}\n"
                             f"result = {func.name}({param.name}=[])",
                    ))
                if param.is_optional or (param.type_hint and "Optional" in param.type_hint):
                    tests.append(TestCase(
                        name=f"test_{func.name}_edge_none_{param.name}",
                        body=f"# Edge case: None for {param.name}\n"
                             f"result = {func.name}({param.name}=None)",
                    ))

        # Boundary tests
        if include_boundary:
            for param in func.parameters:
                if param.type_hint and "int" in param.type_hint:
                    tests.append(TestCase(
                        name=f"test_{func.name}_boundary_{param.name}",
                        body=f"# Boundary values for {param.name}\n"
                             f"try:\n"
                             f"    result = {func.name}({param.name}=0)\n"
                             f"except (ValueError, TypeError):\n"
                             f"    pass",
                    ))

        # Exception test
        if self._has_raises(func):
            tests.append(TestCase(
                name=f"test_{func.name}_raises",
                body=f"# Test that {func.name} raises appropriate exceptions\n"
                     f"with pytest.raises((ValueError, TypeError)):\n"
                     f"    # TODO: add invalid input\n"
                     f"    pass",
            ))

        # Mock test
        if include_mock:
            tests.append(TestCase(
                name=f"test_{func.name}_with_mocks",
                body=f"# Test {func.name} with mocked dependencies\n"
                     f"# TODO: identify external calls and mock them\n"
                     f"result = {func.name}()\n"
                     f"assert result is not None",
            ))

        return tests

    def _basic_test(self, func: FunctionSignature) -> TestCase:
        """Generate a basic unit test."""
        test_name = f"test_{func.name}_basic"
        args = self._sample_args(func)
        call = f"await {func.name}({args})" if func.is_async else f"{func.name}({args})"
        body = f"result = {call}"
        if func.return_type and func.return_type not in ("None", "NoneType", "void"):
            body += f'\nassert result is not None, f"Expected non-None return from {func.name}"'
        return TestCase(name=test_name, body=body)

    def _return_type_test(self, func: FunctionSignature) -> TestCase:
        """Generate a return type test."""
        test_name = f"test_{func.name}_return_type"
        args = self._sample_args(func)
        call = f"await {func.name}({args})" if func.is_async else f"{func.name}({args})"
        body = f"result = {call}\n"
        rt = func.return_type or ""
        if "int" in rt:
            body += 'assert isinstance(result, int), f"Expected int, got {type(result)}"'
        elif "float" in rt:
            body += 'assert isinstance(result, (int, float)), f"Expected numeric, got {type(result)}"'
        elif "str" in rt:
            body += 'assert isinstance(result, str), f"Expected str, got {type(result)}"'
        elif "bool" in rt:
            body += 'assert isinstance(result, bool), f"Expected bool, got {type(result)}"'
        elif "list" in rt or "List" in rt:
            body += 'assert isinstance(result, list), f"Expected list, got {type(result)}"'
        elif "dict" in rt or "Dict" in rt:
            body += 'assert isinstance(result, dict), f"Expected dict, got {type(result)}"'
        elif "tuple" in rt or "Tuple" in rt:
            body += 'assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"'
        else:
            body += 'assert result is not None, f"Expected non-None result"'
        return TestCase(name=test_name, body=body)

    def _generate_method_tests(self, method: FunctionSignature, class_name: str) -> List[TestCase]:
        """Generate test cases for a class method."""
        tests: List[TestCase] = []

        # Basic test
        args = self._sample_args(method)
        test_name = f"test_{method.name}_basic"
        body = f"instance = {class_name}()\nresult = instance.{method.name}({args})"
        if method.return_type and method.return_type not in ("None", "NoneType"):
            body += '\nassert result is not None'
        tests.append(TestCase(name=test_name, body=body))

        # Return type test
        if method.return_type and method.return_type not in ("None", "NoneType"):
            test_name = f"test_{method.name}_return_type"
            body = (f"instance = {class_name}()\n"
                    f"result = instance.{method.name}({args})\n"
                    f'assert result is not None, f"Expected non-None return from {class_name}.{method.name}"')
            tests.append(TestCase(name=test_name, body=body))

        return tests

    def _sample_args(self, func: FunctionSignature) -> str:
        """Generate sample argument values."""
        args: List[str] = []
        for param in func.parameters:
            if param.default_value is not None:
                args.append(param.default_value)
            else:
                args.append(self._default_for_type(param.type_hint))
        return ", ".join(args)

    def _default_for_type(self, type_hint: Optional[str]) -> str:
        """Get default test value for a type."""
        if not type_hint:
            return "None"
        type_map = {
            "int": "42", "float": "3.14", "str": "'test'", "bool": "True",
            "bytes": "b'test'", "list": "[]", "dict": "{}", "tuple": "()",
            "set": "set()", "None": "None", "Any": "None",
        }
        for key, val in type_map.items():
            if key in type_hint:
                return val
        if "Optional" in type_hint:
            return "None"
        if "Callable" in type_hint:
            return "lambda: None"
        return "None"

    def _has_raises(self, func: FunctionSignature) -> bool:
        """Check if a function likely raises exceptions."""
        return bool(func.attributes.get("raises")) or func.parameter_count > 2

    def generate_stats(self, code: str) -> Dict[str, Any]:
        """Generate statistics about generated test code."""
        return {
            "test_count": len(re.findall(r'^\s*def test_', code, re.MULTILINE)),
            "class_count": len(re.findall(r'^\s*class Test', code, re.MULTILINE)),
            "assertion_count": len(re.findall(r'\bassert\b', code)),
            "fixture_count": len(re.findall(r'@pytest\.fixture', code)),
            "mock_count": len(re.findall(r'MagicMock|mock\.patch|patch\(', code)),
            "line_count": len(code.splitlines()),
        }


class CTestGenerator:
    """Generate C test cases (cmocka format)."""

    def generate(self, functions: List[FunctionSignature], module_name: Optional[str] = None) -> str:
        """Generate cmocka-style test cases for C functions."""
        lines: List[str] = [
            "#include <stdarg.h>",
            "#include <stddef.h>",
            "#include <setjmp.h>",
            "#include <cmocka.h>",
            "#include <stdio.h>",
            "#include <stdlib.h>",
            "",
        ]

        if module_name:
            lines.append(f'#include "{module_name}.h"')
            lines.append("")

        # Forward declarations
        for func in functions:
            lines.append(f"static void test_{func.name}(void **state);")
        lines.append("")

        # Main function
        lines.append("int main(void) {")
        lines.append("    const struct CMUnitTest tests[] = {")
        for func in functions:
            lines.append(f"        cmocka_unit_test(test_{func.name}),")
        lines.append("    };")
        lines.append("    return cmocka_run_group_tests(tests, NULL, NULL);")
        lines.append("}")
        lines.append("")

        # Test implementations
        for func in functions:
            lines.append(f"static void test_{func.name}(void **state) {{")
            lines.append(f'    (void) state;  /* unused */')
            lines.append("")
            lines.append(f"    /* TODO: Implement test for {func.name} */")
            for param in func.parameters:
                if param.type_hint:
                    lines.append(f"    /* {param.type_hint} {param.name} = ...; */")
            if func.return_type and func.return_type != "void":
                lines.append(f"    /* {func.return_type} result = {func.name}(...); */")
                lines.append(f"    /* assert_true(result != NULL); */")
            else:
                lines.append(f"    /* {func.name}(...); */")
            lines.append("")
            lines.append(f"    /* Skip until implemented */")
            lines.append(f"    skip();")
            lines.append("}")
            lines.append("")

        return "\n".join(lines)


class RustTestGenerator:
    """Generate Rust test cases (libtest format)."""

    def generate(self, functions: List[FunctionSignature], classes: List[ClassInfo],
                 module_name: Optional[str] = None) -> str:
        """Generate Rust test cases."""
        lines: List[str] = [
            "// Tests generated by ai-test-gen",
            "// Source: " + (module_name or "unknown"),
            "",
        ]

        # Helper imports
        lines.append("#[cfg(test)]")
        lines.append("mod tests {")
        lines.append("    use super::*;")
        lines.append("")

        # Function tests
        for func in functions:
            if func.is_method:
                continue
            lines.append("    #[test]")
            lines.append(f"    fn test_{func.name}() {{")
            args = self._sample_args(func)
            if func.return_type and func.return_type not in ("()", "!", "never"):
                lines.append(f"        let result = {func.name}({args});")
                lines.append(f"        assert!(result == result);  // TODO: proper assertion")
            else:
                lines.append(f"        {func.name}({args});")
            lines.append("    }")
            lines.append("")

        # Method tests
        for cls in classes:
            for method in cls.methods:
                lines.append("    #[test]")
                lines.append(f"    fn test_{cls.name}_{method.name}() {{")
                args = self._sample_args(method)
                lines.append(f"        let instance = {cls.name}::new();  // TODO: adjust constructor")
                if method.return_type and method.return_type not in ("()", "!"):
                    lines.append(f"        let result = instance.{method.name}({args});")
                    lines.append(f"        assert!(true);  // TODO: proper assertion")
                else:
                    lines.append(f"        instance.{method.name}({args});")
                lines.append("    }")
                lines.append("")

        # Property-based test stub
        lines.append("    #[test]")
        lines.append("    fn test_property_based() {")
        lines.append("        // TODO: Add property-based tests using proptest")
        lines.append("        // use proptest::prelude::*;")
        lines.append("        // proptest! {")
        lines.append("        //     #[test]")
        lines.append("        //     fn test_property(/* param in 0..100u32 */) {")
        lines.append("        //         // assert!(property holds for all inputs)")
        lines.append("        //     }")
        lines.append("        // }")
        lines.append("    }")
        lines.append("")

        lines.append("}")
        return "\n".join(lines)

    def _sample_args(self, func: FunctionSignature) -> str:
        """Generate sample Rust argument values."""
        args: List[str] = []
        for param in func.parameters:
            if param.name == "self":
                continue
            if param.default_value is not None:
                args.append(param.default_value)
            elif param.type_hint:
                type_map = {
                    "i32": "0", "i64": "0", "u32": "0", "u64": "0",
                    "f32": "0.0", "f64": "0.0", "bool": "true",
                    "String": r'"test".to_string()', "str": '"test"',
                    "usize": "0", "isize": "0",
                }
                found = False
                for key, val in type_map.items():
                    if key in (param.type_hint or ""):
                        args.append(val)
                        found = True
                        break
                if not found:
                    args.append("/* TODO */")
            else:
                args.append("()")
        return ", ".join(args)


# ---------------------------------------------------------------------------
# Coverage Analysis
# ---------------------------------------------------------------------------

class CoverageAnalyzer:
    """Analyze test coverage gaps."""

    def analyze(self, source: str, language: Language = Language.PYTHON) -> CoverageReport:
        """Analyze source for coverage gaps based on complexity."""
        report = CoverageReport()

        if language == Language.PYTHON:
            try:
                tree = ast.parse(source)
            except SyntaxError:
                return report

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    report.total_functions += 1
                    # Check if function has branching
                    has_branches = any(
                        isinstance(child, (ast.If, ast.Try, ast.For, ast.While))
                        for child in ast.walk(node)
                    )
                    if has_branches:
                        report.weak_areas.append(
                            f"{node.name}: contains branches (lines {node.lineno}-{node.end_lineno})"
                        )

        return report


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the main argument parser."""
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="AI-powered test case generator for Python, C, and Rust",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              %(prog)s generate module.py                      # Generate pytest tests
              %(prog)s generate src/ -o tests/                  # Output to directory
              %(prog)s generate lib.rs -f libtest               # Rust tests
              %(prog)s analyze module.py                        # Analyze testability
              %(prog)s run test_file.py                         # Run tests with coverage
        """),
    )

    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # ------------------------------------------------------------------ #
    # generate subcommand
    # ------------------------------------------------------------------ #
    gen_parser = subparsers.add_parser("generate", help="Generate test cases")
    gen_parser.add_argument("source", type=str, help="Source file or directory")
    gen_parser.add_argument("--output", "-o", type=str, default="",
                            help="Output file or directory (default: stdout)")
    gen_parser.add_argument("--format", "-f", choices=OUTPUT_FORMATS, default="pytest",
                            help="Output format (default: pytest)")
    gen_parser.add_argument("--module-name", "-m", type=str, default="",
                            help="Module name for imports")
    gen_parser.add_argument("--recursive", "-r", action="store_true", default=True,
                            help="Recurse into directories")
    gen_parser.add_argument("--no-property", action="store_false", dest="property",
                            help="Skip property-based tests")
    gen_parser.add_argument("--no-boundary", action="store_false", dest="boundary",
                            help="Skip boundary value tests")
    gen_parser.add_argument("--no-edge", action="store_false", dest="edge",
                            help="Skip edge case tests")
    gen_parser.add_argument("--no-mock", action="store_false", dest="mock",
                            help="Skip mock-based tests")
    gen_parser.add_argument("--coverage", action="store_true",
                            help="Generate coverage-aware tests (requires coverage data)")

    # ------------------------------------------------------------------ #
    # analyze subcommand
    # ------------------------------------------------------------------ #
    analyze_parser = subparsers.add_parser("analyze", help="Analyze source code for testability")
    analyze_parser.add_argument("source", type=str, help="Source file or directory")
    analyze_parser.add_argument("--format", "-f", choices=["text", "json"], default="text",
                                help="Output format (default: text)")
    analyze_parser.add_argument("--recursive", "-r", action="store_true", default=True)

    # ------------------------------------------------------------------ #
    # run subcommand
    # ------------------------------------------------------------------ #
    run_parser = subparsers.add_parser("run", help="Run tests with coverage tracking")
    run_parser.add_argument("test_path", type=str, help="Test file or directory")
    run_parser.add_argument("--source", "-s", type=str, default=".",
                            help="Source path for coverage measurement")
    run_parser.add_argument("--coverage-report", "-c", type=str, default="",
                            help="Generate coverage report to file")
    run_parser.add_argument("--pytest-args", type=str, default="",
                            help="Additional pytest arguments")

    return parser


def cmd_generate(args: argparse.Namespace) -> int:
    """Handle the 'generate' subcommand."""
    source_path = args.source
    analyzer = SignatureAnalyzer()

    if os.path.isfile(source_path):
        source = Path(source_path).read_text(encoding="utf-8", errors="replace")
        ext = os.path.splitext(source_path)[1].lower()
        lang = Language.from_extension(ext)

        if lang is None:
            print(f"Error: Unsupported file type: {source_path}", file=sys.stderr)
            return 1

        if lang == Language.PYTHON:
            functions, classes = analyzer.analyze_python(source, source_path)
            module_name = args.module_name or os.path.splitext(os.path.basename(source_path))[0]
            gen = PythonTestGenerator()
            test_code = gen.generate(
                source, functions, classes, args.format, module_name,
                args.property, args.boundary, args.edge, args.mock,
            )
        elif lang == Language.C:
            functions, classes = analyzer.analyze_c(source, source_path)
            gen = CTestGenerator()
            test_code = gen.generate(functions, args.module_name)
        elif lang == Language.RUST:
            functions, classes = analyzer.analyze_rust(source, source_path)
            gen = RustTestGenerator()
            test_code = gen.generate(functions, classes, args.module_name)
        else:
            print(f"Error: Unsupported language", file=sys.stderr)
            return 1

        # Output
        result = TestGenerationResult(
            source_file=source_path,
            language=lang,
            test_code=test_code,
            test_count=len(re.findall(r'^\s*(?:def|fn)\s+test_', test_code, re.MULTILINE)),
            assertion_count=len(re.findall(r'\bassert\b', test_code)),
        )

        if args.output:
            output_path = args.output
            if os.path.isdir(output_path):
                ext_out = {"pytest": ".py", "unittest": ".py", "doctest": ".py",
                           "libtest": ".rs", "cmocka": ".c"}
                out_name = f"test_{Path(source_path).stem}{ext_out.get(args.format, '.py')}"
                output_path = os.path.join(output_path, out_name)

            Path(output_path).write_text(test_code, encoding="utf-8")
            result.generated_files.append(output_path)
            if args.verbose:
                print(f"Generated {output_path}", file=sys.stderr)
        else:
            print(test_code)

        if args.verbose:
            print(f"\nSummary: {result.test_count} test cases, "
                  f"{result.assertion_count} assertions",
                  file=sys.stderr)

        return 0

    elif os.path.isdir(source_path):
        # Directory mode
        results = analyzer.analyze_directory(source_path)
        if not results:
            print(f"No supported source files found in {source_path}", file=sys.stderr)
            return 1

        total_tests = 0
        for fpath, (funcs, classes) in results.items():
            if not funcs and not classes:
                continue
            source = Path(fpath).read_text(encoding="utf-8", errors="replace")
            ext = os.path.splitext(fpath)[1].lower()
            lang = Language.from_extension(ext)

            if lang == Language.PYTHON:
                gen = PythonTestGenerator()
                mod_name = args.module_name or os.path.splitext(os.path.basename(fpath))[0]
                test_code = gen.generate(
                    source, funcs, classes, args.format, mod_name,
                    args.property, args.boundary, args.edge, args.mock,
                )
            elif lang == Language.C:
                gen = CTestGenerator()
                test_code = gen.generate(funcs, args.module_name)
            elif lang == Language.RUST:
                gen = RustTestGenerator()
                test_code = gen.generate(funcs, classes, args.module_name)
            else:
                continue

            if args.output:
                output_dir = args.output if os.path.isdir(args.output) else "."
                ext_out = {"pytest": ".py", "unittest": ".py", "doctest": ".py",
                           "libtest": ".rs", "cmocka": ".c"}
                out_name = f"test_{Path(fpath).stem}{ext_out.get(args.format, '.py')}"
                out_path = os.path.join(output_dir, out_name)
                Path(out_path).write_text(test_code, encoding="utf-8")
                if args.verbose:
                    print(f"Generated {out_path}", file=sys.stderr)

            test_count = len(re.findall(r'^\s*(?:def|fn)\s+test_', test_code, re.MULTILINE))
            total_tests += test_code

        if args.verbose:
            print(f"Generated tests for {len(results)} files", file=sys.stderr)

        return 0

    else:
        print(f"Error: Path not found: {source_path}", file=sys.stderr)
        return 1


def cmd_analyze(args: argparse.Namespace) -> int:
    """Handle the 'analyze' subcommand."""
    source_path = args.source
    analyzer = SignatureAnalyzer()

    if os.path.isfile(source_path):
        source = Path(source_path).read_text(encoding="utf-8", errors="replace")
        ext = os.path.splitext(source_path)[1].lower()
        lang = Language.from_extension(ext)

        if lang is None:
            print(f"Unsupported file type: {source_path}")
            return 1

        if lang == Language.PYTHON:
            functions, classes = analyzer.analyze_python(source, source_path)
        elif lang == Language.C:
            functions, classes = analyzer.analyze_c(source, source_path)
        elif lang == Language.RUST:
            functions, classes = analyzer.analyze_rust(source, source_path)
        else:
            functions, classes = [], []

        complexity = ComplexityAnalyzer()
        deps = DependencyAnalyzer()

        report = {
            "file": source_path,
            "language": lang.value,
            "functions": len(functions),
            "classes": len(classes),
            "function_details": [],
            "dependencies": deps.analyze_python(source) if lang == Language.PYTHON else {},
            "coverage_gaps": [],
        }

        for func in functions:
            func_source = source.splitlines()
            func_metrics = complexity.analyze_function(func, source)
            report["function_details"].append({
                "name": func.name,
                "parameters": func.parameter_count,
                "body_lines": func.body_lines,
                "return_type": func.return_type,
                "is_method": func.is_method,
                "is_async": func.is_async,
                "cyclomatic_complexity": func_metrics["cyclomatic_complexity"],
                "cognitive_complexity": func_metrics["cognitive_complexity"],
                "test_priority": func_metrics["test_priority"],
            })

        if args.format == "json":
            print(json.dumps(report, indent=2, default=str))
        else:
            print(f"File: {source_path}")
            print(f"Language: {lang.value}")
            print(f"Functions: {len(functions)}")
            print(f"Classes: {len(classes)}")
            print("")
            print("Functions:")
            for fd in report["function_details"]:
                priority = fd["test_priority"]
                priority_label = "HIGH" if priority >= 70 else "MEDIUM" if priority >= 40 else "LOW"
                print(f"  {fd['name']}: {fd['parameters']} params, "
                      f"CC={fd['cyclomatic_complexity']}, "
                      f"priority={priority_label}")
            print("")
            if report["dependencies"].get("external_packages"):
                print("External dependencies:")
                for pkg in report["dependencies"]["external_packages"]:
                    print(f"  - {pkg}")

        return 0

    elif os.path.isdir(source_path):
        results = analyzer.analyze_directory(source_path)
        if args.format == "json":
            report = {}
            for fpath, (funcs, classes) in results.items():
                report[fpath] = {"functions": len(funcs), "classes": len(classes)}
            print(json.dumps(report, indent=2, default=str))
        else:
            print(f"Analysis of {source_path}:")
            print("")
            for fpath, (funcs, classes) in sorted(results.items()):
                rel = os.path.relpath(fpath, source_path)
                print(f"  {rel}: {len(funcs)} functions, {len(classes)} classes")
        return 0

    else:
        print(f"Error: Path not found: {source_path}", file=sys.stderr)
        return 1


def cmd_run(args: argparse.Namespace) -> int:
    """Handle the 'run' subcommand."""
    test_path = args.test_path

    if not os.path.exists(test_path):
        print(f"Error: Test path not found: {test_path}", file=sys.stderr)
        return 1

    # Build pytest command
    cmd = ["python", "-m", "pytest", test_path]

    if args.source:
        cmd.extend(["--cov=" + args.source, "--cov-branch"])

    if args.pytest_args:
        cmd.extend(args.pytest_args.split())

    if args.verbose:
        cmd.append("-v")

    if args.coverage_report:
        cmd.extend(["--cov-report=html:" + args.coverage_report])

    print(f"Running: {' '.join(cmd)}", file=sys.stderr)

    try:
        result = subprocess.run(cmd, capture_output=not args.verbose, text=True)
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            return result.returncode
        if not args.verbose:
            print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
    except FileNotFoundError:
        print("Error: pytest not found. Install with: pip install pytest pytest-cov",
              file=sys.stderr)
        return 1

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "generate":
        return cmd_generate(args)
    elif args.command == "analyze":
        return cmd_analyze(args)
    elif args.command == "run":
        return cmd_run(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())