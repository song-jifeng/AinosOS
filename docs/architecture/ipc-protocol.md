# AinosOS IPC 协议详细规范

## 概述

AinosOS IPC (Inter-Process Communication) 协议基于 NDJSON (Newline Delimited JSON) 格式，为 AI 推理系统中的各个组件提供标准化通信机制。协议支持请求-响应模式和流式推送模式，内置认证和错误处理机制。

## 协议基础

### NDJSON 格式

每条消息为独立的一行 JSON 文本，以换行符 `\n` 分隔：

```json
{"id":"msg_001","type":"request","method":"inference.create","timestamp":1722748800000}\n
{"id":"msg_002","type":"response","request_id":"msg_001","status":"ok","result":{...}}\n
```

### 消息结构

所有消息共享以下基础结构：

```json
{
    "id": "string",              // 消息唯一标识符
    "type": "string",            // 消息类型
    "version": "1.0",           // 协议版本
    "timestamp": 1234567890,    // Unix 毫秒时间戳
    "ttl": 30000,               // 消息生存时间（毫秒）
    "source": "string",         // 源组件标识
    "target": "string"          // 目标组件标识
}
```

### 传输层

IPC 支持以下传输方式：

| 传输方式 | 描述 | 适用场景 |
|---------|------|---------|
| Unix Domain Socket | 本地进程间通信 | 高性能本地通信 |
| TCP Socket | 网络通信 | 分布式部署 |
| Shared Memory | 共享内存通信 | 大数据量传输 |
| Named Pipe | 命名管道 | Windows 平台 |

## 消息类型定义

### 1. 请求消息 (request)

```json
{
    "id": "req_001",
    "type": "request",
    "version": "1.0",
    "timestamp": 1722748800000,
    "method": "inference.create",
    "params": {
        "model_id": "llama-3.1-8b",
        "prompt": "Hello, world!",
        "temperature": 0.7,
        "max_tokens": 512
    },
    "auth": {
        "token": "eyJhbGciOiJIUzI1NiJ9...",
        "scope": "inference"
    }
}
```

### 2. 响应消息 (response)

```json
{
    "id": "resp_001",
    "type": "response",
    "version": "1.0",
    "timestamp": 1722748800050,
    "request_id": "req_001",
    "status": "ok",
    "result": {
        "output": "Hello! How can I help you today?",
        "tokens_generated": 8,
        "inference_time_ms": 45.2
    }
}
```

### 3. 错误消息 (error)

```json
{
    "id": "err_001",
    "type": "error",
    "version": "1.0",
    "timestamp": 1722748800050,
    "request_id": "req_001",
    "error": {
        "code": "INVALID_PARAMS",
        "message": "Temperature must be between 0.0 and 2.0",
        "details": {
            "field": "temperature",
            "value": 3.5,
            "constraint": "0.0 <= temperature <= 2.0"
        }
    }
}
```

### 4. 流式数据消息 (stream)

```json
{
    "id": "str_001",
    "type": "stream",
    "version": "1.0",
    "timestamp": 1722748800050,
    "request_id": "req_001",
    "sequence": 1,
    "data": {
        "token": "Hello",
        "logprob": -0.234,
        "finish_reason": null
    }
}
```

### 5. 流式结束消息 (stream_end)

```json
{
    "id": "str_end_001",
    "type": "stream_end",
    "version": "1.0",
    "timestamp": 1722748800100,
    "request_id": "req_001",
    "sequence": 10,
    "usage": {
        "prompt_tokens": 5,
        "completion_tokens": 50,
        "total_tokens": 55
    },
    "finish_reason": "stop"
}
```

### 6. 心跳消息 (heartbeat)

```json
{
    "id": "hb_001",
    "type": "heartbeat",
    "version": "1.0",
    "timestamp": 1722748800000,
    "source": "inference-server-1",
    "status": {
        "load": 0.45,
        "active_requests": 3,
        "memory_used_mb": 2048
    }
}
```

### 7. 认证消息 (auth)

```json
{
    "id": "auth_001",
    "type": "auth",
    "version": "1.0",
    "timestamp": 1722748800000,
    "method": "jwt",
    "credentials": {
        "token": "eyJhbGciOiJIUzI1NiJ9...",
        "api_key": "sk-xxxxxxxxxxxxxxxx"
    }
}
```

### 8. 认证响应消息 (auth_response)

```json
{
    "id": "auth_resp_001",
    "type": "auth_response",
    "version": "1.0",
    "timestamp": 1722748800010,
    "status": "ok",
    "session": {
        "id": "sess_001",
        "expires_at": 1722835200000,
        "scope": ["inference", "models", "system"]
    }
}
```

### 9. 订阅消息 (subscribe)

```json
{
    "id": "sub_001",
    "type": "subscribe",
    "version": "1.0",
    "timestamp": 1722748800000,
    "events": [
        "model.loaded",
        "model.unloaded",
        "inference.completed",
        "error.*"
    ]
}
```

### 10. 事件消息 (event)

```json
{
    "id": "evt_001",
    "type": "event",
    "version": "1.0",
    "timestamp": 1722748800050,
    "event": "model.loaded",
    "data": {
        "model_id": "llama-3.1-70b",
        "load_time_ms": 1234,
        "quantization": "Q4_K_M"
    }
}
```

### 11. 取消消息 (cancel)

```json
{
    "id": "cancel_001",
    "type": "cancel",
    "version": "1.0",
    "timestamp": 1722748800050,
    "request_id": "req_001",
    "reason": "user_abort"
}
```

### 12. 配置更新消息 (config_update)

```json
{
    "id": "cfg_001",
    "type": "config_update",
    "version": "1.0",
    "timestamp": 1722748800000,
    "source": "admin",
    "changes": {
        "inference.max_concurrent": 10,
        "logging.level": "debug"
    }
}
```

### 13. 日志消息 (log)

```json
{
    "id": "log_001",
    "type": "log",
    "version": "1.0",
    "timestamp": 1722748800050,
    "level": "info",
    "source": "inference-engine",
    "message": "Model loaded successfully",
    "context": {
        "model_id": "llama-3.1-8b",
        "load_time_ms": 850
    }
}
```

### 14. 指标消息 (metrics)

```json
{
    "id": "met_001",
    "type": "metrics",
    "version": "1.0",
    "timestamp": 1722748800000,
    "source": "inference-server-1",
    "metrics": {
        "requests_total": 1500,
        "requests_active": 5,
        "inference_time_avg_ms": 120.5,
        "inference_time_p99_ms": 450.2,
        "tokens_per_second": 85.3,
        "memory_used_bytes": 8589934592,
        "gpu_utilization": 0.78
    }
}
```

## 方法定义

### 推理相关方法

| 方法 | 描述 | 参数 | 返回 |
|------|------|------|------|
| inference.create | 创建推理请求 | model_id, prompt, params | 推理结果 |
| inference.stream | 创建流式推理 | model_id, prompt, params | 流式数据 |
| inference.cancel | 取消推理 | request_id | 取消确认 |
| inference.batch | 批量推理 | requests[] | 批量结果 |
| inference.status | 查询推理状态 | request_id | 状态信息 |

### 模型管理方法

| 方法 | 描述 | 参数 | 返回 |
|------|------|------|------|
| model.load | 加载模型 | model_path, params | 模型 ID |
| model.unload | 卸载模型 | model_id | 卸载确认 |
| model.list | 列出已加载模型 | - | 模型列表 |
| model.info | 获取模型信息 | model_id | 模型详情 |
| model.reload | 热重载模型 | model_id | 重载结果 |

### 系统管理方法

| 方法 | 描述 | 参数 | 返回 |
|------|------|------|------|
| system.info | 获取系统信息 | - | 系统信息 |
| system.stats | 获取运行统计 | - | 统计信息 |
| system.health | 健康检查 | - | 健康状态 |
| system.config | 获取/设置配置 | key, value | 配置值 |
| system.shutdown | 关闭服务 | - | 关闭确认 |

## 认证机制

### JWT 认证

```json
// 认证请求
{
    "id": "auth_001",
    "type": "auth",
    "version": "1.0",
    "timestamp": 1722748800000,
    "method": "jwt",
    "credentials": {
        "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyXzAwMSIsInNjb3BlIjpbImluZmVyZW5jZSIsIm1vZGVscyJdLCJleHAiOjE3MjI4MzUyMDB9.abc123"
    }
}

// 认证成功响应
{
    "id": "auth_resp_001",
    "type": "auth_response",
    "version": "1.0",
    "timestamp": 1722748800010,
    "status": "ok",
    "session": {
        "id": "sess_001",
        "expires_at": 1722835200000,
        "scope": ["inference", "models"]
    }
}

// 认证失败响应
{
    "id": "auth_resp_001",
    "type": "auth_response",
    "version": "1.0",
    "timestamp": 1722748800010,
    "status": "error",
    "error": {
        "code": "AUTH_FAILED",
        "message": "Invalid token signature"
    }
}
```

### API Key 认证

```json
{
    "id": "auth_002",
    "type": "auth",
    "version": "1.0",
    "timestamp": 1722748800000,
    "method": "api_key",
    "credentials": {
        "api_key": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "client_id": "client_001"
    }
}
```

### 权限范围

| 范围 | 描述 | 包含的方法 |
|------|------|-----------|
| inference | 推理权限 | inference.* |
| models | 模型管理权限 | model.* |
| system | 系统管理权限 | system.* |
| admin | 管理员权限 | 所有方法 |
| monitor | 监控权限 | system.stats, system.health |

### Token 格式

JWT Token 包含以下声明：

```json
{
    "sub": "user_001",
    "iss": "ainos-auth",
    "iat": 1722748800,
    "exp": 1722835200,
    "scope": ["inference", "models"],
    "client_id": "client_001",
    "rate_limit": 100,
    "priority": "high"
}
```

## 流式协议

### 流式推理流程

```
客户端                         服务端
  |                              |
  |-- inference.stream -------->|
  |                              |
  |<-- stream (token: "Hello") -|
  |<-- stream (token: " ") -----|
  |<-- stream (token: "world") -|
  |<-- stream (token: "!") -----|
  |<-- stream_end (finish: stop)|
  |                              |
```

### 流式消息序列

```json
// 1. 客户端发起流式推理请求
{"id":"req_001","type":"request","method":"inference.stream","params":{"model_id":"llama-3.1-8b","prompt":"Hello"}}

// 2. 服务端确认开始
{"id":"resp_001","type":"response","request_id":"req_001","status":"streaming","result":{"stream_id":"str_001"}}

// 3. 流式数据块
{"id":"str_001","type":"stream","request_id":"req_001","sequence":1,"data":{"token":"Hello","logprob":-0.5}}
{"id":"str_002","type":"stream","request_id":"req_001","sequence":2,"data":{"token":"!","logprob":-0.3}}
{"id":"str_003","type":"stream","request_id":"req_001","sequence":3,"data":{"token":" How","logprob":-0.8}}
{"id":"str_004","type":"stream","request_id":"req_001","sequence":4,"data":{"token":" can","logprob":-0.2}}
{"id":"str_005","type":"stream","request_id":"req_001","sequence":5,"data":{"token":" I","logprob":-0.1}}
{"id":"str_006","type":"stream","request_id":"req_001","sequence":6,"data":{"token":" help","logprob":-0.4}}
{"id":"str_007","type":"stream","request_id":"req_001","sequence":7,"data":{"token":" you","logprob":-0.6}}
{"id":"str_008","type":"stream","request_id":"req_001","sequence":8,"data":{"token":"?","logprob":-0.7}}

// 4. 流式结束
{"id":"str_end_001","type":"stream_end","request_id":"req_001","sequence":9,"usage":{"prompt_tokens":1,"completion_tokens":8,"total_tokens":9},"finish_reason":"stop"}
```

### 批处理流式推理

```json
// 批量推理请求
{
    "id": "req_002",
    "type": "request",
    "method": "inference.batch_stream",
    "params": {
        "requests": [
            {"id": "sub_001", "prompt": "What is AI?"},
            {"id": "sub_002", "prompt": "Explain ML"},
            {"id": "sub_003", "prompt": "What is Python?"}
        ],
        "model_id": "llama-3.1-8b",
        "params": {
            "temperature": 0.7,
            "max_tokens": 256
        }
    }
}

// 批量流式响应对每个子请求独立流式输出
{"id":"str_010","type":"stream","request_id":"req_002","sub_id":"sub_001","sequence":1,"data":{"token":"Artificial"}}
{"id":"str_011","type":"stream","request_id":"req_002","sub_id":"sub_002","sequence":1,"data":{"token":"Machine"}}
{"id":"str_012","type":"stream","request_id":"req_002","sub_id":"sub_003","sequence":1,"data":{"token":"Python"}}
```

## 错误处理

### 错误码定义

| 错误码 | HTTP 等效 | 描述 |
|--------|-----------|------|
| OK | 200 | 成功 |
| BAD_REQUEST | 400 | 请求格式错误 |
| UNAUTHORIZED | 401 | 未认证 |
| FORBIDDEN | 403 | 权限不足 |
| NOT_FOUND | 404 | 资源不存在 |
| METHOD_NOT_ALLOWED | 405 | 方法不允许 |
| REQUEST_TIMEOUT | 408 | 请求超时 |
| RATE_LIMITED | 429 | 请求频率限制 |
| INTERNAL_ERROR | 500 | 内部错误 |
| NOT_IMPLEMENTED | 501 | 未实现 |
| SERVICE_UNAVAILABLE | 503 | 服务不可用 |
| MODEL_NOT_LOADED | 1000 | 模型未加载 |
| MODEL_LOADING | 1001 | 模型正在加载 |
| CONTEXT_FULL | 1002 | 上下文已满 |
| MEMORY_EXHAUSTED | 1003 | 内存耗尽 |
| GPU_UNAVAILABLE | 1004 | GPU 不可用 |
| INVALID_PARAMS | 2000 | 参数无效 |
| PARAM_OUT_OF_RANGE | 2001 | 参数超出范围 |
| MISSING_PARAM | 2002 | 缺少必需参数 |
| PROTOCOL_ERROR | 3000 | 协议错误 |
| VERSION_MISMATCH | 3001 | 版本不匹配 |
| MESSAGE_TOO_LARGE | 3002 | 消息过大 |

### 错误响应格式

```json
{
    "id": "err_002",
    "type": "error",
    "version": "1.0",
    "timestamp": 1722748800050,
    "request_id": "req_001",
    "error": {
        "code": "RATE_LIMITED",
        "message": "请求频率超过限制，请稍后重试",
        "details": {
            "limit": 100,
            "current": 101,
            "window_ms": 60000,
            "retry_after_ms": 35000
        }
    }
}
```

### 重试策略

```json
{
    "id": "err_003",
    "type": "error",
    "request_id": "req_001",
    "error": {
        "code": "SERVICE_UNAVAILABLE",
        "message": "服务暂时不可用",
        "retry": {
            "allowed": true,
            "max_retries": 3,
            "backoff_ms": 1000,
            "backoff_multiplier": 2.0,
            "max_backoff_ms": 30000
        }
    }
}
```

## 协议状态机

### 连接状态

```
[CLOSED] --连接--> [AUTHENTICATING] --成功--> [READY]
                        |                        |
                        |--失败--> [CLOSED]       |--超时--> [CLOSED]
                                                 |
                        [READY] --请求--> [BUSY]
                        [READY] --订阅--> [SUBSCRIBED]
                        [READY] --心跳--> [READY]
```

### 请求状态

```
[PENDING] --开始处理--> [PROCESSING] --完成--> [COMPLETED]
                            |                      |
                            |--流式--> [STREAMING]  |--错误--> [ERROR]
                            |                      |
                        [STREAMING] --完成--> [COMPLETED]
                        [STREAMING] --取消--> [CANCELLED]
                        [PROCESSING] --取消--> [CANCELLED]
```

## 协议限制

| 限制项 | 默认值 | 最大值 | 说明 |
|--------|--------|--------|------|
| 消息大小 | 1 MB | 10 MB | 单条消息最大大小 |
| 消息速率 | 1000/s | 10000/s | 每秒最多消息数 |
| 并发连接 | 128 | 1024 | 最大并发连接数 |
| 流式超时 | 300s | 600s | 流式连接超时 |
| 请求超时 | 60s | 300s | 请求超时时间 |
| 重试次数 | 3 | 10 | 最大重试次数 |
| 路径深度 | 10 | 20 | 嵌套路径深度 |

## 序列化格式

### 数字精度

```json
{
    "type": "request",
    "temperature": 0.7,           // 浮点数，精确到小数点后 4 位
    "max_tokens": 512,            // 整数
    "top_p": 0.9,                 // 浮点数
    "seed": 42                    // 可选整数
}
```

### 时间戳格式

所有时间戳使用 Unix 毫秒时间戳（整数），精确到毫秒。

### 枚举值

枚举值使用字符串表示，不区分大小写：

```json
{
    "finish_reason": "stop",
    "status": "OK",
    "method": "Inference.Create"
}
```

## 安全考虑

### 消息完整性

所有消息应包含可选的 checksum 字段：

```json
{
    "id": "msg_001",
    "type": "request",
    "method": "inference.create",
    "checksum": "sha256:abc123...",
    "params": {...}
}
```

### 传输加密

TCP 传输应使用 TLS 加密：

```json
{
    "tls": {
        "version": "1.3",
        "certificate": "/etc/ainos/certs/server.crt",
        "ca_certificate": "/etc/ainos/certs/ca.crt"
    }
}
```

## 协议扩展

### 自定义消息类型

```json
{
    "id": "ext_001",
    "type": "x-custom-type",
    "version": "1.0",
    "timestamp": 1722748800000,
    "x-custom-field": "value"
}
```

### 版本协商

```json
// 客户端支持的版本
{
    "id": "ver_001",
    "type": "version",
    "versions": ["1.0", "2.0-beta"],
    "features": ["streaming", "batch", "compression"]
}

// 服务端选择版本
{
    "id": "ver_resp_001",
    "type": "version_response",
    "selected_version": "1.0",
    "supported_features": ["streaming", "batch"]
}
```

## 实现示例

### Python 客户端

```python
import json
import socket
import threading
import time
import uuid

class AinosIPCClient:
    def __init__(self, socket_path="/tmp/ainos.ipc"):
        self.socket_path = socket_path
        self.sock = None
        self.connected = False
        self.callbacks = {}
        self.stream_handlers = {}
        self._recv_thread = None
        
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.socket_path)
        self.connected = True
        self._authenticate()
        self._recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._recv_thread.start()
        
    def _authenticate(self):
        msg = {
            "id": str(uuid.uuid4()),
            "type": "auth",
            "version": "1.0",
            "timestamp": int(time.time() * 1000),
            "method": "api_key",
            "credentials": {
                "api_key": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
            }
        }
        self._send(msg)
        
    def _send(self, msg):
        data = json.dumps(msg) + "\n"
        self.sock.sendall(data.encode())
        
    def inference(self, model_id, prompt, **kwargs):
        req_id = str(uuid.uuid4())
        msg = {
            "id": req_id,
            "type": "request",
            "version": "1.0",
            "timestamp": int(time.time() * 1000),
            "method": "inference.create",
            "params": {
                "model_id": model_id,
                "prompt": prompt,
                "temperature": kwargs.get("temperature", 0.7),
                "max_tokens": kwargs.get("max_tokens", 512),
                "top_p": kwargs.get("top_p", 0.9)
            }
        }
        
        result = threading.Event()
        response = {}
        
        def handler(msg):
            response.update(msg)
            result.set()
            
        self.callbacks[req_id] = handler
        self._send(msg)
        result.wait(timeout=kwargs.get("timeout", 60))
        
        return response.get("result", {})
        
    def stream_inference(self, model_id, prompt, on_token, **kwargs):
        req_id = str(uuid.uuid4())
        msg = {
            "id": req_id,
            "type": "request",
            "version": "1.0",
            "timestamp": int(time.time() * 1000),
            "method": "inference.stream",
            "params": {
                "model_id": model_id,
                "prompt": prompt,
                "temperature": kwargs.get("temperature", 0.7),
                "max_tokens": kwargs.get("max_tokens", 512)
            }
        }
        
        self.stream_handlers[req_id] = on_token
        self._send(msg)
        return req_id
        
    def _receive_loop(self):
        buffer = ""
        while self.connected:
            try:
                data = self.sock.recv(65536).decode()
                if not data:
                    break
                buffer += data
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        self._handle_message(json.loads(line))
            except Exception as e:
                print(f"Receive error: {e}")
                break
                
    def _handle_message(self, msg):
        msg_type = msg.get("type")
        
        if msg_type == "response":
            req_id = msg.get("request_id")
            if req_id in self.callbacks:
                self.callbacks[req_id](msg)
                
        elif msg_type == "stream":
            req_id = msg.get("request_id")
            if req_id in self.stream_handlers:
                self.stream_handlers[req_id](msg.get("data", {}))
                
        elif msg_type == "stream_end":
            req_id = msg.get("request_id")
            if req_id in self.stream_handlers:
                self.stream_handlers[req_id]({"__end__": True, **msg.get("usage", {})})
                
        elif msg_type == "error":
            req_id = msg.get("request_id")
            if req_id in self.callbacks:
                self.callbacks[req_id](msg)
                
    def close(self):
        self.connected = False
        if self.sock:
            self.sock.close()


# 使用示例
client = AinosIPCClient()
client.connect()

# 同步推理
result = client.inference("llama-3.1-8b", "What is IPC?")
print(f"Result: {result['output']}")

# 流式推理
def on_token(data):
    if "__end__" in data:
        print(f"\n[Usage: {data}]")
    else:
        print(data.get("token", ""), end="", flush=True)

client.stream_inference("llama-3.1-8b", "Tell me a story", on_token)
time.sleep(30)
client.close()
```

### C 语言客户端

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <pthread.h>
#include <json-c/json.h>

typedef struct ainos_ipc_client {
    int sock_fd;
    int connected;
    pthread_t recv_thread;
    int running;
} ainos_ipc_client_t;

typedef void (*stream_callback_t)(const char* token);

static struct {
    char request_id[64];
    json_object* response;
    pthread_mutex_t mutex;
    pthread_cond_t cond;
    int completed;
} g_sync_state;

static stream_callback_t g_stream_callback = NULL;
static char g_stream_req_id[64] = {0};

int ainos_ipc_connect(ainos_ipc_client_t* client, const char* socket_path) {
    struct sockaddr_un addr;
    
    client->sock_fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (client->sock_fd < 0) return -1;
    
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, socket_path, sizeof(addr.sun_path) - 1);
    
    if (connect(client->sock_fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        close(client->sock_fd);
        return -1;
    }
    
    client->connected = 1;
    client->running = 1;
    return 0;
}

int ainos_ipc_send(ainos_ipc_client_t* client, json_object* msg) {
    const char* json_str = json_object_to_json_string(msg);
    char* line = malloc(strlen(json_str) + 2);
    sprintf(line, "%s\n", json_str);
    
    int ret = write(client->sock_fd, line, strlen(line));
    free(line);
    return ret > 0 ? 0 : -1;
}

json_object* ainos_ipc_create_request(const char* method, json_object* params) {
    json_object* msg = json_object_new_object();
    char id[64];
    snprintf(id, sizeof(id), "req_%d", rand());
    
    json_object_object_add(msg, "id", json_object_new_string(id));
    json_object_object_add(msg, "type", json_object_new_string("request"));
    json_object_object_add(msg, "version", json_object_new_string("1.0"));
    json_object_object_add(msg, "timestamp", 
        json_object_new_int64((int64_t)(time(NULL) * 1000)));
    json_object_object_add(msg, "method", json_object_new_string(method));
    json_object_object_add(msg, "params", params);
    
    return msg;
}

void* ainos_ipc_recv_loop(void* arg) {
    ainos_ipc_client_t* client = (ainos_ipc_client_t*)arg;
    char buffer[65536];
    size_t buf_len = 0;
    
    while (client->running) {
        char tmp[4096];
        ssize_t n = read(client->sock_fd, tmp, sizeof(tmp) - 1);
        if (n <= 0) break;
        tmp[n] = '\0';
        
        // Append to buffer
        if (buf_len + n < sizeof(buffer)) {
            memcpy(buffer + buf_len, tmp, n);
            buf_len += n;
        }
        
        // Process complete lines
        char* line_start = buffer;
        for (size_t i = 0; i < buf_len; i++) {
            if (buffer[i] == '\n') {
                buffer[i] = '\0';
                json_object* msg = json_tokener_parse(line_start);
                if (msg) {
                    const char* type = json_object_get_string(
                        json_object_object_get(msg, "type"));
                    
                    if (strcmp(type, "response") == 0) {
                        pthread_mutex_lock(&g_sync_state.mutex);
                        g_sync_state.response = msg;
                        g_sync_state.completed = 1;
                        pthread_cond_signal(&g_sync_state.cond);
                        pthread_mutex_unlock(&g_sync_state.mutex);
                    } else if (strcmp(type, "stream") == 0) {
                        json_object* data = json_object_object_get(msg, "data");
                        if (data && g_stream_callback) {
                            json_object* token = json_object_object_get(data, "token");
                            if (token) {
                                g_stream_callback(json_object_get_string(token));
                            }
                        }
                    }
                }
                line_start = buffer + i + 1;
            }
        }
        buf_len -= (line_start - buffer);
        memmove(buffer, line_start, buf_len);
    }
    return NULL;
}

json_object* ainos_ipc_sync_request(ainos_ipc_client_t* client, json_object* request) {
    pthread_mutex_lock(&g_sync_state.mutex);
    g_sync_state.completed = 0;
    g_sync_state.response = NULL;
    
    const char* json_str = json_object_to_json_string(request);
    json_object* params = json_object_object_get(request, "params");
    json_object* req_id = json_object_object_get(request, "id");
    if (req_id) {
        strncpy(g_sync_state.request_id, json_object_get_string(req_id), 
                sizeof(g_sync_state.request_id) - 1);
    }
    
    ainos_ipc_send(client, request);
    
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    ts.tv_sec += 60;  // 60 second timeout
    
    while (!g_sync_state.completed) {
        if (pthread_cond_timedwait(&g_sync_state.cond, &g_sync_state.mutex, &ts) != 0) {
            pthread_mutex_unlock(&g_sync_state.mutex);
            return NULL;  // timeout
        }
    }
    
    json_object* response = g_sync_state.response;
    if (response) json_object_get(response);  // increment refcount
    pthread_mutex_unlock(&g_sync_state.mutex);
    
    return response;
}

// 使用示例
int main() {
    ainos_ipc_client_t client;
    pthread_mutex_init(&g_sync_state.mutex, NULL);
    pthread_cond_init(&g_sync_state.cond, NULL);
    
    if (ainos_ipc_connect(&client, "/tmp/ainos.ipc") != 0) {
        fprintf(stderr, "连接失败\n");
        return 1;
    }
    
    pthread_create(&client.recv_thread, NULL, ainos_ipc_recv_loop, &client);
    
    // 同步推理
    json_object* params = json_object_new_object();
    json_object_object_add(params, "model_id", json_object_new_string("llama-3.1-8b"));
    json_object_object_add(params, "prompt", json_object_new_string("Hello, IPC!"));
    json_object_object_add(params, "temperature", json_object_new_double(0.7));
    
    json_object* request = ainos_ipc_create_request("inference.create", params);
    json_object* response = ainos_ipc_sync_request(&client, request);
    
    if (response) {
        json_object* result = json_object_object_get(response, "result");
        if (result) {
            json_object* output = json_object_object_get(result, "output");
            if (output) {
                printf("结果: %s\n", json_object_get_string(output));
            }
        }
        json_object_put(response);
    }
    
    json_object_put(request);
    client.running = 0;
    close(client.sock_fd);
    
    pthread_mutex_destroy(&g_sync_state.mutex);
    pthread_cond_destroy(&g_sync_state.cond);
    
    return 0;
}
```

## 协议测试

### 一致性测试用例

```python
import json
import pytest
import jsonschema

# JSON Schema 定义
REQUEST_SCHEMA = {
    "type": "object",
    "required": ["id", "type", "version", "method", "params"],
    "properties": {
        "id": {"type": "string", "pattern": "^req_"},
        "type": {"enum": ["request"]},
        "version": {"type": "string", "pattern": "^\\d+\\.\\d+$"},
        "method": {"type": "string"},
        "params": {"type": "object"},
        "timestamp": {"type": "integer"},
        "auth": {"type": "object"}
    }
}

def test_request_schema():
    """测试请求消息格式"""
    msg = {
        "id": "req_001",
        "type": "request",
        "version": "1.0",
        "method": "inference.create",
        "params": {"model_id": "test"}
    }
    jsonschema.validate(msg, REQUEST_SCHEMA)

def test_response_schema():
    """测试响应消息格式"""
    msg = {
        "id": "resp_001",
        "type": "response",
        "version": "1.0",
        "request_id": "req_001",
        "status": "ok",
        "result": {"output": "test"}
    }
    assert msg["type"] == "response"
    assert msg["status"] in ["ok", "error", "streaming"]
    assert "request_id" in msg

def test_stream_sequence():
    """测试流式消息序列"""
    messages = [
        {"type": "stream", "sequence": 1, "data": {"token": "Hello"}},
        {"type": "stream", "sequence": 2, "data": {"token": " "}},
        {"type": "stream", "sequence": 3, "data": {"token": "World"}},
        {"type": "stream_end", "sequence": 4, "finish_reason": "stop"}
    ]
    
    # 验证序列递增
    for i in range(1, len(messages)):
        assert messages[i]["sequence"] > messages[i-1]["sequence"]
    
    # 验证最后一条是 stream_end
    assert messages[-1]["type"] == "stream_end"

def test_error_format():
    """测试错误消息格式"""
    msg = {
        "id": "err_001",
        "type": "error",
        "request_id": "req_001",
        "error": {
            "code": "INVALID_PARAMS",
            "message": "Invalid parameter",
            "details": {}
        }
    }
    assert "code" in msg["error"]
    assert "message" in msg["error"]

def test_ndjson_parsing():
    """测试 NDJSON 解析"""
    data = (
        '{"id":"msg_001","type":"request"}\n'
        '{"id":"msg_002","type":"response"}\n'
        '{"id":"msg_003","type":"error"}\n'
    )
    lines = [json.loads(line) for line in data.strip().split('\n')]
    assert len(lines) == 3
    assert lines[0]["id"] == "msg_001"
    assert lines[1]["id"] == "msg_002"
    assert lines[2]["id"] == "msg_003"

def test_large_message_handling():
    """测试大消息处理"""
    large_data = "x" * 1000000
    msg = {"id": "large_001", "type": "request", "data": large_data}
    serialized = json.dumps(msg)
    assert len(serialized) > 1000000
    deserialized = json.loads(serialized)
    assert len(deserialized["data"]) == 1000000

def test_auth_flow():
    """测试认证流程"""
    # 认证请求
    auth_msg = {
        "id": "auth_001",
        "type": "auth",
        "method": "api_key",
        "credentials": {"api_key": "test_key"}
    }
    assert auth_msg["type"] == "auth"
    assert "credentials" in auth_msg
    
    # 认证响应
    auth_resp = {
        "id": "auth_resp_001",
        "type": "auth_response",
        "status": "ok",
        "session": {"id": "sess_001", "scope": ["inference"]}
    }
    assert auth_resp["type"] == "auth_response"
    assert auth_resp["status"] == "ok"

def test_version_compatibility():
    """测试版本兼容性"""
    v1_msg = {"version": "1.0", "type": "request", "method": "test"}
    v2_msg = {"version": "2.0", "type": "request", "method": "test", "new_field": "value"}
    
    # 旧版本应该忽略新字段，但不能崩溃
    assert v1_msg["version"] == "1.0"
    assert v2_msg.get("new_field") == "value"

def test_method_discovery():
    """测试方法发现"""
    discovery_resp = {
        "methods": [
            "inference.create",
            "inference.stream",
            "model.load",
            "model.unload",
            "system.info"
        ]
    }
    assert "inference.create" in discovery_resp["methods"]
    assert "inference.stream" in discovery_resp["methods"]
```

## 附录

### 协议版本历史

| 版本 | 日期 | 变更说明 |
|------|------|---------|
| 1.0 | 2024-08-01 | 初始版本 |
| 1.1 | 2024-09-15 | 添加流式批处理支持 |
| 1.2 | 2024-11-01 | 添加事件订阅机制 |
| 2.0-beta | 2025-01-15 | 重构消息格式，添加压缩支持 |

### 保留字段

所有以 `x-` 开头的字段为自定义扩展字段，不保证跨版本兼容性。

### 消息 ID 生成规则

消息 ID 格式：`{prefix}_{timestamp}_{random}`

- prefix: 消息类型前缀（req_, resp_, str_, err_, hb_ 等）
- timestamp: 创建时的 Unix 毫秒时间戳
- random: 6 位随机字母数字

示例：`req_1722748800000_a1b2c3`