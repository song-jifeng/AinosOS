/**
 * Ainos SDK — Streaming support for inference responses.
 *
 * Provides a {@link InferenceStream} class that wraps the raw TCP transport
 * into a convenient EventEmitter interface.  Streams emit `data` events for
 * each text chunk, a `progress` event with cumulative stats, and `end` /
 * `error` terminal events.
 */
import { EventEmitter } from 'events';
import { TcpTransport } from './transport';
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
export declare class InferenceStream extends EventEmitter {
    private transport;
    private request;
    private _started;
    private _ended;
    private _tokensGenerated;
    private _startTime;
    private buffer;
    private highWaterMark;
    private _paused;
    private drainResolve;
    constructor(transport: TcpTransport, request: Record<string, unknown>, options?: {
        highWaterMark?: number;
    });
    /** Whether the stream has started receiving data. */
    get started(): boolean;
    /** Whether the stream has ended. */
    get ended(): boolean;
    /** Total tokens generated so far (from the daemon's reporting). */
    get tokensGenerated(): number;
    /** Elapsed milliseconds since the stream started. */
    get elapsedMs(): number;
    /**
     * Start the streaming inference.
     *
     * This sends the inference request and begins reading the response stream.
     * The stream must be consumed via event listeners.
     */
    start(): void;
    /**
     * Cancel the stream before it completes.
     */
    cancel(): void;
    /**
     * Pause the stream (backpressure).
     *
     * While paused, chunks are buffered internally.  Call {@link resume} to
     * resume emitting `data` events.
     */
    pause(): void;
    /**
     * Resume a paused stream.
     */
    resume(): void;
    /**
     * Return a promise that resolves when the stream ends.
     */
    waitForEnd(): Promise<void>;
    /**
     * Read the next available chunk line from the transport.
     *
     * This is called recursively until the stream ends.
     */
    private readNextChunk;
    /**
     * Emit a chunk, applying backpressure.
     */
    private emitChunk;
    /**
     * Finish the stream successfully.
     */
    private finish;
    /**
     * Fail the stream with an error.
     */
    private fail;
}
declare const ReadableStreamAdapter_base: any;
/**
 * Adapt an {@link InferenceStream} to a Node.js `Readable` stream.
 *
 * This allows the streaming inference to be used with Node.js stream
 * pipelines and Web Streams API consumers.
 */
export declare class ReadableStreamAdapter extends ReadableStreamAdapter_base {
    private stream;
    constructor(stream: InferenceStream, options?: {
        highWaterMark?: number;
    });
    _read(): void;
}
/**
 * Accumulate a streaming inference into a single string.
 *
 * Useful for testing or when you want the full output after streaming.
 *
 * @param stream - The inference stream to consume.
 * @returns A promise that resolves to the full concatenated output.
 */
export declare function accumulateStream(stream: InferenceStream): Promise<string>;
export {};
//# sourceMappingURL=stream.d.ts.map