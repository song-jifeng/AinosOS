# Ainos OS — AI 原生操作系统

AI 是系统服务，不是应用——将 AI 深度集成到操作系统内核

## 愿景

Ainos OS 是一个 AI 原生操作系统，核心理念是：AI 不是系统上的一个应用，而是系统本身的基础设施。

就像现代操作系统把网络、图形、文件系统作为内核服务一样，Ainos OS 把 AI 推理能力深度集成到系统每一层——从内核调度器到用户空间 SDK，AI 无处不在。

### 设计原则

- 离线优先 — AI 推理在本地运行，不依赖云端
- AI 即服务 — 通过系统级 IPC 访问 AI 能力，无需集成第三方 SDK
- 温控感知 — 电源策略根据 CPU 温度自动调整推理精度
- 跨平台 — 同一套架构，Windows 和 Linux 双平台支持

## 架构总览

四层架构：

```
用户空间应用 / SDK
  - C SDK (libainos.a)
  - Python SDK (TCP IPC)
  - Web App (HTTP桥接)
        |
        v
AI 守护进程 (ai-daemon)
  - IPC 服务 (TCP/Unix)
  - 推理路由 (本地↔云端)
  - 上下文管理 (会话持久化)
  - 模型管理 (加载/卸载)
  - 温控策略调度 (4级精度自动切换)
        |
        v
AI Runtime 层
  - GGML 推理引擎 (本地模型推理)
  - Power Policy 电源策略管理器 (温度监控/精度降级/线程控制)
        |
        v
内核层 (Linux)
  - AI 调度器 (进程优先级)
  - AI 系统调用 (ioctl/fs)
  - AI 文件系统 (ai-fs)
  - AI 安全策略 (ai-policy)
```

## 核心模块

### 1. AI 守护进程 (ai-daemon)

用 Rust 编写的核心后台服务，使用 tokio 异步运行时，提供：

- IPC 通信 — TCP（跨平台）/ Unix Domain Socket（Linux）
- 推理路由 — 自动选择本地 GGML 引擎或云端 API
- 上下文管理 — 会话级键值存储，支持持久化
- 模型管理 — 加载/卸载/列表查询
- 温控调度 — 每 2 秒轮询 CPU 温度，自动切换电源策略
- 统计监控 — 原子计数器，零锁统计

四种电源策略模式：

| 模式 | 温度 | 线程 | 精度 | 向量宽度 | 延迟 |
|------|------|------|------|----------|------|
| MAX | <70°C | 4 核 | FP32 | AVX-256 | 5ms |
| BALANCED | 70-85°C | 2 核 | FP16 | AVX-128 | 10ms |
| EFFICIENT | 85-95°C | 1 核 | INT8 | NEON | 20ms |
| EMERGENCY | >95°C | 1 核 | INT4 | SCALAR | 40ms |

### 2. AI Runtime (ai-runtime)

C++ 编写的运行时层，包含：

- GGML 引擎 — 本地模型加载与推理，电源策略感知
- Power Policy 管理器 — 独立温控监控线程，自动/手动模式切换，防频繁跳变冷却保护

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

### 4. 内核模块 (Linux)

- AI 进程调度器 — 基于 AI 负载的进程优先级管理
- AI 系统调用 — ioctl 接口，查询功率模式、设置策略
- AI 文件系统 — 通过 FUSE 挂载，提供 AI 资源的文件系统视图
- AI 安全策略 — 基于路径的 AI 资源访问控制

## 快速开始

### Windows

```bash
# 1. 启动守护进程
cd D:/Ainos/system-services/ai-daemon
./target/release/ai-daemon.exe -c D:/Ainos/configs/ai-daemon.toml -v

# 2. 运行 SDK 测试
cd D:/Ainos/userland/sdk
./ainos_test.exe

# 3. 运行全链路验收
python D:/Ainos/scripts/verification_test.py

# 4. 关闭
taskkill //F //IM ai-daemon.exe
```

### Linux

```bash
# 1. 编译
cd system-services/ai-daemon
cargo build --release

# 2. 启动守护进程
sudo ./target/release/ai-daemon

# 3. 使用 Systemd 服务（可选）
sudo systemctl start ai-daemon
sudo systemctl enable ai-daemon
```

## API 参考

### IPC 协议（JSON 行协议）

所有请求/响应均为单行 JSON，以 \n 分隔。

请求格式：
```json
{"type": "操作类型", "参数1": "值1", ...}
```

支持的操作：

| 操作 | 说明 | 请求参数 | 响应类型 |
|------|------|----------|----------|
| Status | 系统状态 | - | StatusResponse |
| Inference | 推理请求 | model, prompt, temperature, max_tokens | InferenceResponse |
| ContextStore | 存储上下文 | key, value | InferenceResponse |
| ContextRetrieve | 检索上下文 | key | InferenceResponse / Error |
| ModelList | 模型列表 | - | ModelListResponse |
| ModelLoad | 加载模型 | path | InferenceResponse / Error |
| ModelUnload | 卸载模型 | model_id | InferenceResponse / Error |

### C SDK API

```c
ainos_ctx*   ainos_init(const char* server_addr);
int          ainos_connect(ainos_ctx* ctx);
ainos_resp*  ainos_infer(ainos_ctx* ctx, const char* model,
                         const char* prompt, ainos_infer_opts* opts);
ainos_resp*  ainos_get_info(ainos_ctx* ctx);
void         ainos_resp_free(ainos_resp* resp);
void         ainos_destroy(ainos_ctx* ctx);
```

## 项目结构

```
D:/Ainos/
├── kernel/                          # Linux 内核模块
│   ├── include/ainos/ai-abi.h      # AI 内核 ABI 定义
│   ├── ai-scheduler-main.c         # AI 调度器主程序
│   └── Makefile
├── ai-runtime/                      # AI 运行时层
│   ├── include/ainos/
│   │   ├── ai_runtime.h            # 运行时公共接口
│   │   └── power_policy.h          # 电源策略接口
│   ├── ggml-engine/                # GGML 推理引擎
│   ├── power-policy/               # 电源策略模块
│   └── CMakeLists.txt
├── ai-fs/                           # AI 文件系统 (FUSE, Rust)
├── ai-policy/                       # AI 安全策略 (Rust)
├── system-services/                 # 系统服务层
│   └── ai-daemon/                  # AI 守护进程 (Rust)
│       ├── src/
│       │   ├── main.rs             # 入口 + 状态管理
│       │   ├── ipc.rs              # IPC 通信 + 云端 API
│       │   ├── config.rs           # 配置管理
│       │   ├── models.rs           # 模型注册表
│       │   ├── runtime.rs          # 运行时管理
│       │   ├── context.rs          # 上下文管理
│       │   └── thermal.rs          # 温控监控
│       └── target/release/ai-daemon.exe
├── userland/sdk/                    # 用户空间 SDK
│   ├── ainos.h                     # 头文件
│   ├── libainos.c                  # SDK 实现
│   ├── ainos_test.c                # 测试程序
│   └── Makefile
├── configs/ai-daemon.toml          # 守护进程配置
├── models/                          # 模型文件目录
├── data/contexts/                   # 上下文存储目录
├── logs/                            # 日志目录
├── scripts/verification_test.py    # 验收测试脚本
├── docs/                            # 文档
└── weelink-agent/                   # 多智能体协作系统
```

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| 守护进程 | Rust 1.97, Tokio, Serde | 异步 IPC 服务 |
| 运行时 | C++17, CMake | 推理引擎、电源策略 |
| SDK | C17 (C11) | 客户端库 |
| 内核 | C (Linux Kernel) | 调度器、系统调用 |
| 文件系统 | Rust + FUSE | AI 文件系统 |
| 安全策略 | Rust | 访问控制 |
| 构建 | Cargo, Make, CMake | 跨平台编译 |
| IPC | TCP / Unix Domain Socket | 进程间通信 |
| AI 模型 | GGUF (GGML) | 本地推理格式 |
| 云端 API | OpenAI 兼容接口 | 云端推理回退 |

## 路线图

### 已完成

- 项目骨架搭建 — 60+ 文件，全平台支持
- AI 守护进程 — Rust 异步 IPC 服务，5 种操作
- C SDK — 跨平台客户端库
- 电源策略调度 — 4 级温控精度自动切换
- 全链路验收 — 6/6 测试通过
- 云端 API 集成 — Weelink 平台接入

### 进行中

- 编译 AI Runtime (CMake 全模块)
- Windows 服务包装 + 系统托盘

### 规划中

- 下载 GGUF 模型，打通真实本地推理
- Python SDK
- 系统托盘图标（右键菜单）
- 开机自启注册
- Web 管理面板
- 集成 llama.cpp 作为本地推理后端
- Linux 内核模块加载脚本
- 性能基准测试

## 开发团队

| 角色 | AI 模型 | 职责 |
|------|---------|------|
| 首席架构师 | GPT-5.6-Sol | 架构设计、接口定义、集成协调 |
| 内核工程师 | DeepSeek-v4-Pro | 内核模块、AI 调度器、系统调用 |
| AI Runtime 工程师 | Claude-Opus-4-8 | GGML/ONNX 集成、模型管理 |
| 用户空间工程师 | Qwen3.7-Plus | 桌面环境、AI 应用框架、SDK |

## 许可证

MIT License