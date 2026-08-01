#include "enforcer.h"
#include "../policy-engine/policy_engine.h"
#include "../policy-db/policy_db.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static ai_policy_engine_t g_engine;
static ai_policy_audit_cb_t g_audit_cb = NULL;

static void generate_audit(const ai_policy_context_t *ctx, ai_policy_decision_t dec, const char *reason) {
    if (!g_audit_cb) return;
    ai_policy_audit_t audit;
    audit.timestamp = (uint64_t)time(NULL);
    audit.decision = dec;
    audit.ctx = *ctx;
    strncpy(audit.reason, reason, sizeof(audit.reason) - 1);
    g_audit_cb(&audit);
}

int enforcer_init(const char *db_path, const char *default_profile_path) {
    if (engine_init(&g_engine) != 0) return -1;
    if (pdb_init(db_path) != 0) return -1;

    /* 加载默认策略 */
    FILE *f = fopen(default_profile_path, "r");
    if (f) {
        fseek(f, 0, SEEK_END);
        long fsize = ftell(f);
        fseek(f, 0, SEEK_SET);
        char *buffer = malloc(fsize + 1);
        if (buffer) {
            fread(buffer, 1, fsize, f);
            buffer[fsize] = 0;
            engine_parse_apl(&g_engine, buffer);
            free(buffer);
        }
        fclose(f);
    }
    return 0;
}

void enforcer_destroy(void) {
    engine_destroy(&g_engine);
    pdb_destroy();
}

int enforcer_intercept(const ai_policy_context_t *ctx, ai_policy_decision_t *decision) {
    if (g_engine.is_cut_off) {
        *decision = AI_POLICY_DENY;
        generate_audit(ctx, AI_POLICY_DENY, "Emergency cut-off active");
        return 0;
    }

    *decision = engine_evaluate(&g_engine, ctx);
    
    const char *reason = (*decision == AI_POLICY_ALLOW) ? "Policy matched" : 
                         (*decision == AI_POLICY_ASK) ? "User consent required" : "Default deny";
    generate_audit(ctx, *decision, reason);
    
    return 0;
}

void enforcer_set_audit_callback(ai_policy_audit_cb_t cb) {
    g_audit_cb = cb;
    g_engine.audit_cb = cb;
}

/* 暴露给公共 API 的包装 */
int ai_policy_init(void) { return 0; } /* 实际由 enforcer_init 处理 */
void ai_policy_destroy(void) { enforcer_destroy(); }
int ai_policy_check_permission(const ai_policy_context_t *ctx, ai_policy_decision_t *decision) {
    return enforcer_intercept(ctx, decision);
}
void ai_policy_register_audit_cb(ai_policy_audit_cb_t cb) { enforcer_set_audit_callback(cb); }
void ai_policy_emergency_cut_off(void) { g_engine.is_cut_off = 1; engine_flush_cache(&g_engine); }
void ai_policy_resume(void) { g_engine.is_cut_off = 0; }