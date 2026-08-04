"""
Euclidean (L2) distance metric.

d(a, b) = sqrt(sum((a_i - b_i)^2))
"""

import numpy as np
from typing import Optional


def euclidean_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute Euclidean (L2) distance between two vectors.

    Args:
        a: First vector (1D) or matrix (2D)
        b: Second vector (1D)

    Returns:
        Euclidean distance(s). Always non-negative.
    """
    if a.ndim == 1:
        return np.sqrt(np.sum((a - b) ** 2))
    else:
        return np.sqrt(np.sum((a - b) ** 2, axis=1))


def squared_euclidean_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute squared Euclidean distance between two vectors.

    Useful for avoiding the sqrt operation when only relative ordering matters.

    Args:
        a: First vector (1D) or matrix (2D)
        b: Second vector (1D)

    Returns:
        Squared Euclidean distance(s).
    """
    if a.ndim == 1:
        return np.sum((a - b) ** 2)
    else:
        return np.sum((a - b) ** 2, axis=1)


def euclidean_pairwise_distance(matrix_a: np.ndarray, matrix_b: np.ndarray) -> np.ndarray:
    """Compute pairwise Euclidean distances between two sets of vectors.

    Uses the expanded formula: ||a - b||^2 = ||a||^2 + ||b||^2 - 2*a·b

    Args:
        matrix_a: Matrix of shape (N, D)
        matrix_b: Matrix of shape (M, D)

    Returns:
        Distance matrix of shape (N, M).
    """
    a_norm = np.sum(matrix_a ** 2, axis=1, keepdims=True)
    b_norm = np.sum(matrix_b ** 2, axis=1)
    dot_product = np.dot(matrix_a, matrix_b.T)
    distances_sq = a_norm + b_norm - 2.0 * dot_product
    distances_sq = np.maximum(distances_sq, 0.0)  # Numerical stability
    return np.sqrt(distances_sq)


def normalized_euclidean_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute normalized Euclidean distance.

    Normalizes by the vector dimension to make distances comparable across
    different dimensionalities.

    Args:
        a: First vector (1D) or matrix (2D)
        b: Second vector (1D)

    Returns:
        Normalized Euclidean distance(s).
    """
    if a.ndim == 1:
        return np.sqrt(np.sum((a - b) ** 2) / len(a))
    else:
        return np.sqrt(np.sum((a - b) ** 2, axis=1) / a.shape[1])