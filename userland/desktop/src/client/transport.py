#!/usr/bin/env python3
"""Ainos Desktop - TCP Transport Layer.

This module provides a reliable TCP transport layer for communicating
with the Ainos backend service using asyncio and socket-based I/O.
"""

import asyncio
import json
import logging
import socket
import struct
import ssl
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


class TransportError(Exception):
    """Base exception for transport errors."""

    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause


class ConnectionError(TransportError):
    """Raised when connection to the backend fails."""

    def __init__(self, host: str, port: int, reason: str = "", cause: Exception | None = None):
        message = f"Failed to connect to {host}:{port}"
        if reason:
            message += f" - {reason}"
        super().__init__(message, cause)
        self.host = host
        self.port = port


class TimeoutError(TransportError):
    """Raised when a transport operation times out."""

    def __init__(self, operation: str, timeout_ms: int):
        super().__init__(f"Operation '{operation}' timed out after {timeout_ms}ms")
        self.operation = operation
        self.timeout_ms = timeout_ms


class ProtocolError(TransportError):
    """Raised on protocol-level errors."""

    def __init__(self, message: str, raw_data: bytes | None = None):
        super().__init__(message)
        self.raw_data = raw_data


class MessageType:
    """Protocol message type constants."""

    REQUEST = 0x01
    RESPONSE = 0x02
    STREAM_CHUNK = 0x03
    STREAM_END = 0x04
    ERROR = 0x05
    HEARTBEAT = 0x06
    HEARTBEAT_ACK = 0x07
    EVENT = 0x08

    # Header size: 4 bytes length + 1 byte type + 1 byte flags + 2 bytes reserved
    HEADER_SIZE = 8

    # Flags
    FLAG_COMPRESSED = 0x01
    FLAG_ENCRYPTED = 0x02
    FLAG_MORE = 0x04


class TCPTransport:
    """TCP transport for communicating with the Ainos backend.

    Uses a simple length-prefixed message protocol with support for
    streaming responses, heartbeats, and reconnection.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        use_ssl: bool = False,
        timeout_ms: int = 30000,
        reconnect_interval_ms: int = 5000,
        max_reconnect_attempts: int = 10,
        heartbeat_interval_ms: int = 15000,
    ):
        """Initialize the TCP transport.

        Args:
            host: Backend hostname or IP address.
            port: Backend port number.
            use_ssl: Whether to use SSL/TLS encryption.
            timeout_ms: Operation timeout in milliseconds.
            reconnect_interval_ms: Interval between reconnection attempts.
            max_reconnect_attempts: Maximum number of reconnection attempts.
            heartbeat_interval_ms: Interval between heartbeat messages.
        """
        self._host = host
        self._port = port
        self._use_ssl = use_ssl
        self._timeout_ms = timeout_ms
        self._reconnect_interval_ms = reconnect_interval_ms
        self._max_reconnect_attempts = max_reconnect_attempts
        self._heartbeat_interval_ms = heartbeat_interval_ms

        # Connection state
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._reconnecting = False
        self._reconnect_attempts = 0
        self._last_heartbeat = 0.0
        self._connection_lock = asyncio.Lock()

        # Callbacks
        self._on_connected: Callable | None = None
        self._on_disconnected: Callable | None = None
        self._on_message: Callable | None = None
        self._on_error: Callable | None = None

        # Heartbeat task
        self._heartbeat_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None

        # Pending requests
        self._pending_requests: dict[str, asyncio.Future] = {}

        # Stream handlers
        self._stream_handlers: dict[str, Callable] = {}

        logger.info(
            "TCPTransport initialized: %s:%d (SSL: %s, timeout: %dms)",
            host, port, use_ssl, timeout_ms
        )

    @property
    def is_connected(self) -> bool:
        """Check if the transport is currently connected.

        Returns:
            True if connected to the backend.
        """
        return self._connected and self._writer is not None and not self._writer.is_closing()

    @property
    def host(self) -> str:
        """Get the configured host."""
        return self._host

    @property
    def port(self) -> int:
        """Get the configured port."""
        return self._port

    def set_callbacks(
        self,
        on_connected: Callable | None = None,
        on_disconnected: Callable | None = None,
        on_message: Callable | None = None,
        on_error: Callable | None = None,
    ) -> None:
        """Set event callbacks.

        Args:
            on_connected: Called when connected to backend.
            on_disconnected: Called when disconnected from backend.
            on_message: Called when a message is received.
            on_error: Called on transport errors.
        """
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._on_message = on_message
        self._on_error = on_error

    async def connect(self) -> bool:
        """Establish connection to the backend.

        Returns:
            True if connection was successful.

        Raises:
            ConnectionError: If connection fails.
        """
        async with self._connection_lock:
            if self._connected:
                logger.debug("Already connected to %s:%d", self._host, self._port)
                return True

            try:
                logger.info("Connecting to %s:%d...", self._host, self._port)

                # Create SSL context if needed
                ssl_context = None
                if self._use_ssl:
                    ssl_context = ssl.create_default_context()
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE

                # Connect with timeout
                timeout = self._timeout_ms / 1000.0
                connect_coro = asyncio.open_connection(
                    self._host, self._port, ssl=ssl_context
                )
                try:
                    self._reader, self._writer = await asyncio.wait_for(
                        connect_coro, timeout=timeout
                    )
                except asyncio.TimeoutError:
                    raise TimeoutError("connect", self._timeout_ms)
                except OSError as e:
                    raise ConnectionError(self._host, self._port, str(e), e)

                self._connected = True
                self._reconnect_attempts = 0
                self._last_heartbeat = time.time()

                # Start heartbeat
                self._start_heartbeat()

                # Start message reader
                asyncio.create_task(self._read_loop())

                logger.info("Connected to %s:%d", self._host, self._port)

                # Notify callback
                if self._on_connected:
                    try:
                        self._on_connected()
                    except Exception as e:
                        logger.error("Error in on_connected callback: %s", e)

                return True

            except (ConnectionError, TimeoutError, OSError) as e:
                self._connected = False
                logger.error("Connection failed: %s", e)
                if self._on_error:
                    try:
                        self._on_error(str(e))
                    except Exception as cb_err:
                        logger.error("Error in on_error callback: %s", cb_err)
                raise

    async def disconnect(self) -> None:
        """Disconnect from the backend."""
        async with self._connection_lock:
            if not self._connected:
                return

            logger.info("Disconnecting from %s:%d", self._host, self._port)

            # Stop heartbeat
            self._stop_heartbeat()

            # Cancel pending requests
            for req_id, future in self._pending_requests.items():
                if not future.done():
                    future.set_exception(TransportError("Connection closed"))
            self._pending_requests.clear()

            # Close socket
            if self._writer:
                try:
                    self._writer.close()
                    await self._writer.wait_closed()
                except Exception as e:
                    logger.debug("Error closing writer: %s", e)
                self._writer = None

            self._reader = None
            self._connected = False

            logger.info("Disconnected")

            # Notify callback
            if self._on_disconnected:
                try:
                    self._on_disconnected()
                except Exception as e:
                    logger.error("Error in on_disconnected callback: %s", e)

    async def send_request(
        self,
        request_id: str,
        method: str,
        params: dict[str, Any] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Send a request and wait for the response.

        Args:
            request_id: Unique request identifier.
            method: RPC method name.
            params: Request parameters.
            stream: Whether to expect a streaming response.

        Returns:
            Response data as dictionary.

        Raises:
            TransportError: If the request fails.
        """
        if not self._connected or not self._writer:
            raise TransportError("Not connected")

        # Build message
        message = {
            "type": "request",
            "id": request_id,
            "method": method,
            "params": params or {},
            "stream": stream,
        }

        # Create future for response
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        try:
            # Send message
            await self._send_message(message)

            # Wait for response with timeout
            timeout = self._timeout_ms / 1000.0
            try:
                response = await asyncio.wait_for(future, timeout=timeout)
                return response
            except asyncio.TimeoutError:
                raise TimeoutError(f"request {method}", self._timeout_ms)

        except (TransportError, TimeoutError):
            self._pending_requests.pop(request_id, None)
            raise
        except Exception as e:
            self._pending_requests.pop(request_id, None)
            raise TransportError(f"Request failed: {e}", e) from e

    async def send_stream_request(
        self,
        request_id: str,
        method: str,
        params: dict[str, Any] | None = None,
        on_chunk: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Send a request with streaming response.

        Args:
            request_id: Unique request identifier.
            method: RPC method name.
            params: Request parameters.
            on_chunk: Callback for each streaming chunk.

        Returns:
            Final response data.
        """
        if on_chunk:
            self._stream_handlers[request_id] = on_chunk

        try:
            return await self.send_request(request_id, method, params, stream=True)
        finally:
            self._stream_handlers.pop(request_id, None)

    async def send_event(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Send an event message to the backend.

        Args:
            event_type: Event type identifier.
            data: Event data.

        Raises:
            TransportError: If sending fails.
        """
        if not self._connected or not self._writer:
            raise TransportError("Not connected")

        message = {
            "type": "event",
            "event_type": event_type,
            "data": data or {},
        }

        await self._send_message(message)
        logger.debug("Event sent: %s", event_type)

    async def _send_message(self, message: dict[str, Any]) -> None:
        """Send a JSON message over the transport.

        Args:
            message: Message dictionary to send.

        Raises:
            TransportError: If writing to the socket fails.
        """
        if not self._writer:
            raise TransportError("Cannot send message: no writer")

        try:
            # Serialize to JSON
            data = json.dumps(message).encode("utf-8")

            # Create header: 4 bytes payload length + 1 byte type + 1 byte flags + 2 bytes reserved
            header = struct.pack("!IBBH", len(data), MessageType.REQUEST, 0, 0)

            # Write header + payload
            self._writer.write(header + data)
            await self._writer.drain()

            logger.debug("Sent message: %s (type=%d, size=%d)",
                         message.get("type", "unknown"),
                         MessageType.REQUEST, len(data))

        except (ConnectionError, OSError) as e:
            self._connected = False
            raise TransportError(f"Failed to send message: {e}", e) from e

    async def _read_loop(self) -> None:
        """Main message reading loop."""
        try:
            while self._connected and self._reader:
                # Read header
                header_bytes = await self._read_exactly(MessageType.HEADER_SIZE)
                if header_bytes is None:
                    break

                # Parse header
                payload_length, msg_type, flags, _ = struct.unpack("!IBBH", header_bytes)

                # Read payload
                payload_bytes = await self._read_exactly(payload_length)
                if payload_bytes is None:
                    break

                # Parse message
                try:
                    message = json.loads(payload_bytes.decode("utf-8"))
                except json.JSONDecodeError as e:
                    logger.error("Invalid JSON received: %s", e)
                    continue

                # Handle based on message type (from header)
                await self._handle_message(msg_type, message)

        except asyncio.CancelledError:
            logger.debug("Read loop cancelled")
        except Exception as e:
            logger.error("Read loop error: %s", e)
        finally:
            if self._connected:
                logger.warning("Read loop ended, connection lost")
                self._connected = False
                self._notify_disconnected()
                self._schedule_reconnect()

    async def _read_exactly(self, n: int) -> bytes | None:
        """Read exactly n bytes from the stream.

        Args:
            n: Number of bytes to read.

        Returns:
            Bytes read, or None if connection closed.
        """
        if not self._reader:
            return None
        try:
            data = await self._reader.readexactly(n)
            return data
        except asyncio.IncompleteReadError:
            return None
        except (ConnectionError, OSError) as e:
            logger.error("Read error: %s", e)
            return None

    async def _handle_message(self, msg_type: int, message: dict[str, Any]) -> None:
        """Handle an incoming message.

        Args:
            msg_type: Message type from the header.
            message: Parsed message dictionary.
        """
        msg_type_str = message.get("type", "")

        if msg_type_str == "response":
            await self._handle_response(message)
        elif msg_type_str == "stream_chunk":
            await self._handle_stream_chunk(message)
        elif msg_type_str == "stream_end":
            await self._handle_stream_end(message)
        elif msg_type_str == "error":
            await self._handle_error_message(message)
        elif msg_type_str == "heartbeat":
            await self._handle_heartbeat()
        elif msg_type_str == "heartbeat_ack":
            self._last_heartbeat = time.time()
        elif msg_type_str == "event":
            await self._handle_event(message)
        else:
            # Unknown message type, pass to general handler
            logger.debug("Unknown message type: %s", msg_type_str)
            if self._on_message:
                try:
                    self._on_message(message)
                except Exception as e:
                    logger.error("Error in on_message callback: %s", e)

    async def _handle_response(self, message: dict[str, Any]) -> None:
        """Handle a response message.

        Args:
            message: Response message dictionary.
        """
        request_id = message.get("id", "")
        if request_id in self._pending_requests:
            future = self._pending_requests.pop(request_id)
            if not future.done():
                future.set_result(message.get("data", {}))
        else:
            logger.debug("Received response for unknown request: %s", request_id)

    async def _handle_stream_chunk(self, message: dict[str, Any]) -> None:
        """Handle a streaming chunk message.

        Args:
            message: Stream chunk message dictionary.
        """
        request_id = message.get("id", "")
        handler = self._stream_handlers.get(request_id)
        if handler:
            try:
                handler(message.get("data", {}))
            except Exception as e:
                logger.error("Stream handler error: %s", e)
        else:
            # Try pending requests
            if request_id in self._pending_requests:
                future = self._pending_requests[request_id]
                if not future.done():
                    # Store partial response
                    if not hasattr(future, "_partial_data"):
                        future._partial_data = []  # type: ignore
                    future._partial_data.append(message.get("data", {}))  # type: ignore

    async def _handle_stream_end(self, message: dict[str, Any]) -> None:
        """Handle a stream end message.

        Args:
            message: Stream end message dictionary.
        """
        request_id = message.get("id", "")
        if request_id in self._pending_requests:
            future = self._pending_requests.pop(request_id)
            if not future.done():
                # Combine partial data
                partial = getattr(future, "_partial_data", [])
                result = {"chunks": partial, "final": message.get("data", {})}
                future.set_result(result)

    async def _handle_error_message(self, message: dict[str, Any]) -> None:
        """Handle an error message.

        Args:
            message: Error message dictionary.
        """
        request_id = message.get("id", "")
        error_msg = message.get("error", "Unknown error")
        if request_id in self._pending_requests:
            future = self._pending_requests.pop(request_id)
            if not future.done():
                future.set_exception(TransportError(error_msg))
        else:
            logger.error("Unhandled error: %s", error_msg)
            if self._on_error:
                try:
                    self._on_error(error_msg)
                except Exception as e:
                    logger.error("Error in on_error callback: %s", e)

    async def _handle_heartbeat(self) -> None:
        """Handle a heartbeat message."""
        self._last_heartbeat = time.time()
        # Send acknowledgment
        if self._writer and not self._writer.is_closing():
            try:
                ack_message = {"type": "heartbeat_ack"}
                data = json.dumps(ack_message).encode("utf-8")
                header = struct.pack("!IBBH", len(data), MessageType.HEARTBEAT_ACK, 0, 0)
                self._writer.write(header + data)
                await self._writer.drain()
            except Exception as e:
                logger.debug("Failed to send heartbeat ACK: %s", e)

    async def _handle_event(self, message: dict[str, Any]) -> None:
        """Handle an event message from the backend.

        Args:
            message: Event message dictionary.
        """
        event_type = message.get("event_type", "unknown")
        event_data = message.get("data", {})
        logger.debug("Event received: %s", event_type)

        if self._on_message:
            try:
                self._on_message(message)
            except Exception as e:
                logger.error("Error in on_message for event: %s", e)

    def _start_heartbeat(self) -> None:
        """Start the heartbeat task."""
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    def _stop_heartbeat(self) -> None:
        """Stop the heartbeat task."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

    async def _heartbeat_loop(self) -> None:
        """Periodic heartbeat sending loop."""
        interval = self._heartbeat_interval_ms / 1000.0
        try:
            while self._connected:
                await asyncio.sleep(interval)
                if self._connected and self._writer and not self._writer.is_closing():
                    try:
                        heartbeat = {"type": "heartbeat"}
                        data = json.dumps(heartbeat).encode("utf-8")
                        header = struct.pack("!IBBH", len(data), MessageType.HEARTBEAT, 0, 0)
                        self._writer.write(header + data)
                        await self._writer.drain()
                    except Exception as e:
                        logger.debug("Heartbeat send failed: %s", e)
                        break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Heartbeat loop error: %s", e)

    def _notify_disconnected(self) -> None:
        """Notify listeners about disconnection."""
        if self._on_disconnected:
            try:
                self._on_disconnected()
            except Exception as e:
                logger.error("Error in on_disconnected callback: %s", e)

    def _schedule_reconnect(self) -> None:
        """Schedule a reconnection attempt."""
        if self._reconnecting or self._reconnect_attempts >= self._max_reconnect_attempts:
            logger.warning("Max reconnection attempts reached (%d)", self._max_reconnect_attempts)
            return

        self._reconnecting = True
        self._reconnect_attempts += 1
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Reconnection loop with backoff."""
        backoff = self._reconnect_interval_ms / 1000.0
        attempt = 0

        while attempt < self._max_reconnect_attempts and not self._connected:
            attempt += 1
            logger.info("Reconnection attempt %d/%d in %.1fs...",
                        attempt, self._max_reconnect_attempts, backoff)

            await asyncio.sleep(backoff)

            try:
                await self.connect()
                if self._connected:
                    logger.info("Reconnected successfully after %d attempts", attempt)
                    self._reconnecting = False
                    return
            except (ConnectionError, TimeoutError, OSError) as e:
                logger.warning("Reconnection attempt %d failed: %s", attempt, e)
                # Exponential backoff, capped at 30 seconds
                backoff = min(backoff * 1.5, 30.0)

        self._reconnecting = False
        logger.error("All reconnection attempts failed")

    async def __aenter__(self) -> "TCPTransport":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, *args) -> None:
        """Async context manager exit."""
        await self.disconnect()