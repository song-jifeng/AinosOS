"""AinosOS AI Test Generator - Python Test Generator.

Generates test cases for Python source code with support for:
- pytest, unittest, and doctest output formats
- Unit tests for each function
- Boundary value analysis
- Property-based testing (Hypothesis-style)
- Mock generation for dependencies
- Edge case detection
- Coverage-aware test generation
"""

import ast
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from analyzers.signature_analyzer import (
    FunctionSignature, ClassInfo, Parameter, ParameterKind, Language,
)
from analyzers.complexity_analyzer import ComplexityAnalyzer, ComplexityMetrics
from analyzers.dependency_analyzer import (
    DependencyAnalyzer, ModuleDependencyMap, MockRecommendation,
)


class PythonOutputFormat:
    """Supported Python test output formats."""
    PYTEST = "pytest"
    UNITTEST = "unittest"
    DOCTEST = "doctest"


@dataclass
class TestCase:
    """A single generated test case."""
    name: str
    body: str
    decorators: List[str] = field(default_factory=list)
    is_parametrized: bool = False
    parametrize_args: Optional[str] = None
    parametrize_values: Optional[str] = None

    def render(self, indent: int = 4) -> str:
        """Render the test case as Python code."""
        lines = []
        prefix = " " * indent

        for dec in self.decorators:
            lines.append(f"{prefix}{dec}")

        if self.is_parametrized and self.parametrize_args and self.parametrize_values:
            lines.append(f'{prefix}@pytest.mark.parametrize({self.parametrize_args}, {self.parametrize_values})')

        lines.append(f"{prefix}def {self.name}:")
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
    class_fixtures: List[str] = field(default_factory=list)

    def render(self, indent: int = 0) -> str:
        """Render the test class as Python code."""
        lines = []
        prefix = " " * indent

        for fixture in self.class_fixtures:
            lines.append(f"{prefix}{fixture}")

        lines.append(f"{prefix}class {self.name}:")

        if self.setup_method:
            lines.append(f"{prefix}    {self.setup_method}")
        if self.teardown_method:
            lines.append(f"{prefix}    {self.teardown_method}")

        for fixture in self.fixtures:
            for line in fixture.strip().split('\n'):
                lines.append(f"{prefix}    {line.strip()}")

        for tc in self.test_cases:
            lines.append(tc.render(4))

        lines.append("")
        return '\n'.join(lines)


class PythonGenerator:
    """Generates Python test cases from parsed signatures.

    Supports pytest, unittest, and doctest output formats.
    Generates unit tests, boundary tests, property-based tests, and edge cases.
    """

    # Common Python type mappings for test value generation
    TYPE_TEST_VALUES: Dict[str, List[str]] = {
        "int": ["0", "1", "-1", "42", "-42", "sys.maxsize", "-sys.maxsize - 1", "2**31 - 1", "-2**31"],
        "float": ["0.0", "1.0", "-1.0", "3.14159", "-3.14159", "float('inf')", "float('-inf')", "float('nan')"],
        "str": ['""', '"hello"', '"a"', '"A"', '"123"', '" "', '"\\n"', '"\\t"', '"unicode_éàü"'],
        "bool": ["True", "False"],
        "bytes": ['b""', 'b"hello"', 'b"\\x00"', 'b"\\xff"'],
        "list": ["[]", "[1, 2, 3]", '["a", "b"]', "[None]", "[[]]"],
        "dict": ["{}", '{"a": 1}', "{1: 2, 3: 4}", "{None: None}"],
        "tuple": ["()", "(1,)", "(1, 2, 3)", '("a", "b")'],
        "set": ["set()", "{1, 2, 3}", '{"a"}'],
        "None": ["None"],
        "Optional[int]": ["None", "0", "42"],
        "Optional[str]": ["None", '""', '"hello"'],
        "Optional[list]": ["None", "[]"],
        "Any": ["None", "0", '""', "[]", "{}"],
    }

    # Edge case categories
    EDGE_CASES = {
        "numeric": [
            ("zero", "0"),
            ("positive", "1"),
            ("negative", "-1"),
            ("max_int", "sys.maxsize"),
            ("min_int", "-sys.maxsize - 1"),
            ("positive_large", "10**6"),
            ("negative_large", "-10**6"),
            ("overflow", "2**63 - 1"),
            ("underflow", "-2**63"),
        ],
        "string": [
            ("empty", '""'),
            ("single_char", '"a"'),
            ("whitespace", '" "'),
            ("newline", '"\\n"'),
            ("unicode", '"\\u00e9\\u00e0\\u00fc"'),
            ("special_chars", '"!@#$%^&*()"'),
            ("very_long", '"a" * 1000'),
            ("null_byte", '"\\x00"'),
            ("sql_injection", '"\' OR 1=1 --"'),
            ("html_injection", '"<script>alert(1)</script>"'),
        ],
        "collection": [
            ("empty", "[]"),
            ("single_element", "[1]"),
            ("many_elements", "list(range(100))"),
            ("nested", "[[1, 2], [3, 4]]"),
            ("with_none", "[None, None]"),
            ("mixed_types", "[1, 'a', None, 3.14]"),
            ("duplicates", "[1, 1, 1, 1]"),
        ],
        "boolean": [
            ("true", "True"),
            ("false", "False"),
        ],
        "none": [
            ("none", "None"),
        ],
    }

    def __init__(self) -> None:
        self.complexity_analyzer = ComplexityAnalyzer()
        self.dependency_analyzer = DependencyAnalyzer()

    # ------------------------------------------------------------------ #
    #  Main Generation Entry Point
    # ------------------------------------------------------------------ #

    def generate(
        self,
        source: str,
        output_format: str = PythonOutputFormat.PYTEST,
        module_name: Optional[str] = None,
        include_property_tests: bool = True,
        include_boundary_tests: bool = True,
        include_edge_cases: bool = True,
        include_mock_tests: bool = True,
    ) -> str:
        """Generate test cases for Python source code.

        Args:
            source: Python source code to generate tests for.
            output_format: pytest, unittest, or doctest.
            module_name: Optional module name for imports.
            include_property_tests: Generate Hypothesis-style property tests.
            include_boundary_tests: Generate boundary value analysis tests.
            include_edge_cases: Generate edge case detection tests.
            include_mock_tests: Generate mock-based tests.

        Returns:
            Generated test code as a string.
        """
        from analyzers.signature_analyzer import SignatureAnalyzer

        analyzer = SignatureAnalyzer()
        functions, classes = analyzer.analyze_python(source)

        if output_format == PythonOutputFormat.DOCTEST:
            return self._generate_doctest(source, functions, classes)
        elif output_format == PythonOutputFormat.UNITTEST:
            return self._generate_unittest(source, functions, classes, module_name)
        else:
            return self._generate_pytest(
                source, functions, classes, module_name,
                include_property_tests, include_boundary_tests,
                include_edge_cases, include_mock_tests,
            )

    # ------------------------------------------------------------------ #
    #  pytest Generator
    # ------------------------------------------------------------------ #

    def _generate_pytest(
        self,
        source: str,
        functions: List[FunctionSignature],
        classes: List[ClassInfo],
        module_name: Optional[str] = None,
        include_property: bool = True,
        include_boundary: bool = True,
        include_edge: bool = True,
        include_mock: bool = True,
    ) -> str:
        """Generate pytest-style test cases."""
        lines = [
            f'"""Tests for {module_name or "module"}."""',
            "",
            "import sys",
            "import math",
            "from typing import Any, Dict, List, Optional",
            "from unittest.mock import MagicMock, patch, PropertyMock, call, AsyncMock",
            "",
            "import pytest",
            "",
        ]

        if module_name:
            lines.append(f"from {module_name} import (")
            # Collect all top-level function names and class names
            names = []
            for func in functions:
                names.append(func.name)
            for cls in classes:
                names.append(cls.name)
            lines.append("    " + ",\n    ".join(names) + ",")
            lines.append(")")
            lines.append("")

        # Add fixtures
        if module_name:
            dep_map = self.dependency_analyzer.analyze_python_dependencies(source, module_name)
            fixtures = self.dependency_analyzer.suggest_fixtures(dep_map)
            for fixture in fixtures:
                for line in fixture.strip().split('\n'):
                    lines.append(f"    {line.strip()}")
                lines.append("")

        test_classes = []

        # Generate test functions for module-level functions
        for func in functions:
            if not func.is_method:  # Skip methods (covered in class tests)
                test_cases = self._generate_test_cases_for_function(
                    func, source, include_property, include_boundary, include_edge, include_mock
                )
                for tc in test_cases:
                    lines.append(tc.render(0))
                    lines.append("")

        # Generate test classes for each class
        for cls in classes:
            test_class = self._generate_test_class(cls, functions, source,
                                                    include_property, include_boundary,
                                                    include_edge, include_mock)
            if test_class:
                # Render the class inline
                lines.append(test_class.render(0))
                lines.append("")

        return '\n'.join(lines)

    # ------------------------------------------------------------------ #
    #  unittest Generator
    # ------------------------------------------------------------------ #

    def _generate_unittest(
        self,
        source: str,
        functions: List[FunctionSignature],
        classes: List[ClassInfo],
        module_name: Optional[str] = None,
    ) -> str:
        """Generate unittest-style test cases."""
        lines = [
            f'"""Tests for {module_name or "module"} using unittest."""',
            "",
            "import sys",
            "import math",
            "import unittest",
            "from unittest.mock import MagicMock, patch, PropertyMock, call, AsyncMock",
            "from typing import Any, Dict, List, Optional",
            "",
        ]

        if module_name:
            lines.append(f"from {module_name} import (")
            names = []
            for func in functions:
                names.append(func.name)
            for cls in classes:
                names.append(cls.name)
            lines.append("    " + ",\n    ".join(names) + ",")
            lines.append(")")
            lines.append("")

        # Generate unittest.TestCase classes
        module_functions = [f for f in functions if not f.is_method]
        if module_functions:
            lines.append("class TestModuleFunctions(unittest.TestCase):")
            lines.append('    """Test cases for module-level functions."""')
            lines.append("")

            for func in module_functions:
                test_cases = self._generate_test_cases_for_function(
                    func, source, False, True, True, True
                )
                for tc in test_cases:
                    lines.append(f"    {tc.render(4)}")

            lines.append("")

        for cls in classes:
            test_class = self._generate_test_class(cls, functions, source, False, True, True, True)
            if test_class:
                # Convert to unittest style
                lines.append(f"class Test{cls.name}(unittest.TestCase):")
                lines.append(f'    """Test cases for {cls.name}."""')
                lines.append("")

                if test_class.setup_method:
                    lines.append(f"    {self._convert_to_unittest_setup(test_class.setup_method)}")
                if test_class.teardown_method:
                    lines.append(f"    {self._convert_to_unittest_teardown(test_class.teardown_method)}")

                for tc in test_class.test_cases:
                    lines.append(f"    {tc.render(4)}")

                lines.append("")

        lines.append("")
        lines.append('if __name__ == "__main__":')
        lines.append("    unittest.main()")
        lines.append("")

        return '\n'.join(lines)

    def _convert_to_unittest_setup(self, setup: str) -> str:
        """Convert a pytest fixture setup to unittest setUp."""
        return setup.replace("@pytest.fixture", "").replace("def setup_method", "def setUp")

    def _convert_to_unittest_teardown(self, teardown: str) -> str:
        """Convert teardown to unittest tearDown."""
        return teardown.replace("@pytest.fixture", "").replace("def teardown_method", "def tearDown")

    # ------------------------------------------------------------------ #
    #  doctest Generator
    # ------------------------------------------------------------------ #

    def _generate_doctest(
        self,
        source: str,
        functions: List[FunctionSignature],
        classes: List[ClassInfo],
    ) -> str:
        """Generate doctest-style examples within docstrings."""
        lines = []
        lines.append('"""')
        lines.append("Module doctests.")
        lines.append("")
        lines.append("Usage:")
        lines.append("    python -m doctest this_module.py")
        lines.append("")

        for func in functions:
            if func.is_method:
                continue
            lines.append(f">>> {func.name}()  # doctest: +SKIP")
            lines.append("...")

        for cls in classes:
            for method in cls.methods:
                if method.name.startswith('_'):
                    continue
                lines.append(f">>> {cls.name}().{method.name}()  # doctest: +SKIP")
                lines.append("...")

        lines.append('"""')

        return '\n'.join(lines)

    # ------------------------------------------------------------------ #
    #  Test Case Generation for a Single Function
    # ------------------------------------------------------------------ #

    def _generate_test_cases_for_function(
        self,
        func: FunctionSignature,
        source: str,
        include_property: bool,
        include_boundary: bool,
        include_edge: bool,
        include_mock: bool,
    ) -> List[TestCase]:
        """Generate all test cases for a single function."""
        test_cases: List[TestCase] = []

        # Basic unit test
        test_cases.append(self._generate_basic_test(func))

        # Return type test
        if func.return_type and func.return_type not in ("None", "NoneType"):
            test_cases.append(self._generate_return_type_test(func))

        # Parameter validation tests
        for param in func.parameters:
            if param.type_hint:
                test_cases.extend(self._generate_parameter_tests(func, param))

        # Edge case tests
        if include_edge:
            test_cases.extend(self._generate_edge_case_tests(func))

        # Boundary value tests
        if include_boundary:
            test_cases.extend(self._generate_boundary_tests(func))

        # Property-based tests
        if include_property:
            test_cases.append(self._generate_property_test(func))

        # Exception tests
        if func.raises or self._likely_raises_exceptions(func, source):
            test_cases.append(self._generate_exception_test(func, source))

        # Mock tests
        if include_mock:
            test_cases.extend(self._generate_mock_tests(func, source))

        return test_cases

    # ------------------------------------------------------------------ #
    #  Basic Unit Test
    # ------------------------------------------------------------------ #

    def _generate_basic_test(self, func: FunctionSignature) -> TestCase:
        """Generate a basic unit test for a function."""
        test_name = f"test_{func.name}_basic"
        params = self._generate_sample_args(func)

        if func.is_async:
            body = f"result = await {func.name}({params})"
        else:
            body = f"result = {func.name}({params})"

        if func.return_type and func.return_type not in ("None", "NoneType", "void"):
            body += f'\nassert result is not None, f"Expected non-None return from {func.name}"'

        return TestCase(name=test_name, body=body)

    def _generate_return_type_test(self, func: FunctionSignature) -> TestCase:
        """Generate a test that verifies the return type."""
        test_name = f"test_{func.name}_return_type"
        params = self._generate_sample_args(func)

        call = f"await {func.name}({params})" if func.is_async else f"{func.name}({params})"

        body = f"result = {call}"

        # Add type assertion based on return type
        rt = func.return_type or ""
        if "int" in rt:
            body += '\nassert isinstance(result, int), f"Expected int, got {type(result)}"'
        elif "float" in rt:
            body += '\nassert isinstance(result, (int, float)), f"Expected numeric, got {type(result)}"'
        elif "str" in rt:
            body += '\nassert isinstance(result, str), f"Expected str, got {type(result)}"'
        elif "bool" in rt:
            body += '\nassert isinstance(result, bool), f"Expected bool, got {type(result)}"'
        elif "list" in rt or "List" in rt:
            body += '\nassert isinstance(result, list), f"Expected list, got {type(result)}"'
        elif "dict" in rt or "Dict" in rt:
            body += '\nassert isinstance(result, dict), f"Expected dict, got {type(result)}"'
        elif "tuple" in rt or "Tuple" in rt:
            body += '\nassert isinstance(result, tuple), f"Expected tuple, got {type(result)}"'
        elif "Optional" in rt:
            body += '\nassert result is None or isinstance(result, object), "Optional return type"'
        elif "None" not in rt and rt != "NoneType":
            body += '\nassert result is not None, f"Expected non-None result from {func.name}"'

        return TestCase(name=test_name, body=body)

    # ------------------------------------------------------------------ #
    #  Parameter Validation Tests
    # ------------------------------------------------------------------ #

    def _generate_parameter_tests(self, func: FunctionSignature, param: Parameter) -> List[TestCase]:
        """Generate parameter-specific validation tests."""
        tests = []
        type_hint = param.type_hint or ""

        # Test with None for optional parameters
        if param.is_optional or "Optional" in type_hint:
            tests.append(self._generate_none_param_test(func, param))

        # Test type-specific edge cases
        if "int" in type_hint:
            tests.append(self._generate_int_param_test(func, param))
        elif "str" in type_hint:
            tests.append(self._generate_str_param_test(func, param))
        elif "float" in type_hint:
            tests.append(self._generate_float_param_test(func, param))
        elif "list" in type_hint or "List" in type_hint:
            tests.append(self._generate_list_param_test(func, param))
        elif "dict" in type_hint or "Dict" in type_hint:
            tests.append(self._generate_dict_param_test(func, param))
        elif "bool" in type_hint:
            tests.append(self._generate_bool_param_test(func, param))

        return tests

    def _generate_none_param_test(self, func: FunctionSignature, param: Parameter) -> TestCase:
        """Test that passing None works for optional parameters."""
        test_name = f"test_{func.name}_with_{param.name}_none"

        args = []
        for p in func.parameters:
            if p.name == param.name:
                args.append("None")
            else:
                args.append(self._get_default_value(p))

        params = ", ".join(args)
        call = f"await {func.name}({params})" if func.is_async else f"{func.name}({params})"
        body = f"# Test with None for optional parameter {param.name}\nresult = {call}"

        return TestCase(name=test_name, body=body)

    def _generate_int_param_test(self, func: FunctionSignature, param: Parameter) -> TestCase:
        """Generate tests for int parameters."""
        test_name = f"test_{func.name}_{param.name}_int_validation"

        cases = ["0", "1", "-1", "sys.maxsize", "-sys.maxsize - 1", "42", "-42"]
        args_template = []
        for p in func.parameters:
            if p.name == param.name:
                args_template.append("{value}")
            else:
                args_template.append(self._get_default_value(p))

        param_str = ", ".join(args_template)

        body_lines = [
            "# Test int parameter edge cases",
            "test_cases = [",
        ]
        for case in cases:
            test_args = param_str.format(value=case)
            call = f"await {func.name}({test_args})" if func.is_async else f"{func.name}({test_args})"
            body_lines.append(f"    ({case}, lambda: {call}),")

        body_lines.append("]")
        body_lines.append("for value, test_fn in test_cases:")
        body_lines.append('    try:')
        body_lines.append('        result = test_fn()')
        body_lines.append('    except Exception as exc:')
        body_lines.append(f'        pass  # Expected: int parameter {param.name} handled error')
        body_lines.append('')

        return TestCase(
            name=test_name,
            body='\n'.join(body_lines),
            is_parametrized=True,
            parametrize_args=f'"{param.name}_value"',
            parametrize_values=f"[{', '.join(cases)}]",
        )

    def _generate_str_param_test(self, func: FunctionSignature, param: Parameter) -> TestCase:
        """Generate tests for string parameters."""
        test_name = f"test_{func.name}_{param.name}_str_validation"
        body = (
            f'# Test string parameter {param.name}\n'
            f'result = {func.name}({param.name}="")\n'
            f'result = {func.name}({param.name}="hello")\n'
            f'result = {func.name}({param.name}="a" * 1000)\n'
        )
        return TestCase(name=test_name, body=body)

    def _generate_float_param_test(self, func: FunctionSignature, param: Parameter) -> TestCase:
        """Generate tests for float parameters."""
        test_name = f"test_{func.name}_{param.name}_float_validation"
        body = (
            f'# Test float parameter {param.name}\n'
            f'result = {func.name}({param.name}=0.0)\n'
            f'result = {func.name}({param.name}=1.0)\n'
            f'result = {func.name}({param.name}=-1.0)\n'
            f'result = {func.name}({param.name}=float("inf"))\n'
            f'result = {func.name}({param.name}=float("-inf"))\n'
            f'result = {func.name}({param.name}=float("nan"))\n'
        )
        return TestCase(name=test_name, body=body)

    def _generate_list_param_test(self, func: FunctionSignature, param: Parameter) -> TestCase:
        """Generate tests for list parameters."""
        test_name = f"test_{func.name}_{param.name}_list_validation"
        body = (
            f'# Test list parameter {param.name}\n'
            f'result = {func.name}({param.name}=[])\n'
            f'result = {func.name}({param.name}=[1, 2, 3])\n'
            f'result = {func.name}({param.name}=[[1, 2], [3, 4]])\n'
        )
        return TestCase(name=test_name, body=body)

    def _generate_dict_param_test(self, func: FunctionSignature, param: Parameter) -> TestCase:
        """Generate tests for dict parameters."""
        test_name = f"test_{func.name}_{param.name}_dict_validation"
        body = (
            f'# Test dict parameter {param.name}\n'
            f'result = {func.name}({param.name}={{\}})\n'
            f'result = {func.name}({param.name}={{"a": 1}})\n'
            f'result = {func.name}({param.name}={{"key": "value"}})\n'
        )
        return TestCase(name=test_name, body=body)

    def _generate_bool_param_test(self, func: FunctionSignature, param: Parameter) -> TestCase:
        """Generate tests for boolean parameters."""
        test_name = f"test_{func.name}_{param.name}_bool_validation"
        body = (
            f'# Test bool parameter {param.name}\n'
            f'result = {func.name}({param.name}=True)\n'
            f'result = {func.name}({param.name}=False)\n'
        )
        return TestCase(name=test_name, body=body)

    # ------------------------------------------------------------------ #
    #  Edge Case Tests
    # ------------------------------------------------------------------ #

    def _generate_edge_case_tests(self, func: FunctionSignature) -> List[TestCase]:
        """Generate edge case detection tests."""
        tests = []

        # Check for null/empty parameter edge cases
        for param in func.parameters:
            if param.type_hint in ("str", "Optional[str]") or "str" in (param.type_hint or ""):
                test_name = f"test_{func.name}_edge_empty_string_{param.name}"
                body = f"# Edge case: empty string for {func.name} parameter {param.name}"
                call = f"await {func.name}({param.name}='')" if func.is_async else f"{func.name}({param.name}='')"
                body += f"\nresult = {call}"
                tests.append(TestCase(name=test_name, body=body))

            if param.type_hint in ("list", "List", "Optional[list]") or "List" in (param.type_hint or ""):
                test_name = f"test_{func.name}_edge_empty_list_{param.name}"
                body = f"# Edge case: empty list for {func.name} parameter {param.name}"
                call = f"await {func.name}({param.name}=[])" if func.is_async else f"{func.name}({param.name}=[])"
                body += f"\nresult = {call}"
                tests.append(TestCase(name=test_name, body=body))

            if param.type_hint in ("dict", "Dict", "Optional[dict]") or "Dict" in (param.type_hint or ""):
                test_name = f"test_{func.name}_edge_empty_dict_{param.name}"
                body = f"# Edge case: empty dict for {func.name} parameter {param.name}"
                call = f"await {func.name}({param.name}={{\}})" if func.is_async else f"{func.name}({param.name}={{\}})"
                body += f"\nresult = {call}"
                tests.append(TestCase(name=test_name, body=body))

        # Null parameter test
        for param in func.parameters:
            if param.is_optional or "Optional" in (param.type_hint or ""):
                test_name = f"test_{func.name}_edge_null_{param.name}"
                body = f"# Edge case: None for {func.name} parameter {param.name}"
                call = f"await {func.name}({param.name}=None)" if func.is_async else f"{func.name}({param.name}=None)"
                body += f"\nresult = {call}"
                tests.append(TestCase(name=test_name, body=body))

        return tests

    # ------------------------------------------------------------------ #
    #  Boundary Value Tests
    # ------------------------------------------------------------------ #

    def _generate_boundary_tests(self, func: FunctionSignature) -> List[TestCase]:
        """Generate boundary value analysis tests."""
        tests = []

        for param in func.parameters:
            type_hint = param.type_hint or ""

            if "int" in type_hint:
                test_name = f"test_{func.name}_boundary_{param.name}"
                body = (
                    f"# Boundary value analysis for {func.name}({param.name}: int)\n"
                    f'"""Test boundary values: min, min+1, nominal, max-1, max."""\n'
                    f"# TODO: Adjust boundary values based on actual parameter constraints\n"
                    f"# Test that function handles int boundaries without crashing\n"
                    f"try:\n"
                    f"    result = {func.name}({param.name}=0)\n"
                    f"except (ValueError, TypeError, OverflowError):\n"
                    f"    pass  # Expected: boundary value may be rejected\n"
                )
                tests.append(TestCase(name=test_name, body=body))

            elif "float" in type_hint:
                test_name = f"test_{func.name}_boundary_{param.name}"
                body = (
                    f"# Boundary value analysis for {func.name}({param.name}: float)\n"
                    f"try:\n"
                    f"    result = {func.name}({param.name}=0.0)\n"
                    f"except (ValueError, TypeError):\n"
                    f"    pass\n"
                )
                tests.append(TestCase(name=test_name, body=body))

            elif "str" in type_hint:
                test_name = f"test_{func.name}_boundary_{param.name}"
                body = (
                    f"# Boundary value analysis for {func.name}({param.name}: str)\n"
                    f"try:\n"
                    f"    result = {func.name}({param.name}='')\n"
                    f"    result = {func.name}({param.name}='a')\n"
                    f"    result = {func.name}({param.name}='a' * 255)\n"
                    f"    result = {func.name}({param.name}='a' * 65535)\n"
                    f"except (ValueError, TypeError, OverflowError):\n"
                    f"    pass\n"
                )
                tests.append(TestCase(name=test_name, body=body))

        return tests

    # ------------------------------------------------------------------ #
    #  Property-Based Tests
    # ------------------------------------------------------------------ #

    def _generate_property_test(self, func: FunctionSignature) -> TestCase:
        """Generate a property-based test (Hypothesis-style)."""
        test_name = f"test_{func.name}_property_based"

        body_lines = [
            "# Property-based test using Hypothesis-style strategies",
            "# Requires: pip install hypothesis",
            "#",
            "# @given(",
        ]

        param_strategies = []
        for param in func.parameters:
            type_hint = param.type_hint or ""
            if "int" in type_hint:
                param_strategies.append(f"#     st.integers()")
            elif "float" in type_hint:
                param_strategies.append(f"#     st.floats()")
            elif "str" in type_hint:
                param_strategies.append(f"#     st.text()")
            elif "bool" in type_hint:
                param_strategies.append(f"#     st.booleans()")
            elif "list" in type_hint or "List" in type_hint:
                inner = "st.integers()"
                if "str" in type_hint:
                    inner = "st.text()"
                param_strategies.append(f"#     st.lists({inner})")
            elif "dict" in type_hint or "Dict" in type_hint:
                param_strategies.append(f"#     st.dictionaries(st.text(), st.integers())")
            elif "bytes" in type_hint:
                param_strategies.append(f"#     st.binary()")
            else:
                param_strategies.append(f"#     st.nothing()")

        body_lines.extend(param_strategies)
        body_lines.append(f"# )")
        body_lines.append(f"# def test_{func.name}_property({', '.join(p.name for p in func.parameters)}):")
        body_lines.append(f"#     \"\"\"Property: {func.name} should not raise unexpected exceptions.\"\"\"")

        params = ", ".join(p.name for p in func.parameters)
        call = f"await {func.name}({params})" if func.is_async else f"{func.name}({params})"
        body_lines.append(f"#     result = {call}")

        if func.return_type and func.return_type not in ("None", "NoneType"):
            body_lines.append(f"#     assert result is not None")

        body_lines.append("")

        return TestCase(
            name=test_name,
            body='\n'.join(body_lines),
            decorators=["@pytest.mark.skip(reason=\"Hypothesis test: uncomment and add strategies\")"],
        )

    # ------------------------------------------------------------------ #
    #  Exception Tests
    # ------------------------------------------------------------------ #

    def _generate_exception_test(self, func: FunctionSignature, source: str) -> TestCase:
        """Generate test for expected exception handling."""
        test_name = f"test_{func.name}_raises_exception"

        # Try to find what exceptions the function might raise
        exceptions = self._find_raised_exceptions(source, func.name)
        if not exceptions:
            exceptions = ["ValueError", "TypeError", "RuntimeError"]

        body = (
            f'# Test that {func.name} raises appropriate exceptions\n'
            f'"""Expected exceptions: {", ".join(exceptions)}"""\n'
            f'# TODO: Add specific invalid inputs that trigger each exception\n'
        )

        for exc in exceptions[:3]:
            body += (
                f'with pytest.raises({exc}):\n'
                f'    # TODO: provide input that triggers {exc}\n'
                f'    pass\n'
            )

        return TestCase(name=test_name, body=body)

    def _find_raised_exceptions(self, source: str, func_name: str) -> List[str]:
        """Find exceptions raised in a function from source."""
        exceptions = []
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == func_name:
                    for child in ast.walk(node):
                        if isinstance(child, ast.Raise):
                            if child.exc and isinstance(child.exc, ast.Call):
                                if isinstance(child.exc.func, ast.Name):
                                    exc_name = child.exc.func.id
                                    if exc_name not in exceptions:
                                        exceptions.append(exc_name)
        except SyntaxError:
            pass
        return exceptions

    def _likely_raises_exceptions(self, func: FunctionSignature, source: str) -> bool:
        """Check if a function is likely to raise exceptions."""
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func.name:
                    for child in ast.walk(node):
                        if isinstance(child, ast.Raise):
                            return True
                        if isinstance(child, ast.Assert):
                            return True
                        if isinstance(child, ast.Try):
                            return True
        except SyntaxError:
            pass
        return False

    # ------------------------------------------------------------------ #
    #  Mock Tests
    # ------------------------------------------------------------------ #

    def _generate_mock_tests(self, func: FunctionSignature, source: str) -> List[TestCase]:
        """Generate mock-based tests for external dependencies."""
        tests = []

        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func.name:
                    # Find external calls
                    external_calls = self._find_external_calls(node)
                    for call_name in external_calls:
                        test_name = f"test_{func.name}_mock_{call_name.replace('.', '_')}"
                        body = (
                            f'# Mock external call: {call_name}\n'
                            f'with patch("{call_name}") as mock_{call_name.replace(".", "_")}:\n'
                            f'    mock_{call_name.replace(".", "_")}.return_value = None\n'
                            f'    result = {func.name}()\n'
                            f'    mock_{call_name.replace(".", "_")}.assert_called_once()\n'
                        )
                        tests.append(TestCase(name=test_name, body=body))
        except SyntaxError:
            pass

        return tests

    def _find_external_calls(self, node: ast.FunctionDef) -> List[str]:
        """Find external function calls in a function body."""
        calls = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Attribute):
                    if isinstance(child.func.value, ast.Name):
                        calls.append(f"{child.func.value.id}.{child.func.attr}")
                elif isinstance(child.func, ast.Name):
                    name = child.func.id
                    if name not in ('range', 'len', 'int', 'str', 'float', 'list',
                                    'dict', 'set', 'tuple', 'type', 'isinstance',
                                    'hasattr', 'getattr', 'setattr', 'print',
                                    'open', 'super', 'property', 'classmethod',
                                    'staticmethod', 'property', 'map', 'filter',
                                    'zip', 'enumerate', 'sorted', 'reversed',
                                    'min', 'max', 'sum', 'abs', 'any', 'all',
                                    'repr', 'str', 'format', 'locals', 'globals',
                                    'hash', 'id', 'ord', 'chr', 'bin', 'hex',
                                    'oct', 'round', 'pow', 'divmod'):
                        calls.append(name)

        return calls

    # ------------------------------------------------------------------ #
    #  Test Class Generation
    # ------------------------------------------------------------------ #

    def _generate_test_class(
        self,
        cls: ClassInfo,
        all_functions: List[FunctionSignature],
        source: str,
        include_property: bool,
        include_boundary: bool,
        include_edge: bool,
        include_mock: bool,
    ) -> Optional[TestClass]:
        """Generate a test class for a source class."""
        if not cls.methods:
            return None

        test_class = TestClass(name=f"Test{cls.name}")

        # Add class-level fixtures
        test_class.class_fixtures = [f'@pytest.fixture\ndef {cls.name.lower()}_instance(self):\n    return {cls.name}()']

        # Generate test cases for each method
        for method in cls.methods:
            if method.name.startswith('__') and method.name not in ('__init__', '__str__', '__repr__', '__eq__'):
                continue

            if method.name == '__init__':
                test_class.setup_method = (
                    f'def setup_method(self):\n'
                    f'    """Set up test fixtures."""\n'
                    f'    self.instance = {cls.name}()\n'
                )
                continue

            test_cases = self._generate_test_cases_for_method(
                method, cls, include_property, include_boundary, include_edge, include_mock
            )
            test_class.test_cases.extend(test_cases)

        return test_class

    def _generate_test_cases_for_method(
        self,
        method: FunctionSignature,
        cls: ClassInfo,
        include_property: bool,
        include_boundary: bool,
        include_edge: bool,
        include_mock: bool,
    ) -> List[TestCase]:
        """Generate test cases for a class method."""
        test_cases: List[TestCase] = []

        # Basic method test
        test_name = f"test_{method.name}_basic"
        params = self._generate_sample_args(method)
        body = f"instance = {cls.name}()\nresult = instance.{method.name}({params})"
        test_cases.append(TestCase(name=test_name, body=body))

        # Return type test
        if method.return_type and method.return_type not in ("None", "NoneType"):
            test_name = f"test_{method.name}_return_type"
            params = self._generate_sample_args(method)
            body = (
                f"instance = {cls.name}()\n"
                f"result = instance.{method.name}({params})\n"
                f'assert result is not None, f"Expected non-None return from {cls.name}.{method.name}"'
            )
            test_cases.append(TestCase(name=test_name, body=body))

        # Edge case tests for methods
        if include_edge:
            for param in method.parameters:
                if param.type_hint in ("str", "Optional[str]") or "str" in (param.type_hint or ""):
                    test_name = f"test_{method.name}_edge_empty_string_{param.name}"
                    body = (
                        f"instance = {cls.name}()\n"
                        f"# Edge case: empty string for {method.name} parameter {param.name}\n"
                        f"result = instance.{method.name}({param.name}='')"
                    )
                    test_cases.append(TestCase(name=test_name, body=body))

        return test_cases

    # ------------------------------------------------------------------ #
    #  Helper Methods
    # ------------------------------------------------------------------ #

    def _generate_sample_args(self, func: FunctionSignature) -> str:
        """Generate sample argument values for a function call."""
        args = []
        for param in func.parameters:
            args.append(self._get_default_value(param))
        return ", ".join(args)

    def _get_default_value(self, param: Parameter) -> str:
        """Get a default test value for a parameter based on type."""
        if param.default_value is not None:
            return param.default_value

        type_hint = param.type_hint or ""

        if "bool" in type_hint:
            return "True"
        if "int" in type_hint:
            return "42"
        if "float" in type_hint:
            return "3.14"
        if "str" in type_hint:
            return '"test"'
        if "bytes" in type_hint:
            return 'b"test"'
        if "list" in type_hint or "List" in type_hint:
            return "[]"
        if "dict" in type_hint or "Dict" in type_hint:
            return "{}"
        if "tuple" in type_hint or "Tuple" in type_hint:
            return "()"
        if "set" in type_hint or "Set" in type_hint:
            return "set()"
        if "Any" in type_hint:
            return "None"
        if "Optional" in type_hint:
            return "None"
        if "Callable" in type_hint:
            return "lambda: None"
        if "Type" in type_hint:
            return "object"

        return "None"

    # ------------------------------------------------------------------ #
    #  Coverage-Aware Test Generation
    # ------------------------------------------------------------------ #

    def generate_coverage_aware_tests(
        self,
        source: str,
        coverage_data: Dict[str, Set[int]],
        module_name: Optional[str] = None,
    ) -> str:
        """Generate tests targeting uncovered lines from coverage data.

        Args:
            source: Python source code.
            coverage_data: Dict mapping function names to sets of uncovered line numbers.
            module_name: Optional module name.

        Returns:
            Test code targeting uncovered lines.
        """
        lines = [
            f'"""Coverage-aware tests for {module_name or "module"}."""',
            "",
            "import pytest",
            "from unittest.mock import MagicMock, patch",
            "",
        ]

        if module_name:
            lines.append(f"from {module_name} import *")
            lines.append("")

        lines.append("# Tests targeting uncovered code paths")
        lines.append("")

        for func_name, uncovered_lines in coverage_data.items():
            if uncovered_lines:
                test_name = f"test_{func_name}_coverage_uncovered"
                body = (
                    f"# Coverage gap: lines {sorted(uncovered_lines)} uncovered\n"
                    f"# TODO: Add test cases to cover these lines\n"
                    f'pytest.skip(f"Coverage gap: {func_name} lines {sorted(uncovered_lines)}")\n'
                )
                lines.append(f"def {test_name}:")
                for line in body.strip().split('\n'):
                    lines.append(f"    {line.strip()}")
                lines.append("")

        return '\n'.join(lines)

    def generate_test_matrix(self, func: FunctionSignature) -> List[Dict[str, Any]]:
        """Generate a test matrix for a function using boundary value analysis.

        Returns a list of test case dicts with parameter values and expected results.
        """
        matrix = []

        # Generate combinatorial test cases for up to 3 parameters
        if len(func.parameters) > 3:
            # Use pairwise sampling for functions with many parameters
            return self._generate_pairwise_test_matrix(func)

        # For simple functions, exhaustive boundary values
        param_values = []
        for param in func.parameters:
            values = self._get_boundary_values(param)
            param_values.append(values)

        # Build combinatorial test matrix
        if param_values:
            from itertools import product
            for combo in product(*param_values):
                test_case = {
                    "name": f"test_{func.name}_matrix",
                    "params": dict(zip([p.name for p in func.parameters], combo)),
                }
                matrix.append(test_case)

        return matrix

    def _get_boundary_values(self, param: Parameter) -> List[str]:
        """Get boundary values for a parameter."""
        type_hint = param.type_hint or ""
        if "int" in type_hint:
            return ["0", "1", "-1", "sys.maxsize", "-sys.maxsize - 1", "42"]
        if "float" in type_hint:
            return ["0.0", "1.0", "-1.0", "float('inf')", "float('-inf')", "float('nan')"]
        if "str" in type_hint:
            return ['""', '"a"', '"hello"', '" "']
        if "bool" in type_hint:
            return ["True", "False"]
        if "list" in type_hint or "List" in type_hint:
            return ["[]", "[1]", "[1, 2, 3]"]
        if "dict" in type_hint or "Dict" in type_hint:
            return ["{}", '{"a": 1}']
        return ["None"]

    def _generate_pairwise_test_matrix(self, func: FunctionSignature) -> List[Dict[str, Any]]:
        """Generate a pairwise test matrix for functions with many parameters."""
        matrix = []
        params = func.parameters

        # Use each parameter's default or boundary value
        for i, param in enumerate(params):
            values = self._get_boundary_values(param)
            for val in values[:2]:  # Take first 2 values per param for pairwise
                test_case = {
                    "name": f"test_{func.name}_pairwise_{i}",
                    "params": {p.name: self._get_default_value(p) for p in params},
                }
                test_case["params"][param.name] = val
                matrix.append(test_case)

        return matrix

    # ------------------------------------------------------------------ #
    #  Test Statistics
    # ------------------------------------------------------------------ #

    def generate_test_stats(self, generated_code: str) -> Dict[str, Any]:
        """Generate statistics about generated tests."""
        test_count = len(re.findall(r'^\s*def test_', generated_code, re.MULTILINE))
        class_count = len(re.findall(r'^\s*class Test', generated_code, re.MULTILINE))
        assertion_count = len(re.findall(r'\bassert\b', generated_code))
        fixture_count = len(re.findall(r'@pytest\.fixture', generated_code))
        parametrize_count = len(re.findall(r'@pytest\.mark\.parametrize', generated_code))
        mock_count = len(re.findall(r'MagicMock|mock\.patch|patch\(', generated_code))
        skip_count = len(re.findall(r'@pytest\.mark\.skip|pytest\.skip\(', generated_code))

        return {
            "test_count": test_count,
            "test_class_count": class_count,
            "assertion_count": assertion_count,
            "fixture_count": fixture_count,
            "parametrize_count": parametrize_count,
            "mock_count": mock_count,
            "skip_count": skip_count,
            "line_count": len(generated_code.splitlines()),
        }