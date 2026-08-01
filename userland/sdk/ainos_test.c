/*
 * Ainos SDK 测试程序
 * 编译: gcc -o ainos_test ainos_test.c -L. -lainos -lws2_32
 * 运行: ./ainos_test
 */

#include <stdio.h>
#include <string.h>
#include "ainos.h"

int main() {
    ainos_ctx *ctx = NULL;
    ainos_resp *resp = NULL;
    int ret;

    printf("=== Ainos OS SDK Test v%s ===\n\n", AINOS_SDK_VERSION);

    // 初始化 SDK
    printf("[1] Initializing SDK...\n");
    ctx = ainos_init("127.0.0.1:9500");
    if (!ctx) {
        printf("FAIL: ainos_init failed\n");
        return 1;
    }
    printf("OK: SDK initialized\n\n");

    // 连接 AI 守护进程
    printf("[2] Connecting to AI daemon...\n");
    ret = ainos_connect(ctx);
    if (ret != AINOS_OK) {
        printf("WARN: AI daemon not running (expected before system install)\n");
        printf("  Run 'ai-daemon' first, then retry.\n");

        // 获取系统信息
        printf("\n[3] Querying system info...\n");
        resp = ainos_get_info(ctx);
        if (resp && !resp->error_code) {
            printf("  Raw response: %s\n", resp->output);
            ainos_resp_free(resp);
        } else {
            printf("  (daemon not running)\n");
        }

        printf("\n=== Test skipped (AI daemon not running) ===\n");
        ainos_destroy(ctx);
        return 0;
    }
    printf("OK: Connected to AI daemon\n\n");

    // 获取系统信息
    printf("[3] Querying system info...\n");
    resp = ainos_get_info(ctx);
    if (resp && !resp->error_code) {
        printf("  Response: %s\n", resp->output);
        ainos_resp_free(resp);
    }

    // 执行推理
    printf("\n[4] Running inference...\n");
    ainos_infer_opts opts = AINOS_INFER_OPTS_DEFAULT;
    opts.temperature = 0.7f;
    opts.max_tokens = 100;

    resp = ainos_infer(ctx, "default", "Hello, what is Ainos OS?", &opts);
    if (resp && !resp->error_code) {
        printf("  Response: %s\n", resp->output);
        printf("  Tokens: %d\n", resp->tokens_generated);
        printf("  Time: %lld ms\n", resp->inference_ms);
        printf("  Source: %s\n", resp->source);
        ainos_resp_free(resp);
    } else {
        printf("  Inference failed: %s\n", resp ? resp->error_message : "NULL response");
        if (resp) ainos_resp_free(resp);
    }

    printf("\n=== All tests completed ===\n");
    ainos_destroy(ctx);
    return 0;
}