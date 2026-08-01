#ifndef AINOS_AI_KILL_H
#define AINOS_AI_KILL_H

#include <linux/types.h>
#include <linux/ioctl.h>

#define AI_KILL_VERSION "2.0.0"

/* ================================================================
 * IOCTL
 * ================================================================ */

#define AI_KILL_IOC_MAGIC 'K'

#define AI_KILL_GET_SCORE  _IOR(AI_KILL_IOC_MAGIC, 1, struct ai_kill_score)
#define AI_KILL_KILL_PID   _IOW(AI_KILL_IOC_MAGIC, 2, pid_t)
#define AI_KILL_GET_CONFIG _IOR(AI_KILL_IOC_MAGIC, 3, struct ai_kill_config)
#define AI_KILL_SET_CONFIG _IOW(AI_KILL_IOC_MAGIC, 4, struct ai_kill_config)
#define AI_KILL_GET_STATS  _IOR(AI_KILL_IOC_MAGIC, 5, struct ai_kill_stats)
#define AI_KILL_RESET      _IO(AI_KILL_IOC_MAGIC, 6)

/* ================================================================
 * 评分维度
 * ================================================================ */

#define AI_KILL_DIM_CPU        0
#define AI_KILL_DIM_MEM        1
#define AI_KILL_DIM_IO         2
#define AI_KILL_DIM_NET        3
#define AI_KILL_DIM_AGE        4
#define AI_KILL_DIM_CRITICALITY 5
#define AI_KILL_DIM_LEAK       6
#define AI_KILL_DIM_COUNT      7

/* ================================================================
 * 动作级别
 * ================================================================ */

enum ai_kill_action {
    AI_KILL_ACTION_NONE     = 0,
    AI_KILL_ACTION_LOG      = 1,
    AI_KILL_ACTION_WARN     = 2,
    AI_KILL_ACTION_TERM     = 3,
    AI_KILL_ACTION_KILL     = 4,
    AI_KILL_ACTION_GROUP    = 5,
};

/* ================================================================
 * 数据结构
 * ================================================================ */

/* 进程评分 */
struct ai_kill_score {
    pid_t  pid;
    char   comm[TASK_COMM_LEN];
    __u32  dims[AI_KILL_DIM_COUNT];  /* 各维度评分 0-100 */
    __u32  total;                     /* 综合评分 0-100 */
    __u32  action;                    /* 建议动作 (enum ai_kill_action) */
    __u64  rss_bytes;                 /* 当前 RSS */
    __u64  cpu_ns;                    /* 最近 CPU 时间 (ns) */
    __u32  nr_threads;               /* 线程数 */
    __u32  nr_fds;                    /* 文件描述符数 */
    __s32  oom_score_adj;            /* OOM 调整值 */
};

/* 进程行为记录 (用于趋势分析) */
struct ai_kill_behavior {
    pid_t  pid;
    char   comm[TASK_COMM_LEN];
    __u64  rss_bytes;                 /* RSS 采样 */
    __u64  cpu_ns;                    /* CPU 时间采样 */
    __u64  io_bytes;                  /* IO 字节数采样 */
    __u64  timestamp_ns;              /* 采样时间戳 */
    __u32  sample_count;              /* 采样次数 */
};

/* 配置 */
struct ai_kill_config {
    __u32  weights[AI_KILL_DIM_COUNT]; /* 各维度权重 */
    __u32  threshold_warn;             /* 警告阈值 */
    __u32  threshold_term;             /* SIGTERM 阈值 */
    __u32  threshold_kill;             /* SIGKILL 阈值 */
    __u32  scan_interval_ms;           /* 扫描间隔 (ms) */
    __u32  enabled;                    /* 1=启用 */
    __u32  max_kills_per_scan;         /* 每次扫描最多杀进程数 */
    __u32  rate_limit_ms;              /* 杀进程速率限制 (ms) */
    __u32  protect_init;               /* 1=保护 init */
    __u32  protect_kthreads;           /* 1=保护内核线程 */
    char   whitelist[256];             /* 白名单进程名 (逗号分隔) */
};

/* 杀戮记录 */
struct ai_kill_record {
    __u64  timestamp_ns;
    pid_t  pid;
    char   comm[TASK_COMM_LEN];
    __u32  total_score;
    __u32  action;                     /* enum ai_kill_action */
    __s32  result;                     /* 0=成功, 负值=错误 */
    char   reason[64];
};

/* 统计 */
struct ai_kill_stats {
    __u64  scans_total;                /* 总扫描次数 */
    __u64  scans_with_candidates;      /* 有候选的扫描次数 */
    __u64  actions_log;                /* 记录次数 */
    __u64  actions_warn;               /* 警告次数 */
    __u64  actions_term;               /* SIGTERM 次数 */
    __u64  actions_kill;               /* SIGKILL 次数 */
    __u64  actions_group;              /* 进程组杀戮次数 */
    __u64  actions_failed;             /* 失败次数 */
    __u64  whitelist_hits;             /* 白名单命中次数 (阻止杀) */
    __u64  last_scan_duration_ns;      /* 上次扫描耗时 (ns) */
    __u32  current_victims;            /* 当前候选进程数 */
    __u32  top_score;                  /* 本次扫描最高分 */
};

/* ================================================================
 * 导出函数
 * ================================================================ */

#ifdef __KERNEL__

/* 获取进程评分 */
int ai_kill_get_score(pid_t pid, struct ai_kill_score *score);

/* 建议杀进程: 返回最高分的进程 PID */
pid_t ai_kill_suggest_victim(void);

/* 执行杀进程 */
int ai_kill_execute(pid_t pid, enum ai_kill_action action);

/* 注册白名单进程 */
int ai_kill_whitelist_add(const char *comm);

/* 获取配置 */
void ai_kill_get_config(struct ai_kill_config *cfg);

/* 设置配置 */
int ai_kill_set_config(const struct ai_kill_config *cfg);

#endif /* __KERNEL__ */

#endif /* AINOS_AI_KILL_H */