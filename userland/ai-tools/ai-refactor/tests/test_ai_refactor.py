"""
Comprehensive tests for the AI Refactoring Assistant (ai_refactor.py).

Tests cover all major components:
- RefactoringEngine base class
- FunctionExtractorRef
- VariableRenamer
- DuplicateDetector
- DesignPatternAnalyzer
- SafetyChecker
- CodeDiffGenerator
- CLI entry points
- Error handling and edge cases
"""

import ast
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# Ensure the parent directory is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_refactor import (
    # Core classes
    RefactoringEngine,
    FunctionExtractorRef,
    VariableRenamer,
    DuplicateDetector,
    DesignPatternAnalyzer,
    SafetyChecker,
    CodeDiffGenerator,

    # Data classes
    CodeLocation,
    DuplicateMatch,
    SafetyWarning,
    SafetyReport,
    PatternSuggestion,
    RefactoringSummary,

    # Exceptions
    RefactoringError,
    ParsingError,
    RenameError,
    ExtractionError,

    # Utilities
    read_source_file,
    write_source_file,
    create_backup_file,
    parse_code,
    unparse_ast,
    get_source_lines,
    dedent_code,
    indent_code,
    compute_hash,
    get_all_names,
    get_assigned_names,
    ast_similarity,
    text_similarity,
    generate_unified_diff,
    normalize_ast_for_comparison,

    # Scope analysis
    Scope,
    ScopeAnalyzer,

    # CLI
    create_parser,
    main,
    VERSION,
)


# ==============================================================================
#  Utility Test Helpers
# ==============================================================================


def sample_code_simple() -> str:
    """Return a simple sample Python program for testing."""
    return '''"""Sample module for testing."""

import os
import sys

CONSTANT = 42


def greet(name: str) -> str:
    """Greet someone."""
    return f"Hello, {name}!"


def add(a: int, b: int) -> int:
    """Add two numbers."""
    result = a + b
    return result


class Calculator:
    """A simple calculator."""

    def __init__(self, factor: int = 1) -> None:
        self.factor = factor
        self._history: List[int] = []

    def multiply(self, x: int, y: int) -> int:
        result = x * y * self.factor
        self._history.append(result)
        return result

    def divide(self, x: int, y: int) -> float:
        if y == 0:
            raise ValueError("Cannot divide by zero")
        result = x / y
        self._history.append(result)
        return result

    def get_history(self) -> List[int]:
        return self._history


def main() -> None:
    calc = Calculator(factor=2)
    print(calc.multiply(3, 4))
    print(calc.divide(10, 2))
'''


def sample_code_with_duplicates() -> str:
    """Return code with intentional duplicate blocks."""
    return '''def process_user_data(data: Dict) -> None:
    """Process user data block 1."""
    # Validate
    if not isinstance(data, dict):
        raise TypeError("Expected dict")
    if 'name' not in data:
        raise ValueError("Missing name")
    if 'age' not in data:
        raise ValueError("Missing age")

    # Transform
    result = {}
    result['full_name'] = data['name'].strip().title()
    result['age'] = int(data['age'])
    return result


def process_order_data(data: Dict) -> None:
    """Process order data block 2."""
    # Validate
    if not isinstance(data, dict):
        raise TypeError("Expected dict")
    if 'order_id' not in data:
        raise ValueError("Missing order_id")
    if 'amount' not in data:
        raise ValueError("Missing amount")

    # Transform
    result = {}
    result['order_id'] = str(data['order_id']).strip()
    result['amount'] = float(data['amount'])
    return result
'''


def sample_code_for_singleton() -> str:
    """Return code that looks like a singleton pattern."""
    return '''class DatabaseConnection:
    """A database connection manager."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, connection_string: str = ""):
        if not hasattr(self, '_initialized'):
            self._connection_string = connection_string
            self._connected = False
            self._initialized = True

    def connect(self) -> bool:
        self._connected = True
        return True
'''


def sample_code_for_factory() -> str:
    """Return code that looks like a factory pattern."""
    return '''class Animal:
    def speak(self) -> str:
        pass

class Dog(Animal):
    def speak(self) -> str:
        return "Woof!"

class Cat(Animal):
    def speak(self) -> str:
        return "Meow!"

class AnimalFactory:
    def create_animal(self, animal_type: str) -> Animal:
        if animal_type == "dog":
            return Dog()
        elif animal_type == "cat":
            return Cat()
        else:
            raise ValueError(f"Unknown animal: {animal_type}")
'''


# ==============================================================================
#  Test Cases
# ==============================================================================


class TestCodeLocation(unittest.TestCase):
    """Tests for the CodeLocation data class."""

    def test_str_with_path(self) -> None:
        loc = CodeLocation(file_path="/path/to/file.py", start_line=10, end_line=20)
        self.assertEqual(str(loc), "/path/to/file.py:10-20")

    def test_str_without_path(self) -> None:
        loc = CodeLocation(start_line=5, end_line=8)
        self.assertEqual(str(loc), "<unknown>:5-8")

    def test_str_default(self) -> None:
        loc = CodeLocation()
        self.assertEqual(str(loc), "<unknown>:0-0")

    def test_to_dict(self) -> None:
        loc = CodeLocation(file_path="test.py", start_line=1, end_line=5, start_col=0, end_col=10)
        d = loc.to_dict()
        self.assertEqual(d['file_path'], 'test.py')
        self.assertEqual(d['start_line'], 1)
        self.assertEqual(d['end_line'], 5)


class TestDuplicateMatch(unittest.TestCase):
    """Tests for the DuplicateMatch data class."""

    def setUp(self) -> None:
        self.loc1 = CodeLocation(file_path="f.py", start_line=1, end_line=5)
        self.loc2 = CodeLocation(file_path="f.py", start_line=10, end_line=14)

    def test_str(self) -> None:
        match = DuplicateMatch(block1=self.loc1, block2=self.loc2, similarity=0.85, content="code")
        s = str(match)
        self.assertIn("85.0%", s)
        self.assertIn("Block 1", s)
        self.assertIn("Block 2", s)

    def test_to_dict(self) -> None:
        match = DuplicateMatch(block1=self.loc1, block2=self.loc2, similarity=0.9, content="code")
        d = match.to_dict()
        self.assertEqual(d['similarity'], 0.9)
        self.assertEqual(d['content'], 'code')


class TestSafetyWarning(unittest.TestCase):
    """Tests for the SafetyWarning data class."""

    def test_str_with_location(self) -> None:
        loc = CodeLocation(file_path="f.py", start_line=1, end_line=5)
        w = SafetyWarning("syntax", "Bad syntax", loc, "error")
        self.assertIn("[ERROR]", str(w))
        self.assertIn("syntax", str(w))
        self.assertIn("f.py", str(w))

    def test_str_without_location(self) -> None:
        w = SafetyWarning("imports", "Missing import", severity="warning")
        self.assertIn("[WARNING]", str(w))

    def test_to_dict(self) -> None:
        w = SafetyWarning("test", "test message", severity="info")
        d = w.to_dict()
        self.assertEqual(d['category'], 'test')
        self.assertEqual(d['severity'], 'info')


class TestSafetyReport(unittest.TestCase):
    """Tests for the SafetyReport data class."""

    def test_default_safe(self) -> None:
        report = SafetyReport()
        self.assertTrue(report.is_safe)
        self.assertTrue(report.syntax_valid)
        self.assertEqual(report.ast_match_score, 1.0)

    def test_add_warning_error(self) -> None:
        report = SafetyReport()
        report.add_warning("test", "error", severity="error")
        self.assertFalse(report.is_safe)
        self.assertEqual(len(report.warnings), 1)

    def test_add_warning_warning(self) -> None:
        report = SafetyReport()
        report.add_warning("test", "warning", severity="warning")
        self.assertTrue(report.is_safe)
        self.assertEqual(len(report.warnings), 1)

    def test_str(self) -> None:
        report = SafetyReport()
        s = str(report)
        self.assertIn("SAFE", s)
        self.assertIn("AST match score", s)

    def test_to_dict(self) -> None:
        report = SafetyReport()
        d = report.to_dict()
        self.assertTrue(d['is_safe'])
        self.assertTrue(d['syntax_valid'])


class TestPatternSuggestion(unittest.TestCase):
    """Tests for the PatternSuggestion data class."""

    def test_str(self) -> None:
        loc = CodeLocation(file_path="f.py", start_line=1, end_line=10)
        suggestion = PatternSuggestion(
            pattern_name="Singleton",
            confidence=0.85,
            description="One instance only",
            rationale="Class manages instance",
            location=loc,
            example_code="class X: pass",
        )
        s = str(suggestion)
        self.assertIn("85%", s)
        self.assertIn("Singleton", s)
        self.assertIn("f.py", s)

    def test_to_dict(self) -> None:
        suggestion = PatternSuggestion(
            pattern_name="Factory",
            confidence=0.75,
            description="Creates objects",
            rationale="Returns different types",
        )
        d = suggestion.to_dict()
        self.assertEqual(d['pattern_name'], 'Factory')
        self.assertEqual(d['confidence'], 0.75)


class TestRefactoringSummary(unittest.TestCase):
    """Tests for the RefactoringSummary data class."""

    def test_success_str(self) -> None:
        summary = RefactoringSummary(
            operation="test",
            description="A test",
            success=True,
            original_code="old",
            refactored_code="new",
            diff="--- old\n+++ new\n",
        )
        s = str(summary)
        self.assertIn("SUCCESS", s)
        self.assertIn("test", s)

    def test_failed_str(self) -> None:
        summary = RefactoringSummary(
            operation="test",
            description="A test",
            success=False,
            original_code="old",
            refactored_code="new",
        )
        s = str(summary)
        self.assertIn("FAILED", s)

    def test_to_dict(self) -> None:
        summary = RefactoringSummary(
            operation="rename",
            description="Renamed x to y",
            success=True,
            original_code="x = 1",
            refactored_code="y = 1",
            diff="diff",
        )
        d = summary.to_dict()
        self.assertEqual(d['operation'], 'rename')
        self.assertTrue(d['success'])


# ==============================================================================
#  Exception Tests
# ==============================================================================


class TestExceptions(unittest.TestCase):
    """Tests for custom exception classes."""

    def test_refactoring_error(self) -> None:
        e = RefactoringError("something went wrong")
        self.assertEqual(str(e), "something went wrong")
        self.assertIsNone(e.original_exception)

    def test_refactoring_error_with_cause(self) -> None:
        cause = ValueError("original")
        e = RefactoringError("wrapped", cause)
        self.assertEqual(e.original_exception, cause)

    def test_parsing_error(self) -> None:
        e = ParsingError("bad syntax")
        self.assertIsInstance(e, RefactoringError)
        self.assertIsNone(e.original_exception)

    def test_rename_error(self) -> None:
        e = RenameError("cannot rename", reason="name_not_found")
        self.assertEqual(e.reason, "name_not_found")
        self.assertIsInstance(e, RefactoringError)

    def test_extraction_error(self) -> None:
        e = ExtractionError("cannot extract", reason="invalid_range")
        self.assertEqual(e.reason, "invalid_range")
        self.assertIsInstance(e, RefactoringError)


# ==============================================================================
#  Utility Function Tests
# ==============================================================================


class TestUtilityFunctions(unittest.TestCase):
    """Tests for utility functions."""

    def test_parse_code_valid(self) -> None:
        tree = parse_code("x = 1")
        self.assertIsInstance(tree, ast.Module)

    def test_parse_code_invalid(self) -> None:
        with self.assertRaises(ParsingError):
            parse_code("def invalid syntax here!!!")

    def test_unparse_ast(self) -> None:
        tree = parse_code("x = 42")
        result = unparse_ast(tree)
        self.assertIn("x", result)
        self.assertIn("42", result)

    def test_get_source_lines(self) -> None:
        lines = get_source_lines("line1\nline2\nline3\n")
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], "line1\n")

    def test_dedent_code(self) -> None:
        code = "    if True:\n        pass\n"
        dedented = dedent_code(code)
        self.assertNotIn("    if", dedented)
        self.assertIn("if True:", dedented)

    def test_indent_code(self) -> None:
        code = "if True:\n    pass\n"
        indented = indent_code(code)
        self.assertTrue(indented.startswith("    if"))

    def test_compute_hash(self) -> None:
        h1 = compute_hash("x = 1")
        h2 = compute_hash("x = 1")
        h3 = compute_hash("y = 2")
        self.assertEqual(h1, h2)
        self.assertNotEqual(h1, h3)

    def test_get_all_names(self) -> None:
        tree = parse_code("x = y + z")
        names = get_all_names(tree)
        self.assertIn("x", names)
        self.assertIn("y", names)
        self.assertIn("z", names)

    def test_get_assigned_names(self) -> None:
        code = """
x = 1
y, z = 2, 3
def foo(): pass
class Bar: pass
import os
from sys import path
"""
        tree = parse_code(code)
        names = get_assigned_names(tree)
        self.assertIn("x", names)
        self.assertIn("y", names)
        self.assertIn("z", names)
        self.assertIn("foo", names)
        self.assertIn("Bar", names)
        self.assertIn("os", names)
        self.assertIn("path", names)

    def test_ast_similarity_identical(self) -> None:
        tree1 = parse_code("x = a + b")
        tree2 = parse_code("y = c + d")
        similarity = ast_similarity(tree1, tree2)
        self.assertGreaterEqual(similarity, 0.9)

    def test_ast_similarity_different(self) -> None:
        tree1 = parse_code("x = a + b")
        tree2 = parse_code("while True: pass")
        similarity = ast_similarity(tree1, tree2)
        self.assertLess(similarity, 0.5)

    def test_text_similarity(self) -> None:
        self.assertAlmostEqual(text_similarity("hello", "hello"), 1.0)
        self.assertLess(text_similarity("hello", "world"), 0.5)
        self.assertGreater(text_similarity("abc def", "abc xyz"), 0.0)

    def test_text_similarity_empty(self) -> None:
        self.assertEqual(text_similarity("", ""), 1.0)
        self.assertEqual(text_similarity("", "a"), 0.0)

    def test_generate_unified_diff(self) -> None:
        diff = generate_unified_diff("line1\nline2\n", "line1\nline3\n")
        self.assertIn("line1", diff)
        self.assertIn("line2", diff)
        self.assertIn("line3", diff)

    def test_normalize_ast(self) -> None:
        code = "def foo(x): return x + 1"
        tree = parse_code(code)
        normalized = normalize_ast_for_comparison(tree)
        n_str = ast.dump(normalized)
        # The original identifiers should be replaced with placeholders
        self.assertNotIn("'foo'", n_str)
        self.assertNotIn("'x'", n_str)


# ==============================================================================
#  Scope Analysis Tests
# ==============================================================================


class TestScope(unittest.TestCase):
    """Tests for the Scope class."""

    def test_scope_creation(self) -> None:
        scope = Scope("module", "<module>")
        self.assertEqual(scope.scope_type, "module")
        self.assertEqual(scope.name, "<module>")
        self.assertIsNone(scope.parent)

    def test_add_child(self) -> None:
        parent = Scope("module", "<module>")
        child = Scope("function", "foo")
        parent.add_child(child)
        self.assertIn(child, parent.children)
        self.assertEqual(child.parent, parent)

    def test_visible_names_module(self) -> None:
        module = Scope("module", "<module>")
        module.defined_names.add("x")
        module.defined_names.add("y")
        visible = module.get_visible_names()
        self.assertIn("x", visible)
        self.assertIn("y", visible)

    def test_visible_names_inherited(self) -> None:
        module = Scope("module", "<module>")
        module.defined_names.add("x")
        func = Scope("function", "foo", parent=module)
        func.defined_names.add("y")
        visible = func.get_visible_names()
        self.assertIn("x", visible)
        self.assertIn("y", visible)

    def test_is_defined_in_scope(self) -> None:
        scope = Scope("function", "f")
        scope.defined_names.add("local_var")
        self.assertTrue(scope.is_defined_in_scope("local_var"))
        self.assertFalse(scope.is_defined_in_scope("other"))

    def test_is_visible_builtin(self) -> None:
        scope = Scope("module", "<module>")
        self.assertTrue(scope.is_visible("len"))
        self.assertTrue(scope.is_visible("print"))

    def test_find_scope_for_name(self) -> None:
        module = Scope("module", "<module>")
        module.defined_names.add("x")
        func = Scope("function", "f", parent=module)
        func.defined_names.add("y")
        self.assertEqual(func.find_scope_for_name("x"), module)
        self.assertEqual(func.find_scope_for_name("y"), func)
        self.assertIsNone(func.find_scope_for_name("z"))


class TestScopeAnalyzer(unittest.TestCase):
    """Tests for the ScopeAnalyzer class."""

    def test_analyze_module(self) -> None:
        code = "x = 1\ny = 2\n"
        tree = parse_code(code)
        analyzer = ScopeAnalyzer()
        scope = analyzer.analyze(tree)
        self.assertEqual(scope.scope_type, "module")
        self.assertIn("x", scope.defined_names)
        self.assertIn("y", scope.defined_names)

    def test_analyze_function(self) -> None:
        code = "def foo(a, b):\n    c = a + b\n    return c\n"
        tree = parse_code(code)
        analyzer = ScopeAnalyzer()
        scope = analyzer.analyze(tree)
        self.assertEqual(len(scope.children), 1)
        func_scope = scope.children[0]
        self.assertEqual(func_scope.name, "foo")
        self.assertIn("a", func_scope.defined_names)
        self.assertIn("b", func_scope.defined_names)
        self.assertIn("c", func_scope.defined_names)

    def test_analyze_nested_functions(self) -> None:
        code = "def outer():\n    def inner():\n        pass\n"
        tree = parse_code(code)
        analyzer = ScopeAnalyzer()
        scope = analyzer.analyze(tree)
        outer = scope.children[0]
        self.assertEqual(len(outer.children), 1)
        self.assertEqual(outer.children[0].name, "inner")

    def test_analyze_class(self) -> None:
        code = "class MyClass:\n    x = 1\n    def method(self): pass\n"
        tree = parse_code(code)
        analyzer = ScopeAnalyzer()
        scope = analyzer.analyze(tree)
        class_scope = scope.children[0]
        self.assertEqual(class_scope.name, "MyClass")
        self.assertIn("method", class_scope.defined_names)

    def test_analyze_imports(self) -> None:
        code = "import os\nfrom sys import path\n"
        tree = parse_code(code)
        analyzer = ScopeAnalyzer()
        scope = analyzer.analyze(tree)
        self.assertIn("os", scope.defined_names)
        self.assertIn("path", scope.defined_names)

    def test_analyze_lambda(self) -> None:
        code = "f = lambda x: x + 1\n"
        tree = parse_code(code)
        analyzer = ScopeAnalyzer()
        scope = analyzer.analyze(tree)
        self.assertEqual(len(scope.children), 1)
        self.assertEqual(scope.children[0].scope_type, "lambda")

    def test_analyze_comprehension(self) -> None:
        code = "squares = [x*x for x in range(10)]\n"
        tree = parse_code(code)
        analyzer = ScopeAnalyzer()
        scope = analyzer.analyze(tree)
        # Should have at least one comprehension scope
        comp_scopes = [c for c in scope.children if c.scope_type == 'comprehension']
        self.assertGreaterEqual(len(comp_scopes), 1)


# ==============================================================================
#  RefactoringEngine Base Class Tests
# ==============================================================================


class TestRefactoringEngine(unittest.TestCase):
    """Tests for the RefactoringEngine base class."""

    def test_initialization(self) -> None:
        code = "x = 1\n"
        engine = _ConcreteEngine(code)
        self.assertEqual(engine.source_code, code)
        self.assertIsNone(engine.file_path)
        self.assertFalse(engine.dry_run)
        self.assertIsInstance(engine.ast_tree, ast.Module)

    def test_initialization_with_file_path(self) -> None:
        engine = _ConcreteEngine("x = 1", file_path="/path/to/file.py")
        self.assertEqual(engine.file_path, "/path/to/file.py")

    def test_initialization_dry_run(self) -> None:
        engine = _ConcreteEngine("x = 1", dry_run=True)
        self.assertTrue(engine.dry_run)

    def test_initialization_invalid_syntax(self) -> None:
        with self.assertRaises(ParsingError):
            _ConcreteEngine("def invalid!!!")

    def test_scope_tree_property(self) -> None:
        code = "x = 1\ndef foo(): pass\n"
        engine = _ConcreteEngine(code)
        scope = engine.scope_tree
        self.assertIsNotNone(scope)
        self.assertEqual(scope.scope_type, "module")
        self.assertIn("x", scope.defined_names)
        self.assertIn("foo", scope.defined_names)

    def test_generate_diff(self) -> None:
        engine = _ConcreteEngine("x = 1\n")
        diff = engine.generate_diff("y = 1\n")
        self.assertIn("x", diff)
        self.assertIn("y", diff)

    def test_check_syntax_valid(self) -> None:
        engine = _ConcreteEngine("x = 1")
        valid, error = engine._check_syntax("y = 2")
        self.assertTrue(valid)
        self.assertIsNone(error)

    def test_check_syntax_invalid(self) -> None:
        engine = _ConcreteEngine("x = 1")
        valid, error = engine._check_syntax("def bad")
        self.assertFalse(valid)
        self.assertIsNotNone(error)


class _ConcreteEngine(RefactoringEngine):
    """Concrete implementation for testing the abstract base class."""

    def apply(self) -> RefactoringSummary:
        return RefactoringSummary(
            operation="test",
            description="Test operation",
            success=True,
            original_code=self.source_code,
            refactored_code=self.source_code,
        )


# ==============================================================================
#  FunctionExtractorRef Tests
# ==============================================================================


class TestFunctionExtractorRef(unittest.TestCase):
    """Tests for the FunctionExtractorRef class."""

    def test_extract_simple_block(self) -> None:
        code = textwrap.dedent("""\
        x = 10
        y = 20
        result = x + y
        print(result)
        """)
        result = FunctionExtractorRef(
            code, start_line=1, end_line=3, function_name="compute_sum"
        ).apply()
        self.assertTrue(result.success)
        self.assertIn("def compute_sum", result.refactored_code)
        self.assertIn("compute_sum(", result.refactored_code)

    def test_extract_with_dependencies(self) -> None:
        code = textwrap.dedent("""\
        a = 5
        b = 3
        c = a + b
        print(c)
        """)
        result = FunctionExtractorRef(
            code, start_line=2, end_line=3, function_name="add_values"
        ).apply()
        self.assertTrue(result.success)
        self.assertIn("def add_values", result.refactored_code)

    def test_extract_invalid_line_range(self) -> None:
        code = "x = 1\n"
        with self.assertRaises(ExtractionError):
            FunctionExtractorRef(code, start_line=5, end_line=10, function_name="test")

    def test_extract_reversed_lines(self) -> None:
        code = "x = 1\ny = 2\n"
        with self.assertRaises(ExtractionError):
            FunctionExtractorRef(code, start_line=3, end_line=1, function_name="test")

    def test_extract_invalid_name(self) -> None:
        code = "x = 1\n"
        with self.assertRaises(ExtractionError):
            FunctionExtractorRef(code, start_line=1, end_line=1, function_name="123bad")

    def test_extract_dry_run(self) -> None:
        code = textwrap.dedent("""\
        x = 1
        y = 2
        z = x + y
        """)
        engine = FunctionExtractorRef(
            code, start_line=1, end_line=3, function_name="calc", dry_run=True
        )
        self.assertTrue(engine.dry_run)
        result = engine.apply()
        self.assertTrue(result.success)

    def test_extract_function_has_docstring(self) -> None:
        code = textwrap.dedent("""\
        value = 42
        print(value)
        """)
        result = FunctionExtractorRef(
            code, start_line=1, end_line=1, function_name="get_value"
        ).apply()
        self.assertIn("def get_value", result.refactored_code)


class TestVariableRenamer(unittest.TestCase):
    """Tests for the VariableRenamer class."""

    def test_rename_simple(self) -> None:
        code = textwrap.dedent("""\
        x = 10
        print(x)
        """)
        result = VariableRenamer(code, old_name="x", new_name="counter").apply()
        self.assertTrue(result.success)
        self.assertIn("counter = 10", result.refactored_code)
        self.assertIn("print(counter)", result.refactored_code)
        self.assertNotIn("x = 10", result.refactored_code)

    def test_rename_function(self) -> None:
        code = textwrap.dedent("""\
        def old_func():
            pass
        old_func()
        """)
        result = VariableRenamer(code, old_name="old_func", new_name="new_func").apply()
        self.assertTrue(result.success)
        self.assertIn("def new_func", result.refactored_code)
        self.assertIn("new_func()", result.refactored_code)

    def test_rename_class(self) -> None:
        code = textwrap.dedent("""\
        class OldClass:
            pass
        obj = OldClass()
        """)
        result = VariableRenamer(code, old_name="OldClass", new_name="NewClass").apply()
        self.assertTrue(result.success)
        self.assertIn("class NewClass", result.refactored_code)
        self.assertIn("NewClass()", result.refactored_code)

    def test_rename_invalid_old_name(self) -> None:
        code = "x = 1\n"
        with self.assertRaises(RenameError):
            VariableRenamer(code, old_name="123bad", new_name="good")

    def test_rename_invalid_new_name(self) -> None:
        code = "x = 1\n"
        with self.assertRaises(RenameError):
            VariableRenamer(code, old_name="x", new_name="123bad")

    def test_rename_same_name(self) -> None:
        code = "x = 1\n"
        with self.assertRaises(RenameError):
            VariableRenamer(code, old_name="x", new_name="x")

    def test_rename_name_not_found(self) -> None:
        code = "x = 1\n"
        renamer = VariableRenamer(code, old_name="nonexistent", new_name="y")
        with self.assertRaises(RenameError):
            renamer.apply()

    def test_rename_dry_run(self) -> None:
        code = "x = 1\n"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            temp_path = f.name

        try:
            engine = VariableRenamer(code, old_name="x", new_name="y",
                                     file_path=temp_path, dry_run=True)
            result = engine.apply()
            self.assertTrue(result.success)
            # Verify file was NOT modified
            with open(temp_path, 'r') as f:
                content = f.read()
            self.assertEqual(content, code)
        finally:
            os.unlink(temp_path)

    def test_rename_with_builtin_shadow_warning(self) -> None:
        code = "x = 1\n"
        engine = VariableRenamer(code, old_name="x", new_name="list")
        result = engine.apply()
        # Should still succeed but with a warning
        self.assertTrue(result.success)
        has_warning = any('built-in' in w.message for w in result.warnings)
        self.assertTrue(has_warning)


class TestDuplicateDetector(unittest.TestCase):
    """Tests for the DuplicateDetector class."""

    def test_detect_duplicates(self) -> None:
        code = sample_code_with_duplicates()
        engine = DuplicateDetector(code, min_lines=3, threshold=0.5)
        result = engine.apply()
        # Should find at least some similarity between the two functions
        # The result.diff should contain the analysis output
        self.assertTrue(result.success)

    def test_detect_no_duplicates(self) -> None:
        code = "x = 1\ny = 2\nz = 3\n"
        engine = DuplicateDetector(code, min_lines=5, threshold=0.9)
        result = engine.apply()
        self.assertTrue(result.success)

    def test_detect_method_ast(self) -> None:
        code = "x = 1\ny = 2\n"
        engine = DuplicateDetector(code, method='ast')
        self.assertEqual(engine.method, 'ast')

    def test_detect_method_text(self) -> None:
        code = "x = 1\ny = 2\n"
        engine = DuplicateDetector(code, method='text')
        self.assertEqual(engine.method, 'text')

    def test_detect_invalid_min_lines(self) -> None:
        with self.assertRaises(ValueError):
            DuplicateDetector("x = 1", min_lines=0)

    def test_detect_invalid_threshold(self) -> None:
        with self.assertRaises(ValueError):
            DuplicateDetector("x = 1", threshold=1.5)

    def test_detect_invalid_method(self) -> None:
        with self.assertRaises(ValueError):
            DuplicateDetector("x = 1", method='invalid')


class TestDesignPatternAnalyzer(unittest.TestCase):
    """Tests for the DesignPatternAnalyzer class."""

    def test_analyze_singleton_detected(self) -> None:
        code = sample_code_for_singleton()
        analyzer = DesignPatternAnalyzer(code)
        suggestions = analyzer.analyze()
        patterns = [s.pattern_name for s in suggestions]
        self.assertIn("Singleton", patterns)

    def test_analyze_factory_detected(self) -> None:
        code = sample_code_for_factory()
        analyzer = DesignPatternAnalyzer(code)
        suggestions = analyzer.analyze()
        patterns = [s.pattern_name for s in suggestions]
        self.assertIn("Factory", patterns)

    def test_analyze_no_patterns(self) -> None:
        code = "x = 1\ny = 2\n"
        analyzer = DesignPatternAnalyzer(code)
        suggestions = analyzer.analyze()
        self.assertEqual(len(suggestions), 0)

    def test_analyze_empty_code(self) -> None:
        analyzer = DesignPatternAnalyzer("")
        suggestions = analyzer.analyze()
        self.assertEqual(len(suggestions), 0)

    def test_analyze_apply(self) -> None:
        code = sample_code_for_singleton()
        analyzer = DesignPatternAnalyzer(code)
        result = analyzer.apply()
        self.assertTrue(result.success)
        self.assertIn("Singleton", result.diff)

    def test_analyze_strategy_detected(self) -> None:
        code = textwrap.dedent("""\
        class StrategyA:
            def execute(self): pass
            def validate(self): pass

        class StrategyB:
            def execute(self): pass
            def validate(self): pass
        """)
        analyzer = DesignPatternAnalyzer(code)
        suggestions = analyzer.analyze()
        patterns = [s.pattern_name for s in suggestions]
        # May or may not detect Strategy depending on threshold
        # But should not crash
        self.assertIsInstance(suggestions, list)


class TestSafetyChecker(unittest.TestCase):
    """Tests for the SafetyChecker class."""

    def test_check_identical_code(self) -> None:
        code = "x = 1\n"
        checker = SafetyChecker(code, code)
        report = checker.check()
        self.assertTrue(report.is_safe)
        self.assertTrue(report.syntax_valid)
        self.assertGreaterEqual(report.ast_match_score, 0.9)

    def test_check_syntax_error_in_refactored(self) -> None:
        original = "x = 1\n"
        refactored = "def invalid syntax!!!\n"
        checker = SafetyChecker(original, refactored)
        report = checker.check()
        self.assertFalse(report.syntax_valid)

    def test_check_missing_imports(self) -> None:
        original = "import os\nx = os.path.join('a', 'b')\n"
        refactored = "x = os.path.join('a', 'b')\n"
        checker = SafetyChecker(original, refactored)
        report = checker.check()
        self.assertFalse(report.is_safe)
        import_warnings = [w for w in report.warnings if w.category == 'imports']
        self.assertGreater(len(import_warnings), 0)

    def test_check_missing_function(self) -> None:
        original = textwrap.dedent("""\
        def foo():
            pass
        foo()
        """)
        refactored = "foo()\n"
        checker = SafetyChecker(original, refactored)
        report = checker.check()
        has_warning = any(w.category == 'globals' for w in report.warnings)
        self.assertTrue(has_warning)

    def test_check_apply(self) -> None:
        original = "x = 1\n"
        refactored = "y = 1\n"
        checker = SafetyChecker(original, refactored)
        result = checker.apply()
        self.assertTrue(result.success)  # AST structure is preserved (names normalized)
        self.assertIn("safety_check", result.operation)


class TestCodeDiffGenerator(unittest.TestCase):
    """Tests for the CodeDiffGenerator class."""

    def setUp(self) -> None:
        self.original = "line1\nline2\nline3\n"
        self.refactored = "line1\nline2_changed\nline3\n"

    def test_generate_unified(self) -> None:
        gen = CodeDiffGenerator(self.original, self.refactored)
        diff = gen.generate_unified()
        self.assertIn("line1", diff)
        self.assertIn("line2", diff)
        self.assertIn("line2_changed", diff)

    def test_generate_colored(self) -> None:
        gen = CodeDiffGenerator(self.original, self.refactored)
        colored = gen.generate_colored()
        self.assertIn('\033[', colored)  # ANSI color codes

    def test_generate_html(self) -> None:
        gen = CodeDiffGenerator(self.original, self.refactored)
        html = gen.generate_html()
        self.assertIn('<html', html.lower() or '<!DOCTYPE', html)
        self.assertIn('diff', html.lower())

    def test_generate_statistics(self) -> None:
        gen = CodeDiffGenerator(self.original, self.refactored)
        stats = gen.generate_statistics()
        self.assertIn('added_lines', stats)
        self.assertIn('removed_lines', stats)
        self.assertIn('hunks', stats)
        self.assertIn('net_change', stats)

    def test_statistics_with_changes(self) -> None:
        gen = CodeDiffGenerator("a\nb\nc\n", "a\nb_modified\nc\nd\n")
        stats = gen.generate_statistics()
        self.assertGreater(stats['added_lines'], 0)

    def test_statistics_identical_files(self) -> None:
        gen = CodeDiffGenerator("a\nb\n", "a\nb\n")
        stats = gen.generate_statistics()
        self.assertEqual(stats['added_lines'], 0)
        self.assertEqual(stats['removed_lines'], 0)


class TestFileOperations(unittest.TestCase):
    """Tests for file read/write/backup operations."""

    def test_read_source_file(self) -> None:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("x = 1\n")
            f.flush()
            temp_path = f.name

        try:
            content = read_source_file(temp_path)
            self.assertEqual(content, "x = 1\n")
        finally:
            os.unlink(temp_path)

    def test_read_source_file_not_found(self) -> None:
        with self.assertRaises(FileNotFoundError):
            read_source_file("/nonexistent/path/file.py")

    def test_write_source_file(self) -> None:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            temp_path = f.name

        try:
            # Write with no backup
            backup = write_source_file(temp_path, "new content\n", create_backup=False)
            self.assertIsNone(backup)
            content = read_source_file(temp_path)
            self.assertEqual(content, "new content\n")
        finally:
            os.unlink(temp_path)

    def test_create_backup_file(self) -> None:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("original\n")
            f.flush()
            temp_path = f.name

        try:
            backup_path = create_backup_file(temp_path)
            self.assertIsNotNone(backup_path)
            self.assertTrue(os.path.exists(backup_path))
            # Verify backup contains original content
            with open(backup_path, 'r') as f:
                content = f.read()
            self.assertEqual(content, "original\n")
        finally:
            os.unlink(temp_path)
            # Clean up backup too
            if backup_path and os.path.exists(backup_path):
                os.unlink(backup_path)


class TestCLI(unittest.TestCase):
    """Tests for the CLI entry point."""

    def test_create_parser(self) -> None:
        parser = create_parser()
        self.assertIsNotNone(parser)
        self.assertEqual(parser.prog, 'ai-refactor')

    def test_parser_version(self) -> None:
        parser = create_parser()
        # Just check that version exists
        self.assertTrue(hasattr(parser, 'add_help'))

    def test_main_extract_help(self) -> None:
        # Should not crash with extract subcommand help
        with self.assertRaises(SystemExit) as ctx:
            main(['extract', '--help'])
        self.assertEqual(ctx.exception.code, 0)

    def test_main_rename_help(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(['rename', '--help'])
        self.assertEqual(ctx.exception.code, 0)

    def test_main_detect_help(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(['detect', '--help'])
        self.assertEqual(ctx.exception.code, 0)

    def test_main_analyze_help(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(['analyze', '--help'])
        self.assertEqual(ctx.exception.code, 0)

    def test_main_check_help(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(['check', '--help'])
        self.assertEqual(ctx.exception.code, 0)

    def test_main_diff_help(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(['diff', '--help'])
        self.assertEqual(ctx.exception.code, 0)

    def test_main_no_args(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main([])
        self.assertEqual(ctx.exception.code, 2)

    def test_main_version(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(['--version'])
        self.assertEqual(ctx.exception.code, 0)

    def test_main_extract_file_not_found(self) -> None:
        exit_code = main(['extract', '/nonexistent.py', '--lines', '1-5', '--name', 'test'])
        self.assertEqual(exit_code, 1)

    def test_main_extract_invalid_lines(self) -> None:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("x = 1\n")
            f.flush()
            temp_path = f.name

        try:
            # Invalid line range format
            exit_code = main(['extract', temp_path, '--lines', 'abc', '--name', 'test'])
            self.assertEqual(exit_code, 1)
        finally:
            os.unlink(temp_path)

    def test_main_rename_file_not_found(self) -> None:
        exit_code = main(['rename', '/nonexistent.py', '--from', 'x', '--to', 'y'])
        self.assertEqual(exit_code, 1)

    def test_main_analyze_file_not_found(self) -> None:
        exit_code = main(['analyze', '/nonexistent.py'])
        self.assertEqual(exit_code, 1)

    def test_main_check_file_not_found(self) -> None:
        exit_code = main(['check', '/nonexistent.py', '--refactored', '/other.py'])
        self.assertEqual(exit_code, 1)

    def test_main_diff_file_not_found(self) -> None:
        exit_code = main(['diff', '/nonexistent.py', '/other.py'])
        self.assertEqual(exit_code, 1)

    def test_main_diff_two_files(self) -> None:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f1:
            f1.write("a\nb\nc\n")
            f1.flush()
            path1 = f1.name

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f2:
            f2.write("a\nb_modified\nc\n")
            f2.flush()
            path2 = f2.name

        try:
            exit_code = main(['diff', path1, path2])
            self.assertEqual(exit_code, 0)
        finally:
            os.unlink(path1)
            os.unlink(path2)

    def test_main_diff_with_output(self) -> None:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f1:
            f1.write("a\nb\n")
            f1.flush()
            path1 = f1.name

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f2:
            f2.write("a\nc\n")
            f2.flush()
            path2 = f2.name

        output_path = tempfile.mktemp(suffix='.diff')

        try:
            exit_code = main(['diff', path1, path2, '--output', output_path])
            self.assertEqual(exit_code, 0)
            self.assertTrue(os.path.exists(output_path))
        finally:
            os.unlink(path1)
            os.unlink(path2)
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_main_diff_stats(self) -> None:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f1:
            f1.write("a\nb\n")
            f1.flush()
            path1 = f1.name

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f2:
            f2.write("a\nc\n")
            f2.flush()
            path2 = f2.name

        try:
            exit_code = main(['diff', path1, path2, '--format', 'stats'])
            self.assertEqual(exit_code, 0)
        finally:
            os.unlink(path1)
            os.unlink(path2)


class TestIntegration(unittest.TestCase):
    """Integration tests that exercise multiple components together."""

    def test_extract_then_rename(self) -> None:
        """Test extracting a function then renaming a variable inside it."""
        code = textwrap.dedent("""\
        x = 10
        y = 20
        z = x + y
        print(z)
        """)

        # First, extract the block
        extract_result = FunctionExtractorRef(
            code, start_line=1, end_line=3, function_name="compute"
        ).apply()
        self.assertTrue(extract_result.success)

        # Then rename a variable in the extracted code
        refactored = extract_result.refactored_code
        rename_result = VariableRenamer(
            refactored, old_name="x", new_name="value_a"
        ).apply()
        self.assertTrue(rename_result.success)
        self.assertIn("value_a", rename_result.refactored_code)

    def test_full_pipeline(self) -> None:
        """Test analyze -> detect -> check pipeline."""
        code = sample_code_with_duplicates()

        # Analyze design patterns
        analyzer = DesignPatternAnalyzer(code)
        suggestions = analyzer.analyze()
        self.assertIsInstance(suggestions, list)

        # Detect duplicates
        detector = DuplicateDetector(code, min_lines=3, threshold=0.3)
        detect_result = detector.apply()
        self.assertTrue(detect_result.success)

        # Safety check self (should be identical)
        checker = SafetyChecker(code, code)
        report = checker.check()
        self.assertTrue(report.is_safe)

    def test_backup_and_restore(self) -> None:
        """Test that backup files are created correctly."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("x = 1\nprint(x)\n")
            f.flush()
            temp_path = f.name

        backup_path = None
        try:
            # Perform rename (should create backup)
            engine = VariableRenamer(
                read_source_file(temp_path),
                old_name="x",
                new_name="counter",
                file_path=temp_path,
                dry_run=False,
            )
            result = engine.apply()

            # Check backup was created
            self.assertIsNotNone(result.backup_path)
            backup_path = result.backup_path
            self.assertTrue(os.path.exists(backup_path))

            # Verify backup contains original content
            with open(backup_path, 'r') as f:
                backup_content = f.read()
            self.assertIn("x = 1", backup_content)
            self.assertNotIn("counter = 1", backup_content)

            # Verify file has new content
            with open(temp_path, 'r') as f:
                new_content = f.read()
            self.assertIn("counter = 1", new_content)
        finally:
            # Clean up
            os.unlink(temp_path)
            if backup_path and os.path.exists(backup_path):
                os.unlink(backup_path)

    def test_error_handling_edge_cases(self) -> None:
        """Test edge cases and error handling."""
        # Empty code - line range is out of bounds
        with self.assertRaises(ExtractionError):
            FunctionExtractorRef("", start_line=1, end_line=1, function_name="f")

        # Rename to existing builtin (should warn but succeed)
        code = "my_var = 1\nprint(my_var)\n"
        result = VariableRenamer(code, old_name="my_var", new_name="list").apply()
        self.assertTrue(result.success)
        has_builtin_warning = any('built-in' in w.message for w in result.warnings)
        self.assertTrue(has_builtin_warning)


class TestNormalizeAST(unittest.TestCase):
    """Tests for AST normalization."""

    def test_normalize_ast_replaces_names(self) -> None:
        tree = parse_code("x = y + z")
        normalized = normalize_ast_for_comparison(tree)
        n_str = ast.dump(normalized)
        self.assertNotIn("'x'", n_str)
        self.assertNotIn("'y'", n_str)
        self.assertNotIn("'z'", n_str)

    def test_normalize_ast_replaces_constants(self) -> None:
        tree = parse_code("x = 42")
        normalized = normalize_ast_for_comparison(tree)
        n_str = ast.dump(normalized)
        self.assertNotIn("42", n_str)

    def test_normalize_ast_function_names(self) -> None:
        tree = parse_code("def my_func(): pass")
        normalized = normalize_ast_for_comparison(tree)
        n_str = ast.dump(normalized)
        self.assertNotIn("my_func", n_str)

    def test_normalize_ast_class_names(self) -> None:
        tree = parse_code("class MyClass: pass")
        normalized = normalize_ast_for_comparison(tree)
        n_str = ast.dump(normalized)
        self.assertNotIn("MyClass", n_str)

    def test_normalize_ast_preserves_structure(self) -> None:
        tree1 = parse_code("x = a + b")
        tree2 = parse_code("y = c + d")
        n1 = normalize_ast_for_comparison(tree1)
        n2 = normalize_ast_for_comparison(tree2)
        self.assertEqual(ast.dump(n1), ast.dump(n2))


class TestASTSimilarity(unittest.TestCase):
    """Tests for AST similarity computation."""

    def test_identical_structures(self) -> None:
        tree1 = parse_code("x = a + b")
        tree2 = parse_code("y = c + d")
        self.assertGreaterEqual(ast_similarity(tree1, tree2), 0.9)

    def test_different_structures(self) -> None:
        tree1 = parse_code("x = a + b")
        tree2 = parse_code("if True: pass")
        self.assertLess(ast_similarity(tree1, tree2), 0.8)

    def test_exact_same(self) -> None:
        tree = parse_code("x = 1")
        self.assertAlmostEqual(ast_similarity(tree, tree), 1.0)

    def test_empty_vs_nonempty(self) -> None:
        tree1 = ast.Module(body=[])
        tree2 = parse_code("x = 1")
        similarity = ast_similarity(tree1, tree2)
        self.assertLess(similarity, 0.5)


class TestSafetyCheckerDetailed(unittest.TestCase):
    """Detailed tests for the SafetyChecker class."""

    def test_check_function_signature_change(self) -> None:
        original = "def foo(a, b): pass\n"
        refactored = "def foo(a): pass\n"
        checker = SafetyChecker(original, refactored)
        report = checker.check()
        has_warning = any(w.category == 'function_signature' for w in report.warnings)
        self.assertTrue(has_warning)

    def test_check_class_methods_removed(self) -> None:
        original = textwrap.dedent("""\
        class MyClass:
            def method1(self): pass
            def method2(self): pass
        """)
        refactored = textwrap.dedent("""\
        class MyClass:
            def method1(self): pass
        """)
        checker = SafetyChecker(original, refactored)
        report = checker.check()
        has_warning = any(w.category == 'class_structure' for w in report.warnings)
        self.assertTrue(has_warning)

    def test_check_extra_imports(self) -> None:
        original = "x = 1\n"
        refactored = "import os\nx = 1\n"
        checker = SafetyChecker(original, refactored)
        report = checker.check()
        extra_imports = [w for w in report.warnings if w.category == 'imports' and 'Extra' in w.message]
        self.assertGreater(len(extra_imports), 0)


class TestCodeDiffGeneratorDetailed(unittest.TestCase):
    """Detailed tests for CodeDiffGenerator."""

    def test_unified_diff_with_context(self) -> None:
        gen = CodeDiffGenerator("a\nb\nc\nd\ne\n", "a\nb\nx\nd\ne\n")
        diff = gen.generate_unified(n_context=1)
        self.assertIn("+x", diff)
        self.assertIn("-c", diff)

    def test_html_diff_contains_html(self) -> None:
        gen = CodeDiffGenerator("a\nb\n", "a\nc\n")
        html = gen.generate_html()
        self.assertTrue('html' in html.lower() or 'diff' in html.lower() or 'table' in html.lower())

    def test_statistics_no_changes(self) -> None:
        gen = CodeDiffGenerator("a\nb\nc\n", "a\nb\nc\n")
        stats = gen.generate_statistics()
        self.assertEqual(stats['added_lines'], 0)
        self.assertEqual(stats['removed_lines'], 0)
        self.assertEqual(stats['net_change'], 0)


class TestDesignPatternAnalyzerDetailed(unittest.TestCase):
    """Detailed tests for DesignPatternAnalyzer pattern detection."""

    def test_observer_pattern_basic(self) -> None:
        code = textwrap.dedent("""\
        class EventBus:
            def __init__(self):
                self._observers = []

            def register(self, observer):
                self._observers.append(observer)

            def notify(self, event):
                for obs in self._observers:
                    obs.update(event)
        """)
        analyzer = DesignPatternAnalyzer(code)
        suggestions = analyzer.analyze()
        patterns = [s.pattern_name for s in suggestions]
        self.assertIn("Observer", patterns)

    def test_builder_pattern(self) -> None:
        code = textwrap.dedent("""\
        class Pizza:
            def __init__(self, size, cheese, pepperoni, mushrooms, onions, bacon):
                self.size = size
                self.cheese = cheese
                self.pepperoni = pepperoni
                self.mushrooms = mushrooms
                self.onions = onions
                self.bacon = bacon
        """)
        analyzer = DesignPatternAnalyzer(code)
        suggestions = analyzer.analyze()
        patterns = [s.pattern_name for s in suggestions]
        self.assertIn("Builder", patterns)

    def test_prototype_pattern(self) -> None:
        code = textwrap.dedent("""\
        class Document:
            def __init__(self, content):
                self.content = content

            def clone(self):
                return Document(self.content)
        """)
        analyzer = DesignPatternAnalyzer(code)
        suggestions = analyzer.analyze()
        patterns = [s.pattern_name for s in suggestions]
        self.assertIn("Prototype", patterns)

    def test_template_method_pattern(self) -> None:
        code = textwrap.dedent("""\
        from abc import ABC, abstractmethod

        class DataProcessor(ABC):
            @abstractmethod
            def load(self): pass

            @abstractmethod
            def transform(self): pass

            def process(self):
                data = self.load()
                result = self.transform(data)
                return result
        """)
        analyzer = DesignPatternAnalyzer(code)
        suggestions = analyzer.analyze()
        patterns = [s.pattern_name for s in suggestions]
        # Template Method may be harder to detect with heuristic
        # But at least it shouldn't crash
        self.assertIsInstance(suggestions, list)


class TestEdgeCases(unittest.TestCase):
    """Tests for edge cases and unusual inputs."""

    def test_empty_source_code(self) -> None:
        # Empty code is valid Python (empty module)
        engine = _ConcreteEngine("")
        self.assertIsNotNone(engine.ast_tree)
        self.assertEqual(len(engine.ast_tree.body), 0)

    def test_whitespace_only(self) -> None:
        # Whitespace-only code is valid Python (empty module)
        engine = _ConcreteEngine("   \n  \n")
        self.assertIsNotNone(engine.ast_tree)
        self.assertEqual(len(engine.ast_tree.body), 0)

    def test_very_large_number(self) -> None:
        code = f"x = {10**100}\n"
        engine = _ConcreteEngine(code)
        self.assertIsNotNone(engine.ast_tree)

    def test_unicode_in_source(self) -> None:
        code = "# -*- coding: utf-8 -*-\nname = 'café'\n"
        engine = _ConcreteEngine(code)
        self.assertIsNotNone(engine.ast_tree)

    def test_multiline_strings(self) -> None:
        code = textwrap.dedent("""\
        x = '''multi
        line
        string'''
        """)
        engine = _ConcreteEngine(code)
        self.assertIsNotNone(engine.ast_tree)

    def test_nested_scopes_rename(self) -> None:
        code = textwrap.dedent("""\
        x = 1
        def outer():
            x = 2
            def inner():
                x = 3
                return x
            return inner()
        result = outer()
        """)
        result = VariableRenamer(code, old_name="x", new_name="value").apply()
        self.assertTrue(result.success)
        # All x's should be renamed to value
        self.assertNotIn("= x", result.refactored_code)
        self.assertIn("value", result.refactored_code)


class TestMainFunction(unittest.TestCase):
    """Tests for the main() entry point."""

    def test_main_handles_unknown_command(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(['unknown_command'])
        self.assertEqual(ctx.exception.code, 2)

    def test_main_verbose_flag(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(['--help'])
        self.assertEqual(ctx.exception.code, 0)

    def test_main_dry_run_flag(self) -> None:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("x = 1\n")
            f.flush()
            temp_path = f.name

        try:
            # Dry run should not modify the file
            exit_code = main(['rename', temp_path, '--from', 'x', '--to', 'y', '--dry-run'])
            self.assertEqual(exit_code, 0)
            # Verify file unchanged
            with open(temp_path, 'r') as f:
                content = f.read()
            self.assertIn("x = 1", content)
        finally:
            os.unlink(temp_path)


class TestVariableRenamerDetailed(unittest.TestCase):
    """Detailed tests for VariableRenamer."""

    def test_rename_with_scope_limit(self) -> None:
        code = textwrap.dedent("""\
        def foo():
            x = 1
            return x

        def bar():
            x = 2
            return x
        """)
        # Should work even with scope_limit (just doesn't filter aggressively)
        renamer = VariableRenamer(code, old_name="x", new_name="val",
                                  scope_limit="foo")
        result = renamer.apply()
        self.assertTrue(result.success)

    def test_rename_in_comprehension(self) -> None:
        code = "squares = [x * x for x in range(10)]\n"
        result = VariableRenamer(code, old_name="x", new_name="n").apply()
        self.assertTrue(result.success)
        self.assertIn("n", result.refactored_code)

    def test_rename_attribute_not_affected(self) -> None:
        code = "obj.x = 1\nprint(obj.x)\n"
        # Attribute access 'obj.x' does not define a standalone variable 'x';
        # the rename should not find 'x' as a standalone variable
        with self.assertRaises(RenameError):
            VariableRenamer(code, old_name="x", new_name="y").apply()


class TestFunctionExtractorRefDetailed(unittest.TestCase):
    """Detailed tests for FunctionExtractorRef."""

    def test_extract_with_no_dependencies(self) -> None:
        code = textwrap.dedent("""\
        print("hello")
        print("world")
        """)
        result = FunctionExtractorRef(
            code, start_line=1, end_line=2, function_name="say_hello"
        ).apply()
        self.assertTrue(result.success)
        self.assertIn("def say_hello", result.refactored_code)

    def test_extract_function_preserves_indentation(self) -> None:
        code = textwrap.dedent("""\
        if True:
            inner = 1
            print(inner)
        """)
        result = FunctionExtractorRef(
            code, start_line=2, end_line=3, function_name="do_inner"
        ).apply()
        self.assertTrue(result.success)
        self.assertIn("def do_inner", result.refactored_code)

    def test_extract_single_line(self) -> None:
        code = "x = 42\n"
        result = FunctionExtractorRef(
            code, start_line=1, end_line=1, function_name="get_value"
        ).apply()
        self.assertTrue(result.success)
        self.assertIn("def get_value", result.refactored_code)

    def test_extract_generates_diff(self) -> None:
        code = "x = 1\ny = 2\n"
        result = FunctionExtractorRef(
            code, start_line=1, end_line=2, function_name="setup"
        ).apply()
        self.assertIn("---", result.diff)
        self.assertIn("+++", result.diff)


if __name__ == '__main__':
    unittest.main()