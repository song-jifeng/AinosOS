#ifndef AINOS_AI_READAHEAD_H
#define AINOS_AI_READAHEAD_H

#include <linux/types.h>
#include <linux/fs.h>

/* AI readahead 接口 */

/* 预测下一个读取位置 */
unsigned long ai_readahead_predict(const char *filename, unsigned long current_offset);

/* 通知缓存命中 */
void ai_readahead_cache_hit(const char *filename);

/* 获取统计 */
int ai_readahead_stats(char *buf, size_t size);

/* 清除跟踪数据 */
void ai_readahead_clear(void);

/* 统计结构 */
struct ai_readahead_stats {
    int tracked_files;
    unsigned long total_predictions;
    unsigned long correct_predictions;
    int avg_confidence;
};

#endif /* AINOS_AI_READAHEAD_H */