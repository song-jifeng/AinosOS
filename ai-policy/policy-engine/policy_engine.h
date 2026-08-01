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

/* 引擎状态 */
typedef struct {
    ai_policy_rule_t *rules[AI_LAYER_MAX];
    ai_cache_node_t *cache[256];
    int cache_size;
    ai_policy_audit_cb_t audit_cb;
    int is_cut_off;
} ai_policy_engine_t;

int engine_init(ai_policy_engine_t *engine);
void engine_destroy(ai_policy_engine_t *engine);
int engine_parse_apl(ai_policy_engine_t *engine, const char *apl_text);
ai_policy_decision_t engine_evaluate(ai_policy_engine_t *engine, const ai_policy_context_t *ctx);
void engine_flush_cache(ai_policy_engine_t *engine);

#endif