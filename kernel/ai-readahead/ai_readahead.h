// SPDX-License-Identifier: GPL-2.0
#ifndef AINOS_AI_READAHEAD_H
#define AINOS_AI_READAHEAD_H

#include <linux/types.h>

#define AI_READAHEAD_VERSION "2.0.0"

/* 预测模型 */
enum ai_ra_model {
    AI_RA_MODEL_SEQUENTIAL = 0,  /* 顺序访问 */
    AI_RA_MODEL_STRIDED    = 1,  /* 固定步长 */
    AI_RA_MODEL_RANDOM     = 2,  /* 随机访问 */
    AI_RA_MODEL_SUBPAGE    = 3,  /* 子页面访问 */
    AI_RA_MODEL_UNKNOWN    = 4,  /* 未知模式 */
};

/* 预测结果 */
struct ai_ra_prediction {
    unsigned long       predicted_offset;   /* 预测的下一个偏移 (页号) */
    unsigned int        confidence;          /* 置信度 0-100 */
    enum ai_ra_model    model;               /* 使用的预测模型 */
    unsigned int        suggested_window;    /* 建议的预读窗口 (页数) */
};

/* 文件访问模式 */
struct ai_ra_pattern {
    unsigned long       offsets[8];          /* 最近 8 次访问偏移 */
    unsigned int        count;               /* 有效偏移数 */
    unsigned long       stride;              /* 检测到的步长 (0=未知) */
    unsigned int        stride_confidence;   /* 步长置信度 */
    enum ai_ra_model    model;               /* 当前模式 */
    unsigned int        sequential_count;    /* 连续顺序计数 */
    unsigned int        random_count;        /* 随机访问计数 */
};

/* 文件跟踪统计 */
struct ai_ra_file_stats {
    char                name[64];
    __u64               total_accesses;
    __u64               sequential_accesses;
    __u64               random_accesses;
    __u64               correct_predictions;
    __u64               total_predictions;
    unsigned int        current_confidence;
    enum ai_ra_model    current_model;
    unsigned int        suggested_window;
};

/* 全局统计 */
struct ai_ra_global_stats {
    __u64               total_predictions;
    __u64               correct_predictions;
    __u64               false_predictions;
    __u64               sequential_detected;
    __u64               strided_detected;
    __u64               random_detected;
    unsigned int        tracked_files;
    unsigned int        avg_confidence;
    unsigned int        avg_window;
};

/* ================================================================
 * 导出函数
 * ================================================================ */

#ifdef __KERNEL__

/* 记录访问并预测下一次 */
struct ai_ra_prediction ai_readahead_record(const char *filename,
                                             unsigned long offset);

/* 通知预测正确 (外部确认) */
void ai_readahead_confirm(const char *filename, unsigned long offset);

/* 通知预测错误 (负确认, 降低置信度) */
void ai_readahead_confirm_negative(const char *filename, unsigned long offset);

/* 批量记录访问 */
void ai_readahead_record_batch(const char *filename,
                                unsigned long *offsets, unsigned int count);

/* 清除指定文件的跟踪 */
void ai_readahead_clear_file(const char *filename);

/* 清除所有跟踪 */
void ai_readahead_clear_all(void);

/* 获取文件统计 */
int ai_readahead_get_stats(const char *filename,
                            struct ai_ra_file_stats *stats);

/* 获取全局统计 */
void ai_readahead_get_global(struct ai_ra_global_stats *stats);

#endif /* __KERNEL__ */

#endif /* AINOS_AI_READAHEAD_H */