"""
AI-powered commands for Ainos Shell.

Provides AI-enhanced shell commands:
- Natural language command interpretation
- Smart command completion with AI
- Interactive command generation
- Command explanation and translation
- Batch command generation
- Learning from user corrections
"""

from __future__ import annotations

import os
import re
import sys
import typing as t
from dataclasses import dataclass, field

from .utils import (
    AnsiCode,
    colorize,
    terminal_width,
    truncate,
    get_config,
    get_env,
)
from .ai_assist import (
    AIAssistant,
    AICommand,
    get_ai_assistant,
)

# ---------------------------------------------------------------------------
# AI Command Handler
# ---------------------------------------------------------------------------


class AICommandHandler:
    """Handles AI-powered commands and interactions."""

    def __init__(self, assistant: t.Optional[AIAssistant] = None) -> None:
        self.assistant = assistant or get_ai_assistant()
        self._last_command: t.Optional[AICommand] = None
        self._interactive_mode = False

    def handle_natural_language(self, query: str, context: t.Optional[dict] = None) -> t.Optional[AICommand]:
        """Process a natural language request and return a command."""
        if not query:
            return None

        if context is None:
            context = {
                "cwd": os.getcwd(),
                "os": os.name,
                "shell": "ainos-sh",
            }

        ai_cmd = self.assistant.natural_language_to_command(query, context)
        if ai_cmd:
            self._last_command = ai_cmd
        return ai_cmd

    def explain_command(self, command: str) -> t.Optional[str]:
        """Get an explanation of what a command does."""
        if not command:
            return None

        system_prompt = (
            "You are a shell command expert. Explain what a shell command does in simple terms. "
            "Be concise and clear. Break down complex commands."
        )

        prompt = f"Explain this shell command: {command}"

        return self.assistant.provider.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=200,
            temperature=0.3,
        ) if self.assistant.is_available else None

    def translate_command(self, command: str, target_os: str = "linux") -> t.Optional[str]:
        """Translate a command between OS types (e.g., Linux to Windows)."""
        if not command:
            return None

        system_prompt = (
            f"You are a cross-platform shell expert. Translate commands between different OS shells. "
            f"Target OS: {target_os}. Provide the equivalent command."
        )

        prompt = f"Translate this command for {target_os}: {command}"

        return self.assistant.provider.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=200,
            temperature=0.2,
        ) if self.assistant.is_available else None

    def suggest_fix(self, command: str, error: str) -> t.Optional[str]:
        """Suggest a fix for a failed command."""
        if not command or not error:
            return None

        system_prompt = (
            "You are a shell debugging expert. Given a failed command and its error message, "
            "suggest a corrected version of the command. Be precise."
        )

        prompt = f"Command: {command}\nError: {error}\nSuggest a fix."

        return self.assistant.provider.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=200,
            temperature=0.2,
        ) if self.assistant.is_available else None

    def generate_script(self, description: str) -> t.Optional[str]:
        """Generate a shell script from a description."""
        if not description:
            return None

        system_prompt = (
            "You are a shell scripting expert. Generate a complete shell script based on the description. "
            "Include shebang, comments, and error handling. Output only the script code."
        )

        prompt = f"Generate a shell script that: {description}"

        return self.assistant.provider.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=500,
            temperature=0.3,
        ) if self.assistant.is_available else None

    def get_shortcut(self, command: str) -> t.Optional[str]:
        """Suggest a shorter or more efficient way to write a command."""
        if not command:
            return None

        # Built-in shortcuts
        shortcuts = {
            "grep -r": "grep -rn",
            "find . -name": "find . -name",
            "ps aux | grep": "pgrep -f" if not get_env("OS", "").startswith("Windows") else "tasklist | findstr",
        }

        for pattern, shortcut in shortcuts.items():
            if command.strip().startswith(pattern):
                return shortcut

        return None

    def format_ai_response(self, ai_cmd: AICommand) -> str:
        """Format an AI command for display."""
        lines = []
        lines.append(colorize("AI Suggestion:", AnsiCode.FG_CYAN, bold=True))
        lines.append(f"  {colorize(ai_cmd.command, AnsiCode.FG_GREEN, bold=True)}")
        if ai_cmd.description:
            lines.append(f"  {ai_cmd.description}")
        if ai_cmd.explanation:
            lines.append(f"  {ai_cmd.explanation[:100]}")
        if ai_cmd.confidence < 0.7:
            conf_str = f"{ai_cmd.confidence:.0%}"
            lines.append(f"  Confidence: {colorize(conf_str, AnsiCode.FG_YELLOW)}")
        else:
            conf_str = f"{ai_cmd.confidence:.0%}"
            lines.append(f"  Confidence: {colorize(conf_str, AnsiCode.FG_GREEN)}")

        return "\n".join(lines)

    def confirm_and_execute(self, ai_cmd: AICommand) -> bool:
        """Ask the user to confirm before executing an AI-suggested command."""
        if not ai_cmd.needs_confirmation or ai_cmd.confidence > 0.9:
            return True

        print(self.format_ai_response(ai_cmd))
        print()

        try:
            response = input(colorize("Execute this command? [Y/n] ", AnsiCode.FG_CYAN)).strip().lower()
            return response in ("", "y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False

    def interactive_session(self) -> None:
        """Start an interactive AI command session."""
        self._interactive_mode = True
        print(colorize("AI Command Mode [type 'exit' to quit]", AnsiCode.FG_CYAN, bold=True))
        print()

        try:
            while True:
                try:
                    query = input(colorize("ai> ", AnsiCode.FG_MAGENTA, bold=True)).strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break

                if not query:
                    continue

                if query.lower() in ("exit", "quit", "q"):
                    break

                if query.startswith("!"):
                    # Treat as raw command
                    print(f"  {colorize(query[1:], AnsiCode.FG_GREEN)}")
                    continue

                ai_cmd = self.handle_natural_language(query)
                if ai_cmd:
                    if self.confirm_and_execute(ai_cmd):
                        print(f"  {colorize('->', AnsiCode.FG_YELLOW)} {ai_cmd.command}")
                    else:
                        print("  Cancelled")
                else:
                    print(colorize("  Could not generate a command.", AnsiCode.FG_RED))
                print()
        finally:
            self._interactive_mode = False

    def batch_process(self, queries: t.List[str]) -> t.List[AICommand]:
        """Process multiple natural language queries."""
        results = []
        for query in queries:
            ai_cmd = self.handle_natural_language(query)
            if ai_cmd:
                results.append(ai_cmd)
        return results

    def get_last_command(self) -> t.Optional[AICommand]:
        """Get the last AI-generated command."""
        return self._last_command

    def __repr__(self) -> str:
        return f"AICommandHandler(assistant={self.assistant})"


# ---------------------------------------------------------------------------
# AI Shell Commands
# ---------------------------------------------------------------------------

def ai_ask(query: str) -> None:
    """Ask AI a question about shell commands."""
    handler = AICommandHandler()
    ai_cmd = handler.handle_natural_language(query)
    if ai_cmd:
        print(handler.format_ai_response(ai_cmd))
    else:
        print(colorize("AI assistant is not available. Check your API key configuration.", AnsiCode.FG_RED))


def ai_explain(command: str) -> None:
    """Explain what a shell command does."""
    handler = AICommandHandler()
    explanation = handler.explain_command(command)
    if explanation:
        print(colorize(f"Command: {command}", AnsiCode.FG_CYAN, bold=True))
        print(f"\n{explanation}")
    else:
        print(colorize("AI assistant is not available.", AnsiCode.FG_RED))


def ai_script(description: str) -> None:
    """Generate a script from a description."""
    handler = AICommandHandler()
    script = handler.generate_script(description)
    if script:
        print(colorize("Generated Script:", AnsiCode.FG_CYAN, bold=True))
        print()
        print(script)
    else:
        print(colorize("AI assistant is not available.", AnsiCode.FG_RED))


def ai_translate(command: str, target_os: str = "linux") -> None:
    """Translate a command between OS types."""
    handler = AICommandHandler()
    translation = handler.translate_command(command, target_os)
    if translation:
        print(colorize(f"Original: {command}", AnsiCode.FG_WHITE))
        print(colorize(f"Target ({target_os}): {translation}", AnsiCode.FG_GREEN))
    else:
        print(colorize("AI assistant is not available.", AnsiCode.FG_RED))


# ---------------------------------------------------------------------------
# AI-aware command execution
# ---------------------------------------------------------------------------

class AIEnhancedExecutor:
    """Wrapper that adds AI features to command execution."""

    def __init__(self) -> None:
        self.handler = AICommandHandler()

    def pre_process(self, command: str) -> str:
        """Pre-process a command: expand shortcuts, check for AI commands."""
        # Check if command starts with AI prefix
        ai_prefixes = ["?", "ai:", "ai ", "!ai", "/ai"]

        for prefix in ai_prefixes:
            if command.startswith(prefix):
                query = command[len(prefix):].strip()
                ai_cmd = self.handler.handle_natural_language(query)
                if ai_cmd and self.handler.confirm_and_execute(ai_cmd):
                    return ai_cmd.command
                return ""

        # Check for command optimization
        optimized = self.handler.get_shortcut(command)
        if optimized and optimized != command:
            print(colorize(f"Tip: Try '{optimized}' instead", AnsiCode.FG_YELLOW))

        return command

    def post_process(self, command: str, exit_code: int, output: str) -> None:
        """Post-process execution: suggest fixes on error."""
        if exit_code != 0 and output:
            fix = self.handler.suggest_fix(command, output[:200])
            if fix:
                print(colorize(f"\nSuggested fix: {fix}", AnsiCode.FG_YELLOW))

    def __repr__(self) -> str:
        return f"AIEnhancedExecutor(handler={self.handler})"


# ---------------------------------------------------------------------------
# Module-level access
# ---------------------------------------------------------------------------

_ai_handler: t.Optional[AICommandHandler] = None


def get_ai_handler() -> AICommandHandler:
    """Get the global AI command handler."""
    global _ai_handler
    if _ai_handler is None:
        _ai_handler = AICommandHandler()
    return _ai_handler


__all__ = [
    "AICommandHandler",
    "AIEnhancedExecutor",
    "get_ai_handler",
    "ai_ask",
    "ai_explain",
    "ai_script",
    "ai_translate",
]