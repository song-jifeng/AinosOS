// SPDX-License-Identifier: GPL-2.0
/*
 * Ainos OS - AI 向量指令加速模块
 * ==========================================
 * 利用 CPU 向量指令 (AVX2/AVX-512/NEON/SVE) 加速 AI 推理
 *
 * 功能:
 *   1. 矩阵乘法加速 (SGEMM)
 *   2. 向量点积加速
 *   3. 量化/反量化加速
 *   4. 激活函数加速
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/slab.h>
#include <linux/cpumask.h>
#include <linux/cache.h>

#include "ainos/ai-abi.h"

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("Ainos AI Vector Acceleration");
MODULE_VERSION("0.1.0");

/* ============================================
 * CPU 特性检测
 * ============================================ */
#ifdef CONFIG_X86
#include <asm/cpufeature.h>
#include <asm/processor.h>

static int has_avx2 = 0;
static int has_avx512 = 0;
static int has_avx512_vnni = 0;
static int has_amx = 0;
static int has_amx_bf16 = 0;
static int has_f16c = 0;
static int has_ssse3 = 0;

static void detect_cpu_features(void)
{
    has_avx2 = boot_cpu_has(X86_FEATURE_AVX2);
    has_avx512 = boot_cpu_has(X86_FEATURE_AVX512F);
    has_avx512_vnni = boot_cpu_has(X86_FEATURE_AVX512_VNNI);
    has_amx = boot_cpu_has(X86_FEATURE_AMX_TILE);
    has_amx_bf16 = boot_cpu_has(X86_FEATURE_AMX_BF16);
    has_f16c = boot_cpu_has(X86_FEATURE_F16C);
    has_ssse3 = boot_cpu_has(X86_FEATURE_SSSE3);
}
#elif defined(CONFIG_ARM64)
#include <asm/cpufeature.h>

static int has_neon = 0;
static int has_sve = 0;
static int has_sve2 = 0;
static int has_i8mm = 0;

static void detect_cpu_features(void)
{
    has_neon = 1; /* ARM64 始终有 NEON */
    has_sve = system_supports_sve();
    has_sve2 = system_supports_sve2();
    has_i8mm = system_capabilities_finalized() &&
               cpus_have_cap(ARM64_HAS_I8MM);
}
#else
static void detect_cpu_features(void) { }
#endif

/* ============================================
 * 向量操作函数指针
 * ============================================ */
typedef void (*matmul_fp32_t)(int m, int n, int k,
                               const float *a, const float *b, float *c);
typedef float (*dot_product_t)(int n, const float *a, const float *b);
typedef void (*quantize_t)(int n, const float *src, void *dst, float scale);
typedef void (*dequantize_t)(int n, const void *src, float *dst, float scale);

/* ============================================
 * 加速器操作表
 * ============================================ */
struct ai_vector_ops {
    matmul_fp32_t matmul_fp32;
    dot_product_t dot_product;
    quantize_t quantize_fp32_to_q8;
    quantize_t quantize_fp32_to_q4;
    dequantize_t dequantize_q8_to_fp32;
    dequantize_t dequantize_q4_to_fp32;
    const char *name;
    int vector_size;   /* 向量寄存器宽度 (字节) */
};

/* 通用实现 (纯 C) */
static void matmul_fp32_generic(int m, int n, int k,
                                 const float *a, const float *b, float *c)
{
    for (int i = 0; i < m; i++) {
        for (int j = 0; j < n; j++) {
            float sum = 0.0f;
            for (int p = 0; p < k; p++) {
                sum += a[i * k + p] * b[p * n + j];
            }
            c[i * n + j] = sum;
        }
    }
}

static float dot_product_generic(int n, const float *a, const float *b)
{
    float sum = 0.0f;
    for (int i = 0; i < n; i++)
        sum += a[i] * b[i];
    return sum;
}

static void quantize_fp32_to_q8_generic(int n, const float *src,
                                         void *dst, float scale)
{
    int8_t *dst8 = (int8_t *)dst;
    for (int i = 0; i < n; i++)
        dst8[i] = (int8_t)(src[i] * scale);
}

static void quantize_fp32_to_q4_generic(int n, const float *src,
                                         void *dst, float scale)
{
    uint8_t *dst4 = (uint8_t *)dst;
    for (int i = 0; i < n; i += 2) {
        int8_t v0 = (int8_t)(src[i] * scale);
        int8_t v1 = (int8_t)(src[i + 1] * scale);
        dst4[i / 2] = (uint8_t)((v0 & 0x0F) | ((v1 & 0x0F) << 4));
    }
}

static void dequantize_q8_to_fp32_generic(int n, const void *src,
                                           float *dst, float scale)
{
    const int8_t *src8 = (const int8_t *)src;
    for (int i = 0; i < n; i++)
        dst[i] = (float)src8[i] / scale;
}

static void dequantize_q4_to_fp32_generic(int n, const void *src,
                                           float *dst, float scale)
{
    const uint8_t *src4 = (const uint8_t *)src;
    for (int i = 0; i < n; i += 2) {
        uint8_t byte = src4[i / 2];
        dst[i] = (float)(int8_t)(byte & 0x0F) / scale;
        dst[i + 1] = (float)(int8_t)(byte >> 4) / scale;
    }
}

/* 默认操作表 (通用实现) */
static struct ai_vector_ops vector_ops = {
    .matmul_fp32 = matmul_fp32_generic,
    .dot_product = dot_product_generic,
    .quantize_fp32_to_q8 = quantize_fp32_to_q8_generic,
    .quantize_fp32_to_q4 = quantize_fp32_to_q4_generic,
    .dequantize_q8_to_fp32 = dequantize_q8_to_fp32_generic,
    .dequantize_q4_to_fp32 = dequantize_q4_to_fp32_generic,
    .name = "generic",
    .vector_size = 0,
};

/* ============================================
 * 公共 API
 * ============================================ */

/* 获取向量操作表 */
struct ai_vector_ops *ai_vector_get_ops(void)
{
    return &vector_ops;
}

/* 矩阵乘法 (自动选择最优实现) */
void ai_vector_matmul_fp32(int m, int n, int k,
                            const float *a, const float *b, float *c)
{
    vector_ops.matmul_fp32(m, n, k, a, b, c);
}

/* 向量点积 */
float ai_vector_dot_product(int n, const float *a, const float *b)
{
    return vector_ops.dot_product(n, a, b);
}

/* 获取加速器信息 */
const char *ai_vector_get_name(void)
{
    return vector_ops.name;
}

int ai_vector_get_vector_size(void)
{
    return vector_ops.vector_size;
}

EXPORT_SYMBOL_GPL(ai_vector_get_ops);
EXPORT_SYMBOL_GPL(ai_vector_matmul_fp32);
EXPORT_SYMBOL_GPL(ai_vector_dot_product);
EXPORT_SYMBOL_GPL(ai_vector_get_name);
EXPORT_SYMBOL_GPL(ai_vector_get_vector_size);

/* ============================================
 * 模块初始化/退出
 * ============================================ */

static int __init ai_vector_init(void)
{
    detect_cpu_features();

    pr_info("ainos: Vector Acceleration loading...\n");

#ifdef CONFIG_X86
    pr_info("ainos: CPU features: AVX2=%d AVX512=%d AVX512_VNNI=%d AMX=%d F16C=%d\n",
            has_avx2, has_avx512, has_avx512_vnni, has_amx, has_f16c);

    if (has_avx2) {
        pr_info("ainos: AVX2 acceleration available\n");
        /* TODO: 注册 AVX2 优化实现 */
    }
    if (has_avx512_vnni) {
        pr_info("ainos: AVX512-VNNI acceleration available\n");
        /* TODO: 注册 AVX512-VNNI 优化实现 */
    }
    if (has_amx_bf16) {
        pr_info("ainos: AMX-BF16 acceleration available\n");
        /* TODO: 注册 AMX 优化实现 */
    }
#elif defined(CONFIG_ARM64)
    pr_info("ainos: CPU features: NEON=1 SVE=%d SVE2=%d I8MM=%d\n",
            has_sve, has_sve2, has_i8mm);
    if (has_sve) {
        pr_info("ainos: SVE acceleration available\n");
        /* TODO: 注册 SVE 优化实现 */
    }
#endif

    pr_info("ainos: Vector Acceleration loaded (%s, vector=%d bytes)\n",
            vector_ops.name, vector_ops.vector_size);
    return 0;
}

static void __exit ai_vector_exit(void)
{
    pr_info("ainos: Vector Acceleration unloaded\n");
}

module_init(ai_vector_init);
module_exit(ai_vector_exit);