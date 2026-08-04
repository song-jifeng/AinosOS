"""
In-memory storage backend for vectors.

Stores vectors and metadata in NumPy arrays and Python dictionaries.
Provides fast access suitable for real-time search operations.
"""

import numpy as np
from typing import Any, Dict, List, Optional, Tuple, Union
from threading import Lock


class MemoryStorage:
    """Thread-safe in-memory storage for vectors and metadata.

    Stores vectors as a NumPy array and metadata as a list of dictionaries.
    Supports dynamic growth and efficient batch operations.
    """

    def __init__(self, dimension: int, dtype: np.dtype = np.float32):
        self.dimension = dimension
        self.dtype = dtype

        # Primary storage
        self._vectors: Optional[np.ndarray] = None
        self._ids: List[int] = []
        self._metadata: List[Optional[Dict[str, Any]]] = []
        self._id_to_index: Dict[int, int] = {}

        # Storage capacity
        self._capacity = 0
        self._size = 0
        self._growth_factor = 1.5
        self._initial_capacity = 1024

        # Thread safety
        self._lock = Lock()

        # Memory tracking
        self._total_vector_bytes = 0
        self._total_metadata_bytes = 0

    def _allocate(self, capacity: int):
        """Allocate internal storage for the given capacity."""
        new_vectors = np.empty((capacity, self.dimension), dtype=self.dtype)
        if self._vectors is not None and self._size > 0:
            new_vectors[:self._size] = self._vectors[:self._size]
        self._vectors = new_vectors
        self._capacity = capacity

    def _grow(self, min_capacity: Optional[int] = None):
        """Grow storage to accommodate more vectors."""
        if min_capacity is None:
            min_capacity = int(self._capacity * self._growth_factor) + 1
        new_capacity = max(min_capacity, self._capacity + self._initial_capacity)
        self._allocate(new_capacity)

    def insert(self, vectors: np.ndarray, ids: Optional[np.ndarray] = None,
               metadata: Optional[List[Optional[Dict[str, Any]]]] = None) -> int:
        """Insert vectors into storage.

        Args:
            vectors: Array of shape (N, D)
            ids: Optional array of IDs. Auto-generated if None.
            metadata: Optional list of metadata dicts.

        Returns:
            Number of vectors inserted.
        """
        with self._lock:
            n = vectors.shape[0]

            if ids is None:
                start_id = max(self._ids) + 1 if self._ids else 0
                ids = np.arange(start_id, start_id + n, dtype=np.int64)

            if metadata is None:
                metadata = [None] * n

            # Ensure capacity
            needed = self._size + n
            if needed > self._capacity:
                self._grow(needed)

            # Store vectors
            self._vectors[self._size:needed] = vectors.astype(self.dtype)

            # Store IDs and metadata
            for i in range(n):
                idx = self._size + i
                id_val = int(ids[i])
                self._ids.append(id_val)
                self._id_to_index[id_val] = idx
                self._metadata.append(metadata[i])

            self._size = needed

            # Update memory tracking
            vec_bytes = n * self.dimension * np.dtype(self.dtype).itemsize
            self._total_vector_bytes += vec_bytes
            meta_bytes = sum(len(str(m)) * 2 for m in metadata if m is not None)
            self._total_metadata_bytes += meta_bytes

            return n

    def get(self, ids: List[int]) -> Tuple[np.ndarray, List[int], List[Optional[Dict[str, Any]]]]:
        """Retrieve vectors by their IDs.

        Args:
            ids: List of vector IDs to retrieve.

        Returns:
            Tuple of (vectors, found_ids, metadata).
        """
        with self._lock:
            found_indices = []
            found_ids = []
            for id_val in ids:
                if id_val in self._id_to_index:
                    idx = self._id_to_index[id_val]
                    found_indices.append(idx)
                    found_ids.append(id_val)

            if not found_indices:
                return np.empty((0, self.dimension), dtype=self.dtype), [], []

            vectors = self._vectors[found_indices].copy()
            metadata = [self._metadata[idx] for idx in found_indices]
            return vectors, found_ids, metadata

    def delete(self, ids: List[int]) -> int:
        """Delete vectors by their IDs.

        Uses a tombstone approach: marks deleted IDs by removing from the
        index map. The actual vector data is preserved for later compaction.

        Args:
            ids: List of vector IDs to delete.

        Returns:
            Number of vectors deleted.
        """
        with self._lock:
            count = 0
            for id_val in ids:
                if id_val in self._id_to_index:
                    idx = self._id_to_index.pop(id_val)
                    # Mark the ID as deleted (set to -1)
                    self._ids[idx] = -1
                    self._metadata[idx] = None
                    count += 1

            # Update memory tracking
            vec_bytes = count * self.dimension * np.dtype(self.dtype).itemsize
            self._total_vector_bytes = max(0, self._total_vector_bytes - vec_bytes)

            return count

    def compact(self) -> int:
        """Compact storage by removing deleted vectors.

        Rebuilds internal arrays without deleted entries.

        Returns:
            Number of vectors after compaction.
        """
        with self._lock:
            valid_indices = [i for i in range(self._size) if self._ids[i] != -1]

            if len(valid_indices) == self._size:
                return self._size  # Nothing to compact

            new_size = len(valid_indices)
            new_vectors = np.empty((new_size, self.dimension), dtype=self.dtype)
            new_ids = []
            new_metadata = []
            new_id_to_index = {}

            for new_idx, old_idx in enumerate(valid_indices):
                new_vectors[new_idx] = self._vectors[old_idx]
                id_val = self._ids[old_idx]
                new_ids.append(id_val)
                new_id_to_index[id_val] = new_idx
                new_metadata.append(self._metadata[old_idx])

            self._vectors = new_vectors
            self._ids = new_ids
            self._id_to_index = new_id_to_index
            self._metadata = new_metadata
            self._capacity = new_size
            self._size = new_size

            return new_size

    def search_brute_force(self, query_vector: np.ndarray, top_k: int,
                            distance_fn) -> List[Tuple[int, float, Optional[Dict[str, Any]]]]:
        """Perform brute-force search over all vectors.

        Args:
            query_vector: Query vector of shape (D,)
            top_k: Number of results to return.
            distance_fn: Distance function to use.

        Returns:
            List of (id, distance, metadata) tuples.
        """
        with self._lock:
            if self._size == 0:
                return []

            # Compute distances
            distances = distance_fn(self._vectors[:self._size], query_vector)

            # Get top-k indices
            if len(distances) <= top_k:
                top_indices = np.argsort(distances)
            else:
                top_indices = np.argpartition(distances, top_k)[:top_k]
                top_indices = top_indices[np.argsort(distances[top_indices])]

            # Build results
            results = []
            for idx in top_indices:
                id_val = self._ids[idx]
                if id_val != -1:  # Skip deleted
                    dist = float(distances[idx])
                    meta = self._metadata[idx]
                    results.append((id_val, dist, meta))

            return results[:top_k]

    def get_all_vectors(self) -> Tuple[np.ndarray, List[int], List[Optional[Dict[str, Any]]]]:
        """Get all vectors, IDs, and metadata.

        Returns:
            Tuple of (vectors, ids, metadata).
        """
        with self._lock:
            valid_indices = [i for i in range(self._size) if self._ids[i] != -1]
            if not valid_indices:
                return np.empty((0, self.dimension), dtype=self.dtype), [], []

            vectors = self._vectors[valid_indices].copy()
            ids = [self._ids[i] for i in valid_indices]
            metadata = [self._metadata[i] for i in valid_indices]
            return vectors, ids, metadata

    def get_vectors_array(self) -> np.ndarray:
        """Get the raw vectors array (valid entries only)."""
        with self._lock:
            valid_indices = [i for i in range(self._size) if self._ids[i] != -1]
            if not valid_indices:
                return np.empty((0, self.dimension), dtype=self.dtype)
            return self._vectors[valid_indices].copy()

    def get_ids_array(self) -> np.ndarray:
        """Get the IDs array (valid entries only)."""
        with self._lock:
            return np.array([self._ids[i] for i in range(self._size)
                           if self._ids[i] != -1], dtype=np.int64)

    def get_id_to_index(self) -> Dict[int, int]:
        """Get the ID-to-index mapping."""
        with self._lock:
            return dict(self._id_to_index)

    def size(self) -> int:
        """Get the number of valid vectors."""
        with self._lock:
            return len(self._id_to_index)

    def capacity(self) -> int:
        """Get the total storage capacity."""
        return self._capacity

    def memory_usage(self) -> Dict[str, int]:
        """Get memory usage statistics."""
        with self._lock:
            return {
                "vector_bytes": self._total_vector_bytes,
                "metadata_bytes": self._total_metadata_bytes,
                "total_bytes": self._total_vector_bytes + self._total_metadata_bytes,
                "vector_count": self._size,
                "capacity": self._capacity,
            }

    def clear(self):
        """Clear all data."""
        with self._lock:
            self._vectors = None
            self._ids.clear()
            self._metadata.clear()
            self._id_to_index.clear()
            self._capacity = 0
            self._size = 0
            self._total_vector_bytes = 0
            self._total_metadata_bytes = 0

    def to_dict(self) -> Dict[str, Any]:
        """Export all data to a dictionary for serialization."""
        vectors, ids, metadata = self.get_all_vectors()
        return {
            "dimension": self.dimension,
            "dtype": str(self.dtype),
            "vectors": vectors.tolist(),
            "ids": ids,
            "metadata": metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MemoryStorage':
        """Load data from a dictionary."""
        storage = cls(dimension=data["dimension"])
        vectors = np.array(data["vectors"], dtype=storage.dtype)
        ids = np.array(data["ids"], dtype=np.int64)
        metadata = data.get("metadata", [None] * len(ids))
        storage.insert(vectors, ids, metadata)
        return storage