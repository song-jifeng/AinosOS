/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Ainos AI Memory Allocator - Header
 *
 * Copyright (C) 2026 Ainos Corporation
 * Authors: Ainos Kernel Team
 *
 * AI workload-aware memory allocation interface.
 * Provides intelligent memory pool management, huge page support,
 * NUMA-aware allocation, memory pressure detection, and OOM prevention.
 */

#ifndef _AINOS_AI_MEMALLOC_H
#define _AINOS_AI_MEMALLOC_H

#include <linux/types.h>
#include <linux/mmzone.h>
#include <linux/numa.h>
#include <linux/huge_mm.h>
#include <linux/mempolicy.h>
#include <linux/dma-direction.h>

/* Module identification */
#define AI_MEMALLOC_MODULE_NAME		"ai_memalloc"
#define AI_MEMALLOC_MODULE_VERSION	"1.0.0"
#define AI_MEMALLOC_MODULE_DESC		"Ainos AI Memory Allocator"
#define AI_MEMALLOC_MODULE_AUTHOR	"Ainos Kernel Team"

/* Device interface */
#define AI_MEMALLOC_DEVICE_NAME		"ai-memalloc"
#define AI_MEMALLOC_CLASS_NAME		"ai-memalloc"
#define AI_MEMALLOC_MAX_DEVICES		4

/* IOCTL commands */
#define AI_MEMALLOC_IOC_MAGIC		0xAE

#define AI_MEMALLOC_IOCTL_GET_INFO		_IOR(AI_MEMALLOC_IOC_MAGIC, 0x01, struct ai_memalloc_info)
#define AI_MEMALLOC_IOCTL_ALLOC		_IOWR(AI_MEMALLOC_IOC_MAGIC, 0x02, struct ai_memalloc_request)
#define AI_MEMALLOC_IOCTL_FREE		_IOW(AI_MEMALLOC_IOC_MAGIC, 0x03, struct ai_memalloc_free)
#define AI_MEMALLOC_IOCTL_PIN		_IOWR(AI_MEMALLOC_IOC_MAGIC, 0x04, struct ai_memalloc_pin)
#define AI_MEMALLOC_IOCTL_UNPIN		_IOW(AI_MEMALLOC_IOC_MAGIC, 0x05, struct ai_memalloc_pin)
#define AI_MEMALLOC_IOCTL_SET_POLICY		_IOW(AI_MEMALLOC_IOC_MAGIC, 0x06, struct ai_memalloc_policy)
#define AI_MEMALLOC_IOCTL_GET_POLICY		_IOR(AI_MEMALLOC_IOC_MAGIC, 0x07, struct ai_memalloc_policy)
#define AI_MEMALLOC_IOCTL_PRESSURE_INFO	_IOR(AI_MEMALLOC_IOC_MAGIC, 0x08, struct ai_memalloc_pressure)
#define AI_MEMALLOC_IOCTL_POOL_STATS		_IOR(AI_MEMALLOC_IOC_MAGIC, 0x09, struct ai_memalloc_pool_stats)
#define AI_MEMALLOC_IOCTL_COMPACT		_IO(AI_MEMALLOC_IOC_MAGIC, 0x0A)
#define AI_MEMALLOC_IOCTL_RECLAIM		_IOW(AI_MEMALLOC_IOC_MAGIC, 0x0B, size_t)
#define AI_MEMALLOC_IOCTL_BIND_NUMA		_IOW(AI_MEMALLOC_IOC_MAGIC, 0x0C, struct ai_memalloc_numa_bind)
#define AI_MEMALLOC_IOCTL_MIGRATE		_IOWR(AI_MEMALLOC_IOC_MAGIC, 0x0D, struct ai_memalloc_migrate)
#define AI_MEMALLOC_IOCTL_RESERVE		_IOWR(AI_MEMALLOC_IOC_MAGIC, 0x0E, struct ai_memalloc_reserve)
#define AI_MEMALLOC_IOCTL_GET_WATERMARKS	_IOR(AI_MEMALLOC_IOC_MAGIC, 0x0F, struct ai_memalloc_watermarks)
#define AI_MEMALLOC_IOCTL_SET_WATERMARKS	_IOW(AI_MEMALLOC_IOC_MAGIC, 0x10, struct ai_memalloc_watermarks)
#define AI_MEMALLOC_IOCTL_HUGEPAGE_STATUS	_IOR(AI_MEMALLOC_IOC_MAGIC, 0x11, struct ai_memalloc_hugepage)
#define AI_MEMALLOC_IOCTL_DEFRAG		_IO(AI_MEMALLOC_IOC_MAGIC, 0x12)
#define AI_MEMALLOC_IOCTL_PROFILE		_IOR(AI_MEMALLOC_IOC_MAGIC, 0x13, struct ai_memalloc_profile)
#define AI_MEMALLOC_IOCTL_CLEANUP		_IO(AI_MEMALLOC_IOC_MAGIC, 0x14)

#define AI_MEMALLOC_IOC_MAXNR		20

/* Memory pool types */
enum ai_memalloc_pool_type {
	AI_MEMALLOC_POOL_SMALL		= 0,	/* < 4KB */
	AI_MEMALLOC_POOL_MEDIUM		= 1,	/* 4KB - 64KB */
	AI_MEMALLOC_POOL_LARGE		= 2,	/* 64KB - 2MB */
	AI_MEMALLOC_POOL_HUGE		= 3,	/* 2MB+ */
	AI_MEMALLOC_POOL_TOTAL		= 4,
};

/* Allocation flags */
#define AI_MEMALLOC_F_HUGEPAGE		BIT(0)
#define AI_MEMALLOC_F_THP		BIT(1)
#define AI_MEMALLOC_F_NUMA_LOCAL	BIT(2)
#define AI_MEMALLOC_F_DMA32		BIT(3)
#define AI_MEMALLOC_F_MOVABLE		BIT(4)
#define AI_MEMALLOC_F_RECLAIMABLE	BIT(5)
#define AI_MEMALLOC_F_ZERO		BIT(6)
#define AI_MEMALLOC_F_CONTIG		BIT(7)
#define AI_MEMALLOC_F_HIGHMEM		BIT(8)
#define AI_MEMALLOC_F_NORETRY		BIT(9)
#define AI_MEMALLOC_F_RETRY_MAYFAIL	BIT(10)
#define AI_MEMALLOC_F_ATOMIC		BIT(11)
#define AI_MEMALLOC_F_KERNEL		BIT(12)
#define AI_MEMALLOC_F_USER		BIT(13)
#define AI_MEMALLOC_F_DMA		BIT(14)
#define AI_MEMALLOC_F_PREFAULT		BIT(15)

/* Memory pressure levels */
enum ai_memalloc_pressure_level {
	AI_MEMALLOC_PRESSURE_NONE	= 0,
	AI_MEMALLOC_PRESSURE_LOW	= 1,
	AI_MEMALLOC_PRESSURE_MEDIUM	= 2,
	AI_MEMALLOC_PRESSURE_HIGH	= 3,
	AI_MEMALLOC_PRESSURE_CRITICAL	= 4,
};

/* NUMA binding modes */
enum ai_memalloc_numa_mode {
	AI_MEMALLOC_NUMA_BIND		= 0,	/* Strict binding */
	AI_MEMALLOC_NUMA_PREFER		= 1,	/* Preferred node */
	AI_MEMALLOC_NUMA_INTERLEAVE	= 2,	/* Interleave */
	AI_MEMALLOC_NUMA_LOCAL		= 3,	/* Local node only */
	AI_MEMALLOC_NUMA_RANDOM		= 4,	/* Random distribution */
};

/* Page allocation order */
enum ai_memalloc_order {
	AI_MEMALLOC_ORDER_4K		= 0,
	AI_MEMALLOC_ORDER_8K		= 1,
	AI_MEMALLOC_ORDER_16K		= 2,
	AI_MEMALLOC_ORDER_32K		= 3,
	AI_MEMALLOC_ORDER_64K		= 4,
	AI_MEMALLOC_ORDER_128K		= 5,
	AI_MEMALLOC_ORDER_256K		= 6,
	AI_MEMALLOC_ORDER_512K		= 7,
	AI_MEMALLOC_ORDER_1M		= 8,
	AI_MEMALLOC_ORDER_2M		= 9,
	AI_MEMALLOC_ORDER_4M		= 10,
	AI_MEMALLOC_ORDER_8M		= 11,
	AI_MEMALLOC_ORDER_16M		= 12,
	AI_MEMALLOC_ORDER_32M		= 13,
	AI_MEMALLOC_ORDER_64M		= 14,
	AI_MEMALLOC_ORDER_128M		= 15,
	AI_MEMALLOC_ORDER_MAX		= 15,
};

/* Memory allocation policy */
struct ai_memalloc_policy {
	__u32			flags;
	__u32			pool_type;
	enum ai_memalloc_numa_mode	numa_mode;
	__u32			numa_nodes[4];
	__u32			numa_node_count;
	__u32			prefetch_depth;
	__u32			reclaim_priority;
	__u32			oom_priority;
	__u32			compaction_proactive;
	__u32			watermark_scale;
	__u32			reserve_pages;
	__u32			max_alloc_attempts;
	__u32			allocation_timeout_ms;
	__u32			padding[4];
};

/* Allocation request */
struct ai_memalloc_request {
	__u64			size;
	__u64			alignment;
	__u32			flags;
	__u32			pool_type;
	__u32			numa_node;
	__u32			workload_hint;
	__u64			phys_addr;
	__u64			virt_addr;
	__s32			result;
	__u32			padding[3];
};

/* Memory free structure */
struct ai_memalloc_free {
	__u64			addr;
	__u64			size;
	__u32			flags;
	__u32			padding[3];
};

/* Memory pin/unpin */
struct ai_memalloc_pin {
	__u64			addr;
	__u64			size;
	__u32			refcount;
	__u32			flags;
	__s32			result;
	__u32			padding[3];
};

/* NUMA bind request */
struct ai_memalloc_numa_bind {
	__u64			addr;
	__u64			size;
	__u32			numa_node;
	__u32			numa_mode;
	__u32			flags;
	__u32			padding[3];
};

/* Migration request */
struct ai_memalloc_migrate {
	__u64			addr;
	__u64			size;
	__u32			source_node;
	__u32			target_node;
	__u32			flags;
	__u32			migrated_pages;
	__s32			result;
	__u32			padding[2];
};

/* Memory reservation */
struct ai_memalloc_reserve {
	__u64			size;
	__u32			flags;
	__u32			numa_node;
	__u64			reserved_addr;
	__s32			result;
	__u32			padding[3];
};

/* Watermark configuration */
struct ai_memalloc_watermarks {
	__u64			min_free_pages;
	__u64			low_free_pages;
	__u64			high_free_pages;
	__u64			emergency_pages;
	__u32			zone;
	__u32			padding[3];
};

/* Huge page status */
struct ai_memalloc_hugepage {
	__u64			total_hugepages;
	__u64			free_hugepages;
	__u64			resv_hugepages;
	__u64			surplus_hugepages;
	__u64			hugepage_size;
	__u32			default_hstate;
	__u32			nr_hstates;
	__u32			padding[4];
};

/* Memory pressure information */
struct ai_memalloc_pressure {
	enum ai_memalloc_pressure_level	level;
	__u32			score;
	__u64			free_pages;
	__u64			total_pages;
	__u64			dirty_pages;
	__u64			writeback_pages;
	__u64			unevictable_pages;
	__u64			mapped_pages;
	__u64			swap_free;
	__u64			swap_total;
	__u32			scan_attempts;
	__u32			reclaim_success;
	__u32			oom_kills;
	__u32			padding[5];
};

/* Pool statistics */
struct ai_memalloc_pool_stats {
	__u64			pool_size[AI_MEMALLOC_POOL_TOTAL];
	__u64			pool_used[AI_MEMALLOC_POOL_TOTAL];
	__u64			pool_free[AI_MEMALLOC_POOL_TOTAL];
	__u64			pool_max[AI_MEMALLOC_POOL_TOTAL];
	__u64			alloc_count[AI_MEMALLOC_POOL_TOTAL];
	__u64			free_count[AI_MEMALLOC_POOL_TOTAL];
	__u64			fail_count[AI_MEMALLOC_POOL_TOTAL];
	__u64			cache_hits[AI_MEMALLOC_POOL_TOTAL];
	__u64			cache_misses[AI_MEMALLOC_POOL_TOTAL];
	__u64			total_allocated;
	__u64			total_freed;
	__u64			current_usage;
	__u32			active_allocations;
	__u32			pending_frees;
	__u32			padding[6];
};

/* Module info */
struct ai_memalloc_info {
	char			version[32];
	char			description[64];
	__u32			major_version;
	__u32			minor_version;
	__u32			patch_version;
	__u32			max_pools;
	__u32			active_pools;
	__u32			hugepage_supported;
	__u32			numa_supported;
	__u32			numa_nodes;
	__u32			features;
	__u32			padding[8];
};

/* Profile data */
struct ai_memalloc_profile {
	__u64			avg_alloc_latency_ns;
	__u64			max_alloc_latency_ns;
	__u64			avg_free_latency_ns;
	__u64			max_free_latency_ns;
	__u64			avg_migrate_latency_ns;
	__u64			total_alloc_time_ns;
	__u64			total_free_time_ns;
	__u64			allocation_count;
	__u64			free_count;
	__u64			migration_count;
	__u64			compaction_count;
	__u64			reclaim_count;
	__u64			page_fault_count;
	__u64			tlb_shootdown_count;
	__u32			padding[8];
};

/* Sysfs entries */
#define AI_MEMALLOC_SYSFS_POOL_SIZE		"pool_size"
#define AI_MEMALLOC_SYSFS_POOL_USED		"pool_used"
#define AI_MEMALLOC_SYSFS_POOL_FREE		"pool_free"
#define AI_MEMALLOC_SYSFS_PRESSURE		"pressure"
#define AI_MEMALLOC_SYSFS_NUMA_NODES		"numa_nodes"
#define AI_MEMALLOC_SYSFS_HUGEPAGE		"hugepage_info"
#define AI_MEMALLOC_SYSFS_STATS		"stats"
#define AI_MEMALLOC_SYSFS_WATERMARKS		"watermarks"
#define AI_MEMALLOC_SYSFS_PROFILE		"profile"
#define AI_MEMALLOC_SYSFS_POLICY		"policy"
#define AI_MEMALLOC_SYSFS_COMPACT		"compact"
#define AI_MEMALLOC_SYSFS_RECLAIM		"reclaim"

/* Internal kernel API - exported for other Ainos modules */
struct ai_memalloc_context;
struct ai_memory_pool;

#ifdef CONFIG_AINOS_AI_MEMALLOC

/* Primary allocation API */
void *ai_memalloc_alloc(size_t size, gfp_t gfp_flags, int numa_node);
void *ai_memalloc_alloc_huge(size_t size, gfp_t gfp_flags, int numa_node);
void *ai_memalloc_alloc_numa(size_t size, gfp_t gfp_flags, nodemask_t *nodemask);
void *ai_memalloc_zalloc(size_t size, gfp_t gfp_flags, int numa_node);
void ai_memalloc_free(void *addr, size_t size);

/* Pool management */
int ai_memalloc_pool_create(size_t min_size, size_t max_size,
			    gfp_t gfp_flags, int numa_node);
int ai_memalloc_pool_destroy(int pool_id);
int ai_memalloc_pool_expand(int pool_id, size_t additional_size);
int ai_memalloc_pool_shrink(int pool_id, size_t target_size);

/* NUMA operations */
int ai_memalloc_migrate_pages(void *addr, size_t size, int target_node);
int ai_memalloc_bind_to_node(void *addr, size_t size, int numa_node);
int ai_memalloc_get_numa_node(void *addr);
nodemask_t ai_memalloc_get_numa_mask(void);

/* Huge page management */
int ai_memalloc_hugepage_alloc(struct page **pages, int nr_pages, int nid);
int ai_memalloc_hugepage_free(struct page **pages, int nr_pages);
int ai_memalloc_hugepage_promote(void *addr, size_t size);
int ai_memalloc_thp_enable(void *addr, size_t size);

/* Pressure and reclaim */
int ai_memalloc_get_pressure_level(enum ai_memalloc_pressure_level *level);
int ai_memalloc_reclaim(size_t target_pages);
int ai_memalloc_compact(void);
int ai_memalloc_register_oom_notifier(void (*handler)(void));
int ai_memalloc_unregister_oom_notifier(void (*handler)(void));

/* Watermark management */
int ai_memalloc_set_watermarks(struct ai_memalloc_watermarks *wm);
int ai_memalloc_get_watermarks(struct ai_memalloc_watermarks *wm);

/* Cache operations */
int ai_memalloc_cache_hit(void *addr);
int ai_memalloc_cache_miss(void *addr);

/* Debug and monitoring */
int ai_memalloc_get_stats(struct ai_memalloc_pool_stats *stats);
int ai_memalloc_get_profile(struct ai_memalloc_profile *profile);
int ai_memalloc_dump_state(void);
int ai_memalloc_validate_allocations(void);

#else /* !CONFIG_AINOS_AI_MEMALLOC */

/* Stub functions when module is disabled */
static inline void *ai_memalloc_alloc(size_t size, gfp_t gfp_flags,
				      int numa_node)
{
	return kmalloc_node(size, gfp_flags, numa_node);
}

static inline void *ai_memalloc_alloc_huge(size_t size, gfp_t gfp_flags,
					   int numa_node)
{
	return kmalloc_node(size, gfp_flags | __GFP_COMP, numa_node);
}

static inline void *ai_memalloc_alloc_numa(size_t size, gfp_t gfp_flags,
					   nodemask_t *nodemask)
{
	return kmalloc_node(size, gfp_flags, first_node(*nodemask));
}

static inline void *ai_memalloc_zalloc(size_t size, gfp_t gfp_flags,
				       int numa_node)
{
	return kzalloc_node(size, gfp_flags, numa_node);
}

static inline void ai_memalloc_free(void *addr, size_t size)
{
	kfree(addr);
}

static inline int ai_memalloc_pool_create(size_t min_size, size_t max_size,
					  gfp_t gfp_flags, int numa_node)
{
	return -ENODEV;
}

static inline int ai_memalloc_pool_destroy(int pool_id)
{
	return -ENODEV;
}

static inline int ai_memalloc_pool_expand(int pool_id, size_t additional_size)
{
	return -ENODEV;
}

static inline int ai_memalloc_pool_shrink(int pool_id, size_t target_size)
{
	return -ENODEV;
}

static inline int ai_memalloc_migrate_pages(void *addr, size_t size,
					    int target_node)
{
	return -ENODEV;
}

static inline int ai_memalloc_bind_to_node(void *addr, size_t size,
					   int numa_node)
{
	return -ENODEV;
}

static inline int ai_memalloc_get_numa_node(void *addr)
{
	return numa_node_id();
}

static inline nodemask_t ai_memalloc_get_numa_mask(void)
{
	return *node_online_mask;
}

static inline int ai_memalloc_hugepage_alloc(struct page **pages,
					     int nr_pages, int nid)
{
	return -ENODEV;
}

static inline int ai_memalloc_hugepage_free(struct page **pages, int nr_pages)
{
	return -ENODEV;
}

static inline int ai_memalloc_hugepage_promote(void *addr, size_t size)
{
	return -ENODEV;
}

static inline int ai_memalloc_thp_enable(void *addr, size_t size)
{
	return -ENODEV;
}

static inline int ai_memalloc_get_pressure_level(
		enum ai_memalloc_pressure_level *level)
{
	*level = AI_MEMALLOC_PRESSURE_NONE;
	return 0;
}

static inline int ai_memalloc_reclaim(size_t target_pages)
{
	return -ENODEV;
}

static inline int ai_memalloc_compact(void)
{
	return -ENODEV;
}

static inline int ai_memalloc_register_oom_notifier(void (*handler)(void))
{
	return -ENODEV;
}

static inline int ai_memalloc_unregister_oom_notifier(void (*handler)(void))
{
	return -ENODEV;
}

static inline int ai_memalloc_set_watermarks(struct ai_memalloc_watermarks *wm)
{
	return -ENODEV;
}

static inline int ai_memalloc_get_watermarks(struct ai_memalloc_watermarks *wm)
{
	return -ENODEV;
}

static inline int ai_memalloc_cache_hit(void *addr)
{
	return 0;
}

static inline int ai_memalloc_cache_miss(void *addr)
{
	return 0;
}

static inline int ai_memalloc_get_stats(struct ai_memalloc_pool_stats *stats)
{
	return -ENODEV;
}

static inline int ai_memalloc_get_profile(struct ai_memalloc_profile *profile)
{
	return -ENODEV;
}

static inline int ai_memalloc_dump_state(void)
{
	return -ENODEV;
}

static inline int ai_memalloc_validate_allocations(void)
{
	return -ENODEV;
}

#endif /* CONFIG_AINOS_AI_MEMALLOC */

#endif /* _AINOS_AI_MEMALLOC_H */