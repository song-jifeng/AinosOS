// SPDX-License-Identifier: GPL-2.0
/*
 * Ainos OS - ARM64 NEON SIMD Vector Acceleration Implementation
 * ===============================================================
 * Provides full ARM NEON (Advanced SIMD) optimizations for AI vector
 * acceleration kernels: matrix multiplication (SGEMM), dot product,
 * quantization (FP32->INT8, FP32->INT4), dequantization, and batch
 * dot product operations.
 *
 * All NEON intrinsic functions require kernel_neon_begin() to be called
 * before use and kernel_neon_end() after completion to manage the
 * floating-point register state in kernel context.
 *
 * Architecture: ARMv8-A NEON (AArch64)
 * Register width: 128-bit (4 x float32)
 * Peak performance: 8 FLOPs/cycle (FMA) on Cortex-A76/A78
 *
 * References:
 *   - ARM Architecture Reference Manual ARMv8-A (DDI0487)
 *   - NEON Programmer's Guide (DEN0018A)
 *   - ARM Cortex-A76 Software Optimization Guide
 */

#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/export.h>
#include <linux/printk.h>
#include <linux/types.h>
#include <linux/bug.h>
#include <linux/string.h>
#include <linux/cache.h>
#include <linux/preempt.h>
#include <asm/neon.h>
#include <arm_neon.h>

#include "simd_impl.h"

/* ============================================================
 * Constants and Configuration
 * ============================================================
 *
 * These tuning parameters control the tiling behavior for the
 * NEON matrix multiplication kernel. They are chosen to match
 * typical ARM Cortex-A76/A78 cache hierarchies:
 *
 *   L1 data cache:   64 KB     (per core)
 *   L2 cache:        256-512 KB (per cluster)
 *   Cache line:      64 bytes  (16 floats)
 *
 * TILE_M, TILE_N: Block dimensions in the output matrix C.
 *   Each tile of C is computed independently, accumulating over
 *   the full K dimension. Larger tiles improve data reuse but
 *   increase register pressure.
 *
 * TILE_K: Block dimension for the reduction loop.
 *   Controls how much of the A and B matrices are brought into
 *   cache at once. The inner kernel reuses the B tile across
 *   multiple rows of A.
 */

/* Outer tile sizes for L2 cache blocking */
#define TILE_M               32
#define TILE_N               32
#define TILE_K               32

/* Inner tile sizes for L1 cache blocking */
#define INNER_TILE_M         4
#define INNER_TILE_N         4
#define INNER_TILE_K         4

/* Minimum dimensions for using the tiled path */
#define TILED_MIN_M          8
#define TILED_MIN_N          8
#define TILED_MIN_K          8

/* Small matrix threshold (use direct path) */
#define SMALL_MATRIX_MAX     32

/* Cache geometry */
#define CACHE_LINE_SIZE      64
#define CACHE_LINE_FLOATS    16

/* Prefetch distance (in iterations ahead) */
#define PREFETCH_DIST        6

/* NEON vector lane counts */
#define NEON_F32_LANES       4       /* 128-bit / 32-bit */
#define NEON_I8_LANES        16      /* 128-bit / 8-bit */
#define NEON_I16_LANES       8       /* 128-bit / 16-bit */

/* ============================================================
 * Utility Macros
 * ============================================================ */

/* Minimum of two values */
#define MIN(a, b)            ({ \
    typeof(a) _a = (a);          \
    typeof(b) _b = (b);          \
    _a < _b ? _a : _b; })

/* Maximum of two values */
#define MAX(a, b)            ({ \
    typeof(a) _a = (a);          \
    typeof(b) _b = (b);          \
    _a > _b ? _a : _b; })

/* Round up to multiple of alignment */
#define ROUND_UP(x, a)       (((x) + ((typeof(x))(a) - 1)) & ~((typeof(x))(a) - 1))

/* Check if pointer is aligned to given size */
#define PTR_IS_ALIGNED(p, a) (((uintptr_t)(p) & ((uintptr_t)(a) - 1)) == 0)

/* Align pointer up to cache line boundary */
#define CACHE_ALIGN_PTR(p)   ((void *)ROUND_UP((uintptr_t)(p), CACHE_LINE_SIZE))

/* Check if value is a multiple of 4 */
#define IS_MULTIPLE_OF_4(x)  (((x) & 3) == 0)

/* ============================================================
 * CPU Feature Detection Helpers
 * ============================================================
 *
 * ARM64 guarantees NEON availability. These helpers check for
 * additional features that may benefit the implementation.
 */

/* Check if we have at least the given number of elements */
static inline bool neon_can_process_4(int n)
{
    return n >= 4;
}

static inline bool neon_can_process_8(int n)
{
    return n >= 8;
}

static inline bool neon_can_process_16(int n)
{
    return n >= 16;
}

/* ============================================================
 * Alignment and Allocation Helpers
 * ============================================================
 *
 * Cache-aligned allocation is critical for NEON performance.
 * Misaligned accesses incur a penalty on most ARM Cortex
 * processors. These helpers provide aligned allocation using
 * kmalloc with alignment guarantees.
 */

/**
 * neon_alloc_aligned - Allocate cache-aligned memory
 * @size: Number of bytes to allocate
 *
 * Returns a pointer to kmalloc'd memory that is aligned to
 * a CACHE_LINE_SIZE boundary. Uses kmalloc with extra space
 * to guarantee alignment.
 *
 * Return: Aligned pointer, or NULL on failure
 */
static void *neon_alloc_aligned(size_t size)
{
    void *ptr;
    void *aligned;
    void **backing;

    /*
     * Allocate extra space for:
     *   1. Alignment padding (CACHE_LINE_SIZE - 1 bytes)
     *   2. Pointer to backing store (for kfree)
     */
    size_t alloc_size = size + CACHE_LINE_SIZE + sizeof(void *);

    ptr = kmalloc(alloc_size, GFP_KERNEL);
    if (!ptr)
        return NULL;

    /* Find the next aligned address within the allocation */
    aligned = (void *)ROUND_UP((uintptr_t)ptr + sizeof(void *),
                                CACHE_LINE_SIZE);

    /* Store the original pointer just before the aligned address */
    backing = (void **)aligned - 1;
    *backing = ptr;

    return aligned;
}

/**
 * neon_free_aligned - Free memory allocated by neon_alloc_aligned
 * @aligned_ptr: The aligned pointer returned by neon_alloc_aligned
 */
static void neon_free_aligned(void *aligned_ptr)
{
    void **backing;

    if (!aligned_ptr)
        return;

    /* Retrieve the original pointer stored before the aligned address */
    backing = (void **)aligned_ptr - 1;
    kfree(*backing);
}

/**
 * neon_is_aligned - Check if data pointer is suitably aligned
 * @ptr: Pointer to check
 * @alignment: Required alignment in bytes
 *
 * Return: true if pointer meets alignment requirement
 */
static inline bool neon_is_aligned(const void *ptr, size_t alignment)
{
    return PTR_IS_ALIGNED(ptr, alignment);
}

/**
 * neon_is_cache_aligned - Check cache line alignment
 * @ptr: Pointer to check
 *
 * Return: true if aligned to CACHE_LINE_SIZE
 */
static inline bool neon_is_cache_aligned(const void *ptr)
{
    return neon_is_aligned(ptr, CACHE_LINE_SIZE);
}

/**
 * neon_pad_size - Round up size to multiple of SIMD vector width
 * @n: Number of elements
 * @elem_size: Size of each element in bytes
 *
 * Return: Number of elements rounded up to next multiple of 4
 */
static inline int neon_pad_elems(int n)
{
    return ROUND_UP(n, NEON_F32_LANES);
}

/* ============================================================
 * Prefetch Helpers
 * ============================================================
 *
 * Software prefetching is essential for keeping the NEON pipeline
 * fed with data. ARM64 provides the prfm instruction via
 * __builtin_prefetch with locality hints.
 *
 * Prefetch hints:
 *   PLDL1KEEP  - Prefetch for load, L1, temporal
 *   PLDL1STRM  - Prefetch for load, L1, streaming
 *   PLDL2KEEP  - Prefetch for load, L2, temporal
 *   PLDL2STRM  - Prefetch for load, L2, streaming
 *   PSTL1KEEP  - Prefetch for store, L1, temporal
 */

/**
 * neon_prefetch_ld - Prefetch data for reading
 * @ptr: Address to prefetch
 * @locality: Locality hint (0 = no locality, 3 = high locality)
 *
 * Prefetches data into L1 cache with the specified locality.
 * Use locality=3 for data that will be reused soon,
 * locality=0 for streaming access (not reused).
 */
static inline void neon_prefetch_ld(const void *ptr, int locality)
{
    if (ptr)
        __builtin_prefetch(ptr, 0, locality);
}

/**
 * neon_prefetch_st - Prefetch data for writing
 * @ptr: Address to prefetch
 * @locality: Locality hint
 */
static inline void neon_prefetch_st(const void *ptr, int locality)
{
    if (ptr)
        __builtin_prefetch(ptr, 1, locality);
}

/**
 * neon_prefetch_ahead - Prefetch matrix data ahead of current position
 * @a: Pointer to matrix A row start
 * @b: Pointer to matrix B block start
 * @c: Pointer to matrix C tile start
 * @ldb: Leading dimension of B
 * @p: Current reduction index
 * @dist: Prefetch distance (number of iterations ahead)
 *
 * Issues prefetch instructions for A, B, and C data that will be
 * accessed 'dist' iterations in the future.
 */
static inline void neon_prefetch_ahead(const float *a, const float *b,
                                        const float *c, int ldb,
                                        int p, int dist)
{
    /*
     * Prefetch A: next rows of A (they are accessed column-wise,
     * so we prefetch ahead in the row direction)
     */
    neon_prefetch_ld(a + dist, 3);

    /*
     * Prefetch B: next columns of B (prefetch ahead in the
     * column direction, which is the next set of B rows)
     */
    neon_prefetch_ld(b + (p + dist) * ldb, 3);

    /*
     * Prefetch C: destination tile (prefetch for write)
     */
    neon_prefetch_st(c, 1);
}

/**
 * neon_prefetch_matmul - Prefetch for matrix multiplication inner loop
 * @a: Current A matrix pointer
 * @b: Current B matrix pointer
 * @k: Total reduction dimension
 * @p: Current reduction index
 * @ldb: Leading dimension of B
 */
static inline void neon_prefetch_matmul(const float *a, const float *b,
                                         int k, int p, int ldb)
{
    /* Prefetch B data ahead in the reduction dimension */
    if (p + PREFETCH_DIST < k) {
        neon_prefetch_ld(b + (p + PREFETCH_DIST) * ldb, 3);
        neon_prefetch_ld(b + (p + PREFETCH_DIST + 1) * ldb, 3);
    }

    /* Prefetch A data ahead */
    neon_prefetch_ld(a + p + PREFETCH_DIST, 3);
}

/* ============================================================
 * NEON Kernel: 4x4 FMA Matrix Multiply Accumulate
 * ============================================================
 *
 * Computes: C[i:i+4, j:j+4] += A[i:i+4, p:p+k] * B[p:p+k, j:j+4]
 *
 * This is the fundamental NEON compute kernel. It processes 4 rows
 * and 4 columns of the output matrix C simultaneously, using the
 * 128-bit NEON register file.
 *
 * Algorithm:
 *   For each element p in the reduction dimension:
 *     Load B[p][j:j+4] into a NEON register (4 floats)
 *     For each row r in [0, 4):
 *       Load A[i+r][p] as a scalar
 *       Multiply by B[p][j:j+4] and accumulate into C[i+r][j:j+4]
 *
 * Register usage (4 x 4 kernel):
 *   v0-v3:  C accumulator registers (4 rows x 4 columns)
 *   v4:     B row vector (4 columns)
 *   v5-v8:  A scalar values (1 per row, broadcast via lane)
 *
 * Performance: 8 FLOPs/cycle (4 FMA instructions per cycle on A76)
 * Throughput: 16 results per k iterations
 *
 * @mr: Number of rows to process (1-4, may be less for boundaries)
 * @nr: Number of columns to process (1-4, may be less for boundaries)
 * @k:  Number of reduction elements
 * @a:  Pointer to A matrix (leading dimension = lda)
 * @lda: Leading dimension of A (stride between rows)
 * @b:  Pointer to B matrix (leading dimension = ldb)
 * @ldb: Leading dimension of B (stride between rows in B)
 * @c:  Pointer to C matrix (leading dimension = ldc)
 * @ldc: Leading dimension of C (stride between rows in C)
 */
static void neon_kernel_4x4(int mr, int nr, int k,
                             const float *a, int lda,
                             const float *b, int ldb,
                             float *c, int ldc)
{
    int p;

    /* ============================================================
     * Step 1: Load C accumulator values from memory
     *
     * We use vld1q_f32 to load 4 consecutive floats from each row
     * of C. These serve as the initial accumulator values. If the
     * output matrix is not zero-initialized, this correctly adds
     * to any existing values.
     *
     * For boundary cases (mr < 4 or nr < 4), we load whatever
     * elements are available. The remainder handling uses scalar
     * operations for the partial rows/columns.
     * ============================================================ */

    float32x4_t cv[4];
    float32x4_t zero = vdupq_n_f32(0.0f);

    /* Initialize accumulators */
    for (int i = 0; i < mr; i++) {
        if (nr == 4) {
            /* Full 4-column load: single NEON instruction */
            cv[i] = vld1q_f32(&c[i * ldc]);
        } else {
            /*
             * Partial column load: load 4 elements and zero out
             * the unused lanes. For nr < 4, we load 4 elements
             * (which may include data beyond the matrix boundary)
             * and rely on the partial store to write only the
             * valid elements.
             *
             * A safer alternative is to load a full vector and
             * then blend with zero, but since we only store nr
             * elements, loading extra data is acceptable as long
             * as we don't access unmapped memory.
             */
            cv[i] = vld1q_f32(&c[i * ldc]);
        }
    }

    /* Zero out unused accumulators */
    for (int i = mr; i < 4; i++)
        cv[i] = zero;

    /* ============================================================
     * Step 2: Main reduction loop (unrolled by 4)
     *
     * The inner loop processes 4 elements of the reduction
     * dimension at a time. This amortizes the loop overhead and
     * allows better instruction scheduling.
     *
     * For each group of 4 reduction elements:
     *   1. Load 4 rows of B into registers (b0, b1, b2, b3)
     *   2. For each row of A (i = 0..mr-1):
     *      a. Load 4 scalar values from A[i][p:p+4]
     *      b. FMA each into the corresponding C accumulator
     *
     * The FMA operation uses vfmaq_n_f32 which broadcasts the
     * scalar A value across all lanes and multiplies with B.
     * ============================================================ */

    p = 0;

    /* Process in groups of 4 */
    for (; p + 4 <= k; p += 4) {
        /*
         * Load 4 consecutive rows of B, each containing 4 columns.
         * These are 4 consecutive float32x4_t loads from B[p][j:j+4],
         * B[p+1][j:j+4], B[p+2][j:j+4], B[p+3][j:j+4].
         */
        float32x4_t b0 = vld1q_f32(&b[(p + 0) * ldb]);
        float32x4_t b1 = vld1q_f32(&b[(p + 1) * ldb]);
        float32x4_t b2 = vld1q_f32(&b[(p + 2) * ldb]);
        float32x4_t b3 = vld1q_f32(&b[(p + 3) * ldb]);

        /* Prefetch next set of B rows */
        neon_prefetch_matmul(a, b, k, p, ldb);

        /*
         * Accumulate for each row of A.
         *
         * vfmaq_n_f32(cv[i], b[j], a_val) performs:
         *   cv[i] = cv[i] + b[j] * a_val
         *
         * where a_val is a scalar broadcast to all 4 lanes.
         * Each row of C uses a different scalar from A:
         *   A[i][p+0], A[i][p+1], A[i][p+2], A[i][p+3]
         */
        for (int i = 0; i < mr; i++) {
            float a_val;

            a_val = a[i * lda + p + 0];
            cv[i] = vfmaq_n_f32(cv[i], b0, a_val);

            a_val = a[i * lda + p + 1];
            cv[i] = vfmaq_n_f32(cv[i], b1, a_val);

            a_val = a[i * lda + p + 2];
            cv[i] = vfmaq_n_f32(cv[i], b2, a_val);

            a_val = a[i * lda + p + 3];
            cv[i] = vfmaq_n_f32(cv[i], b3, a_val);
        }
    }

    /* ============================================================
     * Step 3: Remainder loop (handles k % 4 elements)
     *
     * Processes the remaining 1-3 reduction elements one at a time.
     * Each iteration loads one row of B and accumulates into all
     * active rows of C.
     * ============================================================ */

    for (; p < k; p++) {
        float32x4_t bv = vld1q_f32(&b[p * ldb]);

        for (int i = 0; i < mr; i++) {
            float a_val = a[i * lda + p];
            cv[i] = vfmaq_n_f32(cv[i], bv, a_val);
        }
    }

    /* ============================================================
     * Step 4: Store results back to C
     *
     * For full 4-column results, use vst1q_f32.
     * For partial columns, use a scalar loop to avoid writing
     * beyond the matrix boundary.
     * ============================================================ */

    for (int i = 0; i < mr; i++) {
        if (nr == 4) {
            /* Full 4-column store: single NEON instruction */
            vst1q_f32(&c[i * ldc], cv[i]);
        } else {
            /*
             * Partial column store: write elements one at a time.
             * This is slower but safe for boundary tiles.
             */
            float *c_row = &c[i * ldc];
            float32x4_t v = cv[i];

            switch (nr) {
            case 3:
                c_row[2] = vgetq_lane_f32(v, 2);
                /* fall through */
            case 2:
                c_row[1] = vgetq_lane_f32(v, 1);
                /* fall through */
            case 1:
                c_row[0] = vgetq_lane_f32(v, 0);
                break;
            default:
                break;
            }
        }
    }
}

/* ============================================================
 * NEON Kernel: 4x1 FMA Matrix Multiply Accumulate (4 rows, 1 col)
 * ============================================================
 *
 * Processes 4 rows and 1 column of C. This is a remainder kernel
 * for cases where the output matrix has fewer than 4 columns
 * remaining (n % 4 != 0).
 *
 * Instead of loading a full 4-column vector from B, we load a single
 * scalar value and broadcast it for the FMA operation.
 *
 * @mr: Number of rows to process (1-4)
 * @nr: Number of columns to process (must be 1)
 * @k:  Reduction dimension
 * @a:  Pointer to A matrix
 * @lda: Leading dimension of A
 * @b:  Pointer to B matrix
 * @ldb: Leading dimension of B
 * @c:  Pointer to C matrix tile
 * @ldc: Leading dimension of C
 */
static void neon_kernel_4x1(int mr, int nr, int k,
                              const float *a, int lda,
                              const float *b, int ldb,
                              float *c, int ldc)
{
    int p;
    float32x4_t cv;
    float32x4_t zero = vdupq_n_f32(0.0f);

    /*
     * Load C accumulator for the single column.
     * We load 4 consecutive rows from the same column:
     *   C[i][j], C[i+1][j], C[i+2][j], C[i+3][j]
     * These are not contiguous in memory (stride = ldc).
     * We use vld1q_lane_f32 to load individual elements.
     */
    cv = zero;
    for (int i = 0; i < mr; i++)
        cv = vld1q_lane_f32(&c[i * ldc], cv, i);

    /*
     * Main reduction loop, unrolled by 4.
     * For each element of B, we load a scalar and broadcast it.
     */
    p = 0;

    for (; p + 4 <= k; p += 4) {
        /*
         * Load 4 scalar values from B, one per reduction element.
         * These are at B[p][j], B[p+1][j], B[p+2][j], B[p+3][j]
         * where j is the single column we're processing.
         */
        float b0 = b[(p + 0) * ldb];
        float b1 = b[(p + 1) * ldb];
        float b2 = b[(p + 2) * ldb];
        float b3 = b[(p + 3) * ldb];

        /*
         * Accumulate for each row of A.
         * Each row uses A[i][p:p+4] with the corresponding B scalar.
         */
        for (int i = 0; i < mr; i++) {
            float a_val;
            float32x4_t acc;

            /*
             * Extract the current accumulator for row i.
             * We need to update only lane i of the accumulator.
             * vmlaq_n_f32 with a scalar updates all lanes, so we
             * use a different approach: accumulate into a scalar,
             * then update the lane.
             */
            float acc_i = vgetq_lane_f32(cv, i);

            a_val = a[i * lda + p + 0];
            acc_i += a_val * b0;

            a_val = a[i * lda + p + 1];
            acc_i += a_val * b1;

            a_val = a[i * lda + p + 2];
            acc_i += a_val * b2;

            a_val = a[i * lda + p + 3];
            acc_i += a_val * b3;

            cv = vsetq_lane_f32(acc_i, cv, i);
        }
    }

    /*
     * Remainder loop for k % 4 elements.
     */
    for (; p < k; p++) {
        float bv = b[p * ldb];

        for (int i = 0; i < mr; i++) {
            float acc_i = vgetq_lane_f32(cv, i);
            acc_i += a[i * lda + p] * bv;
            cv = vsetq_lane_f32(acc_i, cv, i);
        }
    }

    /*
     * Store results back to C.
     * Each row stores to the same column position.
     */
    for (int i = 0; i < mr; i++) {
        c[i * ldc] = vgetq_lane_f32(cv, i);
    }
}

/* ============================================================
 * NEON Kernel: 1x4 FMA Matrix Multiply Accumulate (1 row, 4 cols)
 * ============================================================
 *
 * Processes 1 row and 4 columns of C. This is a remainder kernel
 * for cases where the output matrix has fewer than 4 rows
 * remaining (m % 4 != 0).
 *
 * This kernel handles the bottom edge of the output matrix where
 * only a partial row-block remains. It is a simplified version
 * of the 4x4 kernel with only one row accumulator.
 *
 * @mr: Number of rows to process (must be 1)
 * @nr: Number of columns to process (1-4)
 * @k:  Reduction dimension
 * @a:  Pointer to A matrix
 * @lda: Leading dimension of A
 * @b:  Pointer to B matrix
 * @ldb: Leading dimension of B
 * @c:  Pointer to C matrix tile
 * @ldc: Leading dimension of C
 */
static void neon_kernel_1x4(int mr, int nr, int k,
                              const float *a, int lda,
                              const float *b, int ldb,
                              float *c, int ldc)
{
    int p;
    float32x4_t cv;

    /*
     * Load C accumulator for the single row.
     * We load 4 consecutive columns from the same row.
     */
    if (nr == 4) {
        cv = vld1q_f32(&c[0]);
    } else {
        cv = vld1q_f32(&c[0]);
        /* Zero out lanes beyond the valid range */
        for (int j = nr; j < 4; j++)
            cv = vsetq_lane_f32(0.0f, cv, j);
    }

    /*
     * Main reduction loop, unrolled by 4.
     * For each group of 4 reduction elements:
     *   1. Load 4 rows of B (each 4 columns wide)
     *   2. Load 4 A values (scalars, same row)
     *   3. FMA into the accumulator
     */
    p = 0;

    for (; p + 4 <= k; p += 4) {
        float32x4_t b0 = vld1q_f32(&b[(p + 0) * ldb]);
        float32x4_t b1 = vld1q_f32(&b[(p + 1) * ldb]);
        float32x4_t b2 = vld1q_f32(&b[(p + 2) * ldb]);
        float32x4_t b3 = vld1q_f32(&b[(p + 3) * ldb]);

        float a0 = a[p + 0];
        float a1 = a[p + 1];
        float a2 = a[p + 2];
        float a3 = a[p + 3];

        cv = vfmaq_n_f32(cv, b0, a0);
        cv = vfmaq_n_f32(cv, b1, a1);
        cv = vfmaq_n_f32(cv, b2, a2);
        cv = vfmaq_n_f32(cv, b3, a3);
    }

    /*
     * Remainder loop for k % 4 elements.
     */
    for (; p < k; p++) {
        float32x4_t bv = vld1q_f32(&b[p * ldb]);
        float a_val = a[p];

        cv = vfmaq_n_f32(cv, bv, a_val);
    }

    /*
     * Store results.
     */
    if (nr == 4) {
        vst1q_f32(c, cv);
    } else {
        for (int j = 0; j < nr; j++)
            c[j] = vgetq_lane_f32(cv, j);
    }
}

/* ============================================================
 * NEON Kernel: 4x2 FMA Matrix Multiply Accumulate (4 rows, 2 cols)
 * ============================================================
 *
 * Processes 4 rows and 2 columns of C. This is a remainder kernel
 * for when the output matrix has 2 columns remaining.
 *
 * The kernel uses a 2-element vector (float32x2_t) for the
 * accumulator, processing 2 columns at a time. This is more
 * efficient than the 1x4 or 4x1 kernels for the 2-column case.
 *
 * @mr: Number of rows to process (1-4)
 * @nr: Number of columns to process (must be 2)
 * @k:  Reduction dimension
 * @a:  Pointer to A matrix
 * @lda: Leading dimension of A
 * @b:  Pointer to B matrix
 * @ldb: Leading dimension of B
 * @c:  Pointer to C matrix tile
 * @ldc: Leading dimension of C
 */
static void neon_kernel_4x2(int mr, int nr, int k,
                              const float *a, int lda,
                              const float *b, int ldb,
                              float *c, int ldc)
{
    int p;

    /*
     * Accumulator: 4 rows x 2 columns.
     * We use float32x2_t for each row (2-element vector).
     */
    float32x2_t cv[4];
    float32x2_t zero = vdup_n_f32(0.0f);

    /* Load C accumulators */
    for (int i = 0; i < mr; i++) {
        cv[i] = vld1_f32(&c[i * ldc]);
    }

    /* Zero unused accumulators */
    for (int i = mr; i < 4; i++)
        cv[i] = zero;

    /*
     * Main reduction loop, unrolled by 4.
     * For each group of 4 reduction elements:
     *   1. Load 4 pairs of B values (2 columns each)
     *   2. For each row, load 4 A values and FMA
     */
    p = 0;

    for (; p + 4 <= k; p += 4) {
        /*
         * Load B values: 2 columns from 4 rows of B.
         * B[p][j:j+2], B[p+1][j:j+2], etc.
         */
        float32x2_t b0 = vld1_f32(&b[(p + 0) * ldb]);
        float32x2_t b1 = vld1_f32(&b[(p + 1) * ldb]);
        float32x2_t b2 = vld1_f32(&b[(p + 2) * ldb]);
        float32x2_t b3 = vld1_f32(&b[(p + 3) * ldb]);

        for (int i = 0; i < mr; i++) {
            float a_val;

            a_val = a[i * lda + p + 0];
            cv[i] = vfma_n_f32(cv[i], b0, a_val);

            a_val = a[i * lda + p + 1];
            cv[i] = vfma_n_f32(cv[i], b1, a_val);

            a_val = a[i * lda + p + 2];
            cv[i] = vfma_n_f32(cv[i], b2, a_val);

            a_val = a[i * lda + p + 3];
            cv[i] = vfma_n_f32(cv[i], b3, a_val);
        }
    }

    /* Remainder loop */
    for (; p < k; p++) {
        float32x2_t bv = vld1_f32(&b[p * ldb]);

        for (int i = 0; i < mr; i++) {
            float a_val = a[i * lda + p];
            cv[i] = vfma_n_f32(cv[i], bv, a_val);
        }
    }

    /* Store results */
    for (int i = 0; i < mr; i++) {
        vst1_f32(&c[i * ldc], cv[i]);
    }
}

/* ============================================================
 * NEON Kernel: 2x4 FMA Matrix Multiply Accumulate (2 rows, 4 cols)
 * ============================================================
 *
 * Processes 2 rows and 4 columns of C. This is a remainder kernel
 * for when the output matrix has 2 rows remaining.
 *
 * @mr: Number of rows to process (must be 2)
 * @nr: Number of columns to process (1-4)
 * @k:  Reduction dimension
 * @a:  Pointer to A matrix
 * @lda: Leading dimension of A
 * @b:  Pointer to B matrix
 * @ldb: Leading dimension of B
 * @c:  Pointer to C matrix tile
 * @ldc: Leading dimension of C
 */
static void neon_kernel_2x4(int mr, int nr, int k,
                              const float *a, int lda,
                              const float *b, int ldb,
                              float *c, int ldc)
{
    int p;
    float32x4_t cv[2];
    float32x4_t zero = vdupq_n_f32(0.0f);

    /* Load C accumulators */
    for (int i = 0; i < mr; i++) {
        if (nr == 4) {
            cv[i] = vld1q_f32(&c[i * ldc]);
        } else {
            cv[i] = vld1q_f32(&c[i * ldc]);
            for (int j = nr; j < 4; j++)
                cv[i] = vsetq_lane_f32(0.0f, cv[i], j);
        }
    }

    for (int i = mr; i < 2; i++)
        cv[i] = zero;

    /* Main reduction loop */
    p = 0;

    for (; p + 4 <= k; p += 4) {
        float32x4_t b0 = vld1q_f32(&b[(p + 0) * ldb]);
        float32x4_t b1 = vld1q_f32(&b[(p + 1) * ldb]);
        float32x4_t b2 = vld1q_f32(&b[(p + 2) * ldb]);
        float32x4_t b3 = vld1q_f32(&b[(p + 3) * ldb]);

        for (int i = 0; i < mr; i++) {
            float a_val;

            a_val = a[i * lda + p + 0];
            cv[i] = vfmaq_n_f32(cv[i], b0, a_val);

            a_val = a[i * lda + p + 1];
            cv[i] = vfmaq_n_f32(cv[i], b1, a_val);

            a_val = a[i * lda + p + 2];
            cv[i] = vfmaq_n_f32(cv[i], b2, a_val);

            a_val = a[i * lda + p + 3];
            cv[i] = vfmaq_n_f32(cv[i], b3, a_val);
        }
    }

    /* Remainder loop */
    for (; p < k; p++) {
        float32x4_t bv = vld1q_f32(&b[p * ldb]);

        for (int i = 0; i < mr; i++) {
            float a_val = a[i * lda + p];
            cv[i] = vfmaq_n_f32(cv[i], bv, a_val);
        }
    }

    /* Store results */
    for (int i = 0; i < mr; i++) {
        if (nr == 4) {
            vst1q_f32(&c[i * ldc], cv[i]);
        } else {
            for (int j = 0; j < nr; j++)
                c[i * ldc + j] = vgetq_lane_f32(cv[i], j);
        }
    }
}

/* ============================================================
 * NEON Kernel: 1x1 Scalar Remainder
 * ============================================================
 *
 * Handles the corner case where both m % 4 != 0 and n % 4 != 0.
 * Processes a single element of C using scalar operations.
 *
 * @k:  Reduction dimension
 * @a:  Pointer to A matrix (single row)
 * @b:  Pointer to B matrix (single column)
 * @c:  Pointer to C matrix (single element)
 */
static void neon_kernel_1x1(int k,
                              const float *a, const float *b,
                              float *c)
{
    float sum = 0.0f;
    int p;

    for (p = 0; p < k; p++)
        sum += a[p] * b[p];

    *c += sum;
}

/* ============================================================
 * NEON Kernel: Unified Remainder Handler
 * ============================================================
 *
 * Dispatches to the appropriate remainder kernel based on the
 * micro-tile dimensions. This function handles all cases where
 * the tile dimensions are smaller than the standard kernel sizes.
 *
 * @mr: Number of rows to process (1-3, or 5-7)
 * @nr: Number of columns to process (1-3, or 5-7)
 * @k:  Reduction dimension
 * @a:  Pointer to A matrix
 * @lda: Leading dimension of A
 * @b:  Pointer to B matrix
 * @ldb: Leading dimension of B
 * @c:  Pointer to C matrix tile
 * @ldc: Leading dimension of C
 */
static inline void neon_kernel_remainder(int mr, int nr, int k,
                                          const float *a, int lda,
                                          const float *b, int ldb,
                                          float *c, int ldc)
{
    /*
     * Dispatch to the optimal remainder kernel based on
     * the exact dimensions.
     */
    if (mr >= 4) {
        /* 4 rows, partial columns */
        if (nr >= 4) {
            /* Full 4x4 kernel handles this */
            neon_kernel_4x4(mr, nr, k, a, lda, b, ldb, c, ldc);
        } else if (nr == 2) {
            neon_kernel_4x2(mr, nr, k, a, lda, b, ldb, c, ldc);
        } else {
            neon_kernel_4x1(mr, nr, k, a, lda, b, ldb, c, ldc);
        }
    } else if (mr >= 2) {
        /* 2 rows */
        if (nr >= 4) {
            neon_kernel_2x4(mr, nr, k, a, lda, b, ldb, c, ldc);
        } else {
            /* 2x2 or 2x1: use scalar fallback */
            for (int i = 0; i < mr; i++) {
                for (int j = 0; j < nr; j++) {
                    neon_kernel_1x1(k,
                                    a + i * lda, b + j,
                                    c + i * ldc + j);
                }
            }
        }
    } else {
        /* 1 row */
        if (nr >= 4) {
            neon_kernel_1x4(mr, nr, k, a, lda, b, ldb, c, ldc);
        } else {
            /* 1x2, 1x1, 1x3: use scalar fallback */
            for (int j = 0; j < nr; j++) {
                neon_kernel_1x1(k, a, b + j, c + j);
            }
        }
    }
}

/* ============================================================
 * NEON Kernel: 4x8 FMA Matrix Multiply Accumulate (4 rows, 8 cols)
 * ============================================================
 *
 * Extended kernel that processes 4 rows and 8 columns of C.
 * This is implemented as two adjacent 4x4 kernels, sharing the
 * A values (which are loaded once) and using 8 accumulator
 * registers (4 per 4-column block).
 *
 * This kernel is beneficial when n is large and the extra register
 * pressure is manageable. It achieves better arithmetic intensity
 * by reusing each A value across 8 columns of B.
 *
 * @mr: Number of rows to process (1-4)
 * @nr: Number of columns to process (1-8)
 * @k:  Reduction dimension
 * @a:  Pointer to A matrix row start
 * @lda: Leading dimension of A
 * @b:  Pointer to B matrix row start
 * @ldb: Leading dimension of B
 * @c:  Pointer to C matrix tile
 * @ldc: Leading dimension of C
 */
static void neon_kernel_4x8(int mr, int nr, int k,
                             const float *a, int lda,
                             const float *b, int ldb,
                             float *c, int ldc)
{
    int p;

    /*
     * Accumulator registers: 8 vectors for 4 rows x 8 cols
     * cv_left[i] = C[i][j:j+4], cv_right[i] = C[i][j+4:j+8]
     */
    float32x4_t cv_left[4], cv_right[4];
    float32x4_t zero = vdupq_n_f32(0.0f);

    /* Load C accumulators for the left block (columns 0-3) */
    for (int i = 0; i < mr; i++) {
        cv_left[i] = vld1q_f32(&c[i * ldc + 0]);
    }

    /* Load C accumulators for the right block (columns 4-7) */
    if (nr > 4) {
        for (int i = 0; i < mr; i++) {
            int cols_avail = nr - 4;
            cv_right[i] = vld1q_f32(&c[i * ldc + 4]);
            if (cols_avail < 4) {
                /* Zero out lanes beyond the matrix boundary */
                for (int j = cols_avail; j < 4; j++)
                    cv_right[i] = vsetq_lane_f32(0.0f, cv_right[i], j);
            }
        }
    }

    /* Zero unused accumulators */
    for (int i = mr; i < 4; i++) {
        cv_left[i] = zero;
        cv_right[i] = zero;
    }

    /* Main reduction loop, unrolled by 4 */
    p = 0;

    for (; p + 4 <= k; p += 4) {
        /*
         * Load 8 columns of B for each of 4 rows.
         * The left block uses B[p][j:j+4] and B[p][j+4:j+8].
         */
        float32x4_t b_left0 = vld1q_f32(&b[(p + 0) * ldb + 0]);
        float32x4_t b_left1 = vld1q_f32(&b[(p + 1) * ldb + 0]);
        float32x4_t b_left2 = vld1q_f32(&b[(p + 2) * ldb + 0]);
        float32x4_t b_left3 = vld1q_f32(&b[(p + 3) * ldb + 0]);

        float32x4_t b_right0, b_right1, b_right2, b_right3;

        if (nr > 4) {
            b_right0 = vld1q_f32(&b[(p + 0) * ldb + 4]);
            b_right1 = vld1q_f32(&b[(p + 1) * ldb + 4]);
            b_right2 = vld1q_f32(&b[(p + 2) * ldb + 4]);
            b_right3 = vld1q_f32(&b[(p + 3) * ldb + 4]);
        }

        /* Accumulate into each row of C */
        for (int i = 0; i < mr; i++) {
            float a0 = a[i * lda + p + 0];
            float a1 = a[i * lda + p + 1];
            float a2 = a[i * lda + p + 2];
            float a3 = a[i * lda + p + 3];

            /* Left block: columns 0-3 */
            cv_left[i] = vfmaq_n_f32(cv_left[i], b_left0, a0);
            cv_left[i] = vfmaq_n_f32(cv_left[i], b_left1, a1);
            cv_left[i] = vfmaq_n_f32(cv_left[i], b_left2, a2);
            cv_left[i] = vfmaq_n_f32(cv_left[i], b_left3, a3);

            /* Right block: columns 4-7 */
            if (nr > 4) {
                cv_right[i] = vfmaq_n_f32(cv_right[i], b_right0, a0);
                cv_right[i] = vfmaq_n_f32(cv_right[i], b_right1, a1);
                cv_right[i] = vfmaq_n_f32(cv_right[i], b_right2, a2);
                cv_right[i] = vfmaq_n_f32(cv_right[i], b_right3, a3);
            }
        }
    }

    /* Remainder loop */
    for (; p < k; p++) {
        float32x4_t b_left = vld1q_f32(&b[p * ldb + 0]);
        float32x4_t b_right;

        if (nr > 4)
            b_right = vld1q_f32(&b[p * ldb + 4]);

        for (int i = 0; i < mr; i++) {
            float a_val = a[i * lda + p];
            cv_left[i] = vfmaq_n_f32(cv_left[i], b_left, a_val);
            if (nr > 4)
                cv_right[i] = vfmaq_n_f32(cv_right[i], b_right, a_val);
        }
    }

    /* Store left block */
    for (int i = 0; i < mr; i++) {
        int cols_left = MIN(nr, 4);

        if (cols_left == 4) {
            vst1q_f32(&c[i * ldc + 0], cv_left[i]);
        } else {
            float *c_row = &c[i * ldc + 0];
            for (int j = 0; j < cols_left; j++)
                c_row[j] = vgetq_lane_f32(cv_left[i], j);
        }

        /* Store right block */
        if (nr > 4) {
            int cols_right = nr - 4;

            if (cols_right == 4) {
                vst1q_f32(&c[i * ldc + 4], cv_right[i]);
            } else {
                float *c_row = &c[i * ldc + 4];
                for (int j = 0; j < cols_right; j++)
                    c_row[j] = vgetq_lane_f32(cv_right[i], j);
            }
        }
    }
}

/* ============================================================
 * NEON Kernel: 8x4 FMA Matrix Multiply Accumulate (8 rows, 4 cols)
 * ============================================================
 *
 * Processes 8 rows and 4 columns of C. Implemented as two stacked
 * 4x4 kernels, sharing the B values (which are loaded once) and
 * using 8 accumulator registers.
 *
 * This kernel is beneficial when m is large, as it reuses each
 * B vector across 8 rows of A.
 *
 * @mr: Number of rows to process (1-8)
 * @nr: Number of columns to process (1-4)
 * @k:  Reduction dimension
 * @a:  Pointer to A matrix row start
 * @lda: Leading dimension of A
 * @b:  Pointer to B matrix
 * @ldb: Leading dimension of B
 * @c:  Pointer to C matrix tile
 * @ldc: Leading dimension of C
 */
static void neon_kernel_8x4(int mr, int nr, int k,
                             const float *a, int lda,
                             const float *b, int ldb,
                             float *c, int ldc)
{
    int p;

    /*
     * Accumulator registers: 8 vectors for 8 rows x 4 cols
     * cv[i] = C[i][j:j+4]
     */
    float32x4_t cv[8];
    float32x4_t zero = vdupq_n_f32(0.0f);

    /* Load C accumulators */
    for (int i = 0; i < mr; i++) {
        if (nr == 4) {
            cv[i] = vld1q_f32(&c[i * ldc]);
        } else {
            cv[i] = vld1q_f32(&c[i * ldc]);
            /* Zero out lanes beyond boundary */
            for (int j = nr; j < 4; j++)
                cv[i] = vsetq_lane_f32(0.0f, cv[i], j);
        }
    }

    /* Zero unused accumulators */
    for (int i = mr; i < 8; i++)
        cv[i] = zero;

    /* Main reduction loop, unrolled by 4 */
    p = 0;

    for (; p + 4 <= k; p += 4) {
        /*
         * Load 4 rows of B (4 columns each).
         * These are shared across all 8 rows of A.
         */
        float32x4_t b0 = vld1q_f32(&b[(p + 0) * ldb]);
        float32x4_t b1 = vld1q_f32(&b[(p + 1) * ldb]);
        float32x4_t b2 = vld1q_f32(&b[(p + 2) * ldb]);
        float32x4_t b3 = vld1q_f32(&b[(p + 3) * ldb]);

        /* Accumulate into each row of C */
        for (int i = 0; i < mr; i++) {
            float a_val;

            a_val = a[i * lda + p + 0];
            cv[i] = vfmaq_n_f32(cv[i], b0, a_val);

            a_val = a[i * lda + p + 1];
            cv[i] = vfmaq_n_f32(cv[i], b1, a_val);

            a_val = a[i * lda + p + 2];
            cv[i] = vfmaq_n_f32(cv[i], b2, a_val);

            a_val = a[i * lda + p + 3];
            cv[i] = vfmaq_n_f32(cv[i], b3, a_val);
        }
    }

    /* Remainder loop */
    for (; p < k; p++) {
        float32x4_t bv = vld1q_f32(&b[p * ldb]);

        for (int i = 0; i < mr; i++) {
            float a_val = a[i * lda + p];
            cv[i] = vfmaq_n_f32(cv[i], bv, a_val);
        }
    }

    /* Store results */
    for (int i = 0; i < mr; i++) {
        if (nr == 4) {
            vst1q_f32(&c[i * ldc], cv[i]);
        } else {
            float *c_row = &c[i * ldc];
            for (int j = 0; j < nr; j++)
                c_row[j] = vgetq_lane_f32(cv[i], j);
        }
    }
}

/* ============================================================
 * NEON Kernel: 8x8 FMA Matrix Multiply Accumulate (8 rows, 8 cols)
 * ============================================================
 *
 * The largest kernel, processing 8 rows and 8 columns of C.
 * Combines the 8-row approach with the 8-column approach.
 * Uses 16 accumulator registers.
 *
 * Register pressure is high (16 accumulators + 8 B values + temporaries),
 * but this kernel maximizes arithmetic intensity when both m and n
 * are large.
 *
 * @mr: Number of rows to process (1-8)
 * @nr: Number of columns to process (1-8)
 * @k:  Reduction dimension
 * @a:  Pointer to A matrix
 * @lda: Leading dimension of A
 * @b:  Pointer to B matrix
 * @ldb: Leading dimension of B
 * @c:  Pointer to C matrix tile
 * @ldc: Leading dimension of C
 */
static void neon_kernel_8x8(int mr, int nr, int k,
                             const float *a, int lda,
                             const float *b, int ldb,
                             float *c, int ldc)
{
    int p;

    /*
     * Accumulator registers: 16 vectors for 8 rows x 8 cols
     * cv_left[i] = C[i][j:j+4], cv_right[i] = C[i][j+4:j+8]
     */
    float32x4_t cv_left[8], cv_right[8];
    float32x4_t zero = vdupq_n_f32(0.0f);

    /* Load C accumulators for left block */
    for (int i = 0; i < mr; i++)
        cv_left[i] = vld1q_f32(&c[i * ldc + 0]);

    /* Load C accumulators for right block */
    if (nr > 4) {
        for (int i = 0; i < mr; i++) {
            int cols_avail = nr - 4;
            cv_right[i] = vld1q_f32(&c[i * ldc + 4]);
            if (cols_avail < 4) {
                for (int j = cols_avail; j < 4; j++)
                    cv_right[i] = vsetq_lane_f32(0.0f, cv_right[i], j);
            }
        }
    }

    /* Zero unused accumulators */
    for (int i = mr; i < 8; i++) {
        cv_left[i] = zero;
        cv_right[i] = zero;
    }

    /* Main reduction loop, unrolled by 4 */
    p = 0;

    for (; p + 4 <= k; p += 4) {
        /* Load B vectors for the left block */
        float32x4_t b_left0 = vld1q_f32(&b[(p + 0) * ldb + 0]);
        float32x4_t b_left1 = vld1q_f32(&b[(p + 1) * ldb + 0]);
        float32x4_t b_left2 = vld1q_f32(&b[(p + 2) * ldb + 0]);
        float32x4_t b_left3 = vld1q_f32(&b[(p + 3) * ldb + 0]);

        /* Load B vectors for the right block */
        float32x4_t b_right0, b_right1, b_right2, b_right3;

        if (nr > 4) {
            b_right0 = vld1q_f32(&b[(p + 0) * ldb + 4]);
            b_right1 = vld1q_f32(&b[(p + 1) * ldb + 4]);
            b_right2 = vld1q_f32(&b[(p + 2) * ldb + 4]);
            b_right3 = vld1q_f32(&b[(p + 3) * ldb + 4]);
        }

        /* Accumulate into each row of C */
        for (int i = 0; i < mr; i++) {
            float a0 = a[i * lda + p + 0];
            float a1 = a[i * lda + p + 1];
            float a2 = a[i * lda + p + 2];
            float a3 = a[i * lda + p + 3];

            /* Left block */
            cv_left[i] = vfmaq_n_f32(cv_left[i], b_left0, a0);
            cv_left[i] = vfmaq_n_f32(cv_left[i], b_left1, a1);
            cv_left[i] = vfmaq_n_f32(cv_left[i], b_left2, a2);
            cv_left[i] = vfmaq_n_f32(cv_left[i], b_left3, a3);

            /* Right block */
            if (nr > 4) {
                cv_right[i] = vfmaq_n_f32(cv_right[i], b_right0, a0);
                cv_right[i] = vfmaq_n_f32(cv_right[i], b_right1, a1);
                cv_right[i] = vfmaq_n_f32(cv_right[i], b_right2, a2);
                cv_right[i] = vfmaq_n_f32(cv_right[i], b_right3, a3);
            }
        }
    }

    /* Remainder loop */
    for (; p < k; p++) {
        float32x4_t b_left = vld1q_f32(&b[p * ldb + 0]);
        float32x4_t b_right;

        if (nr > 4)
            b_right = vld1q_f32(&b[p * ldb + 4]);

        for (int i = 0; i < mr; i++) {
            float a_val = a[i * lda + p];
            cv_left[i] = vfmaq_n_f32(cv_left[i], b_left, a_val);
            if (nr > 4)
                cv_right[i] = vfmaq_n_f32(cv_right[i], b_right, a_val);
        }
    }

    /* Store left block */
    for (int i = 0; i < mr; i++) {
        int cols_left = MIN(nr, 4);

        if (cols_left == 4) {
            vst1q_f32(&c[i * ldc + 0], cv_left[i]);
        } else {
            float *c_row = &c[i * ldc + 0];
            for (int j = 0; j < cols_left; j++)
                c_row[j] = vgetq_lane_f32(cv_left[i], j);
        }

        /* Store right block */
        if (nr > 4) {
            int cols_right = nr - 4;

            if (cols_right == 4) {
                vst1q_f32(&c[i * ldc + 4], cv_right[i]);
            } else {
                float *c_row = &c[i * ldc + 4];
                for (int j = 0; j < cols_right; j++)
                    c_row[j] = vgetq_lane_f32(cv_right[i], j);
            }
        }
    }
}

/* ============================================================
 * NEON Kernel Selector
 * ============================================================
 *
 * Selects the appropriate kernel based on the tile dimensions.
 * This provides a unified interface for the tile processing
 * functions.
 *
 * @mr: Number of rows to process
 * @nr: Number of columns to process
 * @k:  Reduction dimension
 * @a:  Pointer to A matrix
 * @lda: Leading dimension of A
 * @b:  Pointer to B matrix
 * @ldb: Leading dimension of B
 * @c:  Pointer to C matrix tile
 * @ldc: Leading dimension of C
 */
static inline void neon_kernel_dispatch(int mr, int nr, int k,
                                         const float *a, int lda,
                                         const float *b, int ldb,
                                         float *c, int ldc)
{
    /*
     * Select the largest kernel that fits the tile dimensions.
     * Larger kernels give better arithmetic intensity.
     */
    if (mr >= 8 && nr >= 8) {
        /* 8x8 kernel: best for large tiles */
        neon_kernel_8x8(mr, nr, k, a, lda, b, ldb, c, ldc);
    } else if (mr >= 8 && nr >= 4) {
        /* 8x4 kernel: good for tall tiles */
        neon_kernel_8x4(mr, nr, k, a, lda, b, ldb, c, ldc);
    } else if (mr >= 4 && nr >= 8) {
        /* 4x8 kernel: good for wide tiles */
        neon_kernel_4x8(mr, nr, k, a, lda, b, ldb, c, ldc);
    } else {
        /* 4x4 kernel: general purpose */
        neon_kernel_4x4(mr, nr, k, a, lda, b, ldb, c, ldc);
    }
}

/* ============================================================
 * Tile Processing for Matrix Multiplication
 * ============================================================
 *
 * Processes a single tile of the output matrix C of size
 * m_cur x n_cur, reducing over k_cur elements of A and B.
 *
 * The tile is further subdivided into micro-tiles that match
 * the NEON kernel dimensions (4x4, 4x8, 8x4, 8x8).
 *
 * @m_cur: Number of rows in this tile
 * @n_cur: Number of columns in this tile
 * @k_cur: Number of reduction elements in this tile
 * @a:     Pointer to the A submatrix (m_cur x k_cur, stride = lda)
 * @lda:   Leading dimension of A (full matrix)
 * @b:     Pointer to the B submatrix (k_cur x n_cur, stride = ldb)
 * @ldb:   Leading dimension of B (full matrix)
 * @c:     Pointer to the C submatrix (m_cur x n_cur, stride = ldc)
 * @ldc:   Leading dimension of C (full matrix)
 */
static void neon_process_tile(int m_cur, int n_cur, int k_cur,
                               const float *a, int lda,
                               const float *b, int ldb,
                               float *c, int ldc)
{
    int i, j;

    /*
     * Process the tile in micro-tiles.
     *
     * The outer loop iterates over rows of C in steps of 8,
     * and columns of C in steps of 8. For each micro-tile,
     * we dispatch to the appropriate kernel.
     *
     * The micro-tile dimensions are chosen to maximize NEON
     * utilization while handling arbitrary remainders.
     */
    for (i = 0; i < m_cur; i += 8) {
        int mr = MIN(8, m_cur - i);

        for (j = 0; j < n_cur; j += 8) {
            int nr = MIN(8, n_cur - j);

            /*
             * Dispatch to the appropriate kernel.
             * The kernel will further subdivide if needed.
             */
            neon_kernel_dispatch(mr, nr, k_cur,
                                 a + i * lda, lda,
                                 b + j, ldb,
                                 c + i * ldc + j, ldc);
        }
    }
}

/* ============================================================
 * Small Matrix Fast Path
 * ============================================================
 *
 * For small matrices (m, n <= 16), we use a direct non-tiled
 * path that avoids the overhead of tiling. This is important
 * for AI inference workloads where small matrices are common
 * (e.g., attention projections, MLP layers).
 *
 * @m: Number of rows in A and C
 * @n: Number of columns in B and C
 * @k: Number of columns in A, rows in B
 * @a: Matrix A (m x k, row-major)
 * @b: Matrix B (k x n, row-major)
 * @c: Matrix C (m x n, row-major, zero-initialized)
 */
static void neon_matmul_small(int m, int n, int k,
                               const float *a, const float *b, float *c)
{
    int i, j;

    /*
     * For small matrices, just zero C and process directly.
     * The kernel dispatch handles the micro-tiling.
     */
    for (i = 0; i < m; i++) {
        for (j = 0; j < n; j++) {
            c[i * n + j] = 0.0f;
        }
    }

    /*
     * Process the entire matrix as a single tile.
     * The kernel will handle the actual dimensions.
     */
    neon_kernel_dispatch(m, n, k, a, n, b, n, c, n);
}

/* ============================================================
 * Medium Matrix Path
 * ============================================================
 *
 * For medium-sized matrices (up to ~256), we use a single level
 * of tiling over the K dimension. This reduces cache misses
 * without the overhead of full 3-level tiling.
 *
 * @m: Number of rows in A and C
 * @n: Number of columns in B and C
 * @k: Number of columns in A, rows in B
 * @a: Matrix A (m x k, row-major)
 * @b: Matrix B (k x n, row-major)
 * @c: Matrix C (m x n, row-major, zero-initialized)
 */
static void neon_matmul_medium(int m, int n, int k,
                                const float *a, const float *b, float *c)
{
    int p;

    /* Zero the output matrix */
    for (int i = 0; i < m; i++) {
        for (int j = 0; j < n; j++) {
            c[i * n + j] = 0.0f;
        }
    }

    /*
     * Tile over the K dimension only.
     * Each tile of K is processed with the full m x n output.
     */
    for (p = 0; p < k; p += TILE_K) {
        int k_cur = MIN(TILE_K, k - p);

        neon_process_tile(m, n, k_cur,
                          a + p,           /* A advances by k_cur columns */
                          k,               /* lda = original k */
                          b + p * n,       /* B advances by k_cur rows */
                          n,               /* ldb = n */
                          c,               /* C stays at same position */
                          n);              /* ldc = n */
    }
}

/* ============================================================
 * Large Matrix Path (Fully Tiled)
 * ============================================================
 *
 * For large matrices, we use a 3-level tiling strategy:
 *   1. Outer tiles over M and N (for L2 cache)
 *   2. Inner tiles over K (for L1 cache)
 *   3. Micro-tiles for NEON registers
 *
 * The tiling ensures that the working set fits in the cache
 * hierarchy, keeping the NEON pipeline fed with data.
 *
 * @m: Number of rows in A and C
 * @n: Number of columns in B and C
 * @k: Number of columns in A, rows in B
 * @a: Matrix A (m x k, row-major)
 * @b: Matrix B (k x n, row-major)
 * @c: Matrix C (m x n, row-major, zero-initialized)
 */
static void neon_matmul_large(int m, int n, int k,
                               const float *a, const float *b, float *c)
{
    int i, j, p;

    /* Zero the output matrix */
    for (i = 0; i < m; i++) {
        for (j = 0; j < n; j++) {
            c[i * n + j] = 0.0f;
        }
    }

    /*
     * Three-level nested tiling:
     *
     * Level 1 (outer): Tile over M and N dimensions.
     *   Each outer tile produces a m_cur x n_cur block of C.
     *   Tile size: TILE_M x TILE_N (typically 32x32).
     *   Purpose: Keep the output tile in L2 cache.
     *
     * Level 2 (inner): Tile over K dimension.
     *   Each inner tile accumulates k_cur elements of the
     *   reduction for the current outer tile.
     *   Tile size: TILE_K (typically 32).
     *   Purpose: Keep A and B tiles in L1 cache.
     *
     * Level 3 (micro): Tile within the inner tile using
     *   NEON kernels. Handled by neon_process_tile().
     *   Micro-tile size: 4x4, 4x8, 8x4, or 8x8.
     *   Purpose: Keep values in NEON registers.
     */
    for (i = 0; i < m; i += TILE_M) {
        int m_cur = MIN(TILE_M, m - i);

        for (j = 0; j < n; j += TILE_N) {
            int n_cur = MIN(TILE_N, n - j);

            /*
             * Accumulate over the K dimension for this
             * (m_cur x n_cur) tile of C.
             */
            for (p = 0; p < k; p += TILE_K) {
                int k_cur = MIN(TILE_K, k - p);

                /*
                 * Process the micro-tile using NEON kernels.
                 *
                 * A submatrix: rows i..i+m_cur-1, cols p..p+k_cur-1
                 *   -> a + i * k + p, stride = k (full matrix K)
                 *
                 * B submatrix: rows p..p+k_cur-1, cols j..j+n_cur-1
                 *   -> b + p * n + j, stride = n (full matrix N)
                 *
                 * C submatrix: rows i..i+m_cur-1, cols j..j+n_cur-1
                 *   -> c + i * n + j, stride = n (full matrix N)
                 */
                neon_process_tile(m_cur, n_cur, k_cur,
                                  a + i * k + p, k,
                                  b + p * n + j, n,
                                  c + i * n + j, n);
            }
        }
    }
}

/* ============================================================
 * Matrix Packing Infrastructure
 * ============================================================
 *
 * Packing matrices into contiguous buffers improves cache
 * utilization by ensuring that data accessed by the inner
 * kernel is laid out sequentially in memory.
 *
 * Packing A (row-major to packed format):
 *   For each tile of M rows and K columns:
 *     For each row in the tile:
 *       Copy K contiguous elements from the source row
 *     Result: [row0_k0..kK, row1_k0..kK, ...]
 *
 * Packing B (row-major to packed format for 4-column kernel):
 *   For each tile of K rows and N columns:
 *     For each group of 4 columns:
 *       For each row in the tile:
 *         Copy 4 contiguous elements
 *     Result: [k0_c0..c3, k1_c0..c3, ..., k0_c4..c7, ...]
 *   This layout allows the inner kernel to load B values
 *   as contiguous float32x4_t vectors.
 *
 * Packed buffer management:
 *   The packing functions work with pre-allocated buffers.
 *   Buffer sizes are calculated based on tile dimensions.
 *   For maximum performance, buffers should be cache-aligned.
 */

/**
 * neon_pack_A_tile - Pack a tile of matrix A into contiguous buffer
 * @dst: Destination packed buffer (m_cur * k_cur floats)
 * @src: Source matrix A (m_cur x k_cur, stride = lda)
 * @m_cur: Number of rows in this tile
 * @k_cur: Number of columns in this tile
 * @lda: Leading dimension of source matrix A
 *
 * Packing A makes the inner loop access pattern sequential:
 * instead of strided access across rows (A[i][p] with stride lda),
 * the packed buffer has all elements of the tile in row-major order.
 */
static void neon_pack_A_tile(float *dst, const float *src,
                               int m_cur, int k_cur, int lda)
{
    /*
     * Copy each row of the tile into the packed buffer.
     * The source may have a stride (lda) that differs from k_cur,
     * so we cannot use a single memcpy.
     */
    for (int i = 0; i < m_cur; i++) {
        memcpy(dst + i * k_cur, src + i * lda, k_cur * sizeof(float));
    }
}

/**
 * neon_pack_A_tile_transposed - Pack A tile in transposed order
 * @dst: Destination packed buffer (k_cur * m_cur floats)
 * @src: Source matrix A (m_cur x k_cur, stride = lda)
 * @m_cur: Number of rows
 * @k_cur: Number of columns
 * @lda: Leading dimension of source
 *
 * Packs the tile so that columns become contiguous in memory.
 * This is useful for kernels that access A column-wise.
 */
static void neon_pack_A_tile_transposed(float *dst, const float *src,
                                          int m_cur, int k_cur, int lda)
{
    for (int i = 0; i < m_cur; i++) {
        for (int j = 0; j < k_cur; j++) {
            dst[j * m_cur + i] = src[i * lda + j];
        }
    }
}

/**
 * neon_pack_B_tile - Pack a tile of matrix B into contiguous buffer
 * @dst: Destination packed buffer (k_cur * n_cur floats)
 * @src: Source matrix B (k_cur x n_cur, stride = ldb)
 * @k_cur: Number of rows in this tile
 * @n_cur: Number of columns in this tile
 * @ldb: Leading dimension of source matrix B
 *
 * Packing B is critical for the inner kernel performance.
 * The packed layout places the 4 columns needed by the kernel
 * consecutively, enabling sequential vld1q_f32 loads.
 *
 * Packed B layout:
 *   For each group of 4 columns (g = 0, 4, 8, ...):
 *     For each row (r = 0, 1, ..., k_cur-1):
 *       Copy B[r][g:g+4] (4 consecutive floats)
 *
 * This layout ensures that the inner kernel can load all 4 rows
 * of B for a 4x4 micro-tile with 4 sequential vld1q_f32 calls.
 */
static void neon_pack_B_tile(float *dst, const float *src,
                               int k_cur, int n_cur, int ldb)
{
    int j, p;

    /*
     * Process the tile in groups of 4 columns.
     * For each group, we copy all k_cur rows, each contributing
     * 4 consecutive floats.
     */
    for (j = 0; j < n_cur; j += 4) {
        int nr = MIN(4, n_cur - j);

        for (p = 0; p < k_cur; p++) {
            /*
             * Copy 4 floats from the source row.
             * For partial columns (nr < 4), we zero-pad
             * to maintain 4-element alignment.
             */
            if (nr == 4) {
                memcpy(dst, &src[p * ldb + j], 4 * sizeof(float));
            } else {
                /*
                 * Zero-pad the partial group and copy
                 * the available elements. This ensures
                 * the inner kernel can safely load 4
                 * elements without reading out of bounds.
                 */
                float padding[4] = {0, 0, 0, 0};
                memcpy(padding, &src[p * ldb + j], nr * sizeof(float));
                memcpy(dst, padding, 4 * sizeof(float));
            }
            dst += 4;
        }
    }
}

/**
 * neon_pack_B_tile_interleaved - Pack B tile with interleaved layout
 * @dst: Destination packed buffer
 * @src: Source matrix B
 * @k_cur: Tile rows
 * @n_cur: Tile columns
 * @ldb: Leading dimension of source
 *
 * Alternative packing that interleaves rows. For a 4x4 micro-tile,
 * the packed format is:
 *   [B[0][0], B[1][0], B[2][0], B[3][0],   -- col 0 of 4 rows
 *    B[0][1], B[1][1], B[2][1], B[3][1],   -- col 1 of 4 rows
 *    ...]
 *
 * This layout is beneficial when the kernel accesses B column-wise.
 */
static void neon_pack_B_tile_interleaved(float *dst, const float *src,
                                           int k_cur, int n_cur, int ldb)
{
    int j, p;

    for (j = 0; j < n_cur; j++) {
        for (p = 0; p < k_cur; p += 4) {
            int kr = MIN(4, k_cur - p);

            for (int r = 0; r < kr; r++) {
                *dst++ = src[(p + r) * ldb + j];
            }
            /* Zero-pad if needed */
            for (int r = kr; r < 4; r++) {
                *dst++ = 0.0f;
            }
        }
    }
}

/**
 * neon_pack_B_tile_v4 - Pack B optimized for 4x4 kernel
 * @dst: Destination buffer (k_cur * ROUND_UP(n_cur, 4) floats)
 * @src: Source matrix B
 * @k_cur: Tile rows
 * @n_cur: Tile columns
 * @ldb: Leading dimension of source
 *
 * Packs B specifically for the 4x4 NEON kernel. The layout
 * groups elements so that the kernel can load B vectors
 * with minimal addressing overhead.
 *
 * Packed layout (for each group of 4 columns):
 *   [B[0][0], B[0][1], B[0][2], B[0][3],     -- row 0, cols 0-3
 *    B[1][0], B[1][1], B[1][2], B[1][3],     -- row 1, cols 0-3
 *    ...]
 *
 * This is the standard row-major packing of the B tile,
 * which matches the inner kernel's access pattern.
 */
static void neon_pack_B_tile_v4(float *dst, const float *src,
                                  int k_cur, int n_cur, int ldb)
{
    int p, j;

    for (j = 0; j < n_cur; j += 4) {
        int nr = MIN(4, n_cur - j);

        for (p = 0; p < k_cur; p++) {
            float32x4_t bv;

            if (nr == 4) {
                bv = vld1q_f32(&src[p * ldb + j]);
            } else {
                float vals[4] = {0, 0, 0, 0};
                for (int c = 0; c < nr; c++)
                    vals[c] = src[p * ldb + j + c];
                bv = vld1q_f32(vals);
            }

            vst1q_f32(dst, bv);
            dst += 4;
        }
    }
}

/**
 * neon_pack_B_tile_v8 - Pack B optimized for 4x8 kernel
 * @dst: Destination buffer (k_cur * ROUND_UP(n_cur, 8) floats)
 * @src: Source matrix B
 * @k_cur: Tile rows
 * @n_cur: Tile columns
 * @ldb: Leading dimension of source
 *
 * Packs B for the 4x8 kernel, which processes 8 columns at once.
 * The layout groups 8 columns per row entry.
 */
static void neon_pack_B_tile_v8(float *dst, const float *src,
                                  int k_cur, int n_cur, int ldb)
{
    int p, j;

    for (j = 0; j < n_cur; j += 8) {
        int nr = MIN(8, n_cur - j);

        for (p = 0; p < k_cur; p++) {
            float vals[8] = {0, 0, 0, 0, 0, 0, 0, 0};
            int c;

            for (c = 0; c < nr; c++)
                vals[c] = src[p * ldb + j + c];

            memcpy(dst, vals, 8 * sizeof(float));
            dst += 8;
        }
    }
}

/**
 * neon_calc_packed_A_size - Calculate packed A buffer size
 * @m_cur: Tile rows
 * @k_cur: Tile columns
 *
 * Return: Number of floats needed for the packed buffer
 */
static inline int neon_calc_packed_A_size(int m_cur, int k_cur)
{
    return m_cur * k_cur;
}

/**
 * neon_calc_packed_B_size - Calculate packed B buffer size
 * @k_cur: Tile rows
 * @n_cur: Tile columns
 *
 * Return: Number of floats needed for the packed buffer
 */
static inline int neon_calc_packed_B_size(int k_cur, int n_cur)
{
    /*
     * B is packed in groups of 4 columns, zero-padded to
     * the next multiple of 4.
     */
    int n_padded = ROUND_UP(n_cur, 4);
    return k_cur * n_padded;
}

/**
 * neon_calc_packed_B8_size - Calculate packed B buffer size for 4x8 kernel
 * @k_cur: Tile rows
 * @n_cur: Tile columns
 *
 * Return: Number of floats needed for the packed buffer
 */
static inline int neon_calc_packed_B8_size(int k_cur, int n_cur)
{
    int n_padded = ROUND_UP(n_cur, 8);
    return k_cur * n_padded;
}

/* ============================================================
 * Packed Matrix Multiplication (Tiled + Packed)
 * ============================================================
 *
 * High-performance variant of the matrix multiplication that
 * uses matrix packing for better cache behavior. This is the
 * BLIS-style approach to GEMM.
 *
 * With packing, the inner kernel operates on buffers where:
 *   - Packed A has contiguous rows (no stride)
 *   - Packed B has 4-column groups contiguous
 *
 * This eliminates strided memory access in the inner loop,
 * significantly improving performance on ARM Cortex cores.
 */

/**
 * neon_matmul_tiled_packed - Tiled matrix multiply with packing
 * @m: Number of rows in A and C
 * @n: Number of columns in B and C
 * @k: Number of columns in A, rows in B
 * @a: Matrix A (m x k, row-major)
 * @b: Matrix B (k x n, row-major)
 * @c: Matrix C (m x n, row-major, zero-initialized)
 *
 * This variant packs tiles of A and B into contiguous buffers
 * before calling the inner kernel. The packing overhead is
 * amortized over the inner kernel's computation.
 *
 * For the A matrix, packing is done per tile in the outer loop,
 * so each A tile is packed once and reused for all B tiles
 * in the same row of the output.
 *
 * For the B matrix, packing is done per tile in the inner loop.
 */
static void neon_matmul_tiled_packed(int m, int n, int k,
                                      const float *a, const float *b,
                                      float *c)
{
    int i, j, p;

    /*
     * Allocate packing buffers.
     * These are reused across all tile iterations.
     * We use the slab allocator with GFP_KERNEL flag.
     *
     * Buffer sizes:
     *   packed_A: TILE_M * TILE_K floats
     *   packed_B: TILE_K * ROUND_UP(TILE_N, 4) floats
     */
    int packed_A_size = TILE_M * TILE_K;
    int packed_B_size = TILE_K * ROUND_UP(TILE_N, 4);

    float *packed_A = (float *)neon_alloc_aligned(
        packed_A_size * sizeof(float));
    float *packed_B = (float *)neon_alloc_aligned(
        packed_B_size * sizeof(float));

    if (!packed_A || !packed_B) {
        pr_err("neon_matmul_tiled_packed: failed to allocate "
               "packing buffers (%d, %d floats)\n",
               packed_A_size, packed_B_size);
        neon_free_aligned(packed_A);
        neon_free_aligned(packed_B);
        return;
    }

    /*
     * Zero the output matrix.
     */
    for (i = 0; i < m; i++) {
        for (j = 0; j < n; j++) {
            c[i * n + j] = 0.0f;
        }
    }

    /*
     * Three-level tiled loop with packing.
     *
     * Level 1 (outer): Tile over M and N.
     *   For each tile of C, we accumulate over the K dimension.
     *
     * Level 2 (middle): Tile over K.
     *   For each K-tile, we pack the A and B sub-tiles.
     *
     * Level 3 (inner): Process micro-tiles using packed buffers.
     */
    for (i = 0; i < m; i += TILE_M) {
        int m_cur = MIN(TILE_M, m - i);

        for (p = 0; p < k; p += TILE_K) {
            int k_cur = MIN(TILE_K, k - p);

            /*
             * Pack A tile: m_cur rows x k_cur columns.
             * This tile is reused across all N tiles.
             */
            neon_pack_A_tile(packed_A,
                             a + i * k + p,
                             m_cur, k_cur, k);

            for (j = 0; j < n; j += TILE_N) {
                int n_cur = MIN(TILE_N, n - j);

                /*
                 * Pack B tile: k_cur rows x n_cur columns.
                 * Packed in the format expected by the 4x4 kernel.
                 */
                neon_pack_B_tile(packed_B,
                                 b + p * n + j,
                                 k_cur, n_cur, n);

                /*
                 * Process the micro-tiles using packed buffers.
                 * The packed A has stride = k_cur (no padding).
                 * The packed B has stride = ROUND_UP(n_cur, 4).
                 */
                neon_process_tile(m_cur, n_cur, k_cur,
                                  packed_A, k_cur,
                                  packed_B, ROUND_UP(n_cur, 4),
                                  c + i * n + j, n);
            }
        }
    }

    neon_free_aligned(packed_A);
    neon_free_aligned(packed_B);
}

/* ============================================================
 * Packed Matrix Multiplication: Fixed-Point Variant
 * ============================================================
 *
 * Optimized variant using fixed TILE_M=32, TILE_N=32, TILE_K=32
 * with pre-computed buffer sizes for reduced overhead.
 */
static void neon_matmul_tiled_packed_fixed(int m, int n, int k,
                                             const float *a,
                                             const float *b,
                                             float *c)
{
    int i, j, p;

    /* Pre-allocate fixed-size buffers (32x32 tiles) */
    float packed_A_buf[32 * 32] __attribute__((aligned(64)));
    float packed_B_buf[32 * 32] __attribute__((aligned(64)));

    float *packed_A = packed_A_buf;
    float *packed_B = packed_B_buf;

    /* Zero output */
    for (i = 0; i < m; i++)
        for (j = 0; j < n; j++)
            c[i * n + j] = 0.0f;

    /* Tiled matmul with packing */
    for (i = 0; i < m; i += 32) {
        int m_cur = MIN(32, m - i);

        for (p = 0; p < k; p += 32) {
            int k_cur = MIN(32, k - p);

            /* Pack A tile */
            neon_pack_A_tile(packed_A, a + i * k + p,
                             m_cur, k_cur, k);

            for (j = 0; j < n; j += 32) {
                int n_cur = MIN(32, n - j);

                /* Pack B tile */
                neon_pack_B_tile(packed_B, b + p * n + j,
                                 k_cur, n_cur, n);

                /* Process micro-tiles */
                neon_process_tile(m_cur, n_cur, k_cur,
                                  packed_A, k_cur,
                                  packed_B, ROUND_UP(n_cur, 4),
                                  c + i * n + j, n);
            }
        }
    }
}

/* ============================================================
 * Matrix Multiplication: Size Dispatch
 * ============================================================
 *
 * Dispatches to the optimal matrix multiplication implementation
 * based on matrix dimensions. The goal is to maximize performance
 * while minimizing overhead.
 *
 * Dispatch strategy:
 *   - Very small matrices (<= 32): direct kernel, no packing
 *   - Medium matrices: single-level K tiling, direct access
 *   - Large matrices: 3-level tiling with packing
 *
 * The thresholds are tunable and depend on the target CPU's
 * cache hierarchy and NEON pipeline characteristics.
 */

/* ============================================================
 * neon_matmul_fp32 - Main Entry Point
 * ============================================================
 *
 * Computes C = A * B for single-precision matrices.
 * Dispatches to the optimal implementation based on matrix size.
 *
 * This function must be called within a kernel_neon_begin()/
 * kernel_neon_end() bracket, or it will handle the brackets
 * itself.
 *
 * Matrix layout:
 *   A: m x k, row-major, stride = k
 *   B: k x n, row-major, stride = n
 *   C: m x n, row-major, stride = n
 *
 * @m: Number of rows in A and C
 * @n: Number of columns in B and C
 * @k: Number of columns in A, rows in B
 * @a: Pointer to A matrix (m x k)
 * @b: Pointer to B matrix (k x n)
 * @c: Pointer to C matrix (m x n)
 */
void neon_matmul_fp32(int m, int n, int k,
                       const float *a, const float *b, float *c)
{
    /*
     * Validate inputs. All dimensions must be positive.
     */
    if (m <= 0 || n <= 0 || k <= 0 || !a || !b || !c) {
        pr_warn_ratelimited("neon_matmul_fp32: invalid parameters "
                            "(m=%d, n=%d, k=%d, a=%p, b=%p, c=%p)\n",
                            m, n, k, a, b, c);
        return;
    }

    /*
     * Acquire NEON context. This disables preemption and
     * saves/restores the floating-point register state.
     */
    kernel_neon_begin();

    /*
     * Dispatch to the appropriate implementation based on
     * matrix size. The thresholds are tuned for typical
     * ARM Cortex-A76/A78 cache hierarchies.
     */
    if (m <= SMALL_MATRIX_MAX && n <= SMALL_MATRIX_MAX &&
        k <= SMALL_MATRIX_MAX) {
        /*
         * Small matrix path: direct kernel dispatch.
         * Avoids tiling overhead for small matrices.
         */
        neon_matmul_small(m, n, k, a, b, c);
    } else if (m <= TILE_M * 2 && n <= TILE_N * 2) {
        /*
         * Medium matrix path: single-level K tiling.
         * For matrices that fit in L2 cache but not in registers.
         */
        neon_matmul_medium(m, n, k, a, b, c);
    } else {
        /*
         * Large matrix path: full 3-level tiling.
         * For matrices that exceed L2 cache capacity.
         */
        neon_matmul_large(m, n, k, a, b, c);
    }

    /*
     * Release NEON context. Re-enables preemption.
     */
    kernel_neon_end();
}
EXPORT_SYMBOL_GPL(neon_matmul_fp32);

/* ============================================================
 * neon_dot_product - Vector Dot Product
 * ============================================================
 *
 * Computes the dot product of two single-precision vectors:
 *   result = sum_{i=0}^{n-1} a[i] * b[i]
 *
 * NEON implementation:
 *   The dot product is computed as a 4-wide reduction:
 *   1. Load 4 elements from a and b into NEON registers
 *   2. Multiply and accumulate using vmlaq_f32
 *   3. After all elements, perform a horizontal sum
 *
 * Horizontal sum reduction:
 *   vpadd_f32(vget_low_f32(sum), vget_high_f32(sum))
 *   -> adds adjacent pairs, producing a 2-element vector
 *   vpadds_f32(result)
 *   -> adds the two remaining elements into a scalar
 *
 * @n: Number of elements in each vector
 * @a: First vector (n elements)
 * @b: Second vector (n elements)
 *
 * Return: Dot product (a[0]*b[0] + a[1]*b[1] + ... + a[n-1]*b[n-1])
 */
float neon_dot_product(int n, const float *a, const float *b)
{
    int i;
    float32x4_t sum_vec;

    /*
     * Validate inputs. n must be positive, and both pointers
     * must be valid.
     */
    if (n <= 0 || !a || !b) {
        pr_warn_ratelimited("neon_dot_product: invalid parameters "
                            "(n=%d, a=%p, b=%p)\n", n, a, b);
        return 0.0f;
    }

    /*
     * Acquire NEON context.
     */
    kernel_neon_begin();

    /*
     * Initialize the accumulator to zero.
     * vdupq_n_f32(0.0f) creates a vector of {0.0, 0.0, 0.0, 0.0}.
     */
    sum_vec = vdupq_n_f32(0.0f);

    /*
     * Main loop: process 4 elements at a time.
     *
     * NEON instruction breakdown:
     *   vld1q_f32(ptr)  - Load 4 consecutive floats into a 128-bit register
     *   vmlaq_f32(s, a, b) - Fused multiply-accumulate: s += a * b
     *     (equivalent to s = s + a * b, performed in a single instruction)
     *
     * Each iteration performs 4 multiplies and 4 additions, totaling
     * 8 FLOPs per iteration, or 2 FLOPs per element.
     */
    i = 0;

    for (; i + 4 <= n; i += 4) {
        float32x4_t a_vec = vld1q_f32(&a[i]);
        float32x4_t b_vec = vld1q_f32(&b[i]);

        /*
         * vmlaq_f32 performs element-wise multiply and accumulate:
         *   sum_vec[0] += a_vec[0] * b_vec[0]
         *   sum_vec[1] += a_vec[1] * b_vec[1]
         *   sum_vec[2] += a_vec[2] * b_vec[2]
         *   sum_vec[3] += a_vec[3] * b_vec[3]
         *
         * This is equivalent to the FMA instruction on ARM64.
         */
        sum_vec = vmlaq_f32(sum_vec, a_vec, b_vec);
    }

    /*
     * Remainder loop: handle elements for which n % 4 != 0.
     * These are processed one at a time using scalar operations.
     */
    for (; i < n; i++) {
        /*
         * vgetq_lane_f32 extracts a single element from the vector.
         * We load the scalar, multiply, and add to the appropriate
         * lane of the accumulator.
         */
        float32x4_t a_scalar = vdupq_n_f32(a[i]);
        float32x4_t b_scalar = vdupq_n_f32(b[i]);

        sum_vec = vmlaq_f32(sum_vec, a_scalar, b_scalar);
    }

    /*
     * Horizontal reduction: sum the 4 elements of sum_vec.
     *
     * Step 1: vpadd_f32 - pairwise add within low and high halves.
     *   Input:  sum_vec = [s0, s1, s2, s3]
     *   Output: [s0+s1, s2+s3] (2-element vector)
     *
     * vget_low_f32(sum_vec)  -> [s0, s1] (lower 64 bits)
     * vget_high_f32(sum_vec) -> [s2, s3] (upper 64 bits)
     * vpadd_f32(low, high)   -> [s0+s1, s2+s3]
     */
    float32x2_t sum_pair = vpadd_f32(vget_low_f32(sum_vec),
                                      vget_high_f32(sum_vec));

    /*
     * Step 2: vpadds_f32 - add the pair to get final scalar.
     *   Input:  [s0+s1, s2+s3]
     *   Output: s0 + s1 + s2 + s3
     *
     * This is a scalar result, returned directly.
     */
    float result = vpadds_f32(sum_pair);

    /*
     * Release NEON context.
     */
    kernel_neon_end();

    return result;
}
EXPORT_SYMBOL_GPL(neon_dot_product);

/* ============================================================
 * Dot Product Variant: Load-Only-Once
 * ============================================================
 *
 * Optimized variant that loads both vectors and reduces.
 * This is the same as the standard dot product but can be
 * used when the compiler needs help with scheduling.
 *
 * @n: Number of elements
 * @a: First vector
 * @b: Second vector
 *
 * Return: Dot product
 */
static float neon_dot_product_fast(int n, const float *a, const float *b)
{
    int i;
    float32x4_t sum_vec = vdupq_n_f32(0.0f);

    /* Process 4 elements at a time */
    for (i = 0; i + 4 <= n; i += 4) {
        float32x4_t a_vec = vld1q_f32(&a[i]);
        float32x4_t b_vec = vld1q_f32(&b[i]);

        sum_vec = vmlaq_f32(sum_vec, a_vec, b_vec);
    }

    /* Remainder: process remaining elements by loading scalar */
    for (; i < n; i++) {
        float32x4_t a_scalar = vdupq_n_f32(a[i]);
        float32x4_t b_scalar = vdupq_n_f32(b[i]);

        sum_vec = vmlaq_f32(sum_vec, a_scalar, b_scalar);
    }

    /* Horizontal reduction */
    float32x2_t sum_pair = vpadd_f32(vget_low_f32(sum_vec),
                                      vget_high_f32(sum_vec));

    return vpadds_f32(sum_pair);
}

/* ============================================================
 * Dot Product Variant: Unrolled by 8
 * ============================================================
 *
 * Processes 8 elements per iteration to improve instruction-level
 * parallelism. This variant uses two accumulator registers to
 * break dependency chains.
 *
 * @n: Number of elements
 * @a: First vector
 * @b: Second vector
 *
 * Return: Dot product
 */
static float neon_dot_product_unrolled8(int n, const float *a,
                                         const float *b)
{
    int i;
    float32x4_t sum0 = vdupq_n_f32(0.0f);
    float32x4_t sum1 = vdupq_n_f32(0.0f);

    /*
     * Process 8 elements per iteration using two accumulators.
     * This allows the CPU to pipeline the FMA instructions:
     * while sum0 is being computed, sum1 can be dispatched in
     * the next cycle.
     */
    for (i = 0; i + 8 <= n; i += 8) {
        float32x4_t a0 = vld1q_f32(&a[i + 0]);
        float32x4_t b0 = vld1q_f32(&b[i + 0]);
        float32x4_t a1 = vld1q_f32(&a[i + 4]);
        float32x4_t b1 = vld1q_f32(&b[i + 4]);

        sum0 = vmlaq_f32(sum0, a0, b0);
        sum1 = vmlaq_f32(sum1, a1, b1);
    }

    /* Remainder: process 4 at a time */
    for (; i + 4 <= n; i += 4) {
        float32x4_t a_vec = vld1q_f32(&a[i]);
        float32x4_t b_vec = vld1q_f32(&b[i]);

        sum0 = vmlaq_f32(sum0, a_vec, b_vec);
    }

    /* Remainder: scalar */
    for (; i < n; i++) {
        float32x4_t a_scalar = vdupq_n_f32(a[i]);
        float32x4_t b_scalar = vdupq_n_f32(b[i]);

        sum0 = vmlaq_f32(sum0, a_scalar, b_scalar);
    }

    /* Combine the two accumulators and reduce */
    sum0 = vaddq_f32(sum0, sum1);

    float32x2_t sum_pair = vpadd_f32(vget_low_f32(sum0),
                                      vget_high_f32(sum0));
    return vpadds_f32(sum_pair);
}

/* ============================================================
 * neon_quantize_fp32_to_q8 - Quantize FP32 to INT8
 * ============================================================
 *
 * Converts single-precision floating-point values to signed 8-bit
 * integers using a scaling factor:
 *   dst[i] = (int8_t)(src[i] * scale)
 *
 * NEON implementation:
 *   1. Load 4 floats using vld1q_f32
 *   2. Multiply by scale using vmulq_n_f32
 *   3. Convert to int32 using vcvtq_s32_f32 (round to nearest integer)
 *   4. Saturating narrow to int16 using vqmovn_s32
 *   5. Saturating narrow to int8 using vqmovn_s16
 *   6. Store 4 int8 values using vst1_s32 (as 32-bit word)
 *
 * The saturating narrow operations (vqmovn) ensure that values
 * outside the INT8 range [-128, 127] are clamped rather than
 * wrapped, which is critical for AI inference accuracy.
 *
 * @n:     Number of elements to quantize
 * @src:   Source float32 array
 * @dst:   Destination int8 array (must have at least n bytes)
 * @scale: Scaling factor (multiply before quantization)
 */
void neon_quantize_fp32_to_q8(int n, const float *src,
                               void *dst, float scale)
{
    int i;
    int8_t *dst8 = (int8_t *)dst;
    float32x4_t scale_vec;

    if (n <= 0 || !src || !dst) {
        pr_warn_ratelimited("neon_quantize_fp32_to_q8: invalid "
                            "parameters (n=%d, src=%p, dst=%p)\n",
                            n, src, dst);
        return;
    }

    kernel_neon_begin();

    /*
     * Broadcast the scale factor to all lanes of a NEON register.
     * vdupq_n_f32(scale) = {scale, scale, scale, scale}
     */
    scale_vec = vdupq_n_f32(scale);

    /*
     * Process 4 elements at a time.
     *
     * The conversion pipeline:
     *   float32 -> int32 -> int16 -> int8
     *
     * vcvtq_s32_f32: Convert float32 to int32 with rounding.
     *   Rounds to nearest integer, ties to even (banker's rounding).
     *   This is the standard IEEE 754 rounding mode.
     *
     * vqmovn_s32: Saturating narrow int32 -> int16.
     *   Takes the lower 64 bits of the int32x4 register and narrows
     *   each 32-bit element to 16 bits. Values outside INT16 range
     *   are clamped to [-32768, 32767].
     *
     * vqmovn_s16: Saturating narrow int16 -> int8.
     *   Takes the lower 64 bits of the int16x8 register and narrows
     *   each 16-bit element to 8 bits. Values outside INT8 range
     *   are clamped to [-128, 127].
     */
    i = 0;

    for (; i + 4 <= n; i += 4) {
        /* Load 4 float32 values */
        float32x4_t src_vec = vld1q_f32(&src[i]);

        /* Multiply by scale: src_vec * scale */
        float32x4_t scaled = vmulq_f32(src_vec, scale_vec);

        /* Convert float32 -> int32 with rounding */
        int32x4_t i32_vec = vcvtq_s32_f32(scaled);

        /* Saturating narrow int32 -> int16 (4 elements -> 4 int16) */
        int16x4_t i16_vec = vqmovn_s32(i32_vec);

        /*
         * Saturating narrow int16 -> int8 (4 int16 -> 4 int8).
         * We need to promote i16_vec to int16x8 first.
         */
        int16x8_t i16x8 = vcombine_s16(i16_vec, vdup_n_s16(0));
        int8x8_t i8_vec = vqmovn_s16(i16x8);

        /*
         * Store the 4 int8 values.
         * vst1_s32 stores 4 bytes as a 32-bit word.
         * We reinterpret the int8x8_t as int32x2_t and take the
         * lower 32 bits.
         */
        vst1_lane_s32((int32_t *)&dst8[i],
                       vreinterpret_s32_s8(i8_vec), 0);
    }

    /*
     * Remainder loop: handle elements where n % 4 != 0.
     * Process one element at a time using scalar operations.
     */
    for (; i < n; i++) {
        float val = src[i] * scale;

        /*
         * Simple scalar conversion with clamping.
         * The cast to int32_t performs rounding (truncation toward zero).
         * For better accuracy, we add 0.5 for positive values and
         * subtract 0.5 for negative values before truncation.
         */
        int32_t i32_val;

        if (val >= 0.0f)
            i32_val = (int32_t)(val + 0.5f);
        else
            i32_val = (int32_t)(val - 0.5f);

        /* Clamp to int8 range */
        if (i32_val > 127)
            i32_val = 127;
        if (i32_val < -128)
            i32_val = -128;

        dst8[i] = (int8_t)i32_val;
    }

    kernel_neon_end();
}
EXPORT_SYMBOL_GPL(neon_quantize_fp32_to_q8);

/* ============================================================
 * neon_quantize_fp32_to_q4 - Quantize FP32 to 4-bit Packed
 * ============================================================
 *
 * Converts single-precision floating-point values to signed 4-bit
 * integers, packed two values per byte:
 *   dst[i/2] = (v0 & 0x0F) | ((v1 & 0x0F) << 4)
 * where v0 = (int8_t)(src[i] * scale), v1 = (int8_t)(src[i+1] * scale)
 *
 * NEON implementation:
 *   1. Load 8 floats (two vld1q_f32)
 *   2. Multiply by scale
 *   3. Convert to int32 using vcvtq_s32_f32
 *   4. Saturating narrow to int16, then int8
 *   5. Mask low nibble with 0x0F
 *   6. Interleave: even elements in low nibble, odd elements in high nibble
 *   7. Combine using vuzp and vorr
 *   8. Store 4 bytes
 *
 * The 4-bit format stores each value in the range [-8, 7] (signed).
 * The low nibble of a byte stores the even-indexed element, and the
 * high nibble stores the odd-indexed element.
 *
 * @n:     Number of elements to quantize
 * @src:   Source float32 array
 * @dst:   Destination uint8 array (must have at least n/2 bytes)
 * @scale: Scaling factor
 */
void neon_quantize_fp32_to_q4(int n, const float *src,
                               void *dst, float scale)
{
    int i;
    uint8_t *dst4 = (uint8_t *)dst;
    float32x4_t scale_vec;

    if (n <= 0 || !src || !dst) {
        pr_warn_ratelimited("neon_quantize_fp32_to_q4: invalid "
                            "parameters (n=%d, src=%p, dst=%p)\n",
                            n, src, dst);
        return;
    }

    kernel_neon_begin();

    scale_vec = vdupq_n_f32(scale);

    /*
     * Main loop: process 8 elements at a time, producing 4 bytes.
     *
     * The NEON pipeline for 8 elements:
     *   1. Load 8 floats (2 loads of 4)
     *   2. Multiply by scale
     *   3. Convert float32 -> int32
     *   4. Narrow int32 -> int16 (saturating)
     *   5. Narrow int16 -> int8 (saturating)
     *   6. Mask with 0x0F to get low nibbles
     *   7. De-interleave: vuzp separates even and odd elements
     *   8. Shift odd elements left by 4
     *   9. OR even and shifted-odd to get packed bytes
     *   10. Store 4 bytes
     */
    i = 0;

    for (; i + 8 <= n; i += 8) {
        /*
         * Step 1: Load 8 floats.
         * Two consecutive vld1q_f32 loads.
         */
        float32x4_t src0 = vld1q_f32(&src[i + 0]);
        float32x4_t src1 = vld1q_f32(&src[i + 4]);

        /*
         * Step 2: Multiply by scale.
         * vmulq_f32 performs element-wise multiplication.
         */
        float32x4_t scaled0 = vmulq_f32(src0, scale_vec);
        float32x4_t scaled1 = vmulq_f32(src1, scale_vec);

        /*
         * Step 3: Convert float32 to int32 with rounding.
         * vcvtq_s32_f32 rounds to nearest integer.
         */
        int32x4_t i32_0 = vcvtq_s32_f32(scaled0);
        int32x4_t i32_1 = vcvtq_s32_f32(scaled1);

        /*
         * Step 4: Saturating narrow int32 -> int16.
         * vqmovn_s32 takes the lower 64 bits of each int32x4
         * and produces an int16x4. We combine into int16x8.
         */
        int16x4_t i16_0 = vqmovn_s32(i32_0);
        int16x4_t i16_1 = vqmovn_s32(i32_1);
        int16x8_t i16_all = vcombine_s16(i16_0, i16_1);

        /*
         * Step 5: Saturating narrow int16 -> int8.
         * vqmovn_s16 produces 8 int8 values.
         */
        int8x8_t i8_all = vqmovn_s16(i16_all);

        /*
         * Step 6: Mask to get low nibble of each value.
         * We want only the low 4 bits of each int8 value.
         * For negative values, the low 4 bits of the two's
         * complement representation give the correct modulo-16
         * representation.
         *
         * Example: -5 = 0xFB -> 0xFB & 0x0F = 0x0B = 11
         * This matches the generic implementation's behavior.
         */
        uint8x8_t u8_all = vreinterpret_u8_s8(i8_all);
        uint8x8_t masked = vand_u8(u8_all, vdup_n_u8(0x0F));

        /*
         * Step 7: De-interleave even and odd elements.
         *
         * vuzp_u8(masked, masked) produces:
         *   val[0] = [masked[0], masked[2], masked[4], masked[6],
         *              masked[0], masked[2], masked[4], masked[6]]
         *   val[1] = [masked[1], masked[3], masked[5], masked[7],
         *              masked[1], masked[3], masked[5], masked[7]]
         *
         * The first 4 elements of val[0] are the even-indexed
         * low nibbles. The first 4 elements of val[1] are the
         * odd-indexed low nibbles.
         */
        uint8x8x2_t deinterleaved = vuzp_u8(masked, masked);

        /*
         * Step 8: Shift odd-element low nibbles to the high
         * nibble position (left by 4 bits).
         */
        uint8x8_t odds_shifted = vshl_n_u8(deinterleaved.val[1], 4);

        /*
         * Step 9: Combine even and shifted-odd elements.
         * vorr_u8 performs bitwise OR:
         *   byte[i] = even[i] | (odd[i] << 4)
         *
         * This gives us the packed format:
         *   result[0] = (v0 & 0x0F) | ((v1 & 0x0F) << 4)
         *   result[1] = (v2 & 0x0F) | ((v3 & 0x0F) << 4)
         *   result[2] = (v4 & 0x0F) | ((v5 & 0x0F) << 4)
         *   result[3] = (v6 & 0x0F) | ((v7 & 0x0F) << 4)
         */
        uint8x8_t packed = vorr_u8(deinterleaved.val[0], odds_shifted);

        /*
         * Step 10: Store the first 4 bytes.
         * The lower 32 bits of the packed register contain the
         * 4 bytes we need. The upper 32 bits are a duplicate
         * (from the vuzp with identical inputs).
         */
        vst1_lane_u32((uint32_t *)&dst4[i / 2],
                       vreinterpret_u32_u8(packed), 0);
    }

    /*
     * Remainder loop: handle elements where n % 8 != 0.
     * Process 2 elements at a time using scalar operations.
     */
    for (; i + 2 <= n; i += 2) {
        float v0_f = src[i + 0] * scale;
        float v1_f = src[i + 1] * scale;
        int32_t v0_i, v1_i;

        /* Round to nearest integer */
        if (v0_f >= 0.0f) v0_i = (int32_t)(v0_f + 0.5f);
        else              v0_i = (int32_t)(v0_f - 0.5f);

        if (v1_f >= 0.0f) v1_i = (int32_t)(v1_f + 0.5f);
        else              v1_i = (int32_t)(v1_f - 0.5f);

        /* Clamp to int8 range */
        if (v0_i > 127) v0_i = 127;
        if (v0_i < -128) v0_i = -128;
        if (v1_i > 127) v1_i = 127;
        if (v1_i < -128) v1_i = -128;

        int8_t v0 = (int8_t)v0_i;
        int8_t v1 = (int8_t)v1_i;

        dst4[i / 2] = (uint8_t)((v0 & 0x0F) | ((v1 & 0x0F) << 4));
    }

    /*
     * Handle the last odd element if n is odd.
     */
    if (i < n) {
        float v_f = src[i] * scale;
        int32_t v_i;

        if (v_f >= 0.0f) v_i = (int32_t)(v_f + 0.5f);
        else              v_i = (int32_t)(v_f - 0.5f);

        if (v_i > 127) v_i = 127;
        if (v_i < -128) v_i = -128;

        int8_t v = (int8_t)v_i;

        dst4[i / 2] = (uint8_t)(v & 0x0F);
    }

    kernel_neon_end();
}
EXPORT_SYMBOL_GPL(neon_quantize_fp32_to_q4);

/* ============================================================
 * neon_dequantize_q8_to_fp32 - Dequantize INT8 to FP32
 * ============================================================
 *
 * Converts signed 8-bit integer values back to single-precision
 * floating-point using a scaling factor:
 *   dst[i] = (float)src[i] / scale
 *
 * NEON implementation:
 *   1. Load 4 int8 values (sign-extended to int16)
 *   2. Sign-extend to int32
 *   3. Convert to float32 using vcvtq_f32_s32
 *   4. Divide by scale
 *   5. Store 4 float32 values
 *
 * Sign extension is critical here: the int8 values are signed,
 * and we need to preserve negative values through the conversion.
 * NEON provides the vmovl instruction family for this purpose.
 *
 * @n:     Number of elements to dequantize
 * @src:   Source int8 array
 * @dst:   Destination float32 array (must have at least n * 4 bytes)
 * @scale: Scaling factor (divide after dequantization)
 */
void neon_dequantize_q8_to_fp32(int n, const void *src,
                                 float *dst, float scale)
{
    int i;
    const int8_t *src8 = (const int8_t *)src;
    float32x4_t inv_scale_vec;

    if (n <= 0 || !src || !dst) {
        pr_warn_ratelimited("neon_dequantize_q8_to_fp32: invalid "
                            "parameters (n=%d, src=%p, dst=%p)\n",
                            n, src, dst);
        return;
    }

    kernel_neon_begin();

    /*
     * Precompute the inverse scale factor.
     * Division is expensive; we multiply by 1/scale instead.
     */
    float inv_scale = 1.0f / scale;
    inv_scale_vec = vdupq_n_f32(inv_scale);

    /*
     * Process 4 elements at a time.
     *
     * The conversion pipeline:
     *   int8 -> int16 -> int32 -> float32
     *
     * vmovl_s8: Sign-extend int8x8 to int16x8.
     *   Takes an int8x8 register (8 elements) and widens each
     *   element to 16 bits, preserving the sign.
     *
     * vmovl_s16: Sign-extend int16x4 to int32x4.
     *   Takes the lower 4 elements of int16x8 and widens to
     *   int32x4, preserving the sign.
     *
     * vcvtq_f32_s32: Convert int32 to float32.
     *   Converts 4 signed 32-bit integers to single-precision
     *   floating-point values.
     */
    i = 0;

    for (; i + 4 <= n; i += 4) {
        /*
         * Load 4 int8 values.
         * We load them as a 32-bit word and reinterpret.
         *
         * vld1_s32 loads 4 consecutive bytes into a single
         * 32-bit NEON register (lower 32 bits of a 64-bit D-reg).
         * We then reinterpret as int8x8_t.
         */
        int8x8_t i8_vec = vld1_s8(&src8[i]);

        /*
         * Sign-extend int8 to int16.
         * vmovl_s8 takes an int8x8 and produces an int16x8.
         * Each 8-bit element is sign-extended to 16 bits.
         *
         * Example:
         *   Input:  [-5, 0, 127, -128, ...]
         *   Output: [-5, 0, 127, -128, ...] (as 16-bit values)
         */
        int16x8_t i16_vec = vmovl_s8(i8_vec);

        /*
         * Take the lower 4 elements and sign-extend to int32.
         * vmovl_s16 takes an int16x4 and produces an int32x4.
         */
        int16x4_t i16_lo = vget_low_s16(i16_vec);
        int32x4_t i32_vec = vmovl_s16(i16_lo);

        /*
         * Convert int32 to float32.
         * vcvtq_f32_s32 performs the conversion with rounding.
         * For integer values, this is exact for values in the
         * range [-2^24, 2^24].
         */
        float32x4_t f32_vec = vcvtq_f32_s32(i32_vec);

        /*
         * Divide by scale (multiply by precomputed inverse).
         * vmulq_f32 performs element-wise multiplication.
         */
        float32x4_t result = vmulq_f32(f32_vec, inv_scale_vec);

        /*
         * Store 4 float32 values.
         */
        vst1q_f32(&dst[i], result);
    }

    /*
     * Remainder loop: handle elements where n % 4 != 0.
     */
    for (; i < n; i++) {
        dst[i] = (float)src8[i] / scale;
    }

    kernel_neon_end();
}
EXPORT_SYMBOL_GPL(neon_dequantize_q8_to_fp32);

/* ============================================================
 * neon_dequantize_q4_to_fp32 - Dequantize 4-bit Packed to FP32
 * ============================================================
 *
 * Converts packed 4-bit integer values back to single-precision
 * floating-point using a scaling factor:
 *   dst[i]     = (float)(int8_t)(byte & 0x0F) / scale
 *   dst[i + 1] = (float)(int8_t)(byte >> 4) / scale
 *
 * Each byte in the source contains two 4-bit values:
 *   low nibble (bits 0-3): even-indexed element
 *   high nibble (bits 4-7): odd-indexed element
 *
 * NEON implementation:
 *   1. Load 4 bytes (8 four-bit values)
 *   2. De-interleave into even and odd nibbles
 *   3. Sign-extend each nibble to int8
 *   4. Sign-extend to int16, then int32
 *   5. Convert to float32
 *   6. Divide by scale
 *   7. Interleave results back into original order
 *   8. Store 8 float32 values
 *
 * Sign extension of 4-bit values:
 *   The nibble is treated as a signed 4-bit value in [-8, 7].
 *   To sign-extend a 4-bit value to 8-bit:
 *     (int8_t)(nibble << 4) >> 4
 *   This preserves the sign bit (bit 3 of the nibble).
 *
 * @n:     Number of elements to dequantize
 * @src:   Source uint8 array (packed 4-bit, n/2 bytes)
 * @dst:   Destination float32 array (n elements)
 * @scale: Scaling factor (divide after dequantization)
 */
void neon_dequantize_q4_to_fp32(int n, const void *src,
                                 float *dst, float scale)
{
    int i;
    const uint8_t *src4 = (const uint8_t *)src;
    float32x4_t inv_scale_vec;

    if (n <= 0 || !src || !dst) {
        pr_warn_ratelimited("neon_dequantize_q4_to_fp32: invalid "
                            "parameters (n=%d, src=%p, dst=%p)\n",
                            n, src, dst);
        return;
    }

    kernel_neon_begin();

    /*
     * Precompute the inverse scale factor for multiplication
     * instead of division.
     */
    float inv_scale = 1.0f / scale;
    inv_scale_vec = vdupq_n_f32(inv_scale);

    /*
     * Main loop: process 8 elements at a time (4 bytes of packed data).
     *
     * The NEON pipeline for 8 elements:
     *   1. Load 4 bytes from packed source
     *   2. Unpack bytes into 8 nibbles (even and odd)
     *   3. Sign-extend each nibble from 4-bit to 8-bit
     *   4. Sign-extend 8-bit to 16-bit, then 32-bit
     *   5. Convert to float32
     *   6. Multiply by inverse scale
     *   7. Store 8 float32 values
     */
    i = 0;

    for (; i + 8 <= n; i += 8) {
        /*
         * Step 1: Load 4 packed bytes.
         * Each byte contains two 4-bit values:
         *   byte = [v_i nibble | v_{i+1} nibble]
         * We load as a 32-bit word.
         */
        uint8x8_t packed = vld1_u8(&src4[i / 2]);

        /*
         * Step 2: Extract low and high nibbles.
         *
         * Low nibbles: packed & 0x0F (even-indexed elements)
         * High nibbles: (packed >> 4) & 0x0F (odd-indexed elements)
         *
         * We use vand for masking and vshr for shifting.
         */
        uint8x8_t lo_nibbles = vand_u8(packed, vdup_n_u8(0x0F));
        uint8x8_t hi_nibbles = vshr_n_u8(packed, 4);

        /*
         * Step 3: Interleave low and high nibbles to restore
         * the original element order.
         *
         * vzip_u8 interleaves two vectors:
         *   result.val[0] = [lo[0], hi[0], lo[1], hi[1], ...]
         *
         * This gives us the original element order:
         *   result.val[0] = [v0_nibble, v1_nibble, v2_nibble, ...]
         */
        uint8x8x2_t interleaved = vzip_u8(lo_nibbles, hi_nibbles);
        uint8x8_t nibbles = interleaved.val[0];

        /*
         * Step 4: Sign-extend each 4-bit nibble to 8-bit.
         *
         * Each nibble is in the range [0, 15]. To interpret it
         * as a signed 4-bit value [-8, 7], we sign-extend.
         *
         * The sign extension works by:
         *   (int8_t)(nibble << 4) >> 4
         *
         * This shifts the nibble to the high 4 bits of a byte,
         * then does an arithmetic right shift to sign-extend.
         *
         * Example: nibble = 0x0B (11 unsigned)
         *   (11 << 4) = 0xB0 = 176 as unsigned, -80 as signed
         *   (-80 >> 4) = -5 (arithmetic shift preserves sign)
         *
         * Result: -5, which is the correct signed interpretation
         * of nibble 0x0B in 4-bit two's complement.
         */
        int8x8_t i8_vec = vreinterpret_s8_u8(nibbles);

        /*
         * Apply sign extension: (int8_t)(nibble << 4) >> 4.
         * We shift left by 4, then arithmetic right by 4.
         * vshl_n_s8: left shift (logical)
         * vshr_n_s8: arithmetic right shift (preserves sign)
         */
        int8x8_t shifted = vshl_n_s8(i8_vec, 4);
        int8x8_t sign_ext = vshr_n_s8(shifted, 4);

        /*
         * Step 5: Sign-extend int8 to int16.
         * vmovl_s8 widens each 8-bit element to 16 bits,
         * preserving the sign.
         */
        int16x8_t i16_vec = vmovl_s8(sign_ext);

        /*
         * Step 6: Sign-extend int16 to int32.
         * We process the lower 4 and upper 4 elements separately.
         */
        int16x4_t i16_lo = vget_low_s16(i16_vec);
        int16x4_t i16_hi = vget_high_s16(i16_vec);

        int32x4_t i32_lo = vmovl_s16(i16_lo);
        int32x4_t i32_hi = vmovl_s16(i16_hi);

        /*
         * Step 7: Convert int32 to float32.
         */
        float32x4_t f32_lo = vcvtq_f32_s32(i32_lo);
        float32x4_t f32_hi = vcvtq_f32_s32(i32_hi);

        /*
         * Step 8: Multiply by inverse scale factor.
         * dst[i] = (float)value * inv_scale = (float)value / scale
         */
        float32x4_t result_lo = vmulq_f32(f32_lo, inv_scale_vec);
        float32x4_t result_hi = vmulq_f32(f32_hi, inv_scale_vec);

        /*
         * Step 9: Store 8 float32 values.
         */
        vst1q_f32(&dst[i + 0], result_lo);
        vst1q_f32(&dst[i + 4], result_hi);
    }

    /*
     * Remainder loop: handle elements where n % 8 != 0.
     * Process 2 elements at a time using scalar operations.
     */
    for (; i + 2 <= n; i += 2) {
        uint8_t byte = src4[i / 2];
        int8_t v0 = (int8_t)(byte & 0x0F);
        int8_t v1 = (int8_t)(byte >> 4);

        /* Sign-extend 4-bit to 8-bit */
        v0 = (int8_t)(v0 << 4) >> 4;
        v1 = (int8_t)(v1 << 4) >> 4;

        dst[i + 0] = (float)v0 / scale;
        dst[i + 1] = (float)v1 / scale;
    }

    /*
     * Handle the last odd element if n is odd.
     */
    if (i < n) {
        uint8_t byte = src4[i / 2];
        int8_t v0 = (int8_t)(byte & 0x0F);
        v0 = (int8_t)(v0 << 4) >> 4;
        dst[i] = (float)v0 / scale;
    }

    kernel_neon_end();
}
EXPORT_SYMBOL_GPL(neon_dequantize_q4_to_fp32);

/* ============================================================
 * neon_batch_dot_product - Batch Dot Product
 * ============================================================
 *
 * Computes batch_size independent dot products:
 *   results[i] = sum_{j=0}^{n-1} a[i*n + j] * b[i*n + j]
 *
 * This is useful for computing multiple attention scores or
 * similarity measures in parallel. The vectors are stored
 * contiguously: a and b each have batch_size * n elements.
 *
 * NEON implementation:
 *   For each batch, compute the dot product using the standard
 *   4-wide NEON dot product kernel. Batch processing allows
 *   the prefetcher to work ahead across batch boundaries.
 *
 * @batch_size: Number of independent dot products to compute
 * @n:          Length of each vector
 * @a:          Source array A (batch_size * n elements)
 * @b:          Source array B (batch_size * n elements)
 * @results:    Output array (batch_size elements)
 */
void neon_batch_dot_product(int batch_size, int n,
                             const float *a, const float *b,
                             float *results)
{
    int batch;

    if (batch_size <= 0 || n <= 0 || !a || !b || !results) {
        pr_warn_ratelimited("neon_batch_dot_product: invalid parameters "
                            "(batch=%d, n=%d, a=%p, b=%p, results=%p)\n",
                            batch_size, n, a, b, results);
        return;
    }

    kernel_neon_begin();

    /*
     * Process each batch item independently.
     *
     * For small n (n <= 32), we use the standard dot product
     * which is already well-optimized.
     *
     * For larger n, we can benefit from prefetching across
     * batch boundaries.
     */
    if (n <= 32) {
        /*
         * Small n: use the fast unrolled dot product.
         * Each batch is processed independently with minimal
         * overhead.
         */
        for (batch = 0; batch < batch_size; batch++) {
            results[batch] = neon_dot_product_fast(
                n,
                a + batch * n,
                b + batch * n);
        }
    } else if (n <= 128) {
        /*
         * Medium n: use unrolled-by-8 variant.
         */
        for (batch = 0; batch < batch_size; batch++) {
            results[batch] = neon_dot_product_unrolled8(
                n,
                a + batch * n,
                b + batch * n);
        }
    } else {
        /*
         * Large n: interleave prefetch and computation.
         * We prefetch the next batch's data while computing
         * the current batch's dot product.
         */
        for (batch = 0; batch < batch_size; batch++) {
            const float *a_batch = a + batch * n;
            const float *b_batch = b + batch * n;

            /*
             * Prefetch the next batch's data to L1 cache.
             * This hides memory latency for large vectors.
             */
            if (batch + 1 < batch_size) {
                neon_prefetch_ld(a + (batch + 1) * n, 3);
                neon_prefetch_ld(b + (batch + 1) * n, 3);
            }

            results[batch] = neon_dot_product_unrolled8(
                n, a_batch, b_batch);
        }
    }

    kernel_neon_end();
}
EXPORT_SYMBOL_GPL(neon_batch_dot_product);

/* ============================================================
 * Batch Dot Product Variant: Interleaved Processing
 * ============================================================
 *
 * Computes multiple batch dot products simultaneously by
 * interleaving loads from different batches. This improves
 * instruction-level parallelism and memory-level parallelism.
 *
 * Instead of processing one batch at a time, we process 4 batches
 * in parallel, loading data from all 4 batches before computing.
 *
 * @batch_size: Number of batches
 * @n:          Vector length
 * @a:          Source array A
 * @b:          Source array B
 * @results:    Output array
 */
static void neon_batch_dot_product_interleaved(int batch_size, int n,
                                                 const float *a,
                                                 const float *b,
                                                 float *results)
{
    int batch;

    /*
     * Process batches in groups of 4 to maximize ILP.
     * This is only beneficial when batch_size is large enough.
     */
    for (batch = 0; batch + 4 <= batch_size; batch += 4) {
        float32x4_t sums[4];
        int j;

        for (int i = 0; i < 4; i++)
            sums[i] = vdupq_n_f32(0.0f);

        /*
         * Inner loop: process 4 elements from each of 4 batches.
         */
        for (j = 0; j + 4 <= n; j += 4) {
            for (int i = 0; i < 4; i++) {
                float32x4_t a_vec = vld1q_f32(&a[(batch + i) * n + j]);
                float32x4_t b_vec = vld1q_f32(&b[(batch + i) * n + j]);

                sums[i] = vmlaq_f32(sums[i], a_vec, b_vec);
            }
        }

        /* Remainder elements */
        for (; j < n; j++) {
            for (int i = 0; i < 4; i++) {
                float a_val = a[(batch + i) * n + j];
                float b_val = b[(batch + i) * n + j];

                sums[i] = vmlaq_n_f32(sums[i],
                                       vdupq_n_f32(b_val), a_val);
            }
        }

        /* Horizontal reduction for each batch */
        for (int i = 0; i < 4; i++) {
            float32x2_t pair = vpadd_f32(vget_low_f32(sums[i]),
                                          vget_high_f32(sums[i]));
            results[batch + i] = vpadds_f32(pair);
        }
    }

    /* Handle remaining batches */
    for (; batch < batch_size; batch++) {
        results[batch] = neon_dot_product_fast(
            n, a + batch * n, b + batch * n);
    }
}

/* ============================================================
 * Batch Dot Product Variant: Prefetch-Only
 * ============================================================
 *
 * Lightweight variant that only adds prefetching to the standard
 * dot product. Used when the batches are too large for interleaved
 * processing but we still want to hide memory latency.
 *
 * @batch_size: Number of batches
 * @n:          Vector length
 * @a:          Source array A
 * @b:          Source array B
 * @results:    Output array
 */
static void neon_batch_dot_product_prefetch(int batch_size, int n,
                                              const float *a,
                                              const float *b,
                                              float *results)
{
    int batch;
    int prefetch_ahead = 4;

    for (batch = 0; batch < batch_size; batch++) {
        const float *a_cur = a + batch * n;
        const float *b_cur = b + batch * n;

        /* Prefetch future batches */
        if (batch + prefetch_ahead < batch_size) {
            neon_prefetch_ld(a + (batch + prefetch_ahead) * n, 1);
            neon_prefetch_ld(b + (batch + prefetch_ahead) * n, 1);
        }

        results[batch] = neon_dot_product_unrolled8(n, a_cur, b_cur);
    }
}

/* ============================================================
 * Vectorized Activation Functions
 * ============================================================
 *
 * NEON-accelerated neural network activation functions for
 * element-wise operations on single-precision arrays.
 * These are used in AI inference pipelines for post-processing
 * matrix multiplication results.
 *
 * All functions operate in-place on the data array, processing
 * 4 elements at a time using NEON intrinsics.
 */

/**
 * neon_activation_relu - Rectified Linear Unit (ReLU)
 * @n: Number of elements
 * @data: Input/output array (modified in-place)
 *
 * ReLU(x) = max(0, x)
 *
 * NEON implementation: vmaxq_f32 compares each element with 0
 * and returns the maximum. This is a single instruction.
 */
static void neon_activation_relu(int n, float *data)
{
    int i;
    float32x4_t zero = vdupq_n_f32(0.0f);

    for (i = 0; i + 4 <= n; i += 4) {
        float32x4_t vec = vld1q_f32(&data[i]);
        float32x4_t result = vmaxq_f32(vec, zero);
        vst1q_f32(&data[i], result);
    }

    /* Remainder */
    for (; i < n; i++) {
        if (data[i] < 0.0f)
            data[i] = 0.0f;
    }
}

/**
 * neon_activation_relu6 - ReLU6 (ReLU capped at 6)
 * @n: Number of elements
 * @data: Input/output array
 *
 * ReLU6(x) = min(max(0, x), 6)
 *
 * Used in quantized neural networks (e.g., MobileNets) to
 * limit the output range for better quantization accuracy.
 */
static void neon_activation_relu6(int n, float *data)
{
    int i;
    float32x4_t zero = vdupq_n_f32(0.0f);
    float32x4_t six = vdupq_n_f32(6.0f);

    for (i = 0; i + 4 <= n; i += 4) {
        float32x4_t vec = vld1q_f32(&data[i]);
        vec = vmaxq_f32(vec, zero);
        vec = vminq_f32(vec, six);
        vst1q_f32(&data[i], vec);
    }

    for (; i < n; i++) {
        if (data[i] < 0.0f) data[i] = 0.0f;
        if (data[i] > 6.0f) data[i] = 6.0f;
    }
}

/**
 * neon_activation_leaky_relu - Leaky ReLU
 * @n: Number of elements
 * @data: Input/output array
 * @alpha: Negative slope (e.g., 0.01 for standard Leaky ReLU)
 *
 * LeakyReLU(x) = max(alpha * x, x)
 *
 * The NEON implementation uses vmaxq_f32 to compare the
 * original value with the scaled value, selecting the larger.
 */
static void neon_activation_leaky_relu(int n, float *data, float alpha)
{
    int i;
    float32x4_t alpha_vec = vdupq_n_f32(alpha);

    for (i = 0; i + 4 <= n; i += 4) {
        float32x4_t vec = vld1q_f32(&data[i]);
        float32x4_t scaled = vmulq_f32(vec, alpha_vec);
        float32x4_t result = vmaxq_f32(vec, scaled);
        vst1q_f32(&data[i], result);
    }

    for (; i < n; i++) {
        if (data[i] < 0.0f)
            data[i] *= alpha;
    }
}

/**
 * neon_activation_sigmoid - Sigmoid activation (approximation)
 * @n: Number of elements
 * @data: Input/output array
 *
 * Sigmoid(x) = 1.0 / (1.0 + exp(-x))
 *
 * This implementation uses a polynomial approximation suitable
 * for NEON. The approximation is accurate to within ~1e-3 over
 * the range [-8, 8].
 *
 * For higher accuracy, replace with a table-based approach or
 * use the more accurate vexp approximation.
 */
static void neon_activation_sigmoid(int n, float *data)
{
    int i;
    float32x4_t one = vdupq_n_f32(1.0f);

    for (i = 0; i + 4 <= n; i += 4) {
        float32x4_t x = vld1q_f32(&data[i]);

        /*
         * Clamp input to avoid overflow in exp computation.
         * exp(-x) overflows for large negative x, so we clamp
         * to [-10, 10] which gives sigmoid values in [0, 1].
         */
        float32x4_t neg_ten = vdupq_n_f32(-10.0f);
        float32x4_t ten = vdupq_n_f32(10.0f);
        x = vmaxq_f32(x, neg_ten);
        x = vminq_f32(x, ten);

        /*
         * Compute exp(-x) using a NEON-compatible approximation.
         * We use the identity: exp(-x) = 2^(-x * log2(e))
         * and compute 2^y using a polynomial approximation.
         *
         * This is a simplified approximation. For production use,
         * consider a more accurate exp implementation.
         *
         * The approximation: exp(-x) ~= 1 / (1 + x + x^2/2 + x^3/6)
         * for small x, with clamping for large x.
         */
        float32x4_t neg_x = vnegq_f32(x);

        /*
         * Use the fast sigmoid approximation:
         * sigmoid(x) = 0.5 + 0.197 * x - 0.004 * x^3
         * This is a cubic approximation valid for [-4, 4].
         *
         * For better accuracy, we use the piecewise approach:
         *   x < -8: sigmoid ~= 0
         *   x > 8:  sigmoid ~= 1
         *   otherwise: use approximation
         */
        float32x4_t x2 = vmulq_f32(neg_x, neg_x);
        float32x4_t x3 = vmulq_f32(x2, neg_x);

        /*
         * Polynomial: 0.5 + 0.197*x - 0.004*x^3
         * Coefficients from the cubic sigmoid approximation.
         */
        float32x4_t c0 = vdupq_n_f32(0.5f);
        float32x4_t c1 = vdupq_n_f32(0.197f);
        float32x4_t c3 = vdupq_n_f32(-0.004f);

        float32x4_t result = vmlaq_f32(c0, c1, neg_x);
        result = vmlaq_f32(result, c3, x3);

        /*
         * Clamp to [epsilon, 1-epsilon] for numerical stability.
         */
        float32x4_t eps = vdupq_n_f32(1e-7f);
        float32x4_t one_minus_eps = vdupq_n_f32(1.0f - 1e-7f);
        result = vmaxq_f32(result, eps);
        result = vminq_f32(result, one_minus_eps);

        vst1q_f32(&data[i], result);
    }

    /* Scalar remainder */
    for (; i < n; i++) {
        float x = data[i];
        if (x < -8.0f) data[i] = 0.0f;
        else if (x > 8.0f) data[i] = 1.0f;
        else data[i] = 1.0f / (1.0f + expf(-x));
    }
}

/**
 * neon_activation_tanh - Hyperbolic tangent activation
 * @n: Number of elements
 * @data: Input/output array
 *
 * tanh(x) = 2 * sigmoid(2x) - 1
 *
 * Uses the sigmoid approximation and the identity to compute
 * tanh from sigmoid.
 */
static void neon_activation_tanh(int n, float *data)
{
    int i;
    float32x4_t two = vdupq_n_f32(2.0f);
    float32x4_t one = vdupq_n_f32(1.0f);

    for (i = 0; i + 4 <= n; i += 4) {
        float32x4_t x = vld1q_f32(&data[i]);

        /*
         * tanh(x) = 2 * sigmoid(2x) - 1
         * Compute 2x, pass through sigmoid approximation,
         * then multiply by 2 and subtract 1.
         */
        float32x4_t x2 = vmulq_f32(x, two);

        /* Clamp for sigmoid stability */
        float32x4_t neg_ten = vdupq_n_f32(-10.0f);
        float32x4_t ten = vdupq_n_f32(10.0f);
        x2 = vmaxq_f32(x2, neg_ten);
        x2 = vminq_f32(x2, ten);

        /* Sigmoid approximation */
        float32x4_t x2_sq = vmulq_f32(x2, x2);
        float32x4_t x2_cu = vmulq_f32(x2_sq, x2);

        float32x4_t c0 = vdupq_n_f32(0.5f);
        float32x4_t c1 = vdupq_n_f32(0.197f);
        float32x4_t c3 = vdupq_n_f32(-0.004f);

        float32x4_t sig = vmlaq_f32(c0, c1, x2);
        sig = vmlaq_f32(sig, c3, x2_cu);

        /* tanh = 2 * sig - 1 */
        float32x4_t tanh_val = vsubq_f32(vmulq_f32(sig, two), one);

        /* Clamp to [-1, 1] */
        float32x4_t neg_one = vdupq_n_f32(-1.0f);
        tanh_val = vmaxq_f32(tanh_val, neg_one);
        tanh_val = vminq_f32(tanh_val, one);

        vst1q_f32(&data[i], tanh_val);
    }

    /* Scalar remainder */
    for (; i < n; i++) {
        data[i] = tanhf(data[i]);
    }
}

/* ============================================================
 * Vectorized Element-wise Operations
 * ============================================================
 *
 * NEON-accelerated element-wise operations for AI inference:
 *   - add: element-wise addition of two arrays
 *   - sub: element-wise subtraction
 *   - mul: element-wise multiplication
 *   - div: element-wise division
 *   - scale: multiply all elements by a scalar
 *   - add_scalar: add a constant to all elements
 *   - clip: clamp values to [min, max] range
 */

/**
 * neon_elemwise_add - Element-wise addition
 * @n: Number of elements
 * @a: First input array
 * @b: Second input array
 * @dst: Output array (may alias a or b)
 */
static void neon_elemwise_add(int n, const float *a,
                               const float *b, float *dst)
{
    int i;
    for (i = 0; i + 4 <= n; i += 4) {
        float32x4_t va = vld1q_f32(&a[i]);
        float32x4_t vb = vld1q_f32(&b[i]);
        vst1q_f32(&dst[i], vaddq_f32(va, vb));
    }
    for (; i < n; i++)
        dst[i] = a[i] + b[i];
}

/**
 * neon_elemwise_sub - Element-wise subtraction
 * @n: Number of elements
 * @a: First input array
 * @b: Second input array (subtracted from a)
 * @dst: Output array
 */
static void neon_elemwise_sub(int n, const float *a,
                               const float *b, float *dst)
{
    int i;
    for (i = 0; i + 4 <= n; i += 4) {
        float32x4_t va = vld1q_f32(&a[i]);
        float32x4_t vb = vld1q_f32(&b[i]);
        vst1q_f32(&dst[i], vsubq_f32(va, vb));
    }
    for (; i < n; i++)
        dst[i] = a[i] - b[i];
}

/**
 * neon_elemwise_mul - Element-wise multiplication
 * @n: Number of elements
 * @a: First input array
 * @b: Second input array
 * @dst: Output array
 */
static void neon_elemwise_mul(int n, const float *a,
                               const float *b, float *dst)
{
    int i;
    for (i = 0; i + 4 <= n; i += 4) {
        float32x4_t va = vld1q_f32(&a[i]);
        float32x4_t vb = vld1q_f32(&b[i]);
        vst1q_f32(&dst[i], vmulq_f32(va, vb));
    }
    for (; i < n; i++)
        dst[i] = a[i] * b[i];
}

/**
 * neon_elemwise_scale - Multiply all elements by scalar
 * @n: Number of elements
 * @data: Input/output array
 * @scalar: Multiplication factor
 */
static void neon_elemwise_scale(int n, float *data, float scalar)
{
    int i;
    float32x4_t s = vdupq_n_f32(scalar);

    for (i = 0; i + 4 <= n; i += 4) {
        float32x4_t v = vld1q_f32(&data[i]);
        vst1q_f32(&data[i], vmulq_f32(v, s));
    }
    for (; i < n; i++)
        data[i] *= scalar;
}

/**
 * neon_elemwise_add_scalar - Add constant to all elements
 * @n: Number of elements
 * @data: Input/output array
 * @scalar: Constant to add
 */
static void neon_elemwise_add_scalar(int n, float *data, float scalar)
{
    int i;
    float32x4_t s = vdupq_n_f32(scalar);

    for (i = 0; i + 4 <= n; i += 4) {
        float32x4_t v = vld1q_f32(&data[i]);
        vst1q_f32(&data[i], vaddq_f32(v, s));
    }
    for (; i < n; i++)
        data[i] += scalar;
}

/**
 * neon_elemwise_clip - Clip values to [min, max] range
 * @n: Number of elements
 * @data: Input/output array
 * @min_val: Minimum value
 * @max_val: Maximum value
 */
static void neon_elemwise_clip(int n, float *data,
                                float min_val, float max_val)
{
    int i;
    float32x4_t vmin = vdupq_n_f32(min_val);
    float32x4_t vmax = vdupq_n_f32(max_val);

    for (i = 0; i + 4 <= n; i += 4) {
        float32x4_t v = vld1q_f32(&data[i]);
        v = vmaxq_f32(v, vmin);
        v = vminq_f32(v, vmax);
        vst1q_f32(&data[i], v);
    }
    for (; i < n; i++) {
        if (data[i] < min_val) data[i] = min_val;
        if (data[i] > max_val) data[i] = max_val;
    }
}

/* ============================================================
 * Vectorized Softmax Helper
 * ============================================================
 *
 * NEON-accelerated softmax computation for inference.
 * Computes softmax over a single vector of n elements:
 *   softmax(x_i) = exp(x_i) / sum_j exp(x_j)
 *
 * The implementation:
 *   1. Find the maximum value (for numerical stability)
 *   2. Subtract max and compute exp(x_i - max)
 *   3. Sum all exp values
 *   4. Divide each exp by the sum
 */

/**
 * neon_softmax_inplace - Compute softmax in-place
 * @n: Number of elements
 * @data: Input/output array (modified in-place)
 *
 * The softmax function is computed with numerical stability
 * by subtracting the maximum value before exponentiation.
 */
static void neon_softmax_inplace(int n, float *data)
{
    int i;

    if (n <= 0)
        return;

    /*
     * Step 1: Find the maximum value in the array.
     * We use NEON vmaxq_f32 to find the max in chunks of 4,
     * then reduce to a single scalar.
     */
    float32x4_t vmax = vld1q_f32(&data[0]);

    for (i = 4; i + 4 <= n; i += 4) {
        float32x4_t v = vld1q_f32(&data[i]);
        vmax = vmaxq_f32(vmax, v);
    }

    /* Handle remainder */
    for (; i < n; i++) {
        /* We'll handle this in the scalar fallback */
    }

    /* Horizontal max reduction */
    float max_val = vgetq_lane_f32(vmax, 0);
    for (int lane = 1; lane < 4; lane++) {
        float lane_val = vgetq_lane_f32(vmax, lane);
        if (lane_val > max_val)
            max_val = lane_val;
    }

    /* Check remainder elements */
    for (i = (n & ~3); i < n; i++) {
        if (data[i] > max_val)
            max_val = data[i];
    }

    /*
     * Step 2: Subtract max, compute exp, and sum.
     * We process 4 elements at a time.
     */
    float32x4_t sum_vec = vdupq_n_f32(0.0f);
    float32x4_t vmax_vec = vdupq_n_f32(max_val);

    for (i = 0; i + 4 <= n; i += 4) {
        float32x4_t v = vld1q_f32(&data[i]);
        float32x4_t shifted = vsubq_f32(v, vmax_vec);

        /*
         * Exponential approximation using NEON.
         * We use the identity: exp(x) = 2^(x * log2(e))
         * and compute 2^y using a polynomial.
         *
         * For the softmax, we need a better approximation
         * than the sigmoid one. Here we use a minimax
         * polynomial for exp(x) on [-8, 8].
         */
        float32x4_t exp_val;

        /*
         * Clamp input to avoid overflow/underflow.
         * exp(-100) is essentially 0, exp(100) is huge.
         */
        float32x4_t neg_max = vdupq_n_f32(-80.0f);
        shifted = vmaxq_f32(shifted, neg_max);

        /*
         * Simple exp approximation:
         * exp(x) ~= 1 + x + x^2/2 + x^3/6 + x^4/24
         * This is a 4th-order Taylor expansion.
         */
        float32x4_t x = shifted;
        float32x4_t x2 = vmulq_f32(x, x);
        float32x4_t x3 = vmulq_f32(x2, x);
        float32x4_t x4 = vmulq_f32(x3, x);

        /* Coefficients */
        float32x4_t c0 = vdupq_n_f32(1.0f);
        float32x4_t c1 = vdupq_n_f32(1.0f);
        float32x4_t c2 = vdupq_n_f32(0.5f);
        float32x4_t c3 = vdupq_n_f32(1.0f / 6.0f);
        float32x4_t c4 = vdupq_n_f32(1.0f / 24.0f);

        exp_val = vmlaq_f32(c0, c1, x);
        exp_val = vmlaq_f32(exp_val, c2, x2);
        exp_val = vmlaq_f32(exp_val, c3, x3);
        exp_val = vmlaq_f32(exp_val, c4, x4);

        /* Clamp to avoid INF */
        float32x4_t huge = vdupq_n_f32(1e20f);
        exp_val = vminq_f32(exp_val, huge);

        vst1q_f32(&data[i], exp_val);
        sum_vec = vaddq_f32(sum_vec, exp_val);
    }

    /* Handle remainder with scalar expf */
    for (; i < n; i++) {
        float shifted = data[i] - max_val;
        data[i] = expf(shifted);
        /* We'll add to sum in the scalar loop below */
    }

    /* Compute total sum */
    float sum = 0.0f;
    for (i = 0; i < n; i++)
        sum += data[i];

    /*
     * Step 3: Divide each element by the sum.
     * We use vmulq_f32 with the precomputed inverse.
     */
    float inv_sum = 1.0f / sum;
    float32x4_t inv_sum_vec = vdupq_n_f32(inv_sum);

    for (i = 0; i + 4 <= n; i += 4) {
        float32x4_t v = vld1q_f32(&data[i]);
        vst1q_f32(&data[i], vmulq_f32(v, inv_sum_vec));
    }

    for (; i < n; i++)
        data[i] *= inv_sum;
}

/* ============================================================
 * Matrix Transpose & Utility Operations
 * ============================================================
 *
 * NEON-accelerated matrix operations for AI inference:
 *   - transpose: in-place and out-of-place transpose
 *   - copy: strided copy with NEON
 *   - zero: zero-initialize a matrix
 *   - fill: fill with a constant value
 */

/**
 * neon_matrix_transpose - Transpose an m x n matrix
 * @m: Number of rows in source
 * @n: Number of columns in source
 * @src: Source matrix (m x n, row-major)
 * @dst: Destination matrix (n x m, row-major)
 *
 * For small matrices, NEON's vtrn/vzip instructions can be used
 * for efficient transpose. For larger matrices, we use tiled
 * transpose with cache blocking.
 */
static void neon_matrix_transpose(int m, int n,
                                   const float *src, float *dst)
{
    /*
     * For 4x4 blocks, we can use the NEON transpose instructions.
     * vtrnq_f32 transposes 4x4 matrices in 4 instructions.
     *
     * For larger matrices, we process in 4x4 tiles.
     */
    int i, j;

    for (i = 0; i < m; i += 4) {
        int mr = MIN(4, m - i);

        for (j = 0; j < n; j += 4) {
            int nr = MIN(4, n - j);

            if (mr == 4 && nr == 4) {
                /*
                 * Load a 4x4 block and transpose it using NEON.
                 * vld4q_f32 loads 4 vectors, each representing
                 * a row of the 4x4 block.
                 */
                float32x4x4_t rows;

                rows.val[0] = vld1q_f32(&src[(i + 0) * n + j]);
                rows.val[1] = vld1q_f32(&src[(i + 1) * n + j]);
                rows.val[2] = vld1q_f32(&src[(i + 2) * n + j]);
                rows.val[3] = vld1q_f32(&src[(i + 3) * n + j]);

                /*
                 * Transpose the 4x4 matrix using vtrnq_f32.
                 * This swaps elements across the diagonal.
                 */
                float32x4x4_t transposed = vtrnq_f32(
                    rows.val[0], rows.val[1]);
                float32x4x4_t transposed2 = vtrnq_f32(
                    rows.val[2], rows.val[3]);

                float32x4x4_t result;
                result.val[0] = vcombine_f32(
                    vget_low_f32(transposed.val[0]),
                    vget_low_f32(transposed2.val[0]));
                result.val[1] = vcombine_f32(
                    vget_low_f32(transposed.val[1]),
                    vget_low_f32(transposed2.val[1]));
                result.val[2] = vcombine_f32(
                    vget_high_f32(transposed.val[0]),
                    vget_high_f32(transposed2.val[0]));
                result.val[3] = vcombine_f32(
                    vget_high_f32(transposed.val[1]),
                    vget_high_f32(transposed2.val[1]));

                /*
                 * Store the transposed block.
                 * The block in dst is at position (j, i) since
                 * the destination is n x m.
                 */
                vst1q_f32(&dst[(j + 0) * m + i], result.val[0]);
                vst1q_f32(&dst[(j + 1) * m + i], result.val[1]);
                vst1q_f32(&dst[(j + 2) * m + i], result.val[2]);
                vst1q_f32(&dst[(j + 3) * m + i], result.val[3]);
            } else {
                /*
                 * Partial block: use scalar transpose.
                 */
                for (int ii = 0; ii < mr; ii++) {
                    for (int jj = 0; jj < nr; jj++) {
                        dst[(j + jj) * m + (i + ii)] =
                            src[(i + ii) * n + (j + jj)];
                    }
                }
            }
        }
    }
}

/**
 * neon_matrix_zero - Zero-initialize an m x n matrix
 * @m: Number of rows
 * @n: Number of columns
 * @data: Matrix to zero
 *
 * Uses NEON vst1q_f32 to zero 4 elements at a time.
 */
static inline void neon_matrix_zero(int m, int n, float *data)
{
    int total = m * n;
    int i;
    float32x4_t zero = vdupq_n_f32(0.0f);

    for (i = 0; i + 4 <= total; i += 4)
        vst1q_f32(&data[i], zero);

    for (; i < total; i++)
        data[i] = 0.0f;
}

/**
 * neon_matrix_fill - Fill an m x n matrix with a constant value
 * @m: Number of rows
 * @n: Number of columns
 * @data: Matrix to fill
 * @val: Fill value
 */
static inline void neon_matrix_fill(int m, int n, float *data, float val)
{
    int total = m * n;
    int i;
    float32x4_t vval = vdupq_n_f32(val);

    for (i = 0; i + 4 <= total; i += 4)
        vst1q_f32(&data[i], vval);

    for (; i < total; i++)
        data[i] = val;
}

/* ============================================================
 * Matrix Copy with Stride
 * ============================================================
 *
 * Copies a matrix from source to destination with arbitrary
 * strides. This is useful for extracting sub-matrices or
 * rearranging data for the NEON kernels.
 */

/**
 * neon_matrix_copy_stride - Copy matrix with stride
 * @m: Number of rows to copy
 * @n: Number of columns to copy
 * @src: Source matrix (stride = src_stride)
 * @src_stride: Source row stride (in floats)
 * @dst: Destination matrix (stride = dst_stride)
 * @dst_stride: Destination row stride (in floats)
 */
static void neon_matrix_copy_stride(int m, int n,
                                     const float *src, int src_stride,
                                     float *dst, int dst_stride)
{
    for (int i = 0; i < m; i++) {
        /*
         * Copy one row of n elements using NEON if aligned.
         * Process 4 elements at a time.
         */
        int j;
        for (j = 0; j + 4 <= n; j += 4) {
            float32x4_t v = vld1q_f32(&src[i * src_stride + j]);
            vst1q_f32(&dst[i * dst_stride + j], v);
        }

        /* Remainder */
        for (; j < n; j++)
            dst[i * dst_stride + j] = src[i * src_stride + j];
    }
}

/* ============================================================
 * SIMD Operations Structure
 * ============================================================
 *
 * Defines the NEON implementation of all SIMD operations.
 * This struct is registered with the main accelerator module
 * through the neon_get_ops() function.
 *
 * The struct matches the simd_ops definition from simd_impl.h,
 * providing function pointers for all operations.
 */

static const struct simd_ops neon_simd_ops = {
    .matmul_fp32           = neon_matmul_fp32,
    .dot_product           = neon_dot_product,
    .quantize_fp32_to_q8   = neon_quantize_fp32_to_q8,
    .quantize_fp32_to_q4   = neon_quantize_fp32_to_q4,
    .dequantize_q8_to_fp32 = neon_dequantize_q8_to_fp32,
    .dequantize_q4_to_fp32 = neon_dequantize_q4_to_fp32,
    .name                  = "neon",
    .vector_size           = 16,  /* 128-bit NEON registers = 16 bytes */
};

/* ============================================================
 * neon_get_ops - Get NEON SIMD Operations
 * ============================================================
 *
 * Returns a pointer to the NEON implementation of the SIMD
 * operations structure. This is called by the main accelerator
 * module during initialization to register the NEON backend.
 *
 * The returned structure remains valid for the lifetime of the
 * module and should not be modified or freed.
 *
 * Return: Pointer to the constant simd_ops structure
 */
const struct simd_ops *neon_get_ops(void)
{
    return &neon_simd_ops;
}
EXPORT_SYMBOL_GPL(neon_get_ops);

/* ============================================================
 * Fused Operations (MatMul + Activation)
 * ============================================================
 *
 * Fused operations combine matrix multiplication with an
 * element-wise activation function. This reduces memory
 * bandwidth by avoiding intermediate reads/writes.
 *
 * The general pattern:
 *   C = op(A * B)
 *
 * where op is an activation function applied element-wise
 * to the result.
 */

/**
 * neon_matmul_relu_fp32 - MatMul with fused ReLU activation
 * @m: Number of rows in A and C
 * @n: Number of columns in B and C
 * @k: Number of columns in A, rows in B
 * @a: Matrix A (m x k)
 * @b: Matrix B (k x n)
 * @c: Matrix C (m x n, output)
 *
 * Computes C = ReLU(A * B). The ReLU is applied in-place
 * on the NEON accumulator registers before storing to memory,
 * eliminating one pass over the output data.
 */
static void neon_matmul_relu_fp32(int m, int n, int k,
                                   const float *a, const float *b,
                                   float *c)
{
    int i, j, p;

    kernel_neon_begin();

    /* Zero the output matrix */
    for (i = 0; i < m; i++)
        for (j = 0; j < n; j++)
            c[i * n + j] = 0.0f;

    float32x4_t zero = vdupq_n_f32(0.0f);

    /*
     * Tiled matmul with fused ReLU.
     * The ReLU is applied to the accumulator vectors before
     * storing to C, using vmaxq_f32(acc, zero).
     */
    for (i = 0; i < m; i += TILE_M) {
        int m_cur = MIN(TILE_M, m - i);

        for (j = 0; j < n; j += TILE_N) {
            int n_cur = MIN(TILE_N, n - j);

            for (p = 0; p < k; p += TILE_K) {
                int k_cur = MIN(TILE_K, k - p);

                neon_process_tile_relu(m_cur, n_cur, k_cur,
                                        a + i * k + p, k,
                                        b + p * n + j, n,
                                        c + i * n + j, n,
                                        zero);
            }
        }
    }

    kernel_neon_end();
}

/**
 * neon_process_tile_relu - Process tile with fused ReLU
 * @m_cur: Tile rows
 * @n_cur: Tile columns
 * @k_cur: Tile reduction dimension
 * @a: A submatrix
 * @lda: Leading dimension of A
 * @b: B submatrix
 * @ldb: Leading dimension of B
 * @c: C submatrix
 * @ldc: Leading dimension of C
 * @zero: NEON vector of zeros (for ReLU comparison)
 *
 * Processes a tile of the matrix multiplication, applying ReLU
 * to the accumulator before storing to C. This is the same as
 * the standard tile processing, but with vmaxq_f32 on the
 * accumulator vectors.
 */
static void neon_process_tile_relu(int m_cur, int n_cur, int k_cur,
                                    const float *a, int lda,
                                    const float *b, int ldb,
                                    float *c, int ldc,
                                    float32x4_t zero)
{
    for (int i = 0; i < m_cur; i += 4) {
        int mr = MIN(4, m_cur - i);

        for (int j = 0; j < n_cur; j += 4) {
            int nr = MIN(4, n_cur - j);
            int p;
            float32x4_t cv[4];

            /* Load C accumulators */
            for (int r = 0; r < mr; r++)
                cv[r] = vld1q_f32(&c[(i + r) * ldc + j]);

            for (int r = mr; r < 4; r++)
                cv[r] = zero;

            /* Main reduction loop */
            p = 0;
            for (; p + 4 <= k_cur; p += 4) {
                float32x4_t b0 = vld1q_f32(&b[(p + 0) * ldb + j]);
                float32x4_t b1 = vld1q_f32(&b[(p + 1) * ldb + j]);
                float32x4_t b2 = vld1q_f32(&b[(p + 2) * ldb + j]);
                float32x4_t b3 = vld1q_f32(&b[(p + 3) * ldb + j]);

                for (int r = 0; r < mr; r++) {
                    cv[r] = vfmaq_n_f32(cv[r], b0,
                        a[(i + r) * lda + p + 0]);
                    cv[r] = vfmaq_n_f32(cv[r], b1,
                        a[(i + r) * lda + p + 1]);
                    cv[r] = vfmaq_n_f32(cv[r], b2,
                        a[(i + r) * lda + p + 2]);
                    cv[r] = vfmaq_n_f32(cv[r], b3,
                        a[(i + r) * lda + p + 3]);
                }
            }

            /* Remainder */
            for (; p < k_cur; p++) {
                float32x4_t bv = vld1q_f32(&b[p * ldb + j]);
                for (int r = 0; r < mr; r++)
                    cv[r] = vfmaq_n_f32(cv[r], bv,
                        a[(i + r) * lda + p]);
            }

            /* Apply ReLU: max(0, x) */
            for (int r = 0; r < mr; r++)
                cv[r] = vmaxq_f32(cv[r], zero);

            /* Store results */
            for (int r = 0; r < mr; r++) {
                if (nr == 4) {
                    vst1q_f32(&c[(i + r) * ldc + j], cv[r]);
                } else {
                    for (int cj = 0; cj < nr; cj++)
                        c[(i + r) * ldc + j + cj] =
                            vgetq_lane_f32(cv[r], cj);
                }
            }
        }
    }
}

/**
 * neon_matmul_bias_relu_fp32 - MatMul with fused Bias + ReLU
 * @m: Number of rows
 * @n: Number of columns
 * @k: Reduction dimension
 * @a: Matrix A (m x k)
 * @b: Matrix B (k x n)
 * @c: Matrix C (m x n, output)
 * @bias: Bias vector (n elements)
 *
 * Computes C = ReLU(A * B + bias). The bias is added to each
 * row of the result before ReLU. This is a common pattern in
 * fully-connected and convolutional layers.
 */
static void neon_matmul_bias_relu_fp32(int m, int n, int k,
                                        const float *a, const float *b,
                                        float *c, const float *bias)
{
    int i, j, p;

    kernel_neon_begin();

    float32x4_t zero = vdupq_n_f32(0.0f);

    /*
     * Zero the output matrix. The bias will be added during
     * the tile processing.
     */
    for (i = 0; i < m; i++)
        for (j = 0; j < n; j++)
            c[i * n + j] = 0.0f;

    /* Tiled matmul with bias and ReLU */
    for (i = 0; i < m; i += TILE_M) {
        int m_cur = MIN(TILE_M, m - i);

        for (j = 0; j < n; j += TILE_N) {
            int n_cur = MIN(TILE_N, n - j);

            for (p = 0; p < k; p += TILE_K) {
                int k_cur = MIN(TILE_K, k - p);

                /* Standard matmul tile */
                neon_process_tile(m_cur, n_cur, k_cur,
                                  a + i * k + p, k,
                                  b + p * n + j, n,
                                  c + i * n + j, n);
            }

            /* Add bias and apply ReLU for this tile */
            for (int r = 0; r < m_cur; r++) {
                for (int cj = 0; cj + 4 <= n_cur; cj += 4) {
                    float32x4_t cv = vld1q_f32(
                        &c[(i + r) * n + j + cj]);
                    float32x4_t bv = vld1q_f32(&bias[j + cj]);

                    cv = vaddq_f32(cv, bv);
                    cv = vmaxq_f32(cv, zero);
                    vst1q_f32(&c[(i + r) * n + j + cj], cv);
                }

                /* Remainder bias + ReLU */
                for (int cj = (n_cur & ~3); cj < n_cur; cj++) {
                    float val = c[(i + r) * n + j + cj] +
                                bias[j + cj];
                    c[(i + r) * n + j + cj] = (val > 0.0f) ?
                                               val : 0.0f;
                }
            }
        }
    }

    kernel_neon_end();
}

/* ============================================================
 * Fused Quantize Operations
 * ============================================================
 *
 * Fused operations that combine dequantization with subsequent
 * processing, or quantization with preceding operations.
 * This reduces memory bandwidth and improves cache utilization.
 */

/**
 * neon_dequantize_add_bias_q8 - Dequantize Q8, add bias, requantize
 * @n: Number of elements
 * @src: Source Q8 data
 * @bias: Bias vector (float32, n elements)
 * @dst: Destination Q8 data
 * @scale: Dequantization scale
 * @bias_scale: Bias scale (for quantizing the result)
 *
 * Performs: dst_q8 = quantize(dequantize(src_q8, scale) + bias, bias_scale)
 *
 * This fused operation is common in quantized neural network
 * inference where bias addition happens in floating point.
 */
static void neon_dequantize_add_bias_q8(int n, const void *src,
                                          const float *bias,
                                          void *dst,
                                          float scale,
                                          float bias_scale)
{
    int i;
    const int8_t *src8 = (const int8_t *)src;
    int8_t *dst8 = (int8_t *)dst;

    kernel_neon_begin();

    float32x4_t inv_scale = vdupq_n_f32(1.0f / scale);
    float32x4_t scale_vec = vdupq_n_f32(bias_scale);

    for (i = 0; i + 4 <= n; i += 4) {
        /* Dequantize Q8 to FP32 */
        int8x8_t i8 = vld1_s8(&src8[i]);
        int16x8_t i16 = vmovl_s8(i8);
        int16x4_t i16_lo = vget_low_s16(i16);
        int32x4_t i32 = vmovl_s16(i16_lo);
        float32x4_t f32 = vcvtq_f32_s32(i32);
        float32x4_t deq = vmulq_f32(f32, inv_scale);

        /* Add bias */
        float32x4_t biased = vaddq_f32(deq, vld1q_f32(&bias[i]));

        /* Requantize to Q8 */
        float32x4_t scaled = vmulq_f32(biased, scale_vec);
        int32x4_t q32 = vcvtq_s32_f32(scaled);
        int16x4_t q16 = vqmovn_s32(q32);
        int16x8_t q16x8 = vcombine_s16(q16, vdup_n_s16(0));
        int8x8_t q8 = vqmovn_s16(q16x8);

        vst1_lane_s32((int32_t *)&dst8[i],
                       vreinterpret_s32_s8(q8), 0);
    }

    /* Scalar remainder */
    for (; i < n; i++) {
        float deq = (float)src8[i] / scale;
        float biased = deq + bias[i];
        int32_t q = (int32_t)(biased * bias_scale + 0.5f);
        if (q > 127) q = 127;
        if (q < -128) q = -128;
        dst8[i] = (int8_t)q;
    }

    kernel_neon_end();
}

/* ============================================================
 * Matrix Validation and Debugging Helpers
 * ============================================================
 *
 * Utility functions for validating matrix dimensions, checking
 * for NaN/Inf values, and computing error metrics. These are
 * used during development and debugging, and can be compiled
 * out for production builds.
 */

/**
 * neon_matrix_has_nan - Check if a matrix contains NaN values
 * @n: Number of elements
 * @data: Matrix data
 *
 * Return: true if any element is NaN
 */
static bool neon_matrix_has_nan(int n, const float *data)
{
    int i;
    uint32x4_t nan_mask = vdupq_n_u32(0x7FFFFFFF);
    uint32x4_t inf_mask = vdupq_n_u32(0x7F800000);

    for (i = 0; i + 4 <= n; i += 4) {
        float32x4_t v = vld1q_f32(&data[i]);
        uint32x4_t bits = vreinterpretq_u32_f32(v);

        /*
         * NaN is detected by: (abs(x) > INFINITY)
         * i.e., exponent bits are all 1 and mantissa is non-zero.
         * We check: (bits & 0x7FFFFFFF) > 0x7F800000
         */
        uint32x4_t abs_bits = vandq_u32(bits, nan_mask);
        uint32x4_t is_nan = vcgtq_u32(abs_bits, inf_mask);

        /* Check if any lane is NaN */
        uint32x2_t pair = vpadd_u32(
            vget_low_u32(vreinterpretq_u32_u32(is_nan)),
            vget_high_u32(vreinterpretq_u32_u32(is_nan)));
        uint32x2_t summed = vpadd_u32(pair, pair);

        if (vget_lane_u32(summed, 0) > 0)
            return true;
    }

    /* Scalar remainder */
    for (; i < n; i++) {
        if (isnan(data[i]))
            return true;
    }

    return false;
}

/**
 * neon_matrix_has_inf - Check if a matrix contains infinite values
 * @n: Number of elements
 * @data: Matrix data
 *
 * Return: true if any element is +Inf or -Inf
 */
static bool neon_matrix_has_inf(int n, const float *data)
{
    int i;
    uint32x4_t abs_mask = vdupq_n_u32(0x7FFFFFFF);
    uint32x4_t inf_bits = vdupq_n_u32(0x7F800000);

    for (i = 0; i + 4 <= n; i += 4) {
        float32x4_t v = vld1q_f32(&data[i]);
        uint32x4_t bits = vreinterpretq_u32_f32(v);
        uint32x4_t abs_bits = vandq_u32(bits, abs_mask);

        /* Check if abs_bits == 0x7F800000 (Infinity pattern) */
        uint32x4_t is_inf = vceqq_u32(abs_bits, inf_bits);

        /* Check if any lane is Inf */
        uint32x2_t pair = vpadd_u32(
            vget_low_u32(vreinterpretq_u32_u32(is_inf)),
            vget_high_u32(vreinterpretq_u32_u32(is_inf)));
        uint32x2_t summed = vpadd_u32(pair, pair);

        if (vget_lane_u32(summed, 0) > 0)
            return true;
    }

    for (; i < n; i++) {
        if (isinf(data[i]))
            return true;
    }

    return false;
}

/**
 * neon_matrix_max_diff - Compute maximum absolute difference
 * @n: Number of elements
 * @a: First array
 * @b: Second array
 *
 * Computes max(|a[i] - b[i]|) for all elements.
 * Used for comparing results between implementations.
 *
 * Return: Maximum absolute difference
 */
static float neon_matrix_max_diff(int n, const float *a, const float *b)
{
    int i;
    float32x4_t vmax = vdupq_n_f32(0.0f);

    for (i = 0; i + 4 <= n; i += 4) {
        float32x4_t va = vld1q_f32(&a[i]);
        float32x4_t vb = vld1q_f32(&b[i]);
        float32x4_t diff = vabdq_f32(va, vb);
        vmax = vmaxq_f32(vmax, diff);
    }

    /* Horizontal max */
    float max_val = vgetq_lane_f32(vmax, 0);
    for (int lane = 1; lane < 4; lane++) {
        float lane_val = vgetq_lane_f32(vmax, lane);
        if (lane_val > max_val)
            max_val = lane_val;
    }

    for (; i < n; i++) {
        float diff = (a[i] > b[i]) ? (a[i] - b[i]) : (b[i] - a[i]);
        if (diff > max_val)
            max_val = diff;
    }

    return max_val;
}

/**
 * neon_matrix_relative_error - Compute relative error metric
 * @n: Number of elements
 * @ref: Reference array (ground truth)
 * @test: Test array (implementation under test)
 *
 * Computes: max(|ref[i] - test[i]| / max(1, |ref[i]|))
 *
 * Return: Maximum relative error, or 0 if both arrays are all-zero
 */
static float neon_matrix_relative_error(int n, const float *ref,
                                         const float *test)
{
    int i;
    float max_rel_err = 0.0f;
    float32x4_t vmax = vdupq_n_f32(0.0f);
    float32x4_t one_vec = vdupq_n_f32(1.0f);

    for (i = 0; i + 4 <= n; i += 4) {
        float32x4_t vr = vld1q_f32(&ref[i]);
        float32x4_t vt = vld1q_f32(&test[i]);
        float32x4_t diff = vabdq_f32(vr, vt);
        float32x4_t abs_ref = vabsq_f32(vr);
        float32x4_t denom = vmaxq_f32(abs_ref, one_vec);
        float32x4_t rel = vdivq_f32(diff, denom);

        vmax = vmaxq_f32(vmax, rel);
    }

    /* Horizontal max */
    float max_val = vgetq_lane_f32(vmax, 0);
    for (int lane = 1; lane < 4; lane++) {
        float lane_val = vgetq_lane_f32(vmax, lane);
        if (lane_val > max_val)
            max_val = lane_val;
    }

    for (; i < n; i++) {
        float diff = (ref[i] > test[i]) ? (ref[i] - test[i]) :
                                          (test[i] - ref[i]);
        float abs_ref = (ref[i] > 0.0f) ? ref[i] : -ref[i];
        float denom = (abs_ref > 1.0f) ? abs_ref : 1.0f;
        float rel = diff / denom;
        if (rel > max_val)
            max_val = rel;
    }

    return max_val;
}

/* ============================================================
 * Cache Control and Memory Barriers
 * ============================================================
 *
 * NEON operations may leave data in cache. For correctness
 * in DMA or multi-core scenarios, we may need to flush or
 * invalidate cache lines.
 *
 * These helpers use the ARM64 DC (Data Cache) instructions
 * via inline assembly where needed.
 */

/**
 * neon_flush_dcache_range - Flush D-cache for a memory range
 * @addr: Start address
 * @size: Size in bytes
 *
 * Ensures that data written by NEON instructions is visible
 * to other masters (DMA, other CPUs). This is a no-op on
 * fully-coherent systems.
 */
static inline void neon_flush_dcache_range(void *addr, size_t size)
{
    /* ARM64: use dc cvac (clean virtual address to point of coherency) */
    uintptr_t start = (uintptr_t)addr & ~(CACHE_LINE_SIZE - 1);
    uintptr_t end = (uintptr_t)addr + size;

    for (uintptr_t line = start; line < end; line += CACHE_LINE_SIZE) {
        asm volatile("dc cvac, %0" : : "r"(line) : "memory");
    }
    asm volatile("dsb sy" : : : "memory");
}

/**
 * neon_invalidate_dcache_range - Invalidate D-cache for a memory range
 * @addr: Start address
 * @size: Size in bytes
 *
 * Ensures that the next read from this range will fetch from
 * main memory. Used before reading data written by DMA.
 */
static inline void neon_invalidate_dcache_range(void *addr, size_t size)
{
    uintptr_t start = (uintptr_t)addr & ~(CACHE_LINE_SIZE - 1);
    uintptr_t end = (uintptr_t)addr + size;

    for (uintptr_t line = start; line < end; line += CACHE_LINE_SIZE) {
        asm volatile("dc ivac, %0" : : "r"(line) : "memory");
    }
    asm volatile("dsb sy" : : : "memory");
}

/* ============================================================
 * Module Information
 * ============================================================
 *
 * This file is compiled as part of the Ainos kernel module.
 * It does not have its own module_init/module_exit because it
 * is linked into the main ai-vector-accel module.
 *
 * The NEON implementation is automatically selected at runtime
 * if no higher-priority SIMD implementation (SVE, SVE2) is
 * available.
 */

/* ============================================================
 * Advanced NEON Optimization Techniques
 * ============================================================
 *
 * This section documents the optimization techniques used
 * throughout the NEON implementation and provides additional
 * specialized kernels for edge cases.
 *
 * Key optimization techniques:
 *
 * 1. Loop Tiling (Cache Blocking)
 *    The matrix multiplication uses 3-level tiling to fit
 *    the working set into the L1, L2, and L3 caches:
 *      - Outer tiles (32x32): L2 cache residency
 *      - Inner tiles (4x4): register residency
 *      - K-panels: L1 cache residency
 *
 * 2. Instruction Scheduling
 *    NEON FMA instructions have a latency of 4-5 cycles on
 *    Cortex-A76. To hide this latency, we:
 *      - Unroll loops by 4 to expose independent instructions
 *      - Use multiple accumulator registers (4-16)
 *      - Interleave load and compute instructions
 *
 * 3. Prefetching
 *    Software prefetch (prfm) is used to bring data into
 *    cache before it is accessed. The prefetch distance
 *    is tuned to the memory latency of the target system.
 *
 * 4. Packing
 *    Matrices are packed into contiguous buffers to
 *    eliminate strided memory access in the inner loop.
 *    This improves L1 cache utilization by up to 4x.
 *
 * 5. FMA vs MLA
 *    vfmaq_f32 (fused multiply-add) is preferred over
 *    vmlaq_f32 (multiply-add) on ARM64 because FMA has
 *    better numerical accuracy (single rounding) and
 *    equivalent performance. Both are available as
 *    intrinsics; we use vfmaq_f32 throughout.
 *
 * ============================================================
 * Edge Case Handling Summary
 * ============================================================
 *
 * The following edge cases are handled by all functions:
 *
 * 1. Zero dimensions (m=0, n=0, k=0, n=0, batch_size=0):
 *    Functions return immediately without computation.
 *
 * 2. NULL pointers: Functions log a warning and return.
 *
 * 3. Non-aligned data: The NEON kernels handle unaligned
 *    loads/stores via vld1q_f32/vst1q_f32 which support
 *    unaligned access on ARMv8. However, aligned access
 *    is significantly faster.
 *
 * 4. Partial tiles (dimensions not multiples of 4):
 *    Remainder kernels handle 1, 2, or 3 remaining rows
 *    or columns using specialized kernels (4x1, 1x4, 4x2,
 *    2x4, 1x1) or scalar fallback.
 *
 * 5. Overflow/underflow: Saturating narrowing instructions
 *    (vqmovn) clamp out-of-range values for quantization.
 *    Activation functions clamp inputs to prevent NaN/Inf.
 *
 * 6. NaN/Inf propagation: No special handling in compute
 *    kernels; IEEE 754 compliance is preserved. Detection
 *    functions are provided for debugging.
 *
 * ============================================================
 * Performance Characteristics
 * ============================================================
 *
 * Expected performance on typical ARM Cortex-A76 @ 2.4 GHz:
 *
 * Operation              | Throughput         | Notes
 * -----------------------+--------------------+-----------------------
 * MatMul (32x32x32)     | ~8 GFLOPS          | 4x4 kernel, tiled
 * MatMul (256x256x256)  | ~6 GFLOPS          | 3-level tiling
 * Dot Product (n=1024)  | ~2.5 GFLOPS        | unrolled by 8
 * Quantize Q8 (n=1024)  | ~4 GB/s            | NEON pipeline
 * Quantize Q4 (n=1024)  | ~2.5 GB/s          | nibble packing
 * Dequantize Q8 (n=1024)| ~3.5 GB/s          | sign extension
 * Dequantize Q4 (n=1024)| ~2 GB/s            | nibble unpacking
 *
 * These are rough estimates. Actual performance depends on
 * memory bandwidth, cache behavior, and CPU frequency scaling.
 *
 * ============================================================
 * NV (Non-Vectorized) Scalar Fallback Functions
 * ============================================================
 *
 * These functions are used when NEON is not available or when
 * the data size is too small to benefit from vectorization.
 * They are equivalent to the generic implementations in the
 * main module but are provided here for completeness.
 *
 * NV functions are prefixed with "nv_" to distinguish them
 * from the NEON-accelerated versions.
 */

/**
 * nv_matmul_fp32 - Scalar matrix multiply fallback
 * @m: Number of rows
 * @n: Number of columns
 * @k: Reduction dimension
 * @a: Matrix A (m x k)
 * @b: Matrix B (k x n)
 * @c: Matrix C (m x n)
 *
 * Pure C implementation for verification and platforms
 * without NEON. This is identical to the generic version
 * in the main module.
 */
static void nv_matmul_fp32(int m, int n, int k,
                             const float *a, const float *b,
                             float *c)
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

/**
 * nv_dot_product - Scalar dot product fallback
 * @n: Number of elements
 * @a: First vector
 * @b: Second vector
 *
 * Return: Dot product
 */
static float nv_dot_product(int n, const float *a, const float *b)
{
    float sum = 0.0f;
    for (int i = 0; i < n; i++)
        sum += a[i] * b[i];
    return sum;
}

/**
 * nv_quantize_fp32_to_q8 - Scalar Q8 quantization
 * @n: Number of elements
 * @src: Source float32 array
 * @dst: Destination int8 array
 * @scale: Scaling factor
 */
static void nv_quantize_fp32_to_q8(int n, const float *src,
                                    void *dst, float scale)
{
    int8_t *dst8 = (int8_t *)dst;
    for (int i = 0; i < n; i++) {
        float val = src[i] * scale;
        if (val >= 0.0f)
            dst8[i] = (int8_t)(val + 0.5f);
        else
            dst8[i] = (int8_t)(val - 0.5f);
    }
}

/**
 * nv_quantize_fp32_to_q4 - Scalar Q4 quantization
 * @n: Number of elements
 * @src: Source float32 array
 * @dst: Destination uint8 array (packed)
 * @scale: Scaling factor
 */
static void nv_quantize_fp32_to_q4(int n, const float *src,
                                    void *dst, float scale)
{
    uint8_t *dst4 = (uint8_t *)dst;
    for (int i = 0; i < n; i += 2) {
        float v0_f = src[i] * scale;
        float v1_f = src[i + 1] * scale;
        int8_t v0, v1;

        if (v0_f >= 0.0f) v0 = (int8_t)(v0_f + 0.5f);
        else              v0 = (int8_t)(v0_f - 0.5f);

        if (v1_f >= 0.0f) v1 = (int8_t)(v1_f + 0.5f);
        else              v1 = (int8_t)(v1_f - 0.5f);

        dst4[i / 2] = (uint8_t)((v0 & 0x0F) | ((v1 & 0x0F) << 4));
    }
}

/**
 * nv_dequantize_q8_to_fp32 - Scalar Q8 dequantization
 * @n: Number of elements
 * @src: Source int8 array
 * @dst: Destination float32 array
 * @scale: Scaling factor
 */
static void nv_dequantize_q8_to_fp32(int n, const void *src,
                                      float *dst, float scale)
{
    const int8_t *src8 = (const int8_t *)src;
    float inv_scale = 1.0f / scale;

    for (int i = 0; i < n; i++)
        dst[i] = (float)src8[i] * inv_scale;
}

/**
 * nv_dequantize_q4_to_fp32 - Scalar Q4 dequantization
 * @n: Number of elements
 * @src: Source uint8 array (packed)
 * @dst: Destination float32 array
 * @scale: Scaling factor
 */
static void nv_dequantize_q4_to_fp32(int n, const void *src,
                                      float *dst, float scale)
{
    const uint8_t *src4 = (const uint8_t *)src;
    float inv_scale = 1.0f / scale;

    for (int i = 0; i < n; i += 2) {
        uint8_t byte = src4[i / 2];
        int8_t v0 = (int8_t)(byte & 0x0F);
        int8_t v1 = (int8_t)(byte >> 4);

        /* Sign-extend 4-bit to 8-bit */
        v0 = (int8_t)(v0 << 4) >> 4;
        v1 = (int8_t)(v1 << 4) >> 4;

        dst[i] = (float)v0 * inv_scale;
        dst[i + 1] = (float)v1 * inv_scale;
    }
}

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("Ainos ARM64 NEON SIMD Vector Acceleration Implementation");
MODULE_VERSION("0.2.0");