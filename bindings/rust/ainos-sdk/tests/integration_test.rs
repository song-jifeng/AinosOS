//! Integration tests for the Ainos SDK.
//!
//! These tests use a mock transport to simulate the daemon protocol.
//! They do not require a running daemon.

use ainos_sdk::error::{AinosError, RetryConfig, Retryable, RetryKind, Result};
use ainos_sdk::prelude::*;
use ainos_sdk::transport::mock::MockTransport;
use ainos_sdk::transport::Transport;
use ainos_sdk::{
    auth::{BearerToken, SessionManager, Session},
    streaming::InferenceStream,
    types::ClientConfig,
};
use futures::StreamExt;
use std::sync::Arc;
use std::time::Duration;

// ===========================================================================
// Test helpers
// ===========================================================================

/// Create a mock client with a pre-connected transport.
async fn mock_client() -> (AinosClient, ainos_sdk::transport::mock::MockTransportHandle) {
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
    // Set the transport directly
    *client.transport.write().await = Some(Box::new(transport));
    *client.connected.write().await = true;

    (client, handle)
}

/// Inject a single response and get the result.
// ===========================================================================
// Connection lifecycle tests
// ===========================================================================

#[tokio::test]
async fn test_connect_and_disconnect() {
    let (client, _handle) = mock_client().await;
    assert!(client.is_connected().await);
    client.disconnect().await.unwrap();
    assert!(!client.is_connected().await);
}

#[tokio::test]
async fn test_double_connect_is_idempotent() {
    let (client, _handle) = mock_client().await;
    assert!(client.is_connected().await);
    // Calling connect again should be a no-op
    assert!(client.connect().await.is_ok());
    assert!(client.is_connected().await);
}

#[tokio::test]
async fn test_double_disconnect_is_idempotent() {
    let (client, _handle) = mock_client().await;
    client.disconnect().await.unwrap();
    assert!(!client.is_connected().await);
    // Second disconnect should be a no-op
    assert!(client.disconnect().await.is_ok());
}

// ===========================================================================
// Authentication tests
// ===========================================================================

#[tokio::test]
async fn test_authenticate_success() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"AuthResponse","success":true,"session_token":"tok_abc","message":"OK","permissions":["infer","status"],"session_ttl_seconds":3600}"#,
    );

    let session = client.authenticate("my-token").await.unwrap();
    assert!(session.success);
    assert_eq!(session.session_token, "tok_abc");
}

#[tokio::test]
async fn test_authenticate_failure() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"AuthResponse","success":false,"session_token":null,"message":"Invalid token","permissions":[],"session_ttl_seconds":0}"#,
    );

    let result = client.authenticate("bad-token").await;
    assert!(result.is_err());
    match result.unwrap_err() {
        AinosError::AuthFailed(msg) => assert_eq!(msg, "Invalid token"),
        e => panic!("Expected AuthFailed, got: {}", e),
    }
}

#[tokio::test]
async fn test_authenticate_missing_token() {
    // Create client without auth token
    let (_transport, _handle) = MockTransport::new(1024 * 1024);
    let config = ClientConfig::default();
    let client = AinosClient::with_config(config, SessionManager::new());
    // Don't set a token, try to authenticate with empty string
    let result = client.authenticate("").await;
    assert!(result.is_err());
}

#[tokio::test]
async fn test_authenticate_updates_session() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"AuthResponse","success":true,"session_token":"tok_xyz","message":"OK","permissions":["admin"],"session_ttl_seconds":7200}"#,
    );

    client.authenticate("admin-token").await.unwrap();
    assert!(client.is_authenticated().await);
    assert_eq!(client.session_token().await, Some("tok_xyz".into()));
    let perms = client.permissions().await;
    assert!(perms.contains(&"admin".to_string()));
}

// ===========================================================================
// Inference tests
// ===========================================================================

#[tokio::test]
async fn test_infer_basic() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"InferenceResponse","output":"Hello, world!","tokens_generated":3,"inference_ms":50,"source":"local"}"#,
    );

    let req = InferenceRequest::builder().prompt("Hi").build();
    let resp = client.infer(&req).await.unwrap();
    assert_eq!(resp.output, "Hello, world!");
    assert_eq!(resp.tokens_generated, 3);
    assert_eq!(resp.source, "local");
}

#[tokio::test]
async fn test_infer_with_all_params() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"InferenceResponse","output":"Custom response","tokens_generated":2,"inference_ms":100,"source":"cloud"}"#,
    );

    let req = InferenceRequest::builder()
        .prompt("Test prompt")
        .model("phi-3-mini")
        .temperature(0.5)
        .max_tokens(100)
        .session_id("test-session")
        .build();

    let resp = client.infer(&req).await.unwrap();
    assert_eq!(resp.output, "Custom response");
    assert_eq!(resp.source, "cloud");
}

#[tokio::test]
async fn test_infer_daemon_error() {
    let (client, handle) = mock_client().await;
    handle.add_response(r#"{"type":"Error","code":500,"message":"Internal error"}"#);

    let req = InferenceRequest::builder().prompt("Hi").build();
    let result = client.infer(&req).await;
    assert!(result.is_err());
    match result.unwrap_err() {
        AinosError::DaemonError { code, message } => {
            assert_eq!(code, 500);
            assert_eq!(message, "Internal error");
        }
        e => panic!("Expected DaemonError, got: {}", e),
    }
}

#[tokio::test]
async fn test_infer_unexpected_response() {
    let (client, handle) = mock_client().await;
    handle.add_response(r#"{"type":"Status","uptime":100}"#);

    let req = InferenceRequest::builder().prompt("Hi").build();
    let result = client.infer(&req).await;
    assert!(result.is_err());
    match result.unwrap_err() {
        AinosError::UnexpectedResponse(_) => {} // expected
        e => panic!("Expected UnexpectedResponse, got: {}", e),
    }
}

#[tokio::test]
async fn test_batch_infer() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"InferenceResponse","output":"First","tokens_generated":1,"inference_ms":10,"source":"local"}"#,
    );
    handle.add_response(
        r#"{"type":"InferenceResponse","output":"Second","tokens_generated":2,"inference_ms":20,"source":"local"}"#,
    );
    handle.add_response(
        r#"{"type":"InferenceResponse","output":"Third","tokens_generated":3,"inference_ms":30,"source":"cloud"}"#,
    );

    let reqs = vec![
        InferenceRequest::builder().prompt("R1").build(),
        InferenceRequest::builder().prompt("R2").build(),
        InferenceRequest::builder().prompt("R3").build(),
    ];

    let results = client.batch_infer(&reqs).await.unwrap();
    assert_eq!(results.len(), 3);
    assert_eq!(results[0].output, "First");
    assert_eq!(results[1].output, "Second");
    assert_eq!(results[2].output, "Third");
}

#[tokio::test]
async fn test_batch_infer_empty() {
    let (client, _handle) = mock_client().await;
    let results = client.batch_infer(&[]).await.unwrap();
    assert!(results.is_empty());
}

// ===========================================================================
// Streaming inference tests
// ===========================================================================

#[tokio::test]
async fn test_infer_stream_basic() {
    let (_client, handle) = mock_client().await;
    // For streaming, the client creates a new transport, which we need to mock
    // Here we just test that the streaming request is sent
    handle.add_response(r#"{"type":"InferenceChunk","chunk":"Hello","done":false}"#);
    handle.add_response(r#"{"type":"InferenceChunk","chunk":" world","done":false}"#);
    handle.add_response(r#"{"type":"InferenceChunk","chunk":"!","done":true}"#);

    let _req = InferenceRequest::builder().prompt("Hi").build();
    // Note: infer_stream creates a new connection, so this test uses the mock transport directly
    // rather than going through the client

    // Direct stream test (the stream creates its own transport internally)
    let (transport, handle2) = MockTransport::new(1024 * 1024);
    // Skip the connect step since we're injecting directly
    let mut transport = transport;
    transport.connect("mock://test", Duration::from_secs(1)).await.unwrap();

    handle2.add_response(r#"{"type":"InferenceChunk","chunk":"Hello","done":false}"#);
    handle2.add_response(r#"{"type":"InferenceChunk","chunk":" world","done":false}"#);
    handle2.add_response(r#"{"type":"InferenceChunk","chunk":"!","done":true}"#);

    let mut stream = InferenceStream::new(Box::new(transport), None);

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

#[tokio::test]
async fn test_infer_stream_error() {
    let (mut transport, handle) = MockTransport::new(1024 * 1024);
    transport.connect("mock://test", Duration::from_secs(1)).await.unwrap();

    handle.add_response(r#"{"type":"Error","code":500,"message":"Stream error"}"#);

    let mut stream = InferenceStream::new(Box::new(transport), None);
    let chunk = stream.next().await;
    assert!(chunk.is_some());
    let result = chunk.unwrap();
    assert!(result.is_err());
    match result.unwrap_err() {
        AinosError::DaemonError { code, message } => {
            assert_eq!(code, 500);
            assert_eq!(message, "Stream error");
        }
        e => panic!("Expected DaemonError, got: {}", e),
    }
}

#[tokio::test]
async fn test_infer_stream_cancel() {
    let (mut transport, handle) = MockTransport::new(1024 * 1024);
    transport.connect("mock://test", Duration::from_secs(1)).await.unwrap();

    handle.add_response(r#"{"type":"InferenceChunk","chunk":"a","done":false}"#);
    handle.add_response(r#"{"type":"InferenceChunk","chunk":"b","done":false}"#);
    handle.add_response(r#"{"type":"InferenceChunk","chunk":"c","done":true}"#);

    let mut stream = InferenceStream::new(Box::new(transport), None);

    let chunk = stream.next().await.unwrap().unwrap();
    assert_eq!(chunk.chunk, "a");
    stream.cancel();
    assert!(stream.next().await.is_none());
}

#[tokio::test]
async fn test_infer_stream_collect_string() {
    let (mut transport, handle) = MockTransport::new(1024 * 1024);
    transport.connect("mock://test", Duration::from_secs(1)).await.unwrap();

    handle.add_response(r#"{"type":"InferenceChunk","chunk":"Hello","done":false}"#);
    handle.add_response(r#"{"type":"InferenceChunk","chunk":" ","done":false}"#);
    handle.add_response(r#"{"type":"InferenceChunk","chunk":"World","done":true}"#);

    let mut stream = InferenceStream::new(Box::new(transport), None);
    let result = stream.collect_string().await.unwrap();
    assert_eq!(result, "Hello World");
}

#[tokio::test]
async fn test_infer_stream_drain() {
    let (mut transport, handle) = MockTransport::new(1024 * 1024);
    transport.connect("mock://test", Duration::from_secs(1)).await.unwrap();

    handle.add_response(r#"{"type":"InferenceChunk","chunk":"a","done":false}"#);
    handle.add_response(r#"{"type":"InferenceChunk","chunk":"b","done":true}"#);

    let mut stream = InferenceStream::new(Box::new(transport), None);
    stream.drain().await.unwrap();
    assert!(stream.next().await.is_none());
}

// ===========================================================================
// Model management tests
// ===========================================================================

#[tokio::test]
async fn test_model_list() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"ModelListResponse","models":[
            {"id":"m1","name":"model1.gguf","path":"/m1.gguf","size_mb":1024,"loaded":true,"architecture":"auto"},
            {"id":"m2","name":"model2.gguf","path":"/m2.gguf","size_mb":2048,"loaded":false,"architecture":"phi3"}
        ]}"#,
    );

    let models = client.model_list().await.unwrap();
    assert_eq!(models.len(), 2);
    assert_eq!(models[0].id, "m1");
    assert!(models[0].loaded);
    assert_eq!(models[1].id, "m2");
    assert!(!models[1].loaded);
    assert_eq!(models[1].architecture, "phi3");
}

#[tokio::test]
async fn test_model_list_empty() {
    let (client, handle) = mock_client().await;
    handle.add_response(r#"{"type":"ModelListResponse","models":[]}"#);

    let models = client.model_list().await.unwrap();
    assert!(models.is_empty());
}

#[tokio::test]
async fn test_model_list_error() {
    let (client, handle) = mock_client().await;
    handle.add_response(r#"{"type":"Error","code":500,"message":"Failed to list models"}"#);

    let result = client.model_list().await;
    assert!(result.is_err());
    match result.unwrap_err() {
        AinosError::DaemonError { code, .. } => assert_eq!(code, 500),
        e => panic!("Expected DaemonError, got: {}", e),
    }
}

#[tokio::test]
async fn test_model_load() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"ModelLoadResponse","model_id":"test_model","status":"loaded","message":"OK","model_info":{"id":"test_model","name":"test.gguf","path":"/test.gguf","size_mb":512,"loaded":true,"architecture":"auto"}}"#,
    );

    let opts = ModelLoadOptions::builder()
        .path("/test.gguf")
        .model_type("ggml")
        .build();

    let info = client.model_load("/test.gguf", &opts).await.unwrap();
    assert_eq!(info.id, "test_model");
    assert!(info.loaded);
}

#[tokio::test]
async fn test_model_load_error() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"ModelLoadResponse","model_id":"","status":"error","message":"File not found","model_info":null}"#,
    );

    let opts = ModelLoadOptions::builder()
        .path("/nonexistent.gguf")
        .build();

    let result = client.model_load("/nonexistent.gguf", &opts).await;
    assert!(result.is_err());
}

#[tokio::test]
async fn test_model_unload() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"ModelUnloadResponse","model_id":"m1","status":"unloaded","message":"OK"}"#,
    );

    client.model_unload("m1").await.unwrap();
}

#[tokio::test]
async fn test_model_unload_not_found() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"ModelUnloadResponse","model_id":"m1","status":"not_found","message":"Model not found"}"#,
    );

    let result = client.model_unload("m1").await;
    assert!(result.is_err());
    match result.unwrap_err() {
        AinosError::DaemonError { code, message } => {
            assert_eq!(code, -1);
            assert_eq!(message, "Model not found");
        }
        e => panic!("Expected DaemonError, got: {}", e),
    }
}

// ===========================================================================
// Context tests
// ===========================================================================

#[tokio::test]
async fn test_context_store() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"InferenceResponse","output":"Context stored: sess:key","tokens_generated":0,"inference_ms":0,"source":"local"}"#,
    );

    client
        .context_store("sess", "key", b"value", 3600)
        .await
        .unwrap();
}

#[tokio::test]
async fn test_context_store_error() {
    let (client, handle) = mock_client().await;
    handle.add_response(r#"{"type":"Error","code":-1,"message":"Store failed"}"#);

    let result = client
        .context_store("sess", "key", b"value", 3600)
        .await;
    assert!(result.is_err());
}

#[tokio::test]
async fn test_context_retrieve() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"InferenceResponse","output":"stored_value","tokens_generated":0,"inference_ms":0,"source":"local"}"#,
    );

    let result = client.context_retrieve("sess", "key").await.unwrap();
    assert_eq!(result, Some(b"stored_value".to_vec()));
}

#[tokio::test]
async fn test_context_retrieve_missing() {
    let (client, handle) = mock_client().await;
    handle.add_response(r#"{"type":"Error","code":-1,"message":"Key not found: sess:key"}"#);

    let result = client.context_retrieve("sess", "key").await.unwrap();
    assert!(result.is_none());
}

#[tokio::test]
async fn test_context_retrieve_empty() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"InferenceResponse","output":"","tokens_generated":0,"inference_ms":0,"source":"local"}"#,
    );

    let result = client.context_retrieve("sess", "key").await.unwrap();
    assert!(result.is_none());
}

// ===========================================================================
// Status & Health tests
// ===========================================================================

#[tokio::test]
async fn test_status() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"StatusResponse","uptime":3600,"models_loaded":2,"total_requests":100,"network_available":true,"active_sessions":5}"#,
    );

    let status = client.status().await.unwrap();
    assert_eq!(status.uptime, 3600);
    assert_eq!(status.models_loaded, 2);
    assert_eq!(status.total_requests, 100);
    assert!(status.network_available);
    assert_eq!(status.active_sessions, 5);
}

#[tokio::test]
async fn test_status_with_rate_limits() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"StatusResponse","uptime":100,"models_loaded":1,"total_requests":50,"network_available":true,"active_sessions":2,"rate_limits":[{"category":"inference","limit":100,"remaining":50,"reset_seconds":30}]}"#,
    );

    let status = client.status().await.unwrap();
    assert!(status.rate_limits.is_some());
    let limits = status.rate_limits.unwrap();
    assert_eq!(limits.len(), 1);
    assert_eq!(limits[0].category, "inference");
}

#[tokio::test]
async fn test_health_ok() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"StatusResponse","uptime":3600,"models_loaded":2,"total_requests":100,"network_available":true,"active_sessions":5}"#,
    );

    let health = client.health().await.unwrap();
    assert!(health.healthy);
    assert!(health.engine);
    assert!(health.network);
    assert_eq!(health.uptime, 3600);
}

#[tokio::test]
async fn test_health_degraded() {
    let (client, _handle) = mock_client().await;
    // No response injected — recv will fail

    let health = client.health().await.unwrap();
    assert!(!health.healthy);
    assert!(!health.engine);
    assert!(!health.network);
}

#[tokio::test]
async fn test_rate_limit_status() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"RateLimitStatusResponse","limits":[{"category":"inference","limit":100,"remaining":50,"reset_seconds":30},{"category":"model_ops","limit":50,"remaining":25,"reset_seconds":60}]}"#,
    );

    let status = client.rate_limit_status().await.unwrap();
    assert_eq!(status.limits.len(), 2);
    assert_eq!(status.limits[0].category, "inference");
    assert_eq!(status.limits[0].remaining, 50);
    assert_eq!(status.limits[1].category, "model_ops");
    assert_eq!(status.limits[1].remaining, 25);
}

// ===========================================================================
// Transport tests
// ===========================================================================

#[tokio::test]
async fn test_mock_transport_connect_disconnect() {
    let (mut transport, _handle) = MockTransport::new(1024 * 1024);
    assert!(!transport.is_connected());

    transport
        .connect("mock://test", Duration::from_secs(1))
        .await
        .unwrap();
    assert!(transport.is_connected());

    transport.disconnect().await.unwrap();
    assert!(!transport.is_connected());
}

#[tokio::test]
async fn test_mock_transport_send_recv() {
    let (mut transport, handle) = MockTransport::new(1024 * 1024);
    transport
        .connect("mock://test", Duration::from_secs(1))
        .await
        .unwrap();

    handle.add_response(r#"{"type":"Status"}"#);

    transport.send(r#"{"type":"Status"}"#).await.unwrap();
    let response = transport.recv().await.unwrap();
    assert_eq!(response, r#"{"type":"Status"}"#);

    let sent = handle.sent_messages();
    assert_eq!(sent.len(), 1);
    assert_eq!(sent[0], r#"{"type":"Status"}"#);
}

#[tokio::test]
async fn test_mock_transport_recv_closed() {
    let (mut transport, _handle) = MockTransport::new(1024 * 1024);
    transport
        .connect("mock://test", Duration::from_secs(1))
        .await
        .unwrap();

    // No response queued — should get ConnectionClosed
    let result = transport.recv().await;
    assert!(result.is_err());
    match result.unwrap_err() {
        AinosError::ConnectionClosed => {} // expected
        e => panic!("Expected ConnectionClosed, got: {}", e),
    }
}

#[tokio::test]
async fn test_mock_transport_request() {
    let (mut transport, handle) = MockTransport::new(1024 * 1024);
    transport
        .connect("mock://test", Duration::from_secs(1))
        .await
        .unwrap();

    handle.add_response(r#"{"type":"InferenceResponse","output":"test","tokens_generated":1,"inference_ms":10,"source":"local"}"#);

    let response = transport
        .request(r#"{"type":"Inference","model":"default","prompt":"test"}"#)
        .await
        .unwrap();
    assert!(response.contains("InferenceResponse"));
}

// ===========================================================================
// Session manager tests
// ===========================================================================

#[tokio::test]
async fn test_session_manager_lifecycle() {
    let mgr = SessionManager::with_token("test-token");
    assert!(mgr.is_enabled().await);
    assert!(!mgr.is_authenticated().await);

    let session = Session {
        session_token: "tok_1".into(),
        success: true,
        message: "OK".into(),
        permissions: vec!["infer".into()],
        session_ttl_seconds: 3600,
        created_at: std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs(),
    };

    mgr.set_session(session).await;
    assert!(mgr.is_authenticated().await);
    assert_eq!(mgr.session_token().await, Some("tok_1".into()));

    mgr.clear_session().await;
    assert!(!mgr.is_authenticated().await);
}

#[tokio::test]
async fn test_session_manager_permissions() {
    let mgr = SessionManager::with_token("token");

    let session = Session {
        session_token: "tok_2".into(),
        success: true,
        message: "OK".into(),
        permissions: vec!["infer".into(), "status".into()],
        session_ttl_seconds: 3600,
        created_at: std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs(),
    };

    mgr.set_session(session).await;
    assert!(mgr.check_permission("infer").await.is_ok());
    assert!(mgr.check_permission("status").await.is_ok());
    assert!(mgr.check_permission("admin").await.is_err());
}

#[tokio::test]
async fn test_session_manager_disabled() {
    let mgr = SessionManager::disabled();
    assert!(!mgr.is_enabled().await);
    // When disabled, all permissions should pass
    assert!(mgr.check_permission("anything").await.is_ok());
}

// ===========================================================================
// Error handling tests
// ===========================================================================

#[tokio::test]
async fn test_error_retry_classification() {
    let err = AinosError::ConnectionRefused("refused".into());
    assert_eq!(err.retry_kind(), RetryKind::Transient);

    let err = AinosError::ConnectionLost("lost".into());
    assert_eq!(err.retry_kind(), RetryKind::Transient);

    let err = AinosError::Timeout(Duration::from_secs(5));
    assert_eq!(err.retry_kind(), RetryKind::Transient);

    let err = AinosError::AuthFailed("bad".into());
    assert_eq!(err.retry_kind(), RetryKind::Fatal);

    let err = AinosError::DaemonError {
        code: 429,
        message: "rate limited".into(),
    };
    assert_eq!(err.retry_kind(), RetryKind::Throttled);
}

#[tokio::test]
async fn test_error_is_helpers() {
    let err = AinosError::AuthFailed("bad".into());
    assert!(err.is_auth_error());
    assert!(!err.is_connection_error());
    assert!(!err.is_timeout());
    assert!(!err.is_rate_limited());

    let err = AinosError::ConnectionLost("lost".into());
    assert!(err.is_connection_error());
    assert!(!err.is_auth_error());

    let err = AinosError::RateLimited("too many".into());
    assert!(err.is_rate_limited());

    let err = AinosError::DaemonError {
        code: 500,
        message: "err".into(),
    };
    assert_eq!(err.daemon_code(), Some(500));
}

#[tokio::test]
async fn test_retry_config_backoff() {
    let cfg = RetryConfig::default();
    assert_eq!(cfg.backoff(0), Duration::from_millis(100));
    assert_eq!(cfg.backoff(1), Duration::from_millis(200));
    assert_eq!(cfg.backoff(2), Duration::from_millis(400));
    assert_eq!(cfg.backoff(3), Duration::from_millis(800));
    assert_eq!(cfg.backoff(4), Duration::from_millis(1600));
}

// ===========================================================================
// Builder tests
// ===========================================================================

#[tokio::test]
async fn test_client_builder_defaults() {
    let client = AinosClient::builder().build();
    assert_eq!(client.config().host, "127.0.0.1");
    assert_eq!(client.config().port, 9500);
    assert_eq!(client.config().connect_timeout, Duration::from_secs(5));
    assert!(client.config().auto_reconnect);
    assert!(client.config().auth_token.is_none());
}

#[tokio::test]
async fn test_client_builder_custom() {
    let client = AinosClient::builder()
        .host("10.0.0.1")
        .port(9501)
        .auth_token("secret")
        .connect_timeout(Duration::from_secs(30))
        .read_timeout(Duration::from_secs(300))
        .auto_reconnect(false)
        .build();

    assert_eq!(client.config().host, "10.0.0.1");
    assert_eq!(client.config().port, 9501);
    assert_eq!(client.config().auth_token, Some("secret".into()));
    assert_eq!(client.config().connect_timeout, Duration::from_secs(30));
    assert_eq!(client.config().read_timeout, Duration::from_secs(300));
    assert!(!client.config().auto_reconnect);
}

#[tokio::test]
async fn test_client_builder_addr() {
    let client = AinosClient::builder()
        .addr("192.168.1.1:9500")
        .build();
    assert_eq!(client.config().host, "192.168.1.1");
    assert_eq!(client.config().port, 9500);
}

// ===========================================================================
// InferenceRequest builder tests
// ===========================================================================

#[tokio::test]
async fn test_inference_request_builder() {
    let req = InferenceRequest::builder()
        .prompt("Test prompt")
        .model("custom-model")
        .temperature(0.3)
        .max_tokens(500)
        .session_id("test-session")
        .build();

    assert_eq!(req.prompt, "Test prompt");
    assert_eq!(req.model, "custom-model");
    assert_eq!(req.temperature, Some(0.3));
    assert_eq!(req.max_tokens, Some(500));
    assert_eq!(req.session_id, Some("test-session".into()));
}

#[tokio::test]
async fn test_inference_request_defaults() {
    let req = InferenceRequest::builder().prompt("Hi").build();
    assert_eq!(req.model, "default");
    assert_eq!(req.temperature, None);
    assert_eq!(req.max_tokens, None);
    assert_eq!(req.session_id, None);
}

// ===========================================================================
// ModelLoadOptions builder tests
// ===========================================================================

#[tokio::test]
async fn test_model_load_options_builder() {
    let opts = ModelLoadOptions::builder()
        .path("/models/test.gguf")
        .model_type("ggml")
        .gpu_layers(64)
        .context_size(8192)
        .use_mmap(true)
        .build();

    assert_eq!(opts.path, "/models/test.gguf");
    assert_eq!(opts.model_type, Some("ggml".into()));
    assert_eq!(opts.gpu_layers, Some(64));
    assert_eq!(opts.context_size, Some(8192));
    assert_eq!(opts.use_mmap, Some(true));
}

// ===========================================================================
// IPC message serialization tests
// ===========================================================================

#[tokio::test]
async fn test_ipc_message_roundtrip() {
    // Test all message types serialize/deserialize correctly

    // Auth
    let msg = ainos_sdk::IpcMessage::Auth {
        token: "test-token".into(),
    };
    let json = serde_json::to_string(&msg).unwrap();
    let deserialized: ainos_sdk::IpcMessage = serde_json::from_str(&json).unwrap();
    match deserialized {
        ainos_sdk::IpcMessage::Auth { token } => assert_eq!(token, "test-token"),
        _ => panic!("Expected Auth"),
    }

    // Status
    let msg = ainos_sdk::IpcMessage::Status;
    let json = serde_json::to_string(&msg).unwrap();
    assert_eq!(json, r#"{"type":"Status"}"#);

    // Inference
    let msg = ainos_sdk::IpcMessage::Inference {
        model: "m".into(),
        prompt: "p".into(),
        temperature: Some(0.5),
        max_tokens: Some(100),
        session_id: None,
    };
    let json = serde_json::to_string(&msg).unwrap();
    assert!(json.contains(r#""type":"Inference""#));
    assert!(json.contains(r#""model":"m""#));
    assert!(json.contains(r#""prompt":"p""#));
}

// ===========================================================================
// Concurrent access tests
// ===========================================================================

#[tokio::test]
async fn test_concurrent_inference() {
    let (client, handle) = mock_client().await;

    // Queue up responses for 3 concurrent calls
    handle.add_response(
        r#"{"type":"InferenceResponse","output":"A","tokens_generated":1,"inference_ms":10,"source":"local"}"#,
    );
    handle.add_response(
        r#"{"type":"InferenceResponse","output":"B","tokens_generated":1,"inference_ms":10,"source":"local"}"#,
    );
    handle.add_response(
        r#"{"type":"InferenceResponse","output":"C","tokens_generated":1,"inference_ms":10,"source":"local"}"#,
    );

    let client = Arc::new(client);
    let mut handles = vec![];

    for i in 0..3 {
        let client = client.clone();
        let req = InferenceRequest::builder()
            .prompt(format!("Request {}", i))
            .build();
        handles.push(tokio::spawn(async move {
            client.infer(&req).await
        }));
    }

    let mut results = vec![];
    for h in handles {
        results.push(h.await.unwrap().unwrap());
    }

    assert_eq!(results.len(), 3);
}

// ===========================================================================
// Edge case tests
// ===========================================================================

#[tokio::test]
async fn test_empty_prompt() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"InferenceResponse","output":"","tokens_generated":0,"inference_ms":0,"source":"local"}"#,
    );

    let req = InferenceRequest::builder().prompt("").build();
    let resp = client.infer(&req).await.unwrap();
    assert_eq!(resp.output, "");
    assert_eq!(resp.tokens_generated, 0);
}

#[tokio::test]
async fn test_very_long_input() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"InferenceResponse","output":"OK","tokens_generated":1,"inference_ms":1,"source":"local"}"#,
    );

    let long_prompt = "a".repeat(10000);
    let req = InferenceRequest::builder().prompt(&long_prompt).build();
    let resp = client.infer(&req).await.unwrap();
    assert_eq!(resp.output, "OK");
}

#[tokio::test]
async fn test_negative_temperature() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"InferenceResponse","output":"OK","tokens_generated":1,"inference_ms":1,"source":"local"}"#,
    );

    // Negative temperature should still be sent as-is (daemon validates)
    let req = InferenceRequest::builder()
        .prompt("test")
        .temperature(-1.0)
        .build();
    let resp = client.infer(&req).await.unwrap();
    assert_eq!(resp.output, "OK");
}

#[tokio::test]
async fn test_zero_max_tokens() {
    let (client, handle) = mock_client().await;
    handle.add_response(
        r#"{"type":"InferenceResponse","output":"","tokens_generated":0,"inference_ms":0,"source":"local"}"#,
    );

    let req = InferenceRequest::builder()
        .prompt("test")
        .max_tokens(0)
        .build();
    let resp = client.infer(&req).await.unwrap();
    assert_eq!(resp.tokens_generated, 0);
}

// ===========================================================================
// Bearer token tests
// ===========================================================================

#[tokio::test]
async fn test_bearer_token_creation() {
    let token = BearerToken::new("my-secret-token-12345");
    assert_eq!(token.as_str(), "my-secret-token-12345");
    assert!(!token.is_empty());
}

#[tokio::test]
async fn test_bearer_token_from_string() {
    let token: BearerToken = "test-token".into();
    assert_eq!(token.as_str(), "test-token");
}

#[tokio::test]
async fn test_bearer_token_debug() {
    let token = BearerToken::new("this-is-a-long-token");
    let debug = format!("{:?}", token);
    assert!(debug.starts_with("BearerToken("));
    assert!(debug.ends_with("...)"));

    let short = BearerToken::new("short");
    let debug = format!("{:?}", short);
    assert_eq!(debug, "BearerToken(***)");
}

// ===========================================================================
// Health status construction tests
// ===========================================================================

#[tokio::test]
async fn test_health_status_ok() {
    let health = HealthStatus {
        healthy: true,
        message: "All systems operational".into(),
        database: true,
        engine: true,
        network: true,
        uptime: 3600,
    };
    assert!(health.healthy);
    assert!(health.database);
    assert!(health.engine);
    assert!(health.network);
}

#[tokio::test]
async fn test_health_status_degraded() {
    let health = HealthStatus {
        healthy: false,
        message: "Engine offline".into(),
        database: true,
        engine: false,
        network: true,
        uptime: 100,
    };
    assert!(!health.healthy);
    assert!(!health.engine);
}

// ===========================================================================
// Rate limit construction tests
// ===========================================================================

#[tokio::test]
async fn test_rate_limit_creation() {
    let status = RateLimitStatus {
        limits: vec![
            ainos_sdk::RateLimitInfo {
                category: "inference".into(),
                limit: 100,
                remaining: 75,
                reset_seconds: 30,
            },
        ],
    };
    assert_eq!(status.limits.len(), 1);
    assert_eq!(status.limits[0].remaining, 75);
}

// ===========================================================================
// Model info tests
// ===========================================================================

#[tokio::test]
async fn test_model_info_serialization() {
    let info = ModelInfo {
        id: "test_model".into(),
        name: "test.gguf".into(),
        path: "/models/test.gguf".into(),
        size_mb: 1024,
        loaded: true,
        architecture: "auto".into(),
    };

    let json = serde_json::to_string(&info).unwrap();
    let deserialized: ModelInfo = serde_json::from_str(&json).unwrap();
    assert_eq!(deserialized.id, "test_model");
    assert!(deserialized.loaded);
    assert_eq!(deserialized.architecture, "auto");
}

// ===========================================================================
// ClientConfig tests
// ===========================================================================

#[tokio::test]
async fn test_client_config_serialization() {
    let config = ClientConfig {
        host: "127.0.0.1".into(),
        port: 9500,
        connect_timeout: Duration::from_secs(5),
        read_timeout: Duration::from_secs(120),
        auto_reconnect: true,
        reconnect_delay: Duration::from_secs(1),
        auth_token: Some("token".into()),
        auto_authenticate: true,
        retry_config: RetryConfig::default(),
        max_line_length: 1024 * 1024,
    };
    assert_eq!(config.host, "127.0.0.1");
    assert_eq!(config.port, 9500);
    assert!(config.auto_reconnect);
}

// ===========================================================================
// Stream line parsing tests
// ===========================================================================

#[tokio::test]
async fn test_parse_chunk_line() {
    use ainos_sdk::streaming::parse_chunk_line;

    let line = r#"{"type":"InferenceChunk","chunk":"Hello","done":false}"#;
    let chunk = parse_chunk_line(line).unwrap();
    assert_eq!(chunk.chunk, "Hello");
    assert!(!chunk.done);

    let line = r#"{"type":"InferenceChunk","chunk":"","done":true}"#;
    let chunk = parse_chunk_line(line).unwrap();
    assert!(chunk.chunk.is_empty());
    assert!(chunk.done);
}

#[tokio::test]
async fn test_parse_chunk_line_error() {
    use ainos_sdk::streaming::parse_chunk_line;

    let line = r#"{"type":"Error","code":429,"message":"Rate limited"}"#;
    let result = parse_chunk_line(line);
    assert!(result.is_err());
    match result.unwrap_err() {
        AinosError::DaemonError { code, .. } => assert_eq!(code, 429),
        e => panic!("Expected DaemonError with code 429, got: {}", e),
    }
}

// ===========================================================================
// Accumulate chunks tests
// ===========================================================================

#[tokio::test]
async fn test_accumulate_chunks() {
    use ainos_sdk::streaming::accumulate_chunks;

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

#[tokio::test]
async fn test_accumulate_chunks_error() {
    use ainos_sdk::streaming::accumulate_chunks;

    let chunks: Vec<Result<InferenceChunk>> = vec![
        Ok(InferenceChunk {
            chunk: "Hello".into(),
            done: false,
        }),
        Err(AinosError::Inference("Something went wrong".into())),
    ];

    let result = accumulate_chunks(chunks);
    assert!(result.is_err());
}

// ===========================================================================
// Backpressure buffer tests
// ===========================================================================

#[tokio::test]
async fn test_backpressure_buffer() {
    use ainos_sdk::streaming::BackpressureBuffer;

    let mut buf = BackpressureBuffer::new(100);

    assert!(buf.try_reserve(50));
    assert_eq!(buf.utilization(), 0.5);
    assert!(!buf.try_reserve(60)); // would exceed capacity
    assert_eq!(buf.dropped_count(), 1);

    buf.release(50);
    assert_eq!(buf.utilization(), 0.0);

    buf.reset();
    assert_eq!(buf.dropped_count(), 0);
}

// ===========================================================================
// Session expiry tests
// ===========================================================================

#[tokio::test]
async fn test_session_expiry() {
    let session = Session {
        session_token: "tok".into(),
        success: true,
        message: "OK".into(),
        permissions: vec![],
        session_ttl_seconds: 3600,
        created_at: 0, // epoch — definitely expired
    };
    assert!(session.is_expired());
}

#[tokio::test]
async fn test_session_no_expiry() {
    let session = Session {
        session_token: "tok".into(),
        success: true,
        message: "OK".into(),
        permissions: vec![],
        session_ttl_seconds: 0, // no expiry
        created_at: 0,
    };
    assert!(!session.is_expired());
}

#[tokio::test]
async fn test_session_ttl_remaining() {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs();
    let session = Session {
        session_token: "tok".into(),
        success: true,
        message: "OK".into(),
        permissions: vec![],
        session_ttl_seconds: 3600,
        created_at: now - 100, // 100 seconds ago
    };
    let remaining = session.ttl_remaining();
    assert!(remaining.as_secs() > 3400); // ~3500 seconds remaining
    assert!(remaining.as_secs() <= 3600);
}

// ===========================================================================
// Permission check tests
// ===========================================================================

#[tokio::test]
async fn test_permission_check_ok() {
    let session = Session {
        session_token: "tok".into(),
        success: true,
        message: "OK".into(),
        permissions: vec!["infer".into(), "status".into()],
        session_ttl_seconds: 3600,
        created_at: 1000,
    };
    assert!(ainos_sdk::auth::check_permission(&session, "infer").is_ok());
    assert!(ainos_sdk::auth::check_permission(&session, "status").is_ok());
}

#[tokio::test]
async fn test_permission_check_denied() {
    let session = Session {
        session_token: "tok".into(),
        success: true,
        message: "OK".into(),
        permissions: vec!["infer".into()],
        session_ttl_seconds: 3600,
        created_at: 1000,
    };
    assert!(ainos_sdk::auth::check_permission(&session, "admin").is_err());
}

#[tokio::test]
async fn test_permission_check_empty_is_all() {
    let session = Session {
        session_token: "tok".into(),
        success: true,
        message: "OK".into(),
        permissions: vec![], // empty = all permissions
        session_ttl_seconds: 3600,
        created_at: 1000,
    };
    assert!(ainos_sdk::auth::check_permission(&session, "anything").is_ok());
}

#[tokio::test]
async fn test_permission_check_wildcard() {
    let session = Session {
        session_token: "tok".into(),
        success: true,
        message: "OK".into(),
        permissions: vec!["*".into()], // wildcard = all permissions
        session_ttl_seconds: 3600,
        created_at: 1000,
    };
    assert!(ainos_sdk::auth::check_permission(&session, "anything").is_ok());
}

// ===========================================================================
// Secure string tests
// ===========================================================================

#[tokio::test]
async fn test_secure_string() {
    use ainos_sdk::auth::SecureString;

    let s = SecureString::new("my-api-key-12345");
    assert_eq!(s.as_str(), "my-api-key-12345");

    let debug = format!("{:?}", s);
    assert_eq!(debug, "SecureString(***)");

    let s2: SecureString = "another-key".into();
    assert_eq!(s2.as_str(), "another-key");
}

// ===========================================================================
// NDJSON codec tests
// ===========================================================================

#[tokio::test]
async fn test_ndjson_codec() {
    use ainos_sdk::transport::NdjsonCodec;
    use bytes::BytesMut;

    let encoded = NdjsonCodec::encode(r#"{"type":"Status"}"#);
    let expected = br#"{"type":"Status"}"#.to_vec();
    let mut with_newline = expected.clone();
    with_newline.push(b'\n');
    assert_eq!(encoded, with_newline);

    let mut buf = BytesMut::from("line1\nline2\nline3\n");
    let lines = NdjsonCodec::decode(&mut buf);
    assert_eq!(lines.len(), 3);
    assert_eq!(lines[0], "line1");
    assert_eq!(lines[1], "line2");
    assert_eq!(lines[2], "line3");
    assert!(buf.is_empty());
}

#[tokio::test]
async fn test_ndjson_codec_partial() {
    use ainos_sdk::transport::NdjsonCodec;
    use bytes::BytesMut;

    let mut buf = BytesMut::from("complete\nincomplete");
    let lines = NdjsonCodec::decode(&mut buf);
    assert_eq!(lines.len(), 1);
    assert_eq!(lines[0], "complete");
    assert_eq!(&buf[..], b"incomplete");
}

#[tokio::test]
async fn test_ndjson_codec_empty_lines() {
    use ainos_sdk::transport::NdjsonCodec;
    use bytes::BytesMut;

    let mut buf = BytesMut::from("a\n\n\nb\n");
    let lines = NdjsonCodec::decode(&mut buf);
    assert_eq!(lines.len(), 2);
    assert_eq!(lines[0], "a");
    assert_eq!(lines[1], "b");
}

// ===========================================================================
// Connection pool tests
// ===========================================================================

#[tokio::test]
async fn test_connection_pool_creation() {
    // This test only verifies the struct exists and compiles
    // Actual pool creation requires a real daemon
    use ainos_sdk::transport::ConnectionPool;

    // Just verify the type exists
    let _pool: std::mem::MaybeUninit<ConnectionPool> = std::mem::MaybeUninit::uninit();
}

// ===========================================================================
// Builder edge cases
// ===========================================================================

#[tokio::test]
#[should_panic(expected = "InferenceRequest: prompt is required")]
async fn test_inference_request_missing_prompt() {
    InferenceRequest::builder().build();
}

#[tokio::test]
#[should_panic(expected = "ModelLoadOptions: path is required")]
async fn test_model_load_missing_path() {
    ModelLoadOptions::builder().build();
}

#[tokio::test]
#[should_panic(expected = "host:port format")]
async fn test_client_builder_invalid_addr() {
    AinosClient::builder().addr("no-colon");
}

// ===========================================================================
// Integration: full workflow
// ===========================================================================

#[tokio::test]
async fn test_full_workflow() {
    let (client, handle) = mock_client().await;

    // 1. Authenticate
    handle.add_response(
        r#"{"type":"AuthResponse","success":true,"session_token":"tok_full","message":"OK","permissions":["infer","model_ops","status","context"],"session_ttl_seconds":3600}"#,
    );
    client.authenticate("test-token").await.unwrap();
    assert!(client.is_authenticated().await);

    // 2. List models
    handle.add_response(
        r#"{"type":"ModelListResponse","models":[
            {"id":"m1","name":"m1.gguf","path":"/m1.gguf","size_mb":1024,"loaded":true,"architecture":"auto"}
        ]}"#,
    );
    let models = client.model_list().await.unwrap();
    assert_eq!(models.len(), 1);

    // 3. Run inference
    handle.add_response(
        r#"{"type":"InferenceResponse","output":"Hello!","tokens_generated":1,"inference_ms":50,"source":"local"}"#,
    );
    let req = InferenceRequest::builder().prompt("Hi").build();
    let resp = client.infer(&req).await.unwrap();
    assert_eq!(resp.output, "Hello!");

    // 4. Check status
    handle.add_response(
        r#"{"type":"StatusResponse","uptime":3600,"models_loaded":1,"total_requests":100,"network_available":true,"active_sessions":1}"#,
    );
    let status = client.status().await.unwrap();
    assert_eq!(status.models_loaded, 1);

    // 5. Store context
    handle.add_response(
        r#"{"type":"InferenceResponse","output":"Context stored","tokens_generated":0,"inference_ms":0,"source":"local"}"#,
    );
    client.context_store("sess", "k", b"v", 3600).await.unwrap();

    // 6. Retrieve context
    handle.add_response(
        r#"{"type":"InferenceResponse","output":"v","tokens_generated":0,"inference_ms":0,"source":"local"}"#,
    );
    let val = client.context_retrieve("sess", "k").await.unwrap();
    assert_eq!(val, Some(b"v".to_vec()));

    // 7. Health check
    handle.add_response(
        r#"{"type":"StatusResponse","uptime":3600,"models_loaded":1,"total_requests":101,"network_available":true,"active_sessions":1}"#,
    );
    let health = client.health().await.unwrap();
    assert!(health.healthy);

    // 8. Disconnect
    client.disconnect().await.unwrap();
    assert!(!client.is_connected().await);
}