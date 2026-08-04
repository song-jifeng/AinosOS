<?php

declare(strict_types=1);

/**
 * Ainos PHP SDK - Streaming Inference Example
 *
 * This example demonstrates how to use streaming inference with the Ainos client.
 * Streaming allows you to receive tokens one at a time as they are generated,
 * providing a real-time experience.
 *
 * Usage:
 *   export AINOS_TOKEN=your-token-here
 *   php examples/streaming.php
 *
 * Or set the token directly in the script.
 */

// Load the SDK via Composer autoloader
require_once __DIR__ . '/../vendor/autoload.php';

use Ainos\AinosClient;
use Ainos\Authentication;
use Ainos\Parameters;
use Ainos\StreamChunk;
use Ainos\StreamBuffer;
use Ainos\Utils;

// ----------------------------------------------------------------
// 1. Configuration
// ----------------------------------------------------------------

$token = \getenv('AINOS_TOKEN') ?: 'your-token-here';
$host = '127.0.0.1';
$port = 9500;

$auth = new Authentication($token);

$client = new AinosClient(
    $auth,
    $host,
    $port,
    [
        'timeout' => 60.0,
        'chunk_timeout' => 30.0,
        'max_retries' => 2,
    ]
);

// ----------------------------------------------------------------
// 2. Connect
// ----------------------------------------------------------------

echo "Connecting to Ainos server at {$host}:{$port}...\n";

try {
    $client->connect();
    echo "Connected successfully.\n\n";
} catch (\Ainos\ConnectionException $e) {
    echo "Connection failed: {$e->getMessage()}\n";
    exit(1);
}

// ----------------------------------------------------------------
// 3. Basic Streaming Inference
// ----------------------------------------------------------------

echo "--- Basic Streaming Inference ---\n";
echo "Model: gpt-3.5-turbo\n";
echo "Prompt: Write a short poem about artificial intelligence.\n\n";

echo "Response: ";

$fullText = '';
$chunkCount = 0;
$startTime = Utils::microtimeFloat();

try {
    $stream = $client->inferStream(
        'gpt-3.5-turbo',
        'Write a short poem about artificial intelligence.',
        new Parameters(
            temperature: 0.8,
            maxTokens: 200,
            topP: 0.95,
        ),
    );

    foreach ($stream as $chunk) {
        $chunkCount++;

        if ($chunk->isEnd) {
            echo "\n\n[Stream complete]";
            if ($chunk->usage !== null) {
                echo "\nUsage:";
                echo "\n  Prompt Tokens: {$chunk->usage->promptTokens}";
                echo "\n  Completion Tokens: {$chunk->usage->completionTokens}";
                echo "\n  Total Tokens: {$chunk->usage->totalTokens}";
            }
        } else {
            echo $chunk->text;
            $fullText .= $chunk->text;
            \flush(); // Flush output buffer to show text in real-time
        }
    }

    $duration = Utils::microtimeFloat() - $startTime;

    echo "\n\n";
    echo "--- Streaming Stats ---\n";
    echo "Total Chunks: {$chunkCount}\n";
    echo "Total Characters: " . \strlen($fullText) . "\n";
    echo "Duration: " . \round($duration, 3) . "s\n";
    echo "Chars/sec: " . \round(\strlen($fullText) / $duration, 1) . "\n\n";

} catch (\Ainos\StreamingException $e) {
    echo "\n\nStreaming error: {$e->getMessage()}\n\n";
} catch (\Ainos\AinosException $e) {
    echo "\n\nError: {$e->getMessage()}\n\n";
}

// ----------------------------------------------------------------
// 4. Advanced: Using StreamBuffer Directly
// ----------------------------------------------------------------

echo "--- Advanced: StreamBuffer with Callbacks ---\n";

try {
    // Build the request manually for more control
    $requestId = Utils::generateId('adv');
    $model = 'gpt-3.5-turbo';
    $prompt = 'What are the three laws of robotics?';

    $params = [
        'model' => $model,
        'prompt' => $prompt,
        'parameters' => (new Parameters(temperature: 0.5, maxTokens: 150))->toArray(),
        'stream' => true,
        'token' => $token,
    ];

    $request = [
        'method' => 'infer',
        'params' => $params,
        'id' => $requestId,
    ];

    // Send the request
    $client->getTransport()->sendNDJSON($request);
    echo "Request sent (ID: {$requestId}).\n\n";

    // Create a StreamBuffer with callbacks
    $buffer = new StreamBuffer(
        transport: $client->getTransport(),
        requestId: $requestId,
        model: $model,
        options: [
            'chunk_timeout' => 30.0,
            'max_empty_reads' => 10,
        ],
        onChunk: function (StreamChunk $chunk) {
            // This callback is invoked for each chunk
            if (!$chunk->isEnd && $chunk->text !== '') {
                // You could process each chunk here (e.g., update UI)
            }
        },
        onComplete: function () {
            echo "[Stream completed successfully]\n";
        },
        onError: function (\Ainos\StreamingException $e) {
            echo "[Stream error: {$e->getMessage()}]\n";
        },
    );

    // Collect all chunks
    $result = StreamBuffer::collectAll(
        $client->getTransport(),
        $requestId,
        $model,
        ['chunk_timeout' => 30.0]
    );

    echo "Accumulated Text:\n{$result['text']}\n\n";
    echo "Duration: " . \round($result['duration'], 3) . "s\n";
    echo "Chunks: " . \count($result['chunks']) . "\n";

    if ($result['usage'] !== null) {
        echo "Prompt Tokens: {$result['usage']->promptTokens}\n";
        echo "Completion Tokens: {$result['usage']->completionTokens}\n\n";
    }

} catch (\Ainos\AinosException $e) {
    echo "Advanced streaming error: {$e->getMessage()}\n\n";
}

// ----------------------------------------------------------------
// 5. Cleanup
// ----------------------------------------------------------------

echo "Disconnecting...\n";
$client->disconnect();
echo "Done.\n";