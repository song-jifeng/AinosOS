package com.ainos.sdk

import kotlinx.serialization.encodeToJsonElement
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import java.util.UUID
import java.util.concurrent.atomic.AtomicLong

/**
 * Shared [Json] instance configured for communication with the Ainos daemon.
 *
 * Configuration rationale:
 * - [ignoreUnknownKeys] = true: forward-compatible with future daemon versions
 *   that may add new fields to responses.
 * - [isLenient] = true: tolerant of minor formatting variations.
 * - [encodeDefaults] = true: ensures all fields are present in requests,
 *   making the protocol self-documenting.
 * - [coerceInputValues] = true: gracefully handles values that are close to
 *   the expected type (e.g., int where long is expected).
 * - [classDiscriminator] = "#type": avoids collisions with potential "type"
 *   fields in the data model.
 */
public val json: Json = Json {
    prettyPrint = false
    ignoreUnknownKeys = true
    isLenient = true
    encodeDefaults = true
    coerceInputValues = true
    classDiscriminator = "#type"
}

/**
 * Generates a UUID v4 string with hyphens stripped.
 * Example: `"a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"`
 */
public fun uuid(): String = UUID.randomUUID().toString().replace("-", "")

private val requestIdCounter = AtomicLong(0)

/**
 * Generates a monotonically increasing unique request identifier.
 *
 * Format: `ainos-{counter}-{uuid-prefix}` where:
 * - [counter] is a thread-safe atomic increment starting from 1
 * - [uuid-prefix] is the first 8 characters of a UUID v4
 *
 * Example: `"ainos-42-a1b2c3d4"`
 *
 * This format ensures uniqueness across requests even in high-concurrency
 * scenarios, while being human-readable for debugging.
 */
public fun generateRequestId(): String {
    return "ainos-${requestIdCounter.incrementAndGet()}-${uuid().take(8)}"
}

/**
 * Returns the current system time as epoch milliseconds.
 * Used for timestamps in context operations and diagnostics.
 */
internal fun nowMillis(): Long = System.currentTimeMillis()

/**
 * Converts a [kotlinx.serialization.Serializable] object to a [JsonObject].
 *
 * This is a convenience extension that serializes the receiver and casts
 * the result to a [JsonObject]. The receiver must serialize to a JSON
 * object (i.e., be a data class or class annotated with @Serializable).
 *
 * @throws IllegalArgumentException if the serialized form is not a JSON object
 */
internal inline fun <reified T> T.toJsonObject(): JsonObject {
    val element = json.encodeToJsonElement(this)
    return element.jsonObject
}

/**
 * Returns the name of the current thread for diagnostic and logging purposes.
 */
internal fun currentThreadName(): String = Thread.currentThread().name

/**
 * Truncates a string to [maxLen] characters, appending "..." if truncated.
 * Useful for logging long prompts or responses without overwhelming the output.
 *
 * @param maxLen Maximum length before truncation (must be >= 3)
 * @return The original string if within limit, or truncated with "..." suffix
 */
public fun String.truncate(maxLen: Int): String {
    return if (length <= maxLen) this else take(maxLen - 3) + "..."
}

/**
 * Ensures the string is not blank, returning it or throwing [IllegalArgumentException].
 *
 * @param name The parameter name for the error message
 * @return The same string if it is not blank
 * @throws IllegalArgumentException if the string is blank
 */
internal fun String.requireNotBlank(name: String): String {
    require(isNotBlank()) { "$name must not be blank" }
    return this
}

/**
 * Validates that the port number is within the valid range 1-65535.
 *
 * @throws IllegalArgumentException if the port is out of range
 */
internal fun Int.requireValidPort(): Int {
    require(this in 1..65535) { "Port must be between 1 and 65535, got $this" }
    return this
}