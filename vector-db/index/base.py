"""
Base index class for all vector index implementations.

Defines the common interface that all index types must implement.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from ..distance import DistanceMetric, MetricType
from ..utils.config import IndexConfig


class BaseIndex(ABC):
    """Abstract base class for all vector index implementations.

    All index types (Flat, HNSW, IVF, PQ, LSH, Hybrid) must inherit from
    this class and implement all abstract methods.
    """

    def __init__(self, config: IndexConfig):
        self.config = config
        self.name = config.name
        self.dimension = config.dimension
        self.metric_type = config.metric
        self.distance_metric = DistanceMetric(config.metric)
        self._is_trained = False
        self._vector_count = 0

    @property
    def is_trained(self) -> bool:
        """Whether the index has been trained."""
        return self._is_trained

    @property
    def vector_count(self) -> int:
        """Number of vectors in the index."""
        return self._vector_count

    @abstractmethod
    def train(self, vectors: np.ndarray) -> bool:
        """Train the index on a set of vectors.

        Some index types (IVF, PQ) require training before adding vectors.
        Flat and HNSW may not require training.

        Args:
            vectors: Training vectors of shape (N, D)

        Returns:
            True if training was successful.
        """
        pass

    @abstractmethod
    def add(self, vectors: np.ndarray, ids: np.ndarray) -> int:
        """Add vectors to the index.

        Args:
            vectors: Vectors to add of shape (N, D)
            ids: Vector IDs of shape (N,)

        Returns:
            Number of vectors added.
        """
        pass

    @abstractmethod
    def search(self, query_vector: np.ndarray, top_k: int) -> List[Tuple[int, float]]:
        """Search for the nearest neighbors of a query vector.

        Args:
            query_vector: Query vector of shape (D,)
            top_k: Number of nearest neighbors to return

        Returns:
            List of (id, distance) tuples sorted by distance (ascending).
        """
        pass

    @abstractmethod
    def delete(self, ids: List[int]) -> int:
        """Delete vectors from the index by their IDs.

        Args:
            ids: List of vector IDs to delete

        Returns:
            Number of vectors deleted.
        """
        pass

    @abstractmethod
    def get(self, id: int) -> Optional[np.ndarray]:
        """Get a vector by its ID.

        Args:
            id: The vector ID

        Returns:
            The vector if found, None otherwise.
        """
        pass

    @abstractmethod
    def size(self) -> int:
        """Get the number of vectors in the index.

        Returns:
            Number of vectors.
        """
        pass

    @abstractmethod
    def save(self, path: str) -> bool:
        """Save the index to disk.

        Args:
            path: Directory path to save to

        Returns:
            True if successful.
        """
        pass

    @abstractmethod
    def load(self, path: str) -> bool:
        """Load the index from disk.

        Args:
            path: Directory path to load from

        Returns:
            True if successful.
        """
        pass

    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """Get the current status of the index.

        Returns:
            Dictionary with status information.
        """
        pass

    def normalize_vector(self, vector: np.ndarray) -> np.ndarray:
        """Normalize a vector if required by the metric.

        Args:
            vector: Input vector

        Returns:
            Normalized vector.
        """
        return self.distance_metric.normalize_vector(vector)

    def normalize_vectors(self, vectors: np.ndarray) -> np.ndarray:
        """Normalize multiple vectors if required by the metric.

        Args:
            vectors: Input vectors of shape (N, D)

        Returns:
            Normalized vectors.
        """
        return self.distance_metric.normalize_vectors(vectors)

    def _check_vector(self, vector: np.ndarray):
        """Validate that a vector has the correct dimension.

        Args:
            vector: Input vector

        Raises:
            ValueError: If the vector dimension is incorrect.
        """
        if vector.shape[-1] != self.dimension:
            raise ValueError(
                f"Vector dimension {vector.shape[-1]} does not match "
                f"index dimension {self.dimension}"
            )

    def _check_vectors(self, vectors: np.ndarray):
        """Validate that a set of vectors have the correct dimension.

        Args:
            vectors: Input vectors of shape (N, D)

        Raises:
            ValueError: If the vector dimension is incorrect.
        """
        if vectors.shape[1] != self.dimension:
            raise ValueError(
                f"Vector dimension {vectors.shape[1]} does not match "
                f"index dimension {self.dimension}"
            )