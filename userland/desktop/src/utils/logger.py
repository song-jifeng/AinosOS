#!/usr/bin/env python3
"""Ainos Desktop - Logging Utilities.

This module provides logging configuration with rotating file handlers,
colored console output, and a signal-based log emission system for
the real-time log viewer widget.
"""

import os
import sys
import logging
import logging.handlers
from enum import Enum, auto
from typing import Any
from PySide6.QtCore import QObject, Signal


class LogLevel(Enum):
    """Log level constants matching Python's logging levels."""

    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL

    @classmethod
    def from_string(cls, name: str) -> "LogLevel":
        """Convert string to LogLevel.

        Args:
            name: Level name (case-insensitive).

        Returns:
            Corresponding LogLevel.
        """
        name = name.upper()
        for level in cls:
            if level.name == name:
                return level
        return cls.INFO

    @property
    def display_name(self) -> str:
        """Get human-readable display name.

        Returns:
            Formatted level name.
        """
        names = {
            "DEBUG": "DEBUG",
            "INFO": "INFO",
            "WARNING": "WARN",
            "ERROR": "ERROR",
            "CRITICAL": "CRIT",
        }
        return names.get(self.name, self.name)

    @property
    def color_code(self) -> str:
        """Get ANSI color code for this level.

        Returns:
            ANSI escape code string.
        """
        colors = {
            "DEBUG": "\033[36m",    # Cyan
            "INFO": "\033[32m",     # Green
            "WARNING": "\033[33m",  # Yellow
            "ERROR": "\033[31m",    # Red
            "CRITICAL": "\033[41m\033[37m",  # White on Red
        }
        return colors.get(self.name, "\033[0m")

    @property
    def qt_color(self) -> str:
        """Get color name for Qt styling.

        Returns:
            CSS-compatible color name.
        """
        colors = {
            "DEBUG": "#00BCD4",
            "INFO": "#4CAF50",
            "WARNING": "#FF9800",
            "ERROR": "#F44336",
            "CRITICAL": "#D32F2F",
        }
        return colors.get(self.name, "#FFFFFF")


class LogHandler(logging.Handler):
    """Custom logging handler that emits log records via Qt signals.

    Used by the LogViewerWidget to receive real-time log entries.
    """

    def __init__(self, signal_emitter: QObject | None = None):
        """Initialize the handler.

        Args:
            signal_emitter: Optional QObject with a log_received signal.
        """
        super().__init__()
        self._signal_emitter = signal_emitter
        self._log_buffer: list[logging.LogRecord] = []
        self._buffer_size = 1000
        self.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    def set_signal_emitter(self, emitter: QObject) -> None:
        """Set the signal emitter for log forwarding.

        Args:
            emitter: QObject with a log_received signal.
        """
        self._signal_emitter = emitter

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record.

        Args:
            record: The log record to process.
        """
        try:
            # Format the message
            msg = self.format(record)

            # Store in buffer
            self._log_buffer.append(record)
            if len(self._log_buffer) > self._buffer_size:
                self._log_buffer.pop(0)

            # Emit via signal if connected
            if self._signal_emitter and hasattr(self._signal_emitter, "log_received"):
                try:
                    self._signal_emitter.log_received.emit(record)  # type: ignore
                except RuntimeError:
                    # Signal emitter was deleted
                    self._signal_emitter = None

        except Exception:
            self.handleError(record)

    def get_buffer(self) -> list[logging.LogRecord]:
        """Get the internal log buffer.

        Returns:
            List of recent LogRecord objects.
        """
        return list(self._log_buffer)

    def clear_buffer(self) -> None:
        """Clear the internal log buffer."""
        self._log_buffer.clear()


class ColoredFormatter(logging.Formatter):
    """Log formatter with ANSI color support for terminal output."""

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[41m\033[37m",
        "RESET": "\033[0m",
    }

    def __init__(self, fmt: str | None = None, use_colors: bool = True):
        """Initialize the formatter.

        Args:
            fmt: Format string. Uses default if None.
            use_colors: Whether to include ANSI color codes.
        """
        if fmt is None:
            fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        super().__init__(fmt, datefmt="%Y-%m-%d %H:%M:%S")
        self._use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record with optional colors.

        Args:
            record: The log record to format.

        Returns:
            Formatted log string.
        """
        if self._use_colors and sys.stderr.isatty():
            level_name = record.levelname
            color = self.COLORS.get(level_name, self.COLORS["RESET"])
            record.levelname = f"{color}{level_name}{self.COLORS['RESET']}"
            record.msg = f"{color}{record.msg}{self.COLORS['RESET']}"

        return super().format(record)


class LogEmitter(QObject):
    """Qt object that emits log records as signals for the UI."""

    log_received = Signal(object)  # LogRecord


# Global emitter instance
_log_emitter = LogEmitter()


def get_log_emitter() -> LogEmitter:
    """Get the global log emitter instance.

    Returns:
        The global LogEmitter instance.
    """
    return _log_emitter


def setup_logging(
    level: int = logging.INFO,
    log_file: str | None = None,
    max_size_mb: int = 100,
    backup_count: int = 5,
    use_colors: bool = True,
    log_format: str | None = None,
) -> logging.Logger:
    """Configure application-wide logging.

    Sets up console and file handlers with appropriate formatting.
    Should be called once at application startup.

    Args:
        level: Logging level (use logging.DEBUG, logging.INFO, etc.).
        log_file: Path to the log file. If None, no file logging is set up.
        max_size_mb: Maximum log file size in MB before rotation.
        backup_count: Number of rotated log files to keep.
        use_colors: Whether to use ANSI colors in console output.
        log_format: Custom log format string.

    Returns:
        The root logger instance.
    """
    if log_format is None:
        log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)
    console_formatter = ColoredFormatter(log_format, use_colors=use_colors)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # Qt signal handler (for UI log viewer)
    qt_handler = LogHandler(_log_emitter)
    qt_handler.setLevel(level)
    qt_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    qt_handler.setFormatter(qt_formatter)
    root_logger.addHandler(qt_handler)

    # File handler with rotation
    if log_file:
        try:
            log_dir = os.path.dirname(log_file)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)

            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=max_size_mb * 1024 * 1024,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(level)
            file_formatter = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            file_handler.setFormatter(file_formatter)
            root_logger.addHandler(file_handler)

            logger = logging.getLogger(__name__)
            logger.info("File logging enabled: %s (max %dMB, %d backups)",
                        log_file, max_size_mb, backup_count)
        except (IOError, OSError) as e:
            logger = logging.getLogger(__name__)
            logger.warning("Could not set up file logging: %s", e)

    # Suppress verbose loggers
    logging.getLogger("PySide6").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.info("Logging configured: level=%s, colors=%s, file=%s",
                logging.getLevelName(level), use_colors, log_file)

    return root_logger


class AinosLogger:
    """Convenience wrapper around Python's logging for consistent usage.

    Provides structured logging methods with context information.
    """

    def __init__(self, name: str):
        """Initialize the logger.

        Args:
            name: Logger name (typically __name__).
        """
        self._logger = logging.getLogger(name)

    def debug(self, msg: str, *args, **kwargs) -> None:
        """Log a debug message.

        Args:
            msg: Message format string.
            *args: Format arguments.
            **kwargs: Additional context (extra, exc_info, etc.).
        """
        self._logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:
        """Log an info message.

        Args:
            msg: Message format string.
            *args: Format arguments.
            **kwargs: Additional context.
        """
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs) -> None:
        """Log a warning message.

        Args:
            msg: Message format string.
            *args: Format arguments.
            **kwargs: Additional context.
        """
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs) -> None:
        """Log an error message.

        Args:
            msg: Message format string.
            *args: Format arguments.
            **kwargs: Additional context.
        """
        self._logger.error(msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs) -> None:
        """Log a critical message.

        Args:
            msg: Message format string.
            *args: Format arguments.
            **kwargs: Additional context.
        """
        self._logger.critical(msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs) -> None:
        """Log an exception with traceback.

        Args:
            msg: Message format string.
            *args: Format arguments.
            **kwargs: Additional context.
        """
        self._logger.exception(msg, *args, **kwargs)

    def log(self, level: int, msg: str, *args, **kwargs) -> None:
        """Log at a specific level.

        Args:
            level: Numeric logging level.
            msg: Message format string.
            *args: Format arguments.
            **kwargs: Additional context.
        """
        self._logger.log(level, msg, *args, **kwargs)

    @property
    def logger(self) -> logging.Logger:
        """Get the underlying Python logger.

        Returns:
            The logging.Logger instance.
        """
        return self._logger