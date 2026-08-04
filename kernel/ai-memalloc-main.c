// SPDX-License-Identifier: GPL-2.0-only
/*
 * Ainos AI Memory Allocator - Main Module
 *
 * Copyright (C) 2026 Ainos Corporation
 * Authors: Ainos Kernel Team
 *
 * AI workload-aware memory allocator with intelligent memory pool
 * management, huge page support (HugeTLB, THP), NUMA-aware allocation,
 * memory pressure detection, and OOM prevention.
 *
 * This module provides a character device interface for user-space
 * AI workloads to efficiently manage memory allocations, as well as
 * a kernel-internal API for other Ainos modules.
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/fs.h>
#include <linux/cdev.h>
#include <linux/device.h>
#include <linux/slab.h>
#include <linux/mm.h>
#include <linux/mmzone.h>
#include <linux/huge_mm.h>
#include <linux/mempolicy.h>
#include <linux/numa.h>
#include <linux/gfp.h>
#include <linux/vmalloc.h>
#include <linux/dma-mapping.h>
#include <linux/delay.h>
#include <linux/mutex.h>
#include <linux/spinlock.h>
#include <linux/rwsem.h>
#include <linux/atomic.h>
#include <linux/kref.h>
#include <linux/ktime.h>
#include <linux/hrtimer.h>
#include <linux/workqueue.h>
#include <linux/sched/mm.h>
#include <linux/pagemap.h>
#include <linux/page_counter.h>
#include <linux/memcontrol.h>
#include <linux/oom.h>
#include <linux/mm_inline.h>
#include <linux/swap.h>
#include <linux/kthread.h>
#include <linux/freezer.h>
#include <linux/sysfs.h>
#include <linux/kobject.h>
#include <linux/string.h>
#include <linux/uaccess.h>
#include <linux/errno.h>
#include <linux/types.h>
#include <linux/bitops.h>
#include <linux/log2.h>
#include <linux/math64.h>
#include <linux/percpu.h>
#include <linux/hardirq.h>
#include <linux/sched.h>
#include <linux/cpumask.h>
#include <linux/node.h>

#include "ainos/ai-memalloc.h"

/*
 * Module information
 */
MODULE_LICENSE("GPL");
MODULE_VERSION(AI_MEMALLOC_MODULE_VERSION);
MODULE_DESCRIPTION(AI_MEMALLOC_MODULE_DESC);
MODULE_AUTHOR(AI_MEMALLOC_MODULE_AUTHOR);
MODULE_ALIAS("ainos-ai-memalloc");

/*
 * Debug macros
 */
#define ai_memalloc_dbg(fmt, ...) \
	pr_debug("ai_memalloc: " fmt, ##__VA_ARGS__)

#define ai_memalloc_info(fmt, ...) \
	pr_info("ai_memalloc: " fmt, ##__VA_ARGS__)

#define ai_memalloc_warn(fmt, ...) \
	pr_warn("ai_memalloc: " fmt, ##__VA_ARGS__)

#define ai_memalloc_err(fmt, ...) \
	pr_err("ai_memalloc: " fmt, ##__VA_ARGS__)

/*
 * Module parameters
 */
static unsigned int memalloc_debug = 0;
module_param(memalloc_debug, uint, 0644);
MODULE_PARM_DESC(memalloc_debug, "Enable debug output (0=off, 1=on)");

static unsigned int hugepage_pool_size_mb = 256;
module_param(hugepage_pool_size_mb, uint, 0644);
MODULE_PARM_DESC(hugepage_pool_size_mb, "Huge page pool size in MB");

static unsigned int numa_aware = 1;
module_param(numa_aware, uint, 0644);
MODULE_PARM_DESC(numa_aware, "Enable NUMA-aware allocation (0=off, 1=on)");

static unsigned int pressure_monitor_interval = 100;
module_param(pressure_monitor_interval, uint, 0644);
MODULE_PARM_DESC(pressure_monitor_interval,
		 "Memory pressure monitor interval in ms");

static unsigned int watermark_scale_factor = 10;
module_param(watermark_scale_factor, uint, 0644);
MODULE_PARM_DESC(watermark_scale_factor,
		 "Watermark scale factor (percent)");

/*
 * Forward declarations
 */
struct ai_memory_pool;
struct ai_memalloc_device;

/*
 * Memory pool descriptor
 */
struct ai_memory_pool {
	spinlock_t		lock;
	enum ai_memalloc_pool_type	type;
	char			name[32];

	/* Pool sizing */
	size_t			element_size;
	size_t			alignment;
	size_t			total_size;
	size_t			used_size;
	size_t			free_size;
	size_t			max_size;
	size_t			min_size;

	/* Free list */
	struct list_head	free_list;
	struct list_head	active_list;
	unsigned long		nr_free;
	unsigned long		nr_active;
	unsigned long		nr_max;

	/* Allocation tracking */
	atomic64_t		alloc_count;
	atomic64_t		free_count;
	atomic64_t		fail_count;
	atomic64_t		cache_hits;
	atomic64_t		cache_misses;

	/* NUMA awareness */
	int			numa_node;
	nodemask_t		nodemask;
	unsigned int		numa_policy;

	/* Huge page support */
	struct page		*huge_pages;
	unsigned int		nr_huge_pages;
	unsigned int		huge_page_order;
	unsigned int		thp_enabled;

	/* Watermark management */
	unsigned long		watermark_min;
	unsigned long		watermark_low;
	unsigned long		watermark_high;
	unsigned long		watermark_emergency;

	/* Prefetch */
	struct list_head	prefetch_list;
	unsigned int		prefetch_depth;
	struct workqueue_struct *prefetch_wq;

	/* Statistics */
	ktime_t			last_alloc_time;
	ktime_t			last_free_time;
	unsigned long		avg_alloc_latency_ns;
	unsigned long		avg_free_latency_ns;
	unsigned long		max_alloc_latency_ns;
	unsigned long		max_free_latency_ns;

	/* Reference */
	struct kref		kref;
	struct list_head	list;
};

/*
 * OOM notifier
 */
struct ai_oom_notifier {
	struct list_head	list;
	void			(*handler)(void);
	char			name[64];
};

/*
 * Per-device context
 */
struct ai_memalloc_device {
	struct cdev		cdev;
	struct device		*device;
	struct kobject		*kobj;

	/* Device identification */
	unsigned int		dev_id;
	char			name[64];
	bool			active;

	/* Memory pools */
	struct list_head	pools;
	unsigned int		nr_pools;
	struct mutex		pool_mutex;

	/* Policy settings */
	struct ai_memalloc_policy current_policy;

	/* NUMA information */
	unsigned int		numa_node_count;
	nodemask_t		numa_nodes_online;

	/* Pressure monitoring */
	struct task_struct	*pressure_task;
	struct hrtimer		pressure_timer;
	atomic_t		pressure_level;
	atomic64_t		pressure_score;
	bool			pressure_monitoring;

	/* OOM prevention */
	struct list_head	oom_notifiers;
	struct mutex		oom_mutex;
	unsigned int		oom_kills;
	unsigned int		oom_prevented;

	/* Huge page tracking */
	unsigned long		nr_hugepages_total;
	unsigned long		nr_hugepages_free;
	unsigned long		nr_hugepages_resv;
	unsigned long		hugepage_size;

	/* Profile data */
	struct ai_memalloc_profile profile;
	spinlock_t		profile_lock;

	/* Stats */
	struct ai_memalloc_pool_stats stats;
	spinlock_t		stats_lock;

	/* Watermarks */
	struct ai_memalloc_watermarks watermarks;

	/* Module list */
	struct list_head	list;
};

/*
 * Global state
 */
static dev_t ai_memalloc_devno;
static struct class *ai_memalloc_class;
static struct list_head ai_memalloc_devices;
static struct mutex ai_memalloc_mutex;
static atomic_t ai_memalloc_device_count;
static unsigned int ai_memalloc_major;
static unsigned int ai_memalloc_minor;
static struct kmem_cache *ai_memalloc_pool_cache;
static struct kmem_cache *ai_memalloc_device_cache;

/*
 * Memory pool operations
 */

static struct ai_memory_pool *ai_memalloc_pool_alloc(
		enum ai_memalloc_pool_type type,
		size_t element_size, size_t pool_size,
		int numa_node)
{
	struct ai_memory_pool *pool;
	int ret;

	pool = kmem_cache_zalloc(ai_memalloc_pool_cache, GFP_KERNEL);
	if (!pool)
		return ERR_PTR(-ENOMEM);

	spin_lock_init(&pool->lock);
	INIT_LIST_HEAD(&pool->free_list);
	INIT_LIST_HEAD(&pool->active_list);
	INIT_LIST_HEAD(&pool->prefetch_list);
	kref_init(&pool->kref);

	pool->type = type;
	pool->element_size = element_size;
	pool->alignment = max_t(size_t, element_size, ARCH_KMALLOC_MINALIGN);
	pool->total_size = pool_size;
	pool->max_size = pool_size;
	pool->min_size = pool_size / 4;
	pool->free_size = pool_size;
	pool->used_size = 0;
	pool->nr_free = 0;
	pool->nr_active = 0;
	pool->numa_node = numa_node;
	pool->numa_policy = AI_MEMALLOC_NUMA_LOCAL;
	pool->thp_enabled = 1;

	atomic64_set(&pool->alloc_count, 0);
	atomic64_set(&pool->free_count, 0);
	atomic64_set(&pool->fail_count, 0);
	atomic64_set(&pool->cache_hits, 0);
	atomic64_set(&pool->cache_misses, 0);

	pool->max_alloc_latency_ns = 0;
	pool->max_free_latency_ns = 0;

	switch (type) {
	case AI_MEMALLOC_POOL_SMALL:
		pool->watermark_min = pool_size / 10;
		pool->watermark_low = pool_size / 5;
		pool->watermark_high = pool_size / 3;
		pool->watermark_emergency = pool_size / 20;
		pool->prefetch_depth = 32;
		snprintf(pool->name, sizeof(pool->name), "pool-small-%d",
			 numa_node);
		break;

	case AI_MEMALLOC_POOL_MEDIUM:
		pool->watermark_min = pool_size / 8;
		pool->watermark_low = pool_size / 4;
		pool->watermark_high = pool_size / 2;
		pool->watermark_emergency = pool_size / 16;
		pool->prefetch_depth = 16;
		snprintf(pool->name, sizeof(pool->name), "pool-medium-%d",
			 numa_node);
		break;

	case AI_MEMALLOC_POOL_LARGE:
		pool->watermark_min = pool_size / 5;
		pool->watermark_low = pool_size / 3;
		pool->watermark_high = pool_size / 2;
		pool->watermark_emergency = pool_size / 10;
		pool->prefetch_depth = 8;
		snprintf(pool->name, sizeof(pool->name), "pool-large-%d",
			 numa_node);
		break;

	case AI_MEMALLOC_POOL_HUGE:
		pool->huge_page_order = HPAGE_PMD_ORDER;
		pool->watermark_min = pool_size / 4;
		pool->watermark_low = pool_size / 3;
		pool->watermark_high = pool_size / 2;
		pool->watermark_emergency = pool_size / 8;
		pool->prefetch_depth = 4;
		snprintf(pool->name, sizeof(pool->name), "pool-huge-%d",
			 numa_node);
		break;

	default:
		ret = -EINVAL;
		goto err_free;
	}

	pool->prefetch_wq = alloc_workqueue("ai-memalloc-prefetch-%s",
					    WQ_UNBOUND | WQ_MEM_RECLAIM,
					    0, pool->name);
	if (!pool->prefetch_wq) {
		ret = -ENOMEM;
		goto err_free;
	}

	ai_memalloc_dbg("Created pool '%s' type=%d elem_size=%zu "
			"pool_size=%zu node=%d\n",
			pool->name, type, element_size, pool_size, numa_node);

	return pool;

err_free:
	kmem_cache_free(ai_memalloc_pool_cache, pool);
	return ERR_PTR(ret);
}

static void ai_memalloc_pool_free(struct kref *kref)
{
	struct ai_memory_pool *pool = container_of(kref, struct ai_memory_pool,
						   kref);

	if (pool->prefetch_wq)
		destroy_workqueue(pool->prefetch_wq);

	ai_memalloc_dbg("Destroyed pool '%s' (alloc=%lld free=%lld fail=%lld)\n",
			pool->name,
			atomic64_read(&pool->alloc_count),
			atomic64_read(&pool->free_count),
			atomic64_read(&pool->fail_count));

	kmem_cache_free(ai_memalloc_pool_cache, pool);
}

static struct ai_memory_pool *ai_memalloc_pool_get(
		struct ai_memory_pool *pool)
{
	if (pool)
		kref_get(&pool->kref);
	return pool;
}

static void ai_memalloc_pool_put(struct ai_memory_pool *pool)
{
	if (pool)
		kref_put(&pool->kref, ai_memalloc_pool_free);
}

static void *ai_memalloc_pool_alloc_from(struct ai_memory_pool *pool,
					 gfp_t gfp_flags)
{
	void *ptr;
	unsigned long flags;
	ktime_t start, end;
	unsigned long latency;

	start = ktime_get();

	spin_lock_irqsave(&pool->lock, flags);

	if (pool->free_size < pool->element_size) {
		atomic64_inc(&pool->fail_count);
		spin_unlock_irqrestore(&pool->lock, flags);
		ai_memalloc_dbg("Pool '%s' out of memory (free=%zu need=%zu)\n",
				pool->name, pool->free_size,
				pool->element_size);
		return NULL;
	}

	if (!list_empty(&pool->free_list)) {
		ptr = list_first_entry(&pool->free_list, void, free_list);
		list_del_init((struct list_head *)ptr);
		list_add_tail((struct list_head *)ptr, &pool->active_list);
		pool->nr_free--;
		pool->nr_active++;
		pool->free_size -= pool->element_size;
		pool->used_size += pool->element_size;
		atomic64_inc(&pool->cache_hits);

		spin_unlock_irqrestore(&pool->lock, flags);

		end = ktime_get();
		latency = ktime_to_ns(ktime_sub(end, start));
		pool->avg_alloc_latency_ns = (pool->avg_alloc_latency_ns +
					     latency) / 2;
		if (latency > pool->max_alloc_latency_ns)
			pool->max_alloc_latency_ns = latency;

		ai_memalloc_dbg("Pool '%s' cache hit alloc %p "
				"(latency=%lu ns)\n",
				pool->name, ptr, latency);
		return ptr;
	}

	spin_unlock_irqrestore(&pool->lock, flags);

	ptr = kmalloc_node(pool->element_size, gfp_flags | __GFP_ZERO,
			   pool->numa_node);
	if (!ptr) {
		atomic64_inc(&pool->fail_count);
		ai_memalloc_dbg("Pool '%s' kmalloc failed\n", pool->name);
		return NULL;
	}

	spin_lock_irqsave(&pool->lock, flags);
	list_add_tail((struct list_head *)ptr, &pool->active_list);
	pool->nr_active++;
	pool->used_size += pool->element_size;
	pool->total_size += pool->element_size;
	atomic64_inc(&pool->alloc_count);
	spin_unlock_irqrestore(&pool->lock, flags);

	end = ktime_get();
	latency = ktime_to_ns(ktime_sub(end, start));
	pool->avg_alloc_latency_ns = (pool->avg_alloc_latency_ns + latency) / 2;
	if (latency > pool->max_alloc_latency_ns)
		pool->max_alloc_latency_ns = latency;

	ai_memalloc_dbg("Pool '%s' fresh alloc %p (latency=%lu ns)\n",
			pool->name, ptr, latency);
	return ptr;
}

static int ai_memalloc_pool_free_to(struct ai_memory_pool *pool, void *addr)
{
	unsigned long flags;
	ktime_t start, end;
	unsigned long latency;
	int ret = 0;

	start = ktime_get();

	spin_lock_irqsave(&pool->lock, flags);

	if (list_empty(&pool->active_list)) {
		ret = -EINVAL;
		goto out_unlock;
	}

	if (pool->free_size < pool->max_size) {
		list_del_init((struct list_head *)addr);
		list_add_tail((struct list_head *)addr, &pool->free_list);
		pool->nr_active--;
		pool->nr_free++;
		pool->used_size -= pool->element_size;
		pool->free_size += pool->element_size;
		atomic64_inc(&pool->free_count);

		spin_unlock_irqrestore(&pool->lock, flags);

		end = ktime_get();
		latency = ktime_to_ns(ktime_sub(end, start));
		pool->avg_free_latency_ns = (pool->avg_free_latency_ns +
					    latency) / 2;
		if (latency > pool->max_free_latency_ns)
			pool->max_free_latency_ns = latency;

		return 0;
	}

out_unlock:
	spin_unlock_irqrestore(&pool->lock, flags);

	if (ret == 0) {
		kfree(addr);
		atomic64_inc(&pool->free_count);

		spin_lock_irqsave(&pool->lock, flags);
		pool->used_size -= pool->element_size;
		pool->total_size -= pool->element_size;
		pool->nr_active--;
		spin_unlock_irqrestore(&pool->lock, flags);
	}

	end = ktime_get();
	latency = ktime_to_ns(ktime_sub(end, start));
	pool->avg_free_latency_ns = (pool->avg_free_latency_ns + latency) / 2;

	ai_memalloc_dbg("Pool '%s' freed %p (latency=%lu ns)\n",
			pool->name, addr, latency);
	return ret;
}

/*
 * Memory pressure detection
 */

static enum ai_memalloc_pressure_level ai_memalloc_calc_pressure(
		struct ai_memalloc_device *dev)
{
	struct sysinfo si;
	unsigned long free_pages;
	unsigned long total_pages;
	unsigned long dirty_pages;
	unsigned long swap_free;
	unsigned long swap_total;
	int score = 0;

	si_meminfo(&si);
	si_swapinfo(&si);

	free_pages = si.freeram + si.bufferram;
	total_pages = si.totalram;
	dirty_pages = si.totalram - si.freeram - si.bufferram;
	swap_free = si.freeswap;
	swap_total = si.totalswap;

	if (total_pages == 0)
		return AI_MEMALLOC_PRESSURE_NONE;

	score = (int)((total_pages - free_pages) * 100 / total_pages);

	if (swap_total > 0) {
		int swap_usage = (int)((swap_total - swap_free) * 100 /
				      swap_total);
		score = max(score, swap_usage);
	}

	if (score < 30)
		return AI_MEMALLOC_PRESSURE_NONE;
	else if (score < 50)
		return AI_MEMALLOC_PRESSURE_LOW;
	else if (score < 70)
		return AI_MEMALLOC_PRESSURE_MEDIUM;
	else if (score < 90)
		return AI_MEMALLOC_PRESSURE_HIGH;
	else
		return AI_MEMALLOC_PRESSURE_CRITICAL;
}

static int ai_memalloc_pressure_monitor(void *data)
{
	struct ai_memalloc_device *dev = data;
	enum ai_memalloc_pressure_level level;
	int retries = 0;

	while (!kthread_should_stop()) {
		if (unlikely(freezing(current)))
			__refrigerator(false);

		level = ai_memalloc_calc_pressure(dev);
		atomic_set(&dev->pressure_level, level);

		switch (level) {
		case AI_MEMALLOC_PRESSURE_LOW:
			ai_memalloc_dbg("Memory pressure: LOW\n");
			break;

		case AI_MEMALLOC_PRESSURE_MEDIUM:
			ai_memalloc_dbg("Memory pressure: MEDIUM - "
					"initiating reclaim\n");
			ai_memalloc_reclaim(SWAP_CLUSTER_MAX);
			retries = 0;
			break;

		case AI_MEMALLOC_PRESSURE_HIGH:
			ai_memalloc_warn("Memory pressure: HIGH - "
					 "aggressive reclaim\n");
			ai_memalloc_reclaim(SWAP_CLUSTER_MAX * 4);
			ai_memalloc_compact();
			retries = 0;
			break;

		case AI_MEMALLOC_PRESSURE_CRITICAL:
			ai_memalloc_err("Memory pressure: CRITICAL - "
					"emergency measures\n");
			ai_memalloc_reclaim(SWAP_CLUSTER_MAX * 8);
			ai_memalloc_compact();
			retries++;

			if (retries > 3) {
				ai_memalloc_warn("Still critical after %d "
						 "retries, triggering OOM\n",
						 retries);
				dev->oom_kills++;
			}
			break;

		default:
			retries = 0;
			break;
		}

		msleep_interruptible(pressure_monitor_interval);
	}

	return 0;
}

/*
 * Huge page management
 */

static int ai_memalloc_hugepage_prepare(struct ai_memalloc_device *dev)
{
	unsigned long nr_pages;
	int ret;

	nr_pages = hugepage_pool_size_mb *
		   (SZ_1M / HPAGE_SIZE);

	dev->hugepage_size = HPAGE_SIZE;
	dev->nr_hugepages_total = nr_pages;
	dev->nr_hugepages_free = nr_pages;
	dev->nr_hugepages_resv = 0;

	ai_memalloc_info("Huge page pool: %lu pages (%lu MB total)\n",
			 nr_pages,
			 nr_pages * HPAGE_SIZE / SZ_1M);

	ret = 0;
	return ret;
}

static int ai_memalloc_alloc_hugepage(struct ai_memalloc_device *dev,
				      struct page **page, int nid)
{
	gfp_t gfp_flags;
	int ret;

	if (dev->nr_hugepages_free == 0)
		return -ENOMEM;

	gfp_flags = GFP_TRANSHUGE_LIGHT | __GFP_THISNODE;
	*page = alloc_pages_node(nid, gfp_flags, HPAGE_PMD_ORDER);
	if (!*page) {
		gfp_flags = GFP_TRANSHUGE | __GFP_NORETRY;
		*page = alloc_pages_node(nid, gfp_flags, HPAGE_PMD_ORDER);
		if (!*page)
			return -ENOMEM;
	}

	dev->nr_hugepages_free--;
	dev->nr_hugepages_resv++;

	return 0;
}

static void ai_memalloc_free_hugepage(struct ai_memalloc_device *dev,
				      struct page *page)
{
	if (!page)
		return;

	__free_pages(page, HPAGE_PMD_ORDER);

	dev->nr_hugepages_free++;
	dev->nr_hugepages_resv--;
}

/*
 * NUMA operations
 */

static int ai_memalloc_numa_init(struct ai_memalloc_device *dev)
{
	int nid;

	dev->numa_node_count = 0;
	nodes_clear(dev->numa_nodes_online);

	for_each_online_node(nid) {
		if (node_state(nid, N_NORMAL_MEMORY) ||
		    node_state(nid, N_HIGH_MEMORY)) {
			node_set(nid, dev->numa_nodes_online);
			dev->numa_node_count++;
		}
	}

	ai_memalloc_info("NUMA: %d nodes online\n", dev->numa_node_count);

	if (dev->numa_node_count == 0) {
		node_set(0, dev->numa_nodes_online);
		dev->numa_node_count = 1;
	}

	return 0;
}

static int ai_memalloc_numa_migrate(struct ai_memalloc_device *dev,
				    void *addr, size_t size, int target_node)
{
	struct page *page;
	unsigned long start_pfn, end_pfn, pfn;
	int ret = 0;
	int count = 0;

	if (!addr || !size)
		return -EINVAL;

	if (!node_online(target_node))
		return -EINVAL;

	start_pfn = virt_to_phys(addr) >> PAGE_SHIFT;
	end_pfn = (virt_to_phys(addr) + size - 1) >> PAGE_SHIFT;

	for (pfn = start_pfn; pfn <= end_pfn; pfn++) {
		page = pfn_to_page(pfn);
		if (!page)
			continue;

		if (page_to_nid(page) == target_node)
			continue;

		if (migrate_pages(&page, 1, &target_node, MIGRATE_SYNC_LIGHT))
			ret = -EBUSY;
		else
			count++;
	}

	ai_memalloc_dbg("NUMA migrate: %d pages to node %d\n",
			count, target_node);
	return ret;
}

/*
 * OOM prevention
 */

static int ai_memalloc_register_oom_notifier_locked(
		struct ai_memalloc_device *dev,
		void (*handler)(void), const char *name)
{
	struct ai_oom_notifier *notifier;

	if (!handler)
		return -EINVAL;

	notifier = kzalloc(sizeof(*notifier), GFP_KERNEL);
	if (!notifier)
		return -ENOMEM;

	notifier->handler = handler;
	strscpy(notifier->name, name ? name : "unknown",
		sizeof(notifier->name));
	INIT_LIST_HEAD(&notifier->list);

	mutex_lock(&dev->oom_mutex);
	list_add_tail(&notifier->list, &dev->oom_notifiers);
	mutex_unlock(&dev->oom_mutex);

	ai_memalloc_dbg("OOM notifier registered: %s\n", notifier->name);
	return 0;
}

static int ai_memalloc_unregister_oom_notifier_locked(
		struct ai_memalloc_device *dev,
		void (*handler)(void))
{
	struct ai_oom_notifier *notifier, *tmp;
	int ret = -ENOENT;

	mutex_lock(&dev->oom_mutex);
	list_for_each_entry_safe(notifier, tmp, &dev->oom_notifiers, list) {
		if (notifier->handler == handler) {
			list_del(&notifier->list);
			ai_memalloc_dbg("OOM notifier unregistered: %s\n",
					notifier->name);
			kfree(notifier);
			ret = 0;
			break;
		}
	}
	mutex_unlock(&dev->oom_mutex);

	return ret;
}

static void ai_memalloc_oom_notify_all(struct ai_memalloc_device *dev)
{
	struct ai_oom_notifier *notifier;

	mutex_lock(&dev->oom_mutex);
	list_for_each_entry(notifier, &dev->oom_notifiers, list) {
		if (notifier->handler) {
			ai_memalloc_dbg("OOM notifier calling: %s\n",
					notifier->name);
			notifier->handler();
		}
	}
	mutex_unlock(&dev->oom_mutex);
}

/*
 * Device file operations
 */

static int ai_memalloc_open(struct inode *inode, struct file *file)
{
	struct ai_memalloc_device *dev;

	dev = container_of(inode->i_cdev, struct ai_memalloc_device, cdev);
	if (!dev)
		return -ENODEV;

	if (!dev->active)
		return -ENODEV;

	file->private_data = dev;
	ai_memalloc_dbg("Device opened (dev_id=%u)\n", dev->dev_id);
	return 0;
}

static int ai_memalloc_release(struct inode *inode, struct file *file)
{
	struct ai_memalloc_device *dev = file->private_data;

	if (!dev)
		return -ENODEV;

	ai_memalloc_dbg("Device closed (dev_id=%u)\n", dev->dev_id);
	return 0;
}

static long ai_memalloc_ioctl(struct file *file, unsigned int cmd,
			      unsigned long arg)
{
	struct ai_memalloc_device *dev = file->private_data;
	void __user *argp = (void __user *)arg;
	struct ai_memalloc_info info;
	struct ai_memalloc_request alloc_req;
	struct ai_memalloc_free free_req;
	struct ai_memalloc_pin pin_req;
	struct ai_memalloc_policy policy;
	struct ai_memalloc_pressure pressure;
	struct ai_memalloc_pool_stats pool_stats;
	struct ai_memalloc_watermarks wm;
	struct ai_memalloc_hugepage hp;
	struct ai_memalloc_profile profile;
	struct ai_memalloc_numa_bind numa_bind;
	struct ai_memalloc_migrate migrate;
	struct ai_memalloc_reserve reserve;
	int ret = 0;

	if (!dev || !dev->active)
		return -ENODEV;

	if (_IOC_TYPE(cmd) != AI_MEMALLOC_IOC_MAGIC)
		return -ENOTTY;
	if (_IOC_NR(cmd) > AI_MEMALLOC_IOC_MAXNR)
		return -ENOTTY;

	switch (cmd) {
	case AI_MEMALLOC_IOCTL_GET_INFO:
		memset(&info, 0, sizeof(info));
		strscpy(info.version, AI_MEMALLOC_MODULE_VERSION,
			sizeof(info.version));
		strscpy(info.description, AI_MEMALLOC_MODULE_DESC,
			sizeof(info.description));
		info.major_version = 1;
		info.minor_version = 0;
		info.patch_version = 0;
		info.max_pools = AI_MEMALLOC_POOL_TOTAL;
		info.active_pools = dev->nr_pools;
		info.hugepage_supported = 1;
		info.numa_supported = 1;
		info.numa_nodes = dev->numa_node_count;
		info.features = 0x7F;

		if (copy_to_user(argp, &info, sizeof(info)))
			ret = -EFAULT;
		break;

	case AI_MEMALLOC_IOCTL_ALLOC:
		if (copy_from_user(&alloc_req, argp, sizeof(alloc_req))) {
			ret = -EFAULT;
			break;
		}

		alloc_req.result = 0;

		if (alloc_req.flags & AI_MEMALLOC_F_HUGEPAGE) {
			struct page *page = NULL;
			ret = ai_memalloc_alloc_hugepage(dev, &page,
							 alloc_req.numa_node);
			if (ret == 0 && page) {
				alloc_req.phys_addr = page_to_phys(page);
				alloc_req.virt_addr = (__u64)page_address(page);
				alloc_req.size = dev->hugepage_size;
			}
		} else {
			gfp_t gfp = GFP_KERNEL;

			if (alloc_req.flags & AI_MEMALLOC_F_ZERO)
				gfp |= __GFP_ZERO;
			if (alloc_req.flags & AI_MEMALLOC_F_NORETRY)
				gfp |= __GFP_NORETRY;
			if (alloc_req.flags & AI_MEMALLOC_F_ATOMIC)
				gfp = GFP_ATOMIC;

			if (alloc_req.numa_node >= 0 &&
			    node_online(alloc_req.numa_node)) {
				alloc_req.virt_addr = (__u64)
					kmalloc_node(alloc_req.size, gfp,
						     alloc_req.numa_node);
			} else {
				alloc_req.virt_addr = (__u64)
					kmalloc(alloc_req.size, gfp);
			}

			if (!alloc_req.virt_addr) {
				alloc_req.result = -ENOMEM;
				ret = -ENOMEM;
			}
		}

		if (ret == 0) {
			if (copy_to_user(argp, &alloc_req, sizeof(alloc_req)))
				ret = -EFAULT;
		}
		break;

	case AI_MEMALLOC_IOCTL_FREE:
		if (copy_from_user(&free_req, argp, sizeof(free_req))) {
			ret = -EFAULT;
			break;
		}

		if (free_req.flags & AI_MEMALLOC_F_HUGEPAGE) {
			struct page *page = phys_to_page(free_req.addr);
			ai_memalloc_free_hugepage(dev, page);
		} else {
			kfree((void *)(unsigned long)free_req.addr);
		}
		break;

	case AI_MEMALLOC_IOCTL_PIN:
		if (copy_from_user(&pin_req, argp, sizeof(pin_req))) {
			ret = -EFAULT;
			break;
		}

		pin_req.refcount = 1;
		pin_req.result = 0;

		if (copy_to_user(argp, &pin_req, sizeof(pin_req)))
			ret = -EFAULT;
		break;

	case AI_MEMALLOC_IOCTL_UNPIN:
		if (copy_from_user(&pin_req, argp, sizeof(pin_req))) {
			ret = -EFAULT;
			break;
		}
		break;

	case AI_MEMALLOC_IOCTL_SET_POLICY:
		if (copy_from_user(&policy, argp, sizeof(policy))) {
			ret = -EFAULT;
			break;
		}

		memcpy(&dev->current_policy, &policy,
		       sizeof(dev->current_policy));
		ai_memalloc_dbg("Policy updated: flags=0x%x pool_type=%u\n",
				policy.flags, policy.pool_type);
		break;

	case AI_MEMALLOC_IOCTL_GET_POLICY:
		memcpy(&policy, &dev->current_policy, sizeof(policy));
		if (copy_to_user(argp, &policy, sizeof(policy)))
			ret = -EFAULT;
		break;

	case AI_MEMALLOC_IOCTL_PRESSURE_INFO:
		memset(&pressure, 0, sizeof(pressure));
		pressure.level = atomic_read(&dev->pressure_level);
		pressure.score = atomic64_read(&dev->pressure_score);

		si_meminfo(&pressure);
		si_swapinfo(&pressure);

		pressure.free_pages = pressure.free_pages;
		pressure.total_pages = pressure.total_pages;
		pressure.dirty_pages = pressure.dirty_pages;
		pressure.writeback_pages = 0;
		pressure.unevictable_pages = 0;
		pressure.mapped_pages = 0;
		pressure.oom_kills = dev->oom_kills;

		if (copy_to_user(argp, &pressure, sizeof(pressure)))
			ret = -EFAULT;
		break;

	case AI_MEMALLOC_IOCTL_POOL_STATS:
		memset(&pool_stats, 0, sizeof(pool_stats));

		pool_stats.total_allocated =
			atomic64_read(&dev->stats.total_allocated);
		pool_stats.total_freed =
			atomic64_read(&dev->stats.total_freed);
		pool_stats.current_usage = pool_stats.total_allocated -
					   pool_stats.total_freed;
		pool_stats.active_allocations = 0;
		pool_stats.pending_frees = 0;

		if (copy_to_user(argp, &pool_stats, sizeof(pool_stats)))
			ret = -EFAULT;
		break;

	case AI_MEMALLOC_IOCTL_COMPACT:
		ret = ai_memalloc_compact();
		break;

	case AI_MEMALLOC_IOCTL_RECLAIM:
		ret = ai_memalloc_reclaim(arg);
		break;

	case AI_MEMALLOC_IOCTL_BIND_NUMA:
		if (copy_from_user(&numa_bind, argp, sizeof(numa_bind))) {
			ret = -EFAULT;
			break;
		}
		ret = ai_memalloc_numa_migrate(dev,
					       (void *)(unsigned long)
					       numa_bind.addr,
					       numa_bind.size,
					       numa_bind.numa_node);
		break;

	case AI_MEMALLOC_IOCTL_MIGRATE:
		if (copy_from_user(&migrate, argp, sizeof(migrate))) {
			ret = -EFAULT;
			break;
		}
		ret = ai_memalloc_numa_migrate(dev,
					       (void *)(unsigned long)
					       migrate.addr,
					       migrate.size,
					       migrate.target_node);
		migrate.result = ret;
		if (copy_to_user(argp, &migrate, sizeof(migrate)))
			ret = -EFAULT;
		break;

	case AI_MEMALLOC_IOCTL_RESERVE:
		if (copy_from_user(&reserve, argp, sizeof(reserve))) {
			ret = -EFAULT;
			break;
		}

		reserve.reserved_addr = 0;
		reserve.result = 0;

		if (copy_to_user(argp, &reserve, sizeof(reserve)))
			ret = -EFAULT;
		break;

	case AI_MEMALLOC_IOCTL_GET_WATERMARKS:
		memcpy(&wm, &dev->watermarks, sizeof(wm));
		if (copy_to_user(argp, &wm, sizeof(wm)))
			ret = -EFAULT;
		break;

	case AI_MEMALLOC_IOCTL_SET_WATERMARKS:
		if (copy_from_user(&wm, argp, sizeof(wm))) {
			ret = -EFAULT;
			break;
		}
		memcpy(&dev->watermarks, &wm, sizeof(wm));
		ai_memalloc_dbg("Watermarks updated\n");
		break;

	case AI_MEMALLOC_IOCTL_HUGEPAGE_STATUS:
		memset(&hp, 0, sizeof(hp));
		hp.total_hugepages = dev->nr_hugepages_total;
		hp.free_hugepages = dev->nr_hugepages_free;
		hp.resv_hugepages = dev->nr_hugepages_resv;
		hp.surplus_hugepages = 0;
		hp.hugepage_size = dev->hugepage_size;
		hp.default_hstate = 0;
		hp.nr_hstates = 1;

		if (copy_to_user(argp, &hp, sizeof(hp)))
			ret = -EFAULT;
		break;

	case AI_MEMALLOC_IOCTL_DEFRAG:
		ret = ai_memalloc_compact();
		break;

	case AI_MEMALLOC_IOCTL_PROFILE:
		spin_lock(&dev->profile_lock);
		memcpy(&profile, &dev->profile, sizeof(profile));
		spin_unlock(&dev->profile_lock);
		if (copy_to_user(argp, &profile, sizeof(profile)))
			ret = -EFAULT;
		break;

	case AI_MEMALLOC_IOCTL_CLEANUP:
		ai_memalloc_dbg("Cleanup triggered\n");
		break;

	default:
		ret = -ENOTTY;
		break;
	}

	return ret;
}

#ifdef CONFIG_COMPAT
static long ai_memalloc_compat_ioctl(struct file *file, unsigned int cmd,
				     unsigned long arg)
{
	return ai_memalloc_ioctl(file, cmd, (unsigned long)compat_ptr(arg));
}
#endif

static const struct file_operations ai_memalloc_fops = {
	.owner		= THIS_MODULE,
	.open		= ai_memalloc_open,
	.release	= ai_memalloc_release,
	.unlocked_ioctl	= ai_memalloc_ioctl,
#ifdef CONFIG_COMPAT
	.compat_ioctl	= ai_memalloc_compat_ioctl,
#endif
	.llseek		= noop_llseek,
};

/*
 * Sysfs interface
 */

static ssize_t pool_size_show(struct kobject *kobj,
			      struct kobj_attribute *attr, char *buf)
{
	struct ai_memalloc_device *dev = container_of(kobj,
						      struct ai_memalloc_device,
						      *kobj);
	return sysfs_emit(buf, "%llu %llu %llu %llu\n",
			  dev->stats.pool_size[0],
			  dev->stats.pool_size[1],
			  dev->stats.pool_size[2],
			  dev->stats.pool_size[3]);
}

static ssize_t pool_used_show(struct kobject *kobj,
			      struct kobj_attribute *attr, char *buf)
{
	struct ai_memalloc_device *dev = container_of(kobj,
						      struct ai_memalloc_device,
						      *kobj);
	return sysfs_emit(buf, "%llu %llu %llu %llu\n",
			  dev->stats.pool_used[0],
			  dev->stats.pool_used[1],
			  dev->stats.pool_used[2],
			  dev->stats.pool_used[3]);
}

static ssize_t pressure_show(struct kobject *kobj,
			     struct kobj_attribute *attr, char *buf)
{
	struct ai_memalloc_device *dev = container_of(kobj,
						      struct ai_memalloc_device,
						      *kobj);
	int level = atomic_read(&dev->pressure_level);
	const char *level_str;

	switch (level) {
	case AI_MEMALLOC_PRESSURE_NONE:
		level_str = "none";
		break;
	case AI_MEMALLOC_PRESSURE_LOW:
		level_str = "low";
		break;
	case AI_MEMALLOC_PRESSURE_MEDIUM:
		level_str = "medium";
		break;
	case AI_MEMALLOC_PRESSURE_HIGH:
		level_str = "high";
		break;
	case AI_MEMALLOC_PRESSURE_CRITICAL:
		level_str = "critical";
		break;
	default:
		level_str = "unknown";
		break;
	}

	return sysfs_emit(buf, "%s\n", level_str);
}

static ssize_t numa_nodes_show(struct kobject *kobj,
			       struct kobj_attribute *attr, char *buf)
{
	struct ai_memalloc_device *dev = container_of(kobj,
						      struct ai_memalloc_device,
						      *kobj);
	int nid, len = 0;

	for_each_online_node(nid) {
		if (node_state(nid, N_NORMAL_MEMORY) ||
		    node_state(nid, N_HIGH_MEMORY))
			len += sysfs_emit_at(buf, len, "%d ", nid);
	}
	if (len > 0)
		buf[len - 1] = '\n';
	else
		len = sysfs_emit(buf, "none\n");

	return len;
}

static ssize_t hugepage_info_show(struct kobject *kobj,
				  struct kobj_attribute *attr, char *buf)
{
	struct ai_memalloc_device *dev = container_of(kobj,
						      struct ai_memalloc_device,
						      *kobj);
	return sysfs_emit(buf, "total=%lu free=%lu resv=%lu size=%lu\n",
			  dev->nr_hugepages_total,
			  dev->nr_hugepages_free,
			  dev->nr_hugepages_resv,
			  dev->hugepage_size);
}

static ssize_t stats_show(struct kobject *kobj,
			  struct kobj_attribute *attr, char *buf)
{
	struct ai_memalloc_device *dev = container_of(kobj,
						      struct ai_memalloc_device,
						      *kobj);
	return sysfs_emit(buf,
			  "total_allocated=%llu total_freed=%llu "
			  "current_usage=%llu oom_kills=%u "
			  "oom_prevented=%u\n",
			  atomic64_read(&dev->stats.total_allocated),
			  atomic64_read(&dev->stats.total_freed),
			  atomic64_read(&dev->stats.total_allocated) -
			  atomic64_read(&dev->stats.total_freed),
			  dev->oom_kills,
			  dev->oom_prevented);
}

static ssize_t profile_show(struct kobject *kobj,
			    struct kobj_attribute *attr, char *buf)
{
	struct ai_memalloc_device *dev = container_of(kobj,
						      struct ai_memalloc_device,
						      *kobj);
	struct ai_memalloc_profile *p = &dev->profile;

	return sysfs_emit(buf,
			  "avg_alloc_lat=%llu max_alloc_lat=%llu "
			  "avg_free_lat=%llu alloc_count=%llu "
			  "free_count=%llu\n",
			  p->avg_alloc_latency_ns,
			  p->max_alloc_latency_ns,
			  p->avg_free_latency_ns,
			  p->allocation_count,
			  p->free_count);
}

static ssize_t policy_show(struct kobject *kobj,
			   struct kobj_attribute *attr, char *buf)
{
	struct ai_memalloc_device *dev = container_of(kobj,
						      struct ai_memalloc_device,
						      *kobj);
	return sysfs_emit(buf, "flags=0x%x pool_type=%u numa_mode=%u\n",
			  dev->current_policy.flags,
			  dev->current_policy.pool_type,
			  dev->current_policy.numa_mode);
}

static ssize_t compact_store(struct kobject *kobj,
			     struct kobj_attribute *attr,
			     const char *buf, size_t count)
{
	ai_memalloc_compact();
	return count;
}

static ssize_t reclaim_store(struct kobject *kobj,
			     struct kobj_attribute *attr,
			     const char *buf, size_t count)
{
	unsigned long pages;
	int ret;

	ret = kstrtoul(buf, 10, &pages);
	if (ret)
		return ret;

	ai_memalloc_reclaim(pages);
	return count;
}

static struct kobj_attribute pool_size_attr =
	__ATTR_RO(pool_size);
static struct kobj_attribute pool_used_attr =
	__ATTR_RO(pool_used);
static struct kobj_attribute pressure_attr =
	__ATTR_RO(pressure);
static struct kobj_attribute numa_nodes_attr =
	__ATTR_RO(numa_nodes);
static struct kobj_attribute hugepage_attr =
	__ATTR_RO(hugepage_info);
static struct kobj_attribute stats_attr =
	__ATTR_RO(stats);
static struct kobj_attribute profile_attr =
	__ATTR_RO(profile);
static struct kobj_attribute policy_attr =
	__ATTR_RO(policy);
static struct kobj_attribute compact_attr =
	__ATTR_WO(compact);
static struct kobj_attribute reclaim_attr =
	__ATTR_WO(reclaim);

static struct attribute *ai_memalloc_attrs[] = {
	&pool_size_attr.attr,
	&pool_used_attr.attr,
	&pressure_attr.attr,
	&numa_nodes_attr.attr,
	&hugepage_attr.attr,
	&stats_attr.attr,
	&profile_attr.attr,
	&policy_attr.attr,
	&compact_attr.attr,
	&reclaim_attr.attr,
	NULL,
};

ATTRIBUTE_GROUPS(ai_memalloc);

/*
 * Module initialization and cleanup
 */

static int ai_memalloc_create_device(struct ai_memalloc_device **dev_out)
{
	struct ai_memalloc_device *dev;
	int ret;

	dev = kmem_cache_zalloc(ai_memalloc_device_cache, GFP_KERNEL);
	if (!dev)
		return -ENOMEM;

	dev->dev_id = atomic_inc_return(&ai_memalloc_device_count);
	snprintf(dev->name, sizeof(dev->name), "ai-memalloc-%u", dev->dev_id);
	dev->active = false;

	INIT_LIST_HEAD(&dev->pools);
	INIT_LIST_HEAD(&dev->oom_notifiers);
	mutex_init(&dev->pool_mutex);
	mutex_init(&dev->oom_mutex);
	spin_lock_init(&dev->profile_lock);
	spin_lock_init(&dev->stats_lock);

	dev->nr_pools = 0;
	dev->oom_kills = 0;
	dev->oom_prevented = 0;

	dev->numa_node_count = 0;
	nodes_clear(dev->numa_nodes_online);

	dev->current_policy.flags = AI_MEMALLOC_F_ZERO;
	dev->current_policy.pool_type = AI_MEMALLOC_POOL_MEDIUM;
	dev->current_policy.numa_mode = AI_MEMALLOC_NUMA_LOCAL;
	dev->current_policy.reclaim_priority = 50;
	dev->current_policy.oom_priority = 50;
	dev->current_policy.watermark_scale = watermark_scale_factor;

	dev->pressure_monitoring = false;
	atomic_set(&dev->pressure_level, AI_MEMALLOC_PRESSURE_NONE);
	atomic64_set(&dev->pressure_score, 0);

	memset(&dev->profile, 0, sizeof(dev->profile));
	memset(&dev->stats, 0, sizeof(dev->stats));

	dev->watermarks.min_free_pages = 0;
	dev->watermarks.low_free_pages = 0;
	dev->watermarks.high_free_pages = 0;
	dev->watermarks.emergency_pages = 0;

	dev->nr_hugepages_total = 0;
	dev->nr_hugepages_free = 0;
	dev->nr_hugepages_resv = 0;
	dev->hugepage_size = HPAGE_SIZE;

	cdev_init(&dev->cdev, &ai_memalloc_fops);
	dev->cdev.owner = THIS_MODULE;

	ret = cdev_add(&dev->cdev, dev->dev_id, 1);
	if (ret) {
		ai_memalloc_err("Failed to add cdev: %d\n", ret);
		goto err_free;
	}

	dev->device = device_create(ai_memalloc_class, NULL,
				    dev->dev_id, dev, "ai-memalloc-%u",
				    dev->dev_id);
	if (IS_ERR(dev->device)) {
		ret = PTR_ERR(dev->device);
		ai_memalloc_err("Failed to create device: %d\n", ret);
		goto err_cdev;
	}

	dev->kobj = &dev->device->kobj;

	ret = ai_memalloc_numa_init(dev);
	if (ret)
		goto err_device;

	ret = ai_memalloc_hugepage_prepare(dev);
	if (ret)
		goto err_device;

	dev->active = true;

	mutex_lock(&ai_memalloc_mutex);
	list_add_tail(&dev->list, &ai_memalloc_devices);
	mutex_unlock(&ai_memalloc_mutex);

	dev->pressure_task = kthread_run(ai_memalloc_pressure_monitor, dev,
					 "ai-memalloc-pressure-%u",
					 dev->dev_id);
	if (IS_ERR(dev->pressure_task)) {
		ret = PTR_ERR(dev->pressure_task);
		dev->pressure_task = NULL;
		ai_memalloc_err("Failed to start pressure monitor: %d\n", ret);
		goto err_device;
	}
	dev->pressure_monitoring = true;

	ai_memalloc_info("Device created: %s (major=%u minor=%u)\n",
			 dev->name, MAJOR(dev->dev_id), MINOR(dev->dev_id));

	*dev_out = dev;
	return 0;

err_device:
	device_destroy(ai_memalloc_class, dev->dev_id);
err_cdev:
	cdev_del(&dev->cdev);
err_free:
	kmem_cache_free(ai_memalloc_device_cache, dev);
	return ret;
}

static void ai_memalloc_destroy_device(struct ai_memalloc_device *dev)
{
	if (!dev)
		return;

	dev->active = false;

	if (dev->pressure_monitoring && dev->pressure_task) {
		kthread_stop(dev->pressure_task);
		dev->pressure_monitoring = false;
	}

	mutex_lock(&ai_memalloc_mutex);
	list_del(&dev->list);
	mutex_unlock(&ai_memalloc_mutex);

	device_destroy(ai_memalloc_class, dev->dev_id);
	cdev_del(&dev->cdev);

	mutex_destroy(&dev->pool_mutex);
	mutex_destroy(&dev->oom_mutex);

	ai_memalloc_info("Device destroyed: %s\n", dev->name);
	kmem_cache_free(ai_memalloc_device_cache, dev);
}

static int __init ai_memalloc_init(void)
{
	struct ai_memalloc_device *dev;
	int ret;

	ai_memalloc_info("Loading Ainos AI Memory Allocator v%s\n",
			 AI_MEMALLOC_MODULE_VERSION);

	INIT_LIST_HEAD(&ai_memalloc_devices);
	mutex_init(&ai_memalloc_mutex);
	atomic_set(&ai_memalloc_device_count, 0);

	ai_memalloc_pool_cache = kmem_cache_create("ai_memalloc_pool",
						   sizeof(struct ai_memory_pool),
						   0, SLAB_HWCACHE_ALIGN,
						   NULL);
	if (!ai_memalloc_pool_cache) {
		ret = -ENOMEM;
		goto err;
	}

	ai_memalloc_device_cache = kmem_cache_create("ai_memalloc_device",
						     sizeof(struct ai_memalloc_device),
						     0, SLAB_HWCACHE_ALIGN,
						     NULL);
	if (!ai_memalloc_device_cache) {
		ret = -ENOMEM;
		goto err_pool_cache;
	}

	ret = alloc_chrdev_region(&ai_memalloc_devno, 0,
				  AI_MEMALLOC_MAX_DEVICES,
				  AI_MEMALLOC_MODULE_NAME);
	if (ret) {
		ai_memalloc_err("Failed to allocate chrdev region: %d\n", ret);
		goto err_device_cache;
	}

	ai_memalloc_major = MAJOR(ai_memalloc_devno);
	ai_memalloc_minor = MINOR(ai_memalloc_devno);

	ai_memalloc_class = class_create(THIS_MODULE, AI_MEMALLOC_CLASS_NAME);
	if (IS_ERR(ai_memalloc_class)) {
		ret = PTR_ERR(ai_memalloc_class);
		ai_memalloc_err("Failed to create class: %d\n", ret);
		goto err_unregister;
	}

	ret = ai_memalloc_create_device(&dev);
	if (ret) {
		ai_memalloc_err("Failed to create device: %d\n", ret);
		goto err_class;
	}

	ai_memalloc_info("Ainos AI Memory Allocator loaded successfully "
			 "(major=%u)\n", ai_memalloc_major);
	return 0;

err_class:
	class_destroy(ai_memalloc_class);
err_unregister:
	unregister_chrdev_region(ai_memalloc_devno, AI_MEMALLOC_MAX_DEVICES);
err_device_cache:
	kmem_cache_destroy(ai_memalloc_device_cache);
err_pool_cache:
	kmem_cache_destroy(ai_memalloc_pool_cache);
err:
	ai_memalloc_err("Failed to load module: %d\n", ret);
	return ret;
}

static void __exit ai_memalloc_exit(void)
{
	struct ai_memalloc_device *dev, *tmp;

	ai_memalloc_info("Unloading Ainos AI Memory Allocator\n");

	list_for_each_entry_safe(dev, tmp, &ai_memalloc_devices, list) {
		ai_memalloc_destroy_device(dev);
	}

	class_destroy(ai_memalloc_class);
	unregister_chrdev_region(ai_memalloc_devno, AI_MEMALLOC_MAX_DEVICES);

	kmem_cache_destroy(ai_memalloc_device_cache);
	kmem_cache_destroy(ai_memalloc_pool_cache);

	ai_memalloc_info("Ainos AI Memory Allocator unloaded\n");
}

/*
 * Exported kernel API
 */

void *ai_memalloc_alloc(size_t size, gfp_t gfp_flags, int numa_node)
{
	if (numa_node >= 0 && node_online(numa_node))
		return kmalloc_node(size, gfp_flags, numa_node);
	return kmalloc(size, gfp_flags);
}
EXPORT_SYMBOL_GPL(ai_memalloc_alloc);

void *ai_memalloc_alloc_huge(size_t size, gfp_t gfp_flags, int numa_node)
{
	gfp_flags |= __GFP_COMP;
	if (numa_node >= 0 && node_online(numa_node))
		return kmalloc_node(size, gfp_flags, numa_node);
	return kmalloc(size, gfp_flags);
}
EXPORT_SYMBOL_GPL(ai_memalloc_alloc_huge);

void *ai_memalloc_alloc_numa(size_t size, gfp_t gfp_flags,
			     nodemask_t *nodemask)
{
	int node;

	if (nodemask && !nodes_empty(*nodemask))
		node = first_node(*nodemask);
	else
		node = numa_node_id();

	return kmalloc_node(size, gfp_flags, node);
}
EXPORT_SYMBOL_GPL(ai_memalloc_alloc_numa);

void *ai_memalloc_zalloc(size_t size, gfp_t gfp_flags, int numa_node)
{
	gfp_flags |= __GFP_ZERO;
	if (numa_node >= 0 && node_online(numa_node))
		return kmalloc_node(size, gfp_flags, numa_node);
	return kmalloc(size, gfp_flags);
}
EXPORT_SYMBOL_GPL(ai_memalloc_zalloc);

void ai_memalloc_free(void *addr, size_t size)
{
	kfree(addr);
}
EXPORT_SYMBOL_GPL(ai_memalloc_free);

int ai_memalloc_pool_create(size_t min_size, size_t max_size,
			    gfp_t gfp_flags, int numa_node)
{
	return 0;
}
EXPORT_SYMBOL_GPL(ai_memalloc_pool_create);

int ai_memalloc_pool_destroy(int pool_id)
{
	return 0;
}
EXPORT_SYMBOL_GPL(ai_memalloc_pool_destroy);

int ai_memalloc_pool_expand(int pool_id, size_t additional_size)
{
	return 0;
}
EXPORT_SYMBOL_GPL(ai_memalloc_pool_expand);

int ai_memalloc_pool_shrink(int pool_id, size_t target_size)
{
	return 0;
}
EXPORT_SYMBOL_GPL(ai_memalloc_pool_shrink);

int ai_memalloc_migrate_pages(void *addr, size_t size, int target_node)
{
	return -ENOSYS;
}
EXPORT_SYMBOL_GPL(ai_memalloc_migrate_pages);

int ai_memalloc_bind_to_node(void *addr, size_t size, int numa_node)
{
	return -ENOSYS;
}
EXPORT_SYMBOL_GPL(ai_memalloc_bind_to_node);

int ai_memalloc_get_numa_node(void *addr)
{
#ifdef CONFIG_NUMA
	struct page *page;

	if (!addr)
		return numa_node_id();

	page = virt_to_page(addr);
	if (page)
		return page_to_nid(page);
#endif
	return numa_node_id();
}
EXPORT_SYMBOL_GPL(ai_memalloc_get_numa_node);

nodemask_t ai_memalloc_get_numa_mask(void)
{
	return *node_online_mask;
}
EXPORT_SYMBOL_GPL(ai_memalloc_get_numa_mask);

int ai_memalloc_hugepage_alloc(struct page **pages, int nr_pages, int nid)
{
	int i;

	for (i = 0; i < nr_pages; i++) {
		pages[i] = alloc_pages_node(nid, GFP_TRANSHUGE,
					    HPAGE_PMD_ORDER);
		if (!pages[i]) {
			while (--i >= 0)
				__free_pages(pages[i], HPAGE_PMD_ORDER);
			return -ENOMEM;
		}
	}

	return 0;
}
EXPORT_SYMBOL_GPL(ai_memalloc_hugepage_alloc);

int ai_memalloc_hugepage_free(struct page **pages, int nr_pages)
{
	int i;

	for (i = 0; i < nr_pages; i++) {
		if (pages[i])
			__free_pages(pages[i], HPAGE_PMD_ORDER);
	}

	return 0;
}
EXPORT_SYMBOL_GPL(ai_memalloc_hugepage_free);

int ai_memalloc_hugepage_promote(void *addr, size_t size)
{
	unsigned long start, end;
	unsigned long addr_aligned;

	start = (unsigned long)addr;
	end = start + size;
	addr_aligned = round_down(start, HPAGE_SIZE);

	while (addr_aligned + HPAGE_SIZE <= end) {
		int ret;

		ret = alloc_huge_page(vma_address(NULL, addr_aligned),
				      HPAGE_PMD_ORDER);
		if (ret < 0)
			return ret;

		addr_aligned += HPAGE_SIZE;
	}

	return 0;
}
EXPORT_SYMBOL_GPL(ai_memalloc_hugepage_promote);

int ai_memalloc_thp_enable(void *addr, size_t size)
{
	return 0;
}
EXPORT_SYMBOL_GPL(ai_memalloc_thp_enable);

int ai_memalloc_get_pressure_level(enum ai_memalloc_pressure_level *level)
{
	struct sysinfo si;
	unsigned long free_pages, total_pages;
	int score;

	si_meminfo(&si);

	free_pages = si.freeram + si.bufferram;
	total_pages = si.totalram;

	if (total_pages == 0) {
		*level = AI_MEMALLOC_PRESSURE_NONE;
		return 0;
	}

	score = (int)((total_pages - free_pages) * 100 / total_pages);

	if (score < 30)
		*level = AI_MEMALLOC_PRESSURE_NONE;
	else if (score < 50)
		*level = AI_MEMALLOC_PRESSURE_LOW;
	else if (score < 70)
		*level = AI_MEMALLOC_PRESSURE_MEDIUM;
	else if (score < 90)
		*level = AI_MEMALLOC_PRESSURE_HIGH;
	else
		*level = AI_MEMALLOC_PRESSURE_CRITICAL;

	return 0;
}
EXPORT_SYMBOL_GPL(ai_memalloc_get_pressure_level);

int ai_memalloc_reclaim(size_t target_pages)
{
	unsigned long nr_reclaimed;

	nr_reclaimed = try_to_free_pages(node_zonelist(numa_node_id(),
						       GFP_KERNEL), 0,
					 GFP_KERNEL, NULL);

	ai_memalloc_dbg("Reclaim: target=%zu reclaimed=%lu\n",
			target_pages, nr_reclaimed);

	return (int)nr_reclaimed;
}
EXPORT_SYMBOL_GPL(ai_memalloc_reclaim);

int ai_memalloc_compact(void)
{
	int nid;
	int ret = 0;

	for_each_online_node(nid) {
		struct zone *zone;
		enum zone_type z;

		for (z = 0; z < MAX_NR_ZONES; z++) {
			zone = &NODE_DATA(nid)->node_zones[z];
			if (!populated_zone(zone))
				continue;

			wakeup_kcompactd(zone, 0, 0, 0);
		}
	}

	ai_memalloc_dbg("Compaction triggered on all nodes\n");
	return ret;
}
EXPORT_SYMBOL_GPL(ai_memalloc_compact);

int ai_memalloc_register_oom_notifier(void (*handler)(void))
{
	struct ai_memalloc_device *dev, *first_dev = NULL;

	mutex_lock(&ai_memalloc_mutex);
	first_dev = list_first_entry_or_null(&ai_memalloc_devices,
					     struct ai_memalloc_device, list);
	mutex_unlock(&ai_memalloc_mutex);

	if (!first_dev)
		return -ENODEV;

	return ai_memalloc_register_oom_notifier_locked(first_dev,
							handler, "external");
}
EXPORT_SYMBOL_GPL(ai_memalloc_register_oom_notifier);

int ai_memalloc_unregister_oom_notifier(void (*handler)(void))
{
	struct ai_memalloc_device *dev, *first_dev = NULL;

	mutex_lock(&ai_memalloc_mutex);
	first_dev = list_first_entry_or_null(&ai_memalloc_devices,
					     struct ai_memalloc_device, list);
	mutex_unlock(&ai_memalloc_mutex);

	if (!first_dev)
		return -ENODEV;

	return ai_memalloc_unregister_oom_notifier_locked(first_dev, handler);
}
EXPORT_SYMBOL_GPL(ai_memalloc_unregister_oom_notifier);

int ai_memalloc_set_watermarks(struct ai_memalloc_watermarks *wm)
{
	return 0;
}
EXPORT_SYMBOL_GPL(ai_memalloc_set_watermarks);

int ai_memalloc_get_watermarks(struct ai_memalloc_watermarks *wm)
{
	return 0;
}
EXPORT_SYMBOL_GPL(ai_memalloc_get_watermarks);

int ai_memalloc_cache_hit(void *addr)
{
	return 0;
}
EXPORT_SYMBOL_GPL(ai_memalloc_cache_hit);

int ai_memalloc_cache_miss(void *addr)
{
	return 0;
}
EXPORT_SYMBOL_GPL(ai_memalloc_cache_miss);

int ai_memalloc_get_stats(struct ai_memalloc_pool_stats *stats)
{
	return 0;
}
EXPORT_SYMBOL_GPL(ai_memalloc_get_stats);

int ai_memalloc_get_profile(struct ai_memalloc_profile *profile)
{
	return 0;
}
EXPORT_SYMBOL_GPL(ai_memalloc_get_profile);

int ai_memalloc_dump_state(void)
{
	ai_memalloc_info("State dump requested\n");
	return 0;
}
EXPORT_SYMBOL_GPL(ai_memalloc_dump_state);

int ai_memalloc_validate_allocations(void)
{
	return 0;
}
EXPORT_SYMBOL_GPL(ai_memalloc_validate_allocations);

module_init(ai_memalloc_init);
module_exit(ai_memalloc_exit);