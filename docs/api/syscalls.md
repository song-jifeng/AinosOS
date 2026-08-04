# AinosOS AI 系统调用规范 / AinosOS AI System Call Specification

> **版本 / Version**: 0.1.0  
> **最后更新 / Last Updated**: 2026-08-04  
> **许可 / License**: GPL-2.0  
> **源文件 / Source Files**: `kernel/include/ainos/ai-abi.h`, `kernel/ai-syscalls-main.c`

---

## 目录 / Table of Contents

1. [Overview / 概述](#1-overview--概述)
2. [sys_ai_inference (syscall 450) / 推理系统调用](#2-sys_ai_inference-syscall-450--推理系统调用)
3. [sys_ai_embedding (syscall 451) / 嵌入向量系统调用](#3-sys_ai_embedding-syscall-451--嵌入向量系统调用)
4. [sys_ai_semantic_search (syscall 452) / 语义搜索系统调用](#4-sys_ai_semantic_search-syscall-452--语义搜索系统调用)
5. [sys_ai_model_load (syscall 453) / 加载模型系统调用](#5-sys_ai_model_load-syscall-453--加载模型系统调用)
6. [sys_ai_model_unload (syscall 454) / 卸载模型系统调用](#6-sys_ai_model_unload-syscall-454--卸载模型系统调用)
7. [sys_ai_context_store (syscall 455) / 存储上下文系统调用](#7-sys_ai_context_store-syscall-455--存储上下文系统调用)
8. [sys_ai_context_retrieve (syscall 456) / 检索上下文系统调用](#8-sys_ai_context_retrieve-syscall-456--检索上下文系统调用)
9. [sys_ai_status (syscall 457) / 系统状态系统调用](#9-sys_ai_status-syscall-457--系统状态系统调用)
10. [IOCTL Reference / IOCTL 参考](#10-ioctl-reference--ioctl-参考)
11. [Complete Error Reference / 完整错误码参考](#11-complete-error-reference--完整错误码参考)
12. [Power Policy / 电源策略](#12-power-policy--电源策略)

---

## 1. Overview / 概述

AinosOS 定义了一组专用的 AI 系统调用，编号 450-457，用于在 Linux 内核中实现 AI 推理、嵌入向量计算、语义搜索、模型管理和上下文存储等功能。这些系统调用通过 Linux 内核模块 `ai-syscalls-main.c` 实现，并通过 `/dev/ainos` 字符设备提供 IOCTL 接口。

AinosOS defines a set of dedicated AI system calls, numbered 450-457, that implement AI inference, embedding computation, semantic search, model management, and context storage within the Linux kernel. These system calls are implemented by the kernel module `ai-syscalls-main.c` and exposed through the `/dev/ainos` character device via an IOCTL interface.

### 1.1 系统调用表 / System Call Table

| 系统调用号 / Syscall Number | 名称 / Name | 描述 / Description |
|---|---|---|
| 450 | `sys_ai_inference` | 提交 AI 推理请求 / Submit an AI inference request |
| 451 | `sys_ai_embedding` | 计算文本嵌入向量 / Compute text embeddings |
| 452 | `sys_ai_semantic_search` | 执行语义搜索 / Execute semantic search |
| 453 | `sys_ai_model_load` | 加载 AI 模型 / Load an AI model |
| 454 | `sys_ai_model_unload` | 卸载 AI 模型 / Unload an AI model |
| 455 | `sys_ai_context_store` | 存储上下文数据 / Store context data |
| 456 | `sys_ai_context_retrieve` | 检索上下文数据 / Retrieve context data |
| 457 | `sys_ai_status` | 获取 AI 子系统状态 / Get AI subsystem status |

### 1.2 设备接口 / Device Interface

除了系统调用外，还通过 `/dev/ainos` 设备文件提供 IOCTL 接口，支持以下操作：

In addition to system calls, an IOCTL interface is provided via the `/dev/ainos` device file:

- `AI_IOCTL_GET_STATUS` — 获取系统状态 / Get system status
- `AI_IOCTL_LOAD_MODEL` — 加载模型 / Load model
- `AI_IOCTL_UNLOAD_MODEL` — 卸载模型 / Unload model
- `AI_IOCTL_CANCEL_TASK` — 取消推理任务 / Cancel inference task
- `AI_IOCTL_GET_TASK_STAT` — 获取任务统计 / Get task statistics
- `AI_IOCTL_SET_VERBOSE` — 设置日志级别 / Set verbose level
- `AI_IOCTL_GET_POWER_MODE` — 获取电源策略 / Get power mode
- `AI_IOCTL_SET_POWER_MODE` — 设置电源策略 / Set power mode
- `AI_IOCTL_GET_TEMP` — 获取 CPU 温度 / Get CPU temperature

### 1.3 数据流模型 / Data Flow Model

```
用户空间 / User Space                         内核空间 / Kernel Space
                                                                                
  +------------------+     syscall      +-----------------------+
  | 应用程序 / App   | ---------------> | ai_sched_submit()     |
  |                  |                  | ai_sched_submit_async()|
  | struct req       | <--------------- | ai_sched_cancel()     |
  | struct resp      |     syscall      |                       |
  +------------------+                  +-----------------------+
          |                                      |
          | IOCTL                                |
          v                                      v
  +------------------+                  +-----------------------+
  | /dev/ainos       |                  | 模型表 / Model Table   |
  |                  |                  | 上下文表 / Context Table|
  +------------------+                  +-----------------------+
```

### 1.4 并发模型 / Concurrency Model

- 所有系统调用在内核上下文中执行 / All system calls execute in kernel context
- 推理任务使用 AI 调度器异步执行 / Inference tasks use the AI scheduler for async execution
- 模型表使用互斥锁 `g_model_lock` 保护 / Model table is protected by `g_model_lock`
- 上下文表使用互斥锁 `g_context_lock` 保护 / Context table is protected by `g_context_lock`
- 最大模型数：32 / Maximum models: 32
- 最大上下文条目数：1024 / Maximum context entries: 1024

---

## 2. sys_ai_inference (syscall 450) / 推理系统调用

### 2.1 原型 / Prototype

```c
SYSCALL_DEFINE2(ai_inference,
                struct ai_inference_req __user *, req_u,
                struct ai_inference_resp __user *, resp_u)
```

### 2.2 请求结构体 / Request Structure

```c
struct ai_inference_req {
    uint64_t model_id;                  /* 模型 ID */
    uint64_t session_id;                /* 会话 ID (0 = 新会话) */
    enum ai_task_priority priority;     /* 优先级 */

    /* 输入数据 */
    const char __user *prompt;          /* 输入文本 */
    uint64_t prompt_len;                /* 输入长度 */
    const float __user *images;         /* 图像数据 (可选) */
    uint64_t image_count;               /* 图像数量 */

    /* 推理参数 */
    float temperature;                  /* 温度 (0.0 - 2.0) */
    float top_p;                        /* Top-P 采样 */
    uint32_t max_tokens;                /* 最大输出 token 数 */
    uint32_t context_len;              /* 上下文窗口大小 */
};
```

#### 字段说明 / Field Descriptions

| 字段 / Field | 类型 / Type | 描述 / Description |
|---|---|---|
| `model_id` | `uint64_t` | 通过 `sys_ai_model_load` 返回的模型标识符 / Model identifier returned by `sys_ai_model_load` |
| `session_id` | `uint64_t` | 会话标识符，用于上下文跟踪（0 表示新会话）/ Session identifier for context tracking (0 = new session) |
| `priority` | `enum ai_task_priority` | 任务优先级 / Task priority |
| `prompt` | `const char __user *` | 指向输入提示文本的用户空间指针 / Pointer to input prompt text in user space |
| `prompt_len` | `uint64_t` | 提示文本的字节长度 / Byte length of the prompt |
| `images` | `const float __user *` | 可选图像数据（浮点数组，每个图像展平后串联）/ Optional image data (flattened float arrays) |
| `image_count` | `uint64_t` | 图像数量 / Number of images |
| `temperature` | `float` | 采样温度，控制随机性（0.0=确定性，2.0=高随机）/ Sampling temperature (0.0=deterministic, 2.0=highly random) |
| `top_p` | `float` | 核采样阈值，仅考虑累积概率达到此值的 token / Nucleus sampling threshold |
| `max_tokens` | `uint32_t` | 最大生成 token 数 / Maximum number of tokens to generate |
| `context_len` | `uint32_t` | 上下文窗口大小 / Context window size |

### 2.3 优先级枚举 / Priority Enum

```c
enum ai_task_priority {
    AI_PRIO_BACKGROUND = 0,  /* 后台任务，不抢占用户交互 */
    AI_PRIO_LOW,             /* 低优先级 */
    AI_PRIO_NORMAL,          /* 普通优先级 */
    AI_PRIO_HIGH,            /* 高优先级 */
    AI_PRIO_REALTIME,        /* 实时，仅限系统服务 */
};
```

### 2.4 响应结构体 / Response Structure

```c
struct ai_inference_resp {
    uint64_t task_id;                   /* 任务 ID (用于异步查询) */
    enum ai_task_status status;         /* 任务状态 */

    /* 输出数据 */
    char __user *output;                /* 输出文本缓冲区 */
    uint64_t output_len;                /* 实际输出长度 */
    uint64_t output_capacity;           /* 缓冲区容量 */

    /* 统计信息 */
    uint64_t tokens_generated;          /* 生成 token 数 */
    uint64_t inference_ms;              /* 推理耗时 (毫秒) */
    uint64_t total_ms;                  /* 总耗时 (含排队) */
};
```

#### 字段说明 / Field Descriptions

| 字段 / Field | 类型 / Type | 描述 / Description |
|---|---|---|
| `task_id` | `uint64_t` | 唯一任务标识符，用于异步查询和取消 / Unique task ID for async query and cancellation |
| `status` | `enum ai_task_status` | 任务状态 / Task status |
| `output` | `char __user *` | 指向输出缓冲区的用户空间指针 / Pointer to output buffer in user space |
| `output_len` | `uint64_t` | 实际写入输出缓冲区的字节数 / Actual bytes written to output buffer |
| `output_capacity` | `uint64_t` | 输出缓冲区容量 / Output buffer capacity |
| `tokens_generated` | `uint64_t` | 生成的 token 总数 / Total tokens generated |
| `inference_ms` | `uint64_t` | 纯推理耗时（毫秒）/ Pure inference time (milliseconds) |
| `total_ms` | `uint64_t` | 包含排队等待的总耗时（毫秒）/ Total time including queuing (milliseconds) |

### 2.5 任务状态枚举 / Task Status Enum

```c
enum ai_task_status {
    AI_TASK_PENDING    = 0,  /* 排队等待中 / Queued */
    AI_TASK_RUNNING    = 1,  /* 正在执行 / Running */
    AI_TASK_COMPLETED  = 2,  /* 完成 / Completed */
    AI_TASK_FAILED     = 3,  /* 失败 / Failed */
    AI_TASK_CANCELLED  = 4,  /* 已取消 / Cancelled */
};
```

### 2.6 异步提交 / Async Submission

推理任务支持异步提交模式。当使用 `ai_sched_submit_async()` 时，系统调用立即返回 `task_id`，响应中的 `status` 为 `AI_TASK_PENDING`。应用程序可以通过以下方式获取结果：

- 使用 `AI_IOCTL_GET_TASK_STAT` 查询任务状态
- 使用 `AI_IOCTL_CANCEL_TASK` 取消任务

### 2.7 错误码 / Error Codes

| 错误码 / Error Code | 值 / Value | 说明 / Description |
|---|---|---|
| `AI_ERR_SUCCESS` | 0 | 成功 / Success |
| `AI_ERR_INVALID_PARAM` | -2 | 参数无效（req_u 或 resp_u 为 NULL）/ Invalid parameters |
| `AI_ERR_OUT_OF_MEMORY` | -5 | 内存不足 / Out of memory |
| `AI_ERR_TASK_QUEUE_FULL` | -6 | 任务队列已满 / Task queue full |
| `AI_ERR_NOT_SUPPORTED` | -7 | 不支持的操作 / Not supported |
| `AI_ERR_PERMISSION` | -8 | 权限不足 / Permission denied |
| `AI_ERR_TIMEOUT` | -9 | 操作超时 / Timeout |
| `AI_ERR_THERMAL_THROTTLE` | -10 | 热降频中 / Thermal throttling |

### 2.8 C 语言使用示例 / C Usage Example

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/syscall.h>
#include "ainos/ai-abi.h"

int main() {
    struct ai_inference_req req;
    struct ai_inference_resp resp;
    char output_buf[4096];
    int ret;

    /* 准备请求 / Prepare request */
    memset(&req, 0, sizeof(req));
    req.model_id = 1;  /* 从 sys_ai_model_load 获取 / Obtained from sys_ai_model_load */
    req.prompt = "Hello, Ainos!";
    req.prompt_len = strlen(req.prompt);
    req.temperature = 0.7f;
    req.top_p = 0.9f;
    req.max_tokens = 512;
    req.context_len = 4096;
    req.priority = AI_PRIO_NORMAL;

    /* 准备响应缓冲区 / Prepare response buffer */
    memset(&resp, 0, sizeof(resp));
    resp.output = output_buf;
    resp.output_capacity = sizeof(output_buf);

    /* 调用系统调用 / Invoke system call */
    ret = syscall(__NR_ai_inference, &req, &resp);
    if (ret != 0) {
        fprintf(stderr, "sys_ai_inference failed: %d\n", ret);
        return 1;
    }

    /* 检查异步状态 / Check async status */
    if (resp.status == AI_TASK_COMPLETED) {
        printf("Output: %s\n", output_buf);
        printf("Tokens: %lu, Time: %lu ms\n",
               resp.tokens_generated, resp.inference_ms);
    } else {
        printf("Task %lu status: %d\n", resp.task_id, resp.status);
    }

    return 0;
}
```

### 2.9 Python 使用示例 / Python Usage Example

```python
import ctypes
import os

# 系统调用号 / Syscall number
__NR_ai_inference = 450

# 结构体定义 / Structure definitions
class ai_inference_req(ctypes.Structure):
    _fields_ = [
        ("model_id", ctypes.c_uint64),
        ("session_id", ctypes.c_uint64),
        ("priority", ctypes.c_int),
        ("prompt", ctypes.c_char_p),
        ("prompt_len", ctypes.c_uint64),
        ("images", ctypes.POINTER(ctypes.c_float)),
        ("image_count", ctypes.c_uint64),
        ("temperature", ctypes.c_float),
        ("top_p", ctypes.c_float),
        ("max_tokens", ctypes.c_uint32),
        ("context_len", ctypes.c_uint32),
    ]

class ai_inference_resp(ctypes.Structure):
    _fields_ = [
        ("task_id", ctypes.c_uint64),
        ("status", ctypes.c_int),
        ("output", ctypes.c_char_p),
        ("output_len", ctypes.c_uint64),
        ("output_capacity", ctypes.c_uint64),
        ("tokens_generated", ctypes.c_uint64),
        ("inference_ms", ctypes.c_uint64),
        ("total_ms", ctypes.c_uint64),
    ]

# 准备请求 / Prepare request
prompt = b"Hello, Ainos!"
output_buf = ctypes.create_string_buffer(4096)

req = ai_inference_req()
req.model_id = 1
req.prompt = prompt
req.prompt_len = len(prompt)
req.temperature = 0.7
req.top_p = 0.9
req.max_tokens = 512
req.context_len = 4096
req.priority = 2  # AI_PRIO_NORMAL

resp = ai_inference_resp()
resp.output = output_buf
resp.output_capacity = len(output_buf)

# 调用系统调用 / Invoke system call
libc = ctypes.CDLL("libc.so.6")
ret = libc.syscall(__NR_ai_inference, ctypes.byref(req), ctypes.byref(resp))

if ret == 0 and resp.status == 2:  # AI_TASK_COMPLETED
    print(f"Output: {output_buf.value.decode('utf-8')}")
    print(f"Tokens: {resp.tokens_generated}, Time: {resp.inference_ms}ms")
```

---

## 3. sys_ai_embedding (syscall 451) / 嵌入向量系统调用

### 3.1 原型 / Prototype

```c
SYSCALL_DEFINE1(ai_embedding, struct ai_embedding_req __user *, req_u)
```

### 3.2 请求结构体 / Request Structure

```c
struct ai_embedding_req {
    const float __user *input;      /* 输入浮点数组 */
    uint64_t input_len;             /* 输入元素数 */
    float __user *embedding;        /* 输出嵌入向量缓冲区 */
    uint64_t embedding_dim;         /* 嵌入向量维度 (参见有效维度列表) */
};
```

### 3.3 有效嵌入维度 / Valid Embedding Dimensions

```c
#define AI_EMBEDDING_DIM_128   128
#define AI_EMBEDDING_DIM_256   256
#define AI_EMBEDDING_DIM_512   512
#define AI_EMBEDDING_DIM_768   768
#define AI_EMBEDDING_DIM_1024  1024
#define AI_EMBEDDING_DIM_2048  2048
#define AI_EMBEDDING_DIM_4096  4096
```

内核中通过以下数组验证维度：

```c
static const size_t ai_valid_dims[] = {
    128, 256, 512, 768, 1024, 2048, 4096
};
```

### 3.4 算法说明 / Algorithm Description

嵌入向量计算使用**随机投影（Random Projection）**算法：

1. 输入向量 `input` 的长度为 `input_len`
2. 目标嵌入维度为 `embedding_dim`
3. 对于每个目标维度 `i`，生成确定性哈希权重向量 `w_i`，其中 `w_i[j] = embedding_weight(i, j)`
4. 计算 `embedding[i] = dot(input, w_i)` 作为该维度的值

#### 确定性哈希权重生成 / Deterministic Hash Weight Generation

```c
static inline float embedding_weight(size_t dim_idx, size_t pos)
{
    uint32_t h;
    h = (uint32_t)(dim_idx * 2654435761U + pos * 2246822519U);
    h = (h ^ (h >> 16)) * 0x45d9f3b;
    h = (h ^ (h >> 16)) * 0x45d9f3b;
    h = h ^ (h >> 16);
    return ((float)(h % 2001) / 1000.0f) - 1.0f;
}
```

权重生成使用两个质数常量（2654435761 和 2246822519）作为种子，通过三次混合操作生成范围在 [-1.0, 1.0) 内的确定性伪随机数。相同的 `(dim_idx, pos)` 对始终产生相同的权重值，无需存储权重矩阵。

#### 余弦相似度计算 / Cosine Similarity

余弦相似度用于比较两个嵌入向量：

```c
static inline float ai_float_sqrt(float x)
{
    float guess;
    int i;
    if (x <= 0.0f) return 0.0f;
    guess = x;
    for (i = 0; i < 20; i++)
        guess = (guess + x / guess) * 0.5f;
    return guess;
}

// 余弦相似度 = dot(a, b) / (|a| * |b|)
float similarity = ai_vector_dot_product(n, a, b) /
    (ai_float_sqrt(ai_vector_dot_product(n, a, a)) *
     ai_float_sqrt(ai_vector_dot_product(n, b, b)));
```

### 3.5 输入限制 / Input Limits

- `input_len` 最大值：1,048,576（1M 个浮点数）/ Maximum input_len: 1,048,576 (1M floats)
- `embedding_dim` 必须是有效维度之一 / Must be one of the valid dimensions
- `input` 和 `embedding` 指针不能为 NULL / Pointers must not be NULL

### 3.6 错误码 / Error Codes

| 错误码 / Error Code | 值 / Value | 说明 / Description |
|---|---|---|
| `AI_ERR_SUCCESS` | 0 | 成功 / Success |
| `AI_ERR_INVALID_PARAM` | -2 | 参数无效（NULL 指针、无效维度、输入长度为 0）/ Invalid parameters |
| `AI_ERR_OUT_OF_MEMORY` | -5 | 内存不足 / Out of memory |

### 3.7 使用示例 / Usage Example

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/syscall.h>
#include "ainos/ai-abi.h"

int main() {
    struct ai_embedding_req req;
    float input[] = {1.0f, 2.0f, 3.0f, 4.0f, 5.0f};
    float embedding[AI_EMBEDDING_DIM_128];
    int ret;

    memset(&req, 0, sizeof(req));
    req.input = input;
    req.input_len = 5;
    req.embedding = embedding;
    req.embedding_dim = AI_EMBEDDING_DIM_128;

    ret = syscall(__NR_ai_embedding, &req);
    if (ret == 0) {
        printf("Embedding vector (first 5 dims):\n");
        for (int i = 0; i < 5 && i < AI_EMBEDDING_DIM_128; i++) {
            printf("  [%d] = %f\n", i, embedding[i]);
        }
    } else {
        fprintf(stderr, "sys_ai_embedding failed: %d\n", ret);
    }

    return 0;
}
```

---

## 4. sys_ai_semantic_search (syscall 452) / 语义搜索系统调用

### 4.1 原型 / Prototype

```c
SYSCALL_DEFINE1(ai_semantic_search, struct ai_search_req __user *, req_u)
```

### 4.2 请求结构体 / Request Structure

```c
#define AI_SEARCH_PATH_LEN 512
#define AI_SEARCH_SNIPPET_LEN 256

struct ai_search_result {
    char path[AI_SEARCH_PATH_LEN];          /* 文件路径 */
    char snippet[AI_SEARCH_SNIPPET_LEN];    /* 匹配片段 */
    float score;                             /* 相关度分数 (0-1) */
    uint64_t file_size;                      /* 文件大小 */
    uint64_t modified_at;                    /* 修改时间戳 */
};

struct ai_search_req {
    const float __user *query_emb;          /* 查询嵌入向量 */
    uint64_t query_dim;                     /* 查询向量维度 */
    const float __user *database;           /* 数据库向量 (展平数组) */
    uint64_t db_size;                       /* 数据库向量数量 */
    uint64_t vector_dim;                    /* 每个向量的维度 */
    uint32_t top_k;                         /* 返回 Top-K 结果数 */
    struct ai_search_result __user *results; /* 结果缓冲区 */
};
```

### 4.3 算法说明 / Algorithm Description

1. 从用户空间复制查询向量 `query_emb`
2. 计算查询向量的 L2 范数 `query_norm`
3. 遍历数据库中的每个向量，计算余弦相似度：
   - `similarity = dot(query, vec_i) / (query_norm * vec_norm_i)`
   - 使用 `ai_vector_dot_product()` 进行向量点积
   - 使用 `ai_float_sqrt()` 计算平方根
4. 按相似度降序排序所有向量
5. 返回前 `top_k` 个结果

### 4.4 参数限制 / Parameter Limits

| 参数 / Parameter | 最小值 / Min | 最大值 / Max | 默认值 / Default |
|---|---|---|---|
| `query_dim` | 1 | 4096 | - |
| `vector_dim` | 1 | 4096 | - |
| `db_size` | 1 | 10000 | - |
| `top_k` | 1 | 1000 | 10（如果为 0） |

- `query_dim` 必须等于 `vector_dim`
- 如果 `top_k > db_size`，则自动调整为 `db_size`
- 如果 `top_k > 1000`，则限制为 1000

### 4.5 结果结构体 / Result Structure

```c
struct ai_search_result {
    char path[AI_SEARCH_PATH_LEN];          /* 512 字节 */
    char snippet[AI_SEARCH_SNIPPET_LEN];    /* 256 字节 */
    float score;                             /* 相关度分数 (0-1) */
    uint64_t file_size;                      /* 文件大小 */
    uint64_t modified_at;                    /* 修改时间戳 */
};
```

### 4.6 错误码 / Error Codes

| 错误码 / Error Code | 值 / Value | 说明 / Description |
|---|---|---|
| `AI_ERR_SUCCESS` | 0 | 成功 / Success |
| `AI_ERR_INVALID_PARAM` | -2 | 参数无效 / Invalid parameters |
| `AI_ERR_OUT_OF_MEMORY` | -5 | 内存不足 / Out of memory |

### 4.7 使用示例 / Usage Example

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/syscall.h>
#include "ainos/ai-abi.h"

int main() {
    struct ai_search_req req;
    float query_emb[128];  /* 128 维查询向量 */
    float database[128 * 100];  /* 100 个 128 维向量 */
    struct ai_search_result results[10];
    int ret;

    /* 初始化查询向量和数据库 / Initialize query vector and database */
    /* ... (填充数据) ... */

    memset(&req, 0, sizeof(req));
    req.query_emb = query_emb;
    req.query_dim = 128;
    req.database = database;
    req.db_size = 100;
    req.vector_dim = 128;
    req.top_k = 10;
    req.results = results;

    ret = syscall(__NR_ai_semantic_search, &req);
    if (ret == 0) {
        printf("Top-10 results:\n");
        for (int i = 0; i < 10; i++) {
            printf("  [%d] score=%.4f path=%s\n",
                   i, results[i].score, results[i].path);
        }
    }

    return 0;
}
```

---

## 5. sys_ai_model_load (syscall 453) / 加载模型系统调用

### 5.1 原型 / Prototype

```c
SYSCALL_DEFINE2(ai_model_load,
                struct ai_model_load_req __user *, req_u,
                uint64_t __user *, model_id_u)
```

### 5.2 请求结构体 / Request Structure

```c
#define AI_MODEL_NAME_MAX 64
#define AI_MODEL_PATH_MAX 512

struct ai_model_load_req {
    char name[AI_MODEL_NAME_MAX];   /* 模型名称 (最多 63 字符 + null) */
    char path[AI_MODEL_PATH_MAX];   /* 模型文件路径 (最多 511 字符 + null) */
};
```

### 5.3 模型表 / Model Table

模型表存储在内核中，最多支持 32 个模型：

```c
#define AI_MAX_MODELS 32

struct ai_model_entry {
    uint64_t model_id;
    char name[AI_MODEL_NAME_MAX];
    char path[AI_MODEL_PATH_MAX];
    bool loaded;
    ktime_t loaded_at;
};
```

### 5.4 加载流程 / Load Flow

1. 验证 `name` 和 `path` 不能为空字符串
2. 使用 `filp_open()` 验证模型文件是否存在（以只读方式打开）
3. 如果文件不存在，返回 `AI_ERR_MODEL_NOT_FOUND`
4. 在模型表中查找空槽（最多 32 个模型）
5. 如果模型表已满，返回 `AI_ERR_MODEL_LOAD_FAIL`
6. 检查是否已加载同名模型（按名称去重）
7. 如果已存在同名模型，返回已有模型 ID
8. 分配新模型 ID（从 1 开始递增）
9. 记录加载时间戳
10. 将模型 ID 复制到用户空间

### 5.5 错误码 / Error Codes

| 错误码 / Error Code | 值 / Value | 说明 / Description |
|---|---|---|
| `AI_ERR_SUCCESS` | 0 | 成功 / Success |
| `AI_ERR_INVALID_PARAM` | -2 | 参数无效（NULL 指针或空名称/路径）/ Invalid parameters |
| `AI_ERR_MODEL_NOT_FOUND` | -3 | 模型文件不存在 / Model file not found |
| `AI_ERR_MODEL_LOAD_FAIL` | -4 | 模型表已满 / Model table full |

### 5.6 使用示例 / Usage Example

```c
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/syscall.h>
#include "ainos/ai-abi.h"

int main() {
    struct ai_model_load_req req;
    uint64_t model_id;
    int ret;

    strncpy(req.name, "phi-3-mini", AI_MODEL_NAME_MAX - 1);
    strncpy(req.path, "/models/phi-3-mini-4k-instruct-q4.gguf",
            AI_MODEL_PATH_MAX - 1);

    ret = syscall(__NR_ai_model_load, &req, &model_id);
    if (ret == 0) {
        printf("Model loaded successfully: id=%llu\n", model_id);
    } else if (ret == -AI_ERR_MODEL_NOT_FOUND) {
        fprintf(stderr, "Model file not found\n");
    } else {
        fprintf(stderr, "Model load failed: %d\n", ret);
    }

    return 0;
}
```

---

## 6. sys_ai_model_unload (syscall 454) / 卸载模型系统调用

### 6.1 原型 / Prototype

```c
SYSCALL_DEFINE1(ai_model_unload, uint64_t, model_id)
```

### 6.2 参数说明 / Parameter Description

| 参数 / Parameter | 类型 / Type | 描述 / Description |
|---|---|---|
| `model_id` | `uint64_t` | 要卸载的模型 ID / Model ID to unload |

### 6.3 卸载流程 / Unload Flow

1. 在模型表中查找匹配的 `model_id`（已加载且 ID 匹配）
2. 如果找到，使用 `memset()` 将条目清零
3. 记录卸载日志
4. 如果未找到，返回 `AI_ERR_MODEL_NOT_FOUND`

### 6.4 错误码 / Error Codes

| 错误码 / Error Code | 值 / Value | 说明 / Description |
|---|---|---|
| `AI_ERR_SUCCESS` | 0 | 成功 / Success |
| `AI_ERR_MODEL_NOT_FOUND` | -3 | 指定的模型 ID 未找到 / Model ID not found |

### 6.5 使用示例 / Usage Example

```c
#include <stdio.h>
#include <unistd.h>
#include <sys/syscall.h>
#include "ainos/ai-abi.h"

int main() {
    uint64_t model_id = 1;  /* 从 sys_ai_model_load 获取 */
    int ret;

    ret = syscall(__NR_ai_model_unload, model_id);
    if (ret == 0) {
        printf("Model %llu unloaded successfully\n", model_id);
    } else {
        fprintf(stderr, "Model unload failed: %d\n", ret);
    }

    return 0;
}
```

---

## 7. sys_ai_context_store (syscall 455) / 存储上下文系统调用

### 7.1 原型 / Prototype

```c
SYSCALL_DEFINE2(ai_context_store,
                struct ai_context_store_req __user *, req_u,
                uint64_t __user *, entry_id_u)
```

### 7.2 请求结构体 / Request Structure

```c
#define AI_CONTEXT_KEY_MAX 128
#define AI_CONTEXT_VAL_MAX 65536

struct ai_context_store_req {
    uint64_t session_id;                /* 会话 ID */
    char key[AI_CONTEXT_KEY_MAX];       /* 键 (最多 127 字符 + null) */
    const char __user *value;           /* 值数据 */
    uint64_t value_len;                 /* 值长度 (字节) */
    uint64_t ttl_ms;                    /* 生存时间 (毫秒, 0=永不过期) */
};
```

### 7.3 限制 / Limits

| 参数 / Parameter | 最大值 / Max |
|---|---|
| 键长度 / Key Length | 128 字节（含 null 终止符）/ 128 bytes (including null terminator) |
| 值长度 / Value Length | 65,536 字节 (64 KB) / 65,536 bytes (64 KB) |
| 总条目数 / Total Entries | 1024 |

### 7.4 存储流程 / Store Flow

1. 验证参数（键非空、值非空、值长度不超过 65536）
2. 从用户空间复制值数据到内核缓冲区
3. 在上下文表中查找空槽或已存在的 `(session_id, key)` 对
4. 如果已存在，覆盖旧值（释放旧缓冲区）
5. 如果表已满，返回 `AI_ERR_OUT_OF_MEMORY`
6. 分配新 `entry_id`（从 1 开始递增）
7. 记录时间戳和 TTL
8. 将 `entry_id` 复制到用户空间

### 7.5 错误码 / Error Codes

| 错误码 / Error Code | 值 / Value | 说明 / Description |
|---|---|---|
| `AI_ERR_SUCCESS` | 0 | 成功 / Success |
| `AI_ERR_INVALID_PARAM` | -2 | 参数无效（键为空、值为空等）/ Invalid parameters |
| `AI_ERR_OUT_OF_MEMORY` | -5 | 上下文表已满或内存不足 / Context table full or out of memory |

### 7.6 使用示例 / Usage Example

```c
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/syscall.h>
#include "ainos/ai-abi.h"

int main() {
    struct ai_context_store_req req;
    uint64_t entry_id;
    const char *value = "Hello, Ainos context!";
    int ret;

    memset(&req, 0, sizeof(req));
    req.session_id = 42;
    strncpy(req.key, "greeting", AI_CONTEXT_KEY_MAX - 1);
    req.value = value;
    req.value_len = strlen(value) + 1;
    req.ttl_ms = 60000;  /* 60 秒后过期 / Expire after 60 seconds */

    ret = syscall(__NR_ai_context_store, &req, &entry_id);
    if (ret == 0) {
        printf("Context stored: entry_id=%llu\n", entry_id);
    } else {
        fprintf(stderr, "Context store failed: %d\n", ret);
    }

    return 0;
}
```

---

## 8. sys_ai_context_retrieve (syscall 456) / 检索上下文系统调用

### 8.1 原型 / Prototype

```c
SYSCALL_DEFINE1(ai_context_retrieve,
                struct ai_context_retrieve_req __user *, req_u)
```

### 8.2 请求结构体 / Request Structure

```c
struct ai_context_retrieve_req {
    uint64_t session_id;                /* 会话 ID */
    char key[AI_CONTEXT_KEY_MAX];       /* 键 (可选，当 entry_id > 0 时可忽略) */
    uint64_t entry_id;                  /* 条目 ID (0 = 按 session_id + key 查询) */
    char __user *value;                 /* 值缓冲区 */
    uint64_t value_capacity;            /* 缓冲区容量 */
    uint64_t __user *value_len;         /* 实际值长度 (输出) */
};
```

### 8.3 查询方式 / Query Methods

两种查询方式二选一：

1. **按 entry_id 查询**: 设置 `entry_id > 0`，忽略 `session_id` 和 `key`
2. **按 (session_id, key) 查询**: 设置 `entry_id = 0`，提供 `session_id` 和 `key`

### 8.4 TTL 过期检查 / TTL Expiry Check

检索时自动检查 TTL 过期：

```c
if (g_context_table[i].ttl_ms > 0) {
    ktime_t now = ktime_get();
    uint64_t elapsed = ktime_to_ms(
        ktime_sub(now, g_context_table[i].created_at));
    if (elapsed >= g_context_table[i].ttl_ms) {
        /* 条目已过期，自动清理 */
        kvfree(g_context_table[i].value);
        memset(&g_context_table[i], 0, sizeof(g_context_table[i]));
        return -AI_ERR_TIMEOUT;
    }
}
```

### 8.5 错误码 / Error Codes

| 错误码 / Error Code | 值 / Value | 说明 / Description |
|---|---|---|
| `AI_ERR_SUCCESS` | 0 | 成功 / Success |
| `AI_ERR_INVALID_PARAM` | -2 | 参数无效（键未提供且未指定 entry_id，或缓冲区容量为 0）/ Invalid parameters |
| `AI_ERR_OUT_OF_MEMORY` | -5 | 内存不足 / Out of memory |
| `AI_ERR_TIMEOUT` | -9 | 条目已过期（TTL 到期）/ Entry expired (TTL reached) |
| `ENOSPC` | 28 | 值缓冲区容量不足 / Value buffer too small |

### 8.6 使用示例 / Usage Example

```c
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/syscall.h>
#include "ainos/ai-abi.h"

int main() {
    struct ai_context_retrieve_req req;
    char value_buf[4096];
    uint64_t value_len;
    int ret;

    /* 按 (session_id, key) 查询 / Query by (session_id, key) */
    memset(&req, 0, sizeof(req));
    req.session_id = 42;
    strncpy(req.key, "greeting", AI_CONTEXT_KEY_MAX - 1);
    req.entry_id = 0;
    req.value = value_buf;
    req.value_capacity = sizeof(value_buf);
    req.value_len = &value_len;

    ret = syscall(__NR_ai_context_retrieve, &req);
    if (ret == 0) {
        printf("Retrieved: %s (len=%llu)\n", value_buf, value_len);
    } else if (ret == -AI_ERR_TIMEOUT) {
        printf("Entry has expired\n");
    } else {
        fprintf(stderr, "Context retrieve failed: %d\n", ret);
    }

    return 0;
}
```

---

## 9. sys_ai_status (syscall 457) / 系统状态系统调用

### 9.1 原型 / Prototype

```c
SYSCALL_DEFINE1(ai_status, struct ai_system_status __user *, status)
```

### 9.2 状态结构体 / Status Structure

```c
struct ai_system_status {
    uint32_t models_loaded;      /* 已加载模型数 */
    uint32_t tasks_pending;      /* 排队任务数 */
    uint32_t tasks_running;      /* 运行中任务数 */
    uint64_t total_inferences;   /* 总推理次数 */
    uint64_t total_tokens;       /* 总生成 token 数 */
    uint64_t uptime_ms;          /* 运行时间 (毫秒) */
    uint8_t  network_available;  /* 网络是否可用 (0=不可用, 1=可用) */
    uint8_t  accelerator_type;   /* 加速器类型 */
    char     version[64];        /* AI 子系统版本字符串 */
};
```

### 9.3 加速器类型 / Accelerator Types

| 值 / Value | 类型 / Type | 描述 / Description |
|---|---|---|
| 0 | CPU | 纯 CPU 推理 / CPU-only inference |
| 1 | GPU | GPU 加速 / GPU accelerated |
| 2 | NPU | 神经网络处理器 / Neural Processing Unit |
| 3 | VPU | 视觉处理单元 / Vision Processing Unit |

### 9.4 实现细节 / Implementation Details

系统调用 `sys_ai_status` 执行以下操作：

1. 验证 `status` 指针不为 NULL
2. 调用外部函数 `ai_sched_get_status(&st)` 获取调度器状态
3. 遍历模型表，统计已加载模型数
4. 将完整状态结构体复制到用户空间

### 9.5 错误码 / Error Codes

| 错误码 / Error Code | 值 / Value | 说明 / Description |
|---|---|---|
| `AI_ERR_SUCCESS` | 0 | 成功 / Success |
| `AI_ERR_INVALID_PARAM` | -2 | status 指针为 NULL / NULL status pointer |

### 9.6 使用示例 / Usage Example

```c
#include <stdio.h>
#include <unistd.h>
#include <sys/syscall.h>
#include "ainos/ai-abi.h"

int main() {
    struct ai_system_status status;
    int ret;

    ret = syscall(__NR_ai_status, &status);
    if (ret == 0) {
        printf("Ainos AI Subsystem Status:\n");
        printf("  Version:          %s\n", status.version);
        printf("  Models Loaded:    %u\n", status.models_loaded);
        printf("  Tasks Pending:    %u\n", status.tasks_pending);
        printf("  Tasks Running:    %u\n", status.tasks_running);
        printf("  Total Inferences: %lu\n", status.total_inferences);
        printf("  Total Tokens:     %lu\n", status.total_tokens);
        printf("  Uptime:           %lu ms\n", status.uptime_ms);
        printf("  Network:          %s\n",
               status.network_available ? "Available" : "Unavailable");
        printf("  Accelerator:      %d\n", status.accelerator_type);
    }

    return 0;
}
```

---

## 10. IOCTL Reference / IOCTL 参考

### 10.1 IOCTL 命令表 / IOCTL Command Table

所有 IOCTL 命令使用幻数 `'A'`（`AI_IOC_MAGIC`）。

```c
#define AI_IOC_MAGIC 'A'

#define AI_IOCTL_GET_STATUS    _IOR(AI_IOC_MAGIC, 1, struct ai_system_status)
#define AI_IOCTL_LOAD_MODEL    _IOW(AI_IOC_MAGIC, 2, uint64_t)
#define AI_IOCTL_UNLOAD_MODEL  _IOW(AI_IOC_MAGIC, 3, uint64_t)
#define AI_IOCTL_CANCEL_TASK   _IOW(AI_IOC_MAGIC, 4, uint64_t)
#define AI_IOCTL_GET_TASK_STAT _IOR(AI_IOC_MAGIC, 5, uint64_t)
#define AI_IOCTL_SET_VERBOSE   _IOW(AI_IOC_MAGIC, 6, uint8_t)
```

| 命令 / Command | 方向 / Direction | 参数类型 / Arg Type | 描述 / Description |
|---|---|---|---|
| `AI_IOCTL_GET_STATUS` | 读 (IOR) | `struct ai_system_status` | 获取 AI 子系统状态 / Get AI subsystem status |
| `AI_IOCTL_LOAD_MODEL` | 写 (IOW) | `uint64_t` | 加载模型（通过模型 ID）/ Load model (by model ID) |
| `AI_IOCTL_UNLOAD_MODEL` | 写 (IOW) | `uint64_t` | 卸载模型（通过模型 ID）/ Unload model (by model ID) |
| `AI_IOCTL_CANCEL_TASK` | 写 (IOW) | `uint64_t` | 取消推理任务（通过任务 ID）/ Cancel inference task (by task ID) |
| `AI_IOCTL_GET_TASK_STAT` | 读 (IOR) | `uint64_t` | 获取任务统计信息 / Get task statistics |
| `AI_IOCTL_SET_VERBOSE` | 写 (IOW) | `uint8_t` | 设置日志详细级别 / Set verbose logging level |

### 10.2 IOCTL 实现 / IOCTL Implementation

```c
static long ainos_device_ioctl(struct file *file, unsigned int cmd,
                                unsigned long arg)
{
    void __user *argp = (void __user *)arg;
    struct ai_system_status status;
    uint64_t val;
    int ret = 0;

    switch (cmd) {
    case AI_IOCTL_GET_STATUS:
        ai_sched_get_status(&status);
        if (copy_to_user(argp, &status, sizeof(status)))
            ret = -EFAULT;
        break;

    case AI_IOCTL_CANCEL_TASK:
        if (copy_from_user(&val, argp, sizeof(val))) {
            ret = -EFAULT;
            break;
        }
        ret = ai_sched_cancel(val);
        break;

    default:
        ret = -ENOTTY;
        break;
    }

    return ret;
}
```

### 10.3 使用示例 / Usage Example

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include "ainos/ai-abi.h"

int main() {
    int fd = open("/dev/ainos", O_RDWR);
    if (fd < 0) {
        perror("open /dev/ainos");
        return 1;
    }

    /* 获取系统状态 / Get system status */
    struct ai_system_status status;
    if (ioctl(fd, AI_IOCTL_GET_STATUS, &status) == 0) {
        printf("Models loaded: %u\n", status.models_loaded);
    }

    /* 取消任务 / Cancel a task */
    uint64_t task_id = 123;
    if (ioctl(fd, AI_IOCTL_CANCEL_TASK, &task_id) == 0) {
        printf("Task %llu cancelled\n", task_id);
    }

    close(fd);
    return 0;
}
```

### 10.4 设备文件操作 / Device File Operations

```c
static const struct file_operations ainos_fops = {
    .owner          = THIS_MODULE,
    .open           = ainos_device_open,
    .release        = ainos_device_release,
    .unlocked_ioctl = ainos_device_ioctl,
};

static struct miscdevice ainos_device = {
    .minor = MISC_DYNAMIC_MINOR,
    .name  = "ainos",
    .fops  = &ainos_fops,
};
```

---

## 11. Complete Error Reference / 完整错误码参考

### 11.1 错误码定义 / Error Code Definitions

```c
#define AI_ERR_SUCCESS          0      /* 成功 / Success */
#define AI_ERR_GENERAL          -1     /* 通用错误 / General error */
#define AI_ERR_INVALID_PARAM    -2     /* 参数无效 / Invalid parameter */
#define AI_ERR_MODEL_NOT_FOUND  -3     /* 模型未找到 / Model not found */
#define AI_ERR_MODEL_LOAD_FAIL  -4     /* 模型加载失败 / Model load failed */
#define AI_ERR_OUT_OF_MEMORY    -5     /* 内存不足 / Out of memory */
#define AI_ERR_TASK_QUEUE_FULL  -6     /* 任务队列已满 / Task queue full */
#define AI_ERR_NOT_SUPPORTED    -7     /* 不支持的操作 / Not supported */
#define AI_ERR_PERMISSION       -8     /* 权限不足 / Permission denied */
#define AI_ERR_TIMEOUT          -9     /* 操作超时 / Timeout */
#define AI_ERR_THERMAL_THROTTLE -10    /* 热降频 / Thermal throttling */
```

### 11.2 错误码与系统调用映射 / Error Code to Syscall Mapping

| 错误码 / Error Code | 值 / Value | 450 | 451 | 452 | 453 | 454 | 455 | 456 | 457 |
|---|---|---|---|---|---|---|---|---|---|
| `AI_ERR_SUCCESS` | 0 | x | x | x | x | x | x | x | x |
| `AI_ERR_GENERAL` | -1 | x | x | x | x | x | x | x | x |
| `AI_ERR_INVALID_PARAM` | -2 | x | x | x | x | x | x | x | x |
| `AI_ERR_MODEL_NOT_FOUND` | -3 | | | | x | x | | | |
| `AI_ERR_MODEL_LOAD_FAIL` | -4 | | | | x | | | | |
| `AI_ERR_OUT_OF_MEMORY` | -5 | x | x | x | | | x | x | |
| `AI_ERR_TASK_QUEUE_FULL` | -6 | x | | | | | | | |
| `AI_ERR_NOT_SUPPORTED` | -7 | x | | | | | | | |
| `AI_ERR_PERMISSION` | -8 | x | | | | | | | |
| `AI_ERR_TIMEOUT` | -9 | x | | | | | | x | |
| `AI_ERR_THERMAL_THROTTLE` | -10 | x | | | | | | | |

### 11.3 详细错误说明 / Detailed Error Descriptions

#### AI_ERR_GENERAL (-1)
- **说明**: 未分类的通用错误 / Unclassified general error
- **可能原因**: 内部内核模块错误，硬件故障 / Internal kernel module error, hardware fault
- **处理建议**: 检查内核日志 (`dmesg`) / Check kernel logs (`dmesg`)

#### AI_ERR_INVALID_PARAM (-2)
- **说明**: 传递给系统调用的参数无效 / Invalid parameters passed to syscall
- **可能原因**: NULL 指针、超出范围的值、无效的嵌入维度 / NULL pointer, out-of-range value, invalid embedding dimension
- **处理建议**: 验证所有输入参数 / Validate all input parameters

#### AI_ERR_MODEL_NOT_FOUND (-3)
- **说明**: 请求的模型未找到 / Requested model not found
- **可能原因**: 模型文件路径错误、模型未加载 / Wrong model file path, model not loaded
- **处理建议**: 验证模型路径，先调用 `sys_ai_model_load` / Verify model path, call `sys_ai_model_load` first

#### AI_ERR_MODEL_LOAD_FAIL (-4)
- **说明**: 模型加载失败 / Model load failed
- **可能原因**: 模型表已满 (最多 32 个模型)、文件权限错误 / Model table full (max 32), file permission error
- **处理建议**: 卸载不需要的模型，检查文件权限 / Unload unused models, check file permissions

#### AI_ERR_OUT_OF_MEMORY (-5)
- **说明**: 内核内存不足 / Kernel memory insufficient
- **可能原因**: 系统内存压力过大、上下文表已满 (1024 条目) / System memory pressure, context table full (1024 entries)
- **处理建议**: 释放系统内存，减少并发操作 / Free system memory, reduce concurrent operations

#### AI_ERR_TASK_QUEUE_FULL (-6)
- **说明**: 推理任务队列已满 / Inference task queue full
- **可能原因**: 并发推理请求过多 / Too many concurrent inference requests
- **处理建议**: 等待当前任务完成后再提交 / Wait for current tasks to complete

#### AI_ERR_NOT_SUPPORTED (-7)
- **说明**: 请求的操作不被支持 / Requested operation not supported
- **可能原因**: 不支持的功能特性 / Unsupported feature
- **处理建议**: 检查内核模块版本 / Check kernel module version

#### AI_ERR_PERMISSION (-8)
- **说明**: 权限不足 / Permission denied
- **可能原因**: 调用进程没有足够的权限 / Calling process lacks sufficient privileges
- **处理建议**: 以 root 或适当权限运行 / Run as root or with appropriate permissions

#### AI_ERR_TIMEOUT (-9)
- **说明**: 操作超时 / Operation timed out
- **可能原因**: 上下文条目已过期 (TTL 到期)、推理耗时过长 / Context entry expired (TTL reached), inference took too long
- **处理建议**: 增加超时时间，检查系统负载 / Increase timeout, check system load

#### AI_ERR_THERMAL_THROTTLE (-10)
- **说明**: CPU 温度过高，正在降频 / CPU temperature too high, throttling active
- **可能原因**: 散热不足，持续高负载 / Insufficient cooling, sustained high load
- **处理建议**: 降低推理频率，改善散热 / Reduce inference frequency, improve cooling

---

## 12. Power Policy / 电源策略

### 12.1 电源策略模式 / Power Policy Modes

```c
enum ai_power_mode {
    AI_POWER_MAX       = 0,  /* < 70°C: 全速模式 (AVX-256, 4核推理, FP32) */
    AI_POWER_BALANCED  = 1,  /* 70-85°C: 平衡模式 (AVX-128, 2核推理, FP16) */
    AI_POWER_EFFICIENT = 2,  /* > 85°C: 节能模式 (NEON/标量, 1核推理, INT8) */
    AI_POWER_EMERGENCY = 3,  /* > 95°C: 紧急模式 (仅标量, 1核推理, INT4) */
};
```

### 12.2 电源策略状态结构体 / Power Policy Status Structure

```c
struct ai_power_status {
    enum ai_power_mode  current_mode;           /* 当前策略模式 */
    uint32_t            cpu_temp;               /* 当前 CPU 温度 (毫摄氏度) */
    uint32_t            cpu_temp_decicelsius;   /* 十分之一摄氏度 */
    uint32_t            recommended_threads;    /* 推荐推理线程数 */
    uint8_t             throttle_active;        /* 是否正在降频 */
    uint8_t             sensor_available;       /* 温度传感器是否可用 */
};
```

### 12.3 电源策略 IOCTL / Power Policy IOCTLs

```c
#define AI_IOCTL_GET_POWER_MODE _IOR(AI_IOC_MAGIC, 7, struct ai_power_status)
#define AI_IOCTL_SET_POWER_MODE _IOW(AI_IOC_MAGIC, 8, enum ai_power_mode)
#define AI_IOCTL_GET_TEMP       _IOR(AI_IOC_MAGIC, 9, uint32_t)
```

### 12.4 温度阈值 / Temperature Thresholds

| 模式 / Mode | 温度范围 / Temp Range | 精度 / Precision | 线程数 / Threads | 指令集 / ISA |
|---|---|---|---|---|
| `AI_POWER_MAX` | < 70°C | FP32 | 4 | AVX-256 |
| `AI_POWER_BALANCED` | 70-85°C | FP16 | 2 | AVX-128 |
| `AI_POWER_EFFICIENT` | 85-95°C | INT8 | 1 | NEON/Scalar |
| `AI_POWER_EMERGENCY` | > 95°C | INT4 | 1 | Scalar only |

### 12.5 温度传感器 / Temperature Sensor

通过 `/sys/class/thermal/thermal_zone0/temp` 读取 CPU 温度，返回值为毫摄氏度（millidegrees Celsius）。

---

## 附录 / Appendix

### A. 内核模块信息 / Kernel Module Information

```c
MODULE_LICENSE("GPL");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("Ainos AI System Calls");
MODULE_VERSION("0.1.0");
```

### B. 编译 / Build

```bash
# 作为内核模块编译 / Build as kernel module
make -C /lib/modules/$(uname -r)/build M=$(pwd) modules

# 加载模块 / Load module
insmod ai-syscalls-main.ko

# 验证 / Verify
ls /dev/ainos
dmesg | grep ainos
```

### C. ABI 版本历史 / ABI Version History

| 版本 / Version | 日期 / Date | 变更 / Changes |
|---|---|---|
| 0.1.0 | 2024 | 初始版本 / Initial release |