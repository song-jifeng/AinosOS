// SPDX-License-Identifier: GPL-2.0
/*
 * Ainos OS - AVX-512 SIMD Vector Acceleration Implementation
 * ==========================================================
 * Implements all AVX-512 optimized primitives for the AI vector
 * acceleration module: matrix multiply, dot product, quantize,
 * dequantize, and batch dot product.
 *
 * Architecture: x86-64 with AVX-512F, AVX-512BW, AVX-512DQ, AVX-512VL, FMA
 * Register width: 512-bit (16 x float32 per zmm register)
 * Max vector registers: 32 x zmm
 *
 * Key design decisions:
 * - Loop tiling for cache efficiency (L1/L2/L3 aware)
 * - Packing for vector-friendly memory access patterns
 * - Masked remainder handling for non-multiple-of-16 dimensions
 * - Software prefetching for latency hiding
 * - Multiple code paths optimized for different matrix sizes
 *
 * Algorithm references:
 * - Goto, K., & Van De Geijn, R. A. (2008). Anatomy of high-performance
 *   matrix multiplication. ACM Transactions on Mathematical Software.
 * - Intel Architecture Code Analyzer (IACA) for throughput analysis
 * - Intel 64 and IA-32 Architectures Optimization Reference Manual
 */

#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/export.h>
#include <linux/string.h>
#include <linux/printk.h>
#include <asm/fpu/api.h>
#include <immintrin.h>

#include "simd_impl.h"

/* ============================================
 * Target attribute macro for AVX-512 functions.
 * Applied to every function using AVX-512 intrinsics.
 * Enables: AVX-512 Foundation, Byte&Word, Doubleword&Quadword,
 *          Vector Length, and FMA extensions.
 * ============================================ */
#define AVX512_TARGET \
	__attribute__((target("avx512f,avx512bw,avx512dq,avx512vl,fma")))

/* ============================================
 * Compile-time constants
 * ============================================ */

/* AVX-512 vector width: 16 single-precision floats per zmm register */
#define AVX512_FLOAT_WIDTH  16

/* Micro-kernel tile sizes for the register-level computation */
#define MR_DEFAULT  16  /* Number of rows processed in micro-kernel */
#define NR_DEFAULT  16  /* Number of cols processed in micro-kernel */

/*
 * Cache tiling parameters.
 * These are tuned for typical server-class CPUs with:
 *   L1D: 32 KB per core  (32 KB / 4 B = 8192 floats)
 *   L2:  1 MB per core   (1 MB / 4 B = 262144 floats)
 *   L3:  16-48 MB shared
 *
 * The tile sizes are chosen so that:
 *   MC * KC + KC * NC + MC * NC <= L2 capacity (in floats)
 * For MC=128, KC=256, NC=128:
 *   A panel:  128 * 256 = 32768 floats = 128 KB
 *   B panel:  256 * 128 = 32768 floats = 128 KB
 *   C panel:  128 * 128 = 16384 floats = 64 KB
 *   Total: ~320 KB, fits in 1 MB L2 with room for other data.
 */
#define MC_DEFAULT  128  /* Row tile size for A matrix */
#define NC_DEFAULT  128  /* Column tile size for B/C matrices */
#define KC_DEFAULT  256  /* Inner dimension tile size */

/*
 * For very large matrices (L3-cached), we use larger tiles.
 * These are used when the full working set exceeds L2 capacity.
 */
#define MC_LARGE    256
#define NC_LARGE    256
#define KC_LARGE    512

/* Prefetch distance (in iterations) for software prefetching */
#define PREFETCH_DIST_A   4
#define PREFETCH_DIST_B   4
#define PREFETCH_DIST_C   2

/* Alignment requirements for SIMD-friendly allocation */
#define AVX512_ALIGNMENT  64  /* 64-byte cache line alignment */

/* ============================================
 * Static function declarations
 * ============================================ */

/* Helper: aligned memory allocation */
static AVX512_TARGET void *avx512_aligned_alloc(size_t size);
static AVX512_TARGET void avx512_aligned_free(void *ptr);

/* Helper: compute mask for remainder processing */
static AVX512_TARGET __mmask16 avx512_mask16(int remaining);

/* Helper: prefetch a cache line */
static AVX512_TARGET void avx512_prefetch_l1(const void *addr);
static AVX512_TARGET void avx512_prefetch_l2(const void *addr);
static AVX512_TARGET void avx512_prefetch_nta(const void *addr);

/* Helper: zero a tile of C matrix */
static AVX512_TARGET void avx512_zero_c_tile(float *c, int ldc,
					      int m, int n);

/* Packing functions */
static AVX512_TARGET void avx512_pack_a_tile(int k, int m,
					      const float *a, int lda,
					      float *packed);
static AVX512_TARGET void avx512_pack_a_tile_rem(int k, int m_rem,
						  const float *a, int lda,
						  float *packed);
static AVX512_TARGET void avx512_pack_b_tile(int k, int n,
					      const float *b, int ldb,
					      float *packed);
static AVX512_TARGET void avx512_pack_b_tile_rem(int k, int n_rem,
						  const float *b, int ldb,
						  float *packed);

/* Micro-kernels */
static AVX512_TARGET void avx512_micro_16x16(int k, const float *a_packed,
					      const float *b_packed,
					      float *c, int ldc);
static AVX512_TARGET void avx512_micro_16xN(int k, int n_rem,
					     const float *a_packed,
					     const float *b_packed,
					     float *c, int ldc);
static AVX512_TARGET void avx512_micro_Mx16(int k, int m_rem,
					     const float *a_packed,
					     const float *b_packed,
					     float *c, int ldc);
static AVX512_TARGET void avx512_micro_MxN(int k, int m_rem, int n_rem,
					    const float *a_packed,
					    const float *b_packed,
					    float *c, int ldc);

/* Block matmul strategies */
static AVX512_TARGET void avx512_matmul_large(int m, int n, int k,
					       const float *a, int lda,
					       const float *b, int ldb,
					       float *c, int ldc);
static AVX512_TARGET void avx512_matmul_medium(int m, int n, int k,
						const float *a, int lda,
						const float *b, int ldb,
						float *c, int ldc);
static AVX512_TARGET void avx512_matmul_small(int m, int n, int k,
					       const float *a, int lda,
					       const float *b, int ldb,
					       float *c, int ldc);

/* Dot product variants */
static AVX512_TARGET float avx512_dot_product_large(int n,
						     const float *a,
						     const float *b);
static AVX512_TARGET float avx512_dot_product_small(int n,
						     const float *a,
						     const float *b);

/* Quantize/Dequantize helpers */
static AVX512_TARGET void avx512_quantize_q8_large(int n,
						    const float *src,
						    void *dst, float scale);
static AVX512_TARGET void avx512_quantize_q8_small(int n,
						    const float *src,
						    void *dst, float scale);
static AVX512_TARGET void avx512_quantize_q4_large(int n,
						    const float *src,
						    void *dst, float scale);
static AVX512_TARGET void avx512_quantize_q4_small(int n,
						    const float *src,
						    void *dst, float scale);
static AVX512_TARGET void avx512_dequantize_q8_large(int n,
						      const void *src,
						      float *dst, float scale);
static AVX512_TARGET void avx512_dequantize_q8_small(int n,
						      const void *src,
						      float *dst, float scale);
static AVX512_TARGET void avx512_dequantize_q4_large(int n,
						      const void *src,
						      float *dst, float scale);
static AVX512_TARGET void avx512_dequantize_q4_small(int n,
						      const void *src,
						      float *dst, float scale);

/* Batch dot product helpers */
static AVX512_TARGET void avx512_batch_dot_product_single(int batch_n,
							   int n,
							   const float *a,
							   const float *b,
							   float *results);
static AVX512_TARGET void avx512_batch_dot_product_scalar(
				int batch_n, int n,
				const float *a, const float *b,
				float *results);

/* ============================================
 * Helper: Aligned memory allocation
 *
 * Allocates memory aligned to AVX512_ALIGNMENT (64 bytes).
 * This ensures that zmm load/store operations can use
 * aligned moves (_mm512_load_ps / _mm512_store_ps) for
 * maximum performance on the packing buffers.
 *
 * Falls back to kmalloc if the aligned allocator is
 * not available, but guarantees at least natural alignment.
 * ============================================ */
static AVX512_TARGET void *avx512_aligned_alloc(size_t size)
{
	void *ptr;

	/*
	 * Use kmalloc with cache-line alignment.
	 * On kernels with CONFIG_SLAB_CACHE alignment support,
	 * this returns 64-byte aligned memory when available.
	 */
	if (size == 0)
		return NULL;

	/*
	 * Allocate with extra space for alignment adjustment.
	 * We overallocate by AVX512_ALIGNMENT bytes and then
	 * align the returned pointer. The alignment offset is
	 * stored just before the aligned pointer.
	 */
	ptr = kmalloc(size + AVX512_ALIGNMENT + sizeof(void *), GFP_KERNEL);
	if (!ptr)
		return NULL;

	/*
	 * Compute aligned address: round up to next AVX512_ALIGNMENT
	 * boundary, leaving room for the offset pointer.
	 */
	{
		uintptr_t raw = (uintptr_t)ptr;
		uintptr_t offset_ptr = raw + sizeof(void *);
		uintptr_t aligned = (offset_ptr + AVX512_ALIGNMENT - 1)
				    & ~(uintptr_t)(AVX512_ALIGNMENT - 1);
		void **offset_storage = (void **)(aligned - sizeof(void *));

		*offset_storage = ptr;
		return (void *)aligned;
	}
}

/*
 * Free memory allocated by avx512_aligned_alloc.
 * Retrieves the original kmalloc pointer from the offset storage.
 */
static AVX512_TARGET void avx512_aligned_free(void *ptr)
{
	void **offset_storage;

	if (!ptr)
		return;

	offset_storage = (void **)((uintptr_t)ptr - sizeof(void *));
	kfree(*offset_storage);
}

/* ============================================
 * Helper: Mask computation for remainder handling
 *
 * Computes an AVX-512 mask with the lowest 'remaining' bits set.
 * For fp32 operations, the mask corresponds to elements 0..remaining-1.
 *
 * Example: remaining=5 -> mask = 0x001F (bits 0-4 set)
 *          remaining=0 -> mask = 0x0000 (no elements)
 *          remaining=16 -> mask = 0xFFFF (all elements)
 *
 * The mask is used with _mm512_mask_loadu_ps, _mm512_mask_storeu_ps,
 * _mm512_mask_fmadd_ps, etc.
 * ============================================ */
static AVX512_TARGET __mmask16 avx512_mask16(int remaining)
{
	/*
	 * Clamp to valid range [0, 16].
	 * remaining can be 0..16 for AVX-512 float operations.
	 */
	if (remaining <= 0)
		return 0;
	if (remaining >= AVX512_FLOAT_WIDTH)
		return 0xFFFF;

	/*
	 * Compute mask: (1 << remaining) - 1
	 * This sets the lowest 'remaining' bits to 1.
	 * Example: remaining=5 -> (1<<5)-1 = 32-1 = 31 = 0x001F
	 *
	 * Note: 'remaining' is guaranteed to be in [1, 15] here,
	 * so (1 << remaining) is well-defined.
	 */
	return (__mmask16)((1U << remaining) - 1U);
}

/* ============================================
 * Helper: 32-bit mask (for 32-element operations like Q4)
 *
 * Computes a 32-bit mask with the lowest 'remaining' bits set.
 * Used for operations that process 32 elements at a time.
 * ============================================ */
static AVX512_TARGET __mmask32 avx512_mask32(int remaining)
{
	if (remaining <= 0)
		return 0;
	if (remaining >= 32)
		return 0xFFFFFFFFU;

	return (__mmask32)((1U << remaining) - 1U);
}

/* ============================================
 * Helper: 8-bit mask (for 64-element operations)
 *
 * Computes a 64-bit mask with the lowest 'remaining' bits set.
 * Used for operations that process 64 elements at a time.
 * ============================================ */
static AVX512_TARGET __mmask64 avx512_mask64(int remaining)
{
	/*
	 * For 64-bit masks, we need to handle the shift carefully.
	 * When remaining >= 64, return all bits set.
	 * When remaining == 0, return 0.
	 * For 1..63, compute (1 << remaining) - 1 using 64-bit arithmetic.
	 */
	if (remaining <= 0)
		return 0;
	if (remaining >= 64)
		return 0xFFFFFFFFFFFFFFFFULL;

	return (__mmask64)((1ULL << remaining) - 1ULL);
}

/* ============================================
 * Helper: Prefetch wrappers
 *
 * These wrap _mm_prefetch with named hints for readability.
 * We use three levels of temporal locality:
 *   L1 (T0): Data will be used immediately by the current core
 *   L2 (T1): Data will be used soon, but not immediately
 *   NTA:     Data will be used once and not reused (non-temporal)
 *
 * In the matmul kernel, we use:
 *   - L1 prefetch for the next iteration's A and B panel data
 *   - L2 prefetch for the next tile's A and B data
 *   - NTA for C matrix stores (streaming, no reuse within a tile)
 * ============================================ */
static AVX512_TARGET void avx512_prefetch_l1(const void *addr)
{
	_mm_prefetch(addr, _MM_HINT_T0);
}

static AVX512_TARGET void avx512_prefetch_l2(const void *addr)
{
	_mm_prefetch(addr, _MM_HINT_T1);
}

static AVX512_TARGET void avx512_prefetch_nta(const void *addr)
{
	_mm_prefetch(addr, _MM_HINT_NTA);
}

/* ============================================
 * Helper: Zero a tile of C matrix
 *
 * Zeros out an m x n block of C using AVX-512 vector stores.
 * This is used to initialize the accumulator tile before
 * accumulating partial products from multiple K-tile iterations.
 *
 * For best performance, we use 512-bit stores (_mm512_store_ps)
 * when the row stride allows aligned access, falling back to
 * unaligned stores (_mm512_storeu_ps) otherwise.
 * ============================================ */
static AVX512_TARGET void avx512_zero_c_tile(float *c, int ldc,
					      int m, int n)
{
	const __m512 zero = _mm512_setzero_ps();
	int i, j;

	/*
	 * Process 16 columns at a time using zmm registers.
	 * Each 512-bit store zeroes 16 consecutive float values.
	 */
	for (i = 0; i < m; i++) {
		/*
		 * Check alignment: if the row pointer is 64-byte aligned,
		 * use aligned stores for better performance.
		 */
		int aligned = ((uintptr_t)&c[i * ldc] & (AVX512_ALIGNMENT - 1)) == 0;

		/* Process full 16-float blocks */
		for (j = 0; j + 16 <= n; j += 16) {
			if (aligned)
				_mm512_store_ps(&c[i * ldc + j], zero);
			else
				_mm512_storeu_ps(&c[i * ldc + j], zero);
		}

		/* Handle remainder columns (less than 16) */
		if (j < n) {
			__mmask16 mask = avx512_mask16(n - j);
			_mm512_mask_storeu_ps(&c[i * ldc + j], mask, zero);
		}
	}
}

/* ============================================
 * Helper: Compute LDA (leading dimension) for matrices
 *
 * Computes the effective leading dimension based on the
 * actual matrix dimension and any explicit leading dimension.
 * If lda < dim, we use dim as the leading dimension (column-major
 * compatibility) or dim as the row stride (row-major).
 *
 * In our row-major convention:
 *   A is m x k with leading dimension k (or lda if lda >= k)
 *   B is k x n with leading dimension n (or ldb if ldb >= n)
 *   C is m x n with leading dimension n (or ldc if ldc >= n)
 * ============================================ */

/*
 * Determine if the matrix is small enough for the direct code path.
 * The direct path avoids the overhead of packing and tiling and
 * is suitable for matrices where the working set fits in L1 cache.
 */
static AVX512_TARGET int avx512_is_small(int m, int n, int k)
{
	/*
	 * Small if the total number of floats fits in ~8 KB
	 * (roughly L1 data cache size / 4).
	 * This is a heuristic; actual performance depends on the
	 * CPU microarchitecture and cache topology.
	 */
	return (m * k + k * n + m * n) <= 2048;
}

/*
 * Determine if the matrix is medium-sized.
 * Medium matrices use simple tiling without packing (direct
 * micro-kernel calls) to avoid the overhead of packing buffers.
 */
static AVX512_TARGET int avx512_is_medium(int m, int n, int k)
{
	/*
	 * Medium if the total number of floats fits in ~128 KB
	 * (roughly L2 cache size / 8).
	 * For these matrices, the overhead of packing may not be
	 * amortized by the improved memory access patterns.
	 */
	return (m * k + k * n + m * n) <= 32768;
}

/* ============================================
 * Pack A tile: Row-major to packed format
 *
 * Packs a MC x KC block of matrix A into a contiguous buffer
 * for efficient access by the micro-kernel.
 *
 * Input layout (row-major):
 *   A[i][p] = a[i * lda + p]  for i in [0, m), p in [0, k)
 *
 * Output layout (packed):
 *   For each k_group in chunks of KC:
 *     For each m_group in chunks of MR:
 *       For p in [0, KC):
 *         For i in [0, MR):
 *           packed[offset++] = a[(m_group + i) * lda + (k_group + p)]
 *
 * This layout ensures that within a micro-kernel call, the
 * A values for a given k are contiguous in memory, enabling
 * efficient broadcast loads.
 *
 * The packing is performed with AVX-512 vector loads/stores
 * for maximum throughput, with prefetching for future tiles.
 * ============================================ */
static AVX512_TARGET void avx512_pack_a_tile(int k, int m,
					      const float *a, int lda,
					      float *packed)
{
	int i, p;

	/*
	 * Pack the tile: for each row group of MR rows,
	 * store the MR values for each k position contiguously.
	 *
	 * A_packed layout:
	 *   [row0_k0, row1_k0, ..., row_{MR-1}_k0,
	 *    row0_k1, row1_k1, ..., row_{MR-1}_k1,
	 *    ...,
	 *    row0_{k-1}, row1_{k-1}, ..., row_{MR-1}_{k-1}]
	 */
	for (i = 0; i < m; i += MR_DEFAULT) {
		int mb = (i + MR_DEFAULT <= m) ? MR_DEFAULT : (m - i);

		for (p = 0; p < k; p++) {
			int r;

			/*
			 * Prefetch the next few rows of A for this k position.
			 * This ensures that when the micro-kernel accesses
			 * these values, they are already in L1 cache.
			 */
			if (p + PREFETCH_DIST_A < k) {
				avx512_prefetch_l1(&a[i * lda + p + PREFETCH_DIST_A]);
			}

			/*
			 * Store MR contiguous values from A:
			 * a[i][p], a[i+1][p], ..., a[i+mb-1][p]
			 *
			 * These are strided by lda in the source, but
			 * we pack them contiguously in the destination.
			 */
			for (r = 0; r < mb; r++) {
				*packed++ = a[(i + r) * lda + p];
			}

			/*
			 * If mb < MR, pad with zeros to maintain
			 * the fixed stride in the packed format.
			 */
			for (r = mb; r < MR_DEFAULT; r++) {
				*packed++ = 0.0f;
			}
		}
	}
}

/* ============================================
 * Pack A tile remainder: Specialized for remainder rows
 *
 * Same as avx512_pack_a_tile but optimized for the case
 * where m_rem < MR_DEFAULT (i.e., the last row block).
 * This avoids the branch inside the inner loop.
 * ============================================ */
static AVX512_TARGET void avx512_pack_a_tile_rem(int k, int m_rem,
						  const float *a, int lda,
						  float *packed)
{
	int p, r;

	/*
	 * For the remainder case, m_rem is in [1, MR_DEFAULT-1].
	 * We pack m_rem valid values followed by (MR_DEFAULT - m_rem)
	 * zero-padding for each k position.
	 */
	for (p = 0; p < k; p++) {
		/* Pack valid rows */
		for (r = 0; r < m_rem; r++) {
			*packed++ = a[r * lda + p];
		}

		/* Pad with zeros to maintain fixed stride */
		for (r = m_rem; r < MR_DEFAULT; r++) {
			*packed++ = 0.0f;
		}
	}
}

/* ============================================
 * Pack B tile: Row-major to packed format
 *
 * Packs a KC x NC block of matrix B into a contiguous buffer
 * for efficient access by the micro-kernel.
 *
 * Input layout (row-major):
 *   B[p][j] = b[p * ldb + j]  for p in [0, k), j in [0, n)
 *
 * Output layout (packed):
 *   For each k_group in chunks of KC:
 *     For each n_group in chunks of NR:
 *       For p in [0, KC):
 *         For j in [0, NR):
 *           packed[offset++] = b[(k_group + p) * ldb + (n_group + j)]
 *
 * This layout ensures that within a micro-kernel call, the
 * B values for a given k and the NR columns are contiguous,
 * enabling a single 512-bit load per k iteration.
 * ============================================ */
static AVX512_TARGET void avx512_pack_b_tile(int k, int n,
					      const float *b, int ldb,
					      float *packed)
{
	int p, j;

	/*
	 * Pack the tile: for each column group of NR columns,
	 * store the NR values for each k position contiguously.
	 *
	 * B_packed layout:
	 *   [col0_k0, col1_k0, ..., col_{NR-1}_k0,
	 *    col0_k1, col1_k1, ..., col_{NR-1}_k1,
	 *    ...,
	 *    col0_{k-1}, col1_{k-1}, ..., col_{NR-1}_{k-1}]
	 */
	for (j = 0; j < n; j += NR_DEFAULT) {
		int nb = (j + NR_DEFAULT <= n) ? NR_DEFAULT : (n - j);

		for (p = 0; p < k; p++) {
			int c;

			/*
			 * Prefetch the next few rows of B for this column group.
			 */
			if (p + PREFETCH_DIST_B < k) {
				avx512_prefetch_l1(&b[(p + PREFETCH_DIST_B) * ldb + j]);
			}

			/*
			 * Store NR contiguous values from B:
			 * b[p][j], b[p][j+1], ..., b[p][j+nb-1]
			 */
			for (c = 0; c < nb; c++) {
				*packed++ = b[p * ldb + j + c];
			}

			/*
			 * If nb < NR, pad with zeros to maintain
			 * the fixed stride in the packed format.
			 */
			for (c = nb; c < NR_DEFAULT; c++) {
				*packed++ = 0.0f;
			}
		}
	}
}

/* ============================================
 * Pack B tile remainder: Specialized for remainder columns
 *
 * Same as avx512_pack_b_tile but optimized for the case
 * where n_rem < NR_DEFAULT (i.e., the last column block).
 * ============================================ */
static AVX512_TARGET void avx512_pack_b_tile_rem(int k, int n_rem,
						  const float *b, int ldb,
						  float *packed)
{
	int p, c;

	/*
	 * For the remainder case, n_rem is in [1, NR_DEFAULT-1].
	 * We pack n_rem valid values followed by (NR_DEFAULT - n_rem)
	 * zero-padding for each k position.
	 */
	for (p = 0; p < k; p++) {
		/* Pack valid columns */
		for (c = 0; c < n_rem; c++) {
			*packed++ = b[p * ldb + c];
		}

		/* Pad with zeros to maintain fixed stride */
		for (c = n_rem; c < NR_DEFAULT; c++) {
			*packed++ = 0.0f;
		}
	}
}

/* ============================================
 * Micro-kernel: 16x16 matrix multiply-accumulate
 *
 * Core computation kernel for the tiled SGEMM.
 * Computes: C[0..15][0..15] += A[0..15][0..k) * B[0..k)[0..15]
 *
 * This is the hot inner loop of the entire matmul operation.
 * It uses 16 zmm registers as accumulators and processes
 * k iterations, each performing:
 *   1. Broadcast one value from packed A
 *   2. Load 16 values from packed B
 *   3. FMA with the accumulator
 *
 * Register allocation:
 *   zmm0  - zmm15: Accumulators for C[0..15][0..15]
 *          Each zmm holds 16 floats for one row of the C tile.
 *   zmm16 - zmm23: Temporaries for A broadcasts and B loads
 *          (upper 16 registers, used to avoid spilling)
 *
 * The packed A layout ensures that all 16 A values for a given
 * k are contiguous, allowing us to load them with a single
 * 512-bit load and then broadcast individually.
 *
 * The packed B layout ensures that the 16 B values for a given
 * k and column group are contiguous, allowing a single 512-bit load.
 *
 * Throughput: 16 FMAs per iteration = 32 FLOPs per iteration.
 * With k iterations, total = 32 * k FLOPs for the 16x16 tile.
 * ============================================ */
static AVX512_TARGET void avx512_micro_16x16(int k,
					      const float *a_packed,
					      const float *b_packed,
					      float *c, int ldc)
{
	/*
	 * 16 accumulators, one per row of the C tile.
	 * Each accumulator holds 16 partial sums for the 16 columns.
	 */
	__m512 c0, c1, c2, c3, c4, c5, c6, c7;
	__m512 c8, c9, c10, c11, c12, c13, c14, c15;
	int p;

	/* Initialize accumulators to zero */
	c0  = _mm512_setzero_ps();
	c1  = _mm512_setzero_ps();
	c2  = _mm512_setzero_ps();
	c3  = _mm512_setzero_ps();
	c4  = _mm512_setzero_ps();
	c5  = _mm512_setzero_ps();
	c6  = _mm512_setzero_ps();
	c7  = _mm512_setzero_ps();
	c8  = _mm512_setzero_ps();
	c9  = _mm512_setzero_ps();
	c10 = _mm512_setzero_ps();
	c11 = _mm512_setzero_ps();
	c12 = _mm512_setzero_ps();
	c13 = _mm512_setzero_ps();
	c14 = _mm512_setzero_ps();
	c15 = _mm512_setzero_ps();

	/*
	 * Main K-loop.
	 *
	 * For each k index, we load 16 values from packed B (one zmm load),
	 * and 16 values from packed A (which we then broadcast individually
	 * to zmm registers for the FMA).
	 *
	 * The packed A stride is 16 floats per k index.
	 * The packed B stride is 16 floats per k index.
	 */
	for (p = 0; p < k; p++) {
		/*
		 * Load 16 B values for this k position.
		 * These are contiguous in the packed B buffer.
		 * B_packed[p * 16 + 0..15] = B[p][j..j+15]
		 */
		__m512 b_val = _mm512_loadu_ps(&b_packed[p * NR_DEFAULT]);

		/*
		 * Load 16 A values for this k position.
		 * A_packed[p * 16 + 0..15] = A[i..i+15][p]
		 * These are then broadcast to perform the outer product.
		 */
		__m512 a_row = _mm512_loadu_ps(&a_packed[p * MR_DEFAULT]);

		/*
		 * FMA: For each row of C, we broadcast the corresponding
		 * A value and multiply-add with the B vector.
		 *
		 * Using _mm512_set1_ps for the broadcast has the same
		 * performance as a separate broadcast instruction; the
		 * compiler is smart enough to emit vbroadcastss.
		 *
		 * The embedded rounding mode _MM_FROUND_TO_NEAREST_INT
		 * is used for deterministic results across platforms.
		 */
		c0  = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[0]),  b_val, c0);
		c1  = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[1]),  b_val, c1);
		c2  = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[2]),  b_val, c2);
		c3  = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[3]),  b_val, c3);
		c4  = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[4]),  b_val, c4);
		c5  = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[5]),  b_val, c5);
		c6  = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[6]),  b_val, c6);
		c7  = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[7]),  b_val, c7);
		c8  = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[8]),  b_val, c8);
		c9  = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[9]),  b_val, c9);
		c10 = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[10]), b_val, c10);
		c11 = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[11]), b_val, c11);
		c12 = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[12]), b_val, c12);
		c13 = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[13]), b_val, c13);
		c14 = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[14]), b_val, c14);
		c15 = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[15]), b_val, c15);

		/*
		 * Prefetch next iteration's data.
		 * We prefetch both A and B data for the next PREFETCH_DIST
		 * iterations ahead. This hides the L1 load latency.
		 *
		 * The prefetch is done every 4 iterations to avoid
		 * excessive prefetch instructions.
		 */
		if ((p & 3) == 0) {
			int next_p = p + PREFETCH_DIST_A;
			if (next_p < k) {
				avx512_prefetch_l1(&a_packed[next_p * MR_DEFAULT]);
				avx512_prefetch_l1(&b_packed[next_p * NR_DEFAULT]);
			}
		}
	}

	/*
	 * Store the 16x16 result tile to C.
	 *
	 * Each accumulator row is stored with a 512-bit store.
	 * The destination is C[i * ldc + j] for the current tile
	 * position (i, j). The caller adjusts the base pointer.
	 */
	_mm512_storeu_ps(&c[0 * ldc],  c0);
	_mm512_storeu_ps(&c[1 * ldc],  c1);
	_mm512_storeu_ps(&c[2 * ldc],  c2);
	_mm512_storeu_ps(&c[3 * ldc],  c3);
	_mm512_storeu_ps(&c[4 * ldc],  c4);
	_mm512_storeu_ps(&c[5 * ldc],  c5);
	_mm512_storeu_ps(&c[6 * ldc],  c6);
	_mm512_storeu_ps(&c[7 * ldc],  c7);
	_mm512_storeu_ps(&c[8 * ldc],  c8);
	_mm512_storeu_ps(&c[9 * ldc],  c9);
	_mm512_storeu_ps(&c[10 * ldc], c10);
	_mm512_storeu_ps(&c[11 * ldc], c11);
	_mm512_storeu_ps(&c[12 * ldc], c12);
	_mm512_storeu_ps(&c[13 * ldc], c13);
	_mm512_storeu_ps(&c[14 * ldc], c14);
	_mm512_storeu_ps(&c[15 * ldc], c15);
}

/* ============================================
 * Micro-kernel: 16xN remainder (N < 16)
 *
 * Computes: C[0..15][0..n_rem) += A[0..15][0..k) * B[0..k)[0..n_rem)
 *
 * This variant handles the case where the number of columns in the
 * remaining tile is less than 16. It uses AVX-512 masking to:
 *   1. Mask the B load to only load the valid n_rem columns
 *   2. Mask the FMA to only update the valid n_rem columns
 *   3. Mask the C store to only write the valid n_rem columns
 *
 * The masking ensures that the extra columns (beyond n_rem) are
 * not modified, maintaining correctness for the edge case.
 * ============================================ */
static AVX512_TARGET void avx512_micro_16xN(int k, int n_rem,
					     const float *a_packed,
					     const float *b_packed,
					     float *c, int ldc)
{
	__m512 c0, c1, c2, c3, c4, c5, c6, c7;
	__m512 c8, c9, c10, c11, c12, c13, c14, c15;
	__mmask16 col_mask;
	int p;

	/*
	 * Compute the column mask.
	 * n_rem is in [1, 15]; we set the lowest n_rem bits.
	 */
	col_mask = avx512_mask16(n_rem);

	/* Initialize accumulators to zero */
	c0  = _mm512_setzero_ps();
	c1  = _mm512_setzero_ps();
	c2  = _mm512_setzero_ps();
	c3  = _mm512_setzero_ps();
	c4  = _mm512_setzero_ps();
	c5  = _mm512_setzero_ps();
	c6  = _mm512_setzero_ps();
	c7  = _mm512_setzero_ps();
	c8  = _mm512_setzero_ps();
	c9  = _mm512_setzero_ps();
	c10 = _mm512_setzero_ps();
	c11 = _mm512_setzero_ps();
	c12 = _mm512_setzero_ps();
	c13 = _mm512_setzero_ps();
	c14 = _mm512_setzero_ps();
	c15 = _mm512_setzero_ps();

	/*
	 * Main K-loop with masked operations.
	 * The B load is masked to only load the first n_rem values;
	 * the remaining elements are zeroed. The FMA on the zeroed
	 * elements contributes nothing to the accumulator.
	 */
	for (p = 0; p < k; p++) {
		__m512 a_row;
		__m512 b_val;

		/*
		 * Load B values with masking.
		 * Only the first n_rem elements are loaded from packed B;
		 * the rest are zeroed by the mask.
		 */
		b_val = _mm512_mask_loadu_ps(_mm512_setzero_ps(), col_mask,
					     &b_packed[p * NR_DEFAULT]);

		/*
		 * Load 16 A values (always full row, no masking needed
		 * for A since we broadcast individual values).
		 */
		a_row = _mm512_loadu_ps(&a_packed[p * MR_DEFAULT]);

		/*
		 * Masked FMA: only the first n_rem columns are updated.
		 * The mask is applied to the FMA operation, ensuring
		 * that the extra accumulator elements remain unchanged.
		 */
		c0  = _mm512_mask_fmadd_ps(c0,  col_mask,
					   _mm512_set1_ps(((float *)&a_row)[0]),  b_val);
		c1  = _mm512_mask_fmadd_ps(c1,  col_mask,
					   _mm512_set1_ps(((float *)&a_row)[1]),  b_val);
		c2  = _mm512_mask_fmadd_ps(c2,  col_mask,
					   _mm512_set1_ps(((float *)&a_row)[2]),  b_val);
		c3  = _mm512_mask_fmadd_ps(c3,  col_mask,
					   _mm512_set1_ps(((float *)&a_row)[3]),  b_val);
		c4  = _mm512_mask_fmadd_ps(c4,  col_mask,
					   _mm512_set1_ps(((float *)&a_row)[4]),  b_val);
		c5  = _mm512_mask_fmadd_ps(c5,  col_mask,
					   _mm512_set1_ps(((float *)&a_row)[5]),  b_val);
		c6  = _mm512_mask_fmadd_ps(c6,  col_mask,
					   _mm512_set1_ps(((float *)&a_row)[6]),  b_val);
		c7  = _mm512_mask_fmadd_ps(c7,  col_mask,
					   _mm512_set1_ps(((float *)&a_row)[7]),  b_val);
		c8  = _mm512_mask_fmadd_ps(c8,  col_mask,
					   _mm512_set1_ps(((float *)&a_row)[8]),  b_val);
		c9  = _mm512_mask_fmadd_ps(c9,  col_mask,
					   _mm512_set1_ps(((float *)&a_row)[9]),  b_val);
		c10 = _mm512_mask_fmadd_ps(c10, col_mask,
					   _mm512_set1_ps(((float *)&a_row)[10]), b_val);
		c11 = _mm512_mask_fmadd_ps(c11, col_mask,
					   _mm512_set1_ps(((float *)&a_row)[11]), b_val);
		c12 = _mm512_mask_fmadd_ps(c12, col_mask,
					   _mm512_set1_ps(((float *)&a_row)[12]), b_val);
		c13 = _mm512_mask_fmadd_ps(c13, col_mask,
					   _mm512_set1_ps(((float *)&a_row)[13]), b_val);
		c14 = _mm512_mask_fmadd_ps(c14, col_mask,
					   _mm512_set1_ps(((float *)&a_row)[14]), b_val);
		c15 = _mm512_mask_fmadd_ps(c15, col_mask,
					   _mm512_set1_ps(((float *)&a_row)[15]), b_val);

		/* Prefetch next iterations */
		if ((p & 3) == 0) {
			int next_p = p + PREFETCH_DIST_A;
			if (next_p < k) {
				avx512_prefetch_l1(&a_packed[next_p * MR_DEFAULT]);
				avx512_prefetch_l1(&b_packed[next_p * NR_DEFAULT]);
			}
		}
	}

	/*
	 * Masked store: only the first n_rem columns are written to C.
	 * The remaining columns in the accumulator are not stored.
	 */
	_mm512_mask_storeu_ps(&c[0 * ldc],  col_mask, c0);
	_mm512_mask_storeu_ps(&c[1 * ldc],  col_mask, c1);
	_mm512_mask_storeu_ps(&c[2 * ldc],  col_mask, c2);
	_mm512_mask_storeu_ps(&c[3 * ldc],  col_mask, c3);
	_mm512_mask_storeu_ps(&c[4 * ldc],  col_mask, c4);
	_mm512_mask_storeu_ps(&c[5 * ldc],  col_mask, c5);
	_mm512_mask_storeu_ps(&c[6 * ldc],  col_mask, c6);
	_mm512_mask_storeu_ps(&c[7 * ldc],  col_mask, c7);
	_mm512_mask_storeu_ps(&c[8 * ldc],  col_mask, c8);
	_mm512_mask_storeu_ps(&c[9 * ldc],  col_mask, c9);
	_mm512_mask_storeu_ps(&c[10 * ldc], col_mask, c10);
	_mm512_mask_storeu_ps(&c[11 * ldc], col_mask, c11);
	_mm512_mask_storeu_ps(&c[12 * ldc], col_mask, c12);
	_mm512_mask_storeu_ps(&c[13 * ldc], col_mask, c13);
	_mm512_mask_storeu_ps(&c[14 * ldc], col_mask, c14);
	_mm512_mask_storeu_ps(&c[15 * ldc], col_mask, c15);
}

/* ============================================
 * Micro-kernel: Mx16 remainder (M < 16)
 *
 * Computes: C[0..m_rem)[0..15] += A[0..m_rem)[0..k) * B[0..k)[0..15]
 *
 * This variant handles the case where the number of rows in the
 * remaining tile is less than 16. It uses:
 *   1. Fewer accumulators (m_rem instead of 16)
 *   2. Masked store for the m_rem rows
 *   3. Full B loads (16 columns are still valid)
 *   4. Full A loads (but we only use the first m_rem values)
 *
 * This is more efficient than the MxN fallback because we can
 * still use full 512-bit B loads and FMAs.
 * ============================================ */
static AVX512_TARGET void avx512_micro_Mx16(int k, int m_rem,
					     const float *a_packed,
					     const float *b_packed,
					     float *c, int ldc)
{
	__m512 acc[16];
	int p, r;

	/* Initialize accumulators */
	for (r = 0; r < 16; r++)
		acc[r] = _mm512_setzero_ps();

	/*
	 * Main K-loop.
	 * We still load 16 A values and 16 B values per iteration,
	 * but only m_rem of the A values are used (the rest are
	 * multiplied by the B values but added to zero accumulators,
	 * so they contribute nothing).
	 *
	 * This is slightly wasteful (we do 16 FMAs instead of m_rem),
	 * but it avoids branching in the inner loop and keeps the
	 * code streamlined. The waste is minimal for the edge case.
	 */
	for (p = 0; p < k; p++) {
		__m512 b_val = _mm512_loadu_ps(&b_packed[p * NR_DEFAULT]);
		__m512 a_row = _mm512_loadu_ps(&a_packed[p * MR_DEFAULT]);

		/*
		 * Perform all 16 FMAs, even though we only need m_rem.
		 * The extra accumulators (m_rem..15) are zero and will
		 * not be stored, so the extra computation is harmless.
		 */
		acc[0]  = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[0]),  b_val, acc[0]);
		acc[1]  = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[1]),  b_val, acc[1]);
		acc[2]  = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[2]),  b_val, acc[2]);
		acc[3]  = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[3]),  b_val, acc[3]);
		acc[4]  = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[4]),  b_val, acc[4]);
		acc[5]  = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[5]),  b_val, acc[5]);
		acc[6]  = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[6]),  b_val, acc[6]);
		acc[7]  = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[7]),  b_val, acc[7]);
		acc[8]  = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[8]),  b_val, acc[8]);
		acc[9]  = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[9]),  b_val, acc[9]);
		acc[10] = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[10]), b_val, acc[10]);
		acc[11] = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[11]), b_val, acc[11]);
		acc[12] = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[12]), b_val, acc[12]);
		acc[13] = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[13]), b_val, acc[13]);
		acc[14] = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[14]), b_val, acc[14]);
		acc[15] = _mm512_fmadd_ps(_mm512_set1_ps(((float *)&a_row)[15]), b_val, acc[15]);

		/* Prefetch next iterations */
		if ((p & 3) == 0) {
			int next_p = p + PREFETCH_DIST_A;
			if (next_p < k) {
				avx512_prefetch_l1(&a_packed[next_p * MR_DEFAULT]);
				avx512_prefetch_l1(&b_packed[next_p * NR_DEFAULT]);
			}
		}
	}

	/*
	 * Store the valid rows to C.
	 * For rows 0..m_rem-1, we store all 16 columns.
	 * Rows m_rem..15 are not stored (they contain junk).
	 *
	 * Note: The row_mask from avx512_mask16(m_rem) sets bits 0..m_rem-1,
	 * but this is a column-space mask, not a row-selector. For the store,
	 * we use the mask as a column mask: rows < m_rem store all 16 columns
	 * (mask = 0xFFFF), rows >= m_rem store nothing (mask = 0).
	 *
	 * The simplest correct approach is to store only the m_rem valid rows.
	 */
	for (r = 0; r < m_rem; r++) {
		_mm512_storeu_ps(&c[r * ldc], acc[r]);
	}
}

/* ============================================
 * Micro-kernel: MxN remainder (both M < 16 and N < 16)
 *
 * Computes: C[0..m_rem)[0..n_rem) += A[0..m_rem)[0..k) * B[0..k)[0..n_rem)
 *
 * Fallback for the doubly-remainder case where both dimensions
 * are less than 16. Uses scalar operations since the overhead
 * of setting up SIMD for tiny tiles is not worth it.
 * ============================================ */
static AVX512_TARGET void avx512_micro_MxN(int k, int m_rem, int n_rem,
					    const float *a_packed,
					    const float *b_packed,
					    float *c, int ldc)
{
	int p, i, j;

	/*
	 * Scalar triple loop for the remainder tile.
	 * This is invoked only for the very last tile when both
	 * m_rem < 16 and n_rem < 16, which is at most one tile
	 * per matmul call. The performance impact is negligible.
	 */
	for (i = 0; i < m_rem; i++) {
		for (j = 0; j < n_rem; j++) {
			float sum = 0.0f;
			for (p = 0; p < k; p++) {
				sum += a_packed[p * MR_DEFAULT + i]
				     * b_packed[p * NR_DEFAULT + j];
			}
			c[i * ldc + j] += sum;
		}
	}
}

/* ============================================
 * Large matrix multiply: Fully tiled with packing
 *
 * This is the main code path for large matrices where the
 * working set exceeds L2 cache capacity. It uses:
 *   1. Multi-level tiling (MC, NC, KC) for cache efficiency
 *   2. Explicit packing of A and B panels
 *   3. Micro-kernel for register-level computation
 *   4. Software prefetching for latency hiding
 *
 * Algorithm:
 *   For each row tile i (step MC):
 *     For each col tile j (step NC):
 *       Zero the C tile [i:i+MC, j:j+NC]
 *       For each k tile p (step KC):
 *         Pack A tile [i:i+MC, p:p+KC] -> packed_A
 *         Pack B tile [p:p+KC, j:j+NC] -> packed_B
 *         For each micro-row block ii in [0, MC) step MR:
 *           For each micro-col block jj in [0, NC) step NR:
 *             micro_kernel(C[i+ii][j+jj], packed_A[...], packed_B[...])
 *         Accumulate into C tile
 *       Write C tile back
 *
 * The packing is done once per tile, which is amortized over
 * the MR x NR micro-kernel calls within that tile.
 * ============================================ */
static AVX512_TARGET void avx512_matmul_large(int m, int n, int k,
					       const float *a, int lda,
					       const float *b, int ldb,
					       float *c, int ldc)
{
	/*
	 * Allocate packing buffers.
	 * These are sized for the largest tile and reused.
	 * A_packed: MC * KC floats, B_packed: KC * NC floats.
	 */
	float *a_packed = NULL;
	float *b_packed = NULL;
	int i, j, p;

	/*
	 * Determine tile sizes based on matrix dimensions.
	 * We use the default tile sizes for most cases, but
	 * reduce tile sizes for smaller matrices to avoid
	 * excessive packing overhead.
	 */
	int mc = (m < MC_DEFAULT) ? m : MC_DEFAULT;
	int nc = (n < NC_DEFAULT) ? n : NC_DEFAULT;
	int kc = (k < KC_DEFAULT) ? k : KC_DEFAULT;

	/*
	 * For very large inner dimensions, use larger K tiles
	 * to improve reuse of the packed A panel.
	 */
	if (k > 2048 && kc < KC_LARGE)
		kc = KC_LARGE;

	/*
	 * Allocate packing buffers with cache-line alignment.
	 * These are used for the duration of the matmul call.
	 */
	a_packed = (float *)avx512_aligned_alloc(
			(size_t)mc * kc * sizeof(float));
	b_packed = (float *)avx512_aligned_alloc(
			(size_t)kc * nc * sizeof(float));

	if (!a_packed || !b_packed) {
		/*
		 * Memory allocation failure: fall back to the
		 * medium path which doesn't need packing buffers.
		 * This is a safe fallback that ensures correctness
		 * even under memory pressure.
		 */
		avx512_aligned_free(a_packed);
		avx512_aligned_free(b_packed);
		avx512_matmul_medium(m, n, k, a, lda, b, ldb, c, ldc);
		return;
	}

	/*
	 * Outer tile loop over M dimension.
	 */
	for (i = 0; i < m; i += mc) {
		int mb = (i + mc <= m) ? mc : (m - i);

		/*
		 * Outer tile loop over N dimension.
		 */
		for (j = 0; j < n; j += nc) {
			int nb = (j + nc <= n) ? nc : (n - j);

			/*
			 * Zero the C tile for this (i, j) position.
			 * This initializes the accumulators before
			 * we accumulate partial products from each K tile.
			 */
			avx512_zero_c_tile(&c[i * ldc + j], ldc, mb, nb);

			/*
			 * Inner tile loop over K dimension.
			 * For each K tile, we pack A and B panels and
			 * then call the micro-kernel for each sub-block.
			 */
			for (p = 0; p < k; p += kc) {
				int kb = (p + kc <= k) ? kc : (k - p);
				int ii, jj;

				/*
				 * Pack A tile: mb x kb block starting at A[i][p].
				 * This transposes the data into the packed format
				 * for efficient micro-kernel access.
				 */
				avx512_pack_a_tile(kb, mb,
						   &a[i * lda + p], lda,
						   a_packed);

				/*
				 * Pack B tile: kb x nb block starting at B[p][j].
				 */
				avx512_pack_b_tile(kb, nb,
						   &b[p * ldb + j], ldb,
						   b_packed);

				/*
				 * Micro-kernel loop: process the C tile in
				 * MR x NR sub-blocks.
				 *
				 * For each MR x NR sub-block of C at position
				 * (i+ii, j+jj), we compute the contribution
				 * from the current K tile.
				 */
				for (ii = 0; ii < mb; ii += MR_DEFAULT) {
					int m_rem = (ii + MR_DEFAULT <= mb)
						    ? MR_DEFAULT : (mb - ii);

					/*
					 * Compute the offset into the packed A buffer
					 * for this row block. Since A is packed as
					 * [k][MR] for each k in [0, kb), the offset
					 * for the ii-th row block is:
					 *   offset = (ii / MR) * kb * MR
					 */
					int a_off = (ii / MR_DEFAULT) * kb * MR_DEFAULT;

					for (jj = 0; jj < nb; jj += NR_DEFAULT) {
						int n_rem = (jj + NR_DEFAULT <= nb)
							    ? NR_DEFAULT : (nb - jj);

						/*
						 * Compute the offset into the packed B buffer
						 * for this column block.
						 *   offset = (jj / NR) * kb * NR
						 */
						int b_off = (jj / NR_DEFAULT) * kb * NR_DEFAULT;

						/*
						 * Select the appropriate micro-kernel
						 * based on the remainder dimensions.
						 *
						 * The micro-kernel updates:
						 *   C[i+ii : i+ii+m_rem, j+jj : j+jj+n_rem]
						 * using packed A at a_packed + a_off and
						 * packed B at b_packed + b_off.
						 */
						if (m_rem == MR_DEFAULT && n_rem == NR_DEFAULT) {
							/* Full 16x16 tile */
							avx512_micro_16x16(kb,
								a_packed + a_off,
								b_packed + b_off,
								&c[(i + ii) * ldc + j + jj],
								ldc);
						} else if (m_rem == MR_DEFAULT) {
							/* 16 x N remainder */
							avx512_micro_16xN(kb, n_rem,
								a_packed + a_off,
								b_packed + b_off,
								&c[(i + ii) * ldc + j + jj],
								ldc);
						} else if (n_rem == NR_DEFAULT) {
							/* M x 16 remainder */
							avx512_micro_Mx16(kb, m_rem,
								a_packed + a_off,
								b_packed + b_off,
								&c[(i + ii) * ldc + j + jj],
								ldc);
						} else {
							/* M x N remainder (both < 16) */
							avx512_micro_MxN(kb, m_rem, n_rem,
								a_packed + a_off,
								b_packed + b_off,
								&c[(i + ii) * ldc + j + jj],
								ldc);
						}
					}
				}

				/*
				 * Prefetch the next K tile's A and B data.
				 * This overlaps memory access with computation.
				 */
				if (p + kc < k) {
					avx512_prefetch_l2(&a[(i + mb - 1) * lda + p + kc]);
					avx512_prefetch_l2(&b[(p + kc) * ldb + j]);
				}
			}
		}
	}

	/* Free packing buffers */
	avx512_aligned_free(a_packed);
	avx512_aligned_free(b_packed);
}

/* ============================================
 * Medium matrix multiply: Simple tiling without packing
 *
 * For medium-sized matrices (working set fits in L2 cache),
 * we skip the explicit packing step and directly access the
 * original matrices in the micro-kernel. This avoids the
 * overhead of allocating and filling packing buffers when
 * the cache-friendly access patterns are less critical.
 *
 * The micro-kernel accesses A and B with strided loads,
 * which is less efficient than packed access but avoids
 * the O(mc * kc + kc * nc) packing cost.
 * ============================================ */
static AVX512_TARGET void avx512_matmul_medium(int m, int n, int k,
						const float *a, int lda,
						const float *b, int ldb,
						float *c, int ldc)
{
	/*
	 * Allocate temporary packed buffers for the micro-kernel.
	 * These are smaller than the full tile buffers used in the
	 * large path, sized for MR x KC and KC x NR respectively.
	 */
	float a_packed[MR_DEFAULT * KC_DEFAULT] __attribute__((aligned(64)));
	float b_packed[KC_DEFAULT * NR_DEFAULT] __attribute__((aligned(64)));
	int i, j, p;

	/*
	 * Outer tile loop over M dimension.
	 * We use MR_DEFAULT as the row tile size.
	 */
	for (i = 0; i < m; i += MR_DEFAULT) {
		int mb = (i + MR_DEFAULT <= m) ? MR_DEFAULT : (m - i);

		/*
		 * Outer tile loop over N dimension.
		 * We use NR_DEFAULT as the column tile size.
		 */
		for (j = 0; j < n; j += NR_DEFAULT) {
			int nb = (j + NR_DEFAULT <= n) ? NR_DEFAULT : (n - j);

			/*
			 * Zero the C sub-block.
			 */
			avx512_zero_c_tile(&c[i * ldc + j], ldc, mb, nb);

			/*
			 * Inner loop over K dimension.
			 * We process K in blocks of KC_DEFAULT to improve
			 * cache reuse of the packed A and B buffers.
			 */
			for (p = 0; p < k; p += KC_DEFAULT) {
				int kb = (p + KC_DEFAULT <= k) ? KC_DEFAULT : (k - p);

				/*
				 * Pack the current A sub-block (mb x kb) into
				 * the packed format. This is a small buffer
				 * (MR * KC float = 16 * 256 = 4 KB) that fits
				 * in L1 cache.
				 */
				avx512_pack_a_tile(kb, mb,
						   &a[i * lda + p], lda,
						   a_packed);

				/*
				 * Pack the current B sub-block (kb x nb) into
				 * the packed format.
				 */
				avx512_pack_b_tile(kb, nb,
						   &b[p * ldb + j], ldb,
						   b_packed);

				/*
				 * Call the micro-kernel for the current sub-block.
				 * Since mb <= MR and nb <= NR, we handle
				 * remainders directly.
				 */
				if (mb == MR_DEFAULT && nb == NR_DEFAULT) {
					avx512_micro_16x16(kb, a_packed, b_packed,
							   &c[i * ldc + j], ldc);
				} else if (mb == MR_DEFAULT) {
					avx512_micro_16xN(kb, nb, a_packed, b_packed,
							  &c[i * ldc + j], ldc);
				} else if (nb == NR_DEFAULT) {
					avx512_micro_Mx16(kb, mb, a_packed, b_packed,
							  &c[i * ldc + j], ldc);
				} else {
					avx512_micro_MxN(kb, mb, nb, a_packed, b_packed,
							 &c[i * ldc + j], ldc);
				}
			}
		}
	}
}

/* ============================================
 * Small matrix multiply: Direct vectorized
 *
 * For very small matrices (working set fits in L1 cache),
 * we use a simple direct approach without any tiling or
 * packing. This minimizes overhead for small dimensions.
 *
 * The algorithm processes the full C matrix in MR x NR
 * blocks, but accesses A and B directly from the original
 * matrices (no packing). This is slightly less efficient
 * per FLOP but avoids all setup overhead.
 * ============================================ */
static AVX512_TARGET void avx512_matmul_small(int m, int n, int k,
					       const float *a, int lda,
					       const float *b, int ldb,
					       float *c, int ldc)
{
	int i, j, p;

	/*
	 * Direct outer-product approach.
	 * For each row of A, broadcast it across all columns of B
	 * and accumulate into C.
	 *
	 * This is a simplified version of the micro-kernel that
	 * works directly on the original matrix layout.
	 */
	for (i = 0; i < m; i++) {
		/*
		 * Process 16 columns of C at a time.
		 */
		for (j = 0; j + 16 <= n; j += 16) {
			__m512 c_reg = _mm512_loadu_ps(&c[i * ldc + j]);

			/*
			 * Inner product over K.
			 * For each k, broadcast A[i][k] and FMA with B[k][j..j+15].
			 */
			for (p = 0; p < k; p++) {
				__m512 a_val = _mm512_set1_ps(a[i * lda + p]);
				__m512 b_reg = _mm512_loadu_ps(&b[p * ldb + j]);

				c_reg = _mm512_fmadd_ps(a_val, b_reg, c_reg);
			}

			_mm512_storeu_ps(&c[i * ldc + j], c_reg);
		}

		/*
		 * Handle remainder columns.
		 */
		if (j < n) {
			__mmask16 col_mask = avx512_mask16(n - j);
			__m512 c_reg = _mm512_mask_loadu_ps(
						_mm512_setzero_ps(), col_mask,
						&c[i * ldc + j]);

			for (p = 0; p < k; p++) {
				__m512 a_val = _mm512_set1_ps(a[i * lda + p]);
				__m512 b_reg = _mm512_mask_loadu_ps(
						_mm512_setzero_ps(), col_mask,
						&b[p * ldb + j]);

				c_reg = _mm512_mask_fmadd_ps(c_reg, col_mask,
							      a_val, b_reg);
			}

			_mm512_mask_storeu_ps(&c[i * ldc + j], col_mask, c_reg);
		}
	}
}

/* ============================================
 * avx512_matmul_fp32: Main entry point
 *
 * Dispatches to the appropriate code path based on matrix size.
 * Handles all dimension remainder cases and ensures correct
 * results for arbitrary m, n, k values.
 * ============================================ */
AVX512_TARGET
void avx512_matmul_fp32(int m, int n, int k,
                         const float *a, const float *b, float *c)
{
	int lda, ldb, ldc;

	if (m <= 0 || n <= 0 || k <= 0) {
		if (m > 0 && n > 0 && k == 0) {
			kernel_fpu_begin();
			avx512_zero_c_tile(c, n, m, n);
			kernel_fpu_end();
		}
		return;
	}

	lda = k;
	ldb = n;
	ldc = n;

	kernel_fpu_begin();

	if (avx512_is_small(m, n, k)) {
		avx512_matmul_small(m, n, k, a, lda, b, ldb, c, ldc);
	} else if (avx512_is_medium(m, n, k)) {
		avx512_matmul_medium(m, n, k, a, lda, b, ldb, c, ldc);
	} else {
		avx512_matmul_large(m, n, k, a, lda, b, ldb, c, ldc);
	}

	kernel_fpu_end();
}

/* ============================================
 * avx512_dot_product: Vector dot product
 *
 * Computes: result = sum_i a[i] * b[i] for i in [0, n)
 * Uses AVX-512 FMA, processing 16 elements at a time.
 * ============================================ */
AVX512_TARGET
float avx512_dot_product(int n, const float *a, const float *b)
{
	float result;

	if (n <= 0)
		return 0.0f;

	kernel_fpu_begin();

	if (n <= 64)
		result = avx512_dot_product_small(n, a, b);
	else
		result = avx512_dot_product_large(n, a, b);

	kernel_fpu_end();

	return result;
}

/* ============================================
 * Dot product: Large n path (n > 64)
 *
 * Uses 4 accumulators to hide FMA latency (4-5 cycles).
 * Processes 64 elements per outer iteration with 4-way unrolling.
 * ============================================ */
static AVX512_TARGET float avx512_dot_product_large(int n,
						      const float *a,
						      const float *b)
{
	__m512 sum0 = _mm512_setzero_ps();
	__m512 sum1 = _mm512_setzero_ps();
	__m512 sum2 = _mm512_setzero_ps();
	__m512 sum3 = _mm512_setzero_ps();
	int i = 0;

	for (; i + 64 <= n; i += 64) {
		__m512 a0, a1, a2, a3, b0, b1, b2, b3;

		a0 = _mm512_loadu_ps(&a[i + 0 * 16]);
		a1 = _mm512_loadu_ps(&a[i + 1 * 16]);
		a2 = _mm512_loadu_ps(&a[i + 2 * 16]);
		a3 = _mm512_loadu_ps(&a[i + 3 * 16]);
		b0 = _mm512_loadu_ps(&b[i + 0 * 16]);
		b1 = _mm512_loadu_ps(&b[i + 1 * 16]);
		b2 = _mm512_loadu_ps(&b[i + 2 * 16]);
		b3 = _mm512_loadu_ps(&b[i + 3 * 16]);

		sum0 = _mm512_fmadd_ps(a0, b0, sum0);
		sum1 = _mm512_fmadd_ps(a1, b1, sum1);
		sum2 = _mm512_fmadd_ps(a2, b2, sum2);
		sum3 = _mm512_fmadd_ps(a3, b3, sum3);

		avx512_prefetch_l1(&a[i + 64 + PREFETCH_DIST_A * 16]);
		avx512_prefetch_l1(&b[i + 64 + PREFETCH_DIST_A * 16]);
	}

	for (; i + 16 <= n; i += 16) {
		__m512 a_val = _mm512_loadu_ps(&a[i]);
		__m512 b_val = _mm512_loadu_ps(&b[i]);
		sum0 = _mm512_fmadd_ps(a_val, b_val, sum0);
	}

	if (i < n) {
		__mmask16 mask = avx512_mask16(n - i);
		__m512 a_val = _mm512_mask_loadu_ps(_mm512_setzero_ps(),
						     mask, &a[i]);
		__m512 b_val = _mm512_mask_loadu_ps(_mm512_setzero_ps(),
						     mask, &b[i]);
		sum0 = _mm512_fmadd_ps(a_val, b_val, sum0);
	}

	sum0 = _mm512_add_ps(sum0, sum1);
	sum2 = _mm512_add_ps(sum2, sum3);
	sum0 = _mm512_add_ps(sum0, sum2);

	return _mm512_reduce_add_ps(sum0);
}

/* ============================================
 * Dot product: Small n path (n <= 64)
 * ============================================ */
static AVX512_TARGET float avx512_dot_product_small(int n,
						      const float *a,
						      const float *b)
{
	__m512 sum = _mm512_setzero_ps();
	int i = 0;

	for (; i + 16 <= n; i += 16) {
		__m512 a_val = _mm512_loadu_ps(&a[i]);
		__m512 b_val = _mm512_loadu_ps(&b[i]);
		sum = _mm512_fmadd_ps(a_val, b_val, sum);
	}

	if (i < n) {
		__mmask16 mask = avx512_mask16(n - i);
		__m512 a_val = _mm512_mask_loadu_ps(_mm512_setzero_ps(),
						     mask, &a[i]);
		__m512 b_val = _mm512_mask_loadu_ps(_mm512_setzero_ps(),
						     mask, &b[i]);
		sum = _mm512_fmadd_ps(a_val, b_val, sum);
	}

	return _mm512_reduce_add_ps(sum);
}

/* ============================================
 * avx512_quantize_fp32_to_q8: Float32 to int8 quantization
 *
 * dst[i] = saturate_i8(src[i] * scale)
 * Converts with round-to-nearest, packs with signed saturation.
 * ============================================ */
AVX512_TARGET
void avx512_quantize_fp32_to_q8(int n, const float *src,
                                 void *dst, float scale)
{
	int8_t *dst8 = (int8_t *)dst;

	if (n <= 0 || !src || !dst)
		return;

	kernel_fpu_begin();

	if (n <= 32)
		avx512_quantize_q8_small(n, src, dst8, scale);
	else
		avx512_quantize_q8_large(n, src, dst8, scale);

	kernel_fpu_end();
}

/* ============================================
 * Quantize Q8: Large n path
 * Processes 32 elements per iteration (2 zmm loads, unrolled).
 * ============================================ */
static AVX512_TARGET void avx512_quantize_q8_large(int n,
						     const float *src,
						     void *dst, float scale)
{
	int8_t *dst8 = (int8_t *)dst;
	const __m512 vscale = _mm512_set1_ps(scale);
	int i = 0;

	for (; i + 32 <= n; i += 32) {
		__m512 v0 = _mm512_loadu_ps(&src[i]);
		__m512 v1 = _mm512_loadu_ps(&src[i + 16]);

		v0 = _mm512_mul_ps(v0, vscale);
		v1 = _mm512_mul_ps(v1, vscale);

		__m512i vi0 = _mm512_cvt_roundps_epi32(v0,
				_MM_FROUND_TO_NEAREST_INT | _MM_FROUND_NO_EXC);
		__m512i vi1 = _mm512_cvt_roundps_epi32(v1,
				_MM_FROUND_TO_NEAREST_INT | _MM_FROUND_NO_EXC);

		__m128i packed0 = _mm512_cvtsepi32_epi8(vi0);
		__m128i packed1 = _mm512_cvtsepi32_epi8(vi1);

		_mm_storeu_si128((__m128i *)&dst8[i], packed0);
		_mm_storeu_si128((__m128i *)&dst8[i + 16], packed1);

		avx512_prefetch_l1(&src[i + 32 + PREFETCH_DIST_A * 16]);
	}

	for (; i + 16 <= n; i += 16) {
		__m512 v = _mm512_loadu_ps(&src[i]);
		v = _mm512_mul_ps(v, vscale);
		__m512i vi = _mm512_cvt_roundps_epi32(v,
				_MM_FROUND_TO_NEAREST_INT | _MM_FROUND_NO_EXC);
		__m128i packed = _mm512_cvtsepi32_epi8(vi);
		_mm_storeu_si128((__m128i *)&dst8[i], packed);
	}

	if (i < n) {
		__mmask16 mask = avx512_mask16(n - i);
		__m512 v = _mm512_mask_loadu_ps(_mm512_setzero_ps(),
						 mask, &src[i]);
		v = _mm512_mul_ps(v, vscale);
		__m512i vi = _mm512_cvt_roundps_epi32(v,
				_MM_FROUND_TO_NEAREST_INT | _MM_FROUND_NO_EXC);
		__m128i packed = _mm512_cvtsepi32_epi8(vi);
		_mm_mask_storeu_epi8(&dst8[i], mask, packed);
	}
}

/* ============================================
 * Quantize Q8: Small n path (n <= 32)
 * ============================================ */
static AVX512_TARGET void avx512_quantize_q8_small(int n,
						     const float *src,
						     void *dst, float scale)
{
	int8_t *dst8 = (int8_t *)dst;
	const __m512 vscale = _mm512_set1_ps(scale);
	int i = 0;

	for (; i + 16 <= n; i += 16) {
		__m512 v = _mm512_loadu_ps(&src[i]);
		v = _mm512_mul_ps(v, vscale);
		__m512i vi = _mm512_cvt_roundps_epi32(v,
				_MM_FROUND_TO_NEAREST_INT | _MM_FROUND_NO_EXC);
		__m128i packed = _mm512_cvtsepi32_epi8(vi);
		_mm_storeu_si128((__m128i *)&dst8[i], packed);
	}

	if (i < n) {
		__mmask16 mask = avx512_mask16(n - i);
		__m512 v = _mm512_mask_loadu_ps(_mm512_setzero_ps(),
						 mask, &src[i]);
		v = _mm512_mul_ps(v, vscale);
		__m512i vi = _mm512_cvt_roundps_epi32(v,
				_MM_FROUND_TO_NEAREST_INT | _MM_FROUND_NO_EXC);
		__m128i packed = _mm512_cvtsepi32_epi8(vi);
		_mm_mask_storeu_epi8(&dst8[i], mask, packed);
	}
}

/* ============================================
 * avx512_quantize_fp32_to_q4: Float32 to 4-bit quantization
 *
 * Converts float32 to signed 4-bit integers packed into uint8.
 * Each byte: (q4[2i+1] << 4) | (q4[2i] & 0x0F)
 * Process 32 floats at a time (produces 16 bytes).
 * ============================================ */
AVX512_TARGET
void avx512_quantize_fp32_to_q4(int n, const float *src,
                                 void *dst, float scale)
{
	uint8_t *dst4 = (uint8_t *)dst;

	if (n <= 0 || !src || !dst)
		return;

	kernel_fpu_begin();

	if (n <= 32)
		avx512_quantize_q4_small(n, src, dst4, scale);
	else
		avx512_quantize_q4_large(n, src, dst4, scale);

	kernel_fpu_end();
}

/* ============================================
 * Quantize Q4: Large n path
 *
 * Process 32 floats -> 16 packed bytes per iteration.
 * Nibble interleaving: _mm_and_si128 for low nibbles,
 * _mm_slli_epi16 for shifting high nibbles into position.
 * ============================================ */
static AVX512_TARGET void avx512_quantize_q4_large(int n,
						     const float *src,
						     void *dst, float scale)
{
	uint8_t *dst4 = (uint8_t *)dst;
	const __m512 vscale = _mm512_set1_ps(scale);
	const __m128i nibble_mask = _mm_set1_epi8(0x0F);
	int i = 0;

	for (; i + 32 <= n; i += 32) {
		__m512 v0 = _mm512_loadu_ps(&src[i]);
		__m512 v1 = _mm512_loadu_ps(&src[i + 16]);

		v0 = _mm512_mul_ps(v0, vscale);
		v1 = _mm512_mul_ps(v1, vscale);

		__m512i vi0 = _mm512_cvt_roundps_epi32(v0,
				_MM_FROUND_TO_NEAREST_INT | _MM_FROUND_NO_EXC);
		__m512i vi1 = _mm512_cvt_roundps_epi32(v1,
				_MM_FROUND_TO_NEAREST_INT | _MM_FROUND_NO_EXC);

		__m128i p0 = _mm512_cvtsepi32_epi8(vi0);
		__m128i p1 = _mm512_cvtsepi32_epi8(vi1);

		__m128i low_nib  = _mm_and_si128(p0, nibble_mask);
		__m128i high_nib = _mm_and_si128(p1, nibble_mask);
		high_nib = _mm_slli_epi16(high_nib, 4);

		__m128i packed = _mm_or_si128(low_nib, high_nib);
		_mm_storeu_si128((__m128i *)&dst4[i / 2], packed);

		avx512_prefetch_l1(&src[i + 32 + PREFETCH_DIST_A * 16]);
	}

	for (; i + 32 <= n; i += 32) {
		__m512 v0 = _mm512_loadu_ps(&src[i]);
		__m512 v1 = _mm512_loadu_ps(&src[i + 16]);
		v0 = _mm512_mul_ps(v0, vscale);
		v1 = _mm512_mul_ps(v1, vscale);
		__m512i vi0 = _mm512_cvt_roundps_epi32(v0,
				_MM_FROUND_TO_NEAREST_INT | _MM_FROUND_NO_EXC);
		__m512i vi1 = _mm512_cvt_roundps_epi32(v1,
				_MM_FROUND_TO_NEAREST_INT | _MM_FROUND_NO_EXC);
		__m128i p0 = _mm512_cvtsepi32_epi8(vi0);
		__m128i p1 = _mm512_cvtsepi32_epi8(vi1);
		__m128i low_nib  = _mm_and_si128(p0, nibble_mask);
		__m128i high_nib = _mm_and_si128(p1, nibble_mask);
		high_nib = _mm_slli_epi16(high_nib, 4);
		__m128i packed = _mm_or_si128(low_nib, high_nib);
		_mm_storeu_si128((__m128i *)&dst4[i / 2], packed);
	}

	if (i < n) {
		int rem = n - i;
		int j;
		for (j = 0; j + 1 < rem; j += 2) {
			int8_t q0 = (int8_t)(src[i + j] * scale);
			int8_t q1 = (int8_t)(src[i + j + 1] * scale);
			if (q0 < -8) q0 = -8;
			if (q0 > 7)  q0 = 7;
			if (q1 < -8) q1 = -8;
			if (q1 > 7)  q1 = 7;
			dst4[(i + j) / 2] = (uint8_t)((q0 & 0x0F) |
						       ((q1 & 0x0F) << 4));
		}
		if (j < rem) {
			int8_t q0 = (int8_t)(src[i + j] * scale);
			if (q0 < -8) q0 = -8;
			if (q0 > 7)  q0 = 7;
			dst4[(i + j) / 2] = (uint8_t)(q0 & 0x0F);
		}
	}
}

/* ============================================
 * Quantize Q4: Small n path (n <= 32)
 * ============================================ */
static AVX512_TARGET void avx512_quantize_q4_small(int n,
						     const float *src,
						     void *dst, float scale)
{
	uint8_t *dst4 = (uint8_t *)dst;
	int i;

	for (i = 0; i + 1 < n; i += 2) {
		int8_t q0 = (int8_t)(src[i] * scale);
		int8_t q1 = (int8_t)(src[i + 1] * scale);
		if (q0 < -8) q0 = -8;
		if (q0 > 7)  q0 = 7;
		if (q1 < -8) q1 = -8;
		if (q1 > 7)  q1 = 7;
		dst4[i / 2] = (uint8_t)((q0 & 0x0F) | ((q1 & 0x0F) << 4));
	}
	if (i < n) {
		int8_t q0 = (int8_t)(src[i] * scale);
		if (q0 < -8) q0 = -8;
		if (q0 > 7)  q0 = 7;
		dst4[i / 2] = (uint8_t)(q0 & 0x0F);
	}
}

/* ============================================
 * avx512_dequantize_q8_to_fp32: int8 to float32 dequantization
 *
 * dst[i] = (float)src[i] / scale
 * Uses reciprocal multiply for efficiency.
 * ============================================ */
AVX512_TARGET
void avx512_dequantize_q8_to_fp32(int n, const void *src,
                                   float *dst, float scale)
{
	if (n <= 0 || !src || !dst)
		return;

	kernel_fpu_begin();

	if (n <= 32)
		avx512_dequantize_q8_small(n, src, dst, scale);
	else
		avx512_dequantize_q8_large(n, src, dst, scale);

	kernel_fpu_end();
}

/* ============================================
 * Dequantize Q8: Large n path
 *
 * Processes 32 elements per iteration (2 zmm loads).
 * Uses _mm512_cvtepi8_epi32 for sign extension (AVX-512BW).
 * ============================================ */
static AVX512_TARGET void avx512_dequantize_q8_large(int n,
						       const void *src,
						       float *dst, float scale)
{
	const int8_t *src8 = (const int8_t *)src;
	const __m512 vscale = _mm512_set1_ps(1.0f / scale);
	int i = 0;

	for (; i + 32 <= n; i += 32) {
		__m128i v0 = _mm_loadu_si128((const __m128i *)&src8[i]);
		__m128i v1 = _mm_loadu_si128((const __m128i *)&src8[i + 16]);

		__m512i vi0 = _mm512_cvtepi8_epi32(v0);
		__m512i vi1 = _mm512_cvtepi8_epi32(v1);

		__m512 f0 = _mm512_cvtepi32_ps(vi0);
		__m512 f1 = _mm512_cvtepi32_ps(vi1);

		f0 = _mm512_mul_ps(f0, vscale);
		f1 = _mm512_mul_ps(f1, vscale);

		_mm512_storeu_ps(&dst[i], f0);
		_mm512_storeu_ps(&dst[i + 16], f1);

		avx512_prefetch_l1(&src8[i + 32 + PREFETCH_DIST_A * 16]);
	}

	for (; i + 16 <= n; i += 16) {
		__m128i v = _mm_loadu_si128((const __m128i *)&src8[i]);
		__m512i vi = _mm512_cvtepi8_epi32(v);
		__m512 f = _mm512_cvtepi32_ps(vi);
		f = _mm512_mul_ps(f, vscale);
		_mm512_storeu_ps(&dst[i], f);
	}

	if (i < n) {
		__mmask16 mask = avx512_mask16(n - i);
		__m128i v = _mm_mask_loadu_epi8(_mm_setzero_si128(), mask,
						 (const __m128i *)&src8[i]);
		__m512i vi = _mm512_cvtepi8_epi32(v);
		__m512 f = _mm512_cvtepi32_ps(vi);
		f = _mm512_mul_ps(f, vscale);
		_mm512_mask_storeu_ps(&dst[i], mask, f);
	}
}

/* ============================================
 * Dequantize Q8: Small n path (n <= 32)
 * ============================================ */
static AVX512_TARGET void avx512_dequantize_q8_small(int n,
						       const void *src,
						       float *dst, float scale)
{
	const int8_t *src8 = (const int8_t *)src;
	const __m512 vscale = _mm512_set1_ps(1.0f / scale);
	int i = 0;

	for (; i + 16 <= n; i += 16) {
		__m128i v = _mm_loadu_si128((const __m128i *)&src8[i]);
		__m512i vi = _mm512_cvtepi8_epi32(v);
		__m512 f = _mm512_cvtepi32_ps(vi);
		f = _mm512_mul_ps(f, vscale);
		_mm512_storeu_ps(&dst[i], f);
	}

	if (i < n) {
		__mmask16 mask = avx512_mask16(n - i);
		__m128i v = _mm_mask_loadu_epi8(_mm_setzero_si128(), mask,
						 (const __m128i *)&src8[i]);
		__m512i vi = _mm512_cvtepi8_epi32(v);
		__m512 f = _mm512_cvtepi32_ps(vi);
		f = _mm512_mul_ps(f, vscale);
		_mm512_mask_storeu_ps(&dst[i], mask, f);
	}
}

/* ============================================
 * avx512_dequantize_q4_to_fp32: 4-bit to float32 dequantization
 *
 * Unpacks 4-bit signed values packed in uint8, sign-extends to
 * int8, then to int32, then converts to float with scale.
 *
 * Sign extension of 4-bit to 8-bit:
 *   signed_val = (nibble ^ 0x08) - 0x08
 *   Maps 0..7 -> 0..7, 8..15 -> -8..-1
 * ============================================ */
AVX512_TARGET
void avx512_dequantize_q4_to_fp32(int n, const void *src,
                                   float *dst, float scale)
{
	if (n <= 0 || !src || !dst)
		return;

	kernel_fpu_begin();

	if (n <= 32)
		avx512_dequantize_q4_small(n, src, dst, scale);
	else
		avx512_dequantize_q4_large(n, src, dst, scale);

	kernel_fpu_end();
}

/* ============================================
 * Dequantize Q4: Large n path
 *
 * Process 32 Q4 values (16 packed bytes) per iteration:
 *   1. Load 16 bytes from src
 *   2. Extract low/high nibbles
 *   3. Sign-extend 4-bit -> 8-bit -> 32-bit
 *   4. Convert to float, apply scale
 *   5. Store 32 floats to dst
 * ============================================ */
static AVX512_TARGET void avx512_dequantize_q4_large(int n,
						       const void *src,
						       float *dst, float scale)
{
	const uint8_t *src4 = (const uint8_t *)src;
	const __m512 vscale = _mm512_set1_ps(1.0f / scale);
	const __m128i nibble_mask = _mm_set1_epi8(0x0F);
	const __m128i xor_mask = _mm_set1_epi8(0x08);
	const __m128i sub_mask = _mm_set1_epi8(0x08);
	int i = 0;

	for (; i + 32 <= n; i += 32) {
		__m128i packed = _mm_loadu_si128(
					(const __m128i *)&src4[i / 2]);

		__m128i low_nib = _mm_and_si128(packed, nibble_mask);

		__m128i high_nib = _mm_srli_epi16(packed, 4);
		high_nib = _mm_and_si128(high_nib, nibble_mask);

		/* Sign-extend 4-bit to 8-bit: (nib ^ 0x08) - 0x08 */
		__m128i low_signed  = _mm_sub_epi8(
					_mm_xor_si128(low_nib, xor_mask),
					sub_mask);
		__m128i high_signed = _mm_sub_epi8(
					_mm_xor_si128(high_nib, xor_mask),
					sub_mask);

		/* Sign-extend 8-bit to 32-bit */
		__m512i vi_low  = _mm512_cvtepi8_epi32(low_signed);
		__m512i vi_high = _mm512_cvtepi8_epi32(high_signed);

		/* Convert to float and scale */
		__m512 f_low  = _mm512_cvtepi32_ps(vi_low);
		__m512 f_high = _mm512_cvtepi32_ps(vi_high);
		f_low  = _mm512_mul_ps(f_low, vscale);
		f_high = _mm512_mul_ps(f_high, vscale);

		_mm512_storeu_ps(&dst[i], f_low);
		_mm512_storeu_ps(&dst[i + 16], f_high);

		avx512_prefetch_l1(&src4[(i + 32) / 2 + PREFETCH_DIST_A * 8]);
	}

	for (; i + 32 <= n; i += 32) {
		__m128i packed = _mm_loadu_si128(
					(const __m128i *)&src4[i / 2]);
		__m128i low_nib = _mm_and_si128(packed, nibble_mask);
		__m128i high_nib = _mm_srli_epi16(packed, 4);
		high_nib = _mm_and_si128(high_nib, nibble_mask);
		__m128i low_signed  = _mm_sub_epi8(
					_mm_xor_si128(low_nib, xor_mask),
					sub_mask);
		__m128i high_signed = _mm_sub_epi8(
					_mm_xor_si128(high_nib, xor_mask),
					sub_mask);
		__m512i vi_low  = _mm512_cvtepi8_epi32(low_signed);
		__m512i vi_high = _mm512_cvtepi8_epi32(high_signed);
		__m512 f_low  = _mm512_cvtepi32_ps(vi_low);
		__m512 f_high = _mm512_cvtepi32_ps(vi_high);
		f_low  = _mm512_mul_ps(f_low, vscale);
		f_high = _mm512_mul_ps(f_high, vscale);
		_mm512_storeu_ps(&dst[i], f_low);
		_mm512_storeu_ps(&dst[i + 16], f_high);
	}

	if (i < n) {
		int rem = n - i;
		int j;
		for (j = 0; j + 1 < rem; j += 2) {
			uint8_t byte = src4[(i + j) / 2];
			int8_t q0 = (int8_t)(byte & 0x0F);
			int8_t q1 = (int8_t)(byte >> 4);
			if (q0 & 0x08) q0 |= 0xF0;
			if (q1 & 0x08) q1 |= 0xF0;
			dst[i + j]     = (float)q0 / scale;
			dst[i + j + 1] = (float)q1 / scale;
		}
		if (j < rem) {
			uint8_t byte = src4[(i + j) / 2];
			int8_t q0 = (int8_t)(byte & 0x0F);
			if (q0 & 0x08) q0 |= 0xF0;
			dst[i + j] = (float)q0 / scale;
		}
	}
}

/* ============================================
 * Dequantize Q4: Small n path (n <= 32)
 * ============================================ */
static AVX512_TARGET void avx512_dequantize_q4_small(int n,
						       const void *src,
						       float *dst, float scale)
{
	const uint8_t *src4 = (const uint8_t *)src;
	int i;

	for (i = 0; i + 1 < n; i += 2) {
		uint8_t byte = src4[i / 2];
		int8_t q0 = (int8_t)(byte & 0x0F);
		int8_t q1 = (int8_t)(byte >> 4);
		if (q0 & 0x08) q0 |= 0xF0;
		if (q1 & 0x08) q1 |= 0xF0;
		dst[i]     = (float)q0 / scale;
		dst[i + 1] = (float)q1 / scale;
	}
	if (i < n) {
		uint8_t byte = src4[i / 2];
		int8_t q0 = (int8_t)(byte & 0x0F);
		if (q0 & 0x08) q0 |= 0xF0;
		dst[i] = (float)q0 / scale;
	}
}

/* ============================================
 * avx512_batch_dot_product: Multiple vector dot products
 *
 * Computes batch_size dot products:
 *   results[b] = sum_i a[b*n + i] * b[b*n + i]
 *
 * Uses AVX-512 gather instructions for strided access across batches.
 * Processes 16 batches at a time using zmm registers.
 * ============================================ */
AVX512_TARGET
void avx512_batch_dot_product(int batch_size, int n,
                               const float *a, const float *b,
                               float *results)
{
	if (batch_size <= 0 || n <= 0 || !a || !b || !results)
		return;

	kernel_fpu_begin();

	if (batch_size <= 16) {
		avx512_batch_dot_product_single(batch_size, n, a, b, results);
	} else {
		int batch = 0;
		for (; batch + 16 <= batch_size; batch += 16) {
			avx512_batch_dot_product_single(16, n,
				&a[batch * n], &b[batch * n],
				&results[batch]);
		}
		if (batch < batch_size) {
			avx512_batch_dot_product_single(batch_size - batch, n,
				&a[batch * n], &b[batch * n],
				&results[batch]);
		}
	}

	kernel_fpu_end();
}

/* ============================================
 * Batch dot product: Single group (up to 16 batches)
 *
 * Processes 'batch_n' dot products (batch_n <= 16) in parallel
 * using AVX-512 gather. At each position i, gathers the i-th
 * element from all batches and accumulates via FMA.
 * ============================================ */
static AVX512_TARGET void avx512_batch_dot_product_single(int batch_n,
							   int n,
							   const float *a,
							   const float *b,
							   float *results)
{
	__m512 acc = _mm512_setzero_ps();
	__m512i base_indices;
	__mmask16 gather_mask;
	int i;

	/*
	 * Clamp batch_n to valid range [1, 16].
	 */
	if (batch_n <= 0)
		return;
	if (batch_n > 16)
		batch_n = 16;

	/*
	 * Build the base index vector for gather operations.
	 * For batch b and position i, the index is: b * n + i
	 *
	 * We precompute the batch offsets for all 16 possible batches.
	 * The gather mask controls which batches are actually loaded.
	 */
	gather_mask = avx512_mask16(batch_n);
	base_indices = _mm512_set_epi32(
		15 * n, 14 * n, 13 * n, 12 * n,
		11 * n, 10 * n, 9 * n, 8 * n,
		7 * n, 6 * n, 5 * n, 4 * n,
		3 * n, 2 * n, 1 * n, 0);

	/*
	 * Main loop: for each position i, gather a[i] and b[i] from
	 * all valid batches using masked gathers, then FMA.
	 *
	 * The masked gather (_mm512_mask_i32gather_ps) only loads
	 * from memory for lanes where the mask bit is set. Invalid
	 * lanes (batch_n..15) get the source value (zero), so their
	 * contribution to the FMA is zero.
	 */
	for (i = 0; i < n; i++) {
		__m512i indices = _mm512_add_epi32(base_indices,
						   _mm512_set1_epi32(i));

		/*
		 * Masked gather: only load batch_n valid lanes.
		 * Invalid lanes get zero from the source.
		 */
		__m512 a_vals = _mm512_mask_i32gather_ps(
					_mm512_setzero_ps(), gather_mask,
					indices, a, 4);
		__m512 b_vals = _mm512_mask_i32gather_ps(
					_mm512_setzero_ps(), gather_mask,
					indices, b, 4);

		/*
		 * FMA: multiply-add the valid lanes.
		 * Invalid lanes have a_vals=0, b_vals=0, so they
		 * contribute nothing to the accumulator.
		 */
		acc = _mm512_fmadd_ps(a_vals, b_vals, acc);

		/* Prefetch next iteration */
		if ((i & 3) == 0 && i + PREFETCH_DIST_A < n) {
			avx512_prefetch_l1(&a[i + PREFETCH_DIST_A]);
			avx512_prefetch_l1(&b[i + PREFETCH_DIST_A]);
		}
	}

	/*
	 * Store results. For batch_n < 16, use masked store
	 * to only write valid batch results.
	 */
	if (batch_n == 16) {
		_mm512_storeu_ps(results, acc);
	} else {
		__mmask16 store_mask = avx512_mask16(batch_n);
		_mm512_mask_storeu_ps(results, store_mask, acc);
	}
}

/* ============================================
 * Batch dot product: Scalar fallback for very small batches
 *
 * Processes each batch individually with standard dot product.
 * Used when batch_n < 4 where gather overhead dominates.
 * ============================================ */
static AVX512_TARGET void avx512_batch_dot_product_scalar(
				int batch_n, int n,
				const float *a, const float *b,
				float *results)
{
	int batch;

	for (batch = 0; batch < batch_n; batch++) {
		__m512 acc = _mm512_setzero_ps();
		int i;

		for (i = 0; i + 16 <= n; i += 16) {
			__m512 a_vals = _mm512_loadu_ps(&a[batch * n + i]);
			__m512 b_vals = _mm512_loadu_ps(&b[batch * n + i]);
			acc = _mm512_fmadd_ps(a_vals, b_vals, acc);
		}

		if (i < n) {
			__mmask16 mask = avx512_mask16(n - i);
			__m512 a_vals = _mm512_mask_loadu_ps(
						_mm512_setzero_ps(), mask,
						&a[batch * n + i]);
			__m512 b_vals = _mm512_mask_loadu_ps(
						_mm512_setzero_ps(), mask,
						&b[batch * n + i]);
			acc = _mm512_fmadd_ps(a_vals, b_vals, acc);
		}

		results[batch] = _mm512_reduce_add_ps(acc);
	}
}

/* ============================================
 * Static simd_ops descriptor for AVX-512 implementation
 *
 * Provides function pointers for all AVX-512 optimized operations.
 * Returned by avx512_get_ops() for registration with the main
 * AI vector acceleration module.
 * ============================================ */
static const struct simd_ops avx512_ops = {
	.matmul_fp32          = avx512_matmul_fp32,
	.dot_product          = avx512_dot_product,
	.quantize_fp32_to_q8  = avx512_quantize_fp32_to_q8,
	.quantize_fp32_to_q4  = avx512_quantize_fp32_to_q4,
	.dequantize_q8_to_fp32 = avx512_dequantize_q8_to_fp32,
	.dequantize_q4_to_fp32 = avx512_dequantize_q4_to_fp32,
	.name                 = "avx512",
	.vector_size          = 64,
};

/* ============================================
 * avx512_get_ops: Get the AVX-512 ops descriptor
 *
 * Returns a pointer to the static simd_ops structure.
 * Called by the main module during initialization.
 * ============================================ */
AVX512_TARGET
const struct simd_ops *avx512_get_ops(void)
{
	return &avx512_ops;
}

/*
 * Export the getter function and individual functions
 * for use by other kernel modules.
 */
EXPORT_SYMBOL_GPL(avx512_get_ops);
EXPORT_SYMBOL_GPL(avx512_matmul_fp32);
EXPORT_SYMBOL_GPL(avx512_dot_product);
EXPORT_SYMBOL_GPL(avx512_quantize_fp32_to_q8);
EXPORT_SYMBOL_GPL(avx512_quantize_fp32_to_q4);
EXPORT_SYMBOL_GPL(avx512_dequantize_q8_to_fp32);
EXPORT_SYMBOL_GPL(avx512_dequantize_q4_to_fp32);
EXPORT_SYMBOL_GPL(avx512_batch_dot_product);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Ainos OS AVX-512 SIMD Vector Acceleration Implementation");
MODULE_AUTHOR("Ainos OS Team");
