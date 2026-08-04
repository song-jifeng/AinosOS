// SPDX-License-Identifier: GPL-2.0
/*
 * Ainos OS - ARM64 SVE/SVE2 Vector Acceleration Implementation
 * =============================================================
 * Implements matrix multiply, dot product, and quantization
 * operations using ARM SVE (Scalable Vector Extension) and SVE2
 * instructions.
 *
 * SVE is a scalable vector extension that supports vector lengths
 * from 128 to 2048 bits in 128-bit increments. All code here is
 * written to work with any vector length, determined at runtime
 * via svcntw().
 *
 * SVE2 adds additional instructions:
 *   - svdot (dot product) for INT8 x INT8 accumulations
 *   - svmla (widening multiply-accumulate)
 *   - svqrdmlah (saturating rounding multiply-accumulate)
 *
 * Reference: ARM Architecture Reference Manual Supplement,
 *            The Scalable Vector Extension (SVE)
 */

#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/export.h>
#include <linux/string.h>
#include <linux/cache.h>
#include <linux/vmalloc.h>
#include <linux/random.h>
#include <linux/ktime.h>

#include <asm/neon.h>
#include <arm_sve.h>

#include "simd_impl.h"

/* ============================================
 * Module information
 * ============================================ */
MODULE_LICENSE("GPL");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("ARM SVE/SVE2 Vector Acceleration");
MODULE_VERSION("0.1.0");

/* ============================================
 * Constants
 * ============================================ */

/* Maximum SVE vector length in elements (2048 bits / 32 bits per float) */
#define SVE_MAX_F32_ELEMENTS 64

/* Tile sizes for blocked matrix multiply */
#define SVE_MC 256  /* row tile size for C */
#define SVE_NC 256  /* column tile size for C */
#define SVE_KC 512  /* inner dimension tile size */

/* Cache line size for prefetch */
#define SVE_CACHE_LINE 64

/* Default prefetch distance */
#define SVE_PREFETCH_DIST 8

/* ============================================
 * SVE vector length detection
 * ============================================ */

/* Get the number of float32 elements per SVE vector */
static inline int sve_f32_elements(void)
{
    return svcntw();
}

/* Get the SVE vector length in bytes */
static inline int sve_vector_bytes(void)
{
    return svcntw() * 4;
}

/* Get the SVE vector length in bits */
int sve_vector_length_bits(void)
{
    return svcntw() * 32;
}

/* ============================================
 * Helper: aligned allocation
 * ============================================
 * Use kernel allocation functions with extra space
 * for alignment offset tracking.
 */

static void *sve_aligned_alloc(size_t size, size_t align)
{
    void *ptr;
    size_t alloc_size = size + align + sizeof(void *);
    void **alloc_ptr;

    alloc_ptr = (void **)kmalloc(alloc_size, GFP_KERNEL);
    if (!alloc_ptr)
        return NULL;

    /* Store the original pointer at the beginning */
    ptr = (void *)alloc_ptr + sizeof(void *);

    /* Align the pointer */
    ptr = (void *)(((unsigned long)ptr + align - 1) & ~(align - 1));

    /* Store the original allocation pointer just before the aligned pointer */
    *((void **)ptr - 1) = (void *)alloc_ptr;

    return ptr;
}

static void sve_aligned_free(void *ptr)
{
    if (ptr) {
        void *orig_ptr = *((void **)ptr - 1);
        kfree(orig_ptr);
    }
}

/* ============================================
 * Helper: page-aligned allocation
 * ============================================ */

static void *sve_alloc_page_aligned(size_t size)
{
    return (void *)__get_free_pages(GFP_KERNEL,
                                     get_order(size));
}

static void sve_free_page_aligned(void *ptr, size_t size)
{
    if (ptr)
        free_pages((unsigned long)ptr, get_order(size));
}

/* ============================================
 * Helper: determine blocking parameters
 * based on SVE vector length
 * ============================================ */

struct sve_block_params {
    int mr;  /* row block size (multiple of vector length) */
    int nr;  /* column block size */
    int mc;  /* row cache tile */
    int nc;  /* column cache tile */
    int kc;  /* inner cache tile */
};

static void sve_get_block_params(struct sve_block_params *p)
{
    int vl = sve_f32_elements();

    /* MR is at least 4x the vector length for register blocking */
    p->mr = (vl > 8) ? vl : vl * 4;
    p->nr = (vl > 8) ? vl * 2 : vl * 4;

    /* Cache tile sizes, scaled by vector length */
    p->mc = p->mr * 8;
    p->nc = p->nr * 8;
    p->kc = 256;

    /* Cap at reasonable maximums */
    if (p->mc > SVE_MC) p->mc = SVE_MC;
    if (p->nc > SVE_NC) p->nc = SVE_NC;
    if (p->mr > 64) p->mr = 64;
    if (p->nr > 64) p->nr = 64;

    /* Ensure multiples of vector length */
    p->mr = (p->mr / vl) * vl;
    if (p->mr < vl) p->mr = vl;
    p->nr = (p->nr / vl) * vl;
    if (p->nr < vl) p->nr = vl;
}

/* ============================================
 * SVE matrix multiply (SGEMM)
 * ============================================
 *
 * Blocked SGEMM implementation using SVE scalable vectors.
 * The algorithm divides the matrices into tiles that fit in
 * cache, then processes each tile using SVE vector operations.
 *
 * C = A * B  where A is m x k, B is k x n, C is m x n
 *
 * Algorithm:
 *   for j = 0 to n-1 step NC:
 *     for p = 0 to k-1 step KC:
 *       pack B(p:min(k,p+KC), j:min(n,j+NC)) into packed_B
 *       for i = 0 to m-1 step MC:
 *         pack A(i:min(m,i+MC), p:min(k,p+KC)) into packed_A
 *         for jj = 0 to NC-1 step NR:
 *           for ii = 0 to MC-1 step MR:
 *             micro-kernel(packed_A+ii*KC, packed_B+jj*KC, C+i+ii, j+jj)
 */

/* ============================================
 * SVE micro-kernel: process MR x NR block
 * ============================================
 * Processes a single MR x NR output block by accumulating
 * over the K dimension. Uses SVE vectors for the NR dimension
 * and broadcasts scalar A values for the MR dimension.
 *
 * C[i][j] += sum over p of A[i][p] * B[p][j]
 *
 * Parameters:
 *   mr, nr: actual block dimensions (may be less than full tile)
 *   kc: inner dimension (number of K values to accumulate)
 *   a: packed A matrix (mr x kc, row-major), lda = kc
 *   b: packed B matrix (kc x nr, row-major), ldb = nr
 *   c: output C matrix (mr x n, row-major), ldc = n
 *   n: total column count of C (for stride)
 */

/* Full tile micro-kernel (general mr, nr) */
static void sve_micro_kernel(int mr, int nr, int kc,
                              const float *a, int lda,
                              const float *b, int ldb,
                              float *c, int ldc,
                              const struct sve_block_params *p)
{
    int vl = sve_f32_elements();
    int i, j, pp;

    for (i = 0; i < mr; i++) {
        for (j = 0; j < nr; j += vl) {
            svbool_t pg = svwhilelt_b32(j, nr);
            svfloat32_t acc = svld1_f32(pg, &c[i * ldc + j]);

            for (pp = 0; pp < kc; pp++) {
                float a_val = a[i * lda + pp];
                svfloat32_t b_vec = svld1_f32(pg, &b[pp * ldb + j]);
                acc = svmad_f32(pg, b_vec, a_val, acc);
            }

            svst1_f32(pg, &c[i * ldc + j], acc);
        }
    }
}

/* Unrolled micro-kernel for mr=1 (single row of A) */
static void sve_micro_kernel_mr1(int nr, int kc,
                                  const float *a, int lda,
                                  const float *b, int ldb,
                                  float *c, int ldc)
{
    int vl = sve_f32_elements();
    int j, pp;

    for (j = 0; j < nr; j += vl) {
        svbool_t pg = svwhilelt_b32(j, nr);
        svfloat32_t acc = svld1_f32(pg, &c[j]);

        for (pp = 0; pp < kc; pp++) {
            float a_val = a[pp]; /* mr=1, single row */
            svfloat32_t b_vec = svld1_f32(pg, &b[pp * ldb + j]);
            acc = svmad_f32(pg, b_vec, a_val, acc);
        }

        svst1_f32(pg, &c[j], acc);
    }
}

/* Unrolled micro-kernel for nr=1 (single column of B) */
static void sve_micro_kernel_nr1(int mr, int kc,
                                  const float *a, int lda,
                                  const float *b, int ldb,
                                  float *c, int ldc)
{
    int i, pp;

    for (i = 0; i < mr; i++) {
        float acc = c[i * ldc];

        for (pp = 0; pp < kc; pp++) {
            acc += a[i * lda + pp] * b[pp * ldb]; /* nr=1, single column */
        }

        c[i * ldc] = acc;
    }
}

/* ============================================
 * Direct micro-kernel for small matrices
 * ============================================ */

static void sve_micro_kernel_small(int m, int n, int k,
                                    const float *a, int lda,
                                    const float *b, int ldb,
                                    float *c, int ldc)
{
    int vl = sve_f32_elements();
    int i, j, pp;

    for (i = 0; i < m; i++) {
        for (j = 0; j < n; j += vl) {
            svbool_t pg = svwhilelt_b32(j, n);
            svfloat32_t acc = svld1_f32(pg, &c[i * ldc + j]);

            for (pp = 0; pp < k; pp++) {
                float a_val = a[i * lda + pp];
                svfloat32_t b_vec = svld1_f32(pg, &b[pp * ldb + j]);
                acc = svmad_f32(pg, b_vec, a_val, acc);
            }

            svst1_f32(pg, &c[i * ldc + j], acc);
        }
    }
}

/* ============================================
 * Packing functions
 * ============================================
 * Pack A and B matrices into contiguous buffers
 * to improve cache utilization during the micro-kernel.
 */

/* Pack A: row-major, MR rows x KC columns */
static void sve_pack_a(int mr, int kc,
                        const float *a, int lda,
                        float *packed_a)
{
    int i, pp;

    for (i = 0; i < mr; i++) {
        for (pp = 0; pp < kc; pp++) {
            packed_a[i * kc + pp] = a[i * lda + pp];
        }
    }
}

/* Pack A with transpose for better access pattern */
static void sve_pack_a_transposed(int mr, int kc,
                                   const float *a, int lda,
                                   float *packed_a)
{
    int i, pp;

    for (pp = 0; pp < kc; pp++) {
        for (i = 0; i < mr; i++) {
            packed_a[pp * mr + i] = a[i * lda + pp];
        }
    }
}

/* Pack B: row-major, KC rows x NR columns */
static void sve_pack_b(int nr, int kc,
                        const float *b, int ldb,
                        float *packed_b)
{
    int vl = sve_f32_elements();
    int pp, j;

    for (pp = 0; pp < kc; pp++) {
        for (j = 0; j < nr; j += vl) {
            svbool_t pg = svwhilelt_b32(j, nr);
            svfloat32_t vb = svld1_f32(pg, &b[pp * ldb + j]);
            svst1_f32(pg, &packed_b[pp * nr + j], vb);
        }
    }
}

/* Pack B with interleaving for better cache access */
static void sve_pack_b_interleaved(int nr, int kc,
                                    const float *b, int ldb,
                                    float *packed_b, int interleave)
{
    int pp, j, ii;

    for (pp = 0; pp < kc; pp += interleave) {
        int kk = (kc - pp < interleave) ? (kc - pp) : interleave;
        for (j = 0; j < nr; j++) {
            for (ii = 0; ii < kk; ii++) {
                packed_b[(pp + ii) * nr + j] = b[(pp + ii) * ldb + j];
            }
        }
    }
}

/* ============================================
 * SVE SGEMM: main entry point
 * ============================================ */

void sve_matmul_fp32(int m, int n, int k,
                      const float *a, const float *b, float *c)
{
    struct sve_block_params params;
    float *packed_a = NULL;
    float *packed_b = NULL;
    int i, j, pp;
    int mc, nc, kc, mr, nr;

    /* Handle trivial cases */
    if (m <= 0 || n <= 0 || k <= 0)
        return;

    /* Use kernel_neon_begin() for SVE context (SVE shares FPU with NEON) */
    kernel_neon_begin();

    /* Get blocking parameters based on SVE vector length */
    sve_get_block_params(&params);
    mc = params.mc;
    nc = params.nc;
    kc = params.kc;
    mr = params.mr;
    nr = params.nr;

    /* For very small matrices, use direct micro-kernel */
    if (m <= mc && n <= nc && k <= kc) {
        sve_micro_kernel_small(m, n, k, a, k, b, n, c, n);
        kernel_neon_end();
        return;
    }

    /* Allocate packing buffers */
    packed_a = (float *)kmalloc(mc * kc * sizeof(float), GFP_KERNEL);
    packed_b = (float *)kmalloc(nc * kc * sizeof(float), GFP_KERNEL);

    if (!packed_a || !packed_b) {
        /* Fallback to direct micro-kernel */
        if (packed_a) kfree(packed_a);
        if (packed_b) kfree(packed_b);
        sve_micro_kernel_small(m, n, k, a, k, b, n, c, n);
        kernel_neon_end();
        return;
    }

    /* Blocked SGEMM with packing */
    for (j = 0; j < n; j += nc) {
        int nc_block = (n - j < nc) ? (n - j) : nc;

        for (pp = 0; pp < k; pp += kc) {
            int kc_block = (k - pp < kc) ? (k - pp) : kc;

            /* Pack B block */
            sve_pack_b(nc_block, kc_block, &b[pp * n + j], n, packed_b);

            for (i = 0; i < m; i += mc) {
                int mc_block = (m - i < mc) ? (m - i) : mc;
                int ii, jj;

                /* Pack A block */
                sve_pack_a(mc_block, kc_block, &a[i * k + pp], k, packed_a);

                /* Process micro-kernel on this block */
                for (ii = 0; ii < mc_block; ii += mr) {
                    int mr_block = (mc_block - ii < mr) ? (mc_block - ii) : mr;

                    for (jj = 0; jj < nc_block; jj += nr) {
                        int nr_block = (nc_block - jj < nr) ? (nc_block - jj) : nr;

                        /* Use specialized kernel for common cases */
                        if (mr_block == 1) {
                            sve_micro_kernel_mr1(nr_block, kc_block,
                                                  &packed_a[ii * kc_block], kc_block,
                                                  &packed_b[jj * kc_block], nc_block,
                                                  &c[(i + ii) * n + (j + jj)], n);
                        } else if (nr_block == 1) {
                            sve_micro_kernel_nr1(mr_block, kc_block,
                                                  &packed_a[ii * kc_block], kc_block,
                                                  &packed_b[jj * kc_block], nc_block,
                                                  &c[(i + ii) * n + (j + jj)], n);
                        } else {
                            sve_micro_kernel(mr_block, nr_block, kc_block,
                                              &packed_a[ii * kc_block], kc_block,
                                              &packed_b[jj * kc_block], nc_block,
                                              &c[(i + ii) * n + (j + jj)], n,
                                              &params);
                        }
                    }
                }
            }
        }
    }

    kfree(packed_a);
    kfree(packed_b);

    kernel_neon_end();
}

/* ============================================
 * SVE matrix multiply variants for different shapes
 * ============================================ */

/* Tall-skinny matrices (m >> n) */
void sve_matmul_tall(int m, int n, int k,
                      const float *a, const float *b, float *c)
{
    /* Use the same blocked algorithm with adjusted parameters */
    sve_matmul_fp32(m, n, k, a, b, c);
}

/* Short-wide matrices (n >> m) */
void sve_matmul_wide(int m, int n, int k,
                      const float *a, const float *b, float *c)
{
    sve_matmul_fp32(m, n, k, a, b, c);
}

/* Square matrices optimized path */
void sve_matmul_square(int n, const float *a, const float *b, float *c)
{
    sve_matmul_fp32(n, n, n, a, b, c);
}

/* ============================================
 * SVE dot product
 * ============================================ */

float sve_dot_product(int n, const float *a, const float *b)
{
    int vl = sve_f32_elements();
    int i;
    svfloat32_t sum_vec = svdup_f32(0.0f);

    if (n <= 0)
        return 0.0f;

    kernel_neon_begin();

    /* Process full vectors */
    for (i = 0; i + vl <= n; i += vl) {
        svfloat32_t va = svld1_f32(svptrue_b32(), &a[i]);
        svfloat32_t vb = svld1_f32(svptrue_b32(), &b[i]);
        sum_vec = svmad_f32(svptrue_b32(), va, vb, sum_vec);
    }

    /* Handle remainder */
    if (i < n) {
        svbool_t pg = svwhilelt_b32(i, n);
        svfloat32_t va = svld1_f32(pg, &a[i]);
        svfloat32_t vb = svld1_f32(pg, &b[i]);
        sum_vec = svmad_f32(pg, va, vb, sum_vec);
    }

    /* Horizontal reduction */
    float result = svaddv_f32(svptrue_b32(), sum_vec);

    kernel_neon_end();

    return result;
}

/* ============================================
 * SVE dot product with unrolling
 * ============================================ */

float sve_dot_product_unrolled(int n, const float *a, const float *b)
{
    int vl = sve_f32_elements();
    int step = vl * 4; /* process 4 vectors at a time */
    int i;
    svfloat32_t sum0 = svdup_f32(0.0f);
    svfloat32_t sum1 = svdup_f32(0.0f);
    svfloat32_t sum2 = svdup_f32(0.0f);
    svfloat32_t sum3 = svdup_f32(0.0f);

    if (n <= 0)
        return 0.0f;

    kernel_neon_begin();

    /* Process 4 vectors at a time with independent accumulators */
    for (i = 0; i + step <= n; i += step) {
        svbool_t pg = svptrue_b32();

        svfloat32_t va0 = svld1_f32(pg, &a[i]);
        svfloat32_t vb0 = svld1_f32(pg, &b[i]);
        sum0 = svmad_f32(pg, va0, vb0, sum0);

        svfloat32_t va1 = svld1_f32(pg, &a[i + vl]);
        svfloat32_t vb1 = svld1_f32(pg, &b[i + vl]);
        sum1 = svmad_f32(pg, va1, vb1, sum1);

        svfloat32_t va2 = svld1_f32(pg, &a[i + vl * 2]);
        svfloat32_t vb2 = svld1_f32(pg, &b[i + vl * 2]);
        sum2 = svmad_f32(pg, va2, vb2, sum2);

        svfloat32_t va3 = svld1_f32(pg, &a[i + vl * 3]);
        svfloat32_t vb3 = svld1_f32(pg, &b[i + vl * 3]);
        sum3 = svmad_f32(pg, va3, vb3, sum3);
    }

    /* Handle remaining full vectors */
    for (; i + vl <= n; i += vl) {
        svfloat32_t va = svld1_f32(svptrue_b32(), &a[i]);
        svfloat32_t vb = svld1_f32(svptrue_b32(), &b[i]);
        sum0 = svmad_f32(svptrue_b32(), va, vb, sum0);
    }

    /* Handle remainder */
    if (i < n) {
        svbool_t pg = svwhilelt_b32(i, n);
        svfloat32_t va = svld1_f32(pg, &a[i]);
        svfloat32_t vb = svld1_f32(pg, &b[i]);
        sum0 = svmad_f32(pg, va, vb, sum0);
    }

    /* Combine accumulators and reduce */
    sum0 = svadd_f32(svptrue_b32(), sum0, sum1);
    sum2 = svadd_f32(svptrue_b32(), sum2, sum3);
    sum0 = svadd_f32(svptrue_b32(), sum0, sum2);

    float result = svaddv_f32(svptrue_b32(), sum0);

    kernel_neon_end();

    return result;
}

/* ============================================
 * SVE batch dot product
 * ============================================ */

void sve_batch_dot_product(int batch_size, int n,
                            const float *a, const float *b,
                            float *results)
{
    int vl = sve_f32_elements();
    int b, i;

    if (batch_size <= 0 || n <= 0)
        return;

    kernel_neon_begin();

    for (b = 0; b < batch_size; b++) {
        const float *a_batch = &a[b * n];
        const float *b_batch = &b[b * n];
        svfloat32_t sum_vec = svdup_f32(0.0f);

        /* Process full vectors */
        for (i = 0; i + vl <= n; i += vl) {
            svfloat32_t va = svld1_f32(svptrue_b32(), &a_batch[i]);
            svfloat32_t vb = svld1_f32(svptrue_b32(), &b_batch[i]);
            sum_vec = svmad_f32(svptrue_b32(), va, vb, sum_vec);
        }

        /* Handle remainder */
        if (i < n) {
            svbool_t pg = svwhilelt_b32(i, n);
            svfloat32_t va = svld1_f32(pg, &a_batch[i]);
            svfloat32_t vb = svld1_f32(pg, &b_batch[i]);
            sum_vec = svmad_f32(pg, va, vb, sum_vec);
        }

        results[b] = svaddv_f32(svptrue_b32(), sum_vec);
    }

    kernel_neon_end();
}

/* ============================================
 * SVE quantize float32 to int8 (Q8)
 * ============================================
 * Convert float array to int8 with scaling:
 *   dst[i] = (int8_t)(src[i] * scale)
 *
 * SVE int8 vectors are 4x wider than float32 vectors
 * (svcntb() = 4 * svcntw()). We process 4*VL float32
 * values at a time and narrow them into one int8 vector.
 *
 * Narrowing chain: int32 -> int16 -> int8
 *   svqxtnb_s32: narrow low half of int32 to int16
 *   svqxtnt_s32: narrow to int16, interleave into high half
 *   svqxtnb_s16: narrow low half of int16 to int8
 *   svqxtnt_s16: narrow to int8, interleave into high half
 */

void sve_quantize_fp32_to_q8(int n, const float *src, void *dst, float scale)
{
    int vl = sve_f32_elements();  /* float32 elements per SVE vector */
    int step = vl * 4;            /* 4*VL float32 -> 1 SVE int8 vector */
    int i;
    int8_t *dst8 = (int8_t *)dst;

    if (n <= 0)
        return;

    kernel_neon_begin();

    /* Process 4*VL float32 values at a time */
    for (i = 0; i + step <= n; i += step) {
        svbool_t pg = svptrue_b32();

        /* Load 4 vectors of float32 */
        svfloat32_t v0 = svld1_f32(pg, &src[i]);
        svfloat32_t v1 = svld1_f32(pg, &src[i + vl]);
        svfloat32_t v2 = svld1_f32(pg, &src[i + vl * 2]);
        svfloat32_t v3 = svld1_f32(pg, &src[i + vl * 3]);

        /* Scale and convert to int32 */
        svint32_t i32_0 = svcvt_s32_f32_x(pg, svmul_f32_x(pg, v0, scale));
        svint32_t i32_1 = svcvt_s32_f32_x(pg, svmul_f32_x(pg, v1, scale));
        svint32_t i32_2 = svcvt_s32_f32_x(pg, svmul_f32_x(pg, v2, scale));
        svint32_t i32_3 = svcvt_s32_f32_x(pg, svmul_f32_x(pg, v3, scale));

        /* Narrow int32 -> int16 (pairwise) */
        svint16_t i16_01 = svqxtnb_s32(i32_0);
        i16_01 = svqxtnt_s32(i16_01, i32_1);

        svint16_t i16_23 = svqxtnb_s32(i32_2);
        i16_23 = svqxtnt_s32(i16_23, i32_3);

        /* Narrow int16 -> int8 */
        svint8_t i8 = svqxtnb_s16(i16_01);
        i8 = svqxtnt_s16(i8, i16_23);

        /* Store as int8 */
        svst1_s8(svptrue_b8(), &dst8[i], i8);
    }

    /* Handle remainder with scalar fallback */
    for (; i < n; i++) {
        dst8[i] = (int8_t)(src[i] * scale);
    }

    kernel_neon_end();
}

/* ============================================
 * SVE quantize float32 to 4-bit (Q4)
 * ============================================
 * Pack two 4-bit values per byte:
 *   byte = (v0 & 0x0F) | ((v1 & 0x0F) << 4)
 *
 * Since 4-bit packing is byte-level, we process
 * pairs of float32 values and pack them into bytes.
 * For SVE, we use the vector capability to load/scale
 * pairs efficiently.
 */

void sve_quantize_fp32_to_q4(int n, const float *src, void *dst, float scale)
{
    int i;
    int vl = sve_f32_elements();
    uint8_t *dst4 = (uint8_t *)dst;

    if (n <= 0)
        return;

    kernel_neon_begin();

    /* Process using SVE for batches of elements */
    /* Process 2*vl float32 values at a time (produces vl bytes) */
    int step = 2 * vl;
    for (i = 0; i + step <= n; i += step) {
        svbool_t pg = svptrue_b32();

        /* Load two vectors of float32 */
        svfloat32_t v0 = svld1_f32(pg, &src[i]);
        svfloat32_t v1 = svld1_f32(pg, &src[i + vl]);

        /* Scale */
        svfloat32_t vs0 = svmul_f32_x(pg, v0, scale);
        svfloat32_t vs1 = svmul_f32_x(pg, v1, scale);

        /* Convert to int32 */
        svint32_t i32_0 = svcvt_s32_f32_x(pg, vs0);
        svint32_t i32_1 = svcvt_s32_f32_x(pg, vs1);

        /* Narrow to int16, then int8 */
        svint16_t i16 = svqxtnb_s32(i32_0);
        i16 = svqxtnt_s32(i16, i32_1);

        /* Narrow to int8 */
        svint8_t i8 = svqxtnb_s16(i16);

        /* Now we have vl int8 values. Pack two per byte.
         * For each pair: byte = (i8[2j] & 0x0F) | ((i8[2j+1] & 0x0F) << 4)
         * This is a scalar operation since SVE doesn't have
         * direct nibble packing instructions. */
        int j;
        int8_t tmp[64];
        svst1_s8(svptrue_b8(), tmp, i8);

        for (j = 0; j < vl; j += 2) {
            int8_t v0 = tmp[j];
            int8_t v1 = (j + 1 < vl) ? tmp[j + 1] : 0;
            dst4[(i + j) / 2] = (uint8_t)((v0 & 0x0F) | ((v1 & 0x0F) << 4));
        }
    }

    /* Handle remainder */
    for (; i < n; i += 2) {
        if (i + 1 < n) {
            int8_t v0 = (int8_t)(src[i] * scale);
            int8_t v1 = (int8_t)(src[i + 1] * scale);
            dst4[i / 2] = (uint8_t)((v0 & 0x0F) | ((v1 & 0x0F) << 4));
        } else {
            int8_t v0 = (int8_t)(src[i] * scale);
            dst4[i / 2] = (uint8_t)(v0 & 0x0F);
        }
    }

    kernel_neon_end();
}

/* ============================================
 * SVE dequantize int8 to float32
 * ============================================
 * Convert int8 back to float32:
 *   dst[i] = (float)src[i] / scale
 *
 * Uses svld1sb_s32 to load int8 values and sign-extend
 * to int32 in a single SVE operation.
 */

void sve_dequantize_q8_to_fp32(int n, const void *src, float *dst, float scale)
{
    int vl = sve_f32_elements();
    int i;
    const int8_t *src8 = (const int8_t *)src;
    float inv_scale = 1.0f / scale;

    if (n <= 0)
        return;

    kernel_neon_begin();

    /* Process full vectors: load int8, sign-extend to int32, convert to float */
    for (i = 0; i + vl <= n; i += vl) {
        svbool_t pg = svptrue_b32();

        /* Load int8 and sign-extend to int32 */
        svint32_t vi32 = svld1sb_s32(pg, &src8[i]);

        /* Convert int32 to float32 */
        svfloat32_t vf = svcvt_f32_s32_x(pg, vi32);

        /* Scale */
        vf = svmul_f32_x(pg, vf, inv_scale);

        /* Store */
        svst1_f32(pg, &dst[i], vf);
    }

    /* Handle remainder */
    for (; i < n; i++) {
        dst[i] = (float)src8[i] * inv_scale;
    }

    kernel_neon_end();
}

/* ============================================
 * SVE dequantize 4-bit to float32
 * ============================================
 * Unpack 4-bit values:
 *   dst[i]   = (float)(int8_t)(byte & 0x0F) / scale
 *   dst[i+1] = (float)(int8_t)(byte >> 4) / scale
 *
 * We process 8 bytes at a time (16 values) using SVE
 * for the final store, with scalar unpacking of nibbles.
 */

void sve_dequantize_q4_to_fp32(int n, const void *src, float *dst, float scale)
{
    int vl = sve_f32_elements();
    int i;
    const uint8_t *src4 = (const uint8_t *)src;
    float inv_scale = 1.0f / scale;

    if (n <= 0)
        return;

    kernel_neon_begin();

    /* Process 2*vl float32 values at a time (vl bytes of packed data) */
    int step = 2 * vl;
    for (i = 0; i + step <= n; i += step) {
        int j;
        float tmp[128]; /* max vl = 64 */
        int half_vl = vl;

        for (j = 0; j < half_vl; j++) {
            uint8_t byte = src4[i / 2 + j];
            tmp[j * 2] = (float)(int8_t)(byte & 0x0F) * inv_scale;
            tmp[j * 2 + 1] = (float)(int8_t)(byte >> 4) * inv_scale;
        }

        /* Store using SVE */
        svbool_t pg = svptrue_b32();
        svst1_f32(pg, &dst[i], svld1_f32(pg, &tmp[0]));
        if (vl > 0) {
            svst1_f32(pg, &dst[i + vl], svld1_f32(pg, &tmp[vl]));
        }
    }

    /* Handle remainder */
    for (; i < n; i += 2) {
        if (i + 1 < n) {
            uint8_t byte = src4[i / 2];
            dst[i] = (float)(int8_t)(byte & 0x0F) * inv_scale;
            dst[i + 1] = (float)(int8_t)(byte >> 4) * inv_scale;
        } else {
            uint8_t byte = src4[i / 2];
            dst[i] = (float)(int8_t)(byte & 0x0F) * inv_scale;
        }
    }

    kernel_neon_end();
}

/* ============================================
 * SVE2 dot product
 * ============================================
 * SVE2 adds svdot for INT8 dot product accumulation.
 * For float32, we use the same algorithm as SVE but
 * with SVE2-specific optimizations if available.
 */

float sve2_dot_product(int n, const float *a, const float *b)
{
    /* SVE2 dot product for float32 uses same algorithm as SVE */
    return sve_dot_product_unrolled(n, a, b);
}

/* ============================================
 * SVE2 matrix multiply (with SVE2 optimizations)
 * ============================================ */

void sve2_matmul_fp32(int m, int n, int k,
                       const float *a, const float *b, float *c)
{
    /* SVE2 matmul for float32 uses same algorithm as SVE */
    sve_matmul_fp32(m, n, k, a, b, c);
}

/* ============================================
 * SVE utility functions
 * ============================================ */

/* Check if SVE2 is available (compile-time check) */
int sve_has_sve2(void)
{
#ifdef __ARM_FEATURE_SVE2
    return 1;
#else
    return 0;
#endif
}

/* Get SVE vector length in bytes */
int sve_get_vector_length(void)
{
    return sve_vector_bytes();
}

/* Get SVE vector length in float32 elements */
int sve_get_vector_length_f32(void)
{
    return sve_f32_elements();
}

/* ============================================
 * SVE prefetch helpers
 * ============================================ */

static inline void sve_prefetch_l1(const void *addr)
{
    __asm__ volatile("prfm pldl1keep, %a0" : : "p" (addr));
}

static inline void sve_prefetch_l2(const void *addr)
{
    __asm__ volatile("prfm pldl2keep, %a0" : : "p" (addr));
}

static inline void sve_prefetch_l3(const void *addr)
{
    __asm__ volatile("prfm pldl3keep, %a0" : : "p" (addr));
}

/* ============================================
 * SVE self-test functions
 * ============================================ */

/* Verify dot product against generic implementation */
static int sve_test_dot_product(int n)
{
    int i;
    float *a, *b;
    float ref, result;
    int ret = 0;

    a = kmalloc_array(n, sizeof(float), GFP_KERNEL);
    b = kmalloc_array(n, sizeof(float), GFP_KERNEL);

    if (!a || !b) {
        kfree(a);
        kfree(b);
        return -ENOMEM;
    }

    for (i = 0; i < n; i++) {
        a[i] = (float)(i % 100) * 0.1f;
        b[i] = (float)((i * 7) % 100) * 0.1f;
    }

    /* Compute reference */
    ref = 0.0f;
    for (i = 0; i < n; i++)
        ref += a[i] * b[i];

    /* Compute SVE result */
    result = sve_dot_product(n, a, b);

    /* Compare */
    if (result - ref > 0.01f || ref - result > 0.01f) {
        pr_err("sve: Dot product test FAILED: ref=%f, sve=%f\n", ref, result);
        ret = -1;
    }

    kfree(a);
    kfree(b);
    return ret;
}

/* Verify matmul against generic implementation */
static int sve_test_matmul(int m, int n, int k)
{
    int i, j;
    float *a, *b, *c_ref, *c_sve;
    int ret = 0;

    a = kmalloc_array(m * k, sizeof(float), GFP_KERNEL);
    b = kmalloc_array(k * n, sizeof(float), GFP_KERNEL);
    c_ref = kmalloc_array(m * n, sizeof(float), GFP_KERNEL);
    c_sve = kmalloc_array(m * n, sizeof(float), GFP_KERNEL);

    if (!a || !b || !c_ref || !c_sve) {
        kfree(a);
        kfree(b);
        kfree(c_ref);
        kfree(c_sve);
        return -ENOMEM;
    }

    for (i = 0; i < m * k; i++)
        a[i] = (float)(i % 50) * 0.2f;
    for (i = 0; i < k * n; i++)
        b[i] = (float)(i % 30) * 0.1f;

    /* Reference */
    for (i = 0; i < m; i++) {
        for (j = 0; j < n; j++) {
            float sum = 0.0f;
            for (int p = 0; p < k; p++)
                sum += a[i * k + p] * b[p * n + j];
            c_ref[i * n + j] = sum;
        }
    }

    /* SVE result */
    memset(c_sve, 0, m * n * sizeof(float));
    sve_matmul_fp32(m, n, k, a, b, c_sve);

    /* Verify */
    for (i = 0; i < m; i++) {
        for (j = 0; j < n; j++) {
            float diff = c_ref[i * n + j] - c_sve[i * n + j];
            if (diff < 0) diff = -diff;
            if (diff > 0.1f) {
                pr_err("sve: Matmul test FAILED at [%d,%d]: ref=%f, sve=%f\n",
                       i, j, c_ref[i * n + j], c_sve[i * n + j]);
                ret = -1;
                goto out;
            }
        }
    }

out:
    kfree(a);
    kfree(b);
    kfree(c_ref);
    kfree(c_sve);
    return ret;
}

/* Verify quantize/dequantize round-trip */
static int sve_test_quantize(int n)
{
    int i;
    float *src, *dst;
    int8_t *q8;
    float scale = 127.0f;
    int ret = 0;

    src = kmalloc_array(n, sizeof(float), GFP_KERNEL);
    dst = kmalloc_array(n, sizeof(float), GFP_KERNEL);
    q8 = kmalloc_array(n, sizeof(int8_t), GFP_KERNEL);

    if (!src || !dst || !q8) {
        kfree(src);
        kfree(dst);
        kfree(q8);
        return -ENOMEM;
    }

    for (i = 0; i < n; i++)
        src[i] = (float)(i % 100) * 0.01f - 0.5f;

    sve_quantize_fp32_to_q8(n, src, q8, scale);
    sve_dequantize_q8_to_fp32(n, q8, dst, scale);

    for (i = 0; i < n; i++) {
        float diff = src[i] - dst[i];
        if (diff < 0) diff = -diff;
        if (diff > 0.02f) {
            pr_err("sve: Quantize round-trip FAILED at %d: src=%f, dst=%f\n",
                   i, src[i], dst[i]);
            ret = -1;
            break;
        }
    }

    kfree(src);
    kfree(dst);
    kfree(q8);
    return ret;
}

/* Run all SVE self-tests */
int sve_run_self_tests(void)
{
    int ret = 0;

    pr_info("sve: Running self-tests (vector length = %d bits)\n",
            sve_vector_length_bits());

    if (sve_test_dot_product(100) < 0) {
        pr_err("sve: dot product test FAILED\n");
        ret = -1;
    } else {
        pr_info("sve: dot product test PASSED\n");
    }

    if (sve_test_matmul(16, 16, 16) < 0) {
        pr_err("sve: matmul 16x16 test FAILED\n");
        ret = -1;
    } else {
        pr_info("sve: matmul 16x16 test PASSED\n");
    }

    if (sve_test_matmul(32, 32, 32) < 0) {
        pr_err("sve: matmul 32x32 test FAILED\n");
        ret = -1;
    } else {
        pr_info("sve: matmul 32x32 test PASSED\n");
    }

    if (sve_test_quantize(128) < 0) {
        pr_err("sve: quantize round-trip test FAILED\n");
        ret = -1;
    } else {
        pr_info("sve: quantize round-trip test PASSED\n");
    }

    if (ret == 0)
        pr_info("sve: All self-tests PASSED\n");

    return ret;
}

/* ============================================
 * SVE benchmark functions
 * ============================================ */

/* Benchmark dot product */
static unsigned long sve_bench_dot_product(int n, int iterations)
{
    int i;
    float *a, *b;
    unsigned long t_start, t_end;

    a = kmalloc_array(n, sizeof(float), GFP_KERNEL);
    b = kmalloc_array(n, sizeof(float), GFP_KERNEL);

    if (!a || !b) {
        kfree(a);
        kfree(b);
        return 0;
    }

    get_random_bytes(a, n * sizeof(float));
    get_random_bytes(b, n * sizeof(float));

    /* Normalize to avoid overflow */
    for (i = 0; i < n; i++) {
        a[i] = (a[i] / (float)INT_MAX) * 0.5f;
        b[i] = (b[i] / (float)INT_MAX) * 0.5f;
    }

    t_start = ktime_get_ns();
    for (i = 0; i < iterations; i++)
        sve_dot_product_unrolled(n, a, b);
    t_end = ktime_get_ns();

    kfree(a);
    kfree(b);

    return (t_end - t_start) / iterations;
}

/* Benchmark matmul */
static unsigned long sve_bench_matmul(int n, int iterations)
{
    int i;
    float *a, *b, *c;
    unsigned long t_start, t_end;

    a = kmalloc_array(n * n, sizeof(float), GFP_KERNEL);
    b = kmalloc_array(n * n, sizeof(float), GFP_KERNEL);
    c = kmalloc_array(n * n, sizeof(float), GFP_KERNEL);

    if (!a || !b || !c) {
        kfree(a);
        kfree(b);
        kfree(c);
        return 0;
    }

    get_random_bytes(a, n * n * sizeof(float));
    get_random_bytes(b, n * n * sizeof(float));

    for (i = 0; i < n * n; i++) {
        a[i] = (a[i] / (float)INT_MAX) * 0.5f;
        b[i] = (b[i] / (float)INT_MAX) * 0.5f;
    }

    t_start = ktime_get_ns();
    for (i = 0; i < iterations; i++)
        sve_matmul_fp32(n, n, n, a, b, c);
    t_end = ktime_get_ns();

    kfree(a);
    kfree(b);
    kfree(c);

    return (t_end - t_start) / iterations;
}

/* Run SVE benchmarks */
void sve_run_benchmarks(int iterations)
{
    int sizes[] = {64, 128, 256, 512};
    int nsizes = 4;
    int s;

    pr_info("sve: Running benchmarks (vector=%d bits, %d iterations)\n",
            sve_vector_length_bits(), iterations);

    for (s = 0; s < nsizes; s++) {
        int n = sizes[s];
        unsigned long dot_time = sve_bench_dot_product(n, iterations);
        unsigned long matmul_time = sve_bench_matmul(n, iterations);

        if (dot_time > 0)
            pr_info("sve: dot_product n=%d: %lu ns/iter\n", n, dot_time);
        if (matmul_time > 0)
            pr_info("sve: matmul %dx%d: %lu ns/iter\n", n, n, matmul_time);
    }
}

/* ============================================
 * SVE ops registration
 * ============================================ */

static struct simd_ops sve_ops = {
    .matmul_fp32 = sve_matmul_fp32,
    .dot_product = sve_dot_product_unrolled,
    .quantize_fp32_to_q8 = sve_quantize_fp32_to_q8,
    .quantize_fp32_to_q4 = sve_quantize_fp32_to_q4,
    .dequantize_q8_to_fp32 = sve_dequantize_q8_to_fp32,
    .dequantize_q4_to_fp32 = sve_dequantize_q4_to_fp32,
    .name = "sve",
    .vector_size = 0,  /* Set at runtime based on svcntw() */
};

static struct simd_ops sve2_ops = {
    .matmul_fp32 = sve2_matmul_fp32,
    .dot_product = sve2_dot_product,
    .quantize_fp32_to_q8 = sve_quantize_fp32_to_q8,
    .quantize_fp32_to_q4 = sve_quantize_fp32_to_q4,
    .dequantize_q8_to_fp32 = sve_dequantize_q8_to_fp32,
    .dequantize_q4_to_fp32 = sve_dequantize_q4_to_fp32,
    .name = "sve2",
    .vector_size = 0,  /* Set at runtime */
};

const struct simd_ops *sve_get_ops(void)
{
    /* Set vector size at first call */
    if (sve_ops.vector_size == 0)
        sve_ops.vector_size = sve_vector_bytes();
    return &sve_ops;
}

const struct simd_ops *sve2_get_ops(void)
{
    /* Set vector size at first call */
    if (sve2_ops.vector_size == 0)
        sve2_ops.vector_size = sve_vector_bytes();
    return &sve2_ops;
}

EXPORT_SYMBOL_GPL(sve_get_ops);
EXPORT_SYMBOL_GPL(sve2_get_ops);
EXPORT_SYMBOL_GPL(sve_matmul_fp32);
EXPORT_SYMBOL_GPL(sve_dot_product);
EXPORT_SYMBOL_GPL(sve_quantize_fp32_to_q8);
EXPORT_SYMBOL_GPL(sve_quantize_fp32_to_q4);
EXPORT_SYMBOL_GPL(sve_dequantize_q8_to_fp32);
EXPORT_SYMBOL_GPL(sve_dequantize_q4_to_fp32);
EXPORT_SYMBOL_GPL(sve_batch_dot_product);
EXPORT_SYMBOL_GPL(sve_vector_length_bits);
EXPORT_SYMBOL_GPL(sve_has_sve2);
EXPORT_SYMBOL_GPL(sve_run_self_tests);
EXPORT_SYMBOL_GPL(sve_run_benchmarks);

/* ============================================
 * Module init/exit
 * ============================================ */

static int __init sve_impl_init(void)
{
    int vl_bits = sve_vector_length_bits();
    int vl_f32 = sve_f32_elements();

    pr_info("ainos: SVE implementation loaded (vector=%d bits, %d float32, %d bytes)\n",
            vl_bits, vl_f32, sve_vector_bytes());

    /* Run self-tests */
    sve_run_self_tests();

    return 0;
}

static void __exit sve_impl_exit(void)
{
    pr_info("ainos: SVE implementation unloaded\n");
}

module_init(sve_impl_init);
module_exit(sve_impl_exit);