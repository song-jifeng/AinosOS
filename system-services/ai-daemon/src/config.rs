// Ainos AI Daemon - Configuration
//
// This module provides the configuration types for the AI Daemon.
// It includes:
// - Base daemon configuration (DaemonConfig)
// - Authentication configuration (AuthConfig)
// - Rate limiting configuration (RateLimitConfig)
// - TLS configuration (TlsConfig)
// - Config file loading and default generation

use serde::{Deserialize, Serialize};

/// AI Daemon 配置
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DaemonConfig {
    // 基本配置
    /// 模型存储目录
    pub models_dir: String,
    /// 默认模型名称
    pub default_model: String,
    /// IPC Socket 路径
    pub socket_path: String,

    // 本地推理配置
    /// 是否启用本地推理
    pub enable_local: bool,
    /// 本地推理引擎 (ggml / onnx)
    pub local_engine: String,
    /// 最大并行推理数
    pub max_concurrent_inferences: u32,
    /// 模型缓存大小 (MB)
    pub model_cache_size_mb: u32,
    /// 推理超时 (秒)
    pub inference_timeout_secs: u32,

    // 云端回退配置
    /// 是否启用云端回退
    pub enable_cloud: bool,
    /// 云端 API 端点
    pub cloud_api_url: String,
    /// 云端 API Key
    pub cloud_api_key: String,
    /// 云端模型名称
    pub cloud_model: String,
    /// 网络检测间隔 (秒)
    pub network_check_interval: u32,
    /// 切换阈值 (本地推理置信度低于此值则用云端)
    pub cloud_fallback_confidence: f32,

    // 上下文管理
    /// 上下文存储目录
    pub context_dir: String,
    /// 最大上下文数
    pub max_contexts: u32,
    /// 上下文 TTL (天)
    pub context_ttl_days: u32,

    // 日志和安全
    /// 日志级别
    pub log_level: String,
    /// 审计日志路径
    pub audit_log: String,
    /// 是否记录所有推理请求
    pub audit_all_requests: bool,

    // TLS 配置
    /// 是否启用 TLS 加密
    pub enable_tls: bool,
    /// TLS 证书路径
    pub tls_cert_path: String,
    /// TLS 私钥路径
    pub tls_key_path: String,

    // Authentication 配置
    /// 认证配置
    #[serde(default)]
    pub auth: AuthConfig,

    // Rate limiting 配置
    /// 速率限制配置
    #[serde(default)]
    pub ratelimit: RateLimitConfig,

    // TLS 详细配置
    /// TLS 详细配置
    #[serde(default)]
    pub tls: TlsConfig,
}

impl Default for DaemonConfig {
    fn default() -> Self {
        // 使用环境变量 AINOS_HOME 覆盖默认基路径，默认使用相对路径
        let ainos_home = std::env::var("AINOS_HOME").unwrap_or_else(|_| {
            if cfg!(windows) { "D:\\Ainos\\.ainos-data".to_string() } else { "/var/lib/ainos".to_string() }
        });
        let data_dir = format!("{}/data", ainos_home);
        let log_dir = format!("{}/logs", ainos_home);
        let models_dir = format!("{}/models", ainos_home);

        #[cfg(windows)]
        let (socket_path, context_dir, audit_log) = {
            (format!("127.0.0.1:9500"),
             format!("{}/contexts", data_dir),
             format!("{}/audit.log", log_dir))
        };
        #[cfg(not(windows))]
        let (socket_path, context_dir, audit_log) = {
            ("/var/run/ainos/ai-daemon.sock".to_string(),
             format!("{}/contexts", data_dir),
             format!("{}/audit.log", log_dir))
        };

        Self {
            models_dir,
            default_model: "phi-3-mini-4k-instruct-q4.gguf".to_string(),
            socket_path,

            enable_local: true,
            local_engine: "ggml".to_string(),
            max_concurrent_inferences: 2,
            model_cache_size_mb: 4096,
            inference_timeout_secs: 120,

            enable_cloud: true,
            cloud_api_url: "https://api.weelinking.com/v1".to_string(),
            cloud_api_key: "".to_string(),
            cloud_model: "gpt-5.6-sol".to_string(),
            network_check_interval: 30,
            cloud_fallback_confidence: 0.6,

            context_dir,
            max_contexts: 1000,
            context_ttl_days: 30,

            log_level: "info".to_string(),
            audit_log,
            audit_all_requests: false,

            enable_tls: false,
            tls_cert_path: format!("{}/certs/server.crt", ainos_home),
            tls_key_path: format!("{}/certs/server.key", ainos_home),

            auth: AuthConfig::default(),
            ratelimit: RateLimitConfig::default(),
            tls: TlsConfig::default(),
        }
    }
}

/// 认证配置
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuthConfig {
    /// 是否启用认证
    #[serde(default = "default_true")]
    pub enabled: bool,
    /// 静态 Bearer Token (空字符串则自动生成)
    #[serde(default)]
    pub token: String,
    /// Token 文件路径 (用于持久化自动生成的 token)
    #[serde(default)]
    pub token_path: String,
    /// Session TTL (秒)
    #[serde(default = "default_session_ttl")]
    pub session_ttl_seconds: u64,
    /// 权限配置文件路径 (可选)
    #[serde(default)]
    pub permissions_file: String,
    /// 默认权限列表 (认证后授予)
    #[serde(default)]
    pub default_permissions: Vec<String>,
    /// 审计日志路径
    #[serde(default)]
    pub audit_log_path: String,
    /// 是否记录所有请求
    #[serde(default)]
    pub audit_all_requests: bool,
}

fn default_true() -> bool { true }
fn default_session_ttl() -> u64 { 3600 }

impl Default for AuthConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            token: String::new(),
            token_path: String::new(),
            session_ttl_seconds: 3600,
            permissions_file: String::new(),
            default_permissions: Vec::new(),
            audit_log_path: String::new(),
            audit_all_requests: false,
        }
    }
}

/// 速率限制配置
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RateLimitConfig {
    /// 是否启用速率限制
    #[serde(default = "default_true")]
    pub enabled: bool,
    /// 推理请求速率 (请求/秒)
    #[serde(default = "default_infer_rps")]
    pub infer_rps: f64,
    /// 推理突发大小
    #[serde(default = "default_infer_burst")]
    pub infer_burst: f64,
    /// 模型操作速率 (请求/秒)
    #[serde(default = "default_model_rps")]
    pub model_rps: f64,
    /// 模型操作突发大小
    #[serde(default = "default_model_burst")]
    pub model_burst: f64,
    /// 状态查询速率 (请求/秒)
    #[serde(default = "default_status_rps")]
    pub status_rps: f64,
    /// 状态查询突发大小
    #[serde(default = "default_status_burst")]
    pub status_burst: f64,
    /// 管理操作速率 (请求/秒)
    #[serde(default = "default_admin_rps")]
    pub admin_rps: f64,
    /// 管理操作突发大小
    #[serde(default = "default_admin_burst")]
    pub admin_burst: f64,
    /// 最大客户端数
    #[serde(default = "default_max_clients")]
    pub max_clients: usize,
    /// 清理间隔 (秒)
    #[serde(default = "default_cleanup_interval")]
    pub cleanup_interval_secs: u64,
}

fn default_infer_rps() -> f64 { 100.0 }
fn default_infer_burst() -> f64 { 200.0 }
fn default_model_rps() -> f64 { 10.0 }
fn default_model_burst() -> f64 { 20.0 }
fn default_status_rps() -> f64 { 1000.0 }
fn default_status_burst() -> f64 { 2000.0 }
fn default_admin_rps() -> f64 { 5.0 }
fn default_admin_burst() -> f64 { 10.0 }
fn default_max_clients() -> usize { 1000 }
fn default_cleanup_interval() -> u64 { 300 }

impl Default for RateLimitConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            infer_rps: 100.0,
            infer_burst: 200.0,
            model_rps: 10.0,
            model_burst: 20.0,
            status_rps: 1000.0,
            status_burst: 2000.0,
            admin_rps: 5.0,
            admin_burst: 10.0,
            max_clients: 1000,
            cleanup_interval_secs: 300,
        }
    }
}

/// TLS 详细配置
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TlsConfig {
    /// 是否启用 TLS
    #[serde(default)]
    pub enabled: bool,
    /// TLS 证书路径 (PEM)
    #[serde(default)]
    pub cert_path: String,
    /// TLS 私钥路径 (PEM)
    #[serde(default)]
    pub key_path: String,
    /// 是否验证客户端证书
    #[serde(default)]
    pub verify_client: bool,
}

impl Default for TlsConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            cert_path: String::new(),
            key_path: String::new(),
            verify_client: false,
        }
    }
}

/// 加载配置文件
pub async fn load_config(path: &str) -> anyhow::Result<DaemonConfig> {
    let content = tokio::fs::read_to_string(path).await?;
    let config: DaemonConfig = toml::from_str(&content)?;
    Ok(config)
}

/// 生成默认配置文件
pub fn generate_default_config() -> String {
    let config = DaemonConfig::default();
    toml::to_string_pretty(&config).expect("Failed to serialize config")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_auth_config_default() {
        let cfg = AuthConfig::default();
        assert!(cfg.enabled);
        assert!(cfg.token.is_empty());
        assert_eq!(cfg.session_ttl_seconds, 3600);
    }

    #[test]
    fn test_rate_limit_config_default() {
        let cfg = RateLimitConfig::default();
        assert!(cfg.enabled);
        assert_eq!(cfg.infer_rps, 100.0);
        assert_eq!(cfg.infer_burst, 200.0);
        assert_eq!(cfg.model_rps, 10.0);
        assert_eq!(cfg.model_burst, 20.0);
        assert_eq!(cfg.status_rps, 1000.0);
        assert_eq!(cfg.status_burst, 2000.0);
        assert_eq!(cfg.admin_rps, 5.0);
        assert_eq!(cfg.admin_burst, 10.0);
        assert_eq!(cfg.max_clients, 1000);
        assert_eq!(cfg.cleanup_interval_secs, 300);
    }

    #[test]
    fn test_tls_config_default() {
        let cfg = TlsConfig::default();
        assert!(!cfg.enabled);
        assert!(!cfg.verify_client);
        assert!(cfg.cert_path.is_empty());
        assert!(cfg.key_path.is_empty());
    }

    #[test]
    fn test_daemon_config_default_includes_new_sections() {
        let cfg = DaemonConfig::default();
        assert!(cfg.auth.enabled);
        assert!(cfg.ratelimit.enabled);
        assert!(!cfg.tls.enabled);
    }

    #[test]
    fn test_auth_config_serialization() {
        let cfg = AuthConfig {
            enabled: true,
            token: "my-token".to_string(),
            token_path: "/tmp/token.txt".to_string(),
            session_ttl_seconds: 7200,
            permissions_file: "".to_string(),
            default_permissions: vec!["infer".to_string(), "status".to_string()],
            audit_log_path: "/var/log/ainos/audit.log".to_string(),
            audit_all_requests: true,
        };
        let json = serde_json::to_string(&cfg).unwrap();
        assert!(json.contains("my-token"));
        assert!(json.contains("infer"));
        assert!(json.contains("audit_all_requests"));
    }

    #[test]
    fn test_rate_limit_config_serialization() {
        let cfg = RateLimitConfig::default();
        let json = serde_json::to_string(&cfg).unwrap();
        assert!(json.contains("infer_rps"));
        assert!(json.contains("100.0"));
    }

    #[test]
    fn test_tls_config_serialization() {
        let cfg = TlsConfig {
            enabled: true,
            cert_path: "/etc/ainos/cert.pem".to_string(),
            key_path: "/etc/ainos/key.pem".to_string(),
            verify_client: true,
        };
        let json = serde_json::to_string(&cfg).unwrap();
        assert!(json.contains("cert.pem"));
        assert!(json.contains("verify_client"));
    }

    #[test]
    fn test_daemon_config_serialization_roundtrip() {
        let cfg = DaemonConfig::default();
        let toml_str = toml::to_string_pretty(&cfg).unwrap();
        let deserialized: DaemonConfig = toml::from_str(&toml_str).unwrap();
        assert_eq!(deserialized.models_dir, cfg.models_dir);
        assert_eq!(deserialized.auth.enabled, cfg.auth.enabled);
        assert_eq!(deserialized.ratelimit.enabled, cfg.ratelimit.enabled);
        assert_eq!(deserialized.tls.enabled, cfg.tls.enabled);
    }

    #[test]
    fn test_generate_default_config_contains_new_sections() {
        let config_str = generate_default_config();
        assert!(config_str.contains("[auth]"));
        assert!(config_str.contains("[ratelimit]"));
        assert!(config_str.contains("[tls]"));
    }
}