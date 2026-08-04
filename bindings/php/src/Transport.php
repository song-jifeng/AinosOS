<?php

declare(strict_types=1);

namespace Ainos;

/**
 * Ainos - TCP transport layer for NDJSON communication.
 *
 * Manages a TCP socket connection to the Ainos server, handling
 * low-level send/receive operations with proper timeout and error
 * management. Supports both blocking and non-blocking I/O modes.
 *
 * @package Ainos
 */
final class Transport
{
    /** @var string Default host */
    public const DEFAULT_HOST = '127.0.0.1';

    /** @var int Default port */
    public const DEFAULT_PORT = 9500;

    /** @var float Default connection timeout in seconds */
    public const DEFAULT_TIMEOUT = 30.0;

    /** @var int Default read buffer size in bytes */
    public const BUFFER_SIZE = 65536;

    /** @var int Maximum NDJSON line length (10MB) */
    public const MAX_LINE_LENGTH = 10_485_760;

    /** @var string Host to connect to */
    private string $host;

    /** @var int Port to connect to */
    private int $port;

    /** @var float Connection timeout in seconds */
    private float $timeout;

    /** @var float Read timeout in seconds */
    private float $readTimeout;

    /** @var float Write timeout in seconds */
    private float $writeTimeout;

    /** @var \Socket|null The underlying TCP socket */
    private ?\Socket $socket = null;

    /** @var bool Whether the transport is connected */
    private bool $connected = false;

    /** @var int Total bytes sent */
    private int $bytesSent = 0;

    /** @var int Total bytes received */
    private int $bytesReceived = 0;

    /** @var int Total number of requests sent */
    private int $requestCount = 0;

    /** @var int Total number of responses received */
    private int $responseCount = 0;

    /** @var float|null Timestamp when the connection was established */
    private ?float $connectedAt = null;

    /** @var int Number of reconnections */
    private int $reconnectionCount = 0;

    /** @var array<string, mixed> Last socket error information */
    private array $lastError = [];

    /** @var bool Whether to use non-blocking mode for reads */
    private bool $nonBlocking = false;

    /** @var string Internal buffer for incomplete reads */
    private string $readBuffer = '';

    /**
     * @param string $host Server hostname or IP address
     * @param int $port Server port number
     * @param float $timeout Connection timeout in seconds
     * @throws \Ainos\ConfigurationException if host or port is invalid
     */
    public function __construct(
        string $host = self::DEFAULT_HOST,
        int $port = self::DEFAULT_PORT,
        float $timeout = self::DEFAULT_TIMEOUT,
    ) {
        if (!Utils::validateHost($host)) {
            throw ConfigurationException::invalidSetting('host', $host, 'Invalid hostname or IP address');
        }

        if (!Utils::validatePort($port)) {
            throw ConfigurationException::invalidSetting('port', $port, 'Port must be between 1 and 65535');
        }

        if ($timeout <= 0) {
            throw ConfigurationException::invalidSetting('timeout', $timeout, 'Timeout must be positive');
        }

        $this->host = $host;
        $this->port = $port;
        $this->timeout = $timeout;
        $this->readTimeout = $timeout;
        $this->writeTimeout = $timeout;
    }

    /**
     * Destructor - ensures the socket is disconnected.
     */
    public function __destruct()
    {
        $this->disconnect();
    }

    /**
     * Establish a TCP connection to the server.
     *
     * @return void
     * @throws \Ainos\ConnectionException if connection fails
     */
    public function connect(): void
    {
        if ($this->connected) {
            return;
        }

        $this->socket = @\socket_create(\AF_INET, \SOCK_STREAM, \SOL_TCP);

        if ($this->socket === false) {
            $error = \socket_last_error();
            throw new ConnectionException(
                $this->host,
                $this->port,
                \sprintf('Socket creation failed: %s', \socket_strerror($error))
            );
        }

        // Set socket options for better performance
        @\socket_set_option($this->socket, \SOL_TCP, \TCP_NODELAY, 1);
        @\socket_set_option($this->socket, \SOL_SOCKET, \SO_KEEPALIVE, 1);

        // Set send/receive buffer sizes
        @\socket_set_option($this->socket, \SOL_SOCKET, \SO_SNDBUF, self::BUFFER_SIZE);
        @\socket_set_option($this->socket, \SOL_SOCKET, \SO_RCVBUF, self::BUFFER_SIZE);

        // Set the socket to non-blocking for the connection attempt to implement our own timeout
        @\socket_set_nonblock($this->socket);

        $startTime = Utils::microtimeFloat();
        $connected = @\socket_connect($this->socket, $this->host, $this->port);

        if ($connected) {
            // Connected immediately (unlikely for TCP, but handle it)
            @\socket_set_block($this->socket);
            $this->finalizeConnection();
            return;
        }

        $error = \socket_last_error($this->socket);

        // EINPROGRESS (115) or EALREADY (114) means the connection is in progress
        if ($error !== \SOCKET_EINPROGRESS && $error !== \SOCKET_EALREADY) {
            @\socket_close($this->socket);
            $this->socket = null;

            if ($error === \SOCKET_ECONNREFUSED) {
                throw ConnectionException::refused($this->host, $this->port);
            }

            throw new ConnectionException(
                $this->host,
                $this->port,
                \sprintf('Connection failed: %s', \socket_strerror($error))
            );
        }

        // Wait for the connection to complete using select()
        $write = [$this->socket];
        $except = [$this->socket];
        $read = null;

        $remaining = $this->timeout;

        while ($remaining > 0) {
            $s = $remaining;
            $us = (int)(($s - (int)$s) * 1_000_000);

            $result = @\socket_select($read, $write, $except, (int)$s, $us);

            if ($result === false) {
                $error = \socket_last_error();
                @\socket_close($this->socket);
                $this->socket = null;
                throw new ConnectionException(
                    $this->host,
                    $this->port,
                    \sprintf('Socket select failed: %s', \socket_strerror($error))
                );
            }

            if ($result > 0) {
                break;
            }

            // Timeout
            $remaining = $this->timeout - (Utils::microtimeFloat() - $startTime);
        }

        if ($remaining <= 0) {
            @\socket_close($this->socket);
            $this->socket = null;
            throw ConnectionException::timeout($this->host, $this->port, $this->timeout);
        }

        // Check if the connection succeeded
        $error = @\socket_get_option($this->socket, \SOL_SOCKET, \SO_ERROR);

        if ($error !== 0) {
            @\socket_close($this->socket);
            $this->socket = null;

            if ($error === \SOCKET_ECONNREFUSED) {
                throw ConnectionException::refused($this->host, $this->port);
            }

            throw new ConnectionException(
                $this->host,
                $this->port,
                \sprintf('Connection failed: %s', \socket_strerror($error))
            );
        }

        // Set back to blocking mode
        @\socket_set_block($this->socket);

        $this->finalizeConnection();
    }

    /**
     * Finalize the connection state after successful socket connect.
     */
    private function finalizeConnection(): void
    {
        $this->connected = true;
        $this->connectedAt = Utils::microtimeFloat();
        $this->readBuffer = '';
        $this->lastError = [];
    }

    /**
     * Disconnect from the server.
     *
     * @return void
     */
    public function disconnect(): void
    {
        if ($this->socket !== null) {
            try {
                @\socket_shutdown($this->socket, \SHUT_RDWR);
            } catch (\Throwable) {
                // Ignore shutdown errors
            }
            @\socket_close($this->socket);
        }

        $this->socket = null;
        $this->connected = false;
        $this->connectedAt = null;
        $this->readBuffer = '';
    }

    /**
     * Reconnect to the server, closing any existing connection first.
     *
     * @return void
     * @throws \Ainos\ConnectionException if reconnection fails
     */
    public function reconnect(): void
    {
        $this->disconnect();
        $this->reconnectionCount++;
        $this->connect();
    }

    /**
     * Check if the transport is currently connected.
     *
     * @return bool
     */
    public function isConnected(): bool
    {
        if (!$this->connected || $this->socket === null) {
            return false;
        }

        // Check if the socket is still valid with a non-blocking write
        // (this is a lightweight check that doesn't send data)
        try {
            $result = @\socket_write($this->socket, '', 0);
            return $result !== false;
        } catch (\Throwable) {
            $this->connected = false;
            return false;
        }
    }

    /**
     * Send raw data over the socket.
     *
     * @param string $data Data to send
     * @return int Number of bytes sent
     * @throws \Ainos\TransportException if not connected
     * @throws \Ainos\TransportException if write fails
     */
    public function send(string $data): int
    {
        if (!$this->isConnected()) {
            throw TransportException::notConnected();
        }

        $totalSent = 0;
        $length = \strlen($data);

        while ($totalSent < $length) {
            $remaining = \substr($data, $totalSent);

            $sent = @\socket_write($this->socket, $remaining, \min(self::BUFFER_SIZE, \strlen($remaining)));

            if ($sent === false) {
                $error = \socket_last_error($this->socket);
                throw TransportException::writeFailed($data, $totalSent, \socket_strerror($error));
            }

            if ($sent === 0) {
                throw TransportException::writeFailed($data, $totalSent, 'Connection closed by peer');
            }

            $totalSent += $sent;
        }

        $this->bytesSent += $totalSent;
        $this->requestCount++;

        return $totalSent;
    }

    /**
     * Send an NDJSON-encoded message.
     *
     * @param array $data Data to encode and send
     * @return int Number of bytes sent
     * @throws \Ainos\InvalidRequestException if encoding fails
     * @throws \Ainos\TransportException if send fails
     */
    public function sendNDJSON(array $data): int
    {
        $payload = NDJSON::encode($data);
        return $this->send($payload);
    }

    /**
     * Receive raw data from the socket.
     *
     * @param int $maxBytes Maximum bytes to read (default: buffer size)
     * @return string|null Received data, or null if no data available (non-blocking)
     * @throws \Ainos\TransportException if read fails
     */
    public function receive(int $maxBytes = self::BUFFER_SIZE): ?string
    {
        if (!$this->isConnected()) {
            throw TransportException::notConnected();
        }

        $data = @\socket_read($this->socket, $maxBytes, \PHP_BINARY_READ);

        if ($data === false) {
            $error = \socket_last_error($this->socket);

            if ($this->nonBlocking && ($error === \SOCKET_EWOULDBLOCK || $error === \SOCKET_EAGAIN)) {
                return null;
            }

            // Connection closed by peer
            if ($error === \SOCKET_ECONNRESET) {
                $this->connected = false;
                throw TransportException::readFailed('Connection reset by peer');
            }

            throw TransportException::readFailed(\socket_strerror($error));
        }

        if ($data === '') {
            // Connection closed by remote peer
            $this->connected = false;
            return '';
        }

        $this->bytesReceived += \strlen($data);
        return $data;
    }

    /**
     * Receive a complete NDJSON line (delimited by newline).
     *
     * @param float|null $timeout Read timeout override (null = use default)
     * @return string|null Complete line (without trailing newline), or null on timeout
     * @throws \Ainos\TransportException if read fails
     * @throws \Ainos\TimeoutException if read times out
     */
    public function receiveLine(?float $timeout = null): ?string
    {
        $timeout = $timeout ?? $this->readTimeout;
        $startTime = Utils::microtimeFloat();

        // Check if we already have a complete line in the buffer
        $newlinePos = \strpos($this->readBuffer, "\n");
        if ($newlinePos !== false) {
            $line = \substr($this->readBuffer, 0, $newlinePos);
            $this->readBuffer = \substr($this->readBuffer, $newlinePos + 1);
            return $line;
        }

        // Read more data until we find a newline or timeout
        while (true) {
            $remaining = $timeout - (Utils::microtimeFloat() - $startTime);

            if ($remaining <= 0) {
                throw TimeoutException::timeout('Read line', $timeout);
            }

            // Use socket_select to implement timeout
            $read = [$this->socket];
            $write = null;
            $except = null;
            $sec = (int)$remaining;
            $usec = (int)(($remaining - $sec) * 1_000_000);

            $result = @\socket_select($read, $write, $except, $sec, $usec);

            if ($result === false) {
                $error = \socket_last_error($this->socket);
                throw TransportException::readFailed(\socket_strerror($error));
            }

            if ($result === 0) {
                throw TimeoutException::timeout('Read line', $timeout);
            }

            $chunk = $this->receive(self::BUFFER_SIZE);

            if ($chunk === null) {
                continue;
            }

            if ($chunk === '') {
                // Connection closed
                if ($this->readBuffer !== '') {
                    // Return whatever we have as the last line
                    $line = $this->readBuffer;
                    $this->readBuffer = '';
                    return $line;
                }
                return null;
            }

            $this->readBuffer .= $chunk;

            // Check if we now have a complete line
            $newlinePos = \strpos($this->readBuffer, "\n");
            if ($newlinePos !== false) {
                $line = \substr($this->readBuffer, 0, $newlinePos);
                $this->readBuffer = \substr($this->readBuffer, $newlinePos + 1);

                // Check for excessively long lines
                if (\strlen($line) > self::MAX_LINE_LENGTH) {
                    throw ProtocolException::invalidJson(
                        $line,
                        \sprintf('Line exceeds maximum length of %d bytes', self::MAX_LINE_LENGTH)
                    );
                }

                return $line;
            }

            // Check if the buffer is getting too large (no newline found in data)
            if (\strlen($this->readBuffer) > self::MAX_LINE_LENGTH) {
                throw ProtocolException::invalidJson(
                    $this->readBuffer,
                    \sprintf('Buffer exceeds maximum line length of %d bytes', self::MAX_LINE_LENGTH)
                );
            }
        }
    }

    /**
     * Receive and decode an NDJSON response.
     *
     * @param float|null $timeout Read timeout override
     * @return array|null Decoded response array, or null if connection closed
     * @throws \Ainos\TransportException if read fails
     * @throws \Ainos\TimeoutException if read times out
     * @throws \Ainos\ProtocolException if JSON decoding fails
     */
    public function receiveResponse(?float $timeout = null): ?array
    {
        $line = $this->receiveLine($timeout);

        if ($line === null) {
            return null;
        }

        $this->responseCount++;

        return NDJSON::decodeLine($line, true);
    }

    /**
     * Send a request and receive a response (convenience method).
     *
     * @param array $request Request data to send
     * @param float|null $timeout Read timeout override
     * @return array Response data
     * @throws \Ainos\TransportException if transport fails
     * @throws \Ainos\TimeoutException if read times out
     * @throws \Ainos\ProtocolException if response is malformed
     */
    public function sendAndReceive(array $request, ?float $timeout = null): array
    {
        $this->sendNDJSON($request);

        $response = $this->receiveResponse($timeout);

        if ($response === null) {
            throw TransportException::readFailed('Connection closed before response received');
        }

        return $response;
    }

    /**
     * Set the socket to blocking mode.
     *
     * @return void
     */
    public function setBlocking(): void
    {
        if ($this->socket !== null) {
            @\socket_set_block($this->socket);
        }
        $this->nonBlocking = false;
    }

    /**
     * Set the socket to non-blocking mode.
     *
     * @return void
     */
    public function setNonBlocking(): void
    {
        if ($this->socket !== null) {
            @\socket_set_nonblock($this->socket);
        }
        $this->nonBlocking = true;
    }

    /**
     * Set the read timeout.
     *
     * @param float $seconds Timeout in seconds
     * @return void
     * @throws \Ainos\ConfigurationException if timeout is invalid
     */
    public function setReadTimeout(float $seconds): void
    {
        if ($seconds <= 0) {
            throw ConfigurationException::invalidSetting('read_timeout', $seconds, 'Timeout must be positive');
        }

        $this->readTimeout = $seconds;
    }

    /**
     * Set the write timeout.
     *
     * @param float $seconds Timeout in seconds
     * @return void
     * @throws \Ainos\ConfigurationException if timeout is invalid
     */
    public function setWriteTimeout(float $seconds): void
    {
        if ($seconds <= 0) {
            throw ConfigurationException::invalidSetting('write_timeout', $seconds, 'Timeout must be positive');
        }

        $this->writeTimeout = $seconds;
    }

    /**
     * Get the host.
     *
     * @return string
     */
    public function getHost(): string
    {
        return $this->host;
    }

    /**
     * Get the port.
     *
     * @return int
     */
    public function getPort(): int
    {
        return $this->port;
    }

    /**
     * Get the connection timeout.
     *
     * @return float
     */
    public function getTimeout(): float
    {
        return $this->timeout;
    }

    /**
     * Get the underlying socket resource (for advanced use).
     *
     * @return \Socket|null
     */
    public function getSocket(): ?\Socket
    {
        return $this->socket;
    }

    /**
     * Get transport statistics.
     *
     * @return array<string, mixed>
     */
    public function getStats(): array
    {
        return [
            'host' => $this->host,
            'port' => $this->port,
            'connected' => $this->connected,
            'connected_at' => $this->connectedAt,
            'connection_duration' => $this->connectedAt !== null
                ? Utils::microtimeFloat() - $this->connectedAt
                : 0.0,
            'bytes_sent' => $this->bytesSent,
            'bytes_received' => $this->bytesReceived,
            'request_count' => $this->requestCount,
            'response_count' => $this->responseCount,
            'reconnection_count' => $this->reconnectionCount,
            'read_timeout' => $this->readTimeout,
            'write_timeout' => $this->writeTimeout,
            'non_blocking' => $this->nonBlocking,
            'buffer_size' => \strlen($this->readBuffer),
        ];
    }

    /**
     * Get the connection duration in seconds.
     *
     * @return float 0.0 if not connected
     */
    public function getConnectionDuration(): float
    {
        if ($this->connectedAt === null) {
            return 0.0;
        }

        return Utils::microtimeFloat() - $this->connectedAt;
    }

    /**
     * Get the number of reconnections performed.
     *
     * @return int
     */
    public function getReconnectionCount(): int
    {
        return $this->reconnectionCount;
    }

    /**
     * Reset transport statistics.
     *
     * @return void
     */
    public function resetStats(): void
    {
        $this->bytesSent = 0;
        $this->bytesReceived = 0;
        $this->requestCount = 0;
        $this->responseCount = 0;
        $this->reconnectionCount = 0;
        $this->lastError = [];
    }

    /**
     * Set the maximum NDJSON line length.
     *
     * @param int $maxLength Maximum line length in bytes
     * @return void
     */
    public function setMaxLineLength(int $maxLength): void
    {
        $this->maxLineLength = $maxLength;
    }

    /**
     * Wait for data to be available on the socket.
     *
     * @param float $timeout Wait timeout in seconds
     * @return bool True if data is available, false if timed out
     * @throws \Ainos\TransportException if select fails
     */
    public function waitForData(float $timeout): bool
    {
        if (!$this->isConnected()) {
            throw TransportException::notConnected();
        }

        $read = [$this->socket];
        $write = null;
        $except = null;
        $sec = (int)$timeout;
        $usec = (int)(($timeout - $sec) * 1_000_000);

        $result = @\socket_select($read, $write, $except, $sec, $usec);

        if ($result === false) {
            $error = \socket_last_error($this->socket);
            throw TransportException::readFailed(\socket_strerror($error));
        }

        return $result > 0;
    }

    /**
     * Check if there is data available to read immediately.
     *
     * @return bool
     */
    public function hasDataAvailable(): bool
    {
        if (!$this->connected || $this->socket === null) {
            return false;
        }

        if ($this->readBuffer !== '') {
            return true;
        }

        return $this->waitForData(0.0);
    }

    /**
     * Flush the internal read buffer, discarding any unread data.
     *
     * @return void
     */
    public function flushBuffer(): void
    {
        $this->readBuffer = '';
    }

    /**
     * Get the amount of unread data in the buffer.
     *
     * @return int
     */
    public function getBufferSize(): int
    {
        return \strlen($this->readBuffer);
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