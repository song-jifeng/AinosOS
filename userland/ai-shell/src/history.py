"""
History management for Ainos Shell.

Provides persistent command history storage using SQLite with:
- Full-text search across commands
- Reverse incremental search (Ctrl+R)
- Deduplication options
- History expansion (!!, !$, !:n)
- Session isolation
- Timestamp and duration tracking
- Exit code recording
- Tags and annotations
- Import/export functionality
- Configurable size limits
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sqlite3
import typing as t
from dataclasses import dataclass, field
from pathlib import Path

from .utils import (
    get_data_dir,
    ensure_dir,
    file_exists,
    read_file,
    write_file,
)
from .config import get_config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_HISTORY_DB = os.path.join(get_data_dir(), "history.db")
MAX_HISTORY_SIZE = 100000
RECENT_CACHE_SIZE = 1000


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class HistoryEntry:
    """A single history entry."""
    id: int = 0
    command: str = ""
    cwd: str = ""
    timestamp: float = 0.0
    duration: float = 0.0
    exit_code: int = 0
    session_id: str = ""
    hostname: str = ""
    tags: list = field(default_factory=list)
    annotation: str = ""

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = datetime.datetime.now().timestamp()

    @property
    def datetime(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(self.timestamp)

    @property
    def formatted_time(self) -> str:
        return self.datetime.strftime("%Y-%m-%d %H:%M:%S")

    @property
    def is_recent(self) -> bool:
        """Check if entry is from the last hour."""
        return (datetime.datetime.now().timestamp() - self.timestamp) < 3600

    @property
    def duration_str(self) -> str:
        """Format duration for display."""
        if self.duration < 0.001:
            return f"{self.duration * 1000000:.0f}us"
        elif self.duration < 1.0:
            return f"{self.duration * 1000:.1f}ms"
        elif self.duration < 60.0:
            return f"{self.duration:.2f}s"
        else:
            m = int(self.duration // 60)
            s = self.duration % 60
            return f"{m}m {s:.1f}s"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "command": self.command,
            "cwd": self.cwd,
            "timestamp": self.timestamp,
            "duration": self.duration,
            "exit_code": self.exit_code,
            "session_id": self.session_id,
            "hostname": self.hostname,
            "tags": self.tags,
            "annotation": self.annotation,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HistoryEntry":
        valid_keys = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**filtered)


# ---------------------------------------------------------------------------
# History Database
# ---------------------------------------------------------------------------

class HistoryDatabase:
    """SQLite-backed history storage."""

    def __init__(self, db_path: str = "") -> None:
        self.db_path = db_path or DEFAULT_HISTORY_DB
        self._conn: t.Optional[sqlite3.Connection] = None
        self._ensure_db()

    def _ensure_db(self) -> None:
        """Ensure the database directory and file exist."""
        ensure_dir(os.path.dirname(self.db_path))

    def connect(self) -> sqlite3.Connection:
        """Get or create the database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._create_tables()
        return self._conn

    def _create_tables(self) -> None:
        """Create the database schema if it doesn't exist."""
        conn = self.connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command TEXT NOT NULL,
                cwd TEXT DEFAULT '',
                timestamp REAL NOT NULL,
                duration REAL DEFAULT 0.0,
                exit_code INTEGER DEFAULT 0,
                session_id TEXT DEFAULT '',
                hostname TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                annotation TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_history_timestamp ON history(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_history_command ON history(command);
            CREATE INDEX IF NOT EXISTS idx_history_cwd ON history(cwd);
            CREATE INDEX IF NOT EXISTS idx_history_session ON history(session_id);
            CREATE INDEX IF NOT EXISTS idx_history_exit_code ON history(exit_code);

            CREATE VIRTUAL TABLE IF NOT EXISTS history_fts USING fts5(
                command, tags, annotation,
                content='history',
                content_rowid='id'
            );

            CREATE TRIGGER IF NOT EXISTS history_ai AFTER INSERT ON history BEGIN
                INSERT INTO history_fts(rowid, command, tags, annotation)
                VALUES (new.id, new.command, new.tags, new.annotation);
            END;

            CREATE TRIGGER IF NOT EXISTS history_ad AFTER DELETE ON history BEGIN
                INSERT INTO history_fts(history_fts, rowid, command, tags, annotation)
                VALUES ('delete', old.id, old.command, old.tags, old.annotation);
            END;

            CREATE TRIGGER IF NOT EXISTS history_au AFTER UPDATE ON history BEGIN
                INSERT INTO history_fts(history_fts, rowid, command, tags, annotation)
                VALUES ('delete', old.id, old.command, old.tags, old.annotation);
                INSERT INTO history_fts(rowid, command, tags, annotation)
                VALUES (new.id, new.command, new.tags, new.annotation);
            END;

            CREATE TABLE IF NOT EXISTS history_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            INSERT OR IGNORE INTO history_meta (key, value) VALUES ('version', '1');
            INSERT OR IGNORE INTO history_meta (key, value) VALUES ('created', datetime('now'));
        """)
        conn.commit()

    def add_entry(self, entry: HistoryEntry) -> int:
        """Add a history entry, returning the entry ID."""
        conn = self.connect()
        cursor = conn.execute(
            """INSERT INTO history (command, cwd, timestamp, duration, exit_code, session_id, hostname, tags, annotation)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.command,
                entry.cwd,
                entry.timestamp,
                entry.duration,
                entry.exit_code,
                entry.session_id,
                entry.hostname,
                json.dumps(entry.tags),
                entry.annotation,
            )
        )
        conn.commit()

        # Enforce size limit
        self._enforce_size_limit()

        entry.id = cursor.lastrowid
        return entry.id

    def _enforce_size_limit(self, max_size: int = MAX_HISTORY_SIZE) -> None:
        """Remove oldest entries if over the limit."""
        conn = self.connect()
        count = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        if count > max_size:
            to_delete = count - max_size
            conn.execute(
                "DELETE FROM history WHERE id IN (SELECT id FROM history ORDER BY timestamp ASC LIMIT ?)",
                (to_delete,)
            )
            conn.commit()

    def get_recent(self, limit: int = 50, offset: int = 0) -> t.List[HistoryEntry]:
        """Get the most recent history entries."""
        conn = self.connect()
        rows = conn.execute(
            "SELECT * FROM history ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def search(self, query: str, limit: int = 50, offset: int = 0) -> t.List[HistoryEntry]:
        """Search history using full-text search."""
        conn = self.connect()
        try:
            rows = conn.execute(
                """SELECT h.* FROM history h
                   JOIN history_fts fts ON h.id = fts.rowid
                   WHERE history_fts MATCH ?
                   ORDER BY h.timestamp DESC
                   LIMIT ? OFFSET ?""",
                (query, limit, offset)
            ).fetchall()
        except sqlite3.OperationalError:
            # Fallback to LIKE search
            pattern = f"%{query}%"
            rows = conn.execute(
                "SELECT * FROM history WHERE command LIKE ? ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                (pattern, limit, offset)
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def search_prefix(self, prefix: str, limit: int = 50) -> t.List[HistoryEntry]:
        """Search for commands starting with a prefix."""
        conn = self.connect()
        rows = conn.execute(
            "SELECT * FROM history WHERE command LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (f"{prefix}%", limit)
        ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def search_command(self, command: str, limit: int = 20) -> t.List[HistoryEntry]:
        """Find exact command matches."""
        conn = self.connect()
        rows = conn.execute(
            "SELECT * FROM history WHERE command = ? ORDER BY timestamp DESC LIMIT ?",
            (command, limit)
        ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def get_by_id(self, entry_id: int) -> t.Optional[HistoryEntry]:
        """Get a history entry by ID."""
        conn = self.connect()
        row = conn.execute(
            "SELECT * FROM history WHERE id = ?", (entry_id,)
        ).fetchone()
        if row:
            return self._row_to_entry(row)
        return None

    def get_last(self, n: int = 1) -> t.List[HistoryEntry]:
        """Get the last N entries."""
        conn = self.connect()
        rows = conn.execute(
            "SELECT * FROM history ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
        return [self._row_to_entry(row) for row in reversed(rows)]

    def get_by_session(self, session_id: str, limit: int = 100) -> t.List[HistoryEntry]:
        """Get all entries for a session."""
        conn = self.connect()
        rows = conn.execute(
            "SELECT * FROM history WHERE session_id = ? ORDER BY timestamp ASC LIMIT ?",
            (session_id, limit)
        ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def get_by_cwd(self, cwd: str, limit: int = 50) -> t.List[HistoryEntry]:
        """Get entries that were run in a specific directory."""
        conn = self.connect()
        rows = conn.execute(
            "SELECT * FROM history WHERE cwd = ? ORDER BY timestamp DESC LIMIT ?",
            (cwd, limit)
        ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def get_by_date(self, date: str, limit: int = 100) -> t.List[HistoryEntry]:
        """Get entries for a specific date (YYYY-MM-DD)."""
        conn = self.connect()
        start = datetime.datetime.strptime(date, "%Y-%m-%d").timestamp()
        end = start + 86400
        rows = conn.execute(
            "SELECT * FROM history WHERE timestamp >= ? AND timestamp < ? ORDER BY timestamp ASC LIMIT ?",
            (start, end, limit)
        ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def get_frequent(self, limit: int = 20) -> t.List[t.Tuple[str, int]]:
        """Get most frequently used commands."""
        conn = self.connect()
        rows = conn.execute(
            "SELECT command, COUNT(*) as cnt FROM history GROUP BY command ORDER BY cnt DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [(row["command"], row["cnt"]) for row in rows]

    def get_stats(self) -> dict:
        """Get history statistics."""
        conn = self.connect()
        stats = {}
        stats["total_entries"] = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        stats["unique_commands"] = conn.execute("SELECT COUNT(DISTINCT command) FROM history").fetchone()[0]
        stats["unique_dirs"] = conn.execute("SELECT COUNT(DISTINCT cwd) FROM history").fetchone()[0]
        stats["first_entry"] = conn.execute("SELECT MIN(timestamp) FROM history").fetchone()[0]
        stats["last_entry"] = conn.execute("SELECT MAX(timestamp) FROM history").fetchone()[0]
        stats["total_sessions"] = conn.execute("SELECT COUNT(DISTINCT session_id) FROM history").fetchone()[0]

        # Time range
        if stats["first_entry"]:
            first = datetime.datetime.fromtimestamp(stats["first_entry"])
            last = datetime.datetime.fromtimestamp(stats["last_entry"])
            stats["time_range_days"] = (last - first).days
        else:
            stats["time_range_days"] = 0

        return stats

    def delete_entry(self, entry_id: int) -> bool:
        """Delete a history entry by ID."""
        conn = self.connect()
        cursor = conn.execute("DELETE FROM history WHERE id = ?", (entry_id,))
        conn.commit()
        return cursor.rowcount > 0

    def delete_all(self) -> None:
        """Delete all history entries."""
        conn = self.connect()
        conn.execute("DELETE FROM history")
        conn.execute("DELETE FROM history_fts")
        conn.commit()

    def delete_by_session(self, session_id: str) -> int:
        """Delete all entries for a session."""
        conn = self.connect()
        cursor = conn.execute("DELETE FROM history WHERE session_id = ?", (session_id,))
        conn.commit()
        return cursor.rowcount

    def delete_older_than(self, days: int) -> int:
        """Delete entries older than specified days."""
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).timestamp()
        conn = self.connect()
        cursor = conn.execute("DELETE FROM history WHERE timestamp < ?", (cutoff,))
        conn.commit()
        return cursor.rowcount

    def delete_duplicates(self) -> int:
        """Delete duplicate consecutive commands."""
        conn = self.connect()
        deleted = conn.execute(
            """DELETE FROM history WHERE id IN (
                SELECT h1.id FROM history h1
                JOIN history h2 ON h1.command = h2.command
                AND h1.id > h2.id
                AND h1.id - h2.id = 1
            )"""
        ).rowcount
        conn.commit()
        return deleted

    def update_entry(self, entry_id: int, **kwargs: t.Any) -> bool:
        """Update fields of a history entry."""
        if not kwargs:
            return False
        sets = []
        values = []
        for key, value in kwargs.items():
            if key in self.__dataclass_fields__:
                sets.append(f"{key} = ?")
                values.append(value)
        if not sets:
            return False
        values.append(entry_id)
        conn = self.connect()
        cursor = conn.execute(
            f"UPDATE history SET {', '.join(sets)} WHERE id = ?",
            values
        )
        conn.commit()
        return cursor.rowcount > 0

    def annotate(self, entry_id: int, annotation: str) -> bool:
        """Add an annotation to a history entry."""
        return self.update_entry(entry_id, annotation=annotation)

    def add_tags(self, entry_id: int, tags: t.List[str]) -> bool:
        """Add tags to a history entry."""
        entry = self.get_by_id(entry_id)
        if not entry:
            return False
        existing_tags = set(entry.tags)
        existing_tags.update(tags)
        return self.update_entry(entry_id, tags=list(existing_tags))

    def import_file(self, path: str) -> int:
        """Import history from a file. Returns number of entries imported."""
        if not file_exists(path):
            return 0

        count = 0
        content = read_file(path)
        for line in content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            entry = HistoryEntry(
                command=line,
                cwd=os.getcwd(),
                timestamp=datetime.datetime.now().timestamp(),
            )
            self.add_entry(entry)
            count += 1
        return count

    def export_file(self, path: str, format: str = "txt") -> int:
        """Export history to a file. Returns number of entries exported."""
        entries = self.get_recent(limit=MAX_HISTORY_SIZE)
        if format == "json":
            data = [e.to_dict() for e in entries]
            write_file(path, json.dumps(data, indent=2, ensure_ascii=False))
        elif format == "csv":
            lines = ["id,command,cwd,timestamp,duration,exit_code,session_id"]
            for e in entries:
                cmd_escaped = e.command.replace('"', '""')
                lines.append(f'{e.id},"{cmd_escaped}","{e.cwd}",{e.timestamp},{e.duration},{e.exit_code},"{e.session_id}"')
            write_file(path, "\n".join(lines))
        else:
            # Plain text
            lines = []
            for e in entries:
                lines.append(f"# {e.formatted_time} [{e.duration_str}] exit={e.exit_code}")
                lines.append(e.command)
                lines.append("")
            write_file(path, "\n".join(lines))
        return len(entries)

    def _row_to_entry(self, row: sqlite3.Row) -> HistoryEntry:
        """Convert a database row to a HistoryEntry."""
        return HistoryEntry(
            id=row["id"],
            command=row["command"],
            cwd=row["cwd"],
            timestamp=row["timestamp"],
            duration=row["duration"],
            exit_code=row["exit_code"],
            session_id=row["session_id"],
            hostname=row["hostname"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            annotation=row["annotation"] or "",
        )

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __del__(self) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"HistoryDatabase({self.db_path})"


# ---------------------------------------------------------------------------
# History Manager
# ---------------------------------------------------------------------------

class HistoryManager:
    """High-level history management with session tracking and dedup."""

    def __init__(self, db_path: str = "", session_id: str = "") -> None:
        self.db = HistoryDatabase(db_path)
        self.session_id = session_id or datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        self._recent_cache: t.List[HistoryEntry] = []
        self._max_cache = RECENT_CACHE_SIZE
        self._hostname = os.uname().nodename if hasattr(os, 'uname') else os.environ.get('COMPUTERNAME', 'unknown')

    def add(self, command: str, cwd: str = "", duration: float = 0.0,
            exit_code: int = 0, tags: t.Optional[t.List[str]] = None,
            annotation: str = "") -> int:
        """Add a command to history."""
        entry = HistoryEntry(
            command=command,
            cwd=cwd or os.getcwd(),
            timestamp=datetime.datetime.now().timestamp(),
            duration=duration,
            exit_code=exit_code,
            session_id=self.session_id,
            hostname=self._hostname,
            tags=tags or [],
            annotation=annotation,
        )
        entry_id = self.db.add_entry(entry)
        entry.id = entry_id

        # Update cache
        self._recent_cache.append(entry)
        if len(self._recent_cache) > self._max_cache:
            self._recent_cache = self._recent_cache[-self._max_cache:]

        return entry_id

    def get(self, limit: int = 50, offset: int = 0) -> t.List[HistoryEntry]:
        """Get recent history entries."""
        return self.db.get_recent(limit=limit, offset=offset)

    def search(self, query: str, limit: int = 50) -> t.List[HistoryEntry]:
        """Search history."""
        return self.db.search(query, limit=limit)

    def search_interactive(self, query: str) -> t.Optional[HistoryEntry]:
        """Interactive reverse search (Ctrl+R)."""
        results = self.db.search(query, limit=20)
        if not results:
            return None
        return results[0]

    def get_last_command(self) -> str:
        """Get the last command from history."""
        entries = self.db.get_last(1)
        if entries:
            return entries[0].command
        return ""

    def get_last_n(self, n: int) -> t.List[str]:
        """Get the last N commands."""
        entries = self.db.get_last(n)
        return [e.command for e in entries]

    def expand_history(self, word: str) -> str:
        """Expand history references like !! and !$."""
        if word == "!!":
            return self.get_last_command()
        elif word == "!$":
            last = self.get_last_command()
            parts = last.split()
            return parts[-1] if parts else ""
        elif word == "!^":
            last = self.get_last_command()
            parts = last.split()
            return parts[1] if len(parts) > 1 else ""
        elif word == "!*":
            last = self.get_last_command()
            parts = last.split()
            return " ".join(parts[1:]) if len(parts) > 1 else ""
        elif word.startswith("!:"):
            # !:n - nth argument
            try:
                n = int(word[2:])
                last = self.get_last_command()
                parts = last.split()
                return parts[n] if 0 <= n < len(parts) else ""
            except (ValueError, IndexError):
                return word
        elif word.startswith("!-") and word[2:].isdigit():
            # !-n - nth from last
            try:
                n = int(word[2:])
                entries = self.db.get_last(n)
                if len(entries) >= n:
                    return entries[0].command
            except (ValueError, IndexError):
                pass
        elif word.startswith("!") and word[1:].isdigit():
            # !n - nth command
            try:
                n = int(word[1:])
                entry = self.db.get_by_id(n)
                if entry:
                    return entry.command
            except ValueError:
                pass
        elif word.startswith("!") and len(word) > 1:
            # !string - most recent command starting with string
            prefix = word[1:]
            results = self.db.search_prefix(prefix, limit=1)
            if results:
                return results[0].command

        return word

    def get_stats(self) -> dict:
        """Get history statistics."""
        return self.db.get_stats()

    def clear(self) -> None:
        """Clear all history."""
        self.db.delete_all()
        self._recent_cache.clear()

    def delete(self, entry_id: int) -> bool:
        """Delete a specific entry."""
        return self.db.delete_entry(entry_id)

    def import_from_file(self, path: str) -> int:
        """Import history from a file."""
        return self.db.import_file(path)

    def export_to_file(self, path: str, format: str = "txt") -> int:
        """Export history to a file."""
        return self.db.export_file(path, format)

    def get_frequent(self, limit: int = 20) -> t.List[t.Tuple[str, int]]:
        """Get most frequent commands."""
        return self.db.get_frequent(limit=limit)

    def get_session_commands(self) -> t.List[HistoryEntry]:
        """Get all commands for the current session."""
        return self.db.get_by_session(self.session_id)

    def close(self) -> None:
        """Close the history manager."""
        self.db.close()

    def __repr__(self) -> str:
        return f"HistoryManager(session={self.session_id})"


# ---------------------------------------------------------------------------
# Async history saving (for background writes)
# ---------------------------------------------------------------------------

class AsyncHistoryWriter:
    """Non-blocking history writer using a queue."""

    def __init__(self, db_path: str = "") -> None:
        self.db = HistoryDatabase(db_path)
        self._queue: t.List[HistoryEntry] = []
        self._batch_size = 10

    def write(self, entry: HistoryEntry) -> None:
        """Queue a history entry for writing."""
        self._queue.append(entry)
        if len(self._queue) >= self._batch_size:
            self.flush()

    def flush(self) -> None:
        """Write all queued entries."""
        while self._queue:
            entry = self._queue.pop(0)
            self.db.add_entry(entry)

    def close(self) -> None:
        """Flush and close."""
        self.flush()
        self.db.close()


# ---------------------------------------------------------------------------
# Module-level access
# ---------------------------------------------------------------------------

_history_manager: t.Optional[HistoryManager] = None


def get_history_manager() -> HistoryManager:
    """Get the global history manager singleton."""
    global _history_manager
    if _history_manager is None:
        config = get_config()
        db_path = config.history.file if config.history.file else ""
        _history_manager = HistoryManager(db_path=db_path)
    return _history_manager


__all__ = [
    "HistoryEntry",
    "HistoryDatabase",
    "HistoryManager",
    "AsyncHistoryWriter",
    "get_history_manager",
]