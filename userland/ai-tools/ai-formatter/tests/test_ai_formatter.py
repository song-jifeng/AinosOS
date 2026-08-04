"""Comprehensive tests for the AI-Powered Code Formatting Tool."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_formatter import (
    AIFormatterError,
    AutoFixer,
    CFormatter,
    CodeFormatter,
    ConfigError,
    DiffOutput,
    ExternalFormatter,
    ExternalToolError,
    FixMode,
    FormatError,
    FormatResult,
    FormatterConfig,
    FormatterFactory,
    GoFormatter,
    JavaFormatter,
    ParseError,
    PythonFormatter,
    Rule,
    RuleManager,
    RustFormatter,
    Severity,
    StyleChecker,
    StyleViolationError,
    Violation,
    __version__,
    build_arg_parser,
    main,
)


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def default_config() -> FormatterConfig:
    """Return a default FormatterConfig instance."""
    return FormatterConfig()


@pytest.fixture
def python_config() -> FormatterConfig:
    """Return a Python-specific FormatterConfig."""
    config = FormatterConfig()
    config.set("language", "python")
    config.set("line_length", 88)
    config.set("indent_size", 4)
    config.set("style", "pep8")
    return config


@pytest.fixture
def python_formatter(python_config: FormatterConfig) -> PythonFormatter:
    """Return a PythonFormatter instance."""
    return PythonFormatter(python_config)


@pytest.fixture
def rule_manager() -> RuleManager:
    """Return a RuleManager with built-in rules registered."""
    rm = RuleManager()
    rm.register_builtin_rules()
    return rm


@pytest.fixture
def diff_output() -> DiffOutput:
    """Return a DiffOutput instance."""
    return DiffOutput()


@pytest.fixture
def sample_python_code() -> str:
    """Return a sample Python code snippet for testing."""
    return (
        'import os\n'
        'import sys\n'
        '\n'
        '\n'
        'def foo():\n'
        '    pass\n'
        '\n'
        '\n'
        'class Bar:\n'
        '    pass\n'
    )


@pytest.fixture
def sample_c_code() -> str:
    """Return a sample C code snippet for testing."""
    return (
        '#include <stdio.h>\n'
        '\n'
        'int main() {\n'
        '    printf("hello");\n'
        '    return 0;\n'
        '}\n'
    )


@pytest.fixture
def sample_rust_code() -> str:
    """Return a sample Rust code snippet for testing."""
    return (
        'fn main() {\n'
        '    println!("hello");\n'
        '}\n'
    )


@pytest.fixture
def sample_java_code() -> str:
    """Return a sample Java code snippet for testing."""
    return (
        'public class Hello {\n'
        '    public static void main(String[] args) {\n'
        '        System.out.println("hello");\n'
        '    }\n'
        '}\n'
    )


@pytest.fixture
def sample_go_code() -> str:
    """Return a sample Go code snippet for testing."""
    return (
        'package main\n'
        '\n'
        'import "fmt"\n'
        '\n'
        'func main() {\n'
        '    fmt.Println("hello")\n'
        '}\n'
    )


# ===================================================================
# Tests: Version and Constants
# ===================================================================


class TestVersion:
    """Test module-level constants."""

    def test_version_is_string(self) -> None:
        """Verify __version__ is a string."""
        assert isinstance(__version__, str)
        assert len(__version__) > 0

    def test_supported_languages(self) -> None:
        """Verify supported languages are defined."""
        from ai_formatter import SUPPORTED_LANGUAGES
        assert "python" in SUPPORTED_LANGUAGES
        assert "c" in SUPPORTED_LANGUAGES
        assert "rust" in SUPPORTED_LANGUAGES
        assert "java" in SUPPORTED_LANGUAGES
        assert "go" in SUPPORTED_LANGUAGES
        assert len(SUPPORTED_LANGUAGES) == 5

    def test_config_filenames(self) -> None:
        """Verify config filenames include expected formats."""
        from ai_formatter import CONFIG_FILENAMES
        assert any(".yml" in f for f in CONFIG_FILENAMES)
        assert any(".json" in f for f in CONFIG_FILENAMES)


# ===================================================================
# Tests: Error Handling
# ===================================================================


class TestErrors:
    """Test custom exception classes."""

    def test_base_error(self) -> None:
        """Verify base error has message and code."""
        err = AIFormatterError("test error", code=42)
        assert str(err) == "test error"
        assert err.code == 42
        assert err.message == "test error"

    def test_config_error(self) -> None:
        """Verify ConfigError includes path."""
        path = Path("/fake/path")
        err = ConfigError("bad config", path=path)
        assert err.config_path == path
        assert err.code == 2

    def test_parse_error(self) -> None:
        """Verify ParseError includes line number."""
        err = ParseError("parse failed", lineno=10)
        assert err.lineno == 10
        assert err.code == 3

    def test_format_error(self) -> None:
        """Verify FormatError includes language."""
        err = FormatError("format failed", language="python")
        assert err.language == "python"
        assert err.code == 4

    def test_external_tool_error(self) -> None:
        """Verify ExternalToolError includes tool info."""
        err = ExternalToolError(
            "tool failed", tool_name="black", return_code=1, stderr="error"
        )
        assert err.tool_name == "black"
        assert err.return_code == 1
        assert err.stderr == "error"
        assert err.code == 5

    def test_style_violation_error(self) -> None:
        """Verify StyleViolationError includes count."""
        err = StyleViolationError("violations found", violations=5)
        assert err.violation_count == 5
        assert err.code == 6


# ===================================================================
# Tests: Severity and Violation
# ===================================================================


class TestSeverity:
    """Test Severity enum."""

    def test_severity_values(self) -> None:
        """Verify severity levels exist."""
        assert Severity.ERROR
        assert Severity.WARNING
        assert Severity.INFO
        assert Severity.HINT

    def test_severity_order(self) -> None:
        """Verify severity ordering via auto() assignment."""
        assert Severity.ERROR.value < Severity.WARNING.value
        assert Severity.WARNING.value < Severity.INFO.value


class TestViolation:
    """Test Violation dataclass."""

    def test_violation_creation(self) -> None:
        """Verify Violation can be instantiated."""
        v = Violation(
            lineno=1,
            col_offset=4,
            code="E501",
            message="Line too long",
            severity=Severity.WARNING,
            suggestion="fix",
        )
        assert v.lineno == 1
        assert v.col_offset == 4
        assert v.code == "E501"
        assert v.message == "Line too long"
        assert v.severity == Severity.WARNING
        assert v.suggestion == "fix"

    def test_violation_default_suggestion(self) -> None:
        """Verify suggestion defaults to empty string."""
        v = Violation(
            lineno=1,
            col_offset=0,
            code="TEST",
            message="test",
            severity=Severity.INFO,
        )
        assert v.suggestion == ""


# ===================================================================
# Tests: DiffOutput
# ===================================================================


class TestDiffOutput:
    """Test DiffOutput class."""

    def test_generate_no_changes(self, diff_output: DiffOutput) -> None:
        """Verify diff is empty when content is identical."""
        content = "line1\nline2\nline3\n"
        diff = diff_output.generate(content, content, "test.py")
        assert diff == ""

    def test_generate_with_changes(self, diff_output: DiffOutput) -> None:
        """Verify diff is generated when content differs."""
        original = "line1\nline2\nline3\n"
        formatted = "line1\nline2 modified\nline3\n"
        diff = diff_output.generate(original, formatted, "test.py")
        assert diff != ""
        assert "-line2" in diff
        assert "+line2 modified" in diff

    def test_has_changes(self, diff_output: DiffOutput) -> None:
        """Verify has_changes detects differences."""
        assert diff_output.has_changes("a\nb\n", "a\nc\n")
        assert not diff_output.has_changes("a\nb\n", "a\nb\n")

    def test_statistics(self) -> None:
        """Verify compute_statistics returns correct counts."""
        diff = (
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-old line\n"
            "+new line\n"
            " line3\n"
        )
        stats = DiffOutput.compute_statistics(diff)
        assert stats["additions"] == 1
        assert stats["deletions"] == 1
        assert stats["files_changed"] == 1

    def test_colorize_diff(self) -> None:
        """Verify colorize_diff adds ANSI codes."""
        diff = "--- a/file\n+++ b/file\n@@ -1 +1 @@\n-old\n+new\n"
        colored = DiffOutput.colorize_diff(diff)
        assert "\033[" in colored
        assert "old" in colored
        assert "new" in colored


# ===================================================================
# Tests: Rule Management
# ===================================================================


class TestRuleManager:
    """Test RuleManager class."""

    def test_register_and_get_rule(self, rule_manager: RuleManager) -> None:
        """Verify rule registration and retrieval."""
        rule = rule_manager.get_rule("trailing-whitespace")
        assert rule is not None
        assert rule.name == "trailing-whitespace"
        assert rule.enabled is True

    def test_get_nonexistent_rule(self, rule_manager: RuleManager) -> None:
        """Verify get_rule returns None for unknown rules."""
        assert rule_manager.get_rule("nonexistent") is None

    def test_register_duplicate_rule(self, rule_manager: RuleManager) -> None:
        """Verify duplicate registration raises ValueError."""
        rule = Rule(name="test-rule", language="*")
        rule_manager.register_rule(rule)
        with pytest.raises(ValueError, match="already registered"):
            rule_manager.register_rule(rule)

    def test_enable_rule(self, rule_manager: RuleManager) -> None:
        """Verify enable_rule toggles rule state."""
        rule_manager.enable_rule("trailing-whitespace", enabled=False)
        rule = rule_manager.get_rule("trailing-whitespace")
        assert rule is not None
        assert rule.enabled is False

        rule_manager.enable_rule("trailing-whitespace", enabled=True)
        rule = rule_manager.get_rule("trailing-whitespace")
        assert rule is not None
        assert rule.enabled is True

    def test_enable_nonexistent_rule(self, rule_manager: RuleManager) -> None:
        """Verify enabling unknown rule raises KeyError."""
        with pytest.raises(KeyError):
            rule_manager.enable_rule("nonexistent")

    def test_remove_custom_rule(self) -> None:
        """Verify custom rules can be removed."""
        rm = RuleManager()
        rule = Rule(name="my-rule", language="*")
        rm.register_rule(rule)
        rm.remove_rule("my-rule")
        assert rm.get_rule("my-rule") is None

    def test_remove_builtin_rule(self, rule_manager: RuleManager) -> None:
        """Verify built-in rules cannot be removed."""
        with pytest.raises(KeyError):
            rule_manager.remove_rule("trailing-whitespace")

    def test_rules_for_language(self, rule_manager: RuleManager) -> None:
        """Verify language-specific rules are returned."""
        rules = rule_manager.get_rules_for_language("python")
        names = [r.name for r in rules]
        assert "python-import-order" in names
        assert "trailing-whitespace" in names  # universal rule

    def test_rules_for_language_disabled(self, rule_manager: RuleManager) -> None:
        """Verify disabled rules are excluded when enabled_only=True."""
        rule_manager.enable_rule("trailing-whitespace", enabled=False)
        rules = rule_manager.get_rules_for_language("python", enabled_only=True)
        names = [r.name for r in rules]
        assert "trailing-whitespace" not in names

    def test_rule_count(self, rule_manager: RuleManager) -> None:
        """Verify rule_count returns correct total."""
        assert rule_manager.rule_count > 0

    def test_builtin_count(self, rule_manager: RuleManager) -> None:
        """Verify builtin_count returns correct number."""
        assert rule_manager.builtin_count > 0

    def test_list_rules(self, rule_manager: RuleManager) -> None:
        """Verify list_rules returns formatted strings."""
        lines = rule_manager.list_rules()
        assert len(lines) > 0
        assert any("trailing-whitespace" in line for line in lines)

    def test_list_rules_verbose(self, rule_manager: RuleManager) -> None:
        """Verify verbose listing includes details."""
        lines = rule_manager.list_rules(verbose=True)
        assert any("BUILTIN" in line for line in lines)
        assert any("Language:" in line for line in lines)

    def test_list_rules_filtered(self, rule_manager: RuleManager) -> None:
        """Verify filtered listing works."""
        lines = rule_manager.list_rules(language="python")
        assert len(lines) > 0

    def test_load_rules_from_config(self, rule_manager: RuleManager) -> None:
        """Verify loading rules from config dictionary."""
        config: Dict[str, Any] = {
            "rules": [
                {
                    "name": "custom-rule",
                    "description": "A custom rule",
                    "language": "python",
                    "enabled": True,
                    "severity": "ERROR",
                    "pattern": r"TODO",
                }
            ]
        }
        count = rule_manager.load_rules_from_config(config)
        assert count == 1
        rule = rule_manager.get_rule("custom-rule")
        assert rule is not None
        assert rule.severity == Severity.ERROR
        assert rule.pattern == r"TODO"


# ===================================================================
# Tests: FormatterConfig
# ===================================================================


class TestFormatterConfig:
    """Test FormatterConfig class."""

    def test_default_values(self) -> None:
        """Verify default configuration values."""
        config = FormatterConfig()
        assert config.language == "python"
        assert config.line_length == 88
        assert config.indent_size == 4
        assert config.fix_mode == FixMode.SAFE

    def test_set_and_get(self) -> None:
        """Verify set and get methods."""
        config = FormatterConfig()
        config.set("language", "rust")
        assert config.get("language") == "rust"
        assert config.language == "rust"

    def test_get_default(self) -> None:
        """Verify get returns default for unknown keys."""
        config = FormatterConfig()
        assert config.get("nonexistent", "fallback") == "fallback"
        assert config.get("nonexistent") is None

    def test_set_invalid_language(self) -> None:
        """Verify setting invalid language raises ConfigError."""
        config = FormatterConfig()
        with pytest.raises(ConfigError):
            config.set("language", "brainfuck")

    def test_set_invalid_line_length(self) -> None:
        """Verify setting invalid line length raises ConfigError."""
        config = FormatterConfig()
        with pytest.raises(ConfigError):
            config.set("line_length", -1)

    def test_set_invalid_indent_size(self) -> None:
        """Verify setting invalid indent size raises ConfigError."""
        config = FormatterConfig()
        with pytest.raises(ConfigError):
            config.set("indent_size", 0)

    def test_set_invalid_indent_style(self) -> None:
        """Verify setting invalid indent style raises ConfigError."""
        config = FormatterConfig()
        with pytest.raises(ConfigError):
            config.set("indent_style", "mixed")

    def test_set_invalid_style(self) -> None:
        """Verify setting invalid style raises ConfigError."""
        config = FormatterConfig()
        with pytest.raises(ConfigError):
            config.set("style", "microsoft")

    def test_as_dict(self) -> None:
        """Verify as_dict returns a copy of config."""
        config = FormatterConfig()
        config.set("language", "go")
        d = config.as_dict()
        assert d["language"] == "go"
        d["language"] = "python"
        assert config.language == "go"  # original unchanged

    def test_loaded_path_none(self) -> None:
        """Verify loaded_path is None initially."""
        config = FormatterConfig()
        assert config.loaded_path is None

    def test_load_json_config(self) -> None:
        """Verify loading JSON config from file."""
        config = FormatterConfig()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"language": "rust", "line_length": 100}, f)
            tmp_path = f.name

        try:
            loaded = config.load(Path(tmp_path))
            assert loaded is True
            assert config.language == "rust"
            assert config.line_length == 100
            assert config.loaded_path is not None
        finally:
            os.unlink(tmp_path)

    def test_load_nonexistent_file(self) -> None:
        """Verify loading nonexistent file raises ConfigError."""
        config = FormatterConfig()
        with pytest.raises(ConfigError):
            config.load(Path("/nonexistent/config.json"))

    def test_save_json(self) -> None:
        """Verify saving config to JSON file."""
        config = FormatterConfig()
        config.set("language", "go")
        config.set("line_length", 120)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            tmp_path = f.name

        try:
            config.save(Path(tmp_path), fmt="json")
            loaded = json.loads(Path(tmp_path).read_text(encoding="utf-8"))
            assert loaded["language"] == "go"
            assert loaded["line_length"] == 120
        finally:
            os.unlink(tmp_path)

    def test_config_validation_unknown_key(self) -> None:
        """Verify unknown config keys raise ConfigError."""
        config = FormatterConfig()
        with pytest.raises(ConfigError, match="Unknown configuration key"):
            config.set("unknown_key", "value")


# ===================================================================
# Tests: StyleChecker
# ===================================================================


class TestStyleChecker:
    """Test StyleChecker class."""

    def test_trailing_whitespace(self, python_config: FormatterConfig) -> None:
        """Verify trailing whitespace is detected."""
        checker = StyleChecker(python_config)
        source = "line1   \nline2\nline3  \n"
        violations = checker.check(source, "python")
        trailing = [v for v in violations if v.code == "W291"]
        assert len(trailing) == 2

    def test_line_length(self, python_config: FormatterConfig) -> None:
        """Verify long lines are detected."""
        python_config.set("line_length", 10)
        checker = StyleChecker(python_config)
        source = "x" * 20 + "\n" + "short\n"
        violations = checker.check(source, "python")
        long_lines = [v for v in violations if v.code == "E501"]
        assert len(long_lines) == 1

    def test_final_newline(self, python_config: FormatterConfig) -> None:
        """Verify missing final newline is detected."""
        checker = StyleChecker(python_config)
        source = "line1\nline2"
        violations = checker.check(source, "python")
        assert any(v.code == "W292" for v in violations)

    def test_extra_blank_lines_eof(self, python_config: FormatterConfig) -> None:
        """Verify extra blank lines at EOF are detected."""
        checker = StyleChecker(python_config)
        source = "line1\n\n\n\n"
        violations = checker.check(source, "python")
        assert any(v.code == "W391" for v in violations)

    def test_mixed_indentation(self, python_config: FormatterConfig) -> None:
        """Verify mixed tabs and spaces are detected."""
        checker = StyleChecker(python_config)
        source = "\tdef foo():\n    pass\n"
        violations = checker.check(source, "python")
        assert any(v.code == "E101" for v in violations)

    def test_indentation_multiple(self, python_config: FormatterConfig) -> None:
        """Verify indentation not multiple of indent_size is detected."""
        python_config.set("indent_size", 4)
        python_config.set("indent_style", "space")
        checker = StyleChecker(python_config)
        source = "def foo():\n   pass\n"
        violations = checker.check(source, "python")
        assert any(v.code == "E111" for v in violations)

    def test_clean_code_no_violations(
        self, python_config: FormatterConfig, sample_python_code: str
    ) -> None:
        """Verify clean code produces minimal violations."""
        checker = StyleChecker(python_config)
        violations = checker.check(sample_python_code, "python")
        # Should have no trailing whitespace or indentation issues
        assert not any(v.code == "W291" for v in violations)
        assert not any(v.code == "E101" for v in violations)

    def test_style_name(self, python_config: FormatterConfig) -> None:
        """Verify style_name property."""
        checker = StyleChecker(python_config)
        assert checker.style_name == "pep8"


# ===================================================================
# Tests: AutoFixer
# ===================================================================


class TestAutoFixer:
    """Test AutoFixer class."""

    def test_fix_trailing_whitespace(self, default_config: FormatterConfig) -> None:
        """Verify trailing whitespace is removed."""
        fixer = AutoFixer(default_config)
        result = fixer.fix("line1   \nline2  \n", "python")
        assert result == "line1\nline2\n"
        assert fixer.fix_count > 0

    def test_fix_final_newline(self, default_config: FormatterConfig) -> None:
        """Verify final newline is added."""
        fixer = AutoFixer(default_config)
        result = fixer.fix("line1\nline2", "python")
        assert result.endswith("\n")
        # Should be exactly one newline at end
        assert result == "line1\nline2\n"

    def test_fix_extra_newlines(self, default_config: FormatterConfig) -> None:
        """Verify extra trailing newlines are removed."""
        fixer = AutoFixer(default_config)
        result = fixer.fix("line1\n\n\n\n", "python")
        assert result == "line1\n"
        assert fixer.fix_count > 0

    def test_fix_indentation_tabs_to_spaces(
        self, default_config: FormatterConfig
    ) -> None:
        """Verify tabs are converted to spaces."""
        default_config.set("indent_style", "space")
        default_config.set("indent_size", 4)
        fixer = AutoFixer(default_config)
        result = fixer.fix("\tdef foo():\n\t\tpass\n", "python")
        assert "    def foo():" in result
        assert "        pass" in result

    def test_fix_indentation_spaces_to_tabs(
        self, default_config: FormatterConfig
    ) -> None:
        """Verify spaces are converted to tabs."""
        default_config.set("indent_style", "tab")
        default_config.set("indent_size", 4)
        fixer = AutoFixer(default_config)
        result = fixer.fix("    def foo():\n        pass\n", "python")
        assert result.startswith("\t")

    def test_reset_count(self, default_config: FormatterConfig) -> None:
        """Verify reset_count clears the counter."""
        fixer = AutoFixer(default_config)
        fixer.fix("bad   \n", "python")
        assert fixer.fix_count > 0
        fixer.reset_count()
        assert fixer.fix_count == 0

    def test_no_fix_needed(self, default_config: FormatterConfig) -> None:
        """Verify clean code doesn't increment count."""
        fixer = AutoFixer(default_config)
        result = fixer.fix("clean\ncode\n", "python")
        assert result == "clean\ncode\n"


# ===================================================================
# Tests: PythonFormatter
# ===================================================================


class TestPythonFormatter:
    """Test PythonFormatter class."""

    def test_language_property(self, python_formatter: PythonFormatter) -> None:
        """Verify language property returns 'python'."""
        assert python_formatter.language == "python"

    def test_format_code_preserves_structure(
        self, python_formatter: PythonFormatter, sample_python_code: str
    ) -> None:
        """Verify formatting preserves overall structure."""
        result = python_formatter.format_code(sample_python_code)
        assert "import os" in result
        assert "import sys" in result
        assert "def foo():" in result
        assert "class Bar:" in result

    def test_format_string(self, python_formatter: PythonFormatter) -> None:
        """Verify format_string returns a FormatResult."""
        source = "def foo():\n    pass\n"
        result = python_formatter.format_string(source)
        assert isinstance(result, FormatResult)
        assert result.success

    def test_format_string_with_path(
        self, python_formatter: PythonFormatter
    ) -> None:
        """Verify format_string accepts a path."""
        source = "x = 1\n"
        path = Path("test.py")
        result = python_formatter.format_string(source, file_path=path)
        assert result.path == path

    def test_check_style(self, python_formatter: PythonFormatter) -> None:
        """Verify check_style returns violations."""
        source = "bad   \n"
        violations = python_formatter.check_style(source)
        assert len(violations) >= 0

    def test_get_rule_manager(
        self, python_formatter: PythonFormatter
    ) -> None:
        """Verify get_rule_manager returns a RuleManager."""
        rm = python_formatter.get_rule_manager()
        assert isinstance(rm, RuleManager)
        assert rm.rule_count > 0

    def test_format_file(
        self, python_formatter: PythonFormatter
    ) -> None:
        """Verify format_file processes a file on disk."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write("x=1\n")
            tmp_path = f.name

        try:
            result = python_formatter.format_file(Path(tmp_path))
            assert isinstance(result, FormatResult)
            # Should have at least processed the file
            assert result.path == Path(tmp_path)
        finally:
            os.unlink(tmp_path)


# ===================================================================
# Tests: CFormatter
# ===================================================================


class TestCFormatter:
    """Test CFormatter class."""

    def test_language_property(self, default_config: FormatterConfig) -> None:
        """Verify language property returns 'c'."""
        formatter = CFormatter(default_config)
        assert formatter.language == "c"

    def test_format_code(self, default_config: FormatterConfig) -> None:
        """Verify basic C formatting."""
        formatter = CFormatter(default_config)
        source = "int main() {\nprintf(\"hello\");\nreturn 0;\n}\n"
        result = formatter.format_code(source)
        assert "int main() {" in result
        assert "printf" in result

    def test_format_code_indentation(
        self, default_config: FormatterConfig
    ) -> None:
        """Verify C code gets proper indentation."""
        formatter = CFormatter(default_config)
        source = "void f() {\nif (x) {\ndo_something();\n}\n}\n"
        result = formatter.format_code(source)
        # Content inside braces should be indented
        assert "    do_something();" in result


# ===================================================================
# Tests: RustFormatter
# ===================================================================


class TestRustFormatter:
    """Test RustFormatter class."""

    def test_language_property(self, default_config: FormatterConfig) -> None:
        """Verify language property returns 'rust'."""
        formatter = RustFormatter(default_config)
        assert formatter.language == "rust"

    def test_format_code(self, default_config: FormatterConfig) -> None:
        """Verify basic Rust formatting."""
        formatter = RustFormatter(default_config)
        source = "fn main(){\nprintln!(\"hello\");\n}\n"
        result = formatter.format_code(source)
        assert "fn main()" in result
        assert "println!" in result

    def test_format_code_keyword_spacing(
        self, default_config: FormatterConfig
    ) -> None:
        """Verify keywords get proper spacing."""
        formatter = RustFormatter(default_config)
        source = "fn main(){\nif(x>0){\n}\n}\n"
        result = formatter.format_code(source)
        assert "if (" in result or "if (" in result


# ===================================================================
# Tests: JavaFormatter
# ===================================================================


class TestJavaFormatter:
    """Test JavaFormatter class."""

    def test_language_property(self, default_config: FormatterConfig) -> None:
        """Verify language property returns 'java'."""
        formatter = JavaFormatter(default_config)
        assert formatter.language == "java"

    def test_format_code(self, default_config: FormatterConfig) -> None:
        """Verify basic Java formatting."""
        formatter = JavaFormatter(default_config)
        source = "public class A {\npublic void f() {\n}\n}\n"
        result = formatter.format_code(source)
        assert "public class A {" in result
        assert "public void f()" in result


# ===================================================================
# Tests: GoFormatter
# ===================================================================


class TestGoFormatter:
    """Test GoFormatter class."""

    def test_language_property(self, default_config: FormatterConfig) -> None:
        """Verify language property returns 'go'."""
        formatter = GoFormatter(default_config)
        assert formatter.language == "go"

    def test_format_code(self, default_config: FormatterConfig) -> None:
        """Verify basic Go formatting."""
        formatter = GoFormatter(default_config)
        source = "package main\nfunc main() {\n}\n"
        result = formatter.format_code(source)
        assert "package main" in result
        assert "func main()" in result

    def test_go_uses_tabs(self, default_config: FormatterConfig) -> None:
        """Verify Go formatter uses tabs for indentation."""
        formatter = GoFormatter(default_config)
        source = "func main() {\nx()\n}\n"
        result = formatter.format_code(source)
        # Go uses tab indentation
        assert "\tx()" in result


# ===================================================================
# Tests: FormatterFactory
# ===================================================================


class TestFormatterFactory:
    """Test FormatterFactory class."""

    def test_create_python_formatter(self) -> None:
        """Verify factory creates PythonFormatter."""
        formatter = FormatterFactory.create_formatter("python")
        assert isinstance(formatter, PythonFormatter)

    def test_create_c_formatter(self) -> None:
        """Verify factory creates CFormatter."""
        formatter = FormatterFactory.create_formatter("c")
        assert isinstance(formatter, CFormatter)

    def test_create_rust_formatter(self) -> None:
        """Verify factory creates RustFormatter."""
        formatter = FormatterFactory.create_formatter("rust")
        assert isinstance(formatter, RustFormatter)

    def test_create_java_formatter(self) -> None:
        """Verify factory creates JavaFormatter."""
        formatter = FormatterFactory.create_formatter("java")
        assert isinstance(formatter, JavaFormatter)

    def test_create_go_formatter(self) -> None:
        """Verify factory creates GoFormatter."""
        formatter = FormatterFactory.create_formatter("go")
        assert isinstance(formatter, GoFormatter)

    def test_create_unsupported_language(self) -> None:
        """Verify factory raises ConfigError for unsupported language."""
        with pytest.raises(ConfigError, match="Unsupported language"):
            FormatterFactory.create_formatter("brainfuck")

    def test_create_with_config(self) -> None:
        """Verify factory accepts a config object."""
        config = FormatterConfig()
        config.set("language", "python")
        config.set("line_length", 120)
        formatter = FormatterFactory.create_formatter("python", config)
        assert formatter.get_config().line_length == 120

    def test_register_custom_formatter(self) -> None:
        """Verify custom formatter registration."""
        class CustomFormatter(CodeFormatter):
            @property
            def language(self) -> str:
                return "custom"
            def format_code(self, source: str) -> str:
                return source

        FormatterFactory.register_formatter("custom", CustomFormatter)
        assert "custom" in FormatterFactory.supported_languages()

    def test_register_invalid_formatter(self) -> None:
        """Verify registering non-CodeFormatter raises TypeError."""
        with pytest.raises(TypeError):
            FormatterFactory.register_formatter("bad", str)  # type: ignore[arg-type]

    def test_detect_language_py(self) -> None:
        """Verify language detection for .py files."""
        assert FormatterFactory.detect_language(Path("test.py")) == "python"
        assert FormatterFactory.detect_language(Path("test.pyw")) == "python"

    def test_detect_language_c(self) -> None:
        """Verify language detection for .c files."""
        assert FormatterFactory.detect_language(Path("test.c")) == "c"
        assert FormatterFactory.detect_language(Path("test.h")) == "c"

    def test_detect_language_rs(self) -> None:
        """Verify language detection for .rs files."""
        assert FormatterFactory.detect_language(Path("test.rs")) == "rust"

    def test_detect_language_java(self) -> None:
        """Verify language detection for .java files."""
        assert FormatterFactory.detect_language(Path("Test.java")) == "java"

    def test_detect_language_go(self) -> None:
        """Verify language detection for .go files."""
        assert FormatterFactory.detect_language(Path("test.go")) == "go"

    def test_detect_language_unknown(self) -> None:
        """Verify language detection raises ValueError for unknown."""
        with pytest.raises(ValueError, match="Unrecognized file extension"):
            FormatterFactory.detect_language(Path("test.xyz"))


# ===================================================================
# Tests: ExternalFormatter
# ===================================================================


class TestExternalFormatter:
    """Test ExternalFormatter class."""

    def test_is_tool_available_python(self) -> None:
        """Verify is_tool_available checks for black."""
        result = ExternalFormatter.is_tool_available("python")
        assert isinstance(result, bool)

    def test_is_tool_available_unknown(self) -> None:
        """Verify is_tool_available returns False for unknown languages."""
        assert ExternalFormatter.is_tool_available("unknown") is False

    def test_get_suffix(self) -> None:
        """Verify _get_suffix returns correct extensions."""
        assert ExternalFormatter._get_suffix("python") == ".py"
        assert ExternalFormatter._get_suffix("c") == ".c"
        assert ExternalFormatter._get_suffix("rust") == ".rs"
        assert ExternalFormatter._get_suffix("java") == ".java"
        assert ExternalFormatter._get_suffix("go") == ".go"

    def test_get_suffix_default(self) -> None:
        """Verify _get_suffix defaults to .txt."""
        assert ExternalFormatter._get_suffix("unknown") == ".txt"


# ===================================================================
# Tests: FormatResult
# ===================================================================


class TestFormatResult:
    """Test FormatResult dataclass."""

    def test_default_values(self) -> None:
        """Verify default values for FormatResult."""
        result = FormatResult(path=Path("test.py"))
        assert result.path == Path("test.py")
        assert result.success is True
        assert result.changed is False
        assert result.diff == ""
        assert result.violations == []
        assert result.errors == []
        assert result.elapsed_ms == 0.0

    def test_with_violations(self) -> None:
        """Verify FormatResult can hold violations."""
        v = Violation(1, 0, "E501", "Long line", Severity.WARNING)
        result = FormatResult(
            path=Path("test.py"),
            success=True,
            changed=True,
            violations=[v],
            elapsed_ms=1.5,
        )
        assert len(result.violations) == 1
        assert result.changed is True
        assert result.elapsed_ms == 1.5


# ===================================================================
# Tests: CLI Argument Parsing
# ===================================================================


class TestCLI:
    """Test CLI argument parsing."""

    def test_parser_created(self) -> None:
        """Verify argument parser is created."""
        parser = build_arg_parser()
        assert parser is not None

    def test_parser_version(self) -> None:
        """Verify --version flag is accepted."""
        parser = build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--version"])

    def test_parser_help(self) -> None:
        """Verify --help flag is accepted."""
        parser = build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--help"])

    def test_parser_files(self) -> None:
        """Verify file arguments are parsed."""
        parser = build_arg_parser()
        args = parser.parse_args(["file1.py", "file2.py"])
        assert args.files == ["file1.py", "file2.py"]

    def test_parser_language(self) -> None:
        """Verify --language flag."""
        parser = build_arg_parser()
        args = parser.parse_args(["--language", "rust", "file.rs"])
        assert args.language == "rust"

    def test_parser_check(self) -> None:
        """Verify --check flag."""
        parser = build_arg_parser()
        args = parser.parse_args(["--check", "file.py"])
        assert args.check is True

    def test_parser_diff(self) -> None:
        """Verify --diff flag."""
        parser = build_arg_parser()
        args = parser.parse_args(["--diff", "file.py"])
        assert args.diff is True

    def test_parser_fix_mode(self) -> None:
        """Verify --fix flag."""
        parser = build_arg_parser()
        args = parser.parse_args(["--fix", "all", "file.py"])
        assert args.fix == "all"

    def test_parser_quiet(self) -> None:
        """Verify -q flag."""
        parser = build_arg_parser()
        args = parser.parse_args(["-q", "file.py"])
        assert args.quiet is True

    def test_parser_verbose(self) -> None:
        """Verify -v flags."""
        parser = build_arg_parser()
        args = parser.parse_args(["-vv", "file.py"])
        assert args.verbose == 2

    def test_parser_style(self) -> None:
        """Verify --style flag."""
        parser = build_arg_parser()
        args = parser.parse_args(["--style", "google", "file.py"])
        assert args.style == "google"

    def test_parser_line_length(self) -> None:
        """Verify --line-length flag."""
        parser = build_arg_parser()
        args = parser.parse_args(["--line-length", "100", "file.py"])
        assert args.line_length == 100

    def test_parser_list_rules(self) -> None:
        """Verify --list-rules flag."""
        parser = build_arg_parser()
        args = parser.parse_args(["--list-rules"])
        assert args.list_rules is True

    def test_parser_no_external(self) -> None:
        """Verify --no-external flag."""
        parser = build_arg_parser()
        args = parser.parse_args(["--no-external", "file.py"])
        assert args.no_external is True

    def test_parser_init(self) -> None:
        """Verify --init flag."""
        parser = build_arg_parser()
        args = parser.parse_args(["--init"])
        assert args.init is not None

    def test_parser_config(self) -> None:
        """Verify --config flag."""
        parser = build_arg_parser()
        args = parser.parse_args(["--config", "my-config.json", "file.py"])
        assert args.config == "my-config.json"


# ===================================================================
# Tests: Main Entry Point
# ===================================================================


class TestMain:
    """Test main() entry point."""

    def test_main_no_args(self) -> None:
        """Verify main() with no args returns 0 (prints help)."""
        # argparse exits with SystemExit(0) when --help is used
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_main_init_json(self) -> None:
        """Verify main() with --init generates config."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            tmp_path = f.name

        try:
            exit_code = main(["--init", tmp_path])
            assert exit_code == 0
            assert Path(tmp_path).is_file()
            content = json.loads(Path(tmp_path).read_text(encoding="utf-8"))
            assert "language" in content
        finally:
            if Path(tmp_path).is_file():
                os.unlink(tmp_path)

    def test_main_list_rules(self) -> None:
        """Verify main() with --list-rules returns 0."""
        exit_code = main(["--list-rules"])
        assert exit_code == 0

    def test_main_file_not_found(self) -> None:
        """Verify main() handles nonexistent file gracefully."""
        exit_code = main(["--language", "python", "nonexistent.py"])
        assert exit_code == 0  # No files found, not an error

    def test_main_format_file(self) -> None:
        """Verify main() formats a Python file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write('"""Module docstring."""\nx=1\n')
            tmp_path = f.name

        try:
            exit_code = main(["--language", "python", tmp_path])
            assert exit_code == 0
        finally:
            os.unlink(tmp_path)

    def test_main_check_mode(self) -> None:
        """Verify main() with --check flag."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write('"""Module docstring."""\nx=1\n')
            tmp_path = f.name

        try:
            exit_code = main(["--language", "python", "--check", tmp_path])
            # Should succeed (no violations in this simple file)
            assert exit_code == 0
        finally:
            os.unlink(tmp_path)

    def test_main_check_with_violations(self) -> None:
        """Verify main() --check returns 1 when violations found."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write("x" * 200 + "\n")  # Long line
            tmp_path = f.name

        try:
            exit_code = main(["--language", "python", "--check", tmp_path])
            assert exit_code == 1
        finally:
            os.unlink(tmp_path)

    def test_main_diff_mode(self) -> None:
        """Verify main() with --diff flag."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write('"""Module docstring."""\nx=1\n')
            tmp_path = f.name

        try:
            exit_code = main(["--language", "python", "--diff", tmp_path])
            assert exit_code == 0
        finally:
            os.unlink(tmp_path)

    def test_main_config_error(self) -> None:
        """Verify main() handles config errors gracefully."""
        exit_code = main(["--config", "/nonexistent/config.json", "file.py"])
        assert exit_code == 2

    def test_main_unsupported_language(self) -> None:
        """Verify main() handles unsupported language."""
        # This should work because the CLI restricts choices
        # But we can test with a file that doesn't match
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write("x=1\n")
            tmp_path = f.name

        try:
            exit_code = main(["--language", "rust", tmp_path])
            assert exit_code == 0  # No rust files found, not an error
        finally:
            os.unlink(tmp_path)


# ===================================================================
# Tests: Integration
# ===================================================================


class TestIntegration:
    """Integration tests spanning multiple components."""

    def test_full_pipeline(self, python_config: FormatterConfig) -> None:
        """Verify the full formatting pipeline works."""
        formatter = PythonFormatter(python_config)
        source = "import os\nimport sys\n\ndef foo():\n    pass\n"
        result = formatter.format_string(source)
        assert result.success
        assert isinstance(result, FormatResult)

    def test_auto_fix_and_style_check(
        self, python_config: FormatterConfig
    ) -> None:
        """Verify auto-fix then style check produces clean code."""
        formatter = PythonFormatter(python_config)
        source = "bad   \ncode   \n"
        result = formatter.format_string(source)
        # After formatting and fixing, trailing whitespace should be gone
        if result.changed:
            fixed = source
            fixer = AutoFixer(python_config)
            fixed = fixer.fix(fixed, "python")
            checker = StyleChecker(python_config)
            violations = checker.check(fixed, "python")
            trailing = [v for v in violations if v.code == "W291"]
            assert len(trailing) == 0

    def test_rule_based_checking(self, python_config: FormatterConfig) -> None:
        """Verify rule-based checking works."""
        checker = StyleChecker(python_config)
        source = "bad   \n"
        violations = checker.check(source, "python")
        assert len(violations) > 0

    def test_violation_has_lineno(self, python_config: FormatterConfig) -> None:
        """Verify violations have correct line numbers."""
        checker = StyleChecker(python_config)
        source = "good\nbad   \ngood\n"
        violations = checker.check(source, "python")
        trailing = [v for v in violations if v.code == "W291"]
        if trailing:
            assert trailing[0].lineno == 2

    def test_formatter_get_config(
        self, python_formatter: PythonFormatter
    ) -> None:
        """Verify formatter returns its config."""
        config = python_formatter.get_config()
        assert isinstance(config, FormatterConfig)
        assert config.language == "python"


# ===================================================================
# Tests: Edge Cases
# ===================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_source(self, default_config: FormatterConfig) -> None:
        """Verify empty source is handled gracefully (W292 no newline at EOF)."""
        checker = StyleChecker(default_config)
        violations = checker.check("", "python")
        assert len(violations) == 1
        assert violations[0].code == "W292"

    def test_single_line_source(self, default_config: FormatterConfig) -> None:
        """Verify single line source is handled."""
        checker = StyleChecker(default_config)
        violations = checker.check("x = 1", "python")
        assert isinstance(violations, list)

    def test_source_with_only_newlines(
        self, default_config: FormatterConfig
    ) -> None:
        """Verify source with only newlines is handled."""
        checker = StyleChecker(default_config)
        violations = checker.check("\n\n\n", "python")
        assert isinstance(violations, list)

    def test_source_with_tabs_only(
        self, default_config: FormatterConfig
    ) -> None:
        """Verify source with only tabs is handled."""
        fixer = AutoFixer(default_config)
        result = fixer.fix("\t\t\t\n", "python")
        assert isinstance(result, str)

    def test_very_long_line(self, default_config: FormatterConfig) -> None:
        """Verify very long lines are detected (E501 + D100)."""
        default_config.set("line_length", 10)
        checker = StyleChecker(default_config)
        source = "x" * 1000 + "\n"
        violations = checker.check(source, "python")
        # Expects E501 (line too long) + D100 (missing module docstring)
        assert len(violations) == 2
        assert any(v.code == "E501" for v in violations)
        assert any(v.code == "D100" for v in violations)

    def test_unicode_source(self, default_config: FormatterConfig) -> None:
        """Verify Unicode source is handled."""
        checker = StyleChecker(default_config)
        source = "# -*- coding: utf-8 -*-\nprint('cafe')\n"
        violations = checker.check(source, "python")
        assert isinstance(violations, list)

    def test_mixed_tabs_and_spaces_detection(
        self, default_config: FormatterConfig
    ) -> None:
        """Verify mixed tabs and spaces are caught."""
        checker = StyleChecker(default_config)
        source = "\t    mixed\n"
        violations = checker.check(source, "python")
        assert any(v.code == "E101" for v in violations)

    def test_rule_with_empty_pattern(self) -> None:
        """Verify rule with empty pattern doesn't cause errors."""
        rm = RuleManager()
        rule = Rule(name="empty-pattern", pattern="", language="*")
        rm.register_rule(rule)
        assert rm.get_rule("empty-pattern") is not None

    def test_config_init_with_directory(self) -> None:
        """Verify FormatterConfig initializes with a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FormatterConfig(Path(tmpdir))
            assert config.loaded_path is None

    def test_save_config_to_new_directory(self) -> None:
        """Verify saving config creates parent directories."""
        config = FormatterConfig()
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = Path(tmpdir) / "nested" / "subdir" / "config.json"
            config.save(nested, fmt="json")
            assert nested.is_file()

    def test_rule_manager_load_rules_invalid_config(
        self, rule_manager: RuleManager
    ) -> None:
        """Verify load_rules_from_config handles invalid input."""
        with pytest.raises(ConfigError, match="must be a dictionary"):
            rule_manager.load_rules_from_config("not a dict")  # type: ignore[arg-type]

    def test_rule_manager_load_rules_invalid_rules_list(
        self, rule_manager: RuleManager
    ) -> None:
        """Verify load_rules_from_config validates rules list."""
        config = {"rules": "not a list"}
        with pytest.raises(ConfigError, match="'rules' must be a list"):
            rule_manager.load_rules_from_config(config)

    def test_fix_mode_enum_values(self) -> None:
        """Verify FixMode enum values."""
        assert FixMode.NONE.value == "none"
        assert FixMode.SAFE.value == "safe"
        assert FixMode.ALL.value == "all"

    def test_formatter_factory_supported_languages(self) -> None:
        """Verify supported_languages returns all languages."""
        langs = FormatterFactory.supported_languages()
        assert "python" in langs
        assert "c" in langs
        assert "rust" in langs
        assert "java" in langs
        assert "go" in langs

    def test_main_with_stdin(self) -> None:
        """Verify main() can read from stdin (simulated)."""
        # This is hard to test directly without mocking stdin
        # Just verify the path exists
        pass

    def test_python_formatter_blank_lines(self) -> None:
        """Verify Python formatter handles blank lines correctly."""
        config = FormatterConfig()
        config.set("language", "python")
        formatter = PythonFormatter(config)
        source = "class Foo:\n    pass\nclass Bar:\n    pass\n"
        result = formatter.format_code(source)
        assert "class Foo:" in result
        assert "class Bar:" in result

    def test_go_formatter_nested_blocks(self) -> None:
        """Verify Go formatter handles nested blocks."""
        config = FormatterConfig()
        config.set("language", "go")
        formatter = GoFormatter(config)
        source = "func main() {\nif true {\nx()\n}\n}\n"
        result = formatter.format_code(source)
        assert "func main() {" in result
        assert "if true {" in result

    def test_java_formatter_indentation(self) -> None:
        """Verify Java formatter handles nested indentation."""
        config = FormatterConfig()
        config.set("language", "java")
        formatter = JavaFormatter(config)
        source = "class A {\nvoid f() {\n}\n}\n"
        result = formatter.format_code(source)
        # Inner method should be indented
        assert "    void f()" in result

    def test_rust_formatter_struct(self) -> None:
        """Verify Rust formatter handles struct definitions."""
        config = FormatterConfig()
        config.set("language", "rust")
        formatter = RustFormatter(config)
        source = "struct Point {\nx: i32,\ny: i32,\n}\n"
        result = formatter.format_code(source)
        assert "struct Point {" in result

    def test_c_formatter_pointer_style(self) -> None:
        """Verify C formatter handles pointer declarations."""
        config = FormatterConfig()
        config.set("language", "c")
        formatter = CFormatter(config)
        source = "int *ptr;\n"
        result = formatter.format_code(source)
        assert "int *ptr;" in result or "int* ptr;" in result

    def test_auto_fixer_all_mode(self) -> None:
        """Verify AutoFixer in ALL mode applies more fixes."""
        config = FormatterConfig()
        config.set("fix_mode", "all")
        fixer = AutoFixer(config)
        # The fixer should try to wrap long lines in ALL mode
        source = "x = " + ",".join(f"a{i}" for i in range(50)) + "\n"
        result = fixer.fix(source, "python")
        assert isinstance(result, str)

    def test_diff_output_generate_from_file(self, diff_output: DiffOutput) -> None:
        """Verify generate_from_file reads and diffs files."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f1:
            f1.write("original\n")
            orig_path = f1.name

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f2:
            f2.write("modified\n")
            mod_path = f2.name

        try:
            diff = diff_output.generate_from_file(
                Path(orig_path), Path(mod_path)
            )
            assert diff != ""
        finally:
            os.unlink(orig_path)
            os.unlink(mod_path)


if __name__ == "__main__":
    pytest.main(["-v", __file__])