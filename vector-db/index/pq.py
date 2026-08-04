"""
Product Quantization (PQ) index implementation.

Product Quantization compresses vectors by splitting them into subvectors
and quantizing each subvector independently using a codebook learned via
k-means. This dramatically reduces memory usage and enables fast
approximate distance computation using lookup tables (ADC - Asymmetric
Distance Computation).

Key parameters:
- m_subquantizers: Number of subquantizers (number of subvector spaces)
- nbits: Number of bits per subquantizer (2^nbits centroids per subspace)

Algorithm:
1. Training: Split vectors into m subvectors, learn k-means for each subspace
2. Encoding: Assign each subvector to its nearest centroid, store codes
3. Search: Build lookup tables for query subvectors, compute approximate distances
"""

import numpy as np
import os
import json
import math
from typing import Any, Dict, List, Optional, Tuple
from threading import Lock

from .base import BaseIndex
from ..utils.config import IndexConfig


class PQIndex(BaseIndex):
    """Product Quantization index.

    Compresses vectors using product quantization for efficient
    approximate nearest neighbor search with low memory footprint.
    """

    def __init__(self, config: IndexConfig):
        super().__init__(config)

        # PQ parameters
        self.m_subquantizers = config.m_subquantizers
        self.nbits = config.nbits
        self.ncentroids = 1 << config.nbits  # 2^nbits

        # Derived parameters
        self._subvector_dim = 0  # Dimension of each subvector
        self._subvector_dims: List[int] = []  # Actual dimensions of each subvector

        # Codebooks: list of centroids per subspace, each of shape (ncentroids, subdim)
        self._codebooks: List[np.ndarray] = []

        # Encoded vectors: dict of id -> codes (array of m centroid indices)
        self._codes: Dict[int, np.ndarray] = {}
        self._ids: List[int] = []

        # Precomputed norms for ADC
        self._precomputed_norms: Optional[np.ndarray] = None

        # Lookup table for current query (used during search)
        self._lookup_tables: List[np.ndarray] = []

        self._lock = Lock()
        self._is_trained = False

    def _compute_subvector_dims(self):
        """Compute the dimension of each subvector.

        Handles cases where dimension is not evenly divisible by m.
        """
        self._subvector_dim = self.dimension // self.m_subquantizers
        remainder = self.dimension % self.m_subquantizers

        self._subvector_dims = []
        for i in range(self.m_subquantizers):
            dim = self._subvector_dim
            if i < remainder:
                dim += 1
            self._subvector_dims.append(dim)

    def _split_vectors(self, vectors: np.ndarray) -> List[np.ndarray]:
        """Split vectors into m subvector groups.

        Args:
            vectors: Vectors of shape (N, D)

        Returns:
            List of m arrays, each of shape (N, subdim_i)
        """
        split_idx = 0
        subvectors = []
        for dim in self._subvector_dims:
            subvectors.append(vectors[:, split_idx:split_idx + dim].copy())
            split_idx += dim
        return subvectors

    def _encode_vector(self, vector: np.ndarray) -> np.ndarray:
        """Encode a single vector using product quantization.

        Args:
            vector: Vector of shape (D,)

        Returns:
            Codes array of shape (m,) with centroid indices.
        """
        codes = np.zeros(self.m_subquantizers, dtype=np.int32)
        split_idx = 0

        for i in range(self.m_subquantizers):
            dim = self._subvector_dims[i]
            subvector = vector[split_idx:split_idx + dim]

            # Find nearest centroid in this subspace
            codebook = self._codebooks[i]
            diffs = codebook - subvector
            dists = np.sum(diffs ** 2, axis=1)
            codes[i] = int(np.argmin(dists))

            split_idx += dim

        return codes

    def _encode_vectors(self, vectors: np.ndarray) -> np.ndarray:
        """Encode multiple vectors using product quantization.

        Args:
            vectors: Vectors of shape (N, D)

        Returns:
            Codes array of shape (N, m)
        """
        n = vectors.shape[0]
        codes = np.zeros((n, self.m_subquantizers), dtype=np.int32)
        subvectors = self._split_vectors(vectors)

        for i in range(self.m_subquantizers):
            codebook = self._codebooks[i]  # (ncentroids, subdim)
            sv = subvectors[i]  # (N, subdim)

            # Compute distances to all centroids
            # (N, subdim) -> (N, 1, subdim) - (1, ncentroids, subdim) -> (N, ncentroids, subdim)
            diffs = sv[:, np.newaxis, :] - codebook[np.newaxis, :, :]
            dists = np.sum(diffs ** 2, axis=2)  # (N, ncentroids)
            codes[:, i] = np.argmin(dists, axis=1)

        return codes

    def _compute_lookup_tables(self, query_vector: np.ndarray):
        """Compute lookup tables for asymmetric distance computation.

        For each subspace, precompute the distance from the query subvector
        to each centroid in that subspace's codebook.

        Args:
            query_vector: Query vector of shape (D,)
        """
        self._lookup_tables = []
        split_idx = 0

        for i in range(self.m_subquantizers):
            dim = self._subvector_dims[i]
            subvector = query_vector[split_idx:split_idx + dim]

            codebook = self._codebooks[i]
            diffs = codebook - subvector
            dists = np.sum(diffs ** 2, axis=1)
            self._lookup_tables.append(dists)

            split_idx += dim

    def _compute_adc_distance(self, codes: np.ndarray) -> float:
        """Compute asymmetric distance from lookup tables.

        Sums the precomputed distances for each subvector's code.

        Args:
            codes: Codes array of shape (m,)

        Returns:
            Approximate distance.
        """
        dist = 0.0
        for i in range(self.m_subquantizers):
            dist += self._lookup_tables[i][codes[i]]
        return math.sqrt(dist)

    def train(self, vectors: np.ndarray) -> bool:
        """Train the product quantizer.

        Learns k-means codebooks for each subspace.

        Args:
            vectors: Training vectors of shape (N, D)

        Returns:
            True if training was successful.
        """
        self._check_vectors(vectors)
        self._compute_subvector_dims()

        # Split vectors into subvectors
        subvectors = self._split_vectors(vectors.astype(np.float32))

        # Learn codebook for each subspace
        self._codebooks = []
        for i in range(self.m_subquantizers):
            sv = subvectors[i]  # (N, subdim_i)
            ncentroids = min(self.ncentroids, sv.shape[0])

            # Run k-means for this subspace
            codebook = self._run_kmeans(sv, ncentroids)
            self._codebooks.append(codebook)

        self._is_trained = True
        return True

    def _run_kmeans(self, vectors: np.ndarray, k: int,
                    max_iter: int = 50, tol: float = 1e-4) -> np.ndarray:
        """Run k-means clustering on vectors.

        Args:
            vectors: Vectors of shape (N, D)
            k: Number of clusters
            max_iter: Maximum iterations
            tol: Convergence tolerance

        Returns:
            Centroids of shape (k, D)
        """
        n, d = vectors.shape
        k = min(k, n)

        # Initialize with k-means++
        rng = np.random.RandomState(42)
        centroids = np.empty((k, d), dtype=np.float32)

        # First centroid
        centroids[0] = vectors[rng.randint(n)].copy()

        for i in range(1, k):
            dists = np.zeros(n)
            for j in range(i):
                diff = vectors - centroids[j]
                d2 = np.sum(diff ** 2, axis=1)
                dists = np.minimum(dists, d2) if j > 0 else d2
            probs = dists / np.sum(dists)
            cumprobs = np.cumsum(probs)
            centroids[i] = vectors[np.searchsorted(cumprobs, rng.rand())].copy()

        # Iterate
        for iteration in range(max_iter):
            # Assignment step
            dists = np.zeros((n, k), dtype=np.float32)
            for j in range(k):
                diff = vectors - centroids[j]
                dists[:, j] = np.sum(diff ** 2, axis=1)
            labels = np.argmin(dists, axis=1)

            # Update step
            new_centroids = np.zeros_like(centroids)
            for j in range(k):
                mask = labels == j
                if np.sum(mask) > 0:
                    new_centroids[j] = np.mean(vectors[mask], axis=0)
                else:
                    new_centroids[j] = centroids[j]

            # Check convergence
            shift = np.sum((new_centroids - centroids) ** 2)
            centroids = new_centroids
            if shift < tol:
                break

        return centroids

    def add(self, vectors: np.ndarray, ids: np.ndarray) -> int:
        """Add vectors to the PQ index by encoding them.

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

        # Encode vectors
        codes = self._encode_vectors(vectors)

        with self._lock:
            for i in range(n):
                id_val = int(ids[i])
                self._codes[id_val] = codes[i]
                self._ids.append(id_val)

            self._vector_count += n
            return n

    def search(self, query_vector: np.ndarray, top_k: int) -> List[Tuple[int, float]]:
        """Search for nearest neighbors using asymmetric distance computation.

        Args:
            query_vector: Query vector of shape (D,)
            top_k: Number of results to return

        Returns:
            List of (id, distance) tuples sorted by distance.
        """
        self._check_vector(query_vector)
        query_vector = query_vector.astype(np.float32)

        if self._vector_count == 0:
            return []

        # Compute lookup tables for this query
        self._compute_lookup_tables(query_vector)

        # Compute approximate distances for all encoded vectors
        candidates = []
        with self._lock:
            for id_val, codes in self._codes.items():
                dist = self._compute_adc_distance(codes)
                candidates.append((dist, id_val))

        # Sort by distance and return top_k
        candidates.sort(key=lambda x: x[0])
        return [(c_id, c_dist) for c_dist, c_id in candidates[:top_k]]

    def delete(self, ids: List[int]) -> int:
        """Delete vectors from the PQ index.

        Args:
            ids: List of vector IDs to delete

        Returns:
            Number of vectors deleted.
        """
        with self._lock:
            count = 0
            for id_val in ids:
                if id_val in self._codes:
                    del self._codes[id_val]
                    self._ids = [i for i in self._ids if i != id_val]
                    count += 1

            self._vector_count = len(self._codes)
            return count

    def get(self, id: int) -> Optional[np.ndarray]:
        """Get a vector by its ID.

        Note: PQ only stores compressed codes, not original vectors.
        Returns a decoded (approximate) reconstruction.

        Args:
            id: The vector ID

        Returns:
            Approximate reconstructed vector, or None if not found.
        """
        with self._lock:
            if id in self._codes:
                return self._decode_vector(self._codes[id])
            return None

    def _decode_vector(self, codes: np.ndarray) -> np.ndarray:
        """Reconstruct an approximate vector from its codes.

        Args:
            codes: Codes array of shape (m,)

        Returns:
            Reconstructed vector of shape (D,)
        """
        vector = np.zeros(self.dimension, dtype=np.float32)
        offset = 0

        for i in range(self.m_subquantizers):
            dim = self._subvector_dims[i]
            centroid_idx = codes[i]
            vector[offset:offset + dim] = self._codebooks[i][centroid_idx]
            offset += dim

        return vector

    def size(self) -> int:
        """Get the number of vectors in the index.

        Returns:
            Number of vectors.
        """
        return self._vector_count

    def save(self, path: str) -> bool:
        """Save the PQ index to disk.

        Args:
            path: Directory path to save to

        Returns:
            True if successful.
        """
        try:
            os.makedirs(path, exist_ok=True)

            with self._lock:
                # Save codebooks
                codebook_data = [cb.tolist() for cb in self._codebooks]
                np.save(os.path.join(path, 'codebooks.npy'),
                       np.array(codebook_data, dtype=object), allow_pickle=True)

                # Save codes
                codes_serializable = {int(k): v.tolist() for k, v in self._codes.items()}

                data = {
                    'name': self.name,
                    'dimension': self.dimension,
                    'metric': self.metric_type.value,
                    'm_subquantizers': self.m_subquantizers,
                    'nbits': self.nbits,
                    'ncentroids': self.ncentroids,
                    'subvector_dim': self._subvector_dim,
                    'subvector_dims': self._subvector_dims,
                    'is_trained': self._is_trained,
                    'vector_count': self._vector_count,
                    'ids': self._ids,
                    'codes': codes_serializable,
                }

                with open(os.path.join(path, 'index.json'), 'w') as f:
                    json.dump(data, f, default=str)

            return True
        except Exception as e:
            print(f"Failed to save PQIndex: {e}")
            return False

    def load(self, path: str) -> bool:
        """Load the PQ index from disk.

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
            self.m_subquantizers = data['m_subquantizers']
            self.nbits = data['nbits']
            self.ncentroids = data['ncentroids']
            self._subvector_dim = data['subvector_dim']
            self._subvector_dims = data['subvector_dims']
            self._is_trained = data['is_trained']
            self._vector_count = data['vector_count']
            self._ids = data['ids']

            # Restore codes
            self._codes = {}
            for k, v in data['codes'].items():
                self._codes[int(k)] = np.array(v, dtype=np.int32)

            # Restore codebooks
            codebook_path = os.path.join(path, 'codebooks.npy')
            if os.path.exists(codebook_path):
                codebook_data = np.load(codebook_path, allow_pickle=True)
                self._codebooks = [np.array(cb, dtype=np.float32) for cb in codebook_data]

            return True
        except Exception as e:
            print(f"Failed to load PQIndex: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get the current status of the index.

        Returns:
            Dictionary with status information.
        """
        with self._lock:
            compression_ratio = self.dimension * 4 / (self.m_subquantizers * self.nbits / 8)
            codebook_size = sum(
                cb.size * 4 for cb in self._codebooks
            )

            return {
                'type': 'pq',
                'name': self.name,
                'dimension': self.dimension,
                'metric': self.metric_type.value,
                'size': self._vector_count,
                'parameters': {
                    'm_subquantizers': self.m_subquantizers,
                    'nbits': self.nbits,
                    'ncentroids': self.ncentroids,
                    'subvector_dim': self._subvector_dim,
                },
                'compression': {
                    'compression_ratio': round(compression_ratio, 2),
                    'original_bytes': self._vector_count * self.dimension * 4,
                    'compressed_bytes': self._vector_count * self.m_subquantizers * self.nbits // 8,
                    'codebook_bytes': codebook_size,
                },
                'is_trained': self._is_trained,
                'memory_usage_bytes': (
                    self._vector_count * self.m_subquantizers * (self.nbits // 8) +  # codes
                    codebook_size  # codebooks
                ),
            }