"""AinosOS AI Test Generator - Signature Analyzer.

Parses function/method signatures from Python (AST), C (pycparser-style regex),
and Rust (regex-based) source files. Extracts parameter types, return types,
default values, decorators, generics, and docstrings.
"""

import ast
import re
import typing
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union


class ParameterKind(Enum):
    """Kinds of function parameters."""
    POSITIONAL_ONLY = auto()
    POSITIONAL_OR_KEYWORD = auto()
    VAR_POSITIONAL = auto()
    KEYWORD_ONLY = auto()
    VAR_KEYWORD = auto()


class Language(Enum):
    """Supported source languages."""
    PYTHON = "python"
    C = "c"
    RUST = "rust"


@dataclass
class Parameter:
    """Represents a single function parameter."""
    name: str
    type_hint: Optional[str] = None
    default_value: Optional[str] = None
    kind: ParameterKind = ParameterKind.POSITIONAL_OR_KEYWORD
    is_optional: bool = False
    is_nullable: bool = False
    constraints: List[str] = field(default_factory=list)
    description: Optional[str] = None


@dataclass
class FunctionSignature:
    """Represents a parsed function/method signature."""
    name: str
    parameters: List[Parameter] = field(default_factory=list)
    return_type: Optional[str] = None
    is_method: bool = False
    is_static: bool = False
    is_classmethod: bool = False
    is_async: bool = False
    is_generator: bool = False
    is_abstract: bool = False
    decorators: List[str] = field(default_factory=list)
    docstring: Optional[str] = None
    source_file: Optional[str] = None
    line_number: int = 0
    language: Language = Language.PYTHON
    raises: List[str] = field(default_factory=list)
    template_params: List[str] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
    body_lines: int = 0
    complexity: int = 0

    @property
    def parameter_count(self) -> int:
        return len(self.parameters)

    @property
    def required_parameter_count(self) -> int:
        return sum(1 for p in self.parameters if p.default_value is None)

    @property
    def has_return(self) -> bool:
        return self.return_type is not None and self.return_type not in (
            "None", "void", "()", "!", "never"
        )


@dataclass
class ClassInfo:
    """Represents a parsed class definition."""
    name: str
    bases: List[str] = field(default_factory=list)
    methods: List[FunctionSignature] = field(default_factory=list)
    class_attributes: Dict[str, str] = field(default_factory=dict)
    docstring: Optional[str] = None
    source_file: Optional[str] = None
    line_number: int = 0
    language: Language = Language.PYTHON
    is_abstract: bool = False
    decorators: List[str] = field(default_factory=list)
    generic_params: List[str] = field(default_factory=list)


class SignatureAnalyzer:
    """Analyzes source code to extract function/method signatures.

    Supports Python (AST), C (regex-based heuristic), and Rust (regex-based).
    """

    # ------------------------------------------------------------------ #
    #  C signature regex patterns
    # ------------------------------------------------------------------ #
    C_FUNC_PATTERN = re.compile(
        r"""
        ^\s*
        (?:static\s+|inline\s+|extern\s+|const\s+|volatile\s+)*
        (?P<return_type>[\w\s\*]+)\s+
        (?P<name>\w+)\s*
        \((?P<params>[^)]*)\)
        \s*;
        """,
        re.VERBOSE | re.MULTILINE,
    )

    C_FUNC_DEF_PATTERN = re.compile(
        r"""
        ^\s*
        (?:static\s+|inline\s+|extern\s+|const\s+|volatile\s+)*
        (?P<return_type>[\w\s\*]+)\s+
        (?P<name>\w+)\s*
        \((?P<params>[^)]*)\)
        \s*\{?
        """,
        re.VERBOSE | re.MULTILINE,
    )

    C_PARAM_PATTERN = re.compile(
        r"""
        (?:(?:const|volatile|register|restrict)\s+)?
        (?P<type>[\w\s\*\[\]]+)\s+
        (?P<name>\w+)
        (?:\s*=\s*(?P<default>[^,)]+))?
        """,
        re.VERBOSE,
    )

    C_TYPEDEF_PATTERN = re.compile(
        r"typedef\s+(?P<type>.+?)\s+(?P<name>\w+)\s*;"
    )

    C_STRUCT_PATTERN = re.compile(
        r"""
        (?:typedef\s+)?
        struct\s+(?P<name>\w+)\s*
        \{(?P<body>[^}]*)\}
        (?:\s*(?P<typedef>\w+))?\s*;
        """,
        re.VERBOSE | re.DOTALL,
    )

    # ------------------------------------------------------------------ #
    #  Rust signature regex patterns
    # ------------------------------------------------------------------ #
    RUST_FN_PATTERN = re.compile(
        r"""
        (?:
            (?:pub\s+)?
            (?:async\s+)?
            (?:unsafe\s+)?
            (?:extern\s+"[^"]*"\s+)?
        )?
        fn\s+
        (?P<name>\w+)
        (?:\s*<\s*(?P<generics>[^>]+)\s*>)?
        \s*
        \((?P<params>[^)]*)\)
        (?:\s*->\s*(?P<return_type>[^{;]+))?
        """,
        re.VERBOSE,
    )

    RUST_PARAM_PATTERN = re.compile(
        r"""
        (?:
            (?P<pat>\w+)\s*:
            \s*
            (?P<type>[^,=)]+?)
        )
        (?:\s*=\s*(?P<default>[^,)]+))?
        (?:\s*,
        |\s*\)?
        )
        """,
        re.VERBOSE,
    )

    RUST_IMPL_PATTERN = re.compile(
        r"""
        impl\s+(?P<generic><[^>]+>\s+)?
        (?P<type>\w+(?:<[^>]+>)?)
        (?:\s+for\s+(?P<for_type>\w+(?:<[^>]+>)?))?
        \s*\{
        """,
        re.VERBOSE | re.DOTALL,
    )

    RUST_STRUCT_PATTERN = re.compile(
        r"""
        (?:pub\s+)?
        struct\s+(?P<name>\w+)
        (?:\s*<\s*(?P<generics>[^>]+)\s*>)?
        (?:\s*\{[^}]*\}|;|\s*\()?
        """,
        re.VERBOSE,
    )

    RUST_TRAIT_PATTERN = re.compile(
        r"""
        (?:pub\s+)?
        trait\s+(?P<name>\w+)
        (?:\s*<\s*(?P<generics>[^>]+)\s*>)?
        (?:\s*:\s*(?P<bounds>[^{]+))?
        \s*\{
        """,
        re.VERBOSE,
    )

    RUST_ENUM_PATTERN = re.compile(
        r"""
        (?:pub\s+)?
        enum\s+(?P<name>\w+)
        (?:\s*<\s*(?P<generics>[^>]+)\s*>)?
        \s*\{
        """,
        re.VERBOSE,
    )

    # ------------------------------------------------------------------ #
    #  Python AST-based analysis
    # ------------------------------------------------------------------ #

    @staticmethod
    def _get_annotation_str(node: Optional[ast.AST]) -> Optional[str]:
        """Convert an AST annotation node to a string representation."""
        if node is None:
            return None
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{SignatureAnalyzer._get_annotation_str(node.value)}.{node.attr}"
        if isinstance(node, ast.Subscript):
            value = SignatureAnalyzer._get_annotation_str(node.value)
            if isinstance(node.slice, ast.Tuple):
                slices = ", ".join(
                    SignatureAnalyzer._get_annotation_str(el) or "?"
                    for el in node.slice.elts
                )
                return f"{value}[{slices}]"
            sl = SignatureAnalyzer._get_annotation_str(node.slice)
            return f"{value}[{sl}]"
        if isinstance(node, ast.Constant):
            return repr(node.value)
        if isinstance(node, ast.List):
            elements = ", ".join(
                SignatureAnalyzer._get_annotation_str(el) or "?"
                for el in node.elts
            )
            return f"[{elements}]"
        if isinstance(node, ast.Tuple):
            elements = ", ".join(
                SignatureAnalyzer._get_annotation_str(el) or "?"
                for el in node.elts
            )
            return f"({elements})"
        if isinstance(node, ast.BinOp):
            left = SignatureAnalyzer._get_annotation_str(node.left) or "?"
            right = SignatureAnalyzer._get_annotation_str(node.right) or "?"
            op = type(node.op).__name__.replace("_", " ").lower()
            return f"{left} {op} {right}"
        if isinstance(node, ast.Index):  # Python < 3.9
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
        """Parse Python source and return list of function and class signatures."""
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            raise ValueError(f"Failed to parse Python source: {e}") from e

        functions: List[FunctionSignature] = []
        classes: List[ClassInfo] = []

        self._walk_python_body(tree.body, functions, classes, filepath=filepath, source_lines=source.splitlines(True))

        return functions, classes

    def _walk_python_body(self, body: List[ast.stmt], functions: List[FunctionSignature],
                          classes: List[ClassInfo], filepath: Optional[str] = None,
                          source_lines: Optional[List[str]] = None,
                          class_context: Optional[ClassInfo] = None) -> None:
        """Walk AST body collecting functions and classes recursively."""
        for node in body:
            if isinstance(node, ast.FunctionDef):
                if class_context is not None:
                    sig = self._parse_method(node, class_context, source_lines)
                else:
                    sig = self._parse_function(node, source_lines)
                if sig is not None:
                    sig.source_file = filepath
                    functions.append(sig)
                    if class_context is not None:
                        class_context.methods.append(sig)
            elif isinstance(node, ast.AsyncFunctionDef):
                sig = self._parse_function(node, source_lines)
                if sig is not None:
                    sig.source_file = filepath
                    sig.is_async = True
                    functions.append(sig)
                    if class_context is not None:
                        class_context.methods.append(sig)
            elif isinstance(node, ast.ClassDef):
                cls = self._parse_class(node, source_lines)
                cls.source_file = filepath
                classes.append(cls)
                self._walk_python_body(node.body, functions, classes, filepath, source_lines, cls)
            elif isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id in ("__name__", "TYPE_CHECKING"):
                # Skip __main__ guards and type checking blocks
                pass
            elif isinstance(node, (ast.For, ast.While, ast.With, ast.Try, ast.If)):
                self._walk_python_body(node.body, functions, classes, filepath, source_lines, class_context)
                if isinstance(node, (ast.Try, ast.If)):
                    for handler in getattr(node, "handlers", []):
                        self._walk_python_body(handler.body, functions, classes, filepath, source_lines, class_context)
                    self._walk_python_body(getattr(node, "orelse", []), functions, classes, filepath, source_lines, class_context)
                    self._walk_python_body(getattr(node, "finalbody", []), functions, classes, filepath, source_lines, class_context)

    def _parse_function(self, node: ast.FunctionDef, source_lines: Optional[List[str]] = None) -> FunctionSignature:
        """Parse a Python function definition."""
        sig = FunctionSignature(
            name=node.name,
            return_type=self._get_annotation_str(node.returns),
            is_async=isinstance(node, ast.AsyncFunctionDef),
            decorators=[self._decorator_name(d) for d in node.decorator_list],
            docstring=self._get_docstring(node.body),
            line_number=node.lineno,
            language=Language.PYTHON,
            body_lines=node.end_lineno - node.lineno if hasattr(node, 'end_lineno') and node.end_lineno else 0,
        )

        # Check for generator (yield in body)
        sig.is_generator = self._has_yield(node.body)

        # Check for abstract
        for d in node.decorator_list:
            name = self._decorator_name(d)
            if name in ("abstractmethod", "abstractclassmethod", "abstractstaticmethod"):
                sig.is_abstract = True

        # Process parameters
        args = node.args
        # Positional-only parameters
        for arg in args.posonlyargs:
            param = self._parse_arg(arg, source_lines)
            param.kind = ParameterKind.POSITIONAL_ONLY
            sig.parameters.append(param)

        # Positional or keyword parameters
        defaults_start = len(args.args) - len(args.defaults)
        for i, arg in enumerate(args.args):
            param = self._parse_arg(arg, source_lines)
            if i >= defaults_start:
                default_idx = i - defaults_start
                if default_idx < len(args.defaults):
                    param.default_value = ast.unparse(args.defaults[default_idx]) if hasattr(ast, 'unparse') else self._ast_node_to_str(args.defaults[default_idx])
                    param.is_optional = True
            sig.parameters.append(param)

        # *args
        if args.vararg:
            param = self._parse_arg(args.vararg, source_lines)
            param.kind = ParameterKind.VAR_POSITIONAL
            sig.parameters.append(param)

        # Keyword-only parameters
        for i, arg in enumerate(args.kwonlyargs):
            param = self._parse_arg(arg, source_lines)
            param.kind = ParameterKind.KEYWORD_ONLY
            if i < len(args.kw_defaults) and args.kw_defaults[i] is not None:
                param.default_value = ast.unparse(args.kw_defaults[i]) if hasattr(ast, 'unparse') else self._ast_node_to_str(args.kw_defaults[i])
                param.is_optional = True
            sig.parameters.append(param)

        # **kwargs
        if args.kwarg:
            param = self._parse_arg(args.kwarg, source_lines)
            param.kind = ParameterKind.VAR_KEYWORD
            sig.parameters.append(param)

        return sig

    def _parse_method(self, node: ast.FunctionDef, cls: ClassInfo,
                      source_lines: Optional[List[str]] = None) -> FunctionSignature:
        """Parse a Python method definition within a class."""
        sig = self._parse_function(node, source_lines)
        sig.is_method = True

        # Determine method type from decorators
        for d in node.decorator_list:
            name = self._decorator_name(d)
            if name == "staticmethod":
                sig.is_static = True
            elif name == "classmethod":
                sig.is_classmethod = True

        # Check if first param is cls (classmethod) or self (instance method)
        if sig.parameters:
            first_param = sig.parameters[0].name
            if sig.is_classmethod:
                if first_param == "cls":
                    sig.parameters.pop(0)
            elif not sig.is_static:
                if first_param in ("self", "cls"):
                    sig.parameters.pop(0)

        return sig

    def _parse_arg(self, arg: ast.arg, source_lines: Optional[List[str]] = None) -> Parameter:
        """Parse a single function argument."""
        return Parameter(
            name=arg.arg,
            type_hint=self._get_annotation_str(arg.annotation),
            description=self._find_comment_for_arg(arg.arg, source_lines) if source_lines else None,
        )

    def _parse_class(self, node: ast.ClassDef, source_lines: Optional[List[str]] = None) -> ClassInfo:
        """Parse a Python class definition."""
        bases = []
        for base in node.bases:
            b = self._get_annotation_str(base)
            if b:
                bases.append(b)

        cls = ClassInfo(
            name=node.name,
            bases=bases,
            docstring=self._get_docstring(node.body),
            line_number=node.lineno,
            language=Language.PYTHON,
            decorators=[self._decorator_name(d) for d in node.decorator_list],
        )

        # Check for abstract
        for d in node.decorator_list:
            if self._decorator_name(d) in ("abstractmethod", "ABC", "ABCMeta"):
                cls.is_abstract = True
        for base in bases:
            if base == "ABC" or "ABC" in base:
                cls.is_abstract = True

        # Extract class-level attributes
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        val = ast.unparse(stmt.value) if hasattr(ast, 'unparse') else self._ast_node_to_str(stmt.value)
                        cls.class_attributes[target.id] = val

        return cls

    def _decorator_name(self, node: ast.AST) -> str:
        """Get the name of a decorator."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self._decorator_name(node.value)}.{node.attr}"
        if isinstance(node, ast.Call):
            return self._decorator_name(node.func)
        return str(node)

    def _has_yield(self, body: List[ast.stmt]) -> bool:
        """Check if a function body contains a yield statement."""
        for node in ast.walk(ast.Module(body=body, type_ignores=[])):
            if isinstance(node, ast.Yield) or isinstance(node, ast.YieldFrom):
                return True
        return False

    def _ast_node_to_str(self, node: ast.AST) -> str:
        """Convert AST node to string for Python < 3.9 compatibility."""
        if isinstance(node, ast.Constant):
            return repr(node.value)
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.List):
            return "[" + ", ".join(self._ast_node_to_str(e) for e in node.elts) + "]"
        if isinstance(node, ast.Tuple):
            return "(" + ", ".join(self._ast_node_to_str(e) for e in node.elts) + ")"
        if isinstance(node, ast.Dict):
            keys = [self._ast_node_to_str(k) for k in node.keys if k is not None]
            vals = [self._ast_node_to_str(v) for v in node.values]
            return "{" + ", ".join(f"{k}: {v}" for k, v in zip(keys, vals)) + "}"
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return "-" + self._ast_node_to_str(node.operand)
            if isinstance(node.op, ast.UAdd):
                return "+" + self._ast_node_to_str(node.operand)
            if isinstance(node.op, ast.Not):
                return "not " + self._ast_node_to_str(node.operand)
        if isinstance(node, ast.BinOp):
            left = self._ast_node_to_str(node.left)
            right = self._ast_node_to_str(node.right)
            if isinstance(node.op, ast.Add):
                return f"({left} + {right})"
            if isinstance(node.op, ast.Sub):
                return f"({left} - {right})"
            if isinstance(node.op, ast.Mult):
                return f"({left} * {right})"
            if isinstance(node.op, ast.Div):
                return f"({left} / {right})"
            if isinstance(node.op, ast.Mod):
                return f"({left} % {right})"
        if isinstance(node, ast.Call):
            func = self._ast_node_to_str(node.func)
            args = ", ".join(self._ast_node_to_str(a) for a in node.args)
            return f"{func}({args})"
        if isinstance(node, ast.Attribute):
            return f"{self._ast_node_to_str(node.value)}.{node.attr}"
        if isinstance(node, ast.Subscript):
            return f"{self._ast_node_to_str(node.value)}[{self._ast_node_to_str(node.slice)}]"
        if isinstance(node, ast.Slice):
            lower = self._ast_node_to_str(node.lower) if node.lower else ""
            upper = self._ast_node_to_str(node.upper) if node.upper else ""
            step = self._ast_node_to_str(node.step) if node.step else ""
            if step:
                return f"{lower}:{upper}:{step}"
            return f"{lower}:{upper}"
        if isinstance(node, ast.Constant):
            return repr(node.value)
        return "..."

    def _find_comment_for_arg(self, arg_name: str, source_lines: Optional[List[str]]) -> Optional[str]:
        """Try to find an inline comment describing a parameter."""
        if not source_lines:
            return None
        pattern = re.compile(rf"#.*\b{arg_name}\b[:\s]*(.*)", re.IGNORECASE)
        for line in source_lines:
            match = pattern.search(line)
            if match:
                return match.group(1).strip()
        return None

    # ------------------------------------------------------------------ #
    #  C source analysis
    # ------------------------------------------------------------------ #

    def analyze_c(self, source: str, filepath: Optional[str] = None) -> Tuple[List[FunctionSignature], List[ClassInfo]]:
        """Parse C source and return function signatures and struct info."""
        # Remove comments
        source = self._remove_c_comments(source)

        functions: List[FunctionSignature] = []
        structs: List[ClassInfo] = []

        # Parse structs
        for match in self.C_STRUCT_PATTERN.finditer(source):
            name = match.group("typedef") or match.group("name")
            cls = ClassInfo(
                name=name,
                source_file=filepath,
                line_number=source[:match.start()].count("\n") + 1,
                language=Language.C,
            )
            structs.append(cls)

        # Parse function definitions
        for match in self.C_FUNC_DEF_PATTERN.finditer(source):
            ret_type = match.group("return_type").strip()
            name = match.group("name")
            params_str = match.group("params")
            line_no = source[:match.start()].count("\n") + 1

            # Skip if it looks like a control flow keyword
            if name in ("if", "while", "for", "switch", "return", "sizeof"):
                continue

            sig = FunctionSignature(
                name=name,
                return_type=ret_type,
                language=Language.C,
                source_file=filepath,
                line_number=line_no,
                body_lines=self._estimate_c_body_lines(source, match.end()),
            )

            # Parse parameters
            self._parse_c_parameters(params_str, sig)

            # Check for void return
            if "void" in ret_type and ret_type.strip() == "void":
                pass  # Valid void return

            # Detect pointer return
            if "*" in ret_type:
                sig.attributes["is_pointer_return"] = True

            functions.append(sig)

        # Parse function declarations separately
        for match in self.C_FUNC_PATTERN.finditer(source):
            # Skip if already matched as definition
            if any(f.name == match.group("name") and f.line_number == source[:match.start()].count("\n") + 1 for f in functions):
                continue
            ret_type = match.group("return_type").strip()
            name = match.group("name")
            if name in ("if", "while", "for", "switch", "return", "sizeof"):
                continue
            sig = FunctionSignature(
                name=name,
                return_type=ret_type,
                language=Language.C,
                source_file=filepath,
                line_number=source[:match.start()].count("\n") + 1,
            )
            self._parse_c_parameters(match.group("params"), sig)
            sig.attributes["is_declaration"] = True
            functions.append(sig)

        return functions, structs

    def _parse_c_parameters(self, params_str: str, sig: FunctionSignature) -> None:
        """Parse C function parameters from a comma-separated string."""
        if not params_str or params_str.strip() == "void":
            return

        # Handle nested parens in function pointers
        depth = 0
        param_parts = []
        current = []
        for ch in params_str:
            if ch == ',' and depth == 0:
                param_parts.append(''.join(current).strip())
                current = []
            else:
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                current.append(ch)
        if current:
            param_parts.append(''.join(current).strip())

        for part in param_parts:
            if not part:
                continue
            # Try to match type + name pattern
            match = self.C_PARAM_PATTERN.search(part)
            if match:
                param = Parameter(
                    name=match.group("name"),
                    type_hint=match.group("type").strip(),
                    default_value=match.group("default"),
                    is_optional=match.group("default") is not None,
                )
                if "const" in part:
                    param.constraints.append("const")
                sig.parameters.append(param)
            else:
                # Might be just a type (function pointer, unnamed param)
                param = Parameter(
                    name=f"arg{sig.parameter_count + 1}",
                    type_hint=part.strip(),
                )
                sig.parameters.append(param)

    def _estimate_c_body_lines(self, source: str, start: int) -> int:
        """Estimate the number of lines in a C function body."""
        rest = source[start:]
        depth = 0
        for i, ch in enumerate(rest):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return rest[:i].count("\n") + 1
        return 0

    # ------------------------------------------------------------------ #
    #  Rust source analysis
    # ------------------------------------------------------------------ #

    def analyze_rust(self, source: str, filepath: Optional[str] = None) -> Tuple[List[FunctionSignature], List[ClassInfo]]:
        """Parse Rust source and return function signatures and type info."""
        # Remove comments
        source = self._remove_rust_comments(source)

        functions: List[FunctionSignature] = []
        types: List[ClassInfo] = []

        # Parse structs
        for match in self.RUST_STRUCT_PATTERN.finditer(source):
            cls = ClassInfo(
                name=match.group("name"),
                source_file=filepath,
                line_number=source[:match.start()].count("\n") + 1,
                language=Language.RUST,
                generic_params=self._parse_rust_generics(match.group("generics")),
            )
            types.append(cls)

        # Parse traits
        for match in self.RUST_TRAIT_PATTERN.finditer(source):
            cls = ClassInfo(
                name=match.group("name"),
                source_file=filepath,
                line_number=source[:match.start()].count("\n") + 1,
                language=Language.RUST,
                generic_params=self._parse_rust_generics(match.group("generics")),
            )
            cls.is_abstract = True
            if match.group("bounds"):
                cls.bases = [b.strip() for b in match.group("bounds").split("+")]
            types.append(cls)

        # Parse enums
        for match in self.RUST_ENUM_PATTERN.finditer(source):
            cls = ClassInfo(
                name=match.group("name"),
                source_file=filepath,
                line_number=source[:match.start()].count("\n") + 1,
                language=Language.RUST,
                generic_params=self._parse_rust_generics(match.group("generics")),
            )
            types.append(cls)

        # Parse functions
        for match in self.RUST_FN_PATTERN.finditer(source):
            name = match.group("name")
            ret_type = match.group("return_type")
            params_str = match.group("params")
            generics = match.group("generics")

            # Skip if it's inside an impl block (handled separately)
            preceding = source[:match.start()]
            if re.search(r'impl\b', preceding) and not re.search(r'}\s*$', preceding.rstrip()):
                pass  # Still process - it's a method

            line_no = source[:match.start()].count("\n") + 1
            sig = FunctionSignature(
                name=name,
                return_type=ret_type.strip() if ret_type else None,
                language=Language.RUST,
                source_file=filepath,
                line_number=line_no,
                template_params=self._parse_rust_generics(generics),
            )

            # Detect async
            if "async" in preceding[-100:]:
                sig.is_async = True

            # Detect unsafe
            if "unsafe" in preceding[-100:]:
                sig.attributes["unsafe"] = True

            # Parse parameters
            self._parse_rust_parameters(params_str, sig)

            functions.append(sig)

        return functions, types

    def _parse_rust_parameters(self, params_str: str, sig: FunctionSignature) -> None:
        """Parse Rust function parameters."""
        if not params_str or params_str.strip() == "":
            return

        # Handle self parameter
        params_str = params_str.strip()
        if params_str.startswith("&self") or params_str.startswith("self"):
            self_match = re.match(r"(&?self)\s*,?\s*", params_str)
            if self_match:
                param = Parameter(
                    name="self",
                    type_hint=self_match.group(1),
                    kind=ParameterKind.POSITIONAL_OR_KEYWORD,
                )
                sig.parameters.append(param)
                sig.is_method = True
                params_str = params_str[self_match.end():]

        if not params_str:
            return

        # Split on commas at top level
        parts = self._split_rust_params(params_str)

        for part in parts:
            part = part.strip()
            if not part:
                continue
            match = self.RUST_PARAM_PATTERN.match(part)
            if match:
                param = Parameter(
                    name=match.group("pat"),
                    type_hint=match.group("type").strip(),
                    default_value=match.group("default"),
                    is_optional=match.group("default") is not None,
                )
                sig.parameters.append(param)
            elif ":" in part:
                name, _, typ = part.partition(":")
                param = Parameter(
                    name=name.strip(),
                    type_hint=typ.strip(),
                )
                sig.parameters.append(param)
            else:
                param = Parameter(
                    name=f"arg{sig.parameter_count + 1}",
                    type_hint=part.strip(),
                )
                sig.parameters.append(param)

    def _split_rust_params(self, params_str: str) -> List[str]:
        """Split Rust parameter string on commas, respecting generics."""
        depth_paren = 0
        depth_angle = 0
        parts = []
        current = []
        for ch in params_str:
            if ch == ',' and depth_paren == 0 and depth_angle == 0:
                parts.append(''.join(current))
                current = []
            else:
                if ch == '(':
                    depth_paren += 1
                elif ch == ')':
                    depth_paren -= 1
                elif ch == '<':
                    depth_angle += 1
                elif ch == '>':
                    depth_angle -= 1
                current.append(ch)
        if current:
            parts.append(''.join(current))
        return parts

    def _parse_rust_generics(self, generics_str: Optional[str]) -> List[str]:
        """Parse Rust generic parameters."""
        if not generics_str:
            return []
        parts = []
        for part in generics_str.split(","):
            part = part.strip()
            if part:
                # Take just the name before any trait bounds
                name = part.split(":")[0].strip()
                parts.append(name)
        return parts

    # ------------------------------------------------------------------ #
    #  Comment removal
    # ------------------------------------------------------------------ #

    @staticmethod
    def _remove_c_comments(source: str) -> str:
        """Remove C-style comments (/* */ and //)."""
        # Remove block comments
        source = re.sub(r'/\*[\s\S]*?\*/', '', source)
        # Remove line comments
        source = re.sub(r'//.*', '', source)
        return source

    @staticmethod
    def _remove_rust_comments(source: str) -> str:
        """Remove Rust-style comments (///, //!, //, /* */)."""
        # Remove doc comments
        source = re.sub(r'///.*', '', source)
        source = re.sub(r'//!.*', '', source)
        # Remove block comments
        source = re.sub(r'/\*[\s\S]*?\*/', '', source)
        # Remove line comments
        source = re.sub(r'//.*', '', source)
        return source

    # ------------------------------------------------------------------ #
    #  Combined analysis
    # ------------------------------------------------------------------ #

    def analyze(self, source: str, language: Language, filepath: Optional[str] = None) -> Tuple[List[FunctionSignature], List[ClassInfo]]:
        """Analyze source code in the given language."""
        if language == Language.PYTHON:
            return self.analyze_python(source, filepath)
        elif language == Language.C:
            return self.analyze_c(source, filepath)
        elif language == Language.RUST:
            return self.analyze_rust(source, filepath)
        else:
            raise ValueError(f"Unsupported language: {language}")

    def analyze_file(self, filepath: Union[str, Path]) -> Tuple[List[FunctionSignature], List[ClassInfo]]:
        """Analyze a source file, detecting language from extension."""
        path = Path(filepath)
        source = path.read_text(encoding="utf-8", errors="replace")
        ext = path.suffix.lower()

        lang_map = {
            ".py": Language.PYTHON,
            ".c": Language.C,
            ".h": Language.C,
            ".rs": Language.RUST,
        }

        language = lang_map.get(ext)
        if language is None:
            raise ValueError(f"Unsupported file extension: {ext}")

        return self.analyze(source, language, str(path))

    def analyze_directory(self, directory: Union[str, Path]) -> Dict[str, Tuple[List[FunctionSignature], List[ClassInfo]]]:
        """Analyze all supported source files in a directory recursively."""
        directory = Path(directory)
        results: Dict[str, Tuple[List[FunctionSignature], List[ClassInfo]]] = {}
        supported_exts = {".py", ".c", ".h", ".rs"}

        for path in directory.rglob("*"):
            if path.suffix.lower() in supported_exts and path.is_file():
                try:
                    results[str(path)] = self.analyze_file(path)
                except Exception as e:
                    results[str(path)] = ([], [])
                    results[str(path)][0].append(FunctionSignature(
                        name=f"<error: {e}>",
                        line_number=0,
                        language=Language.PYTHON,
                    ))

        return results