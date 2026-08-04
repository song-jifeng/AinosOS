"""
Tests for distance metric functions.

Tests cover:
- Cosine similarity/distance
- Euclidean distance
- Dot product
- Manhattan distance
- Edge cases (zero vectors, identical vectors, etc.)
"""

import pytest
import numpy as np
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from distance import (
    cosine_similarity, cosine_distance, cosine_pairwise,
    euclidean_distance, euclidean_pairwise,
    dot_product, dot_distance, dot_pairwise,
    manhattan_distance, manhattan_pairwise,
    DistanceMetric
)
from utils.config import MetricType


class TestCosineDistance:
    """Tests for cosine similarity/distance functions."""

    def test_cosine_similarity_identical(self):
        """Test cosine similarity of identical vectors."""
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([1.0, 0.0, 0.0])
        sim = cosine_similarity(a, b)
        assert np.isclose(sim, 1.0), f"Expected 1.0, got {sim}"

    def test_cosine_similarity_orthogonal(self):
        """Test cosine similarity of orthogonal vectors."""
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])
        sim = cosine_similarity(a, b)
        assert np.isclose(sim, 0.0), f"Expected 0.0, got {sim}"

    def test_cosine_similarity_opposite(self):
        """Test cosine similarity of opposite vectors."""
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([-1.0, 0.0, 0.0])
        sim = cosine_similarity(a, b)
        assert np.isclose(sim, -1.0), f"Expected -1.0, got {sim}"

    def test_cosine_similarity_partial(self):
        """Test cosine similarity of partially aligned vectors."""
        a = np.array([1.0, 1.0, 0.0])
        b = np.array([1.0, 0.0, 0.0])
        # a normalized = [0.707, 0.707, 0]
        # b normalized = [1, 0, 0]
        # dot = 0.707
        sim = cosine_similarity(a, b)
        assert np.isclose(sim, np.sqrt(2) / 2, atol=1e-6), f"Got {sim}"

    def test_cosine_distance(self):
        """Test cosine distance = 1 - similarity."""
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])
        dist = cosine_distance(a, b)
        assert np.isclose(dist, 1.0), f"Expected 1.0, got {dist}"

    def test_cosine_distance_identical(self):
        """Test cosine distance of identical vectors."""
        a = np.array([1.0, 2.0, 3.0])
        b = np.array([1.0, 2.0, 3.0])
        dist = cosine_distance(a, b)
        assert np.isclose(dist, 0.0), f"Expected 0.0, got {dist}"

    def test_cosine_similarity_matrix(self):
        """Test cosine similarity with 2D input."""
        a = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        b = np.array([1.0, 0.0, 0.0])
        sim = cosine_similarity(a, b)
        assert len(sim) == 2
        assert np.isclose(sim[0], 1.0)
        assert np.isclose(sim[1], 0.0)

    def test_cosine_pairwise(self):
        """Test pairwise cosine distance."""
        a = np.array([[1.0, 0.0], [0.0, 1.0]])
        b = np.array([[1.0, 0.0], [0.5, 0.5], [0.0, 1.0]])
        dists = cosine_pairwise(a, b)
        assert dists.shape == (2, 3)
        # a[0] vs b[0]: identical
        assert np.isclose(dists[0, 0], 0.0, atol=1e-6)
        # a[0] vs b[2]: orthogonal
        assert np.isclose(dists[0, 2], 1.0, atol=1e-6)

    def test_cosine_zero_vector(self):
        """Test cosine similarity with zero vector (should not crash)."""
        a = np.array([0.0, 0.0, 0.0])
        b = np.array([1.0, 0.0, 0.0])
        sim = cosine_similarity(a, b)
        assert np.isfinite(sim), "Should not produce NaN"

    def test_cosine_normalized(self):
        """Test that pre-normalized vectors give same results."""
        a = np.array([0.6, 0.8])
        b = np.array([0.8, 0.6])
        sim = cosine_similarity(a, b)
        expected = 0.96  # 0.6*0.8 + 0.8*0.6 = 0.48 + 0.48 = 0.96
        assert np.isclose(sim, expected, atol=1e-6)


class TestEuclideanDistance:
    """Tests for Euclidean distance functions."""

    def test_euclidean_identical(self):
        """Test Euclidean distance of identical vectors."""
        a = np.array([1.0, 2.0, 3.0])
        b = np.array([1.0, 2.0, 3.0])
        dist = euclidean_distance(a, b)
        assert np.isclose(dist, 0.0), f"Expected 0.0, got {dist}"

    def test_euclidean_basic(self):
        """Test basic Euclidean distance computation."""
        a = np.array([0.0, 0.0, 0.0])
        b = np.array([3.0, 4.0, 0.0])
        dist = euclidean_distance(a, b)
        assert np.isclose(dist, 5.0), f"Expected 5.0, got {dist}"

    def test_euclidean_3d(self):
        """Test Euclidean distance in 3D."""
        a = np.array([1.0, 2.0, 3.0])
        b = np.array([4.0, 5.0, 6.0])
        dist = euclidean_distance(a, b)
        expected = np.sqrt(27)  # 3^2 + 3^2 + 3^2 = 27
        assert np.isclose(dist, expected), f"Expected {expected}, got {dist}"

    def test_euclidean_matrix(self):
        """Test Euclidean distance with 2D input."""
        a = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
        b = np.array([0.0, 0.0])
        dists = euclidean_distance(a, b)
        assert len(dists) == 3
        assert np.isclose(dists[0], 1.0)
        assert np.isclose(dists[1], 1.0)
        assert np.isclose(dists[2], np.sqrt(2))

    def test_euclidean_pairwise(self):
        """Test pairwise Euclidean distance."""
        a = np.array([[0.0, 0.0], [1.0, 1.0]])
        b = np.array([[0.0, 0.0], [2.0, 2.0]])
        dists = euclidean_pairwise(a, b)
        assert dists.shape == (2, 2)
        assert np.isclose(dists[0, 0], 0.0)
        assert np.isclose(dists[0, 1], np.sqrt(8))
        assert np.isclose(dists[1, 0], np.sqrt(2))

    def test_euclidean_triangle_inequality(self):
        """Test triangle inequality holds."""
        a = np.array([0.0, 0.0])
        b = np.array([3.0, 0.0])
        c = np.array([0.0, 4.0])
        d_ab = euclidean_distance(a, b)
        d_bc = euclidean_distance(b, c)
        d_ac = euclidean_distance(a, c)
        assert d_ac <= d_ab + d_bc + 1e-10


class TestDotProduct:
    """Tests for dot product functions."""

    def test_dot_product_basic(self):
        """Test basic dot product."""
        a = np.array([1.0, 2.0, 3.0])
        b = np.array([4.0, 5.0, 6.0])
        dp = dot_product(a, b)
        expected = 4 + 10 + 18
        assert np.isclose(dp, expected), f"Expected {expected}, got {dp}"

    def test_dot_product_orthogonal(self):
        """Test dot product of orthogonal vectors."""
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])
        dp = dot_product(a, b)
        assert np.isclose(dp, 0.0), f"Expected 0.0, got {dp}"

    def test_dot_product_negative(self):
        """Test dot product with negative values."""
        a = np.array([1.0, -2.0, 3.0])
        b = np.array([-4.0, 5.0, -6.0])
        dp = dot_product(a, b)
        expected = -4 + (-10) + (-18)
        assert np.isclose(dp, expected), f"Expected {expected}, got {dp}"

    def test_dot_distance(self):
        """Test dot distance = -dot product."""
        a = np.array([1.0, 2.0])
        b = np.array([3.0, 4.0])
        dist = dot_distance(a, b)
        assert np.isclose(dist, -11.0), f"Expected -11.0, got {dist}"

    def test_dot_pairwise(self):
        """Test pairwise dot distance."""
        a = np.array([[1.0, 0.0], [0.0, 1.0]])
        b = np.array([[1.0, 0.0], [1.0, 1.0]])
        dists = dot_pairwise(a, b)
        assert dists.shape == (2, 2)
        # -[1,0].[1,0] = -1
        assert np.isclose(dists[0, 0], -1.0)
        # -[1,0].[1,1] = -1
        assert np.isclose(dists[0, 1], -1.0)

    def test_dot_product_matrix(self):
        """Test dot product with matrix input."""
        a = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
        b = np.array([1.0, 0.0])
        dps = dot_product(a, b)
        assert len(dps) == 3
        assert np.isclose(dps[0], 1.0)
        assert np.isclose(dps[1], 0.0)
        assert np.isclose(dps[2], 1.0)


class TestManhattanDistance:
    """Tests for Manhattan distance functions."""

    def test_manhattan_identical(self):
        """Test Manhattan distance of identical vectors."""
        a = np.array([1.0, 2.0, 3.0])
        b = np.array([1.0, 2.0, 3.0])
        dist = manhattan_distance(a, b)
        assert np.isclose(dist, 0.0), f"Expected 0.0, got {dist}"

    def test_manhattan_basic(self):
        """Test basic Manhattan distance."""
        a = np.array([0.0, 0.0])
        b = np.array([3.0, 4.0])
        dist = manhattan_distance(a, b)
        assert np.isclose(dist, 7.0), f"Expected 7.0, got {dist}"

    def test_manhattan_3d(self):
        """Test Manhattan distance in 3D."""
        a = np.array([1.0, 2.0, 3.0])
        b = np.array([4.0, 5.0, 6.0])
        dist = manhattan_distance(a, b)
        assert np.isclose(dist, 9.0), f"Expected 9.0, got {dist}"

    def test_manhattan_matrix(self):
        """Test Manhattan distance with 2D input."""
        a = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
        b = np.array([0.0, 0.0])
        dists = manhattan_distance(a, b)
        assert len(dists) == 3
        assert np.isclose(dists[0], 1.0)
        assert np.isclose(dists[1], 1.0)
        assert np.isclose(dists[2], 2.0)

    def test_manhattan_pairwise(self):
        """Test pairwise Manhattan distance."""
        a = np.array([[0.0, 0.0], [1.0, 1.0]])
        b = np.array([[0.0, 0.0], [2.0, 2.0]])
        dists = manhattan_pairwise(a, b)
        assert dists.shape == (2, 2)
        assert np.isclose(dists[0, 0], 0.0)
        assert np.isclose(dists[0, 1], 4.0)
        assert np.isclose(dists[1, 0], 2.0)

    def test_manhattan_properties(self):
        """Test metric properties of Manhattan distance."""
        a = np.array([1.0, 2.0])
        b = np.array([3.0, 5.0])
        c = np.array([6.0, 7.0])

        # Non-negativity
        d_ab = manhattan_distance(a, b)
        assert d_ab >= 0

        # Symmetry
        d_ba = manhattan_distance(b, a)
        assert np.isclose(d_ab, d_ba)

        # Triangle inequality
        d_ac = manhattan_distance(a, c)
        d_bc = manhattan_distance(b, c)
        assert d_ac <= d_ab + d_bc + 1e-10


class TestDistanceMetric:
    """Tests for the DistanceMetric wrapper class."""

    def test_metric_creation_cosine(self):
        """Test creating a cosine metric."""
        metric = DistanceMetric(MetricType.COSINE)
        assert metric.name == "cosine"

    def test_metric_creation_euclidean(self):
        """Test creating an Euclidean metric."""
        metric = DistanceMetric(MetricType.EUCLIDEAN)
        assert metric.name == "euclidean"

    def test_metric_creation_dot(self):
        """Test creating a dot product metric."""
        metric = DistanceMetric(MetricType.DOT)
        assert metric.name == "dot"

    def test_metric_creation_manhattan(self):
        """Test creating a Manhattan metric."""
        metric = DistanceMetric(MetricType.MANHATTAN)
        assert metric.name == "manhattan"

    def test_metric_compute(self):
        """Test metric computation."""
        metric = DistanceMetric(MetricType.EUCLIDEAN)
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        dist = metric.compute(a, b)
        assert np.isclose(dist, np.sqrt(2))

    def test_metric_normalize(self):
        """Test vector normalization."""
        metric = DistanceMetric(MetricType.COSINE)
        vector = np.array([3.0, 4.0])
        normalized = metric.normalize_vector(vector)
        expected_norm = np.linalg.norm(normalized)
        assert np.isclose(expected_norm, 1.0)
        assert np.isclose(normalized[0], 0.6)
        assert np.isclose(normalized[1], 0.8)

    def test_metric_no_normalize(self):
        """Test that Euclidean metric doesn't normalize."""
        metric = DistanceMetric(MetricType.EUCLIDEAN)
        vector = np.array([3.0, 4.0])
        normalized = metric.normalize_vector(vector)
        assert np.array_equal(normalized, vector)  # No change

    def test_metric_normalize_vectors(self):
        """Test normalizing multiple vectors."""
        metric = DistanceMetric(MetricType.COSINE)
        vectors = np.array([[3.0, 4.0], [1.0, 0.0]])
        normalized = metric.normalize_vectors(vectors)
        assert normalized.shape == (2, 2)
        norms = np.linalg.norm(normalized, axis=1)
        assert np.allclose(norms, 1.0)

    def test_metric_pairwise(self):
        """Test pairwise distance computation."""
        metric = DistanceMetric(MetricType.EUCLIDEAN)
        a = np.array([[0.0, 0.0], [1.0, 1.0]])
        b = np.array([[0.0, 0.0], [2.0, 2.0]])
        dists = metric.compute_pairwise(a, b)
        assert dists.shape == (2, 2)


class TestEdgeCases:
    """Tests for edge cases in distance computations."""

    def test_zero_vector(self):
        """Test behavior with zero vectors."""
        a = np.zeros(128)
        b = np.ones(128)
        # Should not crash or produce NaN
        d = cosine_distance(a, b)
        assert np.isfinite(d)

    def test_single_element(self):
        """Test with single-element vectors."""
        a = np.array([5.0])
        b = np.array([3.0])
        assert np.isclose(euclidean_distance(a, b), 2.0)
        assert np.isclose(manhattan_distance(a, b), 2.0)
        assert np.isclose(dot_product(a, b), 15.0)

    def test_high_dimensional(self):
        """Test with high-dimensional vectors (should not overflow)."""
        a = np.random.randn(1000).astype(np.float32)
        b = np.random.randn(1000).astype(np.float32)
        d = euclidean_distance(a, b)
        assert np.isfinite(d)
        assert d >= 0

    def test_all_metrics_same_input(self):
        """Test all metrics with same input (should be 0 or 1)."""
        a = np.array([1.0, 2.0, 3.0])
        assert np.isclose(cosine_distance(a, a), 0.0)
        assert np.isclose(euclidean_distance(a, a), 0.0)
        assert np.isclose(manhattan_distance(a, a), 0.0)
        # dot distance = -dot(a,a) = -14
        assert np.isclose(dot_distance(a, a), -14.0)

    def test_large_batch(self):
        """Test pairwise distance with large batches."""
        a = np.random.randn(100, 64).astype(np.float32)
        b = np.random.randn(50, 64).astype(np.float32)
        dists = euclidean_pairwise(a, b)
        assert dists.shape == (100, 50)
        assert np.all(dists >= 0)

    def test_single_vector_in_batch(self):
        """Test pairwise with single vectors."""
        a = np.random.randn(1, 128).astype(np.float32)
        b = np.random.randn(1, 128).astype(np.float32)
        # Normalize for cosine
        a = a / np.linalg.norm(a)
        b = b / np.linalg.norm(b)
        dists = cosine_pairwise(a, b)
        assert dists.shape == (1, 1)
        # Same vector should have distance 0
        dists_same = cosine_pairwise(a, a)
        assert np.isclose(dists_same[0, 0], 0.0, atol=1e-6)