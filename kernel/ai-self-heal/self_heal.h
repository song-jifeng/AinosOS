#ifndef AINOS_SELF_HEAL_H
#define AINOS_SELF_HEAL_H

#include <linux/types.h>

/* 自愈统计 */
struct self_heal_stats {
    int attempts;
    int successes;
    int failures;
    unsigned long last_panic_jiffies;
};

/* 导出函数 */
struct self_heal_stats *self_heal_get_stats(void);
int self_heal_force_recovery(void);

#endif /* AINOS_SELF_HEAL_H */