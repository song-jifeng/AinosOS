//! Error types for the Ainos SDK.
//!
//! This module defines the [`AinosError`] enum with all error variants that can
//! arise from SDK operations, conversion helpers, and retry classification.

use std::time::Duration;

/// Alias for `Result<T, AinosError>`.
pub type Result<T> = std::result::Result<T, AinosError>;

/// Unified error type for all Ainos SDK operations.
///
/// Every fallible method on [`AinosClient`](crate::client::AinosClient) returns
/// `Result<T>` where the error is this enum.
#[derive(Debug, thiserror::Error)]
pub enum AinosError {
    // ── Connection ──────────────────────────────────────────────────────────

    /// Could not establish a TCP connection to the daemon.
    #[error("Connection refused: {0}")]
    ConnectionRefused(String),

    /// The connection was lost during an operation.
    #[error("Connection lost: {0}")]
    ConnectionLost(String),

    /// The daemon closed the connection unexpectedly.
    #[error("Connection closed by peer")]
    ConnectionClosed,

    /// DNS resolution failed.
    #[error("DNS resolution failed for {0}")]
    DnsResolutionFailed(String),

    // ── Timeout ─────────────────────────────────────────────────────────────

    /// The operation exceeded the configured timeout.
    #[error("Operation timed out after {0:?}")]
    Timeout(Duration),

    // ── Authentication ──────────────────────────────────────────────────────

    /// Authentication with the daemon failed.
    #[error("Authentication failed: {0}")]
    AuthFailed(String),

    /// The session token has expired; re-authentication is required.
    #[error("Session expired")]
    SessionExpired,

    /// The caller does not have the required permission.
    #[error("Permission denied: {0}")]
    PermissionDenied(String),

    // ── Protocol ────────────────────────────────────────────────────────────

    /// The daemon returned an error response.
    #[error("Daemon error (code={code}): {message}")]
    DaemonError {
        /// Numeric error code from the daemon.
        code: i32,
        /// Human-readable error message.
        message: String,
    },

    /// The response from the daemon could not be deserialized.
    #[error("Protocol error: {0}")]
    Protocol(String),

    /// Unexpected response type from the daemon.
    #[error("Unexpected response type: {0}")]
    UnexpectedResponse(String),

    // ── Serialization ───────────────────────────────────────────────────────

    /// JSON serialization or deserialization failed.
    #[error("Serialization error: {0}")]
    Serialization(String),

    // ── Inference ───────────────────────────────────────────────────────────

    /// The inference request was rejected by the daemon.
    #[error("Inference error: {0}")]
    Inference(String),

    /// The requested model was not found.
    #[error("Model not found: {0}")]
    ModelNotFound(String),

    /// The model is not loaded.
    #[error("Model not loaded: {0}")]
    ModelNotLoaded(String),

    // ── Rate Limit ──────────────────────────────────────────────────────────

    /// The request was rate-limited.
    #[error("Rate limit exceeded: {0}")]
    RateLimited(String),

    // ── Internal ────────────────────────────────────────────────────────────

    /// An internal error occurred (e.g. channel closed, mutex poisoned).
    #[error("Internal error: {0}")]
    Internal(String),

    /// An I/O error occurred.
    #[error("I/O error: {0}")]
    Io(String),

    /// TLS / SSL error.
    #[cfg(feature = "tls")]
    #[error("TLS error: {0}")]
    Tls(String),
}

// ---------------------------------------------------------------------------
// Conversion helpers
// ---------------------------------------------------------------------------

impl From<std::io::Error> for AinosError {
    fn from(e: std::io::Error) -> Self {
        AinosError::Io(e.to_string())
    }
}

impl From<serde_json::Error> for AinosError {
    fn from(e: serde_json::Error) -> Self {
        AinosError::Serialization(e.to_string())
    }
}

impl From<std::time::SystemTimeError> for AinosError {
    fn from(e: std::time::SystemTimeError) -> Self {
        AinosError::Internal(e.to_string())
    }
}

// ---------------------------------------------------------------------------
// Retry classification
// ---------------------------------------------------------------------------

/// Whether an error is retryable.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RetryKind {
    /// The operation can be retried immediately.
    Transient,
    /// The operation can be retried after a delay.
    Throttled,
    /// The operation should not be retried (fatal).
    Fatal,
}

/// Extension trait for classifying errors for retry logic.
pub trait Retryable {
    /// Classify this error for retry decisions.
    fn retry_kind(&self) -> RetryKind;
}

impl Retryable for AinosError {
    fn retry_kind(&self) -> RetryKind {
        match self {
            // Transient — can retry
            AinosError::ConnectionRefused(_)
            | AinosError::ConnectionLost(_)
            | AinosError::ConnectionClosed
            | AinosError::Timeout(_)
            | AinosError::RateLimited(_) => RetryKind::Transient,

            // Throttled — retry after backoff
            AinosError::DaemonError { code: 429, .. } => RetryKind::Throttled,

            // Fatal — don't retry
            AinosError::AuthFailed(_)
            | AinosError::SessionExpired
            | AinosError::PermissionDenied(_)
            | AinosError::Protocol(_)
            | AinosError::UnexpectedResponse(_)
            | AinosError::Serialization(_)
            | AinosError::ModelNotFound(_)
            | AinosError::DaemonError { .. } => RetryKind::Fatal,

            // Default to fatal for unknown cases
            _ => RetryKind::Fatal,
        }
    }
}

// ---------------------------------------------------------------------------
// Builder helpers
// ---------------------------------------------------------------------------

/// Default retry configuration.
#[derive(Debug, Clone)]
pub struct RetryConfig {
    /// Maximum number of retry attempts.
    pub max_retries: u32,
    /// Initial backoff duration.
    pub initial_backoff: Duration,
    /// Maximum backoff duration.
    pub max_backoff: Duration,
    /// Backoff multiplier (applied after each attempt).
    pub backoff_multiplier: f64,
}

impl Default for RetryConfig {
    fn default() -> Self {
        Self {
            max_retries: 3,
            initial_backoff: Duration::from_millis(100),
            max_backoff: Duration::from_secs(10),
            backoff_multiplier: 2.0,
        }
    }
}

impl RetryConfig {
    /// Compute the backoff duration for a given attempt number (0-based).
    pub fn backoff(&self, attempt: u32) -> Duration {
        let base = self.initial_backoff.as_secs_f64() * self.backoff_multiplier.powi(attempt as i32);
        let clamped = base.min(self.max_backoff.as_secs_f64());
        Duration::from_secs_f64(clamped)
    }
}

// ---------------------------------------------------------------------------
// Error classification helpers
// ---------------------------------------------------------------------------

impl AinosError {
    /// Returns `true` if this error is related to authentication.
    pub fn is_auth_error(&self) -> bool {
        matches!(
            self,
            AinosError::AuthFailed(_) | AinosError::SessionExpired | AinosError::PermissionDenied(_)
        )
    }

    /// Returns `true` if this error is related to connectivity.
    pub fn is_connection_error(&self) -> bool {
        matches!(
            self,
            AinosError::ConnectionRefused(_)
                | AinosError::ConnectionLost(_)
                | AinosError::ConnectionClosed
                | AinosError::DnsResolutionFailed(_)
        )
    }

    /// Returns `true` if this error is a timeout.
    pub fn is_timeout(&self) -> bool {
        matches!(self, AinosError::Timeout(_))
    }

    /// Returns `true` if this error is a rate limit.
    pub fn is_rate_limited(&self) -> bool {
        matches!(self, AinosError::RateLimited(_))
    }

    /// Extract the daemon error code, if applicable.
    pub fn daemon_code(&self) -> Option<i32> {
        if let AinosError::DaemonError { code, .. } = self {
            Some(*code)
        } else {
            None
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_retry_kind_transient() {
        assert_eq!(
            AinosError::ConnectionRefused("refused".into()).retry_kind(),
            RetryKind::Transient
        );
        assert_eq!(
            AinosError::ConnectionLost("lost".into()).retry_kind(),
            RetryKind::Transient
        );
        assert_eq!(AinosError::ConnectionClosed.retry_kind(), RetryKind::Transient);
        assert_eq!(
            AinosError::Timeout(Duration::from_secs(5)).retry_kind(),
            RetryKind::Transient
        );
        assert_eq!(
            AinosError::RateLimited("too many".into()).retry_kind(),
            RetryKind::Transient
        );
    }

    #[test]
    fn test_retry_kind_fatal() {
        assert_eq!(
            AinosError::AuthFailed("bad token".into()).retry_kind(),
            RetryKind::Fatal
        );
        assert_eq!(
            AinosError::Protocol("bad json".into()).retry_kind(),
            RetryKind::Fatal
        );
        assert_eq!(
            AinosError::DaemonError {
                code: 500,
                message: "internal".into()
            }
            .retry_kind(),
            RetryKind::Fatal
        );
    }

    #[test]
    fn test_retry_config_backoff() {
        let cfg = RetryConfig::default();
        assert_eq!(cfg.backoff(0), Duration::from_millis(100));
        assert_eq!(cfg.backoff(1), Duration::from_millis(200));
        assert_eq!(cfg.backoff(2), Duration::from_millis(400));
    }

    #[test]
    fn test_error_classification() {
        let err = AinosError::AuthFailed("bad".into());
        assert!(err.is_auth_error());
        assert!(!err.is_connection_error());
        assert!(!err.is_timeout());

        let err = AinosError::ConnectionLost("lost".into());
        assert!(err.is_connection_error());
        assert!(!err.is_auth_error());

        let err = AinosError::Timeout(Duration::from_secs(1));
        assert!(err.is_timeout());
    }

    #[test]
    fn test_daemon_code() {
        let err = AinosError::DaemonError {
            code: 429,
            message: "rate limited".into(),
        };
        assert_eq!(err.daemon_code(), Some(429));
        assert_eq!(AinosError::ConnectionClosed.daemon_code(), None);
    }
}