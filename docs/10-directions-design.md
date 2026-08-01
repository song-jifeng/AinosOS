# Ainos OS 10 大发展方向 — 设计文档

## 1. /proc/ai 虚拟 AI 文件系统

- **目录**: `kernel/ai-proc/`
- **语言**: C (Linux 内核模块)
- **状态**: 已实现
- **接口**: 通过 VFS 暴露 AI 能力
  - `cat /proc/ai/status` — 系统状态
  - `echo "prompt" > /proc/ai/infer` — 推理请求
  - `cat /proc/ai/infer` — 读取结果
  - `cat /proc/ai/models` — 模型列表
  - `cat /proc/ai/config` — 配置信息
  - `echo "text" > /proc/ai/embed` — 嵌入向量
- **核心文件**:
  - `proc_ai.c` — VFS 实现，proc_ops 结构，read/write 处理
  - `proc_ai.h` — 导出接口

## 2. 内核自愈 (替代 panic)

- **目录**: `kernel/ai-self-heal/`
- **语言**: C (Linux 内核模块)
- **状态**: 已实现
- **机制**: 通过 `panic_notifier_list` 注册最高优先级钩子
  - 捕获 panic 上下文 (消息、寄存器、调用栈)
  - AI 分析: 根据 panic 消息匹配恢复策略
  - 策略: HEAL_KILL_TASK / HEAL_RESTART / HEAL_ROLLBACK / HEAL_PANIC
  - 成功则 NOTIFY_STOP 阻止 panic
- **核心文件**: `self_heal.c`, `self_heal.h`

## 3. AI KILL 智能进程管理

- **目录**: `kernel/ai-kill/`
- **语言**: C (Linux 内核模块)
- **状态**: 已实现
- **评分维度**: CPU 使用率、内存泄漏趋势、IO 异常
- **阈值**: kill=80, term=60, warn=40
- **扫描**: 5 秒定时器，遍历所有进程
- **接口**: `/proc/ai/kill/scores`, `/proc/ai/kill/config`
- **核心文件**: `ai_kill.c`, `ai_kill.h`

## 4. AI Borrow Checker

- **目录**: `ai-tools/borrow-checker/`
- **语言**: Rust
- **状态**: 已实现
- **命令**: `cargo-ainos-borrow check`
- **功能**:
  - 扫描项目中的借用错误
  - 常见错误模式匹配和修复建议
  - 代码分析: unsafe 块、clone 调用、内部可变性、静态生命周期
- **核心文件**: `Cargo.toml`, `src/main.rs`, `src/analyzer.rs`

## 5. Crash Oracle

- **目录**: `ai-tools/crash-oracle/`
- **语言**: Rust
- **状态**: 已实现
- **监控指标**: 内存碎片化、CPU 温度、IO 错误率、系统调用延迟、内存压力、OOM 评分
- **预测**: 综合评分 0-10，输出风险等级、预估时间、建议操作
- **核心文件**: `Cargo.toml`, `src/main.rs`

## 6. AI Git

- **目录**: `ai-tools/ai-git/`
- **语言**: Rust
- **状态**: 已实现
- **子命令**: `commit`, `merge`, `diff`, `log`, `analyze`
- **功能**:
  - AI 自动生成提交信息 (基于 diff 分析)
  - 智能合并冲突解决 (保留双方变更)
  - 语义 diff 分析 (变更类别、风险等级)
- **核心文件**: `Cargo.toml`, `src/main.rs`, `src/diff.rs`, `src/merge.rs`

## 7. AI tmpfs 智能文件系统

- **目录**: `kernel/ai-tmpfs/`
- **语言**: C (Linux 内核模块)
- **状态**: 已实现
- **特性**: 热点数据保留 (访问 ≥3 次)、冷数据自动过期 (5 分钟)、智能预测
- **接口**: `ai_tmpfs_create()`, `ai_tmpfs_read()`, `ai_tmpfs_delete()`, `ai_tmpfs_list()`
- **核心文件**: `ai_tmpfs.c`, `ai_tmpfs.h`

## 8. LLM-as-IPC 进程对话

- **目录**: `system-services/llm-ipc/`
- **语言**: Rust
- **状态**: 已实现
- **协议**: JSON over Unix Domain Socket
- **消息格式**: `{ from, to, message, context, timestamp }`
- **功能**: 服务注册、消息路由、意图分析、自然语言↔命令转换
- **核心文件**: `Cargo.toml`, `src/main.rs`, `src/bridge.rs`, `src/protocol.rs`

## 9. Hotpatch 生成器

- **目录**: `kernel/hotpatch/`
- **语言**: C (Linux 内核模块)
- **状态**: 已实现
- **机制**: kprobe 异常检测 → 上下文分析 → 补丁生成 → livepatch 应用
- **功能**: 补丁注册、应用、回滚、异常检测钩子、自动补丁生成
- **核心文件**: `hotpatch.c`, `hotpatch.h`, `patch_gen.c`

## 10. AI readahead 智能预读

- **目录**: `kernel/ai-readahead/`
- **语言**: C (Linux 内核模块)
- **状态**: 已实现
- **算法**: Markov 链预测下一个访问偏移
- **特性**: 每文件跟踪、置信度评分、缓存命中统计
- **接口**: `ai_readahead_predict()`, `ai_readahead_cache_hit()`, `ai_readahead_stats()`
- **核心文件**: `ai_readahead.c`, `ai_readahead.h`

## 项目结构

```
D:/Ainos/
├── kernel/
│   ├── ai-proc/          # 1. /proc/ai 虚拟文件系统
│   ├── ai-self-heal/     # 2. 内核自愈
│   ├── ai-kill/          # 3. AI KILL 进程管理
│   ├── ai-tmpfs/         # 7. AI tmpfs 智能文件系统
│   ├── ai-readahead/     # 10. AI readahead 智能预读
│   └── hotpatch/         # 9. Hotpatch 生成器
├── ai-tools/
│   ├── ai-git/           # 6. AI Git 语义版本控制
│   ├── borrow-checker/   # 4. AI Borrow Checker
│   └── crash-oracle/     # 5. Crash Oracle
├── system-services/
│   └── llm-ipc/          # 8. LLM-as-IPC 进程对话
└── docs/
    └── 10-directions-design.md
```

## 编译说明

### 内核模块 (Linux)
```bash
cd kernel
make          # 编译所有模块
make load-ai  # 加载 AI 模块
```

### Rust 工具
```bash
cd ai-tools/ai-git && cargo build
cd ai-tools/borrow-checker && cargo build
cd ai-tools/crash-oracle && cargo build
cd system-services/llm-ipc && cargo build
```