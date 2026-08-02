// SPDX-License-Identifier: GPL-2.0
#ifndef AINOS_SELF_HEAL_H
#define AINOS_SELF_HEAL_H

#include <linux/types.h>
#include <linux/ioctl.h>

/* ================================================================
 * Ainos OS - 内核自愈模块
 * 版本: 2.0.0 (深度实现)
 * ================================================================
 *
 * 架构:
 *   预防性监控 (定时器 + 工作队列) → 异常检测 → 策略引擎 → 渐变恢复 → 验证
 *                                     ↑
 *   反应式检测 (notifier 链) ──────────┘
 *
 * 恢复级别 (从轻到重):
 *   Level 0: 仅记录
 *   Level 1: 软恢复 (杀进程 / 回收内存)
 *   Level 2: 中恢复 (重启子系统 / 重载驱动)
 *   Level 3: 硬恢复 (紧急 kexec)
 *   Level 4: 紧急 (允许 panic / BUG)
 *
 * /proc/self-heal 接口:
 *   status  - 当前健康状态和统计
 *   config  - 策略配置 (可写)
 *   trigger - 手动触发恢复 (仅写)
 *   history - 最近事件环形缓冲区
 */

#define SELF_HEAL_VERSION "2.0.0"

/* ================================================================
 * IOCTL 命令
 * ================================================================ */

#define SELF_HEAL_IOC_MAGIC  'H'

/* 触发恢复 */
#define SELF_HEAL_TRIGGER    _IOW(SELF_HEAL_IOC_MAGIC, 1, struct heal_trigger_cmd)
/* 获取配置 */
#define SELF_HEAL_GET_CONFIG _IOR(SELF_HEAL_IOC_MAGIC, 2, struct heal_event_config)
/* 设置配置 */
#define SELF_HEAL_SET_CONFIG _IOW(SELF_HEAL_IOC_MAGIC, 3, struct heal_event_config)
/* 获取统计 */
#define SELF_HEAL_GET_STATS  _IOR(SELF_HEAL_IOC_MAGIC, 4, struct heal_stats)
/* 重置统计 */
#define SELF_HEAL_RESET      _IO(SELF_HEAL_IOC_MAGIC, 5)

/* ================================================================
 * 事件类型
 * ================================================================ */

enum heal_event_type {
    HEAL_EVENT_MEM_PRESSURE  = 0,  /* 内存压力过高 */
    HEAL_EVENT_SOFT_LOCKUP  = 1,  /* 软锁 */
    HEAL_EVENT_HUNG_TASK    = 2,  /* 任务挂起 (D 状态) */
    HEAL_EVENT_OOM_NEAR     = 3,  /* 接近 OOM */
    HEAL_EVENT_ZOMBIE       = 4,  /* 僵尸进程过多 */
    HEAL_EVENT_MCE          = 5,  /* 机器检查错误 */
    HEAL_EVENT_PANIC        = 6,  /* 内核 panic */
    HEAL_EVENT_DRIVER       = 7,  /* 驱动错误 */
    HEAL_EVENT_FS           = 8,  /* 文件系统错误 */
    HEAL_EVENT_AI_OVERRIDE  = 9,  /* AI 决策覆盖 */
    HEAL_EVENT_OOM_KILL     = 10, /* OOM killer 触发 */
    HEAL_EVENT_HIGH_LOAD    = 11, /* 系统负载过高 */
    HEAL_EVENT_CUSTOM       = 12, /* 自定义触发 */
    HEAL_EVENT_MAX,
};

/* ================================================================
 * 恢复级别 (从轻到重)
 * ================================================================ */

enum heal_level {
    HEAL_LEVEL_LOG      = 0,  /* 仅记录，不采取行动 */
    HEAL_LEVEL_SOFT     = 1,  /* 软恢复: 杀进程/SIGTERM/SIGKILL */
    HEAL_LEVEL_RECLAIM  = 2,  /* 回收: 内存回收/cgroup 清理 */
    HEAL_LEVEL_RESTART  = 3,  /* 重启: 子系统重启/驱动重载 */
    HEAL_LEVEL_KEXEC    = 4,  /* 硬恢复: 紧急 kexec */
    HEAL_LEVEL_PANIC    = 5,  /* 紧急: 允许 panic */
    HEAL_LEVEL_NUM      = 6,  /* 级别总数 */
};

/* 使用配置默认级别 (sentinel, 不是实际级别) */
#define HEAL_LEVEL_DEFAULT 99

/* ================================================================
 * 数据结构
 * ================================================================ */

/* 事件配置 (每个事件类型可独立配置) */
struct heal_event_config {
    __u32  type;             /* enum heal_event_type */
    __u32  level;            /* enum heal_level - 恢复级别 */
    __u32  cooldown_ms;      /* 冷却时间 (ms)，同类型事件最小间隔 */
    __u32  max_attempts;     /* 最大尝试次数 (0 = 无限) */
    __u32  enabled;          /* 1=启用, 0=禁用 */
    __u32  auto_escalate;    /* 1=自动升级, 0=失败即停止 */
    char   name[32];         /* 可读名称 */
};

/* 触发命令 */
struct heal_trigger_cmd {
    __u32  type;             /* enum heal_event_type */
    __u32  level;            /* enum heal_level - 覆盖恢复级别 */
    pid_t  pid;              /* 目标 PID (可选) */
    char   reason[128];      /* 触发原因 */
};

/* 事件记录 (环形缓冲区条目) */
struct heal_event_record {
    __u64  timestamp_ns;     /* 事件时间戳 */
    __u32  type;             /* enum heal_event_type */
    __u32  level_used;       /* 使用的恢复级别 */
    __u32  level_escalated;  /* 升级到的级别 */
    __s32  result;           /* 0=成功, 负值=错误码 */
    __u32  pid;              /* 关联 PID */
    __u32  seq;              /* 全局序列号 */
    char   comm[16];         /* 进程名 */
    char   description[128]; /* 事件描述 */
};

/* 统计 */
struct heal_stats {
    __u64  events_detected;   /* 检测到的事件总数 */
    __u64  recovery_attempts; /* 恢复尝试次数 */
    __u64  recovery_success;  /* 恢复成功次数 */
    __u64  recovery_failed;   /* 恢复失败次数 */
    __u64  escalation_count;  /* 升级次数 */
    __u64  prevention_actions;/* 预防性行动次数 */
    __u64  oom_kills;         /* OOM 杀进程次数 */
    __u64  tasks_killed;      /* 主动杀进程次数 */
    __u64  drivers_reloaded;  /* 驱动重载次数 */
    __u64  kexec_triggers;    /* kexec 触发次数 */
    __u64  last_event_ns;     /* 最后事件时间戳 */
    __u32  current_level;     /* 当前恢复级别 */
    __u32  health_score;      /* 健康评分 0-100 */
    __u64  uptime_ms;         /* 模块运行时间 */
};

/* 健康状态枚举 */
enum heal_health_status {
    HEAL_HEALTH_OK        = 0,  /* 健康 */
    HEAL_HEALTH_WARNING   = 1,  /* 警告 */
    HEAL_HEALTH_CRITICAL  = 2,  /* 严重 */
    HEAL_HEALTH_RECOVERING= 3,  /* 恢复中 */
    HEAL_HEALTH_UNKNOWN   = 4,  /* 未知 */
};

/* ================================================================
 * 导出函数 (给其他内核模块使用)
 * ================================================================ */

#ifdef __KERNEL__

/* 报告事件 (从其他内核模块调用) */
int self_heal_report_event(enum heal_event_type type,
                           pid_t pid,
                           const char *description);

/* 报告事件带级别覆盖 */
int self_heal_report_event_level(enum heal_event_type type,
                                 enum heal_level level,
                                 pid_t pid,
                                 const char *description);

/* 获取当前健康状态 */
enum heal_health_status self_heal_get_health(void);

/* 获取健康评分 (0-100) */
unsigned int self_heal_get_health_score(void);

/* 强制触发恢复 */
int self_heal_force_recovery(enum heal_event_type type,
                             enum heal_level level,
                             pid_t pid);

#endif /* __KERNEL__ */

#endif /* AINOS_SELF_HEAL_H */