"""System catalog for AinosDB.

Manages metadata about databases, tables, columns, indexes, and
other schema objects. The catalog is stored in system tables.
"""

from __future__ import annotations

import os
import json
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from .types import DataType, parse_type_string


@dataclass
class ColumnInfo:
    """Metadata for a table column.

    Attributes:
        name: Column name.
        data_type: Data type of the column.
        nullable: Whether NULL values are allowed.
        default: Default value for the column.
        primary_key: Whether this column is part of the primary key.
        unique: Whether values must be unique.
        indexed: Whether an index exists on this column.
    """

    name: str
    data_type: DataType
    nullable: bool = True
    default: Optional[Any] = None
    primary_key: bool = False
    unique: bool = False
    indexed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.data_type.name,
            "nullable": self.nullable,
            "default": self.default,
            "primary_key": self.primary_key,
            "unique": self.unique,
            "indexed": self.indexed,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ColumnInfo":
        return cls(
            name=data["name"],
            data_type=parse_type_string(data["type"]),
            nullable=data.get("nullable", True),
            default=data.get("default"),
            primary_key=data.get("primary_key", False),
            unique=data.get("unique", False),
            indexed=data.get("indexed", False),
        )


@dataclass
class TableInfo:
    """Metadata for a database table.

    Attributes:
        name: Table name.
        columns: List of column definitions.
        primary_key: Column name(s) for the primary key.
        row_count: Approximate number of rows.
        storage_path: Path to table data file.
        table_id: Unique table identifier.
    """

    name: str
    columns: List[ColumnInfo] = field(default_factory=list)
    primary_key: Optional[str] = None
    row_count: int = 0
    storage_path: Optional[str] = None
    table_id: int = 0
    _column_map: Dict[str, ColumnInfo] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._column_map = {col.name.upper(): col for col in self.columns}

    def get_column(self, name: str) -> Optional[ColumnInfo]:
        """Get column info by name (case-insensitive).

        Args:
            name: Column name.

        Returns:
            ColumnInfo if found, None otherwise.
        """
        return self._column_map.get(name.upper())

    def has_column(self, name: str) -> bool:
        """Check if a column exists (case-insensitive)."""
        return name.upper() in self._column_map

    def column_index(self, name: str) -> int:
        """Get the index of a column by name.

        Args:
            name: Column name.

        Returns:
            Column index.

        Raises:
            ValueError: If column not found.
        """
        for i, col in enumerate(self.columns):
            if col.name.upper() == name.upper():
                return i
        raise ValueError(f"Column '{name}' not found in table '{self.name}'")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "columns": [c.to_dict() for c in self.columns],
            "primary_key": self.primary_key,
            "row_count": self.row_count,
            "table_id": self.table_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TableInfo":
        return cls(
            name=data["name"],
            columns=[ColumnInfo.from_dict(c) for c in data.get("columns", [])],
            primary_key=data.get("primary_key"),
            row_count=data.get("row_count", 0),
            table_id=data.get("table_id", 0),
        )


@dataclass
class DatabaseInfo:
    """Metadata for a database.

    Attributes:
        name: Database name.
        tables: Dictionary of table name -> TableInfo.
        path: Path to database directory.
    """

    name: str
    tables: Dict[str, TableInfo] = field(default_factory=dict)
    path: Optional[str] = None

    def get_table(self, name: str) -> Optional[TableInfo]:
        """Get table info by name (case-insensitive).

        Args:
            name: Table name.

        Returns:
            TableInfo if found, None otherwise.
        """
        for table_name, info in self.tables.items():
            if table_name.upper() == name.upper():
                return info
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "tables": {name: info.to_dict() for name, info in self.tables.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DatabaseInfo":
        return cls(
            name=data["name"],
            tables={name: TableInfo.from_dict(t) for name, t in data.get("tables", {}).items()},
        )


class Catalog:
    """System catalog for managing database metadata.

    The catalog is persisted to disk as JSON files and cached in memory.
    It provides thread-safe access to schema information.

    Attributes:
        databases: Dictionary of database name -> DatabaseInfo.
        current_db: Name of the currently active database.
        catalog_path: Path to catalog file.
    """

    CATALOG_FILE = "catalog.json"

    def __init__(self, data_dir: str = "./data") -> None:
        self._databases: Dict[str, DatabaseInfo] = {}
        self.current_db: Optional[str] = None
        self.catalog_path = os.path.join(data_dir, self.CATALOG_FILE)
        self._lock = threading.RLock()
        self._next_table_id = 1

        os.makedirs(data_dir, exist_ok=True)
        self._load()

    def _load(self) -> None:
        """Load catalog from disk."""
        if os.path.exists(self.catalog_path):
            try:
                with open(self.catalog_path, "r") as f:
                    data = json.load(f)
                for db_data in data.get("databases", []):
                    db_info = DatabaseInfo.from_dict(db_data)
                    self._databases[db_info.name.upper()] = db_info
                self._next_table_id = data.get("next_table_id", 1)
            except (json.JSONDecodeError, KeyError) as e:
                # Corrupted catalog, start fresh
                pass

    def _save(self) -> None:
        """Save catalog to disk."""
        data = {
            "databases": [db.to_dict() for db in self._databases.values()],
            "next_table_id": self._next_table_id,
        }
        os.makedirs(os.path.dirname(self.catalog_path), exist_ok=True)
        with open(self.catalog_path, "w") as f:
            json.dump(data, f, indent=2)

    def create_database(self, name: str) -> DatabaseInfo:
        """Create a new database.

        Args:
            name: Database name.

        Returns:
            New DatabaseInfo.

        Raises:
            ValueError: If database already exists.
        """
        with self._lock:
            key = name.upper()
            if key in self._databases:
                raise ValueError(f"Database '{name}' already exists")

            db_info = DatabaseInfo(name=name)
            self._databases[key] = db_info
            self._save()
            return db_info

    def drop_database(self, name: str) -> None:
        """Drop a database.

        Args:
            name: Database name.

        Raises:
            ValueError: If database does not exist.
        """
        with self._lock:
            key = name.upper()
            if key not in self._databases:
                raise ValueError(f"Database '{name}' does not exist")

            del self._databases[key]
            if self.current_db and self.current_db.upper() == key:
                self.current_db = None
            self._save()

    def get_database(self, name: str) -> Optional[DatabaseInfo]:
        """Get database info by name.

        Args:
            name: Database name.

        Returns:
            DatabaseInfo if found, None otherwise.
        """
        return self._databases.get(name.upper())

    def list_databases(self) -> List[str]:
        """List all database names.

        Returns:
            List of database names.
        """
        return [db.name for db in self._databases.values()]

    def use_database(self, name: str) -> None:
        """Set the current database.

        Args:
            name: Database name.

        Raises:
            ValueError: If database does not exist.
        """
        key = name.upper()
        if key not in self._databases:
            raise ValueError(f"Database '{name}' does not exist")
        self.current_db = name

    def get_current_db(self) -> Optional[DatabaseInfo]:
        """Get the current database info.

        Returns:
            Current DatabaseInfo, or None if no database selected.
        """
        if self.current_db is None:
            return None
        return self._databases.get(self.current_db.upper())

    def create_table(
        self,
        table_name: str,
        columns: List[ColumnInfo],
        primary_key: Optional[str] = None,
    ) -> TableInfo:
        """Create a new table in the current database.

        Args:
            table_name: Table name.
            columns: List of column definitions.
            primary_key: Optional primary key column name.

        Returns:
            New TableInfo.

        Raises:
            ValueError: If no database selected or table already exists.
        """
        with self._lock:
            db = self.get_current_db()
            if db is None:
                raise ValueError("No database selected")

            table_key = table_name.upper()
            if table_key in db.tables:
                raise ValueError(f"Table '{table_name}' already exists")

            table_info = TableInfo(
                name=table_name,
                columns=columns,
                primary_key=primary_key,
                table_id=self._next_table_id,
            )
            self._next_table_id += 1
            db.tables[table_key] = table_info
            self._save()
            return table_info

    def drop_table(self, table_name: str) -> None:
        """Drop a table from the current database.

        Args:
            table_name: Table name.

        Raises:
            ValueError: If no database selected or table not found.
        """
        with self._lock:
            db = self.get_current_db()
            if db is None:
                raise ValueError("No database selected")

            table_key = table_name.upper()
            if table_key not in db.tables:
                raise ValueError(f"Table '{table_name}' does not exist")

            del db.tables[table_key]
            self._save()

    def get_table(self, table_name: str) -> Optional[TableInfo]:
        """Get table info from the current database.

        Args:
            table_name: Table name.

        Returns:
            TableInfo if found, None otherwise.
        """
        db = self.get_current_db()
        if db is None:
            return None
        return db.get_table(table_name)

    def list_tables(self) -> List[str]:
        """List all tables in the current database.

        Returns:
            List of table names.
        """
        db = self.get_current_db()
        if db is None:
            return []
        return [info.name for info in db.tables.values()]

    def add_column(self, table_name: str, column: ColumnInfo) -> None:
        """Add a column to an existing table.

        Args:
            table_name: Table name.
            column: Column definition.

        Raises:
            ValueError: If table not found or column already exists.
        """
        with self._lock:
            table = self.get_table(table_name)
            if table is None:
                raise ValueError(f"Table '{table_name}' does not exist")

            if table.has_column(column.name):
                raise ValueError(f"Column '{column.name}' already exists")

            table.columns.append(column)
            table._column_map[column.name.upper()] = column
            self._save()

    def drop_column(self, table_name: str, column_name: str) -> None:
        """Remove a column from a table.

        Args:
            table_name: Table name.
            column_name: Column name.

        Raises:
            ValueError: If table or column not found.
        """
        with self._lock:
            table = self.get_table(table_name)
            if table is None:
                raise ValueError(f"Table '{table_name}' does not exist")

            col = table.get_column(column_name)
            if col is None:
                raise ValueError(f"Column '{column_name}' does not exist")

            table.columns.remove(col)
            table._column_map.pop(column_name.upper(), None)
            self._save()

    def update_row_count(self, table_name: str, delta: int = 1) -> None:
        """Update the approximate row count for a table.

        Args:
            table_name: Table name.
            delta: Change in row count (positive or negative).
        """
        with self._lock:
            table = self.get_table(table_name)
            if table is not None:
                table.row_count = max(0, table.row_count + delta)

    def get_table_id(self, table_name: str) -> int:
        """Get the unique ID for a table.

        Args:
            table_name: Table name.

        Returns:
            Table ID.

        Raises:
            ValueError: If table not found.
        """
        table = self.get_table(table_name)
        if table is None:
            raise ValueError(f"Table '{table_name}' not found")
        return table.table_id

    def close(self) -> None:
        """Save and close the catalog."""
        self._save()

    def __repr__(self) -> str:
        return (
            f"Catalog(databases={len(self._databases)}, "
            f"current_db={self.current_db})"
        )