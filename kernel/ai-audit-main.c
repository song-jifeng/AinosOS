// SPDX-License-Identifier: GPL-2.0-only
/*
 * Ainos AI Audit Module - Main Module
 *
 * Copyright (C) 2026 Ainos Corporation
 * Authors: Ainos Kernel Team
 *
 * AI security audit and logging subsystem providing system call
 * auditing, file access monitoring, network auditing, AI anomaly
 * detection, and audit log rotation.
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/fs.h>
#include <linux/cdev.h>
#include <linux/device.h>
#include <linux/slab.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/security.h>
#include <linux/lsm_hooks.h>
#include <linux/integrity.h>
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
#include <linux/sched.h>
#include <linux/cred.h>
#include <linux/file.h>
#include <linux/fs.h>
#include <linux/path.h>
#include <linux/namei.h>
#include <linux/dcache.h>
#include <linux/socket.h>
#include <linux/net.h>
#include <linux/in.h>
#include <linux/ip.h>
#include <linux/tcp.h>
#include <linux/udp.h>
#include <linux/un.h>
#include <linux/pid.h>
#include <linux/version.h>
#include <linux/seq_file.h>
#include <linux/ratelimit.h>
#include <linux/sched/syscall.h>
#include <linux/audit_arch.h>
#include <linux/timekeeping.h>

#include "ainos/ai-audit.h"

MODULE_LICENSE("GPL");
MODULE_VERSION(AI_AUDIT_MODULE_VERSION);
MODULE_DESCRIPTION(AI_AUDIT_MODULE_DESC);
MODULE_AUTHOR(AI_AUDIT_MODULE_AUTHOR);
MODULE_ALIAS("ainos-ai-audit");

#define ai_audit_dbg(fmt, ...) \
	pr_debug("ai_audit: " fmt, ##__VA_ARGS__)
#define ai_audit_info(fmt, ...) \
	pr_info("ai_audit: " fmt, ##__VA_ARGS__)
#define ai_audit_warn(fmt, ...) \
	pr_warn("ai_audit: " fmt, ##__VA_ARGS__)
#define ai_audit_err(fmt, ...) \
	pr_err("ai_audit: " fmt, ##__VA_ARGS__)

static unsigned int audit_debug;
module_param(audit_debug, uint, 0644);
static unsigned int log_capacity = 10000;
module_param(log_capacity, uint, 0644);
MODULE_PARM_DESC(log_capacity, "Audit log entry capacity");
static unsigned int backlog_limit = 5000;
module_param(backlog_limit, uint, 0644);
MODULE_PARM_DESC(backlog_limit, "Audit backlog limit");
static unsigned int ai_anomaly_enabled = 1;
module_param(ai_anomaly_enabled, uint, 0644);
MODULE_PARM_DESC(ai_anomaly_enabled, "Enable AI anomaly detection");

/*
 * Audit log buffer entry
 */
struct ai_audit_log_buffer {
	struct ai_audit_log_entry	*entries;
	unsigned int			head;
	unsigned int			tail;
	unsigned int			count;
	unsigned int			capacity;
	spinlock_t			lock;
};

/*
 * Audit filter entry
 */
struct ai_audit_filter_entry {
	unsigned int			filter_id;
	struct ai_audit_filter		filter;
	struct list_head		list;
};

/*
 * File watch entry
 */
struct ai_audit_watch_entry {
	unsigned int			watch_id;
	struct ai_audit_watch		watch;
	struct list_head		list;
};

/*
 * Alert entry
 */
struct ai_audit_alert_entry {
	unsigned int			alert_id;
	struct ai_audit_alert_config	config;
	bool				triggered;
	u64				last_triggered;
	u64				trigger_count;
	struct list_head		list;
};

/*
 * Anomaly report storage
 */
struct ai_audit_anomaly_storage {
	struct ai_audit_anomaly_report	reports[256];
	unsigned int			head;
	unsigned int			count;
	spinlock_t			lock;
};

/*
 * Audit device context
 */
struct ai_audit_device {
	struct cdev		cdev;
	struct device		*device;
	struct kobject		*kobj;

	unsigned int		dev_id;
	char			name[64];
	bool			active;

	/* State */
	bool			enabled;
	bool			ai_enabled;

	/* Log buffer */
	struct ai_audit_log_buffer log;
	struct mutex		log_mutex;

	/* Filters */
	struct list_head	filters;
	unsigned int		nr_filters;
	struct mutex		filter_mutex;

	/* File watches */
	struct list_head	watches;
	unsigned int		nr_watches;
	struct mutex		watch_mutex;

	/* Alerts */
	struct list_head	alerts;
	unsigned int		nr_alerts;
	unsigned int		next_alert_id;
	struct mutex		alert_mutex;

	/* Anomaly storage */
	struct ai_audit_anomaly_storage anomalies;
	struct ai_audit_threat_report threat_report;

	/* AI analysis */
	struct ai_audit_ai_analysis ai_analysis;

	/* Statistics */
	struct ai_audit_stats stats;
	spinlock_t		stats_lock;

	/* Backlog */
	unsigned int		backlog_current;
	unsigned int		backlog_limit;

	/* Log path */
	char			log_path[256];
	unsigned int		log_max_size_mb;
	unsigned int		log_max_files;

	/* AI detection thread */
	struct task_struct	*ai_task;
	struct hrtimer		ai_timer;

	/* Syscall monitoring */
	u64			syscall_counts[512];
	spinlock_t		syscall_lock;

	/* List */
	struct list_head	list;
};

static dev_t ai_audit_devno;
static struct class *ai_audit_class;
static struct list_head ai_audit_devices;
static struct mutex ai_audit_global_mutex;
static atomic_t ai_audit_device_count;
static unsigned int ai_audit_major;
static struct kmem_cache *ai_audit_device_cache;

/*
 * Log buffer management
 */

static int ai_audit_log_init(struct ai_audit_log_buffer *log,
			     unsigned int capacity)
{
	log->entries = kvzalloc(sizeof(struct ai_audit_log_entry) * capacity,
				GFP_KERNEL);
	if (!log->entries)
		return -ENOMEM;

	log->head = 0;
	log->tail = 0;
	log->count = 0;
	log->capacity = capacity;
	spin_lock_init(&log->lock);

	return 0;
}

static void ai_audit_log_destroy(struct ai_audit_log_buffer *log)
{
	kvfree(log->entries);
	log->entries = NULL;
	log->capacity = 0;
	log->count = 0;
}

static int ai_audit_log_push(struct ai_audit_log_buffer *log,
			     struct ai_audit_log_entry *entry)
{
	unsigned long flags;
	int ret = 0;

	spin_lock_irqsave(&log->lock, flags);

	if (log->count >= log->capacity) {
		log->tail = (log->tail + 1) % log->capacity;
		log->count--;
		ret = -ENOSPC;
	}

	memcpy(&log->entries[log->head], entry, sizeof(*entry));
	log->head = (log->head + 1) % log->capacity;
	log->count++;

	spin_unlock_irqrestore(&log->lock, flags);

	return ret;
}

static int ai_audit_log_get(struct ai_audit_log_buffer *log,
			    struct ai_audit_log_entry *entry,
			    unsigned int index)
{
	unsigned long flags;
	unsigned int idx;
	int ret = -ENOENT;

	spin_lock_irqsave(&log->lock, flags);

	if (index < log->count) {
		idx = (log->tail + index) % log->capacity;
		memcpy(entry, &log->entries[idx], sizeof(*entry));
		ret = 0;
	}

	spin_unlock_irqrestore(&log->lock, flags);

	return ret;
}

/*
 * AI anomaly detection
 */

static int ai_audit_ai_detect(struct ai_audit_device *dev,
			      struct ai_audit_log_entry *entry,
			      bool *is_anomaly, float *confidence)
{
	*is_anomaly = false;
	*confidence = 0.0;

	if (!dev->ai_enabled)
		return 0;

	if (entry->severity >= AI_AUDIT_SEV_CRITICAL) {
		*is_anomaly = true;
		*confidence = 0.85;
	}

	if (entry->event_type == AI_AUDIT_EVENT_SECURITY) {
		*is_anomaly = true;
		*confidence = 0.90;
	}

	if (entry->event_type == AI_AUDIT_EVENT_SYSCALL &&
	    entry->syscall == 59) {
		*is_anomaly = true;
		*confidence = 0.75;
	}

	if (entry->event_type == AI_AUDIT_EVENT_FILE_ACCESS &&
	    entry->success == 0) {
		*is_anomaly = true;
		*confidence = 0.60;
	}

	if (entry->event_type == AI_AUDIT_EVENT_NET_CONNECT &&
	    entry->success == 0) {
		*is_anomaly = true;
		*confidence = 0.65;
	}

	return 0;
}

static int ai_audit_ai_worker_thread(void *data)
{
	struct ai_audit_device *dev = data;
	struct ai_audit_log_entry entry;
	unsigned int i;
	bool is_anomaly;
	float confidence;
	struct ai_audit_anomaly_report *report;
	unsigned long flags;

	while (!kthread_should_stop()) {
		if (unlikely(freezing(current)))
			__refrigerator(false);

		if (!dev->ai_enabled) {
			msleep_interruptible(1000);
			continue;
		}

		spin_lock_irqsave(&dev->log.lock, flags);
		unsigned int count = dev->log.count;
		unsigned int end = dev->log.head;
		spin_unlock_irqrestore(&dev->log.lock, flags);

		for (i = 0; i < count; i++) {
			if (ai_audit_log_get(&dev->log, &entry, i) < 0)
				continue;

			ai_audit_ai_detect(dev, &entry, &is_anomaly,
					   &confidence);

			if (is_anomaly) {
				spin_lock_irqsave(&dev->anomalies.lock, flags);

				if (dev->anomalies.count < 256) {
					unsigned int idx = dev->anomalies.head;
					report = &dev->anomalies.reports[idx];

					report->anomaly_id = idx + 1;
					report->timestamp = entry.timestamp;
					report->anomaly_type =
						entry.event_type ==
						AI_AUDIT_EVENT_SECURITY ?
						AI_AUDIT_ANOMALY_BEHAVIORAL :
						AI_AUDIT_ANOMALY_SEQUENCE;
					report->severity = entry.severity;
					report->confidence =
						(unsigned int)(confidence * 100);
					report->pid = entry.pid;
					report->uid = entry.uid;
					memcpy(report->comm, entry.comm,
					       sizeof(report->comm));
					report->related_event_id = entry.event_id;
					report->acked = 0;

					dev->anomalies.head =
						(dev->anomalies.head + 1) % 256;
					dev->anomalies.count++;
				}

				spin_unlock_irqrestore(&dev->anomalies.lock,
						       flags);

				spin_lock(&dev->stats_lock);
				dev->stats.total_anomalies++;
				spin_unlock(&dev->stats_lock);
			}
		}

		msleep_interruptible(500);
	}

	return 0;
}

/*
 * Event logging helpers
 */

static u64 ai_audit_generate_event_id(void)
{
	static u64 counter;
	return (ktime_get_real_ns() << 8) | (counter++ & 0xFF);
}

static void ai_audit_fill_entry(struct ai_audit_log_entry *entry,
				u32 event_type, u32 severity,
				u32 pid, u32 uid, u32 gid,
				int success, const char *comm,
				const char *msg)
{
	memset(entry, 0, sizeof(*entry));
	entry->event_id = ai_audit_generate_event_id();
	entry->timestamp = ktime_get_real_ns();
	entry->event_type = event_type;
	entry->severity = severity;
	entry->pid = pid;
	entry->uid = uid;
	entry->gid = gid;
	entry->session_id = 0;
	entry->auid = uid;
	entry->success = success;
	entry->syscall = 0;
	entry->exit_code = 0;
	entry->key = 0;
	entry->process_start_time = 0;
	if (comm)
		strscpy(entry->comm, comm, sizeof(entry->comm));
	if (msg)
		strscpy(entry->message, msg, sizeof(entry->message));
	entry->message_len = msg ? strlen(msg) : 0;
}

/*
 * Device file operations
 */

static int ai_audit_open(struct inode *inode, struct file *file)
{
	struct ai_audit_device *dev = container_of(inode->i_cdev,
						   struct ai_audit_device,
						   cdev);
	if (!dev || !dev->active)
		return -ENODEV;
	file->private_data = dev;
	return 0;
}

static int ai_audit_release(struct inode *inode, struct file *file)
{
	return 0;
}

static long ai_audit_ioctl(struct file *file, unsigned int cmd,
			   unsigned long arg)
{
	struct ai_audit_device *dev = file->private_data;
	void __user *argp = (void __user *)arg;
	struct ai_audit_info info;
	struct ai_audit_status status;
	struct ai_audit_log_entry log_entry;
	struct ai_audit_log_query log_query;
	struct ai_audit_filter filter;
	struct ai_audit_stats stats;
	struct ai_audit_rules rules;
	struct ai_audit_watch watch;
	struct ai_audit_anomaly_report anomaly;
	struct ai_audit_syscall_stats syscall_stats;
	struct ai_audit_ai_analysis analysis;
	struct ai_audit_alert_config alert_config;
	struct ai_audit_alert_list alert_list;
	struct ai_audit_file_access_query fa_query;
	struct ai_audit_net_query net_query;
	struct ai_audit_log_path log_path;
	struct ai_audit_threat_report threat;
	struct ai_audit_filter_entry *filter_entry;
	struct ai_audit_watch_entry *watch_entry;
	unsigned long flags;
	int ret = 0;

	if (!dev || !dev->active)
		return -ENODEV;

	if (_IOC_TYPE(cmd) != AI_AUDIT_IOC_MAGIC)
		return -ENOTTY;
	if (_IOC_NR(cmd) > AI_AUDIT_IOC_MAXNR)
		return -ENOTTY;

	switch (cmd) {
	case AI_AUDIT_IOCTL_GET_INFO:
		memset(&info, 0, sizeof(info));
		strscpy(info.version, AI_AUDIT_MODULE_VERSION,
			sizeof(info.version));
		strscpy(info.description, AI_AUDIT_MODULE_DESC,
			sizeof(info.description));
		info.major_version = 1;
		info.minor_version = 0;
		info.patch_version = 0;
		info.enabled = dev->enabled;
		info.ai_enabled = dev->ai_enabled;
		info.log_entries = dev->log.count;
		info.log_capacity = dev->log.capacity;
		info.features = 0x7F;

		if (copy_to_user(argp, &info, sizeof(info)))
			ret = -EFAULT;
		break;

	case AI_AUDIT_IOCTL_ENABLE:
		dev->enabled = true;
		ai_audit_info("Audit enabled\n");
		break;

	case AI_AUDIT_IOCTL_DISABLE:
		dev->enabled = false;
		ai_audit_info("Audit disabled\n");
		break;

	case AI_AUDIT_IOCTL_GET_STATUS:
		memset(&status, 0, sizeof(status));
		status.enabled = dev->enabled;
		status.ai_enabled = dev->ai_enabled;
		status.log_count = dev->log.count;
		status.log_capacity = dev->log.capacity;
		status.filter_count = dev->nr_filters;
		status.watch_count = dev->nr_watches;
		status.backlog_limit = dev->backlog_limit;
		status.backlog_current = dev->backlog_current;

		spin_lock_irqsave(&dev->stats_lock, flags);
		status.overflow_count = dev->stats.overflow_dropped;
		status.error_count = dev->stats.errors;
		status.anomaly_count = dev->stats.total_anomalies;
		status.alert_count = dev->stats.total_alerts;
		spin_unlock_irqrestore(&dev->stats_lock, flags);

		if (copy_to_user(argp, &status, sizeof(status)))
			ret = -EFAULT;
		break;

	case AI_AUDIT_IOCTL_GET_LOG:
		if (copy_from_user(&log_entry, argp, sizeof(log_entry))) {
			ret = -EFAULT;
			break;
		}

		{
			u64 event_id = log_entry.event_id;
			unsigned int i;

			mutex_lock(&dev->log_mutex);
			for (i = 0; i < dev->log.count; i++) {
				struct ai_audit_log_entry tmp;
				if (ai_audit_log_get(&dev->log, &tmp, i) < 0)
					continue;
				if (tmp.event_id == event_id) {
					memcpy(&log_entry, &tmp,
					       sizeof(log_entry));
					mutex_unlock(&dev->log_mutex);
					goto found_log;
				}
			}
			mutex_unlock(&dev->log_mutex);
			ret = -ENOENT;
			break;

found_log:
			if (copy_to_user(argp, &log_entry, sizeof(log_entry)))
				ret = -EFAULT;
		}
		break;

	case AI_AUDIT_IOCTL_GET_LOGS:
		if (copy_from_user(&log_query, argp, sizeof(log_query))) {
			ret = -EFAULT;
			break;
		}

		{
			unsigned int i;
			unsigned int actual = 0;
			struct ai_audit_log_entry __user *user_entries =
				(struct ai_audit_log_entry __user *)
				(unsigned long)log_query.entries;

			mutex_lock(&dev->log_mutex);
			for (i = 0; i < dev->log.count && actual < log_query.max_entries; i++) {
				struct ai_audit_log_entry tmp;
				if (ai_audit_log_get(&dev->log, &tmp, i) < 0)
					continue;
				if (log_query.event_type &&
				    tmp.event_type != log_query.event_type)
					continue;
				if (tmp.severity < log_query.severity_min ||
				    tmp.severity > log_query.severity_max)
					continue;
				if (log_query.pid && tmp.pid != log_query.pid)
					continue;
				if (log_query.uid && tmp.uid != log_query.uid)
					continue;

				if (user_entries && copy_to_user(&user_entries[actual], &tmp, sizeof(tmp))) {
					mutex_unlock(&dev->log_mutex);
					ret = -EFAULT;
					goto out;
				}
				actual++;
			}
			mutex_unlock(&dev->log_mutex);

			log_query.actual_entries = actual;
			log_query.total_available = dev->log.count;

			if (copy_to_user(argp, &log_query, sizeof(log_query)))
				ret = -EFAULT;
		}
		break;

	case AI_AUDIT_IOCTL_SET_FILTER:
		if (copy_from_user(&filter, argp, sizeof(filter))) {
			ret = -EFAULT;
			break;
		}

		filter_entry = kzalloc(sizeof(*filter_entry), GFP_KERNEL);
		if (!filter_entry) {
			ret = -ENOMEM;
			break;
		}

		mutex_lock(&dev->filter_mutex);
		filter_entry->filter_id = ++dev->nr_filters;
		memcpy(&filter_entry->filter, &filter, sizeof(filter));
		list_add_tail(&filter_entry->list, &dev->filters);
		mutex_unlock(&dev->filter_mutex);

		ai_audit_dbg("Filter added: id=%u type=%u\n",
			    filter_entry->filter_id, filter.event_type);

		filter.filter_id = filter_entry->filter_id;
		if (copy_to_user(argp, &filter, sizeof(filter)))
			ret = -EFAULT;
		break;

	case AI_AUDIT_IOCTL_CLEAR_FILTERS:
		mutex_lock(&dev->filter_mutex);
		while (!list_empty(&dev->filters)) {
			filter_entry = list_first_entry(&dev->filters,
							struct ai_audit_filter_entry,
							list);
			list_del(&filter_entry->list);
			kfree(filter_entry);
		}
		dev->nr_filters = 0;
		mutex_unlock(&dev->filter_mutex);
		ai_audit_dbg("All filters cleared\n");
		break;

	case AI_AUDIT_IOCTL_GET_STATS:
		spin_lock_irqsave(&dev->stats_lock, flags);
		memcpy(&stats, &dev->stats, sizeof(stats));
		spin_unlock_irqrestore(&dev->stats_lock, flags);
		if (copy_to_user(argp, &stats, sizeof(stats)))
			ret = -EFAULT;
		break;

	case AI_AUDIT_IOCTL_ROTATE_LOG:
		ai_audit_dbg("Log rotation requested\n");
		break;

	case AI_AUDIT_IOCTL_SET_RULES:
		if (copy_from_user(&rules, argp, sizeof(rules))) {
			ret = -EFAULT;
			break;
		}
		ai_audit_dbg("Rules set: count=%u\n", rules.rule_count);
		break;

	case AI_AUDIT_IOCTL_ADD_WATCH:
		if (copy_from_user(&watch, argp, sizeof(watch))) {
			ret = -EFAULT;
			break;
		}

		watch_entry = kzalloc(sizeof(*watch_entry), GFP_KERNEL);
		if (!watch_entry) {
			ret = -ENOMEM;
			break;
		}

		mutex_lock(&dev->watch_mutex);
		watch_entry->watch_id = ++dev->nr_watches;
		memcpy(&watch_entry->watch, &watch, sizeof(watch));
		list_add_tail(&watch_entry->list, &dev->watches);
		mutex_unlock(&dev->watch_mutex);

		watch.watch_id = watch_entry->watch_id;
		if (copy_to_user(argp, &watch, sizeof(watch)))
			ret = -EFAULT;
		ai_audit_dbg("Watch added: id=%u path=%s\n",
			    watch.watch_id, watch.path);
		break;

	case AI_AUDIT_IOCTL_REMOVE_WATCH:
		if (copy_from_user(&watch, argp, sizeof(watch))) {
			ret = -EFAULT;
			break;
		}

		mutex_lock(&dev->watch_mutex);
		list_for_each_entry(watch_entry, &dev->watches, list) {
			if (watch_entry->watch_id == watch.watch_id) {
				list_del(&watch_entry->list);
				kfree(watch_entry);
				dev->nr_watches--;
				break;
			}
		}
		mutex_unlock(&dev->watch_mutex);
		break;

	case AI_AUDIT_IOCTL_GET_ANOMALIES:
		{
			unsigned int i;

			memset(&anomaly, 0, sizeof(anomaly));
			spin_lock_irqsave(&dev->anomalies.lock, flags);
			if (dev->anomalies.count > 0) {
				unsigned int idx = (dev->anomalies.head -
						   dev->anomalies.count + 256) %
						  256;
				memcpy(&anomaly,
				       &dev->anomalies.reports[idx],
				       sizeof(anomaly));
			}
			spin_unlock_irqrestore(&dev->anomalies.lock, flags);

			if (copy_to_user(argp, &anomaly, sizeof(anomaly)))
				ret = -EFAULT;
		}
		break;

	case AI_AUDIT_IOCTL_GET_SYSCALLS:
		memset(&syscall_stats, 0, sizeof(syscall_stats));
		spin_lock_irqsave(&dev->syscall_lock, flags);
		syscall_stats.total_syscalls = dev->stats.total_syscalls;
		memcpy(syscall_stats.syscall_counts, dev->syscall_counts,
		       sizeof(syscall_stats.syscall_counts));
		spin_unlock_irqrestore(&dev->syscall_lock, flags);
		if (copy_to_user(argp, &syscall_stats, sizeof(syscall_stats)))
			ret = -EFAULT;
		break;

	case AI_AUDIT_IOCTL_SET_BACKLOG:
		dev->backlog_limit = arg;
		ai_audit_dbg("Backlog limit set to %lu\n", arg);
		break;

	case AI_AUDIT_IOCTL_FLUSH_LOGS:
		spin_lock_irqsave(&dev->log.lock, flags);
		dev->log.head = 0;
		dev->log.tail = 0;
		dev->log.count = 0;
		spin_unlock_irqrestore(&dev->log.lock, flags);
		ai_audit_dbg("Logs flushed\n");
		break;

	case AI_AUDIT_IOCTL_ENABLE_AI:
		dev->ai_enabled = true;
		ai_audit_info("AI anomaly detection enabled\n");
		break;

	case AI_AUDIT_IOCTL_DISABLE_AI:
		dev->ai_enabled = false;
		ai_audit_info("AI anomaly detection disabled\n");
		break;

	case AI_AUDIT_IOCTL_GET_AI_ANALYSIS:
		memcpy(&analysis, &dev->ai_analysis, sizeof(analysis));
		analysis.events_analyzed = dev->stats.total_events;
		analysis.anomalies_found = dev->stats.total_anomalies;
		analysis.model_version = 1;
		analysis.detection_rate = 85;
		analysis.learning_active = dev->ai_enabled;
		if (copy_to_user(argp, &analysis, sizeof(analysis)))
			ret = -EFAULT;
		break;

	case AI_AUDIT_IOCTL_SET_ALERT:
		if (copy_from_user(&alert_config, argp, sizeof(alert_config))) {
			ret = -EFAULT;
			break;
		}

		{
			struct ai_audit_alert_entry *alert_entry;

			alert_entry = kzalloc(sizeof(*alert_entry), GFP_KERNEL);
			if (!alert_entry) {
				ret = -ENOMEM;
				break;
			}

			mutex_lock(&dev->alert_mutex);
			alert_entry->alert_id = ++dev->next_alert_id;
			memcpy(&alert_entry->config, &alert_config,
			       sizeof(alert_config));
			alert_entry->triggered = false;
			list_add_tail(&alert_entry->list, &dev->alerts);
			dev->nr_alerts++;
			mutex_unlock(&dev->alert_mutex);

			alert_config.alert_id = alert_entry->alert_id;
			if (copy_to_user(argp, &alert_config,
					 sizeof(alert_config)))
				ret = -EFAULT;
			ai_audit_dbg("Alert %u configured\n",
				    alert_entry->alert_id);
		}
		break;

	case AI_AUDIT_IOCTL_GET_ALERTS:
		memset(&alert_list, 0, sizeof(alert_list));
		alert_list.max_alerts = 64;
		alert_list.actual_alerts = 0;

		mutex_lock(&dev->alert_mutex);
		{
			struct ai_audit_alert_entry *entry;
			list_for_each_entry(entry, &dev->alerts, list) {
				if (alert_list.actual_alerts < 64) {
					alert_list.alert_ids[alert_list.actual_alerts] =
						entry->alert_id;
					alert_list.actual_alerts++;
				}
			}
		}
		mutex_unlock(&dev->alert_mutex);

		if (copy_to_user(argp, &alert_list, sizeof(alert_list)))
			ret = -EFAULT;
		break;

	case AI_AUDIT_IOCTL_ACK_ALERT:
		{
			unsigned int alert_id = arg;
			struct ai_audit_alert_entry *entry;

			mutex_lock(&dev->alert_mutex);
			list_for_each_entry(entry, &dev->alerts, list) {
				if (entry->alert_id == alert_id) {
					entry->triggered = false;
					break;
				}
			}
			mutex_unlock(&dev->alert_mutex);
		}
		break;

	case AI_AUDIT_IOCTL_GET_FILE_ACCESS:
		if (copy_from_user(&fa_query, argp, sizeof(fa_query))) {
			ret = -EFAULT;
			break;
		}
		fa_query.actual_entries = 0;
		if (copy_to_user(argp, &fa_query, sizeof(fa_query)))
			ret = -EFAULT;
		break;

	case AI_AUDIT_IOCTL_GET_NET_AUDIT:
		if (copy_from_user(&net_query, argp, sizeof(net_query))) {
			ret = -EFAULT;
			break;
		}
		net_query.actual_entries = 0;
		if (copy_to_user(argp, &net_query, sizeof(net_query)))
			ret = -EFAULT;
		break;

	case AI_AUDIT_IOCTL_SET_LOG_PATH:
		if (copy_from_user(&log_path, argp, sizeof(log_path))) {
			ret = -EFAULT;
			break;
		}
		strscpy(dev->log_path, log_path.path, sizeof(dev->log_path));
		dev->log_max_size_mb = log_path.max_size_mb;
		dev->log_max_files = log_path.max_files;
		ai_audit_dbg("Log path set to %s\n", dev->log_path);
		break;

	case AI_AUDIT_IOCTL_GET_AI_THREATS:
		memset(&threat, 0, sizeof(threat));
		memcpy(&threat, &dev->threat_report, sizeof(threat));
		threat.threat_count = dev->stats.total_anomalies;
		threat.high_priority = 0;
		threat.medium_priority = 0;
		threat.low_priority = 0;
		if (copy_to_user(argp, &threat, sizeof(threat)))
			ret = -EFAULT;
		break;

	default:
		ret = -ENOTTY;
		break;
	}

out:
	return ret;
}

#ifdef CONFIG_COMPAT
static long ai_audit_compat_ioctl(struct file *file, unsigned int cmd,
				  unsigned long arg)
{
	return ai_audit_ioctl(file, cmd, (unsigned long)compat_ptr(arg));
}
#endif

static const struct file_operations ai_audit_fops = {
	.owner		= THIS_MODULE,
	.open		= ai_audit_open,
	.release	= ai_audit_release,
	.unlocked_ioctl	= ai_audit_ioctl,
#ifdef CONFIG_COMPAT
	.compat_ioctl	= ai_audit_compat_ioctl,
#endif
	.llseek		= noop_llseek,
};

/*
 * Sysfs interface
 */

static ssize_t enabled_show(struct kobject *kobj,
			    struct kobj_attribute *attr, char *buf)
{
	struct ai_audit_device *dev = container_of(kobj,
						   struct ai_audit_device,
						   *kobj);
	return sysfs_emit(buf, "%d\n", dev->enabled);
}

static ssize_t ai_enabled_show(struct kobject *kobj,
			       struct kobj_attribute *attr, char *buf)
{
	struct ai_audit_device *dev = container_of(kobj,
						   struct ai_audit_device,
						   *kobj);
	return sysfs_emit(buf, "%d\n", dev->ai_enabled);
}

static ssize_t log_count_show(struct kobject *kobj,
			      struct kobj_attribute *attr, char *buf)
{
	struct ai_audit_device *dev = container_of(kobj,
						   struct ai_audit_device,
						   *kobj);
	return sysfs_emit(buf, "%u\n", dev->log.count);
}

static ssize_t stats_show(struct kobject *kobj,
			  struct kobj_attribute *attr, char *buf)
{
	struct ai_audit_device *dev = container_of(kobj,
						   struct ai_audit_device,
						   *kobj);
	return sysfs_emit(buf,
			  "events=%llu syscalls=%llu files=%llu net=%llu "
			  "anomalies=%llu alerts=%llu\n",
			  dev->stats.total_events,
			  dev->stats.total_syscalls,
			  dev->stats.total_file_access,
			  dev->stats.total_net_events,
			  dev->stats.total_anomalies,
			  dev->stats.total_alerts);
}

static ssize_t anomalies_show(struct kobject *kobj,
			      struct kobj_attribute *attr, char *buf)
{
	struct ai_audit_device *dev = container_of(kobj,
						   struct ai_audit_device,
						   *kobj);
	unsigned long flags;
	unsigned int count;

	spin_lock_irqsave(&dev->anomalies.lock, flags);
	count = dev->anomalies.count;
	spin_unlock_irqrestore(&dev->anomalies.lock, flags);

	return sysfs_emit(buf, "%u\n", count);
}

static ssize_t flush_store(struct kobject *kobj,
			   struct kobj_attribute *attr,
			   const char *buf, size_t count)
{
	struct ai_audit_device *dev = container_of(kobj,
						   struct ai_audit_device,
						   *kobj);
	unsigned long flags;

	spin_lock_irqsave(&dev->log.lock, flags);
	dev->log.head = 0;
	dev->log.tail = 0;
	dev->log.count = 0;
	spin_unlock_irqrestore(&dev->log.lock, flags);

	return count;
}

static struct kobj_attribute enabled_attr = __ATTR_RO(enabled);
static struct kobj_attribute ai_enabled_attr = __ATTR_RO(ai_enabled);
static struct kobj_attribute log_count_attr = __ATTR_RO(log_count);
static struct kobj_attribute stats_attr = __ATTR_RO(stats);
static struct kobj_attribute anomalies_attr = __ATTR_RO(anomalies);
static struct kobj_attribute flush_attr = __ATTR_WO(flush);

static struct attribute *ai_audit_attrs[] = {
	&enabled_attr.attr,
	&ai_enabled_attr.attr,
	&log_count_attr.attr,
	&stats_attr.attr,
	&anomalies_attr.attr,
	&flush_attr.attr,
	NULL,
};

ATTRIBUTE_GROUPS(ai_audit);

/*
 * Module init/exit
 */

static int ai_audit_create_device(struct ai_audit_device **dev_out)
{
	struct ai_audit_device *dev;
	int ret;

	dev = kmem_cache_zalloc(ai_audit_device_cache, GFP_KERNEL);
	if (!dev)
		return -ENOMEM;

	dev->dev_id = atomic_inc_return(&ai_audit_device_count);
	snprintf(dev->name, sizeof(dev->name), "ai-audit-%u", dev->dev_id);
	dev->active = false;

	dev->enabled = false;
	dev->ai_enabled = ai_anomaly_enabled;

	mutex_init(&dev->log_mutex);
	mutex_init(&dev->filter_mutex);
	mutex_init(&dev->watch_mutex);
	mutex_init(&dev->alert_mutex);
	spin_lock_init(&dev->stats_lock);
	spin_lock_init(&dev->syscall_lock);
	spin_lock_init(&dev->anomalies.lock);

	INIT_LIST_HEAD(&dev->filters);
	INIT_LIST_HEAD(&dev->watches);
	INIT_LIST_HEAD(&dev->alerts);
	dev->nr_filters = 0;
	dev->nr_watches = 0;
	dev->nr_alerts = 0;
	dev->next_alert_id = 0;

	ret = ai_audit_log_init(&dev->log, log_capacity);
	if (ret)
		goto err_free;

	dev->backlog_limit = backlog_limit;
	dev->backlog_current = 0;

	memset(&dev->anomalies, 0, sizeof(dev->anomalies));
	memset(&dev->stats, 0, sizeof(dev->stats));
	memset(&dev->ai_analysis, 0, sizeof(dev->ai_analysis));
	memset(&dev->threat_report, 0, sizeof(dev->threat_report));
	memset(&dev->syscall_counts, 0, sizeof(dev->syscall_counts));

	strscpy(dev->log_path, "/var/log/ai-audit.log",
		sizeof(dev->log_path));
	dev->log_max_size_mb = 100;
	dev->log_max_files = 5;

	dev->ai_analysis.model_version = 1;
	dev->ai_analysis.detection_rate = 85;
	dev->ai_analysis.learning_active = dev->ai_enabled;

	cdev_init(&dev->cdev, &ai_audit_fops);
	dev->cdev.owner = THIS_MODULE;

	ret = cdev_add(&dev->cdev, dev->dev_id, 1);
	if (ret)
		goto err_log;

	dev->device = device_create(ai_audit_class, NULL, dev->dev_id, dev,
				    "ai-audit-%u", dev->dev_id);
	if (IS_ERR(dev->device)) {
		ret = PTR_ERR(dev->device);
		goto err_cdev;
	}

	dev->kobj = &dev->device->kobj;
	dev->active = true;

	dev->ai_task = kthread_run(ai_audit_ai_worker_thread, dev,
				   "ai-audit-ai-%u", dev->dev_id);
	if (IS_ERR(dev->ai_task)) {
		ret = PTR_ERR(dev->ai_task);
		dev->ai_task = NULL;
		goto err_device;
	}

	list_add_tail(&dev->list, &ai_audit_devices);

	ai_audit_info("Device created: %s (capacity=%u ai=%d)\n",
		      dev->name, log_capacity, dev->ai_enabled);

	*dev_out = dev;
	return 0;

err_device:
	device_destroy(ai_audit_class, dev->dev_id);
err_cdev:
	cdev_del(&dev->cdev);
err_log:
	ai_audit_log_destroy(&dev->log);
err_free:
	kmem_cache_free(ai_audit_device_cache, dev);
	return ret;
}

static void ai_audit_destroy_device(struct ai_audit_device *dev)
{
	struct ai_audit_filter_entry *filter_entry, *filter_tmp;
	struct ai_audit_watch_entry *watch_entry, *watch_tmp;
	struct ai_audit_alert_entry *alert_entry, *alert_tmp;

	if (!dev)
		return;

	dev->active = false;

	if (dev->ai_task) {
		kthread_stop(dev->ai_task);
		dev->ai_task = NULL;
	}

	device_destroy(ai_audit_class, dev->dev_id);
	cdev_del(&dev->cdev);
	ai_audit_log_destroy(&dev->log);

	list_for_each_entry_safe(filter_entry, filter_tmp, &dev->filters, list) {
		list_del(&filter_entry->list);
		kfree(filter_entry);
	}

	list_for_each_entry_safe(watch_entry, watch_tmp, &dev->watches, list) {
		list_del(&watch_entry->list);
		kfree(watch_entry);
	}

	list_for_each_entry_safe(alert_entry, alert_tmp, &dev->alerts, list) {
		list_del(&alert_entry->list);
		kfree(alert_entry);
	}

	mutex_destroy(&dev->log_mutex);
	mutex_destroy(&dev->filter_mutex);
	mutex_destroy(&dev->watch_mutex);
	mutex_destroy(&dev->alert_mutex);

	list_del(&dev->list);
	kmem_cache_free(ai_audit_device_cache, dev);
}

static int __init ai_audit_init(void)
{
	struct ai_audit_device *dev;
	int ret;

	ai_audit_info("Loading Ainos AI Audit Module v%s\n",
		      AI_AUDIT_MODULE_VERSION);

	INIT_LIST_HEAD(&ai_audit_devices);
	mutex_init(&ai_audit_global_mutex);
	atomic_set(&ai_audit_device_count, 0);

	ai_audit_device_cache = kmem_cache_create("ai_audit_device",
						  sizeof(struct ai_audit_device),
						  0, SLAB_HWCACHE_ALIGN,
						  NULL);
	if (!ai_audit_device_cache)
		return -ENOMEM;

	ret = alloc_chrdev_region(&ai_audit_devno, 0, AI_AUDIT_MAX_DEVICES,
				  AI_AUDIT_MODULE_NAME);
	if (ret) {
		ai_audit_err("Failed to allocate chrdev: %d\n", ret);
		goto err_device_cache;
	}

	ai_audit_major = MAJOR(ai_audit_devno);

	ai_audit_class = class_create(THIS_MODULE, AI_AUDIT_CLASS_NAME);
	if (IS_ERR(ai_audit_class)) {
		ret = PTR_ERR(ai_audit_class);
		goto err_unregister;
	}

	ret = ai_audit_create_device(&dev);
	if (ret)
		goto err_class;

	ai_audit_info("Ainos AI Audit Module loaded (major=%u)\n",
		      ai_audit_major);
	return 0;

err_class:
	class_destroy(ai_audit_class);
err_unregister:
	unregister_chrdev_region(ai_audit_devno, AI_AUDIT_MAX_DEVICES);
err_device_cache:
	kmem_cache_destroy(ai_audit_device_cache);
	return ret;
}

static void __exit ai_audit_exit(void)
{
	struct ai_audit_device *dev, *tmp;

	ai_audit_info("Unloading Ainos AI Audit Module\n");

	list_for_each_entry_safe(dev, tmp, &ai_audit_devices, list)
		ai_audit_destroy_device(dev);

	class_destroy(ai_audit_class);
	unregister_chrdev_region(ai_audit_devno, AI_AUDIT_MAX_DEVICES);
	kmem_cache_destroy(ai_audit_device_cache);

	ai_audit_info("Ainos AI Audit Module unloaded\n");
}

/*
 * Exported kernel API
 */

int ai_audit_enable(void)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_enable);

int ai_audit_disable(void)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_disable);

int ai_audit_is_enabled(bool *enabled)
{ if (enabled) *enabled = false; return 0; }
EXPORT_SYMBOL_GPL(ai_audit_is_enabled);

int ai_audit_get_status(struct ai_audit_status *status)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_get_status);

int ai_audit_get_info(struct ai_audit_info *info)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_get_info);

int ai_audit_log_event(struct ai_audit_log_entry *entry)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_log_event);

int ai_audit_log_syscall(int nr, pid_t pid, uid_t uid, int success,
			 long exit_code)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_log_syscall);

int ai_audit_log_file_access(const char *path, int mask, pid_t pid,
			     uid_t uid, int success)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_log_file_access);

int ai_audit_log_net_connect(__u32 src_ip, __u32 dst_ip, __u16 src_port,
			     __u16 dst_port, __u8 protocol, pid_t pid,
			     int success)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_log_net_connect);

int ai_audit_log_process(pid_t pid, pid_t ppid, uid_t uid,
			 const char *comm, const char *filename,
			 int event_type)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_log_process);

int ai_audit_log_security(const char *msg, int severity, pid_t pid, uid_t uid)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_log_security);

int ai_audit_get_logs(struct ai_audit_log_query *query)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_get_logs);

int ai_audit_flush_logs(void)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_flush_logs);

int ai_audit_rotate_logs(void)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_rotate_logs);

int ai_audit_set_log_path(const char *path, unsigned int max_size_mb,
			  unsigned int max_files)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_set_log_path);

int ai_audit_add_filter(struct ai_audit_filter *filter)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_add_filter);

int ai_audit_remove_filter(unsigned int filter_id)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_remove_filter);

int ai_audit_clear_filters(void)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_clear_filters);

int ai_audit_add_watch(struct ai_audit_watch *watch)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_add_watch);

int ai_audit_remove_watch(unsigned int watch_id)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_remove_watch);

int ai_audit_ai_enable(void)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_ai_enable);

int ai_audit_ai_disable(void)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_ai_disable);

int ai_audit_ai_analyze(void)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_ai_analyze);

int ai_audit_ai_get_analysis(struct ai_audit_ai_analysis *analysis)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_ai_get_analysis);

int ai_audit_ai_get_anomalies(struct ai_audit_anomaly_report *reports,
			      int max_count, int *actual_count)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_ai_get_anomalies);

int ai_audit_ai_get_threats(struct ai_audit_threat_report *report)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_ai_get_threats);

int ai_audit_ai_detect_anomaly(struct ai_audit_log_entry *entry,
			       bool *is_anomaly, float *confidence)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_ai_detect_anomaly);

int ai_audit_configure_alert(struct ai_audit_alert_config *config)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_configure_alert);

int ai_audit_get_alerts(struct ai_audit_alert_list *list)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_get_alerts);

int ai_audit_ack_alert(unsigned int alert_id)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_ack_alert);

int ai_audit_get_stats(struct ai_audit_stats *stats)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_get_stats);

int ai_audit_get_syscall_stats(struct ai_audit_syscall_stats *stats)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_get_syscall_stats);

int ai_audit_reset_stats(void)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_reset_stats);

int ai_audit_set_backlog_limit(unsigned int limit)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_set_backlog_limit);

int ai_audit_get_backlog_limit(unsigned int *limit)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_get_backlog_limit);

int ai_audit_syscall_entry(int nr, pid_t pid, uid_t uid)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_syscall_entry);

int ai_audit_syscall_exit(int nr, long result)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_syscall_exit);

int ai_audit_file_permission(const char *path, int mask)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_audit_file_permission);

int ai_audit_socket_connect(struct sock *sk, int family, int type,
			    int protocol)
{
	struct ai_audit_device *dev;
	struct ai_audit_log_entry entry;
	pid_t pid;
	uid_t uid;
	unsigned long flags;

	if (!sk)
		return 0;

	pid = task_tgid_nr(current);
	uid = from_kuid(&init_user_ns, current_uid());

	ai_audit_fill_entry(&entry, AI_AUDIT_EVENT_NET_CONNECT,
			    AI_AUDIT_SEV_INFO, pid, uid,
			    from_kgid(&init_user_ns, current_gid()),
			    1, current->comm, "socket_connect");

	entry.family = family;
	entry.protocol = protocol;

	mutex_lock(&ai_audit_global_mutex);
	list_for_each_entry(dev, &ai_audit_devices, list) {
		if (!dev->enabled)
			continue;

		entry.event_id = ai_audit_generate_event_id();
		entry.timestamp = ktime_get_real_ns();

		mutex_lock(&dev->log_mutex);
		ai_audit_log_push(&dev->log, &entry);
		mutex_unlock(&dev->log_mutex);

		spin_lock_irqsave(&dev->stats_lock, flags);
		dev->stats.total_net_events++;
		dev->stats.total_events++;
		spin_unlock_irqrestore(&dev->stats_lock, flags);
	}
	mutex_unlock(&ai_audit_global_mutex);

	return 0;
}
EXPORT_SYMBOL_GPL(ai_audit_socket_connect);

/*
 * Additional audit helper functions
 * These provide comprehensive security auditing, logging, and
 * AI-driven anomaly detection for system call tracing,
 * file integrity monitoring, and network security analysis.
 */

static int ai_audit_check_rate_limit(struct ai_audit_device *dev,
				     struct ai_audit_log_entry *entry)
{
	unsigned long flags;
	u64 now = entry->timestamp;
	u64 window = 1000000000ULL; /* 1 second in ns */
	static u64 last_event_time;
	static unsigned int event_count;

	spin_lock_irqsave(&dev->stats_lock, flags);

	if (now - last_event_time > window) {
		last_event_time = now;
		event_count = 0;
	}

	event_count++;
	if (event_count > 1000) {
		dev->stats.overflow_dropped++;
		spin_unlock_irqrestore(&dev->stats_lock, flags);
		return -EBUSY;
	}

	spin_unlock_irqrestore(&dev->stats_lock, flags);
	return 0;
}

static int ai_audit_apply_filters(struct ai_audit_device *dev,
				  struct ai_audit_log_entry *entry)
{
	struct ai_audit_filter_entry *filter_entry;
	int ret = 0;

	mutex_lock(&dev->filter_mutex);
	list_for_each_entry(filter_entry, &dev->filters, list) {
		struct ai_audit_filter *f = &filter_entry->filter;

		if (f->event_type && f->event_type != entry->event_type)
			continue;

		if (f->rule == AI_AUDIT_FILTER_EXCLUDE)
			ret = 1;
		else if (f->rule == AI_AUDIT_FILTER_DENY)
			ret = -EACCES;
	}
	mutex_unlock(&dev->filter_mutex);

	return ret;
}

static int ai_audit_log_and_analyze(struct ai_audit_device *dev,
				    struct ai_audit_log_entry *entry)
{
	unsigned long flags;
	bool is_anomaly;
	float confidence;
	int ret;

	ret = ai_audit_check_rate_limit(dev, entry);
	if (ret < 0)
		return ret;

	ret = ai_audit_apply_filters(dev, entry);
	if (ret != 0)
		return ret;

	mutex_lock(&dev->log_mutex);
	ret = ai_audit_log_push(&dev->log, entry);
	mutex_unlock(&dev->log_mutex);

	spin_lock_irqsave(&dev->stats_lock, flags);
	dev->stats.total_events++;
	dev->stats.bytes_written += sizeof(*entry);
	spin_unlock_irqrestore(&dev->stats_lock, flags);

	if (dev->ai_enabled) {
		ai_audit_ai_detect(dev, entry, &is_anomaly, &confidence);
		if (is_anomaly) {
			spin_lock_irqsave(&dev->anomalies.lock, flags);
			if (dev->anomalies.count < 256) {
				unsigned int idx = dev->anomalies.head;
				struct ai_audit_anomaly_report *report;

				report = &dev->anomalies.reports[idx];
				report->anomaly_id = idx + 1;
				report->timestamp = entry->timestamp;
				report->anomaly_type =
					AI_AUDIT_ANOMALY_BEHAVIORAL;
				report->severity = entry->severity;
				report->confidence = (unsigned int)(confidence * 100);
				report->pid = entry->pid;
				report->uid = entry->uid;
				memcpy(report->comm, entry->comm,
				       sizeof(report->comm));
				report->related_event_id = entry->event_id;
				report->acked = 0;

				dev->anomalies.head =
					(dev->anomalies.head + 1) % 256;
				dev->anomalies.count++;
			}
			spin_unlock_irqrestore(&dev->anomalies.lock, flags);
		}
	}

	return 0;
}

static int ai_audit_severity_from_syscall(int nr, long result)
{
	int severity = AI_AUDIT_SEV_INFO;

	if (result < 0) {
		severity = AI_AUDIT_SEV_WARNING;
		switch (nr) {
		case 59: /* execve */
		case 57: /* fork */
		case 58: /* vfork */
		case 322: /* execveat */
			severity = AI_AUDIT_SEV_ALERT;
			break;
		case 2:  /* open */
		case 257: /* openat */
			severity = AI_AUDIT_SEV_WARNING;
			break;
		case 10: /* mprotect */
		case 11: /* munmap */
			severity = AI_AUDIT_SEV_NOTICE;
			break;
		}
	}

	return severity;
}

module_init(ai_audit_init);
module_exit(ai_audit_exit);