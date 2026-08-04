package com.ainos.sdk.models;

/**
 * Base exception for all Ainos SDK errors.
 * <p>
 * All SDK exceptions extend this class, allowing callers to catch
 * a single type for all Ainos-related errors.
 */
public class AinosException extends Exception {

    private static final long serialVersionUID = 1L;

    /** Optional error code from the daemon. */
    private final int errorCode;

    /**
     * Constructs a new Ainos exception with the specified detail message.
     *
     * @param message the detail message
     */
    public AinosException(String message) {
        super(message);
        this.errorCode = -1;
    }

    /**
     * Constructs a new Ainos exception with the specified detail message and cause.
     *
     * @param message the detail message
     * @param cause   the root cause
     */
    public AinosException(String message, Throwable cause) {
        super(message, cause);
        this.errorCode = -1;
    }

    /**
     * Constructs a new Ainos exception with a daemon error code and message.
     *
     * @param errorCode the numeric error code from the daemon
     * @param message   the detail message
     */
    public AinosException(int errorCode, String message) {
        super(message);
        this.errorCode = errorCode;
    }

    /**
     * Returns the numeric error code from the daemon, or {@code -1} if not set.
     *
     * @return the error code
     */
    public int getErrorCode() {
        return errorCode;
    }
}