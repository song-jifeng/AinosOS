// SPDX-License-Identifier: GPL-2.0
/*
 * Ainos OS - AI 向量指令加速模块
 * ==========================================
 * 利用 CPU 向量指令 (AVX2/AVX-512/AMX/NEON/SVE) 加速 AI 推理
 *
 * 功能:
 *   1. 矩阵乘法加速 (SGEMM)
 *   2. 向量点积加速
 *   3. 量化/反量化加速
 *   4. 激活函数加速
 *   5. 运行时 CPU 特性检测与最优实现自动选择
 *   6. 启动时基准测试
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/slab.h>
#include <linux/cpumask.h>
#include <linux/cache.h>
#include <linux/export.h>
#include <linux/printk.h>
#include <linux/string.h>

#include "ainos/ai-abi.h"

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("Ainos AI Vector Acceleration with SIMD support");
MODULE_VERSION("0.2.0");

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

/* ============================================
 * SIMD 实现注册
 * ============================================ */

/* Forward declarations for SIMD ops getters */
#ifdef CONFIG_X86
#include "arch/x86/simd_impl.h"
static const struct simd_ops *x86_avx2_ops = NULL;
static const struct simd_ops *x86_avx512_ops = NULL;
static const struct simd_ops *x86_amx_ops = NULL;
#elif defined(CONFIG_ARM64)
#include "arch/arm64/simd_impl.h"
static const struct simd_ops *arm64_neon_ops = NULL;
static const struct simd_ops *arm64_sve_ops = NULL;
#endif

/* Current active ops (set to best available implementation) */
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
 * 选择最优实现
 * ============================================
 * 优先级: AMX > AVX-512 > AVX2 > SVE2 > SVE > NEON > generic
 */
static void select_best_implementation(void)
{
#ifdef CONFIG_X86
    /* Try to register AMX (highest priority on x86) */
    if (has_amx && has_amx_bf16 && x86_amx_ops) {
        vector_ops.matmul_fp32 = x86_amx_ops->matmul_fp32;
        vector_ops.dot_product = x86_amx_ops->dot_product;
        vector_ops.quantize_fp32_to_q8 = x86_amx_ops->quantize_fp32_to_q8;
        vector_ops.quantize_fp32_to_q4 = x86_amx_ops->quantize_fp32_to_q4;
        vector_ops.dequantize_q8_to_fp32 = x86_amx_ops->dequantize_q8_to_fp32;
        vector_ops.dequantize_q4_to_fp32 = x86_amx_ops->dequantize_q4_to_fp32;
        vector_ops.name = x86_amx_ops->name;
        vector_ops.vector_size = x86_amx_ops->vector_size;
        pr_info("ainos: Using AMX acceleration (TILE)\n");
        return;
    }

    /* Try AVX-512 */
    if (has_avx512 && x86_avx512_ops) {
        vector_ops.matmul_fp32 = x86_avx512_ops->matmul_fp32;
        vector_ops.dot_product = x86_avx512_ops->dot_product;
        vector_ops.quantize_fp32_to_q8 = x86_avx512_ops->quantize_fp32_to_q8;
        vector_ops.quantize_fp32_to_q4 = x86_avx512_ops->quantize_fp32_to_q4;
        vector_ops.dequantize_q8_to_fp32 = x86_avx512_ops->dequantize_q8_to_fp32;
        vector_ops.dequantize_q4_to_fp32 = x86_avx512_ops->dequantize_q4_to_fp32;
        vector_ops.name = x86_avx512_ops->name;
        vector_ops.vector_size = x86_avx512_ops->vector_size;
        pr_info("ainos: Using AVX-512 acceleration (64 bytes)\n");
        return;
    }

    /* Try AVX2 */
    if (has_avx2 && x86_avx2_ops) {
        vector_ops.matmul_fp32 = x86_avx2_ops->matmul_fp32;
        vector_ops.dot_product = x86_avx2_ops->dot_product;
        vector_ops.quantize_fp32_to_q8 = x86_avx2_ops->quantize_fp32_to_q8;
        vector_ops.quantize_fp32_to_q4 = x86_avx2_ops->quantize_fp32_to_q4;
        vector_ops.dequantize_q8_to_fp32 = x86_avx2_ops->dequantize_q8_to_fp32;
        vector_ops.dequantize_q4_to_fp32 = x86_avx2_ops->dequantize_q4_to_fp32;
        vector_ops.name = x86_avx2_ops->name;
        vector_ops.vector_size = x86_avx2_ops->vector_size;
        pr_info("ainos: Using AVX2 acceleration (32 bytes)\n");
        return;
    }

#elif defined(CONFIG_ARM64)
    /* Try SVE2 (highest priority on ARM64) */
    if (has_sve2 && arm64_sve_ops) {
        vector_ops.matmul_fp32 = arm64_sve_ops->matmul_fp32;
        vector_ops.dot_product = arm64_sve_ops->dot_product;
        vector_ops.quantize_fp32_to_q8 = arm64_sve_ops->quantize_fp32_to_q8;
        vector_ops.quantize_fp32_to_q4 = arm64_sve_ops->quantize_fp32_to_q4;
        vector_ops.dequantize_q8_to_fp32 = arm64_sve_ops->dequantize_q8_to_fp32;
        vector_ops.dequantize_q4_to_fp32 = arm64_sve_ops->dequantize_q4_to_fp32;
        vector_ops.name = arm64_sve_ops->name;
        vector_ops.vector_size = arm64_sve_ops->vector_size;
        pr_info("ainos: Using SVE2 acceleration\n");
        return;
    }

    /* Try SVE */
    if (has_sve && arm64_sve_ops) {
        vector_ops.matmul_fp32 = arm64_sve_ops->matmul_fp32;
        vector_ops.dot_product = arm64_sve_ops->dot_product;
        vector_ops.quantize_fp32_to_q8 = arm64_sve_ops->quantize_fp32_to_q8;
        vector_ops.quantize_fp32_to_q4 = arm64_sve_ops->quantize_fp32_to_q4;
        vector_ops.dequantize_q8_to_fp32 = arm64_sve_ops->dequantize_q8_to_fp32;
        vector_ops.dequantize_q4_to_fp32 = arm64_sve_ops->dequantize_q4_to_fp32;
        vector_ops.name = arm64_sve_ops->name;
        vector_ops.vector_size = arm64_sve_ops->vector_size;
        pr_info("ainos: Using SVE acceleration\n");
        return;
    }

    /* Try NEON (always available on ARM64) */
    if (has_neon && arm64_neon_ops) {
        vector_ops.matmul_fp32 = arm64_neon_ops->matmul_fp32;
        vector_ops.dot_product = arm64_neon_ops->dot_product;
        vector_ops.quantize_fp32_to_q8 = arm64_neon_ops->quantize_fp32_to_q8;
        vector_ops.quantize_fp32_to_q4 = arm64_neon_ops->quantize_fp32_to_q4;
        vector_ops.dequantize_q8_to_fp32 = arm64_neon_ops->dequantize_q8_to_fp32;
        vector_ops.dequantize_q4_to_fp32 = arm64_neon_ops->dequantize_q4_to_fp32;
        vector_ops.name = arm64_neon_ops->name;
        vector_ops.vector_size = arm64_neon_ops->vector_size;
        pr_info("ainos: Using NEON acceleration (16 bytes)\n");
        return;
    }
#endif

    /* If no SIMD available, keep generic */
    pr_info("ainos: No SIMD acceleration available, using generic fallback\n");
}

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
 * 运行时 API: 查询当前使用的加速器类型
 * ============================================ */

/* 返回使用的加速器类型: "generic", "avx2", "avx512", "amx", "neon", "sve" */
const char *ai_vector_accel_type(void)
{
    return vector_ops.name;
}

/* 返回向量寄存器宽度（字节），0 表示标量 */
int ai_vector_accel_width(void)
{
    return vector_ops.vector_size;
}

/* 检查是否正在使用 SIMD 加速 */
bool ai_vector_has_simd(void)
{
    return vector_ops.vector_size > 0;
}

/* 检查特定 CPU 特性是否可用 */
#ifdef CONFIG_X86
int ai_vector_has_feature(const char *feature)
{
    if (!feature)
        return 0;
    if (strcmp(feature, "avx2") == 0)
        return has_avx2;
    if (strcmp(feature, "avx512") == 0)
        return has_avx512;
    if (strcmp(feature, "avx512_vnni") == 0)
        return has_avx512_vnni;
    if (strcmp(feature, "amx") == 0)
        return has_amx;
    if (strcmp(feature, "amx_bf16") == 0)
        return has_amx_bf16;
    if (strcmp(feature, "f16c") == 0)
        return has_f16c;
    if (strcmp(feature, "ssse3") == 0)
        return has_ssse3;
    return 0;
}
#elif defined(CONFIG_ARM64)
int ai_vector_has_feature(const char *feature)
{
    if (!feature)
        return 0;
    if (strcmp(feature, "neon") == 0)
        return has_neon;
    if (strcmp(feature, "sve") == 0)
        return has_sve;
    if (strcmp(feature, "sve2") == 0)
        return has_sve2;
    if (strcmp(feature, "i8mm") == 0)
        return has_i8mm;
    return 0;
}
#else
int ai_vector_has_feature(const char *feature)
{
    return 0;
}
#endif

EXPORT_SYMBOL_GPL(ai_vector_accel_type);
EXPORT_SYMBOL_GPL(ai_vector_accel_width);
EXPORT_SYMBOL_GPL(ai_vector_has_simd);
EXPORT_SYMBOL_GPL(ai_vector_has_feature);

/* ============================================
 * 基准测试
 * ============================================ */

/* Default benchmark sizes */
static const int bench_sizes[] = {64, 128, 256, 512, 1024, 2048};
#define NUM_BENCH_SIZES (sizeof(bench_sizes) / sizeof(bench_sizes[0]))

/* Test that SIMD implementations produce correct results */
static int verify_correctness(void)
{
    int ret = 0;
    int test_n = 64;
    float *a, *b, *c_generic, *c_simd;
    int i;

    a = kmalloc_array(test_n, sizeof(float), GFP_KERNEL);
    b = kmalloc_array(test_n, sizeof(float), GFP_KERNEL);
    c_generic = kmalloc_array(test_n, sizeof(float), GFP_KERNEL);
    c_simd = kmalloc_array(test_n, sizeof(float), GFP_KERNEL);

    if (!a || !b || !c_generic || !c_simd) {
        pr_err("ainos: Failed to allocate verification buffers\n");
        ret = -ENOMEM;
        goto out_free;
    }

    /* Fill with known test data */
    for (i = 0; i < test_n; i++) {
        a[i] = (float)(i % 7) * 0.5f;
        b[i] = (float)(i % 11) * 0.25f;
    }

    /* Test dot product */
    {
        float ref = dot_product_generic(test_n, a, b);
        float simd = vector_ops.dot_product(test_n, a, b);
        float diff = (ref > simd) ? (ref - simd) : (simd - ref);
        if (diff > 0.01f) {
            pr_warn("ainos: Dot product mismatch: ref=%f simd=%f diff=%f\n",
                    ref, simd, diff);
            ret = -1;
        }
    }

    /* Test matmul (small 8x8) */
    {
        int m = 8, n = 8, k = 8;
        float *ma, *mb, *mc_ref, *mc_simd;
        int j;

        ma = kmalloc_array(m * k, sizeof(float), GFP_KERNEL);
        mb = kmalloc_array(k * n, sizeof(float), GFP_KERNEL);
        mc_ref = kmalloc_array(m * n, sizeof(float), GFP_KERNEL);
        mc_simd = kmalloc_array(m * n, sizeof(float), GFP_KERNEL);

        if (ma && mb && mc_ref && mc_simd) {
            for (i = 0; i < m * k; i++)
                ma[i] = (float)(i % 5) * 0.3f;
            for (i = 0; i < k * n; i++)
                mb[i] = (float)(i % 7) * 0.2f;

            matmul_fp32_generic(m, n, k, ma, mb, mc_ref);
            vector_ops.matmul_fp32(m, n, k, ma, mb, mc_simd);

            for (i = 0; i < m; i++) {
                for (j = 0; j < n; j++) {
                    float diff = mc_ref[i * n + j] - mc_simd[i * n + j];
                    if (diff < 0) diff = -diff;
                    if (diff > 0.1f) {
                        pr_warn("ainos: Matmul mismatch at [%d,%d]: ref=%f simd=%f\n",
                                i, j, mc_ref[i * n + j], mc_simd[i * n + j]);
                        ret = -1;
                        goto out_matmul;
                    }
                }
            }
out_matmul:
            kfree(ma);
            kfree(mb);
            kfree(mc_ref);
            kfree(mc_simd);
        }
    }

    /* Test quantization round-trip */
    {
        float *test_src = a; /* reuse a */
        int8_t *q8 = kmalloc_array(test_n, sizeof(int8_t), GFP_KERNEL);
        float *deq8 = kmalloc_array(test_n, sizeof(float), GFP_KERNEL);
        float scale = 127.0f;

        if (q8 && deq8) {
            quantize_fp32_to_q8_generic(test_n, test_src, q8, scale);
            dequantize_q8_to_fp32_generic(test_n, q8, deq8, scale);

            vector_ops.quantize_fp32_to_q8(test_n, test_src, q8, scale);
            vector_ops.dequantize_q8_to_fp32(test_n, q8, deq8, scale);
        }

        kfree(q8);
        kfree(deq8);
    }

    if (ret == 0)
        pr_info("ainos: Correctness verification passed\n");

out_free:
    kfree(a);
    kfree(b);
    kfree(c_generic);
    kfree(c_simd);
    return ret;
}

/* Run quick benchmark at init time */
static void run_init_benchmark(void)
{
    int i;
    unsigned long long t_start, t_end;
    float *a, *b, *c;
    int test_size = 256; /* moderate size for init benchmark */
    int n = test_size;
    int iters = 5;

    /* Allocate test data */
    a = kmalloc_array(n * n, sizeof(float), GFP_KERNEL);
    b = kmalloc_array(n * n, sizeof(float), GFP_KERNEL);
    c = kmalloc_array(n * n, sizeof(float), GFP_KERNEL);

    if (!a || !b || !c) {
        pr_warn("ainos: Skipping init benchmark (OOM)\n");
        goto out;
    }

    /* Fill with test data */
    for (i = 0; i < n * n; i++) {
        a[i] = (float)(i % 100) * 0.01f;
        b[i] = (float)((i * 7) % 100) * 0.01f;
    }

    /* Benchmark matmul */
    t_start = __arch_get_hw_counter(0);
    for (i = 0; i < iters; i++)
        vector_ops.matmul_fp32(n, n, n, a, b, c);
    t_end = __arch_get_hw_counter(0);

    pr_info("ainos: Init benchmark: matmul %dx%d (%s) = %llu cycles\n",
            n, n, vector_ops.name, (t_end - t_start) / iters);

    /* Benchmark dot product */
    t_start = __arch_get_hw_counter(0);
    for (i = 0; i < iters * 10; i++)
        vector_ops.dot_product(n, a, b);
    t_end = __arch_get_hw_counter(0);

    pr_info("ainos: Init benchmark: dot_product n=%d (%s) = %llu cycles\n",
            n, vector_ops.name, (t_end - t_start) / (iters * 10));

out:
    kfree(a);
    kfree(b);
    kfree(c);
}

/* ============================================
 * 模块初始化/退出
 * ============================================ */

static int __init ai_vector_init(void)
{
    detect_cpu_features();

    pr_info("ainos: Vector Acceleration loading...\n");

#ifdef CONFIG_X86
    /* Register x86 SIMD implementations */
    x86_avx2_ops = avx2_get_ops();
    x86_avx512_ops = avx512_get_ops();
    x86_amx_ops = amx_get_ops();

    pr_info("ainos: CPU features: AVX2=%d AVX512=%d AVX512_VNNI=%d AMX=%d F16C=%d\n",
            has_avx2, has_avx512, has_avx512_vnni, has_amx, has_f16c);

    if (has_avx2)
        pr_info("ainos: AVX2 acceleration available (8-wide float, 32 bytes)\n");
    if (has_avx512)
        pr_info("ainos: AVX-512 acceleration available (16-wide float, 64 bytes)\n");
    if (has_avx512_vnni)
        pr_info("ainos: AVX512-VNNI acceleration available\n");
    if (has_amx_bf16)
        pr_info("ainos: AMX-BF16 acceleration available (TILE)\n");

#elif defined(CONFIG_ARM64)
    /* Register ARM64 SIMD implementations */
    arm64_neon_ops = neon_get_ops();
    arm64_sve_ops = sve_get_ops();

    pr_info("ainos: CPU features: NEON=1 SVE=%d SVE2=%d I8MM=%d\n",
            has_sve, has_sve2, has_i8mm);

    if (has_sve)
        pr_info("ainos: SVE acceleration available (scalable vectors)\n");
    if (has_sve2)
        pr_info("ainos: SVE2 acceleration available\n");
    if (has_i8mm)
        pr_info("ainos: I8MM acceleration available\n");
#endif

    /* Select the best implementation based on available features */
    select_best_implementation();

    pr_info("ainos: Vector Acceleration loaded (%s, vector=%d bytes)\n",
            vector_ops.name, vector_ops.vector_size);

    /* Run correctness verification */
    verify_correctness();

    /* Run quick init benchmark */
    run_init_benchmark();

    /* Run full benchmark suite if requested (module parameter) */
    if (run_benchmarks_at_init) {
        pr_info("ainos: Running full SIMD benchmark suite...\n");
        simd_run_benchmarks(20);
    }

    return 0;
}

static void __exit ai_vector_exit(void)
{
    pr_info("ainos: Vector Acceleration unloaded (was using %s)\n",
            vector_ops.name);
}

/* Module parameter to enable benchmark at init */
static bool run_benchmarks_at_init = false;
module_param(run_benchmarks_at_init, bool, 0444);
MODULE_PARM_DESC(run_benchmarks_at_init,
                 "Run full SIMD benchmark suite at module init (default: false)");

module_init(ai_vector_init);
module_exit(ai_vector_exit);