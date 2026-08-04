"""
Protocol definition for the NDJSON over TCP server.

Defines the message format, request/response types, and error codes
for the AinosOS IPC-compatible protocol.
"""

import json
import uuid
import time
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field, asdict
from enum import Enum


class ErrorCode(int, Enum):
    """Error codes for protocol responses."""
    SUCCESS = 0
    UNKNOWN_ERROR = 1
    INVALID_REQUEST = 2
    METHOD_NOT_FOUND = 3
    INVALID_PARAMS = 4
    COLLECTION_NOT_FOUND = 10
    COLLECTION_ALREADY_EXISTS = 11
    INDEX_NOT_TRAINED = 12
    INVALID_VECTOR_DIMENSION = 13
    STORAGE_ERROR = 20
    SERIALIZATION_ERROR = 21
    INTERNAL_ERROR = 99


class MessageType(str, Enum):
    """Types of messages in the protocol."""
    REQUEST = "request"
    RESPONSE = "response"
    EVENT = "event"
    ERROR = "error"
    HEARTBEAT = "heartbeat"


@dataclass
class NDJSONMessage:
    """Base message format for NDJSON protocol."""
    type: str
    id: Optional[str] = None
    version: str = "1.0"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    def to_ndjson(self) -> str:
        return self.to_json() + '\n'


@dataclass
class Request(NDJSONMessage):
    """Request message."""
    method: str = ""
    params: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.type = MessageType.REQUEST.value
        if self.id is None:
            self.id = str(uuid.uuid4())


@dataclass
class Response(NDJSONMessage):
    """Response message."""
    success: bool = True
    result: Any = None
    error: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        self.type = MessageType.RESPONSE.value


@dataclass
class Event(NDJSONMessage):
    """Server-sent event message."""
    event: str = ""
    data: Any = None

    def __post_init__(self):
        self.type = MessageType.EVENT.value


@dataclass
class Heartbeat(NDJSONMessage):
    """Heartbeat message for keep-alive."""

    def __post_init__(self):
        self.type = MessageType.HEARTBEAT.value


class Protocol:
    """NDJSON protocol handler for the vector database server.

    Handles encoding/decoding of messages according to the
    AinosOS IPC protocol specification.
    """

    @staticmethod
    def parse(line: str) -> Optional[NDJSONMessage]:
        """Parse a single NDJSON line into a message object.

        Args:
            line: A single line of NDJSON

        Returns:
            Parsed message object, or None if parsing failed.
        """
        line = line.strip()
        if not line:
            return None

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None

        msg_type = data.get('type')

        if msg_type == MessageType.REQUEST.value:
            return Request(
                id=data.get('id'),
                method=data.get('method', ''),
                params=data.get('params', {}),
                version=data.get('version', '1.0'),
                timestamp=data.get('timestamp', time.time()),
            )
        elif msg_type == MessageType.RESPONSE.value:
            return Response(
                id=data.get('id'),
                success=data.get('success', True),
                result=data.get('result'),
                error=data.get('error'),
                version=data.get('version', '1.0'),
                timestamp=data.get('timestamp', time.time()),
            )
        elif msg_type == MessageType.EVENT.value:
            return Event(
                event=data.get('event', ''),
                data=data.get('data'),
                version=data.get('version', '1.0'),
                timestamp=data.get('timestamp', time.time()),
            )
        elif msg_type == MessageType.HEARTBEAT.value:
            return Heartbeat(
                version=data.get('version', '1.0'),
                timestamp=data.get('timestamp', time.time()),
            )
        else:
            return None

    @staticmethod
    def create_request(method: str, params: Dict[str, Any] = None,
                       request_id: Optional[str] = None) -> str:
        """Create an NDJSON request string.

        Args:
            method: Method name
            params: Parameters dictionary
            request_id: Optional request ID

        Returns:
            NDJSON request string.
        """
        req = Request(
            id=request_id or str(uuid.uuid4()),
            method=method,
            params=params or {},
        )
        return req.to_ndjson()

    @staticmethod
    def create_success_response(request_id: str, result: Any = None) -> str:
        """Create a success response NDJSON string.

        Args:
            request_id: Request ID to respond to
            result: Result data

        Returns:
            NDJSON response string.
        """
        resp = Response(
            id=request_id,
            success=True,
            result=result,
        )
        return resp.to_ndjson()

    @staticmethod
    def create_error_response(request_id: str, code: ErrorCode,
                               message: str) -> str:
        """Create an error response NDJSON string.

        Args:
            request_id: Request ID to respond to
            code: Error code
            message: Error message

        Returns:
            NDJSON response string.
        """
        resp = Response(
            id=request_id,
            success=False,
            error={
                'code': int(code),
                'message': message,
            },
        )
        return resp.to_ndjson()

    @staticmethod
    def create_event(event_type: str, data: Any = None) -> str:
        """Create an event NDJSON string.

        Args:
            event_type: Event type name
            data: Event data

        Returns:
            NDJSON event string.
        """
        event = Event(event=event_type, data=data)
        return event.to_ndjson()

    @staticmethod
    def create_heartbeat() -> str:
        """Create a heartbeat NDJSON string.

        Returns:
            NDJSON heartbeat string.
        """
        return Heartbeat().to_ndjson()

    @staticmethod
    def encode_batch(messages: List[NDJSONMessage]) -> str:
        """Encode multiple messages as NDJSON.

        Args:
            messages: List of message objects

        Returns:
            NDJSON string with multiple lines.
        """
        return ''.join(msg.to_ndjson() for msg in messages)

    @staticmethod
    def parse_batch(data: str) -> List[NDJSONMessage]:
        """Parse multiple NDJSON lines.

        Args:
            data: NDJSON data with multiple lines

        Returns:
            List of parsed message objects.
        """
        messages = []
        for line in data.split('\n'):
            msg = Protocol.parse(line)
            if msg is not None:
                messages.append(msg)
        return messages


# Supported API methods
SUPPORTED_METHODS = {
    'create_index',
    'drop_index',
    'insert',
    'search',
    'delete',
    'get',
    'stats',
    'persist',
    'load',
    'list_collections',
    'get_collection_info',
    'search_with_filter',
    'ping',
    'health',
    'metrics',
}

# Method parameter schemas
METHOD_SCHEMAS = {
    'create_index': {
        'required': ['name', 'dimension'],
        'optional': ['index_type', 'metric', 'M', 'ef_construction', 'ef_search',
                     'nlist', 'nprobe', 'm_subquantizers', 'nbits', 'nbits_lsh',
                     'num_tables', 'storage_type', 'persist_path'],
    },
    'drop_index': {
        'required': ['name'],
        'optional': [],
    },
    'insert': {
        'required': ['collection', 'vectors'],
        'optional': ['metadata', 'ids'],
    },
    'search': {
        'required': ['collection', 'query_vector'],
        'optional': ['top_k'],
    },
    'delete': {
        'required': ['collection', 'ids'],
        'optional': [],
    },
    'get': {
        'required': ['collection', 'ids'],
        'optional': [],
    },
    'stats': {
        'required': [],
        'optional': ['collection'],
    },
    'persist': {
        'required': ['path'],
        'optional': [],
    },
    'load': {
        'required': ['path'],
        'optional': [],
    },
    'list_collections': {
        'required': [],
        'optional': [],
    },
    'get_collection_info': {
        'required': ['name'],
        'optional': [],
    },
    'search_with_filter': {
        'required': ['collection', 'query_vector'],
        'optional': ['top_k', 'filters', 'tags'],
    },
    'ping': {
        'required': [],
        'optional': [],
    },
    'health': {
        'required': [],
        'optional': [],
    },
    'metrics': {
        'required': [],
        'optional': [],
    },
}