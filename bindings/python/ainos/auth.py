"""
Ainos SDK - Authentication Module
==================================

Manages Bearer token authentication for the Ainos daemon.

This module provides:
- Token storage and lifecycle management
- Bearer token header generation
- Token validation and refresh support
- Secure token handling (masking in logs)

The Ainos daemon uses Bearer token authentication. The token is sent as an
``Authorization: Bearer <token>`` header within each NDJSON request message's
``auth`` field.

Usage::

    from ainos.auth import AuthManager, AuthConfig

    config = AuthConfig(token="my-secret-token")
    auth = AuthManager(config)
    header = auth.get_auth_header()  # "Bearer my-secret-token"
"""

from __future__ import annotations

import hashlib
import logging
import os
import typing as t

from ainos.errors import AuthenticationError, ConfigurationError

log: logging.Logger = logging.getLogger("ainos.auth")

#: Prefix for the Authorization header value.
BEARER_PREFIX: str = "Bearer "


# ---------------------------------------------------------------------------
# Auth configuration
# ---------------------------------------------------------------------------


class AuthConfig:
    """Configuration for authentication.

    Tokens can be provided explicitly via the ``token`` parameter, or loaded
    from a file or environment variable.

    Attributes:
        token: The Bearer token string.
        token_file: Path to a file containing the token (mutually exclusive
            with ``token``).
        token_env_var: Environment variable name from which to read the token
            (mutually exclusive with ``token`` and ``token_file``).
        auto_refresh: Whether to automatically refresh the token (if the
            daemon supports token refresh).
    """

    def __init__(
        self,
        token: t.Optional[str] = None,
        token_file: t.Optional[str] = None,
        token_env_var: t.Optional[str] = None,
        auto_refresh: bool = False,
    ) -> None:
        """Initialise the auth configuration.

        Args:
            token: The Bearer token string.
            token_file: Path to a file containing the token.
            token_env_var: Environment variable name for the token.
            auto_refresh: Whether to enable automatic token refresh.

        Raises:
            ConfigurationError: If multiple token sources are specified, or
                if none are specified and the token cannot be found.
        """
        self.auto_refresh: bool = auto_refresh
        self._resolved_token: t.Optional[str] = None
        self._source: str = "none"

        sources: int = sum(1 for x in (token, token_file, token_env_var) if x is not None)
        if sources > 1:
            raise ConfigurationError(
                "Multiple token sources specified. Use only one of "
                "token, token_file, or token_env_var.",
                setting="auth",
            )

        if token is not None:
            self._resolved_token = token
            self._source = "explicit"
        elif token_file is not None:
            self._resolved_token = self._read_token_from_file(token_file)
            self._source = f"file:{token_file}"
        elif token_env_var is not None:
            self._resolved_token = self._read_token_from_env(token_env_var)
            self._source = f"env:{token_env_var}"
        else:
            # Try common environment variables
            self._resolved_token = self._discover_token()

        if not self._resolved_token:
            raise ConfigurationError(
                "No authentication token provided. Set the token, "
                "token_file, or token_env_var parameter, or set the "
                "AINOS_AUTH_TOKEN environment variable.",
                setting="auth",
            )

    @property
    def token(self) -> str:
        """Get the resolved authentication token.

        Returns:
            The token string.

        Raises:
            ConfigurationError: If the token has not been resolved.
        """
        if self._resolved_token is None:
            raise ConfigurationError(
                "Token not resolved",
                setting="auth",
            )
        return self._resolved_token

    @property
    def source(self) -> str:
        """Get the source of the authentication token.

        Returns:
            A string describing where the token was obtained
            (e.g. ``"explicit"``, ``"file:/path/to/token"``,
            ``"env:AINOS_AUTH_TOKEN"``).
        """
        return self._source

    @staticmethod
    def _read_token_from_file(path: str) -> str:
        """Read a token from a file.

        Args:
            path: Path to the token file.

        Returns:
            The token string (with leading/trailing whitespace stripped).

        Raises:
            ConfigurationError: If the file cannot be read.
        """
        try:
            expanded: str = os.path.expanduser(path)
            with open(expanded, "r") as f:
                token: str = f.read().strip()
            if not token:
                raise ConfigurationError(
                    f"Token file '{path}' is empty",
                    setting="auth",
                )
            return token
        except FileNotFoundError:
            raise ConfigurationError(
                f"Token file not found: {path}",
                setting="auth",
            )
        except PermissionError:
            raise ConfigurationError(
                f"Permission denied reading token file: {path}",
                setting="auth",
            )
        except OSError as exc:
            raise ConfigurationError(
                f"Failed to read token file '{path}': {exc}",
                setting="auth",
            )

    @staticmethod
    def _read_token_from_env(env_var: str) -> str:
        """Read a token from an environment variable.

        Args:
            env_var: The name of the environment variable.

        Returns:
            The token string.

        Raises:
            ConfigurationError: If the environment variable is not set or
                is empty.
        """
        token: t.Optional[str] = os.environ.get(env_var)
        if not token:
            raise ConfigurationError(
                f"Environment variable '{env_var}' is not set or is empty",
                setting="auth",
            )
        return token.strip()

    @staticmethod
    def _discover_token() -> t.Optional[str]:
        """Try to discover a token from well-known environment variables.

        Checks the following environment variables in order:
        - ``AINOS_AUTH_TOKEN``
        - ``AINOS_TOKEN``
        - ``AUTH_TOKEN``

        Returns:
            The discovered token, or None if no token was found.
        """
        for env_var in ("AINOS_AUTH_TOKEN", "AINOS_TOKEN", "AUTH_TOKEN"):
            token: t.Optional[str] = os.environ.get(env_var)
            if token and token.strip():
                return token.strip()
        return None


# ---------------------------------------------------------------------------
# Token mask
# ---------------------------------------------------------------------------


def mask_token(token: str, visible_chars: int = 4) -> str:
    """Mask a token for safe logging, showing only the last N characters.

    Args:
        token: The token to mask.
        visible_chars: Number of characters to show at the end.

    Returns:
        A masked string like ``"****abcd"``.
    """
    if not token:
        return "****"
    if len(token) <= visible_chars:
        return token
    return "*" * (len(token) - visible_chars) + token[-visible_chars:]


def mask_token_short(token: str, prefix_chars: int = 4, suffix_chars: int = 4) -> str:
    """Mask a token showing only the first and last N characters.

    Args:
        token: The token to mask.
        prefix_chars: Number of characters to show at the start.
        suffix_chars: Number of characters to show at the end.

    Returns:
        A masked string like ``"abcd****wxyz"``.
    """
    if not token:
        return "****"
    if len(token) <= prefix_chars + suffix_chars:
        return token
    return token[:prefix_chars] + "*" * (len(token) - prefix_chars - suffix_chars) + token[-suffix_chars:]


# ---------------------------------------------------------------------------
# AuthManager
# ---------------------------------------------------------------------------


class AuthManager:
    """Manages authentication with the Ainos daemon.

    Handles token storage, Bearer header generation, optional token refresh,
    and token validation.

    The AuthManager is used by the transport layer to attach authentication
    headers to each request.

    Attributes:
        config: The authentication configuration.
        authenticated: Whether authentication has been successful.
    """

    def __init__(self, config: AuthConfig) -> None:
        """Initialise the authentication manager.

        Args:
            config: The authentication configuration.
        """
        self.config: AuthConfig = config
        self._token: str = config.token
        self._authenticated: bool = False
        self._refresh_count: int = 0
        self._last_refresh_time: float = 0.0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def token(self) -> str:
        """Get the current authentication token."""
        return self._token

    @property
    def authenticated(self) -> bool:
        """Whether authentication has been confirmed by the daemon."""
        return self._authenticated

    @property
    def refresh_count(self) -> int:
        """Number of times the token has been refreshed."""
        return self._refresh_count

    # ------------------------------------------------------------------
    # Header generation
    # ------------------------------------------------------------------

    def get_auth_header(self) -> str:
        """Generate the ``Authorization`` header value.

        Returns:
            A string like ``"Bearer <token>"`` suitable for embedding in a
            request message's ``auth`` field.
        """
        return f"{BEARER_PREFIX}{self._token}"

    @staticmethod
    def parse_auth_header(header: str) -> str:
        """Parse a Bearer token from an Authorization header value.

        Args:
            header: The header value (e.g. ``"Bearer <token>"``).

        Returns:
            The extracted token string.

        Raises:
            AuthenticationError: If the header is malformed or missing
                the Bearer prefix.
        """
        if not header.startswith(BEARER_PREFIX):
            raise AuthenticationError(
                "Invalid authorization header format. Expected "
                f"'Bearer <token>', got: {mask_token(header)}",
            )
        return header[len(BEARER_PREFIX):]

    # ------------------------------------------------------------------
    # Token validation
    # ------------------------------------------------------------------

    def validate_token(self, token: t.Optional[str] = None) -> bool:
        """Validate that a token has the expected format.

        Performs basic validation (non-empty, reasonable length).
        Does not verify with the daemon.

        Args:
            token: The token to validate. Uses the stored token if None.

        Returns:
            True if the token appears valid, False otherwise.
        """
        tkn: str = token if token is not None else self._token
        if not tkn or not isinstance(tkn, str):
            return False
        if len(tkn) < 8:
            return False
        if len(tkn) > 4096:
            return False
        return True

    def token_hash(self) -> str:
        """Get a SHA-256 hash of the current token.

        Useful for logging and debugging without exposing the token.

        Returns:
            Hex-encoded SHA-256 hash of the token.
        """
        return hashlib.sha256(self._token.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Authentication state
    # ------------------------------------------------------------------

    def mark_authenticated(self) -> None:
        """Mark the session as authenticated.

        Called after a successful authentication handshake with the daemon.
        """
        self._authenticated = True
        log.info(
            "Authentication successful (token hash: %s)",
            self.token_hash()[:12],
        )

    def mark_unauthenticated(self) -> None:
        """Mark the session as unauthenticated.

        Called when authentication fails or the token is rejected.
        """
        self._authenticated = False
        log.warning("Authentication invalidated")

    # ------------------------------------------------------------------
    # Token refresh
    # ------------------------------------------------------------------

    async def refresh_token(self) -> bool:
        """Refresh the authentication token.

        Re-reads the token from the original source (file or env var).
        This is useful if the token is rotated periodically.

        Returns:
            True if the token was refreshed, False if the source does not
            support refresh.

        Raises:
            AuthenticationError: If the new token is invalid.
        """
        source: str = self.config.source

        if source == "explicit":
            log.warning("Token refresh requested but source is explicit")
            return False

        new_token: t.Optional[str] = None

        if source.startswith("file:"):
            file_path: str = source[5:]
            new_token = AuthConfig._read_token_from_file(file_path)
        elif source.startswith("env:"):
            env_var: str = source[4:]
            new_token = AuthConfig._read_token_from_env(env_var)
        else:
            discovered: t.Optional[str] = AuthConfig._discover_token()
            if discovered:
                new_token = discovered

        if new_token is None:
            log.warning("Token refresh failed: no source available")
            return False

        self._token = new_token
        self._refresh_count += 1
        self._last_refresh_time = 0.0  # Could use time.time() if needed

        log.info(
            "Token refreshed (source: %s, hash: %s)",
            source,
            self.token_hash()[:12],
        )
        return True

    # ------------------------------------------------------------------
    # String representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        """Return a string representation of the auth manager."""
        token_preview: str = mask_token_short(self._token) if self._token else "none"
        return (
            f"AuthManager(token={token_preview}, "
            f"authenticated={self._authenticated}, "
            f"source={self.config.source})"
        )


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def create_auth_manager(
    token: t.Optional[str] = None,
    token_file: t.Optional[str] = None,
    token_env_var: t.Optional[str] = None,
    auto_refresh: bool = False,
) -> AuthManager:
    """Create an AuthManager with the given configuration.

    This is a convenience function that wraps ``AuthConfig`` and
    ``AuthManager`` construction.

    Args:
        token: The Bearer token string.
        token_file: Path to a file containing the token.
        token_env_var: Environment variable name for the token.
        auto_refresh: Whether to enable automatic token refresh.

    Returns:
        A configured AuthManager instance.

    Example:
        auth = create_auth_manager(token_env_var="AINOS_AUTH_TOKEN")
    """
    config: AuthConfig = AuthConfig(
        token=token,
        token_file=token_file,
        token_env_var=token_env_var,
        auto_refresh=auto_refresh,
    )
    return AuthManager(config)


__all__: list[str] = [
    "AuthConfig",
    "AuthManager",
    "create_auth_manager",
    "mask_token",
    "mask_token_short",
]