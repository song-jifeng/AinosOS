/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Ainos AI Power Management - Header
 *
 * Copyright (C) 2026 Ainos Corporation
 * Authors: Ainos Kernel Team
 *
 * AI power management subsystem providing intelligent frequency
 * scaling, power consumption prediction, DVFS, thermal management,
 * and performance/power trade-off optimization.
 */

#ifndef _AINOS_AI_POWER_H
#define _AINOS_AI_POWER_H

#include <linux/types.h>
#include <linux/pm_opp.h>
#include <linux/cpufreq.h>
#include <linux/cpuidle.h>
#include <linux/thermal.h>
#include <linux/power_supply.h>
#include <linux/pm_qos.h>
#include <linux/pm_wakeirq.h>

/* Module identification */
#define AI_POWER_MODULE_NAME		"ai_power"
#define AI_POWER_MODULE_VERSION		"1.0.0"
#define AI_POWER_MODULE_DESC		"Ainos AI Power Management"
#define AI_POWER_MODULE_AUTHOR		"Ainos Kernel Team"

/* Device interface */
#define AI_POWER_DEVICE_NAME		"ai-power"
#define AI_POWER_CLASS_NAME		"ai-power"
#define AI_POWER_MAX_DEVICES		4

/* IOCTL commands */
#define AI_POWER_IOC_MAGIC		0xB0

#define AI_POWER_IOCTL_GET_INFO		_IOR(AI_POWER_IOC_MAGIC, 0x01, struct ai_power_info)
#define AI_POWER_IOCTL_GET_FREQ		_IOR(AI_POWER_IOC_MAGIC, 0x02, struct ai_power_freq)
#define AI_POWER_IOCTL_SET_FREQ		_IOW(AI_POWER_IOC_MAGIC, 0x03, struct ai_power_freq)
#define AI_POWER_IOCTL_GET_VOLTAGE	_IOR(AI_POWER_IOC_MAGIC, 0x04, struct ai_power_voltage)
#define AI_POWER_IOCTL_SET_VOLTAGE	_IOW(AI_POWER_IOC_MAGIC, 0x05, struct ai_power_voltage)
#define AI_POWER_IOCTL_GET_POWER	_IOR(AI_POWER_IOC_MAGIC, 0x06, struct ai_power_consumption)
#define AI_POWER_IOCTL_GET_TEMP		_IOR(AI_POWER_IOC_MAGIC, 0x07, struct ai_power_thermal)
#define AI_POWER_IOCTL_SET_POLICY	_IOW(AI_POWER_IOC_MAGIC, 0x08, struct ai_power_policy)
#define AI_POWER_IOCTL_GET_POLICY	_IOR(AI_POWER_IOC_MAGIC, 0x09, struct ai_power_policy)
#define AI_POWER_IOCTL_DVFS_CONFIG	_IOW(AI_POWER_IOC_MAGIC, 0x0A, struct ai_power_dvfs)
#define AI_POWER_IOCTL_GET_DVFS		_IOR(AI_POWER_IOC_MAGIC, 0x0B, struct ai_power_dvfs)
#define AI_POWER_IOCTL_PREDICT_POWER	_IOWR(AI_POWER_IOC_MAGIC, 0x0C, struct ai_power_prediction)
#define AI_POWER_IOCTL_GET_OPP		_IOR(AI_POWER_IOC_MAGIC, 0x0D, struct ai_power_opp)
#define AI_POWER_IOCTL_SET_OPP		_IOW(AI_POWER_IOC_MAGIC, 0x0E, struct ai_power_opp)
#define AI_POWER_IOCTL_GET_THERMAL_LIMIT	_IOR(AI_POWER_IOC_MAGIC, 0x0F, struct ai_power_thermal)
#define AI_POWER_IOCTL_SET_THERMAL_LIMIT	_IOW(AI_POWER_IOC_MAGIC, 0x10, struct ai_power_thermal)
#define AI_POWER_IOCTL_GET_IDLE_STATE	_IOR(AI_POWER_IOC_MAGIC, 0x11, struct ai_power_idle)
#define AI_POWER_IOCTL_SET_IDLE_STATE	_IOW(AI_POWER_IOC_MAGIC, 0x12, struct ai_power_idle)
#define AI_POWER_IOCTL_PERF_PROFILE	_IOW(AI_POWER_IOC_MAGIC, 0x13, struct ai_power_profile)
#define AI_POWER_IOCTL_GET_BATTERY	_IOR(AI_POWER_IOC_MAGIC, 0x14, struct ai_power_battery)
#define AI_POWER_IOCTL_GET_GOVERNOR	_IOR(AI_POWER_IOC_MAGIC, 0x15, struct ai_power_governor)
#define AI_POWER_IOCTL_SET_GOVERNOR	_IOW(AI_POWER_IOC_MAGIC, 0x16, struct ai_power_governor)
#define AI_POWER_IOCTL_GET_PSI		_IOR(AI_POWER_IOC_MAGIC, 0x17, struct ai_power_psi)
#define AI_POWER_IOCTL_SUSPEND		_IOW(AI_POWER_IOC_MAGIC, 0x18, __u32)
#define AI_POWER_IOCTL_RESUME		_IO(AI_POWER_IOC_MAGIC, 0x19)
#define AI_POWER_IOCTL_GET_AVAIL_FREQ	_IOR(AI_POWER_IOC_MAGIC, 0x1A, struct ai_power_avail_freqs)
#define AI_POWER_IOCTL_GET_PSYS		_IOR(AI_POWER_IOC_MAGIC, 0x1B, struct ai_power_psys)
#define AI_POWER_IOCTL_SET_PSYS_LIMIT	_IOW(AI_POWER_IOC_MAGIC, 0x1C, struct ai_power_psys)
#define AI_POWER_IOCTL_GET_AI_ADVICE	_IOR(AI_POWER_IOC_MAGIC, 0x1D, struct ai_power_ai_advice)

#define AI_POWER_IOC_MAXNR		29

/* AI power profiles */
enum ai_power_profile_type {
	AI_POWER_PROFILE_POWERSAVE	= 0,	/* Maximum power saving */
	AI_POWER_PROFILE_BALANCED	= 1,	/* Balanced performance/power */
	AI_POWER_PROFILE_PERFORMANCE	= 2,	/* Maximum performance */
	AI_POWER_PROFILE_AI_INFERENCE	= 3,	/* AI inference optimized */
	AI_POWER_PROFILE_AI_TRAINING	= 4,	/* AI training optimized */
	AI_POWER_PROFILE_AI_ADAPTIVE	= 5,	/* AI adaptive power management */
	AI_POWER_PROFILE_CUSTOM		= 6,	/* Custom profile */
};

/* DVFS governors */
enum ai_power_governor_type {
	AI_POWER_GOV_PERFORMANCE	= 0,
	AI_POWER_GOV_POWERSAVE		= 1,
	AI_POWER_GOV_USERSPACE		= 2,
	AI_POWER_GOV_ONDEMAND		= 3,
	AI_POWER_GOV_CONSERVATIVE	= 4,
	AI_POWER_GOV_SCHEDUTIL		= 5,
	AI_POWER_GOV_AI_PREDICTIVE	= 6,
	AI_POWER_GOV_AI_LEARNING	= 7,
};

/* Power states */
enum ai_power_cstate {
	AI_POWER_CSTATE_C0		= 0,	/* Active */
	AI_POWER_CSTATE_C1		= 1,	/* Halt */
	AI_POWER_CSTATE_C2		= 2,	/* Stop-clock */
	AI_POWER_CSTATE_C3		= 3,	/* Sleep */
	AI_POWER_CSTATE_C4		= 4,	/* Deep sleep */
	AI_POWER_CSTATE_C6		= 5,	/* Deep power-down */
	AI_POWER_CSTATE_C7		= 6,	/* Ultra deep power-down */
	AI_POWER_CSTATE_COUNT		= 7,
};

/* Thermal throttling modes */
enum ai_power_throttle_mode {
	AI_POWER_THROTTLE_NONE		= 0,
	AI_POWER_THROTTLE_PASSIVE	= 1,	/* Passive cooling */
	AI_POWER_THROTTLE_ACTIVE	= 2,	/* Active cooling (fan) */
	AI_POWER_THROTTLE_EMERGENCY	= 3,	/* Emergency shutdown */
	AI_POWER_THROTTLE_AI_ADAPTIVE	= 4,	/* AI adaptive throttling */
};

/* Power domain types */
enum ai_power_domain {
	AI_POWER_DOMAIN_CPU		= 0,
	AI_POWER_DOMAIN_GPU		= 1,
	AI_POWER_DOMAIN_NPU		= 2,
	AI_POWER_DOMAIN_MEMORY		= 3,
	AI_POWER_DOMAIN_IO		= 4,
	AI_POWER_DOMAIN_SOC		= 5,
	AI_POWER_DOMAIN_COUNT		= 6,
};

/* Frequency configuration */
struct ai_power_freq {
	__u32			domain;
	__u32			cpu;
	__u64			freq_hz;
	__u64			min_freq_hz;
	__u64			max_freq_hz;
	__u32			flags;
	__s32			result;
	__u32			padding[4];
};

/* Voltage configuration */
struct ai_power_voltage {
	__u32			domain;
	__u32			cpu;
	__u64			voltage_uv;
	__u64			min_voltage_uv;
	__u64			max_voltage_uv;
	__u32			flags;
	__s32			result;
	__u32			padding[4];
};

/* Power consumption measurements */
struct ai_power_consumption {
	__u32			domain;
	__u64			power_uw;
	__u64			current_ua;
	__u64			energy_uj;
	__u64			avg_power_uw;
	__u64			max_power_uw;
	__u64			min_power_uw;
	__u64			time_window_ms;
	__u32			sensor_id;
	__u32			padding[6];
};

/* Thermal information */
struct ai_power_thermal {
	__u32			domain;
	__s32			temperature_c;
	__s32			trip_temp_c;
	__s32			critical_temp_c;
	__s32			passive_temp_c;
	__s32			hot_temp_c;
	__u32			throttle_mode;
	__u32			fan_speed_rpm;
	__u32			flags;
	__u32			padding[6];
};

/* Power management policy */
struct ai_power_policy {
	enum ai_power_profile_type	profile;
	__u32			flags;
	__u32			performance_bias;
	__u32			power_bias;
	__u32			thermal_throttle_threshold;
	__u32			boost_enabled;
	__u32			turbo_enabled;
	__u32			energy_performance_preference;
	__u32			autonomous_mode;
	__u32			ai_learning_enabled;
	__u32			learning_rate;
	__u32			history_size;
	__u32			prediction_window_ms;
	__u32			padding[8];
};

/* DVFS configuration */
struct ai_power_dvfs {
	__u32			domain;
	__u32			enabled;
	__u32			latency_us;
	__u32			step_size;
	__u64			min_freq;
	__u64			max_freq;
	__u64			target_freq;
	__u64			current_freq;
	__u64			voltage_uv;
	__u32			transition_count;
	__u32			transition_latency_max;
	__u32			flags;
	__u32			pending_count;
	__u32			padding[6];
};

/* Power prediction */
struct ai_power_prediction {
	__u32			domain;
	__u64			time_window_ms;
	__u64			predicted_power_uw;
	__u64			predicted_energy_uj;
	__u64			predicted_temp_c;
	__u64			predicted_freq_hz;
	__u32			confidence_percent;
	__u32			model_version;
	__u32			features;
	__u32			padding[6];
};

/* OPP (Operating Performance Point) */
struct ai_power_opp {
	__u32			domain;
	__u32			index;
	__u64			freq_hz;
	__u64			voltage_uv;
	__u64			power_uw;
	__u64			latency_ns;
	__u32			turbo;
	__u32			available;
	__u32			opp_count;
	__u32			padding[6];
};

/* Idle state configuration */
struct ai_power_idle {
	__u32			cpu;
	__u32			state;
	__u64			latency_us;
	__u64			residency_us;
	__u64			power_uw;
	__u64			time_in_state_ms;
	__u32			entry_count;
	__u32			usage_percent;
	__u32			disabled;
	__u32			padding[6];
};

/* Performance profile */
struct ai_power_profile {
	enum ai_power_profile_type	type;
	char			name[32];
	__u32			flags;
	__u64			boost_threshold;
	__u64			target_load;
	__u64			up_threshold;
	__u64			down_threshold;
	__u32			sampling_rate;
	__u32			up_step;
	__u32			down_step;
	__u32			ignore_nice_load;
	__u32			padding[8];
};

/* Battery information */
struct ai_power_battery {
	__s32			capacity_percent;
	__s32			status;
	__s32			health;
	__s32			temp_c;
	__s64			current_ma;
	__s64			voltage_uv;
	__s64			energy_uw;
	__s64			power_uw;
	__s64			charge_full_uw;
	__s64			charge_now_uw;
	__s32			cycle_count;
	__s32			technology;
	__s32			present;
	__u32			padding[6];
};

/* Governor information */
struct ai_power_governor {
	enum ai_power_governor_type	type;
	char			name[32];
	__u32			available;
	__u32			active;
	__u32			flags;
	__u32			padding[6];
};

/* Pressure Stall Information */
struct ai_power_psi {
	__u64			some_total;
	__u64			some_avg10;
	__u64			some_avg60;
	__u64			some_avg300;
	__u64			full_total;
	__u64			full_avg10;
	__u64			full_avg60;
	__u64			full_avg300;
	__u32			cpu_pressure;
	__u32			memory_pressure;
	__u32			io_pressure;
	__u32			padding[5];
};

/* Available frequencies */
struct ai_power_avail_freqs {
	__u32			domain;
	__u32			count;
	__u64			freqs[32];
	__u32			padding[8];
};

/* System power (PSYS) information */
struct ai_power_psys {
	__u64			power_uw;
	__u64			energy_uj;
	__u64			avg_power_uw;
	__u64			max_power_uw;
	__u64			power_limit_uw;
	__u32			throttle_active;
	__u32			padding[6];
};

/* AI advice on power management */
struct ai_power_ai_advice {
	__u32			domain;
	__u64			target_freq_hz;
	__u64			target_voltage_uv;
	__u32			target_cstate;
	__u32			performance_boost;
	__u32			throttle_recommendation;
	__u32			confidence;
	__u64			predicted_power_save;
	__u64			predicted_perf_impact;
	__u32			padding[8];
};

/* Module info */
struct ai_power_info {
	char			version[32];
	char			description[64];
	__u32			major_version;
	__u32			minor_version;
	__u32			patch_version;
	__u32			profile_active;
	__u32			domains_active;
	__u32			thermal_throttling;
	__u32			dvfs_enabled;
	__u32			ai_governor_enabled;
	__u32			features;
	__u32			padding[8];
};

/* Sysfs entries */
#define AI_POWER_SYSFS_PROFILE		"profile"
#define AI_POWER_SYSFS_FREQUENCY	"frequency"
#define AI_POWER_SYSFS_VOLTAGE		"voltage"
#define AI_POWER_SYSFS_POWER		"power"
#define AI_POWER_SYSFS_TEMPERATURE	"temperature"
#define AI_POWER_SYSFS_DVFS		"dvfs"
#define AI_POWER_SYSFS_GOVERNOR		"governor"
#define AI_POWER_SYSFS_IDLE_STATES	"idle_states"
#define AI_POWER_SYSFS_BATTERY		"battery"
#define AI_POWER_SYSFS_PREDICTION	"prediction"
#define AI_POWER_SYSFS_THERMAL_LIMIT	"thermal_limit"
#define AI_POWER_SYSFS_PSI		"psi"
#define AI_POWER_SYSFS_PSYS		"psys"

/* Internal kernel API */
struct ai_power_manager;

#ifdef CONFIG_AINOS_AI_POWER

/* Frequency management */
int ai_power_set_freq(unsigned int domain, unsigned int cpu, __u64 freq_hz);
int ai_power_get_freq(unsigned int domain, unsigned int cpu, __u64 *freq_hz);
int ai_power_get_avail_freqs(unsigned int domain,
			     struct ai_power_avail_freqs *freqs);

/* Voltage management */
int ai_power_set_voltage(unsigned int domain, unsigned int cpu, __u64 voltage_uv);
int ai_power_get_voltage(unsigned int domain, unsigned int cpu, __u64 *voltage_uv);

/* Power measurement */
int ai_power_get_consumption(unsigned int domain,
			     struct ai_power_consumption *consumption);
int ai_power_get_psys(struct ai_power_psys *psys);
int ai_power_set_psys_limit(struct ai_power_psys *limit);

/* Thermal management */
int ai_power_get_temperature(unsigned int domain, struct ai_power_thermal *thermal);
int ai_power_set_thermal_limit(unsigned int domain,
			       struct ai_power_thermal *limit);
int ai_power_get_throttle_mode(unsigned int domain,
			       enum ai_power_throttle_mode *mode);

/* Policy management */
int ai_power_set_policy(struct ai_power_policy *policy);
int ai_power_get_policy(struct ai_power_policy *policy);
int ai_power_set_profile(enum ai_power_profile_type profile);
int ai_power_get_profile(enum ai_power_profile_type *profile);

/* DVFS management */
int ai_power_dvfs_config(struct ai_power_dvfs *dvfs);
int ai_power_dvfs_get(struct ai_power_dvfs *dvfs);
int ai_power_dvfs_enable(unsigned int domain);
int ai_power_dvfs_disable(unsigned int domain);

/* OPP management */
int ai_power_opp_get(struct ai_power_opp *opp);
int ai_power_opp_set(struct ai_power_opp *opp);
int ai_power_opp_enable(unsigned int domain, unsigned int index);
int ai_power_opp_disable(unsigned int domain, unsigned int index);

/* Governor management */
int ai_power_set_governor(enum ai_power_governor_type governor);
int ai_power_get_governor(enum ai_power_governor_type *governor);
int ai_power_governor_list(struct ai_power_governor *governors, int *count);

/* Idle management */
int ai_power_idle_set(unsigned int cpu, unsigned int state);
int ai_power_idle_get(unsigned int cpu, struct ai_power_idle *idle);
int ai_power_idle_disable(unsigned int cpu, unsigned int state);

/* Prediction */
int ai_power_predict(struct ai_power_prediction *prediction);
int ai_power_get_ai_advice(unsigned int domain,
			   struct ai_power_ai_advice *advice);

/* Battery */
int ai_power_get_battery(struct ai_power_battery *battery);

/* PSI */
int ai_power_get_psi(struct ai_power_psi *psi);

/* System sleep */
int ai_power_suspend(unsigned int state);
int ai_power_resume(void);

#else /* !CONFIG_AINOS_AI_POWER */

/* Stubs */
static inline int ai_power_set_freq(unsigned int domain, unsigned int cpu,
				    __u64 freq_hz)
{ return -ENODEV; }

static inline int ai_power_get_freq(unsigned int domain, unsigned int cpu,
				    __u64 *freq_hz)
{ return -ENODEV; }

static inline int ai_power_get_avail_freqs(unsigned int domain,
					   struct ai_power_avail_freqs *freqs)
{ return -ENODEV; }

static inline int ai_power_set_voltage(unsigned int domain, unsigned int cpu,
				       __u64 voltage_uv)
{ return -ENODEV; }

static inline int ai_power_get_voltage(unsigned int domain, unsigned int cpu,
				       __u64 *voltage_uv)
{ return -ENODEV; }

static inline int ai_power_get_consumption(unsigned int domain,
					   struct ai_power_consumption *c)
{ return -ENODEV; }

static inline int ai_power_get_psys(struct ai_power_psys *psys)
{ return -ENODEV; }

static inline int ai_power_set_psys_limit(struct ai_power_psys *limit)
{ return -ENODEV; }

static inline int ai_power_get_temperature(unsigned int domain,
					   struct ai_power_thermal *thermal)
{ return -ENODEV; }

static inline int ai_power_set_thermal_limit(unsigned int domain,
					     struct ai_power_thermal *limit)
{ return -ENODEV; }

static inline int ai_power_get_throttle_mode(unsigned int domain,
					     enum ai_power_throttle_mode *mode)
{ return -ENODEV; }

static inline int ai_power_set_policy(struct ai_power_policy *policy)
{ return -ENODEV; }

static inline int ai_power_get_policy(struct ai_power_policy *policy)
{ return -ENODEV; }

static inline int ai_power_set_profile(enum ai_power_profile_type profile)
{ return -ENODEV; }

static inline int ai_power_get_profile(enum ai_power_profile_type *profile)
{ return -ENODEV; }

static inline int ai_power_dvfs_config(struct ai_power_dvfs *dvfs)
{ return -ENODEV; }

static inline int ai_power_dvfs_get(struct ai_power_dvfs *dvfs)
{ return -ENODEV; }

static inline int ai_power_dvfs_enable(unsigned int domain)
{ return -ENODEV; }

static inline int ai_power_dvfs_disable(unsigned int domain)
{ return -ENODEV; }

static inline int ai_power_opp_get(struct ai_power_opp *opp)
{ return -ENODEV; }

static inline int ai_power_opp_set(struct ai_power_opp *opp)
{ return -ENODEV; }

static inline int ai_power_opp_enable(unsigned int domain, unsigned int index)
{ return -ENODEV; }

static inline int ai_power_opp_disable(unsigned int domain, unsigned int index)
{ return -ENODEV; }

static inline int ai_power_set_governor(enum ai_power_governor_type governor)
{ return -ENODEV; }

static inline int ai_power_get_governor(enum ai_power_governor_type *governor)
{ return -ENODEV; }

static inline int ai_power_governor_list(struct ai_power_governor *governors,
					 int *count)
{ return -ENODEV; }

static inline int ai_power_idle_set(unsigned int cpu, unsigned int state)
{ return -ENODEV; }

static inline int ai_power_idle_get(unsigned int cpu,
				    struct ai_power_idle *idle)
{ return -ENODEV; }

static inline int ai_power_idle_disable(unsigned int cpu, unsigned int state)
{ return -ENODEV; }

static inline int ai_power_predict(struct ai_power_prediction *prediction)
{ return -ENODEV; }

static inline int ai_power_get_ai_advice(unsigned int domain,
					 struct ai_power_ai_advice *advice)
{ return -ENODEV; }

static inline int ai_power_get_battery(struct ai_power_battery *battery)
{ return -ENODEV; }

static inline int ai_power_get_psi(struct ai_power_psi *psi)
{ return -ENODEV; }

static inline int ai_power_suspend(unsigned int state)
{ return -ENODEV; }

static inline int ai_power_resume(void)
{ return 0; }

#endif /* CONFIG_AINOS_AI_POWER */

#endif /* _AINOS_AI_POWER_H */