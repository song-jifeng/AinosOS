// SPDX-License-Identifier: GPL-2.0
/*
 * Ainos OS - AI 系统调用测试程序
 * ==========================================
 * 测试所有 AI 系统调用:
 *   - ai_embedding        (451)
 *   - ai_semantic_search  (452)
 *   - ai_model_load       (453)
 *   - ai_model_unload     (454)
 *   - ai_context_store    (455)
 *   - ai_context_retrieve (456)
 *   - ai_status           (457)
 *
 * 编译: gcc -o test_syscalls test_syscalls.c -lm
 * 运行: sudo ./test_syscalls   (需要 root 权限以调用系统调用)
 *
 * Copyright (C) 2024 Ainos OS Team
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/syscall.h>
#include <errno.h>
#include <math.h>
#include <time.h>
#include <stdint.h>
#include <stdbool.h>

/* ============================================
 * 内核 ABI 定义 (与 kernel/include/ainos/ai-abi.h 保持一致)
 * ============================================ */

/* __user 在用户空间为空定义 */
#define __user

/* 错误码 */
#define AI_ERR_SUCCESS          0
#define AI_ERR_GENERAL          -1
#define AI_ERR_INVALID_PARAM    -2
#define AI_ERR_MODEL_NOT_FOUND  -3
#define AI_ERR_MODEL_LOAD_FAIL  -4
#define AI_ERR_OUT_OF_MEMORY    -5
#define AI_ERR_TASK_QUEUE_FULL  -6
#define AI_ERR_NOT_SUPPORTED    -7
#define AI_ERR_PERMISSION       -8
#define AI_ERR_TIMEOUT          -9
#define AI_ERR_THERMAL_THROTTLE -10

/* 系统调用号 */
#ifndef __NR_ai_embedding
#define __NR_ai_embedding       451
#endif
#ifndef __NR_ai_semantic_search
#define __NR_ai_semantic_search 452
#endif
#ifndef __NR_ai_model_load
#define __NR_ai_model_load      453
#endif
#ifndef __NR_ai_model_unload
#define __NR_ai_model_unload    454
#endif
#ifndef __NR_ai_context_store
#define __NR_ai_context_store   455
#endif
#ifndef __NR_ai_context_retrieve
#define __NR_ai_context_retrieve 456
#endif
#ifndef __NR_ai_status
#define __NR_ai_status          457
#endif

/* 常量定义 */
#define AI_CONTEXT_KEY_MAX 128
#define AI_CONTEXT_VAL_MAX 65536
#define AI_MODEL_NAME_MAX 64
#define AI_MODEL_PATH_MAX 512
#define AI_SEARCH_PATH_LEN 512
#define AI_SEARCH_SNIPPET_LEN 256

/* 嵌入维度 */
#define AI_EMBEDDING_DIM_128   128
#define AI_EMBEDDING_DIM_256   256
#define AI_EMBEDDING_DIM_512   512
#define AI_EMBEDDING_DIM_768   768
#define AI_EMBEDDING_DIM_1024  1024
#define AI_EMBEDDING_DIM_2048  2048
#define AI_EMBEDDING_DIM_4096  4096

/* 系统状态 */
struct ai_system_status {
    uint32_t models_loaded;
    uint32_t tasks_pending;
    uint32_t tasks_running;
    uint64_t total_inferences;
    uint64_t total_tokens;
    uint64_t uptime_ms;
    uint8_t  network_available;
    uint8_t  accelerator_type;
    char     version[64];
};

/* 嵌入请求 */
struct ai_embedding_req {
    const float __user *input;
    uint64_t input_len;
    float __user *embedding;
    uint64_t embedding_dim;
};

/* 语义搜索结果 */
struct ai_search_result {
    char path[AI_SEARCH_PATH_LEN];
    char snippet[AI_SEARCH_SNIPPET_LEN];
    float score;
    uint64_t file_size;
    uint64_t modified_at;
};

/* 搜索请求 */
struct ai_search_req {
    const float __user *query_emb;
    uint64_t query_dim;
    const float __user *database;
    uint64_t db_size;
    uint64_t vector_dim;
    uint32_t top_k;
    struct ai_search_result __user *results;
};

/* 模型加载请求 */
struct ai_model_load_req {
    char name[AI_MODEL_NAME_MAX];
    char path[AI_MODEL_PATH_MAX];
};

/* 上下文存储请求 */
struct ai_context_store_req {
    uint64_t session_id;
    char key[AI_CONTEXT_KEY_MAX];
    const char __user *value;
    uint64_t value_len;
    uint64_t ttl_ms;
};

/* 上下文检索请求 */
struct ai_context_retrieve_req {
    uint64_t session_id;
    char key[AI_CONTEXT_KEY_MAX];
    uint64_t entry_id;
    char __user *value;
    uint64_t value_capacity;
    uint64_t __user *value_len;
};

/* ============================================
 * 辅助函数
 * ============================================ */

static int test_pass_count = 0;
static int test_fail_count = 0;

#define TEST(name, expr) do { \
    int _ret = (expr); \
    if (_ret == 0) { \
        printf("  PASS: %s\n", name); \
        test_pass_count++; \
    } else { \
        printf("  FAIL: %s (ret=%d, errno=%d)\n", name, _ret, errno); \
        test_fail_count++; \
    } \
} while(0)

#define TEST_EQ(name, expr, expected) do { \
    int _ret = (expr); \
    if (_ret == (expected)) { \
        printf("  PASS: %s\n", name); \
        test_pass_count++; \
    } else { \
        printf("  FAIL: %s (got %d, expected %d, errno=%d)\n", \
               name, _ret, (expected), errno); \
        test_fail_count++; \
    } \
} while(0)

static void print_summary(void)
{
    printf("\n========================================\n");
    printf("Test Summary: %d passed, %d failed out of %d\n",
           test_pass_count, test_fail_count,
           test_pass_count + test_fail_count);
    printf("========================================\n");
}

/* ============================================
 * 测试用例
 * ============================================ */

static void test_ai_embedding(void)
{
    printf("\n--- Test: ai_embedding (syscall 451) ---\n");

    /* 生成测试输入 */
    float input[64];
    float embedding[AI_EMBEDDING_DIM_128];
    int ret;

    for (int i = 0; i < 64; i++)
        input[i] = (float)(i % 10) / 10.0f;

    /* 测试 1: 正常嵌入 (128维) */
    {
        struct ai_embedding_req req = {
            .input = input,
            .input_len = 64,
            .embedding = embedding,
            .embedding_dim = AI_EMBEDDING_DIM_128
        };
        ret = syscall(__NR_ai_embedding, &req);
        TEST("128-dim embedding", ret == 0 ? 0 : -1);
        if (ret == 0) {
            printf("         First 5 values: %.4f %.4f %.4f %.4f %.4f\n",
                   embedding[0], embedding[1], embedding[2],
                   embedding[3], embedding[4]);
        }
    }

    /* 测试 2: 256维嵌入 */
    {
        float emb256[AI_EMBEDDING_DIM_256];
        struct ai_embedding_req req = {
            .input = input,
            .input_len = 64,
            .embedding = emb256,
            .embedding_dim = AI_EMBEDDING_DIM_256
        };
        ret = syscall(__NR_ai_embedding, &req);
        TEST("256-dim embedding", ret == 0 ? 0 : -1);
    }

    /* 测试 3: 4096维嵌入 */
    {
        float *emb4096 = malloc(AI_EMBEDDING_DIM_4096 * sizeof(float));
        if (emb4096) {
            struct ai_embedding_req req = {
                .input = input,
                .input_len = 64,
                .embedding = emb4096,
                .embedding_dim = AI_EMBEDDING_DIM_4096
            };
            ret = syscall(__NR_ai_embedding, &req);
            TEST("4096-dim embedding", ret == 0 ? 0 : -1);
            free(emb4096);
        }
    }

    /* 测试 4: 无效维度 (应返回 -AI_ERR_INVALID_PARAM) */
    {
        float emb_bad[10];
        struct ai_embedding_req req = {
            .input = input,
            .input_len = 64,
            .embedding = emb_bad,
            .embedding_dim = 42  /* 无效维度 */
        };
        ret = syscall(__NR_ai_embedding, &req);
        TEST_EQ("invalid dimension", ret, AI_ERR_INVALID_PARAM);
    }

    /* 测试 5: NULL 请求 */
    {
        ret = syscall(__NR_ai_embedding, NULL);
        TEST_EQ("NULL request", ret, AI_ERR_INVALID_PARAM);
    }

    /* 测试 6: 输入长度为0 */
    {
        struct ai_embedding_req req = {
            .input = input,
            .input_len = 0,
            .embedding = embedding,
            .embedding_dim = AI_EMBEDDING_DIM_128
        };
        ret = syscall(__NR_ai_embedding, &req);
        TEST_EQ("zero input length", ret, AI_ERR_INVALID_PARAM);
    }

    /* 测试 7: 确定性验证 (相同输入应产生相同嵌入) */
    {
        float emb_a[AI_EMBEDDING_DIM_128];
        float emb_b[AI_EMBEDDING_DIM_128];
        struct ai_embedding_req req_a = {
            .input = input,
            .input_len = 64,
            .embedding = emb_a,
            .embedding_dim = AI_EMBEDDING_DIM_128
        };
        struct ai_embedding_req req_b = {
            .input = input,
            .input_len = 64,
            .embedding = emb_b,
            .embedding_dim = AI_EMBEDDING_DIM_128
        };
        ret = syscall(__NR_ai_embedding, &req_a);
        if (ret == 0) {
            ret = syscall(__NR_ai_embedding, &req_b);
            if (ret == 0) {
                int match = 1;
                for (int i = 0; i < AI_EMBEDDING_DIM_128; i++) {
                    if (fabsf(emb_a[i] - emb_b[i]) > 0.0001f) {
                        match = 0;
                        break;
                    }
                }
                TEST("deterministic output", match ? 0 : -1);
            }
        }
    }
}

static void test_ai_semantic_search(void)
{
    printf("\n--- Test: ai_semantic_search (syscall 452) ---\n");

    int ret;
    uint32_t dim = 64;
    uint32_t db_size = 20;
    uint32_t top_k = 5;

    /* 生成查询向量 */
    float *query = malloc(dim * sizeof(float));
    /* 生成数据库向量 */
    float *database = malloc(db_size * dim * sizeof(float));
    /* 结果缓冲区 */
    struct ai_search_result *results = malloc(top_k * sizeof(struct ai_search_result));

    if (!query || !database || !results) {
        printf("  SKIP: memory allocation failed\n");
        free(query);
        free(database);
        free(results);
        return;
    }

    /* 初始化查询向量 */
    for (uint32_t i = 0; i < dim; i++)
        query[i] = (float)(i % 5) / 5.0f;

    /* 初始化数据库向量 (前几个与查询相似) */
    for (uint32_t i = 0; i < db_size; i++) {
        for (uint32_t j = 0; j < dim; j++) {
            if (i < 3) {
                /* 高度相似 */
                database[i * dim + j] = query[j] + ((float)(i + 1) * 0.01f);
            } else {
                /* 随机向量 */
                database[i * dim + j] = (float)(rand() % 1000) / 500.0f - 1.0f;
            }
        }
    }

    /* 测试 1: 正常搜索 */
    {
        struct ai_search_req req = {
            .query_emb = query,
            .query_dim = dim,
            .database = database,
            .db_size = db_size,
            .vector_dim = dim,
            .top_k = top_k,
            .results = results
        };
        ret = syscall(__NR_ai_semantic_search, &req);
        TEST("semantic search", ret == 0 ? 0 : -1);
        if (ret == 0) {
            printf("         Top 5 results:\n");
            for (uint32_t i = 0; i < top_k; i++) {
                printf("           [%u] score=%.4f path=%s\n",
                       i, results[i].score, results[i].path);
            }
        }
    }

    /* 测试 2: 相似度排序验证 (结果应降序排列) */
    {
        struct ai_search_req req = {
            .query_emb = query,
            .query_dim = dim,
            .database = database,
            .db_size = db_size,
            .vector_dim = dim,
            .top_k = db_size,  /* 返回所有结果 */
            .results = results
        };
        ret = syscall(__NR_ai_semantic_search, &req);
        if (ret == 0) {
            int sorted = 1;
            for (uint32_t i = 1; i < db_size; i++) {
                if (results[i - 1].score < results[i].score) {
                    sorted = 0;
                    break;
                }
            }
            TEST("results sorted by score descending", sorted ? 0 : -1);
        }
    }

    /* 测试 3: NULL 请求 */
    {
        ret = syscall(__NR_ai_semantic_search, NULL);
        TEST_EQ("NULL request", ret, AI_ERR_INVALID_PARAM);
    }

    /* 测试 4: 空数据库 */
    {
        struct ai_search_req req = {
            .query_emb = query,
            .query_dim = dim,
            .database = database,
            .db_size = 0,
            .vector_dim = dim,
            .top_k = top_k,
            .results = results
        };
        ret = syscall(__NR_ai_semantic_search, &req);
        TEST_EQ("empty database", ret, AI_ERR_INVALID_PARAM);
    }

    /* 测试 5: 维度不匹配 */
    {
        struct ai_search_req req = {
            .query_emb = query,
            .query_dim = dim,
            .database = database,
            .db_size = db_size,
            .vector_dim = dim + 10,  /* 不匹配 */
            .top_k = top_k,
            .results = results
        };
        ret = syscall(__NR_ai_semantic_search, &req);
        TEST_EQ("dimension mismatch", ret, AI_ERR_INVALID_PARAM);
    }

    free(query);
    free(database);
    free(results);
}

static void test_ai_model_load_unload(void)
{
    printf("\n--- Test: ai_model_load (syscall 453) / ai_model_unload (syscall 454) ---\n");

    uint64_t model_id;
    int ret;

    /* 测试 1: 加载不存在的模型文件 */
    {
        struct ai_model_load_req req = {
            .name = "nonexistent_model",
            .path = "/nonexistent/path/to/model.gguf"
        };
        ret = syscall(__NR_ai_model_load, &req, &model_id);
        TEST_EQ("load nonexistent model", ret, AI_ERR_MODEL_NOT_FOUND);
    }

    /* 测试 2: 加载存在的模型文件 (使用 /etc/passwd 作为测试文件) */
    {
        struct ai_model_load_req req = {
            .name = "test_model",
            .path = "/etc/passwd"
        };
        ret = syscall(__NR_ai_model_load, &req, &model_id);
        TEST("load existing file as model", ret == 0 ? 0 : -1);
        if (ret == 0) {
            printf("         Model ID: %llu\n", model_id);
        }
    }

    /* 测试 3: 卸载刚加载的模型 */
    if (ret == 0) {
        ret = syscall(__NR_ai_model_unload, model_id);
        TEST_EQ("unload model", ret, 0);
    }

    /* 测试 4: 卸载不存在的模型 */
    {
        ret = syscall(__NR_ai_model_unload, 999999);
        TEST_EQ("unload nonexistent model", ret, AI_ERR_MODEL_NOT_FOUND);
    }

    /* 测试 5: NULL 请求 */
    {
        ret = syscall(__NR_ai_model_load, NULL, &model_id);
        TEST_EQ("NULL load request", ret, AI_ERR_INVALID_PARAM);
    }

    /* 测试 6: 空名称 */
    {
        struct ai_model_load_req req = {
            .name = "",
            .path = "/etc/passwd"
        };
        ret = syscall(__NR_ai_model_load, &req, &model_id);
        TEST_EQ("empty model name", ret, AI_ERR_INVALID_PARAM);
    }
}

static void test_ai_context_store_retrieve(void)
{
    printf("\n--- Test: ai_context_store (syscall 455) / ai_context_retrieve (syscall 456) ---\n");

    uint64_t entry_id;
    int ret;

    /* 测试 1: 存储上下文 */
    {
        const char *value = "Hello, Ainos Context!";
        struct ai_context_store_req req = {
            .session_id = 1,
            .key = "test_key",
            .value = value,
            .value_len = strlen(value) + 1,
            .ttl_ms = 60000  /* 60秒 TTL */
        };
        ret = syscall(__NR_ai_context_store, &req, &entry_id);
        TEST("store context", ret == 0 ? 0 : -1);
        if (ret == 0) {
            printf("         Entry ID: %llu\n", entry_id);
        }
    }

    /* 测试 2: 检索上下文 (按 key) */
    if (ret == 0) {
        char buffer[256];
        uint64_t value_len = 0;
        struct ai_context_retrieve_req req = {
            .session_id = 1,
            .key = "test_key",
            .entry_id = 0,
            .value = buffer,
            .value_capacity = sizeof(buffer),
            .value_len = &value_len
        };
        ret = syscall(__NR_ai_context_retrieve, &req);
        TEST("retrieve context by key", ret == 0 ? 0 : -1);
        if (ret == 0) {
            printf("         Retrieved value: '%s' (len=%llu)\n",
                   buffer, value_len);
            TEST("value matches", strcmp(buffer, "Hello, Ainos Context!") == 0 ? 0 : -1);
        }
    }

    /* 测试 3: 检索上下文 (按 entry_id) */
    if (entry_id > 0) {
        char buffer[256];
        uint64_t value_len = 0;
        struct ai_context_retrieve_req req = {
            .session_id = 0,
            .key = "",
            .entry_id = entry_id,
            .value = buffer,
            .value_capacity = sizeof(buffer),
            .value_len = &value_len
        };
        ret = syscall(__NR_ai_context_retrieve, &req);
        TEST("retrieve context by entry_id", ret == 0 ? 0 : -1);
        if (ret == 0) {
            printf("         Retrieved by ID: '%s' (len=%llu)\n",
                   buffer, value_len);
        }
    }

    /* 测试 4: 检索不存在的 key */
    {
        char buffer[256];
        uint64_t value_len = 0;
        struct ai_context_retrieve_req req = {
            .session_id = 1,
            .key = "nonexistent_key",
            .entry_id = 0,
            .value = buffer,
            .value_capacity = sizeof(buffer),
            .value_len = &value_len
        };
        ret = syscall(__NR_ai_context_retrieve, &req);
        TEST_EQ("retrieve nonexistent key", ret, AI_ERR_INVALID_PARAM);
    }

    /* 测试 5: 覆盖已有 key */
    {
        const char *value = "Updated Value!";
        uint64_t new_entry_id;
        struct ai_context_store_req req = {
            .session_id = 1,
            .key = "test_key",
            .value = value,
            .value_len = strlen(value) + 1,
            .ttl_ms = 0  /* 永不过期 */
        };
        ret = syscall(__NR_ai_context_store, &req, &new_entry_id);
        TEST("overwrite existing key", ret == 0 ? 0 : -1);
        if (ret == 0) {
            printf("         New Entry ID: %llu (old: %llu)\n",
                   new_entry_id, entry_id);
        }
    }

    /* 测试 6: NULL 请求 */
    {
        ret = syscall(__NR_ai_context_store, NULL, &entry_id);
        TEST_EQ("NULL store request", ret, AI_ERR_INVALID_PARAM);
    }

    /* 测试 7: 空 key */
    {
        const char *value = "test";
        struct ai_context_store_req req = {
            .session_id = 1,
            .key = "",
            .value = value,
            .value_len = strlen(value) + 1,
            .ttl_ms = 0
        };
        ret = syscall(__NR_ai_context_store, &req, &entry_id);
        TEST_EQ("empty key", ret, AI_ERR_INVALID_PARAM);
    }

    /* 测试 8: 检索时 key 和 entry_id 都为空 */
    {
        char buffer[256];
        uint64_t value_len = 0;
        struct ai_context_retrieve_req req = {
            .session_id = 1,
            .key = "",
            .entry_id = 0,
            .value = buffer,
            .value_capacity = sizeof(buffer),
            .value_len = &value_len
        };
        ret = syscall(__NR_ai_context_retrieve, &req);
        TEST_EQ("retrieve with empty key and id", ret, AI_ERR_INVALID_PARAM);
    }
}

static void test_ai_status(void)
{
    printf("\n--- Test: ai_status (syscall 457) ---\n");

    struct ai_system_status status;
    int ret;

    /* 测试 1: 获取系统状态 */
    {
        ret = syscall(__NR_ai_status, &status);
        TEST("get system status", ret == 0 ? 0 : -1);
        if (ret == 0) {
            printf("         models_loaded=%u tasks_pending=%u tasks_running=%u\n"
                   "         total_inferences=%llu total_tokens=%llu\n"
                   "         version=%s\n",
                   status.models_loaded, status.tasks_pending,
                   status.tasks_running,
                   status.total_inferences, status.total_tokens,
                   status.version);
        }
    }

    /* 测试 2: NULL 指针 */
    {
        ret = syscall(__NR_ai_status, NULL);
        TEST_EQ("NULL status pointer", ret, AI_ERR_INVALID_PARAM);
    }
}

/* ============================================
 * 主函数
 * ============================================ */

int main(void)
{
    printf("========================================\n");
    printf("Ainos OS - AI System Call Test Suite\n");
    printf("========================================\n");
    printf("Running as UID=%d\n", getuid());

    /* 种子初始化 */
    srand((unsigned int)time(NULL));

    /* 运行测试 */
    test_ai_embedding();
    test_ai_semantic_search();
    test_ai_model_load_unload();
    test_ai_context_store_retrieve();
    test_ai_status();

    /* 输出汇总 */
    print_summary();

    return test_fail_count > 0 ? 1 : 0;
}