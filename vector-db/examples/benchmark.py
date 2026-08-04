"""
Benchmark example for the Ainos Vector Database.

Compares the performance of different index types across:
- Build time (insertion speed)
- Query time (search latency)
- Recall (accuracy vs brute force)
- Memory usage
"""

import numpy as np
import time
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from database import VectorDatabase
from utils.config import IndexType, MetricType


def generate_dataset(n: int, dim: int, seed: int = 42) -> np.ndarray:
    """Generate a random dataset of normalized vectors.

    Args:
        n: Number of vectors
        dim: Vector dimension
        seed: Random seed

    Returns:
        Normalized vectors of shape (n, dim)
    """
    rng = np.random.RandomState(seed)
    vectors = rng.randn(n, dim).astype(np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    vectors = vectors / np.maximum(norms, 1e-12)
    return vectors


def benchmark_index(db, name: str, index_type: IndexType,
                     vectors: np.ndarray, queries: np.ndarray,
                     index_params: dict = None,
                     metric: MetricType = MetricType.COSINE) -> dict:
    """Benchmark a single index type.

    Args:
        db: VectorDatabase instance
        name: Collection name
        index_type: Type of index
        vectors: Vectors to index
        queries: Query vectors
        index_params: Additional index parameters
        metric: Distance metric

    Returns:
        Dictionary of benchmark results.
    """
    dim = vectors.shape[1]
    n = vectors.shape[0]
    nq = queries.shape[0]
    k = 10  # Top-k for search

    results = {
        "name": name,
        "index_type": index_type.value,
        "dimension": dim,
        "num_vectors": n,
        "num_queries": nq,
        "top_k": k,
        "build_time_ms": 0.0,
        "avg_query_time_ms": 0.0,
        "throughput_queries_per_sec": 0.0,
        "recall": 0.0,
        "memory_usage_bytes": 0,
    }

    params = index_params or {}

    # Create index
    print(f"\n  Creating {name} index...", end=" ")
    start = time.time()
    db.create_index(name, dim, index_type, metric, **params)
    print(f"done ({time.time() - start:.3f}s)")

    # Build index (insert vectors)
    print(f"  Inserting {n} vectors...", end=" ")
    start = time.time()
    db.insert(name, vectors)
    build_time = time.time() - start
    results["build_time_ms"] = round(build_time * 1000, 2)
    print(f"done ({build_time*1000:.1f}ms, {n/build_time:.0f} vec/s)")

    # Run queries
    print(f"  Running {nq} queries...", end=" ")
    query_times = []
    all_results = []

    for i in range(nq):
        q_start = time.time()
        db.search(name, queries[i], top_k=k)
        q_time = time.time() - q_start
        query_times.append(q_time)

    avg_time = np.mean(query_times)
    results["avg_query_time_ms"] = round(avg_time * 1000, 4)
    results["throughput_queries_per_sec"] = round(1.0 / avg_time, 1)
    print(f"done ({avg_time*1000:.3f}ms avg, {1.0/avg_time:.0f} qps)")

    # Compute recall (compared to brute force Flat)
    if index_type != IndexType.FLAT:
        print(f"  Computing recall vs Flat...", end=" ")
        db.create_index(f"{name}_ref", dim, IndexType.FLAT, metric)
        db.insert(f"{name}_ref", vectors)

        correct = 0
        total = 0
        for i in range(min(nq, 100)):  # Use first 100 queries
            ref_results = db.search(f"{name}_ref", queries[i], top_k=k)
            idx_results = db.search(name, queries[i], top_k=k)

            ref_ids = {r.id for r in ref_results}
            idx_ids = {r.id for r in idx_results}

            correct += len(ref_ids & idx_ids)
            total += k

        recall = correct / total if total > 0 else 0.0
        results["recall"] = round(recall, 4)
        print(f"done ({recall:.2%})")

        db.drop_index(f"{name}_ref")

    # Get memory usage
    try:
        stats = db.stats(name)
        if hasattr(stats, 'status') and 'memory_usage_bytes' in stats.status:
            results["memory_usage_bytes"] = stats.status['memory_usage_bytes']
        else:
            results["memory_usage_bytes"] = n * dim * 4  # Estimate
    except Exception:
        results["memory_usage_bytes"] = n * dim * 4

    return results


def main():
    print("=" * 60)
    print("Ainos Vector Database - Benchmark")
    print("=" * 60)

    # Configuration
    DIM = 128
    N_VECTORS = 1000
    N_QUERIES = 100

    # Generate data
    print(f"\n[1] Generating dataset: {N_VECTORS} vectors, {DIM} dimensions")
    vectors = generate_dataset(N_VECTORS, DIM, seed=42)
    queries = generate_dataset(N_QUERIES, DIM, seed=99)

    # Create database
    db = VectorDatabase()

    # Run benchmarks
    all_results = []

    print("\n[2] Running benchmarks...")

    # Flat (baseline)
    res = benchmark_index(db, "flat_bench", IndexType.FLAT, vectors, queries)
    all_results.append(res)

    # HNSW
    res = benchmark_index(db, "hnsw_bench", IndexType.HNSW, vectors, queries, {
        "M": 16, "ef_construction": 200, "ef_search": 50
    })
    all_results.append(res)

    # IVF
    res = benchmark_index(db, "ivf_bench", IndexType.IVF, vectors, queries, {
        "nlist": 10, "nprobe": 3
    })
    all_results.append(res)

    # LSH
    res = benchmark_index(db, "lsh_bench", IndexType.LSH, vectors, queries, {
        "nbits_lsh": 64, "num_tables": 10
    })
    all_results.append(res)

    # PQ
    res = benchmark_index(db, "pq_bench", IndexType.PQ, vectors, queries, {
        "m_subquantizers": 8, "nbits": 8
    })
    all_results.append(res)

    # Print results table
    print("\n" + "=" * 60)
    print("BENCHMARK RESULTS")
    print("=" * 60)

    header = f"{'Index':<10} {'Build(ms)':<12} {'Query(ms)':<12} {'QPS':<10} {'Recall':<10} {'Memory':<12}"
    print(header)
    print("-" * 66)

    for res in all_results:
        mem_str = f"{res['memory_usage_bytes'] / 1024:.0f}KB" if res['memory_usage_bytes'] < 1024*1024 else f"{res['memory_usage_bytes'] / (1024*1024):.1f}MB"
        recall_str = f"{res['recall']:.2%}" if res['recall'] > 0 else "N/A"
        print(f"{res['name']:<10} {res['build_time_ms']:<12.1f} {res['avg_query_time_ms']:<12.4f} {res['throughput_queries_per_sec']:<10.0f} {recall_str:<10} {mem_str:<12}")

    print("-" * 66)

    # Summary
    print("\n[3] Summary:")
    fastest = min(all_results, key=lambda r: r['avg_query_time_ms'])
    best_recall = max(all_results, key=lambda r: r['recall'])
    print(f"  Fastest query: {fastest['name']} ({fastest['avg_query_time_ms']:.4f}ms)")
    print(f"  Best recall: {best_recall['name']} ({best_recall['recall']:.2%})")

    # Save results
    results_path = "benchmark_results.json"
    with open(results_path, 'w') as f:
        json.dump(all_results, f, indent=2)
    print(f"\n  Results saved to {results_path}")

    db.close()
    print("\n" + "=" * 60)
    print("Benchmark completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()