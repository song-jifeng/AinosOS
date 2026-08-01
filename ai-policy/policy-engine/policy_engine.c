#include "policy_engine.h"
#include <string.h>

/* 内核/用户态内存与字符串操作抽象 */
#ifdef __KERNEL__
#include <linux/slab.h>
#include <linux/string.h>
#define PE_MALLOC(s) kmalloc(s, GFP_KERNEL)
#define PE_FREE(p) kfree(p)
#define PE_STRNCPY(d, s, n) strncpy(d, s, n)
#else
#include <stdlib.h>
#include <string.h>
#define PE_MALLOC(s) malloc(s)
#define PE_FREE(p) free(p)
#define PE_STRNCPY(d, s, n) strncpy(d, s, n)
#endif

static const char *skip_space_comment(const char *p) {
    while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') p++;
    if (*p == '#') {
        while (*p && *p != '\n') p++;
        return skip_space_comment(p);
    }
    return p;
}

static int parse_identifier(const char **p, char *buf, size_t buf_sz) {
    size_t i = 0;
    const char *start = *p;
    while ((*start >= 'a' && *start <= 'z') || (*start >= 'A' && *start <= 'Z') || 
           (*start >= '0' && *start <= '9') || *start == '_') {
        if (i < buf_sz - 1) buf[i++] = *start;
        start++;
    }
    buf[i] = '\0';
    *p = start;
    return (i > 0) ? 0 : -1;
}

static int parse_string(const char **p, char *buf, size_t buf_sz) {
    if (**p != '"') return -1;
    (*p)++;
    size_t i = 0;
    while (**p && **p != '"') {
        if (i < buf_sz - 1) buf[i++] = **p;
        (*p)++;
    }
    buf[i] = '\0';
    if (**p == '"') (*p)++;
    return 0;
}

int engine_parse_apl(ai_policy_engine_t *engine, const char *text) {
    const char *p = text;
    ai_policy_layer_t current_layer = AI_LAYER_SYSTEM;

    while (*p) {
        p = skip_space_comment(p);
        if (!*p) break;

        if (strncmp(p, "layer", 5) == 0) {
            p += 5;
            p = skip_space_comment(p);
            char layer_name[32];
            if (parse_identifier(&p, layer_name, sizeof(layer_name)) != 0) return -1;
            
            if (strcmp(layer_name, "system") == 0) current_layer = AI_LAYER_SYSTEM;
            else if (strcmp(layer_name, "user") == 0) current_layer = AI_LAYER_USER;
            else if (strcmp(layer_name, "app") == 0) current_layer = AI_LAYER_APP;
            else if (strcmp(layer_name, "session") == 0) current_layer = AI_LAYER_SESSION;
            else return -1;

            p = skip_space_comment(p);
            if (*p != '{') return -1;
            p++;
        } else if (*p == '}') {
            p++;
        } else {
            /* 解析规则: allow/deny/ask action [if key == "value"]; */
            ai_policy_decision_t dec;
            if (strncmp(p, "allow", 5) == 0) { dec = AI_POLICY_ALLOW; p += 5; }
            else if (strncmp(p, "deny", 4) == 0) { dec = AI_POLICY_DENY; p += 4; }
            else if (strncmp(p, "ask", 3) == 0) { dec = AI_POLICY_ASK; p += 3; }
            else return -1;

            p = skip_space_comment(p);
            ai_policy_rule_t *rule = (ai_policy_rule_t *)PE_MALLOC(sizeof(ai_policy_rule_t));
            if (!rule) return -1;
            memset(rule, 0, sizeof(*rule));
            
            rule->layer = current_layer;
            rule->decision = dec;
            parse_identifier(&p, rule->action, sizeof(rule->action));

            p = skip_space_comment(p);
            if (strncmp(p, "if", 2) == 0) {
                p += 2;
                p = skip_space_comment(p);
                parse_identifier(&p, rule->condition_key, sizeof(rule->condition_key));
                p = skip_space_comment(p);
                if (*p == '!') { rule->is_negated = 1; p++; }
                if (*p == '=') p++;
                if (*p == '=') p++;
                p = skip_space_comment(p);
                parse_string(&p, rule->condition_val, sizeof(rule->condition_val));
            }

            p = skip_space_comment(p);
            if (*p == ';') p++;

            /* 插入规则链表头部 */
            rule->next = engine->rules[current_layer];
            engine->rules[current_layer] = rule;
        }
    }
    return 0;
}

static int match_condition(const ai_policy_rule_t *rule, const ai_policy_context_t *ctx) {
    if (rule->condition_key[0] == '\0') return 1; /* 无条件 */
    
    /* 在 context 中查找 key="value" 或简单的键值匹配 */
    /* 简化实现：直接比较 context 字符串是否包含条件 */
    char search_buf[256];
    int len = snprintf(search_buf, sizeof(search_buf), "%s=\"%s\"", rule->condition_key, rule->condition_val);
    int found = (strstr(ctx->context, search_buf) != NULL);
    
    return rule->is_negated ? !found : found;
}

ai_policy_decision_t engine_evaluate(ai_policy_engine_t *engine, const ai_policy_context_t *ctx) {
    if (engine->is_cut_off) return AI_POLICY_DENY;

    /* 四层匹配: system -> user -> app -> session */
    for (int i = 0; i < AI_LAYER_MAX; i++) {
        ai_policy_rule_t *rule = engine->rules[i];
        while (rule) {
            if (strcmp(rule->action, ctx->action) == 0 || strcmp(rule->action, "*") == 0) {
                if (match_condition(rule, ctx)) {
                    return rule->decision;
                }
            }
            rule = rule->next;
        }
    }
    return AI_POLICY_DENY; /* 默认拒绝 */
}

void engine_flush_cache(ai_policy_engine_t *engine) {
    for (int i = 0; i < 256; i++) {
        ai_cache_node_t *node = engine->cache[i];
        while (node) {
            ai_cache_node_t *next = node->next;
            PE_FREE(node);
            node = next;
        }
        engine->cache[i] = NULL;
    }
    engine->cache_size = 0;
}

int engine_init(ai_policy_engine_t *engine) {
    memset(engine, 0, sizeof(*engine));
    return 0;
}

void engine_destroy(ai_policy_engine_t *engine) {
    for (int i = 0; i < AI_LAYER_MAX; i++) {
        ai_policy_rule_t *rule = engine->rules[i];
        while (rule) {
            ai_policy_rule_t *next = rule->next;
            PE_FREE(rule);
            rule = next;
        }
    }
    engine_flush_cache(engine);
}