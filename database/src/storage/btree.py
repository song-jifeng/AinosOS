"""B+ Tree implementation for AinosDB storage engine.

The B+ tree provides ordered key-value storage with efficient
insertion, deletion, and range queries. All leaf nodes are linked
for efficient sequential access.
"""

from __future__ import annotations

import struct
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Union
from .page import Page, PageId, PageType
from ..utils.serializer import Serializer


class BTreeNode:
    """A node in the B+ tree.

    Can be either an internal node (with children pointers) or a
    leaf node (with key-value pairs and next/prev leaf pointers).

    Attributes:
        page: Underlying page storage.
        is_leaf: Whether this is a leaf node.
        keys: List of keys in this node.
        values: List of values (leaf) or children PageIds (internal).
        next_leaf: PageId of next leaf (leaf nodes only, None if last).
        prev_leaf: PageId of previous leaf (leaf nodes only, None if first).
    """

    __slots__ = (
        "page", "is_leaf", "order", "keys", "values",
        "next_leaf", "prev_leaf", "parent",
    )

    def __init__(
        self,
        page: Page,
        order: int = 4,
        is_leaf: bool = True,
    ) -> None:
        self.page = page
        self.order = order
        self.is_leaf = is_leaf
        self.keys: List[Any] = []
        self.values: List[Any] = []
        self.next_leaf: Optional[PageId] = None
        self.prev_leaf: Optional[PageId] = None
        self.parent: Optional[PageId] = None
        self._deserialize()

    def _deserialize(self) -> None:
        """Deserialize node data from the page."""
        offset = Page.HEADER_SIZE
        data = bytes(self.page.data)

        if offset + 5 > len(data):
            return

        # Read node header
        # byte: is_leaf, int: num_keys, short: next_leaf_id, short: prev_leaf_id
        self.is_leaf = bool(data[offset])
        offset += 1
        num_keys = struct.unpack_from("!I", data, offset)[0]
        offset += 4

        # Next/prev leaf pointers (only meaningful for leaf nodes)
        next_id = struct.unpack_from("!i", data, offset)[0]
        offset += 4
        prev_id = struct.unpack_from("!i", data, offset)[0]
        offset += 4

        if next_id >= 0:
            self.next_leaf = PageId(next_id)
        else:
            self.next_leaf = None

        if prev_id >= 0:
            self.prev_leaf = PageId(prev_id)
        else:
            self.prev_leaf = None

        # Read keys and values
        self.keys = []
        self.values = []

        for _ in range(num_keys):
            try:
                key, offset = Serializer.decode(data, offset)
                self.keys.append(key)
            except (struct.error, ValueError, IndexError):
                break

        if self.is_leaf:
            for _ in range(len(self.keys)):
                try:
                    val, offset = Serializer.decode(data, offset)
                    self.values.append(val)
                except (struct.error, ValueError, IndexError):
                    self.values.append(None)
        else:
            for _ in range(len(self.keys) + 1):
                try:
                    child_id = struct.unpack_from("!i", data, offset)[0]
                    offset += 4
                    self.values.append(PageId(child_id))
                except (struct.error, ValueError, IndexError):
                    break

    def serialize(self) -> None:
        """Serialize node data back to the page."""
        self.page.clear()
        data = bytearray()

        # Node header
        data.append(1 if self.is_leaf else 0)
        data.extend(struct.pack("!I", len(self.keys)))
        data.extend(struct.pack("!i", self.next_leaf.page_num if self.next_leaf else -1))
        data.extend(struct.pack("!i", self.prev_leaf.page_num if self.prev_leaf else -1))

        # Keys
        for key in self.keys:
            data.extend(Serializer.encode(key))

        # Values
        if self.is_leaf:
            for val in self.values:
                data.extend(Serializer.encode(val))
        else:
            for child in self.values:
                data.extend(struct.pack("!i", child.page_num))

        self.page.write_data(Page.HEADER_SIZE, bytes(data))
        self.page.dirty = True

    @property
    def is_full(self) -> bool:
        """Check if the node is full (ready to split)."""
        max_keys = 2 * self.order
        return len(self.keys) >= max_keys

    @property
    def is_underflow(self) -> bool:
        """Check if the node has too few keys (needs merge/redistribute)."""
        min_keys = self.order
        return len(self.keys) < min_keys

    def __repr__(self) -> str:
        return (
            f"BTreeNode(leaf={self.is_leaf}, keys={len(self.keys)}, "
            f"page={self.page.page_id})"
        )


class BTree:
    """B+ Tree index structure.

    Provides ordered key-value storage with O(log n) operations.
    Supports point queries, range scans, and sequential iteration.

    Attributes:
        order: The order of the tree (max children = 2*order).
        buffer_pool: Buffer pool for page management.
        root_page_id: PageId of the root node.
    """

    __slots__ = ("order", "buffer_pool", "root_page_id", "_page_count", "_size")

    def __init__(
        self,
        buffer_pool: Any,
        order: int = 4,
        root_page_id: Optional[PageId] = None,
    ) -> None:
        self.order = order
        self.buffer_pool = buffer_pool
        self.root_page_id = root_page_id
        self._page_count = 0
        self._size = 0

        if root_page_id is None:
            self._create_root()

    def _create_root(self) -> None:
        """Create a new empty root node (leaf)."""
        page_id = PageId(self._allocate_page_num())
        page = Page(page_id, PageType.BTREE_ROOT)
        self.buffer_pool.insert_page(page)
        self.root_page_id = page_id

        node = BTreeNode(page, self.order, is_leaf=True)
        node.serialize()
        self._size = 0

    def _allocate_page_num(self) -> int:
        """Allocate a new page number."""
        self._page_count += 1
        return self._page_count

    def _get_node(self, page_id: PageId) -> BTreeNode:
        """Get a BTreeNode from the buffer pool.

        Args:
            page_id: Page identifier.

        Returns:
            BTreeNode for the given page.
        """
        page = self.buffer_pool.fetch_page(page_id)
        if page is None:
            raise ValueError(f"Page {page_id} not found in buffer pool")
        return BTreeNode(page, self.order)

    def _release_node(self, node: BTreeNode) -> None:
        """Release a node back to the buffer pool."""
        self.buffer_pool.unpin_page(node.page.page_id)

    def _find_leaf(self, key: Any) -> BTreeNode:
        """Find the leaf node that should contain the given key.

        Args:
            key: Key to search for.

        Returns:
            Leaf node where the key should be.
        """
        if self.root_page_id is None:
            raise ValueError("B+ tree has no root")

        node = self._get_node(self.root_page_id)

        while not node.is_leaf:
            # Find the correct child to descend into
            idx = 0
            while idx < len(node.keys) and key >= node.keys[idx]:
                idx += 1
            child_id = node.values[idx]
            self._release_node(node)
            node = self._get_node(child_id)

        return node

    def insert(self, key: Any, value: Any) -> None:
        """Insert a key-value pair into the tree.

        Args:
            key: Key to insert.
            value: Value to associate with the key.
        """
        if self.root_page_id is None:
            self._create_root()

        leaf = self._find_leaf(key)

        # Insert into leaf
        idx = 0
        while idx < len(leaf.keys) and key > leaf.keys[idx]:
            idx += 1

        if idx < len(leaf.keys) and key == leaf.keys[idx]:
            # Update existing key
            leaf.values[idx] = value
        else:
            leaf.keys.insert(idx, key)
            leaf.values.insert(idx, value)
            self._size += 1

        leaf.serialize()
        self._release_node(leaf)

        # Check if split needed
        if leaf.is_full:
            self._split_leaf(leaf)

    def _split_leaf(self, leaf: BTreeNode) -> None:
        """Split a full leaf node.

        Creates a new leaf node and redistributes keys evenly.

        Args:
            leaf: The full leaf node to split.
        """
        # Create new leaf node
        new_page_id = PageId(self._allocate_page_num())
        new_page = Page(new_page_id, PageType.BTREE_LEAF)
        self.buffer_pool.insert_page(new_page)
        new_leaf = BTreeNode(new_page, self.order, is_leaf=True)

        # Split keys and values
        split_idx = len(leaf.keys) // 2
        new_leaf.keys = leaf.keys[split_idx:]
        new_leaf.values = leaf.values[split_idx:]
        leaf.keys = leaf.keys[:split_idx]
        leaf.values = leaf.values[:split_idx]

        # Update leaf links
        new_leaf.next_leaf = leaf.next_leaf
        new_leaf.prev_leaf = leaf.page.page_id
        leaf.next_leaf = new_page_id

        leaf.serialize()
        new_leaf.serialize()
        self._release_node(new_leaf)

        # Insert split key into parent
        split_key = new_leaf.keys[0]
        self._insert_internal(split_key, new_page_id, leaf)

    def _insert_internal(
        self, key: Any, new_child: PageId, left_node: BTreeNode
    ) -> None:
        """Insert a key and child pointer into an internal node.

        Args:
            key: Key to insert.
            new_child: PageId of the new child node.
            left_node: Left sibling node that was split.
        """
        if left_node.parent is None:
            # Create new root
            self._create_new_root(key, left_node.page.page_id, new_child)
            return

        parent = self._get_node(left_node.parent)

        # Find insertion position
        idx = 0
        while idx < len(parent.keys) and key > parent.keys[idx]:
            idx += 1

        parent.keys.insert(idx, key)
        parent.values.insert(idx + 1, new_child)
        parent.serialize()

        self._release_node(parent)

        if parent.is_full:
            self._split_internal(parent)

    def _create_new_root(
        self, key: Any, left_child: PageId, right_child: PageId
    ) -> None:
        """Create a new root node when splitting.

        Args:
            key: The split key to promote.
            left_child: PageId of the left child.
            right_child: PageId of the right child.
        """
        new_root_id = PageId(self._allocate_page_num())
        new_root_page = Page(new_root_id, PageType.BTREE_ROOT)
        self.buffer_pool.insert_page(new_root_page)

        new_root = BTreeNode(new_root_page, self.order, is_leaf=False)
        new_root.keys = [key]
        new_root.values = [left_child, right_child]
        new_root.serialize()

        # Update children's parent pointers
        for child_id in [left_child, right_child]:
            child_node = self._get_node(child_id)
            child_node.parent = new_root_id
            child_node.serialize()
            self._release_node(child_node)

        self.root_page_id = new_root_id
        self._release_node(new_root)

    def _split_internal(self, node: BTreeNode) -> None:
        """Split a full internal node.

        Args:
            node: The full internal node to split.
        """
        new_page_id = PageId(self._allocate_page_num())
        new_page = Page(new_page_id, PageType.BTREE_INTERNAL)
        self.buffer_pool.insert_page(new_page)
        new_node = BTreeNode(new_page, self.order, is_leaf=False)

        # Split keys and values
        split_idx = len(node.keys) // 2
        promoted_key = node.keys[split_idx]

        new_node.keys = node.keys[split_idx + 1:]
        new_node.values = node.values[split_idx + 1:]
        node.keys = node.keys[:split_idx]
        node.values = node.values[:split_idx + 1]

        node.serialize()
        new_node.serialize()

        # Update children's parent pointers
        for child_id in new_node.values:
            child_node = self._get_node(child_id)
            child_node.parent = new_page_id
            child_node.serialize()
            self._release_node(child_node)

        self._release_node(new_node)

        # Insert promoted key into parent
        if node.parent is None:
            self._create_new_root(promoted_key, node.page.page_id, new_page_id)
        else:
            self._insert_internal(promoted_key, new_page_id, node)

    def search(self, key: Any) -> Optional[Any]:
        """Search for a key in the tree.

        Args:
            key: Key to search for.

        Returns:
            Value associated with the key, or None if not found.
        """
        if self.root_page_id is None:
            return None

        leaf = self._find_leaf(key)

        for i, k in enumerate(leaf.keys):
            if k == key:
                val = leaf.values[i]
                self._release_node(leaf)
                return val

        self._release_node(leaf)
        return None

    def delete(self, key: Any) -> bool:
        """Delete a key from the tree.

        Args:
            key: Key to delete.

        Returns:
            True if the key was found and deleted, False otherwise.
        """
        if self.root_page_id is None:
            return False

        leaf = self._find_leaf(key)

        for i, k in enumerate(leaf.keys):
            if k == key:
                leaf.keys.pop(i)
                leaf.values.pop(i)
                leaf.serialize()
                self._size -= 1
                self._release_node(leaf)
                self._handle_underflow(leaf)
                return True

        self._release_node(leaf)
        return False

    def _handle_underflow(self, node: BTreeNode) -> None:
        """Handle underflow in a node after deletion.

        May redistribute keys from siblings or merge nodes.

        Args:
            node: The node that may be under capacity.
        """
        if not node.is_underflow:
            return

        if node.parent is None:
            # Root node - may need to shrink tree
            if node.is_leaf and len(node.keys) == 0:
                # Empty tree, keep as is
                pass
            elif not node.is_leaf and len(node.keys) == 0 and len(node.values) == 1:
                # Root has one child - make child the new root
                child_id = node.values[0]
                child_node = self._get_node(child_id)
                child_node.parent = None
                child_node.page.page_type = PageType.BTREE_ROOT
                child_node.serialize()
                self.root_page_id = child_id
                self._release_node(child_node)
            return

        parent = self._get_node(node.parent)

        # Find position in parent
        pos = 0
        for i, child_id in enumerate(parent.values):
            if child_id == node.page.page_id:
                pos = i
                break

        # Try to redistribute from left sibling
        if pos > 0:
            left_sibling_id = parent.values[pos - 1]
            left = self._get_node(left_sibling_id)
            if len(left.keys) > self.order:
                self._redistribute_right(left, node, parent, pos - 1)
                self._release_node(left)
                self._release_node(parent)
                return
            self._release_node(left)

        # Try to redistribute from right sibling
        if pos < len(parent.values) - 1:
            right_sibling_id = parent.values[pos + 1]
            right = self._get_node(right_sibling_id)
            if len(right.keys) > self.order:
                self._redistribute_left(node, right, parent, pos)
                self._release_node(right)
                self._release_node(parent)
                return
            self._release_node(right)

        # Merge with sibling
        if pos > 0:
            left_sibling_id = parent.values[pos - 1]
            left = self._get_node(left_sibling_id)
            self._merge_nodes(left, node, parent, pos - 1)
            self._release_node(left)
        elif pos < len(parent.values) - 1:
            right_sibling_id = parent.values[pos + 1]
            right = self._get_node(right_sibling_id)
            self._merge_nodes(node, right, parent, pos)
            self._release_node(right)

        self._release_node(parent)

    def _redistribute_right(
        self, left: BTreeNode, right: BTreeNode, parent: BTreeNode, parent_idx: int
    ) -> None:
        """Redistribute keys from left sibling to right sibling.

        Args:
            left: Left sibling node.
            right: Right sibling node (underflow).
            parent: Parent node.
            parent_idx: Index of separator key in parent.
        """
        if left.is_leaf:
            # Move last key-value from left to right
            key = left.keys.pop()
            val = left.values.pop()
            right.keys.insert(0, key)
            right.values.insert(0, val)
            parent.keys[parent_idx] = right.keys[0]
        else:
            # Move separator and last child from left to right
            key = left.keys.pop()
            child = left.values.pop()
            right.keys.insert(0, parent.keys[parent_idx])
            right.values.insert(0, child)
            parent.keys[parent_idx] = key

            # Update child's parent
            child_node = self._get_node(child)
            child_node.parent = right.page.page_id
            child_node.serialize()
            self._release_node(child_node)

        left.serialize()
        right.serialize()
        parent.serialize()

    def _redistribute_left(
        self, left: BTreeNode, right: BTreeNode, parent: BTreeNode, parent_idx: int
    ) -> None:
        """Redistribute keys from right sibling to left sibling.

        Args:
            left: Left sibling node (underflow).
            right: Right sibling node.
            parent: Parent node.
            parent_idx: Index of separator key in parent.
        """
        if left.is_leaf:
            # Move first key-value from right to left
            key = right.keys.pop(0)
            val = right.values.pop(0)
            left.keys.append(key)
            left.values.append(val)
            parent.keys[parent_idx] = right.keys[0]
        else:
            # Move separator and first child from right to left
            key = right.keys.pop(0)
            child = right.values.pop(0)
            left.keys.append(parent.keys[parent_idx])
            left.values.append(child)
            parent.keys[parent_idx] = key

            # Update child's parent
            child_node = self._get_node(child)
            child_node.parent = left.page.page_id
            child_node.serialize()
            self._release_node(child_node)

        left.serialize()
        right.serialize()
        parent.serialize()

    def _merge_nodes(
        self, left: BTreeNode, right: BTreeNode, parent: BTreeNode, parent_idx: int
    ) -> None:
        """Merge two sibling nodes.

        All keys from right are moved to left, and right is removed.

        Args:
            left: Left sibling node (will absorb right).
            right: Right sibling node (will be removed).
            parent: Parent node.
            parent_idx: Index of separator key in parent.
        """
        if left.is_leaf:
            # Merge leaf nodes
            left.keys.extend(right.keys)
            left.values.extend(right.values)
            left.next_leaf = right.next_leaf
        else:
            # Merge internal nodes
            left.keys.append(parent.keys[parent_idx])
            left.keys.extend(right.keys)
            left.values.extend(right.values)

            # Update children's parent pointers
            for child_id in right.values:
                child_node = self._get_node(child_id)
                child_node.parent = left.page.page_id
                child_node.serialize()
                self._release_node(child_node)

        # Remove separator from parent
        parent.keys.pop(parent_idx)
        parent.values.pop(parent_idx + 1)

        left.serialize()
        parent.serialize()

        # Remove right node from buffer pool
        self.buffer_pool.remove_page(right.page.page_id)

    def range_scan(
        self, start_key: Any, end_key: Optional[Any] = None
    ) -> Iterator[Tuple[Any, Any]]:
        """Scan keys in range [start_key, end_key).

        Args:
            start_key: Start of range (inclusive).
            end_key: End of range (exclusive, None for no end).

        Yields:
            (key, value) tuples in key order.
        """
        if self.root_page_id is None:
            return

        leaf = self._find_leaf(start_key)

        while leaf is not None:
            for i, key in enumerate(leaf.keys):
                if key >= start_key:
                    if end_key is not None and key >= end_key:
                        self._release_node(leaf)
                        return
                    yield key, leaf.values[i]

            # Move to next leaf
            if leaf.next_leaf is not None:
                next_id = leaf.next_leaf
                self._release_node(leaf)
                leaf = self._get_node(next_id)
            else:
                self._release_node(leaf)
                return

    def scan_all(self) -> Iterator[Tuple[Any, Any]]:
        """Scan all key-value pairs in order.

        Yields:
            (key, value) tuples in key order.
        """
        if self.root_page_id is None:
            return

        # Find the leftmost leaf
        node = self._get_node(self.root_page_id)
        while not node.is_leaf:
            child_id = node.values[0]
            self._release_node(node)
            node = self._get_node(child_id)

        # Scan all leaves
        while node is not None:
            for i, key in enumerate(node.keys):
                yield key, node.values[i]

            if node.next_leaf is not None:
                next_id = node.next_leaf
                self._release_node(node)
                node = self._get_node(next_id)
            else:
                self._release_node(node)
                return

    def get_min_key(self) -> Optional[Any]:
        """Get the minimum key in the tree.

        Returns:
            Minimum key, or None if tree is empty.
        """
        if self.root_page_id is None:
            return None

        node = self._get_node(self.root_page_id)
        while not node.is_leaf:
            child_id = node.values[0]
            self._release_node(node)
            node = self._get_node(child_id)

        min_key = node.keys[0] if node.keys else None
        self._release_node(node)
        return min_key

    def get_max_key(self) -> Optional[Any]:
        """Get the maximum key in the tree.

        Returns:
            Maximum key, or None if tree is empty.
        """
        if self.root_page_id is None:
            return None

        node = self._get_node(self.root_page_id)
        while not node.is_leaf:
            child_id = node.values[-1]
            self._release_node(node)
            node = self._get_node(child_id)

        max_key = node.keys[-1] if node.keys else None
        self._release_node(node)
        return max_key

    @property
    def size(self) -> int:
        """Number of key-value pairs in the tree."""
        return self._size

    def __len__(self) -> int:
        return self._size

    def __contains__(self, key: Any) -> bool:
        return self.search(key) is not None

    def __repr__(self) -> str:
        return f"BTree(order={self.order}, size={self._size})"