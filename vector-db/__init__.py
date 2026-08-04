"""
Ainos Vector Database - A high-performance vector database built with NumPy.

A production-grade vector database supporting multiple index types (Flat, HNSW, IVF, PQ, LSH, Hybrid),
multiple distance metrics, disk persistence, and a TCP NDJSON protocol server.
"""

__version__ = "0.1.0"
__author__ = "Ainos"

from database import VectorDatabase
from utils.config import IndexType, IndexConfig, StorageType
from distance import DistanceMetric, MetricType, cosine_similarity, euclidean_distance, dot_product, manhattan_distance
from storage import MemoryStorage, DiskStorage, SQLiteStorage

__all__ = [
    "VectorDatabase",
    "IndexType", "IndexConfig",
    "DistanceMetric", "MetricType",
    "cosine_similarity", "euclidean_distance", "dot_product", "manhattan_distance",
    "MemoryStorage", "DiskStorage", "SQLiteStorage", "StorageType",
]