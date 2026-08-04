"""
Ainos SDK - Streaming Inference
================================

Provides the streaming iterator for consuming token-by-token inference
responses from the Ainos daemon.

The Ainos daemon supports Server-Sent Events (SSE)-style streaming over the
NDJSON protocol. When a request is sent with ``stream=True``, the daemon
responds with multiple ``"stream"`` type messages, each containing a single
token or chunk of the generated output.

Usage::

    async for chunk in client.infer_stream("my-model", "Hello world"):
        print(chunk.token, end="", flush=True)
        if chunk.final:
            print(f"\\nDone. Reason: {chunk.finish_reason}")

Architecture::

    ┌──────────────┐     ┌─────────────────┐     ┌──────────────┐
    │  AinosClient │────▶│  StreamIterator  │────▶│  asyncio.Queue│
    │              │     │                  │     │  (chunks)    │
    └──────────────┘     └─────────────────┘     └──────────────┘
"""

from __future__ import annotations

import asyncio
import logging
import typing as t
from dataclasses import dataclass, field

from ainos.errors import (
    InferenceError,
    StreamError,
    StreamInterruptedError,
    StreamNotStartedError,
)
from ainos.types import (
    InferenceChunk,
    JSONObject,
    RequestMessage,
    TokenUsage,
)
from ainos.utils import generate_request_id, json_encode, timestamp

log: logging.Logger = logging.getLogger("ainos.stream")

#: Maximum number of chunks that can be buffered in the stream queue.
_MAX_QUEUE_SIZE: int = 4096


# ---------------------------------------------------------------------------
# Stream events
# ---------------------------------------------------------------------------


@dataclass
class StreamEvent:
    """An event that occurs during streaming.

    This is used internally by the stream iterator to communicate between
    the transport layer and the consumer.

    Attributes:
        type: The event type (``"chunk"``, ``"error"``, or ``"done"``).
        chunk: The inference chunk (for ``"chunk"`` events).
        error: The error (for ``"error"`` events).
        final_data: The final response data (for ``"done"`` events).
    """

    type: str  # "chunk", "error", "done"
    chunk: t.Optional[InferenceChunk] = None
    error: t.Optional[BaseException] = None
    final_data: t.Optional[JSONObject] = None


# ---------------------------------------------------------------------------
# StreamIterator
# ---------------------------------------------------------------------------


class StreamIterator:
    """Async iterator that yields inference chunks from a streaming response.

    This class is not instantiated directly; instead, it is returned by
    ``AinosClient.infer_stream()``.

    The iterator reads from an internal ``asyncio.Queue`` that is populated
    by the transport layer's message handler.

    Attributes:
        request_id: The UUID of the streaming request.
        model: The model identifier.
        stream_started: Whether the stream has been started.
        stream_finished: Whether the stream has completed.
        token_count: Number of tokens received so far.
    """

    def __init__(
        self,
        request_id: str,
        model: str,
        queue: asyncio.Queue[StreamEvent],
        *,
        timeout: float = 60.0,
    ) -> None:
        """Initialise the stream iterator.

        Args:
            request_id: The UUID of the streaming request.
            model: The model identifier.
            queue: The queue that receives stream events from the transport.
            timeout: Maximum time to wait for the next chunk.
        """
        self.request_id: str = request_id
        self.model: str = model
        self._queue: asyncio.Queue[StreamEvent] = queue
        self._timeout: float = timeout

        self._stream_started: bool = False
        self._stream_finished: bool = False
        self._token_count: int = 0
        self._start_time: float = 0.0
        self._total_time: float = 0.0
        self._generated_text: t.List[str] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def stream_started(self) -> bool:
        """Whether the stream has started receiving chunks."""
        return self._stream_started

    @property
    def stream_finished(self) -> bool:
        """Whether the stream has completed."""
        return self._stream_finished

    @property
    def token_count(self) -> int:
        """Number of tokens received so far."""
        return self._token_count

    @property
    def elapsed(self) -> float:
        """Elapsed time since the stream started, in seconds.

        Returns:
            Elapsed time in seconds, or 0.0 if the stream has not started.
        """
        if self._start_time == 0.0:
            return 0.0
        if self._stream_finished:
            return self._total_time
        return timestamp() - self._start_time

    @property
    def generated_text(self) -> str:
        """The full text generated so far (concatenation of all tokens)."""
        return "".join(self._generated_text)

    # ------------------------------------------------------------------
    # Async iterator protocol
    # ------------------------------------------------------------------

    def __aiter__(self) -> "StreamIterator":
        """Return self as the async iterator."""
        if not self._stream_started:
            self._stream_started = True
            self._start_time = timestamp()
        return self

    async def __anext__(self) -> InferenceChunk:
        """Get the next chunk from the stream.

        Returns:
            The next InferenceChunk.

        Raises:
            StopAsyncIteration: When the stream has completed.
            StreamInterruptedError: If the stream is interrupted.
            StreamError: If a stream error occurs.
            asyncio.TimeoutError: If no chunk is received within the timeout.
        """
        if self._stream_finished:
            raise StopAsyncIteration

        try:
            event: StreamEvent = await asyncio.wait_for(
                self._queue.get(),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            self._stream_finished = True
            raise

        if event.type == "done":
            self._stream_finished = True
            self._total_time = timestamp() - self._start_time
            raise StopAsyncIteration

        if event.type == "error":
            self._stream_finished = True
            self._total_time = timestamp() - self._start_time
            if event.error is not None:
                raise event.error
            raise StreamError("Unknown stream error")

        if event.type == "chunk" and event.chunk is not None:
            chunk: InferenceChunk = event.chunk
            self._token_count += 1
            if chunk.token:
                self._generated_text.append(chunk.token)

            if chunk.final:
                self._stream_finished = True
                self._total_time = timestamp() - self._start_time

            return chunk

        raise StreamError(f"Unknown stream event type: {event.type}")

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    async def collect(self) -> str:
        """Collect all tokens from the stream into a single string.

        This is a convenience method that iterates over the entire stream
        and returns the concatenated text.

        Returns:
            The full generated text.

        Example:
            text = await client.infer_stream("model", "Hello").collect()
        """
        result: t.List[str] = []
        async for chunk in self:
            result.append(chunk.token)
        return "".join(result)

    async def cancel(self) -> None:
        """Cancel the stream early.

        This stops the stream and prevents further chunks from being
        processed. The stream is marked as finished.
        """
        self._stream_finished = True
        self._total_time = timestamp() - self._start_time
        log.info("Stream %s cancelled after %d tokens", self.request_id, self._token_count)

    def get_stats(self) -> t.Dict[str, t.Any]:
        """Get stream statistics.

        Returns:
            A dictionary of stream statistics.
        """
        return {
            "request_id": self.request_id,
            "model": self.model,
            "token_count": self._token_count,
            "elapsed": self.elapsed,
            "stream_started": self._stream_started,
            "stream_finished": self._stream_finished,
            "generated_text_length": len(self.generated_text),
        }

    def __repr__(self) -> str:
        """Return a string representation of the stream iterator."""
        return (
            f"StreamIterator(request_id={self.request_id}, "
            f"model={self.model}, "
            f"tokens={self._token_count}, "
            f"finished={self._stream_finished})"
        )


# ---------------------------------------------------------------------------
# Stream manager
# ---------------------------------------------------------------------------


class StreamManager:
    """Manages multiple active streams.

    The StreamManager keeps track of all active streams, allowing the client
    to manage and monitor concurrent streaming requests.

    Usage::

        manager = StreamManager()
        iterator = manager.create_stream(request_id, model)
        # ... later ...
        active = manager.list_active_streams()
    """

    def __init__(self) -> None:
        """Initialise the stream manager."""
        self._streams: t.Dict[str, StreamIterator] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    async def create_stream(
        self,
        request_id: str,
        model: str,
        *,
        timeout: float = 60.0,
    ) -> StreamIterator:
        """Create a new stream iterator and register it.

        Args:
            request_id: The UUID of the streaming request.
            model: The model identifier.
            timeout: Timeout for each chunk read.

        Returns:
            A new StreamIterator instance.

        Raises:
            ValueError: If a stream with the same request_id already exists.
        """
        async with self._lock:
            if request_id in self._streams:
                raise ValueError(
                    f"Stream '{request_id}' already exists"
                )

            queue: asyncio.Queue[StreamEvent] = asyncio.Queue(
                maxsize=_MAX_QUEUE_SIZE
            )
            iterator: StreamIterator = StreamIterator(
                request_id,
                model,
                queue,
                timeout=timeout,
            )
            self._streams[request_id] = iterator
            return iterator

    async def get_stream(self, request_id: str) -> t.Optional[StreamIterator]:
        """Get a stream iterator by request ID.

        Args:
            request_id: The UUID of the streaming request.

        Returns:
            The StreamIterator, or None if not found.
        """
        async with self._lock:
            return self._streams.get(request_id)

    async def remove_stream(self, request_id: str) -> None:
        """Remove a stream from the manager.

        Args:
            request_id: The UUID of the stream to remove.
        """
        async with self._lock:
            self._streams.pop(request_id, None)

    def list_active_streams(self) -> t.List[t.Dict[str, t.Any]]:
        """List all active streams with their stats.

        Returns:
            A list of stream statistics dictionaries.
        """
        return [
            stream.get_stats()
            for stream in self._streams.values()
            if not stream.stream_finished
        ]

    async def cancel_all(self) -> None:
        """Cancel all active streams."""
        async with self._lock:
            for stream in self._streams.values():
                if not stream.stream_finished:
                    await stream.cancel()
            self._streams.clear()

    @property
    def active_count(self) -> int:
        """Number of active (non-finished) streams."""
        return sum(
            1 for s in self._streams.values() if not s.stream_finished
        )

    @property
    def total_count(self) -> int:
        """Total number of registered streams (including finished)."""
        return len(self._streams)

    def __repr__(self) -> str:
        """Return a string representation of the stream manager."""
        return (
            f"StreamManager(active={self.active_count}, "
            f"total={self.total_count})"
        )


# ---------------------------------------------------------------------------
# Stream event helpers
# ---------------------------------------------------------------------------


def create_chunk_event(chunk: InferenceChunk) -> StreamEvent:
    """Create a chunk event for the stream queue.

    Args:
        chunk: The inference chunk.

    Returns:
        A StreamEvent with type ``"chunk"``.
    """
    return StreamEvent(type="chunk", chunk=chunk)


def create_error_event(error: BaseException) -> StreamEvent:
    """Create an error event for the stream queue.

    Args:
        error: The exception that occurred.

    Returns:
        A StreamEvent with type ``"error"``.
    """
    return StreamEvent(type="error", error=error)


def create_done_event(final_data: t.Optional[JSONObject] = None) -> StreamEvent:
    """Create a done event for the stream queue.

    Args:
        final_data: Optional final response data.

    Returns:
        A StreamEvent with type ``"done"``.
    """
    return StreamEvent(type="done", final_data=final_data)


# ---------------------------------------------------------------------------
# Stream chunk parsing
# ---------------------------------------------------------------------------


def parse_stream_chunk(data: JSONObject) -> InferenceChunk:
    """Parse a stream message data payload into an InferenceChunk.

    The daemon sends stream chunks with the structure::

        {
            "type": "stream",
            "id": "<uuid>",
            "data": {
                "token": "...",
                "final": false,
                ...
            }
        }

    Args:
        data: The ``data`` field of a stream message.

    Returns:
        A parsed InferenceChunk.

    Raises:
        ValueError: If the data is malformed.
    """
    return InferenceChunk.from_dict(data)


# ---------------------------------------------------------------------------
# Accumulator for collecting stream results
# ---------------------------------------------------------------------------


class StreamAccumulator:
    """Accumulates streaming chunks into a complete response.

    This is useful when you want to collect the full output while also
    processing tokens as they arrive.

    Usage::

        accumulator = StreamAccumulator()
        async for chunk in client.infer_stream("model", "Hello"):
            accumulator.add(chunk)
            print(chunk.token, end="", flush=True)
        print(f"\\nFull text: {accumulator.text}")
    """

    def __init__(self) -> None:
        """Initialise the accumulator."""
        self._tokens: t.List[str] = []
        self._chunks: t.List[InferenceChunk] = []
        self._final_chunk: t.Optional[InferenceChunk] = None
        self._start_time: float = timestamp()

    def add(self, chunk: InferenceChunk) -> None:
        """Add a chunk to the accumulator.

        Args:
            chunk: The inference chunk to add.
        """
        self._chunks.append(chunk)
        if chunk.token:
            self._tokens.append(chunk.token)
        if chunk.final:
            self._final_chunk = chunk

    @property
    def text(self) -> str:
        """The accumulated text (all tokens concatenated)."""
        return "".join(self._tokens)

    @property
    def token_count(self) -> int:
        """Number of tokens accumulated."""
        return len(self._tokens)

    @property
    def finish_reason(self) -> t.Optional[str]:
        """The finish reason (if the stream has completed)."""
        if self._final_chunk is not None:
            return self._final_chunk.finish_reason
        return None

    @property
    def usage(self) -> t.Optional[TokenUsage]:
        """Token usage statistics (if available)."""
        if self._final_chunk is not None:
            return self._final_chunk.usage
        return None

    @property
    def elapsed(self) -> float:
        """Elapsed time since the accumulator was created."""
        return timestamp() - self._start_time

    def reset(self) -> None:
        """Reset the accumulator to its initial state."""
        self._tokens.clear()
        self._chunks.clear()
        self._final_chunk = None
        self._start_time = timestamp()

    def __repr__(self) -> str:
        """Return a string representation of the accumulator."""
        return (
            f"StreamAccumulator(tokens={self.token_count}, "
            f"finished={self._final_chunk is not None})"
        )


__all__: list[str] = [
    "StreamIterator",
    "StreamManager",
    "StreamAccumulator",
    "StreamEvent",
    "create_chunk_event",
    "create_error_event",
    "create_done_event",
    "parse_stream_chunk",
]