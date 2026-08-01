# /proc/ai — 深度实现计划

## 现状问题

当前 `/proc/ai` 是纯 POC：
- 所有推理请求返回模拟数据，不连 ai-daemon
- 单个缓冲区，不支持并发
- 无错误处理、超时、重试
- 内核 ↔ 用户态无真实通信通道
- 不同文件节点行为不完整

## 目标

让 `/proc/ai` 成为真正的内核 ↔ AI 守护进程桥梁：
```
echo "翻译成英文" > /proc/ai/infer  →  内核  →  ai-proc-bridge  →  ai-daemon  →  (本地/云端推理)
cat /proc/ai/infer                  ←  内核  ←  ai-proc-bridge  ←  ai-daemon  ←  (结果返回)
```

## 架构设计

### 三层通信架构

```
┌─────────────────────────────────────────────────────────────────┐
│  userspace                                                        │
│  ┌──────────────┐    TCP:9500     ┌────────────────────────────┐ │
│  │  ai-proc-bridge│ ────────────── │  ai-daemon (Rust)          │ │
│  │  (C, 40KB)    │ ←────────────── │  · 推理/嵌入/上下文        │ │
│  │  · 请求转发    │                │  · 本地/云端路由            │ │
│  │  · 重试/超时   │                │  · 模型管理                 │ │
│  │  · 背压控制    │                └────────────────────────────┘ │
│  └──────┬───────┘                                                  │
│         │ /dev/ainos-proc (misc device + IOCTL + poll)             │
├─────────┼─────────────────────────────────────────────────────────┤
│  kernel │                                                          │
│  ┌──────┴──────────────────────────────────────────────────────┐  │
│  │  /proc/ai 内核模块 (proc_ai.c)                                │  │
│  │                                                               │  │
│  │  /proc/ai/status  ── seq_file ── 实时系统状态                 │  │
│  │  /proc/ai/infer   ── 写=提交请求 / 读=获取结果               │  │
│  │  /proc/ai/embed   ── 写=提交文本 / 读=嵌入向量               │  │
│  │  /proc/ai/chat    ── 写=对话 / 读=流式响应                   │  │
│  │  /proc/ai/models  ── seq_file ── 模型列表                     │  │
│  │  /proc/ai/config  ── seq_file ── 配置读写                     │  │
│  │  /proc/ai/stats   ── seq_file ── 性能统计                     │  │
│  │                                                               │  │
│  │  · 请求队列 (64 entry, FIFO, spinlock)                        │  │
│  │  · 响应缓冲区 (per-file, 64KB, RCU)                          │  │
│  │  · 等待队列 (waitqueue, poll 支持)                            │  │
│  │  · 工作队列 (workqueue, 异步处理)                             │  │
│  │  · 统计计数器 (原子操作)                                      │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 1. 内核模块 (proc_ai.c) — 7 个文件节点

| 文件 | 权限 | 读操作 | 写操作 | 实现 |
|------|------|--------|--------|------|
| `status` | 0644 | 实时状态(seq_file) | reload/reset | `/dev/ainos-proc` IOCTL 获取 |
| `infer` | 0644 | 上次推理结果 | 提交推理请求 | 异步: 请求入队 → bridge 转发 → 结果回写 |
| `embed` | 0644 | 上次嵌入结果 | 提交嵌入请求 | 同 infer 但走 embed 路径 |
| `chat` | 0644 | 对话历史 | 提交对话消息 | 带 session 上下文 |
| `models` | 0444 | 模型列表 | - | 通过 bridge 查询 ai-daemon |
| `config` | 0644 | 配置(seq_file) | 更新配置 | 通过 bridge 同步 |
| `stats` | 0444 | 性能统计(seq_file) | - | 原子计数器 |

### 2. 内核 ↔ 用户态传输 (misc device)

**设备**: `/dev/ainos-proc` (major=10, minor=动态)
**IOCTL 命令**:
- `AI_PROC_GET_REQUEST` — bridge 读取待处理请求 (阻塞)
- `AI_PROC_SEND_RESPONSE` — bridge 写入响应
- `AI_PROC_WAIT` — bridge 等待新请求 (poll)
- `AI_PROC_GET_STATS` — 获取统计

**poll 支持**: bridge 可阻塞在 `/dev/ainos-proc` 上等待请求

### 3. 请求队列

```c
struct ai_proc_request {
    u32 id;              // 自增 ID
    u32 file_id;         // 文件类型 (infer/embed/chat)
    u32 session_id;      // 会话 ID
    char data[4096];     // 请求数据
    u32 len;             // 数据长度
    u32 flags;           // 标志位
    ktime_t submitted;   // 提交时间
    struct completion complete; // 完成信号
};

struct ai_proc_response {
    u32 id;              // 对应请求 ID
    u32 status;          // 0=ready, 1=error, 2=timeout
    char data[65536];    // 响应数据
    u32 len;
    char source[16];     // "local" / "cloud"
    u32 tokens;
    u64 inference_ms;
};
```

### 4. 用户态 bridge (ai-proc-bridge.c)

**职责**:
- 打开 `/dev/ainos-proc`，阻塞等待请求
- 收到请求后通过 TCP 转发给 ai-daemon (127.0.0.1:9500)
- 收到响应后写回内核
- 处理重试 (3次)、超时 (30s)、重连

**状态机**:
```
IDLE → WAIT_REQUEST → GOT_REQUEST → FORWARD_TO_DAEMON
  → WAIT_RESPONSE → GOT_RESPONSE → WRITE_BACK → IDLE
```

### 5. 细节工程要点

**并发安全**:
- 请求队列: spinlock_irqsave
- 响应缓冲区: RCU + kfree_rcu
- 统计: atomic_t
- 多个进程同时读同一个文件: 每个 file 私有数据

**超时处理**:
- 内核侧: 30 秒超时定时器，超时返回 ETIMEDOUT
- bridge 侧: 10 秒 TCP 超时，3 次重试

**内存管理**:
- 请求: kmalloc + kfree (最大 4KB)
- 响应: vmalloc (最大 64KB)
- 缓冲区池: 预分配 8 个，避免 GFP_ATOMIC 失败

**poll/select 支持**:
- 读 infer: POLLIN 当有结果
- 写 infer: POLLOUT 当队列不满

**调试**:
- `/proc/ai/stats` 显示: 请求数、成功率、平均延迟、队列深度
- `debugfs: /sys/kernel/debug/ainos/proc` 详细日志

## 实现步骤

### Phase 1: 内核模块基础
1. 重写 `proc_ai.c` — 完整的 VFS 层，7 个文件节点
2. 实现请求队列 (spinlock + FIFO)
3. 实现响应缓冲区 (RCU)
4. 添加 poll 支持
5. 添加统计计数器

### Phase 2: 内核 ↔ 用户态通道
1. 注册 misc device `/dev/ainos-proc`
2. 实现 IOCTL 命令 (GET_REQUEST, SEND_RESPONSE, WAIT)
3. 实现 waitqueue 让 bridge 阻塞等待
4. 实现超时定时器

### Phase 3: 用户态 bridge
1. 编写 `ai-proc-bridge.c`
2. 实现 netlink ↔ TCP 的请求转发
3. 实现重试/超时/重连逻辑
4. 实现 daemon 化 (fork + setsid)

### Phase 4: 集成测试
1. 测试每个 /proc/ai 文件节点
2. 测试并发访问
3. 测试超时/重试场景
4. 测试 bridge 断开重连
5. 性能基准测试

## 涉及文件

| 文件 | 动作 | 说明 |
|------|------|------|
| `kernel/ai-proc/proc_ai.c` | 重写 | 完整 VFS + 请求队列 + misc device |
| `kernel/ai-proc/proc_ai.h` | 重写 | 导出接口 + 设备协议 |
| `kernel/ai-proc/Makefile` | 新增 | 编译支持 |
| `kernel/ai-proc/ai-proc-bridge.c` | 新增 | 用户态转发 daemon |
| `kernel/ai-proc/ai-proc-bridge.service` | 新增 | systemd 服务文件 |
| `kernel/Makefile` | 更新 | 添加 proc-ai 模块 |
| `docs/10-directions-design.md` | 更新 | 设计文档更新 |

## 验证方法

```bash
# 1. 加载模块
insmod proc_ai.ko
ls /proc/ai/

# 2. 启动 bridge
./ai-proc-bridge &

# 3. 测试推理
echo "你好" > /proc/ai/infer
cat /proc/ai/infer      # 应该返回 ai-daemon 的结果

# 4. 测试状态
cat /proc/ai/status
cat /proc/ai/models
cat /proc/ai/stats

# 5. 测试并发
for i in {1..10}; do
  echo "test $i" > /proc/ai/infer &
done
cat /proc/ai/infer

# 6. 测试超时
# 停掉 bridge，看内核超时处理
killall ai-proc-bridge
echo "timeout test" > /proc/ai/infer
# 30 秒后应该返回错误