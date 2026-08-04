/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Ainos AI Device Mapper - Header
 *
 * Copyright (C) 2026 Ainos Corporation
 * Authors: Ainos Kernel Team
 *
 * AI device mapping and management subsystem providing device
 * registry, discovery, hot-plug support, and health monitoring.
 */

#ifndef _AINOS_AI_DEVMAPPER_H
#define _AINOS_AI_DEVMAPPER_H

#include <linux/types.h>
#include <linux/device.h>
#include <linux/pci.h>
#include <linux/platform_device.h>
#include <linux/acpi.h>
#include <linux/of.h>
#include <linux/dma-mapping.h>
#include <linux/iommu.h>

/* Module identification */
#define AI_DEVMAPPER_MODULE_NAME	"ai_devmapper"
#define AI_DEVMAPPER_MODULE_VERSION	"1.0.0"
#define AI_DEVMAPPER_MODULE_DESC	"Ainos AI Device Mapper"
#define AI_DEVMAPPER_MODULE_AUTHOR	"Ainos Kernel Team"

/* Device interface */
#define AI_DEVMAPPER_DEVICE_NAME	"ai-devmapper"
#define AI_DEVMAPPER_CLASS_NAME		"ai-devmapper"
#define AI_DEVMAPPER_MAX_DEVICES	4

/* IOCTL commands */
#define AI_DEVMAPPER_IOC_MAGIC		0xB1

#define AI_DEVMAPPER_IOCTL_GET_INFO		_IOR(AI_DEVMAPPER_IOC_MAGIC, 0x01, struct ai_devmapper_info)
#define AI_DEVMAPPER_IOCTL_REGISTER		_IOWR(AI_DEVMAPPER_IOC_MAGIC, 0x02, struct ai_devmapper_register)
#define AI_DEVMAPPER_IOCTL_UNREGISTER		_IOW(AI_DEVMAPPER_IOC_MAGIC, 0x03, struct ai_devmapper_unregister)
#define AI_DEVMAPPER_IOCTL_GET_DEVICE		_IOR(AI_DEVMAPPER_IOC_MAGIC, 0x04, struct ai_devmapper_device)
#define AI_DEVMAPPER_IOCTL_ENUMERATE		_IOR(AI_DEVMAPPER_IOC_MAGIC, 0x05, struct ai_devmapper_enum)
#define AI_DEVMAPPER_IOCTL_SCAN			_IO(AI_DEVMAPPER_IOC_MAGIC, 0x06)
#define AI_DEVMAPPER_IOCTL_GET_HEALTH		_IOR(AI_DEVMAPPER_IOC_MAGIC, 0x07, struct ai_devmapper_health)
#define AI_DEVMAPPER_IOCTL_SET_POWER		_IOW(AI_DEVMAPPER_IOC_MAGIC, 0x08, struct ai_devmapper_power)
#define AI_DEVMAPPER_IOCTL_RESET		_IOW(AI_DEVMAPPER_IOC_MAGIC, 0x09, __u32)
#define AI_DEVMAPPER_IOCTL_GET_DMA		_IOR(AI_DEVMAPPER_IOC_MAGIC, 0x0A, struct ai_devmapper_dma)
#define AI_DEVMAPPER_IOCTL_SET_DMA		_IOW(AI_DEVMAPPER_IOC_MAGIC, 0x0B, struct ai_devmapper_dma)
#define AI_DEVMAPPER_IOCTL_GET_IRQ_INFO		_IOR(AI_DEVMAPPER_IOC_MAGIC, 0x0C, struct ai_devmapper_irq_info)
#define AI_DEVMAPPER_IOCTL_GET_MMIO		_IOR(AI_DEVMAPPER_IOC_MAGIC, 0x0D, struct ai_devmapper_mmio)
#define AI_DEVMAPPER_IOCTL_GET_IOMMU		_IOR(AI_DEVMAPPER_IOC_MAGIC, 0x0E, struct ai_devmapper_iommu)
#define AI_DEVMAPPER_IOCTL_ATTACH_IOMMU		_IOW(AI_DEVMAPPER_IOC_MAGIC, 0x0F, struct ai_devmapper_iommu)
#define AI_DEVMAPPER_IOCTL_DETACH_IOMMU		_IOW(AI_DEVMAPPER_IOC_MAGIC, 0x10, __u32)
#define AI_DEVMAPPER_IOCTL_GET_AI_DEVICES	_IOR(AI_DEVMAPPER_IOC_MAGIC, 0x11, struct ai_devmapper_ai_devices)
#define AI_DEVMAPPER_IOCTL_BIND_PROCESS		_IOW(AI_DEVMAPPER_IOC_MAGIC, 0x12, struct ai_devmapper_bind)
#define AI_DEVMAPPER_IOCTL_UNBIND_PROCESS	_IOW(AI_DEVMAPPER_IOC_MAGIC, 0x13, struct ai_devmapper_bind)
#define AI_DEVMAPPER_IOCTL_GET_MEMORY		_IOR(AI_DEVMAPPER_IOC_MAGIC, 0x14, struct ai_devmapper_memory)
#define AI_DEVMAPPER_IOCTL_GET_CAPABILITIES	_IOR(AI_DEVMAPPER_IOC_MAGIC, 0x15, struct ai_devmapper_caps)
#define AI_DEVMAPPER_IOCTL_ENABLE_MONITOR	_IOW(AI_DEVMAPPER_IOC_MAGIC, 0x16, __u32)
#define AI_DEVMAPPER_IOCTL_DISABLE_MONITOR	_IOW(AI_DEVMAPPER_IOC_MAGIC, 0x17, __u32)
#define AI_DEVMAPPER_IOCTL_GET_TOPOLOGY		_IOR(AI_DEVMAPPER_IOC_MAGIC, 0x18, struct ai_devmapper_topology)
#define AI_DEVMAPPER_IOCTL_GET_AI_DEVICE	_IOR(AI_DEVMAPPER_IOC_MAGIC, 0x19, struct ai_devmapper_ai_device)
#define AI_DEVMAPPER_IOCTL_GET_ERROR_LOG	_IOR(AI_DEVMAPPER_IOC_MAGIC, 0x1A, struct ai_devmapper_error_log)

#define AI_DEVMAPPER_IOC_MAXNR		26

/* Device types */
enum ai_devmapper_device_type {
	AI_DEVMAPPER_DEV_UNKNOWN	= 0,
	AI_DEVMAPPER_DEV_PCI		= 1,	/* PCI device */
	AI_DEVMAPPER_DEV_PLATFORM	= 2,	/* Platform device */
	AI_DEVMAPPER_DEV_ACPI		= 3,	/* ACPI device */
	AI_DEVMAPPER_DEV_OF		= 4,	/* Device tree */
	AI_DEVMAPPER_DEV_USB		= 5,	/* USB device */
	AI_DEVMAPPER_DEV_VIRTIO		= 6,	/* VirtIO device */
	AI_DEVMAPPER_DEV_AI_ACCEL	= 7,	/* AI accelerator */
	AI_DEVMAPPER_DEV_GPU		= 8,	/* GPU */
	AI_DEVMAPPER_DEV_NPU		= 9,	/* NPU */
	AI_DEVMAPPER_DEV_FPGA		= 10,	/* FPGA */
	AI_DEVMAPPER_DEV_DSP		= 11,	/* DSP */
};

/* Device power states */
enum ai_devmapper_power_state {
	AI_DEVMAPPER_POWER_D0		= 0,	/* Fully on */
	AI_DEVMAPPER_POWER_D1		= 1,	/* Low power */
	AI_DEVMAPPER_POWER_D2		= 2,	/* Deeper low power */
	AI_DEVMAPPER_POWER_D3_HOT	= 3,	/* D3hot - preserved state */
	AI_DEVMAPPER_POWER_D3_COLD	= 4,	/* D3cold - power removed */
	AI_DEVMAPPER_POWER_OFF		= 5,	/* Off */
};

/* Device health status */
enum ai_devmapper_health_status {
	AI_DEVMAPPER_HEALTH_OK		= 0,
	AI_DEVMAPPER_HEALTH_DEGRADED	= 1,
	AI_DEVMAPPER_HEALTH_WARNING	= 2,
	AI_DEVMAPPER_HEALTH_ERROR	= 3,
	AI_DEVMAPPER_HEALTH_CRITICAL	= 4,
	AI_DEVMAPPER_HEALTH_UNKNOWN	= 5,
};

/* Device class for AI */
enum ai_devmapper_ai_class {
	AI_DEVMAPPER_AI_CLASS_NONE	= 0,
	AI_DEVMAPPER_AI_CLASS_INFERENCE= 1,	/* Inference accelerator */
	AI_DEVMAPPER_AI_CLASS_TRAINING	= 2,	/* Training accelerator */
	AI_DEVMAPPER_AI_CLASS_VISION	= 3,	/* Computer vision */
	AI_DEVMAPPER_AI_CLASS_NLP	= 4,	/* NLP accelerator */
	AI_DEVMAPPER_AI_CLASS_AUDIO	= 5,	/* Audio processing */
	AI_DEVMAPPER_AI_CLASS_GENERAL	= 6,	/* General purpose */
};

/* Device register */
struct ai_devmapper_register {
	__u32			device_type;
	__u32			vendor_id;
	__u32			device_id;
	__u32			subsystem_vendor;
	__u32			subsystem_device;
	__u32			revision;
	__u64			driver_data;
	char			name[64];
	char			driver_name[32];
	__u32			flags;
	__u64			resource_start;
	__u64			resource_end;
	__u32			irq_count;
	__u32			device_id_out;
	__s32			result;
	__u32			padding[4];
};

/* Device unregister */
struct ai_devmapper_unregister {
	__u32			device_id;
	__u32			flags;
	__u32			padding[4];
};

/* Device information */
struct ai_devmapper_device {
	__u32			device_id;
	__u32			device_type;
	__u32			vendor_id;
	__u32			device_id_val;
	__u32			subsystem_vendor;
	__u32			subsystem_device;
	__u32			revision;
	__u32			class_code;
	__u32			power_state;
	__u32			enabled;
	__u32			irq_count;
	__u32			numa_node;
	__u32			domain;
	__u32			bus;
	__u32			slot;
	__u32			function;
	char			name[64];
	char			driver[32];
	char			class_name[32];
	__u64			mmio_start;
	__u64			mmio_end;
	__u64			mmio_len;
	__u32			health_status;
	__u32			padding[8];
};

/* Device enumeration */
struct ai_devmapper_enum {
	__u32			device_type;
	__u32			start_index;
	__u32			max_devices;
	__u32			actual_devices;
	__u32			device_ids[64];
	__u32			padding[8];
};

/* Health monitoring */
struct ai_devmapper_health {
	__u32			device_id;
	__u32			health_status;
	__u64			uptime_ms;
	__u64			last_error_timestamp;
	__u32			error_count;
	__u32			warning_count;
	__u32			temperature_c;
	__u32			voltage_uv;
	__u64			power_uw;
	__u64			frequency_hz;
	__u32			utilization_percent;
	__u32			memory_used_mb;
	__u32			memory_total_mb;
	__u32			bandwidth_used_mbps;
	__u32			bandwidth_total_mbps;
	__u32			link_speed;
	__u32			link_width;
	__u32			link_errors;
	__u32			padding[8];
};

/* Device power control */
struct ai_devmapper_power {
	__u32			device_id;
	__u32			power_state;
	__u32			flags;
	__u32			autosuspend_delay_ms;
	__s32			result;
	__u32			padding[4];
};

/* DMA configuration */
struct ai_devmapper_dma {
	__u32			device_id;
	__u64			dma_mask;
	__u64			coherent_dma_mask;
	__u32			flags;
	__u32			max_segment_size;
	__u32			min_align_mask;
	__u32			seg_boundary_mask;
	__u64			dma_addr;
	__u64			dma_size;
	__u32			dma_channels;
	__u32			padding[8];
};

/* IRQ information */
struct ai_devmapper_irq_info {
	__u32			device_id;
	__u32			irq_count;
	__u32			irq_base;
	__u32			msi_capable;
	__u32			msix_capable;
	__u32			msi_vectors;
	__u32			msix_vectors;
	__u32			irq_type;
	__u32			irqs[16];
	__u32			padding[8];
};

/* MMIO region */
struct ai_devmapper_mmio {
	__u32			device_id;
	__u32			bar_index;
	__u64			phys_addr;
	__u64			virt_addr;
	__u64			length;
	__u32			flags;
	__u32			prefetchable;
	__u32			cached;
	__u32			padding[8];
};

/* IOMMU configuration */
struct ai_devmapper_iommu {
	__u32			device_id;
	__u32			iommu_group;
	__u64			iommu_base;
	__u64			iommu_size;
	__u64			page_size;
	__u32			address_width;
	__u32			flags;
	__u32			pasid_capable;
	__u32			pasid_max;
	__u32			ats_supported;
	__u32			pri_supported;
	__u32			padding[8];
};

/* AI device list */
struct ai_devmapper_ai_devices {
	__u32			device_count;
	__u32			device_ids[32];
	__u32			padding[8];
};

/* Process bind */
struct ai_devmapper_bind {
	__u32			device_id;
	__s32			pid;
	__u32			flags;
	__u32			padding[4];
};

/* Device memory */
struct ai_devmapper_memory {
	__u32			device_id;
	__u64			memory_base;
	__u64			memory_size;
	__u64			memory_used;
	__u64			memory_free;
	__u32			memory_type;
	__u32			bandwidth_mbps;
	__u32			clock_mhz;
	__u32			padding[8];
};

/* Capabilities */
struct ai_devmapper_caps {
	__u32			device_id;
	__u32			capabilities[16];
	__u32			padding[8];
};

/* Topology */
struct ai_devmapper_topology {
	__u32			device_count;
	__u32			numa_nodes;
	__u32			pci_domains;
	__u32			ai_devices;
	__u32			gpu_count;
	__u32			npu_count;
	__u32			fpga_count;
	__u32			dsp_count;
	__u32			padding[8];
};

/* AI device detail */
struct ai_devmapper_ai_device {
	__u32			device_id;
	__u32			ai_class;
	__u32			compute_units;
	__u32			cores_per_unit;
	__u32			frequency_mhz;
	__u32			tflops_fp32;
	__u32			tflops_fp16;
	__u32			tflops_int8;
	__u64			memory_size_bytes;
	__u64			memory_bandwidth_bps;
	__u32			cache_size_kb;
	__u32			supported_precisions;
	__u32			firmware_version;
	__u32			pci_lanes;
	__u32			pci_generation;
	__u32			padding[8];
};

/* Error log entry */
struct ai_devmapper_error_log {
	__u32			device_id;
	__u32			error_type;
	__u64			timestamp;
	__u32			error_code;
	__u32			severity;
	char			message[128];
	__u32			padding[8];
};

/* Module info */
struct ai_devmapper_info {
	char			version[32];
	char			description[64];
	__u32			major_version;
	__u32			minor_version;
	__u32			patch_version;
	__u32			max_devices;
	__u32			registered_devices;
	__u32			ai_devices_available;
	__u32			monitoring_enabled;
	__u32			features;
	__u32			padding[8];
};

/* Sysfs entries */
#define AI_DEVMAPPER_SYSFS_DEVICES		"devices"
#define AI_DEVMAPPER_SYSFS_AI_DEVICES		"ai_devices"
#define AI_DEVMAPPER_SYSFS_HEALTH		"health"
#define AI_DEVMAPPER_SYSFS_POWER		"power"
#define AI_DEVMAPPER_SYSFS_DMA			"dma"
#define AI_DEVMAPPER_SYSFS_IOMMU		"iommu"
#define AI_DEVMAPPER_SYSFS_TOPOLOGY		"topology"
#define AI_DEVMAPPER_SYSFS_STATS		"stats"
#define AI_DEVMAPPER_SYSFS_MONITOR		"monitor"
#define AI_DEVMAPPER_SYSFS_BIND		"bind"
#define AI_DEVMAPPER_SYSFS_ERROR_LOG		"error_log"
#define AI_DEVMAPPER_SYSFS_RESCAN		"rescan"

/* Internal kernel API */
struct ai_devmapper_registry;

#ifdef CONFIG_AINOS_AI_DEVMAPPER

/* Device registration */
int ai_devmapper_register_device(struct device *dev,
				 enum ai_devmapper_device_type type,
				 unsigned int *device_id);
int ai_devmapper_unregister_device(unsigned int device_id);
int ai_devmapper_find_device(unsigned int device_id,
			     struct ai_devmapper_device *dev_info);

/* Enumerate and scan */
int ai_devmapper_enumerate(enum ai_devmapper_device_type type,
			   unsigned int *device_ids, int max_count,
			   int *actual_count);
int ai_devmapper_rescan(void);
int ai_devmapper_get_topology(struct ai_devmapper_topology *topology);

/* Health monitoring */
int ai_devmapper_get_health(unsigned int device_id,
			    struct ai_devmapper_health *health);
int ai_devmapper_enable_monitoring(unsigned int device_id);
int ai_devmapper_disable_monitoring(unsigned int device_id);
int ai_devmapper_get_error_log(unsigned int device_id,
			       struct ai_devmapper_error_log *log,
			       int max_entries, int *actual_entries);

/* Power management */
int ai_devmapper_set_power_state(unsigned int device_id,
				 enum ai_devmapper_power_state state);
int ai_devmapper_get_power_state(unsigned int device_id,
				 enum ai_devmapper_power_state *state);

/* DMA operations */
int ai_devmapper_set_dma_mask(unsigned int device_id, __u64 dma_mask);
int ai_devmapper_get_dma_info(unsigned int device_id,
			      struct ai_devmapper_dma *dma);
int ai_devmapper_map_dma(unsigned int device_id, unsigned long phys_addr,
			 size_t size, int direction);
int ai_devmapper_unmap_dma(unsigned int device_id, __u64 dma_addr,
			   size_t size, int direction);

/* IOMMU */
int ai_devmapper_attach_iommu(unsigned int device_id,
			      struct ai_devmapper_iommu *iommu);
int ai_devmapper_detach_iommu(unsigned int device_id);
int ai_devmapper_get_iommu(unsigned int device_id,
			   struct ai_devmapper_iommu *iommu);

/* AI device specific */
int ai_devmapper_get_ai_device(unsigned int device_id,
			       struct ai_devmapper_ai_device *ai_dev);
int ai_devmapper_get_ai_devices(unsigned int *device_ids, int max_count,
				int *actual_count);
int ai_devmapper_bind_process(unsigned int device_id, pid_t pid);
int ai_devmapper_unbind_process(unsigned int device_id, pid_t pid);

/* IRQ and MMIO */
int ai_devmapper_get_irq_info(unsigned int device_id,
			      struct ai_devmapper_irq_info *irq_info);
int ai_devmapper_get_mmio(unsigned int device_id, unsigned int bar_index,
			  struct ai_devmapper_mmio *mmio);

/* Memory */
int ai_devmapper_get_memory(unsigned int device_id,
			    struct ai_devmapper_memory *memory);

/* Capabilities */
int ai_devmapper_get_capabilities(unsigned int device_id,
				  struct ai_devmapper_caps *caps);

/* Utility */
int ai_devmapper_reset_device(unsigned int device_id);
int ai_devmapper_get_info(struct ai_devmapper_info *info);

#else /* !CONFIG_AINOS_AI_DEVMAPPER */

static inline int ai_devmapper_register_device(struct device *dev,
					       enum ai_devmapper_device_type t,
					       unsigned int *device_id)
{ return -ENODEV; }

static inline int ai_devmapper_unregister_device(unsigned int device_id)
{ return -ENODEV; }

static inline int ai_devmapper_find_device(unsigned int device_id,
					   struct ai_devmapper_device *dev)
{ return -ENODEV; }

static inline int ai_devmapper_enumerate(enum ai_devmapper_device_type t,
					 unsigned int *ids, int max, int *act)
{ return -ENODEV; }

static inline int ai_devmapper_rescan(void)
{ return -ENODEV; }

static inline int ai_devmapper_get_topology(struct ai_devmapper_topology *t)
{ return -ENODEV; }

static inline int ai_devmapper_get_health(unsigned int device_id,
					  struct ai_devmapper_health *h)
{ return -ENODEV; }

static inline int ai_devmapper_enable_monitoring(unsigned int device_id)
{ return -ENODEV; }

static inline int ai_devmapper_disable_monitoring(unsigned int device_id)
{ return -ENODEV; }

static inline int ai_devmapper_get_error_log(unsigned int device_id,
					     struct ai_devmapper_error_log *l,
					     int max, int *actual)
{ return -ENODEV; }

static inline int ai_devmapper_set_power_state(unsigned int device_id,
					       enum ai_devmapper_power_state s)
{ return -ENODEV; }

static inline int ai_devmapper_get_power_state(unsigned int device_id,
					       enum ai_devmapper_power_state *s)
{ return -ENODEV; }

static inline int ai_devmapper_set_dma_mask(unsigned int device_id, __u64 mask)
{ return -ENODEV; }

static inline int ai_devmapper_get_dma_info(unsigned int device_id,
					    struct ai_devmapper_dma *dma)
{ return -ENODEV; }

static inline int ai_devmapper_map_dma(unsigned int device_id,
				       unsigned long phys_addr, size_t size,
				       int direction)
{ return -ENODEV; }

static inline int ai_devmapper_unmap_dma(unsigned int device_id,
					 __u64 dma_addr, size_t size,
					 int direction)
{ return -ENODEV; }

static inline int ai_devmapper_attach_iommu(unsigned int device_id,
					    struct ai_devmapper_iommu *iommu)
{ return -ENODEV; }

static inline int ai_devmapper_detach_iommu(unsigned int device_id)
{ return -ENODEV; }

static inline int ai_devmapper_get_iommu(unsigned int device_id,
					 struct ai_devmapper_iommu *iommu)
{ return -ENODEV; }

static inline int ai_devmapper_get_ai_device(unsigned int device_id,
					     struct ai_devmapper_ai_device *d)
{ return -ENODEV; }

static inline int ai_devmapper_get_ai_devices(unsigned int *ids, int max,
					      int *actual)
{ return -ENODEV; }

static inline int ai_devmapper_bind_process(unsigned int device_id, pid_t pid)
{ return -ENODEV; }

static inline int ai_devmapper_unbind_process(unsigned int device_id, pid_t pid)
{ return -ENODEV; }

static inline int ai_devmapper_get_irq_info(unsigned int device_id,
					    struct ai_devmapper_irq_info *i)
{ return -ENODEV; }

static inline int ai_devmapper_get_mmio(unsigned int device_id,
					unsigned int bar,
					struct ai_devmapper_mmio *mmio)
{ return -ENODEV; }

static inline int ai_devmapper_get_memory(unsigned int device_id,
					  struct ai_devmapper_memory *mem)
{ return -ENODEV; }

static inline int ai_devmapper_get_capabilities(unsigned int device_id,
						struct ai_devmapper_caps *c)
{ return -ENODEV; }

static inline int ai_devmapper_reset_device(unsigned int device_id)
{ return -ENODEV; }

static inline int ai_devmapper_get_info(struct ai_devmapper_info *info)
{ return -ENODEV; }

#endif /* CONFIG_AINOS_AI_DEVMAPPER */

#endif /* _AINOS_AI_DEVMAPPER_H */