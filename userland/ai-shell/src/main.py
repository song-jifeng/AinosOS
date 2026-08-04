"""
Main entry point for Ainos Shell (ainos-sh).

Provides the REPL loop and command-line interface for the shell.
Supports:
- Interactive mode (default)
- Command execution mode (-c)
- Script execution (file argument)
- Plugin loading
- AI integration
- Configuration overrides via CLI flags
"""

from __future__ import annotations

import argparse
import os
import sys
import typing as t

from .utils import (
    IS_WINDOWS,
    IS_POSIX,
    AnsiCode,
    colorize,
    is_tty,
    enable_virtual_terminal,
    get_config_dir,
    get_data_dir,
    ensure_dir,
    get_env,
    set_env,
    file_exists,
    read_file,
    expanduser,
)
from .config import get_config, get_config_manager
from .shell import create_shell, get_shell
from .plugins import get_plugin_manager

# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="ainos-sh",
        description="Ainos Shell - An AI-powered shell for developers",
        epilog="For more information, visit https://github.com/ainos/ainos-sh",
    )

    parser.add_argument(
        "-c", "--command",
        type=str,
        help="Execute a single command and exit",
        metavar="COMMAND",
    )

    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Force interactive mode",
    )

    parser.add_argument(
        "-l", "--login",
        action="store_true",
        help="Act as a login shell",
    )

    parser.add_argument(
        "--norc",
        action="store_true",
        help="Do not read the RC file on startup",
    )

    parser.add_argument(
        "--rcfile",
        type=str,
        help="Use a custom RC file instead of the default",
        metavar="FILE",
    )

    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Disable AI features",
    )

    parser.add_argument(
        "--theme",
        type=str,
        help="Set the prompt theme",
        metavar="NAME",
    )

    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version information and exit",
    )

    parser.add_argument(
        "script",
        nargs="?",
        type=str,
        help="Script file to execute",
        metavar="SCRIPT",
    )

    parser.add_argument(
        "script_args",
        nargs=argparse.REMAINDER,
        help="Arguments for the script",
        metavar="ARGS",
    )

    return parser


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def apply_cli_overrides(args: argparse.Namespace) -> None:
    """Apply command-line overrides to the configuration."""
    config = get_config()

    if args.no_ai:
        config.ai.enabled = False

    if args.theme:
        config.theme.name = args.theme

    if args.login:
        config.behavior.login = True

    if args.interactive:
        config.behavior.interactive = True


def load_rc_file(args: argparse.Namespace) -> None:
    """Load the RC file specified by arguments or default."""
    if args.norc:
        return

    rc_path = args.rcfile
    if rc_path:
        rc_path = expanduser(rc_path)
    else:
        # Default RC file locations
        candidates = [
            os.path.join(get_home_dir(), ".ainoshrc"),
            os.path.join(get_config_dir(), "rc"),
            os.path.join(get_config_dir(), "ainosrc"),
            os.path.join(get_config_dir(), "init.ainos"),
        ]
        for candidate in candidates:
            rc_path = expanduser(candidate)
            if file_exists(rc_path):
                break
        else:
            rc_path = os.path.join(get_config_dir(), "rc")

    if file_exists(rc_path):
        try:
            content = read_file(rc_path)
            shell = get_shell()
            if shell:
                shell.execute_source(content)
            else:
                # Store for later execution
                import sys
                # This will be executed when the shell starts
                pass
        except Exception as e:
            print(f"Error loading RC file: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> int:
    """Main entry point for Ainos Shell."""
    # Enable virtual terminal on Windows
    enable_virtual_terminal()

    # Parse arguments
    parser = build_parser()
    args = parser.parse_args()

    # Handle --version
    if args.version:
        config = get_config()
        print(f"ainos-sh version {config.shell_version}")
        print(f"Python: {sys.version}")
        print(f"Platform: {sys.platform}")
        return 0

    # Create shell
    shell = create_shell()

    # Apply CLI overrides
    apply_cli_overrides(args)

    # Set up environment
    _setup_environment()

    # Execute command mode (-c)
    if args.command:
        return _execute_command(shell, args.command)

    # Execute script mode
    if args.script:
        return _execute_script(shell, args.script, args.script_args)

    # Interactive mode
    if not is_tty(sys.stdin):
        return _execute_stdin(shell)

    # Load RC file
    load_rc_file(args)

    # Run interactive shell
    return shell.run()


def _setup_environment() -> None:
    """Set up the shell environment."""
    # Set SHELL environment variable
    shell_path = os.environ.get("SHELL", "")
    if not shell_path:
        # Find our own path
        if getattr(sys, "frozen", False):
            shell_path = sys.executable
        else:
            # Try to find ainos-sh in PATH
            import shutil
            found = shutil.which("ainos-sh")
            if found:
                shell_path = found
            else:
                shell_path = os.path.abspath(sys.argv[0])
        set_env("SHELL", shell_path)

    # Set TERM if not set
    if not get_env("TERM"):
        set_env("TERM", "xterm-256color")

    # Set up Ainos-specific variables
    set_env("AINOS_SH_VERSION", get_config().shell_version)
    set_env("AINOS_HOME", get_config_dir())
    set_env("AINOS_DATA_DIR", get_data_dir())


def _execute_command(shell: t.Any, command: str) -> int:
    """Execute a single command and exit."""
    shell.execute_source(command)
    return shell.state.exit_code


def _execute_script(shell: t.Any, script_path: str, script_args: t.List[str]) -> int:
    """Execute a script file."""
    path = expanduser(script_path)
    if not file_exists(path):
        print(f"ainos-sh: {script_path}: No such file or directory",
              file=sys.stderr)
        return 127

    # Set script arguments
    if script_args:
        sys.argv = [script_path] + script_args
    else:
        sys.argv = [script_path]

    try:
        content = read_file(path)
        shell.execute_source(content)
        return shell.state.exit_code
    except Exception as e:
        print(f"ainos-sh: {script_path}: {e}", file=sys.stderr)
        return 1


def _execute_stdin(shell: t.Any) -> int:
    """Execute commands from stdin (pipe mode)."""
    for line in sys.stdin:
        line = line.strip()
        if line and not line.startswith("#"):
            shell.execute_source(line)
    return shell.state.exit_code


# ---------------------------------------------------------------------------
# Script entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
    except BrokenPipeError:
        pass
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


__all__ = ["main"]