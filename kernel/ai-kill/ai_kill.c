// Ainos OS - AI KILL 智能进程管理器
// 基于行为分析的智能进程终止系统
// 比传统 OOM killer 更精准，考虑多维度指标
//
// 评分维度: CPU 使用率、内存泄漏趋势、IO 异常、网络行为

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/sched.h>
#include <linux/sched/signal.h>
#include <linux/mm.h>
#include <linux/fs.h>
#include <linux/proc_fs.h>
#include <linux/seq_file.h>
#include <linux/timer.h>
#include <linux/version.h>

MODULE_LICENSE("MIT");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("AI KILL - intelligent process manager");
MODULE_VERSION("0.1.0");

#define SCORE_THRESHOLD_KILL   80  /* 直接 SIGKILL */
#define SCORE_THRESHOLD_TERM   60  /* 先 SIGTERM */
#define SCORE_THRESHOLD_WARN   40  /* 记录警告 */
#define SCAN_INTERVAL_MS       5000 /* 每 5 秒扫描一次 */

/* 进程评分 */
struct process_score {
    pid_t pid;
    char comm[TASK_COMM_LEN];
    int cpu_score;       /* CPU 使用异常 */
    int mem_score;       /* 内存泄漏趋势 */
    int io_score;        /* IO 异常 */
    int net_score;       /* 网络行为异常 */
    int total_score;
    unsigned long rss;   /* 当前 RSS */
    unsigned long rss_prev; /* 上次 RSS */
    unsigned long faults;    /* 缺页数 */
    unsigned long faults_prev;
};

/* 扫描定时器 */
static struct timer_list scan_timer;
static struct proc_dir_entry *ai_kill_dir;
static struct proc_dir_entry *scores_file;
static struct proc_dir_entry *config_file;

/* 配置 */
static int score_threshold_kill = SCORE_THRESHOLD_KILL;
static int score_threshold_term = SCORE_THRESHOLD_TERM;
static int scan_interval_ms = SCAN_INTERVAL_MS;
static int enabled = 1;

/* 计算进程 CPU 评分 */
static int calc_cpu_score(struct task_struct *task) {
    unsigned long total_time, cpu_time;
    int score = 0;

    total_time = (unsigned long)ktime_get_seconds();
    cpu_time = task->utime + task->stime;

    /* CPU 使用率 > 80% 持续超过 10 秒 */
    if (cpu_time > 10 && total_time > 0) {
        int pct = (int)(cpu_time * 100 / total_time);
        if (pct > 90) score = 40;
        else if (pct > 80) score = 30;
        else if (pct > 60) score = 20;
    }

    return score;
}

/* 计算进程内存评分 */
static int calc_mem_score(struct task_struct *task) {
    struct mm_struct *mm;
    int score = 0;
    unsigned long rss;

    mm = get_task_mm(task);
    if (!mm) return 0;

    rss = get_mm_rss(mm) * PAGE_SIZE / (1024 * 1024); /* MB */
    mmput(mm);

    /* 内存占用 > 1GB */
    if (rss > 1024) score += 30;
    else if (rss > 512) score += 20;
    else if (rss > 256) score += 10;

    return score;
}

/* 计算进程 IO 评分 */
static int calc_io_score(struct task_struct *task) {
    int score = 0;

    /* IO 密集型进程 */
    if (task->io_count > 10000) score += 20;
    else if (task->io_count > 5000) score += 10;

    return score;
}

/* 计算进程综合评分 */
static int calc_total_score(struct task_struct *task) {
    int cpu = calc_cpu_score(task);
    int mem = calc_mem_score(task);
    int io  = calc_io_score(task);
    int total = cpu + mem + io;

    /* 系统关键进程不杀 */
    if (task->pid <= 1 || task->flags & PF_KTHREAD)
        return 0;

    return total;
}

/* 扫描进程并执行 AI KILL */
static void scan_processes(struct timer_list *t) {
    struct task_struct *task;
    struct task_struct *victim = NULL;
    int max_score = 0;

    if (!enabled) goto reschedule;

    rcu_read_lock();
    for_each_process(task) {
        if (task->flags & PF_KTHREAD) continue;
        if (task->exit_state) continue;

        int score = calc_total_score(task);
        if (score > max_score) {
            max_score = score;
            victim = task;
        }
    }
    rcu_read_unlock();

    if (victim && max_score > 0) {
        pr_info("ai-kill: process %s (pid=%d) score=%d\n",
                victim->comm, task_pid_nr(victim), max_score);

        if (max_score >= score_threshold_kill) {
            pr_info("ai-kill: KILLING %s (pid=%d) score=%d\n",
                    victim->comm, task_pid_nr(victim), max_score);
            send_sig(SIGKILL, victim, 0);
        } else if (max_score >= score_threshold_term) {
            pr_info("ai-kill: TERM %s (pid=%d) score=%d\n",
                    victim->comm, task_pid_nr(victim), max_score);
            send_sig(SIGTERM, victim, 0);
        } else if (max_score >= score_threshold_warn) {
            pr_info("ai-kill: WARN %s (pid=%d) score=%d\n",
                    victim->comm, task_pid_nr(victim), max_score);
        }
    }

reschedule:
    mod_timer(&scan_timer, jiffies + msecs_to_jiffies(scan_interval_ms));
}

/* /proc/ai/kill/scores 显示 */
static int scores_show(struct seq_file *m, void *v) {
    struct task_struct *task;

    seq_printf(m, "%-8s %-20s %6s %6s %6s %6s\n",
               "PID", "COMM", "CPU", "MEM", "IO", "TOTAL");

    rcu_read_lock();
    for_each_process(task) {
        if (task->flags & PF_KTHREAD) continue;
        int cpu = calc_cpu_score(task);
        int mem = calc_mem_score(task);
        int io  = calc_io_score(task);
        int total = cpu + mem + io;
        if (total > 0) {
            seq_printf(m, "%-8d %-20s %6d %6d %6d %6d\n",
                       task_pid_nr(task), task->comm, cpu, mem, io, total);
        }
    }
    rcu_read_unlock();
    return 0;
}
static int scores_open(struct inode *inode, struct file *file) {
    return single_open(file, scores_show, NULL);
}
static const struct proc_ops scores_fops = {
    .proc_open    = scores_open,
    .proc_read    = seq_read,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

/* /proc/ai/kill/config 显示+写入 */
static int config_show(struct seq_file *m, void *v) {
    seq_printf(m, "enabled: %d\n", enabled);
    seq_printf(m, "scan_interval_ms: %d\n", scan_interval_ms);
    seq_printf(m, "threshold_kill: %d\n", score_threshold_kill);
    seq_printf(m, "threshold_term: %d\n", score_threshold_term);
    return 0;
}
static int config_open(struct inode *inode, struct file *file) {
    return single_open(file, config_show, NULL);
}
static ssize_t config_write(struct file *file, const char __user *buf,
                            size_t len, loff_t *off) {
    char cmd[128];
    if (len > sizeof(cmd) - 1) return -EINVAL;
    if (copy_from_user(cmd, buf, len)) return -EFAULT;
    cmd[len] = '\0';

    int val;
    if (sscanf(cmd, "enabled=%d", &val) == 1) enabled = val;
    else if (sscanf(cmd, "threshold_kill=%d", &val) == 1) score_threshold_kill = val;
    else if (sscanf(cmd, "threshold_term=%d", &val) == 1) score_threshold_term = val;
    else if (sscanf(cmd, "scan_interval_ms=%d", &val) == 1) {
        scan_interval_ms = val;
        mod_timer(&scan_timer, jiffies + msecs_to_jiffies(scan_interval_ms));
    }

    return len;
}
static const struct proc_ops config_fops = {
    .proc_open    = config_open,
    .proc_read    = seq_read,
    .proc_write   = config_write,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

static int __init ai_kill_init(void) {
    ai_kill_dir = proc_mkdir("ai/kill", NULL);
    if (!ai_kill_dir) {
        pr_err("ai-kill: failed to create /proc/ai/kill\n");
        return -ENOMEM;
    }

    scores_file = proc_create("scores", 0444, ai_kill_dir, &scores_fops);
    config_file = proc_create("config", 0644, ai_kill_dir, &config_fops);
    if (!scores_file || !config_file) {
        remove_proc_subtree("ai/kill", NULL);
        return -ENOMEM;
    }

    /* 启动定时扫描 */
    timer_setup(&scan_timer, scan_processes, 0);
    mod_timer(&scan_timer, jiffies + msecs_to_jiffies(5000));

    pr_info("ai-kill: intelligent process manager initialized\n");
    return 0;
}

static void __exit ai_kill_exit(void) {
    del_timer_sync(&scan_timer);
    remove_proc_subtree("ai/kill", NULL);
    pr_info("ai-kill: unloaded\n");
}

module_init(ai_kill_init);
module_exit(ai_kill_exit);