// SPDX-License-Identifier: GPL-2.0
/*
 * Ainos OS - AI 安全策略公共接口
 *
 * 本文件是 Ainos OS 内核模块的一部分。
 * 内核模块 (kernel/, ai-fs/, ai-policy/) 使用 GPL-2.0 许可证，
 * 详见内核源码目录中的 COPYING 文件。
 *
 * 当在 __KERNEL__ 上下文中使用时，GPL-2.0 许可证适用。
 * 用户空间 (userspace) 使用不受 GPL 传染性限制。
 *
 * 人类维护者: song-jifeng <song-jifeng@ainos.org>
 */
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

/* Capability 类型 (细粒度权限控制) */
typedef enum {
    AI_CAP_INFERENCE    = 0,  /* 执行推理 */
    AI_CAP_MODEL_LOAD   = 1,  /* 加载模型 */
    AI_CAP_MODEL_UNLOAD = 2,  /* 卸载模型 */
    AI_CAP_CONTEXT_RW   = 3,  /* 上下文读写 */
    AI_CAP_SYSTEM_STAT  = 4,  /* 系统状态查询 */
    AI_CAP_CONFIG_READ  = 5,  /* 配置读取 */
    AI_CAP_CONFIG_WRITE = 6,  /* 配置修改 */
    AI_CAP_AUDIT_VIEW   = 7,  /* 审计日志查看 */
    AI_CAP_NET_ACCESS   = 8,  /* 网络访问 */
    AI_CAP_MAX          = 9
} ai_capability_t;

/* Capability 位图 */
typedef uint64_t ai_capability_bitmap_t;

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
int ai_policy_check_capability(const ai_policy_context_t *ctx, ai_capability_t cap);
int ai_policy_load_from_file(const char *filepath);
int ai_policy_load_from_buffer(const char *buffer, size_t len);
void ai_policy_register_audit_cb(ai_policy_audit_cb_t cb);
void ai_policy_emergency_cut_off(void);
void ai_policy_resume(void);

#endif /* AINOS_AI_POLICY_H */