// SPDX-License-Identifier: GPL-2.0
#ifndef AINOS_PROC_AI_H
#define AINOS_PROC_AI_H

#include <linux/types.h>
#include <linux/ioctl.h>

#define PROC_AI_VERSION "1.0.0"

/* ================================================================
 * IOCTL 命令 (/dev/ainos-proc)
 * ================================================================ */

#define AI_PROC_IOC_MAGIC  'P'

/* 获取待处理请求 (bridge → kernel) */
#define AI_PROC_GET_REQUEST    _IOR(AI_PROC_IOC_MAGIC, 1, struct ai_proc_request)
/* 发送响应 (bridge → kernel) */
#define AI_PROC_SEND_RESPONSE  _IOW(AI_PROC_IOC_MAGIC, 2, struct ai_proc_response)
/* 获取统计 (userspace → kernel) */
#define AI_PROC_GET_STATS     _IOR(AI_PROC_IOC_MAGIC, 3, struct ai_proc_stats)

/* ================================================================
 * 请求/响应结构 (与内核一致)
 * ================================================================ */

/* 文件类型 */
enum ai_proc_file_id {
    AI_PROC_FILE_STATUS = 0,
    AI_PROC_FILE_INFER  = 1,
    AI_PROC_FILE_EMBED  = 2,
    AI_PROC_FILE_CHAT   = 3,
    AI_PROC_FILE_MODELS = 4,
    AI_PROC_FILE_CONFIG = 5,
    AI_PROC_FILE_STATS  = 6,
    AI_PROC_FILE_MAX,
};

/* 请求状态 */
enum ai_req_status {
    AI_REQ_PENDING  = 0,
    AI_REQ_SENT     = 1,
    AI_REQ_TIMEOUT  = 2,
    AI_REQ_ERROR    = 3,
};

/* 请求结构 */
struct ai_proc_request {
    __u32 id;
    __u32 file_id;
    __u32 session_id;
    __u32 status;
    char  data[4096];
    __u32 len;
    __u32 flags;
    struct timespec64 submitted;
};

/* 响应结构 */
struct ai_proc_response {
    __u32 req_id;
    __u32 status;
    char  data[65536];
    __u32 len;
    char  source[16];
    __u32 tokens;
    __u64 inference_ms;
};

/* 统计结构 */
struct ai_proc_stats {
    __u64 infer_count;
    __u64 embed_count;
    __u64 chat_count;
    __u64 error_count;
    __u64 timeout_count;
    __u64 bytes_in;
    __u64 bytes_out;
    __u32 peak_queue_depth;
    __u32 queue_full_count;
    __u64 uptime_ms;
};

/* ================================================================
 * 导出函数 (给其他内核模块用)
 * ================================================================ */

#ifdef __KERNEL__

/* 直接提交推理请求 (从内核其他模块调用) */
int proc_ai_submit_infer(const char *prompt, size_t len,
                         struct ai_proc_response *resp);

/* 查询缓存结果 */
int proc_ai_get_cached(enum ai_proc_file_id file_id,
                       struct ai_proc_response *resp);

#endif /* __KERNEL__ */

#endif /* AINOS_PROC_AI_H */