"""
Tests for Ainos Shell built-in commands.
"""

from __future__ import annotations

import os
import sys
import tempfile
import pytest
from pathlib import Path
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.builtins import (
    BUILTINS,
    BUILTIN_HELP,
    builtin_cd,
    builtin_pwd,
    builtin_echo,
    builtin_exit,
    builtin_clear,
    builtin_true,
    builtin_false,
    builtin_type,
    builtin_which,
    builtin_env,
    builtin_export,
    builtin_unset,
    builtin_alias,
    builtin_unalias,
    builtin_help,
    builtin_history,
    builtin_hostname,
    builtin_uname,
    builtin_whoami,
    builtin_date,
    builtin_sleep,
    builtin_yes,
)
from .conftest import temp_dir, temp_config_dir


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class TestBuiltinCommands:
    """Tests for built-in shell commands."""

    def test_builtins_registry(self) -> None:
        """Test that all expected builtins are registered."""
        expected_builtins = [
            "cd", "ls", "pwd", "echo", "cat", "mkdir", "rmdir", "rm",
            "cp", "mv", "touch", "head", "tail", "wc", "grep", "sort",
            "uniq", "env", "export", "unset", "set", "type", "which",
            "ps", "kill", "jobs", "fg", "bg", "exit", "clear", "help",
            "alias", "unalias", "source", "history", "date", "sleep",
            "yes", "true", "false", "hostname", "uname", "whoami",
            "id", "uptime", "cal", "df", "du", "free", "lsof", "find",
        ]
        for name in expected_builtins:
            assert name in BUILTINS, f"Builtin {name} not found in BUILTINS"

    def test_builtin_help_has_entries(self) -> None:
        """Test that all builtins have help text."""
        for name in BUILTINS:
            assert name in BUILTIN_HELP, f"Builtin {name} has no help text"

    def test_builtin_pwd(self) -> None:
        """Test pwd command."""
        code = builtin_pwd([])
        assert code == 0

    def test_builtin_echo(self) -> None:
        """Test echo command."""
        code = builtin_echo(["hello", "world"])
        assert code == 0

    def test_builtin_echo_newline(self) -> None:
        """Test echo -n."""
        code = builtin_echo(["-n", "hello"])
        assert code == 0

    def test_builtin_true(self) -> None:
        """Test true command."""
        code = builtin_true([])
        assert code == 0

    def test_builtin_false(self) -> None:
        """Test false command."""
        code = builtin_false([])
        assert code == 1

    def test_builtin_cd_valid(self, temp_dir: str) -> None:
        """Test cd to a valid directory."""
        code = builtin_cd([temp_dir])
        assert code == 0
        assert os.getcwd() == temp_dir

    def test_builtin_cd_invalid(self) -> None:
        """Test cd to an invalid directory."""
        code = builtin_cd(["/nonexistent/path"])
        assert code != 0

    def test_builtin_cd_no_args(self, temp_dir: str) -> None:
        """Test cd with no arguments."""
        # cd should go to HOME
        code = builtin_cd([])
        assert code == 0

    def test_builtin_cd_home(self) -> None:
        """Test cd ~."""
        code = builtin_cd(["~"])
        assert code == 0

    def test_builtin_type_builtin(self) -> None:
        """Test type for builtin command."""
        code = builtin_type(["echo"])
        assert code == 0

    def test_builtin_type_not_found(self) -> None:
        """Test type for non-existent command."""
        code = builtin_type(["nonexistent_cmd_xyz"])
        assert code != 0

    def test_builtin_which(self) -> None:
        """Test which command."""
        code = builtin_which(["python"])
        # May or may not succeed depending on environment
        assert code in (0, 1)

    def test_builtin_env(self) -> None:
        """Test env command."""
        code = builtin_env([])
        assert code == 0

    def test_builtin_export(self) -> None:
        """Test export command."""
        code = builtin_export(["TEST_VAR=hello"])
        assert code == 0
        assert os.environ.get("TEST_VAR") == "hello"

    def test_builtin_unset(self) -> None:
        """Test unset command."""
        os.environ["TEST_UNSET"] = "value"
        code = builtin_unset(["TEST_UNSET"])
        assert code == 0
        assert "TEST_UNSET" not in os.environ

    def test_builtin_alias(self) -> None:
        """Test alias command."""
        code = builtin_alias([])
        assert code == 0

    def test_builtin_alias_set(self) -> None:
        """Test setting an alias."""
        code = builtin_alias(["myalias=echo hello"])
        assert code == 0
        from src.config import get_alias
        assert get_alias("myalias") == "echo hello"

    def test_builtin_unalias(self) -> None:
        """Test unalias command."""
        from src.config import set_alias
        set_alias("testalias", "echo test")
        code = builtin_unalias(["testalias"])
        assert code == 0
        from src.config import get_alias
        assert get_alias("testalias") is None

    def test_builtin_help(self) -> None:
        """Test help command."""
        code = builtin_help([])
        assert code == 0

    def test_builtin_help_specific(self) -> None:
        """Test help for a specific command."""
        code = builtin_help(["echo"])
        assert code == 0

    def test_builtin_help_invalid(self) -> None:
        """Test help for invalid command."""
        code = builtin_help(["nonexistent"])
        assert code != 0

    def test_builtin_clear(self) -> None:
        """Test clear command."""
        code = builtin_clear([])
        assert code == 0

    def test_builtin_hostname(self) -> None:
        """Test hostname command."""
        code = builtin_hostname([])
        assert code == 0

    def test_builtin_uname(self) -> None:
        """Test uname command."""
        code = builtin_uname([])
        assert code == 0

    def test_builtin_uname_all(self) -> None:
        """Test uname -a."""
        code = builtin_uname(["-a"])
        assert code == 0

    def test_builtin_whoami(self) -> None:
        """Test whoami command."""
        code = builtin_whoami([])
        assert code == 0

    def test_builtin_date(self) -> None:
        """Test date command."""
        code = builtin_date([])
        assert code == 0

    def test_builtin_sleep(self) -> None:
        """Test sleep command."""
        code = builtin_sleep(["0.1"])
        assert code == 0

    def test_builtin_sleep_invalid(self) -> None:
        """Test sleep with invalid argument."""
        code = builtin_sleep(["not_a_number"])
        assert code != 0

    def test_builtin_exit(self) -> None:
        """Test exit command raises SystemExit."""
        with pytest.raises(SystemExit) as exc_info:
            builtin_exit(["0"])
        assert exc_info.value.code == 0

    def test_builtin_exit_code(self) -> None:
        """Test exit with specific code."""
        with pytest.raises(SystemExit) as exc_info:
            builtin_exit(["42"])
        assert exc_info.value.code == 42


# ---------------------------------------------------------------------------
# cd tests
# ---------------------------------------------------------------------------


class TestCd:
    """Detailed tests for cd command."""

    def test_cd_to_temp(self, temp_dir: str) -> None:
        """Test cd to temp directory."""
        original = os.getcwd()
        code = builtin_cd([temp_dir])
        assert code == 0
        assert os.getcwd() == temp_dir
        os.chdir(original)


# ---------------------------------------------------------------------------
# echo tests
# ---------------------------------------------------------------------------


class TestEcho:
    """Detailed tests for echo command."""

    def test_echo_multiple_args(self) -> None:
        """Test echo with multiple arguments."""
        code = builtin_echo(["hello", "world", "test"])
        assert code == 0

    def test_echo_empty(self) -> None:
        """Test echo with no arguments."""
        code = builtin_echo([])
        assert code == 0

    def test_echo_special_chars(self) -> None:
        """Test echo with special characters."""
        code = builtin_echo(["hello", "&&", "world"])
        assert code == 0


# ---------------------------------------------------------------------------
# true/false tests
# ---------------------------------------------------------------------------


class TestTrueFalse:
    """Tests for true and false commands."""

    def test_true(self) -> None:
        """Test true returns 0."""
        assert builtin_true([]) == 0

    def test_false(self) -> None:
        """Test false returns 1."""
        assert builtin_false([]) == 1

    def test_true_with_args(self) -> None:
        """Test true with arguments."""
        assert builtin_true(["anything"]) == 0

    def test_false_with_args(self) -> None:
        """Test false with arguments."""
        assert builtin_false(["anything"]) == 1


# ---------------------------------------------------------------------------
# type tests
# ---------------------------------------------------------------------------


class TestType:
    """Tests for type command."""

    def test_type_builtins(self) -> None:
        """Test type for various builtins."""
        for cmd in ["cd", "ls", "echo", "pwd", "exit"]:
            assert builtin_type([cmd]) == 0


# ---------------------------------------------------------------------------
# alias/unalias tests
# ---------------------------------------------------------------------------


class TestAlias:
    """Tests for alias and unalias commands."""

    def setup_method(self) -> None:
        """Clean up before each test."""
        from src.config import get_config
        # Don't interfere with real aliases
        pass

    def test_alias_set_and_get(self) -> None:
        """Test setting and getting an alias."""
        from src.config import set_alias, get_alias, unset_alias
        set_alias("testalias1", "echo test1")
        assert get_alias("testalias1") == "echo test1"
        unset_alias("testalias1")

    def test_unalias_all(self) -> None:
        """Test unalias -a."""
        code = builtin_unalias(["-a"])
        assert code == 0


# ---------------------------------------------------------------------------
# export/unset tests
# ---------------------------------------------------------------------------


class TestExportUnset:
    """Tests for export and unset commands."""

    def test_export_set(self) -> None:
        """Test export sets environment variable."""
        assert builtin_export(["MYVAR=testval"]) == 0
        assert os.environ.get("MYVAR") == "testval"
        del os.environ["MYVAR"]

    def test_export_list(self) -> None:
        """Test export lists variables."""
        assert builtin_export([]) == 0

    def test_export_invalid(self) -> None:
        """Test export with invalid syntax."""
        assert builtin_export(["=value"]) == 0  # Should not error

    def test_unset_nonexistent(self) -> None:
        """Test unset of non-existent variable."""
        assert builtin_unset(["NONEXISTENT_VAR_XYZ"]) == 0


# ---------------------------------------------------------------------------
# Builtin registry tests
# ---------------------------------------------------------------------------


class TestBuiltinRegistry:
    """Tests for the builtin command registry."""

    def test_all_builtins_callable(self) -> None:
        """Test that all registered builtins are callable."""
        for name, func in BUILTINS.items():
            assert callable(func), f"Builtin {name} is not callable"

    def test_builtin_count(self) -> None:
        """Test that there are enough builtins."""
        assert len(BUILTINS) >= 40, f"Expected at least 40 builtins, got {len(BUILTINS)}"

    def test_all_help_texts(self) -> None:
        """Test that all help texts are non-empty."""
        for name, help_text in BUILTIN_HELP.items():
            assert len(help_text) > 0, f"Help text for {name} is empty"
            assert ":" in help_text, f"Help text for {name} missing colon separator"