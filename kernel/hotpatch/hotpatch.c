// ================================================================
// Ainos OS - Hotpatch 内核热补丁生成器 (深度实现 v2.0.0)
// ================================================================
//
// 功能:
//   1. 函数级热补丁管理 (注册/应用/回滚)
//   2. kprobe 监控钩子
//   3. x86_64 JMP rel32 指令修补
//   4. stop_machine 安全修补
//   5. /proc/ai-hotpatch 接口
//
// 架构:
//   ┌─────────────────────────────────────────────────────────┐
//   │              Hotpatch 热补丁引擎                          │
//   ├─────────────────────────────────────────────────────────┤
//   │  ┌──────────────────┐  ┌───────────────────────────┐    │
//   │  │ 补丁管理器        │  │ 监控钩子 (kprobe)         │    │
//   │  │ register/apply/  │  │ handler_pre → detect()   │    │
//   │  │ rollback/list    │  │ call_count/error_count   │    │
//   │  └────────┬─────────┘  └──────────────┬────────────┘    │
//   │           ▼                            ▼                 │
//   │  ┌──────────────────────────────────────────────────┐    │
//   │  │ 修补执行器 (stop_machine)                         │    │
//   │  │ • 保存原始指令前 5 字节 (x86_64 JMP rel32)       │    │
//   │  │ • 写入 JMP 指令到补丁函数                        │    │
//   │  │ • 刷新指令缓存 (sync_core)                       │    │
//   │  │ • 回滚时恢复原始指令                             │    │
//   │  │ • 安全检查: 函数是否可修补                       │    │
//   │  └──────────────────────────────────────────────────┘    │
//   │                                                          │
//   │  ┌──────────────────────────────────────────────────┐    │
//   │  │ /proc/ai-hotpatch 接口                            │    │
//   │  │ status | patches | hooks | config                │    │
//   │  └──────────────────────────────────────────────────┘    │
//   └─────────────────────────────────────────────────────────┘
//
// 修补原理 (x86_64):
//   JMP rel32 指令: E9 <4-byte signed offset>
//   跳转偏移 = 目标地址 - (源地址 + 5)
//   +5 是因为 JMP rel32 指令本身长度为 5 字节
//
// ================================================================

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/kprobes.h>
#include <linux/slab.h>
#include <linux/spinlock.h>
#include <linux/mutex.h>
#include <linux/proc_fs.h>
#include <linux/seq_file.h>
#include <linux/uaccess.h>
#include <linux/string.h>
#include <linux/stop_machine.h>
#include <linux/kallsyms.h>
#include <linux/sched.h>
#include <linux/version.h>
#include <linux/timekeeping.h>
#include <linux/cache.h>
#include <linux/preempt.h>

#include "hotpatch.h"

MODULE_LICENSE("MIT");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("Hotpatch generator - kernel self-repair via livepatch");
MODULE_VERSION(HOTPATCH_VERSION);

/* ================================================================
 * 参数
 * ================================================================ */

static unsigned int max_patches = 64;
module_param(max_patches, uint, 0644);
MODULE_PARM_DESC(max_patches, "最大补丁数");

static unsigned int max_hooks = 32;
module_param(max_hooks, uint, 0644);
MODULE_PARM_DESC(max_hooks, "最大监控钩子数");

static bool enable_patching = true;
module_param(enable_patching, bool, 0644);
MODULE_PARM_DESC(enable_patching, "启用指令修补 (关闭则仅框架)");

/* ================================================================
 * 数据结构
 * ================================================================ */

/* 原始指令备份 (x86_64 JMP rel32 = 5 字节) */
#define JMP_INSN_SIZE 5

struct patch_insns {
    u8 data[JMP_INSN_SIZE];
};

/* 补丁条目 */
struct hotpatch_entry {
    char                name[64];
    char                target_func[64];
    char                description[128];
    void               *target_addr;      /* 目标函数地址 */
    void               *patch_addr;       /* 补丁函数地址 */
    enum hotpatch_status status;
    u64                 created_ns;
    u32                 use_count;
    u32                 hit_count;
    int                 safety_ok;
    struct patch_insns  orig_insns;       /* 原始指令备份 */
    struct kprobe       monitor_kp;       /* 监控 kprobe */
    bool                monitor_active;
    struct list_head    list;
};

/* 监控钩子条目 */
struct hook_entry {
    char                func_name[64];
    struct kprobe       kp;
    u64                 call_count;
    u64                 error_count;
    int                (*detect_fn)(struct pt_regs *);
    bool                registered;
    struct list_head    list;
};

/* 全局状态 */
static struct {
    /* 补丁列表 */
    struct list_head    patches;
    unsigned int        patch_count;
    struct mutex        patch_mutex;

    /* 钩子列表 */
    struct list_head    hooks;
    unsigned int        hook_count;
    struct mutex        hook_mutex;

    /* 统计 */
    struct hotpatch_stats stats;

    /* 模块启动时间 */
    unsigned long       start_jiffies;

    /* /proc 条目 */
    struct proc_dir_entry *proc_dir;
    struct proc_dir_entry *proc_status;
    struct proc_dir_entry *proc_patches;
    struct proc_dir_entry *proc_hooks;
    struct proc_dir_entry *proc_config;

    bool initialized;
} g_hp;

/* ================================================================
 * 辅助函数
 * ================================================================ */

static const char *status_str(enum hotpatch_status s)
{
    switch (s) {
    case HOTPATCH_REGISTERED: return "registered";
    case HOTPATCH_APPLIED:    return "applied";
    case HOTPATCH_ROLLEDBACK: return "rolledback";
    case HOTPATCH_FAILED:     return "failed";
    default:                  return "unknown";
    }
}

/* ================================================================
 * 指令修补 (x86_64)
 * ================================================================ */

/*
 * 检查函数是否可修补:
 * 1. 函数地址有效
 * 2. 补丁地址有效
 * 3. 函数不等于补丁
 * 4. 函数有足够空间 (至少 5 字节)
 */
static int check_patch_safety(struct hotpatch_entry *entry)
{
    if (!entry->target_addr || !entry->patch_addr) {
        entry->safety_ok = 0;
        return -EINVAL;
    }

    if (entry->target_addr == entry->patch_addr) {
        entry->safety_ok = 0;
        return -EINVAL;
    }

    /* 检查目标函数前 5 字节是否都是可执行指令 */
    /* 简化: 不做完整反汇编, 只检查不是内核文本段边界 */
    unsigned long addr = (unsigned long)entry->target_addr;
    if (addr < (unsigned long)_stext || addr >= (unsigned long)_etext) {
        pr_warn("hotpatch: target %s (%px) not in kernel text\n",
                entry->target_func, entry->target_addr);
        entry->safety_ok = 0;
        return -EPERM;
    }

    entry->safety_ok = 1;
    return 0;
}

/*
 * stop_machine 回调: 执行实际修补
 * 在 stop_machine 上下文中，所有 CPU 都已停止
 */
struct patch_work {
    void  *target_addr;
    void  *patch_addr;
    u8    *orig_bytes;
    int    apply;  /* 1=apply, 0=rollback */
    int    result;
};

static int do_patch_cb(void *data)
{
    struct patch_work *pw = data;
    u8 jmp_code[JMP_INSN_SIZE];
    s32 offset;
    int i;

    if (pw->apply) {
        /* 构建 JMP rel32 指令 */
        jmp_code[0] = 0xE9;  /* JMP rel32 opcode */
        offset = (s32)((unsigned long)pw->patch_addr -
                       ((unsigned long)pw->target_addr + 5));
        memcpy(&jmp_code[1], &offset, 4);

        /* 备份原始指令 */
        memcpy(pw->orig_bytes, pw->target_addr, JMP_INSN_SIZE);

        /* 写入 JMP 指令 */
        memcpy(pw->target_addr, jmp_code, JMP_INSN_SIZE);
    } else {
        /* 恢复原始指令 */
        memcpy(pw->target_addr, pw->orig_bytes, JMP_INSN_SIZE);
    }

    /* 刷新指令缓存 (确保所有 CPU 执行新代码) */
    __flush_tlb_all();
    sync_core();

    pw->result = 0;
    return 0;
}

/* 应用补丁 (使用 stop_machine) */
static int apply_patch_safe(struct hotpatch_entry *entry)
{
    struct patch_work pw;
    int ret;

    if (!enable_patching) {
        pr_info("hotpatch: patching disabled, skipping apply\n");
        return 0;
    }

    if (!entry->safety_ok) {
        ret = check_patch_safety(entry);
        if (ret < 0)
            return ret;
    }

    pw.target_addr = entry->target_addr;
    pw.patch_addr = entry->patch_addr;
    pw.orig_bytes = entry->orig_insns.data;
    pw.apply = 1;
    pw.result = -EINVAL;

    /* 使用 stop_machine 安全地修改代码 */
    ret = stop_machine(do_patch_cb, &pw, NULL);
    if (ret < 0) {
        pr_err("hotpatch: stop_machine failed (%d)\n", ret);
        return ret;
    }

    ret = pw.result;
    if (ret == 0) {
        pr_info("hotpatch: applied patch '%s' -> %s (%px -> %px)\n",
                entry->name, entry->target_func,
                entry->target_addr, entry->patch_addr);
    }

    return ret;
}

/* 回滚补丁 (使用 stop_machine) */
static int rollback_patch_safe(struct hotpatch_entry *entry)
{
    struct patch_work pw;
    int ret;

    if (!enable_patching) {
        return 0;
    }

    pw.target_addr = entry->target_addr;
    pw.patch_addr = NULL;
    pw.orig_bytes = entry->orig_insns.data;
    pw.apply = 0;
    pw.result = -EINVAL;

    ret = stop_machine(do_patch_cb, &pw, NULL);
    if (ret < 0) {
        pr_err("hotpatch: stop_machine rollback failed (%d)\n", ret);
        return ret;
    }

    ret = pw.result;
    if (ret == 0) {
        pr_info("hotpatch: rolled back patch '%s' -> %s\n",
                entry->name, entry->target_func);
    }

    return ret;
}

/* ================================================================
 * 补丁管理
 * ================================================================ */

int hotpatch_register(const char *target_func, void *patch_func,
                      const char *description)
{
    struct hotpatch_entry *entry;
    int ret;

    if (!target_func || !patch_func)
        return -EINVAL;

    if (g_hp.patch_count >= max_patches)
        return -ENOSPC;

    entry = kzalloc(sizeof(*entry), GFP_KERNEL);
    if (!entry)
        return -ENOMEM;

    /* 生成名称 */
    snprintf(entry->name, sizeof(entry->name), "hp_%s_%llu",
             target_func, (u64)ktime_get_real_ns());
    strscpy(entry->target_func, target_func, sizeof(entry->target_func));
    if (description)
        strscpy(entry->description, description, sizeof(entry->description));
    else
        snprintf(entry->description, sizeof(entry->description),
                 "Patch for %s", target_func);

    entry->patch_addr = patch_func;
    entry->status = HOTPATCH_REGISTERED;
    entry->created_ns = ktime_get_real_ns();
    entry->safety_ok = 0;

    /* 查找目标函数地址 */
    entry->target_addr = (void *)kallsyms_lookup_name(target_func);
    if (!entry->target_addr) {
        pr_warn("hotpatch: function '%s' not found\n", target_func);
        kfree(entry);
        return -ENOENT;
    }

    /* 安全检查 */
    ret = check_patch_safety(entry);
    if (ret < 0) {
        pr_warn("hotpatch: safety check failed for '%s' (%d)\n",
                target_func, ret);
        /* 仍然注册，但标记为不安全 */
    }

    /* 保存原始指令 */
    memcpy(entry->orig_insns.data, entry->target_addr, JMP_INSN_SIZE);

    /* 加入列表 */
    mutex_lock(&g_hp.patch_mutex);
    list_add_tail(&entry->list, &g_hp.patches);
    g_hp.patch_count++;
    g_hp.stats.patches_total++;
    mutex_unlock(&g_hp.patch_mutex);

    pr_info("hotpatch: registered '%s' -> %s (%px)\n",
            entry->name, target_func, entry->target_addr);

    return 0;
}
EXPORT_SYMBOL_GPL(hotpatch_register);

int hotpatch_apply(const char *name)
{
    struct hotpatch_entry *entry = NULL;
    int ret = -ENOENT;

    if (!name)
        return -EINVAL;

    mutex_lock(&g_hp.patch_mutex);

    list_for_each_entry(entry, &g_hp.patches, list) {
        if (strcmp(entry->name, name) == 0) {
            if (entry->status == HOTPATCH_APPLIED) {
                ret = -EALREADY;
                break;
            }

            if (!entry->safety_ok) {
                ret = -EPERM;
                break;
            }

            ret = apply_patch_safe(entry);
            if (ret == 0) {
                entry->status = HOTPATCH_APPLIED;
                entry->use_count++;
                g_hp.stats.patches_applied++;
            } else {
                entry->status = HOTPATCH_FAILED;
                g_hp.stats.patches_failed++;
            }
            break;
        }
    }

    mutex_unlock(&g_hp.patch_mutex);
    return ret;
}
EXPORT_SYMBOL_GPL(hotpatch_apply);

int hotpatch_rollback(const char *name)
{
    struct hotpatch_entry *entry = NULL;
    int ret = -ENOENT;

    if (!name)
        return -EINVAL;

    mutex_lock(&g_hp.patch_mutex);

    list_for_each_entry(entry, &g_hp.patches, list) {
        if (strcmp(entry->name, name) == 0) {
            if (entry->status != HOTPATCH_APPLIED) {
                ret = -EALREADY;
                break;
            }

            ret = rollback_patch_safe(entry);
            if (ret == 0) {
                entry->status = HOTPATCH_ROLLEDBACK;
                g_hp.stats.patches_rolledback++;
            } else {
                entry->status = HOTPATCH_FAILED;
                g_hp.stats.patches_failed++;
            }
            break;
        }
    }

    mutex_unlock(&g_hp.patch_mutex);
    return ret;
}
EXPORT_SYMBOL_GPL(hotpatch_rollback);

int hotpatch_get_info(const char *name, struct hotpatch_info *info)
{
    struct hotpatch_entry *entry = NULL;
    int ret = -ENOENT;

    if (!name || !info)
        return -EINVAL;

    mutex_lock(&g_hp.patch_mutex);

    list_for_each_entry(entry, &g_hp.patches, list) {
        if (strcmp(entry->name, name) == 0) {
            strscpy(info->name, entry->name, sizeof(info->name));
            strscpy(info->target_func, entry->target_func,
                    sizeof(info->target_func));
            info->status = entry->status;
            info->created_ns = entry->created_ns;
            info->use_count = entry->use_count;
            info->hit_count = entry->hit_count;
            info->safety_ok = entry->safety_ok;
            ret = 0;
            break;
        }
    }

    mutex_unlock(&g_hp.patch_mutex);
    return ret;
}
EXPORT_SYMBOL_GPL(hotpatch_get_info);

void hotpatch_get_stats(struct hotpatch_stats *stats)
{
    if (stats)
        *stats = g_hp.stats;
}
EXPORT_SYMBOL_GPL(hotpatch_get_stats);

/* ================================================================
 * 监控钩子 (kprobe)
 * ================================================================ */

static int hook_handler_pre(struct kprobe *p, struct pt_regs *regs)
{
    struct hook_entry *entry = container_of(p, struct hook_entry, kp);

    entry->call_count++;
    g_hp.stats.total_hook_calls++;

    if (entry->detect_fn) {
        if (entry->detect_fn(regs)) {
            entry->error_count++;
            g_hp.stats.total_hook_errors++;
        }
    }

    return 0;
}

int hotpatch_register_hook(const char *func_name,
                           int (*detect)(struct pt_regs *))
{
    struct hook_entry *entry;
    int ret;

    if (!func_name)
        return -EINVAL;

    if (g_hp.hook_count >= max_hooks)
        return -ENOSPC;

    entry = kzalloc(sizeof(*entry), GFP_KERNEL);
    if (!entry)
        return -ENOMEM;

    strscpy(entry->func_name, func_name, sizeof(entry->func_name));
    entry->detect_fn = detect;
    entry->kp.symbol_name = func_name;
    entry->kp.pre_handler = hook_handler_pre;

    ret = register_kprobe(&entry->kp);
    if (ret < 0) {
        pr_err("hotpatch: failed to register kprobe for '%s' (%d)\n",
               func_name, ret);
        kfree(entry);
        return ret;
    }

    entry->registered = true;

    mutex_lock(&g_hp.hook_mutex);
    list_add_tail(&entry->list, &g_hp.hooks);
    g_hp.hook_count++;
    g_hp.stats.hooks_total++;
    mutex_unlock(&g_hp.hook_mutex);

    pr_info("hotpatch: monitoring '%s' via kprobe\n", func_name);
    return 0;
}
EXPORT_SYMBOL_GPL(hotpatch_register_hook);

int hotpatch_unregister_hook(const char *func_name)
{
    struct hook_entry *entry;
    int ret = -ENOENT;

    if (!func_name)
        return -EINVAL;

    mutex_lock(&g_hp.hook_mutex);

    list_for_each_entry(entry, &g_hp.hooks, list) {
        if (strcmp(entry->func_name, func_name) == 0) {
            unregister_kprobe(&entry->kp);
            entry->registered = false;
            list_del(&entry->list);
            g_hp.hook_count--;
            kfree(entry);
            ret = 0;
            break;
        }
    }

    mutex_unlock(&g_hp.hook_mutex);
    return ret;
}
EXPORT_SYMBOL_GPL(hotpatch_unregister_hook);

/* ================================================================
 * 自动补丁生成 (框架)
 * ================================================================ */

int hotpatch_autogen(const char *fault_func, const char *context)
{
    if (!fault_func)
        return -EINVAL;

    pr_info("hotpatch: auto-generate patch for '%s'\n", fault_func);
    pr_info("hotpatch: context: %s\n", context ?: "none");

    /*
     * 自动生成补丁的完整实现需要:
     * 1. 从 fault_func 提取函数原型
     * 2. 分析 context 中的错误信息
     * 3. 生成修复代码 (如: 空指针检查、边界检查)
     * 4. 编译为内核模块
     * 5. 动态加载
     *
     * 当前实现: 框架占位
     */
    pr_info("hotpatch: auto-patch generation requires user-space toolchain\n");

    return 0;
}
EXPORT_SYMBOL_GPL(hotpatch_autogen);

/* ================================================================
 * /proc/ai-hotpatch/status
 * ================================================================ */

static int proc_status_show(struct seq_file *m, void *v)
{
    u64 uptime = (jiffies - g_hp.start_jiffies) / HZ;

    seq_printf(m, "Ainos Hotpatch v%s\n", HOTPATCH_VERSION);
    seq_printf(m, "%-30s = %llu sec\n", "Uptime", uptime);
    seq_printf(m, "%-30s = %s\n", "Patching", enable_patching ? "enabled" : "disabled");
    seq_printf(m, "\n");
    seq_printf(m, "%-30s = %u\n", "Patches Total", g_hp.stats.patches_total);
    seq_printf(m, "%-30s = %u\n", "Applied", g_hp.stats.patches_applied);
    seq_printf(m, "%-30s = %u\n", "Rolled Back", g_hp.stats.patches_rolledback);
    seq_printf(m, "%-30s = %u\n", "Failed", g_hp.stats.patches_failed);
    seq_printf(m, "%-30s = %u\n", "Hooks Total", g_hp.stats.hooks_total);
    seq_printf(m, "%-30s = %llu\n", "Hook Calls", g_hp.stats.total_hook_calls);
    seq_printf(m, "%-30s = %llu\n", "Hook Errors", g_hp.stats.total_hook_errors);
    seq_printf(m, "%-30s = %u\n", "Safety Failures", g_hp.stats.safety_failures);

    return 0;
}

static int proc_status_open(struct inode *inode, struct file *file)
{
    return single_open(file, proc_status_show, NULL);
}

static const struct proc_ops proc_status_fops = {
    .proc_open    = proc_status_open,
    .proc_read    = seq_read,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

/* ================================================================
 * /proc/ai-hotpatch/patches
 * ================================================================ */

static int proc_patches_show(struct seq_file *m, void *v)
{
    struct hotpatch_entry *entry;

    mutex_lock(&g_hp.patch_mutex);

    if (g_hp.patch_count == 0) {
        seq_puts(m, "No patches registered.\n");
        mutex_unlock(&g_hp.patch_mutex);
        return 0;
    }

    seq_printf(m, "%-32s %-24s %-12s %6s %5s %s\n",
               "Name", "Target", "Status", "Uses", "Safe", "Description");

    list_for_each_entry(entry, &g_hp.patches, list) {
        seq_printf(m, "%-32s %-24s %-12s %6u %5s %s\n",
                   entry->name,
                   entry->target_func,
                   status_str(entry->status),
                   entry->use_count,
                   entry->safety_ok ? "yes" : "no",
                   entry->description);
    }

    mutex_unlock(&g_hp.patch_mutex);
    return 0;
}

static int proc_patches_open(struct inode *inode, struct file *file)
{
    return single_open(file, proc_patches_show, NULL);
}

static const struct proc_ops proc_patches_fops = {
    .proc_open    = proc_patches_open,
    .proc_read    = seq_read,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

/* ================================================================
 * /proc/ai-hotpatch/hooks
 * ================================================================ */

static int proc_hooks_show(struct seq_file *m, void *v)
{
    struct hook_entry *entry;

    mutex_lock(&g_hp.hook_mutex);

    if (g_hp.hook_count == 0) {
        seq_puts(m, "No hooks registered.\n");
        mutex_unlock(&g_hp.hook_mutex);
        return 0;
    }

    seq_printf(m, "%-32s %12s %12s %8s\n",
               "Function", "Calls", "Errors", "Status");

    list_for_each_entry(entry, &g_hp.hooks, list) {
        seq_printf(m, "%-32s %12llu %12llu %8s\n",
                   entry->func_name,
                   entry->call_count,
                   entry->error_count,
                   entry->registered ? "active" : "inactive");
    }

    mutex_unlock(&g_hp.hook_mutex);
    return 0;
}

static int proc_hooks_open(struct inode *inode, struct file *file)
{
    return single_open(file, proc_hooks_show, NULL);
}

static const struct proc_ops proc_hooks_fops = {
    .proc_open    = proc_hooks_open,
    .proc_read    = seq_read,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

/* ================================================================
 * /proc/ai-hotpatch/config
 * ================================================================ */

static int proc_config_show(struct seq_file *m, void *v)
{
    seq_printf(m, "%-24s = %u\n", "max_patches", max_patches);
    seq_printf(m, "%-24s = %u\n", "max_hooks", max_hooks);
    seq_printf(m, "%-24s = %s\n", "enable_patching",
               enable_patching ? "yes" : "no");
    return 0;
}

static int proc_config_open(struct inode *inode, struct file *file)
{
    return single_open(file, proc_config_show, NULL);
}

static const struct proc_ops proc_config_fops = {
    .proc_open    = proc_config_open,
    .proc_read    = seq_read,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

/* ================================================================
 * 初始化
 * ================================================================ */

static int __init hotpatch_init(void)
{
    pr_info("hotpatch: Ainos Hotpatch v%s initializing...\n", HOTPATCH_VERSION);

    memset(&g_hp, 0, sizeof(g_hp));
    INIT_LIST_HEAD(&g_hp.patches);
    INIT_LIST_HEAD(&g_hp.hooks);
    mutex_init(&g_hp.patch_mutex);
    mutex_init(&g_hp.hook_mutex);
    g_hp.start_jiffies = jiffies;

    /* 创建 /proc/ai-hotpatch */
    g_hp.proc_dir = proc_mkdir("ai-hotpatch", NULL);
    if (!g_hp.proc_dir) {
        pr_err("hotpatch: failed to create /proc/ai-hotpatch\n");
        return -ENOMEM;
    }

    g_hp.proc_status = proc_create("status", 0444, g_hp.proc_dir,
                                    &proc_status_fops);
    g_hp.proc_patches = proc_create("patches", 0444, g_hp.proc_dir,
                                     &proc_patches_fops);
    g_hp.proc_hooks = proc_create("hooks", 0444, g_hp.proc_dir,
                                   &proc_hooks_fops);
    g_hp.proc_config = proc_create("config", 0444, g_hp.proc_dir,
                                    &proc_config_fops);

    if (!g_hp.proc_status || !g_hp.proc_patches ||
        !g_hp.proc_hooks || !g_hp.proc_config) {
        pr_err("hotpatch: failed to create proc files\n");
        if (g_hp.proc_config)  remove_proc_entry("config", g_hp.proc_dir);
        if (g_hp.proc_hooks)   remove_proc_entry("hooks", g_hp.proc_dir);
        if (g_hp.proc_patches) remove_proc_entry("patches", g_hp.proc_dir);
        if (g_hp.proc_status)  remove_proc_entry("status", g_hp.proc_dir);
        if (g_hp.proc_dir)     remove_proc_entry("ai-hotpatch", NULL);
        return -ENOMEM;
    }

    g_hp.initialized = true;

    pr_info("hotpatch: Ainos Hotpatch v%s initialized\n", HOTPATCH_VERSION);
    pr_info("hotpatch: /proc/ai-hotpatch/{status,patches,hooks,config}\n");
    pr_info("hotpatch: max_patches=%u, max_hooks=%u, patching=%s\n",
            max_patches, max_hooks, enable_patching ? "enabled" : "disabled");

    return 0;
}

/* ================================================================
 * 清理
 * ================================================================ */

static void __exit hotpatch_exit(void)
{
    struct hotpatch_entry *hp_entry, *hp_tmp;
    struct hook_entry *hk_entry, *hk_tmp;

    if (!g_hp.initialized)
        return;

    pr_info("hotpatch: shutting down...\n");

    g_hp.initialized = false;

    /* 回滚所有补丁 */
    mutex_lock(&g_hp.patch_mutex);
    list_for_each_entry_safe(hp_entry, hp_tmp, &g_hp.patches, list) {
        if (hp_entry->status == HOTPATCH_APPLIED) {
            rollback_patch_safe(hp_entry);
        }
        list_del(&hp_entry->list);
        g_hp.patch_count--;
        kfree(hp_entry);
    }
    mutex_unlock(&g_hp.patch_mutex);

    /* 卸载所有钩子 */
    mutex_lock(&g_hp.hook_mutex);
    list_for_each_entry_safe(hk_entry, hk_tmp, &g_hp.hooks, list) {
        if (hk_entry->registered)
            unregister_kprobe(&hk_entry->kp);
        list_del(&hk_entry->list);
        g_hp.hook_count--;
        kfree(hk_entry);
    }
    mutex_unlock(&g_hp.hook_mutex);

    /* 清理 proc 文件 */
    if (g_hp.proc_config)  remove_proc_entry("config", g_hp.proc_dir);
    if (g_hp.proc_hooks)   remove_proc_entry("hooks", g_hp.proc_dir);
    if (g_hp.proc_patches) remove_proc_entry("patches", g_hp.proc_dir);
    if (g_hp.proc_status)  remove_proc_entry("status", g_hp.proc_dir);
    if (g_hp.proc_dir)     remove_proc_entry("ai-hotpatch", NULL);

    pr_info("hotpatch: unloaded (patches=%u, hooks=%u)\n",
            g_hp.stats.patches_total, g_hp.stats.hooks_total);
}

module_init(hotpatch_init);
module_exit(hotpatch_exit);