"""
SQLite storage backend for vector metadata.

SQLite is used for storing and querying vector metadata with full SQL support.
This allows complex filtering queries and efficient metadata management.
Vectors themselves are stored separately (in memory or mmap), but metadata
lives in SQLite for rich query capabilities.
"""

import sqlite3
import json
import threading
import time
import numpy as np
from typing import Any, Dict, List, Optional, Tuple, Union
from pathlib import Path
from collections import defaultdict


class SQLiteStorage:
    """SQLite-backed storage for vector metadata.

    Provides:
    - Metadata storage and retrieval
    - Rich filtering queries (tags, numerical ranges, etc.)
    - Batch operations
    - Thread-safe access
    """

    def __init__(self, db_path: str = ":memory:", dimension: int = 128):
        self.db_path = db_path
        self.dimension = dimension
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._cursor: Optional[sqlite3.Cursor] = None
        self._local = threading.local()
        self._connect()

    def _connect(self):
        """Create database connection."""
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
        self._conn.execute("PRAGMA temp_store=MEMORY")
        self._conn.execute("PRAGMA mmap_size=268435456")  # 256MB mmap
        self._cursor = self._conn.cursor()
        self._init_schema()

    def _init_schema(self):
        """Initialize database schema."""
        with self._lock:
            self._cursor.executescript("""
                CREATE TABLE IF NOT EXISTS vectors (
                    id INTEGER PRIMARY KEY,
                    dimension INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    is_deleted INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS metadata (
                    id INTEGER PRIMARY KEY,
                    vector_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT,
                    value_type TEXT DEFAULT 'string',
                    FOREIGN KEY (vector_id) REFERENCES vectors(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS vector_tags (
                    vector_id INTEGER NOT NULL,
                    tag TEXT NOT NULL,
                    PRIMARY KEY (vector_id, tag),
                    FOREIGN KEY (vector_id) REFERENCES vectors(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS collections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    dimension INTEGER NOT NULL,
                    vector_count INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_metadata_key ON metadata(key);
                CREATE INDEX IF NOT EXISTS idx_metadata_vector ON metadata(vector_id);
                CREATE INDEX IF NOT EXISTS idx_metadata_value ON metadata(value);
                CREATE INDEX IF NOT EXISTS idx_tags_tag ON vector_tags(tag);
                CREATE INDEX IF NOT EXISTS idx_vectors_deleted ON vectors(is_deleted);
            """)
            self._conn.commit()

    def _ensure_connection(self):
        """Ensure the connection is still alive."""
        try:
            self._cursor.execute("SELECT 1")
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            self._connect()

    def insert_metadata(self, vector_id: int, metadata: Dict[str, Any]) -> bool:
        """Insert metadata for a vector.

        Args:
            vector_id: The vector ID
            metadata: Dictionary of metadata key-value pairs

        Returns:
            True if successful.
        """
        with self._lock:
            try:
                now = time.time()
                # Ensure vector exists
                self._cursor.execute(
                    "INSERT OR IGNORE INTO vectors (id, dimension, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (vector_id, self.dimension, now, now)
                )

                # Insert metadata entries
                for key, value in metadata.items():
                    value_type = self._infer_type(value)
                    serialized = self._serialize_value(value)
                    self._cursor.execute(
                        "INSERT OR REPLACE INTO metadata (vector_id, key, value, value_type) "
                        "VALUES (?, ?, ?, ?)",
                        (vector_id, key, serialized, value_type)
                    )

                # Handle tags specially
                tags = metadata.get('tags', [])
                if isinstance(tags, list):
                    for tag in tags:
                        self._cursor.execute(
                            "INSERT OR IGNORE INTO vector_tags (vector_id, tag) VALUES (?, ?)",
                            (vector_id, str(tag))
                        )

                self._conn.commit()
                return True
            except sqlite3.Error as e:
                self._conn.rollback()
                raise RuntimeError(f"Failed to insert metadata: {e}")

    def insert_metadata_batch(self, ids: List[int],
                               metadata_list: List[Optional[Dict[str, Any]]]) -> int:
        """Insert metadata for multiple vectors.

        Args:
            ids: List of vector IDs
            metadata_list: List of metadata dictionaries

        Returns:
            Number of successful insertions.
        """
        with self._lock:
            count = 0
            try:
                now = time.time()
                for i, (vid, meta) in enumerate(zip(ids, metadata_list)):
                    if meta is None:
                        continue

                    # Ensure vector exists
                    self._cursor.execute(
                        "INSERT OR IGNORE INTO vectors (id, dimension, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?)",
                        (int(vid), self.dimension, now, now)
                    )

                    # Insert metadata
                    for key, value in meta.items():
                        value_type = self._infer_type(value)
                        serialized = self._serialize_value(value)
                        self._cursor.execute(
                            "INSERT OR REPLACE INTO metadata (vector_id, key, value, value_type) "
                            "VALUES (?, ?, ?, ?)",
                            (int(vid), key, serialized, value_type)
                        )

                    # Handle tags
                    tags = meta.get('tags', [])
                    if isinstance(tags, list):
                        for tag in tags:
                            self._cursor.execute(
                                "INSERT OR IGNORE INTO vector_tags (vector_id, tag) VALUES (?, ?)",
                                (int(vid), str(tag))
                            )

                    count += 1

                self._conn.commit()
                return count
            except sqlite3.Error as e:
                self._conn.rollback()
                raise RuntimeError(f"Failed to insert metadata batch: {e}")

    def get_metadata(self, vector_id: int) -> Optional[Dict[str, Any]]:
        """Get metadata for a vector.

        Args:
            vector_id: The vector ID

        Returns:
            Metadata dictionary or None if not found.
        """
        with self._lock:
            self._cursor.execute(
                "SELECT key, value, value_type FROM metadata WHERE vector_id = ?",
                (vector_id,)
            )
            rows = self._cursor.fetchall()
            if not rows:
                return None

            metadata = {}
            for row in rows:
                metadata[row['key']] = self._deserialize_value(
                    row['value'], row['value_type']
                )
            return metadata

    def get_metadata_batch(self, ids: List[int]) -> List[Optional[Dict[str, Any]]]:
        """Get metadata for multiple vectors.

        Args:
            ids: List of vector IDs

        Returns:
            List of metadata dictionaries.
        """
        with self._lock:
            placeholders = ','.join('?' * len(ids))
            self._cursor.execute(
                f"SELECT vector_id, key, value, value_type FROM metadata "
                f"WHERE vector_id IN ({placeholders})",
                ids
            )
            rows = self._cursor.fetchall()

            # Group by vector_id
            grouped = defaultdict(dict)
            for row in rows:
                grouped[row['vector_id']][row['key']] = self._deserialize_value(
                    row['value'], row['value_type']
                )

            return [grouped.get(vid) for vid in ids]

    def delete_metadata(self, vector_id: int) -> bool:
        """Delete metadata for a vector.

        Args:
            vector_id: The vector ID

        Returns:
            True if successful.
        """
        with self._lock:
            self._cursor.execute("DELETE FROM metadata WHERE vector_id = ?", (vector_id,))
            self._cursor.execute("DELETE FROM vector_tags WHERE vector_id = ?", (vector_id,))
            self._cursor.execute("UPDATE vectors SET is_deleted = 1, updated_at = ? WHERE id = ?",
                               (time.time(), vector_id))
            self._conn.commit()
            return True

    def delete_metadata_batch(self, ids: List[int]) -> int:
        """Delete metadata for multiple vectors.

        Args:
            ids: List of vector IDs

        Returns:
            Number of deleted entries.
        """
        with self._lock:
            placeholders = ','.join('?' * len(ids))
            now = time.time()
            self._cursor.execute(
                f"DELETE FROM metadata WHERE vector_id IN ({placeholders})", ids
            )
            deleted_count = self._cursor.rowcount
            self._cursor.execute(
                f"DELETE FROM vector_tags WHERE vector_id IN ({placeholders})", ids
            )
            self._cursor.execute(
                f"UPDATE vectors SET is_deleted = 1, updated_at = ? WHERE id IN ({placeholders})",
                (now, *ids)
            )
            self._conn.commit()
            return deleted_count

    def filter_by_metadata(self, filters: Dict[str, Any]) -> List[int]:
        """Query vector IDs by metadata filters.

        Args:
            filters: Dictionary of key -> value pairs to filter by.
                    Supports special operators:
                    - "key__gt": value (greater than)
                    - "key__gte": value (greater than or equal)
                    - "key__lt": value (less than)
                    - "key__lte": value (less than or equal)
                    - "key__in": [values] (in list)
                    - "key__contains": string (substring match)

        Returns:
            List of matching vector IDs.
        """
        with self._lock:
            conditions = []
            params = []

            for key, value in filters.items():
                if '__' in key:
                    actual_key, op = key.rsplit('__', 1)
                else:
                    actual_key = key
                    op = 'eq'

                if op == 'eq':
                    conditions.append(
                        "(key = ? AND value = ?)"
                    )
                    params.extend([actual_key, self._serialize_value(value)])
                elif op == 'gt':
                    conditions.append(
                        "(key = ? AND CAST(value AS REAL) > ?)"
                    )
                    params.extend([actual_key, float(value)])
                elif op == 'gte':
                    conditions.append(
                        "(key = ? AND CAST(value AS REAL) >= ?)"
                    )
                    params.extend([actual_key, float(value)])
                elif op == 'lt':
                    conditions.append(
                        "(key = ? AND CAST(value AS REAL) < ?)"
                    )
                    params.extend([actual_key, float(value)])
                elif op == 'lte':
                    conditions.append(
                        "(key = ? AND CAST(value AS REAL) <= ?)"
                    )
                    params.extend([actual_key, float(value)])
                elif op == 'in':
                    placeholders = ','.join('?' * len(value))
                    conditions.append(
                        f"(key = ? AND value IN ({placeholders}))"
                    )
                    params.extend([actual_key] + [self._serialize_value(v) for v in value])
                elif op == 'contains':
                    conditions.append(
                        "(key = ? AND value LIKE ?)"
                    )
                    params.extend([actual_key, f'%{self._serialize_value(value)}%'])
                elif op == 'ne':
                    conditions.append(
                        "(key = ? AND value != ?)"
                    )
                    params.extend([actual_key, self._serialize_value(value)])

            if not conditions:
                return []

            where_clause = ' OR '.join(conditions)
            query = f"""
                SELECT DISTINCT vector_id FROM metadata
                WHERE {where_clause}
                AND vector_id NOT IN (SELECT id FROM vectors WHERE is_deleted = 1)
            """

            self._cursor.execute(query, params)
            return [row['vector_id'] for row in self._cursor.fetchall()]

    def filter_by_tags(self, tags: List[str], match_all: bool = False) -> List[int]:
        """Query vector IDs by tags.

        Args:
            tags: List of tags to filter by
            match_all: If True, vector must have ALL tags. If False, any tag.

        Returns:
            List of matching vector IDs.
        """
        with self._lock:
            if not tags:
                return []

            if match_all:
                placeholders = ','.join('?' * len(tags))
                query = f"""
                    SELECT vector_id FROM vector_tags
                    WHERE tag IN ({placeholders})
                    AND vector_id NOT IN (SELECT id FROM vectors WHERE is_deleted = 1)
                    GROUP BY vector_id
                    HAVING COUNT(DISTINCT tag) = ?
                """
                self._cursor.execute(query, tags + [len(tags)])
            else:
                placeholders = ','.join('?' * len(tags))
                query = f"""
                    SELECT DISTINCT vector_id FROM vector_tags
                    WHERE tag IN ({placeholders})
                    AND vector_id NOT IN (SELECT id FROM vectors WHERE is_deleted = 1)
                """
                self._cursor.execute(query, tags)

            return [row['vector_id'] for row in self._cursor.fetchall()]

    def get_vector_count(self) -> int:
        """Get the total number of (non-deleted) vectors.

        Returns:
            Vector count.
        """
        with self._lock:
            self._cursor.execute(
                "SELECT COUNT(*) as cnt FROM vectors WHERE is_deleted = 0"
            )
            return self._cursor.fetchone()['cnt']

    def get_all_tags(self) -> List[str]:
        """Get all unique tags.

        Returns:
            List of tag strings.
        """
        with self._lock:
            self._cursor.execute("SELECT DISTINCT tag FROM vector_tags")
            return [row['tag'] for row in self._cursor.fetchall()]

    def get_tag_counts(self) -> Dict[str, int]:
        """Get tag usage counts.

        Returns:
            Dictionary of tag -> count.
        """
        with self._lock:
            self._cursor.execute("""
                SELECT tag, COUNT(*) as cnt FROM vector_tags
                GROUP BY tag ORDER BY cnt DESC
            """)
            return {row['tag']: row['cnt'] for row in self._cursor.fetchall()}

    def clear(self):
        """Clear all data."""
        with self._lock:
            self._cursor.executescript("""
                DELETE FROM metadata;
                DELETE FROM vector_tags;
                DELETE FROM vectors;
            """)
            self._conn.commit()

    def compact(self):
        """Compact the database to reclaim space."""
        with self._lock:
            self._cursor.execute("VACUUM")
            self._conn.commit()

    def close(self):
        """Close the database connection."""
        with self._lock:
            if self._conn:
                self._conn.commit()
                self._conn.close()
                self._conn = None
                self._cursor = None

    def _infer_type(self, value: Any) -> str:
        """Infer the type of a metadata value."""
        if isinstance(value, bool):
            return 'bool'
        elif isinstance(value, int):
            return 'int'
        elif isinstance(value, float):
            return 'float'
        elif isinstance(value, str):
            return 'string'
        elif isinstance(value, list):
            return 'json_array'
        elif isinstance(value, dict):
            return 'json_object'
        elif value is None:
            return 'null'
        else:
            return 'string'

    def _serialize_value(self, value: Any) -> str:
        """Serialize a metadata value to string."""
        if value is None:
            return ''
        if isinstance(value, (bool, int, float)):
            return str(value)
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False, default=str)
        return str(value)

    def _deserialize_value(self, value: str, value_type: str) -> Any:
        """Deserialize a metadata value from string."""
        if value_type == 'null':
            return None
        elif value_type == 'bool':
            return value.lower() == 'true'
        elif value_type == 'int':
            return int(value)
        elif value_type == 'float':
            return float(value)
        elif value_type in ('json_array', 'json_object'):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        else:
            return value

    def __del__(self):
        """Cleanup on deletion."""
        try:
            self.close()
        except Exception:
            pass