// Ainos OS - AI 应用 SDK 头文件
// 支持 Windows 和 Linux 双平台
#ifndef AINOS_H
#define AINOS_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* 基础类型与错误码 */
#define AINOS_OK                  0
#define AINOS_ERR_INVALID_PARAM  -1
#define AINOS_ERR_NOT_INIT       -2
#define AINOS_ERR_MODEL_NOT_FOUND -3
#define AINOS_ERR_OUT_OF_MEMORY  -4
#define AINOS_ERR_TIMEOUT        -5
#define AINOS_ERR_CONNECT        -6
#define AINOS_ERR_INTERNAL       -99

#define AINOS_SDK_VERSION "1.0.0"

/* 类型定义 */

/* Opaque 上下文 */
typedef struct ainos_ctx ainos_ctx;

/* 推理选项 */
typedef struct {
    float temperature;
    float top_p;
    int max_tokens;
    int num_threads;
    const char* session_id;
} ainos_infer_opts;

#define AINOS_INFER_OPTS_DEFAULT {0.7f, 0.9f, 512, 4, NULL}

/* 推理响应 */
typedef struct {
    char* output;
    int tokens_generated;
    long long inference_ms;
    char* source; /* "local" or "cloud" */
    int error_code;
    char* error_message;
} ainos_resp;

/* 系统信息 */
typedef struct {
    uint32_t models_loaded;
    uint32_t tasks_pending;
    uint32_t tasks_running;
    uint64_t total_inferences;
    uint64_t total_tokens;
    uint64_t uptime_ms;
    int network_available;
    int accelerator;
    char version[64];
} ainos_sys_info;

/* 核心 API */

/* 初始化 SDK，server_addr 为 "host:port" (如 "127.0.0.1:9500") 或 Unix socket 路径 */
ainos_ctx* ainos_init(const char* server_addr);

/* 连接 AI 守护进程 */
int ainos_connect(ainos_ctx* ctx);

/* 执行推理请求 */
ainos_resp* ainos_infer(ainos_ctx* ctx, const char* model,
                        const char* prompt, ainos_infer_opts* opts);

/* 获取系统状态 */
ainos_resp* ainos_get_info(ainos_ctx* ctx);

/* 释放响应 */
void ainos_resp_free(ainos_resp* resp);

/* 断开连接并销毁上下文 */
void ainos_destroy(ainos_ctx* ctx);

/* 高级 API (可选) */

/* 获取嵌入向量 */
ainos_resp* ainos_embed(ainos_ctx* ctx, const char* text);

/* 语义搜索 */
ainos_resp* ainos_search(ainos_ctx* ctx, const char* query, int max_results);

/* 上下文管理 */
ainos_resp* ainos_ctx_store(ainos_ctx* ctx, const char* key, const char* value);
ainos_resp* ainos_ctx_get(ainos_ctx* ctx, const char* key);

/* 模型管理 */
int ainos_model_load(ainos_ctx* ctx, const char* path);
int ainos_model_unload(ainos_ctx* ctx, const char* model_id);

#ifdef __cplusplus
}
#endif

#endif // AINOS_H