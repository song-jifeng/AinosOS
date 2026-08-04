# AinosOS IPC 协议规范 / AinosOS IPC Protocol Specification

> **版本 / Version:** 1.0.0
> **最后更新 / Last Updated:** 2026-08-04
> **源文件 / Source Files:**
> - `D:/Ainos/system-services/ai-daemon/src/ipc.rs`
> - `D:/Ainos/system-services/ai-daemon/src/ipc_windows.rs`
> - `D:/Ainos/system-services/ai-daemon/src/auth.rs`
> - `D:/Ainos/system-services/ai-daemon/src/ratelimit.rs`
> - `D:/Ainos/system-services/ai-daemon/src/tls.rs`
> - `D:/Ainos/system-services/ai-daemon/src/config.rs`
> - `D:/Ainos/system-services/ai-daemon/src/main.rs`

---

# 目录 / Table of Contents

1. [IPC 协议概述 / IPC Protocol Overview](#1-ipc-协议概述--ipc-protocol-overview)
2. [消息类型与格式 / Message Types and Formats](#2-消息类型与格式--message-types-and-formats)
3. [认证协议 / Authentication Protocol](#3-认证协议--authentication-protocol)
4. [速率限制 / Rate Limiting](#4-速率限制--rate-limiting)
5. [错误码 / Error Codes](#5-错误码--error-codes)
6. [完整示例 / Complete Examples](#6-完整示例--complete-examples)

---

# 1. IPC 协议概述 / IPC Protocol Overview

## 1.1 传输层 / Transport Layer

AinosOS AI 守护进程支持多种传输协议，以适应不同平台的需求：

| 传输方式 | 平台 | 默认地址 | 描述 |
|---------|------|---------|------|
| TCP | 跨平台 (Windows/Linux/macOS) | `127.0.0.1:9500` | 跨平台兼容，默认回退方案 |
| Unix Domain Socket | Linux | `/var/run/ainos/ai-daemon.sock` | 高性能，低延迟 |
| Named Pipe | Windows | `\\.\pipe\ainos-daemon` | Windows 原生 IPC |
| XPC | macOS | `xpc://com.ainos.daemon.xpc` | macOS 原生 IPC |
| launchd | macOS | `launchd://Listener` | macOS 启动套接字激活 |

### 传输选择逻辑 / Transport Selection Logic

源文件: `D:/Ainos/system-services/ai-daemon/src/ipc.rs` (第 263-295 行)

```rust
// Ainos AI Daemon - IPC Transport Selection
// 地址格式决定传输方式：
// - 包含 `:` 的地址 → TCP
// - 不包含 `:` 的地址 → Unix Domain Socket (Linux)
// - `xpc://` 前缀 → macOS XPC
// - `launchd://` 前缀 → macOS launchd 套接字激活

pub async fn serve_ipc(state: Arc<RwLock<AppState>>, addr: &str) {
    // macOS XPC transport
    #[cfg(target_os = "macos")]
    if addr.starts_with("xpc://") {
        let service_name = addr.trim_start_matches("xpc://");
        tracing::info!("Starting XPC transport for service: {}", service_name);
        serve_xpc(state, service_name).await;
        return;
    }

    // macOS launchd socket activation
    #[cfg(target_os = "macos")]
    if addr.starts_with("launchd://") {
        let socket_name = addr.trim_start_matches("launchd://");
        tracing::info!("Using launchd socket activation for: {}", socket_name);
        serve_launchd_socket(state, socket_name).await;
        return;
    }

    let use_tcp = addr.contains(':');

    if use_tcp {
        serve_tcp(state, addr).await;
    } else {
        #[cfg(unix)]
        serve_unix(state, addr).await;
        #[cfg(not(unix))]
        {
            tracing::warn!("Unix sockets not supported on this platform, \
                falling back to TCP on 127.0.0.1:9500");
            serve_tcp(state, "127.0.0.1:9500").await;
        }
    }
}
```

### 平台特定传输 / Platform-Specific Transports

**Windows 平台**（源文件 `D:/Ainos/system-services/ai-daemon/src/main.rs` 第 174-197 行）：

```rust
#[cfg(windows)]
let ipc_handle = {
    // 优先尝试 Named Pipe（Windows 原生 IPC）
    info!("Starting Windows named pipe server on \\\\.\\pipe\\ainos-daemon");
    match ipc_windows::AsyncPipeServer::new(state.clone(), true) {
        Ok(server) => {
            let server_handle = tokio::spawn(server.serve());
            // 同时启动 TCP 9500 端口作为兼容回退
            let tcp_handle = tokio::spawn(ipc::serve_ipc(state.clone(), ipc_addr));
            tokio::spawn(async move {
                tokio::select! {
                    _ = server_handle => {},
                    _ = tcp_handle => {},
                }
            })
        }
        Err(e) => {
            error!("Failed to create named pipe server: {}. Falling back to TCP.", e);
            tokio::spawn(ipc::serve_ipc(state.clone(), ipc_addr))
        }
    }
};
```

**macOS 平台**（源文件 `D:/Ainos/system-services/ai-daemon/src/ipc.rs` 第 1100-1212 行）：

```rust
// macOS 通过 XPC 服务桥接：
// 1. macOS 应用发送 XPC 消息到 com.ainos.daemon.xpc
// 2. ainos_xpc 服务将 XPC → JSON 并发送到 TCP :9500
// 3. 守护进程处理 JSON 并将响应发送回去
// 4. ainos_xpc 服务将 JSON → XPC 并发送给应用

#[cfg(target_os = "macos")]
async fn serve_xpc(state: Arc<RwLock<AppState>>, service_name: &str) {
    tracing::info!("XPC service '{}' registered (delegating to XPC listener)", service_name);
    // 启动 TCP 监听器，让 XPC 桥接连接
    serve_tcp(state, "127.0.0.1:9500").await;
}
```

## 1.2 协议版本 / Protocol Version

- **当前版本 / Current Version:** 1.0.0
- **版本标识 / Version Identifier:** `ainos-ipc/1.0` (TLS ALPN 协议标识)
- **兼容性 / Compatibility:** 向后兼容同一主版本号内的所有消息

## 1.3 线格式 / Wire Format

### NDJSON (Newline-Delimited JSON)

- 编码方式: **UTF-8**
- 消息分隔符: **`\n`** (换行符, 0x0A)
- 每条消息独立编码为一行 JSON，尾部以换行符结束
- 空行（仅包含换行符）被静默忽略
- 每行最大长度: **10 MB** (默认)

### 消息帧 / Message Framing

源文件: `D:/Ainos/system-services/ai-daemon/src/ipc.rs` 第 438-510 行

```rust
// TCP 客户端消息处理——使用累积缓冲区逐行读取
async fn handle_client_tcp(state: Arc<RwLock<AppState>>, mut stream: tokio::net::TcpStream) {
    let mut buf = vec![0u8; 8192];
    let mut pending = String::new();

    loop {
        match stream.read(&mut buf).await {
            Ok(0) => break,
            Ok(n) => {
                // 将新数据追加到 pending 缓冲区
                if let Ok(text) = String::from_utf8(buf[..n].to_vec()) {
                    pending.push_str(&text);
                } else {
                    error!("IPC received invalid UTF-8 from {}", client_id);
                    break;
                }

                // 处理所有完整行（以 \n 结尾）
                loop {
                    let newline_idx = match pending.find('\n') {
                        Some(idx) => idx,
                        None => break, // 等待更多数据
                    };

                    let line = pending[..newline_idx].trim().to_string();
                    pending = pending[newline_idx + 1..].to_string();

                    if line.is_empty() { continue; }

                    // 解析并处理消息...
                    match serde_json::from_str::<IpcMessage>(&line) {
                        Ok(msg) => process_message(state.clone(), msg, &client).await,
                        Err(e) => IpcMessage::Error {
                            code: -1,
                            message: format!("Invalid JSON: {}", e),
                        },
                    };
                }
            }
            // ...
        }
    }
}
```

### 协议规范摘要 / Protocol Summary

| 属性 | 值 |
|------|-----|
| 传输层 | TCP / Unix Domain Socket / Named Pipe / XPC / launchd |
| 默认地址 | `127.0.0.1:9500` |
| 线格式 | NDJSON (Newline-Delimited JSON) |
| 协议版本 | 1.0.0 |
| 消息分隔符 | `\n` (0x0A) |
| 字符编码 | UTF-8 |
| 默认最大消息大小 | 10 MB |
| 认证方式 | Bearer Token (64 字符十六进制) |
| 会话管理 | UUID v4 会话令牌 |
| 安全传输 | 可选 TLS (tokio-rustls) |

## 1.4 连接生命周期 / Connection Lifecycle

```
客户端连接生命周期:

┌─────────────────────────────────────────────────────────┐
│  1. 建立连接 (Connect)                                   │
│     TCP 三次握手 / Unix Socket 连接 / Named Pipe 打开     │
│           │                                               │
│           ▼                                               │
│  2. 认证 (Auth) [可选]                                    │
│     客户端发送 Auth 消息                                   │
│     服务器验证令牌并返回 AuthResponse                      │
│     包含 session_token (UUID v4) 和权限列表                │
│           │                                               │
│           ▼                                               │
│  3. 通信 (Communicate)                                    │
│     发送请求消息 (Inference, ModelLoad, Status 等)         │
│     接收响应消息 (InferenceResponse, Error 等)             │
│     每条消息包含类型标签和会话令牌                          │
│           │                                               │
│           ▼                                               │
│  4. 断开连接 (Disconnect)                                 │
│     客户端关闭连接                                        │
│     服务器清理会话资源                                    │
│     记录审计日志                                          │
└─────────────────────────────────────────────────────────┘
```

### 连接状态管理 / Client State Management

源文件: `D:/Ainos/system-services/ai-daemon/src/ipc.rs` 第 220-237 行

```rust
/// 每个连接的客户端状态
pub(crate) struct ClientState {
    pub(crate) session_token: Option<String>,
    pub(crate) authenticated: bool,
    pub(crate) client_id: String,
}

impl ClientState {
    pub(crate) fn new(client_id: String) -> Self {
        Self { session_token: None, authenticated: false, client_id }
    }

    pub(crate) fn is_allowed(&self, msg_type: &str, auth_enabled: bool) -> bool {
        if matches!(msg_type, "Auth" | "Error") { return true; }
        if !auth_enabled { return true; }
        if self.authenticated { return true; }
        false
    }
}
```

---

# 2. 消息类型与格式 / Message Types and Formats

## 2.1 消息枚举 / Message Enum

源文件: `D:/Ainos/system-services/ai-daemon/src/ipc.rs` 第 43-187 行

所有 IPC 消息均使用 `#[serde(tag = "type")]` 进行 JSON 鉴别，即每个 JSON 对象中必须包含 `"type"` 字段来标识消息类型。

```rust
#[derive(Debug, serde::Serialize, serde::Deserialize)]
#[serde(tag = "type")]
pub enum IpcMessage {
    // ========================================================================
    // 认证 / Authentication
    // ========================================================================
    Auth     { token: String },
    AuthResponse {
        success: bool,
        #[serde(skip_serializing_if = "Option::is_none")]
        session_token: Option<String>,
        message: String,
        #[serde(default)]
        permissions: Vec<String>,
        #[serde(default)]
        session_ttl_seconds: u64,
    },

    // ========================================================================
    // 推理 / Inference
    // ========================================================================
    Inference {
        model: String,
        prompt: String,
        temperature: Option<f32>,
        max_tokens: Option<u32>,
        session_id: Option<String>,
    },
    InferenceResponse {
        output: String,
        tokens_generated: u32,
        inference_ms: u64,
        source: String,
    },
    InferenceStream {
        model: String,
        prompt: String,
        temperature: Option<f32>,
        max_tokens: Option<u32>,
        session_id: Option<String>,
    },
    InferenceChunk {
        chunk: String,
        done: bool,
    },

    // ========================================================================
    // 模型管理 / Model Management
    // ========================================================================
    ModelLoad  { path: String },
    ModelLoadResponse {
        model_id: String,
        status: String,
        message: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        model_info: Option<ModelInfo>,
    },
    ModelUnload  { model_id: String },
    ModelUnloadResponse {
        model_id: String,
        status: String,
        message: String,
    },
    ModelList,
    ModelListResponse {
        models: Vec<ModelInfo>,
    },

    // ========================================================================
    // 上下文管理 / Context Management
    // ========================================================================
    ContextStore  { key: String, value: String },
    ContextRetrieve  { key: String },

    // ========================================================================
    // 状态与健康检查 / Status & Health
    // ========================================================================
    Status,
    StatusResponse {
        uptime: u64,
        models_loaded: u32,
        total_requests: u64,
        network_available: bool,
        #[serde(default)]
        active_sessions: u32,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        rate_limits: Option<Vec<RateLimitInfoJson>>,
    },
    RateLimitStatus,

    // ========================================================================
    // 错误响应 / Error Response
    // ========================================================================
    Error { code: i32, message: String },
}
```

## 2.2 辅助数据结构 / Helper Data Structures

### ModelInfo

源文件: `D:/Ainos/system-services/ai-daemon/src/ipc.rs` 第 199-213 行

```rust
/// 描述单个模型的元数据
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ModelInfo {
    /// 唯一模型标识符 (如 `"phi_3_mini_4k_instruct_q4_gguf"`)
    pub id: String,
    /// 人类可读模型名称 (如 `"phi-3-mini-4k-instruct-q4.gguf"`)
    pub name: String,
    /// 磁盘上的绝对路径
    pub path: String,
    /// 模型文件大小（MB）
    pub size_mb: u64,
    /// 模型是否已加载到内存
    pub loaded: bool,
    /// 模型架构字符串 (如 `"auto"`, `"phi3"`, `"llama"`)
    pub architecture: String,
}
```

### RateLimitInfoJson

源文件: `D:/Ainos/system-services/ai-daemon/src/ipc.rs` 第 190-196 行

```rust
/// 用于 IPC 响应的 JSON 友好速率限制信息
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct RateLimitInfoJson {
    pub category: String,
    pub limit: u64,
    pub remaining: u64,
    pub reset_seconds: u64,
}
```

## 2.3 完整消息 JSON Schema / Complete Message JSON Schemas

### 2.3.1 Auth (认证请求)

**JSON Schema:**

```json
{
  "type": "object",
  "properties": {
    "type":   { "type": "string", "enum": ["Auth"] },
    "token":  { "type": "string", "minLength": 16, "description": "Bearer token for authentication" }
  },
  "required": ["type", "token"]
}
```

**JSON 示例:**

```json
{"type":"Auth","token":"a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"}
{"type":"Auth","token":"my-bearer-token-thirty-two-chars-minimum"}
```

### 2.3.2 AuthResponse (认证响应)

**JSON Schema:**

```json
{
  "type": "object",
  "properties": {
    "type":              { "type": "string", "enum": ["AuthResponse"] },
    "success":           { "type": "boolean" },
    "session_token":     { "type": ["string", "null"] },
    "message":           { "type": "string" },
    "permissions":       { "type": "array", "items": { "type": "string" } },
    "session_ttl_seconds": { "type": "integer", "minimum": 0 }
  },
  "required": ["type", "success", "message", "permissions", "session_ttl_seconds"]
}
```

**JSON 示例:**

```json
{"type":"AuthResponse","success":true,"session_token":"550e8400-e29b-41d4-a716-446655440000","message":"Authentication successful","permissions":["infer","status","context"],"session_ttl_seconds":3600}
{"type":"AuthResponse","success":false,"session_token":null,"message":"Authentication failed: Invalid authentication token","permissions":[],"session_ttl_seconds":0}
{"type":"AuthResponse","success":true,"session_token":"f47ac10b-58cc-4372-a567-0e02b2c3d479","message":"Auth disabled - full access granted","permissions":["all"],"session_ttl_seconds":3600}
{"type":"AuthResponse","success":false,"session_token":null,"message":"Authentication failed: Token has expired","permissions":[],"session_ttl_seconds":0}
{"type":"AuthResponse","success":true,"session_token":"6ba7b810-9dad-11d1-80b4-00c04fd430c8","message":"Authentication successful","permissions":["infer","status","context","model_load","model_unload","admin"],"session_ttl_seconds":7200}
{"type":"AuthResponse","success":false,"session_token":null,"message":"Authentication failed: No token configured","permissions":[],"session_ttl_seconds":0}
```

### 2.3.3 Inference (同步推理请求)

**JSON Schema:**

```json
{
  "type": "object",
  "properties": {
    "type":         { "type": "string", "enum": ["Inference"] },
    "model":        { "type": "string" },
    "prompt":       { "type": "string" },
    "temperature":  { "type": ["number", "null"], "minimum": 0, "maximum": 2 },
    "max_tokens":   { "type": ["integer", "null"], "minimum": 1 },
    "session_id":   { "type": ["string", "null"] }
  },
  "required": ["type", "model", "prompt"]
}
```

**JSON 示例:**

```json
{"type":"Inference","model":"default","prompt":"你好，请介绍一下Ainos OS","temperature":0.7,"max_tokens":1024,"session_id":"sess-001"}
{"type":"Inference","model":"phi-3-mini-4k-instruct-q4.gguf","prompt":"What is the capital of France?","temperature":0.5,"max_tokens":500}
{"type":"Inference","model":"default","prompt":"请用中文写一首关于AI的诗","temperature":0.8,"max_tokens":2000,"session_id":"sess-002"}
{"type":"Inference","model":"qwen-7b-q4.gguf","prompt":"Explain quantum computing in simple terms","temperature":0.3,"max_tokens":200}
{"type":"Inference","model":"default","prompt":"Hello","temperature":null,"max_tokens":null}
{"type":"Inference","model":"llama-3-8b-q4.gguf","prompt":"Summarize: The quick brown fox jumps over the lazy dog","temperature":0.7,"max_tokens":100,"session_id":"sess-003"}
```

### 2.3.4 InferenceResponse (推理响应)

**JSON Schema:**

```json
{
  "type": "object",
  "properties": {
    "type":             { "type": "string", "enum": ["InferenceResponse"] },
    "output":           { "type": "string" },
    "tokens_generated": { "type": "integer", "minimum": 0 },
    "inference_ms":     { "type": "integer", "minimum": 0 },
    "source":           { "type": "string", "enum": ["local", "cloud"] }
  },
  "required": ["type", "output", "tokens_generated", "inference_ms", "source"]
}
```

**JSON 示例:**

```json
{"type":"InferenceResponse","output":"Ainos OS 是一个AI原生的操作系统，它将AI能力深度集成到系统内核和服务层中。","tokens_generated":32,"inference_ms":150,"source":"local"}
{"type":"InferenceResponse","output":"Paris is the capital of France.","tokens_generated":8,"inference_ms":234,"source":"cloud"}
{"type":"InferenceResponse","output":"[Ainos 离线推理] 你好！我是 Ainos AI 助手。当前系统运行在本地模式（离线模式，使用本地推理）。","tokens_generated":64,"inference_ms":50,"source":"local"}
{"type":"InferenceResponse","output":"[Ainos 离线推理] Ainos OS 是一个AI原生的操作系统，它将AI能力深度集成到系统内核和服务层中，支持离线推理、云端回退、上下文管理和智能电源策略调度。当前系统运行在本地模式（未配置 API Key，使用本地推理）。","tokens_generated":64,"inference_ms":50,"source":"local"}
{"type":"InferenceResponse","output":"Here is a quantum computing primer: Quantum computing uses qubits that can exist in superposition states...","tokens_generated":128,"inference_ms":3200,"source":"cloud"}
{"type":"InferenceResponse","output":"[Ainos 离线推理] 已收到你的问题。当前系统运行在本地模式（离线模式，使用本地推理）。模型推理引擎就绪，上下文管理正常运行。","tokens_generated":64,"inference_ms":50,"source":"local"}
```

### 2.3.5 InferenceStream (流式推理请求)

**JSON Schema:**

```json
{
  "type": "object",
  "properties": {
    "type":         { "type": "string", "enum": ["InferenceStream"] },
    "model":        { "type": "string" },
    "prompt":       { "type": "string" },
    "temperature":  { "type": ["number", "null"], "minimum": 0, "maximum": 2 },
    "max_tokens":   { "type": ["integer", "null"], "minimum": 1 },
    "session_id":   { "type": ["string", "null"] }
  },
  "required": ["type", "model", "prompt"]
}
```

**JSON 示例:**

```json
{"type":"InferenceStream","model":"default","prompt":"写一个故事","temperature":0.8,"max_tokens":2000,"session_id":"stream-001"}
{"type":"InferenceStream","model":"phi-3-mini-4k-instruct-q4.gguf","prompt":"Tell me a joke","temperature":0.9,"max_tokens":300}
{"type":"InferenceStream","model":"default","prompt":"Explain the theory of relativity","temperature":0.5,"max_tokens":1000}
```

### 2.3.6 InferenceChunk (流式推理块)

**JSON Schema:**

```json
{
  "type": "object",
  "properties": {
    "type":  { "type": "string", "enum": ["InferenceChunk"] },
    "chunk": { "type": "string" },
    "done":  { "type": "boolean" }
  },
  "required": ["type", "chunk", "done"]
}
```

**JSON 示例 (流式响应序列):**

```json
{"type":"InferenceChunk","chunk":"从前","done":false}
{"type":"InferenceChunk","chunk":"有","done":false}
{"type":"InferenceChunk","chunk":"一座","done":false}
{"type":"InferenceChunk","chunk":"山","done":false}
{"type":"InferenceChunk","chunk":"，","done":false}
{"type":"InferenceChunk","chunk":"山里","done":false}
{"type":"InferenceChunk","chunk":"有","done":false}
{"type":"InferenceChunk","chunk":"一座","done":false}
{"type":"InferenceChunk","chunk":"庙","done":false}
{"type":"InferenceChunk","chunk":"。","done":false}
{"type":"InferenceChunk","chunk":"","done":true}
```

### 2.3.7 ModelLoad (模型加载请求)

**JSON Schema:**

```json
{
  "type": "object",
  "properties": {
    "type": { "type": "string", "enum": ["ModelLoad"] },
    "path": { "type": "string", "description": "Absolute path to model file" }
  },
  "required": ["type", "path"]
}
```

**JSON 示例:**

```json
{"type":"ModelLoad","path":"D:/Ainos/models/phi-3-mini-4k-instruct-q4.gguf"}
{"type":"ModelLoad","path":"/var/lib/ainos/models/qwen-7b-q4.gguf"}
{"type":"ModelLoad","path":"D:/Ainos/models/llama-3-8b-q4.gguf"}
{"type":"ModelLoad","path":"D:/Ainos/models/qwen-1.5-gguf.gguf"}
{"type":"ModelLoad","path":"/models/mistral-7b-v0.3-q4.gguf"}
```

### 2.3.8 ModelLoadResponse (模型加载响应)

**JSON Schema:**

```json
{
  "type": "object",
  "properties": {
    "type":     { "type": "string", "enum": ["ModelLoadResponse"] },
    "model_id": { "type": "string" },
    "status":   { "type": "string", "enum": ["loaded", "already_loaded", "error"] },
    "message":  { "type": "string" },
    "model_info": {
      "type": ["object", "null"],
      "properties": {
        "id":           { "type": "string" },
        "name":         { "type": "string" },
        "path":         { "type": "string" },
        "size_mb":      { "type": "integer" },
        "loaded":       { "type": "boolean" },
        "architecture": { "type": "string" }
      }
    }
  },
  "required": ["type", "model_id", "status", "message"]
}
```

**JSON 示例:**

```json
{"type":"ModelLoadResponse","model_id":"phi_3_mini_4k_instruct_q4_gguf","status":"loaded","message":"Model 'phi_3_mini_4k_instruct_q4_gguf' loaded successfully","model_info":{"id":"phi_3_mini_4k_instruct_q4_gguf","name":"phi-3-mini-4k-instruct-q4.gguf","path":"D:/Ainos/models/phi-3-mini-4k-instruct-q4.gguf","size_mb":2048,"loaded":true,"architecture":"auto"}}
{"type":"ModelLoadResponse","model_id":"qwen_7b_q4_gguf","status":"already_loaded","message":"Model 'qwen_7b_q4_gguf' is already loaded","model_info":{"id":"qwen_7b_q4_gguf","name":"qwen-7b-q4.gguf","path":"/var/lib/ainos/models/qwen-7b-q4.gguf","size_mb":4096,"loaded":true,"architecture":"auto"}}
{"type":"ModelLoadResponse","model_id":"llama_3_8b_q4_gguf","status":"error","message":"Model file not found: D:/Ainos/models/llama-3-8b-q4.gguf","model_info":null}
{"type":"ModelLoadResponse","model_id":"mistral_7b_q4_gguf","status":"error","message":"Unsupported model format: .bin (supported: [\"gguf\", \"ggml\", \"onnx\", \"bin\"])","model_info":null}
{"type":"ModelLoadResponse","model_id":"model_onnx","status":"loaded","message":"Model 'model_onnx' loaded successfully","model_info":{"id":"model_onnx","name":"model.onnx","path":"D:/Ainos/models/model.onnx","size_mb":512,"loaded":true,"architecture":"onnx"}}
```

### 2.3.9 ModelUnload (模型卸载请求)

**JSON Schema:**

```json
{
  "type": "object",
  "properties": {
    "type":     { "type": "string", "enum": ["ModelUnload"] },
    "model_id": { "type": "string" }
  },
  "required": ["type", "model_id"]
}
```

**JSON 示例:**

```json
{"type":"ModelUnload","model_id":"phi_3_mini_4k_instruct_q4_gguf"}
{"type":"ModelUnload","model_id":"qwen_7b_q4_gguf"}
{"type":"ModelUnload","model_id":"llama_3_8b_q4_gguf"}
```

### 2.3.10 ModelUnloadResponse (模型卸载响应)

**JSON Schema:**

```json
{
  "type": "object",
  "properties": {
    "type":     { "type": "string", "enum": ["ModelUnloadResponse"] },
    "model_id": { "type": "string" },
    "status":   { "type": "string", "enum": ["unloaded", "not_found", "error"] },
    "message":  { "type": "string" }
  },
  "required": ["type", "model_id", "status", "message"]
}
```

**JSON 示例:**

```json
{"type":"ModelUnloadResponse","model_id":"phi_3_mini_4k_instruct_q4_gguf","status":"unloaded","message":"Model 'phi_3_mini_4k_instruct_q4_gguf' unloaded successfully"}
{"type":"ModelUnloadResponse","model_id":"nonexistent_model","status":"not_found","message":"Model 'nonexistent_model' is not loaded"}
{"type":"ModelUnloadResponse","model_id":"qwen_7b_q4_gguf","status":"error","message":"Failed to unload model: engine busy"}
```

### 2.3.11 ModelList (模型列表请求)

**JSON Schema:**

```json
{
  "type": "object",
  "properties": {
    "type": { "type": "string", "enum": ["ModelList"] }
  },
  "required": ["type"]
}
```

**JSON 示例:**

```json
{"type":"ModelList"}
```

### 2.3.12 ModelListResponse (模型列表响应)

**JSON Schema:**

```json
{
  "type": "object",
  "properties": {
    "type":   { "type": "string", "enum": ["ModelListResponse"] },
    "models": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id":           { "type": "string" },
          "name":         { "type": "string" },
          "path":         { "type": "string" },
          "size_mb":      { "type": "integer" },
          "loaded":       { "type": "boolean" },
          "architecture": { "type": "string" }
        }
      }
    }
  },
  "required": ["type", "models"]
}
```

**JSON 示例:**

```json
{"type":"ModelListResponse","models":[{"id":"phi_3_mini_4k_instruct_q4_gguf","name":"phi-3-mini-4k-instruct-q4.gguf","path":"D:/Ainos/models/phi-3-mini-4k-instruct-q4.gguf","size_mb":2048,"loaded":true,"architecture":"auto"},{"id":"qwen_7b_q4_gguf","name":"qwen-7b-q4.gguf","path":"D:/Ainos/models/qwen-7b-q4.gguf","size_mb":4096,"loaded":false,"architecture":"auto"}]}
{"type":"ModelListResponse","models":[]}
```

### 2.3.13 ContextStore (上下文存储请求)

**JSON Schema:**

```json
{
  "type": "object",
  "properties": {
    "type":  { "type": "string", "enum": ["ContextStore"] },
    "key":   { "type": "string" },
    "value": { "type": "string" }
  },
  "required": ["type", "key", "value"]
}
```

**JSON 示例:**

```json
{"type":"ContextStore","key":"user_name","value":"Alice"}
{"type":"ContextStore","key":"conversation_history","value":"User asked about AI, assistant responded with overview"}
{"type":"ContextStore","key":"preferred_language","value":"zh-CN"}
{"type":"ContextStore","key":"last_session_summary","value":"Discussed project architecture"}
{"type":"ContextStore","key":"model_preference","value":"phi-3-mini"}
```

### 2.3.14 ContextRetrieve (上下文检索请求)

**JSON Schema:**

```json
{
  "type": "object",
  "properties": {
    "type": { "type": "string", "enum": ["ContextRetrieve"] },
    "key":  { "type": "string" }
  },
  "required": ["type", "key"]
}
```

**JSON 示例:**

```json
{"type":"ContextRetrieve","key":"user_name"}
{"type":"ContextRetrieve","key":"preferred_language"}
{"type":"ContextRetrieve","key":"nonexistent_key"}
```

### 2.3.15 Status (状态查询)

**JSON Schema:**

```json
{
  "type": "object",
  "properties": {
    "type": { "type": "string", "enum": ["Status"] }
  },
  "required": ["type"]
}
```

**JSON 示例:**

```json
{"type":"Status"}
```

### 2.3.16 StatusResponse (状态响应)

**JSON Schema:**

```json
{
  "type": "object",
  "properties": {
    "type":              { "type": "string", "enum": ["StatusResponse"] },
    "uptime":            { "type": "integer", "description": "Uptime in seconds" },
    "models_loaded":     { "type": "integer" },
    "total_requests":    { "type": "integer" },
    "network_available": { "type": "boolean" },
    "active_sessions":   { "type": "integer" },
    "rate_limits": {
      "type": ["array", "null"],
      "items": {
        "type": "object",
        "properties": {
          "category":      { "type": "string" },
          "limit":         { "type": "integer" },
          "remaining":     { "type": "integer" },
          "reset_seconds": { "type": "integer" }
        }
      }
    }
  },
  "required": ["type", "uptime", "models_loaded", "total_requests", "network_available", "active_sessions"]
}
```

**JSON 示例:**

```json
{"type":"StatusResponse","uptime":86400,"models_loaded":2,"total_requests":15420,"network_available":true,"active_sessions":5,"rate_limits":[{"category":"inference","limit":100,"remaining":85,"reset_seconds":1},{"category":"model_ops","limit":10,"remaining":10,"reset_seconds":1},{"category":"status","limit":1000,"remaining":997,"reset_seconds":1},{"category":"admin","limit":5,"remaining":5,"reset_seconds":1}]}
{"type":"StatusResponse","uptime":3600,"models_loaded":0,"total_requests":0,"network_available":false,"active_sessions":0,"rate_limits":null}
{"type":"StatusResponse","uptime":604800,"models_loaded":3,"total_requests":125000,"network_available":true,"active_sessions":12,"rate_limits":[{"category":"inference","limit":100,"remaining":42,"reset_seconds":1},{"category":"model_ops","limit":10,"remaining":3,"reset_seconds":1},{"category":"status","limit":1000,"remaining":856,"reset_seconds":1},{"category":"admin","limit":5,"remaining":5,"reset_seconds":1}]}
```

### 2.3.17 RateLimitStatus (速率限制查询)

**JSON Schema:**

```json
{
  "type": "object",
  "properties": {
    "type": { "type": "string", "enum": ["RateLimitStatus"] }
  },
  "required": ["type"]
}
```

**JSON 示例:**

```json
{"type":"RateLimitStatus"}
```

### 2.3.18 Error (错误响应)

**JSON Schema:**

```json
{
  "type": "object",
  "properties": {
    "type":    { "type": "string", "enum": ["Error"] },
    "code":    { "type": "integer" },
    "message": { "type": "string" }
  },
  "required": ["type", "code", "message"]
}
```

**JSON 示例:**

```json
{"type":"Error","code":-1,"message":"Invalid JSON: missing field `prompt` at line 1 column 30"}
{"type":"Error","code":401,"message":"Authentication required. Send an Auth message first."}
{"type":"Error","code":403,"message":"Permission denied: Admin required"}
{"type":"Error","code":429,"message":"Rate limit exceeded for Inference. Retry after 1 seconds."}
{"type":"Error","code":-1,"message":"No inference backend available"}
{"type":"Error","code":-1,"message":"Cloud API error: API returned 401 Unauthorized"}
{"type":"Error","code":-1,"message":"Serialize error"}
{"type":"Error","code":401,"message":"Session expired. Please re-authenticate."}
{"type":"Error","code":-1,"message":"Key not found: nonexistent_key"}
{"type":"Error","code":-1,"message":"Unexpected server-to-client message type"}
```

## 2.4 消息路由表 / Message Routing Table

源文件: `D:/Ainos/system-services/ai-daemon/src/ipc.rs` 第 635-742 行

`process_message` 函数是核心消息路由器，根据消息类型分派到对应的处理函数：

| 消息类型 | 处理函数 | 所需权限 | 速率限制类别 |
|---------|---------|---------|-------------|
| `Auth` | `handle_auth` | 无 | 豁免 |
| `Inference` | `handle_inference` | Infer | Inference |
| `InferenceStream` | `handle_inference` | Infer | Inference |
| `ModelLoad` | `handle_model_load` | ModelLoad | ModelOps |
| `ModelUnload` | `handle_model_unload` | ModelUnload | ModelOps |
| `ModelList` | `handle_model_list` | Status | Status |
| `Status` | `handle_status` | Status | Status |
| `RateLimitStatus` | `handle_rate_limit_status` | Status | 豁免 |
| `ContextStore` | `handle_context_store` | Context | Status |
| `ContextRetrieve` | `handle_context_retrieve` | Context | Status |

---

# 3. 认证协议 / Authentication Protocol

## 3.1 概述 / Overview

源文件: `D:/Ainos/system-services/ai-daemon/src/auth.rs`

AinosOS 使用 Bearer Token 认证机制，支持以下特性：

- 令牌认证（Bearer Token）
- 会话管理（UUID v4 会话令牌）
- 基于权限的访问控制
- 审计日志记录
- 令牌自动生成与启动日志
- 令牌轮换支持
- 可配置令牌来源（配置文件、环境变量、自动生成）

## 3.2 令牌来源与优先级 / Token Sources and Priority

源文件: `D:/Ainos/system-services/ai-daemon/src/auth.rs` 第 837-910 行

令牌按以下优先级解析：

```
1. 环境变量 (AINOS_AUTH_TOKEN)
2. 配置文件 (auth.token)
3. 令牌文件 (auth.token_path)
4. 自动生成 (64 字符十六进制)
```

```rust
fn resolve_token(config: &AuthConfig) -> Option<AuthToken> {
    // 1. 环境变量优先
    if let Ok(env_token) = std::env::var("AINOS_AUTH_TOKEN") {
        if !env_token.is_empty() {
            let token = AuthToken::new(env_token);
            if token.validate() {
                info!("Using auth token from AINOS_AUTH_TOKEN environment variable");
                return Some(token);
            }
        }
    }

    // 2. 配置文件令牌
    if !config.token.is_empty() {
        let token = AuthToken::new(config.token.clone());
        if token.validate() {
            info!("Using auth token from config file");
            return Some(token);
        }
    }

    // 3. 令牌文件
    if !config.token_path.is_empty() {
        if let Ok(content) = fs::read_to_string(&config.token_path) {
            let token_str = content.trim().to_string();
            if !token_str.is_empty() {
                let token = AuthToken::new(token_str);
                if token.validate() {
                    info!("Using auth token from file: {}", config.token_path);
                    return Some(token);
                }
            }
        }
    }

    // 4. 自动生成令牌
    if config.enabled {
        let token = AuthToken::generate();
        info!("============================================================");
        info!("  AUTH TOKEN AUTO-GENERATED: {}", token.as_str());
        info!("  Save this token for client authentication.");
        if !config.token_path.is_empty() {
            match fs::write(&config.token_path, token.as_str()) {
                Ok(_) => info!("  Token saved to: {}", config.token_path),
                Err(e) => warn!("  Failed to save token to {}: {}", config.token_path, e),
            }
        }
        info!("============================================================");
        return Some(token);
    }

    None
}
```

## 3.3 令牌格式 / Token Format

源文件: `D:/Ainos/system-services/ai-daemon/src/auth.rs` 第 176-252 行

```rust
/// Bearer 令牌，自动在 drop 时归零化
#[derive(Clone, Zeroize, ZeroizeOnDrop)]
pub struct AuthToken {
    token: String,
}

impl AuthToken {
    /// 生成加密随机令牌 (32 字节 → 64 字符十六进制)
    pub fn generate() -> Self {
        use rand::Rng;
        let mut bytes = [0u8; 32];
        rand::thread_rng().fill(&mut bytes);
        let token = bytes.iter()
            .map(|b| format!("{:02x}", b))
            .collect::<String>();
        Self { token }
    }

    /// 验证令牌格式
    /// 令牌必须至少 16 字符，仅包含字母数字、短横线、下划线和点
    pub fn validate(&self) -> bool {
        if self.token.len() < 16 { return false; }
        self.token.chars()
            .all(|c| c.is_alphanumeric() || c == '-' || c == '_' || c == '.')
    }

    /// 返回屏蔽版本用于日志记录 (前8后4)
    pub fn masked(&self) -> String {
        if self.token.len() <= 16 {
            return format!("{}...{}", &self.token[..4], &self.token[self.token.len() - 4..]);
        }
        format!("{}...{}", &self.token[..8], &self.token[self.token.len() - 4..])
    }
}
```

### 令牌格式规则 / Token Format Rules

| 属性 | 值 |
|------|-----|
| 最小长度 | 16 字符 |
| 默认长度 | 64 字符 (32 随机字节 → 十六进制) |
| 允许字符 | 字母数字 (a-z, A-Z, 0-9), 短横线 (-), 下划线 (_), 点 (.) |
| 生成方式 | `rand::thread_rng()` 加密随机 |
| 内存安全 | `Zeroize` + `ZeroizeOnDrop` 自动清除 |

## 3.4 会话管理 / Session Management

### 会话结构 / Session Structure

源文件: `D:/Ainos/system-services/ai-daemon/src/auth.rs` 第 277-352 行

```rust
#[derive(Debug, Clone)]
pub struct Session {
    /// 会话令牌 (UUID v4)
    pub session_token: String,
    /// 授予此会话的权限
    pub permissions: Vec<Permission>,
    /// 会话创建时间
    pub created_at: Instant,
    /// 会话过期时间
    pub expires_at: Instant,
    /// 最后活动时间
    pub last_activity: Instant,
    /// 客户端标识符
    pub client_id: String,
    /// 认证令牌哈希（用于审计）
    auth_token_hash: u64,
}

impl Session {
    pub fn new(client_id: String, permissions: Vec<Permission>,
                ttl: Duration, auth_token: &AuthToken) -> Self {
        let now = Instant::now();
        Self {
            session_token: Uuid::new_v4().to_string(),
            permissions,
            created_at: now,
            expires_at: now + ttl,
            last_activity: now,
            client_id,
            auth_token_hash: simple_hash(auth_token.as_str()),
        }
    }

    pub fn is_expired(&self) -> bool { Instant::now() >= self.expires_at }
    pub fn has_permission(&self, permission: &Permission) -> bool {
        self.permissions.contains(&Permission::All) || self.permissions.contains(permission)
    }
    pub fn touch(&mut self) { self.last_activity = Instant::now(); }
    pub fn extend_ttl(&mut self, ttl: Duration) { self.expires_at = Instant::now() + ttl; }
    pub fn time_to_live(&self) -> Duration {
        self.expires_at.saturating_duration_since(Instant::now())
    }
    pub fn idle_time(&self) -> Duration {
        Instant::now().saturating_duration_since(self.last_activity)
    }
}
```

### 会话管理器 / Session Manager

源文件: `D:/Ainos/system-services/ai-daemon/src/auth.rs` 第 744-1188 行

```rust
pub struct SessionManager {
    /// 活跃会话 (session_token → Session)
    sessions: Arc<RwLock<HashMap<String, Session>>>,
    /// 配置的 Bearer 令牌
    configured_token: Option<AuthToken>,
    /// 会话 TTL
    session_ttl: Duration,
    /// 默认权限
    default_permissions: Vec<Permission>,
    /// 审计日志
    audit: Arc<AuditLogger>,
    /// 令牌到权限的覆盖
    token_permissions: Arc<RwLock<HashMap<String, Vec<Permission>>>>,
    /// 是否启用认证
    enabled: bool,
}
```

### 认证流程 / Authentication Flow

源文件: `D:/Ainos/system-services/ai-daemon/src/auth.rs` 第 931-1007 行

```rust
/// 使用 Bearer 令牌认证客户端
pub async fn authenticate(&self, client_id: &str, bearer_token: &str) -> Result<String, AuthError> {
    if !self.enabled {
        // 认证未启用：创建具有全部权限的会话
        let dummy_token = AuthToken::new("auth-disabled".to_string());
        let session = Session::new(client_id.to_string(), vec![Permission::All],
            self.session_ttl, &dummy_token);
        let session_token = session.session_token.clone();
        // ... 记录审计日志
        let mut sessions = self.sessions.write().await;
        sessions.insert(session_token.clone(), session);
        return Ok(session_token);
    }

    let configured = self.configured_token.as_ref()
        .ok_or(AuthError::ConfigError("No token configured".to_string()))?;

    // 验证 Bearer 令牌
    if bearer_token != configured.as_str() {
        // 记录审计日志：认证失败
        return Err(AuthError::InvalidToken);
    }

    // 确定权限
    let permissions = { /* 从令牌权限映射获取 */ };

    // 创建会话
    let auth_token = AuthToken::new(bearer_token.to_string());
    let session = Session::new(client_id.to_string(), permissions.clone(),
        self.session_ttl, &auth_token);
    let session_token = session.session_token.clone();

    // 记录审计日志：认证成功
    let mut sessions = self.sessions.write().await;
    sessions.insert(session_token.clone(), session);

    Ok(session_token)
}
```

### 完整认证流程示例 / Complete Auth Flow

```
客户端 (Client)                   服务器 (Server)
    |                                |
    |--- TCP Connect -------------->|
    |                                |
    |--- {"type":"Auth",            |
    |     "token":"a1b2..."} ----->|  ← 验证 Bearer Token
    |                                |  ← 创建 UUID v4 会话
    |                                |  ← 记录审计日志
    |<-- {"type":"AuthResponse",    |
    |     "success":true,           |
    |     "session_token":          |
    |     "550e8400-...",           |
    |     "permissions":            |
    |     ["infer","status",        |
    |      "context"],              |
    |     "session_ttl_seconds":    |
    |     3600}                     |
    |                                |
    |--- {"type":"Status"} ------->|  ← 会话令牌隐式关联
    |                                |  ← 验证会话权限
    |<-- {"type":"StatusResponse",  |
    |     ...}                      |
    |                                |
    |--- TCP Disconnect ---------->|
    |                                |  ← 清理会话
    |                                |  ← 记录审计日志
```

## 3.5 权限系统 / Permission System

源文件: `D:/Ainos/system-services/ai-daemon/src/auth.rs` 第 71-170 行

### 权限枚举 / Permission Enum

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Permission {
    #[serde(rename = "infer")]       Infer,       // 推理请求
    #[serde(rename = "model_load")]  ModelLoad,   // 加载模型
    #[serde(rename = "model_unload")]ModelUnload, // 卸载模型
    #[serde(rename = "admin")]       Admin,       // 管理操作
    #[serde(rename = "status")]      Status,      // 状态查询
    #[serde(rename = "context")]     Context,     // 上下文管理
    #[serde(rename = "all")]         All,         // 超级权限
}
```

### 权限默认值 / Default Permissions

| 客户端类型 | 默认权限 |
|-----------|---------|
| 未认证客户端 | `Status` 仅 |
| 已认证客户端 | `Infer`, `Status`, `Context` |
| 认证未启用 | `All` (全部权限) |

```rust
impl Permission {
    pub fn default_unauthenticated() -> Vec<Permission> {
        vec![Permission::Status]
    }

    pub fn default_authenticated() -> Vec<Permission> {
        vec![Permission::Infer, Permission::Status, Permission::Context]
    }
}
```

### 消息到权限的映射

```rust
impl Permission {
    pub fn from_message_type(msg_type: &str) -> Option<Permission> {
        match msg_type {
            "Inference" | "InferenceResponse" | "InferenceChunk" => Some(Permission::Infer),
            "ModelLoad" => Some(Permission::ModelLoad),
            "ModelUnload" => Some(Permission::ModelUnload),
            "ModelList" | "ModelListResponse" => Some(Permission::Status),
            "Status" | "StatusResponse" => Some(Permission::Status),
            "ContextStore" | "ContextRetrieve" => Some(Permission::Context),
            "Auth" | "AuthResponse" => None,  // 始终允许
            "RateLimitStatus" => Some(Permission::Status),
            "Error" => None,                   // 始终允许
            _ => Some(Permission::Admin),
        }
    }
}
```

## 3.6 审计日志 / Audit Logging

源文件: `D:/Ainos/system-services/ai-daemon/src/auth.rs` 第 366-730 行

### 审计事件类型 / Audit Event Types

```rust
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum AuditEventType {
    Authentication,      // 认证尝试
    AuthFailure,         // 认证失败
    PermissionDenied,    // 权限拒绝
    AdminOperation,      // 管理操作
    SessionExpired,      // 会话过期
    TokenRotation,       // 令牌轮换
    SessionCreated,      // 会话创建
    SessionDestroyed,    // 会话销毁
    RateLimitExceeded,   // 速率限制超限
}
```

### 审计条目结构 / Audit Entry Structure

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuditEntry {
    pub timestamp: String,      // ISO 8601 时间戳
    pub event_type: AuditEventType,  // 事件类型
    pub client_id: String,      // 客户端标识符
    pub session_token: Option<String>,  // 会话令牌（屏蔽后）
    pub message: String,        // 详细信息
    pub error: Option<String>,  // 错误详情
}
```

### 审计日志输出 / Audit Log Output

审计日志同时写入：

1. **结构化追踪事件** (tracing) — 使用 `info!` 或 `warn!` 级别
2. **审计日志文件** — 每行一个 JSON 对象，追加写入

```rust
// 审计日志写入示例
async fn write_entry(&self, entry: AuditEntry) {
    // 写入内存缓冲区
    let mut buffer = self.buffer.write().await;
    buffer.push(entry.clone());

    // 发出结构化追踪事件
    match entry.event_type {
        AuditEventType::AuthFailure | AuditEventType::PermissionDenied
        | AuditEventType::RateLimitExceeded => {
            warn!(target: "ainos::audit", "AUDIT [{}] {}: {}", event_type, entry.client_id, entry.message);
        }
        _ => {
            info!(target: "ainos::audit", "AUDIT [{}] {}: {}", event_type, entry.client_id, entry.message);
        }
    }

    // 写入文件
    if let Some(ref path) = self.log_path {
        if let Ok(json) = serde_json::to_string(&entry) {
            fs::OpenOptions::new().create(true).append(true).open(path)
                .and_then(|mut f| { writeln!(f, "{}", json) }).ok();
        }
    }
}
```

### 审计日志示例 / Audit Log Examples

```
AUDIT [Authentication] 127.0.0.1:9500: [a1b2c3d4...ef89] Authentication successful
AUDIT [AuthFailure] 192.168.1.100: [bad-token] Invalid token provided
AUDIT [PermissionDenied] client-1: Permission denied for ModelLoad: required ModelLoad, granted [Infer, Status]
AUDIT [AdminOperation] admin-user: Admin operation: ModelLoad - Loaded model: phi_3_mini from /models/phi.gguf
AUDIT [SessionExpired] client-2: Session expired
AUDIT [TokenRotation] system: Token rotated: a1b2c3d4...ef89 -> f0e1d2c3...ab45
AUDIT [SessionCreated] 127.0.0.1: Session created with permissions: [Infer, Status, Context]
AUDIT [SessionDestroyed] client-1: Session destroyed
AUDIT [RateLimitExceeded] client-3: Rate limit exceeded for inference: retry after 1000ms
```

## 3.7 会话清理 / Session Cleanup

源文件: `D:/Ainos/system-services/ai-daemon/src/auth.rs` 第 1194-1209 行

```rust
/// 定期会话清理任务
pub async fn session_cleanup_task(session_manager: Arc<SessionManager>, interval_secs: u64) {
    let mut interval = tokio::time::interval(Duration::from_secs(interval_secs));
    loop {
        interval.tick().await;
        let cleaned = session_manager.cleanup_expired().await;
        let active = session_manager.active_sessions().await;
        debug!("Session cleanup: removed {}, active: {}", cleaned, active);
    }
}
```

## 3.8 令牌轮换 / Token Rotation

源文件: `D:/Ainos/system-services/ai-daemon/src/auth.rs` 第 1098-1129 行

```rust
/// 轮换 Bearer 令牌
pub async fn rotate_token(&self, token_path: &str) -> Result<AuthToken, AuthError> {
    let old_token = self.configured_token.as_ref().map(|t| t.masked());
    let new_token = AuthToken::generate();

    // 保存到文件
    if let Some(parent) = Path::new(token_path).parent() {
        let _ = fs::create_dir_all(parent);
    }
    fs::write(token_path, new_token.as_str())
        .map_err(|e| AuthError::TokenFileError(e.to_string()))?;

    if let Some(ref old) = old_token {
        self.audit.log_token_rotation(old, &new_token.masked()).await;
    }

    info!("Token rotated. New token: {} (saved to {})", new_token.masked(), token_path);
    Ok(new_token)
}
```

## 3.9 认证配置 / Auth Configuration

源文件: `D:/Ainos/system-services/ai-daemon/src/config.rs` 第 150-195 行

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuthConfig {
    #[serde(default = "default_true")]
    pub enabled: bool,                    // 是否启用认证
    #[serde(default)]
    pub token: String,                    // 静态 Bearer Token
    #[serde(default)]
    pub token_path: String,              // Token 文件路径
    #[serde(default = "default_session_ttl")]
    pub session_ttl_seconds: u64,        // Session TTL (默认 3600s)
    #[serde(default)]
    pub permissions_file: String,        // 权限配置文件路径
    #[serde(default)]
    pub default_permissions: Vec<String>, // 默认权限列表
    #[serde(default)]
    pub audit_log_path: String,          // 审计日志路径
    #[serde(default)]
    pub audit_all_requests: bool,        // 是否记录所有请求
}
```

## 3.10 认证流程示例 (20+)

### 示例 1: 成功认证（默认权限）

```json
// 请求:
{"type":"Auth","token":"a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"}
// 响应:
{"type":"AuthResponse","success":true,"session_token":"550e8400-e29b-41d4-a716-446655440000","message":"Authentication successful","permissions":["infer","status","context"],"session_ttl_seconds":3600}
```

### 示例 2: 无效令牌

```json
// 请求:
{"type":"Auth","token":"short"}
// 响应:
{"type":"AuthResponse","success":false,"session_token":null,"message":"Authentication failed: Invalid authentication token","permissions":[],"session_ttl_seconds":0}
```

### 示例 3: 认证未启用

```json
// 请求:
{"type":"Auth","token":"any-token-will-work"}
// 响应:
{"type":"AuthResponse","success":true,"session_token":"f47ac10b-58cc-4372-a567-0e02b2c3d479","message":"Auth disabled - full access granted","permissions":["all"],"session_ttl_seconds":3600}
```

### 示例 4: 未认证尝试访问

```json
// 请求 (未发送 Auth):
{"type":"Status"}
// 响应:
{"type":"Error","code":401,"message":"Authentication required. Send an Auth message first."}
```

### 示例 5: 权限不足

```json
// 请求 (已认证，但无 Admin 权限):
{"type":"ModelLoad","path":"D:/Ainos/models/model.gguf"}
// 响应:
{"type":"Error","code":403,"message":"Permission denied: ModelLoad required"}
```

### 示例 6: 会话过期

```json
// 请求:
{"type":"Status"}
// 响应:
{"type":"Error","code":401,"message":"Session expired. Please re-authenticate."}
```

### 示例 7: 完整权限管理令牌

```json
// 请求:
{"type":"Auth","token":"admin-token-with-all-permissions-1234567890"}
// 响应:
{"type":"AuthResponse","success":true,"session_token":"6ba7b810-9dad-11d1-80b4-00c04fd430c8","message":"Authentication successful","permissions":["infer","status","context","model_load","model_unload","admin"],"session_ttl_seconds":7200}
```

### 示例 8: 令牌来自环境变量

```rust
// 启动日志:
// INFO: Using auth token from AINOS_AUTH_TOKEN environment variable
// 客户端使用相同的令牌进行认证:
{"type":"Auth","token":"env-token-from-ainos-auth-token-123456"}
```

### 示例 9: 令牌自动生成

```rust
// 启动日志:
// INFO: ============================================================
// INFO:   AUTH TOKEN AUTO-GENERATED: d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4
// INFO:   Save this token for client authentication.
// INFO:   Token saved to: /var/lib/ainos/auth_token.txt
// INFO: ============================================================
```

### 示例 10: 会话 TTL 续期

```rust
// 在会话活跃期间，touch() 更新 last_activity
// extend_ttl() 延长过期时间
session.touch();
session.extend_ttl(Duration::from_secs(3600));
```

### 示例 11: 令牌轮换

```json
// 管理员请求令牌轮换
// 响应:
// INFO: Token rotated. New token: f0e1d2c3...ab45 (saved to /var/lib/ainos/auth_token.txt)
```

### 示例 12: 会话列表

```rust
// 管理员查询活跃会话
let sessions = manager.list_sessions().await;
// 返回: [(masked_token, client_id, ttl), ...]
```

### 示例 13: 认证禁用时的会话验证

```json
// 即使认证禁用，validate_session 仍返回具有 All 权限的虚拟会话
// 这确保了内部代码路径不需要特殊处理
```

### 示例 14: 权限检查失败

```json
// 请求 (会话只有 Status 和 Context 权限):
{"type":"Inference","model":"default","prompt":"Hello"}
// 响应:
{"type":"Error","code":403,"message":"Permission denied: Infer required"}
```

### 示例 15: 非字母数字令牌字符

```json
// 包含允许的特殊字符的令牌:
{"type":"Auth","token":"test-token_with.dots-and-dashes-1234567890"}
// 响应: 成功认证 (仅当令牌匹配)
```

### 示例 16: 短令牌拒绝

```json
// 请求 (令牌只有 12 字符):
{"type":"Auth","token":"tooshorttoken"}
// 响应:
{"type":"AuthResponse","success":false,"session_token":null,"message":"Authentication failed: Invalid authentication token","permissions":[],"session_ttl_seconds":0}
```

### 示例 17: 多客户端相同令牌

```json
// 客户端 A:
{"type":"Auth","token":"shared-token-for-multiple-clients-12345"}
// 响应: session_token_A

// 客户端 B:
{"type":"Auth","token":"shared-token-for-multiple-clients-12345"}
// 响应: session_token_B (不同的 UUID)
```

### 示例 18: 会话销毁

```rust
// 客户端断开连接时
s.session_manager.destroy_session(session_token).await;
// 审计日志: [SessionDestroyed] client-1: Session destroyed
```

### 示例 19: 审计统计

```rust
let stats = audit.stats();
println!("Total auth attempts: {}", stats.total_auth_attempts);
println!("Successful auths: {}", stats.successful_auths);
println!("Failed auths: {}", stats.failed_auths);
println!("Permission denied: {}", stats.permission_denied);
println!("Admin operations: {}", stats.admin_operations);
println!("Rate limit events: {}", stats.rate_limit_events);
```

### 示例 20: 从权限文件加载覆盖

```rust
// 特定令牌可以配置不同的权限集
// token_permissions: HashMap<String, Vec<Permission>>
token_permissions.insert("admin-token".to_string(), vec![Permission::All]);
token_permissions.insert("readonly-token".to_string(), vec![Permission::Status, Permission::Context]);
```

---

# 4. 速率限制 / Rate Limiting

## 4.1 令牌桶算法 / Token Bucket Algorithm

源文件: `D:/Ainos/system-services/ai-daemon/src/ratelimit.rs` 第 125-253 行

AinosOS 使用令牌桶算法实现速率限制，提供平滑的速率控制和突发处理能力。

```rust
#[derive(Debug, Clone)]
pub struct TokenBucket {
    capacity: f64,     // 桶容量（突发大小）
    tokens: f64,       // 当前令牌数
    refill_rate: f64,  // 令牌补充速率（每秒）
    last_refill: Instant, // 上次补充时间
}

impl TokenBucket {
    pub fn new(rate_per_sec: f64, burst: f64) -> Self {
        Self {
            capacity: burst,
            tokens: burst,  // 从满桶开始
            refill_rate: rate_per_sec,
            last_refill: Instant::now(),
        }
    }

    fn refill(&mut self) {
        let now = Instant::now();
        let elapsed = now.duration_since(self.last_refill);
        let tokens_to_add = elapsed.as_secs_f64() * self.refill_rate;
        self.tokens = (self.tokens + tokens_to_add).min(self.capacity);
        self.last_refill = now;
    }

    pub fn consume(&mut self) -> Result<u64, Duration> {
        self.refill();
        if self.tokens >= 1.0 {
            self.tokens -= 1.0;
            Ok(self.tokens as u64)
        } else {
            let wait_time = Duration::from_secs_f64(1.0 / self.refill_rate);
            Err(wait_time)
        }
    }

    pub fn remaining(&self) -> u64 {
        // 估算当前令牌数（不修改状态）
        let elapsed = Instant::now().duration_since(self.last_refill);
        let estimated_tokens =
            (self.tokens + elapsed.as_secs_f64() * self.refill_rate).min(self.capacity);
        estimated_tokens as u64
    }

    pub fn capacity(&self) -> u64 { self.capacity as u64 }
}
```

## 4.2 速率限制类别 / Rate Limit Categories

源文件: `D:/Ainos/system-services/ai-daemon/src/ratelimit.rs` 第 56-118 行

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum RateLimitCategory {
    #[serde(rename = "inference")] Inference,  // 推理请求
    #[serde(rename = "model_ops")] ModelOps,    // 模型操作
    #[serde(rename = "status")]    Status,      // 状态查询
    #[serde(rename = "admin")]     Admin,       // 管理操作
}
```

### 默认速率限制配置 / Default Rate Limits

| 类别 | 速率 (请求/秒) | 突发大小 | 描述 |
|------|--------------|---------|------|
| Inference | 100 | 200 | 推理请求（本地 + 云端） |
| ModelOps | 10 | 20 | 模型加载/卸载操作 |
| Status | 1000 | 2000 | 状态和上下文查询 |
| Admin | 5 | 10 | 管理操作 |

```rust
impl RateLimitCategory {
    pub fn default_rate(&self) -> f64 {
        match self {
            RateLimitCategory::Inference => 100.0,
            RateLimitCategory::ModelOps => 10.0,
            RateLimitCategory::Status => 1000.0,
            RateLimitCategory::Admin => 5.0,
        }
    }

    pub fn default_burst(&self) -> f64 {
        match self {
            RateLimitCategory::Inference => 200.0,
            RateLimitCategory::ModelOps => 20.0,
            RateLimitCategory::Status => 2000.0,
            RateLimitCategory::Admin => 10.0,
        }
    }

    /// 从消息类型确定速率限制类别
    pub fn from_message_type(msg_type: &str) -> Self {
        match msg_type {
            "Inference" | "InferenceResponse" | "InferenceChunk" | "InferenceStream"
                => RateLimitCategory::Inference,
            "ModelLoad" | "ModelUnload" => RateLimitCategory::ModelOps,
            "ModelList" | "ModelListResponse" | "Status" | "StatusResponse" | "RateLimitStatus"
                => RateLimitCategory::Status,
            "ContextStore" | "ContextRetrieve" => RateLimitCategory::Status,
            _ => RateLimitCategory::Admin,
        }
    }
}
```

## 4.3 速率限制器 / Rate Limiter

源文件: `D:/Ainos/system-services/ai-daemon/src/ratelimit.rs` 第 264-532 行

```rust
pub struct RateLimiter {
    /// 每客户端速率限制器: client_key → (category → bucket)
    clients: Arc<RwLock<HashMap<String, HashMap<RateLimitCategory, TokenBucket>>>>,
    /// 每类别的配置 (rate, burst)
    config: HashMap<RateLimitCategory, (f64, f64)>,
    /// 统计信息
    stats: Arc<RateLimitStats>,
    /// 最大客户端跟踪数
    max_clients: usize,
    /// 客户端不活动超时
    inactivity_timeout: Duration,
}
```

### 速率限制检查 / Rate Limit Check

```rust
pub async fn check_rate_limit(
    &self,
    client_key: &str,
    category: RateLimitCategory,
) -> Result<RateLimitInfo, RateLimitError> {
    let mut clients = self.clients.write().await;

    // 获取或创建客户端的桶
    let client_buckets = clients
        .entry(client_key.to_string())
        .or_insert_with(|| {
            self.stats.active_clients.fetch_add(1, Ordering::Relaxed);
            let mut buckets = HashMap::new();
            for (cat, &(r, b)) in &self.config {
                buckets.insert(*cat, TokenBucket::new(r, b));
            }
            buckets
        });

    // 获取该类别的桶
    let bucket = client_buckets.get_mut(&category).expect("Bucket should exist");

    match bucket.consume() {
        Ok(remaining) => {
            self.stats.total_allowed.fetch_add(1, Ordering::Relaxed);
            Ok(RateLimitInfo { limit: bucket.capacity(), remaining,
                reset: Duration::from_secs_f64(1.0 / rate), category })
        }
        Err(retry_after) => {
            self.stats.total_limited.fetch_add(1, Ordering::Relaxed);
            Err(RateLimitError::RateLimitExceeded {
                category, retry_after, limit: bucket.capacity(), remaining: 0,
            })
        }
    }
}
```

## 4.4 豁免消息类型 / Exempt Message Types

以下消息类型不受速率限制：

```rust
pub fn should_rate_limit(msg_type: &str) -> bool {
    !matches!(msg_type, "Auth" | "AuthResponse" | "Error" | "RateLimitStatus")
}
```

## 4.5 速率限制响应头 / Rate Limit Headers

当速率限制启用时，响应包含类似 HTTP 的速率限制信息：

| 头字段 | 描述 | 示例 |
|-------|------|------|
| `X-RateLimit-Limit` | 速率限制最大值 | `100` |
| `X-RateLimit-Remaining` | 当前窗口内剩余请求数 | `85` |
| `X-RateLimit-Reset` | 重置时间（秒） | `1` |
| `X-RateLimit-Category` | 速率限制类别 | `inference` |

```rust
impl RateLimitInfo {
    pub fn to_headers(&self) -> Vec<(String, String)> {
        vec![
            ("X-RateLimit-Limit".to_string(), self.limit.to_string()),
            ("X-RateLimit-Remaining".to_string(), self.remaining.to_string()),
            ("X-RateLimit-Reset".to_string(), self.reset.as_secs().to_string()),
            ("X-RateLimit-Category".to_string(), format!("{:?}", self.category).to_lowercase()),
        ]
    }
}
```

## 4.6 速率限制配置 / Rate Limit Configuration

源文件: `D:/Ainos/system-services/ai-daemon/src/config.rs` 第 198-262 行

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RateLimitConfig {
    #[serde(default = "default_true")]
    pub enabled: bool,              // 是否启用速率限制
    pub infer_rps: f64,             // 推理速率 (默认 100)
    pub infer_burst: f64,           // 推理突发 (默认 200)
    pub model_rps: f64,             // 模型操作速率 (默认 10)
    pub model_burst: f64,           // 模型操作突发 (默认 20)
    pub status_rps: f64,            // 状态查询速率 (默认 1000)
    pub status_burst: f64,          // 状态查询突发 (默认 2000)
    pub admin_rps: f64,             // 管理操作速率 (默认 5)
    pub admin_burst: f64,           // 管理操作突发 (默认 10)
    pub max_clients: usize,         // 最大客户端数 (默认 1000)
    pub cleanup_interval_secs: u64, // 清理间隔秒 (默认 300)
}
```

## 4.7 垃圾回收 / Garbage Collection

源文件: `D:/Ainos/system-services/ai-daemon/src/ratelimit.rs` 第 486-532 行

```rust
/// 清理不活跃的客户端
pub async fn cleanup_stale(&self) -> usize {
    let mut clients = self.clients.write().await;
    let mut to_remove: Vec<String> = Vec::new();

    for (client_key, buckets) in clients.iter() {
        // 客户端被认为不活跃的条件：所有桶接近满（剩余 >= 95% 容量）
        let all_full = buckets.values().all(|b| {
            b.remaining() as f64 >= b.capacity() as f64 * 0.95
        });
        if all_full {
            to_remove.push(client_key.clone());
        }
    }

    let count = to_remove.len();
    for key in to_remove {
        clients.remove(&key);
        self.stats.active_clients.fetch_sub(1, Ordering::Relaxed);
        self.stats.cleaned_clients.fetch_add(1, Ordering::Relaxed);
    }
    count
}

/// 定期 GC 任务
pub async fn rate_limit_gc_task(rate_limiter: Arc<RateLimiter>, interval_secs: u64) {
    let mut interval = tokio::time::interval(Duration::from_secs(interval_secs));
    loop {
        interval.tick().await;
        let cleaned = rate_limiter.cleanup_stale().await;
        let active = rate_limiter.active_clients().await;
        trace!("Rate limit GC: cleaned {}, active clients: {}", cleaned, active);
    }
}
```

## 4.8 速率限制统计 / Rate Limit Statistics

```rust
#[derive(Debug, Default)]
pub struct RateLimitStats {
    pub total_limited: AtomicU64,    // 被限制的请求总数
    pub total_allowed: AtomicU64,    // 被允许的请求总数
    pub active_clients: AtomicU64,   // 当前跟踪的客户端数
    pub cleaned_clients: AtomicU64,  // 已清理的客户端数
}
```

## 4.9 速率限制场景示例 (15+)

### 示例 1: 正常请求

```json
// 请求:
{"type":"Inference","model":"default","prompt":"Hello"}
// 响应 (含速率限制头):
// X-RateLimit-Limit: 100
// X-RateLimit-Remaining: 99
// X-RateLimit-Reset: 1
// X-RateLimit-Category: inference
{"type":"InferenceResponse","output":"Hello!","tokens_generated":8,"inference_ms":50,"source":"local"}
```

### 示例 2: 速率限制超限

```json
// 请求 (第 201 个推理请求):
{"type":"Inference","model":"default","prompt":"Hello"}
// 响应:
{"type":"Error","code":429,"message":"Rate limit exceeded for Inference. Retry after 1 seconds."}
```

### 示例 3: 突发消耗

```json
// 客户端连续发送 200 个推理请求
// 前 200 个成功（突发桶满）
// 第 201 个失败（429 Too Many Requests）
```

### 示例 4: 不同类别独立限制

```json
// 推理请求速率限制: 100 req/s
// 状态查询速率限制: 1000 req/s
// 两者互不影响
```

### 示例 5: 多客户端独立限制

```json
// 客户端 A 消耗 100 个推理令牌
// 客户端 B 仍可有 200 个推理令牌（独立桶）
```

### 示例 6: 令牌补充

```rust
// 桶容量: 200, 补充速率: 100 tokens/s
// 客户端消耗 200 个令牌后，等待 1 秒后获得 100 个令牌
// 等待 2 秒后桶满（200 个令牌）
```

### 示例 7: 管理操作限制

```json
// 请求:
{"type":"ModelLoad","path":"/models/model.gguf"}
// 管理操作速率: 5 req/s, 突发 10
// 第 11 个请求:
{"type":"Error","code":429,"message":"Rate limit exceeded for ModelOps. Retry after 1 seconds."}
```

### 示例 8: 状态查询高限制

```json
// 状态查询速率: 1000 req/s, 突发 2000
// 适用于健康检查、轮询等高频操作
```

### 示例 9: 豁免消息

```json
// Auth 消息不受速率限制
{"type":"Auth","token":"a1b2c3d4..."}
// Error 消息不受速率限制
{"type":"Error","code":-1,"message":"previous error"}
```

### 示例 10: 速率限制状态查询

```json
// 请求:
{"type":"RateLimitStatus"}
// 响应:
{"type":"RateLimitStatusResponse","limits":[{"category":"inference","limit":100,"remaining":85,"reset_seconds":1},{"category":"model_ops","limit":10,"remaining":10,"reset_seconds":1},{"category":"status","limit":1000,"remaining":997,"reset_seconds":1},{"category":"admin","limit":5,"remaining":5,"reset_seconds":1}]}
```

### 示例 11: 客户端清理

```rust
// 客户端不再发送请求，所有桶逐渐补充到满
// 当所有桶剩余 >= 95% 容量时，客户端被标记为不活跃
// 下次 GC 时被清理（默认每 300 秒）
```

### 示例 12: 最大客户端限制

```rust
// 默认最大跟踪 1000 个客户端
// 超过此数量的新客户端将替换旧客户端
// 配置: max_clients: 1000
```

### 示例 13: 速率限制配置 Override

```toml
[ratelimit]
enabled = true
infer_rps = 200.0    # 提高推理速率限制
infer_burst = 500.0  # 提高推理突发大小
```

### 示例 14: 速率限制错误消息

```rust
// 错误: RateLimitExceeded
println!("{}", err);
// 输出: "Rate limit exceeded: retry after 1s"
```

### 示例 15: 禁用速率限制

```json
// 配置 ratelimit.enabled = false
// 所有请求都不受速率限制
// 但速率限制状态查询仍返回默认值
```

---

# 5. 错误码 / Error Codes

## 5.1 通用错误码 / General Error Codes

AinosOS 定义了一组标准错误码，在 `Error` 消息的 `code` 字段中使用。

```rust
// 在 ipc.rs 中定义的错误码常量
// 注意：这些常量在代码中直接使用整数值
```

| 码值 | 常量名 | 描述 | 当出现时 |
|------|-------|------|---------|
| `0` | `AI_ERR_SUCCESS` | 成功完成 | 操作成功 |
| `-1` | `AI_ERR_GENERAL` | 一般错误 | 未分类的错误 |
| `-2` | `AI_ERR_INVALID_PARAM` | 无效参数 | 请求参数验证失败 |
| `-3` | `AI_ERR_MODEL_NOT_FOUND` | 模型未找到 | 路径不存在或模型未注册 |
| `-4` | `AI_ERR_MODEL_LOAD_FAIL` | 模型加载失败 | 模型文件损坏或不兼容 |
| `-5` | `AI_ERR_OUT_OF_MEMORY` | 内存不足 | 系统内存不足 |
| `-6` | `AI_ERR_TASK_QUEUE_FULL` | 任务队列满 | 并发推理数超限 |
| `-7` | `AI_ERR_NOT_SUPPORTED` | 不支持的操作 | 引擎不支持该模型格式 |
| `-8` | `AI_ERR_PERMISSION` | 权限不足 | 客户端缺少所需权限 |
| `-9` | `AI_ERR_TIMEOUT` | 操作超时 | 推理超时（默认 120 秒） |
| `-10` | `AI_ERR_THERMAL_THROTTLE` | 热节流 | 系统温度过高，已降频 |

## 5.2 HTTP 风格错误码 / HTTP-Style Error Codes

在认证和速率限制场景中，使用类似 HTTP 的状态码：

| 码值 | 描述 | 触发场景 |
|------|------|---------|
| `401` | 未认证 | 需要认证但未提供或令牌无效 |
| `403` | 权限不足 | 已认证但权限不足 |
| `429` | 速率限制超限 | 请求速率超过限制 |

## 5.3 AuthError 类型 / AuthError Types

源文件: `D:/Ainos/system-services/ai-daemon/src/auth.rs` 第 33-65 行

```rust
#[derive(Error, Debug, Clone)]
pub enum AuthError {
    #[error("Invalid authentication token")]
    InvalidToken,

    #[error("Token has expired")]
    TokenExpired,

    #[error("Session not found: {0}")]
    SessionNotFound(String),

    #[error("Permission denied: required {required:?}, granted {granted:?}")]
    PermissionDenied {
        required: Permission,
        granted: Vec<Permission>,
    },

    #[error("Authentication required")]
    AuthenticationRequired,

    #[error("Token file error: {0}")]
    TokenFileError(String),

    #[error("Configuration error: {0}")]
    ConfigError(String),
}
```

### AuthError 错误码映射

| 错误变体 | 错误码 | 描述 |
|---------|--------|------|
| `InvalidToken` | 401 | 令牌无效或格式错误 |
| `TokenExpired` | 401 | 会话已过期，需重新认证 |
| `SessionNotFound` | 401 | 会话令牌无效 |
| `PermissionDenied` | 403 | 缺少所需权限 |
| `AuthenticationRequired` | 401 | 需要先发送 Auth 消息 |
| `TokenFileError` | -1 | 令牌文件读写失败 |
| `ConfigError` | -1 | 认证配置错误 |

## 5.4 RuntimeError 类型 / RuntimeError Types

以下错误类型在运行时引擎中定义（源文件 `D:/Ainos/system-services/ai-daemon/src/runtime.rs`）：

| 错误 | 描述 |
|------|------|
| `ModelNotFound` | 模型文件在磁盘上不存在 |
| `ModelNotLoaded` | 模型未加载到内存 |
| `EngineNotInitialized` | 推理引擎未初始化 |
| `InferenceFailed` | 推理过程失败 |
| `InvalidParameter` | 参数无效（如温度超出范围） |
| `OutOfMemory` | 分配内存失败 |
| `ContextOverflow` | 上下文窗口溢出 |
| `Unsupported` | 不支持的操作或格式 |

## 5.5 RateLimitError 类型 / RateLimitError Types

源文件: `D:/Ainos/system-services/ai-daemon/src/ratelimit.rs` 第 29-46 行

```rust
#[derive(Error, Debug, Clone)]
pub enum RateLimitError {
    #[error("Rate limit exceeded: retry after {retry_after:?}")]
    RateLimitExceeded {
        category: RateLimitCategory,
        retry_after: Duration,
        limit: u64,
        remaining: u64,
    },

    #[error("Invalid rate limit configuration: {0}")]
    ConfigError(String),
}
```

### RateLimitError 错误码映射

| 错误变体 | 错误码 | 描述 |
|---------|--------|------|
| `RateLimitExceeded` | 429 | 速率限制超限，需等待重试 |
| `ConfigError` | -1 | 速率限制配置错误 |

## 5.6 TlsError 类型 / TlsError Types

源文件: `D:/Ainos/system-services/ai-daemon/src/tls.rs` 第 27-59 行

```rust
#[derive(Error, Debug)]
pub enum TlsError {
    #[error("Certificate file not found: {0}")]
    CertFileNotFound(String),

    #[error("Private key file not found: {0}")]
    KeyFileNotFound(String),

    #[error("Failed to load certificate: {0}")]
    CertLoadError(String),

    #[error("Failed to load private key: {0}")]
    KeyLoadError(String),

    #[error("Failed to generate self-signed certificate: {0}")]
    CertGenerationError(String),

    #[error("Failed to create TLS acceptor: {0}")]
    AcceptorError(String),

    #[error("TLS support is not enabled. Enable the `tls` feature in Cargo.toml")]
    FeatureNotEnabled,

    #[error("I/O error: {0}")]
    IoError(String),
}
```

## 5.7 错误响应格式 / Error Response Format

所有错误响应遵循统一的 JSON 格式：

```json
{
  "type": "Error",
  "code": <integer>,
  "message": "<human-readable description>"
}
```

## 5.8 错误场景示例 (20+)

### 示例 1: 一般错误 - 无效 JSON

```json
{"type":"Error","code":-1,"message":"Invalid JSON: missing field `prompt` at line 1 column 30"}
```

### 示例 2: 一般错误 - 序列化错误

```json
{"type":"Error","code":-1,"message":"Serialize error"}
```

### 示例 3: 认证错误 - 未认证

```json
{"type":"Error","code":401,"message":"Authentication required. Send an Auth message first."}
```

### 示例 4: 认证错误 - 令牌无效

```json
{"type":"Error","code":401,"message":"Invalid authentication token"}
```

### 示例 5: 认证错误 - 会话过期

```json
{"type":"Error","code":401,"message":"Session expired. Please re-authenticate."}
```

### 示例 6: 认证错误 - 会话未找到

```json
{"type":"Error","code":401,"message":"Session not found: invalid-session-token"}
```

### 示例 7: 权限错误 - 缺少 Infer 权限

```json
{"type":"Error","code":403,"message":"Permission denied: Infer required"}
```

### 示例 8: 权限错误 - 缺少 Admin 权限

```json
{"type":"Error","code":403,"message":"Permission denied: Admin required"}
```

### 示例 9: 权限错误 - 缺少 ModelLoad 权限

```json
{"type":"Error","code":403,"message":"Permission denied: ModelLoad required"}
```

### 示例 10: 速率限制错误 - 推理超限

```json
{"type":"Error","code":429,"message":"Rate limit exceeded for Inference. Retry after 1 seconds."}
```

### 示例 11: 速率限制错误 - 模型操作超限

```json
{"type":"Error","code":429,"message":"Rate limit exceeded for ModelOps. Retry after 1 seconds."}
```

### 示例 12: 速率限制错误 - 管理操作超限

```json
{"type":"Error","code":429,"message":"Rate limit exceeded for Admin. Retry after 1 seconds."}
```

### 示例 13: 模型错误 - 文件未找到

```json
{"type":"Error","code":-3,"message":"Model file not found: D:/Ainos/models/nonexistent.gguf"}
```

### 示例 14: 模型错误 - 不支持的格式

```json
{"type":"Error","code":-4,"message":"Unsupported model format: .bin (supported: [\"gguf\", \"ggml\", \"onnx\", \"bin\"])"}
```

### 示例 15: 模型错误 - 路径为空

```json
{"type":"Error","code":-2,"message":"Model path is empty"}
```

### 示例 16: 推理错误 - 无可用后端

```json
{"type":"Error","code":-1,"message":"No inference backend available"}
```

### 示例 17: 推理错误 - 云端 API 错误

```json
{"type":"Error","code":-1,"message":"Cloud API error: API returned 401 Unauthorized"}
```

### 示例 18: 上下文错误 - 键未找到

```json
{"type":"Error","code":-1,"message":"Key not found: nonexistent_key"}
```

### 示例 19: 服务器错误 - 意外的消息类型

```json
{"type":"Error","code":-1,"message":"Unexpected server-to-client message type"}
```

### 示例 20: 配置错误 - 认证配置错误

```json
{"type":"Error","code":-1,"message":"Authorization error: Configuration error: No token configured"}
```

### 示例 21: TLS 错误

```rust
// 这些错误在服务器启动时记录，不会直接发送给客户端
// TlsError::CertFileNotFound("cert.pem")
// TlsError::FeatureNotEnabled
// TlsError::AcceptorError("Failed to configure TLS")
```

---

# 6. 完整示例 / Complete Examples

## 6.1 完整认证流程 / Complete Authentication Flow

### 使用 Python 客户端

```python
import socket
import json

def send_message(sock, msg):
    """发送 IPC 消息"""
    data = json.dumps(msg) + "\n"
    sock.sendall(data.encode("utf-8"))

def recv_message(sock):
    """接收 IPC 响应"""
    buf = b""
    while True:
        ch = sock.recv(1)
        if not ch:
            return None
        if ch == b"\n":
            break
        buf += ch
    return json.loads(buf.decode("utf-8"))

# 1. 建立连接
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(("127.0.0.1", 9500))

# 2. 认证
send_message(sock, {"type": "Auth", "token": "your-bearer-token-here-min-16-chars"})
resp = recv_message(sock)
assert resp["type"] == "AuthResponse"
assert resp["success"] == True
session_token = resp["session_token"]
print(f"Authenticated! Session: {session_token}")
print(f"Permissions: {resp['permissions']}")
print(f"Session TTL: {resp['session_ttl_seconds']}s")

# 3. 发送推理请求
send_message(sock, {
    "type": "Inference",
    "model": "default",
    "prompt": "Hello, who are you?",
    "temperature": 0.7,
    "max_tokens": 100
})
resp = recv_message(sock)
print(f"Inference result: {resp['output']}")
print(f"Source: {resp['source']}")
print(f"Tokens: {resp['tokens_generated']}, Time: {resp['inference_ms']}ms")

# 4. 查询状态
send_message(sock, {"type": "Status"})
resp = recv_message(sock)
print(f"Uptime: {resp['uptime']}s")
print(f"Models loaded: {resp['models_loaded']}")
print(f"Total requests: {resp['total_requests']}")

# 5. 断开连接
sock.close()
```

### 使用 Rust 客户端

```rust
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use serde_json::Value;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // 1. 建立连接
    let mut stream = TcpStream::connect("127.0.0.1:9500").await?;

    // 2. 认证
    let auth_msg = r#"{"type":"Auth","token":"your-bearer-token-here-min-16-chars"}"#;
    stream.write_all(auth_msg.as_bytes()).await?;
    stream.write_all(b"\n").await?;

    let mut buf = vec![0u8; 4096];
    let n = stream.read(&mut buf).await?;
    let resp: Value = serde_json::from_slice(&buf[..n])?;
    println!("Auth response: {}", resp);

    // 3. 推理请求
    let infer_msg = r#"{"type":"Inference","model":"default","prompt":"Hello"}"#;
    stream.write_all(infer_msg.as_bytes()).await?;
    stream.write_all(b"\n").await?;

    let n = stream.read(&mut buf).await?;
    let resp: Value = serde_json::from_slice(&buf[..n])?;
    println!("Inference: {}", resp["output"]);

    // 4. 断开
    stream.shutdown().await?;
    Ok(())
}
```

## 6.2 同步推理 / Synchronous Inference

```python
# 同步推理请求
send_message(sock, {
    "type": "Inference",
    "model": "default",
    "prompt": "请用中文写一首关于人工智能的五言绝句",
    "temperature": 0.8,
    "max_tokens": 500
})
resp = recv_message(sock)
print(f"Output: {resp['output']}")
print(f"Tokens: {resp['tokens_generated']}")
print(f"Time: {resp['inference_ms']}ms")
print(f"Source: {resp['source']}")

# 预期输出示例:
# Output: [Ainos 离线推理] 已收到你的问题。当前系统运行在本地模式...
# Tokens: 64
# Time: 50ms
# Source: local
```

## 6.3 流式推理 / Streaming Inference (NDJSON Chunks)

```python
# 流式推理请求
send_message(sock, {
    "type": "InferenceStream",
    "model": "default",
    "prompt": "写一个关于AI的短故事",
    "temperature": 0.9,
    "max_tokens": 2000
})

# 读取流式响应块
while True:
    chunk = recv_message(sock)
    if chunk["type"] == "InferenceChunk":
        print(chunk["chunk"], end="", flush=True)
        if chunk["done"]:
            break
    elif chunk["type"] == "Error":
        print(f"Error: {chunk['message']}")
        break
```

## 6.4 模型管理 / Model Management

### 加载模型

```python
# 加载模型
send_message(sock, {
    "type": "ModelLoad",
    "path": "D:/Ainos/models/phi-3-mini-4k-instruct-q4.gguf"
})
resp = recv_message(sock)
print(f"Status: {resp['status']}")
print(f"Model ID: {resp['model_id']}")
print(f"Message: {resp['message']}")
if resp.get('model_info'):
    info = resp['model_info']
    print(f"  Size: {info['size_mb']}MB")
    print(f"  Architecture: {info['architecture']}")

# 加载已存在的模型
send_message(sock, {
    "type": "ModelLoad",
    "path": "D:/Ainos/models/phi-3-mini-4k-instruct-q4.gguf"
})
resp = recv_message(sock)
# status: "already_loaded"
```

### 卸载模型

```python
# 卸载模型
send_message(sock, {
    "type": "ModelUnload",
    "model_id": "phi_3_mini_4k_instruct_q4_gguf"
})
resp = recv_message(sock)
print(f"Status: {resp['status']}")  # "unloaded"

# 卸载不存在的模型
send_message(sock, {
    "type": "ModelUnload",
    "model_id": "nonexistent_model"
})
resp = recv_message(sock)
print(f"Status: {resp['status']}")  # "not_found"
```

### 列出模型

```python
# 列出所有模型
send_message(sock, {"type": "ModelList"})
resp = recv_message(sock)
for model in resp['models']:
    status = "loaded" if model['loaded'] else "unloaded"
    print(f"  [{status}] {model['id']} ({model['name']}) - {model['size_mb']}MB")
```

## 6.5 上下文管理 / Context Management

```python
# 存储上下文
send_message(sock, {
    "type": "ContextStore",
    "key": "user_name",
    "value": "Alice"
})
resp = recv_message(sock)
print(resp['output'])  # "Context stored: user_name"

# 检索上下文
send_message(sock, {
    "type": "ContextRetrieve",
    "key": "user_name"
})
resp = recv_message(sock)
print(f"Retrieved: {resp['output']}")  # "Alice"

# 检索不存在的键
send_message(sock, {
    "type": "ContextRetrieve",
    "key": "nonexistent"
})
resp = recv_message(sock)
# type: "Error", code: -1, message: "Key not found: nonexistent"
```

## 6.6 速率限制处理 / Rate Limit Handling

```python
import time

def make_request_with_retry(sock, msg, max_retries=3):
    """带重试的请求，处理速率限制"""
    for attempt in range(max_retries):
        send_message(sock, msg)
        resp = recv_message(sock)

        if resp["type"] == "Error" and resp["code"] == 429:
            # 提取重试时间
            import re
            match = re.search(r'Retry after (\d+) seconds?', resp["message"])
            wait = int(match.group(1)) if match else 1
            print(f"Rate limited, waiting {wait}s...")
            time.sleep(wait)
            continue

        return resp
    raise Exception("Max retries exceeded")

# 使用重试逻辑
resp = make_request_with_retry(sock, {"type": "Inference", "model": "default", "prompt": "Hello"})
print(f"Result: {resp['output']}")
```

## 6.7 错误处理 / Error Handling

```python
def safe_send(sock, msg):
    """安全发送消息，处理各种错误"""
    try:
        send_message(sock, msg)
        resp = recv_message(sock)

        if resp["type"] == "Error":
            code = resp["code"]
            msg_text = resp["message"]

            if code == 401:
                print("Auth error: re-authenticating...")
                # 重新认证逻辑
            elif code == 403:
                print(f"Permission error: {msg_text}")
            elif code == 429:
                print(f"Rate limited: {msg_text}")
            else:
                print(f"General error ({code}): {msg_text}")
            return None

        return resp

    except ConnectionRefusedError:
        print("Connection refused - is the daemon running?")
        return None
    except ConnectionResetError:
        print("Connection reset - daemon may have crashed")
        return None
    except json.JSONDecodeError:
        print("Invalid JSON response")
        return None
```

## 6.8 完整会话生命周期 / Full Session Lifecycle

```python
import socket
import json
import time

def demo_full_session():
    """演示完整的 IPC 会话生命周期"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Phase 1: 连接
    print("=" * 60)
    print("Phase 1: 建立连接 / Connect")
    print("=" * 60)
    try:
        sock.connect(("127.0.0.1", 9500))
        print("Connected to 127.0.0.1:9500")
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    # Phase 2: 认证
    print("\n" + "=" * 60)
    print("Phase 2: 认证 / Authenticate")
    print("=" * 60)
    send_message(sock, {"type": "Auth", "token": "your-bearer-token"})
    resp = recv_message(sock)
    if resp["success"]:
        print(f"Authenticated! Session: {resp['session_token']}")
        print(f"Permissions: {resp['permissions']}")
        print(f"TTL: {resp['session_ttl_seconds']}s")
    else:
        print(f"Auth failed: {resp['message']}")
        sock.close()
        return

    # Phase 3: 通信
    print("\n" + "=" * 60)
    print("Phase 3: 通信 / Communicate")
    print("=" * 60)

    # 3a. 状态查询
    send_message(sock, {"type": "Status"})
    resp = recv_message(sock)
    print(f"Status: uptime={resp['uptime']}s, models={resp['models_loaded']}, "
          f"requests={resp['total_requests']}, sessions={resp['active_sessions']}")

    # 3b. 推理
    send_message(sock, {
        "type": "Inference", "model": "default",
        "prompt": "Hello!",
        "temperature": 0.7
    })
    resp = recv_message(sock)
    print(f"Inference ({resp['source']}): {resp['output'][:50]}...")

    # 3c. 列出现有模型
    send_message(sock, {"type": "ModelList"})
    resp = recv_message(sock)
    print(f"Models: {len(resp['models'])} registered")

    # 3d. 上下文管理
    send_message(sock, {"type": "ContextStore", "key": "demo", "value": "active"})
    recv_message(sock)

    # 3e. 速率限制查询
    send_message(sock, {"type": "RateLimitStatus"})
    resp = recv_message(sock)
    print(f"Rate limits: {resp}")

    # Phase 4: 断开连接
    print("\n" + "=" * 60)
    print("Phase 4: 断开连接 / Disconnect")
    print("=" * 60)
    sock.close()
    print("Disconnected. Session cleaned up.")

if __name__ == "__main__":
    demo_full_session()
```

## 6.9 批处理示例 / Batch Processing Example

```python
def batch_inference(sock, prompts, model="default"):
    """批量推理请求"""
    results = []
    for prompt in prompts:
        send_message(sock, {
            "type": "Inference",
            "model": model,
            "prompt": prompt,
            "temperature": 0.7,
            "max_tokens": 200
        })
        resp = recv_message(sock)
        if resp["type"] == "InferenceResponse":
            results.append({
                "prompt": prompt,
                "response": resp["output"],
                "tokens": resp["tokens_generated"],
                "time_ms": resp["inference_ms"],
                "source": resp["source"]
            })
        elif resp["type"] == "Error":
            results.append({"prompt": prompt, "error": resp["message"]})
    return results

# 使用示例
prompts = [
    "What is AI?",
    "Explain machine learning",
    "What is deep learning?",
]
results = batch_inference(sock, prompts)
for r in results:
    if "error" in r:
        print(f"Error: {r['error']}")
    else:
        print(f"Q: {r['prompt']}")
        print(f"A: {r['response'][:60]}...")
        print(f"  ({r['tokens']} tokens, {r['time_ms']}ms, {r['source']})")
```

## 6.10 服务端处理流程 / Server-Side Processing Flow

源文件: `D:/Ainos/system-services/ai-daemon/src/ipc.rs` 第 635-742 行

```rust
/// 核心消息路由器
pub(crate) async fn process_message(
    state: Arc<RwLock<AppState>>,
    msg: IpcMessage,
    client: &ClientState,
) -> IpcMessage {
    // 1. 处理认证消息（绕过所有检查）
    if let IpcMessage::Auth { token } = msg {
        return handle_auth(state, &token, client).await;
    }

    // 2. 检查认证状态
    if session_manager.is_enabled() && !client.authenticated {
        return IpcMessage::Error { code: 401, message: "Authentication required".to_string() };
    }

    // 3. 检查权限
    if let Some(required_perm) = Permission::from_message_type(msg_type) {
        // 验证会话权限
        match session_manager.check_permission(session_token, &required_perm).await {
            Ok(_) => {}
            Err(AuthError::PermissionDenied { .. }) => {
                return IpcMessage::Error { code: 403, message: "Permission denied".to_string() };
            }
            Err(AuthError::TokenExpired) => {
                return IpcMessage::Error { code: 401, message: "Session expired".to_string() };
            }
            Err(e) => {
                return IpcMessage::Error { code: 403, message: format!("Auth error: {}", e) };
            }
        }
    }

    // 4. 检查速率限制
    if rate_limit_enabled && should_rate_limit(msg_type) {
        let category = RateLimitCategory::from_message_type(msg_type);
        if let Err(e) = rate_limiter.check_rate_limit(client_key, category).await {
            return IpcMessage::Error {
                code: 429,
                message: format!("Rate limit exceeded for {:?}. Retry after {} seconds.",
                    category, retry_after.as_secs()),
            };
        }
    }

    // 5. 分派给处理函数
    match msg {
        IpcMessage::Inference { model, prompt, temperature, max_tokens, session_id } => {
            handle_inference(state, model, prompt, temperature, max_tokens, session_id, client).await
        }
        IpcMessage::ModelLoad { path } => handle_model_load(state, &path, client).await,
        IpcMessage::Status => handle_status(state, client).await,
        // ... 其他消息类型
    }
}
```

---

# 附录 / Appendix

## A. 配置示例 / Sample Configuration

源文件: `D:/Ainos/system-services/ai-daemon/src/config.rs`

```toml
# D:/Ainos/configs/ai-daemon.toml
# Ainos AI Daemon 配置文件

# 基本配置
models_dir = "D:/Ainos/models"
default_model = "phi-3-mini-4k-instruct-q4.gguf"
socket_path = "127.0.0.1:9500"

# 本地推理配置
enable_local = true
local_engine = "ggml"
max_concurrent_inferences = 2
model_cache_size_mb = 4096
inference_timeout_secs = 120

# 云端回退配置
enable_cloud = true
cloud_api_url = "https://api.weelinking.com/v1"
cloud_api_key = ""
cloud_model = "gpt-5.6-sol"
network_check_interval = 30
cloud_fallback_confidence = 0.6

# 上下文管理
context_dir = "D:/Ainos/data/contexts"
max_contexts = 1000
context_ttl_days = 30

# 日志配置
log_level = "info"
audit_log = "D:/Ainos/logs/audit.log"
audit_all_requests = false

# 认证配置
[auth]
enabled = true
token = ""
token_path = "D:/Ainos/data/auth_token.txt"
session_ttl_seconds = 3600
default_permissions = ["infer", "status", "context"]
audit_log_path = "D:/Ainos/logs/audit.log"
audit_all_requests = false

# 速率限制配置
[ratelimit]
enabled = true
infer_rps = 100.0
infer_burst = 200.0
model_rps = 10.0
model_burst = 20.0
status_rps = 1000.0
status_burst = 2000.0
admin_rps = 5.0
admin_burst = 10.0
max_clients = 1000
cleanup_interval_secs = 300

# TLS 配置
[tls]
enabled = false
cert_path = "D:/Ainos/certs/server.crt"
key_path = "D:/Ainos/certs/server.key"
verify_client = false
```

## B. 完整消息类型列表 / Complete Message Type List

| 类型 | 方向 | 描述 | 是否需认证 |
|------|------|------|-----------|
| `Auth` | Client → Server | 认证请求 | 否 |
| `AuthResponse` | Server → Client | 认证响应 | 否 |
| `Inference` | Client → Server | 同步推理请求 | 是 |
| `InferenceResponse` | Server → Client | 推理响应 | 是 |
| `InferenceStream` | Client → Server | 流式推理请求 | 是 |
| `InferenceChunk` | Server → Client | 流式推理块 | 是 |
| `ModelLoad` | Client → Server | 模型加载请求 | 是 |
| `ModelLoadResponse` | Server → Client | 模型加载响应 | 是 |
| `ModelUnload` | Client → Server | 模型卸载请求 | 是 |
| `ModelUnloadResponse` | Server → Client | 模型卸载响应 | 是 |
| `ModelList` | Client → Server | 模型列表请求 | 是 |
| `ModelListResponse` | Server → Client | 模型列表响应 | 是 |
| `ContextStore` | Client → Server | 上下文存储请求 | 是 |
| `ContextRetrieve` | Client → Server | 上下文检索请求 | 是 |
| `Status` | Client → Server | 状态查询 | 是 |
| `StatusResponse` | Server → Client | 状态响应 | 是 |
| `RateLimitStatus` | Client → Server | 速率限制查询 | 是 |
| `Error` | Server → Client | 错误响应 | 否 |

## C. 传输层对比 / Transport Layer Comparison

| 特性 | TCP | Unix Domain Socket | Named Pipe | XPC | launchd |
|------|-----|-------------------|------------|-----|---------|
| 平台 | 全平台 | Linux | Windows | macOS | macOS |
| 性能 | 中等 | 高 | 高 | 高 | 高 |
| 安全性 | 需 TLS | 文件权限 | ACL | XPC 沙箱 | 套接字激活 |
| 连接方式 | 127.0.0.1:9500 | `/var/run/ainos/...sock` | `\\.\pipe\ainos-daemon` | XPC 服务 | launchd FD |
| 回退方案 | - | → TCP | → TCP | → TCP | → TCP |

## D. 源文件索引 / Source File Index

| 文件 | 内容 |
|------|------|
| `D:/Ainos/system-services/ai-daemon/src/ipc.rs` | IPC 消息定义、TCP/Unix 服务器、消息处理路由 |
| `D:/Ainos/system-services/ai-daemon/src/ipc_windows.rs` | Windows Named Pipe 实现 |
| `D:/Ainos/system-services/ai-daemon/src/auth.rs` | 认证、会话管理、权限系统、审计日志 |
| `D:/Ainos/system-services/ai-daemon/src/ratelimit.rs` | 令牌桶速率限制器 |
| `D:/Ainos/system-services/ai-daemon/src/tls.rs` | TLS 加密传输 |
| `D:/Ainos/system-services/ai-daemon/src/config.rs` | 配置结构定义 |
| `D:/Ainos/system-services/ai-daemon/src/main.rs` | 入口点、AppState、服务管理 |
| `D:/Ainos/system-services/ai-daemon/src/context.rs` | 上下文管理器 |
| `D:/Ainos/system-services/ai-daemon/src/models.rs` | 模型注册表 |
| `D:/Ainos/system-services/ai-daemon/src/runtime.rs` | 运行时引擎管理 |
| `D:/Ainos/system-services/ai-daemon/src/cache.rs` | 语义缓存 |
| `D:/Ainos/system-services/ai-daemon/src/thermal.rs` | 温度监控 |
| `D:/Ainos/system-services/ai-daemon/src/macos/xpc.rs` | macOS XPC 桥接 |
| `D:/Ainos/system-services/ai-daemon/src/macos/launchd.rs` | macOS launchd 套接字激活 |
| `D:/Ainos/system-services/ai-daemon/src/macos/thermal_macos.rs` | macOS 热策略读取 |

---

> **文档版本 / Document Version:** 1.0.0
> **基于源文件版本 / Based on Source Version:** 1.0.0
> **生成日期 / Generated:** 2026-08-04
> **维护者 / Maintainer:** Ainos OS Core Team