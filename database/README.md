# AinosDB - Hybrid Database Engine

AinosDB is a hybrid database engine that seamlessly integrates SQL, vector search, and document storage into a single unified system. Built for the AinosOS platform, it provides ACID transactions, MVCC, and a custom TCP server protocol.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  TCP Server                      │
├─────────────────────────────────────────────────┤
│                 Database Engine                  │
├──────────┬──────────────┬───────────────────────┤
│   SQL    │    Vector    │      Document         │
│  Engine  │    Index     │       Store           │
├──────────┴──────────────┴───────────────────────┤
│              Storage Engine                      │
│      (B+ Tree, Buffer Pool, WAL, MVCC)          │
└─────────────────────────────────────────────────┘
```

## Features

### SQL Engine
- Full SQL support: CREATE, INSERT, SELECT, UPDATE, DELETE, JOIN
- Recursive descent parser with comprehensive AST
- Cost-based query optimizer with join reordering
- Volcano-style iterator execution model
- MVCC-based transaction isolation

### Vector Index
- HNSW (Hierarchical Navigable Small World) index
- IVF (Inverted File) index with k-means clustering
- PQ (Product Quantization) for vector compression
- Hybrid search combining vector similarity with SQL filters

### Document Store
- JSON document storage with schema validation
- Nested query support with path expressions
- Full-text search with inverted index
- B-tree based document indexing

### Storage Engine
- B+ tree index structure
- Buffer pool with LRU replacement
- Write-ahead logging (WAL) for crash recovery
- Fuzzy checkpointing
- MVCC with snapshot isolation

### Server
- Custom binary protocol (length-prefixed framing)
- Async TCP server
- Session management
- Error handling and logging

## Quick Start

```python
from ainosdb import AinosDB

# Create database
db = AinosDB("path/to/data")

# SQL operations
db.execute("CREATE TABLE users (id INT, name TEXT, age INT)")
db.execute("INSERT INTO users VALUES (1, 'Alice', 30)")
result = db.execute("SELECT * FROM users WHERE age > 25")

# Vector operations
db.create_vector_index("users", "embedding", dims=128)
db.insert_vector("users", row_id=1, vector=[0.1, 0.2, ...])
results = db.search_vector("users", query_vector=[...], k=10)

# Document operations
db.insert_document("users", {"id": 1, "name": "Alice", "age": 30})
result = db.query_documents("users", {"age": {"$gt": 25}})

# Hybrid query
results = db.hybrid_query(
    sql="SELECT * FROM users WHERE age > 25",
    vector_column="embedding",
    query_vector=[...],
    text_search="description",
    weights={"sql": 0.3, "vector": 0.5, "text": 0.2}
)
```

## Installation

```bash
pip install -e .
```

## Development

```bash
pip install -e ".[dev]"
pytest tests/
```

## License

MIT License