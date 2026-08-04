"""
Manhattan (L1) distance metric.

d(a, b) = sum(|a_i - b_i|)
"""

import numpy as np
from typing import Optional


def manhattan_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute Manhattan (L1) distance between two vectors.

    Args:
        a: First vector (1D) or matrix (2D)
        b: Second vector (1D)

    Returns:
        Manhattan distance(s). Always non-negative.
    """
    if a.ndim == 1:
        return np.sum(np.abs(a - b))
    else:
        return np.sum(np.abs(a - b), axis=1)


def manhattan_pairwise_distance(matrix_a: np.ndarray, matrix_b: np.ndarray) -> np.ndarray:
    """Compute pairwise Manhattan distances between two sets of vectors.

    Uses broadcasting to compute distances efficiently.

    Args:
        matrix_a: Matrix of shape (N, D)
        matrix_b: Matrix of shape (M, D)

    Returns:
        Distance matrix of shape (N, M).
    """
    # Expand dimensions for broadcasting
    a_expanded = matrix_a[:, np.newaxis, :]  # (N, 1, D)
    b_expanded = matrix_b[np.newaxis, :, :]  # (1, M, D)
    return np.sum(np.abs(a_expanded - b_expanded), axis=2)


def manhattan_median_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute median absolute deviation (robust L1 variant).

    Uses median instead of mean, making it more robust to outliers.

    Args:
        a: First vector (1D) or matrix (2D)
        b: Second vector (1D)

    Returns:
        Median Manhattan distance(s).
    """
    if a.ndim == 1:
        return np.median(np.abs(a - b))
    else:
        return np.median(np.abs(a - b), axis=1)


def weighted_manhattan_distance(a: np.ndarray, b: np.ndarray,
                                 weights: np.ndarray) -> np.ndarray:
    """Compute weighted Manhattan distance.

    d(a, b) = sum(w_i * |a_i - b_i|)

    Args:
        a: First vector (1D) or matrix (2D)
        b: Second vector (1D)
        weights: Weight vector of same length as a/b

    Returns:
        Weighted Manhattan distance(s).
    """
    if a.ndim == 1:
        return np.sum(weights * np.abs(a - b))
    else:
        return np.sum(weights * np.abs(a - b), axis=1)