"""LEB128 (Little Endian Base 128) variable-length integer encoding and decoding.

LEB128 is used extensively in the WebAssembly binary format for encoding
integer values in a compact variable-length representation. This module
provides both unsigned and signed LEB128 encoding/decoding functions.
"""

from typing import Tuple


def decode_unsigned_leb128(data: bytes, offset: int = 0) -> Tuple[int, int]:
    """Decode an unsigned LEB128 encoded integer from a byte sequence.

    Each byte contributes 7 bits of data, with the MSB indicating whether
    more bytes follow. The result is a non-negative integer.

    Args:
        data: The byte sequence containing the LEB128 encoded value.
        offset: The starting position in the data to decode from.

    Returns:
        A tuple of (decoded_value, next_offset) where next_offset is the
        position after the consumed bytes.

    Raises:
        ValueError: If the encoded value is too large (more than 10 bytes)
            or if the offset is out of bounds.
    """
    if offset >= len(data):
        raise ValueError(f"Offset {offset} out of bounds for data of length {len(data)}")

    result: int = 0
    shift: int = 0
    byte_count: int = 0

    while True:
        byte_count += 1
        if byte_count > 10:
            raise ValueError("Unsigned LEB128 value too large (more than 10 bytes)")

        byte_val = data[offset]
        result |= (byte_val & 0x7F) << shift
        shift += 7
        offset += 1

        if (byte_val & 0x80) == 0:
            break

        if offset >= len(data) and byte_count < 10:
            raise ValueError(
                f"Unexpected end of data while decoding unsigned LEB128 "
                f"after {byte_count} bytes"
            )

    return result, offset


def decode_signed_leb128(data: bytes, offset: int = 0) -> Tuple[int, int]:
    """Decode a signed LEB128 encoded integer from a byte sequence.

    Each byte contributes 7 bits of data, with the MSB indicating whether
    more bytes follow. The result is sign-extended from the effective number
    of bits.

    Args:
        data: The byte sequence containing the LEB128 encoded value.
        offset: The starting position in the data to decode from.

    Returns:
        A tuple of (decoded_value, next_offset) where next_offset is the
        position after the consumed bytes.

    Raises:
        ValueError: If the encoded value is too large (more than 10 bytes)
            or if the offset is out of bounds.
    """
    if offset >= len(data):
        raise ValueError(f"Offset {offset} out of bounds for data of length {len(data)}")

    result: int = 0
    shift: int = 0
    byte_count: int = 0
    byte_val: int = 0

    while True:
        byte_count += 1
        if byte_count > 10:
            raise ValueError("Signed LEB128 value too large (more than 10 bytes)")

        byte_val = data[offset]
        result |= (byte_val & 0x7F) << shift
        shift += 7
        offset += 1

        if (byte_val & 0x80) == 0:
            break

        if offset >= len(data) and byte_count < 10:
            raise ValueError(
                f"Unexpected end of data while decoding signed LEB128 "
                f"after {byte_count} bytes"
            )

    # Sign extend if the last byte's MSB bit is set
    if (byte_val & 0x40) != 0:
        # Calculate the mask for the sign extension
        mask = (1 << shift) - 1
        result = result | (~mask)

    return result, offset


def encode_unsigned_leb128(value: int) -> bytes:
    """Encode an integer as an unsigned LEB128 byte sequence.

    Args:
        value: The non-negative integer to encode.

    Returns:
        The LEB128-encoded byte sequence.

    Raises:
        ValueError: If the value is negative.
    """
    if value < 0:
        raise ValueError(f"Cannot encode negative value {value} as unsigned LEB128")

    result = bytearray()

    while True:
        byte_val = value & 0x7F
        value >>= 7
        if value != 0:
            byte_val |= 0x80
        result.append(byte_val)
        if value == 0:
            break

    return bytes(result)


def encode_signed_leb128(value: int) -> bytes:
    """Encode an integer as a signed LEB128 byte sequence.

    Args:
        value: The integer to encode (may be negative).

    Returns:
        The LEB128-encoded byte sequence.
    """
    result = bytearray()
    more = True
    sign_bit = (value >> 63) & 1  # For 64-bit sign extension

    while more:
        byte_val = value & 0x7F
        value >>= 7
        # Check if the value is in its final form
        if (value == 0 and (byte_val & 0x40) == 0) or \
           (value == -1 and (byte_val & 0x40) != 0):
            more = False
        else:
            byte_val |= 0x80
        result.append(byte_val)

    return bytes(result)


def decode_unsigned_leb128_from_buffer(data: bytes, offset: int = 0) -> Tuple[int, int]:
    """Alias for decode_unsigned_leb128 for compatibility."""
    return decode_unsigned_leb128(data, offset)


def decode_signed_leb128_from_buffer(data: bytes, offset: int = 0) -> Tuple[int, int]:
    """Alias for decode_signed_leb128 for compatibility."""
    return decode_signed_leb128(data, offset)


def encode_leb128(value: int, signed: bool = False) -> bytes:
    """Encode an integer as LEB128.

    Args:
        value: The integer to encode.
        signed: Whether to use signed encoding.

    Returns:
        The LEB128-encoded byte sequence.
    """
    if signed:
        return encode_signed_leb128(value)
    return encode_unsigned_leb128(value)


class LEB128Reader:
    """A streaming reader for LEB128-encoded values from a byte buffer.

    This class maintains internal state for reading multiple LEB128 values
    sequentially from a byte buffer.
    """

    def __init__(self, data: bytes, offset: int = 0):
        """Initialize the reader.

        Args:
            data: The byte buffer to read from.
            offset: The initial offset into the buffer.
        """
        self.data = data
        self.offset = offset

    def read_unsigned(self) -> int:
        """Read the next unsigned LEB128 value from the buffer.

        Returns:
            The decoded unsigned integer.

        Raises:
            ValueError: If the encoding is invalid or buffer is exhausted.
        """
        value, self.offset = decode_unsigned_leb128(self.data, self.offset)
        return value

    def read_signed(self) -> int:
        """Read the next signed LEB128 value from the buffer.

        Returns:
            The decoded signed integer.

        Raises:
            ValueError: If the encoding is invalid or buffer is exhausted.
        """
        value, self.offset = decode_signed_leb128(self.data, self.offset)
        return value

    def read_u32(self) -> int:
        """Read a 32-bit unsigned integer encoded as LEB128.

        Returns:
            The decoded 32-bit unsigned integer.
        """
        return self.read_unsigned()

    def read_u64(self) -> int:
        """Read a 64-bit unsigned integer encoded as LEB128.

        Returns:
            The decoded 64-bit unsigned integer.
        """
        return self.read_unsigned()

    def read_s32(self) -> int:
        """Read a 32-bit signed integer encoded as LEB128.

        Returns:
            The decoded 32-bit signed integer.
        """
        return self.read_signed()

    def read_s64(self) -> int:
        """Read a 64-bit signed integer encoded as LEB128.

        Returns:
            The decoded 64-bit signed integer.
        """
        return self.read_signed()

    def skip(self, count: int = 1) -> None:
        """Skip the next LEB128 encoded value(s).

        Args:
            count: Number of LEB128 values to skip.
        """
        for _ in range(count):
            self.read_unsigned()

    @property
    def remaining(self) -> int:
        """Return the number of remaining bytes in the buffer."""
        return max(0, len(self.data) - self.offset)

    def tell(self) -> int:
        """Return the current offset in the buffer."""
        return self.offset

    def seek(self, offset: int) -> None:
        """Set the offset to a specific position.

        Args:
            offset: The new offset position.

        Raises:
            ValueError: If the offset is out of bounds.
        """
        if offset < 0 or offset > len(self.data):
            raise ValueError(
                f"Offset {offset} out of bounds for data of length {len(self.data)}"
            )
        self.offset = offset