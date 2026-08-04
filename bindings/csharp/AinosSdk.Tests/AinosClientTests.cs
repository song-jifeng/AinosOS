using System.Net;
using System.Net.Sockets;
using System.Text;
using AinosSdk.Models;
using Xunit;
using Xunit.Abstractions;

namespace AinosSdk.Tests;

/// <summary>
/// Tests for the AinosClient using a mock TCP server.
/// </summary>
public class AinosClientTests : IAsyncLifetime
{
    private readonly ITestOutputHelper _output;
    private MockTcpServer? _server;
    private AinosClient? _client;
    private int _port;

    public AinosClientTests(ITestOutputHelper output)
    {
        _output = output;
    }

    public async Task InitializeAsync()
    {
        _server = new MockTcpServer();
        _port = await _server.StartAsync();
    }

    public async Task DisposeAsync()
    {
        if (_client is not null)
            await _client.DisposeAsync().ConfigureAwait(false);
        _server?.Dispose();
    }

    [Fact]
    public async Task ConnectAsync_ConnectsToServer_Success()
    {
        _client = CreateClient();
        await _client.ConnectAsync();
        Assert.True(_client.Connected);
    }

    [Fact]
    public async Task ConnectAsync_ConnectionRefused_ThrowsConnectionException()
    {
        _client = new AinosClient(new Configuration.AinosClientOptions
        {
            Host = "127.0.0.1",
            Port = 19999,
            ConnectTimeout = TimeSpan.FromSeconds(1),
            AutoReconnect = false,
        });

        var ex = await Assert.ThrowsAsync<AinosConnectionException>(
            () => _client.ConnectAsync());
        Assert.Contains("Cannot connect", ex.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task AuthenticateAsync_ValidToken_SetsSessionState()
    {
        _server!.SetResponse("""{"type":"AuthResponse","success":true,"session_token":"test-session-token","message":"OK","permissions":["infer","status"],"session_ttl_seconds":3600}""");

        _client = CreateClient();
        await _client.ConnectAsync();

        var (success, sessionToken, permissions, ttl) = await _client.AuthenticateAsync("my-token");

        Assert.True(success);
        Assert.Equal("test-session-token", sessionToken);
        Assert.Contains("infer", permissions);
        Assert.Equal(3600, ttl);
        Assert.True(_client.Authenticated);
        Assert.Equal("test-session-token", _client.SessionToken);
    }

    [Fact]
    public async Task AuthenticateAsync_InvalidToken_ThrowsAuthException()
    {
        _server!.SetResponse("""{"type":"AuthResponse","success":false,"session_token":null,"message":"Invalid token","permissions":[],"session_ttl_seconds":0}""");

        _client = CreateClient();
        await _client.ConnectAsync();

        var ex = await Assert.ThrowsAsync<AinosAuthException>(
            () => _client.AuthenticateAsync("bad-token"));
        Assert.Contains("Invalid token", ex.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task AuthenticateAsync_EmptyToken_ThrowsAuthException()
    {
        _client = CreateClient();
        await _client.ConnectAsync();

        await Assert.ThrowsAsync<AinosAuthException>(
            () => _client.AuthenticateAsync(""));
    }

    [Fact]
    public async Task InferAsync_ValidResponse_ReturnsInferenceResponse()
    {
        _server!.SetResponse("""{"type":"InferenceResponse","output":"Hello, world!","tokens_generated":10,"inference_ms":150,"source":"local"}""");

        _client = CreateClient();
        await _client.ConnectAsync();

        var request = InferenceRequest.CreateBuilder("Hello").Build();
        var response = await _client.InferAsync(request);

        Assert.Equal("Hello, world!", response.Output);
        Assert.Equal(10, response.TokensGenerated);
        Assert.Equal(150, response.InferenceMs);
        Assert.Equal("local", response.Source);
    }

    [Fact]
    public async Task InferAsync_ServerError_ThrowsException()
    {
        _server!.SetResponse("""{"type":"Error","code":-1,"message":"Model not found"}""");

        _client = CreateClient();
        await _client.ConnectAsync();

        var request = InferenceRequest.CreateBuilder("Test").Build();
        var ex = await Assert.ThrowsAsync<AinosException>(
            () => _client.InferAsync(request));
        Assert.Contains("Model not found", ex.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task InferAsync_RateLimit_ThrowsRateLimitException()
    {
        _server!.SetResponse("""{"type":"Error","code":429,"message":"Rate limit exceeded"}""");

        _client = CreateClient();
        await _client.ConnectAsync();

        var request = InferenceRequest.CreateBuilder("Test").Build();
        var ex = await Assert.ThrowsAsync<AinosRateLimitException>(
            () => _client.InferAsync(request));
    }

    [Fact]
    public async Task GetStatusAsync_ReturnsStatus()
    {
        _server!.SetResponse("""{"type":"StatusResponse","uptime":3600,"models_loaded":2,"total_requests":100,"network_available":true,"active_sessions":3}""");

        _client = CreateClient();
        await _client.ConnectAsync();

        var status = await _client.GetStatusAsync();

        Assert.Equal(3600, status.Uptime);
        Assert.Equal(2, status.ModelsLoaded);
        Assert.Equal(100, status.TotalRequests);
        Assert.True(status.NetworkAvailable);
        Assert.Equal(3, status.ActiveSessions);
    }

    [Fact]
    public async Task GetModelListAsync_ReturnsModels()
    {
        _server!.SetResponse("""{"type":"ModelListResponse","models":[{"id":"m1","name":"model1.gguf","path":"/models/m1.gguf","size_mb":4096,"loaded":true,"architecture":"auto"},{"id":"m2","name":"model2.gguf","path":"/models/m2.gguf","size_mb":2048,"loaded":false,"architecture":"phi3"}]}""");

        _client = CreateClient();
        await _client.ConnectAsync();

        var models = await _client.GetModelListAsync();

        Assert.Equal(2, models.Count);
        Assert.Equal("m1", models[0].Id);
        Assert.Equal("model1.gguf", models[0].Name);
        Assert.True(models[0].Loaded);
        Assert.Equal("phi3", models[1].Architecture);
    }

    [Fact]
    public async Task LoadModelAsync_Success_ReturnsModelInfo()
    {
        _server!.SetResponse("""{"type":"ModelLoadResponse","model_id":"test_model","status":"loaded","message":"Loaded successfully","model_info":{"id":"test_model","name":"test.gguf","path":"/models/test.gguf","size_mb":1024,"loaded":true,"architecture":"auto"}}""");

        _client = CreateClient();
        await _client.ConnectAsync();

        var model = await _client.LoadModelAsync("/models/test.gguf");

        Assert.Equal("test_model", model.Id);
        Assert.True(model.Loaded);
    }

    [Fact]
    public async Task LoadModelAsync_Error_ThrowsException()
    {
        _server!.SetResponse("""{"type":"ModelLoadResponse","model_id":"","status":"error","message":"File not found","model_info":null}""");

        _client = CreateClient();
        await _client.ConnectAsync();

        var ex = await Assert.ThrowsAsync<AinosException>(
            () => _client.LoadModelAsync("/nonexistent/path"));
        Assert.Contains("File not found", ex.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task UnloadModelAsync_Success()
    {
        _server!.SetResponse("""{"type":"ModelUnloadResponse","model_id":"test_model","status":"unloaded","message":"Model unloaded successfully"}""");

        _client = CreateClient();
        await _client.ConnectAsync();

        await _client.UnloadModelAsync("test_model");
        // No exception means success
    }

    [Fact]
    public async Task ContextStoreAndRetrieve_Roundtrip()
    {
        // Store response
        _server!.SetResponse("""{"type":"InferenceResponse","output":"Context stored: my_key","tokens_generated":0,"inference_ms":0,"source":"local"}""");

        _client = CreateClient();
        await _client.ConnectAsync();

        var data = Encoding.UTF8.GetBytes("Hello, Ainos!");
        await _client.ContextStoreAsync("session-1", "my_key", data, ttl: 300);

        // Retrieve response
        _server!.SetResponse("""{"type":"InferenceResponse","output":"SGVsbG8sIEFpbm9zIQ==","tokens_generated":0,"inference_ms":0,"source":"local"}""");

        var retrieved = await _client.ContextRetrieveAsync("session-1", "my_key");
        Assert.NotNull(retrieved);
        Assert.Equal("Hello, Ainos!", Encoding.UTF8.GetString(retrieved));
    }

    [Fact]
    public async Task ContextRetrieveAsync_KeyNotFound_ReturnsNull()
    {
        _server!.SetResponse("""{"type":"Error","code":-1,"message":"Key not found: missing_key"}""");

        _client = CreateClient();
        await _client.ConnectAsync();

        var result = await _client.ContextRetrieveAsync("session-1", "missing_key");
        Assert.Null(result);
    }

    [Fact]
    public async Task GetHealthAsync_WhenConnected_ReturnsHealthy()
    {
        _server!.SetResponse("""{"type":"StatusResponse","uptime":3600,"models_loaded":2,"total_requests":100,"network_available":true,"active_sessions":1}""");

        _client = CreateClient();
        await _client.ConnectAsync();

        var health = await _client.GetHealthAsync();

        Assert.True(health.Healthy);
        Assert.Equal(3600, health.Uptime);
        Assert.Equal(2, health.ModelsLoaded);
    }

    [Fact]
    public async Task GetRateLimitStatusAsync_ReturnsLimits()
    {
        _server!.SetResponse("""{"type":"RateLimitStatusResponse","limits":[{"category":"inference","limit":100,"remaining":75,"reset_seconds":30},{"category":"status","limit":1000,"remaining":999,"reset_seconds":10}]}""");

        _client = CreateClient();
        await _client.ConnectAsync();

        var rateLimit = await _client.GetRateLimitStatusAsync();

        Assert.Equal(2, rateLimit.Limits.Count);
        var inferenceLimit = rateLimit.GetLimit("inference");
        Assert.NotNull(inferenceLimit);
        Assert.Equal(100, inferenceLimit!.Limit);
        Assert.Equal(75, inferenceLimit.Remaining);
    }

    [Fact]
    public async Task BatchInferAsync_ReturnsAllResponses()
    {
        // Set up sequential responses for multiple requests
        _server!.SetResponse("""{"type":"InferenceResponse","output":"Response 1","tokens_generated":5,"inference_ms":10,"source":"local"}""");
        _server!.AppendResponse("""{"type":"InferenceResponse","output":"Response 2","tokens_generated":8,"inference_ms":20,"source":"local"}""");
        _server!.AppendResponse("""{"type":"InferenceResponse","output":"Response 3","tokens_generated":12,"inference_ms":30,"source":"local"}""");

        _client = CreateClient();
        await _client.ConnectAsync();

        var requests = new List<InferenceRequest>
        {
            InferenceRequest.CreateBuilder("Prompt 1").Build(),
            InferenceRequest.CreateBuilder("Prompt 2").Build(),
            InferenceRequest.CreateBuilder("Prompt 3").Build(),
        };

        var results = await _client.BatchInferAsync(requests);

        Assert.Equal(3, results.Count);
        Assert.Equal("Response 1", results[0].Output);
        Assert.Equal("Response 2", results[1].Output);
        Assert.Equal("Response 3", results[2].Output);
    }

    [Fact]
    public async Task InferSimpleAsync_ReturnsOutputText()
    {
        _server!.SetResponse("""{"type":"InferenceResponse","output":"Simple inference result","tokens_generated":5,"inference_ms":10,"source":"local"}""");

        _client = CreateClient();
        await _client.ConnectAsync();

        var result = await _client.InferSimpleAsync("Hello");

        Assert.Equal("Simple inference result", result);
    }

    [Fact]
    public async Task DisconnectAsync_ClosesConnection()
    {
        _client = CreateClient();
        await _client.ConnectAsync();
        Assert.True(_client.Connected);

        await _client.DisconnectAsync();
        Assert.False(_client.Connected);
    }

    [Fact]
    public async Task InferStreamAsync_YieldsChunks()
    {
        _server!.SetResponse("""{"type":"InferenceChunk","chunk":"Hello","done":false}""");
        _server!.AppendResponse("""{"type":"InferenceChunk","chunk":" world","done":false}""");
        _server!.AppendResponse("""{"type":"InferenceChunk","chunk":"!","done":true}""");

        _client = CreateClient();
        await _client.ConnectAsync();

        var request = InferenceRequest.CreateBuilder("Test").Build();
        var chunks = new List<InferenceChunk>();

        await foreach (var chunk in _client.InferStreamAsync(request))
        {
            chunks.Add(chunk);
            if (chunk.Done)
                break;
        }

        Assert.Equal(3, chunks.Count);
        Assert.Equal("Hello", chunks[0].Chunk);
        Assert.Equal(" world", chunks[1].Chunk);
        Assert.Equal("!", chunks[2].Chunk);
        Assert.True(chunks[2].Done);
    }

    [Fact]
    public async Task InferStreamAsync_ErrorResponse_ThrowsException()
    {
        _server!.SetResponse("""{"type":"Error","code":-1,"message":"Stream error occurred"}""");

        _client = CreateClient();
        await _client.ConnectAsync();

        var request = InferenceRequest.CreateBuilder("Test").Build();

        await Assert.ThrowsAsync<AinosException>(async () =>
        {
            await foreach (var _ in _client.InferStreamAsync(request))
            {
            }
        });
    }

    [Fact]
    public async Task AutoAuthenticate_ConnectsAndAuthenticates()
    {
        _server!.SetResponse("""{"type":"AuthResponse","success":true,"session_token":"auto-session","message":"OK","permissions":["infer"],"session_ttl_seconds":3600}""");

        _client = new AinosClient(new Configuration.AinosClientOptions
        {
            Host = "127.0.0.1",
            Port = _port,
            AuthToken = "my-token",
            AutoAuthenticate = true,
            ConnectTimeout = TimeSpan.FromSeconds(5),
        });

        await _client.ConnectAsync();

        Assert.True(_client.Connected);
        Assert.True(_client.Authenticated);
        Assert.Equal("auto-session", _client.SessionToken);
    }

    [Fact]
    public async Task InferenceRequest_Builder_ConstructsCorrectly()
    {
        var request = InferenceRequest.CreateBuilder("Test prompt")
            .WithModel("phi-3")
            .WithTemperature(0.8f)
            .WithMaxTokens(500)
            .WithSessionId("sess-1")
            .Build();

        Assert.Equal("Test prompt", request.Prompt);
        Assert.Equal("phi-3", request.Model);
        Assert.Equal(0.8f, request.Temperature);
        Assert.Equal(500, request.MaxTokens);
        Assert.Equal("sess-1", request.SessionId);
    }

    [Fact]
    public async Task InferenceRequest_ToWireFormat_IncludesCorrectType()
    {
        var request = InferenceRequest.CreateBuilder("Hello").Build();
        var wire = request.ToWireFormat();

        Assert.Equal("Inference", wire["type"]);
        Assert.Equal("Hello", wire["prompt"]);
    }

    [Fact]
    public async Task InferenceRequest_ToStreamWireFormat_UsesInferenceStreamType()
    {
        var request = InferenceRequest.CreateBuilder("Hello").Build();
        var wire = request.ToStreamWireFormat();

        Assert.Equal("InferenceStream", wire["type"]);
    }

    [Fact]
    public async Task ModelLoadOptions_Builder_ConstructsCorrectly()
    {
        var options = ModelLoadOptions.CreateBuilder()
            .WithSkipIfLoaded(true)
            .WithArchitecture("phi3")
            .WithGpuLayers(32)
            .WithContextSize(4096)
            .Build();

        Assert.True(options.SkipIfLoaded);
        Assert.Equal("phi3", options.Architecture);
        Assert.Equal(32, options.GpuLayers);
        Assert.Equal(4096, options.ContextSize);
    }

    // Helper to create a client pointing at the mock server
    private AinosClient CreateClient()
    {
        return new AinosClient(new Configuration.AinosClientOptions
        {
            Host = "127.0.0.1",
            Port = _port,
            AutoReconnect = false,
            ConnectTimeout = TimeSpan.FromSeconds(5),
        });
    }
}

/// <summary>
/// A mock TCP server that simulates the Ainos daemon for testing.
/// </summary>
public class MockTcpServer : IDisposable
{
    private readonly TcpListener _listener;
    private readonly List<string> _responses = new();
    private readonly object _lock = new();
    private CancellationTokenSource? _cts;
    private Task? _listenTask;
    private int _port;
    private bool _disposed;

    public MockTcpServer()
    {
        _listener = new TcpListener(IPAddress.Loopback, 0);
    }

    public async Task<int> StartAsync()
    {
        _listener.Start();
        _port = ((IPEndPoint)_listener.LocalEndpoint).Port;

        _cts = new CancellationTokenSource();
        _listenTask = Task.Run(() => AcceptLoopAsync(_cts.Token));

        // Give the listener a moment to start
        await Task.Delay(50);
        return _port;
    }

    public void SetResponse(string json)
    {
        lock (_lock)
        {
            _responses.Clear();
            _responses.Add(json);
        }
    }

    public void AppendResponse(string json)
    {
        lock (_lock)
        {
            _responses.Add(json);
        }
    }

    private async Task AcceptLoopAsync(CancellationToken cancellationToken)
    {
        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                var client = await _listener.AcceptTcpClientAsync(cancellationToken);
                _ = HandleClientAsync(client, cancellationToken);
            }
        }
        catch (OperationCanceledException)
        {
            // Expected on shutdown
        }
        catch (ObjectDisposedException)
        {
            // Expected on shutdown
        }
    }

    private async Task HandleClientAsync(TcpClient client, CancellationToken cancellationToken)
    {
        try
        {
            using (client)
            using (var stream = client.GetStream())
            {
                var buffer = new byte[4096];
                var responseIndex = 0;

                while (!cancellationToken.IsCancellationRequested)
                {
                    var bytesRead = await stream.ReadAsync(buffer, cancellationToken);
                    if (bytesRead == 0)
                        break;

                    // Read the request line (for logging/assertion if needed)
                    var request = Encoding.UTF8.GetString(buffer, 0, bytesRead);

                    // Send response
                    string? responseJson;
                    lock (_lock)
                    {
                        if (responseIndex < _responses.Count)
                        {
                            responseJson = _responses[responseIndex];
                            responseIndex++;
                        }
                        else
                        {
                            // Echo the last response
                            responseJson = _responses.Count > 0
                                ? _responses[^1]
                                : """{"type":"Error","code":-1,"message":"No mock response configured"}""";
                        }
                    }

                    var responseBytes = Encoding.UTF8.GetBytes(responseJson + "\n");
                    await stream.WriteAsync(responseBytes, cancellationToken);
                    await stream.FlushAsync(cancellationToken);
                }
            }
        }
        catch (OperationCanceledException) { }
        catch (IOException) { }
        catch (ObjectDisposedException) { }
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;

        _cts?.Cancel();
        try { _listener.Stop(); } catch { }
        _cts?.Dispose();
    }
}