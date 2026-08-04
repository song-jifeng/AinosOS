<?php

declare(strict_types=1);

namespace Ainos;

/**
 * Ainos - Base exception for all Ainos SDK errors.
 *
 * All exceptions thrown by the Ainos SDK extend this class, providing
 * a consistent error hierarchy with contextual metadata for debugging
 * and error reporting.
 *
 * @package Ainos
 */
class AinosException extends \RuntimeException
{
    /**
     * Additional context data associated with the exception.
     *
     * @var array<string, mixed>
     */
    private array $context;

    /**
     * Unique identifier for this exception instance, useful for tracing.
     *
     * @var string
     */
    private string $errorId;

    /**
     * @param string $message Human-readable error description
     * @param int $code SDK-specific error code
     * @param \Throwable|null $previous Optional previous exception for chaining
     * @param array<string, mixed> $context Additional contextual data
     */
    public function __construct(
        string $message = '',
        int $code = 0,
        ?\Throwable $previous = null,
        array $context = []
    ) {
        parent::__construct($message, $code, $previous);
        $this->context = $context;
        $this->errorId = \bin2hex(\random_bytes(16));
    }

    /**
     * Get the unique error identifier for this exception instance.
     *
     * @return string 32-character hex string
     */
    public function getErrorId(): string
    {
        return $this->errorId;
    }

    /**
     * Get the context data associated with this exception.
     *
     * @return array<string, mixed>
     */
    public function getContext(): array
    {
        return $this->context;
    }

    /**
     * Get a specific context value by key.
     *
     * @param string $key Context key
     * @param mixed $default Default value if key not found
     * @return mixed
     */
    public function getContextValue(string $key, mixed $default = null): mixed
    {
        return \array_key_exists($key, $this->context) ? $this->context[$key] : $default;
    }

    /**
     * Add additional context data to this exception.
     *
     * @param array<string, mixed> $context Context data to merge
     * @return $this
     */
    public function withContext(array $context): static
    {
        $this->context = \array_merge($this->context, $context);
        return $this;
    }

    /**
     * Convert the exception to an array for logging or serialization.
     *
     * @return array<string, mixed>
     */
    public function toArray(): array
    {
        return [
            'error_id' => $this->errorId,
            'type' => static::class,
            'message' => $this->message,
            'code' => $this->code,
            'file' => $this->file,
            'line' => $this->line,
            'context' => $this->context,
            'trace' => $this->getTraceAsString(),
        ];
    }

    /**
     * Convert the exception to a JSON string for logging.
     *
     * @param int $flags JSON encoding flags
     * @return string
     */
    public function toJson(int $flags = \JSON_PRETTY_PRINT | \JSON_UNESCAPED_UNICODE): string
    {
        return \json_encode($this->toArray(), $flags | \JSON_THROW_ON_ERROR);
    }

    /**
     * Create an exception from an array representation.
     *
     * @param array<string, mixed> $data Exception data array
     * @return static
     */
    public static function fromArray(array $data): static
    {
        return new static(
            (string)($data['message'] ?? 'Unknown error'),
            (int)($data['code'] ?? 0),
            null,
            (array)($data['context'] ?? [])
        );
    }
}

/**
 * Connection errors - raised when the SDK cannot establish or maintain
 * a TCP connection to the Ainos server.
 *
 * Error codes: 1001-1010
 */
class ConnectionException extends AinosException
{
    /** @var int Default connection timeout */
    public const DEFAULT_TIMEOUT = 30;

    /** @var int Maximum number of connection retries */
    public const MAX_RETRIES = 3;

    /**
     * @param string $host Host that was being connected to
     * @param int $port Port that was being connected to
     * @param string $reason Reason for connection failure
     * @param \Throwable|null $previous Optional previous exception
     */
    public function __construct(
        string $host,
        int $port,
        string $reason = 'Connection failed',
        ?\Throwable $previous = null
    ) {
        parent::__construct(
            \sprintf('Cannot connect to %s:%d - %s', $host, $port, $reason),
            1001,
            $previous,
            ['host' => $host, 'port' => $port, 'reason' => $reason]
        );
    }

    /**
     * Get the host that was being connected to.
     *
     * @return string
     */
    public function getHost(): string
    {
        return $this->getContextValue('host', '');
    }

    /**
     * Get the port that was being connected to.
     *
     * @return int
     */
    public function getPort(): int
    {
        return (int)$this->getContextValue('port', 0);
    }

    /**
     * Create an instance for a timeout error.
     *
     * @param string $host Host being connected to
     * @param int $port Port being connected to
     * @param float $timeout Timeout duration in seconds
     * @return self
     */
    public static function timeout(string $host, int $port, float $timeout): self
    {
        return new self(
            $host,
            $port,
            \sprintf('Connection timed out after %.1f seconds', $timeout)
        );
    }

    /**
     * Create an instance for a refused connection.
     *
     * @param string $host Host being connected to
     * @param int $port Port being connected to
     * @return self
     */
    public static function refused(string $host, int $port): self
    {
        return new self(
            $host,
            $port,
            \sprintf('Connection refused by %s:%d - is the server running?', $host, $port)
        );
    }

    /**
     * Create an instance for a DNS resolution failure.
     *
     * @param string $host Host that failed to resolve
     * @return self
     */
    public static function dnsResolutionFailed(string $host): self
    {
        return new self(
            $host,
            0,
            \sprintf('DNS resolution failed for host: %s', $host)
        );
    }

    /**
     * Check if the connection error is likely transient and retryable.
     *
     * @return bool
     */
    public function isRetryable(): bool
    {
        $reason = $this->getContextValue('reason', '');
        return \str_contains($reason, 'timed out')
            || \str_contains($reason, 'reset')
            || \str_contains($reason, 'refused');
    }
}

/**
 * Authentication errors - raised when token validation fails.
 *
 * Error codes: 1011-1020
 */
class AuthenticationException extends AinosException
{
    /**
     * @param string $reason Authentication failure reason
     * @param string|null $tokenPreview Partial preview of the token (first 8 chars)
     * @param \Throwable|null $previous Optional previous exception
     */
    public function __construct(
        string $reason = 'Authentication failed',
        ?string $tokenPreview = null,
        ?\Throwable $previous = null
    ) {
        $context = ['reason' => $reason];
        if ($tokenPreview !== null) {
            $context['token_preview'] = $tokenPreview;
        }

        parent::__construct(
            \sprintf('Authentication failed: %s', $reason),
            1011,
            $previous,
            $context
        );
    }

    /**
     * Create an instance for an invalid token format.
     *
     * @param string $reason Why the token format is invalid
     * @return self
     */
    public static function invalidTokenFormat(string $reason = 'Token format is invalid'): self
    {
        return new self($reason);
    }

    /**
     * Create an instance for an expired token.
     *
     * @return self
     */
    public static function tokenExpired(): self
    {
        return new self('The authentication token has expired');
    }

    /**
     * Create an instance for a missing token.
     *
     * @return self
     */
    public static function missingToken(): self
    {
        return new self('No authentication token provided');
    }

    /**
     * Create an instance for a server-side authentication rejection.
     *
     * @param string $serverMessage Message from the server
     * @return self
     */
    public static function serverRejected(string $serverMessage = 'Token rejected by server'): self
    {
        return new self($serverMessage);
    }
}

/**
 * Invalid request errors - raised when request parameters are invalid.
 *
 * Error codes: 1021-1030
 */
class InvalidRequestException extends AinosException
{
    /**
     * @param string $message Error description
     * @param string $field The field that failed validation
     * @param mixed $value The invalid value
     * @param \Throwable|null $previous Optional previous exception
     */
    public function __construct(
        string $message = 'Invalid request',
        string $field = '',
        mixed $value = null,
        ?\Throwable $previous = null
    ) {
        parent::__construct(
            $message,
            1021,
            $previous,
            ['field' => $field, 'value' => $value]
        );
    }

    /**
     * Get the field that failed validation.
     *
     * @return string
     */
    public function getField(): string
    {
        return $this->getContextValue('field', '');
    }

    /**
     * Get the invalid value.
     *
     * @return mixed
     */
    public function getValue(): mixed
    {
        return $this->getContextValue('value');
    }

    /**
     * Create an instance for a missing required field.
     *
     * @param string $field The missing field name
     * @return self
     */
    public static function missingField(string $field): self
    {
        return new self(
            \sprintf('Required field "%s" is missing', $field),
            $field
        );
    }

    /**
     * Create an instance for an invalid field value.
     *
     * @param string $field The field name
     * @param mixed $value The invalid value
     * @param string $constraint Description of the constraint violated
     * @return self
     */
    public static function invalidField(string $field, mixed $value, string $constraint = 'invalid'): self
    {
        return new self(
            \sprintf('Field "%s" has invalid value "%s": %s', $field, \var_export($value, true), $constraint),
            $field,
            $value
        );
    }

    /**
     * Create an instance for a generic invalid request.
     *
     * @param string $message Error description
     * @return self
     */
    public static function general(string $message): self
    {
        return new self($message);
    }
}

/**
 * Model not found errors - raised when a requested model is not available.
 *
 * Error codes: 1031-1040
 */
class ModelNotFoundException extends AinosException
{
    /**
     * @param string $modelName The model name that was not found
     * @param \Throwable|null $previous Optional previous exception
     */
    public function __construct(
        string $modelName = '',
        ?\Throwable $previous = null
    ) {
        parent::__construct(
            \sprintf('Model "%s" not found. Use modelList() to see available models.', $modelName),
            1031,
            $previous,
            ['model' => $modelName]
        );
    }

    /**
     * Get the model name that was requested.
     *
     * @return string
     */
    public function getModelName(): string
    {
        return $this->getContextValue('model', '');
    }
}

/**
 * Timeout errors - raised when an operation exceeds its timeout.
 *
 * Error codes: 1041-1050
 */
class TimeoutException extends AinosException
{
    /**
     * @param string $operation Name of the operation that timed out
     * @param float $timeout Timeout duration in seconds
     * @param \Throwable|null $previous Optional previous exception
     */
    public function __construct(
        string $operation = 'Operation',
        float $timeout = 30.0,
        ?\Throwable $previous = null
    ) {
        parent::__construct(
            \sprintf('%s timed out after %.1f seconds', \ucfirst($operation), $timeout),
            1041,
            $previous,
            ['operation' => $operation, 'timeout' => $timeout]
        );
    }

    /**
     * Get the operation name.
     *
     * @return string
     */
    public function getOperation(): string
    {
        return $this->getContextValue('operation', '');
    }

    /**
     * Get the timeout duration.
     *
     * @return float
     */
    public function getTimeout(): float
    {
        return (float)$this->getContextValue('timeout', 0.0);
    }

    /**
     * Get the operation name in a human-readable format.
     *
     * @return string
     */
    public function getOperationName(): string
    {
        return \ucfirst($this->getOperation());
    }
}

/**
 * Streaming errors - raised during streaming inference operations.
 *
 * Error codes: 1051-1060
 */
class StreamingException extends AinosException
{
    /** @var int Stream was aborted by the client */
    public const ABORTED = 1051;

    /** @var int Stream ended unexpectedly */
    public const UNEXPECTED_END = 1052;

    /** @var int Invalid chunk data received */
    public const INVALID_CHUNK = 1053;

    /** @var int Stream timeout */
    public const STREAM_TIMEOUT = 1054;

    /** @var int Server error during streaming */
    public const SERVER_ERROR = 1055;

    /**
     * @param string $message Error description
     * @param int $code Streaming-specific error code
     * @param array<string, mixed> $context Additional context
     * @param \Throwable|null $previous Optional previous exception
     */
    public function __construct(
        string $message = 'Streaming error',
        int $code = self::ABORTED,
        array $context = [],
        ?\Throwable $previous = null
    ) {
        parent::__construct($message, $code, $previous, $context);
    }

    /**
     * Create an instance for an aborted stream.
     *
     * @param string $reason Reason for the abort
     * @return self
     */
    public static function aborted(string $reason = 'Stream was aborted by the client'): self
    {
        return new self($reason, self::ABORTED, ['reason' => $reason]);
    }

    /**
     * Create an instance for an unexpected stream end.
     *
     * @param string $details Details about the unexpected end
     * @return self
     */
    public static function unexpectedEnd(string $details = 'Stream ended unexpectedly'): self
    {
        return new self($details, self::UNEXPECTED_END, ['details' => $details]);
    }

    /**
     * Create an instance for an invalid chunk.
     *
     * @param string $chunkPreview Preview of the invalid chunk data
     * @param string $reason Reason the chunk is invalid
     * @return self
     */
    public static function invalidChunk(string $chunkPreview, string $reason = 'Invalid chunk format'): self
    {
        return new self($reason, self::INVALID_CHUNK, [
            'chunk_preview' => $chunkPreview,
            'reason' => $reason,
        ]);
    }

    /**
     * Create an instance for a stream timeout.
     *
     * @param float $timeout Timeout duration in seconds
     * @return self
     */
    public static function streamTimeout(float $timeout): self
    {
        return new self(
            \sprintf('Stream timed out after %.1f seconds', $timeout),
            self::STREAM_TIMEOUT,
            ['timeout' => $timeout]
        );
    }

    /**
     * Create an instance for a server error during streaming.
     *
     * @param string $serverMessage Error message from the server
     * @return self
     */
    public static function serverError(string $serverMessage): self
    {
        return new self($serverMessage, self::SERVER_ERROR, ['server_message' => $serverMessage]);
    }
}

/**
 * Transport errors - raised for low-level transport issues.
 *
 * Error codes: 1061-1070
 */
class TransportException extends AinosException
{
    /** @var int Socket is not connected */
    public const NOT_CONNECTED = 1061;

    /** @var int Socket write failed */
    public const WRITE_FAILED = 1062;

    /** @var int Socket read failed */
    public const READ_FAILED = 1063;

    /** @var int Socket already connected */
    public const ALREADY_CONNECTED = 1064;

    /** @var int Socket option error */
    public const SOCKET_OPTION = 1065;

    /**
     * @param string $message Error description
     * @param int $code Transport-specific error code
     * @param array<string, mixed> $context Additional context
     * @param \Throwable|null $previous Optional previous exception
     */
    public function __construct(
        string $message = 'Transport error',
        int $code = self::NOT_CONNECTED,
        array $context = [],
        ?\Throwable $previous = null
    ) {
        parent::__construct($message, $code, $previous, $context);
    }

    /**
     * Create an instance for a not-connected error.
     *
     * @return self
     */
    public static function notConnected(): self
    {
        return new self(
            'Transport is not connected. Call connect() first.',
            self::NOT_CONNECTED
        );
    }

    /**
     * Create an instance for a write failure.
     *
     * @param string $data Data that was being written (preview)
     * @param int $bytesWritten Number of bytes written before failure
     * @param string $error System error message
     * @return self
     */
    public static function writeFailed(string $data, int $bytesWritten, string $error): self
    {
        return new self(
            \sprintf('Failed to write data to socket: %s', $error),
            self::WRITE_FAILED,
            ['data_preview' => \mb_substr($data, 0, 100), 'bytes_written' => $bytesWritten, 'error' => $error]
        );
    }

    /**
     * Create an instance for a read failure.
     *
     * @param string $error System error message
     * @return self
     */
    public static function readFailed(string $error): self
    {
        return new self(
            \sprintf('Failed to read data from socket: %s', $error),
            self::READ_FAILED,
            ['error' => $error]
        );
    }
}

/**
 * Protocol errors - raised when server responses violate the NDJSON protocol.
 *
 * Error codes: 1071-1080
 */
class ProtocolException extends AinosException
{
    /** @var int Invalid JSON in response */
    public const INVALID_JSON = 1071;

    /** @var int Unexpected response format */
    public const UNEXPECTED_FORMAT = 1072;

    /** @var int Missing required fields in response */
    public const MISSING_FIELDS = 1073;

    /** @var int Response ID mismatch */
    public const ID_MISMATCH = 1074;

    /** @var int Server returned an error response */
    public const SERVER_ERROR = 1075;

    /**
     * @param string $message Error description
     * @param int $code Protocol-specific error code
     * @param array<string, mixed> $context Additional context
     * @param \Throwable|null $previous Optional previous exception
     */
    public function __construct(
        string $message = 'Protocol error',
        int $code = self::INVALID_JSON,
        array $context = [],
        ?\Throwable $previous = null
    ) {
        parent::__construct($message, $code, $previous, $context);
    }

    /**
     * Create an instance for invalid JSON.
     *
     * @param string $raw Raw data that could not be parsed
     * @param string $jsonError The JSON error message
     * @return self
     */
    public static function invalidJson(string $raw, string $jsonError): self
    {
        return new self(
            \sprintf('Invalid JSON in server response: %s', $jsonError),
            self::INVALID_JSON,
            ['raw_preview' => \mb_substr($raw, 0, 200), 'json_error' => $jsonError]
        );
    }

    /**
     * Create an instance for an unexpected response format.
     *
     * @param array $response The unexpected response data
     * @param string $expectedFormat Description of expected format
     * @return self
     */
    public static function unexpectedFormat(array $response, string $expectedFormat = 'unknown'): self
    {
        return new self(
            \sprintf('Unexpected response format. Expected: %s', $expectedFormat),
            self::UNEXPECTED_FORMAT,
            ['response_keys' => \array_keys($response), 'expected' => $expectedFormat]
        );
    }

    /**
     * Create an instance for missing fields.
     *
     * @param array<string> $missingFields List of fields that are missing
     * @return self
     */
    public static function missingFields(array $missingFields): self
    {
        return new self(
            \sprintf('Response missing required fields: %s', \implode(', ', $missingFields)),
            self::MISSING_FIELDS,
            ['missing_fields' => $missingFields]
        );
    }

    /**
     * Create an instance for an ID mismatch.
     *
     * @param string $expected Expected request ID
     * @param string $received Received response ID
     * @return self
     */
    public static function idMismatch(string $expected, string $received): self
    {
        return new self(
            \sprintf('Response ID mismatch: expected "%s", received "%s"', $expected, $received),
            self::ID_MISMATCH,
            ['expected_id' => $expected, 'received_id' => $received]
        );
    }

    /**
     * Create an instance for a server error response.
     *
     * @param string $errorMessage Error message from the server
     * @param int $errorCode Error code from the server
     * @return self
     */
    public static function serverError(string $errorMessage, int $errorCode = 0): self
    {
        return new self(
            \sprintf('Server returned error: %s', $errorMessage),
            self::SERVER_ERROR,
            ['server_error' => $errorMessage, 'server_code' => $errorCode]
        );
    }
}

/**
 * Configuration errors - raised when SDK configuration is invalid.
 *
 * Error codes: 1081-1090
 */
class ConfigurationException extends AinosException
{
    /**
     * @param string $message Error description
     * @param string $setting The configuration setting that is invalid
     * @param mixed $value The invalid value
     * @param \Throwable|null $previous Optional previous exception
     */
    public function __construct(
        string $message = 'Configuration error',
        string $setting = '',
        mixed $value = null,
        ?\Throwable $previous = null
    ) {
        parent::__construct(
            $message,
            1081,
            $previous,
            ['setting' => $setting, 'value' => $value]
        );
    }

    /**
     * Create an instance for an invalid setting value.
     *
     * @param string $setting The setting name
     * @param mixed $value The invalid value
     * @param string $constraint Description of the constraint
     * @return self
     */
    public static function invalidSetting(string $setting, mixed $value, string $constraint = 'invalid'): self
    {
        return new self(
            \sprintf('Configuration setting "%s" has invalid value "%s": %s', $setting, \var_export($value, true), $constraint),
            $setting,
            $value
        );
    }

    /**
     * Create an instance for a missing required setting.
     *
     * @param string $setting The missing setting name
     * @return self
     */
    public static function missingSetting(string $setting): self
    {
        return new self(\sprintf('Required configuration setting "%s" is missing', $setting), $setting);
    }

    /**
     * Create an instance for an unsupported option.
     *
     * @param string $option The unsupported option name
     * @param mixed $value The value that was provided
     * @return self
     */
    public static function unsupportedOption(string $option, mixed $value = null): self
    {
        return new self(
            \sprintf('Unsupported configuration option "%s"', $option),
            $option,
            $value
        );
    }
}