# Ainos OS 总体架构设计

## 1. 系统架构总览

五层架构：

```
应用层 (Userland)
  传统应用 (X11/Wayland) | AI 原生应用 (AI SDK) | 系统工具 (Shell/文件管理)
        |
系统库层 (System Libraries)
  libc (glibc) | libainos (AI SDK) | libggml (推理) | libonnxruntime (云端回退)
        |
系统服务层 (System Services)
  AI 守护进程 (ai-daemon) | 模型管理器 (model-mgr) | 上下文管理器 (context-mgr)
        |
AI 内核子系统 (Kernel AI Subsystem)
  AI 系统调用 (sys_ai_*) | AI 调度器 (ai_sched) | 向量指令加速 | AI 文件索引 (语义搜索)
        |
传统 Linux 内核
  进程管理 · 内存管理 · 文件系统 · 驱动框架 · 网络栈 · 安全模块
        |
硬件层
  CPU (x86_64/ARM/RISC-V) · GPU/NPU · 内存 · 存储 · 网络 · 外设
```

## 2. 核心设计原则

### 2.1 离线优先 (Offline First)

用户请求 AI 能力时，系统自动判断在线/离线状态：
- 在线：使用云端大模型 (70B+)
- 离线：使用本地小模型 (1-7B)
- 两者通过统一 AI 接口暴露给应用，应用无感知

### 2.2 AI 是系统服务，不是应用插件

- AI 守护进程 (ai-daemon) 随系统启动，类似 systemd-journald
- 所有 AI 推理请求通过 Unix Domain Socket 或内核系统调用
- 系统级模型缓存，避免每个应用重复加载模型
- 统一的资源管理，防止 AI 任务抢占关键系统资源

### 2.3 安全沙箱

- AI 推理在隔离的进程/容器中运行
- 模型文件有完整性校验
- 系统调用级权限控制

## 3. AI 系统调用接口 (ABI)

```c
// 新增 AI 系统调用 (Linux 原生扩展)

// AI 推理请求
long sys_ai_inference(struct ai_inference_req __user *req,
                      struct ai_inference_resp __user *resp);

// 获取文本嵌入向量
long sys_ai_embedding(const char __user *text, size_t len,
                      float __user *vector, size_t dim);

// 语义搜索
long sys_ai_semantic_search(const char __user *query,
                            struct ai_search_result __user *results,
                            size_t max_results);

// 模型加载/卸载
long sys_ai_model_load(const char __user *path,
                       uint64_t __user *model_id);
long sys_ai_model_unload(uint64_t model_id);

// 上下文管理
long sys_ai_context_store(uint64_t session_id,
                          const char __user *key, size_t key_len,
                          const char __user *value, size_t value_len);
long sys_ai_context_retrieve(uint64_t session_id,
                             const char __user *key, size_t key_len,
                             char __user *value, size_t *value_len);
```

## 4. 本地离线推理方案

### 4.1 GGML 引擎

GGML 推理引擎 (ai-runtime) 包含：
- GGML 模型加载器
- GGML 加载缓存
- 量化/优化 (4bit/8bit)

支持的模型架构：
- LLaMA / Llama 2 / 3 / 4
- Mistral / Mixtral
- Qwen 2.5 / 3
- DeepSeek (蒸馏版)
- Phi-3 / Phi-4 (小模型)
- Whisper (语音)
- Nomic Embed (文本嵌入)

### 4.2 推荐离线模型

| 用途 | 模型 | 大小 | 量化 |
|------|------|------|------|
| 基础对话 | Phi-3-mini (3.8B) | ~2.5GB | Q4_K_M |
| 语义搜索 | Nomic Embed Text (137M) | ~80MB | Q8 |
| 语音命令 | Whisper Base (74M) | ~150MB | FP16 |
| OCR | TrOCR / PaddleOCR | ~100MB | FP16 |
| 翻译 | NLLB-200-distilled (600M) | ~1.2GB | Q8 |

## 5. 系统服务通信架构

```
AI 应用 (进程A)  AI 应用 (进程B)  Shell (进程C)
        |                |                |
        |     Unix Domain Socket / ioctl  |
        |                |                |
        v                v                v
          AI 守护进程 (ai-daemon)
   请求路由 (router) | 模型编排 (scaler) | 上下文管理 (context)
   本地推理 (GGML)   | 云端推理 (API)    | 安全审计 (audit)
```

## 6. 启动流程

BIOS/UEFI -> Bootloader (GRUB) -> Linux Kernel
  -> initramfs -> 挂载根文件系统
  -> systemd (PID 1)
     - 加载 AI 内核模块 (ai-scheduler.ko, ai-syscalls.ko)
     - 启动 ai-daemon 服务
       - 检测 NPU/GPU 加速器
       - 检查网络连接状态
       - 加载基础小模型 (嵌入模型)
     - 启动桌面环境 (Wayland Compositor)
     - 启动 AI 系统托盘

## 7. 系统目录布局

```
/etc/ainos/              # 配置文件
  - ai-daemon.conf       # AI 守护进程配置
  - models.toml          # 模型注册表
  - policies.toml        # AI 安全策略

/usr/lib/ainos/          # 系统库
  - libainos.so          # AI 应用 SDK
  - libainos-kernel.so   # 内核通信库

/usr/share/ainos/        # 共享数据
  - models/              # 预置模型目录

/var/lib/ainos/          # 运行时数据
  - models/              # 下载的模型
  - contexts/            # 上下文存储
  - logs/                # 审计日志
```