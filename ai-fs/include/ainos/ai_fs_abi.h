// SPDX-License-Identifier: GPL-2.0
/*
 * Ainos OS - AI 文件系统 ABI 定义
 * ==========================================
 * 定义 AI-FS 相关的系统调用和数据结构
 */

#ifndef _AINOS_AI_FS_ABI_H
#define _AINOS_AI_FS_ABI_H

#include <linux/types.h>

#ifdef __KERNEL__
#include <linux/uaccess.h>
#else
#include <stdint.h>
#endif

/* ============================================
 * AI-FS 系统调用号
 * ============================================ */
#define __NR_ai_fs_search       460
#define __NR_ai_fs_index        461
#define __NR_ai_fs_watch        462
#define __NR_ai_fs_get_tags     463
#define __NR_ai_fs_classify     464

/* ============================================
 * 搜索结果
 * ============================================ */
#define AI_FS_PATH_MAX    512
#define AI_FS_SNIPPET_MAX 256
#define AI_FS_TAG_MAX      32
#define AI_FS_MAX_RESULTS 128

struct ai_fs_search_result {
    char path[AI_FS_PATH_MAX];         /* 文件路径 */
    char snippet[AI_FS_SNIPPET_MAX];   /* 匹配片段 */
    float score;                        /* 相关度 (0.0 - 1.0) */
    uint64_t file_size;                 /* 文件大小 */
    uint64_t modified_at;               /* 修改时间戳 */
    char content_type[64];              /* MIME 类型 */
    char tags[AI_FS_TAG_MAX][64];      /* AI 标签 */
    uint32_t tag_count;                 /* 标签数量 */
};

/* ============================================
 * 搜索请求
 * ============================================ */
struct ai_fs_search_request {
    char query[AI_FS_PATH_MAX];        /* 自然语言查询 */
    char directory[AI_FS_PATH_MAX];    /* 搜索目录 (可选) */
    uint32_t max_results;               /* 最大结果数 */
    float min_score;                    /* 最低相关度阈值 */
    uint64_t filter_after;              /* 仅返回此时间之后的文件 */
    uint32_t flags;                     /* 搜索标志 */
};

/* 搜索标志 */
#define AI_FS_SEARCH_RECURSIVE   (1 << 0)  /* 递归搜索子目录 */
#define AI_FS_SEARCH_CONTENT_ONLY (1 << 1) /* 仅搜索文件内容 */
#define AI_FS_SEARCH_FILENAME     (1 << 2) /* 也搜索文件名 */
#define AI_FS_SEARCH_FUZZY        (1 << 3) /* 模糊匹配 */

/* ============================================
 * 索引状态
 * ============================================ */
struct ai_fs_index_status {
    uint64_t files_indexed;             /* 已索引文件数 */
    uint64_t files_pending;             /* 等待索引文件数 */
    uint64_t total_size_bytes;          /* 索引总大小 */
    uint64_t index_size_bytes;          /* 索引文件大小 */
    uint32_t active_watches;            /* 活跃监控数 */
    uint8_t  is_indexing;               /* 是否正在索引 */
    uint8_t  auto_index;                /* 是否自动索引 */
};

/* ============================================
 * 系统调用声明
 * ============================================ */
asmlinkage long sys_ai_fs_search(const struct ai_fs_search_request __user *req,
                                  struct ai_fs_search_result __user *results,
                                  uint32_t *result_count);

asmlinkage long sys_ai_fs_index(const char __user *path, uint32_t flags);

asmlinkage long sys_ai_fs_watch(const char __user *path, uint32_t flags);

asmlinkage long sys_ai_fs_get_tags(const char __user *path,
                                    char __user *tags,
                                    uint32_t *count);

asmlinkage long sys_ai_fs_classify(const char __user *path,
                                    char __user *category,
                                    size_t max_len);

#endif /* _AINOS_AI_FS_ABI_H */