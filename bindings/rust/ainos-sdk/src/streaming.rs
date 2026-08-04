//! Streaming inference support for the Ainos SDK.
//!
//! Provides [`InferenceStream`] for consuming token-by-token streaming
//! responses from the daemon, with backpressure handling and cancellation
//! via drop.

use crate::error::{AinosError, Result};
use crate::transport::Transport;
use crate::types::{InferenceChunk, IpcMessage};
use futures::Stream;
use std::pin::Pin;
use std::task::{Context, Poll};
use tokio::sync::mpsc;
use tracing::{debug, error, trace};

// ===========================================================================
// InferenceStream
// ===========================================================================

/// A streaming sequence of [`InferenceChunk`] values from the daemon.
///
/// This is an async [`Stream`] that yields chunks as they arrive over the
/// transport. The stream can be cancelled by dropping it.
///
/// # Backpressure
///
/// An internal bounded channel (default capacity 1024) buffers chunks
/// between the read task and the consumer. If the consumer is slow, the
/// read task will block on sending, applying backpressure to the daemon
/// (the daemon will block on its TCP write if the receive buffer fills).
///
/// # Cancellation
///
/// Dropping the stream cancels the background read task, which closes
/// the transport channel gracefully.
///
/// # Example
///
/// ```no_run
/// # use ainos_sdk::prelude::*;
/// # async fn example(client: &AinosClient) -> Result<()> {
/// let req = InferenceRequest::builder()
///     .prompt("Tell me a story")
///     .build();
///
/// let mut stream = client.infer_stream(&req).await?;
/// while let Some(chunk) = stream.next().await {
///     match chunk {
///         Ok(chunk) => {
///             print!("{}", chunk.chunk);
///             if chunk.done { break; }
///         }
///         Err(e) => eprintln!("Stream error: {}", e),
///     }
/// }
/// # Ok(())
/// # }
/// ```
pub struct InferenceStream {
    /// Receiver for chunks from the background read task.
    rx: mpsc::Receiver<Result<InferenceChunk>>,

    /// Handle to the background read task.
    read_task: Option<tokio::task::JoinHandle<()>>,

    /// Whether the stream has been cancelled.
    cancelled: bool,
}

impl InferenceStream {
    /// Maximum number of chunks to buffer in the channel.
    const DEFAULT_BUFFER_SIZE: usize = 1024;

    /// Create a new `InferenceStream`.
    ///
    /// Spawns a background task that reads lines from the transport and
    /// sends parsed chunks into the channel.
    pub fn new(
        transport: Box<dyn Transport>,
        buffer_size: Option<usize>,
    ) -> Self {
        let capacity = buffer_size.unwrap_or(Self::DEFAULT_BUFFER_SIZE);
        let (tx, rx) = mpsc::channel(capacity);

        let read_task = tokio::spawn(async move {
            Self::read_loop(transport, tx).await;
        });

        Self {
            rx,
            read_task: Some(read_task),
            cancelled: false,
        }
    }

    /// Background read loop: reads lines from the transport and sends chunks.
    async fn read_loop(
        mut transport: Box<dyn Transport>,
        tx: mpsc::Sender<Result<InferenceChunk>>,
    ) {
        loop {
            let line = match transport.recv().await {
                Ok(line) => line,
                Err(AinosError::ConnectionClosed) => {
                    debug!("InferenceStream: connection closed by peer");
                    let _ = tx.send(Err(AinosError::ConnectionClosed)).await;
                    break;
                }
                Err(e) => {
                    error!("InferenceStream: transport error: {}", e);
                    let _ = tx.send(Err(e)).await;
                    break;
                }
            };

            // Parse the JSON line
            let msg: IpcMessage = match serde_json::from_str(&line) {
                Ok(msg) => msg,
                Err(e) => {
                    error!("InferenceStream: failed to parse chunk: {}", e);
                    let _ = tx
                        .send(Err(AinosError::Protocol(format!(
                            "Failed to parse chunk: {}",
                            e
                        ))))
                        .await;
                    break;
                }
            };

            // Check for errors
            if let IpcMessage::Error { code, message } = &msg {
                let _ = tx
                    .send(Err(AinosError::DaemonError {
                        code: *code,
                        message: message.clone(),
                    }))
                    .await;
                break;
            }

            // Extract the chunk
            match InferenceChunk::from_ipc_message(&msg) {
                Some(chunk) => {
                    let is_done = chunk.done;
                    trace!("InferenceStream: chunk received (done={})", is_done);

                    if tx.send(Ok(chunk)).await.is_err() {
                        // Receiver was dropped (cancellation)
                        debug!("InferenceStream: receiver dropped, stopping read loop");
                        break;
                    }

                    if is_done {
                        debug!("InferenceStream: stream complete");
                        break;
                    }
                }
                None => {
                    // Unexpected message type
                    let _ = tx
                        .send(Err(AinosError::UnexpectedResponse(format!(
                            "Expected InferenceChunk, got: {:?}",
                            msg
                        ))))
                        .await;
                    break;
                }
            }
        }
    }

    /// Cancel the stream and stop the background task.
    pub fn cancel(&mut self) {
        if !self.cancelled {
            self.cancelled = true;
            if let Some(handle) = self.read_task.take() {
                handle.abort();
            }
            self.rx.close();
        }
    }

    /// Collect all remaining chunks into a single string.
    ///
    /// This consumes the stream and concatenates all chunks until the
    /// stream ends or an error occurs.
    pub async fn collect_string(&mut self) -> Result<String> {
        let mut result = String::new();
        use futures::StreamExt;
        while let Some(chunk) = self.next().await {
            match chunk {
                Ok(c) => {
                    result.push_str(&c.chunk);
                    if c.done {
                        break;
                    }
                }
                Err(e) => return Err(e),
            }
        }
        Ok(result)
    }

    /// Skip all remaining chunks (consume to completion).
    pub async fn drain(&mut self) -> Result<()> {
        use futures::StreamExt;
        while let Some(chunk) = self.next().await {
            match chunk {
                Ok(c) if c.done => break,
                Err(e) => return Err(e),
                _ => continue,
            }
        }
        Ok(())
    }
}

impl Drop for InferenceStream {
    fn drop(&mut self) {
        self.cancel();
    }
}

impl Stream for InferenceStream {
    type Item = Result<InferenceChunk>;

    fn poll_next(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        let this = self.get_mut();

        if this.cancelled {
            return Poll::Ready(None);
        }

        // Poll the receiver
        match this.rx.poll_recv(cx) {
            Poll::Ready(Some(item)) => Poll::Ready(Some(item)),
            Poll::Ready(None) => Poll::Ready(None),
            Poll::Pending => Poll::Pending,
        }
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        (0, None)
    }
}

// ===========================================================================
// ChunkedReceiver
// ===========================================================================

/// A synchronous-style receiver for streaming chunks.
///
/// Wraps an `mpsc::Receiver` to provide a `blocking_recv` interface for
/// non-async contexts.
pub struct ChunkedReceiver {
    rx: mpsc::Receiver<Result<InferenceChunk>>,
    cancelled: bool,
}

impl ChunkedReceiver {
    /// Create a new `ChunkedReceiver`.
    pub fn new(rx: mpsc::Receiver<Result<InferenceChunk>>) -> Self {
        Self {
            rx,
            cancelled: false,
        }
    }

    /// Receive the next chunk, blocking the current thread.
    ///
    /// This is only available in non-async contexts. For async, use
    /// the `Stream` implementation on `InferenceStream`.
    pub fn blocking_recv(&mut self) -> Option<Result<InferenceChunk>> {
        if self.cancelled {
            return None;
        }
        self.rx.blocking_recv()
    }

    /// Cancel the receiver.
    pub fn cancel(&mut self) {
        self.cancelled = true;
        self.rx.close();
    }
}

// ===========================================================================
// Utility functions
// ===========================================================================

/// Parse a single NDJSON line into an `InferenceChunk`, if possible.
pub fn parse_chunk_line(line: &str) -> Result<InferenceChunk> {
    let msg: IpcMessage = serde_json::from_str(line)?;

    if let IpcMessage::Error { code, message } = &msg {
        return Err(AinosError::DaemonError {
            code: *code,
            message: message.clone(),
        });
    }

    InferenceChunk::from_ipc_message(&msg).ok_or_else(|| {
        AinosError::UnexpectedResponse(format!(
            "Expected InferenceChunk, got: {}",
            line
        ))
    })
}

/// Accumulate an iterator of chunk results into a single string.
pub fn accumulate_chunks<I>(chunks: I) -> Result<String>
where
    I: IntoIterator<Item = Result<InferenceChunk>>,
{
    let mut output = String::new();
    for chunk in chunks {
        let chunk = chunk?;
        output.push_str(&chunk.chunk);
        if chunk.done {
            break;
        }
    }
    Ok(output)
}

// ===========================================================================
// Backpressure buffer
// ===========================================================================

/// A bounded buffer that provides backpressure-aware chunk processing.
///
/// This is used internally by the streaming infrastructure to prevent
/// memory exhaustion when the consumer is slower than the producer.
pub struct BackpressureBuffer {
    capacity: usize,
    used: usize,
    dropped: u64,
}

impl BackpressureBuffer {
    /// Create a new buffer with the given capacity.
    pub fn new(capacity: usize) -> Self {
        Self {
            capacity,
            used: 0,
            dropped: 0,
        }
    }

    /// Try to reserve space in the buffer.
    ///
    /// Returns `true` if space was reserved, `false` if the buffer is full.
    pub fn try_reserve(&mut self, size: usize) -> bool {
        if self.used + size > self.capacity {
            self.dropped += 1;
            return false;
        }
        self.used += size;
        true
    }

    /// Release previously reserved space.
    pub fn release(&mut self, size: usize) {
        self.used = self.used.saturating_sub(size);
    }

    /// Number of chunks dropped due to backpressure.
    pub fn dropped_count(&self) -> u64 {
        self.dropped
    }

    /// Current utilization as a ratio (0.0 – 1.0).
    pub fn utilization(&self) -> f64 {
        if self.capacity == 0 {
            return 0.0;
        }
        self.used as f64 / self.capacity as f64
    }

    /// Reset the buffer.
    pub fn reset(&mut self) {
        self.used = 0;
        self.dropped = 0;
    }
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::transport::mock::MockTransport;
    use std::time::Duration;

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_inference_stream_basic() {
        let (mut transport, handle) = MockTransport::new(1024 * 1024);
        transport
            .connect("mock://test", Duration::from_secs(1))
            .await
            .unwrap();

        // Inject streaming chunks
        handle.add_response(r#"{"type":"InferenceChunk","chunk":"Hello","done":false}"#);
        handle.add_response(r#"{"type":"InferenceChunk","chunk":" world","done":false}"#);
        handle.add_response(r#"{"type":"InferenceChunk","chunk":"!","done":true}"#);

        let mut stream = InferenceStream::new(Box::new(transport), None);

        use futures::StreamExt;
        let mut output = String::new();
        while let Some(chunk) = stream.next().await {
            let chunk = chunk.unwrap();
            output.push_str(&chunk.chunk);
            if chunk.done {
                break;
            }
        }

        assert_eq!(output, "Hello world!");
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_inference_stream_error() {
        let (mut transport, handle) = MockTransport::new(1024 * 1024);
        transport
            .connect("mock://test", Duration::from_secs(1))
            .await
            .unwrap();

        // Inject an error response
        handle.add_response(
            r#"{"type":"Error","code":500,"message":"Internal server error"}"#,
        );

        let mut stream = InferenceStream::new(Box::new(transport), None);

        use futures::StreamExt;
        let chunk = stream.next().await;
        assert!(chunk.is_some());
        assert!(chunk.unwrap().is_err());
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_inference_stream_cancel() {
        let (mut transport, handle) = MockTransport::new(1024 * 1024);
        transport
            .connect("mock://test", Duration::from_secs(1))
            .await
            .unwrap();

        handle.add_response(r#"{"type":"InferenceChunk","chunk":"a","done":false}"#);
        handle.add_response(r#"{"type":"InferenceChunk","chunk":"b","done":false}"#);
        handle.add_response(r#"{"type":"InferenceChunk","chunk":"c","done":true}"#);

        let mut stream = InferenceStream::new(Box::new(transport), None);

        use futures::StreamExt;
        let chunk = stream.next().await;
        assert!(chunk.is_some());
        // Cancel before reading the rest
        stream.cancel();
        let chunk = stream.next().await;
        assert!(chunk.is_none());
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_collect_string() {
        let (mut transport, handle) = MockTransport::new(1024 * 1024);
        transport
            .connect("mock://test", Duration::from_secs(1))
            .await
            .unwrap();

        handle.add_response(r#"{"type":"InferenceChunk","chunk":"Hello","done":false}"#);
        handle.add_response(r#"{"type":"InferenceChunk","chunk":" ","done":false}"#);
        handle.add_response(r#"{"type":"InferenceChunk","chunk":"World","done":true}"#);

        let mut stream = InferenceStream::new(Box::new(transport), None);
        let result = stream.collect_string().await.unwrap();
        assert_eq!(result, "Hello World");
    }

    #[test]
    fn test_parse_chunk_line() {
        let line = r#"{"type":"InferenceChunk","chunk":"Hello","done":false}"#;
        let chunk = parse_chunk_line(line).unwrap();
        assert_eq!(chunk.chunk, "Hello");
        assert!(!chunk.done);
    }

    #[test]
    fn test_parse_chunk_line_error() {
        let line = r#"{"type":"Error","code":429,"message":"Rate limited"}"#;
        let result = parse_chunk_line(line);
        assert!(result.is_err());
        match result.unwrap_err() {
            AinosError::DaemonError { code, .. } => assert_eq!(code, 429),
            e => panic!("Expected DaemonError with code 429, got: {}", e),
        }
    }

    #[test]
    fn test_accumulate_chunks() {
        let chunks = vec![
            Ok(InferenceChunk {
                chunk: "Hello".into(),
                done: false,
            }),
            Ok(InferenceChunk {
                chunk: " World".into(),
                done: false,
            }),
            Ok(InferenceChunk {
                chunk: "!".into(),
                done: true,
            }),
        ];
        let result = accumulate_chunks(chunks).unwrap();
        assert_eq!(result, "Hello World!");
    }

    #[test]
    fn test_backpressure_buffer() {
        let mut buf = BackpressureBuffer::new(100);

        assert!(buf.try_reserve(50));
        assert!(!buf.try_reserve(60)); // would exceed capacity
        assert_eq!(buf.dropped_count(), 1);
        assert_eq!(buf.utilization(), 0.5);

        buf.release(50);
        assert_eq!(buf.utilization(), 0.0);

        buf.reset();
        assert_eq!(buf.dropped_count(), 0);
    }

    #[test]
    fn test_chunked_receiver() {
        let (tx, rx) = mpsc::channel(10);
        let mut receiver = ChunkedReceiver::new(rx);

        // Send a chunk
        tx.try_send(Ok(InferenceChunk {
            chunk: "test".into(),
            done: true,
        }))
        .unwrap();

        // Receive it
        let chunk = receiver.blocking_recv().unwrap().unwrap();
        assert_eq!(chunk.chunk, "test");
        assert!(chunk.done);
    }
}