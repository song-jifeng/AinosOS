// ================================================================
// Ainos OS - AI KILL 智能进程管理器 (深度实现 v2.0.0)
// ================================================================
//
// 架构:
//   ┌─────────────────────────────────────────────────────────┐
//   │              AI KILL 智能进程管理器                        │
//   ├─────────────────────────────────────────────────────────┤
//   │  ┌──────────────────┐  ┌───────────────────────────┐    │
//   │  │ 进程扫描器 (定时器) │  │ 行为跟踪器                 │    │
//   │  │ • 多维度评分       │  │ • RSS 趋势               │    │
//   │  │ • 加权综合        │  │ • CPU 趋势               │    │
//   │  │ • 白名单过滤      │  │ • 内存泄漏检测            │    │
//   │  └────────┬─────────┘  └───────────────┬───────────┘    │
//   │           ▼                              ▼               │
//   │  ┌──────────────────────────────────────────────────┐    │
//   │  │ 策略引擎                                          │    │
//   │  │ 评分 → 分级 → 动作选择                             │    │
//   │  │ 阈值: WARN(40) → TERM(60) → KILL(80) → GROUP(90)│    │
//   │  └──────────────────────┬───────────────────────────┘    │
//   │                         ▼                                 │
//   │  ┌──────────────────────────────────────────────────┐    │
//   │  │ 执行器                                            │    │
//   │  │ • SIGTERM → 等待 → SIGKILL                       │    │
//   │  │ • 进程组杀戮                                     │    │
//   │  │ • 通知自愈模块                                   │    │
//   │  │ • 速率限制                                       │    │
//   │  └──────────────────────────────────────────────────┘    │
//   │                                                          │
//   │  ┌──────────────────────────────────────────────────┐    │
//   │  │ /proc/ai-kill 接口                                │    │
//   │  │ scores | config | stats | history | behavior      │    │
//   │  └──────────────────────────────────────────────────┘    │
//   └─────────────────────────────────────────────────────────┘
//
// 评分维度:
//   CPU(20) + MEM(25) + IO(15) + NET(10) + AGE(10) + LEAK(20)
//   - CRITICALITY(20)
//   总分 = max(0, Σ(weight * score) / Σ(weight))
//
// ================================================================

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/sched.h>
#include <linux/sched/signal.h>
#include <linux/sched/cputime.h>
#include <linux/mm.h>
#include <linux/mmzone.h>
#include <linux/swap.h>
#include <linux/fs.h>
#include <linux/proc_fs.h>
#include <linux/seq_file.h>
#include <linux/timer.h>
#include <linux/workqueue.h>
#include <linux/slab.h>
#include <linux/string.h>
#include <linux/uaccess.h>
#include <linux/atomic.h>
#include <linux/pid.h>
#include <linux/pid_namespace.h>
#include <linux/fdtable.h>
#include <linux/oom.h>
#include <linux/version.h>
#include <linux/timekeeping.h>
#include <linux/ctype.h>
#include <linux/rcupdate.h>

#include "ai_kill.h"

/* ================================================================
 * 模块参数
 * ================================================================ */

static unsigned int scan_interval_ms = 3000;
module_param(scan_interval_ms, uint, 0644);
MODULE_PARM_DESC(scan_interval_ms, "进程扫描间隔 (ms)");

static unsigned int threshold_warn = 40;
module_param(threshold_warn, uint, 0644);
MODULE_PARM_DESC(threshold_warn, "警告阈值 (0-100)");

static unsigned int threshold_term = 60;
module_param(threshold_term, uint, 0644);
MODULE_PARM_DESC(threshold_term, "SIGTERM 阈值 (0-100)");

static unsigned int threshold_kill = 80;
module_param(threshold_kill, uint, 0644);
MODULE_PARM_DESC(threshold_kill, "SIGKILL 阈值 (0-100)");

static unsigned int max_kills_per_scan = 3;
module_param(max_kills_per_scan, uint, 0644);
MODULE_PARM_DESC(max_kills_per_scan, "每次扫描最多杀进程数");

static unsigned int rate_limit_ms = 10000;
module_param(rate_limit_ms, uint, 0644);
MODULE_PARM_DESC(rate_limit_ms, "杀进程速率限制 (ms)");

static bool protect_init = true;
module_param(protect_init, bool, 0644);
MODULE_PARM_DESC(protect_init, "保护 init 进程");

static bool protect_kthreads = true;
module_param(protect_kthreads, bool, 0644);
MODULE_PARM_DESC(protect_kthreads, "保护内核线程");

static char *whitelist_str = "";
module_param(whitelist_str, charp, 0644);
MODULE_PARM_DESC(whitelist_str, "白名单进程名 (逗号分隔)");

MODULE_LICENSE("MIT");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("AI KILL - intelligent process manager (deep implementation)");
MODULE_VERSION(AI_KILL_VERSION);

/* ================================================================
 * 常量定义
 * ================================================================ */

#define BEHAVIOR_TABLE_SIZE   256  /* 行为跟踪表大小 */
#define BEHAVIOR_SAMPLES      3    /* 每个进程采样数 */
#define WHITELIST_MAX         32   /* 白名单最大条目数 */
#define HISTORY_MAX           128  /* 杀戮历史最大记录数 */
#define COMM_LEN              TASK_COMM_LEN

/* 默认权重 */
static const unsigned int default_weights[AI_KILL_DIM_COUNT] = {
    [AI_KILL_DIM_CPU]           = 20,
    [AI_KILL_DIM_MEM]           = 25,
    [AI_KILL_DIM_IO]            = 15,
    [AI_KILL_DIM_NET]           = 10,
    [AI_KILL_DIM_AGE]           = 10,
    [AI_KILL_DIM_CRITICALITY]   = 20,
    [AI_KILL_DIM_LEAK]          = 20,
};

/* ================================================================
 * 数据结构
 * ================================================================ */

/* 行为样本 */
struct behavior_sample {
    u64 rss_bytes;
    u64 cpu_ns;
    u64 io_bytes;
    u64 timestamp_ns;
};

/* 进程行为跟踪 */
struct behavior_entry {
    pid_t  pid;
    char   comm[COMM_LEN];
    struct behavior_sample samples[BEHAVIOR_SAMPLES];
    unsigned int sample_idx;   /* 当前写入位置 */
    unsigned int sample_count; /* 已采样次数 */
    unsigned long last_jiffies;
    /* 内存泄漏检测: 基线 RSS 和移动平均状态 */
    u64    rss_baseline;       /* 基线 RSS (首次稳定后的值) */
    bool   baseline_valid;     /* 基线是否已建立 */
};

/* 杀戮历史 */
struct kill_history {
    struct ai_kill_record entries[HISTORY_MAX];
    unsigned int head;
    unsigned int count;
    spinlock_t lock;
};

/* AI KILL 全局状态 */
static struct {
    /* 配置 */
    struct ai_kill_config config;
    struct mutex config_lock;

    /* 行为跟踪表 */
    struct behavior_entry *behavior_table;
    spinlock_t behavior_lock;

    /* 白名单 */
    char whitelist[WHITELIST_MAX][COMM_LEN];
    int whitelist_count;

    /* 统计 */
    struct ai_kill_stats stats;

    /* 杀戮历史 */
    struct kill_history history;

    /* 扫描定时器和工作队列 */
    struct timer_list scan_timer;
    struct workqueue_struct *scan_wq;
    struct work_struct scan_work;

    /* 速率限制 */
    unsigned long last_kill_jiffies;
    unsigned int  kills_this_minute;       /* 当前分钟内的杀戮数 */
    unsigned int  kills_per_minute_max;    /* 每分钟最大杀戮数 (默认 10) */
    unsigned long kills_minute_start;      /* 当前分钟的开始 jiffies */

    /* /proc 条目 */
    struct proc_dir_entry *proc_dir;
    struct proc_dir_entry *proc_scores;
    struct proc_dir_entry *proc_config;
    struct proc_dir_entry *proc_stats;
    struct proc_dir_entry *proc_history;
    struct proc_dir_entry *proc_behavior;

    /* 运行标志 */
    bool initialized;
} g_ai_kill;

/* ================================================================
 * 辅助函数
 * ================================================================ */

static const char *action_name(enum ai_kill_action action)
{
    switch (action) {
    case AI_KILL_ACTION_NONE:  return "none";
    case AI_KILL_ACTION_LOG:   return "log";
    case AI_KILL_ACTION_WARN:  return "warn";
    case AI_KILL_ACTION_TERM:  return "term";
    case AI_KILL_ACTION_KILL:  return "kill";
    case AI_KILL_ACTION_GROUP: return "group";
    default:                   return "unknown";
    }
}

/* ================================================================
 * 白名单管理
 *
 * 白名单检查在评分之前执行, 确保关键进程不被误杀.
 * 默认保护: init (pid=1) 和核心系统进程.
 * ================================================================ */

/* 默认受保护的系统进程名列表 */
static const char * const default_protected_processes[] = {
    "init",            /* 容器/传统 init */
    "systemd",         /* 现代 init/systemd */
    "sshd",            /* SSH 守护进程 */
    "cron",            /* 定时任务 */
    "rsyslogd",        /* 系统日志 */
    "dbus-daemon",     /* D-Bus 消息总线 */
    "NetworkManager",  /* 网络管理 */
    "login",           /* 登录进程 */
    "getty",           /* 终端 */
    "agetty",          /* 替代 getty */
    "auditd",          /* 审计 */
    "polkitd",         /* 授权管理器 */
    "udevd",           /* 设备管理 */
    "systemd-journald",/* 日志 */
    "systemd-logind",  /* 登录管理 */
    "systemd-udevd",   /* 设备管理 */
    "systemd-resolved",/* DNS 解析 */
    "systemd-timesyncd", /* 时间同步 */
    "kthreadd",        /* 内核线程守护进程 */
    "rcu_sched",       /* RCU 内核线程 */
    "watchdogd",       /* 看门狗 */
    NULL               /* 哨兵 */
};

/* 添加默认系统保护进程到白名单 */
static void whitelist_add_defaults(void)
{
    int count = g_ai_kill.whitelist_count;
    for (int i = 0; default_protected_processes[i] && count < WHITELIST_MAX; i++) {
        bool already = false;
        for (int j = 0; j < count; j++) {
            if (strncmp(g_ai_kill.whitelist[j],
                        default_protected_processes[i], COMM_LEN) == 0) {
                already = true;
                break;
            }
        }
        if (!already) {
            strscpy(g_ai_kill.whitelist[count],
                    default_protected_processes[i], COMM_LEN);
            count++;
        }
    }
    g_ai_kill.whitelist_count = count;
}

static int whitelist_init(const char *str)
{
    char buf[256];
    char *token;
    int count = 0;

    g_ai_kill.whitelist_count = 0;

    /* 先添加用户配置的白名单 */
    if (str && strlen(str) > 0) {
        strscpy(buf, str, sizeof(buf));

        token = strsep(&buf, ",");
        while (token && count < WHITELIST_MAX) {
            /* 去除前后空格 */
            while (*token == ' ') token++;
            char *end = token + strlen(token) - 1;
            while (end > token && *end == ' ') end--;
            *(end + 1) = '\0';

            if (strlen(token) > 0) {
                strscpy(g_ai_kill.whitelist[count], token, COMM_LEN);
                count++;
                pr_info("ai-kill: whitelist: '%s'\n", token);
            }
            token = strsep(&buf, ",");
        }
    }

    g_ai_kill.whitelist_count = count;

    /* 然后添加默认系统保护进程 (确保关键进程始终受保护) */
    whitelist_add_defaults();

    pr_info("ai-kill: whitelist initialized with %d entries\n",
            g_ai_kill.whitelist_count);
    return g_ai_kill.whitelist_count;
}

static bool whitelist_check(const char *comm)
{
    /* 保护空指针 */
    if (!comm)
        return true;

    for (int i = 0; i < g_ai_kill.whitelist_count; i++) {
        if (strncmp(comm, g_ai_kill.whitelist[i], COMM_LEN) == 0)
            return true;
    }
    return false;
}

int ai_kill_whitelist_add(const char *comm)
{
    if (!comm || g_ai_kill.whitelist_count >= WHITELIST_MAX)
        return -EINVAL;

    strscpy(g_ai_kill.whitelist[g_ai_kill.whitelist_count], comm, COMM_LEN);
    g_ai_kill.whitelist_count++;
    pr_info("ai-kill: added to whitelist: '%s'\n", comm);
    return 0;
}
EXPORT_SYMBOL_GPL(ai_kill_whitelist_add);

/* ================================================================
 * 行为跟踪
 *
 * 锁顺序:
 *   behavior_lock (spinlock_irqsave) -> RCU (rcu_read_lock)
 *
 * 行为跟踪表 (behavior_table) 使用 RCU 保护指针:
 *   - 写入端: behavior_init() 用 rcu_assign_pointer() 赋值,
 *             behavior_destroy() 用 rcu_assign_pointer(NULL) + synchronize_rcu() + kfree()
 *   - 读取端: 所有路径用 rcu_dereference() 获取指针,
 *             /proc 读路径额外包裹 rcu_read_lock()/rcu_read_unlock()
 *   - 条目级操作: 统一由 behavior_lock (spinlock, irq-safe) 保护,
 *                timer 上下文和 /proc 上下文均可安全使用
 * ================================================================ */

static int behavior_init(void)
{
    struct behavior_entry *table;

    table = kzalloc(BEHAVIOR_TABLE_SIZE * sizeof(struct behavior_entry),
                    GFP_KERNEL);
    if (!table)
        return -ENOMEM;

    spin_lock_init(&g_ai_kill.behavior_lock);
    rcu_assign_pointer(g_ai_kill.behavior_table, table);
    return 0;
}

static void behavior_destroy(void)
{
    struct behavior_entry *table;

    /* 用 RCU 安全地移除指针, 等待所有读端完成后再释放 */
    table = rcu_dereference_protected(g_ai_kill.behavior_table,
                                      lockdep_is_held(&g_ai_kill.behavior_lock) ||
                                      !g_ai_kill.initialized);
    rcu_assign_pointer(g_ai_kill.behavior_table, NULL);
    synchronize_rcu();
    kfree(table);
}

/* 查找或创建行为条目
 * 注意: 调用者必须持有 behavior_lock
 */
static struct behavior_entry *behavior_lookup(pid_t pid)
{
    struct behavior_entry *table;
    unsigned int hash;
    struct behavior_entry *entry;
    unsigned int start;

    table = rcu_dereference(g_ai_kill.behavior_table);
    if (!table)
        return NULL;

    hash = (unsigned int)pid % BEHAVIOR_TABLE_SIZE;
    entry = &table[hash];

    /* 如果条目已被占用且不是同一个 PID，尝试线性探测 */
    start = hash;
    while (entry->pid != 0 && entry->pid != pid) {
        hash = (hash + 1) % BEHAVIOR_TABLE_SIZE;
        if (hash == start)
            return NULL; /* 表满了 */
        entry = &table[hash];
    }

    return entry;
}

/* 记录进程行为样本 */
static void behavior_record(struct task_struct *task)
{
    struct behavior_entry *entry;
    struct mm_struct *mm;
    unsigned long flags;

    /* 跳过内核线程 */
    if (task->flags & PF_KTHREAD)
        return;

    spin_lock_irqsave(&g_ai_kill.behavior_lock, flags);

    entry = behavior_lookup(task_tgid_nr(task));
    if (!entry) {
        spin_unlock_irqrestore(&g_ai_kill.behavior_lock, flags);
        return;
    }

    /* 初始化新条目 */
    if (entry->pid == 0) {
        entry->pid = task_tgid_nr(task);
        strscpy(entry->comm, task->comm, COMM_LEN);
        entry->sample_idx = 0;
        entry->sample_count = 0;
    }

    /* 记录样本 */
    unsigned int idx = entry->sample_idx % BEHAVIOR_SAMPLES;
    struct behavior_sample *s = &entry->samples[idx];

    s->timestamp_ns = ktime_get_real_ns();
    s->cpu_ns = (u64)task->utime + (u64)task->stime;

    mm = get_task_mm(task);
    if (mm) {
        s->rss_bytes = get_mm_rss(mm) * PAGE_SIZE;
        mmput(mm);
    } else {
        s->rss_bytes = 0;
    }

    s->io_bytes = task->ioac.read_bytes + task->ioac.write_bytes;
    entry->last_jiffies = jiffies;
    entry->sample_idx++;
    if (entry->sample_count < BEHAVIOR_SAMPLES)
        entry->sample_count++;

    /* 更新 RSS 基线用于泄漏检测 */
    update_rss_baseline(entry);

    spin_unlock_irqrestore(&g_ai_kill.behavior_lock, flags);
}

/* 清除退出进程的行为记录 */
static void behavior_cleanup(pid_t pid)
{
    struct behavior_entry *entry;
    unsigned long flags;

    spin_lock_irqsave(&g_ai_kill.behavior_lock, flags);
    entry = behavior_lookup(pid);
    if (entry && entry->pid == pid) {
        memset(entry, 0, sizeof(*entry));
    }
    spin_unlock_irqrestore(&g_ai_kill.behavior_lock, flags);
}

/* 检测内存泄漏趋势 - 使用速率变化检测
 *
 * 原理:
 *   - 维护一个 3 样本移动平均作为基线
 *   - 仅当最新 RSS 超过移动平均 20% 且总增长 > 1MB 时标记泄漏
 *   - 使用 rss_baseline 跟踪长期基线，避免误报短期波动
 *
 * 该算法比简单的"3 次连续增长"更可靠，因为:
 *   1. 需要幅度条件 (20% + 1MB)，忽略微小波动
 *   2. 基线跟踪避免系统性地把增长进程误判为泄漏
 *   3. 移动平均平滑了瞬时尖峰
 */
static int detect_memory_leak(const struct behavior_entry *entry)
{
    u64 rss_now;
    u64 moving_avg;
    u64 baseline;
    u64 growth_from_baseline;
    unsigned int pct_above_avg;
    unsigned int i, count;

    if (entry->sample_count < 3)
        return 0;

    /* 计算 3 样本移动平均 */
    moving_avg = 0;
    count = min(entry->sample_count, BEHAVIOR_SAMPLES);
    for (i = 0; i < count; i++)
        moving_avg += entry->samples[i].rss_bytes;
    moving_avg /= count;

    /* 最新 RSS */
    rss_now = entry->samples[(entry->sample_idx - 1) % BEHAVIOR_SAMPLES].rss_bytes;

    /* 基线尚未建立: 用移动平均初始化 */
    if (!entry->baseline_valid) {
        /* 允许在第一次检测时静默建立基线，不触发警报 */
        return 0;
    }

    baseline = entry->rss_baseline;

    /* 条件 1: 最新 RSS 超过移动平均 20% 以上 */
    if (moving_avg == 0)
        return 0;
    pct_above_avg = (unsigned int)((rss_now - min(rss_now, moving_avg)) * 100 / moving_avg);
    if (pct_above_avg < 20)
        return 0;

    /* 条件 2: 从基线增长超过 1MB */
    if (baseline == 0)
        return 0;
    growth_from_baseline = rss_now - min(rss_now, baseline);
    if (growth_from_baseline < (u64)1024 * 1024)  /* < 1MB */
        return 0;

    /* 两个条件都满足: 计算泄漏分数 (0-100) */
    {
        unsigned int growth_pct = (unsigned int)(growth_from_baseline * 100 / baseline);
        /* 增长率 20% -> 分数 20, 增长率 100%+ -> 分数 100 */
        return min(growth_pct, 100u);
    }
}

/* 更新 RSS 基线 (在 behavior_record 中定期调用) */
static void update_rss_baseline(struct behavior_entry *entry)
{
    u64 avg = 0;
    unsigned int i, count;

    if (entry->sample_count < 2)
        return;

    /* 计算移动平均 */
    count = min(entry->sample_count, BEHAVIOR_SAMPLES);
    for (i = 0; i < count; i++)
        avg += entry->samples[i].rss_bytes;
    avg /= count;

    if (!entry->baseline_valid) {
        /* 首次建立基线 */
        entry->rss_baseline = avg;
        entry->baseline_valid = true;
        return;
    }

    /* 如果当前 RSS 回落到基线附近 (波动 < 10%), 更新基线 */
    if (avg > entry->rss_baseline) {
        u64 delta = avg - entry->rss_baseline;
        if (delta * 100 / max(entry->rss_baseline, (u64)1) < 10)
            entry->rss_baseline = avg;
    } else {
        u64 delta = entry->rss_baseline - avg;
        if (delta * 100 / max(entry->rss_baseline, (u64)1) < 10)
            entry->rss_baseline = avg;
        else
            entry->rss_baseline = avg; /* 明显下降: 重置基线 */
    }
}

/* ================================================================
 * 评分引擎
 * ================================================================ */

/* CPU 评分: 基于最近 CPU 使用率 */
static unsigned int calc_cpu_score(struct task_struct *task,
                                    const struct behavior_entry *be)
{
    u64 total_cpu = (u64)task->utime + (u64)task->stime;
    u64 now = jiffies;
    u64 elapsed = (now - (be ? be->last_jiffies : (now - HZ))) * 1000 / HZ;

    if (elapsed == 0 || total_cpu == 0)
        return 0;

    /* CPU 使用率 = cpu_time / wall_time */
    unsigned int pct = (unsigned int)(total_cpu * 100 / (elapsed + 1));

    if (pct > 90) return 100;
    if (pct > 80) return 80;
    if (pct > 60) return 60;
    if (pct > 40) return 40;
    if (pct > 20) return 20;
    return 0;
}

/* 内存评分: 基于 RSS 和 swap 使用 */
static unsigned int calc_mem_score(struct task_struct *task)
{
    struct mm_struct *mm;
    unsigned int score = 0;
    unsigned long rss_mb;
    unsigned long total_ram_mb;
    unsigned long avail_mb;

    mm = get_task_mm(task);
    if (!mm)
        return 0;

    rss_mb = get_mm_rss(mm) * PAGE_SIZE / (1024 * 1024);
    mmput(mm);

    total_ram_mb = (totalram_pages() + total_swap_pages()) * 4 / 1024;
    avail_mb = si_mem_available(NULL) * 4 / 1024;

    /* 绝对内存占用评分 */
    if (rss_mb > 1024)     score = 100;
    else if (rss_mb > 512) score = 80;
    else if (rss_mb > 256) score = 60;
    else if (rss_mb > 128) score = 40;
    else if (rss_mb > 64)  score = 20;

    /* 相对内存占用评分 (占系统内存比例) */
    if (total_ram_mb > 0 && rss_mb > 0) {
        unsigned int pct = (unsigned int)(rss_mb * 100 / total_ram_mb);
        if (pct > 30) score = max(score, 90u);
        else if (pct > 20) score = max(score, 70u);
        else if (pct > 10) score = max(score, 50u);
    }

    /* 系统内存紧张时加重评分 */
    if (avail_mb < total_ram_mb / 20) {
        /* 可用内存 < 5%，加重 */
        score = min(score + 20, 100u);
    }

    return score;
}

/* IO 评分: 基于 IO 操作数 */
static unsigned int calc_io_score(struct task_struct *task)
{
    u64 io_total = task->ioac.read_bytes + task->ioac.write_bytes;
    u64 io_count = task->ioac.syscfs;  /* IO 系统调用次数(近似) */

    if (io_total == 0 && io_count == 0)
        return 0;

    /* 使用 IO 总量作为评分依据 */
    if (io_total > (u64)1024 * 1024 * 1024)  /* > 1GB */
        return 80;
    if (io_total > (u64)512 * 1024 * 1024)   /* > 512MB */
        return 60;
    if (io_total > (u64)100 * 1024 * 1024)   /* > 100MB */
        return 40;
    if (io_total > (u64)10 * 1024 * 1024)    /* > 10MB */
        return 20;

    return 0;
}

/* 网络评分: 基于文件描述符 (socket 计数) */
static unsigned int calc_net_score(struct task_struct *task)
{
    struct files_struct *files;
    struct fdtable *fdt;
    unsigned int total_fds = 0;

    files = get_files_struct(task);
    if (!files)
        return 0;

    spin_lock(&files->file_lock);
    fdt = files_fdtable(files);
    total_fds = fdt->max_fds;
    /* 注意: 我们无法轻易区分 socket 和普通文件描述符。
     * 这里使用文件描述符总数作为网络活动的近似。 */
    spin_unlock(&files->file_lock);
    put_files_struct(files);

    if (total_fds > 1000) return 80;
    if (total_fds > 500)  return 60;
    if (total_fds > 200)  return 40;
    if (total_fds > 100)  return 20;

    return 0;
}

/* 年龄评分: 越年轻的进程分数越高 (越容易被杀) */
static unsigned int calc_age_score(struct task_struct *task)
{
    unsigned long age_seconds = (jiffies - task->start_time) / HZ;

    /* 运行不到 1 分钟: 高分数 (容易被杀) */
    if (age_seconds < 60)
        return 80;
    /* 运行不到 10 分钟 */
    if (age_seconds < 600)
        return 50;
    /* 运行不到 1 小时 */
    if (age_seconds < 3600)
        return 30;
    /* 运行超过 1 小时: 低分数 (不容易被杀) */
    return 10;
}

/* 关键性评分: 越重要的进程分数越低 (越不容易被杀) */
static unsigned int calc_criticality_score(struct task_struct *task)
{
    pid_t pid = task_tgid_nr(task);

    /* init 进程 - 最高保护 */
    if (pid == 1)
        return 100;

    /* 检查 comm 名称 */
    const char *critical_processes[] = {
        "systemd", "init", "bash", "sh", "sshd",
        "cron", "rsyslogd", "dbus-daemon", "NetworkManager",
        "login", "getty", "agetty", "auditd", "polkitd",
        "udevd", "systemd-journald", "systemd-logind",
        "systemd-udevd", "systemd-resolved", "systemd-timesyncd",
        NULL
    };

    for (int i = 0; critical_processes[i]; i++) {
        if (strncmp(task->comm, critical_processes[i], COMM_LEN) == 0)
            return 90;
    }

    /* 内核线程 (不应该到这里，但以防万一) */
    if (task->flags & PF_KTHREAD)
        return 100;

    return 0;
}

/* 泄漏评分: 基于 RSS 增长趋势 */
static unsigned int calc_leak_score(const struct behavior_entry *be)
{
    if (!be)
        return 0;

    return (unsigned int)detect_memory_leak(be);
}

/* 计算综合评分
 *
 * 评分公式:
 *   total = max(0, Σ(weight * score) / Σ(weight))
 *   其中 CRITICALITY 维度为负权重 (保护重要进程)
 *
 * 校准步骤:
 *   1. 各维度归一化到 0-100
 *   2. 如果 CPU+MEM+IO > 100, 等比缩放使三者之和 <= 100
 *   3. 应用权重, CRITICALITY 取负贡献
 *   4. 最终结果钳位到 0-100
 */
static unsigned int calc_total_score(const struct ai_kill_score *score)
{
    unsigned int total_weight = 0;
    int weighted_sum = 0;  /* 有符号, 因为 CRITICALITY 贡献为负 */
    unsigned int normalized[AI_KILL_DIM_COUNT];

    /* Step 1: 各维度归一化到 0-100 */
    for (int i = 0; i < AI_KILL_DIM_COUNT; i++)
        normalized[i] = min(score->dims[i], 100u);

    /* Step 2: 资源维度约束检查
     * 如果 CPU + MEM + IO 之和 > 100, 等比缩放.
     * 这防止一个进程在多个资源维度同时高分时被过度惩罚.
     */
    {
        unsigned int sum = normalized[AI_KILL_DIM_CPU]
                         + normalized[AI_KILL_DIM_MEM]
                         + normalized[AI_KILL_DIM_IO];
        if (sum > 100) {
            unsigned int scale = 100;
            normalized[AI_KILL_DIM_CPU] = normalized[AI_KILL_DIM_CPU] * scale / sum;
            normalized[AI_KILL_DIM_MEM] = normalized[AI_KILL_DIM_MEM] * scale / sum;
            normalized[AI_KILL_DIM_IO]  = normalized[AI_KILL_DIM_IO]  * scale / sum;
        }
    }

    /* Step 3: 应用权重
     * CRITICALITY 是负权重: 越重要的进程得分越高, 但应该降低杀戮分数.
     * 因此 CRITICALITY 对加权和做负贡献.
     */
    for (int i = 0; i < AI_KILL_DIM_COUNT; i++) {
        unsigned int w = g_ai_kill.config.weights[i];
        if (i == AI_KILL_DIM_CRITICALITY) {
            /* 关键性越高, 杀戮分数越低 */
            weighted_sum -= (int)(normalized[i] * w);
        } else {
            weighted_sum += (int)(normalized[i] * w);
        }
        total_weight += w;
    }

    if (total_weight == 0)
        return 0;

    /* Step 4: 钳位到 0-100 */
    if (weighted_sum < 0)
        return 0;

    unsigned int total = (unsigned int)weighted_sum / total_weight;
    return min(total, 100u);
}

/* 确定建议动作 */
static enum ai_kill_action determine_action(unsigned int score)
{
    if (score >= g_ai_kill.config.threshold_kill)
        return AI_KILL_ACTION_KILL;
    if (score >= g_ai_kill.config.threshold_term)
        return AI_KILL_ACTION_TERM;
    if (score >= g_ai_kill.config.threshold_warn)
        return AI_KILL_ACTION_WARN;
    return AI_KILL_ACTION_NONE;
}

/* ================================================================
 * 执行器
 * ================================================================ */

/* 检查速率限制
 *
 * 双重限制:
 *   1. 短间隔限制: 两次杀戮之间至少间隔 rate_limit_ms
 *   2. 每分钟上限: 每分钟最多 kills_per_minute_max 次杀戮
 *
 * 返回 true 表示允许执行杀戮, false 表示需要节流.
 */
static bool rate_limit_check(void)
{
    unsigned long now = jiffies;

    /* 重置每分钟计数器 (每分钟滚动一次) */
    if (g_ai_kill.kills_minute_start == 0) {
        g_ai_kill.kills_minute_start = now;
    } else if (time_after_eq(now, g_ai_kill.kills_minute_start + HZ * 60)) {
        /* 超过一分钟, 重置计数器 */
        g_ai_kill.kills_this_minute = 0;
        g_ai_kill.kills_minute_start = now;
    }

    /* 检查每分钟上限 */
    if (g_ai_kill.kills_this_minute >= g_ai_kill.kills_per_minute_max) {
        pr_debug("ai-kill: rate limit: kills/min exceeded (%u >= %u)\n",
                 g_ai_kill.kills_this_minute,
                 g_ai_kill.kills_per_minute_max);
        return false;
    }

    /* 检查短间隔限制 */
    unsigned long interval = msecs_to_jiffies(rate_limit_ms);
    if (time_before(now, g_ai_kill.last_kill_jiffies + interval)) {
        pr_debug("ai-kill: rate limit: interval too short (%lu < %lu)\n",
                 now - g_ai_kill.last_kill_jiffies, interval);
        return false;
    }

    /* 通过限制, 记录本次杀戮 */
    g_ai_kill.last_kill_jiffies = now;
    g_ai_kill.kills_this_minute++;
    return true;
}

/* 安全地杀进程 */
static int ai_kill_do_kill(pid_t pid, enum ai_kill_action action)
{
    struct task_struct *task;
    int ret = -EINVAL;

    if (pid <= 1)
        return -EPERM;

    task = get_pid_task(find_vpid(pid), PIDTYPE_PID);
    if (!task)
        return -ESRCH;

    /* 安全检查 */
    if (task->flags & PF_KTHREAD) {
        put_task_struct(task);
        return -EPERM;
    }

    /* 白名单检查 (安全网, 防止外部调用绕过白名单) */
    if (whitelist_check(task->comm)) {
        pr_info("ai-kill: whitelist protected '%s' (pid=%d)\n",
                task->comm, pid);
        g_ai_kill.stats.whitelist_hits++;
        put_task_struct(task);
        return -EPERM;
    }

    switch (action) {
    case AI_KILL_ACTION_TERM:
        pr_info("ai-kill: SIGTERM %s (pid=%d)\n", task->comm, pid);
        ret = send_sig(SIGTERM, task, 0);
        if (ret == 0)
            g_ai_kill.stats.actions_term++;
        break;

    case AI_KILL_ACTION_KILL:
        pr_info("ai-kill: SIGKILL %s (pid=%d)\n", task->comm, pid);
        ret = send_sig(SIGKILL, task, 0);
        if (ret == 0) {
            g_ai_kill.stats.actions_kill++;
            /* 清理行为记录 */
            behavior_cleanup(pid);
        }
        break;

    case AI_KILL_ACTION_GROUP: {
        /* 杀死整个进程组: 使用 task_pgrp() 获取进程组 PID 结构 */
        struct pid *pgrp = task_pgrp(task);
        if (!pgrp) {
            pr_warn("ai-kill: cannot get process group for %s (pid=%d)\n",
                    task->comm, pid);
            ret = -ESRCH;
            break;
        }
        pr_info("ai-kill: killing group of %s (pid=%d)\n", task->comm, pid);
        ret = kill_pgrp(pgrp, SIGKILL, 1);
        if (ret == 0)
            g_ai_kill.stats.actions_group++;
        break;
    }
        break;
    }

    case AI_KILL_ACTION_LOG:
        ret = 0;
        g_ai_kill.stats.actions_log++;
        break;

    case AI_KILL_ACTION_WARN:
        pr_warn("ai-kill: WARN %s (pid=%d) score=%u\n",
                task->comm, pid, 0u);
        ret = 0;
        g_ai_kill.stats.actions_warn++;
        break;

    default:
        ret = -EINVAL;
        break;
    }

    if (ret < 0)
        g_ai_kill.stats.actions_failed++;

    put_task_struct(task);
    return ret;
}

/* ================================================================
 * 杀戮历史记录
 * ================================================================ */

static void history_init(void)
{
    memset(&g_ai_kill.history, 0, sizeof(g_ai_kill.history));
    spin_lock_init(&g_ai_kill.history.lock);
}

static void history_add(pid_t pid, const char *comm,
                         unsigned int score,
                         enum ai_kill_action action,
                         int result, const char *reason)
{
    unsigned long flags;

    spin_lock_irqsave(&g_ai_kill.history.lock, flags);

    struct ai_kill_record *rec = &g_ai_kill.history.entries[
        g_ai_kill.history.head];

    rec->timestamp_ns = ktime_get_real_ns();
    rec->pid = pid;
    strscpy(rec->comm, comm ?: "?", COMM_LEN);
    rec->total_score = score;
    rec->action = action;
    rec->result = result;
    strscpy(rec->reason, reason ?: "", sizeof(rec->reason));

    g_ai_kill.history.head = (g_ai_kill.history.head + 1) % HISTORY_MAX;
    if (g_ai_kill.history.count < HISTORY_MAX)
        g_ai_kill.history.count++;

    spin_unlock_irqrestore(&g_ai_kill.history.lock, flags);
}

/* ================================================================
 * 扫描器
 * ================================================================ */

/* 扫描所有进程，计算评分，执行动作 */
static void scan_processes(struct work_struct *work)
{
    struct task_struct *task;
    struct ai_kill_score *scores;
    int score_count = 0;
    int score_capacity = 256;
    u64 scan_start = ktime_get_real_ns();
    int killed = 0;

    if (!g_ai_kill.initialized || !g_ai_kill.config.enabled)
        return;

    /* 分配评分数组 */
    scores = kmalloc_array(score_capacity, sizeof(struct ai_kill_score),
                            GFP_KERNEL);
    if (!scores) {
        pr_warn("ai-kill: cannot allocate score array\n");
        return;
    }

    g_ai_kill.stats.scans_total++;

    /* 遍历所有进程并评分 */
    rcu_read_lock();
    for_each_process(task) {
        struct behavior_entry *be;
        struct ai_kill_score *s;
        unsigned long flags;

        if (score_count >= score_capacity)
            break;

        /* 跳过内核线程 */
        if (task->flags & PF_KTHREAD)
            continue;

        /* 跳过退出中的进程 */
        if (task->exit_state)
            continue;

        /* 保护 init (pid <= 1) */
        if (protect_init && task_tgid_nr(task) <= 1)
            continue;

        s = &scores[score_count];
        memset(s, 0, sizeof(*s));

        s->pid = task_tgid_nr(task);
        strscpy(s->comm, task->comm, COMM_LEN);
        s->oom_score_adj = task->signal->oom_score_adj;

        /* 白名单检查: 在评分之前执行, 保护关键进程不被误判 */
        if (whitelist_check(s->comm)) {
            g_ai_kill.stats.whitelist_hits++;
            continue;
        }

        /* 获取行为记录 */
        spin_lock_irqsave(&g_ai_kill.behavior_lock, flags);
        be = behavior_lookup(s->pid);
        if (be && be->pid != s->pid)
            be = NULL;
        spin_unlock_irqrestore(&g_ai_kill.behavior_lock, flags);

        /* 记录当前行为样本 */
        behavior_record(task);

        /* 计算各维度评分 */
        s->dims[AI_KILL_DIM_CPU] = calc_cpu_score(task, be);
        s->dims[AI_KILL_DIM_MEM] = calc_mem_score(task);
        s->dims[AI_KILL_DIM_IO]  = calc_io_score(task);
        s->dims[AI_KILL_DIM_NET] = calc_net_score(task);
        s->dims[AI_KILL_DIM_AGE] = calc_age_score(task);
        s->dims[AI_KILL_DIM_CRITICALITY] = calc_criticality_score(task);
        s->dims[AI_KILL_DIM_LEAK] = calc_leak_score(be);

        /* 计算综合评分 */
        s->total = calc_total_score(s);

        /* 确定建议动作 */
        s->action = determine_action(s->total);

        score_count++;
    }
    rcu_read_unlock();

    g_ai_kill.stats.current_victims = 0;
    g_ai_kill.stats.top_score = 0;

    /* 按评分排序 (部分选择排序, 只取前 max_kills_per_scan 个候选) */
    if (score_count > 0 && g_ai_kill.config.enabled) {
        int candidates = min(score_count, (int)score_capacity);

        for (int i = 0; i < candidates; i++) {
            int best = i;
            for (int j = i + 1; j < score_count; j++) {
                if (scores[j].total > scores[best].total)
                    best = j;
            }

            if (best != i) {
                struct ai_kill_score tmp = scores[i];
                scores[i] = scores[best];
                scores[best] = tmp;
            }

            struct ai_kill_score *s = &scores[i];

            if (s->total > g_ai_kill.stats.top_score)
                g_ai_kill.stats.top_score = s->total;

            /* 执行动作 (仅对超过阈值的) */
            if (s->action >= AI_KILL_ACTION_TERM) {
                g_ai_kill.stats.scans_with_candidates++;
                g_ai_kill.stats.current_victims++;

                /* 速率限制: 每扫描周期最多 max_kills_per_scan 次杀戮 */
                if (killed >= (int)g_ai_kill.config.max_kills_per_scan) {
                    pr_debug("ai-kill: max kills per scan reached (%d)\n", killed);
                    break;
                }

                /* 速率限制: 检查间隔和每分钟上限 */
                if (s->action >= AI_KILL_ACTION_KILL) {
                    if (!rate_limit_check()) {
                        pr_debug("ai-kill: rate limited, skipping %s (pid=%d)\n",
                                 s->comm, s->pid);
                        continue;
                    }
                }

                int ret = ai_kill_do_kill(s->pid, s->action);

                history_add(s->pid, s->comm, s->total,
                            s->action, ret,
                            s->action >= AI_KILL_ACTION_KILL ?
                            "high score" : "elevated score");

                if (ret == 0)
                    killed++;
            }
        }
    }

    kfree(scores);

    g_ai_kill.stats.last_scan_duration_ns =
        ktime_get_real_ns() - scan_start;

    if (killed > 0) {
        pr_info("ai-kill: scan complete: %d/%d candidates killed (%llu ns)\n",
                killed, g_ai_kill.stats.current_victims,
                g_ai_kill.stats.last_scan_duration_ns);
    }
}

/* 定时器回调 */
static void scan_timer_cb(struct timer_list *t)
{
    if (g_ai_kill.initialized && g_ai_kill.scan_wq)
        queue_work(g_ai_kill.scan_wq, &g_ai_kill.scan_work);

    if (g_ai_kill.initialized)
        mod_timer(&g_ai_kill.scan_timer,
                  jiffies + msecs_to_jiffies(scan_interval_ms));
}

/* ================================================================
 * 导出函数
 * ================================================================ */

int ai_kill_get_score(pid_t pid, struct ai_kill_score *score)
{
    struct task_struct *task;
    struct behavior_entry *be = NULL;
    unsigned long flags;

    if (!score)
        return -EINVAL;

    task = get_pid_task(find_vpid(pid), PIDTYPE_PID);
    if (!task)
        return -ESRCH;

    memset(score, 0, sizeof(*score));
    score->pid = pid;
    strscpy(score->comm, task->comm, COMM_LEN);
    score->oom_score_adj = task->signal->oom_score_adj;

    /* 获取行为记录 */
    spin_lock_irqsave(&g_ai_kill.behavior_lock, flags);
    be = behavior_lookup(pid);
    if (be && be->pid != pid)
        be = NULL;
    spin_unlock_irqrestore(&g_ai_kill.behavior_lock, flags);

    score->dims[AI_KILL_DIM_CPU] = calc_cpu_score(task, be);
    score->dims[AI_KILL_DIM_MEM] = calc_mem_score(task);
    score->dims[AI_KILL_DIM_IO]  = calc_io_score(task);
    score->dims[AI_KILL_DIM_NET] = calc_net_score(task);
    score->dims[AI_KILL_DIM_AGE] = calc_age_score(task);
    score->dims[AI_KILL_DIM_CRITICALITY] = calc_criticality_score(task);
    score->dims[AI_KILL_DIM_LEAK] = calc_leak_score(be);
    score->total = calc_total_score(score);
    score->action = determine_action(score->total);

    score->rss_bytes = 0;
    struct mm_struct *mm = get_task_mm(task);
    if (mm) {
        score->rss_bytes = get_mm_rss(mm) * PAGE_SIZE;
        mmput(mm);
    }

    score->cpu_ns = (u64)task->utime + (u64)task->stime;
    score->nr_threads = task->signal->nr_threads;

    put_task_struct(task);
    return 0;
}
EXPORT_SYMBOL_GPL(ai_kill_get_score);

pid_t ai_kill_suggest_victim(void)
{
    struct task_struct *task;
    pid_t best_pid = 0;
    unsigned int best_score = 0;

    rcu_read_lock();
    for_each_process(task) {
        if (task->flags & PF_KTHREAD) continue;
        if (task->exit_state) continue;
        if (protect_init && task_tgid_nr(task) <= 1) continue;

        /* 白名单检查: 保护关键进程 */
        if (whitelist_check(task->comm))
            continue;

        struct ai_kill_score s;
        memset(&s, 0, sizeof(s));
        s.pid = task_tgid_nr(task);
        strscpy(s.comm, task->comm, COMM_LEN);

        s.dims[AI_KILL_DIM_MEM] = calc_mem_score(task);
        s.dims[AI_KILL_DIM_AGE] = calc_age_score(task);
        s.dims[AI_KILL_DIM_CRITICALITY] = calc_criticality_score(task);
        s.total = calc_total_score(&s);

        if (s.total > best_score) {
            best_score = s.total;
            best_pid = s.pid;
        }
    }
    rcu_read_unlock();

    return best_pid;
}
EXPORT_SYMBOL_GPL(ai_kill_suggest_victim);

int ai_kill_execute(pid_t pid, enum ai_kill_action action)
{
    if (action < AI_KILL_ACTION_TERM)
        return 0;

    return ai_kill_do_kill(pid, action);
}
EXPORT_SYMBOL_GPL(ai_kill_execute);

void ai_kill_get_config(struct ai_kill_config *cfg)
{
    if (cfg)
        *cfg = g_ai_kill.config;
}
EXPORT_SYMBOL_GPL(ai_kill_get_config);

int ai_kill_set_config(const struct ai_kill_config *cfg)
{
    if (!cfg)
        return -EINVAL;

    mutex_lock(&g_ai_kill.config_lock);
    g_ai_kill.config = *cfg;
    mutex_unlock(&g_ai_kill.config_lock);

    return 0;
}
EXPORT_SYMBOL_GPL(ai_kill_set_config);

/* ================================================================
 * /proc/ai-kill/scores
 * ================================================================ */

static int proc_scores_show(struct seq_file *m, void *v)
{
    struct task_struct *task;
    struct ai_kill_score *scores;
    int count = 0;
    int capacity = 512;

    scores = kmalloc_array(capacity, sizeof(struct ai_kill_score),
                            GFP_KERNEL);
    if (!scores)
        return -ENOMEM;

    seq_printf(m, "%-8s %-20s %6s %6s %6s %6s %6s %6s %6s %6s %6s\n",
               "PID", "COMM", "CPU", "MEM", "IO", "NET",
               "AGE", "CRIT", "LEAK", "TOTAL", "ACTION");

    rcu_read_lock();
    for_each_process(task) {
        if (task->flags & PF_KTHREAD) continue;
        if (count >= capacity) break;

        struct behavior_entry *be = NULL;
        unsigned long flags;

        pid_t pid = task_tgid_nr(task);
        spin_lock_irqsave(&g_ai_kill.behavior_lock, flags);
        be = behavior_lookup(pid);
        if (be && be->pid != pid) be = NULL;
        spin_unlock_irqrestore(&g_ai_kill.behavior_lock, flags);

        struct ai_kill_score *s = &scores[count];
        memset(s, 0, sizeof(*s));
        s->pid = pid;
        strscpy(s->comm, task->comm, COMM_LEN);

        s->dims[AI_KILL_DIM_CPU] = calc_cpu_score(task, be);
        s->dims[AI_KILL_DIM_MEM] = calc_mem_score(task);
        s->dims[AI_KILL_DIM_IO]  = calc_io_score(task);
        s->dims[AI_KILL_DIM_NET] = calc_net_score(task);
        s->dims[AI_KILL_DIM_AGE] = calc_age_score(task);
        s->dims[AI_KILL_DIM_CRITICALITY] = calc_criticality_score(task);
        s->dims[AI_KILL_DIM_LEAK] = calc_leak_score(be);
        s->total = calc_total_score(s);
        s->action = determine_action(s->total);

        count++;
    }
    rcu_read_unlock();

    /* 按总分排序 (冒泡, 仅显示前 50) */
    int display = min(count, 50);
    for (int i = 0; i < display; i++) {
        int best = i;
        for (int j = i + 1; j < count; j++) {
            if (scores[j].total > scores[best].total)
                best = j;
        }
        if (best != i) {
            struct ai_kill_score tmp = scores[i];
            scores[i] = scores[best];
            scores[best] = tmp;
        }

        struct ai_kill_score *s = &scores[i];
        seq_printf(m, "%-8d %-20s %6u %6u %6u %6u %6u %6u %6u %6u %6s\n",
                   s->pid, s->comm,
                   s->dims[AI_KILL_DIM_CPU],
                   s->dims[AI_KILL_DIM_MEM],
                   s->dims[AI_KILL_DIM_IO],
                   s->dims[AI_KILL_DIM_NET],
                   s->dims[AI_KILL_DIM_AGE],
                   s->dims[AI_KILL_DIM_CRITICALITY],
                   s->dims[AI_KILL_DIM_LEAK],
                   s->total,
                   action_name(s->action));
    }

    kfree(scores);
    return 0;
}

static int proc_scores_open(struct inode *inode, struct file *file)
{
    return single_open(file, proc_scores_show, NULL);
}

static const struct proc_ops proc_scores_fops = {
    .proc_open    = proc_scores_open,
    .proc_read    = seq_read,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

/* ================================================================
 * /proc/ai-kill/config
 * ================================================================ */

static int proc_config_show(struct seq_file *m, void *v)
{
    struct ai_kill_config *cfg = &g_ai_kill.config;

    mutex_lock(&g_ai_kill.config_lock);

    seq_printf(m, "%-20s = %s\n", "enabled", cfg->enabled ? "yes" : "no");
    seq_printf(m, "%-20s = %u ms\n", "scan_interval", cfg->scan_interval_ms);
    seq_printf(m, "%-20s = %u / %u / %u\n",
               "thresholds", cfg->threshold_warn,
               cfg->threshold_term, cfg->threshold_kill);
    seq_printf(m, "%-20s = %u\n", "max_kills_per_scan", cfg->max_kills_per_scan);
    seq_printf(m, "%-20s = %u ms\n", "rate_limit", cfg->rate_limit_ms);
    seq_printf(m, "%-20s = %s\n", "protect_init", cfg->protect_init ? "yes" : "no");
    seq_printf(m, "%-20s = %s\n", "protect_kthreads", cfg->protect_kthreads ? "yes" : "no");
    seq_printf(m, "\n");

    seq_printf(m, "%-10s = %s\n", "whitelist", whitelist_str);
    seq_printf(m, "\n");

    seq_printf(m, "%-12s %6s\n", "Dimension", "Weight");
    seq_printf(m, "%-12s %6s\n", "----------", "------");
    seq_printf(m, "%-12s %6u\n", "cpu", cfg->weights[AI_KILL_DIM_CPU]);
    seq_printf(m, "%-12s %6u\n", "mem", cfg->weights[AI_KILL_DIM_MEM]);
    seq_printf(m, "%-12s %6u\n", "io",  cfg->weights[AI_KILL_DIM_IO]);
    seq_printf(m, "%-12s %6u\n", "net", cfg->weights[AI_KILL_DIM_NET]);
    seq_printf(m, "%-12s %6u\n", "age", cfg->weights[AI_KILL_DIM_AGE]);
    seq_printf(m, "%-12s %6u\n", "criticality", cfg->weights[AI_KILL_DIM_CRITICALITY]);
    seq_printf(m, "%-12s %6u\n", "leak", cfg->weights[AI_KILL_DIM_LEAK]);

    mutex_unlock(&g_ai_kill.config_lock);
    return 0;
}

static int proc_config_open(struct inode *inode, struct file *file)
{
    return single_open(file, proc_config_show, NULL);
}

/*
 * 写入格式:
 *   "weight <dim> <value>"  - 设置权重
 *   "threshold <warn> <term> <kill>" - 设置阈值
 *   "interval <ms>"         - 设置扫描间隔
 *   "max_kill <n>"          - 设置每扫描最大杀戮数
 *   "rate_limit <ms>"       - 设置速率限制
 *   "enabled <0/1>"         - 启用/禁用
 *   "whitelist <str>"       - 设置白名单
 *   "reset"                 - 重置为默认值
 */
static ssize_t proc_config_write(struct file *file,
                                  const char __user *ubuf,
                                  size_t count, loff_t *ppos)
{
    char buf[256];
    char cmd[32];
    char arg1[64];
    unsigned int v1, v2, v3;
    int ret = count;

    if (count >= sizeof(buf))
        return -EINVAL;

    if (copy_from_user(buf, ubuf, count))
        return -EFAULT;
    buf[count] = '\0';
    if (count > 0 && buf[count - 1] == '\n')
        buf[count - 1] = '\0';

    /* 所有写操作必须持有 config_lock, 与 proc_config_show 互斥 */
    mutex_lock(&g_ai_kill.config_lock);

    if (strcmp(buf, "reset") == 0) {
        g_ai_kill.config.enabled = 1;
        g_ai_kill.config.scan_interval_ms = 3000;
        g_ai_kill.config.threshold_warn = 40;
        g_ai_kill.config.threshold_term = 60;
        g_ai_kill.config.threshold_kill = 80;
        g_ai_kill.config.max_kills_per_scan = 3;
        g_ai_kill.config.rate_limit_ms = 10000;
        g_ai_kill.config.protect_init = 1;
        g_ai_kill.config.protect_kthreads = 1;
        memcpy((void *)g_ai_kill.config.weights, default_weights,
               sizeof(default_weights));
        pr_info("ai-kill: config reset to defaults\n");
        goto out;
    }

    if (sscanf(buf, "weight %31s %u", arg1, &v1) == 2) {
        int dim = -1;
        if (strcmp(arg1, "cpu") == 0) dim = AI_KILL_DIM_CPU;
        else if (strcmp(arg1, "mem") == 0) dim = AI_KILL_DIM_MEM;
        else if (strcmp(arg1, "io") == 0)  dim = AI_KILL_DIM_IO;
        else if (strcmp(arg1, "net") == 0) dim = AI_KILL_DIM_NET;
        else if (strcmp(arg1, "age") == 0) dim = AI_KILL_DIM_AGE;
        else if (strcmp(arg1, "criticality") == 0) dim = AI_KILL_DIM_CRITICALITY;
        else if (strcmp(arg1, "leak") == 0) dim = AI_KILL_DIM_LEAK;

        if (dim >= 0) {
            g_ai_kill.config.weights[dim] = v1;
            pr_info("ai-kill: weight %s = %u\n", arg1, v1);
        }
        goto out;
    }

    if (sscanf(buf, "threshold %u %u %u", &v1, &v2, &v3) == 3) {
        /* 阈值必须合理: warn <= term <= kill, 且都在 0-100 范围 */
        if (v1 > 100 || v2 > 100 || v3 > 100 || v1 > v2 || v2 > v3) {
            pr_warn("ai-kill: invalid thresholds: %u/%u/%u\n", v1, v2, v3);
            ret = -EINVAL;
            goto out;
        }
        g_ai_kill.config.threshold_warn = v1;
        g_ai_kill.config.threshold_term = v2;
        g_ai_kill.config.threshold_kill = v3;
        goto out;
    }

    if (sscanf(buf, "interval %u", &v1) == 1) {
        if (v1 < 100 || v1 > 60000) {
            pr_warn("ai-kill: invalid interval: %u (100-60000 ms)\n", v1);
            ret = -EINVAL;
            goto out;
        }
        g_ai_kill.config.scan_interval_ms = v1;
        mod_timer(&g_ai_kill.scan_timer,
                  jiffies + msecs_to_jiffies(v1));
        goto out;
    }

    if (sscanf(buf, "max_kill %u", &v1) == 1) {
        if (v1 > 100) {
            ret = -EINVAL;
            goto out;
        }
        g_ai_kill.config.max_kills_per_scan = v1;
        goto out;
    }

    if (sscanf(buf, "rate_limit %u", &v1) == 1) {
        if (v1 < 100) {
            ret = -EINVAL;
            goto out;
        }
        g_ai_kill.config.rate_limit_ms = v1;
        goto out;
    }

    if (sscanf(buf, "enabled %u", &v1) == 1) {
        g_ai_kill.config.enabled = !!v1;
        goto out;
    }

    if (sscanf(buf, "whitelist %63s", arg1) == 1) {
        whitelist_init(arg1);
        goto out;
    }

    /* 未知命令 */
    ret = -EINVAL;

out:
    mutex_unlock(&g_ai_kill.config_lock);
    return ret;
}

static const struct proc_ops proc_config_fops = {
    .proc_open    = proc_config_open,
    .proc_read    = seq_read,
    .proc_write   = proc_config_write,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

/* ================================================================
 * /proc/ai-kill/stats
 * ================================================================ */

static int proc_stats_show(struct seq_file *m, void *v)
{
    struct ai_kill_stats *s = &g_ai_kill.stats;

    seq_printf(m, "%-30s = %llu\n", "scans_total", s->scans_total);
    seq_printf(m, "%-30s = %llu\n", "scans_with_candidates", s->scans_with_candidates);
    seq_printf(m, "%-30s = %llu\n", "actions_log", s->actions_log);
    seq_printf(m, "%-30s = %llu\n", "actions_warn", s->actions_warn);
    seq_printf(m, "%-30s = %llu\n", "actions_term", s->actions_term);
    seq_printf(m, "%-30s = %llu\n", "actions_kill", s->actions_kill);
    seq_printf(m, "%-30s = %llu\n", "actions_group", s->actions_group);
    seq_printf(m, "%-30s = %llu\n", "actions_failed", s->actions_failed);
    seq_printf(m, "%-30s = %llu\n", "whitelist_hits", s->whitelist_hits);
    seq_printf(m, "%-30s = %llu ns\n", "last_scan_duration", s->last_scan_duration_ns);
    seq_printf(m, "%-30s = %u\n", "current_victims", s->current_victims);
    seq_printf(m, "%-30s = %u\n", "top_score", s->top_score);
    seq_printf(m, "%-30s = %u / %u\n", "kills_this_minute / max",
               g_ai_kill.kills_this_minute,
               g_ai_kill.kills_per_minute_max);
    seq_printf(m, "%-30s = %u\n", "whitelist_count", g_ai_kill.whitelist_count);

    return 0;
}

static int proc_stats_open(struct inode *inode, struct file *file)
{
    return single_open(file, proc_stats_show, NULL);
}

static const struct proc_ops proc_stats_fops = {
    .proc_open    = proc_stats_open,
    .proc_read    = seq_read,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

/* ================================================================
 * /proc/ai-kill/history
 * ================================================================ */

static int proc_history_show(struct seq_file *m, void *v)
{
    unsigned long flags;

    spin_lock_irqsave(&g_ai_kill.history.lock, flags);

    if (g_ai_kill.history.count == 0) {
        seq_puts(m, "No kill history recorded.\n");
        spin_unlock_irqrestore(&g_ai_kill.history.lock, flags);
        return 0;
    }

    seq_printf(m, "%-20s %-8s %-20s %6s %-8s %-6s %s\n",
               "Timestamp", "PID", "COMM", "Score", "Action", "Result", "Reason");

    unsigned int start = (g_ai_kill.history.head + HISTORY_MAX -
                          g_ai_kill.history.count) % HISTORY_MAX;

    for (unsigned int i = 0; i < g_ai_kill.history.count; i++) {
        unsigned int idx = (start + i) % HISTORY_MAX;
        struct ai_kill_record *r = &g_ai_kill.history.entries[idx];
        unsigned long long ns = r->timestamp_ns;

        seq_printf(m, "%5llu.%06llu %-8d %-20s %6u %-8s %-6d %s\n",
                   ns / 1000000000ULL, (ns / 1000) % 1000000,
                   r->pid, r->comm, r->total_score,
                   action_name(r->action), r->result, r->reason);
    }

    seq_printf(m, "\n%u records total\n", g_ai_kill.history.count);

    spin_unlock_irqrestore(&g_ai_kill.history.lock, flags);
    return 0;
}

static int proc_history_open(struct inode *inode, struct file *file)
{
    return single_open(file, proc_history_show, NULL);
}

static const struct proc_ops proc_history_fops = {
    .proc_open    = proc_history_open,
    .proc_read    = seq_read,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

/* ================================================================
 * /proc/ai-kill/behavior
 * ================================================================ */

static int proc_behavior_show(struct seq_file *m, void *v)
{
    struct behavior_entry *table;
    unsigned long flags;

    rcu_read_lock();
    spin_lock_irqsave(&g_ai_kill.behavior_lock, flags);

    table = rcu_dereference(g_ai_kill.behavior_table);
    if (!table) {
        seq_puts(m, "Behavior table not initialized.\n");
        spin_unlock_irqrestore(&g_ai_kill.behavior_lock, flags);
        rcu_read_unlock();
        return 0;
    }

    seq_printf(m, "%-8s %-20s %5s %12s %12s %12s %6s\n",
               "PID", "COMM", "Samp", "RSS(B)", "RSS-1", "RSS-2", "Leak%");

    int active = 0;
    for (int i = 0; i < BEHAVIOR_TABLE_SIZE; i++) {
        struct behavior_entry *be = &table[i];
        if (be->pid == 0) continue;
        active++;

        u64 rss0 = be->samples[0].rss_bytes;
        u64 rss1 = be->samples[1].rss_bytes;
        u64 rss2 = be->samples[2].rss_bytes;
        int leak = detect_memory_leak(be);

        seq_printf(m, "%-8d %-20s %5u %12llu %12llu %12llu %6d\n",
                   be->pid, be->comm,
                   be->sample_count,
                   be->samples[be->sample_idx > 0 ?
                       (be->sample_idx - 1) % BEHAVIOR_SAMPLES : 0].rss_bytes,
                   rss0, rss1, leak);
    }

    seq_printf(m, "\n%d active entries (table: %d slots)\n",
               active, BEHAVIOR_TABLE_SIZE);

    spin_unlock_irqrestore(&g_ai_kill.behavior_lock, flags);
    rcu_read_unlock();
    return 0;
}

static int proc_behavior_open(struct inode *inode, struct file *file)
{
    return single_open(file, proc_behavior_show, NULL);
}

static const struct proc_ops proc_behavior_fops = {
    .proc_open    = proc_behavior_open,
    .proc_read    = seq_read,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

/* ================================================================
 * 初始化
 * ================================================================ */

static int __init ai_kill_init(void)
{
    int ret = 0;

    pr_info("ai-kill: Ainos AI KILL v%s initializing...\n", AI_KILL_VERSION);

    /* 初始化全局状态 */
    memset(&g_ai_kill, 0, sizeof(g_ai_kill));
    g_ai_kill.initialized = false;

    /* 初始化配置 */
    mutex_init(&g_ai_kill.config_lock);
    g_ai_kill.config.enabled = 1;
    g_ai_kill.config.scan_interval_ms = scan_interval_ms;
    g_ai_kill.config.threshold_warn = threshold_warn;
    g_ai_kill.config.threshold_term = threshold_term;
    g_ai_kill.config.threshold_kill = threshold_kill;
    g_ai_kill.config.max_kills_per_scan = max_kills_per_scan;
    g_ai_kill.config.rate_limit_ms = rate_limit_ms;
    g_ai_kill.config.protect_init = protect_init ? 1 : 0;
    g_ai_kill.config.protect_kthreads = protect_kthreads ? 1 : 0;
    memcpy((void *)g_ai_kill.config.weights, default_weights,
           sizeof(default_weights));

    /* 初始化统计 */
    memset(&g_ai_kill.stats, 0, sizeof(g_ai_kill.stats));

    /* 初始化速率限制 */
    g_ai_kill.kills_this_minute = 0;
    g_ai_kill.kills_per_minute_max = 10;  /* 每分钟最多 10 次杀戮 */
    g_ai_kill.kills_minute_start = 0;
    g_ai_kill.last_kill_jiffies = 0;

    /* 初始化杀戮历史 */
    history_init();

    /* 初始化行为跟踪表 */
    ret = behavior_init();
    if (ret < 0) {
        pr_err("ai-kill: failed to init behavior table (%d)\n", ret);
        goto err;
    }

    /* 初始化白名单 */
    whitelist_init(whitelist_str);

    /* 创建扫描工作队列 */
    g_ai_kill.scan_wq = create_singlethread_workqueue("ai-kill-scan");
    if (!g_ai_kill.scan_wq) {
        pr_err("ai-kill: failed to create workqueue\n");
        ret = -ENOMEM;
        goto err_wq;
    }
    INIT_WORK(&g_ai_kill.scan_work, scan_processes);

    /* 创建 /proc/ai-kill 目录 */
    g_ai_kill.proc_dir = proc_mkdir("ai-kill", NULL);
    if (!g_ai_kill.proc_dir) {
        pr_err("ai-kill: failed to create /proc/ai-kill\n");
        ret = -ENOMEM;
        goto err_proc;
    }

    /* 创建 proc 文件 */
    g_ai_kill.proc_scores = proc_create("scores", 0444,
                                         g_ai_kill.proc_dir,
                                         &proc_scores_fops);
    g_ai_kill.proc_config = proc_create("config", 0644,
                                         g_ai_kill.proc_dir,
                                         &proc_config_fops);
    g_ai_kill.proc_stats = proc_create("stats", 0444,
                                        g_ai_kill.proc_dir,
                                        &proc_stats_fops);
    g_ai_kill.proc_history = proc_create("history", 0444,
                                          g_ai_kill.proc_dir,
                                          &proc_history_fops);
    g_ai_kill.proc_behavior = proc_create("behavior", 0444,
                                           g_ai_kill.proc_dir,
                                           &proc_behavior_fops);

    if (!g_ai_kill.proc_scores || !g_ai_kill.proc_config ||
        !g_ai_kill.proc_stats || !g_ai_kill.proc_history ||
        !g_ai_kill.proc_behavior) {
        pr_err("ai-kill: failed to create proc files\n");
        ret = -ENOMEM;
        goto err_proc_files;
    }

    /* 启动扫描定时器 */
    timer_setup(&g_ai_kill.scan_timer, scan_timer_cb, 0);
    mod_timer(&g_ai_kill.scan_timer,
              jiffies + msecs_to_jiffies(5000));

    g_ai_kill.initialized = true;

    pr_info("ai-kill: AI KILL v%s initialized\n", AI_KILL_VERSION);
    pr_info("ai-kill: /proc/ai-kill/{scores,config,stats,history,behavior}\n");
    pr_info("ai-kill: scanning every %u ms, weights: cpu=%u mem=%u io=%u\n",
            scan_interval_ms,
            default_weights[AI_KILL_DIM_CPU],
            default_weights[AI_KILL_DIM_MEM],
            default_weights[AI_KILL_DIM_IO]);

    return 0;

err_proc_files:
    if (g_ai_kill.proc_behavior) remove_proc_entry("behavior", g_ai_kill.proc_dir);
    if (g_ai_kill.proc_history)  remove_proc_entry("history", g_ai_kill.proc_dir);
    if (g_ai_kill.proc_stats)    remove_proc_entry("stats", g_ai_kill.proc_dir);
    if (g_ai_kill.proc_config)   remove_proc_entry("config", g_ai_kill.proc_dir);
    if (g_ai_kill.proc_scores)   remove_proc_entry("scores", g_ai_kill.proc_dir);
    if (g_ai_kill.proc_dir)      remove_proc_entry("ai-kill", NULL);

err_proc:
    if (g_ai_kill.scan_wq)
        destroy_workqueue(g_ai_kill.scan_wq);

err_wq:
    behavior_destroy();

err:
    pr_err("ai-kill: initialization failed (%d)\n", ret);
    return ret;
}

/* ================================================================
 * 清理
 * ================================================================ */

static void __exit ai_kill_exit(void)
{
    if (!g_ai_kill.initialized)
        return;

    pr_info("ai-kill: shutting down...\n");

    g_ai_kill.initialized = false;

    /* 停止定时器 */
    del_timer_sync(&g_ai_kill.scan_timer);

    /* 刷新工作队列 */
    if (g_ai_kill.scan_wq) {
        flush_work(&g_ai_kill.scan_work);
        destroy_workqueue(g_ai_kill.scan_wq);
    }

    /* 清理 proc 文件 */
    if (g_ai_kill.proc_behavior) remove_proc_entry("behavior", g_ai_kill.proc_dir);
    if (g_ai_kill.proc_history)  remove_proc_entry("history", g_ai_kill.proc_dir);
    if (g_ai_kill.proc_stats)    remove_proc_entry("stats", g_ai_kill.proc_dir);
    if (g_ai_kill.proc_config)   remove_proc_entry("config", g_ai_kill.proc_dir);
    if (g_ai_kill.proc_scores)   remove_proc_entry("scores", g_ai_kill.proc_dir);
    if (g_ai_kill.proc_dir)      remove_proc_entry("ai-kill", NULL);

    /* 清理行为跟踪表 */
    behavior_destroy();

    pr_info("ai-kill: final stats: scans=%llu kills=%llu terms=%llu whitelist=%llu\n",
            g_ai_kill.stats.scans_total,
            g_ai_kill.stats.actions_kill,
            g_ai_kill.stats.actions_term,
            g_ai_kill.stats.whitelist_hits);

    pr_info("ai-kill: unloaded\n");
}

module_init(ai_kill_init);
module_exit(ai_kill_exit);