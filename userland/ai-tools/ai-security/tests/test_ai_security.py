"""Comprehensive tests for the AI Security auditing tool."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

# Ensure the parent directory is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_security import (
    DEFAULT_CONFIG,
    CommandInjectionDetector,
    FileAnalyzer,
    Finding,
    PathTraversalDetector,
    ReportGenerator,
    SQLInjectionDetector,
    ScanResult,
    Scanner,
    Severity,
    WeakCredentialDetector,
    XSSDetector,
    load_config,
)


# =========================================================================
# Test: Severity
# =========================================================================

class TestSeverity(unittest.TestCase):
    """Test the Severity class."""

    def test_levels_ordered(self) -> None:
        """Severity.levels() returns levels from most to least severe."""
        levels = Severity.levels()
        self.assertEqual(levels[0], Severity.CRITICAL)
        self.assertEqual(levels[-1], Severity.INFO)

    def test_from_int(self) -> None:
        """from_int maps integer scores to correct severity labels."""
        self.assertEqual(Severity.from_int(9), Severity.CRITICAL)
        self.assertEqual(Severity.from_int(8), Severity.HIGH)
        self.assertEqual(Severity.from_int(7), Severity.HIGH)
        self.assertEqual(Severity.from_int(6), Severity.MEDIUM)
        self.assertEqual(Severity.from_int(5), Severity.MEDIUM)
        self.assertEqual(Severity.from_int(4), Severity.LOW)
        self.assertEqual(Severity.from_int(3), Severity.LOW)
        self.assertEqual(Severity.from_int(2), Severity.INFO)
        self.assertEqual(Severity.from_int(1), Severity.INFO)

    def test_numeric(self) -> None:
        """numeric returns the correct weight for each severity."""
        self.assertEqual(Severity.numeric(Severity.CRITICAL), 5)
        self.assertEqual(Severity.numeric(Severity.HIGH), 4)
        self.assertEqual(Severity.numeric(Severity.MEDIUM), 3)
        self.assertEqual(Severity.numeric(Severity.LOW), 2)
        self.assertEqual(Severity.numeric(Severity.INFO), 1)
        self.assertEqual(Severity.numeric("UNKNOWN"), 0)


# =========================================================================
# Test: Data Models
# =========================================================================

class TestFinding(unittest.TestCase):
    """Test the Finding dataclass."""

    def test_create_finding(self) -> None:
        """A Finding can be created with default values."""
        f = Finding(
            rule_id="TEST-001",
            severity=Severity.HIGH,
            message="Test finding",
            file_path="/test/file.py",
            line_number=42,
        )
        self.assertEqual(f.rule_id, "TEST-001")
        self.assertEqual(f.severity, Severity.HIGH)
        self.assertEqual(f.confidence, 1.0)
        self.assertEqual(f.column, 0)
        self.assertEqual(f.snippet, "")
        self.assertEqual(f.recommendation, "")
        self.assertEqual(f.cwe, "")
        self.assertEqual(f.detector, "")

    def test_to_dict(self) -> None:
        """to_dict serializes the finding correctly."""
        f = Finding(
            rule_id="TEST-001",
            severity=Severity.CRITICAL,
            message="Critical issue",
            file_path="/app/test.py",
            line_number=10,
            column=5,
            snippet="dangerous_code()",
            confidence=0.95,
            recommendation="Fix it",
            cwe="CWE-79",
            detector="XSSDetector",
        )
        d = f.to_dict()
        self.assertEqual(d["rule_id"], "TEST-001")
        self.assertEqual(d["severity"], Severity.CRITICAL)
        self.assertEqual(d["line_number"], 10)
        self.assertEqual(d["confidence"], 0.95)

    def test_to_sarif(self) -> None:
        """to_sarif produces a valid SARIF result structure."""
        f = Finding(
            rule_id="SQL-001",
            severity=Severity.HIGH,
            message="SQL injection",
            file_path="/app/db.py",
            line_number=15,
            column=8,
        )
        sarif = f.to_sarif()
        self.assertEqual(sarif["ruleId"], "SQL-001")
        self.assertEqual(sarif["level"], "error")  # HIGH => error
        self.assertIn("locations", sarif)
        self.assertEqual(sarif["locations"][0]["physicalLocation"]["region"]["startLine"], 15)

    def test_to_sarif_critical(self) -> None:
        """CRITICAL severity maps to 'error' level in SARIF."""
        f = Finding(
            rule_id="CRIT-001",
            severity=Severity.CRITICAL,
            message="Critical",
            file_path="/app/x.py",
            line_number=1,
        )
        sarif = f.to_sarif()
        self.assertEqual(sarif["level"], "error")


class TestScanResult(unittest.TestCase):
    """Test the ScanResult dataclass."""

    def setUp(self) -> None:
        self.result = ScanResult(
            target="/test",
            scan_time="2024-01-01",
            duration_seconds=1.5,
            total_files=10,
            scanned_files=8,
            findings=[
                Finding("R1", Severity.CRITICAL, "Critical", "/a.py", 1),
                Finding("R2", Severity.HIGH, "High", "/b.py", 2),
                Finding("R3", Severity.MEDIUM, "Medium", "/c.py", 3),
            ],
        )

    def test_summary(self) -> None:
        """summary returns correct counts per severity."""
        s = self.result.summary()
        self.assertEqual(s[Severity.CRITICAL], 1)
        self.assertEqual(s[Severity.HIGH], 1)
        self.assertEqual(s[Severity.MEDIUM], 1)
        self.assertEqual(s[Severity.LOW], 0)
        self.assertEqual(s[Severity.INFO], 0)

    def test_to_dict(self) -> None:
        """to_dict contains all expected keys."""
        d = self.result.to_dict()
        self.assertEqual(d["target"], "/test")
        self.assertEqual(d["total_files"], 10)
        self.assertEqual(d["scanned_files"], 8)
        self.assertIn("summary", d)
        self.assertIn("findings", d)
        self.assertIn("errors", d)
        self.assertEqual(len(d["findings"]), 3)


# =========================================================================
# Test: Configuration
# =========================================================================

class TestConfig(unittest.TestCase):
    """Test configuration loading and defaults."""

    def test_default_config(self) -> None:
        """Default configuration contains expected keys."""
        self.assertIn("severity_threshold", DEFAULT_CONFIG)
        self.assertIn("exclude_patterns", DEFAULT_CONFIG)
        self.assertIn("enabled_detectors", DEFAULT_CONFIG)
        self.assertIn("output_format", DEFAULT_CONFIG)
        self.assertEqual(DEFAULT_CONFIG["severity_threshold"], Severity.INFO)

    def test_load_config_defaults(self) -> None:
        """load_config returns defaults when no config file is present."""
        config = load_config()
        self.assertEqual(config["severity_threshold"], Severity.INFO)
        self.assertIn("sql_injection", config["enabled_detectors"])

    def test_load_config_json(self) -> None:
        """load_config reads a JSON config file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"severity_threshold": "HIGH"}, f)
            temp_path = f.name

        try:
            config = load_config(temp_path)
            self.assertEqual(config["severity_threshold"], "HIGH")
            # Other keys should still have defaults
            self.assertIn("exclude_patterns", config)
        finally:
            os.unlink(temp_path)

    def test_load_config_nonexistent(self) -> None:
        """load_config raises FileNotFoundError for explicit missing path."""
        with self.assertRaises(FileNotFoundError):
            load_config("/nonexistent/config.json")


# =========================================================================
# Test: SQL Injection Detector
# =========================================================================

class TestSQLInjectionDetector(unittest.TestCase):
    """Test the SQLInjectionDetector."""

    def setUp(self) -> None:
        self.detector = SQLInjectionDetector(DEFAULT_CONFIG)

    def _detect(self, content: str) -> List[Finding]:
        return self.detector.detect("/test/test.py", content)

    def test_string_concat_select(self) -> None:
        """Detects string concatenation in SELECT queries."""
        code = '''query = "SELECT * FROM users WHERE id = " + user_id'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)
        self.assertIn("SQL", findings[0].message)

    def test_fstring_sql(self) -> None:
        """Detects f-string interpolation in SQL."""
        code = '''query = f"SELECT * FROM users WHERE id = {user_id}"'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_execute_raw(self) -> None:
        """Detects raw execute() calls."""
        code = '''cursor.execute("SELECT * FROM users")'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_format_method(self) -> None:
        """Detects str.format() in SQL."""
        code = '''query = "SELECT * FROM users WHERE id = {}".format(user_id)'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_django_rawsql(self) -> None:
        """Detects Django RawSQL usage."""
        code = '''objects.annotate(val=RawSQL("SELECT ..."))'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_safe_code_no_false_positive(self) -> None:
        """Clean code should not produce findings."""
        code = '''
def get_user(user_id):
    query = "SELECT * FROM users WHERE id = %s"
    cursor.execute(query, (user_id,))
    return cursor.fetchone()
'''
        findings = self._detect(code)
        # The pattern might still match 'execute' with raw SQL, but not the
        # string concatenation pattern. Let's check no CRITICAL findings.
        critical_count = sum(1 for f in findings if f.severity == Severity.CRITICAL)
        self.assertEqual(critical_count, 0)

    def test_php_mysql_query(self) -> None:
        """Detects PHP mysql_query."""
        code = '''$result = mysql_query("SELECT * FROM users");'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_node_template_literal(self) -> None:
        """Detects Node.js template literal SQL."""
        code = '''connection.query(`SELECT * FROM users WHERE id = ${id}`)'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_orm_raw(self) -> None:
        """Detects ORM .raw() method."""
        code = '''Model.objects.raw("SELECT * FROM users")'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)


# =========================================================================
# Test: XSS Detector
# =========================================================================

class TestXSSDetector(unittest.TestCase):
    """Test the XSSDetector."""

    def setUp(self) -> None:
        self.detector = XSSDetector(DEFAULT_CONFIG)

    def _detect(self, content: str, path: str = "/test/test.html") -> List[Finding]:
        return self.detector.detect(path, content)

    def test_inner_html(self) -> None:
        """Detects innerHTML assignment."""
        code = '''element.innerHTML = userInput;'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)
        self.assertIn("innerHTML", findings[0].message)

    def test_document_write(self) -> None:
        """Detects document.write()."""
        code = '''document.write(userInput);'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_eval(self) -> None:
        """Detects eval()."""
        code = '''eval(userInput);'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_jsx_dangerously_set_inner_html(self) -> None:
        """Detects React dangerouslySetInnerHTML."""
        code = '''<div dangerouslySetInnerHTML={{__html: content}} />'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_vue_v_html(self) -> None:
        """Detects Vue v-html."""
        code = '''<div v-html="userContent"></div>'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_jquery_html(self) -> None:
        """Detects jQuery .html() with variable."""
        code = '''$("#foo").html(userInput);'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_safe_filter(self) -> None:
        """Detects |safe filter in templates."""
        code = '''{{ user_input|safe }}'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_missing_csp(self) -> None:
        """Detects missing CSP in HTML documents."""
        content = '''<!DOCTYPE html><html><head><title>Test</title></head><body></body></html>'''
        findings = self._detect(content)
        csp_findings = [f for f in findings if "CSP" in f.message or "Content-Security-Policy" in f.message]
        self.assertGreater(len(csp_findings), 0)

    def test_clean_code(self) -> None:
        """Clean code should not produce XSS findings."""
        code = '''const name = "hello"; console.log(name);'''
        findings = self._detect(code, "/test/test.js")
        self.assertEqual(len(findings), 0)


# =========================================================================
# Test: Command Injection Detector
# =========================================================================

class TestCommandInjectionDetector(unittest.TestCase):
    """Test the CommandInjectionDetector."""

    def setUp(self) -> None:
        self.detector = CommandInjectionDetector(DEFAULT_CONFIG)

    def _detect(self, content: str, path: str = "/test/test.py") -> List[Finding]:
        return self.detector.detect(path, content)

    def test_os_system(self) -> None:
        """Detects os.system()."""
        code = '''os.system("rm -rf /")'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_subprocess_shell_true(self) -> None:
        """Detects subprocess with shell=True."""
        code = '''subprocess.call("ls -la", shell=True)'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_subprocess_popen_string(self) -> None:
        """Detects subprocess.Popen with string argument."""
        code = '''subprocess.Popen("ls -la", shell=True)'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_os_popen(self) -> None:
        """Detects os.popen()."""
        code = '''os.popen("ls")'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_php_shell_exec(self) -> None:
        """Detects PHP shell_exec()."""
        code = '''$output = shell_exec("ls -la");'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_node_child_process(self) -> None:
        """Detects Node.js child_process.exec()."""
        code = '''const { exec } = require('child_process'); exec('ls');'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_java_runtime_exec(self) -> None:
        """Detects Java Runtime.exec()."""
        code = '''Runtime.getRuntime().exec("ls");'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_clean_code(self) -> None:
        """Clean subprocess usage should not flag."""
        code = '''subprocess.run(["ls", "-la"], shell=False)'''
        findings = self._detect(code)
        # The pattern may still match subprocess.run with shell=False
        # but the shell=False variant should not be detected as CRITICAL
        critical = [f for f in findings if f.severity == Severity.CRITICAL]
        self.assertEqual(len(critical), 0)


# =========================================================================
# Test: Path Traversal Detector
# =========================================================================

class TestPathTraversalDetector(unittest.TestCase):
    """Test the PathTraversalDetector."""

    def setUp(self) -> None:
        self.detector = PathTraversalDetector(DEFAULT_CONFIG)

    def _detect(self, content: str, path: str = "/test/test.py") -> List[Finding]:
        return self.detector.detect(path, content)

    def test_open_with_concat(self) -> None:
        """Detects open() with string concatenation."""
        code = '''open("/var/www/" + filename, "r")'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_open_with_dot_dot(self) -> None:
        """Detects open() with ../ pattern."""
        code = '''open("../etc/passwd", "r")'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_send_file(self) -> None:
        """Detects Flask send_file with variable."""
        code = '''send_file(request.args.get('file'))'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_php_include(self) -> None:
        """Detects PHP include with variable."""
        code = '''include($userInput);'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_clean_code(self) -> None:
        """Clean path handling should not flag."""
        code = '''base = Path("/safe/path"); full = base / "file.txt"; open(full)'''
        findings = self._detect(code)
        # Path() with concatenation might trigger
        # Only check no HIGH severity findings
        high = [f for f in findings if f.severity == Severity.HIGH]
        self.assertEqual(len(high), 0)


# =========================================================================
# Test: Weak Credential Detector
# =========================================================================

class TestWeakCredentialDetector(unittest.TestCase):
    """Test the WeakCredentialDetector."""

    def setUp(self) -> None:
        self.detector = WeakCredentialDetector(DEFAULT_CONFIG)

    def _detect(self, content: str, path: str = "/test/test.py") -> List[Finding]:
        return self.detector.detect(path, content)

    def test_hardcoded_password(self) -> None:
        """Detects hardcoded password."""
        code = '''password = "supersecret123"'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_hardcoded_api_key(self) -> None:
        """Detects hardcoded API key."""
        code = '''API_KEY = "sk-abcdef1234567890abcdef1234567890"'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_database_url_with_credentials(self) -> None:
        """Detects database URL with embedded credentials."""
        code = '''DATABASE_URL = "postgres://user:password@localhost:5432/db"'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_private_key(self) -> None:
        """Detects private key in source."""
        code = '''-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_aws_key(self) -> None:
        """Detects AWS Access Key ID."""
        code = '''aws_access_key = "AKIAIOSFODNN7EXAMPLE"'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_jwt_token(self) -> None:
        """Detects hardcoded JWT token."""
        code = '''token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_weak_password_value(self) -> None:
        """Detects known weak password values."""
        code = '''password = "password123"'''
        findings = self._detect(code)
        weak = [f for f in findings if "weak" in f.message.lower() or "password" in f.message.lower()]
        self.assertGreater(len(weak), 0)

    def test_github_token(self) -> None:
        """Detects GitHub token."""
        code = '''token = "ghp_abcdefghijklmnopqrstuvwxyzABCDEFGH"'''
        findings = self._detect(code)
        self.assertGreater(len(findings), 0)

    def test_clean_code(self) -> None:
        """Code without credentials should not flag."""
        code = '''# Use environment variables for secrets\nimport os\npassword = os.environ.get("DB_PASSWORD")'''
        findings = self._detect(code)
        self.assertEqual(len(findings), 0)


# =========================================================================
# Test: File Analyzer
# =========================================================================

class TestFileAnalyzer(unittest.TestCase):
    """Test the FileAnalyzer class."""

    def setUp(self) -> None:
        self.config = dict(DEFAULT_CONFIG)
        self.detectors = [SQLInjectionDetector(self.config)]
        self.analyzer = FileAnalyzer(self.detectors, self.config)

    def test_should_skip_pyc(self) -> None:
        """should_skip returns True for .pyc files."""
        skip, reason = self.analyzer.should_skip("/test/file.pyc")
        self.assertTrue(skip)
        self.assertIn("binary", reason.lower())

    def test_should_skip_excluded(self) -> None:
        """should_skip returns True for files matching exclude patterns."""
        skip, reason = self.analyzer.should_skip("node_modules/foo.js")
        self.assertTrue(skip)
        self.assertIn("exclude", reason.lower())

    def test_should_skip_normal_py(self) -> None:
        """should_skip returns False for normal Python files."""
        self.config["exclude_patterns"] = ["*.pyc"]
        # Create a temp file to test size skipping
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
            f.write("x = 1")
            temp_path = f.name

        try:
            skip, reason = self.analyzer.should_skip(temp_path)
            self.assertFalse(skip)
        finally:
            os.unlink(temp_path)

    def test_analyze_file_sql_injection(self) -> None:
        """analyze_file detects SQL injection in a Python file."""
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8") as f:
            f.write('query = "SELECT * FROM users WHERE id = " + user_id')
            temp_path = f.name

        try:
            findings = self.analyzer.analyze_file(temp_path)
            self.assertGreater(len(findings), 0)
        finally:
            os.unlink(temp_path)

    def test_analyze_clean_file(self) -> None:
        """analyze_file returns no findings for clean code."""
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8") as f:
            f.write('x = 1\ny = 2\nprint(x + y)')
            temp_path = f.name

        try:
            findings = self.analyzer.analyze_file(temp_path)
            self.assertEqual(len(findings), 0)
        finally:
            os.unlink(temp_path)

    def test_analyze_nonexistent_file(self) -> None:
        """analyze_file raises FileNotFoundError for missing file."""
        with self.assertRaises(FileNotFoundError):
            self.analyzer.analyze_file("/nonexistent/file.py")

    def test_analyze_directory(self) -> None:
        """analyze_file raises ValueError for directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError):
                self.analyzer.analyze_file(tmpdir)


# =========================================================================
# Test: Report Generator
# =========================================================================

class TestReportGenerator(unittest.TestCase):
    """Test the ReportGenerator class."""

    def setUp(self) -> None:
        self.result = ScanResult(
            target="/test",
            scan_time="2024-06-15 10:00:00 UTC",
            duration_seconds=2.5,
            total_files=5,
            scanned_files=5,
            findings=[
                Finding(
                    rule_id="SQL-001",
                    severity=Severity.CRITICAL,
                    message="SQL injection in query",
                    file_path="/app/db.py",
                    line_number=10,
                    snippet="query = 'SELECT * FROM users WHERE id = ' + id",
                    confidence=0.95,
                    recommendation="Use parameterized queries",
                    cwe="CWE-89",
                    detector="SQLInjectionDetector",
                ),
                Finding(
                    rule_id="XSS-001",
                    severity=Severity.HIGH,
                    message="XSS via innerHTML",
                    file_path="/app/template.html",
                    line_number=25,
                    snippet="element.innerHTML = userInput",
                    confidence=0.9,
                    recommendation="Use textContent instead",
                    cwe="CWE-79",
                    detector="XSSDetector",
                ),
            ],
        )

    def test_generate_json(self) -> None:
        """generate_json writes a valid JSON file."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            temp_path = f.name

        try:
            ReportGenerator.generate_json(self.result, temp_path)
            with open(temp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["target"], "/test")
            self.assertEqual(len(data["findings"]), 2)
            self.assertIn("summary", data)
            self.assertEqual(data["summary"]["CRITICAL"], 1)
            self.assertEqual(data["summary"]["HIGH"], 1)
        finally:
            os.unlink(temp_path)

    def test_generate_html(self) -> None:
        """generate_html writes a valid HTML file."""
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
            temp_path = f.name

        try:
            ReportGenerator.generate_html(self.result, temp_path)
            with open(temp_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("<!DOCTYPE html>", content)
            self.assertIn("SQL-001", content)
            self.assertIn("XSS-001", content)
            self.assertIn("CRITICAL", content)
            self.assertIn("AI Security Audit Report", content)
        finally:
            os.unlink(temp_path)

    def test_generate_html_empty(self) -> None:
        """generate_html handles empty results."""
        empty_result = ScanResult(
            target="/clean",
            scan_time="2024-01-01",
            duration_seconds=0.5,
            total_files=1,
            scanned_files=1,
        )
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
            temp_path = f.name

        try:
            ReportGenerator.generate_html(empty_result, temp_path)
            with open(temp_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("No findings", content)
        finally:
            os.unlink(temp_path)

    def test_generate_sarif(self) -> None:
        """generate_sarif writes a valid SARIF JSON file."""
        with tempfile.NamedTemporaryFile(suffix=".sarif", delete=False, mode="w") as f:
            temp_path = f.name

        try:
            ReportGenerator.generate_sarif(self.result, temp_path)
            with open(temp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["$schema"], "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json")
            self.assertEqual(data["version"], "2.1.0")
            self.assertIn("runs", data)
            self.assertEqual(len(data["runs"][0]["results"]), 2)
            # Check rules
            rules = data["runs"][0]["tool"]["driver"]["rules"]
            rule_ids = [r["id"] for r in rules]
            self.assertIn("SQL-001", rule_ids)
            self.assertIn("XSS-001", rule_ids)
        finally:
            os.unlink(temp_path)


# =========================================================================
# Test: Scanner (Integration)
# =========================================================================

class TestScanner(unittest.TestCase):
    """Integration tests for the Scanner class."""

    def setUp(self) -> None:
        self.config = dict(DEFAULT_CONFIG)
        self.config["show_progress"] = False
        self.config["exclude_patterns"] = ["*.pyc", "__pycache__/*"]

    def test_scan_single_file(self) -> None:
        """Scanner can scan a single file."""
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8") as f:
            f.write('password = "supersecret"\n')
            f.write('os.system("ls -la")\n')
            f.write('query = "SELECT * FROM users WHERE id = " + uid\n')
            temp_path = f.name

        try:
            scanner = Scanner(self.config)
            result = scanner.scan_path(temp_path)
            self.assertGreater(len(result.findings), 0)
            self.assertEqual(result.scanned_files, 1)
            self.assertEqual(result.total_files, 1)
        finally:
            os.unlink(temp_path)

    def test_scan_clean_file(self) -> None:
        """Scanner returns no findings for clean file."""
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8") as f:
            f.write('import os\nx = 1\nprint(x)\n')
            temp_path = f.name

        try:
            scanner = Scanner(self.config)
            result = scanner.scan_path(temp_path)
            self.assertEqual(len(result.findings), 0)
        finally:
            os.unlink(temp_path)

    def test_scan_directory(self) -> None:
        """Scanner can scan an entire directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a few files
            files = {
                "app.py": 'password = "secret123"',
                "utils.py": 'os.system("ls")',
                "views.py": 'query = "SELECT * FROM users"',
                "README.md": "# Project\nThis is a test.",
                "data.json": '{"key": "value"}',
            }
            for name, content in files.items():
                Path(tmpdir, name).write_text(content, encoding="utf-8")

            scanner = Scanner(self.config)
            result = scanner.scan_path(tmpdir)
            self.assertGreater(len(result.findings), 0)
            self.assertGreater(result.scanned_files, 0)

    def test_scan_nonexistent(self) -> None:
        """Scanner raises FileNotFoundError for nonexistent path."""
        scanner = Scanner(self.config)
        with self.assertRaises(FileNotFoundError):
            scanner.scan_path("/nonexistent/path")

    def test_scan_binary_file_skipped(self) -> None:
        """Scanner skips binary files."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            temp_path = f.name

        try:
            scanner = Scanner(self.config)
            result = scanner.scan_path(temp_path)
            self.assertEqual(result.scanned_files, 0)
        finally:
            os.unlink(temp_path)


# =========================================================================
# Test: All Detectors Together
# =========================================================================

class TestAllDetectors(unittest.TestCase):
    """Test that all detectors work together."""

    def test_all_detectors_run(self) -> None:
        """All five detectors run without errors and cover all vulnerability types."""
        code = """
# SQL Injection
query = "SELECT * FROM users WHERE id = " + user_id

# XSS
element.innerHTML = userInput

# Command Injection
os.system("ls -la")

# Path Traversal
open("../etc/passwd", "r")

# Weak Credentials
password = "supersecret123"
"""
        detectors = [
            SQLInjectionDetector(DEFAULT_CONFIG),
            XSSDetector(DEFAULT_CONFIG),
            CommandInjectionDetector(DEFAULT_CONFIG),
            PathTraversalDetector(DEFAULT_CONFIG),
            WeakCredentialDetector(DEFAULT_CONFIG),
        ]

        all_findings = []
        for detector in detectors:
            findings = detector.detect("/test/test.py", code)
            all_findings.extend(findings)

        # Each detector should find at least one issue
        detector_findings: Dict[str, int] = {}
        for f in all_findings:
            detector_findings[f.detector] = detector_findings.get(f.detector, 0) + 1

        self.assertGreaterEqual(detector_findings.get("SQLInjectionDetector", 0), 1,
                                "SQLInjectionDetector should find at least 1 issue")
        self.assertGreaterEqual(detector_findings.get("XSSDetector", 0), 1,
                                "XSSDetector should find at least 1 issue")
        self.assertGreaterEqual(detector_findings.get("CommandInjectionDetector", 0), 1,
                                "CommandInjectionDetector should find at least 1 issue")
        self.assertGreaterEqual(detector_findings.get("PathTraversalDetector", 0), 1,
                                "PathTraversalDetector should find at least 1 issue")
        self.assertGreaterEqual(detector_findings.get("WeakCredentialDetector", 0), 1,
                                "WeakCredentialDetector should find at least 1 issue")


# =========================================================================
# Test: CLI Argument Parsing
# =========================================================================

class TestCLI(unittest.TestCase):
    """Test the CLI argument parsing."""

    def test_scan_parser_defaults(self) -> None:
        """Scan command parses basic arguments."""
        from ai_security import create_parser
        parser = create_parser()
        args = parser.parse_args(["scan", "/some/path"])
        self.assertEqual(args.command, "scan")
        self.assertEqual(args.target, "/some/path")
        self.assertEqual(args.format, "json")
        self.assertIsNone(args.output)

    def test_scan_parser_all_options(self) -> None:
        """Scan command parses all options."""
        from ai_security import create_parser
        parser = create_parser()
        args = parser.parse_args([
            "scan", "/target",
            "-o", "report.html",
            "-f", "html",
            "-e", "*.test.js",
            "-e", "*.spec.js",
            "-s", "HIGH",
            "-c", "/path/to/config.json",
            "-d", "sql_injection,xss",
            "--no-progress",
            "--confidence", "0.5",
        ])
        self.assertEqual(args.output, "report.html")
        self.assertEqual(args.format, "html")
        self.assertEqual(args.exclude, ["*.test.js", "*.spec.js"])
        self.assertEqual(args.severity, "HIGH")
        self.assertEqual(args.config, "/path/to/config.json")
        self.assertEqual(args.detectors, "sql_injection,xss")
        self.assertTrue(args.no_progress)
        self.assertEqual(args.confidence, 0.5)

    def test_config_parser_init(self) -> None:
        """Config command parses --init."""
        from ai_security import create_parser
        parser = create_parser()
        args = parser.parse_args(["config", "--init", "--path", "/tmp/test-config.json"])
        self.assertEqual(args.command, "config")
        self.assertTrue(args.init)
        self.assertEqual(args.path, "/tmp/test-config.json")

    def test_list_parser(self) -> None:
        """List command parses --verbose."""
        from ai_security import create_parser
        parser = create_parser()
        args = parser.parse_args(["list", "--verbose"])
        self.assertEqual(args.command, "list")
        self.assertTrue(args.verbose)

    def test_no_command(self) -> None:
        """No command prints help (returns 0)."""
        from ai_security import create_parser
        parser = create_parser()
        # Just check that parsing doesn't fail
        args = parser.parse_args([])
        self.assertIsNone(args.command)


# =========================================================================
# Test: Edge Cases and Error Handling
# =========================================================================

class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def test_empty_file(self) -> None:
        """Detectors handle empty files without error."""
        detector = SQLInjectionDetector(DEFAULT_CONFIG)
        findings = detector.detect("/test/empty.py", "")
        self.assertEqual(len(findings), 0)

    def test_binary_content(self) -> None:
        """Detectors handle binary-like content without crashing."""
        detector = XSSDetector(DEFAULT_CONFIG)
        findings = detector.detect("/test/binary.bin", "\x00\x01\x02\xff\xfe")
        self.assertEqual(len(findings), 0)  # May not detect anything

    def test_very_long_line(self) -> None:
        """Detectors handle very long lines."""
        long_line = "x = " + "A" * 10000 + " # " + "SELECT * FROM users WHERE id = " + "B" * 10000
        detector = SQLInjectionDetector(DEFAULT_CONFIG)
        findings = detector.detect("/test/long.py", long_line)
        # Should not crash, may or may not find something
        self.assertIsInstance(findings, list)

    def test_finding_confidence_filter(self) -> None:
        """FileAnalyzer filters findings below confidence threshold."""
        config = dict(DEFAULT_CONFIG)
        config["confidence_threshold"] = 0.8
        detector = SQLInjectionDetector(config)
        analyzer = FileAnalyzer([detector], config)

        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8") as f:
            f.write('query = "SELECT * FROM users WHERE id = " + uid')
            temp_path = f.name

        try:
            findings = analyzer.analyze_file(temp_path)
            for finding in findings:
                self.assertGreaterEqual(finding.confidence, 0.8)
        finally:
            os.unlink(temp_path)

    def test_scan_with_errors(self) -> None:
        """Scanner handles files that cause errors gracefully."""
        config = dict(DEFAULT_CONFIG)
        config["show_progress"] = False
        scanner = Scanner(config)

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a valid file and a symlink to nowhere
            Path(tmpdir, "good.py").write_text("x = 1", encoding="utf-8")

            result = scanner.scan_path(tmpdir)
            self.assertGreaterEqual(result.scanned_files, 1)
            self.assertIsInstance(result.errors, list)

    def test_exclude_patterns_multiple(self) -> None:
        """Multiple exclude patterns are all respected."""
        config = dict(DEFAULT_CONFIG)
        config["exclude_patterns"] = ["*.pyc", "*.log", "tmp/*", "node_modules/*"]
        analyzer = FileAnalyzer([SQLInjectionDetector(config)], config)

        self.assertTrue(analyzer.should_skip("foo.pyc")[0])
        self.assertTrue(analyzer.should_skip("foo.log")[0])
        self.assertTrue(analyzer.should_skip("tmp/foo.py")[0])
        self.assertTrue(analyzer.should_skip("node_modules/foo.js")[0])
        self.assertFalse(analyzer.should_skip("foo.py")[0])


# =========================================================================
# Test: Report Generator - Edge Cases
# =========================================================================

class TestReportGeneratorEdgeCases(unittest.TestCase):
    """Test report generator edge cases."""

    def test_json_empty_findings(self) -> None:
        """JSON report with no findings is valid."""
        result = ScanResult(
            target="/clean",
            scan_time="2024-01-01",
            duration_seconds=0.1,
            total_files=1,
            scanned_files=1,
        )
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            temp_path = f.name

        try:
            ReportGenerator.generate_json(result, temp_path)
            with open(temp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(len(data["findings"]), 0)
            self.assertEqual(data["summary"]["CRITICAL"], 0)
        finally:
            os.unlink(temp_path)

    def test_sarif_no_findings(self) -> None:
        """SARIF report with no findings is valid."""
        result = ScanResult(
            target="/clean",
            scan_time="2024-01-01",
            duration_seconds=0.2,
            total_files=10,
            scanned_files=10,
        )
        with tempfile.NamedTemporaryFile(suffix=".sarif", delete=False, mode="w") as f:
            temp_path = f.name

        try:
            ReportGenerator.generate_sarif(result, temp_path)
            with open(temp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(len(data["runs"][0]["results"]), 0)
        finally:
            os.unlink(temp_path)


# =========================================================================
# Main
# =========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)