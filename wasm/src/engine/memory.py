"""WebAssembly linear memory management.

This module implements the linear memory model for WebAssembly,
supporting page-based memory allocation, load/store operations,
and memory growth.
"""

from typing import Any, List, Optional, Tuple, Union
import struct


# Page size in WebAssembly: 64 KiB
WASM_PAGE_SIZE: int = 65536

# Maximum number of pages
MAX_PAGES: int = 65536

# Maximum memory size (4 GiB)
MAX_MEMORY_SIZE: int = MAX_PAGES * WASM_PAGE_SIZE


class MemoryError(Exception):
    """Exception raised for memory operation errors."""

    def __init__(self, message: str, address: int = 0):
        """Initialize the error.

        Args:
            message: Error description.
            address: The memory address that caused the error.
        """
        full_msg = f"Memory error at 0x{address:08X}: {message}" if address else message
        super().__init__(full_msg)
        self.address = address


class Memory:
    """WebAssembly linear memory.

    Provides a contiguous, byte-addressable memory space that can be
    dynamically grown in pages of 64 KiB. Supports all load and store
    operations required by the WebAssembly specification.
    """

    def __init__(self, initial_pages: int = 1, max_pages: Optional[int] = None):
        """Initialize the memory.

        Args:
            initial_pages: Initial number of memory pages (64 KiB each).
            max_pages: Maximum number of pages, or None for unbounded.

        Raises:
            MemoryError: If the initial pages exceed the maximum.
        """
        if initial_pages < 0:
            raise MemoryError(f"Invalid initial pages: {initial_pages}")
        if max_pages is not None and initial_pages > max_pages:
            raise MemoryError(
                f"Initial pages ({initial_pages}) exceed maximum ({max_pages})"
            )
        if max_pages is not None and max_pages > MAX_PAGES:
            max_pages = MAX_PAGES

        self._initial_pages = initial_pages
        self._max_pages = max_pages if max_pages is not None else MAX_PAGES
        self._pages = initial_pages
        self._data = bytearray(initial_pages * WASM_PAGE_SIZE)

    @property
    def size(self) -> int:
        """Get the current memory size in bytes."""
        return len(self._data)

    @property
    def pages(self) -> int:
        """Get the current number of memory pages."""
        return self._pages

    @property
    def max_pages(self) -> Optional[int]:
        """Get the maximum number of pages."""
        return self._max_pages

    @property
    def initial_pages(self) -> int:
        """Get the initial number of pages."""
        return self._initial_pages

    def grow(self, delta_pages: int) -> int:
        """Grow the memory by a number of pages.

        Args:
            delta_pages: Number of pages to add.

        Returns:
            The previous number of pages.

        Raises:
            MemoryError: If the memory cannot be grown.
        """
        if delta_pages == 0:
            return self._pages

        new_pages = self._pages + delta_pages
        if new_pages > self._max_pages:
            raise MemoryError(
                f"Cannot grow memory: {new_pages} pages exceeds maximum of {self._max_pages}"
            )
        if new_pages < 0:
            return -1  # Overflow, return -1 as per spec

        new_size = new_pages * WASM_PAGE_SIZE
        if new_size > MAX_MEMORY_SIZE:
            raise MemoryError(f"Memory size {new_size} exceeds maximum {MAX_MEMORY_SIZE}")

        old_pages = self._pages
        self._data.extend(b'\x00' * (delta_pages * WASM_PAGE_SIZE))
        self._pages = new_pages
        return old_pages

    def _check_bounds(self, address: int, size: int) -> None:
        """Check if a memory access is within bounds.

        Args:
            address: The starting address.
            size: The number of bytes to access.

        Raises:
            MemoryError: If the access is out of bounds.
        """
        if address < 0:
            raise MemoryError(f"Negative address: 0x{address:08X}", address)
        if address + size > len(self._data):
            raise MemoryError(
                f"Out of bounds access: 0x{address:08X} + {size} > "
                f"0x{len(self._data):08X}",
                address
            )

    # --- Load operations ---

    def load_i32(self, address: int) -> int:
        """Load a 32-bit signed integer from memory.

        Args:
            address: The memory address.

        Returns:
            The loaded 32-bit integer value.
        """
        self._check_bounds(address, 4)
        return struct.unpack_from('<i', self._data, address)[0]

    def load_i64(self, address: int) -> int:
        """Load a 64-bit signed integer from memory.

        Args:
            address: The memory address.

        Returns:
            The loaded 64-bit integer value.
        """
        self._check_bounds(address, 8)
        return struct.unpack_from('<q', self._data, address)[0]

    def load_f32(self, address: int) -> float:
        """Load a 32-bit float from memory.

        Args:
            address: The memory address.

        Returns:
            The loaded float value.
        """
        self._check_bounds(address, 4)
        return struct.unpack_from('<f', self._data, address)[0]

    def load_f64(self, address: int) -> float:
        """Load a 64-bit float from memory.

        Args:
            address: The memory address.

        Returns:
            The loaded float value.
        """
        self._check_bounds(address, 8)
        return struct.unpack_from('<d', self._data, address)[0]

    def load_i32_8s(self, address: int) -> int:
        """Load a signed 8-bit integer and sign-extend to i32.

        Args:
            address: The memory address.

        Returns:
            The sign-extended 32-bit value.
        """
        self._check_bounds(address, 1)
        val = self._data[address]
        if val & 0x80:
            val |= 0xFFFFFF00
        return val

    def load_i32_8u(self, address: int) -> int:
        """Load an unsigned 8-bit integer and zero-extend to i32.

        Args:
            address: The memory address.

        Returns:
            The zero-extended 32-bit value.
        """
        self._check_bounds(address, 1)
        return self._data[address]

    def load_i32_16s(self, address: int) -> int:
        """Load a signed 16-bit integer and sign-extend to i32.

        Args:
            address: The memory address.

        Returns:
            The sign-extended 32-bit value.
        """
        self._check_bounds(address, 2)
        val = struct.unpack_from('<h', self._data, address)[0]
        return val

    def load_i32_16u(self, address: int) -> int:
        """Load an unsigned 16-bit integer and zero-extend to i32.

        Args:
            address: The memory address.

        Returns:
            The zero-extended 32-bit value.
        """
        self._check_bounds(address, 2)
        return struct.unpack_from('<H', self._data, address)[0]

    def load_i64_8s(self, address: int) -> int:
        """Load a signed 8-bit integer and sign-extend to i64.

        Args:
            address: The memory address.

        Returns:
            The sign-extended 64-bit value.
        """
        self._check_bounds(address, 1)
        val = self._data[address]
        if val & 0x80:
            val |= 0xFFFFFFFFFFFFFF00
        return val

    def load_i64_8u(self, address: int) -> int:
        """Load an unsigned 8-bit integer and zero-extend to i64.

        Args:
            address: The memory address.

        Returns:
            The zero-extended 64-bit value.
        """
        self._check_bounds(address, 1)
        return self._data[address]

    def load_i64_16s(self, address: int) -> int:
        """Load a signed 16-bit integer and sign-extend to i64.

        Args:
            address: The memory address.

        Returns:
            The sign-extended 64-bit value.
        """
        self._check_bounds(address, 2)
        val = struct.unpack_from('<h', self._data, address)[0]
        return val

    def load_i64_16u(self, address: int) -> int:
        """Load an unsigned 16-bit integer and zero-extend to i64.

        Args:
            address: The memory address.

        Returns:
            The zero-extended 64-bit value.
        """
        self._check_bounds(address, 2)
        return struct.unpack_from('<H', self._data, address)[0]

    def load_i64_32s(self, address: int) -> int:
        """Load a signed 32-bit integer and sign-extend to i64.

        Args:
            address: The memory address.

        Returns:
            The sign-extended 64-bit value.
        """
        self._check_bounds(address, 4)
        val = struct.unpack_from('<i', self._data, address)[0]
        return val

    def load_i64_32u(self, address: int) -> int:
        """Load an unsigned 32-bit integer and zero-extend to i64.

        Args:
            address: The memory address.

        Returns:
            The zero-extended 64-bit value.
        """
        self._check_bounds(address, 4)
        return struct.unpack_from('<I', self._data, address)[0]

    # --- Store operations ---

    def store_i32(self, address: int, value: int) -> None:
        """Store a 32-bit integer to memory.

        Args:
            address: The memory address.
            value: The 32-bit integer value to store.
        """
        self._check_bounds(address, 4)
        struct.pack_into('<i', self._data, address, value & 0xFFFFFFFF)

    def store_i64(self, address: int, value: int) -> None:
        """Store a 64-bit integer to memory.

        Args:
            address: The memory address.
            value: The 64-bit integer value to store.
        """
        self._check_bounds(address, 8)
        struct.pack_into('<q', self._data, address, value & 0xFFFFFFFFFFFFFFFF)

    def store_f32(self, address: int, value: float) -> None:
        """Store a 32-bit float to memory.

        Args:
            address: The memory address.
            value: The float value to store.
        """
        self._check_bounds(address, 4)
        struct.pack_into('<f', self._data, address, value)

    def store_f64(self, address: int, value: float) -> None:
        """Store a 64-bit float to memory.

        Args:
            address: The memory address.
            value: The float value to store.
        """
        self._check_bounds(address, 8)
        struct.pack_into('<d', self._data, address, value)

    def store_i32_8(self, address: int, value: int) -> None:
        """Store the low 8 bits of an i32 to memory.

        Args:
            address: The memory address.
            value: The integer value to store.
        """
        self._check_bounds(address, 1)
        self._data[address] = value & 0xFF

    def store_i32_16(self, address: int, value: int) -> None:
        """Store the low 16 bits of an i32 to memory.

        Args:
            address: The memory address.
            value: The integer value to store.
        """
        self._check_bounds(address, 2)
        struct.pack_into('<H', self._data, address, value & 0xFFFF)

    def store_i64_8(self, address: int, value: int) -> None:
        """Store the low 8 bits of an i64 to memory.

        Args:
            address: The memory address.
            value: The integer value to store.
        """
        self._check_bounds(address, 1)
        self._data[address] = value & 0xFF

    def store_i64_16(self, address: int, value: int) -> None:
        """Store the low 16 bits of an i64 to memory.

        Args:
            address: The memory address.
            value: The integer value to store.
        """
        self._check_bounds(address, 2)
        struct.pack_into('<H', self._data, address, value & 0xFFFF)

    def store_i64_32(self, address: int, value: int) -> None:
        """Store the low 32 bits of an i64 to memory.

        Args:
            address: The memory address.
            value: The integer value to store.
        """
        self._check_bounds(address, 4)
        struct.pack_into('<I', self._data, address, value & 0xFFFFFFFF)

    # --- Bulk memory operations ---

    def copy(self, dest: int, src: int, count: int) -> None:
        """Copy memory within the linear memory.

        Args:
            dest: Destination address.
            src: Source address.
            count: Number of bytes to copy.

        Raises:
            MemoryError: If the copy is out of bounds.
        """
        self._check_bounds(dest, count)
        self._check_bounds(src, count)
        if count > 0:
            self._data[dest:dest + count] = self._data[src:src + count]

    def fill(self, dest: int, value: int, count: int) -> None:
        """Fill memory with a byte value.

        Args:
            dest: Destination address.
            value: The byte value to fill with.
            count: Number of bytes to fill.

        Raises:
            MemoryError: If the fill is out of bounds.
        """
        self._check_bounds(dest, count)
        if count > 0:
            self._data[dest:dest + count] = bytes([value & 0xFF]) * count

    def init(self, dest: int, data: bytes, src_offset: int, count: int) -> None:
        """Initialize memory from a data segment.

        Args:
            dest: Destination address in memory.
            data: The source data bytes.
            src_offset: Offset into the source data.
            count: Number of bytes to copy.

        Raises:
            MemoryError: If the access is out of bounds.
        """
        self._check_bounds(dest, count)
        if src_offset + count > len(data):
            raise MemoryError(
                f"Data segment access out of bounds: {src_offset} + {count} > {len(data)}"
            )
        if count > 0:
            self._data[dest:dest + count] = data[src_offset:src_offset + count]

    def read(self, address: int, size: int) -> bytes:
        """Read raw bytes from memory.

        Args:
            address: The memory address.
            size: Number of bytes to read.

        Returns:
            The bytes at the given address.

        Raises:
            MemoryError: If the read is out of bounds.
        """
        self._check_bounds(address, size)
        return bytes(self._data[address:address + size])

    def write(self, address: int, data: bytes) -> None:
        """Write raw bytes to memory.

        Args:
            address: The memory address.
            data: The bytes to write.

        Raises:
            MemoryError: If the write is out of bounds.
        """
        self._check_bounds(address, len(data))
        self._data[address:address + len(data)] = data

    def get_byte(self, address: int) -> int:
        """Get a single byte from memory.

        Args:
            address: The memory address.

        Returns:
            The byte value at the address.
        """
        self._check_bounds(address, 1)
        return self._data[address]

    def set_byte(self, address: int, value: int) -> None:
        """Set a single byte in memory.

        Args:
            address: The memory address.
            value: The byte value to set.
        """
        self._check_bounds(address, 1)
        self._data[address] = value & 0xFF

    def get_bytes(self, address: int, count: int) -> bytearray:
        """Get a slice of bytes from memory.

        Args:
            address: The memory address.
            count: Number of bytes to get.

        Returns:
            A bytearray slice.
        """
        self._check_bounds(address, count)
        return self._data[address:address + count]

    def set_bytes(self, address: int, data: bytes) -> None:
        """Set a slice of bytes in memory.

        Args:
            address: The memory address.
            data: The bytes to write.
        """
        self.write(address, data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"Memory(pages={self._pages}, size={len(self._data)} bytes)"

    def __getitem__(self, index: int) -> int:
        """Get a byte value using bracket notation.

        Args:
            index: The memory address.

        Returns:
            The byte value at the address.
        """
        if isinstance(index, slice):
            return self._data[index]
        return self.get_byte(index)

    def __setitem__(self, index: int, value: int) -> None:
        """Set a byte value using bracket notation.

        Args:
            index: The memory address.
            value: The byte value to set.
        """
        if isinstance(index, slice):
            self._data[index] = value
        else:
            self.set_byte(index, value)

    def __contains__(self, address: int) -> bool:
        """Check if an address is within bounds.

        Args:
            address: The memory address.

        Returns:
            True if the address is valid.
        """
        return 0 <= address < len(self._data)


class SharedMemory:
    """Shared WebAssembly memory (for threads proposal).

    Provides atomic operations and shared memory semantics.
    This is a simplified implementation for the threads proposal.
    """

    def __init__(self, initial_pages: int = 1, max_pages: Optional[int] = None):
        """Initialize shared memory.

        Args:
            initial_pages: Initial number of pages.
            max_pages: Maximum number of pages.
        """
        self._memory = Memory(initial_pages, max_pages)
        self._is_shared = True

    @property
    def memory(self) -> Memory:
        """Get the underlying memory."""
        return self._memory

    @property
    def is_shared(self) -> bool:
        """Check if the memory is shared."""
        return self._is_shared

    def grow(self, delta_pages: int) -> int:
        """Grow the shared memory.

        Args:
            delta_pages: Number of pages to add.

        Returns:
            The previous number of pages.
        """
        return self._memory.grow(delta_pages)

    def atomic_load_i32(self, address: int) -> int:
        """Atomically load an i32.

        Args:
            address: The memory address.

        Returns:
            The loaded value.
        """
        return self._memory.load_i32(address)

    def atomic_store_i32(self, address: int, value: int) -> None:
        """Atomically store an i32.

        Args:
            address: The memory address.
            value: The value to store.
        """
        self._memory.store_i32(address, value)

    def atomic_rmw_add(self, address: int, value: int) -> int:
        """Atomically add and return the previous value.

        Args:
            address: The memory address.
            value: The value to add.

        Returns:
            The previous value at the address.
        """
        prev = self._memory.load_i32(address)
        self._memory.store_i32(address, (prev + value) & 0xFFFFFFFF)
        return prev


def create_memory(initial_pages: int = 1, max_pages: Optional[int] = None) -> Memory:
    """Create a new linear memory instance.

    Args:
        initial_pages: Initial number of pages.
        max_pages: Maximum number of pages.

    Returns:
        A new Memory instance.
    """
    return Memory(initial_pages, max_pages)