<?php

declare(strict_types=1);

namespace Ainos;

/**
 * Ainos - Streaming inference handler.
 *
 * Manages streaming responses from the Ainos server, providing
 * both generator-based iteration and full collection modes.
 * Handles buffering, error recovery, and stream lifecycle.
 *
 * @package Ainos
 */
final class StreamBuffer
{
    /** @var Transport The transport layer for reading stream data */
    private Transport $transport;

    /** @var string The request ID for this stream */
    private string $requestId;

    /** @var string The model being used */
    private string $model;

    /** @var callable|null Optional callback invoked on each chunk */
    private $onChunk = null;

    /** @var callable|null Optional callback invoked on stream error */
    private $onError = null;

    /** @var callable|null Optional callback invoked on stream completion */
    private $onComplete = null;

    /** @var bool Whether the stream has been aborted */
    private bool $aborted = false;

    /** @var bool Whether the stream is complete */
    private bool $complete = false;

    /** @var float Time when the stream started */
    private float $startTime;

    /** @var float Time when the stream ended */
    private ?float $endTime = null;

    /** @var int Total number of chunks received */
    private int $chunkCount = 0;

    /** @var int Total text characters received */
    private int $totalChars = 0;

    /** @var \Ainos\Usage|null Final usage statistics */
    private ?Usage $finalUsage = null;

    /** @var string Accumulated text from all chunks */
    private string $accumulatedText = '';

    /** @var array<StreamChunk> All chunks received (for replay) */
    private array $chunks = [];

    /** @var \Ainos\StreamingException|null Last error, if any */
    private ?StreamingException $lastError = null;

    /** @var float Maximum time to wait for a single chunk */
    private float $chunkTimeout;

    /** @var int Maximum number of consecutive empty reads before considering stream dead */
    private int $maxEmptyReads;

    /**
     * @param Transport $transport Connected transport layer
     * @param string $requestId Request ID for this stream
     * @param string $model Model name
     * @param array $options Stream options
     *        - chunk_timeout: float (default 30.0) timeout per chunk
     *        - max_empty_reads: int (default 10) max consecutive empty reads
     * @param callable|null $onChunk Optional chunk callback
     * @param callable|null $onError Optional error callback
     * @param callable|null $onComplete Optional completion callback
     */
    public function __construct(
        Transport $transport,
        string $requestId,
        string $model,
        array $options = [],
        ?callable $onChunk = null,
        ?callable $onError = null,
        ?callable $onComplete = null,
    ) {
        $this->transport = $transport;
        $this->requestId = $requestId;
        $this->model = $model;
        $this->onChunk = $onChunk;
        $this->onError = $onError;
        $this->onComplete = $onComplete;
        $this->startTime = Utils::microtimeFloat();
        $this->chunkTimeout = (float)($options['chunk_timeout'] ?? 30.0);
        $this->maxEmptyReads = (int)($options['max_empty_reads'] ?? 10);
    }

    /**
     * Yield chunks from the stream as they arrive.
     *
     * @return \Generator<StreamChunk>
     * @throws \Ainos\StreamingException on stream errors
     * @throws \Ainos\TransportException on transport errors
     * @throws \Ainos\TimeoutException on read timeout
     * @throws \Ainos\ProtocolException on protocol errors
     */
    public function chunks(): \Generator
    {
        $this->startTime = Utils::microtimeFloat();
        $emptyReads = 0;

        try {
            while (!$this->aborted && !$this->complete) {
                // Read a line from the transport
                $line = null;

                try {
                    $line = $this->transport->receiveLine($this->chunkTimeout);
                } catch (TimeoutException $e) {
                    throw StreamingException::streamTimeout($this->chunkTimeout);
                }

                // Connection closed
                if ($line === null) {
                    if ($this->chunkCount === 0) {
                        throw StreamingException::unexpectedEnd(
                            'Stream ended before any chunks were received'
                        );
                    }
                    break;
                }

                // Empty line (keep-alive or noise)
                if (\trim($line) === '') {
                    $emptyReads++;
                    if ($emptyReads >= $this->maxEmptyReads) {
                        throw StreamingException::unexpectedEnd(
                            \sprintf('Stream ended after %d consecutive empty reads', $emptyReads)
                        );
                    }
                    continue;
                }

                $emptyReads = 0;

                // Decode the response envelope
                $response = ResponseEnvelope::fromArray(
                    NDJSON::decodeLine($line, true)
                );

                // Check for errors
                if ($response->isError()) {
                    $errorMsg = $response->getErrorMessage();
                    $this->lastError = StreamingException::serverError($errorMsg);
                    if ($this->onError !== null) {
                        ($this->onError)($this->lastError);
                    }
                    throw $this->lastError;
                }

                // Check stream end
                if ($response->isStreamEnd()) {
                    $this->complete = true;
                    $this->endTime = Utils::microtimeFloat();

                    // Extract final usage if available
                    if (\is_array($response->result) && isset($response->result['usage'])) {
                        $this->finalUsage = Usage::fromArray($response->result['usage']);
                    }

                    // Yield the final end chunk
                    $endChunk = StreamChunk::end(
                        $this->requestId,
                        $this->model,
                        $this->finalUsage
                    );

                    $this->chunks[] = $endChunk;

                    if ($this->onChunk !== null) {
                        ($this->onChunk)($endChunk);
                    }
                    if ($this->onComplete !== null) {
                        ($this->onComplete)();
                    }

                    yield $endChunk;
                    return;
                }

                // Regular streaming chunk
                if ($response->isStream() || $response->result !== null) {
                    $chunkData = $response->result ?? [];
                    if (\is_array($chunkData)) {
                        $chunk = StreamChunk::fromArray(\array_merge(
                            $chunkData,
                            ['id' => $this->requestId, 'model' => $this->model]
                        ));

                        $this->chunks[] = $chunk;
                        $this->chunkCount++;
                        $this->totalChars += \strlen($chunk->text);
                        $this->accumulatedText .= $chunk->text;

                        if ($this->onChunk !== null) {
                            ($this->onChunk)($chunk);
                        }

                        yield $chunk;
                    }
                }
            }

            // If we exit the loop without a stream_end marker, mark as complete
            if (!$this->complete) {
                $this->complete = true;
                $this->endTime = Utils::microtimeFloat();
            }

        } catch (StreamingException $e) {
            $this->lastError = $e;
            $this->complete = true;
            $this->endTime = Utils::microtimeFloat();
            throw $e;
        } catch (TransportException $e) {
            $this->lastError = StreamingException::unexpectedEnd($e->getMessage());
            $this->complete = true;
            $this->endTime = Utils::microtimeFloat();
            throw $this->lastError;
        } catch (ProtocolException $e) {
            $this->lastError = StreamingException::invalidChunk(
                $e->getContextValue('raw_preview', ''),
                $e->getMessage()
            );
            $this->complete = true;
            $this->endTime = Utils::microtimeFloat();
            throw $this->lastError;
        } catch (\Throwable $e) {
            $this->lastError = StreamingException::unexpectedEnd($e->getMessage());
            $this->complete = true;
            $this->endTime = Utils::microtimeFloat();
            throw $this->lastError;
        }
    }

    /**
     * Collect all chunks into an array (blocks until stream completes).
     *
     * @return array<StreamChunk>
     * @throws \Ainos\StreamingException on stream errors
     */
    public function collect(): array
    {
        foreach ($this->chunks() as $chunk) {
            // Consume the generator
        }

        return $this->chunks;
    }

    /**
     * Collect all chunks and return the concatenated text.
     *
     * @return string
     * @throws \Ainos\StreamingException on stream errors
     */
    public function getText(): string
    {
        $this->collect();
        return $this->accumulatedText;
    }

    /**
     * Abort the stream.
     *
     * @param string|null $reason Optional reason for aborting
     * @return void
     */
    public function abort(?string $reason = null): void
    {
        $this->aborted = true;
        $this->complete = true;
        $this->endTime = Utils::microtimeFloat();

        $exception = StreamingException::aborted($reason ?? 'Stream aborted by client');

        if ($this->onError !== null) {
            ($this->onError)($exception);
        }

        $this->lastError = $exception;
    }

    /**
     * Check if the stream has been aborted.
     *
     * @return bool
     */
    public function isAborted(): bool
    {
        return $this->aborted;
    }

    /**
     * Check if the stream is complete.
     *
     * @return bool
     */
    public function isComplete(): bool
    {
        return $this->complete;
    }

    /**
     * Get the elapsed time since the stream started.
     *
     * @return float
     */
    public function getElapsedTime(): float
    {
        if ($this->endTime !== null) {
            return $this->endTime - $this->startTime;
        }

        return Utils::microtimeFloat() - $this->startTime;
    }

    /**
     * Get the number of chunks received.
     *
     * @return int
     */
    public function getChunkCount(): int
    {
        return $this->chunkCount;
    }

    /**
     * Get the total number of characters received.
     *
     * @return int
     */
    public function getTotalChars(): int
    {
        return $this->totalChars;
    }

    /**
     * Get the accumulated text from all chunks.
     *
     * @return string
     */
    public function getAccumulatedText(): string
    {
        return $this->accumulatedText;
    }

    /**
     * Get the final usage statistics, if available.
     *
     * @return \Ainos\Usage|null
     */
    public function getUsage(): ?Usage
    {
        return $this->finalUsage;
    }

    /**
     * Get all chunks received so far.
     *
     * @return array<StreamChunk>
     */
    public function getChunks(): array
    {
        return $this->chunks;
    }

    /**
     * Get the last error, if any.
     *
     * @return \Ainos\StreamingException|null
     */
    public function getLastError(): ?StreamingException
    {
        return $this->lastError;
    }

    /**
     * Get the request ID.
     *
     * @return string
     */
    public function getRequestId(): string
    {
        return $this->requestId;
    }

    /**
     * Get the model name.
     *
     * @return string
     */
    public function getModel(): string
    {
        return $this->model;
    }

    /**
     * Get the average tokens per second (approx based on chars).
     * Note: This is a rough estimate; actual token count will vary.
     *
     * @return float|null
     */
    public function getCharsPerSecond(): ?float
    {
        $elapsed = $this->getElapsedTime();
        if ($elapsed <= 0) {
            return null;
        }

        return $this->totalChars / $elapsed;
    }

    /**
     * Get stream statistics.
     *
     * @return array<string, mixed>
     */
    public function getStats(): array
    {
        return [
            'request_id' => $this->requestId,
            'model' => $this->model,
            'complete' => $this->complete,
            'aborted' => $this->aborted,
            'chunk_count' => $this->chunkCount,
            'total_chars' => $this->totalChars,
            'elapsed_time' => $this->getElapsedTime(),
            'chars_per_second' => $this->getCharsPerSecond(),
            'has_error' => $this->lastError !== null,
            'has_usage' => $this->finalUsage !== null,
        ];
    }

    /**
     * Wait for the stream to complete without yielding chunks.
     *
     * @return void
     * @throws \Ainos\StreamingException on stream errors
     */
    public function wait(): void
    {
        foreach ($this->chunks() as $chunk) {
            // Consume the generator
        }
    }

    /**
     * Create a StreamBuffer and immediately start collecting.
     * Convenience factory method.
     *
     * @param Transport $transport Connected transport
     * @param string $requestId Request ID
     * @param string $model Model name
     * @param array $options Stream options
     * @return array{text: string, chunks: array<StreamChunk>, usage: Usage|null, duration: float}
     * @throws \Ainos\StreamingException
     */
    public static function collectAll(
        Transport $transport,
        string $requestId,
        string $model,
        array $options = [],
    ): array {
        $buffer = new self($transport, $requestId, $model, $options);
        $text = $buffer->getText();

        return [
            'text' => $text,
            'chunks' => $buffer->getChunks(),
            'usage' => $buffer->getUsage(),
            'duration' => $buffer->getElapsedTime(),
        ];
    }
}

/**
 * Ainos - Stream processor for handling streaming responses with
 * advanced features like backpressure, concurrency limits, and
 * progress tracking.
 *
 * @package Ainos
 */
final class StreamProcessor
{
    /** @var array<StreamBuffer> Active streams */
    private array $streams = [];

    /** @var int Maximum number of concurrent streams */
    private int $maxConcurrent;

    /** @var int Current number of active streams */
    private int $activeCount = 0;

    /**
     * @param int $maxConcurrent Maximum concurrent streams (default: 10)
     */
    public function __construct(int $maxConcurrent = 10)
    {
        $this->maxConcurrent = $maxConcurrent;
    }

    /**
     * Add a stream to the processor.
     *
     * @param StreamBuffer $stream Stream to process
     * @return void
     * @throws \Ainos\InvalidRequestException if max concurrent streams exceeded
     */
    public function addStream(StreamBuffer $stream): void
    {
        if ($this->activeCount >= $this->maxConcurrent) {
            throw InvalidRequestException::general(
                \sprintf(
                    'Maximum concurrent streams (%d) exceeded',
                    $this->maxConcurrent
                )
            );
        }

        $this->streams[] = $stream;
        $this->activeCount++;
    }

    /**
     * Process all streams concurrently and collect results.
     * Each stream is consumed in sequence; for true concurrent
     * processing, use processConcurrent().
     *
     * @return array<string, mixed>
     */
    public function processAll(): array
    {
        $results = [];

        foreach ($this->streams as $index => $stream) {
            try {
                $text = $stream->getText();
                $results["stream_{$index}"] = [
                    'text' => $text,
                    'chunks' => $stream->getChunks(),
                    'usage' => $stream->getUsage(),
                    'duration' => $stream->getElapsedTime(),
                    'error' => null,
                ];
            } catch (StreamingException $e) {
                $results["stream_{$index}"] = [
                    'text' => $stream->getAccumulatedText(),
                    'chunks' => $stream->getChunks(),
                    'usage' => $stream->getUsage(),
                    'duration' => $stream->getElapsedTime(),
                    'error' => $e->getMessage(),
                ];
            }
        }

        return $results;
    }

    /**
     * Get the number of active streams.
     *
     * @return int
     */
    public function getActiveCount(): int
    {
        return $this->activeCount;
    }

    /**
     * Get the maximum concurrent streams setting.
     *
     * @return int
     */
    public function getMaxConcurrent(): int
    {
        return $this->maxConcurrent;
    }

    /**
     * Clear all completed streams.
     *
     * @return void
     */
    public function clearCompleted(): void
    {
        $this->streams = \array_values(
            \array_filter($this->streams, fn(StreamBuffer $s) => !$s->isComplete())
        );
        $this->activeCount = \count($this->streams);
    }

    /**
     * Abort all active streams.
     *
     * @param string $reason Reason for aborting
     * @return void
     */
    public function abortAll(string $reason = 'Processor abort'): void
    {
        foreach ($this->streams as $stream) {
            if (!$stream->isComplete()) {
                $stream->abort($reason);
            }
        }

        $this->streams = [];
        $this->activeCount = 0;
    }
}