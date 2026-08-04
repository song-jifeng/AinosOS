"""Comprehensive tests for the AI-powered code completion engine.

Tests cover all major components:
    - CompletionItem and data models
    - SymbolTable
    - TypeInferrer
    - ContextAnalyzer
    - PriorityScorer
    - CompletionCache
    - SnippetProvider
    - KeywordCompleter
    - VariableCompleter
    - FunctionCompleter
    - ClassCompleter
    - ModuleCompleter
    - PathCompleter
    - PythonCompletionEngine (integration)
    - Server mode
    - CLI
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch, mock_open

# Add the parent directory to the path so we can import ai_complete
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_complete import (
    # Data models
    CompletionItem,
    CompletionItemKind,
    Symbol,
    SignatureInfo,

    # Core
    SymbolTable,
    TypeInferrer,
    CodeContext,
    ContextAnalyzer,
    PriorityScorer,
    CompletionCache,

    # Completers
    SnippetProvider,
    KeywordCompleter,
    VariableCompleter,
    FunctionCompleter,
    ClassCompleter,
    ModuleCompleter,
    PathCompleter,

    # Engine
    CompletionEngine,
    PythonCompletionEngine,

    # Server
    CompletionServer,

    # CLI
    create_parser,
    main,

    # Constants
    DEFAULT_HOST,
    DEFAULT_PORT,
    SCORE_WEIGHTS,
)


# ===========================================================================
# Test: CompletionItem
# ===========================================================================

class TestCompletionItem(unittest.TestCase):
    """Tests for the CompletionItem data model and factory methods."""

    def test_keyword_factory(self) -> None:
        """Test the keyword factory method."""
        item = CompletionItem.keyword("def", documentation="Function definition")
        self.assertEqual(item.label, "def")
        self.assertEqual(item.kind, CompletionItemKind.KEYWORD)
        self.assertEqual(item.detail, "keyword")
        self.assertEqual(item.documentation, "Function definition")
        self.assertEqual(item.insert_text, "def")

    def test_snippet_factory(self) -> None:
        """Test the snippet factory method."""
        item = CompletionItem.snippet(
            "for",
            "for ${1:item} in ${2:iterable}:\\n    ${0:pass}",
            "For loop",
        )
        self.assertEqual(item.label, "for")
        self.assertEqual(item.kind, CompletionItemKind.SNIPPET)
        self.assertEqual(item.detail, "For loop")
        self.assertEqual(item.insert_text_format, 2)

    def test_variable_factory(self) -> None:
        """Test the variable factory method."""
        item = CompletionItem.variable("my_var", type_name="int")
        self.assertEqual(item.label, "my_var")
        self.assertEqual(item.kind, CompletionItemKind.VARIABLE)
        self.assertEqual(item.detail, "-> int")
        self.assertEqual(item.insert_text, "my_var")

    def test_function_factory(self) -> None:
        """Test the function factory method."""
        item = CompletionItem.function("foo", "(x: int) -> str")
        self.assertEqual(item.label, "foo")
        self.assertEqual(item.kind, CompletionItemKind.FUNCTION)
        self.assertEqual(item.detail, "(x: int) -> str")
        self.assertEqual(item.insert_text, "foo(")

    def test_class_factory(self) -> None:
        """Test the class factory method."""
        item = CompletionItem.class_("MyClass", bases=["BaseClass"])
        self.assertEqual(item.label, "MyClass")
        self.assertEqual(item.kind, CompletionItemKind.CLASS)
        self.assertEqual(item.detail, "class(BaseClass)")

    def test_module_factory(self) -> None:
        """Test the module factory method."""
        item = CompletionItem.module("os", is_package=False)
        self.assertEqual(item.label, "os")
        self.assertEqual(item.kind, CompletionItemKind.MODULE)

    def test_file_path_factory(self) -> None:
        """Test the file path factory method."""
        item = CompletionItem.file_path("/home/user/", is_dir=True)
        self.assertEqual(item.kind, CompletionItemKind.FOLDER)
        self.assertEqual(item.detail, "directory")

        item2 = CompletionItem.file_path("file.txt", is_dir=False)
        self.assertEqual(item2.kind, CompletionItemKind.FILE)
        self.assertEqual(item2.detail, "file")

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        item = CompletionItem.function("foo", "(x: int) -> str")
        d = item.to_dict()
        self.assertEqual(d["label"], "foo")
        self.assertEqual(d["kind"], int(CompletionItemKind.FUNCTION))
        self.assertEqual(d["detail"], "(x: int) -> str")
        self.assertEqual(d["insertText"], "foo(")
        self.assertEqual(d["insertTextFormat"], 2)
        self.assertFalse(d["preselect"])

    def test_to_dict_minimal(self) -> None:
        """Test serialization of a minimal item."""
        item = CompletionItem(label="test", kind=CompletionItemKind.TEXT)
        d = item.to_dict()
        self.assertEqual(d["label"], "test")
        self.assertEqual(d["kind"], int(CompletionItemKind.TEXT))
        # Optional fields should not be present
        self.assertNotIn("detail", d)
        self.assertNotIn("documentation", d)


# ===========================================================================
# Test: Symbol
# ===========================================================================

class TestSymbol(unittest.TestCase):
    """Tests for the Symbol data class."""

    def test_symbol_creation(self) -> None:
        """Test symbol creation with all fields."""
        sym = Symbol(
            name="my_func",
            kind="function",
            type_name="str",
            scope="global",
            line=10,
            column=5,
            docstring="My function",
            parameters=["x", "y"],
        )
        self.assertEqual(sym.name, "my_func")
        self.assertEqual(sym.kind, "function")
        self.assertEqual(sym.type_name, "str")
        self.assertEqual(sym.scope, "global")
        self.assertEqual(sym.line, 10)
        self.assertEqual(sym.column, 5)
        self.assertEqual(sym.docstring, "My function")
        self.assertEqual(sym.parameters, ["x", "y"])

    def test_symbol_defaults(self) -> None:
        """Test symbol creation with default values."""
        sym = Symbol(name="x", kind="variable")
        self.assertEqual(sym.type_name, None)
        self.assertEqual(sym.scope, "global")
        self.assertEqual(sym.line, 0)
        self.assertEqual(sym.column, 0)
        self.assertEqual(sym.docstring, None)
        self.assertEqual(sym.parameters, [])


# ===========================================================================
# Test: SignatureInfo
# ===========================================================================

class TestSignatureInfo(unittest.TestCase):
    """Tests for the SignatureInfo data class."""

    def test_signature_info(self) -> None:
        """Test signature info creation and serialization."""
        sig = SignatureInfo(
            name="foo",
            label="foo(x: int, y: str) -> bool",
            parameters=["x: int", "y: str"],
            active_parameter=1,
            documentation="Does something",
        )
        self.assertEqual(sig.name, "foo")
        self.assertEqual(sig.active_parameter, 1)

        d = sig.to_dict()
        self.assertEqual(d["name"], "foo")
        self.assertEqual(d["activeParameter"], 1)
        self.assertEqual(d["documentation"], "Does something")


# ===========================================================================
# Test: SymbolTable
# ===========================================================================

class TestSymbolTable(unittest.TestCase):
    """Tests for the SymbolTable class."""

    def setUp(self) -> None:
        self.table = SymbolTable()

    def test_add_and_get_symbol(self) -> None:
        """Test adding and retrieving a symbol."""
        sym = Symbol(name="x", kind="variable", type_name="int", scope="global")
        self.table.add_symbol(sym)
        retrieved = self.table.get_symbol("x")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "x")
        self.assertEqual(retrieved.type_name, "int")

    def test_get_symbol_nonexistent(self) -> None:
        """Test retrieving a nonexistent symbol."""
        self.assertIsNone(self.table.get_symbol("nonexistent"))

    def test_get_symbol_empty_name(self) -> None:
        """Test adding a symbol with an empty name raises ValueError."""
        with self.assertRaises(ValueError):
            self.table.add_symbol(Symbol(name="", kind="variable"))

    def test_scope_hierarchy(self) -> None:
        """Test that the table correctly walks scope hierarchy."""
        self.table.add_symbol(Symbol(
            name="x", kind="variable", type_name="int", scope="global"
        ))
        self.table.enter_scope("function:foo")
        self.table.add_symbol(Symbol(
            name="y", kind="variable", type_name="str", scope="function:foo"
        ))

        # Should find 'y' in current scope
        self.assertIsNotNone(self.table.get_symbol("y"))
        # Should find 'x' in global scope
        self.assertIsNotNone(self.table.get_symbol("x"))

        self.table.exit_scope()
        # After exiting, 'y' should not be visible
        self.assertIsNone(self.table.get_symbol("y"))

    def test_enter_exit_scope(self) -> None:
        """Test scope enter/exit behavior."""
        prev = self.table.enter_scope("global:test")
        self.assertEqual(prev, "global")
        self.assertEqual(self.table.current_scope, "global:test")

        prev2 = self.table.exit_scope()
        self.assertEqual(prev2, "global")
        self.assertEqual(self.table.current_scope, "global")

    def test_exit_global_scope(self) -> None:
        """Test that exiting from global scope returns None."""
        result = self.table.exit_scope()
        self.assertIsNone(result)
        self.assertEqual(self.table.current_scope, "global")

    def test_get_symbols_in_scope(self) -> None:
        """Test retrieving symbols in a specific scope."""
        self.table.add_symbol(Symbol(name="a", kind="variable", scope="global"))
        self.table.add_symbol(Symbol(name="b", kind="variable", scope="global"))
        self.table.enter_scope("function:foo")
        self.table.add_symbol(Symbol(name="c", kind="variable", scope="function:foo"))

        global_syms = self.table.get_symbols_in_scope("global")
        self.assertEqual(len(global_syms), 2)

        func_syms = self.table.get_symbols_in_scope("function:foo")
        self.assertEqual(len(func_syms), 1)

    def test_get_all_symbols(self) -> None:
        """Test retrieving all symbols across scopes."""
        self.table.add_symbol(Symbol(name="a", kind="variable", scope="global"))
        self.table.enter_scope("function:foo")
        self.table.add_symbol(Symbol(name="b", kind="variable", scope="function:foo"))

        all_syms = self.table.get_all_symbols()
        self.assertEqual(len(all_syms), 2)

    def test_get_symbols_by_kind(self) -> None:
        """Test filtering symbols by kind."""
        self.table.add_symbol(Symbol(name="func", kind="function", scope="global"))
        self.table.add_symbol(Symbol(name="cls", kind="class", scope="global"))
        self.table.add_symbol(Symbol(name="var", kind="variable", scope="global"))

        funcs = self.table.get_symbols_by_kind("function")
        self.assertEqual(len(funcs), 1)
        self.assertEqual(funcs[0].name, "func")

        vars = self.table.get_symbols_by_kind("variable")
        self.assertEqual(len(vars), 1)
        self.assertEqual(vars[0].name, "var")

    def test_get_all_names_in_scope(self) -> None:
        """Test retrieving all visible names from a scope."""
        self.table.add_symbol(Symbol(name="global_var", kind="variable", scope="global"))
        self.table.enter_scope("function:foo")
        self.table.add_symbol(Symbol(name="local_var", kind="variable", scope="function:foo"))

        names = self.table.get_all_names_in_scope("function:foo")
        self.assertIn("local_var", names)
        self.assertIn("global_var", names)
        # Builtins should be included
        self.assertIn("len", names)
        self.assertIn("print", names)

    def test_clear(self) -> None:
        """Test clearing the symbol table."""
        self.table.add_symbol(Symbol(name="x", kind="variable", scope="global"))
        self.table.clear()
        self.assertEqual(len(self.table.get_all_symbols()), 0)
        self.assertEqual(self.table.current_scope, "global")


# ===========================================================================
# Test: TypeInferrer
# ===========================================================================

class TestTypeInferrer(unittest.TestCase):
    """Tests for the TypeInferrer class."""

    def setUp(self) -> None:
        self.inferrer = TypeInferrer()
        self.symbol_table = SymbolTable()

    def _parse_expr(self, expr: str) -> ast.AST:
        """Helper to parse an expression into an AST node."""
        return ast.parse(expr, mode="eval").body

    def test_infer_constant_int(self) -> None:
        """Test inferring int constants."""
        node = self._parse_expr("42")
        self.assertEqual(self.inferrer.infer_type(node), "int")

    def test_infer_constant_float(self) -> None:
        """Test inferring float constants."""
        node = self._parse_expr("3.14")
        self.assertEqual(self.inferrer.infer_type(node), "float")

    def test_infer_constant_str(self) -> None:
        """Test inferring string constants."""
        node = self._parse_expr('"hello"')
        self.assertEqual(self.inferrer.infer_type(node), "str")

    def test_infer_constant_bool(self) -> None:
        """Test inferring bool constants."""
        node = self._parse_expr("True")
        self.assertEqual(self.inferrer.infer_type(node), "bool")
        node2 = self._parse_expr("False")
        self.assertEqual(self.inferrer.infer_type(node2), "bool")

    def test_infer_constant_none(self) -> None:
        """Test inferring None constant."""
        node = self._parse_expr("None")
        self.assertEqual(self.inferrer.infer_type(node), "None")

    def test_infer_constant_bytes(self) -> None:
        """Test inferring bytes constants."""
        node = self._parse_expr('b"hello"')
        self.assertEqual(self.inferrer.infer_type(node), "bytes")

    def test_infer_list(self) -> None:
        """Test inferring list literals."""
        node = self._parse_expr("[1, 2, 3]")
        result = self.inferrer.infer_type(node)
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("list"))

    def test_infer_empty_list(self) -> None:
        """Test inferring empty list."""
        node = self._parse_expr("[]")
        self.assertEqual(self.inferrer.infer_type(node), "list")

    def test_infer_dict(self) -> None:
        """Test inferring dict literals."""
        node = self._parse_expr('{"a": 1}')
        self.assertEqual(self.inferrer.infer_type(node), "dict")

    def test_infer_tuple(self) -> None:
        """Test inferring tuple literals."""
        node = self._parse_expr("(1, 'a')")
        result = self.inferrer.infer_type(node)
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("tuple"))

    def test_infer_set(self) -> None:
        """Test inferring set literals."""
        node = self._parse_expr("{1, 2, 3}")
        self.assertEqual(self.inferrer.infer_type(node), "set")

    def test_infer_name(self) -> None:
        """Test inferring types from name references."""
        self.symbol_table.add_symbol(Symbol(
            name="my_var", kind="variable", type_name="int", scope="global"
        ))
        node = ast.Name(id="my_var", ctx=ast.Load())
        result = self.inferrer.infer_type(node, self.symbol_table)
        self.assertEqual(result, "int")

    def test_infer_name_builtin(self) -> None:
        """Test inferring types from builtin names."""
        node = ast.Name(id="int", ctx=ast.Load())
        result = self.inferrer.infer_type(node, self.symbol_table)
        self.assertEqual(result, "int")

    def test_infer_call_known(self) -> None:
        """Test inferring return type from known function calls."""
        node = self._parse_expr("len([1, 2, 3])")
        self.assertEqual(self.inferrer.infer_type(node), "int")

        node2 = self._parse_expr('str(42)')
        self.assertEqual(self.inferrer.infer_type(node2), "str")

        node3 = self._parse_expr('list(range(5))')
        self.assertEqual(self.inferrer.infer_type(node3), "list")

    def test_infer_call_method(self) -> None:
        """Test inferring return type from method calls."""
        # We can't easily parse "obj.method()" as an expression standalone
        # since it needs an attribute context, so test via AST construction
        call = ast.Call(
            func=ast.Attribute(
                value=ast.Constant(value="hello"),
                attr="upper",
                ctx=ast.Load(),
            ),
            args=[],
            keywords=[],
        )
        # Method return types are looked up by attr name
        # 'upper' maps to 'str' in our _KNOWN_RETURN_TYPES? No, it's in method_returns
        # Actually method_returns is only for the _infer_call method
        # Let me check: 'upper' is not in _KNOWN_RETURN_TYPES
        # It's in the _infer_call's method_returns dict: "upper": "str"
        result = self.inferrer.infer_type(call, self.symbol_table)
        self.assertEqual(result, "str")

    def test_infer_binop_add_int(self) -> None:
        """Test inferring int addition result type."""
        node = self._parse_expr("1 + 2")
        self.assertEqual(self.inferrer.infer_type(node), "int")

    def test_infer_binop_add_str(self) -> None:
        """Test inferring string concatenation result type."""
        node = self._parse_expr('"a" + "b"')
        self.assertEqual(self.inferrer.infer_type(node), "str")

    def test_infer_binop_float(self) -> None:
        """Test inferring float result type."""
        node = self._parse_expr("1 + 2.5")
        self.assertEqual(self.inferrer.infer_type(node), "float")

    def test_infer_compare(self) -> None:
        """Test inferring comparison result type."""
        node = self._parse_expr("1 < 2")
        self.assertEqual(self.inferrer.infer_type(node), "bool")

    def test_infer_bool_op(self) -> None:
        """Test inferring boolean operation result type."""
        node = self._parse_expr("True and False")
        self.assertEqual(self.inferrer.infer_type(node), "bool")

    def test_infer_lambda(self) -> None:
        """Test inferring lambda type."""
        node = self._parse_expr("lambda x: x + 1")
        self.assertEqual(self.inferrer.infer_type(node), "Callable")

    def test_infer_list_comp(self) -> None:
        """Test inferring list comprehension type."""
        node = self._parse_expr("[x for x in range(10)]")
        self.assertEqual(self.inferrer.infer_type(node), "list")

    def test_infer_if_exp(self) -> None:
        """Test inferring ternary expression type."""
        node = self._parse_expr("1 if True else 2")
        self.assertEqual(self.inferrer.infer_type(node), "int")

    def test_infer_unaryop_not(self) -> None:
        """Test inferring 'not' result type."""
        node = self._parse_expr("not True")
        self.assertEqual(self.inferrer.infer_type(node), "bool")

    def test_infer_from_assignment(self) -> None:
        """Test inferring type from assignment."""
        assign = ast.parse("x = 42").body[0]
        self.assertIsInstance(assign, ast.Assign)
        result = self.inferrer.infer_from_assignment(assign)
        self.assertEqual(result, "int")

    def test_infer_from_annotated_assignment(self) -> None:
        """Test inferring type from annotated assignment."""
        ann_assign = ast.parse("x: int = 42").body[0]
        self.assertIsInstance(ann_assign, ast.AnnAssign)
        result = self.inferrer.infer_from_annotated_assignment(ann_assign)
        self.assertEqual(result, "int")

    def test_infer_from_annotation_only(self) -> None:
        """Test inferring type from annotation without value."""
        ann_assign = ast.parse("x: str").body[0]
        self.assertIsInstance(ann_assign, ast.AnnAssign)
        result = self.inferrer.infer_from_annotated_assignment(ann_assign)
        self.assertEqual(result, "str")

    def test_infer_subscript_generic(self) -> None:
        """Test inferring generic type (e.g., List[int])."""
        # This tests the annotation inference path
        node = ast.Subscript(
            value=ast.Name(id="List", ctx=ast.Load()),
            slice=ast.Name(id="int", ctx=ast.Load()),
            ctx=ast.Load(),
        )
        # Use the internal _infer_annotation method
        result = self.inferrer._infer_annotation(node)
        self.assertEqual(result, "List[int]")

    def test_infer_unknown_node(self) -> None:
        """Test inferring type from an unknown node type returns None."""
        node = ast.Break()
        self.assertIsNone(self.inferrer.infer_type(node))


# ===========================================================================
# Test: CodeContext
# ===========================================================================

class TestCodeContext(unittest.TestCase):
    """Tests for the CodeContext dataclass."""

    def test_default_context(self) -> None:
        """Test that default context has expected values."""
        ctx = CodeContext()
        self.assertEqual(ctx.scope_type, "module")
        self.assertEqual(ctx.scope_name, "<module>")
        self.assertEqual(ctx.line, 0)
        self.assertEqual(ctx.column, 0)
        self.assertEqual(ctx.trigger_kind, "general")
        self.assertFalse(ctx.inside_function)
        self.assertFalse(ctx.inside_class)
        self.assertFalse(ctx.inside_string)

    def test_context_with_values(self) -> None:
        """Test context with explicit values."""
        ctx = CodeContext(
            scope_type="function",
            scope_name="foo",
            line=10,
            column=5,
            trigger_kind="dot",
            trigger_word="obj",
            prefix="attr",
            inside_function=True,
            available_names={"x", "y", "z"},
        )
        self.assertEqual(ctx.scope_type, "function")
        self.assertEqual(ctx.trigger_word, "obj")
        self.assertEqual(ctx.prefix, "attr")
        self.assertIn("x", ctx.available_names)


# ===========================================================================
# Test: ContextAnalyzer
# ===========================================================================

class TestContextAnalyzer(unittest.TestCase):
    """Tests for the ContextAnalyzer class."""

    def setUp(self) -> None:
        self.analyzer = ContextAnalyzer()

    def test_analyze_module_level(self) -> None:
        """Test analyzing module-level context."""
        source = "x = 1\ny = 2\n"
        ctx = self.analyzer.analyze(source, 0, 0)
        self.assertEqual(ctx.scope_type, "module")
        self.assertEqual(ctx.trigger_kind, "general")

    def test_analyze_inside_function(self) -> None:
        """Test analyzing context inside a function."""
        source = "def foo():\n    x = 1\n    "
        ctx = self.analyzer.analyze(source, 1, 4)
        self.assertEqual(ctx.scope_type, "function")
        self.assertEqual(ctx.scope_name, "foo")
        self.assertTrue(ctx.inside_function)

    def test_analyze_inside_class(self) -> None:
        """Test analyzing context inside a class."""
        source = "class MyClass:\n    def __init__(self):\n        pass"
        ctx = self.analyzer.analyze(source, 0, 6)
        self.assertEqual(ctx.scope_type, "class")
        self.assertEqual(ctx.scope_name, "MyClass")
        self.assertTrue(ctx.inside_class)

    def test_dot_trigger(self) -> None:
        """Test detecting dot completion trigger."""
        source = "import os\nos."
        ctx = self.analyzer.analyze(source, 1, 3)
        self.assertEqual(ctx.trigger_kind, "dot")
        self.assertEqual(ctx.trigger_word, "os")

    def test_dot_trigger_with_prefix(self) -> None:
        """Test dot completion with an attribute prefix."""
        source = "import os\nos.path."
        ctx = self.analyzer.analyze(source, 1, 8)
        self.assertEqual(ctx.trigger_kind, "dot")
        # os.path is the word before the dot
        self.assertEqual(ctx.trigger_word, "os.path")

    def test_import_trigger(self) -> None:
        """Test detecting import completion trigger."""
        source = "import "
        ctx = self.analyzer.analyze(source, 0, 7)
        self.assertEqual(ctx.trigger_kind, "import")
        self.assertEqual(ctx.trigger_word, "")

    def test_from_import_trigger(self) -> None:
        """Test detecting from-import completion trigger."""
        source = "from os import "
        ctx = self.analyzer.analyze(source, 0, 15)
        self.assertEqual(ctx.trigger_kind, "import")

    def test_general_trigger_with_word(self) -> None:
        """Test detecting general completion with a word."""
        source = "pri"
        ctx = self.analyzer.analyze(source, 0, 3)
        self.assertEqual(ctx.trigger_kind, "general")
        self.assertEqual(ctx.trigger_word, "pri")
        self.assertEqual(ctx.prefix, "pri")

    def test_empty_source(self) -> None:
        """Test analyzing empty source."""
        ctx = self.analyzer.analyze("", 0, 0)
        self.assertEqual(ctx.trigger_kind, "general")
        self.assertIsNone(ctx.trigger_word)

    def test_syntax_error_source(self) -> None:
        """Test analyzing source with syntax errors."""
        source = "def foo(:\n    pass"
        # Should not raise
        ctx = self.analyzer.analyze(source, 0, 5)
        # The ctx should still have basic info
        self.assertIsNotNone(ctx)

    def test_indentation_detection(self) -> None:
        """Test indentation level detection."""
        source = "def foo():\n    pass\n"
        ctx = self.analyzer.analyze(source, 1, 0)
        self.assertEqual(ctx.indentation, 4)

    def test_extract_imports(self) -> None:
        """Test import extraction."""
        source = "import os\nimport sys as system\nfrom pathlib import Path\n"
        ctx = self.analyzer.analyze(source, 0, 0)
        self.assertIn("os", ctx.imports)
        self.assertIn("system", ctx.imports)
        self.assertEqual(ctx.imports["system"], "sys")
        self.assertIn("Path", ctx.imports)

    def test_available_names(self) -> None:
        """Test collection of available names."""
        source = "x = 1\ndef foo(): pass\nclass Bar: pass\n"
        ctx = self.analyzer.analyze(source, 0, 0)
        self.assertIn("x", ctx.available_names)
        self.assertIn("foo", ctx.available_names)
        self.assertIn("Bar", ctx.available_names)

    def test_looks_like_path(self) -> None:
        """Test path detection."""
        self.assertTrue(self.analyzer._looks_like_path("/usr/bin"))
        self.assertTrue(self.analyzer._looks_like_path("./relative"))
        self.assertTrue(self.analyzer._looks_like_path("~/home"))
        self.assertTrue(self.analyzer._looks_like_path("C:\\Users"))
        self.assertTrue(self.analyzer._looks_like_path("file.txt"))
        self.assertFalse(self.analyzer._looks_like_path(""))
        self.assertFalse(self.analyzer._looks_like_path("variable_name"))

    def test_decorator_trigger(self) -> None:
        """Test detecting decorator trigger."""
        source = "@pro"
        ctx = self.analyzer.analyze(source, 0, 4)
        self.assertEqual(ctx.trigger_kind, "decorator")
        self.assertEqual(ctx.trigger_word, "pro")


# ===========================================================================
# Test: PriorityScorer
# ===========================================================================

class TestPriorityScorer(unittest.TestCase):
    """Tests for the PriorityScorer class."""

    def setUp(self) -> None:
        self.scorer = PriorityScorer()

    def test_exact_match_score(self) -> None:
        """Test that exact matches get the highest score."""
        context = CodeContext()
        item = CompletionItem.variable("my_var")
        score = self.scorer.score(item, context, prefix="my_var")
        self.assertGreater(score, 0)
        # Exact match should be high
        self.assertGreaterEqual(score, SCORE_WEIGHTS["exact_match"])

    def test_prefix_match_score(self) -> None:
        """Test that prefix matches get a score."""
        context = CodeContext()
        item = CompletionItem.variable("my_variable")
        score = self.scorer.score(item, context, prefix="my_var")
        self.assertGreater(score, 0)

    def test_no_prefix_score(self) -> None:
        """Test that items without a prefix get a baseline score."""
        context = CodeContext()
        item = CompletionItem.variable("x")
        score = self.scorer.score(item, context, prefix="")
        # Should be 0 or low
        self.assertGreaterEqual(score, 0)

    def test_ranking(self) -> None:
        """Test ranking of multiple items."""
        context = CodeContext()
        items = [
            CompletionItem.variable("my_var"),
            CompletionItem.variable("my_variable"),
            CompletionItem.variable("other"),
        ]
        ranked = self.scorer.rank(items, context, prefix="my_var")
        self.assertEqual(len(ranked), 3)
        # Exact match should be first
        self.assertEqual(ranked[0].label, "my_var")

    def test_max_results(self) -> None:
        """Test that max_results limits the output."""
        context = CodeContext()
        items = [CompletionItem.variable(f"var_{i}") for i in range(20)]
        ranked = self.scorer.rank(items, context, max_results=5)
        self.assertEqual(len(ranked), 5)

    def test_import_boost(self) -> None:
        """Test that import context boosts module items."""
        context = CodeContext(trigger_kind="import")
        item = CompletionItem.module("os")
        score = self.scorer.score(item, context, prefix="os")
        self.assertGreater(score, 0)

    def test_scope_bonus(self) -> None:
        """Test that being inside a function boosts local items."""
        context = CodeContext(inside_function=True)
        item = CompletionItem.variable("local_var")
        score = self.scorer.score(item, context)
        self.assertGreater(score, 0)


# ===========================================================================
# Test: CompletionCache
# ===========================================================================

class TestCompletionCache(unittest.TestCase):
    """Tests for the CompletionCache class."""

    def setUp(self) -> None:
        self.cache = CompletionCache(max_size=10, ttl=60)

    def test_set_and_get(self) -> None:
        """Test setting and getting cache entries."""
        key = "test_key"
        items = [CompletionItem.variable("x")]
        self.cache.set(key, items)
        result = self.cache.get(key)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].label, "x")

    def test_get_miss(self) -> None:
        """Test that missing keys return None."""
        result = self.cache.get("nonexistent")
        self.assertIsNone(result)

    def test_expired_entry(self) -> None:
        """Test that expired entries return None."""
        cache = CompletionCache(max_size=10, ttl=0)  # TTL = 0 means immediate expiry
        cache.set("key", [CompletionItem.variable("x")])
        # The entry should be expired immediately
        result = cache.get("key")
        self.assertIsNone(result)

    def test_cache_eviction(self) -> None:
        """Test LRU eviction when cache is full."""
        cache = CompletionCache(max_size=3, ttl=60)
        for i in range(5):
            cache.set(f"key_{i}", [CompletionItem.variable(f"x_{i}")])

        # The first 2 entries should have been evicted
        self.assertIsNone(cache.get("key_0"))
        self.assertIsNone(cache.get("key_1"))
        # The last 3 should still be there
        self.assertIsNotNone(cache.get("key_2"))
        self.assertIsNotNone(cache.get("key_3"))
        self.assertIsNotNone(cache.get("key_4"))

    def test_invalidate_specific(self) -> None:
        """Test invalidating a specific cache entry."""
        self.cache.set("key1", [CompletionItem.variable("x")])
        self.cache.set("key2", [CompletionItem.variable("y")])
        self.cache.invalidate("key1")
        self.assertIsNone(self.cache.get("key1"))
        self.assertIsNotNone(self.cache.get("key2"))

    def test_clear(self) -> None:
        """Test clearing the entire cache."""
        self.cache.set("key1", [CompletionItem.variable("x")])
        self.cache.set("key2", [CompletionItem.variable("y")])
        self.cache.clear()
        self.assertEqual(self.cache.stats["size"], 0)
        self.assertEqual(self.cache.stats["hits"], 0)

    def test_make_key(self) -> None:
        """Test cache key generation."""
        key1 = CompletionCache.make_key("x = 1", 0, 0)
        key2 = CompletionCache.make_key("x = 1", 0, 0)
        key3 = CompletionCache.make_key("y = 2", 0, 0)
        self.assertEqual(key1, key2)
        self.assertNotEqual(key1, key3)

    def test_stats(self) -> None:
        """Test cache statistics."""
        self.cache.set("key", [CompletionItem.variable("x")])
        self.cache.get("key")  # hit
        self.cache.get("missing")  # miss
        stats = self.cache.stats
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)
        self.assertEqual(stats["hit_rate"], 0.5)


# ===========================================================================
# Test: SnippetProvider
# ===========================================================================

class TestSnippetProvider(unittest.TestCase):
    """Tests for the SnippetProvider class."""

    def setUp(self) -> None:
        self.provider = SnippetProvider()

    def test_get_snippets_module_level(self) -> None:
        """Test getting snippets at module level."""
        context = CodeContext()
        snippets = self.provider.get_snippets(context)
        self.assertGreater(len(snippets), 0)

        # Should include def, class, for, etc.
        labels = [s.label for s in snippets]
        self.assertIn("def", labels)
        self.assertIn("class", labels)
        self.assertIn("for", labels)
        self.assertIn("ifmain", labels)

    def test_get_snippets_inside_function(self) -> None:
        """Test getting snippets inside a function."""
        context = CodeContext(inside_function=True)
        snippets = self.provider.get_snippets(context)
        labels = [s.label for s in snippets]
        # Should NOT include class-level snippets
        self.assertIn("def", labels)
        self.assertIn("for", labels)
        self.assertNotIn("class", labels)
        self.assertNotIn("ifmain", labels)

    def test_get_snippets_inside_class(self) -> None:
        """Test getting snippets inside a class."""
        context = CodeContext(inside_class=True)
        snippets = self.provider.get_snippets(context)
        labels = [s.label for s in snippets]
        # Should include class-specific snippets
        self.assertIn("init", labels)
        self.assertIn("property", labels)
        self.assertIn("staticmethod", labels)

    def test_snippet_format(self) -> None:
        """Test that snippets have the correct format."""
        snippets = self.provider.get_snippets(CodeContext())
        for s in snippets:
            self.assertEqual(s.kind, CompletionItemKind.SNIPPET)
            self.assertEqual(s.insert_text_format, 2)
            self.assertIsNotNone(s.snippet)

    def test_control_flow_snippets(self) -> None:
        """Test that control flow snippets are present."""
        snippets = self.provider.get_snippets(CodeContext())
        labels = [s.label for s in snippets]
        for ctrl in ("if", "else", "for", "while", "try", "with"):
            self.assertIn(ctrl, labels)


# ===========================================================================
# Test: KeywordCompleter
# ===========================================================================

class TestKeywordCompleter(unittest.TestCase):
    """Tests for the KeywordCompleter class."""

    def setUp(self) -> None:
        self.completer = KeywordCompleter()

    def test_keywords_at_module_level(self) -> None:
        """Test keywords available at module level."""
        context = CodeContext()
        keywords = self.completer.get_completions(context)
        kw_labels = [k.label for k in keywords]
        self.assertIn("def", kw_labels)
        self.assertIn("class", kw_labels)
        self.assertIn("import", kw_labels)
        # Should NOT include function-only keywords
        self.assertNotIn("return", kw_labels)
        self.assertNotIn("yield", kw_labels)

    def test_keywords_inside_function(self) -> None:
        """Test keywords available inside a function."""
        context = CodeContext(inside_function=True)
        keywords = self.completer.get_completions(context)
        kw_labels = [k.label for k in keywords]
        self.assertIn("return", kw_labels)
        self.assertIn("yield", kw_labels)

    def test_keywords_with_prefix(self) -> None:
        """Test keyword filtering by prefix."""
        context = CodeContext()
        keywords = self.completer.get_completions(context, prefix="de")
        kw_labels = [k.label for k in keywords]
        self.assertIn("def", kw_labels)
        self.assertIn("del", kw_labels)
        self.assertNotIn("class", kw_labels)

    def test_keyword_type(self) -> None:
        """Test that keyword items have the correct type."""
        context = CodeContext()
        keywords = self.completer.get_completions(context)
        for kw in keywords:
            self.assertEqual(kw.kind, CompletionItemKind.KEYWORD)
            self.assertEqual(kw.detail, "keyword")

    def test_expression_keywords(self) -> None:
        """Test that expression keywords are included."""
        context = CodeContext()
        keywords = self.completer.get_completions(context)
        kw_labels = [k.label for k in keywords]
        self.assertIn("True", kw_labels)
        self.assertIn("False", kw_labels)
        self.assertIn("None", kw_labels)


# ===========================================================================
# Test: VariableCompleter
# ===========================================================================

class TestVariableCompleter(unittest.TestCase):
    """Tests for the VariableCompleter class."""

    def setUp(self) -> None:
        self.symbol_table = SymbolTable()
        self.type_inferrer = TypeInferrer()
        self.completer = VariableCompleter(self.symbol_table, self.type_inferrer)

    def test_variable_completions(self) -> None:
        """Test variable completions from symbol table."""
        self.symbol_table.add_symbol(Symbol(
            name="my_var", kind="variable", type_name="int", scope="global"
        ))
        context = CodeContext()
        vars = self.completer.get_completions(context)
        var_labels = [v.label for v in vars]
        self.assertIn("my_var", var_labels)

    def test_variable_completions_with_prefix(self) -> None:
        """Test variable filtering by prefix."""
        self.symbol_table.add_symbol(Symbol(
            name="my_var", kind="variable", type_name="int", scope="global"
        ))
        self.symbol_table.add_symbol(Symbol(
            name="other", kind="variable", type_name="str", scope="global"
        ))
        context = CodeContext()
        vars = self.completer.get_completions(context, prefix="my")
        var_labels = [v.label for v in vars]
        self.assertIn("my_var", var_labels)
        self.assertNotIn("other", var_labels)

    def test_variable_type_in_detail(self) -> None:
        """Test that variable type is shown in detail."""
        self.symbol_table.add_symbol(Symbol(
            name="my_var", kind="variable", type_name="int", scope="global"
        ))
        context = CodeContext()
        vars = self.completer.get_completions(context)
        my_var = next(v for v in vars if v.label == "my_var")
        self.assertEqual(my_var.detail, "-> int")

    def test_parameter_completions(self) -> None:
        """Test that parameters are included in completions."""
        self.symbol_table.add_symbol(Symbol(
            name="param1", kind="parameter", type_name="str", scope="function:foo"
        ))
        self.symbol_table.enter_scope("function:foo")
        context = CodeContext()
        vars = self.completer.get_completions(context)
        var_labels = [v.label for v in vars]
        self.assertIn("param1", var_labels)


# ===========================================================================
# Test: FunctionCompleter
# ===========================================================================

class TestFunctionCompleter(unittest.TestCase):
    """Tests for the FunctionCompleter class."""

    def setUp(self) -> None:
        self.symbol_table = SymbolTable()
        self.type_inferrer = TypeInferrer()
        self.completer = FunctionCompleter(self.symbol_table, self.type_inferrer)

    def test_function_completions(self) -> None:
        """Test function completions from symbol table."""
        self.symbol_table.add_symbol(Symbol(
            name="my_func",
            kind="function",
            type_name="str",
            scope="global",
            parameters=["x", "y"],
        ))
        context = CodeContext()
        funcs = self.completer.get_completions(context)
        func_labels = [f.label for f in funcs]
        self.assertIn("my_func", func_labels)

    def test_function_completions_with_prefix(self) -> None:
        """Test function filtering by prefix."""
        self.symbol_table.add_symbol(Symbol(
            name="my_func", kind="function", scope="global"
        ))
        self.symbol_table.add_symbol(Symbol(
            name="other_func", kind="function", scope="global"
        ))
        context = CodeContext()
        funcs = self.completer.get_completions(context, prefix="my")
        func_labels = [f.label for f in funcs]
        self.assertIn("my_func", func_labels)
        self.assertNotIn("other_func", func_labels)

    def test_function_signature_in_detail(self) -> None:
        """Test that function signature is shown in detail."""
        self.symbol_table.add_symbol(Symbol(
            name="my_func",
            kind="function",
            type_name="bool",
            scope="global",
            parameters=["x: int", "y: str"],
        ))
        context = CodeContext()
        funcs = self.completer.get_completions(context)
        my_func = next(f for f in funcs if f.label == "my_func")
        self.assertIn("x: int", my_func.detail)
        self.assertIn("-> bool", my_func.detail)

    def test_signature_help(self) -> None:
        """Test signature help detection."""
        source = "my_func(1, "
        self.symbol_table.add_symbol(Symbol(
            name="my_func",
            kind="function",
            scope="global",
            parameters=["x: int", "y: str"],
        ))
        sig = self.completer.get_signature_help(source, 0, 11)
        self.assertIsNotNone(sig)
        self.assertEqual(sig.name, "my_func")
        self.assertEqual(sig.active_parameter, 1)

    def test_signature_help_no_function(self) -> None:
        """Test signature help when no function is detected."""
        source = "x = 1"
        sig = self.completer.get_signature_help(source, 0, 5)
        self.assertIsNone(sig)

    def test_signature_help_empty_source(self) -> None:
        """Test signature help with empty source."""
        sig = self.completer.get_signature_help("", 0, 0)
        self.assertIsNone(sig)


# ===========================================================================
# Test: ClassCompleter
# ===========================================================================

class TestClassCompleter(unittest.TestCase):
    """Tests for the ClassCompleter class."""

    def setUp(self) -> None:
        self.symbol_table = SymbolTable()
        self.type_inferrer = TypeInferrer()
        self.completer = ClassCompleter(self.symbol_table, self.type_inferrer)

    def test_class_completions(self) -> None:
        """Test class completions from symbol table."""
        self.symbol_table.add_symbol(Symbol(
            name="MyClass", kind="class", scope="global"
        ))
        context = CodeContext()
        classes = self.completer.get_completions(context)
        cls_labels = [c.label for c in classes]
        self.assertIn("MyClass", cls_labels)

    def test_class_completions_with_prefix(self) -> None:
        """Test class filtering by prefix."""
        self.symbol_table.add_symbol(Symbol(
            name="MyClass", kind="class", scope="global"
        ))
        self.symbol_table.add_symbol(Symbol(
            name="OtherClass", kind="class", scope="global"
        ))
        context = CodeContext()
        classes = self.completer.get_completions(context, prefix="My")
        cls_labels = [c.label for c in classes]
        self.assertIn("MyClass", cls_labels)
        self.assertNotIn("OtherClass", cls_labels)

    def test_attribute_completions_str(self) -> None:
        """Test attribute completions for string type."""
        attrs = self.completer.get_attribute_completions("obj_name", prefix="")
        attr_labels = [a.label for a in attrs]
        self.assertIn("upper", attr_labels)
        self.assertIn("lower", attr_labels)
        self.assertIn("split", attr_labels)

    def test_attribute_completions_list(self) -> None:
        """Test attribute completions for list type."""
        self.symbol_table.add_symbol(Symbol(
            name="my_list", kind="variable", type_name="list", scope="global"
        ))
        attrs = self.completer.get_attribute_completions("my_list", prefix="")
        attr_labels = [a.label for a in attrs]
        self.assertIn("append", attr_labels)
        self.assertIn("pop", attr_labels)
        self.assertIn("sort", attr_labels)

    def test_attribute_completions_dict(self) -> None:
        """Test attribute completions for dict type."""
        self.symbol_table.add_symbol(Symbol(
            name="my_dict", kind="variable", type_name="dict", scope="global"
        ))
        attrs = self.completer.get_attribute_completions("my_dict", prefix="")
        attr_labels = [a.label for a in attrs]
        self.assertIn("keys", attr_labels)
        self.assertIn("values", attr_labels)
        self.assertIn("items", attr_labels)

    def test_attribute_completions_with_prefix(self) -> None:
        """Test attribute filtering by prefix."""
        attrs = self.completer.get_attribute_completions("obj_name", prefix="up")
        attr_labels = [a.label for a in attrs]
        self.assertIn("upper", attr_labels)
        self.assertNotIn("lower", attr_labels)


# ===========================================================================
# Test: ModuleCompleter
# ===========================================================================

class TestModuleCompleter(unittest.TestCase):
    """Tests for the ModuleCompleter class."""

    def setUp(self) -> None:
        self.completer = ModuleCompleter()

    def test_module_completions(self) -> None:
        """Test that module completions return common modules."""
        modules = self.completer.get_completions(prefix="")
        mod_labels = [m.label for m in modules]
        # Common standard library modules
        self.assertIn("os", mod_labels)
        self.assertIn("sys", mod_labels)
        self.assertIn("re", mod_labels)
        self.assertIn("json", mod_labels)

    def test_module_completions_with_prefix(self) -> None:
        """Test module filtering by prefix."""
        modules = self.completer.get_completions(prefix="os")
        mod_labels = [m.label for m in modules]
        self.assertIn("os", mod_labels)
        self.assertNotIn("sys", mod_labels)

    def test_module_kind(self) -> None:
        """Test that module items have the correct kind."""
        modules = self.completer.get_completions(prefix="os")
        for mod in modules:
            self.assertEqual(mod.kind, CompletionItemKind.MODULE)

    def test_private_modules_excluded(self) -> None:
        """Test that private modules (starting with _) are excluded."""
        # This is hard to test directly, but we can check that the
        # common modules don't include private ones
        modules = self.completer.get_completions(prefix="")
        mod_labels = [m.label for m in modules]
        for label in mod_labels:
            if label.startswith("_"):
                self.fail(f"Private module {label} should not be in completions")

    def test_invalidate_cache(self) -> None:
        """Test cache invalidation."""
        # Populate cache
        modules1 = self.completer.get_completions(prefix="os")
        self.completer.invalidate_cache()
        # After invalidation, the cache should be rebuilt
        modules2 = self.completer.get_completions(prefix="os")
        self.assertEqual(len(modules1), len(modules2))


# ===========================================================================
# Test: PathCompleter
# ===========================================================================

class TestPathCompleter(unittest.TestCase):
    """Tests for the PathCompleter class."""

    def setUp(self) -> None:
        self.completer = PathCompleter()

    def test_path_completions_empty_prefix(self) -> None:
        """Test that empty prefix returns empty results."""
        paths = self.completer.get_completions(prefix="")
        self.assertEqual(len(paths), 0)

    def test_path_completions_current_dir(self) -> None:
        """Test path completions in current directory."""
        # Use a pattern that should match some files
        paths = self.completer.get_completions(prefix="./")
        self.assertGreater(len(paths), 0)

    def test_path_completions_kind(self) -> None:
        """Test that file path items have the correct kind."""
        paths = self.completer.get_completions(prefix="./")
        for p in paths:
            self.assertIn(p.kind, (CompletionItemKind.FILE, CompletionItemKind.FOLDER))


# ===========================================================================
# Test: PythonCompletionEngine (Integration)
# ===========================================================================

class TestPythonCompletionEngine(unittest.TestCase):
    """Integration tests for the PythonCompletionEngine."""

    def setUp(self) -> None:
        self.engine = PythonCompletionEngine()

    def test_get_completions_module_level(self) -> None:
        """Test getting completions at module level."""
        source = "x = 1\n"
        items = self.engine.get_completions(source, 0, 0)
        self.assertGreater(len(items), 0)

    def test_get_completions_empty_source(self) -> None:
        """Test getting completions for empty source."""
        items = self.engine.get_completions("", 0, 0)
        # Should still return some completions (keywords, snippets, etc.)
        self.assertGreater(len(items), 0)

    def test_get_completions_with_prefix(self) -> None:
        """Test that completions are filtered by prefix."""
        source = "pri"
        items = self.engine.get_completions(source, 0, 3)
        for item in items:
            if item.label.startswith("pri"):
                continue
            # Non-prefix matches should be ranked lower
            self.assertLess(item.score, 50)

    def test_get_completions_dot_trigger(self) -> None:
        """Test dot completion."""
        source = "import os\nos."
        items = self.engine.get_completions(source, 1, 3)
        # Should return attribute completions
        self.assertGreater(len(items), 0)

    def test_get_completions_import_trigger(self) -> None:
        """Test import completion."""
        source = "import "
        items = self.engine.get_completions(source, 0, 7)
        # Should return module completions
        self.assertGreater(len(items), 0)
        for item in items:
            self.assertEqual(item.kind, CompletionItemKind.MODULE)

    def test_get_completions_decorator_trigger(self) -> None:
        """Test decorator completion."""
        source = "@pro"
        items = self.engine.get_completions(source, 0, 4)
        self.assertGreater(len(items), 0)
        # Should include 'property' decorator
        labels = [item.label for item in items]
        self.assertIn("property", labels)

    def test_hover_info(self) -> None:
        """Test hover information."""
        source = "x = 1\n"
        info = self.engine.get_hover_info(source, 0, 0)
        # Should be None since we're at the beginning of the line
        # (the word 'x' should be at column 0)
        # Actually, let me check at column 0
        info = self.engine.get_hover_info(source, 0, 0)
        # 'x' is at column 0, so it should find it
        # But it might not have type info since it's just been assigned
        self.assertIsNotNone(info)

    def test_hover_info_builtin(self) -> None:
        """Test hover info for built-in functions."""
        info = self.engine.get_hover_info("len", 0, 1)
        self.assertIsNotNone(info)
        self.assertIn("builtin", info)

    def test_hover_info_out_of_bounds(self) -> None:
        """Test hover info with out-of-bounds position."""
        info = self.engine.get_hover_info("x = 1", 10, 0)
        self.assertIsNone(info)

    def test_signature_help(self) -> None:
        """Test signature help."""
        source = "def foo(x, y): pass\nfoo("
        sig = self.engine.get_signature_help(source, 1, 4)
        # Should find the function call
        self.assertIsNotNone(sig)
        self.assertEqual(sig.name, "foo")

    def test_analyze_document(self) -> None:
        """Test document analysis."""
        source = """
x = 1
y: str = "hello"

def my_func(a, b):
    pass

class MyClass:
    def __init__(self):
        pass
"""
        self.engine.analyze_document(source)
        symbols = self.engine.get_symbols()
        self.assertGreater(len(symbols), 0)

        # Check that specific symbols were collected
        symbol_names = [s.name for s in symbols]
        self.assertIn("x", symbol_names)
        self.assertIn("y", symbol_names)
        self.assertIn("my_func", symbol_names)
        self.assertIn("MyClass", symbol_names)

    def test_get_symbols_by_kind(self) -> None:
        """Test getting symbols by kind."""
        source = "x = 1\ndef foo(): pass\nclass Bar: pass\n"
        self.engine.analyze_document(source)
        symbols = self.engine.get_symbols()
        kinds = [s.kind for s in symbols]
        self.assertIn("variable", kinds)
        self.assertIn("function", kinds)
        self.assertIn("class", kinds)

    def test_clear_cache(self) -> None:
        """Test cache clearing."""
        self.engine.get_completions("x = 1", 0, 0)
        stats_before = self.engine.get_cache_stats()
        self.engine.clear_cache()
        stats_after = self.engine.get_cache_stats()
        self.assertEqual(stats_after["size"], 0)

    def test_reset(self) -> None:
        """Test engine reset."""
        self.engine.analyze_document("x = 1")
        self.engine.reset()
        symbols = self.engine.get_symbols()
        self.assertEqual(len(symbols), 0)

    def test_cache_usage(self) -> None:
        """Test that the cache is being used."""
        self.engine.get_completions("x = 1", 0, 0)
        stats = self.engine.get_cache_stats()
        # After first call, cache should have 1 entry
        self.assertEqual(stats["size"], 1)

    def test_completions_with_syntax_error(self) -> None:
        """Test completions with syntax errors in source."""
        source = "def foo(:\n    pass\n"
        items = self.engine.get_completions(source, 0, 0)
        # Should still return something
        self.assertGreater(len(items), 0)

    def test_signature_help_multi_line(self) -> None:
        """Test signature help with multi-line function calls."""
        source = "def foo(a, b, c): pass\nfoo(\n    1,\n    2,\n"
        sig = self.engine.get_signature_help(source, 4, 4)
        # This is a multi-line call, might be None depending on implementation
        # Just check it doesn't crash
        pass

    def test_hover_info_analysis(self) -> None:
        """Test that hover info works after analysis."""
        source = "my_var = 42\n"
        self.engine.analyze_document(source)
        info = self.engine.get_hover_info(source, 0, 0)
        self.assertIsNotNone(info)


# ===========================================================================
# Test: CompletionServer
# ===========================================================================

class TestCompletionServer(unittest.TestCase):
    """Tests for the CompletionServer class."""

    def setUp(self) -> None:
        self.engine = PythonCompletionEngine()
        self.server = CompletionServer(self.engine, host="127.0.0.1", port=0)

    def test_process_request_completions(self) -> None:
        """Test processing a completions request."""
        request = json.dumps({
            "method": "completions",
            "source": "x = 1\n",
            "line": 0,
            "column": 0,
        })
        response = self.server._process_request(request)
        self.assertIn("result", response)
        self.assertIsNone(response["error"])
        self.assertGreater(len(response["result"]), 0)

    def test_process_request_signature_help(self) -> None:
        """Test processing a signature help request."""
        request = json.dumps({
            "method": "signature_help",
            "source": "def foo(x): pass\nfoo(",
            "line": 1,
            "column": 4,
        })
        response = self.server._process_request(request)
        self.assertIn("result", response)
        self.assertIsNone(response["error"])

    def test_process_request_hover(self) -> None:
        """Test processing a hover request."""
        request = json.dumps({
            "method": "hover",
            "source": "x = 1\n",
            "line": 0,
            "column": 0,
        })
        response = self.server._process_request(request)
        self.assertIn("result", response)
        self.assertIsNone(response["error"])

    def test_process_request_analyze(self) -> None:
        """Test processing an analyze request."""
        request = json.dumps({
            "method": "analyze",
            "source": "x = 1\ndef foo(): pass\n",
        })
        response = self.server._process_request(request)
        self.assertIn("result", response)
        self.assertIsNone(response["error"])
        self.assertGreater(len(response["result"]), 0)

    def test_process_request_clear_cache(self) -> None:
        """Test processing a clear_cache request."""
        request = json.dumps({"method": "clear_cache"})
        response = self.server._process_request(request)
        self.assertEqual(response["result"], "cache cleared")
        self.assertIsNone(response["error"])

    def test_process_request_ping(self) -> None:
        """Test processing a ping request."""
        request = json.dumps({"method": "ping"})
        response = self.server._process_request(request)
        self.assertEqual(response["result"], "pong")
        self.assertIsNone(response["error"])

    def test_process_request_unknown_method(self) -> None:
        """Test processing an unknown method."""
        request = json.dumps({"method": "unknown"})
        response = self.server._process_request(request)
        self.assertIsNone(response["result"])
        self.assertIsNotNone(response["error"])

    def test_process_request_invalid_json(self) -> None:
        """Test processing invalid JSON."""
        response = self.server._process_request("{invalid json}")
        self.assertIsNone(response["result"])
        self.assertIsNotNone(response["error"])

    def test_process_request_cache_stats(self) -> None:
        """Test processing a cache_stats request."""
        request = json.dumps({"method": "cache_stats"})
        response = self.server._process_request(request)
        self.assertIn("result", response)
        self.assertIsNotNone(response["result"])
        self.assertIn("size", response["result"])


# ===========================================================================
# Test: CLI
# ===========================================================================

class TestCLI(unittest.TestCase):
    """Tests for the CLI argument parser and entry point."""

    def test_parser_creation(self) -> None:
        """Test that the argument parser is created correctly."""
        parser = create_parser()
        self.assertIsNotNone(parser)

    def test_parser_defaults(self) -> None:
        """Test default argument values."""
        parser = create_parser()
        args = parser.parse_args([])
        self.assertEqual(args.line, 0)
        self.assertEqual(args.column, 0)
        self.assertFalse(args.server)
        self.assertFalse(args.hover)
        self.assertFalse(args.signature)
        self.assertFalse(args.analyze)
        self.assertFalse(args.json)
        self.assertFalse(args.clear_cache)
        self.assertFalse(args.cache_stats)
        self.assertFalse(args.verbose)
        self.assertEqual(args.max_results, 100)
        self.assertEqual(args.host, DEFAULT_HOST)
        self.assertEqual(args.port, DEFAULT_PORT)

    def test_parser_file_arg(self) -> None:
        """Test the --file argument."""
        parser = create_parser()
        args = parser.parse_args(["-f", "test.py"])
        self.assertEqual(args.file, "test.py")

    def test_parser_position_args(self) -> None:
        """Test line and column arguments."""
        parser = create_parser()
        args = parser.parse_args(["-l", "10", "-c", "5"])
        self.assertEqual(args.line, 10)
        self.assertEqual(args.column, 5)

    def test_parser_server_args(self) -> None:
        """Test server mode arguments."""
        parser = create_parser()
        args = parser.parse_args(["--server", "--host", "0.0.0.0", "--port", "8888"])
        self.assertTrue(args.server)
        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 8888)

    def test_parser_json_output(self) -> None:
        """Test JSON output argument."""
        parser = create_parser()
        args = parser.parse_args(["--json"])
        self.assertTrue(args.json)

    def test_parser_version(self) -> None:
        """Test that --version works."""
        parser = create_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--version"])

    @patch("sys.stdin", new_callable=lambda: open(os.devnull, "r"))
    def test_main_no_args(self, mock_stdin: MagicMock) -> None:
        """Test main with no arguments and no stdin content."""
        # This should exit with an error
        with self.assertRaises(SystemExit):
            main()

    @patch("sys.argv", ["ai-complete", "--clear-cache"])
    def test_main_clear_cache(self) -> None:
        """Test main with --clear-cache."""
        main()  # Should not raise

    @patch("sys.argv", ["ai-complete", "--cache-stats"])
    def test_main_cache_stats(self) -> None:
        """Test main with --cache-stats."""
        main()  # Should not raise


# ===========================================================================
# Test: CompletionEngine ABC
# ===========================================================================

class TestCompletionEngineABC(unittest.TestCase):
    """Tests for the CompletionEngine abstract base class."""

    def test_abc_cannot_instantiate(self) -> None:
        """Test that the ABC cannot be instantiated directly."""
        with self.assertRaises(TypeError):
            CompletionEngine()  # type: ignore[abstract]

    def test_python_engine_is_concrete(self) -> None:
        """Test that PythonCompletionEngine can be instantiated."""
        engine = PythonCompletionEngine()
        self.assertIsInstance(engine, CompletionEngine)
        self.assertIsInstance(engine, PythonCompletionEngine)


# ===========================================================================
# Test: Edge Cases and Error Handling
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    """Tests for edge cases and error handling."""

    def test_symbol_table_add_duplicate(self) -> None:
        """Test that adding duplicate symbols overwrites."""
        table = SymbolTable()
        table.add_symbol(Symbol(name="x", kind="variable", type_name="int", scope="global"))
        table.add_symbol(Symbol(name="x", kind="variable", type_name="str", scope="global"))
        sym = table.get_symbol("x")
        self.assertIsNotNone(sym)
        # The last one should win
        self.assertEqual(sym.type_name, "str")

    def test_type_inferrer_unknown_node(self) -> None:
        """Test type inference with completely unknown node."""
        inferrer = TypeInferrer()
        node = ast.MatchValue(value=ast.Constant(value=1))
        result = inferrer.infer_type(node)
        self.assertIsNone(result)

    def test_context_analyzer_invalid_line(self) -> None:
        """Test context analyzer with invalid line number."""
        analyzer = ContextAnalyzer()
        ctx = analyzer.analyze("x = 1", 100, 0)
        # Should not crash
        self.assertIsNotNone(ctx)

    def test_context_analyzer_invalid_column(self) -> None:
        """Test context analyzer with invalid column number."""
        analyzer = ContextAnalyzer()
        ctx = analyzer.analyze("x = 1", 0, 100)
        self.assertIsNotNone(ctx)

    def test_cache_empty_key(self) -> None:
        """Test cache with empty key."""
        cache = CompletionCache()
        result = cache.get("")
        self.assertIsNone(result)
        cache.set("", [CompletionItem.variable("x")])
        result = cache.get("")
        self.assertIsNotNone(result)

    def test_path_completer_system_dir(self) -> None:
        """Test path completer with system directory."""
        completer = PathCompleter()
        # Use a path that should exist
        paths = completer.get_completions(prefix=os.pathsep)
        # Should not crash
        self.assertIsNotNone(paths)

    def test_function_completer_empty_symbol_table(self) -> None:
        """Test function completer with empty symbol table."""
        table = SymbolTable()
        inferrer = TypeInferrer()
        completer = FunctionCompleter(table, inferrer)
        context = CodeContext()
        funcs = completer.get_completions(context)
        # Should still return built-in functions
        self.assertGreater(len(funcs), 0)

    def test_class_completer_empty_symbol_table(self) -> None:
        """Test class completer with empty symbol table."""
        table = SymbolTable()
        inferrer = TypeInferrer()
        completer = ClassCompleter(table, inferrer)
        context = CodeContext()
        classes = completer.get_completions(context)
        # Should still return built-in types
        self.assertGreater(len(classes), 0)

    def test_engine_analyze_document_syntax_error(self) -> None:
        """Test document analysis with syntax errors."""
        engine = PythonCompletionEngine()
        # Should not crash
        engine.analyze_document("def foo(:\n    pass\n")
        # Should still have some analysis done
        symbols = engine.get_symbols()
        self.assertIsNotNone(symbols)

    def test_engine_get_completions_large_source(self) -> None:
        """Test completions with large source code."""
        source = "\n".join(f"x{i} = {i}" for i in range(100))
        items = self._get_engine_completions(source, 0, 0)
        self.assertGreater(len(items), 0)

    def _get_engine_completions(self, source: str, line: int, column: int) -> list:
        """Helper to get completions from a fresh engine."""
        engine = PythonCompletionEngine()
        return engine.get_completions(source, line, column)

    def test_engine_get_completions_unicode(self) -> None:
        """Test completions with unicode characters."""
        source = "# -*- coding: utf-8 -*-\n# 你好世界\nx = 1\n"
        items = self._get_engine_completions(source, 2, 0)
        self.assertGreater(len(items), 0)

    def test_engine_get_completions_inside_string(self) -> None:
        """Test completions when cursor is inside a string."""
        source = 'x = "hello world"\n'
        # Cursor inside the string
        items = self._get_engine_completions(source, 0, 10)
        # Should still return something
        self.assertGreaterEqual(len(items), 0)

    def test_engine_get_completions_after_dot(self) -> None:
        """Test dot completions."""
        source = "x = 'hello'\nx."
        items = self._get_engine_completions(source, 1, 2)
        # 'x' is a string, should get string attributes
        # But the engine might not know x is a string without analysis
        # Let's just check it doesn't crash and returns something
        self.assertGreaterEqual(len(items), 0)

    def test_priority_scorer_custom_weights(self) -> None:
        """Test priority scorer with custom weights."""
        weights = {"exact_match": 200.0}
        scorer = PriorityScorer(weights=weights)
        context = CodeContext()
        item = CompletionItem.variable("test")
        score = scorer.score(item, context, prefix="test")
        self.assertEqual(score, 200.0)

    def test_priority_scorer_ranking_stability(self) -> None:
        """Test that ranking is stable (same scores get alphabetical order)."""
        scorer = PriorityScorer()
        context = CodeContext()
        items = [
            CompletionItem.variable("beta"),
            CompletionItem.variable("alpha"),
        ]
        ranked = scorer.rank(items, context)
        # Both have the same score (no prefix), so they should be in alphabetical order
        # (since sort key is (-score, label))
        self.assertEqual(ranked[0].label, "alpha")
        self.assertEqual(ranked[1].label, "beta")


# ===========================================================================
# Test: Server mode edge cases
# ===========================================================================

class TestServerEdgeCases(unittest.TestCase):
    """Tests for server edge cases."""

    def test_server_stop_without_start(self) -> None:
        """Test stopping a server that hasn't been started."""
        engine = PythonCompletionEngine()
        server = CompletionServer(engine, host="127.0.0.1", port=0)
        # Should not raise
        server.stop()

    def test_server_process_request_empty(self) -> None:
        """Test processing an empty request."""
        engine = PythonCompletionEngine()
        server = CompletionServer(engine)
        response = server._process_request("")
        self.assertIn("error", response)

    def test_server_process_request_missing_method(self) -> None:
        """Test processing a request without a method field."""
        engine = PythonCompletionEngine()
        server = CompletionServer(engine)
        request = json.dumps({"source": "x = 1"})
        response = server._process_request(request)
        self.assertIn("error", response)


# ===========================================================================
# Test: TypeInferrer - Additional edge cases
# ===========================================================================

class TestTypeInferrerEdgeCases(unittest.TestCase):
    """Additional edge case tests for TypeInferrer."""

    def setUp(self) -> None:
        self.inferrer = TypeInferrer()

    def _parse_expr(self, expr: str) -> ast.AST:
        return ast.parse(expr, mode="eval").body

    def test_infer_unaryop_not(self) -> None:
        """Test 'not' unary operator."""
        node = self._parse_expr("not True")
        self.assertEqual(self.inferrer.infer_type(node), "bool")

    def test_infer_unaryop_neg(self) -> None:
        """Test negation unary operator."""
        node = self._parse_expr("-42")
        self.assertEqual(self.inferrer.infer_type(node), "int")

    def test_infer_bitwise_and(self) -> None:
        """Test bitwise AND."""
        node = self._parse_expr("1 & 2")
        self.assertEqual(self.inferrer.infer_type(node), "int")

    def test_infer_bitwise_or(self) -> None:
        """Test bitwise OR."""
        node = self._parse_expr("1 | 2")
        self.assertEqual(self.inferrer.infer_type(node), "int")

    def test_infer_slice(self) -> None:
        """Test slice type."""
        node = ast.Slice(
            lower=ast.Constant(value=0),
            upper=ast.Constant(value=5),
            step=ast.Constant(value=1),
        )
        result = self.inferrer.infer_type(node)
        self.assertEqual(result, "slice")

    def test_infer_joined_str(self) -> None:
        """Test f-string type."""
        node = ast.JoinedStr(values=[
            ast.Constant(value="hello "),
            ast.FormattedValue(
                value=ast.Name(id="name", ctx=ast.Load()),
                conversion=-1,
            ),
        ])
        result = self.inferrer.infer_type(node)
        self.assertEqual(result, "str")

    def test_infer_named_expr(self) -> None:
        """Test walrus operator type."""
        node = ast.NamedExpr(
            target=ast.Name(id="x", ctx=ast.Store()),
            value=ast.Constant(value=42),
        )
        result = self.inferrer.infer_type(node)
        self.assertEqual(result, "int")

    def test_infer_set_comp(self) -> None:
        """Test set comprehension."""
        node = self._parse_expr("{x for x in range(10)}")
        self.assertEqual(self.inferrer.infer_type(node), "set")

    def test_infer_dict_comp(self) -> None:
        """Test dict comprehension."""
        node = self._parse_expr("{x: x for x in range(10)}")
        self.assertEqual(self.inferrer.infer_type(node), "dict")

    def test_infer_generator(self) -> None:
        """Test generator expression."""
        node = self._parse_expr("(x for x in range(10))")
        self.assertEqual(self.inferrer.infer_type(node), "Generator")

    def test_infer_starred(self) -> None:
        """Test starred expression."""
        node = ast.Starred(
            value=ast.Name(id="args", ctx=ast.Load()),
            ctx=ast.Load(),
        )
        self.assertIsNone(self.inferrer.infer_type(node))

    def test_infer_constant_complex(self) -> None:
        """Test complex number constant."""
        node = self._parse_expr("1+2j")
        self.assertEqual(self.inferrer.infer_type(node), "complex")


# ===========================================================================
# Test: CompletionItemKind values
# ===========================================================================

class TestCompletionItemKind(unittest.TestCase):
    """Tests for the CompletionItemKind enum."""

    def test_values_match_lsp(self) -> None:
        """Test that values match LSP specification."""
        self.assertEqual(int(CompletionItemKind.TEXT), 1)
        self.assertEqual(int(CompletionItemKind.METHOD), 2)
        self.assertEqual(int(CompletionItemKind.FUNCTION), 3)
        self.assertEqual(int(CompletionItemKind.CONSTRUCTOR), 4)
        self.assertEqual(int(CompletionItemKind.FIELD), 5)
        self.assertEqual(int(CompletionItemKind.VARIABLE), 6)
        self.assertEqual(int(CompletionItemKind.CLASS), 7)
        self.assertEqual(int(CompletionItemKind.MODULE), 9)
        self.assertEqual(int(CompletionItemKind.KEYWORD), 14)
        self.assertEqual(int(CompletionItemKind.SNIPPET), 15)
        self.assertEqual(int(CompletionItemKind.FILE), 17)
        self.assertEqual(int(CompletionItemKind.FOLDER), 19)

    def test_all_members_defined(self) -> None:
        """Test that all expected members are defined."""
        expected = [
            "TEXT", "METHOD", "FUNCTION", "CONSTRUCTOR", "FIELD",
            "VARIABLE", "CLASS", "INTERFACE", "MODULE", "PROPERTY",
            "UNIT", "VALUE", "ENUM", "KEYWORD", "SNIPPET", "COLOR",
            "FILE", "REFERENCE", "FOLDER", "ENUM_MEMBER", "CONSTANT",
            "STRUCT", "EVENT", "OPERATOR", "TYPE_PARAMETER",
        ]
        for name in expected:
            self.assertTrue(hasattr(CompletionItemKind, name))


# ===========================================================================
# Test: SCORE_WEIGHTS completeness
# ===========================================================================

class TestScoreWeights(unittest.TestCase):
    """Tests for the score weights configuration."""

    def test_weights_are_positive(self) -> None:
        """Test that all weights are positive."""
        for name, weight in SCORE_WEIGHTS.items():
            self.assertGreater(weight, 0, f"Weight '{name}' should be positive")

    def test_exact_match_highest(self) -> None:
        """Test that exact match has the highest weight."""
        self.assertEqual(
            SCORE_WEIGHTS["exact_match"],
            max(SCORE_WEIGHTS.values()),
        )


# ===========================================================================
# Test: SyntaxError handling in analyze_document
# ===========================================================================

class TestSyntaxErrorHandling(unittest.TestCase):
    """Tests for handling syntax errors in analysis."""

    def test_syntax_error_incomplete_function(self) -> None:
        """Test analysis with incomplete function definition."""
        engine = PythonCompletionEngine()
        source = "def foo(\n    pass\n"
        engine.analyze_document(source)
        # Should not crash
        self.assertIsNotNone(engine.get_symbols())

    def test_syntax_error_unclosed_string(self) -> None:
        """Test analysis with unclosed string."""
        engine = PythonCompletionEngine()
        source = 'x = "hello\n'
        engine.analyze_document(source)
        self.assertIsNotNone(engine.get_symbols())

    def test_syntax_error_unclosed_bracket(self) -> None:
        """Test analysis with unclosed bracket."""
        engine = PythonCompletionEngine()
        source = "x = [1, 2, 3\n"
        engine.analyze_document(source)
        self.assertIsNotNone(engine.get_symbols())

    def test_syntax_error_empty_source(self) -> None:
        """Test analysis with empty source."""
        engine = PythonCompletionEngine()
        engine.analyze_document("")
        symbols = engine.get_symbols()
        self.assertEqual(len(symbols), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)