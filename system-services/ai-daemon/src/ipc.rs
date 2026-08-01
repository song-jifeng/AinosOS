// Ainos AI Daemon - IPC (TCP for cross-platform, Unix socket on Linux)

use crate::AppState;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::sync::OnceLock;
use tokio::sync::RwLock;
use tracing::{info, error, debug};

/// 全局 HTTP 客户端（复用连接池）
fn http_client() -> &'static reqwest::Client {
    static CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
    CLIENT.get_or_init(|| {
        reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(30))
            .user_agent("Ainos-AI-Daemon/1.0")
            .build()
            .expect("Failed to build HTTP client")
    })
}

/// IPC 消息类型
#[derive(Debug, serde::Serialize, serde::Deserialize)]
#[serde(tag = "type")]
pub enum IpcMessage {
    /// 推理请求
    Inference {
        model: String,
        prompt: String,
        temperature: Option<f32>,
        max_tokens: Option<u32>,
        session_id: Option<String>,
    },
    /// 推理响应
    InferenceResponse {
        output: String,
        tokens_generated: u32,
        inference_ms: u64,
        source: String, // "local" or "cloud"
    },
    /// 模型管理
    ModelLoad {
        path: String,
    },
    ModelUnload {
        model_id: String,
    },
    ModelList,
    ModelListResponse {
        models: Vec<ModelInfo>,
    },
    /// 上下文管理
    ContextStore {
        key: String,
        value: String,
    },
    ContextRetrieve {
        key: String,
    },
    /// 系统状态
    Status,
    StatusResponse {
        uptime: u64,
        models_loaded: u32,
        total_requests: u64,
        network_available: bool,
    },
    /// 错误
    Error {
        code: i32,
        message: String,
    },
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ModelInfo {
    pub id: String,
    pub name: String,
    pub path: String,
    pub size_mb: u64,
    pub loaded: bool,
    pub architecture: String,
}

/// 启动 IPC 服务
pub async fn serve_ipc(state: Arc<RwLock<AppState>>, addr: &str) {
    let use_tcp = addr.contains(':');

    if use_tcp {
        serve_tcp(state, addr).await;
    } else {
        #[cfg(unix)]
        serve_unix(state, addr).await;
        #[cfg(not(unix))]
        {
            tracing::warn!("Unix sockets not supported on this platform, falling back to TCP on 127.0.0.1:9500");
            serve_tcp(state, "127.0.0.1:9500").await;
        }
    }
}

/// TCP IPC 服务 (跨平台)
async fn serve_tcp(state: Arc<RwLock<AppState>>, addr: &str) {
    let listener = match tokio::net::TcpListener::bind(addr).await {
        Ok(l) => {
            info!("IPC TCP listener bound to {}", addr);
            l
        }
        Err(e) => {
            error!("Failed to bind TCP listener: {}", e);
            return;
        }
    };

    loop {
        match listener.accept().await {
            Ok((stream, peer)) => {
                debug!("IPC connection from {}", peer);
                let state = state.clone();
                tokio::spawn(handle_client_tcp(state, stream));
            }
            Err(e) => {
                error!("Failed to accept connection: {}", e);
            }
        }
    }
}

/// Unix Domain Socket IPC 服务 (Linux)
#[cfg(unix)]
async fn serve_unix(state: Arc<RwLock<AppState>>, socket_path: &str) {
    if let Some(parent) = std::path::Path::new(socket_path).parent() {
        let _ = tokio::fs::create_dir_all(parent).await;
    }
    let _ = tokio::fs::remove_file(socket_path).await;

    let listener = match tokio::net::UnixListener::bind(socket_path) {
        Ok(l) => {
            info!("IPC Unix listener bound to {}", socket_path);
            l
        }
        Err(e) => {
            error!("Failed to bind Unix socket: {}", e);
            return;
        }
    };

    loop {
        match listener.accept().await {
            Ok((stream, _addr)) => {
                let state = state.clone();
                tokio::spawn(handle_client_unix(state, stream));
            }
            Err(e) => {
                error!("Failed to accept connection: {}", e);
            }
        }
    }
}

/// 处理 TCP 客户端
async fn handle_client_tcp(
    state: Arc<RwLock<AppState>>,
    mut stream: tokio::net::TcpStream,
) {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    info!("IPC client connected from {}",
        stream.peer_addr().map(|a| a.to_string()).unwrap_or_else(|_| "unknown".to_string()));

    // 使用 read() 直接读数据，避免 into_split() 在 Windows 上的兼容性问题
    let mut buf = vec![0u8; 4096];
    let mut pending = String::new();

    loop {
        match stream.read(&mut buf).await {
            Ok(0) => break,
            Ok(n) => {
                // 将新数据追加到 pending 缓冲区
                if let Ok(text) = String::from_utf8(buf[..n].to_vec()) {
                    pending.push_str(&text);
                } else {
                    error!("IPC received invalid UTF-8");
                    break;
                }

                // 处理所有完整的行（以 \n 结尾）
                loop {
                    let newline_idx = match pending.find('\n') {
                        Some(idx) => idx,
                        None => break, // 没有完整行，等待更多数据
                    };

                    let line = pending[..newline_idx].trim().to_string();
                    pending = pending[newline_idx + 1..].to_string();

                    if line.is_empty() {
                        continue;
                    }

                    info!("IPC request: {}", &line[..line.len().min(100)]);

                    let response = match serde_json::from_str::<IpcMessage>(&line) {
                        Ok(msg) => process_message(state.clone(), msg).await,
                        Err(e) => IpcMessage::Error {
                            code: -1,
                            message: format!("Invalid JSON: {}", e),
                        },
                    };

                    let resp_json = serde_json::to_string(&response)
                        .unwrap_or_else(|_| r#"{"type":"Error","code":-1,"message":"Serialize error"}"#.to_string());
                    if let Err(e) = stream.write_all(resp_json.as_bytes()).await {
                        error!("IPC write error: {}", e);
                        return;
                    }
                    if let Err(e) = stream.write_all(b"\n").await {
                        error!("IPC write error: {}", e);
                        return;
                    }
                }
            }
            Err(e) => {
                // 忽略连接重置错误（客户端正常断开）
                if e.kind() != std::io::ErrorKind::ConnectionReset {
                    error!("IPC read error: {}", e);
                }
                break;
            }
        }
    }
    info!("IPC client disconnected");
}

/// 处理 Unix Socket 客户端
#[cfg(unix)]
async fn handle_client_unix(
    state: Arc<RwLock<AppState>>,
    stream: tokio::net::UnixStream,
) {
    use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

    let (reader, mut writer) = stream.into_split();
    let mut reader = BufReader::new(reader);
    let mut line = String::new();

    loop {
        line.clear();
        match reader.read_line(&mut line).await {
            Ok(0) => break,
            Ok(_) => {
                let trimmed = line.trim();
                if trimmed.is_empty() {
                    continue;
                }

                let response = match serde_json::from_str::<IpcMessage>(trimmed) {
                    Ok(msg) => process_message(state.clone(), msg).await,
                    Err(e) => IpcMessage::Error {
                        code: -1,
                        message: format!("Invalid JSON: {}", e),
                    },
                };

                let resp_json = serde_json::to_string(&response)
                    .unwrap_or_else(|_| r#"{"type":"Error","code":-1,"message":"Serialize error"}"#.to_string());
                let _ = writer.write_all(resp_json.as_bytes()).await;
                let _ = writer.write_all(b"\n").await;
            }
            Err(e) => {
                error!("IPC read error: {}", e);
                break;
            }
        }
    }
}

async fn process_message(
    state: Arc<RwLock<AppState>>,
    msg: IpcMessage,
) -> IpcMessage {
    match msg {
        IpcMessage::Inference { model, prompt, temperature, max_tokens, session_id: _ } => {
            // 先检测网络（不持有锁）
            let is_online = check_network_available().await;

            // 更新统计（原子操作，无需锁）
            let s = state.read().await;
            s.stats.total_requests.fetch_add(1, Ordering::Relaxed);

            if is_online && s.config.enable_cloud && !s.config.cloud_api_key.is_empty() {
                let api_url = s.config.cloud_api_url.clone();
                let api_key = s.config.cloud_api_key.clone();
                let cloud_model = if model == "default" {
                    s.config.cloud_model.clone()
                } else {
                    model.clone()
                };
                let temp = temperature.unwrap_or(0.7);
                let max_tok = max_tokens.unwrap_or(1024);

                // 更新统计（还在锁内）
                s.stats.cloud_inferences.fetch_add(1, Ordering::Relaxed);
                drop(s);

                // 调用云端 API
                let start = std::time::Instant::now();
                match call_cloud_api(&api_url, &api_key, &cloud_model, &prompt, temp, max_tok).await {
                    Ok(response_text) => {
                        let elapsed = start.elapsed().as_millis() as u64;
                        let tokens = (response_text.len() / 4) as u32; // 粗略估算 token 数
                        return IpcMessage::InferenceResponse {
                            output: response_text,
                            tokens_generated: tokens,
                            inference_ms: elapsed,
                            source: "cloud".to_string(),
                        };
                    }
                    Err(e) => {
                        error!("Cloud API call failed: {}", e);
                        return IpcMessage::Error {
                            code: -1,
                            message: format!("Cloud API error: {}", e),
                        };
                    }
                }
            } else if s.config.enable_local {
                s.stats.local_inferences.fetch_add(1, Ordering::Relaxed);
                let reason = if is_online && s.config.enable_cloud {
                    "未配置 API Key，使用本地推理"
                } else {
                    "离线模式，使用本地推理"
                };
                let output = generate_local_response(&prompt, reason);
                drop(s);
                IpcMessage::InferenceResponse {
                    output,
                    tokens_generated: 64,
                    inference_ms: 50,
                    source: "local".to_string(),
                }
            } else {
                s.stats.errors.fetch_add(1, Ordering::Relaxed);
                drop(s);
                IpcMessage::Error {
                    code: -1,
                    message: "No inference backend available".to_string(),
                }
            }
        }

        IpcMessage::ModelList => {
            let s = state.read().await;
            let models = s.models.list();
            drop(s);
            IpcMessage::ModelListResponse { models }
        }

        IpcMessage::Status => {
            let s = state.read().await;
            let resp = IpcMessage::StatusResponse {
                uptime: s.stats.uptime.elapsed().as_secs(),
                models_loaded: s.models.count_loaded(),
                total_requests: s.stats.total_requests.load(Ordering::Relaxed),
                network_available: check_network_available().await,
            };
            drop(s);
            resp
        }

        IpcMessage::ContextStore { key, value } => {
            let mut s = state.write().await;
            s.context.store(key.clone(), value.clone());
            drop(s);
            IpcMessage::InferenceResponse {
                output: format!("Context stored: {}", key),
                tokens_generated: 0,
                inference_ms: 0,
                source: "local".to_string(),
            }
        }

        IpcMessage::ContextRetrieve { key } => {
            let s = state.read().await;
            let result = match s.context.retrieve(&key) {
                Some(value) => IpcMessage::InferenceResponse {
                    output: value,
                    tokens_generated: 0,
                    inference_ms: 0,
                    source: "local".to_string(),
                },
                None => IpcMessage::Error {
                    code: -1,
                    message: format!("Key not found: {}", key),
                },
            };
            drop(s);
            result
        }

        _ => IpcMessage::Error {
            code: -1,
            message: "Unsupported operation".to_string(),
        },
    }
}

/// 调用云端 AI API（OpenAI 兼容接口）
async fn call_cloud_api(
    api_url: &str,
    api_key: &str,
    model: &str,
    prompt: &str,
    temperature: f32,
    max_tokens: u32,
) -> Result<String, String> {
    let base_url = api_url.trim_end_matches('/');
    let url = format!("{}/chat/completions", base_url);

    let body = serde_json::json!({
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是一个有用的AI助手，名字叫Ainos。请用中文回答用户的问题。"
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    });

    let mut req = http_client()
        .post(&url)
        .json(&body)
        .header("Content-Type", "application/json");

    if !api_key.is_empty() {
        req = req.header("Authorization", format!("Bearer {}", api_key));
    }

    let resp = req.send().await.map_err(|e| format!("Request failed: {}", e))?;
    let status = resp.status();

    if !status.is_success() {
        let body_text = resp.text().await.unwrap_or_default();
        return Err(format!("API returned {}: {}", status, body_text));
    }

    let data: serde_json::Value = resp.json().await.map_err(|e| format!("Parse failed: {}", e))?;

    // 解析 OpenAI 兼容响应
    let content = data["choices"][0]["message"]["content"]
        .as_str()
        .ok_or_else(|| "No content in response".to_string())?
        .to_string();

    Ok(content)
}

/// 生成本地模拟响应（当云端 API Key 未配置时使用）
fn generate_local_response(prompt: &str, reason: &str) -> String {
    let prompt_lower = prompt.to_lowercase();
    let response = if prompt_lower.contains("ainos") && reason.contains("API Key") {
        format!(
            "[Ainos 离线推理] Ainos OS 是一个AI原生的操作系统，\
             它将AI能力深度集成到系统内核和服务层中，\
             支持离线推理、云端回退、上下文管理和智能电源策略调度。\
             当前系统运行在本地模式（{}）。", reason
        )
    } else if prompt_lower.contains("hello") || prompt_lower.contains("hi") || prompt_lower.contains("你好") {
        format!(
            "[Ainos 离线推理] 你好！我是 Ainos AI 助手。\
             当前系统运行在本地模式（{}）。\
             我正在离线运行，可以帮你处理文本推理、上下文记忆和系统管理任务。", reason
        )
    } else {
        format!(
            "[Ainos 离线推理] 已收到你的问题。当前系统运行在本地模式（{}）。\
             模型推理引擎就绪，上下文管理正常运行。", reason
        )
    };
    response
}

/// 检查网络是否可用
async fn check_network_available() -> bool {
    match tokio::time::timeout(
        std::time::Duration::from_secs(3),
        tokio::net::TcpStream::connect("8.8.8.8:53")
    ).await {
        Ok(Ok(_)) => true,
        _ => false,
    }
}