package com.ainos.sdk.models;

/**
 * Exception thrown when an inference request fails.
 * <p>
 * This can occur when the daemon returns an error response for an
 * inference operation, such as when the model is not loaded, the
 * prompt is invalid, or the backend encounters an error.
 */
public class AinosInferenceException extends AinosException {

    private static final long serialVersionUID = 1L;

    public AinosInferenceException(String message) {
        super(message);
    }

    public AinosInferenceException(String message, Throwable cause) {
        super(message, cause);
    }

    public AinosInferenceException(int errorCode, String message) {
        super(errorCode, message);
    }
}