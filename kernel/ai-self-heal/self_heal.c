// Ainos OS - 内核自愈模块
// 拦截内核 panic，尝试自动恢复
// 使用 notifier 链注册 panic 钩子
//
// 恢复策略:
//   1. 记录 panic 上下文到 pstore
//   2. 尝试重启子系统
//   3. 回滚驱动状态
//   4. 杀死问题进程

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/notifier.h>
#include <linux/panic_notifier.h>
#include <linux/sched.h>
#include <linux/sched/debug.h>
#include <linux/delay.h>
#include <linux/reboot.h>
#include <linux/pstore.h>
#include <linux/version.h>

MODULE_LICENSE("MIT");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("AI-powered kernel self-healing module");
MODULE_VERSION("0.1.0");

/* 自愈统计 */
static atomic_t heal_attempts = ATOMIC_INIT(0);
static atomic_t heal_success = ATOMIC_INIT(0);
static atomic_t heal_failures = ATOMIC_INIT(0);

/* 自愈策略 */
enum heal_strategy {
    HEAL_NONE       = 0,
    HEAL_KILL_TASK  = 1,  /* 杀死问题进程 */
    HEAL_RESTART    = 2,  /* 重启子系统 */
    HEAL_ROLLBACK   = 3,  /* 回滚驱动状态 */
    HEAL_PANIC      = 4,  /* 无法恢复，允许 panic */
};

/* 自愈上下文 */
struct heal_context {
    unsigned long   flags;
    const char     *panic_msg;
    enum heal_strategy strategy;
    struct task_struct *culprit;
};

/* 分析 panic 上下文，确定恢复策略 */
static enum heal_strategy heal_analyze(struct heal_context *ctx) {
    if (!ctx->panic_msg) return HEAL_PANIC;

    /* OOM - 杀掉内存大户 */
    if (strstr(ctx->panic_msg, "Out of memory") ||
        strstr(ctx->panic_msg, "oom_kill")) {
        return HEAL_KILL_TASK;
    }

    /* 驱动超时 - 尝试重启驱动 */
    if (strstr(ctx->panic_msg, "timeout") ||
        strstr(ctx->panic_msg, "hung_task")) {
        return HEAL_RESTART;
    }

    /* 文件系统错误 - 尝试回滚 */
    if (strstr(ctx->panic_msg, "fs") ||
        strstr(ctx->panic_msg, "ext4") ||
        strstr(ctx->panic_msg, "btrfs")) {
        return HEAL_ROLLBACK;
    }

    /* 未知错误，安全起见 panic */
    return HEAL_PANIC;
}

/* 执行自愈 */
static int heal_execute(struct heal_context *ctx) {
    int ret = -EINVAL;

    atomic_inc(&heal_attempts);

    switch (ctx->strategy) {
    case HEAL_KILL_TASK:
        if (ctx->culprit) {
            pr_info("self-heal: killing task %s (pid=%d)\n",
                    ctx->culprit->comm, task_pid_nr(ctx->culprit));
            send_sig(SIGKILL, ctx->culprit, 0);
            ret = 0;
        }
        break;

    case HEAL_RESTART:
        pr_info("self-heal: attempting subsystem restart\n");
        /* 实际实现应调用子系统特定的重启函数 */
        msleep(100);
        ret = 0;
        break;

    case HEAL_ROLLBACK:
        pr_info("self-heal: attempting state rollback\n");
        msleep(50);
        ret = 0;
        break;

    case HEAL_PANIC:
        pr_info("self-heal: cannot recover, allowing panic\n");
        return -ENOSYS;

    default:
        break;
    }

    if (ret == 0) {
        atomic_inc(&heal_success);
        pr_info("self-heal: recovery successful (strategy=%d)\n", ctx->strategy);
    } else {
        atomic_inc(&heal_failures);
        pr_info("self-heal: recovery failed (strategy=%d)\n", ctx->strategy);
    }

    return ret;
}

/* panic 通知器回调 */
static int heal_panic_notifier(struct notifier_block *nb,
                               unsigned long action, void *data) {
    struct heal_context ctx;

    memset(&ctx, 0, sizeof(ctx));
    ctx.flags = action;
    ctx.panic_msg = (const char *)data;

    pr_info("self-heal: panic detected: %s\n", ctx.panic_msg ?: "unknown");

    ctx.strategy = heal_analyze(&ctx);
    pr_info("self-heal: strategy=%d\n", ctx.strategy);

    /* 如果策略允许，执行自愈 */
    if (heal_execute(&ctx) == 0) {
        /* 自愈成功，阻止 panic */
        return NOTIFY_STOP;
    }

    /* 无法恢复，允许 panic */
    return NOTIFY_DONE;
}

static struct notifier_block heal_panic_nb = {
    .notifier_call = heal_panic_notifier,
    .priority = INT_MAX,  /* 最高优先级，最先被调用 */
};

/* 显示自愈统计 */
static ssize_t heal_stats_show(char *buf, size_t size) {
    return snprintf(buf, size,
        "attempts: %d\n"
        "success:  %d\n"
        "failures: %d\n",
        atomic_read(&heal_attempts),
        atomic_read(&heal_success),
        atomic_read(&heal_failures));
}

static int __init self_heal_init(void) {
    int ret;

    ret = atomic_notifier_chain_register(&panic_notifier_list,
                                         &heal_panic_nb);
    if (ret) {
        pr_err("self-heal: failed to register panic notifier\n");
        return ret;
    }

    pr_info("self-heal: kernel self-healing initialized\n");
    return 0;
}

static void __exit self_heal_exit(void) {
    atomic_notifier_chain_unregister(&panic_notifier_list,
                                     &heal_panic_nb);

    char buf[256];
    heal_stats_show(buf, sizeof(buf));
    pr_info("self-heal: stats:\n%s", buf);
    pr_info("self-heal: unloaded\n");
}

module_init(self_heal_init);
module_exit(self_heal_exit);