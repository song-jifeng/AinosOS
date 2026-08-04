"""
Tests for the IVF index.

Tests cover:
- Training with k-means clustering
- Vector insertion and cluster assignment
- Approximate nearest neighbor search
- Delete operations
- Persistence
"""

import pytest
import numpy as np
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from index.ivf import IVFIndex, KMeans
from utils.config import IndexConfig, IndexType, MetricType


class TestKMeans:
    """Tests for the built-in KMeans implementation."""

    def test_kmeans_basic(self):
        """Test basic k-means clustering."""
        rng = np.random.RandomState(42)
        # Create 3 well-separated clusters
        centers = np.array([[0, 0], [10, 10], [-10, -10]], dtype=np.float32)
        vectors = []
        for center in centers:
            points = rng.randn(20, 2).astype(np.float32) * 0.5 + center
            vectors.append(points)
        vectors = np.vstack(vectors)

        kmeans = KMeans(n_clusters=3, random_seed=42)
        kmeans.fit(vectors)

        assert kmeans.centroids.shape == (3, 2)
        assert kmeans.labels is not None
        assert len(kmeans.labels) == 60

    def test_kmeans_convergence(self):
        """Test that k-means converges."""
        rng = np.random.RandomState(42)
        vectors = rng.randn(100, 10).astype(np.float32)

        kmeans = KMeans(n_clusters=5, max_iter=100, random_seed=42)
        kmeans.fit(vectors)

        assert kmeans.n_iter_ > 0
        assert kmeans.n_iter_ <= 100
        assert kmeans.inertia_ > 0

    def test_kmeans_predict(self):
        """Test k-means prediction."""
        rng = np.random.RandomState(42)
        vectors = rng.randn(100, 5).astype(np.float32)

        kmeans = KMeans(n_clusters=5, random_seed=42)
        kmeans.fit(vectors)

        new_vectors = rng.randn(10, 5).astype(np.float32)
        labels = kmeans.predict(new_vectors)
        assert len(labels) == 10
        assert all(0 <= l < 5 for l in labels)

    def test_kmeans_transform(self):
        """Test k-means distance transform."""
        rng = np.random.RandomState(42)
        vectors = rng.randn(50, 3).astype(np.float32)

        kmeans = KMeans(n_clusters=3, random_seed=42)
        kmeans.fit(vectors)

        new_vectors = rng.randn(5, 3).astype(np.float32)
        dists = kmeans.transform(new_vectors)
        assert dists.shape == (5, 3)

    def test_kmeans_fewer_clusters(self):
        """Test k-means with fewer points than clusters."""
        rng = np.random.RandomState(42)
        vectors = rng.randn(3, 5).astype(np.float32)

        kmeans = KMeans(n_clusters=10, random_seed=42)
        kmeans.fit(vectors)
        # Should handle gracefully
        assert kmeans.centroids is not None


class TestIVFIndex:
    """Tests for IVFIndex."""

    @pytest.fixture
    def config(self):
        return IndexConfig(
            name="test_ivf",
            dimension=64,
            index_type=IndexType.IVF,
            metric=MetricType.COSINE,
            nlist=5,
            nprobe=2,
        )

    @pytest.fixture
    def vectors(self):
        rng = np.random.RandomState(42)
        vecs = rng.randn(200, 64).astype(np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.maximum(norms, 1e-12)

    def test_create(self, config):
        """Test IVF index creation."""
        idx = IVFIndex(config)
        assert idx.name == "test_ivf"
        assert idx.dimension == 64
        assert idx.nlist == 5
        assert idx.nprobe == 2
        assert idx.size() == 0

    def test_train(self, config, vectors):
        """Test training the IVF index."""
        idx = IVFIndex(config)
        idx.train(vectors[:100])
        assert idx.is_trained
        assert idx._centroids is not None
        assert idx._centroids.shape[0] == 5

    def test_add_vectors(self, config, vectors):
        """Test adding vectors to IVF."""
        idx = IVFIndex(config)
        idx.train(vectors[:100])

        ids = np.arange(100, dtype=np.int64)
        count = idx.add(vectors[:100], ids)
        assert count == 100
        assert idx.size() == 100

    def test_auto_train(self, config, vectors):
        """Test that IVF auto-trains on first add."""
        idx = IVFIndex(config)
        assert not idx.is_trained

        ids = np.arange(100, dtype=np.int64)
        idx.add(vectors[:100], ids)
        assert idx.is_trained

    def test_search_returns_results(self, config, vectors):
        """Test that IVF search returns results."""
        idx = IVFIndex(config)
        ids = np.arange(200, dtype=np.int64)
        idx.add(vectors, ids)

        results = idx.search(vectors[0], 5)
        assert len(results) > 0
        # First result should be very close to the query
        assert results[0][1] < 0.1

    def test_search_top_k(self, config, vectors):
        """Test that IVF returns correct number of results."""
        idx = IVFIndex(config)
        ids = np.arange(200, dtype=np.int64)
        idx.add(vectors, ids)

        for k in [1, 5, 10]:
            results = idx.search(vectors[0], k)
            assert len(results) == k, f"Expected {k} results, got {len(results)}"

    def test_search_sorted(self, config, vectors):
        """Test that IVF results are sorted by distance."""
        idx = IVFIndex(config)
        ids = np.arange(200, dtype=np.int64)
        idx.add(vectors, ids)

        results = idx.search(vectors[0], 10)
        distances = [r[1] for r in results]
        for i in range(len(distances) - 1):
            assert distances[i] <= distances[i + 1] + 1e-6

    def test_delete(self, config, vectors):
        """Test deleting vectors from IVF."""
        idx = IVFIndex(config)
        ids = np.arange(200, dtype=np.int64)
        idx.add(vectors, ids)

        count = idx.delete([0, 1, 2])
        assert count == 3
        assert idx.size() == 197

        # Verify deleted IDs are gone
        results = idx.search(vectors[5], 10)
        result_ids = {r[0] for r in results}
        assert 0 not in result_ids

    def test_get(self, config, vectors):
        """Test getting a vector by ID."""
        idx = IVFIndex(config)
        ids = np.arange(200, dtype=np.int64)
        idx.add(vectors, ids)

        vec = idx.get(42)
        assert vec is not None
        assert np.allclose(vec, vectors[42])

    def test_get_nonexistent(self, config, vectors):
        """Test getting a nonexistent vector."""
        idx = IVFIndex(config)
        ids = np.arange(10, dtype=np.int64)
        idx.add(vectors[:10], ids)

        vec = idx.get(999)
        assert vec is None

    def test_euclidean_metric(self, vectors):
        """Test IVF with Euclidean distance."""
        config = IndexConfig(
            name="ivf_euclidean",
            dimension=64,
            index_type=IndexType.IVF,
            metric=MetricType.EUCLIDEAN,
            nlist=5,
            nprobe=2,
        )
        idx = IVFIndex(config)
        ids = np.arange(100, dtype=np.int64)
        idx.add(vectors[:100], ids)

        results = idx.search(vectors[0], 5)
        assert len(results) == 5
        assert results[0][0] == 0

    def test_different_nprobe(self, vectors):
        """Test IVF with different nprobe values."""
        for nprobe in [1, 3, 5]:
            config = IndexConfig(
                name=f"ivf_nprobe{nprobe}",
                dimension=64,
                index_type=IndexType.IVF,
                metric=MetricType.COSINE,
                nlist=5,
                nprobe=nprobe,
            )
            idx = IVFIndex(config)
            ids = np.arange(100, dtype=np.int64)
            idx.add(vectors[:100], ids)

            results = idx.search(vectors[0], 5)
            assert len(results) == 5

    def test_save_load(self, config, vectors):
        """Test saving and loading IVF index."""
        idx = IVFIndex(config)
        ids = np.arange(100, dtype=np.int64)
        idx.add(vectors[:100], ids)

        with tempfile.TemporaryDirectory() as tmpdir:
            save_dir = os.path.join(tmpdir, "ivf_index")
            assert idx.save(save_dir)

            # Load into new index
            new_idx = IVFIndex(config)
            assert new_idx.load(save_dir)

            # Verify search works
            results = new_idx.search(vectors[0], 5)
            assert len(results) > 0

    def test_get_status(self, config, vectors):
        """Test status reporting."""
        idx = IVFIndex(config)
        ids = np.arange(50, dtype=np.int64)
        idx.add(vectors[:50], ids)

        status = idx.get_status()
        assert status['type'] == 'ivf'
        assert status['size'] == 50
        assert 'cluster_stats' in status
        assert status['parameters']['nlist'] == 5

    def test_empty_search(self, config):
        """Test searching an empty index."""
        idx = IVFIndex(config)
        query = np.random.randn(64).astype(np.float32)
        query = query / np.linalg.norm(query)
        results = idx.search(query, 5)
        assert len(results) == 0

    def test_large_insert(self, config):
        """Test inserting many vectors."""
        idx = IVFIndex(config)
        rng = np.random.RandomState(42)
        vectors = rng.randn(500, 64).astype(np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / norms
        ids = np.arange(500, dtype=np.int64)

        count = idx.add(vectors, ids)
        assert count == 500
        assert idx.size() == 500

        # Verify search
        results = idx.search(vectors[0], 10)
        assert len(results) == 10


class TestIVFEdgeCases:
    """Edge case tests for IVFIndex."""

    @pytest.fixture
    def config(self):
        return IndexConfig(
            name="test_ivf",
            dimension=64,
            index_type=IndexType.IVF,
            metric=MetricType.COSINE,
            nlist=5,
            nprobe=2,
        )

    @pytest.fixture
    def vectors(self):
        rng = np.random.RandomState(42)
        vecs = rng.randn(200, 64).astype(np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.maximum(norms, 1e-12)

    def test_single_cluster(self):
        """Test IVF with just 1 cluster."""
        config = IndexConfig(
            name="single_cluster",
            dimension=8,
            index_type=IndexType.IVF,
            metric=MetricType.EUCLIDEAN,
            nlist=1,
            nprobe=1,
        )
        idx = IVFIndex(config)
        rng = np.random.RandomState(42)
        vectors = rng.randn(10, 8).astype(np.float32)
        ids = np.arange(10, dtype=np.int64)

        idx.add(vectors, ids)
        results = idx.search(vectors[0], 5)
        assert len(results) == 5

    def test_wrong_dimension(self, config):
        """Test that wrong dimension raises error."""
        idx = IVFIndex(config)
        with pytest.raises(ValueError):
            idx.add(np.random.randn(3, 32).astype(np.float32), np.array([1, 2, 3]))

    def test_nprobe_greater_than_nlist(self, config, vectors):
        """Test nprobe > nlist (should clamp)."""
        config.nprobe = 100  # More than nlist
        idx = IVFIndex(config)
        ids = np.arange(50, dtype=np.int64)
        idx.add(vectors[:50], ids)

        results = idx.search(vectors[0], 5)
        assert len(results) == 5