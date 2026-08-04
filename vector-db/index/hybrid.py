"""
Hybrid index implementation that combines multiple index types.

The Hybrid index runs queries against multiple underlying index types
and merges the results using weighted scoring. This allows leveraging
the strengths of different index types simultaneously.

For example, combining HNSW (speed) with Flat (accuracy) can provide
a good balance of performance and recall.
"""

import numpy as np
import os
import json
from typing import Any, Dict, List, Optional, Set, Tuple
from threading import Lock

from .base import BaseIndex
from .flat import FlatIndex
from .hnsw import HNSWIndex
from .ivf import IVFIndex
from .pq import PQIndex
from .lsh import LSHIndex
from ..utils.config import IndexConfig, IndexType, MetricType


class HybridIndex(BaseIndex):
    """Hybrid index combining multiple index types.

    Runs search queries against multiple indices and merges results
    with configurable weights.

    The hybrid index maintains several sub-indices and combines their
    search results for improved accuracy and robustness.
    """

    def __init__(self, config: IndexConfig):
        super().__init__(config)

        # Sub-indices
        self._indices: Dict[str, BaseIndex] = {}

        # Default weights (equal weighting)
        self._weights: Dict[str, float] = {}
        if config.hybrid_weights:
            self._weights = config.hybrid_weights.copy()

        # Strategy: "merge" (combine results) or "layer" (cascade)
        self._strategy = "merge"  # or "layer"

        # Internal ID mapping to ensure consistent IDs across sub-indices
        self._id_mapping: Dict[int, int] = {}  # internal_id -> original_id
        self._reverse_id_mapping: Dict[int, int] = {}  # original_id -> internal_id
        self._next_internal_id = 0
        self._ids: List[int] = []

        self._lock = Lock()
        self._is_trained = False

    def add_index(self, name: str, index: BaseIndex, weight: float = 1.0):
        """Add a sub-index to the hybrid index.

        Args:
            name: Name for the sub-index
            index: Index instance
            weight: Weight for result merging (higher = more influence)
        """
        self._indices[name] = index
        self._weights[name] = weight

    def _create_default_indices(self):
        """Create default sub-indices if none exist."""
        config = self.config

        # Create Flat index (always accurate)
        flat_config = IndexConfig(
            name=f"{self.name}_flat",
            dimension=self.dimension,
            index_type=IndexType.FLAT,
            metric=self.metric_type,
        )
        self.add_index("flat", FlatIndex(flat_config), weight=1.0)

        # Create HNSW index (fast approximate)
        hnsw_config = IndexConfig(
            name=f"{self.name}_hnsw",
            dimension=self.dimension,
            index_type=IndexType.HNSW,
            metric=self.metric_type,
            M=config.M,
            ef_construction=config.ef_construction,
            ef_search=config.ef_search,
        )
        self.add_index("hnsw", HNSWIndex(hnsw_config), weight=1.0)

    def _get_or_create_internal_id(self, original_id: int) -> int:
        """Get or create an internal ID for a given original ID.

        This ensures consistent ID mapping across all sub-indices.
        """
        if original_id not in self._reverse_id_mapping:
            internal_id = self._next_internal_id
            self._next_internal_id += 1
            self._id_mapping[internal_id] = original_id
            self._reverse_id_mapping[original_id] = internal_id
            return internal_id
        return self._reverse_id_mapping[original_id]

    def _get_original_id(self, internal_id: int) -> int:
        """Get the original ID from an internal ID."""
        return self._id_mapping.get(internal_id, internal_id)

    def train(self, vectors: np.ndarray) -> bool:
        """Train all sub-indices.

        Args:
            vectors: Training vectors of shape (N, D)

        Returns:
            True if all sub-indices trained successfully.
        """
        self._check_vectors(vectors)

        if not self._indices:
            self._create_default_indices()

        success = True
        for name, index in self._indices.items():
            if not index.is_trained:
                if not index.train(vectors):
                    print(f"Warning: Failed to train sub-index '{name}'")
                    success = False

        self._is_trained = success
        return success

    def add(self, vectors: np.ndarray, ids: np.ndarray) -> int:
        """Add vectors to all sub-indices.

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
            # Track original IDs
            for i in range(n):
                original_id = int(ids[i])
                self._ids.append(original_id)

            # Add to all sub-indices
            min_count = float('inf')
            for name, index in self._indices.items():
                count = index.add(vectors.copy(), ids.copy())
                min_count = min(min_count, count)

            self._vector_count += n
            return n

    def search(self, query_vector: np.ndarray, top_k: int) -> List[Tuple[int, float]]:
        """Search using the hybrid strategy.

        Merge strategy: Search all sub-indices and merge results with weights.
        Layer strategy: Search first index, then refine with second, etc.

        Args:
            query_vector: Query vector of shape (D,)
            top_k: Number of results to return

        Returns:
            List of (id, distance) tuples sorted by distance.
        """
        self._check_vector(query_vector)

        with self._lock:
            if self._vector_count == 0:
                return []

            if self._strategy == "merge":
                return self._merge_search(query_vector, top_k)
            else:
                return self._layer_search(query_vector, top_k)

    def _merge_search(self, query_vector: np.ndarray, top_k: int) -> List[Tuple[int, float]]:
        """Merge strategy: combine results from all indices with weights.

        Args:
            query_vector: Query vector
            top_k: Number of results

        Returns:
            Sorted list of (id, combined_score) tuples.
        """
        # Collect results from each sub-index
        all_results: Dict[int, float] = {}
        result_sources: Dict[int, List[str]] = {}

        for name, index in self._indices.items():
            weight = self._weights.get(name, 1.0)
            results = index.search(query_vector, top_k * 2)  # Get more for better merging

            for idx, (id_val, distance) in enumerate(results):
                if id_val not in all_results:
                    all_results[id_val] = 0.0
                    result_sources[id_val] = []

                # Normalize distance by rank (1-based)
                rank_score = 1.0 / (idx + 1)
                all_results[id_val] += weight * rank_score
                result_sources[id_val].append(name)

        # Normalize and sort by combined score (higher is better)
        # Convert to distance-like (lower is better) by negating
        scored_results = [
            (id_val, -score / len(result_sources[id_val]))
            for id_val, score in all_results.items()
        ]

        # Sort by score (ascending, since we negated)
        scored_results.sort(key=lambda x: x[1])

        return scored_results[:top_k]

    def _layer_search(self, query_vector: np.ndarray, top_k: int) -> List[Tuple[int, float]]:
        """Layer strategy: cascade search through indices.

        Uses the first (fastest) index to get candidates, then refines
        with more accurate indices.

        Args:
            query_vector: Query vector
            top_k: Number of results

        Returns:
            Sorted list of (id, distance) tuples.
        """
        # Define index order: fast -> accurate
        index_order = ["lsh", "hnsw", "ivf", "pq", "flat"]
        ordered_indices = [
            (name, self._indices[name])
            for name in index_order if name in self._indices
        ]

        if not ordered_indices:
            return []

        # Start with the first index (fastest)
        first_name, first_index = ordered_indices[0]
        results = first_index.search(query_vector, top_k * 3)

        if len(ordered_indices) == 1:
            return results[:top_k]

        # Refine with remaining indices
        candidate_ids = set(r[0] for r in results)

        for name, index in ordered_indices[1:]:
            if not candidate_ids:
                break

            # Get exact distances for candidates from this index
            refined_results = []
            for cid in candidate_ids:
                vec = index.get(cid)
                if vec is not None:
                    dist = float(self.distance_metric.compute(vec, query_vector))
                    refined_results.append((cid, dist))

            refined_results.sort(key=lambda x: x[1])
            candidate_ids = set(r[0] for r in refined_results[:top_k])

        # Return final results
        final_results = [(cid, dist) for cid, dist in refined_results[:top_k]]
        return final_results

    def delete(self, ids: List[int]) -> int:
        """Delete vectors from all sub-indices.

        Args:
            ids: List of vector IDs to delete

        Returns:
            Number of vectors deleted.
        """
        with self._lock:
            count = 0
            for name, index in self._indices.items():
                count = max(count, index.delete(ids))

            self._ids = [i for i in self._ids if i not in set(ids)]
            self._vector_count = len(self._ids)
            return count

    def get(self, id: int) -> Optional[np.ndarray]:
        """Get a vector by its ID from the first available sub-index.

        Args:
            id: The vector ID

        Returns:
            The vector if found, None otherwise.
        """
        for name, index in self._indices.items():
            vec = index.get(id)
            if vec is not None:
                return vec
        return None

    def size(self) -> int:
        """Get the number of vectors in the index.

        Returns:
            Number of vectors.
        """
        return self._vector_count

    def save(self, path: str) -> bool:
        """Save the hybrid index and all sub-indices to disk.

        Args:
            path: Directory path to save to

        Returns:
            True if successful.
        """
        try:
            os.makedirs(path, exist_ok=True)

            with self._lock:
                # Save sub-indices
                sub_index_paths = {}
                for name in self._indices:
                    sub_path = os.path.join(path, f"sub_{name}")
                    index = self._indices[name]
                    if index.save(sub_path):
                        sub_index_paths[name] = f"sub_{name}"

                data = {
                    'name': self.name,
                    'dimension': self.dimension,
                    'metric': self.metric_type.value,
                    'strategy': self._strategy,
                    'weights': self._weights,
                    'is_trained': self._is_trained,
                    'vector_count': self._vector_count,
                    'ids': self._ids,
                    'sub_indices': list(self._indices.keys()),
                    'sub_index_paths': sub_index_paths,
                }

                with open(os.path.join(path, 'index.json'), 'w') as f:
                    json.dump(data, f, default=str)

            return True
        except Exception as e:
            print(f"Failed to save HybridIndex: {e}")
            return False

    def load(self, path: str) -> bool:
        """Load the hybrid index and all sub-indices from disk.

        Args:
            path: Directory path to load from

        Returns:
            True if successful.
        """
        try:
            from ..utils.config import IndexConfig

            with open(os.path.join(path, 'index.json'), 'r') as f:
                data = json.load(f)

            self.name = data['name']
            self.dimension = data['dimension']
            self.strategy = data.get('strategy', 'merge')
            self._weights = data.get('weights', {})
            self._is_trained = data['is_trained']
            self._vector_count = data['vector_count']
            self._ids = data['ids']

            # Load sub-indices
            sub_index_names = data.get('sub_indices', [])
            sub_index_paths = data.get('sub_index_paths', {})

            index_type_map = {
                'flat': FlatIndex,
                'hnsw': HNSWIndex,
                'ivf': IVFIndex,
                'pq': PQIndex,
                'lsh': LSHIndex,
            }

            for name in sub_index_names:
                sub_path = os.path.join(path, sub_index_paths.get(name, f"sub_{name}"))
                sub_info_path = os.path.join(sub_path, 'index.json')

                if os.path.exists(sub_info_path):
                    with open(sub_info_path, 'r') as f:
                        sub_info = json.load(f)

                    sub_type = sub_info.get('type', sub_info.get('name', 'flat'))
                    sub_config = IndexConfig(
                        name=name,
                        dimension=self.dimension,
                        metric=self.metric_type,
                    )

                    # Create appropriate index type
                    index_class = index_type_map.get(sub_type, FlatIndex)
                    index = index_class(sub_config)
                    if index.load(sub_path):
                        self._indices[name] = index
                        if name not in self._weights:
                            self._weights[name] = 1.0

            # Recreate default indices if none loaded
            if not self._indices:
                self._create_default_indices()

            return True
        except Exception as e:
            print(f"Failed to load HybridIndex: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get the current status of the hybrid index.

        Returns:
            Dictionary with status information.
        """
        sub_statuses = {}
        for name, index in self._indices.items():
            sub_statuses[name] = index.get_status()

        return {
            'type': 'hybrid',
            'name': self.name,
            'dimension': self.dimension,
            'metric': self.metric_type.value,
            'size': self._vector_count,
            'strategy': self._strategy,
            'weights': self._weights,
            'sub_indices': sub_statuses,
            'num_sub_indices': len(self._indices),
            'is_trained': self._is_trained,
        }