"""AinosOS AI Test Generator - Complexity Analyzer.

Analyzes code complexity metrics including cyclomatic complexity, cognitive
complexity, Halstead metrics, nesting depth, and code volume. These metrics
guide test case generation priority and coverage requirements.
"""

import ast
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set, Tuple

from .signature_analyzer import FunctionSignature, Language


class ComplexityLevel(Enum):
    """Classification of complexity for test prioritization."""
    TRIVIAL = auto()
    LOW = auto()
    MODERATE = auto()
    COMPLEX = auto()
    VERY_COMPLEX = auto()
    UNTESTABLE = auto()


@dataclass
class ComplexityMetrics:
    """Aggregated complexity metrics for a function or file."""
    cyclomatic_complexity: int = 0
    cognitive_complexity: int = 0
    nesting_depth: int = 0
    lines_of_code: int = 0
    logical_lines: int = 0
    parameter_count: int = 0
    return_count: int = 0
    branch_count: int = 0
    loop_count: int = 0
    exception_handler_count: int = 0
    boolean_operator_count: int = 0
    recursion_depth: int = 0
    call_count: int = 0

    # Halstead metrics
    halstead_unique_operators: int = 0
    halstead_unique_operands: int = 0
    halstead_total_operators: int = 0
    halstead_total_operands: int = 0
    halstead_vocabulary: float = 0.0
    halstead_length: float = 0.0
    halstead_volume: float = 0.0
    halstead_difficulty: float = 0.0
    halstead_effort: float = 0.0
    halstead_bugs: float = 0.0

    # Maintainability
    maintainability_index: float = 100.0
    test_priority: float = 0.0

    @property
    def level(self) -> ComplexityLevel:
        if self.cyclomatic_complexity <= 1 and self.cognitive_complexity <= 2:
            return ComplexityLevel.TRIVIAL
        if self.cyclomatic_complexity <= 5 and self.cognitive_complexity <= 10:
            return ComplexityLevel.LOW
        if self.cyclomatic_complexity <= 10 and self.cognitive_complexity <= 20:
            return ComplexityLevel.MODERATE
        if self.cyclomatic_complexity <= 20 and self.cognitive_complexity <= 40:
            return ComplexityLevel.COMPLEX
        if self.cyclomatic_complexity <= 50:
            return ComplexityLevel.VERY_COMPLEX
        return ComplexityLevel.UNTESTABLE

    @property
    def recommended_coverage(self) -> float:
        if self.level == ComplexityLevel.TRIVIAL:
            return 0.8
        if self.level == ComplexityLevel.LOW:
            return 0.85
        if self.level == ComplexityLevel.MODERATE:
            return 0.9
        if self.level == ComplexityLevel.COMPLEX:
            return 0.95
        if self.level == ComplexityLevel.VERY_COMPLEX:
            return 0.98
        return 0.99


@dataclass
class FileComplexitySummary:
    """Complexity summary for an entire file."""
    filepath: str
    function_metrics: Dict[str, ComplexityMetrics] = field(default_factory=dict)
    total_cyclomatic: int = 0
    total_cognitive: int = 0
    average_complexity: float = 0.0
    max_complexity: float = 0.0
    most_complex_function: Optional[str] = None
    total_lines: int = 0
    function_count: int = 0


class ComplexityAnalyzer:
    """Analyzes code complexity using multiple metrics.

    Supports:
    - Cyclomatic complexity (McCabe)
    - Cognitive complexity (SonarQube-style)
    - Halstead metrics
    - Nesting depth
    - Maintainability index
    - Test priority scoring
    """

    # Python keywords that increase cyclomatic complexity
    CYCLOMATIC_BRANCH_KEYWORDS = {
        ast.If, ast.While, ast.For, ast.ExceptHandler,
        ast.Assert, ast.Raise,
    }

    CYCLOMATIC_BOOLEAN_OPS = {ast.And, ast.Or}

    # Cognitive complexity incrementors
    COGNITIVE_BASE_KEYWORDS = {
        ast.If, ast.Else, ast.While, ast.For, ast.ExceptHandler,
        ast.Try, ast.Assert, ast.Raise,
    }

    COGNITIVE_NESTING_KEYWORDS = {
        ast.If, ast.While, ast.For, ast.ExceptHandler,
        ast.Try, ast.With, ast.FunctionDef, ast.AsyncFunctionDef,
    }

    def __init__(self) -> None:
        self._cache: Dict[str, ComplexityMetrics] = {}

    # ------------------------------------------------------------------ #
    #  Cyclomatic Complexity (McCabe)
    # ------------------------------------------------------------------ #

    def compute_cyclomatic(self, source: str, language: Language = Language.PYTHON) -> int:
        """Compute McCabe's cyclomatic complexity for a source snippet."""
        if language == Language.PYTHON:
            return self._compute_python_cyclomatic(source)
        elif language == Language.C:
            return self._compute_c_cyclomatic(source)
        elif language == Language.RUST:
            return self._compute_rust_cyclomatic(source)
        return 1

    def _compute_python_cyclomatic(self, source: str) -> int:
        """Compute cyclomatic complexity for Python source."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return 1

        complexity = 1  # Base complexity

        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                complexity += 1
                # Count elif branches
                if isinstance(node, ast.If):
                    self._count_elif_branches(node, complexity)
            elif isinstance(node, (ast.While, ast.For, ast.AsyncFor)):
                complexity += 1
            elif isinstance(node, ast.ExceptHandler):
                complexity += 1
            elif isinstance(node, ast.Assert):
                complexity += 1
            elif isinstance(node, ast.BoolOp):
                # Each boolean operator adds 1
                complexity += len(node.values) - 1
            elif isinstance(node, ast.Raise):
                complexity += 1

        return complexity

    def _count_elif_branches(self, node: ast.If, complexity: int) -> int:
        """Count elif branches recursively."""
        for child in ast.walk(node):
            if isinstance(child, ast.If) and child != node:
                if (hasattr(child, 'parent') and
                        getattr(child, 'parent', None) is node.orelse):
                    complexity += 1
        return complexity

    def _compute_c_cyclomatic(self, source: str) -> int:
        """Compute cyclomatic complexity for C source using regex."""
        complexity = 1
        # Remove strings and comments
        cleaned = re.sub(r'"[^"]*"', '', source)
        cleaned = re.sub(r"'[^']*'", '', cleaned)
        cleaned = re.sub(r'/\*[\s\S]*?\*/', '', cleaned)
        cleaned = re.sub(r'//.*', '', cleaned)

        # Count decision points
        decisions = [
            r'\bif\s*\(',
            r'\belse\s+if\b',
            r'\bwhile\s*\(',
            r'\bfor\s*\(',
            r'\bcase\s+',
            r'\bcatch\s*\(',
            r'\b&&\b',
            r'\b\|\|\b',
            r'\?.*:',
            r'\bdefault\s*:',
        ]
        for pattern in decisions:
            complexity += len(re.findall(pattern, cleaned))

        return complexity

    def _compute_rust_cyclomatic(self, source: str) -> int:
        """Compute cyclomatic complexity for Rust source using regex."""
        complexity = 1
        cleaned = re.sub(r'"[^"]*"', '', source)
        cleaned = re.sub(r"'[^']*'", '', cleaned)
        cleaned = re.sub(r'/\*[\s\S]*?\*/', '', cleaned)
        cleaned = re.sub(r'//.*', '', cleaned)

        decisions = [
            r'\bif\b',
            r'\belse\b',
            r'\bwhile\b',
            r'\bfor\b',
            r'\bmatch\b',
            r'\bcatch\b',
            r'\b&&\b',
            r'\b\|\|\b',
            r'\?.*:',
            r'\bwhere\b',
            r'\bguard\b',
        ]
        for pattern in decisions:
            complexity += len(re.findall(pattern, cleaned))

        return complexity

    # ------------------------------------------------------------------ #
    #  Cognitive Complexity
    # ------------------------------------------------------------------ #

    def compute_cognitive(self, source: str, language: Language = Language.PYTHON) -> int:
        """Compute cognitive complexity (SonarQube-style)."""
        if language == Language.PYTHON:
            return self._compute_python_cognitive(source)
        elif language == Language.C:
            return self._compute_c_cognitive(source)
        elif language == Language.RUST:
            return self._compute_rust_cognitive(source)
        return 0

    def _compute_python_cognitive(self, source: str) -> int:
        """Compute cognitive complexity for Python."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return 0

        return self._walk_cognitive(tree)

    def _walk_cognitive(self, node: ast.AST, nesting: int = 0) -> int:
        """Walk the AST and compute cognitive complexity."""
        score = 0

        if isinstance(node, ast.If):
            # Base increment for if
            score += 1 + nesting
            # Walk children
            for child in node.body:
                score += self._walk_cognitive(child, nesting + 1)
            for child in node.orelse:
                if child and isinstance(child, ast.If):
                    # elif - same nesting level
                    score += self._walk_cognitive(child, nesting)
                elif child:
                    # else - increment
                    score += 1 + nesting
                    score += self._walk_cognitive(child, nesting + 1)

        elif isinstance(node, (ast.While, ast.For, ast.AsyncFor)):
            score += 1 + nesting
            for child in node.body:
                score += self._walk_cognitive(child, nesting + 1)
            for child in node.orelse:
                score += self._walk_cognitive(child, nesting)

        elif isinstance(node, ast.ExceptHandler):
            score += 1 + nesting
            for child in node.body:
                score += self._walk_cognitive(child, nesting + 1)

        elif isinstance(node, ast.Try):
            score += 1 + nesting
            for child in node.body:
                score += self._walk_cognitive(child, nesting + 1)
            for handler in node.handlers:
                score += self._walk_cognitive(handler, nesting)
            for child in node.orelse:
                score += self._walk_cognitive(child, nesting)
            for child in node.finalbody:
                score += self._walk_cognitive(child, nesting)

        elif isinstance(node, ast.With):
            for child in node.body:
                score += self._walk_cognitive(child, nesting)
        elif isinstance(node, ast.Assert):
            score += 1 + nesting
        elif isinstance(node, ast.BoolOp):
            # Each boolean operator adds 1
            score += len(node.values) - 1

        elif isinstance(node, ast.FunctionDef):
            for child in node.body:
                score += self._walk_cognitive(child, nesting)

        # Recursively process children for container nodes
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor,
                                  ast.Try, ast.ExceptHandler, ast.With,
                                  ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.Assert, ast.BoolOp)):
                continue  # Already handled above
            score += self._walk_cognitive(child, nesting)

        return score

    def _compute_c_cognitive(self, source: str) -> int:
        """Compute cognitive complexity for C."""
        score = 0
        nesting = 0
        nesting_keywords = [r'\bif\b', r'\bwhile\b', r'\bfor\b', r'\bdo\b']
        cleaned = re.sub(r'"[^"]*"', '', source)
        cleaned = re.sub(r"'[^']*'", '', cleaned)
        cleaned = re.sub(r'/\*[\s\S]*?\*/', '', cleaned)
        cleaned = re.sub(r'//.*', '', cleaned)

        lines = cleaned.split('\n')
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith('#'):
                continue

            if re.search(r'\bif\s*\(', line_stripped):
                score += 1 + nesting
                nesting += 1
            if re.search(r'\belse\b', line_stripped) and not re.search(r'\belse\s+if\b', line_stripped):
                score += 1 + nesting
            if re.search(r'\b(while|for|do)\s*\(', line_stripped):
                score += 1 + nesting
                nesting += 1
            if re.search(r'\bswitch\s*\(', line_stripped):
                score += 1 + nesting
                nesting += 1
            if re.search(r'\bcase\b', line_stripped):
                score += 1 + nesting
            if re.search(r'\bcatch\s*\(', line_stripped):
                score += 1 + nesting
                nesting += 1
            if re.search(r'&&|\|\|', line_stripped):
                score += 1

            # Decrease nesting on closing braces
            nesting -= line_stripped.count('}')
            nesting = max(nesting, 0)

        return score

    def _compute_rust_cognitive(self, source: str) -> int:
        """Compute cognitive complexity for Rust."""
        score = 0
        nesting = 0
        cleaned = re.sub(r'"[^"]*"', '', source)
        cleaned = re.sub(r"'[^']*'", '', cleaned)
        cleaned = re.sub(r'/\*[\s\S]*?\*/', '', cleaned)
        cleaned = re.sub(r'//.*', '', cleaned)

        lines = cleaned.split('\n')
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith('#'):
                continue

            if re.search(r'\bif\b', line_stripped) and not re.search(r'\bif\s+let\b', line_stripped):
                score += 1 + nesting
                nesting += 1
            if re.search(r'\belse\b', line_stripped):
                score += 1 + nesting
            if re.search(r'\b(for|while)\b', line_stripped):
                score += 1 + nesting
                nesting += 1
            if re.search(r'\bmatch\b', line_stripped):
                score += 1 + nesting
                nesting += 1
            if re.search(r'\bcatch\b', line_stripped):
                score += 1 + nesting
                nesting += 1
            if re.search(r'\bif\s+let\b', line_stripped):
                score += 1 + nesting
            if re.search(r'&&|\|\|', line_stripped):
                score += 1

            nesting -= line_stripped.count('}')
            nesting = max(nesting, 0)

        return score

    # ------------------------------------------------------------------ #
    #  Nesting Depth
    # ------------------------------------------------------------------ #

    def compute_nesting_depth(self, source: str, language: Language = Language.PYTHON) -> int:
        """Compute maximum nesting depth of control structures."""
        if language == Language.PYTHON:
            return self._compute_python_nesting(source)
        else:
            return self._compute_generic_nesting(source)

    def _compute_python_nesting(self, source: str) -> int:
        """Compute nesting depth for Python using AST."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return 0
        return self._max_nesting(tree, 0)

    def _max_nesting(self, node: ast.AST, current_depth: int) -> int:
        """Recursively compute max nesting depth."""
        max_depth = current_depth

        nesting_nodes = (
            ast.If, ast.While, ast.For, ast.AsyncFor,
            ast.Try, ast.With, ast.FunctionDef, ast.AsyncFunctionDef,
            ast.ExceptHandler,
        )

        if isinstance(node, nesting_nodes):
            current_depth += 1
            max_depth = max(max_depth, current_depth)

        for child in ast.iter_child_nodes(node):
            child_depth = self._max_nesting(child, current_depth)
            max_depth = max(max_depth, child_depth)

        return max_depth

    def _compute_generic_nesting(self, source: str) -> int:
        """Compute nesting depth for non-Python using brace counting."""
        max_depth = 0
        depth = 0
        in_string = False
        string_char = None

        i = 0
        while i < len(source):
            ch = source[i]

            # Handle string literals
            if ch in ('"', "'") and not in_string:
                in_string = True
                string_char = ch
            elif ch == string_char and in_string:
                if source[i - 1] != '\\':
                    in_string = False
                    string_char = None

            if not in_string:
                if ch == '{':
                    depth += 1
                    max_depth = max(max_depth, depth)
                elif ch == '}':
                    depth = max(0, depth - 1)

            i += 1

        return max_depth

    # ------------------------------------------------------------------ #
    #  Halstead Metrics
    # ------------------------------------------------------------------ #

    def compute_halstead(self, source: str, language: Language = Language.PYTHON) -> Dict[str, float]:
        """Compute Halstead complexity metrics."""
        if language == Language.PYTHON:
            operators, operands = self._tokenize_python(source)
        elif language == Language.C:
            operators, operands = self._tokenize_c(source)
        elif language == Language.RUST:
            operators, operands = self._tokenize_rust(source)
        else:
            operators, operands = {}, {}

        n1 = len(operators)   # unique operators
        n2 = len(operands)    # unique operands
        N1 = sum(operators.values())  # total operators
        N2 = sum(operands.values())   # total operands

        vocabulary = n1 + n2
        length = N1 + N2

        if vocabulary == 0:
            return {
                "vocabulary": 0.0, "length": 0.0, "volume": 0.0,
                "difficulty": 0.0, "effort": 0.0, "bugs": 0.0,
            }

        volume = length * math.log2(vocabulary) if vocabulary > 0 else 0.0
        difficulty = (n1 / 2) * (N2 / n2) if n2 > 0 else 0.0
        effort = difficulty * volume
        bugs = volume / 3000.0

        return {
            "unique_operators": n1,
            "unique_operands": n2,
            "total_operators": N1,
            "total_operands": N2,
            "vocabulary": vocabulary,
            "length": length,
            "volume": volume,
            "difficulty": difficulty,
            "effort": effort,
            "bugs": bugs,
        }

    def _tokenize_python(self, source: str) -> Tuple[Counter, Counter]:
        """Tokenize Python source into operators and operands."""
        operators = Counter()
        operands = Counter()

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return operators, operands

        for node in ast.walk(tree):
            if isinstance(node, ast.Add): operators['+'] += 1
            elif isinstance(node, ast.Sub): operators['-'] += 1
            elif isinstance(node, ast.Mult): operators['*'] += 1
            elif isinstance(node, ast.Div): operators['/'] += 1
            elif isinstance(node, ast.FloorDiv): operators['//'] += 1
            elif isinstance(node, ast.Mod): operators['%'] += 1
            elif isinstance(node, ast.Pow): operators['**'] += 1
            elif isinstance(node, ast.LShift): operators['<<'] += 1
            elif isinstance(node, ast.RShift): operators['>>'] += 1
            elif isinstance(node, ast.BitOr): operators['|'] += 1
            elif isinstance(node, ast.BitXor): operators['^'] += 1
            elif isinstance(node, ast.BitAnd): operators['&'] += 1
            elif isinstance(node, ast.And): operators['and'] += 1
            elif isinstance(node, ast.Or): operators['or'] += 1
            elif isinstance(node, ast.Not): operators['not'] += 1
            elif isinstance(node, ast.Invert): operators['~'] += 1
            elif isinstance(node, ast.UAdd): operators['+ (unary)'] += 1
            elif isinstance(node, ast.USub): operators['- (unary)'] += 1
            elif isinstance(node, ast.Eq): operators['=='] += 1
            elif isinstance(node, ast.NotEq): operators['!='] += 1
            elif isinstance(node, ast.Lt): operators['<'] += 1
            elif isinstance(node, ast.LtE): operators['<='] += 1
            elif isinstance(node, ast.Gt): operators['>'] += 1
            elif isinstance(node, ast.GtE): operators['>='] += 1
            elif isinstance(node, ast.Is): operators['is'] += 1
            elif isinstance(node, ast.IsNot): operators['is not'] += 1
            elif isinstance(node, ast.In): operators['in'] += 1
            elif isinstance(node, ast.NotIn): operators['not in'] += 1
            elif isinstance(node, ast.Assign): operators['='] += 1
            elif isinstance(node, ast.AugAssign):
                op_map = {
                    ast.Add: '+=', ast.Sub: '-=', ast.Mult: '*=',
                    ast.Div: '/=', ast.Mod: '%=', ast.Pow: '**=',
                    ast.LShift: '<<=', ast.RShift: '>>=',
                    ast.BitOr: '|=', ast.BitXor: '^=', ast.BitAnd: '&=',
                    ast.FloorDiv: '//=',
                }
                op_type = type(getattr(node, 'op', None))
                operators[op_map.get(op_type, '?=')] += 1
            elif isinstance(node, ast.Subscript): operators['[]'] += 1
            elif isinstance(node, ast.Call): operators['()'] += 1
            elif isinstance(node, ast.Attribute): operators['.'] += 1
            elif isinstance(node, ast.IfExp): operators['if/else'] += 1
            elif isinstance(node, ast.Starred): operators['*args'] += 1
            elif isinstance(node, ast.Constant):
                val = node.value
                if isinstance(val, (int, float, complex)):
                    operands[repr(val)] += 1
                elif isinstance(val, str):
                    operands[f'"{val[:20]}"'] += 1
                elif isinstance(val, bytes):
                    operands['b"..."'] += 1
                elif val is None:
                    operands['None'] += 1
                elif isinstance(val, bool):
                    operands['True' if val else 'False'] += 1
            elif isinstance(node, ast.Name):
                if node.id not in ('True', 'False', 'None'):
                    operands[node.id] += 1
            elif isinstance(node, ast.List):
                operands['list'] += 1
            elif isinstance(node, ast.Tuple):
                operands['tuple'] += 1
            elif isinstance(node, ast.Dict):
                operands['dict'] += 1
            elif isinstance(node, ast.Set):
                operands['set'] += 1
            elif isinstance(node, ast.Lambda):
                operators['lambda'] += 1
            elif isinstance(node, ast.Return):
                operators['return'] += 1
            elif isinstance(node, ast.If):
                operators['if'] += 1
            elif isinstance(node, ast.For):
                operators['for'] += 1
            elif isinstance(node, ast.While):
                operators['while'] += 1
            elif isinstance(node, ast.Break):
                operators['break'] += 1
            elif isinstance(node, ast.Continue):
                operators['continue'] += 1
            elif isinstance(node, ast.Raise):
                operators['raise'] += 1
            elif isinstance(node, ast.Try):
                operators['try'] += 1
            elif isinstance(node, ast.With):
                operators['with'] += 1
            elif isinstance(node, ast.Import):
                operators['import'] += 1
            elif isinstance(node, ast.Yield):
                operators['yield'] += 1
            elif isinstance(node, ast.Assert):
                operators['assert'] += 1
            elif isinstance(node, ast.Delete):
                operators['del'] += 1
            elif isinstance(node, ast.Pass):
                operators['pass'] += 1

        return operators, operands

    def _tokenize_c(self, source: str) -> Tuple[Counter, Counter]:
        """Tokenize C source into operators and operands."""
        operators = Counter()
        operands = Counter()

        cleaned = re.sub(r'"[^"]*"', ' "STR" ', source)
        cleaned = re.sub(r"'[^']*'", " 'CHAR' ", cleaned)
        cleaned = re.sub(r'/\*[\s\S]*?\*/', '', cleaned)
        cleaned = re.sub(r'//.*', '', cleaned)

        # Operators
        op_patterns = {
            r'\+=': '+=', r'-=': '-=', r'\*=': '*=', r'/=': '/=',
            r'%=': '%=', r'<<=': '<<=', r'>>=': '>>=',
            r'&=': '&=', r'\|=': '|=', r'\^=': '^=',
            r'\+\+': '++', r'--': '--',
            r'==': '==', r'!=': '!=', r'<=': '<=', r'>=': '>=',
            r'<<': '<<', r'>>': '>>',
            r'&&': '&&', r'\|\|': '||',
            r'->': '->',
            r'\+': '+', r'-': '-', r'\*': '*', r'/': '/',
            r'%': '%', r'&': '&', r'\|': '|', r'\^': '^',
            r'~': '~', r'!': '!', r'=': '=',
            r'<': '<', r'>': '>', r'\?': '?', r':': ':',
            r'\;': ';', r'\,': ',',
        }

        for pattern, op_name in op_patterns.items():
            count = len(re.findall(pattern, cleaned))
            if count > 0:
                operators[op_name] = count

        # Operands - identifiers and literals
        identifiers = re.findall(r'\b[a-zA-Z_]\w*\b', cleaned)
        for ident in identifiers:
            if ident not in ('if', 'else', 'while', 'for', 'do', 'switch',
                             'case', 'break', 'continue', 'return', 'goto',
                             'sizeof', 'typedef', 'struct', 'union', 'enum',
                             'const', 'volatile', 'static', 'extern', 'inline',
                             'register', 'signed', 'unsigned', 'short', 'long',
                             'int', 'char', 'float', 'double', 'void',
                             'auto', 'restrict', '_Bool', '_Complex',
                             'int8_t', 'int16_t', 'int32_t', 'int64_t',
                             'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t',
                             'size_t', 'ssize_t', 'ptrdiff_t', 'intptr_t',
                             'NULL', 'true', 'false', 'TRUE', 'FALSE',):
                operands[ident] += 1

        # Number literals
        numbers = re.findall(r'\b0[xX][0-9a-fA-F]+|\b\d+\.?\d*[fFlL]?\b', cleaned)
        for num in numbers:
            operands[num] += 1

        return operators, operands

    def _tokenize_rust(self, source: str) -> Tuple[Counter, Counter]:
        """Tokenize Rust source into operators and operands."""
        operators = Counter()
        operands = Counter()

        cleaned = re.sub(r'"[^"]*"', ' "STR" ', source)
        cleaned = re.sub(r"'[^']*'", " 'CHAR' ", cleaned)
        cleaned = re.sub(r'/\*[\s\S]*?\*/', '', cleaned)
        cleaned = re.sub(r'//.*', '', cleaned)

        # Rust operators
        op_patterns = {
            r'\+=': '+=', r'-=': '-=', r'\*=': '*=', r'/=': '/=',
            r'%=': '%=', r'&=': '&=', r'\|=': '|=', r'\^=': '^=',
            r'<<=': '<<=', r'>>=': '>>=',
            r'==': '==', r'!=': '!=', r'<=': '<=', r'>=': '>=',
            r'<<': '<<', r'>>': '>>',
            r'&&': '&&', r'\|\|': '||',
            r'->': '->', r'=>': '=>',
            r'::': '::',
            r'\.\.\.': '...', r'\.\.': '..',
            r'\+': '+', r'-': '-', r'\*': '*', r'/': '/',
            r'%': '%', r'&': '&', r'\|': '|', r'\^': '^',
            r'!': '!', r'=': '=', r'<': '<', r'>': '>',
            r'\?': '?', r':': ':',
            r'\;': ';', r'\,': ',',
            r'@': '@',
        }

        for pattern, op_name in op_patterns.items():
            count = len(re.findall(pattern, cleaned))
            if count > 0:
                operators[op_name] = count

        # Rust keywords
        keywords = {
            'fn', 'let', 'mut', 'const', 'static', 'if', 'else',
            'while', 'for', 'loop', 'match', 'return', 'break',
            'continue', 'struct', 'enum', 'trait', 'impl', 'pub',
            'use', 'mod', 'crate', 'self', 'super', 'where',
            'as', 'in', 'ref', 'move', 'async', 'await', 'unsafe',
            'dyn', 'type', 'union', 'unsized', 'extern',
        }

        identifiers = re.findall(r'\b[a-zA-Z_]\w*\b', cleaned)
        for ident in identifiers:
            if ident not in keywords:
                operands[ident] += 1

        # Literals
        numbers = re.findall(r'\b\d+[ui]\d+\b|\b0[xX][0-9a-fA-F]+\b|\b\d+\.\d+\b', cleaned)
        for num in numbers:
            operands[num] += 1

        return operators, operands

    # ------------------------------------------------------------------ #
    #  Maintainability Index
    # ------------------------------------------------------------------ #

    def compute_maintainability(self, metrics: ComplexityMetrics) -> float:
        """Compute the maintainability index (MI)."""
        volume = metrics.halstead_volume
        cc = metrics.cyclomatic_complexity
        loc = metrics.lines_of_code

        if volume <= 0:
            return 100.0

        # Standard MI formula
        mi = max(0.0, 171 - 5.2 * math.log(volume) - 0.23 * cc - 16.2 * math.log(loc))

        # Scale to 0-100
        return min(100.0, mi * 100 / 171)

    # ------------------------------------------------------------------ #
    #  Test Priority Scoring
    # ------------------------------------------------------------------ #

    def compute_test_priority(self, metrics: ComplexityMetrics) -> float:
        """Compute a test priority score (0-100) based on complexity."""
        score = 0.0

        # Cyclomatic complexity contribution (0-40)
        cc = metrics.cyclomatic_complexity
        if cc <= 1:
            score += 5
        elif cc <= 5:
            score += 15
        elif cc <= 10:
            score += 25
        elif cc <= 20:
            score += 35
        else:
            score += 40

        # Cognitive complexity contribution (0-25)
        cog = metrics.cognitive_complexity
        if cog <= 2:
            score += 3
        elif cog <= 10:
            score += 10
        elif cog <= 20:
            score += 15
        elif cog <= 40:
            score += 20
        else:
            score += 25

        # Parameter count contribution (0-15)
        params = metrics.parameter_count
        if params == 0:
            score += 2
        elif params <= 3:
            score += 5
        elif params <= 5:
            score += 8
        elif params <= 8:
            score += 12
        else:
            score += 15

        # Nesting depth contribution (0-10)
        depth = metrics.nesting_depth
        if depth <= 1:
            score += 1
        elif depth <= 3:
            score += 4
        elif depth <= 5:
            score += 7
        else:
            score += 10

        # Return count contribution (0-10)
        returns = metrics.return_count
        if returns <= 1:
            score += 1
        elif returns <= 3:
            score += 3
        elif returns <= 5:
            score += 5
        elif returns <= 10:
            score += 8
        else:
            score += 10

        return min(100.0, score)

    # ------------------------------------------------------------------ #
    #  Full Analysis
    # ------------------------------------------------------------------ #

    def analyze_function(self, func: FunctionSignature, source: Optional[str] = None) -> ComplexityMetrics:
        """Compute full complexity metrics for a function signature."""
        metrics = ComplexityMetrics()

        # Basic metrics from signature
        metrics.parameter_count = func.parameter_count
        metrics.lines_of_code = func.body_lines

        if source:
            # Cyclomatic complexity
            metrics.cyclomatic_complexity = self.compute_cyclomatic(source, func.language)

            # Cognitive complexity
            metrics.cognitive_complexity = self.compute_cognitive(source, func.language)

            # Nesting depth
            metrics.nesting_depth = self.compute_nesting_depth(source, func.language)

            # Halstead metrics
            halstead = self.compute_halstead(source, func.language)
            metrics.halstead_unique_operators = halstead["unique_operators"]
            metrics.halstead_unique_operands = halstead["unique_operands"]
            metrics.halstead_total_operators = halstead["total_operators"]
            metrics.halstead_total_operands = halstead["total_operands"]
            metrics.halstead_vocabulary = halstead["vocabulary"]
            metrics.halstead_length = halstead["length"]
            metrics.halstead_volume = halstead["volume"]
            metrics.halstead_difficulty = halstead["difficulty"]
            metrics.halstead_effort = halstead["effort"]
            metrics.halstead_bugs = halstead["bugs"]

            # Branch count (approximate from cyclomatic)
            metrics.branch_count = max(0, metrics.cyclomatic_complexity - 1)

            # Count loops
            metrics.loop_count = len(re.findall(r'\b(for|while)\b', source))

            # Count returns
            metrics.return_count = len(re.findall(r'\breturn\b', source))

            # Exception handlers
            metrics.exception_handler_count = len(re.findall(r'\b(try|except|catch)\b', source))

            # Boolean operators
            metrics.boolean_operator_count = len(re.findall(r'\b(and|or)\b', source)) + \
                len(re.findall(r'&&|\|\|', source))

        # Maintainability index
        metrics.maintainability_index = self.compute_maintainability(metrics)

        # Test priority
        metrics.test_priority = self.compute_test_priority(metrics)

        return metrics

    def analyze_file(self, filepath: str, source: str, functions: List[FunctionSignature]) -> FileComplexitySummary:
        """Analyze complexity for all functions in a file."""
        summary = FileComplexitySummary(filepath=filepath)
        total_cyclomatic = 0
        total_cognitive = 0
        max_complexity = 0.0
        most_complex = None

        for func in functions:
            # Extract function source from file
            func_source = self._extract_function_source(source, func)
            metrics = self.analyze_function(func, func_source)
            summary.function_metrics[func.name] = metrics

            total_cyclomatic += metrics.cyclomatic_complexity
            total_cognitive += metrics.cognitive_complexity

            if metrics.test_priority > max_complexity:
                max_complexity = metrics.test_priority
                most_complex = func.name

        summary.total_cyclomatic = total_cyclomatic
        summary.total_cognitive = total_cognitive
        summary.function_count = len(functions)
        summary.average_complexity = total_cyclomatic / max(1, len(functions))
        summary.max_complexity = max_complexity
        summary.most_complex_function = most_complex
        summary.total_lines = len(source.splitlines())

        return summary

    def _extract_function_source(self, full_source: str, func: FunctionSignature) -> Optional[str]:
        """Extract the source code of a specific function from the full source."""
        if func.body_lines <= 0 or func.line_number <= 0:
            return None

        lines = full_source.splitlines()
        if func.line_number - 1 < len(lines):
            end_line = min(func.line_number + func.body_lines, len(lines))
            return '\n'.join(lines[func.line_number - 1:end_line])
        return None

    def complexity_report(self, file_summaries: List[FileComplexitySummary]) -> Dict[str, Any]:
        """Generate a comprehensive complexity report."""
        report = {
            "files": [],
            "summary": {
                "total_files": len(file_summaries),
                "total_functions": 0,
                "total_cyclomatic": 0,
                "total_cognitive": 0,
                "average_cyclomatic": 0.0,
                "average_cognitive": 0.0,
                "average_maintainability": 0.0,
                "total_estimated_bugs": 0.0,
                "high_priority_count": 0,
                "complexity_distribution": {
                    "trivial": 0, "low": 0, "moderate": 0,
                    "complex": 0, "very_complex": 0, "untestable": 0,
                },
            },
        }

        total_functions = 0
        total_cyclomatic = 0
        total_cognitive = 0
        total_mi = 0.0
        total_bugs = 0.0
        high_priority = 0
        dist = {"trivial": 0, "low": 0, "moderate": 0,
                "complex": 0, "very_complex": 0, "untestable": 0}

        for fs in file_summaries:
            file_entry = {
                "filepath": fs.filepath,
                "function_count": fs.function_count,
                "total_cyclomatic": fs.total_cyclomatic,
                "total_cognitive": fs.total_cognitive,
                "average_complexity": fs.average_complexity,
                "max_complexity": fs.max_complexity,
                "most_complex_function": fs.most_complex_function,
                "functions": {},
            }

            for func_name, metrics in fs.function_metrics.items():
                func_entry = {
                    "cyclomatic": metrics.cyclomatic_complexity,
                    "cognitive": metrics.cognitive_complexity,
                    "nesting_depth": metrics.nesting_depth,
                    "parameters": metrics.parameter_count,
                    "lines": metrics.lines_of_code,
                    "maintainability": round(metrics.maintainability_index, 1),
                    "test_priority": round(metrics.test_priority, 1),
                    "level": metrics.level.name,
                    "halstead_volume": round(metrics.halstead_volume, 1),
                    "halstead_difficulty": round(metrics.halstead_difficulty, 1),
                    "estimated_bugs": round(metrics.halstead_bugs, 3),
                }
                file_entry["functions"][func_name] = func_entry

                total_functions += 1
                total_cyclomatic += metrics.cyclomatic_complexity
                total_cognitive += metrics.cognitive_complexity
                total_mi += metrics.maintainability_index
                total_bugs += metrics.halstead_bugs

                if metrics.test_priority >= 70:
                    high_priority += 1

                level_name = metrics.level.name.lower()
                if level_name in dist:
                    dist[level_name] += 1

            report["files"].append(file_entry)

        report["summary"]["total_functions"] = total_functions
        report["summary"]["total_cyclomatic"] = total_cyclomatic
        report["summary"]["total_cognitive"] = total_cognitive
        report["summary"]["average_cyclomatic"] = round(total_cyclomatic / max(1, total_functions), 2)
        report["summary"]["average_cognitive"] = round(total_cognitive / max(1, total_functions), 2)
        report["summary"]["average_maintainability"] = round(total_mi / max(1, total_functions), 1)
        report["summary"]["total_estimated_bugs"] = round(total_bugs, 2)
        report["summary"]["high_priority_count"] = high_priority
        report["summary"]["complexity_distribution"] = dist

        return report