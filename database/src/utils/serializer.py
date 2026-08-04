"""Serialization utilities for AinosDB.

Handles binary serialization of database values, tuples, and pages.
"""

from __future__ import annotations

import struct
import pickle
from typing import Any, Dict, List, Optional, Tuple, Union
from datetime import datetime, date
import numpy as np


class Serializer:
    """Binary serializer for database values.

    Supports integers, floats, strings, booleans, None, bytes, lists,
    dicts, and numpy arrays.
    """

    TYPE_NULL = 0
    TYPE_INT = 1
    TYPE_FLOAT = 2
    TYPE_STR = 3
    TYPE_BYTES = 4
    TYPE_BOOL = 5
    TYPE_LIST = 6
    TYPE_DICT = 7
    TYPE_FLOAT32 = 8
    TYPE_FLOAT64 = 9
    TYPE_INT64 = 10
    TYPE_DATETIME = 11
    TYPE_DATE = 12

    @classmethod
    def encode(cls, value: Any) -> bytes:
        """Encode a value to binary format.

        Args:
            value: Value to encode.

        Returns:
            Binary encoded bytes.
        """
        if value is None:
            return struct.pack("!B", cls.TYPE_NULL)
        elif isinstance(value, bool):
            return struct.pack("!BB", cls.TYPE_BOOL, 1 if value else 0)
        elif isinstance(value, int):
            return struct.pack("!Bq", cls.TYPE_INT64, value)
        elif isinstance(value, float):
            return struct.pack("!Bd", cls.TYPE_FLOAT64, value)
        elif isinstance(value, str):
            encoded = value.encode("utf-8")
            return struct.pack("!BI", cls.TYPE_STR, len(encoded)) + encoded
        elif isinstance(value, bytes):
            return struct.pack("!BI", cls.TYPE_BYTES, len(value)) + value
        elif isinstance(value, datetime):
            ts = value.timestamp()
            return struct.pack("!Bd", cls.TYPE_DATETIME, ts)
        elif isinstance(value, date):
            days = value.toordinal()
            return struct.pack("!Bi", cls.TYPE_DATE, days)
        elif isinstance(value, (list, tuple)):
            data = pickle.dumps(value)
            return struct.pack("!BI", cls.TYPE_LIST, len(data)) + data
        elif isinstance(value, dict):
            data = pickle.dumps(value)
            return struct.pack("!BI", cls.TYPE_DICT, len(data)) + data
        elif isinstance(value, np.ndarray):
            data = value.tobytes()
            dtype_code = value.dtype.char
            shape = value.shape
            header = struct.pack("!BBI", cls.TYPE_FLOAT32, len(shape), len(data))
            shape_data = struct.pack(f"!{len(shape)}I", *shape)
            return header + shape_data + data
        else:
            # Fallback to pickle
            data = pickle.dumps(value)
            return struct.pack("!BI", cls.TYPE_DICT, len(data)) + data

    @classmethod
    def decode(cls, data: bytes, offset: int = 0) -> Tuple[Any, int]:
        """Decode a value from binary format.

        Args:
            data: Binary data to decode.
            offset: Starting offset in data.

        Returns:
            Tuple of (decoded value, new offset).
        """
        type_byte = data[offset]
        offset += 1

        if type_byte == cls.TYPE_NULL:
            return None, offset
        elif type_byte == cls.TYPE_BOOL:
            val = struct.unpack_from("!B", data, offset)[0]
            return bool(val), offset + 1
        elif type_byte == cls.TYPE_INT:
            val = struct.unpack_from("!i", data, offset)[0]
            return val, offset + 4
        elif type_byte == cls.TYPE_INT64:
            val = struct.unpack_from("!q", data, offset)[0]
            return val, offset + 8
        elif type_byte == cls.TYPE_FLOAT:
            val = struct.unpack_from("!f", data, offset)[0]
            return val, offset + 4
        elif type_byte == cls.TYPE_FLOAT64:
            val = struct.unpack_from("!d", data, offset)[0]
            return val, offset + 8
        elif type_byte == cls.TYPE_STR:
            length = struct.unpack_from("!I", data, offset)[0]
            offset += 4
            val = data[offset:offset + length].decode("utf-8")
            return val, offset + length
        elif type_byte == cls.TYPE_BYTES:
            length = struct.unpack_from("!I", data, offset)[0]
            offset += 4
            val = data[offset:offset + length]
            return val, offset + length
        elif type_byte == cls.TYPE_LIST:
            length = struct.unpack_from("!I", data, offset)[0]
            offset += 4
            val = pickle.loads(data[offset:offset + length])
            return val, offset + length
        elif type_byte == cls.TYPE_DICT:
            length = struct.unpack_from("!I", data, offset)[0]
            offset += 4
            val = pickle.loads(data[offset:offset + length])
            return val, offset + length
        elif type_byte == cls.TYPE_FLOAT32:
            ndim = struct.unpack_from("!B", data, offset)[0]
            offset += 1
            length = struct.unpack_from("!I", data, offset)[0]
            offset += 4
            shape = struct.unpack_from(f"!{ndim}I", data, offset)
            offset += 4 * ndim
            arr = np.frombuffer(data[offset:offset + length], dtype=np.float32)
            arr = arr.reshape(shape)
            return arr, offset + length
        elif type_byte == cls.TYPE_DATETIME:
            ts = struct.unpack_from("!d", data, offset)[0]
            return datetime.fromtimestamp(ts), offset + 8
        elif type_byte == cls.TYPE_DATE:
            days = struct.unpack_from("!i", data, offset)[0]
            return date.fromordinal(days), offset + 4
        else:
            raise ValueError(f"Unknown type byte: {type_byte}")

    @classmethod
    def encode_row(cls, values: List[Any]) -> bytes:
        """Encode a row of values (for storage in pages).

        Args:
            values: List of values to encode.

        Returns:
            Binary encoded row.
        """
        encoded_values = [cls.encode(v) for v in values]
        lengths = [len(ev) for ev in encoded_values]
        header = struct.pack(f"!H{len(values)}I", len(values), *lengths)
        return header + b"".join(encoded_values)

    @classmethod
    def decode_row(cls, data: bytes, offset: int = 0) -> Tuple[List[Any], int]:
        """Decode a row of values.

        Args:
            data: Binary data to decode.
            offset: Starting offset in data.

        Returns:
            Tuple of (list of values, new offset).
        """
        num_values = struct.unpack_from("!H", data, offset)[0]
        offset += 2
        lengths = list(struct.unpack_from(f"!{num_values}I", data, offset))
        offset += 4 * num_values

        values = []
        for length in lengths:
            val, _ = cls.decode(data, offset)
            values.append(val)
            offset += length

        return values, offset

    @classmethod
    def encode_slot(cls, key: Any, value: Any) -> bytes:
        """Encode a key-value pair (for B+ tree).

        Args:
            key: Key value.
            value: Value to store.

        Returns:
            Binary encoded slot.
        """
        key_data = cls.encode(key)
        val_data = cls.encode(value)
        return struct.pack("!II", len(key_data), len(val_data)) + key_data + val_data

    @classmethod
    def decode_slot(cls, data: bytes, offset: int = 0) -> Tuple[Any, Any, int]:
        """Decode a key-value pair.

        Args:
            data: Binary data to decode.
            offset: Starting offset in data.

        Returns:
            Tuple of (key, value, new offset).
        """
        key_len, val_len = struct.unpack_from("!II", data, offset)
        offset += 8
        key, _ = cls.decode(data, offset)
        offset += key_len
        val, _ = cls.decode(data, offset)
        offset += val_len
        return key, val, offset


class ObjectSerializer:
    """JSON-like serializer for complex objects.

    Handles serialization of database objects, including nested structures,
    using a JSON-compatible format with type information.
    """

    @staticmethod
    def to_dict(obj: Any) -> Any:
        """Convert an object to a JSON-serializable dict."""
        if obj is None or isinstance(obj, (bool, int, float, str)):
            return obj
        elif isinstance(obj, (list, tuple)):
            return [ObjectSerializer.to_dict(item) for item in obj]
        elif isinstance(obj, dict):
            return {str(k): ObjectSerializer.to_dict(v) for k, v in obj.items()}
        elif isinstance(obj, datetime):
            return {"__type__": "datetime", "value": obj.isoformat()}
        elif isinstance(obj, date):
            return {"__type__": "date", "value": obj.isoformat()}
        elif isinstance(obj, np.ndarray):
            return {"__type__": "ndarray", "dtype": str(obj.dtype), "shape": list(obj.shape), "data": obj.tolist()}
        elif hasattr(obj, "__dict__"):
            return {k: ObjectSerializer.to_dict(v) for k, v in obj.__dict__.items()}
        else:
            return str(obj)

    @staticmethod
    def from_dict(data: Any) -> Any:
        """Restore an object from a dict created by to_dict."""
        if isinstance(data, dict):
            if "__type__" in data:
                type_name = data["__type__"]
                if type_name == "datetime":
                    return datetime.fromisoformat(data["value"])
                elif type_name == "date":
                    return date.fromisoformat(data["value"])
                elif type_name == "ndarray":
                    return np.array(data["data"], dtype=data["dtype"]).reshape(data["shape"])
            return {k: ObjectSerializer.from_dict(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [ObjectSerializer.from_dict(item) for item in data]
        return data