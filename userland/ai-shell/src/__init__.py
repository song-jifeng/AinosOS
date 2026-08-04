"""
Ainos Shell (ainos-sh) - An AI-powered shell for developers.

Provides a modern, extensible shell with:
- Built-in commands (cd, ls, grep, find, etc.)
- Pipeline and redirection support
- Tab completion with AI suggestions
- SQLite-backed command history
- Colorful, themeable prompt with Git status
- AI-powered natural language to command translation
- Plugin system for extensibility
"""

from __future__ import annotations

__version__ = "1.0.0"
__author__ = "Ainos Team"
__license__ = "MIT"

from . import utils
from . import config
from . import themes
from . import parser
from . import executor
from . import builtins
from . import prompt
from . import completer
from . import history
from . import ai_assist
from . import ai_commands
from . import completion
from . import plugins
from . import shell
from . import main

__all__ = [
    "utils",
    "config",
    "themes",
    "parser",
    "executor",
    "builtins",
    "prompt",
    "completer",
    "history",
    "ai_assist",
    "ai_commands",
    "completion",
    "plugins",
    "shell",
    "main",
]