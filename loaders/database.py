"""
Database Loader
===============

Loads translations from a database backend.

Supports multiple database backends through a configurable connection
interface.  The default schema uses a ``translations`` table with columns
for locale, key, value, domain, and context.

This loader is designed for dynamic translation management where
translations are stored in a database and can be updated at runtime.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from ainos_i18n.loaders.base import Loader, LoaderError

logger = logging.getLogger(__name__)


class DatabaseConnection(Protocol):
    """Protocol for database connections used by DatabaseLoader.

    Implementations must provide a ``fetch_translations(locale)`` method
    that returns a list of translation records.
    """

    def fetch_translations(self, locale: str) -> list[dict[str, Any]]:
        """Fetch all translation records for a given locale.

        Parameters
        ----------
        locale : str
            Locale code.

        Returns
        -------
        list[dict[str, Any]]
            Each dict should have keys: ``key``, ``value``, optionally
            ``domain`` and ``context``.
        """
        ...


class SQLiteConnection:
    """SQLite database connection for translations.

    Parameters
    ----------
    db_path : str
        Path to SQLite database file.
    table_name : str, optional
        Table name. Defaults to ``"translations"``.
    """

    def __init__(self, db_path: str, table_name: str = "translations") -> None:
        self._db_path = db_path
        self._table_name = table_name

    def fetch_translations(self, locale: str) -> list[dict[str, Any]]:
        """Fetch translations from SQLite.

        Parameters
        ----------
        locale : str
            Locale code.

        Returns
        -------
        list[dict[str, Any]]
        """
        import sqlite3
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Create table if not exists
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {self._table_name} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    locale TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    domain TEXT DEFAULT 'messages',
                    context TEXT DEFAULT '',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(locale, key, domain, context)
                )
            """)
            conn.commit()

            cursor.execute(
                f"SELECT key, value, domain, context FROM {self._table_name} WHERE locale = ?",
                (locale,),
            )
            rows = cursor.fetchall()
            conn.close()

            return [{"key": row["key"], "value": row["value"],
                      "domain": row["domain"], "context": row["context"]}
                    for row in rows]
        except Exception as exc:
            logger.error("SQLite error fetching translations for %s: %s", locale, exc)
            return []


class DatabaseLoader(Loader):
    """Load translations from a database backend.

    Parameters
    ----------
    connection : DatabaseConnection
        A database connection object that implements ``fetch_translations()``.
    cache_enabled : bool, optional
        Whether to cache loaded translations. Defaults to True.
    namespace_separator : str, optional
        Separator for nested key namespaces. Defaults to ``"."``.
    """

    def __init__(
        self,
        connection: DatabaseConnection,
        cache_enabled: bool = True,
        namespace_separator: str = ".",
    ) -> None:
        super().__init__(source_dir=None)
        self._connection = connection
        self._cache_enabled = cache_enabled
        self._namespace_separator = namespace_separator
        self._cache: dict[str, dict[str, Any]] = {}

    # ---- Loader API ----

    def load(self, locale: str) -> dict[str, Any]:
        """Load translations for a locale from the database.

        Parameters
        ----------
        locale : str
            Locale code.

        Returns
        -------
        dict[str, Any]
            Nested dictionary of translations.
        """
        if self._cache_enabled and locale in self._cache:
            logger.debug("Cache hit for locale: %s", locale)
            return dict(self._cache[locale])

        try:
            records = self._connection.fetch_translations(locale)
        except Exception as exc:
            logger.error("Database error loading translations for %s: %s", locale, exc)
            return {}

        if not records:
            logger.warning("No translations found in database for locale: %s", locale)
            return {}

        # Build nested dictionary from flat records
        result: dict[str, Any] = {}
        for record in records:
            key = record.get("key", "")
            value = record.get("value", "")
            if not key:
                continue

            self._set_nested_value(result, key, value)

        if self._cache_enabled:
            self._cache[locale] = dict(result)

        logger.info("Loaded %d translations for locale '%s' from database", len(records), locale)
        return result

    def get_available_locales(self) -> list[str]:
        """Get list of locales available in the database.

        Returns
        -------
        list[str]
        """
        try:
            records = self._connection.fetch_translations("")
            locales: set[str] = set()
            for record in records:
                loc = record.get("locale", "")
                if loc:
                    locales.add(loc)
            return sorted(locales)
        except Exception:
            return []

    # ---- Cache management ----

    def clear_cache(self) -> None:
        """Clear the internal cache."""
        self._cache.clear()
        logger.debug("DatabaseLoader cache cleared")

    def set_cache_enabled(self, enabled: bool) -> None:
        """Enable or disable caching.

        Parameters
        ----------
        enabled : bool
        """
        self._cache_enabled = enabled
        if not enabled:
            self._cache.clear()

    # ---- Database update helpers ----

    def update_translation(
        self,
        locale: str,
        key: str,
        value: str,
        domain: str = "messages",
        context: str = "",
    ) -> bool:
        """Update or insert a single translation in the database.

        Parameters
        ----------
        locale : str
            Locale code.
        key : str
            Translation key.
        value : str
            Translation value.
        domain : str, optional
            Translation domain.
        context : str, optional
            Translation context.

        Returns
        -------
        bool
            True if successful.
        """
        try:
            # Try to use the connection's upsert method if available
            if hasattr(self._connection, "upsert_translation"):
                self._connection.upsert_translation(locale, key, value, domain, context)
            else:
                # Generic SQL approach via SQLite connection
                import sqlite3
                if isinstance(self._connection, SQLiteConnection):
                    conn = sqlite3.connect(self._connection._db_path)
                    cursor = conn.cursor()
                    cursor.execute(f"""
                        INSERT OR REPLACE INTO {self._connection._table_name}
                        (locale, key, value, domain, context, updated_at)
                        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (locale, key, value, domain, context))
                    conn.commit()
                    conn.close()

            # Invalidate cache
            self._cache.pop(locale, None)
            return True
        except Exception as exc:
            logger.error("Failed to update translation %s/%s: %s", locale, key, exc)
            return False

    def delete_translation(self, locale: str, key: str, domain: str = "messages") -> bool:
        """Delete a translation from the database.

        Parameters
        ----------
        locale : str
            Locale code.
        key : str
            Translation key.
        domain : str, optional
            Translation domain.

        Returns
        -------
        bool
        """
        try:
            if hasattr(self._connection, "delete_translation"):
                self._connection.delete_translation(locale, key, domain)
            elif isinstance(self._connection, SQLiteConnection):
                import sqlite3
                conn = sqlite3.connect(self._connection._db_path)
                cursor = conn.cursor()
                cursor.execute(
                    f"DELETE FROM {self._connection._table_name} "
                    "WHERE locale = ? AND key = ? AND domain = ?",
                    (locale, key, domain),
                )
                conn.commit()
                conn.close()

            self._cache.pop(locale, None)
            return True
        except Exception as exc:
            logger.error("Failed to delete translation %s/%s: %s", locale, key, exc)
            return False

    # ---- Internal helpers ----

    def _set_nested_value(self, data: dict[str, Any], key: str, value: str) -> None:
        """Set a value in a nested dictionary using dot notation.

        Parameters
        ----------
        data : dict
            The dictionary to modify.
        key : str
            Dot-separated key path.
        value : str
            The value to set.
        """
        parts = key.split(self._namespace_separator)
        current = data
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                current[part] = value
            else:
                if part not in current:
                    current[part] = {}
                elif not isinstance(current[part], dict):
                    current[part] = {}
                current = current[part]

    def __repr__(self) -> str:
        conn_type = type(self._connection).__name__
        return (
            f"DatabaseLoader(connection={conn_type}, "
            f"cache_enabled={self._cache_enabled})"
        )