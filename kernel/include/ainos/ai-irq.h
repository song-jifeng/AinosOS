/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Ainos AI Interrupt Controller - Header
 *
 * Copyright (C) 2026 Ainos Corporation
 * Authors: Ainos Kernel Team
 *
 * AI-optimized interrupt distribution subsystem.
 * Provides interrupt load balancing, AI-driven priority management,
 * interrupt coalescing, and comprehensive interrupt statistics.
 */

#ifndef _AINOS_AI_IRQ_H
#define _AINOS_AI_IRQ_H

#include <linux/types.h>
#include <linux/interrupt.h>
#include <linux/irq.h>
#include <linux/irqdomain.h>
#include <linux/hardirq.h>
#include <linux/irqreturn.h>
#include <linux/cpumask.h>

/* Module identification */
#define AI_IRQ_MODULE_NAME		"ai_irq"
#define AI_IRQ_MODULE_VERSION		"1.0.0"
#define AI_IRQ_MODULE_DESC		"Ainos AI Interrupt Controller"
#define AI_IRQ_MODULE_AUTHOR		"Ainos Kernel Team"

/* Device interface */
#define AI_IRQ_DEVICE_NAME		"ai-irq"
#define AI_IRQ_CLASS_NAME		"ai-irq"
#define AI_IRQ_MAX_DEVICES		4

/* IOCTL commands */
#define AI_IRQ_IOC_MAGIC		0xAF

#define AI_IRQ_IOCTL_GET_INFO		_IOR(AI_IRQ_IOC_MAGIC, 0x01, struct ai_irq_info)
#define AI_IRQ_IOCTL_REGISTER		_IOWR(AI_IRQ_IOC_MAGIC, 0x02, struct ai_irq_register)
#define AI_IRQ_IOCTL_UNREGISTER		_IOW(AI_IRQ_IOC_MAGIC, 0x03, struct ai_irq_unregister)
#define AI_IRQ_IOCTL_SET_AFFINITY	_IOW(AI_IRQ_IOC_MAGIC, 0x04, struct ai_irq_affinity)
#define AI_IRQ_IOCTL_GET_AFFINITY	_IOR(AI_IRQ_IOC_MAGIC, 0x05, struct ai_irq_affinity)
#define AI_IRQ_IOCTL_SET_PRIORITY	_IOW(AI_IRQ_IOC_MAGIC, 0x06, struct ai_irq_priority)
#define AI_IRQ_IOCTL_GET_PRIORITY	_IOR(AI_IRQ_IOC_MAGIC, 0x07, struct ai_irq_priority)
#define AI_IRQ_IOCTL_GET_STATS		_IOR(AI_IRQ_IOC_MAGIC, 0x08, struct ai_irq_stats)
#define AI_IRQ_IOCTL_BALANCE		_IO(AI_IRQ_IOC_MAGIC, 0x09)
#define AI_IRQ_IOCTL_COALESCE		_IOW(AI_IRQ_IOC_MAGIC, 0x0A, struct ai_irq_coalesce)
#define AI_IRQ_IOCTL_GET_COALESCE	_IOR(AI_IRQ_IOC_MAGIC, 0x0B, struct ai_irq_coalesce)
#define AI_IRQ_IOCTL_SET_BALANCE_POLICY	_IOW(AI_IRQ_IOC_MAGIC, 0x0C, struct ai_irq_balance_policy)
#define AI_IRQ_IOCTL_GET_BALANCE_POLICY	_IOR(AI_IRQ_IOC_MAGIC, 0x0D, struct ai_irq_balance_policy)
#define AI_IRQ_IOCTL_ENABLE_TRACE	_IOW(AI_IRQ_IOC_MAGIC, 0x0E, __u32)
#define AI_IRQ_IOCTL_DISABLE_TRACE	_IOW(AI_IRQ_IOC_MAGIC, 0x0F, __u32)
#define AI_IRQ_IOCTL_GET_CPU_LOAD	_IOR(AI_IRQ_IOC_MAGIC, 0x10, struct ai_irq_cpu_load)
#define AI_IRQ_IOCTL_GET_IRQ_LOAD	_IOR(AI_IRQ_IOC_MAGIC, 0x11, struct ai_irq_load)
#define AI_IRQ_IOCTL_AUTO_BALANCE	_IOW(AI_IRQ_IOC_MAGIC, 0x12, __u32)
#define AI_IRQ_IOCTL_MIGRATE		_IOWR(AI_IRQ_IOC_MAGIC, 0x13, struct ai_irq_migrate)
#define AI_IRQ_IOCTL_GET_TIMING		_IOR(AI_IRQ_IOC_MAGIC, 0x14, struct ai_irq_timing)
#define AI_IRQ_IOCTL_RESET_STATS	_IO(AI_IRQ_IOC_MAGIC, 0x15)
#define AI_IRQ_IOCTL_SET_THROTTLE	_IOW(AI_IRQ_IOC_MAGIC, 0x16, struct ai_irq_throttle)
#define AI_IRQ_IOCTL_GET_THROTTLE	_IOR(AI_IRQ_IOC_MAGIC, 0x17, struct ai_irq_throttle)
#define AI_IRQ_IOCTL_GET_TOPOLOGY	_IOR(AI_IRQ_IOC_MAGIC, 0x18, struct ai_irq_topology)
#define AI_IRQ_IOCTL_INJECT		_IOW(AI_IRQ_IOC_MAGIC, 0x19, struct ai_irq_inject)
#define AI_IRQ_IOCTL_GET_HISTORY	_IOR(AI_IRQ_IOC_MAGIC, 0x1A, struct ai_irq_history)

#define AI_IRQ_IOC_MAXNR		26

/* AI IRQ priority levels */
enum ai_irq_priority {
	AI_IRQ_PRIO_CRITICAL		= 0,	/* System-critical interrupts */
	AI_IRQ_PRIO_REALTIME		= 1,	/* Real-time workloads */
	AI_IRQ_PRIO_HIGH		= 2,	/* AI inference interrupts */
	AI_IRQ_PRIO_MEDIUM		= 3,	/* Normal AI processing */
	AI_IRQ_PRIO_LOW			= 4,	/* Background tasks */
	AI_IRQ_PRIO_IDLE		= 5,	/* Idle processing */
	AI_IRQ_PRIO_COUNT		= 6,
};

/* AI IRQ workload types */
enum ai_irq_workload {
	AI_IRQ_WORKLOAD_INFERENCE	= 0,
	AI_IRQ_WORKLOAD_TRAINING	= 1,
	AI_IRQ_WORKLOAD_PREPROCESS	= 2,
	AI_IRQ_WORKLOAD_IO		= 3,
	AI_IRQ_WORKLOAD_NETWORK		= 4,
	AI_IRQ_WORKLOAD_SCHEDULER	= 5,
	AI_IRQ_WORKLOAD_TIMER		= 6,
	AI_IRQ_WORKLOAD_IPI		= 7,
	AI_IRQ_WORKLOAD_DMA		= 8,
	AI_IRQ_WORKLOAD_GPU		= 9,
	AI_IRQ_WORKLOAD_NPU		= 10,
	AI_IRQ_WORKLOAD_UNKNOWN		= 11,
};

/* IRQ balancing policies */
enum ai_irq_balance_policy_type {
	AI_IRQ_BALANCE_WEIGHTED		= 0,	/* Weighted load balancing */
	AI_IRQ_BALANCE_ROUND_ROBIN	= 1,	/* Round-robin distribution */
	AI_IRQ_BALANCE_LEAST_LOADED	= 2,	/* Least-loaded CPU */
	AI_IRQ_BALANCE_CACHE_AWARE	= 3,	/* Cache topology aware */
	AI_IRQ_BALANCE_POWER_AWARE	= 4,	/* Power efficiency */
	AI_IRQ_BALANCE_AI_PREDICTIVE	= 5,	/* AI predictive balancing */
	AI_IRQ_BALANCE_MANUAL		= 6,	/* Manual distribution */
};

/* Coalescing modes */
enum ai_irq_coalesce_mode {
	AI_IRQ_COALESCE_DISABLED	= 0,
	AI_IRQ_COALESCE_TIMER		= 1,	/* Timer-based coalescing */
	AI_IRQ_COALESCE_PACKET		= 2,	/* Packet count based */
	AI_IRQ_COALESCE_ADAPTIVE	= 3,	/* AI adaptive coalescing */
	AI_IRQ_COALESCE_HYBRID		= 4,	/* Hybrid approach */
};

/* IRQ registration structure */
struct ai_irq_register {
	__u32			irq_number;
	__u32			flags;
	__u32			workload_type;
	__u32			initial_priority;
	char			name[64];
	__u64			handler_data;
	__u32			cpu_affinity;
	__u32			expected_frequency;
	__u64			expected_duration_ns;
	__u32			can_suspend;
	__u32			padding[4];
};

/* IRQ unregister */
struct ai_irq_unregister {
	__u32			irq_number;
	__u32			flags;
	__u32			padding[4];
};

/* IRQ affinity */
struct ai_irq_affinity {
	__u32			irq_number;
	cpumask_var_t		cpumask;
	__u32			cpumask_size;
	__u32			flags;
	__s32			result;
	__u32			padding[4];
};

/* IRQ priority */
struct ai_irq_priority {
	__u32			irq_number;
	enum ai_irq_priority	priority;
	__u32			sub_priority;
	__u32			flags;
	__s32			result;
	__u32			padding[4];
};

/* IRQ coalescing configuration */
struct ai_irq_coalesce {
	__u32			irq_number;
	enum ai_irq_coalesce_mode	mode;
	__u32			timer_usecs;
	__u32			packet_count;
	__u32			adaptive_threshold;
	__u32			max_coalesce_usecs;
	__u32			use_adaptive_rx;
	__u32			use_adaptive_tx;
	__u32			stats_block_coalesce;
	__u32			pkt_rate_high;
	__u32			pkt_rate_low;
	__u32			coalesce_frames;
	__u32			coalesce_bytes;
	__u32			padding[4];
};

/* IRQ statistics */
struct ai_irq_stats {
	__u32			irq_number;
	__u64			total_handled;
	__u64			total_spurious;
	__u64			total_missed;
	__u64			total_coalesced;
	__u64			avg_handling_time_ns;
	__u64			max_handling_time_ns;
	__u64			min_handling_time_ns;
	__u64			total_handling_time_ns;
	__u64			last_handled_jiffies;
	__u64			avg_interarrival_time_ns;
	__u64			min_interarrival_time_ns;
	__u64			max_interarrival_time_ns;
	__u64			balancing_migrations;
	__u64			throttled_events;
	__u64			priority_promotions;
	__u64			priority_demotions;
	__u32			current_cpu;
	__u32			current_priority;
	__u32			workload_type;
	__u32			active;
	__u32			padding[8];
};

/* IRQ balance policy */
struct ai_irq_balance_policy {
	enum ai_irq_balance_policy_type	type;
	__u32			interval_ms;
	__u32			threshold_high;
	__u32			threshold_low;
	__u32			migration_delay_ms;
	__u32			power_save_mode;
	__u32			use_ai_prediction;
	__u32			ai_model_version;
	__u32			learning_rate;
	__u32			min_balance_interval;
	__u32			max_balance_interval;
	__u32			weights[AI_IRQ_PRIO_COUNT];
	__u32			padding[8];
};

/* CPU load information */
struct ai_irq_cpu_load {
	__u32			cpu_id;
	__u64			total_irq_load;
	__u64			irq_count;
	__u64			softirq_count;
	__u64			hardirq_count;
	__u64			idle_time;
	__u64			busy_time;
	__u64			total_time;
	__u32			load_percent;
	__u32			irq_load_percent;
	__u32			softirq_load_percent;
	__u32			running_processes;
	__u32			padding[8];
};

/* Per-IRQ load */
struct ai_irq_load {
	__u32			irq_number;
	__u64			handling_rate;
	__u64			interrupts_per_sec;
	__u64			load_estimate;
	__u64			processing_time_avg;
	__u32			cpu_affinity;
	__u32			load_percent;
	__u32			padding[6];
};

/* IRQ migration */
struct ai_irq_migrate {
	__u32			irq_number;
	__u32			source_cpu;
	__u32			target_cpu;
	__u32			flags;
	__s32			result;
	__u32			padding[4];
};

/* IRQ timing information */
struct ai_irq_timing {
	__u32			irq_number;
	__u64			first_fired;
	__u64			last_fired;
	__u64			total_active_time;
	__u64			idle_since;
	__u32			firing_count;
	__u32			burst_count;
	__u64			avg_burst_duration;
	__u64			max_burst_duration;
	__u32			padding[8];
};

/* IRQ throttle */
struct ai_irq_throttle {
	__u32			irq_number;
	__u32			max_interrupts_per_sec;
	__u32			current_rate;
	__u32			throttle_active;
	__u32			cooldown_period_ms;
	__u32			burst_tolerance;
	__u32			padding[4];
};

/* IRQ topology */
struct ai_irq_topology {
	__u32			irq_count;
	__u32			cpu_count;
	__u32			domain_count;
	__u32			msi_supported;
	__u32			msi_x_supported;
	__u32			ioapic_present;
	__u32			vectors_per_cpu;
	__u32			reserved_vectors;
	__u32			available_vectors;
	__u32			padding[8];
};

/* IRQ inject (for testing) */
struct ai_irq_inject {
	__u32			irq_number;
	__u32			count;
	__u32			interval_us;
	__u32			flags;
	__u32			padding[4];
};

/* IRQ history entry */
struct ai_irq_history_entry {
	__u64			timestamp;
	__u32			irq_number;
	__u32			cpu;
	__u32			action;
	enum ai_irq_priority	priority;
	__u64			duration_ns;
	__u32			padding[4];
};

/* IRQ history query */
struct ai_irq_history {
	__u32			irq_number;
	__u32			max_entries;
	__u32			actual_entries;
	__u64			start_timestamp;
	__u64			end_timestamp;
	struct ai_irq_history_entry	*entries;
	__u32			padding[4];
};

/* Module info */
struct ai_irq_info {
	char			version[32];
	char			description[64];
	__u32			major_version;
	__u32			minor_version;
	__u32			patch_version;
	__u32			max_irqs_supported;
	__u32			active_irqs;
	__u32			balance_policy;
	__u32			coalesce_enabled;
	__u32			ai_balancing_enabled;
	__u32			features;
	__u32			padding[8];
};

/* Sysfs entries */
#define AI_IRQ_SYSFS_BALANCE_POLICY	"balance_policy"
#define AI_IRQ_SYSFS_COALESCE		"coalesce"
#define AI_IRQ_SYSFS_PRIORITY		"priority"
#define AI_IRQ_SYSFS_AFFINITY		"affinity"
#define AI_IRQ_SYSFS_STATS		"stats"
#define AI_IRQ_SYSFS_IRQ_COUNT		"irq_count"
#define AI_IRQ_SYSFS_CPU_LOAD		"cpu_load"
#define AI_IRQ_SYSFS_BALANCE_NOW	"balance_now"
#define AI_IRQ_SYSFS_THROTTLE		"throttle"
#define AI_IRQ_SYSFS_TOPOLOGY		"topology"

/* Internal kernel API */
struct ai_irq_controller;

#ifdef CONFIG_AINOS_AI_IRQ

/* Registration and management */
int ai_irq_register(unsigned int irq, const char *name,
		    enum ai_irq_workload workload,
		    enum ai_irq_priority priority);
int ai_irq_unregister(unsigned int irq);
int ai_irq_set_affinity(unsigned int irq, const struct cpumask *mask);
int ai_irq_get_affinity(unsigned int irq, struct cpumask *mask);
int ai_irq_set_priority(unsigned int irq, enum ai_irq_priority priority);
int ai_irq_get_priority(unsigned int irq, enum ai_irq_priority *priority);

/* Balancing */
int ai_irq_balance_now(void);
int ai_irq_set_balance_policy(enum ai_irq_balance_policy_type policy);
int ai_irq_get_balance_policy(enum ai_irq_balance_policy_type *policy);
int ai_irq_migrate(unsigned int irq, unsigned int target_cpu);

/* Coalescing */
int ai_irq_coalesce_config(unsigned int irq, struct ai_irq_coalesce *config);
int ai_irq_coalesce_get(unsigned int irq, struct ai_irq_coalesce *config);
int ai_irq_coalesce_enable(unsigned int irq);
int ai_irq_coalesce_disable(unsigned int irq);

/* Statistics */
int ai_irq_get_stats(unsigned int irq, struct ai_irq_stats *stats);
int ai_irq_reset_stats(unsigned int irq);
int ai_irq_get_cpu_load(unsigned int cpu, struct ai_irq_cpu_load *load);
int ai_irq_get_irq_load(unsigned int irq, struct ai_irq_load *load);
int ai_irq_get_history(unsigned int irq, struct ai_irq_history *history);

/* Throttling */
int ai_irq_throttle_config(unsigned int irq, struct ai_irq_throttle *config);
int ai_irq_throttle_get(unsigned int irq, struct ai_irq_throttle *config);
int ai_irq_throttle_enable(unsigned int irq);
int ai_irq_throttle_disable(unsigned int irq);

/* AI-specific */
int ai_irq_ai_balance_advise(unsigned int irq, unsigned int *recommended_cpu);
int ai_irq_ai_detect_anomaly(unsigned int irq, bool *anomaly);
int ai_irq_ai_predict_load(unsigned int irq, __u64 *predicted_load);
int ai_irq_ai_classify_workload(unsigned int irq,
				enum ai_irq_workload *workload);

/* Topology */
int ai_irq_get_topology(struct ai_irq_topology *topology);
int ai_irq_get_available_cpus(unsigned int irq, struct cpumask *mask);

/* Debug/test */
int ai_irq_inject(unsigned int irq, unsigned int count);
int ai_irq_dump_state(unsigned int irq);

#else /* !CONFIG_AINOS_AI_IRQ */

/* Stubs */
static inline int ai_irq_register(unsigned int irq, const char *name,
				  enum ai_irq_workload workload,
				  enum ai_irq_priority priority)
{
	return -ENODEV;
}

static inline int ai_irq_unregister(unsigned int irq)
{
	return -ENODEV;
}

static inline int ai_irq_set_affinity(unsigned int irq,
				      const struct cpumask *mask)
{
	return irq_set_affinity_hint(irq, mask);
}

static inline int ai_irq_get_affinity(unsigned int irq, struct cpumask *mask)
{
	return -ENODEV;
}

static inline int ai_irq_set_priority(unsigned int irq,
				      enum ai_irq_priority priority)
{
	return -ENODEV;
}

static inline int ai_irq_get_priority(unsigned int irq,
				      enum ai_irq_priority *priority)
{
	return -ENODEV;
}

static inline int ai_irq_balance_now(void)
{
	return -ENODEV;
}

static inline int ai_irq_set_balance_policy(
		enum ai_irq_balance_policy_type policy)
{
	return -ENODEV;
}

static inline int ai_irq_get_balance_policy(
		enum ai_irq_balance_policy_type *policy)
{
	return -ENODEV;
}

static inline int ai_irq_migrate(unsigned int irq, unsigned int target_cpu)
{
	return -ENODEV;
}

static inline int ai_irq_coalesce_config(unsigned int irq,
					 struct ai_irq_coalesce *config)
{
	return -ENODEV;
}

static inline int ai_irq_coalesce_get(unsigned int irq,
				      struct ai_irq_coalesce *config)
{
	return -ENODEV;
}

static inline int ai_irq_coalesce_enable(unsigned int irq)
{
	return -ENODEV;
}

static inline int ai_irq_coalesce_disable(unsigned int irq)
{
	return -ENODEV;
}

static inline int ai_irq_get_stats(unsigned int irq,
				   struct ai_irq_stats *stats)
{
	return -ENODEV;
}

static inline int ai_irq_reset_stats(unsigned int irq)
{
	return -ENODEV;
}

static inline int ai_irq_get_cpu_load(unsigned int cpu,
				      struct ai_irq_cpu_load *load)
{
	return -ENODEV;
}

static inline int ai_irq_get_irq_load(unsigned int irq,
				      struct ai_irq_load *load)
{
	return -ENODEV;
}

static inline int ai_irq_get_history(unsigned int irq,
				     struct ai_irq_history *history)
{
	return -ENODEV;
}

static inline int ai_irq_throttle_config(unsigned int irq,
					 struct ai_irq_throttle *config)
{
	return -ENODEV;
}

static inline int ai_irq_throttle_get(unsigned int irq,
				      struct ai_irq_throttle *config)
{
	return -ENODEV;
}

static inline int ai_irq_throttle_enable(unsigned int irq)
{
	return -ENODEV;
}

static inline int ai_irq_throttle_disable(unsigned int irq)
{
	return -ENODEV;
}

static inline int ai_irq_ai_balance_advise(unsigned int irq,
					   unsigned int *recommended_cpu)
{
	return -ENODEV;
}

static inline int ai_irq_ai_detect_anomaly(unsigned int irq, bool *anomaly)
{
	return -ENODEV;
}

static inline int ai_irq_ai_predict_load(unsigned int irq,
					 __u64 *predicted_load)
{
	return -ENODEV;
}

static inline int ai_irq_ai_classify_workload(unsigned int irq,
					      enum ai_irq_workload *workload)
{
	return -ENODEV;
}

static inline int ai_irq_get_topology(struct ai_irq_topology *topology)
{
	return -ENODEV;
}

static inline int ai_irq_get_available_cpus(unsigned int irq,
					    struct cpumask *mask)
{
	return -ENODEV;
}

static inline int ai_irq_inject(unsigned int irq, unsigned int count)
{
	return -ENODEV;
}

static inline int ai_irq_dump_state(unsigned int irq)
{
	return -ENODEV;
}

#endif /* CONFIG_AINOS_AI_IRQ */

#endif /* _AINOS_AI_IRQ_H */