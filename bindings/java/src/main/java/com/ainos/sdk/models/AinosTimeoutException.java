package com.ainos.sdk.models;

/**
 * Exception thrown when an operation exceeds the configured timeout.
 * <p>
 * This can occur during connection establishment, socket reads,
 * or long-running operations like inference.
 */
public class AinosTimeoutException extends AinosException {

    private static final long serialVersionUID = 1L;

    private final long timeoutMillis;

    public AinosTimeoutException(String message) {
        super(message);
        this.timeoutMillis = 0;
    }

    public AinosTimeoutException(String message, long timeoutMillis) {
        super(message);
        this.timeoutMillis = timeoutMillis;
    }

    public AinosTimeoutException(String message, long timeoutMillis, Throwable cause) {
        super(message, cause);
        this.timeoutMillis = timeoutMillis;
    }

    /**
     * Returns the timeout duration in milliseconds that was exceeded.
     *
     * @return the timeout in milliseconds, or 0 if unknown
     */
    public long getTimeoutMillis() {
        return timeoutMillis;
    }
}