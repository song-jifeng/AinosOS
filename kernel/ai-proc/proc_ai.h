#ifndef AINOS_PROC_AI_H
#define AINOS_PROC_AI_H

#include <linux/types.h>

/* /proc/ai 文件节点 */
#define PROC_AI_DIR     "ai"
#define PROC_AI_STATUS  "status"
#define PROC_AI_INFER   "infer"
#define PROC_AI_EMBED   "embed"
#define PROC_AI_MODELS  "models"
#define PROC_AI_CONFIG  "config"

/* 缓冲区大小 */
#define PROC_AI_BUF_SIZE 4096

/* 推理请求结构 */
struct proc_ai_infer_req {
    char prompt[PROC_AI_BUF_SIZE];
    size_t len;
};

/* 推理结果结构 */
struct proc_ai_infer_resp {
    char output[PROC_AI_BUF_SIZE];
    size_t len;
    int tokens;
    long long inference_ms;
};

/* 导出函数 */
int proc_ai_infer(const char *prompt, char *output, size_t output_size);
int proc_ai_models_available(void);

#endif /* AINOS_PROC_AI_H */