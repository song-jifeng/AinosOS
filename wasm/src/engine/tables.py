"""WebAssembly table management.

This module implements tables for WebAssembly, which are used to store
reference types (funcref, externref) and enable indirect function calls.
"""

from typing import Any, Callable, List, Optional, Tuple, Union


class TableError(Exception):
    """Exception raised for table operation errors."""

    def __init__(self, message: str, index: int = 0):
        """Initialize the error.

        Args:
            message: Error description.
            index: The table index that caused the error.
        """
        full_msg = f"Table error at index {index}: {message}" if index else message
        super().__init__(full_msg)
        self.index = index


class Table:
    """WebAssembly table for storing reference types.

    Tables are used for indirect function calls and hold function
    references or external references.
    """

    def __init__(
        self,
        elem_type: int,
        initial_size: int,
        max_size: Optional[int] = None,
        init_value: Any = None,
    ):
        """Initialize the table.

        Args:
            elem_type: The element type (0x70 for funcref, 0x6F for externref).
            initial_size: The initial table size.
            max_size: The maximum table size, or None for unbounded.
            init_value: The initial value to fill the table with.

        Raises:
            TableError: If the table parameters are invalid.
        """
        if initial_size < 0:
            raise TableError(f"Invalid initial size: {initial_size}")
        if max_size is not None and initial_size > max_size:
            raise TableError(
                f"Initial size ({initial_size}) exceeds maximum ({max_size})"
            )

        self._elem_type = elem_type
        self._initial_size = initial_size
        self._max_size = max_size
        self._elements: List[Any] = [init_value] * initial_size

    @property
    def elem_type(self) -> int:
        """Get the element type."""
        return self._elem_type

    @property
    def size(self) -> int:
        """Get the current table size."""
        return len(self._elements)

    @property
    def initial_size(self) -> int:
        """Get the initial table size."""
        return self._initial_size

    @property
    def max_size(self) -> Optional[int]:
        """Get the maximum table size."""
        return self._max_size

    def get(self, index: int) -> Any:
        """Get the element at a given index.

        Args:
            index: The table index.

        Returns:
            The element at the index.

        Raises:
            TableError: If the index is out of bounds.
        """
        if index < 0 or index >= len(self._elements):
            raise TableError(f"Index {index} out of bounds (size={len(self._elements)})", index)
        return self._elements[index]

    def set(self, index: int, value: Any) -> None:
        """Set the element at a given index.

        Args:
            index: The table index.
            value: The value to set.

        Raises:
            TableError: If the index is out of bounds.
        """
        if index < 0 or index >= len(self._elements):
            raise TableError(f"Index {index} out of bounds (size={len(self._elements)})", index)
        self._elements[index] = value

    def grow(self, delta: int, init_value: Any = None) -> int:
        """Grow the table by a number of elements.

        Args:
            delta: Number of elements to add.
            init_value: The initial value for new elements.

        Returns:
            The previous table size, or -1 on failure.

        Raises:
            TableError: If the table cannot be grown.
        """
        if delta == 0:
            return self.size

        new_size = self.size + delta
        if self._max_size is not None and new_size > self._max_size:
            return -1

        self._elements.extend([init_value] * delta)
        return new_size - delta

    def fill(self, index: int, value: Any, count: int) -> None:
        """Fill a range of the table with a value.

        Args:
            index: The starting index.
            value: The value to fill with.
            count: The number of elements to fill.

        Raises:
            TableError: If the range is out of bounds.
        """
        if index < 0 or index + count > len(self._elements):
            raise TableError(
                f"Fill range [{index}, {index + count}) out of bounds (size={len(self._elements)})"
            )
        for i in range(count):
            self._elements[index + i] = value

    def copy(self, dest: int, src: int, count: int) -> None:
        """Copy elements within the table.

        Args:
            dest: The destination index.
            src: The source index.
            count: The number of elements to copy.

        Raises:
            TableError: If the range is out of bounds.
        """
        if (dest < 0 or src < 0 or
                dest + count > len(self._elements) or
                src + count > len(self._elements)):
            raise TableError(
                f"Copy range out of bounds: dest={dest}, src={src}, count={count}"
            )
        # Copy with proper overlap handling
        if dest <= src:
            for i in range(count):
                self._elements[dest + i] = self._elements[src + i]
        else:
            for i in range(count - 1, -1, -1):
                self._elements[dest + i] = self._elements[src + i]

    def init(self, index: int, elements: List[Any], src_offset: int, count: int) -> None:
        """Initialize a range of the table from an element segment.

        Args:
            index: The starting table index.
            elements: The source element list.
            src_offset: The offset into the source elements.
            count: The number of elements to copy.

        Raises:
            TableError: If the range is out of bounds.
        """
        if index < 0 or index + count > len(self._elements):
            raise TableError(
                f"Init range [{index}, {index + count}) out of bounds (size={len(self._elements)})"
            )
        if src_offset < 0 or src_offset + count > len(elements):
            raise TableError(
                f"Init source range [{src_offset}, {src_offset + count}) out of bounds"
            )
        for i in range(count):
            self._elements[index + i] = elements[src_offset + i]

    @property
    def elements(self) -> List[Any]:
        """Get a copy of the table elements."""
        return list(self._elements)

    def __len__(self) -> int:
        return len(self._elements)

    def __repr__(self) -> str:
        return f"Table(elem_type=0x{self._elem_type:02X}, size={len(self._elements)})"


class FunctionTable(Table):
    """A table specifically for function references.

    Provides additional methods for indirect function call resolution.
    """

    def __init__(
        self,
        initial_size: int,
        max_size: Optional[int] = None,
    ):
        """Initialize the function table.

        Args:
            initial_size: The initial table size.
            max_size: The maximum table size.
        """
        super().__init__(elem_type=0x70, initial_size=initial_size, max_size=max_size)

    def get_func(self, index: int) -> int:
        """Get the function index at a given table index.

        Args:
            index: The table index.

        Returns:
            The function index, or -1 if null.

        Raises:
            TableError: If the index is out of bounds.
        """
        val = self.get(index)
        if val is None:
            return -1
        return val

    def set_func(self, index: int, func_idx: int) -> None:
        """Set the function index at a given table index.

        Args:
            index: The table index.
            func_idx: The function index to set.
        """
        self.set(index, func_idx)


class ExternalTable(Table):
    """A table for external references."""

    def __init__(
        self,
        initial_size: int,
        max_size: Optional[int] = None,
    ):
        """Initialize the external table.

        Args:
            initial_size: The initial table size.
            max_size: The maximum table size.
        """
        super().__init__(elem_type=0x6F, initial_size=initial_size, max_size=max_size)


def create_table(
    elem_type: int,
    initial_size: int,
    max_size: Optional[int] = None,
) -> Table:
    """Create a table of the appropriate type.

    Args:
        elem_type: The element type (0x70 for funcref, 0x6F for externref).
        initial_size: The initial size.
        max_size: The maximum size.

    Returns:
        A new Table instance.
    """
    if elem_type == 0x70:
        return FunctionTable(initial_size, max_size)
    elif elem_type == 0x6F:
        return ExternalTable(initial_size, max_size)
    else:
        return Table(elem_type, initial_size, max_size)


def create_function_table(
    initial_size: int,
    max_size: Optional[int] = None,
) -> FunctionTable:
    """Create a function table.

    Args:
        initial_size: The initial size.
        max_size: The maximum size.

    Returns:
        A new FunctionTable instance.
    """
    return FunctionTable(initial_size, max_size)