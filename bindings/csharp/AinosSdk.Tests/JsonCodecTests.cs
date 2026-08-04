using System.Text.Json;
using AinosSdk.Models;
using AinosSdk.Transport;
using Xunit;

namespace AinosSdk.Tests;

/// <summary>
/// Tests for the JSON codec serialization and deserialization.
/// </summary>
public class JsonCodecTests
{
    [Fact]
    public void SerializeRequest_WithType_CreatesValidJson()
    {
        var json = JsonCodec.SerializeRequest("Status");
        Assert.Equal("""{"type":"Status"}""", json);
    }

    [Fact]
    public void SerializeRequest_WithBody_CreatesValidJson()
    {
        var json = JsonCodec.SerializeRequest("ModelLoad", new Dictionary<string, object?>
        {
            ["path"] = "/models/test.gguf"
        });

        Assert.Contains("ModelLoad", json);
        Assert.Contains("/models/test.gguf", json);
    }

    [Fact]
    public void GetTypeTag_ExtractsCorrectly()
    {
        var tag = JsonCodec.GetTypeTag("""{"type":"Inference","model":"test"}""");
        Assert.Equal("Inference", tag);
    }

    [Fact]
    public void GetTypeTag_NoType_ReturnsNull()
    {
        var tag = JsonCodec.GetTypeTag("""{"model":"test"}""");
        Assert.Null(tag);
    }

    [Fact]
    public void TryParseError_ErrorResponse_ReturnsTrue()
    {
        var result = JsonCodec.TryParseError(
            """{"type":"Error","code":-1,"message":"Something went wrong"}""",
            out var code, out var message);

        Assert.True(result);
        Assert.Equal(-1, code);
        Assert.Equal("Something went wrong", message);
    }

    [Fact]
    public void TryParseError_NonErrorResponse_ReturnsFalse()
    {
        var result = JsonCodec.TryParseError(
            """{"type":"InferenceResponse","output":"ok"}""",
            out var code, out var message);

        Assert.False(result);
        Assert.Equal(0, code);
        Assert.Null(message);
    }

    [Fact]
    public void TryParseError_InvalidJson_ReturnsFalse()
    {
        var result = JsonCodec.TryParseError(
            "not-json",
            out var code, out var message);

        Assert.False(result);
    }

    [Fact]
    public void ParseInferenceResponse_ValidJson_ReturnsResponse()
    {
        var json = """{"type":"InferenceResponse","output":"Hello","tokens_generated":5,"inference_ms":100,"source":"local"}""";
        var response = JsonCodec.ParseInferenceResponse(json);

        Assert.Equal("Hello", response.Output);
        Assert.Equal(5, response.TokensGenerated);
        Assert.Equal(100, response.InferenceMs);
        Assert.Equal("local", response.Source);
    }

    [Fact]
    public void ParseModelListResponse_ValidJson_ReturnsModels()
    {
        var json = """{"type":"ModelListResponse","models":[{"id":"m1","name":"m1.gguf","path":"/m1","size_mb":1024,"loaded":true,"architecture":"auto"}]}""";
        var models = JsonCodec.ParseModelListResponse(json);

        Assert.Single(models);
        Assert.Equal("m1", models[0].Id);
        Assert.Equal("m1.gguf", models[0].Name);
        Assert.True(models[0].Loaded);
    }

    [Fact]
    public void ParseStatusResponse_ValidJson_ReturnsStatus()
    {
        var json = """{"type":"StatusResponse","uptime":3600,"models_loaded":2,"total_requests":100,"network_available":true,"active_sessions":3}""";
        var status = JsonCodec.ParseStatusResponse(json);

        Assert.Equal(3600, status.Uptime);
        Assert.Equal(2, status.ModelsLoaded);
        Assert.Equal(100, status.TotalRequests);
        Assert.True(status.NetworkAvailable);
        Assert.Equal(3, status.ActiveSessions);
    }

    [Fact]
    public void ParseHealthResponse_ValidJson_ReturnsHealth()
    {
        var json = """{"type":"StatusResponse","uptime":3600,"models_loaded":2,"total_requests":100,"network_available":true,"active_sessions":1}""";
        var health = JsonCodec.ParseHealthResponse(json);

        Assert.True(health.Healthy);
        Assert.Equal(3600, health.Uptime);
        Assert.Equal(2, health.ModelsLoaded);
    }

    [Fact]
    public void ParseRateLimitResponse_ValidJson_ReturnsLimits()
    {
        var json = """{"type":"RateLimitStatusResponse","limits":[{"category":"inference","limit":100,"remaining":75,"reset_seconds":30}]}""";
        var rateLimit = JsonCodec.ParseRateLimitResponse(json);

        Assert.Single(rateLimit.Limits);
        Assert.Equal("inference", rateLimit.Limits[0].Category);
        Assert.Equal(100, rateLimit.Limits[0].Limit);
        Assert.Equal(75, rateLimit.Limits[0].Remaining);
    }

    [Fact]
    public void ParseAuthResponse_Successful()
    {
        var json = """{"type":"AuthResponse","success":true,"session_token":"tok123","message":"OK","permissions":["infer","status"],"session_ttl_seconds":3600}""";
        var auth = JsonCodec.ParseAuthResponse(json);

        Assert.True(auth.Success);
        Assert.Equal("tok123", auth.SessionToken);
        Assert.Equal("OK", auth.Message);
        Assert.Equal(2, auth.Permissions.Count);
        Assert.Equal(3600, auth.SessionTtlSeconds);
    }

    [Fact]
    public void ParseAuthResponse_Failed()
    {
        var json = """{"type":"AuthResponse","success":false,"session_token":null,"message":"Bad token","permissions":[],"session_ttl_seconds":0}""";
        var auth = JsonCodec.ParseAuthResponse(json);

        Assert.False(auth.Success);
        Assert.Null(auth.SessionToken);
        Assert.Equal("Bad token", auth.Message);
    }

    [Fact]
    public void ParseModelLoadResponse_WithModelInfo()
    {
        var json = """{"type":"ModelLoadResponse","model_id":"m1","status":"loaded","message":"OK","model_info":{"id":"m1","name":"m1.gguf","path":"/m1","size_mb":1024,"loaded":true,"architecture":"auto"}}""";
        var data = JsonCodec.ParseModelLoadResponse(json);

        Assert.Equal("m1", data.ModelId);
        Assert.Equal("loaded", data.Status);
        Assert.NotNull(data.ModelInfo);
        Assert.Equal("m1", data.ModelInfo!.Id);
    }

    [Fact]
    public void ParseModelLoadResponse_WithoutModelInfo()
    {
        var json = """{"type":"ModelLoadResponse","model_id":"m1","status":"error","message":"Failed","model_info":null}""";
        var data = JsonCodec.ParseModelLoadResponse(json);

        Assert.Equal("m1", data.ModelId);
        Assert.Equal("error", data.Status);
        Assert.Null(data.ModelInfo);
    }

    [Fact]
    public void Serialize_WithNullValues_Omitted()
    {
        // Test that null values are omitted during serialization
        var json = JsonCodec.SerializeRequest("Inference", new Dictionary<string, object?>
        {
            ["model"] = "test",
            ["prompt"] = "hello",
            ["temperature"] = null,
        });

        Assert.DoesNotContain("temperature", json);
    }

    [Fact]
    public void Deserialize_CaseInsensitive_Works()
    {
        // Test that deserialization is case-insensitive
        var json = """{"OUTPUT":"Hello","TOKENS_GENERATED":5,"INFERENCE_MS":100,"SOURCE":"cloud"}""";
        var response = JsonCodec.ParseInferenceResponse(json);

        Assert.Equal("Hello", response.Output);
        Assert.Equal(5, response.TokensGenerated);
        Assert.Equal(100, response.InferenceMs);
        Assert.Equal("cloud", response.Source);
    }

    [Fact]
    public void ParseContextResponse_ExtractsOutput()
    {
        var json = """{"type":"InferenceResponse","output":"stored_value","tokens_generated":0,"inference_ms":0,"source":"local"}""";
        var output = JsonCodec.ParseContextResponse(json);

        Assert.Equal("stored_value", output);
    }

    [Fact]
    public void ParseContextResponse_EmptyOutput()
    {
        var json = """{"type":"InferenceResponse","output":"","tokens_generated":0,"inference_ms":0,"source":"local"}""";
        var output = JsonCodec.ParseContextResponse(json);

        Assert.Equal("", output);
    }

    [Fact]
    public void ParseModelUnloadResponse_Valid()
    {
        var json = """{"type":"ModelUnloadResponse","model_id":"m1","status":"unloaded","message":"OK"}""";
        var data = JsonCodec.ParseModelUnloadResponse(json);

        Assert.Equal("m1", data.ModelId);
        Assert.Equal("unloaded", data.Status);
        Assert.Equal("OK", data.Message);
    }

    [Fact]
    public void Serialize_InferenceRequest_ToWireFormat()
    {
        var request = new InferenceRequest
        {
            Model = "test-model",
            Prompt = "Hello",
            Temperature = 0.7f,
            MaxTokens = 100,
            SessionId = "sess-1",
        };

        var wire = request.ToWireFormat();
        Assert.Equal("Inference", wire["type"]);
        Assert.Equal("test-model", wire["model"]);
        Assert.Equal("Hello", wire["prompt"]);
        Assert.Equal(0.7f, wire["temperature"]);
        Assert.Equal(100, wire["max_tokens"]);
        Assert.Equal("sess-1", wire["session_id"]);
    }

    [Fact]
    public void Serialize_InferenceRequest_WithoutOptionals()
    {
        var request = new InferenceRequest
        {
            Prompt = "Hello",
        };

        var wire = request.ToWireFormat();
        Assert.Equal("Inference", wire["type"]);
        Assert.Equal("Hello", wire["prompt"]);
        Assert.DoesNotContain("temperature", wire.Keys);
        Assert.DoesNotContain("max_tokens", wire.Keys);
        Assert.DoesNotContain("session_id", wire.Keys);
    }

    [Fact]
    public void InferenceResponse_ToString_ContainsInfo()
    {
        var response = new InferenceResponse
        {
            Output = "Hello, world! This is a longer response.",
            TokensGenerated = 10,
            InferenceMs = 150,
            Source = "local",
        };

        var str = response.ToString();
        Assert.Contains("InferenceResponse", str);
        Assert.Contains("Tokens=10", str);
        Assert.Contains("Time=150ms", str);
    }

    [Fact]
    public void InferenceChunk_Parsing()
    {
        var json = """{"type":"InferenceChunk","chunk":"Hello","done":false}""";
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;

        var chunk = new InferenceChunk();
        if (root.TryGetProperty("chunk", out var c))
            chunk = chunk with { Chunk = c.GetString() ?? string.Empty };
        if (root.TryGetProperty("done", out var d))
            chunk = chunk with { Done = d.GetBoolean() };

        Assert.Equal("Hello", chunk.Chunk);
        Assert.False(chunk.Done);
    }

    [Fact]
    public void InferenceChunk_Done()
    {
        var json = """{"type":"InferenceChunk","chunk":"","done":true}""";
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;

        var chunk = new InferenceChunk();
        if (root.TryGetProperty("done", out var d))
            chunk = chunk with { Done = d.GetBoolean() };

        Assert.True(chunk.Done);
    }

    [Fact]
    public void RateLimitStatus_IsExceeded_DetectsCorrectly()
    {
        var status = new RateLimitStatus
        {
            Limits = new List<RateLimitInfo>
            {
                new() { Category = "inference", Limit = 100, Remaining = 0, ResetSeconds = 30 },
            }
        };

        Assert.True(status.IsExceeded);
    }

    [Fact]
    public void RateLimitStatus_NotExceeded()
    {
        var status = new RateLimitStatus
        {
            Limits = new List<RateLimitInfo>
            {
                new() { Category = "inference", Limit = 100, Remaining = 50, ResetSeconds = 30 },
            }
        };

        Assert.False(status.IsExceeded);
    }

    [Fact]
    public void RateLimitStatus_GetLimit_Found()
    {
        var status = new RateLimitStatus
        {
            Limits = new List<RateLimitInfo>
            {
                new() { Category = "inference", Limit = 100, Remaining = 50, ResetSeconds = 30 },
            }
        };

        var limit = status.GetLimit("inference");
        Assert.NotNull(limit);
        Assert.Equal(100, limit!.Limit);
    }

    [Fact]
    public void RateLimitStatus_GetLimit_NotFound()
    {
        var status = new RateLimitStatus
        {
            Limits = new List<RateLimitInfo>()
        };

        Assert.Null(status.GetLimit("inference"));
    }

    [Fact]
    public void SystemStatus_ToString_ContainsInfo()
    {
        var status = new SystemStatus
        {
            Uptime = 3600,
            ModelsLoaded = 2,
            TotalRequests = 100,
            NetworkAvailable = true,
        };

        var str = status.ToString();
        Assert.Contains("SystemStatus", str);
        Assert.Contains("Uptime=3600", str);
    }

    [Fact]
    public void ModelInfo_ToString_ContainsInfo()
    {
        var info = new ModelInfo
        {
            Id = "test_model",
            Name = "test.gguf",
            SizeMb = 1024,
            Loaded = true,
            Architecture = "auto",
        };

        var str = info.ToString();
        Assert.Contains("test_model", str);
        Assert.Contains("Loaded=True", str);
    }

    [Fact]
    public void HealthStatus_ToString_ContainsInfo()
    {
        var health = new HealthStatus
        {
            Healthy = true,
            Uptime = 3600,
            ModelsLoaded = 2,
        };

        var str = health.ToString();
        Assert.Contains("Healthy=True", str);
    }

    [Fact]
    public void ModelLoadOptions_Default_IsNotNull()
    {
        var options = ModelLoadOptions.Default;
        Assert.NotNull(options);
        Assert.False(options.SkipIfLoaded);
    }

    [Fact]
    public void Exception_WithErrorCode_StoresCode()
    {
        var ex = new AinosException("Test error", 42);
        Assert.Equal(42, ex.ErrorCode);
        Assert.Equal("Test error", ex.Message);
    }

    [Fact]
    public void AinosConnectionException_WithHostPort()
    {
        var ex = new AinosConnectionException("Failed", "host", 9500);
        Assert.Contains("host", ex.Message);
        Assert.Contains("9500", ex.Message);
        Assert.Equal("host", ex.Host);
        Assert.Equal(9500, ex.Port);
    }

    [Fact]
    public void AinosAuthException_WithReason()
    {
        var ex = new AinosAuthException("Auth failed", "Invalid token", false);
        Assert.Equal("Auth failed", ex.Message);
        Assert.Equal("Invalid token", ex.Reason);
        Assert.False(ex.IsSessionExpired);
    }

    [Fact]
    public void AinosRateLimitException_WithDetails()
    {
        var ex = new AinosRateLimitException("Too many requests", 30, "inference", 100, 0);
        Assert.Contains("inference", ex.Message);
        Assert.Equal(30, ex.RetryAfterSeconds);
        Assert.Equal("inference", ex.Category);
        Assert.Equal(100, ex.Limit);
        Assert.Equal(0, ex.Remaining);
    }
}