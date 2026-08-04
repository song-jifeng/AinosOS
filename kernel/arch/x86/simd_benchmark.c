// SPDX-License-Identifier: GPL-2.0
/*
 * Ainos OS - x86 SIMD Benchmark Framework
 * ==============================================
 * Comprehensive benchmark framework for comparing generic vs SIMD
 * implementation performance across matrix multiply, dot product,
 * quantization, and dequantization operations.
 *
 * This framework provides:
 *   - Automated benchmarking across multiple test sizes (64-2048)
 *   - Warmup phase to eliminate cache cold-start effects
 *   - Multiple iterations with min/max/avg/median/stddev statistics
 *   - Verification that SIMD results match generic results within tolerance
 *   - Formatted table output via pr_info
 *   - Speedup computation vs generic implementation
 *   - Module init-time benchmark execution with configurable parameters
 *
 * Operations benchmarked:
 *   - Matrix multiply (SGEMM): C = A * B
 *   - Dot product: sum(a[i] * b[i])
 *   - Quantize: FP32 -> Q8 and FP32 -> Q4
 *   - Dequantize: Q8 -> FP32 and Q4 -> FP32
 *
 * Implementations benchmarked (when available):
 *   - Generic (scalar C)
 *   - AVX2 (256-bit vectors)
 *   - AVX-512 (512-bit vectors)
 *   - AMX (Intel Advanced Matrix Extensions)
 */

#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/export.h>
#include <linux/ktime.h>
#include <linux/random.h>
#include <linux/vmalloc.h>
#include <linux/printk.h>
#include <linux/string.h>
#include <linux/math64.h>
#include <linux/cache.h>
#include <linux/types.h>
#include <linux/stddef.h>
#include <linux/errno.h>
#include <linux/mm.h>
#include <linux/limits.h>
#include <linux/bitops.h>

#include "simd_impl.h"

/* ============================================
 * Module Information
 * ============================================ */
MODULE_LICENSE("GPL");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("Ainos x86 SIMD Benchmark Framework");
MODULE_VERSION("0.1.0");

/* ============================================
 * Benchmark Constants
 * ============================================ */

/* Number of warmup iterations to eliminate cache cold-start effects */
#define BENCHMARK_WARMUP_ITERS		5

/* Default number of measurement iterations */
#define BENCHMARK_DEFAULT_ITERS		20

/* Maximum number of implementations we can benchmark */
#define BENCHMARK_MAX_IMPLS		4

/* Maximum number of test sizes */
#define BENCHMARK_MAX_SIZES		6

/* Maximum total results: MAX_IMPLS * MAX_SIZES */
#define BENCHMARK_MAX_RESULTS		(BENCHMARK_MAX_IMPLS * BENCHMARK_MAX_SIZES)

/* Verification tolerance for floating-point comparison */
#define BENCHMARK_EPSILON		1e-5f

/* Number of nanoseconds in a microsecond */
#define NSEC_PER_USEC			1000UL

/* Number of nanoseconds in a millisecond */
#define NSEC_PER_MSEC			1000000UL

/* Cache line size for alignment hints */
#define CACHE_LINE_SIZE			64

/* Minimum measurement time in nanoseconds (to ensure accuracy) */
#define BENCHMARK_MIN_MEASURE_NS	1000000UL  /* 1 ms */

/* Maximum allowed iterations for safety */
#define BENCHMARK_MAX_ITERATIONS	1000

/* Quantization scale factor for tests */
#define BENCHMARK_QUANT_SCALE		127.0f

/* ============================================
 * Test Size Definitions
 * ============================================ */
static const int benchmark_sizes[BENCHMARK_MAX_SIZES] = {
	64, 128, 256, 512, 1024, 2048
};

static const char *benchmark_size_names[BENCHMARK_MAX_SIZES] = {
	"64", "128", "256", "512", "1024", "2048"
};

/* ============================================
 * Implementation Name Strings
 * ============================================ */
static const char *benchmark_impl_names[BENCHMARK_MAX_IMPLS] = {
	"generic", "AVX2", "AVX-512", "AMX"
};

/* ============================================
 * Internal Data Structures
 * ============================================ */

/**
 * struct benchmark_stats - Statistics for a set of measurements
 * @min:       Minimum measured value (ns)
 * @max:       Maximum measured value (ns)
 * @avg:       Average measured value (ns)
 * @median:    Median measured value (ns)
 * @stddev:    Standard deviation (ns)
 * @samples:   Number of valid samples
 */
struct benchmark_stats {
	unsigned long min;
	unsigned long max;
	unsigned long avg;
	unsigned long median;
	unsigned long stddev;
	int samples;
};

/**
 * struct benchmark_measurement - Complete measurement for one operation
 * @all_ns:    Array of per-iteration measurements (ns)
 * @count:     Number of valid measurements
 * @stats:     Computed statistics
 */
struct benchmark_measurement {
	unsigned long *all_ns;
	int count;
	struct benchmark_stats stats;
};

/**
 * struct benchmark_ops_set - All measurements for one impl at one size
 * @impl_name:    Implementation name
 * @size:         Test size
 * @matmul_ns:    Matmul measurement (ns)
 * @dot_ns:       Dot product measurement (ns)
 * @quant_ns:     Quantize measurement (ns) (avg of q8 and q4)
 * @dequant_ns:   Dequantize measurement (ns) (avg of q8 and q4)
 * @speedup:      Speedup factor vs generic
 */
struct benchmark_ops_set {
	const char *impl_name;
	int size;
	struct benchmark_measurement matmul;
	struct benchmark_measurement dot;
	struct benchmark_measurement quant;
	struct benchmark_measurement dequant;
	float speedup_vs_generic;
};

/**
 * struct benchmark_impl_entry - An implementation to benchmark
 * @ops:        SIMD ops descriptor
 * @name:       Implementation name
 * @available:  Whether this implementation is available on this CPU
 */
struct benchmark_impl_entry {
	const struct simd_ops *ops;
	const char *name;
	int available;
};

/**
 * struct benchmark_run_context - Context for a benchmark run
 * @iters:              Number of measurement iterations
 * @warmup:             Number of warmup iterations
 * @num_sizes:          Number of test sizes
 * @sizes:              Array of test sizes
 * @num_impls:          Number of implementations
 * @impls:              Array of implementation entries
 * @results:            Output results array
 * @max_results:        Maximum number of results
 * @result_count:       Number of results filled
 * @generic_matmul_ns:  Per-size generic matmul times for speedup
 * @generic_dot_ns:     Per-size generic dot times for speedup
 * @generic_quant_ns:   Per-size generic quantize times for speedup
 * @generic_dequant_ns: Per-size generic dequantize times for speedup
 */
struct benchmark_run_context {
	int iters;
	int warmup;
	int num_sizes;
	const int *sizes;
	int num_impls;
	struct benchmark_impl_entry *impls;
	struct simd_bench_result *results;
	int max_results;
	int result_count;
	unsigned long generic_matmul_ns[BENCHMARK_MAX_SIZES];
	unsigned long generic_dot_ns[BENCHMARK_MAX_SIZES];
	unsigned long generic_quant_ns[BENCHMARK_MAX_SIZES];
	unsigned long generic_dequant_ns[BENCHMARK_MAX_SIZES];
};

/* ============================================
 * Generic Reference Implementations
 * ============================================
 * These provide the scalar baseline against which all SIMD
 * implementations are compared. They match the implementations
 * in ai-vector-accel-main.c but are included here for
 * self-containment of the benchmark module.
 */

static void generic_matmul_fp32(int m, int n, int k,
				const float *a, const float *b, float *c)
{
	int i, j, p;

	for (i = 0; i < m; i++) {
		for (j = 0; j < n; j++) {
			float sum = 0.0f;
			for (p = 0; p < k; p++) {
				sum += a[i * (size_t)k + p]
				     * b[p * (size_t)n + j];
			}
			c[i * (size_t)n + j] = sum;
		}
	}
}

static float generic_dot_product(int n, const float *a, const float *b)
{
	float sum = 0.0f;
	int i;

	for (i = 0; i < n; i++)
		sum += a[i] * b[i];
	return sum;
}

static void generic_quantize_fp32_to_q8(int n, const float *src,
					void *dst, float scale)
{
	int8_t *dst8 = (int8_t *)dst;
	int i;

	for (i = 0; i < n; i++)
		dst8[i] = (int8_t)(src[i] * scale);
}

static void generic_quantize_fp32_to_q4(int n, const float *src,
					void *dst, float scale)
{
	uint8_t *dst4 = (uint8_t *)dst;
	int i;

	for (i = 0; i < n; i += 2) {
		int8_t v0 = (int8_t)(src[i] * scale);
		int8_t v1 = (int8_t)(src[i + 1] * scale);
		dst4[i / 2] = (uint8_t)((v0 & 0x0F) | ((v1 & 0x0F) << 4));
	}
}

static void generic_dequantize_q8_to_fp32(int n, const void *src,
					  float *dst, float scale)
{
	const int8_t *src8 = (const int8_t *)src;
	int i;

	for (i = 0; i < n; i++)
		dst[i] = (float)src8[i] / scale;
}

static void generic_dequantize_q4_to_fp32(int n, const void *src,
					  float *dst, float scale)
{
	const uint8_t *src4 = (const uint8_t *)src;
	int i;

	for (i = 0; i < n; i += 2) {
		uint8_t byte = src4[i / 2];
		dst[i] = (float)(int8_t)(byte & 0x0F) / scale;
		dst[i + 1] = (float)(int8_t)(byte >> 4) / scale;
	}
}

/* ============================================
 * Generic Implementation Ops Descriptor
 * ============================================
 * This ops descriptor wraps the generic implementations above.
 * It is used as the baseline for all speedup comparisons.
 */
static const struct simd_ops generic_ops = {
	.matmul_fp32		= generic_matmul_fp32,
	.dot_product		= generic_dot_product,
	.quantize_fp32_to_q8	= generic_quantize_fp32_to_q8,
	.quantize_fp32_to_q4	= generic_quantize_fp32_to_q4,
	.dequantize_q8_to_fp32	= generic_dequantize_q8_to_fp32,
	.dequantize_q4_to_fp32	= generic_dequantize_q4_to_fp32,
	.name			= "generic",
	.vector_size		= 0,
};

/* ============================================
 * Memory Allocation Helpers
 * ============================================ */

/**
 * benchmark_alloc_matrices - Allocate three matrices for benchmarking
 * @size: Matrix dimension (m = n = k = size)
 * @a:    Output pointer for matrix A (m x k)
 * @b:    Output pointer for matrix B (k x n)
 * @c:    Output pointer for matrix C (m x n)
 *
 * Allocates three square matrices of dimensions size x size.
 * Uses vmalloc for large allocations (> PAGE_SIZE), kmalloc otherwise.
 * Memory is zeroed on allocation.
 *
 * Return: 0 on success, -ENOMEM on failure (all allocations freed).
 */
static int benchmark_alloc_matrices(int size, float **a, float **b, float **c)
{
	size_t elem_count = (size_t)size * (size_t)size;
	size_t byte_count = elem_count * sizeof(float);

	/* Clear output pointers */
	*a = NULL;
	*b = NULL;
	*c = NULL;

	/* Validate size */
	if (size <= 0 || byte_count == 0)
		return -EINVAL;

	/* For large allocations, use vmalloc; for small, use kmalloc */
	if (byte_count > PAGE_SIZE) {
		*a = vmalloc(byte_count);
		*b = vmalloc(byte_count);
		*c = vmalloc(byte_count);
	} else {
		*a = kmalloc(byte_count, GFP_KERNEL);
		*b = kmalloc(byte_count, GFP_KERNEL);
		*c = kmalloc(byte_count, GFP_KERNEL);
	}

	/* Check for allocation failures */
	if (!*a || !*b || !*c) {
		if (*a) {
			if (byte_count > PAGE_SIZE)
				vfree(*a);
			else
				kfree(*a);
			*a = NULL;
		}
		if (*b) {
			if (byte_count > PAGE_SIZE)
				vfree(*b);
			else
				kfree(*b);
			*b = NULL;
		}
		if (*c) {
			if (byte_count > PAGE_SIZE)
				vfree(*c);
			else
				kfree(*c);
			*c = NULL;
		}
		return -ENOMEM;
	}

	return 0;
}

/**
 * benchmark_free_matrices - Free matrices allocated by benchmark_alloc_matrices
 * @a:    Matrix A
 * @b:    Matrix B
 * @c:    Matrix C
 * @size: Matrix dimension (used to determine allocation method)
 */
static void benchmark_free_matrices(float *a, float *b, float *c, int size)
{
	size_t byte_count = (size_t)size * (size_t)size * sizeof(float);

	if (a) {
		if (byte_count > PAGE_SIZE)
			vfree(a);
		else
			kfree(a);
	}
	if (b) {
		if (byte_count > PAGE_SIZE)
			vfree(b);
		else
			kfree(b);
	}
	if (c) {
		if (byte_count > PAGE_SIZE)
			vfree(c);
		else
			kfree(c);
	}
}

/**
 * benchmark_alloc_vector - Allocate a float vector of given length
 * @n:    Number of elements
 * @data: Output pointer for allocated vector
 *
 * Return: 0 on success, -ENOMEM on failure.
 */
static int benchmark_alloc_vector(int n, float **data)
{
	size_t byte_count = (size_t)n * sizeof(float);

	*data = NULL;

	if (n <= 0)
		return -EINVAL;

	if (byte_count > PAGE_SIZE)
		*data = vmalloc(byte_count);
	else
		*data = kmalloc(byte_count, GFP_KERNEL);

	if (!*data)
		return -ENOMEM;

	return 0;
}

/**
 * benchmark_free_vector - Free a vector allocated by benchmark_alloc_vector
 * @data: Vector to free
 * @n:    Number of elements (used to determine allocation method)
 */
static void benchmark_free_vector(float *data, int n)
{
	size_t byte_count = (size_t)n * sizeof(float);

	if (data) {
		if (byte_count > PAGE_SIZE)
			vfree(data);
		else
			kfree(data);
	}
}

/**
 * benchmark_alloc_quant_buffer - Allocate a buffer for quantized data
 * @n:            Number of elements
 * @data:         Output pointer for allocated buffer
 * @element_size: Size of each quantized element in bytes
 *
 * Return: 0 on success, -ENOMEM on failure.
 */
static int benchmark_alloc_quant_buffer(int n, void **data, size_t element_size)
{
	size_t byte_count = (size_t)n * element_size;

	*data = NULL;

	if (n <= 0 || element_size == 0)
		return -EINVAL;

	if (byte_count > PAGE_SIZE)
		*data = vmalloc(byte_count);
	else
		*data = kmalloc(byte_count, GFP_KERNEL);

	if (!*data)
		return -ENOMEM;

	return 0;
}

/**
 * benchmark_free_quant_buffer - Free a quantized buffer
 * @data:         Buffer to free
 * @n:            Number of elements
 * @element_size: Size of each quantized element in bytes
 */
static void benchmark_free_quant_buffer(void *data, int n, size_t element_size)
{
	size_t byte_count = (size_t)n * element_size;

	if (data) {
		if (byte_count > PAGE_SIZE)
			vfree(data);
		else
			kfree(data);
	}
}

/* ============================================
 * Random Data Fill Helpers
 * ============================================ */

/**
 * benchmark_fill_random - Fill a float array with random values in [-1.0, 1.0]
 * @data:  Pointer to float array
 * @count: Number of elements to fill
 *
 * Uses get_random_u32() for pseudo-random values.
 * The values are uniformly distributed in [-1.0, 1.0] using 24 bits
 * of mantissa for good distribution quality.
 */
static void benchmark_fill_random(float *data, int count)
{
	int i;

	for (i = 0; i < count; i++) {
		u32 rnd = get_random_u32();
		float val = (float)(int)(rnd & 0x00FFFFFF) / 8388608.0f;
		if (rnd & 0x80000000)
			val = -val;
		data[i] = val;
	}
}

/**
 * benchmark_fill_random_positive - Fill with positive random floats in [0, 1]
 * @data:  Pointer to float array
 * @count: Number of elements to fill
 */
static void benchmark_fill_random_positive(float *data, int count)
{
	int i;

	for (i = 0; i < count; i++) {
		u32 rnd = get_random_u32();
		float val = (float)(rnd & 0x00FFFFFF) / 16777216.0f;
		data[i] = val;
	}
}

/**
 * benchmark_fill_constant - Fill a float array with a constant value
 * @data:  Pointer to float array
 * @count: Number of elements to fill
 * @val:   Constant value to write
 */
static void benchmark_fill_constant(float *data, int count, float val)
{
	int i;

	for (i = 0; i < count; i++)
		data[i] = val;
}

/**
 * benchmark_fill_identity - Fill a square matrix as an identity matrix
 * @data: Pointer to float array representing a square matrix
 * @size: Matrix dimension (rows == columns)
 */
static void benchmark_fill_identity(float *data, int size)
{
	int i, j;

	for (i = 0; i < size; i++) {
		for (j = 0; j < size; j++)
			data[i * (size_t)size + j] = (i == j) ? 1.0f : 0.0f;
	}
}

/**
 * benchmark_fill_sequential - Fill with sequential values
 * @data:  Pointer to float array
 * @count: Number of elements to fill
 *
 * Useful for debugging and verification of deterministic behavior.
 */
static void benchmark_fill_sequential(float *data, int count)
{
	int i;

	for (i = 0; i < count; i++)
		data[i] = (float)(i % 997) / 100.0f;
}

/* ============================================
 * Verification Helpers
 * ============================================ */

/**
 * benchmark_verify_result - Verify matmul result against reference
 * @c:     Computed result matrix (SIMD)
 * @c_ref: Reference result matrix (generic)
 * @m:     Number of rows
 * @n:     Number of columns
 *
 * Checks that each element of c matches c_ref within BENCHMARK_EPSILON
 * relative error. Prints the first mismatch to kernel log.
 *
 * Return: 0 if all match, -EINVAL on first mismatch.
 */
static int benchmark_verify_result(const float *c, const float *c_ref,
				   int m, int n)
{
	int i, j;

	for (i = 0; i < m; i++) {
		for (j = 0; j < n; j++) {
			float diff;
			float ref_val = c_ref[i * (size_t)n + j];
			float c_val   = c[i * (size_t)n + j];

			/* Handle zero reference specially */
			if (ref_val == 0.0f) {
				if (c_val == 0.0f)
					continue;
				diff = (c_val > 0.0f) ? c_val : -c_val;
			} else {
				diff = (c_val - ref_val) / ref_val;
				if (diff < 0.0f)
					diff = -diff;
			}

			if (diff > BENCHMARK_EPSILON) {
				pr_warn("ainos-bench: Verify mismatch at "
					"[%d][%d]: expected %.6f, got %.6f "
					"(rel_diff=%e)\n",
					i, j, ref_val, c_val, (double)diff);
				return -EINVAL;
			}
		}
	}
	return 0;
}

/**
 * benchmark_verify_dot - Verify dot product result against reference
 * @result:   Computed dot product (SIMD)
 * @expected: Expected dot product (generic)
 *
 * Return: 0 if within tolerance, -EINVAL otherwise.
 */
static int benchmark_verify_dot(float result, float expected)
{
	float diff;

	if (expected == 0.0f) {
		if (result == 0.0f)
			return 0;
		diff = (result > 0.0f) ? result : -result;
	} else {
		diff = (result - expected) / expected;
		if (diff < 0.0f)
			diff = -diff;
	}

	if (diff > BENCHMARK_EPSILON) {
		pr_warn("ainos-bench: Dot product mismatch: "
			"expected %.6f, got %.6f (rel_diff=%e)\n",
			expected, result, (double)diff);
		return -EINVAL;
	}
	return 0;
}

/**
 * benchmark_verify_quantize - Verify quantize/dequantize roundtrip
 * @original:  Original float array before quantization
 * @recovered: Float array after quantize+dequantize
 * @n:         Number of elements
 *
 * Checks that quantize+dequantize roundtrip recovers values within
 * BENCHMARK_EPSILON relative error. Due to quantization loss, the
 * tolerance may need to be larger; this function uses a relaxed
 * epsilon for quantized comparisons.
 *
 * Return: 0 if all elements match within tolerance, -EINVAL otherwise.
 */
static int benchmark_verify_quantize(const float *original,
				     const float *recovered, int n)
{
	/*
	 * Quantization tolerance: Q8 has 7 bits of mantissa, Q4 has 3 bits.
	 * Use a relaxed epsilon for quantized comparisons.
	 */
	const float quant_epsilon = 1.0f / BENCHMARK_QUANT_SCALE;
	int i;

	for (i = 0; i < n; i++) {
		float diff;
		float orig = original[i];
		float rec  = recovered[i];

		/* Handle zero reference specially */
		if (orig == 0.0f) {
			if (rec == 0.0f)
				continue;
			diff = (rec > 0.0f) ? rec : -rec;
		} else {
			diff = (rec - orig) / orig;
			if (diff < 0.0f)
				diff = -diff;
		}

		if (diff > quant_epsilon) {
			pr_warn("ainos-bench: Quantize verify mismatch "
				"at [%d]: orig=%.6f rec=%.6f (rel_diff=%e)\n",
				i, orig, rec, (double)diff);
			return -EINVAL;
		}
	}
	return 0;
}

/* ============================================
 * Speedup Computation
 * ============================================ */

/**
 * benchmark_compute_speedup - Compute speedup factor of SIMD vs generic
 * @generic_time: Time taken by generic implementation (ns)
 * @simd_time:    Time taken by SIMD implementation (ns)
 *
 * Computes speedup = generic_time / simd_time.
 * A value > 1.0 means SIMD is faster; < 1.0 means SIMD is slower.
 *
 * Return: Speedup factor, 0.0 if either time is zero.
 */
static float benchmark_compute_speedup(unsigned long generic_time,
				       unsigned long simd_time)
{
	if (simd_time == 0 || generic_time == 0)
		return 0.0f;

	return (float)generic_time / (float)simd_time;
}

/* ============================================
 * Statistics Computation
 * ============================================ */

/**
 * benchmark_compute_stats - Compute statistics from measurement array
 * @values: Array of measured values (ns), will be sorted in place
 * @count:  Number of valid values
 * @stats:  Output statistics structure
 *
 * Computes min, max, average, median, and population standard deviation.
 * The values array is sorted in-place for median computation.
 */
static void benchmark_compute_stats(unsigned long *values, int count,
				    struct benchmark_stats *stats)
{
	unsigned long sum = 0;
	unsigned long sum_sq = 0;
	int i, j;

	/* Initialize */
	stats->min     = ULONG_MAX;
	stats->max     = 0;
	stats->avg     = 0;
	stats->median  = 0;
	stats->stddev  = 0;
	stats->samples = count;

	if (count <= 0)
		return;

	/* Compute min, max, sum */
	for (i = 0; i < count; i++) {
		unsigned long v = values[i];
		if (v < stats->min)
			stats->min = v;
		if (v > stats->max)
			stats->max = v;
		sum += v;
	}

	/* Compute average */
	stats->avg = div_u64(sum, count);

	/*
	 * Sort values for median and trimmed mean.
	 * Use simple insertion sort - count is small (<= 1000).
	 */
	for (i = 1; i < count; i++) {
		unsigned long key = values[i];
		j = i - 1;
		while (j >= 0 && values[j] > key) {
			values[j + 1] = values[j];
			j--;
		}
		values[j + 1] = key;
	}

	/* Compute median */
	if (count % 2 == 0) {
		stats->median = (values[count / 2 - 1] + values[count / 2]) / 2;
	} else {
		stats->median = values[count / 2];
	}

	/* Compute population standard deviation */
	for (i = 0; i < count; i++) {
		long long diff = (long long)values[i] - (long long)stats->avg;
		unsigned long sq = (diff < 0) ?
			(unsigned long)(-(long long)diff) :
			(unsigned long)diff;
		sum_sq += sq * sq;
	}
	stats->stddev = int_sqrt(div_u64(sum_sq, count));
}

/**
 * benchmark_print_stats - Print statistics to kernel log
 * @operation: Name of the operation being measured
 * @stats:     Statistics to print
 * @unit:      Unit string suffix (e.g., "ns", "us")
 */
static void benchmark_print_stats(const char *operation,
				  const struct benchmark_stats *stats,
				  const char *unit)
{
	pr_info("ainos-bench:   %s: min=%lu%s max=%lu%s avg=%lu%s "
		"median=%lu%s stddev=%lu%s samples=%d\n",
		operation,
		stats->min,  unit,
		stats->max,  unit,
		stats->avg,  unit,
		stats->median, unit,
		stats->stddev, unit,
		stats->samples);
}

/* ============================================
 * Measurement Primitives
 * ============================================ */

/**
 * benchmark_measure_begin - Start a high-precision measurement
 *
 * Return: Current timestamp in nanoseconds.
 */
static inline unsigned long benchmark_measure_begin(void)
{
	return (unsigned long)ktime_get_ns();
}

/**
 * benchmark_measure_end - End a measurement and compute elapsed time
 * @start_ns: Start timestamp from benchmark_measure_begin()
 *
 * Return: Elapsed time in nanoseconds (0 if start > end, which
 *         indicates a clock wraparound or error).
 */
static inline unsigned long benchmark_measure_end(unsigned long start_ns)
{
	unsigned long end_ns = (unsigned long)ktime_get_ns();

	if (end_ns > start_ns)
		return end_ns - start_ns;
	return 0;
}

/* ============================================
 * Per-Operation Benchmark Functions
 * ============================================ */

/**
 * benchmark_measure_matmul - Measure matmul time for one implementation
 * @impl:   SIMD ops descriptor
 * @m:      Matrix dimension M (rows of A and C)
 * @n:      Matrix dimension N (columns of B and C)
 * @k:      Matrix dimension K (columns of A, rows of B)
 * @a:      Matrix A (m x k)
 * @b:      Matrix B (k x n)
 * @c:      Matrix C output (m x n), zeroed before each iteration
 * @warmup: Number of warmup iterations (not measured)
 * @iters:  Number of measurement iterations
 * @meas:   Output measurement structure
 * @c_ref:  Reference result for verification (NULL to skip)
 *
 * Runs warmup iterations to eliminate cold-start effects, then
 * measures each iteration individually. Verifies against reference
 * if provided.
 *
 * Return: 0 on success, negative error code on failure.
 */
static int benchmark_measure_matmul(const struct simd_ops *impl,
				    int m, int n, int k,
				    const float *a, const float *b, float *c,
				    int warmup, int iters,
				    struct benchmark_measurement *meas,
				    const float *c_ref)
{
	int i, ret;
	unsigned long start;
	matmul_fp32_fn_t fn = impl->matmul_fp32;
	size_t c_size = (size_t)m * (size_t)n * sizeof(float);

	if (!fn)
		return -EINVAL;

	/* Allocate measurement array */
	meas->all_ns = kmalloc_array(iters, sizeof(unsigned long), GFP_KERNEL);
	if (!meas->all_ns)
		return -ENOMEM;

	meas->count = 0;

	/* Warmup phase: run iterations without measuring */
	for (i = 0; i < warmup; i++) {
		memset(c, 0, c_size);
		fn(m, n, k, a, b, c);
	}

	/* Measurement phase: time each iteration individually */
	for (i = 0; i < iters; i++) {
		/* Clear output matrix to avoid stale data effects */
		memset(c, 0, c_size);

		start = benchmark_measure_begin();
		fn(m, n, k, a, b, c);
		meas->all_ns[i] = benchmark_measure_end(start);
		meas->count++;
	}

	/* Compute statistics */
	benchmark_compute_stats(meas->all_ns, meas->count, &meas->stats);

	/* Verify against reference if provided */
	if (c_ref) {
		ret = benchmark_verify_result(c, c_ref, m, n);
		if (ret < 0) {
			pr_warn("ainos-bench: %s matmul size=%dx%d "
				"verification FAILED\n",
				impl->name, m, n);
		}
	}

	return 0;
}

/**
 * benchmark_measure_dot - Measure dot product time for one implementation
 * @impl:     SIMD ops descriptor
 * @n:        Vector length
 * @a:        Vector A
 * @b:        Vector B
 * @warmup:   Number of warmup iterations
 * @iters:    Number of measurement iterations
 * @meas:     Output measurement structure
 * @expected: Expected result for verification
 *
 * Return: 0 on success, negative error code on failure.
 */
static int benchmark_measure_dot(const struct simd_ops *impl,
				 int n, const float *a, const float *b,
				 int warmup, int iters,
				 struct benchmark_measurement *meas,
				 float expected)
{
	int i, ret;
	unsigned long start;
	dot_product_fn_t fn = impl->dot_product;
	float result = 0.0f;

	if (!fn)
		return -EINVAL;

	/* Allocate measurement array */
	meas->all_ns = kmalloc_array(iters, sizeof(unsigned long), GFP_KERNEL);
	if (!meas->all_ns)
		return -ENOMEM;

	meas->count = 0;

	/* Warmup phase */
	for (i = 0; i < warmup; i++) {
		result = fn(n, a, b);
		/* Prevent compiler from optimizing away the call */
		barrier();
	}

	/* Measurement phase */
	for (i = 0; i < iters; i++) {
		start = benchmark_measure_begin();
		result = fn(n, a, b);
		meas->all_ns[i] = benchmark_measure_end(start);
		meas->count++;
	}

	/* Compute statistics */
	benchmark_compute_stats(meas->all_ns, meas->count, &meas->stats);

	/* Verify against expected value */
	ret = benchmark_verify_dot(result, expected);
	if (ret < 0) {
		pr_warn("ainos-bench: %s dot product size=%d "
			"verification FAILED\n",
			impl->name, n);
	}

	return 0;
}

/**
 * benchmark_measure_quantize - Measure quantize time (avg of Q8 and Q4)
 * @impl:   SIMD ops descriptor
 * @n:      Number of elements
 * @src:    Source float array
 * @dst_q8: Destination Q8 buffer (int8_t)
 * @dst_q4: Destination Q4 buffer (uint8_t, packed)
 * @scale:  Quantization scale factor
 * @warmup: Number of warmup iterations
 * @iters:  Number of measurement iterations
 * @meas:   Output measurement structure
 *
 * Measures both Q8 and Q4 quantize operations and reports their
 * average time. This gives a single representative quantize metric.
 *
 * Return: 0 on success, negative error code on failure.
 */
static int benchmark_measure_quantize(const struct simd_ops *impl,
				      int n, const float *src,
				      void *dst_q8, void *dst_q4,
				      float scale,
				      int warmup, int iters,
				      struct benchmark_measurement *meas)
{
	int i;
	unsigned long start_q8, start_q4;
	unsigned long *q8_times, *q4_times;
	quantize_fn_t fn_q8 = impl->quantize_fp32_to_q8;
	quantize_fn_t fn_q4 = impl->quantize_fp32_to_q4;

	if (!fn_q8 || !fn_q4)
		return -EINVAL;

	/* Allocate measurement arrays */
	q8_times = kmalloc_array(iters, sizeof(unsigned long), GFP_KERNEL);
	q4_times = kmalloc_array(iters, sizeof(unsigned long), GFP_KERNEL);
	meas->all_ns = kmalloc_array(iters, sizeof(unsigned long), GFP_KERNEL);

	if (!q8_times || !q4_times || !meas->all_ns) {
		kfree(q8_times);
		kfree(q4_times);
		kfree(meas->all_ns);
		meas->all_ns = NULL;
		return -ENOMEM;
	}

	meas->count = 0;

	/* Warmup phase */
	for (i = 0; i < warmup; i++) {
		fn_q8(n, src, dst_q8, scale);
		fn_q4(n, src, dst_q4, scale);
	}

	/* Measurement phase */
	for (i = 0; i < iters; i++) {
		/* Measure Q8 quantize */
		start_q8 = benchmark_measure_begin();
		fn_q8(n, src, dst_q8, scale);
		q8_times[i] = benchmark_measure_end(start_q8);

		/* Measure Q4 quantize */
		start_q4 = benchmark_measure_begin();
		fn_q4(n, src, dst_q4, scale);
		q4_times[i] = benchmark_measure_end(start_q4);

		/* Average of Q8 and Q4 for this iteration */
		meas->all_ns[i] = (q8_times[i] + q4_times[i]) / 2;
		meas->count++;
	}

	/* Compute statistics on combined (averaged) times */
	benchmark_compute_stats(meas->all_ns, meas->count, &meas->stats);

	kfree(q8_times);
	kfree(q4_times);

	return 0;
}

/**
 * benchmark_measure_dequantize - Measure dequantize time (avg of Q8 and Q4)
 * @impl:    SIMD ops descriptor
 * @n:       Number of elements
 * @src_q8:  Source Q8 buffer (int8_t)
 * @src_q4:  Source Q4 buffer (uint8_t, packed)
 * @dst_q8:  Destination float array (from Q8 dequant)
 * @dst_q4:  Destination float array (from Q4 dequant)
 * @scale:   Dequantization scale factor
 * @warmup:  Number of warmup iterations
 * @iters:   Number of measurement iterations
 * @meas:    Output measurement structure
 *
 * Measures both Q8 and Q4 dequantize operations and reports their
 * average time. This gives a single representative dequantize metric.
 *
 * Return: 0 on success, negative error code on failure.
 */
static int benchmark_measure_dequantize(const struct simd_ops *impl,
					int n,
					const void *src_q8, const void *src_q4,
					float *dst_q8, float *dst_q4,
					float scale,
					int warmup, int iters,
					struct benchmark_measurement *meas)
{
	int i;
	unsigned long start_q8, start_q4;
	unsigned long *q8_times, *q4_times;
	dequantize_fn_t fn_q8 = impl->dequantize_q8_to_fp32;
	dequantize_fn_t fn_q4 = impl->dequantize_q4_to_fp32;

	if (!fn_q8 || !fn_q4)
		return -EINVAL;

	/* Allocate measurement arrays */
	q8_times = kmalloc_array(iters, sizeof(unsigned long), GFP_KERNEL);
	q4_times = kmalloc_array(iters, sizeof(unsigned long), GFP_KERNEL);
	meas->all_ns = kmalloc_array(iters, sizeof(unsigned long), GFP_KERNEL);

	if (!q8_times || !q4_times || !meas->all_ns) {
		kfree(q8_times);
		kfree(q4_times);
		kfree(meas->all_ns);
		meas->all_ns = NULL;
		return -ENOMEM;
	}

	meas->count = 0;

	/* Warmup phase */
	for (i = 0; i < warmup; i++) {
		fn_q8(n, src_q8, dst_q8, scale);
		fn_q4(n, src_q4, dst_q4, scale);
	}

	/* Measurement phase */
	for (i = 0; i < iters; i++) {
		/* Measure Q8 dequantize */
		start_q8 = benchmark_measure_begin();
		fn_q8(n, src_q8, dst_q8, scale);
		q8_times[i] = benchmark_measure_end(start_q8);

		/* Measure Q4 dequantize */
		start_q4 = benchmark_measure_begin();
		fn_q4(n, src_q4, dst_q4, scale);
		q4_times[i] = benchmark_measure_end(start_q4);

		/* Average of Q8 and Q4 for this iteration */
		meas->all_ns[i] = (q8_times[i] + q4_times[i]) / 2;
		meas->count++;
	}

	/* Compute statistics on combined (averaged) times */
	benchmark_compute_stats(meas->all_ns, meas->count, &meas->stats);

	kfree(q8_times);
	kfree(q4_times);

	return 0;
}

/* ============================================
 * Implementation Enumeration
 * ============================================ */

/**
 * benchmark_get_available_impls - Enumerate available implementations
 * @impls: Output array of implementation entries
 * @max:   Maximum number of entries that fit in the array
 *
 * Checks CPU features using the x86 feature detection macros from
 * simd_impl.h and populates the impls array with available ones.
 * The generic implementation (always available) is placed first.
 *
 * Return: Number of available implementations found.
 */
static int benchmark_get_available_impls(struct benchmark_impl_entry *impls,
					 int max)
{
	int count = 0;

	/* Generic implementation is always available */
	if (count < max) {
		impls[count].name	  = "generic";
		impls[count].ops	  = &generic_ops;
		impls[count].available	  = 1;
		count++;
	}

	/* Check for AVX2 */
	if (count < max && cpu_has_avx2()) {
		const struct simd_ops *ops = avx2_get_ops();
		if (ops) {
			impls[count].ops       = ops;
			impls[count].name      = ops->name;
			impls[count].available = 1;
			count++;
		}
	}

	/* Check for AVX-512 */
	if (count < max && cpu_has_avx512f()) {
		const struct simd_ops *ops = avx512_get_ops();
		if (ops) {
			impls[count].ops       = ops;
			impls[count].name      = ops->name;
			impls[count].available = 1;
			count++;
		}
	}

	/* Check for AMX */
	if (count < max && cpu_has_amx_tile()) {
		const struct simd_ops *ops = amx_get_ops();
		if (ops) {
			impls[count].ops       = ops;
			impls[count].name      = ops->name;
			impls[count].available = 1;
			count++;
		}
	}

	return count;
}

/* ============================================
 * Single-Size Benchmark Runner
 * ============================================ */

/**
 * benchmark_run_single_size - Run all operations for one impl at one size
 * @ctx:    Benchmark context
 * @impl:   Implementation entry to benchmark
 * @size:   Test size (square matrix dimension)
 * @result: Output result structure
 *
 * Allocates test data, runs matmul, dot product, quantize, and
 * dequantize measurements, verifies results against generic reference,
 * and computes speedup.
 *
 * Return: 0 on success, negative error code on failure.
 */
static int benchmark_run_single_size(struct benchmark_run_context *ctx,
				     const struct benchmark_impl_entry *impl,
				     int size,
				     struct simd_bench_result *result)
{
	float *a = NULL, *b = NULL, *c = NULL, *c_ref = NULL;
	float *vec_a = NULL, *vec_b = NULL;
	float *quant_src = NULL;
	float *dequant_dst_q8 = NULL, *dequant_dst_q4 = NULL;
	float *recovered_q8 = NULL, *recovered_q4 = NULL;
	void *quant_dst_q8 = NULL, *quant_dst_q4 = NULL;
	void *dequant_src_q8 = NULL, *dequant_src_q4 = NULL;
	int matmul_n = size;
	int matmul_m = size;
	int matmul_k = size;
	int vec_len = size;
	int quant_len = size * size;
	int ret = 0;
	float scale = BENCHMARK_QUANT_SCALE;
	const struct simd_ops *ops = impl->ops;
	struct benchmark_measurement matmul_meas;
	struct benchmark_measurement dot_meas;
	struct benchmark_measurement quant_meas;
	struct benchmark_measurement dequant_meas;

	/* Zero out measurement structures */
	memset(&matmul_meas, 0, sizeof(matmul_meas));
	memset(&dot_meas, 0, sizeof(dot_meas));
	memset(&quant_meas, 0, sizeof(quant_meas));
	memset(&dequant_meas, 0, sizeof(dequant_meas));

	/* Initialize result */
	memset(result, 0, sizeof(*result));
	result->impl_name = impl->name;
	result->size = size;

	/*
	 * Allocate matrices for matmul.
	 * A: m x k,  B: k x n,  C: m x n,  C_ref: m x n reference
	 */
	ret = benchmark_alloc_matrices(matmul_m, &a, &b, &c);
	if (ret < 0)
		goto out;

	/* Allocate reference result matrix (single matrix, size x size) */
	c_ref = NULL;
	{
		size_t ref_bytes = (size_t)matmul_m * (size_t)matmul_n * sizeof(float);
		if (ref_bytes > PAGE_SIZE)
			c_ref = vmalloc(ref_bytes);
		else
			c_ref = kmalloc(ref_bytes, GFP_KERNEL);
		if (!c_ref) {
			ret = -ENOMEM;
			goto out;
		}
	}

	/* Allocate vectors for dot product */
	ret = benchmark_alloc_vector(vec_len, &vec_a);
	if (ret < 0)
		goto out;
	ret = benchmark_alloc_vector(vec_len, &vec_b);
	if (ret < 0)
		goto out;

	/* Allocate arrays for quantize/dequantize */
	ret = benchmark_alloc_vector(quant_len, &quant_src);
	if (ret < 0)
		goto out;
	ret = benchmark_alloc_vector(quant_len, &dequant_dst_q8);
	if (ret < 0)
		goto out;
	ret = benchmark_alloc_vector(quant_len, &dequant_dst_q4);
	if (ret < 0)
		goto out;
	ret = benchmark_alloc_vector(quant_len, &recovered_q8);
	if (ret < 0)
		goto out;
	ret = benchmark_alloc_vector(quant_len, &recovered_q4);
	if (ret < 0)
		goto out;

	/* Allocate quantized buffers */
	ret = benchmark_alloc_quant_buffer(quant_len, &quant_dst_q8,
					   sizeof(int8_t));
	if (ret < 0)
		goto out;
	ret = benchmark_alloc_quant_buffer(quant_len, &quant_dst_q4,
					   sizeof(uint8_t));
	if (ret < 0)
		goto out;
	ret = benchmark_alloc_quant_buffer(quant_len, &dequant_src_q8,
					   sizeof(int8_t));
	if (ret < 0)
		goto out;
	ret = benchmark_alloc_quant_buffer(quant_len, &dequant_src_q4,
					   sizeof(uint8_t));
	if (ret < 0)
		goto out;

	/* Fill matrices with random data */
	benchmark_fill_random(a, matmul_m * matmul_k);
	benchmark_fill_random(b, matmul_k * matmul_n);
	benchmark_fill_random(vec_a, vec_len);
	benchmark_fill_random(vec_b, vec_len);
	benchmark_fill_random(quant_src, quant_len);

	/* Compute reference results using generic implementation */
	memset(c_ref, 0, (size_t)matmul_m * (size_t)matmul_n * sizeof(float));
	generic_ops.matmul_fp32(matmul_m, matmul_n, matmul_k, a, b, c_ref);

	/*
	 * Pre-quantize source data so we have valid quantized buffers
	 * for dequantize benchmarking. Use generic implementation for
	 * the reference quantized data.
	 */
	generic_ops.quantize_fp32_to_q8(quant_len, quant_src,
					dequant_src_q8, scale);
	generic_ops.quantize_fp32_to_q4(quant_len, quant_src,
					dequant_src_q4, scale);

	/* ============================================
	 * Benchmark Matrix Multiply
	 * ============================================ */
	if (ops->matmul_fp32) {
		ret = benchmark_measure_matmul(ops, matmul_m, matmul_n,
					       matmul_k, a, b, c,
					       ctx->warmup, ctx->iters,
					       &matmul_meas, c_ref);
		if (ret < 0) {
			pr_warn("ainos-bench: %s matmul size=%d "
				"failed (%d)\n", impl->name, size, ret);
			result->matmul_cycles = 0;
		} else {
			result->matmul_cycles = matmul_meas.stats.avg;
			pr_info("ainos-bench: %s matmul size=%d: "
				"avg=%lu ns (min=%lu max=%lu)\n",
				impl->name, size,
				matmul_meas.stats.avg,
				matmul_meas.stats.min,
				matmul_meas.stats.max);
		}
	} else {
		pr_warn("ainos-bench: %s has no matmul implementation\n",
			impl->name);
	}

	/* ============================================
	 * Benchmark Dot Product
	 * ============================================ */
	if (ops->dot_product) {
		float expected = generic_ops.dot_product(vec_len, vec_a, vec_b);

		ret = benchmark_measure_dot(ops, vec_len, vec_a, vec_b,
					    ctx->warmup, ctx->iters,
					    &dot_meas, expected);
		if (ret < 0) {
			pr_warn("ainos-bench: %s dot product size=%d "
				"failed (%d)\n", impl->name, size, ret);
			result->dot_cycles = 0;
		} else {
			result->dot_cycles = dot_meas.stats.avg;
			pr_info("ainos-bench: %s dot product size=%d: "
				"avg=%lu ns (min=%lu max=%lu)\n",
				impl->name, size,
				dot_meas.stats.avg,
				dot_meas.stats.min,
				dot_meas.stats.max);
		}
	} else {
		pr_warn("ainos-bench: %s has no dot product implementation\n",
			impl->name);
	}

	/* ============================================
	 * Benchmark Quantize (average of Q8 and Q4)
	 * ============================================ */
	if (ops->quantize_fp32_to_q8 && ops->quantize_fp32_to_q4) {
		ret = benchmark_measure_quantize(ops, quant_len, quant_src,
						 quant_dst_q8, quant_dst_q4,
						 scale,
						 ctx->warmup, ctx->iters,
						 &quant_meas);
		if (ret < 0) {
			pr_warn("ainos-bench: %s quantize size=%d "
				"failed (%d)\n", impl->name, size, ret);
			result->quantize_cycles = 0;
		} else {
			result->quantize_cycles = quant_meas.stats.avg;
			pr_info("ainos-bench: %s quantize size=%d: "
				"avg=%lu ns (min=%lu max=%lu)\n",
				impl->name, size,
				quant_meas.stats.avg,
				quant_meas.stats.min,
				quant_meas.stats.max);
		}
	} else {
		pr_warn("ainos-bench: %s has no quantize implementation\n",
			impl->name);
	}

	/* ============================================
	 * Benchmark Dequantize (average of Q8 and Q4)
	 * ============================================ */
	if (ops->dequantize_q8_to_fp32 && ops->dequantize_q4_to_fp32) {
		ret = benchmark_measure_dequantize(ops, quant_len,
						   dequant_src_q8,
						   dequant_src_q4,
						   dequant_dst_q8,
						   dequant_dst_q4, scale,
						   ctx->warmup, ctx->iters,
						   &dequant_meas);
		if (ret < 0) {
			pr_warn("ainos-bench: %s dequantize size=%d "
				"failed (%d)\n", impl->name, size, ret);
			result->dequantize_cycles = 0;
		} else {
			result->dequantize_cycles = dequant_meas.stats.avg;
			pr_info("ainos-bench: %s dequantize size=%d: "
				"avg=%lu ns (min=%lu max=%lu)\n",
				impl->name, size,
				dequant_meas.stats.avg,
				dequant_meas.stats.min,
				dequant_meas.stats.max);
		}
	} else {
		pr_warn("ainos-bench: %s has no dequantize implementation\n",
			impl->name);
	}

	/* Verify quantize/dequantize roundtrip for correctness */
	if (quant_dst_q8 && dequant_dst_q8) {
		generic_ops.dequantize_q8_to_fp32(quant_len, quant_dst_q8,
						  recovered_q8, scale);
		benchmark_verify_quantize(quant_src, recovered_q8, quant_len);
	}
	if (quant_dst_q4 && dequant_dst_q4) {
		generic_ops.dequantize_q4_to_fp32(quant_len, quant_dst_q4,
						  recovered_q4, scale);
		benchmark_verify_quantize(quant_src, recovered_q4, quant_len);
	}

	/* Compute speedup vs generic (if not generic itself) */
	if (strcmp(impl->name, "generic") != 0) {
		int s;
		unsigned long gen_matmul = 0, gen_dot = 0;
		unsigned long gen_quant = 0, gen_dequant = 0;

		/* Find generic times for this size */
		for (s = 0; s < ctx->num_sizes; s++) {
			if (ctx->sizes[s] == size) {
				gen_matmul  = ctx->generic_matmul_ns[s];
				gen_dot     = ctx->generic_dot_ns[s];
				gen_quant   = ctx->generic_quant_ns[s];
				gen_dequant = ctx->generic_dequant_ns[s];
				break;
			}
		}

		/* Compute per-operation speedups */
		{
			float sp_matmul  = 0.0f;
			float sp_dot     = 0.0f;
			float sp_quant   = 0.0f;
			float sp_dequant = 0.0f;

			if (result->matmul_cycles > 0 && gen_matmul > 0)
				sp_matmul = benchmark_compute_speedup(
					gen_matmul, result->matmul_cycles);

			if (result->dot_cycles > 0 && gen_dot > 0)
				sp_dot = benchmark_compute_speedup(
					gen_dot, result->dot_cycles);

			if (result->quantize_cycles > 0 && gen_quant > 0)
				sp_quant = benchmark_compute_speedup(
					gen_quant, result->quantize_cycles);

			if (result->dequantize_cycles > 0 && gen_dequant > 0)
				sp_dequant = benchmark_compute_speedup(
					gen_dequant, result->dequantize_cycles);

			/* Overall speedup: average of all four operations */
			result->speedup_vs_generic =
				(sp_matmul + sp_dot + sp_quant + sp_dequant) / 4.0f;
		}
	} else {
		/* Generic vs itself: speedup = 1.0 by definition */
		result->speedup_vs_generic = 1.0f;
	}

	ret = 0;

out:
	/* Free all allocated resources */
	if (a || b || c)
		benchmark_free_matrices(a, b, c, matmul_m);

	if (c_ref) {
		size_t ref_bytes = (size_t)matmul_m * (size_t)matmul_n *
				   sizeof(float);
		if (ref_bytes > PAGE_SIZE)
			vfree(c_ref);
		else
			kfree(c_ref);
	}

	if (vec_a)
		benchmark_free_vector(vec_a, vec_len);
	if (vec_b)
		benchmark_free_vector(vec_b, vec_len);
	if (quant_src)
		benchmark_free_vector(quant_src, quant_len);
	if (dequant_dst_q8)
		benchmark_free_vector(dequant_dst_q8, quant_len);
	if (dequant_dst_q4)
		benchmark_free_vector(dequant_dst_q4, quant_len);
	if (recovered_q8)
		benchmark_free_vector(recovered_q8, quant_len);
	if (recovered_q4)
		benchmark_free_vector(recovered_q4, quant_len);
	if (quant_dst_q8)
		benchmark_free_quant_buffer(quant_dst_q8, quant_len,
					    sizeof(int8_t));
	if (quant_dst_q4)
		benchmark_free_quant_buffer(quant_dst_q4, quant_len,
					    sizeof(uint8_t));
	if (dequant_src_q8)
		benchmark_free_quant_buffer(dequant_src_q8, quant_len,
					    sizeof(int8_t));
	if (dequant_src_q4)
		benchmark_free_quant_buffer(dequant_src_q4, quant_len,
					    sizeof(uint8_t));

	/* Free measurement arrays */
	kfree(matmul_meas.all_ns);
	kfree(dot_meas.all_ns);
	kfree(quant_meas.all_ns);
	kfree(dequant_meas.all_ns);

	return ret;
}

/* ============================================
 * Per-Implementation Benchmark Runner
 * ============================================ */

/**
 * benchmark_run_implementation - Run all sizes for one implementation
 * @ctx:  Benchmark context
 * @impl: Implementation entry to benchmark
 *
 * Runs benchmarks for all test sizes and stores results in the
 * context's results array. For the generic implementation, also
 * stores per-size times for speedup computation.
 *
 * Return: 0 on success, negative error code on failure.
 */
static int benchmark_run_implementation(struct benchmark_run_context *ctx,
					const struct benchmark_impl_entry *impl)
{
	int s, ret;
	int is_generic = (strcmp(impl->name, "generic") == 0);

	pr_info("ainos-bench: Benchmarking '%s' (%d iterations, "
		"%d warmup)...\n",
		impl->name, ctx->iters, ctx->warmup);

	for (s = 0; s < ctx->num_sizes; s++) {
		int size = ctx->sizes[s];

		if (ctx->result_count >= ctx->max_results) {
			pr_warn("ainos-bench: Result buffer full (%d/%d), "
				"stopping\n",
				ctx->result_count, ctx->max_results);
			break;
		}

		pr_info("ainos-bench:   size=%d...\n", size);

		ret = benchmark_run_single_size(ctx, impl, size,
						&ctx->results[ctx->result_count]);
		if (ret < 0) {
			pr_warn("ainos-bench: %s size=%d benchmark "
				"failed (%d), skipping\n",
				impl->name, size, ret);
			continue;
		}

		/* Store generic times for later speedup computation */
		if (is_generic) {
			ctx->generic_matmul_ns[s] =
				ctx->results[ctx->result_count].matmul_cycles;
			ctx->generic_dot_ns[s] =
				ctx->results[ctx->result_count].dot_cycles;
			ctx->generic_quant_ns[s] =
				ctx->results[ctx->result_count].quantize_cycles;
			ctx->generic_dequant_ns[s] =
				ctx->results[ctx->result_count].dequantize_cycles;
		}

		ctx->result_count++;
	}

	return 0;
}

/**
 * benchmark_run_implementation_fast - Run benchmarks using stored generic times
 * @ctx:  Benchmark context (generic times must already be populated)
 * @impl: Implementation entry to benchmark
 *
 * Same as benchmark_run_implementation but uses pre-computed generic
 * times for speedup calculation. This avoids re-computing generic
 * baselines for each SIMD implementation.
 *
 * Return: 0 on success, negative error code on failure.
 */
static int benchmark_run_implementation_fast(
		struct benchmark_run_context *ctx,
		const struct benchmark_impl_entry *impl)
{
	int s, ret;
	int idx;

	pr_info("ainos-bench: Benchmarking '%s'...\n", impl->name);

	for (s = 0; s < ctx->num_sizes; s++) {
		int size = ctx->sizes[s];

		if (ctx->result_count >= ctx->max_results) {
			pr_warn("ainos-bench: Result buffer full (%d/%d), "
				"stopping\n",
				ctx->result_count, ctx->max_results);
			break;
		}

		pr_info("ainos-bench:   size=%d...\n", size);

		ret = benchmark_run_single_size(ctx, impl, size,
						&ctx->results[ctx->result_count]);
		if (ret < 0) {
			pr_warn("ainos-bench: %s size=%d benchmark "
				"failed (%d), skipping\n",
				impl->name, size, ret);
			continue;
		}

		/* Recompute speedup using stored generic times */
		idx = ctx->result_count;
		{
			float sp_matmul  = 0.0f;
			float sp_dot     = 0.0f;
			float sp_quant   = 0.0f;
			float sp_dequant = 0.0f;

			if (ctx->generic_matmul_ns[s] > 0 &&
			    ctx->results[idx].matmul_cycles > 0)
				sp_matmul = benchmark_compute_speedup(
					ctx->generic_matmul_ns[s],
					ctx->results[idx].matmul_cycles);

			if (ctx->generic_dot_ns[s] > 0 &&
			    ctx->results[idx].dot_cycles > 0)
				sp_dot = benchmark_compute_speedup(
					ctx->generic_dot_ns[s],
					ctx->results[idx].dot_cycles);

			if (ctx->generic_quant_ns[s] > 0 &&
			    ctx->results[idx].quantize_cycles > 0)
				sp_quant = benchmark_compute_speedup(
					ctx->generic_quant_ns[s],
					ctx->results[idx].quantize_cycles);

			if (ctx->generic_dequant_ns[s] > 0 &&
			    ctx->results[idx].dequantize_cycles > 0)
				sp_dequant = benchmark_compute_speedup(
					ctx->generic_dequant_ns[s],
					ctx->results[idx].dequantize_cycles);

			ctx->results[idx].speedup_vs_generic =
				(sp_matmul + sp_dot + sp_quant + sp_dequant)
				/ 4.0f;
		}

		ctx->result_count++;
	}

	return 0;
}

/* ============================================
 * Static Storage for Benchmark Results
 * ============================================
 * These are used by simd_run_benchmarks and simd_print_benchmarks
 * to pass results between the two functions without requiring
 * the caller to manage the results array.
 */
static struct simd_bench_result *g_benchmark_results = NULL;
static int g_benchmark_count = 0;

/* ============================================
 * Main Benchmark Function
 * ============================================ */

/**
 * simd_run_benchmarks - Run all SIMD benchmarks
 * @iterations: Number of measurement iterations (0 = use default, 20)
 *
 * Runs benchmarks for all available SIMD implementations (generic,
 * AVX2, AVX-512, AMX) across all test sizes (64, 128, 256, 512,
 * 1024, 2048). For each combination, measures:
 *   - Matrix multiply (m=n=k=size)
 *   - Dot product (vector length = size)
 *   - Quantize (Q8 and Q4, averaged, array length = size^2)
 *   - Dequantize (Q8 and Q4, averaged, array length = size^2)
 *
 * Each measurement includes:
 *   - Warmup phase (5 iterations) to eliminate cache cold-start
 *   - Measurement phase (iterations count) with per-iteration timing
 *   - Statistics: min, max, average, median, standard deviation
 *   - Verification against generic reference
 *   - Speedup factor vs generic implementation
 *
 * Results are stored internally and can be printed via
 * simd_print_benchmarks().
 *
 * Return: Number of benchmark results on success (positive),
 *         negative error code on failure.
 */
int simd_run_benchmarks(int iterations)
{
	struct benchmark_impl_entry impls[BENCHMARK_MAX_IMPLS];
	struct simd_bench_result *results = NULL;
	struct benchmark_run_context ctx;
	int num_impls;
	int i, total_results;
	int ret = 0;

	/* Validate and sanitize iterations */
	if (iterations <= 0)
		iterations = BENCHMARK_DEFAULT_ITERS;
	if (iterations > BENCHMARK_MAX_ITERATIONS) {
		pr_warn("ainos-bench: Clamping iterations from %d to %d\n",
			iterations, BENCHMARK_MAX_ITERATIONS);
		iterations = BENCHMARK_MAX_ITERATIONS;
	}

	pr_info("ainos-bench: ==============================================="
		"=========\n");
	pr_info("ainos-bench: SIMD Performance Benchmark Suite\n");
	pr_info("ainos-bench: Iterations: %d (warmup: %d)\n",
		iterations, BENCHMARK_WARMUP_ITERS);
	pr_info("ainos-bench: ==============================================="
		"=========\n");

	/* Get available implementations */
	num_impls = benchmark_get_available_impls(impls, BENCHMARK_MAX_IMPLS);
	if (num_impls <= 0) {
		pr_err("ainos-bench: No implementations available\n");
		return -ENODEV;
	}

	pr_info("ainos-bench: Found %d implementation(s):", num_impls);
	for (i = 0; i < num_impls; i++)
		pr_cont(" %s", impls[i].name);
	pr_cont("\n");

	/* Calculate total results and allocate array */
	total_results = num_impls * BENCHMARK_NUM_SIZES;
	results = kcalloc(total_results, sizeof(struct simd_bench_result),
			  GFP_KERNEL);
	if (!results) {
		pr_err("ainos-bench: Failed to allocate results array "
		       "(%d entries)\n", total_results);
		return -ENOMEM;
	}

	/* Initialize context */
	memset(&ctx, 0, sizeof(ctx));
	ctx.iters       = iterations;
	ctx.warmup      = BENCHMARK_WARMUP_ITERS;
	ctx.num_sizes   = BENCHMARK_NUM_SIZES;
	ctx.sizes       = benchmark_sizes;
	ctx.num_impls   = num_impls;
	ctx.impls       = impls;
	ctx.results     = results;
	ctx.max_results = total_results;
	ctx.result_count = 0;

	/*
	 * First, run the generic implementation to establish baseline.
	 * Generic is always at index 0 (see benchmark_get_available_impls).
	 */
	if (num_impls > 0 && strcmp(impls[0].name, "generic") == 0) {
		pr_info("ainos-bench: ---------------------------------------"
			"-----------------\n");
		pr_info("ainos-bench: Establishing generic baseline...\n");

		ret = benchmark_run_implementation(&ctx, &impls[0]);
		if (ret < 0) {
			pr_err("ainos-bench: Generic benchmark failed (%d)\n",
			       ret);
			kfree(results);
			return ret;
		}
		pr_info("ainos-bench: Generic baseline complete: %d results\n",
			ctx.result_count);
	}

	/* Then run each SIMD implementation */
	for (i = 1; i < num_impls; i++) {
		if (!impls[i].available || !impls[i].ops) {
			pr_info("ainos-bench: %s not available, skipping\n",
				impls[i].name);
			continue;
		}

		pr_info("ainos-bench: ---------------------------------------"
			"-----------------\n");
		ret = benchmark_run_implementation_fast(&ctx, &impls[i]);
		if (ret < 0) {
			pr_warn("ainos-bench: %s benchmark returned %d, "
				"continuing\n", impls[i].name, ret);
		}
	}

	pr_info("ainos-bench: ==============================================="
		"=========\n");
	pr_info("ainos-bench: Benchmark complete: %d results\n",
		ctx.result_count);
	pr_info("ainos-bench: ==============================================="
		"=========\n");

	/*
	 * Store results globally for simd_print_benchmarks.
	 * Free any previous results first.
	 */
	kfree(g_benchmark_results);
	g_benchmark_results = results;
	g_benchmark_count   = ctx.result_count;

	return ctx.result_count;
}
EXPORT_SYMBOL_GPL(simd_run_benchmarks);

/* ============================================
 * Benchmark Result Printing
 * ============================================ */

/**
 * simd_print_benchmarks - Print benchmark results in a formatted table
 * @results: Array of benchmark results (NULL = use internal buffer)
 * @count:   Number of results (0 = use internal count)
 *
 * Formats and prints benchmark results as a table via pr_info.
 * If results is NULL, uses the internal buffer from the last
 * simd_run_benchmarks() call. If count is <= 0, uses the internal
 * count from the last simd_run_benchmarks() call.
 *
 * The table includes columns:
 *   Implementation, Size, Matmul (ns), Dot (ns), Quant (ns),
 *   Dequant (ns), Speedup
 */
void simd_print_benchmarks(const struct simd_bench_result *results, int count)
{
	const struct simd_bench_result *r;
	int i;

	/* Use internal buffer if no results provided */
	if (!results) {
		results = g_benchmark_results;
		count   = g_benchmark_count;
	}

	if (!results || count <= 0) {
		pr_info("ainos-bench: No benchmark results to print\n");
		return;
	}

	/* Print table header */
	pr_info("ainos-bench: ==============================================="
		"======================================================");
	pr_info("ainos-bench: SIMD Benchmark Results");
	pr_info("ainos-bench: ==============================================="
		"======================================================");
	pr_info("ainos-bench: %-12s %-6s %-14s %-14s %-14s %-14s %-8s",
		"Implement.", "Size", "Matmul(ns)", "Dot(ns)",
		"Quant(ns)", "Dequant(ns)", "Speedup");
	pr_info("ainos-bench: ------------- ------ -------------- "
		"-------------- -------------- -------------- --------");

	/* Print each result row */
	for (i = 0; i < count; i++) {
		r = &results[i];

		pr_info("ainos-bench: %-12s %-6d %-14lu %-14lu %-14lu %-14lu "
			"%-8.2f",
			r->impl_name ? r->impl_name : "unknown",
			r->size,
			r->matmul_cycles,
			r->dot_cycles,
			r->quantize_cycles,
			r->dequantize_cycles,
			r->speedup_vs_generic);
	}

	/* Print table footer */
	pr_info("ainos-bench: ------------- ------ -------------- "
		"-------------- -------------- -------------- --------");
	pr_info("ainos-bench: Total results: %d", count);
	pr_info("ainos-bench: ==============================================="
		"======================================================");
}
EXPORT_SYMBOL_GPL(simd_print_benchmarks);

/* ============================================
 * Summary Print Helper
 * ============================================ */

/**
 * simd_print_benchmark_summary - Print concise summary of results
 * @results: Array of benchmark results
 * @count:   Number of results
 *
 * Prints the best speedup per implementation along with average
 * speedup across all sizes. Useful for quick overview.
 */
static void simd_print_benchmark_summary(
		const struct simd_bench_result *results, int count)
{
	const struct simd_bench_result *r;
	int i;
	const char *current_impl = NULL;
	float best_speedup = 0.0f;
	int best_size = 0;
	int impl_result_count = 0;
	float sum_speedup = 0.0f;

	if (!results || count <= 0) {
		pr_info("ainos-bench: No benchmark results for summary\n");
		return;
	}

	pr_info("ainos-bench: ==============================================="
		"=========");
	pr_info("ainos-bench: Benchmark Summary");
	pr_info("ainos-bench: ==============================================="
		"=========");

	for (i = 0; i < count; i++) {
		r = &results[i];

		/* When implementation changes, print summary for previous */
		if (r->impl_name != current_impl && current_impl != NULL) {
			if (impl_result_count > 0) {
				pr_info("ainos-bench:   %-12s "
					"best speedup: %.2fx at size %d "
					"(avg: %.2fx across %d sizes)",
					current_impl,
					best_speedup,
					best_size,
					sum_speedup / impl_result_count,
					impl_result_count);
			}
			best_speedup = 0.0f;
			best_size = 0;
			sum_speedup = 0.0f;
			impl_result_count = 0;
		}

		current_impl = r->impl_name;

		if (r->speedup_vs_generic > best_speedup) {
			best_speedup = r->speedup_vs_generic;
			best_size = r->size;
		}
		sum_speedup += r->speedup_vs_generic;
		impl_result_count++;
	}

	/* Print summary for the last implementation */
	if (current_impl != NULL && impl_result_count > 0) {
		pr_info("ainos-bench:   %-12s best speedup: %.2fx at size %d "
			"(avg: %.2fx across %d sizes)",
			current_impl,
			best_speedup,
			best_size,
			sum_speedup / impl_result_count,
			impl_result_count);
	}

	pr_info("ainos-bench: ==============================================="
		"=========");
}

/* ============================================
 * CSV Export Helper
 * ============================================ */

/**
 * simd_print_benchmarks_csv - Print results in CSV format
 * @results: Array of benchmark results
 * @count:   Number of results
 *
 * Prints benchmark results in comma-separated format suitable for
 * import into spreadsheet applications. Output goes to kernel log.
 */
static void simd_print_benchmarks_csv(
		const struct simd_bench_result *results, int count)
{
	const struct simd_bench_result *r;
	int i;

	if (!results || count <= 0) {
		pr_info("ainos-bench: No benchmark results for CSV export\n");
		return;
	}

	pr_info("ainos-bench: CSV output:");
	pr_info("ainos-bench: Implementation,Size,Matmul_ns,"
		"Dot_ns,Quant_ns,Dequant_ns,Speedup");

	for (i = 0; i < count; i++) {
		r = &results[i];
		pr_info("ainos-bench: %s,%d,%lu,%lu,%lu,%lu,%.4f",
			r->impl_name ? r->impl_name : "unknown",
			r->size,
			r->matmul_cycles,
			r->dot_cycles,
			r->quantize_cycles,
			r->dequantize_cycles,
			r->speedup_vs_generic);
	}
}

/* ============================================
 * Benchmark Registration Function
 * ============================================ */

/**
 * simd_benchmark_register - Register and optionally run all benchmarks
 * @auto_run:   If non-zero, automatically run benchmarks and print results
 * @iterations: Number of iterations (0 = use default)
 *
 * Convenience function for use from other modules or init code.
 * When auto_run is set, runs benchmarks and prints formatted results
 * plus a summary.
 *
 * Return: Number of results on success, negative error code on failure.
 */
int simd_benchmark_register(int auto_run, int iterations)
{
	int count;

	pr_info("ainos-bench: Benchmark framework initialized\n");

	if (!auto_run) {
		pr_info("ainos-bench: Auto-run disabled, "
			"use simd_run_benchmarks() to execute\n");
		return 0;
	}

	/* Run benchmarks */
	count = simd_run_benchmarks(iterations);
	if (count < 0) {
		pr_err("ainos-bench: Benchmark run failed (%d)\n", count);
		return count;
	}

	/* Print formatted results table */
	simd_print_benchmarks(NULL, 0);

	/* Print concise summary */
	if (g_benchmark_results && g_benchmark_count > 0)
		simd_print_benchmark_summary(g_benchmark_results,
					     g_benchmark_count);

	/* Also print CSV for export */
	simd_print_benchmarks_csv(g_benchmark_results, g_benchmark_count);

	return count;
}
EXPORT_SYMBOL_GPL(simd_benchmark_register);

/* ============================================
 * Self-Test Function
 * ============================================ */

/**
 * simd_benchmark_self_test - Run quick correctness self-test
 *
 * Tests each available implementation on a small matrix (size=32)
 * to verify functional correctness. Does not perform detailed timing.
 * Tests matmul, dot product, and quantize/dequantize roundtrip.
 *
 * Return: 0 on success (all tests pass), negative error code on failure.
 */
static int simd_benchmark_self_test(void)
{
	struct benchmark_impl_entry impls[BENCHMARK_MAX_IMPLS];
	int num_impls;
	int i, ret = 0;
	int test_size = 32;
	int test_len = test_size * test_size;
	float *a = NULL, *b = NULL, *c = NULL, *c_ref = NULL;
	float *vec_a = NULL, *vec_b = NULL;
	float *q_src = NULL, *dq_dst = NULL;
	void *q_buf = NULL;
	const struct simd_ops *ops;
	float scale = BENCHMARK_QUANT_SCALE;
	int errors = 0;

	pr_info("ainos-bench: Running self-test (size=%d)...\n", test_size);

	num_impls = benchmark_get_available_impls(impls, BENCHMARK_MAX_IMPLS);
	if (num_impls <= 0) {
		pr_err("ainos-bench: No implementations for self-test\n");
		return -ENODEV;
	}

	/* Allocate test data */
	if (benchmark_alloc_matrices(test_size, &a, &b, &c) < 0) {
		pr_err("ainos-bench: Self-test matrix allocation failed\n");
		return -ENOMEM;
	}

	/* Allocate reference matrix */
	{
		size_t ref_bytes = (size_t)test_size * (size_t)test_size *
				   sizeof(float);
		if (ref_bytes > PAGE_SIZE)
			c_ref = vmalloc(ref_bytes);
		else
			c_ref = kmalloc(ref_bytes, GFP_KERNEL);
		if (!c_ref) {
			benchmark_free_matrices(a, b, c, test_size);
			return -ENOMEM;
		}
	}

	/* Allocate vectors and buffers */
	if (benchmark_alloc_vector(test_len, &vec_a) < 0) {
		benchmark_free_matrices(a, b, c, test_size);
		if (c_ref) {
			if ((size_t)test_size * test_size * sizeof(float) > PAGE_SIZE)
				vfree(c_ref);
			else
				kfree(c_ref);
		}
		return -ENOMEM;
	}
	vec_b = vec_a; /* Reuse for dot product */

	if (benchmark_alloc_vector(test_len, &q_src) < 0) {
		benchmark_free_matrices(a, b, c, test_size);
		if (c_ref) {
			size_t sz = (size_t)test_size * test_size * sizeof(float);
			if (sz > PAGE_SIZE) vfree(c_ref); else kfree(c_ref);
		}
		benchmark_free_vector(vec_a, test_len);
		return -ENOMEM;
	}
	if (benchmark_alloc_vector(test_len, &dq_dst) < 0) {
		benchmark_free_matrices(a, b, c, test_size);
		if (c_ref) {
			size_t sz = (size_t)test_size * test_size * sizeof(float);
			if (sz > PAGE_SIZE) vfree(c_ref); else kfree(c_ref);
		}
		benchmark_free_vector(vec_a, test_len);
		benchmark_free_vector(q_src, test_len);
		return -ENOMEM;
	}
	if (benchmark_alloc_quant_buffer(test_len, &q_buf, sizeof(int8_t)) < 0) {
		benchmark_free_matrices(a, b, c, test_size);
		if (c_ref) {
			size_t sz = (size_t)test_size * test_size * sizeof(float);
			if (sz > PAGE_SIZE) vfree(c_ref); else kfree(c_ref);
		}
		benchmark_free_vector(vec_a, test_len);
		benchmark_free_vector(q_src, test_len);
		benchmark_free_vector(dq_dst, test_len);
		return -ENOMEM;
	}

	/* Fill with random data */
	benchmark_fill_random(a, test_len);
	benchmark_fill_random(b, test_len);
	benchmark_fill_random(vec_a, test_len);
	benchmark_fill_random(q_src, test_len);

	/* Compute reference results using generic implementation */
	memset(c_ref, 0, (size_t)test_len * sizeof(float));
	generic_ops.matmul_fp32(test_size, test_size, test_size, a, b, c_ref);
	{
		float dot_ref = generic_ops.dot_product(test_len, vec_a, vec_a);

		/* Test each implementation */
		for (i = 0; i < num_impls; i++) {
			if (!impls[i].available)
				continue;

			if (strcmp(impls[i].name, "generic") == 0)
				ops = &generic_ops;
			else
				ops = impls[i].ops;

			if (!ops) {
				pr_warn("ainos-bench:   %s has no ops, "
					"skipping\n", impls[i].name);
				continue;
			}

			pr_info("ainos-bench:   Testing %s...\n",
				impls[i].name);

			/* Test matmul */
			if (ops->matmul_fp32) {
				memset(c, 0, (size_t)test_len * sizeof(float));
				ops->matmul_fp32(test_size, test_size,
						 test_size, a, b, c);
				if (benchmark_verify_result(c, c_ref,
							    test_size,
							    test_size) < 0) {
					pr_err("ainos-bench:   %s matmul "
					       "FAILED\n", impls[i].name);
					errors++;
				} else {
					pr_info("ainos-bench:   %s matmul "
						"PASS\n", impls[i].name);
				}
			}

			/* Test dot product */
			if (ops->dot_product) {
				float dot_val = ops->dot_product(test_len,
								vec_a, vec_a);
				if (benchmark_verify_dot(dot_val, dot_ref) < 0) {
					pr_err("ainos-bench:   %s dot product "
					       "FAILED\n", impls[i].name);
					errors++;
				} else {
					pr_info("ainos-bench:   %s dot product "
						"PASS\n", impls[i].name);
				}
			}

			/* Test quantize/dequantize Q8 roundtrip */
			if (ops->quantize_fp32_to_q8 &&
			    ops->dequantize_q8_to_fp32) {
				ops->quantize_fp32_to_q8(test_len, q_src,
							 q_buf, scale);
				ops->dequantize_q8_to_fp32(test_len, q_buf,
							   dq_dst, scale);
				if (benchmark_verify_quantize(q_src, dq_dst,
							      test_len) < 0) {
					pr_err("ainos-bench:   %s "
					       "quantize/dequantize Q8 "
					       "FAILED\n", impls[i].name);
					errors++;
				} else {
					pr_info("ainos-bench:   %s "
						"quantize/dequantize Q8 "
						"PASS\n", impls[i].name);
				}
			}
		}
	}

	/* Cleanup */
	benchmark_free_matrices(a, b, c, test_size);
	if (c_ref) {
		size_t sz = (size_t)test_size * test_size * sizeof(float);
		if (sz > PAGE_SIZE) vfree(c_ref); else kfree(c_ref);
	}
	benchmark_free_vector(vec_a, test_len);
	benchmark_free_vector(q_src, test_len);
	benchmark_free_vector(dq_dst, test_len);
	benchmark_free_quant_buffer(q_buf, test_len, sizeof(int8_t));

	if (errors == 0) {
		pr_info("ainos-bench: Self-test PASSED "
			"(all implementations correct)\n");
		return 0;
	}

	pr_err("ainos-bench: Self-test FAILED with %d error(s)\n", errors);
	return -EINVAL;
}

/* ============================================
 * Module Parameters
 * ============================================ */

static int bench_iterations = BENCHMARK_DEFAULT_ITERS;
module_param(bench_iterations, int, 0644);
MODULE_PARM_DESC(bench_iterations,
	"Number of benchmark measurement iterations (default: 20)");

static int bench_auto_run = 1;
module_param(bench_auto_run, int, 0644);
MODULE_PARM_DESC(bench_auto_run,
	"Run benchmarks automatically at module init (0=disable, 1=enable)");

static int bench_self_test = 0;
module_param(bench_self_test, int, 0644);
MODULE_PARM_DESC(bench_self_test,
	"Run self-test at module init to verify correctness "
	"(0=disable, 1=enable)");

static int bench_verbosity = 1;
module_param(bench_verbosity, int, 0644);
MODULE_PARM_DESC(bench_verbosity,
	"Output verbosity level (0=minimal, 1=normal, 2=verbose)");

/* ============================================
 * Module Init / Exit
 * ============================================ */

static int __init simd_benchmark_init(void)
{
	int ret = 0;

	pr_info("ainos-bench: x86 SIMD Benchmark Framework loading...\n");
	pr_info("ainos-bench: Parameters: iterations=%d auto_run=%d "
		"self_test=%d verbosity=%d\n",
		bench_iterations, bench_auto_run,
		bench_self_test, bench_verbosity);

	/* Run self-test if requested */
	if (bench_self_test) {
		pr_info("ainos-bench: Running self-test...\n");
		ret = simd_benchmark_self_test();
		if (ret < 0) {
			pr_warn("ainos-bench: Self-test failed (%d), "
				"continuing with benchmark\n", ret);
		}
	}

	/* Run benchmarks if auto-run is enabled */
	if (bench_auto_run) {
		ret = simd_benchmark_register(1, bench_iterations);
		if (ret < 0) {
			pr_err("ainos-bench: Benchmark registration failed "
			       "(%d)\n", ret);
			return ret;
		}
	} else {
		pr_info("ainos-bench: Auto-run disabled. "
			"Use simd_run_benchmarks() to run benchmarks.\n");
	}

	pr_info("ainos-bench: x86 SIMD Benchmark Framework loaded "
		"successfully\n");
	return 0;
}

static void __exit simd_benchmark_exit(void)
{
	pr_info("ainos-bench: x86 SIMD Benchmark Framework unloading...\n");

	/* Free internal benchmark results */
	kfree(g_benchmark_results);
	g_benchmark_results = NULL;
	g_benchmark_count  = 0;

	pr_info("ainos-bench: x86 SIMD Benchmark Framework unloaded\n");
}

module_init(simd_benchmark_init);
module_exit(simd_benchmark_exit);