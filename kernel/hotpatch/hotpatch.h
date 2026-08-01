#ifndef AINOS_HOTPATCH_H
#define AINOS_HOTPATCH_H

#include <linux/types.h>

/* 热补丁接口 */

/* 注册热补丁 */
int hotpatch_register(const char *target_func, void *patch_func);

/* 应用补丁 */
int hotpatch_apply(const char *name);

/* 回滚补丁 */
int hotpatch_rollback(const char *name);

/* 注册异常检测钩子 */
int hotpatch_register_hook(const char *func_name, int (*detect)(struct kprobe *, struct pt_regs *));

/* 自动生成补丁 */
int hotpatch_autogen(const char *fault_func);

/* 列出补丁 */
int hotpatch_list(char *buf, size_t size);

/* 补丁信息 */
struct hotpatch_info {
    char name[64];
    char target_func[64];
    int applied;
    unsigned long created;
    int use_count;
};

#endif /* AINOS_HOTPATCH_H */