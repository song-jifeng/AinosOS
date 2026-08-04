package com.ainos.sdk.models;

/**
 * Exception thrown when authentication with the Ainos daemon fails.
 * <p>
 * This can occur when:
 * <ul>
 *   <li>The provided bearer token is invalid or expired</li>
 *   <li>Authentication is required but no token was provided</li>
 *   <li>The daemon returns an authentication error response</li>
 * </ul>
 */
public class AinosAuthException extends AinosException {

    private static final long serialVersionUID = 1L;

    public AinosAuthException(String message) {
        super(message);
    }

    public AinosAuthException(String message, Throwable cause) {
        super(message, cause);
    }
}