using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using AinosSdk.Models;

namespace AinosSdk.Transport;

/// <summary>
/// JSON serialization and deserialization for the Ainos NDJSON protocol.
/// Handles type-tagged message discrimination and snake_case/camelCase mapping.
/// </summary>
public static class JsonCodec
{
    /// <summary>
    /// Default JSON serializer options matching the daemon's expectations.
    /// Uses camelCase property names and compact serialization.
    /// </summary>
    public static readonly JsonSerializerOptions SerializeOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        WriteIndented = false,
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    /// <summary>
    /// Default JSON deserializer options.
    /// Case-insensitive property matching for the daemon's camelCase JSON.
    /// </summary>
    public static readonly JsonSerializerOptions DeserializeOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    /// <summary>
    /// Serializes a request to a JSON string for the NDJSON wire format.
    /// </summary>
    /// <param name="type">The message type tag.</param>
    /// <param name="body">The request body fields as a dictionary.</param>
    /// <returns>A compact JSON string.</returns>
    public static string SerializeRequest(string type, Dictionary<string, object?>? body = null)
    {
        var payload = new Dictionary<string, object?>
        {
            ["type"] = type
        };

        if (body is not null)
        {
            foreach (var (key, value) in body)
            {
                payload[key] = value;
            }
        }

        return JsonSerializer.Serialize(payload, SerializeOptions);
    }

    /// <summary>
    /// Serializes a request object to a JSON string.
    /// </summary>
    /// <param name="request">The request object.</param>
    /// <returns>A compact JSON string.</returns>
    public static string Serialize<T>(T request)
    {
        return JsonSerializer.Serialize(request, SerializeOptions);
    }

    /// <summary>
    /// Deserializes a JSON response string to a typed response.
    /// </summary>
    /// <typeparam name="T">The target type.</typeparam>
    /// <param name="json">The JSON string.</param>
    /// <returns>The deserialized object.</returns>
    public static T? Deserialize<T>(string json)
    {
        return JsonSerializer.Deserialize<T>(json, DeserializeOptions);
    }

    /// <summary>
    /// Parses a JSON response and extracts the type tag.
    /// </summary>
    /// <param name="json">The JSON response string.</param>
    /// <returns>The type tag value, or null if not found.</returns>
    public static string? GetTypeTag(string json)
    {
        using var doc = JsonDocument.Parse(json);
        if (doc.RootElement.TryGetProperty("type", out var typeProp))
        {
            return typeProp.GetString();
        }
        return null;
    }

    /// <summary>
    /// Parses a JSON response and checks if it's an error message.
    /// </summary>
    /// <param name="json">The JSON response string.</param>
    /// <param name="errorCode">The error code, if applicable.</param>
    /// <param name="errorMessage">The error message, if applicable.</param>
    /// <returns>True if the response is an error.</returns>
    public static bool TryParseError(string json, out int errorCode, out string? errorMessage)
    {
        errorCode = 0;
        errorMessage = null;

        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;

            if (!root.TryGetProperty("type", out var typeProp))
            {
                return false;
            }

            if (typeProp.GetString() != "Error")
            {
                return false;
            }

            if (root.TryGetProperty("code", out var codeProp))
            {
                errorCode = codeProp.GetInt32();
            }

            if (root.TryGetProperty("message", out var msgProp))
            {
                errorMessage = msgProp.GetString();
            }

            return true;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    /// <summary>
    /// Parses an inference response from JSON.
    /// </summary>
    public static InferenceResponse ParseInferenceResponse(string json)
    {
        var response = Deserialize<InferenceResponse>(json);
        return response ?? new InferenceResponse { Output = string.Empty };
    }

    /// <summary>
    /// Parses a model list response from JSON.
    /// </summary>
    public static List<ModelInfo> ParseModelListResponse(string json)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;

        var models = new List<ModelInfo>();
        if (root.TryGetProperty("models", out var modelsProp))
        {
            foreach (var modelElement in modelsProp.EnumerateArray())
            {
                var model = JsonSerializer.Deserialize<ModelInfo>(modelElement.GetRawText(), DeserializeOptions);
                if (model is not null)
                    models.Add(model);
            }
        }

        return models;
    }

    /// <summary>
    /// Parses a system status response from JSON.
    /// </summary>
    public static SystemStatus ParseStatusResponse(string json)
    {
        return Deserialize<SystemStatus>(json) ?? new SystemStatus();
    }

    /// <summary>
    /// Parses a health status response from JSON.
    /// </summary>
    public static HealthStatus ParseHealthResponse(string json)
    {
        return Deserialize<HealthStatus>(json) ?? new HealthStatus { Healthy = false, Message = "Parse failed" };
    }

    /// <summary>
    /// Parses a rate limit status response from JSON.
    /// </summary>
    public static RateLimitStatus ParseRateLimitResponse(string json)
    {
        return Deserialize<RateLimitStatus>(json) ?? new RateLimitStatus();
    }

    /// <summary>
    /// Parses an auth response from JSON.
    /// </summary>
    public static AuthResponseData ParseAuthResponse(string json)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;

        return new AuthResponseData
        {
            Success = root.TryGetProperty("success", out var s) && s.GetBoolean(),
            SessionToken = root.TryGetProperty("session_token", out var st) ? st.GetString() : null,
            Message = root.TryGetProperty("message", out var m) ? m.GetString() : string.Empty,
            Permissions = root.TryGetProperty("permissions", out var p)
                ? p.EnumerateArray().Select(e => e.GetString() ?? string.Empty).Where(x => x is not null).ToList()!
                : new List<string>(),
            SessionTtlSeconds = root.TryGetProperty("session_ttl_seconds", out var ttl) ? ttl.GetInt64() : 0,
        };
    }

    /// <summary>
    /// Parses a model load response from JSON.
    /// </summary>
    public static ModelLoadResponseData ParseModelLoadResponse(string json)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;

        var data = new ModelLoadResponseData
        {
            ModelId = root.TryGetProperty("model_id", out var mid) ? mid.GetString() ?? string.Empty : string.Empty,
            Status = root.TryGetProperty("status", out var st) ? st.GetString() ?? string.Empty : string.Empty,
            Message = root.TryGetProperty("message", out var msg) ? msg.GetString() ?? string.Empty : string.Empty,
        };

        if (root.TryGetProperty("model_info", out var mi) && mi.ValueKind == JsonValueKind.Object)
        {
            data.ModelInfo = JsonSerializer.Deserialize<ModelInfo>(mi.GetRawText(), DeserializeOptions);
        }

        return data;
    }

    /// <summary>
    /// Parses a model unload response from JSON.
    /// </summary>
    public static ModelUnloadResponseData ParseModelUnloadResponse(string json)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;

        return new ModelUnloadResponseData
        {
            ModelId = root.TryGetProperty("model_id", out var mid) ? mid.GetString() ?? string.Empty : string.Empty,
            Status = root.TryGetProperty("status", out var st) ? st.GetString() ?? string.Empty : string.Empty,
            Message = root.TryGetProperty("message", out var msg) ? msg.GetString() ?? string.Empty : string.Empty,
        };
    }

    /// <summary>
    /// Extracts a string value from an inference response.
    /// </summary>
    public static string ParseContextResponse(string json)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;

        if (root.TryGetProperty("output", out var output))
            return output.GetString() ?? string.Empty;

        return string.Empty;
    }
}

/// <summary>
/// Auth response data from the daemon.
/// </summary>
public class AuthResponseData
{
    public bool Success { get; init; }
    public string? SessionToken { get; init; }
    public string Message { get; init; } = string.Empty;
    public List<string> Permissions { get; init; } = new();
    public long SessionTtlSeconds { get; init; }
}

/// <summary>
/// Model load response data from the daemon.
/// </summary>
public class ModelLoadResponseData
{
    public string ModelId { get; init; } = string.Empty;
    public string Status { get; init; } = string.Empty;
    public string Message { get; init; } = string.Empty;
    public ModelInfo? ModelInfo { get; init; }
}

/// <summary>
/// Model unload response data from the daemon.
/// </summary>
public class ModelUnloadResponseData
{
    public string ModelId { get; init; } = string.Empty;
    public string Status { get; init; } = string.Empty;
    public string Message { get; init; } = string.Empty;
}