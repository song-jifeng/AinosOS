<?php

declare(strict_types=1);

namespace Ainos;

/**
 * Ainos - Authentication handler for Bearer token-based authentication.
 *
 * Manages authentication tokens, provides header construction,
 * and handles token validation for the Ainos protocol.
 *
 * @package Ainos
 */
final class Authentication
{
    /**
     * The authentication token.
     *
     * @var string
     */
    private string $token;

    /**
     * Optional token metadata (e.g., expiry, user info).
     *
     * @var array<string, mixed>
     */
    private array $metadata;

    /**
     * Timestamp when this token was created.
     *
     * @var float
     */
    private float $createdAt;

    /**
     * @param string $token The Bearer token for authentication
     * @param array<string, mixed> $metadata Optional token metadata
     * @throws \Ainos\AuthenticationException if the token format is invalid
     */
    public function __construct(string $token, array $metadata = [])
    {
        if (!Utils::validateToken($token)) {
            throw AuthenticationException::invalidTokenFormat(
                'Token must be a non-empty string with only URL-safe characters'
            );
        }

        $this->token = $token;
        $this->metadata = $metadata;
        $this->createdAt = Utils::microtimeFloat();
    }

    /**
     * Get the authentication token.
     *
     * @return string
     */
    public function getToken(): string
    {
        return $this->token;
    }

    /**
     * Create a new instance with a different token.
     *
     * @param string $token The new token
     * @return self
     */
    public function withToken(string $token): self
    {
        return new self($token, $this->metadata);
    }

    /**
     * Get the "Authorization" header value.
     *
     * @return string "Bearer <token>"
     */
    public function getAuthorizationHeader(): string
    {
        return \sprintf('Bearer %s', $this->token);
    }

    /**
     * Get the headers to include in requests.
     *
     * @return array<string, string> Associative array of header name => value
     */
    public function getHeaders(): array
    {
        return [
            'Authorization' => $this->getAuthorizationHeader(),
            'Content-Type' => 'application/x-ndjson',
            'Accept' => 'application/x-ndjson',
        ];
    }

    /**
     * Get authentication data to include in NDJSON request bodies.
     *
     * @return array|null Array with token, or null if token is empty
     */
    public function getAuthPayload(): ?array
    {
        return $this->token !== '' ? ['token' => $this->token] : null;
    }

    /**
     * Check if the token is valid (basic format validation).
     *
     * @return bool
     */
    public function isValid(): bool
    {
        return Utils::validateToken($this->token);
    }

    /**
     * Get a masked preview of the token for logging.
     * Shows only the first 8 and last 4 characters.
     *
     * @return string Masked token string
     */
    public function getTokenPreview(): string
    {
        $length = \strlen($this->token);

        if ($length <= 12) {
            return \str_repeat('*', $length);
        }

        $prefix = \substr($this->token, 0, 8);
        $suffix = \substr($this->token, -4);

        return \sprintf('%s...%s', $prefix, $suffix);
    }

    /**
     * Get a hash of the token (for logging/correlation, not cryptographic).
     *
     * @return string
     */
    public function getTokenHash(): string
    {
        return \sha1($this->token);
    }

    /**
     * Get the token metadata.
     *
     * @return array<string, mixed>
     */
    public function getMetadata(): array
    {
        return $this->metadata;
    }

    /**
     * Get the token age in seconds.
     *
     * @return float
     */
    public function getAge(): float
    {
        return Utils::microtimeFloat() - $this->createdAt;
    }

    /**
     * Get the creation timestamp.
     *
     * @return float
     */
    public function getCreatedAt(): float
    {
        return $this->createdAt;
    }

    /**
     * Create an Authentication instance from an environment variable.
     *
     * @param string $envVarName Environment variable name (default: 'AINOS_TOKEN')
     * @return self
     * @throws \Ainos\AuthenticationException if the environment variable is not set
     */
    public static function fromEnvironment(string $envVarName = 'AINOS_TOKEN'): self
    {
        $token = \getenv($envVarName);

        if ($token === false || $token === '') {
            throw AuthenticationException::missingToken();
        }

        return new self($token);
    }

    /**
     * Create an Authentication instance from a file.
     *
     * @param string $filePath Path to file containing the token
     * @return self
     * @throws \Ainos\AuthenticationException if the file cannot be read
     */
    public static function fromFile(string $filePath): self
    {
        if (!\file_exists($filePath)) {
            throw new AuthenticationException(
                \sprintf('Token file not found: %s', $filePath)
            );
        }

        $token = \trim(\file_get_contents($filePath));

        if ($token === '') {
            throw new AuthenticationException(
                \sprintf('Token file is empty: %s', $filePath)
            );
        }

        return new self($token);
    }

    /**
     * Create an Authentication instance with no token (anonymous access).
     * Useful for testing or when the server allows unauthenticated access.
     *
     * @return self
     */
    public static function anonymous(): self
    {
        return new self('anonymous');
    }

    /**
     * Convert to an array for serialization.
     *
     * @return array<string, mixed>
     */
    public function toArray(): array
    {
        return [
            'token_preview' => $this->getTokenPreview(),
            'token_hash' => $this->getTokenHash(),
            'metadata' => $this->metadata,
            'created_at' => $this->createdAt,
            'age' => $this->getAge(),
        ];
    }

    /**
     * Return the string representation (masked).
     *
     * @return string
     */
    public function __toString(): string
    {
        return $this->getTokenPreview();
    }

    /**
     * Return debug info with sensitive data masked.
     *
     * @return array<string, mixed>
     */
    public function __debugInfo(): array
    {
        return $this->toArray();
    }
}

/**
 * Ainos - Token provider interface for custom authentication strategies.
 *
 * Implement this interface to provide custom token resolution logic,
 * such as token refresh, multi-tenant token resolution, etc.
 *
 * @package Ainos
 */
interface TokenProviderInterface
{
    /**
     * Get the current valid token.
     *
     * @return string
     * @throws \Ainos\AuthenticationException if token cannot be obtained
     */
    public function getToken(): string;

    /**
     * Check if the token needs to be refreshed.
     *
     * @return bool
     */
    public function needsRefresh(): bool;

    /**
     * Refresh the token.
     *
     * @return string The new token
     * @throws \Ainos\AuthenticationException if refresh fails
     */
    public function refresh(): string;
}

/**
 * Ainos - Static token provider (simple wrapper).
 *
 * @package Ainos
 */
final class StaticTokenProvider implements TokenProviderInterface
{
    /** @var Authentication */
    private Authentication $auth;

    /**
     * @param string $token The static token
     */
    public function __construct(string $token)
    {
        $this->auth = new Authentication($token);
    }

    /**
     * @inheritDoc
     */
    public function getToken(): string
    {
        return $this->auth->getToken();
    }

    /**
     * @inheritDoc
     */
    public function needsRefresh(): bool
    {
        return false;
    }

    /**
     * @inheritDoc
     */
    public function refresh(): string
    {
        return $this->auth->getToken();
    }
}

/**
 * Ainos - Environment-based token provider.
 *
 * @package Ainos
 */
final class EnvironmentTokenProvider implements TokenProviderInterface
{
    /** @var string */
    private string $envVarName;

    /** @var Authentication|null */
    private ?Authentication $auth = null;

    /**
     * @param string $envVarName Environment variable name
     */
    public function __construct(string $envVarName = 'AINOS_TOKEN')
    {
        $this->envVarName = $envVarName;
    }

    /**
     * @inheritDoc
     */
    public function getToken(): string
    {
        if ($this->auth === null) {
            $this->auth = Authentication::fromEnvironment($this->envVarName);
        }

        return $this->auth->getToken();
    }

    /**
     * @inheritDoc
     */
    public function needsRefresh(): bool
    {
        return $this->auth === null;
    }

    /**
     * @inheritDoc
     */
    public function refresh(): string
    {
        $this->auth = Authentication::fromEnvironment($this->envVarName);
        return $this->auth->getToken();
    }
}