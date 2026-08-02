#ifndef POLICY_ENGINE_H
#define POLICY_ENGINE_H

#include "ainos/ai_policy.h"

/* 内部规则结构 */
typedef struct ai_policy_rule {
    ai_policy_layer_t layer;
    ai_policy_decision_t decision;
    char action[64];
    char condition_key[64];
    char condition_val[128];
    int is_negated; /* 1 for !=, 0 for == */
    struct ai_policy_rule *next;
} ai_policy_rule_t;

/* 缓存节点 */
typedef struct ai_cache_node {
    uint64_t key;
    ai_policy_decision_t decision;
    struct ai_cache_node *next;
} ai_cache_node_t;

/* ============================================
 * Capability-based 权限控制
 * 类型定义在 ai_policy.h 公共头文件中
 * ============================================ */

/* 兼容性别名 - 内部代码继续使用 CAP_ 前缀 */
#define CAP_INFERENCE    AI_CAP_INFERENCE
#define CAP_MODEL_LOAD   AI_CAP_MODEL_LOAD
#define CAP_MODEL_UNLOAD AI_CAP_MODEL_UNLOAD
#define CAP_CONTEXT_RW   AI_CAP_CONTEXT_RW
#define CAP_SYSTEM_STAT  AI_CAP_SYSTEM_STAT
#define CAP_CONFIG_READ  AI_CAP_CONFIG_READ
#define CAP_CONFIG_WRITE AI_CAP_CONFIG_WRITE
#define CAP_AUDIT_VIEW   AI_CAP_AUDIT_VIEW
#define CAP_NET_ACCESS   AI_CAP_NET_ACCESS
#define CAP_MAX          AI_CAP_MAX

/* Capability 名称映射 */
static const char* const CAP_NAMES[] = {
    [AI_CAP_INFERENCE]    = "inference",
    [AI_CAP_MODEL_LOAD]   = "model.load",
    [AI_CAP_MODEL_UNLOAD] = "model.unload",
    [AI_CAP_CONTEXT_RW]   = "context.rw",
    [AI_CAP_SYSTEM_STAT]  = "system.stat",
    [AI_CAP_CONFIG_READ]  = "config.read",
    [AI_CAP_CONFIG_WRITE] = "config.write",
    [AI_CAP_AUDIT_VIEW]   = "audit.view",
    [AI_CAP_NET_ACCESS]   = "net.access",
};

/* 转化为 action 字符串 */
static inline const char* capability_to_action(ai_capability_t cap) {
    if (cap < AI_CAP_MAX) return CAP_NAMES[cap];
    return "unknown";
}

/* 从 action 字符串解析 capability */
static inline ai_capability_t action_to_capability(const char *action) {
    for (int i = 0; i < AI_CAP_MAX; i++) {
        if (strcmp(action, CAP_NAMES[i]) == 0) return (ai_capability_t)i;
    }
    return AI_CAP_MAX; /* 未知 */
}

/* 引擎状态 */
typedef struct {
    ai_policy_rule_t *rules[AI_LAYER_MAX];
    ai_cache_node_t *cache[256];
    int cache_size;
    ai_policy_audit_cb_t audit_cb;
    int is_cut_off;

    /* Capability-based 策略 */
    ai_capability_bitmap_t default_caps;       /* 默认允许的 capability */
    ai_capability_bitmap_t system_caps;        /* 系统级强制 capability */
    ai_capability_bitmap_t emergency_deny_caps; /* 紧急切断时禁止的 capability */
} ai_policy_engine_t;

int engine_init(ai_policy_engine_t *engine);
void engine_destroy(ai_policy_engine_t *engine);
int engine_parse_apl(ai_policy_engine_t *engine, const char *apl_text);
ai_policy_decision_t engine_evaluate(ai_policy_engine_t *engine, const ai_policy_context_t *ctx);
void engine_flush_cache(ai_policy_engine_t *engine);

/* Capability-based 扩展 API */
int engine_check_capability(ai_policy_engine_t *engine, const ai_policy_context_t *ctx, ai_capability_t cap);
void engine_set_default_caps(ai_policy_engine_t *engine, ai_capability_bitmap_t caps);
void engine_set_emergency_deny_caps(ai_policy_engine_t *engine, ai_capability_bitmap_t caps);

#endif /* POLICY_ENGINE_H */