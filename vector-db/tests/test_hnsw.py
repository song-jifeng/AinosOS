"""
Tests for the HNSW index.

Tests cover:
- Basic creation and configuration
- Vector insertion
- Approximate nearest neighbor search
- Delete operations
- Persistence
- Parameter variations
"""

import pytest
import numpy as np
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from index.hnsw import HNSWIndex
from utils.config import IndexConfig, IndexType, MetricType


class TestHNSWIndex:
    """Tests for HNSWIndex."""

    @pytest.fixture
    def config(self):
        return IndexConfig(
            name="test_hnsw",
            dimension=64,
            index_type=IndexType.HNSW,
            metric=MetricType.COSINE,
            M=8,
            ef_construction=100,
            ef_search=50,
        )

    @pytest.fixture
    def index(self, config):
        idx = HNSWIndex(config)
        idx.train(np.empty((0, 64)))
        return idx

    @pytest.fixture
    def vectors(self):
        rng = np.random.RandomState(42)
        vecs = rng.randn(200, 64).astype(np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.maximum(norms, 1e-12)

    def test_create(self, index):
        """Test HNSW index creation."""
        assert index.name == "test_hnsw"
        assert index.dimension == 64
        assert index.M == 8
        assert index.ef_construction == 100
        assert index.ef_search == 50
        assert index.is_trained
        assert index.size() == 0

    def test_add_vectors(self, index, vectors):
        """Test adding vectors to HNSW."""
        ids = np.arange(100, dtype=np.int64)
        count = index.add(vectors[:100], ids)
        assert count == 100
        assert index.size() == 100

    def test_search_returns_results(self, index, vectors):
        """Test that search returns results."""
        ids = np.arange(200, dtype=np.int64)
        index.add(vectors, ids)

        results = index.search(vectors[0], 5)
        assert len(results) > 0
        # First result should be very close to the query
        assert results[0][1] < 0.1

    def test_search_top_k(self, index, vectors):
        """Test that search returns correct number of results."""
        ids = np.arange(200, dtype=np.int64)
        index.add(vectors, ids)

        for k in [1, 5, 10]:
            results = index.search(vectors[0], k)
            assert len(results) == k, f"Expected {k} results, got {len(results)}"

    def test_search_sorted(self, index, vectors):
        """Test that HNSW results are sorted by distance."""
        ids = np.arange(200, dtype=np.int64)
        index.add(vectors, ids)

        results = index.search(vectors[0], 10)
        distances = [r[1] for r in results]
        for i in range(len(distances) - 1):
            assert distances[i] <= distances[i + 1] + 1e-6

    def test_search_approximate_accuracy(self, index, vectors):
        """Test that HNSW provides reasonable accuracy vs brute force."""
        from index.flat import FlatIndex

        flat_config = IndexConfig(
            name="flat_ref",
            dimension=64,
            metric=MetricType.COSINE,
        )
        flat = FlatIndex(flat_config)
        flat.train(np.empty((0, 64)))

        ids = np.arange(200, dtype=np.int64)
        index.add(vectors, ids)
        flat.add(vectors, ids)

        # Compare top-10 results
        query = vectors[0]
        hnsw_results = index.search(query, 10)
        flat_results = flat.search(query, 10)

        hnsw_ids = {r[0] for r in hnsw_results}
        flat_ids = {r[0] for r in flat_results}

        # Should have at least 50% overlap
        overlap = len(hnsw_ids & flat_ids)
        assert overlap >= 5, f"Only {overlap}/10 overlap with brute force"

    def test_delete(self, index, vectors):
        """Test deleting vectors from HNSW."""
        ids = np.arange(200, dtype=np.int64)
        index.add(vectors, ids)

        count = index.delete([0, 1, 2])
        assert count == 3
        assert index.size() == 197

        # Verify deleted IDs are gone
        results = index.search(vectors[5], 10)
        result_ids = {r[0] for r in results}
        assert 0 not in result_ids

    def test_get(self, index, vectors):
        """Test getting a vector by ID."""
        ids = np.arange(200, dtype=np.int64)
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

    def test_empty_search(self, index):
        """Test searching an empty index."""
        query = np.random.randn(64).astype(np.float32)
        query = query / np.linalg.norm(query)
        results = index.search(query, 5)
        assert len(results) == 0

    def test_save_load(self, index, vectors):
        """Test saving and loading HNSW index."""
        ids = np.arange(100, dtype=np.int64)
        index.add(vectors[:100], ids)

        with tempfile.TemporaryDirectory() as tmpdir:
            save_dir = os.path.join(tmpdir, "hnsw_index")
            assert index.save(save_dir)

            # Load into new index
            config = IndexConfig(
                name="test_hnsw",
                dimension=64,
                index_type=IndexType.HNSW,
                metric=MetricType.COSINE,
                M=8,
                ef_construction=100,
                ef_search=50,
            )
            new_idx = HNSWIndex(config)
            assert new_idx.load(save_dir)

            # Verify search works
            results = new_idx.search(vectors[0], 5)
            assert len(results) > 0

    def test_get_status(self, index, vectors):
        """Test status reporting."""
        ids = np.arange(50, dtype=np.int64)
        index.add(vectors[:50], ids)

        status = index.get_status()
        assert status['type'] == 'hnsw'
        assert status['size'] == 50
        assert status['dimension'] == 64
        assert 'graph_stats' in status
        assert status['parameters']['M'] == 8

    def test_search_with_different_ef(self, vectors):
        """Test search with different ef_search values."""
        for ef in [10, 50, 100]:
            config = IndexConfig(
                name=f"hnsw_ef{ef}",
                dimension=64,
                index_type=IndexType.HNSW,
                metric=MetricType.COSINE,
                M=8,
                ef_construction=100,
                ef_search=ef,
            )
            idx = HNSWIndex(config)
            idx.train(np.empty((0, 64)))
            ids = np.arange(100, dtype=np.int64)
            idx.add(vectors[:100], ids)

            results = idx.search(vectors[0], 10)
            assert len(results) == 10

    def test_euclidean_metric(self, vectors):
        """Test HNSW with Euclidean distance."""
        config = IndexConfig(
            name="hnsw_euclidean",
            dimension=64,
            index_type=IndexType.HNSW,
            metric=MetricType.EUCLIDEAN,
            M=8,
            ef_construction=100,
            ef_search=50,
        )
        idx = HNSWIndex(config)
        idx.train(np.empty((0, 64)))
        ids = np.arange(100, dtype=np.int64)
        idx.add(vectors[:100], ids)

        results = idx.search(vectors[0], 5)
        assert len(results) == 5
        assert results[0][0] == 0  # Closest to itself

    def test_different_m_param(self, vectors):
        """Test HNSW with different M values."""
        for M in [4, 8, 16]:
            config = IndexConfig(
                name=f"hnsw_m{M}",
                dimension=64,
                index_type=IndexType.HNSW,
                metric=MetricType.COSINE,
                M=M,
                ef_construction=100,
                ef_search=50,
            )
            idx = HNSWIndex(config)
            idx.train(np.empty((0, 64)))
            ids = np.arange(50, dtype=np.int64)
            idx.add(vectors[:50], ids)

            results = idx.search(vectors[0], 5)
            assert len(results) == 5

    def test_large_insert(self):
        """Test inserting many vectors."""
        config = IndexConfig(
            name="hnsw_large",
            dimension=32,
            index_type=IndexType.HNSW,
            metric=MetricType.EUCLIDEAN,
            M=8,
            ef_construction=50,
            ef_search=50,
        )
        idx = HNSWIndex(config)
        idx.train(np.empty((0, 32)))

        rng = np.random.RandomState(42)
        vectors = rng.randn(500, 32).astype(np.float32)
        ids = np.arange(500, dtype=np.int64)

        count = idx.add(vectors, ids)
        assert count == 500

        # Verify search
        results = idx.search(vectors[0], 10)
        assert len(results) == 10


class TestHNSWEdgeCases:
    """Edge case tests for HNSWIndex."""

    def test_single_vector(self):
        """Test HNSW with a single vector."""
        config = IndexConfig(
            name="single",
            dimension=4,
            index_type=IndexType.HNSW,
            metric=MetricType.EUCLIDEAN,
            M=4,
            ef_construction=10,
            ef_search=10,
        )
        idx = HNSWIndex(config)
        idx.train(np.empty((0, 4)))

        vec = np.array([[1.0, 2.0, 3.0, 4.0]], dtype=np.float32)
        idx.add(vec, np.array([42]))
        assert idx.size() == 1

        results = idx.search(vec[0], 1)
        assert len(results) == 1
        assert results[0][0] == 42

    def test_identical_vectors(self):
        """Test adding identical vectors."""
        config = IndexConfig(
            name="identical",
            dimension=4,
            index_type=IndexType.HNSW,
            metric=MetricType.EUCLIDEAN,
            M=4,
            ef_construction=10,
            ef_search=10,
        )
        idx = HNSWIndex(config)
        idx.train(np.empty((0, 4)))

        vec = np.array([[1.0, 1.0, 1.0, 1.0]], dtype=np.float32)
        vecs = np.repeat(vec, 10, axis=0)
        ids = np.arange(10, dtype=np.int64)

        idx.add(vecs, ids)
        assert idx.size() == 10

        results = idx.search(vec[0], 5)
        assert len(results) == 5

    def test_wrong_dimension(self):
        """Test that wrong dimension raises error."""
        config = IndexConfig(
            name="dim_check",
            dimension=64,
            index_type=IndexType.HNSW,
            metric=MetricType.COSINE,
        )
        idx = HNSWIndex(config)
        idx.train(np.empty((0, 64)))

        with pytest.raises(ValueError):
            idx.add(np.random.randn(3, 32).astype(np.float32), np.array([1, 2, 3]))