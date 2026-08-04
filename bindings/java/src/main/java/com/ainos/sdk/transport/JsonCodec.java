package com.ainos.sdk.transport;

import com.ainos.sdk.models.AinosConnectionException;
import com.ainos.sdk.models.AinosTimeoutException;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.reflect.TypeToken;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Type;
import java.util.*;

/**
 * JSON serialization and deserialization utilities for the Ainos NDJSON protocol.
 * <p>
 * Provides convenience methods for converting between Java objects and
 * JSON strings, as well as request/response map construction specific
 * to the Ainos IPC protocol.
 * <p>
 * This class is thread-safe.
 */
public final class JsonCodec {

    private static final Logger log = LoggerFactory.getLogger(JsonCodec.class);

    private static final Type MAP_TYPE = new TypeToken<Map<String, Object>>() {}.getType();
    private static final Type LIST_MAP_TYPE = new TypeToken<List<Map<String, Object>>>() {}.getType();

    private final Gson gson;

    /**
     * Constructs a new JsonCodec with default configuration.
     */
    public JsonCodec() {
        this.gson = new GsonBuilder()
                .setLenient()
                .create();
    }

    /**
     * Constructs a new JsonCodec with a custom Gson instance.
     *
     * @param gson the Gson instance to use
     */
    public JsonCodec(Gson gson) {
        this.gson = Objects.requireNonNull(gson, "gson must not be null");
    }

    // -----------------------------------------------------------------------
    // Serialization
    // -----------------------------------------------------------------------

    /**
     * Serializes an object to a JSON string.
     *
     * @param obj the object to serialize
     * @return the JSON string
     */
    public String toJson(Object obj) {
        return gson.toJson(obj);
    }

    /**
     * Deserializes a JSON string to a map.
     *
     * @param json the JSON string
     * @return the deserialized map
     * @throws com.google.gson.JsonSyntaxException if the JSON is invalid
     */
    public Map<String, Object> fromJson(String json) {
        return gson.fromJson(json, MAP_TYPE);
    }

    /**
     * Deserializes a JSON string to the specified type.
     *
     * @param json the JSON string
     * @param type the target type token
     * @param <T>  the target type
     * @return the deserialized object
     */
    @SuppressWarnings("unchecked")
    public <T> T fromJson(String json, Type type) {
        return gson.fromJson(json, type);
    }

    /**
     * Deserializes a JSON string to a list of maps.
     *
     * @param json the JSON string
     * @return the deserialized list of maps
     */
    public List<Map<String, Object>> fromJsonList(String json) {
        return gson.fromJson(json, LIST_MAP_TYPE);
    }

    // -----------------------------------------------------------------------
    // Protocol-specific helpers
    // -----------------------------------------------------------------------

    /**
     * Builds a request map with the specified type tag and parameters.
     * <p>
     * The resulting map will have a {@code "type"} key set to the message type.
     *
     * @param type     the message type (e.g. {@code "Inference"}, {@code "Status"})
     * @param params   additional key-value pairs to include (may be null)
     * @return a mutable map suitable for serialization
     */
    public Map<String, Object> buildRequest(String type, Map<String, Object> params) {
        Map<String, Object> request = new LinkedHashMap<>();
        request.put("type", type);
        if (params != null) {
            request.putAll(params);
        }
        return request;
    }

    /**
     * Builds a simple request with just a type tag (no parameters).
     *
     * @param type the message type
     * @return a mutable map with just the type field
     */
    public Map<String, Object> buildRequest(String type) {
        return buildRequest(type, null);
    }

    /**
     * Extracts the {@code type} field from a response map.
     *
     * @param response the response map
     * @return the type string, or {@code null} if not present
     */
    public static String getType(Map<String, Object> response) {
        Object type = response.get("type");
        return type instanceof String ? (String) type : null;
    }

    /**
     * Extracts a string field from a response map, returning a default if absent.
     *
     * @param response     the response map
     * @param key          the field key
     * @param defaultValue the default value
     * @return the field value, or the default
     */
    public static String getString(Map<String, Object> response, String key, String defaultValue) {
        Object value = response.get(key);
        return value instanceof String ? (String) value : defaultValue;
    }

    /**
     * Extracts a string field from a response map.
     *
     * @param response the response map
     * @param key      the field key
     * @return the field value, or {@code null}
     */
    public static String getString(Map<String, Object> response, String key) {
        return getString(response, key, null);
    }

    /**
     * Extracts an integer field from a response map.
     *
     * @param response     the response map
     * @param key          the field key
     * @param defaultValue the default value
     * @return the field value, or the default
     */
    public static int getInt(Map<String, Object> response, String key, int defaultValue) {
        Object value = response.get(key);
        if (value instanceof Number) {
            return ((Number) value).intValue();
        }
        return defaultValue;
    }

    /**
     * Extracts a long field from a response map.
     *
     * @param response     the response map
     * @param key          the field key
     * @param defaultValue the default value
     * @return the field value, or the default
     */
    public static long getLong(Map<String, Object> response, String key, long defaultValue) {
        Object value = response.get(key);
        if (value instanceof Number) {
            return ((Number) value).longValue();
        }
        return defaultValue;
    }

    /**
     * Extracts a boolean field from a response map.
     *
     * @param response     the response map
     * @param key          the field key
     * @param defaultValue the default value
     * @return the field value, or the default
     */
    public static boolean getBoolean(Map<String, Object> response, String key, boolean defaultValue) {
        Object value = response.get(key);
        if (value instanceof Boolean) {
            return (Boolean) value;
        }
        return defaultValue;
    }

    /**
     * Extracts a list from a response map.
     *
     * @param response the response map
     * @param key      the field key
     * @param <T>      the list element type
     * @return the list, or an empty list if not present
     */
    @SuppressWarnings("unchecked")
    public static <T> List<T> getList(Map<String, Object> response, String key) {
        Object value = response.get(key);
        if (value instanceof List) {
            return (List<T>) value;
        }
        return Collections.emptyList();
    }

    /**
     * Extracts a map from a response map.
     *
     * @param response the response map
     * @param key      the field key
     * @return the map, or an empty map if not present
     */
    @SuppressWarnings("unchecked")
    public static Map<String, Object> getMap(Map<String, Object> response, String key) {
        Object value = response.get(key);
        if (value instanceof Map) {
            return (Map<String, Object>) value;
        }
        return Collections.emptyMap();
    }

    /**
     * Checks if a response map represents an error.
     *
     * @param response the response map
     * @return {@code true} if the type is {@code "Error"}
     */
    public static boolean isError(Map<String, Object> response) {
        return "Error".equals(getType(response));
    }

    /**
     * Extracts the error code from an error response.
     *
     * @param response the error response map
     * @return the error code, or -1
     */
    public static int getErrorCode(Map<String, Object> response) {
        return getInt(response, "code", -1);
    }

    /**
     * Extracts the error message from an error response.
     *
     * @param response the error response map
     * @return the error message, or empty string
     */
    public static String getErrorMessage(Map<String, Object> response) {
        return getString(response, "message", "");
    }

    @Override
    public String toString() {
        return "JsonCodec{}";
    }
}