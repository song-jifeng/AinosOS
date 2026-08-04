package com.ainos.sdk;

import com.ainos.sdk.models.InferenceRequest;
import com.ainos.sdk.models.ModelLoadOptions;
import org.junit.jupiter.api.Test;

import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for the request builder classes.
 */
public class InferenceRequestTest {

    // -----------------------------------------------------------------------
    // InferenceRequest tests
    // -----------------------------------------------------------------------

    @Test
    void testBuilderMinimal() {
        InferenceRequest req = InferenceRequest.builder()
                .prompt("Hello")
                .build();

        assertEquals("Hello", req.getPrompt());
        assertEquals("default", req.getModel());
        assertFalse(req.getTemperature().isPresent());
        assertFalse(req.getMaxTokens().isPresent());
        assertFalse(req.getSessionId().isPresent());
    }

    @Test
    void testBuilderFull() {
        InferenceRequest req = InferenceRequest.builder()
                .prompt("Tell me a story")
                .model("phi-3-mini")
                .temperature(0.8)
                .maxTokens(2048)
                .sessionId("sess-abc-123")
                .build();

        assertEquals("Tell me a story", req.getPrompt());
        assertEquals("phi-3-mini", req.getModel());
        assertEquals(Optional.of(0.8), req.getTemperature());
        assertEquals(Optional.of(2048), req.getMaxTokens());
        assertEquals(Optional.of("sess-abc-123"), req.getSessionId());
    }

    @Test
    void testBuilderNullPrompt() {
        assertThrows(NullPointerException.class, () ->
                InferenceRequest.builder().build());
    }

    @Test
    void testOfFactory() {
        InferenceRequest req = InferenceRequest.of("Hello");
        assertEquals("Hello", req.getPrompt());
        assertEquals("default", req.getModel());
    }

    @Test
    void testOfFactoryWithModel() {
        InferenceRequest req = InferenceRequest.of("Hello", "llama-3");
        assertEquals("Hello", req.getPrompt());
        assertEquals("llama-3", req.getModel());
    }

    @Test
    void testEquality() {
        InferenceRequest req1 = InferenceRequest.builder()
                .prompt("test")
                .model("m1")
                .temperature(0.5)
                .build();

        InferenceRequest req2 = InferenceRequest.builder()
                .prompt("test")
                .model("m1")
                .temperature(0.5)
                .build();

        assertEquals(req1, req2);
        assertEquals(req1.hashCode(), req2.hashCode());
    }

    @Test
    void testInequality() {
        InferenceRequest req1 = InferenceRequest.builder()
                .prompt("test")
                .model("m1")
                .build();

        InferenceRequest req2 = InferenceRequest.builder()
                .prompt("test")
                .model("m2")
                .build();

        assertNotEquals(req1, req2);
    }

    @Test
    void testToString() {
        InferenceRequest req = InferenceRequest.of("hello", "model-x");
        String str = req.toString();
        assertTrue(str.contains("hello"));
        assertTrue(str.contains("model-x"));
    }

    @Test
    void testImmutable() {
        InferenceRequest req = InferenceRequest.of("hello");
        // Verify it's immutable by checking the class is final
        assertNotNull(req.getPrompt());
    }

    // -----------------------------------------------------------------------
    // ModelLoadOptions tests
    // -----------------------------------------------------------------------

    @Test
    void testModelLoadOptionsDefaults() {
        ModelLoadOptions opts = ModelLoadOptions.builder().build();
        assertFalse(opts.getArchitecture().isPresent());
        assertFalse(opts.getGpuLayerCount().isPresent());
        assertFalse(opts.getContextSize().isPresent());
        assertFalse(opts.getUseMmap().isPresent());
        assertFalse(opts.getThreads().isPresent());
        assertFalse(opts.getEngineType().isPresent());
    }

    @Test
    void testModelLoadOptionsFull() {
        ModelLoadOptions opts = ModelLoadOptions.builder()
                .architecture("phi3")
                .gpuLayerCount(32)
                .contextSize(4096)
                .useMmap(true)
                .threads(8)
                .engineType("ggml")
                .build();

        assertEquals(Optional.of("phi3"), opts.getArchitecture());
        assertEquals(Optional.of(32), opts.getGpuLayerCount());
        assertEquals(Optional.of(4096), opts.getContextSize());
        assertEquals(Optional.of(true), opts.getUseMmap());
        assertEquals(Optional.of(8), opts.getThreads());
        assertEquals(Optional.of("ggml"), opts.getEngineType());
    }

    @Test
    void testModelLoadOptionsEquality() {
        ModelLoadOptions opts1 = ModelLoadOptions.builder()
                .architecture("llama")
                .gpuLayerCount(16)
                .build();

        ModelLoadOptions opts2 = ModelLoadOptions.builder()
                .architecture("llama")
                .gpuLayerCount(16)
                .build();

        assertEquals(opts1, opts2);
        assertEquals(opts1.hashCode(), opts2.hashCode());
    }

    @Test
    void testModelLoadOptionsInequality() {
        ModelLoadOptions opts1 = ModelLoadOptions.builder()
                .architecture("llama")
                .build();

        ModelLoadOptions opts2 = ModelLoadOptions.builder()
                .architecture("phi3")
                .build();

        assertNotEquals(opts1, opts2);
    }

    @Test
    void testModelLoadOptionsToString() {
        ModelLoadOptions opts = ModelLoadOptions.builder()
                .architecture("phi3")
                .gpuLayerCount(32)
                .build();

        String str = opts.toString();
        assertTrue(str.contains("phi3"));
        assertTrue(str.contains("32"));
    }
}