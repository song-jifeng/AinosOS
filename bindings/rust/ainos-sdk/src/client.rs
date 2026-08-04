//! Core client for the Ainos AI Daemon.
//!
//! [`AinosClient`] is the main entry point for communicating with the daemon.
//! It manages a TCP connection, handles authentication, and provides methods
//! for inference, model management, context operations, and status queries.

use crate::auth::SessionManager;
use crate::error::{AinosError, RetryKind, Retryable, Result};
use crate::streaming::InferenceStream;
use crate::transport::{TcpTransport, Transport};
use crate::types::{
    check_error, parse_response, ClientConfig, HealthStatus, IpcMessage,
    InferenceRequest, InferenceResponse, ModelInfo, ModelLoadOptions, RateLimitStatus, Session,
    SystemStatus,
};
use tokio::sync::RwLock;
use tokio::time::sleep;
use tracing::{debug, info, warn};

// ===========================================================================
// AinosClient
// ===========================================================================

/// A TCP/IP client for the Ainos AI Daemon.
///
/// `AinosClient` provides a high-level async interface for all daemon
/// operations. It manages the connection lifecycle, handles authentication,
/// and provides automatic reconnection with exponential backoff.
///
/// # Thread safety
///
/// `AinosClient` is thread-safe (`Send + Sync`) and can be shared across
/// tasks via `Arc<AinosClient>`.
///
/// # Example
///
/// ```no_run
/// # use ainos_sdk::{AinosClient, InferenceRequest};
/// # async fn example() -> Result<(), Box<dyn std::error::Error>> {
/// let client = AinosClient::builder()
///     .host("127.0.0.1")
///     .port(9500)
///     .auth_token("my-token")
///     .build();
///
/// client.connect().await?;
///
/// // Basic inference
/// let resp = client.infer(&InferenceRequest::builder()
///     .prompt("Hello, Ainos!")
///     .build()
/// ).await?;
/// println!("{}", resp.output);
///
/// client.disconnect().await?;
/// # Ok(())
/// # }
/// ```
pub struct AinosClient {
    /// Client configuration.
    config: ClientConfig,

    /// The transport connection (TCP, Unix, or mock).
    pub transport: RwLock<Option<Box<dyn Transport>>>,

    /// Session manager for authentication.
    session_manager: SessionManager,

    /// Whether the client is currently connected.
    pub connected: RwLock<bool>,
}

impl AinosClient {
    // ======================================================================
    // Construction
    // ======================================================================

    /// Create a new [`AinosClientBuilder`].
    pub fn builder() -> crate::builder::AinosClientBuilder {
        crate::builder::AinosClientBuilder::new()
    }

    /// Create a new `AinosClient` with the given configuration.
    ///
    /// This does not connect to the daemon; call [`connect`](Self::connect) separately.
    pub fn new(config: ClientConfig) -> Self {
        let session_manager = match &config.auth_token {
            Some(token) => SessionManager::with_token(token),
            None => SessionManager::new(),
        };
        Self::with_config(config, session_manager)
    }

    /// Create a new `AinosClient` with explicit config and session manager.
    ///
    /// This is useful for advanced use cases where you want to control the
    /// session manager lifecycle (e.g. for testing).
    pub fn with_config(config: ClientConfig, session_manager: SessionManager) -> Self {
        Self {
            config,
            transport: RwLock::new(None),
            session_manager,
            connected: RwLock::new(false),
        }
    }

    // ======================================================================
    // Connection lifecycle
    // ======================================================================

    /// Connect to the daemon.
    ///
    /// If `auth_token` and `auto_authenticate` are set, this will also
    /// attempt authentication after connecting.
    pub async fn connect(&self) -> Result<()> {
        let mut connected = self.connected.write().await;
        if *connected {
            debug!("AinosClient: already connected");
            return Ok(());
        }

        let addr = format!("{}:{}", self.config.host, self.config.port);
        info!("AinosClient: connecting to {}", addr);

        let transport = TcpTransport::connect(
            &self.config.host,
            self.config.port,
            self.config.connect_timeout,
            self.config.read_timeout,
            self.config.max_line_length,
        )
        .await?;

        *self.transport.write().await = Some(Box::new(transport));
        *connected = true;
        info!("AinosClient: connected to {}", addr);

        // Auto-authenticate
        if self.config.auth_token.is_some() && self.config.auto_authenticate {
            if let Some(token) = self.config.auth_token.clone() {
                debug!("AinosClient: auto-authenticating");
                self.authenticate(&token).await?;
            }
        }

        Ok(())
    }

    /// Disconnect from the daemon.
    pub async fn disconnect(&self) -> Result<()> {
        let mut connected = self.connected.write().await;
        if !*connected {
            return Ok(());
        }

        info!("AinosClient: disconnecting");
        if let Some(mut transport) = self.transport.write().await.take() {
            transport.disconnect().await?;
        }
        self.session_manager.clear_session().await;
        *connected = false;
        info!("AinosClient: disconnected");
        Ok(())
    }

    /// Reconnect to the daemon with exponential backoff.
    ///
    /// This will attempt to reconnect up to `max_retries` times with
    /// exponential backoff.
    pub async fn reconnect(&self) -> Result<()> {
        info!("AinosClient: reconnecting");
        let _ = self.disconnect().await;

        let retry_config = &self.config.retry_config;
        let mut last_error = None;

        for attempt in 0..retry_config.max_retries {
            match self.connect().await {
                Ok(()) => {
                    info!("AinosClient: reconnected successfully after {} attempt(s)", attempt + 1);
                    return Ok(());
                }
                Err(e) => {
                    warn!("AinosClient: reconnect attempt {} failed: {}", attempt + 1, e);
                    last_error = Some(e);
                    if attempt + 1 < retry_config.max_retries {
                        let backoff = retry_config.backoff(attempt);
                        debug!("AinosClient: backing off for {:?}", backoff);
                        sleep(backoff).await;
                    }
                }
            }
        }

        Err(last_error.unwrap_or_else(|| {
            AinosError::ConnectionRefused("Max reconnect attempts exceeded".into())
        }))
    }

    /// Returns `true` if the client is currently connected.
    pub async fn is_connected(&self) -> bool {
        *self.connected.read().await
    }

    /// Returns `true` if the client is authenticated.
    pub async fn is_authenticated(&self) -> bool {
        self.session_manager.is_authenticated().await
    }

    /// Get the current session token, if authenticated.
    pub async fn session_token(&self) -> Option<String> {
        self.session_manager.session_token().await
    }

    /// Get the current session permissions.
    pub async fn permissions(&self) -> Vec<String> {
        self.session_manager.permissions().await
    }

    // ======================================================================
    // Authentication
    // ======================================================================

    /// Authenticate with the daemon using a bearer token.
    ///
    /// If the token is valid, the client will store the session token and
    /// permissions for subsequent requests.
    pub async fn authenticate(&self, token: &str) -> Result<Session> {
        debug!("AinosClient: authenticating");

        // Update the token in the session manager
        self.session_manager.set_token(token).await;

        let auth_msg = self
            .session_manager
            .build_auth_message()
            .await
            .ok_or_else(|| AinosError::AuthFailed("No authentication token".into()))?;

        let response = self.send_recv(&auth_msg).await?;

        let session = Session::from_ipc_message(&response).ok_or_else(|| {
            AinosError::UnexpectedResponse("Expected AuthResponse".into())
        })?;

        if !session.success {
            return Err(AinosError::AuthFailed(
                session.message.clone(),
            ));
        }

        // Store the session (convert from types::Session to auth::Session)
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        let auth_session = crate::auth::Session {
            session_token: session.session_token.clone(),
            success: session.success,
            message: session.message.clone(),
            permissions: session.permissions.clone(),
            session_ttl_seconds: session.session_ttl_seconds,
            created_at: now,
        };
        self.session_manager.set_session(auth_session).await;

        info!("AinosClient: authenticated successfully");
        Ok(session)
    }

    // ======================================================================
    // Inference
    // ======================================================================

    /// Send an inference request and receive the full response.
    ///
    /// For streaming responses, use [`infer_stream`](Self::infer_stream).
    pub async fn infer(&self, req: &InferenceRequest) -> Result<InferenceResponse> {
        let msg = req.to_ipc_message();
        let response = self.send_recv_with_retry(&msg, "Inference").await?;

        match response {
            IpcMessage::InferenceResponse {
                output,
                tokens_generated,
                inference_ms,
                source,
            } => Ok(InferenceResponse {
                output,
                tokens_generated,
                inference_ms,
                source,
            }),
            IpcMessage::Error { code, message } => {
                Err(AinosError::DaemonError { code, message })
            }
            _ => Err(AinosError::UnexpectedResponse(format!(
                "Expected InferenceResponse, got: {:?}",
                response
            ))),
        }
    }

    /// Send an inference request and receive a streaming response.
    ///
    /// The returned [`InferenceStream`] implements [`Stream`] and yields
    /// [`InferenceChunk`] values as they arrive.
    pub async fn infer_stream(
        &self,
        req: &InferenceRequest,
    ) -> Result<InferenceStream> {
        // Ensure we're connected
        self.ensure_connected().await?;

        let msg = req.to_stream_ipc_message();
        let msg_json = serde_json::to_string(&msg)?;

        // Get a dedicated transport for streaming
        let mut transport = self.clone_transport().await?;

        // Send the streaming request
        transport
            .send(&msg_json)
            .await
            .map_err(|e| AinosError::ConnectionLost(format!("Failed to send stream request: {}", e)))?;

        Ok(InferenceStream::new(transport, None))
    }

    /// Send a batch of inference requests concurrently.
    ///
    /// Each request is sent serially over the shared connection. If you
    /// need true concurrency, use multiple `AinosClient` instances.
    pub async fn batch_infer(&self, reqs: &[InferenceRequest]) -> Result<Vec<InferenceResponse>> {
        let mut results = Vec::with_capacity(reqs.len());
        for req in reqs {
            results.push(self.infer(req).await?);
        }
        Ok(results)
    }

    // ======================================================================
    // Model management
    // ======================================================================

    /// List all registered models.
    pub async fn model_list(&self) -> Result<Vec<ModelInfo>> {
        let response = self.send_recv_with_retry(&IpcMessage::ModelList, "ModelList").await?;

        match response {
            IpcMessage::ModelListResponse { models } => Ok(models),
            IpcMessage::Error { code, message } => {
                Err(AinosError::DaemonError { code, message })
            }
            _ => Err(AinosError::UnexpectedResponse(
                "Expected ModelListResponse".into(),
            )),
        }
    }

    /// Load a model from disk.
    ///
    /// The `path` parameter is the absolute path to the model file on the
    /// daemon's filesystem. Use [`ModelLoadOptions`] for advanced options.
    pub async fn model_load(&self, _path: &str, opts: &ModelLoadOptions) -> Result<ModelInfo> {
        let msg = IpcMessage::ModelLoad {
            path: opts.path.clone(),
        };
        let response = self.send_recv_with_retry(&msg, "ModelLoad").await?;

        match response {
            IpcMessage::ModelLoadResponse {
                status,
                message,
                model_info,
                ..
            } => {
                if status == "error" {
                    Err(AinosError::DaemonError {
                        code: -1,
                        message,
                    })
                } else {
                    model_info.ok_or_else(|| {
                        AinosError::Protocol("ModelLoadResponse missing model_info".into())
                    })
                }
            }
            IpcMessage::Error { code, message } => {
                Err(AinosError::DaemonError { code, message })
            }
            _ => Err(AinosError::UnexpectedResponse(
                "Expected ModelLoadResponse".into(),
            )),
        }
    }

    /// Unload a model from memory.
    pub async fn model_unload(&self, id: &str) -> Result<()> {
        let msg = IpcMessage::ModelUnload {
            model_id: id.to_string(),
        };
        let response = self.send_recv_with_retry(&msg, "ModelUnload").await?;

        match response {
            IpcMessage::ModelUnloadResponse {
                status,
                message, ..
            } => {
                if status == "error" || status == "not_found" {
                    Err(AinosError::DaemonError {
                        code: -1,
                        message,
                    })
                } else {
                    Ok(())
                }
            }
            IpcMessage::Error { code, message } => {
                Err(AinosError::DaemonError { code, message })
            }
            _ => Err(AinosError::UnexpectedResponse(
                "Expected ModelUnloadResponse".into(),
            )),
        }
    }

    // ======================================================================
    // Context management
    // ======================================================================

    /// Store a key-value pair in the daemon's context store.
    ///
    /// The `session_id` groups related context entries. The `ttl` parameter
    /// specifies the time-to-live in seconds (0 = no expiry).
    pub async fn context_store(
        &self,
        session_id: &str,
        key: &str,
        value: &[u8],
        _ttl: u64,
    ) -> Result<()> {
        let value_str = String::from_utf8(value.to_vec())
            .map_err(|e| AinosError::Serialization(format!("Invalid UTF-8 in context value: {}", e)))?;

        let msg = IpcMessage::ContextStore {
            key: format!("{}:{}", session_id, key),
            value: value_str,
        };
        let response = self.send_recv_with_retry(&msg, "ContextStore").await?;

        check_error(&response)?;
        Ok(())
    }

    /// Retrieve a value by key from the daemon's context store.
    pub async fn context_retrieve(
        &self,
        session_id: &str,
        key: &str,
    ) -> Result<Option<Vec<u8>>> {
        let msg = IpcMessage::ContextRetrieve {
            key: format!("{}:{}", session_id, key),
        };
        let response = self.send_recv_with_retry(&msg, "ContextRetrieve").await?;

        match response {
            IpcMessage::InferenceResponse { output, .. } => {
                if output.is_empty() {
                    Ok(None)
                } else {
                    Ok(Some(output.into_bytes()))
                }
            }
            IpcMessage::Error { code: _, message: _ } => Ok(None),
            _ => Err(AinosError::UnexpectedResponse(
                "Expected InferenceResponse or Error".into(),
            )),
        }
    }

    // ======================================================================
    // Status & Health
    // ======================================================================

    /// Query the daemon's system status.
    pub async fn status(&self) -> Result<SystemStatus> {
        let response = self.send_recv_with_retry(&IpcMessage::Status, "Status").await?;

        match response {
            IpcMessage::StatusResponse {
                uptime,
                models_loaded,
                total_requests,
                network_available,
                active_sessions,
                rate_limits,
            } => Ok(SystemStatus {
                uptime,
                models_loaded,
                total_requests,
                network_available,
                active_sessions,
                rate_limits,
            }),
            IpcMessage::Error { code, message } => {
                Err(AinosError::DaemonError { code, message })
            }
            _ => Err(AinosError::UnexpectedResponse(
                "Expected StatusResponse".into(),
            )),
        }
    }

    /// Quick health check of the daemon.
    ///
    /// This is a lightweight check that just verifies the daemon is
    /// reachable and responding.
    pub async fn health(&self) -> Result<HealthStatus> {
        match self.status().await {
            Ok(status) => Ok(HealthStatus {
                healthy: true,
                message: "Daemon is responding".into(),
                database: true,
                engine: status.models_loaded > 0,
                network: status.network_available,
                uptime: status.uptime,
            }),
            Err(e) => Ok(HealthStatus {
                healthy: false,
                message: format!("Health check failed: {}", e),
                database: false,
                engine: false,
                network: false,
                uptime: 0,
            }),
        }
    }

    /// Query the current rate limit status for this session.
    pub async fn rate_limit_status(&self) -> Result<RateLimitStatus> {
        let response = self
            .send_recv_with_retry(&IpcMessage::RateLimitStatus, "RateLimitStatus")
            .await?;

        // RateLimitStatus returns a custom JSON structure
        match &response {
            IpcMessage::RateLimitStatusResponse { limits } => Ok(RateLimitStatus {
                limits: limits.clone(),
            }),
            IpcMessage::Error { code, message } => {
                Err(AinosError::DaemonError {
                    code: *code,
                    message: message.clone(),
                })
            }
            _ => {
                // Try to parse as generic JSON
                let json = serde_json::to_value(&response)?;
                serde_json::from_value(json).map_err(|e| {
                    AinosError::Protocol(format!("Failed to parse RateLimitStatus: {}", e))
                })
            }
        }
    }

    // ======================================================================
    // Internal helpers
    // ======================================================================

    /// Ensure the client is connected, attempting a single reconnect if needed.
    async fn ensure_connected(&self) -> Result<()> {
        let connected = *self.connected.read().await;
        if connected {
            return Ok(());
        }

        if self.config.auto_reconnect {
            warn!("AinosClient: not connected, attempting reconnect");
            // Simple reconnect without recursion
            self.inner_disconnect().await;
            self.inner_connect().await
        } else {
            Err(AinosError::ConnectionRefused("Not connected to daemon".into()))
        }
    }

    /// Inner connect without authentication (avoids recursion).
    async fn inner_connect(&self) -> Result<()> {
        let addr = format!("{}:{}", self.config.host, self.config.port);
        debug!("AinosClient: inner_connect to {}", addr);

        let transport = TcpTransport::connect(
            &self.config.host,
            self.config.port,
            self.config.connect_timeout,
            self.config.read_timeout,
            self.config.max_line_length,
        )
        .await?;

        *self.transport.write().await = Some(Box::new(transport));
        *self.connected.write().await = true;
        info!("AinosClient: connected to {}", addr);
        Ok(())
    }

    /// Inner disconnect without state clearing (avoids recursion).
    async fn inner_disconnect(&self) {
        self.transport.write().await.take();
        *self.connected.write().await = false;
    }

    /// Clone the current transport for use by streaming.
    ///
    /// This creates a new TCP connection to the daemon so that the stream
    /// can run independently of the main request/response flow.
    async fn clone_transport(&self) -> Result<Box<dyn Transport>> {
        let transport = TcpTransport::connect(
            &self.config.host,
            self.config.port,
            self.config.connect_timeout,
            self.config.read_timeout,
            self.config.max_line_length,
        )
        .await?;
        Ok(Box::new(transport))
    }

    /// Send an IPC message and receive the response.
    async fn send_recv(&self, msg: &IpcMessage) -> Result<IpcMessage> {
        self.ensure_connected().await?;

        let json = serde_json::to_string(msg)?;
        debug!("AinosClient: sending: {}", json);

        let mut transport = self.transport.write().await;
        let transport = transport
            .as_mut()
            .ok_or_else(|| AinosError::ConnectionLost("Not connected".into()))?;

        transport.send(&json).await?;
        let line = transport.recv().await?;

        // Re-parse into IpcMessage
        parse_response(&line)
    }

    /// Send an IPC message with retry logic.
    ///
    /// Retries on transient errors up to the configured max retries.
    async fn send_recv_with_retry(
        &self,
        msg: &IpcMessage,
        _operation: &str,
    ) -> Result<IpcMessage> {
        let retry_config = &self.config.retry_config;
        let mut last_error = None;

        for attempt in 0..=retry_config.max_retries {
            match self.send_recv(msg).await {
                Ok(response) => return Ok(response),
                Err(e) => {
                    let retry_kind = e.retry_kind();
                    last_error = Some(e);

                    if retry_kind == RetryKind::Fatal {
                        break;
                    }

                    if attempt < retry_config.max_retries {
                        let backoff = retry_config.backoff(attempt);
                        debug!(
                            "AinosClient: retrying after error (attempt {}), backoff {:?}",
                            attempt + 1,
                            backoff
                        );
                        sleep(backoff).await;
                    }
                }
            }
        }

        Err(last_error.unwrap_or_else(|| {
            AinosError::Internal("send_recv_with_retry: no error recorded".into())
        }))
    }

    /// Get the client configuration.
    pub fn config(&self) -> &ClientConfig {
        &self.config
    }

    /// Get the session manager.
    pub fn session_manager(&self) -> &SessionManager {
        &self.session_manager
    }
}

impl Drop for AinosClient {
    fn drop(&mut self) {
        // Note: we can't call async disconnect from Drop.
        // The transport will be dropped, which closes the connection.
        debug!("AinosClient: dropped");
    }
}

impl std::fmt::Debug for AinosClient {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("AinosClient")
            .field("host", &self.config.host)
            .field("port", &self.config.port)
            .field("connected", &self.connected.try_read().map(|c| *c).unwrap_or(false))
            .finish_non_exhaustive()
    }
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::RetryConfig;
    use std::time::Duration;

    #[cfg(feature = "mock")]
    async fn create_mock_client() -> (AinosClient, crate::transport::mock::MockTransportHandle) {
        use crate::transport::mock::MockTransport;
        let (transport, handle) = MockTransport::new(1024 * 1024);

        let config = ClientConfig {
            host: "mock".into(),
            port: 0,
            connect_timeout: Duration::from_secs(1),
            read_timeout: Duration::from_secs(30),
            auto_reconnect: false,
            reconnect_delay: Duration::from_millis(100),
            auth_token: None,
            auto_authenticate: false,
            retry_config: RetryConfig::default(),
            max_line_length: 1024 * 1024,
        };

        let client = AinosClient::with_config(config, SessionManager::new());
        *client.transport.write().await = Some(Box::new(transport));
        *client.connected.write().await = true;

        (client, handle)
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_infer() {
        let (client, handle) = create_mock_client().await;

        // Inject response
        handle.add_response(
            r#"{"type":"InferenceResponse","output":"Hello!","tokens_generated":1,"inference_ms":50,"source":"local"}"#,
        );

        let req = InferenceRequest::builder().prompt("Hi").build();
        let resp = client.infer(&req).await.unwrap();
        assert_eq!(resp.output, "Hello!");
        assert_eq!(resp.tokens_generated, 1);
        assert_eq!(resp.source, "local");
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_infer_error() {
        let (client, handle) = create_mock_client().await;

        handle.add_response(r#"{"type":"Error","code":500,"message":"Inference failed"}"#);

        let req = InferenceRequest::builder().prompt("Hi").build();
        let result = client.infer(&req).await;
        assert!(result.is_err());
        match result.unwrap_err() {
            AinosError::DaemonError { code, message } => {
                assert_eq!(code, 500);
                assert_eq!(message, "Inference failed");
            }
            e => panic!("Expected DaemonError, got: {}", e),
        }
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_status() {
        let (client, handle) = create_mock_client().await;

        handle.add_response(
            r#"{"type":"StatusResponse","uptime":3600,"models_loaded":2,"total_requests":100,"network_available":true,"active_sessions":5}"#,
        );

        let status = client.status().await.unwrap();
        assert_eq!(status.uptime, 3600);
        assert_eq!(status.models_loaded, 2);
        assert!(status.network_available);
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_model_list() {
        let (client, handle) = create_mock_client().await;

        handle.add_response(
            r#"{"type":"ModelListResponse","models":[{"id":"m1","name":"model1.gguf","path":"/m1.gguf","size_mb":1024,"loaded":true,"architecture":"auto"}]}"#,
        );

        let models = client.model_list().await.unwrap();
        assert_eq!(models.len(), 1);
        assert_eq!(models[0].id, "m1");
        assert!(models[0].loaded);
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_authenticate() {
        let (client, handle) = create_mock_client().await;

        handle.add_response(
            r#"{"type":"AuthResponse","success":true,"session_token":"tok_abc","message":"OK","permissions":["infer","status"],"session_ttl_seconds":3600}"#,
        );

        let session = client.authenticate("my-token").await.unwrap();
        assert!(session.success);
        assert_eq!(session.session_token, "tok_abc");
        assert_eq!(session.permissions, vec!["infer", "status"]);
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_authenticate_failure() {
        let (client, handle) = create_mock_client().await;

        handle.add_response(
            r#"{"type":"AuthResponse","success":false,"session_token":null,"message":"Invalid token","permissions":[],"session_ttl_seconds":0}"#,
        );

        let result = client.authenticate("bad-token").await;
        assert!(result.is_err());
        match result.unwrap_err() {
            AinosError::AuthFailed(msg) => {
                assert_eq!(msg, "Invalid token");
            }
            e => panic!("Expected AuthFailed, got: {}", e),
        }
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_health() {
        let (client, handle) = create_mock_client().await;

        handle.add_response(
            r#"{"type":"StatusResponse","uptime":3600,"models_loaded":2,"total_requests":100,"network_available":true,"active_sessions":5}"#,
        );

        let health = client.health().await.unwrap();
        assert!(health.healthy);
        assert!(health.network);
        assert!(health.engine);
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_health_down() {
        let (client, _handle) = create_mock_client().await;
        // Don't inject any response — the recv will fail

        let health = client.health().await.unwrap();
        assert!(!health.healthy);
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_batch_infer() {
        let (client, handle) = create_mock_client().await;

        handle.add_response(
            r#"{"type":"InferenceResponse","output":"First","tokens_generated":1,"inference_ms":10,"source":"local"}"#,
        );
        handle.add_response(
            r#"{"type":"InferenceResponse","output":"Second","tokens_generated":2,"inference_ms":20,"source":"local"}"#,
        );

        let reqs = vec![
            InferenceRequest::builder().prompt("Req 1").build(),
            InferenceRequest::builder().prompt("Req 2").build(),
        ];

        let results = client.batch_infer(&reqs).await.unwrap();
        assert_eq!(results.len(), 2);
        assert_eq!(results[0].output, "First");
        assert_eq!(results[1].output, "Second");
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_context_store() {
        let (client, handle) = create_mock_client().await;

        handle.add_response(
            r#"{"type":"InferenceResponse","output":"Context stored: sess:key","tokens_generated":0,"inference_ms":0,"source":"local"}"#,
        );

        let result = client
            .context_store("sess", "key", b"value", 3600)
            .await;
        assert!(result.is_ok());
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_context_retrieve() {
        let (client, handle) = create_mock_client().await;

        handle.add_response(
            r#"{"type":"InferenceResponse","output":"stored_value","tokens_generated":0,"inference_ms":0,"source":"local"}"#,
        );

        let result = client.context_retrieve("sess", "key").await.unwrap();
        assert!(result.is_some());
        assert_eq!(result.unwrap(), b"stored_value");
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_context_retrieve_missing() {
        let (client, handle) = create_mock_client().await;

        handle.add_response(r#"{"type":"Error","code":-1,"message":"Key not found: sess:key"}"#);

        let result = client.context_retrieve("sess", "key").await.unwrap();
        assert!(result.is_none());
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_rate_limit_status() {
        let (client, handle) = create_mock_client().await;

        // RateLimitStatus returns a custom JSON
        handle.add_response(
            r#"{"type":"RateLimitStatusResponse","limits":[{"category":"inference","limit":100,"remaining":50,"reset_seconds":30}]}"#,
        );

        let status = client.rate_limit_status().await.unwrap();
        assert_eq!(status.limits.len(), 1);
        assert_eq!(status.limits[0].category, "inference");
        assert_eq!(status.limits[0].limit, 100);
        assert_eq!(status.limits[0].remaining, 50);
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_model_unload() {
        let (client, handle) = create_mock_client().await;

        handle.add_response(
            r#"{"type":"ModelUnloadResponse","model_id":"m1","status":"unloaded","message":"OK"}"#,
        );

        let result = client.model_unload("m1").await;
        assert!(result.is_ok());
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_model_unload_not_found() {
        let (client, handle) = create_mock_client().await;

        handle.add_response(
            r#"{"type":"ModelUnloadResponse","model_id":"m1","status":"not_found","message":"Not found"}"#,
        );

        let result = client.model_unload("m1").await;
        assert!(result.is_err());
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_connection_lifecycle() {
        let (client, handle) = create_mock_client().await;

        assert!(client.is_connected().await);

        // Inject auth response for auto-auth
        handle.add_response(
            r#"{"type":"AuthResponse","success":true,"session_token":"tok","message":"OK","permissions":[],"session_ttl_seconds":3600}"#,
        );

        // Disconnect
        client.disconnect().await.unwrap();
        assert!(!client.is_connected().await);
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_send_recv_error() {
        let (client, _handle) = create_mock_client().await;
        // Don't inject any response — recv will fail

        let req = InferenceRequest::builder().prompt("Hi").build();
        let result = client.infer(&req).await;
        assert!(result.is_err());
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_builder_creates_client() {
        let client = AinosClient::builder()
            .host("127.0.0.1")
            .port(9500)
            .build();
        assert!(!client.is_connected().await);
        assert_eq!(client.config().host, "127.0.0.1");
        assert_eq!(client.config().port, 9500);
    }

    #[cfg(feature = "mock")]
    #[tokio::test]
    async fn test_permissions() {
        let (client, handle) = create_mock_client().await;

        handle.add_response(
            r#"{"type":"AuthResponse","success":true,"session_token":"tok","message":"OK","permissions":["infer","status"],"session_ttl_seconds":3600}"#,
        );

        client.authenticate("test-token").await.unwrap();
        let perms = client.permissions().await;
        assert!(perms.contains(&"infer".to_string()));
        assert!(perms.contains(&"status".to_string()));
    }
}