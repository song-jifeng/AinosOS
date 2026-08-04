package com.ainos.sdk.models;

/**
 * Exception thrown when the daemon returns a rate limit error (HTTP 429).
 * <p>
 * Indicates that the client has exceeded the allowed request rate for
 * a particular API category. The {@link #getRetryAfterSeconds()} method
 * provides the suggested wait time before retrying.
 */
public class AinosRateLimitException extends AinosException {

    private static final long serialVersionUID = 1L;

    private final long retryAfterSeconds;

    public AinosRateLimitException(String message) {
        super(message);
        this.retryAfterSeconds = 1;
    }

    public AinosRateLimitException(String message, long retryAfterSeconds) {
        super(message);
        this.retryAfterSeconds = retryAfterSeconds;
    }

    public AinosRateLimitException(String message, long retryAfterSeconds, Throwable cause) {
        super(message, cause);
        this.retryAfterSeconds = retryAfterSeconds;
    }

    /**
     * Returns the number of seconds the client should wait before retrying.
     *
     * @return retry-after duration in seconds
     */
    public long getRetryAfterSeconds() {
        return retryAfterSeconds;
    }
}