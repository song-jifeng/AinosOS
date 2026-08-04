/**
 * Ainos SDK — TCP transport layer.
 *
 * Manages a TCP socket connection to the Ainos daemon, handles NDJSON
 * (newline-delimited JSON) framing, and provides a clean send/receive
 * interface.  Supports connection pooling via the {@link TransportPool}.
 */

import * as net from 'net';
import { EventEmitter } from 'events';
import { ConnectionError, TimeoutError } from './errors';
import { encodeJson, decodeJson, defer, calculateBackoff } from './utils';

// ============================================================================
// Constants
// ============================================================================

/** Default TCP port for the Ainos daemon. */
export const DEFAULT_PORT = 9500;

/** Default host address. */
export const DEFAULT_HOST = '127.0.0.1';

/** Maximum line length to prevent OOM on malformed input. */
const MAX_LINE_LENGTH = 1024 * 1024; // 1 MB

// ============================================================================
// Transport Options
// ============================================================================

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

// ============================================================================
// Transport Events
// ============================================================================

/** Events emitted by the {@link TcpTransport}. */
export interface TransportEvents {
  connect: [];
  disconnect: [];
  reconnect: [attempt: number, maxAttempts: number];
  error: [error: Error];
  data: [line: string];
}

// ============================================================================
// TcpTransport
// ============================================================================

/**
 * Low-level TCP transport with NDJSON framing.
 *
 * Manages a single TCP connection to the Ainos daemon.  Incoming data is
 * buffered and split on newline boundaries.  Complete JSON lines are emitted
 * via the `data` event.
 */
export class TcpTransport extends EventEmitter {
  private readonly opts: TransportOptions;
  private socket: net.Socket | null = null;
  private buffer: Buffer = Buffer.alloc(0);
  private _connected = false;
  private _closing = false;
  private reconnectAttempt = 0;
  private pendingReads: Array<{
    promise: Promise<string>;
    resolve: (line: string) => void;
    reject: (err: Error) => void;
    timer: ReturnType<typeof setTimeout> | undefined;
  }> = [];

  // Track the number of active listeners to prevent MaxListenersExceededWarning

  constructor(opts: Partial<TransportOptions> = {}) {
    super();
    this.setMaxListeners(100);
    this.opts = {
      host: opts.host ?? DEFAULT_HOST,
      port: opts.port ?? DEFAULT_PORT,
      connectTimeout: opts.connectTimeout ?? 5000,
      readTimeout: opts.readTimeout ?? 120000,
      autoReconnect: opts.autoReconnect ?? true,
      reconnectDelay: opts.reconnectDelay ?? 1000,
      maxReconnectAttempts: opts.maxReconnectAttempts ?? 5,
    };
  }

  // --------------------------------------------------------------------------
  // Properties
  // --------------------------------------------------------------------------

  /** Whether the socket is currently connected. */
  get connected(): boolean {
    return this._connected && this.socket !== null;
  }

  /** The remote host. */
  get host(): string {
    return this.opts.host;
  }

  /** The remote port. */
  get port(): number {
    return this.opts.port;
  }

  // --------------------------------------------------------------------------
  // Connection Management
  // --------------------------------------------------------------------------

  /**
   * Open a TCP connection to the daemon.
   *
   * @throws {ConnectionError} If the connection cannot be established.
   */
  connect(): Promise<void> {
    if (this._connected && this.socket) {
      return Promise.resolve();
    }

    this._closing = false;

    return new Promise<void>((resolve, reject) => {
      const sock = new net.Socket();
      sock.setNoDelay(true);

      const timer = setTimeout(() => {
        sock.destroy();
        reject(new ConnectionError(
          `Connection timeout after ${this.opts.connectTimeout}ms ` +
          `to ${this.opts.host}:${this.opts.port}`,
        ));
      }, this.opts.connectTimeout);

      sock.on('connect', () => {
        clearTimeout(timer);
        this.socket = sock;
        this._connected = true;
        this.reconnectAttempt = 0;
        this.emit('connect');
        resolve();
      });

      sock.on('data', (data: Buffer) => {
        this.handleData(data);
      });

      sock.on('close', (_hadError: boolean) => {
        clearTimeout(timer);
        this._connected = false;
        this.socket = null;
        this.emit('disconnect');
        this.flushPendingReads(new ConnectionError('Connection closed by peer'));
        this.attemptReconnect();
      });

      sock.on('error', (err: Error) => {
        clearTimeout(timer);
        // Only reject if we haven't connected yet
        if (!this._connected) {
          reject(new ConnectionError(
            `Cannot connect to ${this.opts.host}:${this.opts.port} — ${err.message}`,
          ));
        } else {
          this.emit('error', err);
        }
      });

      sock.connect(this.opts.port, this.opts.host);
    });
  }

  /**
   * Close the TCP connection gracefully.
   */
  disconnect(): void {
    this._closing = true;
    if (this.socket) {
      this.socket.end();
      this.socket.destroy();
      this.socket = null;
    }
    this._connected = false;
    this.flushPendingReads(new ConnectionError('Client disconnected'));
  }

  // --------------------------------------------------------------------------
  // Send / Receive
  // --------------------------------------------------------------------------

  /**
   * Send a JSON-serialisable value as a single NDJSON line.
   *
   * @throws {ConnectionError} If the socket is not connected.
   */
  send(payload: unknown): void {
    const sock = this.ensureSocket();
    const json = encodeJson(payload) + '\n';
    sock.write(json);
  }

  /**
   * Send a payload and wait for the next complete JSON line response.
   *
   * @param payload - The JSON-serialisable value to send.
   * @param timeoutMs - Optional per-call timeout override.
   * @returns The parsed JSON response line.
   * @throws {ConnectionError} If the socket is not connected.
   * @throws {TimeoutError} If the response does not arrive in time.
   */
  async sendAndReceive(payload: unknown, timeoutMs?: number): Promise<string> {
    const timeout = timeoutMs ?? this.opts.readTimeout;

    this.send(payload);

    return this.readNextLine(timeout);
  }

  /**
   * Send a payload and return an async iterable of response lines.
   * Used for streaming responses.
   *
   * @param payload - The JSON-serialisable value to send.
   * @returns An async generator yielding response lines.
   */
  async *sendAndReceiveLines(payload: unknown): AsyncGenerator<string> {
    this.send(payload);

    while (true) {
      const line = await this.readNextLine(this.opts.readTimeout);
      yield line;

      // Check if the line is a terminal message
      const parsed = decodeJson<{ type: string }>(line);
      if (parsed) {
        const type = parsed.type;
        // InferenceChunk with done:true is terminal
        if (type === 'InferenceChunk') {
          const full = decodeJson<{ done: boolean }>(line);
          if (full && full.done) {
            break;
          }
        }
        // Error responses are also terminal
        if (type === 'Error') {
          break;
        }
      }
    }
  }

  // --------------------------------------------------------------------------
  // Internal: Read Buffer Management
  // --------------------------------------------------------------------------

  /**
   * Wait for the next complete newline-delimited JSON line from the socket.
   */
  private readNextLine(timeoutMs: number): Promise<string> {
    // Check if we already have a complete line in the buffer
    const line = this.extractLineFromBuffer();
    if (line !== undefined) {
      return Promise.resolve(line);
    }

    // Queue a pending read
    const { promise, resolve, reject } = defer<string>();

    const timer = setTimeout(() => {
      const idx = this.pendingReads.findIndex((pr) => pr.resolve === resolve);
      if (idx !== -1) {
        this.pendingReads.splice(idx, 1);
        reject(new TimeoutError('readNextLine', timeoutMs));
      }
    }, timeoutMs);

    this.pendingReads.push({ promise, resolve, reject, timer });

    return promise;
  }

  /**
   * Try to extract a complete line from the internal buffer.
   */
  private extractLineFromBuffer(): string | undefined {
    const newlineIdx = this.buffer.indexOf(0x0a); // '\n'
    if (newlineIdx === -1) {
      return undefined;
    }

    // Check for buffer overflow
    if (newlineIdx > MAX_LINE_LENGTH) {
      // Line too long — discard it and advance past the newline
      this.buffer = this.buffer.subarray(newlineIdx + 1);
      return undefined;
    }

    const line = this.buffer.subarray(0, newlineIdx).toString('utf-8');
    this.buffer = this.buffer.subarray(newlineIdx + 1);
    return line;
  }

  /**
   * Handle incoming data from the socket.
   */
  private handleData(data: Buffer): void {
    // Append to the internal buffer
    this.buffer = Buffer.concat([this.buffer, data]);

    // Extract and dispatch as many complete lines as possible
    while (true) {
      const line = this.extractLineFromBuffer();
      if (line === undefined) {
        break;
      }

      const trimmed = line.trim();
      if (trimmed.length === 0) {
        continue;
      }

      // Dispatch to pending reads first
      if (this.pendingReads.length > 0) {
        const pending = this.pendingReads.shift()!;
        clearTimeout(pending.timer);
        pending.resolve(trimmed);
      } else {
        // No pending read — emit as a data event
        this.emit('data', trimmed);
      }
    }
  }

  /**
   * Reject all pending reads with the given error.
   */
  private flushPendingReads(err: Error): void {
    while (this.pendingReads.length > 0) {
      const pending = this.pendingReads.shift()!;
      clearTimeout(pending.timer);
      pending.reject(err);
    }
  }

  // --------------------------------------------------------------------------
  // Internal: Reconnection
  // --------------------------------------------------------------------------

  /**
   * Attempt to reconnect with exponential backoff.
   */
  private attemptReconnect(): void {
    if (this._closing || !this.opts.autoReconnect) {
      return;
    }

    if (
      this.opts.maxReconnectAttempts > 0 &&
      this.reconnectAttempt >= this.opts.maxReconnectAttempts
    ) {
      this.emit('error', new ConnectionError(
        `Max reconnect attempts (${this.opts.maxReconnectAttempts}) reached`,
      ));
      return;
    }

    this.reconnectAttempt += 1;
    const delay = calculateBackoff(
      this.reconnectAttempt - 1,
      this.opts.reconnectDelay,
    );

    this.emit('reconnect', this.reconnectAttempt, this.opts.maxReconnectAttempts);

    setTimeout(() => {
      if (!this._closing) {
        this.connect().catch((err) => {
          this.emit('error', err);
        });
      }
    }, delay);
  }

  // --------------------------------------------------------------------------
  // Internal: Socket Guard
  // --------------------------------------------------------------------------

  /**
   * Return the current socket or throw.
   */
  private ensureSocket(): net.Socket {
    if (!this._connected || !this.socket) {
      throw new ConnectionError('Not connected to daemon');
    }
    return this.socket;
  }
}

// ============================================================================
// Transport Pool
// ============================================================================

/**
 * Simple connection pool that reuses a single TCP transport.
 *
 * For most use cases, a single connection to the daemon is sufficient.
 * This pool provides a future extension point for multi-connection scenarios.
 */
export class TransportPool {
  private transport: TcpTransport | null = null;
  private readonly opts: TransportOptions;

  constructor(opts: Partial<TransportOptions> = {}) {
    this.opts = {
      host: opts.host ?? DEFAULT_HOST,
      port: opts.port ?? DEFAULT_PORT,
      connectTimeout: opts.connectTimeout ?? 5000,
      readTimeout: opts.readTimeout ?? 120000,
      autoReconnect: opts.autoReconnect ?? true,
      reconnectDelay: opts.reconnectDelay ?? 1000,
      maxReconnectAttempts: opts.maxReconnectAttempts ?? 5,
    };
  }

  /** Acquire a transport connection. */
  async acquire(): Promise<TcpTransport> {
    if (this.transport && this.transport.connected) {
      return this.transport;
    }
    this.transport = new TcpTransport(this.opts);
    await this.transport.connect();
    return this.transport;
  }

  /** Release (disconnect) the transport. */
  release(): void {
    if (this.transport) {
      this.transport.disconnect();
      this.transport = null;
    }
  }
}