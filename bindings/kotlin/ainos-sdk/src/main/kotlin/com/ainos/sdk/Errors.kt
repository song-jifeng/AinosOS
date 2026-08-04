package com.ainos.sdk

/**
 * Base exception for all Ainos SDK errors.
 *
 * All exceptions thrown by the SDK inherit from this sealed class, allowing
 * callers to catch all SDK errors with a single `catch (e: AinosException)` block
 * while still having the ability to handle specific error types individually.
 *
 * ## Hierarchy
 * ```
 * AinosException
 *  +-- ConnectionException    -- TCP connection issues
 *  +-- AuthenticationException -- Bearer token failures
 *  +-- ProtocolException      -- Malformed or unexpected messages
 *  +-- TimeoutException       -- Request timeouts
 *  +-- ApiException           -- Daemon-side API errors
 *  +-- StreamException        -- Streaming errors
 *  +-- ModelException         -- Model operation failures
 *  +-- InvalidStateException  -- API usage in wrong state
 * ```
 */
public sealed class AinosException(
    message: String,
    cause: Throwable? = null
) : Exception(message, cause) {

    /**
     * Thrown when a TCP connection to the Ainos daemon cannot be established
     * or is unexpectedly lost. This can occur during [AinosClient.connect],
     * during a request, or when the underlying socket is closed by the remote end.
     *
     * Possible causes: daemon not running, wrong host/port, network issues,
     * firewall blocking port 9500, or daemon crash.
     */
    public class ConnectionException(
        message: String,
        cause: Throwable? = null
    ) : AinosException(message, cause)

    /**
     * Thrown when authentication with the daemon fails.
     *
     * This typically indicates that the bearer token is invalid, expired,
     * or missing. Call [AuthenticationManager.setToken] to update the token
     * and retry the operation.
     */
    public class AuthenticationException(
        message: String,
        cause: Throwable? = null
    ) : AinosException(message, cause)

    /**
     * Thrown when the daemon responds with an unexpected or malformed message.
     *
     * This can indicate a protocol version mismatch between the SDK and the
     * daemon, or a bug in the daemon implementation. Check the message for
     * details about the specific protocol violation.
     */
    public class ProtocolException(
        message: String,
        cause: Throwable? = null
    ) : AinosException(message, cause)

    /**
     * Thrown when a request exceeds the configured timeout.
     *
     * The timeout is configured via [ClientConfig.requestTimeoutMs].
     * Increase the timeout for long-running operations like large model loads
     * or extended inference requests.
     */
    public class TimeoutException(
        message: String,
        cause: Throwable? = null
    ) : AinosException(message, cause)

    /**
     * Thrown when the daemon returns an API-level error.
     *
     * [code] contains the daemon-specific error code, which can be used
     * for programmatic error handling. The [message] provides a human-readable
     * description of the error.
     *
     * Common error codes:
     * - -1: Unknown error
     * - 1: Invalid request format
     * - 2: Model not found
     * - 3: Model not loaded
     * - 4: Out of memory
     * - 5: Invalid parameters
     * - 6: Authentication required
     * - 7: Authentication failed
     * - 8: Operation not supported
     */
    public class ApiException(
        public val code: Int,
        message: String
    ) : AinosException(message)

    /**
     * Thrown when a streaming inference operation encounters an error.
     *
     * This can occur if the stream is interrupted mid-generation, the
     * daemon crashes during streaming, or a protocol error occurs while
     * receiving stream chunks.
     */
    public class StreamException(
        message: String,
        cause: Throwable? = null
    ) : AinosException(message, cause)

    /**
     * Thrown when a model operation (load, unload, or inference) fails.
     *
     * This wraps daemon-side model errors such as:
     * - Model file not found on disk
     * - Model format not supported by the backend
     * - Insufficient GPU memory to load the model
     * - Model is busy with another request
     * - Model unloading failed due to active sessions
     */
    public class ModelException(
        message: String,
        cause: Throwable? = null
    ) : AinosException(message, cause)

    /**
     * Thrown when an SDK operation is attempted in an invalid state.
     *
     * The most common case is calling [AinosClient.infer] or other API
     * methods before calling [AinosClient.connect]. Call [AinosClient.connect]
     * first and verify [AinosClient.isConnected] before making API calls.
     */
    public class InvalidStateException(
        message: String
    ) : AinosException(message)
}