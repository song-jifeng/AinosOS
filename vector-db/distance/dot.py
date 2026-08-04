"""
Dot product (inner product) metric.

dot(a, b) = sum(a_i * b_i)

For search purposes, we use negative dot product as distance,
since higher dot product = more similar, and we minimize distance.
"""

import numpy as np
from typing import Optional


def dot_product(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute dot product between two vectors.

    Args:
        a: First vector (1D) or matrix (2D)
        b: Second vector (1D)

    Returns:
        Dot product value(s).
    """
    if a.ndim == 1:
        return np.dot(a, b)
    # Matrix multiplication for 2D
    return np.dot(a, b)


def dot_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute dot-product distance (negative dot product).

    Since we want to search for the most similar vectors (highest dot product),
    we convert to a distance by negating the dot product.

    Args:
        a: First vector (1D) or matrix (2D)
        b: Second vector (1D)

    Returns:
        Negative dot product value(s). Lower = more similar.
    """
    return -dot_product(a, b)


def dot_pairwise_distance(matrix_a: np.ndarray, matrix_b: np.ndarray) -> np.ndarray:
    """Compute pairwise dot distances between two sets of vectors.

    Args:
        matrix_a: Matrix of shape (N, D)
        matrix_b: Matrix of shape (M, D)

    Returns:
        Distance matrix of shape (N, M). Lower = more similar.
    """
    return -np.dot(matrix_a, matrix_b.T)


def cosine_from_dot(a: np.ndarray, b: np.ndarray,
                    a_norm: Optional[float] = None,
                    b_norm: Optional[float] = None) -> np.ndarray:
    """Compute cosine similarity from dot product and precomputed norms.

    This is useful when norms are already computed for efficiency.

    Args:
        a: First vector (1D) or matrix (2D)
        b: Second vector (1D)
        a_norm: Precomputed norm of a. If None, computed on the fly.
        b_norm: Precomputed norm of b. If None, computed on the fly.

    Returns:
        Cosine similarity value(s).
    """
    dot = dot_product(a, b)
    if a_norm is None:
        a_norm = np.linalg.norm(a, axis=-1)
    if b_norm is None:
        b_norm = np.linalg.norm(b)
    return dot / np.maximum(a_norm * b_norm, 1e-12)