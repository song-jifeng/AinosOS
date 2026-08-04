/**
 * Ainos SDK — TCP transport layer.
 *
 * Manages a TCP socket connection to the Ainos daemon, handles NDJSON
 * (newline-delimited JSON) framing, and provides a clean send/receive
 * interface.  Supports connection pooling via the {@link TransportPool}.
 */
import { EventEmitter } from 'events';
/** Default TCP port for the Ainos daemon. */
export declare const DEFAULT_PORT = 9500;
/** Default host address. */
export declare const DEFAULT_HOST = "127.0.0.1";
/** Configuration for a single transport connection. */
export interface TransportOptions {
    host: string;
    port: number;
    connectTimeout: number;
    readTimeout: number;
    autoReconnect: boolean;
    reconnectDelay: number;
    maxReconnectAttempts: number;
}
/** Events emitted by the {@link TcpTransport}. */
export interface TransportEvents {
    connect: [];
    disconnect: [];
    reconnect: [attempt: number, maxAttempts: number];
    error: [error: Error];
    data: [line: string];
}
/**
 * Low-level TCP transport with NDJSON framing.
 *
 * Manages a single TCP connection to the Ainos daemon.  Incoming data is
 * buffered and split on newline boundaries.  Complete JSON lines are emitted
 * via the `data` event.
 */
export declare class TcpTransport extends EventEmitter {
    private readonly opts;
    private socket;
    private buffer;
    private _connected;
    private _closing;
    private reconnectAttempt;
    private pendingReads;
    constructor(opts?: Partial<TransportOptions>);
    /** Whether the socket is currently connected. */
    get connected(): boolean;
    /** The remote host. */
    get host(): string;
    /** The remote port. */
    get port(): number;
    /**
     * Open a TCP connection to the daemon.
     *
     * @throws {ConnectionError} If the connection cannot be established.
     */
    connect(): Promise<void>;
    /**
     * Close the TCP connection gracefully.
     */
    disconnect(): void;
    /**
     * Send a JSON-serialisable value as a single NDJSON line.
     *
     * @throws {ConnectionError} If the socket is not connected.
     */
    send(payload: unknown): void;
    /**
     * Send a payload and wait for the next complete JSON line response.
     *
     * @param payload - The JSON-serialisable value to send.
     * @param timeoutMs - Optional per-call timeout override.
     * @returns The parsed JSON response line.
     * @throws {ConnectionError} If the socket is not connected.
     * @throws {TimeoutError} If the response does not arrive in time.
     */
    sendAndReceive(payload: unknown, timeoutMs?: number): Promise<string>;
    /**
     * Send a payload and return an async iterable of response lines.
     * Used for streaming responses.
     *
     * @param payload - The JSON-serialisable value to send.
     * @returns An async generator yielding response lines.
     */
    sendAndReceiveLines(payload: unknown): AsyncGenerator<string>;
    /**
     * Wait for the next complete newline-delimited JSON line from the socket.
     */
    private readNextLine;
    /**
     * Try to extract a complete line from the internal buffer.
     */
    private extractLineFromBuffer;
    /**
     * Handle incoming data from the socket.
     */
    private handleData;
    /**
     * Reject all pending reads with the given error.
     */
    private flushPendingReads;
    /**
     * Attempt to reconnect with exponential backoff.
     */
    private attemptReconnect;
    /**
     * Return the current socket or throw.
     */
    private ensureSocket;
}
/**
 * Simple connection pool that reuses a single TCP transport.
 *
 * For most use cases, a single connection to the daemon is sufficient.
 * This pool provides a future extension point for multi-connection scenarios.
 */
export declare class TransportPool {
    private transport;
    private readonly opts;
    constructor(opts?: Partial<TransportOptions>);
    /** Acquire a transport connection. */
    acquire(): Promise<TcpTransport>;
    /** Release (disconnect) the transport. */
    release(): void;
}
//# sourceMappingURL=transport.d.ts.map