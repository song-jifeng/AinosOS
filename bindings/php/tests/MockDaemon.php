<?php

declare(strict_types=1);

namespace Ainos\Tests;

use Ainos\NDJSON;

/**
 * Mock Ainos server daemon for testing.
 *
 * Simulates the Ainos server protocol over TCP, allowing tests
 * to run without a real server. Supports all major API methods
 * and streaming responses.
 *
 * @package Ainos\Tests
 */
class MockDaemon
{
    /** @var string Host to bind to */
    private string $host;

    /** @var int Port to bind to */
    private int $port;

    /** @var string Expected authentication token */
    private string $expectedToken;

    /** @var \Socket|null Server socket */
    private ?\Socket $server = null;

    /** @var \Socket|null Client connection socket */
    private ?\Socket $client = null;

    /** @var bool Whether the daemon is running */
    private bool $running = false;

    /** @var int Number of accepted connections */
    private int $connectionCount = 0;

    /** @var array<string, mixed> Server state */
    private array $state = [
        'models' => [],
        'context' => [],
        'request_count' => 0,
    ];

    /** @var array<string, callable> Custom response handlers */
    private array $handlers = [];

    /** @var array<string, mixed> Predefined responses */
    private array $responses = [];

    /**
     * @param string $host Host to bind to
     * @param int $port Port to bind to
     * @param string $expectedToken Expected auth token
     */
    public function __construct(
        string $host = '127.0.0.1',
        int $port = 0,
        string $expectedToken = 'test-token',
    ) {
        $this->host = $host;
        $this->port = $port;
        $this->expectedToken = $expectedToken;
    }

    /**
     * Destructor - ensures clean shutdown.
     */
    public function __destruct()
    {
        $this->stop();
    }

    /**
     * Start the mock daemon.
     *
     * @return int The port the daemon is listening on
     * @throws \RuntimeException if the daemon fails to start
     */
    public function start(): int
    {
        $this->server = @\socket_create(\AF_INET, \SOCK_STREAM, \SOL_TCP);

        if ($this->server === false) {
            throw new \RuntimeException(
                \sprintf('Failed to create socket: %s', \socket_strerror(\socket_last_error()))
            );
        }

        // Allow address reuse
        @\socket_set_option($this->server, \SOL_SOCKET, \SO_REUSEADDR, 1);

        // Bind to the port (port 0 = auto-assign)
        if (!@\socket_bind($this->server, $this->host, $this->port)) {
            throw new \RuntimeException(
                \sprintf('Failed to bind socket: %s', \socket_strerror(\socket_last_error($this->server)))
            );
        }

        // Get the actual port
        if ($this->port === 0) {
            @\socket_getsockname($this->server, $this->host, $this->port);
        }

        // Listen with a backlog
        if (!@\socket_listen($this->server, 5)) {
            throw new \RuntimeException(
                \sprintf('Failed to listen on socket: %s', \socket_strerror(\socket_last_error($this->server)))
            );
        }

        $this->running = true;

        return $this->port;
    }

    /**
     * Stop the mock daemon.
     */
    public function stop(): void
    {
        $this->running = false;

        try {
            if ($this->client !== null) {
                @\socket_shutdown($this->client, \SHUT_RDWR);
                @\socket_close($this->client);
                $this->client = null;
            }
        } catch (\Throwable) {
            // Ignore
        }

        try {
            if ($this->server !== null) {
                @\socket_shutdown($this->server, \SHUT_RDWR);
                @\socket_close($this->server);
                $this->server = null;
            }
        } catch (\Throwable) {
            // Ignore
        }
    }

    /**
     * Set a custom response handler for a specific method.
     *
     * @param string $method The method name
     * @param callable $handler Function(array $params, array $state): array
     */
    public function setHandler(string $method, callable $handler): void
    {
        $this->handlers[$method] = $handler;
    }

    /**
     * Accept a client connection.
     *
     * @param int $timeoutSeconds Timeout in seconds
     * @return bool True if a connection was accepted
     */
    public function acceptConnection(int $timeoutSeconds = 5): bool
    {
        if (!$this->running || $this->server === null) {
            return false;
        }

        // Set non-blocking for select
        @\socket_set_nonblock($this->server);

        $read = [$this->server];
        $write = null;
        $except = null;

        $result = @\socket_select($read, $write, $except, $timeoutSeconds, 0);

        if ($result === false || $result === 0) {
            return false;
        }

        $this->client = @\socket_accept($this->server);

        if ($this->client === false) {
            return false;
        }

        @\socket_set_block($this->client);
        $this->connectionCount++;

        return true;
    }

    /**
     * Handle a single client request.
     *
     * @return bool True if a request was handled, false if client disconnected
     * @throws \RuntimeException on protocol errors
     */
    public function handleRequest(): bool
    {
        if ($this->client === null) {
            return false;
        }

        // Read a line (NDJSON)
        $line = '';
        $buffer = '';

        while (true) {
            $chunk = @\socket_read($this->client, 1, \PHP_BINARY_READ);

            if ($chunk === false || $chunk === '') {
                return false;
            }

            if ($chunk === "\n") {
                break;
            }

            $buffer .= $chunk;

            // Prevent DoS with large lines
            if (\strlen($buffer) > 65536) {
                throw new \RuntimeException('Request line too long');
            }
        }

        $line = \trim($buffer);

        if ($line === '') {
            return true; // Skip empty lines
        }

        // Parse the request
        $request = \json_decode($line, true);

        if (!\is_array($request)) {
            $this->sendError('', 'Invalid JSON in request');
            return true;
        }

        $method = $request['method'] ?? '';
        $params = $request['params'] ?? [];
        $requestId = $request['id'] ?? '';

        // Verify token
        $token = $params['token'] ?? $request['token'] ?? '';
        if ($token !== $this->expectedToken) {
            $this->sendError($requestId, 'Authentication failed: invalid token', 1011);
            return true;
        }

        // Dispatch to handler
        try {
            $this->handleMethod($method, $params, $requestId);
        } catch (\Throwable $e) {
            $this->sendError($requestId, $e->getMessage(), 0);
        }

        $this->state['request_count']++;

        return true;
    }

    /**
     * Handle a single request and return the response data (for testing without socket).
     *
     * @param array $request The request array
     * @return array The response array
     */
    public function handleDirect(array $request): array
    {
        $method = $request['method'] ?? '';
        $params = $request['params'] ?? [];
        $requestId = $request['id'] ?? 'req-001';

        // Verify token
        $token = $params['token'] ?? $request['token'] ?? '';
        if ($token !== $this->expectedToken) {
            return $this->buildErrorResponse($requestId, 'Authentication failed: invalid token', 1011);
        }

        try {
            return $this->buildResponse($method, $params, $requestId);
        } catch (\Throwable $e) {
            return $this->buildErrorResponse($requestId, $e->getMessage(), 0);
        }
    }

    /**
     * Handle a method call.
     *
     * @param string $method Method name
     * @param array $params Parameters
     * @param string $requestId Request ID
     */
    private function handleMethod(string $method, array $params, string $requestId): void
    {
        $response = $this->buildResponse($method, $params, $requestId);
        $this->sendNDJSON($response);
    }

    /**
     * Build a response for a method.
     *
     * @param string $method Method name
     * @param array $params Parameters
     * @param string $requestId Request ID
     * @return array Response data
     */
    private function buildResponse(string $method, array $params, string $requestId): array
    {
        // Check for custom handler
        if (isset($this->handlers[$method])) {
            return ($this->handlers[$method])($params, $this->state, $requestId);
        }

        // Check for predefined response
        if (isset($this->responses[$method])) {
            $response = $this->responses[$method];
            $response['id'] = $requestId;
            return $response;
        }

        return match ($method) {
            'health' => $this->handleHealth($requestId),
            'status' => $this->handleStatus($requestId),
            'modelList' => $this->handleModelList($requestId),
            'modelLoad' => $this->handleModelLoad($params, $requestId),
            'modelUnload' => $this->handleModelUnload($params, $requestId),
            'infer' => $this->handleInfer($params, $requestId),
            'contextStore' => $this->handleContextStore($params, $requestId),
            'contextRetrieve' => $this->handleContextRetrieve($params, $requestId),
            default => $this->buildErrorResponse($requestId, \sprintf('Unknown method: %s', $method), 0),
        };
    }

    /**
     * Handle health check.
     */
    private function handleHealth(string $requestId): array
    {
        return [
            'id' => $requestId,
            'result' => [
                'status' => 'healthy',
                'uptime' => 3600.0,
                'version' => '1.0.0',
                'memory' => [
                    'used' => 1024 * 1024 * 512,
                    'total' => 1024 * 1024 * 1024 * 8,
                    'percentage' => 6.25,
                ],
                'active_connections' => 1,
                'start_time' => \time() - 3600,
                'checks' => [
                    'database' => 'healthy',
                    'cache' => 'healthy',
                    'models' => 'healthy',
                ],
            ],
        ];
    }

    /**
     * Handle server status.
     */
    private function handleStatus(string $requestId): array
    {
        return [
            'id' => $requestId,
            'result' => [
                'version' => '1.0.0',
                'uptime' => 3600,
                'active_models' => ['gpt-3.5-turbo', 'gpt-4'],
                'total_requests' => $this->state['request_count'],
                'memory' => [
                    'used' => 1024 * 1024 * 1024,
                    'total' => 1024 * 1024 * 1024 * 8,
                    'percentage' => 12.5,
                ],
                'cpu_average' => 45.2,
                'active_connections' => 1,
                'start_time' => \time() - 3600,
                'config' => [
                    'max_connections' => 100,
                    'max_model_size' => '10GB',
                    'log_level' => 'info',
                ],
                'hardware' => [
                    'gpu' => ['NVIDIA A100', 'NVIDIA A100'],
                    'cpu' => 'AMD EPYC 7V12',
                    'memory' => '64GB',
                ],
                'stats' => [
                    'avg_inference_time' => 0.5,
                    'p99_inference_time' => 2.0,
                    'tokens_per_second' => 150.0,
                ],
            ],
        ];
    }

    /**
     * Handle model list.
     */
    private function handleModelList(string $requestId): array
    {
        $models = [
            [
                'name' => 'gpt-3.5-turbo',
                'id' => 'gpt-3.5-turbo',
                'path' => '/models/gpt-3.5-turbo',
                'size' => 1024 * 1024 * 1024 * 4,
                'loaded' => true,
                'metadata' => [
                    'architecture' => 'transformer',
                    'parameters' => '175B',
                    'quantization' => 'fp16',
                ],
                'modified_at' => \time() - 86400,
                'loaded_at' => \time() - 3600,
                'version' => '1.0.0',
                'description' => 'GPT-3.5-Turbo model',
                'license' => 'MIT',
                'author' => 'OpenAI',
            ],
            [
                'name' => 'gpt-4',
                'id' => 'gpt-4',
                'path' => '/models/gpt-4',
                'size' => 1024 * 1024 * 1024 * 8,
                'loaded' => true,
                'metadata' => [
                    'architecture' => 'transformer',
                    'parameters' => '1T',
                    'quantization' => 'fp16',
                ],
                'modified_at' => \time() - 172800,
                'loaded_at' => \time() - 7200,
                'version' => '2.0.0',
                'description' => 'GPT-4 model',
                'license' => 'MIT',
                'author' => 'OpenAI',
            ],
            [
                'name' => 'llama-2-7b',
                'id' => 'llama-2-7b',
                'path' => '/models/llama-2-7b',
                'size' => 1024 * 1024 * 1024 * 4,
                'loaded' => false,
                'metadata' => [
                    'architecture' => 'transformer',
                    'parameters' => '7B',
                    'quantization' => 'q4_0',
                ],
                'modified_at' => \time() - 259200,
                'loaded_at' => null,
                'version' => '1.0.0',
                'description' => 'Llama 2 7B model',
                'license' => 'Llama 2 Community License',
                'author' => 'Meta',
            ],
        ];

        $loadedCount = \count(\array_filter($models, fn($m) => $m['loaded']));

        return [
            'id' => $requestId,
            'result' => [
                'models' => $models,
                'total' => \count($models),
                'loaded_count' => $loadedCount,
                'total_size' => \array_sum(\array_column($models, 'size')),
            ],
        ];
    }

    /**
     * Handle model load.
     */
    private function handleModelLoad(array $params, string $requestId): array
    {
        $modelName = $params['model'] ?? '';

        if ($modelName === '') {
            return $this->buildErrorResponse($requestId, 'Model name is required', 1021);
        }

        $model = [
            'name' => $modelName,
            'id' => $modelName,
            'path' => \sprintf('/models/%s', $modelName),
            'size' => 1024 * 1024 * 1024 * 4,
            'loaded' => true,
            'metadata' => [
                'architecture' => 'transformer',
                'parameters' => 'unknown',
                'quantization' => 'fp16',
            ],
            'modified_at' => \time(),
            'loaded_at' => \time(),
            'version' => '1.0.0',
            'description' => \sprintf('Model %s', $modelName),
            'license' => 'MIT',
            'author' => 'Unknown',
        ];

        // Track loaded model
        $this->state['models'][$modelName] = true;

        return [
            'id' => $requestId,
            'result' => $model,
        ];
    }

    /**
     * Handle model unload.
     */
    private function handleModelUnload(array $params, string $requestId): array
    {
        $modelName = $params['model'] ?? '';

        if ($modelName === '') {
            return $this->buildErrorResponse($requestId, 'Model name is required', 1021);
        }

        if (!isset($this->state['models'][$modelName])) {
            return $this->buildErrorResponse(
                $requestId,
                \sprintf('Model "%s" not found', $modelName),
                1031
            );
        }

        unset($this->state['models'][$modelName]);

        return [
            'id' => $requestId,
            'result' => [
                'success' => true,
                'unloaded' => true,
            ],
        ];
    }

    /**
     * Handle inference (non-streaming).
     */
    private function handleInfer(array $params, string $requestId): array
    {
        $model = $params['model'] ?? '';
        $prompt = $params['prompt'] ?? '';
        $stream = $params['stream'] ?? false;

        if ($model === '') {
            return $this->buildErrorResponse($requestId, 'Model is required', 1021);
        }

        if ($prompt === '') {
            return $this->buildErrorResponse($requestId, 'Prompt is required', 1021);
        }

        // Handle streaming
        if ($stream) {
            $this->handleStreamingInfer($params, $requestId);
            return []; // Response already sent via streaming
        }

        // Generate a mock response
        $responseText = \sprintf(
            'This is a mock response from model "%s" for prompt: %s',
            $model,
            $prompt
        );

        $promptTokens = \str_word_count($prompt) + 10;
        $completionTokens = \str_word_count($responseText) + 5;

        return [
            'id' => $requestId,
            'result' => [
                'id' => $requestId,
                'model' => $model,
                'choices' => [
                    [
                        'index' => 0,
                        'text' => $responseText,
                        'finish_reason' => 'stop',
                        'logprobs' => null,
                    ],
                ],
                'usage' => [
                    'prompt_tokens' => $promptTokens,
                    'completion_tokens' => $completionTokens,
                    'total_tokens' => $promptTokens + $completionTokens,
                    'prompt_time' => 0.05,
                    'completion_time' => 0.15,
                    'total_time' => 0.2,
                    'prompt_tokens_per_second' => (int)($promptTokens / 0.05),
                    'completion_tokens_per_second' => (int)($completionTokens / 0.15),
                ],
                'created' => \time(),
                'object' => 'text_completion',
            ],
        ];
    }

    /**
     * Handle streaming inference.
     */
    private function handleStreamingInfer(array $params, string $requestId): void
    {
        $model = $params['model'] ?? '';
        $prompt = $params['prompt'] ?? '';

        $chunks = [
            ['text' => 'This ', 'finish_reason' => null],
            ['text' => 'is ', 'finish_reason' => null],
            ['text' => 'a ', 'finish_reason' => null],
            ['text' => 'streaming ', 'finish_reason' => null],
            ['text' => 'mock ', 'finish_reason' => null],
            ['text' => 'response.', 'finish_reason' => 'stop'],
        ];

        foreach ($chunks as $index => $chunkData) {
            $chunk = [
                'id' => $requestId,
                'type' => 'stream',
                'result' => [
                    'id' => $requestId,
                    'model' => $model,
                    'text' => $chunkData['text'],
                    'index' => 0,
                    'finish_reason' => $chunkData['finish_reason'],
                    'created' => \time(),
                ],
            ];

            $this->sendNDJSON($chunk);

            // Simulate delay between chunks
            \usleep(10000); // 10ms
        }

        // Send stream end
        $endChunk = [
            'id' => $requestId,
            'type' => 'stream_end',
            'result' => [
                'usage' => [
                    'prompt_tokens' => 10,
                    'completion_tokens' => 20,
                    'total_tokens' => 30,
                ],
            ],
        ];

        $this->sendNDJSON($endChunk);
    }

    /**
     * Handle context store.
     */
    private function handleContextStore(array $params, string $requestId): array
    {
        $key = $params['key'] ?? '';
        $value = $params['value'] ?? null;
        $ttl = (int)($params['ttl'] ?? 3600);

        if ($key === '') {
            return $this->buildErrorResponse($requestId, 'Key is required', 1021);
        }

        $this->state['context'][$key] = [
            'value' => $value,
            'ttl' => $ttl,
            'created_at' => \time(),
            'expires_at' => \time() + $ttl,
        ];

        return [
            'id' => $requestId,
            'result' => [
                'id' => \bin2hex(\random_bytes(8)),
                'key' => $key,
                'value' => $value,
                'ttl' => $ttl,
                'created_at' => \time(),
                'expires_at' => \time() + $ttl,
                'last_accessed_at' => \time(),
                'access_count' => 1,
            ],
        ];
    }

    /**
     * Handle context retrieve.
     */
    private function handleContextRetrieve(array $params, string $requestId): array
    {
        $key = $params['key'] ?? '';

        if ($key === '') {
            return $this->buildErrorResponse($requestId, 'Key is required', 1021);
        }

        if (!isset($this->state['context'][$key])) {
            return [
                'id' => $requestId,
                'result' => null,
            ];
        }

        $entry = $this->state['context'][$key];

        return [
            'id' => $requestId,
            'result' => [
                'id' => \bin2hex(\random_bytes(8)),
                'key' => $key,
                'value' => $entry['value'],
                'ttl' => $entry['ttl'],
                'created_at' => $entry['created_at'],
                'expires_at' => $entry['expires_at'],
                'last_accessed_at' => \time(),
                'access_count' => ($entry['access_count'] ?? 0) + 1,
            ],
        ];
    }

    /**
     * Send an NDJSON-encoded response to the client.
     *
     * @param array $data Response data
     */
    private function sendNDJSON(array $data): void
    {
        if ($this->client === null) {
            return;
        }

        $json = \json_encode($data, \JSON_UNESCAPED_UNICODE | \JSON_UNESCAPED_SLASHES);
        $payload = $json . "\n";

        @\socket_write($this->client, $payload, \strlen($payload));
    }

    /**
     * Send an error response.
     *
     * @param string $requestId Request ID
     * @param string $message Error message
     * @param int $code Error code
     */
    private function sendError(string $requestId, string $message, int $code): void
    {
        $response = $this->buildErrorResponse($requestId, $message, $code);
        $this->sendNDJSON($response);
    }

    /**
     * Build an error response array.
     *
     * @param string $requestId Request ID
     * @param string $message Error message
     * @param int $code Error code
     * @return array
     */
    private function buildErrorResponse(string $requestId, string $message, int $code): array
    {
        return [
            'id' => $requestId,
            'error' => [
                'message' => $message,
                'code' => $code,
            ],
        ];
    }

    /**
     * Run a single request-response cycle for testing.
     * Accepts a connection and handles one request.
     *
     * @param int $timeoutSeconds Timeout for accepting connection
     * @return bool True if a request was handled
     */
    public function runOnce(int $timeoutSeconds = 5): bool
    {
        if (!$this->acceptConnection($timeoutSeconds)) {
            return false;
        }

        return $this->handleRequest();
    }

    /**
     * Get the server port.
     *
     * @return int
     */
    public function getPort(): int
    {
        return $this->port;
    }

    /**
     * Get the server host.
     *
     * @return string
     */
    public function getHost(): string
    {
        return $this->host;
    }

    /**
     * Get the number of accepted connections.
     *
     * @return int
     */
    public function getConnectionCount(): int
    {
        return $this->connectionCount;
    }

    /**
     * Get the server state (for test assertions).
     *
     * @return array
     */
    public function getState(): array
    {
        return $this->state;
    }

    /**
     * Check if the daemon is running.
     *
     * @return bool
     */
    public function isRunning(): bool
    {
        return $this->running;
    }

    /**
     * Set a predefined response for a specific method.
     *
     * @param string $method Method name
     * @param array $response Response data (without 'id')
     * @return void
     */
    public function setResponse(string $method, array $response): void
    {
        $this->responses[$method] = $response;
    }
}