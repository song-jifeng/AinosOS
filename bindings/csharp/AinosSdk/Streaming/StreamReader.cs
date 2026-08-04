using System.Text;
using AinosSdk.Models;
using Microsoft.Extensions.Logging;

namespace AinosSdk.Streaming;

/// <summary>
/// Reads NDJSON lines from a raw byte source and yields parsed objects.
/// Handles buffering, partial line accumulation, and UTF-8 decoding.
/// </summary>
public class StreamReader
{
    private readonly Stream _innerStream;
    private readonly ILogger _logger;
    private readonly byte[] _buffer;
    private readonly StringBuilder _pending = new();
    private bool _disposed;

    /// <summary>
    /// Creates a new NDJSON stream reader.
    /// </summary>
    /// <param name="stream">The underlying stream to read from.</param>
    /// <param name="bufferSize">Buffer size for reads (default 8192).</param>
    /// <param name="logger">Optional logger.</param>
    public StreamReader(Stream stream, int bufferSize = 8192, ILogger? logger = null)
    {
        _innerStream = stream ?? throw new ArgumentNullException(nameof(stream));
        _buffer = new byte[bufferSize];
        _logger = logger ?? Microsoft.Extensions.Logging.Abstractions.NullLogger.Instance;
    }

    /// <summary>
    /// Reads a single NDJSON line from the stream.
    /// </summary>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The JSON line, or null if the stream is closed.</returns>
    /// <exception cref="AinosConnectionException">If the connection is lost.</exception>
    public async Task<string?> ReadLineAsync(CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        // Check if we already have a complete line in the pending buffer
        var newlineIdx = _pending.ToString().IndexOf('\n');
        if (newlineIdx >= 0)
        {
            return ExtractLine(newlineIdx);
        }

        while (!cancellationToken.IsCancellationRequested)
        {
            var bytesRead = await _innerStream.ReadAsync(_buffer, cancellationToken).ConfigureAwait(false);

            if (bytesRead == 0)
            {
                // Stream closed
                if (_pending.Length > 0)
                {
                    // Flush remaining data as a line
                    var line = _pending.ToString().TrimEnd();
                    _pending.Clear();
                    return line.Length > 0 ? line : null;
                }
                return null;
            }

            // Decode the buffer
            var text = Encoding.UTF8.GetString(_buffer, 0, bytesRead);
            _pending.Append(text);

            // Check for complete lines
            newlineIdx = _pending.ToString().IndexOf('\n');
            if (newlineIdx >= 0)
            {
                return ExtractLine(newlineIdx);
            }
        }

        return null;
    }

    /// <summary>
    /// Reads all remaining lines from the stream as an async enumerable.
    /// </summary>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>An async enumerable of JSON lines.</returns>
    public async IAsyncEnumerable<string> ReadAllLinesAsync(
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        while (true)
        {
            var line = await ReadLineAsync(cancellationToken).ConfigureAwait(false);
            if (line is null)
                yield break;

            yield return line;
        }
    }

    /// <summary>
    /// Reads a stream of JSON lines and parses them as <see cref="InferenceChunk"/> objects.
    /// </summary>
    /// <param name="model">Optional model name to include in each chunk.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>An async enumerable of inference chunks.</returns>
    public async IAsyncEnumerable<InferenceChunk> ReadChunksAsync(
        string? model = null,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        var index = 0;

        await foreach (var line in ReadAllLinesAsync(cancellationToken).ConfigureAwait(false))
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

                var chunk = new InferenceChunk
                {
                    Index = index++,
                    Model = model,
                };

                if (root.TryGetProperty("chunk", out var chunkProp))
                    chunk = chunk with { Chunk = chunkProp.GetString() ?? string.Empty };

                if (root.TryGetProperty("done", out var doneProp))
                    chunk = chunk with { Done = doneProp.GetBoolean() };

                yield return chunk;

                if (chunk.Done)
                    yield break;
            }
            catch (System.Text.Json.JsonException ex)
            {
                _logger.LogWarning(ex, "Failed to parse chunk JSON");
            }
        }
    }

    /// <summary>
    /// Extracts a complete line from the pending buffer.
    /// </summary>
    private string ExtractLine(int newlineIdx)
    {
        var line = _pending.ToString(0, newlineIdx).TrimEnd('\r');
        _pending.Remove(0, newlineIdx + 1);
        return line;
    }

    /// <summary>
    /// Disposes the reader.
    /// </summary>
    public void Dispose()
    {
        if (_disposed)
            return;
        _disposed = true;
        _pending.Clear();
    }
}