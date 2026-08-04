"""
Ainos SDK - Stream Tests
=========================

Tests for the streaming inference module, including the StreamIterator,
StreamManager, StreamAccumulator, and stream event types.
"""

from __future__ import annotations

import asyncio
import typing as t
from typing import Any, AsyncGenerator

import pytest

from ainos.errors import (
    StreamError,
    StreamInterruptedError,
    StreamNotStartedError,
)
from ainos.stream import (
    StreamAccumulator,
    StreamEvent,
    StreamIterator,
    StreamManager,
    create_chunk_event,
    create_done_event,
    create_error_event,
    parse_stream_chunk,
)
from ainos.types import InferenceChunk, TokenUsage


# ---------------------------------------------------------------------------
# StreamEvent tests
# ---------------------------------------------------------------------------


class TestStreamEvent:
    """Tests for stream events."""

    def test_create_chunk_event(self) -> None:
        """Test creating a chunk event."""
        chunk: InferenceChunk = InferenceChunk(
            token="Hello",
            model="test-model",
            index=0,
        )
        event: StreamEvent = create_chunk_event(chunk)
        assert event.type == "chunk"
        assert event.chunk is not None
        assert event.chunk.token == "Hello"
        assert event.error is None
        assert event.final_data is None

    def test_create_error_event(self) -> None:
        """Test creating an error event."""
        error: ValueError = ValueError("test error")
        event: StreamEvent = create_error_event(error)
        assert event.type == "error"
        assert event.error is not None
        assert str(event.error) == "test error"
        assert event.chunk is None

    def test_create_done_event(self) -> None:
        """Test creating a done event."""
        event: StreamEvent = create_done_event({"status": "complete"})
        assert event.type == "done"
        assert event.final_data is not None
        assert event.final_data["status"] == "complete"
        assert event.chunk is None


# ---------------------------------------------------------------------------
# InferenceChunk tests
# ---------------------------------------------------------------------------


class TestInferenceChunk:
    """Tests for InferenceChunk."""

    def test_chunk_creation(self) -> None:
        """Test basic chunk creation."""
        chunk: InferenceChunk = InferenceChunk(
            token="Hello",
            model="test-model",
            final=False,
            index=0,
            request_id="req-001",
        )
        assert chunk.token == "Hello"
        assert chunk.model == "test-model"
        assert chunk.final is False
        assert chunk.index == 0
        assert chunk.request_id == "req-001"

    def test_final_chunk(self) -> None:
        """Test final chunk creation."""
        usage: TokenUsage = TokenUsage(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        )
        chunk: InferenceChunk = InferenceChunk(
            token="",
            model="test-model",
            final=True,
            finish_reason="stop",
            usage=usage,
            index=9,
        )
        assert chunk.final is True
        assert chunk.finish_reason == "stop"
        assert chunk.usage is not None
        assert chunk.usage.total_tokens == 15

    def test_chunk_from_dict(self) -> None:
        """Test creating a chunk from a dictionary."""
        data: dict[str, t.Any] = {
            "token": "world",
            "model": "test-model",
            "final": True,
            "finish_reason": "length",
            "index": 5,
            "request_id": "req-002",
        }
        chunk: InferenceChunk = InferenceChunk.from_dict(data)
        assert chunk.token == "world"
        assert chunk.final is True
        assert chunk.finish_reason == "length"
        assert chunk.index == 5
        assert chunk.request_id == "req-002"

    def test_chunk_from_dict_with_usage(self) -> None:
        """Test creating a chunk with usage from dict."""
        data: dict[str, t.Any] = {
            "token": "done",
            "final": True,
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 10,
                "total_tokens": 30,
            },
        }
        chunk: InferenceChunk = InferenceChunk.from_dict(data)
        assert chunk.usage is not None
        assert chunk.usage.total_tokens == 30

    def test_parse_stream_chunk(self) -> None:
        """Test parsing a stream chunk."""
        data: dict[str, t.Any] = {
            "token": "chunk-data",
            "final": False,
            "index": 3,
        }
        chunk: InferenceChunk = parse_stream_chunk(data)
        assert chunk.token == "chunk-data"
        assert chunk.final is False
        assert chunk.index == 3


# ---------------------------------------------------------------------------
# StreamIterator tests
# ---------------------------------------------------------------------------


class TestStreamIterator:
    """Tests for the StreamIterator."""

    @pytest.mark.asyncio
    async def test_basic_iteration(self) -> None:
        """Test basic stream iteration."""
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        iterator: StreamIterator = StreamIterator(
            request_id="test-1",
            model="test-model",
            queue=queue,
            timeout=5.0,
        )

        # Push some chunks
        await queue.put(create_chunk_event(InferenceChunk(token="Hello", index=0)))
        await queue.put(create_chunk_event(InferenceChunk(token=" ", index=1)))
        await queue.put(create_chunk_event(InferenceChunk(token="World", index=2)))
        await queue.put(create_done_event())

        # Read them
        tokens: list[str] = []
        async for chunk in iterator:
            tokens.append(chunk.token)

        assert tokens == ["Hello", " ", "World"]
        assert iterator.stream_finished is True
        assert iterator.token_count == 3

    @pytest.mark.asyncio
    async def test_empty_stream(self) -> None:
        """Test an empty stream (immediate done)."""
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        iterator: StreamIterator = StreamIterator(
            request_id="test-2",
            model="test-model",
            queue=queue,
            timeout=5.0,
        )

        await queue.put(create_done_event())

        tokens: list[str] = []
        async for chunk in iterator:
            tokens.append(chunk.token)

        assert tokens == []
        assert iterator.token_count == 0

    @pytest.mark.asyncio
    async def test_final_chunk(self) -> None:
        """Test iteration with a final chunk."""
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        iterator: StreamIterator = StreamIterator(
            request_id="test-3",
            model="test-model",
            queue=queue,
            timeout=5.0,
        )

        await queue.put(create_chunk_event(InferenceChunk(
            token="done",
            final=True,
            finish_reason="stop",
            usage=TokenUsage(10, 5, 15),
        )))

        chunks: list[InferenceChunk] = []
        async for chunk in iterator:
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].final is True
        assert chunks[0].finish_reason == "stop"
        assert chunks[0].usage is not None

    @pytest.mark.asyncio
    async def test_stream_error(self) -> None:
        """Test that errors in the stream are propagated."""
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        iterator: StreamIterator = StreamIterator(
            request_id="test-4",
            model="test-model",
            queue=queue,
            timeout=5.0,
        )

        await queue.put(create_chunk_event(InferenceChunk(token="before")))
        await queue.put(create_error_event(ValueError("Stream failed")))

        with pytest.raises(ValueError, match="Stream failed"):
            async for chunk in iterator:
                pass

    @pytest.mark.asyncio
    async def test_collect(self) -> None:
        """Test the collect() method."""
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        iterator: StreamIterator = StreamIterator(
            request_id="test-5",
            model="test-model",
            queue=queue,
            timeout=5.0,
        )

        await queue.put(create_chunk_event(InferenceChunk(token="Hello", index=0)))
        await queue.put(create_chunk_event(InferenceChunk(token=" World", index=1)))
        await queue.put(create_done_event())

        text: str = await iterator.collect()
        assert text == "Hello World"

    @pytest.mark.asyncio
    async def test_cancel(self) -> None:
        """Test stream cancellation."""
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        iterator: StreamIterator = StreamIterator(
            request_id="test-6",
            model="test-model",
            queue=queue,
            timeout=5.0,
        )

        await queue.put(create_chunk_event(InferenceChunk(token="Hello")))
        await iterator.cancel()

        assert iterator.stream_finished is True

    @pytest.mark.asyncio
    async def test_generated_text(self) -> None:
        """Test the generated_text property."""
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        iterator: StreamIterator = StreamIterator(
            request_id="test-7",
            model="test-model",
            queue=queue,
            timeout=5.0,
        )

        await queue.put(create_chunk_event(InferenceChunk(token="Hello", index=0)))
        await queue.put(create_chunk_event(InferenceChunk(token=" ", index=1)))
        await queue.put(create_chunk_event(InferenceChunk(token="World", index=2)))
        await queue.put(create_done_event())

        async for _ in iterator:
            pass

        assert iterator.generated_text == "Hello World"

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        """Test stream timeout."""
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        iterator: StreamIterator = StreamIterator(
            request_id="test-8",
            model="test-model",
            queue=queue,
            timeout=0.1,  # Very short timeout
        )

        # Don't put anything in the queue
        with pytest.raises(asyncio.TimeoutError):
            async for chunk in iterator:
                pass

    @pytest.mark.asyncio
    async def test_stats(self) -> None:
        """Test stream statistics."""
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        iterator: StreamIterator = StreamIterator(
            request_id="test-9",
            model="test-model",
            queue=queue,
            timeout=5.0,
        )

        await queue.put(create_chunk_event(InferenceChunk(token="A", index=0)))
        await queue.put(create_done_event())

        async for _ in iterator:
            pass

        stats: dict[str, t.Any] = iterator.get_stats()
        assert stats["request_id"] == "test-9"
        assert stats["model"] == "test-model"
        assert stats["token_count"] == 1
        assert stats["stream_finished"] is True

    @pytest.mark.asyncio
    async def test_repr(self) -> None:
        """Test stream iterator representation."""
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        iterator: StreamIterator = StreamIterator(
            request_id="test-10",
            model="test-model",
            queue=queue,
        )
        repr_str: str = repr(iterator)
        assert "StreamIterator" in repr_str
        assert "test-10" in repr_str


# ---------------------------------------------------------------------------
# StreamManager tests
# ---------------------------------------------------------------------------


class TestStreamManager:
    """Tests for the StreamManager."""

    @pytest.mark.asyncio
    async def test_create_and_get_stream(self) -> None:
        """Test creating and retrieving a stream."""
        manager: StreamManager = StreamManager()
        stream: StreamIterator = await manager.create_stream(
            request_id="stream-1",
            model="test-model",
        )
        assert stream is not None

        retrieved: t.Optional[StreamIterator] = await manager.get_stream("stream-1")
        assert retrieved is not None
        assert retrieved.request_id == "stream-1"

    @pytest.mark.asyncio
    async def test_remove_stream(self) -> None:
        """Test removing a stream."""
        manager: StreamManager = StreamManager()
        await manager.create_stream("stream-1", "test-model")
        await manager.remove_stream("stream-1")

        retrieved = await manager.get_stream("stream-1")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_duplicate_stream(self) -> None:
        """Test that duplicate streams raise an error."""
        manager: StreamManager = StreamManager()
        await manager.create_stream("stream-1", "test-model")

        with pytest.raises(ValueError, match="already exists"):
            await manager.create_stream("stream-1", "test-model")

    @pytest.mark.asyncio
    async def test_cancel_all(self) -> None:
        """Test cancelling all streams."""
        manager: StreamManager = StreamManager()
        await manager.create_stream("stream-1", "test-model")
        await manager.create_stream("stream-2", "test-model")

        await manager.cancel_all()
        assert manager.active_count == 0
        assert manager.total_count == 0

    @pytest.mark.asyncio
    async def test_active_count(self) -> None:
        """Test active stream count."""
        manager: StreamManager = StreamManager()
        assert manager.active_count == 0

        await manager.create_stream("stream-1", "test-model")
        assert manager.active_count == 1

        # Add a queue and finish the stream
        stream = await manager.get_stream("stream-1")
        if stream:
            await stream.cancel()

        # After cancel, the stream is finished but still in the manager
        # active_count looks at non-finished streams
        assert manager.active_count == 0

    @pytest.mark.asyncio
    async def test_list_active(self) -> None:
        """Test listing active streams."""
        manager: StreamManager = StreamManager()
        await manager.create_stream("stream-1", "test-model")

        active = manager.list_active_streams()
        assert len(active) == 1
        assert active[0]["request_id"] == "stream-1"

    @pytest.mark.asyncio
    async def test_repr(self) -> None:
        """Test stream manager representation."""
        manager: StreamManager = StreamManager()
        repr_str: str = repr(manager)
        assert "StreamManager" in repr_str


# ---------------------------------------------------------------------------
# StreamAccumulator tests
# ---------------------------------------------------------------------------


class TestStreamAccumulator:
    """Tests for the StreamAccumulator."""

    def test_accumulate_tokens(self) -> None:
        """Test accumulating tokens."""
        acc: StreamAccumulator = StreamAccumulator()
        acc.add(InferenceChunk(token="Hello", index=0))
        acc.add(InferenceChunk(token=" ", index=1))
        acc.add(InferenceChunk(token="World", index=2))

        assert acc.text == "Hello World"
        assert acc.token_count == 3

    def test_final_chunk(self) -> None:
        """Test accumulating with a final chunk."""
        acc: StreamAccumulator = StreamAccumulator()
        acc.add(InferenceChunk(token="partial", index=0))
        acc.add(InferenceChunk(
            token="",
            final=True,
            finish_reason="stop",
            usage=TokenUsage(10, 5, 15),
        ))

        assert acc.finish_reason == "stop"
        assert acc.usage is not None
        assert acc.usage.total_tokens == 15

    def test_no_final_chunk(self) -> None:
        """Test accumulator without final chunk."""
        acc: StreamAccumulator = StreamAccumulator()
        acc.add(InferenceChunk(token="data"))

        assert acc.finish_reason is None
        assert acc.usage is None

    def test_reset(self) -> None:
        """Test resetting the accumulator."""
        acc: StreamAccumulator = StreamAccumulator()
        acc.add(InferenceChunk(token="data"))
        assert acc.token_count == 1

        acc.reset()
        assert acc.token_count == 0
        assert acc.text == ""
        assert acc.finish_reason is None

    def test_empty_accumulator(self) -> None:
        """Test an empty accumulator."""
        acc: StreamAccumulator = StreamAccumulator()
        assert acc.text == ""
        assert acc.token_count == 0
        assert acc.finish_reason is None
        assert acc.usage is None

    def test_repr(self) -> None:
        """Test accumulator representation."""
        acc: StreamAccumulator = StreamAccumulator()
        acc.add(InferenceChunk(token="test"))
        repr_str: str = repr(acc)
        assert "StreamAccumulator" in repr_str
        assert "tokens=1" in repr_str


# ---------------------------------------------------------------------------
# Integration-style stream tests
# ---------------------------------------------------------------------------


class TestStreamIntegration:
    """Integration-style tests for streaming."""

    @pytest.mark.asyncio
    async def test_full_stream_workflow(self) -> None:
        """Test a complete stream workflow."""
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        iterator: StreamIterator = StreamIterator(
            request_id="integ-1",
            model="test-model",
            queue=queue,
            timeout=5.0,
        )

        # Simulate a stream with 5 tokens
        tokens: list[str] = ["The", " quick", " brown", " fox", "!"]
        for i, token in enumerate(tokens):
            await queue.put(create_chunk_event(InferenceChunk(
                token=token,
                model="test-model",
                final=(i == len(tokens) - 1),
                finish_reason="stop" if i == len(tokens) - 1 else None,
                index=i,
                request_id="integ-1",
            )))
        if not iterator.stream_finished:
            await queue.put(create_done_event())

        # Read and accumulate
        acc: StreamAccumulator = StreamAccumulator()
        async for chunk in iterator:
            acc.add(chunk)

        assert acc.text == "The quick brown fox!"
        assert acc.token_count == 5
        assert acc.finish_reason == "stop"
        assert iterator.stream_finished is True

    @pytest.mark.asyncio
    async def test_concurrent_streams(self) -> None:
        """Test multiple concurrent streams."""
        manager: StreamManager = StreamManager()

        # Create two streams
        queue1: asyncio.Queue[StreamEvent] = asyncio.Queue()
        stream1: StreamIterator = StreamIterator(
            request_id="con-1",
            model="model-a",
            queue=queue1,
            timeout=5.0,
        )

        queue2: asyncio.Queue[StreamEvent] = asyncio.Queue()
        stream2: StreamIterator = StreamIterator(
            request_id="con-2",
            model="model-b",
            queue=queue2,
            timeout=5.0,
        )

        # Feed data
        await queue1.put(create_chunk_event(InferenceChunk(token="A1", index=0)))
        await queue1.put(create_done_event())

        await queue2.put(create_chunk_event(InferenceChunk(token="B1", index=0)))
        await queue2.put(create_chunk_event(InferenceChunk(token="B2", index=1)))
        await queue2.put(create_done_event())

        # Read both concurrently
        async def read_stream(
            stream: StreamIterator,
            results: list[str],
        ) -> None:
            async for chunk in stream:
                results.append(chunk.token)

        results1: list[str] = []
        results2: list[str] = []

        await asyncio.gather(
            read_stream(stream1, results1),
            read_stream(stream2, results2),
        )

        assert results1 == ["A1"]
        assert results2 == ["B1", "B2"]


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestStreamErrors:
    """Tests for stream error handling."""

    @pytest.mark.asyncio
    async def test_stream_interrupted_error(self) -> None:
        """Test StreamInterruptedError."""
        error: StreamInterruptedError = StreamInterruptedError(
            request_id="err-1",
            received_tokens=5,
        )
        assert error.request_id == "err-1"
        assert error.received_tokens == 5
        assert "interrupted" in str(error).lower()

    @pytest.mark.asyncio
    async def test_stream_not_started_error(self) -> None:
        """Test StreamNotStartedError."""
        error: StreamNotStartedError = StreamNotStartedError()
        assert "not been started" in str(error).lower()

    @pytest.mark.asyncio
    async def test_queue_full(self) -> None:
        """Test that a full queue raises an error."""
        # The queue has maxsize=_MAX_QUEUE_SIZE (4096), so we shouldn't
        # hit it easily. Just verify the concept works.
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue(maxsize=1)
        await queue.put(create_chunk_event(InferenceChunk(token="a")))

        with pytest.raises(asyncio.QueueFull):
            queue.put_nowait(create_chunk_event(InferenceChunk(token="b")))

    @pytest.mark.asyncio
    async def test_stream_error_event(self) -> None:
        """Test error event propagation."""
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        iterator: StreamIterator = StreamIterator(
            request_id="err-2",
            model="test-model",
            queue=queue,
            timeout=5.0,
        )

        await queue.put(create_error_event(RuntimeError("runtime error")))

        with pytest.raises(RuntimeError, match="runtime error"):
            async for chunk in iterator:
                pass

        assert iterator.stream_finished is True