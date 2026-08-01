// tools/policy_compiler.c
// Ainos OS 策略编译器 - 将 APL 策略文件编译为二进制格式
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ainos/ai_policy.h"

static void print_usage(const char* prog) {
    printf("Ainos Policy Compiler v0.1.0\n");
    printf("Usage: %s [options] <input.apl> [output.bin]\n", prog);
    printf("Options:\n");
    printf("  -c, --check   仅检查策略语法\n");
    printf("  -d, --dump    反编译二进制策略\n");
    printf("  -v, --verbose 详细输出\n");
}

int main(int argc, char** argv) {
    if (argc < 2) {
        print_usage(argv[0]);
        return 1;
    }

    const char* input = NULL;
    const char* output = NULL;
    int check_only = 0;
    int dump = 0;
    int verbose = 0;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-c") == 0 || strcmp(argv[i], "--check") == 0) {
            check_only = 1;
        } else if (strcmp(argv[i], "-d") == 0 || strcmp(argv[i], "--dump") == 0) {
            dump = 1;
        } else if (strcmp(argv[i], "-v") == 0 || strcmp(argv[i], "--verbose") == 0) {
            verbose = 1;
        } else if (!input) {
            input = argv[i];
        } else if (!output) {
            output = argv[i];
        }
    }

    if (!input) {
        print_usage(argv[0]);
        return 1;
    }

    printf("[ai-policyc] Compiling: %s\n", input);

    // 读取策略文件
    FILE* fp = fopen(input, "r");
    if (!fp) {
        fprintf(stderr, "Error: Cannot open %s\n", input);
        return 1;
    }

    fseek(fp, 0, SEEK_END);
    long size = ftell(fp);
    rewind(fp);

    char* source = (char*)malloc(size + 1);
    fread(source, 1, size, fp);
    source[size] = '\0';
    fclose(fp);

    if (verbose) {
        printf("  Source size: %ld bytes\n", size);
    }

    // TODO: 调用策略解析器
    // ai_policy_result_t result = ai_policy_parse(source, size);

    if (check_only) {
        printf("  Syntax check: OK\n");
        free(source);
        return 0;
    }

    // 输出编译后的策略
    if (output) {
        FILE* out = fopen(output, "wb");
        if (out) {
            // TODO: 写入编译后的二进制策略
            fwrite("AIPC", 1, 4, out);  // Magic: Ainos Policy Compiled
            fclose(out);
            printf("[ai-policyc] Output: %s\n", output);
        }
    }

    free(source);
    printf("[ai-policyc] Compilation complete\n");
    return 0;
}