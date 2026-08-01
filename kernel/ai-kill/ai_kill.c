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
    bool stats_initialized;

    /* 杀戮历史 */
    struct kill_history history;

    /* 扫描定时器和工作队列 */
    struct timer_list scan_timer;
    struct workqueue_struct *scan_wq;
    struct work_struct scan_work;

    /* 速率限制 */
    unsigned long last_kill_jiffies;

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
 * ================================================================ */

static int whitelist_init(const char *str)
{
    char buf[256];
    char *token;
    int count = 0;

    g_ai_kill.whitelist_count = 0;

    if (!str || strlen(str) == 0)
        return 0;

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

    g_ai_kill.whitelist_count = count;
    return count;
}

static bool whitelist_check(const char *comm)
{
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
 * ================================================================ */

static int behavior_init(void)
{
    g_ai_kill.behavior_table = kzalloc(
        BEHAVIOR_TABLE_SIZE * sizeof(struct behavior_entry), GFP_KERNEL);
    if (!g_ai_kill.behavior_table)
        return -ENOMEM;

    spin_lock_init(&g_ai_kill.behavior_lock);
    return 0;
}

static void behavior_destroy(void)
{
    kfree(g_ai_kill.behavior_table);
    g_ai_kill.behavior_table = NULL;
}

/* 查找或创建行为条目 */
static struct behavior_entry *behavior_lookup(pid_t pid)
{
    unsigned int hash = (unsigned int)pid % BEHAVIOR_TABLE_SIZE;
    struct behavior_entry *entry = &g_ai_kill.behavior_table[hash];

    /* 如果条目已被占用且不是同一个 PID，尝试线性探测 */
    unsigned int start = hash;
    while (entry->pid != 0 && entry->pid != pid) {
        hash = (hash + 1) % BEHAVIOR_TABLE_SIZE;
        if (hash == start)
            return NULL; /* 表满了 */
        entry = &g_ai_kill.behavior_table[hash];
    }

    return entry;
}

/* 记录进程行为样本 */
static void behavior_record(struct task_struct *task)
{
    struct behavior_entry *entry;
    struct mm_struct *mm;
    unsigned long flags;

    if (!g_ai_kill.behavior_table)
        return;

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

    spin_unlock_irqrestore(&g_ai_kill.behavior_lock, flags);
}

/* 清除退出进程的行为记录 */
static void behavior_cleanup(pid_t pid)
{
    struct behavior_entry *entry;
    unsigned long flags;

    if (!g_ai_kill.behavior_table)
        return;

    spin_lock_irqsave(&g_ai_kill.behavior_lock, flags);
    entry = behavior_lookup(pid);
    if (entry && entry->pid == pid) {
        memset(entry, 0, sizeof(*entry));
    }
    spin_unlock_irqrestore(&g_ai_kill.behavior_lock, flags);
}

/* 检测内存泄漏趋势 */
static int detect_memory_leak(const struct behavior_entry *entry)
{
    if (entry->sample_count < 3)
        return 0;

    /* 检查最近 3 个样本的 RSS 趋势 */
    unsigned int s0 = (entry->sample_idx - 3) % BEHAVIOR_SAMPLES;
    unsigned int s1 = (entry->sample_idx - 2) % BEHAVIOR_SAMPLES;
    unsigned int s2 = (entry->sample_idx - 1) % BEHAVIOR_SAMPLES;

    u64 rss0 = entry->samples[s0].rss_bytes;
    u64 rss1 = entry->samples[s1].rss_bytes;
    u64 rss2 = entry->samples[s2].rss_bytes;

    /* 如果 RSS 持续增长 */
    if (rss0 < rss1 && rss1 < rss2 && rss0 > 0) {
        u64 growth = rss2 - rss0;
        unsigned int pct = (unsigned int)(growth * 100 / rss0);
        /* 增长率 > 20% 提示泄漏 */
        return min(pct, 100);
    }

    return 0;
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
    unsigned int sockets = 0;
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
        "systemd", "init", "bash", "sh", "sshd", "sshd",
        "cron", "rsyslogd", "dbus-daemon", "NetworkManager",
        "login", "getty", "agettty", "auditd", "polkitd",
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

/* 计算综合评分 */
static unsigned int calc_total_score(const struct ai_kill_score *score)
{
    unsigned int total_weight = 0;
    unsigned int weighted_sum = 0;

    for (int i = 0; i < AI_KILL_DIM_COUNT; i++) {
        weighted_sum += score->dims[i] * g_ai_kill.config.weights[i];
        total_weight += g_ai_kill.config.weights[i];
    }

    if (total_weight == 0)
        return 0;

    /* 关键性评分是负权重，所以分数可能低于 0 */
    int total = (int)(weighted_sum / total_weight);
    if (total < 0)
        return 0;
    if (total > 100)
        return 100;

    return (unsigned int)total;
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

/* 检查速率限制 */
static bool rate_limit_check(void)
{
    unsigned long now = jiffies;
    unsigned long interval = msecs_to_jiffies(rate_limit_ms);

    if (time_before(now, g_ai_kill.last_kill_jiffies + interval))
        return false;

    g_ai_kill.last_kill_jiffies = now;
    return true;
}

/* 安全地杀进程 */
static int ai_kill_do_kill(pid_t pid, enum ai_kill_action action)
{
    struct task_struct *task;
    int ret;

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

    /* 白名单检查 */
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
        /* 杀死整个进程组 */
        pr_info("ai-kill: killing group of %s (pid=%d)\n", task->comm, pid);
        kill_pid(task->tgid, SIGKILL, 1);
        g_ai_kill.stats.actions_group++;
        ret = 0;
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

        /* 保护 init */
        if (protect_init && task_tgid_nr(task) <= 1)
            continue;

        s = &scores[score_count];
        memset(s, 0, sizeof(*s));

        s->pid = task_tgid_nr(task);
        strscpy(s->comm, task->comm, COMM_LEN);
        s->oom_score_adj = task->signal->oom_score_adj;

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

    /* 按评分排序 (简单选择排序，取前 N 个) */
    if (score_count > 0 && g_ai_kill.config.enabled) {
        int n = min(score_count, (int)max_kills_per_scan);

        for (int i = 0; i < n; i++) {
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

                /* 速率限制 */
                if (!rate_limit_check() && s->action >= AI_KILL_ACTION_KILL) {
                    pr_debug("ai-kill: rate limited, skipping %s (pid=%d)\n",
                             s->comm, s->pid);
                    continue;
                }

                /* 白名单检查 (再次确认) */
                if (whitelist_check(s->comm)) {
                    g_ai_kill.stats.whitelist_hits++;
                    continue;
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

    if (count >= sizeof(buf))
        return -EINVAL;

    if (copy_from_user(buf, ubuf, count))
        return -EFAULT;
    buf[count] = '\0';
    if (count > 0 && buf[count - 1] == '\n')
        buf[count - 1] = '\0';

    if (strcmp(buf, "reset") == 0) {
        mutex_lock(&g_ai_kill.config_lock);
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
        mutex_unlock(&g_ai_kill.config_lock);
        pr_info("ai-kill: config reset to defaults\n");
        return count;
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
        return count;
    }

    if (sscanf(buf, "threshold %u %u %u", &v1, &v2, &v3) == 3) {
        g_ai_kill.config.threshold_warn = v1;
        g_ai_kill.config.threshold_term = v2;
        g_ai_kill.config.threshold_kill = v3;
        return count;
    }

    if (sscanf(buf, "interval %u", &v1) == 1) {
        g_ai_kill.config.scan_interval_ms = v1;
        mod_timer(&g_ai_kill.scan_timer,
                  jiffies + msecs_to_jiffies(v1));
        return count;
    }

    if (sscanf(buf, "max_kill %u", &v1) == 1) {
        g_ai_kill.config.max_kills_per_scan = v1;
        return count;
    }

    if (sscanf(buf, "rate_limit %u", &v1) == 1) {
        g_ai_kill.config.rate_limit_ms = v1;
        return count;
    }

    if (sscanf(buf, "enabled %u", &v1) == 1) {
        g_ai_kill.config.enabled = v1;
        return count;
    }

    if (sscanf(buf, "whitelist %63s", arg1) == 1) {
        whitelist_init(arg1);
        return count;
    }

    return -EINVAL;
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
    unsigned long flags;

    spin_lock_irqsave(&g_ai_kill.behavior_lock, flags);

    if (!g_ai_kill.behavior_table) {
        seq_puts(m, "Behavior table not initialized.\n");
        spin_unlock_irqrestore(&g_ai_kill.behavior_lock, flags);
        return 0;
    }

    seq_printf(m, "%-8s %-20s %5s %12s %12s %12s %6s\n",
               "PID", "COMM", "Samp", "RSS(B)", "RSS-1", "RSS-2", "Leak%");

    int active = 0;
    for (int i = 0; i < BEHAVIOR_TABLE_SIZE; i++) {
        struct behavior_entry *be = &g_ai_kill.behavior_table[i];
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
    g_ai_kill.stats_initialized = true;

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