"""
HNSW (Hierarchical Navigable Small World) index implementation.

HNSW builds a multi-layer graph structure for approximate nearest neighbor search.
It uses a hierarchical approach where upper layers have fewer nodes and longer
edges, allowing efficient navigation from coarse to fine granularity.

Based on the paper: "Efficient and robust approximate nearest neighbor search
using Hierarchical Navigable Small World graphs" by Malkov & Yashunin (2018).

Key parameters:
- M: Number of bi-directional connections per element (default: 16)
- ef_construction: Size of dynamic candidate list during construction (default: 200)
- ef_search: Size of dynamic candidate list during search (default: 50)
- max_level: Maximum level in the hierarchy (default: 16)
- level_multiplier: Normalization factor for level generation (default: 1/log(M))
"""

import numpy as np
import heapq
import math
import random
import os
import json
import pickle
from typing import Any, Dict, List, Optional, Set, Tuple
from threading import Lock

from .base import BaseIndex
from ..utils.config import IndexConfig


class HNSWIndex(BaseIndex):
    """Hierarchical Navigable Small World graph index.

    Builds a multi-layer graph where each layer is a navigable small world
    graph. Upper layers contain fewer nodes with longer edges, enabling
    efficient coarse-to-fine search.
    """

    def __init__(self, config: IndexConfig):
        super().__init__(config)

        # HNSW parameters
        self.M = config.M
        self.M_max = config.M
        self.M_max0 = config.M * 2  # Max connections at level 0
        self.ef_construction = config.ef_construction
        self.ef_search = config.ef_search
        self.max_level = config.max_level
        self.level_multiplier = config.level_multiplier
        self.ml = config.level_multiplier  # 1 / log(M)

        # Internal storage
        self._vectors: Dict[int, np.ndarray] = {}  # id -> vector
        self._ids: List[int] = []  # All vector IDs in insertion order
        self._levels: Dict[int, int] = {}  # id -> level
        self._graph: Dict[int, Dict[int, Set[int]]] = {}  # id -> {level: set(neighbors)}
        self._enter_point: Optional[int] = None  # Entry point for search

        # Search statistics
        self._dist_computations = 0
        self._lock = Lock()

        # Random number generator
        self._rng = random.Random(42)

    def _get_random_level(self) -> int:
        """Generate a random level for a new element.

        Uses exponential distribution to determine the level.
        Higher levels are exponentially less likely.

        Returns:
            Level number (0 = base layer).
        """
        # Level distribution: P(level) = exp(-level / ml)
        level = int(-math.log(self._rng.random() + 1e-100) * self.ml)
        return min(level, self.max_level)

    def _distance(self, a: np.ndarray, b: np.ndarray) -> float:
        """Compute distance between two vectors.

        Args:
            a: First vector
            b: Second vector

        Returns:
            Distance value.
        """
        self._dist_computations += 1
        return float(self.distance_metric.compute(a, b))

    def _distance_many(self, query: np.ndarray, candidates: List[int]) -> np.ndarray:
        """Compute distances from query to multiple candidates.

        Args:
            query: Query vector
            candidates: List of candidate IDs

        Returns:
            Array of distances.
        """
        if not candidates:
            return np.array([])

        query_vec = query.astype(np.float32)
        cand_vecs = np.array([self._vectors[cid] for cid in candidates], dtype=np.float32)
        self._dist_computations += len(candidates)
        return self.distance_metric.compute(cand_vecs, query_vec).flatten()

    def _select_neighbors_simple(self, candidates: List[Tuple[float, int]],
                                  M: int) -> List[int]:
        """Select M nearest neighbors from candidates.

        Args:
            candidates: List of (distance, id) tuples
            M: Number of neighbors to select

        Returns:
            List of selected neighbor IDs.
        """
        # Sort by distance and take top M
        candidates.sort(key=lambda x: x[0])
        return [c_id for _, c_id in candidates[:M]]

    def _select_neighbors_heuristic(self, candidates: List[Tuple[float, int]],
                                     M: int, extend: bool = False,
                                     keep_pruned: bool = False) -> List[int]:
        """Select diverse neighbors using the heuristic from the HNSW paper.

        This heuristic prefers neighbors that are diverse (not too close to
        already selected neighbors), improving graph navigability.

        Args:
            candidates: List of (distance, id) tuples
            M: Maximum number of neighbors to select
            extend: Whether to extend the candidate set
            keep_pruned: Whether to keep pruned candidates

        Returns:
            List of selected neighbor IDs.
        """
        # Sort candidates by distance
        candidates = sorted(candidates, key=lambda x: x[0])

        selected = []
        rejected = []

        for dist, c_id in candidates:
            if len(selected) >= M:
                rejected.append((dist, c_id))
                continue

            # Check if candidate is closer to query than to any selected neighbor
            is_diverse = True
            for s_id in selected:
                if c_id == s_id:
                    continue
                d_to_selected = self._distance(
                    self._vectors[c_id], self._vectors[s_id]
                )
                if d_to_selected < dist:
                    is_diverse = False
                    break

            if is_diverse:
                selected.append(c_id)
            else:
                rejected.append((dist, c_id))

        if keep_pruned:
            # Add rejected neighbors if there's room
            remaining = M - len(selected)
            if remaining > 0:
                selected.extend([r_id for _, r_id in rejected[:remaining]])

        return selected

    def _search_layer(self, query_vector: np.ndarray, entry_point: int,
                       ef: int, layer: int) -> Dict[int, float]:
        """Search a single layer for nearest neighbors.

        Uses a best-first search with a priority queue.

        Args:
            query_vector: Query vector
            entry_point: Starting node ID
            ef: Size of the dynamic candidate list
            layer: Layer number to search

        Returns:
            Dictionary of {id: distance} for the nearest neighbors found.
        """
        visited = {entry_point}
        result = {entry_point: self._distance(query_vector, self._vectors[entry_point])}

        # Priority queue: (distance, id) - min-heap
        candidates = [(result[entry_point], entry_point)]

        while candidates:
            # Get closest unexplored node
            dist_c, c_id = heapq.heappop(candidates)

            # Find furthest result
            furthest_dist = max(result.values())

            if dist_c > furthest_dist and len(result) >= ef:
                break

            # Explore neighbors of current node
            for neighbor_id in self._graph.get(c_id, {}).get(layer, set()):
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)

                dist = self._distance(query_vector, self._vectors[neighbor_id])
                furthest_dist = max(result.values())

                if dist < furthest_dist or len(result) < ef:
                    result[neighbor_id] = dist
                    heapq.heappush(candidates, (dist, neighbor_id))

                    # Trim if exceeding ef
                    if len(result) > ef:
                        # Find and remove the furthest
                        furthest_id = max(result, key=result.get)
                        del result[furthest_id]

        return result

    def train(self, vectors: np.ndarray) -> bool:
        """HNSW does not require separate training.

        Args:
            vectors: Training vectors (ignored)

        Returns:
            True always.
        """
        self._is_trained = True
        return True

    def add(self, vectors: np.ndarray, ids: np.ndarray) -> int:
        """Add vectors to the HNSW graph.

        Each vector is inserted at a random level and connected to its
        nearest neighbors at each level.

        Args:
            vectors: Vectors of shape (N, D)
            ids: Vector IDs of shape (N,)

        Returns:
            Number of vectors added.
        """
        self._check_vectors(vectors)
        n = vectors.shape[0]

        with self._lock:
            for i in range(n):
                vector = vectors[i].astype(np.float32)
                id_val = int(ids[i])
                level = self._get_random_level()

                self._vectors[id_val] = vector
                self._ids.append(id_val)
                self._levels[id_val] = level

                # Initialize graph for this node at each level
                self._graph[id_val] = {}
                for l in range(level + 1):
                    self._graph[id_val][l] = set()

                self._insert(id_val, level)

            self._vector_count += n
            return n

    def _insert(self, id_val: int, level: int):
        """Insert a single element into the HNSW graph.

        Args:
            id_val: ID of the element to insert
            level: Random level assigned to this element
        """
        query_vector = self._vectors[id_val]

        if self._enter_point is None:
            # First element
            self._enter_point = id_val
            return

        # Find entry point at the top level
        curr_entry = self._enter_point

        # Phase 1: Traverse from top level down to the insertion level
        for l in range(self._levels.get(curr_entry, 0), level, -1):
            if l in self._graph.get(curr_entry, {}):
                result = self._search_layer(query_vector, curr_entry, 1, l)
                curr_entry = min(result, key=result.get)  # Closest node

        # Phase 2: Insert at each level from min(level, top_level) down to 0
        for l in range(min(level, self._levels.get(curr_entry, 0)), -1, -1):
            result = self._search_layer(query_vector, curr_entry,
                                        self.ef_construction, l)

            # Select neighbors
            candidates = [(dist, n_id) for n_id, dist in result.items()]
            neighbors = self._select_neighbors_heuristic(candidates, self.M_max0 if l == 0 else self.M)

            # Connect bidirectional edges
            for neighbor_id in neighbors:
                self._graph[id_val][l].add(neighbor_id)
                self._graph[neighbor_id][l].add(id_val)

                # Shrink neighbor's connections if needed
                self._shrink_neighbors(neighbor_id, l)

            # Set entry point as closest from this layer
            if result:
                curr_entry = min(result, key=result.get)

        # Update global entry point if this element is at a higher level
        if level > self._levels.get(self._enter_point, 0):
            self._enter_point = id_val

    def _shrink_neighbors(self, node_id: int, layer: int):
        """Shrink the neighbor list of a node if it exceeds the maximum.

        Args:
            node_id: Node ID
            layer: Layer number
        """
        max_conn = self.M_max0 if layer == 0 else self.M_max
        neighbors = self._graph[node_id][layer]

        if len(neighbors) <= max_conn:
            return

        # Get distances from node to its neighbors
        node_vec = self._vectors[node_id]
        neighbor_list = [(self._distance(node_vec, self._vectors[n_id]), n_id)
                        for n_id in neighbors]

        # Select diverse subset
        new_neighbors = self._select_neighbors_heuristic(
            neighbor_list, max_conn, extend=True, keep_pruned=False
        )

        self._graph[node_id][layer] = set(new_neighbors)

    def search(self, query_vector: np.ndarray, top_k: int) -> List[Tuple[int, float]]:
        """Search for nearest neighbors in the HNSW graph.

        Traverses from top layer to bottom, then performs ef_search at base layer.

        Args:
            query_vector: Query vector of shape (D,)
            top_k: Number of results to return

        Returns:
            List of (id, distance) tuples sorted by distance.
        """
        self._check_vector(query_vector)

        ef = max(self.ef_search, top_k)

        with self._lock:
            if self._enter_point is None or self._vector_count == 0:
                return []

            query_vector = query_vector.astype(np.float32)

            # Phase 1: Traverse from top level to level 0
            curr_entry = self._enter_point
            top_level = self._levels.get(self._enter_point, 0)

            for l in range(top_level, 0, -1):
                if l in self._graph.get(curr_entry, {}):
                    result = self._search_layer(query_vector, curr_entry, 1, l)
                    if result:
                        curr_entry = min(result, key=result.get)

            # Phase 2: Search at level 0
            result = self._search_layer(query_vector, curr_entry, ef, 0)

            # Sort by distance and return top_k
            sorted_results = sorted(result.items(), key=lambda x: x[1])
            return sorted_results[:top_k]

    def delete(self, ids: List[int]) -> int:
        """Delete vectors from the HNSW graph.

        Note: This is a simplified deletion that marks IDs as removed
        but does not reconnect the graph. For production use, a more
        sophisticated deletion strategy would be needed.

        Args:
            ids: List of vector IDs to delete

        Returns:
            Number of vectors deleted.
        """
        with self._lock:
            count = 0
            for id_val in ids:
                if id_val in self._vectors:
                    # Remove from all neighbor lists
                    for level, neighbors in self._graph.get(id_val, {}).items():
                        for neighbor_id in neighbors:
                            if neighbor_id in self._graph:
                                self._graph[neighbor_id].get(level, set()).discard(id_val)

                    # Remove from storage
                    del self._vectors[id_val]
                    del self._levels[id_val]
                    if id_val in self._graph:
                        del self._graph[id_val]

                    self._ids = [i for i in self._ids if i != id_val]

                    # Update entry point if needed
                    if id_val == self._enter_point and self._vectors:
                        self._enter_point = self._ids[0] if self._ids else None

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
        """Save the HNSW index to disk.

        Args:
            path: Directory path to save to

        Returns:
            True if successful.
        """
        try:
            os.makedirs(path, exist_ok=True)

            with self._lock:
                # Convert graph to serializable format
                graph_serializable = {}
                for nid, levels in self._graph.items():
                    graph_serializable[str(nid)] = {
                        str(l): list(neighbors)
                        for l, neighbors in levels.items()
                    }

                data = {
                    'name': self.name,
                    'dimension': self.dimension,
                    'metric': self.metric_type.value,
                    'M': self.M,
                    'M_max': self.M_max,
                    'M_max0': self.M_max0,
                    'ef_construction': self.ef_construction,
                    'ef_search': self.ef_search,
                    'max_level': self.max_level,
                    'level_multiplier': self.level_multiplier,
                    'ml': self.ml,
                    'enter_point': self._enter_point,
                    'is_trained': self._is_trained,
                    'vector_count': self._vector_count,
                    'ids': self._ids,
                    'levels': {str(k): v for k, v in self._levels.items()},
                    'graph': graph_serializable,
                }

                with open(os.path.join(path, 'index.json'), 'w') as f:
                    json.dump(data, f, default=str)

                # Save vectors as numpy array
                if self._vectors:
                    vector_ids = list(self._vectors.keys())
                    vectors_array = np.array([self._vectors[vid] for vid in vector_ids],
                                             dtype=np.float32)
                    np.save(os.path.join(path, 'vectors.npy'), vectors_array)
                    # Save the order of IDs for vectors
                    with open(os.path.join(path, 'vector_ids.json'), 'w') as f:
                        json.dump(vector_ids, f)

            return True
        except Exception as e:
            print(f"Failed to save HNSWIndex: {e}")
            return False

    def load(self, path: str) -> bool:
        """Load the HNSW index from disk.

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
            self.M = data['M']
            self.M_max = data['M_max']
            self.M_max0 = data['M_max0']
            self.ef_construction = data['ef_construction']
            self.ef_search = data['ef_search']
            self.max_level = data['max_level']
            self.level_multiplier = data['level_multiplier']
            self.ml = data['ml']
            self._enter_point = data['enter_point']
            self._is_trained = data['is_trained']
            self._vector_count = data['vector_count']
            self._ids = data['ids']
            self._levels = {int(k): v for k, v in data['levels'].items()}

            # Restore graph
            self._graph = {}
            for nid_str, levels in data['graph'].items():
                nid = int(nid_str)
                self._graph[nid] = {}
                for l_str, neighbors in levels.items():
                    self._graph[nid][int(l_str)] = set(neighbors)

            # Load vectors
            vec_path = os.path.join(path, 'vectors.npy')
            if os.path.exists(vec_path):
                vectors_array = np.load(vec_path)
                with open(os.path.join(path, 'vector_ids.json'), 'r') as f:
                    vector_ids = json.load(f)
                for vid, vec in zip(vector_ids, vectors_array):
                    self._vectors[vid] = vec

            return True
        except Exception as e:
            print(f"Failed to load HNSWIndex: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get the current status of the index.

        Returns:
            Dictionary with status information.
        """
        with self._lock:
            total_edges = sum(
                len(neighbors)
                for node in self._graph.values()
                for neighbors in node.values()
            )
            avg_edges = total_edges / max(len(self._graph), 1)
            max_level = max(self._levels.values()) if self._levels else 0

            # Count nodes per level
            level_distribution = {}
            for level in range(max_level + 1):
                level_distribution[level] = sum(
                    1 for l in self._levels.values() if l >= level
                )

            return {
                'type': 'hnsw',
                'name': self.name,
                'dimension': self.dimension,
                'metric': self.metric_type.value,
                'size': self._vector_count,
                'parameters': {
                    'M': self.M,
                    'M_max': self.M_max,
                    'M_max0': self.M_max0,
                    'ef_construction': self.ef_construction,
                    'ef_search': self.ef_search,
                    'max_level': self.max_level,
                    'level_multiplier': self.level_multiplier,
                },
                'graph_stats': {
                    'total_nodes': len(self._graph),
                    'total_edges': total_edges,
                    'avg_edges_per_node': round(avg_edges, 2),
                    'max_level': max_level,
                    'level_distribution': level_distribution,
                },
                'dist_computations': self._dist_computations,
                'is_trained': self._is_trained,
                'memory_usage_bytes': (
                    len(self._vectors) * self.dimension * 4 +  # vectors
                    total_edges * 8 +  # graph edges (approx)
                    len(self._levels) * 4  # level storage
                ),
            }