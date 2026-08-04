# AinosOS 模型管理教程 / Model Management Tutorial

> 本文档详细介绍了 AinosOS 的模型管理功能，包括模型下载、加载、配置、优化、查询和卸载等操作。内容涵盖所有 SDK 的使用示例和最佳实践。
>
> This document provides a comprehensive guide to AinosOS model management, including model download, loading, configuration, optimization, querying, and unloading. It covers SDK examples across all supported languages and best practices.

---

## 目录 / Table of Contents

- [1. 模型管理概述 / Model Management Overview](#1-模型管理概述--model-management-overview)
- [2. 模型下载 / Model Download](#2-模型下载--model-download)
- [3. 模型加载 / Model Loading](#3-模型加载--model-loading)
- [4. 模型配置 / Model Configuration](#4-模型配置--model-configuration)
- [5. 模型优化 / Model Optimization](#5-模型优化--model-optimization)
- [6. 模型列表与状态 / Model List and Status](#6-模型列表与状态--model-list-and-status)
- [7. 模型卸载 / Model Unloading](#7-模型卸载--model-unloading)
- [8. 最佳实践 / Best Practices](#8-最佳实践--best-practices)

---

## 1. 模型管理概述 / Model Management Overview

### 1.1 支持的模型格式 / Supported Formats

AinosOS 支持三种主流 AI 模型格式，覆盖了从本地轻量推理到云端高性能推理的完整需求：

| 格式 / Format | 描述 / Description | 典型用途 / Typical Use |
|---------------|-------------------|----------------------|
| **GGUF** | llama.cpp 的通用格式，GGML 的继承者，支持量化模型 | 本地推理，CPU 友好，支持量化和 KV 缓存 |
| **GGML** | 旧版 llama.cpp 格式，向后兼容 | 遗留模型，已逐步迁移至 GGUF |
| **ONNX** | 开放神经网络交换格式，跨框架互操作 | 云端推理，GPU 加速，生产部署 |

格式检测由 `handle_model_load` 函数根据文件扩展名自动完成：`.gguf` 和 `.ggml` 文件使用 GGML 引擎，`.onnx` 文件使用 ONNX 服务。

```rust
// 来自 D:/Ainos/system-services/ai-daemon/src/ipc.rs
let supported_extensions = ["gguf", "ggml", "onnx", "bin"];
let engine_type = match ext {
    "gguf" | "ggml" => crate::runtime::EngineType::GGML,
    "onnx" => crate::runtime::EngineType::ONNX,
    _ => crate::runtime::EngineType::GGML,
};
```

### 1.2 默认模型 / Default Model

AinosOS 默认使用 **Qwen2.5 0.5B Instruct Q4** 量化模型，这是一个轻量级中文模型，适合在 CPU 上快速推理。

根据配置文件 `D:/Ainos/configs/ai-daemon.toml`：

```toml
default_model = "qwen2.5-0.5b-instruct-q4.gguf"
```

默认模型的具体文件映射定义在 `D:/Ainos/scripts/download_model.py` 的 `KNOWN_MODELS` 字典中：

```python
KNOWN_MODELS = {
    "qwen2.5-0.5b": {
        "repo": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "files": {
            "q4_0": "qwen2.5-0.5b-instruct-q4_0.gguf",
            "q4_k_m": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
            "q8_0": "qwen2.5-0.5b-instruct-q8_0.gguf",
        },
        "description": "Qwen2.5 0.5B Instruct - 轻量级中文模型",
    },
    # ...
}
```

### 1.3 模型目录 / Model Directory

模型目录由配置文件中的 `models_dir` 指定，默认值：

- **Windows**: `D:\Ainos\models`
- **Linux/macOS**: `/var/lib/ainos/models`

可通过环境变量 `AINOS_HOME` 覆盖基路径：

```rust
// 来自 D:/Ainos/system-services/ai-daemon/src/config.rs
let ainos_home = std::env::var("AINOS_HOME").unwrap_or_else(|_| {
    if cfg!(windows) { "D:\\Ainos".to_string() } else { "/var/lib/ainos".to_string() }
});
let models_dir = format!("{}/models", ainos_home);
```

### 1.4 模型注册表 / Model Registry

AinosOS 的模型注册表由 `ModelRegistry` 结构体管理（位于 `D:/Ainos/system-services/ai-daemon/src/models.rs`），它维护了两个核心映射：

- `available: HashMap<String, ModelInfo>` — 所有可用的模型（文件系统中扫描到的）
- `loaded: HashMap<String, ModelInfo>` — 当前已加载到内存中的模型
- `lru_order: Vec<String>` — LRU 淘汰顺序记录

模型注册表提供以下核心功能：
- 目录扫描（`scan_directory`）
- 模型注册（`register_model`）
- 模型加载（`load`）
- 模型卸载（`unload`）
- 模型列表（`list`）
- 加载状态查询（`is_loaded`）

### 1.5 模型生命周期 / Model Lifecycle

一个模型在 AinosOS 中的完整生命周期包含以下阶段：

```
下载 (Download) -> 放置目录 (Place in Directory) -> 扫描发现 (Scan) -> 注册 (Register) -> 加载 (Load) -> 使用 (Use) -> 卸载 (Unload)
```

1. **下载**: 使用 `download_model.py` 脚本从 Hugging Face Hub 下载 GGUF 模型
2. **放置目录**: 将模型文件放入 `models_dir` 指定的目录
3. **扫描发现**: 守护进程启动时自动扫描目录，注册所有支持的模型文件
4. **注册**: 模型注册到 `ModelRegistry` 的 `available` 映射中
5. **加载**: 通过 IPC 或自动加载机制将模型载入内存
6. **使用**: 执行推理请求
7. **卸载**: 释放模型占用的内存资源

---

## 2. 模型下载 / Model Download

### 2.1 下载脚本 / Download Script

AinosOS 提供了 `D:/Ainos/scripts/download_model.py` 下载脚本，支持从 Hugging Face Hub 下载 GGUF 格式模型，具备断点续传和进度显示功能。

**基本用法**:

```bash
# 使用预配置的模型名称下载
python download_model.py --known qwen2.5-0.5b --quantization q4_0

# 直接指定 Hugging Face 仓库
python download_model.py --model Qwen/Qwen2.5-0.5B-Instruct-GGUF --quantization q4_0

# 列出所有可用的预配置模型
python download_model.py --list

# 指定输出目录
python download_model.py --known qwen2.5-0.5b --output ./my_models
```

### 2.2 支持的模型 / Supported Models

`download_model.py` 预配置了以下模型：

| 名称 / Name | 仓库 / Repo | 描述 / Description |
|------------|-------------|-------------------|
| `qwen2.5-0.5b` | Qwen/Qwen2.5-0.5B-Instruct-GGUF | Qwen2.5 0.5B Instruct - 轻量级中文模型 |
| `phi-3-mini` | microsoft/Phi-3-mini-4k-instruct-gguf | Phi-3 Mini 4K - 微软小模型，英文优秀 |
| `llama-3.2-1b` | huggingface/llama-3.2-1b-gguf | Llama 3.2 1B - 超轻量英文模型 |

每个模型支持多种量化格式：

| 模型 / Model | 支持的量化 / Supported Quantizations |
|-------------|--------------------------------------|
| qwen2.5-0.5b | q4_0, q4_k_m, q8_0 |
| phi-3-mini | q4_0, q4_k_m |
| llama-3.2-1b | q4_0, q8_0 |

### 2.3 下载 URL 格式 / Download URL Format

下载脚本自动构建 Hugging Face 下载 URL，格式为：

```
https://huggingface.co/{repo}/resolve/main/{filename}
```

例如，下载 Qwen2.5 0.5B Q4_0 模型：

```
https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_0.gguf
```

### 2.4 手动下载 / Manual Download

除使用脚本外，也可以手动从 Hugging Face 下载模型文件：

1. 访问 Hugging Face 模型页面（如 https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF）
2. 下载所需的 GGUF 文件
3. 将文件放入 AinosOS 的 `models_dir` 目录
4. 重启守护进程或手动触发模型扫描

### 2.5 断点续传 / Resume Download

`download_file` 函数支持断点续传机制。如果下载中断，重新运行相同的下载命令会自动检测已下载的部分并从中断处继续：

```python
def download_file(url: str, dest: Path, expected_sha256: Optional[str] = None) -> bool:
    # 检查文件是否已存在且完整
    if dest.exists() and expected_sha256:
        if verify_sha256(dest, expected_sha256):
            print(f"  ✓ 文件已存在且校验通过: {dest.name}")
            return True

    mode = "ab" if dest.exists() else "wb"
    existing_size = dest.stat().st_size if dest.exists() else 0
    headers = {"Range": f"bytes={existing_size}-"} if existing_size > 0 else {}
    # ...
```

### 2.6 模型完整性校验 / Model Integrity Verification

下载脚本支持 SHA256 校验，用于验证下载文件的完整性：

```python
def verify_sha256(filepath: Path, expected: str) -> bool:
    """验证文件 SHA256"""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest() == expected.lower()
```

使用方式：在 `download_model.py` 的 `KNOWN_MODELS` 条目中添加 `sha256` 字段即可启用校验。如果校验失败，下载脚本会提示并返回错误状态。

### 2.7 模型清单文件 / Model Manifest

下载完成后，脚本会自动更新模型清单文件 `model_manifest.json`（位于模型目录中），记录已下载的模型信息：

```json
{
  "models": [
    {
      "name": "qwen2.5-0.5b-instruct-q4_0.gguf",
      "source": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
      "quantization": "q4_0",
      "downloaded_at": "2026-08-04 10:30:00",
      "path": "D:\\Ainos\\models\\qwen2.5-0.5b-instruct-q4_0.gguf"
    }
  ]
}
```

### 2.8 转换模型为 GGUF 格式 / Converting Models to GGUF

对于 Hugging Face 上未提供 GGUF 格式的模型，可以使用 llama.cpp 的转换工具将其转换为 GGUF 格式：

```bash
# 使用 llama.cpp 的 convert.py 脚本
python D:/Ainos/llama.cpp/convert.py \
  --outtype q4_0 \
  ./path/to/model \
  D:/Ainos/models/my-model-q4_0.gguf
```

前提条件：
- 安装 llama.cpp（AinosOS 包含 `D:/Ainos/llama.cpp/` 目录）
- 模型原始文件（如 PyTorch checkpoint 或 safetensors 格式）
- Python 环境依赖（`pip install torch transformers`）

### 2.9 模型存储最佳实践 / Storage Best Practices

1. **使用符号链接**: 可在 `models_dir` 中使用符号链接引用其他位置的模型文件，避免重复拷贝
2. **按量化级别分类**: 建议使用目录结构如 `models/q4_0/`、`models/q8_0/` 来组织不同量化级别的模型
3. **定期清理**: 卸载不再使用的模型文件以节省磁盘空间
4. **备份重要模型**: 对于生产环境，建议备份模型文件到其他存储位置
5. **监控磁盘空间**: 模型文件通常较大（1-10GB），需要确保足够的磁盘空间

### 2.10 下载脚本高级用法 / Advanced Script Usage

```bash
# 下载到自定义目录并自动更新清单
python download_model.py --known qwen2.5-0.5b --quantization q8_0 --output /mnt/models/

# 组合使用 --list 查看本地已有模型
python download_model.py --list

# 输出示例：
# 可用的预配置模型:
# ======================================================================
#   qwen2.5-0.5b: Qwen2.5 0.5B Instruct - 轻量级中文模型
#     仓库: Qwen/Qwen2.5-0.5B-Instruct-GGUF
#     [✓] q4_0      → qwen2.5-0.5b-instruct-q4_0.gguf
#     [ ] q4_k_m    → qwen2.5-0.5b-instruct-q4_k_m.gguf
#     [ ] q8_0      → qwen2.5-0.5b-instruct-q8_0.gguf
#   ...
#
# 本地已有 1 个模型:
#   • qwen2.5-0.5b-instruct-q4_0.gguf (412.50MB)
```

---

## 3. 模型加载 / Model Loading

### 3.1 启动时自动加载 / Automatic Loading on Startup

AinosOS 守护进程启动时自动执行以下流程：

1. 加载配置文件
2. 扫描 `models_dir` 目录，注册所有支持的模型文件（`.gguf`、`.ggml`、`.onnx`、`.bin`）
3. 根据配置自动加载默认模型

目录扫描由 `ModelRegistry::scan_directory` 实现：

```rust
// 来自 D:/Ainos/system-services/ai-daemon/src/models.rs
pub fn scan_directory(&mut self, path: &str) -> std::io::Result<()> {
    let dir = std::fs::read_dir(path)?;
    for entry in dir.flatten() {
        let path = entry.path();
        if let Some(ext) = path.extension() {
            let ext = ext.to_string_lossy().to_lowercase();
            if matches!(ext.as_str(), "gguf" | "ggml" | "onnx" | "bin") {
                let file_name = path.file_name()
                    .map(|n| n.to_string_lossy().to_string())
                    .unwrap_or_default();
                let metadata = std::fs::metadata(&path)?;
                let size_mb = metadata.len() / (1024 * 1024);
                let model_id = file_name.replace('.', "_");

                let info = ModelInfo {
                    id: model_id.clone(),
                    name: file_name,
                    path: path.to_string_lossy().to_string(),
                    size_mb,
                    loaded: false,
                    architecture: "auto".to_string(),
                };
                self.available.insert(model_id, info);
            }
        }
    }
    info!("Scanned models directory: {} models found", self.available.len());
    Ok(())
}
```

### 3.2 通过 IPC 手动加载 / Manual Loading via IPC

客户端通过发送 `ModelLoad` 消息来手动加载模型。IPC 消息格式如下：

**请求 / Request**:

```json
{
  "type": "ModelLoad",
  "path": "D:\\Ainos\\models\\qwen2.5-0.5b-instruct-q4_0.gguf"
}
```

**响应 / Response**:

```json
{
  "type": "ModelLoadResponse",
  "model_id": "qwen2_5-0_5b-instruct-q4_0_gguf",
  "status": "loaded",
  "message": "Model 'qwen2_5-0_5b-instruct-q4_0_gguf' loaded successfully",
  "model_info": {
    "id": "qwen2_5-0_5b-instruct-q4_0_gguf",
    "name": "qwen2.5-0.5b-instruct-q4_0.gguf",
    "path": "D:\\Ainos\\models\\qwen2.5-0.5b-instruct-q4_0.gguf",
    "size_mb": 412,
    "loaded": true,
    "architecture": "auto"
  }
}
```

**错误响应 / Error Response**:

```json
{
  "type": "ModelLoadResponse",
  "model_id": "unknown_model",
  "status": "error",
  "message": "Model file not found: D:\\Ainos\\models\\unknown.gguf",
  "model_info": null
}
```

### 3.3 ModelLoad 请求字段说明 / ModelLoad Request Fields

| 字段 / Field | 类型 / Type | 必需 / Required | 描述 / Description |
|-------------|-------------|----------------|-------------------|
| `type` | string | 是 | 固定为 `"ModelLoad"` |
| `path` | string | 是 | 模型文件的绝对路径 |

### 3.4 ModelLoadResponse 字段说明 / ModelLoadResponse Fields

| 字段 / Field | 类型 / Type | 描述 / Description |
|-------------|-------------|-------------------|
| `model_id` | string | 模型标识符（由文件名自动生成，将 `.` 替换为 `_`） |
| `status` | string | 加载状态：`"loaded"`、`"already_loaded"`、`"error"` |
| `message` | string | 人类可读的状态消息 |
| `model_info` | object/null | 模型元数据，`status` 为 `"error"` 时为 `null` |

### 3.5 加载处理逻辑 / Loading Logic

`handle_model_load` 函数（位于 `D:/Ainos/system-services/ai-daemon/src/ipc.rs`）按以下步骤处理加载请求：

1. **验证路径**: 检查 `path` 是否为空，模型文件是否存在
2. **验证格式**: 检查文件扩展名是否在支持列表中（`gguf`、`ggml`、`onnx`、`bin`）
3. **生成 model_id**: 将文件名中的 `.` 替换为 `_` 作为模型标识符
4. **读取元数据**: 获取文件大小等信息
5. **确定引擎类型**: 根据扩展名选择 GGML 或 ONNX 引擎
6. **注册模型**: 将模型添加到 `ModelRegistry`
7. **加载模型**: 如果模型尚未加载，调用 `ModelRegistry::load` 加载模型
8. **初始化引擎**: 调用 `RuntimeManager::init_engine` 初始化推理引擎
9. **记录审计日志**: 记录加载操作到审计日志

### 3.6 通过 Python SDK 加载 / Loading via Python SDK

```python
import socket
import json

def load_model(path: str, host="127.0.0.1", port=9500) -> dict:
    """通过 IPC 加载模型"""
    msg = {"type": "ModelLoad", "path": path}
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10)
    try:
        s.connect((host, port))
        s.sendall((json.dumps(msg) + "\n").encode("utf-8"))
        resp = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
            if b"\n" in resp:
                break
        return json.loads(resp.decode("utf-8").strip())
    finally:
        s.close()

# 使用示例
result = load_model("D:\\Ainos\\models\\qwen2.5-0.5b-instruct-q4_0.gguf")
print(f"Status: {result['status']}")
print(f"Model ID: {result['model_id']}")
print(f"Message: {result['message']}")
```

### 3.7 通过 Go SDK 加载 / Loading via Go SDK

```go
package main

import (
    "context"
    "fmt"
    "log"
    "github.com/ainos-os/ainos-sdk-go"
)

func main() {
    client := ainos.NewClient()
    if err := client.Connect(); err != nil {
        log.Fatal(err)
    }
    defer client.Disconnect()

    // 加载模型
    result, err := client.LoadModel(context.Background(), &ainos.ModelLoadRequest{
        Path: "D:\\Ainos\\models\\qwen2.5-0.5b-instruct-q4_0.gguf",
    })
    if err != nil {
        log.Fatal(err)
    }

    fmt.Printf("Model ID: %s\n", result.ModelID)
    fmt.Printf("Status: %s\n", result.Status)
    fmt.Printf("Message: %s\n", result.Message)
    if result.ModelInfo != nil {
        fmt.Printf("Size: %d MB\n", result.ModelInfo.SizeMB)
    }
}
```

Go SDK 的模型加载功能由 `client.go` 中的 `Client.LoadModel` 方法实现，该方法发送 `ModelLoad` 消息并解析 `ModelLoadResponse` 响应。Go 客户端类型定义在 `types.go` 中：

```go
// 来自 D:/Ainos/bindings/go/ainos/types.go
type ModelLoadRequest struct {
    Path string `json:"path"`
}

type ModelLoadResponse struct {
    ModelID   string     `json:"model_id"`
    Status    string     `json:"status"`
    Message   string     `json:"message"`
    ModelInfo *ModelInfo `json:"model_info,omitempty"`
}
```

### 3.8 通过 Rust SDK 加载 / Loading via Rust SDK

```rust
use ainos_sdk::AinosClient;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let client = AinosClient::new("127.0.0.1:9500")?;
    client.connect().await?;

    let response = client.load_model(
        "D:\\Ainos\\models\\qwen2.5-0.5b-instruct-q4_0.gguf"
    ).await?;

    println!("Model ID: {}", response.model_id);
    println!("Status: {}", response.status);
    println!("Message: {}", response.message);

    if let Some(info) = response.model_info {
        println!("Size: {} MB", info.size_mb);
        println!("Architecture: {}", info.architecture);
    }

    client.disconnect().await?;
    Ok(())
}
```

Rust SDK 通过 FFI 层与 C++ Runtime 通信。在底层，`runtime.rs` 中的 FFI 绑定调用 `ainos_engine_load_model` 函数（定义在 `D:/Ainos/ai-runtime/ffi/ai_runtime_ffi.cpp`）：

```rust
// 来自 D:/Ainos/system-services/ai-daemon/src/runtime.rs (GGML FFI bindings)
#[link(name = "ainos_ai_runtime")]
extern "C" {
    pub fn ainos_engine_load_model(
        engine: *mut c_void,
        model_path: *const c_char,
        model_id: *const c_char,
    ) -> c_int;
    // ...
}
```

### 3.9 通过 C SDK 加载 / Loading via C SDK

```c
#include "ainos/ai_runtime.h"
#include "ainos/ai_runtime_ffi.h"
#include <stdio.h>

int main() {
    // 创建模型管理器
    ainos_model_manager_t mgr = ainos_model_manager_create();
    if (!mgr) {
        fprintf(stderr, "Failed to create model manager\n");
        return 1;
    }

    // 注册模型
    ainos_status_t status = ainos_model_manager_register(
        mgr,
        "my-model",
        "D:\\Ainos\\models\\qwen2.5-0.5b-instruct-q4_0.gguf",
        "ggml"
    );
    if (status != AINOS_STATUS_OK) {
        fprintf(stderr, "Failed to register model\n");
        return 1;
    }

    // 加载模型
    status = ainos_model_manager_load(mgr, "my-model");
    if (status == AINOS_STATUS_OK) {
        printf("Model loaded successfully\n");
    } else {
        fprintf(stderr, "Failed to load model: %d\n", status);
    }

    ainos_model_manager_destroy(mgr);
    return 0;
}
```

C FFI 层定义在 `D:/Ainos/ai-runtime/ffi/ai_runtime_ffi.cpp`，提供 `extern "C"` 接口：

```c
// 来自 D:/Ainos/ai-runtime/ffi/ai_runtime_ffi.h
ainos_model_manager_t ainos_model_manager_create(void);
void ainos_model_manager_destroy(ainos_model_manager_t mgr);
ainos_status_t ainos_model_manager_register(
    ainos_model_manager_t mgr,
    const char* model_id,
    const char* model_path,
    const char* framework
);
ainos_status_t ainos_model_manager_load(
    ainos_model_manager_t mgr,
    const char* model_id
);
ainos_status_t ainos_model_manager_unload(
    ainos_model_manager_t mgr,
    const char* model_id
);
```

### 3.10 通过 Node.js SDK 加载 / Loading via Node.js SDK

```typescript
// 来自 D:/Ainos/bindings/node/src/client.ts
import { AinosClient } from 'ainos-sdk';

async function main() {
    const client = new AinosClient({
        host: '127.0.0.1',
        port: 9500,
    });

    await client.connect();

    // 加载模型
    const response = await client.loadModel({
        path: 'D:\\Ainos\\models\\qwen2.5-0.5b-instruct-q4_0.gguf',
    });

    console.log(`Model ID: ${response.modelId}`);
    console.log(`Status: ${response.status}`);
    console.log(`Message: ${response.message}`);

    if (response.modelInfo) {
        console.log(`Size: ${response.modelInfo.sizeMb} MB`);
    }

    await client.disconnect();
}

main().catch(console.error);
```

Node.js SDK 的 `AinosClient` 类提供 `loadModel` 方法，内部使用 `TcpTransport` 发送 `ModelLoad` 类型消息：

```typescript
// 来自 D:/Ainos/bindings/node/src/client.ts（类型定义）
export interface ModelLoadOptions {
    path: string;
}

export interface ModelLoadResponse {
    modelId: string;
    status: 'loaded' | 'already_loaded' | 'error';
    message: string;
    modelInfo?: ModelInfo | null;
}
```

### 3.11 配置默认模型 / Configuring Default Model

默认模型在配置文件中设置：

```toml
# D:/Ainos/configs/ai-daemon.toml
default_model = "qwen2.5-0.5b-instruct-q4.gguf"
```

守护进程启动时，会读取此配置并尝试加载默认模型。如果默认模型文件不存在，守护进程将继续运行，但不加载任何模型。

### 3.12 启动时模型扫描 / Model Scanning on Startup

守护进程启动时自动扫描模型目录，代码位于 `D:/Ainos/system-services/ai-daemon/src/main.rs`：

```rust
// 在 main.rs 中初始化 AppState 时调用
let state = Arc::new(RwLock::new(AppState::new(cfg)));

// AppState::new 内部调用 ModelRegistry::new()
// 之后在合适时机调用 scan_directory
```

### 3.13 错误处理 / Error Handling

模型加载可能遇到以下错误：

| 错误场景 / Error Scenario | 状态码 / Status | 描述 / Description |
|--------------------------|----------------|-------------------|
| `model_path is empty` | `"error"` | 路径为空 |
| `Model file not found` | `"error"` | 指定路径不存在 |
| `Unsupported model format` | `"error"` | 文件扩展名不在支持列表中 |
| `Failed to read metadata` | `"error"` | 无法读取文件元数据 |
| `Failed to register model` | `"error"` | 注册模型失败 |
| `Failed to load model` | `"error"` | 模型加载失败（引擎错误） |
| 模型已加载 | `"already_loaded"` | 模型已在内存中，无需重复加载 |

---

## 4. 模型配置 / Model Configuration

### 4.1 配置文件 / Config File

AinosOS 的模型配置位于 `D:/Ainos/configs/ai-daemon.toml`。完整的配置文件结构如下：

```toml
# Ainos AI Daemon Configuration
# ============================================

models_dir = "D:\\Ainos\\models"
default_model = "qwen2.5-0.5b-instruct-q4.gguf"
socket_path = "127.0.0.1:9500"

# Local inference
enable_local = true
local_engine = "ggml"
max_concurrent_inferences = 2
model_cache_size_mb = 4096
inference_timeout_secs = 120

# Cloud fallback (Weelink Platform)
enable_cloud = true
cloud_api_url = "https://api.weelinking.com/v1"
cloud_api_key = ""
cloud_model = "gpt-5.6-sol"
network_check_interval = 30
cloud_fallback_confidence = 0.6

# Context management
context_dir = "D:\\Ainos\\data\\contexts"
max_contexts = 1000
context_ttl_days = 30

# Logging
log_level = "debug"
audit_log = "D:\\Ainos\\logs\\audit.log"
audit_all_requests = true

# Legacy TLS settings (deprecated, use [tls] section)
enable_tls = false
tls_cert_path = "D:\\Ainos\\certs\\server.crt"
tls_key_path = "D:\\Ainos\\certs\\server.key"

# ============================================
# Authentication
# ============================================
[auth]
enabled = true
token = ""
token_path = "D:\\Ainos\\configs\\auth_token.txt"
session_ttl_seconds = 3600
permissions_file = ""
default_permissions = ["infer", "status", "context"]
audit_log_path = "D:\\Ainos\\logs\\audit.log"
audit_all_requests = true

# ============================================
# Rate Limiting
# ============================================
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

# ============================================
# TLS / Transport Security
# ============================================
[tls]
enabled = false
cert_path = "D:\\Ainos\\certs\\server.crt"
key_path = "D:\\Ainos\\certs\\server.key"
verify_client = false
```

### 4.2 模型参数说明 / Model Parameters

`DaemonConfig` 结构体（定义在 `D:/Ainos/system-services/ai-daemon/src/config.rs`）包含以下与模型相关的配置字段：

| 字段 / Field | 类型 / Type | 默认值 / Default | 描述 / Description |
|-------------|-------------|-----------------|-------------------|
| `models_dir` | String | `{AINOS_HOME}/models` | 模型存储目录 |
| `default_model` | String | `"phi-3-mini-4k-instruct-q4.gguf"` | 默认模型文件名 |
| `enable_local` | bool | `true` | 是否启用本地推理 |
| `local_engine` | String | `"ggml"` | 本地推理引擎 (`ggml` / `onnx`) |
| `max_concurrent_inferences` | u32 | `2` | 最大并行推理数 |
| `model_cache_size_mb` | u32 | `4096` | 模型缓存大小 (MB) |
| `inference_timeout_secs` | u32 | `120` | 推理超时时间 (秒) |
| `enable_cloud` | bool | `true` | 是否启用云端回退 |
| `cloud_api_url` | String | `"https://api.weelinking.com/v1"` | 云端 API 端点 |
| `cloud_api_key` | String | `""` | 云端 API Key |
| `cloud_model` | String | `"gpt-5.6-sol"` | 云端模型名称 |

### 4.3 每模型配置 / Per-Model Configuration

AinosOS 支持通过 YAML 配置文件为每个模型单独设置参数。模型配置文件位于 `D:/Ainos/models/model_configs/` 目录：

```bash
ls D:/Ainos/models/model_configs/
# llama-2-13b.yaml  llama-2-70b.yaml  llama-2-7b.yaml
# llama-3-70b.yaml   llama-3-8b.yaml   mistral-7b.yaml
# mixtral-8x7b.yaml  qwen-14b.yaml     qwen-72b.yaml
# qwen-7b.yaml       yi-6b.yaml
```

每个 YAML 配置文件包含模型架构参数、推荐配置和性能基准信息。例如 `llama-2-7b.yaml` 包含：

```yaml
# 模型架构信息
model:
  name: "Llama-2-7b"
  architecture: "llama"
  parameters: 7_000_000_000
  context_length: 4096

# 量化推荐配置
quantization:
  recommended: "q4_0"
  options: ["q4_0", "q4_1", "q5_0", "q5_1", "q8_0"]

# 内存需求
memory:
  q4_0: 4096   # MB
  q8_0: 7168   # MB
  f16: 14336   # MB

# 推理配置推荐
inference:
  batch_size: 512
  num_threads: 4
  use_cache: true
```

### 4.4 默认模型选择 / Default Model Selection

默认模型的选择逻辑：

1. 读取配置文件中的 `default_model` 字段
2. 如果未配置或配置为空，使用代码中的默认值 `"phi-3-mini-4k-instruct-q4.gguf"`
3. 守护进程启动时尝试加载默认模型
4. 如果默认模型文件不存在，守护进程继续运行但不加载任何模型
5. 用户可通过 IPC 手动加载其他模型

### 4.5 模型架构自动检测 / Model Architecture Auto-Detection

模型架构自动检测基于以下策略：

1. 对于通过 `ModelLoad` IPC 手动加载的模型，架构默认设置为 `"auto"`
2. 对于 ONNX 模型，架构设置为 `"onnx"`
3. 如果模型有对应的 YAML 配置文件，架构信息从配置文件中读取
4. 运行时通过 GGUF 文件头信息自动检测架构（如果 GGML 引擎支持）

```rust
// 架构检测逻辑
let architecture = match ext {
    "gguf" | "ggml" => "auto".to_string(),
    "onnx" => "onnx".to_string(),
    _ => "auto".to_string(),
};
```

### 4.6 模型缓存大小配置 / Model Cache Size Configuration

模型缓存大小通过 `model_cache_size_mb` 配置项控制，默认值为 4096 MB（4 GB）。

模型缓存用于：
- 存储已加载模型的权重数据
- 减少模型加载/卸载的磁盘 I/O 开销
- 在多个推理请求间复用模型

当缓存达到上限时，系统使用 LRU 策略自动淘汰最久未使用的模型：

```cpp
// 来自 D:/Ainos/ai-runtime/model-manager/model_manager.cpp
while (current_memory_usage_ > total_memory_limit_ * 0.8) {
    auto status = EvictLRUModel();
    if (status != Status::OK) {
        break;
    }
}
```

### 4.7 并行推理限制 / Concurrent Inference Limits

`max_concurrent_inferences` 配置项控制最大并行推理数，默认值为 2。

此限制受到电源策略的影响：
- **MAX 模式**: 使用 4 个推理线程，批处理大小 8
- **BALANCED 模式**: 使用 2 个推理线程，批处理大小 4
- **EFFICIENT 模式**: 使用 1 个推理线程，批处理大小 2
- **EMERGENCY 模式**: 使用 1 个推理线程，批处理大小 1

```cpp
// 来自 D:/Ainos/ai-runtime/power-policy/power_policy.cpp
// MAX 模式: 全速
modes[0] = { 4, "AVX-256", "FP32", 8, true };
// BALANCED 模式: 平衡
modes[1] = { 2, "AVX-128", "FP16", 4, true };
// EFFICIENT 模式: 节能
modes[2] = { 1, "NEON/SCALAR", "INT8", 2, false };
// EMERGENCY 模式: 紧急
modes[3] = { 1, "SCALAR", "INT4", 1, false };
```

### 4.8 推理超时配置 / Inference Timeout Configuration

`inference_timeout_secs` 配置项控制推理请求的超时时间，默认值为 120 秒。

超时处理逻辑：
1. 如果推理请求在超时时间内未完成，守护进程返回错误响应
2. 超时后，系统会尝试终止推理任务并释放资源
3. 超时阈值可通过配置文件动态调整

### 4.9 云端回退模型配置 / Cloud Fallback Model Configuration

当本地推理不可用或需要更高精度时，AinosOS 支持自动回退到云端模型：

```toml
# 云端回退配置
enable_cloud = true
cloud_api_url = "https://api.weelinking.com/v1"
cloud_api_key = "your-api-key-here"
cloud_model = "gpt-5.6-sol"
network_check_interval = 30
cloud_fallback_confidence = 0.6
```

云端回退的工作流程：

1. 检查网络连接（通过 TCP 连接 8.8.8.8:53 检测）
2. 如果网络可用且配置了 API Key，使用云端 API
3. 如果网络不可用或未配置 API Key，使用本地推理
4. 推理结果首先检查语义缓存

```rust
// 来自 D:/Ainos/system-services/ai-daemon/src/ipc.rs
async fn handle_inference(...) -> IpcMessage {
    let is_online = check_network_available().await;
    if is_online && s.config.enable_cloud && !s.config.cloud_api_key.is_empty() {
        // 使用云端 API
        let response = call_cloud_api(&api_url, &api_key, &cloud_model, &prompt, temp, max_tok).await;
        // ...
    } else if s.config.enable_local {
        // 使用本地推理
        let output = generate_local_response(&prompt, reason);
        // ...
    }
}
```

### 4.10 环境变量覆盖 / Environment Variable Overrides

AinosOS 支持通过环境变量覆盖配置参数：

| 环境变量 / Env Var | 覆盖的配置项 / Overrides |
|-------------------|------------------------|
| `AINOS_HOME` | 基路径（影响 `models_dir`、`context_dir` 等） |
| `RUST_LOG` | 日志级别（如 `RUST_LOG=debug`） |

```rust
// 环境变量覆盖逻辑
let ainos_home = std::env::var("AINOS_HOME").unwrap_or_else(|_| {
    if cfg!(windows) { "D:\\Ainos".to_string() } else { "/var/lib/ainos".to_string() }
});
```

---

## 5. 模型优化 / Model Optimization

### 5.1 量化类型 / Quantization Types

AinosOS 支持以下量化类型，定义在 `D:/Ainos/system-services/ai-daemon/src/runtime.rs` 的 `QuantizationType` 枚举中：

```rust
/// 量化类型
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum QuantizationType {
    Q4_0,  // 4-bit 块量化 (v1)
    Q4_1,  // 4-bit 块量化 (v1, 带偏移)
    Q5_0,  // 5-bit 块量化 (v1)
    Q5_1,  // 5-bit 块量化 (v1, 带偏移)
    Q8_0,  // 8-bit 块量化 (v1)
    F16,   // 半精度浮点 (16-bit)
    F32,   // 全精度浮点 (32-bit)
}
```

### 5.2 量化大小倍数 / Quantization Size Multipliers

不同量化类型相对于 FP32 的模型大小倍数：

| 量化类型 / Type | 大小倍数 / Multiplier | 说明 / Description |
|-----------------|----------------------|-------------------|
| `Q4_0` | 0.25 (25%) | 4-bit 块量化，最小体积 |
| `Q4_1` | 0.28 (28%) | 4-bit 块量化，带偏移，略高精度 |
| `Q5_0` | 0.31 (31%) | 5-bit 块量化，精度/体积均衡 |
| `Q5_1` | 0.35 (35%) | 5-bit 块量化，带偏移 |
| `Q8_0` | 0.50 (50%) | 8-bit 块量化，较高精度 |
| `F16` | 0.50 (50%) | 半精度浮点，无精度损失 |
| `F32` | 1.00 (100%) | 全精度浮点，完整精度 |

```rust
// 大小倍数实现
pub fn size_multiplier(&self) -> f32 {
    match self {
        Self::Q4_0 => 0.25,
        Self::Q4_1 => 0.28,
        Self::Q5_0 => 0.31,
        Self::Q5_1 => 0.35,
        Self::Q8_0 => 0.50,
        Self::F16 => 0.50,
        Self::F32 => 1.0,
    }
}
```

示例：一个 FP32 格式 7GB 的模型使用不同量化后的大小：

| 量化类型 | 模型大小 |
|---------|---------|
| Q4_0 | 1.75 GB |
| Q4_1 | 1.96 GB |
| Q5_0 | 2.17 GB |
| Q5_1 | 2.45 GB |
| Q8_0 | 3.50 GB |
| F16 | 3.50 GB |
| F32 | 7.00 GB |

### 5.3 选择量化级别 / Choosing the Right Quantization Level

选择量化级别的建议：

| 场景 / Scenario | 推荐量化 / Recommended | 原因 / Reason |
|----------------|----------------------|--------------|
| 生产环境，CPU 推理 | `Q4_0` 或 `Q4_K_M` | 最佳体积/质量比，内存占用低 |
| 需要更高精度 | `Q8_0` | 8-bit 量化，几乎无精度损失 |
| 开发测试 | `Q4_0` | 快速加载，足够用于测试 |
| 内存受限设备 | `Q4_0` | 最小内存占用 |
| 高性能服务器 | `F16` 或 `Q8_0` | 最高精度，充足内存 |
| 研究用途 | `F32` | 完整精度，无量化误差 |

### 5.4 电源策略对精度的影响 / Power Policy Impact on Precision

AinosOS 的电源策略会根据 CPU 温度自动调整推理精度：

| 电源模式 / Power Mode | 温度区间 / Temp Range | 精度 / Precision | 向量宽度 / Vector Width | 线程数 / Threads |
|----------------------|---------------------|-----------------|------------------------|-----------------|
| **MAX** (全速) | < 70°C (COOL) | FP32 | AVX-256 | 4 |
| **BALANCED** (平衡) | 70-85°C (WARM) | FP16 | AVX-128 | 2 |
| **EFFICIENT** (节能) | 85-95°C (HOT) | INT8 | NEON/SCALAR | 1 |
| **EMERGENCY** (紧急) | > 95°C (CRITICAL) | INT4 | SCALAR | 1 |

```cpp
// 来自 D:/Ainos/ai-runtime/power-policy/power_policy.cpp
// 温度阈值定义
double cool_warm_threshold = 70.0;    // COOL -> WARM
double warm_hot_threshold = 85.0;     // WARM -> HOT
double hot_critical_threshold = 95.0; // HOT -> CRITICAL
```

可以通过 `OverrideMode` 手动覆盖电源策略，强制使用特定精度模式：

```cpp
// 手动覆盖为全速模式
power_policy->OverrideMode(PrecisionMode::MAX);

// 清除手动覆盖，恢复自动温控
power_policy->ClearOverride();
```

### 5.5 内存优化 / Memory Optimization

AinosOS 提供多级缓存机制来优化内存使用：

#### 模型缓存 / Model Cache

模型缓存由 `ModelManager` 管理，默认最大加载 10 个模型，总内存限制为 8 GB：

```cpp
// 来自 D:/Ainos/ai-runtime/model-manager/model_manager.cpp
ModelManager()
    : max_loaded_models_(10)
    , total_memory_limit_(8ULL * 1024 * 1024 * 1024) // 8GB
    , current_memory_usage_(0) {
    // ...
}
```

当内存使用超过总限制的 80% 时，自动触发 LRU 淘汰：

```cpp
while (current_memory_usage_ > total_memory_limit_ * 0.8) {
    auto status = EvictLRUModel();
    if (status != Status::OK) break;
}
```

#### 上下文缓存 / Context Cache

上下文管理器（`D:/Ainos/ai-runtime/context-manager/context_manager.cpp`）管理 KV 缓存，默认最大支持 100 个上下文：

```cpp
ContextManager()
    : max_contexts_(100)
    , cache_directory_("./context_cache") {}
```

超过限制时自动淘汰最旧的上下文：

```cpp
if (contexts_.size() >= max_contexts_) {
    EvictOldestContext();
}
```

#### 语义缓存 / Semantic Cache

语义缓存（`D:/Ainos/system-services/ai-daemon/src/cache.rs`）缓存推理结果，使用 LRU 淘汰策略，最大容量 1000 条：

```rust
pub struct SemanticCache {
    cache: std::sync::Mutex<lru::LruCache<u64, String>>,
    hits: std::sync::atomic::AtomicU64,
    misses: std::sync::atomic::AtomicU64,
}

impl SemanticCache {
    pub fn new() -> Self {
        Self::with_capacity(1000) // 默认最大容量 1000
    }
}
```

缓存键为 `(prompt, model, temperature)` 的组合哈希，其中 `temperature` 使用定点量化以避免浮点精度问题：

```rust
pub fn compute_key(prompt: &str, model: &str, temperature: f64) -> u64 {
    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    prompt.hash(&mut hasher);
    model.hash(&mut hasher);
    let temp_quantized = (temperature * 1000.0) as i64;
    temp_quantized.hash(&mut hasher);
    hasher.finish()
}
```

### 5.6 GPU 加速 / GPU Acceleration

AinosOS 支持 GPU 加速，通过 feature flags 控制：

```rust
// Feature flags:
// - `ggml`: 启用真实 GGML FFI 推理
// - `onnx`: 启用 ONNX Runtime 集成
// - `cuda`: 启用 CUDA GPU 加速
// - `vulkan`: 启用 Vulkan GPU 加速
```

在 `Cargo.toml` 中启用功能：

```toml
[features]
default = ["ggml"]
cuda = ["ggml/cuda"]
vulkan = ["ggml/vulkan"]
onnx = []
```

启用 GPU 加速后，推理引擎会优先使用 GPU 设备：

```rust
// 根据设备类型和 feature flags 选择推理后端
#[cfg(feature = "cuda")]
let device = DeviceType::GPU;
```

### 5.7 向量加速 / Vector Acceleration

AinosOS 内核模块 `D:/Ainos/kernel/ai-vector-accel-main.c` 提供 CPU 向量指令加速，支持以下指令集：

| 架构 / Architecture | 指令集 / ISA | 状态 / Status |
|-------------------|-------------|--------------|
| **x86-64** | AVX2 | 稳定 |
| **x86-64** | AVX-512 (AVX512F, AVX512_VNNI) | 稳定 |
| **x86-64** | AMX (AMX-TILE, AMX-BF16) | 实验性 |
| **x86-64** | F16C | 稳定 |
| **x86-64** | SSSE3 | 稳定 |
| **ARM64** | NEON | 始终可用 |
| **ARM64** | SVE | 可用 |
| **ARM64** | SVE2 | 可用 |
| **ARM64** | I8MM (Int8 Matrix Multiply) | 可用 |

运行时 CPU 特性自动检测：

```c
// 来自 D:/Ainos/kernel/ai-vector-accel-main.c
static void detect_cpu_features(void) {
    #ifdef CONFIG_X86
    has_avx2 = boot_cpu_has(X86_FEATURE_AVX2);
    has_avx512 = boot_cpu_has(X86_FEATURE_AVX512F);
    has_avx512_vnni = boot_cpu_has(X86_FEATURE_AVX512_VNNI);
    has_amx = boot_cpu_has(X86_FEATURE_AMX_TILE);
    has_amx_bf16 = boot_cpu_has(X86_FEATURE_AMX_BF16);
    #elif defined(CONFIG_ARM64)
    has_neon = 1; /* ARM64 始终有 NEON */
    has_sve = system_supports_sve();
    has_sve2 = system_supports_sve2();
    #endif
}
```

向量加速模块提供以下操作：
- 矩阵乘法加速（SGEMM）
- 向量点积加速
- 量化/反量化加速
- 激活函数加速
- 运行时 CPU 特性检测与最优实现自动选择
- 启动时基准测试

### 5.8 性能基准 / Performance Benchmarks

AinosOS 提供 `D:/Ainos/scripts/benchmark.py` 性能基准测试脚本：

```bash
# 运行完整基准测试
python benchmark.py

# 只测试推理吞吐量
python benchmark.py --inference-only

# 只测试延迟
python benchmark.py --latency-only

# 指定目标地址
python benchmark.py --target 10.0.0.1:9500

# 输出到文件
python benchmark.py --output results.json --inference-only
```

基准测试结果包括：
- **延迟统计**: 最小值、最大值、均值、中位数、P95、P99、标准差
- **吞吐量**: 每秒处理的推理请求数
- **往返时间**: IPC 消息的往返延迟

### 5.9 批处理考虑 / Batch Processing Considerations

批处理大小受电源策略影响：

| 电源模式 | 批处理大小 | 适用场景 |
|---------|-----------|---------|
| MAX | 8 | 高吞吐量，大量并发请求 |
| BALANCED | 4 | 常规工作负载 |
| EFFICIENT | 2 | 节能模式，减少能耗 |
| EMERGENCY | 1 | 紧急降频，单请求处理 |

批处理优化建议：
1. **合并小请求**: 将多个小推理请求合并为批处理
2. **动态批处理**: 等待短时间（如 10ms）收集请求
3. **监控内存**: 大批处理会增加 KV 缓存内存占用
4. **调整线程数**: 批处理大小与线程数成正比

---

## 6. 模型列表与状态 / Model List and Status

### 6.1 通过 IPC 列出可用模型 / Listing Available Models via IPC

客户端通过发送 `ModelList` 消息查询所有可用模型：

**请求 / Request**:

```json
{
  "type": "ModelList"
}
```

**响应 / Response**:

```json
{
  "type": "ModelListResponse",
  "models": [
    {
      "id": "qwen2_5-0_5b-instruct-q4_0_gguf",
      "name": "qwen2.5-0.5b-instruct-q4_0.gguf",
      "path": "D:\\Ainos\\models\\qwen2.5-0.5b-instruct-q4_0.gguf",
      "size_mb": 412,
      "loaded": true,
      "architecture": "auto"
    },
    {
      "id": "phi_3_mini_4k_instruct_q4_gguf",
      "name": "phi-3-mini-4k-instruct-q4.gguf",
      "path": "D:\\Ainos\\models\\phi-3-mini-4k-instruct-q4.gguf",
      "size_mb": 2100,
      "loaded": false,
      "architecture": "auto"
    }
  ]
}
```

### 6.2 ModelInfo 字段说明 / ModelInfo Fields

| 字段 / Field | 类型 / Type | 描述 / Description |
|-------------|-------------|-------------------|
| `id` | string | 唯一模型标识符（如 `"qwen2_5-0_5b-instruct-q4_0_gguf"`） |
| `name` | string | 人类可读的模型名称（如 `"qwen2.5-0.5b-instruct-q4_0.gguf"`） |
| `path` | string | 模型文件的绝对路径 |
| `size_mb` | u64 | 模型文件大小（MB） |
| `loaded` | bool | 模型是否已加载到内存 |
| `architecture` | string | 模型架构字符串（如 `"auto"`、`"phi3"`、`"llama"`、`"onnx"`） |

### 6.3 检查已加载的模型 / Checking Loaded Models

通过 `Status` 消息可以查询系统状态，包括已加载模型的数量：

**请求 / Request**:

```json
{
  "type": "Status"
}
```

**响应 / Response**:

```json
{
  "type": "StatusResponse",
  "uptime": 3600,
  "models_loaded": 2,
  "total_requests": 1500,
  "network_available": true,
  "active_sessions": 3,
  "rate_limits": [
    {
      "category": "inference",
      "limit": 100,
      "remaining": 85,
      "reset_seconds": 30
    }
  ]
}
```

### 6.4 系统状态字段说明 / System Status Fields

| 字段 / Field | 类型 / Type | 描述 / Description |
|-------------|-------------|-------------------|
| `uptime` | u64 | 守护进程运行时间（秒） |
| `models_loaded` | u32 | 当前已加载的模型数量 |
| `total_requests` | u64 | 总推理请求数 |
| `network_available` | bool | 网络是否可用 |
| `active_sessions` | u32 | 当前活跃会话数 |
| `rate_limits` | array | 当前会话的速率限制状态 |

### 6.5 在 Python SDK 中查询 / Querying in Python SDK

```python
import socket
import json

def list_models(host="127.0.0.1", port=9500) -> dict:
    """列出所有可用模型"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10)
    try:
        s.connect((host, port))
        s.sendall((json.dumps({"type": "ModelList"}) + "\n").encode("utf-8"))
        resp = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
            if b"\n" in resp:
                break
        result = json.loads(resp.decode("utf-8").strip())
        return result
    finally:
        s.close()

def get_status(host="127.0.0.1", port=9500) -> dict:
    """查询系统状态"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10)
    try:
        s.connect((host, port))
        s.sendall((json.dumps({"type": "Status"}) + "\n").encode("utf-8"))
        resp = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
            if b"\n" in resp:
                break
        result = json.loads(resp.decode("utf-8").strip())
        return result
    finally:
        s.close()

# 使用示例
models = list_models()
print(f"Found {len(models['models'])} models:")
for m in models['models']:
    status = "loaded" if m['loaded'] else "available"
    print(f"  [{status}] {m['name']} ({m['size_mb']} MB)")

status = get_status()
print(f"\nSystem status:")
print(f"  Uptime: {status['uptime']} seconds")
print(f"  Models loaded: {status['models_loaded']}")
print(f"  Total requests: {status['total_requests']}")
print(f"  Network: {'available' if status['network_available'] else 'unavailable'}")
```

### 6.6 在 Go SDK 中查询 / Querying in Go SDK

```go
package main

import (
    "context"
    "fmt"
    "log"
    "github.com/ainos-os/ainos-sdk-go"
)

func main() {
    client := ainos.NewClient()
    if err := client.Connect(); err != nil {
        log.Fatal(err)
    }
    defer client.Disconnect()

    // 列出模型
    models, err := client.ListModels(context.Background())
    if err != nil {
        log.Fatal(err)
    }
    fmt.Printf("Found %d models:\n", len(models))
    for _, m := range models {
        status := "loaded"
        if !m.Loaded {
            status = "available"
        }
        fmt.Printf("  [%s] %s (%d MB) - %s\n", status, m.Name, m.SizeMB, m.Architecture)
    }

    // 查询状态
    status, err := client.Status(context.Background())
    if err != nil {
        log.Fatal(err)
    }
    fmt.Printf("\nSystem status:\n")
    fmt.Printf("  Uptime: %d seconds\n", status.Uptime)
    fmt.Printf("  Models loaded: %d\n", status.ModelsLoaded)
    fmt.Printf("  Total requests: %d\n", status.TotalRequests)
}
```

Go SDK 中 `ListModels` 和 `Status` 方法的实现（来自 `D:/Ainos/bindings/go/ainos/client.go`）：

```go
// ListModels 列出所有可用模型
func (c *Client) ListModels(ctx context.Context) ([]ModelInfo, error) {
    resp, err := c.sendRequest(ctx, &Request{Type: msgTypeModelList})
    if err != nil {
        return nil, err
    }
    var listResp ModelListResponse
    if err := json.Unmarshal(resp, &listResp); err != nil {
        return nil, fmt.Errorf("parse response: %w", err)
    }
    return listResp.Models, nil
}

// Status 查询系统状态
func (c *Client) Status(ctx context.Context) (*StatusResponse, error) {
    resp, err := c.sendRequest(ctx, &Request{Type: msgTypeStatus})
    if err != nil {
        return nil, err
    }
    var statusResp StatusResponse
    if err := json.Unmarshal(resp, &statusResp); err != nil {
        return nil, fmt.Errorf("parse response: %w", err)
    }
    return &statusResp, nil
}
```

### 6.7 在 Rust SDK 中查询 / Querying in Rust SDK

```rust
use ainos_sdk::AinosClient;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let client = AinosClient::new("127.0.0.1:9500")?;
    client.connect().await?;

    // 列出模型
    let models = client.list_models().await?;
    println!("Found {} models:", models.len());
    for m in &models {
        let status = if m.loaded { "loaded" } else { "available" };
        println!("  [{}] {} ({} MB) - {}", status, m.name, m.size_mb, m.architecture);
    }

    // 查询状态
    let status = client.status().await?;
    println!("\nSystem status:");
    println!("  Uptime: {} seconds", status.uptime);
    println!("  Models loaded: {}", status.models_loaded);
    println!("  Total requests: {}", status.total_requests);

    client.disconnect().await?;
    Ok(())
}
```

### 6.8 在 Node.js SDK 中查询 / Querying in Node.js SDK

```typescript
import { AinosClient } from 'ainos-sdk';

async function main() {
    const client = new AinosClient({
        host: '127.0.0.1',
        port: 9500,
    });

    await client.connect();

    // 列出模型
    const models = await client.listModels();
    console.log(`Found ${models.length} models:`);
    for (const m of models) {
        const status = m.loaded ? 'loaded' : 'available';
        console.log(`  [${status}] ${m.name} (${m.sizeMb} MB) - ${m.architecture}`);
    }

    // 查询状态
    const status = await client.status();
    console.log('\nSystem status:');
    console.log(`  Uptime: ${status.uptime} seconds`);
    console.log(`  Models loaded: ${status.modelsLoaded}`);
    console.log(`  Total requests: ${status.totalRequests}`);

    await client.disconnect();
}

main().catch(console.error);
```

---

## 7. 模型卸载 / Model Unloading

### 7.1 通过 IPC 手动卸载 / Manual Unloading via IPC

客户端通过发送 `ModelUnload` 消息卸载模型：

**请求 / Request**:

```json
{
  "type": "ModelUnload",
  "model_id": "qwen2_5-0_5b-instruct-q4_0_gguf"
}
```

**响应 / Response**:

```json
{
  "type": "ModelUnloadResponse",
  "model_id": "qwen2_5-0_5b-instruct-q4_0_gguf",
  "status": "unloaded",
  "message": "Model 'qwen2_5-0_5b-instruct-q4_0_gguf' unloaded successfully"
}
```

**错误响应 / Error Response**:

```json
{
  "type": "ModelUnloadResponse",
  "model_id": "unknown_model",
  "status": "not_found",
  "message": "Model 'unknown_model' is not loaded"
}
```

### 7.2 ModelUnload 请求字段说明 / ModelUnload Request Fields

| 字段 / Field | 类型 / Type | 必需 / Required | 描述 / Description |
|-------------|-------------|----------------|-------------------|
| `type` | string | 是 | 固定为 `"ModelUnload"` |
| `model_id` | string | 是 | 要卸载的模型标识符 |

### 7.3 ModelUnloadResponse 字段说明 / ModelUnloadResponse Fields

| 字段 / Field | 类型 / Type | 描述 / Description |
|-------------|-------------|-------------------|
| `model_id` | string | 模型标识符 |
| `status` | string | 卸载状态：`"unloaded"`、`"not_found"`、`"error"` |
| `message` | string | 人类可读的状态消息 |

### 7.4 卸载处理逻辑 / Unloading Logic

`handle_model_unload` 函数（位于 `D:/Ainos/system-services/ai-daemon/src/ipc.rs`）按以下步骤处理卸载请求：

1. **检查加载状态**: 验证模型是否已加载
2. **调用 ModelRegistry::unload**: 从 `loaded` 映射中移除
3. **更新 LRU 顺序**: 从 `lru_order` 列表中移除
4. **记录审计日志**: 记录卸载操作到审计日志
5. **释放内存**: 引擎释放模型占用的内存

```rust
// 来自 D:/Ainos/system-services/ai-daemon/src/models.rs
pub fn unload(&mut self, model_id: &str) -> Result<(), String> {
    if self.loaded.remove(model_id).is_some() {
        self.lru_order.retain(|id| id != model_id);
        info!("Model unloaded: {}", model_id);
        Ok(())
    } else {
        Err(format!("Model not loaded: {}", model_id))
    }
}
```

### 7.5 自动卸载（LRU 淘汰） / Automatic Unloading (LRU Eviction)

当内存使用超过阈值时，系统自动驱逐最久未使用的模型。

在 C++ Runtime 层（`D:/Ainos/ai-runtime/model-manager/model_manager.cpp`）：

```cpp
Status EvictLRUModel() {
    if (models_.empty()) {
        return Status::OK;
    }

    // 找到最少访问且已加载的模型
    std::string lru_model_id;
    int64_t oldest_time = std::numeric_limits<int64_t>::max();

    for (const auto& entry : models_) {
        if (entry.second.is_loaded && entry.second.last_access_time < oldest_time) {
            oldest_time = entry.second.last_access_time;
            lru_model_id = entry.first;
        }
    }

    if (!lru_model_id.empty()) {
        return UnloadModel(lru_model_id);
    }

    return Status::OK;
}
```

在 Rust 守护进程层（`D:/Ainos/system-services/ai-daemon/src/models.rs`），`ModelRegistry` 维护 LRU 顺序列表：

```rust
/// 模型缓存最近使用
lru_order: Vec<String>,
```

### 7.6 内存回收 / Memory Reclamation

模型卸载后的内存回收机制：

1. **直接内存释放**: 卸载时立即释放模型权重和 KV 缓存占用的内存
2. **内存优化**: 定期调用 `OptimizeMemory` 方法，卸载长时间未访问的模型（默认 1 小时空闲阈值）
3. **内存统计**: 跟踪 `current_memory_usage_`，确保总内存使用不超过限制

```cpp
// 来自 D:/Ainos/ai-runtime/model-manager/model_manager.cpp
Status OptimizeMemory() override {
    std::lock_guard<std::mutex> lock(mutex_);

    // 卸载长时间未访问的模型
    int64_t current_time = std::chrono::system_clock::now().time_since_epoch().count();
    int64_t idle_threshold = 3600LL * 1000 * 1000 * 1000; // 1小时

    std::vector<std::string> to_unload;
    for (const auto& entry : models_) {
        if (entry.second.is_loaded &&
            (current_time - entry.second.last_access_time) > idle_threshold) {
            to_unload.push_back(entry.first);
        }
    }

    for (const auto& model_id : to_unload) {
        UnloadModel(model_id);
    }

    return Status::OK;
}
```

### 7.7 在 Python SDK 中卸载 / Unloading in Python SDK

```python
import socket
import json

def unload_model(model_id: str, host="127.0.0.1", port=9500) -> dict:
    """卸载模型"""
    msg = {"type": "ModelUnload", "model_id": model_id}
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10)
    try:
        s.connect((host, port))
        s.sendall((json.dumps(msg) + "\n").encode("utf-8"))
        resp = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
            if b"\n" in resp:
                break
        return json.loads(resp.decode("utf-8").strip())
    finally:
        s.close()

# 使用示例
result = unload_model("qwen2_5-0_5b-instruct-q4_0_gguf")
print(f"Status: {result['status']}")
print(f"Message: {result['message']}")
```

### 7.8 在 Go SDK 中卸载 / Unloading in Go SDK

```go
package main

import (
    "context"
    "fmt"
    "log"
    "github.com/ainos-os/ainos-sdk-go"
)

func main() {
    client := ainos.NewClient()
    if err := client.Connect(); err != nil {
        log.Fatal(err)
    }
    defer client.Disconnect()

    // 卸载模型
    result, err := client.UnloadModel(context.Background(), &ainos.ModelUnloadRequest{
        ModelID: "qwen2_5-0_5b-instruct-q4_0_gguf",
    })
    if err != nil {
        log.Fatal(err)
    }

    fmt.Printf("Model ID: %s\n", result.ModelID)
    fmt.Printf("Status: %s\n", result.Status)
    fmt.Printf("Message: %s\n", result.Message)
}
```

Go SDK 类型定义：

```go
// 来自 D:/Ainos/bindings/go/ainos/types.go
type ModelUnloadRequest struct {
    ModelID string `json:"model_id"`
}

type ModelUnloadResponse struct {
    ModelID string `json:"model_id"`
    Status  string `json:"status"`
    Message string `json:"message"`
}
```

### 7.9 在 Rust SDK 中卸载 / Unloading in Rust SDK

```rust
use ainos_sdk::AinosClient;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let client = AinosClient::new("127.0.0.1:9500")?;
    client.connect().await?;

    // 卸载模型
    let response = client.unload_model("qwen2_5-0_5b-instruct-q4_0_gguf").await?;

    println!("Model ID: {}", response.model_id);
    println!("Status: {}", response.status);
    println!("Message: {}", response.message);

    client.disconnect().await?;
    Ok(())
}
```

### 7.10 在 Node.js SDK 中卸载 / Unloading in Node.js SDK

```typescript
import { AinosClient } from 'ainos-sdk';

async function main() {
    const client = new AinosClient({
        host: '127.0.0.1',
        port: 9500,
    });

    await client.connect();

    // 卸载模型
    const response = await client.unloadModel({
        modelId: 'qwen2_5-0_5b-instruct-q4_0_gguf',
    });

    console.log(`Model ID: ${response.modelId}`);
    console.log(`Status: ${response.status}`);
    console.log(`Message: ${response.message}`);

    await client.disconnect();
}

main().catch(console.error);
```

---

## 8. 最佳实践 / Best Practices

### 8.1 生产环境使用量化模型 / Use Quantized Models for Production

对于生产环境，始终使用量化模型（推荐 Q4_0 或 Q8_0）：

- **Q4_0**: 最佳体积/质量比，适合大多数场景
- **Q8_0**: 几乎无损精度，适合需要高精度的场景
- 避免在生产环境中使用 F32 模型，除非有特殊需求

```bash
# 下载 Q4_0 量化模型用于生产
python download_model.py --known qwen2.5-0.5b --quantization q4_0

# 下载 Q8_0 量化模型用于高精度场景
python download_model.py --known qwen2.5-0.5b --quantization q8_0
```

### 8.2 监控模型缓存大小 / Monitor Model Cache Size

定期检查模型缓存使用情况，确保不超过可用内存：

```python
def check_cache_status(host="127.0.0.1", port=9500):
    """检查模型缓存状态"""
    status = get_status(host, port)
    models = list_models(host, port)['models']

    loaded_size = sum(m['size_mb'] for m in models if m['loaded'])
    loaded_count = sum(1 for m in models if m['loaded'])

    print(f"Loaded models: {loaded_count}")
    print(f"Total loaded size: {loaded_size} MB / {status.get('cache_limit', 'N/A')} MB")

    if loaded_size > 3072:  # 超过 3GB 发出警告
        print("WARNING: High memory usage, consider unloading unused models")
```

### 8.3 延迟敏感应用预加载模型 / Pre-load Models for Latency-Sensitive Applications

对于需要低延迟响应的应用，建议在服务启动时预加载模型：

```python
# 应用启动时预加载模型
def preload_models(model_paths: list, host="127.0.0.1", port=9500):
    """预加载模型以减少首次推理延迟"""
    for path in model_paths:
        result = load_model(path, host, port)
        if result['status'] == 'loaded' or result['status'] == 'already_loaded':
            print(f"Model ready: {result['model_id']}")
        else:
            print(f"Failed to load {path}: {result['message']}")
```

### 8.4 及时卸载不使用的模型 / Unload Unused Models

在应用不再需要某个模型时，及时卸载以释放内存：

```python
def cleanup_models(keep: list = None, host="127.0.0.1", port=9500):
    """卸载除 keep 列表外的所有已加载模型"""
    keep = keep or []
    models = list_models(host, port)['models']

    for m in models:
        if m['loaded'] and m['id'] not in keep:
            result = unload_model(m['id'], host, port)
            if result['status'] == 'unloaded':
                print(f"Unloaded: {m['name']} (freed {m['size_mb']} MB)")
```

### 8.5 定期更新模型 / Regular Model Updates

保持模型更新以获得更好的性能和准确性：

```bash
# 定期检查并更新模型
python download_model.py --known qwen2.5-0.5b --quantization q4_0

# 使用脚本定期更新（可配置 cron 任务）
# 0 2 * * 0 cd /D/Ainos && python scripts/download_model.py --known qwen2.5-0.5b --quantization q4_0
```

### 8.6 模型版本管理 / Model Versioning

建议使用以下策略管理模型版本：

1. **文件名包含版本信息**: 如 `qwen2.5-0.5b-instruct-v2-q4_0.gguf`
2. **维护模型清单**: 使用 `model_manifest.json` 记录模型来源和版本
3. **保留旧版本**: 在升级模型时保留至少一个旧版本用于回退
4. **使用语义化版本**: 为自定义模型分配语义化版本号

### 8.7 备份模型文件 / Backup Model Files

模型文件备份建议：

```bash
# 备份模型目录
tar -czf models_backup_$(date +%Y%m%d).tar.gz -C D:/Ainos/models .

# 或 rsync 到远程备份位置
rsync -avz D:/Ainos/models/ backup-server:/ainos-models-backup/
```

### 8.8 性能优化清单 / Performance Optimization Checklist

- [ ] 使用 Q4_0 量化模型减少内存占用
- [ ] 为延迟敏感应用预加载模型
- [ ] 卸载不使用的模型以释放内存
- [ ] 监控模型缓存大小，确保在物理内存限制内
- [ ] 启用 GPU 加速（如果可用硬件支持）
- [ ] 检查 CPU 向量指令集支持（AVX2、AVX-512、NEON）
- [ ] 根据工作负载调整并发推理数
- [ ] 使用语义缓存减少重复推理
- [ ] 定期更新模型到最新版本
- [ ] 备份重要模型文件
- [ ] 使用模型配置文件精确控制每模型参数
- [ ] 监控电源策略状态，避免温度过高导致降频

---

> 本文档基于 AinosOS 代码库（D:/Ainos）的实际代码编写。如需了解更多信息，请参考相关源代码文件或架构文档。
>
> This document is based on the actual AinosOS codebase (D:/Ainos). For more information, please refer to the relevant source code files or architecture documentation.