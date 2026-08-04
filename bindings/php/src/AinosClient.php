<?php

declare(strict_types=1);

namespace Ainos;

/**
 * Ainos - Main client for interacting with the Ainos inference server.
 *
 * Provides a high-level interface for all Ainos API operations:
 * inference (sync and streaming), model management, server health,
 * and context management.
 *
 * All communication is over TCP using the NDJSON protocol with
 * Bearer token authentication.
 *
 * Basic usage:
 * ```php
 * $auth = new Authentication('your-token-here');
 * $client = new AinosClient($auth);
 * $client->connect();
 *
 * $response = $client->infer('gpt-3.5-turbo', 'Hello, world!');
 * echo $response->getText();
 * ```
 *
 * @package Ainos
 */
final class AinosClient
{
    /** @var string Default server host */
    public const DEFAULT_HOST = '127.0.0.1';

    /** @var int Default server port */
    public const DEFAULT_PORT = 9500;

    /** @var float Default timeout */
    public const DEFAULT_TIMEOUT = 30.0;

    /** @var int Default maximum retries for failed requests */
    public const DEFAULT_MAX_RETRIES = 3;

    /** @var float Default retry delay in seconds */
    public const DEFAULT_RETRY_DELAY = 1.0;

    /** @var Authentication The authentication handler */
    private Authentication $auth;

    /** @var Transport The TCP transport layer */
    private Transport $transport;

    /** @var array<string, mixed> Client configuration options */
    private array $options;

    /** @var bool Whether the client auto-connects on first request */
    private bool $autoConnect;

    /** @var int Maximum number of retries for failed requests */
    private int $maxRetries;

    /** @var float Delay between retries in seconds */
    private float $retryDelay;

    /** @var bool Whether retry is enabled */
    private bool $retryEnabled;

    /** @var float Default timeout for all operations */
    private float $defaultTimeout;

    /** @var Timer Performance timer */
    private Timer $timer;

    /** @var array<string, mixed> Client statistics */
    private array $stats;

    /**
     * @param Authentication $auth Authentication handler
     * @param string $host Server hostname
     * @param int $port Server port
     * @param array<string, mixed> $options Client options:
     *        - auto_connect: bool (default: true) auto-connect on first request
     *        - max_retries: int (default: 3) max retry attempts
     *        - retry_delay: float (default: 1.0) delay between retries
     *        - retry_enabled: bool (default: true) enable retry logic
     *        - timeout: float (default: 30.0) default operation timeout
     *        - read_timeout: float (default: 30.0) read timeout
     *        - write_timeout: float (default: 30.0) write timeout
     *        - chunk_timeout: float (default: 30.0) streaming chunk timeout
     * @throws \Ainos\ConfigurationException if options are invalid
     */
    public function __construct(
        Authentication $auth,
        string $host = self::DEFAULT_HOST,
        int $port = self::DEFAULT_PORT,
        array $options = [],
    ) {
        $this->auth = $auth;
        $this->options = \array_merge($this->getDefaultOptions(), $options);
        $this->timer = new Timer();
        $this->stats = $this->initStats();

        // Validate options
        $this->validateOptions();

        // Create transport
        $timeout = (float)($this->options['timeout'] ?? self::DEFAULT_TIMEOUT);
        $this->transport = new Transport($host, $port, $timeout);

        // Apply read/write timeouts
        if (isset($this->options['read_timeout'])) {
            $this->transport->setReadTimeout((float)$this->options['read_timeout']);
        }
        if (isset($this->options['write_timeout'])) {
            $this->transport->setWriteTimeout((float)$this->options['write_timeout']);
        }

        $this->autoConnect = (bool)($this->options['auto_connect'] ?? true);
        $this->maxRetries = (int)($this->options['max_retries'] ?? self::DEFAULT_MAX_RETRIES);
        $this->retryDelay = (float)($this->options['retry_delay'] ?? self::DEFAULT_RETRY_DELAY);
        $this->retryEnabled = (bool)($this->options['retry_enabled'] ?? true);
        $this->defaultTimeout = (float)($this->options['timeout'] ?? self::DEFAULT_TIMEOUT);
    }

    /**
     * Destructor - ensures clean disconnection.
     */
    public function __destruct()
    {
        $this->disconnect();
    }

    /**
     * Get the default client options.
     *
     * @return array<string, mixed>
     */
    private function getDefaultOptions(): array
    {
        return [
            'auto_connect' => true,
            'max_retries' => self::DEFAULT_MAX_RETRIES,
            'retry_delay' => self::DEFAULT_RETRY_DELAY,
            'retry_enabled' => true,
            'timeout' => self::DEFAULT_TIMEOUT,
            'read_timeout' => self::DEFAULT_TIMEOUT,
            'write_timeout' => self::DEFAULT_TIMEOUT,
            'chunk_timeout' => 30.0,
            'max_empty_reads' => 10,
            'max_line_length' => Transport::MAX_LINE_LENGTH,
        ];
    }

    /**
     * Initialize statistics counters.
     *
     * @return array<string, mixed>
     */
    private function initStats(): array
    {
        return [
            'total_requests' => 0,
            'successful_requests' => 0,
            'failed_requests' => 0,
            'retry_count' => 0,
            'total_streaming_chunks' => 0,
            'total_inference_time' => 0.0,
            'total_prompt_tokens' => 0,
            'total_completion_tokens' => 0,
            'last_request_time' => null,
            'last_request_method' => null,
            'last_error' => null,
        ];
    }

    /**
     * Validate client options.
     *
     * @return void
     * @throws \Ainos\ConfigurationException
     */
    private function validateOptions(): void
    {
        if (isset($this->options['max_retries'])) {
            $maxRetries = (int)$this->options['max_retries'];
            if ($maxRetries < 0) {
                throw ConfigurationException::invalidSetting('max_retries', $maxRetries, 'must be >= 0');
            }
        }

        if (isset($this->options['retry_delay'])) {
            $retryDelay = (float)$this->options['retry_delay'];
            if ($retryDelay < 0) {
                throw ConfigurationException::invalidSetting('retry_delay', $retryDelay, 'must be >= 0');
            }
        }

        if (isset($this->options['timeout'])) {
            $timeout = (float)$this->options['timeout'];
            if ($timeout <= 0) {
                throw ConfigurationException::invalidSetting('timeout', $timeout, 'must be > 0');
            }
        }
    }

    /**
     * Ensure the client is connected to the server.
     * Auto-connects if autoConnect is enabled.
     *
     * @return void
     * @throws \Ainos\ConnectionException
     */
    public function ensureConnected(): void
    {
        if (!$this->transport->isConnected()) {
            if (!$this->autoConnect) {
                throw TransportException::notConnected();
            }
            $this->connect();
        }
    }

    /**
     * Establish a connection to the Ainos server.
     *
     * @return void
     * @throws \Ainos\ConnectionException if connection fails
     */
    public function connect(): void
    {
        $this->timer->start();
        $this->transport->connect();
        $this->stats['last_connect_time'] = $this->timer->stop();
    }

    /**
     * Disconnect from the Ainos server.
     *
     * @return void
     */
    public function disconnect(): void
    {
        $this->transport->disconnect();
    }

    /**
     * Send a request to the server and return the decoded response.
     *
     * @param string $method RPC method name
     * @param array $params Request parameters
     * @param float|null $timeout Operation timeout
     * @return array Response data
     * @throws \Ainos\ConnectionException
     * @throws \Ainos\AuthenticationException
     * @throws \Ainos\InvalidRequestException
     * @throws \Ainos\ModelNotFoundException
     * @throws \Ainos\TimeoutException
     * @throws \Ainos\ProtocolException
     * @throws \Ainos\TransportException
     */
    private function sendRequest(string $method, array $params = [], ?float $timeout = null): array
    {
        $this->ensureConnected();

        $envelope = RequestEnvelope::create($method, $params);

        // Add auth token to params
        $envelopeParams = $envelope->params;
        $envelopeParams['token'] = $this->auth->getToken();

        $request = (new RequestEnvelope(
            method: $envelope->method,
            params: $envelopeParams,
            id: $envelope->id,
        ))->toArray();

        $timeout = $timeout ?? $this->defaultTimeout;
        $lastException = null;

        $attempts = $this->retryEnabled ? ($this->maxRetries + 1) : 1;

        for ($attempt = 1; $attempt <= $attempts; $attempt++) {
            try {
                $this->timer->reset();
                $this->timer->start();

                $response = $this->transport->sendAndReceive($request, $timeout);

                $requestDuration = $this->timer->stop();

                // Update stats
                $this->stats['total_requests']++;
                $this->stats['last_request_time'] = $requestDuration;
                $this->stats['last_request_method'] = $method;

                // Parse the response envelope
                $envelope = ResponseEnvelope::fromArray($response);

                // Check for errors
                if ($envelope->isError()) {
                    $this->stats['failed_requests']++;
                    $this->stats['last_error'] = $envelope->getErrorMessage();
                    $envelope->throwIfError();
                }

                // Verify response ID matches request ID
                if ($envelope->id !== '' && $envelope->id !== $envelope->id) {
                    // ID mismatch is non-fatal, just log
                }

                $this->stats['successful_requests']++;

                return $response;

            } catch (ConnectionException $e) {
                $lastException = $e;
                $this->stats['failed_requests']++;
                $this->stats['last_error'] = $e->getMessage();

                if ($attempt < $attempts && $e->isRetryable()) {
                    $this->stats['retry_count']++;
                    \usleep((int)($this->retryDelay * 1_000_000));

                    // Reconnect for next attempt
                    try {
                        $this->reconnect();
                    } catch (ConnectionException $reconnectErr) {
                        throw $reconnectErr;
                    }
                    continue;
                }

                throw $e;

            } catch (TransportException $e) {
                $lastException = $e;
                $this->stats['failed_requests']++;
                $this->stats['last_error'] = $e->getMessage();

                if ($attempt < $attempts) {
                    $this->stats['retry_count']++;
                    \usleep((int)($this->retryDelay * 1_000_000));

                    try {
                        $this->reconnect();
                    } catch (ConnectionException $reconnectErr) {
                        throw $reconnectErr;
                    }
                    continue;
                }

                throw $e;

            } catch (TimeoutException $e) {
                $this->stats['failed_requests']++;
                $this->stats['last_error'] = $e->getMessage();
                throw $e;
            }
        }

        // This should not be reached, but satisfies the type system
        throw $lastException ?? new AinosException('Request failed after all retries');
    }

    /**
     * Reconnect to the server.
     *
     * @return void
     * @throws \Ainos\ConnectionException
     */
    public function reconnect(): void
    {
        $this->transport->reconnect();
    }

    // ========================
    // API Methods
    // ========================

    /**
     * Perform synchronous inference.
     *
     * @param string $model Model name to use
     * @param string $prompt Input prompt text
     * @param array|\Ainos\Parameters $parameters Optional inference parameters
     * @param array|null $context Optional context data
     * @return \Ainos\InferenceResponse
     * @throws \Ainos\ConnectionException
     * @throws \Ainos\AuthenticationException
     * @throws \Ainos\InvalidRequestException
     * @throws \Ainos\ModelNotFoundException
     * @throws \Ainos\TimeoutException
     * @throws \Ainos\ProtocolException
     */
    public function infer(
        string $model,
        string $prompt,
        array|Parameters $parameters = [],
        ?array $context = null,
    ): InferenceResponse {
        // Validate parameters
        Utils::assertNonEmptyString('model', $model);
        Utils::assertNonEmptyString('prompt', $prompt);

        // Convert parameters to array if needed
        if ($parameters instanceof Parameters) {
            $paramsArray = $parameters->toArray();
        } else {
            $paramsArray = Parameters::fromArray($parameters)->toArray();
        }

        $params = [
            'model' => $model,
            'prompt' => $prompt,
            'parameters' => $paramsArray,
            'stream' => false,
        ];

        if ($context !== null) {
            $params['context'] = $context;
        }

        $response = $this->sendRequest('infer', $params);

        // Extract result from response
        $result = $response['result'] ?? $response;

        // Update token stats
        if (isset($result['usage'])) {
            $this->stats['total_prompt_tokens'] += (int)($result['usage']['prompt_tokens'] ?? 0);
            $this->stats['total_completion_tokens'] += (int)($result['usage']['completion_tokens'] ?? 0);
        }

        return InferenceResponse::fromArray(\is_array($result) ? $result : []);
    }

    /**
     * Perform streaming inference. Returns a generator yielding StreamChunk objects.
     *
     * @param string $model Model name to use
     * @param string $prompt Input prompt text
     * @param array|\Ainos\Parameters $parameters Optional inference parameters
     * @param array|null $context Optional context data
     * @return \Generator<StreamChunk>
     * @throws \Ainos\ConnectionException
     * @throws \Ainos\AuthenticationException
     * @throws \Ainos\InvalidRequestException
     * @throws \Ainos\ModelNotFoundException
     * @throws \Ainos\TimeoutException
     * @throws \Ainos\ProtocolException
     */
    public function inferStream(
        string $model,
        string $prompt,
        array|Parameters $parameters = [],
        ?array $context = null,
    ): \Generator {
        // Validate parameters
        Utils::assertNonEmptyString('model', $model);
        Utils::assertNonEmptyString('prompt', $prompt);

        // Ensure connection
        $this->ensureConnected();

        // Convert parameters to array if needed
        if ($parameters instanceof Parameters) {
            $paramsArray = $parameters->toArray();
        } else {
            $paramsArray = Parameters::fromArray($parameters)->toArray();
        }

        $requestId = Utils::generateId('stream');

        $params = [
            'model' => $model,
            'prompt' => $prompt,
            'parameters' => $paramsArray,
            'stream' => true,
        ];

        if ($context !== null) {
            $params['context'] = $context;
        }

        $request = (new RequestEnvelope(
            method: 'infer',
            params: \array_merge($params, ['token' => $this->auth->getToken()]),
            id: $requestId,
        ))->toArray();

        // Send the request
        $this->transport->sendNDJSON($request);
        $this->stats['total_requests']++;

        // Create the stream buffer and yield chunks
        $timeout = (float)($this->options['chunk_timeout'] ?? 30.0);
        $maxEmptyReads = (int)($this->options['max_empty_reads'] ?? 10);

        $buffer = new StreamBuffer(
            transport: $this->transport,
            requestId: $requestId,
            model: $model,
            options: [
                'chunk_timeout' => $timeout,
                'max_empty_reads' => $maxEmptyReads,
            ],
            onChunk: function (StreamChunk $chunk) {
                $this->stats['total_streaming_chunks']++;
            },
            onError: function (StreamingException $e) {
                $this->stats['failed_requests']++;
                $this->stats['last_error'] = $e->getMessage();
            },
            onComplete: function () {
                $this->stats['successful_requests']++;
            },
        );

        // Yield chunks from the stream
        try {
            foreach ($buffer->chunks() as $chunk) {
                // Track usage from final chunk
                if ($chunk->usage !== null) {
                    $this->stats['total_prompt_tokens'] += $chunk->usage->promptTokens;
                    $this->stats['total_completion_tokens'] += $chunk->usage->completionTokens;
                }

                yield $chunk;
            }
        } catch (StreamingException $e) {
            $this->stats['last_error'] = $e->getMessage();
            throw $e;
        }
    }

    /**
     * List all available models on the server.
     *
     * @return \Ainos\ModelList
     * @throws \Ainos\ConnectionException
     * @throws \Ainos\AuthenticationException
     * @throws \Ainos\TimeoutException
     * @throws \Ainos\ProtocolException
     */
    public function modelList(): ModelList
    {
        $response = $this->sendRequest('modelList', []);
        $result = $response['result'] ?? $response;

        return ModelList::fromArray(\is_array($result) ? $result : []);
    }

    /**
     * Load a model into memory.
     *
     * @param string $model Model name or path to load
     * @param array $options Optional loading options (e.g., gpu_layers, context_size)
     * @return \Ainos\ModelInfo
     * @throws \Ainos\ConnectionException
     * @throws \Ainos\AuthenticationException
     * @throws \Ainos\InvalidRequestException
     * @throws \Ainos\TimeoutException
     * @throws \Ainos\ProtocolException
     */
    public function modelLoad(string $model, array $options = []): ModelInfo
    {
        Utils::assertNonEmptyString('model', $model);

        $params = \array_merge(['model' => $model], $options);

        $response = $this->sendRequest('modelLoad', $params);
        $result = $response['result'] ?? $response;

        return ModelInfo::fromArray(\is_array($result) ? $result : []);
    }

    /**
     * Unload a model from memory.
     *
     * @param string $model Model name to unload
     * @return bool True if the model was successfully unloaded
     * @throws \Ainos\ConnectionException
     * @throws \Ainos\AuthenticationException
     * @throws \Ainos\InvalidRequestException
     * @throws \Ainos\ModelNotFoundException
     * @throws \Ainos\TimeoutException
     * @throws \Ainos\ProtocolException
     */
    public function modelUnload(string $model): bool
    {
        Utils::assertNonEmptyString('model', $model);

        $response = $this->sendRequest('modelUnload', ['model' => $model]);
        $result = $response['result'] ?? $response;

        if (\is_array($result)) {
            return (bool)($result['success'] ?? $result['unloaded'] ?? false);
        }

        return (bool)$result;
    }

    /**
     * Check the server health status.
     *
     * @return \Ainos\HealthStatus
     * @throws \Ainos\ConnectionException
     * @throws \Ainos\TimeoutException
     * @throws \Ainos\ProtocolException
     */
    public function health(): HealthStatus
    {
        $response = $this->sendRequest('health', []);
        $result = $response['result'] ?? $response;

        return HealthStatus::fromArray(\is_array($result) ? $result : []);
    }

    /**
     * Get detailed server status.
     *
     * @return \Ainos\ServerStatus
     * @throws \Ainos\ConnectionException
     * @throws \Ainos\AuthenticationException
     * @throws \Ainos\TimeoutException
     * @throws \Ainos\ProtocolException
     */
    public function status(): ServerStatus
    {
        $response = $this->sendRequest('status', []);
        $result = $response['result'] ?? $response;

        return ServerStatus::fromArray(\is_array($result) ? $result : []);
    }

    /**
     * Store a context value on the server.
     *
     * @param string $key Context key
     * @param mixed $value Context value (must be JSON-serializable)
     * @param int $ttl Time-to-live in seconds (default: 3600)
     * @return \Ainos\ContextEntry
     * @throws \Ainos\ConnectionException
     * @throws \Ainos\AuthenticationException
     * @throws \Ainos\InvalidRequestException
     * @throws \Ainos\TimeoutException
     * @throws \Ainos\ProtocolException
     */
    public function contextStore(string $key, mixed $value, int $ttl = 3600): ContextEntry
    {
        Utils::assertNonEmptyString('key', $key);

        if ($ttl < 1) {
            throw InvalidRequestException::invalidField('ttl', $ttl, 'must be >= 1');
        }

        $response = $this->sendRequest('contextStore', [
            'key' => $key,
            'value' => $value,
            'ttl' => $ttl,
        ]);

        $result = $response['result'] ?? $response;

        return ContextEntry::fromArray(\is_array($result) ? $result : []);
    }

    /**
     * Retrieve a context value from the server.
     *
     * @param string $key Context key to retrieve
     * @return \Ainos\ContextEntry|null The context entry, or null if not found
     * @throws \Ainos\ConnectionException
     * @throws \Ainos\AuthenticationException
     * @throws \Ainos\InvalidRequestException
     * @throws \Ainos\TimeoutException
     * @throws \Ainos\ProtocolException
     */
    public function contextRetrieve(string $key): ?ContextEntry
    {
        Utils::assertNonEmptyString('key', $key);

        $response = $this->sendRequest('contextRetrieve', ['key' => $key]);
        $result = $response['result'] ?? $response;

        if ($result === null || (isset($result['found']) && $result['found'] === false)) {
            return null;
        }

        return ContextEntry::fromArray(\is_array($result) ? $result : []);
    }

    // ========================
    // Accessors
    // ========================

    /**
     * Get the transport layer instance.
     *
     * @return Transport
     */
    public function getTransport(): Transport
    {
        return $this->transport;
    }

    /**
     * Get the authentication handler.
     *
     * @return Authentication
     */
    public function getAuthentication(): Authentication
    {
        return $this->auth;
    }

    /**
     * Set a new authentication handler.
     *
     * @param Authentication $auth New authentication handler
     * @return void
     */
    public function setAuthentication(Authentication $auth): void
    {
        $this->auth = $auth;
    }

    /**
     * Get all client options.
     *
     * @return array<string, mixed>
     */
    public function getOptions(): array
    {
        return $this->options;
    }

    /**
     * Update client options.
     *
     * @param array $options New options to merge
     * @return void
     * @throws \Ainos\ConfigurationException
     */
    public function setOptions(array $options): void
    {
        $this->options = \array_merge($this->options, $options);
        $this->validateOptions();

        // Update internal properties
        if (isset($options['max_retries'])) {
            $this->maxRetries = (int)$options['max_retries'];
        }
        if (isset($options['retry_delay'])) {
            $this->retryDelay = (float)$options['retry_delay'];
        }
        if (isset($options['retry_enabled'])) {
            $this->retryEnabled = (bool)$options['retry_enabled'];
        }
        if (isset($options['timeout'])) {
            $this->defaultTimeout = (float)$options['timeout'];
        }
        if (isset($options['auto_connect'])) {
            $this->autoConnect = (bool)$options['auto_connect'];
        }

        // Apply transport-level options
        if (isset($options['read_timeout'])) {
            $this->transport->setReadTimeout((float)$options['read_timeout']);
        }
        if (isset($options['write_timeout'])) {
            $this->transport->setWriteTimeout((float)$options['write_timeout']);
        }
    }

    /**
     * Check if the client is connected to the server.
     *
     * @return bool
     */
    public function isConnected(): bool
    {
        return $this->transport->isConnected();
    }

    /**
     * Get client statistics.
     *
     * @return array<string, mixed>
     */
    public function getStats(): array
    {
        $transportStats = $this->transport->getStats();

        return \array_merge($this->stats, [
            'transport' => $transportStats,
            'auth_token_preview' => $this->auth->getTokenPreview(),
            'options' => [
                'auto_connect' => $this->autoConnect,
                'max_retries' => $this->maxRetries,
                'retry_delay' => $this->retryDelay,
                'retry_enabled' => $this->retryEnabled,
                'timeout' => $this->defaultTimeout,
            ],
        ]);
    }

    /**
     * Reset all client statistics.
     *
     * @return void
     */
    public function resetStats(): void
    {
        $this->stats = $this->initStats();
        $this->transport->resetStats();
    }

    /**
     * Get the server host.
     *
     * @return string
     */
    public function getHost(): string
    {
        return $this->transport->getHost();
    }

    /**
     * Get the server port.
     *
     * @return int
     */
    public function getPort(): int
    {
        return $this->transport->getPort();
    }

    /**
     * Create a client instance from environment variables.
     *
     * Reads AINOS_HOST, AINOS_PORT, AINOS_TOKEN, and AINOS_TIMEOUT
     * from the environment.
     *
     * @param array $options Additional options to override environment values
     * @return self
     * @throws \Ainos\AuthenticationException if AINOS_TOKEN is not set
     */
    public static function fromEnvironment(array $options = []): self
    {
        $auth = Authentication::fromEnvironment('AINOS_TOKEN');
        $host = \getenv('AINOS_HOST') ?: self::DEFAULT_HOST;
        $port = (int)(\getenv('AINOS_PORT') ?: (string)self::DEFAULT_PORT);
        $timeout = (float)(\getenv('AINOS_TIMEOUT') ?: (string)self::DEFAULT_TIMEOUT);

        $options = \array_merge(['timeout' => $timeout], $options);

        return new self($auth, $host, $port, $options);
    }

    /**
     * Create a client from a configuration array.
     *
     * @param array $config Configuration array with keys:
     *        - token: string (required)
     *        - host: string (optional, default: 127.0.0.1)
     *        - port: int (optional, default: 9500)
     *        - options: array (optional, client options)
     * @return self
     * @throws \Ainos\ConfigurationException if token is missing
     */
    public static function fromConfig(array $config): self
    {
        if (!isset($config['token'])) {
            throw ConfigurationException::missingSetting('token');
        }

        $auth = new Authentication($config['token']);
        $host = $config['host'] ?? self::DEFAULT_HOST;
        $port = (int)($config['port'] ?? self::DEFAULT_PORT);
        $options = $config['options'] ?? [];

        return new self($auth, $host, $port, $options);
    }

    /**
     * Return debug information.
     *
     * @return array<string, mixed>
     */
    public function __debugInfo(): array
    {
        return $this->getStats();
    }
}