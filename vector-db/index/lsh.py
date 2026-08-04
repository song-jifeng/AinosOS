"""
LSH (Locality-Sensitive Hashing) index implementation.

LSH uses random projections to hash vectors into buckets such that similar
vectors are likely to hash to the same bucket with high probability.
Multiple hash tables are used to improve recall.

For cosine similarity, we use random hyperplanes (signed random projections).
For Euclidean distance, we use stable distributions.

Key parameters:
- nbits_lsh: Number of hash bits per hash table
- num_tables: Number of independent hash tables

Algorithm:
1. Generate random projection matrices for each hash table
2. Hash each vector by computing sign(random_projections @ vector)
3. Search: hash query vector, check colliding buckets
"""

import numpy as np
import os
import json
import hashlib
from typing import Any, Dict, List, Optional, Set, Tuple
from threading import Lock
from collections import defaultdict

from index.base import BaseIndex
from utils.config import IndexConfig


class LSHIndex(BaseIndex):
    """Locality-Sensitive Hashing index.

    Uses random projections to create hash buckets for approximate
    nearest neighbor search. Supports multiple hash tables for
    improved recall.
    """

    def __init__(self, config: IndexConfig):
        super().__init__(config)

        # LSH parameters
        self.nbits = config.nbits_lsh
        self.num_tables = config.num_tables

        # Random projection matrices: list of (nbits, dimension) arrays
        self._projections: List[np.ndarray] = []

        # Hash tables: list of dicts mapping hash_key -> set of IDs
        self._hash_tables: List[Dict[str, Set[int]]] = []

        # Vector storage (we need original vectors for distance computation)
        self._vectors: Dict[int, np.ndarray] = {}
        self._ids: List[int] = []

        # Precomputed hash keys for each vector in each table
        # id -> list of hash_keys (one per table)
        self._hash_keys: Dict[int, List[str]] = {}

        self._lock = Lock()
        self._is_trained = False
        self._rng = np.random.RandomState(42)

    def _generate_projections(self):
        """Generate random projection matrices for each hash table.

        For cosine similarity, uses random hyperplanes (Gaussian distribution).
        """
        self._projections = []
        for _ in range(self.num_tables):
            # Generate random normal vectors
            proj = self._rng.randn(self.nbits, self.dimension).astype(np.float32)
            # Normalize rows for better performance
            norms = np.linalg.norm(proj, axis=1, keepdims=True)
            proj = proj / np.maximum(norms, 1e-12)
            self._projections.append(proj)

    def _compute_hash(self, vector: np.ndarray, table_idx: int) -> str:
        """Compute the hash key for a vector in a specific table.

        Args:
            vector: Vector of shape (D,)
            table_idx: Hash table index

        Returns:
            Hash key string.
        """
        proj = self._projections[table_idx]  # (nbits, D)
        # Compute dot products with random projections
        dots = np.dot(proj, vector)  # (nbits,)

        # Sign of dot product gives binary hash
        bits = (dots > 0).astype(np.int32)

        # Convert bit string to hex hash
        bit_str = ''.join(str(b) for b in bits)
        return hashlib.md5(bit_str.encode()).hexdigest()

    def train(self, vectors: np.ndarray) -> bool:
        """Train the LSH index by generating random projections.

        Args:
            vectors: Training vectors (used to determine dimension only)

        Returns:
            True if training was successful.
        """
        self._check_vectors(vectors)
        self._generate_projections()

        # Initialize hash tables
        self._hash_tables = [defaultdict(set) for _ in range(self.num_tables)]

        self._is_trained = True
        return True

    def add(self, vectors: np.ndarray, ids: np.ndarray) -> int:
        """Add vectors to the LSH index.

        Each vector is hashed with each hash table and placed in buckets.

        Args:
            vectors: Vectors of shape (N, D)
            ids: Vector IDs of shape (N,)

        Returns:
            Number of vectors added.
        """
        self._check_vectors(vectors)

        if not self._is_trained:
            self.train(vectors)

        n = vectors.shape[0]
        vectors = vectors.astype(np.float32)

        with self._lock:
            for i in range(n):
                id_val = int(ids[i])
                vector = vectors[i]

                self._vectors[id_val] = vector
                self._ids.append(id_val)

                # Compute hash keys for each table
                hash_keys = []
                for t in range(self.num_tables):
                    hk = self._compute_hash(vector, t)
                    hash_keys.append(hk)
                    self._hash_tables[t][hk].add(id_val)

                self._hash_keys[id_val] = hash_keys

            self._vector_count += n
            return n

    def search(self, query_vector: np.ndarray, top_k: int) -> List[Tuple[int, float]]:
        """Search for nearest neighbors using LSH.

        Hashes the query, finds candidates from colliding buckets,
        then computes exact distances for candidates.

        Args:
            query_vector: Query vector of shape (D,)
            top_k: Number of results to return

        Returns:
            List of (id, distance) tuples sorted by distance.
        """
        self._check_vector(query_vector)
        query_vector = query_vector.astype(np.float32)

        with self._lock:
            if self._vector_count == 0:
                return []

            # Find candidate IDs from all hash tables
            candidates: Set[int] = set()
            for t in range(self.num_tables):
                hk = self._compute_hash(query_vector, t)
                if hk in self._hash_tables[t]:
                    candidates.update(self._hash_tables[t][hk])

            if not candidates:
                return []

            # Compute exact distances for candidates
            candidate_list = list(candidates)
            candidate_vectors = np.array([self._vectors[cid] for cid in candidate_list],
                                         dtype=np.float32)

            distances = self.distance_metric.compute(candidate_vectors, query_vector).flatten()

            # Sort and return top_k
            sorted_indices = np.argsort(distances)
            results = [
                (candidate_list[idx], float(distances[idx]))
                for idx in sorted_indices[:top_k]
            ]

            return results

    def delete(self, ids: List[int]) -> int:
        """Delete vectors from the LSH index.

        Args:
            ids: List of vector IDs to delete

        Returns:
            Number of vectors deleted.
        """
        with self._lock:
            count = 0
            for id_val in ids:
                if id_val in self._vectors:
                    # Remove from hash tables
                    if id_val in self._hash_keys:
                        for t, hk in enumerate(self._hash_keys[id_val]):
                            if hk in self._hash_tables[t]:
                                self._hash_tables[t][hk].discard(id_val)

                    # Remove from storage
                    del self._vectors[id_val]
                    del self._hash_keys[id_val]
                    self._ids = [i for i in self._ids if i != id_val]
                    count += 1

            self._vector_count = len(self._vectors)
            return count

    def get(self, id: int) -> Optional[np.ndarray]:
        """Get a vector by its ID.

        Args:
            id: The vector ID

        Returns:
            The vector if found, None otherwise.
        """
        return self._vectors.get(id)

    def size(self) -> int:
        """Get the number of vectors in the index.

        Returns:
            Number of vectors.
        """
        return self._vector_count

    def save(self, path: str) -> bool:
        """Save the LSH index to disk.

        Args:
            path: Directory path to save to

        Returns:
            True if successful.
        """
        try:
            os.makedirs(path, exist_ok=True)

            with self._lock:
                # Save projections
                proj_data = [p.tolist() for p in self._projections]
                np.save(os.path.join(path, 'projections.npy'),
                       np.array(proj_data, dtype=object), allow_pickle=True)

                # Save hash tables (serializable format)
                hash_tables_serializable = {}
                for t, table in enumerate(self._hash_tables):
                    hash_tables_serializable[str(t)] = {
                        k: list(v) for k, v in table.items()
                    }

                data = {
                    'name': self.name,
                    'dimension': self.dimension,
                    'metric': self.metric_type.value,
                    'nbits': self.nbits,
                    'num_tables': self.num_tables,
                    'is_trained': self._is_trained,
                    'vector_count': self._vector_count,
                    'ids': self._ids,
                    'hash_keys': {str(k): v for k, v in self._hash_keys.items()},
                    'hash_tables': hash_tables_serializable,
                }

                with open(os.path.join(path, 'index.json'), 'w') as f:
                    json.dump(data, f, default=str)

                # Save vectors
                if self._vectors:
                    vector_ids = list(self._vectors.keys())
                    vectors_array = np.array([self._vectors[vid] for vid in vector_ids],
                                             dtype=np.float32)
                    np.save(os.path.join(path, 'vectors.npy'), vectors_array)
                    with open(os.path.join(path, 'vector_ids.json'), 'w') as f:
                        json.dump(vector_ids, f)

            return True
        except Exception as e:
            print(f"Failed to save LSHIndex: {e}")
            return False

    def load(self, path: str) -> bool:
        """Load the LSH index from disk.

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
            self.nbits = data['nbits']
            self.num_tables = data['num_tables']
            self._is_trained = data['is_trained']
            self._vector_count = data['vector_count']
            self._ids = data['ids']

            # Restore hash keys
            self._hash_keys = {}
            for k, v in data['hash_keys'].items():
                self._hash_keys[int(k)] = v

            # Restore hash tables
            self._hash_tables = [defaultdict(set) for _ in range(self.num_tables)]
            for t_str, table_dict in data['hash_tables'].items():
                t = int(t_str)
                for k, v in table_dict.items():
                    self._hash_tables[t][k] = set(v)

            # Restore projections
            proj_path = os.path.join(path, 'projections.npy')
            if os.path.exists(proj_path):
                proj_data = np.load(proj_path, allow_pickle=True)
                self._projections = [np.array(p, dtype=np.float32) for p in proj_data]

            # Load vectors
            vec_path = os.path.join(path, 'vectors.npy')
            if os.path.exists(vec_path):
                vectors_array = np.load(vec_path)
                with open(os.path.join(path, 'vector_ids.json'), 'r') as f:
                    vector_ids = json.load(f)
                for vid, vec in zip(vector_ids, vectors_array):
                    self._vectors[int(vid)] = vec

            return True
        except Exception as e:
            print(f"Failed to load LSHIndex: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get the current status of the index.

        Returns:
            Dictionary with status information.
        """
        with self._lock:
            # Compute hash table statistics
            total_buckets = sum(len(t) for t in self._hash_tables)
            total_entries = sum(
                sum(len(v) for v in t.values()) for t in self._hash_tables
            )
            avg_bucket_size = total_entries / max(total_buckets, 1)

            # Compute collision statistics
            if self._ids:
                candidate_counts = []
                for id_val in self._ids[:100]:  # Sample first 100
                    vector = self._vectors.get(id_val)
                    if vector is not None:
                        candidates = set()
                        for t in range(self.num_tables):
                            hk = self._compute_hash(vector, t)
                            if hk in self._hash_tables[t]:
                                candidates.update(self._hash_tables[t][hk])
                        candidate_counts.append(len(candidates))
                avg_candidates = np.mean(candidate_counts) if candidate_counts else 0
            else:
                avg_candidates = 0

            return {
                'type': 'lsh',
                'name': self.name,
                'dimension': self.dimension,
                'metric': self.metric_type.value,
                'size': self._vector_count,
                'parameters': {
                    'nbits': self.nbits,
                    'num_tables': self.num_tables,
                },
                'hash_stats': {
                    'total_buckets': total_buckets,
                    'total_entries': total_entries,
                    'avg_bucket_size': round(float(avg_bucket_size), 2),
                    'avg_candidates_per_query': round(float(avg_candidates), 2),
                },
                'is_trained': self._is_trained,
                'memory_usage_bytes': (
                    len(self._vectors) * self.dimension * 4 +  # vectors
                    self.num_tables * self.nbits * self.dimension * 4 +  # projections
                    total_entries * 8  # hash table entries
                ),
            }