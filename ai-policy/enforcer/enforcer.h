#ifndef ENFORCER_H
#define ENFORCER_H

#include "ainos/ai_policy.h"

int enforcer_init(const char *db_path, const char *default_profile_path);
void enforcer_destroy(void);
int enforcer_intercept(const ai_policy_context_t *ctx, ai_policy_decision_t *decision);
int enforcer_check_capability(const ai_policy_context_t *ctx, ai_capability_t cap);
void enforcer_set_audit_callback(ai_policy_audit_cb_t cb);

#endif