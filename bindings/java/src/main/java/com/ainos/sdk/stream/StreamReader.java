package com.ainos.sdk.stream;

import com.ainos.sdk.models.*;
import com.ainos.sdk.transport.JsonCodec;
import com.ainos.sdk.transport.TcpTransport;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;
import java.util.Objects;
import java.util.concurrent.TimeUnit;

/**
 * Reads streaming inference chunks from the daemon.
 * <p>
 * Handles the low-level parsing of NDJSON response lines into
 * {@link InferenceChunk} objects. Detects error responses and
 * converts them to exceptions.
 * <p>
 * This class is not thread-safe; callers should coordinate access.
 */
public class StreamReader {

    private static final Logger log = LoggerFactory.getLogger(StreamReader.class);

    private final TcpTransport.ResponseReader responseReader;
    private final JsonCodec codec;
    private volatile boolean exhausted;

    /**
     * Constructs a StreamReader.
     *
     * @param responseReader the underlying response line reader
     * @param codec          the JSON codec for parsing responses
     */
    public StreamReader(TcpTransport.ResponseReader responseReader, JsonCodec codec) {
        this.responseReader = Objects.requireNonNull(responseReader, "responseReader must not be null");
        this.codec = Objects.requireNonNull(codec, "codec must not be null");
        this.exhausted = false;
    }

    /**
     * Reads the next chunk from the stream, blocking indefinitely.
     *
     * @return the next chunk, or {@code null} if the stream is exhausted
     * @throws AinosConnectionException if the connection is lost
     * @throws AinosTimeoutException    if the read times out
     * @throws AinosInferenceException  if the daemon returns an error
     */
    public InferenceChunk readChunk()
            throws AinosConnectionException, AinosTimeoutException, AinosInferenceException {
        if (exhausted) {
            return null;
        }

        Map<String, Object> response = responseReader.readLine();
        if (response == null) {
            exhausted = true;
            return null;
        }

        return parseChunk(response);
    }

    /**
     * Reads the next chunk with a timeout.
     *
     * @param timeout the maximum time to wait
     * @param unit    the time unit
     * @return the next chunk, or {@code null} if exhausted or timed out
     * @throws AinosConnectionException if the connection is lost
     * @throws AinosTimeoutException    if the timeout expires
     * @throws AinosInferenceException  if the daemon returns an error
     */
    public InferenceChunk readChunk(long timeout, TimeUnit unit)
            throws AinosConnectionException, AinosTimeoutException, AinosInferenceException {
        if (exhausted) {
            return null;
        }

        // Note: The underlying transport has its own read timeout via SO_TIMEOUT.
        // For a more precise timeout, we'd need async I/O, but for this SDK
        // we rely on the socket timeout configured on the transport.
        return readChunk();
    }

    /**
     * Closes the reader and releases resources.
     */
    public void close() {
        exhausted = true;
        try {
            responseReader.close();
        } catch (Exception e) {
            log.warn("Error closing StreamReader response reader: {}", e.getMessage());
        }
    }

    // -----------------------------------------------------------------------
    // Internal
    // -----------------------------------------------------------------------

    private InferenceChunk parseChunk(Map<String, Object> response) throws AinosInferenceException {
        String type = JsonCodec.getType(response);

        if ("Error".equals(type)) {
            int code = JsonCodec.getErrorCode(response);
            String message = JsonCodec.getErrorMessage(response);
            throw new AinosInferenceException(code, message);
        }

        if ("InferenceChunk".equals(type)) {
            String chunk = JsonCodec.getString(response, "chunk", "");
            boolean done = JsonCodec.getBoolean(response, "done", false);
            return new InferenceChunk(chunk, done);
        }

        // If we get an InferenceResponse instead of chunks (non-streaming fallback),
        // wrap it as a single final chunk
        if ("InferenceResponse".equals(type)) {
            String output = JsonCodec.getString(response, "output", "");
            return InferenceChunk.finalChunk(output);
        }

        // Unknown response type - treat as error
        log.warn("Unexpected stream response type: {}", type);
        throw new AinosInferenceException("Unexpected stream response type: " + type);
    }
}