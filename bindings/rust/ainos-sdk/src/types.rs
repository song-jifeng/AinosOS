//! Data types for the Ainos IPC protocol.
//!
//! This module defines all message types, request/response structs, and
//! supporting types that are exchanged with the Ainos daemon over the
//! NDJSON wire protocol.  All public types implement [`Serialize`] and
//! [`Deserialize`] and mirror the server-side `IpcMessage` enum.

use serde::{Deserialize, Serialize};

// ---------------------------------------------------------------------------
// Re-exports
// ---------------------------------------------------------------------------

pub use crate::error::{AinosError, Result};

// ===========================================================================
// IPC Messages — mirrored from the daemon's `IpcMessage` enum
// ===========================================================================

/// Top-level IPC message exchanged with the Ainos daemon.
///
/// The `type` tag discriminates the variant during JSON serialization,
/// matching the daemon's `#[serde(tag = "type")]` convention.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
#[allow(missing_docs)]
pub enum IpcMessage {
    // ── Authentication ──────────────────────────────────────────────────────
    /// Authentication request.
    Auth {
        token: String,
    },
    /// Authentication response.
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

    // ── Inference ───────────────────────────────────────────────────────────
    /// Inference request.
    Inference {
        model: String,
        prompt: String,
        temperature: Option<f32>,
        max_tokens: Option<u32>,
        session_id: Option<String>,
    },
    /// Inference response.
    InferenceResponse {
        output: String,
        tokens_generated: u32,
        inference_ms: u64,
        source: String,
    },
    /// Streaming inference request.
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

    // ── Model Management ────────────────────────────────────────────────────
    /// Request to load a model.
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
    /// Request to unload a model.
    ModelUnload {
        model_id: String,
    },
    /// Response to a model unload request.
    ModelUnloadResponse {
        model_id: String,
        status: String,
        message: String,
    },
    /// Request to list all models.
    ModelList,
    /// Response with the model list.
    ModelListResponse {
        models: Vec<ModelInfo>,
    },

    // ── Context Management ──────────────────────────────────────────────────
    /// Store a key-value pair in context.
    ContextStore {
        key: String,
        value: String,
    },
    /// Retrieve a value by key.
    ContextRetrieve {
        key: String,
    },

    // ── Status & Health ─────────────────────────────────────────────────────
    /// Query daemon status.
    Status,
    /// Status response.
    StatusResponse {
        uptime: u64,
        models_loaded: u32,
        total_requests: u64,
        network_available: bool,
        #[serde(default)]
        active_sessions: u32,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        rate_limits: Option<Vec<RateLimitInfo>>,
    },
    /// Query rate limit status.
    RateLimitStatus,

    /// Response containing rate limit information.
    #[serde(rename = "RateLimitStatusResponse")]
    RateLimitStatusResponse {
        limits: Vec<RateLimitInfo>,
    },

    // ── Error ───────────────────────────────────────────────────────────────
    /// Error response from the daemon.
    Error {
        code: i32,
        message: String,
    },
}

// ===========================================================================
// Request / Response types
// ===========================================================================

/// Parameters for an inference request.
///
/// Create one with [`InferenceRequest::builder()`]:
///
/// ```
/// # use ainos_sdk::InferenceRequest;
/// let req = InferenceRequest::builder()
///     .prompt("Hello, world!")
///     .model("phi-3-mini")
///     .temperature(0.7)
///     .max_tokens(512)
///     .build();
/// ```
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InferenceRequest {
    /// The input prompt text.
    pub prompt: String,
    /// Model identifier (default `"default"`).
    #[serde(default = "default_model")]
    pub model: String,
    /// Sampling temperature (0.0–2.0).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub temperature: Option<f32>,
    /// Maximum number of tokens to generate.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_tokens: Option<u32>,
    /// Optional session identifier for context tracking.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub session_id: Option<String>,
}

fn default_model() -> String {
    "default".to_string()
}

impl Default for InferenceRequest {
    fn default() -> Self {
        Self {
            prompt: String::new(),
            model: default_model(),
            temperature: None,
            max_tokens: None,
            session_id: None,
        }
    }
}

impl InferenceRequest {
    /// Create a new [`InferenceRequestBuilder`].
    pub fn builder() -> InferenceRequestBuilder {
        InferenceRequestBuilder::default()
    }

    /// Convert to the wire-format IPC message.
    pub fn to_ipc_message(&self) -> IpcMessage {
        IpcMessage::Inference {
            model: self.model.clone(),
            prompt: self.prompt.clone(),
            temperature: self.temperature,
            max_tokens: self.max_tokens,
            session_id: self.session_id.clone(),
        }
    }

    /// Convert to a streaming wire-format IPC message.
    pub fn to_stream_ipc_message(&self) -> IpcMessage {
        IpcMessage::InferenceStream {
            model: self.model.clone(),
            prompt: self.prompt.clone(),
            temperature: self.temperature,
            max_tokens: self.max_tokens,
            session_id: self.session_id.clone(),
        }
    }
}

/// Builder for [`InferenceRequest`].
#[derive(Debug, Default)]
pub struct InferenceRequestBuilder {
    prompt: Option<String>,
    model: Option<String>,
    temperature: Option<f32>,
    max_tokens: Option<u32>,
    session_id: Option<String>,
}

impl InferenceRequestBuilder {
    /// Set the input prompt (required).
    pub fn prompt(mut self, prompt: impl Into<String>) -> Self {
        self.prompt = Some(prompt.into());
        self
    }

    /// Set the model identifier.
    pub fn model(mut self, model: impl Into<String>) -> Self {
        self.model = Some(model.into());
        self
    }

    /// Set the sampling temperature.
    pub fn temperature(mut self, temperature: f32) -> Self {
        self.temperature = Some(temperature);
        self
    }

    /// Set the maximum number of tokens to generate.
    pub fn max_tokens(mut self, max_tokens: u32) -> Self {
        self.max_tokens = Some(max_tokens);
        self
    }

    /// Set the session identifier.
    pub fn session_id(mut self, session_id: impl Into<String>) -> Self {
        self.session_id = Some(session_id.into());
        self
    }

    /// Build the [`InferenceRequest`].
    ///
    /// # Panics
    ///
    /// Panics if `prompt` was not set.
    pub fn build(self) -> InferenceRequest {
        InferenceRequest {
            prompt: self.prompt.expect("InferenceRequest: prompt is required"),
            model: self.model.unwrap_or_else(default_model),
            temperature: self.temperature,
            max_tokens: self.max_tokens,
            session_id: self.session_id,
        }
    }
}

/// Response from a successful inference request.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InferenceResponse {
    /// The generated output text.
    pub output: String,
    /// Number of tokens generated.
    pub tokens_generated: u32,
    /// Wall-clock inference time in milliseconds.
    pub inference_ms: u64,
    /// Source of the response (`"local"` or `"cloud"`).
    pub source: String,
}

impl InferenceResponse {
    /// Create an `InferenceResponse` from a wire-format `IpcMessage`.
    pub fn from_ipc_message(msg: &IpcMessage) -> Option<Self> {
        if let IpcMessage::InferenceResponse {
            output,
            tokens_generated,
            inference_ms,
            source,
        } = msg
        {
            Some(Self {
                output: output.clone(),
                tokens_generated: *tokens_generated,
                inference_ms: *inference_ms,
                source: source.clone(),
            })
        } else {
            None
        }
    }
}

/// A single chunk from a streaming inference response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InferenceChunk {
    /// The partial text generated so far.
    pub chunk: String,
    /// Whether the stream is complete.
    pub done: bool,
}

impl InferenceChunk {
    /// Create an `InferenceChunk` from a wire-format `IpcMessage`.
    pub fn from_ipc_message(msg: &IpcMessage) -> Option<Self> {
        if let IpcMessage::InferenceChunk { chunk, done } = msg {
            Some(Self {
                chunk: chunk.clone(),
                done: *done,
            })
        } else {
            None
        }
    }
}

/// Metadata describing a single registered model.
#[derive(Debug, Clone, Serialize, Deserialize)]
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

/// Options for loading a model.
///
/// Create with [`ModelLoadOptions::builder()`]:
///
/// ```
/// # use ainos_sdk::ModelLoadOptions;
/// let opts = ModelLoadOptions::builder()
///     .path("/models/test.gguf")
///     .model_type("ggml")
///     .gpu_layers(32)
///     .build();
/// ```
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelLoadOptions {
    /// The path to the model file on disk.
    pub path: String,
    /// Model type hint (e.g. `"ggml"`, `"gguf"`, `"onnx"`).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub model_type: Option<String>,
    /// Number of layers to offload to GPU (if supported).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub gpu_layers: Option<u32>,
    /// Context size in tokens.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub context_size: Option<u32>,
    /// Whether to use memory mapping.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub use_mmap: Option<bool>,
}

impl ModelLoadOptions {
    /// Create a new [`ModelLoadOptionsBuilder`].
    pub fn builder() -> ModelLoadOptionsBuilder {
        ModelLoadOptionsBuilder::default()
    }
}

/// Builder for [`ModelLoadOptions`].
#[derive(Debug, Default)]
pub struct ModelLoadOptionsBuilder {
    path: Option<String>,
    model_type: Option<String>,
    gpu_layers: Option<u32>,
    context_size: Option<u32>,
    use_mmap: Option<bool>,
}

impl ModelLoadOptionsBuilder {
    /// Set the model file path (required).
    pub fn path(mut self, path: impl Into<String>) -> Self {
        self.path = Some(path.into());
        self
    }

    /// Set the model type.
    pub fn model_type(mut self, model_type: impl Into<String>) -> Self {
        self.model_type = Some(model_type.into());
        self
    }

    /// Set the number of GPU layers.
    pub fn gpu_layers(mut self, gpu_layers: u32) -> Self {
        self.gpu_layers = Some(gpu_layers);
        self
    }

    /// Set the context size.
    pub fn context_size(mut self, context_size: u32) -> Self {
        self.context_size = Some(context_size);
        self
    }

    /// Set whether to use memory mapping.
    pub fn use_mmap(mut self, use_mmap: bool) -> Self {
        self.use_mmap = Some(use_mmap);
        self
    }

    /// Build the [`ModelLoadOptions`].
    ///
    /// # Panics
    ///
    /// Panics if `path` was not set.
    pub fn build(self) -> ModelLoadOptions {
        ModelLoadOptions {
            path: self.path.expect("ModelLoadOptions: path is required"),
            model_type: self.model_type,
            gpu_layers: self.gpu_layers,
            context_size: self.context_size,
            use_mmap: self.use_mmap,
        }
    }
}

/// Daemon system status.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SystemStatus {
    /// Seconds since the daemon started.
    pub uptime: u64,
    /// Number of models currently loaded in memory.
    pub models_loaded: u32,
    /// Total inference requests handled.
    pub total_requests: u64,
    /// Whether the internet is reachable.
    pub network_available: bool,
    /// Number of active sessions.
    #[serde(default)]
    pub active_sessions: u32,
    /// Per-category rate limit information.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rate_limits: Option<Vec<RateLimitInfo>>,
}

impl SystemStatus {
    /// Create a `SystemStatus` from a wire-format `IpcMessage`.
    pub fn from_ipc_message(msg: &IpcMessage) -> Option<Self> {
        if let IpcMessage::StatusResponse {
            uptime,
            models_loaded,
            total_requests,
            network_available,
            active_sessions,
            rate_limits,
        } = msg
        {
            Some(Self {
                uptime: *uptime,
                models_loaded: *models_loaded,
                total_requests: *total_requests,
                network_available: *network_available,
                active_sessions: *active_sessions,
                rate_limits: rate_limits.clone(),
            })
        } else {
            None
        }
    }
}

/// Health status of the daemon.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthStatus {
    /// Whether the daemon is healthy.
    pub healthy: bool,
    /// Human-readable status message.
    pub message: String,
    /// Database connectivity.
    pub database: bool,
    /// Model inference engine status.
    pub engine: bool,
    /// Network connectivity.
    pub network: bool,
    /// Uptime in seconds.
    pub uptime: u64,
}

/// Rate limit information for a single category.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RateLimitInfo {
    /// The category name.
    pub category: String,
    /// Maximum requests allowed in the window.
    pub limit: u64,
    /// Remaining requests in the current window.
    pub remaining: u64,
    /// Seconds until the window resets.
    pub reset_seconds: u64,
}

/// Rate limit status for all categories.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RateLimitStatus {
    /// Per-category rate limit info.
    pub limits: Vec<RateLimitInfo>,
}

/// Session information returned after authentication.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Session {
    /// The session token for subsequent requests.
    pub session_token: String,
    /// Whether authentication was successful.
    pub success: bool,
    /// Human-readable message.
    pub message: String,
    /// Permissions granted to this session.
    #[serde(default)]
    pub permissions: Vec<String>,
    /// Session TTL in seconds.
    #[serde(default)]
    pub session_ttl_seconds: u64,
}

impl Session {
    /// Create a `Session` from a wire-format `IpcMessage`.
    pub fn from_ipc_message(msg: &IpcMessage) -> Option<Self> {
        if let IpcMessage::AuthResponse {
            success,
            session_token,
            message,
            permissions,
            session_ttl_seconds,
        } = msg
        {
            Some(Self {
                session_token: session_token.clone().unwrap_or_default(),
                success: *success,
                message: message.clone(),
                permissions: permissions.clone(),
                session_ttl_seconds: *session_ttl_seconds,
            })
        } else {
            None
        }
    }
}

/// A single entry in the daemon's context store.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContextEntry {
    /// The lookup key.
    pub key: String,
    /// The stored value.
    pub value: Vec<u8>,
    /// Session identifier.
    #[serde(default = "default_session_id")]
    pub session_id: String,
}

fn default_session_id() -> String {
    "default".to_string()
}

/// Response from a model load operation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelLoadResponse {
    /// The model identifier.
    pub model_id: String,
    /// Status string (`"loaded"`, `"already_loaded"`, `"error"`).
    pub status: String,
    /// Human-readable message.
    pub message: String,
    /// Optional model info.
    pub model_info: Option<ModelInfo>,
}

impl ModelLoadResponse {
    /// Create from a wire-format `IpcMessage`.
    pub fn from_ipc_message(msg: &IpcMessage) -> Option<Self> {
        if let IpcMessage::ModelLoadResponse {
            model_id,
            status,
            message,
            model_info,
        } = msg
        {
            Some(Self {
                model_id: model_id.clone(),
                status: status.clone(),
                message: message.clone(),
                model_info: model_info.clone(),
            })
        } else {
            None
        }
    }
}

/// Response from a model unload operation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelUnloadResponse {
    /// The model identifier.
    pub model_id: String,
    /// Status string (`"unloaded"`, `"not_found"`, `"error"`).
    pub status: String,
    /// Human-readable message.
    pub message: String,
}

impl ModelUnloadResponse {
    /// Create from a wire-format `IpcMessage`.
    pub fn from_ipc_message(msg: &IpcMessage) -> Option<Self> {
        if let IpcMessage::ModelUnloadResponse {
            model_id,
            status,
            message,
        } = msg
        {
            Some(Self {
                model_id: model_id.clone(),
                status: status.clone(),
                message: message.clone(),
            })
        } else {
            None
        }
    }
}

// ===========================================================================
// Wire-format helpers
// ===========================================================================

/// Build a JSON-line request string for the daemon.
#[allow(dead_code)]
pub(crate) fn build_request(msg_type: &str, fields: &[(&str, &serde_json::Value)]) -> String {
    let mut map = serde_json::Map::new();
    map.insert("type".to_string(), serde_json::Value::String(msg_type.to_string()));
    for (key, value) in fields {
        map.insert(key.to_string(), (*value).clone());
    }
    serde_json::to_string(&serde_json::Value::Object(map))
        .expect("build_request: serialization should not fail")
}

/// Parse a JSON-line response from the daemon into an `IpcMessage`.
pub(crate) fn parse_response(line: &str) -> Result<IpcMessage> {
    serde_json::from_str::<IpcMessage>(line).map_err(|e| {
        AinosError::Protocol(format!("Failed to parse response: {} (line: {})", e, line))
    })
}

/// Extract the response body from an IPC message, converting errors.
pub(crate) fn check_error(msg: &IpcMessage) -> Result<()> {
    if let IpcMessage::Error { code, message } = msg {
        return Err(AinosError::DaemonError {
            code: *code,
            message: message.clone(),
        });
    }
    Ok(())
}

// ===========================================================================
// Client configuration
// ===========================================================================

/// Configuration for the [`AinosClient`](crate::client::AinosClient).
#[derive(Debug, Clone)]
pub struct ClientConfig {
    /// Daemon hostname or IP address.
    pub host: String,
    /// Daemon TCP port.
    pub port: u16,
    /// Connection timeout.
    pub connect_timeout: std::time::Duration,
    /// Read timeout for operations.
    pub read_timeout: std::time::Duration,
    /// Whether to auto-reconnect on connection failure.
    pub auto_reconnect: bool,
    /// Delay before reconnect attempt.
    pub reconnect_delay: std::time::Duration,
    /// Optional bearer token for authentication.
    pub auth_token: Option<String>,
    /// Whether to auto-authenticate after connecting.
    pub auto_authenticate: bool,
    /// Retry configuration.
    pub retry_config: crate::error::RetryConfig,
    /// Maximum buffer size for NDJSON lines.
    pub max_line_length: usize,
}

impl Default for ClientConfig {
    fn default() -> Self {
        Self {
            host: "127.0.0.1".to_string(),
            port: 9500,
            connect_timeout: std::time::Duration::from_secs(5),
            read_timeout: std::time::Duration::from_secs(120),
            auto_reconnect: true,
            reconnect_delay: std::time::Duration::from_secs(1),
            auth_token: None,
            auto_authenticate: true,
            retry_config: crate::error::RetryConfig::default(),
            max_line_length: 1024 * 1024, // 1 MB
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
    fn test_inference_request_builder() {
        let req = InferenceRequest::builder()
            .prompt("Hello")
            .model("phi-3")
            .temperature(0.5)
            .max_tokens(200)
            .session_id("sess-1")
            .build();

        assert_eq!(req.prompt, "Hello");
        assert_eq!(req.model, "phi-3");
        assert_eq!(req.temperature, Some(0.5));
        assert_eq!(req.max_tokens, Some(200));
        assert_eq!(req.session_id, Some("sess-1".into()));
    }

    #[test]
    fn test_inference_request_default_model() {
        let req = InferenceRequest::builder().prompt("Hi").build();
        assert_eq!(req.model, "default");
    }

    #[test]
    fn test_inference_request_to_ipc() {
        let req = InferenceRequest::builder()
            .prompt("Hello")
            .model("test")
            .build();
        let msg = req.to_ipc_message();
        match msg {
            IpcMessage::Inference { model, prompt, .. } => {
                assert_eq!(model, "test");
                assert_eq!(prompt, "Hello");
            }
            _ => panic!("Expected Inference"),
        }
    }

    #[test]
    fn test_model_load_options_builder() {
        let opts = ModelLoadOptions::builder()
            .path("/models/test.gguf")
            .model_type("ggml")
            .gpu_layers(32)
            .context_size(4096)
            .use_mmap(true)
            .build();

        assert_eq!(opts.path, "/models/test.gguf");
        assert_eq!(opts.model_type, Some("ggml".into()));
        assert_eq!(opts.gpu_layers, Some(32));
        assert_eq!(opts.context_size, Some(4096));
        assert_eq!(opts.use_mmap, Some(true));
    }

    #[test]
    fn test_ipc_message_roundtrip_inference() {
        let original = IpcMessage::Inference {
            model: "test-model".into(),
            prompt: "Hello".into(),
            temperature: Some(0.7),
            max_tokens: Some(100),
            session_id: Some("sess-1".into()),
        };
        let json = serde_json::to_string(&original).unwrap();
        let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
        match deserialized {
            IpcMessage::Inference { model, prompt, temperature, max_tokens, session_id } => {
                assert_eq!(model, "test-model");
                assert_eq!(prompt, "Hello");
                assert_eq!(temperature, Some(0.7));
                assert_eq!(max_tokens, Some(100));
                assert_eq!(session_id, Some("sess-1".into()));
            }
            _ => panic!("Expected Inference variant"),
        }
    }

    #[test]
    fn test_ipc_message_roundtrip_auth() {
        let original = IpcMessage::Auth {
            token: "bearer-token".into(),
        };
        let json = serde_json::to_string(&original).unwrap();
        assert_eq!(json, r#"{"type":"Auth","token":"bearer-token"}"#);
        let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
        match deserialized {
            IpcMessage::Auth { token } => assert_eq!(token, "bearer-token"),
            _ => panic!("Expected Auth"),
        }
    }

    #[test]
    fn test_ipc_message_roundtrip_status() {
        let json = serde_json::to_string(&IpcMessage::Status).unwrap();
        assert_eq!(json, r#"{"type":"Status"}"#);
    }

    #[test]
    fn test_ipc_message_roundtrip_error() {
        let original = IpcMessage::Error {
            code: -42,
            message: "Something went wrong".into(),
        };
        let json = serde_json::to_string(&original).unwrap();
        let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
        match deserialized {
            IpcMessage::Error { code, message } => {
                assert_eq!(code, -42);
                assert_eq!(message, "Something went wrong");
            }
            _ => panic!("Expected Error"),
        }
    }

    #[test]
    fn test_inference_response_extraction() {
        let msg = IpcMessage::InferenceResponse {
            output: "Hello world".into(),
            tokens_generated: 3,
            inference_ms: 100,
            source: "local".into(),
        };
        let resp = InferenceResponse::from_ipc_message(&msg).unwrap();
        assert_eq!(resp.output, "Hello world");
        assert_eq!(resp.tokens_generated, 3);
        assert_eq!(resp.source, "local");
    }

    #[test]
    fn test_system_status_extraction() {
        let msg = IpcMessage::StatusResponse {
            uptime: 3600,
            models_loaded: 2,
            total_requests: 100,
            network_available: true,
            active_sessions: 5,
            rate_limits: None,
        };
        let status = SystemStatus::from_ipc_message(&msg).unwrap();
        assert_eq!(status.uptime, 3600);
        assert_eq!(status.models_loaded, 2);
        assert!(status.network_available);
    }

    #[test]
    fn test_parse_response() {
        let line = r#"{"type":"InferenceResponse","output":"Hi","tokens_generated":1,"inference_ms":10,"source":"local"}"#;
        let msg = parse_response(line).unwrap();
        match msg {
            IpcMessage::InferenceResponse { output, .. } => assert_eq!(output, "Hi"),
            _ => panic!("Expected InferenceResponse"),
        }
    }

    #[test]
    fn test_check_error() {
        let err_msg = IpcMessage::Error {
            code: 401,
            message: "Unauthorized".into(),
        };
        assert!(check_error(&err_msg).is_err());

        let ok_msg = IpcMessage::Status;
        assert!(check_error(&ok_msg).is_ok());
    }

    #[test]
    fn test_session_extraction() {
        let msg = IpcMessage::AuthResponse {
            success: true,
            session_token: Some("tok_123".into()),
            message: "OK".into(),
            permissions: vec!["infer".into()],
            session_ttl_seconds: 3600,
        };
        let session = Session::from_ipc_message(&msg).unwrap();
        assert!(session.success);
        assert_eq!(session.session_token, "tok_123");
        assert_eq!(session.permissions, vec!["infer"]);
        assert_eq!(session.session_ttl_seconds, 3600);
    }

    #[test]
    fn test_serde_tag_consistency() {
        // Verify the JSON output uses the correct "type" tag
        let msg = IpcMessage::Status;
        let json = serde_json::to_string(&msg).unwrap();
        assert_eq!(json, r#"{"type":"Status"}"#);

        let msg = IpcMessage::RateLimitStatus;
        let json = serde_json::to_string(&msg).unwrap();
        assert_eq!(json, r#"{"type":"RateLimitStatus"}"#);

        let msg = IpcMessage::ModelList;
        let json = serde_json::to_string(&msg).unwrap();
        assert_eq!(json, r#"{"type":"ModelList"}"#);
    }

    #[test]
    fn test_model_load_response_extraction() {
        let msg = IpcMessage::ModelLoadResponse {
            model_id: "m1".into(),
            status: "loaded".into(),
            message: "OK".into(),
            model_info: None,
        };
        let resp = ModelLoadResponse::from_ipc_message(&msg).unwrap();
        assert_eq!(resp.model_id, "m1");
        assert_eq!(resp.status, "loaded");
        assert!(resp.model_info.is_none());
    }

    #[test]
    fn test_model_unload_response_extraction() {
        let msg = IpcMessage::ModelUnloadResponse {
            model_id: "m1".into(),
            status: "unloaded".into(),
            message: "OK".into(),
        };
        let resp = ModelUnloadResponse::from_ipc_message(&msg).unwrap();
        assert_eq!(resp.model_id, "m1");
        assert_eq!(resp.status, "unloaded");
    }

    #[test]
    fn test_client_config_defaults() {
        let cfg = ClientConfig::default();
        assert_eq!(cfg.host, "127.0.0.1");
        assert_eq!(cfg.port, 9500);
        assert!(cfg.auto_reconnect);
    }
}