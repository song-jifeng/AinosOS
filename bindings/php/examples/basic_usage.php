<?php

declare(strict_types=1);

/**
 * Ainos PHP SDK - Basic Usage Example
 *
 * This example demonstrates the basic usage of the Ainos client:
 * - Connecting to the server
 * - Checking health and status
 * - Listing available models
 * - Performing synchronous inference
 * - Managing context
 * - Disconnecting
 *
 * Usage:
 *   export AINOS_TOKEN=your-token-here
 *   php examples/basic_usage.php
 *
 * Or set the token directly in the script.
 */

// Load the SDK via Composer autoloader
require_once __DIR__ . '/../vendor/autoload.php';

use Ainos\AinosClient;
use Ainos\Authentication;
use Ainos\Parameters;
use Ainos\Utils;

// ----------------------------------------------------------------
// 1. Configuration
// ----------------------------------------------------------------

// Option A: Configure from environment variables
// $client = AinosClient::fromEnvironment();

// Option B: Configure directly
$token = \getenv('AINOS_TOKEN') ?: 'your-token-here';
$host = '127.0.0.1';
$port = 9500;

$auth = new Authentication($token);

$client = new AinosClient(
    $auth,
    $host,
    $port,
    [
        'timeout' => 30.0,
        'max_retries' => 3,
        'retry_delay' => 1.0,
    ]
);

// ----------------------------------------------------------------
// 2. Connection
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
// 3. Server Health
// ----------------------------------------------------------------

echo "--- Server Health ---\n";

try {
    $health = $client->health();

    echo "Status: {$health->status}\n";
    echo "Version: {$health->version}\n";
    echo "Uptime: {$health->getUptimeFormatted()}\n";
    echo "Active Connections: {$health->activeConnections}\n";
    echo "Healthy: " . ($health->isHealthy() ? 'Yes' : 'No') . "\n\n";
} catch (\Ainos\AinosException $e) {
    echo "Health check failed: {$e->getMessage()}\n\n";
}

// ----------------------------------------------------------------
// 4. Server Status
// ----------------------------------------------------------------

echo "--- Server Status ---\n";

try {
    $status = $client->status();

    echo "Version: {$status->version}\n";
    echo "Uptime: {$status->uptime} seconds\n";
    echo "Total Requests: {$status->totalRequests}\n";
    echo "Active Models: " . \implode(', ', $status->activeModels) . "\n";
    echo "Active Connections: {$status->activeConnections}\n\n";
} catch (\Ainos\AinosException $e) {
    echo "Status check failed: {$e->getMessage()}\n\n";
}

// ----------------------------------------------------------------
// 5. Model List
// ----------------------------------------------------------------

echo "--- Available Models ---\n";

try {
    $models = $client->modelList();

    echo "Total Models: {$models->total}\n";
    echo "Loaded Models: {$models->loadedCount}\n";
    echo "Total Size: " . Utils::formatBytes($models->totalSize) . "\n\n";

    foreach ($models->models as $model) {
        echo "  - {$model->name}\n";
        echo "    ID: {$model->id}\n";
        echo "    Size: {$model->getSizeFormatted()}\n";
        echo "    Loaded: " . ($model->loaded ? 'Yes' : 'No') . "\n";
        echo "    Version: " . ($model->version ?? 'N/A') . "\n\n";
    }
} catch (\Ainos\AinosException $e) {
    echo "Model list failed: {$e->getMessage()}\n\n";
}

// ----------------------------------------------------------------
// 6. Synchronous Inference
// ----------------------------------------------------------------

echo "--- Synchronous Inference ---\n";

$modelName = 'gpt-3.5-turbo';
$prompt = 'Explain what a TCP socket is in one sentence.';

echo "Model: {$modelName}\n";
echo "Prompt: {$prompt}\n\n";

try {
    $timer = Utils::microtimeFloat();

    $response = $client->infer(
        $modelName,
        $prompt,
        new Parameters(
            temperature: 0.7,
            maxTokens: 100,
            topP: 0.9,
            stop: ['.', '!', '?'],
        ),
    );

    $duration = Utils::microtimeFloat() - $timer;

    echo "Response ID: {$response->id}\n";
    echo "Generated Text:\n{$response->getText()}\n\n";
    echo "Usage:\n";
    echo "  Prompt Tokens: {$response->usage->promptTokens}\n";
    echo "  Completion Tokens: {$response->usage->completionTokens}\n";
    echo "  Total Tokens: {$response->usage->totalTokens}\n";
    echo "  Duration: " . \round($duration, 3) . "s\n\n";
} catch (\Ainos\AinosException $e) {
    echo "Inference failed: {$e->getMessage()}\n\n";
}

// ----------------------------------------------------------------
// 7. Context Management
// ----------------------------------------------------------------

echo "--- Context Management ---\n";

try {
    // Store a context value
    $entry = $client->contextStore(
        'user-session-123',
        ['name' => 'Alice', 'preferences' => ['theme' => 'dark']],
        3600, // 1 hour TTL
    );

    echo "Context Stored:\n";
    echo "  Key: {$entry->key}\n";
    echo "  TTL: {$entry->ttl}s\n";
    echo "  Expires: " . \date('Y-m-d H:i:s', $entry->expiresAt ?? 0) . "\n";

    // Retrieve the context value
    $retrieved = $client->contextRetrieve('user-session-123');

    if ($retrieved !== null) {
        echo "Context Retrieved:\n";
        echo "  Key: {$retrieved->key}\n";
        echo "  Value: " . \json_encode($retrieved->value) . "\n";
        echo "  Expired: " . ($retrieved->isExpired() ? 'Yes' : 'No') . "\n\n";
    } else {
        echo "Context not found.\n\n";
    }
} catch (\Ainos\AinosException $e) {
    echo "Context operation failed: {$e->getMessage()}\n\n";
}

// ----------------------------------------------------------------
// 8. Client Statistics
// ----------------------------------------------------------------

echo "--- Client Statistics ---\n";

$stats = $client->getStats();

echo "Total Requests: {$stats['total_requests']}\n";
echo "Successful Requests: {$stats['successful_requests']}\n";
echo "Failed Requests: {$stats['failed_requests']}\n";
echo "Token Preview: {$stats['auth_token_preview']}\n";

$transportStats = $stats['transport'];
echo "Bytes Sent: {$transportStats['bytes_sent']}\n";
echo "Bytes Received: {$transportStats['bytes_received']}\n\n";

// ----------------------------------------------------------------
// 9. Cleanup
// ----------------------------------------------------------------

echo "Disconnecting...\n";
$client->disconnect();
echo "Done.\n";