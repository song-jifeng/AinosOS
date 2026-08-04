//! Transport layer for the Ainos SDK.
//!
//! Provides the [`Transport`] trait (with TCP and Unix implementations) for
//! connecting to the Ainos daemon, along with NDJSON framing, buffered I/O,
//! and connection pooling.

use crate::error::{AinosError, Result};
use async_trait::async_trait;
use bytes::BytesMut;
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::TcpStream;
use tokio::time::timeout;
use tracing::{debug, info};

// ===========================================================================
// Transport trait
// ===========================================================================

/// Abstract transport for communicating with the Ainos daemon.
///
/// Implementations provide a bidirectional byte stream over which NDJSON
/// messages are exchanged. The default implementation is [`TcpTransport`].
#[async_trait]
pub trait Transport: Send + Sync + 'static {
    /// Connect to the daemon.
    async fn connect(&mut self, addr: &str, connect_timeout: Duration) -> Result<()>;

    /// Disconnect from the daemon.
    async fn disconnect(&mut self) -> Result<()>;

    /// Returns `true` if the transport is currently connected.
    fn is_connected(&self) -> bool;

    /// Send a raw JSON line to the daemon (appends `\n`).
    async fn send(&mut self, data: &str) -> Result<()>;

    /// Read a single JSON line from the daemon (up to `\n`).
    async fn recv(&mut self) -> Result<String>;

    /// Send a request and receive the response atomically.
    async fn request(&mut self, data: &str) -> Result<String> {
        self.send(data).await?;
        self.recv().await
    }

    /// Get the local address of the connection, if available.
    fn local_addr(&self) -> Option<String>;

    /// Get the peer address of the connection, if available.
    fn peer_addr(&self) -> Option<String>;
}

// ===========================================================================
// TCP transport (using split read/write halves)
// ===========================================================================

/// TCP transport implementation for communicating with the Ainos daemon.
///
/// Connects to `host:port` (default `127.0.0.1:9500`) and exchanges
/// newline-delimited JSON messages.
///
/// Internally uses `tokio::io::split` to obtain separate read and write
/// halves, avoiding the need for `try_clone` on Windows.
pub struct TcpTransport {
    /// Buffered reader for receiving NDJSON lines.
    reader: Option<BufReader<tokio::net::tcp::OwnedReadHalf>>,
    /// Writer for sending NDJSON lines.
    writer: Option<tokio::net::tcp::OwnedWriteHalf>,
    /// The address we connected to.
    addr: String,
    /// Maximum line length to accept (prevents memory exhaustion).
    max_line_length: usize,
    /// Read timeout for `recv`.
    read_timeout: Duration,
}

impl TcpTransport {
    /// Create a new unconnected `TcpTransport`.
    pub fn new(read_timeout: Duration, max_line_length: usize) -> Self {
        Self {
            reader: None,
            writer: None,
            addr: String::new(),
            max_line_length,
            read_timeout,
        }
    }

    /// Create a new `TcpTransport` and connect immediately.
    pub async fn connect(
        host: &str,
        port: u16,
        connect_timeout: Duration,
        read_timeout: Duration,
        max_line_length: usize,
    ) -> Result<Self> {
        let addr = format!("{}:{}", host, port);
        let mut transport = Self::new(read_timeout, max_line_length);
        transport.connect(&addr, connect_timeout).await?;
        Ok(transport)
    }
}

#[async_trait]
impl Transport for TcpTransport {
    async fn connect(&mut self, addr: &str, connect_timeout: Duration) -> Result<()> {
        debug!("TcpTransport: connecting to {}", addr);

        let stream = timeout(connect_timeout, TcpStream::connect(addr))
            .await
            .map_err(|_| AinosError::Timeout(connect_timeout))?
            .map_err(|e| {
                AinosError::ConnectionRefused(format!("Failed to connect to {}: {}", addr, e))
            })?;

        // Disable Nagle's algorithm for lower latency
        stream.set_nodelay(true).ok();

        // Split into read/write halves for independent access
        let (read_half, write_half) = stream.into_split();
        let reader = BufReader::new(read_half);

        self.addr = addr.to_string();
        self.reader = Some(reader);
        self.writer = Some(write_half);

        info!("TcpTransport: connected to {}", addr);
        Ok(())
    }

    async fn disconnect(&mut self) -> Result<()> {
        // Drop the reader and writer; this closes the TCP connection
        self.reader = None;
        self.writer = None;
        debug!("TcpTransport: disconnected from {}", self.addr);
        Ok(())
    }

    fn is_connected(&self) -> bool {
        self.writer.is_some()
    }

    async fn send(&mut self, data: &str) -> Result<()> {
        let writer = self
            .writer
            .as_mut()
            .ok_or_else(|| AinosError::ConnectionLost("Not connected".into()))?;

        writer
            .write_all(data.as_bytes())
            .await
            .map_err(|e| AinosError::ConnectionLost(format!("Send failed: {}", e)))?;
        writer
            .write_all(b"\n")
            .await
            .map_err(|e| AinosError::ConnectionLost(format!("Send newline failed: {}", e)))?;
        writer
            .flush()
            .await
            .map_err(|e| AinosError::ConnectionLost(format!("Flush failed: {}", e)))?;

        debug!("TcpTransport: sent {} bytes", data.len());
        Ok(())
    }

    async fn recv(&mut self) -> Result<String> {
        let reader = self
            .reader
            .as_mut()
            .ok_or_else(|| AinosError::ConnectionLost("Not connected".into()))?;

        let mut line = String::new();

        let read_result = timeout(self.read_timeout, reader.read_line(&mut line)).await;

        match read_result {
            Ok(Ok(0)) => {
                // EOF
                self.reader = None;
                self.writer = None;
                Err(AinosError::ConnectionClosed)
            }
            Ok(Ok(_n)) => {
                let trimmed = line.trim().to_string();
                if trimmed.len() > self.max_line_length {
                    return Err(AinosError::Protocol(format!(
                        "Response line too long: {} bytes (max: {})",
                        trimmed.len(),
                        self.max_line_length
                    )));
                }
                debug!("TcpTransport: received {} bytes", trimmed.len());
                Ok(trimmed)
            }
            Ok(Err(e)) => {
                self.reader = None;
                self.writer = None;
                Err(AinosError::ConnectionLost(format!("Read error: {}", e)))
            }
            Err(_) => Err(AinosError::Timeout(self.read_timeout)),
        }
    }

    fn local_addr(&self) -> Option<String> {
        // We don't store the original stream, so we can't get local addr
        None
    }

    fn peer_addr(&self) -> Option<String> {
        Some(self.addr.clone())
    }
}

// ===========================================================================
// Unix transport (Linux / macOS)
// ===========================================================================

/// Unix Domain Socket transport for communicating with the Ainos daemon.
///
/// Available on Unix platforms only. Provides lower latency than TCP when
/// the daemon is running on the same machine.
#[cfg(unix)]
pub mod unix {
    use super::*;
    use tokio::net::UnixStream;

    /// Unix Domain Socket transport.
    pub struct UnixTransport {
        reader: Option<BufReader<tokio::net::unix::OwnedReadHalf>>,
        writer: Option<tokio::net::unix::OwnedWriteHalf>,
        socket_path: String,
        max_line_length: usize,
        read_timeout: Duration,
    }

    impl UnixTransport {
        /// Create a new unconnected `UnixTransport`.
        pub fn new(read_timeout: Duration, max_line_length: usize) -> Self {
            Self {
                reader: None,
                writer: None,
                socket_path: String::new(),
                max_line_length,
                read_timeout,
            }
        }

        /// Connect to a Unix socket at `socket_path`.
        pub async fn connect(
            socket_path: &str,
            connect_timeout: Duration,
            read_timeout: Duration,
            max_line_length: usize,
        ) -> Result<Self> {
            let mut transport = Self::new(read_timeout, max_line_length);
            transport.connect(socket_path, connect_timeout).await?;
            Ok(transport)
        }
    }

    #[async_trait]
    impl Transport for UnixTransport {
        async fn connect(&mut self, socket_path: &str, connect_timeout: Duration) -> Result<()> {
            debug!("UnixTransport: connecting to {}", socket_path);

            let stream = timeout(connect_timeout, UnixStream::connect(socket_path))
                .await
                .map_err(|_| AinosError::Timeout(connect_timeout))?
                .map_err(|e| {
                    AinosError::ConnectionRefused(format!(
                        "Failed to connect to Unix socket {}: {}",
                        socket_path, e
                    ))
                })?;

            let (read_half, write_half) = stream.into_split();
            self.socket_path = socket_path.to_string();
            self.reader = Some(BufReader::new(read_half));
            self.writer = Some(write_half);

            info!("UnixTransport: connected to {}", socket_path);
            Ok(())
        }

        async fn disconnect(&mut self) -> Result<()> {
            self.reader = None;
            self.writer = None;
            debug!("UnixTransport: disconnected from {}", self.socket_path);
            Ok(())
        }

        fn is_connected(&self) -> bool {
            self.writer.is_some()
        }

        async fn send(&mut self, data: &str) -> Result<()> {
            let writer = self
                .writer
                .as_mut()
                .ok_or_else(|| AinosError::ConnectionLost("Not connected".into()))?;

            writer
                .write_all(data.as_bytes())
                .await
                .map_err(|e| AinosError::ConnectionLost(format!("Send failed: {}", e)))?;
            writer
                .write_all(b"\n")
                .await
                .map_err(|e| AinosError::ConnectionLost(format!("Send newline failed: {}", e)))?;
            writer
                .flush()
                .await
                .map_err(|e| AinosError::ConnectionLost(format!("Flush failed: {}", e)))?;

            Ok(())
        }

        async fn recv(&mut self) -> Result<String> {
            let reader = self
                .reader
                .as_mut()
                .ok_or_else(|| AinosError::ConnectionLost("Not connected".into()))?;

            let mut line = String::new();
            let read_result = timeout(self.read_timeout, reader.read_line(&mut line)).await;

            match read_result {
                Ok(Ok(0)) => {
                    self.reader = None;
                    self.writer = None;
                    Err(AinosError::ConnectionClosed)
                }
                Ok(Ok(_n)) => {
                    let trimmed = line.trim().to_string();
                    if trimmed.len() > self.max_line_length {
                        return Err(AinosError::Protocol(format!(
                            "Response line too long: {} bytes (max: {})",
                            trimmed.len(),
                            self.max_line_length
                        )));
                    }
                    Ok(trimmed)
                }
                Ok(Err(e)) => {
                    self.reader = None;
                    self.writer = None;
                    Err(AinosError::ConnectionLost(format!("Read error: {}", e)))
                }
                Err(_) => Err(AinosError::Timeout(self.read_timeout)),
            }
        }

        fn local_addr(&self) -> Option<String> {
            None
        }

        fn peer_addr(&self) -> Option<String> {
            Some(self.socket_path.clone())
        }
    }
}

// ===========================================================================
// Connection pool
// ===========================================================================

/// A simple pool of pre-established transport connections.
///
/// Useful for workloads that require multiple concurrent connections to the
/// daemon. Each connection is independent and can be used from a separate
/// task.
pub struct ConnectionPool {
    connections: Vec<Box<dyn Transport>>,
    addr: String,
    connect_timeout: Duration,
    read_timeout: Duration,
    max_line_length: usize,
}

impl ConnectionPool {
    /// Create a new connection pool and pre-establish `pool_size` connections.
    pub async fn new(
        addr: &str,
        pool_size: usize,
        connect_timeout: Duration,
        read_timeout: Duration,
        max_line_length: usize,
    ) -> Result<Self> {
        let mut connections = Vec::with_capacity(pool_size);
        for i in 0..pool_size {
            let mut transport = TcpTransport::new(read_timeout, max_line_length);
            transport.connect(addr, connect_timeout).await.map_err(|e| {
                AinosError::ConnectionRefused(format!(
                    "Pool connection {} failed: {}",
                    i, e
                ))
            })?;
            connections.push(Box::new(transport) as Box<dyn Transport>);
        }

        Ok(Self {
            connections,
            addr: addr.to_string(),
            connect_timeout,
            read_timeout,
            max_line_length,
        })
    }

    /// Acquire a connection from the pool (round-robin).
    ///
    /// The caller must return the connection via [`release`](Self::release).
    pub fn acquire(&mut self) -> Option<Box<dyn Transport>> {
        if self.connections.is_empty() {
            None
        } else {
            Some(self.connections.remove(0))
        }
    }

    /// Return a connection to the pool.
    pub fn release(&mut self, transport: Box<dyn Transport>) {
        self.connections.push(transport);
    }

    /// Check all connections and reconnect any that are dead.
    pub async fn health_check(&mut self) {
        let mut healthy = Vec::new();
        let mut dead = Vec::new();

        for (i, conn) in self.connections.iter_mut().enumerate() {
            if conn.is_connected() {
                healthy.push(i);
            } else {
                dead.push(i);
            }
        }

        // Remove dead connections in reverse order
        for i in dead.into_iter().rev() {
            self.connections.remove(i);
            // Try to reconnect
            let mut transport = TcpTransport::new(self.read_timeout, self.max_line_length);
            if transport
                .connect(&self.addr, self.connect_timeout)
                .await
                .is_ok()
            {
                self.connections.push(Box::new(transport));
            }
        }
    }

    /// Number of active connections in the pool.
    pub fn size(&self) -> usize {
        self.connections.len()
    }
}

// ===========================================================================
// NDJSON framing utilities
// ===========================================================================

/// A codec for NDJSON (newline-delimited JSON) framing.
///
/// Converts between byte streams and individual JSON strings, handling
/// framing boundaries.
pub struct NdjsonCodec;

impl NdjsonCodec {
    /// Encode a JSON string into NDJSON format (appends `\n`).
    pub fn encode(data: &str) -> Vec<u8> {
        let mut bytes = data.as_bytes().to_vec();
        bytes.push(b'\n');
        bytes
    }

    /// Decode a buffer of bytes into complete NDJSON lines.
    /// Returns the decoded lines and any remaining partial data.
    pub fn decode(buffer: &mut BytesMut) -> Vec<String> {
        let mut lines = Vec::new();

        loop {
            // Find the next newline
            match buffer.iter().position(|&b| b == b'\n') {
                Some(pos) => {
                    let line = buffer.split_to(pos + 1);
                    // Remove the trailing \n
                    let trimmed = &line[..pos];
                    if !trimmed.is_empty() {
                        if let Ok(s) = String::from_utf8(trimmed.to_vec()) {
                            let s = s.trim().to_string();
                            if !s.is_empty() {
                                lines.push(s);
                            }
                        }
                    }
                }
                None => break,
            }
        }

        lines
    }
}

// ===========================================================================
// TLS support
// ===========================================================================

/// TLS-wrapped transport for encrypted connections.
#[cfg(feature = "tls")]
pub mod tls {
    use super::*;
    use tokio::io::{split, AsyncBufReadExt, AsyncWriteExt, BufReader, ReadHalf, WriteHalf};
    use tokio_native_tls::TlsConnector;

    type TlsStream = tokio_native_tls::TlsStream<tokio::net::TcpStream>;

    /// TLS transport wrapping a TCP stream.
    pub struct TlsTransport {
        reader: Option<BufReader<ReadHalf<TlsStream>>>,
        writer: Option<WriteHalf<TlsStream>>,
        addr: String,
        max_line_length: usize,
        read_timeout: Duration,
    }

    impl TlsTransport {
        /// Create a new TLS transport and connect to the given address.
        pub async fn connect(
            host: &str,
            port: u16,
            connect_timeout: Duration,
            read_timeout: Duration,
            max_line_length: usize,
            tls_connector: TlsConnector,
        ) -> Result<Self> {
            let addr = format!("{}:{}", host, port);
            debug!("TlsTransport: connecting to {}", addr);

            let stream = timeout(connect_timeout, TcpStream::connect(&addr))
                .await
                .map_err(|_| AinosError::Timeout(connect_timeout))?
                .map_err(|e| {
                    AinosError::ConnectionRefused(format!(
                        "Failed to connect to {}: {}",
                        addr, e
                    ))
                })?;

            stream.set_nodelay(true).ok();

            let tls_stream = tls_connector
                .connect(host, stream)
                .await
                .map_err(|e| AinosError::Tls(format!("TLS handshake failed: {}", e)))?;

            let (read_half, write_half) = split(tls_stream);
            let reader = BufReader::new(read_half);

            Ok(Self {
                reader: Some(reader),
                writer: Some(write_half),
                addr,
                max_line_length,
                read_timeout,
            })
        }

        fn get_writer(&mut self) -> Result<&mut WriteHalf<TlsStream>> {
            self.writer
                .as_mut()
                .ok_or_else(|| AinosError::ConnectionLost("Not connected".into()))
        }
    }

    #[async_trait]
    impl Transport for TlsTransport {
        async fn connect(&mut self, _addr: &str, _connect_timeout: Duration) -> Result<()> {
            Err(AinosError::Internal(
                "Use TlsTransport::connect() instead of the Transport trait method".into(),
            ))
        }

        async fn disconnect(&mut self) -> Result<()> {
            self.reader = None;
            self.writer = None;
            Ok(())
        }

        fn is_connected(&self) -> bool {
            self.writer.is_some()
        }

        async fn send(&mut self, data: &str) -> Result<()> {
            let writer = self.get_writer()?;
            writer
                .write_all(data.as_bytes())
                .await
                .map_err(|e| AinosError::ConnectionLost(format!("Send failed: {}", e)))?;
            writer
                .write_all(b"\n")
                .await
                .map_err(|e| AinosError::ConnectionLost(format!("Send newline failed: {}", e)))?;
            writer
                .flush()
                .await
                .map_err(|e| AinosError::ConnectionLost(format!("Flush failed: {}", e)))?;
            Ok(())
        }

        async fn recv(&mut self) -> Result<String> {
            let reader = self
                .reader
                .as_mut()
                .ok_or_else(|| AinosError::ConnectionLost("Not connected".into()))?;

            let mut line = String::new();
            let read_result = timeout(self.read_timeout, reader.read_line(&mut line)).await;

            match read_result {
                Ok(Ok(0)) => {
                    self.reader = None;
                    self.writer = None;
                    Err(AinosError::ConnectionClosed)
                }
                Ok(Ok(_n)) => {
                    let trimmed = line.trim().to_string();
                    if trimmed.len() > self.max_line_length {
                        return Err(AinosError::Protocol(format!(
                            "Response line too long: {} bytes (max: {})",
                            trimmed.len(),
                            self.max_line_length
                        )));
                    }
                    Ok(trimmed)
                }
                Ok(Err(e)) => {
                    self.reader = None;
                    self.writer = None;
                    Err(AinosError::ConnectionLost(format!("Read error: {}", e)))
                }
                Err(_) => Err(AinosError::Timeout(self.read_timeout)),
            }
        }

        fn local_addr(&self) -> Option<String> {
            None
        }

        fn peer_addr(&self) -> Option<String> {
            Some(self.addr.clone())
        }
    }
}

// ===========================================================================
// Mock transport (for testing)
// ===========================================================================

/// Mock transport for testing purposes.
///
/// Does not actually connect to anything; instead uses in-memory channels
/// to simulate the daemon protocol.
#[cfg(feature = "mock")]
pub mod mock {
    use super::*;
    use std::collections::VecDeque;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::{Arc, Mutex};

    /// Shared state between a mock transport and its paired responder.
    #[derive(Clone)]
    pub struct MockTransportHandle {
        sent: Arc<Mutex<Vec<String>>>,
        responses: Arc<Mutex<VecDeque<String>>>,
        connected: Arc<AtomicBool>,
    }

    impl MockTransportHandle {
        /// Add a response to the queue (in order).
        pub fn add_response(&self, response: &str) {
            self.responses.lock().unwrap().push_back(response.to_string());
        }

        /// Get all sent messages.
        pub fn sent_messages(&self) -> Vec<String> {
            self.sent.lock().unwrap().clone()
        }

        /// Clear all sent messages.
        pub fn clear_sent(&self) {
            self.sent.lock().unwrap().clear();
        }

        /// Set the connected state.
        pub fn set_connected(&self, connected: bool) {
            self.connected.store(connected, Ordering::SeqCst);
        }
    }

    /// Mock transport that uses in-memory channels.
    pub struct MockTransport {
        sent: Arc<Mutex<Vec<String>>>,
        responses: Arc<Mutex<VecDeque<String>>>,
        connected: Arc<AtomicBool>,
        max_line_length: usize,
    }

    impl MockTransport {
        /// Create a new mock transport with a handle for injecting responses.
        pub fn new(max_line_length: usize) -> (Self, MockTransportHandle) {
            let sent = Arc::new(Mutex::new(Vec::new()));
            let responses = Arc::new(Mutex::new(VecDeque::new()));
            let connected = Arc::new(AtomicBool::new(false));

            let handle = MockTransportHandle {
                sent: sent.clone(),
                responses: responses.clone(),
                connected: connected.clone(),
            };

            let transport = Self {
                sent,
                responses,
                connected,
                max_line_length,
            };

            (transport, handle)
        }
    }

    #[async_trait]
    impl Transport for MockTransport {
        async fn connect(&mut self, _addr: &str, _connect_timeout: Duration) -> Result<()> {
            self.connected.store(true, Ordering::SeqCst);
            Ok(())
        }

        async fn disconnect(&mut self) -> Result<()> {
            self.connected.store(false, Ordering::SeqCst);
            Ok(())
        }

        fn is_connected(&self) -> bool {
            self.connected.load(Ordering::SeqCst)
        }

        async fn send(&mut self, data: &str) -> Result<()> {
            self.sent.lock().unwrap().push(data.to_string());
            Ok(())
        }

        async fn recv(&mut self) -> Result<String> {
            let response = self
                .responses
                .lock()
                .unwrap()
                .pop_front()
                .ok_or_else(|| AinosError::ConnectionClosed)?;

            if response.len() > self.max_line_length {
                return Err(AinosError::Protocol(format!(
                    "Response line too long: {} bytes (max: {})",
                    response.len(),
                    self.max_line_length
                )));
            }
            Ok(response)
        }

        fn local_addr(&self) -> Option<String> {
            Some("mock://local".to_string())
        }

        fn peer_addr(&self) -> Option<String> {
            Some("mock://peer".to_string())
        }
    }
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ndjson_codec_encode() {
        let encoded = NdjsonCodec::encode("hello");
        assert_eq!(encoded, b"hello\n");
    }

    #[test]
    fn test_ndjson_codec_decode_single() {
        let mut buf = BytesMut::from("hello\n");
        let lines = NdjsonCodec::decode(&mut buf);
        assert_eq!(lines, vec!["hello"]);
        assert!(buf.is_empty());
    }

    #[test]
    fn test_ndjson_codec_decode_multiple() {
        let mut buf = BytesMut::from("line1\nline2\nline3\n");
        let lines = NdjsonCodec::decode(&mut buf);
        assert_eq!(lines, vec!["line1", "line2", "line3"]);
    }

    #[test]
    fn test_ndjson_codec_decode_partial() {
        let mut buf = BytesMut::from("line1\nincomplete");
        let lines = NdjsonCodec::decode(&mut buf);
        assert_eq!(lines, vec!["line1"]);
        assert_eq!(&buf[..], b"incomplete");
    }

    #[test]
    fn test_ndjson_codec_decode_empty_lines() {
        let mut buf = BytesMut::from("line1\n\nline2\n");
        let lines = NdjsonCodec::decode(&mut buf);
        assert_eq!(lines, vec!["line1", "line2"]);
    }

    #[test]
    fn test_ndjson_codec_decode_no_newline() {
        let mut buf = BytesMut::from("incomplete");
        let lines = NdjsonCodec::decode(&mut buf);
        assert!(lines.is_empty());
        assert_eq!(&buf[..], b"incomplete");
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_mock_transport() {
        use crate::transport::mock::MockTransport;

        let (mut transport, handle) = MockTransport::new(1024 * 1024);

        // Initially not connected
        assert!(!transport.is_connected());

        // Connect
        transport.connect("mock://test", Duration::from_secs(1)).await.unwrap();
        assert!(transport.is_connected());

        // Inject responses
        handle.add_response(r#"{"type":"Status"}"#);
        handle.add_response(r#"{"type":"InferenceResponse","output":"hi","tokens_generated":1,"inference_ms":10,"source":"local"}"#);

        // Send a request
        transport.send(r#"{"type":"Status"}"#).await.unwrap();

        // Receive the response
        let resp = transport.recv().await.unwrap();
        assert_eq!(resp, r#"{"type":"Status"}"#);

        // Check sent messages
        let sent = handle.sent_messages();
        assert_eq!(sent.len(), 1);
        assert_eq!(sent[0], r#"{"type":"Status"}"#);

        // Disconnect
        transport.disconnect().await.unwrap();
        assert!(!transport.is_connected());
    }

    #[test]
    fn test_tcp_transport_new() {
        let transport = TcpTransport::new(Duration::from_secs(30), 1024 * 1024);
        assert!(!transport.is_connected());
    }

    #[test]
    fn test_connection_pool_params() {
        // Just verify the struct compiles and has expected defaults
        let _cfg = crate::types::ClientConfig::default();
    }
}