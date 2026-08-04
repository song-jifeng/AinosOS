"use strict";
/**
 * Ainos SDK — TCP transport layer.
 *
 * Manages a TCP socket connection to the Ainos daemon, handles NDJSON
 * (newline-delimited JSON) framing, and provides a clean send/receive
 * interface.  Supports connection pooling via the {@link TransportPool}.
 */
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.TransportPool = exports.TcpTransport = exports.DEFAULT_HOST = exports.DEFAULT_PORT = void 0;
const net = __importStar(require("net"));
const events_1 = require("events");
const errors_1 = require("./errors");
const utils_1 = require("./utils");
// ============================================================================
// Constants
// ============================================================================
/** Default TCP port for the Ainos daemon. */
exports.DEFAULT_PORT = 9500;
/** Default host address. */
exports.DEFAULT_HOST = '127.0.0.1';
/** Maximum line length to prevent OOM on malformed input. */
const MAX_LINE_LENGTH = 1024 * 1024; // 1 MB
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
class TcpTransport extends events_1.EventEmitter {
    opts;
    socket = null;
    buffer = Buffer.alloc(0);
    _connected = false;
    _closing = false;
    reconnectAttempt = 0;
    pendingReads = [];
    // Track the number of active listeners to prevent MaxListenersExceededWarning
    constructor(opts = {}) {
        super();
        this.setMaxListeners(100);
        this.opts = {
            host: opts.host ?? exports.DEFAULT_HOST,
            port: opts.port ?? exports.DEFAULT_PORT,
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
    get connected() {
        return this._connected && this.socket !== null;
    }
    /** The remote host. */
    get host() {
        return this.opts.host;
    }
    /** The remote port. */
    get port() {
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
    connect() {
        if (this._connected && this.socket) {
            return Promise.resolve();
        }
        this._closing = false;
        return new Promise((resolve, reject) => {
            const sock = new net.Socket();
            sock.setNoDelay(true);
            const timer = setTimeout(() => {
                sock.destroy();
                reject(new errors_1.ConnectionError(`Connection timeout after ${this.opts.connectTimeout}ms ` +
                    `to ${this.opts.host}:${this.opts.port}`));
            }, this.opts.connectTimeout);
            sock.on('connect', () => {
                clearTimeout(timer);
                this.socket = sock;
                this._connected = true;
                this.reconnectAttempt = 0;
                this.emit('connect');
                resolve();
            });
            sock.on('data', (data) => {
                this.handleData(data);
            });
            sock.on('close', (_hadError) => {
                clearTimeout(timer);
                this._connected = false;
                this.socket = null;
                this.emit('disconnect');
                this.flushPendingReads(new errors_1.ConnectionError('Connection closed by peer'));
                this.attemptReconnect();
            });
            sock.on('error', (err) => {
                clearTimeout(timer);
                // Only reject if we haven't connected yet
                if (!this._connected) {
                    reject(new errors_1.ConnectionError(`Cannot connect to ${this.opts.host}:${this.opts.port} — ${err.message}`));
                }
                else {
                    this.emit('error', err);
                }
            });
            sock.connect(this.opts.port, this.opts.host);
        });
    }
    /**
     * Close the TCP connection gracefully.
     */
    disconnect() {
        this._closing = true;
        if (this.socket) {
            this.socket.end();
            this.socket.destroy();
            this.socket = null;
        }
        this._connected = false;
        this.flushPendingReads(new errors_1.ConnectionError('Client disconnected'));
    }
    // --------------------------------------------------------------------------
    // Send / Receive
    // --------------------------------------------------------------------------
    /**
     * Send a JSON-serialisable value as a single NDJSON line.
     *
     * @throws {ConnectionError} If the socket is not connected.
     */
    send(payload) {
        const sock = this.ensureSocket();
        const json = (0, utils_1.encodeJson)(payload) + '\n';
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
    async sendAndReceive(payload, timeoutMs) {
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
    async *sendAndReceiveLines(payload) {
        this.send(payload);
        while (true) {
            const line = await this.readNextLine(this.opts.readTimeout);
            yield line;
            // Check if the line is a terminal message
            const parsed = (0, utils_1.decodeJson)(line);
            if (parsed) {
                const type = parsed.type;
                // InferenceChunk with done:true is terminal
                if (type === 'InferenceChunk') {
                    const full = (0, utils_1.decodeJson)(line);
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
    readNextLine(timeoutMs) {
        // Check if we already have a complete line in the buffer
        const line = this.extractLineFromBuffer();
        if (line !== undefined) {
            return Promise.resolve(line);
        }
        // Queue a pending read
        const { promise, resolve, reject } = (0, utils_1.defer)();
        const timer = setTimeout(() => {
            const idx = this.pendingReads.findIndex((pr) => pr.resolve === resolve);
            if (idx !== -1) {
                this.pendingReads.splice(idx, 1);
                reject(new errors_1.TimeoutError('readNextLine', timeoutMs));
            }
        }, timeoutMs);
        this.pendingReads.push({ promise, resolve, reject, timer });
        return promise;
    }
    /**
     * Try to extract a complete line from the internal buffer.
     */
    extractLineFromBuffer() {
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
    handleData(data) {
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
                const pending = this.pendingReads.shift();
                clearTimeout(pending.timer);
                pending.resolve(trimmed);
            }
            else {
                // No pending read — emit as a data event
                this.emit('data', trimmed);
            }
        }
    }
    /**
     * Reject all pending reads with the given error.
     */
    flushPendingReads(err) {
        while (this.pendingReads.length > 0) {
            const pending = this.pendingReads.shift();
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
    attemptReconnect() {
        if (this._closing || !this.opts.autoReconnect) {
            return;
        }
        if (this.opts.maxReconnectAttempts > 0 &&
            this.reconnectAttempt >= this.opts.maxReconnectAttempts) {
            this.emit('error', new errors_1.ConnectionError(`Max reconnect attempts (${this.opts.maxReconnectAttempts}) reached`));
            return;
        }
        this.reconnectAttempt += 1;
        const delay = (0, utils_1.calculateBackoff)(this.reconnectAttempt - 1, this.opts.reconnectDelay);
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
    ensureSocket() {
        if (!this._connected || !this.socket) {
            throw new errors_1.ConnectionError('Not connected to daemon');
        }
        return this.socket;
    }
}
exports.TcpTransport = TcpTransport;
// ============================================================================
// Transport Pool
// ============================================================================
/**
 * Simple connection pool that reuses a single TCP transport.
 *
 * For most use cases, a single connection to the daemon is sufficient.
 * This pool provides a future extension point for multi-connection scenarios.
 */
class TransportPool {
    transport = null;
    opts;
    constructor(opts = {}) {
        this.opts = {
            host: opts.host ?? exports.DEFAULT_HOST,
            port: opts.port ?? exports.DEFAULT_PORT,
            connectTimeout: opts.connectTimeout ?? 5000,
            readTimeout: opts.readTimeout ?? 120000,
            autoReconnect: opts.autoReconnect ?? true,
            reconnectDelay: opts.reconnectDelay ?? 1000,
            maxReconnectAttempts: opts.maxReconnectAttempts ?? 5,
        };
    }
    /** Acquire a transport connection. */
    async acquire() {
        if (this.transport && this.transport.connected) {
            return this.transport;
        }
        this.transport = new TcpTransport(this.opts);
        await this.transport.connect();
        return this.transport;
    }
    /** Release (disconnect) the transport. */
    release() {
        if (this.transport) {
            this.transport.disconnect();
            this.transport = null;
        }
    }
}
exports.TransportPool = TransportPool;
//# sourceMappingURL=transport.js.map