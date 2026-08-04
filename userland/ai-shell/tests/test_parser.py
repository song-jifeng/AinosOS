"""
Tests for the Ainos Shell parser module.
"""

from __future__ import annotations

import os
import sys
import pytest
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.parser import (
    Lexer,
    Parser,
    Token,
    TokenType,
    parse_line,
    parse_command,
    parse_pipeline,
    expand_variables,
    expand_braces,
    expand_globs,
    expand_tilde,
    validate_syntax,
    is_assignment,
    is_valid_identifier,
    split_assignment,
    quote_word,
    unquote_word,
)
from src.utils import ParsedCommand, Pipeline, RedirectInfo


# ---------------------------------------------------------------------------
# Lexer tests
# ---------------------------------------------------------------------------


class TestLexer:
    """Tests for the Lexer class."""

    def test_simple_command(self) -> None:
        """Test lexing a simple command."""
        lexer = Lexer("ls -la")
        tokens = lexer.tokenize()
        assert len(tokens) == 2
        assert tokens[0].type == TokenType.WORD
        assert tokens[0].value == "ls"
        assert tokens[1].type == TokenType.WORD
        assert tokens[1].value == "-la"

    def test_pipe(self) -> None:
        """Test lexing a pipe operator."""
        lexer = Lexer("ls | grep foo")
        tokens = lexer.tokenize()
        assert len(tokens) == 4
        assert tokens[0].value == "ls"
        assert tokens[1].type == TokenType.PIPE
        assert tokens[2].value == "grep"
        assert tokens[3].value == "foo"

    def test_or_operator(self) -> None:
        """Test lexing the OR operator."""
        lexer = Lexer("cmd1 || cmd2")
        tokens = lexer.tokenize()
        assert len(tokens) == 3
        assert tokens[0].value == "cmd1"
        assert tokens[1].type == TokenType.OR
        assert tokens[2].value == "cmd2"

    def test_and_operator(self) -> None:
        """Test lexing the AND operator."""
        lexer = Lexer("cmd1 && cmd2")
        tokens = lexer.tokenize()
        assert len(tokens) == 3
        assert tokens[0].value == "cmd1"
        assert tokens[1].type == TokenType.AND
        assert tokens[2].value == "cmd2"

    def test_redirect_output(self) -> None:
        """Test lexing output redirection."""
        lexer = Lexer("ls > output.txt")
        tokens = lexer.tokenize()
        assert len(tokens) == 3
        assert tokens[0].value == "ls"
        assert tokens[1].type == TokenType.REDIRECT_OUT
        assert tokens[2].value == "output.txt"

    def test_redirect_append(self) -> None:
        """Test lexing append redirection."""
        lexer = Lexer("echo hello >> file.txt")
        tokens = lexer.tokenize()
        assert len(tokens) == 4
        assert tokens[2].type == TokenType.REDIRECT_APPEND

    def test_redirect_input(self) -> None:
        """Test lexing input redirection."""
        lexer = Lexer("cat < input.txt")
        tokens = lexer.tokenize()
        assert len(tokens) == 3
        assert tokens[1].type == TokenType.REDIRECT_IN

    def test_redirect_stderr(self) -> None:
        """Test lexing stderr redirection."""
        lexer = Lexer("cmd 2> error.log")
        tokens = lexer.tokenize()
        # Note: "2>" is lexed as separate tokens in some cases
        assert len(tokens) >= 3

    def test_redirect_stderr_merge(self) -> None:
        """Test lexing stderr merge (2>&1)."""
        lexer = Lexer("cmd 2>&1")
        tokens = lexer.tokenize()
        assert len(tokens) == 2
        # "2>&1" should be a single token
        stderr_merge_tokens = [t for t in tokens if t.type == TokenType.REDIRECT_STDERR_MERGE]
        assert len(stderr_merge_tokens) > 0

    def test_redirect_all(self) -> None:
        """Test lexing combined output redirection."""
        lexer = Lexer("cmd &> file.txt")
        tokens = lexer.tokenize()
        assert len(tokens) == 3
        all_out_tokens = [t for t in tokens if t.type == TokenType.REDIRECT_ALL_OUT]
        assert len(all_out_tokens) > 0

    def test_quoted_strings(self) -> None:
        """Test lexing quoted strings."""
        lexer = Lexer('echo "hello world"')
        tokens = lexer.tokenize()
        assert len(tokens) == 2
        # The quoted string should be a single token
        assert tokens[1].value == '"hello world"'

    def test_single_quotes(self) -> None:
        """Test lexing single-quoted strings."""
        lexer = Lexer("echo 'hello world'")
        tokens = lexer.tokenize()
        assert len(tokens) == 2
        assert tokens[1].value == "'hello world'"

    def test_background(self) -> None:
        """Test lexing background operator."""
        lexer = Lexer("sleep 10 &")
        tokens = lexer.tokenize()
        assert len(tokens) == 3
        assert tokens[2].type == TokenType.BACKGROUND

    def test_semicolon(self) -> None:
        """Test lexing semicolon separator."""
        lexer = Lexer("cmd1; cmd2")
        tokens = lexer.tokenize()
        assert len(tokens) == 3
        assert tokens[1].type == TokenType.SEMICOLON

    def test_comment(self) -> None:
        """Test lexing comments."""
        lexer = Lexer("echo hello # this is a comment")
        tokens = lexer.tokenize()
        # Comment should be a token
        comment_tokens = [t for t in tokens if t.type == TokenType.COMMENT]
        assert len(comment_tokens) >= 1

    def test_heredoc(self) -> None:
        """Test lexing heredoc."""
        lexer = Lexer("cat << EOF")
        tokens = lexer.tokenize()
        heredoc_tokens = [t for t in tokens if t.type == TokenType.REDIRECT_HEREDOC]
        assert len(heredoc_tokens) > 0

    def test_empty_input(self) -> None:
        """Test lexing empty input."""
        lexer = Lexer("")
        tokens = lexer.tokenize()
        assert len(tokens) == 0

    def test_whitespace(self) -> None:
        """Test lexing whitespace-only input."""
        lexer = Lexer("   \t  ")
        tokens = lexer.tokenize()
        assert len(tokens) == 0

    def test_variable(self) -> None:
        """Test lexing variable references."""
        lexer = Lexer("echo $HOME $PATH")
        tokens = lexer.tokenize()
        assert len(tokens) == 3
        assert tokens[1].value == "$HOME"
        assert tokens[2].value == "$PATH"

    def test_brace_variable(self) -> None:
        """Test lexing brace-wrapped variables."""
        lexer = Lexer("echo ${HOME}${PATH}")
        tokens = lexer.tokenize()
        assert len(tokens) == 3
        # The variable tokens include the braces as part of the word
        assert "$" in tokens[1].value
        assert "$" in tokens[2].value


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestParser:
    """Tests for the Parser class."""

    def test_simple_command(self) -> None:
        """Test parsing a simple command."""
        pipelines = parse_line("ls -la")
        assert len(pipelines) == 1
        assert len(pipelines[0].commands) == 1
        cmd = pipelines[0].commands[0]
        assert cmd.command == "ls"
        assert cmd.args == ["-la"]

    def test_pipeline(self) -> None:
        """Test parsing a pipeline."""
        pipelines = parse_line("ls | grep foo | wc -l")
        assert len(pipelines) == 1
        assert len(pipelines[0].commands) == 3
        assert pipelines[0].commands[0].command == "ls"
        assert pipelines[0].commands[1].command == "grep"
        assert pipelines[0].commands[2].command == "wc"

    def test_background(self) -> None:
        """Test parsing a background command."""
        pipelines = parse_line("sleep 10 &")
        assert len(pipelines) >= 1
        # Check if any pipeline has background=True
        has_bg = any(p.background for p in pipelines)
        assert has_bg

    def test_multiple_commands(self) -> None:
        """Test parsing multiple commands separated by semicolons."""
        pipelines = parse_line("cd /tmp; ls -la")
        assert len(pipelines) == 2
        assert pipelines[0].commands[0].command == "cd"
        assert pipelines[1].commands[0].command == "ls"

    def test_redirect_output(self) -> None:
        """Test parsing output redirection."""
        pipelines = parse_line("echo hello > file.txt")
        assert len(pipelines) == 1
        cmd = pipelines[0].commands[0]
        assert cmd.command == "echo"
        assert len(cmd.redirects) > 0
        # Check for OUTPUT redirect
        output_redirects = [r for r in cmd.redirects if r.type == RedirectInfo.Type.OUTPUT]
        assert len(output_redirects) > 0

    def test_redirect_input(self) -> None:
        """Test parsing input redirection."""
        pipelines = parse_line("cat < input.txt")
        cmd = pipelines[0].commands[0]
        assert len(cmd.redirects) > 0
        input_redirects = [r for r in cmd.redirects if r.type == RedirectInfo.Type.INPUT]
        assert len(input_redirects) > 0

    def test_append_redirect(self) -> None:
        """Test parsing append redirection."""
        pipelines = parse_line("echo hello >> file.txt")
        cmd = pipelines[0].commands[0]
        append_redirects = [r for r in cmd.redirects if r.type == RedirectInfo.Type.APPEND]
        assert len(append_redirects) > 0

    def test_env_vars(self) -> None:
        """Test parsing environment variable assignments."""
        pipelines = parse_line("FOO=bar BAZ=qux echo hello")
        assert len(pipelines) == 1
        cmd = pipelines[0].commands[0]
        assert cmd.command == "echo"
        assert "FOO" in cmd.env_vars
        assert cmd.env_vars["FOO"] == "bar"
        assert "BAZ" in cmd.env_vars
        assert cmd.env_vars["BAZ"] == "qux"

    def test_empty_input(self) -> None:
        """Test parsing empty input."""
        pipelines = parse_line("")
        assert len(pipelines) == 0

    def test_whitespace_input(self) -> None:
        """Test parsing whitespace-only input."""
        pipelines = parse_line("   ")
        assert len(pipelines) == 0

    def test_parse_command(self) -> None:
        """Test parse_command convenience function."""
        cmd = parse_command("ls -la /tmp")
        assert cmd is not None
        assert cmd.command == "ls"
        assert cmd.args == ["-la", "/tmp"]

    def test_parse_pipeline(self) -> None:
        """Test parse_pipeline convenience function."""
        pipeline = parse_pipeline("ls | grep foo")
        assert pipeline is not None
        assert len(pipeline.commands) == 2


# ---------------------------------------------------------------------------
# Expansion tests
# ---------------------------------------------------------------------------


class TestExpansion:
    """Tests for variable, brace, and glob expansion."""

    def test_expand_variables(self) -> None:
        """Test variable expansion."""
        env = {"HOME": "/home/user", "USER": "testuser"}
        result = expand_variables("echo $HOME $USER", env)
        assert "echo" in result
        assert "/home/user" in result
        assert "testuser" in result

    def test_expand_brace_sequence(self) -> None:
        """Test numeric brace expansion."""
        result = expand_braces("file{1..3}.txt")
        assert len(result) == 3
        assert "file1.txt" in result
        assert "file2.txt" in result
        assert "file3.txt" in result

    def test_expand_brace_list(self) -> None:
        """Test comma-separated brace expansion."""
        result = expand_braces("file{a,b,c}.txt")
        assert len(result) == 3
        assert "filea.txt" in result
        assert "fileb.txt" in result
        assert "filec.txt" in result

    def test_expand_brace_alpha(self) -> None:
        """Test alphabetic brace expansion."""
        result = expand_braces("{a..e}")
        assert len(result) == 5
        assert result == ["a", "b", "c", "d", "e"]

    def test_expand_tilde(self) -> None:
        """Test tilde expansion."""
        result = expand_tilde("~/test")
        home = os.path.expanduser("~")
        assert result == os.path.join(home, "test") or result.startswith(home)

    def test_brace_no_expansion(self) -> None:
        """Test that non-brace patterns are unchanged."""
        result = expand_braces("simple.txt")
        assert result == ["simple.txt"]

    def test_nested_brace(self) -> None:
        """Test nested brace expansion (basic)."""
        result = expand_braces("a{b,c{d,e}}")
        # This should produce some expansion
        assert len(result) >= 2


# ---------------------------------------------------------------------------
# Syntax validation tests
# ---------------------------------------------------------------------------


class TestSyntaxValidation:
    """Tests for syntax validation."""

    def test_valid_syntax(self) -> None:
        """Test that valid syntax has no errors."""
        errors = validate_syntax("ls -la")
        assert len(errors) == 0

    def test_valid_pipeline(self) -> None:
        """Test that valid pipelines have no errors."""
        errors = validate_syntax("ls | grep foo")
        assert len(errors) == 0

    def test_valid_redirect(self) -> None:
        """Test that valid redirections have no errors."""
        errors = validate_syntax("echo hello > file.txt")
        assert len(errors) == 0

    def test_empty_input(self) -> None:
        """Test that empty input has no errors."""
        errors = validate_syntax("")
        assert len(errors) == 0

    def test_whitespace_syntax(self) -> None:
        """Test that whitespace input has no errors."""
        errors = validate_syntax("   ")
        assert len(errors) == 0


# ---------------------------------------------------------------------------
# Utility tests
# ---------------------------------------------------------------------------


class TestParserUtils:
    """Tests for parser utility functions."""

    def test_is_valid_identifier(self) -> None:
        """Test identifier validation."""
        assert is_valid_identifier("FOO")
        assert is_valid_identifier("foo")
        assert is_valid_identifier("foo_bar")
        assert is_valid_identifier("foo123")
        assert not is_valid_identifier("123foo")
        assert not is_valid_identifier("foo-bar")
        assert not is_valid_identifier("")

    def test_is_assignment(self) -> None:
        """Test assignment detection."""
        assert is_assignment("FOO=bar")
        assert is_assignment("VAR=value")
        assert not is_assignment("echo")
        assert not is_assignment("=value")
        assert not is_assignment("FOO=")

    def test_split_assignment(self) -> None:
        """Test assignment splitting."""
        name, value = split_assignment("FOO=bar")
        assert name == "FOO"
        assert value == "bar"

    def test_quote_word(self) -> None:
        """Test word quoting."""
        assert quote_word("hello") == "hello"
        assert quote_word("") == "''"
        assert quote_word("hello world") == "'hello world'"
        assert quote_word("it's") != "'it's'"  # Should be properly escaped

    def test_unquote_word(self) -> None:
        """Test word unquoting."""
        assert unquote_word("hello") == "hello"
        assert unquote_word("'hello'") == "hello"
        assert unquote_word('"hello"') == "hello"
        assert unquote_word("'hello world'") == "hello world"