package com.ainos.sdk.transport;

import com.ainos.sdk.models.AinosConnectionException;
import com.ainos.sdk.models.AinosTimeoutException;

import java.io.Closeable;
import java.util.Map;

/**
 * Low-level transport abstraction for communicating with the Ainos daemon.
 * <p>
 * Implementations handle the NDJSON (newline-delimited JSON) protocol
 * over a TCP socket. All methods are thread-safe.
 */
public interface TcpTransport extends Closeable {

    /**
     * Opens the connection to the daemon.
     *
     * @throws AinosConnectionException if the connection cannot be established
     * @throws AinosTimeoutException    if the connection times out
     */
    void connect() throws AinosConnectionException, AinosTimeoutException;

    /**
     * Closes the connection and releases all resources.
     * <p>
     * Safe to call multiple times; subsequent calls are no-ops.
     */
    @Override
    void close();

    /**
     * Returns whether the transport is currently connected.
     *
     * @return {@code true} if the socket is open and ready
     */
    boolean isConnected();

    /**
     * Sends a JSON request and reads a single JSON response line.
     * <p>
     * This is a blocking synchronous operation.
     *
     * @param request the request map (will be serialized as JSON with type field)
     * @return the parsed response map
     * @throws AinosConnectionException if the connection is lost
     * @throws AinosTimeoutException    if the read times out
     */
    Map<String, Object> sendAndReceive(Map<String, Object> request)
            throws AinosConnectionException, AinosTimeoutException;

    /**
     * Sends a JSON request and returns a {@link ResponseReader} for
     * reading multiple response lines (used for streaming).
     *
     * @param request the request map
     * @return a ResponseReader for reading response lines
     * @throws AinosConnectionException if the connection is lost
     * @throws AinosTimeoutException    if the initial write times out
     */
    ResponseReader sendAndReadLines(Map<String, Object> request)
            throws AinosConnectionException, AinosTimeoutException;

    /**
     * Returns the remote address this transport is connected to.
     *
     * @return the host:port string
     */
    String getRemoteAddress();

    // -----------------------------------------------------------------------
    // Response reader for streaming
    // -----------------------------------------------------------------------

    /**
     * A reader for consuming multiple NDJSON response lines from a single request.
     * <p>
     * Used for streaming inference responses where the daemon sends multiple
     * chunks over time.
     */
    interface ResponseReader extends Closeable {

        /**
         * Reads the next available response line, blocking if necessary.
         *
         * @return the parsed response map, or {@code null} if the stream is exhausted
         * @throws AinosConnectionException if the connection is lost
         * @throws AinosTimeoutException    if the read times out
         */
        Map<String, Object> readLine() throws AinosConnectionException, AinosTimeoutException;

        /**
         * Returns whether this reader may have more lines to read.
         *
         * @return {@code true} if more lines may be available
         */
        boolean hasMore();

        /**
         * Closes this reader. Once closed, {@link #readLine()} returns {@code null}.
         */
        @Override
        void close();
    }
}