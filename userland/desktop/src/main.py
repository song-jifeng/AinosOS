#!/usr/bin/env python3
"""Ainos Desktop - Application Entry Point.

This module serves as the main entry point for the Ainos Desktop application.
It initializes the application, applies the theme, and starts the event loop.
"""

import sys
import os
import argparse
import logging

# Ensure src is on path
_src_dir = os.path.dirname(os.path.abspath(__file__))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from app import AinosApplication
from utils.logger import setup_logging


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        args: Command-line arguments to parse. Defaults to sys.argv[1:].

    Returns:
        Parsed namespace with application configuration.
    """
    parser = argparse.ArgumentParser(
        description="Ainos Desktop - AI Backend Management Interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ainos-desktop                    # Launch with default settings
  ainos-desktop --theme dark       # Launch with dark theme
  ainos-desktop --verbose          # Launch with verbose logging
  ainos-desktop --config custom    # Launch with custom config
        """,
    )

    parser.add_argument(
        "--theme",
        choices=["dark", "light", "system"],
        default="dark",
        help="Initial theme (default: dark)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to configuration file",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Path to log file",
    )
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Disable system tray icon",
    )
    parser.add_argument(
        "--minimized",
        action="store_true",
        help="Start minimized to system tray",
    )
    parser.add_argument(
        "--fullscreen",
        action="store_true",
        help="Start in fullscreen mode",
    )
    parser.add_argument(
        "--geometry",
        type=str,
        default=None,
        help="Window geometry: WIDTHxHEIGHT or X,Y,WxH (e.g. 1280x800 or 100,50,1280x800)",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version and exit",
    )

    return parser.parse_args(args)


def configure_from_args(app: AinosApplication, args: argparse.Namespace) -> None:
    """Apply parsed arguments to the application.

    Args:
        app: The AinosApplication instance.
        args: Parsed command-line arguments.
    """
    # Apply theme
    if args.theme:
        app.config.set("theme", args.theme, save=True)

    # Apply config file
    if args.config:
        config_path = os.path.abspath(args.config)
        if os.path.isfile(config_path):
            app.config.load_from_file(config_path)
        else:
            logging.warning("Config file not found: %s", config_path)

    # Window settings
    if args.fullscreen:
        app.config.set("window.fullscreen", True)
    if args.minimized:
        app.config.set("window.minimized", True)
    if args.no_tray:
        app.config.set("tray.enabled", False)
    if args.geometry:
        app.config.set("window.geometry", args.geometry)

    # Logging
    if args.log_file:
        app.config.set("logging.file", args.log_file)


def main() -> int:
    """Main entry point for the Ainos Desktop application.

    Returns:
        Exit code (0 for success).
    """
    args = parse_args()

    # Setup logging early
    log_level = logging.DEBUG if args.verbose else logging.INFO
    log_file = args.log_file or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "logs", "ainos.log"
    )
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    setup_logging(level=log_level, log_file=log_file)

    logger = logging.getLogger(__name__)
    logger.info("Starting Ainos Desktop v%s", __import__("__init__", fromlist=["__version__"]).__version__)

    if args.version:
        from __init__ import __version__
        print(f"Ainos Desktop v{__version__}")
        return 0

    # Create and configure application
    app = AinosApplication(
        sys.argv,
        app_name="Ainos Desktop",
        organization="Ainos",
        organization_domain="ainos.ai",
    )

    configure_from_args(app, args)

    # Apply initial theme
    theme_name = app.config.get("theme", "dark")
    app.apply_theme(theme_name)

    logger.info("Application initialized with theme: %s", theme_name)

    # Run the application
    exit_code = app.run()

    logger.info("Ainos Desktop exiting with code: %d", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())