"""
Cosine similarity metric.

cos_sim(a, b) = (a . b) / (||a|| * ||b||)
Cosine distance = 1 - cos_sim
"""

import numpy as np
from typing import Optional


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between two vectors.

    Args:
        a: First vector (1D) or matrix (2D)
        b: Second vector (1D)

    Returns:
        Cosine similarity score(s). Range: [-1, 1].
    """
    # Normalize vectors to unit length
    a_norm = a / np.maximum(np.linalg.norm(a, axis=-1, keepdims=True), 1e-12)
    b_norm = b / np.maximum(np.linalg.norm(b, axis=-1, keepdims=True), 1e-12)

    if a_norm.ndim == 1:
        return np.dot(a_norm, b_norm)
    return np.dot(a_norm, b_norm)


def cosine_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute cosine distance between two vectors.

    Cosine distance = 1 - cosine_similarity

    Args:
        a: First vector (1D) or matrix (2D)
        b: Second vector (1D)

    Returns:
        Cosine distance value(s). Range: [0, 2].
    """
    return 1.0 - cosine_similarity(a, b)


def cosine_pairwise_distance(matrix_a: np.ndarray, matrix_b: np.ndarray) -> np.ndarray:
    """Compute pairwise cosine distances between two sets of vectors.

    Args:
        matrix_a: Matrix of shape (N, D)
        matrix_b: Matrix of shape (M, D)

    Returns:
        Distance matrix of shape (N, M).
    """
    a_norm = matrix_a / np.maximum(np.linalg.norm(matrix_a, axis=1, keepdims=True), 1e-12)
    b_norm = matrix_b / np.maximum(np.linalg.norm(matrix_b, axis=1, keepdims=True), 1e-12)
    similarity = np.dot(a_norm, b_norm.T)
    return 1.0 - np.clip(similarity, -1.0, 1.0)