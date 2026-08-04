# AinosOS SDK API Reference / AinosOS SDK API 参考

> **版本 / Version**: 0.1.0  
> **最后更新 / Last Updated**: 2026-08-04  
> **协议 / Protocol**: NDJSON over TCP (newline-delimited JSON)  
> **默认端口 / Default Port**: 9500  
> **默认主机 / Default Host**: 127.0.0.1

---

## 目录 / Table of Contents

1. [Python SDK](#1-python-sdk)
2. [Go SDK](#2-go-sdk)
3. [Rust SDK](#3-rust-sdk)
4. [Java SDK](#4-java-sdk)
5. [C# SDK](#5-c-sdk)
6. [Node.js / TypeScript SDK](#6-nodejs--typescript-sdk)
7. [C SDK (libainos)](#7-c-sdk-libainos)
8. [Common Patterns / 通用模式](#8-common-patterns--通用模式)

---

## 1. Python SDK

**源文件 / Source Files**: `userland/sdk/python/ainos/`  
**包名 / Package**: `ainos`  
**依赖 / Dependencies**: 无（纯 Python 标准库）/ None (pure Python stdlib)  
**协议 / Protocol**: NDJSON over TCP

### 1.1 包结构 / Package Structure

```
ainos/
  __init__.py     # 公共 API 导出 / Public API exports
  client.py       # AinosClient 主类 / Main client class
  models.py       # 数据模型 / Data models
  setup.py        # 包安装配置 / Package setup
examples/
  basic_usage.py  # 使用示例 / Usage examples
```

### 1.2 公共导出 / Public Exports

```python
from ainos import (
    AinosClient,           # 主客户端类 / Main client class
    AinosConnectionError,  # 连接错误 / Connection error
    AinosError,            # 基础错误 / Base error
    AinosInferenceError,   # 推理错误 / Inference error
    AinosTimeoutError,     # 超时错误 / Timeout error
    ContextEntry,          # 上下文条目 / Context entry
    InferenceResponse,     # 推理响应 / Inference response
    ModelInfo,             # 模型信息 / Model info
    SystemStatus,          # 系统状态 / System status
)
```

### 1.3 AinosClient 类 / AinosClient Class

```python
class AinosClient:
    """Synchronous TCP client for the Ainos AI Daemon.
    
    Parameters:
        host: Daemon hostname or IP address (default "127.0.0.1").
        port: Daemon TCP port (default 9500).
        connect_timeout: Connection timeout in seconds (default 5).
        read_timeout: Read (socket) timeout in seconds (default 120).
        auto_reconnect: Attempt a single reconnect on failure (default True).
        reconnect_delay: Seconds to wait before reconnecting (default 1).
        auth_token: Bearer token for authentication.
        auto_authenticate: Auto-authenticate after connect (default True).
    """
```

#### 构造函数参数 / Constructor Parameters

| 参数 / Parameter | 类型 / Type | 默认值 / Default | 描述 / Description |
|---|---|---|---|
| `host` | `str` | `"127.0.0.1"` | 守护进程主机名或 IP 地址 |
| `port` | `int` | `9500` | 守护进程 TCP 端口 |
| `connect_timeout` | `float` | `5.0` | 连接超时（秒） |
| `read_timeout` | `float` | `120.0` | 读取超时（秒） |
| `auto_reconnect` | `bool` | `True` | 是否自动重连 |
| `reconnect_delay` | `float` | `1.0` | 重连延迟（秒） |
| `auth_token` | `Optional[str]` | `None` | 认证令牌 |
| `auto_authenticate` | `bool` | `True` | 是否自动认证 |

#### 属性 / Properties

```python
@property
def connected(self) -> bool
    """True if the socket is currently open."""

@property
def authenticated(self) -> bool
    """True if the client has been authenticated with the daemon."""

@property
def session_token(self) -> Optional[str]
    """The current session token, if authenticated."""

@property
def permissions(self) -> list[str]
    """The permissions granted to the current session."""
```

#### 生命周期方法 / Lifecycle Methods

```python
def connect(self) -> None
    """Open a TCP connection to the daemon.
    If auth_token and auto_authenticate are set, attempts authentication.
    Raises:
        AinosConnectionError: If connection cannot be established.
        AinosAuthError: If auto-authentication fails.
    """

def disconnect(self) -> None
    """Close the TCP connection if open."""

def authenticate(self, token: Optional[str] = None) -> dict[str, Any]
    """Authenticate with the daemon using a bearer token.
    Returns dict with keys: success, session_token, message, permissions, session_ttl_seconds.
    Raises:
        AinosAuthError: If authentication fails.
        AinosConnectionError: If the connection is lost.
    """
```

#### 上下文管理器 / Context Manager

```python
def __enter__(self) -> AinosClient
    """Connect on enter."""

def __exit__(self, *exc_args: Any) -> None
    """Disconnect on exit."""
```

#### 推理 API / Inference API

```python
def infer(
    self,
    prompt: str,
    model: str = "default",
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    session_id: Optional[str] = None,
) -> InferenceResponse
    """Send an inference request to the daemon.
    Returns InferenceResponse with fields: output, tokens_generated, inference_ms, source.
    Raises:
        AinosConnectionError: If the connection is lost.
        AinosInferenceError: If the daemon returns an error.
        AinosTimeoutError: If the operation times out.
    """
```

#### 模型管理 API / Model Management API

```python
def model_list(self) -> list[ModelInfo]
    """List all registered models.
    Returns list of ModelInfo with fields: id, name, path, size_mb, loaded, architecture.
    """

def model_load(self, path: str) -> dict[str, Any]
    """Load a model into memory by its file path.
    Returns dict with keys: model_id, status, message, model_info.
    """

def model_unload(self, model_id: str) -> dict[str, Any]
    """Unload a model from memory.
    Returns dict with keys: model_id, status, message.
    """
```

#### 上下文管理 API / Context Management API

```python
def context_store(self, key: str, value: str) -> str
    """Persist a key-value pair in the daemon's context store.
    Returns a confirmation message from the daemon.
    """

def context_retrieve(self, key: str) -> Optional[str]
    """Retrieve a value by key from the daemon's context store.
    Returns the stored value, or None if the key was not found.
    """
```

#### 系统状态 API / System Status API

```python
def status(self) -> SystemStatus
    """Query the daemon's health and statistics.
    Returns SystemStatus with fields: uptime, models_loaded, total_requests, network_available.
    """

def rate_limit_status(self) -> dict[str, Any]
    """Query the current rate limit status for this session.
    Returns dict with rate limit information for each category.
    """
```

### 1.4 数据模型 / Data Models

```python
@dataclasses.dataclass
class InferenceResponse:
    output: str                         # 生成的文本 / Generated text
    tokens_generated: int = 0           # 生成 token 数 / Tokens produced
    inference_ms: int = 0               # 推理耗时 (毫秒) / Inference time (ms)
    source: str = "local"               # 来源 ("local" 或 "cloud") / Source

@dataclasses.dataclass
class ModelInfo:
    id: str                             # 模型标识符 / Model identifier
    name: str                           # 模型名称 / Model name
    path: str                           # 文件路径 / File path
    size_mb: int = 0                    # 文件大小 (MB) / File size
    loaded: bool = False                # 是否已加载 / Loaded flag
    architecture: str = "auto"          # 模型架构 / Model architecture

@dataclasses.dataclass
class SystemStatus:
    uptime: int = 0                     # 运行时间 (秒) / Uptime (seconds)
    models_loaded: int = 0              # 已加载模型数 / Loaded models
    total_requests: int = 0             # 总请求数 / Total requests
    network_available: bool = False     # 网络可用性 / Network availability

@dataclasses.dataclass
class ContextEntry:
    key: str                            # 查找键 / Lookup key
    value: str                          # 存储值 / Stored value
    session_id: str = "default"         # 会话 ID / Session ID
```

### 1.5 错误类型 / Error Types

| 异常 / Exception | 基类 / Base | 描述 / Description |
|---|---|---|
| `AinosError` | `Exception` | 所有 SDK 错误的基础异常 |
| `AinosConnectionError` | `AinosError` | 连接建立或维护失败 |
| `AinosInferenceError` | `AinosError` | 推理请求失败 |
| `AinosTimeoutError` | `AinosError` | 操作超时 |
| `AinosAuthError` | `AinosError` | 认证失败 |

### 1.6 完整示例 / Complete Example

```python
"""Ainos Python SDK 完整使用示例 / Complete usage example."""

from ainos import AinosClient, AinosError

def main():
    # 方式一: 使用上下文管理器（自动连接和断开）
    with AinosClient(
        host="127.0.0.1",
        port=9500,
        auth_token="your-token-here",
        connect_timeout=10,
        read_timeout=120,
    ) as client:
        # 检查状态
        status = client.status()
        print(f"Daemon uptime: {status.uptime}s")
        print(f"Models loaded: {status.models_loaded}")

        # 列出模型
        models = client.model_list()
        for m in models:
            print(f"  Model: {m.name} (loaded={m.loaded})")

        # 推理
        try:
            resp = client.infer(
                prompt="What is the meaning of life?",
                model="default",
                temperature=0.7,
                max_tokens=256,
            )
            print(f"Response: {resp.output}")
            print(f"Tokens: {resp.tokens_generated}, Time: {resp.inference_ms}ms")
        except AinosError as e:
            print(f"Inference failed: {e}")

        # 上下文管理
        client.context_store("my_key", "my_value")
        value = client.context_retrieve("my_key")
        print(f"Context value: {value}")

    # 方式二: 手动管理连接
    client = AinosClient(auth_token="your-token")
    try:
        client.connect()
        resp = client.infer("Hello!")
        print(resp.output)
    finally:
        client.disconnect()


def streaming_example():
    """Python SDK 目前为同步模式，流式推理需使用底层接口。
    Note: The Python SDK is currently synchronous; for streaming use the
    underlying transport directly or the Rust/Go SDKs.
    """
    pass


if __name__ == "__main__":
    main()
```

### 1.7 内部通信协议 / Internal Wire Protocol

Python SDK 使用 NDJSON（newline-delimited JSON）协议与守护进程通信：

```python
# 请求格式 / Request format
{"type":"Inference","model":"default","prompt":"Hello, Ainos!","temperature":0.7}\n

# 响应格式 / Response format
{"type":"InferenceResponse","output":"Hello!","tokens_generated":5,"inference_ms":150,"source":"local"}\n

# 错误格式 / Error format
{"type":"Error","code":-1,"message":"Model not found"}\n
```

---

## 2. Go SDK

**源文件 / Source Files**: `bindings/go/ainos/`  
**模块路径 / Module Path**: `ainos`  
**协议 / Protocol**: NDJSON over TCP

### 2.1 包结构 / Package Structure

```
bindings/go/ainos/
  client.go     # AinosClient 主类 / Main client
  types.go      # 类型定义和消息解析 / Types and parsing
  errors.go     # 错误类型和重试逻辑 / Error types and retry
  options.go    # 函数选项模式 / Functional options
  auth.go       # 认证管理 / Authentication
  stream.go     # 流式推理 / Streaming inference
  transport.go  # TCP 传输层 / TCP transport
  go.mod        # Go 模块文件 / Go module
```

### 2.2 Client 结构体 / Client Struct

```go
type Client struct {
    // 内部字段，通过 NewClient 创建 / Internal fields, created via NewClient
}

func NewClient(opts ...ClientOption) *Client
    // 创建新 Client，默认连接到 127.0.0.1:9500
```

### 2.3 函数选项 / Function Options

```go
// Client 配置选项 / Client configuration options
func WithHost(host string) ClientOption
func WithPort(port int) ClientOption
func WithConnectTimeout(d time.Duration) ClientOption
func WithReadTimeout(d time.Duration) ClientOption
func WithWriteTimeout(d time.Duration) ClientOption
func WithTimeout(d time.Duration) ClientOption           // 同时设置连接和读取超时
func WithAutoReconnect(enabled bool) ClientOption
func WithReconnectDelay(d time.Duration) ClientOption
func WithMaxReconnectAttempts(n int) ClientOption
func WithAuthToken(token string) ClientOption
func WithAutoAuthenticate(enabled bool) ClientOption
func WithTLS(enabled bool) ClientOption
func WithTLSInsecureSkipVerify(skip bool) ClientOption
func WithRetryConfig(rc RetryConfig) ClientOption

// 请求选项 / Request options
func WithTemperature(t float64) RequestOption
func WithTopP(p float64) RequestOption
func WithTopK(k int) RequestOption
func WithMaxTokens(n int) RequestOption
func WithStop(seqs []string) RequestOption
func WithStream(stream bool) RequestOption
func WithModel(model string) RequestOption
func WithSessionID(sessionID string) RequestOption
```

### 2.4 连接管理 / Connection Management

```go
func (c *Client) Connect() error
    /* 建立 TCP 连接。如果配置了 AuthToken 和 AutoAuthenticate，自动认证。
    返回: ErrNotConnected, ErrAlreadyConnected, ConnectionError, AuthError */

func (c *Client) Disconnect() error
    /* 关闭连接。停止心跳 goroutine，清除认证状态。*/

func (c *Client) Reconnect() error
    /* 关闭当前连接并重新建立。*/

func (c *Client) IsConnected() bool
    /* 返回是否已连接。*/
```

### 2.5 认证 API / Authentication API

```go
func (c *Client) Authenticate(token string) (*AuthResponse, error)
    /* 使用 bearer token 认证。
    返回: AuthResponse (success, session_token, permissions, session_ttl_seconds) */

func (c *Client) Session() *SessionInfo
    /* 返回当前会话信息 (Token, Permissions, TTL, Created)。*/

func (c *Client) IsAuthenticated() bool
func (c *Client) HasPermission(perm string) bool
```

### 2.6 推理 API / Inference API

```go
func (c *Client) Infer(ctx context.Context, req *InferenceRequest) (*InferenceResponse, error)
    /* 发送推理请求并等待完整响应。
    返回: InferenceResponse (Text, TokensGenerated, InferenceMs, Source, TokensPerSecond) */

func (c *Client) InferStream(ctx context.Context, req *InferenceRequest) (<-chan *InferenceChunk, error)
    /* 发送流式推理请求，返回 channel。
    返回: <-chan *InferenceChunk (Text, Index, FinishReason, Done)
    注意: 必须消费 channel 直到关闭，否则会泄漏 goroutine。*/

func (c *Client) BatchInfer(ctx context.Context, reqs []*InferenceRequest) ([]*InferenceResponse, error)
    /* 并发发送多个推理请求，使用连接池。结果按请求顺序返回。*/
```

### 2.7 数据类型 / Data Types

```go
type InferenceRequest struct {
    Model       string         // 模型标识符 (默认 "default")
    Prompt      string         // 输入提示文本
    Temperature *float64       // 采样温度 (0.0-2.0)
    TopP        *float64       // 核采样阈值
    TopK        *int           // Top-K 采样
    MaxTokens   *int           // 最大生成 token 数
    Stop        []string       // 停止序列
    SessionID   string         // 会话 ID
    Stream      bool           // 是否启用流式
}

type InferenceResponse struct {
    Text            string    // 生成的文本
    TokensGenerated int       // 生成 token 数
    InferenceMs     int64     // 推理耗时 (毫秒)
    Source          string    // "local" 或 "cloud"
    TokensPerSecond float64   // 生成吞吐量
    Model           string    // 使用的模型
    Usage           *UsageInfo // token 使用统计
}

type InferenceChunk struct {
    Text         string   // 文本片段
    Index        int      // 序号
    FinishReason string   // 停止原因
    Done         bool     // 是否最后一块
}

type ModelInfo struct {
    ID           string   // 模型标识符
    Name         string   // 模型名称
    Path         string   // 文件路径
    SizeMB       int64    // 文件大小 (MB)
    Loaded       bool     // 是否已加载
    Architecture string   // 模型架构
    Quantized    string   // 量化级别
}

type SystemStatus struct {
    Uptime           int64           // 运行时间 (秒)
    ModelsLoaded     int             // 已加载模型数
    TotalRequests    int64           // 总请求数
    NetworkAvailable bool            // 网络可用性
    ActiveSessions   int             // 活跃会话数
    RateLimits       []RateLimitInfo // 速率限制信息
}

type HealthStatus struct {
    Status       string  // 健康状态 ("ok", "degraded", "error")
    Uptime       int64   // 运行时间 (秒)
    Version      string  // 守护进程版本
    ModelsLoaded int     // 已加载模型数
    MemoryUsage  float64 // 内存使用 (MB)
    CPUUsage     float64 // CPU 使用率 (%)
    PowerMode    string  // 电源策略模式
}

type RateLimitInfo struct {
    Category     string   // 类别 ("inference", "model_ops", "status", "admin")
    Limit        int64    // 窗口内最大请求数
    Remaining    int64    // 当前窗口剩余请求数
    ResetSeconds int64    // 重置时间 (秒)
}

type AuthResponse struct {
    Success          bool     // 认证是否成功
    SessionToken     string   // 会话令牌
    Message          string   // 状态消息
    Permissions      []string // 权限列表
    SessionTTLSeconds int64   // 会话 TTL (秒)
}

type ContextEntry struct {
    Key         string    // 查找键
    Value       []byte    // 存储值
    StringValue string    // 字符串值
    SessionID   string    // 会话 ID
    Timestamp   time.Time // 存储时间
    TTL         int       // 生存时间 (秒)
}
```

### 2.8 权限常量 / Permission Constants

```go
const (
    PermissionInfer    = "infer"     // 推理权限
    PermissionModelOps = "model_ops" // 模型管理权限
    PermissionStatus   = "status"    // 状态查询权限
    PermissionAdmin    = "admin"     // 管理员权限
    PermissionAll      = "*"         // 所有权限
)
```

### 2.9 错误类型 / Error Types

```go
// 哨兵错误 / Sentinel errors
var ErrNotConnected       = errors.New("ainos: not connected to daemon")
var ErrAlreadyConnected   = errors.New("ainos: already connected")
var ErrNoAuthToken        = errors.New("ainos: no authentication token provided")
var ErrAuthRequired       = errors.New("ainos: authentication required")
var ErrSessionExpired     = errors.New("ainos: session token expired")
var ErrStreamClosed       = errors.New("ainos: stream closed")
var ErrModelNotFound      = errors.New("ainos: model not found")

// 结构化错误类型 / Structured error types
type Error struct { Code int; Message string; Op string }              // 守护进程错误
type ConnectionError struct { Op string; Addr string; Err error }     // 连接错误
type AuthError struct { Message string }                               // 认证错误
type PermissionError struct { Permission string }                      // 权限错误
type RateLimitError struct { Category string; RetryAfter time.Duration } // 速率限制
type InferenceError struct { Message string; Code int }                // 推理错误
type TimeoutError struct { Operation string; Timeout time.Duration }   // 超时错误
type ProtocolError struct { Message string }                           // 协议错误
```

### 2.10 错误分类函数 / Error Classification Functions

```go
func IsRetryable(err error) bool    // 错误是否可重试
func IsAuthError(err error) bool     // 是否为认证错误
func IsConnectionError(err error) bool // 是否为连接错误
func IsTimeout(err error) bool       // 是否为超时错误
func IsRateLimited(err error) bool   // 是否为速率限制
func DaemonCode(err error) (int, bool) // 获取守护进程错误码
```

### 2.11 重试配置 / Retry Configuration

```go
type RetryConfig struct {
    MaxRetries        int           // 最大重试次数 (默认 3)
    InitialBackoff    time.Duration // 初始退避时间 (默认 100ms)
    MaxBackoff        time.Duration // 最大退避时间 (默认 10s)
    BackoffMultiplier float64       // 退避乘数 (默认 2.0)
}
```

### 2.12 完整示例 / Complete Example

```go
package main

import (
    "context"
    "fmt"
    "log"

    "ainos"
)

func main() {
    // 创建客户端 / Create client
    client := ainos.NewClient(
        ainos.WithHost("127.0.0.1"),
        ainos.WithPort(9500),
        ainos.WithAuthToken("your-token"),
        ainos.WithTimeout(30*time.Second),
        ainos.WithAutoReconnect(true),
    )

    // 连接 / Connect
    if err := client.Connect(); err != nil {
        log.Fatal(err)
    }
    defer client.Disconnect()

    // 推理 / Inference
    resp, err := client.Infer(context.Background(), &ainos.InferenceRequest{
        Prompt:    "What is the meaning of life?",
        Model:     "default",
        MaxTokens: intPtr(256),
    })
    if err != nil {
        log.Fatal(err)
    }
    fmt.Printf("Response: %s\n", resp.Text)
    fmt.Printf("Tokens: %d, Time: %dms\n", resp.TokensGenerated, resp.InferenceMs)

    // 流式推理 / Streaming inference
    chunks, err := client.InferStream(context.Background(), &ainos.InferenceRequest{
        Prompt: "Tell me a story",
    })
    if err != nil {
        log.Fatal(err)
    }
    for chunk := range chunks {
        fmt.Print(chunk.Text)
    }

    // 模型管理 / Model management
    models, err := client.ModelList()
    if err != nil {
        log.Fatal(err)
    }
    for _, m := range models {
        fmt.Printf("Model: %s (loaded=%v)\n", m.Name, m.Loaded)
    }

    // 上下文管理 / Context management
    err = client.ContextStore("session1", "key1", []byte("value1"), 3600)
    if err != nil {
        log.Fatal(err)
    }
    val, err := client.ContextRetrieve("session1", "key1")
    if err != nil {
        log.Fatal(err)
    }
    fmt.Printf("Context value: %s\n", string(val))

    // 系统状态 / System status
    status, err := client.Status()
    if err != nil {
        log.Fatal(err)
    }
    fmt.Printf("Uptime: %ds, Models: %d\n", status.Uptime, status.ModelsLoaded)
}

func intPtr(i int) *int { return &i }
```

---

## 3. Rust SDK

**源文件 / Source Files**: `bindings/rust/ainos-sdk/`  
**包名 / Crate**: `ainos-sdk`  
**语言 / Language**: Rust (async, tokio-based)

### 3.1 模块结构 / Module Structure

```rust
// 公共模块 / Public modules
pub mod auth;         // 认证和会话管理 / Authentication and session management
pub mod builder;      // 构建器模式 / Builder pattern
pub mod client;       // 主客户端实现 / Main client implementation
pub mod error;        // 错误类型和重试逻辑 / Error types and retry logic
pub mod streaming;    // 流式推理支持 / Streaming inference support
pub mod transport;    // 传输层 (TCP, Unix, mock) / Transport layer
pub mod types;        // 所有 IPC 数据类型 / All IPC data types

// 重新导出 / Re-exports
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
```

### 3.2 AinosClient 构建器 / AinosClient Builder

```rust
pub struct AinosClientBuilder { /* ... */ }

impl AinosClientBuilder {
    pub fn new() -> Self
    pub fn host(self, host: impl Into<String>) -> Self
    pub fn port(self, port: u16) -> Self
    pub fn auth_token(self, token: impl Into<String>) -> Self
    pub fn connect_timeout(self, timeout: Duration) -> Self
    pub fn read_timeout(self, timeout: Duration) -> Self
    pub fn auto_reconnect(self, enabled: bool) -> Self
    pub fn max_reconnect_attempts(self, n: u32) -> Self
    pub fn tls(self, enabled: bool) -> Self
    pub fn build(self) -> AinosClient
}
```

### 3.3 AinosClient 方法 / AinosClient Methods

```rust
impl AinosClient {
    // 连接管理 / Connection management
    pub async fn connect(&self) -> Result<(), AinosError>
    pub async fn disconnect(&self) -> Result<(), AinosError>
    pub fn is_connected(&self) -> bool

    // 认证 / Authentication
    pub async fn authenticate(&self, token: &str) -> Result<AuthResponse, AinosError>
    pub fn is_authenticated(&self) -> bool
    pub fn session_token(&self) -> Option<&str>

    // 推理 / Inference
    pub async fn infer(&self, req: &InferenceRequest) -> Result<InferenceResponse, AinosError>
    pub async fn infer_stream(&self, req: &InferenceRequest) -> Result<InferenceStream, AinosError>

    // 模型管理 / Model management
    pub async fn model_list(&self) -> Result<Vec<ModelInfo>, AinosError>
    pub async fn model_load(&self, path: &str, opts: Option<&ModelLoadOptions>) -> Result<ModelInfo, AinosError>
    pub async fn model_unload(&self, id: &str) -> Result<(), AinosError>

    // 上下文管理 / Context management
    pub async fn context_store(&self, session_id: &str, key: &str, value: &[u8], ttl: u64) -> Result<(), AinosError>
    pub async fn context_retrieve(&self, session_id: &str, key: &str) -> Result<Option<Vec<u8>>, AinosError>

    // 系统状态 / System status
    pub async fn status(&self) -> Result<SystemStatus, AinosError>
    pub async fn health(&self) -> Result<HealthStatus, AinosError>
    pub async fn rate_limit_status(&self) -> Result<RateLimitStatus, AinosError>
}
```

### 3.4 InferenceStream / InferenceStream

```rust
pub struct InferenceStream { /* ... */ }

impl InferenceStream {
    // 获取下一个块 / Get next chunk
    pub async fn next_chunk(&mut self) -> Option<Result<InferenceChunk, AinosError>>

    // 收集所有块到单个响应 / Collect all chunks into a single response
    pub async fn collect(self) -> Result<InferenceResponse, AinosError>

    // 关闭流 / Close the stream
    pub fn close(&self)
}

// 实现 Stream trait / Implements Stream trait
impl Stream for InferenceStream {
    type Item = Result<InferenceChunk, AinosError>;
    fn poll_next(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>>;
}
```

### 3.5 数据类型 / Data Types

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InferenceRequest {
    pub model: String,                    // 模型标识符
    pub prompt: String,                   // 输入提示
    pub temperature: Option<f64>,         // 采样温度 (0.0-2.0)
    pub top_p: Option<f64>,              // 核采样阈值
    pub top_k: Option<u32>,              // Top-K 采样
    pub max_tokens: Option<u32>,         // 最大 token 数
    pub stop: Option<Vec<String>>,       // 停止序列
    pub session_id: Option<String>,      // 会话 ID
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InferenceResponse {
    pub output: String,                   // 生成的文本
    pub tokens_generated: u32,           // 生成 token 数
    pub inference_ms: u64,               // 推理耗时 (毫秒)
    pub source: String,                   // "local" 或 "cloud"
    pub model: String,                    // 使用的模型
    pub usage: Option<UsageInfo>,         // token 使用统计
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InferenceChunk {
    pub chunk: String,                    // 文本片段
    pub done: bool,                       // 是否最后一块
    pub index: u32,                       // 序号
    pub finish_reason: Option<String>,    // 停止原因
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelInfo {
    pub id: String,                       // 模型标识符
    pub name: String,                     // 模型名称
    pub path: String,                     // 文件路径
    pub size_mb: i64,                     // 文件大小 (MB)
    pub loaded: bool,                     // 是否已加载
    pub architecture: String,             // 模型架构
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SystemStatus {
    pub uptime: i64,                      // 运行时间 (秒)
    pub models_loaded: u32,              // 已加载模型数
    pub total_requests: i64,             // 总请求数
    pub network_available: bool,          // 网络可用性
    pub active_sessions: Option<u32>,     // 活跃会话数
    pub rate_limits: Option<Vec<RateLimitInfo>>, // 速率限制
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthStatus {
    pub healthy: bool,                    // 是否健康
    pub message: Option<String>,          // 状态消息
    pub uptime: Option<i64>,              // 运行时间
    pub models_loaded: Option<u32>,       // 已加载模型数
    pub version: Option<String>,          // 版本
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RateLimitInfo {
    pub category: String,                 // 类别
    pub limit: i64,                       // 上限
    pub remaining: i64,                   // 剩余
    pub reset_seconds: i64,               // 重置时间 (秒)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClientConfig {
    pub host: String,                     // 主机地址
    pub port: u16,                        // 端口
    pub connect_timeout: Duration,        // 连接超时
    pub read_timeout: Duration,           // 读取超时
    pub auto_reconnect: bool,             // 自动重连
    pub max_reconnect_attempts: u32,      // 最大重连次数
    pub auth_token: Option<String>,       // 认证令牌
    pub auto_authenticate: bool,          // 自动认证
    pub tls: bool,                        // TLS 加密
}
```

### 3.6 错误类型 / Error Types

```rust
#[derive(Debug, thiserror::Error)]
pub enum AinosError {
    #[error("Connection refused: {0}")]
    ConnectionRefused(String),

    #[error("Connection lost: {0}")]
    ConnectionLost(String),

    #[error("Connection closed by peer")]
    ConnectionClosed,

    #[error("DNS resolution failed for {0}")]
    DnsResolutionFailed(String),

    #[error("Operation timed out after {0:?}")]
    Timeout(Duration),

    #[error("Authentication failed: {0}")]
    AuthFailed(String),

    #[error("Session expired")]
    SessionExpired,

    #[error("Permission denied: {0}")]
    PermissionDenied(String),

    #[error("Daemon error (code={code}): {message}")]
    DaemonError { code: i32, message: String },

    #[error("Protocol error: {0}")]
    Protocol(String),

    #[error("Unexpected response type: {0}")]
    UnexpectedResponse(String),

    #[error("Serialization error: {0}")]
    Serialization(String),

    #[error("Inference error: {0}")]
    Inference(String),

    #[error("Model not found: {0}")]
    ModelNotFound(String),

    #[error("Model not loaded: {0}")]
    ModelNotLoaded(String),

    #[error("Rate limit exceeded: {0}")]
    RateLimited(String),

    #[error("Internal error: {0}")]
    Internal(String),

    #[error("I/O error: {0}")]
    Io(String),
}
```

### 3.7 新请求构建器 / InferenceRequestBuilder

```rust
impl InferenceRequestBuilder {
    pub fn new() -> Self
    pub fn prompt(mut self, prompt: impl Into<String>) -> Self
    pub fn model(mut self, model: impl Into<String>) -> Self
    pub fn temperature(mut self, temp: f64) -> Self
    pub fn top_p(mut self, p: f64) -> Self
    pub fn top_k(mut self, k: u32) -> Self
    pub fn max_tokens(mut self, n: u32) -> Self
    pub fn stop(mut self, stop: Vec<String>) -> Self
    pub fn session_id(mut self, id: impl Into<String>) -> Self
    pub fn build(self) -> InferenceRequest
}
```

### 3.8 完整示例 / Complete Example

```rust
use ainos_sdk::prelude::*;
use std::time::Duration;

#[tokio::main]
async fn main() -> Result<(), AinosError> {
    // 创建客户端 / Create client
    let client = AinosClient::builder()
        .host("127.0.0.1")
        .port(9500)
        .auth_token("your-token")
        .connect_timeout(Duration::from_secs(10))
        .read_timeout(Duration::from_secs(120))
        .auto_reconnect(true)
        .build();

    // 连接 / Connect
    client.connect().await?;

    // 推理 / Inference
    let resp = client.infer(
        &InferenceRequest::builder()
            .prompt("What is the meaning of life?")
            .model("default")
            .temperature(0.7)
            .max_tokens(256)
            .build()
    ).await?;
    println!("Response: {}", resp.output);
    println!("Tokens: {}, Time: {}ms", resp.tokens_generated, resp.inference_ms);

    // 流式推理 / Streaming inference
    let mut stream = client.infer_stream(
        &InferenceRequest::builder()
            .prompt("Tell me a story")
            .build()
    ).await?;

    while let Some(chunk) = stream.next_chunk().await {
        match chunk {
            Ok(c) => {
                print!("{}", c.chunk);
                if c.done { break; }
            }
            Err(e) => eprintln!("Stream error: {}", e),
        }
    }

    // 收集所有块 / Collect all chunks
    let stream = client.infer_stream(
        &InferenceRequest::builder()
            .prompt("Write a poem")
            .build()
    ).await?;
    let full_response = stream.collect().await?;
    println!("Full poem: {}", full_response.output);

    // 模型管理 / Model management
    let models = client.model_list().await?;
    for m in &models {
        println!("Model: {} (loaded={})", m.name, m.loaded);
    }

    // 加载模型 / Load model
    let model = client.model_load(
        "/models/phi-3-mini-4k-instruct-q4.gguf",
        None
    ).await?;
    println!("Loaded model: {}", model.id);

    // 上下文管理 / Context management
    client.context_store("session1", "key1", b"value1", 3600).await?;
    if let Some(val) = client.context_retrieve("session1", "key1").await? {
        println!("Context: {}", String::from_utf8_lossy(&val));
    }

    // 系统状态 / System status
    let status = client.status().await?;
    println!("Uptime: {}s, Models: {}", status.uptime, status.models_loaded);

    // 断开连接 / Disconnect
    client.disconnect().await?;
    Ok(())
}
```

---

## 4. Java SDK

**源文件 / Source Files**: `bindings/java/`  
**包名 / Package**: `com.ainos.sdk`  
**构建工具 / Build**: Maven (pom.xml)

### 4.1 包结构 / Package Structure

```
com.ainos.sdk/
  AinosClient.java          # 主客户端类 / Main client
  AinosClientBuilder.java   # 客户端构建器 / Client builder
  models/
    AinosException.java         # 基础异常 / Base exception
    AinosConnectionException.java # 连接异常 / Connection exception
    AinosAuthException.java     # 认证异常 / Auth exception
    AinosTimeoutException.java  # 超时异常 / Timeout exception
    AinosInferenceException.java # 推理异常 / Inference exception
    AinosRateLimitException.java # 速率限制异常 / Rate limit exception
    InferenceRequest.java       # 推理请求 / Inference request
    InferenceResponse.java      # 推理响应 / Inference response
    InferenceChunk.java         # 推理块 / Inference chunk
    ModelInfo.java              # 模型信息 / Model info
    ModelLoadOptions.java       # 模型加载选项 / Model load options
    SystemStatus.java           # 系统状态 / System status
    HealthStatus.java           # 健康状态 / Health status
    RateLimitStatus.java        # 速率限制状态 / Rate limit status
  transport/
    TcpTransport.java           # TCP 传输 / TCP transport
    TcpTransportImpl.java       # TCP 传输实现 / TCP transport impl
    TransportFactory.java       # 传输工厂 / Transport factory
    ConnectionPool.java         # 连接池 / Connection pool
    JsonCodec.java              # JSON 编解码 / JSON codec
  stream/
    InferenceStream.java        # 推理流 / Inference stream
    StreamReader.java           # 流读取器 / Stream reader
    StreamSubscriber.java       # 流订阅者 / Stream subscriber
```

### 4.2 AinosClientBuilder / AinosClientBuilder

```java
public class AinosClientBuilder {
    // 默认常量 / Default constants
    public static final String DEFAULT_HOST = "127.0.0.1";
    public static final int DEFAULT_PORT = 9500;
    public static final int DEFAULT_CONNECT_TIMEOUT_MS = 5000;
    public static final int DEFAULT_READ_TIMEOUT_MS = 120000;
    public static final boolean DEFAULT_AUTO_RECONNECT = true;
    public static final int DEFAULT_RECONNECT_DELAY_MS = 1000;
    public static final int DEFAULT_MAX_RECONNECT_ATTEMPTS = 3;
    public static final boolean DEFAULT_AUTO_AUTHENTICATE = true;
    public static final boolean DEFAULT_USE_CONNECTION_POOL = false;
    public static final int DEFAULT_POOL_SIZE = 4;

    // 构建器方法 / Builder methods
    public AinosClientBuilder host(String host)
    public AinosClientBuilder port(int port)
    public AinosClientBuilder address(String host, int port)
    public AinosClientBuilder connectTimeoutMs(int connectTimeoutMs)
    public AinosClientBuilder connectTimeout(long timeout, TimeUnit unit)
    public AinosClientBuilder readTimeoutMs(int readTimeoutMs)
    public AinosClientBuilder readTimeout(long timeout, TimeUnit unit)
    public AinosClientBuilder autoReconnect(boolean autoReconnect)
    public AinosClientBuilder reconnectDelayMs(int reconnectDelayMs)
    public AinosClientBuilder maxReconnectAttempts(int maxReconnectAttempts)
    public AinosClientBuilder authToken(String authToken)
    public AinosClientBuilder autoAuthenticate(boolean autoAuthenticate)
    public AinosClientBuilder useConnectionPool(boolean useConnectionPool)
    public AinosClientBuilder poolSize(int poolSize)

    // 构建方法 / Build methods
    public AinosClient build()
    public AinosClient connect() // 构建并连接 / Build and connect
    public AinosClientBuilder copy()
}
```

### 4.3 AinosClient 方法 / AinosClient Methods

```java
public class AinosClient implements Closeable {
    // 创建构建器 / Create builder
    public static AinosClientBuilder builder()

    // 连接生命周期 / Connection lifecycle
    public void connect() throws AinosConnectionException, AinosTimeoutException, AinosAuthException
    public void disconnect()
    public void close()  // 关闭并释放资源 / Close and release resources
    public boolean isConnected()
    public boolean isAuthenticated()
    public String getSessionToken()
    public List<String> getPermissions()

    // 认证 / Authentication
    public Map<String, Object> authenticate(String token)
        throws AinosAuthException, AinosConnectionException, AinosTimeoutException

    // 推理 / Inference
    public InferenceResponse infer(InferenceRequest request)
        throws AinosConnectionException, AinosTimeoutException, AinosInferenceException
    public InferenceStream inferStream(InferenceRequest request)
        throws AinosConnectionException, AinosTimeoutException
    public List<InferenceResponse> batchInfer(List<InferenceRequest> requests)
        throws AinosConnectionException, AinosTimeoutException, AinosInferenceException

    // 模型管理 / Model management
    public List<ModelInfo> modelList()
        throws AinosConnectionException, AinosTimeoutException
    public ModelInfo modelLoad(String path, ModelLoadOptions opts)
        throws AinosConnectionException, AinosTimeoutException
    public ModelInfo modelLoad(String path)
        throws AinosConnectionException, AinosTimeoutException
    public void modelUnload(String modelId)
        throws AinosConnectionException, AinosTimeoutException

    // 上下文管理 / Context management
    public void contextStore(String sessionId, String key, byte[] value, long ttl)
        throws AinosConnectionException, AinosTimeoutException
    public byte[] contextRetrieve(String sessionId, String key)
        throws AinosConnectionException, AinosTimeoutException

    // 系统状态 / System status
    public SystemStatus status()
        throws AinosConnectionException, AinosTimeoutException
    public HealthStatus health()
    public RateLimitStatus rateLimitStatus()
        throws AinosConnectionException, AinosTimeoutException
}
```

### 4.4 数据模型 / Data Models

```java
// 推理请求 / Inference request
public class InferenceRequest {
    public static InferenceRequest of(String prompt)
    // Getters: getModel(), getPrompt(), getTemperature(), getMaxTokens(), getSessionId()
}

// 推理响应 / Inference response
public class InferenceResponse {
    public String getOutput()
    public int getTokensGenerated()
    public long getInferenceMs()
    public String getSource()
}

// 推理块 / Inference chunk
public class InferenceChunk {
    public String getChunk()
    public boolean isDone()
    public int getIndex()
}

// 模型信息 / Model info
public class ModelInfo {
    public String getId()
    public String getName()
    public String getPath()
    public long getSizeMb()
    public boolean isLoaded()
    public String getArchitecture()
}

// 模型加载选项 / Model load options
public class ModelLoadOptions {
    public Optional<String> getArchitecture()
    public Optional<Integer> getGpuLayerCount()
    public Optional<Integer> getContextSize()
    public Optional<Boolean> getUseMmap()
    public Optional<Integer> getThreads()
    public Optional<String> getEngineType()
}

// 系统状态 / System status
public class SystemStatus {
    public long getUptime()
    public int getModelsLoaded()
    public long getTotalRequests()
    public boolean isNetworkAvailable()
    public int getActiveSessions()
    public List<RateLimitInfo> getRateLimits()
}

// 健康状态 / Health status
public class HealthStatus {
    public static HealthStatus unhealthy(String message)
    public boolean isHealthy()
    public String getMessage()
}

// 速率限制状态 / Rate limit status
public class RateLimitStatus {
    public List<RateLimitEntry> getEntries()
    public static class RateLimitEntry {
        public String getCategory()
        public long getLimit()
        public long getRemaining()
        public long getResetSeconds()
    }
}
```

### 4.5 异常层次 / Exception Hierarchy

```
AinosException (base)
  +-- AinosConnectionException
  +-- AinosAuthException
  +-- AinosTimeoutException
  +-- AinosInferenceException
  +-- AinosRateLimitException
```

### 4.6 完整示例 / Complete Example

```java
import com.ainos.sdk.AinosClient;
import com.ainos.sdk.models.*;

public class Example {
    public static void main(String[] args) throws Exception {
        // 创建并连接客户端 / Create and connect client
        try (AinosClient client = AinosClient.builder()
                .host("127.0.0.1")
                .port(9500)
                .authToken("your-token")
                .connectTimeout(10, java.util.concurrent.TimeUnit.SECONDS)
                .readTimeout(2, java.util.concurrent.TimeUnit.MINUTES)
                .autoReconnect(true)
                .build()) {

            client.connect();

            // 推理 / Inference
            InferenceResponse resp = client.infer(
                InferenceRequest.of("What is the meaning of life?"));
            System.out.println("Response: " + resp.getOutput());
            System.out.println("Tokens: " + resp.getTokensGenerated());

            // 流式推理 / Streaming inference
            InferenceStream stream = client.inferStream(
                InferenceRequest.of("Tell me a story"));
            stream.subscribe(chunk -> {
                System.out.print(chunk.getChunk());
                if (chunk.isDone()) {
                    System.out.println("\n[Stream complete]");
                }
            });

            // 模型管理 / Model management
            for (ModelInfo model : client.modelList()) {
                System.out.println("Model: " + model.getName()
                    + " (loaded=" + model.isLoaded() + ")");
            }

            // 加载模型 / Load model
            ModelInfo loaded = client.modelLoad("/models/phi-3-mini-q4.gguf");
            System.out.println("Loaded: " + loaded.getId());

            // 系统状态 / System status
            SystemStatus status = client.status();
            System.out.println("Uptime: " + status.getUptime() + "s");
            System.out.println("Models: " + status.getModelsLoaded());
        }
    }
}
```

---

## 5. C# SDK

**源文件 / Source Files**: `bindings/csharp/AinosSdk/`  
**命名空间 / Namespace**: `AinosSdk`  
**框架 / Framework**: .NET

### 5.1 命名空间结构 / Namespace Structure

```
AinosSdk/
  AinosClient.cs                    # 主客户端类 / Main client
  Configuration/
    AinosClientOptions.cs           # 客户端选项 / Client options
    AinosClientBuilder.cs           # 客户端构建器 / Client builder
  Models/
    AinosException.cs               # 基础异常 / Base exception
    AinosConnectionException.cs     # 连接异常 / Connection exception
    AinosAuthException.cs           # 认证异常 / Auth exception
    AinosRateLimitException.cs      # 速率限制异常 / Rate limit exception
    InferenceRequest.cs             # 推理请求 / Inference request
    InferenceResponse.cs            # 推理响应 / Inference response
    InferenceChunk.cs               # 推理块 / Inference chunk
    ModelInfo.cs                    # 模型信息 / Model info
    ModelLoadOptions.cs             # 模型加载选项 / Model load options
    SystemStatus.cs                 # 系统状态 / System status
    HealthStatus.cs                 # 健康状态 / Health status
    RateLimitStatus.cs              # 速率限制状态 / Rate limit status
  Transport/
    TcpTransport.cs                 # TCP 传输 / TCP transport
    ConnectionPool.cs               # 连接池 / Connection pool
    JsonCodec.cs                    # JSON 编解码 / JSON codec
  Streaming/
    InferenceStream.cs              # 推理流 / Inference stream
    StreamReader.cs                 # 流读取器 / Stream reader
```

### 5.2 AinosClientOptions / AinosClientOptions

```csharp
public class AinosClientOptions
{
    public string Host { get; set; } = "127.0.0.1";
    public int Port { get; set; } = 9500;
    public TimeSpan ConnectTimeout { get; set; } = TimeSpan.FromSeconds(5);
    public TimeSpan ReadTimeout { get; set; } = TimeSpan.FromSeconds(120);
    public TimeSpan SendTimeout { get; set; } = TimeSpan.FromSeconds(10);
    public bool AutoReconnect { get; set; } = true;
    public TimeSpan ReconnectDelay { get; set; } = TimeSpan.FromSeconds(1);
    public int MaxRetries { get; set; } = 3;
    public string? AuthToken { get; set; }
    public bool AutoAuthenticate { get; set; } = true;
    public bool UseConnectionPool { get; set; } = false;
    public int MaxPoolSize { get; set; } = 4;
    public string DefaultModel { get; set; } = "default";
    public double? DefaultTemperature { get; set; }
    public int? DefaultMaxTokens { get; set; }
    public AinosClientOptions Clone();
}
```

### 5.3 AinosClient 方法 / AinosClient Methods

```csharp
public class AinosClient : IAsyncDisposable
{
    // 属性 / Properties
    public bool Connected { get; }
    public bool Authenticated { get; }
    public string? SessionToken { get; }
    public IReadOnlyList<string> Permissions { get; }
    public AinosClientOptions Options { get; }

    // 连接生命周期 / Connection lifecycle
    public AinosClient(AinosClientOptions options, ILogger<AinosClient>? logger = null)
    public async Task ConnectAsync(CancellationToken ct = default)
    public async Task DisconnectAsync()

    // 认证 / Authentication
    public async Task<(bool Success, string? SessionToken, List<string> Permissions, long SessionTtlSeconds)>
        AuthenticateAsync(string token, CancellationToken ct = default)

    // 推理 / Inference
    public async Task<InferenceResponse> InferAsync(InferenceRequest request, CancellationToken ct = default)
    public async IAsyncEnumerable<InferenceChunk> InferStreamAsync(InferenceRequest request,
        [EnumeratorCancellation] CancellationToken ct = default)
    public async Task<List<InferenceResponse>> BatchInferAsync(List<InferenceRequest> requests,
        CancellationToken ct = default)

    // 便捷方法 / Convenience methods
    public async Task<string> InferSimpleAsync(string prompt, string? model = null, CancellationToken ct = default)
    public async Task<string> InferStreamSimpleAsync(string prompt, string? model = null, CancellationToken ct = default)

    // 模型管理 / Model management
    public async Task<List<ModelInfo>> GetModelListAsync(CancellationToken ct = default)
    public async Task<ModelInfo> LoadModelAsync(string path, ModelLoadOptions? options = null, CancellationToken ct = default)
    public async Task UnloadModelAsync(string id, CancellationToken ct = default)

    // 上下文管理 / Context management
    public async Task ContextStoreAsync(string sessionId, string key, byte[] value, long ttl = 0, CancellationToken ct = default)
    public async Task ContextStoreStringAsync(string sessionId, string key, string value, long ttl = 0, CancellationToken ct = default)
    public async Task<byte[]?> ContextRetrieveAsync(string sessionId, string key, CancellationToken ct = default)
    public async Task<string?> ContextRetrieveStringAsync(string sessionId, string key, CancellationToken ct = default)

    // 系统状态 / System status
    public async Task<SystemStatus> GetStatusAsync(CancellationToken ct = default)
    public async Task<HealthStatus> GetHealthAsync(CancellationToken ct = default)
    public async Task<RateLimitStatus> GetRateLimitStatusAsync(CancellationToken ct = default)
}
```

### 5.4 数据模型 / Data Models

```csharp
public record InferenceRequest(
    string Model, string Prompt, double? Temperature, int? MaxTokens, string? SessionId);

public record InferenceResponse(
    string Output, int TokensGenerated, long InferenceMs, string Source);

public record InferenceChunk(string Chunk, bool Done, string Model);

public record ModelInfo(
    string Id, string Name, string Path, long SizeMb, bool Loaded, string Architecture);

public record ModelLoadOptions(
    bool? SkipIfLoaded, string? Architecture, int? GpuLayers, int? ContextSize);

public record SystemStatus(
    long Uptime, int ModelsLoaded, long TotalRequests, bool NetworkAvailable);

public record HealthStatus(bool Healthy, string Message, long Uptime = 0, int ModelsLoaded = 0);

public record RateLimitStatus(List<RateLimitEntry> Limits);
```

### 5.5 异常类型 / Exception Types

```csharp
public class AinosException : Exception       // 基础异常
public class AinosAuthException : AinosException    // 认证异常
public class AinosConnectionException : AinosException // 连接异常
public class AinosRateLimitException : AinosException // 速率限制
```

### 5.6 完整示例 / Complete Example

```csharp
using AinosSdk;
using AinosSdk.Configuration;
using AinosSdk.Models;

var options = new AinosClientOptions
{
    Host = "127.0.0.1",
    Port = 9500,
    AuthToken = "your-token",
    ConnectTimeout = TimeSpan.FromSeconds(10),
    ReadTimeout = TimeSpan.FromMinutes(2),
    AutoReconnect = true,
};

await using var client = new AinosClient(options);
await client.ConnectAsync();

// 推理 / Inference
var response = await client.InferAsync(new InferenceRequest(
    Model: "default",
    Prompt: "What is the meaning of life?",
    Temperature: 0.7,
    MaxTokens: 256,
    SessionId: null
));
Console.WriteLine($"Response: {response.Output}");
Console.WriteLine($"Tokens: {response.TokensGenerated}, Time: {response.InferenceMs}ms");

// 流式推理 / Streaming inference
await foreach (var chunk in client.InferStreamAsync(
    new InferenceRequest("default", "Tell me a story", null, null, null)))
{
    Console.Write(chunk.Chunk);
    if (chunk.Done) break;
}

// 模型管理 / Model management
var models = await client.GetModelListAsync();
foreach (var model in models)
{
    Console.WriteLine($"Model: {model.Name} (loaded={model.Loaded})");
}

// 加载模型 / Load model
var loaded = await client.LoadModelAsync("/models/phi-3-mini-q4.gguf");
Console.WriteLine($"Loaded: {loaded.Id}");

// 上下文管理 / Context management
await client.ContextStoreStringAsync("session1", "key1", "value1", ttl: 3600);
var val = await client.ContextRetrieveStringAsync("session1", "key1");
Console.WriteLine($"Context: {val}");

// 系统状态 / System status
var status = await client.GetStatusAsync();
Console.WriteLine($"Uptime: {status.Uptime}s, Models: {status.ModelsLoaded}");
```

---

## 6. Node.js / TypeScript SDK

**源文件 / Source Files**: `bindings/node/`  
**包名 / Package**: `ainos-sdk`  
**语言 / Language**: TypeScript

### 6.1 模块结构 / Module Structure

```
src/
  index.ts      # 公共导出 / Public exports
  client.ts     # AinosClient 主类 / Main client
  types.ts      # 类型定义 / Type definitions
  errors.ts     # 错误类型 / Error types
  auth.ts       # 认证管理 / Authentication
  transport.ts  # TCP 传输层 / TCP transport
  stream.ts     # 流式推理 / Streaming inference
  utils.ts      # 工具函数 / Utilities
```

### 6.2 类型定义 / Type Definitions

```typescript
/** 客户端选项 / Client options */
interface ClientOptions {
  host?: string;                    // 主机地址 (默认 "127.0.0.1")
  port?: number;                    // 端口 (默认 9500)
  connectTimeout?: number;          // 连接超时 (毫秒)
  readTimeout?: number;             // 读取超时 (毫秒)
  autoReconnect?: boolean;          // 自动重连 (默认 true)
  reconnectDelay?: number;          // 重连延迟 (毫秒)
  maxReconnectAttempts?: number;    // 最大重连次数 (默认 5)
  authToken?: string;               // 认证令牌
  autoAuthenticate?: boolean;       // 自动认证 (默认 true)
}

/** 推理请求 / Inference request */
interface InferenceRequest {
  prompt: string;                   // 输入提示
  model?: string;                   // 模型标识符 (默认 "default")
  temperature?: number;             // 采样温度 (0.0-2.0)
  maxTokens?: number;              // 最大 token 数
  sessionId?: string;               // 会话 ID
}

/** 推理响应 / Inference response */
interface InferenceResponse {
  output: string;                   // 生成的文本
  tokensGenerated: number;         // 生成 token 数
  inferenceMs: number;             // 推理耗时 (毫秒)
  source: string;                   // "local" 或 "cloud"
}

/** 推理块 / Inference chunk */
interface InferenceChunk {
  chunk: string;                    // 文本片段
  done: boolean;                    // 是否最后一块
}

/** 模型信息 / Model info */
interface ModelInfo {
  id: string;                       // 模型标识符
  name: string;                     // 模型名称
  path: string;                     // 文件路径
  sizeMb: number;                   // 文件大小 (MB)
  loaded: boolean;                  // 是否已加载
  architecture: string;             // 模型架构
}

/** 模型加载选项 / Model load options */
interface ModelLoadOptions {
  modelId?: string;                 // 模型 ID 覆盖
  architecture?: string;            // 架构提示
}

/** 模型加载响应 / Model load response */
interface ModelLoadResponse {
  modelId: string;                  // 模型标识符
  status: string;                   // 状态 ("loaded", "already_loaded", "error")
  message: string;                  // 消息
  modelInfo?: ModelInfo;            // 完整模型信息
}

/** 系统状态 / System status */
interface SystemStatus {
  uptime: number;                   // 运行时间 (秒)
  modelsLoaded: number;            // 已加载模型数
  totalRequests: number;           // 总请求数
  networkAvailable: boolean;        // 网络可用性
  activeSessions?: number;          // 活跃会话数
  rateLimits?: RateLimitInfo[];     // 速率限制
}

/** 健康状态 / Health status */
interface HealthStatus {
  ok: boolean;                      // 是否健康
  version?: string;                 // 版本
  message?: string;                 // 消息
  uptime?: number;                  // 运行时间
}

/** 速率限制信息 / Rate limit info */
interface RateLimitInfo {
  category: string;                 // 类别
  limit: number;                    // 上限
  remaining: number;                // 剩余
  resetSeconds: number;             // 重置时间 (秒)
}

/** 认证响应 / Auth response */
interface AuthResponse {
  success: boolean;                 // 是否成功
  sessionToken?: string;            // 会话令牌
  message: string;                  // 消息
  permissions: string[];            // 权限列表
  sessionTtlSeconds: number;        // 会话 TTL (秒)
}
```

### 6.3 AinosClient 类 / AinosClient Class

```typescript
class AinosClient extends EventEmitter {
  // 属性 / Properties
  readonly connected: boolean
  readonly authenticated: boolean
  readonly sessionToken: string | null
  readonly permissions: string[]
  readonly sessionTtl: number
  readonly host: string
  readonly port: number

  // 构造函数 / Constructor
  constructor(options?: ClientOptions)

  // 事件 / Events
  // 'connect'          - TCP 连接建立
  // 'disconnect'       - TCP 连接关闭
  // 'reconnect'        - 重连尝试
  // 'authenticated'    - 认证成功
  // 'authError'        - 认证失败
  // 'error'            - 连接级错误
  // 'rateLimited'      - 速率限制

  // 生命周期 / Lifecycle
  async connect(): Promise<void>
  disconnect(): void
  async authenticate(token?: string): Promise<AuthResponse>

  // 推理 / Inference
  async infer(req: InferenceRequest): Promise<InferenceResponse>
  inferStream(req: InferenceRequest): InferenceStream
  async inferText(req: InferenceRequest): Promise<string>
  async batchInfer(reqs: InferenceRequest[]): Promise<InferenceResponse[]>

  // 模型管理 / Model management
  async modelList(): Promise<ModelInfo[]>
  async modelLoad(path: string, opts?: ModelLoadOptions): Promise<ModelLoadResponse>
  async modelUnload(id: string): Promise<void>

  // 上下文管理 / Context management
  async contextStore(sessionId: string, key: string, value: string | Buffer, ttl?: number): Promise<void>
  async contextRetrieve(sessionId: string, key: string): Promise<Buffer | null>

  // 系统状态 / System status
  async status(): Promise<SystemStatus>
  async health(): Promise<HealthStatus>
  async rateLimitStatus(): Promise<RateLimitStatus>
}

// 工厂函数 / Factory function
async function createClient(options?: ClientOptions): Promise<AinosClient>
```

### 6.4 错误类型 / Error Types

```typescript
class AinosError extends Error          // 基础错误
class ConnectionError extends AinosError  // 连接错误
class AuthError extends AinosError        // 认证错误
class RateLimitError extends AinosError   // 速率限制
class InferenceError extends AinosError   // 推理错误
class TimeoutError extends AinosError     // 超时错误
class DaemonError extends AinosError      // 守护进程错误
```

### 6.5 完整示例 / Complete Example

```typescript
import { AinosClient, createClient } from 'ainos-sdk';

// 方式一: 使用工厂函数 / Using factory function
async function example1() {
  const client = await createClient({
    host: '127.0.0.1',
    port: 9500,
    authToken: 'your-token',
  });

  const resp = await client.infer({
    prompt: 'What is the meaning of life?',
    temperature: 0.7,
    maxTokens: 256,
  });
  console.log(`Response: ${resp.output}`);

  await client.disconnect();
}

// 方式二: 手动管理 / Manual management
async function example2() {
  const client = new AinosClient({
    authToken: 'your-token',
    autoReconnect: true,
  });

  client.on('connect', () => console.log('Connected'));
  client.on('disconnect', () => console.log('Disconnected'));
  client.on('authenticated', (token) => console.log('Auth:', token.slice(0, 8)));

  await client.connect();

  // 流式推理 / Streaming inference
  const stream = client.inferStream({ prompt: 'Tell me a story' });
  stream.on('data', (chunk: string) => process.stdout.write(chunk));
  stream.on('end', () => console.log('\n[Stream complete]'));
  stream.on('error', (err) => console.error('Stream error:', err));

  // 模型列表 / Model list
  const models = await client.modelList();
  models.forEach(m => console.log(`${m.name} (loaded=${m.loaded})`));

  // 加载模型 / Load model
  const result = await client.modelLoad('/models/phi-3-mini-q4.gguf');
  console.log(`Loaded: ${result.modelId} (${result.status})`);

  // 上下文管理 / Context management
  await client.contextStore('session1', 'key1', 'value1', 3600);
  const ctx = await client.contextRetrieve('session1', 'key1');
  console.log(`Context: ${ctx?.toString()}`);

  // 系统状态 / System status
  const status = await client.status();
  console.log(`Uptime: ${status.uptime}s, Models: ${status.modelsLoaded}`);

  await client.disconnect();
}

// 批量推理 / Batch inference
async function batchExample() {
  const client = await createClient();
  const prompts = [
    'Hello!',
    'How are you?',
    'What is AI?',
  ];
  const results = await Promise.all(
    prompts.map(p => client.infer({ prompt: p }))
  );
  results.forEach((r, i) => console.log(`[${i}] ${r.output}`));
  await client.disconnect();
}
```

---

## 7. C SDK (libainos)

**源文件 / Source Files**: `userland/sdk/`  
**头文件 / Header**: `ainos.h`  
**实现 / Implementation**: `libainos.c`  
**版本 / Version**: 1.0.0

### 7.1 头文件 / Header

```c
// Ainos OS - AI 应用 SDK 头文件
// 支持 Windows 和 Linux 双平台
#ifndef AINOS_H
#define AINOS_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* 基础类型与错误码 / Basic types and error codes */
#define AINOS_OK                  0
#define AINOS_ERR_INVALID_PARAM  -1
#define AINOS_ERR_NOT_INIT       -2
#define AINOS_ERR_MODEL_NOT_FOUND -3
#define AINOS_ERR_OUT_OF_MEMORY  -4
#define AINOS_ERR_TIMEOUT        -5
#define AINOS_ERR_CONNECT        -6
#define AINOS_ERR_INTERNAL       -99

#define AINOS_SDK_VERSION "1.0.0"

/* 类型定义 / Type definitions */

/* Opaque 上下文 / Opaque context */
typedef struct ainos_ctx ainos_ctx;

/* 推理选项 / Inference options */
typedef struct {
    float temperature;           /* 温度 (默认 0.7) */
    float top_p;                 /* Top-P (默认 0.9) */
    int max_tokens;              /* 最大 token 数 (默认 512) */
    int num_threads;             /* 推理线程数 (默认 4) */
    const char* session_id;      /* 会话 ID (可选) */
} ainos_infer_opts;

#define AINOS_INFER_OPTS_DEFAULT {0.7f, 0.9f, 512, 4, NULL}

/* 推理响应 / Inference response */
typedef struct {
    char* output;                /* 输出文本 */
    int tokens_generated;        /* 生成 token 数 */
    long long inference_ms;      /* 推理耗时 (毫秒) */
    char* source;                /* 来源 ("local" 或 "cloud") */
    int error_code;              /* 错误码 */
    char* error_message;         /* 错误消息 */
} ainos_resp;

/* 系统信息 / System info */
typedef struct {
    uint32_t models_loaded;      /* 已加载模型数 */
    uint32_t tasks_pending;      /* 排队任务数 */
    uint32_t tasks_running;      /* 运行中任务数 */
    uint64_t total_inferences;   /* 总推理次数 */
    uint64_t total_tokens;       /* 总生成 token 数 */
    uint64_t uptime_ms;          /* 运行时间 (毫秒) */
    int network_available;       /* 网络是否可用 */
    int accelerator;             /* 加速器类型 */
    char version[64];            /* 版本字符串 */
} ainos_sys_info;
```

### 7.2 核心 API / Core API

```c
/* 初始化 SDK / Initialize SDK
 * server_addr: "host:port" (如 "127.0.0.1:9500") 或 Unix socket 路径
 * 返回: ainos_ctx 指针，失败返回 NULL */
ainos_ctx* ainos_init(const char* server_addr);

/* 连接 AI 守护进程 / Connect to AI daemon
 * 返回: AINOS_OK 或错误码 */
int ainos_connect(ainos_ctx* ctx);

/* 执行推理请求 / Execute inference request
 * 返回: ainos_resp 指针，使用 ainos_resp_free 释放 */
ainos_resp* ainos_infer(ainos_ctx* ctx, const char* model,
                        const char* prompt, ainos_infer_opts* opts);

/* 获取系统状态 / Get system status */
ainos_resp* ainos_get_info(ainos_ctx* ctx);

/* 释放响应 / Free response */
void ainos_resp_free(ainos_resp* resp);

/* 断开连接并销毁上下文 / Disconnect and destroy context */
void ainos_destroy(ainos_ctx* ctx);
```

### 7.3 高级 API / Advanced API

```c
/* 获取嵌入向量 / Get embedding vector */
ainos_resp* ainos_embed(ainos_ctx* ctx, const char* text);

/* 语义搜索 / Semantic search */
ainos_resp* ainos_search(ainos_ctx* ctx, const char* query, int max_results);

/* 上下文管理 / Context management */
ainos_resp* ainos_ctx_store(ainos_ctx* ctx, const char* key, const char* value);
ainos_resp* ainos_ctx_get(ainos_ctx* ctx, const char* key);

/* 模型管理 / Model management */
int ainos_model_load(ainos_ctx* ctx, const char* path);
int ainos_model_unload(ainos_ctx* ctx, const char* model_id);
```

### 7.4 内部实现 / Internal Implementation

C SDK 使用 NDJSON 协议通过 TCP 与守护进程通信。核心内部函数：

```c
/* 内部函数 / Internal functions */
static int tcp_connect(ainos_ctx* ctx);
static int send_request(ainos_ctx* ctx, const char* json_request);
static char* recv_response(ainos_ctx* ctx);
static char* json_escape(const char* str);
static ainos_resp* parse_response(const char* json);
```

**上下文结构体 / Context Structure**:

```c
struct ainos_ctx {
    char server_addr[256];          /* 服务器地址 */
    int port;                       /* 端口 */
    socket_t sock;                  /* socket 描述符 */
    int connected;                  /* 是否已连接 */
    int use_unix_socket;            /* 0=TCP, 1=Unix Domain Socket */
};
```

### 7.5 编译 / Build

```bash
# Windows (MinGW or Cygwin)
gcc -shared -o libainos.dll libainos.c -lws2_32
gcc -c -o libainos.o libainos.c -lws2_32

# Linux
gcc -shared -fPIC -o libainos.so libainos.c -lpthread

# 使用 / Use
gcc myapp.c -lainos -o myapp
```

### 7.6 完整示例 / Complete Example

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ainos.h"

int main() {
    ainos_ctx* ctx;
    ainos_resp* resp;
    ainos_infer_opts opts = AINOS_INFER_OPTS_DEFAULT;
    int ret;

    /* 初始化 SDK / Initialize SDK */
    ctx = ainos_init("127.0.0.1:9500");
    if (!ctx) {
        fprintf(stderr, "Failed to initialize Ainos SDK\n");
        return 1;
    }

    /* 连接守护进程 / Connect to daemon */
    ret = ainos_connect(ctx);
    if (ret != AINOS_OK) {
        fprintf(stderr, "Failed to connect: %d\n", ret);
        ainos_destroy(ctx);
        return 1;
    }

    printf("Connected to Ainos daemon\n");

    /* 获取系统状态 / Get system status */
    resp = ainos_get_info(ctx);
    if (resp && resp->error_code == 0) {
        printf("Response: %s\n", resp->output);
    }
    ainos_resp_free(resp);

    /* 执行推理 / Run inference */
    opts.temperature = 0.7f;
    opts.max_tokens = 256;
    opts.num_threads = 4;

    resp = ainos_infer(ctx, "default",
                       "What is the meaning of life?", &opts);
    if (resp) {
        if (resp->error_code == 0) {
            printf("Output: %s\n", resp->output);
            printf("Tokens: %d, Time: %lldms\n",
                   resp->tokens_generated, resp->inference_ms);
        } else {
            fprintf(stderr, "Error: %s\n",
                    resp->error_message ? resp->error_message : "Unknown");
        }
        ainos_resp_free(resp);
    }

    /* 上下文管理 / Context management */
    resp = ainos_ctx_store(ctx, "my_key", "my_value");
    ainos_resp_free(resp);

    resp = ainos_ctx_get(ctx, "my_key");
    if (resp && resp->output) {
        printf("Context: %s\n", resp->output);
    }
    ainos_resp_free(resp);

    /* 模型管理 / Model management */
    ret = ainos_model_load(ctx, "/models/phi-3-mini-q4.gguf");
    if (ret == AINOS_OK) {
        printf("Model loaded successfully\n");
    }

    /* 清理 / Cleanup */
    ainos_destroy(ctx);
    printf("Disconnected from Ainos daemon\n");
    return 0;
}
```

### 7.7 错误码参考 / Error Code Reference

| 宏 / Macro | 值 / Value | 描述 / Description |
|---|---|---|
| `AINOS_OK` | 0 | 成功 / Success |
| `AINOS_ERR_INVALID_PARAM` | -1 | 参数无效 / Invalid parameter |
| `AINOS_ERR_NOT_INIT` | -2 | SDK 未初始化 / SDK not initialized |
| `AINOS_ERR_MODEL_NOT_FOUND` | -3 | 模型未找到 / Model not found |
| `AINOS_ERR_OUT_OF_MEMORY` | -4 | 内存不足 / Out of memory |
| `AINOS_ERR_TIMEOUT` | -5 | 操作超时 / Timeout |
| `AINOS_ERR_CONNECT` | -6 | 连接失败 / Connection failed |
| `AINOS_ERR_INTERNAL` | -99 | 内部错误 / Internal error |

---

## 8. Common Patterns / 通用模式

### 8.1 连接管理 / Connection Management

所有语言 SDK 遵循相同的连接生命周期模式：

```
创建客户端 -> 连接 -> 认证 -> 操作 -> 断开
```

**最佳实践 / Best Practices**:

1. 始终使用 try/finally 或 using 确保断开连接 / Always ensure disconnect
2. 生产环境启用自动重连 / Enable auto-reconnect in production
3. 设置合理的超时时间 / Set reasonable timeouts
4. 使用连接池处理高并发 / Use connection pools for high concurrency

```python
# Python: 上下文管理器自动管理连接 / Context manager auto-manages connection
with AinosClient(auth_token="token") as client:
    client.infer("Hello")

# Go: defer 确保断开 / defer ensures disconnect
client := ainos.NewClient()
defer client.Disconnect()
client.Connect()

// C#: IAsyncDisposable 模式 / IAsyncDisposable pattern
await using var client = new AinosClient(options);
await client.ConnectAsync();

// Java: try-with-resources / try-with-resources
try (AinosClient client = AinosClient.builder().build()) {
    client.connect();
}
```

### 8.2 认证 / Authentication

所有 SDK 支持两种认证方式：

1. **自动认证**: 在构造函数中提供 `auth_token`，连接后自动认证
2. **手动认证**: 连接后调用 `authenticate(token)` 方法

```python
# 自动认证 / Auto authentication
client = AinosClient(auth_token="your-token")
client.connect()  # 自动认证 / Auto-authenticates

# 手动认证 / Manual authentication
client = AinosClient()
client.connect()
client.authenticate("your-token")
```

### 8.3 错误处理与重试 / Error Handling and Retries

**Go SDK 重试策略 / Go SDK Retry Strategy**:

```go
// 默认重试配置 / Default retry configuration
config := ainos.DefaultRetryConfig()
// MaxRetries: 3, InitialBackoff: 100ms, MaxBackoff: 10s, BackoffMultiplier: 2.0

// 使用自定义重试配置 / Custom retry config
client := ainos.NewClient(
    ainos.WithRetryConfig(ainos.RetryConfig{
        MaxRetries:        5,
        InitialBackoff:    500 * time.Millisecond,
        MaxBackoff:        30 * time.Second,
        BackoffMultiplier: 1.5,
    }),
)
```

**错误分类矩阵 / Error Classification Matrix**:

| 错误类型 / Error Type | 是否可重试 / Retryable | 处理方式 / Handling |
|---|---|---|
| 连接错误 / ConnectionError | 是 | 等待后重连 |
| 超时错误 / TimeoutError | 是 | 等待后重试 |
| 速率限制 / RateLimitError | 是 (等待后) | 等待 Retry-After 时间 |
| 认证错误 / AuthError | 否 | 重新获取令牌 |
| 推理错误 / InferenceError | 否 | 检查输入参数 |
| 协议错误 / ProtocolError | 否 | 检查 SDK 版本 |

### 8.4 流式推理 / Streaming Consumption

```python
# Python: 当前为同步模式，流式支持开发中
# Currently synchronous, streaming support in development

// Go: 使用 channel 消费
chunks, err := client.InferStream(ctx, &ainos.InferenceRequest{
    Prompt: "Tell me a story",
})
for chunk := range chunks {
    fmt.Print(chunk.Text)
}

// Rust: 使用 Stream trait
let mut stream = client.infer_stream(&req).await?;
while let Some(chunk) = stream.next_chunk().await {
    print!("{}", chunk?.chunk);
}

// C#: 使用 async foreach
await foreach (var chunk in client.InferStreamAsync(request)) {
    Console.Write(chunk.Chunk);
}

// Node.js: 使用 EventEmitter
const stream = client.inferStream({ prompt: "Hello" });
stream.on('data', (chunk) => process.stdout.write(chunk));
stream.on('end', () => console.log('Done'));
```

### 8.5 模型生命周期 / Model Lifecycle

```
加载模型 -> 列出模型 -> 推理 -> 卸载模型
```

**模型缓存策略 / Model Caching Strategy**:

- 模型加载后，守护进程会缓存模型 ID
- 重复加载同名模型返回已有 ID（幂等操作）
- 模型列表结果在 Node.js SDK 中缓存 5 秒
- 加载/卸载操作后自动刷新缓存

### 8.6 上下文管理 / Context Management

上下文存储支持 TTL（生存时间）：

```python
# 存储带 TTL 的上下文 / Store context with TTL
client.context_store("key", "value")  # 无过期 / No expiry

# Go: 指定 TTL (秒) / Specify TTL in seconds
client.ContextStore("session1", "key1", []byte("value1"), 3600)

# 检索上下文 / Retrieve context
value = client.context_retrieve("key")
```

### 8.7 环境变量 / Environment Variables

建议通过环境变量配置 SDK 连接参数：

```bash
# 通用配置 / Common configuration
export AINOS_HOST="127.0.0.1"
export AINOS_PORT="9500"
export AINOS_AUTH_TOKEN="your-token"
export AINOS_CONNECT_TIMEOUT="10"
export AINOS_READ_TIMEOUT="120"
export AINOS_AUTO_RECONNECT="true"
```

### 8.8 NDJSON 协议格式 / NDJSON Wire Format

所有 SDK 使用相同的 NDJSON 协议与守护进程通信：

```json
// 请求 / Request: {"type":"<MsgType>","field1":"value1","field2":"value2"}\n
// 响应 / Response: {"type":"<MsgType>","field1":"value1","field2":"value2"}\n
// 错误 / Error: {"type":"Error","code":-1,"message":"description"}\n

// 消息类型 / Message Types:
// Auth, AuthResponse, Inference, InferenceResponse, InferenceStream,
// InferenceChunk, ModelList, ModelListResponse, ModelLoad, ModelLoadResponse,
// ModelUnload, ModelUnloadResponse, ContextStore, ContextRetrieve,
// Status, StatusResponse, RateLimitStatus, Error
```

### 8.9 跨语言特性对比 / Cross-Language Feature Comparison

| 特性 / Feature | Python | Go | Rust | Java | C# | Node.js | C |
|---|---|---|---|---|---|---|---|
| 同步推理 / Sync Infer | x | x | x | x | x | x | x |
| 流式推理 / Stream Infer | - | x | x | x | x | x | - |
| 异步 / Async | - | - | x | - | x | x | - |
| 自动重连 / Auto Reconnect | x | x | x | x | x | x | - |
| TLS 支持 / TLS Support | - | x | x | - | - | - | - |
| 认证 / Authentication | x | x | x | x | x | x | - |
| 模型管理 / Model Mgmt | x | x | x | x | x | x | x |
| 上下文管理 / Context | x | x | x | x | x | x | x |
| 速率限制 / Rate Limit | x | x | x | x | x | x | - |
| 连接池 / Conn Pool | - | x | - | x | x | x | - |
| 批量推理 / Batch Infer | - | x | - | x | x | x | - |
| 零依赖 / Zero Deps | x | x | - | x | x | x | x |

### 8.10 快速参考 / Quick Reference Card

| 操作 / Operation | Python | Go | Rust | Java | C# | Node.js | C |
|---|---|---|---|---|---|---|---|
| 创建客户端 | `AinosClient()` | `NewClient()` | `AinosClient::builder()...build()` | `AinosClient.builder()...build()` | `new AinosClient(options)` | `new AinosClient()` | `ainos_init()` |
| 连接 | `connect()` | `Connect()` | `connect().await` | `connect()` | `ConnectAsync()` | `connect()` | `ainos_connect()` |
| 推理 | `infer(prompt)` | `Infer(ctx, req)` | `infer(&req).await` | `infer(request)` | `InferAsync(req)` | `infer(req)` | `ainos_infer()` |
| 流式推理 | - | `InferStream()` | `infer_stream()` | `inferStream()` | `InferStreamAsync()` | `inferStream()` | - |
| 列出模型 | `model_list()` | `ModelList()` | `model_list().await` | `modelList()` | `GetModelListAsync()` | `modelList()` | `ainos_get_info()` |
| 加载模型 | `model_load(path)` | `ModelLoad(path, opts)` | `model_load().await` | `modelLoad(path)` | `LoadModelAsync()` | `modelLoad(path)` | `ainos_model_load()` |
| 卸载模型 | `model_unload(id)` | `ModelUnload(id)` | `model_unload().await` | `modelUnload(id)` | `UnloadModelAsync()` | `modelUnload(id)` | `ainos_model_unload()` |
| 存储上下文 | `context_store()` | `ContextStore()` | `context_store().await` | `contextStore()` | `ContextStoreAsync()` | `contextStore()` | `ainos_ctx_store()` |
| 检索上下文 | `context_retrieve()` | `ContextRetrieve()` | `context_retrieve().await` | `contextRetrieve()` | `ContextRetrieveAsync()` | `contextRetrieve()` | `ainos_ctx_get()` |
| 系统状态 | `status()` | `Status()` | `status().await` | `status()` | `GetStatusAsync()` | `status()` | `ainos_get_info()` |
| 断开连接 | `disconnect()` | `Disconnect()` | `disconnect().await` | `disconnect()` | `DisconnectAsync()` | `disconnect()` | `ainos_destroy()` |

---

> **文档版本 / Document Version**: 0.1.0  
> **最后更新 / Last Updated**: 2026-08-04  
> **SDK 版本 / SDK Version**: 0.1.0 (Python, Rust, Node.js, Java, C#), 1.0.0 (C libainos)  
> **协议 / Protocol**: NDJSON over TCP, port 9500, host 127.0.0.1 (default)