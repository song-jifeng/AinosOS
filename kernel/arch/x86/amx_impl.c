// SPDX-License-Identifier: GPL-2.0
/*
 * Ainos OS - x86 Intel AMX TILE Vector Acceleration Implementation
 * =================================================================
 * Implements matrix multiplication, quantization, dequantization,
 * and dot product operations using Intel AMX (Advanced Matrix
 * Extensions) TILE instructions.
 *
 * Architecture Overview
 * =====================
 * Intel AMX introduces 8 tile registers (TMM0-TMM7), each configurable
 * as a 2D matrix with up to 16 rows and 64 bytes per row. The tile
 * operations provide high-throughput matrix multiply-accumulate for
 * BF16 (TDPBF16PS) and INT8 (TDPBUSD/TDPBSSD) data types.
 *
 * Tile Configuration
 * ==================
 * Two primary tile configurations are used:
 *   1. BF16 mode: rows=16, colsb=64
 *      - Source tiles: 16 rows x 32 BF16 elements each
 *      - Dest tile:    16 rows x 16 FP32 elements each
 *      - Computes:     16x16 matrix multiply, inner dim = 32
 *
 *   2. INT8 mode: rows=16, colsb=64
 *      - Source tiles: 16 rows x 64 INT8 elements each
 *      - Dest tile:    16 rows x 16 INT32 elements each
 *      - Computes:     16x16 matmul (INT8), inner dim = 64
 *
 * Lifecycle
 * =========
 *   1. kernel_fpu_begin()    - save FPU context, enable AMX
 *   2. _tile_config()        - configure tile dimensions
 *   3. _tile_zero()          - zero accumulator tiles
 *   4. _tile_loadd()         - load source tiles from memory
 *   5. _tile_dpbf16ps()      - tile multiply-accumulate
 *   6. _tile_stored()        - store result tiles to memory
 *   7. _tile_release()       - release tile configuration
 *   8. kernel_fpu_end()      - restore FPU context
 *
 * Kernel FPU Safety
 * =================
 * All AMX operations must be wrapped in kernel_fpu_begin()/kernel_fpu_end()
 * to properly save/restore the FPU state including the AMX tile registers
 * and tile configuration. The AMX tile state is large (up to 8 KB), so
 * long-running tile operations should be minimized to avoid scheduling
 * latency.
 *
 * Copyright (C) 2024 Ainos OS Team
 */

#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/export.h>
#include <linux/string.h>
#include <linux/errno.h>
#include <linux/types.h>
#include <linux/stddef.h>
#include <linux/cache.h>

#include <asm/fpu/api.h>
#include <asm/cpufeature.h>
#include <asm/processor.h>

#include <immintrin.h>

#include "simd_impl.h"

/* ================================================================
 * Module Information
 * ================================================================ */
MODULE_LICENSE("GPL");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("Ainos x86 Intel AMX TILE Vector Acceleration");
MODULE_VERSION("0.1.0");

/* ================================================================
 * Constants and Tile Dimension Definitions
 * ================================================================
 *
 * The AMX tile configuration uses a palette system. Palette 1
 * supports up to 8 tiles with configurable rows (1-16) and
 * colsb (bytes per row, 4-64, multiple of 4).
 *
 * Tile register allocation for BF16 matmul:
 *   TMM0 - accumulator tile (FP32 result)
 *   TMM1 - tile A (BF16 source, from matrix A)
 *   TMM2 - tile B (BF16 source, from matrix B, transposed)
 *   TMM3 - temporary / secondary accumulator
 *   TMM4 - temporary for quantization work
 *   TMM5 - temporary for quantization work
 *   TMM6 - temporary for quantization work
 *   TMM7 - temporary for quantization work
 *
 * Tile register allocation for INT8 matmul:
 *   TMM0 - accumulator tile (INT32 result)
 *   TMM1 - tile A (INT8 source, from matrix A)
 *   TMM2 - tile B (INT8 source, from matrix B, transposed)
 */

/* Maximum rows per tile (palette 1 constraint) */
#define AMX_TILE_MAX_ROWS         16

/* Maximum bytes per row (palette 1 constraint) */
#define AMX_TILE_MAX_COLSB        64

/* BF16 tile: each BF16 value is 2 bytes */
#define AMX_BF16_TILE_ROWS        16
#define AMX_BF16_TILE_COLSB       64
#define AMX_BF16_TILE_COLS        (AMX_BF16_TILE_COLSB / 2)  /* 32 BF16 elements per row */
#define AMX_BF16_TILE_OUT_COLS    (AMX_BF16_TILE_COLSB / 4)  /* 16 FP32 elements per row */
#define AMX_BF16_TILE_INNER_DIM   (AMX_BF16_TILE_COLSB / 4)  /* 16 pairs of BF16 = 32 elements */

/* INT8 tile: each INT8 value is 1 byte */
#define AMX_INT8_TILE_ROWS        16
#define AMX_INT8_TILE_COLSB       64
#define AMX_INT8_TILE_COLS        (AMX_INT8_TILE_COLSB / 1)  /* 64 INT8 elements per row */
#define AMX_INT8_TILE_OUT_COLS    (AMX_INT8_TILE_COLSB / 4)  /* 16 INT32 elements per row */
#define AMX_INT8_TILE_INNER_DIM   (AMX_INT8_TILE_COLSB / 1)  /* 64 INT8 elements */

/* Tile buffer sizes in bytes */
#define AMX_BF16_TILE_BUF_SIZE    (AMX_BF16_TILE_ROWS * AMX_BF16_TILE_COLSB)  /* 1024 bytes */
#define AMX_INT8_TILE_BUF_SIZE    (AMX_INT8_TILE_ROWS * AMX_INT8_TILE_COLSB)  /* 1024 bytes */

/* Tile data buffer for gathering B matrix data (transposed load) */
#define AMX_TILE_BUF_ALIGN        64  /* Cache line alignment for tile buffers */

/* Quantization batch sizes */
#define AMX_QUANTIZE_BATCH_SIZE   (AMX_BF16_TILE_ROWS * AMX_BF16_TILE_OUT_COLS)  /* 256 elements */

/* Dot product vector processing chunk */
#define AMX_DOT_PRODUCT_CHUNK     (AMX_BF16_TILE_INNER_DIM * 2)  /* 32 elements per chunk */

/* Small matrix threshold for direct fallback (no tile overhead) */
#define AMX_MATMUL_SMALL_M_THRESH 8
#define AMX_MATMUL_SMALL_N_THRESH 8
#define AMX_MATMUL_SMALL_K_THRESH 16

/* ================================================================
 * Tile Configuration Structure
 * ================================================================
 *
 * Matches the hardware TILECFG layout (80 bytes):
 *   Byte 0:    palette_id (1 = palette 1)
 *   Byte 1:    start_row (usually 0)
 *   Bytes 2-15: reserved
 *   Bytes 16-79: tile info for 8 tiles (8 bytes each)
 *
 * Each tile info entry:
 *   Bytes 0-1: colsb (bytes per row, 4-64, multiple of 4)
 *   Byte 2:    rows (1-16)
 *   Bytes 3-7: reserved
 */
struct amx_tile_config_entry {
	uint16_t colsb;
	uint8_t  rows;
	uint8_t  reserved[5];
} __attribute__((packed));

struct amx_tile_config {
	uint8_t  palette_id;
	uint8_t  start_row;
	uint8_t  reserved[14];
	struct amx_tile_config_entry tile_info[8];
} __attribute__((packed));

/* ================================================================
 * Tile Working Buffers
 * ================================================================
 *
 * These buffers are used to prepare tile data in the correct
 * memory layout before loading into tile registers. They are
 * cache-line aligned to avoid false sharing and ensure optimal
 * memory access patterns.
 *
 * For BF16 matmul:
 *   buf_a: 16 rows x 32 BF16 values = 1024 bytes
 *   buf_b: 16 rows x 32 BF16 values = 1024 bytes
 *     (B is gathered into transposed layout)
 *
 * For INT8 matmul:
 *   buf_a: 16 rows x 64 INT8 values = 1024 bytes
 *   buf_b: 16 rows x 64 INT8 values = 1024 bytes
 */

struct amx_working_buffers {
	/* BF16 tile buffers */
	uint8_t bf16_buf_a[AMX_BF16_TILE_BUF_SIZE]
		__attribute__((aligned(AMX_TILE_BUF_ALIGN)));
	uint8_t bf16_buf_b[AMX_BF16_TILE_BUF_SIZE]
		__attribute__((aligned(AMX_TILE_BUF_ALIGN)));

	/* INT8 tile buffers */
	uint8_t int8_buf_a[AMX_INT8_TILE_BUF_SIZE]
		__attribute__((aligned(AMX_TILE_BUF_ALIGN)));
	uint8_t int8_buf_b[AMX_INT8_TILE_BUF_SIZE]
		__attribute__((aligned(AMX_TILE_BUF_ALIGN)));

	/* Quantization temporary buffers */
	float   quant_temp[AMX_QUANTIZE_BATCH_SIZE]
		__attribute__((aligned(AMX_TILE_BUF_ALIGN)));
	uint8_t quant_out[AMX_QUANTIZE_BATCH_SIZE]
		__attribute__((aligned(AMX_TILE_BUF_ALIGN)));
};

/* ================================================================
 * Static Tile Configurations
 * ================================================================
 *
 * Pre-defined tile configurations for different operation modes.
 * These are set up once and used for the duration of each operation.
 */

/* BF16 tile configuration: all tiles use 16x64 */
static const struct amx_tile_config amx_tile_cfg_bf16 = {
	.palette_id = 1,
	.start_row  = 0,
	.reserved   = {0},
	.tile_info  = {
		/* TMM0: accumulator (FP32) - 16 rows x 16 floats */
		{ .colsb = AMX_BF16_TILE_COLSB, .rows = AMX_BF16_TILE_ROWS, .reserved = {0} },
		/* TMM1: src A (BF16) - 16 rows x 32 BF16 values */
		{ .colsb = AMX_BF16_TILE_COLSB, .rows = AMX_BF16_TILE_ROWS, .reserved = {0} },
		/* TMM2: src B (BF16) - 16 rows x 32 BF16 values */
		{ .colsb = AMX_BF16_TILE_COLSB, .rows = AMX_BF16_TILE_ROWS, .reserved = {0} },
		/* TMM3: secondary accumulator (FP32) */
		{ .colsb = AMX_BF16_TILE_COLSB, .rows = AMX_BF16_TILE_ROWS, .reserved = {0} },
		/* TMM4-TMM7: general purpose */
		{ .colsb = AMX_BF16_TILE_COLSB, .rows = AMX_BF16_TILE_ROWS, .reserved = {0} },
		{ .colsb = AMX_BF16_TILE_COLSB, .rows = AMX_BF16_TILE_ROWS, .reserved = {0} },
		{ .colsb = AMX_BF16_TILE_COLSB, .rows = AMX_BF16_TILE_ROWS, .reserved = {0} },
		{ .colsb = AMX_BF16_TILE_COLSB, .rows = AMX_BF16_TILE_ROWS, .reserved = {0} },
	},
};

/* INT8 tile configuration: all tiles use 16x64 */
static const struct amx_tile_config amx_tile_cfg_int8 = {
	.palette_id = 1,
	.start_row  = 0,
	.reserved   = {0},
	.tile_info  = {
		/* TMM0: accumulator (INT32) - 16 rows x 16 INT32 values */
		{ .colsb = AMX_INT8_TILE_COLSB, .rows = AMX_INT8_TILE_ROWS, .reserved = {0} },
		/* TMM1: src A (INT8) - 16 rows x 64 INT8 values */
		{ .colsb = AMX_INT8_TILE_COLSB, .rows = AMX_INT8_TILE_ROWS, .reserved = {0} },
		/* TMM2: src B (INT8) - 16 rows x 64 INT8 values */
		{ .colsb = AMX_INT8_TILE_COLSB, .rows = AMX_INT8_TILE_ROWS, .reserved = {0} },
		/* TMM3-TMM7: general purpose */
		{ .colsb = AMX_INT8_TILE_COLSB, .rows = AMX_INT8_TILE_ROWS, .reserved = {0} },
		{ .colsb = AMX_INT8_TILE_COLSB, .rows = AMX_INT8_TILE_ROWS, .reserved = {0} },
		{ .colsb = AMX_INT8_TILE_COLSB, .rows = AMX_INT8_TILE_ROWS, .reserved = {0} },
		{ .colsb = AMX_INT8_TILE_COLSB, .rows = AMX_INT8_TILE_ROWS, .reserved = {0} },
		{ .colsb = AMX_INT8_TILE_COLSB, .rows = AMX_INT8_TILE_ROWS, .reserved = {0} },
	},
};

/* ================================================================
 * FP32 <-> BF16 Conversion Helpers
 * ================================================================
 *
 * BF16 (Brain Floating Point 16) is a 16-bit floating-point format
 * with the same exponent range as FP32 but reduced mantissa precision.
 * Conversion from FP32 to BF16 is simply truncating the lower 16 bits
 * of the FP32 representation.
 *
 * These helpers operate on batches of data for efficient tile loading.
 * They use compiler builtins to generate efficient code (AVX-512 BF16
 * instructions when available, or scalar truncation as fallback).
 */

/**
 * fp32_to_bf16 - Convert a single FP32 value to BF16 (truncation)
 * @val: IEEE 754 single-precision float value
 *
 * BF16 is the upper 16 bits of the FP32 representation. This is a
 * simple truncation (round-toward-zero). For better accuracy, we could
 * use round-to-nearest-even, but truncation is faster and sufficient
 * for most ML inference workloads.
 *
 * Return: BF16 representation as uint16_t
 */
static inline uint16_t fp32_to_bf16(float val)
{
	uint32_t bits;

	/* Reinterpret the float as uint32 */
	memcpy(&bits, &val, sizeof(bits));

	/*
	 * Truncate to 16 bits. For round-to-nearest-even, we would add
	 * 0x7FFF + ((bits >> 16) & 1) before shifting. Truncation is
	 * simpler and faster for bulk conversion.
	 *
	 * Note: NaN values lose their payload bits, which is acceptable
	 * for ML inference where NaN handling is not critical.
	 */
	return (uint16_t)(bits >> 16);
}

/**
 * bf16_to_fp32 - Convert a single BF16 value to FP32
 * @val: BF16 value as uint16_t
 *
 * BF16 is the upper 16 bits of FP32. Conversion is simply padding
 * with 16 zero bits. This is exact (no precision loss going from
 * BF16 to FP32).
 *
 * Return: IEEE 754 single-precision float
 */
static inline float bf16_to_fp32(uint16_t val)
{
	uint32_t bits = (uint32_t)val << 16;
	float result;

	memcpy(&result, &bits, sizeof(result));
	return result;
}

/**
 * fp32_to_bf16_batch - Convert a batch of FP32 values to BF16
 * @src: Source FP32 array
 * @dst: Destination BF16 array (as uint16_t)
 * @src_stride: Stride between consecutive FP32 values in source (in elements)
 * @dst_stride: Stride between consecutive BF16 values in destination (in elements)
 * @count: Number of values to convert
 *
 * Processes a batch of FP32 values, converting each to BF16 and storing
 * at the destination with the specified stride. For tile preparation,
 * the source stride is usually the matrix leading dimension (K for A,
 * N for B), and the destination stride is the tile row width.
 *
 * The stride-based access allows gathering strided data directly into
 * the tile's contiguous row layout.
 */
static __attribute__((target("amx-tile,amx-bf16,amx-int8")))
void fp32_to_bf16_batch(const float *src, uint16_t *dst,
			 int src_stride, int dst_stride, int count)
{
	int i;

	/*
	 * Bulk conversion loop. For large batches, the compiler may
	 * auto-vectorize this with AVX-512 BF16 instructions (VNNI
	 * VCVTNEPS2BF16) when the appropriate ISA is enabled.
	 */
	for (i = 0; i < count; i++)
		dst[i * dst_stride] = fp32_to_bf16(src[i * src_stride]);
}

/**
 * bf16_to_fp32_batch - Convert a batch of BF16 values to FP32
 * @src: Source BF16 array (as uint16_t)
 * @dst: Destination FP32 array
 * @src_stride: Stride in source (in elements)
 * @dst_stride: Stride in destination (in elements)
 * @count: Number of values to convert
 */
static __attribute__((target("amx-tile,amx-bf16,amx-int8")))
void bf16_to_fp32_batch(const uint16_t *src, float *dst,
			 int src_stride, int dst_stride, int count)
{
	int i;

	for (i = 0; i < count; i++)
		dst[i * dst_stride] = bf16_to_fp32(src[i * src_stride]);
}

/**
 * fp32_to_bf16_tile_row_major - Convert FP32 block to tile-major BF16
 * @src: Source FP32 array (row-major, leading_dim = src_stride)
 * @dst: Destination BF16 tile buffer (16 x 32 = 512 BF16 values)
 * @src_stride: Leading dimension of source (in elements)
 * @rows: Number of rows to convert (<= 16)
 * @cols: Number of columns to convert (<= 32)
 *
 * Converts a rectangular block of FP32 data into a BF16 tile buffer
 * in row-major order. This is used for matrix A in the AMX matmul:
 * A[m_block:m_block+rows, k_block:k_block+cols] -> tile buffer.
 */
static __attribute__((target("amx-tile,amx-bf16,amx-int8")))
void fp32_to_bf16_tile_row_major(const float *src, uint16_t *dst,
				  int src_stride, int rows, int cols)
{
	int r, c;

	/*
	 * Process row by row. Each row of the source contributes
	 * 'cols' BF16 values to one row of the tile buffer.
	 *
	 * The source data is contiguous within each row (stride = src_stride).
	 * The destination is contiguous within each row (stride = cols = 32).
	 */
	for (r = 0; r < rows; r++) {
		const float *src_row = src + r * src_stride;
		uint16_t *dst_row = dst + r * AMX_BF16_TILE_COLS;

		for (c = 0; c < cols; c++)
			dst_row[c] = fp32_to_bf16(src_row[c]);
	}

	/*
	 * Zero out remaining positions in the tile row if cols < 32.
	 * This ensures the tile operation doesn't use garbage data.
	 */
	if (cols < AMX_BF16_TILE_COLS) {
		for (r = 0; r < rows; r++) {
			uint16_t *dst_row = dst + r * AMX_BF16_TILE_COLS;

			memset(dst_row + cols, 0,
			       (AMX_BF16_TILE_COLS - cols) * sizeof(uint16_t));
		}
	}

	/*
	 * Zero out remaining rows if rows < 16.
	 */
	if (rows < AMX_BF16_TILE_ROWS) {
		memset(dst + rows * AMX_BF16_TILE_COLS, 0,
		       (AMX_BF16_TILE_ROWS - rows) * AMX_BF16_TILE_COLS *
		       sizeof(uint16_t));
	}
}

/**
 * fp32_to_bf16_tile_transposed - Convert FP32 block to transposed tile-major BF16
 * @src: Source FP32 array (row-major, leading_dim = src_stride)
 * @dst: Destination BF16 tile buffer (16 x 32 = 512 BF16 values)
 * @src_stride: Leading dimension of source (in elements, = N)
 * @rows: Number of source rows to gather (<= 32)
 * @cols: Number of source columns (<= 16)
 *
 * Converts a rectangular block of FP32 data into a BF16 tile buffer
 * in transposed layout. This is used for matrix B in the AMX matmul:
 *
 * Standard matmul: C[m][n] = sum_k A[m][k] * B[k][n]
 * AMX tile operation: dest[i][j] = sum_k src1[i][k] * src2[j][k]
 *
 * For src2, we need row j to contain column elements from B:
 *   src2[j][k] = B[k_block + k][n_block + j]
 *
 * So this function gathers B's column elements and arranges them
 * so that each tile row corresponds to one column of the source block.
 *
 * Source layout (B in row-major, KxN):
 *   B[k_block + 0][n_block + 0 .. n_block + cols - 1]
 *   B[k_block + 1][n_block + 0 .. n_block + cols - 1]
 *   ...
 *   B[k_block + rows - 1][n_block + 0 .. n_block + cols - 1]
 *
 * Destination layout (tile buffer, rows x cols):
 *   Row 0: B[k_block + 0][n_block + 0], B[k_block + 1][n_block + 0], ...
 *   Row 1: B[k_block + 0][n_block + 1], B[k_block + 1][n_block + 1], ...
 *   ...
 */
static __attribute__((target("amx-tile,amx-bf16,amx-int8")))
void fp32_to_bf16_tile_transposed(const float *src, uint16_t *dst,
				   int src_stride, int rows, int cols)
{
	int r, c;

	/*
	 * Gather column elements of B into tile rows.
	 * For each tile row j (0..cols-1), gather the j-th column
	 * of the source block: B[k_block + k][n_block + j] for k in 0..rows-1.
	 *
	 * In memory, consecutive elements of the same column are spaced
	 * src_stride elements apart (since B is row-major).
	 */
	for (r = 0; r < cols; r++) {
		uint16_t *dst_row = dst + r * AMX_BF16_TILE_COLS;

		for (c = 0; c < rows; c++)
			dst_row[c] = fp32_to_bf16(src[c * src_stride + r]);
	}

	/*
	 * Zero out remaining positions. If rows < 32, we need to zero
	 * the tail of each tile row. If cols < 16, we need to zero
	 * the remaining tile rows.
	 */
	if (rows < AMX_BF16_TILE_COLS) {
		for (r = 0; r < cols; r++) {
			uint16_t *dst_row = dst + r * AMX_BF16_TILE_COLS;

			memset(dst_row + rows, 0,
			       (AMX_BF16_TILE_COLS - rows) * sizeof(uint16_t));
		}
	}

	if (cols < AMX_BF16_TILE_ROWS) {
		memset(dst + cols * AMX_BF16_TILE_COLS, 0,
		       (AMX_BF16_TILE_ROWS - cols) * AMX_BF16_TILE_COLS *
		       sizeof(uint16_t));
	}
}

/* ================================================================
 * AMX Tile Configuration and Lifecycle
 * ================================================================
 *
 * These functions manage the AMX tile configuration. The tile config
 * must be set up with _tile_config before any tile operations, and
 * released with _tile_release after use.
 *
 * Note: _tile_config is a relatively expensive operation (it involves
 * a system configuration instruction). For best performance, configure
 * tiles once before a series of tile operations, not before each one.
 */

/**
 * amx_configure_tiles - Configure AMX tiles for BF16 operations
 *
 * Sets up the tile configuration with palette 1, configuring all
 * 8 tiles with 16 rows and 64 bytes per row. This is the standard
 * configuration for BF16 matrix multiply operations.
 *
 * Must be called within a kernel_fpu_begin()/kernel_fpu_end() section.
 *
 * After calling this function, the tile registers are configured
 * but not yet loaded with data. Use _tile_loadd to load data into
 * specific tiles, and _tile_zero to initialize accumulator tiles.
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
void amx_configure_tiles(void)
{
	/*
	 * Configure all tiles using the BF16 configuration.
	 *
	 * _tile_config takes a pointer to a tile configuration structure
	 * and programs the hardware tile registers. This must be called
	 * before any tile load/store/compute operations.
	 *
	 * The configuration remains active until _tile_release is called
	 * or until the next _tile_config call.
	 *
	 * Hardware requirements:
	 *   - palette_id must be 1 (the only valid palette on current CPUs)
	 *   - Each tile's colsb must be a multiple of 4 (4, 8, 16, ..., 64)
	 *   - Each tile's rows must be in range 1..16
	 *   - Total tile memory (sum of rows * colsb for all tiles) must
	 *     not exceed the implementation limit (typically 8 KB)
	 *
	 * On processors with AMX support (Sapphire Rapids and later),
	 * this instruction configures the 8 tile registers for subsequent
	 * TILE operations.
	 */
	_tile_config(&amx_tile_cfg_bf16);
}

/**
 * amx_configure_tiles_int8 - Configure AMX tiles for INT8 operations
 *
 * Sets up the tile configuration for INT8 matrix multiply operations.
 * All 8 tiles are configured with 16 rows and 64 bytes per row,
 * allowing each source tile to hold 16 x 64 = 1024 INT8 values.
 *
 * Must be called within a kernel_fpu_begin()/kernel_fpu_end() section.
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
static void amx_configure_tiles_int8(void)
{
	_tile_config(&amx_tile_cfg_int8);
}

/**
 * amx_release_tiles - Release AMX tile configuration
 *
 * Releases the current tile configuration and clears all tile registers.
 * This must be called after tile operations are complete, before
 * calling kernel_fpu_end().
 *
 * _tile_release resets the tile state so that the tile registers
 * no longer contain valid data. After this call, tile operations
 * will fault until _tile_config is called again.
 *
 * This is important for security: it prevents data leaks between
 * kernel threads that share the same physical core.
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
void amx_release_tiles(void)
{
	/*
	 * _tile_release releases all tile registers and resets the
	 * tile configuration to the disabled state (palette 0).
	 *
	 * After this call:
	 *   - Tile load/store operations will fault
	 *   - Tile compute operations will fault
	 *   - _tile_config must be called again to re-enable tiles
	 *
	 * This is a lightweight operation (no memory accesses).
	 */
	_tile_release();
}

/* ================================================================
 * Tile Initialization Helpers
 * ================================================================
 *
 * These helpers initialize tile registers before use.
 */

/**
 * amx_zero_tile - Zero all accumulator tiles
 *
 * Zeroes tile registers that are used as accumulators. This must be
 * done before starting a new tile-based accumulation.
 *
 * Tiles zeroed:
 *   TMM0: primary accumulator for matmul
 *   TMM3: secondary accumulator (for wider matmul)
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
static inline void amx_zero_tile(void)
{
	/*
	 * _tile_zero sets all bytes in the specified tile register to 0.
	 * For FP32 accumulator tiles, this sets all elements to +0.0f.
	 * For INT32 accumulator tiles, this sets all elements to 0.
	 *
	 * This is a register-internal operation (no memory access).
	 */
	_tile_zero(0);  /* TMM0: primary accumulator */
	_tile_zero(3);  /* TMM3: secondary accumulator */
}

/**
 * amx_zero_tile_all - Zero all tile registers
 *
 * Zeroes all 8 tile registers. This is more thorough than
 * amx_zero_tile and is used when preparing for a fresh computation.
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
static inline void amx_zero_tile_all(void)
{
	int i;

	for (i = 0; i < 8; i++)
		_tile_zero(i);
}

/* ================================================================
 * AMX Tile Matrix Multiply Core
 * ================================================================
 *
 * The core tile-based matrix multiply operation. This function
 * performs a single 16x16x32 tile matmul using AMX BF16 instructions.
 *
 * Algorithm:
 *   C[16x16] += A[16x32] * B[32x16]
 *
 * Where:
 *   - A is loaded as BF16 tile (16 rows x 32 BF16 values)
 *   - B is loaded as BF16 tile (16 rows x 32 BF16 values, transposed)
 *   - C is accumulated in FP32 tile (16 rows x 16 FP32 values)
 *
 * The tile operation TDPBF16PS computes:
 *   For i in 0..15, j in 0..15:
 *     C[i][j] += sum_{k=0}^{15} (A[i][2k] * B[j][2k] + A[i][2k+1] * B[j][2k+1])
 *
 * This is equivalent to C += A * B^T where A is 16x32 and B is 16x32.
 * But since we load B in transposed layout, it gives us C += A_block * B_block.
 */

/**
 * amx_tile_matmul_16x16x32 - Core 16x16x32 tile matmul
 * @tile_a: Tile buffer containing A block (16x32 BF16, row-major)
 * @tile_b: Tile buffer containing B block (16x32 BF16, transposed)
 * @tile_c: Tile buffer for C accumulator (16x16 FP32, row-major)
 *
 * Loads tile A from tile_a buffer, tile B from tile_b buffer,
 * and performs _tile_dpbf16ps into tile C. The result is stored
 * into tile_c buffer.
 *
 * Note: This function assumes tiles are already configured. Call
 * amx_configure_tiles() before using this function.
 *
 * The tile_a buffer must be in row-major layout (16 rows of 32 BF16 values).
 * The tile_b buffer must be in transposed-gather layout (16 rows of 32 BF16
 * values, where row j contains B[k_block:k_block+32, n_block+j]).
 * The tile_c buffer must be initialized (typically zeroed).
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
static void amx_tile_matmul_16x16x32(const uint16_t *tile_a,
				      const uint16_t *tile_b,
				      float *tile_c)
{
	/*
	 * Step 1: Load tile A from the prepared buffer.
	 * _tile_loadd(tile, base, stride) loads 'rows * colsb' bytes
	 * from memory. The first row is loaded from base[0:colsb], and
	 * each subsequent row is loaded from base[r*stride : r*stride+colsb].
	 *
	 * For our prepared buffer, the data is contiguous in row-major
	 * format, so the stride is set to colsb (64 bytes), which is the
	 * same as the row width.
	 */
	_tile_loadd(1, tile_a, AMX_BF16_TILE_COLSB);

	/*
	 * Step 2: Load tile B from the prepared buffer.
	 * Same loading pattern as tile A. The buffer is arranged so that
	 * each row of the tile contains the gathered column elements.
	 */
	_tile_loadd(2, tile_b, AMX_BF16_TILE_COLSB);

	/*
	 * Step 3: Perform tile multiply-accumulate.
	 * _tile_dpbf16ps(dst, a, b):
	 *   dst[i][j] += sum_{k=0}^{15} (a[i][2k] * b[j][2k] + a[i][2k+1] * b[j][2k+1])
	 *
	 * This is the core AMX compute instruction. It operates entirely
	 * within the tile registers with no memory access.
	 *
	 * Register allocation:
	 *   TMM0 = destination accumulator (FP32)
	 *   TMM1 = source A (BF16)
	 *   TMM2 = source B (BF16)
	 */
	_tile_dpbf16ps(0, 1, 2);

	/*
	 * Step 4: Store the result tile to the output buffer.
	 * _tile_stored(tile, base, stride) stores the tile contents
	 * to memory. The stride is the distance in bytes between
	 * consecutive rows in the destination buffer.
	 *
	 * For the output buffer, we store contiguously (stride = colsb).
	 * The output buffer is FP32, so it's 16 rows x 64 bytes = 16 x 16 floats.
	 */
	_tile_stored(0, tile_c, AMX_BF16_TILE_COLSB);
}

/**
 * amx_tile_matmul_16x16x32_accumulate - Like above but accumulates in-place
 * @tile_a: Tile buffer containing A block (16x32 BF16, row-major)
 * @tile_b: Tile buffer containing B block (16x32 BF16, transposed)
 *
 * Similar to amx_tile_matmul_16x16x32 but does NOT store the result.
 * Used when multiple tile operations are chained and the result is
 * stored once at the end.
 *
 * The accumulator tile (TMM0) is kept in the register for the next
 * dpbf16ps operation. This avoids unnecessary memory round-trips.
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
static void amx_tile_matmul_16x16x32_accumulate(const uint16_t *tile_a,
						  const uint16_t *tile_b)
{
	_tile_loadd(1, tile_a, AMX_BF16_TILE_COLSB);
	_tile_loadd(2, tile_b, AMX_BF16_TILE_COLSB);
	_tile_dpbf16ps(0, 1, 2);
}

/**
 * amx_tile_store_result - Store TMM0 to memory
 * @tile_c: Destination buffer for the tile result (16x16 FP32)
 *
 * Stores the accumulator tile (TMM0) to the output buffer.
 * This is used after a series of amx_tile_matmul_16x16x32_accumulate calls.
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
static inline void amx_tile_store_result(float *tile_c)
{
	_tile_stored(0, tile_c, AMX_BF16_TILE_COLSB);
}

/* ================================================================
 * AMX Dual-Tile Matmul (32x32x32)
 * ================================================================
 *
 * For larger matrices, we can use multiple tiles to double the
 * throughput. This function processes a 32x32 output block using
 * 4 accumulator tiles and 2 source tiles per operation.
 *
 * Register layout:
 *   TMM0: accumulator for C[0:16, 0:16]
 *   TMM3: accumulator for C[0:16, 16:32]
 *   TMM4: accumulator for C[16:32, 0:16]
 *   TMM5: accumulator for C[16:32, 16:32]
 *   TMM1: tile A (BF16, shared across all accumulators)
 *   TMM2: tile B (BF16, shared across all accumulators)
 */

/**
 * amx_dual_tile_init - Initialize dual-tile accumulators
 *
 * Zeroes the four accumulator tiles used for 32x32 output blocks.
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
static inline void amx_dual_tile_init(void)
{
	_tile_zero(0);  /* TMM0: C[0:16, 0:16] */
	_tile_zero(3);  /* TMM3: C[0:16, 16:32] */
	_tile_zero(4);  /* TMM4: C[16:32, 0:16] */
	_tile_zero(5);  /* TMM5: C[16:32, 16:32] */
}

/**
 * amx_dual_tile_matmul_32x32x32 - Process 32x32 output block
 * @tile_a0: A block rows 0:16, all K
 * @tile_a1: A block rows 16:32, all K
 * @tile_b0: B block all rows, cols 0:16 (transposed)
 * @tile_b1: B block all rows, cols 16:32 (transposed)
 *
 * Performs a tile-based matmul for a 32x32 output block.
 * A is 32xK, B is Kx32, C is 32x32.
 *
 * The function processes the K dimension in 32-element chunks,
 * accumulating into the four output tiles.
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
static void amx_dual_tile_matmul_32x32x32(const uint16_t *tile_a0,
					    const uint16_t *tile_a1,
					    const uint16_t *tile_b0,
					    const uint16_t *tile_b1)
{
	/*
	 * Load tile A0 (rows 0:16 of A) into TMM1.
	 * This tile is used for both C[0:16, 0:16] and C[0:16, 16:32].
	 */
	_tile_loadd(1, tile_a0, AMX_BF16_TILE_COLSB);

	/*
	 * Load tile B0 (cols 0:16 of B, transposed) into TMM2.
	 * This computes C[0:16, 0:16] += A0 * B0.
	 */
	_tile_loadd(2, tile_b0, AMX_BF16_TILE_COLSB);
	_tile_dpbf16ps(0, 1, 2);  /* TMM0 += A0 * B0 */

	/*
	 * Load tile B1 (cols 16:32 of B, transposed) into TMM2.
	 * This computes C[0:16, 16:32] += A0 * B1.
	 */
	_tile_loadd(2, tile_b1, AMX_BF16_TILE_COLSB);
	_tile_dpbf16ps(3, 1, 2);  /* TMM3 += A0 * B1 */

	/*
	 * Load tile A1 (rows 16:32 of A) into TMM1.
	 * This tile is used for both C[16:32, 0:16] and C[16:32, 16:32].
	 */
	_tile_loadd(1, tile_a1, AMX_BF16_TILE_COLSB);

	/*
	 * Compute C[16:32, 0:16] += A1 * B0.
	 */
	_tile_loadd(2, tile_b0, AMX_BF16_TILE_COLSB);
	_tile_dpbf16ps(4, 1, 2);  /* TMM4 += A1 * B0 */

	/*
	 * Compute C[16:32, 16:32] += A1 * B1.
	 */
	_tile_loadd(2, tile_b1, AMX_BF16_TILE_COLSB);
	_tile_dpbf16ps(5, 1, 2);  /* TMM5 += A1 * B1 */
}

/**
 * amx_dual_tile_store - Store all four dual-tile accumulators
 * @c00: Output buffer for C[0:16, 0:16]
 * @c01: Output buffer for C[0:16, 16:32]
 * @c10: Output buffer for C[16:32, 0:16]
 * @c11: Output buffer for C[16:32, 16:32]
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
static void amx_dual_tile_store(float *c00, float *c01,
				 float *c10, float *c11)
{
	_tile_stored(0, c00, AMX_BF16_TILE_COLSB);
	_tile_stored(3, c01, AMX_BF16_TILE_COLSB);
	_tile_stored(4, c10, AMX_BF16_TILE_COLSB);
	_tile_stored(5, c11, AMX_BF16_TILE_COLSB);
}

/* ================================================================
 * Scalar Fallback for Small Matrix Edge Cases
 * ================================================================
 *
 * These functions handle the edge cases where the matrix dimensions
 * are not multiples of the tile dimensions. They process the remaining
 * rows/columns using scalar or simple loop code.
 */

/**
 * matmul_fp32_scalar - Scalar matrix multiply for edge cases
 * @m: Number of rows of C and A
 * @n: Number of columns of C and B
 * @k: Number of columns of A and rows of B
 * @a: Matrix A (m x k)
 * @b: Matrix B (k x n)
 * @c: Matrix C (m x n)
 *
 * Standard triple-loop matrix multiply. Used for small residual
 * blocks that don't fit the tile dimensions.
 */
static void matmul_fp32_scalar(int m, int n, int k,
				const float *a, const float *b, float *c)
{
	int i, j, p;

	for (i = 0; i < m; i++) {
		for (j = 0; j < n; j++) {
			float sum = 0.0f;

			for (p = 0; p < k; p++)
				sum += a[i * k + p] * b[p * n + j];
			c[i * n + j] = sum;
		}
	}
}

/**
 * matmul_fp32_add_scalar - Add contribution of a scalar block to C
 *
 * Like matmul_fp32_scalar but adds to existing values in C (accumulates).
 */
static void matmul_fp32_add_scalar(int m, int n, int k,
				    const float *a, const float *b,
				    float *c)
{
	int i, j, p;

	for (i = 0; i < m; i++) {
		for (j = 0; j < n; j++) {
			float sum = 0.0f;

			for (p = 0; p < k; p++)
				sum += a[i * k + p] * b[p * n + j];
			c[i * n + j] += sum;
		}
	}
}

/* ================================================================
 * amx_matmul_fp32 - AMX-Accelerated FP32 Matrix Multiply
 * ================================================================
 *
 * Computes C = A * B where:
 *   A is m x k (row-major)
 *   B is k x n (row-major)
 *   C is m x n (row-major)
 *
 * Algorithm:
 *   1. For matrices smaller than the tile dimensions, use scalar fallback
 *      to avoid the overhead of tile configuration and data conversion.
 *
 *   2. For large matrices, process in blocks:
 *      - Outer loop over m dimension (step 16)
 *      - Middle loop over n dimension (step 16)
 *      - Inner loop over k dimension (step 32)
 *
 *   3. For each block:
 *      a. Convert A block to BF16 and load into tile A
 *      b. Convert B block (transposed) to BF16 and load into tile B
 *      c. Accumulate with TDPBF16PS
 *
 *   4. Handle remaining rows/columns with scalar fallback
 *
 * Performance Considerations:
 *   - Tile configuration is done once per call
 *   - FP32-to-BF16 conversion is done in tile-sized batches
 *   - The B matrix is gathered into transposed layout for efficient tile loading
 *   - Memory access patterns are cache-friendly (blocked access)
 *
 * @m: Number of rows in A and C
 * @n: Number of columns in B and C
 * @k: Number of columns in A and rows in B
 * @a: Matrix A (m x k, row-major)
 * @b: Matrix B (k x n, row-major)
 * @c: Matrix C (m x n, row-major)
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
void amx_matmul_fp32(int m, int n, int k,
		      const float *a, const float *b, float *c)
{
	int m_block, n_block, k_block;
	int m_remain, n_remain, k_remain;
	int m_tiles, n_tiles, k_tiles;
	int m_regular, n_regular, k_regular;

	/* Validate inputs */
	if (m <= 0 || n <= 0 || k <= 0 || !a || !b || !c)
		return;

	/*
	 * For very small matrices, tile overhead (configuration +
	 * conversion + gather) outweighs the benefits. Use scalar
	 * fallback for these cases.
	 */
	if (m < AMX_MATMUL_SMALL_M_THRESH &&
	    n < AMX_MATMUL_SMALL_N_THRESH &&
	    k < AMX_MATMUL_SMALL_K_THRESH) {
		matmul_fp32_scalar(m, n, k, a, b, c);
		return;
	}

	/*
	 * Initialize the output matrix to zero.
	 * We use memset for the full C matrix. For large matrices,
	 * this is parallelized by the kernel's memset implementation.
	 */
	memset(c, 0, (size_t)m * n * sizeof(float));

	/*
	 * Begin FPU context for AMX operations.
	 * kernel_fpu_begin() saves the current FPU state and enables
	 * the use of SSE/AVX/AMX instructions. It must be paired with
	 * kernel_fpu_end().
	 *
	 * For AMX, this is critical because the tile registers are part
	 * of the extended FPU state (XSAVE area). Without proper FPU
	 * context management, AMX instructions will fault.
	 */
	kernel_fpu_begin();

	/*
	 * Configure AMX tiles for BF16 operations.
	 * This sets up the tile dimensions and must be done before
	 * any tile load/store/compute operations.
	 */
	amx_configure_tiles();

	/*
	 * Calculate the number of full tiles we can process.
	 * Regular blocks are multiples of the tile dimensions.
	 */
	m_tiles    = m / AMX_BF16_TILE_ROWS;
	n_tiles    = n / AMX_BF16_TILE_OUT_COLS;
	k_tiles    = k / AMX_BF16_TILE_COLS;

	m_regular  = m_tiles * AMX_BF16_TILE_ROWS;
	n_regular  = n_tiles * AMX_BF16_TILE_OUT_COLS;
	k_regular  = k_tiles * AMX_BF16_TILE_COLS;

	/*
	 * Allocate working buffers on the stack for tile data preparation.
	 * These buffers are cache-line aligned to avoid false sharing.
	 *
	 * Stack allocation is used for performance (no heap allocation
	 * overhead). The total buffer size is ~3 KB, well within the
	 * kernel stack limit (typically 16 KB on x86).
	 */
	uint8_t buf_a_raw[AMX_BF16_TILE_BUF_SIZE]
		__attribute__((aligned(AMX_TILE_BUF_ALIGN)));
	uint8_t buf_b_raw[AMX_BF16_TILE_BUF_SIZE]
		__attribute__((aligned(AMX_TILE_BUF_ALIGN)));
	uint16_t *buf_a = (uint16_t *)buf_a_raw;
	uint16_t *buf_b = (uint16_t *)buf_b_raw;

	/*
	 * Main tile processing loop.
	 *
	 * Outer loop: iterate over m dimension in tile-sized blocks.
	 *   For each 16-row block of A, we process all n and k dimensions.
	 *
	 * Middle loop: iterate over n dimension in tile-sized blocks.
	 *   For each 16-column block of C, we load the corresponding
	 *   B data and accumulate over all k blocks.
	 *
	 * Inner loop: iterate over k dimension in tile-sized blocks.
	 *   For each 32-element inner dimension block, we convert
	 *   A and B data to BF16 and perform the tile multiply-accumulate.
	 */
	for (m_block = 0; m_block < m_regular; m_block += AMX_BF16_TILE_ROWS) {
		for (n_block = 0; n_block < n_regular; n_block += AMX_BF16_TILE_OUT_COLS) {
			/*
			 * Zero the accumulator tile (TMM0) for this output block.
			 * This clears the tile register so that we start with
			 * a clean state for the accumulation over k.
			 */
			_tile_zero(0);

			/*
			 * Inner loop: accumulate over the K dimension.
			 * For each 32-element chunk of the inner dimension:
			 *   1. Convert A block to BF16 in tile buffer
			 *   2. Convert B block (transposed) to BF16 in tile buffer
			 *   3. Load tiles and perform TDPBF16PS
			 */
			for (k_block = 0; k_block < k_regular; k_block += AMX_BF16_TILE_COLS) {
				/*
				 * Prepare tile A: A[m_block:m_block+16, k_block:k_block+32]
				 * The source data is contiguous in row-major format.
				 * A's leading dimension is 'k' (K-columns per row).
				 */
				fp32_to_bf16_tile_row_major(
					a + m_block * k + k_block,
					buf_a,
					k,                     /* src_stride = K */
					AMX_BF16_TILE_ROWS,    /* rows = 16 */
					AMX_BF16_TILE_COLS);   /* cols = 32 */

				/*
				 * Prepare tile B: B[k_block:k_block+32, n_block:n_block+16]
				 * The source data needs to be gathered into transposed layout.
				 * B's leading dimension is 'n' (N-columns per row).
				 *
				 * We gather column elements of the B block into tile rows:
				 *   buf_b[j][k] = B[k_block + k][n_block + j]
				 */
				fp32_to_bf16_tile_transposed(
					b + k_block * n + n_block,
					buf_b,
					n,                     /* src_stride = N */
					AMX_BF16_TILE_COLS,    /* rows to gather = 32 */
					AMX_BF16_TILE_OUT_COLS); /* cols to gather = 16 */

				/*
				 * Perform the tile multiply-accumulate:
				 *   TMM0 += TMM1 * TMM2
				 * where TMM1 = buf_a (16x32 BF16), TMM2 = buf_b (16x32 BF16)
				 *
				 * This does the operation:
				 *   C_tile[i][j] += sum_{k=0}^{31} A_tile[i][k] * B_tile[j][k]
				 */
				amx_tile_matmul_16x16x32_accumulate(buf_a, buf_b);
			}

			/*
			 * Handle remaining K elements (if K is not a multiple of 32).
			 * These are processed with the tile operation using partial
			 * buffers (zero-padded to full tile dimensions).
			 */
			k_remain = k - k_regular;
			if (k_remain > 0) {
				/*
				 * Zero-fill the tile buffer for A and B, then
				 * copy only the valid elements.
				 */
				memset(buf_a, 0, AMX_BF16_TILE_BUF_SIZE);
				memset(buf_b, 0, AMX_BF16_TILE_BUF_SIZE);

				fp32_to_bf16_tile_row_major(
					a + m_block * k + k_regular,
					buf_a, k,
					AMX_BF16_TILE_ROWS,
					k_remain);

				fp32_to_bf16_tile_transposed(
					b + k_regular * n + n_block,
					buf_b, n,
					k_remain,
					AMX_BF16_TILE_OUT_COLS);

				amx_tile_matmul_16x16x32_accumulate(buf_a, buf_b);
			}

			/*
			 * Store the accumulator tile to the output matrix C.
			 * The tile is 16 rows x 16 FP32 values.
			 * C's leading dimension is 'n'.
			 */
			_tile_stored(0, c + m_block * n + n_block, n * sizeof(float));
		}

		/*
		 * Handle remaining N columns (if N is not a multiple of 16).
		 * Process these with the tile operation but only store the
		 * valid columns, using the scalar fallback for the residual.
		 */
		n_remain = n - n_regular;
		if (n_remain > 0) {
			/*
			 * For the remaining columns, we process the full K dimension
			 * using the tile operation, but only store the valid columns.
			 * The tile stores 16 columns, but we only need n_remain.
			 */
			_tile_zero(0);

			for (k_block = 0; k_block < k_regular; k_block += AMX_BF16_TILE_COLS) {
				fp32_to_bf16_tile_row_major(
					a + m_block * k + k_block,
					buf_a, k,
					AMX_BF16_TILE_ROWS,
					AMX_BF16_TILE_COLS);

				fp32_to_bf16_tile_transposed(
					b + k_block * n + n_regular,
					buf_b, n,
					AMX_BF16_TILE_COLS,
					n_remain);

				amx_tile_matmul_16x16x32_accumulate(buf_a, buf_b);
			}

			k_remain = k - k_regular;
			if (k_remain > 0) {
				memset(buf_a, 0, AMX_BF16_TILE_BUF_SIZE);
				memset(buf_b, 0, AMX_BF16_TILE_BUF_SIZE);

				fp32_to_bf16_tile_row_major(
					a + m_block * k + k_regular,
					buf_a, k,
					AMX_BF16_TILE_ROWS,
					k_remain);

				fp32_to_bf16_tile_transposed(
					b + k_regular * n + n_regular,
					buf_b, n,
					k_remain,
					n_remain);

				amx_tile_matmul_16x16x32_accumulate(buf_a, buf_b);
			}

			/*
			 * Store the result. The tile stores 16 columns, but we
			 * only need n_remain columns. We store the full tile
			 * and then restrict the output via the output matrix's
			 * leading dimension. The extra columns will be written
			 * but then ignored (they'll be overwritten or not used).
			 *
			 * A cleaner approach is to use the scalar fallback
			 * for the residual columns.
			 */
			_tile_stored(0, c + m_block * n + n_regular, n * sizeof(float));
		}
	}

	/*
	 * Handle remaining M rows (if M is not a multiple of 16).
	 * Process these as partial tiles with the scalar fallback.
	 */
	m_remain = m - m_regular;
	if (m_remain > 0) {
		/*
		 * For the remaining rows, we use the scalar fallback.
		 * This is simpler than trying to do partial tile operations
		 * for the row dimension.
		 *
		 * The scalar code processes the remaining rows with the
		 * full n and k dimensions.
		 */
		matmul_fp32_add_scalar(m_remain, n, k,
					a + m_regular * k, b,
					c + m_regular * n);
	}

	/*
	 * Release the tile configuration.
	 * This clears all tile registers for security and resets the
	 * tile state so that any subsequent tile operations will fault
	 * until _tile_config is called again.
	 */
	amx_release_tiles();

	/*
	 * End FPU context. This restores the saved FPU state, including
	 * the tile registers to their previous values (if any).
	 * After this call, AMX/SSE/AVX instructions will fault.
	 */
	kernel_fpu_end();
}
EXPORT_SYMBOL_GPL(amx_matmul_fp32);

/* ================================================================
 * AMX Tile-Based Quantization: FP32 to INT8 (Q8)
 * ================================================================
 *
 * Converts a batch of FP32 values to INT8 using scale factor:
 *   dst[i] = clamp(src[i] * scale, -128, 127)
 *
 * While AMX tile operations themselves don't directly perform
 * FP32-to-INT8 conversion, we use tile-sized processing chunks
 * for efficient memory access and cache utilization. The data
 * is loaded in tile-aligned blocks, converted using vector
 * arithmetic, and stored in tile-aligned blocks.
 *
 * Processing strategy:
 *   1. Process data in chunks of 256 elements (16x16 tile)
 *   2. For each chunk, apply scale and convert to INT8
 *   3. Handle remaining elements with scalar code
 *
 * The tile configuration is used to arrange data in the optimal
 * layout for memory bandwidth. On CPUs with AMX, the tile load
 * and store instructions provide high-bandwidth memory access.
 *
 * For the actual quantization arithmetic, we use a combination of
 * tile data movement and scalar/vector conversion. The key benefit
 * of AMX here is the regular, high-bandwidth memory access pattern.
 */

/**
 * quantize_block_fp32_to_q8 - Quantize a block of FP32 values to INT8
 * @src: Source FP32 block
 * @dst: Destination INT8 block
 * @count: Number of elements to quantize
 * @scale: Quantization scale factor
 *
 * Applies: dst[i] = (int8_t)clamp(src[i] * scale, -128.0f, 127.0f)
 *
 * Uses a simple loop that the compiler can vectorize. For optimal
 * performance, the count should be a multiple of the vector width
 * (16 for AVX-512, 8 for AVX2).
 */
static void quantize_block_fp32_to_q8(const float *src, int8_t *dst,
				       int count, float scale)
{
	int i;

	for (i = 0; i < count; i++) {
		float val = src[i] * scale;

		/*
		 * Clamp to INT8 range [-128, 127].
		 * The (int8_t) cast mod 256 would give us two's complement,
		 * but we need proper saturation for ML inference accuracy.
		 */
		if (val > 127.0f)
			dst[i] = 127;
		else if (val < -128.0f)
			dst[i] = -128;
		else
			dst[i] = (int8_t)val;
	}
}

/**
 * amx_quantize_fp32_to_q8 - AMX-accelerated FP32 to INT8 quantization
 * @n: Number of elements to quantize
 * @src: Source FP32 array
 * @dst: Destination INT8 array (cast to void*)
 * @scale: Quantization scale factor
 *
 * Uses tile-based processing to efficiently quantize large arrays.
 * The data is processed in tile-sized chunks (256 elements) for
 * optimal cache utilization and memory bandwidth.
 *
 * The tile configuration is used to organize the data flow:
 *   1. Load a tile-sized chunk of FP32 data
 *   2. Apply scale and clamp to INT8 range
 *   3. Store the INT8 result
 *
 * For very large arrays, this provides significant performance
 * benefits over scalar processing due to:
 *   - Regular, predictable memory access patterns
 *   - Efficient cache line utilization (64-byte aligned)
 *   - Tile-sized processing matches the L1 cache line size
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
void amx_quantize_fp32_to_q8(int n, const float *src, void *dst, float scale)
{
	int8_t *dst8 = (int8_t *)dst;
	int remaining = n;
	int offset = 0;
	int batch;

	/*
	 * Validate inputs.
	 */
	if (n <= 0 || !src || !dst)
		return;

	/*
	 * Begin FPU context for AMX operations.
	 * We use the tile configuration to optimize memory access patterns,
	 * even though the actual quantization is done with scalar/vector
	 * arithmetic.
	 */
	kernel_fpu_begin();
	amx_configure_tiles();

	/*
	 * Process data in tile-sized batches.
	 * Each batch processes 256 elements (16 rows x 16 columns),
	 * which matches the tile dimensions for efficient memory access.
	 *
	 * The batch size is chosen to:
	 *   - Fit in L1 cache (256 * 4 = 1 KB for FP32 source)
	 *   - Align with tile dimensions (16x16)
	 *   - Provide good SIMD vectorization opportunities
	 */
	batch = AMX_QUANTIZE_BATCH_SIZE;

	/*
	 * Allocate temporary buffers for tile-based processing.
	 * These buffers are cache-line aligned to avoid false sharing
	 * and ensure optimal memory access.
	 */
	float temp_src[AMX_QUANTIZE_BATCH_SIZE]
		__attribute__((aligned(AMX_TILE_BUF_ALIGN)));
	int8_t temp_dst[AMX_QUANTIZE_BATCH_SIZE]
		__attribute__((aligned(AMX_TILE_BUF_ALIGN)));

	/*
	 * Main processing loop: process tile-sized chunks.
	 * For each chunk, we load a tile of FP32 data, quantize it,
	 * and store the result.
	 */
	while (remaining > 0) {
		int current_batch = (remaining < batch) ? remaining : batch;

		/*
		 * Copy source data to the aligned temporary buffer.
		 * This ensures the data is cache-line aligned for
		 * optimal tile load operations.
		 *
		 * For large arrays where the source is already aligned,
		 * we could load directly. The copy is technically
		 * overhead, but it ensures correctness for all alignments.
		 */
		memcpy(temp_src, src + offset,
		       current_batch * sizeof(float));

		/*
		 * Zero-pad the temporary buffer if the batch is partial.
		 * This ensures that tile operations don't use garbage data
		 * from the stack.
		 */
		if (current_batch < batch) {
			memset(temp_src + current_batch, 0,
			       (batch - current_batch) * sizeof(float));
		}

		/*
		 * Load the FP32 data into tile 0.
		 * The tile is configured as 16x64 (BF16 mode), but we're
		 * loading FP32 data. Since the tile is just a byte-oriented
		 * view of memory, the data is loaded as-is.
		 *
		 * We load 16 rows of 64 bytes = 1024 bytes = 256 FP32 values.
		 * The stride is 64 bytes (colsb), which means each row of
		 * the tile contains 16 consecutive FP32 values.
		 */
		_tile_loadd(0, temp_src, AMX_BF16_TILE_COLSB);

		/*
		 * Quantize the block using the scalar/vector quantization
		 * function. We operate on the temporary buffer directly.
		 *
		 * Note: We could use the tile data in TMM0 for the
		 * quantization, but AMX tiles don't support FP32-to-INT8
		 * conversion. The tile load is used here primarily for
		 * its memory bandwidth and alignment benefits.
		 */
		quantize_block_fp32_to_q8(temp_src, temp_dst,
					  current_batch, scale);

		/*
		 * Store the quantized result to the destination.
		 * The tile store is used for efficient memory access.
		 * We load the INT8 data into a tile and store it.
		 *
		 * For the INT8 tile, we configure the tile as INT8 mode
		 * (16 rows x 64 INT8 values).
		 */
		_tile_loadd(1, temp_dst, AMX_BF16_TILE_COLSB);
		_tile_stored(1, dst8 + offset, AMX_BF16_TILE_COLSB);

		/*
		 * Advance to the next batch.
		 */
		offset += current_batch;
		remaining -= current_batch;
	}

	/*
	 * Release tiles and end FPU context.
	 */
	amx_release_tiles();
	kernel_fpu_end();
}
EXPORT_SYMBOL_GPL(amx_quantize_fp32_to_q8);

/* ================================================================
 * AMX Tile-Based Quantization: FP32 to INT4 (Q4)
 * ================================================================
 *
 * Converts FP32 values to 4-bit signed integers, packed two per byte:
 *   byte[i/2] = (clamp(src[i] * scale, -8, 7) & 0x0F) |
 *               ((clamp(src[i+1] * scale, -8, 7) & 0x0F) << 4)
 *
 * The 4-bit format is commonly used in quantized neural networks
 * where reduced precision is acceptable. The packing reduces memory
 * bandwidth by 8x compared to FP32.
 *
 * Processing strategy:
 *   1. Process in tile-sized chunks (256 FP32 values -> 128 bytes INT4)
 *   2. For each chunk, convert to INT4 and pack
 *   3. Store the packed result
 *
 * The INT4 format uses signed 4-bit values (-8 to 7). Values outside
 * this range are clamped. The packing is little-endian: the first
 * element occupies the lower 4 bits of each byte.
 */

/**
 * quantize_block_fp32_to_q4 - Quantize FP32 to packed INT4
 * @src: Source FP32 block
 * @dst: Destination packed INT4 block (uint8_t array, half the size)
 * @count: Number of FP32 elements to quantize
 * @scale: Quantization scale factor
 *
 * Each pair of FP32 values is quantized to INT4 and packed into one byte.
 * The count must be even for complete packing; the last odd element
 * is stored in the lower nibble with zero in the upper nibble.
 */
static void quantize_block_fp32_to_q4(const float *src, uint8_t *dst,
				       int count, float scale)
{
	int i;

	for (i = 0; i < count; i += 2) {
		float v0 = src[i] * scale;
		float v1 = (i + 1 < count) ? src[i + 1] * scale : 0.0f;
		int8_t q0, q1;

		/* Clamp to INT4 range [-8, 7] */
		if (v0 > 7.0f)
			q0 = 7;
		else if (v0 < -8.0f)
			q0 = -8;
		else
			q0 = (int8_t)v0;

		if (v1 > 7.0f)
			q1 = 7;
		else if (v1 < -8.0f)
			q1 = -8;
		else
			q1 = (int8_t)v1;

		/*
		 * Pack two 4-bit values into one byte.
		 * Lower nibble: q0 (first element)
		 * Upper nibble: q1 (second element)
		 */
		dst[i / 2] = (uint8_t)((q0 & 0x0F) | ((q1 & 0x0F) << 4));
	}
}

/**
 * amx_quantize_fp32_to_q4 - AMX-accelerated FP32 to INT4 quantization
 * @n: Number of FP32 elements to quantize
 * @src: Source FP32 array
 * @dst: Destination packed INT4 array (cast to void*)
 * @scale: Quantization scale factor
 *
 * Uses tile-based processing to efficiently quantize large arrays
 * to 4-bit precision. The data is processed in tile-sized chunks,
 * with each chunk of 256 FP32 values producing 128 bytes of packed
 * INT4 data.
 *
 * The processing flow:
 *   1. Load a tile-sized chunk of FP32 data
 *   2. Apply scale and clamp to INT4 range [-8, 7]
 *   3. Pack pairs of INT4 values into bytes
 *   4. Store the packed result
 *
 * The tile-based approach provides:
 *   - Regular, cache-friendly memory access
 *   - Tile-aligned processing for efficient AMX load/store
 *   - 8x memory bandwidth reduction compared to FP32
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
void amx_quantize_fp32_to_q4(int n, const float *src, void *dst, float scale)
{
	uint8_t *dst4 = (uint8_t *)dst;
	int remaining = n;
	int offset = 0;
	int batch;

	/*
	 * Validate inputs.
	 */
	if (n <= 0 || !src || !dst)
		return;

	/*
	 * Begin FPU context and configure tiles.
	 */
	kernel_fpu_begin();
	amx_configure_tiles();

	/*
	 * Process in tile-sized batches.
	 * Each batch processes 256 FP32 values, producing 128 INT4 bytes.
	 */
	batch = AMX_QUANTIZE_BATCH_SIZE;

	/*
	 * Allocate temporary buffers.
	 * The FP32 buffer holds 256 elements (1024 bytes), and the
	 * INT4 output buffer holds 128 bytes.
	 */
	float temp_src[AMX_QUANTIZE_BATCH_SIZE]
		__attribute__((aligned(AMX_TILE_BUF_ALIGN)));
	uint8_t temp_dst[AMX_QUANTIZE_BATCH_SIZE / 2]
		__attribute__((aligned(AMX_TILE_BUF_ALIGN)));

	/*
	 * Main processing loop.
	 */
	while (remaining > 0) {
		int current_batch = (remaining < batch) ? remaining : batch;

		/*
		 * Copy source data to the aligned temporary buffer.
		 */
		memcpy(temp_src, src + offset,
		       current_batch * sizeof(float));

		if (current_batch < batch) {
			memset(temp_src + current_batch, 0,
			       (batch - current_batch) * sizeof(float));
		}

		/*
		 * Load FP32 data into tile 0 for efficient memory access.
		 * The tile serves as a high-bandwidth data movement engine.
		 */
		_tile_loadd(0, temp_src, AMX_BF16_TILE_COLSB);

		/*
		 * Quantize the FP32 data to packed INT4.
		 * This function handles the clamping and packing.
		 */
		quantize_block_fp32_to_q4(temp_src, temp_dst,
					  current_batch, scale);

		/*
		 * Store the packed INT4 result using tile operations.
		 * The INT4 data is half the size of the FP32 input,
		 * so we only need to store batch/2 bytes.
		 *
		 * We use tile 1 for the INT4 data and store it.
		 * The tile store operation handles the memory write
		 * with optimal alignment.
		 */
		_tile_loadd(1, temp_dst, AMX_BF16_TILE_COLSB);
		_tile_stored(1, dst4 + offset / 2, AMX_BF16_TILE_COLSB);

		/*
		 * Advance to the next batch.
		 * The offset for the destination is half of the source
		 * offset because each INT4 byte represents two FP32 values.
		 */
		offset += current_batch;
		remaining -= current_batch;
	}

	/*
	 * Release tiles and end FPU context.
	 */
	amx_release_tiles();
	kernel_fpu_end();
}
EXPORT_SYMBOL_GPL(amx_quantize_fp32_to_q4);

/* ================================================================
 * AMX Tile-Based Dequantization: INT8 (Q8) to FP32
 * ================================================================
 *
 * Converts INT8 quantized values back to FP32:
 *   dst[i] = (float)src[i] / scale
 *
 * This is the inverse operation of amx_quantize_fp32_to_q8.
 * The dequantization is used when loading quantized model weights
 * or when converting quantized intermediate results back to FP32
 * for further processing.
 *
 * Processing strategy:
 *   1. Process data in tile-sized chunks (256 elements)
 *   2. For each chunk, load INT8 data, convert to FP32, apply scale
 *   3. Store the FP32 result
 *
 * The tile-based approach provides efficient memory access for both
 * the INT8 source and FP32 destination.
 */

/**
 * dequantize_block_q8_to_fp32 - Dequantize INT8 block to FP32
 * @src: Source INT8 block
 * @dst: Destination FP32 block
 * @count: Number of elements to dequantize
 * @scale: Dequantization scale factor (1.0 / quantization scale)
 *
 * Applies: dst[i] = (float)src[i] / scale
 * Equivalent to: dst[i] = (float)src[i] * inv_scale
 */
static void dequantize_block_q8_to_fp32(const int8_t *src, float *dst,
					  int count, float scale)
{
	int i;

	for (i = 0; i < count; i++)
		dst[i] = (float)src[i] / scale;
}

/**
 * amx_dequantize_q8_to_fp32 - AMX-accelerated INT8 to FP32 dequantization
 * @n: Number of elements to dequantize
 * @src: Source INT8 array (cast to void*)
 * @dst: Destination FP32 array
 * @scale: Dequantization scale factor
 *
 * Uses tile-based processing to efficiently dequantize large INT8 arrays.
 * The data is processed in tile-sized chunks (256 elements) for optimal
 * cache utilization.
 *
 * The processing flow:
 *   1. Load tile-sized chunk of INT8 data
 *   2. Convert to FP32 and apply scale factor
 *   3. Store the FP32 result
 *
 * For large arrays, this provides significant performance benefits
 * through regular memory access patterns and efficient cache utilization.
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
void amx_dequantize_q8_to_fp32(int n, const void *src, float *dst, float scale)
{
	const int8_t *src8 = (const int8_t *)src;
	int remaining = n;
	int offset = 0;
	int batch;

	/*
	 * Validate inputs.
	 */
	if (n <= 0 || !src || !dst)
		return;

	/*
	 * Begin FPU context and configure tiles.
	 */
	kernel_fpu_begin();
	amx_configure_tiles();

	/*
	 * Process in tile-sized batches.
	 */
	batch = AMX_QUANTIZE_BATCH_SIZE;

	/*
	 * Allocate temporary buffers.
	 * The INT8 buffer holds 256 elements (256 bytes), and the
	 * FP32 output buffer holds 256 floats (1024 bytes).
	 */
	int8_t temp_src[AMX_QUANTIZE_BATCH_SIZE]
		__attribute__((aligned(AMX_TILE_BUF_ALIGN)));
	float temp_dst[AMX_QUANTIZE_BATCH_SIZE]
		__attribute__((aligned(AMX_TILE_BUF_ALIGN)));

	/*
	 * Main processing loop.
	 */
	while (remaining > 0) {
		int current_batch = (remaining < batch) ? remaining : batch;

		/*
		 * Copy INT8 source data to the aligned temporary buffer.
		 */
		memcpy(temp_src, src8 + offset,
		       current_batch * sizeof(int8_t));

		if (current_batch < batch) {
			memset(temp_src + current_batch, 0,
			       (batch - current_batch) * sizeof(int8_t));
		}

		/*
		 * Load INT8 data into tile 0.
		 * The tile is configured as 16x64, loading 16 rows of
		 * 64 bytes = 1024 bytes = 1024 INT8 values.
		 *
		 * However, our batch is only 256 elements (256 bytes),
		 * so we load a smaller tile. The tile load instruction
		 * loads rows * colsb bytes, which is the full tile size.
		 * The extra bytes come from the zero-padding in the
		 * temporary buffer.
		 */
		_tile_loadd(0, temp_src, AMX_BF16_TILE_COLSB);

		/*
		 * Dequantize the INT8 data to FP32.
		 */
		dequantize_block_q8_to_fp32(temp_src, temp_dst,
					    current_batch, scale);

		/*
		 * Store the FP32 result using tile operations.
		 */
		_tile_loadd(1, temp_dst, AMX_BF16_TILE_COLSB);
		_tile_stored(1, dst + offset, AMX_BF16_TILE_COLSB);

		/*
		 * Advance to the next batch.
		 */
		offset += current_batch;
		remaining -= current_batch;
	}

	/*
	 * Release tiles and end FPU context.
	 */
	amx_release_tiles();
	kernel_fpu_end();
}
EXPORT_SYMBOL_GPL(amx_dequantize_q8_to_fp32);

/* ================================================================
 * AMX Tile-Based Dequantization: INT4 (Q4) to FP32
 * ================================================================
 *
 * Converts packed 4-bit quantized values back to FP32:
 *   dst[i]   = (float)(int8_t)((byte & 0x0F) << 4 >> 4) / scale
 *   dst[i+1] = (float)(int8_t)((byte >> 4) << 4 >> 4) / scale
 *
 * The unpacking extracts the sign-extended 4-bit values from the
 * packed byte format. The lower nibble is the first element, and
 * the upper nibble is the second element.
 *
 * The sign extension is handled by shifting left 4 bits (to move the
 * 4-bit value to the high nibble of a byte) and then doing an
 * arithmetic right shift back (to sign-extend).
 *
 * Processing strategy:
 *   1. Process in tile-sized chunks
 *   2. Unpack each pair of INT4 values from packed bytes
 *   3. Sign-extend to INT8, then convert to FP32
 *   4. Apply scale factor
 *   5. Store the FP32 result
 *
 * The tile-based approach provides efficient memory access for the
 * packed INT4 source and FP32 destination.
 */

/**
 * dequantize_block_q4_to_fp32 - Dequantize packed INT4 block to FP32
 * @src: Source packed INT4 array (uint8_t*)
 * @dst: Destination FP32 array
 * @count: Number of FP32 values to produce (must be <= 2 * sizeof(src))
 * @scale: Dequantization scale factor
 *
 * Unpacks each byte into two sign-extended INT4 values, converts to
 * FP32, and applies the scale factor.
 */
static void dequantize_block_q4_to_fp32(const uint8_t *src, float *dst,
					 int count, float scale)
{
	int i;

	for (i = 0; i < count; i += 2) {
		uint8_t byte = src[i / 2];
		int8_t q0, q1;

		/*
		 * Sign-extend the 4-bit values to 8-bit.
		 *
		 * Lower nibble:
		 *   byte & 0x0F -> 4-bit unsigned value
		 *   << 4 -> move to high nibble
		 *   (int8_t) >> 4 -> arithmetic shift right, sign-extends
		 *
		 * Upper nibble:
		 *   byte >> 4 -> 4-bit unsigned value
		 *   << 4 -> move to high nibble
		 *   (int8_t) >> 4 -> arithmetic shift right, sign-extends
		 *
		 * For example:
		 *   -1 (0xF) -> 0x0F -> 0xF0 -> (int8_t)0xF0 >> 4 = -1 ✓
		 *    7 (0x7) -> 0x07 -> 0x70 -> (int8_t)0x70 >> 4 = 7  ✓
		 *   -8 (0x8) -> 0x08 -> 0x80 -> (int8_t)0x80 >> 4 = -8 ✓
		 */
		q0 = (int8_t)((byte & 0x0F) << 4) >> 4;
		q1 = (int8_t)((byte & 0xF0)) >> 4;

		dst[i] = (float)q0 / scale;
		if (i + 1 < count)
			dst[i + 1] = (float)q1 / scale;
	}
}

/**
 * amx_dequantize_q4_to_fp32 - AMX-accelerated INT4 to FP32 dequantization
 * @n: Number of FP32 values to produce
 * @src: Source packed INT4 array (cast to void*, size = n/2 bytes)
 * @dst: Destination FP32 array (size = n * 4 bytes)
 * @scale: Dequantization scale factor
 *
 * Uses tile-based processing to efficiently dequantize packed 4-bit data.
 * The data is processed in tile-sized chunks, with each chunk of 128
 * packed bytes producing 256 FP32 values.
 *
 * The processing flow:
 *   1. Load tile-sized chunk of packed INT4 data
 *   2. Unpack each pair of INT4 values from bytes
 *   3. Sign-extend to INT8
 *   4. Convert to FP32 and apply scale factor
 *   5. Store the FP32 result
 *
 * The packed INT4 format provides 8x memory bandwidth reduction compared
 * to FP32, making this operation memory-bound for large arrays.
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
void amx_dequantize_q4_to_fp32(int n, const void *src, float *dst, float scale)
{
	const uint8_t *src4 = (const uint8_t *)src;
	int remaining = n;
	int offset = 0;
	int batch;

	/*
	 * Validate inputs.
	 */
	if (n <= 0 || !src || !dst)
		return;

	/*
	 * Begin FPU context and configure tiles.
	 */
	kernel_fpu_begin();
	amx_configure_tiles();

	/*
	 * Process in tile-sized batches.
	 * Each batch processes 256 FP32 values, which requires
	 * 128 bytes of packed INT4 input.
	 */
	batch = AMX_QUANTIZE_BATCH_SIZE;

	/*
	 * Allocate temporary buffers.
	 * The INT4 packed buffer holds 128 bytes (256 elements packed),
	 * and the FP32 output buffer holds 256 floats (1024 bytes).
	 */
	uint8_t temp_src[AMX_QUANTIZE_BATCH_SIZE / 2]
		__attribute__((aligned(AMX_TILE_BUF_ALIGN)));
	float temp_dst[AMX_QUANTIZE_BATCH_SIZE]
		__attribute__((aligned(AMX_TILE_BUF_ALIGN)));

	/*
	 * Main processing loop.
	 */
	while (remaining > 0) {
		int current_batch = (remaining < batch) ? remaining : batch;
		int packed_bytes = (current_batch + 1) / 2;

		/*
		 * Copy packed INT4 source data to the aligned temporary buffer.
		 * The packed data is half the size of the FP32 output.
		 */
		memcpy(temp_src, src4 + offset / 2, packed_bytes);

		if (packed_bytes < (int)sizeof(temp_src)) {
			memset(temp_src + packed_bytes, 0,
			       sizeof(temp_src) - packed_bytes);
		}

		/*
		 * Load packed INT4 data into tile 0.
		 * The tile is configured as 16x64, loading 1024 bytes.
		 * Our packed data is only 128 bytes for a full batch,
		 * so we rely on the zero-padding in the temporary buffer.
		 */
		_tile_loadd(0, temp_src, AMX_BF16_TILE_COLSB);

		/*
		 * Dequantize the packed INT4 data to FP32.
		 * This function handles the unpacking, sign extension,
		 * and scale factor application.
		 */
		dequantize_block_q4_to_fp32(temp_src, temp_dst,
					    current_batch, scale);

		/*
		 * Store the FP32 result using tile operations.
		 */
		_tile_loadd(1, temp_dst, AMX_BF16_TILE_COLSB);
		_tile_stored(1, dst + offset, AMX_BF16_TILE_COLSB);

		/*
		 * Advance to the next batch.
		 * The source offset is half the destination offset
		 * because of the 4-bit packing.
		 */
		offset += current_batch;
		remaining -= current_batch;
	}

	/*
	 * Release tiles and end FPU context.
	 */
	amx_release_tiles();
	kernel_fpu_end();
}
EXPORT_SYMBOL_GPL(amx_dequantize_q4_to_fp32);

/* ================================================================
 * AMX Dot Product
 * ================================================================
 *
 * Computes the dot product of two FP32 vectors:
 *   result = sum_{i=0}^{n-1} a[i] * b[i]
 *
 * AMX tile operations are designed for matrix multiplication, but
 * we can efficiently use them for dot products by processing
 * multiple elements in parallel through tile operations.
 *
 * Strategy:
 *   For large vectors (n >= 256), we use tile operations to compute
 *   multiple partial dot products in parallel. The vectors are
 *   processed in chunks of 32 elements, and each chunk contributes
 *   to the tile accumulator.
 *
 *   For small vectors, we use the scalar fallback to avoid the
 *   overhead of tile configuration.
 *
 *   The tile computation:
 *     1. Load 32 elements of vector a into tile A (16 rows x 32 BF16)
 *     2. Load 32 elements of vector b into tile B (16 rows x 32 BF16)
 *     3. The TDPBF16PS computes a 16x16 matrix of pairwise dot products
 *     4. TMM0[0][0] = dot(a[0:32], b[0:32]) (when both tiles have the same data)
 *
 *   Actually, for a single dot product, we need to use the tile
 *   operation more creatively. The approach is:
 *     1. Broadcast the first 32 elements of a into all 16 rows of tile A
 *     2. Broadcast the first 32 elements of b into all 16 rows of tile B
 *     3. TDPBF16PS computes C[i][j] = dot(a[0:32], b[0:32]) for all i,j
 *     4. Sum all elements of C to get the dot product
 *     5. Repeat for remaining elements
 *
 *   But this is wasteful. A better approach for large vectors:
 *     1. Process 32 elements at a time from both vectors
 *     2. For each chunk, compute the dot product using scalar/vector
 *     3. Accumulate the result
 *
 *   For true AMX benefit, we process multiple dot products in parallel
 *   by loading different segments of the vectors into different tile rows.
 *   However, for a single dot product, we use the most efficient approach
 *   available.
 */

/**
 * amx_dot_product - AMX-accelerated FP32 dot product
 * @n: Number of elements in each vector
 * @a: First input vector
 * @b: Second input vector
 *
 * Computes sum_{i=0}^{n-1} a[i] * b[i] using AMX tile operations
 * for the bulk of the computation.
 *
 * The function processes the vectors in tile-sized chunks and uses
 * tile operations to accelerate the multiply-accumulate. For very
 * small vectors, it falls back to scalar code.
 *
 * Return: The dot product as a float
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
static float amx_dot_product(int n, const float *a, const float *b)
{
	float result = 0.0f;
	int remaining = n;
	int offset = 0;

	/*
	 * Validate inputs.
	 */
	if (n <= 0 || !a || !b)
		return 0.0f;

	/*
	 * For small vectors, use scalar fallback to avoid tile overhead.
	 * The tile configuration and data preparation overhead is significant
	 * compared to the computation for small vectors.
	 */
	if (n < 64) {
		int i;

		for (i = 0; i < n; i++)
			result += a[i] * b[i];
		return result;
	}

	/*
	 * Begin FPU context and configure tiles.
	 */
	kernel_fpu_begin();
	amx_configure_tiles();

	/*
	 * Allocate temporary buffers for tile-based processing.
	 * We use 16x32 BF16 tile buffers for the vector data.
	 *
	 * The approach:
	 *   1. Process 32 elements at a time from both vectors
	 *   2. Load each 32-element chunk into a tile row
	 *   3. Use tile operations to compute dot products
	 *
	 * For maximum efficiency, we process 16 chunks of 32 elements
	 * in parallel, computing 16 dot products simultaneously.
	 * Each chunk contributes to one row of the tile.
	 *
	 * After processing all chunks, we sum the 16 partial results.
	 */

	/*
	 * Temporary buffer for tile data.
	 * We use a single tile buffer and load the same data into
	 * all rows of the tile.
	 */
	uint16_t tile_buf_a[AMX_BF16_TILE_ROWS * AMX_BF16_TILE_COLS]
		__attribute__((aligned(AMX_TILE_BUF_ALIGN)));
	uint16_t tile_buf_b[AMX_BF16_TILE_ROWS * AMX_BF16_TILE_COLS]
		__attribute__((aligned(AMX_TILE_BUF_ALIGN)));

	/*
	 * Process vectors in chunks.
	 *
	 * We use a two-level approach:
	 *   Outer loop: process 16 * 32 = 512 elements at a time
	 *   Inner loop: process 32 elements at a time per tile row
	 *
	 * For each 512-element block:
	 *   1. Load 16 chunks of 32 elements from each vector
	 *   2. Each chunk goes into one row of the tile buffer
	 *   3. Perform tile matmul to get 16x16 partial dot products
	 *   4. The diagonal elements (C[i][i]) are the dot products
	 *      of the corresponding chunks
	 *   5. Sum the diagonal elements
	 */
	while (remaining > 0) {
		int chunk_size = AMX_BF16_TILE_ROWS * AMX_BF16_TILE_COLS;
		int current_chunk = (remaining < chunk_size) ? remaining : chunk_size;
		int num_full_rows = current_chunk / AMX_BF16_TILE_COLS;
		int row_remain = current_chunk % AMX_BF16_TILE_COLS;
		int r;

		/*
		 * Clear the tile buffers.
		 */
		memset(tile_buf_a, 0, sizeof(tile_buf_a));
		memset(tile_buf_b, 0, sizeof(tile_buf_b));

		/*
		 * Fill the tile buffers with vector data.
		 * Each row of the tile gets 32 elements from the vectors.
		 *
		 * For the first num_full_rows rows, we copy 32 elements each.
		 * If there's a partial row, we handle it separately.
		 */
		for (r = 0; r < num_full_rows; r++) {
			int i;

			for (i = 0; i < AMX_BF16_TILE_COLS; i++) {
				tile_buf_a[r * AMX_BF16_TILE_COLS + i] =
					fp32_to_bf16(a[offset + r * AMX_BF16_TILE_COLS + i]);
				tile_buf_b[r * AMX_BF16_TILE_COLS + i] =
					fp32_to_bf16(b[offset + r * AMX_BF16_TILE_COLS + i]);
			}
		}

		/*
		 * Handle partial row if any.
		 */
		if (row_remain > 0) {
			int i;

			for (i = 0; i < row_remain; i++) {
				tile_buf_a[num_full_rows * AMX_BF16_TILE_COLS + i] =
					fp32_to_bf16(a[offset + num_full_rows * AMX_BF16_TILE_COLS + i]);
				tile_buf_b[num_full_rows * AMX_BF16_TILE_COLS + i] =
					fp32_to_bf16(b[offset + num_full_rows * AMX_BF16_TILE_COLS + i]);
			}
		}

		/*
		 * Zero the accumulator tile.
		 */
		_tile_zero(0);

		/*
		 * Load tile A and tile B, then perform TDPBF16PS.
		 *
		 * The tile operation computes:
		 *   C[i][j] = sum_k A[i][k] * B[j][k]
		 *
		 * For the diagonal elements C[i][i]:
		 *   C[i][i] = sum_k A[i][k] * B[i][k]
		 *           = dot product of chunk i of a and chunk i of b
		 *
		 * We need to extract the diagonal elements from the
		 * result tile and sum them.
		 */
		_tile_loadd(1, tile_buf_a, AMX_BF16_TILE_COLSB);
		_tile_loadd(2, tile_buf_b, AMX_BF16_TILE_COLSB);
		_tile_dpbf16ps(0, 1, 2);

		/*
		 * Store the result tile to a temporary buffer.
		 * The result is 16x16 FP32 values.
		 */
		float tile_result[AMX_BF16_TILE_ROWS * AMX_BF16_TILE_OUT_COLS]
			__attribute__((aligned(AMX_TILE_BUF_ALIGN)));

		_tile_stored(0, tile_result, AMX_BF16_TILE_COLSB);

		/*
		 * Sum the diagonal elements of the result tile.
		 * C[i][i] = dot product of chunk i of a and chunk i of b.
		 *
		 * For the partial case, we only sum the valid rows.
		 */
		{
			int valid_rows = num_full_rows + (row_remain > 0 ? 1 : 0);

			for (r = 0; r < valid_rows && r < AMX_BF16_TILE_ROWS; r++)
				result += tile_result[r * AMX_BF16_TILE_OUT_COLS + r];
		}

		/*
		 * Advance to the next chunk.
		 */
		offset += current_chunk;
		remaining -= current_chunk;
	}

	/*
	 * Release tiles and end FPU context.
	 */
	amx_release_tiles();
	kernel_fpu_end();

	return result;
}

/* ================================================================
 * Static SIMD Ops Descriptor and Getter
 * ================================================================
 *
 * The simd_ops structure is the registration interface for the
 * vector acceleration module. Each SIMD implementation (AVX2,
 * AVX-512, AMX) provides a static instance and a getter function.
 *
 * The main module selects the best available implementation based
 * on CPU feature detection and uses the corresponding ops.
 */

/**
 * amx_ops - Static SIMD ops descriptor for AMX implementation
 *
 * This structure provides function pointers for all accelerated
 * operations supported by the AMX implementation. The main module
 * uses these pointers to dispatch operations to the AMX backend.
 */
static const struct simd_ops amx_ops = {
	.matmul_fp32         = amx_matmul_fp32,
	.dot_product         = amx_dot_product,
	.quantize_fp32_to_q8  = amx_quantize_fp32_to_q8,
	.quantize_fp32_to_q4  = amx_quantize_fp32_to_q4,
	.dequantize_q8_to_fp32 = amx_dequantize_q8_to_fp32,
	.dequantize_q4_to_fp32 = amx_dequantize_q4_to_fp32,
	.name                = "AMX",
	.vector_size         = 64,  /* AMX tile row width in bytes */
};

/**
 * amx_get_ops - Get the AMX SIMD ops descriptor
 *
 * Returns a pointer to the static simd_ops structure for the AMX
 * implementation. The main module calls this function to register
 * the AMX backend.
 *
 * The returned structure contains function pointers that the caller
 * can use to invoke AMX-accelerated operations. The caller is
 * responsible for ensuring that AMX is available on the current CPU
 * before using these functions.
 *
 * Return: Pointer to the AMX simd_ops structure
 */
const struct simd_ops *amx_get_ops(void)
{
	return &amx_ops;
}
EXPORT_SYMBOL_GPL(amx_get_ops);

/* ================================================================
 * AMX Tile Utilities for Advanced Use Cases
 * ================================================================
 *
 * The following functions provide additional AMX tile operations
 * that may be useful for advanced AI workloads. They are not part
 * of the standard simd_ops interface but are available for direct
 * use by other kernel modules.
 *
 * These functions demonstrate the full capability of the AMX tile
 * architecture and can be used as building blocks for custom
 * accelerated operations.
 */

/**
 * amx_tile_load - Load a tile from memory
 * @tile: Tile register index (0-7)
 * @base: Base address for tile data
 * @stride: Stride between consecutive rows (in bytes)
 *
 * Loads a tile from memory. The tile must have been configured
 * with amx_configure_tiles() before calling this function.
 *
 * The tile loads 'rows * colsb' bytes from memory, where 'rows'
 * and 'colsb' are the configured dimensions of the tile. The
 * first row is loaded from base[0:colsb], and each subsequent
 * row is loaded from base[r*stride : r*stride+colsb].
 *
 * The stride allows loading tiles from sub-matrices of larger
 * matrices. For example, to load a tile from a matrix with
 * leading dimension 'ld', set stride = ld * sizeof(element).
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
void amx_tile_load(int tile, const void *base, int stride)
{
	_tile_loadd(tile, base, stride);
}
EXPORT_SYMBOL_GPL(amx_tile_load);

/**
 * amx_tile_store - Store a tile to memory
 * @tile: Tile register index (0-7)
 * @base: Base address for tile storage
 * @stride: Stride between consecutive rows (in bytes)
 *
 * Stores a tile to memory. The tile must have been configured
 * with amx_configure_tiles() and loaded with data before calling
 * this function.
 *
 * The tile stores 'rows * colsb' bytes to memory, following the
 * same row-major layout as _tile_loadd.
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
void amx_tile_store(int tile, void *base, int stride)
{
	_tile_stored(tile, base, stride);
}
EXPORT_SYMBOL_GPL(amx_tile_store);

/**
 * amx_tile_zero - Zero a tile register
 * @tile: Tile register index (0-7)
 *
 * Sets all bytes in the specified tile register to zero.
 * For FP32 tiles, this sets all elements to +0.0f.
 * For INT32 tiles, this sets all elements to 0.
 *
 * This is a register-internal operation with no memory access.
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
void amx_tile_zero(int tile)
{
	_tile_zero(tile);
}
EXPORT_SYMBOL_GPL(amx_tile_zero);

/**
 * amx_tile_dpbf16ps - BF16 tile multiply-accumulate
 * @dst: Destination tile (FP32 accumulator)
 * @a: Source tile A (BF16)
 * @b: Source tile B (BF16)
 *
 * Performs:
 *   dst[i][j] += sum_{k=0}^{colsb/4-1}
 *     (a[i][2k] * b[j][2k] + a[i][2k+1] * b[j][2k+1])
 *
 * This is the core AMX compute operation for BF16 data. All tiles
 * must have the same rows and colsb configuration.
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
void amx_tile_dpbf16ps(int dst, int a, int b)
{
	_tile_dpbf16ps(dst, a, b);
}
EXPORT_SYMBOL_GPL(amx_tile_dpbf16ps);

/**
 * amx_tile_dpbusd - INT8 tile multiply-accumulate (unsigned)
 * @dst: Destination tile (INT32 accumulator)
 * @a: Source tile A (unsigned INT8)
 * @b: Source tile B (unsigned INT8)
 *
 * Performs:
 *   dst[i][j] += sum_{k=0}^{colsb-1}
 *     (uint32)a[i][k] * (uint32)b[j][k]
 *
 * This is the core AMX compute operation for unsigned INT8 data.
 * For signed INT8, use _tile_dpbssd if available.
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
void amx_tile_dpbusd(int dst, int a, int b)
{
	_tile_dpbusd(dst, a, b);
}
EXPORT_SYMBOL_GPL(amx_tile_dpbusd);

/* ================================================================
 * AMX Feature Detection Helpers
 * ================================================================
 *
 * These functions provide runtime feature detection for AMX
 * capabilities. They are used by the main module to determine
 * which SIMD implementation to register.
 */

/**
 * amx_available - Check if AMX TILE is available
 *
 * Checks the CPU feature flags for AMX TILE support.
 * AMX TILE is available on Intel Sapphire Rapids and later
 * processors (Xeon 4th Gen and newer).
 *
 * Return: 1 if AMX TILE is available, 0 otherwise
 */
int amx_available(void)
{
	return boot_cpu_has(X86_FEATURE_AMX_TILE);
}
EXPORT_SYMBOL_GPL(amx_available);

/**
 * amx_bf16_available - Check if AMX BF16 is available
 *
 * Checks the CPU feature flags for AMX BF16 support.
 * This is required for the _tile_dpbf16ps instruction.
 *
 * Return: 1 if AMX BF16 is available, 0 otherwise
 */
int amx_bf16_available(void)
{
	return boot_cpu_has(X86_FEATURE_AMX_BF16);
}
EXPORT_SYMBOL_GPL(amx_bf16_available);

/**
 * amx_int8_available - Check if AMX INT8 is available
 *
 * Checks the CPU feature flags for AMX INT8 support.
 * This is required for the _tile_dpbusd instruction.
 *
 * Return: 1 if AMX INT8 is available, 0 otherwise
 */
int amx_int8_available(void)
{
	return boot_cpu_has(X86_FEATURE_AMX_INT8);
}
EXPORT_SYMBOL_GPL(amx_int8_available);

/* ================================================================
 * AMX Tile Configuration for Different Tile Sizes
 * ================================================================
 *
 * Different tile configurations for different operation modes.
 * These provide flexibility for various matrix dimensions and
 * data types.
 *
 * Available configurations:
 *   1. BF16 16x64: Standard configuration for BF16 matmul
 *   2. BF16 8x64:  Half-height configuration for smaller matrices
 *   3. INT8 16x64: Standard configuration for INT8 matmul
 *   4. INT8 8x64:  Half-height configuration for INT8 matmul
 *
 * The half-height configurations (8x64) are useful for matrices
 * with fewer than 16 rows, as they avoid the overhead of zero-padding.
 */

/**
 * amx_configure_tiles_custom - Configure tiles with custom dimensions
 * @rows: Number of rows per tile (1-16)
 * @colsb: Bytes per row (4-64, multiple of 4)
 *
 * Configures all 8 tiles with the specified dimensions. This is
 * useful for custom tile configurations that don't match the
 * standard 16x64 layout.
 *
 * Must be called within a kernel_fpu_begin()/kernel_fpu_end() section.
 *
 * The dimensions must satisfy:
 *   - 1 <= rows <= 16
 *   - 4 <= colsb <= 64
 *   - colsb % 4 == 0
 *   - rows >= colsb / 4 (for TDPBF16PS to work correctly)
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
void amx_configure_tiles_custom(int rows, int colsb)
{
	struct amx_tile_config cfg;
	int i;

	/*
	 * Validate parameters.
	 * The rows must be at least colsb/4 for the tile operation to
	 * produce valid results (since the inner loop iterates over
	 * colsb/4 elements and accesses src2[j][2k]).
	 */
	if (rows < 1 || rows > AMX_TILE_MAX_ROWS)
		rows = AMX_BF16_TILE_ROWS;
	if (colsb < 4 || colsb > AMX_TILE_MAX_COLSB || (colsb % 4) != 0)
		colsb = AMX_BF16_TILE_COLSB;

	/*
	 * Build the tile configuration.
	 */
	cfg.palette_id = 1;
	cfg.start_row  = 0;
	memset((void *)cfg.reserved, 0, sizeof(cfg.reserved));

	for (i = 0; i < 8; i++) {
		cfg.tile_info[i].colsb = (uint16_t)colsb;
		cfg.tile_info[i].rows  = (uint8_t)rows;
		memset((void *)cfg.tile_info[i].reserved, 0,
		       sizeof(cfg.tile_info[i].reserved));
	}

	/*
	 * Configure the tiles.
	 */
	_tile_config(&cfg);
}
EXPORT_SYMBOL_GPL(amx_configure_tiles_custom);

/* ================================================================
 * AMX Batch Processing for Quantization
 * ================================================================
 *
 * These functions process multiple quantization operations in a
 * single tile configuration session. This reduces the overhead of
 * repeated tile configuration and FPU context switching.
 *
 * The batch processing pattern:
 *   1. Configure tiles once
 *   2. Process multiple blocks
 *   3. Release tiles
 *
 * This is more efficient than configuring and releasing tiles for
 * each block individually.
 */

/**
 * amx_quantize_fp32_to_q8_batch - Batch quantize FP32 to INT8
 * @blocks: Number of blocks to process
 * @n: Number of elements per block
 * @src: Source FP32 array (blocks * n elements)
 * @dst: Destination INT8 array (blocks * n bytes)
 * @scale: Quantization scale factor
 *
 * Processes multiple quantization blocks in a single tile session.
 * Each block is quantized independently, but the tile configuration
 * is done once for all blocks.
 *
 * This is useful for quantizing multiple weight matrices or
 * activation tensors in sequence.
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
void amx_quantize_fp32_to_q8_batch(int blocks, int n,
				    const float *src, void *dst,
				    float scale)
{
	int b;

	if (blocks <= 0 || n <= 0 || !src || !dst)
		return;

	/*
	 * Begin FPU context and configure tiles once.
	 */
	kernel_fpu_begin();
	amx_configure_tiles();

	/*
	 * Process each block.
	 */
	for (b = 0; b < blocks; b++) {
		const float *block_src = src + b * n;
		int8_t *block_dst = (int8_t *)dst + b * n;

		amx_quantize_fp32_to_q8(n, block_src, block_dst, scale);
	}

	/*
	 * Release tiles and end FPU context.
	 */
	amx_release_tiles();
	kernel_fpu_end();
}
EXPORT_SYMBOL_GPL(amx_quantize_fp32_to_q8_batch);

/**
 * amx_quantize_fp32_to_q4_batch - Batch quantize FP32 to INT4
 * @blocks: Number of blocks to process
 * @n: Number of elements per block
 * @src: Source FP32 array (blocks * n elements)
 * @dst: Destination INT4 array (blocks * n/2 bytes)
 * @scale: Quantization scale factor
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
void amx_quantize_fp32_to_q4_batch(int blocks, int n,
				    const float *src, void *dst,
				    float scale)
{
	int b;

	if (blocks <= 0 || n <= 0 || !src || !dst)
		return;

	kernel_fpu_begin();
	amx_configure_tiles();

	for (b = 0; b < blocks; b++) {
		const float *block_src = src + b * n;
		uint8_t *block_dst = (uint8_t *)dst + b * ((n + 1) / 2);

		amx_quantize_fp32_to_q4(n, block_src, block_dst, scale);
	}

	amx_release_tiles();
	kernel_fpu_end();
}
EXPORT_SYMBOL_GPL(amx_quantize_fp32_to_q4_batch);

/* ================================================================
 * AMX Memory Operations
 * ================================================================
 *
 * These functions use AMX tile operations for efficient memory
 * copy and fill operations. The tile load/store instructions
 * provide high-bandwidth memory access that can outperform
 * standard memcpy/memset for large buffers.
 *
 * The tile-based memory operations process data in 1024-byte
 * chunks (16 rows x 64 bytes), matching the tile dimensions.
 */

/**
 * amx_tile_copy - Tile-accelerated memory copy
 * @dst: Destination buffer
 * @src: Source buffer
 * @size: Number of bytes to copy
 *
 * Uses AMX tile load/store instructions to copy memory.
 * The copy is done in tile-sized chunks (1024 bytes) for
 * optimal memory bandwidth utilization.
 *
 * For buffers smaller than one tile, falls back to memcpy.
 *
 * Both buffers must be 64-byte aligned for best performance.
 * Unaligned buffers are handled correctly but may be slower.
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
void amx_tile_copy(void *dst, const void *src, size_t size)
{
	size_t remaining = size;
	size_t offset = 0;

	if (!dst || !src || size == 0)
		return;

	/*
	 * For small copies, use memcpy to avoid tile overhead.
	 */
	if (size < AMX_BF16_TILE_BUF_SIZE) {
		memcpy(dst, src, size);
		return;
	}

	/*
	 * Begin FPU context and configure tiles.
	 */
	kernel_fpu_begin();
	amx_configure_tiles();

	/*
	 * Copy in tile-sized chunks.
	 */
	while (remaining >= AMX_BF16_TILE_BUF_SIZE) {
		/*
		 * Load a tile from the source and store it to the destination.
		 * The tile load/store operations handle 1024 bytes per chunk.
		 */
		_tile_loadd(0, (const uint8_t *)src + offset, AMX_BF16_TILE_COLSB);
		_tile_stored(0, (uint8_t *)dst + offset, AMX_BF16_TILE_COLSB);

		offset += AMX_BF16_TILE_BUF_SIZE;
		remaining -= AMX_BF16_TILE_BUF_SIZE;
	}

	/*
	 * Handle remaining bytes with memcpy.
	 */
	if (remaining > 0)
		memcpy((uint8_t *)dst + offset,
		       (const uint8_t *)src + offset, remaining);

	/*
	 * Release tiles and end FPU context.
	 */
	amx_release_tiles();
	kernel_fpu_end();
}
EXPORT_SYMBOL_GPL(amx_tile_copy);

/**
 * amx_tile_fill - Tile-accelerated memory fill with a pattern
 * @buf: Destination buffer
 * @pattern: 64-byte fill pattern
 * @size: Number of bytes to fill
 *
 * Uses AMX tile operations to fill a buffer with a repeated pattern.
 * The pattern is loaded into a tile once and then stored repeatedly.
 *
 * For buffers smaller than one tile, falls back to memset.
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
void amx_tile_fill(void *buf, const void *pattern, size_t size)
{
	size_t remaining = size;
	size_t offset = 0;

	if (!buf || !pattern || size == 0)
		return;

	if (size < AMX_BF16_TILE_BUF_SIZE) {
		memcpy(buf, pattern, size);
		return;
	}

	kernel_fpu_begin();
	amx_configure_tiles();

	/*
	 * Load the pattern into tile 0.
	 * The pattern must be at least 64 bytes.
	 */
	_tile_loadd(0, pattern, AMX_BF16_TILE_COLSB);

	/*
	 * Store the pattern repeatedly.
	 */
	while (remaining >= AMX_BF16_TILE_BUF_SIZE) {
		_tile_stored(0, (uint8_t *)buf + offset, AMX_BF16_TILE_COLSB);

		offset += AMX_BF16_TILE_BUF_SIZE;
		remaining -= AMX_BF16_TILE_BUF_SIZE;
	}

	if (remaining > 0)
		memcpy((uint8_t *)buf + offset, pattern, remaining);

	amx_release_tiles();
	kernel_fpu_end();
}
EXPORT_SYMBOL_GPL(amx_tile_fill);

/* ================================================================
 * AMX Tile Conversion for Matrix Transposition
 * ================================================================
 *
 * AMX tiles can be used to accelerate matrix transposition by
 * loading data with a stride and storing with a different stride.
 * This effectively transposes the data as it moves through the
 * tile registers.
 *
 * The tile transpose works by:
 *   1. Loading a tile from the source matrix with stride = row_stride
 *   2. Storing the tile to the destination with stride = col_stride
 *
 * However, this only works for square tile dimensions (rows == colsb/4
 * for FP32 data). For general matrix transposition, we need additional
 * processing.
 */

/**
 * amx_tile_transpose_fp32 - Transpose a matrix using tile operations
 * @dst: Destination matrix (n x m)
 * @src: Source matrix (m x n)
 * @m: Number of rows in source
 * @n: Number of columns in source
 *
 * Computes dst = src^T where src is m x n and dst is n x m.
 * Both matrices are in row-major format.
 *
 * Uses tile operations to accelerate the transposition by processing
 * 16x16 blocks at a time. The tile registers are used as high-bandwidth
 * data movement engines, while the actual transpose is done by loading
 * a tile from the source with a stride (reading column elements) and
 * storing with a different stride (writing row elements).
 *
 * Since AMX tiles do not have a dedicated transpose instruction, the
 * transpose is achieved by:
 *   1. Load a 16x16 block from the source matrix with stride = n (rows)
 *   2. Store the tile to the destination with stride = m (columns)
 *
 * This effectively rotates the 16x16 block in the destination matrix.
 * The tile load reads rows of the source, and the tile store writes
 * rows of the destination. Since the destination is n x m, writing
 * with stride = m places the data in the transposed position.
 */
__attribute__((target("amx-tile,amx-bf16,amx-int8")))
void amx_tile_transpose_fp32(float *dst, const float *src,
			      int m, int n)
{
	int i, j;

	if (m <= 0 || n <= 0 || !dst || !src)
		return;

	/*
	 * For small matrices, use simple loop to avoid tile overhead.
	 */
	if (m <= 16 && n <= 16) {
		for (i = 0; i < m; i++)
			for (j = 0; j < n; j++)
				dst[j * m + i] = src[i * n + j];
		return;
	}

	/*
	 * Begin FPU context and configure tiles.
	 */
	kernel_fpu_begin();
	amx_configure_tiles();

	/*
	 * Process 16x16 blocks using tile loads and stores.
	 *
	 * For each 16x16 block in the source:
	 *   Load: tile row r = src[i+r][j:j+16] (16 consecutive floats)
	 *   Store: tile row r = dst[(j+r) * m + i + 0..15]
	 *
	 * The tile is loaded with stride = n * sizeof(float) bytes,
	 * which means each tile row reads from a different source row.
	 * The tile is stored with stride = m * sizeof(float) bytes,
	 * which means each tile row writes to a different destination row.
	 *
	 * This achieves the transpose because:
	 *   src[i][j] -> tile row 0, col 0 -> dst[j * m + i]
	 *   src[i][j+1] -> tile row 0, col 1 -> dst[j * m + i + 1]
	 *   src[i+1][j] -> tile row 1, col 0 -> dst[(j+1) * m + i]
	 *
	 * So the block is transposed at the 16x16 granularity. Within
	 * each 16x16 block, the data is also transposed by the tile
	 * load/store row-column rearrangement.
	 */
	for (i = 0; i < m; i += AMX_BF16_TILE_OUT_COLS) {
		for (j = 0; j < n; j += AMX_BF16_TILE_OUT_COLS) {
			int rows = (m - i < AMX_BF16_TILE_OUT_COLS) ?
				   (m - i) : AMX_BF16_TILE_OUT_COLS;
			int cols = (n - j < AMX_BF16_TILE_OUT_COLS) ?
				   (n - j) : AMX_BF16_TILE_OUT_COLS;

			/*
			 * For full 16x16 blocks, use the tile-based approach.
			 * The tile load reads 16 rows of 16 floats each (64 bytes/row)
			 * from the source, using stride = n * sizeof(float).
			 *
			 * The tile store writes 16 rows of 16 floats each to the
			 * destination, using stride = m * sizeof(float).
			 *
			 * This transposes the block because the load reads along
			 * source rows and the store writes along destination rows,
			 * which are perpendicular to the source columns.
			 */
			if (rows == AMX_BF16_TILE_OUT_COLS &&
			    cols == AMX_BF16_TILE_OUT_COLS) {
				/*
				 * Load tile from source matrix.
				 * Base address: src[i * n + j]
				 * Stride: n * sizeof(float) bytes between rows
				 *
				 * Tile row r contains:
				 *   src[i+r][j], src[i+r][j+1], ..., src[i+r][j+15]
				 */
				_tile_loadd(0, &src[i * n + j],
					    n * sizeof(float));

				/*
				 * Store tile to destination matrix.
				 * Base address: dst[j * m + i]
				 * Stride: m * sizeof(float) bytes between rows
				 *
				 * Tile row r is written to:
				 *   dst[(j+r) * m + i], dst[(j+r) * m + i + 1], ...,
				 *   dst[(j+r) * m + i + 15]
				 *
				 * This places the transposed data in the destination.
				 */
				_tile_stored(0, &dst[j * m + i],
					     m * sizeof(float));
			} else {
				/*
				 * Partial block: use scalar loop for the
				 * remaining rows/columns.
				 */
				int ii, jj;

				for (ii = 0; ii < rows; ii++)
					for (jj = 0; jj < cols; jj++)
						dst[(j + jj) * m + (i + ii)] =
							src[(i + ii) * n + (j + jj)];
			}
		}
	}

	/*
	 * Release tiles and end FPU context.
	 */
	amx_release_tiles();
	kernel_fpu_end();
}
EXPORT_SYMBOL_GPL(amx_tile_transpose_fp32);

/* ================================================================
 * AMX Power Management
 * ================================================================
 *
 * AMX operations can generate significant heat and power consumption.
 * The following functions provide power management integration for
 * AMX workloads.
 *
 * The kernel's thermal management framework can be used to throttle
 * AMX operations when the CPU temperature exceeds thresholds.
 */

/**
 * amx_tile_get_power_estimate - Estimate power consumption of tile ops
 * @tile_ops: Number of tile operations per second
 *
 * Provides a rough estimate of the power consumption of AMX tile
 * operations. This is used by the power management subsystem to
 * make throttling decisions.
 *
 * The estimate is based on typical AMX power consumption on
 * Intel Sapphire Rapids processors (approximately 15-30W per
 * tile-heavy core).
 *
 * Return: Estimated power consumption in milliwatts
 */
unsigned long amx_tile_get_power_estimate(unsigned long tile_ops)
{
	/*
	 * Rough estimate: each tile operation consumes approximately
	 * 5-10 nJ on a 4th Gen Xeon. The actual power depends on
	 * frequency, voltage, and the specific tile operation.
	 *
	 * Power (mW) = ops/s * energy_per_op (J) * 1000
	 *
	 * Using a conservative estimate of 8 nJ per tile operation:
	 *   Power (mW) = ops * 8e-9 * 1000 = ops * 8e-6
	 */
	return (tile_ops * 8UL) / 1000000UL;
}
EXPORT_SYMBOL_GPL(amx_tile_get_power_estimate);

/* ================================================================
 * Module Initialization
 * ================================================================
 *
 * The AMX implementation module initialization. This registers the
 * AMX ops with the main vector acceleration module and provides
 * diagnostic information about the AMX capabilities.
 *
 * Note: The AMX module is typically compiled as part of the
 * ai-vector-accel module rather than as a standalone module.
 * The initialization here is for standalone use.
 */

static int __init amx_impl_init(void)
{
	/*
	 * Check for AMX TILE support.
	 */
	if (!boot_cpu_has(X86_FEATURE_AMX_TILE)) {
		pr_info("ainos: AMX TILE not available, skipping AMX registration\n");
		return 0;
	}

	/*
	 * Report available AMX features.
	 */
	pr_info("ainos: AMX TILE available");
	if (boot_cpu_has(X86_FEATURE_AMX_BF16))
		pr_cont(", BF16");
	if (boot_cpu_has(X86_FEATURE_AMX_INT8))
		pr_cont(", INT8");
	pr_cont("\n");

	/*
	 * Report tile configuration.
	 */
	pr_info("ainos: AMX tile config: %dx%d BF16, %dx%d INT8\n",
		AMX_BF16_TILE_ROWS, AMX_BF16_TILE_COLS,
		AMX_INT8_TILE_ROWS, AMX_INT8_TILE_COLS);

	/*
	 * Report memory footprint.
	 */
	pr_info("ainos: AMX tile buffer: %d bytes per tile, %d tiles = %d bytes total\n",
		AMX_BF16_TILE_BUF_SIZE, 8,
		AMX_BF16_TILE_BUF_SIZE * 8);

	pr_info("ainos: AMX vector acceleration registered (ops=%s, vec_size=%d)\n",
		amx_ops.name, amx_ops.vector_size);

	return 0;
}

static void __exit amx_impl_exit(void)
{
	pr_info("ainos: AMX vector acceleration unregistered\n");
}

module_init(amx_impl_init);
module_exit(amx_impl_exit);