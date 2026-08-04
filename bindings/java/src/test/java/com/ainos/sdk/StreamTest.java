package com.ainos.sdk;

import com.ainos.sdk.models.InferenceChunk;
import com.ainos.sdk.models.InferenceRequest;
import com.ainos.sdk.stream.InferenceStream;
import com.ainos.sdk.stream.StreamReader;
import com.ainos.sdk.stream.StreamSubscriber;
import com.ainos.sdk.transport.JsonCodec;
import com.ainos.sdk.transport.TcpTransport;
import org.junit.jupiter.api.Test;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for streaming inference support.
 */
public class StreamTest {

    private final JsonCodec codec = new JsonCodec();

    // -----------------------------------------------------------------------
    // InferenceChunk tests
    // -----------------------------------------------------------------------

    @Test
    void testChunkCreation() {
        InferenceChunk chunk = new InferenceChunk("Hello", false);
        assertEquals("Hello", chunk.getChunk());
        assertFalse(chunk.isDone());
    }

    @Test
    void testFinalChunk() {
        InferenceChunk chunk = InferenceChunk.finalChunk("World");
        assertEquals("World", chunk.getChunk());
        assertTrue(chunk.isDone());
    }

    @Test
    void testOfFactory() {
        InferenceChunk chunk = InferenceChunk.of("test");
        assertEquals("test", chunk.getChunk());
        assertFalse(chunk.isDone());
    }

    @Test
    void testChunkEquality() {
        InferenceChunk c1 = new InferenceChunk("hello", false);
        InferenceChunk c2 = new InferenceChunk("hello", false);
        assertEquals(c1, c2);
        assertEquals(c1.hashCode(), c2.hashCode());
    }

    @Test
    void testChunkInequality() {
        InferenceChunk c1 = new InferenceChunk("hello", false);
        InferenceChunk c2 = new InferenceChunk("hello", true);
        assertNotEquals(c1, c2);
    }

    @Test
    void testChunkToString() {
        InferenceChunk chunk = new InferenceChunk("test", true);
        String str = chunk.toString();
        assertTrue(str.contains("test"));
        assertTrue(str.contains("done=true"));
    }

    // -----------------------------------------------------------------------
    // StreamReader tests
    // -----------------------------------------------------------------------

    @Test
    void testStreamReaderReadsChunks() throws Exception {
        String[] lines = {
                "{\"type\":\"InferenceChunk\",\"chunk\":\"Hello\",\"done\":false}",
                "{\"type\":\"InferenceChunk\",\"chunk\":\" World\",\"done\":false}",
                "{\"type\":\"InferenceChunk\",\"chunk\":\"!\",\"done\":true}"
        };

        MockResponseReader mockReader = new MockResponseReader(lines);
        StreamReader streamReader = new StreamReader(mockReader, codec);

        InferenceChunk c1 = streamReader.readChunk();
        assertEquals("Hello", c1.getChunk());
        assertFalse(c1.isDone());

        InferenceChunk c2 = streamReader.readChunk();
        assertEquals(" World", c2.getChunk());
        assertFalse(c2.isDone());

        InferenceChunk c3 = streamReader.readChunk();
        assertEquals("!", c3.getChunk());
        assertTrue(c3.isDone());

        assertNull(streamReader.readChunk());
    }

    @Test
    void testStreamReaderError() {
        String[] lines = {
                "{\"type\":\"Error\",\"code\":-1,\"message\":\"Model error\"}"
        };

        MockResponseReader mockReader = new MockResponseReader(lines);
        StreamReader streamReader = new StreamReader(mockReader, codec);

        assertThrows(com.ainos.sdk.models.AinosInferenceException.class,
                () -> streamReader.readChunk());
    }

    @Test
    void testStreamReaderInferenceResponseAsChunk() throws Exception {
        // Non-streaming fallback: InferenceResponse should be treated as a single final chunk
        String[] lines = {
                "{\"type\":\"InferenceResponse\",\"output\":\"Full response\",\"tokens_generated\":5,\"inference_ms\":100,\"source\":\"local\"}"
        };

        MockResponseReader mockReader = new MockResponseReader(lines);
        StreamReader streamReader = new StreamReader(mockReader, codec);

        InferenceChunk chunk = streamReader.readChunk();
        assertEquals("Full response", chunk.getChunk());
        assertTrue(chunk.isDone());
    }

    @Test
    void testStreamReaderEmpty() throws Exception {
        String[] lines = {};
        MockResponseReader mockReader = new MockResponseReader(lines);
        StreamReader streamReader = new StreamReader(mockReader, codec);

        assertNull(streamReader.readChunk());
    }

    // -----------------------------------------------------------------------
    // InferenceStream tests
    // -----------------------------------------------------------------------

    @Test
    void testInferenceStreamIteration() throws Exception {
        String[] lines = {
                "{\"type\":\"InferenceChunk\",\"chunk\":\"A\",\"done\":false}",
                "{\"type\":\"InferenceChunk\",\"chunk\":\"B\",\"done\":false}",
                "{\"type\":\"InferenceChunk\",\"chunk\":\"C\",\"done\":true}"
        };

        MockResponseReader mockReader = new MockResponseReader(lines);
        StreamReader streamReader = new StreamReader(mockReader, codec);

        try (InferenceStream stream = new InferenceStream(streamReader)) {
            List<InferenceChunk> chunks = new ArrayList<>();
            for (InferenceChunk chunk : stream) {
                chunks.add(chunk);
            }
            assertEquals(3, chunks.size());
            assertEquals("A", chunks.get(0).getChunk());
            assertEquals("B", chunks.get(1).getChunk());
            assertEquals("C", chunks.get(2).getChunk());
            assertTrue(chunks.get(2).isDone());
        }
    }

    @Test
    void testInferenceStreamNext() throws Exception {
        String[] lines = {
                "{\"type\":\"InferenceChunk\",\"chunk\":\"chunk1\",\"done\":false}",
                "{\"type\":\"InferenceChunk\",\"chunk\":\"chunk2\",\"done\":true}"
        };

        MockResponseReader mockReader = new MockResponseReader(lines);
        StreamReader streamReader = new StreamReader(mockReader, codec);

        try (InferenceStream stream = new InferenceStream(streamReader)) {
            InferenceChunk c1 = stream.next();
            assertEquals("chunk1", c1.getChunk());
            assertFalse(c1.isDone());

            InferenceChunk c2 = stream.next();
            assertEquals("chunk2", c2.getChunk());
            assertTrue(c2.isDone());

            assertNull(stream.next());
        }
    }

    @Test
    void testInferenceStreamClose() throws Exception {
        String[] lines = {"{\"type\":\"InferenceChunk\",\"chunk\":\"test\",\"done\":false}"};
        MockResponseReader mockReader = new MockResponseReader(lines);
        StreamReader streamReader = new StreamReader(mockReader, codec);

        InferenceStream stream = new InferenceStream(streamReader);
        stream.close();
        assertTrue(stream.isClosed());
        assertNull(stream.next());
    }

    @Test
    void testInferenceStreamCannotReiterate() throws Exception {
        String[] lines = {"{\"type\":\"InferenceChunk\",\"chunk\":\"test\",\"done\":true}"};
        MockResponseReader mockReader = new MockResponseReader(lines);
        StreamReader streamReader = new StreamReader(mockReader, codec);

        InferenceStream stream = new InferenceStream(streamReader);

        // First iteration should work
        for (InferenceChunk ignored : stream) {
            // consume
        }

        // Second iteration should fail
        assertThrows(IllegalStateException.class, () -> {
            for (InferenceChunk ignored : stream) {
                // should not reach here
            }
        });

        stream.close();
    }

    // -----------------------------------------------------------------------
    // StreamSubscriber tests
    // -----------------------------------------------------------------------

    @Test
    void testStreamSubscriberBuffersChunks() throws Exception {
        StreamSubscriber subscriber = new StreamSubscriber();

        subscriber.onStart();
        subscriber.onChunk(new InferenceChunk("chunk1", false));
        subscriber.onChunk(new InferenceChunk("chunk2", false));
        subscriber.onChunk(new InferenceChunk("chunk3", true));
        subscriber.onComplete();

        // Poll chunks
        InferenceChunk c1 = subscriber.poll(100, TimeUnit.MILLISECONDS);
        assertEquals("chunk1", c1.getChunk());

        InferenceChunk c2 = subscriber.poll(100, TimeUnit.MILLISECONDS);
        assertEquals("chunk2", c2.getChunk());

        InferenceChunk c3 = subscriber.poll(100, TimeUnit.MILLISECONDS);
        assertEquals("chunk3", c3.getChunk());

        // After completion, should return null once queue is drained
        InferenceChunk c4 = subscriber.poll(100, TimeUnit.MILLISECONDS);
        assertNull(c4);
    }

    @Test
    void testStreamSubscriberError() {
        StreamSubscriber subscriber = new StreamSubscriber();
        subscriber.onError(new RuntimeException("test error"));

        assertTrue(subscriber.isCompleted());
        assertNotNull(subscriber.getError());
        assertThrows(RuntimeException.class, () -> subscriber.take());
    }

    @Test
    void testStreamSubscriberBufferedCount() throws Exception {
        StreamSubscriber subscriber = new StreamSubscriber(10);
        assertEquals(0, subscriber.bufferedCount());

        subscriber.onChunk(new InferenceChunk("a", false));
        assertEquals(1, subscriber.bufferedCount());

        subscriber.onChunk(new InferenceChunk("b", false));
        assertEquals(2, subscriber.bufferedCount());

        subscriber.poll(100, TimeUnit.MILLISECONDS);
        assertEquals(1, subscriber.bufferedCount());
    }

    @Test
    void testStreamSubscriberDrain() throws Exception {
        StreamSubscriber subscriber = new StreamSubscriber();
        subscriber.onChunk(new InferenceChunk("a", false));
        subscriber.onChunk(new InferenceChunk("b", false));
        subscriber.onComplete();

        InferenceChunk[] drained = subscriber.drain();
        assertEquals(2, drained.length);
    }

    // -----------------------------------------------------------------------
    // MockResponseReader
    // -----------------------------------------------------------------------

    /**
     * A mock {@link TcpTransport.ResponseReader} that returns pre-defined lines.
     */
    static class MockResponseReader implements TcpTransport.ResponseReader {

        private final com.google.gson.Gson gson = new com.google.gson.Gson();
        private final java.util.Iterator<String> iterator;
        private volatile boolean closed = false;

        MockResponseReader(String... lines) {
            this.iterator = Arrays.asList(lines).iterator();
        }

        @Override
        @SuppressWarnings("unchecked")
        public Map<String, Object> readLine() {
            if (closed || !iterator.hasNext()) {
                return null;
            }
            String line = iterator.next();
            return gson.fromJson(line, Map.class);
        }

        @Override
        public boolean hasMore() {
            return !closed && iterator.hasNext();
        }

        @Override
        public void close() {
            closed = true;
        }
    }
}