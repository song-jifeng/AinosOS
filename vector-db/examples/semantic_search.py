"""
Semantic search example using the Ainos Vector Database.

Demonstrates a complete semantic search pipeline:
1. Generate text embeddings using a simple method
2. Index them in the vector database
3. Search by semantic similarity
4. Compare different index types
"""

import numpy as np
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from database import VectorDatabase
from utils.config import IndexType, MetricType


def simple_text_embedding(text: str, dim: int = 128) -> np.ndarray:
    """Generate a simple embedding from text (character-level).

    This is a simplified embedding for demonstration purposes.
    In production, you would use a real embedding model like
    sentence-transformers, OpenAI embeddings, etc.

    Args:
        text: Input text
        dim: Embedding dimension

    Returns:
        Embedding vector of shape (dim,)
    """
    text = text.lower()
    # Create a simple bag-of-characters embedding
    embedding = np.zeros(dim, dtype=np.float32)

    for i, char in enumerate(text):
        idx = ord(char) % dim
        embedding[idx] += 1.0

    # Normalize
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm

    return embedding


# Sample documents
DOCUMENTS = [
    "The quick brown fox jumps over the lazy dog",
    "Machine learning is transforming how we process data",
    "Neural networks can learn complex patterns from data",
    "Vector databases enable efficient similarity search",
    "Python is a popular programming language for data science",
    "The weather today is sunny and warm",
    "Artificial intelligence is reshaping industries worldwide",
    "Database indexing improves query performance significantly",
    "Deep learning models require large amounts of training data",
    "Natural language processing enables computers to understand text",
    "Climate change is affecting ecosystems around the globe",
    "The history of ancient Rome spans over a thousand years",
    "Quantum computing promises exponential speedup for certain problems",
    "Protein folding is a fundamental problem in biology",
    "The solar system has eight planets orbiting the sun",
    "Sustainable energy sources are crucial for our future",
    "Blockchain technology enables decentralized applications",
    "Computer vision allows machines to interpret visual information",
    "The human brain contains approximately 86 billion neurons",
    "Space exploration continues to push the boundaries of knowledge",
]

# Queries for testing
QUERIES = [
    "machine learning and artificial intelligence",
    "database and indexing technology",
    "space and astronomy",
    "biology and life sciences",
    "climate and environment",
]


def main():
    print("=" * 60)
    print("Ainos Vector Database - Semantic Search Example")
    print("=" * 60)

    # Create database
    print("\n[1] Creating database with multiple index types...")
    db = VectorDatabase()

    # Create collections with different index types
    collections = {}

    collections["flat"] = {
        "name": "semantic_flat",
        "index": None
    }
    db.create_index("semantic_flat", 128, IndexType.FLAT, MetricType.COSINE)

    collections["hnsw"] = {
        "name": "semantic_hnsw",
        "index": None
    }
    db.create_index("semantic_hnsw", 128, IndexType.HNSW, MetricType.COSINE,
                    M=16, ef_construction=200, ef_search=50)

    collections["ivf"] = {
        "name": "semantic_ivf",
        "index": None
    }
    db.create_index("semantic_ivf", 128, IndexType.IVF, MetricType.COSINE,
                    nlist=5, nprobe=2)

    # Generate embeddings for documents
    print(f"\n[2] Generating embeddings for {len(DOCUMENTS)} documents...")
    embeddings = []
    metadata = []
    for i, doc in enumerate(DOCUMENTS):
        emb = simple_text_embedding(doc)
        embeddings.append(emb)
        metadata.append({
            "id": i,
            "text": doc,
            "length": len(doc),
            "has_ai": any(kw in doc.lower() for kw in
                         ["machine", "neural", "ai", "deep", "learning"]),
        })
        print(f"  [{i:2d}] {doc[:50]}...")

    embeddings = np.array(embeddings, dtype=np.float32)

    # Insert into all collections
    print("\n[3] Inserting into all collections...")
    for name, info in collections.items():
        count = db.insert(info["name"], embeddings, metadata)
        print(f"  {name}: {count} vectors inserted")

    # Search queries
    print("\n[4] Running semantic search queries...")
    print()

    for q_idx, query_text in enumerate(QUERIES):
        print(f"{'=' * 60}")
        print(f"Query {q_idx + 1}: \"{query_text}\"")
        print(f"{'=' * 60}")

        query_emb = simple_text_embedding(query_text)

        for name, info in collections.items():
            print(f"\n  --- {name.upper()} Index ---")
            results = db.search(info["name"], query_emb, top_k=3)

            for i, r in enumerate(results):
                text = r.metadata.get("text", "N/A") if r.metadata else "N/A"
                print(f"  {i+1}. [score={r.score:.4f}] {text[:60]}")

        print()

    # Compare search performance
    print("\n[5] Performance comparison...")
    import time

    query_emb = simple_text_embedding("technology and science")

    for name, info in collections.items():
        start = time.time()
        for _ in range(100):
            db.search(info["name"], query_emb, top_k=5)
        elapsed = time.time() - start
        print(f"  {name}: 100 searches in {elapsed*1000:.1f}ms "
              f"({elapsed*10:.1f}ms per search)")

    # Delete some vectors
    print("\n[6] Deleting first 3 documents...")
    for name, info in collections.items():
        deleted = db.delete(info["name"], [0, 1, 2])
        print(f"  {name}: deleted {deleted} vectors")

    # Show final stats
    print("\n[7] Final statistics:")
    stats = db.stats()
    for name, stat in stats.items():
        if isinstance(stat, dict):
            continue
        print(f"  {name}: {stat.size} vectors, type={stat.index_type}")

    print("\n" + "=" * 60)
    print("Semantic search example completed!")
    print("=" * 60)

    db.close()


if __name__ == "__main__":
    main()