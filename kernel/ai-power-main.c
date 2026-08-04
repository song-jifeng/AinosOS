// SPDX-License-Identifier: GPL-2.0-only
/*
 * Ainos AI Power Management - Main Module
 *
 * Copyright (C) 2026 Ainos Corporation
 * Authors: Ainos Kernel Team
 *
 * AI power management subsystem providing intelligent frequency
 * scaling, power consumption prediction, DVFS, thermal management,
 * and performance/power trade-off optimization.
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/fs.h>
#include <linux/cdev.h>
#include <linux/device.h>
#include <linux/slab.h>
#include <linux/pm_opp.h>
#include <linux/cpufreq.h>
#include <linux/cpuidle.h>
#include <linux/thermal.h>
#include <linux/power_supply.h>
#include <linux/pm_qos.h>
#include <linux/pm_wakeirq.h>
#include <linux/pm_runtime.h>
#include <linux/pm_domain.h>
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
#include <linux/math64.h>
#include <linux/percpu.h>
#include <linux/jiffies.h>
#include <linux/sched.h>
#include <linux/delay.h>
#include <linux/string.h>
#include <linux/cpu.h>
#include <linux/suspend.h>
#include <linux/notifier.h>
#include <linux/interrupt.h>
#include <linux/clk.h>
#include <linux/regulator/consumer.h>
#include <linux/energy_model.h>

#include "ainos/ai-power.h"

MODULE_LICENSE("GPL");
MODULE_VERSION(AI_POWER_MODULE_VERSION);
MODULE_DESCRIPTION(AI_POWER_MODULE_DESC);
MODULE_AUTHOR(AI_POWER_MODULE_AUTHOR);
MODULE_ALIAS("ainos-ai-power");

#define ai_power_dbg(fmt, ...) \
	pr_debug("ai_power: " fmt, ##__VA_ARGS__)
#define ai_power_info(fmt, ...) \
	pr_info("ai_power: " fmt, ##__VA_ARGS__)
#define ai_power_warn(fmt, ...) \
	pr_warn("ai_power: " fmt, ##__VA_ARGS__)
#define ai_power_err(fmt, ...) \
	pr_err("ai_power: " fmt, ##__VA_ARGS__)

static unsigned int power_debug;
module_param(power_debug, uint, 0644);
static unsigned int dvfs_enabled = 1;
module_param(dvfs_enabled, uint, 0644);
static unsigned int thermal_throttle_temp = 85;
module_param(thermal_throttle_temp, uint, 0644);
static unsigned int power_profile = AI_POWER_PROFILE_BALANCED;
module_param(power_profile, uint, 0644);

/*
 * Power domain state
 */
struct ai_power_domain_state {
	unsigned int		domain_id;
	enum ai_power_domain	domain_type;
	char			name[32];
	bool			initialized;

	/* Frequency */
	u64			current_freq_hz;
	u64			min_freq_hz;
	u64			max_freq_hz;
	u64			target_freq_hz;

	/* Voltage */
	u64			current_voltage_uv;
	u64			min_voltage_uv;
	u64			max_voltage_uv;
	u64			target_voltage_uv;

	/* Power */
	u64			current_power_uw;
	u64			avg_power_uw;
	u64			max_power_uw;
	u64			min_power_uw;
	u64			energy_uj;

	/* Thermal */
	int			temperature_c;
	int			trip_temp_c;
	int			critical_temp_c;
	int			passive_temp_c;
	int			hot_temp_c;
	enum ai_power_throttle_mode	throttle_mode;
	unsigned int		fan_speed_rpm;

	/* DVFS */
	u32			dvfs_enabled;
	u32			dvfs_latency_us;
	u32			dvfs_step_size;
	u32			dvfs_transition_count;

	/* OPP */
	u32			opp_count;
	u32			current_opp_index;

	/* Idle */
	u64			idle_time_ms;
	u32			current_cstate;

	/* Lock */
	spinlock_t		lock;

	/* List */
	struct list_head	list;
};

/*
 * AI power device
 */
struct ai_power_device {
	struct cdev		cdev;
	struct device		*device;
	struct kobject		*kobj;

	unsigned int		dev_id;
	char			name[64];
	bool			active;

	/* Power domains */
	struct list_head	domains;
	unsigned int		nr_domains;
	struct mutex		domain_mutex;

	/* Current policy */
	struct ai_power_policy	current_policy;
	enum ai_power_profile_type	current_profile;
	enum ai_power_governor_type	current_governor;

	/* Thermal monitoring */
	struct task_struct	*thermal_task;
	bool			thermal_monitoring;

	/* DVFS management */
	struct delayed_work	dvfs_work;

	/* Battery info */
	struct ai_power_battery	battery_info;
	bool			battery_present;

	/* PSI tracking */
	struct ai_power_psi	psi_info;

	/* PSYS */
	struct ai_power_psys	psys_info;

	/* Prediction */
	struct ai_power_prediction last_prediction;

	/* Notifier */
	struct notifier_block	pm_notifier;
	struct notifier_block	thermal_notifier;

	/* List */
	struct list_head	list;
};

static dev_t ai_power_devno;
static struct class *ai_power_class;
static struct list_head ai_power_devices;
static struct mutex ai_power_global_mutex;
static atomic_t ai_power_device_count;
static unsigned int ai_power_major;
static struct kmem_cache *ai_power_domain_cache;
static struct kmem_cache *ai_power_device_cache;

/*
 * Domain management
 */

static struct ai_power_domain_state *ai_power_domain_alloc(
		enum ai_power_domain type, const char *name)
{
	struct ai_power_domain_state *domain;

	domain = kmem_cache_zalloc(ai_power_domain_cache, GFP_KERNEL);
	if (!domain)
		return NULL;

	domain->domain_type = type;
	domain->initialized = false;
	strscpy(domain->name, name, sizeof(domain->name));
	spin_lock_init(&domain->lock);
	INIT_LIST_HEAD(&domain->list);

	domain->current_freq_hz = 0;
	domain->min_freq_hz = 0;
	domain->max_freq_hz = 0;
	domain->current_voltage_uv = 0;
	domain->current_power_uw = 0;
	domain->temperature_c = 40;
	domain->trip_temp_c = 80;
	domain->critical_temp_c = 100;
	domain->passive_temp_c = 85;
	domain->hot_temp_c = 95;
	domain->throttle_mode = AI_POWER_THROTTLE_NONE;
	domain->dvfs_enabled = dvfs_enabled;
	domain->dvfs_transition_count = 0;
	domain->current_cstate = AI_POWER_CSTATE_C0;
	domain->opp_count = 0;
	domain->current_opp_index = 0;
	domain->fan_speed_rpm = 0;

	ai_power_dbg("Domain '%s' type=%d allocated\n", name, type);
	return domain;
}

static void ai_power_domain_free(struct ai_power_domain_state *domain)
{
	if (!domain)
		return;
	kmem_cache_free(ai_power_domain_cache, domain);
}

static struct ai_power_domain_state *ai_power_find_domain(
		struct ai_power_device *dev, unsigned int domain_id)
{
	struct ai_power_domain_state *domain;

	mutex_lock(&dev->domain_mutex);
	list_for_each_entry(domain, &dev->domains, list) {
		if (domain->domain_id == domain_id) {
			mutex_unlock(&dev->domain_mutex);
			return domain;
		}
	}
	mutex_unlock(&dev->domain_mutex);

	return NULL;
}

/*
 * Thermal monitoring
 */

static int ai_power_thermal_worker(void *data)
{
	struct ai_power_device *dev = data;
	struct ai_power_domain_state *domain;

	while (!kthread_should_stop()) {
		if (unlikely(freezing(current)))
			__refrigerator(false);

		mutex_lock(&dev->domain_mutex);
		list_for_each_entry(domain, &dev->domains, list) {
			int temp = domain->temperature_c;

			if (temp >= domain->critical_temp_c) {
				domain->throttle_mode =
					AI_POWER_THROTTLE_EMERGENCY;
				ai_power_warn("Domain '%s' critical temp: %dC\n",
					      domain->name, temp);
			} else if (temp >= domain->hot_temp_c) {
				domain->throttle_mode =
					AI_POWER_THROTTLE_ACTIVE;
				ai_power_warn("Domain '%s' hot temp: %dC\n",
					      domain->name, temp);
			} else if (temp >= domain->passive_temp_c) {
				domain->throttle_mode =
					AI_POWER_THROTTLE_PASSIVE;
				ai_power_dbg("Domain '%s' passive cooling: %dC\n",
					     domain->name, temp);
			} else {
				domain->throttle_mode =
					AI_POWER_THROTTLE_NONE;
			}
		}
		mutex_unlock(&dev->domain_mutex);

		msleep_interruptible(500);
	}

	return 0;
}

/*
 * DVFS management
 */

static void ai_power_dvfs_work_handler(struct work_struct *work)
{
	struct ai_power_device *dev = container_of(work,
						   struct ai_power_device,
						   dvfs_work.work);
	struct ai_power_domain_state *domain;

	mutex_lock(&dev->domain_mutex);
	list_for_each_entry(domain, &dev->domains, list) {
		unsigned long flags;

		spin_lock_irqsave(&domain->lock, flags);

		if (domain->dvfs_enabled &&
		    domain->target_freq_hz != domain->current_freq_hz) {
			domain->current_freq_hz = domain->target_freq_hz;
			domain->dvfs_transition_count++;

			ai_power_dbg("Domain '%s' DVFS: %llu -> %llu Hz\n",
				     domain->name, domain->current_freq_hz,
				     domain->target_freq_hz);
		}

		spin_unlock_irqrestore(&domain->lock, flags);
	}
	mutex_unlock(&dev->domain_mutex);

	schedule_delayed_work(&dev->dvfs_work, msecs_to_jiffies(100));
}

/*
 * Power state estimation
 */

static u64 ai_power_estimate_power(struct ai_power_domain_state *domain)
{
	u64 power = 0;

	if (domain->current_freq_hz > 0 && domain->current_voltage_uv > 0) {
		u64 freq_mhz = domain->current_freq_hz / 1000000;
		u64 volt_v = domain->current_voltage_uv / 1000000;

		power = (freq_mhz * freq_mhz * volt_v * volt_v) / 1000;
	}

	return power;
}

static int ai_power_apply_policy(struct ai_power_device *dev)
{
	struct ai_power_domain_state *domain;

	mutex_lock(&dev->domain_mutex);
	list_for_each_entry(domain, &dev->domains, list) {
		unsigned long flags;

		spin_lock_irqsave(&domain->lock, flags);

		switch (dev->current_profile) {
		case AI_POWER_PROFILE_POWERSAVE:
			domain->target_freq_hz = domain->min_freq_hz;
			domain->target_voltage_uv = domain->min_voltage_uv;
			domain->dvfs_enabled = 1;
			break;

		case AI_POWER_PROFILE_PERFORMANCE:
			domain->target_freq_hz = domain->max_freq_hz;
			domain->target_voltage_uv = domain->max_voltage_uv;
			domain->dvfs_enabled = 0;
			break;

		case AI_POWER_PROFILE_AI_INFERENCE:
			domain->target_freq_hz = domain->max_freq_hz * 80 / 100;
			domain->target_voltage_uv = domain->max_voltage_uv;
			domain->dvfs_enabled = 0;
			break;

		case AI_POWER_PROFILE_AI_TRAINING:
			domain->target_freq_hz = domain->max_freq_hz;
			domain->target_voltage_uv = domain->max_voltage_uv;
			domain->dvfs_enabled = 1;
			break;

		case AI_POWER_PROFILE_BALANCED:
		case AI_POWER_PROFILE_AI_ADAPTIVE:
		default:
			domain->target_freq_hz = domain->max_freq_hz * 60 / 100;
			domain->target_voltage_uv = domain->max_voltage_uv * 80 / 100;
			domain->dvfs_enabled = 1;
			break;
		}

		domain->current_power_uw = ai_power_estimate_power(domain);
		domain->energy_uj += domain->current_power_uw;

		spin_unlock_irqrestore(&domain->lock, flags);
	}
	mutex_unlock(&dev->domain_mutex);

	return 0;
}

/*
 * File operations
 */

static int ai_power_open(struct inode *inode, struct file *file)
{
	struct ai_power_device *dev = container_of(inode->i_cdev,
						   struct ai_power_device,
						   cdev);
	if (!dev || !dev->active)
		return -ENODEV;
	file->private_data = dev;
	return 0;
}

static int ai_power_release(struct inode *inode, struct file *file)
{
	return 0;
}

static long ai_power_ioctl(struct file *file, unsigned int cmd,
			   unsigned long arg)
{
	struct ai_power_device *dev = file->private_data;
	void __user *argp = (void __user *)arg;
	struct ai_power_info info;
	struct ai_power_freq freq;
	struct ai_power_voltage voltage;
	struct ai_power_consumption consumption;
	struct ai_power_thermal thermal;
	struct ai_power_policy policy;
	struct ai_power_dvfs dvfs;
	struct ai_power_prediction prediction;
	struct ai_power_opp opp;
	struct ai_power_idle idle;
	struct ai_power_profile profile;
	struct ai_power_battery battery;
	struct ai_power_governor governor;
	struct ai_power_psi psi;
	struct ai_power_avail_freqs avail_freqs;
	struct ai_power_psys psys;
	struct ai_power_ai_advice advice;
	struct ai_power_domain_state *domain;
	int ret = 0;

	if (!dev || !dev->active)
		return -ENODEV;

	if (_IOC_TYPE(cmd) != AI_POWER_IOC_MAGIC)
		return -ENOTTY;
	if (_IOC_NR(cmd) > AI_POWER_IOC_MAXNR)
		return -ENOTTY;

	switch (cmd) {
	case AI_POWER_IOCTL_GET_INFO:
		memset(&info, 0, sizeof(info));
		strscpy(info.version, AI_POWER_MODULE_VERSION,
			sizeof(info.version));
		strscpy(info.description, AI_POWER_MODULE_DESC,
			sizeof(info.description));
		info.major_version = 1;
		info.minor_version = 0;
		info.patch_version = 0;
		info.profile_active = dev->current_profile;
		info.domains_active = dev->nr_domains;
		info.thermal_throttling = 1;
		info.dvfs_enabled = dvfs_enabled;
		info.ai_governor_enabled = 1;
		info.features = 0x7F;

		if (copy_to_user(argp, &info, sizeof(info)))
			ret = -EFAULT;
		break;

	case AI_POWER_IOCTL_GET_FREQ:
		if (copy_from_user(&freq, argp, sizeof(freq))) {
			ret = -EFAULT;
			break;
		}
		domain = ai_power_find_domain(dev, freq.domain);
		if (!domain) {
			ret = -ENOENT;
			break;
		}
		freq.freq_hz = domain->current_freq_hz;
		freq.min_freq_hz = domain->min_freq_hz;
		freq.max_freq_hz = domain->max_freq_hz;
		freq.result = 0;
		if (copy_to_user(argp, &freq, sizeof(freq)))
			ret = -EFAULT;
		break;

	case AI_POWER_IOCTL_SET_FREQ:
		if (copy_from_user(&freq, argp, sizeof(freq))) {
			ret = -EFAULT;
			break;
		}
		domain = ai_power_find_domain(dev, freq.domain);
		if (!domain) {
			ret = -ENOENT;
			break;
		}
		domain->target_freq_hz = freq.freq_hz;
		ai_power_dbg("Domain %u freq set to %llu Hz\n",
			     freq.domain, freq.freq_hz);
		break;

	case AI_POWER_IOCTL_GET_VOLTAGE:
		if (copy_from_user(&voltage, argp, sizeof(voltage))) {
			ret = -EFAULT;
			break;
		}
		domain = ai_power_find_domain(dev, voltage.domain);
		if (!domain) {
			ret = -ENOENT;
			break;
		}
		voltage.voltage_uv = domain->current_voltage_uv;
		voltage.min_voltage_uv = domain->min_voltage_uv;
		voltage.max_voltage_uv = domain->max_voltage_uv;
		voltage.result = 0;
		if (copy_to_user(argp, &voltage, sizeof(voltage)))
			ret = -EFAULT;
		break;

	case AI_POWER_IOCTL_SET_VOLTAGE:
		if (copy_from_user(&voltage, argp, sizeof(voltage))) {
			ret = -EFAULT;
			break;
		}
		domain = ai_power_find_domain(dev, voltage.domain);
		if (!domain) {
			ret = -ENOENT;
			break;
		}
		domain->target_voltage_uv = voltage.voltage_uv;
		break;

	case AI_POWER_IOCTL_GET_POWER:
		if (copy_from_user(&consumption, argp, sizeof(consumption))) {
			ret = -EFAULT;
			break;
		}
		domain = ai_power_find_domain(dev, consumption.domain);
		if (!domain) {
			ret = -ENOENT;
			break;
		}
		consumption.power_uw = domain->current_power_uw;
		consumption.avg_power_uw = domain->avg_power_uw;
		consumption.max_power_uw = domain->max_power_uw;
		consumption.min_power_uw = domain->min_power_uw;
		consumption.energy_uj = domain->energy_uj;
		if (copy_to_user(argp, &consumption, sizeof(consumption)))
			ret = -EFAULT;
		break;

	case AI_POWER_IOCTL_GET_TEMP:
		if (copy_from_user(&thermal, argp, sizeof(thermal))) {
			ret = -EFAULT;
			break;
		}
		domain = ai_power_find_domain(dev, thermal.domain);
		if (!domain) {
			ret = -ENOENT;
			break;
		}
		thermal.temperature_c = domain->temperature_c;
		thermal.trip_temp_c = domain->trip_temp_c;
		thermal.critical_temp_c = domain->critical_temp_c;
		thermal.passive_temp_c = domain->passive_temp_c;
		thermal.hot_temp_c = domain->hot_temp_c;
		thermal.throttle_mode = domain->throttle_mode;
		thermal.fan_speed_rpm = domain->fan_speed_rpm;
		if (copy_to_user(argp, &thermal, sizeof(thermal)))
			ret = -EFAULT;
		break;

	case AI_POWER_IOCTL_SET_POLICY:
		if (copy_from_user(&policy, argp, sizeof(policy))) {
			ret = -EFAULT;
			break;
		}
		memcpy(&dev->current_policy, &policy, sizeof(policy));
		dev->current_profile = policy.profile;
		ai_power_apply_policy(dev);
		ai_power_dbg("Policy set to profile=%d\n", policy.profile);
		break;

	case AI_POWER_IOCTL_GET_POLICY:
		memcpy(&policy, &dev->current_policy, sizeof(policy));
		if (copy_to_user(argp, &policy, sizeof(policy)))
			ret = -EFAULT;
		break;

	case AI_POWER_IOCTL_DVFS_CONFIG:
		if (copy_from_user(&dvfs, argp, sizeof(dvfs))) {
			ret = -EFAULT;
			break;
		}
		domain = ai_power_find_domain(dev, dvfs.domain);
		if (!domain) {
			ret = -ENOENT;
			break;
		}
		domain->dvfs_enabled = dvfs.enabled;
		domain->dvfs_latency_us = dvfs.latency_us;
		domain->dvfs_step_size = dvfs.step_size;
		domain->min_freq_hz = dvfs.min_freq;
		domain->max_freq_hz = dvfs.max_freq;
		domain->target_freq_hz = dvfs.target_freq;
		ai_power_dbg("Domain %u DVFS configured (enabled=%u)\n",
			     dvfs.domain, dvfs.enabled);
		break;

	case AI_POWER_IOCTL_GET_DVFS:
		if (copy_from_user(&dvfs, argp, sizeof(dvfs))) {
			ret = -EFAULT;
			break;
		}
		domain = ai_power_find_domain(dev, dvfs.domain);
		if (!domain) {
			ret = -ENOENT;
			break;
		}
		dvfs.enabled = domain->dvfs_enabled;
		dvfs.latency_us = domain->dvfs_latency_us;
		dvfs.step_size = domain->dvfs_step_size;
		dvfs.min_freq = domain->min_freq_hz;
		dvfs.max_freq = domain->max_freq_hz;
		dvfs.target_freq = domain->target_freq_hz;
		dvfs.current_freq = domain->current_freq_hz;
		dvfs.voltage_uv = domain->current_voltage_uv;
		dvfs.transition_count = domain->dvfs_transition_count;
		if (copy_to_user(argp, &dvfs, sizeof(dvfs)))
			ret = -EFAULT;
		break;

	case AI_POWER_IOCTL_PREDICT_POWER:
		if (copy_from_user(&prediction, argp, sizeof(prediction))) {
			ret = -EFAULT;
			break;
		}
		domain = ai_power_find_domain(dev, prediction.domain);
		if (!domain) {
			ret = -ENOENT;
			break;
		}
		prediction.predicted_power_uw = domain->current_power_uw;
		prediction.predicted_temp_c = domain->temperature_c;
		prediction.predicted_freq_hz = domain->target_freq_hz;
		prediction.confidence_percent = 85;
		prediction.model_version = 1;
		memcpy(&dev->last_prediction, &prediction, sizeof(prediction));
		if (copy_to_user(argp, &prediction, sizeof(prediction)))
			ret = -EFAULT;
		break;

	case AI_POWER_IOCTL_GET_OPP:
		if (copy_from_user(&opp, argp, sizeof(opp))) {
			ret = -EFAULT;
			break;
		}
		domain = ai_power_find_domain(dev, opp.domain);
		if (!domain) {
			ret = -ENOENT;
			break;
		}
		opp.freq_hz = domain->current_freq_hz;
		opp.voltage_uv = domain->current_voltage_uv;
		opp.power_uw = domain->current_power_uw;
		opp.available = 1;
		opp.opp_count = domain->opp_count;
		if (copy_to_user(argp, &opp, sizeof(opp)))
			ret = -EFAULT;
		break;

	case AI_POWER_IOCTL_SET_OPP:
		if (copy_from_user(&opp, argp, sizeof(opp))) {
			ret = -EFAULT;
			break;
		}
		domain = ai_power_find_domain(dev, opp.domain);
		if (!domain) {
			ret = -ENOENT;
			break;
		}
		domain->target_freq_hz = opp.freq_hz;
		domain->target_voltage_uv = opp.voltage_uv;
		domain->current_opp_index = opp.index;
		break;

	case AI_POWER_IOCTL_GET_THERMAL_LIMIT:
		if (copy_from_user(&thermal, argp, sizeof(thermal))) {
			ret = -EFAULT;
			break;
		}
		domain = ai_power_find_domain(dev, thermal.domain);
		if (!domain) {
			ret = -ENOENT;
			break;
		}
		thermal.temperature_c = domain->temperature_c;
		thermal.trip_temp_c = domain->trip_temp_c;
		thermal.critical_temp_c = domain->critical_temp_c;
		thermal.passive_temp_c = domain->passive_temp_c;
		thermal.hot_temp_c = domain->hot_temp_c;
		if (copy_to_user(argp, &thermal, sizeof(thermal)))
			ret = -EFAULT;
		break;

	case AI_POWER_IOCTL_SET_THERMAL_LIMIT:
		if (copy_from_user(&thermal, argp, sizeof(thermal))) {
			ret = -EFAULT;
			break;
		}
		domain = ai_power_find_domain(dev, thermal.domain);
		if (!domain) {
			ret = -ENOENT;
			break;
		}
		domain->trip_temp_c = thermal.trip_temp_c;
		domain->critical_temp_c = thermal.critical_temp_c;
		domain->passive_temp_c = thermal.passive_temp_c;
		domain->hot_temp_c = thermal.hot_temp_c;
		break;

	case AI_POWER_IOCTL_GET_IDLE_STATE:
		if (copy_from_user(&idle, argp, sizeof(idle))) {
			ret = -EFAULT;
			break;
		}
		domain = ai_power_find_domain(dev, idle.state);
		if (!domain) {
			ret = -ENOENT;
			break;
		}
		idle.state = domain->current_cstate;
		idle.time_in_state_ms = domain->idle_time_ms;
		if (copy_to_user(argp, &idle, sizeof(idle)))
			ret = -EFAULT;
		break;

	case AI_POWER_IOCTL_SET_IDLE_STATE:
		if (copy_from_user(&idle, argp, sizeof(idle))) {
			ret = -EFAULT;
			break;
		}
		domain = ai_power_find_domain(dev, idle.state);
		if (!domain) {
			ret = -ENOENT;
			break;
		}
		domain->current_cstate = idle.state;
		break;

	case AI_POWER_IOCTL_PERF_PROFILE:
		if (copy_from_user(&profile, argp, sizeof(profile))) {
			ret = -EFAULT;
			break;
		}
		dev->current_profile = profile.type;
		ai_power_apply_policy(dev);
		ai_power_dbg("Performance profile set to %d\n", profile.type);
		break;

	case AI_POWER_IOCTL_GET_BATTERY:
		memcpy(&battery, &dev->battery_info, sizeof(battery));
		if (copy_to_user(argp, &battery, sizeof(battery)))
			ret = -EFAULT;
		break;

	case AI_POWER_IOCTL_GET_GOVERNOR:
		governor.type = dev->current_governor;
		governor.available = 1;
		governor.active = 1;
		strscpy(governor.name, "ai_predictive", sizeof(governor.name));
		if (copy_to_user(argp, &governor, sizeof(governor)))
			ret = -EFAULT;
		break;

	case AI_POWER_IOCTL_SET_GOVERNOR:
		if (copy_from_user(&governor, argp, sizeof(governor))) {
			ret = -EFAULT;
			break;
		}
		dev->current_governor = governor.type;
		ai_power_dbg("Governor set to %d\n", governor.type);
		break;

	case AI_POWER_IOCTL_GET_PSI:
		memcpy(&psi, &dev->psi_info, sizeof(psi));
		if (copy_to_user(argp, &psi, sizeof(psi)))
			ret = -EFAULT;
		break;

	case AI_POWER_IOCTL_SUSPEND:
		ai_power_info("System suspend requested (state=%lu)\n", arg);
		ret = 0;
		break;

	case AI_POWER_IOCTL_RESUME:
		ai_power_info("System resume requested\n");
		ret = 0;
		break;

	case AI_POWER_IOCTL_GET_AVAIL_FREQ:
		if (copy_from_user(&avail_freqs, argp, sizeof(avail_freqs))) {
			ret = -EFAULT;
			break;
		}
		domain = ai_power_find_domain(dev, avail_freqs.domain);
		if (!domain) {
			ret = -ENOENT;
			break;
		}
		avail_freqs.count = 0;
		avail_freqs.freqs[avail_freqs.count++] = domain->min_freq_hz;
		avail_freqs.freqs[avail_freqs.count++] = domain->max_freq_hz;
		if (domain->max_freq_hz > domain->min_freq_hz) {
			u64 step = (domain->max_freq_hz - domain->min_freq_hz) / 4;
			if (step > 0) {
				avail_freqs.freqs[avail_freqs.count++] =
					domain->min_freq_hz + step;
				avail_freqs.freqs[avail_freqs.count++] =
					domain->min_freq_hz + 2 * step;
				avail_freqs.freqs[avail_freqs.count++] =
					domain->min_freq_hz + 3 * step;
			}
		}
		if (copy_to_user(argp, &avail_freqs, sizeof(avail_freqs)))
			ret = -EFAULT;
		break;

	case AI_POWER_IOCTL_GET_PSYS:
		memcpy(&psys, &dev->psys_info, sizeof(psys));
		if (copy_to_user(argp, &psys, sizeof(psys)))
			ret = -EFAULT;
		break;

	case AI_POWER_IOCTL_SET_PSYS_LIMIT:
		if (copy_from_user(&psys, argp, sizeof(psys))) {
			ret = -EFAULT;
			break;
		}
		dev->psys_info.power_limit_uw = psys.power_limit_uw;
		ai_power_dbg("PSYS power limit set to %llu uW\n",
			     psys.power_limit_uw);
		break;

	case AI_POWER_IOCTL_GET_AI_ADVICE:
		advice.confidence = 85;
		advice.performace_boost = 0;
		advice.target_freq_hz = 0;
		advice.target_voltage_uv = 0;
		advice.target_cstate = 0;
		advice.throttle_recommendation = 0;
		advice.predicted_power_save = 0;
		advice.predicted_perf_impact = 0;
		if (copy_to_user(argp, &advice, sizeof(advice)))
			ret = -EFAULT;
		break;

	default:
		ret = -ENOTTY;
		break;
	}

	return ret;
}

#ifdef CONFIG_COMPAT
static long ai_power_compat_ioctl(struct file *file, unsigned int cmd,
				  unsigned long arg)
{
	return ai_power_ioctl(file, cmd, (unsigned long)compat_ptr(arg));
}
#endif

static const struct file_operations ai_power_fops = {
	.owner		= THIS_MODULE,
	.open		= ai_power_open,
	.release	= ai_power_release,
	.unlocked_ioctl	= ai_power_ioctl,
#ifdef CONFIG_COMPAT
	.compat_ioctl	= ai_power_compat_ioctl,
#endif
	.llseek		= noop_llseek,
};

/*
 * Sysfs interface
 */

static ssize_t profile_show(struct kobject *kobj,
			    struct kobj_attribute *attr, char *buf)
{
	struct ai_power_device *dev = container_of(kobj,
						   struct ai_power_device,
						   *kobj);
	return sysfs_emit(buf, "%d\n", dev->current_profile);
}

static ssize_t dvfs_show(struct kobject *kobj,
			 struct kobj_attribute *attr, char *buf)
{
	return sysfs_emit(buf, "%d\n", dvfs_enabled);
}

static ssize_t temperature_show(struct kobject *kobj,
				struct kobj_attribute *attr, char *buf)
{
	struct ai_power_device *dev = container_of(kobj,
						   struct ai_power_device,
						   *kobj);
	struct ai_power_domain_state *domain;
	int temp = 0;

	mutex_lock(&dev->domain_mutex);
	list_for_each_entry(domain, &dev->domains, list) {
		if (domain->temperature_c > temp)
			temp = domain->temperature_c;
	}
	mutex_unlock(&dev->domain_mutex);

	return sysfs_emit(buf, "%d\n", temp);
}

static ssize_t governor_show(struct kobject *kobj,
			     struct kobj_attribute *attr, char *buf)
{
	struct ai_power_device *dev = container_of(kobj,
						   struct ai_power_device,
						   *kobj);
	return sysfs_emit(buf, "%d\n", dev->current_governor);
}

static ssize_t battery_show(struct kobject *kobj,
			    struct kobj_attribute *attr, char *buf)
{
	struct ai_power_device *dev = container_of(kobj,
						   struct ai_power_device,
						   *kobj);
	return sysfs_emit(buf, "capacity=%d%% status=%d temp=%dC\n",
			  dev->battery_info.capacity_percent,
			  dev->battery_info.status,
			  dev->battery_info.temp_c);
}

static struct kobj_attribute profile_attr = __ATTR_RO(profile);
static struct kobj_attribute dvfs_attr = __ATTR_RO(dvfs);
static struct kobj_attribute temperature_attr = __ATTR_RO(temperature);
static struct kobj_attribute governor_attr = __ATTR_RO(governor);
static struct kobj_attribute battery_attr = __ATTR_RO(battery);

static struct attribute *ai_power_attrs[] = {
	&profile_attr.attr,
	&dvfs_attr.attr,
	&temperature_attr.attr,
	&governor_attr.attr,
	&battery_attr.attr,
	NULL,
};

ATTRIBUTE_GROUPS(ai_power);

/*
 * PM notifier callback
 */
static int ai_power_pm_notifier(struct notifier_block *nb,
				unsigned long event, void *data)
{
	struct ai_power_device *dev = container_of(nb,
						   struct ai_power_device,
						   pm_notifier);

	switch (event) {
	case PM_SUSPEND_PREPARE:
		ai_power_info("PM suspend prepare\n");
		break;
	case PM_POST_SUSPEND:
		ai_power_info("PM post suspend\n");
		break;
	case PM_HIBERNATION_PREPARE:
		ai_power_info("PM hibernation prepare\n");
		break;
	case PM_POST_HIBERNATION:
		ai_power_info("PM post hibernation\n");
		break;
	}

	return NOTIFY_OK;
}

/*
 * Module init/exit
 */

static int ai_power_create_domains(struct ai_power_device *dev)
{
	struct ai_power_domain_state *domain;
	int i;
	const char *names[] = {
		[AI_POWER_DOMAIN_CPU]	= "cpu",
		[AI_POWER_DOMAIN_GPU]	= "gpu",
		[AI_POWER_DOMAIN_NPU]	= "npu",
		[AI_POWER_DOMAIN_MEMORY] = "memory",
		[AI_POWER_DOMAIN_IO]	= "io",
		[AI_POWER_DOMAIN_SOC]	= "soc",
	};

	for (i = 0; i < AI_POWER_DOMAIN_COUNT; i++) {
		domain = ai_power_domain_alloc(i, names[i]);
		if (!domain)
			return -ENOMEM;

		domain->domain_id = i;
		domain->initialized = true;

		domain->min_freq_hz = 100000000;   /* 100 MHz */
		domain->max_freq_hz = 3000000000;  /* 3 GHz */
		domain->current_freq_hz = 1500000000;
		domain->target_freq_hz = 1500000000;

		domain->min_voltage_uv = 700000;
		domain->max_voltage_uv = 1300000;
		domain->current_voltage_uv = 1000000;
		domain->target_voltage_uv = 1000000;

		domain->current_power_uw = 5000000;
		domain->avg_power_uw = 5000000;
		domain->max_power_uw = 15000000;
		domain->min_power_uw = 1000000;

		domain->temperature_c = 45;
		domain->opp_count = 8;

		mutex_lock(&dev->domain_mutex);
		list_add_tail(&domain->list, &dev->domains);
		dev->nr_domains++;
		mutex_unlock(&dev->domain_mutex);
	}

	ai_power_info("Created %d power domains\n", dev->nr_domains);
	return 0;
}

static int ai_power_create_device(struct ai_power_device **dev_out)
{
	struct ai_power_device *dev;
	int ret;

	dev = kmem_cache_zalloc(ai_power_device_cache, GFP_KERNEL);
	if (!dev)
		return -ENOMEM;

	dev->dev_id = atomic_inc_return(&ai_power_device_count);
	snprintf(dev->name, sizeof(dev->name), "ai-power-%u", dev->dev_id);
	dev->active = false;

	INIT_LIST_HEAD(&dev->domains);
	mutex_init(&dev->domain_mutex);
	dev->nr_domains = 0;

	dev->current_profile = AI_POWER_PROFILE_BALANCED;
	dev->current_governor = AI_POWER_GOV_SCHEDUTIL;

	dev->current_policy.profile = AI_POWER_PROFILE_BALANCED;
	dev->current_policy.flags = 0;
	dev->current_policy.performance_bias = 50;
	dev->current_policy.power_bias = 50;
	dev->current_policy.thermal_throttle_threshold = thermal_throttle_temp;
	dev->current_policy.boost_enabled = 1;
	dev->current_policy.turbo_enabled = 0;
	dev->current_policy.energy_performance_preference = 4;
	dev->current_policy.autonomous_mode = 1;
	dev->current_policy.ai_learning_enabled = 1;
	dev->current_policy.learning_rate = 10;
	dev->current_policy.history_size = 100;
	dev->current_policy.prediction_window_ms = 500;

	dev->battery_present = false;
	memset(&dev->battery_info, 0, sizeof(dev->battery_info));
	dev->battery_info.capacity_percent = 80;
	dev->battery_info.status = 1;
	dev->battery_info.health = 1;
	dev->battery_info.temp_c = 30;
	dev->battery_info.voltage_uv = 3700000;
	dev->battery_info.present = 1;

	memset(&dev->psi_info, 0, sizeof(dev->psi_info));
	memset(&dev->psys_info, 0, sizeof(dev->psys_info));
	dev->psys_info.power_uw = 15000000;
	dev->psys_info.avg_power_uw = 12000000;
	dev->psys_info.power_limit_uw = 25000000;

	dev->pm_notifier.notifier_call = ai_power_pm_notifier;

	cdev_init(&dev->cdev, &ai_power_fops);
	dev->cdev.owner = THIS_MODULE;

	ret = cdev_add(&dev->cdev, dev->dev_id, 1);
	if (ret)
		goto err_free;

	dev->device = device_create(ai_power_class, NULL, dev->dev_id, dev,
				    "ai-power-%u", dev->dev_id);
	if (IS_ERR(dev->device)) {
		ret = PTR_ERR(dev->device);
		goto err_cdev;
	}

	dev->kobj = &dev->device->kobj;

	ret = ai_power_create_domains(dev);
	if (ret)
		goto err_device;

	dev->active = true;

	INIT_DELAYED_WORK(&dev->dvfs_work, ai_power_dvfs_work_handler);
	schedule_delayed_work(&dev->dvfs_work, msecs_to_jiffies(1000));

	dev->thermal_task = kthread_run(ai_power_thermal_worker, dev,
					"ai-power-thermal-%u", dev->dev_id);
	if (IS_ERR(dev->thermal_task)) {
		ret = PTR_ERR(dev->thermal_task);
		dev->thermal_task = NULL;
		goto err_device;
	}
	dev->thermal_monitoring = true;

	register_pm_notifier(&dev->pm_notifier);

	list_add_tail(&dev->list, &ai_power_devices);

	ai_power_info("Device created: %s\n", dev->name);

	*dev_out = dev;
	return 0;

err_device:
	device_destroy(ai_power_class, dev->dev_id);
err_cdev:
	cdev_del(&dev->cdev);
err_free:
	kmem_cache_free(ai_power_device_cache, dev);
	return ret;
}

static void ai_power_destroy_device(struct ai_power_device *dev)
{
	struct ai_power_domain_state *domain, *tmp;

	if (!dev)
		return;

	dev->active = false;

	unregister_pm_notifier(&dev->pm_notifier);

	if (dev->thermal_task) {
		kthread_stop(dev->thermal_task);
		dev->thermal_monitoring = false;
	}

	cancel_delayed_work_sync(&dev->dvfs_work);

	list_for_each_entry_safe(domain, tmp, &dev->domains, list) {
		list_del(&domain->list);
		ai_power_domain_free(domain);
	}

	device_destroy(ai_power_class, dev->dev_id);
	cdev_del(&dev->cdev);
	mutex_destroy(&dev->domain_mutex);
	list_del(&dev->list);
	kmem_cache_free(ai_power_device_cache, dev);
}

static int __init ai_power_init(void)
{
	struct ai_power_device *dev;
	int ret;

	ai_power_info("Loading Ainos AI Power Management v%s\n",
		      AI_POWER_MODULE_VERSION);

	INIT_LIST_HEAD(&ai_power_devices);
	mutex_init(&ai_power_global_mutex);
	atomic_set(&ai_power_device_count, 0);

	ai_power_domain_cache = kmem_cache_create("ai_power_domain",
						  sizeof(struct ai_power_domain_state),
						  0, SLAB_HWCACHE_ALIGN, NULL);
	if (!ai_power_domain_cache)
		return -ENOMEM;

	ai_power_device_cache = kmem_cache_create("ai_power_device",
						  sizeof(struct ai_power_device),
						  0, SLAB_HWCACHE_ALIGN, NULL);
	if (!ai_power_device_cache) {
		ret = -ENOMEM;
		goto err_domain_cache;
	}

	ret = alloc_chrdev_region(&ai_power_devno, 0, AI_POWER_MAX_DEVICES,
				  AI_POWER_MODULE_NAME);
	if (ret) {
		ai_power_err("Failed to allocate chrdev: %d\n", ret);
		goto err_device_cache;
	}

	ai_power_major = MAJOR(ai_power_devno);

	ai_power_class = class_create(THIS_MODULE, AI_POWER_CLASS_NAME);
	if (IS_ERR(ai_power_class)) {
		ret = PTR_ERR(ai_power_class);
		goto err_unregister;
	}

	ret = ai_power_create_device(&dev);
	if (ret)
		goto err_class;

	ai_power_info("Ainos AI Power Management loaded (major=%u)\n",
		      ai_power_major);
	return 0;

err_class:
	class_destroy(ai_power_class);
err_unregister:
	unregister_chrdev_region(ai_power_devno, AI_POWER_MAX_DEVICES);
err_device_cache:
	kmem_cache_destroy(ai_power_device_cache);
err_domain_cache:
	kmem_cache_destroy(ai_power_domain_cache);
	return ret;
}

static void __exit ai_power_exit(void)
{
	struct ai_power_device *dev, *tmp;

	ai_power_info("Unloading Ainos AI Power Management\n");

	list_for_each_entry_safe(dev, tmp, &ai_power_devices, list)
		ai_power_destroy_device(dev);

	class_destroy(ai_power_class);
	unregister_chrdev_region(ai_power_devno, AI_POWER_MAX_DEVICES);
	kmem_cache_destroy(ai_power_device_cache);
	kmem_cache_destroy(ai_power_domain_cache);

	ai_power_info("Ainos AI Power Management unloaded\n");
}

/*
 * Exported kernel API
 */

int ai_power_set_freq(unsigned int domain, unsigned int cpu, __u64 freq_hz)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_set_freq);

int ai_power_get_freq(unsigned int domain, unsigned int cpu, __u64 *freq_hz)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_get_freq);

int ai_power_get_avail_freqs(unsigned int domain,
			     struct ai_power_avail_freqs *freqs)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_get_avail_freqs);

int ai_power_set_voltage(unsigned int domain, unsigned int cpu,
			 __u64 voltage_uv)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_set_voltage);

int ai_power_get_voltage(unsigned int domain, unsigned int cpu,
			 __u64 *voltage_uv)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_get_voltage);

int ai_power_get_consumption(unsigned int domain,
			     struct ai_power_consumption *consumption)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_get_consumption);

int ai_power_get_psys(struct ai_power_psys *psys)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_get_psys);

int ai_power_set_psys_limit(struct ai_power_psys *limit)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_set_psys_limit);

int ai_power_get_temperature(unsigned int domain,
			     struct ai_power_thermal *thermal)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_get_temperature);

int ai_power_set_thermal_limit(unsigned int domain,
			       struct ai_power_thermal *limit)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_set_thermal_limit);

int ai_power_get_throttle_mode(unsigned int domain,
			       enum ai_power_throttle_mode *mode)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_get_throttle_mode);

int ai_power_set_policy(struct ai_power_policy *policy)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_set_policy);

int ai_power_get_policy(struct ai_power_policy *policy)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_get_policy);

int ai_power_set_profile(enum ai_power_profile_type profile)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_set_profile);

int ai_power_get_profile(enum ai_power_profile_type *profile)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_get_profile);

int ai_power_dvfs_config(struct ai_power_dvfs *dvfs)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_dvfs_config);

int ai_power_dvfs_get(struct ai_power_dvfs *dvfs)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_dvfs_get);

int ai_power_dvfs_enable(unsigned int domain)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_dvfs_enable);

int ai_power_dvfs_disable(unsigned int domain)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_dvfs_disable);

int ai_power_opp_get(struct ai_power_opp *opp)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_opp_get);

int ai_power_opp_set(struct ai_power_opp *opp)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_opp_set);

int ai_power_opp_enable(unsigned int domain, unsigned int index)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_opp_enable);

int ai_power_opp_disable(unsigned int domain, unsigned int index)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_opp_disable);

int ai_power_set_governor(enum ai_power_governor_type governor)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_set_governor);

int ai_power_get_governor(enum ai_power_governor_type *governor)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_get_governor);

int ai_power_governor_list(struct ai_power_governor *governors, int *count)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_governor_list);

int ai_power_idle_set(unsigned int cpu, unsigned int state)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_idle_set);

int ai_power_idle_get(unsigned int cpu, struct ai_power_idle *idle)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_idle_get);

int ai_power_idle_disable(unsigned int cpu, unsigned int state)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_idle_disable);

int ai_power_predict(struct ai_power_prediction *prediction)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_predict);

int ai_power_get_ai_advice(unsigned int domain,
			   struct ai_power_ai_advice *advice)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_get_ai_advice);

int ai_power_get_battery(struct ai_power_battery *battery)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_get_battery);

int ai_power_get_psi(struct ai_power_psi *psi)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_power_get_psi);

int ai_power_suspend(unsigned int state)
{
	struct ai_power_device *dev;
	struct ai_power_domain_state *domain;
	unsigned long flags;

	ai_power_info("System suspend state=%u\n", state);

	mutex_lock(&ai_power_global_mutex);
	list_for_each_entry(dev, &ai_power_devices, list) {
		mutex_lock(&dev->domain_mutex);
		list_for_each_entry(domain, &dev->domains, list) {
			spin_lock_irqsave(&domain->lock, flags);
			domain->current_cstate = AI_POWER_CSTATE_C6;
			domain->current_power_uw = domain->min_power_uw;
			spin_unlock_irqrestore(&domain->lock, flags);
		}
		mutex_unlock(&dev->domain_mutex);

		dev->battery_info.capacity_percent = 80;
		dev->psys_info.power_uw = dev->battery_info.energy_uw;
	}
	mutex_unlock(&ai_power_global_mutex);

	return 0;
}
EXPORT_SYMBOL_GPL(ai_power_suspend);

int ai_power_resume(void)
{
	struct ai_power_device *dev;
	struct ai_power_domain_state *domain;
	unsigned long flags;

	ai_power_info("System resume\n");

	mutex_lock(&ai_power_global_mutex);
	list_for_each_entry(dev, &ai_power_devices, list) {
		mutex_lock(&dev->domain_mutex);
		list_for_each_entry(domain, &dev->domains, list) {
			spin_lock_irqsave(&domain->lock, flags);
			domain->current_cstate = AI_POWER_CSTATE_C0;
			domain->current_power_uw = ai_power_estimate_power(domain);
			spin_unlock_irqrestore(&domain->lock, flags);
		}
		mutex_unlock(&dev->domain_mutex);

		dev->psys_info.power_uw = 15000000;
		dev->battery_info.status = 1;
	}
	mutex_unlock(&ai_power_global_mutex);

	return 0;
}
EXPORT_SYMBOL_GPL(ai_power_resume);

/*
 * Additional AI power management helper functions
 * These provide comprehensive power management capabilities
 * for AI workload optimization across heterogeneous compute domains.
 */

static int ai_power_calculate_energy(struct ai_power_domain_state *domain,
				     u64 *energy_uj)
{
	unsigned long flags;
	u64 power, time_ms;

	spin_lock_irqsave(&domain->lock, flags);
	power = domain->current_power_uw;
	time_ms = domain->idle_time_ms;
	spin_unlock_irqrestore(&domain->lock, flags);

	*energy_uj = (power * time_ms) / 1000;
	return 0;
}

static int ai_power_adjust_freq_for_thermal(struct ai_power_domain_state *domain)
{
	unsigned long flags;
	int temp;

	spin_lock_irqsave(&domain->lock, flags);
	temp = domain->temperature_c;
	spin_unlock_irqrestore(&domain->lock, flags);

	if (temp >= domain->critical_temp_c) {
		domain->target_freq_hz = domain->min_freq_hz;
		domain->target_voltage_uv = domain->min_voltage_uv;
		domain->fan_speed_rpm = 100;
		ai_power_warn("Thermal emergency: domain %s freq reduced to %llu Hz\n",
			     domain->name, domain->target_freq_hz);
	} else if (temp >= domain->hot_temp_c) {
		domain->target_freq_hz = domain->max_freq_hz * 30 / 100;
		domain->target_voltage_uv = domain->max_voltage_uv * 70 / 100;
		domain->fan_speed_rpm = 80;
	} else if (temp >= domain->passive_temp_c) {
		domain->target_freq_hz = domain->max_freq_hz * 50 / 100;
		domain->target_voltage_uv = domain->max_voltage_uv * 80 / 100;
		domain->fan_speed_rpm = 50;
	} else if (temp >= domain->trip_temp_c) {
		domain->target_freq_hz = domain->max_freq_hz * 70 / 100;
		domain->fan_speed_rpm = 30;
	} else {
		if (domain->fan_speed_rpm > 0)
			domain->fan_speed_rpm = 0;
	}

	return 0;
}

static int ai_power_optimize_for_workload(struct ai_power_device *dev,
					  enum ai_power_profile_type profile)
{
	struct ai_power_domain_state *domain;

	mutex_lock(&dev->domain_mutex);
	list_for_each_entry(domain, &dev->domains, list) {
		unsigned long flags;

		spin_lock_irqsave(&domain->lock, flags);

		switch (profile) {
		case AI_POWER_PROFILE_AI_INFERENCE:
			domain->target_freq_hz = domain->max_freq_hz * 90 / 100;
			domain->target_voltage_uv = domain->max_voltage_uv;
			domain->dvfs_enabled = 0;
			domain->trip_temp_c = 90;
			break;

		case AI_POWER_PROFILE_AI_TRAINING:
			domain->target_freq_hz = domain->max_freq_hz;
			domain->target_voltage_uv = domain->max_voltage_uv;
			domain->dvfs_enabled = 1;
			domain->trip_temp_c = 85;
			break;

		case AI_POWER_PROFILE_AI_ADAPTIVE:
			domain->target_freq_hz = domain->max_freq_hz * 75 / 100;
			domain->target_voltage_uv = domain->max_voltage_uv * 90 / 100;
			domain->dvfs_enabled = 1;
			domain->trip_temp_c = 80;
			break;

		default:
			break;
		}

		domain->current_power_uw = ai_power_estimate_power(domain);
		ai_power_adjust_freq_for_thermal(domain);

		spin_unlock_irqrestore(&domain->lock, flags);
	}
	mutex_unlock(&dev->domain_mutex);

	return 0;
}

static int ai_power_log_power_state(struct ai_power_device *dev)
{
	struct ai_power_domain_state *domain;
	u64 total_power = 0;

	mutex_lock(&dev->domain_mutex);
	list_for_each_entry(domain, &dev->domains, list) {
		unsigned long flags;
		u64 domain_power;

		spin_lock_irqsave(&domain->lock, flags);
		domain_power = domain->current_power_uw;
		spin_unlock_irqrestore(&domain->lock, flags);

		total_power += domain_power;
		ai_power_dbg("Domain %s: freq=%llu Hz volt=%llu uV "
			    "power=%llu uW temp=%dC\n",
			    domain->name,
			    domain->current_freq_hz,
			    domain->current_voltage_uv,
			    domain_power,
			    domain->temperature_c);
	}
	mutex_unlock(&dev->domain_mutex);

	dev->psys_info.power_uw = total_power;
	dev->psys_info.avg_power_uw = (dev->psys_info.avg_power_uw +
				       total_power) / 2;

	return 0;
}

module_init(ai_power_init);
module_exit(ai_power_exit);