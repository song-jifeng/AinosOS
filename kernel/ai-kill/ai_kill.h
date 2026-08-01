#ifndef AINOS_AI_KILL_H
#define AINOS_AI_KILL_H

#include <linux/types.h>

/* AI KILL 配置 */
struct ai_kill_config {
    int threshold_kill;
    int threshold_term;
    int scan_interval_ms;
    int enabled;
};

/* 进程评分 */
struct ai_kill_score {
    pid_t pid;
    char comm[64];
    int cpu_score;
    int mem_score;
    int io_score;
    int total_score;
};

/* 导出函数 */
int ai_kill_get_score(pid_t pid, struct ai_kill_score *score);
int ai_kill_set_config(const struct ai_kill_config *cfg);
void ai_kill_get_config(struct ai_kill_config *cfg);

#endif /* AINOS_AI_KILL_H */