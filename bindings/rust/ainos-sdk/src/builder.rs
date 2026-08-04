//! Builder pattern for [`AinosClient`] and request types.
//!
//! Provides fluent builders for constructing the client and all request
//! types with a consistent API.

use crate::auth::{BearerToken, SessionManager};
use crate::error::RetryConfig;
use crate::types::{ClientConfig, InferenceRequest, InferenceRequestBuilder, ModelLoadOptions, ModelLoadOptionsBuilder};
use std::time::Duration;

// ===========================================================================
// Client builder
// ===========================================================================

/// Builder for constructing an [`AinosClient`](crate::client::AinosClient).
///
/// # Example
///
/// ```no_run
/// # use ainos_sdk::AinosClient;
/// # async fn example() -> Result<(), ainos_sdk::error::AinosError> {
/// let client = AinosClient::builder()
///     .host("192.168.1.100")
///     .port(9500)
///     .auth_token("my-token")
///     .connect_timeout(std::time::Duration::from_secs(10))
///     .read_timeout(std::time::Duration::from_secs(60))
///     .auto_reconnect(true)
///     .build();
/// client.connect().await?;
/// # Ok(())
/// # }
/// ```
#[derive(Debug, Clone)]
pub struct AinosClientBuilder {
    /// Daemon hostname or IP address.
    host: Option<String>,
    /// Daemon TCP port.
    port: Option<u16>,
    /// Connection timeout.
    connect_timeout: Option<Duration>,
    /// Read timeout for operations.
    read_timeout: Option<Duration>,
    /// Whether to auto-reconnect on connection failure.
    auto_reconnect: Option<bool>,
    /// Delay before reconnect attempt.
    reconnect_delay: Option<Duration>,
    /// Optional bearer token for authentication.
    auth_token: Option<String>,
    /// Whether to auto-authenticate after connecting.
    auto_authenticate: Option<bool>,
    /// Retry configuration.
    retry_config: Option<RetryConfig>,
    /// Maximum line length for NDJSON responses.
    max_line_length: Option<usize>,
}

impl Default for AinosClientBuilder {
    fn default() -> Self {
        Self::new()
    }
}

impl AinosClientBuilder {
    /// Create a new `AinosClientBuilder` with default values.
    pub fn new() -> Self {
        Self {
            host: None,
            port: None,
            connect_timeout: None,
            read_timeout: None,
            auto_reconnect: None,
            reconnect_delay: None,
            auth_token: None,
            auto_authenticate: None,
            retry_config: None,
            max_line_length: None,
        }
    }

    /// Set the daemon hostname or IP address.
    ///
    /// Default: `"127.0.0.1"`
    pub fn host(mut self, host: impl Into<String>) -> Self {
        self.host = Some(host.into());
        self
    }

    /// Set the daemon TCP port.
    ///
    /// Default: `9500`
    pub fn port(mut self, port: u16) -> Self {
        self.port = Some(port);
        self
    }

    /// Set the daemon address as `host:port`.
    ///
    /// This is a convenience method that sets both host and port from a
    /// single string like `"127.0.0.1:9500"`.
    ///
    /// # Panics
    ///
    /// Panics if the address does not contain a `:` separator.
    pub fn addr(mut self, addr: &str) -> Self {
        if let Some((host, port_str)) = addr.split_once(':') {
            self.host = Some(host.to_string());
            self.port = Some(port_str.parse().expect("Invalid port number"));
        } else {
            panic!("AinosClientBuilder::addr: address must be in host:port format");
        }
        self
    }

    /// Set the connection timeout.
    ///
    /// Default: 5 seconds
    pub fn connect_timeout(mut self, timeout: Duration) -> Self {
        self.connect_timeout = Some(timeout);
        self
    }

    /// Set the read timeout for operations.
    ///
    /// Default: 120 seconds
    pub fn read_timeout(mut self, timeout: Duration) -> Self {
        self.read_timeout = Some(timeout);
        self
    }

    /// Enable or disable auto-reconnect on connection failure.
    ///
    /// Default: `true`
    pub fn auto_reconnect(mut self, auto_reconnect: bool) -> Self {
        self.auto_reconnect = Some(auto_reconnect);
        self
    }

    /// Set the delay before reconnect attempt.
    ///
    /// Default: 1 second
    pub fn reconnect_delay(mut self, delay: Duration) -> Self {
        self.reconnect_delay = Some(delay);
        self
    }

    /// Set the bearer token for authentication.
    ///
    /// If set, the client will automatically authenticate after connecting.
    pub fn auth_token(mut self, token: impl Into<String>) -> Self {
        self.auth_token = Some(token.into());
        self
    }

    /// Enable or disable auto-authentication after connecting.
    ///
    /// Default: `true` (only effective if `auth_token` is set)
    pub fn auto_authenticate(mut self, auto_authenticate: bool) -> Self {
        self.auto_authenticate = Some(auto_authenticate);
        self
    }

    /// Set the retry configuration.
    pub fn retry_config(mut self, config: RetryConfig) -> Self {
        self.retry_config = Some(config);
        self
    }

    /// Set the maximum line length for NDJSON responses.
    ///
    /// Default: 1 MB
    pub fn max_line_length(mut self, max_line_length: usize) -> Self {
        self.max_line_length = Some(max_line_length);
        self
    }

    /// Build the [`ClientConfig`] from the builder's settings.
    pub fn build_config(&self) -> ClientConfig {
        let defaults = ClientConfig::default();
        ClientConfig {
            host: self.host.clone().unwrap_or(defaults.host),
            port: self.port.unwrap_or(defaults.port),
            connect_timeout: self.connect_timeout.unwrap_or(defaults.connect_timeout),
            read_timeout: self.read_timeout.unwrap_or(defaults.read_timeout),
            auto_reconnect: self.auto_reconnect.unwrap_or(defaults.auto_reconnect),
            reconnect_delay: self.reconnect_delay.unwrap_or(defaults.reconnect_delay),
            auth_token: self.auth_token.clone().or(defaults.auth_token),
            auto_authenticate: self.auto_authenticate.unwrap_or(defaults.auto_authenticate),
            retry_config: self.retry_config.clone().unwrap_or(defaults.retry_config),
            max_line_length: self.max_line_length.unwrap_or(defaults.max_line_length),
        }
    }

    /// Build the [`AinosClient`](crate::client::AinosClient).
    ///
    /// This does not connect to the daemon; call [`connect`](crate::client::AinosClient::connect)
    /// separately.
    pub fn build(&self) -> crate::client::AinosClient {
        let config = self.build_config();
        let session_manager = match &config.auth_token {
            Some(token) => SessionManager::with_token(BearerToken::new(token)),
            None => SessionManager::new(),
        };

        crate::client::AinosClient::with_config(config, session_manager)
    }
}

// ===========================================================================
// Re-export builders
// ===========================================================================

/// Convenience function to create an [`InferenceRequestBuilder`].
pub fn inference_request() -> InferenceRequestBuilder {
    InferenceRequest::builder()
}

/// Convenience function to create a [`ModelLoadOptionsBuilder`].
pub fn model_load_options() -> ModelLoadOptionsBuilder {
    ModelLoadOptions::builder()
}

// ===========================================================================
// Tests
// ===========================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_builder_defaults() {
        let config = AinosClientBuilder::new().build_config();
        assert_eq!(config.host, "127.0.0.1");
        assert_eq!(config.port, 9500);
        assert_eq!(config.connect_timeout, Duration::from_secs(5));
        assert!(config.auto_reconnect);
    }

    #[test]
    fn test_builder_custom() {
        let config = AinosClientBuilder::new()
            .host("192.168.1.1")
            .port(9501)
            .connect_timeout(Duration::from_secs(10))
            .read_timeout(Duration::from_secs(30))
            .auto_reconnect(false)
            .auth_token("my-token")
            .build_config();

        assert_eq!(config.host, "192.168.1.1");
        assert_eq!(config.port, 9501);
        assert_eq!(config.connect_timeout, Duration::from_secs(10));
        assert_eq!(config.read_timeout, Duration::from_secs(30));
        assert!(!config.auto_reconnect);
        assert_eq!(config.auth_token, Some("my-token".into()));
    }

    #[test]
    fn test_builder_addr() {
        let config = AinosClientBuilder::new()
            .addr("10.0.0.1:9500")
            .build_config();
        assert_eq!(config.host, "10.0.0.1");
        assert_eq!(config.port, 9500);
    }

    #[test]
    fn test_builder_with_auth_token() {
        let config = AinosClientBuilder::new()
            .auth_token("my-secret-token")
            .build_config();
        assert_eq!(config.auth_token, Some("my-secret-token".into()));
        assert!(config.auto_authenticate); // default
    }

    #[test]
    fn test_builder_auto_authenticate_off() {
        let config = AinosClientBuilder::new()
            .auth_token("token")
            .auto_authenticate(false)
            .build_config();
        assert!(!config.auto_authenticate);
    }

    #[test]
    fn test_inference_request_shortcut() {
        let builder = inference_request();
        let req = builder.prompt("Hello").build();
        assert_eq!(req.prompt, "Hello");
    }

    #[test]
    fn test_model_load_options_shortcut() {
        let builder = model_load_options();
        let opts = builder.path("/model.gguf").gpu_layers(32).build();
        assert_eq!(opts.path, "/model.gguf");
        assert_eq!(opts.gpu_layers, Some(32));
    }

    #[test]
    #[should_panic(expected = "InferenceRequest: prompt is required")]
    fn test_inference_request_missing_prompt() {
        InferenceRequest::builder().build();
    }

    #[test]
    #[should_panic(expected = "ModelLoadOptions: path is required")]
    fn test_model_load_missing_path() {
        ModelLoadOptions::builder().build();
    }

    #[test]
    #[should_panic(expected = "host:port format")]
    fn test_builder_addr_invalid() {
        AinosClientBuilder::new().addr("invalid-address");
    }

    #[test]
    fn test_builder_max_line_length() {
        let config = AinosClientBuilder::new()
            .max_line_length(2048)
            .build_config();
        assert_eq!(config.max_line_length, 2048);
    }
}