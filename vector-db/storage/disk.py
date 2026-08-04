"""
Disk-based storage backend using memory-mapped files (mmap).

Provides persistent storage with memory-mapped access for efficient
random access to large vector collections without loading everything into RAM.
"""

import os
import mmap
import json
import numpy as np
import pickle
from typing import Any, Dict, List, Optional, Tuple, Union
from threading import Lock, RLock
from pathlib import Path


class DiskStorage:
    """Disk-backed storage using memory-mapped numpy arrays.

    Primary data is stored in .npy files (memory-mapped), with metadata
    in a separate JSON file. This allows working with datasets larger than RAM.

    File layout:
        base_path/
            vectors.npy       # Memory-mapped array of shape (N, D)
            ids.npy           # Memory-mapped array of shape (N,)
            metadata.json     # Metadata dictionary
            info.json         # Storage metadata (dimension, dtype, etc.)
    """

    def __init__(self, dimension: int, dtype: np.dtype = np.float32,
                 base_path: Optional[str] = None):
        self.dimension = dimension
        self.dtype = dtype
        self.base_path = base_path

        self._vectors: Optional[np.memmap] = None
        self._ids: Optional[np.memmap] = None
        self._metadata: Dict[int, Dict[str, Any]] = {}
        self._id_to_index: Dict[int, int] = {}

        self._size = 0
        self._capacity = 0
        self._lock = RLock()

        self._dirty = False
        self._page_size = 4096  # Typical OS page size

    def _ensure_paths(self, base_path: str):
        """Create necessary directories and file paths."""
        path = Path(base_path)
        path.mkdir(parents=True, exist_ok=True)
        self._vec_path = str(path / "vectors.npy")
        self._ids_path = str(path / "ids.npy")
        self._meta_path = str(path / "metadata.json")
        self._info_path = str(path / "info.json")

    def _create_memmap(self, capacity: int):
        """Create memory-mapped arrays with the given capacity."""
        # Create vectors file
        vec_shape = (capacity, self.dimension)
        self._vectors = np.memmap(
            self._vec_path, dtype=self.dtype, mode='w+', shape=vec_shape
        )

        # Create IDs file
        self._ids = np.memmap(
            self._ids_path, dtype=np.int64, mode='w+', shape=(capacity,)
        )

        self._capacity = capacity
        self._save_info()

    def _open_memmap(self):
        """Open existing memory-mapped arrays."""
        # Load info first
        self._load_info()

        # Open vectors
        self._vectors = np.memmap(
            self._vec_path, dtype=self.dtype, mode='r+',
            shape=(self._capacity, self._dimension)
        )

        # Open IDs
        self._ids = np.memmap(
            self._ids_path, dtype=np.int64, mode='r+',
            shape=(self._capacity,)
        )

    def _load_info(self):
        """Load storage metadata from info.json."""
        with open(self._info_path, 'r') as f:
            info = json.load(f)
        self._dimension = info['dimension']
        self._dtype = np.dtype(info['dtype'])
        self._capacity = info['capacity']
        self._size = info['size']

    def _save_info(self):
        """Save storage metadata to info.json."""
        info = {
            'dimension': self.dimension,
            'dtype': str(self.dtype),
            'capacity': self._capacity,
            'size': self._size,
        }
        with open(self._info_path, 'w') as f:
            json.dump(info, f)

    def _load_metadata(self):
        """Load metadata from metadata.json."""
        if os.path.exists(self._meta_path):
            with open(self._meta_path, 'r') as f:
                raw = json.load(f)
            # Convert string keys back to ints
            self._metadata = {int(k): v for k, v in raw.items()}
            # Rebuild ID-to-index mapping
            self._id_to_index = {}
            for i in range(self._size):
                id_val = int(self._ids[i])
                if id_val != -1:
                    self._id_to_index[id_val] = i

    def _save_metadata(self):
        """Save metadata to metadata.json."""
        with open(self._meta_path, 'w') as f:
            json.dump(self._metadata, f, default=str)

    def _grow(self, min_capacity: Optional[int] = None):
        """Grow the memory-mapped storage."""
        if min_capacity is None:
            new_capacity = int(self._capacity * 1.5) + 1024
        else:
            new_capacity = max(min_capacity, self._capacity + 1024)

        # Flush current data
        if self._vectors is not None:
            self._vectors.flush()
        if self._ids is not None:
            self._ids.flush()

        # Save current state
        old_size = self._size
        old_capacity = self._capacity

        # Create new arrays with larger capacity
        self._create_memmap(new_capacity)

        # Copy old data if exists
        if old_capacity > 0:
            self._vectors[:old_size] = np.memmap(
                self._vec_path, dtype=self.dtype, mode='r',
                shape=(old_size, self.dimension)
            )[:old_size]
            self._ids[:old_size] = np.memmap(
                self._ids_path, dtype=np.int64, mode='r',
                shape=(old_size,)
            )[:old_size]

        self._size = old_size

    def open(self, base_path: str):
        """Open an existing storage or create a new one."""
        self._ensure_paths(base_path)
        self.base_path = base_path

        if os.path.exists(self._info_path):
            # Load existing storage
            self._open_memmap()
            self._load_metadata()
        else:
            # Create new storage
            self._create_memmap(1024)

        self._dirty = False

    def close(self):
        """Close the storage and flush data to disk."""
        with self._lock:
            if self._vectors is not None:
                self._vectors.flush()
                self._vectors = None
            if self._ids is not None:
                self._ids.flush()
                self._ids = None
            if self._dirty:
                self._save_metadata()
                self._save_info()
                self._dirty = False

    def insert(self, vectors: np.ndarray, ids: Optional[np.ndarray] = None,
               metadata: Optional[List[Optional[Dict[str, Any]]]] = None) -> int:
        """Insert vectors into disk storage.

        Args:
            vectors: Array of shape (N, D)
            ids: Optional array of IDs. Auto-generated if None.
            metadata: Optional list of metadata dicts.

        Returns:
            Number of vectors inserted.
        """
        with self._lock:
            n = vectors.shape[0]

            if ids is None:
                start_id = max(self._id_to_index.keys()) + 1 if self._id_to_index else 0
                ids = np.arange(start_id, start_id + n, dtype=np.int64)
            else:
                ids = np.asarray(ids, dtype=np.int64)

            if metadata is None:
                metadata = [None] * n

            # Ensure capacity
            needed = self._size + n
            if needed > self._capacity:
                self._grow(needed)

            # Store vectors
            self._vectors[self._size:needed] = vectors.astype(self.dtype)

            # Store IDs
            self._ids[self._size:needed] = ids

            # Update metadata and index
            for i in range(n):
                idx = self._size + i
                id_val = int(ids[i])
                self._id_to_index[id_val] = idx
                if metadata[i] is not None:
                    self._metadata[id_val] = metadata[i]

            self._size = needed
            self._dirty = True

            return n

    def get(self, ids: List[int]) -> Tuple[np.ndarray, List[int], List[Optional[Dict[str, Any]]]]:
        """Retrieve vectors by their IDs.

        Args:
            ids: List of vector IDs to retrieve.

        Returns:
            Tuple of (vectors, found_ids, metadata).
        """
        with self._lock:
            found_indices = []
            found_ids = []
            for id_val in ids:
                if id_val in self._id_to_index:
                    idx = self._id_to_index[id_val]
                    if idx < self._size and self._ids[idx] != -1:
                        found_indices.append(idx)
                        found_ids.append(id_val)

            if not found_indices:
                return np.empty((0, self.dimension), dtype=self.dtype), [], []

            vectors = np.array([self._vectors[idx] for idx in found_indices])
            metadata = [self._metadata.get(id_val) for id_val in found_ids]
            return vectors, found_ids, metadata

    def delete(self, ids: List[int]) -> int:
        """Delete vectors by their IDs.

        Args:
            ids: List of vector IDs to delete.

        Returns:
            Number of vectors deleted.
        """
        with self._lock:
            count = 0
            for id_val in ids:
                if id_val in self._id_to_index:
                    idx = self._id_to_index.pop(id_val)
                    self._ids[idx] = -1  # Mark as deleted
                    self._metadata.pop(id_val, None)
                    count += 1

            if count > 0:
                self._dirty = True

            return count

    def compact(self) -> int:
        """Compact storage by removing deleted vectors.

        Creates new memory-mapped files without the deleted entries.

        Returns:
            Number of vectors after compaction.
        """
        with self._lock:
            valid_indices = [i for i in range(self._size) if self._ids[i] != -1]
            new_size = len(valid_indices)

            if new_size == self._size:
                return new_size  # Nothing to compact

            # Save data to temporary arrays
            old_vectors = np.array([self._vectors[i] for i in valid_indices])
            old_ids = np.array([int(self._ids[i]) for i in valid_indices])

            # Create new memmaps
            self._create_memmap(max(new_size, 1024))

            # Copy data
            self._vectors[:new_size] = old_vectors
            self._ids[:new_size] = old_ids

            # Rebuild index
            self._id_to_index = {int(old_ids[i]): i for i in range(new_size)}

            self._size = new_size
            self._dirty = True

            return new_size

    def get_all_vectors(self) -> Tuple[np.ndarray, List[int], List[Optional[Dict[str, Any]]]]:
        """Get all vectors, IDs, and metadata.

        Returns:
            Tuple of (vectors, ids, metadata).
        """
        with self._lock:
            valid_indices = [i for i in range(self._size) if self._ids[i] != -1]
            if not valid_indices:
                return np.empty((0, self.dimension), dtype=self.dtype), [], []

            vectors = np.array([self._vectors[i] for i in valid_indices])
            ids = [int(self._ids[i]) for i in valid_indices]
            metadata = [self._metadata.get(id_val) for id_val in ids]
            return vectors, ids, metadata

    def get_vectors_array(self) -> np.ndarray:
        """Get the valid vectors as a numpy array."""
        with self._lock:
            valid_indices = [i for i in range(self._size) if self._ids[i] != -1]
            if not valid_indices:
                return np.empty((0, self.dimension), dtype=self.dtype)
            return np.array([self._vectors[i] for i in valid_indices])

    def get_ids_array(self) -> np.ndarray:
        """Get the valid IDs as a numpy array."""
        with self._lock:
            return np.array([int(self._ids[i]) for i in range(self._size)
                           if self._ids[i] != -1], dtype=np.int64)

    def size(self) -> int:
        """Get the number of valid vectors."""
        with self._lock:
            return len(self._id_to_index)

    def memory_usage(self) -> Dict[str, int]:
        """Get storage usage statistics."""
        with self._lock:
            vec_bytes = self._size * self.dimension * np.dtype(self.dtype).itemsize
            meta_bytes = sum(len(json.dumps(v, default=str)) * 2
                           for v in self._metadata.values())
            return {
                "vector_bytes": vec_bytes,
                "metadata_bytes": meta_bytes,
                "total_bytes": vec_bytes + meta_bytes,
                "vector_count": self._size,
                "capacity": self._capacity,
                "disk_path": self.base_path,
            }

    def clear(self):
        """Clear all data and reset storage."""
        with self._lock:
            self._metadata.clear()
            self._id_to_index.clear()
            self._size = 0
            self._dirty = True

            if self._vectors is not None:
                self._vectors.flush()
                self._vectors = None
            if self._ids is not None:
                self._ids.flush()
                self._ids = None

            # Remove files
            for path in [self._vec_path, self._ids_path, self._meta_path, self._info_path]:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except OSError:
                    pass

            self._capacity = 0

    def flush(self):
        """Flush data to disk immediately."""
        with self._lock:
            if self._vectors is not None:
                self._vectors.flush()
            if self._ids is not None:
                self._ids.flush()
            if self._dirty:
                self._save_metadata()
                self._save_info()
                self._dirty = False

    def __del__(self):
        """Cleanup on deletion."""
        try:
            self.close()
        except Exception:
            pass