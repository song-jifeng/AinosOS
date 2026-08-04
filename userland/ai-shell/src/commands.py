"""
Commands module - wraps built-in commands and provides command dispatch.

This module serves as a bridge between the shell core and the built-in
command implementations, providing command lookup, dispatch, and
registration functionality.
"""

from __future__ import annotations

import typing as t
from .builtins import BUILTINS, BUILTIN_HELP, BuiltinFunc

# Re-export for convenience
__all__ = ["BUILTINS", "BUILTIN_HELP", "BuiltinFunc", "get_command", "list_commands", "is_builtin"]


def get_command(name: str) -> t.Optional[BuiltinFunc]:
    """Get a built-in command function by name.

    Args:
        name: The command name to look up.

    Returns:
        The command function, or None if not found.
    """
    return BUILTINS.get(name)


def list_commands() -> t.List[str]:
    """List all available built-in command names.

    Returns:
        Sorted list of command names.
    """
    return sorted(BUILTINS.keys())


def is_builtin(name: str) -> bool:
    """Check if a command name is a built-in.

    Args:
        name: The command name to check.

    Returns:
        True if the command is a built-in.
    """
    return name in BUILTINS


def get_help(name: str) -> t.Optional[str]:
    """Get help text for a command.

    Args:
        name: The command name.

    Returns:
        Help text string, or None if not found.
    """
    return BUILTIN_HELP.get(name)