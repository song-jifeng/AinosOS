// Ainos AI Daemon - Configuration

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
}

impl Default for DaemonConfig {
    fn default() -> Self {
        #[cfg(windows)]
        let (models_dir, socket_path, context_dir, audit_log) = {
            ("D:\\Ainos\\models".to_string(),
             "127.0.0.1:9500".to_string(),
             "D:\\Ainos\\data\\contexts".to_string(),
             "D:\\Ainos\\logs\\audit.log".to_string())
        };
        #[cfg(not(windows))]
        let (models_dir, socket_path, context_dir, audit_log) = {
            ("/var/lib/ainos/models".to_string(),
             "/var/run/ainos/ai-daemon.sock".to_string(),
             "/var/lib/ainos/contexts".to_string(),
             "/var/log/ainos/audit.log".to_string())
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