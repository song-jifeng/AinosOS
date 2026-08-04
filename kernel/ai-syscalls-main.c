// SPDX-License-Identifier: GPL-2.0
/*
 * Ainos OS - AI 系统调用实现
 * ==========================================
 * 实现 AI 相关的系统调用：
 *   - sys_ai_inference:       AI 推理请求 (450)
 *   - sys_ai_embedding:       文本嵌入 (451)
 *   - sys_ai_semantic_search: 语义搜索 (452)
 *   - sys_ai_model_load:      加载模型 (453)
 *   - sys_ai_model_unload:    卸载模型 (454)
 *   - sys_ai_context_store:   存储上下文 (455)
 *   - sys_ai_context_retrieve: 检索上下文 (456)
 *   - sys_ai_status:          获取系统状态 (457)
 *
 * Copyright (C) 2024 Ainos OS Team
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/syscalls.h>
#include <linux/uaccess.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/slab.h>
#include <linux/vmalloc.h>
#include <linux/ioctl.h>
#include <linux/string.h>
#include <linux/mutex.h>
#include <linux/spinlock.h>
#include <linux/sort.h>
#include <linux/file.h>
#include <linux/ktime.h>

#include "ainos/ai-abi.h"

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("Ainos AI System Calls");
MODULE_VERSION("0.1.0");

/* ============================================
 * 外部符号引用
 * ============================================ */

/* AI 调度器接口 */
extern int ai_sched_submit(struct ai_inference_req *req,
                            struct ai_inference_resp *resp);
extern int ai_sched_submit_async(struct ai_inference_req *req,
                                  uint64_t *task_id);
extern int ai_sched_cancel(uint64_t task_id);
extern void ai_sched_get_status(struct ai_system_status *status);

/* 向量加速模块接口 */
extern float ai_vector_dot_product(int n, const float *a, const float *b);

/* ============================================
 * 辅助函数
 * ============================================ */

/* 有效的嵌入维度列表 */
static const size_t ai_valid_dims[] = {
    128, 256, 512, 768, 1024, 2048, 4096
};

static bool is_valid_embedding_dim(size_t dim)
{
    size_t i;

    for (i = 0; i < ARRAY_SIZE(ai_valid_dims); i++) {
        if (ai_valid_dims[i] == dim)
            return true;
    }
    return false;
}

/* 浮点数平方根 (Newton's method, 20 次迭代足够达到 float 精度) */
static inline float ai_float_sqrt(float x)
{
    float guess;
    int i;

    if (x <= 0.0f)
        return 0.0f;

    guess = x;
    for (i = 0; i < 20; i++)
        guess = (guess + x / guess) * 0.5f;

    return guess;
}

/* ============================================
 * 嵌入向量计算
 * ============================================ */

/*
 * 确定性哈希权重生成器
 * 为每个 (dim_idx, pos) 对生成固定的 [-1.0, 1.0) 权重
 */
static inline float embedding_weight(size_t dim_idx, size_t pos)
{
    uint32_t h;

    h = (uint32_t)(dim_idx * 2654435761U + pos * 2246822519U);
    h = (h ^ (h >> 16)) * 0x45d9f3b;
    h = (h ^ (h >> 16)) * 0x45d9f3b;
    h = h ^ (h >> 16);

    return ((float)(h % 2001) / 1000.0f) - 1.0f;
}

/*
 * compute_embedding - 计算输入浮点数组的嵌入向量
 *
 * 使用随机投影 (Random Projection) 将输入投影到目标维度空间。
 * 权重矩阵通过确定性哈希函数生成，无需存储。
 *
 * 利用向量加速模块的 dot_product 进行高效计算。
 */
static int compute_embedding(const float *input, size_t input_len,
                              float *embedding, size_t embedding_dim)
{
    float *weights;
    size_t i, j;

    if (!input || !embedding || input_len == 0 || embedding_dim == 0)
        return -AI_ERR_INVALID_PARAM;

    weights = kmalloc_array(input_len, sizeof(float), GFP_KERNEL);
    if (!weights)
        return -AI_ERR_OUT_OF_MEMORY;

    for (i = 0; i < embedding_dim; i++) {
        for (j = 0; j < input_len; j++)
            weights[j] = embedding_weight(i, j);

        embedding[i] = ai_vector_dot_product((int)input_len, input, weights);
    }

    kfree(weights);
    return 0;
}

/* ============================================
 * 模型表
 * ============================================ */
#define AI_MAX_MODELS 32

struct ai_model_entry {
    uint64_t model_id;
    char name[AI_MODEL_NAME_MAX];
    char path[AI_MODEL_PATH_MAX];
    bool loaded;
    ktime_t loaded_at;
};

static struct ai_model_entry g_model_table[AI_MAX_MODELS];
static DEFINE_MUTEX(g_model_lock);
static uint64_t g_next_model_id = 1;

/*
 * 向模型表注册一个新模型
 * 验证文件存在，分配空槽，返回模型 ID
 */
static int model_table_add(const char *name, const char *path,
                            uint64_t *model_id)
{
    struct file *f;
    int i;
    int ret;

    /* 验证模型文件存在 */
    f = filp_open(path, O_RDONLY, 0);
    if (IS_ERR(f))
        return -AI_ERR_MODEL_NOT_FOUND;
    filp_close(f, NULL);

    mutex_lock(&g_model_lock);

    /* 查找空槽 */
    for (i = 0; i < AI_MAX_MODELS; i++) {
        if (!g_model_table[i].loaded)
            break;
    }

    if (i >= AI_MAX_MODELS) {
        pr_err("ainos: model table full (max %d)\n", AI_MAX_MODELS);
        ret = -AI_ERR_MODEL_LOAD_FAIL;
        goto out_unlock;
    }

    /* 检查是否已加载同名模型 */
    for (i = 0; i < AI_MAX_MODELS; i++) {
        if (g_model_table[i].loaded &&
            strncmp(g_model_table[i].name, name, AI_MODEL_NAME_MAX - 1) == 0) {
            *model_id = g_model_table[i].model_id;
            pr_info("ainos: model already loaded: id=%llu name=%s\n",
                    *model_id, name);
            ret = 0;
            goto out_unlock;
        }
    }

    /* 重新查找空槽 */
    for (i = 0; i < AI_MAX_MODELS; i++) {
        if (!g_model_table[i].loaded)
            break;
    }

    g_model_table[i].model_id = g_next_model_id++;
    strscpy(g_model_table[i].name, name, sizeof(g_model_table[i].name));
    strscpy(g_model_table[i].path, path, sizeof(g_model_table[i].path));
    g_model_table[i].loaded = true;
    g_model_table[i].loaded_at = ktime_get();

    *model_id = g_model_table[i].model_id;
    pr_info("ainos: model loaded: id=%llu name=%s path=%s\n",
            *model_id, name, path);
    ret = 0;

out_unlock:
    mutex_unlock(&g_model_lock);
    return ret;
}

/* 从模型表卸载模型 */
static int model_table_remove(uint64_t model_id)
{
    int i;

    mutex_lock(&g_model_lock);

    for (i = 0; i < AI_MAX_MODELS; i++) {
        if (g_model_table[i].loaded &&
            g_model_table[i].model_id == model_id) {
            memset(&g_model_table[i], 0, sizeof(g_model_table[i]));
            pr_info("ainos: model unloaded: id=%llu\n", model_id);
            mutex_unlock(&g_model_lock);
            return 0;
        }
    }

    mutex_unlock(&g_model_lock);
    return -AI_ERR_MODEL_NOT_FOUND;
}

/* ============================================
 * 上下文表
 * ============================================ */
#define AI_MAX_CONTEXT_ENTRIES 1024

struct ai_context_entry_kern {
    uint64_t entry_id;
    uint64_t session_id;
    char key[AI_CONTEXT_KEY_MAX];
    uint8_t *value;
    size_t value_len;
    ktime_t created_at;
    uint64_t ttl_ms;   /* 0 表示永不过期 */
    bool used;
};

static struct ai_context_entry_kern g_context_table[AI_MAX_CONTEXT_ENTRIES];
static DEFINE_MUTEX(g_context_lock);
static uint64_t g_next_context_id = 1;

/*
 * 存储上下文条目
 * 如果 session_id + key 已存在则覆盖
 * 支持 TTL (毫秒，0 表示永不过期)
 */
static int context_table_store(uint64_t session_id, const char *key,
                                const uint8_t *value, size_t value_len,
                                uint64_t ttl_ms, uint64_t *entry_id)
{
    struct ai_context_entry_kern *entry = NULL;
    int i;

    mutex_lock(&g_context_lock);

    /* 查找空槽或已存在的 key */
    for (i = 0; i < AI_MAX_CONTEXT_ENTRIES; i++) {
        if (!g_context_table[i].used) {
            if (!entry)
                entry = &g_context_table[i];
        } else if (g_context_table[i].session_id == session_id &&
                   strncmp(g_context_table[i].key, key,
                           AI_CONTEXT_KEY_MAX - 1) == 0) {
            /* 覆盖已存在的条目 */
            entry = &g_context_table[i];
            kvfree(entry->value);
            entry->value = NULL;
            break;
        }
    }

    if (!entry) {
        pr_warn_ratelimited("ainos: context table full (max %d)\n",
                            AI_MAX_CONTEXT_ENTRIES);
        mutex_unlock(&g_context_lock);
        return -AI_ERR_OUT_OF_MEMORY;
    }

    /* 分配值缓冲区 */
    entry->value = kvmalloc(value_len, GFP_KERNEL);
    if (!entry->value) {
        mutex_unlock(&g_context_lock);
        return -AI_ERR_OUT_OF_MEMORY;
    }

    memcpy(entry->value, value, value_len);
    entry->entry_id = g_next_context_id++;
    entry->session_id = session_id;
    strscpy(entry->key, key, AI_CONTEXT_KEY_MAX);
    entry->value_len = value_len;
    entry->created_at = ktime_get();
    entry->ttl_ms = ttl_ms;
    entry->used = true;

    *entry_id = entry->entry_id;
    pr_debug("ainos: context stored: id=%llu session=%llu key=%s len=%zu\n",
             *entry_id, session_id, key, value_len);

    mutex_unlock(&g_context_lock);
    return 0;
}

/*
 * 检索上下文条目
 * 支持按 entry_id 或 (session_id + key) 查询
 * 检查 TTL，已过期条目自动清理并返回 -AI_ERR_TIMEOUT
 */
static int context_table_retrieve(uint64_t session_id, const char *key,
                                   uint64_t entry_id, uint8_t *value,
                                   size_t value_capacity, size_t *value_len)
{
    int i;
    int ret;

    mutex_lock(&g_context_lock);

    for (i = 0; i < AI_MAX_CONTEXT_ENTRIES; i++) {
        if (!g_context_table[i].used)
            continue;

        /* 匹配 entry_id 或 (session_id + key) */
        if ((entry_id > 0 &&
             g_context_table[i].entry_id == entry_id) ||
            (entry_id == 0 &&
             g_context_table[i].session_id == session_id &&
             strncmp(g_context_table[i].key, key,
                     AI_CONTEXT_KEY_MAX - 1) == 0)) {

            /* 检查 TTL */
            if (g_context_table[i].ttl_ms > 0) {
                ktime_t now = ktime_get();
                uint64_t elapsed = ktime_to_ms(
                    ktime_sub(now, g_context_table[i].created_at));

                if (elapsed >= g_context_table[i].ttl_ms) {
                    /* 条目已过期，自动清理 */
                    kvfree(g_context_table[i].value);
                    memset(&g_context_table[i], 0,
                           sizeof(g_context_table[i]));
                    ret = -AI_ERR_TIMEOUT;
                    goto out_unlock;
                }
            }

            /* 复制值 */
            if (value_capacity < g_context_table[i].value_len) {
                ret = -ENOSPC;
                goto out_unlock;
            }

            memcpy(value, g_context_table[i].value,
                   g_context_table[i].value_len);
            *value_len = g_context_table[i].value_len;
            ret = 0;
            goto out_unlock;
        }
    }

    ret = -AI_ERR_INVALID_PARAM;

out_unlock:
    mutex_unlock(&g_context_lock);
    return ret;
}

/* ============================================
 * 语义搜索辅助
 * ============================================ */

struct ai_search_score {
    float score;
    uint32_t index;
};

static int compare_scores_desc(const void *a, const void *b)
{
    const struct ai_search_score *sa =
        (const struct ai_search_score *)a;
    const struct ai_search_score *sb =
        (const struct ai_search_score *)b;

    if (sa->score > sb->score) return -1;
    if (sa->score < sb->score) return 1;
    return 0;
}

/* ============================================
 * AI 设备文件 (/dev/ainos)
 * ============================================ */

static int ainos_device_open(struct inode *inode, struct file *file)
{
    return 0;
}

static int ainos_device_release(struct inode *inode, struct file *file)
{
    return 0;
}

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

/* ============================================
 * 系统调用实现
 * ============================================ */

/* ---- AI 推理 (syscall 450) ---- */
SYSCALL_DEFINE2(ai_inference,
                struct ai_inference_req __user *, req_u,
                struct ai_inference_resp __user *, resp_u)
{
    struct ai_inference_req req;
    struct ai_inference_resp resp;
    int ret;

    if (!req_u || !resp_u)
        return -AI_ERR_INVALID_PARAM;

    if (copy_from_user(&req, req_u, sizeof(req)))
        return -EFAULT;

    memset(&resp, 0, sizeof(resp));
    ret = ai_sched_submit(&req, &resp);

    if (copy_to_user(resp_u, &resp, sizeof(resp)))
        return -EFAULT;

    return ret;
}

/* ---- 嵌入向量 (syscall 451) ---- */
SYSCALL_DEFINE1(ai_embedding, struct ai_embedding_req __user *, req_u)
{
    struct ai_embedding_req req;
    float *input_buf = NULL;
    float *emb_buf = NULL;
    int ret;

    if (!req_u)
        return -AI_ERR_INVALID_PARAM;

    if (copy_from_user(&req, req_u, sizeof(req)))
        return -EFAULT;

    /* 参数验证 */
    if (!req.input || !req.embedding)
        return -AI_ERR_INVALID_PARAM;

    if (req.input_len == 0 || req.input_len > 1048576) /* 最大 1M 元素 */
        return -AI_ERR_INVALID_PARAM;

    if (!is_valid_embedding_dim(req.embedding_dim))
        return -AI_ERR_INVALID_PARAM;

    /* 分配输入缓冲区 */
    input_buf = kmalloc_array(req.input_len, sizeof(float), GFP_KERNEL);
    if (!input_buf)
        return -AI_ERR_OUT_OF_MEMORY;

    /* 从用户空间复制输入 */
    if (copy_from_user(input_buf, req.input,
                       req.input_len * sizeof(float))) {
        ret = -EFAULT;
        goto out_free_input;
    }

    /* 分配嵌入向量缓冲区 */
    emb_buf = kmalloc_array(req.embedding_dim, sizeof(float), GFP_KERNEL);
    if (!emb_buf) {
        ret = -AI_ERR_OUT_OF_MEMORY;
        goto out_free_input;
    }

    /* 计算嵌入向量 */
    ret = compute_embedding(input_buf, req.input_len,
                             emb_buf, req.embedding_dim);
    if (ret)
        goto out_free_emb;

    /* 复制结果到用户空间 */
    if (copy_to_user(req.embedding, emb_buf,
                     req.embedding_dim * sizeof(float))) {
        ret = -EFAULT;
        goto out_free_emb;
    }

    pr_debug("ainos: ai_embedding: input_len=%zu dim=%zu\n",
             req.input_len, req.embedding_dim);
    ret = 0;

out_free_emb:
    kfree(emb_buf);
out_free_input:
    kfree(input_buf);
    return ret;
}

/* ---- 语义搜索 (syscall 452) ---- */
SYSCALL_DEFINE1(ai_semantic_search, struct ai_search_req __user *, req_u)
{
    struct ai_search_req req;
    float *query_buf = NULL;
    float *vec_buf = NULL;
    float query_norm;
    struct ai_search_score *scores = NULL;
    uint32_t i, j;
    uint32_t actual_k;
    int ret;

    if (!req_u)
        return -AI_ERR_INVALID_PARAM;

    if (copy_from_user(&req, req_u, sizeof(req)))
        return -EFAULT;

    /* 参数验证 */
    if (!req.query_emb || !req.database || !req.results)
        return -AI_ERR_INVALID_PARAM;

    if (req.query_dim == 0 || req.query_dim > 4096)
        return -AI_ERR_INVALID_PARAM;

    if (req.vector_dim == 0 || req.vector_dim > 4096)
        return -AI_ERR_INVALID_PARAM;

    if (req.query_dim != req.vector_dim)
        return -AI_ERR_INVALID_PARAM;

    if (req.db_size == 0 || req.db_size > 10000)
        return -AI_ERR_INVALID_PARAM;

    if (req.top_k == 0)
        req.top_k = 10;

    if (req.top_k > req.db_size)
        req.top_k = (uint32_t)req.db_size;

    if (req.top_k > 1000)
        req.top_k = 1000; /* 上限保护 */

    /* 分配查询向量缓冲区 */
    query_buf = kmalloc_array(req.query_dim, sizeof(float), GFP_KERNEL);
    if (!query_buf)
        return -AI_ERR_OUT_OF_MEMORY;

    /* 从用户空间复制查询向量 */
    if (copy_from_user(query_buf, req.query_emb,
                       req.query_dim * sizeof(float))) {
        ret = -EFAULT;
        goto out_free_query;
    }

    /* 计算查询向量范数 */
    query_norm = ai_float_sqrt(
        ai_vector_dot_product((int)req.query_dim, query_buf, query_buf));

    if (query_norm < 0.000001f)
        query_norm = 1.0f; /* 避免除零 */

    /* 分配分数数组 */
    scores = kmalloc_array(req.db_size, sizeof(struct ai_search_score),
                           GFP_KERNEL);
    if (!scores) {
        ret = -AI_ERR_OUT_OF_MEMORY;
        goto out_free_query;
    }

    /* 分配向量缓冲区 (逐向量处理) */
    vec_buf = kmalloc_array(req.vector_dim, sizeof(float), GFP_KERNEL);
    if (!vec_buf) {
        ret = -AI_ERR_OUT_OF_MEMORY;
        goto out_free_scores;
    }

    /* 逐向量计算余弦相似度 */
    for (i = 0; i < req.db_size; i++) {
        const float __user *vec_ptr = req.database + i * req.vector_dim;
        float dot, vec_norm, similarity;

        if (copy_from_user(vec_buf, vec_ptr,
                           req.vector_dim * sizeof(float))) {
            ret = -EFAULT;
            goto out_free_vec;
        }

        dot = ai_vector_dot_product((int)req.vector_dim,
                                     query_buf, vec_buf);
        vec_norm = ai_float_sqrt(
            ai_vector_dot_product((int)req.vector_dim, vec_buf, vec_buf));

        if (vec_norm < 0.000001f)
            vec_norm = 1.0f;

        similarity = dot / (query_norm * vec_norm);

        scores[i].score = similarity;
        scores[i].index = i;
    }

    /* 按相似度降序排序 */
    sort(scores, req.db_size, sizeof(struct ai_search_score),
         compare_scores_desc, NULL);

    /* 取 top-k */
    actual_k = min_t(uint32_t, req.top_k, (uint32_t)req.db_size);

    /* 复制结果到用户空间 */
    for (j = 0; j < actual_k; j++) {
        struct ai_search_result result;
        uint32_t idx = scores[j].index;

        memset(&result, 0, sizeof(result));
        result.score = scores[j].score;
        snprintf(result.path, sizeof(result.path), "vector_%u", idx);
        snprintf(result.snippet, sizeof(result.snippet),
                 "similarity=%.4f", result.score);

        if (copy_to_user(&req.results[j], &result, sizeof(result))) {
            ret = -EFAULT;
            goto out_free_vec;
        }
    }

    pr_debug("ainos: ai_semantic_search: db=%llu dim=%llu top=%u\n",
             req.db_size, req.vector_dim, actual_k);
    ret = 0;

out_free_vec:
    kfree(vec_buf);
out_free_scores:
    kfree(scores);
out_free_query:
    kfree(query_buf);
    return ret;
}

/* ---- 加载模型 (syscall 453) ---- */
SYSCALL_DEFINE2(ai_model_load,
                struct ai_model_load_req __user *, req_u,
                uint64_t __user *, model_id_u)
{
    struct ai_model_load_req req;
    uint64_t model_id;
    int ret;

    if (!req_u || !model_id_u)
        return -AI_ERR_INVALID_PARAM;

    if (copy_from_user(&req, req_u, sizeof(req)))
        return -EFAULT;

    /* 验证名称和路径非空 */
    if (req.name[0] == '\0' || req.path[0] == '\0')
        return -AI_ERR_INVALID_PARAM;

    /* 确保字符串以 null 结尾 */
    req.name[AI_MODEL_NAME_MAX - 1] = '\0';
    req.path[AI_MODEL_PATH_MAX - 1] = '\0';

    ret = model_table_add(req.name, req.path, &model_id);
    if (ret)
        return ret;

    if (copy_to_user(model_id_u, &model_id, sizeof(model_id)))
        return -EFAULT;

    pr_info("ainos: ai_model_load: name=%s path=%s id=%llu\n",
            req.name, req.path, model_id);
    return 0;
}

/* ---- 卸载模型 (syscall 454) ---- */
SYSCALL_DEFINE1(ai_model_unload, uint64_t, model_id)
{
    int ret;

    ret = model_table_remove(model_id);
    if (ret)
        return ret;

    pr_debug("ainos: ai_model_unload: id=%llu\n", model_id);
    return 0;
}

/* ---- 存储上下文 (syscall 455) ---- */
SYSCALL_DEFINE2(ai_context_store,
                struct ai_context_store_req __user *, req_u,
                uint64_t __user *, entry_id_u)
{
    struct ai_context_store_req req;
    uint8_t *value_buf = NULL;
    uint64_t entry_id;
    int ret;

    if (!req_u || !entry_id_u)
        return -AI_ERR_INVALID_PARAM;

    if (copy_from_user(&req, req_u, sizeof(req)))
        return -EFAULT;

    /* 验证参数 */
    req.key[AI_CONTEXT_KEY_MAX - 1] = '\0';
    if (req.key[0] == '\0')
        return -AI_ERR_INVALID_PARAM;

    if (!req.value || req.value_len == 0)
        return -AI_ERR_INVALID_PARAM;

    if (req.value_len > AI_CONTEXT_VAL_MAX)
        return -AI_ERR_INVALID_PARAM;

    /* 分配值缓冲区 */
    value_buf = kmalloc(req.value_len, GFP_KERNEL);
    if (!value_buf)
        return -AI_ERR_OUT_OF_MEMORY;

    /* 从用户空间复制值 */
    if (copy_from_user(value_buf, req.value, req.value_len)) {
        ret = -EFAULT;
        goto out_free_value;
    }

    /* 存储到上下文表 */
    ret = context_table_store(req.session_id, req.key,
                               value_buf, req.value_len,
                               req.ttl_ms, &entry_id);
    if (ret)
        goto out_free_value;

    /* 返回 entry_id 给用户空间 */
    if (copy_to_user(entry_id_u, &entry_id, sizeof(entry_id))) {
        ret = -EFAULT;
        goto out_free_value;
    }

    pr_debug("ainos: ai_context_store: session=%llu key=%s len=%zu ttl=%llu\n",
             req.session_id, req.key, req.value_len, req.ttl_ms);
    ret = 0;

out_free_value:
    kfree(value_buf);
    return ret;
}

/* ---- 检索上下文 (syscall 456) ---- */
SYSCALL_DEFINE1(ai_context_retrieve,
                struct ai_context_retrieve_req __user *, req_u)
{
    struct ai_context_retrieve_req req;
    uint8_t *value_buf = NULL;
    size_t value_len = 0;
    int ret;

    if (!req_u)
        return -AI_ERR_INVALID_PARAM;

    if (copy_from_user(&req, req_u, sizeof(req)))
        return -EFAULT;

    /* 验证参数 */
    if (!req.value || !req.value_len)
        return -AI_ERR_INVALID_PARAM;

    req.key[AI_CONTEXT_KEY_MAX - 1] = '\0';

    if (req.entry_id == 0 && req.key[0] == '\0')
        return -AI_ERR_INVALID_PARAM;

    if (req.value_capacity == 0 || req.value_capacity > AI_CONTEXT_VAL_MAX)
        return -AI_ERR_INVALID_PARAM;

    /* 分配值缓冲区 */
    value_buf = kmalloc(req.value_capacity, GFP_KERNEL);
    if (!value_buf)
        return -AI_ERR_OUT_OF_MEMORY;

    /* 从上下文表检索 */
    ret = context_table_retrieve(req.session_id, req.key,
                                  req.entry_id, value_buf,
                                  req.value_capacity, &value_len);
    if (ret)
        goto out_free_value;

    /* 复制值到用户空间 */
    if (copy_to_user(req.value, value_buf, value_len)) {
        ret = -EFAULT;
        goto out_free_value;
    }

    /* 返回实际长度 */
    if (copy_to_user(req.value_len, &value_len, sizeof(value_len))) {
        ret = -EFAULT;
        goto out_free_value;
    }

    pr_debug("ainos: ai_context_retrieve: session=%llu key=%s id=%llu len=%zu\n",
             req.session_id, req.key, req.entry_id, value_len);

out_free_value:
    kfree(value_buf);
    return ret;
}

/* ---- 获取系统状态 (syscall 457) ---- */
SYSCALL_DEFINE1(ai_status, struct ai_system_status __user *, status)
{
    struct ai_system_status st;

    if (!status)
        return -AI_ERR_INVALID_PARAM;

    ai_sched_get_status(&st);

    /* 补充模型加载数 */
    {
        int i, count = 0;

        mutex_lock(&g_model_lock);
        for (i = 0; i < AI_MAX_MODELS; i++) {
            if (g_model_table[i].loaded)
                count++;
        }
        mutex_unlock(&g_model_lock);
        st.models_loaded = (uint32_t)count;
    }

    if (copy_to_user(status, &st, sizeof(st)))
        return -EFAULT;

    return 0;
}

/* ============================================
 * 模块初始化/退出
 * ============================================ */

static int __init ai_syscalls_init(void)
{
    int ret;

    pr_info("ainos: AI Syscalls loading...\n");

    /* 注册设备 */
    ret = misc_register(&ainos_device);
    if (ret) {
        pr_err("ainos: failed to register device: %d\n", ret);
        return ret;
    }

    pr_info("ainos: AI Syscalls loaded. Device: /dev/ainos\n");
    return 0;
}

static void __exit ai_syscalls_exit(void)
{
    int i;

    /* 清理上下文表 */
    mutex_lock(&g_context_lock);
    for (i = 0; i < AI_MAX_CONTEXT_ENTRIES; i++) {
        if (g_context_table[i].used && g_context_table[i].value) {
            kvfree(g_context_table[i].value);
            g_context_table[i].value = NULL;
            g_context_table[i].used = false;
        }
    }
    mutex_unlock(&g_context_lock);

    misc_deregister(&ainos_device);
    pr_info("ainos: AI Syscalls unloaded\n");
}

module_init(ai_syscalls_init);
module_exit(ai_syscalls_exit);