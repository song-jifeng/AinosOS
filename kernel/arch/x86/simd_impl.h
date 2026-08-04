// SPDX-License-Identifier: GPL-2.0
/*
 * Ainos OS - x86 SIMD Vector Acceleration Implementation Header
 * =============================================================
 * Declares all x86 SIMD optimizations (AVX2, AVX-512, AMX)
 * and their registration functions.
 */

#ifndef _ASM_X86_SIMD_IMPL_H
#define _ASM_X86_SIMD_IMPL_H

#include <linux/types.h>
#include <linux/module.h>
#include <linux/kernel.h>

/* ============================================
 * Forward declarations for function pointer types
 * used by the vector acceleration module
 * ============================================ */
typedef void (*matmul_fp32_fn_t)(int m, int n, int k,
                                  const float *a, const float *b, float *c);
typedef float (*dot_product_fn_t)(int n, const float *a, const float *b);
typedef void (*quantize_fn_t)(int n, const float *src, void *dst, float scale);
typedef void (*dequantize_fn_t)(int n, const void *src, float *dst, float scale);

/* SIMD ops descriptor for registration */
struct simd_ops {
    matmul_fp32_fn_t matmul_fp32;
    dot_product_fn_t dot_product;
    quantize_fn_t quantize_fp32_to_q8;
    quantize_fn_t quantize_fp32_to_q4;
    dequantize_fn_t dequantize_q8_to_fp32;
    dequantize_fn_t dequantize_q4_to_fp32;
    const char *name;
    int vector_size;   /* vector register width in bytes */
};

/* ============================================
 * x86 Feature Detection Macros
 * ============================================ */
#ifdef CONFIG_X86
#include <asm/cpufeature.h>

#define cpu_has_avx2()       boot_cpu_has(X86_FEATURE_AVX2)
#define cpu_has_avx512f()    boot_cpu_has(X86_FEATURE_AVX512F)
#define cpu_has_avx512_vnni() boot_cpu_has(X86_FEATURE_AVX512_VNNI)
#define cpu_has_avx512_bw()  boot_cpu_has(X86_FEATURE_AVX512BW)
#define cpu_has_avx512_dq()  boot_cpu_has(X86_FEATURE_AVX512DQ)
#define cpu_has_avx512_vl()  boot_cpu_has(X86_FEATURE_AVX512VL)
#define cpu_has_amx_tile()   boot_cpu_has(X86_FEATURE_AMX_TILE)
#define cpu_has_amx_bf16()   boot_cpu_has(X86_FEATURE_AMX_BF16)
#define cpu_has_amx_int8()   boot_cpu_has(X86_FEATURE_AMX_INT8)
#define cpu_has_f16c()       boot_cpu_has(X86_FEATURE_F16C)
#define cpu_has_ssse3()      boot_cpu_has(X86_FEATURE_SSSE3)
#endif

/* ============================================
 * AVX2 Implementation Declarations
 * ============================================ */
#ifdef CONFIG_X86

/* Matrix multiply: C = A * B  (A: m x k, B: k x n, C: m x n) */
void avx2_matmul_fp32(int m, int n, int k,
                       const float *a, const float *b, float *c);

/* Dot product: sum of a[i] * b[i] for i in [0, n) */
float avx2_dot_product(int n, const float *a, const float *b);

/* Quantize float32 to int8 (Q8) */
void avx2_quantize_fp32_to_q8(int n, const float *src, void *dst, float scale);

/* Quantize float32 to 4-bit (Q4) packed as uint8 */
void avx2_quantize_fp32_to_q4(int n, const float *src, void *dst, float scale);

/* Dequantize int8 (Q8) to float32 */
void avx2_dequantize_q8_to_fp32(int n, const void *src, float *dst, float scale);

/* Dequantize 4-bit (Q4) to float32 */
void avx2_dequantize_q4_to_fp32(int n, const void *src, float *dst, float scale);

/* Batch dot product: compute multiple dot products at once */
void avx2_batch_dot_product(int batch_size, int n,
                             const float *a, const float *b, float *results);

/* Get AVX2 ops descriptor */
const struct simd_ops *avx2_get_ops(void);

/* ============================================
 * AVX-512 Implementation Declarations
 * ============================================ */

/* Matrix multiply using AVX-512 */
void avx512_matmul_fp32(int m, int n, int k,
                         const float *a, const float *b, float *c);

/* Dot product using AVX-512 */
float avx512_dot_product(int n, const float *a, const float *b);

/* Quantize float32 to int8 using AVX-512 */
void avx512_quantize_fp32_to_q8(int n, const float *src, void *dst, float scale);

/* Quantize float32 to 4-bit using AVX-512 */
void avx512_quantize_fp32_to_q4(int n, const float *src, void *dst, float scale);

/* Dequantize int8 to float32 using AVX-512 */
void avx512_dequantize_q8_to_fp32(int n, const void *src, float *dst, float scale);

/* Dequantize 4-bit to float32 using AVX-512 */
void avx512_dequantize_q4_to_fp32(int n, const void *src, float *dst, float scale);

/* Batch dot product using AVX-512 */
void avx512_batch_dot_product(int batch_size, int n,
                               const float *a, const float *b, float *results);

/* Get AVX-512 ops descriptor */
const struct simd_ops *avx512_get_ops(void);

/* ============================================
 * AMX Implementation Declarations
 * ============================================ */

/* Matrix multiply using Intel AMX TILE */
void amx_matmul_fp32(int m, int n, int k,
                      const float *a, const float *b, float *c);

/* AMX tile configuration and management */
void amx_configure_tiles(void);
void amx_release_tiles(void);

/* Quantize using AMX */
void amx_quantize_fp32_to_q8(int n, const float *src, void *dst, float scale);
void amx_quantize_fp32_to_q4(int n, const float *src, void *dst, float scale);

/* Dequantize using AMX */
void amx_dequantize_q8_to_fp32(int n, const void *src, float *dst, float scale);
void amx_dequantize_q4_to_fp32(int n, const void *src, float *dst, float scale);

/* Get AMX ops descriptor */
const struct simd_ops *amx_get_ops(void);

/* ============================================
 * Benchmark Support
 * ============================================ */

/* Run benchmarks for all x86 SIMD implementations */
int simd_run_benchmarks(int iterations);

/* Benchmark result structure */
struct simd_bench_result {
    const char *impl_name;
    int size;
    unsigned long matmul_cycles;
    unsigned long dot_cycles;
    unsigned long quantize_cycles;
    unsigned long dequantize_cycles;
    float speedup_vs_generic;
};

/* Print benchmark results to kernel log */
void simd_print_benchmarks(const struct simd_bench_result *results, int count);

#endif /* CONFIG_X86 */

#endif /* _ASM_X86_SIMD_IMPL_H */