"""
Request handler for the vector database TCP server.

Processes incoming NDJSON requests and dispatches them to the
appropriate database methods, serializing responses back to NDJSON.
"""

import numpy as np
import json
import traceback
from typing import Any, Dict, List, Optional, Tuple

from server.protocol import (
    Protocol, Request, Response, ErrorCode, SUPPORTED_METHODS, METHOD_SCHEMAS
)
from database import VectorDatabase
from utils.serializer import Serializer, NDJSONProtocol


class RequestHandler:
    """Handles incoming requests by dispatching to database methods.

    Validates requests, executes database operations, and formats responses.
    """

    def __init__(self, database: VectorDatabase):
        self.db = database

    def handle_request(self, request: Request) -> str:
        """Handle a single request and return an NDJSON response.

        Args:
            request: Parsed request message

        Returns:
            NDJSON response string.
        """
        request_id = request.id or 'unknown'
        method = request.method
        params = request.params or {}

        # Validate method
        if method not in SUPPORTED_METHODS:
            return Protocol.create_error_response(
                request_id, ErrorCode.METHOD_NOT_FOUND,
                f"Unknown method: {method}"
            )

        # Validate parameters
        validation_error = self._validate_params(method, params)
        if validation_error:
            return Protocol.create_error_response(
                request_id, ErrorCode.INVALID_PARAMS, validation_error
            )

        # Dispatch to handler
        try:
            handler = getattr(self, f'_handle_{method}', None)
            if handler is None:
                return Protocol.create_error_response(
                    request_id, ErrorCode.METHOD_NOT_FOUND,
                    f"No handler for method: {method}"
                )

            result = handler(params)
            return Protocol.create_success_response(request_id, result)

        except ValueError as e:
            return Protocol.create_error_response(
                request_id, ErrorCode.INVALID_PARAMS, str(e)
            )
        except KeyError as e:
            return Protocol.create_error_response(
                request_id, ErrorCode.COLLECTION_NOT_FOUND, str(e)
            )
        except Exception as e:
            traceback.print_exc()
            return Protocol.create_error_response(
                request_id, ErrorCode.INTERNAL_ERROR, str(e)
            )

    def _validate_params(self, method: str, params: Dict[str, Any]) -> Optional[str]:
        """Validate parameters for a method.

        Args:
            method: Method name
            params: Parameters dictionary

        Returns:
            Error message string if invalid, None if valid.
        """
        schema = METHOD_SCHEMAS.get(method)
        if schema is None:
            return None

        # Check required params
        for key in schema.get('required', []):
            if key not in params:
                return f"Missing required parameter: '{key}'"

        # Check for unknown params
        all_keys = set(schema.get('required', []) + schema.get('optional', []))
        for key in params:
            if key not in all_keys:
                return f"Unknown parameter: '{key}'"

        return None

    def _handle_create_index(self, params: Dict[str, Any]) -> bool:
        """Handle create_index request.

        Args:
            params: Request parameters

        Returns:
            True if index was created.
        """
        name = params['name']
        dimension = int(params['dimension'])
        index_type = params.get('index_type', 'flat')
        metric = params.get('metric', 'cosine')

        # Extract index-specific params
        kwargs = {}
        for key in ['M', 'ef_construction', 'ef_search', 'nlist', 'nprobe',
                     'm_subquantizers', 'nbits', 'storage_type', 'persist_path']:
            if key in params:
                kwargs[key] = params[key]

        return self.db.create_index(
            name=name,
            dimension=dimension,
            index_type=index_type,
            metric=metric,
            **kwargs
        )

    def _handle_drop_index(self, params: Dict[str, Any]) -> bool:
        """Handle drop_index request.

        Args:
            params: Request parameters

        Returns:
            True if index was dropped.
        """
        return self.db.drop_index(params['name'])

    def _handle_insert(self, params: Dict[str, Any]) -> int:
        """Handle insert request.

        Args:
            params: Request parameters

        Returns:
            Number of vectors inserted.
        """
        collection = params['collection']
        vectors_data = params['vectors']
        metadata = params.get('metadata')

        # Decode vectors
        vectors = np.array(vectors_data, dtype=np.float32)

        # Decode metadata if provided
        if metadata is not None and isinstance(metadata, list):
            # metadata is already a list of dicts from JSON
            pass

        return self.db.insert(collection, vectors, metadata)

    def _handle_search(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handle search request.

        Args:
            params: Request parameters

        Returns:
            List of search results.
        """
        collection = params['collection']
        query_data = params['query_vector']
        top_k = int(params.get('top_k', 10))

        query_vector = np.array(query_data, dtype=np.float32)
        results = self.db.search(collection, query_vector, top_k)

        return [r.to_dict() for r in results]

    def _handle_delete(self, params: Dict[str, Any]) -> int:
        """Handle delete request.

        Args:
            params: Request parameters

        Returns:
            Number of vectors deleted.
        """
        collection = params['collection']
        ids = [int(i) for i in params['ids']]
        return self.db.delete(collection, ids)

    def _handle_get(self, params: Dict[str, Any]) -> List[Optional[Dict[str, Any]]]:
        """Handle get request.

        Args:
            params: Request parameters

        Returns:
            List of vector data.
        """
        collection = params['collection']
        ids = [int(i) for i in params['ids']]
        results = self.db.get(collection, ids)

        output = []
        for r in results:
            if r is not None:
                output.append(r.to_dict())
            else:
                output.append(None)
        return output

    def _handle_stats(self, params: Dict[str, Any]) -> Any:
        """Handle stats request.

        Args:
            params: Request parameters

        Returns:
            Statistics data.
        """
        collection = params.get('collection')
        stats = self.db.stats(collection)

        if isinstance(stats, dict):
            return {k: v.to_dict() if hasattr(v, 'to_dict') else v
                    for k, v in stats.items()}
        return stats.to_dict() if hasattr(stats, 'to_dict') else stats

    def _handle_persist(self, params: Dict[str, Any]) -> bool:
        """Handle persist request.

        Args:
            params: Request parameters

        Returns:
            True if persisted successfully.
        """
        return self.db.persist(params['path'])

    def _handle_load(self, params: Dict[str, Any]) -> bool:
        """Handle load request.

        Args:
            params: Request parameters

        Returns:
            True if loaded successfully.
        """
        return self.db.load(params['path'])

    def _handle_list_collections(self, params: Dict[str, Any]) -> List[str]:
        """Handle list_collections request.

        Args:
            params: Request parameters (unused)

        Returns:
            List of collection names.
        """
        return self.db.list_collections()

    def _handle_get_collection_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle get_collection_info request.

        Args:
            params: Request parameters

        Returns:
            Collection information.
        """
        return self.db.get_collection_info(params['name'])

    def _handle_search_with_filter(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handle search_with_filter request.

        Args:
            params: Request parameters

        Returns:
            List of search results.
        """
        collection = params['collection']
        query_data = params['query_vector']
        top_k = int(params.get('top_k', 10))
        filters = params.get('filters')
        tags = params.get('tags')

        query_vector = np.array(query_data, dtype=np.float32)
        results = self.db.search_with_filter(
            collection, query_vector, top_k, filters, tags
        )

        return [r.to_dict() for r in results]

    def _handle_ping(self, params: Dict[str, Any]) -> str:
        """Handle ping request.

        Args:
            params: Request parameters (unused)

        Returns:
            "pong"
        """
        return "pong"

    def _handle_health(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle health request.

        Args:
            params: Request parameters (unused)

        Returns:
            Health status dictionary.
        """
        import time
        return {
            "status": "ok",
            "timestamp": time.time(),
            "collections": len(self.db.list_collections()),
            "total_vectors": sum(
                self.db.stats(c).size for c in self.db.list_collections()
            ) if self.db.list_collections() else 0,
        }

    def _handle_metrics(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle metrics request.

        Args:
            params: Request parameters (unused)

        Returns:
            Metrics data.
        """
        return self.db.metrics.get_all_stats()