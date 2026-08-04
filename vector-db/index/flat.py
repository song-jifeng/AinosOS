"""
Flat (brute-force) index implementation.

The Flat index performs exhaustive search by computing distances between
the query vector and all stored vectors. This is the simplest and most
accurate index type, but also the slowest for large datasets.

Use Flat when:
- Dataset is small (< 100K vectors)
- Exact results are required
- As a baseline for evaluating other index types
"""

import numpy as np
import os
import json
import pickle
from typing import Any, Dict, List, Optional, Tuple
from threading import Lock

from index.base import BaseIndex
from utils.config import IndexConfig


class FlatIndex(BaseIndex):
    """Flat (brute-force) index.

    Stores all vectors in a contiguous numpy array and performs
    exhaustive search by computing distances to all vectors.
    """

    def __init__(self, config: IndexConfig):
        super().__init__(config)
        self._vectors: Optional[np.ndarray] = None
        self._ids: List[int] = []
        self._id_to_index: Dict[int, int] = {}
        self._capacity = 0
        self._size = 0
        self._deleted_ids: set = set()
        self._lock = Lock()

        # Pre-allocated norms for faster cosine search
        self._norms: Optional[np.ndarray] = None

    def train(self, vectors: np.ndarray) -> bool:
        """Flat index does not require training.

        Args:
            vectors: Training vectors (ignored)

        Returns:
            True always.
        """
        self._is_trained = True
        return True

    def add(self, vectors: np.ndarray, ids: np.ndarray) -> int:
        """Add vectors to the index.

        Args:
            vectors: Vectors of shape (N, D)
            ids: Vector IDs of shape (N,)

        Returns:
            Number of vectors added.
        """
        self._check_vectors(vectors)
        n = vectors.shape[0]

        with self._lock:
            if self._vectors is None:
                # Allocate initial storage
                self._capacity = max(n, 1024)
                self._vectors = np.empty((self._capacity, self.dimension),
                                         dtype=np.float32)
                self._norms = np.empty(self._capacity, dtype=np.float32)

            # Grow if needed
            needed = self._size + n
            if needed > self._capacity:
                new_capacity = int(max(needed * 1.5, self._capacity * 2))
                self._vectors = np.resize(self._vectors, (new_capacity, self.dimension))
                self._norms = np.resize(self._norms, new_capacity)
                self._capacity = new_capacity

            # Store vectors
            vectors = vectors.astype(np.float32)
            self._vectors[self._size:needed] = vectors

            # Compute norms for cosine
            if self.metric_type.name == 'COSINE':
                self._norms[self._size:needed] = np.linalg.norm(vectors, axis=1)

            # Store IDs
            for i in range(n):
                idx = self._size + i
                id_val = int(ids[i])
                self._ids.append(id_val)
                self._id_to_index[id_val] = idx

            self._size = needed
            self._vector_count = self._size - len(self._deleted_ids)

            return n

    def search(self, query_vector: np.ndarray, top_k: int) -> List[Tuple[int, float]]:
        """Search for nearest neighbors by brute force.

        Args:
            query_vector: Query vector of shape (D,)
            top_k: Number of results to return

        Returns:
            List of (id, distance) tuples.
        """
        self._check_vector(query_vector)
        query_vector = query_vector.astype(np.float32).reshape(1, -1)

        with self._lock:
            if self._size == 0:
                return []

            # Compute distances
            if self.metric_type.name == 'COSINE':
                q_norm = np.linalg.norm(query_vector)
                query_normed = query_vector / max(q_norm, 1e-12)
                vec_normed = self._vectors[:self._size] / \
                    np.maximum(self._norms[:self._size, np.newaxis], 1e-12)
                distances = 1.0 - np.dot(vec_normed, query_normed.T).flatten()
            elif self.metric_type.name == 'EUCLIDEAN':
                diff = self._vectors[:self._size] - query_vector
                distances = np.sqrt(np.sum(diff ** 2, axis=1))
            elif self.metric_type.name == 'DOT':
                distances = -np.dot(self._vectors[:self._size], query_vector.T).flatten()
            elif self.metric_type.name == 'MANHATTAN':
                distances = np.sum(np.abs(self._vectors[:self._size] - query_vector), axis=1)
            else:
                distances = np.linalg.norm(self._vectors[:self._size] - query_vector, axis=1)

            # Get top-k (handle deleted IDs)
            actual_k = min(top_k + len(self._deleted_ids), self._size)
            top_indices = np.argpartition(distances, actual_k - 1)[:actual_k]
            top_indices = top_indices[np.argsort(distances[top_indices])]

            # Filter out deleted IDs
            results = []
            for idx in top_indices:
                id_val = self._ids[idx]
                if id_val not in self._deleted_ids:
                    results.append((id_val, float(distances[idx])))
                    if len(results) >= top_k:
                        break

            return results

    def delete(self, ids: List[int]) -> int:
        """Delete vectors by their IDs.

        Args:
            ids: List of vector IDs to delete

        Returns:
            Number of vectors deleted.
        """
        with self._lock:
            count = 0
            for id_val in ids:
                if id_val in self._id_to_index:
                    self._deleted_ids.add(id_val)
                    del self._id_to_index[id_val]
                    count += 1

            self._vector_count = self._size - len(self._deleted_ids)
            return count

    def get(self, id: int) -> Optional[np.ndarray]:
        """Get a vector by its ID.

        Args:
            id: The vector ID

        Returns:
            The vector if found, None otherwise.
        """
        with self._lock:
            if id in self._id_to_index:
                idx = self._id_to_index[id]
                return self._vectors[idx].copy()
            return None

    def size(self) -> int:
        """Get the number of vectors in the index.

        Returns:
            Number of active vectors.
        """
        return self._vector_count

    def save(self, path: str) -> bool:
        """Save the index to disk.

        Args:
            path: Directory path to save to

        Returns:
            True if successful.
        """
        try:
            os.makedirs(path, exist_ok=True)

            with self._lock:
                # Save vectors
                valid_indices = [i for i in range(self._size)
                               if self._ids[i] not in self._deleted_ids]
                if valid_indices:
                    vectors = self._vectors[valid_indices]
                    np.save(os.path.join(path, 'vectors.npy'), vectors)

                # Save metadata
                data = {
                    'name': self.name,
                    'dimension': self.dimension,
                    'metric': self.metric_type.value,
                    'size': len(valid_indices),
                    'ids': [self._ids[i] for i in valid_indices],
                    'is_trained': self._is_trained,
                }
                with open(os.path.join(path, 'index.json'), 'w') as f:
                    json.dump(data, f, default=str)

            return True
        except Exception as e:
            print(f"Failed to save FlatIndex: {e}")
            return False

    def load(self, path: str) -> bool:
        """Load the index from disk.

        Args:
            path: Directory path to load from

        Returns:
            True if successful.
        """
        try:
            with open(os.path.join(path, 'index.json'), 'r') as f:
                data = json.load(f)

            self.name = data['name']
            self.dimension = data['dimension']
            self.metric_type = self.config.metric.__class__(data['metric'])
            self._is_trained = data['is_trained']

            # Load vectors
            vec_path = os.path.join(path, 'vectors.npy')
            if os.path.exists(vec_path):
                vectors = np.load(vec_path)
                ids = np.array(data['ids'], dtype=np.int64)
                self.add(vectors, ids)

            return True
        except Exception as e:
            print(f"Failed to load FlatIndex: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get the current status of the index.

        Returns:
            Dictionary with status information.
        """
        with self._lock:
            return {
                'type': 'flat',
                'name': self.name,
                'dimension': self.dimension,
                'metric': self.metric_type.value,
                'size': self._vector_count,
                'capacity': self._capacity,
                'total_added': self._size,
                'deleted_count': len(self._deleted_ids),
                'is_trained': self._is_trained,
                'memory_usage_bytes': (self._capacity * self.dimension * 4 +
                                       self._capacity * 4),  # vectors + norms
            }

    def get_all_vectors(self) -> Tuple[np.ndarray, List[int]]:
        """Get all vectors and their IDs.

        Returns:
            Tuple of (vectors, ids).
        """
        with self._lock:
            valid_indices = [i for i in range(self._size)
                           if self._ids[i] not in self._deleted_ids]
            if not valid_indices:
                return np.empty((0, self.dimension), dtype=np.float32), []
            return self._vectors[valid_indices].copy(), [self._ids[i] for i in valid_indices]