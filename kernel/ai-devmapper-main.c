// SPDX-License-Identifier: GPL-2.0-only
/*
 * Ainos AI Device Mapper - Main Module
 *
 * Copyright (C) 2026 Ainos Corporation
 * Authors: Ainos Kernel Team
 *
 * AI device mapping and management subsystem providing device
 * registry, discovery, hot-plug support, and health monitoring
 * for AI accelerators and other devices.
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/fs.h>
#include <linux/cdev.h>
#include <linux/device.h>
#include <linux/slab.h>
#include <linux/pci.h>
#include <linux/platform_device.h>
#include <linux/acpi.h>
#include <linux/of.h>
#include <linux/dma-mapping.h>
#include <linux/iommu.h>
#include <linux/mutex.h>
#include <linux/spinlock.h>
#include <linux/atomic.h>
#include <linux/ktime.h>
#include <linux/hrtimer.h>
#include <linux/workqueue.h>
#include <linux/kthread.h>
#include <linux/freezer.h>
#include <linux/sysfs.h>
#include <linux/kobject.h>
#include <linux/uaccess.h>
#include <linux/errno.h>
#include <linux/types.h>
#include <linux/string.h>
#include <linux/list.h>
#include <linux/idr.h>
#include <linux/delay.h>
#include <linux/cpumask.h>
#include <linux/topology.h>
#include <linux/pci_ids.h>

#include "ainos/ai-devmapper.h"

MODULE_LICENSE("GPL");
MODULE_VERSION(AI_DEVMAPPER_MODULE_VERSION);
MODULE_DESCRIPTION(AI_DEVMAPPER_MODULE_DESC);
MODULE_AUTHOR(AI_DEVMAPPER_MODULE_AUTHOR);
MODULE_ALIAS("ainos-ai-devmapper");

#define ai_devmapper_dbg(fmt, ...) \
	pr_debug("ai_devmapper: " fmt, ##__VA_ARGS__)
#define ai_devmapper_info(fmt, ...) \
	pr_info("ai_devmapper: " fmt, ##__VA_ARGS__)
#define ai_devmapper_warn(fmt, ...) \
	pr_warn("ai_devmapper: " fmt, ##__VA_ARGS__)
#define ai_devmapper_err(fmt, ...) \
	pr_err("ai_devmapper: " fmt, ##__VA_ARGS__)

static unsigned int devmapper_debug;
module_param(devmapper_debug, uint, 0644);
static unsigned int monitor_interval = 5;
module_param(monitor_interval, uint, 0644);
MODULE_PARM_DESC(monitor_interval, "Health monitor interval in seconds");

/*
 * Device entry in the registry
 */
struct ai_devmapper_entry {
	unsigned int			device_id;
	enum ai_devmapper_device_type	device_type;
	enum ai_devmapper_ai_class	ai_class;

	/* Identification */
	u32				vendor_id;
	u32				device_id_val;
	u32				subsystem_vendor;
	u32				subsystem_device;
	u32				revision;
	u32				class_code;

	/* Naming */
	char				name[64];
	char				driver[32];
	char				class_name[32];

	/* Hardware resources */
	u64				mmio_start;
	u64				mmio_end;
	u64				mmio_len;
	unsigned int			irq_count;
	unsigned int			irq_base;
	int				numa_node;

	/* PCI location */
	unsigned int			domain;
	unsigned int			bus;
	unsigned int			slot;
	unsigned int			function;

	/* Power state */
	enum ai_devmapper_power_state	power_state;
	bool				enabled;

	/* Health */
	enum ai_devmapper_health_status	health_status;
	u64				uptime_ms;
	u64				last_error_timestamp;
	unsigned int			error_count;
	unsigned int			warning_count;
	u32				temperature_c;
	u32				voltage_uv;
	u64				power_uw;
	u64				frequency_hz;
	u32				utilization_percent;
	u64				memory_used;
	u64				memory_total;
	u32				bandwidth_used;
	u32				bandwidth_total;
	u32				link_speed;
	u32				link_width;
	u32				link_errors;

	/* DMA */
	u64				dma_mask;
	u64				coherent_dma_mask;
	unsigned int			dma_channels;

	/* IOMMU */
	unsigned int			iommu_group;
	bool				iommu_attached;

	/* AI specific */
	unsigned int			compute_units;
	unsigned int			cores_per_unit;
	u32				tflops_fp32;
	u32				tflops_fp16;
	u32				tflops_int8;
	u64				memory_size_bytes;
	u64				memory_bandwidth_bps;
	u32				cache_size_kb;
	u32				supported_precisions;
	u32				firmware_version;
	u32				pci_lanes;
	u32				pci_generation;
	unsigned int			bound_processes[16];
	unsigned int			nr_bound_processes;

	/* Monitoring */
	bool				monitoring_enabled;
	struct delayed_work		monitor_work;

	/* Error log */
	struct ai_devmapper_error_log	error_logs[32];
	unsigned int			error_log_head;
	unsigned int			error_log_count;

	/* Capabilities */
	u32				capabilities[16];
	unsigned int			nr_capabilities;

	/* Lock */
	spinlock_t			lock;

	/* List */
	struct list_head		list;
};

/*
 * Device mapper device context
 */
struct ai_devmapper_device {
	struct cdev		cdev;
	struct device		*device;
	struct kobject		*kobj;

	unsigned int		dev_id;
	char			name[64];
	bool			active;

	/* Device registry */
	struct list_head	entries;
	unsigned int		nr_entries;
	unsigned int		nr_ai_devices;
	struct mutex		entry_mutex;
	struct idr		entry_idr;

	/* Topology */
	struct ai_devmapper_topology topology;

	/* Monitoring */
	struct task_struct	*monitor_task;
	bool			monitoring_active;

	/* Statistics */
	atomic64_t		total_errors;
	atomic64_t		total_warnings;

	/* List */
	struct list_head	list;
};

static dev_t ai_devmapper_devno;
static struct class *ai_devmapper_class;
static struct list_head ai_devmapper_devices;
static struct mutex ai_devmapper_global_mutex;
static atomic_t ai_devmapper_device_count;
static unsigned int ai_devmapper_major;
static struct kmem_cache *ai_devmapper_entry_cache;
static struct kmem_cache *ai_devmapper_device_cache;

/*
 * Entry management
 */

static struct ai_devmapper_entry *ai_devmapper_entry_alloc(void)
{
	struct ai_devmapper_entry *entry;

	entry = kmem_cache_zalloc(ai_devmapper_entry_cache, GFP_KERNEL);
	if (!entry)
		return NULL;

	spin_lock_init(&entry->lock);
	INIT_LIST_HEAD(&entry->list);
	INIT_DELAYED_WORK(&entry->monitor_work, NULL);

	entry->device_id = 0;
	entry->device_type = AI_DEVMAPPER_DEV_UNKNOWN;
	entry->ai_class = AI_DEVMAPPER_AI_CLASS_NONE;
	entry->power_state = AI_DEVMAPPER_POWER_D0;
	entry->enabled = false;
	entry->health_status = AI_DEVMAPPER_HEALTH_UNKNOWN;
	entry->uptime_ms = 0;
	entry->last_error_timestamp = 0;
	entry->error_count = 0;
	entry->warning_count = 0;
	entry->temperature_c = 35;
	entry->voltage_uv = 0;
	entry->power_uw = 0;
	entry->frequency_hz = 0;
	entry->utilization_percent = 0;
	entry->memory_used = 0;
	entry->memory_total = 0;
	entry->bandwidth_used = 0;
	entry->nr_bound_processes = 0;
	entry->monitoring_enabled = false;
	entry->nr_capabilities = 0;
	entry->error_log_head = 0;
	entry->error_log_count = 0;
	entry->iommu_attached = false;
	entry->iommu_group = 0;
	entry->link_errors = 0;
	entry->numa_node = NUMA_NO_NODE;

	return entry;
}

static void ai_devmapper_entry_free(struct ai_devmapper_entry *entry)
{
	if (!entry)
		return;
	kmem_cache_free(ai_devmapper_entry_cache, entry);
}

static struct ai_devmapper_entry *ai_devmapper_find_entry(
		struct ai_devmapper_device *dev, unsigned int device_id)
{
	struct ai_devmapper_entry *entry;

	mutex_lock(&dev->entry_mutex);
	list_for_each_entry(entry, &dev->entries, list) {
		if (entry->device_id == device_id) {
			mutex_unlock(&dev->entry_mutex);
			return entry;
		}
	}
	mutex_unlock(&dev->entry_mutex);

	return NULL;
}

/*
 * Health monitoring
 */

static void ai_devmapper_monitor_device(struct ai_devmapper_entry *entry)
{
	unsigned long flags;

	spin_lock_irqsave(&entry->lock, flags);

	entry->uptime_ms += monitor_interval * 1000;

	if (entry->temperature_c > 85) {
		entry->health_status = AI_DEVMAPPER_HEALTH_WARNING;
		entry->warning_count++;
	}

	if (entry->link_errors > 100) {
		entry->health_status = AI_DEVMAPPER_HEALTH_ERROR;
		entry->error_count++;
		entry->last_error_timestamp = ktime_get_real_ns();
	}

	if (entry->utilization_percent > 95) {
		entry->health_status = AI_DEVMAPPER_HEALTH_DEGRADED;
	}

	if (entry->temperature_c > 100) {
		entry->health_status = AI_DEVMAPPER_HEALTH_CRITICAL;
		entry->error_count++;
		entry->last_error_timestamp = ktime_get_real_ns();
		ai_devmapper_warn("Device %u CRITICAL: temp=%dC\n",
				 entry->device_id, entry->temperature_c);
	}

	spin_unlock_irqrestore(&entry->lock, flags);
}

static int ai_devmapper_monitor_worker(void *data)
{
	struct ai_devmapper_device *dev = data;
	struct ai_devmapper_entry *entry;

	while (!kthread_should_stop()) {
		if (unlikely(freezing(current)))
			__refrigerator(false);

		mutex_lock(&dev->entry_mutex);
		list_for_each_entry(entry, &dev->entries, list) {
			if (entry->monitoring_enabled)
				ai_devmapper_monitor_device(entry);
		}
		mutex_unlock(&dev->entry_mutex);

		ssleep(monitor_interval);
	}

	return 0;
}

/*
 * Device file operations
 */

static int ai_devmapper_open(struct inode *inode, struct file *file)
{
	struct ai_devmapper_device *dev = container_of(inode->i_cdev,
						       struct ai_devmapper_device,
						       cdev);
	if (!dev || !dev->active)
		return -ENODEV;
	file->private_data = dev;
	return 0;
}

static int ai_devmapper_release(struct inode *inode, struct file *file)
{
	return 0;
}

static long ai_devmapper_ioctl(struct file *file, unsigned int cmd,
			       unsigned long arg)
{
	struct ai_devmapper_device *dev = file->private_data;
	void __user *argp = (void __user *)arg;
	struct ai_devmapper_info info;
	struct ai_devmapper_register reg;
	struct ai_devmapper_unregister unreg;
	struct ai_devmapper_device dev_info;
	struct ai_devmapper_enum enum_info;
	struct ai_devmapper_health health;
	struct ai_devmapper_power power;
	struct ai_devmapper_dma dma;
	struct ai_devmapper_irq_info irq_info;
	struct ai_devmapper_mmio mmio;
	struct ai_devmapper_iommu iommu;
	struct ai_devmapper_ai_devices ai_devs;
	struct ai_devmapper_bind bind;
	struct ai_devmapper_memory memory;
	struct ai_devmapper_caps caps;
	struct ai_devmapper_topology topology;
	struct ai_devmapper_ai_device ai_dev;
	struct ai_devmapper_error_log error_log;
	struct ai_devmapper_entry *entry;
	int ret = 0;

	if (!dev || !dev->active)
		return -ENODEV;

	if (_IOC_TYPE(cmd) != AI_DEVMAPPER_IOC_MAGIC)
		return -ENOTTY;
	if (_IOC_NR(cmd) > AI_DEVMAPPER_IOC_MAXNR)
		return -ENOTTY;

	switch (cmd) {
	case AI_DEVMAPPER_IOCTL_GET_INFO:
		memset(&info, 0, sizeof(info));
		strscpy(info.version, AI_DEVMAPPER_MODULE_VERSION,
			sizeof(info.version));
		strscpy(info.description, AI_DEVMAPPER_MODULE_DESC,
			sizeof(info.description));
		info.major_version = 1;
		info.minor_version = 0;
		info.patch_version = 0;
		info.max_devices = 256;
		info.registered_devices = dev->nr_entries;
		info.ai_devices_available = dev->nr_ai_devices;
		info.monitoring_enabled = dev->monitoring_active;
		info.features = 0xFF;

		if (copy_to_user(argp, &info, sizeof(info)))
			ret = -EFAULT;
		break;

	case AI_DEVMAPPER_IOCTL_REGISTER:
		if (copy_from_user(&reg, argp, sizeof(reg))) {
			ret = -EFAULT;
			break;
		}

		entry = ai_devmapper_entry_alloc();
		if (!entry) {
			ret = -ENOMEM;
			break;
		}

		mutex_lock(&dev->entry_mutex);
		entry->device_id = idr_alloc_cyclic(&dev->entry_idr, entry,
						    1, 256, GFP_KERNEL);
		entry->device_type = reg.device_type;
		entry->vendor_id = reg.vendor_id;
		entry->device_id_val = reg.device_id;
		entry->subsystem_vendor = reg.subsystem_vendor;
		entry->subsystem_device = reg.subsystem_device;
		entry->revision = reg.revision;
		entry->mmio_start = reg.resource_start;
		entry->mmio_end = reg.resource_end;
		entry->mmio_len = reg.resource_end - reg.resource_start;
		entry->irq_count = reg.irq_count;
		strscpy(entry->name, reg.name, sizeof(entry->name));
		strscpy(entry->driver, reg.driver_name, sizeof(entry->driver));

		entry->enabled = true;
		entry->power_state = AI_DEVMAPPER_POWER_D0;
		entry->health_status = AI_DEVMAPPER_HEALTH_OK;
		entry->monitoring_enabled = true;

		if (reg.device_type >= AI_DEVMAPPER_DEV_AI_ACCEL &&
		    reg.device_type <= AI_DEVMAPPER_DEV_DSP) {
			dev->nr_ai_devices++;
			entry->ai_class = AI_DEVMAPPER_AI_CLASS_GENERAL;
		}

		list_add_tail(&entry->list, &dev->entries);
		dev->nr_entries++;
		reg.device_id_out = entry->device_id;
		mutex_unlock(&dev->entry_mutex);

		ai_devmapper_dbg("Device registered: id=%u type=%d %s\n",
				entry->device_id, reg.device_type, reg.name);

		reg.result = 0;
		if (copy_to_user(argp, &reg, sizeof(reg)))
			ret = -EFAULT;
		break;

	case AI_DEVMAPPER_IOCTL_UNREGISTER:
		if (copy_from_user(&unreg, argp, sizeof(unreg))) {
			ret = -EFAULT;
			break;
		}

		mutex_lock(&dev->entry_mutex);
		list_for_each_entry(entry, &dev->entries, list) {
			if (entry->device_id == unreg.device_id) {
				list_del(&entry->list);
				idr_remove(&dev->entry_idr, entry->device_id);
				dev->nr_entries--;
				if (entry->ai_class != AI_DEVMAPPER_AI_CLASS_NONE)
					dev->nr_ai_devices--;
				ai_devmapper_entry_free(entry);
				ai_devmapper_dbg("Device %u unregistered\n",
						unreg.device_id);
				break;
			}
		}
		mutex_unlock(&dev->entry_mutex);
		break;

	case AI_DEVMAPPER_IOCTL_GET_DEVICE:
		if (copy_from_user(&dev_info, argp, sizeof(dev_info))) {
			ret = -EFAULT;
			break;
		}

		entry = ai_devmapper_find_entry(dev, dev_info.device_id);
		if (!entry) {
			ret = -ENOENT;
			break;
		}

		dev_info.device_type = entry->device_type;
		dev_info.vendor_id = entry->vendor_id;
		dev_info.device_id_val = entry->device_id_val;
		dev_info.subsystem_vendor = entry->subsystem_vendor;
		dev_info.subsystem_device = entry->subsystem_device;
		dev_info.revision = entry->revision;
		dev_info.class_code = entry->class_code;
		dev_info.power_state = entry->power_state;
		dev_info.enabled = entry->enabled;
		dev_info.irq_count = entry->irq_count;
		dev_info.numa_node = entry->numa_node;
		dev_info.domain = entry->domain;
		dev_info.bus = entry->bus;
		dev_info.slot = entry->slot;
		dev_info.function = entry->function;
		strscpy(dev_info.name, entry->name, sizeof(dev_info.name));
		strscpy(dev_info.driver, entry->driver, sizeof(dev_info.driver));
		dev_info.mmio_start = entry->mmio_start;
		dev_info.mmio_end = entry->mmio_end;
		dev_info.mmio_len = entry->mmio_len;
		dev_info.health_status = entry->health_status;

		if (copy_to_user(argp, &dev_info, sizeof(dev_info)))
			ret = -EFAULT;
		break;

	case AI_DEVMAPPER_IOCTL_ENUMERATE:
		if (copy_from_user(&enum_info, argp, sizeof(enum_info))) {
			ret = -EFAULT;
			break;
		}

		enum_info.actual_devices = 0;
		mutex_lock(&dev->entry_mutex);
		list_for_each_entry(entry, &dev->entries, list) {
			if (enum_info.actual_devices >= enum_info.max_devices)
				break;
			if (enum_info.device_type == 0 ||
			    entry->device_type == enum_info.device_type) {
				enum_info.device_ids[enum_info.actual_devices] =
					entry->device_id;
				enum_info.actual_devices++;
			}
		}
		mutex_unlock(&dev->entry_mutex);

		if (copy_to_user(argp, &enum_info, sizeof(enum_info)))
			ret = -EFAULT;
		break;

	case AI_DEVMAPPER_IOCTL_SCAN:
		ai_devmapper_dbg("Rescan triggered\n");
		break;

	case AI_DEVMAPPER_IOCTL_GET_HEALTH:
		if (copy_from_user(&health, argp, sizeof(health))) {
			ret = -EFAULT;
			break;
		}

		entry = ai_devmapper_find_entry(dev, health.device_id);
		if (!entry) {
			ret = -ENOENT;
			break;
		}

		health.health_status = entry->health_status;
		health.uptime_ms = entry->uptime_ms;
		health.last_error_timestamp = entry->last_error_timestamp;
		health.error_count = entry->error_count;
		health.warning_count = entry->warning_count;
		health.temperature_c = entry->temperature_c;
		health.voltage_uv = entry->voltage_uv;
		health.power_uw = entry->power_uw;
		health.frequency_hz = entry->frequency_hz;
		health.utilization_percent = entry->utilization_percent;
		health.memory_used_mb = entry->memory_used / SZ_1M;
		health.memory_total_mb = entry->memory_total / SZ_1M;
		health.bandwidth_used_mbps = entry->bandwidth_used;
		health.bandwidth_total_mbps = entry->bandwidth_total;
		health.link_speed = entry->link_speed;
		health.link_width = entry->link_width;
		health.link_errors = entry->link_errors;

		if (copy_to_user(argp, &health, sizeof(health)))
			ret = -EFAULT;
		break;

	case AI_DEVMAPPER_IOCTL_SET_POWER:
		if (copy_from_user(&power, argp, sizeof(power))) {
			ret = -EFAULT;
			break;
		}

		entry = ai_devmapper_find_entry(dev, power.device_id);
		if (!entry) {
			ret = -ENOENT;
			break;
		}

		entry->power_state = power.power_state;
		power.result = 0;
		ai_devmapper_dbg("Device %u power state set to %d\n",
				power.device_id, power.power_state);

		if (copy_to_user(argp, &power, sizeof(power)))
			ret = -EFAULT;
		break;

	case AI_DEVMAPPER_IOCTL_RESET:
		entry = ai_devmapper_find_entry(dev, arg);
		if (!entry) {
			ret = -ENOENT;
			break;
		}
		entry->error_count = 0;
		entry->health_status = AI_DEVMAPPER_HEALTH_OK;
		entry->uptime_ms = 0;
		ai_devmapper_dbg("Device %u reset\n", (unsigned int)arg);
		break;

	case AI_DEVMAPPER_IOCTL_GET_DMA:
		if (copy_from_user(&dma, argp, sizeof(dma))) {
			ret = -EFAULT;
			break;
		}

		entry = ai_devmapper_find_entry(dev, dma.device_id);
		if (!entry) {
			ret = -ENOENT;
			break;
		}

		dma.dma_mask = entry->dma_mask;
		dma.coherent_dma_mask = entry->coherent_dma_mask;
		dma.dma_channels = entry->dma_channels;

		if (copy_to_user(argp, &dma, sizeof(dma)))
			ret = -EFAULT;
		break;

	case AI_DEVMAPPER_IOCTL_SET_DMA:
		if (copy_from_user(&dma, argp, sizeof(dma))) {
			ret = -EFAULT;
			break;
		}

		entry = ai_devmapper_find_entry(dev, dma.device_id);
		if (!entry) {
			ret = -ENOENT;
			break;
		}

		entry->dma_mask = dma.dma_mask;
		entry->coherent_dma_mask = dma.coherent_dma_mask;
		entry->dma_channels = dma.dma_channels;
		break;

	case AI_DEVMAPPER_IOCTL_GET_IRQ_INFO:
		if (copy_from_user(&irq_info, argp, sizeof(irq_info))) {
			ret = -EFAULT;
			break;
		}

		entry = ai_devmapper_find_entry(dev, irq_info.device_id);
		if (!entry) {
			ret = -ENOENT;
			break;
		}

		irq_info.irq_count = entry->irq_count;
		irq_info.irq_base = entry->irq_base;
		irq_info.msi_capable = 1;
		irq_info.msix_capable = 1;
		irq_info.msi_vectors = entry->irq_count;
		irq_info.msix_vectors = entry->irq_count;

		if (copy_to_user(argp, &irq_info, sizeof(irq_info)))
			ret = -EFAULT;
		break;

	case AI_DEVMAPPER_IOCTL_GET_MMIO:
		if (copy_from_user(&mmio, argp, sizeof(mmio))) {
			ret = -EFAULT;
			break;
		}

		entry = ai_devmapper_find_entry(dev, mmio.device_id);
		if (!entry) {
			ret = -ENOENT;
			break;
		}

		mmio.phys_addr = entry->mmio_start;
		mmio.length = entry->mmio_len;
		mmio.bar_index = mmio.bar_index;

		if (copy_to_user(argp, &mmio, sizeof(mmio)))
			ret = -EFAULT;
		break;

	case AI_DEVMAPPER_IOCTL_GET_IOMMU:
		if (copy_from_user(&iommu, argp, sizeof(iommu))) {
			ret = -EFAULT;
			break;
		}

		entry = ai_devmapper_find_entry(dev, iommu.device_id);
		if (!entry) {
			ret = -ENOENT;
			break;
		}

		iommu.iommu_group = entry->iommu_group;
		iommu.pasid_capable = 1;
		iommu.ats_supported = 1;
		iommu.pri_supported = 1;

		if (copy_to_user(argp, &iommu, sizeof(iommu)))
			ret = -EFAULT;
		break;

	case AI_DEVMAPPER_IOCTL_ATTACH_IOMMU:
		if (copy_from_user(&iommu, argp, sizeof(iommu))) {
			ret = -EFAULT;
			break;
		}

		entry = ai_devmapper_find_entry(dev, iommu.device_id);
		if (!entry) {
			ret = -ENOENT;
			break;
		}

		entry->iommu_attached = true;
		entry->iommu_group = iommu.iommu_group;
		ai_devmapper_dbg("Device %u IOMMU attached\n", iommu.device_id);
		break;

	case AI_DEVMAPPER_IOCTL_DETACH_IOMMU:
		entry = ai_devmapper_find_entry(dev, arg);
		if (!entry) {
			ret = -ENOENT;
			break;
		}
		entry->iommu_attached = false;
		ai_devmapper_dbg("Device %u IOMMU detached\n",
				(unsigned int)arg);
		break;

	case AI_DEVMAPPER_IOCTL_GET_AI_DEVICES:
		ai_devs.device_count = 0;
		mutex_lock(&dev->entry_mutex);
		list_for_each_entry(entry, &dev->entries, list) {
			if (entry->ai_class != AI_DEVMAPPER_AI_CLASS_NONE &&
			    ai_devs.device_count < 32) {
				ai_devs.device_ids[ai_devs.device_count] =
					entry->device_id;
				ai_devs.device_count++;
			}
		}
		mutex_unlock(&dev->entry_mutex);

		if (copy_to_user(argp, &ai_devs, sizeof(ai_devs)))
			ret = -EFAULT;
		break;

	case AI_DEVMAPPER_IOCTL_BIND_PROCESS:
		if (copy_from_user(&bind, argp, sizeof(bind))) {
			ret = -EFAULT;
			break;
		}

		entry = ai_devmapper_find_entry(dev, bind.device_id);
		if (!entry) {
			ret = -ENOENT;
			break;
		}

		if (entry->nr_bound_processes < 16) {
			entry->bound_processes[entry->nr_bound_processes] =
				bind.pid;
			entry->nr_bound_processes++;
			ai_devmapper_dbg("Process %d bound to device %u\n",
					bind.pid, bind.device_id);
		} else {
			ret = -EBUSY;
		}
		break;

	case AI_DEVMAPPER_IOCTL_UNBIND_PROCESS:
		if (copy_from_user(&bind, argp, sizeof(bind))) {
			ret = -EFAULT;
			break;
		}

		entry = ai_devmapper_find_entry(dev, bind.device_id);
		if (!entry) {
			ret = -ENOENT;
			break;
		}

		{
			int i;
			for (i = 0; i < entry->nr_bound_processes; i++) {
				if (entry->bound_processes[i] == bind.pid) {
					for (int j = i;
					     j < entry->nr_bound_processes - 1;
					     j++)
						entry->bound_processes[j] =
							entry->bound_processes[j+1];
					entry->nr_bound_processes--;
					ai_devmapper_dbg(
						"Process %d unbound from device %u\n",
						bind.pid, bind.device_id);
					break;
				}
			}
		}
		break;

	case AI_DEVMAPPER_IOCTL_GET_MEMORY:
		if (copy_from_user(&memory, argp, sizeof(memory))) {
			ret = -EFAULT;
			break;
		}

		entry = ai_devmapper_find_entry(dev, memory.device_id);
		if (!entry) {
			ret = -ENOENT;
			break;
		}

		memory.memory_base = 0;
		memory.memory_size = entry->memory_total;
		memory.memory_used = entry->memory_used;
		memory.memory_free = entry->memory_total - entry->memory_used;
		memory.bandwidth_mbps = entry->bandwidth_total;

		if (copy_to_user(argp, &memory, sizeof(memory)))
			ret = -EFAULT;
		break;

	case AI_DEVMAPPER_IOCTL_GET_CAPABILITIES:
		if (copy_from_user(&caps, argp, sizeof(caps))) {
			ret = -EFAULT;
			break;
		}

		entry = ai_devmapper_find_entry(dev, caps.device_id);
		if (!entry) {
			ret = -ENOENT;
			break;
		}

		memcpy(caps.capabilities, entry->capabilities,
		       sizeof(u32) * min_t(unsigned int, entry->nr_capabilities, 16));

		if (copy_to_user(argp, &caps, sizeof(caps)))
			ret = -EFAULT;
		break;

	case AI_DEVMAPPER_IOCTL_ENABLE_MONITOR:
		entry = ai_devmapper_find_entry(dev, arg);
		if (!entry) {
			ret = -ENOENT;
			break;
		}
		entry->monitoring_enabled = true;
		ai_devmapper_dbg("Monitoring enabled for device %u\n",
				(unsigned int)arg);
		break;

	case AI_DEVMAPPER_IOCTL_DISABLE_MONITOR:
		entry = ai_devmapper_find_entry(dev, arg);
		if (!entry) {
			ret = -ENOENT;
			break;
		}
		entry->monitoring_enabled = false;
		ai_devmapper_dbg("Monitoring disabled for device %u\n",
				(unsigned int)arg);
		break;

	case AI_DEVMAPPER_IOCTL_GET_TOPOLOGY:
		memset(&topology, 0, sizeof(topology));
		topology.device_count = dev->nr_entries;
		topology.numa_nodes = num_online_nodes();
		topology.pci_domains = 1;
		topology.ai_devices = dev->nr_ai_devices;
		topology.gpu_count = 0;
		topology.npu_count = 0;
		topology.fpga_count = 0;
		topology.dsp_count = 0;

		mutex_lock(&dev->entry_mutex);
		list_for_each_entry(entry, &dev->entries, list) {
			switch (entry->device_type) {
			case AI_DEVMAPPER_DEV_GPU:
				topology.gpu_count++;
				break;
			case AI_DEVMAPPER_DEV_NPU:
				topology.npu_count++;
				break;
			case AI_DEVMAPPER_DEV_FPGA:
				topology.fpga_count++;
				break;
			case AI_DEVMAPPER_DEV_DSP:
				topology.dsp_count++;
				break;
			default:
				break;
			}
		}
		mutex_unlock(&dev->entry_mutex);

		if (copy_to_user(argp, &topology, sizeof(topology)))
			ret = -EFAULT;
		break;

	case AI_DEVMAPPER_IOCTL_GET_AI_DEVICE:
		if (copy_from_user(&ai_dev, argp, sizeof(ai_dev))) {
			ret = -EFAULT;
			break;
		}

		entry = ai_devmapper_find_entry(dev, ai_dev.device_id);
		if (!entry) {
			ret = -ENOENT;
			break;
		}

		ai_dev.ai_class = entry->ai_class;
		ai_dev.compute_units = entry->compute_units;
		ai_dev.cores_per_unit = entry->cores_per_unit;
		ai_dev.frequency_mhz = entry->frequency_hz / 1000000;
		ai_dev.tflops_fp32 = entry->tflops_fp32;
		ai_dev.tflops_fp16 = entry->tflops_fp16;
		ai_dev.tflops_int8 = entry->tflops_int8;
		ai_dev.memory_size_bytes = entry->memory_size_bytes;
		ai_dev.memory_bandwidth_bps = entry->memory_bandwidth_bps;
		ai_dev.cache_size_kb = entry->cache_size_kb;
		ai_dev.supported_precisions = entry->supported_precisions;
		ai_dev.firmware_version = entry->firmware_version;
		ai_dev.pci_lanes = entry->pci_lanes;
		ai_dev.pci_generation = entry->pci_generation;

		if (copy_to_user(argp, &ai_dev, sizeof(ai_dev)))
			ret = -EFAULT;
		break;

	case AI_DEVMAPPER_IOCTL_GET_ERROR_LOG:
		if (copy_from_user(&error_log, argp, sizeof(error_log))) {
			ret = -EFAULT;
			break;
		}

		entry = ai_devmapper_find_entry(dev, error_log.device_id);
		if (!entry) {
			ret = -ENOENT;
			break;
		}

		if (entry->error_log_count > 0) {
			unsigned int idx = (entry->error_log_head + 1) %
					   ARRAY_SIZE(entry->error_logs);
			error_log.error_type = entry->error_logs[idx].error_type;
			error_log.timestamp = entry->error_logs[idx].timestamp;
			error_log.error_code = entry->error_logs[idx].error_code;
			error_log.severity = entry->error_logs[idx].severity;
			strscpy(error_log.message,
				entry->error_logs[idx].message,
				sizeof(error_log.message));
		}

		if (copy_to_user(argp, &error_log, sizeof(error_log)))
			ret = -EFAULT;
		break;

	default:
		ret = -ENOTTY;
		break;
	}

	return ret;
}

#ifdef CONFIG_COMPAT
static long ai_devmapper_compat_ioctl(struct file *file, unsigned int cmd,
				      unsigned long arg)
{
	return ai_devmapper_ioctl(file, cmd, (unsigned long)compat_ptr(arg));
}
#endif

static const struct file_operations ai_devmapper_fops = {
	.owner		= THIS_MODULE,
	.open		= ai_devmapper_open,
	.release	= ai_devmapper_release,
	.unlocked_ioctl	= ai_devmapper_ioctl,
#ifdef CONFIG_COMPAT
	.compat_ioctl	= ai_devmapper_compat_ioctl,
#endif
	.llseek		= noop_llseek,
};

/*
 * Sysfs interface
 */

static ssize_t devices_show(struct kobject *kobj,
			    struct kobj_attribute *attr, char *buf)
{
	struct ai_devmapper_device *dev = container_of(kobj,
						       struct ai_devmapper_device,
						       *kobj);
	return sysfs_emit(buf, "%u\n", dev->nr_entries);
}

static ssize_t ai_devices_show(struct kobject *kobj,
			       struct kobj_attribute *attr, char *buf)
{
	struct ai_devmapper_device *dev = container_of(kobj,
						       struct ai_devmapper_device,
						       *kobj);
	return sysfs_emit(buf, "%u\n", dev->nr_ai_devices);
}

static ssize_t topology_show(struct kobject *kobj,
			     struct kobj_attribute *attr, char *buf)
{
	struct ai_devmapper_device *dev = container_of(kobj,
						       struct ai_devmapper_device,
						       *kobj);
	return sysfs_emit(buf, "devices=%u ai=%u gpu=%u npu=%u fpga=%u dsp=%u\n",
			  dev->topology.device_count,
			  dev->topology.ai_devices,
			  dev->topology.gpu_count,
			  dev->topology.npu_count,
			  dev->topology.fpga_count,
			  dev->topology.dsp_count);
}

static ssize_t stats_show(struct kobject *kobj,
			  struct kobj_attribute *attr, char *buf)
{
	struct ai_devmapper_device *dev = container_of(kobj,
						       struct ai_devmapper_device,
						       *kobj);
	return sysfs_emit(buf,
			  "devices=%u ai_devices=%u errors=%llu warnings=%llu\n",
			  dev->nr_entries, dev->nr_ai_devices,
			  atomic64_read(&dev->total_errors),
			  atomic64_read(&dev->total_warnings));
}

static ssize_t rescan_store(struct kobject *kobj,
			    struct kobj_attribute *attr,
			    const char *buf, size_t count)
{
	ai_devmapper_dbg("Rescan requested\n");
	return count;
}

static struct kobj_attribute devices_attr = __ATTR_RO(devices);
static struct kobj_attribute ai_devices_attr = __ATTR_RO(ai_devices);
static struct kobj_attribute topology_attr = __ATTR_RO(topology);
static struct kobj_attribute stats_attr = __ATTR_RO(stats);
static struct kobj_attribute rescan_attr = __ATTR_WO(rescan);

static struct attribute *ai_devmapper_attrs[] = {
	&devices_attr.attr,
	&ai_devices_attr.attr,
	&topology_attr.attr,
	&stats_attr.attr,
	&rescan_attr.attr,
	NULL,
};

ATTRIBUTE_GROUPS(ai_devmapper);

/*
 * Module init/exit
 */

static int ai_devmapper_create_device(struct ai_devmapper_device **dev_out)
{
	struct ai_devmapper_device *dev;
	int ret;

	dev = kmem_cache_zalloc(ai_devmapper_device_cache, GFP_KERNEL);
	if (!dev)
		return -ENOMEM;

	dev->dev_id = atomic_inc_return(&ai_devmapper_device_count);
	snprintf(dev->name, sizeof(dev->name), "ai-devmapper-%u", dev->dev_id);
	dev->active = false;

	INIT_LIST_HEAD(&dev->entries);
	mutex_init(&dev->entry_mutex);
	idr_init(&dev->entry_idr);
	dev->nr_entries = 0;
	dev->nr_ai_devices = 0;
	dev->monitoring_active = false;

	atomic64_set(&dev->total_errors, 0);
	atomic64_set(&dev->total_warnings, 0);

	memset(&dev->topology, 0, sizeof(dev->topology));

	cdev_init(&dev->cdev, &ai_devmapper_fops);
	dev->cdev.owner = THIS_MODULE;

	ret = cdev_add(&dev->cdev, dev->dev_id, 1);
	if (ret)
		goto err_free;

	dev->device = device_create(ai_devmapper_class, NULL, dev->dev_id, dev,
				    "ai-devmapper-%u", dev->dev_id);
	if (IS_ERR(dev->device)) {
		ret = PTR_ERR(dev->device);
		goto err_cdev;
	}

	dev->kobj = &dev->device->kobj;
	dev->active = true;

	dev->monitor_task = kthread_run(ai_devmapper_monitor_worker, dev,
					"ai-devmapper-mon-%u", dev->dev_id);
	if (IS_ERR(dev->monitor_task)) {
		ret = PTR_ERR(dev->monitor_task);
		dev->monitor_task = NULL;
		goto err_device;
	}
	dev->monitoring_active = true;

	list_add_tail(&dev->list, &ai_devmapper_devices);

	ai_devmapper_info("Device created: %s\n", dev->name);

	*dev_out = dev;
	return 0;

err_device:
	device_destroy(ai_devmapper_class, dev->dev_id);
err_cdev:
	cdev_del(&dev->cdev);
err_free:
	kmem_cache_free(ai_devmapper_device_cache, dev);
	return ret;
}

static void ai_devmapper_destroy_device(struct ai_devmapper_device *dev)
{
	struct ai_devmapper_entry *entry, *tmp;

	if (!dev)
		return;

	dev->active = false;

	if (dev->monitor_task) {
		kthread_stop(dev->monitor_task);
		dev->monitoring_active = false;
	}

	list_for_each_entry_safe(entry, tmp, &dev->entries, list) {
		list_del(&entry->list);
		idr_remove(&dev->entry_idr, entry->device_id);
		ai_devmapper_entry_free(entry);
	}

	device_destroy(ai_devmapper_class, dev->dev_id);
	cdev_del(&dev->cdev);
	idr_destroy(&dev->entry_idr);
	mutex_destroy(&dev->entry_mutex);
	list_del(&dev->list);
	kmem_cache_free(ai_devmapper_device_cache, dev);
}

static int __init ai_devmapper_init(void)
{
	struct ai_devmapper_device *dev;
	int ret;

	ai_devmapper_info("Loading Ainos AI Device Mapper v%s\n",
			  AI_DEVMAPPER_MODULE_VERSION);

	INIT_LIST_HEAD(&ai_devmapper_devices);
	mutex_init(&ai_devmapper_global_mutex);
	atomic_set(&ai_devmapper_device_count, 0);

	ai_devmapper_entry_cache = kmem_cache_create("ai_devmapper_entry",
						     sizeof(struct ai_devmapper_entry),
						     0, SLAB_HWCACHE_ALIGN,
						     NULL);
	if (!ai_devmapper_entry_cache)
		return -ENOMEM;

	ai_devmapper_device_cache = kmem_cache_create("ai_devmapper_device",
						      sizeof(struct ai_devmapper_device),
						      0, SLAB_HWCACHE_ALIGN,
						      NULL);
	if (!ai_devmapper_device_cache) {
		ret = -ENOMEM;
		goto err_entry_cache;
	}

	ret = alloc_chrdev_region(&ai_devmapper_devno, 0,
				  AI_DEVMAPPER_MAX_DEVICES,
				  AI_DEVMAPPER_MODULE_NAME);
	if (ret) {
		ai_devmapper_err("Failed to allocate chrdev: %d\n", ret);
		goto err_device_cache;
	}

	ai_devmapper_major = MAJOR(ai_devmapper_devno);

	ai_devmapper_class = class_create(THIS_MODULE, AI_DEVMAPPER_CLASS_NAME);
	if (IS_ERR(ai_devmapper_class)) {
		ret = PTR_ERR(ai_devmapper_class);
		goto err_unregister;
	}

	ret = ai_devmapper_create_device(&dev);
	if (ret)
		goto err_class;

	ai_devmapper_info("Ainos AI Device Mapper loaded (major=%u)\n",
			  ai_devmapper_major);
	return 0;

err_class:
	class_destroy(ai_devmapper_class);
err_unregister:
	unregister_chrdev_region(ai_devmapper_devno, AI_DEVMAPPER_MAX_DEVICES);
err_device_cache:
	kmem_cache_destroy(ai_devmapper_device_cache);
err_entry_cache:
	kmem_cache_destroy(ai_devmapper_entry_cache);
	return ret;
}

static void __exit ai_devmapper_exit(void)
{
	struct ai_devmapper_device *dev, *tmp;

	ai_devmapper_info("Unloading Ainos AI Device Mapper\n");

	list_for_each_entry_safe(dev, tmp, &ai_devmapper_devices, list)
		ai_devmapper_destroy_device(dev);

	class_destroy(ai_devmapper_class);
	unregister_chrdev_region(ai_devmapper_devno, AI_DEVMAPPER_MAX_DEVICES);
	kmem_cache_destroy(ai_devmapper_device_cache);
	kmem_cache_destroy(ai_devmapper_entry_cache);

	ai_devmapper_info("Ainos AI Device Mapper unloaded\n");
}

/*
 * Exported kernel API
 */

int ai_devmapper_register_device(struct device *dev,
				 enum ai_devmapper_device_type type,
				 unsigned int *device_id)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_register_device);

int ai_devmapper_unregister_device(unsigned int device_id)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_unregister_device);

int ai_devmapper_find_device(unsigned int device_id,
			     struct ai_devmapper_device *dev_info)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_find_device);

int ai_devmapper_enumerate(enum ai_devmapper_device_type type,
			   unsigned int *device_ids, int max_count,
			   int *actual_count)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_enumerate);

int ai_devmapper_rescan(void)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_rescan);

int ai_devmapper_get_topology(struct ai_devmapper_topology *topology)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_get_topology);

int ai_devmapper_get_health(unsigned int device_id,
			    struct ai_devmapper_health *health)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_get_health);

int ai_devmapper_enable_monitoring(unsigned int device_id)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_enable_monitoring);

int ai_devmapper_disable_monitoring(unsigned int device_id)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_disable_monitoring);

int ai_devmapper_get_error_log(unsigned int device_id,
			       struct ai_devmapper_error_log *log,
			       int max_entries, int *actual_entries)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_get_error_log);

int ai_devmapper_set_power_state(unsigned int device_id,
				 enum ai_devmapper_power_state state)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_set_power_state);

int ai_devmapper_get_power_state(unsigned int device_id,
				 enum ai_devmapper_power_state *state)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_get_power_state);

int ai_devmapper_set_dma_mask(unsigned int device_id, __u64 dma_mask)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_set_dma_mask);

int ai_devmapper_get_dma_info(unsigned int device_id,
			      struct ai_devmapper_dma *dma)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_get_dma_info);

int ai_devmapper_map_dma(unsigned int device_id, unsigned long phys_addr,
			 size_t size, int direction)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_map_dma);

int ai_devmapper_unmap_dma(unsigned int device_id, __u64 dma_addr,
			   size_t size, int direction)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_unmap_dma);

int ai_devmapper_attach_iommu(unsigned int device_id,
			      struct ai_devmapper_iommu *iommu)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_attach_iommu);

int ai_devmapper_detach_iommu(unsigned int device_id)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_detach_iommu);

int ai_devmapper_get_iommu(unsigned int device_id,
			   struct ai_devmapper_iommu *iommu)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_get_iommu);

int ai_devmapper_get_ai_device(unsigned int device_id,
			       struct ai_devmapper_ai_device *ai_dev)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_get_ai_device);

int ai_devmapper_get_ai_devices(unsigned int *device_ids, int max_count,
				int *actual_count)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_get_ai_devices);

int ai_devmapper_bind_process(unsigned int device_id, pid_t pid)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_bind_process);

int ai_devmapper_unbind_process(unsigned int device_id, pid_t pid)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_unbind_process);

int ai_devmapper_get_irq_info(unsigned int device_id,
			      struct ai_devmapper_irq_info *irq_info)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_get_irq_info);

int ai_devmapper_get_mmio(unsigned int device_id, unsigned int bar_index,
			  struct ai_devmapper_mmio *mmio)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_get_mmio);

int ai_devmapper_get_memory(unsigned int device_id,
			    struct ai_devmapper_memory *memory)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_get_memory);

int ai_devmapper_get_capabilities(unsigned int device_id,
				  struct ai_devmapper_caps *caps)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_get_capabilities);

int ai_devmapper_reset_device(unsigned int device_id)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_reset_device);

int ai_devmapper_get_info(struct ai_devmapper_info *info)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_devmapper_get_info);

module_init(ai_devmapper_init);
module_exit(ai_devmapper_exit);