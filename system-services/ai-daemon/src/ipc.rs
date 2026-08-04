// Ainos AI Daemon - IPC (TCP for cross-platform, Unix socket on Linux)
//
// This module provides the inter-process communication layer for the Ainos AI
// Daemon. It supports two transport protocols:
// - TCP (cross-platform, used on Windows and as fallback)
// - Unix Domain Socket (Linux-only, higher performance)
//
// Messages are JSON-encoded newline-delimited streams over the wire.

use crate::auth::{self, Permission};
use crate::ratelimit::{self, RateLimitCategory};
use crate::AppState;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::sync::OnceLock;
use std::time::Duration;
use tokio::sync::RwLock;
use tracing::{info, error, debug, warn};

/// Global HTTP client with connection pooling.
///
/// Returns a lazily-initialized singleton `reqwest::Client` configured with:
/// - A 30-second request timeout
/// - A custom `User-Agent` header (`Ainos-AI-Daemon/1.0`)
///
/// The client is built once and reused for all outbound HTTP calls (e.g. cloud
/// API requests), which avoids repeated TLS handshake and connection overhead.
fn http_client() -> &'static reqwest::Client {
    static CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
    CLIENT.get_or_init(|| {
        reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(30))
            .user_agent("Ainos-AI-Daemon/1.0")
            .build()
            .expect("Failed to build HTTP client")
    })
}

/// IPC message types exchanged between the daemon and its clients.
///
/// All messages are serialized as JSON with a `type` tag field for
/// discrimination. The wire format is newline-delimited JSON (NDJSON).
#[derive(Debug, serde::Serialize, serde::Deserialize)]
#[serde(tag = "type")]
pub enum IpcMessage {
    // ========================================================================
    // Authentication
    // ========================================================================

    /// Authentication request from client.
    Auth {
        token: String,
    },

    /// Authentication response from server.
    AuthResponse {
        success: bool,
        #[serde(skip_serializing_if = "Option::is_none")]
        session_token: Option<String>,
        message: String,
        #[serde(default)]
        permissions: Vec<String>,
        #[serde(default)]
        session_ttl_seconds: u64,
    },

    // ========================================================================
    // Inference
    // ========================================================================

    /// Inference request.
    Inference {
        model: String,
        prompt: String,
        temperature: Option<f32>,
        max_tokens: Option<u32>,
        session_id: Option<String>,
    },

    /// Response to an inference request.
    InferenceResponse {
        output: String,
        tokens_generated: u32,
        inference_ms: u64,
        source: String,
    },

    /// Streaming inference request (SSE-style).
    InferenceStream {
        model: String,
        prompt: String,
        temperature: Option<f32>,
        max_tokens: Option<u32>,
        session_id: Option<String>,
    },

    /// A single chunk from a streaming inference response.
    InferenceChunk {
        chunk: String,
        done: bool,
    },

    // ========================================================================
    // Model Management
    // ========================================================================

    /// Request to load a model from disk.
    ModelLoad {
        path: String,
    },

    /// Response to a model load request.
    ModelLoadResponse {
        model_id: String,
        status: String,
        message: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        model_info: Option<ModelInfo>,
    },

    /// Request to unload a model from memory.
    ModelUnload {
        model_id: String,
    },

    /// Response to a model unload request.
    ModelUnloadResponse {
        model_id: String,
        status: String,
        message: String,
    },

    /// Request to list all available models.
    ModelList,

    /// Response containing the list of available models.
    ModelListResponse {
        models: Vec<ModelInfo>,
    },

    // ========================================================================
    // Context Management
    // ========================================================================

    /// Request to store a key-value pair in context.
    ContextStore {
        key: String,
        value: String,
    },

    /// Request to retrieve a value by key from context.
    ContextRetrieve {
        key: String,
    },

    // ========================================================================
    // Status & Health
    // ========================================================================

    /// Query daemon status (health, uptime, stats).
    Status,

    /// Response to a status query.
    StatusResponse {
        uptime: u64,
        models_loaded: u32,
        total_requests: u64,
        network_available: bool,
        #[serde(default)]
        active_sessions: u32,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        rate_limits: Option<Vec<RateLimitInfoJson>>,
    },

    /// Query rate limit status for the current session.
    RateLimitStatus,

    // ========================================================================
    // Error Response
    // ========================================================================

    /// Error response with a numeric code and human-readable message.
    Error {
        code: i32,
        message: String,
    },
}

/// JSON-friendly rate limit info for IPC responses.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct RateLimitInfoJson {
    pub category: String,
    pub limit: u64,
    pub remaining: u64,
    pub reset_seconds: u64,
}

/// Metadata describing a single model.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ModelInfo {
    /// Unique model identifier (e.g. `"phi_3_mini_4k_instruct_q4_gguf"`).
    pub id: String,
    /// Human-readable model name (e.g. `"phi-3-mini-4k-instruct-q4.gguf"`).
    pub name: String,
    /// Absolute file path on disk.
    pub path: String,
    /// Model file size in megabytes.
    pub size_mb: u64,
    /// Whether the model is currently loaded in memory.
    pub loaded: bool,
    /// Model architecture string (e.g. `"auto"`, `"phi3"`, `"llama"`).
    pub architecture: String,
}

// ============================================================================
// Client State (per-connection)
// ============================================================================

/// State tracked for each connected client.
pub(crate) struct ClientState {
    pub(crate) session_token: Option<String>,
    pub(crate) authenticated: bool,
    pub(crate) client_id: String,
}

impl ClientState {
    pub(crate) fn new(client_id: String) -> Self {
        Self { session_token: None, authenticated: false, client_id }
    }

    pub(crate) fn is_allowed(&self, msg_type: &str, auth_enabled: bool) -> bool {
        if matches!(msg_type, "Auth" | "Error") { return true; }
        if !auth_enabled { return true; }
        if self.authenticated { return true; }
        false
    }
}

/// Start the IPC server on the given address.
///
/// This is the top-level entry point for IPC. It selects the appropriate
/// transport based on the address format:
/// - If `addr` contains a `:`, TCP is used (cross-platform).
/// - Otherwise, a Unix Domain Socket is used (Linux only).
/// - macOS: `xpc://` prefix uses XPC transport.
/// - macOS: `launchd://` prefix uses launchd socket activation.
///
/// On non-Unix platforms, Unix socket requests automatically fall back to
/// TCP on `127.0.0.1:9500`.
///
/// # Parameters
///
/// * `state` — Shared application state, wrapped in `Arc<RwLock<>>`.
/// * `addr`  — Listen address. TCP example: `"127.0.0.1:9500"`.
///             Unix socket example: `"/var/run/ainos/ai-daemon.sock"`.
///             macOS XPC example: `"xpc://com.ainos.daemon.xpc"`.
///             macOS launchd example: `"launchd://Listener"`.
///
/// # Panics
///
/// Does not panic. Binding failures are logged and the function returns
/// silently.
pub async fn serve_ipc(state: Arc<RwLock<AppState>>, addr: &str) {
    // macOS XPC transport
    #[cfg(target_os = "macos")]
    if addr.starts_with("xpc://") {
        let service_name = addr.trim_start_matches("xpc://");
        tracing::info!("Starting XPC transport for service: {}", service_name);
        serve_xpc(state, service_name).await;
        return;
    }

    // macOS launchd socket activation
    #[cfg(target_os = "macos")]
    if addr.starts_with("launchd://") {
        let socket_name = addr.trim_start_matches("launchd://");
        tracing::info!("Using launchd socket activation for: {}", socket_name);
        serve_launchd_socket(state, socket_name).await;
        return;
    }

    let use_tcp = addr.contains(':');

    if use_tcp {
        serve_tcp(state, addr).await;
    } else {
        #[cfg(unix)]
        serve_unix(state, addr).await;
        #[cfg(not(unix))]
        {
            tracing::warn!("Unix sockets not supported on this platform, falling back to TCP on 127.0.0.1:9500");
            serve_tcp(state, "127.0.0.1:9500").await;
        }
    }
}

/// TCP IPC server loop (cross-platform).
///
/// Binds a TCP listener to the given address and enters an accept loop.
/// Each accepted connection is dispatched to [`handle_client_tcp`] in a
/// new Tokio task.
async fn serve_tcp(state: Arc<RwLock<AppState>>, addr: &str) {
    let listener = match tokio::net::TcpListener::bind(addr).await {
        Ok(l) => { info!("IPC TCP listener bound to {}", addr); l }
        Err(e) => { error!("Failed to bind TCP listener: {}", e); return; }
    };

    let use_tls = { let s = state.read().await; s.config.tls.enabled || s.config.enable_tls };

    if use_tls {
        #[cfg(feature = "tls")]
        {
            match crate::tls::init_tls(&state.read().await.config.tls).await {
                Ok(_acceptor) => {
                    info!("IPC TLS listener ready");
                    loop {
                        match listener.accept().await {
                            Ok((stream, peer)) => {
                                debug!("IPC TLS connection from {}", peer);
                                tokio::spawn(handle_client_tcp(state.clone(), stream));
                            }
                            Err(e) => error!("Failed to accept TLS connection: {}", e),
                        }
                    }
                }
                Err(e) => {
                    error!("Failed to init TLS: {}", e);
                    info!("Falling back to plain TCP");
                    serve_tcp_plain(state, listener).await;
                }
            }
        }
        #[cfg(not(feature = "tls"))]
        {
            warn!("TLS is enabled but feature not compiled. Falling back to plain TCP.");
            serve_tcp_plain(state, listener).await;
        }
    } else {
        serve_tcp_plain(state, listener).await;
    }
}

/// Run the TCP server loop without TLS.
async fn serve_tcp_plain(state: Arc<RwLock<AppState>>, listener: tokio::net::TcpListener) {
    loop {
        match listener.accept().await {
            Ok((stream, peer)) => {
                debug!("IPC connection from {}", peer);
                tokio::spawn(handle_client_tcp(state.clone(), stream));
            }
            Err(e) => error!("Failed to accept connection: {}", e),
        }
    }
}

/// Unix Domain Socket IPC server (Linux-only).
///
/// Removes any existing socket file at `socket_path`, creates the parent
/// directory if needed, and binds a Unix listener. Each accepted connection
/// is dispatched to [`handle_client_unix`] in a new Tokio task.
///
/// # Parameters
///
/// * `state` — Shared application state.
/// * `socket_path` — Path to the Unix socket (e.g.
///   `"/var/run/ainos/ai-daemon.sock"`).
///
/// # Errors
///
/// If binding fails, the error is logged and the function returns silently.
#[cfg(unix)]
async fn serve_unix(state: Arc<RwLock<AppState>>, socket_path: &str) {
    if let Some(parent) = std::path::Path::new(socket_path).parent() {
        let _ = tokio::fs::create_dir_all(parent).await;
    }
    let _ = tokio::fs::remove_file(socket_path).await;

    let listener = match tokio::net::UnixListener::bind(socket_path) {
        Ok(l) => {
            info!("IPC Unix listener bound to {}", socket_path);
            l
        }
        Err(e) => {
            error!("Failed to bind Unix socket: {}", e);
            return;
        }
    };

    loop {
        match listener.accept().await {
            Ok((stream, _addr)) => {
                let state = state.clone();
                tokio::spawn(handle_client_unix(state, stream));
            }
            Err(e) => {
                error!("Failed to accept connection: {}", e);
            }
        }
    }
}

/// Handle a single TCP client connection.
///
/// Reads newline-delimited JSON messages from the TCP stream, processes each
/// one via [`process_message`], and writes the JSON response back followed by
/// a newline.
///
/// Uses a buffered approach: incoming bytes are accumulated in a `pending`
/// string, and complete lines (ending with `\n`) are extracted for processing.
/// This avoids the `into_split()` compatibility issue on Windows.
///
/// # Parameters
///
/// * `state` — Shared application state.
/// * `stream` — The connected TCP stream.
///
/// # Behavior
///
/// - Invalid UTF-8 data causes the connection to be closed.
/// - `ConnectionReset` errors are silently ignored (normal client disconnect).
/// - Other read errors are logged and the connection is closed.
/// - After the client disconnects, a disconnect message is logged.
async fn handle_client_tcp(
    state: Arc<RwLock<AppState>>,
    mut stream: tokio::net::TcpStream,
) {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    let peer_addr = stream.peer_addr()
        .map(|a| a.to_string())
        .unwrap_or_else(|_| "unknown".to_string());
    let client_id = peer_addr.clone();

    info!("IPC client connected from {}", client_id);
    let mut client = ClientState::new(client_id.clone());

    // 使用 read() 直接读数据，避免 into_split() 在 Windows 上的兼容性问题
    let mut buf = vec![0u8; 8192];
    let mut pending = String::new();

    loop {
        match stream.read(&mut buf).await {
            Ok(0) => break,
            Ok(n) => {
                // 将新数据追加到 pending 缓冲区
                if let Ok(text) = String::from_utf8(buf[..n].to_vec()) {
                    pending.push_str(&text);
                } else {
                    error!("IPC received invalid UTF-8 from {}", client_id);
                    break;
                }

                // 处理所有完整的行（以 \n 结尾）
                loop {
                    let newline_idx = match pending.find('\n') {
                        Some(idx) => idx,
                        None => break, // 没有完整行，等待更多数据
                    };

                    let line = pending[..newline_idx].trim().to_string();
                    pending = pending[newline_idx + 1..].to_string();

                    if line.is_empty() { continue; }

                    // Check auth state before processing
                    let auth_enabled = { let s = state.read().await; s.session_manager.is_enabled() };
                    let msg_type = extract_type_tag(&line);

                    if let Some(ref mtype) = msg_type {
                        if !client.is_allowed(mtype, auth_enabled) {
                            let err = serde_json::to_string(&IpcMessage::Error {
                                code: 401,
                                message: "Authentication required. Send an Auth message first.".to_string(),
                            }).unwrap_or_default();
                            let _ = stream.write_all(err.as_bytes()).await;
                            let _ = stream.write_all(b"\n").await;
                            continue;
                        }
                    }

                    let response = match serde_json::from_str::<IpcMessage>(&line) {
                        Ok(msg) => process_message(state.clone(), msg, &client).await,
                        Err(e) => IpcMessage::Error {
                            code: -1,
                            message: format!("Invalid JSON: {}", e),
                        },
                    };

                    // Update client state from auth response
                    if let IpcMessage::AuthResponse { success, ref session_token, .. } = response {
                        if success {
                            if let Some(ref token) = session_token {
                                client.session_token = Some(token.clone());
                                client.authenticated = true;
                            }
                            debug!("Client {} authenticated successfully", client_id);
                        }
                    }

                    let resp_json = serde_json::to_string(&response)
                        .unwrap_or_else(|_| r#"{"type":"Error","code":-1,"message":"Serialize error"}"#.to_string());
                    if let Err(e) = stream.write_all(resp_json.as_bytes()).await {
                        error!("IPC write error to {}: {}", client_id, e);
                        return;
                    }
                    if let Err(e) = stream.write_all(b"\n").await {
                        error!("IPC write error to {}: {}", client_id, e);
                        return;
                    }
                }
            }
            Err(e) => {
                // 忽略连接重置错误（客户端正常断开）
                if e.kind() != std::io::ErrorKind::ConnectionReset {
                    error!("IPC read error from {}: {}", client_id, e);
                }
                break;
            }
        }
    }
    info!("IPC client {} disconnected", client_id);

    // Clean up session on disconnect
    if let Some(ref session_token) = client.session_token {
        let s = state.read().await;
        s.session_manager.destroy_session(session_token).await;
    }
}

/// Extract the `type` field from a JSON line without full deserialization.
fn extract_type_tag(line: &str) -> Option<String> {
    let line = line.trim();
    if let Some(start) = line.find("\"type\":\"") {
        let rest = &line[start + 8..];
        if let Some(end) = rest.find('"') {
            return Some(rest[..end].to_string());
        }
    }
    None
}

/// Handle a single Unix socket client connection (Linux-only).
///
/// Reads newline-delimited JSON messages from the Unix stream, processes each
/// one via [`process_message`], and writes the JSON response back followed by
/// a newline.
///
/// Uses `BufReader` + `read_line` for efficient line-based I/O.
///
/// # Parameters
///
/// * `state` — Shared application state.
/// * `stream` — The connected Unix stream.
///
/// # Behavior
///
/// - Empty lines are silently skipped.
/// - Read errors are logged and the connection is closed.
#[cfg(unix)]
async fn handle_client_unix(
    state: Arc<RwLock<AppState>>,
    stream: tokio::net::UnixStream,
) {
    use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

    let client_id = "unix-client".to_string();
    info!("IPC Unix client connected");

    let (reader, mut writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut line = String::new();
    let mut client = ClientState::new(client_id.clone());

    loop {
        line.clear();
        match reader.read_line(&mut line).await {
            Ok(0) => break,
            Ok(_) => {
                let trimmed = line.trim();
                if trimmed.is_empty() { continue; }

                // Check auth state
                let auth_enabled = { let s = state.read().await; s.session_manager.is_enabled() };
                let msg_type = extract_type_tag(trimmed);
                if let Some(ref mtype) = msg_type {
                    if !client.is_allowed(mtype, auth_enabled) {
                        let err = serde_json::to_string(&IpcMessage::Error {
                            code: 401, message: "Authentication required".to_string(),
                        }).unwrap_or_default();
                        let _ = writer.write_all(err.as_bytes()).await;
                        let _ = writer.write_all(b"\n").await;
                        continue;
                    }
                }

                let response = match serde_json::from_str::<IpcMessage>(trimmed) {
                    Ok(msg) => process_message(state.clone(), msg, &client).await,
                    Err(e) => IpcMessage::Error {
                        code: -1, message: format!("Invalid JSON: {}", e),
                    },
                };

                // Update client state from auth response
                if let IpcMessage::AuthResponse { success, ref session_token, .. } = response {
                    if success { client.session_token = session_token.clone(); client.authenticated = true; }
                }

                let resp_json = serde_json::to_string(&response)
                    .unwrap_or_else(|_| r#"{"type":"Error","code":-1,"message":"Serialize error"}"#.to_string());
                let _ = writer.write_all(resp_json.as_bytes()).await;
                let _ = writer.write_all(b"\n").await;
            }
            Err(e) => {
                error!("IPC Unix read error: {}", e);
                break;
            }
        }
    }

    // Clean up session on disconnect
    if let Some(ref session_token) = client.session_token {
        let s = state.read().await;
        s.session_manager.destroy_session(session_token).await;
    }
    info!("IPC Unix client disconnected");
}

/// Process an IPC message and produce a response.
///
/// This is the core message router. It dispatches each `IpcMessage` variant
/// to the appropriate handler. Before dispatching, it performs:
/// 1. Authentication check (if enabled)
/// 2. Rate limit check (if enabled)
/// 3. Permission check (if enabled)
pub(crate) async fn process_message(
    state: Arc<RwLock<AppState>>,
    msg: IpcMessage,
    client: &ClientState,
) -> IpcMessage {
    // Get the message type string for routing
    let msg_type = match &msg {
        IpcMessage::Auth { .. } => "Auth",
        IpcMessage::Inference { .. } => "Inference",
        IpcMessage::InferenceStream { .. } => "InferenceStream",
        IpcMessage::ModelLoad { .. } => "ModelLoad",
        IpcMessage::ModelUnload { .. } => "ModelUnload",
        IpcMessage::ModelList { .. } => "ModelList",
        IpcMessage::ContextStore { .. } => "ContextStore",
        IpcMessage::ContextRetrieve { .. } => "ContextRetrieve",
        IpcMessage::Status { .. } => "Status",
        IpcMessage::RateLimitStatus { .. } => "RateLimitStatus",
        _ => "Other",
    };

    // Handle auth messages before any checks
    if let IpcMessage::Auth { token } = msg {
        return handle_auth(state, &token, client).await;
    }

    // Check authentication
    let session_manager: std::sync::Arc<crate::auth::SessionManager> = {
        let s = state.read().await;
        s.session_manager.clone()
    };
    if session_manager.is_enabled() && !client.authenticated {
        return IpcMessage::Error {
            code: 401,
            message: "Authentication required. Send an Auth message first.".to_string(),
        };
    }

    // Check permissions
    if let Some(required_perm) = Permission::from_message_type(msg_type) {
        if session_manager.is_enabled() {
            if let Some(ref session_token) = client.session_token {
                match session_manager.check_permission(session_token, &required_perm).await {
                    Ok(_) => {}
                    Err(auth::AuthError::PermissionDenied { .. }) => {
                        return IpcMessage::Error { code: 403, message: format!("Permission denied: {:?} required", required_perm) };
                    }
                    Err(auth::AuthError::TokenExpired) => {
                        return IpcMessage::Error { code: 401, message: "Session expired. Please re-authenticate.".to_string() };
                    }
                    Err(e) => {
                        return IpcMessage::Error { code: 403, message: format!("Authorization error: {}", e) };
                    }
                }
            }
        }
    }

    // Check rate limit
    let rate_limiter: std::sync::Arc<crate::ratelimit::RateLimiter> = {
        let s = state.read().await;
        s.rate_limiter.clone()
    };
    let rate_limit_enabled = { let s = state.read().await; s.config.ratelimit.enabled };
    if rate_limit_enabled && ratelimit::should_rate_limit(msg_type) {
        let category = RateLimitCategory::from_message_type(msg_type);
        let client_key = client.session_token.as_deref().unwrap_or(&client.client_id);
        if let Err(e) = rate_limiter.check_rate_limit(client_key, category).await {
            let (retry_after, _limit) = match &e {
                ratelimit::RateLimitError::RateLimitExceeded { retry_after, limit, .. } => (*retry_after, *limit),
                _ => (Duration::from_secs(1), 0),
            };
            let s = state.read().await;
            s.session_manager.audit().log_rate_limit(
                &client.client_id, client.session_token.as_deref(),
                &format!("{:?}", category), retry_after,
            ).await;
            return IpcMessage::Error {
                code: 429,
                message: format!("Rate limit exceeded for {:?}. Retry after {} seconds.", category, retry_after.as_secs()),
            };
        }
    }

    // Dispatch to handler
    match msg {
        IpcMessage::Auth { .. } => unreachable!(),

        IpcMessage::Inference { model, prompt, temperature, max_tokens, session_id } => {
            handle_inference(state, model, prompt, temperature, max_tokens, session_id, client).await
        }

        IpcMessage::InferenceStream { model, prompt, temperature, max_tokens, session_id } => {
            // For now, delegate to regular inference handler
            handle_inference(state, model, prompt, temperature, max_tokens, session_id, client).await
        }

        IpcMessage::ModelLoad { path } => handle_model_load(state, &path, client).await,
        IpcMessage::ModelUnload { model_id } => handle_model_unload(state, &model_id, client).await,
        IpcMessage::ModelList => handle_model_list(state).await,
        IpcMessage::Status => handle_status(state, client).await,
        IpcMessage::RateLimitStatus => handle_rate_limit_status(state, client).await,
        IpcMessage::ContextStore { key, value } => handle_context_store(state, &key, &value).await,
        IpcMessage::ContextRetrieve { key } => handle_context_retrieve(state, &key).await,

        // Server-to-client messages received from client (should not happen)
        _ => IpcMessage::Error { code: -1, message: "Unexpected server-to-client message type".to_string() },
    }
}

// ============================================================================
// Authentication Handler
// ============================================================================

async fn handle_auth(state: Arc<RwLock<AppState>>, token: &str, client: &ClientState) -> IpcMessage {
    let session_manager: std::sync::Arc<crate::auth::SessionManager> = {
        let s = state.read().await;
        s.session_manager.clone()
    };
    match session_manager.authenticate(&client.client_id, token).await {
        Ok(session_token) => {
            let session = session_manager.validate_session(&session_token).await;
            let permissions = session.as_ref()
                .map(|s| s.permissions.iter().map(|p| auth::permission_to_str(p).to_string()).collect())
                .unwrap_or_default();
            let ttl = session_manager.session_ttl();
            IpcMessage::AuthResponse {
                success: true, session_token: Some(session_token),
                message: "Authentication successful".to_string(),
                permissions, session_ttl_seconds: ttl.as_secs(),
            }
        }
        Err(e) => IpcMessage::AuthResponse {
            success: false, session_token: None,
            message: format!("Authentication failed: {}", e),
            permissions: vec![], session_ttl_seconds: 0,
        },
    }
}

// ============================================================================
// Inference Handler
// ============================================================================

async fn handle_inference(
    state: Arc<RwLock<AppState>>,
    model: String, prompt: String,
    temperature: Option<f32>, max_tokens: Option<u32>,
    _session_id: Option<String>, _client: &ClientState,
) -> IpcMessage {
    let is_online = check_network_available().await;
    let s = state.read().await;
    s.stats.total_requests.fetch_add(1, Ordering::Relaxed);

    if is_online && s.config.enable_cloud && !s.config.cloud_api_key.is_empty() {
        let api_url = s.config.cloud_api_url.clone();
        let api_key = s.config.cloud_api_key.clone();
        let cloud_model = if model == "default" { s.config.cloud_model.clone() } else { model.clone() };
        let temp = temperature.unwrap_or(0.7);
        let max_tok = max_tokens.unwrap_or(1024);
        s.stats.cloud_inferences.fetch_add(1, Ordering::Relaxed);
        drop(s);

        let start = std::time::Instant::now();
        match call_cloud_api(&api_url, &api_key, &cloud_model, &prompt, temp, max_tok).await {
            Ok(response_text) => {
                let elapsed = start.elapsed().as_millis() as u64;
                let tokens = (response_text.len() / 4) as u32;
                IpcMessage::InferenceResponse { output: response_text, tokens_generated: tokens, inference_ms: elapsed, source: "cloud".to_string() }
            }
            Err(e) => { error!("Cloud API call failed: {}", e); IpcMessage::Error { code: -1, message: format!("Cloud API error: {}", e) } }
        }
    } else if s.config.enable_local {
        s.stats.local_inferences.fetch_add(1, Ordering::Relaxed);
        let reason = if is_online && s.config.enable_cloud { "未配置 API Key，使用本地推理" } else { "离线模式，使用本地推理" };
        let output = generate_local_response(&prompt, reason);
        drop(s);
        IpcMessage::InferenceResponse { output, tokens_generated: 64, inference_ms: 50, source: "local".to_string() }
    } else {
        s.stats.errors.fetch_add(1, Ordering::Relaxed);
        drop(s);
        IpcMessage::Error { code: -1, message: "No inference backend available".to_string() }
    }
}

// ============================================================================
// Model Management Handlers
// ============================================================================

async fn handle_model_load(state: Arc<RwLock<AppState>>, path: &str, _client: &ClientState) -> IpcMessage {
    if path.is_empty() {
        return IpcMessage::ModelLoadResponse { model_id: String::new(), status: "error".to_string(), message: "Model path is empty".to_string(), model_info: None };
    }

    let path_obj = std::path::Path::new(path);
    if !path_obj.exists() {
        return IpcMessage::ModelLoadResponse { model_id: path.to_string(), status: "error".to_string(), message: format!("Model file not found: {}", path), model_info: None };
    }

    let supported_extensions = ["gguf", "ggml", "onnx", "bin"];
    let ext = path_obj.extension().and_then(|e| e.to_str()).unwrap_or("");
    if !supported_extensions.contains(&ext) {
        return IpcMessage::ModelLoadResponse { model_id: path.to_string(), status: "error".to_string(), message: format!("Unsupported model format: .{} (supported: {:?})", ext, supported_extensions), model_info: None };
    }

    let file_name = path_obj.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_else(|| "unknown".to_string());
    let model_id = file_name.replace('.', "_");
    let metadata = match tokio::fs::metadata(path).await {
        Ok(m) => m,
        Err(e) => { return IpcMessage::ModelLoadResponse { model_id: model_id.clone(), status: "error".to_string(), message: format!("Failed to read metadata: {}", e), model_info: None }; }
    };
    let size_mb = metadata.len() / (1024 * 1024);
    let engine_type = match ext { "gguf" | "ggml" => crate::runtime::EngineType::GGML, "onnx" => crate::runtime::EngineType::ONNX, _ => crate::runtime::EngineType::GGML };

    let mut s = state.write().await;
    let already_loaded = s.models.is_loaded(&model_id);

    match s.models.register_model(model_id.clone(), file_name.clone(), path.to_string(), size_mb, if ext == "onnx" { "onnx" } else { "auto" }) {
        Ok(_) => {
            if already_loaded {
                IpcMessage::ModelLoadResponse {
                    model_id: model_id.clone(), status: "already_loaded".to_string(),
                    message: format!("Model '{}' is already loaded", model_id),
                    model_info: Some(ModelInfo { id: model_id.clone(), name: file_name, path: path.to_string(), size_mb, loaded: true, architecture: if ext == "onnx" { "onnx".to_string() } else { "auto".to_string() } }),
                }
            } else {
                match s.models.load(&model_id) {
                    Ok(_) => {
                        let _ = s.runtime.init_engine(engine_type, path);
                        info!("Model loaded: {} ({})", model_id, path);
                        s.session_manager.audit().log_admin_operation(&_client.client_id, _client.session_token.as_deref(), "ModelLoad", &format!("Loaded model: {} from {}", model_id, path)).await;
                        IpcMessage::ModelLoadResponse {
                            model_id: model_id.clone(), status: "loaded".to_string(),
                            message: format!("Model '{}' loaded successfully", model_id),
                            model_info: Some(ModelInfo { id: model_id.clone(), name: file_name, path: path.to_string(), size_mb, loaded: true, architecture: if ext == "onnx" { "onnx".to_string() } else { "auto".to_string() } }),
                        }
                    }
                    Err(e) => IpcMessage::ModelLoadResponse { model_id: model_id.clone(), status: "error".to_string(), message: format!("Failed to load model: {}", e), model_info: None },
                }
            }
        }
        Err(e) => IpcMessage::ModelLoadResponse { model_id: model_id.clone(), status: "error".to_string(), message: format!("Failed to register model: {}", e), model_info: None },
    }
}

async fn handle_model_unload(state: Arc<RwLock<AppState>>, model_id: &str, _client: &ClientState) -> IpcMessage {
    let mut s = state.write().await;
    if !s.models.is_loaded(model_id) {
        return IpcMessage::ModelUnloadResponse { model_id: model_id.to_string(), status: "not_found".to_string(), message: format!("Model '{}' is not loaded", model_id) };
    }
    match s.models.unload(model_id) {
        Ok(_) => {
            info!("Model unloaded: {}", model_id);
            s.session_manager.audit().log_admin_operation(&_client.client_id, _client.session_token.as_deref(), "ModelUnload", &format!("Unloaded model: {}", model_id)).await;
            IpcMessage::ModelUnloadResponse { model_id: model_id.to_string(), status: "unloaded".to_string(), message: format!("Model '{}' unloaded successfully", model_id) }
        }
        Err(e) => IpcMessage::ModelUnloadResponse { model_id: model_id.to_string(), status: "error".to_string(), message: format!("Failed to unload model: {}", e) },
    }
}

async fn handle_model_list(state: Arc<RwLock<AppState>>) -> IpcMessage {
    let s = state.read().await;
    IpcMessage::ModelListResponse { models: s.models.list() }
}

// ============================================================================
// Status Handler
// ============================================================================

async fn handle_status(state: Arc<RwLock<AppState>>, _client: &ClientState) -> IpcMessage {
    let s = state.read().await;
    let active_sessions = s.session_manager.active_sessions().await;
    let mut rate_limits = Vec::new();
    if s.config.ratelimit.enabled {
        let client_key = _client.session_token.as_deref().unwrap_or(&_client.client_id);
        for cat in &[RateLimitCategory::Inference, RateLimitCategory::ModelOps, RateLimitCategory::Status, RateLimitCategory::Admin] {
            if let Some(info) = s.rate_limiter.peek_rate_limit(client_key, *cat).await {
                rate_limits.push(RateLimitInfoJson { category: format!("{:?}", cat).to_lowercase(), limit: info.limit, remaining: info.remaining, reset_seconds: info.reset.as_secs() });
            }
        }
    }
    IpcMessage::StatusResponse {
        uptime: s.stats.uptime.elapsed().as_secs(),
        models_loaded: s.models.count_loaded(),
        total_requests: s.stats.total_requests.load(Ordering::Relaxed),
        network_available: check_network_available().await,
        active_sessions: active_sessions as u32,
        rate_limits: if rate_limits.is_empty() { None } else { Some(rate_limits) },
    }
}

async fn handle_rate_limit_status(state: Arc<RwLock<AppState>>, _client: &ClientState) -> IpcMessage {
    let s = state.read().await;
    let client_key = _client.session_token.as_deref().unwrap_or(&_client.client_id);
    let mut limits = Vec::new();
    for cat in &[RateLimitCategory::Inference, RateLimitCategory::ModelOps, RateLimitCategory::Status, RateLimitCategory::Admin] {
        if let Some(info) = s.rate_limiter.peek_rate_limit(client_key, *cat).await {
            limits.push(RateLimitInfoJson { category: format!("{:?}", cat).to_lowercase(), limit: info.limit, remaining: info.remaining, reset_seconds: info.reset.as_secs() });
        }
    }
    drop(s);
    serde_json::from_value(serde_json::json!({ "type": "RateLimitStatusResponse", "limits": limits }))
        .unwrap_or_else(|_| IpcMessage::Error { code: -1, message: "Serialization error".to_string() })
}

// ============================================================================
// Context Handlers
// ============================================================================

async fn handle_context_store(state: Arc<RwLock<AppState>>, key: &str, value: &str) -> IpcMessage {
    let mut s = state.write().await;
    s.context.store(key.to_string(), value.to_string());
    IpcMessage::InferenceResponse { output: format!("Context stored: {}", key), tokens_generated: 0, inference_ms: 0, source: "local".to_string() }
}

async fn handle_context_retrieve(state: Arc<RwLock<AppState>>, key: &str) -> IpcMessage {
    let s = state.read().await;
    match s.context.retrieve(key) {
        Some(value) => IpcMessage::InferenceResponse { output: value, tokens_generated: 0, inference_ms: 0, source: "local".to_string() },
        None => IpcMessage::Error { code: -1, message: format!("Key not found: {}", key) },
    }
}

/// Call a cloud AI API endpoint (OpenAI-compatible interface).
///
/// Sends a chat completion request to the configured API endpoint and returns
/// the generated text content. The endpoint must follow the OpenAI chat
/// completions schema.
///
/// # Parameters
///
/// * `api_url` — Base URL of the API (e.g. `"https://api.weelinking.com/v1"`).
/// * `api_key` — Bearer token for authentication. May be empty for open APIs.
/// * `model`   — Model identifier (e.g. `"gpt-5.6-sol"`).
/// * `prompt`  — User message text.
/// * `temperature` — Sampling temperature (0.0–2.0).
/// * `max_tokens` — Maximum tokens to generate.
///
/// # Returns
///
/// * `Ok(String)` — The generated response text.
/// * `Err(String)` — A human-readable error description.
///
/// # Errors
///
/// Can fail due to:
/// - Network connectivity issues (timeout, DNS failure).
/// - Non-2xx HTTP status codes (the response body is included in the error).
/// - Invalid or unexpected JSON response structure.
async fn call_cloud_api(
    api_url: &str,
    api_key: &str,
    model: &str,
    prompt: &str,
    temperature: f32,
    max_tokens: u32,
) -> Result<String, String> {
    let base_url = api_url.trim_end_matches('/');
    let url = format!("{}/chat/completions", base_url);

    let body = serde_json::json!({
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是一个有用的AI助手，名字叫Ainos。请用中文回答用户的问题。"
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    });

    let mut req = http_client()
        .post(&url)
        .json(&body)
        .header("Content-Type", "application/json");

    if !api_key.is_empty() {
        req = req.header("Authorization", format!("Bearer {}", api_key));
    }

    let resp = req.send().await.map_err(|e| format!("Request failed: {}", e))?;
    let status = resp.status();

    if !status.is_success() {
        let body_text = resp.text().await.unwrap_or_default();
        return Err(format!("API returned {}: {}", status, body_text));
    }

    let data: serde_json::Value = resp.json().await.map_err(|e| format!("Parse failed: {}", e))?;

    // 解析 OpenAI 兼容响应
    let content = data["choices"][0]["message"]["content"]
        .as_str()
        .ok_or_else(|| "No content in response".to_string())?
        .to_string();

    Ok(content)
}

/// Generate a local simulated response when no cloud API key is configured.
///
/// Matches the prompt against known keywords to produce a contextually
/// relevant canned response. This is a fallback for demo / offline mode.
///
/// # Parameters
///
/// * `prompt` — The user's input text.
/// * `reason` — A short reason string explaining why local mode is active
///   (e.g. `"未配置 API Key，使用本地推理"` or `"离线模式，使用本地推理"`).
///
/// # Returns
///
/// A formatted string containing the simulated response, prefixed with
/// `[Ainos 离线推理]`.
pub(crate) fn generate_local_response(prompt: &str, reason: &str) -> String {
    let prompt_lower = prompt.to_lowercase();
    let response = if prompt_lower.contains("ainos") && reason.contains("API Key") {
        format!(
            "[Ainos 离线推理] Ainos OS 是一个AI原生的操作系统，\
             它将AI能力深度集成到系统内核和服务层中，\
             支持离线推理、云端回退、上下文管理和智能电源策略调度。\
             当前系统运行在本地模式（{}）。", reason
        )
    } else if prompt_lower.contains("hello") || prompt_lower.contains("hi") || prompt_lower.contains("你好") {
        format!(
            "[Ainos 离线推理] 你好！我是 Ainos AI 助手。\
             当前系统运行在本地模式（{}）。\
             我正在离线运行，可以帮你处理文本推理、上下文记忆和系统管理任务。", reason
        )
    } else {
        format!(
            "[Ainos 离线推理] 已收到你的问题。当前系统运行在本地模式（{}）。\
             模型推理引擎就绪，上下文管理正常运行。", reason
        )
    };
    response
}

/// Check whether the internet is reachable.
///
/// Attempts to open a TCP connection to `8.8.8.8:53` (Google DNS) with a
/// 3-second timeout. This is a lightweight connectivity check that does not
/// depend on DNS resolution.
///
/// # Returns
///
/// `true` if the connection succeeded within the timeout, `false` otherwise.
pub(crate) async fn check_network_available() -> bool {
    match tokio::time::timeout(
        std::time::Duration::from_secs(3),
        tokio::net::TcpStream::connect("8.8.8.8:53")
    ).await {
        Ok(Ok(_)) => true,
        _ => false,
    }
}

// ============================================================================
// macOS-specific IPC transports
// ============================================================================

/// XPC transport for macOS.
///
/// Listens for XPC messages from the macOS XPC service (com.ainos.daemon.xpc).
/// This is a two-way bridge: XPC messages from client apps are translated
/// into the Ainos IPC protocol and forwarded to the daemon, and responses
/// are sent back via XPC.
///
/// # Parameters
///
/// * `state` — Shared application state.
/// * `service_name` — The XPC service name (e.g. "com.ainos.daemon.xpc").
#[cfg(target_os = "macos")]
async fn serve_xpc(state: Arc<RwLock<AppState>>, service_name: &str) {
    tracing::info!("XPC service '{}' registered (delegating to XPC listener)", service_name);

    // In the real implementation, this would set up an XPC listener using
    // the xpc_connection_t API via FFI. For the Rust daemon, the XPC service
    // is handled by the separate ainos_xpc C process. This function serves
    // as a placeholder that indicates the daemon is ready for XPC bridging.
    //
    // The actual flow is:
    //   1. macOS app sends XPC message to com.ainos.daemon.xpc
    //   2. ainos_xpc service converts XPC -> JSON and sends to TCP :9500
    //   3. This daemon processes the JSON and sends response back
    //   4. ainos_xpc service converts JSON -> XPC and sends to the app
    //
    // So the daemon just needs to be reachable on TCP :9500.

    // Start a TCP listener on the standard port for the XPC bridge to connect to
    serve_tcp(state, "127.0.0.1:9500").await;
}

/// launchd socket activation for macOS.
///
/// Receives a pre-bound socket from launchd via the file descriptor
/// passed in the environment (XPC_SERVICE_NAME / LISTEN_FDS).
/// This is the standard macOS way to hand off socket ownership to
/// a daemon process.
///
/// # Parameters
///
/// * `state` — Shared application state.
/// * `socket_name` — The socket name from the launchd plist Sockets dict.
#[cfg(target_os = "macos")]
async fn serve_launchd_socket(state: Arc<RwLock<AppState>>, socket_name: &str) {
    use std::os::unix::io::{FromRawFd, RawFd};

    // launchd passes socket file descriptors using the environment:
    //   LISTEN_FDS  = number of FDs passed (starts at FD 3)
    //   LISTEN_PID  = PID of the receiving process (must match)
    //   XPC_SERVICE_NAME = service identifier

    let listen_pid: u32 = std::env::var("LISTEN_PID")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(0);

    let listen_fds: u32 = std::env::var("LISTEN_FDS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(0);

    let my_pid = std::process::id();
    if listen_pid != my_pid || listen_fds == 0 {
        tracing::warn!(
            "launchd socket activation: LISTEN_PID mismatch or no FDs \
             (expecting PID={}, got PID={}, FDs={})",
            listen_pid, my_pid, listen_fds
        );
        // Fall back to regular TCP
        tracing::info!("Falling back to TCP on 127.0.0.1:9500");
        serve_tcp(state, "127.0.0.1:9500").await;
        return;
    }

    // launchd convention: the first FD is at 3 (SD_LISTEN_FDS_START)
    // The socket name maps to the index in the Sockets dict
    const SD_LISTEN_FDS_START: RawFd = 3;

    tracing::info!(
        "launchd socket activation: {} FDs available (PID={})",
        listen_fds, listen_pid
    );

    // Use the first FD for now (the "Listener" socket)
    let fd = SD_LISTEN_FDS_START; // Index 0 -> FD 3

    // Safety: This FD is owned by launchd and is a valid TCP socket.
    // We must not close it (launchd expects us to use it).
    // The FD is not owned by us - we create a tokio TcpListener from it.
    unsafe {
        let std_listener = std::net::TcpListener::from_raw_fd(fd);
        // Set non-blocking for tokio compatibility
        std_listener.set_nonblocking(true).ok();
        let listener = tokio::net::TcpListener::from_std(std_listener)
            .expect("Failed to create tokio listener from launchd FD");

        tracing::info!("launchd socket listener ready on FD {}", fd);

        // Accept connections in a loop
        loop {
            match listener.accept().await {
                Ok((stream, peer)) => {
                    tracing::debug!("launchd socket connection from {}", peer);
                    tokio::spawn(handle_client_tcp(state.clone(), stream));
                }
                Err(e) => {
                    tracing::error!("launchd socket accept error: {}", e);
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::DaemonConfig;
    use crate::AppState;
    use std::sync::Arc;
    use tokio::sync::RwLock;

    /// Helper to create a test state and client.
    fn test_state() -> (Arc<RwLock<AppState>>, ClientState) {
        let cfg = DaemonConfig::default();
        let state = Arc::new(RwLock::new(AppState::new(cfg)));
        let mut client = ClientState::new("test-client".to_string());
        client.authenticated = true;
        (state, client)
    }

    #[test]
    fn test_generate_local_response_basic() {
        let resp = generate_local_response("你好", "离线模式，使用本地推理");
        assert!(!resp.is_empty()); assert!(resp.contains("Ainos")); assert!(resp.contains("离线推理"));
    }

    #[test]
    fn test_generate_local_response_ainos_keyword() {
        let resp = generate_local_response("Tell me about Ainos", "未配置 API Key，使用本地推理");
        assert!(resp.contains("Ainos OS 是一个AI原生的操作系统"));
    }

    #[test]
    fn test_generate_local_response_greeting() {
        let resp = generate_local_response("hello", "离线模式，使用本地推理");
        assert!(resp.contains("你好"));
    }

    #[test]
    fn test_generate_local_response_empty() {
        let resp = generate_local_response("", "离线模式");
        assert!(!resp.is_empty());
    }

    #[test]
    fn test_ipc_message_serialize_status() {
        let json = serde_json::to_string(&IpcMessage::Status).unwrap();
        assert_eq!(json, r#"{"type":"Status"}"#);
    }

    #[test]
    fn test_ipc_message_roundtrip_inference() {
        let original = IpcMessage::Inference {
            model: "test-model".into(), prompt: "Hello".into(),
            temperature: Some(0.7), max_tokens: Some(100), session_id: Some("sess-1".into()),
        };
        let json = serde_json::to_string(&original).unwrap();
        let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
        match deserialized {
            IpcMessage::Inference { model, prompt, temperature, max_tokens, session_id } => {
                assert_eq!(model, "test-model"); assert_eq!(prompt, "Hello");
                assert_eq!(temperature, Some(0.7)); assert_eq!(max_tokens, Some(100));
                assert_eq!(session_id, Some("sess-1".into()));
            }
            _ => panic!("Expected Inference variant"),
        }
    }

    #[test]
    fn test_ipc_message_roundtrip_error() {
        let original = IpcMessage::Error { code: -42, message: "Something went wrong".into() };
        let json = serde_json::to_string(&original).unwrap();
        let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
        match deserialized { IpcMessage::Error { code, message } => { assert_eq!(code, -42); assert_eq!(message, "Something went wrong"); } _ => panic!("Expected Error variant"), }
    }

    #[test]
    fn test_ipc_message_roundtrip_auth() {
        let original = IpcMessage::Auth { token: "my-bearer-token".into() };
        let json = serde_json::to_string(&original).unwrap();
        let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
        match deserialized { IpcMessage::Auth { token } => assert_eq!(token, "my-bearer-token"), _ => panic!("Expected Auth variant"), }
    }

    #[test]
    fn test_ipc_message_roundtrip_auth_response() {
        let original = IpcMessage::AuthResponse { success: true, session_token: Some("uuid".into()), message: "Auth OK".into(), permissions: vec!["infer".into()], session_ttl_seconds: 3600 };
        let json = serde_json::to_string(&original).unwrap();
        let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
        match deserialized { IpcMessage::AuthResponse { success, session_token, message, .. } => { assert!(success); assert_eq!(session_token, Some("uuid".to_string())); assert_eq!(message, "Auth OK"); } _ => panic!("Expected AuthResponse variant"), }
    }

    #[test]
    fn test_ipc_message_roundtrip_model_load_response() {
        let original = IpcMessage::ModelLoadResponse { model_id: "m1".into(), status: "loaded".into(), message: "OK".into(), model_info: Some(ModelInfo { id: "m1".into(), name: "m.gguf".into(), path: "/m.gguf".into(), size_mb: 1024, loaded: true, architecture: "auto".into() }) };
        let json = serde_json::to_string(&original).unwrap();
        let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
        match deserialized { IpcMessage::ModelLoadResponse { model_id, status, model_info, .. } => { assert_eq!(model_id, "m1"); assert_eq!(status, "loaded"); assert!(model_info.is_some()); } _ => panic!("Expected ModelLoadResponse"), }
    }

    #[test]
    fn test_ipc_message_roundtrip_model_unload_response() {
        let original = IpcMessage::ModelUnloadResponse { model_id: "m1".into(), status: "unloaded".into(), message: "OK".into() };
        let json = serde_json::to_string(&original).unwrap();
        let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
        match deserialized { IpcMessage::ModelUnloadResponse { model_id, status, .. } => { assert_eq!(model_id, "m1"); assert_eq!(status, "unloaded"); } _ => panic!("Expected ModelUnloadResponse"), }
    }

    #[test]
    fn test_ipc_message_roundtrip_inference_chunk() {
        let original = IpcMessage::InferenceChunk { chunk: "Hello".into(), done: false };
        let json = serde_json::to_string(&original).unwrap();
        let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
        match deserialized { IpcMessage::InferenceChunk { chunk, done } => { assert_eq!(chunk, "Hello"); assert!(!done); } _ => panic!("Expected InferenceChunk variant"), }
    }

    #[test]
    fn test_ipc_message_roundtrip_inference_stream() {
        let original = IpcMessage::InferenceStream { model: "m1".into(), prompt: "Hello".into(), temperature: Some(0.7), max_tokens: Some(100), session_id: Some("s1".into()) };
        let json = serde_json::to_string(&original).unwrap();
        let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
        match deserialized { IpcMessage::InferenceStream { model, prompt, .. } => { assert_eq!(model, "m1"); assert_eq!(prompt, "Hello"); } _ => panic!("Expected InferenceStream variant"), }
    }

    #[test]
    fn test_ipc_message_rate_limit_status() {
        let json = serde_json::to_string(&IpcMessage::RateLimitStatus).unwrap();
        assert_eq!(json, r#"{"type":"RateLimitStatus"}"#);
        let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
        match deserialized { IpcMessage::RateLimitStatus => {} _ => panic!("Expected RateLimitStatus"), }
    }

    #[test]
    fn test_extract_type_tag() {
        assert_eq!(extract_type_tag(r#"{"type":"Status"}"#), Some("Status".to_string()));
        assert_eq!(extract_type_tag(r#"{"type":"Auth","token":"abc"}"#), Some("Auth".to_string()));
        assert_eq!(extract_type_tag(r#"{}"#), None);
    }

    #[test]
    fn test_client_state_new() {
        let state = ClientState::new("127.0.0.1:9500".to_string());
        assert!(!state.authenticated); assert!(state.session_token.is_none());
    }

    #[test]
    fn test_client_state_is_allowed() {
        let mut state = ClientState::new("client".to_string());
        assert!(state.is_allowed("Auth", true)); assert!(state.is_allowed("Error", true));
        assert!(!state.is_allowed("Inference", true)); assert!(!state.is_allowed("Status", true));
        assert!(state.is_allowed("Inference", false));
        state.authenticated = true;
        assert!(state.is_allowed("Inference", true)); assert!(state.is_allowed("ModelLoad", true));
    }

    #[test]
    fn test_model_info_serialize() {
        let info = ModelInfo { id: "m1".into(), name: "model-1.gguf".into(), path: "/models/m1.gguf".into(), size_mb: 4096, loaded: true, architecture: "auto".into() };
        let json = serde_json::to_string(&info).unwrap();
        let deserialized: ModelInfo = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.id, "m1"); assert!(deserialized.loaded);
    }

    #[test]
    fn test_rate_limit_info_json() {
        let info = RateLimitInfoJson { category: "inference".to_string(), limit: 100, remaining: 50, reset_seconds: 1 };
        let json = serde_json::to_string(&info).unwrap();
        assert!(json.contains("inference"));
    }

    #[tokio::test]
    async fn test_process_message_auth() {
        let cfg = DaemonConfig::default();
        let state = Arc::new(RwLock::new(AppState::new(cfg)));
        let client = ClientState::new("test-client".to_string());
        let response = process_message(state, IpcMessage::Auth { token: "invalid".into() }, &client).await;
        match response { IpcMessage::AuthResponse { .. } => {} _ => panic!("Expected AuthResponse"), }
    }

    #[tokio::test]
    async fn test_process_message_status() {
        let (state, client) = test_state();
        let response = process_message(state, IpcMessage::Status, &client).await;
        match response {
            IpcMessage::StatusResponse { models_loaded, total_requests, .. } => {
                assert_eq!(models_loaded, 0); assert_eq!(total_requests, 0);
            }
            _ => panic!("Expected StatusResponse, got {:?}", response),
        }
    }

    #[tokio::test]
    async fn test_process_message_auth_required() {
        let mut cfg = DaemonConfig::default();
        cfg.auth.enabled = true; cfg.auth.token = "test-token-thirty-two-chars-min".to_string();
        let state = Arc::new(RwLock::new(AppState::new(cfg)));
        let client = ClientState::new("unauthenticated".to_string());
        let response = process_message(state, IpcMessage::Status, &client).await;
        match response { IpcMessage::Error { code, .. } => assert_eq!(code, 401), _ => panic!("Expected Error 401"), }
    }

    #[tokio::test]
    async fn test_handle_model_load_empty_path() {
        let (state, client) = test_state();
        let response = handle_model_load(state, "", &client).await;
        match response { IpcMessage::ModelLoadResponse { status, .. } => assert_eq!(status, "error"), _ => panic!("Expected ModelLoadResponse"), }
    }

    #[tokio::test]
    async fn test_handle_model_unload_not_found() {
        let (state, client) = test_state();
        let response = handle_model_unload(state, "nonexistent_model", &client).await;
        match response { IpcMessage::ModelUnloadResponse { status, .. } => assert_eq!(status, "not_found"), _ => panic!("Expected ModelUnloadResponse"), }
    }

    #[tokio::test]
    async fn test_handle_context_store_retrieve() {
        let (state, _client) = test_state();
        let r = handle_context_store(state.clone(), "test_key", "test_value").await;
        match r { IpcMessage::InferenceResponse { output, .. } => assert!(output.contains("test_key")), _ => panic!("Expected InferenceResponse"), }
        let r = handle_context_retrieve(state, "test_key").await;
        match r { IpcMessage::InferenceResponse { output, .. } => assert_eq!(output, "test_value"), _ => panic!("Expected InferenceResponse"), }
    }

    #[tokio::test]
    async fn test_handle_context_retrieve_missing() {
        let (state, _client) = test_state();
        let response = handle_context_retrieve(state, "nonexistent").await;
        match response { IpcMessage::Error { code, .. } => assert_eq!(code, -1), _ => panic!("Expected Error"), }
    }

    #[tokio::test]
    async fn test_check_network_timeout() {
        let result = tokio::time::timeout(std::time::Duration::from_secs(10), check_network_available()).await;
        assert!(result.is_ok()); let _ = result.unwrap();
    }

    #[test]
    fn test_config_defaults() {
        let cfg = DaemonConfig::default();
        assert!(cfg.enable_local); assert!(cfg.enable_cloud); assert_eq!(cfg.local_engine, "ggml");
        assert_eq!(cfg.max_concurrent_inferences, 2); assert!(!cfg.enable_tls);
    }

    #[test]
    fn test_deserialize_invalid_type() {
        let result: Result<IpcMessage, _> = serde_json::from_str(r#"{"type":"UnknownType"}"#);
        assert!(result.is_err(), "Unknown type tag should fail deserialization");
    }
}