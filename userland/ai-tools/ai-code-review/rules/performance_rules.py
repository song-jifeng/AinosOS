"""
Performance Rules Module for AI Code Review.

Analyzes code for performance issues including O(n^2) algorithms, unnecessary allocations,
inefficient data structures, blocking calls in async code, and more.
"""

import ast
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PerfIssue:
    """Represents a single performance issue detected by a rule."""
    rule_id: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    message: str
    file_path: str
    line_number: int
    column: int = 0
    end_line: int = 0
    end_column: int = 0
    snippet: str = ""
    remediation: str = ""
    complexity: str = ""
    estimated_impact: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PerfRuleResult:
    """Result from a single performance rule check."""
    rule_id: str
    rule_name: str
    description: str
    issues: List[PerfIssue] = field(default_factory=list)
    duration_ms: float = 0.0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Base rule class
# ---------------------------------------------------------------------------

class BasePerfRule(ABC):
    """Abstract base for all performance rules."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._rule_id: str = ""
        self._name: str = ""
        self._description: str = ""
        self._severity: str = "MEDIUM"
        self._languages: List[str] = field(default_factory=lambda: ["python"])

    @property
    @abstractmethod
    def rule_id(self) -> str:
        """Unique identifier for the rule."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Description of what the rule detects."""

    @property
    def severity(self) -> str:
        return self._severity

    @property
    def languages(self) -> List[str]:
        return self._languages

    @abstractmethod
    def check(self, tree: ast.AST, file_path: str, source_code: str) -> PerfRuleResult:
        """Run the rule check on the given AST."""


# ---------------------------------------------------------------------------
# Algorithmic complexity rules
# ---------------------------------------------------------------------------

class NestedLoopDetectionRule(BasePerfRule):
    """Detects O(n^2) or worse algorithmic complexity from nested loops."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "PERF-LOOP-001"
        self._name = "Nested Loop Detection"
        self._description = "Detects nested loops that may indicate O(n^2) or worse algorithmic complexity"
        self._severity = "HIGH"
        self._languages = ["python"]

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> PerfRuleResult:
        result = PerfRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._check_function_loops(node, result, file_path, lines)

        return result

    def _check_function_loops(self, func_node: ast.FunctionDef, result: PerfRuleResult, file_path: str, lines: List[str]) -> None:
        loops = []
        for node in ast.walk(func_node):
            if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                # Check depth of nesting
                depth = self._get_loop_depth(node, func_node)
                if depth >= 2:
                    loops.append((node, depth))

        # Group by depth and report
        for loop_node, depth in loops:
            if depth == 2:
                severity = "HIGH"
                complexity = "O(n^2)"
            elif depth == 3:
                severity = "CRITICAL"
                complexity = "O(n^3)"
            else:
                severity = "CRITICAL"
                complexity = f"O(n^{depth})"

            line_no = loop_node.lineno

            # Check if the inner loop iterates over the same data structure
            iter_var = self._get_iter_var(loop_node)
            parent_iter_var = self._get_parent_iter_var(loop_node, func_node)

            same_data = False
            if iter_var and parent_iter_var and iter_var == parent_iter_var:
                same_data = True
                severity = "CRITICAL"
                complexity = "O(n^2) - same data structure"

            msg = f"Nested loop (depth={depth}) with {complexity} complexity at line {line_no}"
            if same_data:
                msg = f"Nested loop iterating over same data structure '{iter_var}' at line {line_no} ({complexity})"

            issue = PerfIssue(
                rule_id=self.rule_id,
                severity=severity,
                message=msg,
                file_path=file_path,
                line_number=line_no,
                complexity=complexity,
                estimated_impact="HIGH" if depth >= 2 else "MEDIUM",
                snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                remediation=f"Consider using a hash map (dict/set) to reduce {complexity} to O(n). Use indexing or lookups instead of nested iteration.",
            )
            result.issues.append(issue)

    def _get_loop_depth(self, loop_node: ast.AST, func_node: ast.AST) -> int:
        depth = 0
        current = loop_node
        while current is not func_node and hasattr(current, 'parent'):
            if isinstance(current, (ast.For, ast.AsyncFor, ast.While)):
                depth += 1
            current = getattr(current, 'parent', func_node)
        # Walk the AST to find nesting
        # Since we can't rely on parent pointers, let's do a deeper analysis
        max_depth = 1
        for child in ast.walk(loop_node):
            if child is loop_node:
                continue
            if isinstance(child, (ast.For, ast.AsyncFor, ast.While)):
                # Check if child is nested within loop_node
                if self._is_nested_within(child, loop_node):
                    child_depth = 1 + self._get_loop_depth(child, func_node)
                    max_depth = max(max_depth, child_depth)
        return max_depth

    def _is_nested_within(self, inner: ast.AST, outer: ast.AST) -> bool:
        """Check if inner node is lexically nested within outer node."""
        if not hasattr(inner, 'lineno') or not hasattr(outer, 'lineno'):
            return False
        if not hasattr(inner, 'end_lineno') or not hasattr(outer, 'end_lineno'):
            return inner.lineno > outer.lineno
        return outer.lineno <= inner.lineno <= (inner.end_lineno or inner.lineno) <= (outer.end_lineno or outer.lineno)

    def _get_iter_var(self, loop_node: ast.AST) -> Optional[str]:
        if isinstance(loop_node, (ast.For, ast.AsyncFor)):
            if isinstance(loop_node.target, ast.Name):
                return loop_node.target.id
            if isinstance(loop_node.target, ast.Tuple) or isinstance(loop_node.target, ast.List):
                return "tuple_destructure"
        return None

    def _get_parent_iter_var(self, loop_node: ast.AST, func_node: ast.AST) -> Optional[str]:
        for node in ast.walk(func_node):
            if isinstance(node, (ast.For, ast.AsyncFor)) and node is not loop_node:
                if self._is_nested_within(loop_node, node):
                    if isinstance(node.target, ast.Name):
                        return node.target.id
        return None

    def _contains_loop(self, node: ast.AST) -> bool:
        for child in ast.walk(node):
            if isinstance(child, (ast.For, ast.AsyncFor, ast.While)):
                return True
        return False


class ListComprehensionOverGenerationRule(BasePerfRule):
    """Detects list comprehensions that could be generators."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "PERF-LIST-001"
        self._name = "List Comprehension Over Generator"
        self._description = "Detects list comprehensions where a generator expression would be more memory-efficient"
        self._severity = "MEDIUM"
        self._languages = ["python"]

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> PerfRuleResult:
        result = PerfRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        FUNCTIONS_THAT_ACCEPT_GENERATORS = {
            'sum', 'min', 'max', 'any', 'all', 'sorted', 'list', 'set', 'dict',
            'tuple', 'filter', 'map', 'reduce', 'functools.reduce',
            'join', 'str.join',
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.ListComp):
                # Check if the list comprehension is passed to a function that accepts generators
                parent = self._find_parent_call(node, tree)
                if parent and isinstance(parent.func, (ast.Name, ast.Attribute)):
                    func_name = parent.func.id if isinstance(parent.func, ast.Name) else parent.func.attr
                    if func_name in FUNCTIONS_THAT_ACCEPT_GENERATORS:
                        line_no = node.lineno
                        issue = PerfIssue(
                            rule_id=self.rule_id,
                            severity="LOW",
                            message=f"List comprehension passed to {func_name}() at line {line_no} - use generator expression instead",
                            file_path=file_path,
                            line_number=line_no,
                            complexity="O(n) memory",
                            estimated_impact="LOW",
                            snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                            remediation=f"Replace [...] with (...) to use a generator expression: {func_name}(x for x in ...)",
                        )
                        result.issues.append(issue)

                # Check if the list comprehension is only iterated once
                if self._is_iterated_once(node, tree):
                    line_no = node.lineno
                    issue = PerfIssue(
                        rule_id=self.rule_id,
                        severity="MEDIUM",
                        message=f"List comprehension at line {line_no} is only iterated once - use generator expression",
                        file_path=file_path,
                        line_number=line_no,
                        complexity="O(n) unnecessary memory allocation",
                        estimated_impact="MEDIUM",
                        snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                        remediation="Replace list comprehension with a generator expression to avoid allocating the entire list in memory",
                    )
                    result.issues.append(issue)

        return result

    def _find_parent_call(self, node: ast.AST, tree: ast.AST) -> Optional[ast.Call]:
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                for arg in n.args:
                    if arg is node:
                        return n
                for kw in n.keywords:
                    if kw.value is node:
                        return n
        return None

    def _is_iterated_once(self, node: ast.ListComp, tree: ast.AST) -> bool:
        for n in ast.walk(tree):
            if isinstance(n, (ast.For, ast.AsyncFor)):
                if isinstance(n.iter, ast.ListComp) and n.iter is node:
                    return True
                if isinstance(n.iter, ast.Call) and node in ast.walk(n.iter):
                    return True
        return False


class UnnecessaryListAllocationRule(BasePerfRule):
    """Detects patterns where a list is allocated unnecessarily."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "PERF-ALLOC-001"
        self._name = "Unnecessary List Allocation"
        self._description = "Detects unnecessary list allocations in loops and comprehensions"
        self._severity = "MEDIUM"
        self._languages = ["python"]

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> PerfRuleResult:
        result = PerfRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            # Pattern: list() around a list comprehension
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'list':
                if node.args and isinstance(node.args[0], ast.ListComp):
                    line_no = node.lineno
                    issue = PerfIssue(
                        rule_id=self.rule_id,
                        severity="MEDIUM",
                        message=f"Unnecessary list() call around list comprehension at line {line_no}",
                        file_path=file_path,
                        line_number=line_no,
                        complexity="O(n) unnecessary allocation",
                        estimated_impact="MEDIUM",
                        snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                        remediation="Remove the outer list() call - the list comprehension already creates a list",
                    )
                    result.issues.append(issue)

            # Pattern: [x for x in ...] when only iterating once
            if isinstance(node, ast.ListComp):
                if self._is_used_in_for_loop(node, tree):
                    line_no = node.lineno
                    issue = PerfIssue(
                        rule_id=self.rule_id,
                        severity="LOW",
                        message=f"List comprehension allocated at line {line_no} but only iterated once",
                        file_path=file_path,
                        line_number=line_no,
                        complexity="O(n) memory",
                        estimated_impact="LOW",
                        snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                        remediation="Use a generator expression instead of a list comprehension",
                    )
                    result.issues.append(issue)

            # Pattern: building a list with .append() in a loop when a comprehension would work
            if isinstance(node, ast.For):
                self._check_append_in_loop(node, result, file_path, lines, tree)

            # Pattern: str.split() then index access instead of partition
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'split':
                self._check_split_then_index(node, result, file_path, lines, tree)

            # Pattern: list(dict.keys()) - extra allocation
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'list':
                if node.args and isinstance(node.args[0], ast.Call) and isinstance(node.args[0].func, ast.Attribute) and node.args[0].func.attr == 'keys':
                    line_no = node.lineno
                    issue = PerfIssue(
                        rule_id=self.rule_id,
                        severity="LOW",
                        message=f"Unnecessary list() allocation from dict.keys() at line {line_no}",
                        file_path=file_path,
                        line_number=line_no,
                        complexity="O(n) memory",
                        estimated_impact="LOW",
                        snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                        remediation="Remove list() - iterating over a dict directly yields its keys",
                    )
                    result.issues.append(issue)

        return result

    def _is_used_in_for_loop(self, comp: ast.ListComp, tree: ast.AST) -> bool:
        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.AsyncFor)) and node.iter is comp:
                return True
            if isinstance(node, ast.Call):
                for arg in node.args:
                    if arg is comp:
                        return True
        return False

    def _check_append_in_loop(self, for_node: ast.For, result: PerfRuleResult, file_path: str, lines: List[str], tree: ast.AST) -> None:
        """Check for loop building a list with .append() that could be a comprehension."""
        appends = []
        for stmt in for_node.body:
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                call = stmt.value
                if isinstance(call.func, ast.Attribute) and call.func.attr == 'append':
                    if isinstance(call.func.value, ast.Name):
                        appends.append(call.func.value.id)

        if appends:
            # Check if the list was initialized empty before the loop
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id in appends:
                            if isinstance(node.value, ast.List) and len(node.value.elts) == 0:
                                # Check if the for loop is on an iterable that could be a comprehension
                                iter_src = ast.unparse(for_node.iter) if hasattr(ast, 'unparse') else ""
                                if iter_src:
                                    line_no = for_node.lineno
                                    issue = PerfIssue(
                                        rule_id=self.rule_id,
                                        severity="MEDIUM",
                                        message=f"List built with .append() in for loop at line {line_no} - use list comprehension instead",
                                        file_path=file_path,
                                        line_number=line_no,
                                        complexity="O(n) with function call overhead",
                                        estimated_impact="MEDIUM",
                                        snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                                        remediation=f"Replace loop with list comprehension: [expression for item in {iter_src}]",
                                    )
                                    result.issues.append(issue)
                                    return

    def _check_split_then_index(self, node: ast.Call, result: PerfRuleResult, file_path: str, lines: List[str], tree: ast.AST) -> None:
        """Check for 'x.split(...)[0]' pattern that could use partition()."""
        line_no = node.lineno
        parent = self._find_parent_subscript(node, tree)
        if parent:
            issue = PerfIssue(
                rule_id=self.rule_id,
                severity="LOW",
                message=f"str.split() with immediate index access at line {line_no} - use str.partition() instead",
                file_path=file_path,
                line_number=line_no,
                complexity="O(n) allocation",
                estimated_impact="LOW",
                snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                remediation="Use str.partition(sep) which returns a tuple without allocating a list",
            )
            result.issues.append(issue)

    def _find_parent_subscript(self, node: ast.AST, tree: ast.AST) -> Optional[ast.Subscript]:
        for n in ast.walk(tree):
            if isinstance(n, ast.Subscript) and n.value is node:
                return n
        return None


class RepeatedComputationInLoopRule(BasePerfRule):
    """Detects computations that are repeated inside loops but could be hoisted."""

    INVARIANT_FUNCTIONS = {'len', 'range', 'enumerate', 'isinstance', 'type', 'hasattr'}

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "PERF-HOIST-001"
        self._name = "Loop Invariant Computation"
        self._description = "Detects computations inside loops that don't change between iterations (loop-invariant code)"
        self._severity = "MEDIUM"
        self._languages = ["python"]

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> PerfRuleResult:
        result = PerfRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                self._detect_invariant_calls(node, result, file_path, lines)

        return result

    def _detect_invariant_calls(self, loop_node: ast.AST, result: PerfRuleResult, file_path: str, lines: List[str]) -> None:
        """Detect function calls inside the loop that don't depend on the loop variable."""
        # Get loop variable name
        loop_var = None
        if isinstance(loop_node, (ast.For, ast.AsyncFor)):
            if isinstance(loop_node.target, ast.Name):
                loop_var = loop_node.target.id
            elif isinstance(loop_node.target, (ast.Tuple, ast.List)):
                loop_var = "tuple_destructure"

        # Find all call expressions in the loop body
        for node in ast.walk(loop_node):
            if isinstance(node, ast.Call) and node is not loop_node.iter:
                # Check if it's a len() call that could be hoisted
                if isinstance(node.func, ast.Name) and node.func.id == 'len':
                    if isinstance(node.args[0], ast.Name) if node.args else False:
                        arg_name = node.args[0].id
                        # Check if the argument is not the loop variable
                        if loop_var and arg_name != loop_var:
                            line_no = node.lineno
                            issue = PerfIssue(
                                rule_id=self.rule_id,
                                severity="LOW",
                                message=f"len({arg_name}) called inside loop at line {line_no} - hoist to loop invariant",
                                file_path=file_path,
                                line_number=line_no,
                                complexity="O(1) per iteration",
                                estimated_impact="LOW",
                                snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                                remediation=f"Compute len({arg_name}) once before the loop and store in a local variable",
                            )
                            result.issues.append(issue)

                # Check for repeated attribute access
                if isinstance(node.func, ast.Attribute):
                    attr_name = node.func.attr
                    if attr_name in ('keys', 'values', 'items') and isinstance(node.func.value, ast.Name):
                        obj_name = node.func.value.id
                        if loop_var and obj_name != loop_var:
                            line_no = node.lineno
                            issue = PerfIssue(
                                rule_id=self.rule_id,
                                severity="LOW",
                                message=f"{obj_name}.{attr_name}() called inside loop at line {line_no} - consider hoisting",
                                file_path=file_path,
                                line_number=line_no,
                                complexity="O(n) per iteration",
                                estimated_impact="LOW",
                                snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                                remediation=f"Compute {obj_name}.{attr_name}() once before the loop",
                            )
                            result.issues.append(issue)


class StringConcatenationInLoopRule(BasePerfRule):
    """Detects string concatenation in loops, which is O(n^2)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "PERF-STR-001"
        self._name = "String Concatenation in Loop"
        self._description = "Detects string concatenation inside loops, which has O(n^2) complexity"
        self._severity = "HIGH"
        self._languages = ["python"]

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> PerfRuleResult:
        result = PerfRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                self._check_string_concat_in_loop(node, result, file_path, lines)

        return result

    def _check_string_concat_in_loop(self, loop_node: ast.AST, result: PerfRuleResult, file_path: str, lines: List[str]) -> None:
        """Check for string concatenation (+= or +) inside a loop body."""
        for node in ast.walk(loop_node):
            # Check for += augmented assignment on strings
            if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
                if isinstance(node.target, ast.Name):
                    line_no = node.lineno
                    issue = PerfIssue(
                        rule_id=self.rule_id,
                        severity="HIGH",
                        message=f"String concatenation (+=) inside loop at line {line_no} - O(n^2) complexity",
                        file_path=file_path,
                        line_number=line_no,
                        complexity="O(n^2)",
                        estimated_impact="HIGH",
                        snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                        remediation="Use a list to collect string parts and ''.join() them after the loop",
                    )
                    result.issues.append(issue)
                    return

            # Check for s = s + x pattern
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name) and isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Add):
                    if isinstance(node.value.left, ast.Name) and node.value.left.id == target.id:
                        line_no = node.lineno
                        issue = PerfIssue(
                            rule_id=self.rule_id,
                            severity="HIGH",
                            message=f"String concatenation (s = s + x) inside loop at line {line_no} - O(n^2) complexity",
                            file_path=file_path,
                            line_number=line_no,
                            complexity="O(n^2)",
                            estimated_impact="HIGH",
                            snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                            remediation="Use a list to collect string parts and ''.join() them after the loop",
                        )
                        result.issues.append(issue)
                        return


# ---------------------------------------------------------------------------
# Data structure rules
# ---------------------------------------------------------------------------

class InefficientDataStructureRule(BasePerfRule):
    """Detects inefficient data structure usage."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "PERF-DS-001"
        self._name = "Inefficient Data Structure Usage"
        self._description = "Detects inefficient data structure choices like list for membership testing"
        self._severity = "MEDIUM"
        self._languages = ["python"]

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> PerfRuleResult:
        result = PerfRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        # Track list variables to detect 'in' checks on lists
        list_vars = self._find_list_variables(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for op, comparator in zip(node.ops, node.comparators):
                    if isinstance(op, ast.In):
                        if isinstance(comparator, ast.Name) and comparator.id in list_vars:
                            line_no = node.lineno
                            list_name = comparator.id
                            # Check if the list is large (heuristic: assigned a literal with many elements)
                            size_hint = self._get_list_size_hint(list_name, tree)
                            if size_hint is None or size_hint > 5:
                                issue = PerfIssue(
                                    rule_id=self.rule_id,
                                    severity="MEDIUM",
                                    message=f"Membership test on list '{list_name}' at line {line_no} - O(n) complexity",
                                    file_path=file_path,
                                    line_number=line_no,
                                    complexity="O(n)",
                                    estimated_impact="MEDIUM",
                                    snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                                    remediation=f"Use a set for '{list_name}' if order doesn't matter and items are hashable: {list_name} = set({list_name})",
                                )
                                result.issues.append(issue)

            # Check for dict.keys() in 'in' comparison
            if isinstance(node, ast.Compare):
                for op, comparator in zip(node.ops, node.comparators):
                    if isinstance(op, ast.In):
                        if isinstance(comparator, ast.Call) and isinstance(comparator.func, ast.Attribute) and comparator.func.attr == 'keys':
                            line_no = node.lineno
                            issue = PerfIssue(
                                rule_id=self.rule_id,
                                severity="LOW",
                                message=f"Unnecessary .keys() call in membership test at line {line_no}",
                                file_path=file_path,
                                line_number=line_no,
                                complexity="O(1) vs O(n) with list(keys())",
                                estimated_impact="LOW",
                                snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                                remediation="Remove .keys() - 'x in dict' is equivalent to 'x in dict.keys()' and more efficient",
                            )
                            result.issues.append(issue)

            # Check for list() constructor on set/dict iteration
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'list':
                if node.args and isinstance(node.args[0], ast.Call) and isinstance(node.args[0].func, ast.Attribute):
                    attr = node.args[0].func.attr
                    if attr in ('keys', 'values'):
                        line_no = node.lineno
                        issue = PerfIssue(
                            rule_id=self.rule_id,
                            severity="LOW",
                            message=f"Unnecessary list() wrapping at line {line_no}",
                            file_path=file_path,
                            line_number=line_no,
                            complexity="O(n) memory",
                            estimated_impact="LOW",
                            snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                            remediation="Remove list() - dict iteration views can be used directly",
                        )
                        result.issues.append(issue)

        return result

    def _find_list_variables(self, tree: ast.AST) -> Set[str]:
        """Find variables that are assigned list literals or list() calls."""
        list_vars = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    if isinstance(node.value, ast.List):
                        list_vars.add(target.id)
                    elif isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == 'list':
                        list_vars.add(target.id)
                    elif isinstance(node.value, ast.ListComp):
                        list_vars.add(target.id)
        return list_vars

    def _get_list_size_hint(self, var_name: str, tree: ast.AST) -> Optional[int]:
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name) and target.id == var_name:
                    if isinstance(node.value, ast.List):
                        return len(node.value.elts)
        return None


class DefaultDictVsSetDefaultRule(BasePerfRule):
    """Detects patterns where defaultdict or setdefault could be more efficient."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "PERF-DICT-001"
        self._name = "Dictionary Default Pattern"
        self._description = "Detects patterns where dict.setdefault() or collections.defaultdict would be more efficient"
        self._severity = "MEDIUM"
        self._languages = ["python"]

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> PerfRuleResult:
        result = PerfRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        # Pattern: if key not in dict: dict[key] = [] followed by dict[key].append(...)
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                self._check_if_not_in_dict(node, result, file_path, lines)

        return result

    def _check_if_not_in_dict(self, if_node: ast.If, result: PerfRuleResult, file_path: str, lines: List[str]) -> None:
        """Check for 'if key not in dict: dict[key] = default' pattern."""
        # Check condition: 'x not in dict' or 'x not in dict.keys()'
        if not isinstance(if_node.test, ast.Compare):
            return

        has_not_in = any(isinstance(op, ast.NotIn) for op in if_node.ops)
        if not has_not_in:
            return

        # Find the 'not in' comparison
        for op, comparator in zip(if_node.ops, if_node.comparators):
            if isinstance(op, ast.NotIn) and isinstance(comparator, ast.Name):
                dict_name = comparator.id

                # Check if body does dict[key] = value
                for stmt in if_node.body:
                    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                        target = stmt.targets[0]
                        if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id == dict_name:
                            if isinstance(if_node.test.left, ast.Name):
                                key_name = if_node.test.left.id
                                line_no = if_node.lineno
                                issue = PerfIssue(
                                    rule_id=self.rule_id,
                                    severity="MEDIUM",
                                    message=f"Dict membership check before assignment at line {line_no} - use setdefault() or defaultdict",
                                    file_path=file_path,
                                    line_number=line_no,
                                    complexity="O(1) double lookup",
                                    estimated_impact="MEDIUM",
                                    snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                                    remediation=f"Use {dict_name}.setdefault({key_name}, default) or collections.defaultdict",
                                )
                                result.issues.append(issue)
                                return

        # Simpler: look for if-else pattern with 'in' checks
        test_str = ast.unparse(if_node.test) if hasattr(ast, 'unparse') else ""
        if re.search(r'not in\s+\w+', test_str):
            for stmt in if_node.body:
                if isinstance(stmt, ast.Assign):
                    target = stmt.targets[0] if stmt.targets else None
                    if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                        dict_name = target.value.id
                        line_no = if_node.lineno
                        issue = PerfIssue(
                            rule_id=self.rule_id,
                            severity="MEDIUM",
                            message=f"Dict membership check before assignment at line {line_no} - use setdefault() or defaultdict",
                            file_path=file_path,
                            line_number=line_no,
                            complexity="O(1) double lookup",
                            estimated_impact="MEDIUM",
                            snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                            remediation=f"Use {dict_name}.setdefault(key, default) or collections.defaultdict",
                        )
                        result.issues.append(issue)
                        return


# ---------------------------------------------------------------------------
# Async/blocking rules
# ---------------------------------------------------------------------------

class BlockingCallInAsyncRule(BasePerfRule):
    """Detects blocking calls in async functions."""

    BLOCKING_FUNCS = {
        'time.sleep', 'requests.get', 'requests.post', 'requests.put', 'requests.delete',
        'subprocess.call', 'subprocess.check_call', 'subprocess.check_output',
        'os.system', 'os.popen',
        'open', 'open(',
        'input', 'raw_input',
        'json.load', 'json.dump',
        'pickle.load', 'pickle.dump',
        'sqlite3.connect', 'sqlite3.execute',
    }

    BLOCKING_MODULES = {'time', 'requests', 'subprocess', 'os', 'pickle', 'sqlite3', 'shutil', 'socket'}

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "PERF-ASYNC-001"
        self._name = "Blocking Call in Async Function"
        self._description = "Detects blocking I/O calls inside async functions that should use async equivalents"
        self._severity = "HIGH"
        self._languages = ["python"]

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> PerfRuleResult:
        result = PerfRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                self._check_async_function(node, result, file_path, lines)

        return result

    def _check_async_function(self, func_node: ast.AsyncFunctionDef, result: PerfRuleResult, file_path: str, lines: List[str]) -> None:
        for node in ast.walk(func_node):
            if isinstance(node, ast.Call):
                func_name = self._get_full_func_name(node)

                # Check for blocking calls
                if func_name in self.BLOCKING_FUNCS:
                    line_no = node.lineno
                    async_alternative = self._get_async_alternative(func_name)
                    issue = PerfIssue(
                        rule_id=self.rule_id,
                        severity="HIGH",
                        message=f"Blocking call '{func_name}()' in async function '{func_node.name}' at line {line_no}",
                        file_path=file_path,
                        line_number=line_no,
                        complexity="Blocks event loop",
                        estimated_impact="HIGH",
                        snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                        remediation=f"Use async alternative: {async_alternative}",
                    )
                    result.issues.append(issue)

                # Check for blocking module imports used in async context
                if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    if node.func.value.id in self.BLOCKING_MODULES:
                        line_no = node.lineno
                        async_alternative = self._get_async_alternative(f"{node.func.value.id}.{node.func.attr}")
                        if async_alternative:
                            issue = PerfIssue(
                                rule_id=self.rule_id,
                                severity="MEDIUM",
                                message=f"Potential blocking call from '{node.func.value.id}' module in async function at line {line_no}",
                                file_path=file_path,
                                line_number=line_no,
                                complexity="Blocks event loop",
                                estimated_impact="MEDIUM",
                                snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                                remediation=f"Consider using async alternative: {async_alternative}",
                            )
                            result.issues.append(issue)

    def _get_full_func_name(self, node: ast.Call) -> str:
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                return f"{node.func.value.id}.{node.func.attr}"
            if isinstance(node.func.value, ast.Attribute):
                parts = []
                current = node.func
                while isinstance(current, ast.Attribute):
                    parts.append(current.attr)
                    current = current.value
                if isinstance(current, ast.Name):
                    parts.append(current.id)
                return ".".join(reversed(parts))
            return node.func.attr
        if isinstance(node.func, ast.Name):
            return node.func.id
        return ""

    def _get_async_alternative(self, blocking_func: str) -> str:
        mapping = {
            'time.sleep': 'asyncio.sleep()',
            'requests.get': 'aiohttp.ClientSession.get() or httpx.AsyncClient.get()',
            'requests.post': 'aiohttp.ClientSession.post() or httpx.AsyncClient.post()',
            'requests.put': 'aiohttp.ClientSession.put() or httpx.AsyncClient.put()',
            'requests.delete': 'aiohttp.ClientSession.delete() or httpx.AsyncClient.delete()',
            'subprocess.call': 'asyncio.create_subprocess_exec()',
            'subprocess.check_call': 'asyncio.create_subprocess_exec()',
            'subprocess.check_output': 'asyncio.create_subprocess_exec()',
            'os.system': 'asyncio.create_subprocess_exec()',
            'os.popen': 'asyncio.create_subprocess_exec()',
            'open': 'aiofiles.open()',
            'input': 'asyncio.get_event_loop().run_in_executor(None, input)',
            'json.load': 'asyncio.get_event_loop().run_in_executor(None, json.load)',
            'json.dump': 'asyncio.get_event_loop().run_in_executor(None, json.dump)',
            'pickle.load': 'asyncio.get_event_loop().run_in_executor(None, pickle.load)',
            'pickle.dump': 'asyncio.get_event_loop().run_in_executor(None, pickle.dump)',
            'sqlite3.connect': 'aiosqlite.connect()',
            'sqlite3.execute': 'aiosqlite.connect().execute()',
            'shutil.copy': 'asyncio.get_event_loop().run_in_executor(None, shutil.copy)',
            'socket.connect': 'asyncio.open_connection()',
            'socket.send': 'asyncio.get_event_loop().create_connection()',
        }
        return mapping.get(blocking_func, f"Use asyncio equivalent or run_in_executor() for {blocking_func}")


# ---------------------------------------------------------------------------
# Memory usage rules
# ---------------------------------------------------------------------------

class LargeAllocationRule(BasePerfRule):
    """Detects unnecessarily large memory allocations."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "PERF-MEM-001"
        self._name = "Large Memory Allocation"
        self._description = "Detects unnecessarily large memory allocations"
        self._severity = "MEDIUM"
        self._languages = ["python"]

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> PerfRuleResult:
        result = PerfRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            # Check for large list literals
            if isinstance(node, ast.List) and len(node.elts) > 100:
                line_no = node.lineno
                issue = PerfIssue(
                    rule_id=self.rule_id,
                    severity="LOW",
                    message=f"Large list literal with {len(node.elts)} elements at line {line_no}",
                    file_path=file_path,
                    line_number=line_no,
                    complexity=f"O({len(node.elts)}) memory",
                    estimated_impact="LOW",
                    snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                    remediation="Consider loading data from a file or using a generator",
                )
                result.issues.append(issue)

            # Check for large dict literals
            if isinstance(node, ast.Dict) and len(node.keys) > 50:
                line_no = node.lineno
                issue = PerfIssue(
                    rule_id=self.rule_id,
                    severity="LOW",
                    message=f"Large dict literal with {len(node.keys)} entries at line {line_no}",
                    file_path=file_path,
                    line_number=line_no,
                    complexity=f"O({len(node.keys)}) memory",
                    estimated_impact="LOW",
                    snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                    remediation="Consider loading data from a file or database",
                )
                result.issues.append(issue)

            # Check for [0] * N pattern
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
                if isinstance(node.left, ast.List) and len(node.left.elts) == 1:
                    if isinstance(node.right, ast.Constant) and isinstance(node.right.value, int) and node.right.value > 1000:
                        line_no = node.lineno
                        issue = PerfIssue(
                            rule_id=self.rule_id,
                            severity="LOW",
                            message=f"Large list replication [{node.left.elts[0].value}] * {node.right.value} at line {line_no}",
                            file_path=file_path,
                            line_number=line_no,
                            complexity=f"O({node.right.value}) memory",
                            estimated_impact="LOW",
                            snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                            remediation="Consider using array('i') or numpy for large numeric arrays",
                        )
                        result.issues.append(issue)

        return result


class SliceCopyRule(BasePerfRule):
    """Detects unnecessary slice copies."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "PERF-SLICE-001"
        self._name = "Unnecessary Slice Copy"
        self._description = "Detects pattern where [:] is used unnecessarily"
        self._severity = "LOW"
        self._languages = ["python"]

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> PerfRuleResult:
        result = PerfRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript):
                if isinstance(node.slice, ast.Slice):
                    if node.slice.lower is None and node.slice.upper is None and node.slice.step is None:
                        # This is a [:] copy
                        # Check if it's used in a context where a copy isn't needed
                        parent = self._find_parent(node, tree)
                        if parent:
                            # If it's used in a for loop iteration, copy is unnecessary
                            if isinstance(parent, (ast.For, ast.AsyncFor)) and parent.iter is node:
                                line_no = node.lineno
                                issue = PerfIssue(
                                    rule_id=self.rule_id,
                                    severity="LOW",
                                    message=f"Unnecessary full-slice copy [:] in for loop at line {line_no}",
                                    file_path=file_path,
                                    line_number=line_no,
                                    complexity="O(n) memory",
                                    estimated_impact="LOW",
                                    snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                                    remediation="Remove [:] - iterating directly over the list is safe without copying",
                                )
                                result.issues.append(issue)

        return result

    def _find_parent(self, node: ast.AST, tree: ast.AST) -> Optional[ast.AST]:
        for n in ast.walk(tree):
            for child in ast.iter_child_nodes(n):
                if child is node:
                    return n
        return None


# ---------------------------------------------------------------------------
# C performance rules
# ---------------------------------------------------------------------------

class CPerformanceRule(BasePerfRule):
    """Performance analysis for C code."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "PERF-C-001"
        self._name = "C Performance Issues"
        self._description = "Detects performance issues in C code"
        self._severity = "MEDIUM"
        self._languages = ["c"]

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> PerfRuleResult:
        result = PerfRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        PATTERNS = [
            (re.compile(r'\bstrlen\s*\([^)]+\)\s*[<>=!]+\s*\d'), "strlen() called repeatedly in loop condition", "HIGH", "Hoist strlen() result to a variable before the loop"),
            (re.compile(r'\bstrcat\s*\([^,]+,\s*[^)]+\)\s*;'), "strcat() in a loop creates O(n^2) behavior", "HIGH", "Track the end of string or use memcpy with offset"),
            (re.compile(r'\bprintf\s*\('), "printf() in performance-critical section", "LOW", "Consider buffered output or deferring formatting"),
            (re.compile(r'\bmalloc\s*\([^)]+\)\s*;\s*\n\s*\w+\s*=\s*\w+;\s*\n\s*free\s*\('), "malloc/free pair in hot loop", "HIGH", "Allocate once outside the loop and reuse"),
            (re.compile(r'\brealloc\s*\('), "realloc() in a loop", "MEDIUM", "Pre-allocate sufficient capacity, avoid repeated reallocation"),
            (re.compile(r'\bqsort\s*\('), "qsort() with function pointer comparison", "LOW", "Inline comparison may be faster; consider specialized sort for small arrays"),
            (re.compile(r'\bint\s+\w+\s*=\s*strlen\s*\('), "strlen() result stored in int instead of size_t", "LOW", "Use size_t for strlen() return value"),
            (re.compile(r'\b(?:for|while)\s*\([^;]+;\s*\w+\s*<\s*strlen\b'), "strlen() in loop condition evaluated each iteration", "CRITICAL", "Store strlen() result in a variable before the loop"),
        ]

        for i, line in enumerate(lines, 1):
            for pattern, message, severity, remediation in PATTERNS:
                if pattern.search(line):
                    issue = PerfIssue(
                        rule_id=self.rule_id,
                        severity=severity,
                        message=f"C performance: {message} at line {i}",
                        file_path=file_path,
                        line_number=i,
                        complexity="Varies",
                        estimated_impact=severity,
                        snippet=line.strip(),
                        remediation=remediation,
                    )
                    result.issues.append(issue)
                    break

        return result


# ---------------------------------------------------------------------------
# Rust performance rules
# ---------------------------------------------------------------------------

class RustPerformanceRule(BasePerfRule):
    """Performance analysis for Rust code."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "PERF-RUST-001"
        self._name = "Rust Performance Issues"
        self._description = "Detects performance issues in Rust code"
        self._severity = "MEDIUM"
        self._languages = ["rust"]

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> PerfRuleResult:
        result = PerfRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        PATTERNS = [
            (re.compile(r'\.clone\s*\(\s*\)'), "Unnecessary clone() call", "MEDIUM", "Use references (&T) instead of cloning. Clone is expensive for large types."),
            (re.compile(r'\.to_string\s*\(\s*\)'), "to_string() in hot path", "MEDIUM", "Consider using String::from or Cow<str> for borrowed string data"),
            (re.compile(r'\.collect::<Vec<_>>\s*\(\s*\)\s*\.iter\b'), "Collect to Vec then iterate", "HIGH", "Use the iterator directly without collecting to Vec"),
            (re.compile(r'\.collect::<Vec<_>>\s*\(\s*\)\s*\.into_iter\b'), "Collect to Vec then into_iter()", "HIGH", "Use the iterator directly - collect() adds allocation overhead"),
            (re.compile(r'for\s+\w+\s+in\s+\w+\.iter\s*\(\s*\)\s*\{'), "Explicit .iter() call in for loop", "LOW", "Remove .iter() - for x in &collection is equivalent and clearer"),
            (re.compile(r'\.chars\(\)\.count\(\)'), "chars().count() on a string", "LOW", "calling chars().count() is O(n). Use .len() for byte length, or cache the result."),
            (re.compile(r'\bBox::new\s*\([^)]+\)\s*\)'), "Box::new in hot loop", "MEDIUM", "Box allocates on the heap. Avoid in tight loops."),
            (re.compile(r'\bArc::new\s*\([^)]+\)\s*\)'), "Arc::new in hot loop", "MEDIUM", "Arc has atomic reference counting overhead. Consider Rc or avoid sharing."),
            (re.compile(r'\bRc::new\s*\([^)]+\)\s*\)'), "Rc::new in hot loop", "LOW", "Rc has non-atomic reference counting overhead. Consider using references."),
            (re.compile(r'\.to_owned\s*\(\s*\)'), "to_owned() in performance-critical path", "MEDIUM", "to_owned() allocates. Use borrowing where possible."),
            (re.compile(r'\.as_str\s*\(\s*\)\s*\.to_string\s*\(\s*\)'), "as_str().to_string() chain", "MEDIUM", "Chain creates unnecessary intermediate step. Use .to_string() directly."),
            (re.compile(r'\bVec::<[^>]+>::new\s*\(\)'), "Vec::new() can be replaced with vec![]", "LOW", "Use vec![] for initialization with known elements"),
            (re.compile(r'\.collect::<HashMap<'), "Collecting into HashMap", "LOW", "Consider using .collect() with HashMap::from_iter or specifying capacity"),
            (re.compile(r'\bHashMap<[^>]+>\s*::new\s*\(\s*\)'), "HashMap::new() with known size", "MEDIUM", "Use HashMap::with_capacity(n) if you know the approximate size to avoid reallocation"),
            (re.compile(r'\bHashSet<[^>]+>\s*::new\s*\(\s*\)'), "HashSet::new() with known size", "MEDIUM", "Use HashSet::with_capacity(n) if you know the approximate size to avoid reallocation"),
            (re.compile(r'\.filter\s*\([^)]+\)\s*\.filter\s*\('), "Chained filters could be combined", "LOW", "Combine filter closures for better cache locality: .filter(|x| cond1 && cond2)"),
            (re.compile(r'\.map\s*\([^)]+\)\s*\.map\s*\('), "Chained maps could be combined", "LOW", "Combine map closures: .map(|x| transform1(transform2(x)))"),
            (re.compile(r'\.iter\(\).*\.collect::<Vec<_>>\(\).*\.len\(\)'), "Collect to Vec just for length", "HIGH", "Use .count() instead of collecting to Vec and checking length"),
        ]

        for i, line in enumerate(lines, 1):
            for pattern, message, severity, remediation in PATTERNS:
                if pattern.search(line):
                    issue = PerfIssue(
                        rule_id=self.rule_id,
                        severity=severity,
                        message=f"Rust performance: {message} at line {i}",
                        file_path=file_path,
                        line_number=i,
                        complexity="Varies",
                        estimated_impact=severity,
                        snippet=line.strip(),
                        remediation=remediation,
                    )
                    result.issues.append(issue)
                    break

        return result


# ---------------------------------------------------------------------------
# General performance rules
# ---------------------------------------------------------------------------

class ImportTimeSideEffectRule(BasePerfRule):
    """Detects import-time side effects that slow down module loading."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "PERF-IMPORT-001"
        self._name = "Import-Time Side Effect"
        self._description = "Detects expensive operations at module level that execute on import"
        self._severity = "MEDIUM"
        self._languages = ["python"]

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> PerfRuleResult:
        result = PerfRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, ast.Module):
                for child in ast.iter_child_nodes(node):
                    # Check for expensive top-level calls
                    if isinstance(child, ast.Expr) and isinstance(child.value, ast.Call):
                        call = child.value
                        func_name = ""
                        if isinstance(call.func, ast.Name):
                            func_name = call.func.id
                        elif isinstance(call.func, ast.Attribute):
                            if isinstance(call.func.value, ast.Name):
                                func_name = f"{call.func.value.id}.{call.func.attr}"

                        if func_name in ('open', 'os.open', 'pathlib.Path.open', 'subprocess.call', 'subprocess.Popen', 'requests.get', 'requests.post'):
                            line_no = child.lineno
                            issue = PerfIssue(
                                rule_id=self.rule_id,
                                severity="MEDIUM",
                                message=f"Expensive operation at module level: {func_name}() at line {line_no}",
                                file_path=file_path,
                                line_number=line_no,
                                complexity="I/O operation on import",
                                estimated_impact="MEDIUM",
                                snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                                remediation=f"Move {func_name}() into a function or lazy initialization to avoid execution on import",
                            )
                            result.issues.append(issue)

                    # Check for large top-level comprehensions
                    if isinstance(child, ast.Assign):
                        for target in child.targets:
                            if isinstance(target, ast.Name) and isinstance(child.value, (ast.ListComp, ast.SetComp, ast.DictComp)):
                                line_no = child.lineno
                                issue = PerfIssue(
                                    rule_id=self.rule_id,
                                    severity="LOW",
                                    message=f"Top-level comprehension assigned to '{target.id}' at line {line_no} executed on import",
                                    file_path=file_path,
                                    line_number=line_no,
                                    complexity="O(n) on import",
                                    estimated_impact="LOW",
                                    snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                                    remediation=f"Move '{target.id}' into a lazy-initialized function or use generators",
                                )
                                result.issues.append(issue)

        return result


class UnnecessaryElseInLoopRule(BasePerfRule):
    """Detects unnecessary else clause in for/while loops."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "PERF-LOOP-002"
        self._name = "Unnecessary Loop Else"
        self._description = "Detects for/while-else patterns that may indicate confusion or unnecessary code"
        self._severity = "INFO"
        self._languages = ["python"]

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> PerfRuleResult:
        result = PerfRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.While)):
                # Check if there's a break in the loop body
                has_break = any(isinstance(n, ast.Break) for n in ast.walk(node))
                if has_break and node.orelse:
                    line_no = node.orelse[0].lineno if node.orelse else node.lineno
                    issue = PerfIssue(
                        rule_id=self.rule_id,
                        severity="INFO",
                        message=f"for-else clause at line {line_no} - the else block runs when no break occurs",
                        file_path=file_path,
                        line_number=line_no,
                        complexity="N/A",
                        estimated_impact="INFO",
                        snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                        remediation="Ensure the else clause is intentional - it runs only when the loop completes without break",
                    )
                    result.issues.append(issue)

        return result


class RedundantCallRule(BasePerfRule):
    """Detects redundant function calls that can be simplified."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "PERF-REDUN-001"
        self._name = "Redundant Function Call"
        self._description = "Detects redundant or unnecessary function calls"
        self._severity = "LOW"
        self._languages = ["python"]

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> PerfRuleResult:
        result = PerfRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        REDUNDANT_PATTERNS = [
            lambda n: isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'list' and n.args and isinstance(n.args[0], ast.ListComp),
            lambda n: isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'list' and n.args and isinstance(n.args[0], ast.Call) and isinstance(n.args[0].func, ast.Attribute) and n.args[0].func.attr == 'keys',
            lambda n: isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'list' and n.args and isinstance(n.args[0], ast.Call) and isinstance(n.args[0].func, ast.Attribute) and n.args[0].func.attr == 'values',
            lambda n: isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'list' and n.args and isinstance(n.args[0], ast.Call) and isinstance(n.args[0].func, ast.Attribute) and n.args[0].func.attr == 'items',
            lambda n: isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'set' and n.args and isinstance(n.args[0], ast.SetComp),
            lambda n: isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'dict' and n.args and isinstance(n.args[0], ast.DictComp),
            lambda n: isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'str' and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str),
            lambda n: isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'int' and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, int),
            lambda n: isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'float' and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, float),
            lambda n: isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'bool' and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, bool),
            lambda n: isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'list' and n.args and isinstance(n.args[0], ast.Call) and isinstance(n.args[0].func, ast.Attribute) and n.args[0].func.attr == 'items',
        ]

        for node in ast.walk(tree):
            for pattern in REDUNDANT_PATTERNS:
                if pattern(node):
                    line_no = node.lineno
                    msg = self._describe_redundant_call(node)
                    issue = PerfIssue(
                        rule_id=self.rule_id,
                        severity="LOW",
                        message=f"Redundant call: {msg} at line {line_no}",
                        file_path=file_path,
                        line_number=line_no,
                        complexity="N/A",
                        estimated_impact="LOW",
                        snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                        remediation=self._remediate_redundant_call(node),
                    )
                    result.issues.append(issue)
                    break

        return result

    def _describe_redundant_call(self, node: ast.Call) -> str:
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name == 'list' and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.ListComp):
                    return "list() around list comprehension"
                if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute):
                    return f"list() around dict.{arg.func.attr}()"
            if func_name == 'str' and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                return "str() on a string"
            if func_name in ('int', 'float', 'bool') and isinstance(node.args[0], ast.Constant):
                return f"{func_name}() on a {func_name} literal"
        return "redundant function call"

    def _remediate_redundant_call(self, node: ast.Call) -> str:
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name == 'list' and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.ListComp):
                    return "Remove the outer list() call - list comprehension already creates a list"
                if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute):
                    return f"Remove the outer list() call - dict.{arg.func.attr}() returns a view that can be iterated directly"
            if func_name in ('str', 'int', 'float', 'bool') and isinstance(node.args[0], ast.Constant):
                return f"Remove the redundant {func_name}() call, the value is already the correct type"
        return "Remove the redundant call"


class FstringVsFormatRule(BasePerfRule):
    """Detects where f-strings should be preferred over .format() or % formatting."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "PERF-FSTR-001"
        self._name = "F-String Preference"
        self._description = "Detects .format() or % formatting where f-strings would be faster and more readable"
        self._severity = "LOW"
        self._languages = ["python"]

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> PerfRuleResult:
        result = PerfRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'format':
                # Check if the format call is on a string constant
                if isinstance(node.func.value, ast.Constant) and isinstance(node.func.value.value, str):
                    # Simple pattern: "hello {}".format(var)
                    line_no = node.lineno
                    issue = PerfIssue(
                        rule_id=self.rule_id,
                        severity="LOW",
                        message=f"Use f-string instead of .format() at line {line_no}",
                        file_path=file_path,
                        line_number=line_no,
                        complexity="N/A",
                        estimated_impact="LOW",
                        snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                        remediation="Replace .format() with an f-string for better readability and performance",
                    )
                    result.issues.append(issue)

            # Check for % formatting
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
                if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str) and '%' in node.left.value:
                    line_no = node.lineno
                    issue = PerfIssue(
                        rule_id=self.rule_id,
                        severity="LOW",
                        message=f"Use f-string instead of % formatting at line {line_no}",
                        file_path=file_path,
                        line_number=line_no,
                        complexity="N/A",
                        estimated_impact="LOW",
                        snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                        remediation="Replace % formatting with an f-string for better readability and performance",
                    )
                    result.issues.append(issue)

        return result


class DeadCodeInLoopRule(BasePerfRule):
    """Detects dead code patterns inside loops."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "PERF-DEAD-001"
        self._name = "Dead Code in Loop"
        self._description = "Detects assignments inside loops that are overwritten each iteration"
        self._severity = "LOW"
        self._languages = ["python"]

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> PerfRuleResult:
        result = PerfRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                # Check for variable assignments that are never used after the loop
                assigned_in_loop = set()
                for stmt in node.body:
                    if isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            if isinstance(target, ast.Name):
                                assigned_in_loop.add(target.id)

                # Check if these variables are used outside the loop
                for var_name in assigned_in_loop:
                    used_outside = False
                    for n in ast.walk(tree):
                        if n is node:
                            continue
                        if isinstance(n, ast.Name) and n.id == var_name:
                            # Check if it's in a parent scope
                            if self._is_outside_loop(n, node):
                                used_outside = True
                                break
                    if not used_outside:
                        # Find the assignment line
                        for stmt in node.body:
                            if isinstance(stmt, ast.Assign):
                                for target in stmt.targets:
                                    if isinstance(target, ast.Name) and target.id == var_name:
                                        line_no = stmt.lineno
                                        issue = PerfIssue(
                                            rule_id=self.rule_id,
                                            severity="LOW",
                                            message=f"Loop variable '{var_name}' assigned at line {line_no} but not used after loop",
                                            file_path=file_path,
                                            line_number=line_no,
                                            complexity="N/A",
                                            estimated_impact="LOW",
                                            snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                                            remediation=f"Consider removing or moving '{var_name}' outside the loop if it's overwritten each iteration",
                                        )
                                        result.issues.append(issue)
                                        break

        return result

    def _is_outside_loop(self, node: ast.Name, loop_node: ast.AST) -> bool:
        """Check if the name usage is outside the loop body."""
        for parent in ast.walk(loop_node):
            for child in ast.iter_child_nodes(parent):
                if child is node:
                    return False
        return True


# ---------------------------------------------------------------------------
# Rule registry
# ---------------------------------------------------------------------------

def get_all_performance_rules(config: Optional[Dict[str, Any]] = None) -> List[BasePerfRule]:
    """Return all registered performance rules."""
    return [
        NestedLoopDetectionRule(config),
        ListComprehensionOverGenerationRule(config),
        UnnecessaryListAllocationRule(config),
        RepeatedComputationInLoopRule(config),
        StringConcatenationInLoopRule(config),
        InefficientDataStructureRule(config),
        DefaultDictVsSetDefaultRule(config),
        BlockingCallInAsyncRule(config),
        LargeAllocationRule(config),
        SliceCopyRule(config),
        CPerformanceRule(config),
        RustPerformanceRule(config),
        ImportTimeSideEffectRule(config),
        UnnecessaryElseInLoopRule(config),
        RedundantCallRule(config),
        FstringVsFormatRule(config),
        DeadCodeInLoopRule(config),
    ]


def get_performance_rules_by_language(language: str, config: Optional[Dict[str, Any]] = None) -> List[BasePerfRule]:
    """Return performance rules applicable to a specific language."""
    return [rule for rule in get_all_performance_rules(config) if language in rule.languages]


def get_performance_rule_by_id(rule_id: str, config: Optional[Dict[str, Any]] = None) -> Optional[BasePerfRule]:
    """Return a specific performance rule by ID."""
    for rule in get_all_performance_rules(config):
        if rule.rule_id == rule_id:
            return rule
    return None