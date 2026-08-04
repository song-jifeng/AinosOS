#!/usr/bin/env python3
"""AI-powered Python code completion engine.

Provides context-aware code completions with AST-based analysis,
type inference, symbol tracking, and LSP-compatible structures.

Supports:
  - Variable, function, class, and module completions
  - Context-aware suggestions based on scope
  - Type inference from assignments, annotations, and calls
  - Python keyword completions
  - Import path completions
  - File path completions in string literals
  - Code snippets for common patterns
  - Signature help for function calls
  - Hover information for symbols
  - LSP-compatible data structures
  - Server mode for IDE integration
  - Result caching for performance
"""

from __future__ import annotations

import argparse
import ast
import builtins
import importlib
import importlib.util
import json
import keyword
import logging
import os
import pkgutil
import re
import socket
import sys
import textwrap
import threading
import time
import tokenize
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    List,
    NamedTuple,
    Optional,
    Sequence,
    Set,
    Tuple,
    Type,
    Union,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("ai_complete")

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

__version__ = "1.0.0"
__author__ = "AI-Completion Engine"

# Maximum number of completion items returned by default
DEFAULT_MAX_RESULTS = 100

# Maximum cache entries
DEFAULT_CACHE_SIZE = 200

# Cache TTL in seconds
DEFAULT_CACHE_TTL = 30

# Default server host and port
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876

# Score weights for the priority scoring system
SCORE_WEIGHTS: Dict[str, float] = {
    "exact_match": 100.0,
    "prefix_match": 50.0,
    "substring_match": 20.0,
    "scope_match": 30.0,
    "type_match": 25.0,
    "recent_usage": 10.0,
    "frequency": 5.0,
    "keyword": 15.0,
    "snippet": 10.0,
    "builtin": 5.0,
    "local_var": 35.0,
    "parameter": 40.0,
    "module_match": 20.0,
}

# Python keywords that are valid in expression context
EXPRESSION_KEYWORDS: Set[str] = {
    "True", "False", "None", "and", "or", "not", "in", "is",
    "lambda", "if", "else", "for", "while", "try", "except",
    "finally", "with", "as", "yield", "await",
}

# Python built-in type names for type inference
BUILTIN_TYPE_NAMES: Dict[str, str] = {
    "int": "int",
    "float": "float",
    "str": "str",
    "bool": "bool",
    "bytes": "bytes",
    "bytearray": "bytearray",
    "list": "list",
    "tuple": "tuple",
    "set": "set",
    "frozenset": "frozenset",
    "dict": "dict",
    "complex": "complex",
    "range": "range",
    "memoryview": "memoryview",
    "None": "None",
    "type": "type",
    "object": "object",
    "callable": "Callable",
    "iterable": "Iterable",
    "Any": "Any",
    "Optional": "Optional",
    "Union": "Union",
    "List": "List",
    "Dict": "Dict",
    "Tuple": "Tuple",
    "Set": "Set",
    "Callable": "Callable",
    "Type": "Type",
    "Generator": "Generator",
    "Iterator": "Iterator",
    "Iterable": "Iterable",
    "Sequence": "Sequence",
    "Mapping": "Mapping",
    "NamedTuple": "NamedTuple",
    "TypedDict": "TypedDict",
}

# ---------------------------------------------------------------------------
# LSP-compatible CompletionItemKind
# ---------------------------------------------------------------------------

class CompletionItemKind(IntEnum):
    """LSP-compatible completion item kinds.

    Mirrors the Language Server Protocol specification for completion item
    kinds, enabling seamless integration with LSP clients.
    """

    TEXT = 1
    METHOD = 2
    FUNCTION = 3
    CONSTRUCTOR = 4
    FIELD = 5
    VARIABLE = 6
    CLASS = 7
    INTERFACE = 8
    MODULE = 9
    PROPERTY = 10
    UNIT = 11
    VALUE = 12
    ENUM = 13
    KEYWORD = 14
    SNIPPET = 15
    COLOR = 16
    FILE = 17
    REFERENCE = 18
    FOLDER = 19
    ENUM_MEMBER = 20
    CONSTANT = 21
    STRUCT = 22
    EVENT = 23
    OPERATOR = 24
    TYPE_PARAMETER = 25


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class CompletionItem:
    """Represents a single completion item (LSP CompletionItem compatible).

    Attributes:
        label: Display text for the completion.
        kind: Completion item kind (maps to LSP CompletionItemKind).
        detail: Additional detail string (e.g., type or signature).
        documentation: Markdown documentation string.
        insert_text: Text to insert if different from label.
        insert_text_format: 1 for PlainText, 2 for Snippet.
        filter_text: Text used for filtering.
        sort_text: Text used for sorting.
        preselect: Whether this item is preselected.
        score: Internal priority score (higher = more relevant).
        snippet: Snippet string with placeholders ($1, $2, ...).
        data: Arbitrary extra data.
    """

    label: str
    kind: CompletionItemKind
    detail: Optional[str] = None
    documentation: Optional[str] = None
    insert_text: Optional[str] = None
    insert_text_format: int = 1
    filter_text: Optional[str] = None
    sort_text: Optional[str] = None
    preselect: bool = False
    score: float = 0.0
    snippet: Optional[str] = None
    data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        result: Dict[str, Any] = {
            "label": self.label,
            "kind": int(self.kind),
        }
        if self.detail is not None:
            result["detail"] = self.detail
        if self.documentation is not None:
            result["documentation"] = self.documentation
        if self.insert_text is not None:
            result["insertText"] = self.insert_text
        result["insertTextFormat"] = self.insert_text_format
        if self.filter_text is not None:
            result["filterText"] = self.filter_text
        if self.sort_text is not None:
            result["sortText"] = self.sort_text
        result["preselect"] = self.preselect
        return result

    @classmethod
    def keyword(
        cls,
        name: str,
        documentation: Optional[str] = None,
    ) -> "CompletionItem":
        """Create a keyword completion item."""
        return cls(
            label=name,
            kind=CompletionItemKind.KEYWORD,
            detail="keyword",
            documentation=documentation,
            insert_text=name,
        )

    @classmethod
    def snippet(
        cls,
        label: str,
        insert_text: str,
        description: str,
        documentation: Optional[str] = None,
    ) -> "CompletionItem":
        """Create a snippet completion item."""
        return cls(
            label=label,
            kind=CompletionItemKind.SNIPPET,
            detail=description,
            documentation=documentation,
            insert_text=insert_text,
            insert_text_format=2,
            snippet=insert_text,
        )

    @classmethod
    def variable(
        cls,
        name: str,
        type_name: Optional[str] = None,
        documentation: Optional[str] = None,
    ) -> "CompletionItem":
        """Create a variable completion item."""
        return cls(
            label=name,
            kind=CompletionItemKind.VARIABLE,
            detail=f"-> {type_name}" if type_name else "variable",
            documentation=documentation,
            insert_text=name,
        )

    @classmethod
    def function(
        cls,
        name: str,
        signature: str,
        documentation: Optional[str] = None,
    ) -> "CompletionItem":
        """Create a function completion item."""
        return cls(
            label=name,
            kind=CompletionItemKind.FUNCTION,
            detail=signature,
            documentation=documentation,
            insert_text=f"{name}(",
            insert_text_format=2,
        )

    @classmethod
    def class_(
        cls,
        name: str,
        bases: Optional[List[str]] = None,
        documentation: Optional[str] = None,
    ) -> "CompletionItem":
        """Create a class completion item."""
        base_str = f"({', '.join(bases)})" if bases else ""
        return cls(
            label=name,
            kind=CompletionItemKind.CLASS,
            detail=f"class{base_str}",
            documentation=documentation,
            insert_text=name,
        )

    @classmethod
    def module(
        cls,
        name: str,
        is_package: bool = False,
    ) -> "CompletionItem":
        """Create a module completion item."""
        return cls(
            label=name,
            kind=CompletionItemKind.MODULE,
            detail="package" if is_package else "module",
            insert_text=name,
        )

    @classmethod
    def file_path(
        cls,
        path: str,
        is_dir: bool = False,
    ) -> "CompletionItem":
        """Create a file path completion item."""
        return cls(
            label=path,
            kind=CompletionItemKind.FILE if not is_dir else CompletionItemKind.FOLDER,
            detail="directory" if is_dir else "file",
            insert_text=path,
        )


@dataclass
class Symbol:
    """Represents a defined symbol in the codebase.

    Attributes:
        name: Symbol name.
        kind: Symbol kind ('variable', 'function', 'class', 'module',
              'parameter', 'method', 'attribute').
        type_name: Inferred or annotated type.
        scope: Scope path ('global', 'function:foo', 'class:Bar').
        line: Line number where the symbol is defined.
        column: Column number where the symbol is defined.
        docstring: Docstring text, if available.
        parameters: List of parameter names (for functions/methods).
    """

    name: str
    kind: str
    type_name: Optional[str] = None
    scope: str = "global"
    line: int = 0
    column: int = 0
    docstring: Optional[str] = None
    parameters: List[str] = field(default_factory=list)


@dataclass
class SignatureInfo:
    """Represents a function/method signature for signature help.

    Attributes:
        name: Function name.
        label: Full signature label (e.g., "foo(x: int, y: str) -> bool").
        parameters: List of parameter labels.
        active_parameter: Index of the active parameter (0-based).
        documentation: Optional documentation string.
    """

    name: str
    label: str
    parameters: List[str] = field(default_factory=list)
    active_parameter: int = 0
    documentation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "name": self.name,
            "label": self.label,
            "parameters": self.parameters,
            "activeParameter": self.active_parameter,
            "documentation": self.documentation,
        }


# ---------------------------------------------------------------------------
# SymbolTable
# ---------------------------------------------------------------------------

class SymbolTable:
    """Tracks defined symbols and their types across scopes.

    Maintains a hierarchical symbol table that maps symbol names to their
    definitions, enabling scope-aware lookup and type inference.
    """

    def __init__(self) -> None:
        self._symbols: Dict[str, Dict[str, Symbol]] = {}
        self._scope_order: List[str] = ["global"]
        self._current_scope: str = "global"
        self._builtins: Set[str] = set(dir(builtins))

    def add_symbol(self, symbol: Symbol) -> None:
        """Add a symbol to the table.

        Args:
            symbol: The symbol to add.

        Raises:
            ValueError: If the symbol name is empty.
        """
        if not symbol.name.strip():
            raise ValueError("Symbol name must not be empty")

        scope = symbol.scope
        if scope not in self._symbols:
            self._symbols[scope] = {}
            if scope not in self._scope_order:
                self._scope_order.append(scope)
        self._symbols[scope][symbol.name] = symbol

    def get_symbol(
        self,
        name: str,
        scope: Optional[str] = None,
    ) -> Optional[Symbol]:
        """Look up a symbol by name, optionally in a specific scope.

        Searches the current scope first, then parent scopes, then global
        scope, then builtins.

        Args:
            name: Symbol name to look up.
            scope: Specific scope to search. If None, searches all visible
                   scopes from the current scope outward.

        Returns:
            The symbol if found, None otherwise.
        """
        # Check builtins first
        if name in self._builtins:
            return Symbol(
                name=name,
                kind="builtin",
                type_name=BUILTIN_TYPE_NAMES.get(name),
                scope="builtin",
            )

        if scope is not None:
            return self._symbols.get(scope, {}).get(name)

        # Local scope first
        if name in self._symbols.get(self._current_scope, {}):
            return self._symbols[self._current_scope][name]

        # Walk up scope hierarchy
        seen: Set[str] = set()
        scope_parts = self._current_scope.split(":")
        for i in range(len(scope_parts), 0, -1):
            parent_scope = ":".join(scope_parts[:i])
            if parent_scope in seen:
                continue
            seen.add(parent_scope)
            if parent_scope in self._symbols and name in self._symbols[parent_scope]:
                return self._symbols[parent_scope][name]

        # Check global scope
        if name in self._symbols.get("global", {}):
            return self._symbols["global"][name]

        return None

    def get_symbols_in_scope(self, scope: str) -> List[Symbol]:
        """Get all symbols defined in a given scope.

        Args:
            scope: The scope name.

        Returns:
            List of symbols in that scope.
        """
        return list(self._symbols.get(scope, {}).values())

    def get_all_symbols(self) -> List[Symbol]:
        """Get all symbols across all scopes.

        Returns:
            Flattened list of all symbols.
        """
        result: List[Symbol] = []
        for scope_symbols in self._symbols.values():
            result.extend(scope_symbols.values())
        return result

    def get_symbols_by_kind(self, kind: str) -> List[Symbol]:
        """Get all symbols of a specific kind.

        Args:
            kind: Symbol kind to filter by.

        Returns:
            List of matching symbols.
        """
        return [s for s in self.get_all_symbols() if s.kind == kind]

    def get_all_names_in_scope(self, scope: str) -> Set[str]:
        """Get all symbol names visible from a scope.

        Includes the scope's own symbols, parent scope symbols, global
        symbols, and builtins.

        Args:
            scope: The scope to query from.

        Returns:
            Set of visible symbol names.
        """
        names: Set[str] = set()
        names.update(self._builtins)

        scope_parts = scope.split(":")
        for i in range(len(scope_parts), 0, -1):
            parent = ":".join(scope_parts[:i])
            if parent in self._symbols:
                names.update(self._symbols[parent].keys())

        if "global" in self._symbols:
            names.update(self._symbols["global"].keys())

        return names

    def enter_scope(self, scope: str) -> str:
        """Enter a new scope.

        Args:
            scope: The scope name to enter.

        Returns:
            The previous scope name.
        """
        previous = self._current_scope
        self._current_scope = scope
        if scope not in self._symbols:
            self._symbols[scope] = {}
            self._scope_order.append(scope)
        return previous

    def exit_scope(self) -> Optional[str]:
        """Exit the current scope and return to the parent.

        Returns:
            The previous (now current) scope name, or None if already at
            global scope.
        """
        if self._current_scope == "global":
            return None

        parts = self._current_scope.split(":")
        if len(parts) > 1:
            self._current_scope = ":".join(parts[:-1])
        else:
            self._current_scope = "global"
        return self._current_scope

    @property
    def current_scope(self) -> str:
        """Get the current scope name."""
        return self._current_scope

    def clear(self) -> None:
        """Clear all symbols and reset to global scope."""
        self._symbols.clear()
        self._scope_order = ["global"]
        self._current_scope = "global"


# ---------------------------------------------------------------------------
# TypeInferrer
# ---------------------------------------------------------------------------

class TypeInferrer:
    """Infers Python types from AST nodes.

    Analyzes assignment expressions, function calls, type annotations, and
    literal values to determine the type of a Python expression.
    """

    # Mapping of known function return types
    _KNOWN_RETURN_TYPES: Dict[str, str] = {
        "int": "int",
        "float": "float",
        "str": "str",
        "bool": "bool",
        "list": "list",
        "dict": "dict",
        "tuple": "tuple",
        "set": "set",
        "bytes": "bytes",
        "bytearray": "bytearray",
        "range": "range",
        "enumerate": "enumerate",
        "zip": "zip",
        "map": "map",
        "filter": "filter",
        "reversed": "reversed",
        "sorted": "list",
        "iter": "iterator",
        "next": "Any",
        "len": "int",
        "abs": "int | float",
        "sum": "int | float",
        "min": "Any",
        "max": "Any",
        "type": "type",
        "isinstance": "bool",
        "hasattr": "bool",
        "getattr": "Any",
        "open": "file",
        "print": "None",
        "input": "str",
        "format": "str",
        "repr": "str",
        "str": "str",
        "int": "int",
        "float": "float",
        "bool": "bool",
        "list": "list",
        "tuple": "tuple",
        "set": "set",
        "dict": "dict",
        "bytes": "bytes",
        "bytearray": "bytearray",
        "complex": "complex",
        "hex": "str",
        "oct": "str",
        "bin": "str",
        "ord": "int",
        "chr": "str",
        "pow": "int | float",
        "round": "int | float",
        "divmod": "tuple",
    }

    def infer_type(self, node: ast.AST, symbol_table: Optional[SymbolTable] = None) -> Optional[str]:
        """Infer the type of an AST node.

        Args:
            node: The AST node to analyze.
            symbol_table: Optional symbol table for name resolution.

        Returns:
            Inferred type name as a string, or None if inference fails.
        """
        try:
            if isinstance(node, ast.Constant):
                return self._infer_constant(node)
            elif isinstance(node, ast.Name):
                return self._infer_name(node, symbol_table)
            elif isinstance(node, ast.Call):
                return self._infer_call(node, symbol_table)
            elif isinstance(node, ast.BinOp):
                return self._infer_binop(node, symbol_table)
            elif isinstance(node, ast.UnaryOp):
                return self._infer_unaryop(node, symbol_table)
            elif isinstance(node, ast.List):
                return self._infer_list(node, symbol_table)
            elif isinstance(node, ast.Tuple):
                return self._infer_tuple(node, symbol_table)
            elif isinstance(node, ast.Set):
                return "set"
            elif isinstance(node, ast.Dict):
                return "dict"
            elif isinstance(node, ast.Attribute):
                return self._infer_attribute(node, symbol_table)
            elif isinstance(node, ast.Subscript):
                return self._infer_subscript(node, symbol_table)
            elif isinstance(node, ast.Lambda):
                return "Callable"
            elif isinstance(node, ast.ListComp):
                return "list"
            elif isinstance(node, ast.SetComp):
                return "set"
            elif isinstance(node, ast.DictComp):
                return "dict"
            elif isinstance(node, ast.GeneratorExp):
                return "Generator"
            elif isinstance(node, ast.IfExp):
                # Infer from both branches
                body_type = self.infer_type(node.body, symbol_table)
                orelse_type = self.infer_type(node.orelse, symbol_table)
                if body_type and orelse_type and body_type == orelse_type:
                    return body_type
                return body_type or orelse_type or "Any"
            elif isinstance(node, ast.Starred):
                return self.infer_type(node.value, symbol_table)
            elif isinstance(node, ast.Slice):
                return "slice"
            elif isinstance(node, ast.FormattedValue):
                return "str"
            elif isinstance(node, ast.JoinedStr):
                return "str"
            # ast.fstring is not available in all Python versions; JoinedStr handles f-strings
            elif isinstance(node, ast.NamedExpr):
                return self.infer_type(node.value, symbol_table)
            elif isinstance(node, ast.Compare):
                return "bool"
            elif isinstance(node, ast.BoolOp):
                return "bool"
        except Exception:
            logger.debug("Type inference failed for %s", type(node).__name__, exc_info=True)
        return None

    def infer_from_assignment(self, node: ast.Assign, symbol_table: Optional[SymbolTable] = None) -> Optional[str]:
        """Infer the type of a value being assigned.

        Args:
            node: The assignment node.
            symbol_table: Optional symbol table for name resolution.

        Returns:
            Inferred type name, or None.
        """
        return self.infer_type(node.value, symbol_table)

    def infer_from_annotated_assignment(
        self,
        node: ast.AnnAssign,
        symbol_table: Optional[SymbolTable] = None,
    ) -> Optional[str]:
        """Infer the type from an annotated assignment.

        Prioritizes the annotation over the inferred value type.

        Args:
            node: The annotated assignment node.
            symbol_table: Optional symbol table for name resolution.

        Returns:
            Inferred type name, or None.
        """
        # Prefer explicit annotation
        if node.annotation is not None:
            ann_type = self._infer_annotation(node.annotation, symbol_table)
            if ann_type:
                return ann_type

        # Fall back to value inference
        if node.value is not None:
            return self.infer_type(node.value, symbol_table)

        return None

    def _infer_constant(self, node: ast.Constant) -> str:
        """Infer type from a constant literal."""
        value = node.value
        if value is None:
            return "None"
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, complex):
            return "complex"
        if isinstance(value, str):
            return "str"
        if isinstance(value, bytes):
            return "bytes"
        if isinstance(value, bytearray):
            return "bytearray"
        if isinstance(value, type(Ellipsis)):
            return "ellipsis"
        return type(value).__name__

    def _infer_name(
        self,
        node: ast.Name,
        symbol_table: Optional[SymbolTable] = None,
    ) -> Optional[str]:
        """Infer type from a name reference."""
        name = node.id

        # Check built-in type names
        if name in BUILTIN_TYPE_NAMES:
            return BUILTIN_TYPE_NAMES[name]

        # Look up in symbol table
        if symbol_table is not None:
            symbol = symbol_table.get_symbol(name)
            if symbol is not None and symbol.type_name:
                return symbol.type_name

        # Check builtins module
        if hasattr(builtins, name):
            obj = getattr(builtins, name)
            if isinstance(obj, type):
                return "type"
            return type(obj).__name__

        return None

    def _infer_call(
        self,
        node: ast.Call,
        symbol_table: Optional[SymbolTable] = None,
    ) -> Optional[str]:
        """Infer return type from a function call."""
        # Get the function name
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name in self._KNOWN_RETURN_TYPES:
                return self._KNOWN_RETURN_TYPES[func_name]

            # Look up in symbol table
            if symbol_table is not None:
                symbol = symbol_table.get_symbol(func_name)
                if symbol is not None:
                    if symbol.type_name and symbol.type_name != "Callable":
                        return symbol.type_name
                    # If it's a constructor, return the class name
                    if symbol.kind == "class":
                        return func_name
                    return None

            # Check builtins
            if hasattr(builtins, func_name):
                obj = getattr(builtins, func_name)
                if isinstance(obj, type):
                    return func_name  # Constructor returns instance
                return None

        elif isinstance(node.func, ast.Attribute):
            # Method call: obj.method()
            attr_name = node.func.attr
            # Known method return types
            method_returns: Dict[str, str] = {
                "append": "None",
                "extend": "None",
                "pop": "Any",
                "remove": "None",
                "sort": "None",
                "reverse": "None",
                "insert": "None",
                "clear": "None",
                "copy": "list",
                "count": "int",
                "index": "int",
                "keys": "dict_keys",
                "values": "dict_values",
                "items": "dict_items",
                "get": "Any",
                "update": "None",
                "setdefault": "Any",
                "popitem": "tuple",
                "split": "list",
                "join": "str",
                "strip": "str",
                "replace": "str",
                "find": "int",
                "rfind": "int",
                "startswith": "bool",
                "endswith": "bool",
                "format": "str",
                "encode": "bytes",
                "decode": "str",
                "upper": "str",
                "lower": "str",
                "capitalize": "str",
                "title": "str",
                "swapcase": "str",
                "zfill": "str",
            }
            if attr_name in method_returns:
                return method_returns[attr_name]

        # Constructor calls: ClassName(...)
        if isinstance(node.func, ast.Name):
            return node.func.id

        return None

    def _infer_binop(
        self,
        node: ast.BinOp,
        symbol_table: Optional[SymbolTable] = None,
    ) -> Optional[str]:
        """Infer result type from a binary operation."""
        left_type = self.infer_type(node.left, symbol_table)
        right_type = self.infer_type(node.right, symbol_table)

        if isinstance(node.op, ast.Add):
            if left_type == "str" or right_type == "str":
                return "str"
            if left_type in ("int", "float") or right_type in ("int", "float"):
                if left_type == "float" or right_type == "float":
                    return "float"
                return "int"
            if left_type == "list" and right_type == "list":
                return "list"
            if left_type == "tuple" and right_type == "tuple":
                return "tuple"

        if isinstance(node.op, (ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)):
            if left_type == "float" or right_type == "float":
                return "float"
            if left_type == "int" and right_type == "int":
                return "int"
            if isinstance(node.op, ast.FloorDiv):
                return "int"
            if isinstance(node.op, ast.Mod):
                return "int" if left_type == "int" else "str"

        if isinstance(node.op, ast.Pow):
            return "int" if left_type == "int" and right_type == "int" else "float"

        if isinstance(node.op, (ast.LShift, ast.RShift, ast.BitOr, ast.BitXor, ast.BitAnd)):
            return "int"

        if isinstance(node.op, ast.MatMult):
            return "Any"

        return None

    def _infer_unaryop(
        self,
        node: ast.UnaryOp,
        symbol_table: Optional[SymbolTable] = None,
    ) -> Optional[str]:
        """Infer result type from a unary operation."""
        operand_type = self.infer_type(node.operand, symbol_table)
        if isinstance(node.op, (ast.UAdd, ast.USub)):
            return operand_type  # Preserves type
        if isinstance(node.op, ast.Not):
            return "bool"
        if isinstance(node.op, ast.Invert):
            return "int"
        return operand_type

    def _infer_list(
        self,
        node: ast.List,
        symbol_table: Optional[SymbolTable] = None,
    ) -> str:
        """Infer type from a list literal."""
        if not node.elts:
            return "list"
        # Try to infer element type
        elem_types: Set[str] = set()
        for elt in node.elts:
            t = self.infer_type(elt, symbol_table)
            if t:
                elem_types.add(t)
        if len(elem_types) == 1:
            return f"list[{next(iter(elem_types))}]"
        return "list"

    def _infer_tuple(
        self,
        node: ast.Tuple,
        symbol_table: Optional[SymbolTable] = None,
    ) -> str:
        """Infer type from a tuple literal."""
        if not node.elts:
            return "tuple"
        elem_types: List[str] = []
        for elt in node.elts:
            t = self.infer_type(elt, symbol_table)
            elem_types.append(t if t else "Any")
        return f"tuple[{', '.join(elem_types)}]"

    def _infer_attribute(
        self,
        node: ast.Attribute,
        symbol_table: Optional[SymbolTable] = None,
    ) -> Optional[str]:
        """Infer type from an attribute access."""
        # Known module attributes
        if isinstance(node.value, ast.Name):
            if node.value.id == "os" and node.attr == "path":
                return "os.PathLike"
            if node.value.id == "sys":
                return "Any"
            if node.value.id == "re":
                return "re.Pattern" if node.attr == "compile" else "Any"
        return None

    def _infer_subscript(
        self,
        node: ast.Subscript,
        symbol_table: Optional[SymbolTable] = None,
    ) -> Optional[str]:
        """Infer type from a subscript operation (e.g., List[int])."""
        value_type = self.infer_type(node.value, symbol_table)
        if value_type and value_type in ("list", "List"):
            slice_type = self.infer_type(node.slice, symbol_table)
            if slice_type:
                return f"{value_type}[{slice_type}]"
            return value_type
        if value_type and value_type in ("dict", "Dict"):
            return value_type
        if value_type and value_type in ("tuple", "Tuple"):
            return value_type
        if value_type and value_type in ("Optional", "Union"):
            slice_type = self.infer_type(node.slice, symbol_table)
            if slice_type:
                return f"{value_type}[{slice_type}]"
            return value_type
        return value_type

    def _infer_annotation(
        self,
        node: ast.AST,
        symbol_table: Optional[SymbolTable] = None,
    ) -> Optional[str]:
        """Infer type from a type annotation node."""
        if isinstance(node, ast.Name):
            name = node.id
            if name in BUILTIN_TYPE_NAMES:
                return BUILTIN_TYPE_NAMES[name]
            return name
        if isinstance(node, ast.Subscript):
            # Generic type like List[int], Dict[str, Any]
            value_type = self._infer_annotation(node.value, symbol_table)
            slice_type = self._infer_annotation(node.slice, symbol_table)
            if value_type and slice_type:
                return f"{value_type}[{slice_type}]"
            return value_type
        if isinstance(node, ast.Attribute):
            # Qualified name like typing.List
            if isinstance(node.value, ast.Name):
                return f"{node.value.id}.{node.attr}"
            return node.attr
        if isinstance(node, ast.Constant):
            return str(node.value) if node.value is not None else None
        if isinstance(node, ast.Tuple):
            # Tuple of types
            types: List[str] = []
            for elt in node.elts:
                t = self._infer_annotation(elt, symbol_table)
                if t:
                    types.append(t)
            if types:
                return f"tuple[{', '.join(types)}]"
            return "tuple"
        if isinstance(node, ast.List):
            types = []
            for elt in node.elts:
                t = self._infer_annotation(elt, symbol_table)
                if t:
                    types.append(t)
            if types:
                return f"list[{', '.join(types)}]"
            return "list"
        return None


# ---------------------------------------------------------------------------
# CodeContext
# ---------------------------------------------------------------------------

@dataclass
class CodeContext:
    """Describes the code context at a cursor position.

    Captures the syntactic and semantic context around the cursor to
    enable context-aware completions.

    Attributes:
        scope_type: Type of scope ('module', 'function', 'class', 'method',
                    'lambda').
        scope_name: Name of the enclosing scope.
        line: Cursor line number (0-based).
        column: Cursor column number (0-based).
        prefix: Text before the cursor on the current line (for filtering).
        trigger_word: The word being completed (e.g., object name before dot).
        trigger_kind: Trigger type ('dot', 'import', 'path', 'general',
                     'keyword', 'decorator').
        inside_function: Whether the cursor is inside a function body.
        inside_class: Whether the cursor is inside a class body.
        inside_loop: Whether the cursor is inside a loop body.
        inside_try: Whether the cursor is inside a try/except block.
        inside_string: Whether the cursor is inside a string literal.
        inside_comment: Whether the cursor is inside a comment.
        indentation: Current indentation level (in spaces).
        available_names: Set of names visible from this context.
        imports: Mapping of imported names to their module paths.
    """

    scope_type: str = "module"
    scope_name: str = "<module>"
    line: int = 0
    column: int = 0
    prefix: str = ""
    trigger_word: Optional[str] = None
    trigger_kind: str = "general"
    inside_function: bool = False
    inside_class: bool = False
    inside_loop: bool = False
    inside_try: bool = False
    inside_string: bool = False
    inside_comment: bool = False
    indentation: int = 0
    available_names: Set[str] = field(default_factory=set)
    imports: Dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ContextAnalyzer
# ---------------------------------------------------------------------------

class ContextAnalyzer:
    """Analyzes Python source code to determine the context at a cursor position.

    Parses the source code and walks the AST to determine the syntactic
    context, available symbols, and trigger type for code completions.
    """

    def __init__(self) -> None:
        self._source: str = ""
        self._lines: List[str] = []
        self._tree: Optional[ast.AST] = None
        self._parse_error: Optional[str] = None

    def analyze(self, source: str, line: int, column: int) -> CodeContext:
        """Analyze the source code at the given cursor position.

        Args:
            source: The full source code text.
            line: Cursor line number (0-based).
            column: Cursor column number (0-based).

        Returns:
            A CodeContext describing the context at the cursor.
        """
        self._source = source
        self._lines = source.splitlines(keepends=True)
        context = CodeContext(
            line=line,
            column=column,
        )

        try:
            self._tree = ast.parse(source, mode="exec")
            self._parse_error = None
        except SyntaxError as e:
            self._parse_error = str(e)
            self._tree = None

        # Determine indentation at cursor
        context.indentation = self._get_indentation(line)

        # Check if inside string or comment
        context.inside_string, context.inside_comment = self._check_string_comment(line, column)

        # Determine trigger kind and prefix
        context.trigger_kind, context.trigger_word, context.prefix = self._find_trigger(
            line, column
        )

        # If inside a string and it looks like a path, set trigger to path
        if context.inside_string and self._looks_like_path(context.prefix):
            context.trigger_kind = "path"
            context.trigger_word = context.prefix

        # Walk the AST to determine scope and collect symbols
        if self._tree is not None:
            self._analyze_ast(context)

        # Collect imports and available names
        context.imports = self._extract_imports()
        context.available_names = self._collect_available_names(context)

        return context

    def _get_indentation(self, line: int) -> int:
        """Get the indentation level of a line (in spaces)."""
        if line < 0 or line >= len(self._lines):
            return 0
        line_text = self._lines[line]
        stripped = line_text.lstrip()
        if stripped == "" or stripped.startswith("#"):
            # Use the line's indentation
            return len(line_text) - len(line_text.lstrip())
        return len(line_text) - len(stripped)

    def _check_string_comment(
        self,
        line: int,
        column: int,
    ) -> Tuple[bool, bool]:
        """Check if the cursor is inside a string literal or comment.

        Uses token-based analysis for accurate detection.

        Args:
            line: Cursor line.
            column: Cursor column.

        Returns:
            Tuple of (inside_string, inside_comment).
        """
        try:
            if not self._source.strip():
                return False, False

            tokens = list(tokenize.generate_tokens(
                iter(self._lines).__next__ if self._lines else iter([]).__next__
            ))

            for token in tokens:
                start_line, start_col = token.start
                end_line, end_col = token.end
                tok_type = token.type
                tok_string = token.string

                # Check if cursor is inside this token
                if start_line == line + 1 and start_col <= column:
                    if end_line == line + 1 and end_col >= column:
                        if tok_type == tokenize.STRING:
                            return True, False
                        if tok_type == tokenize.COMMENT:
                            return False, True
                        if tok_type == tokenize.OP and tok_string in ("'''", '"""', "'", '"'):
                            return True, False
        except Exception:
            pass

        # Fallback: simple text-based check
        if 0 <= line < len(self._lines):
            line_text = self._lines[line]
            # Check if we're in a comment
            comment_pos = line_text.find("#")
            if comment_pos != -1 and comment_pos < column:
                return False, True

        return False, False

    def _find_trigger(
        self,
        line: int,
        column: int,
    ) -> Tuple[str, Optional[str], str]:
        """Determine the completion trigger kind, word, and prefix.

        Analyzes the text before the cursor to determine whether the user
        is triggering a dot completion, import completion, path completion,
        or general completion.

        Args:
            line: Cursor line (0-based).
            column: Cursor column (0-based).

        Returns:
            Tuple of (trigger_kind, trigger_word, prefix).
        """
        if line < 0 or line >= len(self._lines):
            return "general", None, ""

        line_text = self._lines[line]
        # Text before cursor on this line
        before_cursor = line_text[:column]

        # Check for decorator: @prefix
        stripped = before_cursor.lstrip()
        if stripped.startswith("@"):
            word = stripped[1:].rstrip()
            return "decorator", word, word

        # Check for dot completion: obj.attr
        dot_match = re.search(r"(\w+(?:\.\w+)*)\.$", before_cursor.rstrip())
        if dot_match:
            word = dot_match.group(1)
            return "dot", word, ""

        # Check for dot completion with partial: obj.attr
        dot_match_partial = re.search(r"(\w+(?:\.\w+)*)\.(\w*)$", before_cursor.rstrip())
        if dot_match_partial:
            word = dot_match_partial.group(1)
            prefix = dot_match_partial.group(2)
            return "dot", word, prefix

        # Check for import statement
        import_match = re.search(
            r"(?:^|;)\s*import\s+(\w*(?:\.\w*)*)\s*$",
            before_cursor,
        )
        if import_match:
            word = import_match.group(1)
            return "import", word, word

        # Check for from ... import statement
        from_match = re.search(
            r"(?:^|;)\s*from\s+(\w+(?:\.\w+)*)\s+import\s+(\w*)$",
            before_cursor,
        )
        if from_match:
            word = from_match.group(2)
            return "import", word, word

        # Check for import after 'import' keyword
        import_word_match = re.search(
            r"(?:^|;)\s*import\s+(\w*)$",
            before_cursor,
        )
        if import_word_match:
            word = import_word_match.group(1)
            return "import", word, word

        # Check for from ... import
        from_word_match = re.search(
            r"(?:^|;)\s*from\s+(\w+(?:\.\w+)*)\s+import\s+(\w*)$",
            before_cursor,
        )
        if from_word_match:
            word = from_word_match.group(2)
            return "import", word, word

        # Check for import after 'from'
        from_module_match = re.search(
            r"(?:^|;)\s*from\s+(\w*)$",
            before_cursor,
        )
        if from_module_match:
            word = from_module_match.group(1)
            return "import", word, word

        # Check for path prefix in string
        path_match = re.search(
            r'["\']([^"\']*)$',
            before_cursor,
        )
        if path_match:
            word = path_match.group(1)
            if self._looks_like_path(word):
                return "path", word, word

        # General completion: extract the word being typed
        word_match = re.search(r"(\w+)$", before_cursor)
        if word_match:
            prefix = word_match.group(1)
            return "general", prefix, prefix

        return "general", None, ""

    def _looks_like_path(self, text: str) -> bool:
        """Check if text looks like a file path."""
        if not text:
            return False
        # Check for path separators
        if "/" in text or "\\" in text:
            return True
        # Check for common path patterns
        if text.startswith(".") or text.startswith("~"):
            return True
        # Check for drive letter (Windows)
        if re.match(r"^[a-zA-Z]:\\", text):
            return True
        # Check if it ends with a common file extension
        if re.search(r"\.\w{1,5}$", text):
            return True
        return False

    def _analyze_ast(self, context: CodeContext) -> None:
        """Walk the AST to determine scope and context at the cursor position.

        Traverses the AST depth-first, tracking scope entries and exits
        to find the innermost scope containing the cursor.

        Args:
            context: The CodeContext to populate.
        """
        if self._tree is None:
            return

        cursor_line = context.line + 1  # ast uses 1-based line numbers

        # Walk the AST nodes
        for node in ast.walk(self._tree):
            node_line = getattr(node, "lineno", None)
            node_end_line = getattr(node, "end_lineno", None)

            if node_line is None:
                continue

            if node_line <= cursor_line <= (node_end_line or node_line):
                if isinstance(node, ast.FunctionDef):
                    context.scope_type = "method" if context.inside_class else "function"
                    context.scope_name = node.name
                    context.inside_function = True
                elif isinstance(node, ast.AsyncFunctionDef):
                    context.scope_type = "method" if context.inside_class else "function"
                    context.scope_name = node.name
                    context.inside_function = True
                elif isinstance(node, ast.ClassDef):
                    context.scope_type = "class"
                    context.scope_name = node.name
                    context.inside_class = True
                elif isinstance(node, ast.For) or isinstance(node, ast.AsyncFor):
                    context.inside_loop = True
                elif isinstance(node, ast.While):
                    context.inside_loop = True
                elif isinstance(node, ast.Try):
                    context.inside_try = True
                elif isinstance(node, ast.Lambda):
                    context.inside_function = True

    def _extract_imports(self) -> Dict[str, str]:
        """Extract all import statements from the source code.

        Returns:
            Mapping of imported names to their full module paths.
        """
        imports: Dict[str, str] = {}
        if self._tree is None:
            return imports

        for node in ast.walk(self._tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name
                    imports[name] = alias.name
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    name = alias.asname or alias.name
                    imports[name] = f"{module}.{alias.name}" if module else alias.name

        return imports

    def _collect_available_names(self, context: CodeContext) -> Set[str]:
        """Collect all names available from the current context.

        Includes builtins, imported names, and names from the current scope.

        Args:
            context: The current code context.

        Returns:
            Set of available names.
        """
        names: Set[str] = set()

        # Built-in names
        names.update(dir(builtins))

        # Imported names
        names.update(context.imports.keys())

        # Names from the AST (if available)
        if self._tree is not None:
            for node in ast.walk(self._tree):
                if isinstance(node, ast.FunctionDef):
                    names.add(node.name)
                elif isinstance(node, ast.AsyncFunctionDef):
                    names.add(node.name)
                elif isinstance(node, ast.ClassDef):
                    names.add(node.name)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            names.add(target.id)
                        elif isinstance(target, ast.Tuple) or isinstance(target, ast.List):
                            for elt in target.elts:
                                if isinstance(elt, ast.Name):
                                    names.add(elt.id)
                elif isinstance(node, ast.AnnAssign):
                    if isinstance(node.target, ast.Name):
                        names.add(node.target.id)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        names.add(alias.asname or alias.name)
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        names.add(alias.asname or alias.name)

        return names


# ---------------------------------------------------------------------------
# PriorityScorer
# ---------------------------------------------------------------------------

class PriorityScorer:
    """Scores and ranks completion items by relevance.

    Uses a multi-factor scoring system that considers exact matches,
    prefix matches, scope proximity, type consistency, and other
    heuristics to rank completion candidates.
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None) -> None:
        """Initialize the scorer.

        Args:
            weights: Optional custom weight dictionary. Falls back to
                     SCORE_WEIGHTS if not provided.
        """
        self._weights = SCORE_WEIGHTS.copy()
        if weights is not None:
            self._weights.update(weights)

    def score(
        self,
        item: CompletionItem,
        context: CodeContext,
        prefix: str = "",
    ) -> float:
        """Compute a relevance score for a completion item.

        Args:
            item: The completion item to score.
            context: The current code context.
            prefix: The user's current input prefix.

        Returns:
            A relevance score (higher = more relevant).
        """
        score = 0.0

        # Exact match bonus
        if prefix and item.label == prefix:
            score += self._weights["exact_match"]

        # Prefix match bonus
        if prefix and item.label.startswith(prefix):
            score += self._weights["prefix_match"] * (len(prefix) / len(item.label))

        # Substring match bonus
        if prefix and prefix in item.label and not item.label.startswith(prefix):
            score += self._weights["substring_match"] * (len(prefix) / len(item.label))

        # Case-insensitive match bonus
        if prefix and item.label.lower().startswith(prefix.lower()):
            score += self._weights["prefix_match"] * 0.5

        # Scope bonus: prefer local over global
        if context.inside_function and item.kind in (
            CompletionItemKind.VARIABLE,
            CompletionItemKind.FUNCTION,
        ):
            score += self._weights["scope_match"]

        # Type match bonus (for dot completions)
        if context.trigger_kind == "dot" and context.trigger_word:
            score += self._weights["type_match"]

        # Keyword bonus
        if item.kind == CompletionItemKind.KEYWORD:
            score += self._weights["keyword"]

        # Snippet bonus
        if item.kind == CompletionItemKind.SNIPPET:
            score += self._weights["snippet"]

        # Builtin penalty
        if item.kind == CompletionItemKind.KEYWORD:
            pass  # Keywords are handled separately

        # Boost for exact kind match
        if context.trigger_kind == "import" and item.kind == CompletionItemKind.MODULE:
            score += self._weights["module_match"]

        if context.trigger_kind == "general" and item.kind == CompletionItemKind.VARIABLE:
            score += self._weights["local_var"]

        # Preselect boost
        if item.preselect:
            score += 20.0

        # Module match boost
        if (
            context.trigger_kind == "import"
            and item.kind == CompletionItemKind.MODULE
            and prefix
            and item.label.startswith(prefix)
        ):
            score += self._weights["module_match"]

        # Store the score on the item
        item.score = score

        return score

    def rank(
        self,
        items: List[CompletionItem],
        context: CodeContext,
        prefix: str = "",
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> List[CompletionItem]:
        """Score and rank a list of completion items.

        Args:
            items: The items to rank.
            context: The current code context.
            prefix: The user's current input prefix.
            max_results: Maximum number of results to return.

        Returns:
            Ranked list of completion items, sorted by score descending.
        """
        for item in items:
            self.score(item, context, prefix)

        # Sort by score descending
        items.sort(key=lambda x: (-x.score, x.label))

        # Return top N
        return items[:max_results]


# ---------------------------------------------------------------------------
# CompletionCache
# ---------------------------------------------------------------------------

class CompletionCache:
    """Caches completion results to improve performance.

    Uses a time-to-live (TTL) cache that automatically expires entries
    after a configurable period. The cache is keyed by a hash of the
    source code and cursor position.
    """

    def __init__(self, max_size: int = DEFAULT_CACHE_SIZE, ttl: int = DEFAULT_CACHE_TTL) -> None:
        """Initialize the cache.

        Args:
            max_size: Maximum number of cache entries.
            ttl: Time-to-live in seconds for cache entries.
        """
        self._max_size = max_size
        self._ttl = ttl
        self._cache: Dict[str, Tuple[List[CompletionItem], float]] = {}
        self._access_order: List[str] = []
        self._hits: int = 0
        self._misses: int = 0

    def get(self, key: str) -> Optional[List[CompletionItem]]:
        """Retrieve cached results for a key.

        Args:
            key: The cache key.

        Returns:
            Cached completion items if found and not expired, None otherwise.
        """
        if key not in self._cache:
            self._misses += 1
            return None

        items, timestamp = self._cache[key]
        if time.time() - timestamp > self._ttl:
            # Expired
            del self._cache[key]
            if key in self._access_order:
                self._access_order.remove(key)
            self._misses += 1
            return None

        # Move to end of access order (LRU)
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)

        self._hits += 1
        return items

    def set(self, key: str, items: List[CompletionItem]) -> None:
        """Store results in the cache.

        Args:
            key: The cache key.
            items: The completion items to cache.
        """
        # Evict oldest entries if at capacity
        while len(self._cache) >= self._max_size:
            if self._access_order:
                oldest = self._access_order.pop(0)
                if oldest in self._cache:
                    del self._cache[oldest]

        self._cache[key] = (items, time.time())
        if key not in self._access_order:
            self._access_order.append(key)

    def invalidate(self, key: Optional[str] = None) -> None:
        """Invalidate cache entries.

        Args:
            key: Specific key to invalidate. If None, invalidates all
                 entries related to the source (keys starting with known
                 patterns). If '*', clears the entire cache.
        """
        if key is None:
            return

        if key == "*":
            self.clear()
            return

        if key in self._cache:
            del self._cache[key]
            if key in self._access_order:
                self._access_order.remove(key)

    def clear(self) -> None:
        """Clear the entire cache."""
        self._cache.clear()
        self._access_order.clear()
        self._hits = 0
        self._misses = 0

    @property
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache size, hits, misses, and hit rate.
        """
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0.0,
        }

    @staticmethod
    def make_key(source: str, line: int, column: int) -> str:
        """Generate a cache key from source code and cursor position.

        Args:
            source: The source code.
            line: Cursor line (0-based).
            column: Cursor column (0-based).

        Returns:
            A hash string for cache lookup.
        """
        # Use a simple hash for speed
        import hashlib
        content = f"{hash(source)}:{line}:{column}"
        return hashlib.md5(content.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# SnippetProvider
# ---------------------------------------------------------------------------

class SnippetProvider:
    """Provides code snippet completions for common Python patterns.

    Snippets use the VSCode/TextMate snippet syntax with placeholders
    ($1, $2, ..., $0 for final cursor position).
    """

    def __init__(self) -> None:
        self._snippets: List[CompletionItem] = []
        self._initialize_snippets()

    def _initialize_snippets(self) -> None:
        """Build the list of available Python snippets."""
        self._snippets = [
            CompletionItem.snippet(
                "def",
                "def ${1:name}(${2:params}):\n    ${0:pass}",
                "Function definition",
            ),
            CompletionItem.snippet(
                "async def",
                "async def ${1:name}(${2:params}):\n    ${0:pass}",
                "Async function definition",
            ),
            CompletionItem.snippet(
                "class",
                "class ${1:Name}(${2:object}):\n    ${3:def __init__(self):\n        ${0:pass}}",
                "Class definition",
            ),
            CompletionItem.snippet(
                "if",
                "if ${1:condition}:\n    ${0:pass}",
                "If statement",
            ),
            CompletionItem.snippet(
                "elif",
                "elif ${1:condition}:\n    ${0:pass}",
                "Else if statement",
            ),
            CompletionItem.snippet(
                "else",
                "else:\n    ${0:pass}",
                "Else statement",
            ),
            CompletionItem.snippet(
                "for",
                "for ${1:item} in ${2:iterable}:\n    ${0:pass}",
                "For loop",
            ),
            CompletionItem.snippet(
                "async for",
                "async for ${1:item} in ${2:iterable}:\n    ${0:pass}",
                "Async for loop",
            ),
            CompletionItem.snippet(
                "while",
                "while ${1:condition}:\n    ${0:pass}",
                "While loop",
            ),
            CompletionItem.snippet(
                "with",
                "with ${1:context} as ${2:name}:\n    ${0:pass}",
                "With statement (context manager)",
            ),
            CompletionItem.snippet(
                "async with",
                "async with ${1:context} as ${2:name}:\n    ${0:pass}",
                "Async with statement",
            ),
            CompletionItem.snippet(
                "try",
                "try:\n    ${1:pass}\nexcept ${2:Exception} as ${3:e}:\n    ${0:pass}",
                "Try/except block",
            ),
            CompletionItem.snippet(
                "except",
                "except ${1:Exception} as ${2:e}:\n    ${0:pass}",
                "Except clause",
            ),
            CompletionItem.snippet(
                "finally",
                "finally:\n    ${0:pass}",
                "Finally clause",
            ),
            CompletionItem.snippet(
                "ifmain",
                'if __name__ == "__main__":\n    ${0:main()}',
                "Main guard",
            ),
            CompletionItem.snippet(
                "main",
                'def main() -> None:\n    ${0:pass}\n\n\nif __name__ == "__main__":\n    main()',
                "Main function template",
            ),
            CompletionItem.snippet(
                "lambda",
                "lambda ${1:args}: ${0:expr}",
                "Lambda expression",
            ),
            CompletionItem.snippet(
                "list comprehension",
                "[${1:expr} for ${2:item} in ${3:iterable}]",
                "List comprehension",
            ),
            CompletionItem.snippet(
                "dict comprehension",
                "{${1:key}: ${2:value} for ${3:item} in ${4:iterable}}",
                "Dict comprehension",
            ),
            CompletionItem.snippet(
                "set comprehension",
                "{${1:expr} for ${2:item} in ${3:iterable}}",
                "Set comprehension",
            ),
            CompletionItem.snippet(
                "generator",
                "(${1:expr} for ${2:item} in ${3:iterable})",
                "Generator expression",
            ),
            CompletionItem.snippet(
                "property",
                "@property\ndef ${1:name}(self) -> ${2:type}:\n    return ${0:self._${1}}",
                "Property decorator",
            ),
            CompletionItem.snippet(
                "staticmethod",
                "@staticmethod\ndef ${1:name}(${2:args}) -> ${3:type}:\n    ${0:pass}",
                "Static method decorator",
            ),
            CompletionItem.snippet(
                "classmethod",
                "@classmethod\ndef ${1:name}(cls, ${2:args}) -> ${3:type}:\n    ${0:pass}",
                "Class method decorator",
            ),
            CompletionItem.snippet(
                "init",
                "def __init__(self, ${1:args}) -> None:\n    ${0:pass}",
                "Constructor method",
            ),
            CompletionItem.snippet(
                "str",
                "def __str__(self) -> str:\n    return ${0:repr(self)}",
                "__str__ method",
            ),
            CompletionItem.snippet(
                "repr",
                "def __repr__(self) -> str:\n    return ${0:repr(self)}",
                "__repr__ method",
            ),
            CompletionItem.snippet(
                "import",
                "import ${1:module}",
                "Import statement",
            ),
            CompletionItem.snippet(
                "from",
                "from ${1:module} import ${2:name}",
                "From import statement",
            ),
            CompletionItem.snippet(
                "print",
                "print(${1:value})",
                "Print function call",
            ),
            CompletionItem.snippet(
                "isinstance",
                "isinstance(${1:obj}, ${2:type})",
                "Isinstance check",
            ),
            CompletionItem.snippet(
                "enumerate",
                "enumerate(${1:iterable})",
                "Enumerate function",
            ),
            CompletionItem.snippet(
                "zip",
                "zip(${1:iterable1}, ${2:iterable2})",
                "Zip function",
            ),
            CompletionItem.snippet(
                "dataclass",
                "@dataclass\nclass ${1:Name}:\n    ${2:field}: ${3:type}\n\n    ${0:pass}",
                "Dataclass definition",
            ),
        ]

    def get_snippets(self, context: CodeContext) -> List[CompletionItem]:
        """Get relevant snippets for the current context.

        Filters snippets based on the current scope and context.

        Args:
            context: The current code context.

        Returns:
            List of relevant snippet completion items.
        """
        results: List[CompletionItem] = []

        # Filter snippets by context
        for snippet in self._snippets:
            label = snippet.label

            # Inside a class, don't suggest 'def' (use 'method' instead)
            # but do suggest __init__ and property methods
            if context.inside_class:
                if label in ("def", "class", "ifmain", "main", "lambda"):
                    # Still include basic snippets
                    results.append(snippet)
                    continue
                # Include class-specific snippets
                if label in ("init", "property", "staticmethod", "classmethod", "str", "repr"):
                    results.append(snippet)
                    continue
                # Include control flow
                if label in ("if", "for", "while", "try", "with"):
                    results.append(snippet)
                    continue
                # Include dataclass only at module level
                if label == "dataclass":
                    continue
                results.append(snippet)
            elif context.inside_function:
                # Inside a function, exclude class-level snippets
                if label in ("class", "ifmain", "main", "dataclass", "property",
                             "staticmethod", "classmethod", "init", "str", "repr"):
                    continue
                results.append(snippet)
            else:
                # Module level: include everything
                results.append(snippet)

        return results


# ---------------------------------------------------------------------------
# KeywordCompleter
# ---------------------------------------------------------------------------

class KeywordCompleter:
    """Provides Python keyword completions.

    Returns Python keywords that are valid in the current context,
    filtered by whether the keyword is usable in expression or
    statement position.
    """

    # Python keywords organized by category
    STATEMENT_KEYWORDS: List[str] = [
        "def", "class", "return", "yield", "raise", "pass", "break",
        "continue", "import", "from", "as", "global", "nonlocal",
        "del", "assert", "with", "if", "elif", "else", "for",
        "while", "try", "except", "finally", "async", "await",
    ]

    EXPRESSION_KEYWORDS: List[str] = [
        "True", "False", "None", "and", "or", "not", "in", "is",
        "lambda",
    ]

    SOFT_KEYWORDS: List[str] = [
        "_", "match", "case",  # Python 3.10+
    ]

    def __init__(self) -> None:
        self._keywords: Dict[str, Optional[str]] = {}
        self._initialize_keywords()

    def _initialize_keywords(self) -> None:
        """Build the keyword documentation map."""
        kw_docs: Dict[str, str] = {
            "False": "Boolean false value",
            "None": "The null value",
            "True": "Boolean true value",
            "and": "Logical and operator",
            "as": "Alias in import/with statements",
            "assert": "Assertion check",
            "async": "Async/await syntax",
            "await": "Await coroutine",
            "break": "Break out of loop",
            "class": "Class definition",
            "continue": "Continue to next loop iteration",
            "def": "Function definition",
            "del": "Delete a variable",
            "elif": "Else if condition",
            "else": "Else condition or loop else",
            "except": "Except clause in try block",
            "finally": "Finally clause in try block",
            "for": "For loop",
            "from": "Import from module",
            "global": "Declare global variable",
            "if": "If condition",
            "import": "Import module",
            "in": "Membership test",
            "is": "Identity test",
            "lambda": "Lambda expression",
            "nonlocal": "Declare nonlocal variable",
            "not": "Logical not operator",
            "or": "Logical or operator",
            "pass": "No-op statement",
            "raise": "Raise exception",
            "return": "Return from function",
            "try": "Try block for exception handling",
            "while": "While loop",
            "with": "Context manager statement",
            "yield": "Yield from generator",
        }

        for kw in keyword.kwlist:
            self._keywords[kw] = kw_docs.get(kw)

        # Add soft keywords
        for kw in self.SOFT_KEYWORDS:
            if kw not in self._keywords:
                self._keywords[kw] = None

    def get_completions(self, context: CodeContext, prefix: str = "") -> List[CompletionItem]:
        """Get keyword completions relevant to the current context.

        Args:
            context: The current code context.
            prefix: The current input prefix for filtering.

        Returns:
            List of keyword completion items.
        """
        results: List[CompletionItem] = []

        for kw, doc in self._keywords.items():
            # Filter by prefix
            if prefix and not kw.startswith(prefix):
                continue

            # At module level, exclude 'return', 'yield', 'break', 'continue',
            # 'nonlocal' (these are invalid outside functions)
            if not context.inside_function and not context.inside_class:
                if kw in ("return", "yield", "break", "continue", "nonlocal", "await"):
                    continue

            # Inside a class but not in a method, exclude some keywords
            if context.inside_class and not context.inside_function:
                if kw in ("return", "yield", "break", "continue", "nonlocal"):
                    continue

            results.append(CompletionItem.keyword(kw, documentation=doc))

        return results


# ---------------------------------------------------------------------------
# VariableCompleter
# ---------------------------------------------------------------------------

class VariableCompleter:
    """Provides variable name completions from the symbol table.

    Returns variables, parameters, and constants visible from the
    current scope.
    """

    def __init__(
        self,
        symbol_table: SymbolTable,
        type_inferrer: TypeInferrer,
    ) -> None:
        """Initialize the variable completer.

        Args:
            symbol_table: The symbol table for symbol lookup.
            type_inferrer: The type inferrer for type information.
        """
        self._symbol_table = symbol_table
        self._type_inferrer = type_inferrer

    def get_completions(self, context: CodeContext, prefix: str = "") -> List[CompletionItem]:
        """Get variable completions for the current context.

        Args:
            context: The current code context.
            prefix: The current input prefix.

        Returns:
            List of variable completion items.
        """
        results: List[CompletionItem] = []

        # Get all symbols from the symbol table
        for symbol in self._symbol_table.get_all_symbols():
            if symbol.kind not in ("variable", "parameter", "attribute", "builtin"):
                continue

            # Filter by prefix
            if prefix and not symbol.name.startswith(prefix):
                continue

            # Filter by context
            if not self._is_visible(symbol, context):
                continue

            results.append(CompletionItem.variable(
                name=symbol.name,
                type_name=symbol.type_name,
                documentation=symbol.docstring,
            ))

        # Also add built-in names that look like variables
        builtin_names = dir(builtins)
        for name in builtin_names:
            if prefix and not name.startswith(prefix):
                continue
            if name.startswith("_"):
                continue
            # Skip if already in symbol table
            if self._symbol_table.get_symbol(name) is not None:
                continue
            obj = getattr(builtins, name, None)
            if obj is None:
                continue
            # Skip types and functions (handled by other completers)
            if isinstance(obj, type):
                continue
            if callable(obj):
                continue
            results.append(CompletionItem.variable(
                name=name,
                type_name=type(obj).__name__ if not isinstance(obj, type) else None,
            ))

        return results

    def _is_visible(self, symbol: Symbol, context: CodeContext) -> bool:
        """Check if a symbol is visible from the current context.

        Args:
            symbol: The symbol to check.
            context: The current code context.

        Returns:
            True if the symbol is visible.
        """
        # Builtins are always visible
        if symbol.scope == "builtin":
            return True

        # Global symbols are visible everywhere
        if symbol.scope == "global":
            return True

        # Symbols in the current scope are visible
        if symbol.scope == self._symbol_table.current_scope:
            return True

        # Check if the symbol is in a parent scope
        current_parts = self._symbol_table.current_scope.split(":")
        symbol_parts = symbol.scope.split(":")
        for i in range(len(current_parts)):
            if ":".join(current_parts[:i + 1]) == symbol.scope:
                return True

        return False


# ---------------------------------------------------------------------------
# FunctionCompleter
# ---------------------------------------------------------------------------

class FunctionCompleter:
    """Provides function/method call completions with signature help.

    Returns function and method definitions from the symbol table and
    builtins, with signature information for call completion.
    """

    def __init__(
        self,
        symbol_table: SymbolTable,
        type_inferrer: TypeInferrer,
    ) -> None:
        """Initialize the function completer.

        Args:
            symbol_table: The symbol table for symbol lookup.
            type_inferrer: The type inferrer for return type inference.
        """
        self._symbol_table = symbol_table
        self._type_inferrer = type_inferrer

    def get_completions(self, context: CodeContext, prefix: str = "") -> List[CompletionItem]:
        """Get function completion items for the current context.

        Args:
            context: The current code context.
            prefix: The current input prefix.

        Returns:
            List of function completion items.
        """
        results: List[CompletionItem] = []

        # Get function symbols from the symbol table
        for symbol in self._symbol_table.get_all_symbols():
            if symbol.kind not in ("function", "method", "builtin"):
                continue

            # Filter by prefix
            if prefix and not symbol.name.startswith(prefix):
                continue

            # Generate signature
            signature = self._format_signature(symbol)
            results.append(CompletionItem.function(
                name=symbol.name,
                signature=signature,
                documentation=symbol.docstring,
            ))

        # Add built-in callables
        builtin_names = dir(builtins)
        for name in builtin_names:
            if prefix and not name.startswith(prefix):
                continue
            if name.startswith("_"):
                continue
            if self._symbol_table.get_symbol(name) is not None:
                continue
            obj = getattr(builtins, name, None)
            if obj is None:
                continue
            if not callable(obj):
                continue
            if isinstance(obj, type):
                continue  # Handled by ClassCompleter
            # Build signature
            sig = self._format_builtin_signature(name, obj)
            results.append(CompletionItem.function(
                name=name,
                signature=sig,
            ))

        return results

    def get_signature_help(
        self,
        source: str,
        line: int,
        column: int,
    ) -> Optional[SignatureInfo]:
        """Get signature help for a function call at the cursor position.

        Analyzes the text before the cursor to find a function call and
        returns its signature information.

        Args:
            source: The full source code.
            line: Cursor line (0-based).
            column: Cursor column (0-based).

        Returns:
            SignatureInfo if a function call is found, None otherwise.
        """
        lines = source.splitlines()
        if line >= len(lines):
            return None

        # Get text before cursor
        before_cursor = lines[line][:column]

        # Find the last opening parenthesis
        paren_pos = before_cursor.rfind("(")
        if paren_pos == -1:
            # Try to find if there's a '(' on previous lines
            # (multi-line function call)
            for l in range(line - 1, -1, -1):
                paren_pos = lines[l].rfind("(")
                if paren_pos != -1:
                    before_cursor = lines[l][:paren_pos + 1] + "\n" + before_cursor
                    break

        if paren_pos == -1:
            return None

        # Extract the function name before the '('
        text_before_paren = before_cursor[:paren_pos].rstrip()
        func_match = re.search(r"(\w+(?:\.\w+)*)\s*$", text_before_paren)
        if not func_match:
            return None

        func_name = func_match.group(1)

        # Count parameters (commas after the last '(')
        text_after_paren = before_cursor[paren_pos + 1:]
        # Simple count: commas at the top level
        param_count = 0
        depth = 0
        for ch in text_after_paren:
            if ch in "({[":
                depth += 1
            elif ch in ")}]":
                depth -= 1
            elif ch == "," and depth == 0:
                param_count += 1

        # Look up the function
        symbol = self._symbol_table.get_symbol(func_name.split(".")[0])
        if symbol is None:
            return None

        if symbol.kind not in ("function", "method", "builtin"):
            return None

        params = symbol.parameters if symbol.parameters else []

        signature = self._format_signature(symbol)
        return SignatureInfo(
            name=func_name,
            label=signature,
            parameters=params,
            active_parameter=min(param_count, len(params) - 1) if params else 0,
            documentation=symbol.docstring,
        )

    def _format_signature(self, symbol: Symbol) -> str:
        """Format a symbol's signature as a string.

        Args:
            symbol: The symbol to format.

        Returns:
            Formatted signature string.
        """
        params = symbol.parameters if symbol.parameters else ["..."]
        param_str = ", ".join(params)
        if symbol.type_name and symbol.type_name != "Callable":
            return f"({param_str}) -> {symbol.type_name}"
        return f"({param_str})"

    def _format_builtin_signature(self, name: str, obj: Callable[..., Any]) -> str:
        """Format a built-in function's signature.

        Args:
            name: The function name.
            obj: The built-in function object.

        Returns:
            Formatted signature string.
        """
        try:
            import inspect
            sig = inspect.signature(obj)
            param_str = str(sig)[1:-1]  # Remove parentheses
            if param_str:
                return f"({param_str})"
        except (ValueError, TypeError):
            pass
        return "(...)"
        # ---

# ---------------------------------------------------------------------------
# ClassCompleter
# ---------------------------------------------------------------------------

class ClassCompleter:
    """Provides class and attribute completions.

    Returns class definitions from the symbol table and builtins, with
    support for attribute completions after a dot access.
    """

    # Common special methods and their descriptions
    SPECIAL_METHODS: Dict[str, str] = {
        "__init__": "Initialize instance",
        "__str__": "String representation",
        "__repr__": "Debug representation",
        "__len__": "Length",
        "__getitem__": "Index access",
        "__setitem__": "Index assignment",
        "__delitem__": "Index deletion",
        "__iter__": "Iterator",
        "__next__": "Next item",
        "__contains__": "Membership test",
        "__call__": "Callable instance",
        "__enter__": "Enter context manager",
        "__exit__": "Exit context manager",
        "__bool__": "Truthiness",
        "__hash__": "Hash value",
        "__eq__": "Equality",
        "__ne__": "Inequality",
        "__lt__": "Less than",
        "__le__": "Less or equal",
        "__gt__": "Greater than",
        "__ge__": "Greater or equal",
        "__add__": "Addition",
        "__sub__": "Subtraction",
        "__mul__": "Multiplication",
        "__truediv__": "Division",
        "__floordiv__": "Floor division",
        "__mod__": "Modulo",
        "__pow__": "Power",
        "__and__": "Bitwise and",
        "__or__": "Bitwise or",
        "__xor__": "Bitwise xor",
        "__lshift__": "Left shift",
        "__rshift__": "Right shift",
    }

    def __init__(
        self,
        symbol_table: SymbolTable,
        type_inferrer: TypeInferrer,
    ) -> None:
        """Initialize the class completer.

        Args:
            symbol_table: The symbol table for symbol lookup.
            type_inferrer: The type inferrer for type information.
        """
        self._symbol_table = symbol_table
        self._type_inferrer = type_inferrer

    def get_completions(self, context: CodeContext, prefix: str = "") -> List[CompletionItem]:
        """Get class completion items for the current context.

        Args:
            context: The current code context.
            prefix: The current input prefix.

        Returns:
            List of class completion items.
        """
        results: List[CompletionItem] = []

        # Get class symbols from the symbol table
        for symbol in self._symbol_table.get_all_symbols():
            if symbol.kind not in ("class",):
                continue

            if prefix and not symbol.name.startswith(prefix):
                continue

            results.append(CompletionItem.class_(
                name=symbol.name,
                documentation=symbol.docstring,
            ))

        # Add built-in types
        builtin_names = dir(builtins)
        for name in builtin_names:
            if prefix and not name.startswith(prefix):
                continue
            if name.startswith("_"):
                continue
            if self._symbol_table.get_symbol(name) is not None:
                continue
            obj = getattr(builtins, name, None)
            if obj is None:
                continue
            if isinstance(obj, type):
                # Skip common exceptions (not useful in completions)
                if name.endswith("Error") or name.endswith("Warning"):
                    continue
                if name in ("BaseException", "Exception", "object", "type"):
                    continue
                results.append(CompletionItem.class_(
                    name=name,
                    documentation=obj.__doc__,
                ))

        return results

    def get_attribute_completions(
        self,
        obj_name: str,
        prefix: str = "",
    ) -> List[CompletionItem]:
        """Get attribute completions for a given object.

        Attempts to resolve the object's type and returns its attributes.
        Falls back to common attribute suggestions for known types.

        Args:
            obj_name: The name of the object being accessed.
            prefix: The current attribute prefix.

        Returns:
            List of attribute completion items.
        """
        results: List[CompletionItem] = []

        # Look up the object in the symbol table
        symbol = self._symbol_table.get_symbol(obj_name)

        # Try to determine the type
        obj_type = symbol.type_name if symbol else obj_name

        # Known type attributes
        type_attributes: Dict[str, List[Tuple[str, str, str]]] = {
            "str": [
                ("upper", "method", "str.upper() -> str"),
                ("lower", "method", "str.lower() -> str"),
                ("strip", "method", "str.strip() -> str"),
                ("split", "method", "str.split() -> list"),
                ("join", "method", "str.join() -> str"),
                ("replace", "method", "str.replace() -> str"),
                ("find", "method", "str.find() -> int"),
                ("index", "method", "str.index() -> int"),
                ("startswith", "method", "str.startswith() -> bool"),
                ("endswith", "method", "str.endswith() -> bool"),
                ("format", "method", "str.format() -> str"),
                ("encode", "method", "str.encode() -> bytes"),
                ("capitalize", "method", "str.capitalize() -> str"),
                ("title", "method", "str.title() -> str"),
                ("swapcase", "method", "str.swapcase() -> str"),
                ("zfill", "method", "str.zfill() -> str"),
                ("ljust", "method", "str.ljust() -> str"),
                ("rjust", "method", "str.rjust() -> str"),
                ("center", "method", "str.center() -> str"),
                ("count", "method", "str.count() -> int"),
                ("__len__", "method", "str.__len__() -> int"),
            ],
            "list": [
                ("append", "method", "list.append() -> None"),
                ("extend", "method", "list.extend() -> None"),
                ("pop", "method", "list.pop() -> Any"),
                ("remove", "method", "list.remove() -> None"),
                ("sort", "method", "list.sort() -> None"),
                ("reverse", "method", "list.reverse() -> None"),
                ("insert", "method", "list.insert() -> None"),
                ("clear", "method", "list.clear() -> None"),
                ("copy", "method", "list.copy() -> list"),
                ("count", "method", "list.count() -> int"),
                ("index", "method", "list.index() -> int"),
                ("__len__", "method", "list.__len__() -> int"),
            ],
            "dict": [
                ("keys", "method", "dict.keys() -> dict_keys"),
                ("values", "method", "dict.values() -> dict_values"),
                ("items", "method", "dict.items() -> dict_items"),
                ("get", "method", "dict.get() -> Any"),
                ("pop", "method", "dict.pop() -> Any"),
                ("update", "method", "dict.update() -> None"),
                ("setdefault", "method", "dict.setdefault() -> Any"),
                ("clear", "method", "dict.clear() -> None"),
                ("copy", "method", "dict.copy() -> dict"),
                ("__len__", "method", "dict.__len__() -> int"),
                ("__contains__", "method", "dict.__contains__() -> bool"),
            ],
            "int": [
                ("__add__", "method", "int.__add__() -> int"),
                ("__sub__", "method", "int.__sub__() -> int"),
                ("__mul__", "method", "int.__mul__() -> int"),
                ("__truediv__", "method", "int.__truediv__() -> float"),
                ("__floordiv__", "method", "int.__floordiv__() -> int"),
                ("__mod__", "method", "int.__mod__() -> int"),
                ("__pow__", "method", "int.__pow__() -> int"),
                ("__and__", "method", "int.__and__() -> int"),
                ("__or__", "method", "int.__or__() -> int"),
                ("__xor__", "method", "int.__xor__() -> int"),
                ("__lshift__", "method", "int.__lshift__() -> int"),
                ("__rshift__", "method", "int.__rshift__() -> int"),
                ("bit_length", "method", "int.bit_length() -> int"),
                ("conjugate", "method", "int.conjugate() -> int"),
                ("real", "property", "int.real"),
                ("imag", "property", "int.imag"),
                ("numerator", "property", "int.numerator"),
                ("denominator", "property", "int.denominator"),
            ],
            "float": [
                ("__add__", "method", "float.__add__() -> float"),
                ("__sub__", "method", "float.__sub__() -> float"),
                ("__mul__", "method", "float.__mul__() -> float"),
                ("__truediv__", "method", "float.__truediv__() -> float"),
                ("__floordiv__", "method", "float.__floordiv__() -> float"),
                ("__mod__", "method", "float.__mod__() -> float"),
                ("__pow__", "method", "float.__pow__() -> float"),
                ("is_integer", "method", "float.is_integer() -> bool"),
                ("as_integer_ratio", "method", "float.as_integer_ratio() -> tuple"),
                ("conjugate", "method", "float.conjugate() -> float"),
                ("real", "property", "float.real"),
                ("imag", "property", "float.imag"),
                ("hex", "method", "float.hex() -> str"),
                ("fromhex", "method", "float.fromhex() -> float"),
            ],
            "set": [
                ("add", "method", "set.add() -> None"),
                ("remove", "method", "set.remove() -> None"),
                ("discard", "method", "set.discard() -> None"),
                ("pop", "method", "set.pop() -> Any"),
                ("clear", "method", "set.clear() -> None"),
                ("copy", "method", "set.copy() -> set"),
                ("union", "method", "set.union() -> set"),
                ("intersection", "method", "set.intersection() -> set"),
                ("difference", "method", "set.difference() -> set"),
                ("symmetric_difference", "method", "set.symmetric_difference() -> set"),
                ("issubset", "method", "set.issubset() -> bool"),
                ("issuperset", "method", "set.issuperset() -> bool"),
                ("update", "method", "set.update() -> None"),
                ("__len__", "method", "set.__len__() -> int"),
            ],
            "Path": [
                ("parent", "property", "Parent directory"),
                ("parents", "property", "Parent directories"),
                ("name", "property", "File name"),
                ("stem", "property", "File stem (name without suffix)"),
                ("suffix", "property", "File extension"),
                ("anchor", "property", "Anchor (drive/root)"),
                ("parts", "property", "Path parts"),
                ("joinpath", "method", "pathlib.Path.joinpath() -> Path"),
                ("resolve", "method", "pathlib.Path.resolve() -> Path"),
                ("absolute", "method", "pathlib.Path.absolute() -> Path"),
                ("exists", "method", "pathlib.Path.exists() -> bool"),
                ("is_dir", "method", "pathlib.Path.is_dir() -> bool"),
                ("is_file", "method", "pathlib.Path.is_file() -> bool"),
                ("mkdir", "method", "pathlib.Path.mkdir() -> None"),
                ("rmdir", "method", "pathlib.Path.rmdir() -> None"),
                ("unlink", "method", "pathlib.Path.unlink() -> None"),
                ("rename", "method", "pathlib.Path.rename() -> Path"),
                ("replace", "method", "pathlib.Path.replace() -> Path"),
                ("glob", "method", "pathlib.Path.glob() -> Generator"),
                ("rglob", "method", "pathlib.Path.rglob() -> Generator"),
                ("iterdir", "method", "pathlib.Path.iterdir() -> Generator"),
                ("read_text", "method", "pathlib.Path.read_text() -> str"),
                ("read_bytes", "method", "pathlib.Path.read_bytes() -> bytes"),
                ("write_text", "method", "pathlib.Path.write_text() -> None"),
                ("write_bytes", "method", "pathlib.Path.write_bytes() -> None"),
                ("open", "method", "pathlib.Path.open() -> file"),
            ],
        }

        # Get attributes for the inferred type
        normalized_type = obj_type or "object"
        # Try to match the type name
        best_match = "object"
        for known_type in type_attributes:
            if known_type.lower() in normalized_type.lower() or normalized_type.lower() in known_type.lower():
                best_match = known_type
                break

        attrs = type_attributes.get(best_match, [])
        for attr_name, attr_kind, attr_detail in attrs:
            if prefix and not attr_name.startswith(prefix):
                continue
            kind = CompletionItemKind.METHOD if attr_kind == "method" else CompletionItemKind.PROPERTY
            results.append(CompletionItem(
                label=attr_name,
                kind=kind,
                detail=attr_detail,
                insert_text=attr_name,
            ))

        return results


# ---------------------------------------------------------------------------
# ModuleCompleter
# ---------------------------------------------------------------------------

class ModuleCompleter:
    """Provides Python module/package completions for import statements.

    Discovers available Python modules from the system path and installed
    packages.
    """

    def __init__(self) -> None:
        self._module_cache: Optional[List[Tuple[str, bool]]] = None
        self._cache_time: float = 0
        self._cache_ttl: float = 60.0  # Re-scan every 60 seconds

    def get_completions(self, prefix: str = "") -> List[CompletionItem]:
        """Get module completion items matching the prefix.

        Args:
            prefix: The module prefix to filter by.

        Returns:
            List of module completion items.
        """
        results: List[CompletionItem] = []
        modules = self._get_available_modules()

        for mod_name, is_package in modules:
            if prefix and not mod_name.startswith(prefix):
                continue
            # Skip private modules (starting with _)
            if mod_name.startswith("_"):
                continue
            results.append(CompletionItem.module(mod_name, is_package))

        return results

    def get_submodules(self, module_path: str) -> List[CompletionItem]:
        """Get submodules of a given module path.

        Args:
            module_path: The parent module path (e.g., 'os.path').

        Returns:
            List of submodule completion items.
        """
        results: List[CompletionItem] = []

        try:
            # Try to import the module
            mod = importlib.import_module(module_path)
            if hasattr(mod, "__path__"):
                # It's a package
                for finder, name, is_pkg in pkgutil.iter_modules(mod.__path__):
                    full_name = f"{module_path}.{name}"
                    results.append(CompletionItem.module(full_name, is_pkg))
        except (ImportError, AttributeError, ValueError):
            pass

        return results

    def _get_available_modules(self) -> List[Tuple[str, bool]]:
        """Get all available Python modules.

        Returns:
            List of (module_name, is_package) tuples.
        """
        now = time.time()
        if self._module_cache is not None and now - self._cache_time < self._cache_ttl:
            return self._module_cache

        modules: List[Tuple[str, bool]] = []

        # Built-in modules
        for name in sys.builtin_module_names:
            modules.append((name, False))

        # Installed packages (top-level only)
        seen: Set[str] = set()
        for finder, name, is_pkg in pkgutil.iter_modules():
            if name not in seen:
                seen.add(name)
                modules.append((name, is_pkg))

        # Add some common standard library modules that might not be found
        common_modules = [
            "os", "sys", "re", "json", "math", "random", "datetime",
            "collections", "itertools", "functools", "pathlib", "typing",
            "abc", "enum", "dataclasses", "hashlib", "base64", "copy",
            "pprint", "logging", "argparse", "subprocess", "threading",
            "multiprocessing", "io", "textwrap", "string", "struct",
            "tempfile", "shutil", "glob", "fnmatch", "linecache",
            "pickle", "shelve", "sqlite3", "csv", "configparser",
            "xml", "html", "http", "urllib", "email", "unittest",
            "doctest", "pdb", "profile", "timeit", "trace",
            "warnings", "contextlib", "weakref", "types", "inspect",
            "ast", "tokenize", "keyword", "token", "parser",
            "symtable", "symbol", "opcode", "dis", "codecs",
            "difflib", "filecmp", "fileinput", "stat", "locale",
            "gettext", "getopt", "atexit", "signal", "mmap",
            "ctypes", "struct", "array", "decimal", "fractions",
            "statistics", "numbers", "cmath", "calendar", "time",
            "zoneinfo", "importlib", "pkgutil", "runpy", "site",
        ]
        for name in common_modules:
            if name not in seen:
                seen.add(name)
                modules.append((name, True))

        self._module_cache = modules
        self._cache_time = now
        return modules

    def invalidate_cache(self) -> None:
        """Force a cache refresh on the next call."""
        self._module_cache = None
        self._cache_time = 0


# ---------------------------------------------------------------------------
# PathCompleter
# ---------------------------------------------------------------------------

class PathCompleter:
    """Provides file path completions inside string literals.

    Completes file and directory paths when the cursor is inside a string
    that looks like a file path.
    """

    def get_completions(self, prefix: str = "") -> List[CompletionItem]:
        """Get path completion items matching the prefix.

        Args:
            prefix: The partial path to complete.

        Returns:
            List of file/folder completion items.
        """
        results: List[CompletionItem] = []

        if not prefix:
            return results

        try:
            # Expand user directory
            expanded = os.path.expanduser(prefix)
            expanded = os.path.expandvars(expanded)

            # Determine the directory to list and the partial name
            dir_path = os.path.dirname(expanded) if expanded else "."
            partial = os.path.basename(expanded)

            # If the prefix ends with a separator, list the directory
            if prefix.endswith(("/", "\\")):
                dir_path = expanded
                partial = ""
            elif prefix.endswith(".") and not expanded.endswith("."):
                # Handle relative paths like "./"
                dir_path = os.path.dirname(expanded.rstrip("."))
                partial = os.path.basename(expanded.rstrip("."))

            if not dir_path:
                dir_path = "."

            # List directory contents
            if os.path.isdir(dir_path):
                for entry in sorted(os.listdir(dir_path)):
                    if partial and not entry.startswith(partial):
                        continue
                    if entry.startswith("."):
                        continue
                    entry_path = os.path.join(dir_path, entry)
                    is_dir = os.path.isdir(entry_path)

                    # Format the completion label
                    if prefix.startswith("~"):
                        # Keep the ~ prefix
                        home = os.path.expanduser("~")
                        label = entry
                        if prefix.startswith("~"):
                            rel = os.path.relpath(dir_path, os.path.dirname(home))
                            if rel == ".":
                                label = os.path.join("~", entry)
                            else:
                                label = os.path.join(rel, entry)
                        label = label.replace("\\", "/")
                    elif prefix.startswith("."):
                        # Keep relative prefix
                        rel = os.path.relpath(dir_path, os.path.dirname(prefix) if os.path.dirname(prefix) else ".")
                        if rel == ".":
                            label = entry
                        else:
                            label = os.path.join(os.path.dirname(prefix.rstrip("/\\")), entry)
                        label = label.replace("\\", "/")
                    else:
                        label = entry

                    if is_dir:
                        label += "/"
                        results.append(CompletionItem.file_path(label, is_dir=True))
                    else:
                        results.append(CompletionItem.file_path(label, is_dir=False))
        except (PermissionError, FileNotFoundError, OSError):
            pass

        return results


# ---------------------------------------------------------------------------
# CompletionEngine (Abstract Base Class)
# ---------------------------------------------------------------------------

class CompletionEngine(ABC):
    """Abstract base class for code completion engines.

    Defines the interface for completion engines that provide code
    completions, signature help, and hover information.
    """

    @abstractmethod
    def get_completions(
        self,
        source: str,
        line: int,
        column: int,
    ) -> List[CompletionItem]:
        """Get completion items for a given cursor position.

        Args:
            source: The full source code text.
            line: Cursor line number (0-based).
            column: Cursor column number (0-based).

        Returns:
            List of completion items, ranked by relevance.
        """
        ...

    @abstractmethod
    def get_signature_help(
        self,
        source: str,
        line: int,
        column: int,
    ) -> Optional[SignatureInfo]:
        """Get signature help for a function call at the cursor position.

        Args:
            source: The full source code text.
            line: Cursor line number (0-based).
            column: Cursor column number (0-based).

        Returns:
            SignatureInfo if a function call is detected, None otherwise.
        """
        ...

    @abstractmethod
    def get_hover_info(
        self,
        source: str,
        line: int,
        column: int,
    ) -> Optional[str]:
        """Get hover information for a symbol at the cursor position.

        Args:
            source: The full source code text.
            line: Cursor line number (0-based).
            column: Cursor column number (0-based).

        Returns:
            Markdown hover text if a symbol is found, None otherwise.
        """
        ...


# ---------------------------------------------------------------------------
# PythonCompletionEngine
# ---------------------------------------------------------------------------

class PythonCompletionEngine(CompletionEngine):
    """AST-based Python code completion engine.

    Provides context-aware code completions by analyzing the Python AST,
    tracking symbols, inferring types, and scoring candidates.
    """

    def __init__(self) -> None:
        """Initialize the completion engine with all sub-components."""
        self._symbol_table = SymbolTable()
        self._type_inferrer = TypeInferrer()
        self._context_analyzer = ContextAnalyzer()
        self._scorer = PriorityScorer()
        self._cache = CompletionCache()

        # Completers
        self._keyword_completer = KeywordCompleter()
        self._snippet_provider = SnippetProvider()
        self._variable_completer = VariableCompleter(self._symbol_table, self._type_inferrer)
        self._function_completer = FunctionCompleter(self._symbol_table, self._type_inferrer)
        self._class_completer = ClassCompleter(self._symbol_table, self._type_inferrer)
        self._module_completer = ModuleCompleter()
        self._path_completer = PathCompleter()

        # Track whether the document has been analyzed
        self._analyzed: bool = False

    def get_completions(
        self,
        source: str,
        line: int,
        column: int,
    ) -> List[CompletionItem]:
        """Get completion items for the given cursor position.

        Args:
            source: The full source code.
            line: Cursor line (0-based).
            column: Cursor column (0-based).

        Returns:
            Ranked list of completion items.
        """
        # Check cache
        cache_key = CompletionCache.make_key(source, line, column)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for key %s", cache_key[:8])
            return cached

        # Analyze the document
        self.analyze_document(source)

        # Analyze context at cursor position
        context = self._context_analyzer.analyze(source, line, column)

        # Collect completions based on trigger kind
        items: List[CompletionItem] = []

        if context.trigger_kind == "dot":
            # Attribute completion
            if context.trigger_word:
                items.extend(
                    self._class_completer.get_attribute_completions(
                        context.trigger_word,
                        prefix=context.prefix,
                    )
                )

        elif context.trigger_kind == "import":
            # Module completion
            items.extend(self._module_completer.get_completions(prefix=context.prefix))

        elif context.trigger_kind == "path":
            # Path completion
            items.extend(self._path_completer.get_completions(prefix=context.prefix))

        elif context.trigger_kind == "decorator":
            # Decorator completions (common decorator names)
            decorators = [
                CompletionItem(label="property", kind=CompletionItemKind.FUNCTION, detail="Built-in property decorator"),
                CompletionItem(label="staticmethod", kind=CompletionItemKind.FUNCTION, detail="Built-in staticmethod decorator"),
                CompletionItem(label="classmethod", kind=CompletionItemKind.FUNCTION, detail="Built-in classmethod decorator"),
                CompletionItem(label="abstractmethod", kind=CompletionItemKind.FUNCTION, detail="abc.abstractmethod decorator"),
                CompletionItem(label="dataclass", kind=CompletionItemKind.FUNCTION, detail="dataclasses.dataclass decorator"),
                CompletionItem(label="contextmanager", kind=CompletionItemKind.FUNCTION, detail="contextlib.contextmanager decorator"),
                CompletionItem(label="wraps", kind=CompletionItemKind.FUNCTION, detail="functools.wraps decorator"),
                CompletionItem(label="lru_cache", kind=CompletionItemKind.FUNCTION, detail="functools.lru_cache decorator"),
                CompletionItem(label="cached_property", kind=CompletionItemKind.FUNCTION, detail="functools.cached_property decorator"),
                CompletionItem(label="final", kind=CompletionItemKind.FUNCTION, detail="typing.final decorator"),
                CompletionItem(label="overload", kind=CompletionItemKind.FUNCTION, detail="typing.overload decorator"),
                CompletionItem(label="runtime_checkable", kind=CompletionItemKind.FUNCTION, detail="typing.runtime_checkable decorator"),
                CompletionItem(label="no_type_check", kind=CompletionItemKind.FUNCTION, detail="typing.no_type_check decorator"),
            ]
            for dec in decorators:
                if context.prefix and not dec.label.startswith(context.prefix):
                    continue
                items.append(dec)

        else:
            # General completion: combine all sources
            # Keywords
            items.extend(
                self._keyword_completer.get_completions(context, prefix=context.prefix)
            )

            # Snippets
            items.extend(self._snippet_provider.get_snippets(context))

            # Variables
            items.extend(
                self._variable_completer.get_completions(context, prefix=context.prefix)
            )

            # Functions
            items.extend(
                self._function_completer.get_completions(context, prefix=context.prefix)
            )

            # Classes
            items.extend(
                self._class_completer.get_completions(context, prefix=context.prefix)
            )

            # Modules (only if prefix looks like a module name)
            if context.prefix and not context.prefix[0].isupper():
                items.extend(
                    self._module_completer.get_completions(prefix=context.prefix)
                )

        # Score and rank
        ranked = self._scorer.rank(items, context, prefix=context.prefix)

        # Cache the result
        self._cache.set(cache_key, ranked)

        return ranked

    def get_signature_help(
        self,
        source: str,
        line: int,
        column: int,
    ) -> Optional[SignatureInfo]:
        """Get signature help for a function call at the cursor.

        Args:
            source: The full source code.
            line: Cursor line (0-based).
            column: Cursor column (0-based).

        Returns:
            SignatureInfo if a function call is found, None otherwise.
        """
        self.analyze_document(source)
        return self._function_completer.get_signature_help(source, line, column)

    def get_hover_info(
        self,
        source: str,
        line: int,
        column: int,
    ) -> Optional[str]:
        """Get hover information for a symbol at the cursor.

        Args:
            source: The full source code.
            line: Cursor line (0-based).
            column: Cursor column (0-based).

        Returns:
            Markdown hover text if a symbol is found, None otherwise.
        """
        self.analyze_document(source)

        lines = source.splitlines()
        if line >= len(lines):
            return None

        # Extract the word at the cursor
        line_text = lines[line]
        if column >= len(line_text):
            return None

        # Find the word boundaries
        start = column
        while start > 0 and (line_text[start - 1].isalnum() or line_text[start - 1] == "_"):
            start -= 1
        end = column
        while end < len(line_text) and (line_text[end].isalnum() or line_text[end] == "_"):
            end += 1

        word = line_text[start:end]
        if not word:
            return None

        # Look up in symbol table
        symbol = self._symbol_table.get_symbol(word)
        if symbol is not None:
            parts: List[str] = []
            if symbol.kind == "function" or symbol.kind == "method":
                params = ", ".join(symbol.parameters) if symbol.parameters else "..."
                sig = f"{symbol.name}({params})"
                if symbol.type_name:
                    sig += f" -> {symbol.type_name}"
                parts.append(f"**{symbol.kind}**: `{sig}`")
            elif symbol.kind == "class":
                parts.append(f"**class**: `{symbol.name}`")
            elif symbol.kind == "variable" or symbol.kind == "parameter":
                type_str = f": {symbol.type_name}" if symbol.type_name else ""
                parts.append(f"**{symbol.kind}**: `{symbol.name}{type_str}`")
            elif symbol.kind == "module":
                parts.append(f"**module**: `{symbol.name}`")
            else:
                parts.append(f"**{symbol.kind}**: `{symbol.name}`")

            if symbol.docstring:
                parts.append("")
                parts.append(symbol.docstring.strip())

            if symbol.line > 0:
                parts.append("")
                parts.append(f"*Defined at line {symbol.line}*")

            return "\n".join(parts)

        # Check builtins
        if hasattr(builtins, word):
            obj = getattr(builtins, word)
            doc = getattr(obj, "__doc__", None)
            type_name = type(obj).__name__
            parts = [f"**builtin {type_name}**: `{word}`"]
            if doc:
                parts.append("")
                parts.append(doc.strip())
            return "\n".join(parts)

        return None

    def analyze_document(self, source: str) -> None:
        """Analyze a source document and build the symbol table.

        Parses the source code into an AST and walks it to collect all
        symbol definitions (functions, classes, variables, imports).

        Args:
            source: The source code to analyze.
        """
        self._symbol_table.clear()

        try:
            tree = ast.parse(source, mode="exec")
        except SyntaxError:
            # Try to parse as much as possible
            try:
                tree = ast.parse(source + "\n", mode="exec")
            except SyntaxError:
                self._analyzed = False
                return

        self._walk_and_collect(tree, scope="global")

        self._analyzed = True

    def _walk_and_collect(
        self,
        node: ast.AST,
        scope: str = "global",
        parent_class: Optional[str] = None,
    ) -> None:
        """Walk the AST and collect symbols into the symbol table.

        Recursively traverses the AST to find function definitions, class
        definitions, variable assignments, and import statements.

        Args:
            node: The current AST node.
            scope: The current scope name.
            parent_class: The enclosing class name, if any.
        """
        if isinstance(node, ast.FunctionDef):
            # Collect function
            kind = "method" if parent_class is not None else "function"
            params: List[str] = []
            for arg in node.args.args:
                params.append(arg.arg)
            if node.args.vararg:
                params.append(f"*{node.args.vararg.arg}")
            if node.args.kwonlyargs:
                for arg in node.args.kwonlyargs:
                    params.append(arg.arg)
            if node.args.kwarg:
                params.append(f"**{node.args.kwarg.arg}")

            # Infer return type
            return_type: Optional[str] = None
            if node.returns is not None:
                return_type = self._type_inferrer._infer_annotation(node.returns)

            docstring = ast.get_docstring(node)

            symbol = Symbol(
                name=node.name,
                kind=kind,
                type_name=return_type,
                scope=scope,
                line=node.lineno,
                column=node.col_offset,
                docstring=docstring,
                parameters=params,
            )
            self._symbol_table.add_symbol(symbol)

            # Enter function scope
            func_scope = f"{scope}:{node.name}"
            self._symbol_table.enter_scope(func_scope)

            # Add parameters as symbols
            for arg in node.args.args:
                param_type = None
                if arg.annotation:
                    param_type = self._type_inferrer._infer_annotation(arg.annotation)
                self._symbol_table.add_symbol(Symbol(
                    name=arg.arg,
                    kind="parameter",
                    type_name=param_type,
                    scope=func_scope,
                    line=arg.lineno if hasattr(arg, 'lineno') else node.lineno,
                    column=arg.col_offset if hasattr(arg, 'col_offset') else 0,
                ))

            # Continue walking the function body
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                                       ast.Assign, ast.AnnAssign, ast.AugAssign,
                                       ast.Import, ast.ImportFrom)):
                    self._walk_and_collect(child, scope=func_scope, parent_class=parent_class)

            self._symbol_table.exit_scope()

        elif isinstance(node, ast.AsyncFunctionDef):
            # Async function - similar to FunctionDef
            kind = "method" if parent_class is not None else "function"
            params = [arg.arg for arg in node.args.args]
            if node.args.vararg:
                params.append(f"*{node.args.vararg.arg}")
            if node.args.kwarg:
                params.append(f"**{node.args.kwarg.arg}")

            return_type = None
            if node.returns is not None:
                return_type = self._type_inferrer._infer_annotation(node.returns)

            docstring = ast.get_docstring(node)

            symbol = Symbol(
                name=node.name,
                kind=kind,
                type_name=return_type,
                scope=scope,
                line=node.lineno,
                column=node.col_offset,
                docstring=docstring,
                parameters=params,
            )
            self._symbol_table.add_symbol(symbol)

            func_scope = f"{scope}:{node.name}"
            self._symbol_table.enter_scope(func_scope)

            for arg in node.args.args:
                self._symbol_table.add_symbol(Symbol(
                    name=arg.arg,
                    kind="parameter",
                    scope=func_scope,
                    line=arg.lineno if hasattr(arg, 'lineno') else node.lineno,
                    column=arg.col_offset if hasattr(arg, 'col_offset') else 0,
                ))

            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                                       ast.Assign, ast.AnnAssign, ast.AugAssign,
                                       ast.Import, ast.ImportFrom)):
                    self._walk_and_collect(child, scope=func_scope, parent_class=parent_class)

            self._symbol_table.exit_scope()

        elif isinstance(node, ast.ClassDef):
            # Collect class
            bases = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.append(base.id)

            docstring = ast.get_docstring(node)

            symbol = Symbol(
                name=node.name,
                kind="class",
                type_name=node.name,
                scope=scope,
                line=node.lineno,
                column=node.col_offset,
                docstring=docstring,
            )
            self._symbol_table.add_symbol(symbol)

            # Enter class scope
            class_scope = f"{scope}:{node.name}"
            self._symbol_table.enter_scope(class_scope)

            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                                       ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    self._walk_and_collect(child, scope=class_scope, parent_class=node.name)

            self._symbol_table.exit_scope()

        elif isinstance(node, ast.Assign):
            # Variable assignment
            inferred_type = self._type_inferrer.infer_from_assignment(node)

            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._symbol_table.add_symbol(Symbol(
                        name=target.id,
                        kind="variable",
                        type_name=inferred_type,
                        scope=scope,
                        line=target.lineno if hasattr(target, 'lineno') else node.lineno,
                        column=target.col_offset if hasattr(target, 'col_offset') else 0,
                    ))
                elif isinstance(target, (ast.Tuple, ast.List)):
                    # Unpacking assignment
                    for elt in target.elts:
                        if isinstance(elt, ast.Name):
                            self._symbol_table.add_symbol(Symbol(
                                name=elt.id,
                                kind="variable",
                                type_name=inferred_type,
                                scope=scope,
                                line=elt.lineno if hasattr(elt, 'lineno') else node.lineno,
                                column=elt.col_offset if hasattr(elt, 'col_offset') else 0,
                            ))

        elif isinstance(node, ast.AnnAssign):
            # Annotated assignment
            inferred_type = self._type_inferrer.infer_from_annotated_assignment(node)

            if isinstance(node.target, ast.Name):
                self._symbol_table.add_symbol(Symbol(
                    name=node.target.id,
                    kind="variable",
                    type_name=inferred_type,
                    scope=scope,
                    line=node.target.lineno if hasattr(node.target, 'lineno') else node.lineno,
                    column=node.target.col_offset if hasattr(node.target, 'col_offset') else 0,
                ))

        elif isinstance(node, ast.AugAssign):
            # Augmented assignment (x += 1)
            if isinstance(node.target, ast.Name):
                # Look up existing symbol to preserve type
                existing = self._symbol_table.get_symbol(node.target.id, scope)
                if existing is None:
                    inferred_type = self._type_inferrer.infer_type(node.value)
                    self._symbol_table.add_symbol(Symbol(
                        name=node.target.id,
                        kind="variable",
                        type_name=inferred_type,
                        scope=scope,
                        line=node.lineno,
                        column=node.col_offset,
                    ))

        elif isinstance(node, ast.Import):
            # Import statement
            for alias in node.names:
                name = alias.asname or alias.name
                self._symbol_table.add_symbol(Symbol(
                    name=name,
                    kind="module",
                    type_name="module",
                    scope=scope,
                    line=node.lineno,
                    column=node.col_offset,
                ))

        elif isinstance(node, ast.ImportFrom):
            # From import statement
            module = node.module or ""
            for alias in node.names:
                name = alias.asname or alias.name
                self._symbol_table.add_symbol(Symbol(
                    name=name,
                    kind="variable",
                    type_name=name,
                    scope=scope,
                    line=node.lineno,
                    column=node.col_offset,
                ))

        # Recurse into children for composite nodes
        # Include all statement types to ensure top-level module children
        # (FunctionDef, ClassDef, Assign, etc.) are properly collected.
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                                   ast.Assign, ast.AnnAssign, ast.AugAssign,
                                   ast.Import, ast.ImportFrom,
                                   ast.For, ast.AsyncFor, ast.While, ast.With,
                                   ast.AsyncWith, ast.Try, ast.If)):
                self._walk_and_collect(child, scope=scope, parent_class=parent_class)

    def get_symbols(self) -> List[Symbol]:
        """Get all symbols collected from the analyzed document.

        Returns:
            List of all symbols in the symbol table.
        """
        return self._symbol_table.get_all_symbols()

    def clear_cache(self) -> None:
        """Clear the completion cache."""
        self._cache.clear()
        logger.info("Completion cache cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache performance metrics.
        """
        return self._cache.stats

    def reset(self) -> None:
        """Reset the engine to its initial state."""
        self._symbol_table.clear()
        self._cache.clear()
        self._analyzed = False
        logger.info("Engine reset to initial state")


# ---------------------------------------------------------------------------
# Server mode
# ---------------------------------------------------------------------------

class CompletionServer:
    """Simple TCP server for LSP-like code completion.

    Listens for JSON requests and returns completion results over TCP.
    Each request is a single JSON object, and each response is a single
    JSON object followed by a newline.
    """

    def __init__(
        self,
        engine: PythonCompletionEngine,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ) -> None:
        """Initialize the server.

        Args:
            engine: The completion engine to use.
            host: Host address to bind to.
            port: Port to listen on.
        """
        self._engine = engine
        self._host = host
        self._port = port
        self._running = False
        self._server: Optional[socket.socket] = None

    def start(self) -> None:
        """Start the server and listen for connections."""
        self._running = True
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self._host, self._port))
        self._server.listen(5)
        self._server.settimeout(1.0)

        logger.info("Completion server listening on %s:%d", self._host, self._port)
        print(f"Server listening on {self._host}:{self._port}", flush=True)

        while self._running:
            try:
                client, addr = self._server.accept()
                logger.debug("Connection from %s", addr)
                threading.Thread(
                    target=self._handle_client,
                    args=(client, addr),
                    daemon=True,
                ).start()
            except socket.timeout:
                continue
            except OSError:
                break

    def stop(self) -> None:
        """Stop the server."""
        self._running = False
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass
        logger.info("Server stopped")

    def _handle_client(self, client: socket.socket, addr: Tuple[str, int]) -> None:
        """Handle a single client connection.

        Reads JSON requests, processes them, and sends JSON responses.

        Args:
            client: The client socket.
            addr: The client address.
        """
        buffer = ""
        try:
            client.settimeout(30.0)
            while self._running:
                try:
                    data = client.recv(65536).decode("utf-8")
                    if not data:
                        break
                    buffer += data

                    # Process complete JSON lines
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue

                        response = self._process_request(line)
                        client.sendall((json.dumps(response) + "\n").encode("utf-8"))

                except socket.timeout:
                    continue
                except (ConnectionError, BrokenPipeError):
                    break
        except Exception as e:
            logger.error("Error handling client %s: %s", addr, e)
        finally:
            try:
                client.close()
            except OSError:
                pass

    def _process_request(self, request_str: str) -> Dict[str, Any]:
        """Process a JSON request and return a JSON response.

        Args:
            request_str: JSON-encoded request string.

        Returns:
            JSON-encodable response dictionary.
        """
        try:
            request = json.loads(request_str)
            method = request.get("method", "")

            if method == "completions":
                source = request.get("source", "")
                line = request.get("line", 0)
                column = request.get("column", 0)
                items = self._engine.get_completions(source, line, column)
                return {"result": [item.to_dict() for item in items], "error": None}

            elif method == "signature_help":
                source = request.get("source", "")
                line = request.get("line", 0)
                column = request.get("column", 0)
                sig = self._engine.get_signature_help(source, line, column)
                return {"result": sig.to_dict() if sig else None, "error": None}

            elif method == "hover":
                source = request.get("source", "")
                line = request.get("line", 0)
                column = request.get("column", 0)
                info = self._engine.get_hover_info(source, line, column)
                return {"result": info, "error": None}

            elif method == "analyze":
                source = request.get("source", "")
                self._engine.analyze_document(source)
                symbols = [
                    {"name": s.name, "kind": s.kind, "type": s.type_name,
                     "scope": s.scope, "line": s.line}
                    for s in self._engine.get_symbols()
                ]
                return {"result": symbols, "error": None}

            elif method == "clear_cache":
                self._engine.clear_cache()
                return {"result": "cache cleared", "error": None}

            elif method == "cache_stats":
                return {"result": self._engine.get_cache_stats(), "error": None}

            elif method == "ping":
                return {"result": "pong", "error": None}

            elif method == "shutdown":
                self._running = False
                return {"result": "shutting down", "error": None}

            else:
                return {"result": None, "error": f"Unknown method: {method}"}

        except json.JSONDecodeError as e:
            return {"result": None, "error": f"Invalid JSON: {e}"}
        except Exception as e:
            logger.error("Request error: %s", traceback.format_exc())
            return {"result": None, "error": str(e)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for the CLI.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="ai-complete",
        description="AI-powered Python code completion engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              # Get completions from stdin
              echo "import os\\nos.p" | ai-complete -l 1 -c 5

              # Get completions from a file
              ai-complete -f script.py -l 10 -c 15

              # Start server mode
              ai-complete --server --port 9876

              # Get signature help
              ai-complete -f script.py -l 5 -c 20 --signature

              # Get hover info
              ai-complete -f script.py -l 3 -c 8 --hover

              # Analyze a file and show symbols
              ai-complete -f script.py --analyze
        """),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    # Input source
    input_group = parser.add_argument_group("input")
    input_group.add_argument(
        "-f", "--file",
        type=str,
        help="Python source file to analyze",
    )

    # Cursor position
    position_group = parser.add_argument_group("position")
    position_group.add_argument(
        "-l", "--line",
        type=int,
        default=0,
        help="Cursor line number (0-based, default: 0)",
    )
    position_group.add_argument(
        "-c", "--column",
        type=int,
        default=0,
        help="Cursor column number (0-based, default: 0)",
    )

    # Mode
    mode_group = parser.add_argument_group("mode")
    mode_group.add_argument(
        "--server",
        action="store_true",
        help="Start in server mode",
    )
    mode_group.add_argument(
        "--host",
        type=str,
        default=DEFAULT_HOST,
        help=f"Server host (default: {DEFAULT_HOST})",
    )
    mode_group.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Server port (default: {DEFAULT_PORT})",
    )
    mode_group.add_argument(
        "--hover",
        action="store_true",
        help="Get hover information instead of completions",
    )
    mode_group.add_argument(
        "--signature",
        action="store_true",
        help="Get signature help instead of completions",
    )
    mode_group.add_argument(
        "--analyze",
        action="store_true",
        help="Analyze a file and show collected symbols",
    )

    # Output
    output_group = parser.add_argument_group("output")
    output_group.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    output_group.add_argument(
        "--max-results",
        type=int,
        default=DEFAULT_MAX_RESULTS,
        help=f"Maximum number of results (default: {DEFAULT_MAX_RESULTS})",
    )

    # Cache
    cache_group = parser.add_argument_group("cache")
    cache_group.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear the completion cache",
    )
    cache_group.add_argument(
        "--cache-stats",
        action="store_true",
        help="Show cache statistics",
    )

    # Logging
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    return parser


def main() -> None:
    """Main entry point for the CLI.

    Parses command-line arguments, reads source code, and performs
    the requested completion, analysis, or server operation.
    """
    parser = create_parser()
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Create the engine
    engine = PythonCompletionEngine()

    # Handle cache operations
    if args.clear_cache:
        engine.clear_cache()
        print("Cache cleared.")
        return

    if args.cache_stats:
        stats = engine.get_cache_stats()
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print(f"Cache size: {stats['size']}/{stats['max_size']}")
            print(f"Cache hits: {stats['hits']}")
            print(f"Cache misses: {stats['misses']}")
            print(f"Hit rate: {stats['hit_rate']:.1%}")
        return

    # Server mode
    if args.server:
        server = CompletionServer(engine, host=args.host, port=args.port)
        try:
            server.start()
        except KeyboardInterrupt:
            print("\nShutting down...")
            server.stop()
        except OSError as e:
            print(f"Failed to start server: {e}", file=sys.stderr)
            sys.exit(1)
        return

    # Read source code
    source: str = ""
    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                source = f.read()
        except FileNotFoundError:
            print(f"File not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        except IOError as e:
            print(f"Error reading file: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Read from stdin
        source = sys.stdin.read()

    if not source:
        print("No source code provided.", file=sys.stderr)
        sys.exit(1)

    # Analyze mode
    if args.analyze:
        engine.analyze_document(source)
        symbols = engine.get_symbols()

        if args.json:
            print(json.dumps([
                {"name": s.name, "kind": s.kind, "type": s.type_name,
                 "scope": s.scope, "line": s.line, "column": s.column}
                for s in symbols
            ], indent=2))
        else:
            print(f"Found {len(symbols)} symbols:")
            print("-" * 60)
            for s in sorted(symbols, key=lambda x: (x.scope, x.line, x.name)):
                type_str = f" -> {s.type_name}" if s.type_name else ""
                print(f"  {s.kind:12s} {s.name:20s} {type_str:20s}  [{s.scope}]")

        return

    # Hover mode
    if args.hover:
        info = engine.get_hover_info(source, args.line, args.column)
        if info:
            if args.json:
                print(json.dumps({"result": info}, indent=2))
            else:
                print(info)
        else:
            if args.json:
                print(json.dumps({"result": None}))
            else:
                print("No hover information available.")
        return

    # Signature help mode
    if args.signature:
        sig = engine.get_signature_help(source, args.line, args.column)
        if sig:
            if args.json:
                print(json.dumps(sig.to_dict(), indent=2))
            else:
                print(f"Function: {sig.name}")
                print(f"Signature: {sig.label}")
                if sig.parameters:
                    print(f"Parameters: {', '.join(sig.parameters)}")
                print(f"Active parameter: {sig.active_parameter}")
                if sig.documentation:
                    print(f"\n{sig.documentation}")
        else:
            if args.json:
                print(json.dumps({"result": None}))
            else:
                print("No signature help available.")
        return

    # Default: completions
    items = engine.get_completions(source, args.line, args.column)

    if args.json:
        print(json.dumps([item.to_dict() for item in items], indent=2))
    else:
        if not items:
            print("No completions found.")
            return

        print(f"Found {len(items)} completions:")
        print("-" * 80)
        print(f"{'Score':>8} {'Kind':14s} {'Label':30s} Detail")
        print("-" * 80)
        for item in items[:args.max_results]:
            kind_name = CompletionItemKind(item.kind).name if isinstance(item.kind, int) else item.kind.name
            print(f"{item.score:>8.1f} {kind_name:14s} {item.label:30s} {item.detail or ''}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()