<?php

declare(strict_types=1);

namespace Ainos;

/**
 * Ainos - Utility functions for JSON handling, validation, and general helpers.
 *
 * @package Ainos
 */
final class Utils
{
    /**
     * JSON encode with error handling and default flags.
     *
     * @param mixed $value The value to encode
     * @param int $flags JSON encoding flags (JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES by default)
     * @param int $depth Maximum depth
     * @return string JSON-encoded string
     * @throws \Ainos\InvalidRequestException if encoding fails
     */
    public static function jsonEncode(mixed $value, int $flags = \JSON_UNESCAPED_UNICODE | \JSON_UNESCAPED_SLASHES, int $depth = 512): string
    {
        try {
            $json = \json_encode($value, $flags | \JSON_THROW_ON_ERROR, $depth);
        } catch (\JsonException $e) {
            throw InvalidRequestException::general(
                \sprintf('JSON encoding failed: %s', $e->getMessage())
            );
        }

        return $json;
    }

    /**
     * JSON decode with error handling.
     *
     * @param string $json The JSON string to decode
     * @param bool $assoc Decode to associative array (true) or stdClass (false)
     * @param int $depth Maximum depth
     * @param int $flags JSON decoding flags
     * @return mixed Decoded value
     * @throws \Ainos\ProtocolException if decoding fails
     */
    public static function jsonDecode(string $json, bool $assoc = true, int $depth = 512, int $flags = 0): mixed
    {
        if (\trim($json) === '') {
            throw ProtocolException::invalidJson($json, 'Empty JSON string');
        }

        try {
            $decoded = \json_decode($json, $assoc, $depth, $flags | \JSON_THROW_ON_ERROR);
        } catch (\JsonException $e) {
            throw ProtocolException::invalidJson($json, $e->getMessage());
        }

        return $decoded;
    }

    /**
     * Recursively filter an array, removing null values and empty arrays.
     *
     * @param array $array The array to filter
     * @param callable|null $callback Optional custom filter callback
     * @return array Filtered array
     */
    public static function arrayFilterRecursive(array $array, ?callable $callback = null): array
    {
        $result = [];

        foreach ($array as $key => $value) {
            if (\is_array($value)) {
                $value = self::arrayFilterRecursive($value, $callback);
            }

            $keep = $callback !== null
                ? $callback($value, $key)
                : $value !== null;

            if ($keep) {
                $result[$key] = $value;
            }
        }

        return $result;
    }

    /**
     * Return only the specified keys from an array.
     *
     * @param array $array Source array
     * @param array<string> $keys Keys to keep
     * @return array Filtered array
     */
    public static function arrayOnly(array $array, array $keys): array
    {
        $result = [];

        foreach ($keys as $key) {
            if (\array_key_exists($key, $array)) {
                $result[$key] = $array[$key];
            }
        }

        return $result;
    }

    /**
     * Return all keys except the specified ones from an array.
     *
     * @param array $array Source array
     * @param array<string> $keys Keys to remove
     * @return array Filtered array
     */
    public static function arrayExcept(array $array, array $keys): array
    {
        foreach ($keys as $key) {
            unset($array[$key]);
        }

        return $array;
    }

    /**
     * Deep-merge two or more arrays, with later values overwriting earlier ones.
     * Arrays are merged recursively, non-array values are overwritten.
     *
     * @param array ...$arrays Arrays to merge
     * @return array Merged array
     */
    public static function arrayMergeDeep(array ...$arrays): array
    {
        $result = [];

        foreach ($arrays as $array) {
            foreach ($array as $key => $value) {
                if (\is_array($value) && isset($result[$key]) && \is_array($result[$key])) {
                    $result[$key] = self::arrayMergeDeep($result[$key], $value);
                } else {
                    $result[$key] = $value;
                }
            }
        }

        return $result;
    }

    /**
     * Generate a unique request ID.
     *
     * @param string $prefix Optional prefix for the ID
     * @return string 32-character hex string with optional prefix
     */
    public static function generateId(string $prefix = ''): string
    {
        $id = \bin2hex(\random_bytes(16));

        return $prefix !== '' ? $prefix . '_' . $id : $id;
    }

    /**
     * Validate an authentication token format.
     * Tokens must be non-empty strings with only URL-safe characters.
     *
     * @param string $token Token to validate
     * @return bool True if the token has valid format
     */
    public static function validateToken(string $token): bool
    {
        if ($token === '') {
            return false;
        }

        // Tokens can be hex, base64url, or JWT-like
        return (bool)\preg_match('/^[A-Za-z0-9_\-\.]+$/', $token);
    }

    /**
     * Validate a hostname or IP address for connection.
     *
     * @param string $host Host to validate
     * @return bool True if the host is valid
     */
    public static function validateHost(string $host): bool
    {
        if ($host === '') {
            return false;
        }

        // Allow IP addresses (IPv4, IPv6) and hostnames
        if (\filter_var($host, \FILTER_VALIDATE_IP) !== false) {
            return true;
        }

        // Validate hostname format
        return (bool)\preg_match(
            '/^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$/',
            $host
        );
    }

    /**
     * Validate a TCP port number.
     *
     * @param int $port Port to validate
     * @return bool True if the port is valid (1-65535)
     */
    public static function validatePort(int $port): bool
    {
        return $port >= 1 && $port <= 65535;
    }

    /**
     * Format bytes into a human-readable string.
     *
     * @param int|float $bytes Size in bytes
     * @param int $precision Number of decimal places
     * @return string Human-readable size string (e.g., "1.5 MB")
     */
    public static function formatBytes(int|float $bytes, int $precision = 2): string
    {
        $units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];

        $bytes = \max((float)$bytes, 0.0);
        $pow = \floor(($bytes === 0.0) ? 0 : \log($bytes, 1024));
        $pow = \min((int)$pow, \count($units) - 1);

        $bytes /= 1024 ** $pow;

        return \sprintf("%.{$precision}f %s", $bytes, $units[$pow]);
    }

    /**
     * Get the current time as a high-precision float.
     *
     * @return float Current time in seconds with microsecond precision
     */
    public static function microtimeFloat(): float
    {
        return \microtime(true);
    }

    /**
     * Build a query string from an array of parameters.
     * Handles nested arrays and special characters.
     *
     * @param array $params Parameters to encode
     * @param string $numericPrefix Numeric index prefix
     * @param string|null $argSeparator Argument separator
     * @return string URL-encoded query string
     */
    public static function buildQueryString(array $params, string $numericPrefix = '', ?string $argSeparator = null): string
    {
        $argSeparator ??= \ini_get('arg_separator.output') ?: '&';

        if ($params === []) {
            return '';
        }

        return \http_build_query($params, $numericPrefix, $argSeparator, \PHP_QUERY_RFC3986);
    }

    /**
     * Parse a query string into an array, handling URL encoding.
     *
     * @param string $query Query string to parse
     * @return array Parsed parameters
     */
    public static function parseQueryString(string $query): array
    {
        if ($query === '') {
            return [];
        }

        $result = [];
        \parse_str($query, $result);

        return $result;
    }

    /**
     * Truncate a string to a maximum length, appending a suffix if truncated.
     *
     * @param string $string String to truncate
     * @param int $maxLength Maximum length
     * @param string $suffix Suffix for truncated strings (default: "...")
     * @return string Truncated string
     */
    public static function truncate(string $string, int $maxLength = 100, string $suffix = '...'): string
    {
        if (\mb_strlen($string) <= $maxLength) {
            return $string;
        }

        return \mb_substr($string, 0, $maxLength - \mb_strlen($suffix)) . $suffix;
    }

    /**
     * Convert a camelCase string to snake_case.
     *
     * @param string $input CamelCase string
     * @return string snake_case string
     */
    public static function camelToSnake(string $input): string
    {
        return \mb_strtolower(\preg_replace('/(?<!^)[A-Z]/', '_$0', $input));
    }

    /**
     * Convert a snake_case string to camelCase.
     *
     * @param string $input snake_case string
     * @param bool $upperCamelCase Use UpperCamelCase (PascalCase) if true
     * @return string camelCase string
     */
    public static function snakeToCamel(string $input, bool $upperCamelCase = false): string
    {
        $result = \str_replace(' ', '', \ucwords(\str_replace('_', ' ', $input)));

        if (!$upperCamelCase) {
            $result = \lcfirst($result);
        }

        return $result;
    }

    /**
     * Asserts that a value is within a given range.
     *
     * @param string $field Field name for error messages
     * @param int|float $value Value to check
     * @param int|float $min Minimum allowed value
     * @param int|float $max Maximum allowed value
     * @throws \Ainos\InvalidRequestException if the value is out of range
     */
    public static function assertRange(string $field, int|float $value, int|float $min, int|float $max): void
    {
        if ($value < $min || $value > $max) {
            throw InvalidRequestException::invalidField(
                $field,
                $value,
                \sprintf('must be between %s and %s', $min, $max)
            );
        }
    }

    /**
     * Asserts that a value is one of the allowed choices.
     *
     * @param string $field Field name for error messages
     * @param mixed $value Value to check
     * @param array $allowed Allowed values
     * @throws \Ainos\InvalidRequestException if the value is not in the allowed list
     */
    public static function assertChoice(string $field, mixed $value, array $allowed): void
    {
        if (!\in_array($value, $allowed, true)) {
            throw InvalidRequestException::invalidField(
                $field,
                $value,
                \sprintf('must be one of: %s', \implode(', ', $allowed))
            );
        }
    }

    /**
     * Asserts that a value is a non-empty string.
     *
     * @param string $field Field name for error messages
     * @param mixed $value Value to check
     * @throws \Ainos\InvalidRequestException if the value is not a non-empty string
     */
    public static function assertNonEmptyString(string $field, mixed $value): void
    {
        if (!\is_string($value) || \trim($value) === '') {
            throw InvalidRequestException::invalidField(
                $field,
                $value,
                'must be a non-empty string'
            );
        }
    }

    /**
     * Collapse an array of arrays into a single array.
     *
     * @param array $array Array of arrays to collapse
     * @return array Collapsed array
     */
    public static function arrayCollapse(array $array): array
    {
        $result = [];

        foreach ($array as $values) {
            if (\is_array($values)) {
                $result = \array_merge($result, $values);
            }
        }

        return $result;
    }

    /**
     * Determine if an array is associative (has string keys).
     *
     * @param array $array Array to check
     * @return bool True if the array is associative
     */
    public static function isAssociativeArray(array $array): bool
    {
        if ($array === []) {
            return false;
        }

        return \count(\array_filter(\array_keys($array), 'is_string')) > 0;
    }

    /**
     * Convert an array to a readable string representation for debugging.
     *
     * @param array $array Array to convert
     * @param int $maxDepth Maximum recursion depth
     * @return string String representation
     */
    public static function arrayToString(array $array, int $maxDepth = 3): string
    {
        $format = static function ($value, int $depth) use (&$format, $maxDepth): string {
            if ($depth > $maxDepth) {
                return '...';
            }

            if (\is_null($value)) {
                return 'null';
            }

            if (\is_bool($value)) {
                return $value ? 'true' : 'false';
            }

            if (\is_string($value)) {
                return \sprintf('"%s"', self::truncate($value, 50));
            }

            if (\is_numeric($value)) {
                return (string)$value;
            }

            if (\is_array($value)) {
                if ($value === []) {
                    return '[]';
                }

                $parts = [];
                foreach ($value as $k => $v) {
                    $parts[] = \sprintf('%s: %s', $k, $format($v, $depth + 1));
                }

                return '[' . \implode(', ', $parts) . ']';
            }

            if ($value instanceof \stdClass) {
                return '(object)';
            }

            return \get_debug_type($value);
        };

        return $format($array, 0);
    }
}

/**
 * Ainos - High-precision timer for performance measurement.
 *
 * Provides a simple, reusable timer with microsecond precision for
 * measuring operation durations.
 *
 * @package Ainos
 */
final class Timer
{
    /** @var float|null Start time in microseconds */
    private ?float $startTime = null;

    /** @var float|null Stop time in microseconds */
    private ?float $stopTime = null;

    /** @var float Total accumulated time in microseconds (for lap-style timing) */
    private float $accumulated = 0.0;

    /** @var bool Whether the timer is currently running */
    private bool $running = false;

    /**
     * Start the timer. If already running, this resets and restarts.
     *
     * @return $this
     */
    public function start(): static
    {
        $this->startTime = Utils::microtimeFloat();
        $this->running = true;
        $this->stopTime = null;

        return $this;
    }

    /**
     * Stop the timer and return the elapsed time.
     *
     * @return float Elapsed time in seconds (with microsecond precision)
     * @throws \Ainos\AinosException if the timer was never started
     */
    public function stop(): float
    {
        if ($this->startTime === null) {
            throw new AinosException('Timer was never started');
        }

        $this->stopTime = Utils::microtimeFloat();
        $this->running = false;
        $this->accumulated += $this->stopTime - $this->startTime;

        return $this->stopTime - $this->startTime;
    }

    /**
     * Get the elapsed time without stopping the timer.
     *
     * @return float Elapsed time in seconds
     * @throws \Ainos\AinosException if the timer was never started
     */
    public function elapsed(): float
    {
        if ($this->startTime === null) {
            throw new AinosException('Timer was never started');
        }

        if ($this->running) {
            return Utils::microtimeFloat() - $this->startTime;
        }

        if ($this->stopTime !== null) {
            return $this->stopTime - $this->startTime;
        }

        return 0.0;
    }

    /**
     * Get the total accumulated time across all start/stop cycles.
     *
     * @return float Total accumulated time in seconds
     */
    public function total(): float
    {
        return $this->accumulated + ($this->running ? $this->elapsed() : 0.0);
    }

    /**
     * Reset the timer to its initial state.
     *
     * @return $this
     */
    public function reset(): static
    {
        $this->startTime = null;
        $this->stopTime = null;
        $this->accumulated = 0.0;
        $this->running = false;

        return $this;
    }

    /**
     * Check if the timer is currently running.
     *
     * @return bool
     */
    public function isRunning(): bool
    {
        return $this->running;
    }

    /**
     * Format the current elapsed time as a human-readable string.
     *
     * @param int $precision Number of decimal places
     * @return string Formatted time string
     */
    public function format(int $precision = 3): string
    {
        $elapsed = $this->elapsed();

        if ($elapsed < 0.001) {
            return \sprintf('%.0f µs', $elapsed * 1_000_000);
        }

        if ($elapsed < 1.0) {
            return \sprintf('%.0f ms', $elapsed * 1_000);
        }

        if ($elapsed < 60.0) {
            return \sprintf("%.{$precision}f s", $elapsed);
        }

        $minutes = (int)($elapsed / 60);
        $seconds = $elapsed - ($minutes * 60);

        return \sprintf('%d min %02d sec', $minutes, (int)$seconds);
    }

    /**
     * Execute a callable and measure its execution time.
     *
     * @template T
     * @param callable(): T $callback The callable to execute
     * @return array{result: T, duration: float} Result and duration in seconds
     */
    public static function measure(callable $callback): array
    {
        $start = Utils::microtimeFloat();
        $result = $callback();
        $duration = Utils::microtimeFloat() - $start;

        return ['result' => $result, 'duration' => $duration];
    }

    /**
     * Return the current state as an array for serialization.
     *
     * @return array<string, mixed>
     */
    public function __debugInfo(): array
    {
        return [
            'running' => $this->running,
            'elapsed' => $this->elapsed(),
            'total' => $this->total(),
            'accumulated' => $this->accumulated,
        ];
    }
}

/**
 * Ainos - NDJSON (Newline Delimited JSON) encoder/decoder.
 *
 * Handles the serialization and deserialization of NDJSON messages
 * used by the Ainos protocol.
 *
 * @package Ainos
 */
final class NDJSON
{
    /** @var string Line ending character */
    public const DELIMITER = "\n";

    /**
     * Encode a value as an NDJSON line.
     *
     * @param mixed $value Value to encode
     * @param int $flags JSON encoding flags
     * @return string NDJSON-encoded string (with trailing newline)
     * @throws \Ainos\InvalidRequestException if encoding fails
     */
    public static function encode(mixed $value, int $flags = \JSON_UNESCAPED_UNICODE | \JSON_UNESCAPED_SLASHES): string
    {
        return Utils::jsonEncode($value, $flags) . self::DELIMITER;
    }

    /**
     * Decode an NDJSON string into an array of values.
     *
     * @param string $data NDJSON data (may contain multiple lines)
     * @param bool $assoc Decode to associative arrays
     * @return array Decoded values
     * @throws \Ainos\ProtocolException if decoding fails
     */
    public static function decode(string $data, bool $assoc = true): array
    {
        if (\trim($data) === '') {
            return [];
        }

        $lines = \explode(self::DELIMITER, $data);
        $result = [];

        foreach ($lines as $line) {
            $line = \trim($line);

            if ($line === '') {
                continue;
            }

            $result[] = Utils::jsonDecode($line, $assoc);
        }

        return $result;
    }

    /**
     * Decode a single NDJSON line.
     *
     * @param string $line Single NDJSON line (without trailing newline)
     * @param bool $assoc Decode to associative arrays
     * @return mixed Decoded value
     * @throws \Ainos\ProtocolException if decoding fails
     */
    public static function decodeLine(string $line, bool $assoc = true): mixed
    {
        $line = \trim($line);

        if ($line === '') {
            throw ProtocolException::invalidJson($line, 'Empty NDJSON line');
        }

        return Utils::jsonDecode($line, $assoc);
    }

    /**
     * Check if a string looks like valid NDJSON.
     *
     * @param string $data Data to check
     * @return bool True if the data appears to be valid NDJSON
     */
    public static function isValid(string $data): bool
    {
        if (\trim($data) === '') {
            return false;
        }

        $lines = \explode(self::DELIMITER, $data);
        $nonEmpty = \array_filter(\array_map('trim', $lines));

        if ($nonEmpty === []) {
            return false;
        }

        foreach ($nonEmpty as $line) {
            if (!\json_validate($line)) {
                return false;
            }
        }

        return true;
    }

    /**
     * Encode multiple values into a single NDJSON string.
     *
     * @param array $values Values to encode
     * @param int $flags JSON encoding flags
     * @return string NDJSON-encoded string
     * @throws \Ainos\InvalidRequestException if encoding fails
     */
    public static function encodeBatch(array $values, int $flags = \JSON_UNESCAPED_UNICODE | \JSON_UNESCAPED_SLASHES): string
    {
        $lines = [];

        foreach ($values as $value) {
            $lines[] = Utils::jsonEncode($value, $flags);
        }

        return \implode(self::DELIMITER, $lines) . self::DELIMITER;
    }
}