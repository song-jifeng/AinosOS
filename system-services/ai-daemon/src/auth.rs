// Ainos AI Daemon - Authentication & Authorization
//
// This module provides a comprehensive authentication and authorization system
// for the Ainos AI Daemon IPC layer. It supports:
//
// - Token-based authentication (bearer tokens)
// - Session management with configurable TTL
// - Permission-based access control
// - Audit logging of all auth events
// - Token auto-generation with startup logging
// - Token rotation support
// - Configurable token sources (config file, env var, or auto-generated)

use crate::config::AuthConfig;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use thiserror::Error;
use tokio::sync::RwLock;
use tracing::{debug, error, info, warn};
use uuid::Uuid;
use zeroize::{Zeroize, ZeroizeOnDrop, Zeroizing};

// ============================================================================
// Error Types
// ============================================================================

/// Errors that can occur during authentication operations.
#[derive(Error, Debug, Clone)]
pub enum AuthError {
    /// The provided token is invalid or malformed.
    #[error("Invalid authentication token")]
    InvalidToken,

    /// The token has expired and needs to be refreshed.
    #[error("Token has expired")]
    TokenExpired,

    /// The session is not found (invalid or expired session token).
    #[error("Session not found: {0}")]
    SessionNotFound(String),

    /// The client does not have the required permission.
    #[error("Permission denied: required {required:?}, granted {granted:?}")]
    PermissionDenied {
        required: Permission,
        granted: Vec<Permission>,
    },

    /// Authentication is required but not provided.
    #[error("Authentication required")]
    AuthenticationRequired,

    /// The token file could not be read or written.
    #[error("Token file error: {0}")]
    TokenFileError(String),

    /// The configuration is invalid.
    #[error("Configuration error: {0}")]
    ConfigError(String),
}

// ============================================================================
// Permission System
// ============================================================================

/// Permission levels for IPC operations.
///
/// Each IPC handler requires a specific permission level. Clients must have
/// the corresponding permission (or `All`) to invoke the handler.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Permission {
    /// Permission to run inference requests.
    #[serde(rename = "infer")]
    Infer,

    /// Permission to load models into memory.
    #[serde(rename = "model_load")]
    ModelLoad,

    /// Permission to unload models from memory.
    #[serde(rename = "model_unload")]
    ModelUnload,

    /// Permission to perform admin operations.
    #[serde(rename = "admin")]
    Admin,

    /// Permission to query daemon status.
    #[serde(rename = "status")]
    Status,

    /// Permission to access context store/retrieve.
    #[serde(rename = "context")]
    Context,

    /// Super permission that grants access to all operations.
    #[serde(rename = "all")]
    All,
}

impl Permission {
    /// Returns a human-readable description of this permission.
    pub fn description(&self) -> &'static str {
        match self {
            Permission::Infer => "Inference requests",
            Permission::ModelLoad => "Load models into memory",
            Permission::ModelUnload => "Unload models from memory",
            Permission::Admin => "Administrative operations",
            Permission::Status => "Status queries",
            Permission::Context => "Context store/retrieve",
            Permission::All => "All operations (super permission)",
        }
    }

    /// Returns all defined permission variants (excluding `All`).
    pub fn all_permissions() -> Vec<Permission> {
        vec![
            Permission::Infer,
            Permission::ModelLoad,
            Permission::ModelUnload,
            Permission::Admin,
            Permission::Status,
            Permission::Context,
        ]
    }

    /// Returns the default permissions for unauthenticated clients.
    pub fn default_unauthenticated() -> Vec<Permission> {
        vec![Permission::Status]
    }

    /// Returns the default permissions for authenticated clients.
    pub fn default_authenticated() -> Vec<Permission> {
        vec![
            Permission::Infer,
            Permission::Status,
            Permission::Context,
        ]
    }

    /// Checks if this permission is satisfied by a set of granted permissions.
    pub fn is_satisfied_by(&self, granted: &[Permission]) -> bool {
        granted.contains(&Permission::All) || granted.contains(self)
    }
}

/// Map a permission to its required IPC message type.
/// This is used to look up the permission needed for a given message.
impl Permission {
    /// Determine the required permission from an IPC message type string.
    pub fn from_message_type(msg_type: &str) -> Option<Permission> {
        match msg_type {
            "Inference" | "InferenceResponse" | "InferenceChunk" => Some(Permission::Infer),
            "ModelLoad" => Some(Permission::ModelLoad),
            "ModelUnload" => Some(Permission::ModelUnload),
            "ModelList" | "ModelListResponse" => Some(Permission::Status),
            "Status" | "StatusResponse" => Some(Permission::Status),
            "ContextStore" | "ContextRetrieve" => Some(Permission::Context),
            "Auth" | "AuthResponse" => None, // Auth is always allowed
            "RateLimitStatus" => Some(Permission::Status),
            "Error" => None, // Errors are always allowed
            _ => Some(Permission::Admin),
        }
    }
}

// ============================================================================
// Auth Token (zeroize-protected)
// ============================================================================

/// A bearer token that is automatically zeroized on drop.
///
/// This wraps a `String` and implements `Zeroize` and `ZeroizeOnDrop` to
/// ensure the token contents are securely cleared from memory when the
/// token is no longer needed.
#[derive(Clone, Zeroize, ZeroizeOnDrop)]
pub struct AuthToken {
    /// The raw token string.
    token: String,
}

impl AuthToken {
    /// Create a new `AuthToken` from a string.
    pub fn new(token: String) -> Self {
        Self { token }
    }

    /// Create a new `AuthToken` from a `Zeroizing<String>`.
    pub fn from_zeroizing(token: Zeroizing<String>) -> Self {
        Self {
            token: token.to_string(),
        }
    }

    /// Return the token value as a string reference.
    pub fn as_str(&self) -> &str {
        &self.token
    }

    /// Generate a cryptographically random token.
    ///
    /// Uses `rand` to generate 32 random bytes, then encodes them as a
    /// lowercase hex string (64 characters).
    pub fn generate() -> Self {
        use rand::Rng;
        let mut bytes = [0u8; 32];
        rand::thread_rng().fill(&mut bytes);
        let token = bytes
            .iter()
            .map(|b| format!("{:02x}", b))
            .collect::<String>();
        Self { token }
    }

    /// Validate the token format.
    ///
    /// Tokens must be at least 16 characters long and contain only
    /// alphanumeric characters, dashes, and underscores.
    pub fn validate(&self) -> bool {
        if self.token.len() < 16 {
            return false;
        }
        self.token
            .chars()
            .all(|c| c.is_alphanumeric() || c == '-' || c == '_' || c == '.')
    }

    /// Return a masked version of the token for logging.
    ///
    /// Only the first 8 and last 4 characters are shown, e.g.
    /// `"abc12345...ef89"`.
    pub fn masked(&self) -> String {
        if self.token.len() <= 16 {
            return format!("{}...{}", &self.token[..4], &self.token[self.token.len() - 4..]);
        }
        format!(
            "{}...{}",
            &self.token[..8],
            &self.token[self.token.len() - 4..]
        )
    }

    /// Consume the token and return the inner string.
    pub fn into_inner(self) -> String {
        self.token.clone()
    }
}

impl std::fmt::Debug for AuthToken {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("AuthToken")
            .field("token", &"[REDACTED]")
            .finish()
    }
}

impl std::fmt::Display for AuthToken {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "AuthToken({})", self.masked())
    }
}

// ============================================================================
// Session
// ============================================================================

/// A session represents an authenticated client connection.
///
/// Each session has a unique token, a set of permissions, and a TTL.
/// Sessions are created upon successful authentication and are used to
/// authorize subsequent IPC messages.
#[derive(Debug, Clone)]
pub struct Session {
    /// The session token (UUID v4) used to identify this session.
    pub session_token: String,

    /// The permissions granted to this session.
    pub permissions: Vec<Permission>,

    /// When this session was created.
    pub created_at: Instant,

    /// When this session expires.
    pub expires_at: Instant,

    /// Last activity timestamp (updated on each message).
    pub last_activity: Instant,

    /// A human-readable identifier for the client (IP address or hostname).
    pub client_id: String,

    /// The original bearer token used to authenticate (stored for audit).
    /// This is not serialized or exposed externally.
    #[cfg_attr(not(test), allow(dead_code))]
    auth_token_hash: u64,
}

impl Session {
    /// Create a new session.
    pub fn new(
        client_id: String,
        permissions: Vec<Permission>,
        ttl: Duration,
        auth_token: &AuthToken,
    ) -> Self {
        let now = Instant::now();
        Self {
            session_token: Uuid::new_v4().to_string(),
            permissions,
            created_at: now,
            expires_at: now + ttl,
            last_activity: now,
            client_id,
            auth_token_hash: simple_hash(auth_token.as_str()),
        }
    }

    /// Check if this session has expired.
    pub fn is_expired(&self) -> bool {
        Instant::now() >= self.expires_at
    }

    /// Check if the session has the given permission.
    pub fn has_permission(&self, permission: &Permission) -> bool {
        self.permissions.contains(&Permission::All) || self.permissions.contains(permission)
    }

    /// Touch the session, updating the last activity time.
    pub fn touch(&mut self) {
        self.last_activity = Instant::now();
    }

    /// Extend the session TTL.
    pub fn extend_ttl(&mut self, ttl: Duration) {
        self.expires_at = Instant::now() + ttl;
    }

    /// Return the time until this session expires.
    pub fn time_to_live(&self) -> Duration {
        self.expires_at.saturating_duration_since(Instant::now())
    }

    /// Return the time since last activity.
    pub fn idle_time(&self) -> Duration {
        Instant::now().saturating_duration_since(self.last_activity)
    }
}

/// Simple non-cryptographic hash for token audit tracking.
fn simple_hash(s: &str) -> u64 {
    use std::hash::{Hash, Hasher};
    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    s.hash(&mut hasher);
    hasher.finish()
}

// ============================================================================
// Audit Event
// ============================================================================

/// Types of audit events.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum AuditEventType {
    /// Authentication attempt (success or failure).
    Authentication,
    /// Authentication failure.
    AuthFailure,
    /// Permission denied.
    PermissionDenied,
    /// Admin operation.
    AdminOperation,
    /// Session expired.
    SessionExpired,
    /// Token rotation.
    TokenRotation,
    /// Session created.
    SessionCreated,
    /// Session destroyed.
    SessionDestroyed,
    /// Rate limit exceeded.
    RateLimitExceeded,
}

/// A single audit log entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuditEntry {
    /// Timestamp of the event (ISO 8601).
    pub timestamp: String,
    /// Type of audit event.
    pub event_type: AuditEventType,
    /// Client identifier (IP or hostname).
    pub client_id: String,
    /// Session token (masked).
    pub session_token: Option<String>,
    /// Detailed message.
    pub message: String,
    /// Optional error details.
    pub error: Option<String>,
}

impl AuditEntry {
    fn new(
        event_type: AuditEventType,
        client_id: &str,
        session_token: Option<&str>,
        message: String,
        error: Option<String>,
    ) -> Self {
        use chrono::Utc;
        Self {
            timestamp: Utc::now().to_rfc3339(),
            event_type,
            client_id: client_id.to_string(),
            session_token: session_token.map(|s| mask_token(s)),
            message,
            error,
        }
    }
}

/// Mask a token for logging (show first 8 chars, then "...", then last 4 chars).
fn mask_token(token: &str) -> String {
    if token.len() <= 16 {
        return format!("{}...{}", &token[..4], &token[token.len() - 4..]);
    }
    format!("{}...{}", &token[..8], &token[token.len() - 4..])
}

// ============================================================================
// Audit Logger
// ============================================================================

/// Audit logger for recording authentication and authorization events.
///
/// Audit logs are written to the configured audit log file and also
/// emitted as structured tracing events at the `info` level.
#[derive(Debug)]
pub struct AuditLogger {
    /// Path to the audit log file.
    log_path: Option<String>,
    /// Whether to log all requests (not just auth events).
    log_all_requests: bool,
    /// Statistics counters.
    stats: Arc<AuditStats>,
    /// In-memory audit log buffer (last N entries).
    buffer: Arc<RwLock<Vec<AuditEntry>>>,
    /// Maximum number of in-memory entries.
    max_buffer_size: usize,
}

/// Audit statistics counters.
#[derive(Debug, Default)]
pub struct AuditStats {
    pub total_auth_attempts: AtomicU64,
    pub successful_auths: AtomicU64,
    pub failed_auths: AtomicU64,
    pub permission_denied: AtomicU64,
    pub admin_operations: AtomicU64,
    pub session_expirations: AtomicU64,
    pub rate_limit_events: AtomicU64,
}

impl AuditLogger {
    /// Create a new audit logger.
    pub fn new(log_path: Option<String>, log_all_requests: bool) -> Self {
        Self {
            log_path,
            log_all_requests,
            stats: Arc::new(AuditStats::default()),
            buffer: Arc::new(RwLock::new(Vec::with_capacity(1000))),
            max_buffer_size: 10_000,
        }
    }

    /// Create a new audit logger from configuration.
    pub fn from_config(config: &AuthConfig) -> Self {
        let log_path = if config.audit_log_path.is_empty() {
            None
        } else {
            Some(config.audit_log_path.clone())
        };
        Self::new(log_path, config.audit_all_requests)
    }

    /// Log an authentication attempt.
    pub async fn log_auth(
        &self,
        client_id: &str,
        success: bool,
        token_masked: &str,
        message: String,
    ) {
        self.stats.total_auth_attempts.fetch_add(1, Ordering::Relaxed);

        let event_type = if success {
            self.stats.successful_auths.fetch_add(1, Ordering::Relaxed);
            AuditEventType::Authentication
        } else {
            self.stats.failed_auths.fetch_add(1, Ordering::Relaxed);
            AuditEventType::AuthFailure
        };

        let entry = AuditEntry::new(
            event_type,
            client_id,
            None,
            format!("[{}] {}", token_masked, message),
            if success { None } else { Some("Authentication failed".to_string()) },
        );

        self.write_entry(entry).await;
    }

    /// Log a permission denied event.
    pub async fn log_permission_denied(
        &self,
        client_id: &str,
        session_token: Option<&str>,
        required: &Permission,
        granted: &[Permission],
        operation: &str,
    ) {
        self.stats.permission_denied.fetch_add(1, Ordering::Relaxed);

        let entry = AuditEntry::new(
            AuditEventType::PermissionDenied,
            client_id,
            session_token,
            format!(
                "Permission denied for {}: required {:?}, granted {:?}",
                operation, required, granted
            ),
            Some(format!("Required {:?}", required)),
        );

        self.write_entry(entry).await;
    }

    /// Log an admin operation.
    pub async fn log_admin_operation(
        &self,
        client_id: &str,
        session_token: Option<&str>,
        operation: &str,
        details: &str,
    ) {
        self.stats.admin_operations.fetch_add(1, Ordering::Relaxed);

        let entry = AuditEntry::new(
            AuditEventType::AdminOperation,
            client_id,
            session_token,
            format!("Admin operation: {} - {}", operation, details),
            None,
        );

        self.write_entry(entry).await;
    }

    /// Log a session expiry event.
    pub async fn log_session_expired(&self, client_id: &str, session_token: &str) {
        self.stats.session_expirations.fetch_add(1, Ordering::Relaxed);

        let entry = AuditEntry::new(
            AuditEventType::SessionExpired,
            client_id,
            Some(session_token),
            "Session expired".to_string(),
            None,
        );

        self.write_entry(entry).await;
    }

    /// Log a rate limit exceeded event.
    pub async fn log_rate_limit(
        &self,
        client_id: &str,
        session_token: Option<&str>,
        category: &str,
        retry_after: Duration,
    ) {
        self.stats.rate_limit_events.fetch_add(1, Ordering::Relaxed);

        let entry = AuditEntry::new(
            AuditEventType::RateLimitExceeded,
            client_id,
            session_token,
            format!(
                "Rate limit exceeded for {}: retry after {}ms",
                category,
                retry_after.as_millis()
            ),
            None,
        );

        self.write_entry(entry).await;
    }

    /// Log a session created event.
    pub async fn log_session_created(
        &self,
        client_id: &str,
        session_token: &str,
        permissions: &[Permission],
    ) {
        let perms_str = permissions
            .iter()
            .map(|p| format!("{:?}", p))
            .collect::<Vec<_>>()
            .join(", ");

        let entry = AuditEntry::new(
            AuditEventType::SessionCreated,
            client_id,
            Some(session_token),
            format!("Session created with permissions: [{}]", perms_str),
            None,
        );

        self.write_entry(entry).await;
    }

    /// Log a session destroyed event.
    #[allow(dead_code)]
    pub async fn log_session_destroyed(&self, client_id: &str, session_token: &str) {
        let entry = AuditEntry::new(
            AuditEventType::SessionDestroyed,
            client_id,
            Some(session_token),
            "Session destroyed".to_string(),
            None,
        );

        self.write_entry(entry).await;
    }

    /// Log a token rotation event.
    #[allow(dead_code)]
    pub async fn log_token_rotation(&self, old_token_masked: &str, new_token_masked: &str) {
        let entry = AuditEntry::new(
            AuditEventType::TokenRotation,
            "system",
            None,
            format!(
                "Token rotated: {} -> {}",
                old_token_masked, new_token_masked
            ),
            None,
        );

        self.write_entry(entry).await;
    }

    /// Get a reference to the audit statistics.
    pub fn stats(&self) -> &Arc<AuditStats> {
        &self.stats
    }

    /// Get the current in-memory audit buffer.
    pub async fn get_buffer(&self) -> Vec<AuditEntry> {
        self.buffer.read().await.clone()
    }

    /// Get the number of entries in the audit buffer.
    pub async fn buffer_len(&self) -> usize {
        self.buffer.read().await.len()
    }

    /// Write an audit entry to the log file and in-memory buffer.
    async fn write_entry(&self, entry: AuditEntry) {
        // Write to in-memory buffer
        {
            let mut buffer = self.buffer.write().await;
            buffer.push(entry.clone());
            while buffer.len() > self.max_buffer_size {
                buffer.remove(0);
            }
        }

        // Emit structured tracing event
        let event_type = format!("{:?}", entry.event_type);
        match entry.event_type {
            AuditEventType::AuthFailure
            | AuditEventType::PermissionDenied
            | AuditEventType::RateLimitExceeded => {
                warn!(
                    target: "ainos::audit",
                    event_type = %event_type,
                    client_id = %entry.client_id,
                    message = %entry.message,
                    "AUDIT [{}] {}: {}",
                    event_type, entry.client_id, entry.message
                );
            }
            _ => {
                info!(
                    target: "ainos::audit",
                    event_type = %event_type,
                    client_id = %entry.client_id,
                    message = %entry.message,
                    "AUDIT [{}] {}: {}",
                    event_type, entry.client_id, entry.message
                );
            }
        }

        // Write to file if configured
        if let Some(ref path) = self.log_path {
            if let Ok(json) = serde_json::to_string(&entry) {
                if let Err(e) = fs::OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(path)
                    .and_then(|mut f| {
                        use std::io::Write;
                        writeln!(f, "{}", json)
                    })
                {
                    error!("Failed to write audit log entry: {}", e);
                }
            }
        }
    }
}

// ============================================================================
// Session Manager
// ============================================================================

/// Manages client sessions, including creation, validation, and cleanup.
///
/// The session manager is the central authority for authentication. It:
/// 1. Validates bearer tokens against the configured token
/// 2. Creates sessions with appropriate permissions
/// 3. Validates session tokens on subsequent requests
/// 4. Enforces permission checks
/// 5. Periodically cleans up expired sessions
pub struct SessionManager {
    /// Active sessions (session_token -> Session).
    sessions: Arc<RwLock<HashMap<String, Session>>>,

    /// The configured bearer token for authentication.
    configured_token: Option<AuthToken>,

    /// Session TTL configuration.
    session_ttl: Duration,

    /// Default permissions for authenticated clients.
    default_permissions: Vec<Permission>,

    /// Audit logger.
    audit: Arc<AuditLogger>,

    /// Token-to-permission overrides (from permissions file).
    token_permissions: Arc<RwLock<HashMap<String, Vec<Permission>>>>,

    /// Whether authentication is enabled.
    enabled: bool,
}

impl std::fmt::Debug for SessionManager {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SessionManager")
            .field("active_sessions", &self.sessions.blocking_read().len())
            .field("has_token", &self.configured_token.is_some())
            .field("session_ttl", &self.session_ttl)
            .field("enabled", &self.enabled)
            .finish()
    }
}

impl SessionManager {
    /// Create a new session manager.
    pub fn new(
        config: &AuthConfig,
        audit: Arc<AuditLogger>,
    ) -> Self {
        // Determine the bearer token
        let configured_token = Self::resolve_token(config);

        // Log the token status
        if let Some(ref token) = configured_token {
            info!(
                "Authentication configured with token: {}",
                token.masked()
            );
        } else {
            info!("Authentication is disabled (no token configured)");
        }

        let session_ttl = if config.session_ttl_seconds > 0 {
            Duration::from_secs(config.session_ttl_seconds)
        } else {
            Duration::from_secs(3600) // Default: 1 hour
        };

        let default_permissions = if config.default_permissions.is_empty() {
            Permission::default_authenticated()
        } else {
            config
                .default_permissions
                .iter()
                .filter_map(|p| match p.to_lowercase().as_str() {
                    "infer" => Some(Permission::Infer),
                    "model_load" => Some(Permission::ModelLoad),
                    "model_unload" => Some(Permission::ModelUnload),
                    "admin" => Some(Permission::Admin),
                    "status" => Some(Permission::Status),
                    "context" => Some(Permission::Context),
                    "all" => Some(Permission::All),
                    _ => {
                        warn!("Unknown permission in config: {}", p);
                        None
                    }
                })
                .collect()
        };

        Self {
            sessions: Arc::new(RwLock::new(HashMap::new())),
            configured_token,
            session_ttl,
            default_permissions,
            audit,
            token_permissions: Arc::new(RwLock::new(HashMap::new())),
            enabled: config.enabled,
        }
    }

    /// Resolve the bearer token from config, env var, or auto-generation.
    fn resolve_token(config: &AuthConfig) -> Option<AuthToken> {
        // 1. Check environment variable first
        if let Ok(env_token) = std::env::var("AINOS_AUTH_TOKEN") {
            if !env_token.is_empty() {
                let token = AuthToken::new(env_token);
                if token.validate() {
                    info!("Using auth token from AINOS_AUTH_TOKEN environment variable");
                    return Some(token);
                } else {
                    warn!("AINOS_AUTH_TOKEN format is invalid (min 16 chars, alphanumeric)");
                }
            }
        }

        // 2. Check config file token
        if !config.token.is_empty() {
            let token = AuthToken::new(config.token.clone());
            if token.validate() {
                info!("Using auth token from config file");
                return Some(token);
            } else {
                warn!("Auth token from config file is invalid (min 16 chars, alphanumeric)");
            }
        }

        // 3. Check token file
        if !config.token_path.is_empty() {
            if let Ok(content) = fs::read_to_string(&config.token_path) {
                let token_str = content.trim().to_string();
                if !token_str.is_empty() {
                    let token = AuthToken::new(token_str);
                    if token.validate() {
                        info!("Using auth token from file: {}", config.token_path);
                        return Some(token);
                    } else {
                        warn!("Auth token from file is invalid");
                    }
                }
            }
        }

        // 4. Auto-generate token
        if config.enabled {
            let token = AuthToken::generate();
            info!(
                "============================================================"
            );
            info!(
                "  AUTH TOKEN AUTO-GENERATED: {}",
                token.as_str()
            );
            info!(
                "  Save this token for client authentication."
            );
            if !config.token_path.is_empty() {
                // Try to save the token to the configured path
                if let Some(parent) = Path::new(&config.token_path).parent() {
                    if !parent.exists() {
                        let _ = fs::create_dir_all(parent);
                    }
                }
                match fs::write(&config.token_path, token.as_str()) {
                    Ok(_) => info!("  Token saved to: {}", config.token_path),
                    Err(e) => warn!("  Failed to save token to {}: {}", config.token_path, e),
                }
            }
            info!(
                "============================================================"
            );
            return Some(token);
        }

        None
    }

    /// Check if authentication is enabled.
    pub fn is_enabled(&self) -> bool {
        self.enabled
    }

    /// Check if a token is configured.
    pub fn has_token(&self) -> bool {
        self.configured_token.is_some()
    }

    /// Get the configured token (for display purposes only).
    /// Returns the masked version of the token.
    pub fn masked_token(&self) -> Option<String> {
        self.configured_token.as_ref().map(|t| t.masked())
    }

    /// Authenticate a client with a bearer token.
    ///
    /// Returns a session token on success, or an error on failure.
    pub async fn authenticate(
        &self,
        client_id: &str,
        bearer_token: &str,
    ) -> Result<String, AuthError> {
        if !self.enabled {
            // Auth disabled: create a session with full permissions
            let dummy_token = AuthToken::new("auth-disabled".to_string());
            let session = Session::new(
                client_id.to_string(),
                vec![Permission::All],
                self.session_ttl,
                &dummy_token,
            );
            let session_token = session.session_token.clone();

            self.audit
                .log_auth(client_id, true, "auth-disabled", "Auth disabled - full access granted".to_string())
                .await;

            let mut sessions = self.sessions.write().await;
            sessions.insert(session_token.clone(), session);

            return Ok(session_token);
        }

        let configured = self
            .configured_token
            .as_ref()
            .ok_or(AuthError::ConfigError("No token configured".to_string()))?;

        // Validate the bearer token
        if bearer_token != configured.as_str() {
            self.audit
                .log_auth(
                    client_id,
                    false,
                    &mask_token(bearer_token),
                    format!("Invalid token provided (expected {})", configured.masked()),
                )
                .await;

            return Err(AuthError::InvalidToken);
        }

        // Determine permissions for this token
        let permissions = {
            let token_perms = self.token_permissions.read().await;
            token_perms
                .get(bearer_token)
                .cloned()
                .unwrap_or_else(|| self.default_permissions.clone())
        };

        // Create session
        let auth_token = AuthToken::new(bearer_token.to_string());
        let session = Session::new(
            client_id.to_string(),
            permissions.clone(),
            self.session_ttl,
            &auth_token,
        );
        let session_token = session.session_token.clone();

        self.audit
            .log_auth(client_id, true, &configured.masked(), "Authentication successful".to_string())
            .await;

        self.audit
            .log_session_created(client_id, &session_token, &permissions)
            .await;

        let mut sessions = self.sessions.write().await;
        sessions.insert(session_token.clone(), session);

        Ok(session_token)
    }

    /// Validate a session token and return the session.
    ///
    /// Returns an error if the session is not found or has expired.
    pub async fn validate_session(
        &self,
        session_token: &str,
    ) -> Result<Session, AuthError> {
        if !self.enabled {
            // Auth disabled: return a dummy session with full permissions
            return Ok(Session {
                session_token: session_token.to_string(),
                permissions: vec![Permission::All],
                created_at: Instant::now(),
                expires_at: Instant::now() + Duration::from_secs(3600),
                last_activity: Instant::now(),
                client_id: "unknown".to_string(),
                auth_token_hash: 0,
            });
        }

        let mut sessions = self.sessions.write().await;

        let session = sessions
            .get_mut(session_token)
            .ok_or_else(|| AuthError::SessionNotFound(session_token.to_string()))?;

        if session.is_expired() {
            let client_id = session.client_id.clone();
            sessions.remove(session_token);
            drop(sessions);

            self.audit
                .log_session_expired(&client_id, session_token)
                .await;

            return Err(AuthError::TokenExpired);
        }

        // Update last activity
        session.touch();

        Ok(session.clone())
    }

    /// Check if a session has the required permission.
    pub async fn check_permission(
        &self,
        session_token: &str,
        required: &Permission,
    ) -> Result<Session, AuthError> {
        let session = self.validate_session(session_token).await?;

        if !session.has_permission(required) {
            self.audit
                .log_permission_denied(
                    &session.client_id,
                    Some(session_token),
                    required,
                    &session.permissions,
                    &format!("{:?}", required),
                )
                .await;

            return Err(AuthError::PermissionDenied {
                required: *required,
                granted: session.permissions,
            });
        }

        Ok(session)
    }

    /// Destroy a session (logout).
    pub async fn destroy_session(&self, session_token: &str) -> bool {
        let mut sessions = self.sessions.write().await;
        if let Some(session) = sessions.remove(session_token) {
            self.audit
                .log_session_destroyed(&session.client_id, session_token)
                .await;
            true
        } else {
            false
        }
    }

    /// Rotate the bearer token.
    ///
    /// This generates a new token and saves it to the token file.
    /// Existing sessions remain valid until they expire.
    pub async fn rotate_token(&self, token_path: &str) -> Result<AuthToken, AuthError> {
        let old_token = self.configured_token.as_ref().map(|t| t.masked());
        let new_token = AuthToken::generate();

        // Save to file
        if let Some(parent) = Path::new(token_path).parent() {
            let _ = fs::create_dir_all(parent);
        }
        fs::write(token_path, new_token.as_str())
            .map_err(|e| AuthError::TokenFileError(e.to_string()))?;

        // Update the configured token (using interior mutability)
        // Since configured_token is not in a RwLock, we use unsafe to update it.
        // In practice, the session manager is behind an Arc, so we need to
        // use a different approach. We'll use a separate atomic approach.
        //
        // For now, we log the rotation and return the new token.
        // The caller is responsible for updating the config.
        if let Some(ref old) = old_token {
            self.audit
                .log_token_rotation(old, &new_token.masked())
                .await;
        }

        info!(
            "Token rotated. New token: {} (saved to {})",
            new_token.masked(),
            token_path
        );

        Ok(new_token)
    }

    /// Get the number of active sessions.
    pub async fn active_sessions(&self) -> usize {
        self.sessions.read().await.len()
    }

    /// Get a list of all active session tokens (masked).
    pub async fn list_sessions(&self) -> Vec<(String, String, Duration)> {
        self.sessions
            .read()
            .await
            .iter()
            .map(|(token, session)| {
                (
                    mask_token(token),
                    session.client_id.clone(),
                    session.time_to_live(),
                )
            })
            .collect()
    }

    /// Clean up expired sessions.
    ///
    /// This should be called periodically to remove stale sessions.
    pub async fn cleanup_expired(&self) -> usize {
        let mut sessions = self.sessions.write().await;
        let expired_tokens: Vec<String> = sessions
            .iter()
            .filter(|(_, session)| session.is_expired())
            .map(|(token, _)| token.clone())
            .collect();

        let count = expired_tokens.len();
        for token in &expired_tokens {
            if let Some(session) = sessions.remove(token) {
                self.audit
                    .log_session_expired(&session.client_id, token)
                    .await;
            }
        }

        if count > 0 {
            debug!("Cleaned up {} expired sessions", count);
        }

        count
    }

    /// Get a reference to the audit logger.
    pub fn audit(&self) -> &Arc<AuditLogger> {
        &self.audit
    }

    /// Get the session TTL.
    pub fn session_ttl(&self) -> Duration {
        self.session_ttl
    }
}

// ============================================================================
// Periodic session cleanup task
// ============================================================================

/// Run periodic session cleanup.
///
/// This should be spawned as a background task that runs every
/// `interval` seconds to clean up expired sessions.
pub async fn session_cleanup_task(session_manager: Arc<SessionManager>, interval_secs: u64) {
    let mut interval = tokio::time::interval(Duration::from_secs(interval_secs));
    loop {
        interval.tick().await;
        let cleaned = session_manager.cleanup_expired().await;
        let active = session_manager.active_sessions().await;
        debug!(
            "Session cleanup: removed {}, active: {}",
            cleaned, active
        );
    }
}

// ============================================================================
// Auth Handshake (IPC message types)
// ============================================================================

/// Authentication request sent by the client.
///
/// The client sends this as the first message after connecting. The
/// `token` field contains the bearer token.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuthRequest {
    /// The bearer token for authentication.
    pub token: String,
}

/// Authentication response sent by the server.
///
/// If successful, `session_token` must be included in subsequent messages
/// as the `auth` field.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuthResponse {
    /// Whether authentication was successful.
    pub success: bool,
    /// The session token for subsequent requests.
    pub session_token: Option<String>,
    /// Human-readable message.
    pub message: String,
    /// Permissions granted to this session.
    #[serde(default)]
    pub permissions: Vec<String>,
    /// Session TTL in seconds.
    #[serde(default)]
    pub session_ttl_seconds: u64,
}

// ============================================================================
// Permission mapping helper
// ============================================================================

/// Convert a permission enum to a string slice.
pub fn permission_to_str(p: &Permission) -> &'static str {
    match p {
        Permission::Infer => "infer",
        Permission::ModelLoad => "model_load",
        Permission::ModelUnload => "model_unload",
        Permission::Admin => "admin",
        Permission::Status => "status",
        Permission::Context => "context",
        Permission::All => "all",
    }
}

/// Parse a permission from a string.
pub fn permission_from_str(s: &str) -> Option<Permission> {
    match s.to_lowercase().as_str() {
        "infer" => Some(Permission::Infer),
        "model_load" => Some(Permission::ModelLoad),
        "model_unload" => Some(Permission::ModelUnload),
        "admin" => Some(Permission::Admin),
        "status" => Some(Permission::Status),
        "context" => Some(Permission::Context),
        "all" => Some(Permission::All),
        _ => None,
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    fn test_config() -> AuthConfig {
        AuthConfig {
            enabled: true,
            token: "test-token-12345-abcdefghij".to_string(),
            token_path: "".to_string(),
            session_ttl_seconds: 3600,
            permissions_file: "".to_string(),
            default_permissions: vec![],
            audit_log_path: "".to_string(),
            audit_all_requests: false,
        }
    }

    fn disabled_config() -> AuthConfig {
        let mut cfg = test_config();
        cfg.enabled = false;
        cfg
    }

    fn test_audit() -> Arc<AuditLogger> {
        Arc::new(AuditLogger::new(None, false))
    }

    #[tokio::test]
    async fn test_auth_token_generate() {
        let token = AuthToken::generate();
        assert_eq!(token.as_str().len(), 64, "Generated token should be 64 hex chars");
        assert!(token.validate(), "Generated token should be valid");
    }

    #[tokio::test]
    async fn test_auth_token_validate() {
        let valid = AuthToken::new("abcdefghijklmnop".to_string());
        assert!(valid.validate(), "16-char token should be valid");

        let short = AuthToken::new("short".to_string());
        assert!(!short.validate(), "Short token should be invalid");

        let special = AuthToken::new("abcdefghijklmnop_-.test".to_string());
        assert!(special.validate(), "Token with dashes/underscores/dots should be valid");
    }

    #[tokio::test]
    async fn test_auth_token_masked() {
        let token = AuthToken::new("abcdefghijklmnopqrstuvwxyz12345678".to_string());
        let masked = token.masked();
        assert!(masked.contains("..."), "Masked token should contain '...'");
        assert!(masked.starts_with("abcdefgh"), "Masked token should start with first 8 chars");
        assert!(masked.ends_with("5678"), "Masked token should end with last 4 chars");
    }

    #[tokio::test]
    async fn test_session_creation() {
        let token = AuthToken::new("test-token".to_string());
        let session = Session::new(
            "127.0.0.1:12345".to_string(),
            vec![Permission::Infer, Permission::Status],
            Duration::from_secs(3600),
            &token,
        );

        assert_eq!(session.client_id, "127.0.0.1:12345");
        assert!(session.has_permission(&Permission::Infer));
        assert!(session.has_permission(&Permission::Status));
        assert!(!session.has_permission(&Permission::Admin));
        assert!(!session.is_expired());
        assert_eq!(session.session_token.len(), 36); // UUID v4
    }

    #[tokio::test]
    async fn test_session_expiry() {
        let token = AuthToken::new("test-token".to_string());
        let session = Session::new(
            "client".to_string(),
            vec![Permission::Status],
            Duration::from_millis(1), // Very short TTL
            &token,
        );

        // Wait for expiry
        tokio::time::sleep(Duration::from_millis(10)).await;
        assert!(session.is_expired(), "Session should be expired");
    }

    #[tokio::test]
    async fn test_session_ttl() {
        let token = AuthToken::new("test-token".to_string());
        let session = Session::new(
            "client".to_string(),
            vec![Permission::Status],
            Duration::from_secs(60),
            &token,
        );

        let ttl = session.time_to_live();
        assert!(ttl > Duration::from_secs(55), "TTL should be close to 60s");
        assert!(ttl <= Duration::from_secs(60), "TTL should not exceed 60s");
    }

    #[tokio::test]
    async fn test_session_all_permission() {
        let token = AuthToken::new("test-token".to_string());
        let session = Session::new(
            "admin".to_string(),
            vec![Permission::All],
            Duration::from_secs(3600),
            &token,
        );

        assert!(session.has_permission(&Permission::Infer));
        assert!(session.has_permission(&Permission::ModelLoad));
        assert!(session.has_permission(&Permission::Admin));
        assert!(session.has_permission(&Permission::Status));
        assert!(session.has_permission(&Permission::Context));
    }

    #[tokio::test]
    async fn test_session_manager_authenticate() {
        let config = test_config();
        let audit = test_audit();
        let manager = SessionManager::new(&config, audit);

        // Test successful authentication
        let result = manager
            .authenticate("127.0.0.1:9500", "test-token-12345-abcdefghij")
            .await;
        assert!(result.is_ok(), "Authentication should succeed with correct token");

        let session_token = result.unwrap();
        assert!(!session_token.is_empty(), "Session token should not be empty");

        // Test failed authentication
        let result = manager
            .authenticate("127.0.0.1:9501", "wrong-token")
            .await;
        assert!(result.is_err(), "Authentication should fail with wrong token");
        match result {
            Err(AuthError::InvalidToken) => {}
            _ => panic!("Expected InvalidToken error"),
        }
    }

    #[tokio::test]
    async fn test_session_manager_disabled_auth() {
        let config = disabled_config();
        let audit = test_audit();
        let manager = SessionManager::new(&config, audit);

        // Auth disabled should succeed with any token
        let result = manager
            .authenticate("client", "any-token")
            .await;
        assert!(result.is_ok(), "Auth should succeed when disabled");

        // Should have all permissions
        let session = manager
            .validate_session(&result.unwrap())
            .await
            .unwrap();
        assert!(
            session.has_permission(&Permission::All),
            "Disabled auth should grant all permissions"
        );
    }

    #[tokio::test]
    async fn test_session_validate() {
        let config = test_config();
        let audit = test_audit();
        let manager = SessionManager::new(&config, audit);

        let session_token = manager
            .authenticate("client", "test-token-12345-abcdefghij")
            .await
            .unwrap();

        // Validate session
        let session = manager.validate_session(&session_token).await;
        assert!(session.is_ok(), "Session should be valid");

        // Session token should match
        assert_eq!(session.unwrap().session_token, session_token);
    }

    #[tokio::test]
    async fn test_session_validate_invalid() {
        let config = test_config();
        let audit = test_audit();
        let manager = SessionManager::new(&config, audit);

        let result = manager.validate_session("nonexistent-session-token").await;
        assert!(result.is_err(), "Invalid session token should fail");
        match result {
            Err(AuthError::SessionNotFound(_)) => {}
            _ => panic!("Expected SessionNotFound error"),
        }
    }

    #[tokio::test]
    async fn test_permission_check() {
        let config = test_config();
        let audit = test_audit();
        let manager = SessionManager::new(&config, audit);

        let session_token = manager
            .authenticate("client", "test-token-12345-abcdefghij")
            .await
            .unwrap();

        // Default permissions include Infer, Status, Context
        let result = manager
            .check_permission(&session_token, &Permission::Infer)
            .await;
        assert!(result.is_ok(), "Should have Infer permission");

        let result = manager
            .check_permission(&session_token, &Permission::Status)
            .await;
        assert!(result.is_ok(), "Should have Status permission");

        // ModelLoad is not in default permissions
        let result = manager
            .check_permission(&session_token, &Permission::ModelLoad)
            .await;
        assert!(result.is_err(), "Should NOT have ModelLoad permission");
    }

    #[tokio::test]
    async fn test_session_destroy() {
        let config = test_config();
        let audit = test_audit();
        let manager = SessionManager::new(&config, audit);

        let session_token = manager
            .authenticate("client", "test-token-12345-abcdefghij")
            .await
            .unwrap();

        assert!(manager.destroy_session(&session_token).await);
        assert!(!manager.destroy_session(&session_token).await);

        // Session should be invalid after destroy
        let result = manager.validate_session(&session_token).await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_session_cleanup() {
        let config = AuthConfig {
            enabled: true,
            token: "test-token-12345-abcdefghij".to_string(),
            token_path: "".to_string(),
            session_ttl_seconds: 1, // 1 second TTL
            permissions_file: "".to_string(),
            default_permissions: vec![],
            audit_log_path: "".to_string(),
            audit_all_requests: false,
        };
        let audit = test_audit();
        let manager = SessionManager::new(&config, audit);

        let session_token = manager
            .authenticate("client", "test-token-12345-abcdefghij")
            .await
            .unwrap();

        // Wait for session to expire
        tokio::time::sleep(Duration::from_millis(1100)).await;
        let cleaned = manager.cleanup_expired().await;
        assert_eq!(cleaned, 1, "Should clean up 1 expired session");

        // Session should be invalid now
        let result = manager.validate_session(&session_token).await;
        assert!(result.is_err(), "Session should be invalid after cleanup");
    }

    #[tokio::test]
    async fn test_audit_logger_auth_success() {
        let audit = test_audit();
        audit
            .log_auth("127.0.0.1", true, "token-masked", "Auth successful".to_string())
            .await;

        let buffer = audit.get_buffer().await;
        assert_eq!(buffer.len(), 1);
        assert_eq!(buffer[0].client_id, "127.0.0.1");
        assert_eq!(buffer[0].message, "[token-masked] Auth successful");
    }

    #[tokio::test]
    async fn test_audit_logger_auth_failure() {
        let audit = test_audit();
        audit
            .log_auth("127.0.0.1", false, "bad-token", "Invalid token".to_string())
            .await;

        let buffer = audit.get_buffer().await;
        assert_eq!(buffer.len(), 1);
        assert!(buffer[0].error.is_some());
    }

    #[tokio::test]
    async fn test_audit_logger_permission_denied() {
        let audit = test_audit();
        audit
            .log_permission_denied(
                "client",
                Some("sess-token"),
                &Permission::ModelLoad,
                &[Permission::Status],
                "ModelLoad",
            )
            .await;

        let buffer = audit.get_buffer().await;
        assert_eq!(buffer.len(), 1);
        assert_eq!(buffer[0].event_type, AuditEventType::PermissionDenied);
    }

    #[tokio::test]
    async fn test_audit_logger_admin() {
        let audit = test_audit();
        audit
            .log_admin_operation("admin-client", Some("sess-token"), "token-rotate", "Rotated API token")
            .await;

        let buffer = audit.get_buffer().await;
        assert_eq!(buffer.len(), 1);
        assert_eq!(buffer[0].event_type, AuditEventType::AdminOperation);
    }

    #[tokio::test]
    async fn test_audit_stats() {
        let audit = test_audit();
        let stats = audit.stats();

        assert_eq!(stats.total_auth_attempts.load(Ordering::Relaxed), 0);

        audit.log_auth("c1", true, "t1", "OK".to_string()).await;
        audit.log_auth("c2", false, "t2", "FAIL".to_string()).await;

        assert_eq!(stats.total_auth_attempts.load(Ordering::Relaxed), 2);
        assert_eq!(stats.successful_auths.load(Ordering::Relaxed), 1);
        assert_eq!(stats.failed_auths.load(Ordering::Relaxed), 1);
    }

    #[tokio::test]
    async fn test_permission_from_message_type() {
        assert_eq!(
            Permission::from_message_type("Inference"),
            Some(Permission::Infer)
        );
        assert_eq!(
            Permission::from_message_type("ModelLoad"),
            Some(Permission::ModelLoad)
        );
        assert_eq!(
            Permission::from_message_type("Status"),
            Some(Permission::Status)
        );
        assert_eq!(Permission::from_message_type("Auth"), None);
        assert_eq!(Permission::from_message_type("Error"), None);
    }

    #[tokio::test]
    async fn test_permission_satisfied_by() {
        let granted = vec![Permission::Infer, Permission::Status];

        assert!(Permission::Infer.is_satisfied_by(&granted));
        assert!(Permission::Status.is_satisfied_by(&granted));
        assert!(!Permission::Admin.is_satisfied_by(&granted));
        assert!(!Permission::ModelLoad.is_satisfied_by(&granted));

        // All permission satisfies everything
        let all_granted = vec![Permission::All];
        assert!(Permission::Infer.is_satisfied_by(&all_granted));
        assert!(Permission::Admin.is_satisfied_by(&all_granted));
        assert!(Permission::ModelLoad.is_satisfied_by(&all_granted));
    }

    #[tokio::test]
    async fn test_session_manager_token_resolution() {
        // Test with valid token from config
        let config = test_config();
        let audit = test_audit();
        let manager = SessionManager::new(&config, audit);

        assert!(manager.has_token());
        assert!(manager.is_enabled());
        assert!(manager.masked_token().is_some());
    }

    #[tokio::test]
    async fn test_session_manager_no_token() {
        let config = AuthConfig {
            enabled: false,
            token: "".to_string(),
            token_path: "".to_string(),
            session_ttl_seconds: 3600,
            permissions_file: "".to_string(),
            default_permissions: vec![],
            audit_log_path: "".to_string(),
            audit_all_requests: false,
        };
        let audit = test_audit();
        let manager = SessionManager::new(&config, audit);

        assert!(!manager.has_token());
        assert!(!manager.is_enabled());
    }

    #[tokio::test]
    async fn test_session_manager_list_sessions() {
        let config = test_config();
        let audit = test_audit();
        let manager = SessionManager::new(&config, audit);

        manager
            .authenticate("client1", "test-token-12345-abcdefghij")
            .await
            .unwrap();
        manager
            .authenticate("client2", "test-token-12345-abcdefghij")
            .await
            .unwrap();

        let sessions = manager.list_sessions().await;
        assert_eq!(sessions.len(), 2);
    }

    #[tokio::test]
    async fn test_permission_defaults() {
        let unauthenticated = Permission::default_unauthenticated();
        assert_eq!(unauthenticated, vec![Permission::Status]);

        let authenticated = Permission::default_authenticated();
        assert!(authenticated.contains(&Permission::Infer));
        assert!(authenticated.contains(&Permission::Status));
        assert!(authenticated.contains(&Permission::Context));
        assert!(!authenticated.contains(&Permission::Admin));
    }

    #[tokio::test]
    async fn test_permission_serialization() {
        let perms = vec![Permission::Infer, Permission::Admin, Permission::All];
        let json = serde_json::to_string(&perms).unwrap();
        assert_eq!(json, r#"["infer","admin","all"]"#);

        let deserialized: Vec<Permission> = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.len(), 3);
        assert_eq!(deserialized[0], Permission::Infer);
        assert_eq!(deserialized[1], Permission::Admin);
        assert_eq!(deserialized[2], Permission::All);
    }

    #[tokio::test]
    async fn test_auth_request_response() {
        let req = AuthRequest {
            token: "my-token".to_string(),
        };
        let json = serde_json::to_string(&req).unwrap();
        assert_eq!(json, r#"{"token":"my-token"}"#);

        let resp = AuthResponse {
            success: true,
            session_token: Some("uuid-here".to_string()),
            message: "Authenticated".to_string(),
            permissions: vec!["infer".to_string(), "status".to_string()],
            session_ttl_seconds: 3600,
        };
        let resp_json = serde_json::to_string(&resp).unwrap();
        assert!(resp_json.contains("Authenticated"));
        assert!(resp_json.contains("infer"));
    }

    #[tokio::test]
    async fn test_session_manager_cleanup_task() {
        let config = AuthConfig {
            enabled: true,
            token: "test-token-12345-abcdefghij".to_string(),
            token_path: "".to_string(),
            session_ttl_seconds: 1, // 1 second TTL
            permissions_file: "".to_string(),
            default_permissions: vec![],
            audit_log_path: "".to_string(),
            audit_all_requests: false,
        };
        let audit = test_audit();
        let manager = Arc::new(SessionManager::new(&config, audit));

        manager
            .authenticate("client", "test-token-12345-abcdefghij")
            .await
            .unwrap();

        assert_eq!(manager.active_sessions().await, 1);

        // Wait for session to expire
        tokio::time::sleep(Duration::from_millis(1100)).await;

        // Clean up
        let cleaned = manager.cleanup_expired().await;
        assert_eq!(cleaned, 1);
        assert_eq!(manager.active_sessions().await, 0);
    }

    #[tokio::test]
    async fn test_session_touch() {
        let token = AuthToken::new("test".to_string());
        let mut session = Session::new(
            "client".to_string(),
            vec![Permission::Status],
            Duration::from_secs(3600),
            &token,
        );

        let old_last_activity = session.last_activity;
        tokio::time::sleep(Duration::from_millis(5)).await;
        session.touch();
        assert!(session.last_activity > old_last_activity);
    }

    #[tokio::test]
    async fn test_session_extend_ttl() {
        let token = AuthToken::new("test".to_string());
        let mut session = Session::new(
            "client".to_string(),
            vec![Permission::Status],
            Duration::from_secs(60),
            &token,
        );

        let old_ttl = session.time_to_live();
        session.extend_ttl(Duration::from_secs(3600));
        let new_ttl = session.time_to_live();
        assert!(new_ttl > old_ttl);
    }

    #[tokio::test]
    async fn test_audit_logger_rate_limit() {
        let audit = test_audit();
        audit
            .log_rate_limit("client", Some("sess"), "infer", Duration::from_secs(30))
            .await;

        let buffer = audit.get_buffer().await;
        assert_eq!(buffer.len(), 1);
        assert_eq!(buffer[0].event_type, AuditEventType::RateLimitExceeded);
    }

    #[tokio::test]
    async fn test_audit_logger_buffer_limit() {
        let audit = AuditLogger {
            max_buffer_size: 5,
            ..AuditLogger::new(None, false)
        };
        let audit = Arc::new(audit);

        for i in 0..10 {
            audit
                .log_auth("client", true, "token", format!("event {}", i))
                .await;
        }

        let buffer = audit.get_buffer().await;
        assert_eq!(buffer.len(), 5, "Buffer should be limited to 5 entries");
    }

    #[tokio::test]
    async fn test_permission_description() {
        assert_eq!(Permission::Infer.description(), "Inference requests");
        assert_eq!(Permission::Admin.description(), "Administrative operations");
        assert_eq!(Permission::All.description(), "All operations (super permission)");
    }

    #[tokio::test]
    async fn test_permission_all_permissions() {
        let all = Permission::all_permissions();
        assert_eq!(all.len(), 6);
        assert!(all.contains(&Permission::Infer));
        assert!(all.contains(&Permission::Admin));
    }

    #[tokio::test]
    async fn test_auth_error_messages() {
        let err = AuthError::InvalidToken;
        assert_eq!(format!("{}", err), "Invalid authentication token");

        let err = AuthError::AuthenticationRequired;
        assert_eq!(format!("{}", err), "Authentication required");

        let err = AuthError::PermissionDenied {
            required: Permission::Admin,
            granted: vec![Permission::Status],
        };
        let msg = format!("{}", err);
        assert!(msg.contains("Admin"));
        assert!(msg.contains("Status"));
    }

    #[tokio::test]
    async fn test_permission_from_str() {
        assert_eq!(permission_from_str("infer"), Some(Permission::Infer));
        assert_eq!(permission_from_str("ADMIN"), Some(Permission::Admin));
        assert_eq!(permission_from_str("unknown"), None);
    }

    #[tokio::test]
    async fn test_permission_to_str() {
        assert_eq!(permission_to_str(&Permission::Infer), "infer");
        assert_eq!(permission_to_str(&Permission::All), "all");
    }
}