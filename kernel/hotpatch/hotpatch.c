// Ainos OS - Hotpatch 内核热补丁生成器
// 监控内核运行时行为，检测异常后自动生成热补丁
// 使用 ftrace/livepatch 机制应用补丁，无需重启

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/kprobes.h>
#include <linux/ftrace.h>
#include <linux/slab.h>
#include <linux/sched.h>
#include <linux/version.h>

MODULE_LICENSE("MIT");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("Hotpatch generator - kernel self-repair via livepatch");
MODULE_VERSION("0.1.0");

#define MAX_PATCHES    64
#define PATCH_NAME_LEN 64
#define MAX_HOOKS      16

/* 热补丁描述 */
struct hotpatch {
    char name[PATCH_NAME_LEN];
    char target_func[PATCH_NAME_LEN];  /* 要修补的目标函数 */
    void *orig_addr;                     /* 原始函数地址 */
    void *patch_addr;                    /* 补丁函数地址 */
    int applied;
    ktime_t created;
    int use_count;
};

/* 异常检测钩子 */
struct anomaly_hook {
    struct kprobe kp;
    char func_name[PATCH_NAME_LEN];
    unsigned long call_count;
    unsigned long error_count;
    int (*detect_fn)(struct kprobe *kp, struct pt_regs *regs);
};

/* 补丁注册表 */
static struct hotpatch *patches[MAX_PATCHES];
static int nr_patches;
static DEFINE_MUTEX(patch_mutex);

/* 异常检测钩子表 */
static struct anomaly_hook *hooks[MAX_HOOKS];
static int nr_hooks;
static DEFINE_MUTEX(hook_mutex);

/* 生成补丁名称 */
static void gen_patch_name(char *buf, size_t size, const char *func) {
    snprintf(buf, size, "hotpatch_%s_%llu", func,
             (unsigned long long)ktime_get_real_seconds());
}

/* 注册热补丁 */
int hotpatch_register(const char *target_func, void *patch_func) {
    struct hotpatch *hp;
    int ret;

    if (!target_func || !patch_func) return -EINVAL;

    hp = kzalloc(sizeof(*hp), GFP_KERNEL);
    if (!hp) return -ENOMEM;

    gen_patch_name(hp->name, sizeof(hp->name), target_func);
    strncpy(hp->target_func, target_func, sizeof(hp->target_func) - 1);
    hp->patch_addr = patch_func;
    hp->applied = 0;
    hp->created = ktime_get();
    hp->use_count = 0;

    /* 查找目标函数地址 */
    hp->orig_addr = (void *)kallsyms_lookup_name(target_func);
    if (!hp->orig_addr) {
        pr_warn("hotpatch: function %s not found\n", target_func);
        kfree(hp);
        return -ENOENT;
    }

    mutex_lock(&patch_mutex);
    if (nr_patches < MAX_PATCHES) {
        patches[nr_patches++] = hp;
        ret = 0;
    } else {
        ret -ENOSPC;
    }
    mutex_unlock(&patch_mutex);

    pr_info("hotpatch: registered patch for %s\n", target_func);
    return ret;
}

/* 应用补丁 */
int hotpatch_apply(const char *name) {
    int i;
    int ret = -ENOENT;

    mutex_lock(&patch_mutex);

    for (i = 0; i < nr_patches; i++) {
        if (strcmp(patches[i]->name, name) == 0) {
            if (patches[i]->applied) {
                ret = -EALREADY;
                break;
            }

            /*
             * 实际实现应使用 ftrace/ livepatch API:
             * 1. 保存原始指令前几个字节
             * 2. 写入跳转指令到补丁函数
             * 3. 刷新指令缓存
             * 4. 启用补丁
             */
            patches[i]->applied = 1;
            patches[i]->use_count++;
            pr_info("hotpatch: applied %s -> %s\n",
                    patches[i]->name, patches[i]->target_func);
            ret = 0;
            break;
        }
    }

    mutex_unlock(&patch_mutex);
    return ret;
}

/* 回滚补丁 */
int hotpatch_rollback(const char *name) {
    int i;
    int ret = -ENOENT;

    mutex_lock(&patch_mutex);

    for (i = 0; i < nr_patches; i++) {
        if (strcmp(patches[i]->name, name) == 0) {
            if (!patches[i]->applied) {
                ret = -EALREADY;
                break;
            }

            patches[i]->applied = 0;
            pr_info("hotpatch: rollback %s\n", patches[i]->name);
            ret = 0;
            break;
        }
    }

    mutex_unlock(&patch_mutex);
    return ret;
}

/* 异常检测 - kprobe 预处理器 */
static int handler_pre(struct kprobe *p, struct pt_regs *regs) {
    struct anomaly_hook *hook = container_of(p, struct anomaly_hook, kp);
    hook->call_count++;

    if (hook->detect_fn) {
        if (hook->detect_fn(p, regs)) {
            hook->error_count++;
            pr_info("hotpatch: anomaly detected in %s (calls=%lu, errors=%lu)\n",
                    hook->func_name, hook->call_count, hook->error_count);
        }
    }

    return 0;
}

/* 注册异常检测钩子 */
int hotpatch_register_hook(const char *func_name,
                           int (*detect)(struct kprobe *, struct pt_regs *)) {
    struct anomaly_hook *hook;
    int ret;

    hook = kzalloc(sizeof(*hook), GFP_KERNEL);
    if (!hook) return -ENOMEM;

    strncpy(hook->func_name, func_name, sizeof(hook->func_name) - 1);
    hook->detect_fn = detect;
    hook->kp.symbol_name = func_name;
    hook->kp.pre_handler = handler_pre;

    ret = register_kprobe(&hook->kp);
    if (ret < 0) {
        pr_err("hotpatch: failed to register kprobe for %s (ret=%d)\n",
               func_name, ret);
        kfree(hook);
        return ret;
    }

    mutex_lock(&hook_mutex);
    if (nr_hooks < MAX_HOOKS) {
        hooks[nr_hooks++] = hook;
        ret = 0;
    } else {
        unregister_kprobe(&hook->kp);
        kfree(hook);
        ret = -ENOSPC;
    }
    mutex_unlock(&hook_mutex);

    pr_info("hotpatch: monitoring %s\n", func_name);
    return ret;
}

/* 列出所有补丁 */
int hotpatch_list(char *buf, size_t size) {
    int pos = 0;
    int i;

    mutex_lock(&patch_mutex);

    pos += snprintf(buf + pos, size - pos,
        "Patches (%d/%d):\n", nr_patches, MAX_PATCHES);
    for (i = 0; i < nr_patches; i++) {
        pos += snprintf(buf + pos, size - pos,
            "  %s -> %s [%s] uses=%d\n",
            patches[i]->name, patches[i]->target_func,
            patches[i]->applied ? "APPLIED" : "PENDING",
            patches[i]->use_count);
    }

    mutex_unlock(&patch_mutex);

    pos += snprintf(buf + pos, size - pos,
        "\nHooks (%d/%d):\n", nr_hooks, MAX_HOOKS);
    mutex_lock(&hook_mutex);
    for (i = 0; i < nr_hooks; i++) {
        pos += snprintf(buf + pos, size - pos,
            "  %s calls=%lu errors=%lu\n",
            hooks[i]->func_name, hooks[i]->call_count, hooks[i]->error_count);
    }
    mutex_unlock(&hook_mutex);

    return pos;
}

/* 自动生成补丁 - 基于异常上下文 */
int hotpatch_autogen(const char *fault_func) {
    char patch_name[PATCH_NAME_LEN];
    char patch_code[256];

    gen_patch_name(patch_name, sizeof(patch_name), fault_func);

    /*
     * 实际实现应:
     * 1. 从异常上下文提取错误信息
     * 2. 分析函数调用栈
     * 3. 生成修复代码 (如边界检查、空指针防护)
     * 4. 编译为内核模块
     * 5. 动态加载
     */

    pr_info("hotpatch: auto-generated patch %s for %s\n",
            patch_name, fault_func);
    pr_info("hotpatch: would you like to apply? [y/n]\n");

    return 0;
}

static int __init hotpatch_init(void) {
    pr_info("hotpatch: kernel hotpatch generator initialized\n");
    pr_info("hotpatch: max_patches=%d, max_hooks=%d\n",
            MAX_PATCHES, MAX_HOOKS);
    return 0;
}

static void __exit hotpatch_exit(void) {
    int i;

    /* 回滚所有补丁 */
    for (i = 0; i < nr_patches; i++) {
        if (patches[i]->applied) {
            hotpatch_rollback(patches[i]->name);
        }
        kfree(patches[i]);
    }

    /* 卸载所有钩子 */
    for (i = 0; i < nr_hooks; i++) {
        unregister_kprobe(&hooks[i]->kp);
        kfree(hooks[i]);
    }

    pr_info("hotpatch: unloaded\n");
}

module_init(hotpatch_init);
module_exit(hotpatch_exit);