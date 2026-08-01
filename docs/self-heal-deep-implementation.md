# Ainos OS - 内核自愈模块深度实现方案

> 版本: 2.0.0 | 更新: 2026-08-01

## 概述

内核自愈 (Kernel Self-Healing) 是 Ainos OS 的核心基础设施之一，实现对内核异常的自动检测、分析和恢复，具备"预防性监控 + 反应式检测 + 渐变恢复"三位一体的自愈能力。

## 架构

```
┌──────────────────────────────────────────────────────────────────┐
│                      Ainos Self-Healing Engine                     │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│   ┌──────────────────────────────────────────────────────────┐   │
│   │                   Prevention Layer                         │   │
│   │  (Timer-based periodic health monitoring)                 │   │
│   │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐  │   │
│   │  │ Memory   │ │ Zombie   │ │ Load     │ │ Hung Task  │  │   │
│   │  │Pressure  │ │Processes │ │Average   │ │ Detection  │  │   │
│   │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬─────┘  │   │
│   │       └────────────┴────────────┴───────────────┘         │   │
│   │                            │                               │   │
│   └────────────────────────────┼───────────────────────────────┘   │
│                                ▼                                    │
│   ┌──────────────────────────────────────────────────────────┐   │
│   │                   Detection Layer                          │   │
│   │  ┌──────────────┐ ┌──────────────┐ ┌───────────────────┐ │   │
│   │  │ Panic        │ │ External     │ │ Health Score      │ │   │
│   │  │ Notifier     │ │ Module Event │ │ Calculation       │ │   │
│   │  └──────┬───────┘ └──────┬───────┘ └───────────────────┘ │   │
│   │         └────────────────┘                                │   │
│   └────────────────────────────┼───────────────────────────────┘   │
│                                ▼                                    │
│   ┌──────────────────────────────────────────────────────────┐   │
│   │                   Policy Engine                           │   │
│   │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐  │   │
│   │  │Event     │ │Level     │ │Cooldown  │ │Auto-       │  │   │
│   │  │Config    │ │Selection │ │Check     │ │Escalation  │  │   │
│   │  └──────────┘ └──────────┘ └──────────┘ └────────────┘  │   │
│   └────────────────────────────┼───────────────────────────────┘   │
│                                ▼                                    │
│   ┌──────────────────────────────────────────────────────────┐   │
│   │                   Recovery Layer                          │   │
│   │  Level 0: LOG     → 记录事件，不采取行动                     │   │
│   │  Level 1: SOFT    → 杀进程/SIGTERM/SIGKILL               │   │
│   │  Level 2: RECLAIM → 内存回收/cgroup 清理                   │   │
│   │  Level 3: RESTART → 子系统重启/驱动重载                    │   │
│   │  Level 4: KEXEC   → 紧急 kexec 跳转                       │   │
│   │  Level 5: PANIC   → 允许 panic (最后手段)                  │   │
│   └────────────────────────────┬───────────────────────────────┘   │
│                                ▼                                    │
│   ┌──────────────────────────────────────────────────────────┐   │
│   │                   Verification Layer                       │   │
│   │  · 恢复后健康状态检查                                     │   │
│   │  · 事件环形缓冲区 (256 条)                                 │   │
│   │  · 健康评分 (0-100)                                       │   │
│   │  · 统计跟踪 (原子计数器)                                   │   │
│   └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│   ┌──────────────────────────────────────────────────────────┐   │
│   │                   Interface Layer                          │   │
│   │  · /proc/self-heal/status   → 健康状态和统计             │   │
│   │  · /proc/self-heal/config   → 策略配置 (可写)            │   │
│   │  · /proc/self-heal/trigger  → 手动触发恢复 (仅写)        │   │
│   │  · /proc/self-heal/history  → 事件历史记录               │   │
│   │  · 导出函数 (给其他内核模块用)                            │   │
│   └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

## 关键设计决策

### 1. 预防性监控 (Preventive Monitoring)

| 监控项 | 检测方法 | 警告阈值 | 严重阈值 | 恢复动作 |
|--------|----------|---------|---------|---------|
| 内存压力 | `si_mem_available()` 可用百分比 | < 10% | < 5% | 杀进程 → 回收 → 连杀 |
| 僵尸进程 | `for_each_process` 统计 EXIT_ZOMBIE | > 20 | > 50 | 记录 (等待内核自动回收) |
| 系统负载 | `avenrun` 1-min 负载 | > 4×CPU | > 8×CPU | 杀 CPU 大户 |
| 挂起任务 | 任务状态检查 | 120s D 状态 | — | 杀进程 |

监控定时器每 10 秒触发一次，通过工作队列执行 (不在原子上下文阻塞)。

### 2. 渐变恢复策略 (Graduated Recovery)

每个事件类型可独立配置：
- **起始级别**: 从哪个级别开始尝试
- **冷却时间**: 同类型事件最小间隔 (ms)
- **最大尝试次数**: 单次事件最多尝试恢复几次
- **自动升级**: 失败后是否自动尝试更高级别
- **启用/禁用**: 是否处理该类型事件

### 3. 安全设计

| 场景 | 风险 | 措施 |
|------|------|------|
| Panic 上下文 | 不能睡眠、不能分配内存 | 只用栈内存和原子操作，`spin_trylock` |
| 工作队列 | 可能和通知器冲突 | `recovery_in_progress` 原子标志防止递归 |
| 杀进程 | 可能杀死 init 或内核线程 | 明确检查 PID==1、PF_KTHREAD |
| 内存分配 | 在内存压力下可能失败 | 预分配环形缓冲区，监控路径不用 GFP 分配 |
| 锁顺序 | 死锁 | 固定顺序: spinlock(ring) → mutex(config) → mutex(monitor) |

### 4. 导出 API

| 函数 | 用途 | 可调用上下文 |
|------|------|------------|
| `self_heal_report_event()` | 报告事件 | 进程上下文 (可睡眠) |
| `self_heal_report_event_level()` | 报告事件带级别覆盖 | 进程上下文 |
| `self_heal_get_health()` | 获取健康状态 | 任何上下文 |
| `self_heal_get_health_score()` | 获取健康评分 | 任何上下文 |
| `self_heal_force_recovery()` | 强制触发恢复 | 进程上下文 |

## 文件清单

| 文件 | 行数 | 说明 |
|------|------|------|
| `kernel/ai-self-heal/self_heal.h` | 142 | 头文件，IOCTL 定义，导出 API |
| `kernel/ai-self-heal/self_heal.c` | ~950 | 主实现，6 大子系统 |
| `kernel/ai-self-heal/Makefile` | 96 | 编译和测试目标 |
| `kernel/ai-self-heal/test_self_heal.py` | 170 | Python 集成测试 |

## 与 POC 版本对比

| 对比项 | POC (v1.0) | 深度实现 (v2.0) |
|--------|-----------|----------------|
| 行数 | 188 行 | ~950 行 |
| 监控方式 | 仅 panic 通知器 | 预防性定时器 + panic 通知器 + 外部事件 |
| 恢复策略 | 单一级别 | 5 级渐变恢复 (LOG→SOFT→RECLAIM→RESTART→KEXEC) |
| 安全性 | msleep 在 panic 上下文 | 上下文感知，panic 中只用原子操作 |
| 配置 | 硬编码 | 动态可配置，13 种事件类型独立配置 |
| /proc 接口 | 无 | 4 个文件: status, config, trigger, history |
| 统计 | 3 个原子变量 | 11 个原子计数器 + 健康评分 |
| 事件记录 | 无 | 256 条环形缓冲区 |
| 导出 API | 2 个函数 | 5 个导出函数 |
| 测试 | 手动 | Python 自动化测试 (20+ 测试用例) |

## 恢复场景示例

### 场景 1: 内存压力
```
1. 定时器检测到可用内存 < 5%
2. 触发 HEAL_EVENT_MEM_PRESSURE
3. 策略引擎: 起始级别=SOFT (配置: mem_pressure soft 60000 5 yes yes)
4. 执行: 找到 RSS 最大的进程，发送 SIGTERM
5. 等待 1 秒，检查是否已退出
6. 如果未退出，发送 SIGKILL
7. 验证: 检查可用内存是否恢复到 10% 以上
8. 如果失败，升级到 RECLAIM → RESTART → ...
```

### 场景 2: Panic 拦截
```
1. 内核调用 panic()
2. panic_notifier 链被调用，自愈模块最高优先级
3. 记录 panic 消息到环形缓冲区
4. 更新统计
5. 返回 NOTIFY_DONE (允许 panic 继续)
6. 后续可通过 kdump 分析
```

### 场景 3: 外部模块报告
```
1. ai-fs 模块检测到文件系统错误
2. 调用 self_heal_report_event(HEAL_EVENT_FS, 0, "ext4 journal error")
3. 策略引擎: 起始级别=RESTART (尝试重启文件系统)
4. 如果失败，升级到 KEXEC → PANIC
```

## 编译和使用

```bash
# 编译
cd kernel/ai-self-heal
make

# 加载
sudo insmod self_heal.ko

# 查看状态
cat /proc/self-heal/status

# 配置
echo "mem_pressure reclaim 60000 5 yes yes" > /proc/self-heal/config

# 手动触发测试
echo "custom soft 0 'test recovery'" > /proc/self-heal/trigger

# 查看历史
cat /proc/self-heal/history

# 卸载
sudo rmmod self_heal
```

## 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `monitor_interval_sec` | 10 | 预防性监控间隔 (秒) |
| `ring_buffer_size` | 256 | 事件环形缓冲区大小 |
| `mem_pressure_warn_pct` | 10 | 内存压力警告阈值 (%) |
| `mem_pressure_crit_pct` | 5 | 内存压力严重阈值 (%) |
| `zombie_warn_count` | 20 | 僵尸进程警告阈值 |
| `zombie_crit_count` | 50 | 僵尸进程严重阈值 |
| `load_warn_multiplier` | 4 | 负载警告倍数 (相对于 CPU 数) |
| `load_crit_multiplier` | 8 | 负载严重倍数 |
| `hung_task_timeout_sec` | 120 | D 状态任务超时 (秒) |
| `max_recovery_attempts` | 3 | 单次事件最大恢复尝试次数 |
| `enable_preventive` | true | 启用预防性监控 |
| `enable_ai_integration` | true | 启用 AI 集成 |

## 未来扩展

1. **AI 集成**: 通过 `proc_ai_submit_infer()` 将事件报告给 ai-daemon，获取 AI 建议的恢复策略
2. **健康检查扩展**: 支持更多系统健康指标 (磁盘 I/O、网络延迟、文件系统状态)
3. **快照/回滚**: 事件发生前保存系统状态快照，恢复后可回滚
4. **自动学习**: 记录每次恢复的效果，自动调整策略参数
5. **用户空间通知**: 事件发生时向用户空间发送 netlink 通知