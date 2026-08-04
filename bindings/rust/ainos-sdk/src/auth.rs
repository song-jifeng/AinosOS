//! Authentication and session management for the Ainos SDK.
//!
//! Provides token-based authentication, session token management, and
//! permission checking.  Sensitive tokens are secured with [`zeroize`].

use crate::error::{AinosError, Result};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::sync::RwLock;
use zeroize::Zeroize;

// ===========================================================================
// Credentials
// ===========================================================================

/// A bearer token used for authentication.
///
/// The token is zeroed on drop to prevent accidental leakage.
#[derive(Clone, Zeroize)]
#[zeroize(drop)]
pub struct BearerToken(String);

impl BearerToken {
    /// Create a new `BearerToken` from a string.
    pub fn new(token: impl Into<String>) -> Self {
        Self(token.into())
    }

    /// Return the token as a string slice.
    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// Return the token length.
    pub fn len(&self) -> usize {
        self.0.len()
    }

    /// Returns `true` if the token is empty.
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
}

impl std::fmt::Debug for BearerToken {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        if self.0.len() > 8 {
            write!(f, "BearerToken({}...)", &self.0[..8])
        } else {
            write!(f, "BearerToken(***)")
        }
    }
}

impl From<String> for BearerToken {
    fn from(s: String) -> Self {
        Self(s)
    }
}

impl From<&str> for BearerToken {
    fn from(s: &str) -> Self {
        Self(s.to_string())
    }
}

impl From<&String> for BearerToken {
    fn from(s: &String) -> Self {
        Self(s.clone())
    }
}

impl std::ops::Deref for BearerToken {
    type Target = str;

    fn deref(&self) -> &str {
        &self.0
    }
}

// ===========================================================================
// Session
// ===========================================================================

/// A session established after successful authentication.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Session {
    /// The session token for subsequent requests.
    pub session_token: String,
    /// Whether authentication was successful.
    pub success: bool,
    /// Human-readable message from the daemon.
    pub message: String,
    /// Permissions granted to this session.
    #[serde(default)]
    pub permissions: Vec<String>,
    /// Session TTL in seconds.
    #[serde(default)]
    pub session_ttl_seconds: u64,
    /// When this session was created (Unix timestamp).
    #[serde(default)]
    pub created_at: u64,
}

impl Session {
    /// Check if the session has expired.
    pub fn is_expired(&self) -> bool {
        if self.session_ttl_seconds == 0 {
            return false; // No expiry
        }
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        now > self.created_at + self.session_ttl_seconds
    }

    /// Check if the session has a specific permission.
    pub fn has_permission(&self, permission: &str) -> bool {
        self.permissions.is_empty() || self.permissions.iter().any(|p| p == permission)
    }

    /// Time remaining until the session expires.
    pub fn ttl_remaining(&self) -> Duration {
        if self.session_ttl_seconds == 0 {
            return Duration::from_secs(u64::MAX);
        }
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        let elapsed = now.saturating_sub(self.created_at);
        Duration::from_secs(self.session_ttl_seconds.saturating_sub(elapsed))
    }
}

// ===========================================================================
// Permission checking
// ===========================================================================

/// Permission constants matching the daemon's permission model.
pub mod permissions {
    /// Permission to perform inference.
    pub const INFER: &str = "infer";
    /// Permission to manage models (load/unload).
    pub const MODEL_OPS: &str = "model_ops";
    /// Permission to query status.
    pub const STATUS: &str = "status";
    /// Permission to store/retrieve context.
    pub const CONTEXT: &str = "context";
    /// Administrative permission.
    pub const ADMIN: &str = "admin";
    /// All permissions (wildcard).
    pub const ALL: &str = "*";
}

/// Check if a session has the required permission.
///
/// Returns `Ok(())` if the session has the permission, or an error describing
/// why the check failed.
pub fn check_permission(session: &Session, required: &str) -> Result<()> {
    // If session has no permissions (empty == all access), or has the "all" wildcard
    if session.permissions.is_empty() || session.permissions.iter().any(|p| p == permissions::ALL) {
        return Ok(());
    }

    if session.has_permission(required) {
        return Ok(());
    }

    Err(AinosError::PermissionDenied(format!(
        "Required permission: '{}', available: {:?}",
        required, session.permissions
    )))
}

// ===========================================================================
// Session manager (client-side)
// ===========================================================================

/// Manages session state on the client side.
///
/// Stores the current session token, handles re-authentication, and
/// provides permission checking.
#[derive(Clone)]
pub struct SessionManager {
    inner: Arc<RwLock<SessionManagerInner>>,
}

struct SessionManagerInner {
    /// The current session, if authenticated.
    session: Option<Session>,
    /// The bearer token used for authentication.
    bearer_token: Option<BearerToken>,
    /// Whether auth is enabled.
    enabled: bool,
}

impl SessionManager {
    /// Create a new `SessionManager`.
    pub fn new() -> Self {
        Self {
            inner: Arc::new(RwLock::new(SessionManagerInner {
                session: None,
                bearer_token: None,
                enabled: true,
            })),
        }
    }

    /// Create a new `SessionManager` with a bearer token.
    pub fn with_token(token: impl Into<BearerToken>) -> Self {
        Self {
            inner: Arc::new(RwLock::new(SessionManagerInner {
                session: None,
                bearer_token: Some(token.into()),
                enabled: true,
            })),
        }
    }

    /// Disable authentication (for daemons that don't require it).
    pub fn disabled() -> Self {
        Self {
            inner: Arc::new(RwLock::new(SessionManagerInner {
                session: None,
                bearer_token: None,
                enabled: false,
            })),
        }
    }

    /// Set the bearer token.
    pub async fn set_token(&self, token: impl Into<BearerToken>) {
        let mut inner = self.inner.write().await;
        inner.bearer_token = Some(token.into());
    }

    /// Get the bearer token, if set.
    pub async fn bearer_token(&self) -> Option<BearerToken> {
        let inner = self.inner.read().await;
        inner.bearer_token.clone()
    }

    /// Update the session after successful authentication.
    pub async fn set_session(&self, session: Session) {
        let mut inner = self.inner.write().await;
        inner.session = Some(session);
    }

    /// Get the current session, if authenticated.
    pub async fn session(&self) -> Option<Session> {
        let inner = self.inner.read().await;
        inner.session.clone()
    }

    /// Get the session token string, if authenticated.
    pub async fn session_token(&self) -> Option<String> {
        let inner = self.inner.read().await;
        inner.session.as_ref().map(|s| s.session_token.clone())
    }

    /// Clear the current session (e.g. on disconnect or expiry).
    pub async fn clear_session(&self) {
        let mut inner = self.inner.write().await;
        inner.session = None;
    }

    /// Check if the client is authenticated.
    pub async fn is_authenticated(&self) -> bool {
        let inner = self.inner.read().await;
        inner.session.as_ref().map(|s| s.success).unwrap_or(false)
    }

    /// Check if authentication is enabled.
    pub async fn is_enabled(&self) -> bool {
        let inner = self.inner.read().await;
        inner.enabled
    }

    /// Check if the session has expired.
    pub async fn is_expired(&self) -> bool {
        let inner = self.inner.read().await;
        inner
            .session
            .as_ref()
            .map(|s| s.is_expired())
            .unwrap_or(true)
    }

    /// Check if the current session has a specific permission.
    pub async fn check_permission(&self, permission: &str) -> Result<()> {
        let inner = self.inner.read().await;
        if !inner.enabled {
            return Ok(());
        }
        match inner.session.as_ref() {
            Some(session) => check_permission(session, permission),
            None => Err(AinosError::AuthFailed(
                "Not authenticated".to_string(),
            )),
        }
    }

    /// Get the list of granted permissions.
    pub async fn permissions(&self) -> Vec<String> {
        let inner = self.inner.read().await;
        inner
            .session
            .as_ref()
            .map(|s| s.permissions.clone())
            .unwrap_or_default()
    }

    /// Clear all state (token + session).
    pub async fn clear_all(&self) {
        let mut inner = self.inner.write().await;
        inner.session = None;
        inner.bearer_token = None;
    }

    /// Build the authentication IPC message.
    pub(crate) async fn build_auth_message(&self) -> Option<crate::types::IpcMessage> {
        let inner = self.inner.read().await;
        inner.bearer_token.as_ref().map(|token| {
            crate::types::IpcMessage::Auth {
                token: token.as_str().to_string(),
            }
        })
    }
}

impl Default for SessionManager {
    fn default() -> Self {
        Self::new()
    }
}

impl std::fmt::Debug for SessionManager {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SessionManager").finish_non_exhaustive()
    }
}

// ===========================================================================
// Secure token storage
// ===========================================================================

/// A secure container for sensitive string data.
///
/// Automatically zeroes the contents on drop. Use this for API keys,
/// tokens, and other secrets that should not remain in memory.
#[derive(Clone, Zeroize)]
#[zeroize(drop)]
pub struct SecureString(String);

impl SecureString {
    /// Create a new `SecureString`.
    pub fn new(value: impl Into<String>) -> Self {
        Self(value.into())
    }

    /// Return the value as a string slice.
    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// Returns `true` if the string is empty.
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    /// Return the length of the string.
    pub fn len(&self) -> usize {
        self.0.len()
    }
}

impl std::fmt::Debug for SecureString {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("SecureString(***)")
    }
}

impl From<String> for SecureString {
    fn from(s: String) -> Self {
        Self(s)
    }
}

impl From<&str> for SecureString {
    fn from(s: &str) -> Self {
        Self(s.to_string())
    }
}

impl std::ops::Deref for SecureString {
    type Target = str;

    fn deref(&self) -> &str {
        &self.0
    }
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_bearer_token_zeroize() {
        let token = BearerToken::new("my-secret-token-12345");
        assert_eq!(token.as_str(), "my-secret-token-12345");
        // On drop, the memory should be zeroed
        drop(token);
    }

    #[test]
    fn test_secure_string_debug() {
        let s = SecureString::new("secret-value");
        assert_eq!(format!("{:?}", s), "SecureString(***)");
    }

    #[test]
    fn test_session_expiry() {
        let session = Session {
            session_token: "tok_123".into(),
            success: true,
            message: "OK".into(),
            permissions: vec!["infer".into()],
            session_ttl_seconds: 3600,
            created_at: 0, // epoch
        };
        // Created at epoch, so it should be expired
        assert!(session.is_expired());
    }

    #[test]
    fn test_session_no_expiry() {
        let session = Session {
            session_token: "tok_123".into(),
            success: true,
            message: "OK".into(),
            permissions: vec!["infer".into()],
            session_ttl_seconds: 0, // no expiry
            created_at: 0,
        };
        assert!(!session.is_expired());
    }

    #[test]
    fn test_session_has_permission() {
        let session = Session {
            session_token: "tok_123".into(),
            success: true,
            message: "OK".into(),
            permissions: vec!["infer".into(), "status".into()],
            session_ttl_seconds: 3600,
            created_at: 1000,
        };
        assert!(session.has_permission("infer"));
        assert!(session.has_permission("status"));
        assert!(!session.has_permission("admin"));
    }

    #[test]
    fn test_empty_permissions_means_all() {
        let session = Session {
            session_token: "tok_123".into(),
            success: true,
            message: "OK".into(),
            permissions: vec![], // empty means all
            session_ttl_seconds: 3600,
            created_at: 1000,
        };
        assert!(session.has_permission("anything"));
    }

    #[test]
    fn test_check_permission_ok() {
        let session = Session {
            session_token: "tok_123".into(),
            success: true,
            message: "OK".into(),
            permissions: vec!["infer".into()],
            session_ttl_seconds: 3600,
            created_at: 1000,
        };
        assert!(check_permission(&session, "infer").is_ok());
        assert!(check_permission(&session, "admin").is_err());
    }

    #[tokio::test]
    async fn test_session_manager() {
        let mgr = SessionManager::with_token("test-token");

        assert!(mgr.is_enabled().await);

        let session = Session {
            session_token: "tok_abc".into(),
            success: true,
            message: "OK".into(),
            permissions: vec!["infer".into()],
            session_ttl_seconds: 3600,
            created_at: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_secs(),
        };

        mgr.set_session(session).await;
        assert!(mgr.is_authenticated().await);
        assert!(!mgr.is_expired().await);

        assert!(mgr.check_permission("infer").await.is_ok());
        assert!(mgr.check_permission("admin").await.is_err());

        mgr.clear_session().await;
        assert!(!mgr.is_authenticated().await);
    }

    #[tokio::test]
    async fn test_session_manager_token() {
        let mgr = SessionManager::new();
        assert!(mgr.bearer_token().await.is_none());

        mgr.set_token("my-token").await;
        let token = mgr.bearer_token().await;
        assert!(token.is_some());
        assert_eq!(token.unwrap().as_str(), "my-token");
    }

    #[test]
    fn test_ttl_remaining() {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs();
        let session = Session {
            session_token: "tok".into(),
            success: true,
            message: "OK".into(),
            permissions: vec![],
            session_ttl_seconds: 3600,
            created_at: now,
        };
        let remaining = session.ttl_remaining();
        assert!(remaining.as_secs() <= 3600);
        assert!(remaining.as_secs() > 3590); // within ~10 seconds
    }

    #[test]
    fn test_bearer_token_debug() {
        let token = BearerToken::new("this-is-a-long-token-value");
        let debug_str = format!("{:?}", token);
        assert!(debug_str.starts_with("BearerToken(this-is"));
        assert!(debug_str.ends_with("...)"));

        let short = BearerToken::new("short");
        let debug_short = format!("{:?}", short);
        assert_eq!(debug_short, "BearerToken(***)");
    }
}