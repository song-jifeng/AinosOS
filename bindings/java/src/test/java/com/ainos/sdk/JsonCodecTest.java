package com.ainos.sdk;

import com.ainos.sdk.transport.JsonCodec;
import com.google.gson.Gson;
import org.junit.jupiter.api.Test;

import java.util.*;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for {@link JsonCodec} - JSON serialization and protocol helpers.
 */
public class JsonCodecTest {

    private final JsonCodec codec = new JsonCodec();

    // -----------------------------------------------------------------------
    // Basic serialization
    // -----------------------------------------------------------------------

    @Test
    void testToJson() {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("type", "Status");
        data.put("value", 42);

        String json = codec.toJson(data);
        assertTrue(json.contains("\"type\":\"Status\""));
        assertTrue(json.contains("\"value\":42"));
    }

    @Test
    void testFromJson() {
        String json = "{\"type\":\"Status\",\"value\":42}";
        Map<String, Object> result = codec.fromJson(json);

        assertEquals("Status", result.get("type"));
        assertEquals(42.0, ((Number) result.get("value")).doubleValue());
    }

    @Test
    void testRoundTrip() {
        Map<String, Object> original = new LinkedHashMap<>();
        original.put("type", "Inference");
        original.put("model", "test-model");
        original.put("prompt", "Hello");
        original.put("temperature", 0.7);

        String json = codec.toJson(original);
        Map<String, Object> result = codec.fromJson(json);

        assertEquals(original.get("type"), result.get("type"));
        assertEquals(original.get("model"), result.get("model"));
        assertEquals(original.get("prompt"), result.get("prompt"));
    }

    // -----------------------------------------------------------------------
    // Build request
    // -----------------------------------------------------------------------

    @Test
    void testBuildRequestWithType() {
        Map<String, Object> request = codec.buildRequest("Status");
        assertEquals("Status", request.get("type"));
        assertEquals(1, request.size());
    }

    @Test
    void testBuildRequestWithParams() {
        Map<String, Object> params = new LinkedHashMap<>();
        params.put("model", "phi-3");
        params.put("prompt", "Hello");

        Map<String, Object> request = codec.buildRequest("Inference", params);
        assertEquals("Inference", request.get("type"));
        assertEquals("phi-3", request.get("model"));
        assertEquals("Hello", request.get("prompt"));
    }

    // -----------------------------------------------------------------------
    // Type extraction
    // -----------------------------------------------------------------------

    @Test
    void testGetType() {
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("type", "InferenceResponse");
        assertEquals("InferenceResponse", JsonCodec.getType(response));
    }

    @Test
    void testGetTypeMissing() {
        Map<String, Object> response = new LinkedHashMap<>();
        assertNull(JsonCodec.getType(response));
    }

    // -----------------------------------------------------------------------
    // Field extraction
    // -----------------------------------------------------------------------

    @Test
    void testGetString() {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("name", "hello");
        assertEquals("hello", JsonCodec.getString(data, "name"));
        assertNull(JsonCodec.getString(data, "missing"));
        assertEquals("default", JsonCodec.getString(data, "missing", "default"));
    }

    @Test
    void testGetInt() {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("count", 42);
        assertEquals(42, JsonCodec.getInt(data, "count", 0));
        assertEquals(0, JsonCodec.getInt(data, "missing", 0));
    }

    @Test
    void testGetLong() {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("big", 10000000000L);
        assertEquals(10000000000L, JsonCodec.getLong(data, "big", 0));
        assertEquals(0L, JsonCodec.getLong(data, "missing", 0));
    }

    @Test
    void testGetBoolean() {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("flag", true);
        assertTrue(JsonCodec.getBoolean(data, "flag", false));
        assertFalse(JsonCodec.getBoolean(data, "missing", false));
    }

    @Test
    void testGetBooleanDefaultTrue() {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("flag", false);
        assertFalse(JsonCodec.getBoolean(data, "flag", true));
    }

    // -----------------------------------------------------------------------
    // List extraction
    // -----------------------------------------------------------------------

    @Test
    void testGetList() {
        Map<String, Object> data = new LinkedHashMap<>();
        List<String> items = Arrays.asList("a", "b", "c");
        data.put("items", items);

        List<String> result = JsonCodec.getList(data, "items");
        assertEquals(3, result.size());
        assertEquals("a", result.get(0));
    }

    @Test
    @SuppressWarnings("unchecked")
    void testGetListOfMaps() {
        Map<String, Object> data = new LinkedHashMap<>();
        List<Map<String, Object>> items = new ArrayList<>();
        Map<String, Object> item1 = new LinkedHashMap<>();
        item1.put("id", "m1");
        items.add(item1);
        data.put("models", items);

        List<Map<String, Object>> result = JsonCodec.getList(data, "models");
        assertEquals(1, result.size());
        assertEquals("m1", result.get(0).get("id"));
    }

    @Test
    void testGetListMissing() {
        Map<String, Object> data = new LinkedHashMap<>();
        List<String> result = JsonCodec.getList(data, "missing");
        assertTrue(result.isEmpty());
    }

    // -----------------------------------------------------------------------
    // Map extraction
    // -----------------------------------------------------------------------

    @Test
    void testGetMap() {
        Map<String, Object> data = new LinkedHashMap<>();
        Map<String, Object> nested = new LinkedHashMap<>();
        nested.put("key", "value");
        data.put("info", nested);

        Map<String, Object> result = JsonCodec.getMap(data, "info");
        assertEquals("value", result.get("key"));
    }

    @Test
    void testGetMapMissing() {
        Map<String, Object> data = new LinkedHashMap<>();
        Map<String, Object> result = JsonCodec.getMap(data, "missing");
        assertTrue(result.isEmpty());
    }

    // -----------------------------------------------------------------------
    // Error detection
    // -----------------------------------------------------------------------

    @Test
    void testIsError() {
        Map<String, Object> error = new LinkedHashMap<>();
        error.put("type", "Error");
        assertTrue(JsonCodec.isError(error));

        Map<String, Object> ok = new LinkedHashMap<>();
        ok.put("type", "InferenceResponse");
        assertFalse(JsonCodec.isError(ok));
    }

    @Test
    void testGetErrorCode() {
        Map<String, Object> error = new LinkedHashMap<>();
        error.put("code", 401);
        assertEquals(401, JsonCodec.getErrorCode(error));
    }

    @Test
    void testGetErrorCodeMissing() {
        Map<String, Object> error = new LinkedHashMap<>();
        assertEquals(-1, JsonCodec.getErrorCode(error));
    }

    @Test
    void testGetErrorMessage() {
        Map<String, Object> error = new LinkedHashMap<>();
        error.put("message", "Not found");
        assertEquals("Not found", JsonCodec.getErrorMessage(error));
    }

    // -----------------------------------------------------------------------
    // Custom Gson instance
    // -----------------------------------------------------------------------

    @Test
    void testCustomGson() {
        Gson custom = new Gson();
        JsonCodec customCodec = new JsonCodec(custom);

        String json = customCodec.toJson(Collections.singletonMap("key", "value"));
        assertTrue(json.contains("value"));
    }

    // -----------------------------------------------------------------------
    // Edge cases
    // -----------------------------------------------------------------------

    @Test
    void testNullInput() {
        assertThrows(NullPointerException.class, () -> new JsonCodec(null));
    }

    @Test
    void testJsonNull() {
        Map<String, Object> result = codec.fromJson("null");
        assertNull(result);
    }

    @Test
    void testJsonEmptyObject() {
        Map<String, Object> result = codec.fromJson("{}");
        assertNotNull(result);
        assertTrue(result.isEmpty());
    }

    @Test
    void testJsonWithNestedObject() {
        String json = "{\"type\":\"ModelLoadResponse\",\"model_info\":{\"id\":\"m1\",\"loaded\":true}}";
        Map<String, Object> result = codec.fromJson(json);

        assertEquals("ModelLoadResponse", result.get("type"));
        assertTrue(result.containsKey("model_info"));

        @SuppressWarnings("unchecked")
        Map<String, Object> info = (Map<String, Object>) result.get("model_info");
        assertEquals("m1", info.get("id"));
    }

    @Test
    void testJsonArray() {
        String json = "{\"models\":[{\"id\":\"m1\"},{\"id\":\"m2\"}]}";
        Map<String, Object> result = codec.fromJson(json);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> models = (List<Map<String, Object>>) result.get("models");
        assertEquals(2, models.size());
        assertEquals("m1", models.get(0).get("id"));
    }

    @Test
    void testNumericTypes() {
        // Gson deserializes all numbers as Double by default when using Map
        String json = "{\"int_val\":42,\"long_val\":9999999999,\"float_val\":3.14}";
        Map<String, Object> result = codec.fromJson(json);

        assertTrue(result.get("int_val") instanceof Number);
        assertEquals(42, ((Number) result.get("int_val")).intValue());
        assertEquals(9999999999L, ((Number) result.get("long_val")).longValue());
        assertEquals(3.14, ((Number) result.get("float_val")).doubleValue(), 0.001);
    }
}