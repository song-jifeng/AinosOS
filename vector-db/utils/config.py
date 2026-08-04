"""
Configuration management for the vector database.
"""

import os
import json
from typing import Any, Dict, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum


class IndexType(str, Enum):
    """Supported index types."""
    FLAT = "flat"
    HNSW = "hnsw"
    IVF = "ivf"
    PQ = "pq"
    LSH = "lsh"
    HYBRID = "hybrid"


class StorageType(str, Enum):
    """Supported storage backends."""
    MEMORY = "memory"
    DISK = "disk"
    SQLITE = "sqlite"


class MetricType(str, Enum):
    """Supported distance metrics."""
    COSINE = "cosine"
    EUCLIDEAN = "euclidean"
    DOT = "dot"
    MANHATTAN = "manhattan"


@dataclass
class IndexConfig:
    """Configuration for an index."""
    name: str
    dimension: int
    index_type: IndexType = IndexType.FLAT
    metric: MetricType = MetricType.COSINE

    # HNSW specific
    M: int = 16
    ef_construction: int = 200
    ef_search: int = 50
    max_level: int = 16
    level_multiplier: float = 1.0 / 0.3

    # IVF specific
    nlist: int = 100
    nprobe: int = 10

    # PQ specific
    m_subquantizers: int = 8
    nbits: int = 8

    # LSH specific
    nbits_lsh: int = 128
    num_tables: int = 10

    # Hybrid specific
    hybrid_weights: Optional[Dict[str, float]] = None

    # Storage
    storage_type: StorageType = StorageType.MEMORY
    persist_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        result = asdict(self)
        result['index_type'] = self.index_type.value
        result['metric'] = self.metric.value
        result['storage_type'] = self.storage_type.value
        if self.hybrid_weights is not None:
            result['hybrid_weights'] = self.hybrid_weights
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IndexConfig':
        """Create config from dictionary."""
        data = data.copy()
        data['index_type'] = IndexType(data['index_type'])
        data['metric'] = MetricType(data['metric'])
        data['storage_type'] = StorageType(data['storage_type'])
        return cls(**data)


@dataclass
class ServerConfig:
    """Configuration for the TCP server."""
    host: str = "0.0.0.0"
    port: int = 9600
    max_workers: int = 4
    max_packet_size: int = 10 * 1024 * 1024  # 10MB
    recv_timeout: float = 30.0
    send_timeout: float = 30.0
    socket_buffer_size: int = 65536

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ServerConfig':
        return cls(**data)


@dataclass
class DatabaseConfig:
    """Global database configuration."""
    default_index_type: IndexType = IndexType.FLAT
    default_metric: MetricType = MetricType.COSINE
    default_dimension: int = 128
    auto_persist: bool = False
    persist_interval: int = 300  # seconds
    enable_metrics: bool = True
    max_collections: int = 1000
    max_vectors_per_collection: int = 10_000_000
    vector_precision: str = "float32"  # float32 or float64

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['default_index_type'] = self.default_index_type.value
        result['default_metric'] = self.default_metric.value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DatabaseConfig':
        data = data.copy()
        data['default_index_type'] = IndexType(data['default_index_type'])
        data['default_metric'] = MetricType(data['default_metric'])
        return cls(**data)


class ConfigManager:
    """Manages configuration loading and saving."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config.json"
        )
        self.database_config = DatabaseConfig()
        self.server_config = ServerConfig()
        self._loaded = False

    def load(self, config_path: Optional[str] = None) -> bool:
        """Load configuration from file."""
        path = config_path or self.config_path
        if not os.path.exists(path):
            return False

        try:
            with open(path, 'r') as f:
                data = json.load(f)

            if 'database' in data:
                self.database_config = DatabaseConfig.from_dict(data['database'])
            if 'server' in data:
                self.server_config = ServerConfig.from_dict(data['server'])

            self._loaded = True
            return True
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"Warning: Failed to load config from {path}: {e}")
            return False

    def save(self, config_path: Optional[str] = None) -> bool:
        """Save configuration to file."""
        path = config_path or self.config_path
        try:
            data = {
                'database': self.database_config.to_dict(),
                'server': self.server_config.to_dict(),
            }
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except (IOError, OSError) as e:
            print(f"Warning: Failed to save config to {path}: {e}")
            return False

    def get_default_index_config(self, name: str, dimension: int,
                                  index_type: Optional[IndexType] = None,
                                  metric: Optional[MetricType] = None) -> IndexConfig:
        """Create a default index config using global settings."""
        return IndexConfig(
            name=name,
            dimension=dimension,
            index_type=index_type or self.database_config.default_index_type,
            metric=metric or self.database_config.default_metric,
        )


# Global config manager
global_config = ConfigManager()