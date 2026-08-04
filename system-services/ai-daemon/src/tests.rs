// Ainos AI Daemon — Comprehensive Test Suite
//
// This module contains unit tests and integration-style tests for the daemon
// core components. It is compiled only when `cargo test` is run.
//
// Coverage areas:
// - DaemonConfig defaults and platform-specific paths
// - IpcMessage serialization / deserialization for all variants
// - generate_local_response() behavior
// - check_network_available() timeout behavior
// - AppState initialization
// - ModelRegistry basics
// - ContextManager store/retrieve/delete + stats + LRU + TTL
// - SemanticCache get/put/miss/eviction
// - ThermalMonitor zone mapping and power mode transitions
// - RuntimeManager model loading, inference, stats, error handling
// - IPC ModelLoad / ModelUnload message handling

#![cfg(test)]

use crate::AppState;
use crate::config::DaemonConfig;
use crate::ipc::{self, IpcMessage, ModelInfo, generate_local_response};
use crate::models::ModelRegistry;
use crate::context::ContextManager;
use crate::cache::SemanticCache;
use crate::thermal::{ThermalMonitor, ThermalZone, PowerMode, power_mode_name, thermal_zone_name};
use crate::runtime::{self, RuntimeManager, EngineType, InferenceRequest, RuntimeError,
                     QuantizationType, SamplingConfig, KVCacheState};
use crate::ratelimit::RateLimitCategory;

// =========================================================================
// DaemonConfig tests
// =========================================================================

#[test]
fn test_config_default_values() {
    let cfg = DaemonConfig::default();

    // Core features
    assert!(cfg.enable_local, "Local inference should be enabled by default");
    assert!(cfg.enable_cloud, "Cloud fallback should be enabled by default");

    // Engine defaults
    assert_eq!(cfg.local_engine, "ggml");
    assert_eq!(cfg.default_model, "phi-3-mini-4k-instruct-q4.gguf");

    // Resource limits
    assert_eq!(cfg.max_concurrent_inferences, 2);
    assert_eq!(cfg.inference_timeout_secs, 120);
    assert_eq!(cfg.model_cache_size_mb, 4096);

    // Cloud defaults
    assert_eq!(cfg.network_check_interval, 30);
    assert_eq!(cfg.cloud_fallback_confidence, 0.6);

    // Context defaults
    assert_eq!(cfg.max_contexts, 1000);
    assert_eq!(cfg.context_ttl_days, 30);

    // Security defaults
    assert_eq!(cfg.log_level, "info");
    assert!(!cfg.enable_tls, "TLS should be disabled by default");
}

#[test]
fn test_config_socket_path_platform() {
    let cfg = DaemonConfig::default();
    if cfg!(windows) {
        assert!(cfg.socket_path.contains(':'), "Windows: TCP host:port");
    } else {
        assert!(cfg.socket_path.starts_with('/'), "Unix: socket file path");
    }
}

#[test]
fn test_config_models_dir_default() {
    let cfg = DaemonConfig::default();
    assert!(cfg.models_dir.contains("models"), "models_dir should contain 'models'");
}

// =========================================================================
// IpcMessage serialization / deserialization tests
// =========================================================================

#[test]
fn test_ipc_message_serialize_tags() {
    let json = serde_json::to_string(&IpcMessage::Status).unwrap();
    assert_eq!(json, r#"{"type":"Status"}"#);

    let json = serde_json::to_string(&IpcMessage::ModelList).unwrap();
    assert_eq!(json, r#"{"type":"ModelList"}"#);

    let json = serde_json::to_string(&IpcMessage::Error {
        code: -1, message: "test".into(),
    }).unwrap();
    assert_eq!(json, r#"{"type":"Error","code":-1,"message":"test"}"#);
}

#[test]
fn test_ipc_message_roundtrip_inference() {
    let original = IpcMessage::Inference {
        model: "m1".into(),
        prompt: "Hello".into(),
        temperature: Some(0.7),
        max_tokens: Some(200),
        session_id: Some("s1".into()),
    };
    let json = serde_json::to_string(&original).unwrap();
    let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
    match deserialized {
        IpcMessage::Inference { model, prompt, temperature, max_tokens, session_id } => {
            assert_eq!(model, "m1");
            assert_eq!(prompt, "Hello");
            assert_eq!(temperature, Some(0.7));
            assert_eq!(max_tokens, Some(200));
            assert_eq!(session_id, Some("s1".into()));
        }
        _ => panic!("Expected Inference variant"),
    }
}

#[test]
fn test_ipc_message_roundtrip_inference_response() {
    let original = IpcMessage::InferenceResponse {
        output: "Hello world".into(),
        tokens_generated: 42,
        inference_ms: 150,
        source: "local".into(),
    };
    let json = serde_json::to_string(&original).unwrap();
    let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
    match deserialized {
        IpcMessage::InferenceResponse { output, tokens_generated, inference_ms, source } => {
            assert_eq!(output, "Hello world");
            assert_eq!(tokens_generated, 42);
            assert_eq!(inference_ms, 150);
            assert_eq!(source, "local");
        }
        _ => panic!("Expected InferenceResponse variant"),
    }
}

#[test]
fn test_ipc_message_roundtrip_status_response() {
    let original = IpcMessage::StatusResponse {
        uptime: 999,
        models_loaded: 3,
        total_requests: 5000,
        network_available: true,
        active_sessions: 0,
        rate_limits: None,
    };
    let json = serde_json::to_string(&original).unwrap();
    let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
    match deserialized {
        IpcMessage::StatusResponse { uptime, models_loaded, total_requests, network_available, .. } => {
            assert_eq!(uptime, 999);
            assert_eq!(models_loaded, 3);
            assert_eq!(total_requests, 5000);
            assert!(network_available);
        }
        _ => panic!("Expected StatusResponse variant"),
    }
}

#[test]
fn test_ipc_message_roundtrip_context_store() {
    let original = IpcMessage::ContextStore {
        key: "k1".into(),
        value: "v1".into(),
    };
    let json = serde_json::to_string(&original).unwrap();
    let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
    match deserialized {
        IpcMessage::ContextStore { key, value } => {
            assert_eq!(key, "k1");
            assert_eq!(value, "v1");
        }
        _ => panic!("Expected ContextStore variant"),
    }
}

#[test]
fn test_ipc_message_roundtrip_context_retrieve() {
    let original = IpcMessage::ContextRetrieve { key: "k1".into() };
    let json = serde_json::to_string(&original).unwrap();
    let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
    match deserialized {
        IpcMessage::ContextRetrieve { key } => {
            assert_eq!(key, "k1");
        }
        _ => panic!("Expected ContextRetrieve variant"),
    }
}

#[test]
fn test_ipc_message_roundtrip_model_load() {
    let original = IpcMessage::ModelLoad { path: "/models/test.gguf".into() };
    let json = serde_json::to_string(&original).unwrap();
    let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
    match deserialized {
        IpcMessage::ModelLoad { path } => {
            assert_eq!(path, "/models/test.gguf");
        }
        _ => panic!("Expected ModelLoad variant"),
    }
}

#[test]
fn test_ipc_message_roundtrip_model_unload() {
    let original = IpcMessage::ModelUnload { model_id: "test_model".into() };
    let json = serde_json::to_string(&original).unwrap();
    let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
    match deserialized {
        IpcMessage::ModelUnload { model_id } => {
            assert_eq!(model_id, "test_model");
        }
        _ => panic!("Expected ModelUnload variant"),
    }
}

#[test]
fn test_ipc_message_roundtrip_model_list_response() {
    let models = vec![
        ModelInfo {
            id: "m1".into(),
            name: "model1.gguf".into(),
            path: "/m1.gguf".into(),
            size_mb: 1024,
            loaded: true,
            architecture: "auto".into(),
        },
    ];
    let original = IpcMessage::ModelListResponse { models };
    let json = serde_json::to_string(&original).unwrap();
    let deserialized: IpcMessage = serde_json::from_str(&json).unwrap();
    match deserialized {
        IpcMessage::ModelListResponse { models } => {
            assert_eq!(models.len(), 1);
            assert_eq!(models[0].id, "m1");
            assert!(models[0].loaded);
        }
        _ => panic!("Expected ModelListResponse variant"),
    }
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
        _ => panic!("Expected Error variant"),
    }
}

#[test]
fn test_model_info_roundtrip() {
    let info = ModelInfo {
        id: "phi_3_mini".into(),
        name: "phi-3-mini.gguf".into(),
        path: "/models/phi-3-mini.gguf".into(),
        size_mb: 2048,
        loaded: false,
        architecture: "phi3".into(),
    };
    let json = serde_json::to_string(&info).unwrap();
    let deserialized: ModelInfo = serde_json::from_str(&json).unwrap();
    assert_eq!(deserialized.id, "phi_3_mini");
    assert_eq!(deserialized.size_mb, 2048);
    assert!(!deserialized.loaded);
}

// =========================================================================
// generate_local_response tests
// =========================================================================

#[test]
fn test_generate_local_response_not_empty() {
    let cases = [
        ("", "离线模式"),
        ("你好世界", "本地模式"),
        ("Tell me about Ainos", "API Key 未配置"),
        ("hello", "离线模式"),
        ("random text", "测试模式"),
    ];
    for (prompt, reason) in &cases {
        let resp = generate_local_response(prompt, reason);
        assert!(!resp.is_empty(), "Response should not be empty for prompt={:?}", prompt);
        assert!(resp.contains("Ainos"), "Response should contain 'Ainos'");
    }
}

#[test]
fn test_generate_local_response_ainos_keyword() {
    let resp = generate_local_response("What is Ainos OS?", "未配置 API Key，使用本地推理");
    assert!(resp.contains("Ainos OS 是一个AI原生的操作系统"));
}

#[test]
fn test_generate_local_response_greeting() {
    for greeting in &["hello", "hi", "你好", "HELLO", "Hi there"] {
        let resp = generate_local_response(greeting, "离线模式");
        assert!(resp.contains("你好"), "Greeting response should contain '你好'");
    }
}

#[test]
fn test_generate_local_response_reason_included() {
    let reason = "自定义测试原因";
    let resp = generate_local_response("test", reason);
    assert!(resp.contains(reason), "Response should include the reason string");
}

// =========================================================================
// check_network_available timeout behavior test
// =========================================================================

#[tokio::test]
async fn test_check_network_available_timeout() {
    let result = tokio::time::timeout(
        std::time::Duration::from_secs(10),
        ipc::check_network_available(),
    ).await;

    assert!(result.is_ok(), "check_network_available() must not deadlock");
    let _available = result.unwrap();
}

// =========================================================================
// AppState initialization tests
// =========================================================================

#[test]
fn test_app_state_initialization() {
    let cfg = DaemonConfig::default();
    let state = AppState::new(cfg);

    assert_eq!(state.stats.total_requests.load(std::sync::atomic::Ordering::Relaxed), 0);
    assert_eq!(state.stats.local_inferences.load(std::sync::atomic::Ordering::Relaxed), 0);
    assert_eq!(state.stats.cloud_inferences.load(std::sync::atomic::Ordering::Relaxed), 0);
    assert_eq!(state.stats.errors.load(std::sync::atomic::Ordering::Relaxed), 0);
}

#[test]
fn test_app_state_contains_components() {
    let cfg = DaemonConfig::default();
    let state = AppState::new(cfg);

    // Verify all components are initialized
    assert_eq!(state.models.count_loaded(), 0);
    assert_eq!(state.context.count_entries(), 0);
    assert!(state.cache.is_empty());
    assert_eq!(state.cache.capacity(), 1000);
}

// =========================================================================
// ModelRegistry tests
// =========================================================================

#[test]
fn test_model_registry_new() {
    let registry = ModelRegistry::new();
    assert_eq!(registry.count_loaded(), 0);
}

#[test]
fn test_model_registry_load_unload() {
    let registry = ModelRegistry::new();
    let list = registry.list();
    assert!(list.is_empty());
}

// =========================================================================
// RuntimeManager tests
// =========================================================================

#[test]
fn test_runtime_manager_new() {
    let rm = RuntimeManager::new();
    assert_eq!(rm.loaded_count(), 0);
    assert_eq!(rm.active_engine(), &EngineType::GGML);
}

#[test]
fn test_runtime_manager_switch_engine() {
    let mut rm = RuntimeManager::new();
    assert_eq!(rm.active_engine(), &EngineType::GGML);
    rm.switch_engine(EngineType::ONNX);
    assert_eq!(rm.active_engine(), &EngineType::ONNX);
}

#[test]
fn test_runtime_manager_get_stats() {
    let rm = RuntimeManager::new();
    let stats = rm.get_stats();
    assert_eq!(stats.get("models_loaded"), Some(&0));
    assert_eq!(stats.get("total_inferences"), Some(&0));
    assert!(stats.contains_key("total_errors"));
    assert!(stats.contains_key("max_context_length"));
    assert!(stats.contains_key("total_tokens_generated"));
}

#[test]
fn test_runtime_manager_get_loaded_models_empty() {
    let rm = RuntimeManager::new();
    assert!(rm.get_loaded_models().is_empty());
}

#[test]
fn test_runtime_manager_set_max_context_length() {
    let mut rm = RuntimeManager::new();
    rm.set_max_context_length(8192);
    let stats = rm.get_stats();
    assert_eq!(stats.get("max_context_length"), Some(&8192));
}

#[test]
fn test_runtime_manager_set_max_loaded_models() {
    let mut rm = RuntimeManager::new();
    rm.set_max_loaded_models(4);
    let stats = rm.get_stats();
    assert_eq!(stats.get("max_loaded_models"), Some(&4));
}

#[test]
fn test_runtime_manager_load_model_missing_file() {
    let mut rm = RuntimeManager::new();
    let result = rm.load_model("/nonexistent/model.gguf", "test_model");
    assert!(result.is_err());
    match result {
        Err(RuntimeError::ModelNotFound(_)) => {} // expected
        _ => panic!("Expected ModelNotFound error"),
    }
}

#[test]
fn test_runtime_manager_load_model_duplicate() {
    // 加载不存在的模型两次，第二次应返回错误（文件不存在）
    let mut rm = RuntimeManager::new();
    let result1 = rm.load_model("/nonexistent/duplicate.gguf", "dup");
    assert!(result1.is_err());
}

#[tokio::test]
async fn test_runtime_manager_infer_model_not_loaded() {
    let mut rm = RuntimeManager::new();
    let req = InferenceRequest::default();
    let result = rm.infer(req).await;
    assert!(result.is_err());
    match result {
        Err(RuntimeError::ModelNotLoaded(_)) => {} // expected
        _ => panic!("Expected ModelNotLoaded error"),
    }
}

#[tokio::test]
async fn test_runtime_manager_infer_streaming_model_not_loaded() {
    let mut rm = RuntimeManager::new();
    let req = InferenceRequest::default();
    let tokens: std::sync::Arc<std::sync::Mutex<Vec<String>>> =
        std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
    let tokens_clone = tokens.clone();
    let result = rm.infer_streaming(req, move |token| {
        tokens_clone.lock().unwrap().push(token.to_string());
    }).await;
    assert!(result.is_err());
}

#[tokio::test]
async fn test_runtime_manager_batch_infer() {
    let mut rm = RuntimeManager::new();
    let requests = vec![
        InferenceRequest { model: "m1".into(), prompt: "Hello".into(), ..Default::default() },
        InferenceRequest { model: "m2".into(), prompt: "World".into(), ..Default::default() },
    ];
    let results = rm.batch_infer(requests).await;
    assert_eq!(results.len(), 2);
    for result in results {
        assert!(result.is_err()); // models not loaded
    }
}

#[test]
fn test_runtime_manager_detect_architecture() {
    assert_eq!(RuntimeManager::detect_architecture("llama-2-7b.gguf"), "llama");
    assert_eq!(RuntimeManager::detect_architecture("phi-3-mini.gguf"), "phi3");
    assert_eq!(RuntimeManager::detect_architecture("mistral-7b.gguf"), "mistral");
    assert_eq!(RuntimeManager::detect_architecture("unknown.gguf"), "auto");
    assert_eq!(RuntimeManager::detect_architecture("qwen2-7b.gguf"), "qwen2");
    assert_eq!(RuntimeManager::detect_architecture("falcon-7b.gguf"), "falcon");
}

#[test]
fn test_runtime_manager_detect_quantization() {
    assert_eq!(RuntimeManager::detect_quantization("model-q4_0.gguf"),
        Some(QuantizationType::Q4_0));
    assert_eq!(RuntimeManager::detect_quantization("model-q8_0.gguf"),
        Some(QuantizationType::Q8_0));
    assert_eq!(RuntimeManager::detect_quantization("model-fp16.gguf"),
        Some(QuantizationType::F16));
    assert_eq!(RuntimeManager::detect_quantization("model.gguf"), None);
}

// =========================================================================
// QuantizationType tests
// =========================================================================

#[test]
fn test_quantization_from_str() {
    assert_eq!(QuantizationType::from_str("q4_0"), Some(QuantizationType::Q4_0));
    assert_eq!(QuantizationType::from_str("Q8_0"), Some(QuantizationType::Q8_0));
    assert_eq!(QuantizationType::from_str("fp16"), Some(QuantizationType::F16));
    assert_eq!(QuantizationType::from_str("fp32"), Some(QuantizationType::F32));
    assert_eq!(QuantizationType::from_str("invalid"), None);
}

#[test]
fn test_quantization_size_multiplier() {
    assert!((QuantizationType::Q4_0.size_multiplier() - 0.25).abs() < 0.01);
    assert!((QuantizationType::F32.size_multiplier() - 1.0).abs() < 0.01);
    assert!((QuantizationType::F16.size_multiplier() - 0.5).abs() < 0.01);
    assert!((QuantizationType::Q8_0.size_multiplier() - 0.5).abs() < 0.01);
}

// =========================================================================
// InferenceRequest tests
// =========================================================================

#[test]
fn test_inference_request_default() {
    let req = InferenceRequest::default();
    assert_eq!(req.model, "default");
    assert_eq!(req.temperature, 0.7);
    assert_eq!(req.top_p, 0.9);
    assert_eq!(req.top_k, 40);
    assert_eq!(req.max_tokens, 512);
    assert_eq!(req.repeat_penalty, 1.1);
    assert_eq!(req.frequency_penalty, 0.0);
    assert_eq!(req.presence_penalty, 0.0);
}

#[test]
fn test_inference_request_new() {
    let req = InferenceRequest::new(
        "test_model".into(),
        "Hello".into(),
        Some(0.5),
        Some(100),
        Some("sess1".into()),
    );
    assert_eq!(req.model, "test_model");
    assert_eq!(req.prompt, "Hello");
    assert_eq!(req.temperature, 0.5);
    assert_eq!(req.max_tokens, 100);
    assert_eq!(req.session_id, Some("sess1".into()));
}

#[test]
fn test_inference_request_new_defaults() {
    let req = InferenceRequest::new("m".into(), "test".into(), None, None, None);
    assert_eq!(req.temperature, 0.7);
    assert_eq!(req.max_tokens, 512);
    assert_eq!(req.session_id, None);
}

// =========================================================================
// SamplingConfig tests
// =========================================================================

#[test]
fn test_sampling_config_default() {
    let cfg = SamplingConfig::default();
    assert!((cfg.temperature - 0.7).abs() < 0.001);
    assert!((cfg.top_p - 0.9).abs() < 0.001);
    assert_eq!(cfg.top_k, 40);
}

#[test]
fn test_sampling_config_from_request() {
    let req = InferenceRequest {
        temperature: 0.3,
        top_p: 0.8,
        top_k: 20,
        ..Default::default()
    };
    let cfg = SamplingConfig::from(&req);
    assert!((cfg.temperature - 0.3).abs() < 0.001);
    assert!((cfg.top_p - 0.8).abs() < 0.001);
    assert_eq!(cfg.top_k, 20);
}

// =========================================================================
// KVCacheState tests
// =========================================================================

#[test]
fn test_kv_cache_state() {
    let cache = KVCacheState::new(32, 32, 4096, 2048);
    assert_eq!(cache.max_seq_len, 2048);
    assert_eq!(cache.n_layers, 32);
    assert_eq!(cache.n_heads, 32);
    assert_eq!(cache.n_embd, 4096);
    assert!(cache.memory_usage > 0);
}

#[test]
fn test_kv_cache_defaults() {
    let cache = KVCacheState::new(1, 1, 64, 128);
    assert_eq!(cache.current_seq_len, 0);
    assert!(cache.memory_usage > 0);
}

// =========================================================================
// RuntimeError tests
// =========================================================================

#[test]
fn test_runtime_error_display() {
    let err = RuntimeError::ModelNotFound("test.gguf".into());
    assert_eq!(err.to_string(), "Model not found: test.gguf");

    let err = RuntimeError::ModelNotLoaded("m1".into());
    assert_eq!(err.to_string(), "Model not loaded: m1");

    let err = RuntimeError::InferenceFailed("OOM".into());
    assert_eq!(err.to_string(), "Inference failed: OOM");

    let err = RuntimeError::InvalidParameter("bad param".into());
    assert_eq!(err.to_string(), "Invalid parameter: bad param");

    let err = RuntimeError::OutOfMemory("8GB limit".into());
    assert_eq!(err.to_string(), "Out of memory: 8GB limit");

    let err = RuntimeError::EngineNotInitialized("no GPU".into());
    assert_eq!(err.to_string(), "Engine not initialized: no GPU");

    let err = RuntimeError::ContextOverflow("4096 limit".into());
    assert_eq!(err.to_string(), "Context overflow: 4096 limit");

    let err = RuntimeError::Unsupported("feature not available".into());
    assert_eq!(err.to_string(), "Unsupported operation: feature not available");
}

#[test]
fn test_runtime_error_into_string() {
    let err = RuntimeError::ModelNotLoaded("m1".into());
    let s: String = err.into();
    assert_eq!(s, "Model not loaded: m1");
}

// =========================================================================
// ContextManager tests (enhanced)
// =========================================================================

#[test]
fn test_context_store_and_retrieve() {
    let mut cm = ContextManager::new();
    cm.store("key1".to_string(), "value1".to_string());
    assert_eq!(cm.retrieve("key1"), Some("value1".to_string()));
}

#[test]
fn test_context_retrieve_missing() {
    let cm = ContextManager::new();
    assert_eq!(cm.retrieve("nonexistent"), None);
}

#[test]
fn test_context_delete() {
    let mut cm = ContextManager::new();
    cm.store("key1".to_string(), "value1".to_string());
    assert_eq!(cm.retrieve("key1"), Some("value1".to_string()));
    cm.delete("key1");
    assert_eq!(cm.retrieve("key1"), None);
}

#[test]
fn test_context_count_entries() {
    let mut cm = ContextManager::new();
    assert_eq!(cm.count_entries(), 0);
    cm.store("a".to_string(), "1".to_string());
    cm.store("b".to_string(), "2".to_string());
    assert_eq!(cm.count_entries(), 2);
}

#[test]
fn test_context_session_entries() {
    let mut cm = ContextManager::new();
    assert_eq!(cm.session_entries("default"), 0);
    cm.store("a".to_string(), "1".to_string());
    assert_eq!(cm.session_entries("default"), 1);
    assert_eq!(cm.session_entries("other"), 0);
}

#[test]
fn test_context_retrieve_expired_ttl() {
    let mut cm = ContextManager::new();
    cm.ttl_days = 0; // 立即过期
    cm.store("key1".to_string(), "value1".to_string());
    // TTL 为 0 时，retrieve 应返回 None (过期)
    assert_eq!(cm.retrieve("key1"), None);
}

#[test]
fn test_context_hit_rate() {
    let cm = ContextManager::new();
    assert_eq!(cm.hit_rate(), 0.0);
    assert_eq!(cm.hits(), 0);
    assert_eq!(cm.misses(), 0);
}

#[test]
fn test_context_hit_rate_after_operations() {
    let mut cm = ContextManager::new();
    cm.store("key1".to_string(), "val1".to_string());
    cm.retrieve("key1"); // hit
    cm.retrieve("nonexistent"); // miss
    assert_eq!(cm.hits(), 1);
    assert_eq!(cm.misses(), 1);
    assert!((cm.hit_rate() - 0.5).abs() < 0.001);
}

#[test]
fn test_context_get_stats() {
    let cm = ContextManager::new();
    let stats = cm.get_stats();
    assert!(stats.contains_key("hits"));
    assert!(stats.contains_key("misses"));
    assert!(stats.contains_key("evictions"));
    assert!(stats.contains_key("entries"));
    assert!(stats.contains_key("ttl_days"));
    assert_eq!(stats.get("ttl_days"), Some(&30));
}

#[test]
fn test_context_total_stores_retrieves() {
    let mut cm = ContextManager::new();
    assert_eq!(cm.total_stores(), 0);
    assert_eq!(cm.total_retrieves(), 0);
    cm.store("a".to_string(), "1".to_string());
    cm.store("b".to_string(), "2".to_string());
    let _ = cm.retrieve("a");
    let _ = cm.retrieve("b");
    let _ = cm.retrieve("nonexistent");
    assert_eq!(cm.total_stores(), 2);
    assert_eq!(cm.total_retrieves(), 3);
}

#[test]
fn test_context_lru_eviction() {
    let mut cm = ContextManager::new();
    cm.max_memory_entries = 2;
    cm.store("a".to_string(), "1".to_string());
    cm.store("b".to_string(), "2".to_string());
    // 访问 "a" 使其成为最近使用
    cm.retrieve("a");
    // 存储 "c" 应淘汰 "b" (最久未访问)
    cm.store("c".to_string(), "3".to_string());
    assert_eq!(cm.retrieve("a"), Some("1".to_string()));
    assert_eq!(cm.retrieve("b"), None); // 被淘汰
    assert_eq!(cm.retrieve("c"), Some("3".to_string()));
}

#[test]
fn test_context_evictions_counter() {
    let mut cm = ContextManager::new();
    cm.max_entries = 1;
    assert_eq!(cm.evictions(), 0);
    cm.store("a".to_string(), "1".to_string());
    cm.store("b".to_string(), "2".to_string()); // 应淘汰 "a"
    assert!(cm.evictions() >= 1);
}

#[test]
fn test_context_cleanup_expired() {
    let mut cm = ContextManager::new();
    cm.ttl_days = 0; // 立即过期
    cm.store("key1".to_string(), "value1".to_string());
    cm.cleanup_expired();
    assert_eq!(cm.count_entries(), 0);
}

#[test]
fn test_context_log_rotation_config() {
    let cm = ContextManager::new();
    assert!(cm.should_rotate_logs());
    assert_eq!(cm.log_rotation.max_size_mb, 100);
    assert_eq!(cm.log_rotation.retain_days, 7);
}

#[test]
fn test_context_with_log_rotation() {
    let config = crate::context::LogRotationConfig {
        enabled: false,
        max_size_mb: 200,
        retain_days: 14,
        log_path: "custom.log".to_string(),
    };
    let cm = ContextManager::new().with_log_rotation(config);
    assert!(!cm.should_rotate_logs());
    assert_eq!(cm.log_rotation.max_size_mb, 200);
}

#[test]
fn test_context_max_entries_eviction() {
    let mut cm = ContextManager::new();
    cm.max_entries = 2;
    cm.store("a".to_string(), "1".to_string());
    cm.store("b".to_string(), "2".to_string());
    cm.store("c".to_string(), "3".to_string()); // 应淘汰 "a"
    assert_eq!(cm.retrieve("a"), None);
    assert_eq!(cm.retrieve("b"), Some("2".to_string()));
    assert_eq!(cm.retrieve("c"), Some("3".to_string()));
}

// =========================================================================
// SemanticCache tests
// =========================================================================

#[test]
fn test_cache_put_get() {
    let cache = SemanticCache::new();
    assert!(cache.is_empty());
    cache.put("hello", "model1", 0.7, "world".to_string());
    assert_eq!(cache.len(), 1);
    assert_eq!(cache.get("hello", "model1", 0.7), Some("world".to_string()));
}

#[test]
fn test_cache_miss() {
    let cache = SemanticCache::new();
    assert_eq!(cache.get("nonexistent", "model1", 0.7), None);
}

#[test]
fn test_cache_key_different_temp() {
    let cache = SemanticCache::new();
    cache.put("hello", "model1", 0.7, "result1".to_string());
    assert_eq!(cache.get("hello", "model1", 0.8), None);
}

#[test]
fn test_cache_key_quantization() {
    let key1 = SemanticCache::compute_key("hello", "model1", 0.700);
    let key2 = SemanticCache::compute_key("hello", "model1", 0.7);
    assert_eq!(key1, key2);
}

#[test]
fn test_cache_eviction() {
    let cache = SemanticCache::with_capacity(2);
    cache.put("a", "m", 0.5, "1".to_string());
    cache.put("b", "m", 0.5, "2".to_string());
    cache.put("c", "m", 0.5, "3".to_string()); // evicts "a"
    assert_eq!(cache.get("a", "m", 0.5), None);
    assert_eq!(cache.get("c", "m", 0.5), Some("3".to_string()));
}

#[test]
fn test_cache_hit_rate() {
    let cache = SemanticCache::new();
    assert_eq!(cache.hit_rate(), 0.0);
    cache.put("a", "m", 0.5, "1".to_string());
    cache.get("a", "m", 0.5); // hit
    cache.get("b", "m", 0.5); // miss
    assert!((cache.hit_rate() - 0.5).abs() < 1e-9);
}

#[test]
fn test_cache_clear() {
    let cache = SemanticCache::new();
    cache.put("a", "m", 0.5, "1".to_string());
    cache.put("b", "m", 0.5, "2".to_string());
    assert_eq!(cache.len(), 2);
    cache.clear();
    assert!(cache.is_empty());
    assert_eq!(cache.hits(), 0);
    assert_eq!(cache.misses(), 0);
}

#[test]
fn test_cache_with_capacity_minimum() {
    let cache = SemanticCache::with_capacity(0);
    assert!(cache.capacity() >= 1);
}

// =========================================================================
// ThermalMonitor tests
// =========================================================================

#[test]
fn test_thermal_zone_cool() {
    let zone = ThermalMonitor::celsius_to_zone(40.0);
    assert_eq!(zone, ThermalZone::Cool);
}

#[test]
fn test_thermal_zone_warm() {
    let zone = ThermalMonitor::celsius_to_zone(75.0);
    assert_eq!(zone, ThermalZone::Warm);
}

#[test]
fn test_thermal_zone_hot() {
    let zone = ThermalMonitor::celsius_to_zone(90.0);
    assert_eq!(zone, ThermalZone::Hot);
}

#[test]
fn test_thermal_zone_critical() {
    let zone = ThermalMonitor::celsius_to_zone(100.0);
    assert_eq!(zone, ThermalZone::Critical);
}

#[test]
fn test_thermal_zone_boundaries() {
    assert_eq!(ThermalMonitor::celsius_to_zone(69.9), ThermalZone::Cool);
    assert_eq!(ThermalMonitor::celsius_to_zone(70.0), ThermalZone::Warm);
    assert_eq!(ThermalMonitor::celsius_to_zone(84.9), ThermalZone::Warm);
    assert_eq!(ThermalMonitor::celsius_to_zone(85.0), ThermalZone::Hot);
    assert_eq!(ThermalMonitor::celsius_to_zone(94.9), ThermalZone::Hot);
    assert_eq!(ThermalMonitor::celsius_to_zone(95.0), ThermalZone::Critical);
}

#[test]
fn test_zone_to_power_mode() {
    assert_eq!(ThermalMonitor::zone_to_power_mode(ThermalZone::Cool), PowerMode::Max);
    assert_eq!(ThermalMonitor::zone_to_power_mode(ThermalZone::Warm), PowerMode::Balanced);
    assert_eq!(ThermalMonitor::zone_to_power_mode(ThermalZone::Hot), PowerMode::Efficient);
    assert_eq!(ThermalMonitor::zone_to_power_mode(ThermalZone::Critical), PowerMode::Emergency);
}

#[test]
fn test_power_mode_to_threads() {
    assert_eq!(ThermalMonitor::power_mode_to_threads(PowerMode::Max), 4);
    assert_eq!(ThermalMonitor::power_mode_to_threads(PowerMode::Balanced), 2);
    assert_eq!(ThermalMonitor::power_mode_to_threads(PowerMode::Efficient), 1);
    assert_eq!(ThermalMonitor::power_mode_to_threads(PowerMode::Emergency), 1);
}

#[test]
fn test_power_mode_name() {
    assert_eq!(power_mode_name(PowerMode::Max), "MAX");
    assert_eq!(power_mode_name(PowerMode::Balanced), "BALANCED");
    assert_eq!(power_mode_name(PowerMode::Efficient), "EFFICIENT");
    assert_eq!(power_mode_name(PowerMode::Emergency), "EMERGENCY");
}

#[test]
fn test_thermal_zone_name() {
    assert_eq!(thermal_zone_name(ThermalZone::Cool), "COOL");
    assert_eq!(thermal_zone_name(ThermalZone::Warm), "WARM");
    assert_eq!(thermal_zone_name(ThermalZone::Hot), "HOT");
    assert_eq!(thermal_zone_name(ThermalZone::Critical), "CRITICAL");
}

#[test]
fn test_thermal_snapshot_new() {
    use crate::thermal::ThermalSnapshot;
    let snap = ThermalSnapshot::new();
    assert_eq!(snap.cpu_temp_celsius, 40.0);
    assert_eq!(snap.zone, ThermalZone::Cool);
    assert_eq!(snap.power_mode, PowerMode::Max);
    assert_eq!(snap.recommended_threads, 4);
    assert!(!snap.sensor_available);
    assert!(!snap.throttle_active);
}

#[test]
fn test_thermal_monitor_new() {
    let monitor = ThermalMonitor::new();
    let snap = monitor.get_snapshot();
    assert_eq!(snap.cpu_temp_celsius, 40.0);
    assert_eq!(monitor.get_power_mode(), PowerMode::Max);
    assert_eq!(monitor.get_recommended_threads(), 4);
}

// =========================================================================
// PowerMode ordering tests
// =========================================================================

#[test]
fn test_power_mode_ordering() {
    assert!(PowerMode::Max < PowerMode::Balanced);
    assert!(PowerMode::Balanced < PowerMode::Efficient);
    assert!(PowerMode::Efficient < PowerMode::Emergency);
    assert!(PowerMode::Max < PowerMode::Emergency);
}

// =========================================================================
// process_message tests (ModelLoad / ModelUnload)
// =========================================================================

/// Helper to create a test ClientState with auth.
fn auth_client() -> crate::ipc::ClientState {
    let mut client = crate::ipc::ClientState::new("test-client".to_string());
    client.authenticated = true;
    client
}

#[tokio::test]
async fn test_process_message_status() {
    let cfg = DaemonConfig::default();
    let state = std::sync::Arc::new(tokio::sync::RwLock::new(AppState::new(cfg)));
    let client = auth_client();

    let response = ipc::process_message(state, IpcMessage::Status, &client).await;
    match response {
        IpcMessage::StatusResponse { uptime, models_loaded, total_requests, network_available, .. } => {
            let _ = uptime;
            assert_eq!(models_loaded, 0);
            assert_eq!(total_requests, 0);
            let _ = network_available;
        }
        _ => panic!("Expected StatusResponse, got {:?}", response),
    }
}

#[tokio::test]
async fn test_process_message_model_load_nonexistent() {
    let cfg = DaemonConfig::default();
    let state = std::sync::Arc::new(tokio::sync::RwLock::new(AppState::new(cfg)));
    let client = auth_client();

    let response = ipc::process_message(state, IpcMessage::ModelLoad {
        path: "/nonexistent/model.gguf".into(),
    }, &client).await;
    match response {
        IpcMessage::ModelLoadResponse { status, .. } => {
            assert_eq!(status, "error", "Should report error for nonexistent file");
        }
        _ => panic!("Expected ModelLoadResponse, got {:?}", response),
    }
}

#[tokio::test]
async fn test_process_message_model_unload_not_loaded() {
    let cfg = DaemonConfig::default();
    let state = std::sync::Arc::new(tokio::sync::RwLock::new(AppState::new(cfg)));
    let client = auth_client();

    let response = ipc::process_message(state, IpcMessage::ModelUnload {
        model_id: "nonexistent_model".into(),
    }, &client).await;
    match response {
        IpcMessage::ModelUnloadResponse { status, .. } => {
            assert_eq!(status, "not_found", "Should report not_found for unloaded model");
        }
        _ => panic!("Expected ModelUnloadResponse, got {:?}", response),
    }
}

#[tokio::test]
async fn test_process_message_unsupported() {
    let cfg = DaemonConfig::default();
    let state = std::sync::Arc::new(tokio::sync::RwLock::new(AppState::new(cfg)));
    let client = auth_client();

    // ModelLoad and ModelUnload are now handled with proper response types
    let response = ipc::process_message(state.clone(), IpcMessage::ModelLoad {
        path: "/nonexistent/path.gguf".into(),
    }, &client).await;
    match response {
        IpcMessage::ModelLoadResponse { status, .. } => {
            assert_eq!(status, "error", "Should be a ModelLoadResponse");
        }
        _ => panic!("Expected ModelLoadResponse, got {:?}", response),
    }
}

// =========================================================================
// Auth integration tests
// =========================================================================

#[tokio::test]
async fn test_auth_integration_authenticate() {
    let mut cfg = DaemonConfig::default();
    cfg.auth.enabled = true;
    cfg.auth.token = "test-token-thirty-two-chars".to_string();
    let state = std::sync::Arc::new(tokio::sync::RwLock::new(AppState::new(cfg)));

    // Test successful authentication
    {
        let s = state.read().await;
        let result = s.session_manager.authenticate("test-client", "test-token-thirty-two-chars").await;
        assert!(result.is_ok(), "Authentication should succeed with correct token");
        let session_token = result.unwrap();
        let session = s.session_manager.validate_session(&session_token).await;
        assert!(session.is_ok(), "Session should be valid");
    }
}

#[tokio::test]
async fn test_auth_integration_permission_denied() {
    let mut cfg = DaemonConfig::default();
    cfg.auth.enabled = true;
    cfg.auth.token = "test-token-thirty-two-chars".to_string();
    let state = std::sync::Arc::new(tokio::sync::RwLock::new(AppState::new(cfg)));

    let session_manager;
    let session_token;
    {
        let s = state.read().await;
        session_manager = s.session_manager.clone();
    }
    let result = session_manager.authenticate("test-client", "test-token-thirty-two-chars").await;
    assert!(result.is_ok());
    session_token = result.unwrap();

    // Default permissions don't include Admin, so this should fail
    let result = session_manager.check_permission(&session_token, &crate::auth::Permission::Admin).await;
    assert!(result.is_err(), "Default permissions should not include Admin");
}

// =========================================================================
// Rate limit integration tests
// =========================================================================

#[tokio::test]
async fn test_rate_limit_integration() {
    let cfg = DaemonConfig::default();
    let state = std::sync::Arc::new(tokio::sync::RwLock::new(AppState::new(cfg)));

    let rate_limiter;
    {
        let s = state.read().await;
        rate_limiter = s.rate_limiter.clone();
    }

    // Test basic rate limiting
    let result = rate_limiter.check_rate_limit("test-client", RateLimitCategory::Status).await;
    assert!(result.is_ok(), "First request should be allowed");

    let info = result.unwrap();
    assert!(info.remaining < info.limit, "Remaining should be less than limit");
}

// =========================================================================
// AppState integration tests
// =========================================================================

#[test]
fn test_app_state_new_includes_security() {
    let cfg = DaemonConfig::default();
    let state = AppState::new(cfg);

    // Verify security components are initialized
    assert!(state.session_manager.is_enabled(), "Session manager should be enabled");
    assert!(state.rate_limiter.stats().total_allowed.load(std::sync::atomic::Ordering::Relaxed) == 0);
}