package com.ainos.sdk

import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicReference

/**
 * Manages authentication state for the Ainos daemon.
 *
 * Supports Bearer token authentication. The token is sent with every
 * request to the daemon via the `"token"` field in the NDJSON envelope.
 * This class is thread-safe and observable via [AuthListener].
 *
 * ## Usage
 * ```kotlin
 * val auth = AuthenticationManager("my-bearer-token")
 *
 * // Update token at runtime
 * auth.setToken("new-token")
 *
 * // Listen for changes
 * auth.addListener { newToken ->
 *     println("Token updated: $newToken")
 * }
 *
 * // Clear on logout
 * auth.clearToken()
 * ```
 *
 * @param initialToken Optional initial bearer token
 */
public class AuthenticationManager(initialToken: String? = null) {

    private val tokenRef = AtomicReference(initialToken)
    private val listeners = CopyOnWriteArrayList<AuthListener>()

    /**
     * The current bearer token, or `null` if not authenticated.
     */
    public val token: String?
        get() = tokenRef.get()

    /**
     * Whether a non-blank bearer token is currently set.
     */
    public val isAuthenticated: Boolean
        get() = !tokenRef.get().isNullOrBlank()

    /**
     * Sets a new bearer token and notifies all registered listeners.
     *
     * @param token The new bearer token (must not be blank)
     * @throws IllegalArgumentException if [token] is blank
     */
    public fun setToken(token: String) {
        require(token.isNotBlank()) { "Token must not be blank" }
        val old = tokenRef.getAndSet(token)
        if (old != token) {
            listeners.forEach { listener ->
                try {
                    listener.onTokenChanged(token)
                } catch (_: Exception) {
                    // Swallow listener exceptions to prevent cascading failures
                }
            }
        }
    }

    /**
     * Clears the current bearer token and notifies all registered listeners.
     *
     * After calling this method, [isAuthenticated] returns `false` and
     * requests will be sent without a token. This is useful for logout
     * or token expiry scenarios.
     */
    public fun clearToken() {
        val old = tokenRef.getAndSet(null)
        if (old != null) {
            listeners.forEach { listener ->
                try {
                    listener.onTokenCleared()
                } catch (_: Exception) {
                    // Swallow listener exceptions
                }
            }
        }
    }

    /**
     * Returns the HTTP Authorization header value, or `null` if no token is set.
     * Format: `"Bearer <token>"`
     */
    public fun authorizationHeader(): String? {
        return tokenRef.get()?.let { "Bearer $it" }
    }

    /**
     * Registers a listener that will be notified of authentication state changes.
     *
     * @param listener The listener to register
     */
    public fun addListener(listener: AuthListener) {
        listeners.add(listener)
    }

    /**
     * Removes a previously registered listener.
     *
     * @param listener The listener to remove
     */
    public fun removeListener(listener: AuthListener) {
        listeners.remove(listener)
    }

    /**
     * Creates a copy of this manager with the same current token.
     * The copy has no listeners attached.
     */
    public fun copy(): AuthenticationManager {
        return AuthenticationManager(tokenRef.get())
    }

    /**
     * Returns a string representation of the authentication state.
     * The token value is masked for security.
     */
    override fun toString(): String {
        val tokenStr = tokenRef.get()
        return if (tokenStr != null) {
            "AuthenticationManager(token=${tokenStr.take(4)}...${tokenStr.takeLast(4)})"
        } else {
            "AuthenticationManager(token=null)"
        }
    }
}

/**
 * Functional interface for listening to authentication state changes.
 *
 * Implementations can override either or both methods. [onTokenCleared]
 * has a default no-op implementation.
 */
public fun interface AuthListener {

    /**
     * Called when the bearer token changes to a new value.
     *
     * @param newToken The new bearer token
     */
    public fun onTokenChanged(newToken: String)

    /**
     * Called when the token is cleared (i.e., the user logs out).
     * Default implementation does nothing.
     */
    public fun onTokenCleared() {
        // Default no-op
    }
}