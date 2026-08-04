"""
日志管理模块 - Log management for Ainos containers.

支持:
- 日志收集 (stdout/stderr)
- 日志轮转
- 日志驱动 (json-file, journald, syslog)
- 日志过滤和查询
- 日志归档
"""

import datetime
import enum
import gzip
import json
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, ClassVar, Optional, Union

logger = logging.getLogger(__name__)

LOG_DIR = Path("/var/log/ainos/containers")


class LogDriver(enum.Enum):
    """Supported log drivers."""

    JSON_FILE = "json-file"
    JOURNALD = "journald"
    SYSLOG = "syslog"
    NONE = "none"

    def __str__(self) -> str:
        return self.value


class LogLevel(enum.IntEnum):
    """Log severity levels."""

    DEBUG = 0
    INFO = 1
    WARN = 2
    ERROR = 3
    FATAL = 4


@dataclass
class LogEntry:
    """A single log entry from a container."""

    timestamp: str
    message: str
    stream: str  # "stdout" or "stderr"
    level: LogLevel = LogLevel.INFO
    container_id: str = ""
    source: str = "container"
    pid: Optional[int] = None
    tags: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: str) -> "LogEntry":
        """Parse a log entry from JSON."""
        try:
            parsed = json.loads(data)
            level = LogLevel(parsed.get("level", 1))
            return cls(
                timestamp=parsed.get("timestamp", ""),
                message=parsed.get("message", ""),
                stream=parsed.get("stream", "stdout"),
                level=level,
                container_id=parsed.get("container_id", ""),
                source=parsed.get("source", "container"),
                pid=parsed.get("pid"),
                tags=parsed.get("tags", {}),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            return cls(
                timestamp=datetime.datetime.utcnow().isoformat(),
                message=data,
                stream="stdout",
            )

    def to_json(self) -> str:
        """Serialize to JSON string."""
        data: dict[str, Any] = {
            "timestamp": self.timestamp,
            "message": self.message,
            "stream": self.stream,
            "level": self.level.value,
            "container_id": self.container_id,
            "source": self.source,
        }
        if self.pid is not None:
            data["pid"] = self.pid
        if self.tags:
            data["tags"] = self.tags
        return json.dumps(data, ensure_ascii=False)

    def __str__(self) -> str:
        return f"[{self.timestamp}] [{self.stream}] {self.message}"


@dataclass
class LogConfig:
    """Logging configuration for a container."""

    driver: LogDriver = LogDriver.JSON_FILE
    max_size: str = "10m"  # Max log file size before rotation
    max_files: int = 5     # Max number of rotated log files
    compress: bool = True  # Compress rotated logs
    enabled: bool = True
    tags: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        """Validate log configuration."""
        if self.max_files < 1:
            raise ValueError(f"max_files must be >= 1, got {self.max_files}")
        size_bytes = self.parse_size(self.max_size)
        if size_bytes < 1024:
            raise ValueError(f"max_size must be at least 1KB, got {self.max_size}")

    @staticmethod
    def parse_size(size_str: str) -> int:
        """Parse a human-readable size string to bytes."""
        size_str = size_str.strip().lower()
        multipliers = {
            "k": 1024,
            "m": 1024 * 1024,
            "g": 1024 * 1024 * 1024,
            "t": 1024 * 1024 * 1024 * 1024,
        }
        match = re.match(r"^(\d+(?:\.\d+)?)\s*([kmgt]?b?)?$", size_str)
        if not match:
            raise ValueError(f"Invalid size string: {size_str}")
        value = float(match.group(1))
        suffix = (match.group(2) or "b").rstrip("b")
        multiplier = multipliers.get(suffix, 1)
        return int(value * multiplier)


class LogDriverBase:
    """Abstract base class for log drivers."""

    def __init__(self, container_id: str, config: LogConfig) -> None:
        self.container_id = container_id
        self.config = config

    def write(self, entry: LogEntry) -> None:
        """Write a log entry."""
        raise NotImplementedError

    def read(self, tail: int = 100, stream: Optional[str] = None) -> list[LogEntry]:
        """Read log entries."""
        raise NotImplementedError

    def close(self) -> None:
        """Close the log driver."""

    def cleanup(self) -> None:
        """Clean up log resources."""


class JSONFileDriver(LogDriverBase):
    """
    JSON File log driver.

    Writes log entries as JSON lines to a file with rotation support.
    """

    def __init__(self, container_id: str, config: LogConfig) -> None:
        super().__init__(container_id, config)
        self.log_dir = LOG_DIR / container_id
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "container.log"
        self._current_size = 0
        self._file_handle: Optional[TextIO] = None
        self._open_file()

    def _open_file(self) -> None:
        """Open the log file for appending."""
        try:
            self._file_handle = open(self.log_file, "a", encoding="utf-8")
            self._current_size = self.log_file.stat().st_size
        except OSError as e:
            logger.error("Failed to open log file %s: %s", self.log_file, e)

    def _rotate(self) -> None:
        """Rotate the log file if it exceeds max_size."""
        max_bytes = LogConfig.parse_size(self.config.max_size)
        if self._current_size < max_bytes:
            return

        # Close current file
        self._close_file()

        # Rotate existing files
        for i in range(self.config.max_files - 1, 0, -1):
            src = self.log_dir / f"container.log.{i}"
            dst = self.log_dir / f"container.log.{i + 1}"
            if src.exists():
                shutil.move(str(src), str(dst))

        # Compress old log if needed
        if self.config.compress:
            old_log = self.log_dir / "container.log.1"
            if old_log.exists():
                with open(old_log, "rb") as f_in:
                    with gzip.open(str(old_log) + ".gz", "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                old_log.unlink()
                # Rename compressed
                (self.log_dir / "container.log.1.gz").rename(
                    self.log_dir / "container.log.1.gz"
                )

        # Rename current log
        self.log_file.rename(self.log_dir / "container.log.1")

        # Open new log file
        self._open_file()
        logger.info("Rotated log file for container %s", self.container_id)

    def _close_file(self) -> None:
        """Close the log file handle."""
        if self._file_handle:
            try:
                self._file_handle.close()
            except OSError:
                pass
            self._file_handle = None

    def write(self, entry: LogEntry) -> None:
        """Write a log entry as JSON line."""
        if not self.config.enabled:
            return

        entry.container_id = self.container_id
        entry.tags.update(self.config.tags)
        line = entry.to_json() + "\n"

        if self._file_handle:
            try:
                self._file_handle.write(line)
                self._file_handle.flush()
                self._current_size += len(line.encode("utf-8"))
                self._rotate()
            except OSError as e:
                logger.error("Failed to write log entry: %s", e)

    def read(self, tail: int = 100, stream: Optional[str] = None) -> list[LogEntry]:
        """
        Read log entries from the log file.

        Args:
            tail: Number of recent entries to return.
            stream: Filter by stream ("stdout" or "stderr").

        Returns:
            List of LogEntry objects.
        """
        entries: list[LogEntry] = []

        # Read from all log files
        log_files: list[Path] = [self.log_file]
        for i in range(1, self.config.max_files + 1):
            f = self.log_dir / f"container.log.{i}"
            if f.exists():
                log_files.append(f)
            # Also check compressed
            f_gz = self.log_dir / f"container.log.{i}.gz"
            if f_gz.exists():
                log_files.append(f_gz)

        lines: list[str] = []
        for fpath in log_files:
            try:
                if fpath.suffix == ".gz":
                    with gzip.open(fpath, "rt", encoding="utf-8") as f:
                        lines.extend(f.readlines())
                else:
                    with open(fpath, "r", encoding="utf-8") as f:
                        lines.extend(f.readlines())
            except OSError:
                continue

        # Parse entries
        for line in lines[-tail:]:
            line = line.strip()
            if not line:
                continue
            entry = LogEntry.from_json(line)
            if stream is None or entry.stream == stream:
                entries.append(entry)

        return entries

    def close(self) -> None:
        """Close the log file."""
        self._close_file()

    def cleanup(self) -> None:
        """Remove all log files for this container."""
        self.close()
        if self.log_dir.exists():
            shutil.rmtree(self.log_dir, ignore_errors=True)
            logger.info("Cleaned up logs for container %s", self.container_id)

    def __del__(self) -> None:
        self.close()


class LogManager:
    """
    Central log manager for containers.

    Manages log drivers, log querying, and log lifecycle.
    """

    _drivers: ClassVar[dict[str, type[LogDriverBase]]] = {
        "json-file": JSONFileDriver,
    }
    _instances: ClassVar[dict[str, LogDriverBase]] = {}

    def __init__(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def register_driver(cls, name: str, driver_cls: type[LogDriverBase]) -> None:
        """Register a custom log driver."""
        cls._drivers[name] = driver_cls
        logger.info("Registered log driver: %s", name)

    def get_driver(self, container_id: str, config: LogConfig) -> LogDriverBase:
        """
        Get or create a log driver for a container.

        Args:
            container_id: Container identifier.
            config: Logging configuration.

        Returns:
            LogDriverBase instance.
        """
        key = f"{container_id}:{config.driver.value}"
        if key not in self._instances:
            driver_cls = self._drivers.get(config.driver.value)
            if driver_cls is None:
                raise ValueError(f"Unsupported log driver: {config.driver}")
            self._instances[key] = driver_cls(container_id, config)
        return self._instances[key]

    def write_log(self, container_id: str, message: str, stream: str = "stdout",
                  level: LogLevel = LogLevel.INFO, config: Optional[LogConfig] = None) -> None:
        """
        Write a log entry for a container.

        Args:
            container_id: Container identifier.
            message: Log message.
            stream: "stdout" or "stderr".
            level: Log severity level.
            config: Log configuration (uses default if None).
        """
        cfg = config or LogConfig()
        if not cfg.enabled:
            return

        try:
            driver = self.get_driver(container_id, cfg)
            entry = LogEntry(
                timestamp=datetime.datetime.utcnow().isoformat(),
                message=message,
                stream=stream,
                level=level,
                container_id=container_id,
            )
            driver.write(entry)
        except Exception as e:
            logger.error("Failed to write log for container %s: %s", container_id, e)

    def read_logs(self, container_id: str, tail: int = 100,
                  stream: Optional[str] = None,
                  config: Optional[LogConfig] = None) -> list[LogEntry]:
        """
        Read log entries for a container.

        Args:
            container_id: Container identifier.
            tail: Number of recent entries to return.
            stream: Filter by stream.
            config: Log configuration.

        Returns:
            List of LogEntry objects.
        """
        cfg = config or LogConfig()
        try:
            driver = self.get_driver(container_id, cfg)
            return driver.read(tail=tail, stream=stream)
        except Exception as e:
            logger.error("Failed to read logs for container %s: %s", container_id, e)
            return []

    def close_driver(self, container_id: str, driver_name: str = "json-file") -> None:
        """Close a log driver for a container."""
        key = f"{container_id}:{driver_name}"
        driver = self._instances.pop(key, None)
        if driver:
            driver.close()

    def cleanup_container(self, container_id: str) -> None:
        """Clean up all log resources for a container."""
        keys_to_remove = [k for k in self._instances if k.startswith(container_id)]
        for key in keys_to_remove:
            driver = self._instances.pop(key, None)
            if driver:
                driver.cleanup()

    def cleanup_all(self) -> None:
        """Clean up all log resources."""
        for driver in self._instances.values():
            try:
                driver.close()
            except Exception:
                pass
        self._instances.clear()

    def get_log_file_path(self, container_id: str) -> Optional[Path]:
        """Get the path to a container's log file."""
        log_path = LOG_DIR / container_id / "container.log"
        if log_path.exists():
            return log_path
        return None

    def get_log_stats(self, container_id: str) -> dict[str, Any]:
        """
        Get log statistics for a container.

        Returns:
            Dict with log file count, total size, etc.
        """
        log_dir = LOG_DIR / container_id
        if not log_dir.exists():
            return {"exists": False, "file_count": 0, "total_size": 0}

        total_size = 0
        file_count = 0
        for f in log_dir.iterdir():
            if f.is_file():
                try:
                    total_size += f.stat().st_size
                    file_count += 1
                except OSError:
                    continue

        return {
            "exists": True,
            "file_count": file_count,
            "total_size": total_size,
            "log_dir": str(log_dir),
        }