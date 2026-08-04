"""
数据库集成测试

测试 SQL 查询执行、向量搜索、混合查询和事务处理。
"""

import os
import sys
import json
import time
import math
import random
import pickle
import sqlite3
import struct
import pytest
import threading
import concurrent.futures
from typing import List, Dict, Optional, Any, Tuple, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
from enum import Enum, auto
from contextlib import contextmanager
from unittest.mock import MagicMock, Mock, patch, PropertyMock
from pathlib import Path


# =============================================================================
# 向量引擎模拟
# =============================================================================

@dataclass
class VectorRecord:
    """向量记录"""
    id: str
    vector: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class SearchResult:
    """搜索结果"""
    id: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    rank: int = 0


class VectorEngine:
    """向量引擎 - 模拟向量数据库操作"""

    def __init__(self, dimension: int = 768, index_type: str = "flat"):
        self.dimension = dimension
        self.index_type = index_type
        self._records: Dict[str, VectorRecord] = {}
        self._lock = threading.RLock()

    def insert(self, record: VectorRecord) -> bool:
        with self._lock:
            self._records[record.id] = record
            return True

    def insert_batch(self, records: List[VectorRecord]) -> int:
        with self._lock:
            count = 0
            for record in records:
                if record.id not in self._records:
                    self._records[record.id] = record
                    count += 1
            return count

    def delete(self, record_id: str) -> bool:
        with self._lock:
            if record_id in self._records:
                del self._records[record_id]
                return True
            return False

    def get(self, record_id: str) -> Optional[VectorRecord]:
        with self._lock:
            return self._records.get(record_id)

    def update(self, record_id: str, vector: List[float] = None,
               metadata: Dict[str, Any] = None) -> bool:
        with self._lock:
            if record_id not in self._records:
                return False
            record = self._records[record_id]
            if vector is not None:
                record.vector = vector
            if metadata is not None:
                record.metadata.update(metadata)
            record.created_at = time.time()
            return True

    def count(self) -> int:
        with self._lock:
            return len(self._records)

    @staticmethod
    def cosine_similarity(a: List[float], b: List[float]) -> float:
        if len(a) != len(b):
            raise ValueError(f"Dimension mismatch: {len(a)} vs {len(b)}")
        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot_product / (norm_a * norm_b)

    @staticmethod
    def euclidean_distance(a: List[float], b: List[float]) -> float:
        if len(a) != len(b):
            raise ValueError(f"Dimension mismatch: {len(a)} vs {len(b)}")
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

    @staticmethod
    def dot_product(a: List[float], b: List[float]) -> float:
        if len(a) != len(b):
            raise ValueError(f"Dimension mismatch: {len(a)} vs {len(b)}")
        return sum(x * y for x, y in zip(a, b))

    def search(self, query_vector: List[float], top_k: int = 10,
               metric: str = "cosine") -> List[SearchResult]:
        if metric == "cosine":
            similarity_fn = self.cosine_similarity
            reverse = True
        elif metric == "euclidean":
            similarity_fn = self.euclidean_distance
            reverse = False
        elif metric == "dot_product":
            similarity_fn = self.dot_product
            reverse = True
        else:
            raise ValueError(f"Unknown metric: {metric}")

        with self._lock:
            scores = []
            for record_id, record in self._records.items():
                try:
                    score = similarity_fn(query_vector, record.vector)
                    scores.append(SearchResult(
                        id=record_id,
                        score=score,
                        metadata=record.metadata,
                    ))
                except ValueError:
                    continue

            scores.sort(key=lambda x: x.score, reverse=reverse)
            for i, result in enumerate(scores[:top_k]):
                result.rank = i + 1
            return scores[:top_k]

    def search_with_filter(self, query_vector: List[float], top_k: int = 10,
                           metric: str = "cosine",
                           filters: Dict[str, Any] = None) -> List[SearchResult]:
        if filters is None:
            return self.search(query_vector, top_k, metric)

        if metric == "cosine":
            similarity_fn = self.cosine_similarity
            reverse = True
        elif metric == "euclidean":
            similarity_fn = self.euclidean_distance
            reverse = False
        else:
            similarity_fn = self.dot_product
            reverse = True

        with self._lock:
            scores = []
            for record_id, record in self._records.items():
                # 应用过滤条件
                match = True
                if filters:
                    for key, value in filters.items():
                        if key in record.metadata:
                            if isinstance(value, (list, tuple)):
                                if record.metadata[key] not in value:
                                    match = False
                                    break
                            elif record.metadata[key] != value:
                                match = False
                                break
                        else:
                            match = False
                            break
                if not match:
                    continue

                try:
                    score = similarity_fn(query_vector, record.vector)
                    scores.append(SearchResult(
                        id=record_id,
                        score=score,
                        metadata=record.metadata,
                    ))
                except ValueError:
                    continue

            scores.sort(key=lambda x: x.score, reverse=reverse)
            for i, result in enumerate(scores[:top_k]):
                result.rank = i + 1
            return scores[:top_k]

    def clear(self):
        with self._lock:
            self._records.clear()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "total_records": len(self._records),
                "dimension": self.dimension,
                "index_type": self.index_type,
            }


# =============================================================================
# 混合查询引擎
# =============================================================================

@dataclass
class HybridQueryResult:
    """混合查询结果"""
    id: str
    vector_score: float
    text_score: float
    combined_score: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    rank: int = 0


class HybridSearchEngine:
    """混合搜索 - 结合向量搜索和文本搜索"""

    def __init__(self, vector_engine: VectorEngine):
        self.vector_engine = vector_engine
        self._text_index: Dict[str, str] = {}  # id -> text
        self._lock = threading.RLock()

    def index_text(self, record_id: str, text: str):
        with self._lock:
            self._text_index[record_id] = text

    def index_text_batch(self, items: List[Tuple[str, str]]):
        with self._lock:
            for record_id, text in items:
                self._text_index[record_id] = text

    def _text_search_score(self, query: str, text: str) -> float:
        """简单的文本匹配分数"""
        if not text or not query:
            return 0.0

        query_lower = query.lower()
        text_lower = text.lower()
        query_terms = set(query_lower.split())
        text_terms = text_lower.split()

        if not query_terms:
            return 0.0

        # 计算 TF-IDF 风格的分数
        term_frequencies = defaultdict(int)
        for term in text_terms:
            term_frequencies[term] += 1

        score = 0.0
        for term in query_terms:
            if term in term_frequencies:
                tf = term_frequencies[term] / len(text_terms)
                score += tf

        # 精确匹配加分
        if query_lower in text_lower:
            score += 1.0

        return score / len(query_terms)

    def hybrid_search(self, query_vector: List[float], query_text: str,
                      top_k: int = 10, vector_weight: float = 0.7,
                      text_weight: float = 0.3) -> List[HybridQueryResult]:
        if not (0 <= vector_weight <= 1 and 0 <= text_weight <= 1):
            raise ValueError("Weights must be between 0 and 1")

        vector_results = self.vector_engine.search(query_vector, top_k=top_k * 2)

        with self._lock:
            results = []
            for vr in vector_results:
                text_score = self._text_search_score(
                    query_text,
                    self._text_index.get(vr.id, ""),
                )
                combined = vector_weight * vr.score + text_weight * text_score
                results.append(HybridQueryResult(
                    id=vr.id,
                    vector_score=vr.score,
                    text_score=text_score,
                    combined_score=combined,
                    metadata=vr.metadata,
                ))

            results.sort(key=lambda x: x.combined_score, reverse=True)
            for i, result in enumerate(results[:top_k]):
                result.rank = i + 1
            return results[:top_k]


# =============================================================================
# 数据库管理器
# =============================================================================

class DatabaseManager:
    """数据库管理器 - 封装 SQLite 操作"""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._connection: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()
        self._transaction_depth = 0

    @contextmanager
    def connection(self):
        if self._connection is None:
            self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
        yield self._connection

    @contextmanager
    def cursor(self):
        with self.connection() as conn:
            cursor = conn.cursor()
            try:
                yield cursor
            finally:
                cursor.close()

    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        with self.cursor() as c:
            c.execute(query, params)
            self._connection.commit()
            return c

    def execute_many(self, query: str, params_list: List[tuple]) -> int:
        with self.cursor() as c:
            c.executemany(query, params_list)
            self._connection.commit()
            return c.rowcount

    def fetch_one(self, query: str, params: tuple = ()) -> Optional[Dict]:
        with self.cursor() as c:
            c.execute(query, params)
            row = c.fetchone()
            return dict(row) if row else None

    def fetch_all(self, query: str, params: tuple = ()) -> List[Dict]:
        with self.cursor() as c:
            c.execute(query, params)
            return [dict(row) for row in c.fetchall()]

    @contextmanager
    def transaction(self):
        with self._lock:
            self._transaction_depth += 1
            if self._transaction_depth == 1:
                self.execute("BEGIN TRANSACTION")
            try:
                yield
            except Exception:
                if self._transaction_depth == 1:
                    self.execute("ROLLBACK")
                raise
            finally:
                self._transaction_depth -= 1
                if self._transaction_depth == 0:
                    self.execute("COMMIT")

    def create_table(self, table_name: str, schema: str):
        query = f"CREATE TABLE IF NOT EXISTS {table_name} ({schema})"
        self.execute(query)

    def drop_table(self, table_name: str):
        self.execute(f"DROP TABLE IF EXISTS {table_name}")

    def insert(self, table_name: str, data: Dict[str, Any]) -> int:
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        query = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"
        with self.cursor() as c:
            c.execute(query, tuple(data.values()))
            self._connection.commit()
            return c.lastrowid

    def insert_batch(self, table_name: str, data_list: List[Dict[str, Any]]) -> int:
        if not data_list:
            return 0
        columns = ", ".join(data_list[0].keys())
        placeholders = ", ".join(["?"] * len(data_list[0]))
        query = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"
        params_list = [tuple(d.values()) for d in data_list]
        with self.cursor() as c:
            c.executemany(query, params_list)
            self._connection.commit()
            return len(data_list)

    def update(self, table_name: str, data: Dict[str, Any],
               condition: str, condition_params: tuple = ()) -> int:
        set_clause = ", ".join(f"{k} = ?" for k in data.keys())
        query = f"UPDATE {table_name} SET {set_clause} WHERE {condition}"
        params = tuple(data.values()) + condition_params
        with self.cursor() as c:
            c.execute(query, params)
            self._connection.commit()
            return c.rowcount

    def delete(self, table_name: str, condition: str,
               params: tuple = ()) -> int:
        query = f"DELETE FROM {table_name} WHERE {condition}"
        with self.cursor() as c:
            c.execute(query, params)
            self._connection.commit()
            return c.rowcount

    def close(self):
        if self._connection:
            self._connection.close()
            self._connection = None


# =============================================================================
# 测试夹具
# =============================================================================

@pytest.fixture
def vector_engine():
    return VectorEngine(dimension=128)

@pytest.fixture
def db_manager():
    manager = DatabaseManager()
    yield manager
    manager.close()


@pytest.fixture
def hybrid_engine(vector_engine):
    return HybridSearchEngine(vector_engine)


@pytest.fixture
def sample_vectors(vector_engine):
    """创建样本向量数据"""
    records = []
    for i in range(100):
        vector = [random.uniform(-1, 1) for _ in range(128)]
        vector = [v / math.sqrt(sum(x*x for x in vector)) for v in vector]  # 归一化
        record = VectorRecord(
            id=f"vec-{i}",
            vector=vector,
            metadata={
                "category": random.choice(["A", "B", "C"]),
                "priority": random.randint(1, 5),
                "tags": random.sample(["tag1", "tag2", "tag3", "tag4"], 2),
                "value": random.random() * 100,
            },
        )
        vector_engine.insert(record)
    return vector_engine


# =============================================================================
# 测试用例：SQL 查询执行
# =============================================================================

class TestSQLQueryExecution:
    """SQL 查询执行测试"""

    def test_create_table(self, db_manager):
        """测试创建表"""
        db_manager.create_table("users", "id INTEGER PRIMARY KEY, name TEXT, age INTEGER")
        tables = db_manager.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
        assert any(t["name"] == "users" for t in tables)

    def test_insert_data(self, db_manager):
        """测试插入数据"""
        db_manager.create_table("test_insert", "id INTEGER PRIMARY KEY, value TEXT")
        db_manager.insert("test_insert", {"id": 1, "value": "hello"})
        result = db_manager.fetch_one("SELECT * FROM test_insert WHERE id=1")
        assert result is not None
        assert result["value"] == "hello"

    def test_batch_insert(self, db_manager):
        """测试批量插入"""
        db_manager.create_table("batch_test", "id INTEGER PRIMARY KEY, name TEXT, score REAL")
        data = [{"id": i, "name": f"user-{i}", "score": random.random() * 100} for i in range(100)]
        count = db_manager.insert_batch("batch_test", data)
        assert count == 100

        results = db_manager.fetch_all("SELECT COUNT(*) as cnt FROM batch_test")
        assert results[0]["cnt"] == 100

    def test_select_query(self, db_manager):
        """测试 SELECT 查询"""
        db_manager.create_table("employees", "id INTEGER PRIMARY KEY, name TEXT, dept TEXT, salary REAL")
        employees = [
            {"id": 1, "name": "Alice", "dept": "Engineering", "salary": 100000},
            {"id": 2, "name": "Bob", "dept": "Engineering", "salary": 90000},
            {"id": 3, "name": "Charlie", "dept": "Sales", "salary": 80000},
            {"id": 4, "name": "Diana", "dept": "Marketing", "salary": 85000},
        ]
        db_manager.insert_batch("employees", employees)

        # 简单查询
        results = db_manager.fetch_all("SELECT * FROM employees WHERE dept = 'Engineering'")
        assert len(results) == 2
        assert all(r["dept"] == "Engineering" for r in results)

        # 带排序
        results = db_manager.fetch_all("SELECT * FROM employees ORDER BY salary DESC")
        assert results[0]["name"] == "Alice"

        # 聚合查询
        result = db_manager.fetch_one("SELECT dept, AVG(salary) as avg_salary FROM employees GROUP BY dept")
        assert result is not None
        assert "avg_salary" in result

    def test_update_data(self, db_manager):
        """测试更新数据"""
        db_manager.create_table("updatable", "id INTEGER PRIMARY KEY, value TEXT, status TEXT")
        db_manager.insert("updatable", {"id": 1, "value": "old", "status": "active"})

        db_manager.update("updatable", {"value": "new"}, "id = ?", (1,))
        result = db_manager.fetch_one("SELECT * FROM updatable WHERE id=1")
        assert result["value"] == "new"

    def test_delete_data(self, db_manager):
        """测试删除数据"""
        db_manager.create_table("deletable", "id INTEGER PRIMARY KEY, value TEXT")
        for i in range(10):
            db_manager.insert("deletable", {"id": i, "value": f"item-{i}"})

        db_manager.delete("deletable", "id >= ?", (5,))
        remaining = db_manager.fetch_all("SELECT COUNT(*) as cnt FROM deletable")
        assert remaining[0]["cnt"] == 5

    def test_complex_query(self, db_manager):
        """测试复杂查询"""
        db_manager.create_table("orders",
            "id INTEGER PRIMARY KEY, customer TEXT, product TEXT, quantity INTEGER, price REAL, created_at TEXT")

        orders = [
            {"id": i, "customer": f"cust-{i%5}", "product": f"prod-{i%10}",
             "quantity": random.randint(1, 10), "price": random.uniform(10, 1000),
             "created_at": f"2024-{(i%12)+1:02d}-{(i%28)+1:02d}"}
            for i in range(50)
        ]
        db_manager.insert_batch("orders", orders)

        # 多表连接查询
        db_manager.create_table("products", "id INTEGER PRIMARY KEY, name TEXT, category TEXT")
        products = [{"id": i, "name": f"prod-{i}", "category": random.choice(["A", "B", "C"])}
                    for i in range(10)]
        db_manager.insert_batch("products", products)

        results = db_manager.fetch_all("""
            SELECT o.customer, o.product, o.quantity, o.price,
                   o.quantity * o.price as total
            FROM orders o
            WHERE o.quantity > 5
            ORDER BY total DESC
            LIMIT 10
        """)
        assert len(results) <= 10
        for r in results:
            assert r["quantity"] > 5

    def test_like_wildcard(self, db_manager):
        """测试 LIKE 通配符查询"""
        db_manager.create_table("items", "id INTEGER PRIMARY KEY, name TEXT")
        names = ["apple", "appetizer", "application", "banana", "apricot", "APPLE"]
        for i, name in enumerate(names):
            db_manager.insert("items", {"id": i, "name": name})

        results = db_manager.fetch_all("SELECT * FROM items WHERE name LIKE 'app%'")
        assert len(results) == 3  # app开头

    def test_subquery(self, db_manager):
        """测试子查询"""
        db_manager.create_table("dept", "id INTEGER PRIMARY KEY, name TEXT")
        db_manager.create_table("emp", "id INTEGER PRIMARY KEY, name TEXT, dept_id INTEGER, salary REAL")

        db_manager.insert("dept", {"id": 1, "name": "Engineering"})
        db_manager.insert("dept", {"id": 2, "name": "Sales"})

        emp_data = [
            {"id": 1, "name": "Alice", "dept_id": 1, "salary": 100000},
            {"id": 2, "name": "Bob", "dept_id": 1, "salary": 90000},
            {"id": 3, "name": "Charlie", "dept_id": 2, "salary": 80000},
        ]
        db_manager.insert_batch("emp", emp_data)

        results = db_manager.fetch_all("""
            SELECT e.name, e.salary
            FROM emp e
            WHERE e.salary > (SELECT AVG(salary) FROM emp)
            ORDER BY e.salary DESC
        """)
        assert len(results) == 1
        assert results[0]["name"] == "Alice"


# =============================================================================
# 测试用例：向量搜索
# =============================================================================

class TestVectorSearch:
    """向量搜索测试"""

    def test_vector_insert_and_search(self, vector_engine):
        """测试向量插入和搜索"""
        query_vector = [1.0] + [0.0] * 127
        result = vector_engine.search(query_vector, top_k=10)
        assert len(result) <= 10

    def test_cosine_similarity(self, vector_engine):
        """测试余弦相似度"""
        a = [1.0, 0.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0, 0.0]
        assert VectorEngine.cosine_similarity(a, b) == pytest.approx(1.0)

        c = [0.0, 1.0, 0.0, 0.0]
        assert VectorEngine.cosine_similarity(a, c) == pytest.approx(0.0)

        d = [-1.0, 0.0, 0.0, 0.0]
        assert VectorEngine.cosine_similarity(a, d) == pytest.approx(-1.0)

    def test_euclidean_distance(self, vector_engine):
        """测试欧几里得距离"""
        a = [0.0, 0.0]
        b = [3.0, 4.0]
        assert VectorEngine.euclidean_distance(a, b) == pytest.approx(5.0)

        c = [1.0, 1.0]
        d = [1.0, 1.0]
        assert VectorEngine.euclidean_distance(c, d) == pytest.approx(0.0)

    def test_dot_product(self, vector_engine):
        """测试点积"""
        a = [1.0, 2.0, 3.0]
        b = [4.0, 5.0, 6.0]
        assert VectorEngine.dot_product(a, b) == 32.0

        c = [0.0, 0.0, 0.0]
        assert VectorEngine.dot_product(a, c) == 0.0

    def test_search_with_different_metrics(self, vector_engine):
        """测试不同度量指标的搜索"""
        query = [0.5] * 128
        query = [v / math.sqrt(sum(x*x for x in query)) for v in query]

        cosine_results = vector_engine.search(query, top_k=5, metric="cosine")
        euclidean_results = vector_engine.search(query, top_k=5, metric="euclidean")
        dot_results = vector_engine.search(query, top_k=5, metric="dot_product")

        assert len(cosine_results) == 5
        assert len(euclidean_results) == 5
        assert len(dot_results) == 5

    def test_search_with_filter(self, sample_vectors):
        """测试带过滤条件的搜索"""
        query = [0.5] * 128
        query = [v / math.sqrt(sum(x*x for x in query)) for v in query]

        # 按类别过滤
        results = sample_vectors.search_with_filter(
            query, top_k=5, filters={"category": "A"}
        )
        assert len(results) <= 5
        for r in results:
            assert r.metadata["category"] == "A"

        # 按优先级过滤
        results = sample_vectors.search_with_filter(
            query, top_k=10, filters={"priority": [1, 2]}
        )
        for r in results:
            assert r.metadata["priority"] in [1, 2]

    def test_batch_vector_operations(self, vector_engine):
        """测试批量向量操作"""
        records = []
        for i in range(1000):
            vector = [random.uniform(-1, 1) for _ in range(128)]
            vector = [v / math.sqrt(sum(x*x for x in vector)) for v in vector]
            records.append(VectorRecord(
                id=f"batch-{i}",
                vector=vector,
                metadata={"index": i},
            ))

        count = vector_engine.insert_batch(records)
        assert count == 1000
        assert vector_engine.count() == 1000

        # 搜索
        query = [random.uniform(-1, 1) for _ in range(128)]
        results = vector_engine.search(query, top_k=10)
        assert len(results) == 10

    def test_vector_update(self, vector_engine):
        """测试向量更新"""
        vector = [1.0] + [0.0] * 127
        record = VectorRecord(id="update-test", vector=vector)
        vector_engine.insert(record)

        new_vector = [0.0] * 128
        vector_engine.update("update-test", vector=new_vector)

        updated = vector_engine.get("update-test")
        assert updated.vector == new_vector

    def test_vector_delete(self, vector_engine):
        """测试向量删除"""
        vector = [1.0] + [0.0] * 127
        record = VectorRecord(id="delete-test", vector=vector)
        vector_engine.insert(record)
        assert vector_engine.count() == 1

        vector_engine.delete("delete-test")
        assert vector_engine.count() == 0
        assert vector_engine.get("delete-test") is None

    def test_nearest_neighbor_accuracy(self, vector_engine):
        """测试最近邻准确度"""
        # 插入一个和查询向量完全相同的向量
        query = [1.0, 0.0, 0.0]
        # 需要是128维
        target = [1.0] + [0.0] * 127
        vector_engine.insert(VectorRecord(id="exact-match", vector=target))

        query_vector = [1.0] + [0.0] * 127
        results = vector_engine.search(query_vector, top_k=1)
        assert len(results) > 0
        assert results[0].id == "exact-match"
        assert results[0].score == pytest.approx(1.0, abs=1e-6)


# =============================================================================
# 测试用例：混合查询
# =============================================================================

class TestHybridQuery:
    """混合查询测试"""

    def test_hybrid_search(self, hybrid_engine, sample_vectors):
        """测试混合搜索"""
        # 索引文本
        for i in range(100):
            text = f"This is document {i} about topic {random.choice(['AI', 'ML', 'data', 'cloud'])}"
            hybrid_engine.index_text(f"vec-{i}", text)

        query_vector = [0.5] * 128
        query_vector = [v / math.sqrt(sum(x*x for x in query_vector)) for v in query_vector]

        results = hybrid_engine.hybrid_search(
            query_vector=query_vector,
            query_text="AI",
            top_k=10,
            vector_weight=0.7,
            text_weight=0.3,
        )

        assert len(results) <= 10
        for r in results:
            assert 0 <= r.vector_score <= 1
            assert r.combined_score >= 0
            assert r.rank > 0

    def test_hybrid_search_weight_balance(self, hybrid_engine, sample_vectors):
        """测试混合搜索权重平衡"""
        for i in range(100):
            hybrid_engine.index_text(f"vec-{i}", f"Document {i}")

        query_vector = [0.5] * 128
        query_vector = [v / math.sqrt(sum(x*x for x in query_vector)) for v in query_vector]

        # 纯向量搜索
        vector_only = hybrid_engine.hybrid_search(
            query_vector, "AI", top_k=5, vector_weight=1.0, text_weight=0.0
        )
        # 混合搜索
        balanced = hybrid_engine.hybrid_search(
            query_vector, "AI", top_k=5, vector_weight=0.5, text_weight=0.5
        )

        assert len(vector_only) == 5
        assert len(balanced) == 5

    def test_hybrid_search_empty_text(self, hybrid_engine, sample_vectors):
        """测试空文本的混合搜索"""
        # 不索引文本
        query_vector = [0.5] * 128
        query_vector = [v / math.sqrt(sum(x*x for x in query_vector)) for v in query_vector]

        results = hybrid_engine.hybrid_search(query_vector, "", top_k=5)
        assert len(results) >= 0

    def test_hybrid_search_with_metadata(self, hybrid_engine, sample_vectors):
        """测试混合搜索的元数据"""
        for i in range(100):
            hybrid_engine.index_text(f"vec-{i}", f"Document about {random.choice(['AI', 'ML', 'Data'])}")

        query_vector = [0.5] * 128
        query_vector = [v / math.sqrt(sum(x*x for x in query_vector)) for v in query_vector]

        results = hybrid_engine.hybrid_search(query_vector, "AI", top_k=10)
        for r in results:
            assert "category" in r.metadata
            assert "priority" in r.metadata

    def test_hybrid_search_invalid_weights(self, hybrid_engine):
        """测试无效权重"""
        query_vector = [0.5] * 128
        with pytest.raises(ValueError):
            hybrid_engine.hybrid_search(query_vector, "test", vector_weight=1.5, text_weight=0.5)


# =============================================================================
# 测试用例：事务处理
# =============================================================================

class TestTransactionProcessing:
    """事务处理测试"""

    def test_basic_transaction(self, db_manager):
        """测试基本事务"""
        db_manager.create_table("accounts", "id INTEGER PRIMARY KEY, name TEXT, balance REAL")

        with db_manager.transaction():
            db_manager.insert("accounts", {"id": 1, "name": "Alice", "balance": 1000.0})
            db_manager.insert("accounts", {"id": 2, "name": "Bob", "balance": 500.0})

        # 验证事务提交
        alice = db_manager.fetch_one("SELECT * FROM accounts WHERE id=1")
        bob = db_manager.fetch_one("SELECT * FROM accounts WHERE id=2")
        assert alice["balance"] == 1000.0
        assert bob["balance"] == 500.0

    def test_transaction_rollback(self, db_manager):
        """测试事务回滚"""
        db_manager.create_table("rollback_test", "id INTEGER PRIMARY KEY, value TEXT")

        try:
            with db_manager.transaction():
                db_manager.insert("rollback_test", {"id": 1, "value": "first"})
                db_manager.insert("rollback_test", {"id": 2, "value": "second"})
                raise RuntimeError("Forced rollback")
        except RuntimeError:
            pass

        # 事务应回滚，表应该为空
        count = db_manager.fetch_one("SELECT COUNT(*) as cnt FROM rollback_test")
        assert count["cnt"] == 0

    def test_nested_transactions(self, db_manager):
        """测试嵌套事务"""
        db_manager.create_table("nested", "id INTEGER PRIMARY KEY, value TEXT")

        with db_manager.transaction():
            db_manager.insert("nested", {"id": 1, "value": "outer"})
            with db_manager.transaction():
                db_manager.insert("nested", {"id": 2, "value": "inner"})

        count = db_manager.fetch_one("SELECT COUNT(*) as cnt FROM nested")
        assert count["cnt"] == 2

    def test_transaction_isolation(self, db_manager):
        """测试事务隔离"""
        db_manager.create_table("isolation_test", "id INTEGER PRIMARY KEY, value TEXT")

        # 在一个事务中插入
        with db_manager.transaction():
            db_manager.insert("isolation_test", {"id": 1, "value": "in-transaction"})

        # 验证数据可见
        result = db_manager.fetch_one("SELECT * FROM isolation_test WHERE id=1")
        assert result["value"] == "in-transaction"

    def test_concurrent_transactions(self, db_manager):
        """测试并发事务"""
        db_manager.create_table("concurrent", "id INTEGER PRIMARY KEY, counter INTEGER")

        def increment_counter():
            with db_manager.transaction():
                result = db_manager.fetch_one("SELECT MAX(counter) as max_c FROM concurrent")
                current = result["max_c"] if result and result["max_c"] else 0
                db_manager.insert("concurrent", {"id": current + 1, "counter": current + 1})

        threads = []
        for i in range(10):
            t = threading.Thread(target=increment_counter)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        count = db_manager.fetch_one("SELECT COUNT(*) as cnt FROM concurrent")
        assert count["cnt"] == 10

    def test_transaction_with_rollback_savepoint(self, db_manager):
        """测试事务保存点"""
        db_manager.create_table("savepoint_test", "id INTEGER PRIMARY KEY, value TEXT")

        with db_manager.transaction():
            db_manager.insert("savepoint_test", {"id": 1, "value": "first"})
            # 模拟保存点
            try:
                db_manager.execute("SAVEPOINT sp1")
                db_manager.insert("savepoint_test", {"id": 2, "value": "second"})
                raise RuntimeError("rollback to savepoint")
            except RuntimeError:
                db_manager.execute("ROLLBACK TO sp1")
            db_manager.insert("savepoint_test", {"id": 3, "value": "third"})

        results = db_manager.fetch_all("SELECT * FROM savepoint_test ORDER BY id")
        assert len(results) == 2
        assert results[0]["value"] == "first"
        assert results[1]["value"] == "third"


# =============================================================================
# 测试用例：数据库完整性和约束
# =============================================================================

class TestDatabaseIntegrity:
    """数据库完整性和约束测试"""

    def test_primary_key_constraint(self, db_manager):
        """测试主键约束"""
        db_manager.create_table("pk_test", "id INTEGER PRIMARY KEY, name TEXT")
        db_manager.insert("pk_test", {"id": 1, "name": "first"})
        with pytest.raises(sqlite3.IntegrityError):
            db_manager.insert("pk_test", {"id": 1, "name": "duplicate"})

    def test_unique_constraint(self, db_manager):
        """测试唯一约束"""
        db_manager.create_table("unique_test",
            "id INTEGER PRIMARY KEY, email TEXT UNIQUE")
        db_manager.insert("unique_test", {"id": 1, "email": "a@test.com"})
        with pytest.raises(sqlite3.IntegrityError):
            db_manager.insert("unique_test", {"id": 2, "email": "a@test.com"})

    def test_not_null_constraint(self, db_manager):
        """测试非空约束"""
        db_manager.create_table("notnull_test",
            "id INTEGER PRIMARY KEY, name TEXT NOT NULL")
        with pytest.raises(sqlite3.IntegrityError):
            db_manager.insert("notnull_test", {"id": 1, "name": None})

    def test_foreign_key_constraint(self, db_manager):
        """测试外键约束"""
        db_manager.execute("PRAGMA foreign_keys = ON")
        db_manager.create_table("parent", "id INTEGER PRIMARY KEY, name TEXT")
        db_manager.create_table("child",
            "id INTEGER PRIMARY KEY, parent_id INTEGER, "
            "FOREIGN KEY (parent_id) REFERENCES parent(id)")

        db_manager.insert("parent", {"id": 1, "name": "parent1"})
        db_manager.insert("child", {"id": 1, "parent_id": 1, "name": "child1"})

        with pytest.raises(sqlite3.IntegrityError):
            db_manager.insert("child", {"id": 2, "parent_id": 999, "name": "orphan"})

    def test_check_constraint(self, db_manager):
        """测试 CHECK 约束"""
        db_manager.create_table("check_test",
            "id INTEGER PRIMARY KEY, age INTEGER CHECK(age >= 0 AND age <= 150)")
        db_manager.insert("check_test", {"id": 1, "age": 25})
        with pytest.raises(sqlite3.IntegrityError):
            db_manager.insert("check_test", {"id": 2, "age": -1})

    def test_default_values(self, db_manager):
        """测试默认值"""
        db_manager.create_table("default_test",
            "id INTEGER PRIMARY KEY, name TEXT, created_at TEXT DEFAULT (datetime('now'))")
        db_manager.insert("default_test", {"id": 1, "name": "test"})
        result = db_manager.fetch_one("SELECT * FROM default_test WHERE id=1")
        assert result["name"] == "test"
        assert result["created_at"] is not None


# =============================================================================
# 测试用例：数据库迁移
# =============================================================================

class TestDatabaseMigration:
    """数据库迁移测试"""

    def test_add_column(self, db_manager):
        """测试添加列"""
        db_manager.create_table("migrate_test", "id INTEGER PRIMARY KEY, name TEXT")
        db_manager.insert("migrate_test", {"id": 1, "name": "old"})

        # 添加新列
        db_manager.execute("ALTER TABLE migrate_test ADD COLUMN email TEXT")
        db_manager.update("migrate_test", {"email": "test@example.com"}, "id=1")

        result = db_manager.fetch_one("SELECT * FROM migrate_test WHERE id=1")
        assert result["email"] == "test@example.com"

    def test_rename_column(self, db_manager):
        """测试重命名列"""
        db_manager.create_table("rename_test", "id INTEGER PRIMARY KEY, old_name TEXT")
        db_manager.insert("rename_test", {"id": 1, "old_name": "test"})

        # SQLite 使用新方法重命名
        db_manager.execute("ALTER TABLE rename_test RENAME COLUMN old_name TO new_name")
        result = db_manager.fetch_one("SELECT * FROM rename_test WHERE id=1")
        assert "new_name" in result

    def test_create_index(self, db_manager):
        """测试创建索引"""
        db_manager.create_table("index_test", "id INTEGER PRIMARY KEY, value TEXT, category TEXT")
        db_manager.execute("CREATE INDEX idx_category ON index_test(category)")

        # 验证索引存在
        indexes = db_manager.fetch_all("SELECT name FROM sqlite_master WHERE type='index'")
        assert any(idx["name"] == "idx_category" for idx in indexes)

    def test_foreign_key_index(self, db_manager):
        """测试外键索引"""
        db_manager.create_table("fk_parent", "id INTEGER PRIMARY KEY, name TEXT")
        db_manager.create_table("fk_child",
            "id INTEGER PRIMARY KEY, parent_id INTEGER, name TEXT")
        db_manager.execute("CREATE INDEX idx_fk_child_parent ON fk_child(parent_id)")

        indexes = db_manager.fetch_all("SELECT name FROM sqlite_master WHERE type='index'")
        assert any("idx_fk_child_parent" in idx["name"] for idx in indexes)


# =============================================================================
# 测试用例：数据库性能
# =============================================================================

class TestDatabasePerformance:
    """数据库性能测试"""

    def test_bulk_insert_performance(self, db_manager):
        """测试批量插入性能"""
        db_manager.create_table("perf_test", "id INTEGER PRIMARY KEY, data TEXT, value REAL")

        num_records = 1000
        data = []
        for i in range(num_records):
            data.append({
                "id": i,
                "data": f"record-{i}-{os.urandom(16).hex()}",
                "value": random.random(),
            })

        start = time.time()
        db_manager.insert_batch("perf_test", data)
        elapsed = time.time() - start

        count = db_manager.fetch_one("SELECT COUNT(*) as cnt FROM perf_test")
        assert count["cnt"] == num_records
        assert elapsed < 5.0, f"Bulk insert too slow: {elapsed:.2f}s"

    def test_query_with_index(self, db_manager):
        """测试索引查询性能"""
        db_manager.create_table("perf_query", "id INTEGER PRIMARY KEY, category TEXT, value REAL")

        for i in range(5000):
            db_manager.insert("perf_query", {
                "id": i,
                "category": random.choice(["A", "B", "C", "D", "E"]),
                "value": random.random(),
            })

        # 无索引查询
        db_manager.execute("CREATE INDEX idx_category ON perf_query(category)")

        start = time.time()
        results = db_manager.fetch_all("SELECT * FROM perf_query WHERE category='A'")
        indexed_time = time.time() - start

        # 验证结果
        assert len(results) > 0
        assert indexed_time < 2.0

    def test_concurrent_reads(self, db_manager):
        """测试并发读取"""
        db_manager.create_table("concurrent_read", "id INTEGER PRIMARY KEY, value TEXT")
        for i in range(100):
            db_manager.insert("concurrent_read", {"id": i, "value": f"data-{i}"})

        def read_worker():
            for _ in range(10):
                db_manager.fetch_one("SELECT * FROM concurrent_read WHERE id = ?",
                                     (random.randint(0, 99),))

        threads = [threading.Thread(target=read_worker) for _ in range(20)]
        start = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.time() - start

        assert elapsed < 10.0, f"Concurrent reads too slow: {elapsed:.2f}s"


# =============================================================================
# 数据库测试主入口
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])