// SPDX-License-Identifier: GPL-2.0
#ifndef _AINOS_AI_ABI_H
#define _AINOS_AI_ABI_H

/*
 * Ainos OS AI 系统调用 ABI 定义
 * ==========================================
 * 定义 AI 内核子系统与用户空间之间的接口
 *
 * 系统调用号分配 (Linux 原生):
 *   450-459: Ainos AI 系统调用
 */

#include <linux/types.h>
#include <linux/ioctl.h>

#ifdef __KERNEL__
#include <linux/uaccess.h>
#else
#include <stdint.h>
#endif

/* ============================================
 * 系统调用号
 * ============================================ */
#define __NR_ai_inference       450
#define __NR_ai_embedding       451
#define __NR_ai_semantic_search 452
#define __NR_ai_model_load      453
#define __NR_ai_model_unload    454
#define __NR_ai_context_store   455
#define __NR_ai_context_retrieve 456
#define __NR_ai_status          457

/* ============================================
 * AI 任务优先级
 * ============================================ */
enum ai_task_priority {
    AI_PRIO_BACKGROUND = 0,   /* 后台任务，不抢占用户交互 */
    AI_PRIO_LOW,              /* 低优先级 */
    AI_PRIO_NORMAL,           /* 普通优先级 */
    AI_PRIO_HIGH,             /* 高优先级 */
    AI_PRIO_REALTIME,         /* 实时，仅限系统服务 */
};

/* ============================================
 * AI 推理任务状态
 * ============================================ */
enum ai_task_status {
    AI_TASK_PENDING    = 0,
    AI_TASK_RUNNING    = 1,
    AI_TASK_COMPLETED  = 2,
    AI_TASK_FAILED     = 3,
    AI_TASK_CANCELLED  = 4,
};

/* ============================================
 * AI 推理请求结构体
 * ============================================ */
struct ai_inference_req {
    uint64_t model_id;          /* 模型 ID */
    uint64_t session_id;        /* 会话 ID (0 = 新会话) */
    enum ai_task_priority priority;  /* 优先级 */

    /* 输入数据 */
    const char __user *prompt;  /* 输入文本 */
    uint64_t prompt_len;        /* 输入长度 */
    const float __user *images; /* 图像数据 (可选) */
    uint64_t image_count;       /* 图像数量 */

    /* 推理参数 */
    float temperature;          /* 温度 (0.0 - 2.0) */
    float top_p;                /* Top-P 采样 */
    uint32_t max_tokens;        /* 最大输出 token 数 */
    uint32_t context_len;       /* 上下文窗口大小 */
};

/* ============================================
 * AI 推理响应结构体
 * ============================================ */
struct ai_inference_resp {
    uint64_t task_id;           /* 任务 ID (用于异步查询) */
    enum ai_task_status status; /* 任务状态 */

    /* 输出数据 */
    char __user *output;        /* 输出文本缓冲区 */
    uint64_t output_len;        /* 实际输出长度 */
    uint64_t output_capacity;   /* 缓冲区容量 */

    /* 统计信息 */
    uint64_t tokens_generated;  /* 生成 token 数 */
    uint64_t inference_ms;      /* 推理耗时 (毫秒) */
    uint64_t total_ms;          /* 总耗时 (含排队) */
};

/* ============================================
 * 语义搜索结果
 * ============================================ */
#define AI_SEARCH_PATH_LEN 512
#define AI_SEARCH_SNIPPET_LEN 256

struct ai_search_result {
    char path[AI_SEARCH_PATH_LEN];       /* 文件路径 */
    char snippet[AI_SEARCH_SNIPPET_LEN]; /* 匹配片段 */
    float score;                          /* 相关度分数 (0-1) */
    uint64_t file_size;                   /* 文件大小 */
    uint64_t modified_at;                 /* 修改时间戳 */
};

/* ============================================
 * AI 系统状态
 * ============================================ */
struct ai_system_status {
    uint32_t models_loaded;      /* 已加载模型数 */
    uint32_t tasks_pending;      /* 排队任务数 */
    uint32_t tasks_running;      /* 运行中任务数 */
    uint64_t total_inferences;   /* 总推理次数 */
    uint64_t total_tokens;       /* 总生成 token 数 */
    uint64_t uptime_ms;          /* 运行时间 */
    uint8_t  network_available;  /* 网络是否可用 */
    uint8_t  accelerator_type;   /* 加速器类型: 0=CPU, 1=GPU, 2=NPU, 3=VPU */
    char     version[64];        /* AI 子系统版本 */
};

/* ============================================
 * AI 上下文管理
 * ============================================ */
#define AI_CONTEXT_KEY_MAX 128
#define AI_CONTEXT_VAL_MAX 65536

struct ai_context_entry {
    uint64_t session_id;
    char key[AI_CONTEXT_KEY_MAX];
    char __user *value;
    uint64_t value_len;
    uint64_t value_capacity;
};

/* ============================================
 * Embedding 系统调用参数
 * ============================================ */
#define AI_EMBEDDING_DIM_128   128
#define AI_EMBEDDING_DIM_256   256
#define AI_EMBEDDING_DIM_512   512
#define AI_EMBEDDING_DIM_768   768
#define AI_EMBEDDING_DIM_1024  1024
#define AI_EMBEDDING_DIM_2048  2048
#define AI_EMBEDDING_DIM_4096  4096

struct ai_embedding_req {
    const float __user *input;
    uint64_t input_len;
    float __user *embedding;
    uint64_t embedding_dim;
};

/* ============================================
 * Semantic Search 系统调用参数
 * ============================================ */
struct ai_search_req {
    const float __user *query_emb;
    uint64_t query_dim;
    const float __user *database;
    uint64_t db_size;
    uint64_t vector_dim;
    uint32_t top_k;
    struct ai_search_result __user *results;
};

/* ============================================
 * Model Load 参数
 * ============================================ */
#define AI_MODEL_NAME_MAX 64
#define AI_MODEL_PATH_MAX 512

struct ai_model_load_req {
    char name[AI_MODEL_NAME_MAX];
    char path[AI_MODEL_PATH_MAX];
};

/* ============================================
 * Context Store/Retrieve 系统调用参数
 * ============================================ */
struct ai_context_store_req {
    uint64_t session_id;
    char key[AI_CONTEXT_KEY_MAX];
    const char __user *value;
    uint64_t value_len;
    uint64_t ttl_ms;
};

struct ai_context_retrieve_req {
    uint64_t session_id;
    char key[AI_CONTEXT_KEY_MAX];
    uint64_t entry_id;
    char __user *value;
    uint64_t value_capacity;
    uint64_t __user *value_len;
};

/* ============================================
 * IOCTL 命令 (用于 /dev/ainos 设备)
 * ============================================ */
#define AI_IOC_MAGIC  'A'

#define AI_IOCTL_GET_STATUS    _IOR(AI_IOC_MAGIC, 1, struct ai_system_status)
#define AI_IOCTL_LOAD_MODEL    _IOW(AI_IOC_MAGIC, 2, uint64_t)
#define AI_IOCTL_UNLOAD_MODEL  _IOW(AI_IOC_MAGIC, 3, uint64_t)
#define AI_IOCTL_CANCEL_TASK   _IOW(AI_IOC_MAGIC, 4, uint64_t)
#define AI_IOCTL_GET_TASK_STAT _IOR(AI_IOC_MAGIC, 5, uint64_t)
#define AI_IOCTL_SET_VERBOSE   _IOW(AI_IOC_MAGIC, 6, uint8_t)

/* ============================================
 * 错误码
 * ============================================ */
#define AI_ERR_SUCCESS          0
#define AI_ERR_GENERAL          -1
#define AI_ERR_INVALID_PARAM    -2
#define AI_ERR_MODEL_NOT_FOUND  -3
#define AI_ERR_MODEL_LOAD_FAIL  -4
#define AI_ERR_OUT_OF_MEMORY    -5
#define AI_ERR_TASK_QUEUE_FULL  -6
#define AI_ERR_NOT_SUPPORTED    -7
#define AI_ERR_PERMISSION       -8
#define AI_ERR_TIMEOUT          -9
#define AI_ERR_THERMAL_THROTTLE -10

/* ============================================
 * 电源策略调度 (Power Policy)
 * ============================================
 * 当 CPU 温度超过阈值时自动降级推理精度
 * 读取 /sys/class/thermal/thermal_zone0/temp
 * 返回毫摄氏度 (millidegrees Celsius)
 */

/* 电源策略模式 */
enum ai_power_mode {
    AI_POWER_MAX       = 0,  /* < 70°C: 全速模式 (AVX-256, 4核推理, FP32) */
    AI_POWER_BALANCED  = 1,  /* 70-85°C: 平衡模式 (AVX-128, 2核推理, FP16) */
    AI_POWER_EFFICIENT = 2,  /* > 85°C: 节能模式 (NEON/标量, 1核推理, INT8) */
    AI_POWER_EMERGENCY = 3,  /* > 95°C: 紧急模式 (仅标量, 1核推理, INT4) */
};

/* 电源策略状态 */
struct ai_power_status {
    enum ai_power_mode  current_mode;     /* 当前策略模式 */
    uint32_t            cpu_temp;         /* 当前 CPU 温度 (毫摄氏度) */
    uint32_t            cpu_temp_decicelsius; /* 十分之一摄氏度 */
    uint32_t            recommended_threads;  /* 推荐推理线程数 */
    uint8_t             throttle_active;  /* 是否正在降频 */
    uint8_t             sensor_available; /* 温度传感器是否可用 */
};

/* 电源策略 IOCTL */
#define AI_IOCTL_GET_POWER_MODE _IOR(AI_IOC_MAGIC, 7, struct ai_power_status)
#define AI_IOCTL_SET_POWER_MODE _IOW(AI_IOC_MAGIC, 8, enum ai_power_mode)
#define AI_IOCTL_GET_TEMP       _IOR(AI_IOC_MAGIC, 9, uint32_t)

#endif /* _AINOS_AI_ABI_H */