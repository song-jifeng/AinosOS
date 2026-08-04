# Ainos Vector Database

A high-performance vector database built with **Python** and **NumPy**. Supports multiple index types, distance metrics, storage backends, and a TCP NDJSON protocol server.

## Features

- **Multiple Index Types**: Flat (brute-force), HNSW (hierarchical navigable small world), IVF (inverted file), PQ (product quantization), LSH (locality-sensitive hashing), and Hybrid indices
- **Distance Metrics**: Cosine similarity, Euclidean (L2) distance, dot product, Manhattan (L1) distance
- **Storage Backends**: In-memory, memory-mapped disk, SQLite metadata
- **TCP Server**: Multi-threaded NDJSON protocol server on port 9600, compatible with AinosOS IPC
- **Persistence**: Save and load the entire database to/from disk
- **Metadata Filtering**: Rich metadata and tag-based filtering with SQLite
- **Monitoring**: Built-in metrics, timing, and throughput tracking
- **Thread-safe**: All operations are thread-safe with fine-grained locking

## Quick Start

```python
from database import VectorDatabase
from utils.config import IndexType, MetricType
import numpy as np

# Create a database
db = VectorDatabase()

# Create a collection
db.create_index("my_collection", dimension=128, index_type=IndexType.FLAT, metric=MetricType.COSINE)

# Generate some vectors
vectors = np.random.randn(100, 128).astype(np.float32)
norms = np.linalg.norm(vectors, axis=1, keepdims=True)
vectors = vectors / norms

# Insert with metadata
metadata = [{"title": f"doc_{i}"} for i in range(100)]
db.insert("my_collection", vectors, metadata)

# Search
query = vectors[0]
results = db.search("my_collection", query, top_k=5)
for r in results:
    print(f"ID={r.id}, Score={r.score:.4f}, Metadata={r.metadata}")

# Persist to disk
db.persist("./data/my_db")

# Close
db.close()
```

## Installation

```bash
pip install numpy
```

Then clone the repository and run:

```bash
cd vector-db
python -m examples.basic_usage
```

## Index Types

| Index | Description | Best For | Training Required |
|-------|-------------|----------|-------------------|
| **Flat** | Brute-force exact search | Small datasets (<100K), accuracy-critical | No |
| **HNSW** | Hierarchical Navigable Small World graph | Large datasets, high recall, fast search | No |
| **IVF** | Inverted File with k-means clustering | Large datasets, good balance of speed/accuracy | Yes |
| **PQ** | Product Quantization (compressed vectors) | Memory-constrained environments | Yes |
| **LSH** | Locality-Sensitive Hashing | Very large datasets, approximate search | No |
| **Hybrid** | Combines multiple index types | When you need the best of multiple worlds | Varies |

## Distance Metrics

| Metric | Description | Range |
|--------|-------------|-------|
| Cosine | Cosine similarity (1 - cos) | [0, 2] |
| Euclidean | L2 distance | [0, +inf) |
| Dot | Negative dot product | (-inf, +inf) |
| Manhattan | L1 distance | [0, +inf) |

## API Reference

### Database Methods

- `create_index(name, dimension, index_type, metric, **kwargs)` - Create a new collection
- `drop_index(name)` - Drop a collection
- `insert(collection, vectors, metadata)` - Insert vectors
- `search(collection, query_vector, top_k)` - Search nearest neighbors
- `delete(collection, ids)` - Delete vectors by ID
- `get(collection, ids)` - Get vectors by ID
- `stats(collection)` - Get collection statistics
- `persist(path)` - Save database to disk
- `load(path)` - Load database from disk
- `list_collections()` - List all collections
- `search_with_filter(collection, query, top_k, filters, tags)` - Search with metadata filtering

### TCP Server

Start the server:

```bash
python -c "
from server.server import start_server
server = start_server(host='0.0.0.0', port=9600)
input('Press Enter to stop...')
server.stop()
"
```

Connect via TCP and send NDJSON:

```json
{"type":"request","id":"1","method":"ping","params":{},"version":"1.0"}
```

## Running Tests

```bash
pytest tests/ -v
```

## Examples

- `examples/basic_usage.py` - Complete walkthrough of all features
- `examples/semantic_search.py` - Semantic search with text embeddings
- `examples/benchmark.py` - Performance comparison of all index types

## Architecture

```
vector-db/
├── database.py           # Main database class
├── index/                # Index implementations
│   ├── base.py          # Abstract base class
│   ├── flat.py          # Brute-force index
│   ├── hnsw.py          # HNSW graph index
│   ├── ivf.py           # IVF with k-means
│   ├── pq.py            # Product quantization
│   ├── lsh.py           # LSH random projections
│   └── hybrid.py        # Hybrid multi-index
├── storage/              # Storage backends
│   ├── memory.py        # In-memory storage
│   ├── disk.py           # Memory-mapped disk
│   └── sqlite.py        # SQLite metadata
├── distance/             # Distance metrics
│   ├── cosine.py        # Cosine similarity
│   ├── euclidean.py     # Euclidean (L2)
│   ├── dot.py           # Dot product
│   └── manhattan.py     # Manhattan (L1)
├── server/               # TCP server
│   ├── server.py        # Multi-threaded server
│   ├── handler.py       # Request handler
│   └── protocol.py      # NDJSON protocol
├── utils/                # Utilities
│   ├── config.py        # Configuration
│   ├── serializer.py    # Serialization
│   └── metrics.py       # Performance metrics
├── tests/                # Unit tests
└── examples/             # Usage examples
```

## License

MIT License