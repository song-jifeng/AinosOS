package com.ainos.sdk.transport;

import com.ainos.sdk.models.AinosConnectionException;
import com.ainos.sdk.models.AinosTimeoutException;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.reflect.TypeToken;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.*;
import java.lang.reflect.Type;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.locks.Lock;
import java.util.concurrent.locks.ReentrantLock;

/**
 * TCP transport implementation for the Ainos NDJSON protocol.
 * <p>
 * Manages a single TCP socket connection to the Ainos daemon and handles
 * the newline-delimited JSON wire protocol. All public methods are thread-safe.
 * <p>
 * This implementation is not safe for concurrent streaming operations on
 * the same connection - concurrent {@link #sendAndReceive} or
 * {@link #sendAndReadLines} calls are serialized via an internal lock.
 */
public class TcpTransportImpl implements TcpTransport {

    private static final Logger log = LoggerFactory.getLogger(TcpTransportImpl.class);

    private static final Type MAP_TYPE = new TypeToken<Map<String, Object>>() {}.getType();

    private final String host;
    private final int port;
    private final int connectTimeoutMs;
    private final int readTimeoutMs;
    private final boolean tcpNoDelay;

    private final Gson gson;
    private final Lock lock;

    private Socket socket;
    private BufferedReader reader;
    private BufferedWriter writer;
    private final AtomicBoolean connected;

    /**
     * Constructs a new TCP transport.
     *
     * @param host             the daemon hostname or IP
     * @param port             the daemon TCP port
     * @param connectTimeoutMs connection timeout in milliseconds
     * @param readTimeoutMs    read timeout in milliseconds
     * @param tcpNoDelay       whether to enable TCP_NODELAY
     */
    public TcpTransportImpl(String host, int port, int connectTimeoutMs,
                            int readTimeoutMs, boolean tcpNoDelay) {
        this.host = host;
        this.port = port;
        this.connectTimeoutMs = connectTimeoutMs;
        this.readTimeoutMs = readTimeoutMs;
        this.tcpNoDelay = tcpNoDelay;
        this.gson = new GsonBuilder()
                .setLenient()
                .create();
        this.lock = new ReentrantLock();
        this.connected = new AtomicBoolean(false);
    }

    /**
     * Constructs a new TCP transport with default settings.
     *
     * @param host the daemon hostname
     * @param port the daemon TCP port
     */
    public TcpTransportImpl(String host, int port) {
        this(host, port, 5000, 120000, true);
    }

    @Override
    public void connect() throws AinosConnectionException, AinosTimeoutException {
        lock.lock();
        try {
            if (socket != null && !socket.isClosed()) {
                log.debug("Already connected to {}:{}", host, port);
                return;
            }

            log.info("Connecting to Ainos daemon at {}:{}", host, port);
            Socket newSocket = new Socket();
            try {
                newSocket.setTcpNoDelay(tcpNoDelay);
                newSocket.setKeepAlive(true);
                newSocket.connect(new InetSocketAddress(host, port), connectTimeoutMs);
                newSocket.setSoTimeout(readTimeoutMs);

                this.socket = newSocket;
                this.reader = new BufferedReader(
                        new InputStreamReader(socket.getInputStream(), StandardCharsets.UTF_8));
                this.writer = new BufferedWriter(
                        new OutputStreamWriter(socket.getOutputStream(), StandardCharsets.UTF_8));
                this.connected.set(true);

                log.info("Connected to Ainos daemon at {}:{}", host, port);
            } catch (SocketTimeoutException e) {
                closeQuietly(newSocket);
                throw new AinosTimeoutException(
                        "Connection timed out after " + connectTimeoutMs + "ms to " + host + ":" + port,
                        connectTimeoutMs, e);
            } catch (IOException e) {
                closeQuietly(newSocket);
                throw new AinosConnectionException(
                        "Cannot connect to " + host + ":" + port + " - " + e.getMessage(), e);
            }
        } finally {
            lock.unlock();
        }
    }

    @Override
    public void close() {
        lock.lock();
        try {
            connected.set(false);
            closeQuietly(reader);
            closeQuietly(writer);
            closeQuietly(socket);
            reader = null;
            writer = null;
            socket = null;
            log.info("Disconnected from Ainos daemon at {}:{}", host, port);
        } finally {
            lock.unlock();
        }
    }

    @Override
    public boolean isConnected() {
        lock.lock();
        try {
            return connected.get() && socket != null && !socket.isClosed();
        } finally {
            lock.unlock();
        }
    }

    @Override
    public Map<String, Object> sendAndReceive(Map<String, Object> request)
            throws AinosConnectionException, AinosTimeoutException {
        lock.lock();
        try {
            ensureConnected();

            String json = gson.toJson(request);
            log.trace("Sending: {}", json);
            writeLine(json);
            String response = readLine();
            log.trace("Received: {}", response);

            if (response == null) {
                throw new AinosConnectionException("Connection closed by peer");
            }

            return gson.fromJson(response, MAP_TYPE);
        } catch (AinosConnectionException | AinosTimeoutException e) {
            throw e;
        } catch (IOException e) {
            handleSocketError();
            throw new AinosConnectionException("Connection lost: " + e.getMessage(), e);
        } finally {
            lock.unlock();
        }
    }

    @Override
    public ResponseReader sendAndReadLines(Map<String, Object> request)
            throws AinosConnectionException, AinosTimeoutException {
        lock.lock();
        try {
            ensureConnected();

            String json = gson.toJson(request);
            log.trace("Sending (stream): {}", json);
            writeLine(json);

            // Create a response reader that shares the socket resources
            // The reader uses the same socket but reads independently
            return new StreamResponseReader(socket, reader, readTimeoutMs);
        } catch (AinosConnectionException e) {
            throw e;
        } catch (IOException e) {
            handleSocketError();
            throw new AinosConnectionException("Connection lost: " + e.getMessage(), e);
        } finally {
            lock.unlock();
        }
    }

    @Override
    public String getRemoteAddress() {
        return host + ":" + port;
    }

    // -----------------------------------------------------------------------
    // Internal helpers
    // -----------------------------------------------------------------------

    private void ensureConnected() throws AinosConnectionException {
        if (!connected.get() || socket == null || socket.isClosed()) {
            throw new AinosConnectionException("Not connected to daemon");
        }
    }

    private void writeLine(String line) throws IOException {
        writer.write(line);
        writer.write('\n');
        writer.flush();
    }

    private String readLine() throws IOException, AinosTimeoutException {
        try {
            String line = reader.readLine();
            if (line == null) {
                return null;
            }
            return line;
        } catch (SocketTimeoutException e) {
            throw new AinosTimeoutException(
                    "Read timed out after " + readTimeoutMs + "ms",
                    readTimeoutMs, e);
        }
    }

    private void handleSocketError() {
        connected.set(false);
        closeQuietly(reader);
        closeQuietly(writer);
        closeQuietly(socket);
        reader = null;
        writer = null;
        socket = null;
    }

    private static void closeQuietly(Closeable closeable) {
        if (closeable != null) {
            try {
                closeable.close();
            } catch (IOException ignored) {
                // ignore
            }
        }
    }

    private static void closeQuietly(Socket socket) {
        if (socket != null && !socket.isClosed()) {
            try {
                socket.close();
            } catch (IOException ignored) {
                // ignore
            }
        }
    }

    // -----------------------------------------------------------------------
    // Stream response reader
    // -----------------------------------------------------------------------

    /**
     * A {@link ResponseReader} that reads NDJSON lines from the socket.
     * <p>
     * This reader is not thread-safe; callers should coordinate access.
     */
    static class StreamResponseReader implements ResponseReader {

        private static final Logger log = LoggerFactory.getLogger(StreamResponseReader.class);

        private final Socket socket;
        private final BufferedReader reader;
        private final int readTimeoutMs;
        private final AtomicBoolean closed;
        private final Gson gson;

        StreamResponseReader(Socket socket, BufferedReader reader, int readTimeoutMs) {
            this.socket = socket;
            this.reader = reader;
            this.readTimeoutMs = readTimeoutMs;
            this.closed = new AtomicBoolean(false);
            this.gson = new Gson();
        }

        @Override
        public Map<String, Object> readLine() throws AinosConnectionException, AinosTimeoutException {
            if (closed.get()) {
                return null;
            }

            try {
                String line = reader.readLine();
                if (line == null) {
                    closed.set(true);
                    return null;
                }

                if (line.isEmpty()) {
                    // Skip empty lines
                    return readLine();
                }

                log.trace("Stream received: {}", line);
                return gson.fromJson(line, MAP_TYPE);
            } catch (SocketTimeoutException e) {
                throw new AinosTimeoutException(
                        "Stream read timed out after " + readTimeoutMs + "ms",
                        readTimeoutMs, e);
            } catch (IOException e) {
                closed.set(true);
                throw new AinosConnectionException(
                        "Stream connection lost: " + e.getMessage(), e);
            }
        }

        @Override
        public boolean hasMore() {
            return !closed.get();
        }

        @Override
        public void close() {
            closed.set(true);
            // Note: we do NOT close the underlying socket/reader here
            // because they are owned by the TcpTransportImpl
        }
    }
}