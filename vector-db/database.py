"""
Main VectorDatabase class.

Provides the high-level API for the vector database, including:
- Creating and managing collections (indices)
- Inserting, searching, and deleting vectors
- Persisting and loading from disk
- Statistics and monitoring
"""

import numpy as np
import os
import json
import time
import threading
from typing import Any, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, field

from .index import (
    BaseIndex, FlatIndex, HNSWIndex, IVFIndex, PQIndex, LSHIndex, HybridIndex
)
from .index.base import BaseIndex
from .distance import DistanceMetric, MetricType
from .storage import MemoryStorage, DiskStorage, SQLiteStorage
from .utils.config import (
    IndexConfig, IndexType, StorageType, MetricType, ConfigManager, global_config
)
from .utils.metrics import MetricsCollector, timed
from .utils.serializer import Serializer, VectorSerializer


class SearchResult:
    """Represents a single search result."""

    def __init__(self, id: int, score: float, metadata: Optional[Dict[str, Any]] = None):
        self.id = id
        self.score = score
        self.metadata = metadata

    def to_dict(self) -> Dict[str, Any]:
        result = {"id": self.id, "score": self.score}
        if self.metadata is not None:
            result["metadata"] = self.metadata
        return result

    def __repr__(self) -> str:
        return f"SearchResult(id={self.id}, score={self.score:.4f})"


class IndexStats:
    """Statistics for a collection."""

    def __init__(self, name: str, dimension: int, index_type: str,
                 metric: str, size: int, status: Dict[str, Any]):
        self.name = name
        self.dimension = dimension
        self.index_type = index_type
        self.metric = metric
        self.size = size
        self.status = status

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "dimension": self.dimension,
            "index_type": self.index_type,
            "metric": self.metric,
            "size": self.size,
            "status": self.status,
        }

    def __repr__(self) -> str:
        return (f"IndexStats(name={self.name}, dim={self.dimension}, "
                f"type={self.index_type}, metric={self.metric}, "
                f"size={self.size})")


class VectorDatabase:
    """Main vector database class.

    Provides a high-level API for managing vector collections with
    multiple index types, distance metrics, and storage backends.
    """

    def __init__(self, config: Optional[Any] = None):
        # Collection management
        self._collections: Dict[str, BaseIndex] = {}
        self._configs: Dict[str, IndexConfig] = {}
        self._storage: Dict[str, Any] = {}  # Storage backends per collection
        self._metadata_storage: Dict[str, SQLiteStorage] = {}

        # Metadata storage for the database itself
        self._db_metadata: SQLiteStorage = SQLiteStorage(":memory:")

        # Configuration
        self._config = config or global_config

        # Metrics
        self.metrics = MetricsCollector(enabled=True)

        # Thread safety
        self._lock = threading.RLock()

        # Database state
        self._loaded = False
        self._persist_path: Optional[str] = None

    @timed()
    def create_index(self, name: str, dimension: int,
                     index_type: Union[str, IndexType] = IndexType.FLAT,
                     metric: Union[str, MetricType] = MetricType.COSINE,
                     **kwargs) -> bool:
        """Create a new index (collection).

        Args:
            name: Collection name
            dimension: Vector dimension
            index_type: Type of index to create
            metric: Distance metric to use
            **kwargs: Additional index-specific parameters

        Returns:
            True if the index was created successfully.
        """
        if isinstance(index_type, str):
            index_type = IndexType(index_type)
        if isinstance(metric, str):
            metric = MetricType(metric)

        if name in self._collections:
            raise ValueError(f"Collection '{name}' already exists")

        # Build config
        config = IndexConfig(
            name=name,
            dimension=dimension,
            index_type=index_type,
            metric=metric,
            **{k: v for k, v in kwargs.items()
               if k in IndexConfig.__dataclass_fields__},
        )

        # Create index
        index = self._create_index_instance(config)
        index.train(np.empty((0, dimension)))  # Mark as trained

        # Create storage
        storage = self._create_storage(config)

        # Create metadata storage
        meta_storage = SQLiteStorage(f":memory:", dimension=dimension)

        with self._lock:
            self._collections[name] = index
            self._configs[name] = config
            self._storage[name] = storage
            self._metadata_storage[name] = meta_storage

        return True

    def _create_index_instance(self, config: IndexConfig) -> BaseIndex:
        """Create an index instance based on the config.

        Args:
            config: Index configuration

        Returns:
            Index instance.
        """
        if config.index_type == IndexType.FLAT:
            return FlatIndex(config)
        elif config.index_type == IndexType.HNSW:
            return HNSWIndex(config)
        elif config.index_type == IndexType.IVF:
            return IVFIndex(config)
        elif config.index_type == IndexType.PQ:
            return PQIndex(config)
        elif config.index_type == IndexType.LSH:
            return LSHIndex(config)
        elif config.index_type == IndexType.HYBRID:
            return HybridIndex(config)
        else:
            raise ValueError(f"Unknown index type: {config.index_type}")

    def _create_storage(self, config: IndexConfig) -> Any:
        """Create a storage backend based on the config.

        Args:
            config: Index configuration

        Returns:
            Storage instance.
        """
        if config.storage_type == StorageType.MEMORY:
            return MemoryStorage(dimension=config.dimension)
        elif config.storage_type == StorageType.DISK:
            path = config.persist_path or f"./data/{config.name}"
            return DiskStorage(dimension=config.dimension, base_path=path)
        elif config.storage_type == StorageType.SQLITE:
            return SQLiteStorage(dimension=config.dimension)
        else:
            return MemoryStorage(dimension=config.dimension)

    @timed()
    def drop_index(self, name: str) -> bool:
        """Drop an index (collection).

        Args:
            name: Collection name

        Returns:
            True if the index was dropped.
        """
        with self._lock:
            if name not in self._collections:
                return False

            del self._collections[name]
            del self._configs[name]
            if name in self._storage:
                self._storage[name].clear()
                del self._storage[name]
            if name in self._metadata_storage:
                self._metadata_storage[name].close()
                del self._metadata_storage[name]

            return True

    @timed()
    def insert(self, collection: str, vectors: np.ndarray,
               metadata: Optional[List[Optional[Dict[str, Any]]]] = None) -> int:
        """Insert vectors into a collection.

        Args:
            collection: Collection name
            vectors: Vectors of shape (N, D)
            metadata: Optional list of metadata dictionaries

        Returns:
            Number of vectors inserted.
        """
        with self._lock:
            if collection not in self._collections:
                raise ValueError(f"Collection '{collection}' not found")

            index = self._collections[collection]
            config = self._configs[collection]
            storage = self._storage.get(collection)
            meta_storage = self._metadata_storage.get(collection)

            n = vectors.shape[0]

            # Generate IDs
            start_id = index.size()
            ids = np.arange(start_id, start_id + n, dtype=np.int64)

            # Normalize vectors if needed
            vectors = index.normalize_vectors(vectors)

            # Add to index
            index.add(vectors, ids)

            # Add to storage
            if storage is not None:
                storage.insert(vectors, ids, metadata)

            # Add metadata to SQLite
            if meta_storage is not None and metadata is not None:
                meta_storage.insert_metadata_batch(ids.tolist(), metadata)

            # Update metrics
            self.metrics.update_memory(
                vector_bytes=n * config.dimension * 4
            )

            return n

    @timed()
    def search(self, collection: str, query_vector: np.ndarray,
               top_k: int = 10) -> List[SearchResult]:
        """Search for nearest neighbors in a collection.

        Args:
            collection: Collection name
            query_vector: Query vector of shape (D,)
            top_k: Number of results to return

        Returns:
            List of SearchResult objects.
        """
        with self._lock:
            if collection not in self._collections:
                raise ValueError(f"Collection '{collection}' not found")

            index = self._collections[collection]
            meta_storage = self._metadata_storage.get(collection)

            # Normalize query vector
            query_vector = index.normalize_vector(query_vector)

            # Search
            raw_results = index.search(query_vector, top_k)

            # Enrich with metadata
            results = []
            for id_val, distance in raw_results:
                meta = None
                if meta_storage is not None:
                    meta = meta_storage.get_metadata(int(id_val))
                results.append(SearchResult(
                    id=int(id_val),
                    score=float(distance),
                    metadata=meta
                ))

            return results

    @timed()
    def delete(self, collection: str, ids: List[int]) -> int:
        """Delete vectors from a collection.

        Args:
            collection: Collection name
            ids: List of vector IDs to delete

        Returns:
            Number of vectors deleted.
        """
        with self._lock:
            if collection not in self._collections:
                raise ValueError(f"Collection '{collection}' not found")

            index = self._collections[collection]
            storage = self._storage.get(collection)
            meta_storage = self._metadata_storage.get(collection)

            # Delete from index
            count = index.delete(ids)

            # Delete from storage
            if storage is not None:
                storage.delete(ids)

            # Delete metadata
            if meta_storage is not None:
                meta_storage.delete_metadata_batch(ids)

            return count

    @timed()
    def get(self, collection: str, ids: List[int]) -> List[Optional[SearchResult]]:
        """Get vectors by their IDs.

        Args:
            collection: Collection name
            ids: List of vector IDs

        Returns:
            List of SearchResult objects (or None for not found).
        """
        with self._lock:
            if collection not in self._collections:
                raise ValueError(f"Collection '{collection}' not found")

            index = self._collections[collection]
            meta_storage = self._metadata_storage.get(collection)

            results = []
            for id_val in ids:
                vector = index.get(id_val)
                if vector is not None:
                    meta = None
                    if meta_storage is not None:
                        meta = meta_storage.get_metadata(int(id_val))
                    results.append(SearchResult(
                        id=int(id_val),
                        score=0.0,
                        metadata=meta
                    ))
                else:
                    results.append(None)

            return results

    @timed()
    def stats(self, collection: Optional[str] = None) -> Any:
        """Get statistics for a collection or all collections.

        Args:
            collection: Optional collection name. If None, returns all stats.

        Returns:
            IndexStats or dict of IndexStats.
        """
        with self._lock:
            if collection is not None:
                if collection not in self._collections:
                    raise ValueError(f"Collection '{collection}' not found")
                return self._get_collection_stats(collection)

            return {
                name: self._get_collection_stats(name)
                for name in self._collections
            }

    def _get_collection_stats(self, name: str) -> IndexStats:
        """Get statistics for a single collection.

        Args:
            name: Collection name

        Returns:
            IndexStats object.
        """
        index = self._collections[name]
        config = self._configs[name]
        status = index.get_status()
        storage = self._storage.get(name)

        return IndexStats(
            name=name,
            dimension=config.dimension,
            index_type=config.index_type.value,
            metric=config.metric.value,
            size=index.size(),
            status=status
        )

    @timed()
    def persist(self, path: str) -> bool:
        """Persist the entire database to disk.

        Args:
            path: Directory path to save to

        Returns:
            True if successful.
        """
        try:
            os.makedirs(path, exist_ok=True)

            with self._lock:
                # Save each collection
                collection_data = {}
                for name, index in self._collections.items():
                    config = self._configs[name]
                    collection_path = os.path.join(path, name)
                    os.makedirs(collection_path, exist_ok=True)

                    # Save index
                    index.save(collection_path)

                    # Save config
                    with open(os.path.join(collection_path, 'config.json'), 'w') as f:
                        json.dump(config.to_dict(), f, default=str)

                    collection_data[name] = {
                        'index_type': config.index_type.value,
                        'dimension': config.dimension,
                    }

                # Save database metadata
                db_meta = {
                    'version': '0.1.0',
                    'created_at': time.time(),
                    'collections': collection_data,
                    'collection_order': list(self._collections.keys()),
                }
                with open(os.path.join(path, 'database.json'), 'w') as f:
                    json.dump(db_meta, f, default=str)

                self._persist_path = path

            return True
        except Exception as e:
            print(f"Failed to persist database: {e}")
            return False

    @timed()
    def load(self, path: str) -> bool:
        """Load the database from disk.

        Args:
            path: Directory path to load from

        Returns:
            True if successful.
        """
        from .utils.config import IndexConfig

        try:
            # Load database metadata
            with open(os.path.join(path, 'database.json'), 'r') as f:
                db_meta = json.load(f)

            # Load each collection
            for collection_name in db_meta.get('collection_order', []):
                collection_path = os.path.join(path, collection_name)

                # Load config
                with open(os.path.join(collection_path, 'config.json'), 'r') as f:
                    config_data = json.load(f)
                config = IndexConfig.from_dict(config_data)

                # Create index instance
                index = self._create_index_instance(config)
                index.load(collection_path)

                # Create storage
                storage = self._create_storage(config)

                with self._lock:
                    self._collections[collection_name] = index
                    self._configs[collection_name] = config
                    self._storage[collection_name] = storage
                    self._metadata_storage[collection_name] = SQLiteStorage(
                        f":memory:", dimension=config.dimension
                    )

            self._loaded = True
            self._persist_path = path

            return True
        except Exception as e:
            print(f"Failed to load database: {e}")
            return False

    def list_collections(self) -> List[str]:
        """List all collection names.

        Returns:
            List of collection names.
        """
        return list(self._collections.keys())

    def get_collection_info(self, name: str) -> Dict[str, Any]:
        """Get detailed information about a collection.

        Args:
            name: Collection name

        Returns:
            Dictionary with collection info.
        """
        with self._lock:
            if name not in self._collections:
                raise ValueError(f"Collection '{name}' not found")

            config = self._configs[name]
            index = self._collections[name]
            status = index.get_status()

            return {
                'name': name,
                'dimension': config.dimension,
                'index_type': config.index_type.value,
                'metric': config.metric.value,
                'size': index.size(),
                'config': config.to_dict(),
                'status': status,
            }

    def search_with_filter(self, collection: str, query_vector: np.ndarray,
                            top_k: int = 10,
                            filters: Optional[Dict[str, Any]] = None,
                            tags: Optional[List[str]] = None) -> List[SearchResult]:
        """Search with metadata filtering.

        This is a post-filtering approach: first filters by metadata,
        then searches among the filtered set.

        Args:
            collection: Collection name
            query_vector: Query vector
            top_k: Number of results
            filters: Metadata filters
            tags: Tag filters

        Returns:
            List of SearchResult objects.
        """
        with self._lock:
            if collection not in self._collections:
                raise ValueError(f"Collection '{collection}' not found")

            meta_storage = self._metadata_storage.get(collection)
            if meta_storage is None:
                return self.search(collection, query_vector, top_k)

            # Get filtered IDs
            filtered_ids = set()
            if filters:
                filtered_ids = set(meta_storage.filter_by_metadata(filters))
            if tags:
                tag_ids = set(meta_storage.filter_by_tags(tags))
                if filtered_ids:
                    filtered_ids &= tag_ids
                else:
                    filtered_ids = tag_ids

            if not filtered_ids:
                # No filter matches, search all
                return self.search(collection, query_vector, top_k)

            # Search among filtered set
            index = self._collections[collection]
            query_vector = index.normalize_vector(query_vector)

            # Get vectors for filtered IDs
            filtered_list = list(filtered_ids)
            vectors = []
            valid_ids = []
            for fid in filtered_list:
                vec = index.get(fid)
                if vec is not None:
                    vectors.append(vec)
                    valid_ids.append(fid)

            if not vectors:
                return []

            vectors_array = np.array(vectors)
            distances = index.distance_metric.compute(vectors_array, query_vector).flatten()

            # Sort and return
            sorted_indices = np.argsort(distances)
            results = []
            for idx in sorted_indices[:top_k]:
                vid = valid_ids[idx]
                meta = meta_storage.get_metadata(vid)
                results.append(SearchResult(
                    id=vid,
                    score=float(distances[idx]),
                    metadata=meta
                ))

            return results

    def get_metrics_report(self) -> str:
        """Get a formatted metrics report.

        Returns:
            Metrics report string.
        """
        return self.metrics.get_metrics_report()

    def close(self):
        """Close the database and release resources."""
        for name in list(self._collections.keys()):
            self.drop_index(name)
        self._db_metadata.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False