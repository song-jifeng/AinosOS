// SPDX-License-Identifier: GPL-2.0
#ifndef AINOS_HOTPATCH_H
#define AINOS_HOTPATCH_H

#include <linux/types.h>

#define HOTPATCH_VERSION "2.0.0"

/* 补丁状态 */
enum hotpatch_status {
    HOTPATCH_REGISTERED = 0,
    HOTPATCH_APPLIED    = 1,
    HOTPATCH_ROLLEDBACK = 2,
    HOTPATCH_FAILED     = 3,
};

/* 补丁信息 */
struct hotpatch_info {
    char   name[64];
    char   target_func[64];
    __u32  status;           /* enum hotpatch_status */
    __u64  created_ns;
    __u32  use_count;
    __u32  hit_count;        /* 补丁被触发次数 */
    int    safety_ok;        /* 安全检查是否通过 */
};

/* 监控钩子信息 */
struct hotpatch_hook_info {
    char   func_name[64];
    __u64  call_count;
    __u64  error_count;
    int    registered;
};

/* 统计 */
struct hotpatch_stats {
    __u32  patches_total;
    __u32  patches_applied;
    __u32  patches_rolledback;
    __u32  patches_failed;
    __u32  hooks_total;
    __u64  total_hook_calls;
    __u64  total_hook_errors;
    __u32  safety_failures;
};

/* ================================================================
 * 导出函数
 * ================================================================ */

#ifdef __KERNEL__

/* 注册热补丁 */
int hotpatch_register(const char *target_func, void *patch_func,
                      const char *description);

/* 应用补丁 */
int hotpatch_apply(const char *name);

/* 回滚补丁 */
int hotpatch_rollback(const char *name);

/* 注册监控钩子 */
int hotpatch_register_hook(const char *func_name,
                           int (*detect)(struct pt_regs *));

/* 取消注册钩子 */
int hotpatch_unregister_hook(const char *func_name);

/* 获取补丁信息 */
int hotpatch_get_info(const char *name, struct hotpatch_info *info);

/* 获取统计 */
void hotpatch_get_stats(struct hotpatch_stats *stats);

/* 自动生成补丁 (框架) */
int hotpatch_autogen(const char *fault_func, const char *context);

#endif /* __KERNEL__ */

#endif /* AINOS_HOTPATCH_H */