package com.ainos.sdk

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.ClosedReceiveChannelException
import kotlinx.coroutines.channels.ReceiveChannel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.awaitClose
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.launch
import kotlinx.serialization.decodeFromJsonElement
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * Utility functions for working with streaming inference responses.
 *
 * The streaming system uses Kotlin [Flow] to represent token-by-token
 * generation. Flows are cold, meaning the stream is not initiated until
 * a terminal operator (e.g., [collect], [toList]) is called. They are
 also cancellable: cancelling the coroutine that collects the flow will
 * close the underlying TCP stream channel.
 *
 * ## Basic Usage
 * ```kotlin
 * val flow: Flow<StreamChunk> = client.inferStream("Tell me a story")
 *
 * flow.collect { chunk ->
 *     print(chunk.text)
 *     if (chunk.finished) {
 *         println("\n[Done: ${chunk.finishReason}]")
 *     }
 * }
 * ```
 *
 * ## Text Concatenation
 * ```kotlin
 * val fullText = Streaming.collectText(flow)
 * ```
 */
public object Streaming {

    /**
     * Converts a raw [ReceiveChannel] of [JsonElement] into a typed [Flow] of [StreamChunk].
     *
     * The channel is expected to produce JSON elements with the following structure:
     * - `{"text": "Hello", "index": 0, "finished": false}` — intermediate chunk
     * - `{"text": " world", "index": 1, "finished": true, "finish_reason": "stop"}` — final chunk
     *
     * The flow will:
     * - Emit a [StreamChunk] for each element received from the channel
     * - Complete when a chunk with `finished = true` or a `stream_end` signal is received
     * - Throw [AinosException.StreamException] if the channel closes with an error
     * - Cancel the underlying channel when the flow collection is cancelled
     *
     * @param channel The raw channel from [Transport.requestStream] or [AinosClient.rawRequestStream]
     * @return A flow that emits [StreamChunk] objects
     */
    public fun fromChannel(channel: ReceiveChannel<JsonElement>): Flow<StreamChunk> = callbackFlow {
        val job = launch {
            try {
                for (element in channel) {
                    val chunk = parseChunk(element)
                    trySend(chunk)
                    if (chunk.finished) break
                }
            } catch (e: ClosedReceiveChannelException) {
                // Channel closed normally, stream is complete
            } catch (e: Exception) {
                throw AinosException.StreamException(
                    "Stream error while receiving chunks: ${e.message}", e
                )
            } finally {
                channel.cancel()
            }
        }

        awaitClose {
            job.cancel()
            channel.cancel()
        }
    }.flowOn(Dispatchers.IO)

    /**
     * Collects a streaming flow and concatenates all text chunks into a single string.
     *
     * This is a convenience method for non-streaming consumption of streaming data.
     *
     * @param flow The streaming flow to collect
     * @return The complete generated text
     */
    public suspend fun collectText(flow: Flow<StreamChunk>): String {
        val sb = StringBuilder()
        flow.collect { chunk ->
            sb.append(chunk.text)
        }
        return sb.toString()
    }

    /**
     * Collects a streaming flow, invoking [onChunk] for each chunk, and returns
     * the concatenated text.
     *
     * This is useful for scenarios where you want both the full text and
     * per-chunk processing (e.g., updating a UI element with each token).
     *
     * @param flow The streaming flow to collect
     * @param onChunk Callback invoked for each [StreamChunk] as it arrives
     * @return The complete generated text
     */
    public suspend fun collectWithCallback(
        flow: Flow<StreamChunk>,
        onChunk: (StreamChunk) -> Unit
    ): String {
        val sb = StringBuilder()
        flow.collect { chunk ->
            sb.append(chunk.text)
            onChunk(chunk)
        }
        return sb.toString()
    }

    /**
     * Converts a flow of [StreamChunk] into a flow of raw text strings.
     *
     * Empty text chunks are filtered out. This is useful for line-by-line
     * processing of the generated text.
     *
     * ```kotlin
     * client.inferStream("Write a poem")
     *     .textOnly()
     *     .collect { text -> println("Received: $text") }
     * ```
     */
    public fun Flow<StreamChunk>.textOnly(): Flow<String> = flow {
        collect { chunk ->
            if (chunk.text.isNotEmpty()) {
                emit(chunk.text)
            }
        }
    }

    /**
     * Collects a streaming flow, printing each chunk's text to stdout in real-time,
     * and returns the concatenated text.
     *
     * This is useful for CLI applications and demos where you want to show
     * the generation as it happens.
     *
     * @return The complete generated text
     */
    public suspend fun Flow<StreamChunk>.printCollected(): String {
        val sb = StringBuilder()
        collect { chunk ->
            val text = chunk.text
            sb.append(text)
            print(text)
            System.out.flush()
        }
        println()
        return sb.toString()
    }

    /**
     * Accumulates a streaming flow into a list of chunks.
     *
     * @return List of all [StreamChunk] objects emitted by the flow
     */
    public suspend fun Flow<StreamChunk>.toChunkList(): List<StreamChunk> {
        val chunks = mutableListOf<StreamChunk>()
        collect { chunks.add(it) }
        return chunks
    }

    /**
     * Returns a flow that emits only the final chunk (with [StreamChunk.finished] = true).
     * If the stream completes without a finished chunk, the flow emits nothing.
     */
    public fun Flow<StreamChunk>.finalChunk(): Flow<StreamChunk> = flow {
        var last: StreamChunk? = null
        collect { chunk ->
            if (chunk.finished) {
                last = chunk
            }
        }
        last?.let { emit(it) }
    }

    /**
     * Parses a [JsonElement] into a [StreamChunk].
     *
     * First attempts typed deserialization via [json.decodeFromJsonElement].
     * Falls back to manual field extraction for robustness against schema
     * variations from different daemon versions.
     */
    private fun parseChunk(element: JsonElement): StreamChunk {
        return try {
            json.decodeFromJsonElement(element)
        } catch (e: Exception) {
            // Fallback: extract fields manually from raw JSON object
            val obj = element.jsonObject
            StreamChunk(
                text = obj["text"]?.jsonPrimitive?.contentOrNull ?: "",
                index = obj["index"]?.jsonPrimitive?.intOrNull ?: 0,
                finished = obj["finished"]?.jsonPrimitive?.booleanOrNull ?: false,
                finishReason = obj["finish_reason"]?.jsonPrimitive?.contentOrNull,
                tokens = obj["tokens"]?.jsonPrimitive?.intOrNull,
                tokensPerSecond = obj["tokens_per_second"]?.jsonPrimitive?.floatOrNull
            )
        }
    }
}