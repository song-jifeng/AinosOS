#ifndef AINOS_AI_POLICY_H
#define AINOS_AI_POLICY_H

#ifdef __KERNEL__
#include <linux/types.h>
#else
#include <stdint.h>
#include <stddef.h>
#endif

/* 决策结果 */
typedef enum {
    AI_POLICY_DENY = 0,
    AI_POLICY_ALLOW = 1,
    AI_POLICY_ASK = 2
} ai_policy_decision_t;

/* 策略层级 (system→user→app→session) */
typedef enum {
    AI_LAYER_SYSTEM = 0,
    AI_LAYER_USER = 1,
    AI_LAYER_APP = 2,
    AI_LAYER_SESSION = 3,
    AI_LAYER_MAX = 4
} ai_policy_layer_t;

/* 权限请求上下文 */
typedef struct {
    uint32_t uid;
    uint32_t pid;
    uint32_t session_id;
    char app_id[64];
    char action[64];
    char resource[128];
    char context[256]; /* 附加上下文，如 user_role, session_type */
} ai_policy_context_t;

/* 审计日志条目 */
typedef struct {
    uint64_t timestamp;
    ai_policy_decision_t decision;
    ai_policy_context_t ctx;
    char reason[128];
} ai_policy_audit_t;

/* 审计回调函数 */
typedef void (*ai_policy_audit_cb_t)(const ai_policy_audit_t *audit);

/* 公共 API */
int ai_policy_init(void);
void ai_policy_destroy(void);
int ai_policy_check_permission(const ai_policy_context_t *ctx, ai_policy_decision_t *decision);
int ai_policy_load_from_file(const char *filepath);
int ai_policy_load_from_buffer(const char *buffer, size_t len);
void ai_policy_register_audit_cb(ai_policy_audit_cb_t cb);
void ai_policy_emergency_cut_off(void);
void ai_policy_resume(void);

#endif /* AINOS_AI_POLICY_H */