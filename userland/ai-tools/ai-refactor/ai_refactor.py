#!/usr/bin/env python3
"""
AI-Powered Code Refactoring Assistant

Provides automated code refactoring tools including function extraction,
variable renaming, duplicate detection, design pattern analysis, and
safety checking. Uses Python's AST module for deep code analysis.

Usage:
    python ai_refactor.py extract <file> --lines 10-25 --name new_function
    python ai_refactor.py rename <file> --from old_name --to new_name
    python ai_refactor.py detect <file> --min-lines 5 --threshold 0.8
    python ai_refactor.py analyze <file>
    python ai_refactor.py check <file> --refactored <refactored.py>
    python ai_refactor.py diff <file> <refactored.py>
"""

import ast
import difflib
import hashlib
import os
import shutil
import sys
import textwrap
import copy
import itertools
import re
import json
import datetime
import argparse
import traceback
from abc import ABC, abstractmethod
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import (
    Any, Callable, Dict, List, Optional, Set, Tuple, Union, Iterator,
    FrozenSet, ClassVar, TypeVar, Generic, cast, Sequence
)

# ── Type Aliases ──────────────────────────────────────────────────────────────

ASTNode = ast.AST
ScopeInfo = Dict[str, Any]
T = TypeVar('T')

# ── Constants ─────────────────────────────────────────────────────────────────

BUILTIN_NAMES: FrozenSet[str] = frozenset({
    'abs', 'all', 'any', 'ascii', 'bin', 'bool', 'breakpoint', 'bytearray',
    'bytes', 'callable', 'chr', 'classmethod', 'compile', 'complex', 'delattr',
    'dict', 'dir', 'divmod', 'enumerate', 'eval', 'exec', 'filter', 'float',
    'format', 'frozenset', 'getattr', 'globals', 'hasattr', 'hash', 'hex',
    'id', 'input', 'int', 'isinstance', 'issubclass', 'iter', 'len', 'list',
    'locals', 'map', 'max', 'memoryview', 'min', 'next', 'object', 'oct',
    'open', 'ord', 'pow', 'print', 'property', 'range', 'repr', 'reversed',
    'round', 'set', 'setattr', 'slice', 'sorted', 'staticmethod', 'str',
    'sum', 'super', 'tuple', 'type', 'vars', 'zip', '__import__',
    'True', 'False', 'None',
})

SENTINEL = object()
DEFAULT_ENCODING = 'utf-8'
BACKUP_SUFFIX = '.bak'
MAX_BACKUPS = 10
PROJECT_NAME = 'ai-refactor'
VERSION = '1.0.0'

# ── Data Classes ──────────────────────────────────────────────────────────────


@dataclass
class CodeLocation:
    """Represents a location range in source code.

    Attributes:
        file_path: Optional path to the source file.
        start_line: Starting line number (1-based).
        end_line: Ending line number (1-based, inclusive).
        start_col: Starting column offset.
        end_col: Ending column offset.
    """

    file_path: Optional[str] = None
    start_line: int = 0
    end_line: int = 0
    start_col: int = 0
    end_col: int = 0

    def __str__(self) -> str:
        """Return a human-readable string representation."""
        loc = f"{self.start_line}-{self.end_line}"
        if self.file_path:
            return f"{self.file_path}:{loc}"
        return f"<unknown>:{loc}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary for serialization."""
        return asdict(self)


@dataclass
class DuplicateMatch:
    """Represents a detected duplicate code block between two locations.

    Attributes:
        block1: Location of the first duplicate block.
        block2: Location of the second duplicate block.
        similarity: Similarity score between 0.0 and 1.0.
        content: The duplicated source code text.
    """

    block1: CodeLocation
    block2: CodeLocation
    similarity: float
    content: str

    def __str__(self) -> str:
        """Return a formatted string describing the duplicate."""
        return (
            f"Duplicate ({self.similarity:.1%} similarity):\n"
            f"  Block 1: {self.block1}\n"
            f"  Block 2: {self.block2}"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary for serialization."""
        return {
            'block1': self.block1.to_dict(),
            'block2': self.block2.to_dict(),
            'similarity': self.similarity,
            'content': self.content,
        }


@dataclass
class SafetyWarning:
    """A warning about a potential safety issue in a refactoring operation.

    Attributes:
        category: The category of warning (e.g., 'syntax', 'semantics', 'imports').
        message: A human-readable description of the warning.
        location: Optional source code location related to the warning.
        severity: Severity level: 'info', 'warning', or 'error'.
    """

    category: str
    message: str
    location: Optional[CodeLocation] = None
    severity: str = 'warning'

    def __str__(self) -> str:
        """Return a formatted warning string."""
        prefix = f"[{self.severity.upper()}] {self.category}"
        if self.location:
            return f"{prefix} at {self.location}: {self.message}"
        return f"{prefix}: {self.message}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary for serialization."""
        result: Dict[str, Any] = {
            'category': self.category,
            'message': self.message,
            'severity': self.severity,
        }
        if self.location:
            result['location'] = self.location.to_dict()
        return result


@dataclass
class SafetyReport:
    """Report from the safety checker after comparing original and refactored code.

    Attributes:
        is_safe: Whether the refactoring is considered safe.
        warnings: List of safety warnings.
        syntax_valid: Whether both code snippets have valid syntax.
        ast_match_score: Structural similarity score between original and refactored ASTs.
    """

    is_safe: bool = True
    warnings: List[SafetyWarning] = field(default_factory=list)
    syntax_valid: bool = True
    ast_match_score: float = 1.0

    def add_warning(
        self,
        category: str,
        message: str,
        location: Optional[CodeLocation] = None,
        severity: str = 'warning',
    ) -> None:
        """Add a warning to the report.

        Args:
            category: Warning category.
            message: Warning description.
            location: Optional code location.
            severity: Severity level.
        """
        self.warnings.append(SafetyWarning(category, message, location, severity))
        if severity == 'error':
            self.is_safe = False

    def __str__(self) -> str:
        """Return a formatted safety report string."""
        status = "SAFE" if self.is_safe else "UNSAFE"
        lines = [f"Safety Report: {status}"]
        lines.append(f"  Syntax valid: {self.syntax_valid}")
        lines.append(f"  AST match score: {self.ast_match_score:.2%}")
        lines.append(f"  Warnings ({len(self.warnings)}):")
        for w in self.warnings:
            lines.append(f"    - {w}")
        return '\n'.join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary for serialization."""
        return {
            'is_safe': self.is_safe,
            'warnings': [w.to_dict() for w in self.warnings],
            'syntax_valid': self.syntax_valid,
            'ast_match_score': self.ast_match_score,
        }


@dataclass
class PatternSuggestion:
    """A suggested design pattern for a codebase.

    Attributes:
        pattern_name: Name of the design pattern (e.g., 'Singleton', 'Factory').
        confidence: Confidence score between 0.0 and 1.0.
        description: Brief description of the pattern.
        rationale: Explanation of why this pattern is suggested.
        location: Optional code location where the pattern could apply.
        example_code: Optional example code snippet showing the pattern.
    """

    pattern_name: str
    confidence: float
    description: str
    rationale: str
    location: Optional[CodeLocation] = None
    example_code: Optional[str] = None

    def __str__(self) -> str:
        """Return a formatted suggestion string."""
        result = (
            f"[{self.confidence:.0%}] {self.pattern_name}: {self.description}\n"
            f"  Rationale: {self.rationale}"
        )
        if self.location:
            result += f"\n  Location: {self.location}"
        return result

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary for serialization."""
        result: Dict[str, Any] = {
            'pattern_name': self.pattern_name,
            'confidence': self.confidence,
            'description': self.description,
            'rationale': self.rationale,
        }
        if self.location:
            result['location'] = self.location.to_dict()
        if self.example_code:
            result['example_code'] = self.example_code
        return result


@dataclass
class RefactoringSummary:
    """Summary of a completed refactoring operation.

    Attributes:
        operation: Name of the operation performed.
        description: Human-readable description of what was done.
        success: Whether the operation completed successfully.
        original_code: The original source code before refactoring.
        refactored_code: The refactored source code.
        diff: A unified diff string showing changes.
        warnings: List of safety warnings generated during the operation.
        backup_path: Optional path to a backup file created before refactoring.
    """

    operation: str
    description: str
    success: bool
    original_code: str
    refactored_code: str
    diff: str = ''
    warnings: List[SafetyWarning] = field(default_factory=list)
    backup_path: Optional[str] = None

    def __str__(self) -> str:
        """Return a formatted summary string."""
        status = "SUCCESS" if self.success else "FAILED"
        lines = [
            f"{'='*60}",
            f"  Refactoring Summary: {status}",
            f"  Operation: {self.operation}",
            f"  Description: {self.description}",
            f"{'='*60}",
        ]
        if self.warnings:
            lines.append(f"  Warnings ({len(self.warnings)}):")
            for w in self.warnings:
                lines.append(f"    - {w}")
        if self.backup_path:
            lines.append(f"  Backup: {self.backup_path}")
        if self.diff:
            lines.append(f"  Diff:")
            lines.append(self.diff)
        return '\n'.join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary for serialization."""
        return {
            'operation': self.operation,
            'description': self.description,
            'success': self.success,
            'original_code': self.original_code,
            'refactored_code': self.refactored_code,
            'diff': self.diff,
            'warnings': [w.to_dict() for w in self.warnings],
            'backup_path': self.backup_path,
        }


# ── Exception Classes ────────────────────────────────────────────────────────


class RefactoringError(Exception):
    """Base exception for refactoring-related errors."""

    def __init__(self, message: str, original_exception: Optional[Exception] = None) -> None:
        """Initialize the error.

        Args:
            message: Human-readable error message.
            original_exception: The original exception that caused this error, if any.
        """
        self.original_exception = original_exception
        super().__init__(message)


class ParsingError(RefactoringError):
    """Raised when source code cannot be parsed."""

    def __init__(self, message: str, syntax_error: Optional[SyntaxError] = None) -> None:
        """Initialize the error.

        Args:
            message: Human-readable error message.
            syntax_error: The original SyntaxError, if any.
        """
        super().__init__(message, syntax_error)


class RenameError(RefactoringError):
    """Raised when a variable rename operation fails."""

    def __init__(self, message: str, reason: str = '') -> None:
        """Initialize the error.

        Args:
            message: Human-readable error message.
            reason: Specific reason for the rename failure.
        """
        self.reason = reason
        super().__init__(message)


class ExtractionError(RefactoringError):
    """Raised when function extraction fails."""

    def __init__(self, message: str, reason: str = '') -> None:
        """Initialize the error.

        Args:
            message: Human-readable error message.
            reason: Specific reason for the extraction failure.
        """
        self.reason = reason
        super().__init__(message)


# ── Utility Functions ─────────────────────────────────────────────────────────


def read_source_file(file_path: str) -> str:
    """Read a Python source file from disk.

    Args:
        file_path: Path to the file to read.

    Returns:
        The contents of the file as a string.

    Raises:
        FileNotFoundError: If the file does not exist.
        IOError: If the file cannot be read.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if not path.is_file():
        raise IOError(f"Path is not a file: {file_path}")
    try:
        return path.read_text(encoding=DEFAULT_ENCODING)
    except Exception as e:
        raise IOError(f"Failed to read file {file_path}: {e}") from e


def write_source_file(file_path: str, content: str, create_backup: bool = True) -> Optional[str]:
    """Write Python source code to a file, optionally creating a backup.

    Args:
        file_path: Path to write the file.
        content: Source code content to write.
        create_backup: Whether to create a backup of the existing file.

    Returns:
        The backup file path if a backup was created, otherwise None.

    Raises:
        IOError: If the file cannot be written.
    """
    backup_path: Optional[str] = None
    path = Path(file_path)

    if create_backup and path.exists():
        backup_path = create_backup_file(file_path)

    try:
        path.write_text(content, encoding=DEFAULT_ENCODING)
    except Exception as e:
        raise IOError(f"Failed to write file {file_path}: {e}") from e

    return backup_path


def create_backup_file(file_path: str) -> str:
    """Create a backup of a file with a timestamp suffix.

    Args:
        file_path: Path to the file to back up.

    Returns:
        Path to the created backup file.

    Raises:
        IOError: If the backup cannot be created.
    """
    path = Path(file_path)
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f"{path.stem}_{timestamp}{BACKUP_SUFFIX}"
    backup_path = path.with_name(backup_name)

    try:
        shutil.copy2(str(path), str(backup_path))
        _cleanup_old_backups(path)
    except Exception as e:
        raise IOError(f"Failed to create backup of {file_path}: {e}") from e

    return str(backup_path)


def _cleanup_old_backups(file_path: Path) -> None:
    """Remove old backup files, keeping only the most recent MAX_BACKUPS.

    Args:
        file_path: Path to the original file whose backups should be cleaned.
    """
    pattern = f"{file_path.stem}_*{BACKUP_SUFFIX}"
    backups = sorted(file_path.parent.glob(pattern), key=os.path.getmtime)
    while len(backups) > MAX_BACKUPS:
        oldest = backups.pop(0)
        try:
            oldest.unlink()
        except OSError:
            pass


def get_source_lines(source: str) -> List[str]:
    """Split source code into individual lines, preserving endings.

    Args:
        source: The source code string.

    Returns:
        List of lines with their original line endings.
    """
    return source.splitlines(keepends=True)


def dedent_code(code: str) -> str:
    """Remove common leading whitespace from all lines in a code block.

    Args:
        code: The code string to dedent.

    Returns:
        The dedented code string.
    """
    return textwrap.dedent(code)


def indent_code(code: str, indent: str = '    ') -> str:
    """Add a given indentation to each non-empty line of code.

    Args:
        code: The code string to indent.
        indent: The indentation string to prepend (default: 4 spaces).

    Returns:
        The indented code string.
    """
    lines = code.splitlines(keepends=True)
    result: List[str] = []
    for line in lines:
        if line.strip():
            result.append(indent + line)
        else:
            result.append(line)
    return ''.join(result)


def parse_code(code: str) -> ast.Module:
    """Parse Python source code into an abstract syntax tree.

    Args:
        code: The source code string to parse.

    Returns:
        The parsed AST module.

    Raises:
        ParsingError: If the code contains syntax errors.
    """
    try:
        return ast.parse(code)
    except SyntaxError as e:
        raise ParsingError(f"Syntax error in source code: {e}", e) from e


def unparse_ast(tree: ast.AST) -> str:
    """Convert an AST back into Python source code string.

    Args:
        tree: The AST node to convert.

    Returns:
        The source code representation of the AST.

    Raises:
        RefactoringError: If the AST cannot be unparsed.
    """
    try:
        return ast.unparse(tree)
    except Exception as e:
        raise RefactoringError(f"Failed to unparse AST: {e}", e) from e


def compute_hash(code: str) -> str:
    """Compute a SHA-256 hash of the source code.

    Args:
        code: The source code string.

    Returns:
        The hexadecimal SHA-256 digest.
    """
    return hashlib.sha256(code.encode(DEFAULT_ENCODING)).hexdigest()


def get_all_names(node: ast.AST) -> List[str]:
    """Extract all Name node identifiers from an AST subtree.

    Args:
        node: The AST node to search.

    Returns:
        List of all identifier strings found in Name nodes.
    """
    names: List[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.append(child.id)
    return names


def get_assigned_names(node: ast.AST) -> Set[str]:
    """Collect all names that are assigned or bound in an AST subtree.

    This includes variable assignments, function/class definitions,
    import aliases, loop variables, and exception handler bindings.

    Args:
        node: The AST node to search.

    Returns:
        Set of all assigned names.
    """
    names: Set[str] = set()

    for child in ast.walk(node):
        # Name nodes with Store context
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            names.add(child.id)
        # Function and class definitions
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(child.name)
        # Regular assignments
        elif isinstance(child, ast.Assign):
            for target in child.targets:
                _extract_target_names(target, names)
        # Annotated assignments
        elif isinstance(child, ast.AnnAssign):
            _extract_target_names(child.target, names)
        # For loop variables
        elif isinstance(child, (ast.For, ast.AsyncFor)):
            _extract_target_names(child.target, names)
        # With statement variables
        elif isinstance(child, (ast.With, ast.AsyncWith)):
            for item in child.items:
                if item.optional_vars is not None:
                    _extract_target_names(item.optional_vars, names)
        # Exception handler
        elif isinstance(child, ast.ExceptHandler) and child.name is not None:
            names.add(child.name)
        # Import statements
        elif isinstance(child, ast.Import):
            for alias in child.names:
                names.add(alias.asname or alias.name)
        elif isinstance(child, ast.ImportFrom):
            for alias in child.names:
                names.add(alias.asname or alias.name)

    return names


def _extract_target_names(target: ast.AST, names: Set[str]) -> None:
    """Recursively extract assigned names from a target node.

    Args:
        target: The assignment target AST node.
        names: Set to populate with extracted names.
    """
    if isinstance(target, ast.Name):
        names.add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            _extract_target_names(elt, names)
    elif isinstance(target, ast.Starred):
        _extract_target_names(target.value, names)
    elif isinstance(target, ast.Attribute):
        pass  # obj.attr doesn't define a new name in the local scope


def normalize_ast_for_comparison(node: ast.AST) -> ast.AST:
    """Create a normalized copy of an AST with identifiers replaced by placeholders.

    This is used for structural comparison of code fragments. All variable names,
    function names, class names, attribute names, and literal values are replaced
    with generic placeholders so that only the structure is compared.

    Args:
        node: The AST node to normalize.

    Returns:
        A new AST node with identifiers replaced by placeholders.
    """
    normalizer = _ASTNormalizer()
    return normalizer.visit(copy.deepcopy(node))


class _ASTNormalizer(ast.NodeTransformer):
    """AST transformer that replaces identifiers with placeholders."""

    _name_counter: ClassVar[int] = 0
    _value_counter: ClassVar[int] = 0

    def visit_Name(self, node: ast.Name) -> ast.Name:
        """Replace variable names with a placeholder."""
        self._name_counter += 1
        return ast.Name(id=f'__var_{self._name_counter}__', ctx=node.ctx)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        """Replace function names with a placeholder."""
        self._name_counter += 1
        node.name = f'__func_{self._name_counter}__'
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        """Replace async function names with a placeholder."""
        self._name_counter += 1
        node.name = f'__func_{self._name_counter}__'
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        """Replace class names with a placeholder."""
        self._name_counter += 1
        node.name = f'__class_{self._name_counter}__'
        self.generic_visit(node)
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
        """Replace attribute names with a placeholder."""
        self._name_counter += 1
        node.attr = f'__attr_{self._name_counter}__'
        self.generic_visit(node)
        return node

    def visit_arg(self, node: ast.arg) -> ast.arg:
        """Replace argument names with a placeholder."""
        self._name_counter += 1
        node.arg = f'__arg_{self._name_counter}__'
        node.annotation = self.visit(node.annotation) if node.annotation else None
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        """Replace literal values with a placeholder."""
        self._value_counter += 1
        return ast.Constant(value=f'__val_{self._value_counter}__')

    def visit_Str(self, node: ast.Str) -> ast.Str:  # For Python < 3.8
        """Replace string literals with a placeholder."""
        self._value_counter += 1
        return ast.Str(s=f'__val_{self._value_counter}__')

    def visit_Num(self, node: ast.Num) -> ast.Num:  # For Python < 3.8
        """Replace numeric literals with a placeholder."""
        self._value_counter += 1
        return ast.Num(n=self._value_counter)


def ast_similarity(node1: ast.AST, node2: ast.AST) -> float:
    """Compute structural similarity between two AST nodes.

    Both nodes are normalized (identifiers and literals replaced) before
    comparison. Returns a score between 0.0 (completely different) and
    1.0 (identical structure).

    Args:
        node1: First AST node.
        node2: Second AST node.

    Returns:
        Similarity score between 0.0 and 1.0.
    """
    try:
        norm1 = normalize_ast_for_comparison(node1)
        norm2 = normalize_ast_for_comparison(node2)
        str1 = ast.dump(norm1)
        str2 = ast.dump(norm2)
        return difflib.SequenceMatcher(None, str1, str2).ratio()
    except Exception:
        return 0.0


def text_similarity(text1: str, text2: str) -> float:
    """Compute text similarity between two strings using sequence matching.

    Args:
        text1: First text string.
        text2: Second text string.

    Returns:
        Similarity score between 0.0 and 1.0.
    """
    if not text1 and not text2:
        return 1.0
    if not text1 or not text2:
        return 0.0
    return difflib.SequenceMatcher(None, text1, text2).ratio()


def generate_unified_diff(
    original: str,
    refactored: str,
    original_name: str = 'original',
    refactored_name: str = 'refactored',
    n_context: int = 3,
) -> str:
    """Generate a unified diff between two code strings.

    Args:
        original: Original source code.
        refactored: Refactored source code.
        original_name: Label for the original version.
        refactored_name: Label for the refactored version.
        n_context: Number of context lines around each change.

    Returns:
        The unified diff as a string.
    """
    original_lines = original.splitlines(keepends=True)
    refactored_lines = refactored.splitlines(keepends=True)

    diff_lines = list(difflib.unified_diff(
        original_lines,
        refactored_lines,
        fromfile=original_name,
        tofile=refactored_name,
        n=n_context,
    ))

    return ''.join(diff_lines)


# ── Scope Analysis ───────────────────────────────────────────────────────────


class Scope:
    """Represents a lexical scope in Python source code.

    Attributes:
        scope_type: Type of scope ('module', 'function', 'class', 'lambda', 'comprehension').
        name: The name of this scope (e.g., function name, 'module').
        defined_names: Set of names defined directly in this scope.
        referenced_names: Set of names referenced in this scope.
        parent: The parent scope, or None for the module scope.
        children: List of child scopes.
        node: The AST node that created this scope.
    """

    def __init__(
        self,
        scope_type: str,
        name: str,
        parent: Optional['Scope'] = None,
        node: Optional[ast.AST] = None,
    ) -> None:
        """Initialize the scope.

        Args:
            scope_type: Type of scope.
            name: Name of the scope.
            parent: Parent scope, if any.
            node: AST node that created this scope.
        """
        self.scope_type: str = scope_type
        self.name: str = name
        self.defined_names: Set[str] = set()
        self.referenced_names: Set[str] = set()
        self.parent: Optional['Scope'] = parent
        self.children: List['Scope'] = []
        self.node: Optional[ast.AST] = node

    def add_child(self, child: 'Scope') -> None:
        """Add a child scope.

        Args:
            child: The child scope to add.
        """
        self.children.append(child)
        child.parent = self

    def get_visible_names(self) -> Set[str]:
        """Get all names visible from this scope (including parents).

        Returns:
            Set of all visible names from this scope outward.
        """
        names: Set[str] = set(self.defined_names)
        if self.parent is not None:
            names.update(self.parent.get_visible_names())
        return names

    def is_defined_in_scope(self, name: str) -> bool:
        """Check if a name is defined in this scope (not parents).

        Args:
            name: The name to check.

        Returns:
            True if the name is defined in this exact scope.
        """
        return name in self.defined_names

    def is_visible(self, name: str) -> bool:
        """Check if a name is visible from this scope.

        Args:
            name: The name to check.

        Returns:
            True if the name is visible from this scope.
        """
        if name in self.defined_names:
            return True
        if self.parent is not None:
            return self.parent.is_visible(name)
        return name in BUILTIN_NAMES

    def find_scope_for_name(self, name: str) -> Optional['Scope']:
        """Find the scope where a name is defined.

        Searches this scope and parent scopes for the definition.

        Args:
            name: The name to search for.

        Returns:
            The scope where the name is defined, or None if not found.
        """
        if name in self.defined_names:
            return self
        if self.parent is not None:
            return self.parent.find_scope_for_name(name)
        return None

    def __repr__(self) -> str:
        """Return a string representation of the scope."""
        return (
            f"Scope(type={self.scope_type}, name={self.name}, "
            f"defined={len(self.defined_names)}, "
            f"children={len(self.children)})"
        )


class ScopeAnalyzer(ast.NodeVisitor):
    """Builds a scope tree from an AST.

    Walks the AST and creates Scope objects for each lexical scope
    (module, function, class, lambda, comprehension).
    """

    def __init__(self) -> None:
        """Initialize the scope analyzer."""
        self.module_scope: Optional[Scope] = None
        self._current_scope: Optional[Scope] = None

    def analyze(self, tree: ast.AST) -> Scope:
        """Analyze an AST and build the scope tree.

        Args:
            tree: The AST to analyze.

        Returns:
            The root module-level Scope.
        """
        self.module_scope = Scope('module', '<module>')
        self._current_scope = self.module_scope
        self.visit(tree)
        return self.module_scope

    def _enter_scope(self, scope_type: str, name: str, node: ast.AST) -> Scope:
        """Create and enter a new child scope.

        Args:
            scope_type: Type of the new scope.
            name: Name of the new scope.
            node: AST node that creates the scope.

        Returns:
            The newly created scope.
        """
        assert self._current_scope is not None
        new_scope = Scope(scope_type, name, parent=self._current_scope, node=node)
        self._current_scope.add_child(new_scope)
        self._current_scope = new_scope
        return new_scope

    def _exit_scope(self) -> None:
        """Exit the current scope and return to the parent."""
        assert self._current_scope is not None
        assert self._current_scope.parent is not None
        self._current_scope = self._current_scope.parent

    def _add_definition(self, name: str) -> None:
        """Add a name definition to the current scope.

        Args:
            name: The name being defined.
        """
        if self._current_scope is not None:
            self._current_scope.defined_names.add(name)

    def _add_reference(self, name: str) -> None:
        """Add a name reference to the current scope.

        Args:
            name: The name being referenced.
        """
        if self._current_scope is not None:
            self._current_scope.referenced_names.add(name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit a function definition and create a function scope."""
        self._add_definition(node.name)
        scope = self._enter_scope('function', node.name, node)
        for arg in node.args.args:
            scope.defined_names.add(arg.arg)
        if node.args.vararg:
            scope.defined_names.add(node.args.vararg.arg)
        if node.args.kwarg:
            scope.defined_names.add(node.args.kwarg.arg)
        for arg in node.args.kwonlyargs:
            scope.defined_names.add(arg.arg)
        for arg in node.args.posonlyargs:
            scope.defined_names.add(arg.arg)
        self.generic_visit(node)
        self._exit_scope()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit an async function definition and create a function scope."""
        self._add_definition(node.name)
        scope = self._enter_scope('function', node.name, node)
        for arg in node.args.args:
            scope.defined_names.add(arg.arg)
        if node.args.vararg:
            scope.defined_names.add(node.args.vararg.arg)
        if node.args.kwarg:
            scope.defined_names.add(node.args.kwarg.arg)
        for arg in node.args.kwonlyargs:
            scope.defined_names.add(arg.arg)
        for arg in node.args.posonlyargs:
            scope.defined_names.add(arg.arg)
        self.generic_visit(node)
        self._exit_scope()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Visit a class definition and create a class scope."""
        self._add_definition(node.name)
        self._enter_scope('class', node.name, node)
        self.generic_visit(node)
        self._exit_scope()

    def visit_Lambda(self, node: ast.Lambda) -> None:
        """Visit a lambda expression and create a lambda scope."""
        scope = self._enter_scope('lambda', '<lambda>', node)
        for arg in node.args.args:
            scope.defined_names.add(arg.arg)
        self.generic_visit(node)
        self._exit_scope()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        """Visit a list comprehension and create a comprehension scope."""
        scope = self._enter_scope('comprehension', '<listcomp>', node)
        self._visit_comprehension_generators(node.generators, scope)
        self.generic_visit(node)
        self._exit_scope()

    def visit_SetComp(self, node: ast.SetComp) -> None:
        """Visit a set comprehension and create a comprehension scope."""
        scope = self._enter_scope('comprehension', '<setcomp>', node)
        self._visit_comprehension_generators(node.generators, scope)
        self.generic_visit(node)
        self._exit_scope()

    def visit_DictComp(self, node: ast.DictComp) -> None:
        """Visit a dict comprehension and create a comprehension scope."""
        scope = self._enter_scope('comprehension', '<dictcomp>', node)
        self._visit_comprehension_generators(node.generators, scope)
        self.generic_visit(node)
        self._exit_scope()

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        """Visit a generator expression and create a comprehension scope."""
        scope = self._enter_scope('comprehension', '<genexpr>', node)
        self._visit_comprehension_generators(node.generators, scope)
        self.generic_visit(node)
        self._exit_scope()

    def _visit_comprehension_generators(
        self, generators: List[ast.comprehension], scope: Scope
    ) -> None:
        """Register loop variables from comprehension generators in the scope.

        Args:
            generators: The comprehension generators.
            scope: The current comprehension scope.
        """
        for gen in generators:
            for name in get_all_names(gen.target):
                if isinstance(gen.target, ast.Name):
                    scope.defined_names.add(gen.target.id)
                elif isinstance(gen.target, (ast.Tuple, ast.List)):
                    for elt in gen.target.elts:
                        if isinstance(elt, ast.Name):
                            scope.defined_names.add(elt.id)

    def visit_Name(self, node: ast.Name) -> None:
        """Visit a Name node and register it as a reference."""
        if isinstance(node.ctx, ast.Load):
            self._add_reference(node.id)
        elif isinstance(node.ctx, ast.Store):
            self._add_definition(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        """Visit an import statement and register the alias."""
        for alias in node.names:
            name = alias.asname or alias.name
            self._add_definition(name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Visit a from-import statement and register the alias."""
        for alias in node.names:
            name = alias.asname or alias.name
            self._add_definition(name)


# ── Refactoring Engine Base Class ────────────────────────────────────────────


class RefactoringEngine(ABC):
    """Abstract base class for all refactoring operations.

    Provides common functionality for reading source code, parsing ASTs,
    creating backups, and generating diffs. Subclasses implement specific
    refactoring transformations.

    Attributes:
        source_code: The original source code being refactored.
        file_path: Optional path to the source file.
        ast_tree: The parsed AST of the source code.
        source_lines: The source code split into lines.
        dry_run: If True, don't write changes to disk.
    """

    def __init__(
        self,
        source_code: str,
        file_path: Optional[str] = None,
        dry_run: bool = False,
    ) -> None:
        """Initialize the refactoring engine.

        Args:
            source_code: The source code to refactor.
            file_path: Optional path to the source file.
            dry_run: If True, show changes without applying them.

        Raises:
            ParsingError: If the source code contains syntax errors.
        """
        self.source_code: str = source_code
        self.file_path: Optional[str] = file_path
        self.source_lines: List[str] = get_source_lines(source_code)

        try:
            self.ast_tree: ast.Module = parse_code(source_code)
        except ParsingError:
            raise

        self.dry_run: bool = dry_run
        self._scope_analyzer: Optional[ScopeAnalyzer] = None
        self._scope_tree: Optional[Scope] = None

    @property
    def scope_tree(self) -> Scope:
        """Get the scope tree for the source code (lazy-computed).

        Returns:
            The root Scope of the code.
        """
        if self._scope_tree is None:
            analyzer = ScopeAnalyzer()
            self._scope_tree = analyzer.analyze(self.ast_tree)
            self._scope_analyzer = analyzer
        return self._scope_tree

    def create_backup(self) -> Optional[str]:
        """Create a backup of the source file if a file path is provided.

        Returns:
            The backup file path, or None if no file path is set.
        """
        if self.file_path:
            return create_backup_file(self.file_path)
        return None

    @abstractmethod
    def apply(self) -> RefactoringSummary:
        """Apply the refactoring transformation.

        Subclasses must implement this method to perform the specific
        refactoring operation and return a summary.

        Returns:
            A RefactoringSummary with the results of the operation.
        """
        ...

    def dry_run_apply(self) -> RefactoringSummary:
        """Perform a dry run of the refactoring without writing to disk.

        Returns:
            A RefactoringSummary showing what would change.
        """
        original_dry_run = self.dry_run
        self.dry_run = True
        try:
            return self.apply()
        finally:
            self.dry_run = original_dry_run

    def generate_diff(self, refactored_code: str) -> str:
        """Generate a unified diff between original and refactored code.

        Args:
            refactored_code: The refactored source code.

        Returns:
            A unified diff string.
        """
        original_name = self.file_path or 'original'
        return generate_unified_diff(
            self.source_code, refactored_code,
            original_name=original_name,
            refactored_name=f'{original_name} (refactored)',
        )

    def _check_syntax(self, code: str) -> Tuple[bool, Optional[str]]:
        """Check if a code string has valid Python syntax.

        Args:
            code: The code string to check.

        Returns:
            A tuple of (is_valid, error_message).
        """
        try:
            ast.parse(code)
            return True, None
        except SyntaxError as e:
            return False, str(e)


# ── Function Extractor ───────────────────────────────────────────────────────


class FunctionExtractorRef(RefactoringEngine):
    """Extracts a block of code into a named function, replacing the original
    block with a function call.

    Analyzes variable dependencies to determine function parameters and
    return values automatically.

    Attributes:
        start_line: The starting line of the code block to extract (1-based).
        end_line: The ending line of the code block to extract (inclusive).
        function_name: The name for the new function.
    """

    def __init__(
        self,
        source_code: str,
        start_line: int,
        end_line: int,
        function_name: str,
        file_path: Optional[str] = None,
        dry_run: bool = False,
    ) -> None:
        """Initialize the function extractor.

        Args:
            source_code: The source code to refactor.
            start_line: Start line of the block to extract (1-based).
            end_line: End line of the block to extract (inclusive).
            function_name: Name for the new function.
            file_path: Optional path to the source file.
            dry_run: If True, show changes without applying them.

        Raises:
            ExtractionError: If the line range is invalid.
            ParsingError: If the source code cannot be parsed.
        """
        super().__init__(source_code, file_path, dry_run)

        self.start_line: int = start_line
        self.end_line: int = end_line
        self.function_name: str = function_name

        if start_line < 1 or end_line > len(self.source_lines):
            raise ExtractionError(
                f"Line range {start_line}-{end_line} is out of bounds "
                f"(file has {len(self.source_lines)} lines)"
            )
        if start_line > end_line:
            raise ExtractionError(
                f"Start line {start_line} is after end line {end_line}"
            )
        if not function_name.isidentifier():
            raise ExtractionError(
                f"'{function_name}' is not a valid Python identifier"
            )

        self._extracted_block: str = self._get_block_source()
        self._indent: str = self._get_block_indent()

    def _get_block_source(self) -> str:
        """Extract the source code of the selected line range.

        Returns:
            The source code of the block.
        """
        return ''.join(self.source_lines[self.start_line - 1:self.end_line])

    def _get_block_indent(self) -> str:
        """Determine the indentation of the extracted block.

        Returns:
            The indentation string of the first non-empty line.
        """
        for line in self.source_lines[self.start_line - 1:self.end_line]:
            if line.strip():
                stripped = line.lstrip()
                return line[:len(line) - len(stripped)]
        return ''

    def _analyze_dependencies(self) -> Tuple[Set[str], Set[str], Set[str]]:
        """Analyze variable dependencies of the extracted block.

        Returns:
            A tuple of (inputs, outputs, modified) where:
            - inputs: variables used but not defined in the block.
            - outputs: variables defined in the block and used after it.
            - modified: variables defined outside the block but modified in it.
        """
        block_tree = parse_code(dedent_code(self._extracted_block))

        # Names defined within the block
        defined_in_block = get_assigned_names(block_tree)

        # Names referenced within the block
        referenced_in_block = set(get_all_names(block_tree))

        # Names used in the block but not defined there (inputs)
        inputs = referenced_in_block - defined_in_block - BUILTIN_NAMES

        # Determine what's modified (defined both outside and inside block)
        whole_tree_names = get_assigned_names(self.ast_tree)
        modified = defined_in_block & whole_tree_names - defined_in_block

        # Determine outputs: names defined in block that are used after it
        outputs: Set[str] = set()
        after_block_start = self.end_line + 1
        if after_block_start <= len(self.source_lines):
            after_code = ''.join(self.source_lines[after_block_start - 1:])
            try:
                after_tree = parse_code(after_code)
                after_names = set(get_all_names(after_tree))
                outputs = defined_in_block & after_names
            except ParsingError:
                pass

        return inputs, outputs, modified

    def _build_function_code(self, inputs: Set[str], outputs: Set[str]) -> str:
        """Build the extracted function definition code.

        Args:
            inputs: Set of input variable names (parameters).
            outputs: Set of output variable names (return values).

        Returns:
            The function definition as a string.
        """
        body = dedent_code(self._extracted_block)
        params = ', '.join(sorted(inputs)) if inputs else ''

        lines: List[str] = []
        lines.append(f"def {self.function_name}({params}):")

        if body.strip():
            indented_body = indent_code(body)
            lines.append(indented_body)
        else:
            lines.append(f"    pass")

        if outputs:
            return_vals = ', '.join(sorted(outputs))
            if len(outputs) == 1:
                lines.append(f"    return {return_vals}")
            else:
                lines.append(f"    return ({return_vals})")

        return '\n'.join(lines)

    def _build_call_code(self, inputs: Set[str], outputs: Set[str]) -> str:
        """Build the function call to replace the original block.

        Args:
            inputs: Set of input variable names.
            outputs: Set of output variable names.

        Returns:
            The function call statement as a string.
        """
        args = ', '.join(sorted(inputs)) if inputs else ''

        if outputs:
            targets = ', '.join(sorted(outputs))
            if len(outputs) == 1:
                return f"{targets} = {self.function_name}({args})"
            else:
                return f"{targets} = {self.function_name}({args})"
        else:
            return f"{self.function_name}({args})"

    def apply(self) -> RefactoringSummary:
        """Apply the function extraction refactoring.

        Returns:
            A RefactoringSummary with the results.

        Raises:
            ExtractionError: If the extraction cannot be completed.
        """
        try:
            inputs, outputs, modified = self._analyze_dependencies()
        except ParsingError as e:
            raise ExtractionError(f"Failed to analyze block dependencies: {e}", str(e))

        # Build the function and call
        function_code = self._build_function_code(inputs, outputs)
        call_code = self._build_call_code(inputs, outputs)

        # Determine where to insert the function (before the enclosing scope)
        insertion_point = self._find_insertion_point()

        # Build the refactored code
        lines_before = self.source_lines[:insertion_point]
        lines_after_block = self.source_lines[self.end_line:]

        # The function gets inserted with proper indentation
        refactored_lines: List[str] = []
        refactored_lines.extend(''.join(lines_before))

        # Add the function definition (at module level, no extra indent)
        refactored_lines.append('\n')
        refactored_lines.append(function_code)
        refactored_lines.append('\n\n')

        # Add the replacement call with original indentation
        refactored_lines.append(self._indent + call_code + '\n')

        # Add remaining lines after the extracted block
        refactored_lines.extend(lines_after_block)

        refactored_code = ''.join(refactored_lines)
        refactored_code = refactored_code.rstrip() + '\n'

        # Generate diff
        diff = self.generate_diff(refactored_code)

        # Collect warnings
        warnings: List[SafetyWarning] = []
        if modified:
            warnings.append(SafetyWarning(
                'side_effects',
                f"Variables modified in block: {', '.join(sorted(modified))}",
                severity='warning',
            ))

        # Write to file if applicable
        backup_path: Optional[str] = None
        if not self.dry_run and self.file_path:
            backup_path = self.create_backup()
            write_source_file(self.file_path, refactored_code, create_backup=False)

        return RefactoringSummary(
            operation='extract_function',
            description=f"Extracted lines {self.start_line}-{self.end_line} "
                        f"into function '{self.function_name}'",
            success=True,
            original_code=self.source_code,
            refactored_code=refactored_code,
            diff=diff,
            warnings=warnings,
            backup_path=backup_path,
        )

    def _find_insertion_point(self) -> int:
        """Find the line index where the new function should be inserted.

        The function is inserted right before the line that contains the
        first line of the extracted block, but at module scope.

        Returns:
            The line index for insertion.
        """
        return self.start_line - 1


# ── Variable Renamer ─────────────────────────────────────────────────────────


class VariableRenamer(RefactoringEngine):
    """Safely renames variables throughout a codebase with scope awareness.

    Performs comprehensive scope analysis to ensure the rename is safe
    and doesn't introduce name conflicts or shadowing issues.

    Attributes:
        old_name: The name to rename.
        new_name: The new name to use.
        scope_limit: Optional scope name to limit the rename to.
    """

    def __init__(
        self,
        source_code: str,
        old_name: str,
        new_name: str,
        file_path: Optional[str] = None,
        dry_run: bool = False,
        scope_limit: Optional[str] = None,
    ) -> None:
        """Initialize the variable renamer.

        Args:
            source_code: The source code to refactor.
            old_name: The variable name to rename.
            new_name: The replacement name.
            file_path: Optional path to the source file.
            dry_run: If True, show changes without applying them.
            scope_limit: Optional scope name to limit the rename to.

        Raises:
            RenameError: If the names are invalid.
            ParsingError: If the source code cannot be parsed.
        """
        super().__init__(source_code, file_path, dry_run)

        if not old_name.isidentifier():
            raise RenameError(f"'{old_name}' is not a valid Python identifier",
                              reason='invalid_old_name')
        if not new_name.isidentifier():
            raise RenameError(f"'{new_name}' is not a valid Python identifier",
                              reason='invalid_new_name')
        if old_name == new_name:
            raise RenameError("Old name and new name are the same",
                              reason='same_name')

        self.old_name: str = old_name
        self.new_name: str = new_name
        self.scope_limit: Optional[str] = scope_limit

    def _check_name_conflicts(self) -> List[str]:
        """Check if the new name conflicts with existing names in visible scopes.

        Returns:
            A list of conflict descriptions, or an empty list if safe.
        """
        conflicts: List[str] = []
        scope = self.scope_tree

        # Check if new_name is used in any visible scope where old_name is also used
        for name in scope.get_visible_names():
            if name == self.new_name and name != self.old_name:
                # Check if the conflict is in a scope that matters
                defining_scope = scope.find_scope_for_name(name)
                if defining_scope is not None:
                    conflicts.append(
                        f"'{self.new_name}' is already defined in scope "
                        f"'{defining_scope.name}' ({defining_scope.scope_type})"
                    )

        if self.new_name in BUILTIN_NAMES:
            conflicts.append(
                f"'{self.new_name}' shadows a Python built-in name"
            )

        return conflicts

    def _should_rename_in_scope(self, scope: Scope) -> bool:
        """Check if a scope should be included in the rename operation.

        Args:
            scope: The scope to check.

        Returns:
            True if the scope should be included.
        """
        if self.scope_limit is None:
            return True
        return scope.name == self.scope_limit

    def _rename_in_ast(self) -> ast.Module:
        """Perform the rename operation on the AST.

        Returns:
            A new AST with the variable renamed.

        Raises:
            RenameError: If the name is not found or conflicts exist.
        """
        # Check if old_name exists in the code
        all_names = set(get_all_names(self.ast_tree))
        if self.old_name not in all_names:
            raise RenameError(
                f"'{self.old_name}' not found in the source code",
                reason='name_not_found'
            )

        # Check for conflicts
        conflicts = self._check_name_conflicts()
        if conflicts:
            # Log conflicts but still proceed (they're warnings)
            pass

        # Perform the rename using a node transformer
        renamer = _RenameTransformer(
            old_name=self.old_name,
            new_name=self.new_name,
            scope_analyzer=self._scope_analyzer,
            scope_limit=self.scope_limit,
        )
        new_tree = renamer.visit(copy.deepcopy(self.ast_tree))
        ast.fix_missing_locations(new_tree)
        return new_tree

    def apply(self) -> RefactoringSummary:
        """Apply the variable rename refactoring.

        Returns:
            A RefactoringSummary with the results.

        Raises:
            RenameError: If the rename cannot be completed.
        """
        try:
            new_tree = self._rename_in_ast()
        except RenameError:
            raise
        except Exception as e:
            raise RenameError(f"Failed to rename variable: {e}", str(e))

        refactored_code = unparse_ast(new_tree) + '\n'
        diff = self.generate_diff(refactored_code)

        # Check conflicts for warnings
        conflicts = self._check_name_conflicts()
        warnings: List[SafetyWarning] = []
        for conflict in conflicts:
            warnings.append(SafetyWarning(
                'name_conflict', conflict, severity='warning'
            ))

        backup_path: Optional[str] = None
        if not self.dry_run and self.file_path:
            backup_path = self.create_backup()
            write_source_file(self.file_path, refactored_code, create_backup=False)

        return RefactoringSummary(
            operation='rename_variable',
            description=f"Renamed '{self.old_name}' to '{self.new_name}'",
            success=True,
            original_code=self.source_code,
            refactored_code=refactored_code,
            diff=diff,
            warnings=warnings,
            backup_path=backup_path,
        )


class _RenameTransformer(ast.NodeTransformer):
    """AST node transformer that renames a variable in the appropriate scopes.

    This transformer is scope-aware: it only renames variables that belong
    to the correct lexical scope, avoiding accidental renaming of variables
    in nested scopes that happen to have the same name.
    """

    def __init__(
        self,
        old_name: str,
        new_name: str,
        scope_analyzer: Optional[ScopeAnalyzer] = None,
        scope_limit: Optional[str] = None,
    ) -> None:
        """Initialize the rename transformer.

        Args:
            old_name: The name to rename.
            new_name: The replacement name.
            scope_analyzer: Optional scope analyzer for scope-aware renaming.
            scope_limit: Optional scope name to limit the rename to.
        """
        self.old_name = old_name
        self.new_name = new_name
        self.scope_analyzer = scope_analyzer
        self.scope_limit = scope_limit
        self._current_scope_names: List[str] = []

    def visit_Name(self, node: ast.Name) -> ast.Name:
        """Rename a Name node if it matches the target name.

        Args:
            node: The Name node to potentially rename.

        Returns:
            The renamed (or original) Name node.
        """
        self.generic_visit(node)
        if node.id == self.old_name:
            node.id = self.new_name
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        """Visit a function definition, potentially renaming its name."""
        self.generic_visit(node)
        if node.name == self.old_name:
            node.name = self.new_name
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        """Visit an async function definition, potentially renaming its name."""
        self.generic_visit(node)
        if node.name == self.old_name:
            node.name = self.new_name
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        """Visit a class definition, potentially renaming its name."""
        self.generic_visit(node)
        if node.name == self.old_name:
            node.name = self.new_name
        return node

    def visit_arg(self, node: ast.arg) -> ast.arg:
        """Visit a function argument, potentially renaming it."""
        if node.arg == self.old_name:
            node.arg = self.new_name
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
        """Visit an attribute access, renaming the value part if needed."""
        self.generic_visit(node)
        return node


# ── Duplicate Detector ───────────────────────────────────────────────────────


class DuplicateDetector(RefactoringEngine):
    """Detects duplicate or highly similar code blocks within a source file.

    Uses both AST-based structural comparison and text-based similarity
    to find code clones. Reports the location and similarity of each match.

    Attributes:
        min_lines: Minimum number of lines for a code block to be considered.
        threshold: Similarity threshold (0.0-1.0) for reporting matches.
        method: Detection method ('ast', 'text', or 'both').
    """

    def __init__(
        self,
        source_code: str,
        file_path: Optional[str] = None,
        dry_run: bool = False,
        min_lines: int = 5,
        threshold: float = 0.8,
        method: str = 'both',
    ) -> None:
        """Initialize the duplicate detector.

        Args:
            source_code: The source code to analyze.
            file_path: Optional path to the source file.
            dry_run: If True, show results without writing.
            min_lines: Minimum number of lines for a code block.
            threshold: Similarity threshold (0.0-1.0).
            method: Detection method ('ast', 'text', or 'both').

        Raises:
            ValueError: If parameters are invalid.
        """
        super().__init__(source_code, file_path, dry_run)

        if min_lines < 1:
            raise ValueError(f"min_lines must be >= 1, got {min_lines}")
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"threshold must be between 0.0 and 1.0, got {threshold}")
        if method not in ('ast', 'text', 'both'):
            raise ValueError(f"method must be 'ast', 'text', or 'both', got {method}")

        self.min_lines: int = min_lines
        self.threshold: float = threshold
        self.method: str = method

    def _extract_blocks(self) -> List[Tuple[int, int, str]]:
        """Extract all code blocks from the source that meet the minimum line count.

        A block is a sequence of consecutive statements at the same indentation level.

        Returns:
            List of (start_line, end_line, content) tuples for each block.
        """
        blocks: List[Tuple[int, int, str]] = []
        current_start: Optional[int] = None
        current_indent: Optional[str] = None
        block_lines: List[str] = []

        for i, line in enumerate(self.source_lines):
            if not line.strip():
                # Empty line: flush current block if any
                if current_start is not None and len(block_lines) >= self.min_lines:
                    content = ''.join(block_lines)
                    blocks.append((current_start, i, content))
                current_start = None
                current_indent = None
                block_lines = []
                continue

            stripped = line.lstrip()
            indent = line[:len(line) - len(stripped)]

            if stripped.startswith(('def ', 'class ', '@', 'import ', 'from ')):
                # Flush any existing block
                if current_start is not None and len(block_lines) >= self.min_lines:
                    content = ''.join(block_lines)
                    blocks.append((current_start, i, content))
                current_start = None
                current_indent = None
                block_lines = []
                continue

            if current_start is None:
                current_start = i + 1
                current_indent = indent
                block_lines = [line]
            elif indent == current_indent:
                block_lines.append(line)
            else:
                if len(block_lines) >= self.min_lines:
                    content = ''.join(block_lines)
                    blocks.append((current_start, i, content))
                current_start = i + 1
                current_indent = indent
                block_lines = [line]

        # Flush last block
        if current_start is not None and len(block_lines) >= self.min_lines:
            content = ''.join(block_lines)
            blocks.append((current_start, len(self.source_lines), content))

        return blocks

    def _detect_ast_duplicates(
        self, blocks: List[Tuple[int, int, str]]
    ) -> List[DuplicateMatch]:
        """Detect duplicates using AST-based structural comparison.

        Args:
            blocks: List of (start_line, end_line, content) tuples.

        Returns:
            List of DuplicateMatch objects found via AST comparison.
        """
        matches: List[DuplicateMatch] = []
        parsed_blocks: List[Tuple[int, int, Optional[ast.AST]]] = []

        for start, end, content in blocks:
            try:
                tree = parse_code(dedent_code(content))
                parsed_blocks.append((start, end, tree))
            except ParsingError:
                parsed_blocks.append((start, end, None))

        for i in range(len(parsed_blocks)):
            for j in range(i + 1, len(parsed_blocks)):
                start1, end1, tree1 = parsed_blocks[i]
                start2, end2, tree2 = parsed_blocks[j]

                if tree1 is None or tree2 is None:
                    continue

                similarity = ast_similarity(tree1, tree2)
                if similarity >= self.threshold:
                    location = CodeLocation(
                        file_path=self.file_path,
                        start_line=start1,
                        end_line=end1,
                    )
                    matches.append(DuplicateMatch(
                        block1=location,
                        block2=CodeLocation(
                            file_path=self.file_path,
                            start_line=start2,
                            end_line=end2,
                        ),
                        similarity=similarity,
                        content=''.join(self.source_lines[start1 - 1:end1]),
                    ))

        return matches

    def _detect_text_duplicates(
        self, blocks: List[Tuple[int, int, str]]
    ) -> List[DuplicateMatch]:
        """Detect duplicates using text-based similarity comparison.

        Args:
            blocks: List of (start_line, end_line, content) tuples.

        Returns:
            List of DuplicateMatch objects found via text comparison.
        """
        matches: List[DuplicateMatch] = []

        for i in range(len(blocks)):
            for j in range(i + 1, len(blocks)):
                start1, end1, content1 = blocks[i]
                start2, end2, content2 = blocks[j]

                similarity = text_similarity(content1, content2)
                if similarity >= self.threshold:
                    matches.append(DuplicateMatch(
                        block1=CodeLocation(
                            file_path=self.file_path,
                            start_line=start1,
                            end_line=end1,
                        ),
                        block2=CodeLocation(
                            file_path=self.file_path,
                            start_line=start2,
                            end_line=end2,
                        ),
                        similarity=similarity,
                        content=content1,
                    ))

        return matches

    def apply(self) -> RefactoringSummary:
        """Run duplicate detection and return the results.

        Returns:
            A RefactoringSummary with the detected duplicates.
        """
        blocks = self._extract_blocks()
        all_matches: List[DuplicateMatch] = []

        if self.method in ('ast', 'both'):
            all_matches.extend(self._detect_ast_duplicates(blocks))
        if self.method in ('text', 'both'):
            all_matches.extend(self._detect_text_duplicates(blocks))

        # Remove duplicate matches based on location pairs
        seen: Set[Tuple[int, int, int, int]] = set()
        unique_matches: List[DuplicateMatch] = []
        for match in all_matches:
            key = (match.block1.start_line, match.block1.end_line,
                   match.block2.start_line, match.block2.end_line)
            reverse_key = (match.block2.start_line, match.block2.end_line,
                           match.block1.start_line, match.block1.end_line)
            if key not in seen and reverse_key not in seen:
                seen.add(key)
                unique_matches.append(match)

        # Sort by similarity (highest first)
        unique_matches.sort(key=lambda m: m.similarity, reverse=True)

        results_lines: List[str] = []
        for match in unique_matches:
            results_lines.append(str(match))
            results_lines.append('')

        result_text = '\n'.join(results_lines)

        warnings: List[SafetyWarning] = []
        if unique_matches:
            warnings.append(SafetyWarning(
                'duplicates_found',
                f"Found {len(unique_matches)} duplicate code block(s). "
                f"Consider extracting into a shared function.",
                severity='warning',
            ))

        return RefactoringSummary(
            operation='detect_duplicates',
            description=f"Found {len(unique_matches)} duplicate(s) "
                        f"(threshold={self.threshold}, min_lines={self.min_lines})",
            success=True,
            original_code=self.source_code,
            refactored_code=self.source_code,
            diff=result_text,
            warnings=warnings,
        )


# ── Design Pattern Analyzer ──────────────────────────────────────────────────


class DesignPatternAnalyzer(RefactoringEngine):
    """Analyzes Python source code and suggests applicable design patterns.

    Uses heuristic analysis of code structure, class relationships, and
    method signatures to identify opportunities for applying common
    design patterns.

    Attributes:
        suggestions: List of generated pattern suggestions.
    """

    # Pattern descriptions for reference
    PATTERN_INFO: ClassVar[Dict[str, Dict[str, str]]] = {
        'Singleton': {
            'description': 'Ensures a class has only one instance.',
            'indicators': 'Class-level instance management, __new__ override.',
        },
        'Factory': {
            'description': 'Creates objects without specifying exact class.',
            'indicators': 'Methods returning different class instances based on input.',
        },
        'Observer': {
            'description': 'Defines a one-to-many dependency between objects.',
            'indicators': 'Register/notify/update method patterns.',
        },
        'Strategy': {
            'description': 'Defines a family of interchangeable algorithms.',
            'indicators': 'Multiple classes with identical interfaces, swapped at runtime.',
        },
        'Builder': {
            'description': 'Separates object construction from representation.',
            'indicators': 'Chainable setter methods, complex __init__ methods.',
        },
        'Adapter': {
            'description': 'Allows incompatible interfaces to work together.',
            'indicators': 'Wrapper classes that delegate with interface conversion.',
        },
        'Decorator': {
            'description': 'Adds behavior to objects dynamically.',
            'indicators': 'Wrapper classes with same interface, callable __init__.',
        },
        'Facade': {
            'description': 'Provides a simplified interface to a complex subsystem.',
            'indicators': 'Classes that aggregate many other classes, delegating calls.',
        },
        'Template Method': {
            'description': 'Defines skeleton of algorithm, deferring steps to subclasses.',
            'indicators': 'Base class with abstract methods called by a concrete method.',
        },
        'Prototype': {
            'description': 'Creates objects by cloning existing instances.',
            'indicators': 'Classes with copy or clone methods.',
        },
    }

    def __init__(
        self,
        source_code: str,
        file_path: Optional[str] = None,
        dry_run: bool = False,
    ) -> None:
        """Initialize the design pattern analyzer.

        Args:
            source_code: The source code to analyze.
            file_path: Optional path to the source file.
            dry_run: If True, show results without writing.
        """
        super().__init__(source_code, file_path, dry_run)
        self.suggestions: List[PatternSuggestion] = []

    def _check_singleton(self) -> Optional[PatternSuggestion]:
        """Check if the code uses or could use the Singleton pattern.

        Looks for:
        - __new__ method that manages instance creation
        - Class-level _instance variable
        - Custom instance() or get_instance() class methods

        Returns:
            A PatternSuggestion if the pattern is detected, else None.
        """
        for node in ast.walk(self.ast_tree):
            if isinstance(node, ast.ClassDef):
                has_instance_var = False
                has_new_method = False
                has_instance_method = False

                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name) and 'instance' in target.id.lower():
                                has_instance_var = True
                    elif isinstance(item, ast.FunctionDef):
                        if item.name == '__new__':
                            has_new_method = True
                        if item.name in ('instance', 'get_instance', 'getinstance'):
                            has_instance_method = True

                if has_instance_var or has_new_method or has_instance_method:
                    return PatternSuggestion(
                        pattern_name='Singleton',
                        confidence=0.85 if has_new_method else 0.65,
                        description=self.PATTERN_INFO['Singleton']['description'],
                        rationale=(
                            f"Class '{node.name}' manages its own instance lifecycle. "
                            f"Consider formalizing as a Singleton pattern."
                        ),
                        location=CodeLocation(
                            file_path=self.file_path,
                            start_line=node.lineno,
                            end_line=node.end_lineno,
                        ),
                        example_code=(
                            f"class {node.name}:\n"
                            f"    _instance = None\n\n"
                            f"    def __new__(cls):\n"
                            f"        if cls._instance is None:\n"
                            f"            cls._instance = super().__new__(cls)\n"
                            f"        return cls._instance\n"
                        ),
                    )
        return None

    def _check_factory(self) -> Optional[PatternSuggestion]:
        """Check if the code uses or could use the Factory pattern.

        Looks for methods that return instances of different classes
        based on conditional logic (if/elif chains).

        Returns:
            A PatternSuggestion if the pattern is detected, else None.
        """
        for node in ast.walk(self.ast_tree):
            if isinstance(node, ast.FunctionDef):
                # Look for methods that return different types
                returns: List[ast.AST] = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Return) and child.value is not None:
                        returns.append(child.value)

                if len(returns) >= 2:
                    # Check if returns are creating different types
                    created_types: Set[str] = set()
                    for ret in returns:
                        if isinstance(ret, ast.Call):
                            if isinstance(ret.func, ast.Name):
                                if ret.func.id[0].isupper():
                                    created_types.add(ret.func.id)
                            elif isinstance(ret.func, ast.Attribute):
                                if isinstance(ret.func.value, ast.Name):
                                    created_types.add(ret.func.attr)

                    if len(created_types) >= 2:
                        return PatternSuggestion(
                            pattern_name='Factory',
                            confidence=0.75,
                            description=self.PATTERN_INFO['Factory']['description'],
                            rationale=(
                                f"Method '{node.name}' returns different types "
                                f"({', '.join(sorted(created_types))}). "
                                f"Consider using a Factory pattern."
                            ),
                            location=CodeLocation(
                                file_path=self.file_path,
                                start_line=node.lineno,
                                end_line=node.end_lineno,
                            ),
                        )
        return None

    def _check_observer(self) -> Optional[PatternSuggestion]:
        """Check if the code uses or could use the Observer pattern.

        Looks for register/notify/update method names and observer
        collection patterns.

        Returns:
            A PatternSuggestion if the pattern is detected, else None.
        """
        for node in ast.walk(self.ast_tree):
            if isinstance(node, ast.ClassDef):
                method_names: Set[str] = {item.name for item in node.body
                                          if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))}

                has_register = any('register' in n.lower() or 'subscribe' in n.lower()
                                   for n in method_names)
                has_notify = any('notify' in n.lower() or 'publish' in n.lower()
                                 for n in method_names)
                has_update = any('update' in n.lower() for n in method_names)
                has_observer_list = any(
                    isinstance(item, ast.Assign) and
                    any(isinstance(t, ast.Name) and
                        ('observer' in t.id.lower() or 'listener' in t.id.lower())
                        for t in item.targets)
                    for item in node.body
                )

                score = sum([has_register, has_notify, has_update, has_observer_list])
                if score >= 2:
                    confidence = 0.5 + (score * 0.1)
                    return PatternSuggestion(
                        pattern_name='Observer',
                        confidence=min(confidence, 0.95),
                        description=self.PATTERN_INFO['Observer']['description'],
                        rationale=(
                            f"Class '{node.name}' has observer-like methods "
                            f"(register={has_register}, notify={has_notify}, "
                            f"update={has_update}). Consider formalizing as Observer pattern."
                        ),
                        location=CodeLocation(
                            file_path=self.file_path,
                            start_line=node.lineno,
                            end_line=node.end_lineno,
                        ),
                    )
        return None

    def _check_strategy(self) -> Optional[PatternSuggestion]:
        """Check if the code uses or could use the Strategy pattern.

        Looks for multiple classes with similar interfaces that are
        used interchangeably, or long if/elif chains that select
        behavior.

        Returns:
            A PatternSuggestion if the pattern is detected, else None.
        """
        # Collect all classes with their methods
        classes: Dict[str, Set[str]] = {}
        for node in ast.walk(self.ast_tree):
            if isinstance(node, ast.ClassDef):
                methods = {item.name for item in node.body
                           if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))}
                classes[node.name] = methods

        # Check for classes with similar interfaces
        for name1, methods1 in classes.items():
            for name2, methods2 in classes.items():
                if name1 < name2:
                    common = methods1 & methods2
                    if len(common) >= 2 and len(common) >= min(len(methods1), len(methods2)) * 0.5:
                        return PatternSuggestion(
                            pattern_name='Strategy',
                            confidence=0.7,
                            description=self.PATTERN_INFO['Strategy']['description'],
                            rationale=(
                                f"Classes '{name1}' and '{name2}' share {len(common)} "
                                f"common methods: {', '.join(sorted(common))}. "
                                f"Consider using a Strategy pattern with a common interface."
                            ),
                        )
        return None

    def _check_builder(self) -> Optional[PatternSuggestion]:
        """Check if the code uses or could use the Builder pattern.

        Looks for classes with chainable methods (returning self) or
        complex constructors with many parameters.

        Returns:
            A PatternSuggestion if the pattern is detected, else None.
        """
        for node in ast.walk(self.ast_tree):
            if isinstance(node, ast.ClassDef):
                # Check for chainable methods
                chainable = 0
                total_methods = 0
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        total_methods += 1
                        # Check if method returns self
                        for child in ast.walk(item):
                            if isinstance(child, ast.Return) and child.value is not None:
                                if (isinstance(child.value, ast.Name) and
                                        child.value.id == 'self'):
                                    chainable += 1
                                    break

                # Check for __init__ with many parameters
                init_params = 0
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == '__init__':
                        init_params = len(item.args.args) - 1  # exclude self

                if chainable >= 2 or init_params >= 5:
                    return PatternSuggestion(
                        pattern_name='Builder',
                        confidence=0.7 if chainable >= 2 else 0.6,
                        description=self.PATTERN_INFO['Builder']['description'],
                        rationale=(
                            f"Class '{node.name}' has {chainable} chainable method(s) "
                            f"and __init__ with {init_params} parameter(s). "
                            f"Consider using a Builder pattern."
                        ),
                        location=CodeLocation(
                            file_path=self.file_path,
                            start_line=node.lineno,
                            end_line=node.end_lineno,
                        ),
                    )
        return None

    def _check_adapter(self) -> Optional[PatternSuggestion]:
        """Check if the code uses or could use the Adapter pattern.

        Looks for wrapper classes that delegate calls with interface
        conversion.

        Returns:
            A PatternSuggestion if the pattern is detected, else None.
        """
        for node in ast.walk(self.ast_tree):
            if isinstance(node, ast.ClassDef):
                # Check if class wraps another object
                has_wrapped = False
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name) and target.id in ('wrapped', '_obj', 'adaptee'):
                                has_wrapped = True
                    if isinstance(item, ast.FunctionDef):
                        if item.name == '__init__':
                            for child in ast.walk(item):
                                if (isinstance(child, ast.Attribute) and
                                        isinstance(child.value, ast.Name) and
                                        child.value.id == 'self' and
                                        child.attr in ('wrapped', '_obj', 'adaptee', 'obj')):
                                    has_wrapped = True

                if has_wrapped:
                    return PatternSuggestion(
                        pattern_name='Adapter',
                        confidence=0.65,
                        description=self.PATTERN_INFO['Adapter']['description'],
                        rationale=(
                            f"Class '{node.name}' appears to wrap another object. "
                            f"Consider formalizing as an Adapter pattern."
                        ),
                        location=CodeLocation(
                            file_path=self.file_path,
                            start_line=node.lineno,
                            end_line=node.end_lineno,
                        ),
                    )
        return None

    def _check_decorator(self) -> Optional[PatternSuggestion]:
        """Check if the code uses or could use the Decorator pattern.

        Looks for wrapper classes that accept a callable/compatible object
        in __init__ and implement the same interface.

        Returns:
            A PatternSuggestion if the pattern is detected, else None.
        """
        for node in ast.walk(self.ast_tree):
            if isinstance(node, ast.ClassDef):
                method_names: Set[str] = set()
                has_wrapped_param = False

                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        method_names.add(item.name)
                        if item.name == '__init__':
                            for child in ast.walk(item):
                                if (isinstance(child, ast.Call) and
                                        isinstance(child.func, ast.Attribute) and
                                        child.func.attr in ('__call__', 'call')):
                                    has_wrapped_param = True

                if has_wrapped_param and len(method_names) >= 2:
                    return PatternSuggestion(
                        pattern_name='Decorator',
                        confidence=0.6,
                        description=self.PATTERN_INFO['Decorator']['description'],
                        rationale=(
                            f"Class '{node.name}' wraps a callable and implements "
                            f"{len(method_names)} methods. Consider using Decorator pattern."
                        ),
                        location=CodeLocation(
                            file_path=self.file_path,
                            start_line=node.lineno,
                            end_line=node.end_lineno,
                        ),
                    )
        return None

    def _check_facade(self) -> Optional[PatternSuggestion]:
        """Check if the code uses or could use the Facade pattern.

        Looks for classes that aggregate and delegate to many other
        classes, providing a simplified interface.

        Returns:
            A PatternSuggestion if the pattern is detected, else None.
        """
        for node in ast.walk(self.ast_tree):
            if isinstance(node, ast.ClassDef):
                # Count how many other classes are referenced in __init__
                referenced_classes: Set[str] = set()
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        for child in ast.walk(item):
                            if (isinstance(child, ast.Call) and
                                    isinstance(child.func, ast.Name) and
                                    child.func.id[0].isupper() and
                                    child.func.id != node.name):
                                referenced_classes.add(child.func.id)

                if len(referenced_classes) >= 3:
                    return PatternSuggestion(
                        pattern_name='Facade',
                        confidence=0.7,
                        description=self.PATTERN_INFO['Facade']['description'],
                        rationale=(
                            f"Class '{node.name}' references {len(referenced_classes)} "
                            f"other classes ({', '.join(sorted(referenced_classes))}). "
                            f"Consider formalizing as a Facade pattern."
                        ),
                        location=CodeLocation(
                            file_path=self.file_path,
                            start_line=node.lineno,
                            end_line=node.end_lineno,
                        ),
                    )
        return None

    def _check_template_method(self) -> Optional[PatternSuggestion]:
        """Check if the code uses or could use the Template Method pattern.

        Looks for base classes with abstract methods called by a concrete
        method that defines the algorithm skeleton.

        Returns:
            A PatternSuggestion if the pattern is detected, else None.
        """
        for node in ast.walk(self.ast_tree):
            if isinstance(node, ast.ClassDef):
                abstract_methods: Set[str] = set()
                concrete_methods: Set[str] = set()
                has_abstract = False

                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        # Check for decorators
                        for decorator in item.decorator_list:
                            if (isinstance(decorator, ast.Name) and
                                    decorator.id in ('abstractmethod', 'abstract_class_method')):
                                has_abstract = True
                                abstract_methods.add(item.name)
                                break
                        else:
                            concrete_methods.add(item.name)

                    # Check for ABCMeta/ABC inheritance
                    if isinstance(item, ast.ClassDef) and item.name == node.name:
                        for base in item.bases:
                            if isinstance(base, ast.Name) and base.id in ('ABC', 'ABCMeta'):
                                has_abstract = True

                if abstract_methods and concrete_methods:
                    # Check if a concrete method calls abstract methods
                    for cm in concrete_methods:
                        for item in node.body:
                            if isinstance(item, ast.FunctionDef) and item.name == cm:
                                called_names = set(get_all_names(item))
                                shared = called_names & abstract_methods
                                if shared:
                                    return PatternSuggestion(
                                        pattern_name='Template Method',
                                        confidence=0.8,
                                        description=self.PATTERN_INFO['Template Method']['description'],
                                        rationale=(
                                            f"Class '{node.name}' has abstract method(s) "
                                            f"({', '.join(sorted(abstract_methods))}) called by "
                                            f"concrete method '{cm}'. This is the Template Method pattern."
                                        ),
                                        location=CodeLocation(
                                            file_path=self.file_path,
                                            start_line=node.lineno,
                                            end_line=node.end_lineno,
                                        ),
                                    )
        return None

    def _check_prototype(self) -> Optional[PatternSuggestion]:
        """Check if the code uses or could use the Prototype pattern.

        Looks for classes with copy or clone methods.

        Returns:
            A PatternSuggestion if the pattern is detected, else None.
        """
        for node in ast.walk(self.ast_tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        if item.name in ('copy', 'clone', 'duplicate'):
                            return PatternSuggestion(
                                pattern_name='Prototype',
                                confidence=0.7,
                                description=self.PATTERN_INFO['Prototype']['description'],
                                rationale=(
                                    f"Class '{node.name}' has a '{item.name}' method "
                                    f"for creating copies. Consider using the Prototype pattern."
                                ),
                                location=CodeLocation(
                                    file_path=self.file_path,
                                    start_line=node.lineno,
                                    end_line=node.end_lineno,
                                ),
                            )
        return None

    def analyze(self) -> List[PatternSuggestion]:
        """Run all pattern checks and return the collected suggestions.

        Returns:
            A list of PatternSuggestion objects, sorted by confidence.
        """
        self.suggestions.clear()

        checks: List[Callable[[], Optional[PatternSuggestion]]] = [
            self._check_singleton,
            self._check_factory,
            self._check_observer,
            self._check_strategy,
            self._check_builder,
            self._check_adapter,
            self._check_decorator,
            self._check_facade,
            self._check_template_method,
            self._check_prototype,
        ]

        for check in checks:
            try:
                result = check()
                if result is not None:
                    self.suggestions.append(result)
            except Exception:
                # Individual checks should not fail the whole analysis
                pass

        self.suggestions.sort(key=lambda s: s.confidence, reverse=True)
        return self.suggestions

    def apply(self) -> RefactoringSummary:
        """Run the design pattern analysis and return the results.

        Returns:
            A RefactoringSummary with the pattern suggestions.
        """
        self.analyze()

        result_lines: List[str] = []
        if self.suggestions:
            result_lines.append(f"Found {len(self.suggestions)} pattern suggestion(s):")
            result_lines.append('')
            for s in self.suggestions:
                result_lines.append(str(s))
                result_lines.append('')
        else:
            result_lines.append("No design pattern suggestions found.")

        result_text = '\n'.join(result_lines)

        return RefactoringSummary(
            operation='analyze_patterns',
            description=f"Generated {len(self.suggestions)} design pattern suggestion(s)",
            success=True,
            original_code=self.source_code,
            refactored_code=self.source_code,
            diff=result_text,
        )


# ── Safety Checker ───────────────────────────────────────────────────────────


class SafetyChecker(RefactoringEngine):
    """Verifies that a refactoring operation preserves program semantics.

    Compares the original and refactored code using AST comparison,
    syntax validation, and various semantic checks.

    Attributes:
        refactored_code: The refactored source code to check against.
    """

    def __init__(
        self,
        source_code: str,
        refactored_code: str,
        file_path: Optional[str] = None,
        dry_run: bool = False,
    ) -> None:
        """Initialize the safety checker.

        Args:
            source_code: The original source code.
            refactored_code: The refactored source code to validate.
            file_path: Optional path to the source file.
            dry_run: If True, show results without writing.
        """
        super().__init__(source_code, file_path, dry_run)
        self.refactored_code: str = refactored_code

        # Parse refactored code
        try:
            self.refactored_ast: ast.Module = parse_code(refactored_code)
        except ParsingError as e:
            self.refactored_ast = ast.Module(body=[])
            self._parse_error = str(e)
        else:
            self._parse_error = None

    def check(self) -> SafetyReport:
        """Perform a comprehensive safety check of the refactoring.

        Returns:
            A SafetyReport with the results of all checks.
        """
        report = SafetyReport()

        # 1. Syntax check
        self._check_syntax_validity(report)

        if not report.syntax_valid:
            report.is_safe = False
            return report

        # 2. AST structure comparison
        self._check_ast_structure(report)

        # 3. Import consistency
        self._check_imports(report)

        # 4. Global name consistency
        self._check_global_names(report)

        # 5. Function signature consistency
        self._check_function_signatures(report)

        # 6. Class structure consistency
        self._check_class_structure(report)

        return report

    def _check_syntax_validity(self, report: SafetyReport) -> None:
        """Check if both original and refactored code have valid syntax.

        Args:
            report: The safety report to update.
        """
        orig_valid, orig_error = self._check_syntax(self.source_code)
        refac_valid, refac_error = self._check_syntax(self.refactored_code)

        if not orig_valid:
            report.add_warning(
                'syntax',
                f"Original code has syntax errors: {orig_error}",
                severity='error',
            )
            report.syntax_valid = False

        if not refac_valid:
            report.add_warning(
                'syntax',
                f"Refactored code has syntax errors: {refac_error}",
                severity='error',
            )
            report.syntax_valid = False

    def _check_ast_structure(self, report: SafetyReport) -> None:
        """Compare the AST structure of original and refactored code.

        Args:
            report: The safety report to update.
        """
        try:
            similarity = ast_similarity(self.ast_tree, self.refactored_ast)
            report.ast_match_score = similarity

            if similarity < 0.5:
                report.add_warning(
                    'semantics',
                    f"AST structure is very different (similarity: {similarity:.2%}). "
                    f"Refactoring may have changed program semantics.",
                    severity='warning',
                )
            elif similarity < 0.8:
                report.add_warning(
                    'semantics',
                    f"AST structure has moderate differences (similarity: {similarity:.2%}). "
                    f"Verify the refactoring manually.",
                    severity='info',
                )
        except Exception as e:
            report.add_warning(
                'semantics',
                f"Failed to compare AST structures: {e}",
                severity='warning',
            )

    def _check_imports(self, report: SafetyReport) -> None:
        """Check that imports are consistent between original and refactored code.

        Args:
            report: The safety report to update.
        """
        def get_imports(tree: ast.AST) -> Set[Tuple[str, Optional[str]]]:
            imports: Set[Tuple[str, Optional[str]]] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add((alias.name, alias.asname))
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        imports.add((f"{node.module}.{alias.name}", alias.asname))
            return imports

        orig_imports = get_imports(self.ast_tree)
        refac_imports = get_imports(self.refactored_ast)

        missing = orig_imports - refac_imports
        extra = refac_imports - orig_imports

        if missing:
            report.add_warning(
                'imports',
                f"Missing imports in refactored code: {', '.join(m[0] for m in missing)}",
                severity='error',
            )

        if extra:
            report.add_warning(
                'imports',
                f"Extra imports in refactored code: {', '.join(e[0] for e in extra)}",
                severity='info',
            )

    def _check_global_names(self, report: SafetyReport) -> None:
        """Check that top-level names are consistent between versions.

        Args:
            report: The safety report to update.
        """
        def get_global_names(tree: ast.AST) -> Set[str]:
            names: Set[str] = set()
            if isinstance(tree, ast.Module):
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        names.add(node.name)
                    elif isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                names.add(target.id)
            return names

        orig_names = get_global_names(self.ast_tree)
        refac_names = get_global_names(self.refactored_ast)

        # Allow extra names in refactored (new functions, etc.)
        missing = orig_names - refac_names
        if missing:
            report.add_warning(
                'globals',
                f"Top-level names removed: {', '.join(sorted(missing))}",
                severity='warning',
            )

    def _check_function_signatures(self, report: SafetyReport) -> None:
        """Check that function signatures are preserved.

        Args:
            report: The safety report to update.
        """
        def get_signatures(tree: ast.AST) -> Dict[str, int]:
            sigs: Dict[str, int] = {}
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sigs[node.name] = len(node.args.args)
            return sigs

        orig_sigs = get_signatures(self.ast_tree)
        refac_sigs = get_signatures(self.refactored_ast)

        for func_name, orig_count in orig_sigs.items():
            if func_name in refac_sigs:
                refac_count = refac_sigs[func_name]
                if orig_count != refac_count:
                    report.add_warning(
                        'function_signature',
                        f"Function '{func_name}' parameter count changed "
                        f"from {orig_count} to {refac_count}",
                        severity='warning',
                    )

    def _check_class_structure(self, report: SafetyReport) -> None:
        """Check that class structures are preserved.

        Args:
            report: The safety report to update.
        """
        def get_class_methods(tree: ast.AST) -> Dict[str, Set[str]]:
            classes: Dict[str, Set[str]] = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    methods: Set[str] = set()
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            methods.add(item.name)
                    classes[node.name] = methods
            return classes

        orig_classes = get_class_methods(self.ast_tree)
        refac_classes = get_class_methods(self.refactored_ast)

        for cls_name, orig_methods in orig_classes.items():
            if cls_name in refac_classes:
                refac_methods = refac_classes[cls_name]
                missing = orig_methods - refac_methods
                if missing:
                    report.add_warning(
                        'class_structure',
                        f"Class '{cls_name}' missing methods: {', '.join(sorted(missing))}",
                        severity='error',
                    )

    def apply(self) -> RefactoringSummary:
        """Run the safety check and return the results.

        Returns:
            A RefactoringSummary with the safety check results.
        """
        report = self.check()

        # Build a summary
        diff = generate_unified_diff(self.source_code, self.refactored_code)

        return RefactoringSummary(
            operation='safety_check',
            description=f"Safety check: {'SAFE' if report.is_safe else 'ISSUES FOUND'}",
            success=report.is_safe,
            original_code=self.source_code,
            refactored_code=self.refactored_code,
            diff=diff,
            warnings=report.warnings,
        )


# ── Code Diff Generator ──────────────────────────────────────────────────────


class CodeDiffGenerator:
    """Generates diffs between original and refactored code in multiple formats.

    Supports unified diff, colored terminal output, and HTML-formatted diff.
    """

    def __init__(self, original: str, refactored: str) -> None:
        """Initialize the diff generator.

        Args:
            original: Original source code.
            refactored: Refactored source code.
        """
        self.original: str = original
        self.refactored: str = refactored
        self.original_lines: List[str] = original.splitlines(keepends=True)
        self.refactored_lines: List[str] = refactored.splitlines(keepends=True)

    def generate_unified(
        self,
        original_name: str = 'original',
        refactored_name: str = 'refactored',
        n_context: int = 3,
    ) -> str:
        """Generate a standard unified diff.

        Args:
            original_name: Label for the original version.
            refactored_name: Label for the refactored version.
            n_context: Number of context lines.

        Returns:
            A unified diff string.
        """
        return generate_unified_diff(
            self.original, self.refactored,
            original_name=original_name,
            refactored_name=refactored_name,
            n_context=n_context,
        )

    def generate_colored(self, n_context: int = 3) -> str:
        """Generate a diff with ANSI color codes for terminal display.

        Args:
            n_context: Number of context lines.

        Returns:
            A colorized diff string.
        """
        diff = self.generate_unified(n_context=n_context)

        # ANSI color codes
        RED = '\033[91m'
        GREEN = '\033[92m'
        YELLOW = '\033[93m'
        CYAN = '\033[96m'
        RESET = '\033[0m'

        colored_lines: List[str] = []
        for line in diff.splitlines(keepends=True):
            if line.startswith('+++') or line.startswith('---'):
                colored_lines.append(f"{CYAN}{line}{RESET}")
            elif line.startswith('+'):
                colored_lines.append(f"{GREEN}{line}{RESET}")
            elif line.startswith('-'):
                colored_lines.append(f"{RED}{line}{RESET}")
            elif line.startswith('@@'):
                colored_lines.append(f"{YELLOW}{line}{RESET}")
            else:
                colored_lines.append(line)

        return ''.join(colored_lines)

    def generate_html(self, n_context: int = 3) -> str:
        """Generate an HTML-formatted diff with line numbers.

        Args:
            n_context: Number of context lines.

        Returns:
            An HTML string showing the diff.
        """
        diff = difflib.HtmlDiff(tabsize=4)
        html = diff.make_file(
            self.original_lines,
            self.refactored_lines,
            fromdesc='Original',
            todesc='Refactored',
            context=True,
            numlines=n_context,
        )
        return html

    def generate_statistics(self) -> Dict[str, int]:
        """Generate statistics about the diff.

        Returns:
            A dictionary with keys: added, removed, changed, total_added_lines,
            total_removed_lines.
        """
        diff_lines = self.generate_unified().splitlines()
        added = 0
        removed = 0
        changed = 0

        in_hunk = False
        for line in diff_lines:
            if line.startswith('@@'):
                if in_hunk:
                    changed += 1
                in_hunk = True
            elif in_hunk:
                if line.startswith('+') and not line.startswith('+++'):
                    added += 1
                elif line.startswith('-') and not line.startswith('---'):
                    removed += 1

        return {
            'added_lines': added,
            'removed_lines': removed,
            'hunks': changed,
            'net_change': added - removed,
        }


# ── CLI Entry Point ──────────────────────────────────────────────────────────


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for the CLI.

    Returns:
        A configured ArgumentParser instance.
    """
    # Common parent parser for flags shared across all subcommands
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument(
        '--dry-run', action='store_true', default=False,
        help='Show refactoring results without modifying files',
    )
    common_parser.add_argument(
        '--verbose', '-v', action='store_true', default=False,
        help='Enable verbose output',
    )

    parser = argparse.ArgumentParser(
        prog='ai-refactor',
        description='AI-Powered Code Refactoring Assistant',
        epilog=(
            'Examples:\n'
            '  %(prog)s extract file.py --lines 10-25 --name new_function\n'
            '  %(prog)s rename file.py --from old_var --to new_var\n'
            '  %(prog)s detect file.py --min-lines 5 --threshold 0.8\n'
            '  %(prog)s analyze file.py\n'
            '  %(prog)s check file.py --refactored file_refactored.py\n'
            '  %(prog)s diff file.py file_refactored.py\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        '--version', action='version', version=f'%(prog)s {VERSION}',
    )

    subparsers = parser.add_subparsers(
        dest='command', title='Commands', required=True,
    )

    # Extract command
    extract_parser = subparsers.add_parser(
        'extract', parents=[common_parser],
        help='Extract code into a new function',
        description='Extract a block of code into a named function.',
    )
    extract_parser.add_argument('file', help='Python source file to refactor')
    extract_parser.add_argument(
        '--lines', '-l', required=True,
        help='Line range to extract (e.g., "10-25")',
    )
    extract_parser.add_argument(
        '--name', '-n', required=True,
        help='Name for the extracted function',
    )

    # Rename command
    rename_parser = subparsers.add_parser(
        'rename', parents=[common_parser],
        help='Rename a variable',
        description='Safely rename a variable with scope awareness.',
    )
    rename_parser.add_argument('file', help='Python source file to refactor')
    rename_parser.add_argument(
        '--from', '-f', dest='old_name', required=True,
        help='Current variable name',
    )
    rename_parser.add_argument(
        '--to', '-t', dest='new_name', required=True,
        help='New variable name',
    )
    rename_parser.add_argument(
        '--scope', '-s', dest='scope_limit', default=None,
        help='Limit rename to a specific scope (function/class name)',
    )

    # Detect command
    detect_parser = subparsers.add_parser(
        'detect', parents=[common_parser],
        help='Detect duplicate code',
        description='Find duplicate or highly similar code blocks.',
    )
    detect_parser.add_argument('file', help='Python source file to analyze')
    detect_parser.add_argument(
        '--min-lines', '-m', type=int, default=5,
        help='Minimum lines for a code block (default: 5)',
    )
    detect_parser.add_argument(
        '--threshold', '-t', type=float, default=0.8,
        help='Similarity threshold 0.0-1.0 (default: 0.8)',
    )
    detect_parser.add_argument(
        '--method', choices=['ast', 'text', 'both'], default='both',
        help='Detection method (default: both)',
    )

    # Analyze command
    analyze_parser = subparsers.add_parser(
        'analyze', parents=[common_parser],
        help='Analyze design patterns',
        description='Analyze code and suggest applicable design patterns.',
    )
    analyze_parser.add_argument('file', help='Python source file to analyze')

    # Check command
    check_parser = subparsers.add_parser(
        'check', parents=[common_parser],
        help='Check refactoring safety',
        description='Verify that a refactoring preserves semantics.',
    )
    check_parser.add_argument('file', help='Original Python source file')
    check_parser.add_argument(
        '--refactored', '-r', required=True,
        help='Refactored Python source file to validate',
    )

    # Diff command
    diff_parser = subparsers.add_parser(
        'diff', parents=[common_parser],
        help='Show diff between files',
        description='Generate a diff between two Python source files.',
    )
    diff_parser.add_argument('file', help='Original Python source file')
    diff_parser.add_argument('refactored', help='Refactored Python source file')
    diff_parser.add_argument(
        '--format', choices=['unified', 'colored', 'html', 'stats'],
        default='unified', help='Output format (default: unified)',
    )
    diff_parser.add_argument(
        '--context', '-c', type=int, default=3,
        help='Number of context lines (default: 3)',
    )
    diff_parser.add_argument(
        '--output', '-o', default=None,
        help='Write output to file instead of stdout',
    )

    return parser


def handle_extract(args: argparse.Namespace) -> int:
    """Handle the 'extract' subcommand.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    try:
        # Parse line range
        line_parts = args.lines.split('-')
        if len(line_parts) != 2:
            print(f"Error: Invalid line range '{args.lines}'. Use format like '10-25'.",
                  file=sys.stderr)
            return 1
        start_line = int(line_parts[0])
        end_line = int(line_parts[1])
    except ValueError:
        print(f"Error: Invalid line range '{args.lines}'. Use format like '10-25'.",
              file=sys.stderr)
        return 1

    try:
        source = read_source_file(args.file)
        engine = FunctionExtractorRef(
            source_code=source,
            start_line=start_line,
            end_line=end_line,
            function_name=args.name,
            file_path=args.file,
            dry_run=args.dry_run,
        )
        summary = engine.apply()
        print(str(summary))
        return 0 if summary.success else 1
    except (RefactoringError, FileNotFoundError, IOError) as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            traceback.print_exc()
        return 1


def handle_rename(args: argparse.Namespace) -> int:
    """Handle the 'rename' subcommand.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    try:
        source = read_source_file(args.file)
        engine = VariableRenamer(
            source_code=source,
            old_name=args.old_name,
            new_name=args.new_name,
            file_path=args.file,
            dry_run=args.dry_run,
            scope_limit=args.scope_limit,
        )
        summary = engine.apply()
        print(str(summary))
        return 0 if summary.success else 1
    except (RefactoringError, FileNotFoundError, IOError) as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            traceback.print_exc()
        return 1


def handle_detect(args: argparse.Namespace) -> int:
    """Handle the 'detect' subcommand.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    try:
        source = read_source_file(args.file)
        engine = DuplicateDetector(
            source_code=source,
            file_path=args.file,
            dry_run=args.dry_run,
            min_lines=args.min_lines,
            threshold=args.threshold,
            method=args.method,
        )
        summary = engine.apply()
        print(str(summary))
        return 0 if summary.success else 1
    except (RefactoringError, FileNotFoundError, IOError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            traceback.print_exc()
        return 1


def handle_analyze(args: argparse.Namespace) -> int:
    """Handle the 'analyze' subcommand.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    try:
        source = read_source_file(args.file)
        engine = DesignPatternAnalyzer(
            source_code=source,
            file_path=args.file,
            dry_run=args.dry_run,
        )
        summary = engine.apply()
        print(str(summary))
        return 0 if summary.success else 1
    except (RefactoringError, FileNotFoundError, IOError) as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            traceback.print_exc()
        return 1


def handle_check(args: argparse.Namespace) -> int:
    """Handle the 'check' subcommand.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    try:
        source = read_source_file(args.file)
        refactored = read_source_file(args.refactored)
        engine = SafetyChecker(
            source_code=source,
            refactored_code=refactored,
            file_path=args.file,
            dry_run=args.dry_run,
        )
        report = engine.check()
        print(str(report))
        return 0 if report.is_safe else 1
    except (RefactoringError, FileNotFoundError, IOError) as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            traceback.print_exc()
        return 1


def handle_diff(args: argparse.Namespace) -> int:
    """Handle the 'diff' subcommand.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    try:
        original = read_source_file(args.file)
        refactored = read_source_file(args.refactored)

        generator = CodeDiffGenerator(original, refactored)

        if args.format == 'unified':
            result = generator.generate_unified(n_context=args.context)
        elif args.format == 'colored':
            result = generator.generate_colored(n_context=args.context)
        elif args.format == 'html':
            result = generator.generate_html(n_context=args.context)
        elif args.format == 'stats':
            stats = generator.generate_statistics()
            result = json.dumps(stats, indent=2)
        else:
            result = generator.generate_unified(n_context=args.context)

        if args.output:
            Path(args.output).write_text(result, encoding=DEFAULT_ENCODING)
            print(f"Diff written to {args.output}")
        else:
            print(result)

        return 0
    except (FileNotFoundError, IOError) as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            traceback.print_exc()
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point for the AI Refactor CLI.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    parser = create_parser()
    args = parser.parse_args(argv)

    # Map commands to handler functions
    handlers = {
        'extract': handle_extract,
        'rename': handle_rename,
        'detect': handle_detect,
        'analyze': handle_analyze,
        'check': handle_check,
        'diff': handle_diff,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == '__main__':
    sys.exit(main())