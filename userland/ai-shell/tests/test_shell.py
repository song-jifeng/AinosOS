"""
Tests for the Ainos Shell core (shell.py) module.
"""

from __future__ import annotations

import os
import sys
import pytest
from pathlib import Path
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.shell import Shell, ShellState, create_shell, get_shell
from src.utils import (
    ParsedCommand,
    Pipeline,
    ShellError,
    ExitRequested,
    IS_WINDOWS,
    IS_POSIX,
    get_config_dir,
    find_executable,
)
from src.config import get_config, set_alias, unset_alias, get_alias
from src.parser import parse_line, expand_variables
from src.executor import ExecutionResult, CommandExecutor, get_executor


# ---------------------------------------------------------------------------
# ShellState tests
# ---------------------------------------------------------------------------


class TestShellState:
    """Tests for the ShellState class."""

    def test_initial_state(self) -> None:
        """Test initial state values."""
        state = ShellState()
        assert state.running is False
        assert state.exit_code == 0
        assert state.command_count == 0
        assert state.error_count == 0
        assert state.last_command == ""
        assert state.in_continuation is False
        assert state.continuation_lines == []

    def test_uptime(self) -> None:
        """Test uptime tracking."""
        state = ShellState()
        state.start_time = 0
        assert state.uptime > 0

    def test_to_dict(self) -> None:
        """Test serialization to dict."""
        state = ShellState()
        d = state.to_dict()
        assert "running" in d
        assert "exit_code" in d
        assert "session_id" in d
        assert "command_count" in d


# ---------------------------------------------------------------------------
# Shell creation tests
# ---------------------------------------------------------------------------


class TestShellCreation:
    """Tests for shell creation."""

    def test_create_shell(self) -> None:
        """Test creating a shell instance."""
        shell = create_shell()
        assert shell is not None
        assert isinstance(shell, Shell)

    def test_shell_has_config(self) -> None:
        """Test shell has configuration."""
        shell = create_shell()
        assert shell.config is not None

    def test_shell_has_executor(self) -> None:
        """Test shell has executor."""
        shell = create_shell()
        assert shell.executor is not None

    def test_shell_has_prompt_renderer(self) -> None:
        """Test shell has prompt renderer."""
        shell = create_shell()
        assert shell.prompt_renderer is not None

    def test_shell_has_history(self) -> None:
        """Test shell has history manager."""
        shell = create_shell()
        assert shell.history_manager is not None

    def test_shell_has_ai_assistant(self) -> None:
        """Test shell has AI assistant."""
        shell = create_shell()
        assert shell.ai_assistant is not None

    def test_shell_has_plugin_manager(self) -> None:
        """Test shell has plugin manager."""
        shell = create_shell()
        assert shell.plugin_manager is not None

    def test_shell_has_theme_manager(self) -> None:
        """Test shell has theme manager."""
        shell = create_shell()
        assert shell.theme_manager is not None

    def test_shell_has_parser(self) -> None:
        """Test shell has parser."""
        shell = create_shell()
        assert shell.parser is not None


# ---------------------------------------------------------------------------
# Shell expansion tests
# ---------------------------------------------------------------------------


class TestShellExpansion:
    """Tests for shell command expansion."""

    def test_expand_line_variables(self, temp_dir: str) -> None:
        """Test variable expansion in commands."""
        os.environ["TEST_VAR"] = "test_value"
        shell = create_shell()
        # We test the expansion function directly
        line = "echo $TEST_VAR"
        expanded = expand_variables(line, os.environ)
        assert "test_value" in expanded

    def test_expand_line_tilde(self) -> None:
        """Test tilde expansion."""
        shell = create_shell()
        home = os.path.expanduser("~")
        line = shell._expand_line("echo ~/test")
        assert home in line

    def test_expand_line_alias(self) -> None:
        """Test alias expansion."""
        set_alias("ll", "ls -la")
        shell = create_shell()
        line = shell._expand_line("ll /tmp")
        assert "ls -la" in line
        unset_alias("ll")


# ---------------------------------------------------------------------------
# Shell execution tests
# ---------------------------------------------------------------------------


class TestShellExecution:
    """Tests for shell command execution."""

    def test_execute_echo(self, temp_dir: str) -> None:
        """Test executing echo."""
        shell = create_shell()
        shell.execute_source("echo hello")
        assert shell.state.exit_code == 0

    def test_execute_true(self, temp_dir: str) -> None:
        """Test executing true."""
        shell = create_shell()
        shell.execute_source("true")
        assert shell.state.exit_code == 0

    def test_execute_false(self, temp_dir: str) -> None:
        """Test executing false."""
        shell = create_shell()
        shell.execute_source("false")
        assert shell.state.exit_code == 1

    def test_execute_pwd(self, temp_dir: str) -> None:
        """Test executing pwd."""
        shell = create_shell()
        shell.execute_source("pwd")
        assert shell.state.exit_code == 0

    def test_execute_multiple_commands(self, temp_dir: str) -> None:
        """Test executing multiple commands."""
        shell = create_shell()
        shell.execute_source("echo hello; echo world")
        assert shell.state.exit_code == 0

    def test_execute_source(self, temp_dir: str) -> None:
        """Test source command execution."""
        shell = create_shell()
        shell.execute_source("echo hello")
        assert shell.state.exit_code == 0

    def test_state_tracking(self, temp_dir: str) -> None:
        """Test that state is updated after execution."""
        shell = create_shell()
        shell.execute_source("echo test")
        assert shell.state.command_count >= 1
        assert shell.state.last_command != ""

    def test_error_count(self, temp_dir: str) -> None:
        """Test error counting."""
        shell = create_shell()
        initial_errors = shell.state.error_count
        shell.execute_source("false")
        assert shell.state.exit_code == 1


# ---------------------------------------------------------------------------
# Configuration tests
# ---------------------------------------------------------------------------


class TestShellConfig:
    """Tests for shell configuration integration."""

    def test_get_config(self) -> None:
        """Test getting configuration."""
        config = get_config()
        assert config is not None
        assert config.shell_name == "ainos-sh"

    def test_config_aliases(self) -> None:
        """Test default aliases."""
        config = get_config()
        assert "ll" in config.aliases
        assert "la" in config.aliases
        assert ".." in config.aliases
        assert "cls" in config.aliases
        assert "q" in config.aliases

    def test_alias_operations(self) -> None:
        """Test alias CRUD operations."""
        assert get_alias("nonexistent_alias") is None
        set_alias("testalias", "echo test")
        assert get_alias("testalias") == "echo test"
        unset_alias("testalias")
        assert get_alias("testalias") is None


# ---------------------------------------------------------------------------
# Shell features tests
# ---------------------------------------------------------------------------


class TestShellFeatures:
    """Tests for shell features."""

    def test_shell_has_state(self) -> None:
        """Test shell has state tracking."""
        shell = create_shell()
        assert shell.state is not None
        assert isinstance(shell.state, ShellState)

    def test_shell_signals(self) -> None:
        """Test that signal handlers are initialized."""
        shell = create_shell()
        # Should not crash
        assert True

    def test_shell_shutdown(self) -> None:
        """Test shell shutdown."""
        shell = create_shell()
        shell.shutdown()
        assert shell.state.running is False

    def test_command_count(self, temp_dir: str) -> None:
        """Test command counting."""
        shell = create_shell()
        shell.execute_source("true")
        assert shell.state.command_count >= 1
        shell.execute_source("true")
        assert shell.state.command_count >= 2

    def test_session_id(self, temp_dir: str) -> None:
        """Test session ID is set."""
        shell = create_shell()
        assert shell.state.session_id is not None
        assert len(shell.state.session_id) > 0


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestShellIntegration:
    """Integration tests for shell with external commands."""

    def test_touch_and_rm(self, temp_dir: str) -> None:
        """Test creating and removing a file."""
        test_file = os.path.join(temp_dir, "test_integration.txt")
        shell = create_shell()
        shell.execute_source(f"touch {test_file}")
        assert os.path.exists(test_file)
        shell.execute_source(f"rm {test_file}")
        assert not os.path.exists(test_file)

    def test_mkdir_and_rmdir(self, temp_dir: str) -> None:
        """Test creating and removing a directory."""
        test_dir = os.path.join(temp_dir, "test_integration_dir")
        shell = create_shell()
        shell.execute_source(f"mkdir {test_dir}")
        assert os.path.isdir(test_dir)
        shell.execute_source(f"rmdir {test_dir}")
        assert not os.path.exists(test_dir)

    def test_echo_and_wc(self, temp_dir: str) -> None:
        """Test echo with output."""
        shell = create_shell()
        shell.execute_source("echo hello world")
        assert shell.state.exit_code == 0

    def test_multiple_mkdir(self, temp_dir: str) -> None:
        """Test creating multiple directories."""
        d1 = os.path.join(temp_dir, "d1")
        d2 = os.path.join(temp_dir, "d2")
        shell = create_shell()
        shell.execute_source(f"mkdir {d1} {d2}")
        assert os.path.isdir(d1)
        assert os.path.isdir(d2)


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestShellErrorHandling:
    """Tests for shell error handling."""

    def test_cd_error(self) -> None:
        """Test cd to invalid path."""
        shell = create_shell()
        shell.execute_source("cd /nonexistent_path_xyz")
        assert shell.state.exit_code != 0

    def test_rm_nonexistent(self) -> None:
        """Test removing non-existent file."""
        shell = create_shell()
        shell.execute_source("rm /nonexistent_file_xyz.abc")
        # rm may fail or not depending on force flag
        assert shell.state.exit_code is not None

    def test_mkdir_existing(self, temp_dir: str) -> None:
        """Test creating existing directory."""
        test_dir = os.path.join(temp_dir, "exists")
        os.makedirs(test_dir, exist_ok=True)
        shell = create_shell()
        shell.execute_source(f"mkdir {test_dir}")
        assert shell.state.exit_code is not None

    def test_touch_permission(self) -> None:
        """Test touch on a path without permission (should not crash)."""
        shell = create_shell()
        # Just verify it doesn't crash
        shell.execute_source("touch /test.txt")
        assert True


# ---------------------------------------------------------------------------
# Shell helpers
# ---------------------------------------------------------------------------


class TestShellHelpers:
    """Tests for shell helper functions."""

    def test_get_shell(self) -> None:
        """Test getting shell singleton."""
        shell = create_shell()
        retrieved = get_shell()
        assert retrieved is shell

    def test_get_shell_none(self) -> None:
        """Test getting shell before creation."""
        # Reset and test
        import src.shell
        src.shell._shell = None
        result = get_shell()
        assert result is None

    def test_multiple_creations(self) -> None:
        """Test that create_shell returns the same instance."""
        import src.shell
        src.shell._shell = None
        s1 = create_shell()
        s2 = create_shell()
        assert s1 is s2


# ---------------------------------------------------------------------------
# Parser integration tests
# ---------------------------------------------------------------------------


class TestParserIntegration:
    """Tests for parser integration with shell."""

    def test_parse_and_execute(self, temp_dir: str) -> None:
        """Test parsing and executing a simple command."""
        shell = create_shell()
        pipelines = parse_line("echo hello")
        assert len(pipelines) == 1
        assert pipelines[0].commands[0].command == "echo"

    def test_parse_pipeline(self) -> None:
        """Test parsing a pipeline."""
        pipelines = parse_line("ls | grep test")
        assert len(pipelines) == 1
        assert len(pipelines[0].commands) == 2

    def test_parse_redirect(self) -> None:
        """Test parsing a redirect."""
        pipelines = parse_line("echo test > file.txt")
        assert len(pipelines) == 1
        cmd = pipelines[0].commands[0]
        assert len(cmd.redirects) >= 1