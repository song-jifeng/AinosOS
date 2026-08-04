"""Configuration management for AinosDB."""

from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DatabaseConfig:
    """Database configuration parameters.

    Attributes:
        data_dir: Root directory for database files.
        page_size: Size of each page in bytes (default 8192).
        buffer_pool_size: Number of pages in buffer pool (default 1000).
        wal_dir: Directory for write-ahead log files.
        checkpoint_interval: Number of WAL entries before checkpoint (default 1000).
        btree_order: Order of B+ tree (default 4).
        vector_dim: Default vector dimension.
        hnsw_m: HNSW M parameter (max connections per layer, default 16).
        hnsw_ef_construction: HNSW ef_construction parameter (default 200).
        hnsw_ef_search: HNSW ef_search parameter (default 50).
        ivf_nlist: IVF number of centroids (default 100).
        pq_m: Product Quantization number of sub-vectors (default 8).
        pq_k: Product Quantization number of centroids per sub-vector (default 256).
        server_host: TCP server host (default 'localhost').
        server_port: TCP server port (default 8899).
        max_connections: Maximum concurrent connections (default 50).
    """

    data_dir: str = "./data"
    page_size: int = 8192
    buffer_pool_size: int = 1000
    wal_dir: Optional[str] = None
    checkpoint_interval: int = 1000
    btree_order: int = 4

    # Vector defaults
    vector_dim: int = 128
    hnsw_m: int = 16
    hnsw_ef_construction: int = 200
    hnsw_ef_search: int = 50
    ivf_nlist: int = 100
    pq_m: int = 8
    pq_k: int = 256

    # Server defaults
    server_host: str = "localhost"
    server_port: int = 8899
    max_connections: int = 50

    def __post_init__(self) -> None:
        if self.wal_dir is None:
            self.wal_dir = os.path.join(self.data_dir, "wal")

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "DatabaseConfig":
        """Create config from dictionary, using defaults for missing keys."""
        valid_keys = set(cls.__dataclass_fields__.keys())
        filtered = {k: v for k, v in config_dict.items() if k in valid_keys}
        return cls(**filtered)

    @classmethod
    def from_json(cls, path: str) -> "DatabaseConfig":
        """Load configuration from a JSON file."""
        with open(path, "r") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        result = {}
        for field_name in self.__dataclass_fields__:
            result[field_name] = getattr(self, field_name)
        return result

    def to_json(self, path: str) -> None:
        """Save configuration to a JSON file."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    def ensure_dirs(self) -> None:
        """Create all required directories."""
        os.makedirs(self.data_dir, exist_ok=True)
        if self.wal_dir:
            os.makedirs(self.wal_dir, exist_ok=True)


class Config:
    """Global configuration manager."""

    _instance: Optional["Config"] = None
    _config: DatabaseConfig = DatabaseConfig()

    def __new__(cls) -> "Config":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get(cls) -> DatabaseConfig:
        """Get the current database configuration."""
        return cls._config

    @classmethod
    def set(cls, config: DatabaseConfig) -> None:
        """Set the database configuration."""
        cls._config = config
        cls._config.ensure_dirs()

    @classmethod
    def reset(cls) -> None:
        """Reset to default configuration."""
        cls._config = DatabaseConfig()