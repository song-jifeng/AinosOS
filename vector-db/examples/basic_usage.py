"""
Basic usage example for the Ainos Vector Database.

Demonstrates:
1. Creating a database and collections
2. Inserting vectors with metadata
3. Searching for nearest neighbors
4. Deleting vectors
5. Getting database statistics
6. Persisting and loading
"""

import numpy as np
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from database import VectorDatabase
from utils.config import IndexType, MetricType


def main():
    print("=" * 60)
    print("Ainos Vector Database - Basic Usage Example")
    print("=" * 60)

    # 1. Create a database
    print("\n[1] Creating database...")
    db = VectorDatabase()

    # 2. Create collections with different index types
    print("\n[2] Creating collections...")

    # Flat index (exact search)
    db.create_index(
        name="articles_flat",
        dimension=128,
        index_type=IndexType.FLAT,
        metric=MetricType.COSINE,
    )
    print("  - Created 'articles_flat' (Flat, Cosine)")

    # HNSW index (approximate, fast)
    db.create_index(
        name="articles_hnsw",
        dimension=128,
        index_type=IndexType.HNSW,
        metric=MetricType.COSINE,
        M=16,           # Connections per node
        ef_construction=200,  # Build-time search width
        ef_search=50,   # Query-time search width
    )
    print("  - Created 'articles_hnsw' (HNSW, Cosine)")

    # IVF index (clustering-based)
    db.create_index(
        name="articles_ivf",
        dimension=128,
        index_type=IndexType.IVF,
        metric=MetricType.EUCLIDEAN,
        nlist=10,    # Number of clusters
        nprobe=3,    # Clusters to search
    )
    print("  - Created 'articles_ivf' (IVF, Euclidean)")

    # 3. Generate sample vectors and metadata
    print("\n[3] Generating sample data...")
    np.random.seed(42)
    num_vectors = 100

    # Create random vectors and normalize them
    vectors = np.random.randn(num_vectors, 128).astype(np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    vectors = vectors / np.maximum(norms, 1e-12)

    # Create metadata
    metadata = [
        {"title": f"Article {i}", "category": "tech" if i < 50 else "science",
         "tags": ["ai", "database"] if i % 2 == 0 else ["ml", "search"],
         "length": 100 + i * 10}
        for i in range(num_vectors)
    ]

    # 4. Insert vectors with metadata
    print("\n[4] Inserting vectors...")
    count = db.insert("articles_flat", vectors, metadata)
    print(f"  - Inserted {count} vectors into 'articles_flat'")

    count = db.insert("articles_hnsw", vectors, metadata)
    print(f"  - Inserted {count} vectors into 'articles_hnsw'")

    count = db.insert("articles_ivf", vectors, metadata)
    print(f"  - Inserted {count} vectors into 'articles_ivf'")

    # 5. Search for nearest neighbors
    print("\n[5] Searching for nearest neighbors...")
    query = vectors[0]  # Use the first vector as query

    print("\n  --- Flat Index (exact) ---")
    results = db.search("articles_flat", query, top_k=5)
    for i, r in enumerate(results):
        print(f"  {i+1}. ID={r.id}, Score={r.score:.4f}, "
              f"Title={r.metadata.get('title', 'N/A') if r.metadata else 'N/A'}")

    print("\n  --- HNSW Index (approximate) ---")
    results = db.search("articles_hnsw", query, top_k=5)
    for i, r in enumerate(results):
        print(f"  {i+1}. ID={r.id}, Score={r.score:.4f}")

    print("\n  --- IVF Index (approximate) ---")
    results = db.search("articles_ivf", query, top_k=5)
    for i, r in enumerate(results):
        print(f"  {i+1}. ID={r.id}, Score={r.score:.4f}")

    # 6. Search with metadata filtering
    print("\n[6] Searching with metadata filter...")
    results = db.search_with_filter(
        "articles_flat", query, top_k=3,
        filters={"category": "science"},
        tags=["ai"]
    )
    print(f"  Found {len(results)} science articles tagged 'ai':")
    for r in results:
        title = r.metadata.get('title', 'N/A') if r.metadata else 'N/A'
        print(f"    - {title}")

    # 7. Get vectors by ID
    print("\n[7] Getting vectors by ID...")
    vectors_found = db.get("articles_flat", [0, 1, 2, 999])
    for i, v in enumerate(vectors_found):
        if v is not None:
            title = v.metadata.get('title', 'N/A') if v.metadata else 'N/A'
            print(f"  ID={v.id}: {title}")
        else:
            print(f"  ID={[0, 1, 2, 999][i]}: Not found")

    # 8. Delete vectors
    print("\n[8] Deleting vectors...")
    deleted = db.delete("articles_flat", [0, 1])
    print(f"  Deleted {deleted} vectors from 'articles_flat'")

    # 9. Get statistics
    print("\n[9] Collection statistics:")
    stats = db.stats()
    for name, stat in stats.items():
        if isinstance(stat, dict):
            continue
        print(f"  {name}:")
        print(f"    Type: {stat.index_type}")
        print(f"    Dimension: {stat.dimension}")
        print(f"    Metric: {stat.metric}")
        print(f"    Size: {stat.size}")

    # 10. Persist to disk
    print("\n[10] Persisting database...")
    persist_path = "./data/example_db"
    db.persist(persist_path)
    print(f"  Database saved to {persist_path}")

    # 11. Load from disk
    print("\n[11] Loading database from disk...")
    db2 = VectorDatabase()
    db2.load(persist_path)
    print(f"  Loaded {len(db2.list_collections())} collections")

    # 12. Metrics report
    print("\n[12] Metrics:")
    print(db.get_metrics_report())

    # Cleanup
    print("\n" + "=" * 60)
    print("Example completed successfully!")
    print("=" * 60)

    db.close()
    db2.close()


if __name__ == "__main__":
    main()