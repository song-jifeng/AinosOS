"""
TCP server for the vector database using NDJSON protocol.

Implements a multi-threaded TCP server that accepts connections and
processes NDJSON-formatted requests. Compatible with the AinosOS IPC protocol.

The server listens on port 9600 and handles:
- Concurrent client connections
- NDJSON request/response protocol
- Heartbeat/keep-alive
- Graceful shutdown
"""

import socket
import threading
import json
import time
import os
import signal
from typing import Any, Dict, List, Optional, Set, Tuple
from queue import Queue, Empty

from .protocol import Protocol, Request, ErrorCode
from .handler import RequestHandler
from ..database import VectorDatabase
from ..utils.config import ServerConfig, global_config
from ..utils.metrics import MetricsCollector, ThroughputMeter


class ClientConnection:
    """Represents a single client connection."""

    def __init__(self, client_socket: socket.socket, address: Tuple[str, int],
                 handler: RequestHandler, config: ServerConfig):
        self.socket = client_socket
        self.address = address
        self.handler = handler
        self.config = config
        self.buffer = ""
        self.last_activity = time.time()
        self.closed = False
        self._lock = threading.Lock()

    def send(self, message: str):
        """Send a message to the client.

        Args:
            message: NDJSON message string
        """
        if self.closed:
            return
        try:
            with self._lock:
                self.socket.sendall(message.encode('utf-8'))
        except (socket.error, BrokenPipeError):
            self.close()

    def receive(self) -> Optional[Request]:
        """Receive and parse a request from the client.

        Returns:
            Parsed Request object, or None if no complete request available.
        """
        try:
            data = self.socket.recv(self.config.socket_buffer_size)
            if not data:
                self.close()
                return None

            self.last_activity = time.time()
            self.buffer += data.decode('utf-8')

            # Process complete lines
            while '\n' in self.buffer:
                line, self.buffer = self.buffer.split('\n', 1)
                line = line.strip()
                if line:
                    msg = Protocol.parse(line)
                    if isinstance(msg, Request):
                        return msg

            return None

        except (socket.timeout, BlockingIOError):
            return None
        except (socket.error, ConnectionResetError, ConnectionAbortedError):
            self.close()
            return None

    def process_request(self, request: Request) -> str:
        """Process a request and return the response.

        Args:
            request: Request to process

        Returns:
            NDJSON response string.
        """
        return self.handler.handle_request(request)

    def close(self):
        """Close the connection."""
        if not self.closed:
            self.closed = True
            try:
                self.socket.close()
            except Exception:
                pass

    def is_alive(self) -> bool:
        """Check if the connection is still alive.

        Returns:
            True if the connection is alive.
        """
        if self.closed:
            return False
        # Check timeout
        if time.time() - self.last_activity > self.config.recv_timeout:
            return False
        return True


class VectorDatabaseServer:
    """Multi-threaded TCP server for the vector database.

    Listens for client connections on a configurable port and processes
    NDJSON requests using a thread pool.
    """

    def __init__(self, database: Optional[VectorDatabase] = None,
                 config: Optional[ServerConfig] = None):
        self.db = database or VectorDatabase()
        self.config = config or ServerConfig()
        self.handler = RequestHandler(self.db)

        # Server state
        self._server_socket: Optional[socket.socket] = None
        self._running = False
        self._clients: Dict[int, ClientConnection] = {}
        self._client_id_counter = 0
        self._client_lock = threading.Lock()

        # Threading
        self._accept_thread: Optional[threading.Thread] = None
        self._worker_threads: List[threading.Thread] = []
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._request_queue: Queue = Queue()
        self._stop_event = threading.Event()

        # Metrics
        self.metrics = MetricsCollector(enabled=True)
        self.throughput = ThroughputMeter()

        # Connection tracking
        self._total_connections = 0
        self._active_connections = 0

    def start(self, host: Optional[str] = None, port: Optional[int] = None):
        """Start the TCP server.

        Args:
            host: Host to bind to (default: from config)
            port: Port to bind to (default: 9600)
        """
        if self._running:
            print("Server is already running")
            return

        host = host or self.config.host
        port = port or self.config.port

        # Create server socket
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.settimeout(1.0)  # 1 second timeout for accept

        try:
            self._server_socket.bind((host, port))
            self._server_socket.listen(128)
            self._running = True
            print(f"Vector Database Server started on {host}:{port}")
        except socket.error as e:
            print(f"Failed to start server: {e}")
            self._server_socket = None
            return

        # Start threads
        self._stop_event.clear()

        # Accept thread
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="accept-thread", daemon=True
        )
        self._accept_thread.start()

        # Worker threads
        for i in range(self.config.max_workers):
            worker = threading.Thread(
                target=self._worker_loop, name=f"worker-{i}", daemon=True
            )
            worker.start()
            self._worker_threads.append(worker)

        # Heartbeat thread
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name="heartbeat-thread", daemon=True
        )
        self._heartbeat_thread.start()

    def stop(self):
        """Stop the server gracefully."""
        if not self._running:
            return

        print("Stopping server...")
        self._running = False
        self._stop_event.set()

        # Close all client connections
        with self._client_lock:
            for client_id, client in list(self._clients.items()):
                client.close()
            self._clients.clear()

        # Close server socket
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None

        # Wait for threads
        if self._accept_thread and self._accept_thread.is_alive():
            self._accept_thread.join(timeout=5)

        for worker in self._worker_threads:
            if worker.is_alive():
                worker.join(timeout=5)

        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=5)

        self._worker_threads.clear()
        print("Server stopped.")

    def _accept_loop(self):
        """Main loop for accepting new connections."""
        while self._running and not self._stop_event.is_set():
            try:
                client_sock, address = self._server_socket.accept()
                client_sock.settimeout(self.config.recv_timeout)
                client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

                # Create client connection
                client = ClientConnection(client_sock, address, self.handler, self.config)

                with self._client_lock:
                    client_id = self._client_id_counter
                    self._client_id_counter += 1
                    self._clients[client_id] = client

                self._total_connections += 1
                self._active_connections = len(self._clients)

                print(f"New client connection from {address[0]}:{address[1]} "
                      f"(client_id={client_id})")

            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    print("Socket error in accept loop")
                break
            except Exception as e:
                print(f"Error in accept loop: {e}")
                break

    def _worker_loop(self):
        """Worker thread loop for processing requests."""
        while self._running and not self._stop_event.is_set():
            # Check for timed-out clients
            self._cleanup_stale_clients()

            # Process client requests
            with self._client_lock:
                client_ids = list(self._clients.keys())

            for client_id in client_ids:
                if self._stop_event.is_set():
                    break

                client = self._get_client(client_id)
                if client is None:
                    continue

                try:
                    # Try to receive a request
                    request = client.receive()
                    if request is None:
                        continue

                    # Process the request
                    start_time = time.time()
                    response = client.process_request(request)
                    elapsed = time.time() - start_time

                    # Send response
                    client.send(response)

                    # Update metrics
                    self.metrics.record_operation(
                        request.method, elapsed, True
                    )
                    self.throughput.record()

                except Exception as e:
                    # Error handling
                    if client and not client.closed:
                        error_resp = Protocol.create_error_response(
                            'unknown', ErrorCode.INTERNAL_ERROR, str(e)
                        )
                        try:
                            client.send(error_resp)
                        except Exception:
                            self._remove_client(client_id)

            # Brief sleep to prevent busy-waiting
            if not self._stop_event.is_set():
                self._stop_event.wait(0.01)

    def _heartbeat_loop(self):
        """Heartbeat thread for keep-alive."""
        while self._running and not self._stop_event.is_set():
            self._stop_event.wait(30)  # Send heartbeat every 30 seconds
            if self._stop_event.is_set():
                break

            with self._client_lock:
                for client_id, client in list(self._clients.items()):
                    if client.is_alive() and not client.closed:
                        try:
                            client.send(Protocol.create_heartbeat())
                        except Exception:
                            self._remove_client(client_id)

    def _cleanup_stale_clients(self):
        """Remove stale client connections."""
        with self._client_lock:
            stale_ids = []
            for client_id, client in self._clients.items():
                if not client.is_alive():
                    stale_ids.append(client_id)

            for client_id in stale_ids:
                client = self._clients.pop(client_id, None)
                if client:
                    client.close()
                    print(f"Removed stale client {client_id}")

            self._active_connections = len(self._clients)

    def _get_client(self, client_id: int) -> Optional[ClientConnection]:
        """Get a client connection by ID.

        Args:
            client_id: Client ID

        Returns:
            ClientConnection or None.
        """
        with self._client_lock:
            return self._clients.get(client_id)

    def _remove_client(self, client_id: int):
        """Remove a client connection.

        Args:
            client_id: Client ID to remove
        """
        with self._client_lock:
            client = self._clients.pop(client_id, None)
            if client:
                client.close()
                self._active_connections = len(self._clients)

    def get_status(self) -> Dict[str, Any]:
        """Get server status information.

        Returns:
            Status dictionary.
        """
        return {
            "running": self._running,
            "host": self.config.host,
            "port": self.config.port,
            "total_connections": self._total_connections,
            "active_connections": self._active_connections,
            "max_workers": self.config.max_workers,
            "collections": self.db.list_collections(),
            "uptime_seconds": time.time() - getattr(self, '_start_time', time.time()),
        }

    def __enter__(self):
        self._start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False


def start_server(host: str = "0.0.0.0", port: int = 9600,
                 database: Optional[VectorDatabase] = None,
                 config: Optional[ServerConfig] = None) -> VectorDatabaseServer:
    """Convenience function to start the vector database server.

    Args:
        host: Host to bind to
        port: Port to bind to
        database: Optional pre-configured database instance
        config: Optional server configuration

    Returns:
        Running server instance.
    """
    if config is None:
        config = ServerConfig(host=host, port=port)

    server = VectorDatabaseServer(database=database, config=config)
    server.start()
    return server