"""
IVF (Inverted File) index implementation.

The IVF index partitions the vector space using k-means clustering and
only searches the nearest clusters during query time. This provides
significant speed improvements over brute-force search for large datasets.

Key parameters:
- nlist: Number of clusters (Voronoi cells)
- nprobe: Number of nearest clusters to search during query

Algorithm:
1. Training: Run k-means clustering on a representative sample
2. Addition: Assign each vector to its nearest cluster centroid
3. Search: Find nprobe nearest centroids, search only those clusters
"""

import numpy as np
from sklearn.cluster import KMeans as SKLearnKMeans
import os
import json
import pickle
from typing import Any, Dict, List, Optional, Tuple
from threading import Lock
from collections import defaultdict

from .base import BaseIndex
from ..utils.config import IndexConfig


class KMeans:
    """Simple k-means clustering implementation using NumPy.

    This is a self-contained implementation that doesn't depend on sklearn.
    """

    def __init__(self, n_clusters: int, max_iter: int = 100, tol: float = 1e-4,
                 random_seed: int = 42):
        self.n_clusters = n_clusters
        self.max_iter = max_iter
        self.tol = tol
        self.random_seed = random_seed
        self.centroids: Optional[np.ndarray] = None
        self.labels: Optional[np.ndarray] = None
        self.inertia_: float = 0.0
        self.n_iter_: int = 0

    def fit(self, vectors: np.ndarray):
        """Fit k-means to the data.

        Args:
            vectors: Training data of shape (N, D)
        """
        n, d = vectors.shape
        k = min(self.n_clusters, n)

        # Initialize centroids using k-means++
        rng = np.random.RandomState(self.random_seed)
        self.centroids = np.empty((k, d), dtype=np.float32)

        # Choose first centroid randomly
        first_idx = rng.randint(n)
        self.centroids[0] = vectors[first_idx].copy()

        # Choose remaining centroids with probability proportional to distance^2
        for i in range(1, k):
            dists = np.min([
                np.sum((vectors - self.centroids[j]) ** 2, axis=1)
                for j in range(i)
            ], axis=0)
            probs = dists / np.sum(dists)
            cumprobs = np.cumsum(probs)
            r = rng.rand()
            idx = np.searchsorted(cumprobs, r)
            self.centroids[i] = vectors[idx].copy()

        # Iterate
        for iteration in range(self.max_iter):
            # Assign each point to nearest centroid
            dists = np.zeros((n, k), dtype=np.float32)
            for j in range(k):
                diff = vectors - self.centroids[j]
                dists[:, j] = np.sum(diff ** 2, axis=1)
            self.labels = np.argmin(dists, axis=1)

            # Compute new centroids
            new_centroids = np.zeros_like(self.centroids)
            for j in range(k):
                mask = self.labels == j
                if np.sum(mask) > 0:
                    new_centroids[j] = np.mean(vectors[mask], axis=0)
                else:
                    new_centroids[j] = self.centroids[j]  # Keep old centroid

            # Check convergence
            shift = np.sum((new_centroids - self.centroids) ** 2)
            self.centroids = new_centroids

            if shift < self.tol:
                self.n_iter_ = iteration + 1
                break

            self.n_iter_ = iteration + 1

        # Compute inertia (sum of squared distances)
        self.inertia_ = 0.0
        for j in range(k):
            mask = self.labels == j
            if np.sum(mask) > 0:
                diff = vectors[mask] - self.centroids[j]
                self.inertia_ += np.sum(diff ** 2)

    def predict(self, vectors: np.ndarray) -> np.ndarray:
        """Assign vectors to nearest centroids.

        Args:
            vectors: Vectors of shape (N, D)

        Returns:
            Cluster assignments of shape (N,)
        """
        n = vectors.shape[0]
        k = self.centroids.shape[0]
        dists = np.zeros((n, k), dtype=np.float32)
        for j in range(k):
            diff = vectors - self.centroids[j]
            dists[:, j] = np.sum(diff ** 2, axis=1)
        return np.argmin(dists, axis=1)

    def transform(self, vectors: np.ndarray) -> np.ndarray:
        """Compute distances to all centroids.

        Args:
            vectors: Vectors of shape (N, D)

        Returns:
            Distance matrix of shape (N, k)
        """
        n = vectors.shape[0]
        k = self.centroids.shape[0]
        dists = np.zeros((n, k), dtype=np.float32)
        for j in range(k):
            diff = vectors - self.centroids[j]
            dists[:, j] = np.sum(diff ** 2, axis=1)
        return dists


class IVFIndex(BaseIndex):
    """Inverted File index with k-means clustering.

    Partitions the vector space into nlist clusters and only searches
    the nprobe nearest clusters during query.
    """

    def __init__(self, config: IndexConfig):
        super().__init__(config)

        # IVF parameters
        self.nlist = config.nlist
        self.nprobe = config.nprobe

        # Clustering
        self._kmeans: Optional[KMeans] = None
        self._centroids: Optional[np.ndarray] = None

        # Inverted lists: cluster_id -> list of (vector_id, vector)
        self._inverted_lists: Dict[int, List[Tuple[int, np.ndarray]]] = defaultdict(list)
        self._vectors: Dict[int, np.ndarray] = {}  # id -> vector
        self._id_to_cluster: Dict[int, int] = {}  # id -> cluster_id
        self._ids: List[int] = []

        # Precomputed cluster centroids norms (for faster distance)
        self._centroid_norms: Optional[np.ndarray] = None

        self._lock = Lock()
        self._is_trained = False

    def train(self, vectors: np.ndarray) -> bool:
        """Train the IVF index by running k-means clustering.

        Args:
            vectors: Training vectors of shape (N, D)

        Returns:
            True if training was successful.
        """
        self._check_vectors(vectors)
        n = vectors.shape[0]

        if n < self.nlist:
            self.nlist = max(1, n // 4)

        # Run k-means
        self._kmeans = KMeans(n_clusters=self.nlist, random_seed=42)
        self._kmeans.fit(vectors.astype(np.float32))
        self._centroids = self._kmeans.centroids

        # Precompute centroid norms
        if self.metric_type.name == 'COSINE':
            self._centroid_norms = np.linalg.norm(self._centroids, axis=1)

        self._is_trained = True
        return True

    def add(self, vectors: np.ndarray, ids: np.ndarray) -> int:
        """Add vectors to the IVF index.

        Each vector is assigned to its nearest cluster centroid.

        Args:
            vectors: Vectors of shape (N, D)
            ids: Vector IDs of shape (N,)

        Returns:
            Number of vectors added.
        """
        self._check_vectors(vectors)

        if not self._is_trained:
            # Auto-train if not trained
            self.train(vectors)

        n = vectors.shape[0]
        vectors = vectors.astype(np.float32)

        # Assign vectors to nearest centroids
        cluster_assignments = self._kmeans.predict(vectors)

        with self._lock:
            for i in range(n):
                id_val = int(ids[i])
                vector = vectors[i]
                cluster_id = int(cluster_assignments[i])

                self._vectors[id_val] = vector
                self._ids.append(id_val)
                self._id_to_cluster[id_val] = cluster_id
                self._inverted_lists[cluster_id].append((id_val, vector))

            self._vector_count += n
            return n

    def search(self, query_vector: np.ndarray, top_k: int) -> List[Tuple[int, float]]:
        """Search for nearest neighbors in the IVF index.

        Finds the nprobe nearest centroids, then searches only those clusters.

        Args:
            query_vector: Query vector of shape (D,)
            top_k: Number of results to return

        Returns:
            List of (id, distance) tuples sorted by distance.
        """
        self._check_vector(query_vector)
        query_vector = query_vector.astype(np.float32).reshape(1, -1)

        with self._lock:
            if not self._centroids is None and self._vector_count == 0:
                return []

            # Find nearest centroids
            if self.metric_type.name == 'COSINE':
                q_norm = np.linalg.norm(query_vector)
                query_normed = query_vector / max(q_norm, 1e-12)
                centroid_normed = self._centroids / \
                    np.maximum(self._centroid_norms[:, np.newaxis], 1e-12)
                centroid_distances = 1.0 - np.dot(centroid_normed, query_normed.T).flatten()
            else:
                diff = self._centroids - query_vector
                centroid_distances = np.sqrt(np.sum(diff ** 2, axis=1))

            # Get nprobe nearest centroids
            nprobe = min(self.nprobe, len(self._centroids))
            nearest_centroids = np.argsort(centroid_distances)[:nprobe]

            # Search selected clusters
            candidates = []
            for cluster_id in nearest_centroids:
                for id_val, vector in self._inverted_lists.get(int(cluster_id), []):
                    # Compute distance
                    if self.metric_type.name == 'COSINE':
                        v_norm = np.linalg.norm(vector)
                        q_norm = np.linalg.norm(query_vector)
                        sim = np.dot(vector, query_vector.T) / \
                            max(v_norm * q_norm, 1e-12)
                        dist = 1.0 - float(sim)
                    elif self.metric_type.name == 'EUCLIDEAN':
                        dist = float(np.sqrt(np.sum((vector - query_vector) ** 2)))
                    elif self.metric_type.name == 'DOT':
                        dist = -float(np.dot(vector, query_vector.T))
                    elif self.metric_type.name == 'MANHATTAN':
                        dist = float(np.sum(np.abs(vector - query_vector)))
                    else:
                        dist = float(np.linalg.norm(vector - query_vector))

                    candidates.append((dist, id_val))

            # Sort by distance and return top_k
            candidates.sort(key=lambda x: x[0])
            return [(c_id, c_dist) for c_dist, c_id in candidates[:top_k]]

    def delete(self, ids: List[int]) -> int:
        """Delete vectors from the IVF index.

        Args:
            ids: List of vector IDs to delete

        Returns:
            Number of vectors deleted.
        """
        with self._lock:
            count = 0
            for id_val in ids:
                if id_val in self._vectors:
                    # Remove from inverted list
                    cluster_id = self._id_to_cluster.get(id_val)
                    if cluster_id is not None:
                        self._inverted_lists[cluster_id] = [
                            (vid, v) for vid, v in self._inverted_lists[cluster_id]
                            if vid != id_val
                        ]

                    # Remove from storage
                    del self._vectors[id_val]
                    del self._id_to_cluster[id_val]
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
        """Save the IVF index to disk.

        Args:
            path: Directory path to save to

        Returns:
            True if successful.
        """
        try:
            os.makedirs(path, exist_ok=True)

            with self._lock:
                # Save centroids
                if self._centroids is not None:
                    np.save(os.path.join(path, 'centroids.npy'), self._centroids)

                # Save inverted lists (simplified: save as dict of lists of IDs)
                inv_lists_serializable = {}
                for cid, entries in self._inverted_lists.items():
                    inv_lists_serializable[int(cid)] = [int(vid) for vid, _ in entries]

                data = {
                    'name': self.name,
                    'dimension': self.dimension,
                    'metric': self.metric_type.value,
                    'nlist': self.nlist,
                    'nprobe': self.nprobe,
                    'is_trained': self._is_trained,
                    'vector_count': self._vector_count,
                    'ids': self._ids,
                    'id_to_cluster': {int(k): int(v) for k, v in self._id_to_cluster.items()},
                    'inverted_lists': inv_lists_serializable,
                }

                with open(os.path.join(path, 'index.json'), 'w') as f:
                    json.dump(data, f, default=str)

                # Save vectors as numpy array
                if self._vectors:
                    vector_ids = list(self._vectors.keys())
                    vectors_array = np.array([self._vectors[vid] for vid in vector_ids],
                                             dtype=np.float32)
                    np.save(os.path.join(path, 'vectors.npy'), vectors_array)
                    with open(os.path.join(path, 'vector_ids.json'), 'w') as f:
                        json.dump(vector_ids, f)

            return True
        except Exception as e:
            print(f"Failed to save IVFIndex: {e}")
            return False

    def load(self, path: str) -> bool:
        """Load the IVF index from disk.

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
            self.nlist = data['nlist']
            self.nprobe = data['nprobe']
            self._is_trained = data['is_trained']
            self._vector_count = data['vector_count']
            self._ids = data['ids']
            self._id_to_cluster = {int(k): int(v) for k, v in data['id_to_cluster'].items()}

            # Restore centroids
            centroids_path = os.path.join(path, 'centroids.npy')
            if os.path.exists(centroids_path):
                self._centroids = np.load(centroids_path)
                self._kmeans = KMeans(n_clusters=self.nlist)
                self._kmeans.centroids = self._centroids

            # Restore inverted lists
            self._inverted_lists = defaultdict(list)
            for cid_str, vid_list in data['inverted_lists'].items():
                self._inverted_lists[int(cid_str)] = []

            # Load vectors
            vec_path = os.path.join(path, 'vectors.npy')
            if os.path.exists(vec_path):
                vectors_array = np.load(vec_path)
                with open(os.path.join(path, 'vector_ids.json'), 'r') as f:
                    vector_ids = json.load(f)

                for vid, vec in zip(vector_ids, vectors_array):
                    vid = int(vid)
                    self._vectors[vid] = vec
                    cluster_id = self._id_to_cluster.get(vid)
                    if cluster_id is not None:
                        self._inverted_lists[cluster_id].append((vid, vec))

            return True
        except Exception as e:
            print(f"Failed to load IVFIndex: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get the current status of the index.

        Returns:
            Dictionary with status information.
        """
        with self._lock:
            cluster_sizes = {
                int(cid): len(entries)
                for cid, entries in self._inverted_lists.items()
            }
            avg_cluster_size = np.mean(list(cluster_sizes.values())) if cluster_sizes else 0
            max_cluster_size = max(cluster_sizes.values()) if cluster_sizes else 0
            min_cluster_size = min(cluster_sizes.values()) if cluster_sizes else 0

            return {
                'type': 'ivf',
                'name': self.name,
                'dimension': self.dimension,
                'metric': self.metric_type.value,
                'size': self._vector_count,
                'parameters': {
                    'nlist': self.nlist,
                    'nprobe': self.nprobe,
                },
                'cluster_stats': {
                    'num_clusters': len(cluster_sizes),
                    'avg_cluster_size': round(float(avg_cluster_size), 2),
                    'max_cluster_size': int(max_cluster_size),
                    'min_cluster_size': int(min_cluster_size),
                    'cluster_sizes': cluster_sizes,
                },
                'is_trained': self._is_trained,
                'memory_usage_bytes': (
                    len(self._vectors) * self.dimension * 4 +  # vectors
                    (self._centroids.size if self._centroids is not None else 0) * 4 +  # centroids
                    sum(len(e) * 2 * 4 for e in self._inverted_lists.values())  # approx inv lists
                ),
            }