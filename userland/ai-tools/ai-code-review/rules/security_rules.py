"""
Security Rules Module for AI Code Review.

Provides comprehensive security-focused analysis rules for Python, C, and Rust.
Detects vulnerabilities including SQL injection, XSS, command injection, path traversal,
insecure deserialization, hardcoded secrets, weak cryptography, and more.
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
class SecurityIssue:
    """Represents a single security issue detected by a rule."""
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
    cwe: str = ""
    cvss_score: float = 0.0
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SecurityRuleResult:
    """Result from a single security rule check."""
    rule_id: str
    rule_name: str
    description: str
    issues: List[SecurityIssue] = field(default_factory=list)
    duration_ms: float = 0.0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Base rule class
# ---------------------------------------------------------------------------

class BaseSecurityRule(ABC):
    """Abstract base for all security rules."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._rule_id: str = ""
        self._name: str = ""
        self._description: str = ""
        self._severity: str = "MEDIUM"
        self._languages: List[str] = field(default_factory=lambda: ["python"])
        self._cwe: str = ""
        self._cvss: float = 0.0

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

    @property
    def cwe(self) -> str:
        return self._cwe

    @abstractmethod
    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        """Run the rule check on the given AST."""


# ---------------------------------------------------------------------------
# Python-specific security rules
# ---------------------------------------------------------------------------

class SQLInjectionRule(BaseSecurityRule):
    """Detects potential SQL injection vulnerabilities in Python code."""

    SQL_KEYWORDS = {"SELECT", "INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE", "EXEC", "EXECUTE"}
    DANGEROUS_PATTERNS = [
        re.compile(r'execute\s*\(\s*f["\']'),  # f-string in execute
        re.compile(r'execute\s*\(\s*["\'][^"\']*\{[^}]*\}'),  # format string in execute
        re.compile(r'execute\s*\(\s*[\'\"].*?%[sd]'),  # % formatting
        re.compile(r'execute\s*\(\s*[\'\"].*?\+\s*\w+'),  # string concatenation
        re.compile(r'raw_input\(|input\s*\(.*\)'),  # unsanitized input
    ]
    RAW_SQL_FUNCS = {"raw_input", "input", "request.get", "request.form", "request.args", "request.values"}

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "SEC-SQL-001"
        self._name = "SQL Injection Detection"
        self._description = "Detects SQL injection vulnerabilities from string formatting in SQL queries"
        self._severity = "CRITICAL"
        self._languages = ["python"]
        self._cwe = "CWE-89"
        self._cvss = 9.8

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        result = SecurityRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            # Check for string concatenation in execute/executemany
            if isinstance(node, ast.Call) and hasattr(node.func, 'attr') and node.func.attr in ('execute', 'executemany', 'executescript'):
                self._check_execute_call(node, result, file_path, lines, source_code)

            # Check for raw SQL construction with string formatting
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ('format', 'format_map') and self._is_sql_context(node, source_code):
                    self._check_format_in_sql(node, result, file_path, lines, source_code)

            # Check for ORM methods with raw SQL
            if isinstance(node, ast.Call) and hasattr(node.func, 'attr'):
                orm_raw_methods = {'raw', 'from_statement', 'text', 'where', 'having'}
                if node.func.attr in orm_raw_methods:
                    self._check_orm_raw_sql(node, result, file_path, lines, source_code)

        return result

    def _check_execute_call(self, node: ast.Call, result: SecurityRuleResult, file_path: str, lines: List[str], source_code: str) -> None:
        if not node.args:
            return
        query_arg = node.args[0]
        line_no = node.lineno

        # f-string in execute
        if isinstance(query_arg, ast.JoinedStr):
            issue = SecurityIssue(
                rule_id=self.rule_id,
                severity="CRITICAL",
                message=f"SQL injection vulnerability: f-string used in database execute() call at line {line_no}. Use parameterized queries instead.",
                file_path=file_path,
                line_number=line_no,
                cwe=self.cwe,
                cvss_score=self._cvss,
                remediation="Use parameterized queries: cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))",
                snippet=lines[line_no - 1] if line_no <= len(lines) else "",
            )
            result.issues.append(issue)
            return

        # String concatenation in execute
        if isinstance(query_arg, ast.BinOp) and isinstance(query_arg.op, ast.Add):
            issue = SecurityIssue(
                rule_id=self.rule_id,
                severity="CRITICAL",
                message=f"SQL injection vulnerability: string concatenation in execute() at line {line_no}",
                file_path=file_path,
                line_number=line_no,
                cwe=self.cwe,
                cvss_score=self._cvss,
                remediation="Use parameterized queries with placeholders instead of string concatenation",
                snippet=lines[line_no - 1] if line_no <= len(lines) else "",
            )
            result.issues.append(issue)
            return

        # String with % formatting
        if isinstance(query_arg, ast.Constant) and isinstance(query_arg.value, str):
            if '%s' in query_arg.value or '%d' in query_arg.value or '%(' in query_arg.value:
                # Check if there's a second argument (tuple/dict for formatting)
                if len(node.args) >= 2:
                    issue = SecurityIssue(
                        rule_id=self.rule_id,
                        severity="HIGH",
                        message=f"SQL injection vulnerability: % formatting in execute() at line {line_no}",
                        file_path=file_path,
                        line_number=line_no,
                        cwe=self.cwe,
                        cvss_score=8.2,
                        remediation="Use parameterized queries: execute('SELECT * FROM users WHERE id = %s', (id,))",
                        snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                    )
                    result.issues.append(issue)

        # .format() in execute
        if isinstance(query_arg, ast.Call) and isinstance(query_arg.func, ast.Attribute) and query_arg.func.attr == 'format':
            issue = SecurityIssue(
                rule_id=self.rule_id,
                severity="CRITICAL",
                message=f"SQL injection vulnerability: .format() used in execute() at line {line_no}",
                file_path=file_path,
                line_number=line_no,
                cwe=self.cwe,
                cvss_score=self._cvss,
                remediation="Use parameterized queries instead of .format() for SQL queries",
                snippet=lines[line_no - 1] if line_no <= len(lines) else "",
            )
            result.issues.append(issue)

    def _is_sql_context(self, node: ast.Call, source_code: str) -> bool:
        """Heuristic: check if the surrounding context is SQL-related."""
        # Walk up to find assignment to SQL-related variable names
        for parent in ast.walk(node):
            if isinstance(parent, ast.Assign):
                for target in parent.targets:
                    if isinstance(target, ast.Name) and any(kw in target.id.upper() for kw in self.SQL_KEYWORDS):
                        return True
                    if isinstance(target, ast.Attribute) and any(kw in target.attr.upper() for kw in self.SQL_KEYWORDS):
                        return True
        return False

    def _check_format_in_sql(self, node: ast.Call, result: SecurityRuleResult, file_path: str, lines: List[str], source_code: str) -> None:
        line_no = node.lineno
        issue = SecurityIssue(
            rule_id=self.rule_id,
            severity="HIGH",
            message=f"Potential SQL injection: .format() used in SQL context at line {line_no}",
            file_path=file_path,
            line_number=line_no,
            cwe=self.cwe,
            cvss_score=8.2,
            remediation="Use parameterized queries instead of .format() for SQL strings",
            snippet=lines[line_no - 1] if line_no <= len(lines) else "",
        )
        result.issues.append(issue)

    def _check_orm_raw_sql(self, node: ast.Call, result: SecurityRuleResult, file_path: str, lines: List[str], source_code: str) -> None:
        if not node.args:
            return
        arg = node.args[0]
        line_no = node.lineno

        dangerous = False
        if isinstance(arg, ast.JoinedStr):
            dangerous = True
        elif isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add):
            dangerous = True
        elif isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == 'format':
            dangerous = True

        if dangerous:
            issue = SecurityIssue(
                rule_id=self.rule_id,
                severity="CRITICAL",
                message=f"SQL injection vulnerability: raw SQL with string formatting in ORM method at line {line_no}",
                file_path=file_path,
                line_number=line_no,
                cwe=self.cwe,
                cvss_score=self._cvss,
                remediation="Use ORM query builder methods or parameterized raw SQL",
                snippet=lines[line_no - 1] if line_no <= len(lines) else "",
            )
            result.issues.append(issue)


class XSSRule(BaseSecurityRule):
    """Detects cross-site scripting vulnerabilities."""

    DANGEROUS_METHODS = {
        'render_template_string', 'Markup', 'format_html', 'format_html_join',
        'mark_safe', 'safe', 'HTML', 'write', 'response.write',
        'innerHTML', 'outerHTML', 'insertAdjacentHTML',
    }
    DANGEROUS_TEMPLATE_PATTERNS = [
        re.compile(r'\{\{.*?\|?\s*safe\s*\}\}'),
        re.compile(r'\{\%.*?autoescape\s+off.*?\%\}'),
        re.compile(r'\$\{.*?\}'),
    ]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "SEC-XSS-001"
        self._name = "Cross-Site Scripting Detection"
        self._description = "Detects cross-site scripting vulnerabilities in Python web applications"
        self._severity = "CRITICAL"
        self._languages = ["python"]
        self._cwe = "CWE-79"
        self._cvss = 8.6

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        result = SecurityRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            # Check for dangerous function calls
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in self.DANGEROUS_METHODS:
                    self._check_dangerous_call(node, result, file_path, lines, source_code)
                if node.func.attr == 'render_template_string':
                    self._check_render_template_string(node, result, file_path, lines, source_code)

            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in self.DANGEROUS_METHODS:
                    self._check_dangerous_call(node, result, file_path, lines, source_code)

            # Check for unsafe string concatenation in HTML context
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                if self._is_html_context(node, source_code):
                    self._check_concat_in_html(node, result, file_path, lines, source_code)

        return result

    def _check_dangerous_call(self, node: ast.Call, result: SecurityRuleResult, file_path: str, lines: List[str], source_code: str) -> None:
        func_name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        line_no = node.lineno
        has_user_input = self._has_user_input_arg(node)

        severity = "CRITICAL" if has_user_input else "HIGH"
        cvss = 8.6 if has_user_input else 6.1

        if func_name in ('safe', 'mark_safe', 'Markup'):
            issue = SecurityIssue(
                rule_id=self.rule_id,
                severity=severity,
                message=f"XSS vulnerability: {func_name}() used potentially with unsanitized input at line {line_no}",
                file_path=file_path,
                line_number=line_no,
                cwe=self.cwe,
                cvss_score=cvss,
                remediation="Use mark_safe only on trusted strings, or escape HTML entities with escape() or conditional_escape()",
                snippet=lines[line_no - 1] if line_no <= len(lines) else "",
            )
            result.issues.append(issue)

        if func_name in ('innerHTML', 'outerHTML', 'insertAdjacentHTML'):
            issue = SecurityIssue(
                rule_id=self.rule_id,
                severity="CRITICAL",
                message=f"XSS vulnerability: {func_name} used with user-controlled data at line {line_no}",
                file_path=file_path,
                line_number=line_no,
                cwe=self.cwe,
                cvss_score=self._cvss,
                remediation="Use textContent or createTextNode() instead of innerHTML when inserting user data",
                snippet=lines[line_no - 1] if line_no <= len(lines) else "",
            )
            result.issues.append(issue)

    def _check_render_template_string(self, node: ast.Call, result: SecurityRuleResult, file_path: str, lines: List[str], source_code: str) -> None:
        line_no = node.lineno
        if not node.args:
            return

        template_arg = node.args[0]
        if isinstance(template_arg, ast.JoinedStr) or isinstance(template_arg, ast.BinOp):
            issue = SecurityIssue(
                rule_id=self.rule_id,
                severity="CRITICAL",
                message=f"XSS vulnerability: Dynamic template string in render_template_string() at line {line_no}",
                file_path=file_path,
                line_number=line_no,
                cwe=self.cwe,
                cvss_score=self._cvss,
                remediation="Use render_template() with separate template files instead of dynamic strings",
                snippet=lines[line_no - 1] if line_no <= len(lines) else "",
            )
            result.issues.append(issue)

    def _check_concat_in_html(self, node: ast.BinOp, result: SecurityRuleResult, file_path: str, lines: List[str], source_code: str) -> None:
        line_no = node.lineno
        issue = SecurityIssue(
            rule_id=self.rule_id,
            severity="MEDIUM",
            message=f"Potential XSS: string concatenation in HTML context at line {line_no}",
            file_path=file_path,
            line_number=line_no,
            cwe=self.cwe,
            cvss_score=4.3,
            remediation="Use template engines with auto-escaping or explicitly escape HTML entities",
            snippet=lines[line_no - 1] if line_no <= len(lines) else "",
        )
        result.issues.append(issue)

    def _is_html_context(self, node: ast.AST, source_code: str) -> bool:
        """Check if the AST node is within an HTML-generating context."""
        for parent in ast.walk(node):
            if isinstance(parent, ast.Call):
                name = ""
                if isinstance(parent.func, ast.Attribute):
                    name = parent.func.attr
                elif isinstance(parent.func, ast.Name):
                    name = parent.func.id
                if name in ('render_template', 'render_template_string', 'make_response', 'Response'):
                    return True
        return False

    def _has_user_input_arg(self, node: ast.Call) -> bool:
        """Check if any argument looks like user input."""
        input_names = {'request', 'form', 'args', 'data', 'json', 'cookies', 'files', 'environ', 'session', 'g'}
        for arg in node.args:
            if isinstance(arg, ast.Name) and arg.id in input_names:
                return True
            if isinstance(arg, ast.Attribute):
                if isinstance(arg.value, ast.Name) and arg.value.id in input_names:
                    return True
                if isinstance(arg.value, ast.Attribute):
                    outer = arg.value
                    if isinstance(outer.value, ast.Name) and outer.value.id in ('request', 'flask'):
                        return True
        for kw in node.keywords:
            if isinstance(kw.value, ast.Name) and kw.value.id in input_names:
                return True
            if isinstance(kw.value, ast.Attribute):
                if isinstance(kw.value.value, ast.Name) and kw.value.value.id in input_names:
                    return True
        return False


class CommandInjectionRule(BaseSecurityRule):
    """Detects command injection vulnerabilities."""

    DANGEROUS_FUNCS = {
        'os.system', 'os.popen', 'os.popen2', 'os.popen3', 'os.popen4',
        'subprocess.call', 'subprocess.check_call', 'subprocess.check_output',
        'subprocess.Popen', 'subprocess.getoutput', 'subprocess.getstatusoutput',
        'commands.getoutput', 'commands.getstatusoutput',
        'asyncio.create_subprocess_exec', 'asyncio.create_subprocess_shell',
        'pty.spawn',
    }

    DANGEROUS_NAMES = {
        'system', 'popen', 'Popen', 'call', 'check_call', 'check_output',
        'getoutput', 'getstatusoutput', 'spawn',
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "SEC-CMD-001"
        self._name = "Command Injection Detection"
        self._description = "Detects command injection vulnerabilities from shell execution with unsanitized input"
        self._severity = "CRITICAL"
        self._languages = ["python"]
        self._cwe = "CWE-78"
        self._cvss = 9.8

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        result = SecurityRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            func_name = self._get_full_func_name(node)

            # Check known dangerous functions
            if func_name in self.DANGEROUS_FUNCS or node.func.attr if isinstance(node.func, ast.Attribute) and node.func.attr in self.DANGEROUS_NAMES else False:
                self._check_dangerous_func(node, func_name, result, file_path, lines, source_code)

            # Check for shell=True in subprocess
            if func_name in ('subprocess.call', 'subprocess.check_call', 'subprocess.check_output', 'subprocess.Popen', 'subprocess.run'):
                self._check_shell_true(node, result, file_path, lines, source_code)

            # Check os.system with dynamic input
            if func_name == 'os.system' or (isinstance(node.func, ast.Name) and node.func.id == 'system'):
                self._check_os_system(node, result, file_path, lines, source_code)

        return result

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

    def _check_dangerous_func(self, node: ast.Call, func_name: str, result: SecurityRuleResult, file_path: str, lines: List[str], source_code: str) -> None:
        if not node.args:
            return
        arg = node.args[0]
        line_no = node.lineno

        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            # Static string is okay (though still flagged at lower severity)
            issue = SecurityIssue(
                rule_id=self.rule_id,
                severity="MEDIUM",
                message=f"Command injection: {func_name}() called with potentially static shell command at line {line_no}",
                file_path=file_path,
                line_number=line_no,
                cwe=self.cwe,
                cvss_score=5.0,
                remediation="Use subprocess.run() with a list of arguments instead of shell=True",
                snippet=lines[line_no - 1] if line_no <= len(lines) else "",
            )
            result.issues.append(issue)
            return

        if isinstance(arg, ast.JoinedStr) or isinstance(arg, ast.BinOp):
            severity = "CRITICAL"
            cvss = 9.8
        elif isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == 'format':
            severity = "CRITICAL"
            cvss = 9.8
        elif isinstance(arg, ast.Name):
            severity = "HIGH"
            cvss = 8.2
        else:
            severity = "HIGH"
            cvss = 7.8

        issue = SecurityIssue(
            rule_id=self.rule_id,
            severity=severity,
            message=f"Command injection vulnerability: {func_name}() called with dynamic input at line {line_no}",
            file_path=file_path,
            line_number=line_no,
            cwe=self.cwe,
            cvss_score=cvss,
            remediation="Use subprocess.run() with a list argument and shell=False, or validate/sanitize all input",
            snippet=lines[line_no - 1] if line_no <= len(lines) else "",
        )
        result.issues.append(issue)

    def _check_shell_true(self, node: ast.Call, result: SecurityRuleResult, file_path: str, lines: List[str], source_code: str) -> None:
        line_no = node.lineno
        for kw in node.keywords:
            if kw.arg == 'shell' and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                issue = SecurityIssue(
                    rule_id=self.rule_id,
                    severity="CRITICAL",
                    message=f"Command injection vulnerability: subprocess call with shell=True at line {line_no}",
                    file_path=file_path,
                    line_number=line_no,
                    cwe=self.cwe,
                    cvss_score=self._cvss,
                    remediation="Avoid shell=True. Use a list of arguments instead: subprocess.run(['command', 'arg1', 'arg2'])",
                    snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                )
                result.issues.append(issue)
                return

    def _check_os_system(self, node: ast.Call, result: SecurityRuleResult, file_path: str, lines: List[str], source_code: str) -> None:
        if not node.args:
            return
        arg = node.args[0]
        line_no = node.lineno

        if isinstance(arg, (ast.Name, ast.Attribute, ast.JoinedStr, ast.BinOp, ast.Call)):
            severity = "CRITICAL" if isinstance(arg, (ast.JoinedStr, ast.BinOp)) else "HIGH"
            cvss = 9.8 if severity == "CRITICAL" else 8.2
            issue = SecurityIssue(
                rule_id=self.rule_id,
                severity=severity,
                message=f"Command injection: os.system() called with variable/dynamic input at line {line_no}",
                file_path=file_path,
                line_number=line_no,
                cwe=self.cwe,
                cvss_score=cvss,
                remediation="Use subprocess.run() with a list argument instead of os.system()",
                snippet=lines[line_no - 1] if line_no <= len(lines) else "",
            )
            result.issues.append(issue)


class PathTraversalRule(BaseSecurityRule):
    """Detects path traversal vulnerabilities."""

    DANGEROUS_FUNCS = {
        'open', 'io.open', 'os.open', 'pathlib.Path.open',
        'os.remove', 'os.unlink', 'os.rename', 'os.replace',
        'shutil.copy', 'shutil.copy2', 'shutil.move',
        'os.listdir', 'os.scandir', 'os.walk',
        'os.mkdir', 'os.makedirs',
        'open', 'codecs.open',
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "SEC-PATH-001"
        self._name = "Path Traversal Detection"
        self._description = "Detects path traversal vulnerabilities from user-controlled file paths"
        self._severity = "HIGH"
        self._languages = ["python"]
        self._cwe = "CWE-22"
        self._cvss = 7.5

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        result = SecurityRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            func_name = self._get_func_name(node)
            if func_name not in self.DANGEROUS_FUNCS:
                continue

            if not node.args:
                continue

            path_arg = node.args[0]
            line_no = node.lineno

            if isinstance(path_arg, (ast.Name, ast.Attribute)):
                # Check if the variable could be user-controlled
                var_name = self._get_var_name(path_arg)
                if var_name and self._is_likely_user_input(var_name, tree, source_code):
                    issue = SecurityIssue(
                        rule_id=self.rule_id,
                        severity="HIGH",
                        message=f"Path traversal: {func_name}() called with possibly user-controlled path '{var_name}' at line {line_no}",
                        file_path=file_path,
                        line_number=line_no,
                        cwe=self.cwe,
                        cvss_score=self._cvss,
                        remediation="Validate and sanitize file paths: use os.path.abspath() and check against a whitelist of allowed directories",
                        snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                    )
                    result.issues.append(issue)

            if isinstance(path_arg, (ast.JoinedStr, ast.BinOp)):
                issue = SecurityIssue(
                    rule_id=self.rule_id,
                    severity="HIGH",
                    message=f"Path traversal: dynamic path construction in {func_name}() at line {line_no}",
                    file_path=file_path,
                    line_number=line_no,
                    cwe=self.cwe,
                    cvss_score=self._cvss,
                    remediation="Use os.path.join() and validate the resulting path is within allowed directories",
                    snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                )
                result.issues.append(issue)

        return result

    def _get_func_name(self, node: ast.Call) -> str:
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                return f"{node.func.value.id}.{node.func.attr}"
            return node.func.attr
        return ""

    def _get_var_name(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def _is_likely_user_input(self, var_name: str, tree: ast.AST, source_code: str) -> bool:
        user_input_patterns = {'request', 'form', 'args', 'get', 'post', 'input', 'argv', 'environ', 'file', 'path', 'filename', 'upload'}
        if var_name.lower() in user_input_patterns:
            return True
        # Check source code for common patterns
        if re.search(rf'\b{re.escape(var_name)}\s*=\s*request\.', source_code):
            return True
        if re.search(rf'\b{re.escape(var_name)}\s*=\s*input\(', source_code):
            return True
        if re.search(rf'\b{re.escape(var_name)}\s*=\s*sys\.argv', source_code):
            return True
        if re.search(rf'\b{re.escape(var_name)}\s*=\s*os\.environ', source_code):
            return True
        return False


class InsecureDeserializationRule(BaseSecurityRule):
    """Detects insecure deserialization vulnerabilities."""

    DANGEROUS_FUNCS = {
        'pickle.loads', 'pickle.load', 'cPickle.loads', 'cPickle.load',
        'shelve.open', 'shelve.DbfilenameShelf',
        'yaml.load', 'yaml.load_all',
        'marshal.load', 'marshal.loads',
        'PyYAML.load',
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "SEC-DESER-001"
        self._name = "Insecure Deserialization"
        self._description = "Detects use of insecure deserialization libraries like pickle"
        self._severity = "CRITICAL"
        self._languages = ["python"]
        self._cwe = "CWE-502"
        self._cvss = 9.8

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        result = SecurityRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            func_name = self._get_full_func_name(node)
            if func_name in self.DANGEROUS_FUNCS:
                line_no = node.lineno
                remediation_map = {
                    'pickle': "Use a safer serialization format like JSON or msgpack. Never unpickle untrusted data.",
                    'yaml': "Use yaml.safe_load() instead of yaml.load() to prevent arbitrary code execution.",
                    'marshal': "Avoid marshal for untrusted data. Use JSON or structured data formats.",
                    'shelve': "Avoid shelve for untrusted data. Use a database with proper access controls.",
                }

                library = 'pickle' if 'pickle' in func_name else 'yaml' if 'yaml' in func_name else 'marshal' if 'marshal' in func_name else 'shelve'
                remediation = remediation_map.get(library, "Avoid insecure deserialization of untrusted data.")

                issue = SecurityIssue(
                    rule_id=self.rule_id,
                    severity="CRITICAL",
                    message=f"Insecure deserialization: {func_name}() can execute arbitrary code at line {line_no}",
                    file_path=file_path,
                    line_number=line_no,
                    cwe=self.cwe,
                    cvss_score=self._cvss,
                    remediation=remediation,
                    snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                )
                result.issues.append(issue)

        return result

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


class HardcodedSecretsRule(BaseSecurityRule):
    """Detects hardcoded secrets, passwords, API keys, and tokens."""

    SECRET_PATTERNS = [
        re.compile(r'(?i)(password|passwd|pwd|secret|token|api_key|apikey|auth_token|access_key|secret_key|private_key)\s*[:=]\s*["\'][^"\'\s]+["\']'),
        re.compile(r'(?i)(?:A3T[A-Z0-9]|AKIA[0-9A-Z]{16}|SK[0-9a-fA-F]{32}|[0-9a-zA-Z/+]{40})'),  # AWS keys
        re.compile(r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----'),
        re.compile(r'ghp_[a-zA-Z0-9]{36}'),  # GitHub PAT
        re.compile(r'gho_[a-zA-Z0-9]{36}'),  # GitHub OAuth
        re.compile(r'xox[abarps]-[0-9a-zA-Z-]{10,}'),  # Slack tokens
        re.compile(r'sk-[a-zA-Z0-9]{32,}'),  # OpenAI keys
        re.compile(r'pk-[a-zA-Z0-9]{32,}'),  # OpenAI publishable keys
        re.compile(r'(?i)(jwt|JWT)\s*[:=]\s*["\'][A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+["\']'),
    ]

    SUSPICIOUS_VAR_NAMES = {
        'password', 'passwd', 'pwd', 'secret', 'token', 'api_key', 'apikey',
        'auth_token', 'access_key', 'secret_key', 'private_key', 'jwt_secret',
        'secret_key', 'encryption_key', 'db_password', 'db_user', 'mysql_pwd',
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "SEC-SECRET-001"
        self._name = "Hardcoded Secrets Detection"
        self._description = "Detects hardcoded passwords, API keys, tokens, and other secrets"
        self._severity = "CRITICAL"
        self._languages = ["python"]
        self._cwe = "CWE-798"
        self._cvss = 7.5

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        result = SecurityRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for i, line in enumerate(lines, 1):
            for pattern in self.SECRET_PATTERNS:
                match = pattern.search(line)
                if match:
                    issue = SecurityIssue(
                        rule_id=self.rule_id,
                        severity="CRITICAL",
                        message=f"Hardcoded secret detected at line {i}: potential {self._classify_secret(match.group())}",
                        file_path=file_path,
                        line_number=i,
                        column=match.start(),
                        end_line=i,
                        end_column=match.end(),
                        cwe=self.cwe,
                        cvss_score=self._cvss,
                        remediation="Store secrets in environment variables or a secrets manager. Never hardcode secrets in source code.",
                        snippet=line.strip(),
                        evidence={"match": match.group()[:50]},
                    )
                    result.issues.append(issue)
                    break

        # AST-based detection for variable assignments
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.lower() in self.SUSPICIOUS_VAR_NAMES:
                        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                            if len(node.value.value) > 8 and not node.value.value.startswith('$') and 'ENV' not in target.id.upper() and 'env' not in target.id.lower():
                                line_no = node.lineno
                                issue = SecurityIssue(
                                    rule_id=self.rule_id,
                                    severity="HIGH",
                                    message=f"Hardcoded secret: variable '{target.id}' assigned a string literal at line {line_no}",
                                    file_path=file_path,
                                    line_number=line_no,
                                    cwe=self.cwe,
                                    cvss_score=6.5,
                                    remediation=f"Move '{target.id}' to environment variables: os.getenv('{target.id.upper()}')",
                                    snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                                )
                                result.issues.append(issue)

        return result

    def _classify_secret(self, match: str) -> str:
        if '-----BEGIN' in match:
            return 'private key'
        if match.startswith('ghp_') or match.startswith('gho_'):
            return 'GitHub token'
        if match.startswith('AKIA') or 'A3T' in match[:4]:
            return 'AWS access key'
        if match.startswith('xox'):
            return 'Slack token'
        if match.startswith('sk-'):
            return 'OpenAI API key'
        if match.startswith('pk-'):
            return 'OpenAI publishable key'
        if 'password' in match.lower() or 'passwd' in match.lower():
            return 'password'
        if 'token' in match.lower() or 'jwt' in match.lower() or 'JWT' in match:
            return 'auth token'
        if 'api_key' in match.lower() or 'apikey' in match.lower():
            return 'API key'
        if 'secret' in match.lower():
            return 'secret key'
        return 'credential'


class WeakCryptoRule(BaseSecurityRule):
    """Detects use of weak or deprecated cryptographic algorithms."""

    WEAK_ALGORITHMS = {
        'md5', 'sha1', 'sha-1', 'des', '3des', 'rc2', 'rc4', 'blowfish',
        'ecb', 'pkcs1v15', 'pbkdf2_sha1',
    }

    DANGEROUS_FUNCS = {
        'hashlib.md5', 'hashlib.sha1', 'Crypto.Cipher.DES', 'Crypto.Cipher.ARC4',
        'Crypto.Cipher.Blowfish', 'Cryptodome.Cipher.DES', 'Cryptodome.Cipher.ARC4',
    }

    DANGEROUS_NAMES = {'md5', 'sha1'}

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "SEC-CRYPTO-001"
        self._name = "Weak Cryptography Detection"
        self._description = "Detects use of weak or deprecated cryptographic algorithms"
        self._severity = "HIGH"
        self._languages = ["python"]
        self._cwe = "CWE-327"
        self._cvss = 7.4

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        result = SecurityRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = self._get_full_func_name(node)
                if any(weak in func_name.lower() for weak in self.WEAK_ALGORITHMS):
                    if 'sha256' in func_name.lower() or 'sha512' in func_name.lower() or 'sha3' in func_name.lower():
                        continue
                    line_no = node.lineno
                    algorithm = self._identify_algorithm(func_name)
                    issue = SecurityIssue(
                        rule_id=self.rule_id,
                        severity="HIGH",
                        message=f"Weak cryptographic algorithm '{algorithm}' used at line {line_no}",
                        file_path=file_path,
                        line_number=line_no,
                        cwe=self.cwe,
                        cvss_score=self._cvss,
                        remediation=f"Replace {algorithm} with a strong algorithm: SHA-256/SHA-3 for hashing, AES-GCM for encryption",
                        snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                    )
                    result.issues.append(issue)

            # Check for ECB mode in cipher operations
            if isinstance(node, ast.Attribute):
                if node.attr == 'ECB' or node.attr == 'MODE_ECB':
                    line_no = node.lineno
                    issue = SecurityIssue(
                        rule_id=self.rule_id,
                        severity="CRITICAL",
                        message=f"ECB encryption mode detected at line {line_no}. ECB is deterministic and not semantically secure.",
                        file_path=file_path,
                        line_number=line_no,
                        cwe="CWE-327",
                        cvss_score=8.0,
                        remediation="Use AES-GCM or AES-CBC with a random IV instead of ECB mode",
                        snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                    )
                    result.issues.append(issue)

        return result

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

    def _identify_algorithm(self, func_name: str) -> str:
        lower = func_name.lower()
        if 'md5' in lower:
            return 'MD5'
        if 'sha1' in lower or 'sha-1' in lower:
            return 'SHA-1'
        if 'des' in lower:
            return 'DES'
        if 'rc4' in lower or 'arc4' in lower:
            return 'RC4'
        if 'blowfish' in lower:
            return 'Blowfish'
        if 'ecb' in lower:
            return 'ECB'
        return func_name


class SSRFDetectionRule(BaseSecurityRule):
    """Detects Server-Side Request Forgery vulnerabilities."""

    HTTP_LIBS = {'requests', 'urllib', 'httpx', 'aiohttp', 'http.client', 'httplib'}
    DANGEROUS_FUNCS = {
        'requests.get', 'requests.post', 'requests.put', 'requests.delete', 'requests.patch',
        'requests.request', 'urllib.request.urlopen', 'urllib.urlopen',
        'httpx.get', 'httpx.post', 'httpx.put', 'httpx.delete', 'httpx.patch', 'httpx.request',
        'aiohttp.ClientSession.get', 'aiohttp.ClientSession.post',
        'urlopen', 'urlretrieve',
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "SEC-SSRF-001"
        self._name = "SSRF Detection"
        self._description = "Detects Server-Side Request Forgery vulnerabilities from user-controlled URLs"
        self._severity = "HIGH"
        self._languages = ["python"]
        self._cwe = "CWE-918"
        self._cvss = 8.6

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        result = SecurityRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            func_name = self._get_full_func_name(node)
            if func_name not in self.DANGEROUS_FUNCS and node.func.attr if isinstance(node.func, ast.Attribute) and node.func.attr in ('get', 'post', 'put', 'delete', 'patch', 'request', 'urlopen') else False:
                continue

            if not node.args:
                continue

            url_arg = node.args[0] if func_name in self.DANGEROUS_FUNCS else node.args[0]
            line_no = node.lineno

            if isinstance(url_arg, (ast.Name, ast.Attribute)):
                var_name = self._get_var_name(url_arg)
                if var_name and self._is_user_controlled(var_name, source_code):
                    issue = SecurityIssue(
                        rule_id=self.rule_id,
                        severity="HIGH",
                        message=f"SSRF vulnerability: user-controlled URL '{var_name}' passed to {func_name}() at line {line_no}",
                        file_path=file_path,
                        line_number=line_no,
                        cwe=self.cwe,
                        cvss_score=self._cvss,
                        remediation="Validate URLs against a whitelist of allowed hosts. Avoid passing user input directly to HTTP request functions.",
                        snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                    )
                    result.issues.append(issue)

            if isinstance(url_arg, (ast.JoinedStr, ast.BinOp)):
                issue = SecurityIssue(
                    rule_id=self.rule_id,
                    severity="HIGH",
                    message=f"SSRF vulnerability: dynamically constructed URL in {func_name}() at line {line_no}",
                    file_path=file_path,
                    line_number=line_no,
                    cwe=self.cwe,
                    cvss_score=self._cvss,
                    remediation="Use a URL whitelist or validate the hostname against allowed domains",
                    snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                )
                result.issues.append(issue)

        return result

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

    def _get_var_name(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def _is_user_controlled(self, var_name: str, source_code: str) -> bool:
        user_patterns = {'request', 'form', 'args', 'get', 'post', 'input', 'argv', 'url', 'link', 'href', 'redirect', 'next', 'return_url', 'callback'}
        if var_name.lower() in user_patterns:
            return True
        if re.search(rf'\b{re.escape(var_name)}\s*=\s*request\.', source_code):
            return True
        if re.search(rf'\b{re.escape(var_name)}\s*=\s*input\(', source_code):
            return True
        if re.search(rf'\b{re.escape(var_name)}\s*=\s*sys\.argv', source_code):
            return True
        return False


class LooseCSPRule(BaseSecurityRule):
    """Detects overly permissive Content Security Policy configurations."""

    CSP_PATTERNS = [
        re.compile(r"default-src\s+'\*'"),
        re.compile(r"script-src\s+'\*'"),
        re.compile(r"script-src\s+(?!.*'nonce-)(?!.*'sha256-)'unsafe-inline'"),
        re.compile(r"script-src\s+'\*'\s+'\*'"),
        re.compile(r"object-src\s+'\*'"),
        re.compile(r"frame-ancestors\s+'\*'"),
        re.compile(r"base-uri\s+'\*'"),
        re.compile(r"form-action\s+'\*'"),
    ]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "SEC-CSP-001"
        self._name = "Loose Content Security Policy"
        self._description = "Detects overly permissive CSP headers that weaken XSS protection"
        self._severity = "MEDIUM"
        self._languages = ["python"]
        self._cwe = "CWE-1021"
        self._cvss = 5.4

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        result = SecurityRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for i, line in enumerate(lines, 1):
            for pattern in self.CSP_PATTERNS:
                if pattern.search(line):
                    issue = SecurityIssue(
                        rule_id=self.rule_id,
                        severity="MEDIUM",
                        message=f"Overly permissive CSP directive at line {i}: '{pattern.pattern}'",
                        file_path=file_path,
                        line_number=i,
                        cwe=self.cwe,
                        cvss_score=self._cvss,
                        remediation="Use strict CSP with nonces or hashes for scripts. Avoid wildcard (*) in script-src, default-src, and object-src.",
                        snippet=line.strip(),
                        evidence={"directive": pattern.pattern},
                    )
                    result.issues.append(issue)
                    break

        return result


class SecurityMisconfigRule(BaseSecurityRule):
    """Detects common security misconfigurations."""

    DANGEROUS_SETTINGS = {
        'DEBUG': True,
        'SECRET_KEY': 'secret',
        'ALLOWED_HOSTS': ['*'],
        'CORS_ORIGIN_ALLOW_ALL': True,
        'CORS_ALLOW_ALL_ORIGINS': True,
        'SESSION_COOKIE_SECURE': False,
        'SESSION_COOKIE_HTTPONLY': False,
        'SESSION_COOKIE_SAMESITE': None,
        'CSRF_COOKIE_SECURE': False,
        'CSRF_COOKIE_HTTPONLY': False,
        'SECURE_SSL_REDIRECT': False,
        'SECURE_HSTS_SECONDS': 0,
        'SECURE_BROWSER_XSS_FILTER': False,
        'SECURE_CONTENT_TYPE_NOSNIFF': False,
        'X_FRAME_OPTIONS': 'DENY' if False else None,
    }

    SETTING_PATTERNS = [
        (re.compile(r'\bDEBUG\s*=\s*True'), "Debug mode enabled in production", "CRITICAL", 9.0),
        (re.compile(r'\bSECRET_KEY\s*=\s*["\']secret["\']'), "Default secret key", "CRITICAL", 9.8),
        (re.compile(r'\bALLOWED_HOSTS\s*=\s*\[\s*["\']\*["\']\s*\]'), "Wildcard ALLOWED_HOSTS", "HIGH", 7.5),
        (re.compile(r'\bCORS_ORIGIN_ALLOW_ALL\s*=\s*True'), "CORS allowing all origins", "HIGH", 7.5),
        (re.compile(r'\bCORS_ALLOW_ALL_ORIGINS\s*=\s*True'), "CORS allowing all origins", "HIGH", 7.5),
        (re.compile(r'\bSESSION_COOKIE_SECURE\s*=\s*False'), "Session cookie without Secure flag", "MEDIUM", 5.9),
        (re.compile(r'\bSESSION_COOKIE_HTTPONLY\s*=\s*False'), "Session cookie without HttpOnly flag", "MEDIUM", 5.3),
        (re.compile(r'\bSESSION_COOKIE_SAMESITE\s*=\s*["\'](?:None|none)["\']'), "Session cookie SameSite=None without Secure", "MEDIUM", 4.3),
        (re.compile(r'\bSECURE_SSL_REDIRECT\s*=\s*False'), "SSL redirect disabled", "MEDIUM", 4.8),
        (re.compile(r'\bSECURE_HSTS_SECONDS\s*=\s*0'), "HSTS disabled", "LOW", 3.7),
        (re.compile(r'\bSECURE_BROWSER_XSS_FILTER\s*=\s*False'), "Browser XSS filter disabled", "MEDIUM", 4.3),
        (re.compile(r'\bSECURE_CONTENT_TYPE_NOSNIFF\s*=\s*False'), "Content-Type sniffing protection disabled", "MEDIUM", 4.3),
        (re.compile(r'\bX_FRAME_OPTIONS\s*=\s*["\'](?:ALLOW|SAMEORIGIN)["\']'), "Permissive X-Frame-Options", "MEDIUM", 4.3),
    ]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "SEC-CONFIG-001"
        self._name = "Security Misconfiguration"
        self._description = "Detects insecure configuration settings"
        self._severity = "HIGH"
        self._languages = ["python"]
        self._cwe = "CWE-16"
        self._cvss = 7.5

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        result = SecurityRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for i, line in enumerate(lines, 1):
            for pattern, message, severity, cvss in self.SETTING_PATTERNS:
                if pattern.search(line):
                    issue = SecurityIssue(
                        rule_id=self.rule_id,
                        severity=severity,
                        message=f"{message} at line {i}",
                        file_path=file_path,
                        line_number=i,
                        cwe=self.cwe,
                        cvss_score=cvss,
                        remediation=f"Fix this configuration: {self._get_remediation(pattern)}",
                        snippet=line.strip(),
                    )
                    result.issues.append(issue)
                    break

        return result

    def _get_remediation(self, pattern: re.Pattern) -> str:
        mapping = {
            r'\bDEBUG\s*=\s*True': "Set DEBUG=False in production",
            r'\bSECRET_KEY\s*=\s*["\']secret["\']': "Generate a strong random SECRET_KEY and store in environment variables",
            r'\bALLOWED_HOSTS\s*=\s*\[\s*["\']\*["\']\s*\]': "List specific allowed hosts instead of wildcard",
            r'\bCORS_ORIGIN_ALLOW_ALL\s*=\s*True': "Allow only specific origins in CORS",
            r'\bCORS_ALLOW_ALL_ORIGINS\s*=\s*True': "Allow only specific origins in CORS",
            r'\bSESSION_COOKIE_SECURE\s*=\s*False': "Set SESSION_COOKIE_SECURE=True in production",
            r'\bSESSION_COOKIE_HTTPONLY\s*=\s*False': "Set SESSION_COOKIE_HTTPONLY=True",
            r'\bSECURE_SSL_REDIRECT\s*=\s*False': "Set SECURE_SSL_REDIRECT=True in production",
            r'\bSECURE_HSTS_SECONDS\s*=\s*0': "Set SECURE_HSTS_SECONDS to a positive value (e.g., 31536000)",
            r'\bSECURE_BROWSER_XSS_FILTER\s*=\s*False': "Set SECURE_BROWSER_XSS_FILTER=True",
            r'\bSECURE_CONTENT_TYPE_NOSNIFF\s*=\s*False': "Set SECURE_CONTENT_TYPE_NOSNIFF=True",
        }
        for pat, remediation in mapping.items():
            if re.match(pat, pattern.pattern):
                return remediation
        return "Review and fix the insecure configuration"


class InsecureRedirectRule(BaseSecurityRule):
    """Detects open redirect vulnerabilities."""

    REDIRECT_FUNCS = {'redirect', 'HttpResponseRedirect', 'HttpResponsePermanentRedirect', 'redirect_to', 'url_for', 'Location'}
    UNSAFE_PATTERNS = [
        re.compile(r'redirect\s*\(\s*request\.'),
        re.compile(r'redirect\s*\(\s*\w+\s*\)'),
        re.compile(r'next\s*=\s*request\.args'),
        re.compile(r'return_url\s*=\s*request\.'),
        re.compile(r'Location\s*:\s*[\'"]\s*\+\s*\w+'),
    ]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "SEC-REDIR-001"
        self._name = "Open Redirect Detection"
        self._description = "Detects open redirect vulnerabilities from user-controlled redirect targets"
        self._severity = "MEDIUM"
        self._languages = ["python"]
        self._cwe = "CWE-601"
        self._cvss = 6.1

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        result = SecurityRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr

            if func_name not in self.REDIRECT_FUNCS:
                continue

            if not node.args:
                continue

            target = node.args[0]
            line_no = node.lineno

            if isinstance(target, (ast.Name, ast.Attribute)):
                var_name = self._get_var_name(target)
                if var_name and self._is_user_input(var_name, source_code):
                    issue = SecurityIssue(
                        rule_id=self.rule_id,
                        severity="MEDIUM",
                        message=f"Open redirect: user-controlled redirect target '{var_name}' at line {line_no}",
                        file_path=file_path,
                        line_number=line_no,
                        cwe=self.cwe,
                        cvss_score=self._cvss,
                        remediation="Validate redirect targets against a whitelist of allowed URLs. Use url_for() with named routes instead of user-provided URLs.",
                        snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                    )
                    result.issues.append(issue)

            if isinstance(target, (ast.JoinedStr, ast.BinOp)):
                issue = SecurityIssue(
                    rule_id=self.rule_id,
                    severity="MEDIUM",
                    message=f"Open redirect: dynamically constructed redirect URL at line {line_no}",
                    file_path=file_path,
                    line_number=line_no,
                    cwe=self.cwe,
                    cvss_score=self._cvss,
                    remediation="Use url_for() with named routes instead of dynamic URLs for redirects",
                    snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                )
                result.issues.append(issue)

        return result

    def _get_var_name(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def _is_user_input(self, var_name: str, source_code: str) -> bool:
        if re.search(rf'\b{re.escape(var_name)}\s*=\s*request\.', source_code):
            return True
        if re.search(rf'\b{re.escape(var_name)}\s*=\s*input\(', source_code):
            return True
        if var_name.lower() in ('url', 'next', 'redirect', 'return_url', 'callback', 'target', 'dest'):
            return True
        return False


class LogInjectionRule(BaseSecurityRule):
    """Detects log injection vulnerabilities (log forging)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "SEC-LOG-001"
        self._name = "Log Injection Detection"
        self._description = "Detects log injection vulnerabilities from unsanitized user input in log statements"
        self._severity = "MEDIUM"
        self._languages = ["python"]
        self._cwe = "CWE-117"
        self._cvss = 5.3

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        result = SecurityRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        LOG_FUNCS = {'logging.info', 'logging.debug', 'logging.warning', 'logging.error', 'logging.critical', 'logger.info', 'logger.debug', 'logger.warning', 'logger.error', 'logger.critical', 'print', 'log.info', 'log.debug', 'log.warning', 'log.error', 'log.critical'}
        LOG_PATTERN = re.compile(r'(?:logger|logging|log)\.(?:info|debug|warning|error|critical)\s*\(f["\']')

        for i, line in enumerate(lines, 1):
            if LOG_PATTERN.search(line):
                # Check if f-string contains user input
                if re.search(r'\{[^}]*request\.|\{[^}]*form\[|\{[^}]*args\[|\{[^}]*input\(', line):
                    issue = SecurityIssue(
                        rule_id=self.rule_id,
                        severity="MEDIUM",
                        message=f"Log injection: f-string in log statement may contain unsanitized user input at line {i}",
                        file_path=file_path,
                        line_number=i,
                        cwe=self.cwe,
                        cvss_score=self._cvss,
                        remediation="Sanitize or encode user input before logging. Use %s formatting with string substitution instead of f-strings.",
                        snippet=line.strip(),
                    )
                    result.issues.append(issue)

        # AST-based check
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func_name = self._get_full_func_name(node)
            if func_name not in LOG_FUNCS:
                continue
            if not node.args:
                continue
            msg_arg = node.args[0]
            if isinstance(msg_arg, ast.JoinedStr):
                has_user_input = False
                for value in msg_arg.values:
                    if isinstance(value, ast.FormattedValue):
                        if isinstance(value.value, ast.Attribute):
                            if isinstance(value.value.value, ast.Name) and value.value.value.id == 'request':
                                has_user_input = True
                        if isinstance(value.value, ast.Name):
                            var_name = value.value.id
                            if re.search(rf'\b{re.escape(var_name)}\s*=\s*request\.', source_code):
                                has_user_input = True
                if has_user_input:
                    issue = SecurityIssue(
                        rule_id=self.rule_id,
                        severity="MEDIUM",
                        message=f"Log injection: f-string in log may contain user-controlled data at line {node.lineno}",
                        file_path=file_path,
                        line_number=node.lineno,
                        cwe=self.cwe,
                        cvss_score=self._cvss,
                        remediation="Avoid logging user-controlled data directly. Sanitize or encode input before logging.",
                        snippet=lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                    )
                    result.issues.append(issue)

        return result

    def _get_full_func_name(self, node: ast.Call) -> str:
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                return f"{node.func.value.id}.{node.func.attr}"
            return node.func.attr
        if isinstance(node.func, ast.Name):
            return node.func.id
        return ""


class InsecureDirectObjectReferenceRule(BaseSecurityRule):
    """Detects Insecure Direct Object Reference (IDOR) vulnerabilities."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "SEC-IDOR-001"
        self._name = "Insecure Direct Object Reference"
        self._description = "Detects potential IDOR vulnerabilities where user-controlled IDs are used without authorization checks"
        self._severity = "HIGH"
        self._languages = ["python"]
        self._cwe = "CWE-639"
        self._cvss = 7.5

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        result = SecurityRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func_name = ""
            if isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            elif isinstance(node.func, ast.Name):
                func_name = node.func.id

            if func_name not in ('get', 'filter', 'first_or_404', 'get_or_404', 'query', 'find', 'find_by_id', 'find_by_pk'):
                continue

            if not node.args:
                continue

            id_arg = node.args[0]
            line_no = node.lineno

            if isinstance(id_arg, (ast.Name, ast.Attribute)):
                var_name = self._get_var_name(id_arg)
                if var_name and self._is_id_from_request(var_name, source_code, tree):
                    # Check if there's an authorization check before this call
                    if not self._has_auth_check_before(node, tree):
                        issue = SecurityIssue(
                            rule_id=self.rule_id,
                            severity="HIGH",
                            message=f"Potential IDOR: user-controlled object ID '{var_name}' used in {func_name}() without authorization check at line {line_no}",
                            file_path=file_path,
                            line_number=line_no,
                            cwe=self.cwe,
                            cvss_score=self._cvss,
                            remediation="Verify that the authenticated user has permission to access the requested object. Implement ownership checks or authorization gates.",
                            snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                        )
                        result.issues.append(issue)

        return result

    def _get_var_name(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def _is_id_from_request(self, var_name: str, source_code: str, tree: ast.AST) -> bool:
        if re.search(rf'\b{re.escape(var_name)}\s*=\s*request\.(args|form|json|view_args)\s*\[', source_code):
            return True
        if re.search(rf'\b{re.escape(var_name)}\s*=\s*request\.(args|form|json|view_args)\.get\(', source_code):
            return True
        if re.search(rf'\b{re.escape(var_name)}\s*=\s*request\.get_json\(\)', source_code):
            return True
        if re.search(rf'\b{re.escape(var_name)}\s*=\s*request\.(args|form|json|view_args)\.get\("', source_code):
            return True
        if var_name.lower() in ('id', 'pk', 'pk_id', 'user_id', 'object_id', 'item_id', 'resource_id', 'uid', 'guid'):
            return True
        return False

    def _has_auth_check_before(self, node: ast.AST, tree: ast.AST) -> bool:
        current_func = None
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(n):
                    if child is node:
                        current_func = n
                        break
                if current_func:
                    break

        if current_func is None:
            return False

        # Check for decorator-based auth
        for decorator in current_func.decorator_list:
            dec_name = ""
            if isinstance(decorator, ast.Name):
                dec_name = decorator.id
            elif isinstance(decorator, ast.Attribute):
                dec_name = decorator.attr
            if dec_name in ('login_required', 'permission_required', 'user_passes_test', 'has_permission', 'authorization_required', 'auth_required', 'require_auth'):
                return True

        # Check for auth checks in the function body
        body = current_func.body
        for stmt in body:
            if isinstance(stmt, ast.If):
                # Simple check for authorization conditions
                test_source = ast.unparse(stmt.test) if hasattr(ast, 'unparse') else ""
                auth_keywords = ['current_user', 'user', 'permission', 'role', 'is_authenticated', 'is_admin', 'has_permission', 'can_access', 'is_owner', 'authorize', 'check_permission']
                for kw in auth_keywords:
                    if kw in test_source.lower():
                        return True
            if isinstance(stmt, ast.Call):
                call_name = ast.unparse(stmt.func) if hasattr(ast, 'unparse') else ""
                auth_funcs = ['check_permission', 'authorize', 'require_auth', 'has_permission']
                for af in auth_funcs:
                    if af in call_name:
                        return True

        return False


class CSRFProtectionRule(BaseSecurityRule):
    """Detects missing CSRF protection."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "SEC-CSRF-001"
        self._name = "Missing CSRF Protection"
        self._description = "Detects endpoints and forms missing CSRF protection"
        self._severity = "MEDIUM"
        self._languages = ["python"]
        self._cwe = "CWE-352"
        self._cvss = 6.5

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        result = SecurityRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        CSRF_EXEMPT_PATTERN = re.compile(r'@.*csrf_exempt|@.*csrf\.exempt')
        CSRF_DISABLED_PATTERN = re.compile(r'CSRF_COOKIE_SECURE|WTF_CSRF_ENABLED\s*=\s*False')

        # Check for csrf_exempt decorators
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    dec_name = ""
                    if isinstance(decorator, ast.Name):
                        dec_name = decorator.id
                    elif isinstance(decorator, ast.Attribute):
                        dec_name = decorator.attr
                    if 'csrf_exempt' in dec_name or 'csrf' in dec_name:
                        line_no = decorator.lineno if hasattr(decorator, 'lineno') else node.lineno
                        issue = SecurityIssue(
                            rule_id=self.rule_id,
                            severity="MEDIUM",
                            message=f"CSRF protection disabled: @{dec_name} decorator on '{node.name}' at line {line_no}",
                            file_path=file_path,
                            line_number=line_no,
                            cwe=self.cwe,
                            cvss_score=self._cvss,
                            remediation="Avoid using @csrf_exempt. Use CSRF tokens for all state-changing operations. If truly needed, implement alternative CSRF protection.",
                            snippet=lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                        )
                        result.issues.append(issue)

        # Check for CSRF disabled in config
        for i, line in enumerate(lines, 1):
            match = CSRF_DISABLED_PATTERN.search(line)
            if match:
                issue = SecurityIssue(
                    rule_id=self.rule_id,
                    severity="MEDIUM",
                    message=f"CSRF protection may be disabled at line {i}",
                    file_path=file_path,
                    line_number=i,
                    cwe=self.cwe,
                    cvss_score=self._cvss,
                    remediation="Enable CSRF protection. Set WTF_CSRF_ENABLED=True and ensure all forms include CSRF tokens.",
                    snippet=line.strip(),
                )
                result.issues.append(issue)

        return result


class NoSQLInjectionRule(BaseSecurityRule):
    """Detects NoSQL injection vulnerabilities."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "SEC-NOSQL-001"
        self._name = "NoSQL Injection Detection"
        self._description = "Detects potential NoSQL injection vulnerabilities in MongoDB and other NoSQL databases"
        self._severity = "HIGH"
        self._languages = ["python"]
        self._cwe = "CWE-943"
        self._cvss = 8.1

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        result = SecurityRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        DANGEROUS_PATTERNS = [
            (re.compile(r'\.find\s*\(\s*\{.*?request\.'), "User input in MongoDB find() query"),
            (re.compile(r'\.find_one\s*\(\s*\{.*?request\.'), "User input in MongoDB find_one() query"),
            (re.compile(r'\.find\s*\(\s*\{.*?form\['), "Form input in MongoDB find() query"),
            (re.compile(r'\.aggregate\s*\(\s*\[.*?request\.'), "User input in MongoDB aggregate() query"),
            (re.compile(r'\.insert_one\s*\(\s*\{.*?request\.'), "User input in MongoDB insert_one() query"),
            (re.compile(r'\.update_one\s*\(\s*\{.*?request\.'), "User input in MongoDB update_one() query"),
            (re.compile(r'\.delete_one\s*\(\s*\{.*?request\.'), "User input in MongoDB delete_one() query"),
            (re.compile(r'\$where\s*:'), "Dangerous $where operator in MongoDB query"),
            (re.compile(r'\$where\s*:'), "Dangerous $where operator"),
        ]

        for i, line in enumerate(lines, 1):
            for pattern, message in DANGEROUS_PATTERNS:
                if pattern.search(line):
                    issue = SecurityIssue(
                        rule_id=self.rule_id,
                        severity="HIGH",
                        message=f"Potential NoSQL injection: {message} at line {i}",
                        file_path=file_path,
                        line_number=i,
                        cwe=self.cwe,
                        cvss_score=self._cvss,
                        remediation="Sanitize and validate user input before using in NoSQL queries. Use a schema validation library. Avoid using $where operator.",
                        snippet=line.strip(),
                    )
                    result.issues.append(issue)
                    break

        return result


class LDAPInjectionRule(BaseSecurityRule):
    """Detects LDAP injection vulnerabilities."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "SEC-LDAP-001"
        self._name = "LDAP Injection Detection"
        self._description = "Detects potential LDAP injection vulnerabilities"
        self._severity = "HIGH"
        self._languages = ["python"]
        self._cwe = "CWE-90"
        self._cvss = 8.1

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        result = SecurityRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        LDAP_FUNCS = {'ldap.initialize', 'ldap.open', 'ldap.simple_bind', 'ldap.bind_s', 'ldap.search', 'ldap.search_s', 'ldap.search_st'}
        LDAP_USER_PATTERN = re.compile(r'(?:ldap|conn|con|ldap_conn)\.(?:search|search_s|search_st|simple_bind|bind_s)\s*\(.*?(?:user|username|uid|cn|dn|filter)\s*[=+].*?(?:request\.|form\[|args\[|input\()')

        for i, line in enumerate(lines, 1):
            if LDAP_USER_PATTERN.search(line):
                issue = SecurityIssue(
                    rule_id=self.rule_id,
                    severity="HIGH",
                    message=f"Potential LDAP injection: user input in LDAP search/bind at line {i}",
                    file_path=file_path,
                    line_number=i,
                    cwe=self.cwe,
                    cvss_score=self._cvss,
                    remediation="Use LDAP escaping functions (e.g., ldap.filter.escape_filter_chars) for all user-supplied values in LDAP queries",
                    snippet=line.strip(),
                )
                result.issues.append(issue)

        # AST-based check
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func_name = ""
            if isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == 'ldap':
                    func_name = f"ldap.{node.func.attr}"
            if func_name not in LDAP_FUNCS:
                continue
            if not node.args:
                continue
            for arg in node.args:
                if isinstance(arg, (ast.Name, ast.Attribute, ast.JoinedStr, ast.BinOp)):
                    line_no = node.lineno
                    issue = SecurityIssue(
                        rule_id=self.rule_id,
                        severity="HIGH",
                        message=f"LDAP injection: dynamic input in {func_name}() at line {line_no}",
                        file_path=file_path,
                        line_number=line_no,
                        cwe=self.cwe,
                        cvss_score=self._cvss,
                        remediation="Escape all user-supplied values using ldap.filter.escape_filter_chars()",
                        snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                    )
                    result.issues.append(issue)
                    break

        return result


class XMLExternalEntityRule(BaseSecurityRule):
    """Detects XML External Entity (XXE) vulnerabilities."""

    XXE_LIBS = {'xml.dom.minidom', 'xml.dom.pulldom', 'xml.sax', 'xml.parsers.expat', 'lxml', 'xml.etree.ElementTree', 'xmlrpc'}

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "SEC-XXE-001"
        self._name = "XML External Entity (XXE) Detection"
        self._description = "Detects XML External Entity processing vulnerabilities"
        self._severity = "HIGH"
        self._languages = ["python"]
        self._cwe = "CWE-611"
        self._cvss = 8.6

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        result = SecurityRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        # Check for unsafe XML parsing
        UNSAFE_XML_PATTERNS = [
            re.compile(r'xml\.dom\.minidom\.parse\s*\('),
            re.compile(r'xml\.dom\.minidom\.parseString\s*\('),
            re.compile(r'xml\.sax\.make_parser\s*\('),
            re.compile(r'xml\.parsers\.expat\.ParserCreate\s*\('),
            re.compile(r'lxml\.etree\.parse\s*\('),
            re.compile(r'lxml\.etree\.fromstring\s*\('),
            re.compile(r'xml\.etree\.ElementTree\.parse\s*\('),
            re.compile(r'xml\.etree\.ElementTree\.fromstring\s*\('),
            re.compile(r'xmlrpc\.client\.ServerProxy\s*\('),
            re.compile(r'xmlrpc\.server\.SimpleXMLRPCServer\s*\('),
        ]

        for i, line in enumerate(lines, 1):
            for pattern in UNSAFE_XML_PATTERNS:
                if pattern.search(line):
                    # Check if there's a resolve_entities=False or no_defdtd=False setting
                    if 'resolve_entities' not in line and 'no_defdtd' not in line:
                        issue = SecurityIssue(
                            rule_id=self.rule_id,
                            severity="HIGH",
                            message=f"Potential XXE vulnerability: XML parsing without disabling external entities at line {i}",
                            file_path=file_path,
                            line_number=i,
                            cwe=self.cwe,
                            cvss_score=self._cvss,
                            remediation="Configure the XML parser to disable external entities: e.g., parser = ET.XMLParser(resolve_entities=False)",
                            snippet=line.strip(),
                        )
                        result.issues.append(issue)
                        break

        # Check for imports of vulnerable XML libraries without proper configuration
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    lib_name = alias.name
                    if any(xxe_lib in lib_name for xxe_lib in self.XXE_LIBS):
                        line_no = node.lineno
                        # Check if the code also sets up secure parsing
                        if not self._has_secure_xml_config(tree):
                            issue = SecurityIssue(
                                rule_id=self.rule_id,
                                severity="MEDIUM",
                                message=f"XML library '{lib_name}' imported at line {line_no} without secure parser configuration",
                                file_path=file_path,
                                line_number=line_no,
                                cwe=self.cwe,
                                cvss_score=6.5,
                                remediation="Configure the XML parser to disable external entities and DTD processing",
                                snippet=lines[line_no - 1] if line_no <= len(lines) else "",
                            )
                            result.issues.append(issue)

        return result

    def _has_secure_xml_config(self, tree: ast.AST) -> bool:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords if hasattr(node, 'keywords') else []:
                    if kw.arg in ('resolve_entities', 'no_defdtd', 'dtd_validation') and isinstance(kw.value, ast.Constant) and kw.value.value is False:
                        return True
        return False


class RaceConditionRule(BaseSecurityRule):
    """Detects race condition vulnerabilities in Python."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "SEC-RACE-001"
        self._name = "Race Condition Detection"
        self._description = "Detects potential race conditions in file operations, database transactions, and shared state"
        self._severity = "MEDIUM"
        self._languages = ["python"]
        self._cwe = "CWE-362"
        self._cvss = 5.9

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        result = SecurityRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        TOCTOU_PATTERN = re.compile(r'(?:os\.path\.exists|os\.path\.isfile|os\.path\.islink|os\.access)\s*\(.*?\).*?(?:\n.*?){0,5}(?:os\.remove|os\.rename|open\s*\(|os\.open)')

        for i, line in enumerate(lines, 1):
            if TOCTOU_PATTERN.search(line):
                issue = SecurityIssue(
                    rule_id=self.rule_id,
                    severity="MEDIUM",
                    message=f"TOCTOU (Time-of-Check Time-of-Use) race condition at line {i}",
                    file_path=file_path,
                    line_number=i,
                    cwe=self.cwe,
                    cvss_score=self._cvss,
                    remediation="Use atomic file operations. Instead of check-then-act, use try-except around the operation. Use os.replace() for atomic renames.",
                    snippet=line.strip(),
                )
                result.issues.append(issue)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                has_file_check = False
                has_file_use = False
                check_line = 0
                for child in ast.walk(node):
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                        if child.func.attr in ('exists', 'isfile', 'islink', 'access') and isinstance(child.func.value, ast.Name) and child.func.value.id == 'os':
                            has_file_check = True
                            check_line = child.lineno
                        if child.func.attr in ('remove', 'unlink', 'rename', 'replace') and isinstance(child.func.value, ast.Name) and child.func.value.id == 'os':
                            has_file_use = True
                        if child.func.attr == 'open' and child.func.value.id == 'os' if isinstance(child.func.value, ast.Name) else False:
                            has_file_use = True
                if has_file_check and has_file_use:
                    issue = SecurityIssue(
                        rule_id=self.rule_id,
                        severity="MEDIUM",
                        message=f"TOCTOU race condition: file check before use in function '{node.name}'",
                        file_path=file_path,
                        line_number=check_line,
                        cwe=self.cwe,
                        cvss_score=self._cvss,
                        remediation="Use try-except to handle the file operation directly instead of checking first",
                        snippet=lines[check_line - 1] if check_line <= len(lines) else "",
                    )
                    result.issues.append(issue)

        # Check for shared state without locks
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                body_text = ast.unparse(node) if hasattr(ast, 'unparse') else ""
                has_shared_state = any(kw in body_text for kw in ['global ', 'self.counter', 'self.count', 'self.state', 'shared_'])
                has_lock = any(kw in body_text for kw in ['threading.Lock', 'asyncio.Lock', 'with lock', '.acquire()', '.release()'])
                if has_shared_state and not has_lock:
                    has_async = any(isinstance(n, ast.AsyncFunctionDef) or (isinstance(n, ast.Call) and hasattr(n.func, 'attr') and n.func.attr in ('gather', 'create_task', 'ensure_future')) for n in ast.walk(node))
                    if has_async:
                        issue = SecurityIssue(
                            rule_id=self.rule_id,
                            severity="MEDIUM",
                            message=f"Potential race condition: shared state in function '{node.name}' without proper synchronization",
                            file_path=file_path,
                            line_number=node.lineno,
                            cwe=self.cwe,
                            cvss_score=5.5,
                            remediation="Protect shared state with threading.Lock() or asyncio.Lock() when accessed from multiple threads/tasks",
                            snippet=lines[node.lineno - 1] if node.lineno <= len(lines) else "",
                        )
                        result.issues.append(issue)

        return result


# ---------------------------------------------------------------------------
# C-specific security rules
# ---------------------------------------------------------------------------

class CSecurityRules(BaseSecurityRule):
    """Security analysis for C code (buffer overflow, format string, etc.)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "SEC-C-001"
        self._name = "C Security Rules"
        self._description = "Detects memory safety and security issues in C code"
        self._severity = "CRITICAL"
        self._languages = ["c"]
        self._cwe = "CWE-120"
        self._cvss = 9.0

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        result = SecurityRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        DANGEROUS_C_FUNCS = [
            (re.compile(r'\bstrcpy\s*\('), "strcpy() does not check buffer bounds", "CRITICAL", 9.3, "Use strncpy() or snprintf() with explicit size limits"),
            (re.compile(r'\bstrcat\s*\('), "strcat() does not check buffer bounds", "CRITICAL", 9.3, "Use strncat() with explicit size limits"),
            (re.compile(r'\bsprintf\s*\('), "sprintf() does not check buffer bounds", "CRITICAL", 9.3, "Use snprintf() with size limit"),
            (re.compile(r'\bgets\s*\('), "gets() does not check buffer bounds", "CRITICAL", 9.8, "Use fgets() with size limit"),
            (re.compile(r'\bscanf\s*\([^)]*[^[]\s*%s'), "scanf() %s without field width specifier", "HIGH", 8.0, "Use scanf() with field width: %Ns"),
            (re.compile(r'\bprintf\s*\([^)]*%n'), "printf() with %n specifier can corrupt memory", "CRITICAL", 9.0, "Avoid %n in printf format strings"),
            (re.compile(r'\bsystem\s*\('), "system() call can execute arbitrary commands", "HIGH", 8.5, "Use execve() with full path if possible"),
            (re.compile(r'\balloca\s*\('), "alloca() can cause stack overflow", "MEDIUM", 6.5, "Use malloc() with proper error handling"),
            (re.compile(r'\bmktemp\s*\('), "mktemp() is insecure", "HIGH", 8.0, "Use mkstemp() instead"),
            (re.compile(r'\btmpnam\s*\('), "tmpnam() has race condition", "HIGH", 7.5, "Use mkstemp() instead"),
            (re.compile(r'\bgetpass\s*\('), "getpass() may not be portable", "LOW", 3.0, "Use secure password input methods"),
            (re.compile(r'\brealloc\s*\([^,]+,\s*0\s*\)'), "realloc() with size 0 is implementation-defined", "MEDIUM", 5.0, "Avoid realloc with zero size"),
            (re.compile(r'\bfree\s*\([^)]+\);\s*\n\s*\1\s*=\s*NULL'), "Missing NULL assignment after free", "MEDIUM", 5.5, "Set pointer to NULL after free"),
        ]

        for i, line in enumerate(lines, 1):
            for pattern, message, severity, cvss, remediation in DANGEROUS_C_FUNCS:
                if pattern.search(line):
                    issue = SecurityIssue(
                        rule_id=self.rule_id,
                        severity=severity,
                        message=f"C security issue: {message} at line {i}",
                        file_path=file_path,
                        line_number=i,
                        cwe=self.cwe,
                        cvss_score=cvss,
                        remediation=remediation,
                        snippet=line.strip(),
                    )
                    result.issues.append(issue)
                    break

        return result


# ---------------------------------------------------------------------------
# Rust-specific security rules
# ---------------------------------------------------------------------------

class RustSecurityRules(BaseSecurityRule):
    """Security analysis for Rust code."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._rule_id = "SEC-RUST-001"
        self._name = "Rust Security Rules"
        self._description = "Detects security issues in Rust code"
        self._severity = "HIGH"
        self._languages = ["rust"]
        self._cwe = "CWE-676"
        self._cvss = 7.0

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def check(self, tree: ast.AST, file_path: str, source_code: str) -> SecurityRuleResult:
        result = SecurityRuleResult(rule_id=self.rule_id, rule_name=self.name, description=self.description)
        lines = source_code.splitlines()

        DANGEROUS_RUST_PATTERNS = [
            (re.compile(r'\bunsafe\s*\{'), "Unsafe block used without safety justification", "MEDIUM", 5.5, "Minimize unsafe code. Document safety invariants with SAFETY comments."),
            (re.compile(r'\.unwrap\s*\(\s*\)'), "Unwrap may cause panic on None/Err", "MEDIUM", 5.0, "Use proper error handling: match, ? operator, or expect() with descriptive message"),
            (re.compile(r'\.expect\s*\(\s*"[^"]{0,20}"\s*\)'), "Expect with short or generic message", "LOW", 3.0, "Provide a descriptive error message that helps debugging"),
            (re.compile(r'ptr::read\s*\(|ptr::write\s*\('), "Dangerous raw pointer operation", "HIGH", 7.0, "Ensure proper alignment and validity before dereferencing raw pointers"),
            (re.compile(r'transmute\s*\(|mem::transmute\s*\('), "Transmute between unrelated types", "HIGH", 7.5, "Use transmute only when type layouts are guaranteed compatible"),
            (re.compile(r'\bstd::mem::zeroed\s*\('), "Type may not be zero-initializable", "MEDIUM", 6.0, "Ensure the type is zero-initializable. Use MaybeUninit for complex types."),
            (re.compile(r'\bstd::intrinsics::'), "Use of compiler intrinsics", "HIGH", 7.0, "Compiler intrinsics are unstable and unsafe. Avoid them."),
            (re.compile(r'\bstd::process::Command\s*::new\s*\([^)]*\)\s*\.arg\s*\([^)]*\)\s*\.arg\s*\([^)]*\)'), "Potential command injection via multi-arg command", "MEDIUM", 5.5, "Validate and sanitize command arguments"),
            (re.compile(r'\bstd::process::Command\s*::new\s*\([^)]*\)\s*\.arg\s*\([^)]*\)\s*\.spawn\s*\('), "Command execution with user input", "MEDIUM", 5.0, "Avoid passing user input to Command::new"),
            (re.compile(r'\.ok\(\)\.unwrap\(\)'), "ok().unwrap() converts error to panic", "MEDIUM", 5.0, "Use ? operator or pattern matching for proper error handling"),
            (re.compile(r'format!\s*\([^)]*\)\s*\.as_str\(\)'), "Temporary allocation in format! then as_str()", "LOW", 2.0, "Use format! directly or write! macro"),
            (re.compile(r'\bpanic!\s*\('), "Explicit panic in production code", "LOW", 3.0, "Use proper error types and Result returns instead of panicking"),
            (re.compile(r'\bunreachable!\s*\('), "Unreachable code marker", "LOW", 2.0, "Ensure unreachable! is only used for truly unreachable paths"),
            (re.compile(r'\btodo!\s*\('), "TODO macro in production code", "INFO", 0.0, "Implement the TODO before releasing"),
            (re.compile(r'\bimpl\s+(Sync|Send)\s+for'), "Manual Send/Sync implementation", "HIGH", 7.5, "Manual Send/Sync impls can cause undefined behavior if incorrect"),
            (re.compile(r'\b#[allow\(unsafe_code\)\]'), "Allowing unsafe code", "MEDIUM", 5.0, "Avoid allowing unsafe code. Keep unsafe blocks minimal."),
            (re.compile(r'\buse\s+std::os::unix::io::(FromRawFd|IntoRawFd)'), "Raw file descriptor operations", "HIGH", 7.0, "Raw FD operations can cause double-close or use-after-close"),
        ]

        for i, line in enumerate(lines, 1):
            for pattern, message, severity, cvss, remediation in DANGEROUS_RUST_PATTERNS:
                if pattern.search(line):
                    issue = SecurityIssue(
                        rule_id=self.rule_id,
                        severity=severity,
                        message=f"Rust security issue: {message} at line {i}",
                        file_path=file_path,
                        line_number=i,
                        cwe=self.cwe,
                        cvss_score=cvss,
                        remediation=remediation,
                        snippet=line.strip(),
                    )
                    result.issues.append(issue)
                    break

        return result


# ---------------------------------------------------------------------------
# Rule registry
# ---------------------------------------------------------------------------

def get_all_security_rules(config: Optional[Dict[str, Any]] = None) -> List[BaseSecurityRule]:
    """Return all registered security rules."""
    return [
        SQLInjectionRule(config),
        XSSRule(config),
        CommandInjectionRule(config),
        PathTraversalRule(config),
        InsecureDeserializationRule(config),
        HardcodedSecretsRule(config),
        WeakCryptoRule(config),
        SSRFDetectionRule(config),
        LooseCSPRule(config),
        SecurityMisconfigRule(config),
        InsecureRedirectRule(config),
        LogInjectionRule(config),
        InsecureDirectObjectReferenceRule(config),
        CSRFProtectionRule(config),
        NoSQLInjectionRule(config),
        LDAPInjectionRule(config),
        XMLExternalEntityRule(config),
        RaceConditionRule(config),
        CSecurityRules(config),
        RustSecurityRules(config),
    ]


def get_security_rules_by_language(language: str, config: Optional[Dict[str, Any]] = None) -> List[BaseSecurityRule]:
    """Return security rules applicable to a specific language."""
    return [rule for rule in get_all_security_rules(config) if language in rule.languages]


def get_security_rule_by_id(rule_id: str, config: Optional[Dict[str, Any]] = None) -> Optional[BaseSecurityRule]:
    """Return a specific security rule by ID."""
    for rule in get_all_security_rules(config):
        if rule.rule_id == rule_id:
            return rule
    return None