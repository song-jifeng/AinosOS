#ifndef AINOS_AI_TMPFS_H
#define AINOS_AI_TMPFS_H

#include <linux/types.h>
#include <linux/fs.h>

#define AI_TMPFS_VERSION "2.0.0"
#define AI_TMPFS_MAGIC    0x41494D50  /* "AIMP" */

/* ================================================================
 * 配置
 * ================================================================ */

/* 热数据阈值 */
#define AI_TMPFS_HOT_ACCESS_MIN    5    /* 最少访问次数 */
#define AI_TMPFS_HOT_FREQ_MIN      10   /* 每分钟最少访问次数 */
#define AI_TMPFS_WARM_ACCESS_MIN   2    /* 温数据最少访问次数 */

/* 文件大小限制 */
#define AI_TMPFS_MAX_FILE_SIZE     (16UL * 1024 * 1024)  /* 16MB */
#define AI_TMPFS_MAX_FILES         4096
#define AI_TMPFS_MAX_NAME_LEN      256

/* 冷数据清理间隔 (秒) */
#define AI_TMPFS_CLEAN_INTERVAL    30

/* ================================================================
 * 统计
 * ================================================================ */

struct ai_tmpfs_stats {
    __u64  files_total;          /* 总文件数 */
    __u64  files_hot;            /* 热文件数 */
    __u64  files_warm;           /* 温文件数 */
    __u64  files_cold;           /* 冷文件数 */
    __u64  bytes_total;          /* 总字节数 */
    __u64  bytes_hot;            /* 热数据字节数 */
    __u64  bytes_warm;           /* 温数据字节数 */
    __u64  bytes_cold;           /* 冷数据字节数 */
    __u64  reads_total;          /* 总读取次数 */
    __u64  writes_total;         /* 总写入次数 */
    __u64  evictions_total;      /* 总驱逐次数 */
    __u64  evictions_hot;        /* 热数据驱逐次数 (异常) */
    __u64  hits_hot;             /* 热数据命中 */
    __u64  hits_cold;            /* 冷数据命中 (需要 promotion) */
    __u64  shrinker_calls;       /* shrinker 调用次数 */
    __u64  uptime_seconds;       /* 运行时间 */
};

#endif /* AINOS_AI_TMPFS_H */