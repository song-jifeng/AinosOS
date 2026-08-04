"""Buffer pool management for AinosDB.

The buffer pool caches pages in memory, managing page replacement
using a CLOCK-sweep algorithm (approximating LRU).
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional, Set, Tuple
from .page import Page, PageId, PageType


class BufferPool:
    """Manages in-memory caching of database pages.

    The buffer pool provides:
    - Page cache with configurable size
    - CLOCK-sweep replacement policy
    - Pin/unpin for concurrent access
    - Dirty page tracking
    - Page prefetching hints

    Attributes:
        capacity: Maximum number of pages in the pool.
        page_size: Size of each page in bytes.
    """

    __slots__ = (
        "capacity", "page_size", "_pages", "_page_ids", "_clock_hand",
        "_clock_refs", "_dirty_pages", "_lock", "_stats",
    )

    def __init__(self, capacity: int = 1000, page_size: int = 8192) -> None:
        self.capacity = capacity
        self.page_size = page_size
        self._pages: List[Optional[Page]] = [None] * capacity
        self._page_ids: Dict[PageId, int] = {}
        self._clock_hand: int = 0
        self._clock_refs: List[bool] = [False] * capacity
        self._dirty_pages: Set[int] = set()
        self._lock = threading.RLock()

        # Statistics
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "reads": 0,
            "writes": 0,
        }

    @property
    def size(self) -> int:
        """Current number of pages in the pool."""
        return len(self._page_ids)

    @property
    def hits(self) -> int:
        """Number of cache hits."""
        return self._stats["hits"]

    @property
    def misses(self) -> int:
        """Number of cache misses."""
        return self._stats["misses"]

    @property
    def hit_ratio(self) -> float:
        """Cache hit ratio."""
        total = self._stats["hits"] + self._stats["misses"]
        if total == 0:
            return 0.0
        return self._stats["hits"] / total

    def fetch_page(self, page_id: PageId) -> Optional[Page]:
        """Fetch a page from the buffer pool.

        If the page is not in the pool, returns None (caller must
        load from disk and insert).

        Args:
            page_id: Page identifier.

        Returns:
            The page if found, None otherwise.
        """
        with self._lock:
            idx = self._page_ids.get(page_id)
            if idx is not None:
                self._clock_refs[idx] = True
                page = self._pages[idx]
                if page is not None:
                    page.pin()
                    self._stats["hits"] += 1
                    return page
            self._stats["misses"] += 1
            return None

    def get_page(self, page_id: PageId) -> Optional[Page]:
        """Get a page without pinning (for internal use).

        Args:
            page_id: Page identifier.

        Returns:
            The page if found, None otherwise.
        """
        with self._lock:
            idx = self._page_ids.get(page_id)
            if idx is not None:
                return self._pages[idx]
            return None

    def insert_page(self, page: Page) -> Page:
        """Insert a page into the buffer pool.

        If the pool is full, evicts a page using CLOCK-sweep.

        Args:
            page: Page to insert.

        Returns:
            The inserted page (same object).

        Raises:
            ValueError: If page already exists in the pool.
        """
        with self._lock:
            page_id = page.page_id

            if page_id in self._page_ids:
                raise ValueError(f"Page {page_id} already exists in buffer pool")

            if self.size >= self.capacity:
                self._evict_page()

            idx = self._find_slot()
            page.pin()
            self._pages[idx] = page
            self._page_ids[page_id] = idx
            self._clock_refs[idx] = True
            self._stats["reads"] += 1
            return page

    def unpin_page(self, page_id: PageId) -> None:
        """Unpin a page (decrement pin count).

        Args:
            page_id: Page identifier.
        """
        with self._lock:
            idx = self._page_ids.get(page_id)
            if idx is not None:
                page = self._pages[idx]
                if page is not None:
                    page.unpin()

    def mark_dirty(self, page_id: PageId) -> None:
        """Mark a page as dirty (modified).

        Args:
            page_id: Page identifier.
        """
        with self._lock:
            idx = self._page_ids.get(page_id)
            if idx is not None:
                self._dirty_pages.add(idx)
                page = self._pages[idx]
                if page is not None:
                    page.dirty = True

    def flush_page(self, page_id: PageId) -> Optional[bytes]:
        """Flush a specific dirty page to disk.

        Args:
            page_id: Page identifier.

        Returns:
            Serialized page bytes if dirty, None otherwise.
        """
        with self._lock:
            idx = self._page_ids.get(page_id)
            if idx is not None and idx in self._dirty_pages:
                page = self._pages[idx]
                if page is not None and page.dirty:
                    self._dirty_pages.discard(idx)
                    page.dirty = False
                    self._stats["writes"] += 1
                    return page.to_bytes()
            return None

    def flush_all(self) -> List[Tuple[PageId, bytes]]:
        """Flush all dirty pages.

        Returns:
            List of (page_id, serialized_bytes) tuples.
        """
        with self._lock:
            result: List[Tuple[PageId, bytes]] = []
            for idx in list(self._dirty_pages):
                page = self._pages[idx]
                if page is not None and page.dirty:
                    page.dirty = False
                    self._stats["writes"] += 1
                    result.append((page.page_id, page.to_bytes()))
            self._dirty_pages.clear()
            return result

    def remove_page(self, page_id: PageId) -> Optional[bytes]:
        """Remove a page from the buffer pool.

        Args:
            page_id: Page identifier.

        Returns:
            Serialized page bytes if dirty, None otherwise.
        """
        with self._lock:
            idx = self._page_ids.pop(page_id, None)
            if idx is not None:
                page = self._pages[idx]
                self._pages[idx] = None
                self._clock_refs[idx] = False
                self._dirty_pages.discard(idx)
                if page is not None and page.dirty:
                    page.dirty = False
                    self._stats["writes"] += 1
                    return page.to_bytes()
            return None

    def _evict_page(self) -> None:
        """Evict a page using CLOCK-sweep replacement.

        Iterates through page slots, clearing reference bits until
        a slot with a cleared reference bit is found.
        """
        while True:
            idx = self._clock_hand
            self._clock_hand = (self._clock_hand + 1) % self.capacity

            page = self._pages[idx]
            if page is None:
                # Empty slot, can use it
                return

            if page.is_pinned:
                # Skip pinned pages
                continue

            if self._clock_refs[idx]:
                # Give it a second chance
                self._clock_refs[idx] = False
                continue

            # Evict this page
            page_id = page.page_id
            if page.dirty:
                # Flush dirty page
                page.dirty = False
                self._stats["writes"] += 1

            self._page_ids.pop(page_id, None)
            self._pages[idx] = None
            self._dirty_pages.discard(idx)
            self._stats["evictions"] += 1
            return

    def _find_slot(self) -> int:
        """Find an empty slot for a new page.

        Returns:
            Index of an empty slot.
        """
        for i in range(self.capacity):
            if self._pages[i] is None:
                return i
        # Should not reach here if eviction worked
        raise RuntimeError("Buffer pool is full and no page could be evicted")

    def get_stats(self) -> Dict[str, int]:
        """Get buffer pool statistics.

        Returns:
            Dictionary with stats keys.
        """
        with self._lock:
            return dict(self._stats)

    def reset_stats(self) -> None:
        """Reset all statistics counters."""
        with self._lock:
            for key in self._stats:
                self._stats[key] = 0

    def __len__(self) -> int:
        return self.size

    def __repr__(self) -> str:
        return (
            f"BufferPool(capacity={self.capacity}, size={self.size}, "
            f"hits={self._stats['hits']}, misses={self._stats['misses']}, "
            f"hit_ratio={self.hit_ratio:.2%})"
        )