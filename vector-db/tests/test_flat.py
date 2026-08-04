"""
Tests for the Flat index.

Tests cover:
- Basic creation and training
- Insert and search
- Delete and get
- Persistence (save/load)
- Edge cases
"""

import pytest
import numpy as np
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from index.flat import FlatIndex
from utils.config import IndexConfig, IndexType, MetricType


class TestFlatIndex:
    """Tests for FlatIndex."""

    @pytest.fixture
    def config(self):
        return IndexConfig(
            name="test_flat",
            dimension=128,
            index_type=IndexType.FLAT,
            metric=MetricType.COSINE,
        )

    @pytest.fixture
    def index(self, config):
        idx = FlatIndex(config)
        idx.train(np.empty((0, 128)))
        return idx

    @pytest.fixture
    def vectors(self):
        rng = np.random.RandomState(42)
        vecs = rng.randn(100, 128).astype(np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.maximum(norms, 1e-12)

    def test_create(self, index):
        """Test index creation."""
        assert index.name == "test_flat"
        assert index.dimension == 128
        assert index.is_trained
        assert index.size() == 0

    def test_add_vectors(self, index, vectors):
        """Test adding vectors."""
        ids = np.arange(50, dtype=np.int64)
        count = index.add(vectors[:50], ids)
        assert count == 50
        assert index.size() == 50

    def test_add_with_duplicates(self, index, vectors):
        """Test adding with duplicate IDs (should still work)."""
        ids = np.arange(10, dtype=np.int64)
        index.add(vectors[:10], ids)
        index.add(vectors[10:20], ids)  # Same IDs
        assert index.size() == 20  # Duplicate IDs are allowed

    def test_search_exact(self, index, vectors):
        """Test that search finds the exact vector."""
        ids = np.arange(100, dtype=np.int64)
        index.add(vectors, ids)

        # Search for the first vector
        results = index.search(vectors[0], 5)
        assert len(results) > 0
        assert results[0][0] == 0  # First result should be ID 0
        assert np.isclose(results[0][1], 0.0, atol=1e-5)  # Distance should be ~0

    def test_search_top_k(self, index, vectors):
        """Test that search returns correct number of results."""
        ids = np.arange(100, dtype=np.int64)
        index.add(vectors, ids)

        for k in [1, 3, 5, 10, 20]:
            results = index.search(vectors[0], k)
            assert len(results) == k, f"Expected {k} results, got {len(results)}"

    def test_search_sorted(self, index, vectors):
        """Test that search results are sorted by distance."""
        ids = np.arange(100, dtype=np.int64)
        index.add(vectors, ids)

        results = index.search(vectors[0], 10)
        distances = [r[1] for r in results]
        for i in range(len(distances) - 1):
            assert distances[i] <= distances[i + 1] + 1e-6

    def test_search_euclidean(self, vectors):
        """Test search with Euclidean distance."""
        config = IndexConfig(
            name="test_euclidean",
            dimension=128,
            metric=MetricType.EUCLIDEAN,
        )
        idx = FlatIndex(config)
        idx.train(np.empty((0, 128)))
        ids = np.arange(100, dtype=np.int64)
        idx.add(vectors, ids)

        results = idx.search(vectors[0], 5)
        assert len(results) == 5
        assert results[0][0] == 0  # Closest to itself

    def test_search_dot(self, vectors):
        """Test search with dot product distance."""
        config = IndexConfig(
            name="test_dot",
            dimension=128,
            metric=MetricType.DOT,
        )
        idx = FlatIndex(config)
        idx.train(np.empty((0, 128)))
        ids = np.arange(100, dtype=np.int64)
        idx.add(vectors, ids)

        results = idx.search(vectors[0], 5)
        assert len(results) == 5

    def test_search_manhattan(self, vectors):
        """Test search with Manhattan distance."""
        config = IndexConfig(
            name="test_manhattan",
            dimension=128,
            metric=MetricType.MANHATTAN,
        )
        idx = FlatIndex(config)
        idx.train(np.empty((0, 128)))
        ids = np.arange(100, dtype=np.int64)
        idx.add(vectors, ids)

        results = idx.search(vectors[0], 5)
        assert len(results) == 5

    def test_delete(self, index, vectors):
        """Test deleting vectors."""
        ids = np.arange(100, dtype=np.int64)
        index.add(vectors, ids)

        count = index.delete([0, 1, 2])
        assert count == 3
        assert index.size() == 97

        # Deleted vector should not appear in results
        results = index.search(vectors[3], 10)
        result_ids = {r[0] for r in results}
        assert 0 not in result_ids

    def test_delete_nonexistent(self, index, vectors):
        """Test deleting nonexistent IDs."""
        ids = np.arange(10, dtype=np.int64)
        index.add(vectors[:10], ids)

        count = index.delete([999, 1000])
        assert count == 0

    def test_get(self, index, vectors):
        """Test getting a vector by ID."""
        ids = np.arange(100, dtype=np.int64)
        index.add(vectors, ids)

        vec = index.get(42)
        assert vec is not None
        assert np.allclose(vec, vectors[42])

    def test_get_nonexistent(self, index, vectors):
        """Test getting a nonexistent vector."""
        ids = np.arange(10, dtype=np.int64)
        index.add(vectors[:10], ids)

        vec = index.get(999)
        assert vec is None

    def test_empty_search(self, index, vectors):
        """Test searching an empty index."""
        results = index.search(vectors[0], 5)
        assert len(results) == 0

    def test_save_load(self, index, vectors):
        """Test saving and loading the index."""
        ids = np.arange(100, dtype=np.int64)
        index.add(vectors, ids)

        # Save
        with tempfile.TemporaryDirectory() as tmpdir:
            save_dir = os.path.join(tmpdir, "flat_index")
            assert index.save(save_dir)

            # Load into new index
            config = IndexConfig(
                name="test_flat",
                dimension=128,
                metric=MetricType.COSINE,
            )
            new_idx = FlatIndex(config)
            assert new_idx.load(save_dir)

            # Check that search works
            results = new_idx.search(vectors[0], 5)
            assert len(results) == 5
            assert results[0][0] == 0

    def test_get_status(self, index, vectors):
        """Test status reporting."""
        ids = np.arange(50, dtype=np.int64)
        index.add(vectors[:50], ids)

        status = index.get_status()
        assert status['type'] == 'flat'
        assert status['size'] == 50
        assert status['dimension'] == 128
        assert status['metric'] == 'cosine'

    def test_large_insert(self, index):
        """Test inserting a large number of vectors."""
        rng = np.random.RandomState(123)
        big_vectors = rng.randn(1000, 128).astype(np.float32)
        norms = np.linalg.norm(big_vectors, axis=1, keepdims=True)
        big_vectors = big_vectors / norms
        ids = np.arange(1000, dtype=np.int64)

        count = index.add(big_vectors, ids)
        assert count == 1000
        assert index.size() == 1000

        # Search should still work
        results = index.search(big_vectors[500], 10)
        assert len(results) == 10

    def test_multiple_adds(self, index, vectors):
        """Test adding vectors in multiple batches."""
        ids1 = np.arange(0, 30, dtype=np.int64)
        ids2 = np.arange(30, 60, dtype=np.int64)
        ids3 = np.arange(60, 100, dtype=np.int64)

        index.add(vectors[:30], ids1)
        assert index.size() == 30

        index.add(vectors[30:60], ids2)
        assert index.size() == 60

        index.add(vectors[60:100], ids3)
        assert index.size() == 100

        # Search should work across all batches
        results = index.search(vectors[50], 5)
        assert len(results) == 5


class TestFlatIndexEdgeCases:
    """Edge case tests for FlatIndex."""

    def test_single_vector(self):
        """Test with a single vector."""
        config = IndexConfig(name="single", dimension=4, metric=MetricType.EUCLIDEAN)
        idx = FlatIndex(config)
        idx.train(np.empty((0, 4)))

        vec = np.array([[1.0, 2.0, 3.0, 4.0]], dtype=np.float32)
        idx.add(vec, np.array([42]))
        assert idx.size() == 1

        results = idx.search(vec[0], 1)
        assert len(results) == 1
        assert results[0][0] == 42

    def test_high_precision(self):
        """Test with float64 precision."""
        config = IndexConfig(name="precision", dimension=3, metric=MetricType.EUCLIDEAN)
        idx = FlatIndex(config)
        idx.train(np.empty((0, 3)))

        vec = np.array([[1.0, 2.0, 3.0]], dtype=np.float64)
        idx.add(vec, np.array([1]))
        results = idx.search(vec[0], 1)
        assert len(results) == 1
        assert np.isclose(results[0][1], 0.0, atol=1e-10)

    def test_wrong_dimension(self):
        """Test that wrong dimension raises error."""
        config = IndexConfig(name="dim_check", dimension=128, metric=MetricType.COSINE)
        idx = FlatIndex(config)
        idx.train(np.empty((0, 128)))

        with pytest.raises(ValueError):
            idx.add(np.random.randn(3, 64).astype(np.float32), np.array([1, 2, 3]))

    def test_extreme_values(self):
        """Test with extreme values (should not overflow)."""
        config = IndexConfig(name="extreme", dimension=4, metric=MetricType.EUCLIDEAN)
        idx = FlatIndex(config)
        idx.train(np.empty((0, 4)))

        vec = np.array([[1e10, 1e10, 1e10, 1e10]], dtype=np.float32)
        idx.add(vec, np.array([1]))
        results = idx.search(vec[0], 1)
        assert len(results) == 1

    def test_many_deletes(self, index, vectors):
        """Test deleting many vectors."""
        ids = np.arange(100, dtype=np.int64)
        index.add(vectors, ids)

        # Delete all even IDs
        even_ids = list(range(0, 100, 2))
        count = index.delete(even_ids)
        assert count == 50
        assert index.size() == 50

        # Verify no even IDs in results
        results = index.search(vectors[1], 50)
        result_ids = {r[0] for r in results}
        for eid in even_ids:
            assert eid not in result_ids