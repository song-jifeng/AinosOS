"""
Ainos SDK - TCP Transport Layer
================================

Provides the low-level TCP transport for communicating with the Ainos daemon
using the NDJSON (Newline-Delimited JSON) protocol.

The transport layer handles:
- TCP connection establishment and teardown
- Connection pooling with configurable pool size
- Automatic reconnection with exponential backoff
- Message framing (newline-delimited JSON)
- Read and write buffering
- Timeout management
- SSL/TLS encryption support

Architecture::

    ┌──────────────┐     ┌──────────────┐     ┌────────────────┐
    │  AinosClient │────▶│  Transport   │────▶│  TCP Socket    │
    │              │     │  (conn pool) │     │  (to daemon)   │
    └──────────────┘     └──────────────┘     └────────────────┘
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import ssl
import typing as t
from collections import deque

from ainos.auth import AuthManager, AuthConfig
from ainos.errors import (
    AuthenticationError,
    ConnectionError,
    ConnectionTimeoutError,
    MessageTooLargeError,
    ProtocolError,
    InvalidMessageError,
    ReconnectionFailedError,
    TransportClosedError,
    TransportBufferFullError,
)
from ainos.types import (
    ConnectionConfig,
    JSONObject,
    RequestMessage,
    ResponseMessage,
    StreamMessage,
)
from ainos.utils import (
    generate_request_id,
    json_decode,
    json_encode,
    monotonic_ns,
    retry,
    timestamp,
    truncate,
)

log: logging.Logger = logging.getLogger("ainos.transport")

# Default message size limit: 16 MiB
_DEFAULT_MAX_MESSAGE_SIZE: int = 16 * 1024 * 1024

# Default buffer size for socket reads
_DEFAULT_READ_SIZE: int = 64 * 1024

# Maximum number of concurrent pending requests per connection
_MAX_PENDING_REQUESTS: int = 1024


# ---------------------------------------------------------------------------
# Transport connection
# ---------------------------------------------------------------------------


class TransportConnection:
    """A single TCP connection to the Ainos daemon.

    This class manages one TCP socket connection, handling message framing,
    read/write operations, and connection lifecycle.

    Attributes:
        host: The remote host.
        port: The remote port.
        config: The connection configuration.
        connected: Whether the connection is currently established.
        closed: Whether the connection has been permanently closed.
    """

    def __init__(
        self,
        host: str,
        port: int,
        config: ConnectionConfig,
        auth_manager: t.Optional[AuthManager] = None,
    ) -> None:
        """Initialise the connection.

        Args:
            host: The remote hostname or IP address.
            port: The remote TCP port.
            config: Connection configuration parameters.
            auth_manager: Optional authentication manager for token
                management.
        """
        self.host: str = host
        self.port: int = port
        self.config: ConnectionConfig = config
        self._auth_manager: t.Optional[AuthManager] = auth_manager

        # Socket and I/O
        self._reader: t.Optional[asyncio.StreamReader] = None
        self._writer: t.Optional[asyncio.StreamWriter] = None
        self._connected: bool = False
        self._closed: bool = False

        # Read buffer for partial messages
        self._read_buffer: bytearray = bytearray()

        # Pending request tracking
        self._pending_requests: t.Dict[str, asyncio.Future[JSONObject]] = {}
        self._pending_lock: asyncio.Lock = asyncio.Lock()

        # Background reader task
        self._reader_task: t.Optional[asyncio.Task[None]] = None

        # Connection metadata
        self._connected_at: float = 0.0
        self._bytes_sent: int = 0
        self._bytes_received: int = 0
        self._request_count: int = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        """Whether the connection is currently established."""
        return self._connected and not self._closed

    @property
    def closed(self) -> bool:
        """Whether the connection has been permanently closed."""
        return self._closed

    @property
    def connected_at(self) -> float:
        """Unix timestamp when the connection was established (0 if not connected)."""
        return self._connected_at

    @property
    def bytes_sent(self) -> int:
        """Total bytes sent over this connection."""
        return self._bytes_sent

    @property
    def bytes_received(self) -> int:
        """Total bytes received over this connection."""
        return self._bytes_received

    @property
    def request_count(self) -> int:
        """Total requests sent over this connection."""
        return self._request_count

    @property
    def pending_count(self) -> int:
        """Number of requests currently awaiting a response."""
        return len(self._pending_requests)

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Establish the TCP connection to the daemon.

        Creates the socket, connects to the remote endpoint, and starts the
        background reader task that processes incoming messages.

        Raises:
            ConnectionTimeoutError: If the connection times out.
            ConnectionError: If the connection cannot be established.
            AuthenticationError: If authentication with the daemon fails.
        """
        if self._closed:
            raise TransportClosedError()

        if self._connected:
            log.debug("Already connected to %s:%d", self.host, self.port)
            return

        try:
            log.info("Connecting to %s:%d...", self.host, self.port)

            # Create SSL context if needed
            ssl_context: t.Optional[ssl.SSLContext] = None
            if self.config.ssl:
                ssl_context = ssl.create_default_context(
                    cafile=self.config.ssl_ca_cert
                )

            # Open the connection (with timeout)
            connect_coro = asyncio.open_connection(
                host=self.host,
                port=self.port,
                ssl=ssl_context,
                limit=self.config.max_buffer_size,
            )

            try:
                self._reader, self._writer = await asyncio.wait_for(
                    connect_coro,
                    timeout=self.config.connect_timeout,
                )
            except asyncio.TimeoutError as exc:
                raise ConnectionTimeoutError(
                    self.host,
                    self.port,
                    self.config.connect_timeout,
                    cause=exc,
                ) from exc

            self._connected = True
            self._connected_at = timestamp()

            # Start the background reader task
            self._reader_task = asyncio.create_task(self._read_loop())

            log.info(
                "Connected to %s:%d (connection established)",
                self.host,
                self.port,
            )
        except (OSError, socket.gaierror) as exc:
            self._connected = False
            raise ConnectionError(
                f"Failed to connect to {self.host}:{self.port}: {exc}",
                cause=exc,
            ) from exc

    async def disconnect(self) -> None:
        """Gracefully close the connection.

        Cancels the background reader task, waits for pending requests to
        complete or fail, and closes the socket.
        """
        if self._closed:
            return

        self._closed = True
        self._connected = False

        # Cancel the reader task
        if self._reader_task is not None and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        # Fail all pending requests
        async with self._pending_lock:
            pending: t.Dict[str, asyncio.Future[JSONObject]] = self._pending_requests
            self._pending_requests = {}
            for request_id, future in pending.items():
                if not future.done():
                    future.set_exception(TransportClosedError())

        # Close the socket
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None

        self._reader = None
        log.info("Disconnected from %s:%d", self.host, self.port)

    # ------------------------------------------------------------------
    # Send / receive
    # ------------------------------------------------------------------

    async def send_request(
        self,
        method: str,
        params: t.Optional[JSONObject] = None,
        *,
        request_id: t.Optional[str] = None,
        timeout: t.Optional[float] = None,
    ) -> JSONObject:
        """Send a request and wait for the response.

        This is the primary method for making RPC calls. It sends the request
        and returns the response JSON object.

        Args:
            method: The RPC method name.
            params: Method parameters (JSON object).
            request_id: Optional request ID. Generated automatically if not
                provided.
            timeout: Optional request timeout. Uses the config default if not
                specified.

        Returns:
            The response JSON object.

        Raises:
            TransportClosedError: If the transport is closed.
            ConnectionError: If the connection is lost.
            RequestTimeoutError: If the request times out.
            ProtocolError: If the response is malformed.
        """
        if self._closed:
            raise TransportClosedError()

        if params is None:
            params = {}

        rid: str = request_id or generate_request_id()
        actual_timeout: float = timeout if timeout is not None else self.config.request_timeout

        # Create the future for this request
        future: asyncio.Future[JSONObject] = asyncio.get_event_loop().create_future()

        async with self._pending_lock:
            if len(self._pending_requests) >= _MAX_PENDING_REQUESTS:
                raise TransportBufferFullError(
                    len(self._pending_requests),
                    _MAX_PENDING_REQUESTS,
                )
            self._pending_requests[rid] = future

        try:
            # Build and send the request message
            auth_header: t.Optional[str] = None
            if self._auth_manager is not None:
                auth_header = self._auth_manager.get_auth_header()

            msg: RequestMessage = RequestMessage(
                id=rid,
                method=method,
                params=params,
                auth=auth_header,
            )

            await self._send_message(msg)

            # Wait for the response
            try:
                response: JSONObject = await asyncio.wait_for(
                    future,
                    timeout=actual_timeout,
                )
                return response
            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"Request '{rid}' ({method}) timed out after {actual_timeout}s"
                )
        except Exception:
            # Clean up the pending future on error
            async with self._pending_lock:
                if rid in self._pending_requests:
                    del self._pending_requests[rid]
            raise

    async def send_streaming_request(
        self,
        method: str,
        params: t.Optional[JSONObject] = None,
        *,
        request_id: t.Optional[str] = None,
    ) -> str:
        """Send a request that expects a streaming response.

        Unlike :meth:`send_request`, this method returns immediately after
        sending the request. The caller should use :meth:`read_stream_chunk`
        to read streaming chunks.

        Args:
            method: The RPC method name.
            params: Method parameters.
            request_id: Optional request ID.

        Returns:
            The request ID that can be used to read stream chunks.

        Raises:
            TransportClosedError: If the transport is closed.
        """
        if self._closed:
            raise TransportClosedError()

        if params is None:
            params = {}

        rid: str = request_id or generate_request_id()

        # Create a future for the stream (not completed until the stream ends)
        future: asyncio.Future[JSONObject] = asyncio.get_event_loop().create_future()

        async with self._pending_lock:
            self._pending_requests[rid] = future

        auth_header: t.Optional[str] = None
        if self._auth_manager is not None:
            auth_header = self._auth_manager.get_auth_header()

        msg: RequestMessage = RequestMessage(
            id=rid,
            method=method,
            params=params,
            auth=auth_header,
        )

        await self._send_message(msg)
        return rid

    async def _send_message(self, msg: RequestMessage) -> None:
        """Encode and send a request message over the wire.

        Args:
            msg: The request message to send.

        Raises:
            MessageTooLargeError: If the encoded message exceeds the size limit.
            ConnectionError: If the socket write fails.
        """
        if not self._connected or self._writer is None:
            raise ConnectionError("Not connected")

        data: bytes = json_encode(msg.to_dict())

        # Check message size
        if len(data) > self.config.max_message_size:
            raise MessageTooLargeError(
                len(data),
                self.config.max_message_size,
                direction="send",
            )

        try:
            self._writer.write(data)
            await self._writer.drain()
            self._bytes_sent += len(data)
            self._request_count += 1
            log.debug("Sent request %s: %s", msg.id, msg.method)
        except (OSError, ConnectionError) as exc:
            self._connected = False
            raise ConnectionError(
                f"Failed to send message: {exc}",
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Background reader
    # ------------------------------------------------------------------

    async def _read_loop(self) -> None:
        """Background task that reads and dispatches incoming messages.

        This runs as a separate asyncio task for the lifetime of the
        connection. It reads raw bytes from the socket, splits on newlines,
        parses JSON, and routes responses to the appropriate pending future.
        """
        try:
            while self._connected and not self._closed:
                # Read data from the socket
                try:
                    chunk: bytes = await asyncio.wait_for(
                        self._reader.read(_DEFAULT_READ_SIZE),
                        timeout=None,  # No timeout on reads (keepalive handles it)
                    )
                except asyncio.TimeoutError:
                    continue
                except (OSError, ConnectionError) as exc:
                    if not self._closed:
                        log.warning("Read error: %s", exc)
                        self._connected = False
                    break

                if not chunk:
                    # Connection closed by remote
                    log.info("Connection closed by remote: %s:%d", self.host, self.port)
                    self._connected = False
                    break

                self._bytes_received += len(chunk)
                self._read_buffer.extend(chunk)

                # Process complete messages (newline-delimited)
                await self._process_buffer()

        except asyncio.CancelledError:
            log.debug("Reader task cancelled")
            raise
        except Exception as exc:
            log.error("Reader task error: %s", exc, exc_info=True)
        finally:
            self._connected = False
            # Fail all pending requests
            async with self._pending_lock:
                pending = self._pending_requests
                self._pending_requests = {}
                for request_id, future in pending.items():
                    if not future.done():
                        future.set_exception(
                            ConnectionError("Connection lost", cause=None)
                        )

    async def _process_buffer(self) -> None:
        """Process the read buffer, extracting complete NDJSON messages.

        Splits the buffer on newline characters and dispatches each complete
        JSON object to the appropriate handler.
        """
        while b"\n" in self._read_buffer:
            line, self._read_buffer = self._read_buffer.split(b"\n", 1)

            line = line.strip()
            if not line:
                continue

            # Check message size
            if len(line) > self.config.max_message_size:
                log.warning(
                    "Received message exceeds size limit: %d bytes",
                    len(line),
                )
                continue

            try:
                data: JSONObject = json_decode(line)
                await self._dispatch_message(data)
            except ValueError as exc:
                log.warning(
                    "Failed to parse message: %s (data: %s)",
                    exc,
                    truncate(line.decode("utf-8", errors="replace"), 200),
                )
                continue

    async def _dispatch_message(self, data: JSONObject) -> None:
        """Route a parsed message to the appropriate handler.

        Args:
            data: The parsed JSON message.

        Raises:
            InvalidMessageError: If the message type is unknown.
        """
        msg_type: str = data.get("type", "")
        msg_id: str = data.get("id", "")

        if msg_type == "response":
            await self._handle_response(msg_id, data)
        elif msg_type == "stream":
            await self._handle_stream(msg_id, data)
        elif msg_type == "error":
            await self._handle_response(msg_id, data)
        else:
            log.warning("Unknown message type: %s", msg_type)

    async def _handle_response(self, request_id: str, data: JSONObject) -> None:
        """Handle a response message by completing the pending future.

        Args:
            request_id: The ID of the request this response corresponds to.
            data: The response data.
        """
        async with self._pending_lock:
            future: t.Optional[asyncio.Future[JSONObject]] = self._pending_requests.pop(
                request_id, None
            )

        if future is None:
            log.warning("Received response for unknown request: %s", request_id)
            return

        if not future.done():
            future.set_result(data)

    async def _handle_stream(self, request_id: str, data: JSONObject) -> None:
        """Handle a stream chunk by appending it to the pending future.

        The stream data is accumulated in the future's result. When the
        final chunk is received, the future is completed.

        Args:
            request_id: The ID of the originating request.
            data: The stream chunk data.
        """
        async with self._pending_lock:
            future = self._pending_requests.get(request_id)

        if future is None:
            log.warning("Received stream chunk for unknown request: %s", request_id)
            return

        stream_data: JSONObject = data.get("data", {})
        is_final: bool = stream_data.get("final", False)

        if is_final:
            # Complete the future with the final data
            async with self._pending_lock:
                self._pending_requests.pop(request_id, None)
            if not future.done():
                future.set_result(data)
        else:
            # For streaming, we set the result incrementally.
            # The stream iterator reads from an intermediate queue.
            pass

    # ------------------------------------------------------------------
    # Health / stats
    # ------------------------------------------------------------------

    def get_stats(self) -> t.Dict[str, t.Any]:
        """Get connection statistics.

        Returns:
            A dictionary of connection statistics.
        """
        return {
            "host": self.host,
            "port": self.port,
            "connected": self._connected,
            "closed": self._closed,
            "connected_at": self._connected_at,
            "bytes_sent": self._bytes_sent,
            "bytes_received": self._bytes_received,
            "request_count": self._request_count,
            "pending_count": len(self._pending_requests),
            "buffer_size": len(self._read_buffer),
        }

    def __repr__(self) -> str:
        """Return a string representation of the connection."""
        status: str = "connected" if self._connected else "disconnected"
        return (
            f"TransportConnection({self.host}:{self.port}, {status}, "
            f"pending={len(self._pending_requests)})"
        )


# ---------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------


class ConnectionPool:
    """Manages a pool of TCP connections to the Ainos daemon.

    The pool maintains multiple connections for concurrent request handling.
    Connections are checked out round-robin style.

    Attributes:
        host: The remote host.
        port: The remote port.
        config: Connection configuration.
        pool_size: Maximum number of connections in the pool.
    """

    def __init__(
        self,
        host: str,
        port: int,
        config: ConnectionConfig,
        auth_manager: t.Optional[AuthManager] = None,
    ) -> None:
        """Initialise the connection pool.

        Args:
            host: The remote hostname or IP address.
            port: The remote TCP port.
            config: Connection configuration.
            auth_manager: Optional authentication manager.
        """
        self.host: str = host
        self.port: int = port
        self.config: ConnectionConfig = config
        self._auth_manager: t.Optional[AuthManager] = auth_manager
        self.pool_size: int = config.pool_size

        self._connections: t.List[TransportConnection] = []
        self._lock: asyncio.Lock = asyncio.Lock()
        self._next_index: int = 0
        self._started: bool = False
        self._stopped: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialise all connections in the pool.

        Creates and connects all pool connections. If some connections fail,
        the pool will still operate with the successfully connected ones.

        Raises:
            ConnectionError: If no connections could be established.
        """
        if self._stopped:
            raise TransportClosedError("Pool is stopped")

        if self._started:
            return

        self._started = True

        async with self._lock:
            tasks: list[asyncio.Task[None]] = []
            for i in range(self.pool_size):
                conn = TransportConnection(
                    self.host,
                    self.port,
                    self.config,
                    auth_manager=self._auth_manager,
                )
                self._connections.append(conn)
                tasks.append(asyncio.create_task(self._connect_safe(conn, i)))

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        # Check if at least one connection succeeded
        connected_count: int = sum(1 for c in self._connections if c.connected)
        if connected_count == 0:
            # Try once more with retry logic
            await self._retry_start()

        connected_count = sum(1 for c in self._connections if c.connected)
        if connected_count == 0:
            raise ConnectionError(
                f"Failed to establish any connection to {self.host}:{self.port}"
            )

        log.info(
            "Connection pool started: %d/%d connections active",
            connected_count,
            self.pool_size,
        )

    async def _retry_start(self) -> None:
        """Retry connection establishment for failed connections."""
        max_retries: int = self.config.reconnect_attempts
        delay: float = self.config.reconnect_delay

        for attempt in range(1, max_retries + 1):
            log.info(
                "Retrying pool connections (attempt %d/%d)...",
                attempt,
                max_retries,
            )
            tasks: list[asyncio.Task[None]] = []
            async with self._lock:
                for i, conn in enumerate(self._connections):
                    if not conn.connected:
                        tasks.append(
                            asyncio.create_task(self._connect_safe(conn, i))
                        )
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            connected_count = sum(1 for c in self._connections if c.connected)
            if connected_count > 0:
                return

            if attempt < max_retries:
                await asyncio.sleep(delay * (2 ** (attempt - 1)))

    async def stop(self) -> None:
        """Close all connections in the pool."""
        if self._stopped:
            return

        self._stopped = True
        self._started = False

        async with self._lock:
            disconnect_tasks: list[asyncio.Task[None]] = []
            for conn in self._connections:
                disconnect_tasks.append(
                    asyncio.create_task(conn.disconnect())
                )
            if disconnect_tasks:
                await asyncio.gather(*disconnect_tasks, return_exceptions=True)
            self._connections.clear()

        log.info("Connection pool stopped")

    # ------------------------------------------------------------------
    # Connection acquisition
    # ------------------------------------------------------------------

    async def get_connection(self) -> TransportConnection:
        """Get a connection from the pool (round-robin).

        Returns:
            An active TransportConnection.

        Raises:
            TransportClosedError: If the pool is stopped.
            ConnectionError: If no active connections are available.
        """
        if self._stopped:
            raise TransportClosedError("Pool is stopped")

        async with self._lock:
            active: list[TransportConnection] = [
                c for c in self._connections if c.connected
            ]

            if not active:
                # Try to reconnect one connection
                for conn in self._connections:
                    if not conn.connected and not conn.closed:
                        await self._connect_safe(conn, self._connections.index(conn))
                        if conn.connected:
                            active.append(conn)
                            break

            if not active:
                raise ConnectionError("No active connections available")

            # Round-robin selection
            self._next_index = (self._next_index + 1) % len(active)
            return active[self._next_index]

    async def send_request(
        self,
        method: str,
        params: t.Optional[JSONObject] = None,
        *,
        request_id: t.Optional[str] = None,
        timeout: t.Optional[float] = None,
    ) -> JSONObject:
        """Send a request using any available connection.

        Args:
            method: The RPC method name.
            params: Method parameters.
            request_id: Optional request ID.
            timeout: Optional request timeout.

        Returns:
            The response JSON object.

        Raises:
            ConnectionError: If no connection is available.
        """
        conn: TransportConnection = await self.get_connection()
        return await conn.send_request(
            method,
            params,
            request_id=request_id,
            timeout=timeout,
        )

    @property
    def connected(self) -> bool:
        """Whether the pool has at least one active connection."""
        return any(c.connected for c in self._connections)

    @property
    def active_count(self) -> int:
        """Number of active (connected) connections in the pool."""
        return sum(1 for c in self._connections if c.connected)

    async def _connect_safe(
        self,
        conn: TransportConnection,
        index: int,
    ) -> None:
        """Connect a connection, logging errors without raising.

        Args:
            conn: The connection to connect.
            index: The connection index (for logging).
        """
        try:
            await conn.connect()
        except Exception as exc:
            log.warning(
                "Connection %d failed: %s",
                index,
                exc,
            )

    def get_pool_stats(self) -> t.List[t.Dict[str, t.Any]]:
        """Get statistics for all connections in the pool.

        Returns:
            A list of connection statistics dictionaries.
        """
        return [conn.get_stats() for conn in self._connections]

    def __repr__(self) -> str:
        """Return a string representation of the pool."""
        return (
            f"ConnectionPool({self.host}:{self.port}, "
            f"active={self.active_count}/{self.pool_size})"
        )


# ---------------------------------------------------------------------------
# Transport (high-level interface)
# ---------------------------------------------------------------------------


class Transport:
    """High-level transport interface used by the AinosClient.

    This class wraps the connection pool and provides the public API for
    sending requests and managing connectivity.

    Usage::

        config = ConnectionConfig(host="127.0.0.1", port=9500)
        transport = Transport(config)
        await transport.start()
        response = await transport.send_request("health", {})
        await transport.stop()
    """

    def __init__(
        self,
        config: ConnectionConfig,
        auth_manager: t.Optional[AuthManager] = None,
    ) -> None:
        """Initialise the transport.

        Args:
            config: Connection configuration.
            auth_manager: Optional authentication manager.
        """
        self.config: ConnectionConfig = config
        self._auth_manager: t.Optional[AuthManager] = auth_manager
        self._pool: t.Optional[ConnectionPool] = None
        self._started: bool = False
        self._stopped: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the transport and establish the connection pool.

        Raises:
            ConnectionError: If the pool cannot be established.
        """
        if self._stopped:
            raise TransportClosedError("Transport is stopped")

        if self._started:
            return

        self._pool = ConnectionPool(
            host=self.config.host,
            port=self.config.port,
            config=self.config,
            auth_manager=self._auth_manager,
        )

        await self._pool.start()
        self._started = True
        log.info("Transport started")

    async def stop(self) -> None:
        """Stop the transport and close all connections."""
        if self._stopped:
            return

        self._stopped = True
        self._started = False

        if self._pool is not None:
            await self._pool.stop()
            self._pool = None

        log.info("Transport stopped")

    # ------------------------------------------------------------------
    # Request sending
    # ------------------------------------------------------------------

    async def send_request(
        self,
        method: str,
        params: t.Optional[JSONObject] = None,
        *,
        request_id: t.Optional[str] = None,
        timeout: t.Optional[float] = None,
    ) -> JSONObject:
        """Send an RPC request and return the response.

        Args:
            method: The RPC method name.
            params: Method parameters.
            request_id: Optional request ID.
            timeout: Optional timeout in seconds.

        Returns:
            The response JSON object.

        Raises:
            TransportClosedError: If the transport is not started.
            ConnectionError: If the request cannot be sent.
        """
        if not self._started or self._pool is None:
            raise TransportClosedError("Transport is not started")

        if params is None:
            params = {}

        return await self._pool.send_request(
            method,
            params,
            request_id=request_id,
            timeout=timeout,
        )

    async def reconnect(self) -> None:
        """Re-establish all connections in the pool.

        This is called after a connection loss to restore connectivity.
        """
        if self._stopped:
            raise TransportClosedError("Transport is stopped")

        log.info("Reconnecting transport...")

        if self._pool is not None:
            await self._pool.stop()

        self._pool = ConnectionPool(
            host=self.config.host,
            port=self.config.port,
            config=self.config,
            auth_manager=self._auth_manager,
        )

        await self._pool.start()
        self._started = True
        log.info("Transport reconnected")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        """Whether the transport has at least one active connection."""
        if self._pool is None:
            return False
        return self._pool.connected

    @property
    def active_connections(self) -> int:
        """Number of active connections."""
        if self._pool is None:
            return 0
        return self._pool.active_count

    @property
    def is_started(self) -> bool:
        """Whether the transport has been started."""
        return self._started

    @property
    def is_stopped(self) -> bool:
        """Whether the transport has been stopped."""
        return self._stopped

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> t.Dict[str, t.Any]:
        """Get transport statistics.

        Returns:
            A dictionary of transport-level statistics.
        """
        pool_stats: t.List[t.Dict[str, t.Any]] = []
        if self._pool is not None:
            pool_stats = self._pool.get_pool_stats()

        return {
            "host": self.config.host,
            "port": self.config.port,
            "started": self._started,
            "stopped": self._stopped,
            "connected": self.connected,
            "active_connections": self.active_connections,
            "pool_size": self.config.pool_size,
            "connections": pool_stats,
        }

    def __repr__(self) -> str:
        """Return a string representation of the transport."""
        return (
            f"Transport({self.config.host}:{self.config.port}, "
            f"started={self._started}, connected={self.connected})"
        )


__all__: list[str] = [
    "Transport",
    "TransportConnection",
    "ConnectionPool",
]