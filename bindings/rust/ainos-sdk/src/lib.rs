//! # Ainos SDK — Rust client for the Ainos AI Daemon
//!
//! A complete async SDK for communicating with the Ainos AI Daemon over
//! TCP/IP using the newline-delimited JSON (NDJSON) protocol.
//!
//! ## Quick Start
//!
//! ```no_run
//! use ainos_sdk::{AinosClient, InferenceRequest};
//!
//! # async fn example() -> Result<(), ainos_sdk::error::AinosError> {
//! let client = AinosClient::builder()
//!     .host("127.0.0.1")
//!     .port(9500)
//!     .auth_token("your-token")
//!     .build();
//!
//! client.connect().await?;
//!
//! let resp = client.infer(&InferenceRequest::builder()
//!     .prompt("Hello, Ainos!")
//!     .temperature(0.7)
//!     .max_tokens(512)
//!     .build()
//! ).await?;
//!
//! println!("{}", resp.output);
//!
//! client.disconnect().await?;
//! # Ok(())
//! # }
//! ```
//!
//! ## Feature Flags
//!
//! - `full` — All features enabled (default).
//! - `streaming` — Streaming inference support.
//! - `tls` — TLS encrypted transport.
//! - `mock` — Mock transport for testing.

// ---------------------------------------------------------------------------
// Version constant
// ---------------------------------------------------------------------------

/// The current version of the Ainos SDK crate.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

// ---------------------------------------------------------------------------
// Public modules
// ---------------------------------------------------------------------------

/// Authentication and session management.
pub mod auth;
/// Builder pattern for client and requests.
pub mod builder;
/// The main `AinosClient` implementation.
pub mod client;
/// Error types and retry logic.
pub mod error;
/// Streaming inference support.
pub mod streaming;
/// Transport layer (TCP, Unix, mock).
pub mod transport;
/// All data types for the IPC protocol.
pub mod types;

// ---------------------------------------------------------------------------
// Re-exports
// ---------------------------------------------------------------------------

pub use auth::{BearerToken, Session as AuthSession, SessionManager, SecureString};
pub use builder::AinosClientBuilder;
pub use client::AinosClient;
pub use error::{AinosError, RetryConfig, RetryKind};
pub use streaming::InferenceStream;
pub use types::{
    ClientConfig, ContextEntry, HealthStatus, InferenceChunk, InferenceRequest,
    InferenceRequestBuilder, InferenceResponse, IpcMessage, ModelInfo, ModelLoadOptions,
    ModelLoadOptionsBuilder, ModelLoadResponse, ModelUnloadResponse, RateLimitInfo,
    RateLimitStatus, Session, SystemStatus,
};

// ---------------------------------------------------------------------------
// Prelude
// ---------------------------------------------------------------------------

/// The Ainos SDK prelude.
///
/// Import this module to bring all commonly-used types into scope:
///
/// ```
/// use ainos_sdk::prelude::*;
/// ```
pub mod prelude {
    pub use crate::error::Result;
    pub use crate::{
        AinosClient, AinosClientBuilder, AinosError, ClientConfig, HealthStatus, InferenceChunk,
        InferenceRequest, InferenceRequestBuilder, InferenceResponse, InferenceStream, ModelInfo,
        ModelLoadOptions, ModelLoadOptionsBuilder, ModelLoadResponse, ModelUnloadResponse,
        RateLimitInfo, RateLimitStatus, Session, SystemStatus,
    };
    pub use futures::StreamExt;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_version_is_set() {
        assert!(!VERSION.is_empty());
    }

    #[test]
    fn test_prelude_imports() {
        // Just verify the prelude compiles
        use prelude::*;
        let _ = std::any::type_name::<Result<()>>();
    }

    #[test]
    fn test_ipc_message_roundtrip() {
        use types::IpcMessage;
        let msg = IpcMessage::Status;
        let json = serde_json::to_string(&msg).unwrap();
        let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
        match deserialized {
            IpcMessage::Status => {} // expected
            _ => panic!("Expected Status"),
        }
    }
}