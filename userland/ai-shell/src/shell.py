"""
Shell core for Ainos Shell.

The central Shell class that orchestrates:
- REPL (Read-Eval-Print-Loop) lifecycle
- Command parsing and execution
- Built-in command dispatch
- Plugin hook management
- History recording
- Prompt rendering
- Tab completion
- AI integration
- Configuration management
- Signal handling
"""

from __future__ import annotations

import atexit
import os
import signal
import sys
import time
import traceback
import typing as t
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .utils import (
    IS_WINDOWS,
    IS_POSIX,
    AnsiCode,
    colorize,
    ShellError,
    CommandNotFoundError,
    ExitRequested,
    Timer,
    ensure_dir,
    get_config_dir,
    get_data_dir,
    terminal_width,
    is_tty,
    expanduser,
    find_executable,
)
from .config import (
    ConfigManager,
    get_config_manager,
    get_config,
    resolve_alias,
    get_aliases,
)
from .parser import (
    Parser,
    parse_line,
    validate_syntax,
    expand_variables,
    expand_braces,
    expand_globs,
    expand_tilde,
)
from .executor import (
    CommandExecutor,
    ExecutionResult,
    get_executor,
)
from .builtins import BUILTINS, BUILTIN_HELP
from .prompt import (
    PromptRenderer,
    get_prompt_renderer,
    get_git_status,
)
from .completer import (
    Completer,
    get_completer,
)
from .history import (
    HistoryManager,
    HistoryEntry,
    get_history_manager,
)
from .ai_assist import (
    AIAssistant,
    get_ai_assistant,
)
from .ai_commands import (
    AICommandHandler,
    get_ai_handler,
)
from .plugins import (
    PluginManager,
    PluginContext,
    HookType,
    get_plugin_manager,
)
from .themes import (
    ThemeManager,
    get_theme_manager,
    get_current_theme,
)

# ---------------------------------------------------------------------------
# Shell state
# ---------------------------------------------------------------------------


class ShellState:
    """Tracks the state of the shell session."""

    def __init__(self) -> None:
        self.running = False
        self.exit_code = 0
        self.session_id = datetime.now().strftime("%Y%m%d%H%M%S")
        self.start_time = time.time()
        self.command_count = 0
        self.error_count = 0
        self.last_command: str = ""
        self.last_output: str = ""
        self.last_error: str = ""
        self.in_continuation = False
        self.continuation_lines: t.List[str] = []
        self.background_jobs: t.List[dict] = []

    @property
    def uptime(self) -> float:
        return time.time() - self.start_time

    @property
    def uptime_str(self) -> str:
        uptime = self.uptime
        days = int(uptime // 86400)
        hours = int((uptime % 86400) // 3600)
        minutes = int((uptime % 3600) // 60)
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        parts.append(f"{hours}h")
        parts.append(f"{minutes}m")
        return " ".join(parts)

    def to_dict(self) -> dict:
        return {
            "running": self.running,
            "exit_code": self.exit_code,
            "session_id": self.session_id,
            "start_time": self.start_time,
            "command_count": self.command_count,
            "error_count": self.error_count,
            "last_command": self.last_command,
            "uptime": self.uptime,
        }


# ---------------------------------------------------------------------------
# Shell class
# ---------------------------------------------------------------------------

class Shell:
    """Main shell class implementing the REPL cycle."""

    def __init__(self) -> None:
        self.state = ShellState()
        self.config_manager = get_config_manager()
        self.config = self.config_manager.config
        self.executor = get_executor()
        self.prompt_renderer = get_prompt_renderer()
        self.completer = get_completer()
        self.history_manager = get_history_manager()
        self.ai_assistant = get_ai_assistant()
        self.ai_handler = get_ai_handler()
        self.plugin_manager = get_plugin_manager()
        self.theme_manager = get_theme_manager()

        self.parser = Parser()
        self._init_signals()
        self._init_plugins()
        self._source_queue: t.List[str] = []

    def _init_signals(self) -> None:
        """Initialize signal handlers."""
        if IS_POSIX:
            signal.signal(signal.SIGINT, self._handle_sigint)
            signal.signal(signal.SIGTERM, self._handle_sigterm)
            signal.signal(signal.SIGCHLD, signal.SIG_IGN)

    def _handle_sigint(self, signum: int, frame: t.Any) -> None:
        """Handle Ctrl+C gracefully."""
        print()
        # Don't exit, just prompt again
        self.state.exit_code = 130

    def _handle_sigterm(self, signum: int, frame: t.Any) -> None:
        """Handle SIGTERM."""
        print("\nReceived SIGTERM, shutting down...")
        self.shutdown()
        sys.exit(0)

    def _init_plugins(self) -> None:
        """Initialize the plugin system."""
        try:
            context = PluginContext(
                shell=self,
                config=self.config.to_dict(),
                env=dict(os.environ),
            )
            self.plugin_manager.initialize(context)
        except Exception as e:
            import logging
            logging.warning(f"Plugin initialization failed: {e}")

    def run(self) -> int:
        """Run the main shell REPL loop."""
        self.state.running = True
        self.plugin_manager.trigger_hook(HookType.SHELL_START)

        # Print welcome
        if is_tty():
            self._print_welcome()

        # Process any queued source commands
        self._process_source_queue()

        try:
            while self.state.running:
                try:
                    self._repl_cycle()
                except ExitRequested as e:
                    self.state.exit_code = e.exit_code
                    break
                except SystemExit as e:
                    self.state.exit_code = e.code if e.code is not None else 0
                    break
                except KeyboardInterrupt:
                    self.state.exit_code = 130
                    print()
                    continue
                except Exception as e:
                    self._handle_error(e)
        finally:
            self.shutdown()

        return self.state.exit_code

    def _repl_cycle(self) -> None:
        """Execute one REPL cycle: read, parse, execute, print."""
        # Render prompt
        prompt = self.prompt_renderer.render(get_current_theme())
        rprompt = self.prompt_renderer.render_rprompt(get_current_theme())

        # Read input
        line = self._read_input(prompt, rprompt)
        if line is None:
            return

        line = line.strip()

        # Skip empty lines
        if not line:
            return

        # Handle continuation
        if self.state.in_continuation:
            self.state.continuation_lines.append(line)
            if line.endswith("\\"):
                return
            line = "\n".join(self.state.continuation_lines)
            self.state.in_continuation = False
            self.state.continuation_lines = []

        # Check for continuation
        if line.endswith("\\"):
            self.state.in_continuation = True
            self.state.continuation_lines.append(line[:-1])
            return

        # Skip comments
        if line.startswith("#"):
            return

        self.state.last_command = line

        # Record in history
        if self.config.history.enabled:
            self.history_manager.add(
                command=line,
                cwd=os.getcwd(),
            )

        # Check for source queuing
        if line.startswith("source "):
            self._handle_source(line)

        # Parse
        timer = Timer()
        timer.start()

        # Expand variables
        expanded_line = self._expand_line(line)

        # Check for AI prefix
        if expanded_line.startswith("?"):
            query = expanded_line[1:].strip()
            self._handle_ai_query(query)
            return

        # Parse the command
        pipelines = parse_line(expanded_line)

        if not pipelines:
            return

        self.state.command_count += 1

        # Plugin hook: pre-command
        self.plugin_manager.trigger_hook(HookType.PRE_COMMAND, line)

        # Execute
        all_results = self.executor.execute_commands(pipelines)

        # Process results
        last_result = None
        for pipeline_results in all_results:
            for result in pipeline_results:
                last_result = result
                # Print output
                if result.stdout:
                    print(result.stdout, end="")
                if result.stderr:
                    print(result.stderr, end="", file=sys.stderr)

        # Update state
        if last_result:
            self.state.exit_code = last_result.exit_code
            self.prompt_renderer.set_last_exit_code(last_result.exit_code)
            self.state.last_output = last_result.stdout
            self.state.last_error = last_result.stderr

            if last_result.exit_code != 0:
                self.state.error_count += 1

        timer.stop()

        # Update AI completion engine
        from .completion import get_ai_completion_engine
        get_ai_completion_engine().learn_from_command(expanded_line)

        # Plugin hook: post-command
        self.plugin_manager.trigger_hook(
            HookType.POST_COMMAND,
            line, last_result,
        )

        # Update history with duration
        if self.config.history.enabled and last_result:
            entries = self.history_manager.get(limit=1)
            if entries:
                entries[0].duration = timer.elapsed
                entries[0].exit_code = last_result.exit_code

        # AI error explanation
        if (last_result and last_result.exit_code != 0
                and last_result.stderr
                and self.config.ai.explain_errors):
            self._ai_explain_error(last_result)

    def _read_input(self, prompt: str, rprompt: str = "") -> t.Optional[str]:
        """Read a line of input from the user."""
        try:
            # Print right prompt first (if any)
            if rprompt:
                # Position cursor for right prompt
                width = terminal_width()
                rprompt_visible = AnsiCode.len_without_ansi(rprompt)
                if rprompt_visible < width:
                    # Save cursor, move to right, print, restore
                    sys.stdout.write("\0337")  # Save cursor
                    sys.stdout.write(f"\033[{width - rprompt_visible}C")
                    sys.stdout.write(rprompt)
                    sys.stdout.write("\0338")  # Restore cursor

            # Print the prompt
            sys.stdout.write(prompt)
            sys.stdout.flush()

            # Read input
            line = sys.stdin.readline()

            if not line:
                # EOF
                print()
                raise ExitRequested(0)

            return line.rstrip("\n\r")
        except EOFError:
            raise ExitRequested(0)
        except KeyboardInterrupt:
            return None

    def _expand_line(self, line: str) -> str:
        """Expand variables, aliases, and special characters in a line."""
        # Check for aliases
        first_word = line.split()[0] if line.split() else ""
        if first_word:
            resolved = resolve_alias(first_word)
            if resolved != first_word:
                line = resolved + line[len(first_word):]

        # Expand variables
        line = expand_variables(line, os.environ)

        # Expand tilde
        line = expand_tilde(line)

        return line

    def _handle_ai_query(self, query: str) -> None:
        """Handle an AI natural language query."""
        print(colorize("AI: ", AnsiCode.FG_CYAN, bold=True), end="")
        self.prompt_renderer.set_ai_loading(True)

        ai_cmd = self.ai_handler.handle_natural_language(query, {
            "cwd": os.getcwd(),
            "os": os.name,
        })

        self.prompt_renderer.set_ai_loading(False)

        if ai_cmd:
            print(self.ai_handler.format_ai_response(ai_cmd))
            print()
            if ai_cmd.needs_confirmation:
                try:
                    resp = input(colorize("Execute? [Y/n] ", AnsiCode.FG_CYAN)).strip().lower()
                    if resp in ("", "y", "yes"):
                        self._repl_cycle_with_input(ai_cmd.command)
                except (EOFError, KeyboardInterrupt):
                    print()
        else:
            print(colorize("AI assistant is not available.",
                           AnsiCode.FG_RED))

    def _repl_cycle_with_input(self, input_line: str) -> None:
        """Execute a command directly (used for AI suggestions)."""
        # Simulate a regular REPL cycle with the given input
        self.state.last_command = input_line

        if self.config.history.enabled:
            self.history_manager.add(
                command=input_line,
                cwd=os.getcwd(),
            )

        expanded_line = self._expand_line(input_line)
        pipelines = parse_line(expanded_line)

        if not pipelines:
            return

        self.state.command_count += 1
        all_results = self.executor.execute_commands(pipelines)

        last_result = None
        for pipeline_results in all_results:
            for result in pipeline_results:
                last_result = result
                if result.stdout:
                    print(result.stdout, end="")
                if result.stderr:
                    print(result.stderr, end="", file=sys.stderr)

        if last_result:
            self.state.exit_code = last_result.exit_code
            self.prompt_renderer.set_last_exit_code(last_result.exit_code)

    def _ai_explain_error(self, result: ExecutionResult) -> None:
        """Use AI to explain a command error."""
        try:
            explanation = self.ai_assistant.explain_error(
                command=result.command,
                error_message=result.stderr,
                exit_code=result.exit_code,
                cwd=os.getcwd(),
            )
            if explanation and explanation.explanation:
                print(colorize(f"\nAI Error Explanation:",
                               AnsiCode.FG_YELLOW, bold=True))
                print(f"  {explanation.explanation}")
                if explanation.suggestions:
                    print(colorize("  Suggestions:", AnsiCode.FG_CYAN))
                    for s in explanation.suggestions:
                        print(f"    - {s}")
                if explanation.fix_command:
                    print(colorize(f"  Fix: {explanation.fix_command}",
                                   AnsiCode.FG_GREEN))
        except Exception:
            pass

    def _handle_source(self, line: str) -> None:
        """Handle source command by queuing the file content."""
        parts = line.split()
        if len(parts) >= 2:
            path = expanduser(parts[1])
            if os.path.isfile(path):
                try:
                    with open(path, "r") as f:
                        content = f.read()
                    self._source_queue.append(content)
                except Exception as e:
                    print(f"source: error reading {path}: {e}")

    def _process_source_queue(self) -> None:
        """Process queued source commands."""
        while self._source_queue:
            content = self._source_queue.pop(0)
            for line in content.split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    self._repl_cycle_with_input(line)

    def execute_source(self, content: str) -> None:
        """Execute content as shell commands (used by source builtin)."""
        for line in content.split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                self._repl_cycle_with_input(line)

    def _handle_error(self, error: Exception) -> None:
        """Handle an unexpected error."""
        self.state.error_count += 1
        if is_tty():
            print(colorize(f"Error: {error}", AnsiCode.FG_RED), file=sys.stderr)
            if self.config.behavior.log_level == "debug":
                traceback.print_exc()
        else:
            print(f"Error: {error}", file=sys.stderr)

    def _print_welcome(self) -> None:
        """Print the shell welcome message."""
        print(colorize(f"╔══════════════════════════════════════════╗", AnsiCode.FG_CYAN))
        print(colorize(f"║  Ainos Shell (ainos-sh) v{self.config.shell_version}", AnsiCode.FG_CYAN))
        print(colorize(f"║  Type 'help' for commands, '?' for AI", AnsiCode.FG_CYAN))
        print(colorize(f"╚══════════════════════════════════════════╝", AnsiCode.FG_CYAN))
        print()

    def shutdown(self) -> None:
        """Clean up shell resources."""
        self.state.running = False

        # Save history
        if self.config.history.enabled:
            self.history_manager.close()

        # Shutdown plugins
        self.plugin_manager.shutdown()

        # Clean up background processes
        self.executor.cleanup_background()

    def __repr__(self) -> str:
        return f"Shell(pid={os.getpid()}, session={self.state.session_id})"


# ---------------------------------------------------------------------------
# Module-level access
# ---------------------------------------------------------------------------

_shell: t.Optional[Shell] = None


def get_shell() -> t.Optional[Shell]:
    """Get the global shell instance."""
    global _shell
    return _shell


def create_shell() -> Shell:
    """Create and return a new Shell instance."""
    global _shell
    _shell = Shell()
    return _shell


__all__ = [
    "Shell",
    "ShellState",
    "get_shell",
    "create_shell",
]