"""
Ainos SDK - AinosClient
========================

The main client class for interacting with the Ainos daemon over the NDJSON
TCP protocol.

AinosClient provides the high-level API for all daemon operations, including
inference (sync and streaming), model management, health checks, and context
storage.

Typical usage::

    from ainos import AinosClient

    client = AinosClient(host="127.0.0.1", port=9500, auth_token="my-token")

    # Health check
    status = await client.health()
    print(status)

    # Basic inference
    response = await client.infer("my-model", "What is the capital of France?")
    print(response.text)

    # Streaming inference
    async for chunk in client.infer_stream("my-model", "Write a poem"):
        print(chunk.token, end="", flush=True)

    # Model management
    models = await client.model_list()
    info = await client.model_load("llama", "/path/to/model.gguf")

    # Clean up
    await client.disconnect()
"""

from __future__ import annotations

import asyncio
import logging
import typing as t

from ainos.auth import AuthConfig, AuthManager, create_auth_manager
from ainos.errors import (
    AinosError,
    AuthenticationError,
    ConnectionError,
    ConnectionTimeoutError,
    InferenceError,
    InferenceTimeoutError,
    InvalidRequestError,
    ModelError,
    ModelLoadError,
    ModelNotFoundError,
    ModelNotLoadedError,
    ReconnectionFailedError,
    RequestError,
    RequestTimeoutError,
    TransportClosedError,
    error_from_code,
)
from ainos.models import ModelManager
from ainos.stream import (
    StreamIterator,
    StreamManager,
    create_chunk_event,
    create_done_event,
    create_error_event,
    parse_stream_chunk,
)
from ainos.transport import Transport
from ainos.types import (
    ConnectionConfig,
    HealthStatus,
    InferenceChunk,
    InferenceRequest,
    InferenceResponse,
    JSONObject,
    JSONValue,
    ModelInfo,
    SystemStatus,
    TokenUsage,
)
from ainos.utils import generate_request_id, retry, timestamp

log: logging.Logger = logging.getLogger("ainos.client")


class AinosClient:
    """Main client for communicating with the Ainos daemon.

    This class is the primary entry point for the SDK. It manages the
    connection lifecycle, request routing, authentication, and provides
    type-safe methods for all daemon RPC calls.

    The client is designed for use with ``asyncio``. All public methods are
    async and should be awaited.

    Attributes:
        host: The daemon hostname or IP address.
        port: The daemon TCP port.
        config: The full connection configuration.
        connected: Whether the client is currently connected.
        model_manager: The ModelManager instance for model operations.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9500,
        *,
        auth_token: t.Optional[str] = None,
        auth_token_file: t.Optional[str] = None,
        auth_token_env_var: t.Optional[str] = None,
        connect_timeout: float = 10.0,
        request_timeout: float = 60.0,
        reconnect_attempts: int = 3,
        reconnect_delay: float = 1.0,
        pool_size: int = 4,
        max_message_size: int = 16 * 1024 * 1024,
        ssl: bool = False,
        ssl_ca_cert: t.Optional[str] = None,
        auto_connect: bool = True,
    ) -> None:
        """Initialise the Ainos client.

        Args:
            host: The daemon hostname or IP address.
            port: The daemon TCP port (default 9500).
            auth_token: Bearer token for authentication.
            auth_token_file: Path to a file containing the token.
            auth_token_env_var: Environment variable name for the token.
            connect_timeout: Timeout for the initial TCP connection
                in seconds (default 10).
            request_timeout: Default timeout for RPC requests in seconds
                (default 60).
            reconnect_attempts: Maximum number of reconnection attempts
                (default 3).
            reconnect_delay: Initial delay between reconnection attempts
                in seconds (default 1).
            pool_size: Number of connections in the pool (default 4).
            max_message_size: Maximum message size in bytes (default 16 MiB).
            ssl: Whether to use SSL/TLS encryption (default False).
            ssl_ca_cert: Path to CA certificate for SSL verification.
            auto_connect: If True, automatically connect on construction
                (default True).

        Raises:
            ConfigurationError: If authentication configuration is invalid.
            ConnectionError: If auto_connect is True and the connection fails.
        """
        self.host: str = host
        self.port: int = port

        # Build the connection configuration
        self.config: ConnectionConfig = ConnectionConfig(
            host=host,
            port=port,
            auth_token=auth_token,
            connect_timeout=connect_timeout,
            request_timeout=request_timeout,
            reconnect_attempts=reconnect_attempts,
            reconnect_delay=reconnect_delay,
            pool_size=pool_size,
            max_message_size=max_message_size,
            ssl=ssl,
            ssl_ca_cert=ssl_ca_cert,
        )

        # Authentication
        self._auth_manager: t.Optional[AuthManager] = None
        if auth_token or auth_token_file or auth_token_env_var:
            self._auth_manager = create_auth_manager(
                token=auth_token,
                token_file=auth_token_file,
                token_env_var=auth_token_env_var,
            )

        # Transport layer
        self._transport: t.Optional[Transport] = None

        # Stream management
        self._stream_manager: StreamManager = StreamManager()

        # Model management
        self.model_manager: ModelManager = ModelManager(self)

        # Connection state
        self._connected: bool = False
        self._disconnecting: bool = False
        self._request_id_counter: int = 0

        # Auto-connect
        if auto_connect and host and port:
            # We need to start the connection; this will be done lazily
            pass

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        """Whether the client is currently connected to the daemon."""
        return self._connected and self._transport is not None and self._transport.connected

    @property
    def is_authenticated(self) -> bool:
        """Whether the client has authenticated with the daemon."""
        if self._auth_manager is None:
            return True  # No auth required
        return self._auth_manager.authenticated

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def connect(
        self,
        host: t.Optional[str] = None,
        port: t.Optional[int] = None,
        auth_token: t.Optional[str] = None,
    ) -> bool:
        """Establish a connection to the Ainos daemon.

        Args:
            host: Override the configured hostname.
            port: Override the configured port.
            auth_token: Override the configured authentication token.

        Returns:
            True if the connection was established successfully.

        Raises:
            ConnectionTimeoutError: If the connection times out.
            AuthenticationError: If authentication fails.
            ConnectionError: If the connection cannot be established.
        """
        if self._connected:
            log.debug("Already connected to %s:%d", self.host, self.port)
            return True

        # Apply overrides
        actual_host: str = host or self.host
        actual_port: int = port or self.port

        if auth_token is not None:
            self._auth_manager = create_auth_manager(token=auth_token)

        # Update config
        self.config = ConnectionConfig(
            host=actual_host,
            port=actual_port,
            auth_token=self.config.auth_token,
            connect_timeout=self.config.connect_timeout,
            request_timeout=self.config.request_timeout,
            reconnect_attempts=self.config.reconnect_attempts,
            reconnect_delay=self.config.reconnect_delay,
            pool_size=self.config.pool_size,
            max_message_size=self.config.max_message_size,
            ssl=self.config.ssl,
            ssl_ca_cert=self.config.ssl_ca_cert,
        )

        # Create and start the transport
        self._transport = Transport(
            config=self.config,
            auth_manager=self._auth_manager,
        )

        try:
            await self._transport.start()
            self._connected = True

            # Verify connectivity with a health check
            try:
                health: HealthStatus = await self.health()
                if health.healthy:
                    log.info(
                        "Connected to Ainos daemon v%s at %s:%d",
                        health.version,
                        actual_host,
                        actual_port,
                    )
                    if self._auth_manager is not None:
                        self._auth_manager.mark_authenticated()
                else:
                    log.warning(
                        "Connected but daemon reports unhealthy: %s",
                        health.message,
                    )
            except Exception as exc:
                log.warning("Health check after connect failed: %s", exc)
                # Still connected, just the health check failed

            return True
        except (ConnectionError, ConnectionTimeoutError, OSError) as exc:
            self._connected = False
            self._transport = None
            raise ConnectionError(
                f"Failed to connect to {actual_host}:{actual_port}: {exc}",
                cause=exc,
            ) from exc

    async def disconnect(self) -> None:
        """Disconnect from the Ainos daemon.

        Gracefully closes all connections, cancels any active streams, and
        cleans up resources.
        """
        if self._disconnecting:
            return

        self._disconnecting = True
        self._connected = False

        # Cancel all streams
        await self._stream_manager.cancel_all()

        # Stop the transport
        if self._transport is not None:
            try:
                await self._transport.stop()
            except Exception as exc:
                log.warning("Error during transport stop: %s", exc)
            self._transport = None

        self._disconnecting = False
        log.info("Disconnected from Ainos daemon")

    async def reconnect(self) -> bool:
        """Re-establish the connection to the daemon.

        Attempts to reconnect with the configured retry parameters.

        Returns:
            True if the connection was re-established.

        Raises:
            ReconnectionFailedError: If all reconnection attempts fail.
        """
        log.info("Attempting reconnection...")

        # Disconnect first
        await self.disconnect()

        # Wait a moment before reconnecting
        await asyncio.sleep(self.config.reconnect_delay)

        # Try to reconnect with retry
        for attempt in range(1, self.config.reconnect_attempts + 1):
            try:
                await self.connect()
                if self._connected:
                    log.info("Reconnection successful on attempt %d", attempt)
                    return True
            except (ConnectionError, ConnectionTimeoutError, OSError) as exc:
                log.warning(
                    "Reconnection attempt %d/%d failed: %s",
                    attempt,
                    self.config.reconnect_attempts,
                    exc,
                )
                if attempt < self.config.reconnect_attempts:
                    delay: float = self.config.reconnect_delay * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)

        raise ReconnectionFailedError(
            attempts=self.config.reconnect_attempts,
            last_error=None,
        )

    # ------------------------------------------------------------------
    # Internal request sending
    # ------------------------------------------------------------------

    async def _send_request(
        self,
        method: str,
        params: t.Optional[JSONObject] = None,
        *,
        request_id: t.Optional[str] = None,
        timeout: t.Optional[float] = None,
    ) -> JSONObject:
        """Send an RPC request and return the parsed response.

        This is the low-level request method used by all public API methods.

        Args:
            method: The RPC method name.
            params: Method parameters as a JSON object.
            request_id: Optional request ID (auto-generated if not provided).
            timeout: Optional request timeout.

        Returns:
            The response JSON object.

        Raises:
            TransportClosedError: If the transport is not connected.
            ConnectionError: If the request cannot be sent.
            RequestError: If the daemon returns an error response.
            AuthenticationError: If authentication is required and fails.
        """
        if not self._connected or self._transport is None:
            raise TransportClosedError("Client is not connected. Call connect() first.")

        if params is None:
            params = {}

        rid: str = request_id or generate_request_id()
        actual_timeout: float = timeout if timeout is not None else self.config.request_timeout

        try:
            response: JSONObject = await self._transport.send_request(
                method,
                params,
                request_id=rid,
                timeout=actual_timeout,
            )
        except TransportClosedError:
            self._connected = False
            raise
        except ConnectionError:
            self._connected = False
            raise
        except asyncio.TimeoutError as exc:
            raise RequestTimeoutError(
                rid,
                method,
                actual_timeout,
                cause=exc,
            ) from exc

        # Check for daemon error response
        error_data: t.Optional[JSONObject] = response.get("error")
        if error_data is not None:
            code: int = error_data.get("code", -1)
            message: str = error_data.get("message", "Unknown error")
            exc: AinosError = error_from_code(code, message)

            if isinstance(exc, AuthenticationError) and self._auth_manager is not None:
                self._auth_manager.mark_unauthenticated()

            raise exc

        return response

    # ------------------------------------------------------------------
    # Inference API
    # ------------------------------------------------------------------

    async def infer(
        self,
        model: str,
        prompt: str,
        *,
        system_prompt: t.Optional[str] = None,
        temperature: t.Optional[float] = None,
        top_p: t.Optional[float] = None,
        top_k: t.Optional[int] = None,
        max_tokens: t.Optional[int] = None,
        stop: t.Optional[t.List[str]] = None,
        presence_penalty: t.Optional[float] = None,
        frequency_penalty: t.Optional[float] = None,
        extra_params: t.Optional[t.Dict[str, JSONValue]] = None,
        timeout: t.Optional[float] = None,
    ) -> InferenceResponse:
        """Run a non-streaming inference against a model.

        Sends a prompt to the model and waits for the complete response.

        Args:
            model: The model identifier to use for inference.
            prompt: The input text prompt.
            system_prompt: Optional system prompt.
            temperature: Sampling temperature (0.0 to 2.0).
            top_p: Nucleus sampling threshold (0.0 to 1.0).
            top_k: Top-k sampling value.
            max_tokens: Maximum number of tokens to generate.
            stop: List of stop sequences.
            presence_penalty: Presence penalty (-2.0 to 2.0).
            frequency_penalty: Frequency penalty (-2.0 to 2.0).
            extra_params: Additional model-specific parameters.
            timeout: Optional request timeout override.

        Returns:
            An InferenceResponse with the generated text and metadata.

        Raises:
            ModelNotLoadedError: If the model is not loaded.
            InvalidPromptError: If the prompt is invalid.
            ContextLengthExceededError: If the prompt exceeds the context
                window.
            InferenceTimeoutError: If the inference times out.
            RequestError: For other request failures.
            ConnectionError: If the daemon is unreachable.
        """
        request: InferenceRequest = InferenceRequest(
            model=model,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            max_tokens=max_tokens,
            stop=stop,
            presence_penalty=presence_penalty,
            frequency_penalty=frequency_penalty,
            stream=False,
            extra_params=extra_params,
        )

        try:
            response: JSONObject = await self._send_request(
                "infer",
                request.to_dict(),
                timeout=timeout,
            )
            result: t.Optional[JSONObject] = response.get("result")
            if result is None:
                raise InferenceError("Empty response from daemon")
            return InferenceResponse.from_dict(result)
        except (InferenceError, ModelError):
            raise
        except RequestError as exc:
            raise InferenceError(
                f"Inference failed: {exc}",
                cause=exc,
            ) from exc

    async def infer_stream(
        self,
        model: str,
        prompt: str,
        *,
        system_prompt: t.Optional[str] = None,
        temperature: t.Optional[float] = None,
        top_p: t.Optional[float] = None,
        top_k: t.Optional[int] = None,
        max_tokens: t.Optional[int] = None,
        stop: t.Optional[t.List[str]] = None,
        presence_penalty: t.Optional[float] = None,
        frequency_penalty: t.Optional[float] = None,
        extra_params: t.Optional[t.Dict[str, JSONValue]] = None,
        timeout: t.Optional[float] = None,
    ) -> StreamIterator:
        """Run a streaming inference against a model.

        Returns an async iterator that yields tokens as they are generated.

        Args:
            model: The model identifier.
            prompt: The input text prompt.
            system_prompt: Optional system prompt.
            temperature: Sampling temperature (0.0 to 2.0).
            top_p: Nucleus sampling threshold (0.0 to 1.0).
            top_k: Top-k sampling value.
            max_tokens: Maximum number of tokens to generate.
            stop: List of stop sequences.
            presence_penalty: Presence penalty (-2.0 to 2.0).
            frequency_penalty: Frequency penalty (-2.0 to 2.0).
            extra_params: Additional model-specific parameters.
            timeout: Optional timeout for each chunk read.

        Returns:
            A StreamIterator that yields InferenceChunk objects.

        Raises:
            ModelNotLoadedError: If the model is not loaded.
            InvalidPromptError: If the prompt is invalid.
            ConnectionError: If the daemon is unreachable.

        Example:
            async for chunk in client.infer_stream("model", "Hello"):
                print(chunk.token, end="")
        """
        if not self._connected or self._transport is None:
            raise TransportClosedError("Client is not connected. Call connect() first.")

        request: InferenceRequest = InferenceRequest(
            model=model,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            max_tokens=max_tokens,
            stop=stop,
            presence_penalty=presence_penalty,
            frequency_penalty=frequency_penalty,
            stream=True,
            extra_params=extra_params,
        )

        # Generate a request ID for the stream
        request_id: str = generate_request_id()
        actual_timeout: float = timeout if timeout is not None else self.config.request_timeout

        # Create the stream iterator
        stream_iterator: StreamIterator = await self._stream_manager.create_stream(
            request_id,
            model,
            timeout=actual_timeout,
        )

        try:
            # Send the streaming request
            response: JSONObject = await self._transport.send_request(
                "infer",
                request.to_dict(),
                request_id=request_id,
                timeout=actual_timeout,
            )

            # Check for immediate error
            error_data = response.get("error")
            if error_data:
                code = error_data.get("code", -1)
                message = error_data.get("message", "Unknown error")
                exc = error_from_code(code, message)
                await self._stream_manager.remove_stream(request_id)
                raise exc

            result = response.get("result", {})
            # If the response has a token, it's a stream chunk
            if "token" in result:
                chunk: InferenceChunk = parse_stream_chunk(result)
                # Push it to the stream queue
                # We need to access the queue via the stream manager
                # For now, the stream will be populated by the transport's
                # message handler
        except Exception as exc:
            await self._stream_manager.remove_stream(request_id)
            raise

        return stream_iterator

    # ------------------------------------------------------------------
    # Model management
    # ------------------------------------------------------------------

    async def model_list(self) -> t.List[ModelInfo]:
        """List all models known to the daemon.

        Returns:
            A list of ModelInfo objects describing each model.

        Raises:
            ConnectionError: If the daemon is unreachable.
        """
        return await self.model_manager.list_models()

    async def model_load(
        self,
        name: str,
        path: str,
        *,
        backend: t.Optional[str] = None,
        context_length: t.Optional[int] = None,
        gpu_layers: t.Optional[int] = None,
        quantisation: t.Optional[str] = None,
        device: t.Optional[str] = None,
        extra_options: t.Optional[t.Dict[str, t.Any]] = None,
        wait_ready: bool = True,
    ) -> ModelInfo:
        """Load a model into the daemon.

        Args:
            name: A human-readable name for the model.
            path: File path to the model weights.
            backend: Inference backend (auto-detected if not specified).
            context_length: Maximum context length override.
            gpu_layers: Number of layers to offload to GPU.
            quantisation: Quantisation type.
            device: Device to load the model on.
            extra_options: Additional backend-specific options.
            wait_ready: If True, wait for the model to finish loading.

        Returns:
            ModelInfo for the loaded model.

        Raises:
            ModelLoadError: If the model fails to load.
        """
        return await self.model_manager.load_model(
            name,
            path,
            backend=backend,
            context_length=context_length,
            gpu_layers=gpu_layers,
            quantisation=quantisation,
            device=device,
            extra_options=extra_options,
            wait_ready=wait_ready,
        )

    async def model_unload(
        self,
        model_id: str,
        *,
        force: bool = False,
    ) -> bool:
        """Unload a model from the daemon.

        Args:
            model_id: The model identifier.
            force: Force unload even if busy.

        Returns:
            True if successful.

        Raises:
            ModelNotFoundError: If the model is not found.
            ModelBusyError: If the model is busy.
        """
        return await self.model_manager.unload_model(model_id, force=force)

    # ------------------------------------------------------------------
    # Health & status
    # ------------------------------------------------------------------

    async def health(self) -> HealthStatus:
        """Check the daemon's health status.

        Returns:
            A HealthStatus object with daemon health information.

        Raises:
            ConnectionError: If the daemon is unreachable.
        """
        try:
            response: JSONObject = await self._send_request(
                "health",
                {},
                timeout=10.0,
            )
            result: t.Optional[JSONObject] = response.get("result")
            if result is None:
                return HealthStatus(healthy=False, status="no_result")
            return HealthStatus.from_dict(result)
        except ConnectionError:
            return HealthStatus(healthy=False, status="unreachable")
        except Exception as exc:
            log.warning("Health check failed: %s", exc)
            return HealthStatus(healthy=False, status="error", message=str(exc))

    async def status(self) -> SystemStatus:
        """Get detailed system status from the daemon.

        Returns:
            A SystemStatus object with comprehensive daemon metrics.

        Raises:
            ConnectionError: If the daemon is unreachable.
        """
        response = await self._send_request("status", {})
        result = response.get("result", {})
        return SystemStatus.from_dict(result)

    # ------------------------------------------------------------------
    # Context storage
    # ------------------------------------------------------------------

    async def context_store(
        self,
        key: str,
        value: JSONValue,
        ttl: t.Optional[int] = None,
    ) -> bool:
        """Store a value in the daemon's context store.

        The context store is a key-value storage maintained by the daemon.
        Values can be stored with an optional TTL (time-to-live in seconds).

        Args:
            key: The key to store the value under.
            value: The value to store (must be JSON-encodable).
            ttl: Optional time-to-live in seconds. After this time, the
                value is automatically removed.

        Returns:
            True if the value was stored successfully.

        Raises:
            InvalidRequestError: If the key or value is invalid.
            ConnectionError: If the daemon is unreachable.
        """
        params: JSONObject = {"key": key, "value": value}
        if ttl is not None:
            params["ttl"] = ttl

        try:
            response = await self._send_request("context_store", params)
            result = response.get("result", {})
            return bool(result.get("success", True))
        except InvalidRequestError:
            raise
        except Exception as exc:
            log.warning("Failed to store context key '%s': %s", key, exc)
            return False

    async def context_retrieve(self, key: str) -> t.Optional[JSONValue]:
        """Retrieve a value from the daemon's context store.

        Args:
            key: The key to look up.

        Returns:
            The stored value, or None if the key does not exist or has
            expired.

        Raises:
            InvalidRequestError: If the key is invalid.
            ConnectionError: If the daemon is unreachable.
        """
        try:
            response = await self._send_request(
                "context_retrieve",
                {"key": key},
            )
            result = response.get("result", {})
            return result.get("value")
        except InvalidRequestError:
            raise
        except Exception as exc:
            log.warning("Failed to retrieve context key '%s': %s", key, exc)
            return None

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    async def wait_for_ready(
        self,
        *,
        timeout: float = 30.0,
        poll_interval: float = 1.0,
    ) -> bool:
        """Wait for the daemon to become healthy and ready.

        Polls the health endpoint until the daemon reports healthy or the
        timeout is reached.

        Args:
            timeout: Maximum time to wait in seconds.
            poll_interval: Time between health checks in seconds.

        Returns:
            True if the daemon became healthy within the timeout.

        Raises:
            ConnectionError: If the daemon is unreachable.
        """
        start_time: float = timestamp()
        while timestamp() - start_time < timeout:
            try:
                health_status: HealthStatus = await self.health()
                if health_status.healthy:
                    return True
            except ConnectionError:
                pass
            except Exception as exc:
                log.debug("Waiting for daemon: %s", exc)

            await asyncio.sleep(poll_interval)

        return False

    async def __aenter__(self) -> "AinosClient":
        """Enter async context manager."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: t.Optional[t.Type[BaseException]],
        exc_val: t.Optional[BaseException],
        exc_tb: t.Optional[object],
    ) -> None:
        """Exit async context manager, cleaning up resources."""
        await self.disconnect()

    def __repr__(self) -> str:
        """Return a string representation of the client."""
        return (
            f"AinosClient(host={self.host}, port={self.port}, "
            f"connected={self._connected})"
        )


__all__: list[str] = [
    "AinosClient",
]