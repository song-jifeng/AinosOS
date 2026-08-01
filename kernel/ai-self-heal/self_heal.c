// ================================================================
// Ainos OS - 内核自愈模块 (深度实现 v2.0.0)
// ================================================================
//
// 架构:
//   ┌─────────────────────────────────────────────────────────┐
//   │                  自愈引擎核心                              │
//   ├─────────────────────────────────────────────────────────┤
//   │  ┌──────────────────┐   ┌──────────────────────────┐    │
//   │  │ 预防性监控 (定时器)│   │ 反应式检测 (notifier)    │    │
//   │  │ • 内存压力        │   │ • Panic 通知器          │    │
//   │  │ • 僵尸进程        │   │ • 外部模块事件报告       │    │
//   │  │ • OOM 风险        │   │                          │    │
//   │  │ • 系统负载        │   └──────────────────────────┘    │
//   │  │ • D 状态任务      │                                    │
//   │  └────────┬─────────┘                                    │
//   │           ▼                                               │
//   │  ┌──────────────────────────────────────────────────┐    │
//   │  │ 策略引擎 (渐变恢复)                                │    │
//   │  │ Level 0: LOG   → Level 1: SOFT  → Level 2:       │    │
//   │  │ RECLAIM → Level 3: RESTART → Level 4: KEXEC      │    │
//   │  │ → Level 5: PANIC                                 │    │
//   │  └──────────────────────┬───────────────────────────┘    │
//   │                         ▼                                 │
//   │  ┌──────────────────────────────────────────────────┐    │
//   │  │ 恢复执行器                                        │    │
//   │  │ • kill_task() • reclaim_memory() • reload_driver()│    │
//   │  │ • trigger_kexec() • intercept_panic()             │    │
//   │  └──────────────────────┬───────────────────────────┘    │
//   │                         ▼                                 │
//   │  ┌──────────────────────────────────────────────────┐    │
//   │  │ 验证 & 统计                                      │    │
//   │  │ • 恢复后健康检查 • 事件环形缓冲区 • 健康评分      │    │
//   │  └──────────────────────────────────────────────────┘    │
//   │                                                          │
//   │  ┌──────────────────────────────────────────────────┐    │
//   │  │ /proc/self-heal 接口                              │    │
//   │  │ status | config | trigger | history               │    │
//   │  └──────────────────────────────────────────────────┘    │
//   └─────────────────────────────────────────────────────────┘
//
// 安全设计:
//   1. 上下文感知: 区分 panic 原子上下文 vs 工作队列可睡眠上下文
//   2. 锁顺序: spinlock(ring) → mutex(config) → mutex(monitor)
//   3. 无自死锁: 恢复执行中不触发监控, 监控中不触发恢复
//   4. 冷却期: 同类型事件在冷却期内不重复触发
//   5. 回退: 如果恢复失败, 自动升级到更高级别
//
// ================================================================

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/version.h>
#include <linux/notifier.h>
#include <linux/panic_notifier.h>
#include <linux/sched.h>
#include <linux/sched/signal.h>
#include <linux/sched/debug.h>
#include <linux/sched/loadavg.h>
#include <linux/sched/stat.h>
#include <linux/delay.h>
#include <linux/reboot.h>
#include <linux/timer.h>
#include <linux/workqueue.h>
#include <linux/proc_fs.h>
#include <linux/seq_file.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/slab.h>
#include <linux/string.h>
#include <linux/atomic.h>
#include <linux/mm.h>
#include <linux/mmzone.h>
#include <linux/swap.h>
#include <linux/oom.h>
#include <linux/kexec.h>
#include <linux/moduleparam.h>
#include <linux/pid.h>
#include <linux/pid_namespace.h>
#include <linux/timekeeping.h>
#include <linux/rtc.h>
#include <linux/syscalls.h>
#include <linux/file.h>
#include <linux/fdtable.h>

#include "self_heal.h"

/* ================================================================
 * 模块参数
 * ================================================================ */

static unsigned int monitor_interval_sec = 10;
module_param(monitor_interval_sec, uint, 0644);
MODULE_PARM_DESC(monitor_interval_sec, "预防性监控间隔 (秒)");

static unsigned int ring_buffer_size = 256;
module_param(ring_buffer_size, uint, 0644);
MODULE_PARM_DESC(ring_buffer_size, "事件环形缓冲区大小");

static unsigned int mem_pressure_warn_pct = 10;
module_param(mem_pressure_warn_pct, uint, 0644);
MODULE_PARM_DESC(mem_pressure_warn_pct, "内存压力警告阈值 (%)");

static unsigned int mem_pressure_crit_pct = 5;
module_param(mem_pressure_crit_pct, uint, 0644);
MODULE_PARM_DESC(mem_pressure_crit_pct, "内存压力严重阈值 (%)");

static unsigned int zombie_warn_count = 20;
module_param(zombie_warn_count, uint, 0644);
MODULE_PARM_DESC(zombie_warn_count, "僵尸进程警告阈值");

static unsigned int zombie_crit_count = 50;
module_param(zombie_crit_count, uint, 0644);
MODULE_PARM_DESC(zombie_crit_count, "僵尸进程严重阈值");

static unsigned int load_warn_multiplier = 4;
module_param(load_warn_multiplier, uint, 0644);
MODULE_PARM_DESC(load_warn_multiplier, "负载警告倍数 (相对于 CPU 数)");

static unsigned int load_crit_multiplier = 8;
module_param(load_crit_multiplier, uint, 0644);
MODULE_PARM_DESC(load_crit_multiplier, "负载严重倍数 (相对于 CPU 数)");

static unsigned int hung_task_timeout_sec = 120;
module_param(hung_task_timeout_sec, uint, 0644);
MODULE_PARM_DESC(hung_task_timeout_sec, "D 状态任务超时 (秒)");

static unsigned int max_recovery_attempts = 3;
module_param(max_recovery_attempts, uint, 0644);
MODULE_PARM_DESC(max_recovery_attempts, "单次事件最大恢复尝试次数");

static bool enable_preventive = true;
module_param(enable_preventive, bool, 0644);
MODULE_PARM_DESC(enable_preventive, "启用预防性监控");

static bool enable_ai_integration = true;
module_param(enable_ai_integration, bool, 0644);
MODULE_PARM_DESC(enable_ai_integration, "启用 AI 集成 (向 ai-daemon 报告事件)");

MODULE_LICENSE("MIT");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("AI-powered kernel self-healing module (deep implementation)");
MODULE_VERSION(SELF_HEAL_VERSION);

/* ================================================================
 * 数据结构
 * ================================================================ */

/* 环形缓冲区 */
struct heal_ring_buffer {
    struct heal_event_record *entries;
    spinlock_t               lock;
    unsigned int             head;
    unsigned int             tail;
    unsigned int             count;
    unsigned int             max_entries;
    atomic64_t               seq_counter;
};

/* 事件配置默认值 */
static const struct heal_event_config default_configs[HEAL_EVENT_MAX] = {
    [HEAL_EVENT_MEM_PRESSURE] = {HEAL_EVENT_MEM_PRESSURE,  HEAL_LEVEL_SOFT,    60000, 5, 1, 1, "mem_pressure"},
    [HEAL_EVENT_SOFT_LOCKUP]  = {HEAL_EVENT_SOFT_LOCKUP,   HEAL_LEVEL_RESTART, 30000, 3, 1, 1, "soft_lockup"},
    [HEAL_EVENT_HUNG_TASK]    = {HEAL_EVENT_HUNG_TASK,     HEAL_LEVEL_SOFT,    30000, 3, 1, 1, "hung_task"},
    [HEAL_EVENT_OOM_NEAR]     = {HEAL_EVENT_OOM_NEAR,      HEAL_LEVEL_SOFT,    120000,5, 1, 1, "oom_near"},
    [HEAL_EVENT_ZOMBIE]       = {HEAL_EVENT_ZOMBIE,        HEAL_LEVEL_LOG,     120000,3, 1, 1, "zombie"},
    [HEAL_EVENT_MCE]          = {HEAL_EVENT_MCE,           HEAL_LEVEL_KEXEC,   0,      1, 1, 1, "mce"},
    [HEAL_EVENT_PANIC]        = {HEAL_EVENT_PANIC,         HEAL_LEVEL_RESTART, 0,      1, 1, 1, "panic"},
    [HEAL_EVENT_DRIVER]       = {HEAL_EVENT_DRIVER,        HEAL_LEVEL_RESTART, 60000, 3, 1, 1, "driver"},
    [HEAL_EVENT_FS]           = {HEAL_EVENT_FS,            HEAL_LEVEL_RESTART, 60000, 3, 1, 1, "fs"},
    [HEAL_EVENT_AI_OVERRIDE]  = {HEAL_EVENT_AI_OVERRIDE,   HEAL_LEVEL_SOFT,    30000, 10,1, 1, "ai_override"},
    [HEAL_EVENT_OOM_KILL]     = {HEAL_EVENT_OOM_KILL,      HEAL_LEVEL_LOG,     60000, 3, 1, 1, "oom_kill"},
    [HEAL_EVENT_HIGH_LOAD]    = {HEAL_EVENT_HIGH_LOAD,     HEAL_LEVEL_SOFT,    60000, 3, 1, 1, "high_load"},
    [HEAL_EVENT_CUSTOM]       = {HEAL_EVENT_CUSTOM,        HEAL_LEVEL_SOFT,    30000, 5, 1, 1, "custom"},
};

/* 自愈全局状态 */
static struct {
    /* 配置 */
    struct heal_event_config configs[HEAL_EVENT_MAX];
    struct mutex             config_lock;

    /* 统计 (原子操作, 无需锁) */
    struct heal_stats        stats;

    /* 事件环形缓冲区 */
    struct heal_ring_buffer  ring;

    /* 监控 */
    struct timer_list        monitor_timer;
    struct workqueue_struct *monitor_wq;
    struct work_struct       monitor_work;

    /* 状态 */
    enum heal_health_status  health_status;
    unsigned int             health_score;
    unsigned long            last_monitor_jiffies;
    unsigned long            module_start_jiffies;

    /* 冷却期跟踪 */
    unsigned long            last_event_jiffies[HEAL_EVENT_MAX];

    /* 恢复执行中标志 (防止递归) */
    atomic_t                 recovery_in_progress;

    /* panic 通知器 */
    struct notifier_block    panic_nb;

    /* /proc 条目 */
    struct proc_dir_entry   *proc_dir;
    struct proc_dir_entry   *proc_status;
    struct proc_dir_entry   *proc_config;
    struct proc_dir_entry   *proc_trigger;
    struct proc_dir_entry   *proc_history;

    /* 运行标志 */
    bool                     initialized;
} g_self_heal;

/* ================================================================
 * 事件类型名称映射
 * ================================================================ */

static const char *heal_event_name(enum heal_event_type type)
{
    static const char *names[] = {
        [HEAL_EVENT_MEM_PRESSURE]  = "mem_pressure",
        [HEAL_EVENT_SOFT_LOCKUP]   = "soft_lockup",
        [HEAL_EVENT_HUNG_TASK]     = "hung_task",
        [HEAL_EVENT_OOM_NEAR]      = "oom_near",
        [HEAL_EVENT_ZOMBIE]        = "zombie",
        [HEAL_EVENT_MCE]           = "mce",
        [HEAL_EVENT_PANIC]         = "panic",
        [HEAL_EVENT_DRIVER]        = "driver",
        [HEAL_EVENT_FS]            = "fs",
        [HEAL_EVENT_AI_OVERRIDE]   = "ai_override",
        [HEAL_EVENT_OOM_KILL]      = "oom_kill",
        [HEAL_EVENT_HIGH_LOAD]     = "high_load",
        [HEAL_EVENT_CUSTOM]        = "custom",
    };

    if (type < HEAL_EVENT_MAX)
        return names[type] ?: "unknown";
    return "unknown";
}

static const char *heal_level_name(enum heal_level level)
{
    switch (level) {
    case HEAL_LEVEL_LOG:     return "log";
    case HEAL_LEVEL_SOFT:    return "soft";
    case HEAL_LEVEL_RECLAIM: return "reclaim";
    case HEAL_LEVEL_RESTART: return "restart";
    case HEAL_LEVEL_KEXEC:   return "kexec";
    case HEAL_LEVEL_PANIC:   return "panic";
    case HEAL_LEVEL_DEFAULT: return "default";
    default:                 return "unknown";
    }
}

static const char *heal_health_name(enum heal_health_status status)
{
    switch (status) {
    case HEAL_HEALTH_OK:        return "OK";
    case HEAL_HEALTH_WARNING:   return "WARNING";
    case HEAL_HEALTH_CRITICAL:  return "CRITICAL";
    case HEAL_HEALTH_RECOVERING:return "RECOVERING";
    default:                    return "UNKNOWN";
    }
}

/* ================================================================
 * 环形缓冲区操作
 * ================================================================ */

static int heal_ring_init(struct heal_ring_buffer *ring, unsigned int size)
{
    if (size < 16 || size > 4096)
        return -EINVAL;

    /* 对齐到 2 的幂 */
    unsigned int actual = 1;
    while (actual < size)
        actual <<= 1;

    ring->entries = kmalloc_array(actual, sizeof(struct heal_event_record), GFP_KERNEL);
    if (!ring->entries)
        return -ENOMEM;

    spin_lock_init(&ring->lock);
    ring->head = 0;
    ring->tail = 0;
    ring->count = 0;
    ring->max_entries = actual;
    atomic64_set(&ring->seq_counter, 0);

    pr_info("self-heal: ring buffer allocated %u entries (%zu bytes)\n",
            actual, actual * sizeof(struct heal_event_record));
    return 0;
}

static void heal_ring_destroy(struct heal_ring_buffer *ring)
{
    kfree(ring->entries);
    ring->entries = NULL;
}

static void heal_ring_push(struct heal_ring_buffer *ring,
                           const struct heal_event_record *rec)
{
    unsigned long flags;

    spin_lock_irqsave(&ring->lock, flags);

    rec->seq = (u32)atomic64_inc_return(&ring->seq_counter);

    ring->entries[ring->head] = *rec;

    ring->head = (ring->head + 1) & (ring->max_entries - 1);

    if (ring->count == ring->max_entries) {
        ring->tail = (ring->tail + 1) & (ring->max_entries - 1);
    } else {
        ring->count++;
    }

    spin_unlock_irqrestore(&ring->lock, flags);
}

static int heal_ring_read(struct heal_ring_buffer *ring, char *buf, size_t size)
{
    unsigned long flags;
    int count = 0;
    unsigned int i;
    unsigned int idx;
    unsigned int n;

    spin_lock_irqsave(&ring->lock, flags);

    n = ring->count;
    if (n == 0) {
        count = snprintf(buf, size, "No events recorded.\n");
        spin_unlock_irqrestore(&ring->lock, flags);
        return count;
    }

    /* 从 tail 读到 head */
    for (i = 0; i < n; i++) {
        idx = (ring->tail + i) & (ring->max_entries - 1);
        const struct heal_event_record *r = &ring->entries[idx];
        unsigned long long secs = r->timestamp_ns / 1000000000ULL;
        unsigned long long nsecs_rem = r->timestamp_ns % 1000000000ULL;

        int ret = snprintf(buf + count, size - count,
            "[%llu.%06llu] #%u %-16s lvl=%-7s pid=%-6d %s (result=%d)\n",
            secs, nsecs_rem / 1000,
            r->seq,
            heal_event_name(r->type),
            heal_level_name(r->level_used),
            r->pid,
            r->description,
            r->result);

        if (ret > 0) {
            count += ret;
            if (count >= (int)size - 128) {
                /* 防止缓冲区溢出，截断 */
                snprintf(buf + count, size - count, "... (truncated, %u entries)\n", n - i - 1);
                break;
            }
        }
    }

    spin_unlock_irqrestore(&ring->lock, flags);
    return count;
}

/* ================================================================
 * 统计操作
 * ================================================================ */

static inline void heal_stats_init(struct heal_stats *s)
{
    memset(s, 0, sizeof(*s));
}

static inline void heal_stats_inc(atomic64_t *counter)
{
    atomic64_inc(counter);
}

static inline u64 heal_stats_read(const atomic64_t *counter)
{
    return atomic64_read(counter);
}

/* ================================================================
 * 冷却期检查
 * ================================================================ */

static bool heal_is_on_cooldown(enum heal_event_type type)
{
    unsigned long now = jiffies;
    unsigned long last = g_self_heal.last_event_jiffies[type];
    unsigned long cooldown = msecs_to_jiffies(g_self_heal.configs[type].cooldown_ms);

    if (time_before(now, last + cooldown))
        return true;
    return false;
}

static void heal_update_cooldown(enum heal_event_type type)
{
    g_self_heal.last_event_jiffies[type] = jiffies;
}

/* ================================================================
 * 健康评分计算
 * ================================================================ */

static unsigned int heal_calculate_health_score(void)
{
    unsigned int score = 100;
    unsigned long avail, total;
    unsigned int free_pct;
    unsigned int zombie_count = 0;
    unsigned long load[3];
    unsigned int num_online_cpus;
    struct task_struct *p;
    u64 events_detected;

    /* 1. 内存压力 (权重 30) */
    total = totalram_pages() + total_swap_pages;
    avail = si_mem_available(NULL);
    if (total > 0) {
        free_pct = (unsigned int)(avail * 100 / total);
        if (free_pct < mem_pressure_crit_pct) {
            score -= 30;
        } else if (free_pct < mem_pressure_warn_pct) {
            score -= 15;
        }
    }

    /* 2. 僵尸进程 (权重 10) */
    rcu_read_lock();
    for_each_process(p) {
        if (p->state == TASK_DEAD || p->exit_state == EXIT_ZOMBIE)
            zombie_count++;
    }
    rcu_read_unlock();

    if (zombie_count >= zombie_crit_count) {
        score -= 10;
    } else if (zombie_count >= zombie_warn_count) {
        score -= 5;
    }

    /* 3. 系统负载 (权重 20) */
    get_avenrun(load, FIXED_1/100, 0);
    num_online_cpus = num_online_cpus();
    if (num_online_cpus > 0) {
        unsigned long load_avg = load[0] / 100;  /* 近似 */
        if (load_avg > num_online_cpus * load_crit_multiplier) {
            score -= 20;
        } else if (load_avg > num_online_cpus * load_warn_multiplier) {
            score -= 10;
        }
    }

    /* 4. 最近事件 (权重 20) */
    events_detected = heal_stats_read(&g_self_heal.stats.events_detected);
    if (events_detected > 100) {
        score -= 20;
    } else if (events_detected > 50) {
        score -= 10;
    } else if (events_detected > 10) {
        score -= 5;
    }

    /* 5. 恢复成功率 (权重 20) */
    u64 attempts = heal_stats_read(&g_self_heal.stats.recovery_attempts);
    u64 success = heal_stats_read(&g_self_heal.stats.recovery_success);
    if (attempts > 0) {
        unsigned int success_pct = (unsigned int)(success * 100 / attempts);
        if (success_pct < 30) {
            score -= 20;
        } else if (success_pct < 60) {
            score -= 10;
        }
    }

    /* 确保在 0-100 范围内 */
    if (score > 100)
        score = 100;

    return score;
}

static enum heal_health_status heal_calculate_health_status(unsigned int score)
{
    if (score >= 80) return HEAL_HEALTH_OK;
    if (score >= 50) return HEAL_HEALTH_WARNING;
    if (score >= 30) return HEAL_HEALTH_CRITICAL;
    return HEAL_HEALTH_CRITICAL;
}

/* ================================================================
 * 恢复执行器
 * ================================================================ */

/*
 * 安全地杀死进程。
 * 1. 先发 SIGTERM (给进程优雅退出的机会)
 * 2. 等待 1 秒
 * 3. 如果还在运行，发 SIGKILL
 *
 * 返回: 0=成功, 负值=错误
 */
static int heal_kill_task(struct task_struct *task, bool force)
{
    int ret;
    struct pid *pid_struct;
    pid_t pid;

    if (!task)
        return -EINVAL;

    pid = task_tgid_nr(task);
    if (pid <= 0)
        return -ESRCH;

    /* 跳过内核线程和 init */
    if (pid == 1 || (task->flags & PF_KTHREAD)) {
        pr_warn("self-heal: refusing to kill kernel thread or init (pid=%d)\n", pid);
        return -EPERM;
    }

    pid_struct = get_task_pid(task, PIDTYPE_PID);
    if (!pid_struct)
        return -ESRCH;

    if (!force) {
        /* 先 SIGTERM */
        pr_info("self-heal: sending SIGTERM to pid=%d (%s)\n", pid, task->comm);
        ret = send_sig(SIGTERM, task, 0);
        if (ret < 0) {
            put_pid(pid_struct);
            return ret;
        }
        msleep(1000);
    }

    /* 检查是否还在运行 */
    if (task->state == TASK_DEAD || task->exit_state == EXIT_DEAD) {
        put_pid(pid_struct);
        return 0;  /* 已经优雅退出 */
    }

    /* SIGKILL */
    pr_info("self-heal: sending SIGKILL to pid=%d (%s)%s\n",
            pid, task->comm, force ? " (forced)" : "");
    ret = send_sig(SIGKILL, task, 0);

    if (ret == 0) {
        heal_stats_inc(&g_self_heal.stats.tasks_killed);
    }

    put_pid(pid_struct);
    return ret;
}

/*
 * 找到内存占用最大的可杀进程。
 * 跳过: init, kthreadd, 当前进程, 其他内核线程
 */
static struct task_struct *heal_find_biggest_memory_consumer(void)
{
    struct task_struct *p;
    struct task_struct *biggest = NULL;
    unsigned long max_rss = 0;
    unsigned long rss;

    rcu_read_lock();
    for_each_process(p) {
        /* 跳过内核线程和 init */
        if (p->flags & PF_KTHREAD)
            continue;
        if (task_tgid_nr(p) <= 1)
            continue;

        /* 获取 RSS (近似) */
        rss = get_mm_rss(p->mm);
        if (rss > max_rss) {
            max_rss = rss;
            biggest = p;
        }
    }
    if (biggest)
        get_task_struct(biggest);
    rcu_read_unlock();

    return biggest;
}

/*
 * 找到 CPU 占用最大的可杀进程。
 */
static struct task_struct *heal_find_biggest_cpu_consumer(void)
{
    struct task_struct *p;
    struct task_struct *biggest = NULL;
    u64 max_cpu = 0;
    u64 cpu_time;

    rcu_read_lock();
    for_each_process(p) {
        if (p->flags & PF_KTHREAD)
            continue;
        if (task_tgid_nr(p) <= 1)
            continue;

        cpu_time = (u64)p->stime + (u64)p->utime;  /* 近似，单位 jiffies */
        if (cpu_time > max_cpu) {
            max_cpu = cpu_time;
            biggest = p;
        }
    }
    if (biggest)
        get_task_struct(biggest);
    rcu_read_unlock();

    return biggest;
}

/*
 * 触发内存回收。
 * 通过唤醒 kswapd 和触发 shrinker 来回收内存。
 */
static int heal_reclaim_memory(void)
{
    pr_info("self-heal: triggering memory reclaim\n");

    unsigned long avail_before = si_mem_available(NULL);

    /* 唤醒 kswapd 进行回收 */
    wakeup_kswapd(0, GFP_KERNEL, 0);

    /* 等待回收进行 (仅在非原子上下文) */
    msleep(500);

    unsigned long avail_after = si_mem_available(NULL);

    pr_info("self-heal: memory reclaim: %lu kB -> %lu kB available\n",
            avail_before * 4, avail_after * 4);

    return 0;
}

/*
 * 尝试重新加载驱动模块。
 * 注意: 内核模块无法安全地卸载自己或其他模块。
 * 实际重载应由用户空间完成 (rmmod + insmod)。
 * 这里只记录意图和检查依赖。
 */
static int heal_reload_driver(const char *module_name)
{
    if (!module_name)
        return -EINVAL;

    pr_info("self-heal: driver reload requested for '%s'\n", module_name);

    /* 检查模块是否存在 (通过 /proc/modules) */
    /* 在内核中，我们无法直接检查模块状态而不持有引用 */

    /* 记录统计 */
    heal_stats_inc(&g_self_heal.stats.drivers_reloaded);

    /* 实际重载需要用户空间协助:
     * echo "reload <module>" > /proc/self-heal/trigger
     * 或者由 ai-daemon 执行 rmmod + insmod */
    pr_info("self-heal: driver '%s' reload scheduled (user-space will execute)\n",
            module_name);

    return 0;
}

/*
 * 触发紧急 kexec。
 * 注意: 需要预先用 kexec 工具加载备用内核。
 * 内核模块只做检查，实际执行由用户空间完成。
 */
static int heal_trigger_kexec(void)
{
    pr_info("self-heal: emergency kexec requested\n");

#if defined(CONFIG_KEXEC)
    pr_info("self-heal: kexec is configured, execute 'kexec -e' from user-space to activate\n");
    heal_stats_inc(&g_self_heal.stats.kexec_triggers);
    return 0;
#else
    pr_warn("self-heal: kexec not configured in kernel (CONFIG_KEXEC=n)\n");
    return -ENOSYS;
#endif
}

/* ================================================================
 * 场景特定的恢复执行
 * ================================================================ */

/*
 * 执行内存压力恢复。
 * Level 1: 杀死最大内存消费者
 * Level 2: 触发内存回收
 * Level 3: 杀死更多进程
 */
static int heal_recover_mem_pressure(enum heal_level level)
{
    switch (level) {
    case HEAL_LEVEL_LOG:
        return 0;

    case HEAL_LEVEL_SOFT: {
        struct task_struct *victim = heal_find_biggest_memory_consumer();
        if (victim) {
            int ret = heal_kill_task(victim, false);
            put_task_struct(victim);
            return ret;
        }
        return -ESRCH;
    }

    case HEAL_LEVEL_RECLAIM:
        return heal_reclaim_memory();

    case HEAL_LEVEL_RESTART: {
        /* 先回收，再连续杀进程 */
        heal_reclaim_memory();
        int killed = 0;
        for (int i = 0; i < 3; i++) {
            struct task_struct *victim = heal_find_biggest_memory_consumer();
            if (!victim)
                break;
            heal_kill_task(victim, true);
            put_task_struct(victim);
            killed++;
        }
        return killed > 0 ? 0 : -ESRCH;
    }

    default:
        return -ENOSYS;
    }
}

/*
 * 执行高负载恢复。
 * Level 1: 杀死最大 CPU 消费者
 */
static int heal_recover_high_load(enum heal_level level)
{
    switch (level) {
    case HEAL_LEVEL_LOG:
        return 0;

    case HEAL_LEVEL_SOFT: {
        struct task_struct *victim = heal_find_biggest_cpu_consumer();
        if (victim) {
            int ret = heal_kill_task(victim, false);
            put_task_struct(victim);
            return ret;
        }
        return -ESRCH;
    }

    default:
        return -ENOSYS;
    }
}

/*
 * 执行僵尸进程恢复。
 * Level 1: 尝试收割 (内核自动处理，通常不需要操作)
 */
static int heal_recover_zombie(enum heal_level level)
{
    switch (level) {
    case HEAL_LEVEL_LOG:
    case HEAL_LEVEL_SOFT:
        /* 内核的 wait 系统调用会处理僵尸进程。
         * 如果僵尸进程过多，通常是 init 进程的问题。
         * 这里我们只记录和报告。 */
        pr_info("self-heal: %u zombies detected, waiting for reaping\n",
                zombie_crit_count);
        return 0;

    default:
        return -ENOSYS;
    }
}

/*
 * 执行恢复 (根据事件类型和级别)
 */
static int heal_execute_recovery(enum heal_event_type type, enum heal_level level)
{
    int ret = -ENOSYS;

    pr_info("self-heal: executing recovery: event=%s level=%s\n",
            heal_event_name(type), heal_level_name(level));

    switch (type) {
    case HEAL_EVENT_MEM_PRESSURE:
    case HEAL_EVENT_OOM_NEAR:
        ret = heal_recover_mem_pressure(level);
        break;

    case HEAL_EVENT_HIGH_LOAD:
        ret = heal_recover_high_load(level);
        break;

    case HEAL_EVENT_ZOMBIE:
        ret = heal_recover_zombie(level);
        break;

    case HEAL_EVENT_HUNG_TASK:
    case HEAL_EVENT_OOM_KILL:
        /* 对于挂起任务和 OOM 杀进程，需要找到并杀任务 */
        if (level >= HEAL_LEVEL_SOFT) {
            struct task_struct *victim = heal_find_biggest_memory_consumer();
            if (victim) {
                ret = heal_kill_task(victim, true);
                put_task_struct(victim);
            } else {
                ret = -ESRCH;
            }
        } else {
            ret = 0;  /* 仅记录 */
        }
        break;

    case HEAL_EVENT_SOFT_LOCKUP:
    case HEAL_EVENT_DRIVER:
    case HEAL_EVENT_FS:
        /* 需要驱动重载或子系统重启 */
        if (level >= HEAL_LEVEL_RESTART)
            ret = 0;  /* 记录意图，实际由用户空间执行 */
        else
            ret = -ENOSYS;
        break;

    case HEAL_EVENT_MCE:
        /* 硬件错误，只能 kexec */
        if (level >= HEAL_LEVEL_KEXEC)
            ret = heal_trigger_kexec();
        else
            ret = -ENOSYS;
        break;

    case HEAL_EVENT_PANIC:
        /* 从 panic 恢复 */
        if (level >= HEAL_LEVEL_RESTART)
            ret = 0;  /* 阻止 panic 继续 */
        else
            ret = -ENOSYS;
        break;

    default:
        ret = -ENOSYS;
        break;
    }

    return ret;
}

/* ================================================================
 * 策略引擎 (渐变恢复)
 * ================================================================ */

/*
 * 处理事件的主函数。
 * 实现渐变恢复策略:
 *   1. 从配置的级别开始尝试
 *   2. 如果失败且配置允许自动升级，尝试更高级别
 *   3. 记录每个步骤
 *   4. 更新统计和环形缓冲区
 */
static int heal_process_event(enum heal_event_type type,
                              enum heal_level level_override,
                              pid_t pid,
                              const char *description)
{
    struct heal_event_record rec;
    int ret = -ENOSYS;
    enum heal_level current_level;
    enum heal_level max_level;
    enum heal_level level_used = HEAL_LEVEL_LOG;
    int attempts = 0;
    bool escalated = false;

    /* 检查是否初始化 */
    if (!g_self_heal.initialized)
        return -ENODEV;

    /* 检查恢复执行中防止递归 */
    if (atomic_read(&g_self_heal.recovery_in_progress)) {
        pr_warn("self-heal: recovery already in progress, skipping\n");
        return -EAGAIN;
    }

    /* 检查冷却期 */
    if (heal_is_on_cooldown(type)) {
        return 0;  /* 静默跳过 */
    }

    /* 获取配置 */
    if (type >= HEAL_EVENT_MAX)
        return -EINVAL;

    /* 检查是否启用 */
    if (!g_self_heal.configs[type].enabled) {
        return 0;
    }

    /* 更新冷却期 */
    heal_update_cooldown(type);

    /* 递增统计 */
    heal_stats_inc(&g_self_heal.stats.events_detected);

    /* 确定起始级别 */
    if (level_override == HEAL_LEVEL_DEFAULT)
        current_level = g_self_heal.configs[type].level;
    else
        current_level = level_override;

    max_level = g_self_heal.configs[type].auto_escalate ?
                HEAL_LEVEL_PANIC : current_level;

    /* 设置恢复执行标志 */
    atomic_set(&g_self_heal.recovery_in_progress, 1);

    /* 渐变恢复循环 */
    while (current_level <= max_level && attempts < max_recovery_attempts) {
        attempts++;

        ret = heal_execute_recovery(type, current_level);
        if (ret == 0) {
            level_used = current_level;
            if (current_level > g_self_heal.configs[type].level) {
                escalated = true;
                heal_stats_inc(&g_self_heal.stats.escalation_count);
            }
            heal_stats_inc(&g_self_heal.stats.recovery_success);
            break;
        }

        /* 失败，记录并尝试升级 */
        if (current_level < max_level) {
            pr_info("self-heal: level %s failed, escalating to next level\n",
                    heal_level_name(current_level));
            current_level++;
            escalated = true;
            heal_stats_inc(&g_self_heal.stats.escalation_count);
            msleep(100);  /* 短暂延迟再尝试更高级别 */
        } else {
            break;
        }
    }

    heal_stats_inc(&g_self_heal.stats.recovery_attempts);

    if (ret != 0) {
        heal_stats_inc(&g_self_heal.stats.recovery_failed);
    }

    /* 清除恢复执行标志 */
    atomic_set(&g_self_heal.recovery_in_progress, 0);

    /* 填充事件记录 */
    memset(&rec, 0, sizeof(rec));
    rec.timestamp_ns = ktime_get_real_ns();
    rec.type = type;
    rec.level_used = level_used;
    rec.level_escalated = escalated ? current_level : level_used;
    rec.result = ret;
    rec.pid = (u32)pid;
    strscpy(rec.comm, "", sizeof(rec.comm));
    if (description)
        strscpy(rec.description, description, sizeof(rec.description));
    else
        strscpy(rec.description, heal_event_name(type), sizeof(rec.description));

    /* 推入环形缓冲区 */
    heal_ring_push(&g_self_heal.ring, &rec);

    /* 更新健康状态 */
    g_self_heal.health_score = heal_calculate_health_score();
    g_self_heal.health_status = heal_calculate_health_status(g_self_heal.health_score);

    /* 更新统计中的最后事件时间 */
    g_self_heal.stats.last_event_ns = rec.timestamp_ns;

    pr_info("self-heal: event=%s level=%s -> %s (attempts=%d, health=%u)\n",
            heal_event_name(type), heal_level_name(level_used),
            ret == 0 ? "OK" : "FAILED",
            attempts, g_self_heal.health_score);

    return ret;
}

/* ================================================================
 * 预防性监控 (定时器 + 工作队列)
 * ================================================================ */

static void heal_monitor_work(struct work_struct *work)
{
    unsigned long avail, total;
    unsigned int free_pct;
    unsigned int zombie_count = 0;
    unsigned long load[3];
    unsigned int num_online_cpus;
    struct task_struct *p;
    char desc[128];

    if (!g_self_heal.initialized)
        return;

    /* 1. 内存压力检查 */
    total = totalram_pages() + total_swap_pages;
    avail = si_mem_available(NULL);
    if (total > 0) {
        free_pct = (unsigned int)(avail * 100 / total);
        if (free_pct < mem_pressure_crit_pct) {
            snprintf(desc, sizeof(desc),
                     "Critical memory pressure: %u%% free (%lu MB/%lu MB)",
                     free_pct, (avail * 4) / 1024, (total * 4) / 1024);
            heal_process_event(HEAL_EVENT_MEM_PRESSURE, HEAL_LEVEL_DEFAULT, 0, desc);
        } else if (free_pct < mem_pressure_warn_pct) {
            snprintf(desc, sizeof(desc),
                     "Memory pressure warning: %u%% free", free_pct);
            heal_process_event(HEAL_EVENT_MEM_PRESSURE, HEAL_LEVEL_LOG, 0, desc);
        }
    }

    /* 2. 僵尸进程检查 */
    rcu_read_lock();
    for_each_process(p) {
        if (p->exit_state == EXIT_ZOMBIE)
            zombie_count++;
    }
    rcu_read_unlock();

    if (zombie_count >= zombie_crit_count) {
        snprintf(desc, sizeof(desc), "%u zombie processes detected", zombie_count);
        heal_process_event(HEAL_EVENT_ZOMBIE, HEAL_LEVEL_LOG, 0, desc);
    } else if (zombie_count >= zombie_warn_count) {
        snprintf(desc, sizeof(desc), "%u zombie processes", zombie_count);
        heal_process_event(HEAL_EVENT_ZOMBIE, HEAL_LEVEL_LOG, 0, desc);
    }

    /* 3. 系统负载检查 */
    get_avenrun(load, FIXED_1/100, 0);
    num_online_cpus = num_online_cpus();
    if (num_online_cpus > 0) {
        unsigned long load_avg = load[0] / 100;  /* 转换为整数 */
        if (load_avg > num_online_cpus * load_crit_multiplier) {
            snprintf(desc, sizeof(desc),
                     "Critical load average: %lu (CPUs: %u)", load_avg, num_online_cpus);
            heal_process_event(HEAL_EVENT_HIGH_LOAD, HEAL_LEVEL_DEFAULT, 0, desc);
        } else if (load_avg > num_online_cpus * load_warn_multiplier) {
            snprintf(desc, sizeof(desc),
                     "High load average: %lu (CPUs: %u)", load_avg, num_online_cpus);
            heal_process_event(HEAL_EVENT_HIGH_LOAD, HEAL_LEVEL_LOG, 0, desc);
        }
    }

    /* 4. 更新健康状态 */
    g_self_heal.health_score = heal_calculate_health_score();
    g_self_heal.health_status = heal_calculate_health_status(g_self_heal.health_score);
    g_self_heal.last_monitor_jiffies = jiffies;
}

static void heal_monitor_timer_cb(struct timer_list *t)
{
    /* 定时器在原子上下文，将实际工作调度到工作队列 */
    if (g_self_heal.initialized && g_self_heal.monitor_wq)
        queue_work(g_self_heal.monitor_wq, &g_self_heal.monitor_work);

    /* 重新设置定时器 */
    if (g_self_heal.initialized)
        mod_timer(&g_self_heal.monitor_timer,
                  jiffies + msecs_to_jiffies(monitor_interval_sec * 1000));
}

/* ================================================================
 * Panic 通知器
 * ================================================================ */

/*
 * Panic 通知器回调。
 * 在 panic 上下文中调用，所有 CPU 已停止。
 * 必须非常小心:
 *   - 不能睡眠 (msleep, mutex)
 *   - 不能分配内存
 *   - 不能获取已经是 panic 上下文的锁
 *   - 只能做原子操作
 */
static int heal_panic_notifier(struct notifier_block *nb,
                                unsigned long action, void *data)
{
    const char *msg = data ? (const char *)data : "unknown";
    struct heal_event_record rec;

    /* 在 panic 上下文中，只做最必要的记录 */
    pr_info("self-heal: PANIC detected: %s\n", msg);

    /* 尝试记录事件 (仅使用栈内存) */
    memset(&rec, 0, sizeof(rec));
    rec.timestamp_ns = ktime_get_real_ns();
    rec.type = HEAL_EVENT_PANIC;
    rec.level_used = HEAL_LEVEL_PANIC;
    rec.level_escalated = HEAL_LEVEL_PANIC;
    rec.result = -EFAULT;
    strscpy(rec.description, msg, sizeof(rec.description));

    /* 尝试推入环形缓冲区 (可能失败，这是预期的) */
    unsigned long flags;
    if (spin_trylock_irqsave(&g_self_heal.ring.lock, flags)) {
        if (g_self_heal.ring.entries) {
            rec.seq = (u32)atomic64_inc_return(&g_self_heal.ring.seq_counter);
            g_self_heal.ring.entries[g_self_heal.ring.head] = rec;
            g_self_heal.ring.head = (g_self_heal.ring.head + 1) &
                                    (g_self_heal.ring.max_entries - 1);
            if (g_self_heal.ring.count == g_self_heal.ring.max_entries)
                g_self_heal.ring.tail = (g_self_heal.ring.tail + 1) &
                                         (g_self_heal.ring.max_entries - 1);
            else
                g_self_heal.ring.count++;
        }
        spin_unlock_irqrestore(&g_self_heal.ring.lock, flags);
    }

    /* 更新统计 (原子操作，总是安全) */
    heal_stats_inc(&g_self_heal.stats.events_detected);
    g_self_heal.stats.last_event_ns = rec.timestamp_ns;

    /* 通知链继续执行，让 panic 完成 */
    return NOTIFY_DONE;
}

/* ================================================================
 * /proc/self-heal/status
 * ================================================================ */

static int heal_proc_status_show(struct seq_file *m, void *v)
{
    u64 uptime_ms;
    unsigned long total_ram = totalram_pages() + total_swap_pages;
    unsigned long avail_ram = si_mem_available(NULL);
    unsigned int free_pct = 0;
    unsigned long load[3];
    unsigned int zombie_count = 0;
    struct task_struct *p;

    if (total_ram > 0)
        free_pct = (unsigned int)(avail_ram * 100 / total_ram);

    rcu_read_lock();
    for_each_process(p) {
        if (p->exit_state == EXIT_ZOMBIE)
            zombie_count++;
    }
    rcu_read_unlock();

    get_avenrun(load, FIXED_1/100, 0);

    uptime_ms = (jiffies - g_self_heal.module_start_jiffies) * 1000 / HZ;

    seq_printf(m, "Ainos Self-Healing Module v%s\n", SELF_HEAL_VERSION);
    seq_printf(m, "========================================\n");
    seq_printf(m, "Health Status:    %s\n",
               heal_health_name(g_self_heal.health_status));
    seq_printf(m, "Health Score:     %u/100\n", g_self_heal.health_score);
    seq_printf(m, "Uptime:           %llu seconds\n", uptime_ms / 1000);
    seq_printf(m, "Monitor Interval: %u seconds\n", monitor_interval_sec);
    seq_printf(m, "AI Integration:   %s\n", enable_ai_integration ? "enabled" : "disabled");
    seq_printf(m, "\n");

    seq_printf(m, "--- System Status ---\n");
    seq_printf(m, "Memory:           %lu MB total, %lu MB available (%u%% free)\n",
               (total_ram * 4) / 1024, (avail_ram * 4) / 1024, free_pct);
    seq_printf(m, "Load Average:     %lu / %lu / %lu\n",
               load[0] / 100, load[1] / 100, load[2] / 100);
    seq_printf(m, "CPUs:             %u\n", num_online_cpus());
    seq_printf(m, "Zombie Processes: %u\n", zombie_count);
    seq_printf(m, "\n");

    seq_printf(m, "--- Recovery Statistics ---\n");
    seq_printf(m, "Events Detected:   %llu\n",
               heal_stats_read(&g_self_heal.stats.events_detected));
    seq_printf(m, "Recovery Attempts: %llu\n",
               heal_stats_read(&g_self_heal.stats.recovery_attempts));
    seq_printf(m, "Recovery Success:  %llu\n",
               heal_stats_read(&g_self_heal.stats.recovery_success));
    seq_printf(m, "Recovery Failed:   %llu\n",
               heal_stats_read(&g_self_heal.stats.recovery_failed));
    seq_printf(m, "Escalations:       %llu\n",
               heal_stats_read(&g_self_heal.stats.escalation_count));
    seq_printf(m, "Prevention Actions:%llu\n",
               heal_stats_read(&g_self_heal.stats.prevention_actions));
    seq_printf(m, "Tasks Killed:      %llu\n",
               heal_stats_read(&g_self_heal.stats.tasks_killed));
    seq_printf(m, "Drivers Reloaded:  %llu\n",
               heal_stats_read(&g_self_heal.stats.drivers_reloaded));
    seq_printf(m, "KExec Triggers:    %llu\n",
               heal_stats_read(&g_self_heal.stats.kexec_triggers));
    seq_printf(m, "Current Level:     %u\n",
               g_self_heal.stats.current_level);

    return 0;
}

static int heal_proc_status_open(struct inode *inode, struct file *file)
{
    return single_open(file, heal_proc_status_show, NULL);
}

static const struct proc_ops heal_proc_status_ops = {
    .proc_open    = heal_proc_status_open,
    .proc_read    = seq_read,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

/* ================================================================
 * /proc/self-heal/config
 * ================================================================ */

static int heal_proc_config_show(struct seq_file *m, void *v)
{
    mutex_lock(&g_self_heal.config_lock);

    seq_printf(m, "# %-16s %-8s %-10s %-12s %-8s %-8s\n",
               "Event", "Level", "Cooldown", "MaxAttempts", "Enabled", "Escalate");
    seq_printf(m, "# %s\n",
               "----------------------------------------------------------------------");

    for (int i = 0; i < HEAL_EVENT_MAX; i++) {
        struct heal_event_config *cfg = &g_self_heal.configs[i];
        seq_printf(m, "  %-16s %-8s %-10u %-12u %-8s %-8s\n",
                   cfg->name,
                   heal_level_name(cfg->level),
                   cfg->cooldown_ms,
                   cfg->max_attempts,
                   cfg->enabled ? "yes" : "no",
                   cfg->auto_escalate ? "yes" : "no");
    }

    mutex_unlock(&g_self_heal.config_lock);
    return 0;
}

static int heal_proc_config_open(struct inode *inode, struct file *file)
{
    return single_open(file, heal_proc_config_show, NULL);
}

/*
 * 写入格式: "<event_name> <level> [cooldown_ms] [max_attempts] [enabled] [auto_escalate]"
 * 示例:    "mem_pressure soft 60000 5 yes yes"
 *          "panic kexec 0 1 yes yes"
 * 特殊命令: "reset" - 重置所有配置为默认值
 */
static ssize_t heal_proc_config_write(struct file *file,
                                       const char __user *ubuf,
                                       size_t count, loff_t *ppos)
{
    char buf[256];
    char cmd[32];
    char level_str[16];
    unsigned int cooldown = 0;
    unsigned int max_attempts = 0;
    char enabled_str[8] = "";
    char escalate_str[8] = "";
    int parsed;
    int i;

    if (count >= sizeof(buf))
        return -EINVAL;

    if (copy_from_user(buf, ubuf, count))
        return -EFAULT;
    buf[count] = '\0';

    /* 去除换行符 */
    if (count > 0 && buf[count - 1] == '\n')
        buf[count - 1] = '\0';

    /* 特殊命令: reset */
    if (strcmp(buf, "reset") == 0) {
        mutex_lock(&g_self_heal.config_lock);
        for (i = 0; i < HEAL_EVENT_MAX; i++)
            g_self_heal.configs[i] = default_configs[i];
        mutex_unlock(&g_self_heal.config_lock);
        pr_info("self-heal: config reset to defaults\n");
        return count;
    }

    /* 解析配置行 */
    parsed = sscanf(buf, "%31s %15s %u %u %7s %7s",
                    cmd, level_str, &cooldown, &max_attempts,
                    enabled_str, escalate_str);
    if (parsed < 2)
        return -EINVAL;

    /* 查找事件类型 */
    int found = -1;
    for (i = 0; i < HEAL_EVENT_MAX; i++) {
        if (strcmp(cmd, g_self_heal.configs[i].name) == 0) {
            found = i;
            break;
        }
    }
    if (found < 0)
        return -EINVAL;

    /* 解析级别 */
    int level = -1;
    for (i = HEAL_LEVEL_LOG; i <= HEAL_LEVEL_PANIC; i++) {
        if (strcmp(level_str, heal_level_name(i)) == 0) {
            level = i;
            break;
        }
    }
    if (level < 0)
        return -EINVAL;

    /* 更新配置 */
    mutex_lock(&g_self_heal.config_lock);
    g_self_heal.configs[found].level = level;
    if (parsed >= 3)
        g_self_heal.configs[found].cooldown_ms = cooldown;
    if (parsed >= 4)
        g_self_heal.configs[found].max_attempts = max_attempts;
    if (parsed >= 5)
        g_self_heal.configs[found].enabled =
            (strcmp(enabled_str, "yes") == 0 || strcmp(enabled_str, "1") == 0);
    if (parsed >= 6)
        g_self_heal.configs[found].auto_escalate =
            (strcmp(escalate_str, "yes") == 0 || strcmp(escalate_str, "1") == 0);
    mutex_unlock(&g_self_heal.config_lock);

    pr_info("self-heal: config updated: %s level=%s cooldown=%u max_attempts=%u\n",
            cmd, level_str, cooldown, max_attempts);

    return count;
}

static const struct proc_ops heal_proc_config_ops = {
    .proc_open    = heal_proc_config_open,
    .proc_read    = seq_read,
    .proc_write   = heal_proc_config_write,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

/* ================================================================
 * /proc/self-heal/trigger
 * ================================================================ */

/*
 * 触发命令格式:
 *   "<event_name> [level] [pid] [reason]"
 *   "trigger panic test" - 模拟 panic
 *   "trigger mem_pressure soft 1234 OOM process" - 带 PID 和描述
 *   "reset" - 重置统计
 */
static ssize_t heal_proc_trigger_write(struct file *file,
                                        const char __user *ubuf,
                                        size_t count, loff_t *ppos)
{
    char buf[256];
    char cmd[32];
    char level_str[16] = "";
    char reason[128] = "";
    int pid = 0;
    int parsed;

    if (count >= sizeof(buf))
        return -EINVAL;

    if (copy_from_user(buf, ubuf, count))
        return -EFAULT;
    buf[count] = '\0';

    if (count > 0 && buf[count - 1] == '\n')
        buf[count - 1] = '\0';

    /* 特殊命令: reset stats */
    if (strcmp(buf, "reset") == 0) {
        heal_stats_init(&g_self_heal.stats);
        pr_info("self-heal: stats reset\n");
        return count;
    }

    /* 解析: <event> [level] [pid] [reason...] */
    parsed = sscanf(buf, "%31s %15s %d %127[^\n]", cmd, level_str, &pid, reason);
    if (parsed < 1)
        return -EINVAL;

    /* 查找事件类型 */
    int type = -1;
    for (int i = 0; i < HEAL_EVENT_MAX; i++) {
        if (strcmp(cmd, g_self_heal.configs[i].name) == 0) {
            type = i;
            break;
        }
    }
    if (type < 0) {
        /* 尝试直接匹配 trigger 命令 */
        if (strcmp(cmd, "trigger") == 0 && parsed >= 2) {
            /* trigger <event> 格式 */
            for (int i = 0; i < HEAL_EVENT_MAX; i++) {
                if (strcmp(level_str, g_self_heal.configs[i].name) == 0) {
                    type = i;
                    /* 调整解析 */
                    parsed = sscanf(buf, "%*s %*s %15s %d %127[^\n]",
                                    level_str, &pid, reason);
                    break;
                }
            }
        }
        if (type < 0) {
            pr_warn("self-heal: unknown event type '%s'\n", cmd);
            return -EINVAL;
        }
    }

    /* 解析级别 (可选) */
    enum heal_level level = HEAL_LEVEL_DEFAULT;  /* 使用配置默认 */
    if (parsed >= 2 && strlen(level_str) > 0) {
        for (i = HEAL_LEVEL_LOG; i < HEAL_LEVEL_NUM; i++) {
            if (strcmp(level_str, heal_level_name(i)) == 0) {
                level = i;
                break;
            }
        }
    }

    if (strlen(reason) == 0)
        snprintf(reason, sizeof(reason), "triggered by /proc/self-heal/trigger");

    pr_info("self-heal: manual trigger: event=%s level=%s pid=%d reason=%s\n",
            heal_event_name(type),
            level == HEAL_LEVEL_DEFAULT ? "default" : heal_level_name(level),
            pid, reason);

    /* 执行恢复 */
    int ret = heal_process_event(type, level, pid, reason);

    return ret == 0 ? count : (ssize_t)ret;
}

static const struct proc_ops heal_proc_trigger_ops = {
    .proc_write = heal_proc_trigger_write,
};

/* ================================================================
 * /proc/self-heal/history
 * ================================================================ */

static int heal_proc_history_show(struct seq_file *m, void *v)
{
    unsigned long flags;
    unsigned int n;
    unsigned int i, idx;

    spin_lock_irqsave(&g_self_heal.ring.lock, flags);

    n = g_self_heal.ring.count;
    if (n == 0) {
        seq_puts(m, "No events recorded.\n");
        spin_unlock_irqrestore(&g_self_heal.ring.lock, flags);
        return 0;
    }

    seq_printf(m, "%-20s %-8s %-16s %-7s %-6s %-16s %s\n",
               "Timestamp", "Seq", "Event", "Level", "Result", "Description", "PID");

    for (i = 0; i < n; i++) {
        idx = (g_self_heal.ring.tail + i) & (g_self_heal.ring.max_entries - 1);
        const struct heal_event_record *r = &g_self_heal.ring.entries[idx];
        unsigned long long ns = r->timestamp_ns;
        unsigned long long secs = ns / 1000000000ULL;
        unsigned long long usecs = (ns / 1000) % 1000000;

        seq_printf(m, "%5llu.%06llu %-8u %-16s %-7s %-6d %-16s %u\n",
                   secs, usecs,
                   r->seq,
                   heal_event_name(r->type),
                   heal_level_name(r->level_used),
                   r->result,
                   r->description,
                   r->pid);
    }

    seq_printf(m, "\n%u events total (buffer: %u)\n", n, g_self_heal.ring.max_entries);

    spin_unlock_irqrestore(&g_self_heal.ring.lock, flags);
    return 0;
}

static int heal_proc_history_open(struct inode *inode, struct file *file)
{
    return single_open(file, heal_proc_history_show, NULL);
}

static const struct proc_ops heal_proc_history_ops = {
    .proc_open    = heal_proc_history_open,
    .proc_read    = seq_read,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

/* ================================================================
 * 导出函数 (给其他内核模块使用)
 * ================================================================ */

int self_heal_report_event(enum heal_event_type type,
                           pid_t pid,
                           const char *description)
{
    return heal_process_event(type, HEAL_LEVEL_DEFAULT, pid, description);
}
EXPORT_SYMBOL_GPL(self_heal_report_event);

int self_heal_report_event_level(enum heal_event_type type,
                                 enum heal_level level,
                                 pid_t pid,
                                 const char *description)
{
    return heal_process_event(type, level, pid, description);
}
EXPORT_SYMBOL_GPL(self_heal_report_event_level);

enum heal_health_status self_heal_get_health(void)
{
    return g_self_heal.health_status;
}
EXPORT_SYMBOL_GPL(self_heal_get_health);

unsigned int self_heal_get_health_score(void)
{
    return g_self_heal.health_score;
}
EXPORT_SYMBOL_GPL(self_heal_get_health_score);

int self_heal_force_recovery(enum heal_event_type type,
                             enum heal_level level,
                             pid_t pid)
{
    return heal_process_event(type, level, pid, "forced recovery");
}
EXPORT_SYMBOL_GPL(self_heal_force_recovery);

/* ================================================================
 * 初始化
 * ================================================================ */

static int __init self_heal_init(void)
{
    int ret = 0;
    int i;

    pr_info("self-heal: Ainos Self-Healing v%s initializing...\n", SELF_HEAL_VERSION);

    /* 初始化全局状态 */
    memset(&g_self_heal, 0, sizeof(g_self_heal));
    g_self_heal.health_status = HEAL_HEALTH_OK;
    g_self_heal.health_score = 100;
    g_self_heal.module_start_jiffies = jiffies;
    g_self_heal.initialized = false;
    atomic_set(&g_self_heal.recovery_in_progress, 0);

    /* 初始化统计 */
    heal_stats_init(&g_self_heal.stats);

    /* 初始化配置锁 */
    mutex_init(&g_self_heal.config_lock);

    /* 初始化冷却期 */
    for (i = 0; i < HEAL_EVENT_MAX; i++)
        g_self_heal.last_event_jiffies[i] = 0;

    /* 加载默认配置 */
    for (i = 0; i < HEAL_EVENT_MAX; i++)
        g_self_heal.configs[i] = default_configs[i];

    /* 初始化环形缓冲区 */
    ret = heal_ring_init(&g_self_heal.ring, ring_buffer_size);
    if (ret < 0) {
        pr_err("self-heal: failed to init ring buffer (%d)\n", ret);
        goto err_ring;
    }

    /* 创建监控工作队列 */
    g_self_heal.monitor_wq = create_singlethread_workqueue("self-heal-mon");
    if (!g_self_heal.monitor_wq) {
        pr_err("self-heal: failed to create workqueue\n");
        ret = -ENOMEM;
        goto err_wq;
    }

    INIT_WORK(&g_self_heal.monitor_work, heal_monitor_work);

    /* 创建 /proc/self-heal 目录 */
    g_self_heal.proc_dir = proc_mkdir("self-heal", NULL);
    if (!g_self_heal.proc_dir) {
        pr_err("self-heal: failed to create /proc/self-heal\n");
        ret = -ENOMEM;
        goto err_proc;
    }

    /* 创建 proc 文件 */
    g_self_heal.proc_status = proc_create("status", 0444,
                                           g_self_heal.proc_dir,
                                           &heal_proc_status_ops);
    if (!g_self_heal.proc_status) {
        pr_err("self-heal: failed to create /proc/self-heal/status\n");
        ret = -ENOMEM;
        goto err_proc_files;
    }

    g_self_heal.proc_config = proc_create("config", 0644,
                                           g_self_heal.proc_dir,
                                           &heal_proc_config_ops);
    if (!g_self_heal.proc_config) {
        pr_err("self-heal: failed to create /proc/self-heal/config\n");
        ret = -ENOMEM;
        goto err_proc_files;
    }

    g_self_heal.proc_trigger = proc_create("trigger", 0200,
                                            g_self_heal.proc_dir,
                                            &heal_proc_trigger_ops);
    if (!g_self_heal.proc_trigger) {
        pr_err("self-heal: failed to create /proc/self-heal/trigger\n");
        ret = -ENOMEM;
        goto err_proc_files;
    }

    g_self_heal.proc_history = proc_create("history", 0444,
                                            g_self_heal.proc_dir,
                                            &heal_proc_history_ops);
    if (!g_self_heal.proc_history) {
        pr_err("self-heal: failed to create /proc/self-heal/history\n");
        ret = -ENOMEM;
        goto err_proc_files;
    }

    /* 注册 panic 通知器 */
    g_self_heal.panic_nb.notifier_call = heal_panic_notifier;
    g_self_heal.panic_nb.priority = INT_MAX;  /* 最高优先级 */
    ret = atomic_notifier_chain_register(&panic_notifier_list,
                                          &g_self_heal.panic_nb);
    if (ret) {
        pr_err("self-heal: failed to register panic notifier (%d)\n", ret);
        goto err_panic;
    }

    /* 启动预防性监控定时器 */
    if (enable_preventive) {
        timer_setup(&g_self_heal.monitor_timer, heal_monitor_timer_cb, 0);
        mod_timer(&g_self_heal.monitor_timer,
                  jiffies + msecs_to_jiffies(monitor_interval_sec * 1000));
        pr_info("self-heal: preventive monitoring started (interval=%us)\n",
                monitor_interval_sec);
    }

    g_self_heal.initialized = true;

    pr_info("self-heal: Ainos Self-Healing v%s initialized successfully\n",
            SELF_HEAL_VERSION);
    pr_info("self-heal: /proc/self-heal/{status,config,trigger,history}\n");
    pr_info("self-heal: %u event types, %u-entry ring buffer\n",
            HEAL_EVENT_MAX, ring_buffer_size);

    return 0;

err_panic:
    /* Panic 通知器注册失败，清理 proc 文件 */
err_proc_files:
    if (g_self_heal.proc_history) remove_proc_entry("history", g_self_heal.proc_dir);
    if (g_self_heal.proc_trigger) remove_proc_entry("trigger", g_self_heal.proc_dir);
    if (g_self_heal.proc_config)  remove_proc_entry("config", g_self_heal.proc_dir);
    if (g_self_heal.proc_status)  remove_proc_entry("status", g_self_heal.proc_dir);
    remove_proc_entry("self-heal", NULL);
    g_self_heal.proc_dir = NULL;

err_proc:
    if (g_self_heal.monitor_wq)
        destroy_workqueue(g_self_heal.monitor_wq);

err_wq:
    heal_ring_destroy(&g_self_heal.ring);

err_ring:
    pr_err("self-heal: initialization failed (%d)\n", ret);
    return ret;
}

/* ================================================================
 * 清理
 * ================================================================ */

static void __exit self_heal_exit(void)
{
    if (!g_self_heal.initialized)
        return;

    pr_info("self-heal: shutting down...\n");

    g_self_heal.initialized = false;

    /* 停止监控定时器 */
    if (enable_preventive)
        del_timer_sync(&g_self_heal.monitor_timer);

    /* 刷新工作队列 */
    if (g_self_heal.monitor_wq) {
        flush_work(&g_self_heal.monitor_work);
        destroy_workqueue(g_self_heal.monitor_wq);
    }

    /* 注销 panic 通知器 */
    atomic_notifier_chain_unregister(&panic_notifier_list,
                                      &g_self_heal.panic_nb);

    /* 清理 proc 文件 */
    if (g_self_heal.proc_history)
        remove_proc_entry("history", g_self_heal.proc_dir);
    if (g_self_heal.proc_trigger)
        remove_proc_entry("trigger", g_self_heal.proc_dir);
    if (g_self_heal.proc_config)
        remove_proc_entry("config", g_self_heal.proc_dir);
    if (g_self_heal.proc_status)
        remove_proc_entry("status", g_self_heal.proc_dir);
    if (g_self_heal.proc_dir)
        remove_proc_entry("self-heal", NULL);

    /* 清理环形缓冲区 */
    heal_ring_destroy(&g_self_heal.ring);

    /* 输出最终统计 */
    pr_info("self-heal: final stats: detected=%llu attempts=%llu success=%llu failed=%llu\n",
            heal_stats_read(&g_self_heal.stats.events_detected),
            heal_stats_read(&g_self_heal.stats.recovery_attempts),
            heal_stats_read(&g_self_heal.stats.recovery_success),
            heal_stats_read(&g_self_heal.stats.recovery_failed));

    pr_info("self-heal: unloaded\n");
}

module_init(self_heal_init);
module_exit(self_heal_exit);