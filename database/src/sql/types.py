"""Data type system for AinosDB SQL engine.

Defines the type system used throughout the database, including
type checking, coercion, and serialization.
"""

from __future__ import annotations

import struct
from abc import ABC, abstractmethod
from datetime import datetime, date
from typing import Any, ClassVar, Dict, List, Optional, Tuple, Type, Union


class DataType(ABC):
    """Abstract base class for all data types.

    Each data type knows how to:
    - Validate and coerce values
    - Serialize/deserialize to binary
    - Compare values
    """

    type_id: ClassVar[int]
    name: ClassVar[str]

    @abstractmethod
    def validate(self, value: Any) -> bool:
        """Check if a value is valid for this type.

        Args:
            value: Value to validate.

        Returns:
            True if the value is valid.
        """
        ...

    @abstractmethod
    def coerce(self, value: Any) -> Any:
        """Coerce a value to this type.

        Args:
            value: Value to coerce.

        Returns:
            Coerced value.

        Raises:
            TypeError: If value cannot be coerced.
        """
        ...

    @abstractmethod
    def serialize(self, value: Any) -> bytes:
        """Serialize a value to bytes.

        Args:
            value: Value to serialize.

        Returns:
            Binary representation.
        """
        ...

    @abstractmethod
    def deserialize(self, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        """Deserialize a value from bytes.

        Args:
            data: Binary data.
            offset: Starting offset.

        Returns:
            Tuple of (value, new offset).
        """
        ...

    def compare(self, a: Any, b: Any) -> int:
        """Compare two values of this type.

        Args:
            a: First value.
            b: Second value.

        Returns:
            Negative if a < b, 0 if a == b, positive if a > b.
        """
        if a is None and b is None:
            return 0
        if a is None:
            return -1
        if b is None:
            return 1
        a = self.coerce(a)
        b = self.coerce(b)
        if a < b:
            return -1
        elif a > b:
            return 1
        return 0

    def __eq__(self, other: object) -> bool:
        if isinstance(other, type):
            return type(self) is other
        if isinstance(other, DataType):
            return type(self) is type(other)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(type(self))

    def __repr__(self) -> str:
        return self.name


class IntegerType(DataType):
    """32-bit integer type."""

    type_id = 1
    name = "INTEGER"
    FORMAT = "!i"
    SIZE = 4

    def validate(self, value: Any) -> bool:
        return isinstance(value, int) and -2147483648 <= value <= 2147483647

    def coerce(self, value: Any) -> int:
        if isinstance(value, int):
            if -2147483648 <= value <= 2147483647:
                return value
            raise TypeError(f"Integer overflow: {value}")
        if isinstance(value, float):
            result = int(value)
            if -2147483648 <= result <= 2147483647:
                return result
            raise TypeError(f"Integer overflow: {value}")
        if isinstance(value, str):
            try:
                result = int(value)
                if -2147483648 <= result <= 2147483647:
                    return result
                raise TypeError(f"Integer overflow: {value}")
            except ValueError:
                raise TypeError(f"Cannot coerce '{value}' to INTEGER")
        raise TypeError(f"Cannot coerce {type(value).__name__} to INTEGER")

    def serialize(self, value: Any) -> bytes:
        return struct.pack(self.FORMAT, self.coerce(value))

    def deserialize(self, data: bytes, offset: int = 0) -> Tuple[int, int]:
        return struct.unpack_from(self.FORMAT, data, offset)[0], offset + self.SIZE


class FloatType(DataType):
    """64-bit floating point type."""

    type_id = 2
    name = "FLOAT"
    FORMAT = "!d"
    SIZE = 8

    def validate(self, value: Any) -> bool:
        return isinstance(value, (int, float))

    def coerce(self, value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                raise TypeError(f"Cannot coerce '{value}' to FLOAT")
        raise TypeError(f"Cannot coerce {type(value).__name__} to FLOAT")

    def serialize(self, value: Any) -> bytes:
        return struct.pack(self.FORMAT, self.coerce(value))

    def deserialize(self, data: bytes, offset: int = 0) -> Tuple[float, int]:
        return struct.unpack_from(self.FORMAT, data, offset)[0], offset + self.SIZE


class VarcharType(DataType):
    """Variable-length string type with max length."""

    type_id = 3
    name = "VARCHAR"

    def __init__(self, max_length: int = 255) -> None:
        self.max_length = max_length

    @property
    def name(self) -> str:  # type: ignore[override]
        return f"VARCHAR({self.max_length})"

    def validate(self, value: Any) -> bool:
        return isinstance(value, str) and len(value) <= self.max_length

    def coerce(self, value: Any) -> str:
        if isinstance(value, str):
            if len(value) <= self.max_length:
                return value
            return value[:self.max_length]
        if isinstance(value, (int, float)):
            result = str(value)
            if len(result) <= self.max_length:
                return result
            return result[:self.max_length]
        raise TypeError(f"Cannot coerce {type(value).__name__} to VARCHAR")

    def serialize(self, value: Any) -> bytes:
        s = self.coerce(value).encode("utf-8")
        return struct.pack("!H", len(s)) + s

    def deserialize(self, data: bytes, offset: int = 0) -> Tuple[str, int]:
        length = struct.unpack_from("!H", data, offset)[0]
        offset += 2
        s = data[offset:offset + length].decode("utf-8")
        return s, offset + length

    def __eq__(self, other: object) -> bool:
        if isinstance(other, VarcharType):
            return self.max_length == other.max_length
        return isinstance(other, type) and type(self) is type(other)

    def __hash__(self) -> int:
        return hash((type(self), self.max_length))


class TextType(DataType):
    """Unlimited-length text type."""

    type_id = 4
    name = "TEXT"

    def validate(self, value: Any) -> bool:
        return isinstance(value, str)

    def coerce(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            return str(value)
        raise TypeError(f"Cannot coerce {type(value).__name__} to TEXT")

    def serialize(self, value: Any) -> bytes:
        s = self.coerce(value).encode("utf-8")
        return struct.pack("!I", len(s)) + s

    def deserialize(self, data: bytes, offset: int = 0) -> Tuple[str, int]:
        length = struct.unpack_from("!I", data, offset)[0]
        offset += 4
        s = data[offset:offset + length].decode("utf-8")
        return s, offset + length


class BooleanType(DataType):
    """Boolean type."""

    type_id = 5
    name = "BOOLEAN"
    FORMAT = "!?"
    SIZE = 1

    def validate(self, value: Any) -> bool:
        return isinstance(value, bool)

    def coerce(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return bool(value)
        if isinstance(value, str):
            if value.lower() in ("true", "1", "yes"):
                return True
            elif value.lower() in ("false", "0", "no"):
                return False
            raise TypeError(f"Cannot coerce '{value}' to BOOLEAN")
        raise TypeError(f"Cannot coerce {type(value).__name__} to BOOLEAN")

    def serialize(self, value: Any) -> bytes:
        return struct.pack(self.FORMAT, self.coerce(value))

    def deserialize(self, data: bytes, offset: int = 0) -> Tuple[bool, int]:
        return struct.unpack_from(self.FORMAT, data, offset)[0], offset + self.SIZE


class NullType(DataType):
    """NULL type (represents the absence of a value)."""

    type_id = 0
    name = "NULL"

    def validate(self, value: Any) -> bool:
        return value is None

    def coerce(self, value: Any) -> None:
        if value is not None:
            raise TypeError("Cannot coerce non-NULL value to NULL")
        return None

    def serialize(self, value: Any) -> bytes:
        return b"\x00"

    def deserialize(self, data: bytes, offset: int = 0) -> Tuple[None, int]:
        return None, offset + 1


class TimestampType(DataType):
    """Timestamp type (datetime with microsecond precision)."""

    type_id = 6
    name = "TIMESTAMP"
    FORMAT = "!q"
    SIZE = 8

    def validate(self, value: Any) -> bool:
        return isinstance(value, datetime)

    def coerce(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                raise TypeError(f"Cannot coerce '{value}' to TIMESTAMP")
        raise TypeError(f"Cannot coerce {type(value).__name__} to TIMESTAMP")

    def serialize(self, value: Any) -> bytes:
        dt = self.coerce(value)
        ts = int(dt.timestamp() * 1_000_000)
        return struct.pack(self.FORMAT, ts)

    def deserialize(self, data: bytes, offset: int = 0) -> Tuple[datetime, int]:
        ts = struct.unpack_from(self.FORMAT, data, offset)[0]
        return datetime.fromtimestamp(ts / 1_000_000), offset + self.SIZE


class DateType(DataType):
    """Date type (date only, no time component)."""

    type_id = 7
    name = "DATE"
    FORMAT = "!i"
    SIZE = 4

    def validate(self, value: Any) -> bool:
        return isinstance(value, date)

    def coerce(self, value: Any) -> date:
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                raise TypeError(f"Cannot coerce '{value}' to DATE")
        if isinstance(value, (int, float)):
            return date.fromordinal(int(value))
        raise TypeError(f"Cannot coerce {type(value).__name__} to DATE")

    def serialize(self, value: Any) -> bytes:
        d = self.coerce(value)
        return struct.pack(self.FORMAT, d.toordinal())

    def deserialize(self, data: bytes, offset: int = 0) -> Tuple[date, int]:
        ordinal = struct.unpack_from(self.FORMAT, data, offset)[0]
        return date.fromordinal(ordinal), offset + self.SIZE


class ArrayType(DataType):
    """Array type with element type."""

    type_id = 8

    def __init__(self, element_type: DataType) -> None:
        self.element_type = element_type

    @property
    def name(self) -> str:  # type: ignore[override]
        return f"ARRAY<{self.element_type.name}>"

    def validate(self, value: Any) -> bool:
        if not isinstance(value, (list, tuple)):
            return False
        return all(self.element_type.validate(v) for v in value)

    def coerce(self, value: Any) -> list:
        if isinstance(value, (list, tuple)):
            return [self.element_type.coerce(v) for v in value]
        raise TypeError(f"Cannot coerce {type(value).__name__} to ARRAY")

    def serialize(self, value: Any) -> bytes:
        arr = self.coerce(value)
        data = struct.pack("!I", len(arr))
        for v in arr:
            data += self.element_type.serialize(v)
        return data

    def deserialize(self, data: bytes, offset: int = 0) -> Tuple[list, int]:
        length = struct.unpack_from("!I", data, offset)[0]
        offset += 4
        result = []
        for _ in range(length):
            val, offset = self.element_type.deserialize(data, offset)
            result.append(val)
        return result, offset

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ArrayType):
            return self.element_type == other.element_type
        return False

    def __hash__(self) -> int:
        return hash((type(self), self.element_type))


# Type registry
_TYPE_REGISTRY: Dict[int, Type[DataType]] = {
    0: NullType,
    1: IntegerType,
    2: FloatType,
    3: VarcharType,
    4: TextType,
    5: BooleanType,
    6: TimestampType,
    7: DateType,
}


def get_type(type_id: int) -> Type[DataType]:
    """Get a data type class by its type ID.

    Args:
        type_id: Numeric type identifier.

    Returns:
        DataType class.

    Raises:
        ValueError: If type_id is unknown.
    """
    if type_id not in _TYPE_REGISTRY:
        raise ValueError(f"Unknown type ID: {type_id}")
    return _TYPE_REGISTRY[type_id]


def parse_type_string(type_str: str) -> DataType:
    """Parse a type string into a DataType instance.

    Args:
        type_str: Type string (e.g., 'INTEGER', 'VARCHAR(100)', 'FLOAT').

    Returns:
        DataType instance.

    Raises:
        ValueError: If the type string is not recognized.
    """
    type_str = type_str.strip().upper()

    if type_str == "INT" or type_str == "INTEGER" or type_str == "INT4":
        return IntegerType()
    elif type_str == "FLOAT" or type_str == "FLOAT8" or type_str == "DOUBLE" or type_str == "REAL":
        return FloatType()
    elif type_str == "TEXT" or type_str == "STRING":
        return TextType()
    elif type_str == "BOOL" or type_str == "BOOLEAN":
        return BooleanType()
    elif type_str == "NULL":
        return NullType()
    elif type_str == "TIMESTAMP" or type_str == "DATETIME":
        return TimestampType()
    elif type_str == "DATE":
        return DateType()
    elif type_str.startswith("VARCHAR") or type_str.startswith("CHAR"):
        if "(" in type_str and ")" in type_str:
            max_len = int(type_str.split("(")[1].split(")")[0])
            return VarcharType(max_len)
        return VarcharType(255)
    else:
        raise ValueError(f"Unknown type: {type_str}")