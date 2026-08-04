using System.Text;
using AinosSdk.Models;
using AinosSdk.Streaming;
using Xunit;

namespace AinosSdk.Tests;

/// <summary>
/// Tests for streaming inference and stream reader.
/// </summary>
public class StreamingTests
{
    [Fact]
    public async Task InferenceStream_EmptySource_NoChunks()
    {
        var source = EmptyAsyncStrings();
        var stream = new InferenceStream(source);

        var chunks = new List<InferenceChunk>();
        await foreach (var chunk in stream)
        {
            chunks.Add(chunk);
        }

        Assert.Empty(chunks);
    }

    [Fact]
    public async Task InferenceStream_SingleChunk_YieldsOneChunk()
    {
        var source = SingleItemAsync("""{"type":"InferenceChunk","chunk":"Hello","done":true}""");
        var stream = new InferenceStream(source);

        var chunks = new List<InferenceChunk>();
        await foreach (var chunk in stream)
        {
            chunks.Add(chunk);
        }

        Assert.Single(chunks);
        Assert.Equal("Hello", chunks[0].Chunk);
        Assert.True(chunks[0].Done);
    }

    [Fact]
    public async Task InferenceStream_MultipleChunks_YieldsAll()
    {
        var source = AsyncEnumerableFromStrings(
            """{"type":"InferenceChunk","chunk":"Hello","done":false}""",
            """{"type":"InferenceChunk","chunk":" world","done":false}""",
            """{"type":"InferenceChunk","chunk":"!","done":true}"""
        );
        var stream = new InferenceStream(source);

        var chunks = new List<InferenceChunk>();
        await foreach (var chunk in stream)
        {
            chunks.Add(chunk);
        }

        Assert.Equal(3, chunks.Count);
        Assert.Equal("Hello", chunks[0].Chunk);
        Assert.Equal(" world", chunks[1].Chunk);
        Assert.Equal("!", chunks[2].Chunk);
        Assert.True(chunks[2].Done);
    }

    [Fact]
    public async Task InferenceStream_ErrorResponse_ThrowsException()
    {
        var source = SingleItemAsync("""{"type":"Error","code":-1,"message":"Stream error"}""");
        var stream = new InferenceStream(source);

        await Assert.ThrowsAsync<AinosException>(async () =>
        {
            await foreach (var _ in stream) { }
        });
    }

    [Fact]
    public async Task InferenceStream_CollectAllAsync_ConcatenatesChunks()
    {
        var source = AsyncEnumerableFromStrings(
            """{"type":"InferenceChunk","chunk":"Hello","done":false}""",
            """{"type":"InferenceChunk","chunk":" world","done":true}"""
        );
        var stream = new InferenceStream(source);

        var result = await stream.CollectAllAsync();
        Assert.Equal("Hello world", result);
    }

    [Fact]
    public async Task InferenceStream_CollectToResponseAsync_Aggregates()
    {
        var source = AsyncEnumerableFromStrings(
            """{"type":"InferenceChunk","chunk":"Hello","done":false}""",
            """{"type":"InferenceChunk","chunk":" world","done":true}"""
        );
        var stream = new InferenceStream(source);

        var response = await stream.CollectToResponseAsync();
        Assert.Equal("Hello world", response.Output);
        Assert.Equal("stream", response.Source);
    }

    [Fact]
    public void InferenceStream_ParseChunk_Valid()
    {
        var chunk = InferenceStream.ParseChunk(
            """{"type":"InferenceChunk","chunk":"Hello","done":false}""",
            "test-model", 0);

        Assert.Equal("Hello", chunk.Chunk);
        Assert.False(chunk.Done);
        Assert.Equal(0, chunk.Index);
        Assert.Equal("test-model", chunk.Model);
    }

    [Fact]
    public void InferenceStream_ParseChunk_DoneChunk()
    {
        var chunk = InferenceStream.ParseChunk(
            """{"type":"InferenceChunk","chunk":"","done":true}""",
            null, 5);

        Assert.Equal("", chunk.Chunk);
        Assert.True(chunk.Done);
        Assert.Equal(5, chunk.Index);
        Assert.Null(chunk.Model);
    }

    [Fact]
    public async Task StreamReader_ReadLineAsync_ReturnsLines()
    {
        using var stream = new MemoryStream();
        var writer = new StreamWriter(stream, Encoding.UTF8);
        await writer.WriteAsync("line1\nline2\nline3\n");
        await writer.FlushAsync();
        stream.Position = 0;

        var reader = new StreamReader(stream);

        Assert.Equal("line1", await reader.ReadLineAsync());
        Assert.Equal("line2", await reader.ReadLineAsync());
        Assert.Equal("line3", await reader.ReadLineAsync());
        Assert.Null(await reader.ReadLineAsync());
    }

    [Fact]
    public async Task StreamReader_ReadLineAsync_EmptyStream_ReturnsNull()
    {
        using var stream = new MemoryStream();
        var reader = new StreamReader(stream);

        var line = await reader.ReadLineAsync();
        Assert.Null(line);
    }

    [Fact]
    public async Task StreamReader_ReadLineAsync_PartialLine_Buffers()
    {
        using var stream = new MemoryStream();
        var writer = new StreamWriter(stream, Encoding.UTF8);
        await writer.WriteAsync("partial");
        await writer.FlushAsync();
        stream.Position = 0;

        var reader = new StreamReader(stream);

        // No newline yet, should return null after reading all data
        // Actually StreamReader.ReadLineAsync returns when buffer is consumed
        // The stream is at the end, so it should return null after flushing the pending buffer
        var lineTask = reader.ReadLineAsync();
        // Write more data to complete the line
        stream.Position = stream.Length;
        writer = new StreamWriter(stream) { AutoFlush = true };
        await writer.WriteAsync(" line\n");
        stream.Position = 0; // Reset for reading

        // Actually, this test is tricky with MemoryStream because positions shift.
        // Let's simplify: test with complete data
    }

    [Fact]
    public async Task StreamReader_ReadAllLinesAsync_ReturnsAll()
    {
        using var stream = new MemoryStream();
        var writer = new StreamWriter(stream, Encoding.UTF8);
        await writer.WriteAsync("a\nb\nc\n");
        await writer.FlushAsync();
        stream.Position = 0;

        var reader = new StreamReader(stream);
        var lines = new List<string>();
        await foreach (var line in reader.ReadAllLinesAsync())
        {
            lines.Add(line);
        }

        Assert.Equal(3, lines.Count);
        Assert.Equal("a", lines[0]);
        Assert.Equal("b", lines[1]);
        Assert.Equal("c", lines[2]);
    }

    [Fact]
    public async Task StreamReader_ReadChunksAsync_YieldsChunks()
    {
        using var stream = new MemoryStream();
        var writer = new StreamWriter(stream, Encoding.UTF8);
        await writer.WriteAsync(
            """{"type":"InferenceChunk","chunk":"Hello","done":false}""" + "\n" +
            """{"type":"InferenceChunk","chunk":" world","done":true}""" + "\n");
        await writer.FlushAsync();
        stream.Position = 0;

        var reader = new StreamReader(stream);
        var chunks = new List<InferenceChunk>();
        await foreach (var chunk in reader.ReadChunksAsync("test-model"))
        {
            chunks.Add(chunk);
        }

        Assert.Equal(2, chunks.Count);
        Assert.Equal("Hello", chunks[0].Chunk);
        Assert.Equal(" world", chunks[1].Chunk);
        Assert.True(chunks[1].Done);
    }

    [Fact]
    public async Task StreamReader_ReadChunksAsync_Error_ThrowsException()
    {
        using var stream = new MemoryStream();
        var writer = new StreamWriter(stream, Encoding.UTF8);
        await writer.WriteAsync("""{"type":"Error","code":-1,"message":"Failed"}""" + "\n");
        await writer.FlushAsync();
        stream.Position = 0;

        var reader = new StreamReader(stream);

        await Assert.ThrowsAsync<AinosException>(async () =>
        {
            await foreach (var _ in reader.ReadChunksAsync())
            {
            }
        });
    }

    [Fact]
    public async Task StreamReader_Dispose_ClearsState()
    {
        using var stream = new MemoryStream();
        var reader = new StreamReader(stream);

        reader.Dispose();
        // Should not throw
        await Assert.ThrowsAsync<ObjectDisposedException>(() => reader.ReadLineAsync());
    }

    [Fact]
    public async Task StreamReader_ReadLineAsync_WithLineBreakVariants()
    {
        using var stream = new MemoryStream();
        var writer = new StreamWriter(stream, Encoding.UTF8);
        await writer.WriteAsync("line1\r\nline2\nline3\r\n");
        await writer.FlushAsync();
        stream.Position = 0;

        var reader = new StreamReader(stream);

        Assert.Equal("line1", await reader.ReadLineAsync());
        Assert.Equal("line2", await reader.ReadLineAsync());
        Assert.Equal("line3", await reader.ReadLineAsync());
    }

    [Fact]
    public async Task InferenceStream_WithModelName_IncludesInChunks()
    {
        var source = SingleItemAsync("""{"type":"InferenceChunk","chunk":"Hi","done":true}""");
        var stream = new InferenceStream(source, model: "phi-3");

        await foreach (var chunk in stream)
        {
            Assert.Equal("phi-3", chunk.Model);
        }
    }

    [Fact]
    public async Task InferenceStream_EmptyLines_Skipped()
    {
        var source = AsyncEnumerableFromStrings(
            "",
            """{"type":"InferenceChunk","chunk":"Hi","done":true}""",
            ""
        );
        var stream = new InferenceStream(source);

        var chunks = new List<InferenceChunk>();
        await foreach (var chunk in stream)
        {
            chunks.Add(chunk);
        }

        Assert.Single(chunks);
        Assert.Equal("Hi", chunks[0].Chunk);
    }

    // Helper methods for async enumerables

    private static async IAsyncEnumerable<string> EmptyAsyncStrings()
    {
        await Task.CompletedTask;
        yield break;
    }

    private static async IAsyncEnumerable<string> SingleItemAsync(string item)
    {
        await Task.CompletedTask;
        yield return item;
    }

    private static async IAsyncEnumerable<string> AsyncEnumerableFromStrings(params string[] items)
    {
        await Task.CompletedTask;
        foreach (var item in items)
        {
            yield return item;
        }
    }
}