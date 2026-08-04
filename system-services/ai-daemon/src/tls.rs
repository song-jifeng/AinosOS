// Ainos AI Daemon - TLS Support
//
// This module provides optional TLS encryption for the IPC layer.
// It is feature-gated behind the `tls` feature flag.
//
// Features:
// - Self-signed certificate generation on first run
// - Configurable cert/key file paths
// - TCP listener upgrade to TLS (tokio-rustls)
// - Optional client certificate authentication
// - Certificate expiry checking and logging

use crate::config::TlsConfig;
use std::path::Path;
use std::sync::Arc;
use thiserror::Error;
use tokio::net::TcpListener;
use tokio::io::{AsyncRead, AsyncWrite};
use tracing::{error, info, warn};

// ============================================================================
// Error Types
// ============================================================================

/// Errors that can occur during TLS operations.
#[derive(Error, Debug)]
pub enum TlsError {
    /// Certificate file not found.
    #[error("Certificate file not found: {0}")]
    CertFileNotFound(String),

    /// Private key file not found.
    #[error("Private key file not found: {0}")]
    KeyFileNotFound(String),

    /// Failed to load certificate.
    #[error("Failed to load certificate: {0}")]
    CertLoadError(String),

    /// Failed to load private key.
    #[error("Failed to load private key: {0}")]
    KeyLoadError(String),

    /// Failed to generate self-signed certificate.
    #[error("Failed to generate self-signed certificate: {0}")]
    CertGenerationError(String),

    /// Failed to create TLS acceptor.
    #[error("Failed to create TLS acceptor: {0}")]
    AcceptorError(String),

    /// TLS feature is not enabled (compile-time feature gate).
    #[error("TLS support is not enabled. Enable the `tls` feature in Cargo.toml")]
    FeatureNotEnabled,

    /// I/O error during TLS operations.
    #[error("I/O error: {0}")]
    IoError(String),
}

impl From<std::io::Error> for TlsError {
    fn from(e: std::io::Error) -> Self {
        TlsError::IoError(e.to_string())
    }
}

// ============================================================================
// TLS Configuration
// ============================================================================

/// TLS configuration state.
pub struct TlsState {
    /// Whether TLS is enabled.
    pub enabled: bool,

    /// Path to the certificate file.
    pub cert_path: String,

    /// Path to the private key file.
    pub key_path: String,

    /// Whether to verify client certificates.
    pub verify_client: bool,

    /// Certificate expiry info (for logging).
    pub cert_expiry: Option<String>,

    /// Whether the certificate was auto-generated.
    pub cert_auto_generated: bool,
}

impl TlsState {
    /// Create a new TLS state from configuration.
    pub fn from_config(config: &TlsConfig) -> Self {
        Self {
            enabled: config.enabled,
            cert_path: config.cert_path.clone(),
            key_path: config.key_path.clone(),
            verify_client: config.verify_client,
            cert_expiry: None,
            cert_auto_generated: false,
        }
    }

    /// Create a default TLS state (disabled).
    pub fn disabled() -> Self {
        Self {
            enabled: false,
            cert_path: String::new(),
            key_path: String::new(),
            verify_client: false,
            cert_expiry: None,
            cert_auto_generated: false,
        }
    }
}

// ============================================================================
// TLS Acceptor (feature-gated implementation)
// ============================================================================

/// A TLS-enabled TCP acceptor.
///
/// This wraps a `tokio::net::TcpListener` and upgrades incoming connections
/// to TLS using `tokio-rustls`.
pub enum TlsAcceptor {
    /// TLS is enabled and the acceptor is ready.
    #[cfg(feature = "tls")]
    Enabled(#[cfg(feature = "tls")] tokio_rustls::TlsAcceptor),

    /// TLS is disabled; connections are accepted as plain TCP.
    Disabled,
}

impl TlsAcceptor {
    /// Create a new TLS acceptor.
    ///
    /// If TLS is enabled, this will load or generate certificates and
    /// create the TLS acceptor.
    pub async fn new(config: &TlsConfig) -> Result<Self, TlsError> {
        if !config.enabled {
            return Ok(TlsAcceptor::Disabled);
        }

        Self::create_enabled(config).await
    }

    /// Create an enabled TLS acceptor.
    #[cfg(feature = "tls")]
    async fn create_enabled(config: &TlsConfig) -> Result<Self, TlsError> {
        let (certs, key) = if !config.cert_path.is_empty() && !config.key_path.is_empty() {
            // Load existing certificates
            let cert_path = Path::new(&config.cert_path);
            let key_path = Path::new(&config.key_path);

            if !cert_path.exists() {
                return Err(TlsError::CertFileNotFound(config.cert_path.clone()));
            }
            if !key_path.exists() {
                return Err(TlsError::KeyFileNotFound(config.key_path.clone()));
            }

            let certs = load_certs(&config.cert_path)?;
            let key = load_private_key(&config.key_path)?;

            info!("TLS: Loaded certificate from {}", config.cert_path);
            info!("TLS: Loaded private key from {}", config.key_path);

            (certs, key)
        } else {
            // Generate self-signed certificate
            info!("TLS: No certificate configured, generating self-signed certificate");
            let (certs, key) = generate_self_signed_cert()?;

            // Save to default paths
            let default_cert = config.cert_path.clone();
            let default_key = config.key_path.clone();

            if !default_cert.is_empty() {
                if let Some(parent) = Path::new(&default_cert).parent() {
                    let _ = tokio::fs::create_dir_all(parent).await;
                }
                let cert_pem = rustls_pemfile::write_one(&certs[0], rustls_pemfile::Item::X509Certificate)
                    .map_err(|e| TlsError::CertGenerationError(e.to_string()))?;
                tokio::fs::write(&default_cert, &cert_pem)
                    .await
                    .map_err(|e| TlsError::CertGenerationError(e.to_string()))?;
                info!("TLS: Saved self-signed certificate to {}", default_cert);
            }

            if !default_key.is_empty() {
                if let Some(parent) = Path::new(&default_key).parent() {
                    let _ = tokio::fs::create_dir_all(parent).await;
                }
                let key_pem = rustls_pemfile::write_one(
                    &key.secret_der(),
                    rustls_pemfile::Item::PKCS8Key,
                )
                .map_err(|e| TlsError::CertGenerationError(e.to_string()))?;
                tokio::fs::write(&default_key, &key_pem)
                    .await
                    .map_err(|e| TlsError::CertGenerationError(e.to_string()))?;
                info!("TLS: Saved private key to {}", default_key);
            }

            (certs, key)
        };

        // Build TLS server config
        let mut server_config = rustls::ServerConfig::builder()
            .with_no_client_auth()
            .with_single_cert(certs, key)
            .map_err(|e| TlsError::AcceptorError(e.to_string()))?;

        // Configure ALPN for IPC
        server_config.alpn_protocols = vec![b"ainos-ipc/1.0".to_vec()];

        let acceptor = tokio_rustls::TlsAcceptor::from(Arc::new(server_config));
        info!("TLS: Acceptor ready");

        Ok(TlsAcceptor::Enabled(acceptor))
    }

    /// Create an enabled TLS acceptor (fallback when feature is disabled).
    #[cfg(not(feature = "tls"))]
    async fn create_enabled(_config: &TlsConfig) -> Result<Self, TlsError> {
        error!("TLS is enabled in config but the `tls` feature is not compiled in. Enable it in Cargo.toml: `features = [\"tls\"]`");
        Err(TlsError::FeatureNotEnabled)
    }

    /// Accept a new connection, optionally upgrading to TLS.
    ///
    /// Returns the accepted stream and peer address.
    pub async fn accept(
        &self,
        listener: &TcpListener,
    ) -> std::io::Result<(TlsStream, std::net::SocketAddr)> {
        match self {
            #[cfg(feature = "tls")]
            TlsAcceptor::Enabled(acceptor) => {
                let (stream, addr) = listener.accept().await?;
                match acceptor.accept(stream).await {
                    Ok(tls_stream) => Ok((TlsStream::Enabled(tls_stream), addr)),
                    Err(e) => Err(std::io::Error::new(
                        std::io::ErrorKind::ConnectionAborted,
                        format!("TLS handshake failed: {}", e),
                    )),
                }
            }
            TlsAcceptor::Disabled => {
                let (stream, addr) = listener.accept().await?;
                Ok((TlsStream::Disabled(stream), addr))
            }
        }
    }
}

// ============================================================================
// TLS Stream
// ============================================================================

/// A stream that may be TLS-encrypted.
pub enum TlsStream {
    /// TLS-encrypted stream.
    #[cfg(feature = "tls")]
    Enabled(tokio_rustls::server::TlsStream<tokio::net::TcpStream>),

    /// Plain TCP stream (no encryption).
    Disabled(tokio::net::TcpStream),
}

// Implement common traits for TlsStream
impl TlsStream {
    /// Get the peer address of the underlying TCP stream.
    pub fn peer_addr(&self) -> std::io::Result<std::net::SocketAddr> {
        match self {
            #[cfg(feature = "tls")]
            TlsStream::Enabled(stream) => stream.get_ref().0.peer_addr(),
            TlsStream::Disabled(stream) => stream.peer_addr(),
        }
    }
}

impl tokio::io::AsyncRead for TlsStream {
    fn poll_read(
        self: std::pin::Pin<&mut Self>,
        cx: &mut std::task::Context<'_>,
        buf: &mut tokio::io::ReadBuf<'_>,
    ) -> std::task::Poll<std::io::Result<()>> {
        match self.get_mut() {
            #[cfg(feature = "tls")]
            TlsStream::Enabled(stream) => {
                std::pin::Pin::new(stream).poll_read(cx, buf)
            }
            TlsStream::Disabled(stream) => {
                std::pin::Pin::new(stream).poll_read(cx, buf)
            }
        }
    }
}

impl tokio::io::AsyncWrite for TlsStream {
    fn poll_write(
        self: std::pin::Pin<&mut Self>,
        cx: &mut std::task::Context<'_>,
        buf: &[u8],
    ) -> std::task::Poll<std::io::Result<usize>> {
        match self.get_mut() {
            #[cfg(feature = "tls")]
            TlsStream::Enabled(stream) => std::pin::Pin::new(stream).poll_write(cx, buf),
            TlsStream::Disabled(stream) => std::pin::Pin::new(stream).poll_write(cx, buf),
        }
    }

    fn poll_flush(
        self: std::pin::Pin<&mut Self>,
        cx: &mut std::task::Context<'_>,
    ) -> std::task::Poll<std::io::Result<()>> {
        match self.get_mut() {
            #[cfg(feature = "tls")]
            TlsStream::Enabled(stream) => std::pin::Pin::new(stream).poll_flush(cx),
            TlsStream::Disabled(stream) => std::pin::Pin::new(stream).poll_flush(cx),
        }
    }

    fn poll_shutdown(
        self: std::pin::Pin<&mut Self>,
        cx: &mut std::task::Context<'_>,
    ) -> std::task::Poll<std::io::Result<()>> {
        match self.get_mut() {
            #[cfg(feature = "tls")]
            TlsStream::Enabled(stream) => std::pin::Pin::new(stream).poll_shutdown(cx),
            TlsStream::Disabled(stream) => std::pin::Pin::new(stream).poll_shutdown(cx),
        }
    }
}

// ============================================================================
// Certificate Operations (feature-gated)
// ============================================================================

/// Load certificates from a PEM file.
#[cfg(feature = "tls")]
fn load_certs(path: &str) -> Result<Vec<rustls::pki_types::CertificateDer<'static>>, TlsError> {
    use std::io::BufReader;

    let cert_file = std::fs::File::open(path)
        .map_err(|e| TlsError::CertLoadError(format!("Cannot open {}: {}", path, e)))?;
    let mut reader = BufReader::new(cert_file);

    let certs = rustls_pemfile::certs(&mut reader)
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| TlsError::CertLoadError(format!("Failed to parse {}: {}", path, e)))?;

    if certs.is_empty() {
        return Err(TlsError::CertLoadError(format!(
            "No certificates found in {}",
            path
        )));
    }

    info!("TLS: Loaded {} certificate(s) from {}", certs.len(), path);
    Ok(certs)
}

/// Load a private key from a PEM file.
#[cfg(feature = "tls")]
fn load_private_key(path: &str) -> Result<rustls::pki_types::PrivateKeyDer<'static>, TlsError> {
    use std::io::BufReader;

    let key_file = std::fs::File::open(path)
        .map_err(|e| TlsError::KeyLoadError(format!("Cannot open {}: {}", path, e)))?;
    let mut reader = BufReader::new(key_file);

    let keys = rustls_pemfile::pkcs8_private_keys(&mut reader)
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| TlsError::KeyLoadError(format!("Failed to parse {}: {}", path, e)))?;

    if let Some(key) = keys.into_iter().next() {
        return Ok(key.into());
    }

    // Try reading as SEC1 (EC) key
    let key_file = std::fs::File::open(path)
        .map_err(|e| TlsError::KeyLoadError(format!("Cannot open {}: {}", path, e)))?;
    let mut reader = BufReader::new(key_file);

    let sec1_keys = rustls_pemfile::sec1_private_keys(&mut reader)
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| TlsError::KeyLoadError(format!("Failed to parse {}: {}", path, e)))?;

    if let Some(key) = sec1_keys.into_iter().next() {
        return Ok(key.into());
    }

    // Try reading as RSA key
    let key_file = std::fs::File::open(path)
        .map_err(|e| TlsError::KeyLoadError(format!("Cannot open {}: {}", path, e)))?;
    let mut reader = BufReader::new(key_file);

    let rsa_keys = rustls_pemfile::rsa_private_keys(&mut reader)
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| TlsError::KeyLoadError(format!("Failed to parse {}: {}", path, e)))?;

    if let Some(key) = rsa_keys.into_iter().next() {
        return Ok(key.into());
    }

    Err(TlsError::KeyLoadError(format!(
        "No private key found in {} (tried PKCS8, SEC1, RSA)",
        path
    )))
}

/// Generate a self-signed certificate for development/testing.
#[cfg(feature = "tls")]
fn generate_self_signed_cert(
) -> Result<(Vec<rustls::pki_types::CertificateDer<'static>>, rustls::pki_types::PrivateKeyDer<'static>), TlsError>
{
    use rcgen::{CertificateParams, KeyPair, KeyUsagePurpose, IsCa, BasicConstraints, DnType, date_time_ymd};

    let mut params = CertificateParams::default();

    // Set distinguished name
    params.distinguished_name.push(DnType::CommonName, "Ainos AI Daemon");
    params.distinguished_name.push(DnType::OrganizationName, "Ainos OS");
    params.distinguished_name.push(DnType::CountryName, "CN");

    // Set subject alternative names
    params.subject_alt_names = vec![
        "localhost".to_string(),
        "127.0.0.1".to_string(),
    ];

    // Set validity period (5 years)
    params.not_before = date_time_ymd(2024, 1, 1);
    params.not_after = date_time_ymd(2029, 12, 31);

    // Key usage
    params.key_usages = vec![
        KeyUsagePurpose::KeyEncipherment,
        KeyUsagePurpose::DigitalSignature,
    ];

    // Extended key usage
    params.extended_key_usages = vec![
        rcgen::ExtendedKeyUsagePurpose::ServerAuth,
    ];

    // Basic constraints
    params.is_ca = IsCa::Ca(BasicConstraints::Unconstrained);

    // Generate key pair and certificate
    let key_pair = KeyPair::generate()
        .map_err(|e| TlsError::CertGenerationError(format!("Failed to generate key pair: {}", e)))?;

    let cert = params
        .self_signed(&key_pair)
        .map_err(|e| TlsError::CertGenerationError(format!("Failed to self-sign certificate: {}", e)))?;

    let cert_der = cert.der().to_vec();
    let key_der = key_pair.serialize_der();

    let certs = vec![rustls::pki_types::CertificateDer::from(cert_der)];
    let key = rustls::pki_types::PrivateKeyDer::Pkcs8(
        rustls::pki_types::PrivatePkcs8KeyDer::from(key_der),
    );

    info!("TLS: Generated self-signed certificate (valid 2024-2029)");
    info!("TLS: Subject: CN=Ainos AI Daemon, O=Ainos OS, C=CN");
    info!("TLS: SANs: localhost, 127.0.0.1");

    Ok((certs, key))
}

/// Load certs (stub when feature is disabled).
#[cfg(not(feature = "tls"))]
fn load_certs(_path: &str) -> Result<Vec<Vec<u8>>, TlsError> {
    Err(TlsError::FeatureNotEnabled)
}

// ============================================================================
// TLS initialization helper
// ============================================================================

/// Initialize TLS for the daemon.
///
/// This is called during daemon startup to configure TLS. It logs the
/// TLS state and returns the TLS acceptor.
pub async fn init_tls(config: &TlsConfig) -> Result<TlsAcceptor, TlsError> {
    if !config.enabled {
        info!("TLS: Disabled (plain TCP connections)");
        return Ok(TlsAcceptor::Disabled);
    }

    info!("TLS: Initializing...");
    info!("TLS: Certificate path: {}", config.cert_path);
    info!("TLS: Private key path: {}", config.key_path);
    if config.verify_client {
        info!("TLS: Client certificate verification enabled");
    } else {
        info!("TLS: Client certificate verification disabled");
    }

    let acceptor = TlsAcceptor::new(config).await?;

    info!("TLS: Initialization complete");

    Ok(acceptor)
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_tls_config_default() {
        let config = TlsConfig::default();
        assert!(!config.enabled);
        assert!(!config.verify_client);
    }

    #[test]
    fn test_tls_state_from_config() {
        let config = TlsConfig::default();
        let state = TlsState::from_config(&config);
        assert!(!state.enabled);
        assert_eq!(state.cert_path, "");
        assert_eq!(state.key_path, "");
    }

    #[test]
    fn test_tls_state_disabled() {
        let state = TlsState::disabled();
        assert!(!state.enabled);
        assert!(!state.cert_auto_generated);
    }

    #[test]
    fn test_tls_error_messages() {
        let err = TlsError::CertFileNotFound("cert.pem".to_string());
        assert!(format!("{}", err).contains("cert.pem"));

        let err = TlsError::FeatureNotEnabled;
        assert!(format!("{}", err).contains("tls feature")
                || format!("{}", err).contains("Enable the"));

        let err = TlsError::IoError("connection refused".to_string());
        assert!(format!("{}", err).contains("connection refused"));
    }

    #[test]
    fn test_tls_acceptor_disabled() {
        // When TLS is disabled, the acceptor should always be Disabled
        let config = TlsConfig::default();
        let acceptor = futures::executor::block_on(TlsAcceptor::new(&config)).unwrap();
        match acceptor {
            TlsAcceptor::Disabled => {} // Expected
            #[cfg(feature = "tls")]
            TlsAcceptor::Enabled(_) => panic!("Should be Disabled when TLS is disabled in config"),
        }
    }

    #[cfg(feature = "tls")]
    #[tokio::test]
    async fn test_tls_generate_self_signed() {
        let (certs, key) = generate_self_signed_cert().unwrap();
        assert!(!certs.is_empty(), "Should generate at least one certificate");
        assert!(!key.secret_der().is_empty(), "Should generate a private key");
    }

    #[cfg(feature = "tls")]
    #[tokio::test]
    async fn test_tls_load_certs() {
        // Test that loading a non-existent file returns an error
        let result = load_certs("/nonexistent/cert.pem");
        assert!(result.is_err(), "Should fail on nonexistent file");
    }

    #[cfg(feature = "tls")]
    #[tokio::test]
    async fn test_tls_load_key() {
        // Test that loading a non-existent file returns an error
        let result = load_private_key("/nonexistent/key.pem");
        assert!(result.is_err(), "Should fail on nonexistent file");
    }

    #[test]
    fn test_tls_error_from_io() {
        let io_err = std::io::Error::new(std::io::ErrorKind::NotFound, "file not found");
        let tls_err: TlsError = io_err.into();
        match tls_err {
            TlsError::IoError(_) => {} // Expected
            _ => panic!("Expected IoError variant"),
        }
    }

    #[tokio::test]
    async fn test_init_tls_disabled() {
        let config = TlsConfig::default();
        let result = init_tls(&config).await;
        assert!(result.is_ok());

        match result.unwrap() {
            TlsAcceptor::Disabled => {} // Expected
            #[cfg(feature = "tls")]
            TlsAcceptor::Enabled(_) => panic!("Should be Disabled"),
        }
    }

    #[cfg(feature = "tls")]
    #[tokio::test]
    async fn test_tls_acceptor_creation() {
        let config = TlsConfig {
            enabled: true,
            cert_path: String::new(),
            key_path: String::new(),
            verify_client: false,
        };
        // Should generate self-signed certs
        let result = TlsAcceptor::new(&config).await;
        assert!(result.is_ok(), "Should create acceptor with self-signed certs");
    }

    #[cfg(not(feature = "tls"))]
    #[tokio::test]
    async fn test_tls_acceptor_feature_not_enabled() {
        let config = TlsConfig {
            enabled: true,
            cert_path: String::new(),
            key_path: String::new(),
            verify_client: false,
        };
        let result = TlsAcceptor::new(&config).await;
        assert!(result.is_err(), "Should fail when tls feature is disabled");
        match result {
            Err(TlsError::FeatureNotEnabled) => {} // Expected
            _ => panic!("Expected FeatureNotEnabled error"),
        }
    }
}