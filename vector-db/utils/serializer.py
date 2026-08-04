"""
Serialization utilities for the vector database.
"""

import struct
import json
import pickle
import numpy as np
from typing import Any, Dict, List, Optional, Tuple, Union
from enum import Enum


class SerializationFormat(str, Enum):
    """Supported serialization formats."""
    JSON = "json"
    PICKLE = "pickle"
    NPY = "npy"
    BINARY = "binary"


class Serializer:
    """Handles serialization and deserialization of vectors and metadata."""

    # Format identifiers for binary serialization
    MAGIC_HEADER = b"AINOSVEC"
    VERSION = 1

    # Struct format characters for different dtypes
    DTYPE_MAP = {
        np.dtype('float32'): 'f',
        np.dtype('float64'): 'd',
        np.dtype('int8'): 'b',
        np.dtype('int16'): 'h',
        np.dtype('int32'): 'i',
        np.dtype('int64'): 'q',
        np.dtype('uint8'): 'B',
        np.dtype('uint16'): 'H',
        np.dtype('uint32'): 'I',
        np.dtype('uint64'): 'Q',
    }

    @staticmethod
    def vector_to_bytes(vector: np.ndarray) -> bytes:
        """Serialize a single vector to bytes."""
        if vector.dtype not in [np.float32, np.float64]:
            vector = vector.astype(np.float32)
        return vector.tobytes()

    @staticmethod
    def vectors_to_bytes(vectors: np.ndarray) -> bytes:
        """Serialize multiple vectors to bytes."""
        if vectors.dtype not in [np.float32, np.float64]:
            vectors = vectors.astype(np.float32)
        return vectors.tobytes()

    @staticmethod
    def bytes_to_vector(data: bytes, dtype: np.dtype = np.float32) -> np.ndarray:
        """Deserialize bytes to a single vector."""
        return np.frombuffer(data, dtype=dtype)

    @staticmethod
    def bytes_to_vectors(data: bytes, dimension: int, dtype: np.dtype = np.float32) -> np.ndarray:
        """Deserialize bytes to multiple vectors."""
        return np.frombuffer(data, dtype=dtype).reshape(-1, dimension)

    @staticmethod
    def serialize_metadata(metadata: Union[Dict[str, Any], List[Dict[str, Any]]]) -> bytes:
        """Serialize metadata to bytes using JSON."""
        return json.dumps(metadata, default=str).encode('utf-8')

    @staticmethod
    def deserialize_metadata(data: bytes) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """Deserialize metadata from bytes."""
        return json.loads(data.decode('utf-8'))

    @staticmethod
    def serialize_index_data(data: Dict[str, Any]) -> bytes:
        """Serialize index data using pickle."""
        return pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)

    @staticmethod
    def deserialize_index_data(data: bytes) -> Dict[str, Any]:
        """Deserialize index data from pickle."""
        return pickle.loads(data)

    @staticmethod
    def serialize_binary_format(vectors: np.ndarray, ids: Optional[np.ndarray] = None,
                                 metadata: Optional[List[Dict[str, Any]]] = None) -> bytes:
        """
        Serialize vectors, ids, and metadata in a custom binary format.

        Format:
        - Magic header (8 bytes): "AINOSVEC"
        - Version (4 bytes): uint32
        - Num vectors (4 bytes): uint32
        - Dimension (4 bytes): uint32
        - Dtype code (1 byte): 0=float32, 1=float64
        - Has ids (1 byte): 0 or 1
        - Has metadata (1 byte): 0 or 1
        - Vector data (N * D * sizeof(dtype) bytes)
        - Ids (if present): N * 8 bytes (int64)
        - Metadata JSON (if present): 4 bytes length + JSON bytes
        """
        n = vectors.shape[0]
        dim = vectors.shape[1]
        dtype_code = 0 if vectors.dtype == np.float32 else 1

        # Build header
        header = Serializer.MAGIC_HEADER
        header += struct.pack('<I', Serializer.VERSION)
        header += struct.pack('<I', n)
        header += struct.pack('<I', dim)
        header += struct.pack('<B', dtype_code)

        has_ids = 1 if ids is not None else 0
        has_meta = 1 if metadata is not None else 0
        header += struct.pack('<B', has_ids)
        header += struct.pack('<B', has_meta)

        # Vector data
        vector_data = vectors.tobytes()

        # Ids
        id_data = b''
        if ids is not None:
            id_data = np.asarray(ids, dtype=np.int64).tobytes()

        # Metadata
        meta_data = b''
        if metadata is not None:
            meta_json = json.dumps(metadata, default=str).encode('utf-8')
            meta_data = struct.pack('<I', len(meta_json)) + meta_json

        return header + vector_data + id_data + meta_data

    @staticmethod
    def deserialize_binary_format(data: bytes) -> Tuple[np.ndarray, Optional[np.ndarray], Optional[List[Dict[str, Any]]]]:
        """Deserialize the custom binary format."""
        # Parse header
        offset = 0
        magic = data[offset:offset + 8]
        offset += 8
        if magic != Serializer.MAGIC_HEADER:
            raise ValueError(f"Invalid magic header: {magic}")

        version = struct.unpack('<I', data[offset:offset + 4])[0]
        offset += 4
        if version > Serializer.VERSION:
            raise ValueError(f"Unsupported version: {version}")

        n = struct.unpack('<I', data[offset:offset + 4])[0]
        offset += 4
        dim = struct.unpack('<I', data[offset:offset + 4])[0]
        offset += 4
        dtype_code = struct.unpack('<B', data[offset:offset + 1])[0]
        offset += 1
        dtype = np.float32 if dtype_code == 0 else np.float64

        has_ids = bool(struct.unpack('<B', data[offset:offset + 1])[0])
        offset += 1
        has_meta = bool(struct.unpack('<B', data[offset:offset + 1])[0])
        offset += 1

        # Vector data
        vec_size = n * dim * (4 if dtype == np.float32 else 8)
        vector_data = data[offset:offset + vec_size]
        offset += vec_size
        vectors = np.frombuffer(vector_data, dtype=dtype).reshape(n, dim)

        # Ids
        ids = None
        if has_ids:
            id_size = n * 8
            id_data = data[offset:offset + id_size]
            offset += id_size
            ids = np.frombuffer(id_data, dtype=np.int64)

        # Metadata
        metadata = None
        if has_meta:
            meta_len = struct.unpack('<I', data[offset:offset + 4])[0]
            offset += 4
            meta_data = data[offset:offset + meta_len]
            offset += meta_len
            metadata = json.loads(meta_data.decode('utf-8'))

        return vectors, ids, metadata

    @staticmethod
    def serialize_search_result(results: List[Tuple[int, float, Optional[Dict[str, Any]]]]) -> bytes:
        """Serialize search results to JSON bytes."""
        serialized = []
        for r in results:
            entry = {"id": int(r[0]), "score": float(r[1])}
            if r[2] is not None:
                entry["metadata"] = r[2]
            serialized.append(entry)
        return json.dumps(serialized).encode('utf-8')

    @staticmethod
    def deserialize_search_result(data: bytes) -> List[Tuple[int, float, Optional[Dict[str, Any]]]]:
        """Deserialize search results from JSON bytes."""
        entries = json.loads(data.decode('utf-8'))
        results = []
        for entry in entries:
            meta = entry.get("metadata")
            results.append((entry["id"], entry["score"], meta))
        return results

    @staticmethod
    def serialize_stats(stats: Dict[str, Any]) -> bytes:
        """Serialize statistics to JSON bytes."""
        return json.dumps(stats, default=str).encode('utf-8')

    @staticmethod
    def deserialize_stats(data: bytes) -> Dict[str, Any]:
        """Deserialize statistics from JSON bytes."""
        return json.loads(data.decode('utf-8'))

    @staticmethod
    def encode_vector_for_json(vector: np.ndarray) -> List[float]:
        """Encode a numpy vector as a JSON-compatible list."""
        return vector.tolist()

    @staticmethod
    def decode_vector_from_json(data: List[float]) -> np.ndarray:
        """Decode a JSON list back to a numpy vector."""
        return np.array(data, dtype=np.float32)

    @staticmethod
    def serialize_ndjson(obj: Any) -> bytes:
        """Serialize an object to NDJSON line."""
        return (json.dumps(obj, default=str) + '\n').encode('utf-8')

    @staticmethod
    def deserialize_ndjson_line(line: str) -> Any:
        """Deserialize a single NDJSON line."""
        return json.loads(line)


class VectorSerializer:
    """Specialized serializer for vector operations."""

    @staticmethod
    def pack_vectors_with_ids(vectors: np.ndarray, ids: np.ndarray) -> bytes:
        """Pack vectors and their IDs into a compact binary format."""
        n = vectors.shape[0]
        dim = vectors.shape[1]

        # Convert to float32 for consistency
        if vectors.dtype != np.float32:
            vectors = vectors.astype(np.float32)

        # Pack: n (4) + dim (4) + ids (n*8) + vectors (n*dim*4)
        header = struct.pack('<II', n, dim)
        id_data = np.asarray(ids, dtype=np.int64).tobytes()
        vec_data = vectors.tobytes()
        return header + id_data + vec_data

    @staticmethod
    def unpack_vectors_with_ids(data: bytes) -> Tuple[np.ndarray, np.ndarray]:
        """Unpack vectors and IDs from binary format."""
        offset = 0
        n, dim = struct.unpack('<II', data[offset:offset + 8])
        offset += 8

        ids = np.frombuffer(data[offset:offset + n * 8], dtype=np.int64)
        offset += n * 8

        vectors = np.frombuffer(data[offset:offset + n * dim * 4], dtype=np.float32)
        vectors = vectors.reshape(n, dim)

        return vectors, ids


class NDJSONProtocol:
    """NDJSON protocol helper for the TCP server."""

    @staticmethod
    def encode_request(request_id: str, method: str, params: Dict[str, Any]) -> str:
        """Encode a request as NDJSON."""
        return json.dumps({
            "type": "request",
            "id": request_id,
            "method": method,
            "params": params,
            "version": "1.0"
        }) + '\n'

    @staticmethod
    def encode_response(request_id: str, success: bool, result: Any = None,
                         error: Optional[str] = None) -> str:
        """Encode a response as NDJSON."""
        msg = {
            "type": "response",
            "id": request_id,
            "success": success,
        }
        if success and result is not None:
            msg["result"] = result
        if not success and error is not None:
            msg["error"] = error
        return json.dumps(msg) + '\n'

    @staticmethod
    def encode_event(event_type: str, data: Any) -> str:
        """Encode a server-sent event as NDJSON."""
        return json.dumps({
            "type": "event",
            "event": event_type,
            "data": data
        }) + '\n'

    @staticmethod
    def encode_error(request_id: str, code: int, message: str) -> str:
        """Encode an error response."""
        return json.dumps({
            "type": "response",
            "id": request_id,
            "success": False,
            "error": {
                "code": code,
                "message": message
            }
        }) + '\n'

    @staticmethod
    def decode(line: str) -> Optional[Dict[str, Any]]:
        """Decode a single NDJSON line."""
        line = line.strip()
        if not line:
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def encode_batch(responses: List[Dict[str, Any]]) -> str:
        """Encode multiple responses."""
        return ''.join(json.dumps(r, default=str) + '\n' for r in responses)