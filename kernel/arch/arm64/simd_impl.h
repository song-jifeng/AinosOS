// SPDX-License-Identifier: GPL-2.0
/*
 * Ainos OS - ARM64 SIMD Vector Acceleration Implementation Header
 * ===============================================================
 * Declares all ARM64 SIMD optimizations (NEON, SVE, SVE2)
 * and their registration functions.
 */

#ifndef _ASM_ARM64_SIMD_IMPL_H
#define _ASM_ARM64_SIMD_IMPL_H

#include <linux/types.h>
#include <linux/module.h>
#include <linux/kernel.h>

/* ============================================
 * Forward declarations for function pointer types
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
 * ARM64 Feature Detection Macros
 * ============================================ */
#ifdef CONFIG_ARM64
#include <asm/cpufeature.h>

/* ARM64 always has NEON */
#define cpu_has_neon()       (1)
#define cpu_has_sve()        system_supports_sve()
#define cpu_has_sve2()       system_supports_sve2()
#define cpu_has_i8mm()       (system_capabilities_finalized() && \
                               cpus_have_cap(ARM64_HAS_I8MM))
#endif

/* ============================================
 * NEON Implementation Declarations
 * ============================================ */
#ifdef CONFIG_ARM64

/* Matrix multiply using NEON */
void neon_matmul_fp32(int m, int n, int k,
                       const float *a, const float *b, float *c);

/* Dot product using NEON */
float neon_dot_product(int n, const float *a, const float *b);

/* Quantize float32 to int8 using NEON */
void neon_quantize_fp32_to_q8(int n, const float *src, void *dst, float scale);

/* Quantize float32 to 4-bit using NEON */
void neon_quantize_fp32_to_q4(int n, const float *src, void *dst, float scale);

/* Dequantize int8 to float32 using NEON */
void neon_dequantize_q8_to_fp32(int n, const void *src, float *dst, float scale);

/* Dequantize 4-bit to float32 using NEON */
void neon_dequantize_q4_to_fp32(int n, const void *src, float *dst, float scale);

/* Batch dot product using NEON */
void neon_batch_dot_product(int batch_size, int n,
                             const float *a, const float *b, float *results);

/* Get NEON ops descriptor */
const struct simd_ops *neon_get_ops(void);

/* ============================================
 * SVE Implementation Declarations
 * ============================================ */

/* Matrix multiply using SVE */
void sve_matmul_fp32(int m, int n, int k,
                      const float *a, const float *b, float *c);

/* Dot product using SVE */
float sve_dot_product(int n, const float *a, const float *b);

/* Quantize float32 to int8 using SVE */
void sve_quantize_fp32_to_q8(int n, const float *src, void *dst, float scale);

/* Quantize float32 to 4-bit using SVE */
void sve_quantize_fp32_to_q4(int n, const float *src, void *dst, float scale);

/* Dequantize int8 to float32 using SVE */
void sve_dequantize_q8_to_fp32(int n, const void *src, float *dst, float scale);

/* Dequantize 4-bit to float32 using SVE */
void sve_dequantize_q4_to_fp32(int n, const void *src, float *dst, float scale);

/* Batch dot product using SVE */
void sve_batch_dot_product(int batch_size, int n,
                            const float *a, const float *b, float *results);

/* Get SVE ops descriptor */
const struct simd_ops *sve_get_ops(void);

/* ============================================
 * SVE2 Implementation Declarations
 * ============================================ */

/* Matrix multiply using SVE2 (with I8MM if available) */
void sve2_matmul_fp32(int m, int n, int k,
                       const float *a, const float *b, float *c);

/* Dot product using SVE2 */
float sve2_dot_product(int n, const float *a, const float *b);

/* Get SVE2 ops descriptor */
const struct simd_ops *sve2_get_ops(void);

/* ============================================
 * Benchmark Support
 * ============================================ */

/* Run benchmarks for all ARM64 SIMD implementations */
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

#endif /* CONFIG_ARM64 */

#endif /* _ASM_ARM64_SIMD_IMPL_H */