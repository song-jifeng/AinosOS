using System.Runtime.CompilerServices;
using AinosSdk.Models;
using Microsoft.Extensions.Logging;

namespace AinosSdk.Streaming;

/// <summary>
/// Provides an <see cref="IAsyncEnumerable{T}"/> of <see cref="InferenceChunk"/> for streaming inference.
/// Handles reading NDJSON lines from the transport and yielding parsed chunks.
/// </summary>
public class InferenceStream : IAsyncEnumerable<InferenceChunk>
{
    private readonly IAsyncEnumerable<InferenceChunk> _inner;

    /// <summary>
    /// Creates a new inference stream from a transport source.
    /// </summary>
    /// <param name="chunkSource">An async enumerable of raw JSON lines.</param>
    /// <param name="model">The model name (included in each chunk for context).</param>
    /// <param name="logger">Optional logger.</param>
    public InferenceStream(
        IAsyncEnumerable<string> chunkSource,
        string? model = null,
        ILogger? logger = null)
    {
        _inner = StreamChunks(chunkSource, model, logger);
    }

    /// <summary>
    /// Returns an async enumerator that iterates through the inference chunks.
    /// </summary>
    public IAsyncEnumerator<InferenceChunk> GetAsyncEnumerator(CancellationToken cancellationToken = default)
        => _inner.GetAsyncEnumerator(cancellationToken);

    /// <summary>
    /// Internal streaming logic: parses raw JSON lines into <see cref="InferenceChunk"/> objects.
    /// </summary>
    private static async IAsyncEnumerable<InferenceChunk> StreamChunks(
        IAsyncEnumerable<string> jsonLines,
        string? model,
        ILogger? logger,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        var index = 0;

        await foreach (var line in jsonLines.WithCancellation(cancellationToken).ConfigureAwait(false))
        {
            if (string.IsNullOrWhiteSpace(line))
                continue;

            try
            {
                using var doc = System.Text.Json.JsonDocument.Parse(line);
                var root = doc.RootElement;

                // Check for error
                if (root.TryGetProperty("type", out var typeProp))
                {
                    var type = typeProp.GetString();
                    if (type == "Error")
                    {
                        var code = root.TryGetProperty("code", out var c) ? c.GetInt32() : -1;
                        var message = root.TryGetProperty("message", out var m) ? m.GetString() : "Unknown streaming error";
                        throw new AinosException(message, code, type);
                    }
                }

                var chunk = ParseChunk(line, model, index);
                index++;

                yield return chunk;

                if (chunk.Done)
                    yield break;
            }
            catch (System.Text.Json.JsonException ex)
            {
                logger?.LogWarning(ex, "Failed to parse chunk JSON: {Line}", line[..Math.Min(line.Length, 200)]);
            }
        }
    }

    /// <summary>
    /// Parses a single JSON line into an <see cref="InferenceChunk"/>.
    /// </summary>
    internal static InferenceChunk ParseChunk(string json, string? model, int index)
    {
        using var doc = System.Text.Json.JsonDocument.Parse(json);
        var root = doc.RootElement;

        var chunk = new InferenceChunk
        {
            Index = index,
            Model = model,
        };

        if (root.TryGetProperty("chunk", out var chunkProp))
            chunk = chunk with { Chunk = chunkProp.GetString() ?? string.Empty };

        if (root.TryGetProperty("done", out var doneProp))
            chunk = chunk with { Done = doneProp.GetBoolean() };

        return chunk;
    }

    /// <summary>
    /// Collects all chunks from the stream into a single concatenated string.
    /// </summary>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The complete generated text.</returns>
    public async Task<string> CollectAllAsync(CancellationToken cancellationToken = default)
    {
        var sb = new System.Text.StringBuilder();
        await foreach (var chunk in this.WithCancellation(cancellationToken).ConfigureAwait(false))
        {
            sb.Append(chunk.Chunk);
            if (chunk.Done)
                break;
        }
        return sb.ToString();
    }

    /// <summary>
    /// Collects all chunks from the stream into a single <see cref="InferenceResponse"/>.
    /// </summary>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>An aggregated inference response.</returns>
    public async Task<InferenceResponse> CollectToResponseAsync(CancellationToken cancellationToken = default)
    {
        var sb = new System.Text.StringBuilder();
        var chunkCount = 0;

        await foreach (var chunk in this.WithCancellation(cancellationToken).ConfigureAwait(false))
        {
            sb.Append(chunk.Chunk);
            chunkCount++;
            if (chunk.Done)
                break;
        }

        return new InferenceResponse
        {
            Output = sb.ToString(),
            TokensGenerated = chunkCount,
            Source = "stream",
        };
    }
}