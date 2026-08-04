"""
Command parser for Ainos Shell.

Parses raw command-line input into structured representations:
- Tokenization (quotes, escapes, variables)
- Pipeline detection (|)
- Redirection parsing (<, >, >>, 2>&1, etc.)
- Environment variable substitution
- Heredoc/herestring support
- Command chaining (;, &&, ||)
- Job control (&)
- Variable assignment detection
- Glob pattern expansion
- Brace expansion
"""

from __future__ import annotations

import os
import re
import typing as t
from dataclasses import dataclass, field
from enum import Enum, auto

from .utils import (
    ParsedCommand,
    Pipeline,
    RedirectInfo,
    ShellError,
    SyntaxError_,
    expandvars,
    expanduser,
    split_quoted,
    is_glob_pattern,
    expand_glob,
)

# ---------------------------------------------------------------------------
# Token types
# ---------------------------------------------------------------------------


class TokenType(Enum):
    """Types of tokens in the shell lexer."""
    WORD = auto()           # Regular word
    PIPE = auto()           # |
    BACKGROUND = auto()     # &
    SEMICOLON = auto()      # ;
    AND = auto()            # &&
    OR = auto()             # ||
    REDIRECT_IN = auto()    # <
    REDIRECT_OUT = auto()   # >
    REDIRECT_APPEND = auto() # >>
    REDIRECT_HEREDOC = auto() # <<
    REDIRECT_HERESTR = auto() # <<<
    REDIRECT_STDERR = auto() # 2>
    REDIRECT_STDERR_APPEND = auto() # 2>>
    REDIRECT_STDERR_MERGE = auto() # 2>&1
    REDIRECT_ALL_OUT = auto() # &>
    REDIRECT_ALL_APPEND = auto() # &>>
    REDIRECT_DUP_IN = auto() # <&
    REDIRECT_DUP_OUT = auto() # >&
    ASSIGNMENT = auto()    # VAR=value
    SUBSHELL_OPEN = auto() # (
    SUBSHELL_CLOSE = auto() # )
    BRACE_OPEN = auto()    # {
    BRACE_CLOSE = auto()   # }
    NEWLINE = auto()       # \n
    COMMENT = auto()       # #


@dataclass
class Token:
    """A single token from the shell lexer."""
    type: TokenType
    value: str
    pos: int = -1  # Position in original input
    quoted: bool = False
    escaped: bool = False

    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.value!r})"


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

class Lexer:
    """Lexer that tokenizes shell input into tokens."""

    # Characters that are special to the shell
    SPECIAL_CHARS = set('|&;<>(){}# \t\n\r"\'\\$`')
    REDIRECT_PATTERNS = {
        "2>&1": TokenType.REDIRECT_STDERR_MERGE,
        "2>>": TokenType.REDIRECT_STDERR_APPEND,
        "2>": TokenType.REDIRECT_STDERR,
        "&>>": TokenType.REDIRECT_ALL_APPEND,
        "&>": TokenType.REDIRECT_ALL_OUT,
        ">>&": TokenType.REDIRECT_ALL_APPEND,
        ">>": TokenType.REDIRECT_APPEND,
        "<<<": TokenType.REDIRECT_HERESTR,
        "<<": TokenType.REDIRECT_HEREDOC,
        "<>": TokenType.REDIRECT_IN,  # Read-write
        "<&": TokenType.REDIRECT_DUP_IN,
        ">&": TokenType.REDIRECT_DUP_OUT,
        '<': TokenType.REDIRECT_IN,
        '>': TokenType.REDIRECT_OUT,
    }

    def __init__(self, input_str: str) -> None:
        self.input = input_str
        self.pos = 0
        self.tokens: t.List[Token] = []

    def tokenize(self) -> t.List[Token]:
        """Tokenize the input string into a list of tokens."""
        self.tokens = []
        self.pos = 0

        while self.pos < len(self.input):
            char = self.input[self.pos]

            if char in ' \t\r':
                self.pos += 1
                continue

            if char == '#':
                self._read_comment()
                continue

            if char == '\n':
                self.tokens.append(Token(TokenType.NEWLINE, '\n', self.pos))
                self.pos += 1
                continue

            if char == '|':
                if self.pos + 1 < len(self.input) and self.input[self.pos + 1] == '|':
                    self.tokens.append(Token(TokenType.OR, '||', self.pos))
                    self.pos += 2
                else:
                    self.tokens.append(Token(TokenType.PIPE, '|', self.pos))
                    self.pos += 1
                continue

            if char == '&':
                if self.pos + 1 < len(self.input) and self.input[self.pos + 1] == '&':
                    self.tokens.append(Token(TokenType.AND, '&&', self.pos))
                    self.pos += 2
                elif self.pos + 1 < len(self.input) and self.input[self.pos + 1] == '>':
                    # Check for &>>
                    if (self.pos + 2 < len(self.input) and self.input[self.pos + 2] == '>'):
                        self.tokens.append(Token(TokenType.REDIRECT_ALL_APPEND, '&>>', self.pos))
                        self.pos += 3
                    else:
                        self.tokens.append(Token(TokenType.REDIRECT_ALL_OUT, '&>', self.pos))
                        self.pos += 2
                else:
                    self.tokens.append(Token(TokenType.BACKGROUND, '&', self.pos))
                    self.pos += 1
                continue

            if char == ';':
                self.tokens.append(Token(TokenType.SEMICOLON, ';', self.pos))
                self.pos += 1
                continue

            if char == '(':
                self.tokens.append(Token(TokenType.SUBSHELL_OPEN, '(', self.pos))
                self.pos += 1
                continue

            if char == ')':
                self.tokens.append(Token(TokenType.SUBSHELL_CLOSE, ')', self.pos))
                self.pos += 1
                continue

            if char == '{':
                self.tokens.append(Token(TokenType.BRACE_OPEN, '{', self.pos))
                self.pos += 1
                continue

            if char == '}':
                self.tokens.append(Token(TokenType.BRACE_CLOSE, '}', self.pos))
                self.pos += 1
                continue

            # Check for redirection patterns (starting with digits followed by > or <)
            if char.isdigit() and self.pos + 1 < len(self.input):
                next_char = self.input[self.pos + 1]
                if next_char in '>':
                    # Check for 2>&1 pattern
                    lookahead = self.input[self.pos:self.pos + 4]
                    if lookahead == "2>&1":
                        self.tokens.append(Token(TokenType.REDIRECT_STDERR_MERGE, '2>&1', self.pos))
                        self.pos += 4
                        continue
                    elif lookahead[:3] == "2>>":
                        self.tokens.append(Token(TokenType.REDIRECT_STDERR_APPEND, '2>>', self.pos))
                        self.pos += 3
                        continue
                    elif lookahead[:2] == "2>":
                        self.tokens.append(Token(TokenType.REDIRECT_STDERR, '2>', self.pos))
                        self.pos += 2
                        continue

                    # Any other digit followed by > or < is a word
                    pass

            # Check for other redirection patterns
            matched = False
            for pattern, token_type in sorted(self.REDIRECT_PATTERNS.items(), key=lambda x: -len(x[0])):
                if self.input[self.pos:self.pos + len(pattern)] == pattern:
                    self.tokens.append(Token(token_type, pattern, self.pos))
                    self.pos += len(pattern)
                    matched = True
                    break

            if matched:
                continue

            # Regular word
            token = self._read_word()
            if token is not None:
                self.tokens.append(token)

        return self.tokens

    def _read_comment(self) -> None:
        """Read a comment until end of line."""
        start = self.pos
        while self.pos < len(self.input) and self.input[self.pos] != '\n':
            self.pos += 1
        comment_text = self.input[start:self.pos]
        self.tokens.append(Token(TokenType.COMMENT, comment_text, start))

    def _read_word(self) -> t.Optional[Token]:
        """Read a word (possibly quoted), handling escapes and variables."""
        start = self.pos
        parts: t.List[str] = []
        quoted = False
        escaped = False
        quote_char = ''

        while self.pos < len(self.input):
            char = self.input[self.pos]

            if escaped:
                parts.append(char)
                self.pos += 1
                escaped = False
                continue

            if char == '\\':
                next_pos = self.pos + 1
                if next_pos < len(self.input):
                    escaped = True
                    self.pos += 1
                    continue
                else:
                    parts.append(char)
                    self.pos += 1
                    continue

            if char in '"\'':
                if not quoted:
                    quoted = True
                    quote_char = char
                    self.pos += 1
                    continue
                elif char == quote_char:
                    quoted = False
                    quote_char = ''
                    self.pos += 1
                    continue
                else:
                    # Different quote inside quoted string
                    if quote_char == '"':
                        # Single quotes inside double quotes are literal
                        parts.append(char)
                        self.pos += 1
                        continue
                    else:
                        # Inside single quotes, everything is literal
                        parts.append(char)
                        self.pos += 1
                        continue

            if not quoted and char in self.SPECIAL_CHARS:
                break

            parts.append(char)
            self.pos += 1

        if not parts:
            return None

        value = ''.join(parts)
        return Token(TokenType.WORD, value, start, quoted=bool(quoted), escaped=escaped)

    def peek(self, offset: int = 0) -> t.Optional[Token]:
        """Peek at a token without consuming it."""
        idx = offset
        if idx < len(self.tokens):
            return self.tokens[idx]
        return None


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class Parser:
    """Parses a line of shell input into structured commands."""

    def __init__(self, config: t.Optional[dict] = None) -> None:
        self.config = config or {}
        self.tokens: t.List[Token] = []
        self.pos = 0

    def parse(self, input_str: str) -> t.List[Pipeline]:
        """Parse a full input line into a list of pipelines."""
        if not input_str or not input_str.strip():
            return []

        lexer = Lexer(input_str)
        self.tokens = lexer.tokenize()
        self.pos = 0

        pipelines: t.List[Pipeline] = []
        pipeline = Pipeline()

        while self.pos < len(self.tokens):
            token = self.tokens[self.pos]

            if token.type == TokenType.NEWLINE or token.type == TokenType.SEMICOLON:
                if pipeline.commands:
                    pipelines.append(pipeline)
                    pipeline = Pipeline()
                self.pos += 1
                continue

            if token.type == TokenType.AND:
                # && or & (background)
                if pipeline.commands and pipeline.commands[-1].command:
                    if self.pos + 1 < len(self.tokens) and self.tokens[self.pos + 1].type == TokenType.AND:
                        # && - not fully implemented here, handled as sequential
                        if pipeline.commands:
                            next_pipeline = Pipeline()
                            pipelines.append(pipeline)
                            pipeline = next_pipeline
                        self.pos += 2
                    else:
                        # Background
                        pipeline.background = True
                        if pipeline.commands:
                            pipelines.append(pipeline)
                            pipeline = Pipeline()
                        self.pos += 1
                else:
                    self.pos += 1
                continue

            if token.type == TokenType.OR:
                # || - handle as sequential
                if pipeline.commands:
                    pipelines.append(pipeline)
                    pipeline = Pipeline()
                self.pos += 1
                continue

            if token.type == TokenType.PIPE:
                # End current command in pipeline, start next
                if pipeline.commands:
                    # If last command has no command name, it's just redirects
                    last_cmd = pipeline.commands[-1]
                    if last_cmd.command:
                        pipeline.commands.append(ParsedCommand())
                self.pos += 1
                continue

            if token.type == TokenType.BACKGROUND:
                pipeline.background = True
                if pipeline.commands:
                    pipelines.append(pipeline)
                    pipeline = Pipeline()
                self.pos += 1
                continue

            if token.type == TokenType.COMMENT:
                self.pos += 1
                continue

            # Parse a single command
            cmd = self._parse_command()
            if cmd is not None:
                pipeline.commands.append(cmd)

        if pipeline.commands:
            pipelines.append(pipeline)

        return pipelines

    def _parse_command(self) -> t.Optional[ParsedCommand]:
        """Parse a single command (possibly piped)."""
        cmd = ParsedCommand()

        while self.pos < len(self.tokens):
            token = self.tokens[self.pos]

            # Stop at pipeline/control operators
            if token.type in (
                TokenType.PIPE, TokenType.SEMICOLON, TokenType.NEWLINE,
                TokenType.AND, TokenType.OR, TokenType.BACKGROUND,
            ):
                break

            # Handle redirections
            if token.type in (
                TokenType.REDIRECT_IN, TokenType.REDIRECT_OUT,
                TokenType.REDIRECT_APPEND, TokenType.REDIRECT_HEREDOC,
                TokenType.REDIRECT_HERESTR, TokenType.REDIRECT_STDERR,
                TokenType.REDIRECT_STDERR_APPEND, TokenType.REDIRECT_STDERR_MERGE,
                TokenType.REDIRECT_ALL_OUT, TokenType.REDIRECT_ALL_APPEND,
            ):
                redirect = self._parse_redirect(token)
                if redirect is not None:
                    cmd.redirects.append(redirect)
                self.pos += 1
                continue

            # Handle special word tokens with redirection-like prefixes
            if token.type == TokenType.WORD:
                value = token.value

                # Check for assignment (VAR=value)
                if '=' in value and not value.startswith('=') and not cmd.command:
                    # Check if LHS is a valid identifier
                    var_name = value.split('=', 1)[0]
                    if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', var_name):
                        cmd.env_vars[var_name] = value.split('=', 1)[1]
                        self.pos += 1
                        continue

                # First word is the command
                if not cmd.command:
                    cmd.command = value
                else:
                    cmd.args.append(value)

                self.pos += 1
                continue

            # Skip other token types
            self.pos += 1

        # If no command was found, return None
        if not cmd.command and not cmd.env_vars and not cmd.redirects:
            return None

        return cmd

    def _parse_redirect(self, token: Token) -> t.Optional[RedirectInfo]:
        """Parse a redirection token and its target."""
        type_map = {
            TokenType.REDIRECT_IN: RedirectInfo.Type.INPUT,
            TokenType.REDIRECT_OUT: RedirectInfo.Type.OUTPUT,
            TokenType.REDIRECT_APPEND: RedirectInfo.Type.APPEND,
            TokenType.REDIRECT_HEREDOC: RedirectInfo.Type.HEREDOC,
            TokenType.REDIRECT_HERESTR: RedirectInfo.Type.HERESTR,
            TokenType.REDIRECT_STDERR: RedirectInfo.Type.STDERR_OUTPUT,
            TokenType.REDIRECT_STDERR_APPEND: RedirectInfo.Type.STDERR_APPEND,
            TokenType.REDIRECT_STDERR_MERGE: RedirectInfo.Type.STDERR_MERGE,
            TokenType.REDIRECT_ALL_OUT: RedirectInfo.Type.OUTPUT_MERGE,
            TokenType.REDIRECT_ALL_APPEND: RedirectInfo.Type.ALL_APPEND,
        }

        redirect_type = type_map.get(token.type)
        if redirect_type is None:
            return None

        # Parse FD number from prefix (e.g., "2>")
        fd = -1
        value = token.value
        if value[0].isdigit() and len(value) > 1 and value[1] in '>':
            try:
                fd = int(value[0])
            except ValueError:
                pass

        # For "2>&1", the target is "&1" meaning FD 1
        target = ""
        if redirect_type == RedirectInfo.Type.STDERR_MERGE:
            target = "&1"  # Merge with stdout

        # Get the target filename from the next token
        elif self.pos + 1 < len(self.tokens):
            next_token = self.tokens[self.pos + 1]
            if next_token.type == TokenType.WORD:
                target = next_token.value
                self.pos += 1  # Consume target token

        return RedirectInfo(type=redirect_type, target=target, fd=fd)

    def _is_special_char(self, char: str) -> bool:
        """Check if a character is a shell special character."""
        return char in '|&;<>(){}# \t\n\r"\''


# ---------------------------------------------------------------------------
# High-level parsing functions
# ---------------------------------------------------------------------------

def parse_line(line: str) -> t.List[Pipeline]:
    """Parse a full command line into pipelines."""
    parser = Parser()
    return parser.parse(line)


def parse_command(line: str) -> t.Optional[ParsedCommand]:
    """Parse a single command (first pipeline, first command)."""
    pipelines = parse_line(line)
    if pipelines and pipelines[0].commands:
        return pipelines[0].commands[0]
    return None


def parse_pipeline(line: str) -> t.Optional[Pipeline]:
    """Parse a single pipeline."""
    pipelines = parse_line(line)
    if pipelines:
        return pipelines[0]
    return None


# ---------------------------------------------------------------------------
# Variable expansion
# ---------------------------------------------------------------------------

def expand_variables(text: str, env: t.Optional[t.Dict[str, str]] = None) -> str:
    """Expand $VAR and ${VAR} references in text."""
    if env is None:
        env = os.environ

    def _replace(m: re.Match) -> str:
        var_name = m.group(1) or m.group(2) or ""
        if not var_name:
            return "$"

        # Special variables
        if var_name == "$":
            return str(os.getpid())
        elif var_name == "?":
            return "0"  # Will be replaced with actual exit code
        elif var_name == "!":
            return ""  # Background PID
        elif var_name == "0":
            return "ainos-sh"
        elif var_name == "@":
            return " ".join(env.get("_", ""))
        elif var_name == "*":
            return " ".join(env.get("_", ""))

        # Variable substitution with default
        if ":-" in var_name:
            name, default = var_name.split(":-", 1)
            return env.get(name, default)
        elif ":?" in var_name:
            name, err_msg = var_name.split(":?", 1)
            if name in env:
                return env[name]
            raise ShellError(f"{name}: {err_msg}")
        elif ":+" in var_name:
            name, alt_value = var_name.split(":+", 1)
            return alt_value if name in env else ""

        # Regular variable
        return env.get(var_name, "")

    pattern = r"\$\{([^}]+)\}|\$([a-zA-Z_][a-zA-Z0-9_]*)|\$\$"
    return re.sub(pattern, _replace, text)


# ---------------------------------------------------------------------------
# Brace expansion
# ---------------------------------------------------------------------------

def expand_braces(pattern: str) -> t.List[str]:
    """Expand brace patterns like {a,b,c} or {1..5}."""
    if '{' not in pattern:
        return [pattern]

    results = [""]
    i = 0
    while i < len(pattern):
        if pattern[i] == '{':
            end = _find_matching_brace(pattern, i)
            if end == -1:
                results = [r + pattern[i] for r in results]
                i += 1
                continue

            inner = pattern[i + 1:end]
            parts = _parse_brace_inner(inner)

            if parts:
                new_results = []
                for r in results:
                    for p in parts:
                        new_results.append(r + p)
                results = new_results
                i = end + 1
            else:
                results = [r + pattern[i] for r in results]
                i += 1
        else:
            results = [r + pattern[i] for r in results]
            i += 1

    return results


def _find_matching_brace(text: str, start: int) -> int:
    """Find the matching closing brace for an opening brace at start."""
    depth = 1
    i = start + 1
    while i < len(text):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return i
        elif text[i] == '\'' or text[i] == '"':
            # Skip quoted strings
            quote = text[i]
            i += 1
            while i < len(text) and text[i] != quote:
                if text[i] == '\\' and i + 1 < len(text):
                    i += 1
                i += 1
        i += 1
    return -1


def _parse_brace_inner(inner: str) -> t.List[str]:
    """Parse the inner contents of a brace expansion."""
    # Range expansion: {1..5} or {a..z}
    range_match = re.match(r'^(-?\d+)\.\.(-?\d+)$', inner)
    if range_match:
        start, end = int(range_match.group(1)), int(range_match.group(2))
        step = 1 if start <= end else -1
        return [str(i) for i in range(start, end + step, step)]

    range_char = re.match(r'^([a-zA-Z])\.\.([a-zA-Z])$', inner)
    if range_char:
        start_c, end_c = range_char.group(1), range_char.group(2)
        start_n, end_n = ord(start_c), ord(end_c)
        step = 1 if start_n <= end_n else -1
        return [chr(i) for i in range(start_n, end_n + step, step)]

    # Comma-separated list
    parts = _split_brace_parts(inner)
    return parts if parts else [inner]


def _split_brace_parts(inner: str) -> t.List[str]:
    """Split brace inner contents by commas, respecting nesting."""
    parts = []
    depth = 0
    current = []
    i = 0
    while i < len(inner):
        c = inner[i]
        if c == '{':
            depth += 1
            current.append(c)
        elif c == '}':
            depth -= 1
            current.append(c)
        elif c == ',' and depth == 0:
            parts.append(''.join(current).strip())
            current = []
        elif c in '"\'':
            quote = c
            current.append(c)
            i += 1
            while i < len(inner) and inner[i] != quote:
                if inner[i] == '\\' and i + 1 < len(inner):
                    current.append(inner[i])
                    i += 1
                    current.append(inner[i])
                else:
                    current.append(inner[i])
                i += 1
            if i < len(inner):
                current.append(inner[i])
        else:
            current.append(c)
        i += 1

    if current:
        parts.append(''.join(current).strip())

    return parts


# ---------------------------------------------------------------------------
# Glob expansion
# ---------------------------------------------------------------------------

def expand_globs(args: t.List[str], cwd: t.Optional[str] = None) -> t.List[str]:
    """Expand glob patterns in argument list."""
    if cwd is None:
        cwd = os.getcwd()

    result = []
    for arg in args:
        if is_glob_pattern(arg) and not (arg.startswith('"') or arg.startswith("'")):
            matches = expand_glob(arg, cwd)
            if matches:
                result.extend(sorted(matches))
            else:
                result.append(arg)
        else:
            result.append(arg)
    return result


# ---------------------------------------------------------------------------
# Tilde expansion
# ---------------------------------------------------------------------------

def expand_tilde(path: str) -> str:
    """Expand ~ and ~user constructs."""
    return expanduser(path)


# ---------------------------------------------------------------------------
# Full expansion pipeline
# ---------------------------------------------------------------------------

def expand_line(line: str, env: t.Optional[t.Dict[str, str]] = None) -> str:
    """Apply all expansions to a command line."""
    if env is None:
        env = os.environ

    # Order: brace expansion, tilde expansion, parameter expansion, command substitution, arithmetic expansion, word splitting, glob expansion
    # For simplicity, we do the main ones

    # 1. Brace expansion
    line_parts = expand_braces(line)

    # 2. Tilde expansion
    line_parts = [expand_tilde(p) for p in line_parts]

    # 3. Variable expansion
    line_parts = [expand_variables(p, env) for p in line_parts]

    # Join back (normally would split on spaces for brace expansion)
    return ' '.join(line_parts)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def is_valid_identifier(name: str) -> bool:
    """Check if a string is a valid shell identifier."""
    return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name))


def is_assignment(word: str) -> bool:
    """Check if a word looks like a variable assignment."""
    if '=' not in word:
        return False
    name = word.split('=', 1)[0]
    return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name))


def split_assignment(word: str) -> t.Tuple[str, str]:
    """Split a VAR=value assignment into name and value."""
    parts = word.split('=', 1)
    if len(parts) == 2:
        return (parts[0], parts[1])
    return (parts[0], "")


def quote_word(word: str) -> str:
    """Quote a word for safe shell use."""
    if not word:
        return "''"
    if re.match(r'^[a-zA-Z0-9_./-]+$', word):
        return word
    return "'" + word.replace("'", "'\\''") + "'"


def unquote_word(word: str) -> str:
    """Remove quotes from a word."""
    if len(word) >= 2 and word[0] == word[-1] and word[0] in '"\'':
        return word[1:-1]
    return word


# ---------------------------------------------------------------------------
# Syntax validation
# ---------------------------------------------------------------------------

def validate_syntax(line: str) -> t.List[str]:
    """Validate shell syntax, returning list of errors."""
    errors: t.List[str] = []

    if not line or not line.strip():
        return errors

    lexer = Lexer(line)
    tokens = lexer.tokenize()

    if not tokens:
        return errors

    # Check for unclosed quotes
    for i, token in enumerate(tokens):
        if token.type == TokenType.WORD and token.quoted:
            # Check if quote was closed
            value = token.value
            if value.count('"') % 2 != 0:
                errors.append(f"Unclosed double quote at position {token.pos}")
            if value.count("'") % 2 != 0:
                errors.append(f"Unclosed single quote at position {token.pos}")

    # Check for unclosed subshells
    depth = 0
    for token in tokens:
        if token.type == TokenType.SUBSHELL_OPEN:
            depth += 1
        elif token.type == TokenType.SUBSHELL_CLOSE:
            depth -= 1
            if depth < 0:
                errors.append(f"Unexpected closing parenthesis at position {token.pos}")
                depth = 0

    if depth > 0:
        errors.append("Unclosed subshell")

    # Check for empty pipe
    for i, token in enumerate(tokens):
        if token.type == TokenType.PIPE:
            # Check if there's a command before the pipe
            has_before = False
            for j in range(i - 1, -1, -1):
                if tokens[j].type == TokenType.WORD:
                    has_before = True
                    break
                elif tokens[j].type in (TokenType.PIPE, TokenType.SEMICOLON, TokenType.AND, TokenType.OR):
                    break

            has_after = False
            for j in range(i + 1, len(tokens)):
                if tokens[j].type == TokenType.WORD:
                    has_after = True
                    break
                elif tokens[j].type in (TokenType.PIPE, TokenType.SEMICOLON, TokenType.AND, TokenType.OR):
                    break

            if not has_before:
                errors.append(f"Empty command before pipe at position {token.pos}")
            if not has_after:
                errors.append(f"Empty command after pipe at position {token.pos}")

    # Check for redirection without target
    for i, token in enumerate(tokens):
        if token.type in (
            TokenType.REDIRECT_IN, TokenType.REDIRECT_OUT,
            TokenType.REDIRECT_APPEND, TokenType.REDIRECT_STDERR,
            TokenType.REDIRECT_STDERR_APPEND, TokenType.REDIRECT_ALL_OUT,
            TokenType.REDIRECT_ALL_APPEND,
        ):
            if i + 1 >= len(tokens) or tokens[i + 1].type != TokenType.WORD:
                errors.append(f"Redirection without target at position {token.pos}")

    return errors


__all__ = [
    "Lexer", "Parser", "Token", "TokenType",
    "parse_line", "parse_command", "parse_pipeline",
    "expand_variables", "expand_braces", "expand_globs", "expand_tilde",
    "expand_line",
    "is_valid_identifier", "is_assignment", "split_assignment",
    "quote_word", "unquote_word",
    "validate_syntax",
]