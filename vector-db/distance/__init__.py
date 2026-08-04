"""Distance metric functions for vector similarity computation.

Provides four distance metrics:
- Cosine similarity (angular distance)
- Euclidean distance (L2)
- Dot product (inner product)
- Manhattan distance (L1)
"""

import numpy as np
from typing import Callable, Optional
from enum import Enum

from ..utils.config import MetricType


class DistanceMetric:
    """Wrapper for distance metric functions."""

    def __init__(self, metric_type: MetricType):
        self.metric_type = metric_type
        self._fn = self._get_metric_function(metric_type)

    @staticmethod
    def _get_metric_function(metric_type: MetricType) -> Callable:
        """Get the distance function for the given metric type."""
        if metric_type == MetricType.COSINE:
            return cosine_distance
        elif metric_type == MetricType.EUCLIDEAN:
            return euclidean_distance
        elif metric_type == MetricType.DOT:
            return dot_distance
        elif metric_type == MetricType.MANHATTAN:
            return manhattan_distance
        else:
            raise ValueError(f"Unknown metric type: {metric_type}")

    def compute(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """Compute distance between two vectors or sets of vectors.

        Args:
            a: First vector (1D) or matrix (2D)
            b: Second vector (1D) or matrix (2D)

        Returns:
            Distance(s). Scalar for 1D inputs, array for 2D inputs.
        """
        return self._fn(a, b)

    def compute_pairwise(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """Compute pairwise distances between two sets of vectors.

        Args:
            a: Matrix of shape (N, D)
            b: Matrix of shape (M, D)

        Returns:
            Matrix of shape (N, M) with pairwise distances.
        """
        if self.metric_type == MetricType.COSINE:
            return cosine_pairwise(a, b)
        elif self.metric_type == MetricType.EUCLIDEAN:
            return euclidean_pairwise(a, b)
        elif self.metric_type == MetricType.DOT:
            return dot_pairwise(a, b)
        elif self.metric_type == MetricType.MANHATTAN:
            return manhattan_pairwise(a, b)
        else:
            raise ValueError(f"Unknown metric type: {self.metric_type}")

    def normalize_vector(self, vector: np.ndarray) -> np.ndarray:
        """Normalize a vector if needed by the metric."""
        if self.metric_type == MetricType.COSINE:
            norm = np.linalg.norm(vector, axis=-1, keepdims=True)
            norm = np.where(norm == 0, 1.0, norm)
            return vector / norm
        return vector

    def normalize_vectors(self, vectors: np.ndarray) -> np.ndarray:
        """Normalize a set of vectors if needed by the metric."""
        if self.metric_type == MetricType.COSINE:
            norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
            norms = np.where(norms == 0, 1.0, norms)
            return vectors / norms
        return vectors

    @property
    def name(self) -> str:
        return self.metric_type.value

    def __repr__(self) -> str:
        return f"DistanceMetric({self.metric_type.value})"


# =============================================================================
# Cosine Similarity
# =============================================================================

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between two vectors.

    cos_sim = (a . b) / (||a|| * ||b||)

    Args:
        a: First vector (1D) or matrix (2D)
        b: Second vector (1D)

    Returns:
        Cosine similarity. Range: [-1, 1] for 1D, array for 2D.
    """
    a_norm = a / np.maximum(np.linalg.norm(a, axis=-1, keepdims=True), 1e-12)
    b_norm = b / np.maximum(np.linalg.norm(b, axis=-1, keepdims=True), 1e-12)
    return np.dot(a_norm, b_norm.T) if a_norm.ndim > 1 else np.dot(a_norm, b_norm)


def cosine_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute cosine distance (1 - cosine_similarity).

    Args:
        a: First vector (1D) or matrix (2D)
        b: Second vector (1D)

    Returns:
        Cosine distance. Range: [0, 2]
    """
    sim = cosine_similarity(a, b)
    return 1.0 - sim


def cosine_pairwise(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute pairwise cosine distances between two sets of vectors.

    Args:
        a: Matrix of shape (N, D)
        b: Matrix of shape (M, D)

    Returns:
        Matrix of shape (N, M) with pairwise cosine distances.
    """
    a_norm = a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-12)
    b_norm = b / np.maximum(np.linalg.norm(b, axis=1, keepdims=True), 1e-12)
    sim = np.dot(a_norm, b_norm.T)
    return 1.0 - np.clip(sim, -1.0, 1.0)


# =============================================================================
# Euclidean Distance (L2)
# =============================================================================

def euclidean_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute Euclidean (L2) distance between two vectors.

    d = sqrt(sum((a - b)^2))

    Args:
        a: First vector (1D) or matrix (2D)
        b: Second vector (1D)

    Returns:
        Euclidean distance. Non-negative.
    """
    if a.ndim == 1:
        return np.sqrt(np.sum((a - b) ** 2))
    else:
        return np.sqrt(np.sum((a - b) ** 2, axis=1))


def euclidean_pairwise(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute pairwise Euclidean distances between two sets of vectors.

    Uses the identity: ||a - b||^2 = ||a||^2 + ||b||^2 - 2*a.b

    Args:
        a: Matrix of shape (N, D)
        b: Matrix of shape (M, D)

    Returns:
        Matrix of shape (N, M) with pairwise Euclidean distances.
    """
    a_norm = np.sum(a ** 2, axis=1, keepdims=True)
    b_norm = np.sum(b ** 2, axis=1)
    dot = np.dot(a, b.T)
    dist_sq = a_norm + b_norm - 2.0 * dot
    dist_sq = np.maximum(dist_sq, 0.0)  # Numerical stability
    return np.sqrt(dist_sq)


# =============================================================================
# Dot Product (Inner Product)
# =============================================================================

def dot_product(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute dot product (inner product) between two vectors.

    Args:
        a: First vector (1D) or matrix (2D)
        b: Second vector (1D)

    Returns:
        Dot product.
    """
    return np.dot(a, b) if a.ndim == 1 else np.dot(a, b)


def dot_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute dot-product distance (negative dot product).

    For dot product, we want to maximize similarity, so distance = -dot(a,b).
    This allows the search to use the same distance-minimization framework.

    Args:
        a: First vector (1D) or matrix (2D)
        b: Second vector (1D)

    Returns:
        Dot distance (negative dot product).
    """
    return -dot_product(a, b)


def dot_pairwise(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute pairwise dot distances between two sets of vectors.

    Args:
        a: Matrix of shape (N, D)
        b: Matrix of shape (M, D)

    Returns:
        Matrix of shape (N, M) with pairwise dot distances.
    """
    return -np.dot(a, b.T)


# =============================================================================
# Manhattan Distance (L1)
# =============================================================================

def manhattan_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute Manhattan (L1) distance between two vectors.

    d = sum(|a - b|)

    Args:
        a: First vector (1D) or matrix (2D)
        b: Second vector (1D)

    Returns:
        Manhattan distance. Non-negative.
    """
    if a.ndim == 1:
        return np.sum(np.abs(a - b))
    else:
        return np.sum(np.abs(a - b), axis=1)


def manhattan_pairwise(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute pairwise Manhattan distances between two sets of vectors.

    Args:
        a: Matrix of shape (N, D)
        b: Matrix of shape (M, D)

    Returns:
        Matrix of shape (N, M) with pairwise Manhattan distances.
    """
    # Expand for broadcasting: a (N, 1, D), b (1, M, D)
    a_exp = a[:, np.newaxis, :]
    b_exp = b[np.newaxis, :, :]
    return np.sum(np.abs(a_exp - b_exp), axis=2)

# =============================================================================
# Utility functions
# =============================================================================

def is_metric_compatible(metric: MetricType, index_type: str) -> bool:
    """Check if a metric is compatible with an index type.

    Some index types have restrictions on which metrics they support.
    """
    # All metrics work with Flat
    if index_type == "flat":
        return True

    # HNSW works with all metrics
    if index_type == "hnsw":
        return True

    # IVF works with all metrics
    if index_type == "ivf":
        return True

    # PQ works best with Euclidean
    if index_type == "pq":
        return metric in [MetricType.EUCLIDEAN, MetricType.COSINE]

    # LSH works with cosine and Euclidean
    if index_type == "lsh":
        return metric in [MetricType.COSINE, MetricType.EUCLIDEAN, MetricType.MANHATTAN]

    # Hybrid works with all
    if index_type == "hybrid":
        return True

    return False


def get_metric_function(metric_type: MetricType) -> Callable:
    """Get the raw distance function for a metric type."""
    mapping = {
        MetricType.COSINE: cosine_distance,
        MetricType.EUCLIDEAN: euclidean_distance,
        MetricType.DOT: dot_distance,
        MetricType.MANHATTAN: manhattan_distance,
    }
    return mapping[metric_type]


def get_pairwise_function(metric_type: MetricType) -> Callable:
    """Get the pairwise distance function for a metric type."""
    mapping = {
        MetricType.COSINE: cosine_pairwise,
        MetricType.EUCLIDEAN: euclidean_pairwise,
        MetricType.DOT: dot_pairwise,
        MetricType.MANHATTAN: manhattan_pairwise,
    }
    return mapping[metric_type]


def get_similarity_metric_type(metric_type: MetricType) -> str:
    """Get whether the metric is a similarity (higher is better) or distance (lower is better)."""
    # Cosine is similarity (1 - distance), but we store as distance (1 - sim)
    # Dot is similarity (higher = more similar), but we store as -dot
    # Euclidean and Manhattan are distances (lower = better)
    return "similarity" if metric_type in [MetricType.COSINE, MetricType.DOT] else "distance"