"""Page management for AinosDB storage engine.

Pages are fixed-size blocks of data that form the foundation of the
storage engine. Each page has a header and a data area.
"""

from __future__ import annotations

import struct
from enum import IntEnum
from typing import Optional, Tuple


class PageType(IntEnum):
    """Types of pages in the database."""
    FREE = 0
    BTREE_NODE = 1
    BTREE_LEAF = 2
    BTREE_INTERNAL = 3
    BTREE_ROOT = 4
    CATALOG = 5
    WAL_PAGE = 6
    CHECKPOINT = 7
    OVERFLOW = 8
    VECTOR_PAGE = 9
    DOCUMENT_PAGE = 10
    META_PAGE = 11


class PageId:
    """Unique identifier for a page.

    Attributes:
        page_num: Page number within the file.
        table_id: Optional table identifier.
    """

    __slots__ = ("page_num", "table_id")

    def __init__(self, page_num: int, table_id: int = 0) -> None:
        self.page_num = page_num
        self.table_id = table_id

    def __repr__(self) -> str:
        return f"PageId({self.table_id}:{self.page_num})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PageId):
            return NotImplemented
        return self.page_num == other.page_num and self.table_id == other.table_id

    def __hash__(self) -> int:
        return hash((self.table_id, self.page_num))

    def to_bytes(self) -> bytes:
        return struct.pack("!II", self.table_id, self.page_num)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0) -> Tuple["PageId", int]:
        table_id, page_num = struct.unpack_from("!II", data, offset)
        return cls(page_num, table_id), offset + 8


class Page:
    """Fixed-size page for storage.

    Page layout:
    - Header (24 bytes): page_id, page_type, free_space_offset, checksum, flags, version
    - Data area (remaining space)

    Attributes:
        page_id: Unique page identifier.
        page_type: Type of page content.
        data: Raw page data including header.
        dirty: Whether the page has been modified.
        pin_count: Number of buffer pool pins.
        page_size: Total page size in bytes.
    """

    HEADER_SIZE = 24
    HEADER_FORMAT = "!IIHHII"

    __slots__ = (
        "page_id", "page_type", "data", "dirty", "pin_count",
        "page_size", "_free_offset", "_checksum", "_flags", "_version",
    )

    def __init__(
        self,
        page_id: PageId,
        page_type: PageType = PageType.FREE,
        page_size: int = 8192,
    ) -> None:
        self.page_id = page_id
        self.page_type = page_type
        self.page_size = page_size
        self.dirty = False
        self.pin_count = 0
        self._flags = 0
        self._version = 1

        # Initialize data buffer
        self.data = bytearray(page_size)
        self._free_offset = self.HEADER_SIZE
        self._write_header()

    def _write_header(self) -> None:
        """Write the page header into the data buffer."""
        struct.pack_into(
            self.HEADER_FORMAT, self.data, 0,
            self.page_id.page_num,
            self.page_id.table_id,
            int(self.page_type),
            self._free_offset,
            self._flags,
            self._version,
        )

    def _read_header(self) -> None:
        """Read the page header from the data buffer."""
        (
            page_num,
            table_id,
            page_type_int,
            self._free_offset,
            self._flags,
            self._version,
        ) = struct.unpack_from(self.HEADER_FORMAT, self.data, 0)
        self.page_id = PageId(page_num, table_id)
        self.page_type = PageType(page_type_int)

    @classmethod
    def from_bytes(cls, data: bytes, page_size: int = 8192) -> "Page":
        """Create a Page from raw bytes.

        Args:
            data: Raw page data with header.
            page_size: Page size in bytes.

        Returns:
            Deserialized Page object.
        """
        page = cls.__new__(cls)
        page.page_size = page_size
        page.data = bytearray(data)
        page.dirty = False
        page.pin_count = 0
        page._read_header()
        return page

    def to_bytes(self) -> bytes:
        """Serialize page to bytes.

        Returns:
            Bytes representation of the page.
        """
        self._write_header()
        return bytes(self.data)

    @property
    def free_space(self) -> int:
        """Get remaining free space in the page."""
        return self.page_size - self._free_offset

    @property
    def free_offset(self) -> int:
        """Get the current free space offset."""
        return self._free_offset

    def set_free_offset(self, offset: int) -> None:
        """Set the free space offset."""
        self._free_offset = offset
        self.dirty = True

    def write_data(self, offset: int, data: bytes) -> None:
        """Write data at a specific offset.

        Args:
            offset: Offset within the page data area.
            data: Data bytes to write.

        Raises:
            ValueError: If data exceeds page boundaries.
        """
        end = offset + len(data)
        if end > self.page_size:
            raise ValueError(
                f"Data write exceeds page boundary: {end} > {self.page_size}"
            )
        self.data[offset:end] = data
        self.dirty = True

    def read_data(self, offset: int, length: int) -> bytes:
        """Read data from a specific offset.

        Args:
            offset: Offset within the page data area.
            length: Number of bytes to read.

        Returns:
            Data bytes.

        Raises:
            ValueError: If read exceeds page boundaries.
        """
        end = offset + length
        if end > self.page_size:
            raise ValueError(
                f"Data read exceeds page boundary: {end} > {self.page_size}"
            )
        return bytes(self.data[offset:end])

    def append_data(self, data: bytes) -> int:
        """Append data at the current free space offset.

        Args:
            data: Data bytes to append.

        Returns:
            Offset where data was written.

        Raises:
            ValueError: If not enough free space.
        """
        if len(data) > self.free_space:
            raise ValueError(
                f"Not enough free space: need {len(data)}, have {self.free_space}"
            )
        offset = self._free_offset
        self.data[offset:offset + len(data)] = data
        self._free_offset += len(data)
        self.dirty = True
        return offset

    def clear(self) -> None:
        """Clear the page data area, resetting it to empty."""
        self.data[self.HEADER_SIZE:] = b"\x00" * (self.page_size - self.HEADER_SIZE)
        self._free_offset = self.HEADER_SIZE
        self.dirty = True

    def pin(self) -> None:
        """Increment pin count (pin in buffer pool)."""
        self.pin_count += 1

    def unpin(self) -> None:
        """Decrement pin count (unpin from buffer pool)."""
        if self.pin_count > 0:
            self.pin_count -= 1

    @property
    def is_pinned(self) -> bool:
        """Check if the page is currently pinned."""
        return self.pin_count > 0

    def __repr__(self) -> str:
        return (
            f"Page(id={self.page_id}, type={self.page_type.name}, "
            f"free={self.free_space}, dirty={self.dirty}, pins={self.pin_count})"
        )