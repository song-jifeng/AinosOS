# Ainos OS — AI 原生操作系统

<p align="center">
  <img src="https://img.shields.io/badge/version-0.2.0-blue" alt="Version">
  <img src="https://img.shields.io/badge/license-MIT%20%7C%20GPL--2.0-green" alt="License">
  <img src="https://img.shields.io/badge/status-development-yellow" alt="Status">
  <img src="https://img.shields.io/badge/Rust-1.77+-orange" alt="Rust">
  <img src="https://img.shields.io/badge/C%2B%2B-17-blue" alt="C++">
</p>

<p align="center">
  <b>AI 是系统服务，不是应用——将 AI 深度集成到操作系统内核</b>
</p>

---

## 🌟 愿景

Ainos OS 是一个 AI 原生操作系统，核心理念是：**AI 不是系统上的一个应用，而是系统本身的基础设施**。

就像现代操作系统把网络、图形、文件系统作为内核服务一样，Ainos OS 把 AI 推理能力深度集成到系统每一层——从内核调度器到用户空间 SDK，AI 无处不在。

### 设计原则

- **离线优先** — AI 推理在本地运行，不依赖云端
- **AI 即服务** — 通过系统级 IPC 访问 AI 能力，无需集成第三方 SDK
- **温控感知** — 电源策略根据 CPU 温度自动调整推理精度（自适应轮询）
- **跨平台** — 同一套架构，Windows 和 Linux 双平台支持
- **安全边界** — 内核模块 GPL 与用户空间 MIT 明确分离

---

## 🏗️ 架构总览

```
用户空间应用 / SDK
  - C SDK (libainos.a)
  - Python SDK (ainos-sdk, TCP IPC)
  - Web App (HTTP 桥接)
        |
        ▼
AI 守护进程 (ai-daemon)
  - IPC 服务 (TCP/Unix, 支持 TLS)
  - 推理路由 (本地↔云端)
  - 上下文管理 (SQLite 持久化)
  - 语义缓存 (LRU 1000条)
  - 模型管理 (加载/卸载)
  - 自适应温控策略调度 (0.5s-10s 动态轮询)
        |
        ▼
AI Runtime 层
  - GGML 推理引擎 (本地模型推理)
  - ONNX Runtime 服务 (可选)
  - 模型管理器 (注册/加载/卸载)
  - 上下文管理器 (创建/保存/恢复)
  - Power Policy 电源策略管理器 (温度监控/精度降级/线程控制)
        |
        ▼
内核层 (Linux)
  - AI 调度器 (进程优先级 + 5 级队列)
  - AI 系统调用 (ioctl/fs, 10 个系统调用)
  - AI 文件系统 (ai-fs, FUSE)
  - AI 安全策略 (ai-policy, Capability-based)
  - 内核自愈 (self-heal)
  - AI KILL 进程管理器
  - AI tmpfs 智能文件系统
  - AI readahead 智能预读
  - Hotpatch 热补丁生成器
```

---

## 🎯 核心模块

### 1. AI 守护进程 (ai-daemon)

用 Rust 编写的核心后台服务，使用 tokio 异步运行时，提供：

- **IPC 通信** — TCP（跨平台）/ Unix Domain Socket（Linux），支持 TLS 加密
- **推理路由** — 自动选择本地 GGML 引擎或云端 API
- **上下文管理** — 会话级键值存储，支持 SQLite 持久化
- **语义缓存** — LRU 缓存推理结果，减少重复计算（1000 条容量）
- **模型管理** — 加载/卸载/列表查询
- **自适应温控调度** — 温度变化剧烈时 0.5s 采样，稳定时 10s 采样，支持 inotify 事件驱动
- **统计监控** — 原子计数器，零锁统计

四种电源策略模式：

| 模式 | 温度 | 线程 | 精度 | 向量宽度 | 延迟 |
|------|------|------|------|----------|------|
| MAX | <70°C | 4 核 | FP32 | AVX-256 | 5ms |
| BALANCED | 70-85°C | 2 核 | FP16 | AVX-128 | 10ms |
| EFFICIENT | 85-95°C | 1 核 | INT8 | NEON | 20ms |
| EMERGENCY | >95°C | 1 核 | INT4 | SCALAR | 40ms |

### 2. AI Runtime (ai-runtime)

C++17 编写的运行时层，包含：

- **GGML 引擎** — 本地模型加载与推理，电源策略感知，支持流式推理
- **ONNX Service** — 可选 ONNX Runtime 后端
- **模型管理器** — 模型注册、加载、卸载、内存优化
- **上下文管理器** — 上下文创建、保存、加载、过期清理
- **Power Policy 管理器** — 自适应温控监控，自动/手动模式切换，防频繁跳变冷却保护

### 3. C SDK (libainos)

纯 C 编写的客户端库，提供简洁的 API：

```c
ainos_ctx *ctx = ainos_init("127.0.0.1:9500");
ainos_connect(ctx);

ainos_infer_opts opts = AINOS_INFER_OPTS_DEFAULT;
ainos_resp *resp = ainos_infer(ctx, "default", "Hello!", &opts);
printf("AI: %s\n", resp->output);

ainos_destroy(ctx);
```

### 4. Python SDK (ainos-sdk)

纯 Python 编写的客户端库，零外部依赖，支持所有 IPC 操作：

```python
from ainos import AinosClient

client = AinosClient("127.0.0.1", 9500)
client.connect()

resp = client.infer("Hello!", model="default")
print(f"AI: {resp.output}")

client.disconnect()
```

### 5. 内核模块 (Linux)

- **AI 调度器** — 5 级优先级队列，4 个工作线程，看门狗超时保护
- **AI 系统调用** — 10 个系统调用（450-459），ioctl 接口
- **AI 文件系统** — 通过 FUSE 挂载，提供 AI 资源的文件系统视图
- **AI 安全策略** — Capability-based 细粒度访问控制，支持紧急切断
- **内核自愈** — 健康状态监控、僵尸进程恢复、热修复
- **AI KILL** — 基于 7 维评分的智能进程终止
- **AI tmpfs** — 智能文件系统缓存
- **AI readahead** — 智能预读优化
- **Hotpatch** — 热补丁生成器

### 6. AI 工具集 (ai-tools)

- **ai-git** — 语言感知的智能合并引擎，自动化提交信息生成

---

## 🚀 快速开始

### Windows

```bash
# 一键安装
scripts\install.bat

# 或手动启动
cd system-services/ai-daemon
cargo build --release
.\target\release\ai-daemon.exe -c ..\..\configs\ai-daemon.toml -v

# 系统托盘
python scripts\ainos_tray.py

# 运行验收测试
python scripts\verification_test.py

# Web 管理面板
python system-services/web-panel/web_server.py
# 访问 http://127.0.0.1:9501
```

### Linux

```bash
# 一键安装
bash scripts/install.sh

# 或手动启动
cd system-services/ai-daemon
cargo build --release
./target/release/ai-daemon -c ../../configs/ai-daemon.toml -v

# Systemd 服务
sudo systemctl start ai-daemon
sudo systemctl enable ai-daemon
```

### Docker

```bash
docker-compose up -d
# 或
docker build -t ainos-daemon .
docker run -d -p 9500:9500 -v ./models:/var/lib/ainos/models ainos-daemon
```

---

## 📦 模型下载

```bash
# 列出可用模型
python scripts/download_model.py --list

# 下载预配置模型
python scripts/download_model.py --known qwen2.5-0.5b --quantization q4_0

# 从 HuggingFace 下载
python scripts/download_model.py --model Qwen/Qwen2.5-0.5B-Instruct-GGUF
```

---

## 📊 测试与基准

```bash
# 一键运行所有测试
bash scripts/run_tests.sh

# 仅 Rust 测试（76 个）
cd system-services/ai-daemon && cargo test

# 性能基准测试
python scripts/benchmark.py
python scripts/benchmark.py --latency-only --count 100
python scripts/benchmark.py --inference-only --duration 30
```

---

## 🔧 配置

通过 `configs/ai-daemon.toml` 配置守护进程：

```toml
models_dir = "D:\\Ainos\\models"
default_model = "qwen2.5-0.5b-instruct-q4.gguf"
socket_path = "127.0.0.1:9500"

# TLS 加密（可选）
enable_tls = false
tls_cert_path = "certs/server.crt"
tls_key_path = "certs/server.key"
```

支持 `$AINOS_HOME` 环境变量覆盖默认路径。

---

## 📖 API 参考

### IPC 协议（JSON 行协议）

所有请求/响应均为单行 JSON，以 `\n` 分隔。

| 操作 | 说明 | 请求参数 | 响应类型 |
|------|------|----------|----------|
| Status | 系统状态 | - | StatusResponse |
| Inference | 推理请求 | model, prompt, temperature, max_tokens | InferenceResponse |
| ContextStore | 存储上下文 | key, value | InferenceResponse |
| ContextRetrieve | 检索上下文 | key | InferenceResponse / Error |
| ModelList | 模型列表 | - | ModelListResponse |
| ModelLoad | 加载模型 | path | InferenceResponse / Error |
| ModelUnload | 卸载模型 | model_id | InferenceResponse / Error |

---

## 📁 项目结构

```
D:/Ainos/
├── kernel/                          # Linux 内核模块 (GPL-2.0)
│   ├── include/ainos/ai-abi.h      # AI 内核 ABI 定义
│   ├── ai-scheduler-main.c         # AI 调度器
│   ├── ai-self-heal/               # 内核自愈
│   ├── ai-kill/                    # AI KILL 进程管理器
│   ├── ai-tmpfs/                   # 智能文件系统
│   ├── ai-readahead/               # 智能预读
│   ├── ai-proc/                    # Proc 文件系统
│   ├── hotpatch/                   # 热补丁生成器
│   └── Makefile
├── ai-runtime/                      # AI 运行时层 (MIT)
│   ├── include/ainos/              # 公共接口
│   ├── ggml-engine/                # GGML 推理引擎
│   ├── onnx-service/               # ONNX Runtime 服务
│   ├── model-manager/              # 模型管理器
│   ├── context-manager/            # 上下文管理器
│   ├── power-policy/               # 电源策略模块
│   ├── tests/                      # 单元测试
│   └── CMakeLists.txt
├── ai-fs/                           # AI 文件系统 (GPL-2.0)
├── ai-policy/                       # AI 安全策略 (GPL-2.0)
│   ├── enforcer/                   # 策略执行器
│   ├── policy-engine/              # 策略引擎
│   ├── policy-db/                  # 策略数据库
│   └── include/ainos/ai_policy.h   # 公共头文件
├── system-services/                 # 系统服务层 (MIT)
│   ├── ai-daemon/                  # AI 守护进程 (Rust)
│   │   ├── src/
│   │   │   ├── main.rs             # 入口 + 状态管理
│   │   │   ├── ipc.rs              # IPC 通信 (12函数文档)
│   │   │   ├── config.rs           # 配置管理 ($AINOS_HOME)
│   │   │   ├── models.rs           # 模型注册表
│   │   │   ├── runtime.rs          # 运行时管理
│   │   │   ├── context.rs          # 上下文管理 (SQLite)
│   │   │   ├── thermal.rs          # 自适应温控监控
│   │   │   ├── cache.rs            # 语义缓存 (LRU)
│   │   │   └── tests.rs            # 76 个单元测试
│   │   └── Cargo.toml
│   └── web-panel/                  # Web 管理面板
│       ├── web_server.py           # HTTP 服务器
│       └── index.html              # 单页应用
├── userland/sdk/                    # 用户空间 SDK (MIT)
│   ├── ainos.h                     # C SDK 头文件
│   ├── libainos.c                  # C SDK 实现
│   └── python/                     # Python SDK
│       ├── ainos/client.py         # Python 客户端
│       ├── ainos/models.py         # 数据模型
│       └── setup.py                # pip 安装包
├── ai-tools/                        # AI 工具集 (MIT)
│   └── ai-git/                     # AI Git 增强
├── configs/ai-daemon.toml          # 守护进程配置
├── scripts/                         # 工具脚本
│   ├── install.sh / install.bat    # 一键安装
│   ├── download_model.py           # 模型下载器
│   ├── ainos_tray.py               # 系统托盘
│   ├── register_autostart.py       # 开机自启
│   ├── benchmark.py                # 性能基准测试
│   ├── run_tests.sh                # 一键测试
│   ├── rotate_logs.sh              # 日志轮转
│   └── verification_test.py        # 验收测试
├── docs/                            # 文档
│   ├── adr/                        # 架构决策记录
│   ├── license-boundary.md         # 许可证边界说明
│   └── architecture.md             # 架构文档
└── models/                          # 模型文件目录
```

---

## 🛠️ 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| 守护进程 | Rust 1.77+, Tokio, Serde | 异步 IPC 服务 |
| 运行时 | C++17, CMake | 推理引擎、电源策略 |
| C SDK | C17 (C11) | 客户端库 |
| Python SDK | Python 3.9+ (零依赖) | Python 客户端库 |
| 内核 | C (Linux Kernel) | 调度器、系统调用 |
| 文件系统 | Rust + FUSE | AI 文件系统 |
| 安全策略 | C (双模式: 内核/用户态) | 访问控制 |
| 构建 | Cargo, Make, CMake | 跨平台编译 |
| IPC | TCP / Unix Domain Socket | 进程间通信 |
| 持久化 | SQLite (可选) | 上下文持久化 |
| 缓存 | LRU (1000 条) | 推理结果缓存 |
| AI 模型 | GGUF (GGML) | 本地推理格式 |
| 云端 API | OpenAI 兼容接口 | 云端推理回退 |

---

## 🧪 测试覆盖

| 模块 | 测试数 | 覆盖内容 |
|------|--------|----------|
| 守护进程 | 76 个 | Config、IPC 序列化、推理、缓存、温控、上下文 |
| AI Runtime | 5 个 | 引擎创建、模型管理、上下文管理、电源策略 |
| 验收测试 | 6 个 | 全链路 IPC 操作验证 |

---

## 🗺️ 路线图

### 已完成

- 项目骨架搭建 — 60+ 文件，全平台支持
- AI 守护进程 — Rust 异步 IPC 服务，7 种操作
- C SDK — 跨平台客户端库
- Python SDK — 零依赖 TCP 客户端
- 电源策略调度 — 自适应温控轮询 (0.5s-10s)
- 全链路验收 — 6/6 测试通过 + 76 个单元测试
- 云端 API 集成 — Weelink 平台接入
- 语义缓存 — LRU 1000 条推理结果缓存
- 上下文持久化 — SQLite 存储 (feature flag)
- 内核模块 — 调度器/自愈/AI KILL/tmpfs/readahead/hotpatch
- Capability-based 安全策略 — 细粒度权限控制
- 架构决策记录 — 5 份 ADR 文档
- CI 流水线 — GitHub Actions 构建验证
- 系统托盘 — Windows 托盘管理
- 模型下载器 — HuggingFace 集成
- Web 管理面板 — 5 页面单页应用
- Docker 部署 — 多阶段构建
- 一键安装 — Windows (.bat) + Linux (.sh)

### 进行中

- 编译 AI Runtime (CMake 全模块)
- 集成 llama.cpp 本地推理后端

### 规划中

- GPU 加速 (CUDA/Metal/Vulkan)
- 多模型并发加载
- 插件系统
- 跨平台配置路径标准化
- 性能回归 CI

---

## ⚖️ 许可证

本项目采用**双许可证**策略：

| 目录 | 许可证 | 说明 |
|------|--------|------|
| `kernel/` | GPL-2.0 | Linux 内核模块，遵循内核许可证 |
| `ai-fs/` | GPL-2.0 | FUSE 内核模块 |
| `ai-policy/` | GPL-2.0 | LSM 安全模块 |
| 其余所有 | MIT | 用户空间代码 |

详见 [docs/license-boundary.md](docs/license-boundary.md)。

---

## 👥 开发团队

### 项目维护者

| 角色 | 姓名 | 职责 |
|------|------|------|
| 项目维护者 | song-jifeng | 架构设计、集成协调、代码审查、项目管理 |

### 开发工具

Ainos OS 的代码由以下 AI 模型辅助生成。这些模型是**开发工具**，不作为团队成员署名。

| 工具 | 主要贡献领域 |
|------|-------------|
| GPT-5.6-Sol | 架构设计、接口定义、集成协调 |
| DeepSeek-v4-Pro | 内核模块、AI 调度器、系统调用 |
| Claude-Opus-4-8 | GGML/ONNX 集成、模型管理 |
| Qwen3.7-Plus | 桌面环境、AI 应用框架、SDK |

---

## 🤝 贡献指南

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交改动 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 提交 Pull Request

注意：内核模块修改需遵守 GPL-2.0 许可证。

---

<p align="center">
  <b>Ainos OS — AI 从云到端，从内核到应用</b>
  <br>
  <sub>Making AI an OS-level service, not just an application</sub>
</p>