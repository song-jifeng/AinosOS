/**
 * Ainos SDK — Streaming support for inference responses.
 *
 * Provides a {@link InferenceStream} class that wraps the raw TCP transport
 * into a convenient EventEmitter interface.  Streams emit `data` events for
 * each text chunk, a `progress` event with cumulative stats, and `end` /
 * `error` terminal events.
 */

import { EventEmitter } from 'events';
import { InferenceChunk } from './types';
import { TcpTransport } from './transport';
import { safeDecodeJson } from './utils';
import { InferenceError } from './errors';

// ============================================================================
// Constants
// ============================================================================

/** Default high-water mark for backpressure (number of buffered chunks). */
const DEFAULT_HIGH_WATER_MARK = 1024;

// ============================================================================
// InferenceStream
// ============================================================================

/**
 * A streaming inference session.
 *
 * Emits:
 * - `data` (chunk: string) — for each text fragment received
 * - `progress` (tokensGenerated: number, elapsedMs: number) — cumulative stats
 * - `end` () — when the stream completes
 * - `error` (err: Error) — when an error occurs
 *
 * Usage:
 * ```ts
 * const stream = client.inferStream({ prompt: "Hello" });
 * stream.on('data', (chunk) => process.stdout.write(chunk));
 * stream.on('end', () => console.log('\n[Done]'));
 * ```
 */
export class InferenceStream extends EventEmitter {
  private transport: TcpTransport;
  private request: Record<string, unknown>;
  private _started = false;
  private _ended = false;
  private _tokensGenerated = 0;
  private _startTime = 0;
  private buffer: string[] = [];
  private highWaterMark: number;

  // Backpressure tracking
  private _paused = false;
  private drainResolve: (() => void) | null = null;

  constructor(
    transport: TcpTransport,
    request: Record<string, unknown>,
    options?: { highWaterMark?: number },
  ) {
    super();
    this.transport = transport;
    this.request = request;
    this.highWaterMark = options?.highWaterMark ?? DEFAULT_HIGH_WATER_MARK;
  }

  // --------------------------------------------------------------------------
  // Properties
  // --------------------------------------------------------------------------

  /** Whether the stream has started receiving data. */
  get started(): boolean {
    return this._started;
  }

  /** Whether the stream has ended. */
  get ended(): boolean {
    return this._ended;
  }

  /** Total tokens generated so far (from the daemon's reporting). */
  get tokensGenerated(): number {
    return this._tokensGenerated;
  }

  /** Elapsed milliseconds since the stream started. */
  get elapsedMs(): number {
    if (!this._startTime) return 0;
    return Date.now() - this._startTime;
  }

  // --------------------------------------------------------------------------
  // Public API
  // --------------------------------------------------------------------------

  /**
   * Start the streaming inference.
   *
   * This sends the inference request and begins reading the response stream.
   * The stream must be consumed via event listeners.
   */
  start(): void {
    if (this._started) {
      throw new Error('Stream already started');
    }
    this._started = true;
    this._startTime = Date.now();

    // Send the request
    const payload = { ...this.request, type: 'InferenceStream' };
    this.transport.send(payload);

    // Begin reading lines in the background
    this.readNextChunk();
  }

  /**
   * Cancel the stream before it completes.
   */
  cancel(): void {
    if (this._ended) return;
    this._ended = true;
    this.buffer = [];
    this.emit('end');
    this.removeAllListeners();
  }

  /**
   * Pause the stream (backpressure).
   *
   * While paused, chunks are buffered internally.  Call {@link resume} to
   * resume emitting `data` events.
   */
  pause(): void {
    this._paused = true;
  }

  /**
   * Resume a paused stream.
   */
  resume(): void {
    if (!this._paused) return;
    this._paused = false;

    // Flush buffered chunks
    while (this.buffer.length > 0 && !this._paused && !this._ended) {
      const chunk = this.buffer.shift()!;
      this.emit('data', chunk);
    }

    // Signal drain
    if (this.drainResolve) {
      this.drainResolve();
      this.drainResolve = null;
    }

    // If we drained the buffer, resume reading
    if (this.buffer.length === 0 && !this._ended) {
      this.readNextChunk();
    }
  }

  /**
   * Return a promise that resolves when the stream ends.
   */
  waitForEnd(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (this._ended) {
        resolve();
        return;
      }
      this.once('end', resolve);
      this.once('error', reject);
    });
  }

  // --------------------------------------------------------------------------
  // Internal: Chunk Reading
  // --------------------------------------------------------------------------

  /**
   * Read the next available chunk line from the transport.
   *
   * This is called recursively until the stream ends.
   */
  private async readNextChunk(): Promise<void> {
    if (this._ended) return;

    try {
      // Apply backpressure: if paused and buffer is full, wait
      if (this._paused && this.buffer.length >= this.highWaterMark) {
        await new Promise<void>((resolve) => {
          this.drainResolve = resolve;
        });
        if (this._ended) return;
      }

      const line = await this.transport.sendAndReceive(this.request, 300000);

      if (this._ended) return;

      const parsed = safeDecodeJson<{ type: string }>(line, { type: '' });

      if (!parsed || !parsed.type) {
        // Malformed line — skip
        this.readNextChunk();
        return;
      }

      switch (parsed.type) {
        case 'InferenceChunk': {
          const chunk = safeDecodeJson<InferenceChunk>(line, { chunk: '', done: false });
          if (chunk.chunk.length > 0) {
            this.emitChunk(chunk.chunk);
          }
          if (chunk.done) {
            this.finish();
          } else {
            this.readNextChunk();
          }
          break;
        }

        case 'Error': {
          const errData = safeDecodeJson<{ message: string }>(line, { message: 'Unknown streaming error' });
          this.fail(new InferenceError(errData.message));
          break;
        }

        case 'InferenceResponse': {
          // Non-streaming response returned for a stream request — treat as a single chunk
          const respData = safeDecodeJson<{ output: string; tokens_generated?: number }>(
            line,
            { output: '', tokens_generated: 0 },
          );
          if (respData.output.length > 0) {
            this.emitChunk(respData.output);
          }
          this._tokensGenerated = respData.tokens_generated ?? 0;
          this.finish();
          break;
        }

        default: {
          // Unknown type — skip and continue
          this.readNextChunk();
          break;
        }
      }
    } catch (err) {
      if (!this._ended) {
        this.fail(err instanceof Error ? err : new Error(String(err)));
      }
    }
  }

  /**
   * Emit a chunk, applying backpressure.
   */
  private emitChunk(chunk: string): void {
    if (this._paused) {
      this.buffer.push(chunk);
      return;
    }

    this.emit('data', chunk);

    // Update progress
    this._tokensGenerated += 1;
    this.emit('progress', this._tokensGenerated, this.elapsedMs);

    // Check if we need to pause
    if (this.listenerCount('data') === 0) {
      // No consumer — buffer
      this.buffer.push(chunk);
      if (this.buffer.length >= this.highWaterMark) {
        this._paused = true;
      }
    }
  }

  /**
   * Finish the stream successfully.
   */
  private finish(): void {
    if (this._ended) return;
    this._ended = true;
    this.emit('progress', this._tokensGenerated, this.elapsedMs);
    this.emit('end');
    this.removeAllListeners();
  }

  /**
   * Fail the stream with an error.
   */
  private fail(err: Error): void {
    if (this._ended) return;
    this._ended = true;
    this.emit('error', err);
    this.removeAllListeners();
  }
}

// ============================================================================
// ReadableStreamAdapter
// ============================================================================

/**
 * Adapt an {@link InferenceStream} to a Node.js `Readable` stream.
 *
 * This allows the streaming inference to be used with Node.js stream
 * pipelines and Web Streams API consumers.
 */
export class ReadableStreamAdapter extends (require('stream').Readable) {
  private stream: InferenceStream;

  constructor(stream: InferenceStream, options?: { highWaterMark?: number }) {
    super({
      objectMode: true,
      highWaterMark: options?.highWaterMark ?? DEFAULT_HIGH_WATER_MARK,
    });
    this.stream = stream;

    this.stream.on('data', (chunk: string) => {
      if (!this.push(chunk)) {
        this.stream.pause();
      }
    });

    this.stream.on('end', () => {
      this.push(null);
    });

    this.stream.on('error', (err: Error) => {
      this.destroy(err);
    });
  }

  _read(): void {
    this.stream.resume();
  }
}

// ============================================================================
// Stream Accumulator
// ============================================================================

/**
 * Accumulate a streaming inference into a single string.
 *
 * Useful for testing or when you want the full output after streaming.
 *
 * @param stream - The inference stream to consume.
 * @returns A promise that resolves to the full concatenated output.
 */
export function accumulateStream(stream: InferenceStream): Promise<string> {
  return new Promise((resolve, reject) => {
    const parts: string[] = [];
    stream.on('data', (chunk: string) => parts.push(chunk));
    stream.on('end', () => resolve(parts.join('')));
    stream.on('error', reject);
    stream.start();
  });
}