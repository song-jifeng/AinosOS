package com.ainos.sdk.models;

/**
 * Exception thrown when the SDK cannot establish or maintain a connection
 * to the Ainos daemon.
 * <p>
 * This can occur during initial connection, after a socket timeout,
 * or when the remote end closes the connection unexpectedly.
 */
public class AinosConnectionException extends AinosException {

    private static final long serialVersionUID = 1L;

    public AinosConnectionException(String message) {
        super(message);
    }

    public AinosConnectionException(String message, Throwable cause) {
        super(message, cause);
    }
}