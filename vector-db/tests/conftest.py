"""Test configuration and fixtures for the vector database."""
import pytest
import numpy as np
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from database import VectorDatabase
from distance import cosine_distance, euclidean_distance, dot_product, manhattan_distance


@pytest.fixture
def db():
    """Create a fresh vector database for testing."""
    database = VectorDatabase()
    yield database
    database.close()


@pytest.fixture
def random_vectors():
    """Generate random vectors for testing."""
    def _generate(n: int = 100, dim: int = 128, seed: int = 42):
        rng = np.random.RandomState(seed)
        vectors = rng.randn(n, dim).astype(np.float32)
        # Normalize for cosine
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.maximum(norms, 1e-12)
        return vectors
    return _generate


@pytest.fixture
def flat_db(db, random_vectors):
    """Create a database with a flat index and some vectors."""
    db.create_index("test_flat", 128, "flat", "cosine")
    vectors = random_vectors(50, 128)
    db.insert("test_flat", vectors)
    return db


@pytest.fixture
def hnsw_db(db, random_vectors):
    """Create a database with an HNSW index and some vectors."""
    db.create_index("test_hnsw", 128, "hnsw", "cosine", M=8, ef_construction=100, ef_search=50)
    vectors = random_vectors(50, 128)
    db.insert("test_hnsw", vectors)
    return db


@pytest.fixture
def ivf_db(db, random_vectors):
    """Create a database with an IVF index and some vectors."""
    db.create_index("test_ivf", 128, "ivf", "cosine", nlist=5, nprobe=2)
    vectors = random_vectors(50, 128)
    db.insert("test_ivf", vectors)
    return db


@pytest.fixture
def multi_collection_db(db, random_vectors):
    """Create a database with multiple collections."""
    for name in ["col_a", "col_b", "col_c"]:
        db.create_index(name, 64, "flat", "euclidean")
        vectors = random_vectors(20, 64)
        db.insert(name, vectors)
    return db


@pytest.fixture
def sample_vectors():
    """Generate simple known vectors for deterministic testing."""
    vectors = np.array([
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
        [1.0, 1.0, 0.0],
        [1.0, 1.0, 1.0],
    ], dtype=np.float32)
    # Normalize
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    vectors = vectors / norms
    return vectors


@pytest.fixture
def temp_dir():
    """Create a temporary directory for persistence tests."""
    import tempfile
    import shutil
    path = tempfile.mkdtemp()
    yield path
    shutil.rmtree(path, ignore_errors=True)